
from datetime import datetime, timedelta

import requests
import json
import os 
import pytz

BASE_URL = 'https://statsapi.mlb.com'

def load_json_file(file_name):
    data_dict = {}
    if not os.path.isfile(file_name):
        return data_dict
    with open(file_name, 'r') as file:
        data_dict = json.load(file)
        return data_dict

    
def save_off_results(data, output):
    with open( output + '.json', 'w') as f:
        json.dump(data, f, indent=4)
        
def convert_time_z_to(utc_time_str, time_zone='America/Chicago'):
    utc_time = datetime.strptime(utc_time_str, "%Y-%m-%dT%H:%M:%SZ")

    utc_time = pytz.utc.localize(utc_time)

    cst_timezone = pytz.timezone(time_zone)

    cst_time = utc_time.astimezone(cst_timezone)

    cst_hour_minutes = cst_time.strftime("%-I:%M %p")
    return cst_hour_minutes


def parse_games(data):
    game_dates = data.get('dates', {})
    games = game_dates[0].get('games')
    
    standings_dict = load_json_file('standings.json')
    team_abb_to_game_id_dict = {}
    
    game_list = {}
    for game in games:
        game_id = game.get('gamePk')
        game_dict = {
            'away_team_name': game.get('teams', {}).get('away', {}).get('team', {}).get('name'),
            'away_team_id': game.get('teams', {}).get('away', {}).get('team', {}).get('id'),
            'away_team_is_winner': game.get('teams', {}).get('away', {}).get('isWinner'),         
            'away_team_series_number': game.get('teams', {}).get('away', {}).get('seriesNumber'),
            
            'home_team_name': game.get('teams', {}).get('home', {}).get('team', {}).get('name'),
            'home_team_id': game.get('teams', {}).get('home', {}).get('team', {}).get('id'),
            'home_team_is_winner': game.get('teams', {}).get('home', {}).get('isWinner'),     
            'home_team_series_number': game.get('teams', {}).get('home', {}).get('seriesNumber'), 
            
            'double_header': game.get('doubleHeader'), 
            
            'series_description': game.get('seriesDescription'), 
            'day_night': game.get('dayNight'), 
            'description': game.get('description'), 
            'game_number': game.get('gameNumber'), 
            'games_in_series': game.get('gamesInSeries'), 
            'game_date': game.get('gameDate'), 
            'game_start': convert_time_z_to(game.get('gameDate')),
            'detailed_state': game.get('status', {}).get('detailedState'), 
            }
           
            
        print(game.get('teams', {}).get('away', {}).get('team', {}).get('name'))
        print(game.get('teams', {}).get('home', {}).get('team', {}).get('name'))


        extra_key = ''
        if game.get('doubleHeader') == 'Y' and game.get('gameNumber') == 2:
            extra_key = '_Double'
        
        team_id = game.get('teams', {}).get('away', {}).get('team', {}).get('id')
        away_abbrevation = standings_dict.get('team_abbreviation',{}).get(str(team_id))
        
        team_id = game.get('teams', {}).get('home', {}).get('team', {}).get('id')
        home_abbrevation = standings_dict.get('team_abbreviation',{}).get(str(team_id))


        
        team_abb_to_game_id_dict[away_abbrevation + extra_key] =  str(game.get('gamePk') )

        team_abb_to_game_id_dict[home_abbrevation + extra_key] =  str(game.get('gamePk'))

        game_list[game_id] = game_dict
        
        
        games_scheduled = {'games_scheduled': game_list, 'team_to_game_id': team_abb_to_game_id_dict}
        save_off_results(games_scheduled, 'games_scheduled')
        

def check_if_games_in_progress(data):
    if data.get('totalGamesInProgress') > 0:
        print(f'{data.get('totalGamesInProgress')} games in progress.')
    else:
        print('No games in progress.')    
    
def pad_innings(innings):
    while len(innings) < 9:
        innings.append(None)
        
        
        
    return innings[-9::]
        
    
        
