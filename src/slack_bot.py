"""
MLB Display Slack bot — extends the generic SlackBot from hiemenz_utils.

Adds a team dropdown and mode buttons to the standard error-feed panel.
Writes changes directly to config/config.yaml (line-based patch, preserves comments).

@mention the bot in any Slack channel to open the control panel.

Run: python3 src/slack_bot.py
See scripts/slack_bot.service for the Pi systemd unit.
"""

import os
import re
import socket
import sys
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

_CONFIG = _ROOT / "config" / "config.yaml"


def _set_yaml_scalar(key: str, value: str) -> None:
    """Patch a single top-level key: value line in config.yaml, preserving comments."""
    lines = _CONFIG.read_text().splitlines(keepends=True)
    pattern = re.compile(rf'^{re.escape(key)}:\s')
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f'{key}: {value}\n'
            break
    else:
        lines.append(f'{key}: {value}\n')
    _CONFIG.write_text("".join(lines))


def _current_settings() -> tuple[str, str]:
    try:
        config = load_yaml_file(str(_CONFIG))
    except Exception:
        config = {}
    mode = config.get("display_mode") or (
        "scoreboard" if config.get("scoreboard", True) else "linescore"
    )
    team = config.get("primary", "—")
    return mode, team


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

bot = SlackBot("MLB Display")


@bot.add_blocks
def display_controls() -> list:
    mode, team = _current_settings()
    pending = _pending_label()

    host = socket.gethostname()
    status = f"*Host:* `{host}`   *Mode:* `{mode}`   *Team:* `{team}`"
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
    _set_yaml_scalar("primary", selected)
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
            _set_yaml_scalar("display_mode", _m)
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
