import requests
import json

    
def save_off_results(data, output):

    with open( output + '.json', 'w') as f:
        json.dump(data, f, indent=4)
        
        
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
    response = requests.get(f'https://statsapi.mlb.com/api/v1/teams/{team_id}')
        
    data = response.json()
    team_id = data.get('teams', {})[0].get('id')
    team_abbreviation = data.get('teams', {})[0].get('abbreviation')
    
    team_abbreviation_list[team_id] = team_abbreviation

        

def get_standings(league_id_list, season=2024):
    division_standings_list = {}
    for league_id in league_id_list:
        response = requests.get(f'https://statsapi.mlb.com/api/v1/standings?leagueId={league_id}&season={season}')
        
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
    # print(division_standings_list)
    
    
    standings = {'standings': division_standings_list, 'team_abbreviation':team_abbreviation_list ,'last_updated': last_updated, }
    
    save_off_results(standings, 'standings')
    
    
    
get_standings([103,104])


