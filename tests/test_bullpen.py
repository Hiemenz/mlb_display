"""Tests for the bullpen-usage tiles: fetch_bullpen, image_bullpen, grid placement, main hook."""
import time
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

import fetch_bullpen
import image_bullpen
import main as main_mod

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason='PIL not installed')

TODAY = date(2026, 9, 29)
TEAMS = {'team_abbreviation': {'144': 'ATL', '121': 'NYM'}}


def _game(pk, away, home, state='Final'):
    return {'gamePk': pk, 'status': {'detailedState': state},
            'teams': {'away': {'team': {'id': away}}, 'home': {'team': {'id': home}}}}


def _side(team_id, pitchers):
    """pitchers: list of (id, full_name, pitches); first is the starter."""
    return {
        'team': {'id': team_id},
        'pitchers': [p[0] for p in pitchers],
        'players': {f'ID{pid}': {'person': {'fullName': name},
                                 'stats': {'pitching': {'numberOfPitches': n}}}
                    for pid, name, n in pitchers},
    }


def _box(away_side, home_side):
    return {'teams': {'away': away_side, 'home': home_side}}


def _roster(pitchers):
    """Build a fake /teams/{id}/roster response with the given list of (fullName,) tuples."""
    return {'roster': [
        {'person': {'fullName': name}, 'position': {'type': 'Pitcher'}}
        for name in pitchers
    ]}


def _router(schedules, boxes, rosters=None):
    """requests.get stand-in: schedule by (teamId, startDate), box by gamePk,
    roster by teamId (optional; returns empty roster when not provided)."""
    rosters = rosters or {}

    def fake_get(url, timeout=None):
        resp = MagicMock()
        if '/schedule' in url:
            team = int(url.split('teamId=')[1].split('&')[0])
            start = url.split('startDate=')[1].split('&')[0]
            resp.json.return_value = schedules[(team, start)]
        elif '/teams/' in url and '/roster' in url:
            tid = int(url.split('/teams/')[1].split('/')[0])
            resp.json.return_value = rosters.get(tid, {'roster': []})
        else:
            resp.json.return_value = boxes[int(url.split('/game/')[1].split('/')[0])]
        return resp
    return fake_get


def _fixture():
    """ATL faces NYM today; ATL played 9/28 (pk 1) and 9/26 (pk 2), NYM played 9/28 (pk 1)."""
    schedules = {
        (144, '2026-09-29'): {'dates': [{'date': '2026-09-29', 'games': [_game(9, 121, 144, 'Preview')]}]},
        (144, '2026-09-19'): {'dates': [
            {'date': '2026-09-26', 'games': [_game(2, 144, 121)]},
            {'date': '2026-09-27', 'games': [_game(3, 144, 121, 'Postponed')]},
            {'date': '2026-09-28', 'games': [_game(1, 144, 121)]},
        ]},
        (121, '2026-09-19'): {'dates': [{'date': '2026-09-28', 'games': [_game(1, 144, 121)]}]},
    }
    boxes = {
        1: _box(_side(144, [(1, 'Spencer Strider', 90), (2, 'Raisel Iglesias', 10), (3, 'A.J. Minter', 25)]),
                _side(121, [(4, 'Kodai Senga', 80), (5, 'Edwin Diaz', 14)])),
        2: _box(_side(144, [(1, 'Max Fried', 95), (2, 'Raisel Iglesias', 12), (6, 'Zero Pitches', 0)]),
                _side(121, [(4, 'Kodai Senga', 70)])),
    }
    return schedules, boxes


@pytest.fixture
def isolated(monkeypatch):
    """No cache on disk, teams.json stubbed, save captured."""
    saved = {}
    monkeypatch.setattr(fetch_bullpen, 'load_json_file',
                        lambda name: TEAMS if name == 'teams.json' else saved.get('bullpen', {}))
    monkeypatch.setattr(fetch_bullpen, 'save_off_results',
                        lambda data, name: saved.__setitem__(name, data))
    return saved


