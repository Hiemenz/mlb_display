"""
Render scoreboard image from cached data/games.json.
Does NOT call the MLB API — run fetch_games.py first.

Standalone CLI:
    python src/render_scoreboard.py [--date 2025-04-01] [--mode scorecard|pitch|scoreboard]
                                    [--output output/test.bmp] [--open] [--config PATH]
"""
import os
import sys
import argparse

# Allow running as a standalone script from any directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageChops
from util import load_json_file
from config_loader import load_config, add_config_arg
from generate_image import orchestrate_score_board
from game_detail_fetch import select_game, fetch_scorecard_data, fetch_pitch_view_data
from scorecard_view import render_scorecard_view
from pitch_view import render_pitch_view
from image_derby import render_derby_bracket
from image_grid import draw_fields_grid

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_OUTPUT = os.path.join(_REPO_ROOT, 'resulting_image.bmp')


_VALID_MODES = ('scoreboard', 'linescore', 'scorecard', 'pitch', 'derby', 'fields')


def _get_display_mode(config):
    """Determine display mode from config or DISPLAY_MODE env var (env wins)."""
    env_mode = os.environ.get('DISPLAY_MODE', '').strip().lower()
    if env_mode in _VALID_MODES:
        return env_mode
    mode = config.get('display_mode')
    if mode and mode in _VALID_MODES:
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

    # dark_mode is injected by main.py (auto day/night); fall back to False for standalone CLI use.
    dark_mode = config.get('dark_mode', False)

    away_id = str(game.get('away_team_id', ''))
    home_id = str(game.get('home_team_id', ''))
    away_abbr = team_data.get('team_abbreviation', {}).get(away_id, '')
    home_abbr = team_data.get('team_abbreviation', {}).get(home_id, '')
    print(f"Selected game: {away_abbr} @ {home_abbr} (pk={game_pk}, mode={mode})")

    try:
        if mode == 'pitch':
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


def _pixel_diff_bands(old_img, new_img, row_gap=4):
    """Return tight (x, y, w, h) rectangles for every cluster of changed pixels.

    Algorithm:
      1. Pixel-diff the two images (converted to 8-bit grayscale).
      2. Per row: find the leftmost and rightmost changed pixel (if any).
      3. Group contiguous changed rows — tolerating up to `row_gap` unchanged
         rows between them — into a band.
      4. Per band: take the union of each row's x-range for the tightest box.
      5. Align x down and x+w up to 8-pixel boundaries (e-ink driver requirement).

    Returns:
        list of (x, y, w, h)  — partial-refresh exactly these rectangles
        []                     — >70 % of rows changed; caller should full-refresh
        None                   — exception; caller keeps its own region list
    """
    try:
        W, H = new_img.size
        diff = ImageChops.difference(old_img.convert('L'), new_img.convert('L'))
        raw = diff.tobytes()   # one byte per pixel in 'L' mode

        # Build per-row (min_x, max_x) for every row that has at least one change
        row_x: dict[int, tuple[int, int]] = {}
        for y in range(H):
            row = raw[y * W: y * W + W]
            # Short-circuit: skip unchanged rows cheaply
            if not any(row):
                continue
            min_x = next(x for x, b in enumerate(row) if b)
            max_x = W - 1 - next(x for x, b in enumerate(reversed(row)) if b)
            row_x[y] = (min_x, max_x)

        if not row_x:
            return []

        changed_rows = sorted(row_x)
        if len(changed_rows) > H * 0.70:   # too much changed → full-screen partial
            return [(0, 0, W, H)]

        # Group rows into bands and track the union x-range per band
        bands = []
        start = prev = changed_rows[0]
        bx0, bx1 = row_x[start]

        for y in changed_rows[1:]:
            if y - prev > row_gap:
                # Align to 8-pixel boundaries required by the e-ink driver
                xa = (bx0 // 8) * 8
                xb = ((bx1 + 8) // 8) * 8
                bands.append((xa, start, xb - xa, prev - start + 1))
                start = y
                bx0, bx1 = row_x[y]
            else:
                mx0, mx1 = row_x[y]
                bx0 = min(bx0, mx0)
                bx1 = max(bx1, mx1)
            prev = y

        xa = (bx0 // 8) * 8
        xb = ((bx1 + 8) // 8) * 8
        bands.append((xa, start, xb - xa, prev - start + 1))
        return bands
    except Exception:
        return None   # caller falls back to its own region list


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

    if mode in ('scorecard', 'pitch'):
        image = _render_single_game_mode(mode, game_state_data, team_data, config, output_path)
        if image:
            return (image, [(0, 0, image.width, image.height)])
        return None

    if mode == 'derby':
        derby_data = load_json_file('derby_bracket.json')
        if not derby_data:
            print("No derby_bracket.json data found")
            return None
        dark_mode = config.get('dark_mode', False)
        image = render_derby_bracket(derby_data, dark_mode=dark_mode)
        if output_path:
            image.save(output_path)
            print(f"Image saved to {output_path}")
        return (image, [(0, 0, image.width, image.height)])

    if mode == 'fields':
        image = Image.new('1', (800, 480), 255)
        image = draw_fields_grid(image, game_state_data, team_data)
        if output_path:
            image.save(output_path)
            print(f"Image saved to {output_path}")
        return (image, [(0, 0, 800, 480)])

    # Snapshot the current saved image before overwriting so we can pixel-diff it.
    # Only used for the fullscreen single-game display where partial updates are
    # most valuable; the multi-game scoreboard already uses per-cell regions.
    _is_fullscreen = os.environ.get('FEATURED_TEAM_FULLSCREEN', '').lower() in ('true', '1', 'yes')
    _old_snap = None
    if _is_fullscreen and not bypass_cache and os.path.isfile(output_path):
        try:
            _old_snap = Image.open(output_path).copy()
        except Exception:
            pass

    result = orchestrate_score_board(game_state_data, team_data, date_str, bypass_cache=bypass_cache, config=config)
    if result:
        image, changed_regions = result

        # Fullscreen: replace zone-based regions with pixel-exact diff bands.
        # _pixel_diff_bands returns None on error (keep zone-based fallback),
        # [] when too much changed or nothing changed (full refresh), or a
        # list of (x, y, w, h) bands for a precise partial refresh.
        if _is_fullscreen and _old_snap is not None and _old_snap.size == image.size:
            _bands = _pixel_diff_bands(_old_snap, image)
            if _bands is not None:
                changed_regions = _bands
                if _bands:
                    total_h = sum(b[3] for b in _bands)
                    print(f"Pixel diff: {len(_bands)} band(s), {total_h}px of {image.size[1]}px refreshed")

        image.save(output_path)
        print(f"Image saved to {output_path}")
        return (image, changed_regions)

    return None


def main():
    """CLI entry point: render the scoreboard image from cached data/games.json."""
    parser = argparse.ArgumentParser(
        description='Render scoreboard image from cached data/games.json',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python src/render_scoreboard.py
  python src/render_scoreboard.py --mode scorecard
  python src/render_scoreboard.py --date 2025-04-01 --output output/test.bmp --open
        ''',
    )
    parser.add_argument('--date', type=str, help='Date string for scoreboard header')
    parser.add_argument('--mode', type=str,
                        choices=['scoreboard', 'linescore', 'scorecard', 'pitch', 'derby', 'fields'],
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


if __name__ == '__main__':  # pragma: no cover
    main()
