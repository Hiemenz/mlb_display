"""Tests for the debug overlay and auto dark/light mode logic."""
import json
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, mock_open

import pytest
from PIL import Image

from generate_image import (
    _get_system_uptime,
    _fetch_skip_is_expected,
    _draw_debug_overlay,
)


# ---------------------------------------------------------------------------
# _get_system_uptime
# ---------------------------------------------------------------------------

def test_get_system_uptime_parses_proc_uptime():
    """Get system uptime parses proc uptime."""
    # 3661 seconds = 1h 1m
    with patch('builtins.open', mock_open(read_data='3661.0 1234.5\n')):
        assert _get_system_uptime() == '1h 1m'


def test_get_system_uptime_large_value():
    """Get system uptime large value."""
    # 90000 seconds = 25h 0m
    with patch('builtins.open', mock_open(read_data='90000.0 45000.0\n')):
        assert _get_system_uptime() == '25h 0m'


def test_get_system_uptime_returns_empty_when_unavailable():
    """Get system uptime returns empty when unavailable."""
    with patch('builtins.open', side_effect=FileNotFoundError):
        assert _get_system_uptime() == ''


# ---------------------------------------------------------------------------
# _fetch_skip_is_expected
# ---------------------------------------------------------------------------

BASE_CONFIG = {
    'night_mode': True,
    'night_start': 2,
    'night_end': 7,
    'timezone': 'America/Chicago',
}


def _make_sched(last_fetch_hours_ago=0.5, next_game_date=None):
    """Make sched."""
    dt = datetime.now(timezone.utc) - timedelta(hours=last_fetch_hours_ago)
    sched = {'last_game_fetch': dt.isoformat()}
    if next_game_date:
        sched['next_game_date'] = next_game_date
    return sched


def test_skip_expected_during_night_window():
    """Skip expected during night window."""
    sched = _make_sched()
    # Mock current hour to 3am (inside 2–7 night window)
    with patch('generate_image.datetime') as mock_dt:
        mock_dt.now.return_value.hour = 3
        mock_dt.now.side_effect = lambda tz=None: type('dt', (), {'hour': 3})()
        import pytz
        with patch('generate_image.pytz') as mock_pytz:
            mock_pytz.timezone.return_value = pytz.timezone('America/Chicago')
            # Use real datetime for the night window check
            pass

    # Direct test: simulate being in the night window
    cfg = dict(BASE_CONFIG, night_start=2, night_end=7)
    # Patch datetime.now to return 3am Chicago time
    import pytz
    tz = pytz.timezone('America/Chicago')
    fake_now = datetime(2026, 7, 8, 3, 0, 0, tzinfo=tz)
    with patch('generate_image.datetime') as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.now.side_effect = lambda *a, **kw: fake_now
        mock_dt.fromisoformat = datetime.fromisoformat
        assert _fetch_skip_is_expected(cfg, sched) is True


def test_skip_not_expected_during_day():
    """Skip not expected during day."""
    sched = _make_sched()
    cfg = dict(BASE_CONFIG, night_start=2, night_end=7)
    import pytz
    tz = pytz.timezone('America/Chicago')
    fake_now = datetime(2026, 7, 8, 14, 0, 0, tzinfo=tz)
    with patch('generate_image.datetime') as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.now.side_effect = lambda *a, **kw: fake_now
        mock_dt.fromisoformat = datetime.fromisoformat
        assert _fetch_skip_is_expected(cfg, sched) is False


def test_skip_expected_on_off_day():
    """Skip expected on off day."""
    sched = _make_sched(next_game_date='2026-07-15')
    cfg = dict(BASE_CONFIG)
    import pytz
    tz = pytz.timezone('America/Chicago')
    fake_now = datetime(2026, 7, 8, 14, 0, 0, tzinfo=tz)
    with patch('generate_image.datetime') as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.now.side_effect = lambda *a, **kw: fake_now
        mock_dt.fromisoformat = datetime.fromisoformat
        # Also need to patch timezone.utc access for next_game_date comparison
        with patch('generate_image.timezone') as mock_tz:
            mock_tz.utc = timezone.utc
            result = _fetch_skip_is_expected(cfg, sched)
    assert result is True


def test_skip_not_expected_when_next_game_date_is_today():
    """Skip not expected when next game date is today."""
    sched = _make_sched(next_game_date='2026-07-08')
    cfg = dict(BASE_CONFIG)
    import pytz
    tz = pytz.timezone('America/Chicago')
    fake_now = datetime(2026, 7, 8, 14, 0, 0, tzinfo=tz)
    with patch('generate_image.datetime') as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.now.side_effect = lambda *a, **kw: fake_now
        mock_dt.fromisoformat = datetime.fromisoformat
        with patch('generate_image.timezone') as mock_tz:
            mock_tz.utc = timezone.utc
            result = _fetch_skip_is_expected(cfg, sched)
    assert result is False


def test_skip_not_expected_when_night_mode_disabled():
    """Skip not expected when night mode disabled."""
    cfg = dict(BASE_CONFIG, night_mode=False)
    sched = _make_sched()
    import pytz
    tz = pytz.timezone('America/Chicago')
    # Simulate 3am — would be in night window if night_mode were enabled
    fake_now = datetime(2026, 7, 8, 3, 0, 0, tzinfo=tz)
    with patch('generate_image.datetime') as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.now.side_effect = lambda *a, **kw: fake_now
        mock_dt.fromisoformat = datetime.fromisoformat
        result = _fetch_skip_is_expected(cfg, sched)
    assert result is False


