"""
Unit tests for src/standings.py (0% covered previously). Mocks all network
access via patch('standings.requests.get', ...) and file I/O via
patch('standings.load_json_file'/'save_off_results', ...), matching the
patching style used elsewhere in this repo (see tests/test_wide_cell.py).

Note: get_teams()/get_standings()/fetch_wildcard_standings() all read/write
the module-level `team_abbreviation_list` dict, so every test resets it via
the `_reset_team_abbr_list` autouse fixture below to avoid cross-test leakage.
"""
from unittest.mock import patch, MagicMock

import pytest

import standings
import sys
from standings import get_teams, get_standings, fetch_wildcard_standings, main


def _resp(status_code=200, json_data=None):
    """Resp."""
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data if json_data is not None else {}
    return m


@pytest.fixture(autouse=True)
def _reset_team_abbr_list():
    """Reset team abbr list."""
    standings.team_abbreviation_list.clear()
    yield
    standings.team_abbreviation_list.clear()


# ===========================================================================
# get_teams
# ===========================================================================

class TestGetTeams:
    def test_already_cached_skips_request(self):
        """Already cached skips request."""
        standings.team_abbreviation_list['147'] = 'NYY'
        with patch('standings.requests.get') as mock_get:
            get_teams(147)
        mock_get.assert_not_called()
        assert standings.team_abbreviation_list['147'] == 'NYY'

    def test_success_populates_cache(self):
        """Success populates cache."""
        payload = {'teams': [{'id': 147, 'abbreviation': 'NYY'}]}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)):
            get_teams(147)
        assert standings.team_abbreviation_list['147'] == 'NYY'

    def test_missing_abbreviation_uses_fallback(self):
        """Missing abbreviation uses fallback."""
        payload = {'teams': [{'id': 147}]}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)):
            get_teams(147)
        assert standings.team_abbreviation_list['147'] == 'T147'

    def test_non_200_status_uses_fallback(self):
        """Non 200 status uses fallback."""
        with patch('standings.requests.get', return_value=_resp(status_code=500)):
            get_teams(147)
        assert standings.team_abbreviation_list['147'] == 'T147'

    def test_exception_uses_fallback(self):
        """Exception uses fallback."""
        with patch('standings.requests.get', side_effect=Exception('boom')):
            get_teams(147)
        assert standings.team_abbreviation_list['147'] == 'T147'


# ===========================================================================
# get_standings
# ===========================================================================

def _team_record(team_id, abbr, name, div_rank, wins=50, losses=30, pct='.625',
                  gb='-', streak='W3', split_records=None, wc_rank=1, wc_gb='-',
                  division_leader=False):
    """Team record."""
    return {
        'team': {'id': team_id, 'abbreviation': abbr, 'name': name},
        'divisionRank': str(div_rank),
        'leagueRecord': {'wins': wins, 'losses': losses, 'pct': pct},
        'gamesBack': gb,
        'streak': {'streakCode': streak},
        'records': {'splitRecords': split_records if split_records is not None else [
            {'type': 'lastTen', 'wins': 7, 'losses': 3},
            {'type': 'home', 'wins': 25, 'losses': 15},
            {'type': 'away', 'wins': 25, 'losses': 15},
        ]},
        'divisionLeader': division_leader,
        'wildCardRank': wc_rank,
        'wildCardGamesBack': wc_gb,
    }


def _standings_payload(division_id=201, division_name='American League East',
                        team_records=None, last_updated='2026-07-01T12:00:00Z'):
    """Standings payload."""
    return {
        'records': [
            {
                'division': {'id': division_id, 'name': division_name},
                'lastUpdated': last_updated,
                'teamRecords': team_records or [_team_record(147, 'NYY', 'New York Yankees', 1)],
            },
        ],
    }


