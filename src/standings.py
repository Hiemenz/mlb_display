import requests
import json
import argparse
from datetime import datetime, timedelta


from util import save_off_results, load_json_file



leauge_dict = {
    201:'American League East',
    202:'American League Central',
    200:'American League West',

    204:'National League East',
    205:'National League Central',
    203:'National League West',

    # Triple-A
    219:'International League East',
    221:'International League West',
    233:'Pacific Coast League East',
    231:'Pacific Coast League West',
}
team_abbreviation_list = {}

def get_teams(team_id):
    """Fetch and cache the abbreviation for team_id from the MLB Stats API."""
    tid = str(team_id)
    if tid in team_abbreviation_list:
        return
    try:
        response = requests.get(f'https://statsapi.mlb.com/api/v1/teams/{team_id}')
        if response.status_code == 200:
            data = response.json()
            fetched_team_id = data.get('teams', [{}])[0].get('id')
            team_abbreviation = data.get('teams', [{}])[0].get('abbreviation')

            if fetched_team_id and team_abbreviation:
                team_abbreviation_list[str(fetched_team_id)] = team_abbreviation
            else:
                print(f'Warning: Could not get abbreviation for team {team_id}, using fallback')
                team_abbreviation_list[tid] = f'T{team_id}'
        else:
            print(f'Warning: API returned status {response.status_code} for team {team_id}')
            team_abbreviation_list[tid] = f'T{team_id}'
    except Exception as e:
        print(f'Error fetching team {team_id}: {e}')
        team_abbreviation_list[tid] = f'T{team_id}'



def get_standings(league_id_list, season=2025, date=None, save_as='standings'):
    """Fetch division standings for the given league IDs and write them to data/<save_as>.json."""
    # Pre-populate from teams.json so we avoid per-team API calls for known teams
    cached_teams = load_json_file('teams.json').get('team_abbreviation', {})
    team_abbreviation_list.update(cached_teams)

    division_standings_list = {}
    last_updated = None
    for league_id in league_id_list:
        # Build the API URL with optional date parameter
        url = f'https://statsapi.mlb.com/api/v1/standings?leagueId={league_id}&season={season}&hydrate=team'
        if date:
            url += f'&date={date}'

        response = requests.get(url)

        data = response.json()

        for record in data['records']:
            last_updated = record.get('lastUpdated')



            div_info = record.get('division', {})
            division_id = leauge_dict.get(div_info.get('id')) or div_info.get('name')
            division_team_list = []
            for division in record['teamRecords']:
                last_ten_wins = last_ten_losses = None
                home_wins = home_losses = None
                away_wins = away_losses = None

                for item in division.get("records", {}).get("splitRecords") or []:
                    if item.get('type') == 'lastTen':
                        last_ten_wins = item.get('wins')
                        last_ten_losses = item.get('losses')

                    if item.get('type') == 'home':
                        home_wins = item.get('wins')
                        home_losses = item.get('losses')

                    if item.get('type') == 'away':
                        away_wins = item.get('wins')
                        away_losses = item.get('losses')

                # Use abbreviation from the API response directly; only fetch if missing
                team_obj = division.get("team", {})
                team_id = team_obj.get('id')
                tid = str(team_id) if team_id else None
                if tid and tid not in team_abbreviation_list:
                    abbr = team_obj.get('abbreviation')
                    if abbr:
                        team_abbreviation_list[tid] = abbr
                    else:
                        get_teams(team_id)

                team_standings = {
                # 'division_id': division_id,

                'team_name': team_obj.get('name'),
                'team_id': team_id,

                'divisionRank': division.get("divisionRank"),
                'league_record_wins': division.get("leagueRecord", {}).get('wins'),
                'league_record_losses': division.get("leagueRecord", {}).get('losses'),
                'league_record_percent': division.get("leagueRecord", {}).get('pct'),
                'games_back': division.get("gamesBack"),
                'last_ten_wins': last_ten_wins,
                'last_ten_losses': last_ten_losses,
                'streak': division.get('streak', {}).get('streakCode'),
                'home_wins': home_wins,
                'home_losses': home_losses,
                'away_wins':away_wins,
                'away_losses':away_losses,



                'league_rank': division.get("leagueRank"),
                'sport_rank': division.get("sportRank"),
                'games_played': division.get("gamesPlayed"),
                'wild_card_games_back': division.get("wildCardGamesBack"),
                'league_games_back': division.get("leagueGamesBack"),
                'clinch_indicator': division.get("clinchIndicator", ""),
                }

                # print(team_standings)
                division_team_list.append(team_standings)

            division_standings_list[ division_id] = division_team_list


    standings = {'standings': division_standings_list, 'team_abbreviation': team_abbreviation_list, 'last_updated': last_updated}

    save_off_results(standings, save_as)

    # Also update the teams.json file to include these abbreviations
    teams_data = load_json_file('teams.json')
    existing_abbreviations = teams_data.get('team_abbreviation', {})
    existing_abbreviations.update(team_abbreviation_list)
    save_off_results({'team_abbreviation': existing_abbreviations}, 'teams')



