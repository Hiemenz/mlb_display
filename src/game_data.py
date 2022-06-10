
import yaml
import json

tags_dict = ''

with open("/Users/kevinhiemenz/Documents/python/mlb_display/src/tags.yaml", "r") as stream:
    try:
        tags_dict = yaml.safe_load(stream)
        # print(tags_dict)
    except yaml.YAMLError as exc:
        print(exc) 

import requests
from bs4 import BeautifulSoup
  
URL = tags_dict['end_point']
r = requests.get(URL)
  
soup = BeautifulSoup(r.content, 'html5lib') 
results = []
# print(soup.prettify())
def orchastrate():

    # getting all_the_games
    game_container_divs = get_games()

    # print(game_container_divs[0].prettify())
    for game in game_container_divs:
        game_state_active, game_state_not_active, game_state_time = get_game_state(game)

        if game_state_active:
            # going on
            outs = game.find_all("svg", {"class": tags_dict['game_state_outs']})
            print(outs[0].title.text)

            if game_state_active[0].text != 'Warmup':
                game_state = game_state_active[0].text + '  O: ' + outs[0].title.text[0] 
            else:
                game_state = game_state_active[0].text 
            game_live_finished(game, game_state)

        elif game_state_not_active:
            # final
            game_state = game_state_not_active[0].text
            game_live_finished(game, game_state)

        else:
            game_state =  game_state_time[0].text
            away_team, home_team = get_team_names(game)
            store_data(game_state, [ i + 1 for i in range(9)] + ['R', 'H', 'E'], 
                away_team, [ '' for i in range(9)], '', ['',''],
                home_team, [ '' for i in range(9)], '', ['','']
            )

    for item in results:
        # json_object = json.load(item)

        json_formatted_str = json.dumps(item, indent=2)

        print(json_formatted_str)


def get_team_box_score(team='DEFAULT'):
    if team == 'DEFAULT':
        featured_team = tags_dict['featured_team']
    elif team == 'ALT':
        featured_team = tags_dict['alt_team']
    
    elif team == 'RIV':
        featured_team = tags_dict['rival_team']
    else:
        featured_team = team

    for game in results:
        if game['away_team'] == featured_team or game['home_team'] == featured_team:
            away_line = game['away_line_score'][-9:] + [game['away_score']] + game['away_hits_errors']
            home_line = game['home_line_score'][-9:] + [game['home_score']] + game['home_hits_errors']

            return game['away_team'], game['home_team'], away_line, home_line, game['game_state'], game['inning_header']
    return 'Not Found', 2, 3, 4, 5, 6


def get_games():
    return soup.find_all("div", {"class": tags_dict['game_container']})


def get_game_state(game):
    game_state_active = game.find_all("div", {"class": tags_dict['game_state_active']})
    game_state_not_active = game.find_all("span", {"class": tags_dict['game_state_not_active']})
    game_state_time = game.find_all("div", {"class": tags_dict['game_state_time']})
    return game_state_active, game_state_not_active, game_state_time


def get_team_names(game):
    teams = game.find_all("div", {"class": tags_dict['short_name']})
    away_team = teams[0].text
    home_team = teams[1].text
    return away_team, home_team


def store_data(
    game_state,
    inning_header,
    away_team,
    away_line_score, 
    away_score, 
    away_hits_errors, 
    home_team, 
    home_line_score, 
    home_score, 
    home_hits_errors):
    print(game_state)
    print(away_team, away_line_score, away_score, away_hits_errors)
    print(home_team, home_line_score, home_score, home_hits_errors)

    data = {
            "game_state": game_state,
            "inning_header": inning_header,

            "away_team": away_team,
            "away_line_score": away_line_score, 
            "away_score": away_score,
            "away_hits_errors": away_hits_errors,

            "home_team":home_team,
            "home_line_score": home_line_score,
            "home_score": home_score,
            "home_hits_errors": home_hits_errors 
        }
    results.append(data)

def game_live_finished(game, game_state):
    away_team, home_team = get_team_names(game)

    away_line_scores = game.find_all("div", {"class": tags_dict['away_line_scores']})
    home_line_scores = game.find_all("div", {"class": tags_dict['home_line_scores']})
    
    away_line_score = [score.text for score in away_line_scores]
    home_line_score = [score.text for score in home_line_scores]

    innings = len(away_line_score)
    inning_header = [i for i in range(innings - 8, innings + 1)] + ['R', 'H', 'E']

    try:
        # print(game)
        away_score = game.find("div", {"class": tags_dict['away_score']}).text
        away_hits_errors = game.find_all("div", {"class": tags_dict['away_hits_errors']})
        # print(away_hits_errors)
        away_hits_errors = [item.text for item in away_hits_errors[0:2]]
            
        # multiple returned here 2nd and 3rd items are good
        home_score = game.find_all("div", {"class": tags_dict['home_score']})[1].text
        home_hits_errors = game.find_all("div", {"class": tags_dict['home_hits_errors']})
        home_hits_errors = [item.text for item in home_hits_errors[0:2]]
        store_data( game_state, inning_header, away_team, away_line_score,  away_score,  away_hits_errors,  home_team,  home_line_score,  home_score,  home_hits_errors)
    except:
        print(away_team)
        print(home_team)
        store_data(game_state, [ i + 1 for i in range(9)] + ['R', 'H', 'E'], 
                away_team, [ '' for i in range(9)], '', ['',''],
                home_team, [ '' for i in range(9)], '', ['','']
            )


def get_mlb_standings():

    r = requests.get(tags_dict['url_standings'])
    
    standings = BeautifulSoup(r.content, 'lxml')
    print(standings)

    results = standings.find_all("div", {"class": tags_dict['division_containers_class']})
    
    standing_teams_name = []
    standing_teams_values = []
    [standing_teams_name.append(item.find("span", {"class": tags_dict['get_long_name']}).text)
     for item in results]
    
    table_standings = standings.find_all(
        "div", {"class": tags_dict['table_standings']})
    
    for table_standing in table_standings:
        values = table_standing.find_all(
            "tr", {"class": tags_dict['team_values']})
        for value in values:
            team_stats = []
            col_values = value.find_all("td", {"class": tags_dict["col_values"]})
            [team_stats.append(item.text) for item in col_values]
            standing_teams_values.append(team_stats)

    for item in standing_teams_values:
        if item[0] == 'W':
            standings_header = item
            standing_teams_values.remove(item)
    for team in range(len(standing_teams_name)):
        print(standing_teams_name[team])
        print(standing_teams_values[team])
    return standing_teams_name, standing_teams_values, standings_header

def save_off_scores():
    pass


def did_game_state_change():
    pass


def get_active_game():
    pass


orchastrate()
# get_mlb_standings()
