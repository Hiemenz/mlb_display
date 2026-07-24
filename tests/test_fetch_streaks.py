"""Tests for fetch_streaks.fetch_streaks and helpers."""
import time
from unittest.mock import patch, MagicMock

import fetch_streaks
from fetch_streaks import fetch_streaks as _fetch_streaks, _parse_float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resp(status_code=200, json_data=None):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data or {}
    m.raise_for_status = MagicMock()
    if status_code != 200:
        m.raise_for_status.side_effect = Exception(f'HTTP {status_code}')
    return m


def _primary_payload(avg_leaders=None, era_leaders=None):
    groups = []
    if avg_leaders is not None:
        groups.append({
            'statGroup': 'hitting',
            'leaderCategory': 'battingAverage',
            'leaders': avg_leaders,
        })
    if era_leaders is not None:
        groups.append({
            'statGroup': 'pitching',
            'leaderCategory': 'earnedRunAverage',
            'leaders': era_leaders,
        })
    return {'leagueLeaders': groups}


def _secondary_payload(ip_leaders=None, gp_leaders=None):
    groups = []
    if ip_leaders is not None:
        groups.append({
            'statGroup': 'pitching',
            'leaderCategory': 'inningsPitched',
            'leaders': ip_leaders,
        })
    if gp_leaders is not None:
        groups.append({
            'statGroup': 'hitting',
            'leaderCategory': 'gamesPlayed',
            'leaders': gp_leaders,
        })
    return {'leagueLeaders': groups}


def _hitter(pid, name, avg, team_id='147'):
    return {
        'rank': 1,
        'value': avg,
        'person': {'id': pid, 'fullName': name},
        'team': {'id': int(team_id)},
    }


def _pitcher(pid, name, era, team_id='147'):
    return {
        'rank': 1,
        'value': era,
        'person': {'id': pid, 'fullName': name},
        'team': {'id': int(team_id)},
    }


_TEAMS_DATA = {'team_abbreviation': {'147': 'NYY'}}


# ---------------------------------------------------------------------------
# _parse_float
# ---------------------------------------------------------------------------

class TestParseFloat:
    def test_valid_float_string(self):
        assert _parse_float('1.57') == 1.57

    def test_none_returns_sentinel(self):
        assert _parse_float(None) == 999.0

    def test_non_numeric_returns_sentinel(self):
        assert _parse_float('N/A') == 999.0

    def test_integer_string(self):
        assert _parse_float('3') == 3.0


# ---------------------------------------------------------------------------
# Cache path
# ---------------------------------------------------------------------------

class TestFetchStreaksCache:
    def test_returns_cached_when_fresh(self):
        cached = {
            'fetched_at': time.time() - 100,
            'season': 2026,
            'streaks': [{'name': 'cached hitter'}],
            'scoreless': [],
        }
        with patch('fetch_streaks.load_json_file', return_value=cached), \
             patch('fetch_streaks.requests.get') as mock_get:
            result = _fetch_streaks(season=2026)
        mock_get.assert_not_called()
        assert result['streaks'][0]['name'] == 'cached hitter'

    def test_bypasses_cache_when_force(self):
        cached = {'fetched_at': time.time() - 100, 'season': 2026, 'streaks': [], 'scoreless': []}
        primary = _primary_payload(avg_leaders=[], era_leaders=[])
        secondary = _secondary_payload(ip_leaders=[], gp_leaders=[])
        with patch('fetch_streaks.load_json_file', side_effect=[cached, _TEAMS_DATA]), \
             patch('fetch_streaks.requests.get', side_effect=[_resp(json_data=primary), _resp(json_data=secondary)]), \
             patch('fetch_streaks.save_off_results'):
            _fetch_streaks(season=2026, force=True)

    def test_bypasses_cache_when_stale(self):
        cached = {'fetched_at': time.time() - 25 * 3600, 'season': 2026, 'streaks': [], 'scoreless': []}
        primary = _primary_payload(avg_leaders=[], era_leaders=[])
        secondary = _secondary_payload(ip_leaders=[], gp_leaders=[])
        with patch('fetch_streaks.load_json_file', side_effect=[cached, _TEAMS_DATA]), \
             patch('fetch_streaks.requests.get', side_effect=[_resp(json_data=primary), _resp(json_data=secondary)]), \
             patch('fetch_streaks.save_off_results'):
            _fetch_streaks(season=2026)

    def test_bypasses_cache_when_wrong_season(self):
        cached = {'fetched_at': time.time() - 100, 'season': 2025, 'streaks': [], 'scoreless': []}
        primary = _primary_payload(avg_leaders=[], era_leaders=[])
        secondary = _secondary_payload(ip_leaders=[], gp_leaders=[])
        with patch('fetch_streaks.load_json_file', side_effect=[cached, _TEAMS_DATA]), \
             patch('fetch_streaks.requests.get', side_effect=[_resp(json_data=primary), _resp(json_data=secondary)]), \
             patch('fetch_streaks.save_off_results'):
            _fetch_streaks(season=2026)


