"""
API contract and intermediate data schema tests for the MLB scoreboard.

These tests document what the MLB Stats API is expected to return and how
parse_games() transforms it into games.json. When the API changes year-over-year,
these tests fail at the exact field that changed, making the breakage visible.

Sections:
  1.  Extended wildcard derivation tests
  2.  Wildcard header rendering smoke tests
  3.  Standings sidebar movement indicator tests
  4.  games.json intermediate schema validation
  5.  standings.json intermediate schema validation
  6.  parse_games() API contract tests (mock API responses)
  7.  Save situation detection (inning + run differential)
  8.  WBC abbreviation override pipeline
  9.  MLB API field structure documentation tests
"""

import json
import os
import re
import pytest
from unittest.mock import patch

# conftest.py adds src/ to sys.path and os.chdir(project_root)
from generate_image import (
    derive_wildcard_from_standings,
    draw_wildcard_header,
    draw_standings_sidebar,
)
from fetch_games import parse_games, _WBC_ABBR_OVERRIDES, _PRE_GAME_STATES

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')


# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------

def _has_dark_pixels(image, x1, y1, x2, y2):
    """Return True if any pixel in region [x1:x2, y1:y2] is black (<128)."""
    region = image.crop((x1, y1, x2, y2)).convert('L')
    return any(p < 128 for p in region.getdata())


def _make_team(team_id, div_rank, league_rank, wins=80, losses=60,
               wc_gb='-', name='Test Team'):
    """Build a minimal standings team dict matching the standings.json schema."""
    return {
        'team_id': team_id,
        'team_name': name,
        'divisionRank': str(div_rank),
        'league_rank': str(league_rank),
        'league_record_wins': wins,
        'league_record_losses': losses,
        'league_record_percent': '.500',
        'games_back': '-',
        'last_ten_wins': 5,
        'last_ten_losses': 5,
        'streak': 'W1',
        'wild_card_games_back': wc_gb,
        'home_wins': 40,
        'home_losses': 30,
        'away_wins': 40,
        'away_losses': 30,
        'league_games_back': '-',
        'sport_rank': '5',
        'games_played': 140,
    }


def _make_standings_data(al_teams=None, nl_teams=None, abbr_map=None):
    """Build a standings_data dict with all 6 division keys."""
    al_teams = al_teams or {}
    nl_teams = nl_teams or {}
    standings = {}
    for div, teams in {**al_teams, **nl_teams}.items():
        standings[div] = teams
    for div in [
        'American League East', 'American League Central', 'American League West',
        'National League East', 'National League Central', 'National League West',
    ]:
        standings.setdefault(div, [])
    return {
        'standings': standings,
        'team_abbreviation': abbr_map or {},
    }


def _minimal_game_api(
    game_pk=745123,
    away_abbr='BOS', away_id=111,
    home_abbr='BAL', home_id=110,
    state='Scheduled',
    current_inning=None,
    inning_state=None,
    away_runs=None,
    home_runs=None,
):
    """Build a minimal MLB schedule API game object for use in parse_games() tests."""
    ls_away = {}
    ls_home = {}
    if away_runs is not None:
        ls_away['runs'] = away_runs
    if home_runs is not None:
        ls_home['runs'] = home_runs
    return {
        'gamePk': game_pk,
        'status': {'detailedState': state, 'reason': None},
        'teams': {
            'away': {
                'team': {'id': away_id, 'name': 'Boston Red Sox', 'abbreviation': away_abbr},
                'leagueRecord': {'wins': 10, 'losses': 8},
                'isWinner': None,
                'probablePitcher': {},
                'seriesNumber': 1,
            },
            'home': {
                'team': {'id': home_id, 'name': 'Baltimore Orioles', 'abbreviation': home_abbr},
                'leagueRecord': {'wins': 12, 'losses': 6},
                'isWinner': None,
                'probablePitcher': {},
                'seriesNumber': 1,
            },
        },
        'linescore': {
            'currentInning': current_inning,
            'currentInningOrdinal': None,
            'inningState': inning_state,
            'outs': None,
            'balls': None,
            'strikes': None,
            'teams': {'away': ls_away, 'home': ls_home},
            'innings': [],
            'offense': {},
            'defense': {'pitcher': {}},
        },
        'decisions': {},
        'flags': {'noHitter': False, 'perfectGame': False},
        'venue': {'id': 2, 'name': 'Oriole Park at Camden Yards'},
        'broadcasts': [
            {'type': 'TV', 'callSign': 'MASN', 'homeAway': 'home'},
        ],
        'doubleHeader': 'N',
        'seriesDescription': 'Regular Season',
        'dayNight': 'night',
        'description': None,
        'gameNumber': 1,
        'gamesInSeries': 3,
        'gameDate': '2026-04-25T23:05:00Z',
        'seriesStatus': {
            'gameNumber': 1,
            'totalGames': 3,
            'isTied': False,
            'isOver': False,
            'wins': 0,
            'losses': 0,
            'result': '',
            'shortDescription': 'Season',
        },
    }


def _parse(api_games, sport_id=1, config=None):
    """Run parse_games() with I/O mocked; return list of parsed game dicts."""
    captured = {}

    def fake_save(data, name):
        captured[name] = data

    schedule_data = {'dates': [{'games': api_games}]}
    if config is None:
        config = {'timezone': 'America/Chicago'}

    with patch('fetch_games.save_off_results', side_effect=fake_save), \
         patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
         patch('fetch_games._attach_pregame_weather'), \
         patch('fetch_games.fetch_win_probability', return_value=(None, None, None, None, None, None, None)):
        parse_games(schedule_data, sport_id=sport_id, config=config)

    return captured.get('games', {}).get('games', [])


# ===========================================================================
# 1. EXTENDED WILDCARD DERIVATION TESTS
# ===========================================================================

