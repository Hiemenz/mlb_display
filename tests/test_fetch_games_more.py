"""
Additional unit tests for src/fetch_games.py targeting functions not covered by
tests/test_api_contract.py: network-backed helpers (win probability, challenge
lookup, odds, pitcher stat batching, team abbreviation lookups, schedule
scanning) and remaining parse_games()/wrapper branches.

Reuses _minimal_game_api()/_parse() from test_api_contract.py rather than
duplicating fixture builders.
"""
import os
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

import fetch_games
from fetch_games import (
    convert_time_z_to,
    fetch_win_probability,
    _fetch_challenge_team_abbr,
    _fetch_mlb_odds,
    _get_odds_cached,
    _pitcher_cache_key,
    _cache_get,
    _cache_set,
    _fetch_pitcher_eras,
    _fetch_decision_pitcher_stats,
    fetch_all_team_abbreviations,
    get_team_abbreviation,
    check_games_for_sport,
    find_next_game_date,
    parse_games,
    fetch_tomorrow_games,
    fetch_scoreboard_for_date,
    _pick_tv_channel,
    _attach_pregame_weather,
    _lookup_stadium,
)

from test_api_contract import _minimal_game_api, _parse


def _resp(status_code=200, json_data=None):
    """Build a MagicMock standing in for a requests.Response."""
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data if json_data is not None else {}
    return m


@pytest.fixture(autouse=True)
def _reset_stadium_cache():
    """_load_stadium_weather() memoizes into a module-level global; reset it
    around every test in this file so mocks of load_json_file take effect."""
    fetch_games._STADIUM_WEATHER_CACHE = None
    yield
    fetch_games._STADIUM_WEATHER_CACHE = None


@pytest.fixture(autouse=True)
def _clear_odds_api_key(monkeypatch):
    """A real ODDS_API_KEY may be present in the dev .env; parse_games() only
    calls the odds endpoint when this env var is set, and we don't want that
    branch silently activating (and hitting the real network) in tests that
    aren't specifically exercising odds attachment."""
    monkeypatch.delenv('ODDS_API_KEY', raising=False)


def _parse_isolated(api_games, sport_id=1, config=None):
    """Like test_api_contract._parse(), but also stubs out fetch_games.requests.get
    so Final-state games (which otherwise probe the real game-end-time live feed)
    never touch the network. Use for tests that only care about fields computed
    before any live/network branches (e.g. walk-off detection)."""
    captured = {}

    def fake_save(data, name):
        """Fake save."""
        captured[name] = data

    if config is None:
        config = {'timezone': 'America/Chicago'}

    with patch('fetch_games.save_off_results', side_effect=fake_save), \
         patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
         patch('fetch_games._attach_pregame_weather'), \
         patch('fetch_games.fetch_win_probability',
               return_value=(None, None, None, None, None, None, None)), \
         patch('fetch_games.requests.get', return_value=_resp(json_data={})):
        parse_games({'dates': [{'games': api_games}]}, sport_id=sport_id, config=config)

    return captured.get('games', {}).get('games', [])


# ===========================================================================
# convert_time_z_to
# ===========================================================================

class TestConvertTimeZTo:
    def test_chicago_summer_offset(self):
        """Chicago summer offset."""
        # 23:05 UTC in July -> CDT (UTC-5) -> 6:05 PM
        assert convert_time_z_to('2024-07-04T23:05:00Z', 'America/Chicago') == '6:05 PM'

    def test_new_york_summer_offset(self):
        """New york summer offset."""
        # 23:05 UTC in July -> EDT (UTC-4) -> 7:05 PM
        assert convert_time_z_to('2024-07-04T23:05:00Z', 'America/New_York') == '7:05 PM'

    def test_los_angeles_offset(self):
        """Los angeles offset."""
        # 23:05 UTC in July -> PDT (UTC-7) -> 4:05 PM
        assert convert_time_z_to('2024-07-04T23:05:00Z', 'America/Los_Angeles') == '4:05 PM'

    def test_default_timezone_is_chicago(self):
        """Default timezone is chicago."""
        assert convert_time_z_to('2024-07-04T23:05:00Z') == '6:05 PM'

    def test_midnight_becomes_12_am(self):
        """Midnight becomes 12 am."""
        # 06:00 UTC in Jan -> CST (UTC-6) -> 12:00 AM
        assert convert_time_z_to('2024-01-01T06:00:00Z', 'America/Chicago') == '12:00 AM'

    def test_noon_becomes_12_pm(self):
        """Noon becomes 12 pm."""
        # 18:00 UTC in Jan -> CST (UTC-6) -> 12:00 PM
        assert convert_time_z_to('2024-01-01T18:00:00Z', 'America/Chicago') == '12:00 PM'


# ===========================================================================
# _pick_tv_channel — favorite-home branch + national/first fallback
# ===========================================================================

class TestPickTvChannelExtra:
    def test_favorite_is_home_team(self):
        """Favorite is home team."""
        broadcasts = [
            {'type': 'TV', 'callSign': 'NESN', 'homeAway': 'away'},
            {'type': 'TV', 'callSign': 'MASN', 'homeAway': 'home'},
        ]
        result = _pick_tv_channel(broadcasts, 'BAL', 'BOS', 'BAL')
        assert result == 'MASN'

    def test_no_home_no_favorite_falls_back_to_first_tv(self):
        """No home no favorite falls back to first tv."""
        broadcasts = [
            {'type': 'TV', 'callSign': 'ESPN', 'homeAway': 'away'},
        ]
        result = _pick_tv_channel(broadcasts, None, 'BOS', 'BAL')
        assert result == 'ESPN'

    def test_uses_name_when_no_callsign(self):
        """Uses name when no callsign."""
        broadcasts = [{'type': 'TV', 'name': 'Peacock', 'homeAway': 'away'}]
        assert _pick_tv_channel(broadcasts, None, 'BOS', 'BAL') == 'Peacock'

    def test_favorite_side_with_no_matching_broadcast_falls_through(self):
        """Favorite side with no matching broadcast falls through."""
        # Favorite is away, but away has no TV entries -> falls to home local.
        broadcasts = [{'type': 'TV', 'callSign': 'MASN', 'homeAway': 'home'}]
        result = _pick_tv_channel(broadcasts, 'BOS', 'BOS', 'BAL')
        assert result == 'MASN'

    def test_no_broadcasts_returns_none(self):
        """No broadcasts returns none."""
        assert _pick_tv_channel([], 'BOS', 'BOS', 'BAL') is None
        assert _pick_tv_channel(None, 'BOS', 'BOS', 'BAL') is None


# ===========================================================================
# _lookup_stadium / _attach_pregame_weather
# ===========================================================================

class TestLookupStadium:
    def test_found_by_venue_id(self):
        """Found by venue id."""
        with patch('fetch_games.load_json_file',
                   return_value={'2392': {'roof': 'fixed', 'lat': 1, 'lon': 2}}):
            result = _lookup_stadium(2392, 'Daikin Park')
        assert result == {'roof': 'fixed', 'lat': 1, 'lon': 2}

    def test_not_found_returns_none(self):
        """Not found returns none."""
        with patch('fetch_games.load_json_file', return_value={}):
            assert _lookup_stadium(999, 'Nowhere Field') is None

    def test_fallback_by_venue_name(self):
        """Fallback by venue name."""
        stadiums = {
            '5': {'roof': 'open', 'lat': 3, 'lon': 4},
            '_name_fallback': {'Some Park': 5},
        }
        with patch('fetch_games.load_json_file', return_value=stadiums):
            result = _lookup_stadium(None, 'Some Park')
        assert result == {'roof': 'open', 'lat': 3, 'lon': 4}

    def test_venue_name_not_in_fallback_returns_none(self):
        """Venue name not in fallback returns none."""
        stadiums = {'_name_fallback': {}}
        with patch('fetch_games.load_json_file', return_value=stadiums):
            assert _lookup_stadium(None, 'Unknown Park') is None


