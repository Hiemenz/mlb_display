import os
import json
import random
import time as _time_mod
from datetime import datetime
import pytz
from util import load_json_file, load_yaml_file, save_off_results
from collections import OrderedDict

from image_assets import (
    picdir, _get_font, _logo_small, _load_logo_gray, _logo_ghost, _paste_logo,
    Image, ImageDraw, ImageFont, ImageOps,
)
from image_utils import (
    normalize_dict, standings_dict,
    draw_diamond, draw_circle, check_if_two_chars,
    _last_name, _pitcher_line, _clean_venue_name, _is_game_effectively_over,
    _format_player_name,
)
from image_standings import (
    _WC_STRIP_H,
    derive_wildcard_from_standings, draw_wildcard_header, draw_standings_sidebar,
    draw_standings_sidebar_fullscreen, draw_playoff_bracket_header,
)
from image_box import draw_box, _abbr_play, _draw_linescore_grid, _draw_backwards_k

# Re-export grid display functions for backward compatibility
from image_grid import (
    generate_linescore,
    draw_boards,
    generate_image,
    generate_standings,
    draw_out_of_town_score_board,
)

# Re-export featured/fullscreen functions for backward compatibility
from image_featured import (
    _find_featured_game,
    draw_live_fullscreen_game,
    draw_featured_game_fullscreen,
)

# ---------------------------------------------------------------------------
# logging.basicConfig(level=logging.DEBUG)
# ---------------------------------------------------------------------------


def compare_json_dicts_sorted(dict1, dict2):
    """Compare two JSON dictionaries to see if they are equal, ignoring key order."""
    return json.dumps(dict1, sort_keys=True) == json.dumps(dict2, sort_keys=True)


def load_and_sort_json(json_string):
    """Load JSON data from a string and sort it."""
    return json.loads(json_string, object_pairs_hook=OrderedDict)


