import requests
from datetime import datetime
from util import load_json_file, save_off_results


def fetch_league_leaders(season=None):
    """Fetch HR, RBI, AVG, ERA, K leaders. Caches to data/leaders.json."""
    if season is None:
        season = datetime.now().year

    leaders = {}

    # Hitting leaders
    try:
        url = (
            'https://statsapi.mlb.com/api/v1/stats/leaders'
            '?leaderCategories=homeRuns,battingAverage,rbi'
            f'&season={season}&sportId=1&limit=5&hydrate=person'
        )
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for category in data.get('leagueLeaders', []):
                cat_name = category.get('leaderCategory')
                leaders[cat_name] = []
                for leader in category.get('leaders', []):
                    leaders[cat_name].append({
                        'rank': leader.get('rank'),
                        'value': leader.get('value'),
                        'name': leader.get('person', {}).get('fullName', ''),
                        'team': leader.get('team', {}).get('abbreviation', ''),
                    })
    except Exception as e:
        print(f"Error fetching hitting leaders: {e}")

    # Pitching leaders
    try:
        url = (
            'https://statsapi.mlb.com/api/v1/stats/leaders'
            '?leaderCategories=earnedRunAverage,strikeOuts'
            f'&season={season}&sportId=1&limit=5&hydrate=person&statGroup=pitching'
        )
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for category in data.get('leagueLeaders', []):
                cat_name = category.get('leaderCategory')
                leaders[cat_name] = []
                for leader in category.get('leaders', []):
                    leaders[cat_name].append({
                        'rank': leader.get('rank'),
                        'value': leader.get('value'),
                        'name': leader.get('person', {}).get('fullName', ''),
                        'team': leader.get('team', {}).get('abbreviation', ''),
                    })
    except Exception as e:
        print(f"Error fetching pitching leaders: {e}")

    save_off_results(leaders, 'leaders')
    return leaders


def fetch_hot_streaks(season=None, num_games=7, limit=10):
    """Fetch players with best AVG over last N games. Caches to data/hot_streaks.json."""
    if season is None:
        season = datetime.now().year

    hot = []
    try:
        url = (
            'https://statsapi.mlb.com/api/v1/stats'
            '?stats=lastXGames&group=hitting'
            f'&season={season}&sportId=1&numGames={num_games}'
            f'&sortStat=avg&limit={limit}&hydrate=person,team'
        )
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            splits = data.get('stats', [{}])[0].get('splits', [])
            for i, split in enumerate(splits):
                stat = split.get('stat', {})
                hot.append({
                    'rank': i + 1,
                    'name': split.get('player', {}).get('fullName', ''),
                    'team': split.get('team', {}).get('abbreviation', ''),
                    'avg': stat.get('avg', '.000'),
                    'hits': stat.get('hits', 0),
                    'atBats': stat.get('atBats', 0),
                })
    except Exception as e:
        print(f"Error fetching hot streaks: {e}")

    save_off_results({'hot_streaks': hot, 'num_games': num_games}, 'hot_streaks')
    return hot