def parse_linescore(data):
    
    
    
    inning_list = []
    
    away_runs = []
    home_runs = []
    
    for inning in data.get('innings', {}):
        
        away_runs.append(inning.get('away', {}).get('runs'))
        home_runs.append(inning.get('home', {}).get('runs'))
        
        inning_dict = {
            
            'inning_num': inning.get('num'),
            
            
            
            'home_runs': inning.get('home', {}).get('runs'),
            'home_hits': inning.get('home', {}).get('hits'),
            'home_errors': inning.get('home', {}).get('errors'),
            'home_left_on_base': inning.get('home', {}).get('leftOnBase'),

            'away_runs': inning.get('away', {}).get('runs'),
            'away_hits': inning.get('away', {}).get('hits'),
            'away_errors': inning.get('away', {}).get('errors'),
            'away_left_on_base': inning.get('away', {}).get('leftOnBase'),
        }
        inning_list.append(inning_dict)
        
    away_runs = pad_innings(away_runs)
    home_runs = pad_innings(home_runs)
    
    
    linescore_dict = {
        'runner_first': data.get('offense', {}).get('first',{}).get('fullName'),
        'runner_second': data.get('offense', {}).get('second',{}).get('fullName'),
        'runner_third': data.get('offense', {}).get('third',{}).get('fullName'),
        'current_inning_ordinal': data.get('currentInningOrdinal'),
        'current_inning': data.get('currentInning', 0),
        'inning_half': data.get('inningHalf'),
        
        
        'home_runs': data.get('teams', {}).get('home', {}).get('runs'),
        'home_hits': data.get('teams', {}).get('home', {}).get('hits'),
        'home_errors': data.get('teams', {}).get('home', {}).get('errors'),
        
        'away_runs': data.get('teams', {}).get('away', {}).get('runs'),
        'away_hits': data.get('teams', {}).get('away', {}).get('hits'),
        'away_errors': data.get('teams', {}).get('away', {}).get('errors'),
        
        
        
        'balls': data.get('balls'),
        'strikes': data.get('strikes'),
        'outs': data.get('outs', 0),
        
        'away_runs_innings': away_runs,
        'home_runs_innings': home_runs,
        
        'innings': inning_list,
        
    }

    
    return linescore_dict
    
            
        
        
def get_linescore(game_id):
    url_endpoint = f'https://statsapi.mlb.com/api/v1/game/{game_id}/linescore'
    response = requests.get(url_endpoint)
    data = response.json()
    
    
    linescore_dict = parse_linescore(data)
    
    return linescore_dict
    
    

        

def get_games(game_date):
    url_endpoint = f'https://statsapi.mlb.com/api/v1/schedule?startDate={game_date}&endDate={game_date}&sportId=1'
    print(url_endpoint)

    response = requests.get(url_endpoint)
    data = response.json()
    parse_games(data)

    
    
def main():
    six_hours_ago = datetime.now() - timedelta(hours=6)

    get_games(six_hours_ago.date())
    
    config_data = load_json_file('config.json')
    
    
    games_scheduled_data = load_json_file('games_scheduled.json')
    
    linescore_dict = {}
    print(config_data)
    print(config_data.get('primary'))
    primary_game_id = games_scheduled_data.get('team_to_game_id').get(config_data.get('primary'))
    
    
    print(primary_game_id)
    primary_backup_game_id = games_scheduled_data.get('team_to_game_id', {}).get(config_data.get('primary_backup'), {})
    primary_backup_2_game_id = games_scheduled_data.get('team_to_game_id', {}).get(config_data.get('primary_backup_2'), {})
    
    if primary_game_id:
        linescore_dict[config_data.get('primary')] = get_linescore(primary_game_id)
    elif primary_backup_game_id:
        linescore_dict[config_data.get('primary_backup')] = get_linescore(primary_backup_game_id)
    elif primary_backup_2_game_id:
        linescore_dict[config_data.get('primary_backup_2')] = get_linescore(primary_backup_2_game_id)


    secondary_game_id = games_scheduled_data.get('team_to_game_id', {}).get(config_data.get('secondary'), {})
    secondary_backup_game_id = games_scheduled_data.get('team_to_game_id', {}).get(config_data.get('secondary_backup'), {})
    secondary_backup_2_game_id = games_scheduled_data.get('team_to_game_id', {}).get(config_data.get('secondary_backup_2'), {})
    

    if secondary_game_id:
        linescore_dict[config_data.get('secondary')] = get_linescore(secondary_game_id)
    elif secondary_backup_game_id:
        linescore_dict[config_data.get('secondary_backup')] = get_linescore(secondary_backup_game_id)
    elif secondary_backup_2_game_id:
        linescore_dict[config_data.get('secondary_backup_2')] = get_linescore(secondary_backup_2_game_id)
    
    
    save_off_results(linescore_dict, 'linescore')

    
    
main()