def fetch_wildcard_standings(season=None, date=None):
    """Fetch wildcard standings for AL (103) and NL (104), save data/wildcard_standings.json.

    Returns {'AL': [...], 'NL': [...]} where each entry has:
        abbr, team_id, rank (int), gb (str e.g. '-' or '+1.5')
    """
    if season is None:
        season = datetime.now().year

    result = {'AL': [], 'NL': []}
    league_map = {103: 'AL', 104: 'NL'}

    for league_id, league_key in league_map.items():
        url = (
            f'https://statsapi.mlb.com/api/v1/standings'
            f'?leagueId={league_id}&standingsType=wildCard&season={season}'
        )
        if date:
            url += f'&date={date}'

        try:
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                print(f'Warning: wildcard standings API returned {response.status_code} for league {league_id}')
                continue

            data = response.json()
            teams = []

            for record in data.get('records', []):
                for team_record in record.get('teamRecords', []):
                    # Skip division leaders — they aren't competing for the wildcard
                    if team_record.get('divisionLeader', False):
                        continue

                    team_id = str(team_record.get('team', {}).get('id', ''))
                    abbr = team_abbreviation_list.get(team_id)
                    if not abbr:
                        abbr = team_record.get('team', {}).get('abbreviation', f'T{team_id}')
                        if team_id:
                            team_abbreviation_list[team_id] = abbr

                    wc_rank = team_record.get('wildCardRank')
                    wc_gb = team_record.get('wildCardGamesBack') or '-'

                    teams.append({
                        'abbr': abbr,
                        'team_id': team_id,
                        'rank': int(wc_rank) if wc_rank else 99,
                        'gb': wc_gb,
                    })

            teams.sort(key=lambda t: t['rank'])
            result[league_key] = teams[:10]

        except Exception as e:
            print(f'Error fetching wildcard standings for league {league_id}: {e}')

    save_off_results(result, 'wildcard_standings')
    return result


def fetch_playoff_bracket(season=None):
    """Fetch current postseason series data and save to data/playoff_bracket.json.

    Queries the schedule API for all postseason game types (Wild Card through World Series),
    aggregates games into series, and counts wins for each team.

    Returns the bracket dict, or None on failure.
    """
    import time as _t
    if season is None:
        season = datetime.now().year

    url = (
        f'https://statsapi.mlb.com/api/v1/schedule'
        f'?sportId=1&gameType=F,D,L,W'
        f'&season={season}'
        f'&startDate={season}-01-01&endDate={season}-12-31'
        f'&hydrate=team'
    )
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            print(f'Warning: playoff bracket fetch returned {resp.status_code}')
            return None
        data = resp.json()
    except Exception as e:
        print(f'Error fetching playoff bracket: {e}')
        return None

    _WIN_GOAL  = {'F': 2, 'D': 3, 'L': 4, 'W': 4}
    _ROUND_ABB = {'F': 'WC', 'D': 'DS', 'L': 'CS', 'W': 'WS'}
    _ROUND_ORD = {'F': 0, 'D': 1, 'L': 2, 'W': 3}

    series_map = {}

    for date_entry in data.get('dates', []):
        for game in date_entry.get('games', []):
            gtype = game.get('gameType', '')
            if gtype not in _WIN_GOAL:
                continue

            teams    = game.get('teams', {})
            away_t   = teams.get('away', {})
            home_t   = teams.get('home', {})
            away_obj = away_t.get('team', {})
            home_obj = home_t.get('team', {})
            away_id  = str(away_obj.get('id', ''))
            home_id  = str(home_obj.get('id', ''))

            # Stable key: sort IDs so home/away swap in WS doesn't create duplicates
            key = tuple(sorted([away_id, home_id]))

            if key not in series_map:
                series_map[key] = {
                    'round':       _ROUND_ABB.get(gtype, '?'),
                    'round_order': _ROUND_ORD.get(gtype, 9),
                    'game_type':   gtype,
                    'away_abbr':   away_obj.get('abbreviation', '???'),
                    'home_abbr':   home_obj.get('abbreviation', '???'),
                    'away_id':     away_id,
                    'home_id':     home_id,
                    'away_wins':   0,
                    'home_wins':   0,
                    'complete':    False,
                    'winner_abbr': None,
                }

            entry = series_map[key]
            state = game.get('status', {}).get('detailedState', '')
            if state in ('Final', 'Game Over', 'Final: Tied'):
                if away_t.get('isWinner'):
                    entry['away_wins'] += 1
                elif home_t.get('isWinner'):
                    entry['home_wins'] += 1

            wins_needed = _WIN_GOAL[gtype]
            if entry['away_wins'] >= wins_needed:
                entry['complete']    = True
                entry['winner_abbr'] = entry['away_abbr']
            elif entry['home_wins'] >= wins_needed:
                entry['complete']    = True
                entry['winner_abbr'] = entry['home_abbr']

    series_list = sorted(
        series_map.values(),
        key=lambda s: (s.pop('round_order', 9), s.get('away_abbr', '')),
    )

    bracket_data = {
        'season':     season,
        'fetched_at': _t.time(),
        'series':     series_list,
    }
    save_off_results(bracket_data, 'playoff_bracket')
    return bracket_data


