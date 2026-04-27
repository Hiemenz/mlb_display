"""
Render scoreboard image from cached data/games.json.
Does NOT call the MLB API — run fetch_games.py first.

Standalone CLI:
    python src/render_scoreboard.py [--date 2025-04-01] [--mode field|scorecard|pitch|scoreboard]
                                    [--output output/test.bmp] [--open] [--config PATH]
"""
import os
import sys
import argparse

# Allow running as a standalone script from any directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from util import load_json_file
from config_loader import load_config, add_config_arg
from generate_image import orchestrate_score_board
from game_detail_fetch import select_game, fetch_field_view_data, fetch_scorecard_data, fetch_pitch_view_data
from field_view import render_field_view
from scorecard_view import render_scorecard_view
from pitch_view import render_pitch_view

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_OUTPUT = os.path.join(_REPO_ROOT, 'resulting_image.bmp')


def _get_display_mode(config):
    """Determine display mode from config."""
    mode = config.get('display_mode')
    if mode and mode in ('scoreboard', 'linescore', 'field', 'scorecard', 'pitch'):
        return mode
    if config.get('scoreboard', True):
        return 'scoreboard'
    return 'linescore'


def _render_single_game_mode(mode, game_state_data, team_data, config, output_path=None):
    """Render field/scorecard/pitch view for a single game. Returns image or None."""
    favorite = config.get('primary', '')
    game = select_game(game_state_data, favorite, team_data)
    if not game:
        print("No game found for single-game display mode")
        return None

    game_pk = game.get('game_pk')
    if not game_pk:
        print("No game_pk found")
        return None

    dark_mode = config.get('dark_mode', False)

    away_id = str(game.get('away_team_id', ''))
    home_id = str(game.get('home_team_id', ''))
    away_abbr = team_data.get('team_abbreviation', {}).get(away_id, '')
    home_abbr = team_data.get('team_abbreviation', {}).get(home_id, '')
    print(f"Selected game: {away_abbr} @ {home_abbr} (pk={game_pk}, mode={mode})")

    try:
        if mode == 'field':
            data = fetch_field_view_data(game_pk)
            image = render_field_view(data, dark_mode=dark_mode)
        elif mode == 'pitch':
            data = fetch_pitch_view_data(game_pk)
            image = render_pitch_view(data, dark_mode=dark_mode)
        else:
            data = fetch_scorecard_data(game_pk)
            image = render_scorecard_view(data, dark_mode=dark_mode)

        if output_path:
            image.save(output_path)
            print(f"Image saved to {output_path}")

        return image
    except Exception as e:
        print(f"Error generating {mode} view: {e}")
        import traceback
        traceback.print_exc()
        return None


def render(config, date_str=None, output_path=None, bypass_cache=False):
    """
    Render display from cached data/games.json.

    Args:
        config: Config dict
        date_str: Date string for scoreboard header (optional)
        output_path: Where to save the output image (default: resulting_image.bmp)
        bypass_cache: If True, always regenerate even if data is unchanged.

    Returns:
        (PIL.Image, changed_regions) tuple, or None if no update needed.
    """
    if output_path is None:
        output_path = _DEFAULT_OUTPUT

    game_state_data = load_json_file('games.json').get('games', [])
    team_data = load_json_file('teams.json')
    if not team_data or 'team_abbreviation' not in team_data:
        team_data = {'team_abbreviation': {}}

    mode = _get_display_mode(config)

    if mode in ('field', 'scorecard', 'pitch'):
        image = _render_single_game_mode(mode, game_state_data, team_data, config, output_path)
        if image:
            return (image, [])
        return None

    result = orchestrate_score_board(game_state_data, team_data, date_str, bypass_cache=bypass_cache)
    if result:
        image, changed_regions = result
        image.save(output_path)
        print(f"Image saved to {output_path}")
        return (image, changed_regions)

    return None


def main():
    parser = argparse.ArgumentParser(
        description='Render scoreboard image from cached data/games.json',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python src/render_scoreboard.py
  python src/render_scoreboard.py --mode field
  python src/render_scoreboard.py --date 2025-04-01 --output output/test.bmp --open
        ''',
    )
    parser.add_argument('--date', type=str, help='Date string for scoreboard header')
    parser.add_argument('--mode', type=str,
                        choices=['scoreboard', 'linescore', 'field', 'scorecard', 'pitch'],
                        help='Display mode override')
    parser.add_argument('--output', type=str, default=None,
                        help=f'Output image path (default: {_DEFAULT_OUTPUT})')
    parser.add_argument('--open', action='store_true',
                        help='Auto-open image after rendering (macOS)')
    add_config_arg(parser)
    args = parser.parse_args()

    config = load_config(args.config)
    if args.mode:
        config['display_mode'] = args.mode

    output_path = args.output or _DEFAULT_OUTPUT
    result = render(config, date_str=args.date, output_path=output_path)

    if result:
        image, changed_regions = result
        print(f"\n✓ Image written to {output_path}")
        if args.open:
            import platform
            if platform.system() == 'Darwin':
                import subprocess
                subprocess.run(['open', output_path], check=False)
    else:
        print("No output generated")


if __name__ == '__main__':
    main()
