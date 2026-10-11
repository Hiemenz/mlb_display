"""Every config/config.yaml option as an editable Slack setting.

Pure logic with no slack_bolt dependency (so it's unit-tested): the schema
(SETTINGS), Block Kit modal builders, form-submission parsing/validation, and a
comment-preserving YAML patcher. src/slack_bot.py wires these to Slack events.

config.yaml is heavily hand-commented, so writes go through set_yaml_value()
(a line-based patch of just the value) rather than a yaml.safe_dump() round-trip.
"""
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import yaml

from render_scoreboard import _VALID_MODES

MLB_TEAMS = [
    ("BAL", "Baltimore Orioles"), ("BOS", "Boston Red Sox"), ("NYY", "NY Yankees"),
    ("TB", "Tampa Bay Rays"), ("TOR", "Toronto Blue Jays"),
    ("CWS", "Chicago White Sox"), ("CLE", "Cleveland Guardians"), ("DET", "Detroit Tigers"),
    ("KC", "Kansas City Royals"), ("MIN", "Minnesota Twins"),
    ("HOU", "Houston Astros"), ("LAA", "LA Angels"), ("OAK", "Oakland Athletics"),
    ("SEA", "Seattle Mariners"), ("TEX", "Texas Rangers"),
    ("ATL", "Atlanta Braves"), ("MIA", "Miami Marlins"), ("NYM", "NY Mets"),
    ("PHI", "Philadelphia Phillies"), ("WSH", "Washington Nationals"),
    ("CHC", "Chicago Cubs"), ("CIN", "Cincinnati Reds"), ("MIL", "Milwaukee Brewers"),
    ("PIT", "Pittsburgh Pirates"), ("STL", "St. Louis Cardinals"),
    ("ARI", "Arizona Diamondbacks"), ("COL", "Colorado Rockies"), ("LAD", "LA Dodgers"),
    ("SD", "San Diego Padres"), ("SF", "San Francisco Giants"),
]

# .env vars that override a yaml key, silently masking a Slack change.
ENV_OVERRIDES = {
    "display_mode": "DISPLAY_MODE",
    "league_mode": "LEAGUE_MODE",
    "hide_non_live_games": "HIDE_NON_LIVE_GAMES",
}


@dataclass(frozen=True)
class Setting:
    key: str            # config.yaml key; "parent.child" for one-level nesting
    label: str
    kind: str           # bool | select | team | int | text | date | datetime | timezone | int_list
    group: str
    options: tuple = ()
    help: str = ""
    lo: int | None = None
    hi: int | None = None
    blank_ok: bool = False


def _b(key, label, group, help=""):
    return Setting(key, label, "bool", group, help=help)


def _i(key, label, group, lo=0, hi=None, help=""):
    return Setting(key, label, "int", group, lo=lo, hi=hi, help=help)


G_DISPLAY = "Display & Teams"
G_TIMING = "Refresh & Timing"
G_LAYOUT = "Scoreboard Layout"
G_PANELS = "Panels"
G_IDLE = "Idle & Quadrant"
G_REPLAY = "Replay & Video"
G_SYSTEM = "System"

GROUPS = (G_DISPLAY, G_TIMING, G_LAYOUT, G_PANELS, G_IDLE, G_REPLAY, G_SYSTEM)