class TestFetchBullpen:
    def test_builds_primary_and_opponent_relievers(self, isolated):
        schedules, boxes = _fixture()
        with patch('fetch_bullpen.requests.get', _router(schedules, boxes)):
            data = fetch_bullpen.fetch_bullpen('ATL', today=TODAY)

        assert data['team_order'] == ['144', '121']
        atl = data['teams']['144']['pitchers']
        assert atl == [
            {'name': 'A. Minter', 'yesterday': 25, 'total': 25},
            {'name': 'R. Iglesias', 'yesterday': 10, 'total': 22},
        ]
        assert 'Z. Pitches' not in {p['name'] for p in atl}
        assert data['teams']['121']['pitchers'] == [
            {'name': 'E. Diaz', 'yesterday': 14, 'total': 14}]
        assert isolated['bullpen'] is data

    def test_starters_and_unfinished_games_excluded(self, isolated):
        schedules, boxes = _fixture()
        with patch('fetch_bullpen.requests.get', _router(schedules, boxes)):
            data = fetch_bullpen.fetch_bullpen('ATL', today=TODAY)
        names = {p['name'] for t in data['teams'].values() for p in t['pitchers']}
        assert not names & {'S. Strider', 'M. Fried', 'K. Senga'}

    def test_sorted_heaviest_first(self, isolated):
        schedules, boxes = _fixture()
        with patch('fetch_bullpen.requests.get', _router(schedules, boxes)):
            data = fetch_bullpen.fetch_bullpen('ATL', today=TODAY)
        totals = [p['total'] for p in data['teams']['144']['pitchers']]
        assert totals == sorted(totals, reverse=True)

    def test_no_game_today_gives_primary_only(self, isolated):
        schedules, boxes = _fixture()
        schedules[(144, '2026-09-29')] = {'dates': []}
        with patch('fetch_bullpen.requests.get', _router(schedules, boxes)):
            data = fetch_bullpen.fetch_bullpen('ATL', today=TODAY)
        assert data['team_order'] == ['144']

    def test_window_anchors_to_last_game_after_off_days(self, isolated):
        schedules, boxes = _fixture()
        schedules[(144, '2026-09-19')] = {'dates': [
            {'date': '2026-09-26', 'games': [_game(2, 144, 121)]}]}
        with patch('fetch_bullpen.requests.get', _router(schedules, boxes)):
            data = fetch_bullpen.fetch_bullpen('ATL', today=TODAY)
        assert data['teams']['144']['pitchers'] == [
            {'name': 'R. Iglesias', 'yesterday': 12, 'total': 12}]

    def test_unknown_team_returns_empty(self, isolated):
        assert fetch_bullpen.fetch_bullpen('ZZZ', today=TODAY) == {}
        assert fetch_bullpen.fetch_bullpen('', today=TODAY) == {}

    def test_fresh_cache_skips_network(self, isolated):
        cached = {'date': TODAY.isoformat(), 'primary': 'ATL', 'days': 3,
                  'fetched_at': time.time(), 'team_order': [], 'teams': {}}
        isolated['bullpen'] = cached
        with patch('fetch_bullpen.requests.get') as get:
            assert fetch_bullpen.fetch_bullpen('ATL', today=TODAY) is cached
        get.assert_not_called()

    @pytest.mark.parametrize('change', [
        {'date': '2026-09-28'}, {'primary': 'NYM'}, {'days': 5},
        {'fetched_at': 0},
    ])
    def test_stale_or_mismatched_cache_refetches(self, isolated, change):
        schedules, boxes = _fixture()
        isolated['bullpen'] = dict(
            {'date': TODAY.isoformat(), 'primary': 'ATL', 'days': 3,
             'fetched_at': time.time()}, **change)
        with patch('fetch_bullpen.requests.get', _router(schedules, boxes)):
            data = fetch_bullpen.fetch_bullpen('ATL', today=TODAY)
        assert data['primary'] == 'ATL' and data['teams']

    def test_force_refetches_despite_fresh_cache(self, isolated):
        schedules, boxes = _fixture()
        isolated['bullpen'] = {'date': TODAY.isoformat(), 'primary': 'ATL', 'days': 3,
                               'fetched_at': time.time()}
        with patch('fetch_bullpen.requests.get', _router(schedules, boxes)):
            data = fetch_bullpen.fetch_bullpen('ATL', force=True, today=TODAY)
        assert data['teams']

    def test_api_error_returns_cached(self, isolated):
        isolated['bullpen'] = {'stale': True}
        with patch('fetch_bullpen.requests.get', side_effect=RuntimeError('boom')):
            assert fetch_bullpen.fetch_bullpen('ATL', today=TODAY) == {'stale': True}

    def test_defaults_to_real_today(self, isolated):
        with patch('fetch_bullpen.requests.get', side_effect=RuntimeError('boom')):
            assert fetch_bullpen.fetch_bullpen('ATL') == {}