class TestDeriveWildcardExpanded:
    """Extended coverage for derive_wildcard_from_standings()."""

    def test_gb_field_populated_from_wild_card_games_back(self):
        """The 'gb' field in wildcard entries comes from the team's wild_card_games_back."""
        data = _make_standings_data(
            al_teams={'American League East': [_make_team(1, 2, 2, wc_gb='+1.5')]},
            abbr_map={'1': 'NYY'},
        )
        result = derive_wildcard_from_standings(data)
        assert result['AL'][0]['gb'] == '+1.5'

    def test_gb_defaults_to_dash_when_field_missing(self):
        """If wild_card_games_back is absent from the team dict, 'gb' defaults to '-'."""
        team = _make_team(1, 2, 2)
        team.pop('wild_card_games_back')
        data = _make_standings_data(
            al_teams={'American League East': [team]},
            abbr_map={'1': 'NYY'},
        )
        result = derive_wildcard_from_standings(data)
        assert result['AL'][0]['gb'] == '-'

    def test_gb_none_value_becomes_dash(self):
        """wild_card_games_back=None must produce 'gb': '-'."""
        data = _make_standings_data(
            al_teams={'American League East': [_make_team(1, 2, 2, wc_gb=None)]},
            abbr_map={'1': 'NYY'},
        )
        result = derive_wildcard_from_standings(data)
        assert result['AL'][0]['gb'] == '-'

    def test_fallback_abbr_from_team_name_first_three_chars(self):
        """When team_id is not in abbr_map, use team_name[:3].upper() as abbreviation."""
        data = _make_standings_data(
            al_teams={'American League East': [
                _make_team(999, 2, 2, name='Houston Astros'),
            ]},
            abbr_map={},
        )
        result = derive_wildcard_from_standings(data)
        assert result['AL'][0]['abbr'] == 'HOU'

    def test_fallback_abbr_uppercased(self):
        """Fallback abbreviation from team_name must always be uppercased."""
        data = _make_standings_data(
            al_teams={'American League East': [
                _make_team(999, 2, 2, name='boston red sox'),
            ]},
            abbr_map={},
        )
        result = derive_wildcard_from_standings(data)
        assert result['AL'][0]['abbr'] == 'BOS'

    def test_non_integer_league_rank_sorts_last(self):
        """Teams with non-parseable league_rank (e.g. 'N/A') should sort to the end."""
        bad_rank = _make_team(1, 2, 'N/A')
        good_rank = _make_team(2, 3, 5)
        data = _make_standings_data(
            al_teams={'American League East': [bad_rank, good_rank]},
            abbr_map={'1': 'AAA', '2': 'BBB'},
        )
        result = derive_wildcard_from_standings(data)
        abbrs = [t['abbr'] for t in result['AL']]
        assert abbrs.index('BBB') < abbrs.index('AAA'), "Valid rank should precede bad rank"

    def test_empty_string_league_rank_sorts_last(self):
        """Empty string league_rank should also sort last (treated as 999)."""
        empty_rank = _make_team(1, 2, '')
        normal_rank = _make_team(2, 3, 3)
        data = _make_standings_data(
            al_teams={'American League East': [empty_rank, normal_rank]},
            abbr_map={'1': 'AAA', '2': 'BBB'},
        )
        result = derive_wildcard_from_standings(data)
        assert result['AL'][0]['abbr'] == 'BBB'

    def test_division_leader_excluded_others_included(self):
        """In a 5-team division, only the 4 non-leaders appear in wildcard results."""
        teams = [_make_team(i, i, i + 1) for i in range(1, 6)]
        data = _make_standings_data(
            al_teams={'American League East': teams},
            abbr_map={str(i): f'T{i:02d}' for i in range(1, 6)},
        )
        result = derive_wildcard_from_standings(data)
        abbrs = [t['abbr'] for t in result['AL']]
        assert 'T01' not in abbrs, "divisionRank='1' team must be excluded"
        assert len(abbrs) == 4

    def test_max_12_wildcard_per_league(self):
        """Each league can have at most 12 wildcard-eligible teams (15 - 3 division leaders)."""
        al_divs = {}
        for i, div in enumerate([
            'American League East', 'American League Central', 'American League West'
        ]):
            base_id = i * 5 + 1
            al_divs[div] = [_make_team(base_id + j, j + 1, base_id + j) for j in range(5)]
        data = _make_standings_data(al_teams=al_divs)
        result = derive_wildcard_from_standings(data)
        assert len(result['AL']) <= 12

    def test_team_id_is_string_in_result(self):
        """Each wildcard entry must have a string team_id field."""
        data = _make_standings_data(
            al_teams={'American League East': [_make_team(147, 2, 2)]},
            abbr_map={'147': 'NYY'},
        )
        result = derive_wildcard_from_standings(data)
        assert isinstance(result['AL'][0]['team_id'], str)
        assert result['AL'][0]['team_id'] == '147'

    def test_nl_three_divisions_all_contribute(self):
        """All three NL divisions must contribute teams to the NL wildcard list."""
        nl_divs = {
            'National League East': [_make_team(10, 2, 4)],
            'National League Central': [_make_team(11, 2, 2)],
            'National League West': [_make_team(12, 2, 6)],
        }
        data = _make_standings_data(
            nl_teams=nl_divs,
            abbr_map={'10': 'PHI', '11': 'CHC', '12': 'SDP'},
        )
        result = derive_wildcard_from_standings(data)
        abbrs = {t['abbr'] for t in result['NL']}
        assert abbrs == {'PHI', 'CHC', 'SDP'}

    def test_result_sorted_by_league_rank_ascending(self):
        """Teams in each league must be sorted by league_rank ascending (rank 1 first)."""
        al_teams = {
            'American League East': [
                _make_team(10, 2, 5),
                _make_team(11, 3, 3),
            ],
            'American League Central': [_make_team(12, 2, 1)],
            'American League West': [],
        }
        data = _make_standings_data(
            al_teams=al_teams,
            abbr_map={'10': 'TEA', '11': 'TEB', '12': 'TEC'},
        )
        result = derive_wildcard_from_standings(data)
        abbrs = [t['abbr'] for t in result['AL']]
        assert abbrs == ['TEC', 'TEB', 'TEA'], "Must be sorted by league_rank ascending"

    def test_wildcard_with_live_standings_file(self):
        """Smoke test: should not crash on live data/standings.json and produce valid output."""
        path = os.path.join(DATA_DIR, 'standings.json')
        if not os.path.exists(path):
            pytest.skip("data/standings.json not available")
        with open(path) as f:
            data = json.load(f)
        result = derive_wildcard_from_standings(data)
        assert 'AL' in result
        assert 'NL' in result
        for teams in result.values():
            for t in teams:
                assert 'abbr' in t
                assert 'team_id' in t
                assert 'gb' in t
                assert isinstance(t['abbr'], str)
                assert len(t['abbr']) >= 2


# ===========================================================================
# 2. WILDCARD HEADER RENDERING SMOKE TESTS
# ===========================================================================

