"""Tests for fetch_leaders.py and image_leaders.py."""
import json
import time
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

from fetch_leaders import fetch_leaders, _CACHE_TTL_HOURS, _CATEGORIES
from image_leaders import _current_category, _FORMAT, draw_leaders_cell, rotating_categories


# ---------------------------------------------------------------------------
# _FORMAT helpers
# ---------------------------------------------------------------------------

def _avg(v):
    """Avg."""
    return _FORMAT['battingAverage'](v)


class TestBattingAverageFormat:
    def test_strips_leading_zero(self):
        """Strips leading zero."""
        assert _avg('0.345') == '.345'

    def test_zero_average(self):
        """Zero average."""
        # Must not collapse to bare '.' — lstrip('0') leaves '.000'
        assert _avg('0.000') == '.000'

    def test_already_no_leading_zero(self):
        """Already no leading zero."""
        assert _avg('.298') == '.298'

    def test_no_decimal(self):
        """No decimal."""
        assert _avg('345') == '345'

    def test_empty_string(self):
        """Empty string."""
        assert _avg('') == ''


class TestOtherFormats:
    def test_home_runs_passthrough(self):
        """Home runs passthrough."""
        assert _FORMAT['homeRuns']('27') == '27'

    def test_era_passthrough(self):
        """Era passthrough."""
        assert _FORMAT['earnedRunAverage']('2.85') == '2.85'


# ---------------------------------------------------------------------------
# _current_category
# ---------------------------------------------------------------------------

class TestCurrentCategory:
    def test_returns_a_known_category(self):
        """Returns a known category."""
        assert _current_category() in _CATEGORIES

    def test_rotation_eventually_covers_all_categories(self):
        """Rotation eventually covers all categories."""
        # Selection is randomized per time block, so a handful of consecutive
        # blocks won't necessarily hit every category — sample many blocks
        # instead to confirm the full category set is reachable.
        with patch('image_leaders.datetime') as mock_dt:
            seen = set()
            for step in range(200):
                mock_dt.now.return_value.hour = 0
                mock_dt.now.return_value.minute = step * 5
                seen.add(_current_category(rotation_minutes=5))
            assert seen == set(_CATEGORIES)

    def test_rotation_stable_within_time_block(self):
        """Rotation stable within time block."""
        with patch('image_leaders.datetime') as mock_dt:
            mock_dt.now.return_value.hour = 3
            mock_dt.now.return_value.minute = 17
            first = _current_category(rotation_minutes=5)
            second = _current_category(rotation_minutes=5)
            assert first == second

    def test_zero_rotation_minutes_does_not_crash(self):
        """Zero rotation minutes does not crash."""
        # rotation_minutes=0 was a ZeroDivisionError before the fix
        cat = _current_category(rotation_minutes=0)
        assert cat in _CATEGORIES

    def test_negative_rotation_minutes_does_not_crash(self):
        """Negative rotation minutes does not crash."""
        cat = _current_category(rotation_minutes=-3)
        assert cat in _CATEGORIES


# ---------------------------------------------------------------------------
# rotating_categories
# ---------------------------------------------------------------------------

class TestRotatingCategories:
    def test_returns_requested_count(self):
        """Returns requested count."""
        with patch('image_leaders.datetime') as mock_dt:
            mock_dt.now.return_value.hour = 0
            mock_dt.now.return_value.minute = 0
            assert len(rotating_categories(2)) == 2
            assert len(rotating_categories(1)) == 1

    def test_clamps_n_to_category_count(self):
        """Clamps n to category count."""
        with patch('image_leaders.datetime') as mock_dt:
            mock_dt.now.return_value.hour = 0
            mock_dt.now.return_value.minute = 0
            assert len(rotating_categories(999)) == len(_CATEGORIES)
            assert rotating_categories(0) == []
            assert rotating_categories(-5) == []

    def test_window_slides_over_time(self):
        """Window slides over time."""
        # With a 2-slot window, the randomized subset shown per rotation
        # window should still surface every category if sampled long enough.
        with patch('image_leaders.datetime') as mock_dt:
            seen = set()
            for step in range(200):
                mock_dt.now.return_value.hour = 0
                mock_dt.now.return_value.minute = step * 5
                seen.update(rotating_categories(2, rotation_minutes=5))
            assert seen == set(_CATEGORIES)


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
    """Make image."""
    return Image.new('1', (800, 480), 255)


