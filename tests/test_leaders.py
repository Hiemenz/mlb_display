"""Tests for fetch_leaders.py and image_leaders.py."""
import json
import time
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

from fetch_leaders import fetch_leaders, _CACHE_TTL_HOURS, _CATEGORIES
from image_leaders import _current_category, _FORMAT, draw_leaders_cell


# ---------------------------------------------------------------------------
# _FORMAT helpers
# ---------------------------------------------------------------------------

def _avg(v):
    return _FORMAT['battingAverage'](v)


class TestBattingAverageFormat:
    def test_strips_leading_zero(self):
        assert _avg('0.345') == '.345'

    def test_zero_average(self):
        # Must not collapse to bare '.' — lstrip('0') leaves '.000'
        assert _avg('0.000') == '.000'

    def test_already_no_leading_zero(self):
        assert _avg('.298') == '.298'

    def test_no_decimal(self):
        assert _avg('345') == '345'

    def test_empty_string(self):
        assert _avg('') == ''


class TestOtherFormats:
    def test_home_runs_passthrough(self):
        assert _FORMAT['homeRuns']('27') == '27'

    def test_era_passthrough(self):
        assert _FORMAT['earnedRunAverage']('2.85') == '2.85'


# ---------------------------------------------------------------------------
# _current_category
# ---------------------------------------------------------------------------

class TestCurrentCategory:
    def test_returns_a_known_category(self):
        assert _current_category() in _CATEGORIES

    def test_rotation_cycles_all_categories(self):
        # minute_block = 0 → idx 0; 5 → idx 1; 10 → idx 2; 15 → idx 0 again
        with patch('image_leaders.datetime') as mock_dt:
            seen = set()
            for minute in (0, 5, 10):
                mock_dt.now.return_value.hour = 0
                mock_dt.now.return_value.minute = minute
                seen.add(_current_category(rotation_minutes=5))
            assert seen == set(_CATEGORIES)

    def test_zero_rotation_minutes_does_not_crash(self):
        # rotation_minutes=0 was a ZeroDivisionError before the fix
        cat = _current_category(rotation_minutes=0)
        assert cat in _CATEGORIES

    def test_negative_rotation_minutes_does_not_crash(self):
        cat = _current_category(rotation_minutes=-3)
        assert cat in _CATEGORIES


# ---------------------------------------------------------------------------
# draw_leaders_cell
# ---------------------------------------------------------------------------

SAMPLE_LEADERS = {
    'homeRuns': [
        {'rank': 1, 'value': '28', 'name': 'Aaron Judge', 'team_id': '147'},
        {'rank': 2, 'value': '25', 'name': 'Yordan Alvarez', 'team_id': '117'},
    ],
    'battingAverage': [
        {'rank': 1, 'value': '0.345', 'name': 'Luis Arraez', 'team_id': '146'},
    ],
    'earnedRunAverage': [
        {'rank': 1, 'value': '1.85', 'name': 'Zack Wheeler', 'team_id': '143'},
    ],
}

SAMPLE_TEAM_DATA = {
    'team_abbreviation': {
        '147': 'NYY',
        '117': 'HOU',
        '146': 'MIA',
        '143': 'PHI',
    }
}


def _make_image():
    return Image.new('1', (800, 480), 255)


def test_draw_leaders_cell_renders_without_error():
    img = _make_image()
    with patch('image_leaders._current_category', return_value='homeRuns'):
        result = draw_leaders_cell(img, 32, 30, SAMPLE_LEADERS, SAMPLE_TEAM_DATA)
    assert result is not None


def test_draw_leaders_cell_no_data_for_category():
    img = _make_image()
    # Empty leaders dict — should show 'No data' fallback without crashing
    result = draw_leaders_cell(img, 32, 30, {}, SAMPLE_TEAM_DATA)
    assert result is not None


def test_draw_leaders_cell_none_leaders_data():
    img = _make_image()
    result = draw_leaders_cell(img, 32, 30, None, SAMPLE_TEAM_DATA)
    assert result is not None


def test_draw_leaders_cell_none_team_data():
    img = _make_image()
    with patch('image_leaders._current_category', return_value='homeRuns'):
        result = draw_leaders_cell(img, 32, 30, SAMPLE_LEADERS, None)
    assert result is not None