@needs_pil
class TestDrawWildcardHeaderSmoke:
    """draw_wildcard_header() must not crash and must render in the expected locations."""

    # _WC_BOX_X_START=32, _WC_BOX_X_END=767, _WC_STRIP_H=30
    _AL_LEFT_REGION  = (32, 0, 200, 30)
    _NL_RIGHT_REGION = (600, 0, 767, 30)
    _AL_BOX_TOP      = (32, 1, 104, 3)  # top edge of 3-team AL wildcard box (3 * 24 = 72 wide)

    def _blank(self):
        return Image.new('1', (800, 480), 255)

    def test_empty_wildcard_dict_no_crash(self):
        draw_wildcard_header(self._blank(), {})

    def test_empty_al_nl_lists_no_crash(self):
        draw_wildcard_header(self._blank(), {'AL': [], 'NL': []})

    def test_one_al_team_no_crash(self):
        draw_wildcard_header(self._blank(), {
            'AL': [{'abbr': 'NYY', 'team_id': '999', 'gb': '-'}],
            'NL': [],
        })

    def test_one_nl_team_no_crash(self):
        draw_wildcard_header(self._blank(), {
            'AL': [],
            'NL': [{'abbr': 'LAD', 'team_id': '998', 'gb': '-'}],
        })

    def test_max_twelve_teams_per_league_no_crash(self):
        al = [{'abbr': f'A{i:02d}', 'team_id': str(i), 'gb': '-'} for i in range(12)]
        nl = [{'abbr': f'N{i:02d}', 'team_id': str(100 + i), 'gb': '-'} for i in range(12)]
        draw_wildcard_header(self._blank(), {'AL': al, 'NL': nl})

    def test_al_team_draws_pixels_in_left_region(self):
        """AL rank-1 team slot starts at x=32; pixels must appear in the left strip."""
        img = self._blank()
        draw_wildcard_header(img, {
            'AL': [{'abbr': 'NYY', 'team_id': '999', 'gb': '-'}],
            'NL': [],
        })
        assert _has_dark_pixels(img, *self._AL_LEFT_REGION), \
            "AL team should render text/logo in left portion of the wildcard strip"

    def test_nl_team_draws_pixels_in_right_region(self):
        """NL rank-1 team slot ends at x=767; pixels must appear in the right strip."""
        img = self._blank()
        draw_wildcard_header(img, {
            'AL': [],
            'NL': [{'abbr': 'LAD', 'team_id': '998', 'gb': '-'}],
        })
        assert _has_dark_pixels(img, *self._NL_RIGHT_REGION), \
            "NL team should render text/logo in right portion of the wildcard strip"

    def test_al_box_drawn_around_top_3(self):
        """A bounding box must be drawn around the top-3 AL wildcard teams."""
        img = self._blank()
        draw_wildcard_header(img, {
            'AL': [{'abbr': f'A{i}', 'team_id': str(i), 'gb': '-'} for i in range(3)],
            'NL': [],
        })
        # Box top border at y=1, x=[32..104] (3 slots * 24px wide = 72px)
        assert _has_dark_pixels(img, *self._AL_BOX_TOP), \
            "Wildcard box top border should be visible at y≈1 for 3 AL teams"

    def test_returns_same_image_object(self):
        """draw_wildcard_header() must return the same image it was passed."""
        img = self._blank()
        result = draw_wildcard_header(img, {'AL': [], 'NL': []})
        assert result is img

    def test_missing_abbr_key_no_crash(self):
        """Entry with no 'abbr' key must not crash (uses '???' fallback)."""
        draw_wildcard_header(self._blank(), {
            'AL': [{'team_id': '999', 'gb': '-'}],
            'NL': [],
        })

    def test_al_and_nl_both_render_simultaneously(self):
        """Both AL and NL teams must render without interfering."""
        img = self._blank()
        draw_wildcard_header(img, {
            'AL': [{'abbr': 'NYY', 'team_id': '999', 'gb': '-'}],
            'NL': [{'abbr': 'LAD', 'team_id': '998', 'gb': '-'}],
        })
        assert _has_dark_pixels(img, *self._AL_LEFT_REGION)
        assert _has_dark_pixels(img, *self._NL_RIGHT_REGION)


# ===========================================================================
# 3. STANDINGS SIDEBAR MOVEMENT INDICATOR TESTS
# ===========================================================================

@needs_pil
class TestStandingsSidebarMovers:
    """Movement indicator line logic in draw_standings_sidebar().

    Indicator line: x=2 (logo_x=6 - 4), width=2 for left sidebar — drawn on the
    outer (left) edge of the logo column, between the screen edge and the logo.
    Check region: (2, 25, 4, 480) — the full indicator column, clear of logos/text.
    """

    _INDICATOR_REGION = (2, 25, 4, 480)

    def _blank(self):
        return Image.new('1', (800, 480), 255)

    def _render(self, cur_teams, prev_teams=None, abbr_map=None):
        """Render the left sidebar (AL East first) and return the image."""
        standings_data = {
            'standings': {
                'American League East': cur_teams,
                'American League Central': [],
                'American League West': [],
            },
            'team_abbreviation': abbr_map or {},
        }
        team_data = {'team_abbreviation': abbr_map or {}}

        prev_data = None
        if prev_teams is not None:
            prev_data = {
                'standings': {
                    'American League East': prev_teams,
                    'American League Central': [],
                    'American League West': [],
                }
            }

        def fake_load(fname):
            if fname == 'standings_prev.json' and prev_data is not None:
                return prev_data
            return {}

        img = self._blank()
        with patch('image_standings.load_json_file', side_effect=fake_load), \
             patch('image_standings.save_off_results'):
            draw_standings_sidebar(img, standings_data, team_data, side='left')
        return img

    def test_no_previous_data_means_no_indicators(self):
        """When standings_prev.json is absent, no mover lines should be drawn."""
        teams = [
            _make_team(1, 1, 1, wins=15, losses=5),
            _make_team(2, 2, 3, wins=12, losses=8),
        ]
        img = self._render(teams, prev_teams=None)
        assert not _has_dark_pixels(img, *self._INDICATOR_REGION), \
            "No mover lines should appear when there is no previous standings data"

    def test_mover_gets_indicator_when_rank_and_record_changed(self):
        """A team that changed both rank and record must receive an indicator line."""
        # Team 1: was rank 2 (wins=14), now rank 1 (wins=15) — genuine mover
        # Team 2: was rank 1 (losses=7), now rank 2 (losses=8) — genuine mover
        cur_teams = [
            _make_team(1, 1, 1, wins=15, losses=5),
            _make_team(2, 2, 3, wins=12, losses=8),
        ]
        prev_teams = [
            _make_team(1, 2, 2, wins=14, losses=5),
            _make_team(2, 1, 1, wins=12, losses=7),
        ]
        img = self._render(cur_teams, prev_teams=prev_teams,
                           abbr_map={'1': 'NYY', '2': 'BOS'})
        assert _has_dark_pixels(img, *self._INDICATOR_REGION), \
            "Mover teams should each receive an indicator line in the sidebar"

    def test_api_tiebreak_no_indicator_when_only_rank_changed(self):
        """Rank changed but record identical (API tiebreak reorder) must not produce an indicator."""
        # Use unequal records so no tied-team --- dashes land in the indicator region.
        # Each team's own record is unchanged; only their relative ranking swapped.
        cur_teams = [
            _make_team(1, 1, 1, wins=12, losses=8),
            _make_team(2, 2, 3, wins=11, losses=9),
        ]
        prev_teams = [
            _make_team(1, 2, 2, wins=12, losses=8),
            _make_team(2, 1, 1, wins=11, losses=9),
        ]
        img = self._render(cur_teams, prev_teams=prev_teams,
                           abbr_map={'1': 'NYY', '2': 'BOS'})
        assert not _has_dark_pixels(img, *self._INDICATOR_REGION), \
            "Pure API tiebreak reorders (record unchanged) must not show movement indicators"

    def test_displaced_team_also_gets_indicator(self):
        """A team displaced by a mover also gets an indicator even if its own record didn't change."""
        # Team 1 won a game (wins 13→14) and jumped from rank 2 to rank 1.
        # Team 2 was rank 1 but got pushed down — its own record didn't change.
        cur_teams = [
            _make_team(1, 1, 1, wins=14, losses=6),
            _make_team(2, 2, 3, wins=13, losses=6),
        ]
        prev_teams = [
            _make_team(1, 2, 2, wins=13, losses=6),
            _make_team(2, 1, 1, wins=13, losses=6),
        ]
        img = self._render(cur_teams, prev_teams=prev_teams,
                           abbr_map={'1': 'NYY', '2': 'BOS'})
        assert _has_dark_pixels(img, *self._INDICATOR_REGION), \
            "Both the mover and the displaced team should have indicator lines"

    def test_unchanged_teams_produce_no_indicator(self):
        """Teams with identical rank and record produce no indicator."""
        # Use distinct records to avoid tied-team --- dashes appearing in the indicator region.
        teams = [
            _make_team(1, 1, 1, wins=12, losses=8),
            _make_team(2, 2, 2, wins=10, losses=10),
            _make_team(3, 3, 3, wins=8, losses=12),
        ]
        img = self._render(teams, prev_teams=teams[:])
        assert not _has_dark_pixels(img, *self._INDICATOR_REGION)

    def test_sidebar_returns_image_object(self):
        """draw_standings_sidebar() must return the modified image."""
        data = {'standings': {d: [] for d in [
            'American League East', 'American League Central', 'American League West',
        ]}, 'team_abbreviation': {}}
        img = self._blank()
        with patch('image_standings.load_json_file', return_value={}), \
             patch('image_standings.save_off_results'):
            result = draw_standings_sidebar(img, data, {}, side='left')
        assert result is img

    def test_right_sidebar_no_crash(self):
        """draw_standings_sidebar with side='right' should not crash."""
        data = {'standings': {d: [] for d in [
            'National League East', 'National League Central', 'National League West',
        ]}, 'team_abbreviation': {}}
        img = self._blank()
        with patch('image_standings.load_json_file', return_value={}), \
             patch('image_standings.save_off_results'):
            draw_standings_sidebar(img, data, {}, side='right')