class TestAttachPregameWeather:
    def _game_dict(self):
        """Game dict."""
        return {'game_date': '2026-07-04T23:05:00Z'}

    def _schedule_game(self, venue_id=10, venue_name='Test Park'):
        """Schedule game."""
        return {'venue': {'id': venue_id, 'name': venue_name}}

    def test_weather_disabled_short_circuits(self):
        """Weather disabled short circuits."""
        gd = self._game_dict()
        with patch('fetch_games.load_json_file', return_value={}):
            _attach_pregame_weather(gd, self._schedule_game(), {'weather': {'enabled': False}})
        assert 'weather_temp_f' not in gd
        assert 'roof_state' not in gd

    def test_no_stadium_match_leaves_game_dict_unchanged(self):
        """No stadium match leaves game dict unchanged."""
        gd = self._game_dict()
        with patch('fetch_games.load_json_file', return_value={}):
            _attach_pregame_weather(gd, self._schedule_game(), {})
        assert gd == self._game_dict()

    def test_fixed_roof_sets_roof_state(self):
        """Fixed roof sets roof state."""
        gd = self._game_dict()
        stadiums = {'10': {'roof': 'fixed', 'lat': 1, 'lon': 2}}
        with patch('fetch_games.load_json_file', return_value=stadiums), \
             patch('weather.get_forecast', return_value=None):
            _attach_pregame_weather(gd, self._schedule_game(), {})
        assert gd['roof_state'] == 'fixed'

    def test_always_closed_venue_id_sets_roof_state_even_if_not_fixed(self):
        """Always closed venue id sets roof state even if not fixed."""
        gd = self._game_dict()
        stadiums = {'2392': {'roof': 'retractable', 'lat': 1, 'lon': 2}}
        with patch('fetch_games.load_json_file', return_value=stadiums), \
             patch('weather.get_forecast', return_value=None):
            _attach_pregame_weather(gd, self._schedule_game(venue_id=2392), {})
        assert gd['roof_state'] == 'fixed'

    def test_forecast_none_leaves_weather_fields_unset(self):
        """Forecast none leaves weather fields unset."""
        gd = self._game_dict()
        stadiums = {'10': {'roof': 'open', 'lat': 1, 'lon': 2}}
        with patch('fetch_games.load_json_file', return_value=stadiums), \
             patch('weather.get_forecast', return_value=None):
            _attach_pregame_weather(gd, self._schedule_game(), {})
        assert 'weather_temp_f' not in gd

    def test_forecast_success_populates_weather_fields(self):
        """Forecast success populates weather fields."""
        gd = self._game_dict()
        stadiums = {'10': {'roof': 'open', 'lat': 1, 'lon': 2}}
        forecast = {'temp_f': 75, 'wind_mph': 5, 'wind_dir': 'NW', 'precip_pct': 10}
        with patch('fetch_games.load_json_file', return_value=stadiums), \
             patch('weather.get_forecast', return_value=forecast) as mock_fc:
            _attach_pregame_weather(gd, self._schedule_game(), {'weather': {'cache_ttl_minutes': 15}})
        assert gd['weather_temp_f'] == 75
        assert gd['weather_wind_mph'] == 5
        assert gd['weather_wind_dir'] == 'NW'
        assert gd['weather_precip_pct'] == 10
        mock_fc.assert_called_once()

    def test_import_error_on_weather_module_short_circuits(self):
        """Import error on weather module short circuits."""
        gd = self._game_dict()
        stadiums = {'10': {'roof': 'open', 'lat': 1, 'lon': 2}}
        with patch('fetch_games.load_json_file', return_value=stadiums), \
             patch.dict('sys.modules', {'weather': None}):
            _attach_pregame_weather(gd, self._schedule_game(), {})
        assert 'weather_temp_f' not in gd


# ===========================================================================
# fetch_win_probability
# ===========================================================================

class TestFetchWinProbability:
    def test_success_returns_scaled_percentages(self):
        """Success returns scaled percentages."""
        data = [
            {
                'awayTeamWinProbability': 0.55,
                'homeTeamWinProbability': 0.45,
                'about': {'inning': 5, 'isTopInning': True},
                'result': {'event': 'Single', 'eventType': 'single', 'rbi': 1, 'description': 'a single'},
            },
        ]
        with patch('fetch_games.requests.get', return_value=_resp(json_data=data)):
            result = fetch_win_probability(12345)
        away_wp, home_wp, last_play, inning, is_top, rbi, desc = result
        assert away_wp == pytest.approx(55.0)
        assert home_wp == pytest.approx(45.0)
        assert last_play == 'Single'
        assert inning == 5
        assert is_top is True
        assert rbi == 1
        assert desc == 'a single'

    def test_already_percent_scale_not_doubled(self):
        """Already percent scale not doubled."""
        data = [
            {
                'awayTeamWinProbability': 55.0,
                'homeTeamWinProbability': 45.0,
                'about': {'inning': 5, 'isTopInning': True},
                'result': {'event': 'Single', 'eventType': 'single'},
            },
        ]
        with patch('fetch_games.requests.get', return_value=_resp(json_data=data)):
            away_wp, home_wp, *_ = fetch_win_probability(12345)
        assert away_wp == 55.0
        assert home_wp == 45.0

    def test_skips_substitution_events_for_last_play(self):
        """Skips substitution events for last play."""
        data = [
            {'result': {'event': 'Single', 'eventType': 'single'}, 'about': {'inning': 3, 'isTopInning': False}},
            {'result': {'event': 'Sub', 'eventType': 'substitution'}, 'about': {'inning': 4, 'isTopInning': True}},
        ]
        with patch('fetch_games.requests.get', return_value=_resp(json_data=data)):
            _, _, last_play, inning, is_top, *_ = fetch_win_probability(12345)
        assert last_play == 'Single'
        assert inning == 3
        assert is_top is False

    def test_empty_list_returns_safe_defaults(self):
        """Empty list returns safe defaults."""
        with patch('fetch_games.requests.get', return_value=_resp(json_data=[])):
            result = fetch_win_probability(1)
        assert result == (None, None, None, None, None, 0, '')

    def test_non_list_payload_returns_safe_defaults(self):
        """Non list payload returns safe defaults."""
        with patch('fetch_games.requests.get', return_value=_resp(json_data={'foo': 'bar'})):
            result = fetch_win_probability(1)
        assert result == (None, None, None, None, None, 0, '')

    def test_network_exception_returns_safe_defaults(self):
        """Network exception returns safe defaults."""
        with patch('fetch_games.requests.get', side_effect=Exception('boom')):
            result = fetch_win_probability(1)
        assert result == (None, None, None, None, None, 0, '')

    def test_missing_win_probability_fields_returns_none_none(self):
        """Missing win probability fields returns none none."""
        data = [{'result': {'event': 'Single', 'eventType': 'single'}, 'about': {}}]
        with patch('fetch_games.requests.get', return_value=_resp(json_data=data)):
            away_wp, home_wp, *_ = fetch_win_probability(1)
        assert away_wp is None
        assert home_wp is None


# ===========================================================================
# _fetch_challenge_team_abbr
# ===========================================================================