def fetch_transactions(lookback_days=2):
    """Fetch recent MLB transactions (IL moves, call-ups/demotions, signings, etc.)
    and save to data/transactions.json.

    Queries the transactions API for the window [today - lookback_days, today],
    newest first.

    Returns the transactions dict, or None on failure.
    """
    import time as _t
    end = datetime.now()
    start = end - timedelta(days=lookback_days)

    url = (
        f'https://statsapi.mlb.com/api/v1/transactions'
        f'?sportId=1'
        f'&startDate={start.strftime("%Y-%m-%d")}&endDate={end.strftime("%Y-%m-%d")}'
    )
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            print(f'Warning: transactions fetch returned {resp.status_code}')
            return None
        data = resp.json()
    except Exception as e:
        print(f'Error fetching transactions: {e}')
        return None

    entries = []
    for tx in data.get('transactions', []):
        team = tx.get('toTeam') or tx.get('fromTeam') or {}
        entries.append({
            'date':        tx.get('date', ''),
            'player_name': (tx.get('person') or {}).get('fullName', ''),
            'team_abbr':   team.get('abbreviation', ''),
            'team_id':     str(team.get('id', '')),
            'type_desc':   tx.get('typeDesc', ''),
            'description': tx.get('description', ''),
        })

    # Newest first
    entries.sort(key=lambda e: e['date'], reverse=True)

    transactions_data = {
        'fetched_at':    _t.time(),
        'lookback_days': lookback_days,
        'transactions':  entries,
    }
    save_off_results(transactions_data, 'transactions')
    return transactions_data


def main():
    """CLI entry point: fetch and save standings for a given season or date."""
    parser = argparse.ArgumentParser(description='Fetch standings for a specific season or date')
    parser.add_argument('--season', '-s', type=int, default=datetime.now().year,
                        help='Season year (e.g., 2024, 2023). Default is current year.')
    parser.add_argument('--date', '-d', type=str,
                        help='Specific date for standings (format: YYYY-MM-DD or MM/DD/YYYY).')
    parser.add_argument('--aaa', action='store_true',
                        help='Fetch Triple-A (IL + PCL) standings instead of MLB (AL + NL).')

    args = parser.parse_args()

    league_ids = [117, 112] if args.aaa else [103, 104]

    # If a specific date is provided, extract the year from it and format it properly
    date_param = None
    if args.date:
        try:
            # Try both date formats
            try:
                date_obj = datetime.strptime(args.date, '%Y-%m-%d')
            except ValueError:
                date_obj = datetime.strptime(args.date, '%m/%d/%Y')

            season = date_obj.year
            date_param = date_obj.strftime('%m/%d/%Y')  # MLB API uses MM/DD/YYYY format
            print(f'Fetching standings for date: {date_param} (season {season})')
        except ValueError:
            print('Error: Invalid date format. Please use YYYY-MM-DD or MM/DD/YYYY')
            return
    else:
        season = args.season
        print(f'Fetching standings for season: {season}')

    get_standings(league_ids, season=season, date=date_param)
    print(f'\nTeam abbreviations loaded: {len(team_abbreviation_list)} teams')
    print('Standings data saved to data/standings.json')

if __name__ == '__main__':  # pragma: no cover
    main()
