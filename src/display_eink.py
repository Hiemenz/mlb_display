#!/usr/bin/python3
# -*- coding:utf-8 -*-

import sys
import os

from regex import F
import json

import random


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
from waveshare_epd import epd7in5_V2
import time
from PIL import Image, ImageDraw, ImageFont
import traceback


logging.basicConfig(level=logging.DEBUG)

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


    # magic string to account for extra innings
    if int(data_linescore.get('current_inning', 0)) > 9:
        start_inning = int(data_linescore.get('current_inning')) - 8
    else:
        start_inning = 1

    inning_header = [ i + start_inning for i in range(9)] + ['R', 'H', 'E']

    home_team = standings_data.get('team_abbreviation').get(str(game_info.get('home_team_id')))
    away_team = standings_data.get('team_abbreviation').get(str(game_info.get('away_team_id')))
    
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
    }
    
    Himage = generate_image(Himage, col_start, row_start, away_team, home_team, away,
                            home, game_state, inning_header, first_base, second_base,
                            third_base, outs, start_time, home_is_winner, away_probable,
                            home_probable, winner_name, loser_name, venue,
                            home_team_win_probability, away_team_win_probability)
    return Himage, new_image_dict

def draw_boards():
    
    new_image_dict = {}
    config_data = load_json_file('config.json')
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
    else: 
        print('image is different')
        
        Himage.save('temp.bmp') 
        display_image(Himage)
        
        save_off_results(new_image_dict, "old_image_state")
        print('saving off image...')
        
    

def generate_image(Himage, col_start, row_start, away_team, home_team, away,
                   home, game_state, inning_header, first_base, second_base, 
                   third_base, outs, start_time, home_is_winner, away_probable,
                   home_probable,winner_name, loser_name,  venue,
                            home_team_win_probability, away_team_win_probability):
    draw = ImageDraw.Draw(Himage)

    # bmp = Image.open(os.path.join('/home/pi/Documents/e-Paper/RaspberryPi_JetsonNano/python/examples/', 'qr.jpg'))
    # Himage.paste(bmp, (0,0))
    font24 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 24)
    font18 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)
    
    draw.text(( col_start + 460 , row_start + 93), venue, font = font18, fill = 0)
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




def display_image(image_to_display):
    try:

        # logging.info("epd7in5_V2 Demo")
        epd = epd7in5_V2.EPD()
        
        logging.info("init and Clear")
        epd.init_fast()
        # epd.Clear()

        logging.info("1.Drawing on the Horizontal image...")
        
        epd.display(epd.getbuffer(image_to_display))
        image_to_display.save('resulting_image.bmp') 
        # image_to_display.save('/Users/kevinhiemenz/Documents/python/mlb_display/resulting_image.bmp')


        time.sleep(2)

    except IOError as e:
        logging.info(e)
        
    except KeyboardInterrupt:    
        logging.info("ctrl + c:")
        epd7in5_V2.epdconfig.module_exit()
        exit()
    finally:
        logging.info("Goto Sleep...")
        epd.sleep()

draw_boards()



