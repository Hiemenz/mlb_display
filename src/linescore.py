
from datetime import datetime, timedelta

import requests
import json
import os 
import pytz
from generate_image import draw_boards

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

def are_timestamps_separated_by(timestamp1, timestamp2, minutes):
    # Convert timestamp strings to datetime objects
    time_format = "%Y-%m-%dT%H:%M:%S"
    if not timestamp1:
        timestamp1 = timestamp2
        return True
        
    dt1 = datetime.strptime(timestamp1, time_format)
    dt2 = datetime.strptime(timestamp2, time_format)
    
    # Calculate the absolute difference between the two datetime objects
    time_diff = abs(dt2 - dt1)
    
    print(time_diff)
    
    # Check if the difference is greater than the specified duration
    return time_diff > timedelta(minutes=minutes)

def get_current_time():
    current_time = datetime.now()
    return current_time.strftime("%Y-%m-%dT%H:%M:%S")


def get_win_probability_events(game_id):
    url_endpoint = f'https://statsapi.mlb.com/api/v1/game/{game_id}/winProbability'
    response = requests.get(url_endpoint)
    data = response.json()
    
    if type(data) != list:
        return {}
    
    for item in data:
        temp_dict = {
            'home_team_win_probability': item.get('homeTeamWinProbability'), 
            'away_team_win_probability': item.get('awayTeamWinProbability'), 
            'home_team_win_probability_added': item.get('homeTeamWinProbabilityAdded'), 
            'leverage_index': item.get('leverageIndex'), 
            'result_event': item.get('result',{}).get('event'), 
            'result_description': item.get('result',{}).get('description'), 
        }
        
    return temp_dict


def get_weather_data(game_id):
    url_endpoint = f'https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live'
    
    data = load_json_file('games_scheduled.json')
    if data.get('games_scheduled', {}).get(str(game_id), {}).get('weather_condition'):
        weather_dict = {
            'weather_condition': data.get('games_scheduled', {}).get(str(game_id), {}).get('weather_condition'),
            'weather_temp': data.get('games_scheduled', {}).get(str(game_id), {}).get('weather_temp'),
            'weather_wind': data.get('games_scheduled', {}).get(str(game_id), {}).get('weather_wind'),
        }
        
    else:
        print(url_endpoint)
        response = requests.get(url_endpoint)
        data = response.json()
    
        weather_dict = {
            'weather_condition': data.get('gameData',{}).get('weather',{}).get('condition'),
            'weather_temp': data.get('gameData',{}).get('weather',{}).get('temp'),
            'weather_wind': data.get('gameData',{}).get('weather',{}).get('wind'),
        }
    
    return weather_dict
    
def parse_games(data):
    current_time  = get_current_time()
    
    game_dates = data.get('dates', {})
    games = game_dates[0].get('games')
    
    standings_dict = load_json_file('standings.json')
    team_abb_to_game_id_dict = {}
    
    game_list = {}
    for game in games:
        game_id = game.get('gamePk')

        detailed_state = game.get('status', {}).get('detailedState')
        weather_dict = get_weather_data(game_id)
    
        game_dict = {
            'away_team_name': game.get('teams', {}).get('away', {}).get('team', {}).get('name'),
            'away_team_id': game.get('teams', {}).get('away', {}).get('team', {}).get('id'),
            'away_team_is_winner': game.get('teams', {}).get('away', {}).get('isWinner'),         
            'away_probable': game.get('teams', {}).get('away', {}).get('probablePitcher',{}).get('fullName'),         
            'away_team_series_number': game.get('teams', {}).get('away', {}).get('seriesNumber'),
            'home_team_name': game.get('teams', {}).get('home', {}).get('team', {}).get('name'),
            'home_team_id': game.get('teams', {}).get('home', {}).get('team', {}).get('id'),
            'home_team_is_winner': game.get('teams', {}).get('home', {}).get('isWinner'),     
            'home_probable': game.get('teams', {}).get('home', {}).get('probablePitcher',{}).get('fullName'),         
            'home_team_series_number': game.get('teams', {}).get('home', {}).get('seriesNumber'), 
            'double_header': game.get('doubleHeader'), 
            'series_description': game.get('seriesDescription'), 
            'day_night': game.get('dayNight'), 
            'description': game.get('description'), 
            'game_number': game.get('gameNumber'), 
            'games_in_series': game.get('gamesInSeries'), 
            'game_date': game.get('gameDate'), 
            'game_start': convert_time_z_to(game.get('gameDate')),
            'detailed_state': detailed_state, 
            'venue': game.get('venue',{}).get('name'),
            'weather_condition':weather_dict.get('weather_condition'),
            'weather_temp':weather_dict.get('weather_temp'),
            'weather_wind':weather_dict.get('weather_wind'),
            'current_inning': game.get('linescore',{}).get('currentInning'),
            'winner_name': game.get('decisions',{}).get('winner',{}).get('fullName'),
            'loser_name': game.get('decisions',{}).get('loser',{}).get('fullName'),
            }

        extra_key = ''
        if game.get('doubleHeader') in ('Y', 'S') and game.get('gameNumber') == 2:
            extra_key = '_DOUBLE'
        
        team_id = game.get('teams', {}).get('away', {}).get('team', {}).get('id')
        away_abbrevation = standings_dict.get('team_abbreviation',{}).get(str(team_id))
        
        team_id = game.get('teams', {}).get('home', {}).get('team', {}).get('id')
        home_abbrevation = standings_dict.get('team_abbreviation',{}).get(str(team_id))

        team_abb_to_game_id_dict[away_abbrevation + extra_key] =  str(game.get('gamePk') )

        team_abb_to_game_id_dict[home_abbrevation + extra_key] =  str(game.get('gamePk'))

        game_list[game_id] = game_dict
        
        games_scheduled = {
            'games_scheduled': game_list,
            'team_to_game_id': team_abb_to_game_id_dict, 
            'last_updated_time': current_time,
            }
        
    save_off_results(games_scheduled, 'games_scheduled')
        
