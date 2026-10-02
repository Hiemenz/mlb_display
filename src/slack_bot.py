"""
Slack bot for controlling the MLB e-ink display via interactive messages.

Mention @mlb-display in any channel the bot is in to get the control panel.
Select a team from the dropdown or click a mode button — the Pi picks it up
on its next cron tick via data/discord_state.json.

Setup (one-time):
  1. https://api.slack.com/apps → Create New App → From scratch
  2. Socket Mode → Enable → Generate App-level token (xapp-...) → save as SLACK_APP_TOKEN
  3. OAuth & Permissions → Bot Token Scopes: chat:write, app_mentions:read
  4. Event Subscriptions → Enable → Subscribe to bot events: app_mention
  5. Interactivity & Shortcuts → Enable (no URL needed with Socket Mode)
  6. Install to Workspace → copy Bot User OAuth Token (xoxb-...) → save as SLACK_BOT_TOKEN
  7. Invite the bot to a channel: /invite @mlb-display

Run:
  python3 src/slack_bot.py          (development)
  See scripts/slack_bot.service     (systemd for Pi)
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

_SRC = Path(__file__).parent
_ROOT = _SRC.parent
sys.path.insert(0, str(_SRC))

from util import load_yaml_file

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_MODES = (
    'scoreboard', 'linescore', 'scorecard',
    'fields', 'quadrant', 'race', 'bracket',
)

MODE_LABELS = {
    'scoreboard': 'Scoreboard',
    'linescore':  'Linescore',
    'scorecard':  'Scorecard',
    'fields':     'Field',
    'quadrant':   'Quadrant',
    'race':       'Race',
    'bracket':    'Bracket',
}

MLB_TEAMS = [
    # AL East
    ("BAL", "Baltimore Orioles"),
    ("BOS", "Boston Red Sox"),
    ("NYY", "NY Yankees"),
    ("TB",  "Tampa Bay Rays"),
    ("TOR", "Toronto Blue Jays"),
    # AL Central
    ("CWS", "Chicago White Sox"),
    ("CLE", "Cleveland Guardians"),
    ("DET", "Detroit Tigers"),
    ("KC",  "Kansas City Royals"),
    ("MIN", "Minnesota Twins"),
    # AL West
    ("HOU", "Houston Astros"),
    ("LAA", "LA Angels"),
    ("OAK", "Oakland Athletics"),
    ("SEA", "Seattle Mariners"),
    ("TEX", "Texas Rangers"),
    # NL East
    ("ATL", "Atlanta Braves"),
    ("MIA", "Miami Marlins"),
    ("NYM", "NY Mets"),
    ("PHI", "Philadelphia Phillies"),
    ("WSH", "Washington Nationals"),
    # NL Central
    ("CHC", "Chicago Cubs"),
    ("CIN", "Cincinnati Reds"),
    ("MIL", "Milwaukee Brewers"),
    ("PIT", "Pittsburgh Pirates"),
    ("STL", "St. Louis Cardinals"),
    # NL West
    ("ARI", "Arizona Diamondbacks"),
    ("COL", "Colorado Rockies"),
    ("LAD", "LA Dodgers"),
    ("SD",  "San Diego Padres"),
    ("SF",  "San Francisco Giants"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _data_path(filename: str) -> Path:
    return _ROOT / 'data' / filename


def _load_config() -> dict:
    try:
        return load_yaml_file(str(_ROOT / 'config' / 'config.yaml'))
    except Exception:
        return {}


def _current_settings() -> tuple[str, str]:
    config = _load_config()
    mode = config.get('display_mode') or (
        'scoreboard' if config.get('scoreboard', True) else 'linescore'
    )
    team = config.get('primary', '—')
    return mode, team


def _save_state(state: dict) -> None:
    path = _data_path('discord_state.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def _pending_label() -> str:
    """Return a short label if there's an unapplied pending change."""
    try:
        ds = json.loads(_data_path('discord_state.json').read_text())
        if not ds.get('applied', True):
            parts = []
            if ds.get('pending_mode'):
                parts.append(f"mode→{ds['pending_mode']}")
            if ds.get('pending_team'):
                parts.append(f"team→{ds['pending_team']}")
            by = ds.get('requested_by', '?')
            return f"⏳ Pending ({by}): {', '.join(parts)}" if parts else ''
    except (FileNotFoundError, Exception):
        pass
    return ''


# ---------------------------------------------------------------------------
# Block Kit UI
# ---------------------------------------------------------------------------

def _build_blocks(current_mode: str, current_team: str, footer: str = '') -> list:
    pending = _pending_label()

    status_lines = [f"*Mode:* `{current_mode}`   *Team:* `{current_team}`"]
    if pending:
        status_lines.append(pending)
    if footer:
        status_lines.append(footer)

    team_options = [
        {
            "text": {"type": "plain_text", "text": f"{abbr} — {name}"},
            "value": abbr,
        }
        for abbr, name in MLB_TEAMS
    ]

    # Find initial team option for the dropdown
    initial_team = next(
        (o for o in team_options if o["value"] == current_team), None
    )

    team_block = {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*Team*"},
        "accessory": {
            "type": "static_select",
            "action_id": "select_team",
            "placeholder": {"type": "plain_text", "text": "Choose team…"},
            "options": team_options,
            **({"initial_option": initial_team} if initial_team else {}),
        },
    }

    mode_buttons = []
    for mode in VALID_MODES:
        btn = {
            "type": "button",
            "text": {"type": "plain_text", "text": MODE_LABELS.get(mode, mode)},
            "action_id": f"mode_{mode}",
            "value": mode,
        }
        if mode == current_mode:
            btn["style"] = "primary"
        mode_buttons.append(btn)

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "⚾ MLB Display Control"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(status_lines)},
        },
        {"type": "divider"},
        team_block,
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Display Mode*"},
        },
        {
            "type": "actions",
            "elements": mode_buttons,
        },
    ]


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

def _tokens() -> tuple[str, str]:
    bot_token = os.environ.get('SLACK_BOT_TOKEN', '')
    app_token = os.environ.get('SLACK_APP_TOKEN', '')
    if not bot_token or not app_token:
        print("Error: SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set in .env")
        sys.exit(1)
    return bot_token, app_token


def _make_app() -> App:
    bot_token, _ = _tokens()
    return App(token=bot_token)


app = _make_app()


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@app.event("app_mention")
def handle_mention(event, say):
    """Show the control panel when the bot is @mentioned."""
    mode, team = _current_settings()
    say(
        blocks=_build_blocks(mode, team),
        text="MLB Display Control",
    )


@app.action("select_team")
def handle_team(ack, body, client):
    """User picked a team from the dropdown."""
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
    mode, _ = _current_settings()
    footer = f"✓ Team set to *{selected}* — applies on next refresh"
    client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        blocks=_build_blocks(mode, selected, footer=footer),
        text="MLB Display Control",
    )


for _mode in VALID_MODES:
    def _make_mode_handler(m):
        @app.action(f"mode_{m}")
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
            _, team = _current_settings()
            footer = f"✓ Mode set to *{MODE_LABELS.get(_m, _m)}* — applies on next refresh"
            client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                blocks=_build_blocks(_m, team, footer=footer),
                text="MLB Display Control",
            )
    _make_mode_handler(_mode)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    os.chdir(_ROOT)
    # Reload tokens now (in case .env was loaded after module import)
    bot_token, app_token = _tokens()
    print("MLB Display Slack bot starting…")
    handler = SocketModeHandler(app, app_token)
    handler.start()


if __name__ == "__main__":
    main()
