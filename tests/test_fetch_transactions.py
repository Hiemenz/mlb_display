"""Tests for standings.fetch_transactions.

Mocks all network access (standings.requests.get) and file I/O
(standings.save_off_results) following the pattern in test_fetch_playoff_bracket.py.
"""
from unittest.mock import patch, MagicMock

import pytest

import standings
from standings import fetch_transactions


def _resp(status_code=200, json_data=None):
    """Resp."""
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data if json_data is not None else {}
    return m


def _tx(date='2026-07-08', player='Aaron Judge', team_abbr='NYY', team_id=147,
        type_desc='Status Change', description='Yankees placed Aaron Judge on 10-day IL',
        to_team=True):
    """Tx."""
    team = {'id': team_id, 'abbreviation': team_abbr}
    entry = {
        'date': date,
        'person': {'fullName': player},
        'typeDesc': type_desc,
        'description': description,
    }
    entry['toTeam' if to_team else 'fromTeam'] = team
    return entry


@pytest.fixture(autouse=True)
def _reset_team_abbr_list():
    """Reset team abbr list."""
    standings.team_abbreviation_list.clear()
    yield
    standings.team_abbreviation_list.clear()


class TestFetchTransactions:
    def test_non_200_response_returns_none(self):
        """Non 200 response returns none."""
        with patch('standings.requests.get', return_value=_resp(status_code=503)), \
             patch('standings.save_off_results') as mock_save:
            result = fetch_transactions()
        assert result is None
        mock_save.assert_not_called()

    def test_network_exception_returns_none(self):
        """Network exception returns none."""
        with patch('standings.requests.get', side_effect=OSError('timeout')), \
             patch('standings.save_off_results') as mock_save:
            result = fetch_transactions()
        assert result is None
        mock_save.assert_not_called()

    def test_empty_transactions_returns_empty_list(self):
        """Empty transactions returns empty list."""
        payload = {'transactions': []}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results') as mock_save:
            result = fetch_transactions()
        assert result is not None
        assert result['transactions'] == []
        mock_save.assert_called_once()

    def test_entry_fields_extracted(self):
        """Entry fields extracted."""
        payload = {'transactions': [_tx()]}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_transactions()
        e = result['transactions'][0]
        assert e['player_name'] == 'Aaron Judge'
        assert e['team_abbr'] == 'NYY'
        assert e['team_id'] == '147'
        assert e['type_desc'] == 'Status Change'
        assert e['date'] == '2026-07-08'

    def test_from_team_used_when_no_to_team(self):
        """From team used when no to team."""
        payload = {'transactions': [_tx(team_abbr='BOS', team_id=111, to_team=False)]}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_transactions()
        assert result['transactions'][0]['team_abbr'] == 'BOS'

    def test_entries_sorted_newest_first(self):
        """Entries sorted newest first."""
        payload = {'transactions': [
            _tx(date='2026-07-06', player='Older Move'),
            _tx(date='2026-07-08', player='Newer Move'),
            _tx(date='2026-07-07', player='Middle Move'),
        ]}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_transactions()
        names = [e['player_name'] for e in result['transactions']]
        assert names == ['Newer Move', 'Middle Move', 'Older Move']

    def test_result_includes_fetched_at_and_lookback_days(self):
        """Result includes fetched at and lookback days."""
        payload = {'transactions': []}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_transactions(lookback_days=5)
        assert 'fetched_at' in result
        assert isinstance(result['fetched_at'], float)
        assert result['lookback_days'] == 5

    def test_save_off_results_called_with_transactions_name(self):
        """Save off results called with transactions name."""
        payload = {'transactions': []}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results') as mock_save:
            fetch_transactions()
        mock_save.assert_called_once()
        call_args = mock_save.call_args
        assert call_args[0][1] == 'transactions'

    def test_lookback_days_embedded_in_request_url(self):
        """Lookback days embedded in request url reflects the date window."""
        from datetime import datetime, timedelta
        payload = {'transactions': []}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)) as mock_get, \
             patch('standings.save_off_results'):
            fetch_transactions(lookback_days=3)
        url = mock_get.call_args[0][0]
        expected_start = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
        assert expected_start in url
        assert 'sportId=1' in url

    def test_missing_person_or_team_falls_back_to_empty_strings(self):
        """Missing person or team falls back to empty strings."""
        payload = {'transactions': [{'date': '2026-07-08', 'typeDesc': 'Trade'}]}
        with patch('standings.requests.get', return_value=_resp(json_data=payload)), \
             patch('standings.save_off_results'):
            result = fetch_transactions()
        e = result['transactions'][0]
        assert e['player_name'] == ''
        assert e['team_abbr'] == ''
        assert e['team_id'] == ''
