"""Regular-season head-to-head record between two teams, for postseason tiles.

    season_series(team_a, team_b, season) -> {str(team_a): wins, str(team_b): wins} or None

The regular season is over by the time this is used, so the result never
changes and is cached on disk (``data/season_series_cache.json``) per
season/pair. A failed fetch is not cached, so the next run retries it.
"""
import requests

from util import load_json_file, save_off_results

_API = 'https://statsapi.mlb.com/api/v1'
_CACHE_FILE = 'season_series_cache'
_FINAL_STATES = ('Final', 'Game Over')


def _key(team_a, team_b, season):
    lo, hi = sorted((int(team_a), int(team_b)))
    return f'{season}:{lo}-{hi}'


def season_series(team_a, team_b, season):
    """Wins by each team over the other in the regular season, or None if unavailable."""
    key = _key(team_a, team_b, season)
    cache = load_json_file(_CACHE_FILE)
    if key in cache:
        return cache[key]

    try:
        resp = requests.get(f'{_API}/schedule', params={
            'sportId': 1, 'season': season, 'gameType': 'R',
            'teamId': team_a, 'opponentId': team_b}, timeout=10)
        resp.raise_for_status()
        dates = resp.json().get('dates', [])
    except (requests.RequestException, ValueError):
        return None

    wins = {str(team_a): 0, str(team_b): 0}
    for d in dates:
        for g in d.get('games', []):
            if g.get('status', {}).get('detailedState') not in _FINAL_STATES:
                continue
            for side in ('away', 'home'):
                t = g.get('teams', {}).get(side, {})
                if t.get('isWinner') and str(t.get('team', {}).get('id')) in wins:
                    wins[str(t['team']['id'])] += 1

    cache[key] = wins
    save_off_results(cache, _CACHE_FILE)
    return wins