class TestFetchChallengeTeamAbbr:
    def _live_payload(self, challenge_team_id, in_progress=True):
        """Live payload."""
        return {
            'liveData': {
                'plays': {
                    'currentPlay': {
                        'playEvents': [
                            {'reviewDetails': {'inProgress': in_progress, 'challengeTeamId': challenge_team_id}},
                        ],
                    },
                },
            },
        }

    def test_away_team_challenge(self):
        """Away team challenge."""
        resp = _resp(json_data=self._live_payload(111))
        with patch('fetch_games.requests.get', return_value=resp):
            result = _fetch_challenge_team_abbr(1, 111, 110, 'BOS', 'BAL')
        assert result == 'BOS'

    def test_home_team_challenge(self):
        """Home team challenge."""
        resp = _resp(json_data=self._live_payload(110))
        with patch('fetch_games.requests.get', return_value=resp):
            result = _fetch_challenge_team_abbr(1, 111, 110, 'BOS', 'BAL')
        assert result == 'BAL'

    def test_no_active_review_returns_empty_string(self):
        """No active review returns empty string."""
        resp = _resp(json_data=self._live_payload(111, in_progress=False))
        with patch('fetch_games.requests.get', return_value=resp):
            result = _fetch_challenge_team_abbr(1, 111, 110, 'BOS', 'BAL')
        assert result == ''

    def test_exception_returns_empty_string(self):
        """Exception returns empty string."""
        with patch('fetch_games.requests.get', side_effect=Exception('boom')):
            result = _fetch_challenge_team_abbr(1, 111, 110, 'BOS', 'BAL')
        assert result == ''


# ===========================================================================
# _fetch_mlb_odds
# ===========================================================================

class TestFetchMlbOdds:
    def test_success_extracts_h2h_prices(self):
        """Success extracts h2h prices."""
        payload = [
            {
                'home_team': 'Baltimore Orioles',
                'away_team': 'Boston Red Sox',
                'bookmakers': [
                    {'markets': [
                        {'key': 'h2h', 'outcomes': [
                            {'name': 'Baltimore Orioles', 'price': -150},
                            {'name': 'Boston Red Sox', 'price': 130},
                        ]},
                    ]},
                ],
            },
        ]
        resp = _resp(json_data=payload)
        with patch('fetch_games.requests.get', return_value=resp):
            result = _fetch_mlb_odds('fake-key')
        assert result == {('baltimore orioles', 'boston red sox'): (-150, 130)}

    def test_non_h2h_market_ignored(self):
        """Non h2h market ignored."""
        payload = [
            {
                'home_team': 'A', 'away_team': 'B',
                'bookmakers': [{'markets': [{'key': 'spreads', 'outcomes': []}]}],
            },
        ]
        with patch('fetch_games.requests.get', return_value=_resp(json_data=payload)):
            result = _fetch_mlb_odds('fake-key')
        assert result == {}

    def test_raise_for_status_error_returns_empty_dict(self):
        """Raise for status error returns empty dict."""
        resp = _resp()
        resp.raise_for_status.side_effect = Exception('HTTP 401')
        with patch('fetch_games.requests.get', return_value=resp):
            assert _fetch_mlb_odds('bad-key') == {}

    def test_network_exception_returns_empty_dict(self):
        """Network exception returns empty dict."""
        with patch('fetch_games.requests.get', side_effect=Exception('boom')):
            assert _fetch_mlb_odds('fake-key') == {}


# ===========================================================================
# _get_odds_cached
# ===========================================================================

class TestGetOddsCached:
    def test_fresh_cache_hit_skips_fetch(self):
        """Fresh cache hit skips fetch."""
        from datetime import date
        today = str(date.today())
        cache = {'date': today, 'odds': {'baltimore orioles|boston red sox': [-150, 130]}}
        with patch('fetch_games.load_json_file', return_value=cache), \
             patch('fetch_games._fetch_mlb_odds') as mock_fetch:
            result = _get_odds_cached('key')
        mock_fetch.assert_not_called()
        assert result == {('baltimore orioles', 'boston red sox'): (-150, 130)}

    def test_stale_cache_triggers_refetch_and_save(self):
        """Stale cache triggers refetch and save."""
        stale_cache = {'date': '2000-01-01', 'odds': {}}
        fresh_odds = {('a', 'b'): (100, -120)}
        with patch('fetch_games.load_json_file', return_value=stale_cache), \
             patch('fetch_games._fetch_mlb_odds', return_value=fresh_odds), \
             patch('fetch_games.save_off_results') as mock_save:
            result = _get_odds_cached('key')
        assert result == fresh_odds
        mock_save.assert_called_once()
        saved_data, saved_name = mock_save.call_args[0]
        assert saved_name == 'odds_cache'
        assert saved_data['odds'] == {'a|b': [100, -120]}

    def test_missing_cache_triggers_fetch(self):
        """Missing cache triggers fetch."""
        with patch('fetch_games.load_json_file', return_value=None), \
             patch('fetch_games._fetch_mlb_odds', return_value={}) as mock_fetch, \
             patch('fetch_games.save_off_results') as mock_save:
            result = _get_odds_cached('key')
        mock_fetch.assert_called_once()
        mock_save.assert_not_called()
        assert result == {}


# ===========================================================================
# Pitcher cache helpers
# ===========================================================================

class TestPitcherCacheHelpers:
    def test_pitcher_cache_key_sorted_and_joined(self):
        """Pitcher cache key sorted and joined."""
        assert _pitcher_cache_key([3, 1, 2]) == '1,2,3'

    def test_cache_get_returns_none_for_missing_bucket(self):
        """Cache get returns none for missing bucket."""
        assert _cache_get({}, 'era', 'k', '2025') is None

    def test_cache_get_returns_none_for_season_mismatch(self):
        """Cache get returns none for season mismatch."""
        cache = {'era': {'k': {'season': '2024', 'data': {}, 'fetched_at': datetime.now().isoformat()}}}
        assert _cache_get(cache, 'era', 'k', '2025') is None

    def test_cache_get_returns_none_when_stale(self):
        """Cache get returns none when stale."""
        old_time = (datetime.now() - timedelta(hours=2)).isoformat(timespec='seconds')
        cache = {'era': {'k': {'season': '2025', 'data': {'1': 'x'}, 'fetched_at': old_time}}}
        assert _cache_get(cache, 'era', 'k', '2025') is None

    def test_cache_get_returns_data_when_fresh(self):
        """Cache get returns data when fresh."""
        fresh_time = datetime.now().isoformat(timespec='seconds')
        cache = {'era': {'k': {'season': '2025', 'data': {'1': 'x'}, 'fetched_at': fresh_time}}}
        assert _cache_get(cache, 'era', 'k', '2025') == {'1': 'x'}

    def test_cache_get_handles_malformed_fetched_at(self):
        """Cache get handles malformed fetched at."""
        cache = {'era': {'k': {'season': '2025', 'data': {}, 'fetched_at': 'not-a-date'}}}
        assert _cache_get(cache, 'era', 'k', '2025') is None

    def test_cache_set_creates_bucket_if_missing(self):
        """Cache set creates bucket if missing."""
        cache = {}
        _cache_set(cache, 'era', 'k', '2025', {'1': 'x'})
        assert cache['era']['k']['season'] == '2025'
        assert cache['era']['k']['data'] == {'1': 'x'}
        assert 'fetched_at' in cache['era']['k']