class TestHelpers:
    @pytest.mark.parametrize('full,short', [
        ('Bryce Elder', 'B. Elder'), ('Ronald Acuna Jr.', 'R. Acuna Jr.'),
        ('Ohtani', 'Ohtani'), ('', ''), (None, ''),
    ])
    def test_short_name(self, full, short):
        assert fetch_bullpen._short_name(full) == short

    def test_relief_lines_tolerates_missing_stats(self):
        side = {'pitchers': [1, 2, 3], 'players': {'ID2': {'person': {'fullName': 'A B'}}}}
        assert fetch_bullpen._relief_lines(side) == []

    def test_abbr_lookup_is_case_insensitive(self, isolated):
        assert fetch_bullpen._abbr_to_team_id('atl') == 144

    def test_roster_pitchers_returns_short_names(self):
        fake = MagicMock()
        fake.json.return_value = {'roster': [
            {'person': {'fullName': 'Joe Smith'}, 'position': {'type': 'Pitcher'}},
            {'person': {'fullName': 'Bob Batter'}, 'position': {'type': 'Outfielder'}},
            {'person': {'fullName': 'Ann Catcher'}, 'position': {'type': 'Catcher'}},
        ]}
        with patch('fetch_bullpen.requests.get', return_value=fake):
            result = fetch_bullpen._roster_pitchers(144)
        assert result == {'J. Smith'}

    def test_roster_pitchers_skips_missing_name(self):
        fake = MagicMock()
        fake.json.return_value = {'roster': [
            {'person': {'fullName': ''}, 'position': {'type': 'Pitcher'}},
            {'person': {}, 'position': {'type': 'Pitcher'}},
        ]}
        with patch('fetch_bullpen.requests.get', return_value=fake):
            result = fetch_bullpen._roster_pitchers(144)
        assert result == set()

    def test_roster_pitchers_returns_empty_on_error(self):
        with patch('fetch_bullpen.requests.get', side_effect=RuntimeError('boom')):
            assert fetch_bullpen._roster_pitchers(144) == set()


class TestRestedPitchers:
    """Rested roster pitchers (no pitches in the window) appear at the bottom."""

    def test_rested_pitchers_added_from_roster(self, isolated):
        """Pitchers on the active roster but silent during the look-back window are included."""
        schedules, boxes = _fixture()
        rosters = {
            144: _roster(['A.J. Minter', 'Raisel Iglesias', 'Chris Sale', 'Nate Elder']),
            121: _roster(['Edwin Diaz', 'Sean Reid-Foley']),
        }
        with patch('fetch_bullpen.requests.get', _router(schedules, boxes, rosters)):
            data = fetch_bullpen.fetch_bullpen('ATL', today=TODAY)

        atl_names = [p['name'] for p in data['teams']['144']['pitchers']]
        # Pitched in window — sorted heavy-first
        assert atl_names[:2] == ['A. Minter', 'R. Iglesias']
        # Rested roster pitchers appear after (alphabetical within the zero bucket)
        assert set(atl_names[2:]) == {'C. Sale', 'N. Elder'}

        # Rested pitchers have zero workload
        rested = [p for p in data['teams']['144']['pitchers'] if p['name'] in {'C. Sale', 'N. Elder'}]
        for p in rested:
            assert p['yesterday'] == 0
            assert p['total'] == 0

    def test_rested_pitchers_not_duplicated(self, isolated):
        """Pitchers already in usage are not added again."""
        schedules, boxes = _fixture()
        rosters = {144: _roster(['A.J. Minter']), 121: _roster([])}
        with patch('fetch_bullpen.requests.get', _router(schedules, boxes, rosters)):
            data = fetch_bullpen.fetch_bullpen('ATL', today=TODAY)
        # A. Minter pitched AND is on roster — must appear exactly once
        minter_rows = [p for p in data['teams']['144']['pitchers'] if p['name'] == 'A. Minter']
        assert len(minter_rows) == 1
        assert minter_rows[0]['total'] == 25  # pitched, not zeroed out

    def test_roster_error_does_not_break_fetch(self, isolated):
        """If roster API fails, workload fetch continues without rested pitchers."""
        schedules, boxes = _fixture()

        def bad_get(url, timeout=None):
            if '/roster' in url:
                raise RuntimeError('network error')
            return _router(schedules, boxes)(url, timeout)

        with patch('fetch_bullpen.requests.get', bad_get):
            data = fetch_bullpen.fetch_bullpen('ATL', today=TODAY)
        # Pitched-pitchers still present; no crash
        assert any(p['total'] > 0 for p in data['teams']['144']['pitchers'])


