#!/usr/bin/env python3
"""Generate a test image showing all MLB team logos at large size with fake data."""

import os
import sys

picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')
logodir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic', 'logos')
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance
from generate_image import _load_logo_gray

TEAMS = [
    'ATH', 'HOU', 'SEA', 'TEX', 'LAA', 'CWS',
    'CLE', 'DET', 'KC',  'MIN', 'BAL', 'BOS',
    'NYY', 'TB',  'TOR', 'AZ',  'COL', 'LAD',
    'SD',  'SF',  'CHC', 'CIN', 'MIL', 'PIT',
    'STL', 'ATL', 'MIA', 'NYM', 'PHI', 'WSH',
]

COLS = 6
LOGO_SIZE = 80
CELL_W = 130
CELL_H = 110
ROWS = (len(TEAMS) + COLS - 1) // COLS
TITLE_H = 30

W = COLS * CELL_W
H = ROWS * CELL_H + TITLE_H

img = Image.new('1', (W, H), 1)
draw = ImageDraw.Draw(img)
font16 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 16)
font12 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 12)

draw.text((5, 6), 'MLB Logo Test — all 30 teams', font=font16, fill=0)
draw.line((0, TITLE_H - 2, W, TITLE_H - 2), fill=0)

for i, abbr in enumerate(TEAMS):
    col = i % COLS
    row = i // COLS
    cx = col * CELL_W
    cy = row * CELL_H + TITLE_H

    draw.rectangle([cx, cy, cx + CELL_W - 2, cy + CELL_H - 2], outline=0)

    gray = _load_logo_gray(abbr, abbr)
    if gray:
        gray.thumbnail((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)
        gray = ImageOps.autocontrast(gray, cutoff=0)
        gray = ImageEnhance.Contrast(gray).enhance(2.0)
        logo = gray.convert('1')
        lw, lh = logo.size
        lx = cx + (CELL_W - lw) // 2
        ly = cy + 4 + (LOGO_SIZE - lh) // 2
        img.paste(logo, (lx, ly))
    else:
        draw.text((cx + 10, cy + 35), abbr, font=font16, fill=0)
        draw.text((cx + 10, cy + 55), '(no logo)', font=font12, fill=0)

    draw.text((cx + 4, cy + CELL_H - 22), abbr, font=font16, fill=0)
    draw.text((cx + 50, cy + CELL_H - 20), 'Final 5-3', font=font12, fill=0)

out = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'test_logos.png')
img.save(out)
print(f'Saved {out}  ({W}x{H})')