class TestFetchPitcherEras:
    def test_empty_ids_returns_empty_without_request(self):
        """Empty ids returns empty without request."""
        with patch('fetch_games.requests.get') as mock_get:
            assert _fetch_pitcher_eras([], '2025') == {}
        mock_get.assert_not_called()

    def test_cache_hit_skips_request(self):
        """Cache hit skips request."""
        fresh_time = datetime.now().isoformat(timespec='seconds')
        key = _pitcher_cache_key([1])
        cache = {'era': {key: {'season': '2025', 'data': {'1': '10-5, 3.50 ERA'}, 'fetched_at': fresh_time}}}
        with patch('fetch_games.load_json_file', return_value=cache), \
             patch('fetch_games.requests.get') as mock_get:
            result = _fetch_pitcher_eras([1], '2025')
        mock_get.assert_not_called()
        assert result == {1: '10-5, 3.50 ERA'}

    def test_cache_miss_fetches_and_saves(self):
        """Cache miss fetches and saves."""
        payload = {
            'people': [
                {'id': 1, 'stats': [{'splits': [{'stat': {'era': '3.50', 'wins': 10, 'losses': 5}}]}]},
            ],
        }
        with patch('fetch_games.load_json_file', return_value={}), \
             patch('fetch_games.requests.get', return_value=_resp(json_data=payload)), \
             patch('fetch_games.save_off_results') as mock_save:
            result = _fetch_pitcher_eras([1], '2025')
        assert result == {1: '10-5, 3.50 ERA'}
        mock_save.assert_called_once()

    def test_negative_era_is_ignored(self):
        """Negative era is ignored."""
        payload = {
            'people': [
                {'id': 1, 'stats': [{'splits': [{'stat': {'era': '-.--', 'wins': 0, 'losses': 0}}]}]},
                {'id': 2, 'stats': [{'splits': [{'stat': {'era': '2.75', 'wins': 8, 'losses': 3}}]}]},
            ],
        }
        with patch('fetch_games.load_json_file', return_value={}), \
             patch('fetch_games.requests.get', return_value=_resp(json_data=payload)), \
             patch('fetch_games.save_off_results'):
            result = _fetch_pitcher_eras([1, 2], '2025')
        assert 1 not in result
        assert result[2] == '8-3, 2.75 ERA'

    def test_network_exception_returns_empty_dict(self):
        """Network exception returns empty dict."""
        with patch('fetch_games.load_json_file', return_value={}), \
             patch('fetch_games.requests.get', side_effect=Exception('boom')):
            assert _fetch_pitcher_eras([1], '2025') == {}

    def test_season_mismatch_forces_refetch(self):
        """Season mismatch forces refetch."""
        stale_time = datetime.now().isoformat(timespec='seconds')
        key = _pitcher_cache_key([1])
        cache = {'era': {key: {'season': '2024', 'data': {'1': 'old'}, 'fetched_at': stale_time}}}
        payload = {'people': [{'id': 1, 'stats': [{'splits': [{'stat': {'era': '4.00', 'wins': 1, 'losses': 1}}]}]}]}
        with patch('fetch_games.load_json_file', return_value=cache), \
             patch('fetch_games.requests.get', return_value=_resp(json_data=payload)), \
             patch('fetch_games.save_off_results'):
            result = _fetch_pitcher_eras([1], '2025')
        assert result == {1: '1-1, 4.00 ERA'}


class TestFetchDecisionPitcherStats:
    def test_empty_ids_returns_empty(self):
        """Empty ids returns empty."""
        assert _fetch_decision_pitcher_stats([], '2025') == {}
        assert _fetch_decision_pitcher_stats([None, None], '2025') == {}

    def test_cache_hit_skips_request(self):
        """Cache hit skips request."""
        fresh_time = datetime.now().isoformat(timespec='seconds')
        key = _pitcher_cache_key([1])
        cache = {'decision': {key: {'season': '2025', 'data': {'1': {'record': '10-5', 'saves': 2}},
                                     'fetched_at': fresh_time}}}
        with patch('fetch_games.load_json_file', return_value=cache), \
             patch('fetch_games.requests.get') as mock_get:
            result = _fetch_decision_pitcher_stats([1], '2025')
        mock_get.assert_not_called()
        assert result == {1: {'record': '10-5', 'saves': 2}}

    def test_cache_miss_fetches_wins_losses_saves(self):
        """Cache miss fetches wins losses saves."""
        payload = {
            'people': [
                {'id': 42, 'stats': [{'splits': [{'stat': {'wins': 3, 'losses': 1, 'saves': 12}}]}]},
            ],
        }
        with patch('fetch_games.load_json_file', return_value={}), \
             patch('fetch_games.requests.get', return_value=_resp(json_data=payload)), \
             patch('fetch_games.save_off_results') as mock_save:
            result = _fetch_decision_pitcher_stats([42], '2025')
        assert result == {42: {'record': '3-1', 'saves': 12}}
        mock_save.assert_called_once()

    def test_missing_saves_defaults_to_zero(self):
        """Missing saves defaults to zero."""
        payload = {'people': [{'id': 1, 'stats': [{'splits': [{'stat': {'wins': 1, 'losses': 0}}]}]}]}
        with patch('fetch_games.load_json_file', return_value={}), \
             patch('fetch_games.requests.get', return_value=_resp(json_data=payload)), \
             patch('fetch_games.save_off_results'):
            result = _fetch_decision_pitcher_stats([1], '2025')
        assert result[1]['saves'] == 0

    def test_network_exception_returns_empty_dict(self):
        """Network exception returns empty dict."""
        with patch('fetch_games.load_json_file', return_value={}), \
             patch('fetch_games.requests.get', side_effect=Exception('boom')):
            assert _fetch_decision_pitcher_stats([1], '2025') == {}


# ===========================================================================
# fetch_all_team_abbreviations / get_team_abbreviation
# ===========================================================================

class TestFetchAllTeamAbbreviations:
    def test_success_saves_and_returns_mapping(self):
        """Success saves and returns mapping."""
        payload = {'teams': [{'id': 147, 'abbreviation': 'NYY', 'name': 'New York Yankees'}]}
        with patch('fetch_games.requests.get', return_value=_resp(json_data=payload)), \
             patch('fetch_games.save_off_results') as mock_save:
            result = fetch_all_team_abbreviations(sport_id=1)
        assert result == {'147': 'NYY'}
        mock_save.assert_called_once_with({'team_abbreviation': {'147': 'NYY'}}, 'teams')

    def test_wbc_override_applied(self):
        """Wbc override applied."""
        payload = {'teams': [{'id': 9999, 'abbreviation': 'COL', 'name': 'Colombia'}]}
        with patch('fetch_games.requests.get', return_value=_resp(json_data=payload)), \
             patch('fetch_games.save_off_results'):
            result = fetch_all_team_abbreviations(sport_id=8)
        assert result == {'9999': 'CLM'}

    def test_non_200_status_returns_empty(self):
        """Non 200 status returns empty."""
        with patch('fetch_games.requests.get', return_value=_resp(status_code=500)), \
             patch('fetch_games.save_off_results') as mock_save:
            result = fetch_all_team_abbreviations(sport_id=1)
        assert result == {}
        mock_save.assert_not_called()

    def test_exception_returns_empty(self):
        """Exception returns empty."""
        with patch('fetch_games.requests.get', side_effect=Exception('boom')):
            assert fetch_all_team_abbreviations(sport_id=1) == {}


class TestGetTeamAbbreviation:
    def test_success_returns_abbreviation(self):
        """Success returns abbreviation."""
        payload = {'teams': [{'abbreviation': 'NYY'}]}
        with patch('fetch_games.requests.get', return_value=_resp(json_data=payload)):
            assert get_team_abbreviation(147) == 'NYY'

    def test_missing_abbreviation_returns_fallback(self):
        """Missing abbreviation returns fallback."""
        payload = {'teams': [{}]}
        with patch('fetch_games.requests.get', return_value=_resp(json_data=payload)):
            assert get_team_abbreviation(147) == 'T147'

    def test_non_200_returns_fallback(self):
        """Non 200 returns fallback."""
        with patch('fetch_games.requests.get', return_value=_resp(status_code=404)):
            assert get_team_abbreviation(147) == 'T147'

    def test_exception_returns_fallback(self):
        """Exception returns fallback."""
        with patch('fetch_games.requests.get', side_effect=Exception('boom')):
            assert get_team_abbreviation(147) == 'T147'


# ===========================================================================
# check_games_for_sport
# ===========================================================================