PITCHERS = [
    {'name': 'B. Suter', 'yesterday': 20, 'total': 43},
    {'name': 'D. Dodd', 'yesterday': 25, 'total': 25},
    {'name': 'D. Lee', 'yesterday': 0, 'total': 10},
    {'name': 'Way Over', 'yesterday': 60, 'total': 90},
]


@needs_pil
class TestDrawBullpenCell:
    def _ink(self, entry, days=3):
        img = Image.new('1', (200, 200), 255)
        image_bullpen.draw_bullpen_cell(img, 10, 10, entry, days=days)
        return img

    def test_draws_rows_into_cell_only(self):
        img = self._ink({'abbr': 'ATL', 'pitchers': PITCHERS})
        assert img.getbbox() is not None
        outside = img.crop((146, 0, 200, 200)).getextrema()
        assert outside == (255, 255)

    def test_more_pitchers_means_more_ink(self):
        few = self._ink({'abbr': 'ATL', 'pitchers': PITCHERS[:1]})
        many = self._ink({'abbr': 'ATL', 'pitchers': PITCHERS})
        assert list(many.getdata()).count(0) > list(few.getdata()).count(0)

    def test_rows_capped(self):
        many = [dict(PITCHERS[0], name=f'P. Arm{i}') for i in range(20)]
        capped = self._ink({'abbr': 'ATL', 'pitchers': many})
        exact = self._ink({'abbr': 'ATL', 'pitchers': many[:image_bullpen.MAX_ROWS]})
        assert list(capped.getdata()) == list(exact.getdata())

    def test_empty_bullpen_shows_message(self):
        img = self._ink({'abbr': 'ATL', 'pitchers': []})
        assert img.getbbox() is not None

    def test_missing_entry_does_not_crash(self):
        assert self._ink(None) is not None

    def test_bar_clamps_at_full_scale(self):
        img = Image.new('1', (100, 40), 255)
        from PIL import ImageDraw
        image_bullpen._draw_bar(ImageDraw.Draw(img), 5, 5, 60, 500, 900)
        assert img.crop((66, 0, 100, 40)).getextrema() == (255, 255)

    def test_rested_pitcher_shows_dash_not_zero(self):
        """A pitcher with total=0 gets a '–' label; the bar remains just an outline."""
        rested = [{'name': 'C. Sale', 'yesterday': 0, 'total': 0}]
        has_workload = [{'name': 'C. Sale', 'yesterday': 0, 'total': 1}]
        img_rested = self._ink({'abbr': 'ATL', 'pitchers': rested})
        img_nonzero = self._ink({'abbr': 'ATL', 'pitchers': has_workload})
        # The two renders differ (dash vs "1")
        assert list(img_rested.getdata()) != list(img_nonzero.getdata())


TEAM_DATA = {'team_abbreviation': {'147': 'NYY'}}
BASE_CONFIG = {
    'sport_id_priority': [1], 'show_bullpen_panel': True, 'show_leaders_panel': False,
    'show_standings_sidebar': False, 'hide_non_live_games': False,
    'use_team_logos': False, 'dark_mode': False, 'primary': 'NYY',
}
BULLPEN = {
    'days': 3, 'team_order': ['147', '111'],
    'teams': {'147': {'abbr': 'NYY', 'pitchers': PITCHERS[:2]},
              '111': {'abbr': 'BOS', 'pitchers': PITCHERS[2:3]}},
}