class TestGetStandings:
    def test_basic_flow_saves_expected_structure(self):
        """Basic flow saves expected structure."""
        payload = _standings_payload()
        with patch('standings.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results') as mock_save:
            get_standings([103], season=2025)
        # Two save_off_results calls: one for 'standings', one for 'teams'.
        assert mock_save.call_count == 2
        first_call_data, first_call_name = mock_save.call_args_list[0][0]
        assert first_call_name == 'standings'
        assert 'American League East' in first_call_data['standings']
        team = first_call_data['standings']['American League East'][0]
        assert team['team_name'] == 'New York Yankees'
        assert team['league_record_wins'] == 50
        assert team['last_ten_wins'] == 7
        assert team['home_wins'] == 25
        assert team['away_wins'] == 25
        assert first_call_data['last_updated'] == '2026-07-01T12:00:00Z'

    def test_custom_save_as_name_used(self):
        """Custom save as name used."""
        payload = _standings_payload()
        with patch('standings.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results') as mock_save:
            get_standings([103], season=2025, save_as='custom_standings')
        first_call_name = mock_save.call_args_list[0][0][1]
        assert first_call_name == 'custom_standings'

    def test_missing_split_records_falls_back_to_none_values(self):
        """Missing split records falls back to none values."""
        team_records = [_team_record(147, 'NYY', 'New York Yankees', 1, split_records=[])]
        payload = _standings_payload(team_records=team_records)
        with patch('standings.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results') as mock_save:
            get_standings([103], season=2025)
        team = mock_save.call_args_list[0][0][0]['standings']['American League East'][0]
        assert team['last_ten_wins'] is None
        assert team['home_wins'] is None
        assert team['away_wins'] is None

    def test_missing_split_records_key_entirely_falls_back(self):
        """Missing split records key entirely falls back."""
        team_record = _team_record(147, 'NYY', 'New York Yankees', 1)
        team_record['records'] = {}
        payload = _standings_payload(team_records=[team_record])
        with patch('standings.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results') as mock_save:
            get_standings([103], season=2025)
        team = mock_save.call_args_list[0][0][0]['standings']['American League East'][0]
        assert team['last_ten_wins'] is None

    def test_team_abbreviation_used_directly_when_present(self):
        """Team abbreviation used directly when present."""
        payload = _standings_payload()
        with patch('standings.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'), \
             patch('standings.get_teams') as mock_get_teams:
            get_standings([103], season=2025)
        mock_get_teams.assert_not_called()
        assert standings.team_abbreviation_list['147'] == 'NYY'

    def test_get_teams_called_when_abbreviation_missing_and_not_cached(self):
        """Get teams called when abbreviation missing and not cached."""
        team_record = _team_record(147, 'NYY', 'New York Yankees', 1)
        del team_record['team']['abbreviation']
        payload = _standings_payload(team_records=[team_record])
        with patch('standings.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'), \
             patch('standings.get_teams') as mock_get_teams:
            get_standings([103], season=2025)
        mock_get_teams.assert_called_once_with(147)

    def test_pre_populated_cache_skips_get_teams_even_without_api_abbr(self):
        """Pre populated cache skips get teams even without api abbr."""
        standings.team_abbreviation_list['147'] = 'NYY'
        team_record = _team_record(147, 'NYY', 'New York Yankees', 1)
        del team_record['team']['abbreviation']
        payload = _standings_payload(team_records=[team_record])
        with patch('standings.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'), \
             patch('standings.get_teams') as mock_get_teams:
            get_standings([103], season=2025)
        mock_get_teams.assert_not_called()

    def test_multiple_league_ids_call_api_per_league(self):
        """Multiple league ids call api per league."""
        al_payload = _standings_payload(division_id=201, division_name='American League East')
        nl_payload = _standings_payload(
            division_id=204, division_name='National League East',
            team_records=[_team_record(143, 'PHI', 'Philadelphia Phillies', 1)],
        )
        with patch('standings.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('standings.requests.get', side_effect=[_resp(json_data=al_payload),
                                                          _resp(json_data=nl_payload)]) as mock_get, \
             patch('standings.save_off_results') as mock_save:
            get_standings([103, 104], season=2025)
        assert mock_get.call_count == 2
        standings_dict = mock_save.call_args_list[0][0][0]['standings']
        assert 'American League East' in standings_dict
        assert 'National League East' in standings_dict

    def test_exception_from_one_league_propagates(self):
        """get_standings() has no per-league try/except: a failure on one league
        call currently aborts the whole call rather than continuing to the next."""
        with patch('standings.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('standings.requests.get', side_effect=Exception('network down')):
            with pytest.raises(Exception, match='network down'):
                get_standings([103, 104], season=2025)

    def test_optional_date_param_appended_to_url(self):
        """Optional date param appended to url."""
        payload = _standings_payload()
        with patch('standings.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('standings.requests.get', return_value=_resp(json_data=payload)) as mock_get, \
             patch('standings.save_off_results'):
            get_standings([103], season=2025, date='07/01/2026')
        called_url = mock_get.call_args[0][0]
        assert 'date=07/01/2026' in called_url

    def test_teams_json_updated_with_merged_abbreviations(self):
        """Teams json updated with merged abbreviations."""
        payload = _standings_payload()
        with patch('standings.load_json_file', return_value={'team_abbreviation': {'999': 'OLD'}}), \
             patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results') as mock_save:
            get_standings([103], season=2025)
        teams_call = mock_save.call_args_list[1]
        saved_data, saved_name = teams_call[0]
        assert saved_name == 'teams'
        assert saved_data['team_abbreviation']['999'] == 'OLD'
        assert saved_data['team_abbreviation']['147'] == 'NYY'

    def test_division_id_maps_via_leauge_dict(self):
        """Division id maps via leauge dict."""
        payload = _standings_payload(division_id=203, division_name='Should Not Use This Name')
        with patch('standings.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results') as mock_save:
            get_standings([103], season=2025)
        standings_dict = mock_save.call_args_list[0][0][0]['standings']
        assert 'National League West' in standings_dict

    def test_unmapped_division_id_falls_back_to_api_name(self):
        """Unmapped division id falls back to api name."""
        payload = _standings_payload(division_id=99999, division_name='Some New Division')
        with patch('standings.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results') as mock_save:
            get_standings([103], season=2025)
        standings_dict = mock_save.call_args_list[0][0][0]['standings']
        assert 'Some New Division' in standings_dict


# ===========================================================================
# fetch_wildcard_standings
# ===========================================================================

def _wc_payload(team_records):
    """Wc payload."""
    return {'records': [{'teamRecords': team_records}]}


class TestFetchWildcardStandings:
    def test_division_leaders_excluded(self):
        """Division leaders excluded."""
        team_records = [
            _team_record(1, 'NYY', 'Yankees', 1, division_leader=True, wc_rank=None),
            _team_record(2, 'BOS', 'Red Sox', 2, division_leader=False, wc_rank=1),
        ]
        with patch('standings.requests.get', return_value=_resp(json_data=_wc_payload(team_records))), \
             patch('standings.save_off_results'):
            result = fetch_wildcard_standings(season=2025)
        abbrs = [t['abbr'] for t in result['AL']]
        assert 'NYY' not in abbrs
        assert 'BOS' in abbrs

    def test_wild_card_rank_sorting_with_none_last(self):
        """Wild card rank sorting with none last."""
        team_records = [
            _team_record(1, 'AAA', 'Team A', 2, wc_rank=None),
            _team_record(2, 'BBB', 'Team B', 3, wc_rank=3),
            _team_record(3, 'CCC', 'Team C', 4, wc_rank=1),
        ]
        with patch('standings.requests.get', return_value=_resp(json_data=_wc_payload(team_records))), \
             patch('standings.save_off_results'):
            result = fetch_wildcard_standings(season=2025)
        abbrs = [t['abbr'] for t in result['AL']]
        assert abbrs == ['CCC', 'BBB', 'AAA']

    def test_wild_card_rank_zero_treated_as_falsy_sorts_last(self):
        """Wild card rank zero treated as falsy sorts last."""
        team_records = [
            _team_record(1, 'AAA', 'Team A', 2, wc_rank=0),
            _team_record(2, 'BBB', 'Team B', 3, wc_rank=2),
        ]
        with patch('standings.requests.get', return_value=_resp(json_data=_wc_payload(team_records))), \
             patch('standings.save_off_results'):
            result = fetch_wildcard_standings(season=2025)
        abbrs = [t['abbr'] for t in result['AL']]
        assert abbrs == ['BBB', 'AAA']

    def test_results_capped_at_ten_per_league(self):
        """Results capped at ten per league."""
        team_records = [
            _team_record(i, f'T{i:02d}', f'Team {i}', 2, wc_rank=i)
            for i in range(1, 13)
        ]
        with patch('standings.requests.get', return_value=_resp(json_data=_wc_payload(team_records))), \
             patch('standings.save_off_results'):
            result = fetch_wildcard_standings(season=2025)
        assert len(result['AL']) == 10

    def test_abbr_uses_cached_team_abbreviation_list_first(self):
        """Abbr uses cached team abbreviation list first."""
        standings.team_abbreviation_list['2'] = 'CACHED'
        team_records = [_team_record(2, 'API_ABBR', 'Team B', 2, wc_rank=1)]
        with patch('standings.requests.get', return_value=_resp(json_data=_wc_payload(team_records))), \
             patch('standings.save_off_results'):
            result = fetch_wildcard_standings(season=2025)
        assert result['AL'][0]['abbr'] == 'CACHED'

    def test_abbr_falls_back_to_team_record_abbreviation(self):
        """Abbr falls back to team record abbreviation."""
        team_records = [_team_record(2, 'API_ABBR', 'Team B', 2, wc_rank=1)]
        with patch('standings.requests.get', return_value=_resp(json_data=_wc_payload(team_records))), \
             patch('standings.save_off_results'):
            result = fetch_wildcard_standings(season=2025)
        assert result['AL'][0]['abbr'] == 'API_ABBR'

    def test_non_200_response_skips_league_without_crash(self):
        """Non 200 response skips league without crash."""
        with patch('standings.requests.get', return_value=_resp(status_code=500)), \
             patch('standings.save_off_results'):
            result = fetch_wildcard_standings(season=2025)
        assert result == {'AL': [], 'NL': []}

    def test_exception_on_one_league_does_not_abort_the_other(self):
        """Exception on one league does not abort the other."""
        team_records = [_team_record(2, 'BOS', 'Red Sox', 2, wc_rank=1)]

        def fake_get(url, *args, **kwargs):
            """Fake get."""
            if 'leagueId=103' in url:
                raise Exception('AL API down')
            return _resp(json_data=_wc_payload(team_records))

        with patch('standings.requests.get', side_effect=fake_get), \
             patch('standings.save_off_results'):
            result = fetch_wildcard_standings(season=2025)
        assert result['AL'] == []
        assert len(result['NL']) == 1

    def test_defaults_season_to_current_year_when_none(self):
        """Defaults season to current year when none."""
        with patch('standings.requests.get', return_value=_resp(json_data=_wc_payload([]))) as mock_get, \
             patch('standings.save_off_results'):
            fetch_wildcard_standings(season=None)
        from datetime import datetime as _dt
        assert f'season={_dt.now().year}' in mock_get.call_args_list[0][0][0]

    def test_optional_date_appended_to_url(self):
        """Optional date appended to url."""
        with patch('standings.requests.get', return_value=_resp(json_data=_wc_payload([]))) as mock_get, \
             patch('standings.save_off_results'):
            fetch_wildcard_standings(season=2025, date='07/01/2026')
        assert 'date=07/01/2026' in mock_get.call_args_list[0][0][0]

    def test_result_saved_via_save_off_results(self):
        """Result saved via save off results."""
        with patch('standings.requests.get', return_value=_resp(json_data=_wc_payload([]))), \
             patch('standings.save_off_results') as mock_save:
            result = fetch_wildcard_standings(season=2025)
        mock_save.assert_called_once_with(result, 'wildcard_standings')

    def test_gb_defaults_to_dash_when_missing(self):
        """Gb defaults to dash when missing."""
        team_record = _team_record(2, 'BOS', 'Red Sox', 2, wc_rank=1)
        team_record['wildCardGamesBack'] = None
        with patch('standings.requests.get', return_value=_resp(json_data=_wc_payload([team_record]))), \
             patch('standings.save_off_results'):
            result = fetch_wildcard_standings(season=2025)
        assert result['AL'][0]['gb'] == '-'


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

class TestMain:
    """Tests for the CLI entry-point main()."""

    def _run(self, args):
        """Invoke main() with sys.argv set to args; patch get_standings + print."""
        with patch.object(sys, 'argv', ['standings'] + args), \
             patch('standings.get_standings') as mock_gs, \
             patch('builtins.print'):
            main()
        return mock_gs

    def test_no_args_uses_default_mlb_leagues(self):
        """No args uses default mlb leagues."""
        mock_gs = self._run([])
        # Default is MLB: league_ids [103, 104]
        call_args = mock_gs.call_args
        assert call_args[0][0] == [103, 104]

    def test_aaa_flag_uses_aaa_leagues(self):
        """Aaa flag uses aaa leagues."""
        mock_gs = self._run(['--aaa'])
        assert mock_gs.call_args[0][0] == [117, 112]

    def test_season_arg_passed_to_get_standings(self):
        """Season arg passed to get standings."""
        mock_gs = self._run(['--season', '2023'])
        assert mock_gs.call_args[1]['season'] == 2023

    def test_date_yyyy_mm_dd_parses_and_passes_formatted(self):
        """Date yyyy mm dd parses and passes formatted."""
        mock_gs = self._run(['--date', '2026-06-20'])
        call_kw = mock_gs.call_args[1]
        assert call_kw['date'] == '06/20/2026'
        assert call_kw['season'] == 2026

    def test_date_mm_dd_yyyy_format_also_accepted(self):
        """Date mm dd yyyy format also accepted."""
        mock_gs = self._run(['--date', '06/20/2026'])
        call_kw = mock_gs.call_args[1]
        assert call_kw['date'] == '06/20/2026'
        assert call_kw['season'] == 2026

    def test_invalid_date_prints_error_and_returns_early(self):
        """Invalid date prints error and returns early."""
        with patch.object(sys, 'argv', ['standings', '--date', 'not-a-date']), \
             patch('standings.get_standings') as mock_gs, \
             patch('builtins.print'):
            main()
        mock_gs.assert_not_called()
