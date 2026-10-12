"""Tests for standings.is_postseason_window — the coarse date gate that lets
main.py auto-toggle the playoff bracket on without a manual config flip,
while skipping the schedule API entirely outside the postseason months.

Also covers the main._refresh_playoff_bracket WS-complete guard: once the
World Series is over the bracket is final and must never be re-fetched."""
from datetime import datetime
from unittest.mock import patch, MagicMock

from standings import is_postseason_window


class TestIsPostseasonWindow:
    def test_early_october_is_in_window(self):
        """Early october is in window."""
        assert is_postseason_window(datetime(2026, 10, 3)) is True

    def test_late_october_is_in_window(self):
        """Late october is in window."""
        assert is_postseason_window(datetime(2026, 10, 31)) is True

    def test_mid_september_boundary_included(self):
        """Mid september boundary included."""
        assert is_postseason_window(datetime(2026, 9, 15)) is True

    def test_before_mid_september_excluded(self):
        """Before mid september excluded."""
        assert is_postseason_window(datetime(2026, 9, 14)) is False

    def test_early_september_excluded(self):
        """Early september excluded."""
        assert is_postseason_window(datetime(2026, 9, 1)) is False

    def test_mid_november_boundary_included(self):
        """Mid november boundary included."""
        assert is_postseason_window(datetime(2026, 11, 10)) is True

    def test_after_mid_november_excluded(self):
        """After mid november excluded."""
        assert is_postseason_window(datetime(2026, 11, 11)) is False

    def test_regular_season_month_excluded(self):
        """Regular season month excluded."""
        assert is_postseason_window(datetime(2026, 6, 15)) is False

    def test_offseason_month_excluded(self):
        """Offseason month excluded."""
        assert is_postseason_window(datetime(2026, 1, 15)) is False

    def test_december_excluded(self):
        """December excluded."""
        assert is_postseason_window(datetime(2026, 12, 25)) is False

    def test_defaults_to_now_when_no_arg_given(self):
        """No crash and returns a bool when called with no argument."""
        assert isinstance(is_postseason_window(), bool)


_WS_COMPLETE_BRACKET = {'series': [{'round': 'WS', 'complete': True, 'winner_abbr': 'NYY'}]}
_WS_LIVE_BRACKET     = {'series': [{'round': 'WS', 'complete': False}]}
_NO_WS_BRACKET       = {'series': [{'round': 'CS', 'complete': False}]}
_EMPTY_BRACKET       = {}


def _call_refresh(bracket_json, in_window=True, age_stale=True):
    """Call main._refresh_playoff_bracket with the given mocked bracket state."""
    import main
    config = {'show_playoff_bracket': True}
    with patch('main.is_postseason_window', return_value=in_window), \
         patch('main._should_refresh_playoff_bracket', return_value=age_stale), \
         patch('main.load_json_file', return_value=bracket_json), \
         patch('main.fetch_playoff_bracket') as mock_fetch:
        main._refresh_playoff_bracket(config, league_mode='mlb')
    return mock_fetch


class TestRefreshPlayoffBracketWSGuard:
    def test_ws_complete_suppresses_fetch(self):
        """Once the WS is marked complete the bracket is never re-fetched."""
        mock = _call_refresh(_WS_COMPLETE_BRACKET)
        mock.assert_not_called()

    def test_ws_live_allows_fetch(self):
        """While the WS is still in progress, refreshes continue."""
        mock = _call_refresh(_WS_LIVE_BRACKET)
        mock.assert_called_once()

    def test_no_ws_series_yet_allows_fetch(self):
        """Before the WS begins (only CS/DS data), refreshes continue."""
        mock = _call_refresh(_NO_WS_BRACKET)
        mock.assert_called_once()

    def test_empty_bracket_allows_fetch(self):
        """No cached bracket at all → fetch to populate it."""
        mock = _call_refresh(_EMPTY_BRACKET)
        mock.assert_called_once()

    def test_outside_postseason_window_still_suppressed(self):
        """Calendar gate blocks fetch regardless of WS state."""
        mock = _call_refresh(_WS_LIVE_BRACKET, in_window=False)
        mock.assert_not_called()

    def test_fresh_cache_suppressed_unless_forced(self):
        """Non-stale cache skips fetch even with live WS."""
        mock = _call_refresh(_WS_LIVE_BRACKET, age_stale=False)
        mock.assert_not_called()