# ===========================================================================
# 4. games.json INTERMEDIATE SCHEMA VALIDATION
# ===========================================================================

_GAME_FIELD_TYPES = {
    'game_pk':                 (int,),
    'detailed_state':          (str,),
    'game_date':               (str,),
    'game_start':              (str,),
    'away_team_id':            (int, type(None)),
    'home_team_id':            (int, type(None)),
    'away_team_name':          (str, type(None)),
    'home_team_name':          (str, type(None)),
    'away_runs':               (int, type(None)),
    'home_runs':               (int, type(None)),
    'away_hits':               (int, type(None)),
    'home_hits':               (int, type(None)),
    'away_errors':             (int, type(None)),
    'home_errors':             (int, type(None)),
    'no_hitter':               (bool, type(None)),
    'perfect_game':            (bool, type(None)),
    'current_inning':          (int, type(None)),
    'inningState':             (str, type(None)),
    'away_inning_runs':        (list,),
    'home_inning_runs':        (list,),
    'save_situation':          (bool,),
    'walk_off':                (bool,),
    'tv_channel':              (str, type(None)),
    'num_of_outs':             (int, type(None)),
    'balls':                   (int, type(None)),
    'strikes':                 (int, type(None)),
    'away_team_record_wins':   (int, type(None)),
    'away_team_record_losses': (int, type(None)),
    'home_team_record_wins':   (int, type(None)),
    'home_team_record_losses': (int, type(None)),
    'venue':                   (str, type(None)),
    'double_header':           (str, type(None)),
    'game_number':             (int, type(None)),
    'day_night':               (str, type(None)),
}

# Fields added via seriesStatus hydration — present in fresh parse_games() output
# but may be absent from older cached games.json files.
_SERIES_FIELD_TYPES = {
    'series_result':      (str, type(None)),
    'series_game_number': (int, type(None)),
    'series_total_games': (int, type(None)),
    'series_wins':        (int, type(None)),
    'series_losses':      (int, type(None)),
    'series_is_tied':     (bool, type(None)),
    'series_is_over':     (bool, type(None)),
}

# States observed in the wild from the MLB Stats API
_KNOWN_MLB_STATES = {
    'Scheduled', 'Pre-Game', 'Warmup', 'In Progress',
    'Final', 'Game Over', 'Final: Tied',
    'Postponed', 'Suspended', 'Cancelled',
    'Delayed', 'Delayed Start',
    'Completed Early',
    'Player Challenge', 'Manager Challenge',
}

_ISO_PATTERN  = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
_TIME_PATTERN = re.compile(r'^\d{1,2}:\d{2} (AM|PM)$')


class TestGamesJsonSchema:
    """Validate the intermediate games.json file against the expected schema.

    These tests use the live data/games.json so they run against real data.
    They will catch any API field renames or type changes on the next fetch.
    """

    @pytest.fixture(scope='class')
    def games(self):
        path = os.path.join(DATA_DIR, 'games.json')
        if not os.path.exists(path):
            pytest.skip("data/games.json not available")
        with open(path) as f:
            data = json.load(f)
        return data.get('games', [])

    def test_top_level_structure(self):
        """games.json must have a 'games' key containing a list."""
        path = os.path.join(DATA_DIR, 'games.json')
        if not os.path.exists(path):
            pytest.skip("data/games.json not available")
        with open(path) as f:
            data = json.load(f)
        assert 'games' in data, "games.json top level must have a 'games' key"
        assert isinstance(data['games'], list)

    def test_required_fields_present_in_every_game(self, games):
        """Every game dict must contain all documented required fields."""
        for idx, game in enumerate(games):
            for field in _GAME_FIELD_TYPES:
                assert field in game, (
                    f"Game[{idx}] (pk={game.get('game_pk')}) is missing required field '{field}'. "
                    f"If the API renamed this field, update parse_games() and this test together."
                )

    def test_field_types_match_contract(self, games):
        """Every field must have the documented type (or None if nullable)."""
        for idx, game in enumerate(games):
            for field, allowed_types in _GAME_FIELD_TYPES.items():
                value = game.get(field)
                assert isinstance(value, allowed_types), (
                    f"Game[{idx}] (pk={game.get('game_pk')}) field '{field}': "
                    f"expected one of {[t.__name__ for t in allowed_types]}, "
                    f"got {type(value).__name__} = {value!r}"
                )

    def test_inning_runs_are_always_lists(self, games):
        """away_inning_runs and home_inning_runs must always be lists, never None."""
        for idx, game in enumerate(games):
            for key in ('away_inning_runs', 'home_inning_runs'):
                assert isinstance(game[key], list), (
                    f"Game[{idx}] (pk={game.get('game_pk')}) "
                    f"'{key}' must be a list, got {type(game[key]).__name__}"
                )

    def test_save_situation_is_python_bool(self, games):
        """save_situation must be a Python bool, not int 0/1."""
        for idx, game in enumerate(games):
            val = game['save_situation']
            assert type(val) is bool, (
                f"Game[{idx}] save_situation={val!r} is {type(val).__name__}, not bool. "
                "API change may have altered the detection logic."
            )

    def test_game_pk_unique_within_file(self, games):
        """No two games should have the same game_pk."""
        pks = [g['game_pk'] for g in games]
        assert len(pks) == len(set(pks)), "Duplicate game_pk values in games.json"

    def test_detailed_state_is_known_value(self, games):
        """detailed_state must be a recognized MLB API state string.

        Failure here means a new state appeared in the API — add it to _KNOWN_MLB_STATES
        and decide whether generate_image.py needs to handle it.
        """
        for idx, game in enumerate(games):
            state = game.get('detailed_state', '')
            assert state in _KNOWN_MLB_STATES, (
                f"Game[{idx}] (pk={game.get('game_pk')}) has unrecognized state: {state!r}. "
                f"Add to _KNOWN_MLB_STATES if this is a real MLB API state."
            )

    def test_game_date_is_iso_format(self, games):
        """game_date must match ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ."""
        for idx, game in enumerate(games):
            date_str = game.get('game_date', '')
            assert _ISO_PATTERN.match(date_str), (
                f"Game[{idx}] game_date='{date_str}' does not match ISO 8601 format. "
                "If the API changed the date format, update convert_time_z_to() and this test."
            )

    def test_game_start_is_localized_time(self, games):
        """game_start must be a localized time string like '7:05 PM' or '12:30 PM'."""
        for idx, game in enumerate(games):
            start_str = game.get('game_start', '')
            assert _TIME_PATTERN.match(start_str), (
                f"Game[{idx}] game_start='{start_str}' does not match 'H:MM AM/PM' format"
            )

    def test_scheduled_games_have_null_runs(self, games):
        """Scheduled/Pre-Game/Warmup games must have null run totals."""
        pre_game_states = {'Scheduled', 'Pre-Game', 'Warmup'}
        for idx, game in enumerate(games):
            if game['detailed_state'] in pre_game_states:
                assert game['away_runs'] is None, (
                    f"Game[{idx}] away_runs should be null for {game['detailed_state']}"
                )
                assert game['home_runs'] is None, (
                    f"Game[{idx}] home_runs should be null for {game['detailed_state']}"
                )

    def test_final_games_have_integer_runs(self, games):
        """Final/Game Over games must have integer run totals."""
        final_states = {'Final', 'Game Over', 'Final: Tied'}
        for idx, game in enumerate(games):
            if game['detailed_state'] in final_states:
                assert isinstance(game['away_runs'], int), (
                    f"Game[{idx}] away_runs should be int for {game['detailed_state']}"
                )
                assert isinstance(game['home_runs'], int), (
                    f"Game[{idx}] home_runs should be int for {game['detailed_state']}"
                )

    def test_team_ids_are_integers_not_strings(self, games):
        """away_team_id and home_team_id must be Python ints, not strings."""
        for idx, game in enumerate(games):
            for key in ('away_team_id', 'home_team_id'):
                val = game.get(key)
                if val is not None:
                    assert type(val) is int, (
                        f"Game[{idx}] {key}={val!r} is {type(val).__name__}, expected int"
                    )


