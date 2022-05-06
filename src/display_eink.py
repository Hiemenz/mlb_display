#!/usr/bin/python3
# -*- coding:utf-8 -*-
import sys
import os

from regex import F
picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')
libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')


if os.path.exists(libdir):
    sys.path.append(libdir)

import logging
from waveshare_epd import epd7in5_V2
import time
from PIL import Image, ImageDraw, ImageFont
import traceback

import game_data
logging.basicConfig(level=logging.DEBUG)

    

def draw_boards():
    epd = epd7in5_V2.EPD()
    Himage = Image.new('1', (epd.width, epd.height), 255)  # 255: clear the frame
    col_start = 100
    row_start = 40
    away_team, home_team, away, home, game_state, inning_header = game_data.get_team_box_score()

    if away_team != 'Not Found':
        Himage = generate_image(Himage, col_start, row_start, away_team, home_team, away, home, game_state, inning_header)
    else:
        away_team, home_team, away, home, game_state, inning_header = game_data.get_team_box_score('RIV')
        if away_team != 'Not Found':
            Himage = generate_image(Himage, col_start, row_start, away_team, home_team, away, home, game_state, inning_header)
    
    col_start = 100
    row_start = 180
    away_team, home_team, away, home, game_state, inning_header = game_data.get_team_box_score('ALT')

    if away_team != 'Not Found':
        Himage = generate_image(Himage, col_start, row_start, away_team, home_team, away, home, game_state, inning_header)


    # col_start = 100
    # row_start = 320
    # away_team, home_team, away, home, game_state, inning_header = game_data.get_team_box_score('RIV')

    # if away_team != 'Not Found':
    #     Himage = generate_image(Himage, col_start, row_start, away_team, home_team, away, home, game_state, inning_header)
    
    Himage = generate_standings(Himage, col_start=180, row_start=320)
    display_image(Himage)


def generate_standings(Himage, col_start=0, row_start=0):
    standings = game_data.get_standings()
    font24 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 24)
    font18 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)
    draw = ImageDraw.Draw(Himage)
    # draw.text((0 + col_start, 0 + row_start), standings[0], font = font18, fill = 0) 

    space = [0, 50, 210, 260, 310, 370,420,450,500 ]
    # standings = ['Rank', 'Team', 'W', 'L', 'GB',  '(E#)', 'WC Rank', 'WC GB', '(E#)'] + standings[1:]
    for i, item in enumerate(standings):
        
        [draw.text((space[k] + col_start, i * 23 + row_start), part, font = font18, fill = 0) for k, part in enumerate(item)]
        
    return Himage


def generate_image(Himage, col_start, row_start, away_team, home_team, away, home, game_state, inning_header):
    draw = ImageDraw.Draw(Himage)

    # bmp = Image.open(os.path.join('/home/pi/Documents/e-Paper/RaspberryPi_JetsonNano/python/examples/', 'qr.jpg'))
    # Himage.paste(bmp, (0,0))
    font24 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 24)
    font18 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)

    draw.text((0 + col_start, 8 + row_start), game_state, font = font18, fill = 0)
    draw.text((25 + col_start, 30 + row_start), away_team, font = font24, fill = 0)
    draw.text((25 + col_start, 60 + row_start), home_team, font = font24, fill = 0)
    
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

            draw.text((115 + sub_header + (40*i) + col_start, 0 + row_start), str(inning_header[i]), font = font24, fill = 0)
            draw.text((115 + sub_away + (40*i) + col_start, 30 + row_start), str(away[i]), font = font24, fill = 0)
            draw.text((115 + sub_home + (40*i) + col_start, 60 + row_start), str(home[i]), font = font24, fill = 0)
        
        # vertical line
        draw.line((100 + (40*i) + col_start, 0 + row_start, 100 + (40*i) + col_start, 90 + row_start), fill = 0)
    return Himage

def display_image(image_to_display):


    try:

        logging.info("epd7in5_V2 Demo")
        epd = epd7in5_V2.EPD()
        
        logging.info("init and Clear")
        epd.init()
        epd.Clear()

        

        logging.info("1.Drawing on the Horizontal image...")
        
        epd.display(epd.getbuffer(image_to_display))
        image_to_display.save('/home/pi/Documents/copy/RaspberryPi_JetsonNano/python/examples/test.bmp') 
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
