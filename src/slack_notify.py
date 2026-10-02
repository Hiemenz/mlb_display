"""
Slack error notifications via Incoming Webhook.

Usage:
    from slack_notify import notify_error
    notify_error("render failed", exc)

Set SLACK_WEBHOOK_URL in .env (or the environment) to enable. When the var is
absent the calls are silent no-ops, so the display keeps running without Slack.

Rate-limiting: the same error_key is suppressed for COOLDOWN_SECONDS after the
first fire, preventing a fast crash loop from flooding the channel.
"""

import json
import os
import sys
import time
import traceback
import urllib.request
from urllib.error import URLError

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COOLDOWN_FILE = os.path.join(_BASE_DIR, 'data', 'slack_notify_cooldown.json')
COOLDOWN_SECONDS = 3600  # 1 hour per error key


def _webhook_url() -> str:
    return os.environ.get('SLACK_WEBHOOK_URL', '')


def _load_cooldowns() -> dict:
    try:
        with open(_COOLDOWN_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cooldowns(data: dict) -> None:
    os.makedirs(os.path.dirname(_COOLDOWN_FILE), exist_ok=True)
    with open(_COOLDOWN_FILE, 'w') as f:
        json.dump(data, f)


def _is_cooled_down(error_key: str) -> bool:
    """Return True when this error key was recently sent and is still in cooldown."""
    cooldowns = _load_cooldowns()
    last = cooldowns.get(error_key, 0)
    return (time.time() - last) < COOLDOWN_SECONDS


def _record_sent(error_key: str) -> None:
    cooldowns = _load_cooldowns()
    cooldowns[error_key] = time.time()
    _save_cooldowns(cooldowns)


def notify_error(message: str, exc: BaseException | None = None,
                 error_key: str | None = None) -> None:
    """Send an error notification to Slack.

    Args:
        message:   Human-readable description of what failed.
        exc:       Optional exception instance — its traceback is appended.
        error_key: Rate-limit key (defaults to ``message``). Errors with the
                   same key are suppressed for COOLDOWN_SECONDS after the
                   first send.
    """
    url = _webhook_url()
    if not url:
        return

    key = error_key or message
    if _is_cooled_down(key):
        return

    text = f":warning: *MLB Display error*\n{message}"
    if exc is not None:
        tb = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        # Keep the traceback brief — last 10 lines only
        lines = tb.strip().splitlines()
        snippet = '\n'.join(lines[-10:])
        text += f"\n```{snippet}```"

    payload = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
        _record_sent(key)
    except (URLError, OSError) as _e:
        # Never let a Slack failure crash the display loop.
        print(f"slack_notify: failed to send ({_e})", file=sys.stderr)