def check_if_games_in_progress(data):
    if data.get('totalGamesInProgress', 0) > 0:
        print(f'{data.get("totalGamesInProgress")} games in progress.')
    else:
        print('No games in progress.')    
    
def pad_innings(innings):
    while len(innings) < 9:
        innings.append(None)
    
    return innings[-9::]
        
        
def parse_linescore(data, probability_events_dict):
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
        'home_team_win_probability': probability_events_dict.get('home_team_win_probability'),
        'away_team_win_probability': probability_events_dict.get('away_team_win_probability'),
        'home_team_win_probability_added': probability_events_dict.get('home_team_win_probability_added'),
        'leverage_index': probability_events_dict.get('leverage_index'),
        'result_event': probability_events_dict.get('result_event'),
        'result_description': probability_events_dict.get('result_description'),
    }
    return linescore_dict
    
        
def get_linescore(game_id):
    url_endpoint = f'https://statsapi.mlb.com/api/v1/game/{game_id}/linescore'
    print(url_endpoint)
    response = requests.get(url_endpoint)
    data = response.json()
    
    probability_events_dict = get_win_probability_events(game_id)

    
    linescore_dict = parse_linescore(data, probability_events_dict)
    return linescore_dict
    
    
def get_player_name(person_id):
    url_endpoint = f'https://statsapi.mlb.com/api/v1/people/{person_id}'
    
    if person_id:
        data = requests.get(url_endpoint).json().get('people' )[0]
        print(url_endpoint)

        return data.get('fullName')
    return None
    

    
def get_games(game_date):
    url_endpoint = f'https://statsapi.mlb.com/api/v1/schedule?startDate={game_date}&endDate={game_date}&sportId=1&hydrate=decisions,probablePitcher(note),linescore'
    games_scheduled_data = load_json_file('games_scheduled.json')
    config_data = load_json_file('config.json')

    if are_timestamps_separated_by(games_scheduled_data.get('last_updated_time'), get_current_time() ,int(config_data.get('update_interval'))):
        print('it has been more than ')
        print(url_endpoint)
        response = requests.get(url_endpoint)
        data = response.json()
        parse_games(data)


def find_game_in_progress(avoid_game_id):
    
    games_scheduled = load_json_file('games_scheduled.json').get('games_scheduled', {})
    if not games_scheduled:
        return None
    # Initialize an empty list to hold games that are in progress
    games_in_progress = []

    # Iterate through each game in the games_scheduled dictionary
    for game_id, game_info in games_scheduled.items():
        # Check if the detailed_state of the game is "In Progress"
        if game_info.get('detailed_state') == "In Progress":
            # If the game is in progress, add it to the list
            games_in_progress.append((game_id, game_info))

    # Print out the games that are in progress
    print(len(games_in_progress))
    for game in games_in_progress:
        game_id, game_info = game
        print(f"Game ID: {game_id}, Away Team: {game_info['away_team_name']}, Home Team: {game_info['home_team_name']}")
        if avoid_game_id == game_id:
            continue
        return game_id
    
    return None 