def test_draw_leaders_cell_batting_avg_category():
    img = _make_image()
    with patch('image_leaders._current_category', return_value='battingAverage'):
        result = draw_leaders_cell(img, 32, 30, SAMPLE_LEADERS, SAMPLE_TEAM_DATA)
    assert result is not None


def test_draw_leaders_cell_very_long_name_truncated():
    img = _make_image()
    long_name_leaders = {
        'homeRuns': [
            {'rank': 1, 'value': '28', 'name': 'Bartholomew Humperdink-Smithson', 'team_id': '147'},
        ]
    }
    with patch('image_leaders._current_category', return_value='homeRuns'):
        result = draw_leaders_cell(img, 32, 30, long_name_leaders, SAMPLE_TEAM_DATA)
    assert result is not None


# ---------------------------------------------------------------------------
# fetch_leaders cache behaviour (no network calls)
# ---------------------------------------------------------------------------

def test_fetch_leaders_uses_cache_when_fresh(tmp_path, monkeypatch):
    import util
    fresh_cache = {
        'season': 2026,
        'fetched_at': time.time() - 100,  # 100 seconds old — well within 20h
        'leaders': {'homeRuns': [{'rank': 1, 'value': '28', 'name': 'Judge', 'team_id': '147'}]},
    }
    monkeypatch.setattr(util, '_DATA_DIR', str(tmp_path))
    (tmp_path / 'leaders.json').write_text(json.dumps(fresh_cache))

    with patch('fetch_leaders.requests.get') as mock_get:
        result = fetch_leaders(season=2026)
        mock_get.assert_not_called()

    assert result['leaders']['homeRuns'][0]['name'] == 'Judge'


def test_fetch_leaders_refetches_when_stale(tmp_path, monkeypatch):
    import util
    stale_cache = {
        'season': 2026,
        'fetched_at': time.time() - (_CACHE_TTL_HOURS + 1) * 3600,
        'leaders': {},
    }
    monkeypatch.setattr(util, '_DATA_DIR', str(tmp_path))
    (tmp_path / 'leaders.json').write_text(json.dumps(stale_cache))

    api_response = {
        'leagueLeaders': [
            {
                'leaderCategory': 'homeRuns',
                'leaders': [
                    {'rank': 1, 'value': '30', 'person': {'fullName': 'Aaron Judge'},
                     'team': {'id': 147}}
                ],
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = api_response
    mock_resp.raise_for_status.return_value = None

    with patch('fetch_leaders.requests.get', return_value=mock_resp) as mock_get:
        result = fetch_leaders(season=2026)
        mock_get.assert_called_once()

    assert result['leaders']['homeRuns'][0]['name'] == 'Aaron Judge'


def test_fetch_leaders_refetches_when_season_changed(tmp_path, monkeypatch):
    import util
    old_season_cache = {
        'season': 2025,
        'fetched_at': time.time() - 60,  # fresh but wrong season
        'leaders': {},
    }
    monkeypatch.setattr(util, '_DATA_DIR', str(tmp_path))
    (tmp_path / 'leaders.json').write_text(json.dumps(old_season_cache))

    mock_resp = MagicMock()
    mock_resp.json.return_value = {'leagueLeaders': []}
    mock_resp.raise_for_status.return_value = None

    with patch('fetch_leaders.requests.get', return_value=mock_resp) as mock_get:
        fetch_leaders(season=2026)
        mock_get.assert_called_once()


def test_fetch_leaders_returns_stale_cache_on_network_error(tmp_path, monkeypatch):
    import util
    stale_cache = {
        'season': 2026,
        'fetched_at': time.time() - 999 * 3600,
        'leaders': {'homeRuns': [{'rank': 1, 'value': '28', 'name': 'Judge', 'team_id': '147'}]},
    }
    monkeypatch.setattr(util, '_DATA_DIR', str(tmp_path))
    (tmp_path / 'leaders.json').write_text(json.dumps(stale_cache))

    with patch('fetch_leaders.requests.get', side_effect=Exception("timeout")):
        result = fetch_leaders(season=2026)

    # Falls back to stale cache rather than crashing
    assert result['leaders']['homeRuns'][0]['name'] == 'Judge'


def test_fetch_leaders_returns_empty_on_total_failure(tmp_path, monkeypatch):
    import util
    monkeypatch.setattr(util, '_DATA_DIR', str(tmp_path))
    # No cache file at all

    with patch('fetch_leaders.requests.get', side_effect=Exception("no network")):
        result = fetch_leaders(season=2026)

    assert result == {}