def _final(idx):
    return {'game_pk': idx, 'status': 'Final', 'away_team_id': '147', 'home_team_id': '111',
            'away_team': 'NYY', 'home_team': 'BOS', 'away_score': 3, 'home_score': 1,
            'inning': 9, 'is_top_inning': False, 'detailed_state': 'Final',
            'game_type': 'R', 'doubleheader': 'N', 'game_num': 1}


def _render(n_games, config=BASE_CONFIG, data=BULLPEN):
    import image_box
    from image_grid import draw_out_of_town_score_board
    calls = []
    real = image_bullpen.draw_bullpen_cell

    def spy(img, x, y, entry, days=3):
        calls.append((x, y, entry['abbr'], days))
        return real(img, x, y, entry, days=days)

    with patch('image_grid.load_yaml_file', return_value=config), \
         patch('image_box.load_yaml_file', return_value=config), \
         patch('image_grid.load_json_file', return_value=data), \
         patch('image_bullpen.draw_bullpen_cell', spy):
        image_box.set_historical_mode(True)
        try:
            draw_out_of_town_score_board(
                Image.new('1', (800, 480), 255), [_final(i) for i in range(n_games)], TEAM_DATA)
        finally:
            image_box.set_historical_mode(False)
    return calls


@needs_pil
class TestGridPlacement:
    def test_two_tiles_primary_then_opponent(self):
        calls = _render(3)
        assert [c[2] for c in calls] == ['NYY', 'BOS']
        assert calls[0][:2] != calls[1][:2]
        assert calls[0][3] == 3

    def test_single_free_slot_gets_primary_only(self):
        assert [c[2] for c in _render(14)] == ['NYY']

    def test_full_grid_draws_nothing(self):
        assert _render(15) == []

    def test_disabled_draws_nothing(self):
        assert _render(3, config=dict(BASE_CONFIG, show_bullpen_panel=False)) == []

    def test_missing_data_draws_nothing(self):
        assert _render(3, data={}) == []

    def test_team_missing_from_teams_stops(self):
        data = dict(BULLPEN, team_order=['147', '999', '111'])
        assert [c[2] for c in _render(3, data=data)] == ['NYY']

    def test_eliminated_team_skipped(self):
        bracket = {'series': [{'round': 'WC', 'away_abbr': 'NYY', 'home_abbr': 'BOS',
                               'complete': True, 'winner_abbr': 'NYY'},
                              {'round': 'DS', 'away_abbr': 'NYY', 'home_abbr': 'TB'}]}
        data = dict(BULLPEN, **bracket)
        assert [c[2] for c in _render(3, data=data)] == ['NYY']


class TestMainRefresh:
    def test_disabled_does_not_fetch(self, monkeypatch):
        fetch = MagicMock()
        monkeypatch.setattr(main_mod, 'fetch_bullpen', fetch)
        main_mod._refresh_bullpen({'show_bullpen_panel': False}, 'mlb')
        fetch.assert_not_called()

    def test_aaa_does_not_fetch(self, monkeypatch):
        fetch = MagicMock()
        monkeypatch.setattr(main_mod, 'fetch_bullpen', fetch)
        main_mod._refresh_bullpen({'show_bullpen_panel': True}, 'aaa')
        fetch.assert_not_called()

    def test_enabled_fetches_with_config(self, monkeypatch):
        fetch = MagicMock()
        monkeypatch.setattr(main_mod, 'fetch_bullpen', fetch)
        main_mod._refresh_bullpen(
            {'show_bullpen_panel': True, 'primary': 'ATL', 'bullpen_lookback_days': 4},
            'mlb', force=True)
        fetch.assert_called_once_with('ATL', days=4, force=True)

    def test_fetch_failure_is_swallowed(self, monkeypatch, capsys):
        monkeypatch.setattr(main_mod, 'fetch_bullpen', MagicMock(side_effect=RuntimeError('x')))
        main_mod._refresh_bullpen({'show_bullpen_panel': True, 'primary': 'ATL'}, 'mlb',
                                  context=' here')
        assert 'bullpen fetch here failed' in capsys.readouterr().out
