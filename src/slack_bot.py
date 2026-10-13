"""MLB Display Slack bot — change any config/config.yaml option from Slack.

@mention the bot in a channel to get a control panel; its Settings button opens a
modal with a category dropdown (Display & Teams, Panels, Replay & Video, ...) and
one control per config option. Saving patches config/config.yaml in place
(comments preserved); the display picks changes up on its next refresh.

Uses Socket Mode, so it works behind a home router with no port forwarding.

Run: uv run python src/slack_bot.py
See scripts/slack_bot.service for the Pi systemd unit.
"""
import os
import socket
import sys
from pathlib import Path

_SRC = Path(__file__).parent
sys.path.insert(0, str(_SRC))

import config_loader  # noqa: E402  (loads .env into os.environ)
import slack_settings as settings  # noqa: E402
from slack_bolt import App  # noqa: E402
from slack_bolt.adapter.socket_mode import SocketModeHandler  # noqa: E402

CONFIG_PATH = config_loader._DEFAULT_CONFIG


def build_app(token):
    app = App(token=token)

    def modal(group):
        return settings.settings_modal(
            group, config_loader.load_config(CONFIG_PATH), config_loader.read_env_file())

    @app.event("app_mention")
    def on_mention(event, client):
        client.chat_postMessage(
            channel=event["channel"],
            text="MLB Display settings",
            blocks=settings.control_panel_blocks(
                config_loader.load_config(CONFIG_PATH), socket.gethostname()),
        )

    @app.action("open_settings")
    def on_open(ack, body, client):
        ack()
        client.views_open(trigger_id=body["trigger_id"], view=modal(settings.GROUPS[0]))

    @app.action("select_group")
    def on_group(ack, body, client):
        ack()
        group = body["actions"][0]["selected_option"]["value"]
        client.views_update(view_id=body["view"]["id"], view=modal(group))

    @app.view("settings_modal")
    def on_submit(ack, body, view, client):
        group = view["private_metadata"]
        try:
            changes, errors = settings.save_submission(group, view["state"]["values"], CONFIG_PATH)
        except Exception as exc:  # unparseable/unwritable config: show it rather than die silently
            ack(response_action="errors", errors={f"cfg_{settings.settings_for(group)[0].key}": str(exc)})
            return
        if errors:
            ack(response_action="errors", errors=errors)
            return
        ack()
        text = (f"Saved — applies on the next refresh:\n{settings.describe_changes(changes)}"
                if changes else "No changes.")
        client.chat_postMessage(channel=body["user"]["id"], text=text)

    return app


if __name__ == "__main__":
    os.chdir(_SRC.parent)
    SocketModeHandler(build_app(os.environ["SLACK_BOT_TOKEN"]), os.environ["SLACK_APP_TOKEN"]).start()