SETTINGS = (
    # --- Display & Teams
    Setting("display_mode", "Display mode", "select", G_DISPLAY, options=_VALID_MODES,
            help="Overrides the old scoreboard true/false flag."),
    _b("scoreboard", "Scoreboard grid", G_DISPLAY,
       "Legacy flag: on = 15-game grid, off = 2 linescores + standings. Ignored when display mode is set."),
    Setting("primary", "Primary team", "team", G_DISPLAY),
    Setting("primary_backup", "Primary backup", "team", G_DISPLAY),
    Setting("primary_backup_2", "Primary backup 2", "team", G_DISPLAY),
    Setting("secondary", "Secondary", "text", G_DISPLAY, help="Team abbr or NYY_DOUBLE / LIVE."),
    Setting("secondary_backup", "Secondary backup", "text", G_DISPLAY),
    Setting("secondary_backup_2", "Secondary backup 2", "text", G_DISPLAY),
    _b("favorite_team_first", "Favorite team first", G_DISPLAY, "Pin the primary team's game top-left."),
    Setting("league_mode", "League mode", "select", G_DISPLAY, options=("mlb", "aaa")),
    Setting("sport_id_priority", "Sport ID priority", "int_list", G_DISPLAY,
            help="Comma-separated, first with games wins: 1 MLB, 8 WBC, 11 AAA, 12 AA, 13 High-A, 14 A, 16 Spring, 51 Intl."),
    Setting("timezone", "Timezone", "timezone", G_DISPLAY, help="IANA name, e.g. America/Chicago."),
    _b("use_team_logos", "Team logos", G_DISPLAY),
    # --- Refresh & Timing
    _i("update_interval", "Update interval (min)", G_TIMING, 1, 1440),
    _i("live_game_interval", "Live game interval (sec)", G_TIMING, 0, 3600),
    _i("max_live_game_calls", "Max live game calls", G_TIMING, 0, 100),
    _b("night_mode", "Night mode", G_TIMING, "Skip refreshes between night start and end."),
    _i("night_start", "Night start (hour)", G_TIMING, 0, 23),
    _i("night_end", "Night end (hour)", G_TIMING, 0, 23),
    _b("morning_alternate_games", "Morning alternate games", G_TIMING),
    _i("morning_end", "Morning end, weekday (hour)", G_TIMING, 0, 23),
    _i("morning_end_weekend", "Morning end, weekend (hour)", G_TIMING, 0, 23),
    _b("morning_alternate_quadrant", "Morning: include quadrant", G_TIMING),
    _i("dark_start", "Dark mode start (hour)", G_TIMING, 0, 23),
    _i("dark_end", "Dark mode end (hour)", G_TIMING, 0, 23),
    # --- Scoreboard Layout
    _b("show_standings_sidebar", "Standings sidebar", G_LAYOUT),
    _b("show_wildcard_standings", "Wildcard standings strip", G_LAYOUT),
    _b("show_playoff_bracket", "Playoff bracket header", G_LAYOUT),
    _b("sidebar_magic_badges", "Magic badges on sidebar", G_LAYOUT),
    _i("overflow_ticker_rotation_minutes", "Overflow ticker rotation (min)", G_LAYOUT, 1, 120),
    _i("small_logo_x_offset", "Small logo X offset (px)", G_LAYOUT, 0, 100),
    _i("final_linescore_minutes", "Final linescore minutes", G_LAYOUT, 0, 9999),
    _b("scoreboard_win_probability", "Win probability bar", G_LAYOUT),
    _b("scoreboard_live_details", "Live details in boxes", G_LAYOUT),
    _b("wide_cell_always", "Always show wide cell", G_LAYOUT),
    _b("wide_cell_featured", "Wide cell for featured team", G_LAYOUT),
    _b("triple_cell_live", "Triple-cell live game", G_LAYOUT),
    _b("hide_non_live_games", "Hide non-live games", G_LAYOUT),
    _b("show_debug_overlay", "Debug overlay", G_LAYOUT),
    # --- Panels
    _b("show_leaders_panel", "Season leaders panel", G_PANELS),
    _i("leaders_rotation_minutes", "Leaders rotation (min)", G_PANELS, 1, 120),
    _b("show_series_panel", "Series leaders / playoff series tiles", G_PANELS),
    _b("show_transactions_ticker", "Transactions ticker", G_PANELS),
    _i("transactions_lookback_days", "Transactions lookback (days)", G_PANELS, 1, 30),
    _b("show_lineup_panel", "Batting lineup panel", G_PANELS),
    _b("lineup_logo_background", "Lineup logo watermark", G_PANELS),
    _b("show_deadline_panel", "Trade deadline countdown", G_PANELS),
    Setting("trade_deadline", "Trade deadline", "datetime", G_PANELS, help="Local ET, YYYY-MM-DD HH:MM."),
    _b("show_news_panel", "News headlines panel", G_PANELS),
    _b("news_team_only", "News: primary team only", G_PANELS),
    _b("show_magic_numbers", "Magic / elimination numbers", G_PANELS),
    _b("show_streaks_panel", "Hot hitters panel", G_PANELS),
    _b("show_scoreless_panel", "Hot arms panel", G_PANELS),
    _b("show_bullpen_panel", "Bullpen usage tiles", G_PANELS),
    _i("bullpen_lookback_days", "Bullpen lookback (days)", G_PANELS, 1, 14),
    # --- Idle & Quadrant
    Setting("quadrant_grain", "Quadrant window", "select", G_IDLE,
            options=("season", "month", "week", "rotate")),
    _i("quadrant_rotate_minutes", "Quadrant rotate (min)", G_IDLE, 1, 240),
    _b("auto_derby_mode", "Auto Home Run Derby mode", G_IDLE),
    _b("idle_schedule_rotation", "Idle: next-games block", G_IDLE),
    # --- Replay & Video
    Setting("replay_date", "Replay date", "date", G_REPLAY, blank_ok=True,
            help="YYYY-MM-DD; blank when not replaying."),
    _i("replay_step_minutes", "Replay step (baseball min)", G_REPLAY, 1, 60),
    _i("replay_delay_seconds", "Replay delay (sec)", G_REPLAY, 1, 600),
    _b("offseason_replay", "Off-season replay", G_REPLAY),
    _i("offseason_replays_per_day", "Off-season replays per day", G_REPLAY, 1, 20),
    _i("offseason_replay_step_minutes", "Off-season step (min)", G_REPLAY, 1, 60),
    _i("offseason_replay_delay_seconds", "Off-season delay (sec)", G_REPLAY, 1, 600),
    _b("auto_generate_video", "Auto-generate daily video", G_REPLAY),
    _i("video_interval_min", "Video interval (min)", G_REPLAY, 1, 60),
    _i("video_frame_delay_ms", "Video frame delay (ms)", G_REPLAY, 10, 5000),
    # --- System
    _b("weather.enabled", "Pre-game weather footer", G_SYSTEM),
    _i("weather.cache_ttl_minutes", "Weather cache TTL (min)", G_SYSTEM, 1, 1440),
    _i("config_server_port", "Config web server port", G_SYSTEM, 1, 65535,
       help="Takes effect when the config server restarts."),
)

