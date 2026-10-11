"""Tests for src/slack_settings.py — Slack-editable config schema, modal, and YAML patcher."""
import os

import pytest
import yaml

import config_loader
import slack_settings as ss

REAL_CONFIG = config_loader._DEFAULT_CONFIG

SAMPLE = """\
# header comment
display_mode: "scoreboard"
primary: NYY
morning_end: 9          # weekday cutoff
use_team_logos: True
trade_deadline: "2026-08-03 18:00"  # ET

sport_id_priority:
  - 1   # MLB
  - 8

weather:
  enabled: true
  cache_ttl_minutes: 60

replay_date: ""
"""


def _values(**by_key):
    """Build a view-state `values` dict from {key: raw} using each setting's element type."""
    out = {}
    for key, raw in by_key.items():
        spec = next(s for s in ss.SETTINGS if s.key == key)
        if spec.kind == "bool":
            el = {"type": "checkboxes", "selected_options": [{"value": "on"}] if raw else []}
        elif spec.kind in ("select", "team"):
            el = {"type": "static_select", "selected_option": {"value": raw} if raw else None}
        else:
            el = {"type": "plain_text_input", "value": raw}
        out[f"cfg_{key}"] = {"val": el}
    return out


# --- schema -----------------------------------------------------------------

def test_every_real_config_key_is_covered():
    """Adding a key to config.yaml without a Slack setting should fail here."""
    with open(REAL_CONFIG) as f:
        config = yaml.safe_load(f)
    covered = {s.key.split(".")[0] for s in ss.SETTINGS}
    assert set(config) - covered == set()


def test_every_setting_key_exists_in_real_config():
    with open(REAL_CONFIG) as f:
        config = yaml.safe_load(f)
    missing = [s.key for s in ss.SETTINGS if ss.get_value(config, s.key) is None]
    assert missing == []


def test_every_group_fits_a_modal_and_has_valid_blocks():
    with open(REAL_CONFIG) as f:
        config = yaml.safe_load(f)
    for group in ss.GROUPS:
        view = ss.settings_modal(group, config)
        assert len(view["blocks"]) <= 100
        ids = [b["block_id"] for b in view["blocks"] if b["type"] == "input"]
        assert len(ids) == len(set(ids)) == len(ss.settings_for(group))


# --- blocks -----------------------------------------------------------------

def test_modal_initial_values_reflect_config():
    config = {"primary": "BOS", "use_team_logos": True, "night_mode": False, "update_interval": 14,
              "display_mode": "quadrant", "sport_id_priority": [1, 8]}
    blocks = {b["block_id"]: b for b in ss.settings_modal(ss.G_DISPLAY, config)["blocks"] if b["type"] == "input"}
    assert blocks["cfg_primary"]["element"]["initial_option"]["value"] == "BOS"
    assert blocks["cfg_display_mode"]["element"]["initial_option"]["value"] == "quadrant"
    assert "initial_options" in blocks["cfg_use_team_logos"]["element"]
    assert blocks["cfg_sport_id_priority"]["element"]["initial_value"] == "1, 8"
    timing = {b["block_id"]: b for b in ss.settings_modal(ss.G_TIMING, config)["blocks"] if b["type"] == "input"}
    assert "initial_options" not in timing["cfg_night_mode"]["element"]
    assert timing["cfg_update_interval"]["element"]["initial_value"] == "14"


def test_unknown_team_and_blank_values_omit_initial():
    blocks = {b["block_id"]: b for b in ss.settings_modal(ss.G_DISPLAY, {"primary": "LIVE"})["blocks"]
              if b["type"] == "input"}
    assert "initial_option" not in blocks["cfg_primary"]["element"]
    assert "initial_value" not in blocks["cfg_secondary"]["element"]
    assert blocks["cfg_secondary"]["optional"] is False


def test_display_mode_falls_back_to_legacy_scoreboard_flag():
    assert "linescore" in ss.summary({"scoreboard": False})
    assert "scoreboard" in ss.summary({})


def test_env_override_warning_shown():
    view = ss.settings_modal(ss.G_DISPLAY, {}, {"DISPLAY_MODE": "race"})
    assert any("DISPLAY_MODE" in str(b) for b in view["blocks"] if b["type"] == "context")
    assert ss.env_warnings(ss.G_PANELS, {"DISPLAY_MODE": "race"}) == []


def test_control_panel_has_settings_button():
    blocks = ss.control_panel_blocks({"primary": "NYY"}, "pi")
    assert blocks[1]["elements"][0]["action_id"] == "open_settings"
    assert "NYY" in blocks[0]["text"]["text"]


# --- parsing / validation ---------------------------------------------------

def test_parse_returns_only_changed_values():
    config = {"primary": "NYY", "night_mode": True, "morning_end": 9}
    changes, errors = ss.parse_submission(ss.G_TIMING, _values(night_mode=False, morning_end="9"), config)
    assert changes == {"night_mode": False}
    assert errors == {}


@pytest.mark.parametrize("key,raw", [
    ("morning_end", "abc"), ("morning_end", "30"), ("morning_end", "-1"),
    ("replay_date", "2026-13-40"), ("replay_date", "nope"),
    ("trade_deadline", "tomorrow"), ("timezone", "Mars/Base"),
    ("secondary", "bad value!"), ("sport_id_priority", "1, x"), ("sport_id_priority", " , "),
    ("primary", ""), ("league_mode", "nhl"),
])
def test_invalid_values_are_rejected(key, raw):
    group = next(s.group for s in ss.SETTINGS if s.key == key)
    changes, errors = ss.parse_submission(group, _values(**{key: raw}), {})
    assert f"cfg_{key}" in errors and changes == {}


