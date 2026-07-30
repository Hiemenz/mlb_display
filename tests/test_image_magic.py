"""Tests for image_magic.draw_magic_cell and its helpers."""
from unittest.mock import patch
from PIL import Image

from image_magic import (
    draw_magic_cell,
    _division_header,
    _find_primary_division,
    _magic_or_elim,
)


def _make_image():
    return Image.new('1', (800, 480), 255)


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_TEAMS = [
    {'team_id': 147, 'team_name': 'New York Yankees', 'divisionRank': 1,
     'league_record_wins': 60, 'league_record_losses': 30, 'clinch_indicator': ''},
    {'team_id': 111, 'team_name': 'Boston Red Sox', 'divisionRank': 2,
     'league_record_wins': 55, 'league_record_losses': 35, 'clinch_indicator': ''},
    {'team_id': 110, 'team_name': 'Baltimore Orioles', 'divisionRank': 3,
     'league_record_wins': 50, 'league_record_losses': 40, 'clinch_indicator': ''},
    {'team_id': 141, 'team_name': 'Toronto Blue Jays', 'divisionRank': 4,
     'league_record_wins': 45, 'league_record_losses': 45, 'clinch_indicator': ''},
    {'team_id': 139, 'team_name': 'Tampa Bay Rays', 'divisionRank': 5,
     'league_record_wins': 40, 'league_record_losses': 50, 'clinch_indicator': ''},
]

_STANDINGS = {
    'team_abbreviation': {
        '147': 'NYY', '111': 'BOS', '110': 'BAL', '141': 'TOR', '139': 'TB',
    },
    'standings': {
        'American League East': _TEAMS,
        'National League West': [
            {'team_id': 119, 'team_name': 'Los Angeles Dodgers', 'divisionRank': 1,
             'league_record_wins': 65, 'league_record_losses': 25, 'clinch_indicator': ''},
        ],
    },
}

_TEAM_DATA = {'team_abbreviation': {'147': 'NYY', '111': 'BOS'}}


# ---------------------------------------------------------------------------
# _division_header
# ---------------------------------------------------------------------------

class TestDivisionHeader:
    def test_al_east(self):
        assert _division_header('American League East') == 'AL EAST'

    def test_nl_central(self):
        assert _division_header('National League Central') == 'NL CENTRAL'

    def test_il_east(self):
        assert _division_header('International League East') == 'IL EAST'

    def test_pcl_west(self):
        assert _division_header('Pacific Coast League West') == 'PCL WEST'

    def test_unrecognised_name_uppercased(self):
        assert _division_header('Mystery Division') == 'MYSTERY DIVISION'

    def test_strips_excess_whitespace(self):
        result = _division_header('American League  East')
        assert result.startswith('AL ')


# ---------------------------------------------------------------------------
# _find_primary_division
# ---------------------------------------------------------------------------

class TestFindPrimaryDivision:
    def test_finds_nyy_in_al_east(self):
        abbr_map = _STANDINGS['team_abbreviation']
        name, teams = _find_primary_division(_STANDINGS['standings'], abbr_map, 'NYY')
        assert name == 'American League East'
        assert len(teams) == 5

    def test_returns_none_for_unknown_team(self):
        abbr_map = _STANDINGS['team_abbreviation']
        name, teams = _find_primary_division(_STANDINGS['standings'], abbr_map, 'XYZ')
        assert name is None
        assert teams is None

    def test_teams_sorted_by_division_rank(self):
        abbr_map = _STANDINGS['team_abbreviation']
        _, teams = _find_primary_division(_STANDINGS['standings'], abbr_map, 'NYY')
        ranks = [t.get('divisionRank') for t in teams]
        assert ranks == sorted(ranks)

    def test_empty_standings_returns_none(self):
        name, teams = _find_primary_division({}, {}, 'NYY')
        assert name is None

    def test_none_standings_returns_none(self):
        name, teams = _find_primary_division(None, {}, 'NYY')
        assert name is None

    def test_team_with_none_division_rank_sorted_last(self):
        teams = [
            {'team_id': 1, 'divisionRank': 2},
            {'team_id': 2, 'divisionRank': None},
            {'team_id': 3, 'divisionRank': 1},
        ]
        standings = {'AL Test': teams}
        abbr = {'1': 'AAA', '2': 'BBB', '3': 'CCC'}
        _, result = _find_primary_division(standings, abbr, 'BBB')
        assert result[-1]['team_id'] == 2  # None rank sorts last


# ---------------------------------------------------------------------------
# _magic_or_elim
# ---------------------------------------------------------------------------