_BY_GROUP = {g: tuple(s for s in SETTINGS if s.group == g) for g in GROUPS}


def settings_for(group):
    return _BY_GROUP[group]


# ---------------------------------------------------------------------------
# Reading current values
# ---------------------------------------------------------------------------

def get_value(config, key):
    node = config
    for part in key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _display_value(spec, config):
    """Current value normalised to what a form control for `spec` would submit."""
    value = get_value(config, spec.key)
    if spec.key == "display_mode" and not value:
        return "scoreboard" if config.get("scoreboard", True) else "linescore"
    if spec.kind == "bool":
        return bool(value)
    if spec.kind == "int_list":
        return [int(v) for v in value] if isinstance(value, list) else []
    if value is None:
        return ""
    return value if spec.kind == "int" else str(value)


def summary(config):
    """One-line status for the control panel."""
    mode = _display_value(next(s for s in SETTINGS if s.key == "display_mode"), config)
    return f"*Mode:* `{mode}`   *Team:* `{config.get('primary', '—')}`"


def env_warnings(group, env):
    """Notes for settings in `group` that a non-empty .env override would mask."""
    return [
        f"`{var}` in .env overrides *{spec.label}* — clear it for this change to take effect."
        for spec in settings_for(group)
        if (var := ENV_OVERRIDES.get(spec.key)) and env.get(var)
    ]


# ---------------------------------------------------------------------------
# Block Kit
# ---------------------------------------------------------------------------

def _plain(text):
    return {"type": "plain_text", "text": text}


def _block_id(spec):
    return f"cfg_{spec.key}"


def _option(value, text=None):
    return {"text": _plain(text or str(value)), "value": str(value)}