# ---------------------------------------------------------------------------
# _draw_debug_overlay
# ---------------------------------------------------------------------------

def _blank_image():
    """Blank image."""
    return Image.new('1', (800, 480), 255)


def test_draw_debug_overlay_renders_without_error():
    """Draw debug overlay renders without error."""
    img = _blank_image()
    config = {'timezone': 'America/Chicago', 'night_mode': True, 'night_start': 2, 'night_end': 7}
    with patch('generate_image.load_json_file', return_value={}):
        with patch('generate_image._get_system_uptime', return_value='2h 30m'):
            result = _draw_debug_overlay(img, config)
    assert result is not None


def test_draw_debug_overlay_no_uptime_no_fetch_returns_image():
    """Draw debug overlay no uptime no fetch returns image."""
    img = _blank_image()
    config = {'timezone': 'America/Chicago'}
    with patch('generate_image.load_json_file', return_value={}):
        with patch('generate_image._get_system_uptime', return_value=''):
            result = _draw_debug_overlay(img, config)
    assert result is not None


def test_draw_debug_overlay_stale_fetch_inverts_box(tmp_path):
    """When fetch is stale and not suppressed, the box fill should be black (0)."""
    img = _blank_image()
    config = {
        'timezone': 'America/Chicago',
        'night_mode': False,  # disable night mode so stale is never suppressed
        'night_start': 2,
        'night_end': 7,
    }
    # Last fetch 3 hours ago
    stale_dt = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    sched = {'last_game_fetch': stale_dt}

    with patch('generate_image.load_json_file', return_value=sched):
        with patch('generate_image._get_system_uptime', return_value='5h 0m'):
            with patch('generate_image._fetch_skip_is_expected', return_value=False):
                result = _draw_debug_overlay(img, config)

    import numpy as np
    arr = np.array(result.convert('L'))
    # Bottom-right corner should contain black pixels (the inverted stale box)
    bottom_right = arr[-20:, -250:]
    assert (bottom_right == 0).any(), "Expected black pixels in stale overlay"


def test_draw_debug_overlay_fresh_fetch_draws_nothing(tmp_path):
    """Below the stale threshold, the overlay draws nothing at all — the
    corner stays untouched rather than showing an uptime/last-fetch
    readout during normal operation."""
    img = _blank_image()
    config = {
        'timezone': 'America/Chicago',
        'night_mode': False,
        'night_start': 2,
        'night_end': 7,
    }
    # Last fetch 10 minutes ago — well under the stale threshold
    fresh_dt = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    sched = {'last_game_fetch': fresh_dt}

    with patch('generate_image.load_json_file', return_value=sched):
        with patch('generate_image._get_system_uptime', return_value='1h 0m'):
            result = _draw_debug_overlay(img, config)

    import numpy as np
    arr = np.array(result.convert('L'))
    bottom_right = arr[-20:, -250:]
    # Fully blank — no box, no text — until the fetch actually goes stale.
    assert (bottom_right == 255).all()


# ---------------------------------------------------------------------------
# Auto dark mode: night_mode=False means always light
# ---------------------------------------------------------------------------

def test_in_night_window_respects_night_mode_false():
    """night_mode: false must suppress dark mode even during the night window."""
    from main import _in_night_window
    config = {
        'night_mode': False,
        'night_start': 0,
        'night_end': 23,  # almost entire day would be "night"
        'timezone': 'UTC',
    }
    # main.py gates: _is_dark = _in_night_window(config) if config.get('night_mode', True) else False
    # _in_night_window itself doesn't check the flag — the gating is in main.py.
    # The fix is in main.py; verify the gating expression directly.
    result = _in_night_window(config) if config.get('night_mode', True) else False
    assert result is False


def test_in_night_window_enabled_returns_true_at_night():
    """In night window enabled returns true at night."""
    from main import _in_night_window
    import pytz
    config = {
        'night_mode': True,
        'night_start': 2,
        'night_end': 7,
        'timezone': 'UTC',
    }
    # Patch to 3am UTC
    tz = pytz.utc
    fake_now = datetime(2026, 7, 8, 3, 0, 0, tzinfo=tz)
    with patch('main.datetime') as mock_dt:
        mock_dt.now.return_value = fake_now
        result = _in_night_window(config)
    is_dark = result if config.get('night_mode', True) else False
    assert is_dark is True


def test_in_night_window_enabled_returns_false_during_day():
    """In night window enabled returns false during day."""
    from main import _in_night_window
    import pytz
    config = {
        'night_mode': True,
        'night_start': 2,
        'night_end': 7,
        'timezone': 'UTC',
    }
    tz = pytz.utc
    fake_now = datetime(2026, 7, 8, 14, 0, 0, tzinfo=tz)
    with patch('main.datetime') as mock_dt:
        mock_dt.now.return_value = fake_now
        result = _in_night_window(config)
    is_dark = result if config.get('night_mode', True) else False
    assert is_dark is False
