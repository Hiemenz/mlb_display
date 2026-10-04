"""Fetch recent relief-pitcher workload for the primary team and today's opponent.

Writes data/bullpen.json:
{
  "date": "2026-09-29",           # the day the data was built for
  "days": 3,                      # look-back window: the last N calendar days before today
  "primary": "ATL",
  "fetched_at": <unix ts>,
  "team_order": ["144", "121"],   # primary, today's opponent, then any extra teams
  "teams": {
    "144": {"team_id": 144, "abbr": "ATL",
            "pitchers": [{"name": "Dodd", "yesterday": 12, "total": 25}, ...]},
    ...
  }
}

Only relievers count (the first pitcher in a box score is the starter), and
today's game is excluded. The window is the last ``days`` calendar days before
today, so a team that hasn't played recently (off days, a week between series)
shows everyone rested: the tile answers "who is tired going into today".
Pitchers are sorted by total pitches over the window, heaviest first.

Standalone:
    python src/fetch_bullpen.py [--abbr ATL] [--days 3] [--force]
"""
import argparse
import os
import sys
import time
from datetime import date, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from util import load_json_file, save_off_results

_BASE = 'https://statsapi.mlb.com/api/v1'
_TIMEOUT = 15
_CACHE_TTL_HOURS = 6
DEFAULT_DAYS = 3
_LIVE_STATES = ('In Progress', 'Player challenge', 'Manager challenge')
_PLAYOFF_GAME_TYPES = ('W', 'D', 'L', 'F')


def live_playoff_team_ids(games, primary_abbr=''):
    """Team ids (str) of every team in a live postseason game, in game order.

    ``games`` is the games.json list. The primary team's game, if live, comes
    first so its tiles win the free slots when space is short.
    """
    live = [g for g in games or []
            if g.get('detailed_state') in _LIVE_STATES
            and g.get('game_type') in _PLAYOFF_GAME_TYPES]
    live.sort(key=lambda g: primary_abbr not in (g.get('away_team'), g.get('home_team')))
    ids = []
    for g in live:
        for key in ('away_team_id', 'home_team_id'):
            tid = g.get(key)
            if tid and str(tid) not in ids:
                ids.append(str(tid))
    return ids


def _abbr_to_team_id(abbr):
    abbr_map = (load_json_file('teams.json') or {}).get('team_abbreviation', {})
    for tid, a in abbr_map.items():
        if a.upper() == abbr.upper():
            return int(tid)
    return None


