"""Tests for src/replay.py — time-based game-day replay on the e-ink display."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import pytz

import replay as replay_mod
from replay import replay_day

UTC = pytz.utc


def _dt(hour, minute=0):
    return UTC.localize(datetime(2026, 8, 1, hour, minute, 0))


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_TEAM_DATA = {
    'team_abbreviation': {
        '112': 'CHC',
        '158': 'MIL',
        '147': 'NYY',
        '111': 'BOS',
    }
}

_BASE_GAMES = [
    {'game_pk': 1001, 'away_team_id': 112, 'home_team_id': 158,
     'away_team_name': 'Chicago Cubs', 'home_team_name': 'Milwaukee Brewers',
     'detailed_state': 'Final'},
    {'game_pk': 1002, 'away_team_id': 147, 'home_team_id': 111,
     'away_team_name': 'New York Yankees', 'home_team_name': 'Boston Red Sox',
     'detailed_state': 'Final'},
]


def _make_tl(first_pitch_hour=20, last_play_hour=23):
    """Minimal timeline dict with a sensible time window."""
    fp = _dt(first_pitch_hour)
    lp = _dt(last_play_hour)
    return {
        'pitch_events': [],
        'plays': [],
        'wp_events': [],
        'hit_events': [],
        'header_events': [],
        'pitcher_k_events': [],
        'challenge_events': [],
        'next_batters_events': [],
        'first_pitch_utc': fp,
        'first_actual_pitch_utc': fp,
        'last_play_utc': lp,
        'scheduled_start_utc': fp,
    }


def _patched_load(name, *a, **kw):
    if 'games' in name:
        return {'games': _BASE_GAMES}
    return _TEAM_DATA


# ---------------------------------------------------------------------------
# replay_day — core time-advance loop
# ---------------------------------------------------------------------------

@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._game_state_at_time')
@patch('replay._any_game_active', return_value=True)
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file', side_effect=_patched_load)
@patch('replay.fetch_scoreboard_for_date')
@patch('replay.time.sleep')
def test_replay_day_renders_and_displays_each_active_step(
        mock_sleep, mock_fetch, mock_load, mock_tl, mock_active,
        mock_gsat, mock_orc, mock_disp,
):
    """A frame is rendered and pushed for every active step in the window."""
    tl = _make_tl(20, 20)   # 0-minute window → exactly 1 step
    mock_tl.return_value = tl
    mock_gsat.return_value = {'game_pk': 1001}
    fake_image = MagicMock()
    mock_orc.return_value = (fake_image, [])

    replay_day('2026-08-01', step_minutes=1, real_delay=0, config={}, local_mode=False)

    assert mock_orc.call_count >= 1
    assert mock_disp.call_count >= 1


@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._game_state_at_time')
@patch('replay._any_game_active', return_value=False)
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file', side_effect=_patched_load)
@patch('replay.fetch_scoreboard_for_date')
@patch('replay.time.sleep')
def test_replay_day_skips_inactive_steps(
        mock_sleep, mock_fetch, mock_load, mock_tl, mock_active,
        mock_gsat, mock_orc, mock_disp,
):
    """Steps where no games are active are skipped (no render, no display push)."""
    mock_tl.return_value = _make_tl(20, 20)

    replay_day('2026-08-01', step_minutes=1, real_delay=0, config={}, local_mode=False)

    mock_orc.assert_not_called()
    mock_disp.assert_not_called()


@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file')
@patch('replay.fetch_scoreboard_for_date')
def test_replay_day_no_games_returns_early(
        mock_fetch, mock_load, mock_tl, mock_orc, mock_disp,
):
    """Empty schedule: nothing is fetched or displayed."""
    mock_load.return_value = {'games': []}

    replay_day('2026-08-01', step_minutes=1, real_delay=0, config={}, local_mode=False)

    mock_tl.assert_not_called()
    mock_orc.assert_not_called()


@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._game_state_at_time')
@patch('replay._any_game_active', return_value=True)
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file', side_effect=_patched_load)
@patch('replay.fetch_scoreboard_for_date')
@patch('replay.time.sleep')
def test_replay_day_local_mode_skips_display(
        mock_sleep, mock_fetch, mock_load, mock_tl, mock_active,
        mock_gsat, mock_orc, mock_disp,
):
    """local_mode=True: orchestrate runs but send_to_display is never called."""
    mock_tl.return_value = _make_tl(20, 20)
    mock_gsat.return_value = {'game_pk': 1001}
    mock_orc.return_value = (MagicMock(), [])

    replay_day('2026-08-01', step_minutes=1, real_delay=0, config={}, local_mode=True)

    mock_orc.assert_called()
    mock_disp.assert_not_called()


@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._game_state_at_time')
@patch('replay._any_game_active', return_value=True)
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file', side_effect=_patched_load)
@patch('replay.fetch_scoreboard_for_date')
@patch('replay.time.sleep')
def test_replay_day_orchestrate_none_does_not_push(
        mock_sleep, mock_fetch, mock_load, mock_tl, mock_active,
        mock_gsat, mock_orc, mock_disp,
):
    """When orchestrate returns None (unchanged image), send_to_display is not called."""
    mock_tl.return_value = _make_tl(20, 20)
    mock_gsat.return_value = {'game_pk': 1001}
    mock_orc.return_value = None

    replay_day('2026-08-01', step_minutes=1, real_delay=0, config={}, local_mode=False)

    mock_disp.assert_not_called()


@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._game_state_at_time')
@patch('replay._any_game_active', return_value=True)
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file', side_effect=_patched_load)
@patch('replay.fetch_scoreboard_for_date')
@patch('replay.time.sleep')
def test_replay_day_render_error_continues_to_next_step(
        mock_sleep, mock_fetch, mock_load, mock_tl, mock_active,
        mock_gsat, mock_orc, mock_disp,
):
    """A render exception on one step doesn't abort the whole replay."""
    mock_tl.return_value = _make_tl(20, 20)
    mock_gsat.return_value = {'game_pk': 1001}
    mock_orc.side_effect = [RuntimeError("render failed"), (MagicMock(), [])]

    # Should not raise
    replay_day('2026-08-01', step_minutes=1, real_delay=0, config={}, local_mode=False)