# ===========================================================================
# 5. standings.json INTERMEDIATE SCHEMA VALIDATION
# ===========================================================================

_STANDINGS_TEAM_FIELD_TYPES = {
    'team_name':              (str,),
    'team_id':                (int,),
    'divisionRank':           (str,),
    'league_record_wins':     (int,),
    'league_record_losses':   (int,),
    'league_record_percent':  (str,),
    'games_back':             (str,),
    'last_ten_wins':          (int,),
    'last_ten_losses':        (int,),
    'streak':                 (str,),
    'wild_card_games_back':   (str,),
    'league_rank':            (str,),
}

_EXPECTED_DIVISIONS = {
    'American League East', 'American League Central', 'American League West',
    'National League East', 'National League Central', 'National League West',
}

_GB_PATTERN      = re.compile(r'^(-|\d+(\.\d+)?)$')
_PCT_PATTERN     = re.compile(r'^\.\d{3}$')
_STREAK_PATTERN  = re.compile(r'^[WL]\d+$')


class TestStandingsJsonSchema:
    """Validate the intermediate standings.json file against the expected schema."""

    @pytest.fixture(scope='class')
    def standings_data(self):
        path = os.path.join(DATA_DIR, 'standings.json')
        if not os.path.exists(path):
            pytest.skip("data/standings.json not available")
        with open(path) as f:
            return json.load(f)

    def test_top_level_keys(self, standings_data):
        """standings.json must have 'standings' and 'team_abbreviation' at the top level."""
        assert 'standings' in standings_data
        assert 'team_abbreviation' in standings_data

    def test_standings_value_is_dict(self, standings_data):
        assert isinstance(standings_data['standings'], dict)

    def test_team_abbreviation_maps_string_to_string(self, standings_data):
        """team_abbreviation must map string team_id keys to string abbreviation values."""
        abbr = standings_data['team_abbreviation']
        assert isinstance(abbr, dict)
        for key, val in abbr.items():
            assert isinstance(key, str), f"team_abbreviation key {key!r} should be str"
            assert isinstance(val, str), f"team_abbreviation value {val!r} should be str"

    def test_all_six_divisions_present(self, standings_data):
        """All 6 MLB divisions must appear as keys in the 'standings' dict."""
        present = set(standings_data['standings'].keys())
        missing = _EXPECTED_DIVISIONS - present
        assert not missing, (
            f"Missing divisions: {missing}. "
            "If the API renamed a division, update _EXPECTED_DIVISIONS and the standings fetch."
        )

    def test_required_fields_in_every_team(self, standings_data):
        """Every team entry must have all required fields with correct types."""
        for div_name, teams in standings_data['standings'].items():
            for idx, team in enumerate(teams):
                for field, allowed_types in _STANDINGS_TEAM_FIELD_TYPES.items():
                    assert field in team, (
                        f"Division '{div_name}' team[{idx}] missing field '{field}'. "
                        f"If the API dropped this field, update fetch_standings and this test."
                    )
                    value = team[field]
                    assert isinstance(value, allowed_types), (
                        f"Division '{div_name}' team[{idx}] '{field}': "
                        f"expected {[t.__name__ for t in allowed_types]}, "
                        f"got {type(value).__name__} = {value!r}"
                    )

    def test_division_rank_is_digit_string_1_to_5(self, standings_data):
        """divisionRank must be a digit string in range '1'..'5'."""
        for div_name, teams in standings_data['standings'].items():
            for team in teams:
                rank = team.get('divisionRank', '')
                assert rank.isdigit() and 1 <= int(rank) <= 5, (
                    f"Division '{div_name}' team '{team.get('team_name')}' "
                    f"has unexpected divisionRank: {rank!r}"
                )

    def test_league_rank_is_integer_string(self, standings_data):
        """league_rank must be parseable as an integer (e.g. '1', '15')."""
        for div_name, teams in standings_data['standings'].items():
            for team in teams:
                rank = team.get('league_rank', '')
                try:
                    int(rank)
                except (ValueError, TypeError):
                    pytest.fail(
                        f"Division '{div_name}' team '{team.get('team_name')}' "
                        f"has non-integer league_rank: {rank!r}. "
                        "If the API changed this field, update derive_wildcard_from_standings()."
                    )

    def test_streak_format_is_w_or_l_followed_by_digits(self, standings_data):
        """Streak must match 'W{n}' or 'L{n}' format (e.g. 'W3', 'L1')."""
        for div_name, teams in standings_data['standings'].items():
            for team in teams:
                streak = team.get('streak', '')
                assert _STREAK_PATTERN.match(streak), (
                    f"Division '{div_name}' team '{team.get('team_name')}' "
                    f"has unexpected streak format: {streak!r}"
                )

    def test_games_back_format(self, standings_data):
        """games_back must be '-' (division leader) or a numeric string like '1.5'."""
        for div_name, teams in standings_data['standings'].items():
            for team in teams:
                gb = team.get('games_back', '')
                assert _GB_PATTERN.match(str(gb)), (
                    f"Division '{div_name}' team '{team.get('team_name')}' "
                    f"has unexpected games_back: {gb!r}"
                )

    def test_record_percent_format(self, standings_data):
        """league_record_percent must be a '.NNN' decimal string."""
        for div_name, teams in standings_data['standings'].items():
            for team in teams:
                pct = team.get('league_record_percent', '')
                assert _PCT_PATTERN.match(pct), (
                    f"Division '{div_name}' team '{team.get('team_name')}' "
                    f"has unexpected league_record_percent: {pct!r}"
                )

    def test_each_division_has_at_most_five_teams(self, standings_data):
        """Each division must have ≤5 teams."""
        for div_name, teams in standings_data['standings'].items():
            assert len(teams) <= 5, (
                f"Division '{div_name}' has {len(teams)} teams (max 5)"
            )

    def test_team_id_is_integer(self, standings_data):
        """team_id in each standings entry must be an int, not a string."""
        for div_name, teams in standings_data['standings'].items():
            for team in teams:
                tid = team.get('team_id')
                assert isinstance(tid, int), (
                    f"Division '{div_name}' team '{team.get('team_name')}' "
                    f"team_id={tid!r} should be int, got {type(tid).__name__}"
                )

    def test_division_leader_has_games_back_dash(self, standings_data):
        """The team with divisionRank='1' must have games_back='-'."""
        for div_name, teams in standings_data['standings'].items():
            for team in teams:
                if team.get('divisionRank') == '1':
                    assert team.get('games_back') == '-', (
                        f"Division leader in '{div_name}' should have games_back='-', "
                        f"got {team.get('games_back')!r}"
                    )


