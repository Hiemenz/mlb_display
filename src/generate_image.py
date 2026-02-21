
import sys
import os

import json

import random
from util import load_json_file, load_yaml_file, save_off_results
from collections import OrderedDict

standings_dict = {
    1: 'American League East',
    2: 'American League Central',
    3: 'American League West',
    4: 'National League East',
    5: 'National League Central',
    6: 'National League West',
}

picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')
libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')

if os.path.exists(libdir):
    sys.path.append(libdir)

EPD_WIDTH = 800
EPD_HEIGHT = 480

import logging
import time
from PIL import Image, ImageDraw, ImageFont
import traceback



# logging.basicConfig(level=logging.DEBUG)

def normalize_dict(d):
    for key, value in d.items():
        if value is None:
            d[key] = ''  # Convert None to ''
        elif isinstance(value, list):
            d[key] = [item if item is not None else '' for item in value]  # Convert None to '' in lists
        elif isinstance(value, dict):
            d[key] = normalize_dict(value)  # Recursively normalize nested dictionaries
    return d


def generate_linescore(col_start, row_start, team_abbr, Himage, new_image_dict):
    
    data_linescore = load_json_file('linescore.json').get(team_abbr)
    data = load_json_file('games_scheduled.json')
    standings_data = load_json_file('standings.json')
    
    if team_abbr == 'LIVE':
        game_id = load_json_file('linescore.json').get('live_game_id')
    else: 
        game_id = data.get('team_to_game_id').get(team_abbr)
    
    game_info = data.get('games_scheduled').get(game_id)
    away_probable = game_info.get('away_probable')
    home_probable = game_info.get('home_probable')
    winner_name = game_info.get('winner_name')
    loser_name = game_info.get('loser_name')
    venue = game_info.get('venue')
    home_team_win_probability = str(data_linescore.get('home_team_win_probability'))[:4] + '%'
    away_team_win_probability = str(data_linescore.get('away_team_win_probability'))[:4] + '%'
    
    result_event = data_linescore.get('result_event')
    
    weather_condition = game_info.get('weather_condition',)
    weather_temp = game_info.get('weather_temp',)
    weather_wind = game_info.get('weather_wind',)
    
    # result_event = 'temp'
    # weather_condition =  'temp'
    # weather_temp = 'temp'
    # weather_wind = 'temp'


    # magic string to account for extra innings
    if int(data_linescore.get('current_inning', 0)) > 9:
        start_inning = int(data_linescore.get('current_inning')) - 8
    else:
        start_inning = 1

    inning_header = [ i + start_inning for i in range(9)] + ['R', 'H', 'E']

    # Handle missing team abbreviations gracefully for linescore
    home_team_id = str(game_info.get('home_team_id'))
    away_team_id = str(game_info.get('away_team_id'))

    home_team = standings_data.get('team_abbreviation', {}).get(home_team_id, f'T{home_team_id}')
    away_team = standings_data.get('team_abbreviation', {}).get(away_team_id, f'T{away_team_id}')
    
    away = data_linescore.get('away_runs_innings') + [data_linescore.get('away_runs'),data_linescore.get('away_hits'),data_linescore.get('away_errors')]
    home = data_linescore.get('home_runs_innings') + [data_linescore.get('home_runs'),data_linescore.get('home_hits'),data_linescore.get('home_errors')]
    game_state = game_info.get('detailed_state')
    start_time = game_info.get('game_start')

    home_is_winner = None
    if game_info.get('away_team_is_winner'):
        home_is_winner = 'L'
    elif game_info.get('home_team_is_winner'):
        home_is_winner = 'W'

        

    if (game_state == 'Final' or game_state == 'Game Over') and home[8] == None:
        home[8] = 'X'
        
    first_base = data_linescore.get('runner_first')
    second_base = data_linescore.get('runner_second')
    third_base = data_linescore.get('runner_third', None)
    outs = data_linescore.get('outs')
    
    
    if game_state == 'In Progress' and  data_linescore.get('inning_half')[:3] == 'Top' and  outs == 3:
        game_state = 'Mid ' + data_linescore.get('current_inning_ordinal')
        
    if game_state == 'In Progress' and  data_linescore.get('inning_half')[:3] == 'Bot' and  outs == 3:
        game_state = 'End ' + data_linescore.get('current_inning_ordinal')
    
    if game_state == 'In Progress':
        game_state = data_linescore.get('inning_half')[:3] + ' ' + data_linescore.get('current_inning_ordinal')
        
    new_image_dict[team_abbr] = {
        'home_team': home_team,
        'away_team': away_team,
        'away': away,
        'home': home,
        'game_state': game_state,
        'start_time': start_time,
        'first_base': first_base,
        'second_base': second_base,
        'third_base': third_base,
        'outs': outs,
        'winner_name': winner_name,
        'loser_name': loser_name, 
        'result_event': result_event,
    }
    
    Himage = generate_image(Himage, col_start, row_start, away_team, home_team, away,
                            home, game_state, inning_header, first_base, second_base,
                            third_base, outs, start_time, home_is_winner, away_probable,
                            home_probable, winner_name, loser_name, venue,
                            home_team_win_probability, away_team_win_probability, 
                            result_event, weather_condition, weather_temp, weather_wind)
    return Himage, new_image_dict

