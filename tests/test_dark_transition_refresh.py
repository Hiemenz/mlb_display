"""Regression tests for the dark-mode transition render path in main.py.

The bug: at a dark/light transition main() saved last_dark_mode immediately,
then called render() with the normal unchanged-data cache. If no game data
had changed at that poll (common at night when most games are final),
render() returned None and main() exited without touching the display — the
forced full refresh for the polarity flip was silently swallowed, and no
later run re-detected the transition. Subsequent partial refreshes then
repainted only cells whose games changed, leaving stale opposite-polarity
bands (e.g. a washed-out light-mode column on a dark screen).

The fix: on a detected transition, render() must be called with
bypass_cache=True so an image is always produced and reaches the display.
"""
import sys
from unittest.mock import MagicMock

import main as main_mod


BASE_CONFIG = {
    'night_mode': False,   # skips the night-skip gate; _is_dark evaluates False
    'use_team_logos': False,
    'show_standings_sidebar': False,
    'show_wildcard_standings': False,
    'show_playoff_bracket': False,
    'show_transactions_ticker': False,
    'show_leaders_panel': False,
    'morning_alternate_games': False,
    'timezone': 'America/Chicago',
}


def _run_main(monkeypatch, tmp_path, sched, render_mock):
    """Drive main.main() down the on-Pi path (throttling active) with all
    network/display side effects stubbed out."""
    # Point _REPO_ROOT away from the repo so the real .env (ENV=test) doesn't
    # flip _no_throttle — the dark-transition branch only runs when throttled.
    monkeypatch.setattr(main_mod, '_REPO_ROOT', str(tmp_path))
    monkeypatch.delenv('ENV', raising=False)
    monkeypatch.setattr(main_mod.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(sys, 'argv', ['main.py'])

    monkeypatch.setattr(main_mod, 'load_config', lambda *a, **k: dict(BASE_CONFIG))
    monkeypatch.setattr(main_mod, '_load_schedule_state', lambda: sched)
    monkeypatch.setattr(main_mod, '_save_schedule_state', lambda s: None)
    monkeypatch.setattr(main_mod, '_should_skip_poll', lambda *a, **k: (False, ''))
    monkeypatch.setattr(main_mod, '_update_schedule_state', lambda *a, **k: False)
    monkeypatch.setattr(main_mod, 'fetch_scoreboard_for_date', lambda *a, **k: None)
    monkeypatch.setattr(main_mod, 'fetch_tomorrow_games', lambda *a, **k: None)
    monkeypatch.setattr(main_mod, 'render', render_mock)
    monkeypatch.setattr(main_mod, 'send_to_display', MagicMock(return_value='full'))

    main_mod.main()


def test_dark_transition_bypasses_render_cache(monkeypatch, tmp_path):
    """A dark→light transition must render even if game data is unchanged."""
    render_mock = MagicMock(return_value=None)
    # last run was dark, config now evaluates light → transition detected
    _run_main(monkeypatch, tmp_path, {'last_dark_mode': True}, render_mock)

    render_mock.assert_called_once()
    assert render_mock.call_args.kwargs['bypass_cache'] is True


def test_first_run_bypasses_render_cache(monkeypatch, tmp_path):
    """First run after boot/state reset (last_dark_mode missing) also forces
    a render so the display starts in the correct polarity."""
    render_mock = MagicMock(return_value=None)
    _run_main(monkeypatch, tmp_path, {}, render_mock)

    render_mock.assert_called_once()
    assert render_mock.call_args.kwargs['bypass_cache'] is True


def test_no_transition_keeps_render_cache(monkeypatch, tmp_path):
    """Steady state (no polarity change) keeps the unchanged-data cache so
    quiet polls still skip the display entirely."""
    render_mock = MagicMock(return_value=None)
    _run_main(monkeypatch, tmp_path, {'last_dark_mode': False}, render_mock)

    render_mock.assert_called_once()
    assert render_mock.call_args.kwargs['bypass_cache'] is False