# ===========================================================================
# 6. parse_games() API CONTRACT TESTS
# ===========================================================================

class TestParseGamesContract:
    """Mock the MLB schedule API and verify parse_games() output structure."""

    def test_scheduled_game_has_all_required_fields(self):
        """A standard scheduled game must produce a dict with all required fields."""
        games = _parse([_minimal_game_api(state='Scheduled')])
        assert len(games) == 1
        game = games[0]
        for field in {**_GAME_FIELD_TYPES, **_SERIES_FIELD_TYPES}:
            assert field in game, f"Parsed game missing required field '{field}'"

    def test_game_pk_matches_api_value(self):
        """game_pk in output must exactly match gamePk from the API response."""
        games = _parse([_minimal_game_api(game_pk=999888)])
        assert games[0]['game_pk'] == 999888

    def test_away_team_id_extracted_correctly(self):
        """away_team_id must come from teams.away.team.id in the API response."""
        games = _parse([_minimal_game_api(away_id=111)])
        assert games[0]['away_team_id'] == 111

    def test_home_team_id_extracted_correctly(self):
        """home_team_id must come from teams.home.team.id in the API response."""
        games = _parse([_minimal_game_api(home_id=110)])
        assert games[0]['home_team_id'] == 110

    def test_team_ids_are_python_ints(self):
        """Team IDs must be Python ints, not strings or other types."""
        games = _parse([_minimal_game_api(away_id=111, home_id=110)])
        assert type(games[0]['away_team_id']) is int
        assert type(games[0]['home_team_id']) is int

    def test_game_date_iso_format(self):
        """game_date must preserve the raw ISO datetime string from the API."""
        games = _parse([_minimal_game_api()])
        assert _ISO_PATTERN.match(games[0]['game_date']), (
            f"game_date '{games[0]['game_date']}' should match ISO 8601 format"
        )

    def test_game_start_localized_time_format(self):
        """game_start must be converted to localized time like '6:05 PM'."""
        games = _parse([_minimal_game_api()])
        assert _TIME_PATTERN.match(games[0]['game_start']), (
            f"game_start '{games[0]['game_start']}' should match 'H:MM AM/PM' format"
        )

    def test_tv_channel_home_broadcast_returned(self):
        """TV channel must be extracted from the home broadcast entry."""
        games = _parse([_minimal_game_api()])
        assert games[0]['tv_channel'] == 'MASN'

    def test_tv_channel_none_when_only_radio_broadcasts(self):
        """tv_channel must be None when no TV-type broadcasts exist."""
        api_game = _minimal_game_api()
        api_game['broadcasts'] = [{'type': 'Radio', 'callSign': 'WBAL', 'homeAway': 'home'}]
        games = _parse([api_game])
        assert games[0]['tv_channel'] is None

    def test_no_hitter_flag_extracted(self):
        """no_hitter must reflect flags.noHitter from the API."""
        api_game = _minimal_game_api()
        api_game['flags']['noHitter'] = True
        games = _parse([api_game])
        assert games[0]['no_hitter'] is True

    def test_perfect_game_flag_extracted(self):
        """perfect_game must reflect flags.perfectGame from the API."""
        api_game = _minimal_game_api()
        api_game['flags']['perfectGame'] = True
        games = _parse([api_game])
        assert games[0]['perfect_game'] is True

    def test_scheduled_game_null_runs(self):
        """Scheduled games have no linescore runs; away_runs and home_runs must be None."""
        games = _parse([_minimal_game_api(state='Scheduled')])
        assert games[0]['away_runs'] is None
        assert games[0]['home_runs'] is None

    def test_final_game_runs_extracted(self):
        """Final game linescore runs must be extracted to away_runs/home_runs."""
        api_game = _minimal_game_api(state='Final', away_runs=3, home_runs=5)
        games = _parse([api_game])
        assert games[0]['away_runs'] == 3
        assert games[0]['home_runs'] == 5

    def test_scheduled_game_empty_inning_runs(self):
        """Scheduled games have no innings — away_inning_runs/home_inning_runs must be []."""
        games = _parse([_minimal_game_api(state='Scheduled')])
        assert games[0]['away_inning_runs'] == []
        assert games[0]['home_inning_runs'] == []

    def test_inning_runs_extracted_from_linescore(self):
        """Linescore innings array must be mapped into per-inning run lists."""
        api_game = _minimal_game_api(state='Final', away_runs=3, home_runs=2)
        api_game['linescore']['innings'] = [
            {'away': {'runs': 1}, 'home': {'runs': 0}},
            {'away': {'runs': 2}, 'home': {'runs': 2}},
        ]
        games = _parse([api_game])
        assert games[0]['away_inning_runs'] == [1, 2]
        assert games[0]['home_inning_runs'] == [0, 2]

    def test_team_win_loss_records_extracted(self):
        """Win/loss records must be extracted from leagueRecord in the API response."""
        games = _parse([_minimal_game_api()])
        assert games[0]['away_team_record_wins'] == 10
        assert games[0]['away_team_record_losses'] == 8
        assert games[0]['home_team_record_wins'] == 12
        assert games[0]['home_team_record_losses'] == 6

    def test_save_situation_is_bool_type(self):
        """save_situation must be a Python bool (not int 0/1)."""
        games = _parse([_minimal_game_api(state='Scheduled')])
        assert type(games[0]['save_situation']) is bool

    def test_double_header_extracted(self):
        """double_header must match the 'doubleHeader' field in the API."""
        games = _parse([_minimal_game_api()])
        assert games[0]['double_header'] == 'N'

    def test_multiple_games_all_parsed(self):
        """All games in the API dates list must appear in the output."""
        api_games = [_minimal_game_api(game_pk=i) for i in range(5)]
        games = _parse(api_games)
        assert len(games) == 5

    def test_empty_dates_list_produces_empty_games(self):
        """API response with no dates must produce an empty games list without crashing."""
        captured = {}

        def fake_save(data, name):
            captured[name] = data

        with patch('fetch_games.save_off_results', side_effect=fake_save), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}):
            parse_games({'dates': []}, sport_id=1, config={'timezone': 'America/Chicago'})

        assert captured.get('games', {}).get('games', []) == []

    def test_empty_games_in_date_produces_empty_output(self):
        """A dates entry with an empty games list must produce an empty games list."""
        captured = {}

        def fake_save(data, name):
            captured[name] = data

        with patch('fetch_games.save_off_results', side_effect=fake_save), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}):
            parse_games({'dates': [{'games': []}]}, sport_id=1,
                        config={'timezone': 'America/Chicago'})

        assert captured.get('games', {}).get('games', []) == []

    def test_team_abbreviations_written_to_teams_output(self):
        """Team abbreviations must be saved to teams.json (via save_off_results('teams', ...))."""
        captured = {}

        def fake_save(data, name):
            captured[name] = data

        data = {'dates': [{'games': [_minimal_game_api(away_abbr='BOS', away_id=111,
                                                        home_abbr='BAL', home_id=110)]}]}
        with patch('fetch_games.save_off_results', side_effect=fake_save), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games._attach_pregame_weather'), \
             patch('fetch_games.fetch_win_probability', return_value=(None, None, None, None, None, None, None)):
            parse_games(data, sport_id=1, config={'timezone': 'America/Chicago'})

        teams = captured.get('teams', {}).get('team_abbreviation', {})
        assert teams.get('111') == 'BOS', f"Expected BOS for id 111, got: {teams}"
        assert teams.get('110') == 'BAL', f"Expected BAL for id 110, got: {teams}"

    def test_favorite_team_tv_prioritized(self):
        """When config has 'primary' matching the away team, their local broadcast is shown."""
        api_game = _minimal_game_api()
        api_game['broadcasts'] = [
            {'type': 'TV', 'callSign': 'NESN',  'homeAway': 'away'},  # BOS local
            {'type': 'TV', 'callSign': 'MASN',  'homeAway': 'home'},  # BAL local
        ]
        games = _parse([api_game], config={'timezone': 'America/Chicago', 'primary': 'BOS'})
        assert games[0]['tv_channel'] == 'NESN', \
            "Favorite team's local broadcast should be preferred"