class TestCheckGamesForSport:
    def test_no_dates_returns_zero(self):
        """No dates returns zero."""
        with patch('fetch_games.requests.get', return_value=_resp(json_data={'dates': []})):
            assert check_games_for_sport('2026-07-01', 1) == 0

    def test_games_present_returns_count(self):
        """Games present returns count."""
        payload = {'dates': [{'games': [{'gameType': 'R'}, {'gameType': 'R'}]}]}
        with patch('fetch_games.requests.get', return_value=_resp(json_data=payload)):
            assert check_games_for_sport('2026-07-01', 8) == 2

    def test_sport_1_filters_out_spring_training_when_regular_present(self):
        """Sport 1 filters out spring training when regular present."""
        payload = {'dates': [{'games': [
            {'gameType': 'R'}, {'gameType': 'S'}, {'gameType': 'E'},
        ]}]}
        with patch('fetch_games.requests.get', return_value=_resp(json_data=payload)):
            assert check_games_for_sport('2026-03-15', 1) == 1

    def test_sport_1_keeps_spring_training_when_no_regular_games(self):
        """Sport 1 keeps spring training when no regular games."""
        payload = {'dates': [{'games': [{'gameType': 'S'}, {'gameType': 'S'}]}]}
        with patch('fetch_games.requests.get', return_value=_resp(json_data=payload)):
            assert check_games_for_sport('2026-03-15', 1) == 2

    def test_non_sport_1_not_filtered(self):
        """Non sport 1 not filtered."""
        payload = {'dates': [{'games': [{'gameType': 'S'}]}]}
        with patch('fetch_games.requests.get', return_value=_resp(json_data=payload)):
            assert check_games_for_sport('2026-03-15', 16) == 1

    def test_non_200_returns_zero(self):
        """Non 200 returns zero."""
        with patch('fetch_games.requests.get', return_value=_resp(status_code=500)):
            assert check_games_for_sport('2026-07-01', 1) == 0

    def test_exception_returns_zero(self):
        """Exception returns zero."""
        with patch('fetch_games.requests.get', side_effect=Exception('boom')):
            assert check_games_for_sport('2026-07-01', 1) == 0


# ===========================================================================
# find_next_game_date
# ===========================================================================

class TestFindNextGameDate:
    def test_found_on_later_date_entry(self):
        """Found on later date entry."""
        payload = {'dates': [
            {'date': '2026-07-01', 'games': []},
            {'date': '2026-07-02', 'games': []},
            {'date': '2026-07-03', 'games': [{'gameType': 'R'}]},
        ]}
        with patch('fetch_games.requests.get', return_value=_resp(json_data=payload)) as mock_get:
            result = find_next_game_date([1], '2026-07-01')
        assert result == '2026-07-03'
        assert mock_get.call_count == 1

    def test_games_on_from_date_itself_are_found(self):
        """Games on from_date itself count as the next game date.

        The caller always passes "tomorrow" relative to a confirmed no-games
        day, so from_date_str is never itself already-known-empty — skipping
        it caused real games that day (e.g. the All-Star Game) to be missed.
        """
        payload = {'dates': [
            {'date': '2026-07-01', 'games': [{'gameType': 'R'}]},
            {'date': '2026-07-02', 'games': []},
        ]}
        with patch('fetch_games.requests.get', return_value=_resp(json_data=payload)):
            result = find_next_game_date([1], '2026-07-01')
        assert result == '2026-07-01'

    def test_falls_through_sport_priority_list(self):
        """Falls through sport priority list."""
        def fake_get(url, *args, **kwargs):
            """Fake get."""
            if 'sportId=1' in url:
                return _resp(json_data={'dates': [{'date': '2026-07-02', 'games': []}]})
            return _resp(json_data={'dates': [{'date': '2026-07-02', 'games': [{'gameType': 'R'}]}]})

        with patch('fetch_games.requests.get', side_effect=fake_get) as mock_get:
            result = find_next_game_date([1, 8], '2026-07-01')
        assert result == '2026-07-02'
        assert mock_get.call_count == 2

    def test_never_found_returns_none(self):
        """Never found returns none."""
        payload = {'dates': [{'date': '2026-07-02', 'games': []}]}
        with patch('fetch_games.requests.get', return_value=_resp(json_data=payload)):
            result = find_next_game_date([1, 8], '2026-07-01')
        assert result is None

    def test_sport_1_spring_training_only_still_counts(self):
        """Sport 1 spring training only still counts."""
        payload = {'dates': [{'date': '2026-03-02', 'games': [{'gameType': 'S'}]}]}
        with patch('fetch_games.requests.get', return_value=_resp(json_data=payload)):
            result = find_next_game_date([1], '2026-03-01')
        assert result == '2026-03-02'

    def test_non_200_response_treated_as_not_found(self):
        """Non 200 response treated as not found."""
        with patch('fetch_games.requests.get', return_value=_resp(status_code=500)):
            assert find_next_game_date([1], '2026-07-01') is None

    def test_exception_is_caught_and_continues(self):
        """Exception is caught and continues."""
        with patch('fetch_games.requests.get', side_effect=Exception('boom')):
            assert find_next_game_date([1, 8], '2026-07-01') is None


# ===========================================================================
# parse_games — remaining branches (live feed extras, pitcher batching,
# game-end-time caching, odds attachment, walk-off detection)
# ===========================================================================