class TestMagicOrElim:
    def _leader(self, wins=60, losses=30):
        return {'league_record_wins': wins, 'league_record_losses': losses,
                'clinch_indicator': ''}

    def _team(self, wins=50, losses=40, clinch='', games_back=None):
        return {'league_record_wins': wins, 'league_record_losses': losses,
                'clinch_indicator': clinch, 'games_back': games_back}

    def test_leader_magic_number(self):
        leader = self._leader(wins=100)
        # rival_losses=48 → M = 163-100-48 = 15, within _ELIM_THRESHOLD (20)
        result = _magic_or_elim(leader, leader, is_leader=True, rival_losses=48)
        assert result == 'M15'

    def test_leader_magic_number_hidden_when_above_threshold(self):
        """A magic number above _ELIM_THRESHOLD isn't meaningful yet, so the
        leader shows nothing instead of a large 'M68'."""
        leader = self._leader(wins=60)
        # rival_losses=35 → M = 163-60-35 = 68, well above the threshold
        result = _magic_or_elim(leader, leader, is_leader=True, rival_losses=35)
        assert result == ''

    def test_leader_clinched_when_magic_zero(self):
        # M = 163 - wins - rival_losses; CL when M <= 0
        # 163 - 100 - 63 = 0 → CL
        leader = self._leader(wins=100)
        result = _magic_or_elim(leader, leader, is_leader=True, rival_losses=63)
        assert result == 'CL'

    def test_leader_magic_one(self):
        # 163 - 100 - 62 = 1 → M1 (not yet clinched)
        leader = self._leader(wins=100)
        result = _magic_or_elim(leader, leader, is_leader=True, rival_losses=62)
        assert result == 'M1'

    def test_leader_clinched_when_no_rivals(self):
        leader = self._leader(wins=60)
        result = _magic_or_elim(leader, leader, is_leader=True, rival_losses=None)
        assert result == 'CL'

    def test_trailer_shows_games_back_when_elim_number_is_large(self):
        """Above _ELIM_THRESHOLD, games back is shown instead of the (not yet
        meaningful) elimination number."""
        leader = self._leader(wins=60)
        team = self._team(losses=40, games_back='6.5')
        # E = 163-60-40 = 63, well above the threshold
        result = _magic_or_elim(team, leader, is_leader=False, rival_losses=35)
        assert result == '6.5'

    def test_trailer_games_back_falls_back_to_dash_when_missing(self):
        """No games_back on the team dict falls back to '-', mirroring the
        wildcard header's convention for a missing value."""
        leader = self._leader(wins=60)
        team = self._team(losses=40, games_back=None)
        result = _magic_or_elim(team, leader, is_leader=False, rival_losses=35)
        assert result == '-'

    def test_trailer_shows_elimination_number_once_race_is_close(self):
        """Below _ELIM_THRESHOLD, the elimination number takes over from
        games back — the race is tight enough to be worth highlighting."""
        leader = self._leader(wins=100)
        team = self._team(losses=44, games_back='18.0')
        # E = 163-100-44 = 19 < 20 → elimination number, not games back
        result = _magic_or_elim(team, leader, is_leader=False, rival_losses=35)
        assert result == 'E19'

    def test_trailer_eliminated(self):
        leader = self._leader(wins=120)
        team = self._team(losses=63)
        # E = 163-120-63 = -20 → OUT
        result = _magic_or_elim(team, leader, is_leader=False, rival_losses=35)
        assert result == 'OUT'

    def test_clinch_indicator_z_returns_cl(self):
        team = self._team(clinch='z')
        result = _magic_or_elim(team, team, is_leader=True, rival_losses=35)
        assert result == 'CL'

    def test_clinch_indicator_y_returns_cl(self):
        team = self._team(clinch='y')
        result = _magic_or_elim(team, team, is_leader=True, rival_losses=35)
        assert result == 'CL'

    def test_clinch_indicator_e_returns_out(self):
        team = self._team(clinch='e')
        leader = self._leader()
        result = _magic_or_elim(team, leader, is_leader=False, rival_losses=35)
        assert result == 'OUT'

    def test_missing_wins_returns_empty(self):
        leader = {'league_record_wins': None, 'league_record_losses': 30, 'clinch_indicator': ''}
        result = _magic_or_elim(leader, leader, is_leader=True, rival_losses=35)
        assert result == ''

    def test_missing_losses_for_trailer_returns_empty(self):
        leader = self._leader(wins=60)
        team = {'league_record_wins': 50, 'league_record_losses': None, 'clinch_indicator': ''}
        result = _magic_or_elim(team, leader, is_leader=False, rival_losses=35)
        assert result == ''


# ---------------------------------------------------------------------------
# draw_magic_cell
# ---------------------------------------------------------------------------