# ===========================================================================
# 7. SAVE SITUATION DETECTION
# ===========================================================================

class TestSaveSituationDetectionViaApi:
    """Verify save_situation flag logic: inning >= 7 AND 1 <= run_diff <= 3."""

    def _ip_game(self, current_inning, away_runs, home_runs, game_pk=12345):
        """In-progress game with given inning and run totals."""
        return _minimal_game_api(
            game_pk=game_pk,
            state='In Progress',
            current_inning=current_inning,
            inning_state='Top',
            away_runs=away_runs,
            home_runs=home_runs,
        )

    def _flag(self, current_inning, away_runs, home_runs):
        return _parse([self._ip_game(current_inning, away_runs, home_runs)])[0]['save_situation']

    def test_inning_7_diff_1_is_save(self):
        assert self._flag(7, 5, 4) is True

    def test_inning_7_diff_3_is_save(self):
        assert self._flag(7, 7, 4) is True

    def test_inning_9_diff_2_is_save(self):
        assert self._flag(9, 6, 4) is True

    def test_extra_innings_diff_1_is_save(self):
        assert self._flag(11, 5, 4) is True

    def test_tied_game_is_not_save(self):
        """Tied game (diff=0) is not a save situation."""
        assert self._flag(8, 4, 4) is False

    def test_diff_4_is_not_save(self):
        """Run diff=4 is not a save situation (must be 1-3)."""
        assert self._flag(8, 8, 4) is False

    def test_early_inning_6_is_not_save(self):
        """Inning 6 is not a save situation (must be >= 7)."""
        assert self._flag(6, 5, 4) is False

    def test_away_team_leading_also_detected(self):
        """Save situation applies regardless of which team leads."""
        assert self._flag(7, 5, 3) is True   # away leads 5-3

    def test_scheduled_game_never_save(self):
        assert _parse([_minimal_game_api(state='Scheduled')])[0]['save_situation'] is False

    def test_final_game_not_save(self):
        api_game = _minimal_game_api(state='Final', away_runs=5, home_runs=4)
        assert _parse([api_game])[0]['save_situation'] is False

    def test_inning_7_diff_4_not_save(self):
        """Boundary: diff=4 in inning 7 is not a save situation."""
        assert self._flag(7, 8, 4) is False

    def test_inning_7_diff_3_leading_home(self):
        """Home team leading by 3 in inning 7 is a save situation."""
        assert self._flag(7, 4, 7) is True


# ===========================================================================
# 8. WBC ABBREVIATION OVERRIDE PIPELINE
# ===========================================================================

class TestWbcAbbreviationOverride:
    """Verify WBC abbreviation collision fixes flow through parse_games()."""

    def _parse_wbc(self, away_abbr, away_id, home_abbr='DOM', home_id=9000):
        """Run parse_games() with sport_id=8 (WBC) and capture teams output."""
        captured = {}

        def fake_save(data, name):
            captured[name] = data

        api_game = _minimal_game_api(
            away_abbr=away_abbr, away_id=away_id,
            home_abbr=home_abbr, home_id=home_id,
        )
        data = {'dates': [{'games': [api_game]}]}
        with patch('fetch_games.save_off_results', side_effect=fake_save), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games._attach_pregame_weather'), \
             patch('fetch_games.fetch_win_probability', return_value=(None, None, None, None, None, None, None)):
            parse_games(data, sport_id=8, config={'timezone': 'America/Chicago'})

        return captured.get('teams', {}).get('team_abbreviation', {})

    def test_wbc_override_dict_has_colombia_mapping(self):
        """_WBC_ABBR_OVERRIDES must map COL → CLM for the Colombia collision fix."""
        assert 'COL' in _WBC_ABBR_OVERRIDES
        assert _WBC_ABBR_OVERRIDES['COL'] == 'CLM'

    def test_colombia_away_col_becomes_clm_in_wbc(self):
        """Colombia away team abbreviation (COL) must be remapped to CLM for WBC."""
        teams = self._parse_wbc(away_abbr='COL', away_id=9901)
        assert teams.get('9901') == 'CLM', (
            f"Expected 'CLM' for Colombia WBC away team, got: {teams.get('9901')!r}"
        )

    def test_colombia_home_col_becomes_clm_in_wbc(self):
        """Colombia home team abbreviation (COL) must also be remapped to CLM for WBC."""
        captured = {}

        def fake_save(data, name):
            captured[name] = data

        api_game = _minimal_game_api(home_abbr='COL', home_id=9902)
        data = {'dates': [{'games': [api_game]}]}
        with patch('fetch_games.save_off_results', side_effect=fake_save), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games._attach_pregame_weather'), \
             patch('fetch_games.fetch_win_probability', return_value=(None, None, None, None, None, None, None)):
            parse_games(data, sport_id=8, config={'timezone': 'America/Chicago'})

        teams = captured.get('teams', {}).get('team_abbreviation', {})
        assert teams.get('9902') == 'CLM', (
            f"Expected 'CLM' for Colombia WBC home team, got: {teams.get('9902')!r}"
        )

    def test_colorado_col_unchanged_for_mlb(self):
        """Colorado Rockies (COL) must NOT be remapped when sport_id=1 (MLB)."""
        captured = {}

        def fake_save(data, name):
            captured[name] = data

        api_game = _minimal_game_api(away_abbr='COL', away_id=115)
        data = {'dates': [{'games': [api_game]}]}
        with patch('fetch_games.save_off_results', side_effect=fake_save), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games._attach_pregame_weather'), \
             patch('fetch_games.fetch_win_probability', return_value=(None, None, None, None, None, None, None)):
            parse_games(data, sport_id=1, config={'timezone': 'America/Chicago'})

        teams = captured.get('teams', {}).get('team_abbreviation', {})
        assert teams.get('115') == 'COL', (
            f"Colorado Rockies should stay COL for MLB; got: {teams.get('115')!r}"
        )

    def test_pre_game_states_constant_covers_all_expected_states(self):
        """_PRE_GAME_STATES must include all states where games haven't started yet."""
        for state in ('Scheduled', 'Pre-Game', 'Warmup', 'Delayed Start'):
            assert state in _PRE_GAME_STATES, (
                f"'{state}' is missing from _PRE_GAME_STATES. "
                "Weather attachment and score suppression depend on this constant."
            )


