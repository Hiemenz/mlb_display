"""
Render the normal scoreboard grid with 3 live games expanded into 3-cell
(triple) tiles, using hand-written example data — no MLB API call.

Standalone CLI:
    python src/example_triple_cell_view.py [--output output/triple_example.bmp] [--dark]
"""
import os
import sys
import argparse
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import image_box
import image_grid
from generate_image import orchestrate_score_board

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_OUTPUT = os.path.join(_REPO_ROOT, 'output', 'triple_example.bmp')

TEAM_DATA = {
    'team_abbreviation': {
        '147': 'NYY', '111': 'BOS', '119': 'LAD', '137': 'SF',
        '133': 'OAK', '144': 'ATL', '158': 'MIL', '112': 'CHC',
    }
}


def _base_game(pk, away_id, home_id, away_runs, home_runs, venue, **overrides):
    g = {
        'game_pk': pk,
        'away_team_id': away_id,
        'home_team_id': home_id,
        'detailed_state': 'Scheduled',
        'away_runs': away_runs,
        'home_runs': home_runs,
        'away_hits': 0,
        'home_hits': 0,
        'away_errors': 0,
        'home_errors': 0,
        'away_team_is_winner': False,
        'home_team_is_winner': False,
        'winner_name': None,
        'loser_name': None,
        'saver_name': None,
        'current_inning': 1,
        'inningState': 'Top',
        'away_inning_runs': [0] * 9,
        'home_inning_runs': [0] * 9,
        'away_team_record_wins': 45,
        'away_team_record_losses': 40,
        'home_team_record_wins': 48,
        'home_team_record_losses': 37,
        'num_of_outs': 0,
        'balls': None,
        'strikes': None,
        'runner_on_first': None,
        'runner_on_second': None,
        'runner_on_third': None,
        'game_start': '7:05 PM',
        'game_datetime': '2026-07-23T23:05:00Z',
        'no_hitter': False,
        'perfect_game': False,
        'save_situation': False,
        'walk_off': False,
        'last_play': None,
        'venue': venue,
        'current_hitter': None,
        'current_pitcher': None,
        'due_up': None,
        'in_hole': None,
        'series_game_number': 1,
        'series_total_games': 3,
    }
    g.update(overrides)
    return g


def _live_game(pk, away_id, home_id, away_runs, home_runs, venue, **overrides):
    g = _base_game(pk, away_id, home_id, away_runs, home_runs, venue,
        detailed_state='In Progress',
        current_inning=6,
        inningState='Bottom',
        num_of_outs=1,
        balls=1,
        strikes=2,
        strike_calls=['C', 'S'],
        runner_on_first='Mookie Betts',
        runner_on_second=None,
        runner_on_third='Freddie Freeman',
        runner_first_number=50,
        runner_second_number=None,
        runner_third_number=5,
        current_pitcher='Logan Webb',
        current_hitter='Will Smith',
        current_play_batter='Will Smith',
        pitch_count=78,
        last_pitch_type='SL',
        last_pitch_speed=86.2,
        batter_hits=1,
        batter_at_bats=3,
        current_at_bat_complete=False,
        ab_pitches=[
            {'seq': 1, 'px': -0.3, 'pz': 2.8, 'sz_top': 3.4, 'sz_bot': 1.6, 'code': 'C', 'pt_abbr': 'FB'},
            {'seq': 2, 'px': 0.9, 'pz': 1.2, 'sz_top': 3.4, 'sz_bot': 1.6, 'code': 'B', 'pt_abbr': 'SL'},
            {'seq': 3, 'px': 0.1, 'pz': 2.5, 'sz_top': 3.4, 'sz_bot': 1.6, 'code': 'S', 'pt_abbr': 'CH'},
        ],
        half_inning_plays=['K', '1B'],
        home_pitcher_ks=['K', 'K', 'L', 'K'],
        away_pitcher_ks=['K', 'L'],
        away_win_probability=47.0,
        home_win_probability=53.0,
    )
    g.update(overrides)
    return g


GAMES = [
    _live_game(1, 147, 111, 3, 2, 'Fenway Park'),
    _live_game(2, 119, 137, 5, 4, 'Oracle Park'),
    _live_game(3, 133, 144, 1, 0, 'Truist Park'),
    _base_game(4, 158, 112, 0, 0, 'Wrigley Field'),
]


def main():
    parser = argparse.ArgumentParser(description='Render 3-triple-cell scoreboard grid from example data')
    parser.add_argument('--output', default=_DEFAULT_OUTPUT)
    parser.add_argument('--dark', action='store_true')
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()

    # Fixed config, independent of config/config.yaml on disk — draw_out_of_town_score_board
    # and several image_box helpers reload config.yaml themselves rather than taking the
    # config dict passed to orchestrate_score_board, so without patching those loads below,
    # this example's output would silently depend on whatever the local config.yaml (and its
    # standings/leaders/news/transactions JSON caches) happens to contain at render time.
    config = {
        'use_team_logos': True,
        'small_logo_x_offset': 2,
        'dark_mode': args.dark,
        'favorite_team_first': False,
        'wide_cell_always': False,
        'wide_cell_featured': False,
        'triple_cell_live': True,
        'primary': '',
        'timezone': 'America/Chicago',
        'show_wildcard_standings': False,
        'show_standings_sidebar': False,
        'show_playoff_bracket': False,
        'show_debug_overlay': False,
        'show_transactions_ticker': False,
        'show_news_panel': False,
        'show_magic_numbers': False,
        'show_leaders_panel': False,
    }

    # Historical mode gates the Final-game linescore window and tomorrow's-game
    # preview, both of which otherwise compare against the real wall clock.
    image_box.set_historical_mode(True)
    with patch.object(image_grid, 'load_yaml_file', return_value=config), \
         patch.object(image_box, 'load_yaml_file', return_value=config):
        result = orchestrate_score_board(GAMES, TEAM_DATA, date_str='2026-07-23', bypass_cache=True, config=config)
    image, _regions = result

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    image.save(args.output)
    print(f"Image saved to {args.output}")

    if args.open:
        image.show()


if __name__ == '__main__':
    main()
