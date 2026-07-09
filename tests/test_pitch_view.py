"""Smoke tests for pitch_view.py — single-game strike-zone/pitch-log rendering.

Covers:
  1. render_pitch_view happy path (In Progress, mid-count, several pitches)
  2. Pitch-code branches (S/C/T strike, F foul, X in play, ball) + None coords skipped
  3. Missing optional keys (batter/pitcher absent or None) don't crash
  4. detailed_state branches: Scheduled, Warmup, In Progress, Final
  5. dark_mode True/False
  6. Long pitch log (overflow / break at y > 468)
"""

from unittest.mock import patch

import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")


@pytest.fixture(autouse=True)
def _no_network(request):
    """No network."""
    if not PIL_AVAILABLE:
        yield
        return
    with patch('image_assets._try_download_logo', return_value=False):
        yield


def _base_game(**overrides):
    """Base game."""
    g = {
        'detailed_state': 'In Progress',
        'inning_state': 'Top',
        'inning_ordinal': '7th',
        'balls': 2,
        'strikes': 1,
        'outs': 1,
        'away_abbr': 'LAD',
        'home_abbr': 'SF',
        'away_id': 119,
        'home_id': 137,
        'away_runs': 3,
        'home_runs': 2,
        'batter': {
            'name': 'Freddie Freeman',
            'season': {'avg': '.312', 'homeRuns': '15', 'rbi': '55'},
        },
        'pitcher': {
            'name': 'Logan Webb',
            'season': {'era': '2.85'},
            'stats': {'inningsPitched': '150.0', 'strikeOuts': '140'},
        },
        'pitches': [
            {'px': -0.3, 'pz': 2.8, 'code': 'C', 'seq': 1, 'pitch_type': 'Fastball', 'speed': 93.4},
            {'px': 0.9, 'pz': 1.2, 'code': 'B', 'seq': 2, 'pitch_type': 'Slider', 'speed': 85.1},
            {'px': 0.1, 'pz': 2.5, 'code': 'S', 'seq': 3, 'pitch_type': 'Changeup', 'speed': 88.0},
        ],
    }
    g.update(overrides)
    return g


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

@needs_pil
def test_happy_path_in_progress():
    """Happy path in progress."""
    from pitch_view import render_pitch_view
    result = render_pitch_view(_base_game())
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)
    assert result.mode == '1'
    assert result.getbbox() is not None


# ---------------------------------------------------------------------------
# 2. Pitch code branches
# ---------------------------------------------------------------------------

@needs_pil
def test_no_pitches():
    """No pitches."""
    from pitch_view import render_pitch_view
    result = render_pitch_view(_base_game(pitches=[]))
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)


@needs_pil
def test_all_pitch_codes():
    """All pitch codes."""
    from pitch_view import render_pitch_view
    pitches = [
        {'px': -0.5, 'pz': 2.0, 'code': 'S', 'seq': 1, 'pitch_type': 'FB', 'speed': 95.0},
        {'px': -0.2, 'pz': 2.2, 'code': 'C', 'seq': 2, 'pitch_type': 'SL', 'speed': 84.0},
        {'px': 0.0, 'pz': 2.4, 'code': 'T', 'seq': 3, 'pitch_type': 'CH', 'speed': 87.0},
        {'px': 0.2, 'pz': 2.6, 'code': 'F', 'seq': 4, 'pitch_type': 'CB', 'speed': 79.0},
        {'px': 0.4, 'pz': 2.8, 'code': 'X', 'seq': 5, 'pitch_type': 'FB', 'speed': 96.0},
        {'px': -0.8, 'pz': 3.9, 'code': 'B', 'seq': 6, 'pitch_type': 'SI', 'speed': 92.0},
        {'px': None, 'pz': None, 'code': 'B', 'seq': 7, 'pitch_type': 'FB', 'speed': 91.0},
    ]
    result = render_pitch_view(_base_game(pitches=pitches))
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)


@needs_pil
def test_pitch_missing_speed_and_type():
    """speed=None / missing pitch_type must not crash the log line formatting."""
    from pitch_view import render_pitch_view
    pitches = [
        {'code': 'B', 'seq': 1},
        {'px': 0.1, 'pz': 2.0, 'code': 'S', 'seq': 2, 'speed': None},
    ]
    result = render_pitch_view(_base_game(pitches=pitches))
    assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# 3. Missing optional keys
# ---------------------------------------------------------------------------

@needs_pil
def test_missing_batter_pitcher():
    """Missing batter pitcher."""
    from pitch_view import render_pitch_view
    game = _base_game()
    game.pop('batter', None)
    game.pop('pitcher', None)
    result = render_pitch_view(game)
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)


@needs_pil
def test_empty_data_dict():
    """Empty data dict."""
    from pitch_view import render_pitch_view
    result = render_pitch_view({})
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)
    assert result.mode == '1'


# ---------------------------------------------------------------------------
# 4. detailed_state branches
# ---------------------------------------------------------------------------

@needs_pil
@pytest.mark.parametrize('state', ['Scheduled', 'Warmup', 'In Progress', 'Final', 'Game Over'])
def test_detailed_state_variants(state):
    """Detailed state variants."""
    from pitch_view import render_pitch_view
    result = render_pitch_view(_base_game(detailed_state=state))
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)


# ---------------------------------------------------------------------------
# 5. dark_mode
# ---------------------------------------------------------------------------

@needs_pil
def test_dark_mode_true():
    """Dark mode true."""
    from pitch_view import render_pitch_view
    result = render_pitch_view(_base_game(), dark_mode=True)
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)
    assert result.mode == '1'


@needs_pil
def test_dark_mode_false():
    """Dark mode false."""
    from pitch_view import render_pitch_view
    result = render_pitch_view(_base_game(), dark_mode=False)
    assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# 6. Long pitch log — exercises the y > 468 break
# ---------------------------------------------------------------------------

@needs_pil
def test_long_pitch_log_overflow():
    """Long pitch log overflow."""
    from pitch_view import render_pitch_view
    pitches = [
        {'px': 0.1 * (i % 3 - 1), 'pz': 2.0 + 0.05 * i, 'code': 'S' if i % 2 else 'B',
         'seq': i, 'pitch_type': 'Fastball', 'speed': 90.0 + i}
        for i in range(60)
    ]
    result = render_pitch_view(_base_game(pitches=pitches))
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)
