"""Tests for standings.fetch_playoff_bracket.

Mocks all network access (standings.requests.get) and file I/O
(standings.save_off_results) following the pattern in test_standings.py.
"""
from unittest.mock import patch, MagicMock

import pytest

import standings
from standings import fetch_playoff_bracket


def _resp(status_code=200, json_data=None):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data if json_data is not None else {}
    return m


def _game(gtype, away_id, home_id, away_abbr, home_abbr,
          state='Scheduled', away_winner=False, home_winner=False):
    return {
        'gameType': gtype,
        'status': {'detailedState': state},
        'teams': {
            'away': {
                'team': {'id': away_id, 'abbreviation': away_abbr},
                'isWinner': away_winner,
            },
            'home': {
                'team': {'id': home_id, 'abbreviation': home_abbr},
                'isWinner': home_winner,
            },
        },
    }


@pytest.fixture(autouse=True)
def _reset_team_abbr_list():
    standings.team_abbreviation_list.clear()
    yield
    standings.team_abbreviation_list.clear()


class TestFetchPlayoffBracket:
    def test_non_200_response_returns_none(self):
        with patch('standings.requests.get', return_value=_resp(status_code=503)), \
             patch('standings.save_off_results') as mock_save:
            result = fetch_playoff_bracket(season=2025)
        assert result is None
        mock_save.assert_not_called()

    def test_network_exception_returns_none(self):
        with patch('standings.requests.get', side_effect=OSError('timeout')), \
             patch('standings.save_off_results') as mock_save:
            result = fetch_playoff_bracket(season=2025)
        assert result is None
        mock_save.assert_not_called()

    def test_empty_dates_returns_empty_series(self):
        payload = {'dates': []}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results') as mock_save:
            result = fetch_playoff_bracket(season=2025)
        assert result is not None
        assert result['season'] == 2025
        assert result['series'] == []
        mock_save.assert_called_once()

    def test_unknown_game_type_skipped(self):
        payload = {
            'dates': [{'games': [
                _game('R', 147, 111, 'NYY', 'BOS'),   # regular season — should skip
            ]}]
        }
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_playoff_bracket(season=2025)
        assert result['series'] == []

    def test_single_wc_series_created(self):
        payload = {
            'dates': [{'games': [
                _game('F', 147, 111, 'NYY', 'BOS'),
            ]}]
        }
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_playoff_bracket(season=2025)
        assert len(result['series']) == 1
        s = result['series'][0]
        assert s['round'] == 'WC'
        assert s['away_abbr'] == 'NYY'
        assert s['home_abbr'] == 'BOS'
        assert s['away_wins'] == 0
        assert s['home_wins'] == 0
        assert s['complete'] is False
        assert s['winner_abbr'] is None

    def test_away_win_increments_away_wins(self):
        payload = {
            'dates': [{'games': [
                _game('F', 147, 111, 'NYY', 'BOS', state='Final', away_winner=True),
            ]}]
        }
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_playoff_bracket(season=2025)
        s = result['series'][0]
        assert s['away_wins'] == 1
        assert s['home_wins'] == 0

    def test_home_win_increments_home_wins(self):
        payload = {
            'dates': [{'games': [
                _game('F', 147, 111, 'NYY', 'BOS', state='Final', home_winner=True),
            ]}]
        }
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_playoff_bracket(season=2025)
        s = result['series'][0]
        assert s['home_wins'] == 1
        assert s['away_wins'] == 0

    def test_game_over_state_counts_as_win(self):
        payload = {
            'dates': [{'games': [
                _game('D', 147, 111, 'NYY', 'BOS', state='Game Over', away_winner=True),
            ]}]
        }
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_playoff_bracket(season=2025)
        assert result['series'][0]['away_wins'] == 1

    def test_wc_series_complete_after_2_away_wins(self):
        """Wild card is best-of-3 (2 wins to clinch)."""
        games = [
            _game('F', 147, 111, 'NYY', 'BOS', state='Final', away_winner=True),
            _game('F', 147, 111, 'NYY', 'BOS', state='Final', away_winner=True),
        ]
        payload = {'dates': [{'games': games}]}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_playoff_bracket(season=2025)
        s = result['series'][0]
        assert s['complete'] is True
        assert s['winner_abbr'] == 'NYY'

    def test_ds_series_complete_after_3_home_wins(self):
        """Division series is best-of-5 (3 wins to clinch)."""
        games = [_game('D', 147, 111, 'NYY', 'BOS', state='Final', home_winner=True)] * 3
        payload = {'dates': [{'games': games}]}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_playoff_bracket(season=2025)
        s = result['series'][0]
        assert s['complete'] is True
        assert s['winner_abbr'] == 'BOS'

    def test_ws_series_complete_after_4_wins(self):
        """World Series is best-of-7 (4 wins to clinch)."""
        games = [_game('W', 147, 111, 'NYY', 'BOS', state='Final', away_winner=True)] * 4
        payload = {'dates': [{'games': games}]}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_playoff_bracket(season=2025)
        s = result['series'][0]
        assert s['complete'] is True
        assert s['winner_abbr'] == 'NYY'

    def test_duplicate_game_keys_merged_into_one_series(self):
        """Home/away swap in WS shouldn't create two separate series entries."""
        games = [
            _game('W', 147, 111, 'NYY', 'BOS'),
            _game('W', 111, 147, 'BOS', 'NYY'),  # same teams, home/away swapped
        ]
        payload = {'dates': [{'games': games}]}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_playoff_bracket(season=2025)
        assert len(result['series']) == 1

    def test_multiple_series_all_game_types(self):
        games = [
            _game('F', 147, 111, 'NYY', 'BOS'),   # WC
            _game('D', 119, 137, 'LAD', 'SF'),    # DS
            _game('L', 147, 119, 'NYY', 'LAD'),   # CS
            _game('W', 137, 111, 'SF', 'BOS'),    # WS (different teams)
        ]
        payload = {'dates': [{'games': games}]}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_playoff_bracket(season=2025)
        assert len(result['series']) == 4
        rounds = [s['round'] for s in result['series']]
        assert 'WC' in rounds
        assert 'DS' in rounds
        assert 'CS' in rounds
        assert 'WS' in rounds

    def test_series_sorted_wc_before_ds_before_cs_before_ws(self):
        games = [
            _game('W', 147, 111, 'NYY', 'BOS'),
            _game('F', 119, 137, 'LAD', 'SF'),
            _game('L', 147, 119, 'NYY', 'LAD'),
            _game('D', 137, 111, 'SF', 'BOS'),
        ]
        payload = {'dates': [{'games': games}]}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_playoff_bracket(season=2025)
        rounds = [s['round'] for s in result['series']]
        assert rounds.index('WC') < rounds.index('DS')
        assert rounds.index('DS') < rounds.index('CS')
        assert rounds.index('CS') < rounds.index('WS')

    def test_result_includes_season_and_fetched_at(self):
        payload = {'dates': []}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_playoff_bracket(season=2024)
        assert result['season'] == 2024
        assert 'fetched_at' in result
        assert isinstance(result['fetched_at'], float)

    def test_save_off_results_called_with_playoff_bracket_name(self):
        payload = {'dates': []}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results') as mock_save:
            fetch_playoff_bracket(season=2025)
        mock_save.assert_called_once()
        call_args = mock_save.call_args
        assert call_args[0][1] == 'playoff_bracket'

    def test_defaults_season_to_current_year_when_none(self):
        from datetime import datetime
        payload = {'dates': []}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)) as mock_get, \
             patch('standings.save_off_results'):
            fetch_playoff_bracket()
        url = mock_get.call_args[0][0]
        current_year = str(datetime.now().year)
        assert current_year in url

    def test_season_embedded_in_request_url(self):
        payload = {'dates': []}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)) as mock_get, \
             patch('standings.save_off_results'):
            fetch_playoff_bracket(season=2023)
        url = mock_get.call_args[0][0]
        assert '2023' in url
        assert 'gameType=F,D,L,W' in url

    def test_in_progress_game_does_not_count_as_win(self):
        payload = {
            'dates': [{'games': [
                _game('F', 147, 111, 'NYY', 'BOS', state='In Progress'),
            ]}]
        }
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_playoff_bracket(season=2025)
        s = result['series'][0]
        assert s['away_wins'] == 0
        assert s['home_wins'] == 0
        assert s['complete'] is False

    def test_cs_series_complete_after_4_wins(self):
        """Championship series is best-of-7 (4 wins)."""
        games = [_game('L', 147, 111, 'NYY', 'BOS', state='Final', home_winner=True)] * 4
        payload = {'dates': [{'games': games}]}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_playoff_bracket(season=2025)
        s = result['series'][0]
        assert s['complete'] is True
        assert s['winner_abbr'] == 'BOS'

    def test_incomplete_series_not_marked_complete(self):
        games = [
            _game('D', 147, 111, 'NYY', 'BOS', state='Final', away_winner=True),
            _game('D', 147, 111, 'NYY', 'BOS', state='Final', home_winner=True),
        ]
        payload = {'dates': [{'games': games}]}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_playoff_bracket(season=2025)
        s = result['series'][0]
        assert s['complete'] is False
        assert s['winner_abbr'] is None
