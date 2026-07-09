"""
Fetch MLB season statistical leaders (HR, AVG, ERA) and cache to data/leaders.json.

Standalone CLI:
    python src/fetch_leaders.py [--season 2026]
"""
import os
import sys
import time
import argparse
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util import save_off_results, load_json_file

_BASE_URL = 'https://statsapi.mlb.com/api/v1'
_CACHE_TTL_HOURS = 20
_TOP_N = 5
_CATEGORIES = ['homeRuns', 'battingAverage', 'earnedRunAverage']


def fetch_leaders(season=None, sport_id=1):
    """Fetch HR/AVG/ERA leaders and cache to data/leaders.json.

    Returns the cached dict (possibly stale) or {} on total failure.
    """
    if season is None:
        season = datetime.now().year

    cached = load_json_file('leaders.json')
    if cached:
        age_h = (time.time() - cached.get('fetched_at', 0)) / 3600
        if age_h < _CACHE_TTL_HOURS and cached.get('season') == season:
            print(f"Leaders cache fresh ({age_h:.1f}h old) — skipping fetch")
            return cached

    print(f"Fetching {season} season leaders...")
    try:
        cats = ','.join(_CATEGORIES)
        url = (
            f"{_BASE_URL}/stats/leaders"
            f"?leaderCategories={cats}&season={season}&sportId={sport_id}"
            f"&limit={_TOP_N}"
        )
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        leaders: dict = {}
        for group in data.get('leagueLeaders', []):
            cat = group.get('leaderCategory')
            if cat not in _CATEGORIES:
                continue
            entries = []
            for leader in group.get('leaders', [])[:_TOP_N]:
                entries.append({
                    'rank': leader.get('rank'),
                    'value': leader.get('value', ''),
                    'name': leader.get('person', {}).get('fullName', ''),
                    'team_id': str(leader.get('team', {}).get('id', '')),
                })
            leaders[cat] = entries

        result = {
            'season': season,
            'fetched_at': time.time(),
            'leaders': leaders,
        }
        save_off_results(result, 'leaders')
        print(f"Leaders fetched: {list(leaders.keys())}")
        return result
    except Exception as e:
        print(f"Warning: leaders fetch failed: {e}")
        return cached or {}


def main():
    parser = argparse.ArgumentParser(description='Fetch MLB season statistical leaders')
    parser.add_argument('--season', type=int, help='Season year (default: current year)')
    parser.add_argument('--sport-id', type=int, default=1, help='Sport ID (default: 1=MLB)')
    args = parser.parse_args()

    result = fetch_leaders(season=args.season, sport_id=args.sport_id)
    if result.get('leaders'):
        for cat, entries in result['leaders'].items():
            print(f"\n{cat}:")
            for e in entries:
                print(f"  {e['rank']}. {e['name']} ({e['team_id']}) — {e['value']}")


if __name__ == '__main__':
    main()
