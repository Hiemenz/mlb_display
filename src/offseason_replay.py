"""Off-season screen: replay every game of a random past date.

Once the World Series is over there is nothing to show, so the idle screen
hands the panel to src/replay.py on a randomly chosen past game day. Replay
blocks for the whole day's games, so it runs as a detached subprocess guarded
by a pid lock: each cron tick either sees it still running (and leaves the
panel alone) or starts a fresh replay on a new random date.
"""
import json
import os
import subprocess
import sys

from fetch_idle import pick_replay_date
from util import load_json_file

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOCK_PATH = os.path.join(_REPO_ROOT, 'data', 'offseason_replay.json')

_DEFAULT_STEP_MINUTES = 5     # a whole game day in ~an hour at the default delay
_DEFAULT_DELAY_SECONDS = 30
_DEFAULT_REPLAYS_PER_DAY = 2  # then the regular idle screen takes over until tomorrow


def is_offseason(now, bracket_series=None):
    """True once the World Series is over and until the next season starts.

    Dec-Feb is always off-season. In Oct/Nov it starts as soon as the World
    Series is complete in the bracket data, or after Nov 10 regardless.
    """
    if now.month in (12, 1, 2):
        return True
    if now.month == 11 and now.day > 10:
        return True
    if now.month in (10, 11):
        return any(s.get('round') == 'WS' and s.get('complete')
                   for s in (bracket_series or []))
    return False


def _replay_running(pid):
    """True when pid is alive and is still a replay.py (guards against pid reuse)."""
    try:
        with open(f'/proc/{int(pid)}/cmdline', 'rb') as f:
            return b'replay.py' in f.read()
    except (OSError, ValueError, TypeError):
        return False


def maybe_start_replay(config, today_str):
    """Ensure a replay of a random past day is running; True when one is.

    False means nothing could be started (disabled, or no usable date), so the
    caller should fall back to its normal idle screen (including once the
    day's replay quota is used up).
    """
    if not config.get('offseason_replay', True):
        return False

    lock = load_json_file('offseason_replay.json') or {}
    if _replay_running(lock.get('pid')):
        print(f"Off-season: replay of {lock.get('date')} still running")
        return True

    started_today = lock.get('count', 0) if lock.get('day') == today_str else 0
    if started_today >= config.get('offseason_replays_per_day', _DEFAULT_REPLAYS_PER_DAY):
        return False

    date_str = pick_replay_date(today_str)
    if not date_str:
        print("Off-season: no usable replay date found")
        return False

    cmd = [sys.executable, os.path.join(_REPO_ROOT, 'src', 'replay.py'),
           '--date', date_str,
           '--step', str(config.get('offseason_replay_step_minutes', _DEFAULT_STEP_MINUTES)),
           '--delay', str(config.get('offseason_replay_delay_seconds', _DEFAULT_DELAY_SECONDS)),
           '--align-starts']
    try:
        proc = subprocess.Popen(cmd, cwd=_REPO_ROOT, start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        os.makedirs(os.path.dirname(_LOCK_PATH), exist_ok=True)
        with open(_LOCK_PATH, 'w') as f:
            json.dump({'pid': proc.pid, 'date': date_str,
                       'day': today_str, 'count': started_today + 1}, f)
    except OSError as e:
        print(f"Off-season: could not start replay ({e})")
        return False
    print(f"Off-season: started replay of {date_str} (pid {proc.pid})")
    return True
