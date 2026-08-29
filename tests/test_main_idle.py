"""Tests for main._show_idle_screen's three-way rotation: recent transactions,
the team quadrant chart and the playoff-race view, one per 20-minute block.

All network, render and display access is mocked, following the pattern in
test_main_quadrant.py.
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import main


def _config(**overrides):
    config = {'night_mode': False}
    config.update(overrides)
    return config


def _loader(quadrant_payload=None, standings_payload=None, teams_payload=None,
            transactions_payload=None):
    """Build a load_json_file side_effect that never touches real data/ files."""
    quadrant_payload = quadrant_payload if quadrant_payload is not None else {}
    standings_payload = standings_payload if standings_payload is not None else {}
    teams_payload = teams_payload if teams_payload is not None else {'team_abbreviation': {}}
    transactions_payload = transactions_payload if transactions_payload is not None else {
        'transactions': [{'date': '2026-08-29'}], 'fetched_at': 9e12,
    }

    def _fn(filename, file_path=None):
        if filename == 'team_quadrant.json':
            return quadrant_payload
        if filename == 'standings.json':
            return standings_payload
        if filename == 'teams.json':
            return teams_payload
        if filename == 'transactions.json':
            return transactions_payload
        return {}
    return _fn


def _at_minute(minute):
    """A fixed datetime whose minute selects the given rotation slot."""
    return datetime(2026, 8, 29, 12, minute)


class TestIdleRotationSlotSelection:
    def test_slot_0_shows_transactions(self):
        """Minutes 0-19: the transactions view, regardless of other data."""
        with patch('main.datetime') as mock_dt, \
             patch('main.load_json_file', side_effect=_loader(
                 quadrant_payload={'grains': {'month': {}}},
                 standings_payload={'standings': {'AL East': []}})), \
             patch('refresh_tracker.needs_full_refresh', return_value=True), \
             patch('main.send_to_display'), \
             patch('main._in_dark_window', return_value=False), \
             patch('main.draw_idle_screen', return_value=MagicMock()) as m_idle, \
             patch('quadrant_view.render_quadrant_view') as m_quad, \
             patch('race_view.render_race_view') as m_race:
            mock_dt.now.return_value = _at_minute(5)
            main._show_idle_screen(_config())
        m_idle.assert_called_once()
        m_quad.assert_not_called()
        m_race.assert_not_called()

    def test_slot_1_shows_quadrant_when_data_present(self):
        """Minutes 20-39: the quadrant chart, when its data is cached."""
        fake_image = MagicMock()
        with patch('main.datetime') as mock_dt, \
             patch('main.load_json_file', side_effect=_loader(
                 quadrant_payload={'grains': {'month': {}}})), \
             patch('refresh_tracker.needs_full_refresh', return_value=True), \
             patch('main.send_to_display'), \
             patch('main._in_dark_window', return_value=False), \
             patch('main.draw_idle_screen') as m_idle, \
             patch('quadrant_view.render_quadrant_view', return_value=fake_image) as m_quad:
            mock_dt.now.return_value = _at_minute(25)
            main._show_idle_screen(_config())
        m_quad.assert_called_once()
        m_idle.assert_not_called()

    def test_slot_1_falls_back_to_transactions_without_quadrant_data(self):
        """No cached team_quadrant.json — the slot falls back to transactions."""
        with patch('main.datetime') as mock_dt, \
             patch('main.load_json_file', side_effect=_loader(quadrant_payload={})), \
             patch('refresh_tracker.needs_full_refresh', return_value=True), \
             patch('main.send_to_display'), \
             patch('main._in_dark_window', return_value=False), \
             patch('main.draw_idle_screen', return_value=MagicMock()) as m_idle:
            mock_dt.now.return_value = _at_minute(25)
            main._show_idle_screen(_config())
        m_idle.assert_called_once()

    def test_slot_1_falls_back_when_quadrant_rotation_disabled(self):
        """idle_quadrant_rotation=False skips the quadrant slot even with data."""
        with patch('main.datetime') as mock_dt, \
             patch('main.load_json_file', side_effect=_loader(
                 quadrant_payload={'grains': {'month': {}}})), \
             patch('refresh_tracker.needs_full_refresh', return_value=True), \
             patch('main.send_to_display'), \
             patch('main._in_dark_window', return_value=False), \
             patch('main.draw_idle_screen', return_value=MagicMock()) as m_idle, \
             patch('quadrant_view.render_quadrant_view') as m_quad:
            mock_dt.now.return_value = _at_minute(25)
            main._show_idle_screen(_config(idle_quadrant_rotation=False))
        m_idle.assert_called_once()
        m_quad.assert_not_called()

    def test_slot_1_falls_back_when_quadrant_render_raises(self):
        """A broken chart render must not crash the idle cycle."""
        with patch('main.datetime') as mock_dt, \
             patch('main.load_json_file', side_effect=_loader(
                 quadrant_payload={'grains': {'month': {}}})), \
             patch('refresh_tracker.needs_full_refresh', return_value=True), \
             patch('main.send_to_display'), \
             patch('main._in_dark_window', return_value=False), \
             patch('main.draw_idle_screen', return_value=MagicMock()) as m_idle, \
             patch('quadrant_view.render_quadrant_view', side_effect=ValueError('empty')):
            mock_dt.now.return_value = _at_minute(25)
            main._show_idle_screen(_config())
        m_idle.assert_called_once()

    def test_slot_2_shows_race_when_data_present(self):
        """Minutes 40-59: the playoff-race view, when standings are cached."""
        fake_image = MagicMock()
        with patch('main.datetime') as mock_dt, \
             patch('main.load_json_file', side_effect=_loader(
                 standings_payload={'standings': {'AL East': []}})), \
             patch('refresh_tracker.needs_full_refresh', return_value=True), \
             patch('main.send_to_display'), \
             patch('main._in_dark_window', return_value=False), \
             patch('main.draw_idle_screen') as m_idle, \
             patch('race_view.render_race_view', return_value=fake_image) as m_race:
            mock_dt.now.return_value = _at_minute(45)
            main._show_idle_screen(_config())
        m_race.assert_called_once()
        m_idle.assert_not_called()

    def test_slot_2_falls_back_to_transactions_without_standings_data(self):
        """No cached standings.json — the slot falls back to transactions."""
        with patch('main.datetime') as mock_dt, \
             patch('main.load_json_file', side_effect=_loader(standings_payload={})), \
             patch('refresh_tracker.needs_full_refresh', return_value=True), \
             patch('main.send_to_display'), \
             patch('main._in_dark_window', return_value=False), \
             patch('main.draw_idle_screen', return_value=MagicMock()) as m_idle:
            mock_dt.now.return_value = _at_minute(45)
            main._show_idle_screen(_config())
        m_idle.assert_called_once()

    def test_slot_2_falls_back_when_race_rotation_disabled(self):
        """idle_race_rotation=False skips the race slot even with data."""
        with patch('main.datetime') as mock_dt, \
             patch('main.load_json_file', side_effect=_loader(
                 standings_payload={'standings': {'AL East': []}})), \
             patch('refresh_tracker.needs_full_refresh', return_value=True), \
             patch('main.send_to_display'), \
             patch('main._in_dark_window', return_value=False), \
             patch('main.draw_idle_screen', return_value=MagicMock()) as m_idle, \
             patch('race_view.render_race_view') as m_race:
            mock_dt.now.return_value = _at_minute(45)
            main._show_idle_screen(_config(idle_race_rotation=False))
        m_idle.assert_called_once()
        m_race.assert_not_called()

    def test_slot_2_falls_back_when_race_render_raises(self):
        """A broken race-view render must not crash the idle cycle."""
        with patch('main.datetime') as mock_dt, \
             patch('main.load_json_file', side_effect=_loader(
                 standings_payload={'standings': {'AL East': []}})), \
             patch('refresh_tracker.needs_full_refresh', return_value=True), \
             patch('main.send_to_display'), \
             patch('main._in_dark_window', return_value=False), \
             patch('main.draw_idle_screen', return_value=MagicMock()) as m_idle, \
             patch('race_view.render_race_view', side_effect=ValueError('empty')):
            mock_dt.now.return_value = _at_minute(45)
            main._show_idle_screen(_config())
        m_idle.assert_called_once()