def _get(path):
    resp = requests.get(f'{_BASE}{path}', timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _schedule(team_id, start, end):
    """Games for one team between two dates inclusive, as (date_str, game) pairs."""
    raw = _get(f'/schedule?teamId={team_id}&sportId=1'
               f'&startDate={start.isoformat()}&endDate={end.isoformat()}')
    return [(d.get('date', ''), g)
            for d in raw.get('dates', []) for g in d.get('games', [])]


def _opponent_today(team_id, today):
    """Team id of the first opponent on today's schedule, or None if idle."""
    for _, game in _schedule(team_id, today, today):
        sides = game.get('teams', {})
        for side, other in (('away', 'home'), ('home', 'away')):
            if (sides.get(side, {}).get('team') or {}).get('id') == team_id:
                return (sides.get(other, {}).get('team') or {}).get('id')
    return None


def _short_name(full_name):
    """'Bryce Elder' -> 'B. Elder'; a single token is returned unchanged."""
    first, _, rest = (full_name or '').partition(' ')
    return f'{first[0]}. {rest}' if rest else first


def _relief_lines(box_side):
    """(name, pitches) for each non-starting pitcher on one side of a box score."""
    players = box_side.get('players', {})
    lines = []
    for pid in (box_side.get('pitchers') or [])[1:]:
        p = players.get(f'ID{pid}', {})
        pitches = ((p.get('stats') or {}).get('pitching') or {}).get('numberOfPitches')
        if pitches:
            lines.append((_short_name((p.get('person') or {}).get('fullName', '')), pitches))
    return lines


def _roster_pitchers(team_id):
    """Short names of all pitchers on the active roster for *team_id*."""
    try:
        data = _get(f'/teams/{team_id}/roster?rosterType=active')
        names = set()
        for p in data.get('roster', []):
            if (p.get('position') or {}).get('type') == 'Pitcher':
                full = (p.get('person') or {}).get('fullName', '')
                if full:
                    names.add(_short_name(full))
        return names
    except Exception:
        return set()


def _team_bullpen(team_id, today, days, box_cache):
    """Reliever workload for one team over the ``days`` calendar days before today.

    Games on yesterday count as ``yesterday`` (the solid bar); earlier days in
    the window add to ``total`` only. The window is anchored to today, not to
    the team's last game, so a team that hasn't played within it has no workload.

    Pitchers on the active roster who threw no pitches during the window are
    included at the bottom with yesterday=0, total=0 (rested).
    """
    yesterday = (today - timedelta(days=1)).isoformat()
    window_start = today - timedelta(days=days)
    finals = [(d, g) for d, g in _schedule(team_id, window_start, today - timedelta(days=1))
              if (g.get('status', {}).get('detailedState', '')).startswith(('Final', 'Completed Early'))]
    usage = {}
    for date_str, game in finals:
        pk = game.get('gamePk')
        if pk not in box_cache:
            box_cache[pk] = _get(f'/game/{pk}/boxscore')
        for side in ('away', 'home'):
            box_side = box_cache[pk].get('teams', {}).get(side, {})
            if (box_side.get('team') or {}).get('id') != team_id:
                continue
            for name, pitches in _relief_lines(box_side):
                row = usage.setdefault(name, {'name': name, 'yesterday': 0, 'total': 0})
                row['total'] += pitches
                if date_str == yesterday:
                    row['yesterday'] += pitches
    for name in _roster_pitchers(team_id):
        if name not in usage:
            usage[name] = {'name': name, 'yesterday': 0, 'total': 0}
    return sorted(usage.values(), key=lambda r: (-r['total'], r['name']))


def fetch_bullpen(primary_abbr, days=DEFAULT_DAYS, force=False, today=None,
                  extra_team_ids=()):
    """Build and cache bullpen workload for the primary team and its opponent today.

    ``extra_team_ids`` adds further teams (e.g. everyone in a live postseason
    game); a cache that lacks any of them is rebuilt.

    Returns the data dict, the still-usable cache if the network fails, or {}.
    """
    today = today or date.today()
    cached = load_json_file('bullpen.json') or {}
    if (cached and not force
            and cached.get('date') == today.isoformat()
            and cached.get('primary') == primary_abbr
            and cached.get('days') == days
            and all(str(t) in cached.get('teams', {}) for t in extra_team_ids)
            and (time.time() - cached.get('fetched_at', 0)) / 3600 < _CACHE_TTL_HOURS):
        return cached

    primary_id = _abbr_to_team_id(primary_abbr or '')
    if primary_id is None:
        print(f"fetch_bullpen: unknown team {primary_abbr!r}")
        return {}

    abbr_map = (load_json_file('teams.json') or {}).get('team_abbreviation', {})
    try:
        team_ids = [primary_id]
        opponent_id = _opponent_today(primary_id, today)
        if opponent_id:
            team_ids.append(opponent_id)
        for tid in extra_team_ids:
            if int(tid) not in team_ids:
                team_ids.append(int(tid))
        box_cache = {}
        teams = {
            str(tid): {
                'team_id': tid,
                'abbr': abbr_map.get(str(tid), ''),
                'pitchers': _team_bullpen(tid, today, days, box_cache),
            }
            for tid in team_ids
        }
    except Exception as exc:
        print(f"fetch_bullpen: API error: {exc}")
        return cached

    data = {
        'date': today.isoformat(),
        'days': days,
        'primary': primary_abbr,
        'fetched_at': time.time(),
        'team_order': [str(t) for t in team_ids],
        'teams': teams,
    }
    save_off_results(data, 'bullpen')
    print(f"bullpen: {', '.join(t['abbr'] for t in teams.values())} over last {days} days")
    return data


if __name__ == '__main__':  # pragma: no cover
    parser = argparse.ArgumentParser(description='Fetch recent bullpen workload')
    parser.add_argument('--abbr', default=None, help='Primary team abbreviation (e.g. ATL)')
    parser.add_argument('--days', type=int, default=DEFAULT_DAYS)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()

    _abbr = args.abbr
    if _abbr is None:
        from config_loader import load_config
        _abbr = load_config().get('primary', '')
    if not _abbr:
        print("Error: provide --abbr or set primary in config.yaml")
        sys.exit(1)
    if not fetch_bullpen(_abbr, days=args.days, force=args.force):
        sys.exit(1)