class TestParseGamesLiveDetails:
    def test_win_probability_attached_when_configured(self):
        """Win probability attached when configured."""
        api_game = _minimal_game_api(state='In Progress', current_inning=5, inning_state='Top')
        config = {'timezone': 'America/Chicago', 'scoreboard_win_probability': True}
        with patch('fetch_games.save_off_results'), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games.fetch_win_probability',
                   return_value=(60.0, 40.0, 'Single', 5, True, 1, 'a single')):
            captured = {}

            def fake_save(data, name):
                """Fake save."""
                captured[name] = data
            with patch('fetch_games.save_off_results', side_effect=fake_save):
                parse_games({'dates': [{'games': [api_game]}]}, sport_id=1, config=config)
        game = captured['games']['games'][0]
        assert game['away_win_probability'] == 60.0
        assert game['home_win_probability'] == 40.0

    def test_max_live_calls_limits_fetch_win_probability(self):
        """Max live calls limits fetch win probability."""
        games_api = [
            _minimal_game_api(game_pk=1, state='In Progress', current_inning=1, inning_state='Top'),
            _minimal_game_api(game_pk=2, away_id=200, home_id=201, state='In Progress',
                               current_inning=1, inning_state='Top'),
        ]
        config = {'timezone': 'America/Chicago', 'max_live_game_calls': 1}
        with patch('fetch_games.save_off_results'), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games.fetch_win_probability',
                   return_value=(None, None, None, None, None, 0, '')) as mock_wp:
            parse_games({'dates': [{'games': games_api}]}, sport_id=1, config=config)
        assert mock_wp.call_count == 1

    def test_featured_abbr_filters_live_calls(self):
        """Featured abbr filters live calls."""
        api_game = _minimal_game_api(away_abbr='BOS', away_id=111, home_abbr='BAL', home_id=110,
                                      state='In Progress', current_inning=1, inning_state='Top')
        config = {'timezone': 'America/Chicago', '_featured_abbr': 'NYY'}
        with patch('fetch_games.save_off_results'), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games.fetch_win_probability',
                   return_value=(None, None, None, None, None, 0, '')) as mock_wp:
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1, config=config)
        mock_wp.assert_not_called()

    def test_challenge_state_fetches_challenge_team_abbr(self):
        """Challenge state fetches challenge team abbr."""
        api_game = _minimal_game_api(state='Player challenge', current_inning=5, inning_state='Top')
        config = {'timezone': 'America/Chicago'}
        captured = {}

        def fake_save(data, name):
            """Fake save."""
            captured[name] = data
        with patch('fetch_games.save_off_results', side_effect=fake_save), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games.fetch_win_probability',
                   return_value=(None, None, None, None, None, 0, '')), \
             patch('fetch_games._fetch_challenge_team_abbr', return_value='BOS') as mock_challenge:
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1, config=config)
        mock_challenge.assert_called_once()
        assert captured['games']['games'][0]['challenge_team_abbr'] == 'BOS'

    def test_scoreboard_live_details_merges_extras(self):
        """Scoreboard live details merges extras."""
        api_game = _minimal_game_api(state='In Progress', current_inning=5, inning_state='Top')
        config = {'timezone': 'America/Chicago', 'scoreboard_live_details': True}
        captured = {}

        def fake_save(data, name):
            """Fake save."""
            captured[name] = data
        extras = {'pitch_count': 42, 'last_play': None}
        with patch('fetch_games.save_off_results', side_effect=fake_save), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games.fetch_win_probability',
                   return_value=(None, None, 'Double', 5, True, 2, 'a double')), \
             patch('game_detail_fetch.fetch_scoreboard_live_extras', return_value=extras):
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1, config=config)
        game = captured['games']['games'][0]
        assert game['pitch_count'] == 42
        # extras['last_play'] is None -> must not clobber the win-probability last_play
        assert game['last_play'] == 'Double'

    def test_between_innings_pc_restores_inning_state(self):
        """Between innings pc restores inning state."""
        api_game = _minimal_game_api(state='In Progress', current_inning=5, inning_state='Bottom')
        config = {'timezone': 'America/Chicago', 'scoreboard_live_details': True}
        captured = {}

        def fake_save(data, name):
            """Fake save."""
            captured[name] = data
        extras = {'sub_event': 'PC: 1-2', 'at_bat_pitch_count': 0}
        with patch('fetch_games.save_off_results', side_effect=fake_save), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games.fetch_win_probability',
                   return_value=(None, None, None, None, None, 0, '')), \
             patch('game_detail_fetch.fetch_scoreboard_live_extras', return_value=extras), \
             patch('game_detail_fetch.fetch_between_inning_info',
                   return_value={'last_play': None}):
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1, config=config)
        game = captured['games']['games'][0]
        assert game['inningState'] == 'Middle'

    def test_between_innings_pc_top_inning_state_becomes_end(self):
        """When inningState is 'Top' (not 'Bottom'), the PC restore branch must
        flip it to 'End', decrement current_inning, and recompute the ordinal."""
        api_game = _minimal_game_api(state='In Progress', current_inning=5, inning_state='Top')
        config = {'timezone': 'America/Chicago', 'scoreboard_live_details': True}
        captured = {}

        def fake_save(data, name):
            """Fake save."""
            captured[name] = data
        extras = {'sub_event': 'PC: 1-2', 'at_bat_pitch_count': 0}
        with patch('fetch_games.save_off_results', side_effect=fake_save), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games.fetch_win_probability',
                   return_value=(None, None, None, None, None, 0, '')), \
             patch('game_detail_fetch.fetch_scoreboard_live_extras', return_value=extras), \
             patch('game_detail_fetch.fetch_between_inning_info',
                   return_value={'last_play': None}):
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1, config=config)
        game = captured['games']['games'][0]
        assert game['inningState'] == 'End'
        assert game['current_inning'] == 4
        assert game['currentInningOrdinal'] == '4th'

    def test_inning_state_middle_triggers_between_inning_fetch(self):
        """Inning state middle triggers between inning fetch."""
        api_game = _minimal_game_api(state='In Progress', current_inning=5, inning_state='Middle')
        config = {'timezone': 'America/Chicago'}
        captured = {}

        def fake_save(data, name):
            """Fake save."""
            captured[name] = data
        with patch('fetch_games.save_off_results', side_effect=fake_save), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games.fetch_win_probability',
                   return_value=(None, None, 'Homer', 5, True, 1, 'a homer')), \
             patch('game_detail_fetch.fetch_between_inning_info',
                   return_value={'next_batter_1': 'Player A', 'last_play': None}) as mock_bi:
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1, config=config)
        mock_bi.assert_called_once()
        game = captured['games']['games'][0]
        # bi_info['last_play'] is None -> must not clobber existing win-probability last_play
        assert game['last_play'] == 'Homer'
        assert game['next_batter_1'] == 'Player A'

    def test_delayed_state_with_current_inning_fetches_between_inning_info(self):
        """Delayed state with current inning fetches between inning info."""
        api_game = _minimal_game_api(state='Delayed', current_inning=3, inning_state='Bottom')
        config = {'timezone': 'America/Chicago'}
        captured = {}

        def fake_save(data, name):
            """Fake save."""
            captured[name] = data
        with patch('fetch_games.save_off_results', side_effect=fake_save), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('game_detail_fetch.fetch_between_inning_info',
                   return_value={'next_pitcher': 'Some Pitcher'}) as mock_bi:
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1, config=config)
        mock_bi.assert_called_once_with(api_game['gamePk'], 'Middle')
        game = captured['games']['games'][0]
        assert game['next_pitcher'] == 'Some Pitcher'


class TestParseGamesWalkOff:
    def _final_game(self, home_wins, away_innings, home_innings):
        """Final game."""
        api_game = _minimal_game_api(state='Final', away_runs=sum(r or 0 for r in away_innings),
                                      home_runs=sum(r or 0 for r in home_innings))
        api_game['teams']['home']['isWinner'] = home_wins
        api_game['teams']['away']['isWinner'] = not home_wins
        api_game['linescore']['innings'] = [
            {'away': {'runs': a}, 'home': {'runs': h}} for a, h in zip(away_innings, home_innings)
        ]
        return api_game

    def test_home_walk_off_detected(self):
        """Home walk off detected."""
        api_game = self._final_game(True, [1, 0, 0], [0, 0, 2])
        games = _parse_isolated([api_game])
        assert games[0]['walk_off'] is True

    def test_away_winner_never_walk_off(self):
        """Away winner never walk off."""
        api_game = self._final_game(False, [2, 0, 0], [0, 0, 0])
        games = _parse_isolated([api_game])
        assert games[0]['walk_off'] is False

    def test_home_winner_but_no_runs_in_final_inning_not_walk_off(self):
        """Home winner but no runs in final inning not walk off."""
        api_game = self._final_game(True, [0, 0, 1], [1, 1, 0])
        games = _parse_isolated([api_game])
        assert games[0]['walk_off'] is False

    def test_unequal_inning_lengths_not_walk_off(self):
        """Unequal inning lengths not walk off."""
        api_game = self._final_game(True, [1, 0], [0, 0, 2])
        games = _parse_isolated([api_game])
        assert games[0]['walk_off'] is False