# ---------------------------------------------------------------------------
# Network path
# ---------------------------------------------------------------------------

class TestFetchStreaksNetwork:
    def _make_responses(self, avg_leaders=None, era_leaders=None,
                        ip_leaders=None, gp_leaders=None):
        primary = _primary_payload(avg_leaders or [], era_leaders or [])
        secondary = _secondary_payload(ip_leaders or [], gp_leaders or [])
        return [_resp(json_data=primary), _resp(json_data=secondary)]

    def _patches(self, responses):
        return (
            patch('fetch_streaks.load_json_file', return_value=_TEAMS_DATA),
            patch('fetch_streaks.requests.get', side_effect=responses),
            patch('fetch_streaks.save_off_results'),
        )

    def test_returns_hitters_list(self):
        responses = self._make_responses(
            avg_leaders=[_hitter(1, 'Aaron Judge', '.350')],
        )
        p1, p2, p3 = self._patches(responses)
        with p1, p2, p3:
            result = _fetch_streaks(season=2026)
        assert len(result['streaks']) == 1
        assert result['streaks'][0]['name'] == 'Aaron Judge'
        assert result['streaks'][0]['avg'] == '.350'
        assert result['streaks'][0]['abbr'] == 'NYY'

    def test_returns_pitchers_list_sorted_ascending(self):
        era_leaders = [
            _pitcher(10, 'Pitcher A', '4.00'),
            _pitcher(11, 'Pitcher B', '1.50'),
            _pitcher(12, 'Pitcher C', '2.75'),
        ]
        responses = self._make_responses(era_leaders=era_leaders)
        p1, p2, p3 = self._patches(responses)
        with p1, p2, p3:
            result = _fetch_streaks(season=2026)
        eras = [float(e['era']) for e in result['scoreless']]
        assert eras == sorted(eras)

    def test_ip_joined_to_pitcher(self):
        era_leaders = [_pitcher(10, 'Pitcher A', '2.00')]
        ip_leaders = [{'statGroup': 'pitching', 'person': {'id': 10}, 'value': '88.2'}]
        primary = _primary_payload(era_leaders=era_leaders)
        secondary = {'leagueLeaders': [
            {'statGroup': 'pitching', 'leaderCategory': 'inningsPitched',
             'leaders': [{'person': {'id': 10}, 'value': '88.2'}]},
        ]}
        with patch('fetch_streaks.load_json_file', return_value=_TEAMS_DATA), \
             patch('fetch_streaks.requests.get', side_effect=[
                 _resp(json_data=primary), _resp(json_data=secondary)
             ]), \
             patch('fetch_streaks.save_off_results'):
            result = _fetch_streaks(season=2026)
        assert result['scoreless'][0]['ip'] == '88.2'

    def test_games_played_joined_to_hitter(self):
        avg_leaders = [_hitter(5, 'Freddie Freeman', '.330')]
        secondary = {'leagueLeaders': [
            {'statGroup': 'hitting', 'leaderCategory': 'gamesPlayed',
             'leaders': [{'person': {'id': 5}, 'value': '14'}]},
        ]}
        primary = _primary_payload(avg_leaders=avg_leaders)
        with patch('fetch_streaks.load_json_file', return_value=_TEAMS_DATA), \
             patch('fetch_streaks.requests.get', side_effect=[
                 _resp(json_data=primary), _resp(json_data=secondary)
             ]), \
             patch('fetch_streaks.save_off_results'):
            result = _fetch_streaks(season=2026)
        assert result['streaks'][0]['games'] == '14'

    def test_result_has_fetched_at_and_season(self):
        responses = self._make_responses()
        p1, p2, p3 = self._patches(responses)
        with p1, p2, p3:
            result = _fetch_streaks(season=2026)
        assert 'fetched_at' in result
        assert result['season'] == 2026

    def test_network_error_returns_cached(self):
        cached = {'fetched_at': 0.0, 'season': 2025, 'streaks': [{'name': 'old'}], 'scoreless': []}
        with patch('fetch_streaks.load_json_file', return_value=cached), \
             patch('fetch_streaks.requests.get', side_effect=OSError('timeout')):
            result = _fetch_streaks(season=2026)
        assert result['streaks'][0]['name'] == 'old'

    def test_network_error_with_no_cache_returns_empty(self):
        with patch('fetch_streaks.load_json_file', return_value={}), \
             patch('fetch_streaks.requests.get', side_effect=OSError('timeout')):
            result = _fetch_streaks(season=2026)
        assert result == {}

    def test_season_defaults_to_current_year(self):
        responses = self._make_responses()
        p1, p2, p3 = self._patches(responses)
        with p1, p2, p3:
            result = _fetch_streaks()
        import datetime
        assert result['season'] == datetime.datetime.now().year

    def test_secondary_leader_missing_person_id_skipped(self):
        secondary = {'leagueLeaders': [
            {'statGroup': 'pitching', 'leaderCategory': 'inningsPitched',
             'leaders': [{'person': {}, 'value': '50.0'}]},
        ]}
        primary = _primary_payload(era_leaders=[_pitcher(99, 'Some Pitcher', '3.00')])
        with patch('fetch_streaks.load_json_file', return_value=_TEAMS_DATA), \
             patch('fetch_streaks.requests.get', side_effect=[
                 _resp(json_data=primary), _resp(json_data=secondary)
             ]), \
             patch('fetch_streaks.save_off_results'):
            result = _fetch_streaks(season=2026)
        assert result['scoreless'][0]['ip'] == ''

    def test_top_n_limit_applied(self):
        many_hitters = [_hitter(i, f'Player {i}', '.300') for i in range(20)]
        responses = self._make_responses(avg_leaders=many_hitters)
        p1, p2, p3 = self._patches(responses)
        with p1, p2, p3:
            result = _fetch_streaks(season=2026)
        assert len(result['streaks']) <= fetch_streaks._TOP_N


