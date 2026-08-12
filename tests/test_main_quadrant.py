"""Tests for main.py's team-quadrant refresh and no-games display helpers.

All network, render and display access is mocked, following the pattern in
test_main_derby.py.
"""
from unittest.mock import patch

import main


def _config(**overrides):
    """A config with the quadrant mode selected."""
    config = {'display_mode': 'quadrant', 'league_mode': 'mlb', 'night_mode': False}
    config.update(overrides)
    return config


class TestRefreshTeamQuadrant:
    def test_fetches_when_the_quadrant_mode_is_on_screen(self):
        """The only mode that needs this data is the one that draws it."""
        with patch('main.fetch_team_quadrant') as fetch:
            main._refresh_team_quadrant(_config(), 'mlb')
        fetch.assert_called_once_with(force=False)

    def test_skips_for_every_other_display_mode(self):
        """A scoreboard user never pays for the extra Stats API calls."""
        with patch('main.fetch_team_quadrant') as fetch:
            main._refresh_team_quadrant(_config(display_mode='scoreboard'), 'mlb')
        fetch.assert_not_called()

    def test_skips_in_triple_a_mode(self):
        """The date-ranged team splits are MLB-only."""
        with patch('main.fetch_team_quadrant') as fetch:
            main._refresh_team_quadrant(_config(), 'aaa')
        fetch.assert_not_called()

    def test_passes_the_force_flag_through(self):
        """--full-refresh and dark-mode transitions bypass the 6-hour TTL."""
        with patch('main.fetch_team_quadrant') as fetch:
            main._refresh_team_quadrant(_config(), 'mlb', force=True)
        fetch.assert_called_once_with(force=True)

    def test_a_failed_fetch_never_breaks_the_cycle(self):
        """A bad API call leaves the previous chart up instead of crashing main()."""
        with patch('main.fetch_team_quadrant', side_effect=OSError('timeout')):
            main._refresh_team_quadrant(_config(), 'mlb')


class TestMaybeShowQuadrant:
    def test_returns_false_for_other_modes_without_rendering(self):
        """Off-days fall through to the idle screen unless quadrant is selected."""
        with patch('main.render') as render:
            result = main._maybe_show_quadrant(_config(display_mode='scoreboard'))
        assert result is False
        render.assert_not_called()

    def test_renders_and_pushes_to_the_panel(self):
        """On a no-games day the chart replaces the idle screen."""
        with patch('main._refresh_team_quadrant'), \
             patch('main.render', return_value=('image', [(0, 0, 800, 480)])), \
             patch('main.send_to_display', return_value='full') as display:
            result = main._maybe_show_quadrant(_config(), no_throttle=True)
        assert result is True
        display.assert_called_once()

    def test_returns_false_when_there_is_nothing_to_render(self):
        """Missing data hands the off-day back to the idle screen."""
        with patch('main._refresh_team_quadrant'), \
             patch('main.render', return_value=None), \
             patch('main.send_to_display') as display:
            result = main._maybe_show_quadrant(_config())
        assert result is False
        display.assert_not_called()

    def test_applies_night_mode_when_enabled(self):
        """The chart honours the same dark window as every other view."""
        with patch('main._refresh_team_quadrant'), \
             patch('main._in_dark_window', return_value=True), \
             patch('main.render', return_value=('image', [])) as render, \
             patch('main.send_to_display', return_value='full'):
            main._maybe_show_quadrant(_config(night_mode=True))
        assert render.call_args.args[0]['dark_mode'] is True

    def test_refreshes_the_data_before_rendering(self):
        """An off-day render must not show a stale chart."""
        with patch('main._refresh_team_quadrant') as refresh, \
             patch('main.render', return_value=('image', [])), \
             patch('main.send_to_display', return_value='full'):
            main._maybe_show_quadrant(_config())
        refresh.assert_called_once()