class TestParseGamesPitcherAndDecisionBatching:
    def test_probable_pitcher_era_attached_when_no_note(self):
        """Probable pitcher era attached when no note."""
        api_game = _minimal_game_api()
        api_game['teams']['away']['probablePitcher'] = {'id': 501, 'fullName': 'A Pitcher'}
        api_game['teams']['home']['probablePitcher'] = {'id': 502, 'fullName': 'H Pitcher'}
        with patch('fetch_games.save_off_results') as mock_save, \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games._attach_pregame_weather'), \
             patch('fetch_games._fetch_pitcher_eras',
                   return_value={501: '10-5, 3.00 ERA', 502: '8-6, 4.20 ERA'}) as mock_eras:
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1,
                        config={'timezone': 'America/Chicago'})
        mock_eras.assert_called_once()
        saved_games = mock_save.call_args_list[0][0][0]['games']
        assert saved_games[0]['away_probable_note'] == '10-5, 3.00 ERA'
        assert saved_games[0]['home_probable_note'] == '8-6, 4.20 ERA'

    def test_existing_probable_note_not_overwritten(self):
        """Existing probable note not overwritten."""
        api_game = _minimal_game_api()
        api_game['teams']['away']['probablePitcher'] = {
            'id': 501, 'fullName': 'A Pitcher', 'note': 'Existing note',
        }
        with patch('fetch_games.save_off_results') as mock_save, \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games._attach_pregame_weather'), \
             patch('fetch_games._fetch_pitcher_eras', return_value={501: '10-5, 3.00 ERA'}):
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1,
                        config={'timezone': 'America/Chicago'})
        saved_games = mock_save.call_args_list[0][0][0]['games']
        assert saved_games[0]['away_probable_note'] == 'Existing note'

    def test_no_probable_pitchers_skips_era_fetch(self):
        """No probable pitchers skips era fetch."""
        api_game = _minimal_game_api()
        with patch('fetch_games.save_off_results'), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games._attach_pregame_weather'), \
             patch('fetch_games._fetch_pitcher_eras') as mock_eras:
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1,
                        config={'timezone': 'America/Chicago'})
        mock_eras.assert_not_called()

    def test_decision_pitcher_stats_attached(self):
        """Decision pitcher stats attached."""
        api_game = _minimal_game_api(state='Final', away_runs=5, home_runs=3)
        api_game['decisions'] = {
            'winner': {'id': 1, 'fullName': 'Winner Pitcher'},
            'loser': {'id': 2, 'fullName': 'Loser Pitcher'},
            'save': {'id': 3, 'fullName': 'Save Pitcher'},
        }
        decision_stats = {
            1: {'record': '10-2', 'saves': 0},
            2: {'record': '5-8', 'saves': 0},
            3: {'record': '0-0', 'saves': 20},
        }
        with patch('fetch_games.save_off_results') as mock_save, \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games.requests.get', return_value=_resp(json_data={})), \
             patch('fetch_games._fetch_decision_pitcher_stats', return_value=decision_stats) as mock_dec:
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1,
                        config={'timezone': 'America/Chicago'})
        mock_dec.assert_called_once()
        saved_games = mock_save.call_args_list[0][0][0]['games']
        g = saved_games[0]
        assert g['winner_record'] == '10-2'
        assert g['loser_record'] == '5-8'
        assert g['saver_saves'] == 20

    def test_no_decisions_skips_decision_fetch(self):
        """No decisions skips decision fetch."""
        api_game = _minimal_game_api()
        with patch('fetch_games.save_off_results'), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games._attach_pregame_weather'), \
             patch('fetch_games._fetch_decision_pitcher_stats') as mock_dec:
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1,
                        config={'timezone': 'America/Chicago'})
        mock_dec.assert_not_called()


class TestParseGamesEndTimeCache:
    def test_cache_hit_skips_live_feed_request(self):
        """Cache hit skips live feed request."""
        api_game = _minimal_game_api(game_pk=555, state='Final', away_runs=5, home_runs=3)
        end_cache = {'555': '2026-07-01T02:00:00Z'}
        with patch('fetch_games.save_off_results') as mock_save, \
             patch('fetch_games.load_json_file',
                   side_effect=lambda name: end_cache if name == 'game_end_time_cache.json'
                   else {'team_abbreviation': {}}), \
             patch('fetch_games.requests.get') as mock_get:
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1,
                        config={'timezone': 'America/Chicago'})
        mock_get.assert_not_called()
        saved_games = mock_save.call_args_list[0][0][0]['games']
        assert saved_games[0]['game_end_time_utc'] == '2026-07-01T02:00:00Z'

    def test_cache_miss_fetches_and_persists(self):
        """Cache miss fetches and persists."""
        api_game = _minimal_game_api(game_pk=556, state='Final', away_runs=5, home_runs=3)
        live_payload = {'liveData': {'plays': {'currentPlay': {'about': {'endTime': '2026-07-01T03:00:00Z'}}}}}

        def fake_load(name):
            """Fake load."""
            if name == 'game_end_time_cache.json':
                return {}
            return {'team_abbreviation': {}}

        with patch('fetch_games.save_off_results') as mock_save, \
             patch('fetch_games.load_json_file', side_effect=fake_load), \
             patch('fetch_games.requests.get', return_value=_resp(json_data=live_payload)):
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1,
                        config={'timezone': 'America/Chicago'})
        saved_names = [c[0][1] for c in mock_save.call_args_list]
        assert 'game_end_time_cache' in saved_names
        saved_games = mock_save.call_args_list[[c[0][1] for c in mock_save.call_args_list].index('games')][0][0]['games']
        assert saved_games[0]['game_end_time_utc'] == '2026-07-01T03:00:00Z'

    def test_end_time_fetch_exception_is_swallowed(self):
        """End time fetch exception is swallowed."""
        api_game = _minimal_game_api(game_pk=557, state='Final', away_runs=5, home_runs=3)

        def fake_load(name):
            """Fake load."""
            if name == 'game_end_time_cache.json':
                return {}
            return {'team_abbreviation': {}}

        with patch('fetch_games.save_off_results') as mock_save, \
             patch('fetch_games.load_json_file', side_effect=fake_load), \
             patch('fetch_games.requests.get', side_effect=Exception('boom')):
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1,
                        config={'timezone': 'America/Chicago'})
        saved_games = mock_save.call_args_list[0][0][0]['games']
        assert 'game_end_time_utc' not in saved_games[0]

    def test_non_final_game_never_hits_end_time_cache(self):
        """Non final game never hits end time cache."""
        api_game = _minimal_game_api(state='Scheduled')
        with patch('fetch_games.save_off_results'), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games._attach_pregame_weather'), \
             patch('fetch_games.requests.get') as mock_get:
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1,
                        config={'timezone': 'America/Chicago'})
        mock_get.assert_not_called()


class TestParseGamesOddsAttachment:
    def test_odds_attached_to_pregame_games_when_matched(self):
        """Odds attached to pregame games when matched."""
        api_game = _minimal_game_api(state='Scheduled')
        odds_map = {('baltimore orioles', 'boston red sox'): (-150, 130)}
        with patch('fetch_games.save_off_results') as mock_save, \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games._attach_pregame_weather'), \
             patch.dict(os.environ, {'ODDS_API_KEY': 'fake-key'}), \
             patch('fetch_games._get_odds_cached', return_value=odds_map) as mock_odds:
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1,
                        config={'timezone': 'America/Chicago'})
        mock_odds.assert_called_once_with('fake-key')
        saved_games = mock_save.call_args_list[0][0][0]['games']
        assert saved_games[0]['home_ml'] == -150
        assert saved_games[0]['away_ml'] == 130

    def test_odds_loop_skips_non_pregame_games_in_mixed_batch(self):
        """A mix of one pre-game game and one Final game must only attach
        odds to the pre-game entry, skipping (continue) the Final one."""
        pregame_game = _minimal_game_api(game_pk=1, state='Scheduled')
        final_game = _minimal_game_api(game_pk=2, away_id=200, home_id=201, state='Final',
                                        away_runs=4, home_runs=2)
        odds_map = {('baltimore orioles', 'boston red sox'): (-150, 130)}
        with patch('fetch_games.save_off_results') as mock_save, \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games._attach_pregame_weather'), \
             patch('fetch_games.requests.get', return_value=_resp(json_data={})), \
             patch.dict(os.environ, {'ODDS_API_KEY': 'fake-key'}), \
             patch('fetch_games._get_odds_cached', return_value=odds_map):
            parse_games({'dates': [{'games': [pregame_game, final_game]}]}, sport_id=1,
                        config={'timezone': 'America/Chicago'})
        saved_games = mock_save.call_args_list[0][0][0]['games']
        assert saved_games[0]['home_ml'] == -150
        assert 'home_ml' not in saved_games[1]

    def test_no_odds_api_key_skips_odds_lookup(self):
        """No odds api key skips odds lookup."""
        api_game = _minimal_game_api(state='Scheduled')
        with patch('fetch_games.save_off_results'), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games._attach_pregame_weather'), \
             patch.dict(os.environ, {}, clear=False), \
             patch('fetch_games._get_odds_cached') as mock_odds:
            os.environ.pop('ODDS_API_KEY', None)
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1,
                        config={'timezone': 'America/Chicago'})
        mock_odds.assert_not_called()

    def test_no_pregame_games_skips_odds_lookup(self):
        """No pregame games skips odds lookup."""
        api_game = _minimal_game_api(state='Final', away_runs=1, home_runs=0)
        with patch('fetch_games.save_off_results'), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games.requests.get', return_value=_resp(json_data={})), \
             patch.dict(os.environ, {'ODDS_API_KEY': 'fake-key'}), \
             patch('fetch_games._get_odds_cached') as mock_odds:
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1,
                        config={'timezone': 'America/Chicago'})
        mock_odds.assert_not_called()

    def test_config_defaults_when_none_passed(self):
        """Config defaults when none passed."""
        api_game = _minimal_game_api(state='Scheduled')
        with patch('fetch_games.save_off_results'), \
             patch('fetch_games.load_json_file', return_value={'team_abbreviation': {}}), \
             patch('fetch_games._attach_pregame_weather'), \
             patch('fetch_games.load_config', return_value={'timezone': 'America/Chicago'}) as mock_cfg:
            parse_games({'dates': [{'games': [api_game]}]}, sport_id=1, config=None)
        mock_cfg.assert_called_once()