@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._game_state_at_time')
@patch('replay._any_game_active', return_value=True)
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file', side_effect=_patched_load)
@patch('replay.fetch_scoreboard_for_date')
@patch('replay.time.sleep')
def test_replay_day_reconstructs_each_game_at_current_time(
        mock_sleep, mock_fetch, mock_load, mock_tl, mock_active,
        mock_gsat, mock_orc, mock_disp,
):
    """_game_state_at_time is called once per game per active step."""
    mock_tl.return_value = _make_tl(20, 20)  # 1-step window
    mock_gsat.return_value = {'game_pk': 1001}
    mock_orc.return_value = (MagicMock(), [])

    replay_day('2026-08-01', step_minutes=1, real_delay=0, config={}, local_mode=False)

    # Each active step reconstructs every game once, so call count is a multiple of 2
    assert mock_gsat.call_count > 0
    assert mock_gsat.call_count % len(_BASE_GAMES) == 0


@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._game_state_at_time')
@patch('replay._any_game_active', return_value=True)
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file', side_effect=_patched_load)
@patch('replay.fetch_scoreboard_for_date')
@patch('replay.time.sleep', side_effect=KeyboardInterrupt)
def test_replay_day_keyboard_interrupt_stops_cleanly(
        mock_sleep, mock_fetch, mock_load, mock_tl, mock_active,
        mock_gsat, mock_orc, mock_disp,
):
    """KeyboardInterrupt during sleep stops replay without raising."""
    mock_tl.return_value = _make_tl(20, 21)
    mock_gsat.return_value = {'game_pk': 1001}
    mock_orc.return_value = (MagicMock(), [])

    # Should not propagate the KeyboardInterrupt
    replay_day('2026-08-01', step_minutes=1, real_delay=5, config={}, local_mode=False)


# ---------------------------------------------------------------------------
# main() — argument parsing
# ---------------------------------------------------------------------------