def draw_boards():
    
    new_image_dict = {}
    config_data = load_yaml_file('config.yaml')
    linescore_data = load_json_file('linescore.json')
    # epd = epd7in5_V2.EPD()
    Himage = Image.new('1', (800, 480), 255)  # 255: clear the frame
    col_start = 100
    row_start = 40
    
    team_abbr = None
    if linescore_data.get(config_data.get('primary')):
        team_abbr = config_data.get('primary')
    elif linescore_data.get(config_data.get('primary_backup')):
        team_abbr = config_data.get('primary_backup')
    elif linescore_data.get(config_data.get('primary_backup_2')):
        team_abbr = config_data.get('primary_backup_2')
    
    
    
    if team_abbr:   
        Himage, new_image_dict = generate_linescore(col_start, row_start, team_abbr, Himage, new_image_dict)
    
    team_abbr = None
    if linescore_data.get(config_data.get('secondary')):
        team_abbr = config_data.get('secondary')
    elif linescore_data.get(config_data.get('secondary_backup')):
        
        team_abbr = config_data.get('secondary_backup')
        
    elif linescore_data.get(config_data.get('secondary_backup_2')):
        team_abbr = config_data.get('secondary_backup_2')
        
    col_start = 100
    row_start = 180
    if team_abbr:
        Himage, new_image_dict = generate_linescore(col_start, row_start, team_abbr, Himage, new_image_dict)

    Himage = generate_standings(Himage, col_start=100, row_start=320)
    
    data = load_json_file('old_image_state.json')
    
    
    n1 = normalize_dict(data)
    n2 = normalize_dict(new_image_dict)

    if n1 == n2:
        print('images the same')
        linescore_data['update_display'] = None

    else: 
        print('image is different')
        
        print('saving off image...')
        linescore_data['update_display'] = True
        save_off_results(new_image_dict, "old_image_state")
    Himage.save('temp.bmp') 
    if not data:
        save_off_results(new_image_dict, "old_image_state")
        

    save_off_results(linescore_data, "linescore")

        
        
        
    

