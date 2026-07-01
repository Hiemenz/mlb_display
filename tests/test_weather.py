"""Tests for src/weather.py — Open-Meteo forecast client with on-disk TTL cache."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import weather


# ===========================================================================
# _compass_from_degrees
# ===========================================================================

class TestCompassFromDegrees:
    def test_none_returns_none(self):
        assert weather._compass_from_degrees(None) is None

    def test_zero_is_north(self):
        assert weather._compass_from_degrees(0) == 'N'

    def test_360_wraps_to_north(self):
        assert weather._compass_from_degrees(360) == 'N'

    def test_45_is_northeast(self):
        assert weather._compass_from_degrees(45) == 'NE'

    def test_90_is_east(self):
        assert weather._compass_from_degrees(90) == 'E'

    def test_135_is_southeast(self):
        assert weather._compass_from_degrees(135) == 'SE'

    def test_180_is_south(self):
        assert weather._compass_from_degrees(180) == 'S'

    def test_225_is_southwest(self):
        assert weather._compass_from_degrees(225) == 'SW'

    def test_270_is_west(self):
        assert weather._compass_from_degrees(270) == 'W'

    def test_315_is_northwest(self):
        assert weather._compass_from_degrees(315) == 'NW'

    def test_just_below_wraparound_boundary_is_north(self):
        # 22.4 degrees rounds down into the N bucket
        assert weather._compass_from_degrees(22.4) == 'N'

    def test_just_above_wraparound_boundary_is_northeast(self):
        assert weather._compass_from_degrees(22.6) == 'NE'

    def test_string_degree_value_is_coerced_to_float(self):
        assert weather._compass_from_degrees('0') == 'N'


# ===========================================================================
# _parse_iso_utc
# ===========================================================================

class TestParseIsoUtc:
    def test_none_returns_none(self):
        assert weather._parse_iso_utc(None) is None

    def test_empty_string_returns_none(self):
        assert weather._parse_iso_utc('') is None

    def test_malformed_timestamp_returns_none(self):
        assert weather._parse_iso_utc('not-a-timestamp') is None

    def test_z_suffix_parsed_as_utc(self):
        dt = weather._parse_iso_utc('2026-06-30T18:05:00Z')
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.year == 2026 and dt.month == 6 and dt.day == 30
        assert dt.hour == 18

    def test_offset_naive_treated_as_utc(self):
        dt = weather._parse_iso_utc('2026-06-30T18:05:00')
        assert dt.tzinfo == timezone.utc

    def test_offset_aware_converted_to_utc(self):
        dt = weather._parse_iso_utc('2026-06-30T14:05:00-04:00')
        assert dt.hour == 18
        assert dt.tzinfo == timezone.utc

    def test_whitespace_stripped(self):
        dt = weather._parse_iso_utc('  2026-06-30T18:05:00Z  ')
        assert dt is not None


# ===========================================================================
# _pick_hour
# ===========================================================================

class TestPickHour:
    def _game_dt(self, hour=18):
        return datetime(2026, 6, 30, hour, 0, tzinfo=timezone.utc)

    def test_no_hourly_data_returns_none(self):
        assert weather._pick_hour({}, self._game_dt()) is None

    def test_empty_times_returns_none(self):
        payload = {'hourly': {'time': []}}
        assert weather._pick_hour(payload, self._game_dt()) is None

    def test_exact_hour_match(self):
        payload = {
            'hourly': {
                'time': ['2026-06-30T17:00', '2026-06-30T18:00', '2026-06-30T19:00'],
                'temperature_2m': [70, 72, 74],
                'wind_speed_10m': [5, 6, 7],
                'wind_direction_10m': [0, 90, 180],
                'precipitation_probability': [10, 20, 30],
            }
        }
        result = weather._pick_hour(payload, self._game_dt(18))
        assert result['temp_f'] == 72
        assert result['wind_mph'] == 6
        assert result['wind_dir'] == 'E'
        assert result['precip_pct'] == 20

    def test_closest_hour_fallback(self):
        # No exact match for 18:00 — closest is 19:00 (only later hour present)
        payload = {
            'hourly': {
                'time': ['2026-06-30T20:00', '2026-06-30T19:00', '2026-06-30T22:00'],
                'temperature_2m': [50, 60, 80],
                'wind_speed_10m': [1, 2, 3],
                'wind_direction_10m': [0, 0, 0],
                'precipitation_probability': [0, 0, 0],
            }
        }
        result = weather._pick_hour(payload, self._game_dt(18))
        # closest to 18:00 among 20:00/19:00/22:00 is 19:00 (index 1) -> temp 60
        assert result['temp_f'] == 60

    def test_malformed_time_strings_return_none(self):
        payload = {'hourly': {'time': ['not-a-time', 'also-bad']}}
        assert weather._pick_hour(payload, self._game_dt()) is None

    def test_all_none_values_returns_none(self):
        payload = {
            'hourly': {
                'time': ['2026-06-30T18:00'],
                'temperature_2m': [None],
                'wind_speed_10m': [None],
                'wind_direction_10m': [None],
                'precipitation_probability': [None],
            }
        }
        assert weather._pick_hour(payload, self._game_dt(18)) is None

    def test_missing_series_field_treated_as_none(self):
        payload = {
            'hourly': {
                'time': ['2026-06-30T18:00'],
                'temperature_2m': [72],
                # other fields entirely absent
            }
        }
        result = weather._pick_hour(payload, self._game_dt(18))
        assert result['temp_f'] == 72
        assert result['wind_mph'] is None
        assert result['wind_dir'] is None
        assert result['precip_pct'] is None


# ===========================================================================
# _cache_key / _is_fresh
# ===========================================================================

class TestCacheKey:
    def test_key_format(self):
        dt = datetime(2026, 6, 30, 18, 30, tzinfo=timezone.utc)
        assert weather._cache_key(123, dt) == '123:2026-06-30T18'

    def test_minutes_truncated_from_key(self):
        dt1 = datetime(2026, 6, 30, 18, 0, tzinfo=timezone.utc)
        dt2 = datetime(2026, 6, 30, 18, 59, tzinfo=timezone.utc)
        assert weather._cache_key(1, dt1) == weather._cache_key(1, dt2)


class TestIsFresh:
    def test_missing_fetched_at_is_not_fresh(self):
        assert weather._is_fresh({}, 60) is False

    def test_malformed_fetched_at_is_not_fresh(self):
        assert weather._is_fresh({'fetched_at': 'garbage'}, 60) is False

    def test_recent_fetch_is_fresh(self):
        now = datetime.now(timezone.utc)
        entry = {'fetched_at': now.strftime('%Y-%m-%dT%H:%M:%SZ')}
        assert weather._is_fresh(entry, 60) is True

    def test_stale_fetch_is_not_fresh(self):
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        entry = {'fetched_at': old.strftime('%Y-%m-%dT%H:%M:%SZ')}
        assert weather._is_fresh(entry, 60) is False


# ===========================================================================
# _prune_cache
# ===========================================================================

class TestPruneCache:
    def test_removes_entries_older_than_keep_days(self):
        old_dt = datetime.now(timezone.utc) - timedelta(days=10)
        fresh_dt = datetime.now(timezone.utc) - timedelta(hours=1)
        cache = {
            weather._cache_key(1, old_dt): {'forecast': {}, 'fetched_at': 'x'},
            weather._cache_key(2, fresh_dt): {'forecast': {}, 'fetched_at': 'x'},
        }
        weather._prune_cache(cache, keep_days=3)
        assert weather._cache_key(1, old_dt) not in cache
        assert weather._cache_key(2, fresh_dt) in cache

    def test_malformed_key_is_ignored_not_removed(self):
        cache = {'not-a-valid-key-format': {'forecast': {}}}
        weather._prune_cache(cache, keep_days=3)
        assert 'not-a-valid-key-format' in cache


# ===========================================================================
# get_forecast — integration-ish tests, network + cache mocked
# ===========================================================================

class TestGetForecast:
    GAME_ISO = '2026-06-30T18:00:00Z'

    def test_lat_or_lon_none_returns_none_immediately(self):
        with patch('weather._load_cache') as mock_load:
            assert weather.get_forecast(1, None, -80.0, self.GAME_ISO) is None
            assert weather.get_forecast(1, 40.0, None, self.GAME_ISO) is None
            mock_load.assert_not_called()

    def test_malformed_game_time_returns_none(self):
        assert weather.get_forecast(1, 40.0, -80.0, 'garbage') is None

    def test_cache_hit_fresh_skips_fetch(self):
        game_dt = weather._parse_iso_utc(self.GAME_ISO)
        key = weather._cache_key(1, game_dt)
        cached_forecast = {'temp_f': 70, 'wind_mph': 5, 'wind_dir': 'N', 'precip_pct': 10}
        cache = {
            key: {
                'forecast': cached_forecast,
                'fetched_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            }
        }
        with patch('weather._load_cache', return_value=cache), \
             patch('weather._fetch_open_meteo') as mock_fetch:
            result = weather.get_forecast(1, 40.0, -80.0, self.GAME_ISO)
        assert result == cached_forecast
        mock_fetch.assert_not_called()

    def test_cache_miss_triggers_fetch_and_saves(self):
        payload = {
            'hourly': {
                'time': ['2026-06-30T18:00'],
                'temperature_2m': [72],
                'wind_speed_10m': [6],
                'wind_direction_10m': [90],
                'precipitation_probability': [20],
            }
        }
        with patch('weather._load_cache', return_value={}), \
             patch('weather._fetch_open_meteo', return_value=payload) as mock_fetch, \
             patch('weather._save_cache') as mock_save:
            result = weather.get_forecast(1, 40.0, -80.0, self.GAME_ISO)
        mock_fetch.assert_called_once()
        assert result['temp_f'] == 72
        mock_save.assert_called_once()

    def test_network_failure_falls_back_to_stale_cache(self):
        game_dt = weather._parse_iso_utc(self.GAME_ISO)
        key = weather._cache_key(1, game_dt)
        stale_forecast = {'temp_f': 55, 'wind_mph': 3, 'wind_dir': 'S', 'precip_pct': 0}
        stale_time = datetime.now(timezone.utc) - timedelta(hours=5)
        cache = {
            key: {
                'forecast': stale_forecast,
                'fetched_at': stale_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            }
        }
        with patch('weather._load_cache', return_value=cache), \
             patch('weather._fetch_open_meteo', side_effect=weather.URLError('boom')):
            result = weather.get_forecast(1, 40.0, -80.0, self.GAME_ISO)
        assert result == stale_forecast

    def test_network_failure_no_cache_returns_none(self):
        with patch('weather._load_cache', return_value={}), \
             patch('weather._fetch_open_meteo', side_effect=weather.URLError('boom')):
            result = weather.get_forecast(1, 40.0, -80.0, self.GAME_ISO)
        assert result is None

    def test_pick_hour_none_falls_back_to_stale_cache(self):
        """When the fetch succeeds but no usable hour is found, fall back to stale cache."""
        game_dt = weather._parse_iso_utc(self.GAME_ISO)
        key = weather._cache_key(1, game_dt)
        stale_forecast = {'temp_f': 55, 'wind_mph': 3, 'wind_dir': 'S', 'precip_pct': 0}
        cache = {
            key: {
                'forecast': stale_forecast,
                'fetched_at': (datetime.now(timezone.utc) - timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M:%SZ'),
            }
        }
        with patch('weather._load_cache', return_value=cache), \
             patch('weather._fetch_open_meteo', return_value={'hourly': {}}):
            result = weather.get_forecast(1, 40.0, -80.0, self.GAME_ISO)
        assert result == stale_forecast

    def test_pick_hour_none_no_cache_returns_none(self):
        with patch('weather._load_cache', return_value={}), \
             patch('weather._fetch_open_meteo', return_value={'hourly': {}}):
            result = weather.get_forecast(1, 40.0, -80.0, self.GAME_ISO)
        assert result is None


# ===========================================================================
# _load_cache / _save_cache — file I/O
# ===========================================================================

class TestLoadCache:
    def test_missing_file_returns_empty_dict(self, tmp_path, monkeypatch):
        monkeypatch.setattr(weather, '_CACHE_PATH', str(tmp_path / 'missing.json'))
        assert weather._load_cache() == {}

    def test_valid_file_returns_data(self, tmp_path, monkeypatch):
        path = tmp_path / 'weather_cache.json'
        path.write_text(json.dumps({'a': 1}))
        monkeypatch.setattr(weather, '_CACHE_PATH', str(path))
        assert weather._load_cache() == {'a': 1}

    def test_malformed_json_returns_empty_dict(self, tmp_path, monkeypatch):
        path = tmp_path / 'weather_cache.json'
        path.write_text('{not valid json')
        monkeypatch.setattr(weather, '_CACHE_PATH', str(path))
        assert weather._load_cache() == {}

    def test_null_json_returns_empty_dict(self, tmp_path, monkeypatch):
        path = tmp_path / 'weather_cache.json'
        path.write_text('null')
        monkeypatch.setattr(weather, '_CACHE_PATH', str(path))
        assert weather._load_cache() == {}


class TestSaveCache:
    def test_writes_json_to_disk(self, tmp_path, monkeypatch):
        path = tmp_path / 'nested' / 'weather_cache.json'
        monkeypatch.setattr(weather, '_CACHE_PATH', str(path))
        weather._save_cache({'x': 1})
        assert json.loads(path.read_text()) == {'x': 1}

    def test_write_failure_is_caught_and_printed(self, monkeypatch, capsys):
        # Point at a path whose parent cannot be created (invalid null byte is not
        # portable, so instead patch os.makedirs to raise).
        monkeypatch.setattr(weather.os, 'makedirs', lambda *a, **k: (_ for _ in ()).throw(OSError('nope')))
        weather._save_cache({'x': 1})
        captured = capsys.readouterr()
        assert 'failed to write cache' in captured.out