def _input_block(spec, config):
    value = _display_value(spec, config)
    if spec.kind == "bool":
        option = _option("on", "Enabled")
        element = {"type": "checkboxes", "action_id": "val", "options": [option]}
        if value:
            element["initial_options"] = [option]
        optional = True
    elif spec.kind in ("select", "team"):
        if spec.kind == "team":
            options = [_option(abbr, f"{abbr} — {name}") for abbr, name in MLB_TEAMS]
        else:
            options = [_option(o) for o in spec.options]
        element = {"type": "static_select", "action_id": "val", "options": options}
        initial = next((o for o in options if o["value"] == value), None)
        if initial:
            element["initial_option"] = initial
        optional = False
    else:
        element = {"type": "plain_text_input", "action_id": "val"}
        text = ", ".join(map(str, value)) if spec.kind == "int_list" else str(value)
        if text:
            element["initial_value"] = text
        optional = spec.blank_ok
    block = {
        "type": "input",
        "block_id": _block_id(spec),
        "optional": optional,
        "label": _plain(spec.label),
        "element": element,
    }
    if spec.help:
        block["hint"] = _plain(spec.help)
    return block


def settings_modal(group, config, env=None):
    """Modal view for one settings category (config options as inputs)."""
    blocks = [{
        "type": "actions",
        "block_id": "group_picker",
        "elements": [{
            "type": "static_select",
            "action_id": "select_group",
            "options": [_option(g) for g in GROUPS],
            "initial_option": _option(group),
        }],
    }, {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "Submit to save. Switching category discards unsaved edits."}],
    }]
    for warning in env_warnings(group, env or {}):
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f":warning: {warning}"}]})
    blocks.extend(_input_block(spec, config) for spec in settings_for(group))
    return {
        "type": "modal",
        "callback_id": "settings_modal",
        "private_metadata": group,
        "title": _plain("Display Settings"),
        "submit": _plain("Save"),
        "close": _plain("Cancel"),
        "blocks": blocks,
    }


def control_panel_blocks(config, host):
    """Message shown on @mention: status line plus a button that opens the modal."""
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*MLB Display* on `{host}`\n{summary(config)}"}},
        {"type": "actions", "elements": [{
            "type": "button", "style": "primary", "action_id": "open_settings",
            "text": _plain("Settings"),
        }]},
    ]


# ---------------------------------------------------------------------------
# Submission parsing / validation
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _raw(element):
    """Pull the submitted value out of a view-state element."""
    kind = element.get("type")
    if kind == "checkboxes":
        return bool(element.get("selected_options"))
    if kind == "static_select":
        option = element.get("selected_option")
        return option["value"] if option else ""
    return (element.get("value") or "").strip()


def _coerce(spec, raw):
    """Validate/convert one submitted value. Returns the typed value; raises ValueError."""
    if spec.kind == "bool":
        return raw
    if spec.kind in ("select", "team"):
        valid = spec.options or tuple(a for a, _ in MLB_TEAMS)
        if raw not in valid:
            raise ValueError("Pick one of the listed values.")
        return raw
    if spec.kind == "int":
        try:
            number = int(raw)
        except ValueError:
            raise ValueError("Enter a whole number.") from None
        if (spec.lo is not None and number < spec.lo) or (spec.hi is not None and number > spec.hi):
            raise ValueError(f"Must be between {spec.lo} and {spec.hi}.")
        return number
    if spec.kind == "int_list":
        try:
            numbers = [int(p) for p in raw.split(",") if p.strip()]
        except ValueError:
            raise ValueError("Enter comma-separated whole numbers.") from None
        if not numbers:
            raise ValueError("Enter at least one number.")
        return numbers
    if raw == "" and spec.blank_ok:
        return ""
    if spec.kind == "date":
        if not _DATE_RE.match(raw):
            raise ValueError("Use YYYY-MM-DD.")
        datetime.strptime(raw, "%Y-%m-%d")
    elif spec.kind == "datetime":
        datetime.strptime(raw, "%Y-%m-%d %H:%M")
    elif spec.kind == "timezone":
        try:
            ZoneInfo(raw)
        except Exception:
            raise ValueError("Unknown timezone.") from None
    elif not re.fullmatch(r"[A-Za-z0-9_]+", raw):
        raise ValueError("Letters, digits and underscores only.")
    return raw