def generate_image(Himage, col_start, row_start, away_team, home_team, away,
                   home, game_state, inning_header, first_base, second_base, 
                   third_base, outs, start_time, home_is_winner, away_probable,
                   home_probable,winner_name, loser_name,  venue,
                   home_team_win_probability, away_team_win_probability, result_event,
                    weather_condition, weather_temp, weather_wind):
    draw = ImageDraw.Draw(Himage)

    # bmp = Image.open(os.path.join('/home/pi/Documents/e-Paper/RaspberryPi_JetsonNano/python/examples/', 'qr.jpg'))
    # Himage.paste(bmp, (0,0))
    font24 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 24)
    font18 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)
    font14 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 14)
    

    
    if game_state not in ('Final', 'Game Over','Scheduled','Pre-Game','Delayed','Postponed', 'Warmup') :
        outs_list = [None] * 3
        
        for i in range(1,4):
            outs_list[i-1] =  i <= outs
            
        draw_circle(Himage, (col_start + 20 - 95, row_start + 82), 8, outs_list[0])  # Circle 1 filled
        draw_circle(Himage, (col_start + 45 - 95, row_start + 82), 8, outs_list[1]) # Circle 2 not filled
        draw_circle(Himage, (col_start + 70 - 95, row_start + 82), 8, outs_list[2]) # Circle 3 filled

        draw_diamond(Himage, (col_start + 70 - 95, row_start + 45), 20, first_base) # first base at (150, 100) with size 20
        draw_diamond(Himage, (col_start + 45 - 95, row_start + 20), 20, second_base) # second base 
        draw_diamond(Himage, (col_start + 20 - 95, row_start + 45), 20, third_base)  # third base 
        
        draw.text(( col_start + 585 , row_start + 63), home_team_win_probability, font = font24, fill = 0)
        draw.text(( col_start + 585 , row_start + 30), away_team_win_probability, font = font24, fill = 0)

        draw.text(( col_start + 0 , row_start + 93), result_event , font = font18, fill = 0)

    if home_is_winner == 'L':
        draw_circle(Himage, (col_start + 12, row_start + 45), 8, True) 
    elif home_is_winner == 'W':
        draw_circle(Himage, (col_start + 12, row_start + 75), 8, True) 

    if not away_probable:
        away_probable = ''    
    if not home_probable:
        home_probable = ''
        
    DISPLAY_PROBS = False
    
    if game_state in ('Scheduled', 'Pre-Game', 'Warmup'):
        innings = [None] * 12
        away, home = innings, innings
        if game_state != 'Warmup':
            game_state = start_time 
        DISPLAY_PROBS = True

        draw.text((25 + col_start + 82, 30 + row_start), away_probable, font = font24, fill = 0)
        draw.text((25 + col_start + 82, 60 + row_start), home_probable, font = font24, fill = 0)
        
    elif game_state in ('Final'):
        draw.text(( col_start + 0 , row_start + 93), f'WP: {winner_name}  LP: {loser_name}' , font = font18, fill = 0)
    
    draw.text((0 + col_start, 8 + row_start), game_state, font = font18, fill = 0)
    draw.text((25 + col_start, 30 + row_start), away_team, font = font24, fill = 0)
    draw.text((25 + col_start, 60 + row_start), home_team, font = font24, fill = 0)
    
    if game_state == 'Delayed Start':
        game_state = 'Delayed'    
         
    if weather_temp and weather_condition and weather_wind:
        draw.text(( col_start + 0 , row_start - 18), f'{weather_temp}°F | {weather_condition} | {weather_wind}', font = font14, fill = 0)
    draw.text(( col_start + 460 , row_start + 93), venue, font = font18, fill = 0)
    
    
    # lines horizontal
    draw.line((col_start, 30 + row_start, 580 + col_start, 30 + row_start), fill = 0)
    draw.line((col_start, 60 + row_start, 580 + col_start, 60 + row_start), fill = 0)
    draw.line((col_start, 90 + row_start, 580 + col_start, 90 + row_start), fill = 0)
    
    for i in range(13):
        # inning
        sub_header, sub_away, sub_home = 0,0,0
        if i < 12:
            
            
            if 1 < len(str(inning_header[i])):
                sub_header = -7
            if 1 < len(str(away[i])):
                sub_away = -7
            if 1 < len(str(home[i])):
                sub_home = -7
                
            if away[i] == None:
                away[i] = ''
                
            if home[i] == None:
                home[i] = ''

            draw.text((115 + sub_header + (40*i) + col_start, 0 + row_start), str(inning_header[i]), font = font24, fill = 0)
            draw.text((115 + sub_away + (40*i) + col_start, 30 + row_start), str(away[i]), font = font24, fill = 0)
            draw.text((115 + sub_home + (40*i) + col_start, 60 + row_start), str(home[i]), font = font24, fill = 0)
        
        # vertical line 
        if i >= 1 and i <= 8 and DISPLAY_PROBS:
            continue
        if i == 9 or i == 10:

            if i == 9:
                draw.line((100 + (40*i) + col_start, 0 + row_start + 88, 100 + (40*i) + 40 + col_start, +88 + row_start), fill = 0)
                draw.line((100 + (40*i) + col_start, 0 + row_start + 89, 100 + (40*i) + 40 + col_start, +89 + row_start), fill = 0)
            
            draw.line((101 + (40*i) + col_start, 0 + row_start, 101 + (40*i) + col_start, 90 + row_start), fill = 0)
            draw.line((102 + (40*i) + col_start, 0 + row_start, 102 + (40*i) + col_start, 90 + row_start), fill = 0)
            draw.line((103 + (40*i) + col_start, 0 + row_start, 103 + (40*i) + col_start, 90 + row_start), fill = 0)
        draw.line((100 + (40*i) + col_start, 0 + row_start, 100 + (40*i) + col_start, 90 + row_start), fill = 0)
    return Himage