# ===========================================================================
# fetch_tomorrow_games
# ===========================================================================

class TestFetchTomorrowGames:
    def test_successful_fetch_saves_minimal_games(self):
        """Successful fetch saves minimal games."""
        schedule_payload = {'dates': [{'games': [
            {'teams': {'away': {'team': {'id': 111}}, 'home': {'team': {'id': 110}}},
             'gameDate': '2026-07-02T23:05:00Z', 'gamePk': 777, 'gameType': 'R'},
        ]}]}
        with patch('fetch_games.check_games_for_sport', return_value=1), \
             patch('fetch_games.requests.get', return_value=_resp(json_data=schedule_payload)), \
             patch('fetch_games.save_off_results') as mock_save:
            fetch_tomorrow_games(config={'sport_id_priority': [1]}, for_date='2026-07-02')
        saved_data, saved_name = mock_save.call_args[0]
        assert saved_name == 'tomorrow_games'
        assert saved_data['games'][0]['game_pk'] == 777
        assert saved_data['date'] == '2026-07-02'

    def test_no_games_for_date_saves_empty_list(self):
        """No games for date saves empty list."""
        with patch('fetch_games.check_games_for_sport', return_value=0), \
             patch('fetch_games.requests.get', return_value=_resp(json_data={'dates': []})), \
             patch('fetch_games.save_off_results') as mock_save:
            fetch_tomorrow_games(config={'sport_id_priority': [1]}, for_date='2026-07-02')
        saved_data, saved_name = mock_save.call_args[0]
        assert saved_data['games'] == []

    def test_non_200_response_does_not_save(self):
        """Non 200 response does not save."""
        with patch('fetch_games.check_games_for_sport', return_value=0), \
             patch('fetch_games.requests.get', return_value=_resp(status_code=500)), \
             patch('fetch_games.save_off_results') as mock_save:
            fetch_tomorrow_games(config={'sport_id_priority': [1]}, for_date='2026-07-02')
        mock_save.assert_not_called()

    def test_request_exception_is_swallowed(self):
        """Request exception is swallowed."""
        with patch('fetch_games.check_games_for_sport', return_value=0), \
             patch('fetch_games.requests.get', side_effect=Exception('boom')), \
             patch('fetch_games.save_off_results') as mock_save:
            fetch_tomorrow_games(config={'sport_id_priority': [1]}, for_date='2026-07-02')
        mock_save.assert_not_called()

    def test_defaults_to_tomorrow_when_no_for_date(self):
        """Defaults to tomorrow when no for date."""
        with patch('fetch_games.check_games_for_sport', return_value=0), \
             patch('fetch_games.requests.get', return_value=_resp(json_data={'dates': []})), \
             patch('fetch_games.save_off_results') as mock_save, \
             patch('fetch_games.load_config', return_value={'sport_id_priority': [1]}):
            fetch_tomorrow_games(config=None, for_date=None)
        saved_data, _ = mock_save.call_args[0]
        from datetime import date as _d, timedelta as _td
        expected = (_d.today() + _td(days=1)).strftime('%Y-%m-%d')
        assert saved_data['date'] == expected

    def test_empty_sport_priority_defaults_to_sport_1(self):
        """Empty sport priority defaults to sport 1."""
        with patch('fetch_games.check_games_for_sport') as mock_check, \
             patch('fetch_games.requests.get', return_value=_resp(json_data={'dates': []})), \
             patch('fetch_games.save_off_results'):
            fetch_tomorrow_games(config={'sport_id_priority': []}, for_date='2026-07-02')
        mock_check.assert_not_called()

    def test_spring_training_filtered_when_regular_games_present(self):
        """Spring training filtered when regular games present."""
        schedule_payload = {'dates': [{'games': [
            {'teams': {'away': {'team': {'id': 1}}, 'home': {'team': {'id': 2}}},
             'gameDate': 'x', 'gamePk': 1, 'gameType': 'R'},
            {'teams': {'away': {'team': {'id': 3}}, 'home': {'team': {'id': 4}}},
             'gameDate': 'x', 'gamePk': 2, 'gameType': 'S'},
        ]}]}
        with patch('fetch_games.check_games_for_sport', return_value=1), \
             patch('fetch_games.requests.get', return_value=_resp(json_data=schedule_payload)), \
             patch('fetch_games.save_off_results') as mock_save:
            fetch_tomorrow_games(config={'sport_id_priority': [1]}, for_date='2026-03-15')
        saved_data, _ = mock_save.call_args[0]
        assert len(saved_data['games']) == 1
        assert saved_data['games'][0]['game_pk'] == 1


# ===========================================================================
# fetch_scoreboard_for_date
# ===========================================================================

class TestFetchScoreboardForDate:
    def test_explicit_sport_id_skips_priority_logic(self):
        """Explicit sport id skips priority logic."""
        with patch('fetch_games.check_games_for_sport') as mock_check, \
             patch('fetch_games.requests.get', return_value=_resp(json_data={'dates': []})), \
             patch('fetch_games.parse_games') as mock_parse:
            fetch_scoreboard_for_date('2026-07-01', sport_id=8, config={'sport_id_priority': [1, 8]})
        mock_check.assert_not_called()
        mock_parse.assert_called_once()
        assert mock_parse.call_args[0][1] == 8

    def test_priority_list_picks_first_sport_with_games(self):
        """Priority list picks first sport with games."""
        with patch('fetch_games.check_games_for_sport', side_effect=[0, 3]), \
             patch('fetch_games.requests.get', return_value=_resp(json_data={'dates': []})), \
             patch('fetch_games.parse_games') as mock_parse:
            fetch_scoreboard_for_date('2026-07-01', sport_id=None,
                                       config={'sport_id_priority': [1, 8]})
        assert mock_parse.call_args[0][1] == 8

    def test_no_games_found_defaults_to_first_priority_sport(self):
        """No games found defaults to first priority sport."""
        with patch('fetch_games.check_games_for_sport', return_value=0), \
             patch('fetch_games.requests.get', return_value=_resp(json_data={'dates': []})), \
             patch('fetch_games.parse_games') as mock_parse:
            fetch_scoreboard_for_date('2026-07-01', sport_id=None,
                                       config={'sport_id_priority': [1, 8]})
        assert mock_parse.call_args[0][1] == 1

    def test_no_priority_list_uses_config_sport_id(self):
        """No priority list uses config sport id."""
        with patch('fetch_games.requests.get', return_value=_resp(json_data={'dates': []})), \
             patch('fetch_games.parse_games') as mock_parse:
            fetch_scoreboard_for_date('2026-07-01', sport_id=None, config={'sport_id': 16})
        assert mock_parse.call_args[0][1] == 16

    def test_config_none_loads_config(self):
        """Config none loads config."""
        with patch('fetch_games.load_config', return_value={'sport_id': 1}) as mock_cfg, \
             patch('fetch_games.requests.get', return_value=_resp(json_data={'dates': []})), \
             patch('fetch_games.parse_games'):
            fetch_scoreboard_for_date('2026-07-01', sport_id=1, config=None)
        mock_cfg.assert_called_once()