def test_draw_leaders_cell_renders_without_error():
    """Draw leaders cell renders without error."""
    img = _make_image()
    with patch('image_leaders._current_category', return_value='homeRuns'):
        result = draw_leaders_cell(img, 32, 30, SAMPLE_LEADERS, SAMPLE_TEAM_DATA)
    assert result is not None


def test_draw_leaders_cell_no_data_for_category():
    """Draw leaders cell no data for category."""
    img = _make_image()
    # Empty leaders dict — should show 'No data' fallback without crashing
    result = draw_leaders_cell(img, 32, 30, {}, SAMPLE_TEAM_DATA)
    assert result is not None


def test_draw_leaders_cell_none_leaders_data():
    """Draw leaders cell none leaders data."""
    img = _make_image()
    result = draw_leaders_cell(img, 32, 30, None, SAMPLE_TEAM_DATA)
    assert result is not None


def test_draw_leaders_cell_none_team_data():
    """Draw leaders cell none team data."""
    img = _make_image()
    with patch('image_leaders._current_category', return_value='homeRuns'):
        result = draw_leaders_cell(img, 32, 30, SAMPLE_LEADERS, None)
    assert result is not None


def test_draw_leaders_cell_batting_avg_category():
    """Draw leaders cell batting avg category."""
    img = _make_image()
    with patch('image_leaders._current_category', return_value='battingAverage'):
        result = draw_leaders_cell(img, 32, 30, SAMPLE_LEADERS, SAMPLE_TEAM_DATA)
    assert result is not None


def test_draw_leaders_cell_very_long_name_truncated():
    """Draw leaders cell very long name truncated."""
    img = _make_image()
    long_name_leaders = {
        'homeRuns': [
            {'rank': 1, 'value': '28', 'name': 'Bartholomew Humperdink-Smithson', 'team_id': '147'},
        ]
    }
    with patch('image_leaders._current_category', return_value='homeRuns'):
        result = draw_leaders_cell(img, 32, 30, long_name_leaders, SAMPLE_TEAM_DATA)
    assert result is not None


def test_draw_leaders_cell_with_logos_pastes_logo():
    """Draw leaders cell with logos pastes logo."""
    img = _make_image()
    fake_logo = Image.new('1', (18, 18), 0)
    with patch('image_leaders._current_category', return_value='homeRuns'), \
         patch('image_leaders._logo_small', return_value=fake_logo) as mock_logo:
        result = draw_leaders_cell(img, 32, 30, SAMPLE_LEADERS, SAMPLE_TEAM_DATA, use_logos=True)
    assert result is not None
    assert mock_logo.called


def test_draw_leaders_cell_logo_lookup_failure_falls_back():
    """Draw leaders cell logo lookup failure falls back."""
    # _logo_small raising must not crash the cell — falls back to no logo.
    img = _make_image()
    with patch('image_leaders._current_category', return_value='homeRuns'), \
         patch('image_leaders._logo_small', side_effect=OSError('missing')):
        result = draw_leaders_cell(img, 32, 30, SAMPLE_LEADERS, SAMPLE_TEAM_DATA, use_logos=True)
    assert result is not None


def test_draw_leaders_cell_top_10_entries_all_fit():
    """Draw leaders cell top 10 entries all fit."""
    img = _make_image()
    ten_entries = {
        'homeRuns': [
            {'rank': i + 1, 'value': str(30 - i), 'name': f'Player{i} Lastname{i}', 'team_id': '147'}
            for i in range(10)
        ]
    }
    with patch('image_leaders._current_category', return_value='homeRuns'):
        result = draw_leaders_cell(img, 32, 30, ten_entries, SAMPLE_TEAM_DATA)
    assert result is not None


# ---------------------------------------------------------------------------
# fetch_leaders cache behaviour (no network calls)
# ---------------------------------------------------------------------------

def test_fetch_leaders_uses_cache_when_fresh(tmp_path, monkeypatch):
    """Fetch leaders uses cache when fresh."""
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
    """Fetch leaders refetches when stale."""
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
                'statGroup': 'hitting',
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
    """Fetch leaders refetches when season changed."""
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
    """Fetch leaders returns stale cache on network error."""
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
    """Fetch leaders returns empty on total failure."""
    import util
    monkeypatch.setattr(util, '_DATA_DIR', str(tmp_path))
    # No cache file at all

    with patch('fetch_leaders.requests.get', side_effect=Exception("no network")):
        result = fetch_leaders(season=2026)

    assert result == {}