def generate_standings(Himage, col_start=100, row_start=320):
    data = load_json_file('standings.json')
    
    ran_num = random.randint(1, 6)
    
    teams_in_division = data.get('standings').get(standings_dict.get(ran_num))
    
    
    # standings_list = [[name] + value for name, value in zip(standing_teams_name, standing_teams_values)]
    font24 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 24)
    font18 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)
    font15 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 15)
    draw = ImageDraw.Draw(Himage)

    # draw lines
    # 'W', 'L', 'PCT', 'GB', 'HOME', 'AWAY', 'RS', 'RA', 'DIFF', 'STRK', 'L10'
    for item in range(6):
        padding = item * 30
        draw.line((col_start, padding + row_start, 580 +
                  col_start, padding + row_start), fill=0)
        
    verticle_lines = [160, 200, 240, 290, 340, 395, 440, 510, 580]

    # verticle lines 
    for line in verticle_lines:
        draw.line((line + col_start, -20 + row_start,
                   line + col_start, 150 + row_start), fill=0)
    # draw text 
    row_start += 5
    padding = -30
    draw.text((0 + col_start, padding + row_start),
              'Team', font=font18, fill=0)
    # wins
    draw.text((verticle_lines[0] + 8 + col_start, padding + row_start),
              'W', font=font18, fill=0)
    # losses
    draw.text((verticle_lines[1] + 8 + col_start, padding + row_start),
              'L', font=font18, fill=0)
    # percentage
    draw.text((verticle_lines[2] + 8 + col_start, padding + row_start),
              'PCT', font=font18, fill=0)
    # games back
    draw.text((verticle_lines[3] + 8 + col_start, padding + row_start),
              'GB', font=font18, fill=0)
    # streak
    draw.text((verticle_lines[4] + 8 + col_start, padding + row_start),
              'STRK', font=font18, fill=0)
    # last 10
    draw.text((verticle_lines[5] + 8 + col_start, padding + row_start),
              'L10', font=font18, fill=0)
    # home record
    draw.text((verticle_lines[6] + 8 + col_start, padding + row_start),
              'Home', font=font18, fill=0)
    # away record
    draw.text((verticle_lines[7] + 8 + col_start, padding + row_start),
              'Away', font=font18, fill=0)
    
    for item, team in enumerate(teams_in_division):
        print(item, team.get('team_name'))
        padding = item * 30
        draw.text((0 + col_start, padding + row_start),
                  team.get('team_name'), font=font15, fill=0)
        # wins
        draw.text((verticle_lines[0] + 8 + col_start, padding + row_start),
                  str(team.get('league_record_wins')), font=font18, fill=0)
        # losses 
        draw.text((verticle_lines[1] + 8 + col_start, padding + row_start),
                  str(team.get('league_record_losses')), font=font18, fill=0)
    #     # percentage
        draw.text((verticle_lines[2] + 8 + col_start, padding + row_start),
                  str(team.get('league_record_percent')), font=font18, fill=0)
    #     # games back
        draw.text((verticle_lines[3] + 8 + col_start, padding + row_start),
                  str(team.get('games_back')), font=font18, fill=0)
    #     # streak
        draw.text((verticle_lines[4] + 8 + col_start, padding + row_start),
                  team.get('streak'), font=font18, fill=0)
    #     # last 10
        draw.text((verticle_lines[5] + 8 + col_start, padding + row_start),
                 f'{team.get("last_ten_wins")}-{team.get("last_ten_losses")}' , font=font18, fill=0)
    #     # home record
        draw.text((verticle_lines[6] + 8 + col_start, padding + row_start),
                  f'{team.get("home_wins")}-{team.get("home_losses")}', font=font18, fill=0)
    #     # away record
        draw.text((verticle_lines[7] + 8 + col_start, padding + row_start),
                  f'{team.get("away_wins")}-{team.get("away_losses")}', font=font18, fill=0)
    return Himage


