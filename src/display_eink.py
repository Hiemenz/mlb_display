#!/usr/bin/python3
# -*- coding:utf-8 -*-

import os
import platform
import json
import logging
from PIL import Image

from util import load_json_file, load_yaml_file

# Only import waveshare hardware drivers on non-Darwin platforms
if platform.system() != 'Darwin':
    try:
        from waveshare_epd import epd7in5_V2
    except Exception as e:
        logging.warning(f"Could not import waveshare_epd: {e}")
        epd7in5_V2 = None
else:
    epd7in5_V2 = None


def display_image(image_to_display, output_filename='resulting_image.bmp'):
    """
    Display image on e-ink display.
    On Darwin (macOS), only saves the image file without attempting hardware display.
    On other platforms (Linux/Raspberry Pi), updates the physical e-ink display.

    Args:
        image_to_display: PIL Image object to display
        output_filename: Filename to save the image (default: 'resulting_image.bmp')
    """
    system_platform = platform.system()

    # Always save the image file
    image_to_display.save(output_filename)
    print(f"Image saved to {output_filename}")

    # Skip e-ink display update on Darwin (macOS)
    if system_platform == 'Darwin':
        print(f"Running on {system_platform} - skipping e-ink display update (hardware not available)")
        return

    # Update physical e-ink display on non-Darwin platforms
    if epd7in5_V2 is None:
        print(f"Running on {system_platform} - e-ink display module not available")
        return

    try:
        print(f"Running on {system_platform} - updating e-ink display")
        epd = epd7in5_V2.EPD()

        logging.info("init and Clear")
        epd.init()
        # epd.Clear()

        logging.info("Drawing on the Horizontal image...")

        epd.display(epd.getbuffer(image_to_display))

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
    system_platform = platform.system()
    print(f"Running on platform: {system_platform}")

    data = load_json_file('linescore.json')
    config_data = load_yaml_file('config.yaml')

    # this is bad but i designed this two different ways
    if data.get('update_display') and not config_data.get('scoreboard'):

        display_image(Image.open('temp.bmp'))

if __name__ == '__main__':
    main()