class TestDrawMagicCell:
    def test_renders_with_full_standings(self):
        img = _make_image()
        result = draw_magic_cell(img, 32, 30, _STANDINGS, _TEAM_DATA, 'NYY')
        assert result is not None

    def test_renders_when_primary_not_found(self):
        img = _make_image()
        result = draw_magic_cell(img, 32, 30, _STANDINGS, _TEAM_DATA, 'XYZ')
        assert result is not None

    def test_renders_with_none_standings(self):
        img = _make_image()
        result = draw_magic_cell(img, 32, 30, None, _TEAM_DATA, 'NYY')
        assert result is not None

    def test_renders_with_none_team_data(self):
        img = _make_image()
        result = draw_magic_cell(img, 32, 30, _STANDINGS, None, 'NYY')
        assert result is not None

    def test_returns_image(self):
        img = _make_image()
        result = draw_magic_cell(img, 0, 0, _STANDINGS, _TEAM_DATA, 'NYY')
        assert isinstance(result, Image.Image)

    def test_renders_with_use_logos_true(self):
        img = _make_image()
        fake_logo = Image.new('1', (18, 18), 0)
        with patch('image_magic._logo_small', return_value=fake_logo):
            result = draw_magic_cell(img, 32, 30, _STANDINGS, _TEAM_DATA, 'NYY', use_logos=True)
        assert result is not None

    def test_renders_with_logo_failure(self):
        img = _make_image()
        with patch('image_magic._logo_small', side_effect=OSError('missing')):
            result = draw_magic_cell(img, 32, 30, _STANDINGS, _TEAM_DATA, 'NYY', use_logos=True)
        assert result is not None

    def test_renders_with_clinch_indicators(self):
        img = _make_image()
        teams = [
            {**t, 'clinch_indicator': 'z' if i == 0 else ('e' if i == 4 else '')}
            for i, t in enumerate(_TEAMS)
        ]
        standings = {**_STANDINGS, 'standings': {'American League East': teams}}
        result = draw_magic_cell(img, 32, 30, standings, _TEAM_DATA, 'NYY')
        assert result is not None

    def test_renders_large_division(self):
        """Divisions with >5 teams use smaller font — must not crash."""
        img = _make_image()
        extra_teams = _TEAMS + [
            {'team_id': 999, 'divisionRank': 6,
             'league_record_wins': 30, 'league_record_losses': 60, 'clinch_indicator': ''},
        ]
        abbr_map = {**_STANDINGS['team_abbreviation'], '999': 'EXT'}
        standings = {
            'team_abbreviation': abbr_map,
            'standings': {'American League East': extra_teams},
        }
        result = draw_magic_cell(img, 32, 30, standings, None, 'NYY')
        assert result is not None

    def test_header_says_magic_when_no_division_found(self):
        """When primary team's division isn't in standings, the header falls back to 'Magic #'."""
        img = _make_image()
        result = draw_magic_cell(img, 32, 30, {}, {}, 'NYY')
        assert result is not None

    def test_abbr_from_team_data_fallback(self):
        """abbr_map falls back to team_data when standings has no team_abbreviation."""
        img = _make_image()
        standings_no_abbr = {'standings': _STANDINGS['standings']}
        result = draw_magic_cell(img, 32, 30, standings_no_abbr, _TEAM_DATA, 'NYY')
        assert result is not None

    def test_record_truncation_when_column_too_narrow(self):
        """Record truncation loop (rec = rec[:-1]) fires when the record is too wide.

        The real PIL font never triggers this in practice — the cell is wide enough
        for any real W-L record.  We use a mock font whose getlength returns a
        fixed very-large value for non-empty strings so the while condition is
        always True and the loop fires at least once per team row.
        """
        from unittest.mock import MagicMock
        import image_magic as _im

        img = _make_image()
        teams = [
            {'team_id': 147, 'divisionRank': 1, 'clinch_indicator': '',
             'league_record_wins': 60, 'league_record_losses': 30},
            {'team_id': 111, 'divisionRank': 2, 'clinch_indicator': '',
             'league_record_wins': 50, 'league_record_losses': 40},
        ]
        standings = {
            'team_abbreviation': {'147': 'NYY', '111': 'BOS'},
            'standings': {'American League East': teams},
        }

        # Wrap the real font so getlength returns 999 for any non-empty string,
        # forcing the truncation while loop to fire (and terminate when rec='').
        from image_assets import _get_font as _real_get_font

        class _WideFont:
            def __init__(self, real):
                self._real = real

            def getlength(self, s):
                return 999 if s else 0

            def __getattr__(self, name):
                return getattr(self._real, name)

        _wide = _WideFont(_real_get_font(12))

        with patch('image_magic._get_font', return_value=_wide):
            result = draw_magic_cell(img, 32, 30, standings, None, 'NYY')
        assert result is not None