@pytest.mark.parametrize("key,raw,expected", [
    ("replay_date", "", ""), ("replay_date", "2026-09-01", "2026-09-01"),
    ("trade_deadline", "2026-08-03 18:00", "2026-08-03 18:00"),
    ("timezone", "America/New_York", "America/New_York"),
    ("sport_id_priority", "1, 8,11", [1, 8, 11]),
    ("secondary", "NYY_DOUBLE", "NYY_DOUBLE"),
    ("primary", "BOS", "BOS"),
])
def test_valid_values_are_coerced(key, raw, expected):
    group = next(s.group for s in ss.SETTINGS if s.key == key)
    changes, errors = ss.parse_submission(group, _values(**{key: raw}), {"replay_date": "x"})
    assert errors == {} and changes == {key: expected}


def test_missing_block_in_submission_is_skipped():
    assert ss.parse_submission(ss.G_TIMING, {}, {}) == ({}, {})


# --- YAML patching ----------------------------------------------------------

def test_set_scalar_keeps_comments_and_trailing_comment():
    out = ss.set_yaml_value(SAMPLE, "morning_end", 10)
    assert "morning_end: 10          # weekday cutoff" in out
    assert out.startswith("# header comment")
    assert ss.set_yaml_value(SAMPLE, "trade_deadline", "2026-09-01 12:00").count("# ET") == 1


def test_set_scalar_types():
    out = ss.set_yaml_value(SAMPLE, "use_team_logos", False)
    assert "use_team_logos: false" in out
    out = ss.set_yaml_value(SAMPLE, "primary", 'B"OS')
    assert yaml.safe_load(out)["primary"] == 'B"OS'


def test_set_missing_key_appends():
    out = ss.set_yaml_value("a: 1", "b", 2)
    assert yaml.safe_load(out) == {"a": 1, "b": 2}


def test_set_nested_existing_and_missing():
    out = ss.set_yaml_value(SAMPLE, "weather.cache_ttl_minutes", 5)
    assert yaml.safe_load(out)["weather"] == {"enabled": True, "cache_ttl_minutes": 5}
    out = ss.set_yaml_value(SAMPLE, "weather.extra", True)
    assert yaml.safe_load(out)["weather"]["extra"] is True
    assert yaml.safe_load(out)["replay_date"] == ""
    fresh = ss.set_yaml_value("a: 1\n", "weather.enabled", False)
    assert yaml.safe_load(fresh) == {"a": 1, "weather": {"enabled": False}}


def test_set_list_replaces_items():
    out = ss.set_yaml_value(SAMPLE, "sport_id_priority", [11, 1, 16])
    loaded = yaml.safe_load(out)
    assert loaded["sport_id_priority"] == [11, 1, 16]
    assert loaded["weather"]["enabled"] is True
    assert yaml.safe_load(ss.set_yaml_value("a: 1", "sport_id_priority", [1]))["sport_id_priority"] == [1]


def test_apply_changes_writes_atomically(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE)
    ss.apply_changes(str(path), {"primary": "LAD", "weather.enabled": False})
    loaded = yaml.safe_load(path.read_text())
    assert loaded["primary"] == "LAD" and loaded["weather"]["enabled"] is False
    assert [p.name for p in tmp_path.iterdir()] == ["config.yaml"]


def test_apply_changes_refuses_non_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE)
    monkeypatch.setattr(ss, "set_yaml_value", lambda text, key, value: text)
    with pytest.raises(ValueError):
        ss.apply_changes(str(path), {"primary": "LAD"})
    assert yaml.safe_load(path.read_text())["primary"] == "NYY"


def test_apply_changes_cleans_tmp_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE)

    def boom(src, dst):
        raise OSError("disk")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        ss.apply_changes(str(path), {"primary": "LAD"})
    assert [p.name for p in tmp_path.iterdir()] == ["config.yaml"]


def test_real_config_roundtrips_every_setting(tmp_path):
    """Patching each setting to its current value must leave a parseable, equal config."""
    path = tmp_path / "config.yaml"
    path.write_text(open(REAL_CONFIG).read())
    before = yaml.safe_load(path.read_text())
    changes = {}
    for spec in ss.SETTINGS:
        value = ss.get_value(before, spec.key)
        if value is not None:
            changes[spec.key] = value
    ss.apply_changes(str(path), changes)
    after = yaml.safe_load(path.read_text())
    for key in changes:
        assert ss.get_value(after, key) == ss.get_value(before, key)


# --- save_submission --------------------------------------------------------

def test_save_submission_writes_and_describes(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE)
    changes, errors = ss.save_submission(ss.G_DISPLAY, _values(primary="BOS", use_team_logos=False), str(path))
    assert errors == {}
    assert yaml.safe_load(path.read_text())["primary"] == "BOS"
    text = ss.describe_changes({**changes, "sport_id_priority": [1, 8]})
    assert "Primary team" in text and "`BOS`" in text and "`1, 8`" in text


def test_save_submission_writes_nothing_on_error(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE)
    changes, errors = ss.save_submission(
        ss.G_DISPLAY, _values(primary="BOS", timezone="Mars/Base"), str(path))
    assert "cfg_timezone" in errors
    assert yaml.safe_load(path.read_text())["primary"] == "NYY"


def test_get_value_handles_non_dict_parent():
    assert ss.get_value({"weather": True}, "weather.enabled") is None
