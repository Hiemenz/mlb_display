#!/usr/bin/python3
# -*- coding:utf-8 -*-

import os
from waveshare_epd import epd7in5_V2
import json
import logging
from PIL import Image


def load_json_file(file_name):
    data_dict = {}
    if not os.path.isfile(file_name):
        return data_dict
    with open(file_name, 'r') as file:
        data_dict = json.load(file)
        return data_dict
   
   
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
    data = load_json_file('old_image_state.json')
        
    if data.get('update_display'):

        display_image(Image.open('temp.bmp'))


main()
