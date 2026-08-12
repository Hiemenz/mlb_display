"""Tests for the three-way morning rotation.

Between night_end and morning_end the display cycles today's games →
yesterday's games → the team quadrant, one view per 5-minute block.
"""
from collections import namedtuple
from datetime import datetime
from unittest.mock import patch

import pytest
import pytz

import main

_Args = namedtuple('_Args', ['date'])
_CT = pytz.timezone('America/Chicago')


def _config(**overrides):
    """Morning-window config with the rotation on."""
    config = {
        'timezone': 'America/Chicago',
        'night_end': 7,
        'morning_end': 9,
        'morning_alternate_games': True,
        'morning_alternate_quadrant': True,
    }
    config.update(overrides)
    return config


def _context(hour, minute, config=None):
    """Resolve the date context at a fixed local time."""
    now = _CT.localize(datetime(2026, 8, 10, hour, minute))
    with patch.object(main, '_local_now', return_value=now):
        return main._resolve_target_date(_Args(date=None), config or _config())


def _view(ctx):
    """Collapse a context to the view it represents."""
    if ctx.mode_override:
        return ctx.mode_override
    return 'yesterday' if ctx.showing_previous_day else 'today'


# ---------------------------------------------------------------------------
# Rotation membership
# ---------------------------------------------------------------------------

def test_rotation_is_three_way_by_default():
    """Today, yesterday, then the quadrant."""
    assert main.morning_rotation(_config()) == ('today', 'yesterday', 'quadrant')


def test_rotation_falls_back_to_the_original_two_way_cycle():
    """Opting out restores the yesterday/today alternation that predates the quadrant."""
    assert main.morning_rotation(_config(morning_alternate_quadrant=False)) == (
        'yesterday', 'today')


# ---------------------------------------------------------------------------
# Cycling
# ---------------------------------------------------------------------------

def test_every_view_appears_within_one_cycle():
    """Three consecutive blocks cover all three views."""
    views = [_view(_context(7, minute)) for minute in (0, 5, 10)]
    assert set(views) == {'today', 'yesterday', 'quadrant'}


def test_the_view_advances_every_five_minutes():
    """Each 5-minute block is a different view from the one before it."""
    views = [_view(_context(7, minute)) for minute in range(0, 60, 5)]
    assert all(a != b for a, b in zip(views, views[1:]))


def test_the_view_is_stable_inside_a_block():
    """Every minute of a block resolves to the same view and block index."""
    contexts = [_context(7, minute) for minute in (5, 6, 7, 8, 9)]
    assert len({c.morning_block for c in contexts}) == 1
    assert len({_view(c) for c in contexts}) == 1


def test_the_cycle_repeats_every_three_blocks():
    """Block N and block N+3 show the same thing."""
    assert _view(_context(7, 0)) == _view(_context(7, 15))
    assert _view(_context(7, 5)) == _view(_context(7, 20))


# ---------------------------------------------------------------------------
# What each view carries
# ---------------------------------------------------------------------------

def test_quadrant_blocks_override_the_display_mode():
    """The quadrant rides along as a mode override, not as a date."""
    quadrant = next(c for c in (_context(7, m) for m in (0, 5, 10))
                    if c.mode_override)
    assert quadrant.mode_override == 'quadrant'
    assert quadrant.showing_previous_day is False


def test_game_blocks_carry_no_mode_override():
    """Today/yesterday blocks leave the configured display mode alone."""
    game_views = [c for c in (_context(7, m) for m in (0, 5, 10))
                  if not c.mode_override]
    assert len(game_views) == 2
    assert {c.showing_previous_day for c in game_views} == {True, False}


def test_yesterday_block_targets_the_previous_day():
    """The yesterday view actually asks for yesterday's date."""
    yesterday = next(c for c in (_context(7, m) for m in (0, 5, 10))
                     if c.showing_previous_day)
    assert yesterday.date_str == '2026-08-09'


def test_every_block_carries_an_index_for_the_throttle():
    """morning_block is what the 5-minute poll gate keys on — it must never be None."""
    assert all(_context(7, m).morning_block is not None for m in range(0, 60, 5))


# ---------------------------------------------------------------------------
# Window boundaries — the rotation only runs during the morning
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('hour,minute', [(6, 30), (9, 5), (14, 0)])
def test_no_rotation_outside_the_morning_window(hour, minute):
    """Before night_end and after morning_end the display is not rotating."""
    ctx = _context(hour, minute)
    assert ctx.morning_block is None
    assert ctx.mode_override is None


def test_before_the_window_still_shows_yesterday():
    """Overnight keeps last night's finals up."""
    ctx = _context(6, 30)
    assert ctx.showing_previous_day is True
    assert ctx.date_str == '2026-08-09'


def test_after_the_cutoff_shows_today():
    """Past the morning cutoff the display settles on today."""
    ctx = _context(9, 5)
    assert ctx.date_str == '2026-08-10'
    assert ctx.showing_previous_day is False


def test_explicit_date_bypasses_the_rotation_entirely():
    """--date is a historical replay; it must not land on a quadrant block."""
    with patch.object(main, 'set_historical_mode'):
        ctx = main._resolve_target_date(_Args(date='2026-05-01'), _config())
    assert ctx.date_str == '2026-05-01'
    assert ctx.mode_override is None
    assert ctx.morning_block is None


def test_disabling_alternation_stops_the_rotation():
    """morning_alternate_games off means no blocks and no quadrant."""
    ctx = _context(7, 25, _config(morning_alternate_games=False))
    assert ctx.morning_block is None
    assert ctx.mode_override is None
    assert ctx.showing_previous_day is True
