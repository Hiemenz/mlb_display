"""Tests for fetch_derby.py — Home Run Derby bracket fetch/transform.

Mocks all network access (fetch_derby.requests.get) and file I/O
(fetch_derby.save_off_results) following the pattern in test_fetch_playoff_bracket.py.
"""
import time as time_mod
from datetime import datetime
from unittest.mock import patch, MagicMock

import fetch_derby
from fetch_derby import (
    _find_asg_date, find_derby_event_id, fetch_derby_bracket_raw,
    transform_bracket, fetch_and_save_derby_bracket, _short_name,
    get_derby_date, _seed_to_player,
)


def _resp(status_code=200, json_data=None):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data if json_data is not None else {}
    m.raise_for_status = MagicMock()
    return m


def _seed(name, team_id, hr, winner, complete=True, started=True):
    return {
        'started': started,
        'complete': complete,
        'winner': winner,
        'player': {'id': team_id * 1000, 'fullName': name},
        'numHomeRuns': hr,
    }


class TestShortName:
    def test_two_part_name(self):
        assert _short_name('Cal Raleigh') == 'C. Raleigh'

    def test_single_word_name_unchanged(self):
        assert _short_name('Ohtani') == 'Ohtani'


class TestFindAsgDate:
    def test_returns_official_date_of_all_star_game(self):
        payload = {'dates': [{'games': [{'gameType': 'A', 'officialDate': '2026-07-14'}]}]}
        with patch('fetch_derby.requests.get', return_value=_resp(json_data=payload)):
            assert _find_asg_date(2026) == '2026-07-14'

    def test_no_asg_found_returns_none(self):
        with patch('fetch_derby.requests.get', return_value=_resp(json_data={'dates': []})):
            assert _find_asg_date(2026) is None


class TestFindDerbyEventId:
    def test_finds_event_one_day_before_asg(self):
        asg_resp = _resp(json_data={'dates': [{'games': [{'gameType': 'A', 'officialDate': '2026-07-14'}]}]})
        events_resp = _resp(json_data={'dates': [{'events': [
            {'id': 838655, 'name': '2026 MLB All-Star Workout Day: Home Run Derby'},
            {'id': 1, 'name': 'Ballpark Tour'},
        ]}]})
        with patch('fetch_derby.requests.get', side_effect=[asg_resp, events_resp]):
            event_id, event_date = find_derby_event_id(2026)
        assert event_id == 838655
        assert event_date == '2026-07-13'

    def test_no_asg_date_returns_none_none(self):
        with patch('fetch_derby.requests.get', return_value=_resp(json_data={'dates': []})):
            event_id, event_date = find_derby_event_id(2026)
        assert (event_id, event_date) == (None, None)

    def test_no_matching_event_scans_wider_window_then_gives_up(self):
        asg_resp = _resp(json_data={'dates': [{'games': [{'gameType': 'A', 'officialDate': '2026-07-14'}]}]})
        empty_events = _resp(json_data={'dates': [{'events': []}]})
        with patch('fetch_derby.requests.get', side_effect=[asg_resp, empty_events, empty_events, empty_events]):
            event_id, event_date = find_derby_event_id(2026)
        assert (event_id, event_date) == (None, None)


class TestFetchDerbyBracketRaw:
    def test_non_200_returns_none(self):
        with patch('fetch_derby.requests.get', return_value=_resp(status_code=404)):
            assert fetch_derby_bracket_raw(838655) is None

    def test_missing_rounds_key_returns_none(self):
        with patch('fetch_derby.requests.get', return_value=_resp(json_data={'info': {}})):
            assert fetch_derby_bracket_raw(838655) is None

    def test_valid_payload_returned(self):
        payload = {'info': {}, 'rounds': [], 'players': []}
        with patch('fetch_derby.requests.get', return_value=_resp(json_data=payload)):
            assert fetch_derby_bracket_raw(838655) == payload


class TestTransformBracket:
    def _raw(self):
        return {
            'info': {},
            'status': {'state': 'Final', 'currentRound': 3},
            'players': [
                {'id': 1000, 'fullName': 'Cal Raleigh', 'currentTeam': {'abbreviation': 'SEA'}},
                {'id': 2000, 'fullName': 'Oneil Cruz', 'currentTeam': {'abbreviation': 'PIT'}},
            ],
            'rounds': [
                {'round': 1, 'matchups': [
                    {'topSeed': _seed('Cal Raleigh', 1, 17, True), 'bottomSeed': _seed('Oneil Cruz', 2, 21, True)},
                ]},
                {'round': 2, 'matchups': [
                    {'topSeed': _seed('Cal Raleigh', 1, 19, True), 'bottomSeed': _seed('Oneil Cruz', 2, 13, False)},
                ]},
                {'round': 3, 'matchups': [
                    {'topSeed': _seed('Cal Raleigh', 1, 18, True), 'bottomSeed': _seed('Oneil Cruz', 2, 15, False)},
                ]},
            ],
        }

    def test_full_bracket_transform_and_champion(self):
        result = transform_bracket(self._raw(), '2025-07-14')
        assert result['event_date'] == '2025-07-14'
        assert result['round_status'] == 'Round 3 - Final'
        assert result['champion'] == 'C. Raleigh'
        assert len(result['matchups']['qf']) == 4  # padded to 4 slots
        assert len(result['matchups']['sf']) == 2  # padded to 2 slots
        qf0 = result['matchups']['qf'][0]
        assert qf0['complete'] is True
        assert qf0['players'][0] == {'name': 'C. Raleigh', 'abbr': 'SEA', 'hr': 17, 'winner': True}
        assert qf0['players'][1] == {'name': 'O. Cruz', 'abbr': 'PIT', 'hr': 21, 'winner': True}
        # unfilled qf/sf slots are TBD placeholders
        assert result['matchups']['qf'][1]['players'][0]['name'] == 'TBD'

    def test_missing_final_round_defaults_to_tbd(self):
        raw = self._raw()
        raw['rounds'] = raw['rounds'][:2]  # only qf + sf rounds present
        result = transform_bracket(raw, '2025-07-14')
        assert result['matchups']['final']['players'][0]['name'] == 'TBD'
        assert result['champion'] is None


