#!/usr/bin/env python3
"""
Generate a field-view test image for every stadium in BALLPARK_DIMENSIONS.
Run from project root: python3 src/test_stadiums.py

Output: output/stadium/<Venue Name>.png  (one per ballpark)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from field_view import render_field_view
from stadium_polygons import STADIUM_POLYGONS as BALLPARK_DIMENSIONS

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'output', 'stadium')
os.makedirs(OUT_DIR, exist_ok=True)

SAMPLE_DATA = {
    'away_abbr': 'NYY', 'home_abbr': 'BOS',
    'away_id': '147',   'home_id': '111',
    'away_runs': 3,     'home_runs': 2,
    'away_hits': 7,     'home_hits': 5,
    'away_errors': 0,   'home_errors': 1,
    'detailed_state': 'In Progress',
    'inning_state': 'Top',
    'inning_ordinal': '7th',
    'current_inning': 7,
    'balls': 2, 'strikes': 1, 'outs': 1,
    'runner_first': True, 'runner_second': False, 'runner_third': True,
    'batter': {
        'name': 'A. Judge',
        'season': {'avg': '.310', 'homeRuns': 45, 'rbi': 102},
    },
    'pitcher': {
        'name': 'C. Sale',
        'stats': {'inningsPitched': '6.1', 'strikeOuts': 8},
        'season': {'era': '2.94'},
    },
    'on_deck': {
        'name': 'G. Stanton',
        'season': {'avg': '.265', 'homeRuns': 32, 'rbi': 78},
        'stats': {},
    },
    'last_play': 'Single to left field, Soto scores from second',
    'all_hits': [
        # Previous innings — rendered as ghost/outline markers
        {'x': 100, 'y': 155, 'is_hr': False, 'is_hit': False, 'is_out': True,  'player': 'Torres', 'inning': 3, 'half': 'bottom'},
        {'x': 130, 'y': 145, 'is_hr': False, 'is_hit': True,  'is_out': False, 'player': 'Betts',  'inning': 4, 'half': 'top'},
        {'x': 18,  'y': 88,  'is_hr': True,  'is_hit': True,  'is_out': False, 'player': 'Devers', 'inning': 5, 'half': 'bottom'},
        # Current half-inning (inning=7, half='top') — rendered filled
        {'x': 127, 'y': -10, 'is_hr': True,  'is_hit': True,  'is_out': False, 'player': 'Judge',  'inning': 7, 'half': 'top'},
        {'x': 115, 'y': 155, 'is_hr': False, 'is_hit': False, 'is_out': True,  'player': 'Rizzo',  'inning': 7, 'half': 'top'},
        {'x': 142, 'y': 138, 'is_hr': False, 'is_hit': True,  'is_out': False, 'player': 'Soto',   'inning': 7, 'half': 'top'},
    ],
    'pitches': [
        {'px': -0.3, 'pz': 2.8, 'code': 'S'},   # strike, mid-left
        {'px':  1.1, 'pz': 2.2, 'code': 'B'},   # ball, outside right edge
        {'px': -0.1, 'pz': 2.5, 'code': 'F'},   # foul, center
        {'px':  0.2, 'pz': 2.9, 'code': 'C'},   # called strike, center-right
        {'px': -0.9, 'pz': 3.8, 'code': 'B'},   # ball, high and outside left
    ],
    'innings': [
        {'num': i, 'away_runs': (i % 2), 'home_runs': (i % 3 == 0 and 1 or 0)}
        for i in range(1, 8)
    ],
    'winner': '', 'loser': '', 'save': '',
}

for venue in sorted(BALLPARK_DIMENSIONS.keys()):
    data = dict(SAMPLE_DATA, venue=venue)
    img = render_field_view(data, dark_mode=False)
    safe_name = venue.replace('/', '-').replace(' ', '_')
    path = os.path.join(OUT_DIR, f'{safe_name}.png')
    img.save(path)
    print(f'  {venue}')

print(f'\nSaved {len(BALLPARK_DIMENSIONS)} images to {OUT_DIR}/')
