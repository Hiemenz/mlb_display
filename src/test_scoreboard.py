#!/usr/bin/env python3
"""
Generate two test scoreboard images with all 30 MLB teams (15 games).
Image 1: away teams win.  Image 2: scores flipped so home teams win.
Run from project root: python3 src/test_scoreboard.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from PIL import Image, ImageOps
from generate_image import draw_out_of_town_score_board, load_yaml_file
from datetime import date

# 15 matchups covering all 30 teams
MATCHUPS = [
    ('NYY', 'BOS', 7, 3),
    ('TB',  'TOR', 2, 5),
    ('BAL', 'CWS', 10, 1),
    ('CLE', 'DET', 3, 6),
    ('KC',  'MIN', 8, 2),
    ('HOU', 'TEX', 4, 7),
    ('LAA', 'ATH', 1, 9),
    ('SEA', 'NYM', 6, 3),
    ('PHI', 'ATL', 2, 5),
    ('MIA', 'WSH', 7, 0),
    ('CHC', 'MIL', 4, 3),
    ('STL', 'PIT', 9, 2),
    ('CIN', 'LAD', 1, 4),
    ('SF',  'SD',  6, 5),
    ('COL', 'AZ',  3, 8),
]

# Assign fake numeric IDs and build team_data lookup
all_teams = sorted({t for m in MATCHUPS for t in (m[0], m[1])})
_id = {t: str(i + 1) for i, t in enumerate(all_teams)}
team_data = {'team_abbreviation': {v: k for k, v in _id.items()}}

WP_NAMES = [
    'J. Smith', 'M. Garcia', 'T. Johnson', 'C. Williams', 'R. Brown',
    'A. Davis',  'K. Miller', 'S. Wilson',  'D. Moore',   'J. Taylor',
    'B. Anderson','P. Thomas','N. Jackson', 'E. White',   'L. Harris',
]
LP_NAMES = [
    'B. Martinez','A. Robinson','M. Clark','J. Rodriguez','T. Lewis',
    'K. Lee',     'C. Walker',  'S. Hall', 'D. Allen',    'J. Young',
    'R. Hernandez','P. King',   'N. Wright','E. Lopez',   'L. Hill',
]

def make_games(flip=False):
    games = []
    for g, (away, home, away_sc, home_sc) in enumerate(MATCHUPS):
        if flip:
            away_sc, home_sc = home_sc, away_sc
        a_win = away_sc > home_sc
        h_win = home_sc > away_sc
        games.append({
            'game_pk': g + 1000,
            'away_team_id': _id[away],
            'home_team_id': _id[home],
            'detailed_state': 'Final',
            'away_runs':   away_sc,
            'home_runs':   home_sc,
            'away_hits':   away_sc + (g % 4) + 2,
            'home_hits':   home_sc + (g % 3) + 1,
            'away_errors': g % 2,
            'home_errors': (g + 1) % 2,
            'away_team_is_winner': a_win,
            'home_team_is_winner': h_win,
            'winner_name': WP_NAMES[g],
            'loser_name':  LP_NAMES[g],
            'current_inning': 9,
            'game_start':  '7:05 PM',
            'away_probable': None,
            'home_probable': None,
            'away_team_record_wins':   '50',
            'away_team_record_losses': '40',
            'home_team_record_wins':   '45',
            'home_team_record_losses': '45',
            'perfect_game': False,
            'no_hitter':    False,
            'save_situation': False,
            'last_play': None,
        })
    return games

date_str = str(date.today())
out_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

for flip, label, fname in [
    (False, 'away teams win', 'test_scoreboard_1'),
    (True,  'home teams win', 'test_scoreboard_2'),
]:
    games = make_games(flip=flip)
    img = Image.new('1', (800, 480), 255)
    img = draw_out_of_town_score_board(
        img, games, team_data, date_str,
        changed_game_ids=None, use_logos=True
    )
    config = load_yaml_file('config.yaml')
    if config.get('dark_mode', False):
        img = ImageOps.invert(img)
    path = os.path.join(out_dir, f'{fname}.png')
    img.save(path)
    print(f'Saved {fname}.png  ({label})')
