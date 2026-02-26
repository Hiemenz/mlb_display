import json
import os
import time

STATE_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'refresh_state.json')
FULL_REFRESH_INTERVAL = 3600  # 1 hour in seconds


def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def needs_full_refresh():
    """Return True if 1+ hour since last full refresh (or first run)."""
    state = _load_state()
    last = state.get('last_full_refresh')
    if last is None:
        return True
    return (time.time() - last) >= FULL_REFRESH_INTERVAL


def record_full_refresh():
    """Save current timestamp as last full refresh."""
    state = _load_state()
    state['last_full_refresh'] = time.time()
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)
