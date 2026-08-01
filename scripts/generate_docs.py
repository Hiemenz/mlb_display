#!/usr/bin/env python3
"""
Generate all screenshots used in the README docs/ directory.

Run from the repo root:
    poetry run python scripts/generate_docs.py

Produces:
    docs/scoreboard_pregame.png     — 5×3 grid, pre-game tiles + standings/wildcard
    docs/scoreboard_live.png        — 5×3 grid, live mid-inning tiles
    docs/scoreboard_finals.png      — 5×3 grid, final tiles with ghost logos
    docs/scoreboard_nohitter.png    — wide cell with inverted no-hitter header
    docs/tile_pregame.png           — single pre-game tile (cropped)
    docs/tile_live.png              — single live tile mid-inning (cropped)
    docs/tile_live_detail.png       — single live tile between-innings (cropped)
    docs/tile_final.png             — single final tile (cropped)
    docs/wide_cell.png              — wide (2-slot) live cell with pitch zone
    docs/fields_mode.png            — 5×3 fields-mode grid
    docs/pitch_mode.png             — pitch zone view
    docs/scorecard_mode.png         — at-bat scorecard view
    docs/standings_sidebar.png      — standings sidebar strip with streak badges
    docs/demo.gif                   — animated GIF cycling through all states
"""

import os
import sys

# Run from repo root so imports work
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, 'src'))
os.chdir(REPO_ROOT)

from unittest.mock import patch, MagicMock

from PIL import Image, ImageDraw

# Silence any download attempts
_NO_NETWORK = patch('image_assets._try_download_logo', return_value=False)

