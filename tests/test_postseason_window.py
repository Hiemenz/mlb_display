"""Tests for standings.is_postseason_window — the coarse date gate that lets
main.py auto-toggle the playoff bracket on without a manual config flip,
while skipping the schedule API entirely outside the postseason months."""
from datetime import datetime

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
