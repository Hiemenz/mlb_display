#!/usr/bin/env python3
"""
Generate a standalone standings image for e-ink display
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont
from util import load_json_file
import argparse

picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')

EPD_WIDTH = 800
EPD_HEIGHT = 480

standings_dict = {
    1: 'American League East',
    2: 'American League Central',
    3: 'American League West',
    4: 'National League East',
    5: 'National League Central',
    6: 'National League West',
}

def generate_standings_image(division_id=None, output_file='standings.bmp'):
    """
    Generate a standings image for a specific division or random if not specified.

    Args:
        division_id: Division number (1-6) or None for random
        output_file: Output filename
    """
    data = load_json_file('standings.json')

    if not data or 'standings' not in data:
        print("Error: No standings data found. Run standings.py first.")
        return None

    # If no division specified, show all divisions
    if division_id is None:
        print("No division specified - generating image with all divisions")
        return generate_all_divisions_image(data, output_file)

    # Create blank white image
    Himage = Image.new('1', (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(Himage)

    division_name = standings_dict.get(division_id)
    if not division_name:
        print(f"Error: Invalid division ID {division_id}. Use 1-6.")
        return None

    teams_in_division = data.get('standings').get(division_name)
    if not teams_in_division:
        print(f"Error: No data for {division_name}")
        return None

    print(f"Generating standings for: {division_name}")

    # Draw title
    font24 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 24)
    font18 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)
    font15 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 15)

    # Title
    draw.text((50, 20), division_name, font=font24, fill=0)

    # Draw standings table
    col_start = 50
    row_start = 80

    # Draw horizontal lines
    for item in range(6):
        padding = item * 30
        draw.line((col_start, padding + row_start, 700, padding + row_start), fill=0)

    verticle_lines = [160, 200, 240, 290, 340, 395, 440, 510, 580]

    # Draw vertical lines
    for line in verticle_lines:
        draw.line((line + col_start, -20 + row_start, line + col_start, 150 + row_start), fill=0)

    # Draw headers
    row_start += 5
    padding = -30
    draw.text((0 + col_start, padding + row_start), 'Team', font=font18, fill=0)
    draw.text((verticle_lines[0] + 8 + col_start, padding + row_start), 'W', font=font18, fill=0)
    draw.text((verticle_lines[1] + 8 + col_start, padding + row_start), 'L', font=font18, fill=0)
    draw.text((verticle_lines[2] + 8 + col_start, padding + row_start), 'PCT', font=font18, fill=0)
    draw.text((verticle_lines[3] + 8 + col_start, padding + row_start), 'GB', font=font18, fill=0)
    draw.text((verticle_lines[4] + 8 + col_start, padding + row_start), 'STRK', font=font18, fill=0)
    draw.text((verticle_lines[5] + 8 + col_start, padding + row_start), 'L10', font=font18, fill=0)
    draw.text((verticle_lines[6] + 8 + col_start, padding + row_start), 'Home', font=font18, fill=0)
    draw.text((verticle_lines[7] + 8 + col_start, padding + row_start), 'Away', font=font18, fill=0)

    # Draw team data
    for item, team in enumerate(teams_in_division):
        print(f"  {item+1}. {team.get('team_name')}")
        padding = item * 30
        draw.text((0 + col_start, padding + row_start), team.get('team_name'), font=font15, fill=0)
        draw.text((verticle_lines[0] + 8 + col_start, padding + row_start),
                  str(team.get('league_record_wins')), font=font18, fill=0)
        draw.text((verticle_lines[1] + 8 + col_start, padding + row_start),
                  str(team.get('league_record_losses')), font=font18, fill=0)
        draw.text((verticle_lines[2] + 8 + col_start, padding + row_start),
                  str(team.get('league_record_percent')), font=font18, fill=0)
        draw.text((verticle_lines[3] + 8 + col_start, padding + row_start),
                  str(team.get('games_back')), font=font18, fill=0)
        draw.text((verticle_lines[4] + 8 + col_start, padding + row_start),
                  team.get('streak'), font=font18, fill=0)
        draw.text((verticle_lines[5] + 8 + col_start, padding + row_start),
                  f'{team.get("last_ten_wins")}-{team.get("last_ten_losses")}', font=font18, fill=0)
        draw.text((verticle_lines[6] + 8 + col_start, padding + row_start),
                  f'{team.get("home_wins")}-{team.get("home_losses")}', font=font18, fill=0)
        draw.text((verticle_lines[7] + 8 + col_start, padding + row_start),
                  f'{team.get("away_wins")}-{team.get("away_losses")}', font=font18, fill=0)

    # Add last updated timestamp
    last_updated = data.get('last_updated', 'Unknown')
    font14 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 14)
    draw.text((50, 450), f'Updated: {last_updated}', font=font14, fill=0)

    # Save image
    Himage.save(output_file)
    print(f"\n✓ Standings image saved to: {output_file}")
    return Himage


def generate_all_divisions_image(data, output_file='standings_all.bmp'):
    """Generate an image showing all 6 divisions in a compact layout."""
    Himage = Image.new('1', (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(Himage)

    font18 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)
    font14 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 14)
    font12 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 12)

    # Draw title
    draw.text((280, 10), 'MLB Standings', font=font18, fill=0)

    # Layout: 2 columns x 3 rows
    col_width = 390
    row_height = 145

    for div_num in range(1, 7):
        division_name = standings_dict[div_num]
        teams = data.get('standings').get(division_name, [])

        # Calculate position
        col = (div_num - 1) % 2
        row = (div_num - 1) // 2

        x_start = 10 + (col * col_width)
        y_start = 40 + (row * row_height)

        # Division name
        short_name = division_name.replace('American League ', 'AL ').replace('National League ', 'NL ')
        draw.text((x_start, y_start), short_name, font=font14, fill=0)

        # Draw teams (compact format: rank. team W-L)
        for i, team in enumerate(teams[:5]):
            y = y_start + 20 + (i * 22)
            team_name = team.get('team_name', '').replace('Americans', 'Am.')
            # Truncate long names
            if len(team_name) > 16:
                team_name = team_name[:13] + '...'

            text = f"{i+1}. {team_name:16s} {team.get('league_record_wins'):3d}-{team.get('league_record_losses'):<3d}"
            draw.text((x_start, y), text, font=font12, fill=0)

    # Add timestamp
    last_updated = data.get('last_updated', 'Unknown')
    draw.text((10, 465), f'Updated: {last_updated}', font=font12, fill=0)

    Himage.save(output_file)
    print(f"\n✓ All divisions image saved to: {output_file}")
    return Himage


def main():
    parser = argparse.ArgumentParser(description='Generate MLB standings image for e-ink display')
    parser.add_argument('--division', '-d', type=int, choices=range(1, 7),
                        help='Division to display (1-6): 1=AL East, 2=AL Central, 3=AL West, '
                             '4=NL East, 5=NL Central, 6=NL West. Omit to show all divisions.')
    parser.add_argument('--output', '-o', type=str, default='standings.bmp',
                        help='Output filename (default: standings.bmp)')

    args = parser.parse_args()

    print("\nDivision Key:")
    for num, name in standings_dict.items():
        print(f"  {num}: {name}")
    print()

    generate_standings_image(args.division, args.output)


if __name__ == '__main__':
    main()