# ===========================================================================
# 9. MLB API FIELD STRUCTURE DOCUMENTATION TESTS
# ===========================================================================

class TestMlbApiFieldContract:
    """
    Document and validate the expected nesting structure of the MLB Stats API response.

    Each test verifies a specific field path that parse_games() depends on.
    When the API changes a field name or restructures nesting, the broken test
    names the exact path that stopped working.
    """

    _GAME = _minimal_game_api()

    def test_game_pk_is_top_level_integer(self):
        """gamePk must be a top-level integer on each game object."""
        assert 'gamePk' in self._GAME
        assert isinstance(self._GAME['gamePk'], int)

    def test_status_contains_detailed_state(self):
        """detailedState must be at game.status.detailedState."""
        assert 'status' in self._GAME
        assert 'detailedState' in self._GAME['status']
        assert isinstance(self._GAME['status']['detailedState'], str)

    def test_teams_has_away_and_home(self):
        """game.teams must have 'away' and 'home' sub-dicts."""
        teams = self._GAME['teams']
        assert 'away' in teams
        assert 'home' in teams

    def test_team_id_at_teams_away_team_id(self):
        """Team ID path: game.teams.away.team.id (must be int)."""
        team_id = self._GAME['teams']['away']['team']['id']
        assert isinstance(team_id, int)

    def test_team_abbreviation_at_teams_away_team_abbreviation(self):
        """Abbreviation path: game.teams.away.team.abbreviation (must be str)."""
        abbr = self._GAME['teams']['away']['team']['abbreviation']
        assert isinstance(abbr, str)
        assert len(abbr) >= 2

    def test_league_record_at_teams_away_league_record(self):
        """Win/loss record path: game.teams.away.leagueRecord.{wins,losses}."""
        record = self._GAME['teams']['away']['leagueRecord']
        assert 'wins' in record
        assert 'losses' in record

    def test_linescore_is_top_level_on_game(self):
        """Linescore must be at game.linescore (not nested under teams)."""
        assert 'linescore' in self._GAME

    def test_linescore_has_current_inning(self):
        """game.linescore.currentInning must exist."""
        assert 'currentInning' in self._GAME['linescore']

    def test_linescore_has_inning_state(self):
        """game.linescore.inningState must exist."""
        assert 'inningState' in self._GAME['linescore']

    def test_linescore_teams_structure(self):
        """Linescore teams must have 'away' and 'home' sub-dicts."""
        ls_teams = self._GAME['linescore']['teams']
        assert 'away' in ls_teams
        assert 'home' in ls_teams

    def test_linescore_runs_at_linescore_teams_away_runs(self):
        """Run count path: game.linescore.teams.away.runs."""
        game = _minimal_game_api(away_runs=3)
        runs = game['linescore']['teams']['away'].get('runs')
        assert runs == 3

    def test_linescore_outs_balls_strikes_present(self):
        """game.linescore must have outs, balls, strikes fields."""
        ls = self._GAME['linescore']
        assert 'outs' in ls
        assert 'balls' in ls
        assert 'strikes' in ls

    def test_flags_contains_no_hitter_and_perfect_game(self):
        """game.flags must contain noHitter and perfectGame boolean fields."""
        assert 'flags' in self._GAME
        flags = self._GAME['flags']
        assert 'noHitter' in flags
        assert 'perfectGame' in flags

    def test_decisions_is_present(self):
        """game.decisions must be present (contains winner, loser, save)."""
        assert 'decisions' in self._GAME

    def test_broadcasts_is_list(self):
        """game.broadcasts must be a list (contains TV/radio broadcast dicts)."""
        assert 'broadcasts' in self._GAME
        assert isinstance(self._GAME['broadcasts'], list)

    def test_broadcast_entry_structure(self):
        """Each broadcast entry must have 'type', 'callSign', and 'homeAway' fields."""
        broadcasts = self._GAME['broadcasts']
        assert len(broadcasts) > 0
        b = broadcasts[0]
        assert 'type' in b
        assert 'callSign' in b or 'name' in b   # API uses either field
        assert 'homeAway' in b

    def test_schedule_response_has_dates_list(self):
        """Top-level schedule API response must have a 'dates' list."""
        response = {'dates': [{'games': [self._GAME]}]}
        assert isinstance(response['dates'], list)

    def test_dates_entry_has_games_list(self):
        """Each date entry in the schedule response must have a 'games' list."""
        response = {'dates': [{'games': [self._GAME]}]}
        assert isinstance(response['dates'][0]['games'], list)

    def test_innings_list_at_linescore_innings(self):
        """Linescore innings (per-inning scores) must be at game.linescore.innings."""
        assert 'innings' in self._GAME['linescore']
        assert isinstance(self._GAME['linescore']['innings'], list)

    def test_offense_at_linescore_offense(self):
        """Base runners path: game.linescore.offense.{first,second,third}."""
        assert 'offense' in self._GAME['linescore']

    def test_series_status_is_present(self):
        """game.seriesStatus must be present when seriesStatus hydration is used."""
        assert 'seriesStatus' in self._GAME

    def test_series_status_has_required_fields(self):
        """seriesStatus must have gameNumber, totalGames, wins, losses, isTied."""
        ss = self._GAME['seriesStatus']
        for field in ('gameNumber', 'totalGames', 'wins', 'losses', 'isTied'):
            assert field in ss, f"seriesStatus missing field: {field}"


# ===========================================================================
# Series record parse_games() contract
# ===========================================================================

class TestSeriesRecordParsing:
    """parse_games() must extract series status fields into game dicts."""

    def test_series_fields_present_in_output(self):
        """parse_games() output must include all series_* fields."""
        game = _minimal_game_api(1001, 'Final', 111, 147, 'BOS', 'BAL', away_runs=4, home_runs=3)
        games = _parse([game])
        g = games[0]
        for field in ('series_result', 'series_game_number', 'series_total_games',
                      'series_wins', 'series_losses', 'series_is_tied'):
            assert field in g, f"Missing field: {field}"

    def test_series_total_games_extracted(self):
        """series_total_games should match totalGames from seriesStatus."""
        game = _minimal_game_api(1001, 'Final', 111, 147, 'BOS', 'BAL', away_runs=4, home_runs=3)
        game['seriesStatus']['totalGames'] = 7
        games = _parse([game])
        assert games[0]['series_total_games'] == 7

    def test_series_tied_extracted(self):
        """series_is_tied must reflect isTied from the API."""
        game = _minimal_game_api(1001, 'Final', 111, 147, 'BOS', 'BAL', away_runs=4, home_runs=3)
        game['seriesStatus']['isTied'] = True
        game['seriesStatus']['wins'] = 1
        game['seriesStatus']['losses'] = 1
        games = _parse([game])
        assert games[0]['series_is_tied'] is True
        assert games[0]['series_wins'] == 1