DOCS_DIR = os.path.join(REPO_ROOT, 'docs')
os.makedirs(DOCS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _save(img: Image.Image, name: str, scale: int = 2):
    """Convert 1-bit to grayscale, optionally scale, save to docs/."""
    out = img.convert('L')
    if scale != 1:
        out = out.resize((out.width * scale, out.height * scale), Image.NEAREST)
    path = os.path.join(DOCS_DIR, name)
    out.save(path)
    print(f"  wrote {name}  ({out.width}×{out.height})")
    return path


def _canvas():
    """Canvas."""
    return Image.new('1', (800, 480), 255)


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

TEAM_DATA = {
    'team_abbreviation': {
        '108': 'LAA', '109': 'ARI', '110': 'BAL', '111': 'BOS', '112': 'CHC',
        '113': 'CIN', '114': 'CLE', '115': 'COL', '116': 'DET', '117': 'HOU',
        '118': 'KC',  '119': 'LAD', '120': 'WSH', '121': 'NYM', '133': 'OAK',
        '134': 'PIT', '135': 'SD',  '136': 'SEA', '137': 'SF',  '138': 'STL',
        '139': 'TB',  '140': 'TEX', '141': 'TOR', '142': 'MIN', '143': 'PHI',
        '144': 'ATL', '145': 'CWS', '146': 'MIA', '147': 'NYY', '158': 'MIL',
    }
}


def _pregame(away_id, home_id, away_abbr, home_abbr,
             away_record='38-27', home_record='35-30',
             start='7:10 PM', moneyline_away=-140, moneyline_home=120,
             weather_temp=72, weather_wind='8 mph NE', weather_precip='0%',
             stadium='Tropicana Field',
             away_pitcher='Shane McClanahan', away_pitcher_era='3.12', away_pitcher_wl='7-3',
             home_pitcher='Kevin Gausman', home_pitcher_era='2.87', home_pitcher_wl='8-2',
             away_streak='W3', home_streak='L2'):
    """Pregame."""
    return {
        'game_pk': hash((away_id, home_id)) & 0xFFFF,
        'away_team_id': away_id, 'home_team_id': home_id,
        'away_team_name': away_abbr, 'home_team_name': home_abbr,
        'away_abbr': away_abbr, 'home_abbr': home_abbr,
        'detailed_state': 'Pre-Game',
        'abstract_game_state': 'Preview',
        'away_runs': 0, 'home_runs': 0,
        'away_hits': 0, 'home_hits': 0,
        'away_errors': 0, 'home_errors': 0,
        'away_team_is_winner': False, 'home_team_is_winner': False,
        'current_inning': 0, 'inningState': '',
        'num_of_outs': 0, 'balls': None, 'strikes': None,
        'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None,
        'game_start': start, 'game_datetime': '2026-07-02T00:10:00Z',
        'away_team_record': away_record, 'home_team_record': home_record,
        'away_team_record_wins': int(away_record.split('-')[0]),
        'away_team_record_losses': int(away_record.split('-')[1]),
        'home_team_record_wins': int(home_record.split('-')[0]),
        'home_team_record_losses': int(home_record.split('-')[1]),
        'away_streak': away_streak, 'home_streak': home_streak,
        'moneyline_away': moneyline_away, 'moneyline_home': moneyline_home,
        'weather_temp': weather_temp, 'weather_wind': weather_wind,
        'weather_precip': weather_precip,
        'stadium': stadium,
        'away_probable': away_pitcher, 'away_probable_era': away_pitcher_era,
        'away_probable_wl': away_pitcher_wl,
        'home_probable': home_pitcher, 'home_probable_era': home_pitcher_era,
        'home_probable_wl': home_pitcher_wl,
        'away_probable_note': None, 'home_probable_note': None,
        'no_hitter': False, 'perfect_game': False, 'save_situation': False,
        'walk_off': False, 'last_play': None, 'venue': stadium,
        'away_win_probability': None, 'home_win_probability': None,
        'series_game_number': 1, 'series_total_games': 3,
        'series_wins': 0, 'series_losses': 0,
        'series_result': '', 'series_is_tied': False, 'series_is_over': False,
    }


def _live(away_id, home_id, away_abbr, home_abbr,
          away_runs=2, home_runs=3,
          inning=7, inning_state='Top',
          outs=1, balls=2, strikes=1,
          runner_first='Mookie Betts', runner_second=None, runner_third=None,
          pitcher='Logan Webb', batter='Freddie Freeman',
          pitch_count=87, last_pitch_speed=94.1, last_pitch_type='FB',
          win_prob_away=42.0,
          no_hitter=False, perfect_game=False):
    """Live."""
    return {
        'game_pk': hash((away_id, home_id, inning)) & 0xFFFF,
        'away_team_id': away_id, 'home_team_id': home_id,
        'away_team_name': away_abbr, 'home_team_name': home_abbr,
        'away_abbr': away_abbr, 'home_abbr': home_abbr,
        'detailed_state': 'In Progress',
        'abstract_game_state': 'Live',
        'away_runs': away_runs, 'home_runs': home_runs,
        'away_hits': away_runs + 4, 'home_hits': home_runs + 5,
        'away_errors': 0, 'home_errors': 0,
        'away_team_is_winner': False, 'home_team_is_winner': False,
        'current_inning': inning, 'inningState': inning_state,
        'inning_ordinal': f'{inning}th',
        'num_of_outs': outs, 'balls': balls, 'strikes': strikes,
        'runner_on_first': runner_first, 'runner_on_second': runner_second,
        'runner_on_third': runner_third,
        'runner_first_number': 50 if runner_first else None,
        'runner_second_number': None, 'runner_third_number': None,
        'game_start': '7:05 PM', 'game_datetime': '2026-07-02T00:05:00Z',
        'away_team_record': '40-30', 'home_team_record': '45-25',
        'away_team_record_wins': 40, 'away_team_record_losses': 30,
        'home_team_record_wins': 45, 'home_team_record_losses': 25,
        'current_pitcher': pitcher, 'current_hitter': batter,
        'current_play_batter': batter,
        'pitch_count': pitch_count,
        'last_pitch_type': last_pitch_type, 'last_pitch_speed': last_pitch_speed,
        'batter_hits': 2, 'batter_at_bats': 3, 'current_at_bat_complete': False,
        'away_inning_runs': [0, 1, 0, 0, 0, 1, 0],
        'home_inning_runs': [0, 0, 2, 0, 0, 0, 1],
        'strike_calls': ['C', 'S'],
        'half_inning_plays': ['K', '1B'],
        'home_pitcher_ks': ['K', 'K', 'L', 'K', 'K'],
        'away_pitcher_ks': ['K', 'L', 'K'],
        'ab_pitches': [
            {'seq': 1, 'px': -0.3, 'pz': 2.8, 'sz_top': 3.4, 'sz_bot': 1.6,
             'code': 'C', 'pt_abbr': 'FB'},
            {'seq': 2, 'px': 0.9,  'pz': 1.2, 'sz_top': 3.4, 'sz_bot': 1.6,
             'code': 'B', 'pt_abbr': 'SL'},
            {'seq': 3, 'px': 0.1,  'pz': 2.5, 'sz_top': 3.4, 'sz_bot': 1.6,
             'code': 'S', 'pt_abbr': 'CH'},
        ],
        'away_win_probability': win_prob_away,
        'home_win_probability': 100 - win_prob_away,
        'no_hitter': no_hitter, 'perfect_game': perfect_game,
        'save_situation': False, 'walk_off': False,
        'last_play': f'{batter} lined out to center field.',
        'venue': 'Oracle Park',
        'game_duration_minutes': 120,
        'series_game_number': 2, 'series_total_games': 3,
        'series_wins': 1, 'series_losses': 0,
        'series_result': '', 'series_is_tied': False, 'series_is_over': False,
    }


def _between_innings(away_id, home_id, away_abbr, home_abbr,
                     inning=7, away_runs=2, home_runs=3):
    """Between innings."""
    base = _live(away_id, home_id, away_abbr, home_abbr,
                 away_runs=away_runs, home_runs=home_runs,
                 inning=inning, inning_state='Middle', outs=3)
    base.update({
        'ab_pitches': [],
        'num_of_outs': 3,
        'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None,
        'next_batter_1': 'Freddie Freeman',
        'next_batter_2': 'Will Smith',
        'next_batter_3': 'Max Muncy',
        'next_pitcher': 'Edwin Diaz',
    })
    return base


def _final(away_id, home_id, away_abbr, home_abbr,
           away_runs=2, home_runs=5,
           winner='Logan Webb', loser='Clayton Kershaw',
           winner_record='9-2', loser_record='5-6', saver=None):
    """Final."""
    return {
        'game_pk': hash((away_id, home_id)) & 0xFFFF,
        'away_team_id': away_id, 'home_team_id': home_id,
        'away_team_name': away_abbr, 'home_team_name': home_abbr,
        'away_abbr': away_abbr, 'home_abbr': home_abbr,
        'detailed_state': 'Final',
        'abstract_game_state': 'Final',
        'away_runs': away_runs, 'home_runs': home_runs,
        'away_hits': away_runs + 4, 'home_hits': home_runs + 5,
        'away_errors': 0, 'home_errors': 1,
        'away_team_is_winner': away_runs > home_runs,
        'home_team_is_winner': home_runs > away_runs,
        'winner_name': winner, 'loser_name': loser,
        'winner_record': winner_record, 'loser_record': loser_record,
        'saver_name': saver, 'saver_saves': '8' if saver else None,
        'current_inning': 9, 'inningState': 'End',
        'num_of_outs': 3, 'balls': None, 'strikes': None,
        'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None,
        'game_start': '7:05 PM', 'game_datetime': '2026-07-02T00:05:00Z',
        'away_team_record': '40-30', 'home_team_record': '46-25',
        'away_team_record_wins': 40, 'away_team_record_losses': 30,
        'home_team_record_wins': 46, 'home_team_record_losses': 25,
        'away_inning_runs': [0, 1, 0, 0, 0, 1, 0, 0, 0],
        'home_inning_runs': [1, 0, 2, 0, 0, 0, 1, 0, 1],
        'away_win_probability': None, 'home_win_probability': None,
        'no_hitter': False, 'perfect_game': False,
        'save_situation': False, 'walk_off': False, 'last_play': None,
        'venue': 'Oracle Park', 'game_duration_minutes': 178,
        'series_game_number': 2, 'series_total_games': 3,
        'series_wins': 0, 'series_losses': 1,
        'series_result': '', 'series_is_tied': False, 'series_is_over': False,
    }


# 15 games for a full scoreboard grid
PREGAME_GAMES = [
    _pregame(139, 147, 'TB',  'NYY', '50-33', '48-38', '7:05 PM', -115, -105,
             78, '12 mph SE', '10%', 'Yankee Stadium',
             'Shane McClanahan', '2.91', '8-4', 'Gerrit Cole', '3.18', '9-3',
             'W7', 'L7'),
    _pregame(111, 119, 'BOS', 'LAD', '38-45', '52-28', '10:10 PM', +130, -150,
             70, '5 mph SW', '0%', 'Dodger Stadium',
             'Brayan Bello', '4.02', '6-7', 'Tyler Glasnow', '2.75', '10-2',
             'W1', 'W5'),
    _pregame(117, 144, 'HOU', 'ATL', '41-42', '49-32', '7:20 PM', -125, +105,
             84, '10 mph NW', '5%', 'Truist Park',
             'Hunter Brown', '3.55', '7-5', 'Spencer Strider', '2.50', '11-1',
             'L1', 'W3'),
    _pregame(142, 134, 'MIN', 'PIT', '43-38', '30-53', '6:40 PM', -190, +160,
             75, '6 mph NE', '0%', 'PNC Park',
             'Joe Ryan', '3.30', '8-4', 'Mitch Keller', '4.15', '5-8',
             'W2', 'L4'),
    _pregame(113, 138, 'CIN', 'STL', '35-48', '40-42', '7:15 PM', +110, -130,
             82, '9 mph E', '15%', 'Busch Stadium',
             'Hunter Greene', '3.80', '6-6', 'Miles Mikolas', '4.60', '4-7',
             'L3', 'W1'),
]

LIVE_GAMES = [
    _live(139, 147, 'TB',  'NYY', 3, 2, 7, 'Top',  1, 2, 1, 'Yandy Diaz',  None, None,
          'Gerrit Cole', 'Randy Arozarena', 87, 96.2, 'FF', 55.0),
    _live(111, 119, 'BOS', 'LAD', 1, 4, 5, 'Bot',  0, 3, 0, 'Freddie Freeman', None, None,
          'Brayan Bello', 'Mookie Betts', 62, 89.3, 'CH', 25.0),
    _live(117, 144, 'HOU', 'ATL', 2, 2, 6, 'Top',  2, 1, 2, None, 'Ronald Acuña Jr', None,
          'Spencer Strider', 'Yordan Alvarez', 95, 100.1, 'FF', 48.0),
    _live(142, 134, 'MIN', 'PIT', 5, 1, 8, 'Bot',  1, 0, 1, None, None, 'Andrew McCutchen',
          'Jorge Lopez', 'Carlos Santana', 45, 92.7, 'SI', 82.0),
    _live(113, 138, 'CIN', 'STL', 0, 3, 4, 'Top',  0, 2, 2, 'Nick Castellanos', 'TJ Friedl', None,
          'Miles Mikolas', 'Elly De La Cruz', 71, 84.5, 'SL', 30.0),
]

FINAL_GAMES = [
    _final(139, 147, 'TB',  'NYY', 4, 2, 'Zach Eflin',   'Gerrit Cole',   '9-4', '6-6'),
    _final(111, 119, 'BOS', 'LAD', 1, 6, 'Tyler Glasnow','Brayan Bello',  '11-2','7-7'),
    _final(117, 144, 'HOU', 'ATL', 3, 5, 'Spencer Strider','Hunter Brown','12-1','8-5'),
    _final(142, 134, 'MIN', 'PIT', 7, 2, 'Joe Ryan',     'Mitch Keller',  '9-4', '5-9'),
    _final(113, 138, 'CIN', 'STL', 2, 4, 'Miles Mikolas','Hunter Greene', '5-7', '7-6'),
    _final(112, 143, 'CHC', 'PHI', 3, 1, 'Justin Steele','Aaron Nola',    '8-5', '7-5'),
    _final(118, 110, 'KC',  'BAL', 0, 4, 'Corbin Burnes','Brady Singer',  '10-3','4-9',
           saver='Felix Bautista'),
    _final(114, 116, 'CLE', 'DET', 5, 3, 'Shane Bieber', 'Eduardo Rodriguez','7-4','5-8'),
    _final(120, 121, 'WSH', 'NYM', 1, 3, 'Kodai Senga',  'Patrick Corbin','6-5', '3-10'),
    _final(115, 135, 'COL', 'SD',  2, 7, 'Yu Darvish',   'Austin Gomber', '11-4','3-10'),
    _final(140, 136, 'TEX', 'SEA', 4, 3, 'Jacob DeGrom', 'Logan Gilbert', '8-3', '6-7'),
    _final(133, 145, 'OAK', 'CWS', 6, 1, 'JP Sears',     'Dylan Cease',   '5-8', '3-11'),
    _final(146, 158, 'MIA', 'MIL', 2, 5, 'Freddy Peralta','Sandy Alcantara','9-3','3-10'),
    _final(109, 108, 'ARI', 'LAA', 8, 3, 'Merrill Kelly', 'Patrick Sandoval','7-6','3-10'),
    _final(141, 137, 'TOR', 'SF',  3, 4, 'Logan Webb',   'Kevin Gausman', '10-4','7-6'),
]

STANDINGS_DATA = {
    'standings': {
        'American League East': [
            {'team_id': '139', 'divisionRank': '1', 'league_record_wins': '50',
             'league_record_losses': '33', 'games_back': '-', 'streak': 'W7',
             'clinched': None, 'movement': 0},
            {'team_id': '147', 'divisionRank': '2', 'league_record_wins': '48',
             'league_record_losses': '38', 'games_back': '3.5', 'streak': 'L7',
             'clinched': None, 'movement': -1},
            {'team_id': '111', 'divisionRank': '3', 'league_record_wins': '38',
             'league_record_losses': '45', 'games_back': '11.0', 'streak': 'W1',
             'clinched': None, 'movement': 1},
            {'team_id': '141', 'divisionRank': '4', 'league_record_wins': '35',
             'league_record_losses': '48', 'games_back': '14.0', 'streak': 'L2',
             'clinched': None, 'movement': 0},
            {'team_id': '110', 'divisionRank': '5', 'league_record_wins': '33',
             'league_record_losses': '50', 'games_back': '16.0', 'streak': 'L3',
             'clinched': None, 'movement': 0},
        ],
        'American League Central': [
            {'team_id': '142', 'divisionRank': '1', 'league_record_wins': '43',
             'league_record_losses': '38', 'games_back': '-', 'streak': 'W2',
             'clinched': None, 'movement': 0},
            {'team_id': '114', 'divisionRank': '2', 'league_record_wins': '41',
             'league_record_losses': '40', 'games_back': '2.0', 'streak': 'W3',
             'clinched': None, 'movement': 1},
            {'team_id': '116', 'divisionRank': '3', 'league_record_wins': '40',
             'league_record_losses': '41', 'games_back': '3.0', 'streak': 'L1',
             'clinched': None, 'movement': -1},
            {'team_id': '145', 'divisionRank': '4', 'league_record_wins': '35',
             'league_record_losses': '46', 'games_back': '8.0', 'streak': 'L5',
             'clinched': None, 'movement': 0},
            {'team_id': '118', 'divisionRank': '5', 'league_record_wins': '34',
             'league_record_losses': '47', 'games_back': '9.0', 'streak': 'W1',
             'clinched': None, 'movement': 0},
        ],
        'American League West': [
            {'team_id': '117', 'divisionRank': '1', 'league_record_wins': '41',
             'league_record_losses': '42', 'games_back': '-', 'streak': 'L1',
             'clinched': None, 'movement': 0},
            {'team_id': '136', 'divisionRank': '2', 'league_record_wins': '40',
             'league_record_losses': '43', 'games_back': '1.0', 'streak': 'W2',
             'clinched': None, 'movement': 1},
            {'team_id': '140', 'divisionRank': '3', 'league_record_wins': '38',
             'league_record_losses': '45', 'games_back': '3.0', 'streak': 'L2',
             'clinched': None, 'movement': 0},
            {'team_id': '108', 'divisionRank': '4', 'league_record_wins': '30',
             'league_record_losses': '53', 'games_back': '11.0', 'streak': 'L4',
             'clinched': None, 'movement': 0},
            {'team_id': '133', 'divisionRank': '5', 'league_record_wins': '28',
             'league_record_losses': '55', 'games_back': '13.0', 'streak': 'L6',
             'clinched': None, 'movement': -1},
        ],
        'National League East': [
            {'team_id': '144', 'divisionRank': '1', 'league_record_wins': '49',
             'league_record_losses': '32', 'games_back': '-', 'streak': 'W3',
             'clinched': None, 'movement': 0},
            {'team_id': '143', 'divisionRank': '2', 'league_record_wins': '46',
             'league_record_losses': '35', 'games_back': '3.0', 'streak': 'L1',
             'clinched': None, 'movement': 1},
            {'team_id': '121', 'divisionRank': '3', 'league_record_wins': '40',
             'league_record_losses': '41', 'games_back': '9.0', 'streak': 'W2',
             'clinched': None, 'movement': -1},
            {'team_id': '120', 'divisionRank': '4', 'league_record_wins': '33',
             'league_record_losses': '48', 'games_back': '16.0', 'streak': 'L3',
             'clinched': None, 'movement': 0},
            {'team_id': '146', 'divisionRank': '5', 'league_record_wins': '28',
             'league_record_losses': '53', 'games_back': '21.0', 'streak': 'W1',
             'clinched': None, 'movement': 0},
        ],
        'National League Central': [
            {'team_id': '112', 'divisionRank': '1', 'league_record_wins': '45',
             'league_record_losses': '36', 'games_back': '-', 'streak': 'W4',
             'clinched': None, 'movement': 0},
            {'team_id': '158', 'divisionRank': '2', 'league_record_wins': '44',
             'league_record_losses': '37', 'games_back': '1.0', 'streak': 'L1',
             'clinched': None, 'movement': 0},
            {'team_id': '138', 'divisionRank': '3', 'league_record_wins': '40',
             'league_record_losses': '41', 'games_back': '5.0', 'streak': 'W1',
             'clinched': None, 'movement': 1},
            {'team_id': '113', 'divisionRank': '4', 'league_record_wins': '35',
             'league_record_losses': '46', 'games_back': '10.0', 'streak': 'L3',
             'clinched': None, 'movement': 0},
            {'team_id': '134', 'divisionRank': '5', 'league_record_wins': '30',
             'league_record_losses': '51', 'games_back': '15.0', 'streak': 'L9',
             'clinched': None, 'movement': -1},
        ],
        'National League West': [
            {'team_id': '119', 'divisionRank': '1', 'league_record_wins': '52',
             'league_record_losses': '28', 'games_back': '-', 'streak': 'W5',
             'clinched': None, 'movement': 0},
            {'team_id': '109', 'divisionRank': '2', 'league_record_wins': '43',
             'league_record_losses': '37', 'games_back': '9.0', 'streak': 'L2',
             'clinched': None, 'movement': 0},
            {'team_id': '137', 'divisionRank': '3', 'league_record_wins': '41',
             'league_record_losses': '39', 'games_back': '11.0', 'streak': 'W2',
             'clinched': None, 'movement': 1},
            {'team_id': '135', 'divisionRank': '4', 'league_record_wins': '38',
             'league_record_losses': '42', 'games_back': '14.0', 'streak': 'L1',
             'clinched': None, 'movement': 0},
            {'team_id': '115', 'divisionRank': '5', 'league_record_wins': '30',
             'league_record_losses': '50', 'games_back': '22.0', 'streak': 'L8',
             'clinched': None, 'movement': -1},
        ],
    }
}


def _wildcard_teams():
    """Wildcard teams."""
    return {
        'AL': [
            {'team_id': '136', 'team_abbr': 'SEA', 'games_back': '-'},
            {'team_id': '142', 'team_abbr': 'MIN', 'games_back': '+1'},
            {'team_id': '117', 'team_abbr': 'HOU', 'games_back': '+2'},
            {'team_id': '139', 'team_abbr': 'TB',  'games_back': '+3'},
            {'team_id': '114', 'team_abbr': 'CLE', 'games_back': '+4'},
            {'team_id': '141', 'team_abbr': 'TOR', 'games_back': '+5'},
        ],
        'NL': [
            {'team_id': '112', 'team_abbr': 'CHC', 'games_back': '-'},
            {'team_id': '143', 'team_abbr': 'PHI', 'games_back': '+1'},
            {'team_id': '144', 'team_abbr': 'ATL', 'games_back': '+2'},
            {'team_id': '137', 'team_abbr': 'SF',  'games_back': '+3'},
            {'team_id': '119', 'team_abbr': 'LAD', 'games_back': '+4'},
            {'team_id': '109', 'team_abbr': 'ARI', 'games_back': '+6'},
        ],
    }


def _field_fixture():
    """Field fixture."""
    return {
        'venue': 'Oracle Park',
        'detailed_state': 'In Progress',
        'inning_state': 'Top',
        'inning_ordinal': '7th',
        'current_inning': 7,
        'outs': 1, 'balls': 2, 'strikes': 1,
        'away_abbr': 'LAD', 'home_abbr': 'SF',
        'away_id': 119, 'home_id': 137,
        'away_runs': 3, 'home_runs': 2,
        'away_hits': 7, 'home_hits': 5,
        'away_errors': 0, 'home_errors': 1,
        'runner_first': 'Mookie Betts', 'runner_second': None, 'runner_third': None,
        'batter': {'name': 'Freddie Freeman',
                   'season': {'avg': '.312', 'homeRuns': '15', 'rbi': '55'}},
        'pitcher': {'name': 'Logan Webb', 'season': {'era': '2.85'},
                    'stats': {'inningsPitched': '150.0', 'strikeOuts': '140'}},
        'on_deck': {'name': 'Will Smith', 'season': {'avg': '.290', 'homeRuns': '10'}},
        'last_play': 'Freeman singled to right field.',
        'pitches': [
            {'px': -0.3, 'pz': 2.8, 'code': 'C'},
            {'px':  0.9, 'pz': 1.2, 'code': 'B'},
            {'px':  0.1, 'pz': 2.5, 'code': 'S'},
            {'px': -0.5, 'pz': 3.1, 'code': 'F'},
        ],
        'all_hits': [
            {'x': 150, 'y': 180, 'is_hr': False, 'is_hit': True,
             'player': 'Freeman', 'inning': 7, 'half': 'top'},
            {'x': 60,  'y': 120, 'is_hr': True,  'is_hit': True,
             'player': 'Betts',  'inning': 4, 'half': 'top'},
            {'x': 220, 'y': 210, 'is_hr': False, 'is_hit': False,
             'player': 'Webb',   'inning': 6, 'half': 'bot'},
        ],
        'innings': [{'num': i + 1, 'away_runs': 0, 'home_runs': 0} for i in range(7)],
    }


def _pitch_fixture():
    """Pitch fixture."""
    return {
        'detailed_state': 'In Progress',
        'inning_state': 'Top',
        'inning_ordinal': '7th',
        'balls': 2, 'strikes': 1, 'outs': 1,
        'away_abbr': 'LAD', 'home_abbr': 'SF',
        'away_id': 119, 'home_id': 137,
        'away_runs': 3, 'home_runs': 2,
        'batter': {'name': 'Freddie Freeman',
                   'season': {'avg': '.312', 'homeRuns': '15', 'rbi': '55'}},
        'pitcher': {'name': 'Logan Webb', 'season': {'era': '2.85'},
                    'stats': {'inningsPitched': '150.0', 'strikeOuts': '140'}},
        'pitches': [
            {'px': -0.3, 'pz': 2.8, 'code': 'C', 'seq': 1, 'pitch_type': 'Fastball', 'speed': 94.1},
            {'px':  0.9, 'pz': 1.2, 'code': 'B', 'seq': 2, 'pitch_type': 'Slider', 'speed': 86.3},
            {'px':  0.1, 'pz': 2.5, 'code': 'S', 'seq': 3, 'pitch_type': 'Changeup', 'speed': 88.5},
            {'px': -0.6, 'pz': 2.9, 'code': 'F', 'seq': 4, 'pitch_type': 'Fastball', 'speed': 95.0},
            {'px':  0.3, 'pz': 3.0, 'code': 'X', 'seq': 5, 'pitch_type': 'Cutter', 'speed': 90.2},
        ],
    }


def _scorecard_lineup(n=9):
    """Scorecard lineup."""
    codes = ['1B', 'K', 'HR', '6-3', 'BB', '2B', 'F9', '3B', 'K']
    names = ['Mookie Betts', 'Freddie Freeman', 'Max Muncy', 'Will Smith',
             'J.D. Martinez', 'Chris Taylor', 'Miguel Vargas', 'Michael Grove', 'James Outman']
    positions = ['RF', '1B', '3B', 'C', 'LF', 'SS', 'DH', 'CF', 'P']
    lineup = []
    for i in range(n):
        order = i + 1
        ab = {
            1: [{'code': codes[i % len(codes)], 'bases': i % 4,
                  'balls': i % 4, 'strikes': i % 3}],
            4: [{'code': 'K', 'bases': 0, 'balls': 1, 'strikes': 3}],
        }
        totals = {'runs': 1 if i % 3 == 0 else 0, 'hits': 1 if i % 2 == 0 else 0}
        lineup.append({
            'name': names[i], 'position': positions[i], 'order': order,
            'sub': False, 'sub_original': None,
            'at_bats': ab, 'totals': totals,
        })
    return lineup


def _scorecard_fixture():
    """Scorecard fixture."""
    return {
        'detailed_state': 'In Progress',
        'inning_state': 'Top',
        'inning_ordinal': '5th',
        'current_inning': 5,
        'away_abbr': 'LAD', 'home_abbr': 'SF',
        'away_id': 119, 'home_id': 137,
        'away_runs': 3, 'home_runs': 2,
        'away_hits': 6, 'home_hits': 4,
        'away_errors': 0, 'home_errors': 1,
        'innings': [
            {'num': 1, 'away_runs': 0, 'home_runs': 1},
            {'num': 2, 'away_runs': 1, 'home_runs': 0},
            {'num': 3, 'away_runs': 2, 'home_runs': 0},
            {'num': 4, 'away_runs': 0, 'home_runs': 1},
            {'num': 5, 'away_runs': 0, 'home_runs': 0},
        ],
        'away_lineup': _scorecard_lineup(9),
        'home_lineup': _scorecard_lineup(9),
        'away_pitchers': [
            {'name': 'Tyler Glasnow', 'ip': '4.0', 'hits': 4, 'er': 2, 'k': 5},
        ],
        'home_pitchers': [
            {'name': 'Logan Webb', 'ip': '5.0', 'hits': 5, 'er': 3, 'k': 6},
        ],
    }


def _nohitter_game():
    """Nohitter game."""
    g = _live(117, 147, 'HOU', 'NYY', 0, 0, 7, 'Bot', 2, 1, 1,
              None, None, None, 'Gerrit Cole', 'Alex Bregman', 98, 97.5, 'FF',
              no_hitter=True)
    g['away_hits'] = 0
    g['away_runs'] = 0
    return g


def _wide_live_game():
    """Wide live game."""
    g = _live(139, 147, 'TB', 'NYY', 2, 3, 7, 'Top', 1, 2, 1,
              'Yandy Diaz', None, None, 'Gerrit Cole', 'Randy Arozarena',
              87, 96.2, 'FF', 45.0)
    g.update({
        'ab_pitches': [
            {'seq': 1, 'px': -0.3, 'pz': 2.8, 'sz_top': 3.4, 'sz_bot': 1.6,
             'code': 'C', 'pt_abbr': 'FB'},
            {'seq': 2, 'px': 0.9,  'pz': 1.2, 'sz_top': 3.4, 'sz_bot': 1.6,
             'code': 'B', 'pt_abbr': 'SL'},
            {'seq': 3, 'px': 0.1,  'pz': 2.5, 'sz_top': 3.4, 'sz_bot': 1.6,
             'code': 'S', 'pt_abbr': 'CH'},
            {'seq': 4, 'px': 0.5,  'pz': 1.8, 'sz_top': 3.4, 'sz_bot': 1.6,
             'code': 'F', 'pt_abbr': 'CU'},
        ],
        'half_inning_plays': ['K', '1B', 'K'],
        'home_pitcher_ks': ['K', 'K', 'L', 'K', 'K', 'K'],
        'away_pitcher_ks': ['K', 'L', 'K', 'K'],
        'strike_calls': ['C', 'S', 'S'],
        'batter_hits': 1, 'batter_at_bats': 3,
    })
    return g


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _render_scoreboard(games, show_win_prob=True):
    """Render a full 5×3 scoreboard grid with wildcard strip + standings."""
    from image_grid import draw_out_of_town_score_board
    from image_standings import draw_standings_sidebar, draw_wildcard_header

    img = _canvas()
    with _NO_NETWORK:
        img = draw_out_of_town_score_board(
            img, games, TEAM_DATA,
            use_logos=False,
            logo_x_offset=2,
            show_win_prob=show_win_prob,
        )
        img = draw_wildcard_header(img, _wildcard_teams())
        img = draw_standings_sidebar(img, STANDINGS_DATA, TEAM_DATA, side='left')
        img = draw_standings_sidebar(img, STANDINGS_DATA, TEAM_DATA, side='right')

    return img


def generate_scoreboard_pregame():
    """Generate scoreboard pregame."""
    print("Generating scoreboard_pregame.png ...")
    img = _render_scoreboard(PREGAME_GAMES * 3, show_win_prob=False)
    _save(img, 'scoreboard_pregame.png', scale=1)
    return img


def generate_scoreboard_live():
    """Generate scoreboard live."""
    print("Generating scoreboard_live.png ...")
    games = LIVE_GAMES * 2 + PREGAME_GAMES[:5]
    img = _render_scoreboard(games)
    _save(img, 'scoreboard_live.png', scale=1)
    return img


def generate_scoreboard_finals():
    """Generate scoreboard finals."""
    print("Generating scoreboard_finals.png ...")
    img = _render_scoreboard(FINAL_GAMES)
    _save(img, 'scoreboard_finals.png', scale=1)
    return img


def generate_scoreboard_nohitter():
    """Generate scoreboard nohitter."""
    print("Generating scoreboard_nohitter.png ...")
    games = [_nohitter_game()] + LIVE_GAMES[:4] + FINAL_GAMES[:5] + PREGAME_GAMES[:5]
    img = _render_scoreboard(games)
    _save(img, 'scoreboard_nohitter.png', scale=1)
    return img


def _crop_tile(img: Image.Image, col: int, row: int) -> Image.Image:
    """Crop one tile from the 5×3 scoreboard grid (columns 1-5, rows 1-3).
    Tiles start after the 32px sidebar. Each tile is 147×130 px (last col wider).
    """
    # The grid occupies x=32..767, y=18..480 (18px wildcard strip at top).
    SIDEBAR = 32
    WILDCARD_H = 18
    GRID_W = 800 - 2 * SIDEBAR   # 736 px
    GRID_H = 480 - WILDCARD_H    # 462 px
    CELL_W = GRID_W // 5          # 147 px
    CELL_H = GRID_H // 3          # 154 px
    x0 = SIDEBAR + (col - 1) * CELL_W
    y0 = WILDCARD_H + (row - 1) * CELL_H
    return img.crop((x0, y0, x0 + CELL_W, y0 + CELL_H))


def generate_tile_pregame():
    """Generate tile pregame."""
    print("Generating tile_pregame.png ...")
    img = _render_scoreboard(PREGAME_GAMES * 3)
    tile = _crop_tile(img, 1, 1)
    _save(tile, 'tile_pregame.png', scale=3)


def generate_tile_live():
    """Generate tile live."""
    print("Generating tile_live.png ...")
    games = LIVE_GAMES * 3
    img = _render_scoreboard(games)
    tile = _crop_tile(img, 1, 1)
    _save(tile, 'tile_live.png', scale=3)


def generate_tile_live_detail():
    """Generate tile live detail."""
    print("Generating tile_live_detail.png ...")
    bi_game = _between_innings(139, 147, 'TB', 'NYY', inning=7, away_runs=2, home_runs=3)
    games = [bi_game] + LIVE_GAMES[1:] * 3
    img = _render_scoreboard(games)
    tile = _crop_tile(img, 1, 1)
    _save(tile, 'tile_live_detail.png', scale=3)


def generate_tile_final():
    """Generate tile final."""
    print("Generating tile_final.png ...")
    img = _render_scoreboard(FINAL_GAMES)
    tile = _crop_tile(img, 1, 1)
    _save(tile, 'tile_final.png', scale=3)


def generate_wide_cell():
    """Render the wide-cell doc screenshot showing the expanded linescore box layout."""
    print("Generating wide_cell.png ...")
    from image_box import draw_wide_box
    from image_standings import draw_standings_sidebar, draw_wildcard_header

    img = _canvas()
    game = _wide_live_game()
    with _NO_NETWORK:
        img = draw_wide_box(img, 32, 18, game, TEAM_DATA,
                            use_logos=False, show_win_prob=True)
        img = draw_wildcard_header(img, _wildcard_teams())
        img = draw_standings_sidebar(img, STANDINGS_DATA, TEAM_DATA, side='left')
        img = draw_standings_sidebar(img, STANDINGS_DATA, TEAM_DATA, side='right')

    # Crop to the wide cell area: x=32..317, y=18..148
    SIDEBAR = 32
    WILDCARD_H = 18
    wide = img.crop((SIDEBAR, WILDCARD_H, SIDEBAR + 285, WILDCARD_H + 130))
    _save(wide, 'wide_cell.png', scale=3)


def generate_fields_mode():
    """Generate fields mode — 5×3 grid of field-diagram cells."""
    print("Generating fields_mode.png ...")
    from image_grid import draw_fields_grid

    def _with_hits(game, venue, hits, inning_state='Middle'):
        g = dict(game)
        g['venue'] = venue
        g['inningState'] = inning_state
        g['all_game_hits'] = hits
        return g

    _hits_yankee = [
        {'x': 160, 'y': 170, 'is_hr': False, 'is_hit': True},
        {'x':  80, 'y': 100, 'is_hr': True,  'is_hit': True},
        {'x': 200, 'y': 195, 'is_hr': False, 'is_hit': False},
        {'x': 175, 'y': 155, 'is_hr': False, 'is_hit': True},
    ]
    _hits_oracle = [
        {'x': 150, 'y': 180, 'is_hr': False, 'is_hit': True},
        {'x':  60, 'y': 120, 'is_hr': True,  'is_hit': True},
        {'x': 220, 'y': 210, 'is_hr': False, 'is_hit': False},
        {'x': 170, 'y': 160, 'is_hr': False, 'is_hit': True},
        {'x': 100, 'y': 140, 'is_hr': False, 'is_hit': False},
    ]
    _hits_truist = [
        {'x': 140, 'y': 175, 'is_hr': False, 'is_hit': True},
        {'x': 185, 'y': 130, 'is_hr': True,  'is_hit': True},
        {'x':  70, 'y': 145, 'is_hr': False, 'is_hit': False},
    ]

    games = (
        [_with_hits(LIVE_GAMES[0], 'Yankee Stadium', _hits_yankee)]
        + [_with_hits(LIVE_GAMES[1], 'Oracle Park', _hits_oracle)]
        + [_with_hits(LIVE_GAMES[2], 'Truist Park', _hits_truist)]
        + LIVE_GAMES[3:]
        + FINAL_GAMES[:5]
        + PREGAME_GAMES[:3]
    )

    img = Image.new('1', (800, 480), 255)
    with _NO_NETWORK:
        img = draw_fields_grid(img, games, TEAM_DATA)
    _save(img, 'fields_mode.png', scale=1)


def generate_pitch_mode():
    """Generate pitch mode."""
    print("Generating pitch_mode.png ...")
    from pitch_view import render_pitch_view

    with _NO_NETWORK:
        img = render_pitch_view(_pitch_fixture())
    _save(img, 'pitch_mode.png', scale=1)


def generate_scorecard_mode():
    """Generate scorecard mode."""
    print("Generating scorecard_mode.png ...")
    from scorecard_view import render_scorecard_view

    with _NO_NETWORK:
        img = render_scorecard_view(_scorecard_fixture())
    _save(img, 'scorecard_mode.png', scale=1)


def generate_standings_sidebar():
    """Generate a zoomed-in view of both standings sidebar strips."""
    print("Generating standings_sidebar.png ...")
    from image_standings import draw_standings_sidebar

    img = _canvas()
    with _NO_NETWORK:
        img = draw_standings_sidebar(img, STANDINGS_DATA, TEAM_DATA, side='left')
        img = draw_standings_sidebar(img, STANDINGS_DATA, TEAM_DATA, side='right')

    # Composite: left strip (x=0..31) | gap | right strip (x=768..799)
    left  = img.convert('L').crop((0, 0, 32, 480))
    right = img.convert('L').crop((768, 0, 800, 480))
    gap   = Image.new('L', (4, 480), 180)
    composite = Image.new('L', (32 + 4 + 32, 480), 255)
    composite.paste(left,  (0, 0))
    composite.paste(gap,   (32, 0))
    composite.paste(right, (36, 0))
    scaled = composite.resize((composite.width * 5, composite.height * 5), Image.NEAREST)
    path = os.path.join(DOCS_DIR, 'standings_sidebar.png')
    scaled.save(path)
    print(f"  wrote standings_sidebar.png  ({scaled.width}×{scaled.height})")


def generate_demo_gif():
    """Animated GIF cycling through all display states — used in the README."""
    print("Generating demo.gif ...")
    from image_grid import draw_out_of_town_score_board
    from image_box import draw_wide_box
    from image_standings import draw_standings_sidebar, draw_wildcard_header
    from pitch_view import render_pitch_view

    frames = []

    def _add(img: Image.Image, repeat: int = 1):
        """Add."""
        gray = img.convert('L')
        for _ in range(repeat):
            frames.append(gray)

    with _NO_NETWORK:
        # Frame 1: Pre-game scoreboard
        img = _canvas()
        img = draw_out_of_town_score_board(
            img, PREGAME_GAMES * 3, TEAM_DATA,
            use_logos=False, show_win_prob=False,
        )
        img = draw_wildcard_header(img, _wildcard_teams())
        img = draw_standings_sidebar(img, STANDINGS_DATA, TEAM_DATA, side='left')
        img = draw_standings_sidebar(img, STANDINGS_DATA, TEAM_DATA, side='right')
        _add(img, 4)

        # Frame 2: Live scoreboard
        img = _canvas()
        games = LIVE_GAMES * 3
        img = draw_out_of_town_score_board(
            img, games, TEAM_DATA,
            use_logos=False, show_win_prob=True,
        )
        img = draw_wildcard_header(img, _wildcard_teams())
        img = draw_standings_sidebar(img, STANDINGS_DATA, TEAM_DATA, side='left')
        img = draw_standings_sidebar(img, STANDINGS_DATA, TEAM_DATA, side='right')
        _add(img, 4)

        # Frame 3: Wide cell (featured game)
        img = _canvas()
        img = draw_wide_box(img, 32, 18, _wide_live_game(), TEAM_DATA,
                            use_logos=False, show_win_prob=True)
        img = draw_wildcard_header(img, _wildcard_teams())
        img = draw_standings_sidebar(img, STANDINGS_DATA, TEAM_DATA, side='left')
        img = draw_standings_sidebar(img, STANDINGS_DATA, TEAM_DATA, side='right')
        _add(img, 3)

        # Frame 4: Finals scoreboard
        img = _canvas()
        img = draw_out_of_town_score_board(
            img, FINAL_GAMES, TEAM_DATA,
            use_logos=False, show_win_prob=False,
        )
        img = draw_wildcard_header(img, _wildcard_teams())
        img = draw_standings_sidebar(img, STANDINGS_DATA, TEAM_DATA, side='left')
        img = draw_standings_sidebar(img, STANDINGS_DATA, TEAM_DATA, side='right')
        _add(img, 4)

        # Frame 5: Fields mode grid
        from image_grid import draw_fields_grid as _dfg
        img = Image.new('1', (800, 480), 255)
        img = _dfg(img, LIVE_GAMES * 3, TEAM_DATA)
        _add(img, 3)

        # Frame 6: Pitch view
        img = render_pitch_view(_pitch_fixture())
        _add(img, 3)

    # Downscale to 400×240 to keep GIF size reasonable
    scaled_frames = [f.resize((400, 240), Image.LANCZOS) for f in frames]
    gif_path = os.path.join(DOCS_DIR, 'demo.gif')
    scaled_frames[0].save(
        gif_path,
        save_all=True,
        append_images=scaled_frames[1:],
        loop=0,
        duration=800,   # ms per frame
        optimize=True,
    )
    size_kb = os.path.getsize(gif_path) // 1024
    print(f"  wrote demo.gif  ({size_kb} KB,  {len(scaled_frames)} frames)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """CLI entry point: generate all documentation screenshots into the docs/ directory."""
    print(f"Generating docs screenshots → {DOCS_DIR}/")
    generate_scoreboard_pregame()
    generate_scoreboard_live()
    generate_scoreboard_finals()
    generate_scoreboard_nohitter()
    generate_tile_pregame()
    generate_tile_live()
    generate_tile_live_detail()
    generate_tile_final()
    generate_wide_cell()
    generate_fields_mode()
    generate_pitch_mode()
    generate_scorecard_mode()
    generate_standings_sidebar()
    generate_demo_gif()
    print("\nDone.")


if __name__ == '__main__':
    main()
