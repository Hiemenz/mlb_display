#!/usr/bin/env python3
"""
Simple script to generate an image with just MLB standings (no games)
Uses the generate_standings function from generate_image.py
"""
import sys
sys.path.insert(0, 'src')

from PIL import Image
from generate_image import generate_standings
from util import load_json_file

def main():
    """Generate a simple image with standings"""

    # Check if standings data exists
    standings_data = load_json_file('standings.json')
    if not standings_data or 'standings' not in standings_data:
        print("Error: No standings data found!")
        print("Run this first: poetry run python src/standings.py")
        return

    print("Generating standings image...")

    # Create blank white image (800x480 for e-ink display)
    Himage = Image.new('1', (800, 480), 255)

    # Generate standings at the bottom of the image
    Himage = generate_standings(Himage, col_start=100, row_start=100)

    # Save the image
    output_file = 'resulting_image.bmp'
    Himage.save(output_file)

    print(f"✓ Standings image saved to: {output_file}")
    print(f"\nTo view: open {output_file}")

if __name__ == '__main__':
    main()
