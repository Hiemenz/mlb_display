"""Tests for main.py's Home Run Derby auto-detection helpers.

Mocks all network/render/display access so these run offline, following the
pattern in test_fetch_derby.py.
"""
from unittest.mock import patch, MagicMock

import main


def _base_config(**overrides):
    config = {'timezone': 'America/Chicago', 'auto_derby_mode': True}
    config.update(overrides)
    return config


class TestMaybeShowDerbyBracket:
    def test_disabled_returns_false_without_lookup(self):
        config = _base_config(auto_derby_mode=False)
        with patch('main.get_derby_date') as mock_get_date:
            result = main._maybe_show_derby_bracket(config)
        assert result is False
        mock_get_date.assert_not_called()

    def test_not_derby_day_returns_false(self):
        config = _base_config()
        with patch('main.get_derby_date', return_value=('2026-01-01', 999)), \
             patch('main._run_derby_mode') as mock_run:
            result = main._maybe_show_derby_bracket(config)
        assert result is False
        mock_run.assert_not_called()

    def test_lookup_failure_returns_false(self):
        config = _base_config()
        with patch('main.get_derby_date', side_effect=OSError('timeout')), \
             patch('main._run_derby_mode') as mock_run:
            result = main._maybe_show_derby_bracket(config)
        assert result is False
        mock_run.assert_not_called()

    def test_derby_day_runs_derby_mode_and_returns_true(self):
        config = _base_config()
        import pytz
        from datetime import datetime
        today_str = datetime.now(pytz.timezone(config['timezone'])).strftime('%Y-%m-%d')
        with patch('main.get_derby_date', return_value=(today_str, 838655)), \
             patch('main._run_derby_mode') as mock_run:
            result = main._maybe_show_derby_bracket(config, no_throttle=True, auto_open=False)
        assert result is True
        mock_run.assert_called_once_with(config, event_id=838655, no_throttle=True, auto_open=False)


class TestRunDerbyMode:
    def test_fetch_failure_still_renders(self):
        config = _base_config()
        with patch('main.fetch_and_save_derby_bracket', side_effect=OSError('boom')), \
             patch('main.render', return_value=None) as mock_render:
            main._run_derby_mode(config, event_id=1, no_throttle=True)
        mock_render.assert_called_once()
        assert mock_render.call_args.args[0]['display_mode'] == 'derby'

    def test_no_result_skips_display(self):
        config = _base_config()
        with patch('main.fetch_and_save_derby_bracket', return_value={'state': 'Final'}), \
             patch('main.render', return_value=None), \
             patch('main.send_to_display') as mock_display:
            main._run_derby_mode(config)
        mock_display.assert_not_called()

    def test_successful_render_sends_to_display(self):
        config = _base_config()
        fake_image = MagicMock()
        with patch('main.fetch_and_save_derby_bracket', return_value={'state': 'Final'}), \
             patch('main.render', return_value=(fake_image, [(0, 0, 800, 480)])), \
             patch('main.send_to_display', return_value='full') as mock_display:
            main._run_derby_mode(config, no_throttle=True)
        mock_display.assert_called_once()

    def test_preview_state_runs_only_once_no_sleep(self):
        config = _base_config()
        with patch('main.fetch_and_save_derby_bracket', return_value={'state': 'Preview'}), \
             patch('main.render', return_value=None) as mock_render, \
             patch('main.time.sleep') as mock_sleep:
            main._run_derby_mode(config)
        assert mock_render.call_count == 1
        mock_sleep.assert_not_called()

    def test_none_bracket_runs_only_once_no_sleep(self):
        config = _base_config()
        with patch('main.fetch_and_save_derby_bracket', return_value=None), \
             patch('main.render', return_value=None) as mock_render, \
             patch('main.time.sleep') as mock_sleep:
            main._run_derby_mode(config)
        assert mock_render.call_count == 1
        mock_sleep.assert_not_called()

    def test_in_progress_state_polls_every_minute_until_final(self):
        config = _base_config()
        states = iter([{'state': 'In Progress'}, {'state': 'In Progress'}, {'state': 'Final'}])
        with patch('main.fetch_and_save_derby_bracket', side_effect=lambda **kw: next(states)), \
             patch('main.render', return_value=None) as mock_render, \
             patch('main.time.sleep') as mock_sleep:
            main._run_derby_mode(config)
        assert mock_render.call_count == 3
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(main._DERBY_LIVE_POLL_SECONDS)

    def test_in_progress_state_stops_at_safety_cap(self):
        config = _base_config()
        # monotonic() is read once for start, then once per loop iteration to check elapsed time.
        # Return a start time, then a time already past the cap so the loop stops after one fetch.
        with patch('main.fetch_and_save_derby_bracket', return_value={'state': 'In Progress'}), \
             patch('main.render', return_value=None) as mock_render, \
             patch('main.time.sleep') as mock_sleep, \
             patch('main.time.monotonic', side_effect=[0, main._DERBY_LIVE_POLL_MAX_SECONDS + 1]):
            main._run_derby_mode(config)
        assert mock_render.call_count == 1
        mock_sleep.assert_not_called()
