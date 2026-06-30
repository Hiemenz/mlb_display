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
    draw_standings_sidebar_fullscreen,
)
from image_box import draw_box, _abbr_play, _draw_linescore_grid, _draw_backwards_k

# Re-export grid display functions for backward compatibility
from image_grid import (
    generate_linescore,
    draw_boards,
    generate_image,
    generate_standings,
    draw_out_of_town_score_board,
    compute_grid_layout,
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

        # Partial refresh for live fullscreen: map changed fields to display zones and
        # refresh only the affected zones.  Three zones:
        #   Header  y=0..75   — inning label, last-play event
        #   Score   y=69..276 — R/H/E rows, bases, outs, challenges
        #   Bottom  y=277..479 — B/S/O, pitch info, pitcher/batter, win %
        # (Header and Score overlap slightly at y=69..75 to cover the thick divider line.)
        # If all three zones change, fall back to a full refresh (empty list).
        _fs_regions = []
        if not bypass_cache and featured_game:
            _ds = featured_game.get('detailed_state', '')
            _is_live_fs = _ds in ('In Progress', 'Player challenge', 'Manager challenge')
            if _is_live_fs:
                _feat_pk = str(featured_game.get('game_pk', ''))
                _old_feat = old_by_pk.get(_feat_pk)
                if _old_feat is not None:
                    _HEADER_FIELDS = frozenset({
                        'inningState', 'inningHalf', 'current_inning', 'currentInningOrdinal',
                        'last_play', 'last_review_result', 'last_play_description',
                        'sub_event', 'last_play_rbi',
                    })
                    _SCORE_FIELDS = frozenset({
                        'away_runs', 'home_runs', 'away_hits', 'home_hits',
                        'away_errors', 'home_errors',
                        'runner_on_first', 'runner_on_second', 'runner_on_third',
                        'runner_first_number', 'runner_second_number', 'runner_third_number',
                        'num_of_outs',
                        'away_challenges_remaining', 'home_challenges_remaining',
                        'away_replay_remaining', 'home_replay_remaining', 'abs_challenge_max',
                        'save_situation', 'detailed_state',
                    })
                    _BOTTOM_FIELDS = frozenset({
                        'balls', 'strikes', 'strike_calls',
                        'last_pitch_speed', 'last_pitch_type', 'pitch_count',
                        'current_pitcher',
                        'current_play_batter', 'current_hitter',
                        'due_up', 'next_batter_1', 'next_batter_2', 'next_batter_3', 'in_hole',
                        'current_at_bat_complete', 'next_pitcher',
                        'away_win_probability', 'home_win_probability',
                        'away_inning_runs', 'home_inning_runs',
                        'inningState', 'inningHalf', 'current_inning',
                        'num_of_outs',
                    })
                    _ALL_KNOWN = _HEADER_FIELDS | _SCORE_FIELDS | _BOTTOM_FIELDS
                    _changed_fields = {k for k in set(featured_game) | set(_old_feat)
                                       if featured_game.get(k) != _old_feat.get(k)}
                    if _changed_fields and not (_changed_fields - _ALL_KNOWN):
                        _zones = []
                        if _changed_fields & _HEADER_FIELDS:
                            _zones.append((0, 0, 800, 76))    # header + thick border
                        if _changed_fields & _SCORE_FIELDS:
                            _zones.append((0, 69, 800, 208))  # R/H/E rows through divider
                        if _changed_fields & _BOTTOM_FIELDS:
                            _zones.append((0, 277, 800, 203)) # situation + win% bar
                        if len(_zones) < 3:
                            _fs_regions = _zones
                        else:
                            _fs_regions = [(0, 0, 800, 480)]  # all zones → full-screen partial

        return (Himage, _fs_regions)

    # --- Normal scoreboard grid ---
    Himage = Image.new('1', (800, 480), 255)
    Himage = draw_out_of_town_score_board(Himage, game_state_data, team_data, date_str, changed_game_ids=changed_game_ids, use_logos=use_logos, logo_x_offset=logo_x_offset, show_win_prob=show_win_prob)

    standings_data = None
    if config.get('show_wildcard_standings', False) or config.get('show_standings_sidebar', False):
        standings_data = load_json_file('standings.json')

    if config.get('show_wildcard_standings', False) and league_mode != 'aaa':
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
    # Use the exact same layout draw_out_of_town_score_board used, so wide
    # (2-cell) games — which consume two slot units and may be reordered —
    # get a region that covers the whole tile rather than only its left half.
    x_start = 32
    y_start = 30
    _ordered, _slots = compute_grid_layout(game_state_data, team_data, config)
    changed_regions = []
    for game, slot_info in zip(_ordered, _slots):
        slot_type, gx, gy = slot_info
        pk = str(game.get('game_pk', ''))
        if pk in refreshed_game_ids:
            # Align x to 8-pixel boundary
            rx = (gx * 150 + x_start) // 8 * 8
            ry = gy * 150 + y_start
            # Wide tiles span 2 columns (≈300px); normal tiles span 1 (150px).
            # Pad to cover 8px alignment rounding and keep width divisible by 8.
            rw = 304 if slot_type == 'wide' else 152
            rh = 150
            changed_regions.append((rx, ry, rw, rh))

    # If 10+ cells changed, refresh the whole canvas as one partial region
    if len(changed_regions) >= 10:
        changed_regions = [(0, 0, 800, 480)]

    return (Himage, changed_regions)