def main():
    six_hours_ago = datetime.now() - timedelta(hours=6)
    get_games(six_hours_ago.date())
    config_data = load_json_file('config.json')
    games_scheduled_data = load_json_file('games_scheduled.json')
    
    linescore_dict = {}
    primary_game_id = games_scheduled_data.get('team_to_game_id', {}).get(config_data.get('primary'))
    primary_backup_game_id = games_scheduled_data.get('team_to_game_id', {}).get(config_data.get('primary_backup'), {})
    primary_backup_2_game_id = games_scheduled_data.get('team_to_game_id', {}).get(config_data.get('primary_backup_2'), {})
    loaded_json = load_json_file('linescore.json')
    
    
    primary_id = None
    if primary_game_id:
        primary_id = primary_game_id
        if games_scheduled_data.get('games_scheduled').get(primary_game_id).get('detailed_state') == 'In Progress' or not loaded_json.get(config_data.get('primary')):
            print('Game in progress')
            linescore_dict[config_data.get('primary')] = get_linescore(primary_game_id)
        else:
            print('Game not in progress')
            linescore_dict[config_data.get('primary')] = loaded_json.get(config_data.get('primary'))
    elif primary_backup_game_id:
        primary_id = primary_backup_game_id
        if games_scheduled_data.get('games_scheduled').get(primary_backup_game_id).get('detailed_state') == 'In Progress' or not loaded_json.get(config_data.get('primary_backup'), False):
            print('Game in progress')
            linescore_dict[config_data.get('primary_backup')] = get_linescore(primary_backup_game_id)
        else:
            print('Game not in progress')
            linescore_dict[config_data.get('primary_backup')] = loaded_json.get(config_data.get('primary_backup'))
    elif primary_backup_2_game_id:
        primary_id = primary_backup_2_game_id
        if games_scheduled_data.get('games_scheduled').get(primary_backup_2_game_id).get('detailed_state') == 'In Progress' or not loaded_json.get(config_data.get('primary_backup_2')):
            print('Game in progress')
            linescore_dict[config_data.get('primary_backup_2')] = get_linescore(primary_backup_2_game_id)
        else:
            print('Game not in progress')
            linescore_dict[config_data.get('primary_backup_2')] = loaded_json.get(config_data.get('primary_backup_2'))
        
    secondary_game_id = games_scheduled_data.get('team_to_game_id', {}).get(config_data.get('secondary'), {})
    secondary_backup_game_id = games_scheduled_data.get('team_to_game_id', {}).get(config_data.get('secondary_backup'), {})
    if config_data.get('secondary_backup') == "LIVE":
        secondary_backup_game_id = find_game_in_progress(primary_id)
        print(secondary_backup_game_id)
    secondary_backup_2_game_id = games_scheduled_data.get('team_to_game_id', {}).get(config_data.get('secondary_backup_2'), {})
    
    print(secondary_game_id)
    if secondary_game_id:
        if games_scheduled_data.get('games_scheduled').get(secondary_game_id).get('detailed_state') == 'In Progress'  or not loaded_json.get(config_data.get('secondary')):
            print('Game in progress')
            linescore_dict[config_data.get('secondary')] = get_linescore(secondary_game_id)
        else:
            print('Game not in progress')
            linescore_dict[config_data.get('secondary')] = loaded_json.get(config_data.get('secondary'))
       
    elif secondary_backup_game_id:
        if games_scheduled_data.get('games_scheduled').get(secondary_backup_game_id).get('detailed_state') == 'In Progress' or not loaded_json.get(config_data.get('secondary_backup')):
            print('Game in progress')
            linescore_dict[config_data.get('secondary_backup')] = get_linescore(secondary_backup_game_id)
            linescore_dict['live_game_id'] = secondary_backup_game_id
        # elif secondary_backup_game_id == 'LIVE':
        #     linescore_dict[config_data.get('secondary_backup')] = get_linescore(live_game_id)
        else:
            print('Game not in progress')
            linescore_dict[config_data.get('secondary_backup')] = loaded_json.get(config_data.get('secondary_backup'))
       
    elif secondary_backup_2_game_id:
        if games_scheduled_data.get('games_scheduled').get(secondary_backup_2_game_id).get('detailed_state') == 'In Progress' or not loaded_json.get(config_data.get('secondary_backup_2')):
            print('Game in progress')
            linescore_dict[config_data.get('secondary_backup_2')] = get_linescore(secondary_backup_2_game_id)
        else:
            print('Game not in progress')
            linescore_dict[config_data.get('secondary_backup_2')] = loaded_json.get(config_data.get('secondary_backup_2'))
    
    save_off_results(linescore_dict, 'linescore')
    
    draw_boards()
    
main()