def parse_submission(group, state_values, config):
    """Validate a modal submission for `group`.

    Returns (changes, errors): changes maps key -> new typed value for settings
    that differ from `config`; errors maps block_id -> message (Slack's
    response_action=errors shape).
    """
    changes, errors = {}, {}
    for spec in settings_for(group):
        block = state_values.get(_block_id(spec), {}).get("val")
        if block is None:
            continue
        try:
            value = _coerce(spec, _raw(block))
        except ValueError as exc:
            errors[_block_id(spec)] = str(exc) or "Invalid value."
            continue
        if value != _display_value(spec, config):
            changes[spec.key] = value
    return changes, errors


# ---------------------------------------------------------------------------
# YAML patching
# ---------------------------------------------------------------------------

def _fmt_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _trailing_comment(line):
    """The `  # comment` suffix of a `key: value  # comment` line ('' if none)."""
    rest = line.split(":", 1)[1].rstrip("\n").lstrip()
    if rest[:1] in ("'", '"'):
        close = rest.find(rest[0], 1)
        rest = rest[close + 1:] if close != -1 else ""
    m = re.search(r"\s+#.*$", " " + rest)
    return m.group(0).rstrip() if m else ""


def _scalar_line(indent, key, value, old_line=None):
    """Build `key: value`, keeping any trailing `# comment` from old_line."""
    comment = _trailing_comment(old_line) if old_line else ""
    return f"{indent}{key}: {_fmt_scalar(value)}{comment}\n"


def _list_lines(indent, key, values):
    return [f"{indent}{key}:\n"] + [f"{indent}  - {v}\n" for v in values]


def set_yaml_value(text, key, value):
    """Return `text` with `key` (optionally "parent.child") set to `value`, comments intact."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    parent, _, child = key.rpartition(".")
    indent = "  " if parent else ""
    start, end = (0, len(lines))
    if parent:
        pi = next((i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(parent)}:\s*(#.*)?$", ln)), None)
        if pi is None:
            lines.append(f"{parent}:\n")
            pi = len(lines) - 1
        start = pi + 1
        end = next((i for i in range(start, len(lines)) if lines[i].strip() and not lines[i].startswith((" ", "#"))),
                   len(lines))
        while end > start and not lines[end - 1].strip():
            end -= 1
    pattern = re.compile(rf"^{indent}{re.escape(child)}:(\s|$)")
    idx = next((i for i in range(start, end) if pattern.match(lines[i])), None)

    if isinstance(value, list):
        new = _list_lines(indent, child, value)
        if idx is None:
            lines[end:end] = new
        else:
            stop = idx + 1
            while stop < len(lines) and re.match(rf"^{indent}\s*-\s", lines[stop]):
                stop += 1
            lines[idx:stop] = new
    elif idx is None:
        lines.insert(end, _scalar_line(indent, child, value))
    else:
        lines[idx] = _scalar_line(indent, child, value, lines[idx])
    return "".join(lines)


def apply_changes(path, changes):
    """Patch `changes` into the YAML file at `path` atomically; verify it still parses."""
    with open(path) as f:
        text = f.read()
    for key, value in changes.items():
        text = set_yaml_value(text, key, value)
    loaded = yaml.safe_load(text) or {}
    for key, value in changes.items():
        if get_value(loaded, key) != value:
            raise ValueError(f"Refusing to write: {key} did not round-trip.")
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save_submission(group, state_values, config_path):
    """Validate a modal submission and write its changes. Returns (changes, errors);
    nothing is written when there are errors."""
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    changes, errors = parse_submission(group, state_values, config)
    if changes and not errors:
        apply_changes(config_path, changes)
    return changes, errors


def describe_changes(changes):
    """Slack mrkdwn bullet list of what was saved."""
    labels = {s.key: s.label for s in SETTINGS}
    return "\n".join(
        f"• *{labels[key]}* → `{', '.join(map(str, v)) if isinstance(v, list) else v}`"
        for key, v in changes.items()
    )