class TestSeedToPlayer:
    def test_missing_seed_returns_tbd(self):
        assert _seed_to_player(None, {}) == {'name': 'TBD', 'abbr': '', 'hr': None, 'winner': False}

    def test_seed_without_player_returns_tbd(self):
        assert _seed_to_player({'started': True}, {}) == {'name': 'TBD', 'abbr': '', 'hr': None, 'winner': False}


class TestGetDerbyDate:
    def test_cache_miss_calls_lookup_and_saves(self):
        with patch('fetch_derby.load_json_file', return_value={}), \
             patch('fetch_derby.find_derby_event_id', return_value=(838655, '2026-07-13')) as mock_find, \
             patch('fetch_derby.save_off_results') as mock_save:
            event_date, event_id = get_derby_date(season=2026)
        assert (event_date, event_id) == ('2026-07-13', 838655)
        mock_find.assert_called_once_with(2026)
        mock_save.assert_called_once()
        assert mock_save.call_args.args[1] == 'derby_event_cache'

    def test_fresh_cache_skips_lookup(self):
        cache = {'season': 2026, 'event_id': 838655, 'event_date': '2026-07-13', 'fetched_at': time_mod.time()}
        with patch('fetch_derby.load_json_file', return_value=cache), \
             patch('fetch_derby.find_derby_event_id') as mock_find:
            event_date, event_id = get_derby_date(season=2026)
        assert (event_date, event_id) == ('2026-07-13', 838655)
        mock_find.assert_not_called()

    def test_stale_cache_triggers_refresh(self):
        cache = {'season': 2026, 'event_id': 1, 'event_date': 'old', 'fetched_at': 0}
        with patch('fetch_derby.load_json_file', return_value=cache), \
             patch('fetch_derby.find_derby_event_id', return_value=(838655, '2026-07-13')) as mock_find, \
             patch('fetch_derby.save_off_results'):
            event_date, event_id = get_derby_date(season=2026)
        assert (event_date, event_id) == ('2026-07-13', 838655)
        mock_find.assert_called_once()

    def test_force_refresh_bypasses_fresh_cache(self):
        cache = {'season': 2026, 'event_id': 1, 'event_date': 'old', 'fetched_at': time_mod.time()}
        with patch('fetch_derby.load_json_file', return_value=cache), \
             patch('fetch_derby.find_derby_event_id', return_value=(838655, '2026-07-13')) as mock_find, \
             patch('fetch_derby.save_off_results'):
            event_date, event_id = get_derby_date(season=2026, force_refresh=True)
        assert (event_date, event_id) == ('2026-07-13', 838655)
        mock_find.assert_called_once()

    def test_default_season_uses_current_year(self):
        with patch('fetch_derby.load_json_file', return_value={}), \
             patch('fetch_derby.find_derby_event_id', return_value=(None, None)) as mock_find, \
             patch('fetch_derby.save_off_results'):
            get_derby_date()
        mock_find.assert_called_once_with(datetime.now().year)


class TestFetchAndSaveDerbyBracket:
    def test_default_season_uses_current_year(self):
        with patch('fetch_derby.find_derby_event_id', return_value=(None, None)) as mock_find, \
             patch('fetch_derby.save_off_results') as mock_save:
            result = fetch_and_save_derby_bracket()
        assert result is None
        mock_find.assert_called_once_with(datetime.now().year)
        mock_save.assert_not_called()


    def test_no_event_found_returns_none(self):
        with patch('fetch_derby.find_derby_event_id', return_value=(None, None)), \
             patch('fetch_derby.save_off_results') as mock_save:
            result = fetch_and_save_derby_bracket(season=2026)
        assert result is None
        mock_save.assert_not_called()

    def test_no_bracket_data_yet_returns_none(self):
        with patch('fetch_derby.find_derby_event_id', return_value=(838655, '2026-07-13')), \
             patch('fetch_derby.fetch_derby_bracket_raw', return_value=None), \
             patch('fetch_derby.save_off_results') as mock_save:
            result = fetch_and_save_derby_bracket(season=2026)
        assert result is None
        mock_save.assert_not_called()

    def test_successful_fetch_saves_and_returns_result(self):
        raw = TestTransformBracket()._raw()
        with patch('fetch_derby.find_derby_event_id', return_value=(838655, '2026-07-13')), \
             patch('fetch_derby.fetch_derby_bracket_raw', return_value=raw), \
             patch('fetch_derby.save_off_results') as mock_save:
            result = fetch_and_save_derby_bracket(season=2026)
        assert result['champion'] == 'C. Raleigh'
        mock_save.assert_called_once_with(result, 'derby_bracket')

    def test_explicit_event_id_skips_lookup(self):
        raw = TestTransformBracket()._raw()
        with patch('fetch_derby.find_derby_event_id') as mock_find, \
             patch('fetch_derby.fetch_derby_bracket_raw', return_value=raw), \
             patch('fetch_derby.save_off_results'):
            fetch_and_save_derby_bracket(season=2026, event_id=838655)
        mock_find.assert_not_called()
