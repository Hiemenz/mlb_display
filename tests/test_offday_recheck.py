"""Off-day smart polling re-checks the schedule every _OFFDAY_RECHECK_HOURS."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import main  # noqa: E402


def _sched(hours_ago, next_game_date='2026-10-12'):
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(timespec='seconds')
    return {'next_game_date': next_game_date, 'last_game_fetch': ts,
            'last_fetch_date': '2026-10-11'}


def test_offday_skips_when_recently_checked():
    skip, reason = main._should_skip_poll('2026-10-11', {}, _sched(5))
    assert skip and reason.startswith('No games until')


def test_offday_rechecks_after_six_hours():
    assert main._should_skip_poll('2026-10-11', {}, _sched(6.1)) == (False, '')


def test_offday_rechecks_when_no_fetch_timestamp():
    sched = {'next_game_date': '2026-10-12'}
    assert main._should_skip_poll('2026-10-11', {}, sched) == (False, '')


def test_hours_since_handles_naive_and_garbage():
    naive = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(tzinfo=None).isoformat()
    assert 1.9 < main._hours_since(naive) < 2.1
    assert main._hours_since('garbage') is None
    assert main._hours_since(None) is None
