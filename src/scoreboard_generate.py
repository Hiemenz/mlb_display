
from generate_image import orchestrate_score_board

from datetime import datetime 
import json
import requests

from display_eink import display_image
from util import load_json_file, save_off_results
import pytz




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
    
    game_array = []
    game_list = {}
    for game in games:
        game_id = game.get('gamePk')

        detailed_state = game.get('status', {}).get('detailedState')
    
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
            'current_inning': game.get('linescore',{}).get('currentInning'),
            'currentInningOrdinal': game.get('linescore',{}).get('currentInningOrdinal'),
            'inningState': game.get('linescore',{}).get('inningState'),
            'winner_name': game.get('decisions',{}).get('winner',{}).get('fullName'),
            'loser_name': game.get('decisions',{}).get('loser',{}).get('fullName'),
            'num_of_outs': game.get('linescore',{}).get('outs'),
            'balls': game.get('linescore',{}).get('balls'),
            'strikes': game.get('linescore',{}).get('strikes'),
            'away_runs': game.get('linescore',{}).get('teams',{}).get('away',{}).get('runs'),
            'home_runs': game.get('linescore',{}).get('teams',{}).get('home',{}).get('runs'),
            'away_hits': game.get('linescore',{}).get('teams',{}).get('away',{}).get('hits'),
            'home_hits': game.get('linescore',{}).get('teams',{}).get('home',{}).get('hits'),
            'away_errors': game.get('linescore',{}).get('teams',{}).get('away',{}).get('errors'),
            'home_errors': game.get('linescore',{}).get('teams',{}).get('home',{}).get('errors'),
            'away_left_on_base': game.get('linescore',{}).get('teams',{}).get('away',{}).get('leftOnBase'),
            'home_left_on_base': game.get('linescore',{}).get('teams',{}).get('home',{}).get('leftOnBase'),
            'runner_on_first': game.get('linescore',{}).get('offense',{}).get('first',{}).get('fullName'),
            'runner_on_second': game.get('linescore',{}).get('offense',{}).get('second',{}).get('fullName'),
            'runner_on_third': game.get('linescore',{}).get('offense',{}).get('third',{}).get('fullName'),
            'away_team_record_wins': game.get('teams',{}).get('away',{}).get('leagueRecord',{}).get('wins'),
            'away_team_record_losses': game.get('teams',{}).get('away',{}).get('leagueRecord',{}).get('losses'),
            'home_team_record_wins': game.get('teams',{}).get('home',{}).get('leagueRecord',{}).get('wins'),
            'home_team_record_losses': game.get('teams',{}).get('home',{}).get('leagueRecord',{}).get('losses'),
            'no_hitter': game.get('flags',{}).get('noHitter'),
            'perfect_game': game.get('flags',{}).get('perfectGame'),
            'current_hitter': game.get('linescore',{}).get('offense',{}).get('batter', {}).get('fullName'),
            'current_pitcher': game.get('linescore',{}).get('defense',{}).get('pitcher', {}).get('fullName'),
            }

        game_array.append(game_dict)
        
    save_off_results( {'games': game_array}, 'games')

def read_json_file(file_name):
    """
    Reads a JSON file and returns the parsed JSON data.
    
    :param file_name: str, the name of the JSON file to read
    :return: dict or list, the parsed JSON data
    """
    try:
        with open(file_name, 'r') as file:
            data = json.load(file)
        return data
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        return None
    except FileNotFoundError:
        print("File not found")
        return None



def fetch_scoreboard_for_date(date):
    endpoint_url = (
        'https://statsapi.mlb.com/api/v1/schedule?'
        f'startDate={date}&endDate={date}&sportId=1&hydrate=decisions,probablePitcher(note),linescore,flags'
    )
    response = requests.get(endpoint_url)
    data = response.json()

    parse_games(data)
    
    

def scoreboard_generate(date_str, game_data):
    
    if game_data:
        parse_games(game_data)
    else:
        
          
        fetch_scoreboard_for_date(date_str)
    
    game_state_data = read_json_file('data/games.json')['games']
    team_data = read_json_file('data/teams.json')

    
    sccoreboard_image = orchestrate_score_board(game_state_data, team_data) 
    
    if sccoreboard_image:
        display_image(sccoreboard_image)
    
    
    
    
    
def main():
    # Get the current date
    now = datetime.now().date()
    
    date_str = now.strftime('%Y-%m-%d')
    
    fetch_scoreboard_for_date(date_str)
    # fetch_scoreboard_for_date('2024-07-26')
    
    game_state_data = read_json_file('data/games.json')['games']
    team_data = read_json_file('data/teams.json')

    
    sccoreboard_image =     orchestrate_score_board(game_state_data, team_data) 
    
    display_image(sccoreboard_image)

if __name__ == '__main__':
    main()