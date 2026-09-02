"""Fetch season win/loss trend for a team.

Writes data/win_trend.json:
{
  "team_id": 147,
  "team_abbr": "NYY",
  "season": 2026,
  "fetched_at": <unix ts>,
  "games": [
    {"date": "2026-04-01", "wins": 1, "losses": 0, "result": "W"},
    ...
  ]
}

Standalone:
    python src/fetch_win_trend.py [--abbr NYY] [--season 2026]
"""
import argparse
import sys
import os
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from util import load_json_file, save_off_results

_BASE = 'https://statsapi.mlb.com/api/v1'
_TIMEOUT = 15


def _abbr_to_team_id(abbr):
    """Return the MLB team ID for an abbreviation, from cached teams.json."""
    data = load_json_file('teams.json') or {}
    abbr_map = data.get('team_abbreviation', {})
    abbr_upper = abbr.upper()
    for tid, a in abbr_map.items():
        if a.upper() == abbr_upper:
            return int(tid)
    return None


def fetch_win_trend(team_abbr, season=None):
    """Fetch season game-by-game results for team_abbr.

    Returns the written data dict, or None on failure.
    season defaults to the current calendar year.
    """
    if season is None:
        season = datetime.now().year

    team_id = _abbr_to_team_id(team_abbr)
    if team_id is None:
        print(f"fetch_win_trend: unknown abbreviation {team_abbr!r}")
        return None

    url = (
        f'{_BASE}/schedule'
        f'?teamId={team_id}&season={season}&sportId=1&gameType=R'
        f'&hydrate=decisions,linescore'
    )
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as exc:
        print(f"fetch_win_trend: API error: {exc}")
        return None

    games = []
    wins = losses = 0
    for date_entry in sorted(raw.get('dates', []), key=lambda d: d.get('date', '')):
        date_str = date_entry.get('date', '')
        for game in date_entry.get('games', []):
            status = game.get('status', {}).get('detailedState', '')
            if not (status.startswith('Final') or status.startswith('Completed Early')):
                continue
            teams = game.get('teams', {})
            away = teams.get('away', {})
            home = teams.get('home', {})
            if away.get('team', {}).get('id') == team_id:
                is_winner = away.get('isWinner', False)
            elif home.get('team', {}).get('id') == team_id:
                is_winner = home.get('isWinner', False)
            else:
                continue
            result = 'W' if is_winner else 'L'
            if is_winner:
                wins += 1
            else:
                losses += 1
            games.append({'date': date_str, 'wins': wins, 'losses': losses, 'result': result})

    data = {
        'team_id': team_id,
        'team_abbr': team_abbr.upper(),
        'season': season,
        'fetched_at': time.time(),
        'games': games,
    }
    save_off_results(data, 'win_trend')
    print(f"win_trend: {wins}W-{losses}L over {len(games)} games for {team_abbr.upper()} {season}")
    return data


if __name__ == '__main__':  # pragma: no cover
    parser = argparse.ArgumentParser(description='Fetch season win/loss trend')
    parser.add_argument('--abbr', default=None, help='Team abbreviation (e.g. NYY)')
    parser.add_argument('--season', type=int, default=None)
    args = parser.parse_args()

    _abbr = args.abbr
    if _abbr is None:
        try:
            from config_loader import load_config
            _cfg = load_config()
            _abbr = _cfg.get('primary', '')
        except Exception:
            pass

    if not _abbr:
        print("Error: provide --abbr or set primary in config.yaml")
        sys.exit(1)

    result = fetch_win_trend(_abbr, season=args.season)
    if result is None:
        sys.exit(1)
