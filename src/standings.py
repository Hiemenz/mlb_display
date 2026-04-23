import requests
import json
import argparse
from datetime import datetime


from util import save_off_results

    

leauge_dict = {
    201:'American League East',
    202:'American League Central',
    200:'American League West',
    
    204:'National League East',
    205:'National League Central',
    203:'National League West',
    
}
team_abbreviation_list = {}

def get_teams(team_id):
    try:
        response = requests.get(f'https://statsapi.mlb.com/api/v1/teams/{team_id}')
        if response.status_code == 200:
            data = response.json()
            fetched_team_id = data.get('teams', [{}])[0].get('id')
            team_abbreviation = data.get('teams', [{}])[0].get('abbreviation')

            if fetched_team_id and team_abbreviation:
                print(f'Adding team: {fetched_team_id} => {team_abbreviation}')
                team_abbreviation_list[str(fetched_team_id)] = team_abbreviation
            else:
                print(f'Warning: Could not get abbreviation for team {team_id}, using fallback')
                team_abbreviation_list[str(team_id)] = f'T{team_id}'
        else:
            print(f'Warning: API returned status {response.status_code} for team {team_id}')
            team_abbreviation_list[str(team_id)] = f'T{team_id}'
    except Exception as e:
        print(f'Error fetching team {team_id}: {e}')
        team_abbreviation_list[str(team_id)] = f'T{team_id}'

        

def get_standings(league_id_list, season=2025, date=None, save_as='standings'):
    division_standings_list = {}
    for league_id in league_id_list:
        # Build the API URL with optional date parameter
        url = f'https://statsapi.mlb.com/api/v1/standings?leagueId={league_id}&season={season}'
        if date:
            url += f'&date={date}'

        response = requests.get(url)
        
        data = response.json()
        
        for record in data['records']:
            last_updated = record.get('lastUpdated')
            

            
            division_id = leauge_dict.get(record.get('division', {}).get('id'))
            division_team_list = []
            for division in record['teamRecords']:
                
                
                    
                
                for item in division.get("records", {}).get("splitRecords"):
                    if item.get('type') == 'lastTen':
                        last_ten_wins = item.get('wins')
                        last_ten_losses = item.get('losses')
                        
                    if item.get('type') == 'home':
                        home_wins = item.get('wins')
                        home_losses = item.get('losses')
                        
                    if item.get('type') == 'away':
                        away_wins = item.get('wins')
                        away_losses = item.get('losses')
                        
                get_teams(division.get("team", {}).get('id'))
                team_standings = {
                # 'division_id': division_id,
                
                'team_name': division.get("team", {}).get('name'),
                'team_id': division.get("team", {}).get('id'),

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
                }
                
                # print(team_standings)
                division_team_list.append(team_standings) 
           
            division_standings_list[ division_id] = division_team_list 

    
    standings = {'standings': division_standings_list, 'team_abbreviation': team_abbreviation_list, 'last_updated': last_updated}

    save_off_results(standings, save_as)

    # Also update the teams.json file to include these abbreviations
    from util import load_json_file
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


def main():
    parser = argparse.ArgumentParser(description='Fetch MLB standings for a specific season or date')
    parser.add_argument('--season', '-s', type=int, default=datetime.now().year,
                        help='Season year (e.g., 2024, 2023). Default is current year.')
    parser.add_argument('--date', '-d', type=str,
                        help='Specific date for standings (format: YYYY-MM-DD or MM/DD/YYYY).')

    args = parser.parse_args()

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
            print(f'Error: Invalid date format. Please use YYYY-MM-DD or MM/DD/YYYY')
            return
    else:
        season = args.season
        print(f'Fetching standings for season: {season}')

    get_standings([103, 104], season=season, date=date_param)
    print(f'\nTeam abbreviations loaded: {len(team_abbreviation_list)} teams')
    print(f'Standings data saved to data/standings.json')

if __name__ == '__main__':
    main()