# ---------------------------------------------------------------------------
# main() CLI entry point
# ---------------------------------------------------------------------------

from unittest.mock import patch as _patch
import sys as _sys


def test_main_runs_without_error(capsys):
    """main() parses sys.argv and prints results — exercises lines 157-169, 173."""
    fake_result = {
        'streaks':   [{'rank': 1, 'name': 'Aaron Judge', 'abbr': 'NYY', 'avg': '.350'}],
        'scoreless': [{'rank': 1, 'name': 'Gerrit Cole', 'abbr': 'NYY', 'era': '1.57'}],
    }
    with _patch('sys.argv', ['fetch_streaks']), \
         _patch('fetch_streaks.fetch_streaks', return_value=fake_result):
        from fetch_streaks import main
        main()
    out = capsys.readouterr().out
    assert 'Aaron Judge' in out
    assert 'Gerrit Cole' in out


def test_main_guard_via_runpy(capsys):
    """Cover line 173: the `if __name__ == '__main__': main()` guard."""
    import runpy
    import sys
    fake_result = {'streaks': [], 'scoreless': []}
    with _patch('sys.argv', ['fetch_streaks']), \
         _patch('fetch_streaks.fetch_streaks', return_value=fake_result):
        runpy.run_module('fetch_streaks', run_name='__main__', alter_sys=True)
