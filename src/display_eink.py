#!/usr/bin/python3
# -*- coding:utf-8 -*-

import os
import platform
import json
import logging
from PIL import Image

from util import load_json_file, load_yaml_file
from refresh_tracker import needs_full_refresh, record_full_refresh, record_partial_refresh

# Only import waveshare hardware drivers on non-Darwin platforms
if platform.system() != 'Darwin':
    try:
        from waveshare_epd import epd7in5_V2
    except Exception as e:
        logging.warning(f"Could not import waveshare_epd: {e}")
        epd7in5_V2 = None
else:
    epd7in5_V2 = None


def _getbuffer_partial(image):
    """Convert a cropped PIL Image of any size to an e-ink buffer.

    Unlike the driver's getbuffer() which requires exactly 800x480,
    this works with arbitrary region sizes for partial refresh.
    """
    img = image.convert('1')
    buf = bytearray(img.tobytes('raw'))
    for i in range(len(buf)):
        buf[i] ^= 0xFF
    return buf


def display_image(image_to_display, output_filename='resulting_image.bmp'):
    """
    Display image on e-ink display (full refresh).
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

    # Record that we did a full refresh
    record_full_refresh()

    # Skip e-ink display update on Darwin (macOS)
    if system_platform == 'Darwin':
        print(f"Running on {system_platform} - skipping e-ink display update (hardware not available)")
        return

    # Update physical e-ink display on non-Darwin platforms
    if epd7in5_V2 is None:
        print(f"Running on {system_platform} - e-ink display module not available")
        return

    try:
        print(f"Running on {system_platform} - updating e-ink display (full refresh)")
        epd = epd7in5_V2.EPD()

        logging.info("init and Clear")
        epd.init()

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


def display_partial_regions(full_image, regions, output_filename='resulting_image.bmp'):
    """
    Display only the changed regions using partial e-ink refresh.

    Args:
        full_image: Full 800x480 PIL Image
        regions: List of (x, y, w, h) tuples — regions to partially refresh.
                 x must be aligned to 8-pixel boundaries.
        output_filename: Filename to save the full image
    """
    system_platform = platform.system()

    # Always save the full image
    full_image.save(output_filename)
    print(f"Image saved to {output_filename}")
    record_partial_refresh()

    for r in regions:
        print(f"  Partial region: x={r[0]}, y={r[1]}, w={r[2]}, h={r[3]}")

    # Skip e-ink display update on Darwin (macOS)
    if system_platform == 'Darwin':
        print(f"Running on {system_platform} - skipping e-ink display update (hardware not available)")
        return

    if epd7in5_V2 is None:
        print(f"Running on {system_platform} - e-ink display module not available")
        return

    try:
        print(f"Running on {system_platform} - updating e-ink display (partial refresh, {len(regions)} region(s))")
        epd = epd7in5_V2.EPD()
        epd.init_part()

        for (x, y, w, h) in regions:
            cropped = full_image.crop((x, y, x + w, y + h))
            buf = _getbuffer_partial(cropped)
            epd.display_Partial(buf, x, y, x + w, y + h)

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
    """CLI entry point: render and send the current scoreboard image to the e-ink display."""
    system_platform = platform.system()
    print(f"Running on platform: {system_platform}")

    data = load_json_file('linescore.json')
    config_data = load_yaml_file('config.yaml')

    # this is bad but i designed this two different ways
    if data.get('update_display') and not config_data.get('scoreboard'):
        image = Image.open('temp.bmp')
        changed_regions = data.get('changed_regions', [])

        if needs_full_refresh() or not changed_regions:
            print("Linescore: full refresh")
            display_image(image)
        else:
            print(f"Linescore: partial refresh ({len(changed_regions)} region(s))")
            # Convert lists back to tuples
            regions = [tuple(r) for r in changed_regions]
            display_partial_regions(image, regions)

if __name__ == '__main__':
    main()