def  orchestrate_score_board(game_state_data, team_data, date_str=None, bypass_cache=False, config=None):
    """Returns (image, changed_regions) or None if nothing changed.

    changed_regions is a list of (x, y, w, h) tuples for partial refresh.
    An empty list signals that a full refresh should be used.

    bypass_cache=True skips the unchanged-image check and state persistence.
    Use this when generating GIFs or rendering historical snapshots.
    """
    if config is None:
        config = load_yaml_file('config.yaml')
    use_logos = config.get('use_team_logos', False)
    logo_x_offset = config.get('small_logo_x_offset', 2)
    show_win_prob = config.get('scoreboard_win_probability', False)

    if bypass_cache:
        new_dict = old_dict = None  # skip comparison below
    else:
        old_data = load_json_file('old_scoreboard_state.json')

        new_data_str = json.dumps(game_state_data)
        old_data_str = json.dumps(old_data)

        new_dict = load_and_sort_json(new_data_str)
        old_dict = load_and_sort_json(old_data_str)

        save_off_results(game_state_data, "old_scoreboard_state")

    # Build map of old game data by game_pk for per-game comparison
    old_by_pk = {}
    if not bypass_cache:
        if old_data and isinstance(old_data, list):
            for g in old_data:
                pk = str(g.get('game_pk', ''))
                if pk:
                    old_by_pk[pk] = g

    # Track all games with ANY data change (for partial refresh regions)
    refreshed_game_ids = set()
    for game in game_state_data:
        pk = str(game.get('game_pk', ''))
        if not pk:
            continue
        if old_by_pk.get(pk) != game:
            refreshed_game_ids.add(pk)

    changed_game_ids = set()
    if not bypass_cache:
        # --- Score change detection ---
        old_scores = load_json_file('score_alerts.json')
        new_scores = {}
        for game in game_state_data:
            pk = str(game.get('game_pk', ''))
            if not pk:
                continue
            away_runs = game.get('away_runs')
            home_runs = game.get('home_runs')
            new_scores[pk] = {'away_runs': away_runs, 'home_runs': home_runs}
            if pk in old_scores:
                old_entry = old_scores[pk]
                if away_runs != old_entry.get('away_runs') or home_runs != old_entry.get('home_runs'):
                    changed_game_ids.add(pk)
                    print(f'Score change detected for game {pk}: {old_entry} -> {new_scores[pk]}')
        save_off_results(new_scores, 'score_alerts')
        # --- End score change detection ---

        # Detect when a Final game's linescore window transitions True→False.
        # The visual content (linescore grid vs WP/LP) changes at the 60-min boundary
        # without any change to game_state_data, so the data comparison above won't
        # catch it. We track the window state separately and force a re-render when
        # any game exits the window.
        _final_state_set = {'Final', 'Game Over', 'Final: Tied'}
        _final_times = load_json_file('game_final_times.json') or {}
        _old_win_state = load_json_file('old_linescore_window_state.json') or {}
        _new_win_state = {}
        _linescore_window_changed = False
        _final_linescore_secs = config.get('final_linescore_minutes', 60) * 60
        for _g in game_state_data:
            if _g.get('detailed_state') in _final_state_set:
                _pk = str(_g.get('game_pk', ''))
                if not _pk:
                    continue
                _ft = _final_times.get(_pk)
                if _ft is None:
                    continue
                _end_utc = _g.get('game_end_time_utc')
                if _end_utc:
                    try:
                        _end_dt = pytz.utc.localize(datetime.strptime(_end_utc[:19], "%Y-%m-%dT%H:%M:%S"))
                        _in_win = (datetime.now(pytz.utc) - _end_dt).total_seconds() < _final_linescore_secs
                    except Exception:
                        _in_win = (_time_mod.time() - float(_ft)) < _final_linescore_secs
                else:
                    _in_win = (_time_mod.time() - float(_ft)) < _final_linescore_secs
                _new_win_state[_pk] = _in_win
                if _old_win_state.get(_pk) is True and not _in_win:
                    _linescore_window_changed = True
                    refreshed_game_ids.add(_pk)
                    print(f'Linescore window expired for game {_pk} — forcing re-render')
        save_off_results(_new_win_state, 'old_linescore_window_state')

        if compare_json_dicts_sorted(new_dict, old_dict) and not _linescore_window_changed:
            print('images the same')
            return None

        # In fullscreen mode the display shows only one game, so skip re-render
        # if that specific game's data hasn't changed, even if other games did.
        if os.environ.get('FEATURED_TEAM_FULLSCREEN', '').lower() in ('true', '1', 'yes'):
            primary = config.get('primary', '')
            featured_game = _find_featured_game(game_state_data, team_data, primary)
            if featured_game:
                featured_pk = str(featured_game.get('game_pk', ''))
                old_featured = old_by_pk.get(featured_pk)
                if old_featured is not None and featured_game == old_featured:
                    _feat_linescore_changed = (
                        _old_win_state.get(featured_pk) is True
                        and not _new_win_state.get(featured_pk, False)
                    )
                    if not _feat_linescore_changed:
                        print('images the same (fullscreen — featured game unchanged)')
                        return None

    print('image is different')

    league_mode = config.get('league_mode', 'mlb')

    # --- Featured team full-screen mode ---
    if os.environ.get('FEATURED_TEAM_FULLSCREEN', '').lower() in ('true', '1', 'yes'):
        primary = config.get('primary', '')
        featured_game = _find_featured_game(game_state_data, team_data, primary)
        if featured_game:
            Himage = draw_featured_game_fullscreen(featured_game, team_data, config)
        else:
            Himage = Image.new('1', (800, 480), 255)
            Himage = draw_out_of_town_score_board(Himage, game_state_data, team_data, date_str, changed_game_ids=changed_game_ids, use_logos=use_logos, logo_x_offset=logo_x_offset, show_win_prob=show_win_prob)

        Himage = ImageOps.invert(Himage.convert('L')).convert('1')

        # Partial refresh for live fullscreen: if only bottom-panel fields changed
        # (count, pitch info, pitcher/batter, win %), refresh just y=277..479.
        # Top section (scores, bases, outs) requires a full refresh when it changes.
        _fs_regions = []
        if not bypass_cache and featured_game:
            _ds = featured_game.get('detailed_state', '')
            _is_live_fs = _ds in ('In Progress', 'Player challenge', 'Manager challenge')
            if _is_live_fs:
                _feat_pk = str(featured_game.get('game_pk', ''))
                _old_feat = old_by_pk.get(_feat_pk)
                if _old_feat is not None:
                    _BOTTOM_ONLY = frozenset({
                        'balls', 'strikes', 'strike_calls',
                        'last_pitch_speed', 'last_pitch_type', 'pitch_count',
                        'current_pitcher',
                        'current_play_batter', 'current_hitter',
                        'due_up', 'next_batter_1', 'next_batter_2', 'next_batter_3', 'in_hole',
                        'current_at_bat_complete',
                        'away_win_probability', 'home_win_probability',
                    })
                    _changed_fields = {k for k in set(featured_game) | set(_old_feat)
                                       if featured_game.get(k) != _old_feat.get(k)}
                    if _changed_fields and _changed_fields.issubset(_BOTTOM_ONLY):
                        _fs_regions = [(0, 277, 800, 203)]  # situation area + win% bar

        return (Himage, _fs_regions)

    # --- Normal scoreboard grid ---
    Himage = Image.new('1', (800, 480), 255)
    Himage = draw_out_of_town_score_board(Himage, game_state_data, team_data, date_str, changed_game_ids=changed_game_ids, use_logos=use_logos, logo_x_offset=logo_x_offset, show_win_prob=show_win_prob)

    standings_data = None
    if config.get('show_wildcard_standings', False) or config.get('show_standings_sidebar', False):
        standings_data = load_json_file('standings.json')

    if config.get('show_playoff_bracket', False) and league_mode != 'aaa':
        _bracket = load_json_file('playoff_bracket.json')
        if _bracket and _bracket.get('series'):
            Himage = draw_playoff_bracket_header(Himage, _bracket)
    elif config.get('show_wildcard_standings', False) and league_mode != 'aaa':
        if standings_data and 'standings' in standings_data:
            wildcard_data = derive_wildcard_from_standings(standings_data)
            Himage = draw_wildcard_header(Himage, wildcard_data)

    if config.get('show_standings_sidebar', False):
        if standings_data and 'standings' in standings_data:
            Himage = draw_standings_sidebar(Himage, standings_data, team_data, side='left', league_mode=league_mode)
            Himage = draw_standings_sidebar(Himage, standings_data, team_data, side='right', league_mode=league_mode)

    if config.get('dark_mode', False):
        Himage = ImageOps.invert(Himage.convert('L')).convert('1')

    # --- Compute changed regions from changed_game_ids ---
    # Must use the same game ordering that draw_out_of_town_score_board used,
    # otherwise the favorite-team-first reorder causes grid positions to mismatch.
    x_start = 32
    y_start = 30
    _ordered = list(game_state_data)
    if config.get('favorite_team_first', False):
        _primary = config.get('primary', '')
        if _primary:
            _abbr_map = team_data.get('team_abbreviation', {})
            for _i, _g in enumerate(_ordered):
                _away = _abbr_map.get(str(_g.get('away_team_id', '')), '')
                _home = _abbr_map.get(str(_g.get('home_team_id', '')), '')
                if _primary in (_away, _home):
                    _ordered.insert(0, _ordered.pop(_i))
                    break
    changed_regions = []
    for i, game in enumerate(_ordered):
        if i >= 15:  # 5x3 grid max
            break
        pk = str(game.get('game_pk', ''))
        if pk in refreshed_game_ids:
            col = i % 5
            row = i // 5
            # Align x to 8-pixel boundary
            rx = (col * 150 + x_start) // 8 * 8
            ry = row * 150 + y_start
            rw = 152  # slightly wider to cover alignment rounding (divisible by 8)
            rh = 150
            changed_regions.append((rx, ry, rw, rh))

    # If 10+ cells changed, signal full refresh with empty list; fewer → partial per cell
    if len(changed_regions) >= 10:
        changed_regions = []

    return (Himage, changed_regions)
