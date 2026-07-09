"""Tests for src/refresh_tracker.py — e-ink full/partial refresh scheduling state."""
import json
from unittest.mock import patch

import pytest

import refresh_tracker as rt


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    """State file."""
    path = tmp_path / 'refresh_state.json'
    monkeypatch.setattr(rt, 'STATE_FILE', str(path))
    return path


# ===========================================================================
# _load_state
# ===========================================================================

class TestLoadState:
    def test_missing_file_returns_empty_dict(self, state_file):
        """Missing file returns empty dict."""
        assert rt._load_state() == {}

    def test_valid_file_returns_data(self, state_file):
        """Valid file returns data."""
        state_file.write_text(json.dumps({'last_full_refresh': 100.0}))
        assert rt._load_state() == {'last_full_refresh': 100.0}

    def test_malformed_json_returns_empty_dict(self, state_file):
        """Malformed json returns empty dict."""
        state_file.write_text('{not json')
        assert rt._load_state() == {}


# ===========================================================================
# needs_full_refresh
# ===========================================================================

class TestNeedsFullRefresh:
    def test_no_prior_state_needs_refresh(self, state_file):
        """No prior state needs refresh."""
        assert rt.needs_full_refresh() is True

    def test_recent_refresh_does_not_need_refresh(self, state_file):
        """Recent refresh does not need refresh."""
        state_file.write_text(json.dumps({'last_full_refresh': 1000.0}))
        with patch.object(rt.time, 'time', return_value=1000.0 + 100):
            assert rt.needs_full_refresh() is False

    def test_stale_refresh_needs_refresh(self, state_file):
        """Stale refresh needs refresh."""
        state_file.write_text(json.dumps({'last_full_refresh': 1000.0}))
        with patch.object(rt.time, 'time', return_value=1000.0 + rt.FULL_REFRESH_INTERVAL):
            assert rt.needs_full_refresh() is True

    def test_just_under_interval_does_not_need_refresh(self, state_file):
        """Just under interval does not need refresh."""
        state_file.write_text(json.dumps({'last_full_refresh': 1000.0}))
        with patch.object(rt.time, 'time', return_value=1000.0 + rt.FULL_REFRESH_INTERVAL - 1):
            assert rt.needs_full_refresh() is False


# ===========================================================================
# record_full_refresh
# ===========================================================================

class TestRecordFullRefresh:
    def test_writes_timestamp_and_resets_counter(self, state_file):
        """Writes timestamp and resets counter."""
        state_file.write_text(json.dumps({'partial_refresh_count': 5}))
        with patch.object(rt.time, 'time', return_value=12345.0):
            rt.record_full_refresh()
        data = json.loads(state_file.read_text())
        assert data['last_full_refresh'] == 12345.0
        assert data['partial_refresh_count'] == 0

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        """Creates parent directory."""
        nested = tmp_path / 'nested' / 'refresh_state.json'
        monkeypatch.setattr(rt, 'STATE_FILE', str(nested))
        with patch.object(rt.time, 'time', return_value=1.0):
            rt.record_full_refresh()
        assert nested.exists()


# ===========================================================================
# record_partial_refresh
# ===========================================================================

class TestRecordPartialRefresh:
    def test_increments_counter_from_zero(self, state_file):
        """Increments counter from zero."""
        rt.record_partial_refresh()
        data = json.loads(state_file.read_text())
        assert data['partial_refresh_count'] == 1

    def test_increments_existing_counter(self, state_file):
        """Increments existing counter."""
        state_file.write_text(json.dumps({'partial_refresh_count': 3}))
        rt.record_partial_refresh()
        data = json.loads(state_file.read_text())
        assert data['partial_refresh_count'] == 4

    def test_preserves_other_state_keys(self, state_file):
        """Preserves other state keys."""
        state_file.write_text(json.dumps({'last_full_refresh': 500.0, 'partial_refresh_count': 1}))
        rt.record_partial_refresh()
        data = json.loads(state_file.read_text())
        assert data['last_full_refresh'] == 500.0
        assert data['partial_refresh_count'] == 2