@patch('replay.replay_day')
@patch('replay.load_config', return_value={})
def test_main_passes_defaults(mock_cfg, mock_rd):
    """main() uses module-level defaults when config has no replay keys."""
    import sys
    with patch.object(sys, 'argv', ['replay.py', '--date', '2026-08-01']):
        replay_mod.main()

    _, kwargs = mock_rd.call_args
    assert kwargs['date_str'] == '2026-08-01'
    assert kwargs['step_minutes'] == replay_mod._DEFAULT_STEP_MINUTES
    assert kwargs['real_delay'] == replay_mod._DEFAULT_DELAY_SECONDS
    assert kwargs['local_mode'] is False


@patch('replay.replay_day')
@patch('replay.load_config', return_value={})
def test_main_custom_step_and_delay(mock_cfg, mock_rd):
    """--step and --delay CLI args override config values."""
    import sys
    with patch.object(sys, 'argv', [
        'replay.py', '--date', '2026-08-01', '--step', '2', '--delay', '10',
    ]):
        replay_mod.main()

    _, kwargs = mock_rd.call_args
    assert kwargs['step_minutes'] == 2.0
    assert kwargs['real_delay'] == 10.0


@patch('replay.replay_day')
@patch('replay.load_config', return_value={
    'replay_date': '2026-07-04',
    'replay_step_minutes': 3,
    'replay_delay_seconds': 45,
})
def test_main_reads_date_and_pacing_from_config(mock_cfg, mock_rd):
    """When no CLI args given, main() falls back to replay_* keys in config."""
    import sys
    with patch.object(sys, 'argv', ['replay.py']):
        replay_mod.main()

    _, kwargs = mock_rd.call_args
    assert kwargs['date_str'] == '2026-07-04'
    assert kwargs['step_minutes'] == 3.0
    assert kwargs['real_delay'] == 45.0


@patch('replay.replay_day')
@patch('replay.load_config', return_value={'replay_date': '2026-07-04'})
def test_main_cli_date_overrides_config_date(mock_cfg, mock_rd):
    """--date on the CLI wins over replay_date in config."""
    import sys
    with patch.object(sys, 'argv', ['replay.py', '--date', '2026-08-01']):
        replay_mod.main()

    _, kwargs = mock_rd.call_args
    assert kwargs['date_str'] == '2026-08-01'


@patch('replay.replay_day')
@patch('replay.load_config', return_value={})
def test_main_local_flag(mock_cfg, mock_rd):
    """--local sets local_mode=True."""
    import sys
    with patch.object(sys, 'argv', ['replay.py', '--date', '2026-08-01', '--local']):
        replay_mod.main()

    _, kwargs = mock_rd.call_args
    assert kwargs['local_mode'] is True


def test_main_no_date_no_config_exits():
    """main() exits when neither --date nor config replay_date is set."""
    import sys
    with patch('replay.load_config', return_value={'replay_date': ''}):
        with patch.object(sys, 'argv', ['replay.py']):
            with pytest.raises(SystemExit):
                replay_mod.main()


@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._game_state_at_time')
@patch('replay._any_game_active', return_value=True)
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file', side_effect=_patched_load)
@patch('replay.fetch_scoreboard_for_date')
@patch('replay.time.sleep')
@patch('replay.ImageFont.load_default', return_value=MagicMock())
@patch('replay.ImageFont.truetype', side_effect=OSError('font not found'))
def test_replay_day_font_fallback_on_truetype_error(
        mock_truetype, mock_load_default, mock_sleep, mock_fetch, mock_load,
        mock_tl, mock_active, mock_gsat, mock_orc, mock_disp,
):
    """Falls back to ImageFont.load_default() when Font.ttc cannot be loaded."""
    mock_tl.return_value = _make_tl(20, 20)
    mock_gsat.return_value = {'game_pk': 1001}
    mock_orc.return_value = (MagicMock(), [])

    # Should not raise even when truetype fails
    replay_day('2026-08-01', step_minutes=1, real_delay=0, config={}, local_mode=False)

    mock_load_default.assert_called_once()
    assert mock_orc.call_count >= 1