def draw_diamond(Himage, center, size, fill=False):
    draw = ImageDraw.Draw(Himage)
    x, y = center
    diamond = [(x, y - size), (x + size, y), (x, y + size), (x - size, y)]
    
    if fill:
        draw.polygon(diamond,fill='black', outline='black')
    else :
        draw.polygon(diamond, outline='black')
    return Himage
        

# Function to draw a circle at a specific location with an option to fill
def draw_circle(Himage, center, radius, fill):
    draw = ImageDraw.Draw(Himage)

    x, y = center
    bounding_box = [x - radius, y - radius, x + radius, y + radius]  # Defines the square in which the circle will be drawn
    if fill:
        draw.ellipse(bounding_box, fill='black', outline='black')
    else:
        draw.ellipse(bounding_box, outline='black')
    return Himage

def check_if_two_chars(num):
    
    if len(str(num)) == 2:
        return -6
    return 0

def draw_box(Himage, start_x, start_y, game_data, team_data):
    draw = ImageDraw.Draw(Himage)
    font26 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 26)
    font24 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 24)
    font18 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)
    font14 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 14)
    font11 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 11)

    vertical_len = 110
    horizonta_len = 135
    max_text_width = horizonta_len - 14

    def fit_text(text, max_w):
        try:
            if font14.getlength(text) <= max_w:
                return text, font14
            if font11.getlength(text) <= max_w:
                return text, font11
            while text and font11.getlength(text) > max_w:
                text = text[:-1]
            return text, font11
        except AttributeError:
            return text[:17], font14

    # team names short
    away_team_id = str(game_data['away_team_id'])
    home_team_id = str(game_data['home_team_id'])

    # Handle missing team abbreviations gracefully
    away_team_name = team_data.get('team_abbreviation', {}).get(away_team_id, f'T{away_team_id}')
    home_team_name = team_data.get('team_abbreviation', {}).get(home_team_id, f'T{home_team_id}')
    
    # inning or game state
    if game_data['detailed_state'] == 'Final':
        # pitchers of record
        wp_str, wp_font = fit_text(f'WP: {game_data.get("winner_name") or ""}', max_text_width)
        lp_str, lp_font = fit_text(f'LP: {game_data.get("loser_name") or ""}', max_text_width)
        draw.text((start_x + 7 , start_y + 25 + 59), wp_str, font=wp_font, fill=0)
        draw.text((start_x + 7 , start_y + 25 + 74), lp_str, font=lp_font, fill=0)
        
    elif game_data['detailed_state'] == 'Warmup' or game_data['detailed_state'] == 'Pre-Game' or  game_data['detailed_state'] == 'Scheduled':
        away_prob = game_data.get("away_probable") or ''
        home_prob = game_data.get("home_probable") or ''
        away_prob, away_font = fit_text(away_prob, max_text_width)
        home_prob, home_font = fit_text(home_prob, max_text_width)
        draw.text((start_x + 7 , start_y + 25 + 59), away_prob, font=away_font, fill=0)
        draw.text((start_x + 7, start_y + 25 + 74), home_prob, font=home_font, fill=0)
    elif game_data['detailed_state'] == 'In Progress':
        # Show last play result if available, otherwise show pitcher/hitter
        last_play = game_data.get('last_play')
        if last_play:
            if len(last_play) > 45:
                last_play = last_play[:42] + '...'
            draw.text((start_x + 5, start_y + 25 + 59), 'Last:', font=font14, fill=0)
            draw.text((start_x + 5, start_y + 25 + 74), last_play, font=font14, fill=0)
        else:
            # Fallback to showing current matchup
            pitcher_str, pitcher_font = fit_text(f'P: {game_data.get("current_pitcher") or ""}', max_text_width)
            hitter_str, hitter_font = fit_text(f'AB: {game_data.get("current_hitter") or ""}', max_text_width)
            draw.text((start_x + 5, start_y + 25 + 74), pitcher_str, font=pitcher_font, fill=0)
            draw.text((start_x + 7, start_y + 25 + 89), hitter_str, font=hitter_font, fill=0)
        
    if game_data['detailed_state'] == 'Final' or  game_data['detailed_state'] == 'Postponed' or  game_data['detailed_state'] == 'Delayed' or  game_data['detailed_state'] == 'Game Over':
        game_state_str = game_data['detailed_state'] 
        
        
        if game_data.get('current_inning') != 9:
            game_state_str += '/' + str(game_data.get('current_inning'))
            
    elif game_data['detailed_state'] == 'Warmup':
        game_state_str = game_data['detailed_state'] 
        
        
    elif game_data['detailed_state'] == 'Scheduled'  or game_data['detailed_state'] == 'Pre-Game':
        game_state_str = game_data['game_start'] 
        
    else:
        extra = ''
        if game_data.get('inningState'):
            extra = game_data.get('inningState').upper()
        
        if game_data['inningState'] == 'Bottom':
            extra = 'Bot'.upper()
            
        if game_data['inningState'] == 'Middle':
            extra = 'Mid'.upper()
            

        game_state_str = extra + ' ' + str(game_data['current_inning'])
    
    # game state — bold via double draw; append last play on same line for live games
    draw.text((start_x + 5, start_y + 3), game_state_str, font=font14, fill=0)
    draw.text((start_x + 6, start_y + 3), game_state_str, font=font14, fill=0)
    if game_data['detailed_state'] == 'In Progress':
        raw_play = game_data.get('last_play') or ''
        if raw_play:
            inline_play = raw_play if len(raw_play) <= 11 else raw_play[:10] + '…'
            draw.text((start_x + 60, start_y + 5), inline_play, font=font11, fill=0)

    # Initialize score variables (will be used later for winner display)
    away_runs = str(game_data.get('away_runs', 0) if game_data.get('away_runs', 0) is not None else 0)
    home_runs = str(game_data.get('home_runs', 0) if game_data.get('home_runs', 0) is not None else 0)

    is_game_started = game_data['detailed_state'] in ['Final', 'Game Over', 'In Progress']
    is_game_finished = game_data['detailed_state'] in ['Final', 'Game Over']

    # Display score if game has started, otherwise show team records
    if is_game_started:
        draw.text((start_x + 66 + check_if_two_chars(away_runs), start_y + 25), away_runs, font=font24, fill=0)
        draw.text((start_x + 66 + check_if_two_chars(home_runs), start_y + 55), home_runs, font=font24, fill=0)

        if is_game_finished:
            # hits
            away_hits = str(game_data.get('away_hits', 0) if game_data.get('away_hits', 0) is not None else 0)
            home_hits = str(game_data.get('home_hits', 0) if game_data.get('home_hits', 0) is not None else 0)
            draw.text((start_x + 95 + check_if_two_chars(away_hits), start_y + 25),  away_hits, font=font24, fill=0)
            draw.text((start_x + 95 + check_if_two_chars(home_hits), start_y + 55), home_hits , font=font24, fill=0)

            # errors
            draw.text((start_x + 123, start_y + 25),  str(game_data.get('away_errors', 0) if game_data.get('away_errors', 0) is not None else 0), font=font24, fill=0)
            draw.text((start_x + 123 , start_y + 55),  str( game_data.get('home_errors', 0) if game_data.get('home_errors', 0) is not None else 0), font=font24, fill=0)

            # header (skip if perfect game or no-hitter to avoid overlap)
            if not game_data.get('perfect_game') and not game_data.get('no_hitter'):
                header = 'R     H     E'
                draw.text((start_x + 68, start_y + 3), header, font=font14, fill=0)
                draw.text((start_x + 69, start_y + 3), header, font=font14, fill=0)
    else:
        # Game hasn't started - show team records
        draw.text((start_x + 89, start_y + 31), f'{game_data.get("away_team_record_wins", "0")} - {game_data.get("away_team_record_losses", "0")}', font=font14, fill=0)
        draw.text((start_x + 89, start_y + 61), f'{game_data.get("home_team_record_wins", "0")} - {game_data.get("home_team_record_losses", "0")}', font=font14, fill=0)
        
    # horizontal line
    end_x = start_x + horizonta_len
    end_y = start_y
    draw.line((start_x, start_y, end_x, end_y), fill = 0)
    draw.line((start_x, start_y + 20, end_x, end_y  + 20), fill = 0)

    end_x = start_x + horizonta_len
    end_y = start_y + vertical_len
    # draw.line((start_x, start_y + vertical_len, end_x, end_y), fill = 0)
    
    
    # vertical line
    end_x = start_x
    end_y = start_y + vertical_len
    # draw.line((start_x, start_y, end_x, end_y), fill = 0)
    
    end_x = start_x + horizonta_len
    end_y = start_y + vertical_len
    # draw.line((start_x + horizonta_len , start_y, end_x, end_y), fill = 0)


    # line down the middle
    # vert_start_x =  start_x + horizonta_len / 2
    # vert_start_y = start_y + 12
    # end_x = vert_start_x
    # end_y = vert_start_y + 85
    
    # draw.line((vert_start_x, vert_start_y, end_x, end_y), fill = 0)
    

    # Show bases/outs/count if game is in progress (started but not finished)
    if is_game_started and not is_game_finished:
        # bases
        Himage = draw_diamond(Himage, (start_x + 22 + 75, start_y + 27 + 25), 10, isinstance(game_data['runner_on_third'], str))
        Himage = draw_diamond(Himage, (start_x + 34 + 75, start_y + 15 + 25), 10, isinstance(game_data['runner_on_second'], str))
        Himage = draw_diamond(Himage, (start_x + 46 + 75, start_y + 27 + 25), 10, isinstance(game_data['runner_on_first'], str))

        # outs
        outs_list = [None] * 3

        for i in range(1,4):
            outs_list[i-1] =  i <= game_data['num_of_outs']

        Himage = draw_circle(Himage, (start_x + 22 + 75, start_y + 25 + 48), 5, outs_list[0])
        Himage = draw_circle(Himage, (start_x + 34 + 75, start_y + 25 + 48), 5, outs_list[1])
        Himage = draw_circle(Himage, (start_x + 46 + 75, start_y + 25 + 48), 5, outs_list[2])

        balls_list = [None] * 4
        for i in range(1,4):
            balls_list[i-1] =  i <= game_data['balls']

        draw.text((start_x + 5 , start_y + 25 + 59), 'B', font=font14, fill=0)
        Himage = draw_circle(Himage, (start_x + 22 , start_y + 25 + 68), 4, balls_list[0])
        Himage = draw_circle(Himage, (start_x + 34, start_y + 25 + 68), 4, balls_list[1])
        Himage = draw_circle(Himage, (start_x + 46, start_y + 25 + 68), 4, balls_list[2])


        strikes_list = [None] * 3
        for i in range(1,3):
            strikes_list[i-1] =  i <= game_data['strikes']

        draw.text((start_x + 22 + 47, start_y + 25 + 59), 'S', font=font14, fill=0)
        Himage = draw_circle(Himage, (start_x + 22 + 63, start_y + 25 + 68), 4, strikes_list[0])
        Himage = draw_circle(Himage, (start_x + 34 + 63, start_y + 25 + 68), 4, strikes_list[1])
    else:

        # Perfect game takes precedence over no-hitter display
        if game_data.get('perfect_game'):
            draw.text((start_x + 50, start_y + 3), 'Perfect Game', font=font14, fill=0)
        elif game_data.get('no_hitter'):
            draw.text((start_x + 79, start_y + 3), 'No Hitter', font=font14, fill=0)

        


    # teams names
    draw.text((start_x + 5, start_y + 25), away_team_name, font=font24, fill=0)
    draw.text((start_x + 5 , start_y + 55), home_team_name, font=font24, fill=0)



    if game_data.get('away_team_is_winner'):
        draw.text((start_x + 7, start_y + 25), away_team_name, font=font24, fill=0)
        draw.text((start_x + 67 + check_if_two_chars(away_runs), start_y + 25), away_runs, font=font24, fill=0)

        
        # Himage = draw_circle(Himage, (start_x - 5, start_y + 25), 20, True)
    if game_data.get('home_team_is_winner'):
        draw.text((start_x + 7 , start_y + 55), home_team_name, font=font24, fill=0)
        draw.text((start_x + 67 + check_if_two_chars(home_runs), start_y + 55), home_runs, font=font24, fill=0)

        # Himage = draw_circle(Himage, (start_x -5, start_y + 55), 17, True)

        
    return Himage

