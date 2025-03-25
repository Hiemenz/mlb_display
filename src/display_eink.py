#!/usr/bin/python3
# -*- coding:utf-8 -*-

import os
from waveshare_epd import epd7in5_V2
import json
import logging
from PIL import Image

from util import load_json_file


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

    except IOError as e:
        logging.info(e)
        
    except KeyboardInterrupt:    
        logging.info("ctrl + c:")
        epd7in5_V2.epdconfig.module_exit()
        exit()
    finally:
        logging.info("Goto Sleep...")
        epd.sleep()



def main():
    data = load_json_file('linescore.json')
    config_data = load_json_file('config.json', 'config/')
        
    # this is bad but i designed this two different ways
    if data.get('update_display') and not config_data.get('scoreboard'):

        display_image(Image.open('temp.bmp'))

if __name__ == '__main__':
    main()
