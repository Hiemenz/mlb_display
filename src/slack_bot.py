"""
MLB Display Slack bot — extends the generic SlackBot from hiemenz_utils.

Adds a team dropdown and mode buttons to the standard error-feed panel.
Writes pending changes to data/discord_state.json (same as the Discord bot).

@mention the bot in any Slack channel to open the control panel.

Run: python3 src/slack_bot.py
See scripts/slack_bot.service for the Pi systemd unit.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

_SRC = Path(__file__).parent
_ROOT = _SRC.parent
sys.path.insert(0, str(_SRC))

from hiemenz_utils.env import load_dotenv
from hiemenz_utils.slack_bot import SlackBot
from util import load_yaml_file

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_MODES = (
    "scoreboard", "linescore", "scorecard",
    "fields", "quadrant", "race", "bracket",
)

MODE_LABELS = {
    "scoreboard": "Scoreboard",
    "linescore":  "Linescore",
    "scorecard":  "Scorecard",
    "fields":     "Field",
    "quadrant":   "Quadrant",
    "race":       "Race",
    "bracket":    "Bracket",
}

MLB_TEAMS = [
    # AL East
    ("BAL", "Baltimore Orioles"),  ("BOS", "Boston Red Sox"),
    ("NYY", "NY Yankees"),         ("TB",  "Tampa Bay Rays"),
    ("TOR", "Toronto Blue Jays"),
    # AL Central
    ("CWS", "Chicago White Sox"),  ("CLE", "Cleveland Guardians"),
    ("DET", "Detroit Tigers"),     ("KC",  "Kansas City Royals"),
    ("MIN", "Minnesota Twins"),
    # AL West
    ("HOU", "Houston Astros"),     ("LAA", "LA Angels"),
    ("OAK", "Oakland Athletics"),  ("SEA", "Seattle Mariners"),
    ("TEX", "Texas Rangers"),
    # NL East
    ("ATL", "Atlanta Braves"),     ("MIA", "Miami Marlins"),
    ("NYM", "NY Mets"),            ("PHI", "Philadelphia Phillies"),
    ("WSH", "Washington Nationals"),
    # NL Central
    ("CHC", "Chicago Cubs"),       ("CIN", "Cincinnati Reds"),
    ("MIL", "Milwaukee Brewers"),  ("PIT", "Pittsburgh Pirates"),
    ("STL", "St. Louis Cardinals"),
    # NL West
    ("ARI", "Arizona Diamondbacks"), ("COL", "Colorado Rockies"),
    ("LAD", "LA Dodgers"),           ("SD",  "San Diego Padres"),
    ("SF",  "San Francisco Giants"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _data_path(filename: str) -> Path:
    return _ROOT / "data" / filename


def _current_settings() -> tuple[str, str]:
    try:
        config = load_yaml_file(str(_ROOT / "config" / "config.yaml"))
    except Exception:
        config = {}
    mode = config.get("display_mode") or (
        "scoreboard" if config.get("scoreboard", True) else "linescore"
    )
    team = config.get("primary", "—")
    return mode, team


def _pending_label() -> str:
    try:
        ds = json.loads(_data_path("discord_state.json").read_text())
        if not ds.get("applied", True):
            parts = []
            if ds.get("pending_mode"):
                parts.append(f"mode→{ds['pending_mode']}")
            if ds.get("pending_team"):
                parts.append(f"team→{ds['pending_team']}")
            by = ds.get("requested_by", "?")
            return f"⏳ Pending ({by}): {', '.join(parts)}" if parts else ""
    except (FileNotFoundError, Exception):
        pass
    return ""


def _save_state(state: dict) -> None:
    path = _data_path("discord_state.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

bot = SlackBot("MLB Display")


@bot.add_blocks
def display_controls() -> list:
    mode, team = _current_settings()
    pending = _pending_label()

    status = f"*Mode:* `{mode}`   *Team:* `{team}`"
    if pending:
        status += f"\n{pending}"

    team_options = [
        {"text": {"type": "plain_text", "text": f"{abbr} — {name}"}, "value": abbr}
        for abbr, name in MLB_TEAMS
    ]
    initial = next((o for o in team_options if o["value"] == team), None)

    mode_buttons = []
    for m in VALID_MODES:
        btn = {
            "type": "button",
            "text": {"type": "plain_text", "text": MODE_LABELS.get(m, m)},
            "action_id": f"mode_{m}",
            "value": m,
        }
        if m == mode:
            btn["style"] = "primary"
        mode_buttons.append(btn)

    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": status},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Team*"},
            "accessory": {
                "type": "static_select",
                "action_id": "select_team",
                "placeholder": {"type": "plain_text", "text": "Choose team…"},
                "options": team_options,
                **({"initial_option": initial} if initial else {}),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Display Mode*"},
        },
        {
            "type": "actions",
            "elements": mode_buttons,
        },
    ]


@bot.action("select_team")
def handle_team(ack, body, client):
    ack()
    selected = body["actions"][0]["selected_option"]["value"]
    user = body["user"]["username"]
    _save_state({
        "pending_mode": None,
        "pending_team": selected,
        "requested_by": user,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "applied": False,
    })
    bot.update_message(
        client,
        body["channel"]["id"],
        body["message"]["ts"],
        footer=f"✓ Team set to *{selected}* — applies on next refresh",
    )


for _m in VALID_MODES:
    def _make_mode_handler(m):
        @bot.action(f"mode_{m}")
        def handler(ack, body, client, _m=m):
            ack()
            user = body["user"]["username"]
            _save_state({
                "pending_mode": _m,
                "pending_team": None,
                "requested_by": user,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "applied": False,
            })
            bot.update_message(
                client,
                body["channel"]["id"],
                body["message"]["ts"],
                footer=f"✓ Mode set to *{MODE_LABELS.get(_m, _m)}* — applies on next refresh",
            )
    _make_mode_handler(_m)


if __name__ == "__main__":
    os.chdir(_ROOT)
    bot.start()