def draw_out_of_town_score_board(Himage, game_state_data, team_data, date_str=None):

    draw = ImageDraw.Draw(Himage)

    # draw.line((col_start, 60 + row_start, 580 + col_start, 60 + row_start), fill = 0)
    # draw.line((col_start, 90 + row_start, 580 + col_start, 90 + row_start), fill = 0)
    x_start = 32
    y_start = 30

    game_list = game_state_data

    counter = 0
    for y in range(0,3):
        for x in range(0,5):
            if counter > len(game_list) - 1:
                continue
            if game_list[counter]:
                Himage = draw_box(Himage, x * 150 + x_start, y * 150 + y_start, game_list[counter], team_data)
            counter += 1

    # Add date in bottom right corner
    if date_str:
        font18 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)
        draw.text((690, 462), date_str, font=font18, fill=0)

    Himage.save('score_board.bmp')
    return Himage

def compare_json_dicts_sorted(dict1, dict2):
    """Compare two JSON dictionaries to see if they are equal, ignoring key order."""
    return json.dumps(dict1, sort_keys=True) == json.dumps(dict2, sort_keys=True)


def load_and_sort_json(json_string):
    """Load JSON data from a string and sort it."""
    return json.loads(json_string, object_pairs_hook=OrderedDict)

def  orchestrate_score_board(game_state_data, team_data, date_str=None):

    old_data = load_json_file('old_scoreboard_state.json')

    new_data_str = json.dumps(game_state_data)
    old_data_str = json.dumps(old_data)


    new_dict = load_and_sort_json(new_data_str)
    old_dict = load_and_sort_json(old_data_str)

    save_off_results(game_state_data, "old_scoreboard_state")

    if compare_json_dicts_sorted(new_dict, old_dict):
        print('images the same')
        return None

    print('image is different')
    Himage = Image.new('1', (800, 480), 255)
    Himage = draw_out_of_town_score_board(Himage, game_state_data, team_data, date_str)
    return Himage 
    