"""Where are we in the MLB year? One answer for the whole app.

The season doesn't start or end on the same dates every year, so instead of
month checks scattered through the code, ask `season_phase(now, bracket_series)`:

    preseason        Jan 1 -> spring training (MLB's own preSeason window)
    spring           spring training -> opening day
    regular          opening day -> start of the postseason
    postseason       first Wild Card game -> World Series over
    offseason_hot    World Series over -> Dec 20 (hot stove: free agency,
                     winter meetings, Rule 5 draft)
    offseason_quiet  Dec 21 -> end of the year (the next year's record, which
                     starts Jan 1 as `preseason`, takes over from there)

Dates come from the Stats API (/api/v1/seasons), cached in data/season.json and
refreshed at most once a day. If the API is unreachable the cache is used, even
stale; with no data at all a calendar heuristic gives the same answers the old
month-based checks did.

The postseason ends the moment the bracket data says the World Series is
complete (it can finish before the scheduled end date), and runs past the
scheduled end while a World Series is still in progress (capped at Nov 10).
"""
import time
from datetime import date, datetime

import requests

from util import load_json_file, save_off_results

PHASES = ('preseason', 'spring', 'regular', 'postseason',
          'offseason_hot', 'offseason_quiet')
OFFSEASON_PHASES = frozenset({'preseason', 'offseason_hot', 'offseason_quiet'})

_API = 'https://statsapi.mlb.com/api/v1/seasons'
_REFRESH_SECONDS = 24 * 3600
_HOT_STOVE_END = (12, 20)      # (month, day) inclusive
_WS_LATEST_END = (11, 10)      # a World Series still "live" after this is stale data
_UNSET = object()


# ---------------------------------------------------------------------------
# Season dates: fetch + cache
# ---------------------------------------------------------------------------

def _fetch_season(year):
    """The Stats API season record for `year`, or None on any failure."""
    try:
        resp = requests.get(_API, params={'sportId': 1, 'season': year, 'all': 'false'},
                            timeout=10)
        if resp.status_code != 200:
            return None
        for rec in resp.json().get('seasons', []):
            if str(rec.get('seasonId')) == str(year):
                return rec
    except Exception as e:
        print(f'Warning: season dates fetch failed: {e}')
    return None


def get_season(year, now_ts=None):
    """Season record for `year` from the daily cache, fetching when stale.

    Returns the (possibly stale) cached record when the network fails, and
    None when there is nothing at all.
    """
    now_ts = time.time() if now_ts is None else now_ts
    cache = load_json_file('season.json') or {}
    seasons = cache.get('seasons') or {}
    rec = seasons.get(str(year))
    if rec is not None and now_ts - cache.get('fetched_at', 0) < _REFRESH_SECONDS:
        return rec
    new = _fetch_season(year)
    if new is None:
        return rec
    seasons[str(year)] = new
    try:
        save_off_results({'fetched_at': now_ts, 'seasons': seasons}, 'season')
    except OSError as e:
        print(f'Warning: could not cache season dates: {e}')
    return new


# ---------------------------------------------------------------------------
# Phase logic
# ---------------------------------------------------------------------------

def _d(rec, key):
    try:
        return datetime.strptime(rec[key], '%Y-%m-%d').date()
    except (KeyError, TypeError, ValueError):
        return None


def _ws_state(bracket_series):
    """(complete, in_progress) for the World Series in the bracket data."""
    ws = [s for s in (bracket_series or []) if s.get('round') == 'WS']
    return (any(s.get('complete') for s in ws),
            any(not s.get('complete') for s in ws))


def _offseason_phase(d):
    return 'offseason_hot' if (d.month, d.day) <= _HOT_STOVE_END else 'offseason_quiet'


def _calendar_phase(now, bracket_series=None):
    """Fallback when there are no season dates: the old month-based rules."""
    d = now.date()
    ws_done, _ = _ws_state(bracket_series)
    if d.month in (10, 11):
        if ws_done or (d.month == 11 and d.day > _WS_LATEST_END[1]):
            return 'offseason_hot'
        return 'postseason'
    if d.month == 12:
        return _offseason_phase(d)
    if d.month == 1 or (d.month == 2 and d.day < 20):
        return 'preseason'
    if d.month == 2 or (d.month == 3 and d.day < 25):
        return 'spring'
    if d.month == 9 and d.day >= 28:
        return 'postseason'
    return 'regular'


def season_phase(now=None, bracket_series=None, season=_UNSET):
    """One of PHASES for `now` (a naive local datetime; default: now).

    bracket_series: the 'series' list from playoff_bracket.json, if any.
    season: an explicit season record (tests); by default read from the cache /
            API. None forces the calendar fallback.
    """
    now = now or datetime.now()
    if season is _UNSET:
        season = get_season(now.year)
    if not season:
        return _calendar_phase(now, bracket_series)

    d = now.date()
    spring, opening = _d(season, 'springStartDate'), _d(season, 'regularSeasonStartDate')
    post_start, post_end = _d(season, 'postSeasonStartDate'), _d(season, 'postSeasonEndDate')
    pre = _d(season, 'preSeasonStartDate')
    if not (spring and opening and post_start and post_end):
        return _calendar_phase(now, bracket_series)

    if d < spring:
        return 'preseason' if pre is None or d >= pre else 'offseason_quiet'
    if d < opening:
        return 'spring'
    if d < post_start:
        return 'regular'

    ws_done, ws_live = _ws_state(bracket_series)
    cap = date(d.year, *_WS_LATEST_END)
    if not ws_done and (d <= post_end or (ws_live and d <= cap)):
        return 'postseason'
    return _offseason_phase(d)


def is_offseason_phase(phase):
    """True when there is no baseball to follow (idle / replay territory)."""
    return phase in OFFSEASON_PHASES


def main():
    """CLI: print the current phase."""
    series = (load_json_file('playoff_bracket.json') or {}).get('series')
    print(season_phase(datetime.now(), series))


if __name__ == '__main__':
    main()
