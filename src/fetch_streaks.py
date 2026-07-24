"""
Fetch MLB rolling-window leaders for two "streak" panels and cache to
data/streaks.json:

  streaks   — Hot Hitters: batting-average leaders over the last 14 days
              (position players only).
  scoreless — Hot Arms: ERA leaders over the last 14 days (starting pitchers),
              sorted ascending so the best (lowest ERA) appear first.

The MLB Stats API does not expose consecutive hitting-streak or scoreless-
inning-streak counts as leader categories, so these rolling averages are the
best available proxy for "who's been on a tear lately."

Standalone CLI:
    python src/fetch_streaks.py [--season 2026] [--days 14]
"""
import os
import sys
import time
import argparse
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util import save_off_results, load_json_file

_BASE_URL = 'https://statsapi.mlb.com/api/v1'
_CACHE_TTL_HOURS = 20
_TOP_N = 8
_ROLLING_DAYS = 14


def _parse_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 999.0


def fetch_streaks(season=None, sport_id=1, force=False, days=_ROLLING_DAYS):
    """Fetch rolling batting-average + ERA leaders and cache to data/streaks.json.

    Returns the cached dict or {} on failure.
    """
    if season is None:
        season = datetime.now().year

    cached = load_json_file('streaks.json')
    if cached and not force:
        age_h = (time.time() - cached.get('fetched_at', 0)) / 3600
        if age_h < _CACHE_TTL_HOURS and cached.get('season') == season:
            print(f"Streaks cache fresh ({age_h:.1f}h old) — skipping fetch")
            return cached

    print(f"Fetching {season} hot hitters + hot arms (last {days} days)...")

    abbr_map = load_json_file('teams.json').get('team_abbreviation', {})

    today = datetime.now()
    start_date = (today - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = today.strftime('%Y-%m-%d')

    # Primary fetch: batting average (hitting) + ERA (pitching), top _TOP_N each
    primary_url = (
        f"{_BASE_URL}/stats/leaders"
        f"?leaderCategories=battingAverage,earnedRunAverage"
        f"&season={season}&sportId={sport_id}"
        f"&limit={_TOP_N}"
        f"&startDate={start_date}&endDate={end_date}"
    )
    # Secondary fetch: IP + gamesPlayed with wide limit so join always hits
    secondary_url = (
        f"{_BASE_URL}/stats/leaders"
        f"?leaderCategories=inningsPitched,gamesPlayed"
        f"&season={season}&sportId={sport_id}"
        f"&limit=50"
        f"&startDate={start_date}&endDate={end_date}"
    )

    hitters = []
    pitchers = []

    try:
        primary_resp = requests.get(primary_url, timeout=10)
        primary_resp.raise_for_status()
        secondary_resp = requests.get(secondary_url, timeout=10)
        secondary_resp.raise_for_status()

        # Build lookup tables keyed by player ID
        ip_by_player = {}
        games_by_player = {}
        for group in secondary_resp.json().get('leagueLeaders', []):
            sg = group.get('statGroup')
            cat = group.get('leaderCategory')
            for leader in group.get('leaders', []):
                pid = leader.get('person', {}).get('id')
                if not pid:
                    continue
                if sg == 'pitching' and cat == 'inningsPitched':
                    ip_by_player[pid] = leader.get('value', '')
                elif sg == 'hitting' and cat == 'gamesPlayed':
                    games_by_player[pid] = leader.get('value', '')

        data = primary_resp.json()

        for group in data.get('leagueLeaders', []):
            sg = group.get('statGroup')
            cat = group.get('leaderCategory')

            if sg == 'hitting' and cat == 'battingAverage':
                for leader in group.get('leaders', [])[:_TOP_N]:
                    team_id = str(leader.get('team', {}).get('id', ''))
                    pid = leader.get('person', {}).get('id')
                    hitters.append({
                        'rank': leader.get('rank', len(hitters) + 1),
                        'avg': leader.get('value', ''),
                        'games': games_by_player.get(pid, ''),
                        'name': leader.get('person', {}).get('fullName', ''),
                        'team_id': team_id,
                        'abbr': abbr_map.get(team_id, ''),
                    })

            elif sg == 'pitching' and cat == 'earnedRunAverage':
                raw = group.get('leaders', [])
                # Sort ascending — lowest ERA is best
                raw_sorted = sorted(raw, key=lambda l: _parse_float(l.get('value')))
                for i, leader in enumerate(raw_sorted[:_TOP_N]):
                    team_id = str(leader.get('team', {}).get('id', ''))
                    pid = leader.get('person', {}).get('id')
                    pitchers.append({
                        'rank': i + 1,
                        'era': leader.get('value', ''),
                        'ip': ip_by_player.get(pid, ''),
                        'name': leader.get('person', {}).get('fullName', ''),
                        'team_id': team_id,
                        'abbr': abbr_map.get(team_id, ''),
                    })

        result = {
            'season': season,
            'days': days,
            'fetched_at': time.time(),
            'streaks': hitters,
            'scoreless': pitchers,
        }
        save_off_results(result, 'streaks')
        print(f"Hot hitters: {len(hitters)}, hot arms: {len(pitchers)}")
        return result

    except Exception as e:
        print(f"Warning: streaks fetch failed: {e}")
        return cached or {}


def main():
    parser = argparse.ArgumentParser(description='Fetch MLB hot hitters + hot arms')
    parser.add_argument('--season', type=int, help='Season year (default: current year)')
    parser.add_argument('--sport-id', type=int, default=1, help='Sport ID (default: 1=MLB)')
    parser.add_argument('--days', type=int, default=_ROLLING_DAYS, help='Rolling window in days')
    args = parser.parse_args()

    result = fetch_streaks(season=args.season, sport_id=args.sport_id, days=args.days)
    print('\nHot Hitters (14d avg):')
    for e in result.get('streaks', []):
        print(f"  {e['rank']}. {e['name']:25s} {e.get('abbr','?'):4s}  {e['avg']}")
    print('\nHot Arms (14d ERA):')
    for e in result.get('scoreless', []):
        print(f"  {e['rank']}. {e['name']:25s} {e.get('abbr','?'):4s}  {e['era']}")


if __name__ == '__main__':
    main()
