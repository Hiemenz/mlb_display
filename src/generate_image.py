import os
import json
import random
import time as _time_mod
from datetime import datetime, timezone
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


def _get_system_uptime():
    """Return system uptime string ('Xh Ym') or '' if unavailable."""
    try:
        with open('/proc/uptime') as f:
            secs = float(f.read().split()[0])
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        return f"{h}h {m}m"
    except Exception:
        return ''


_DEBUG_STALE_HOURS = 2  # fetch age threshold before overlay turns inverted/alarmed


def _fetch_skip_is_expected(config, sched):
    """Return True when a long gap since the last fetch is normal and expected.

    Three cases suppress the stale alarm:
    - Night mode is enabled and we are currently inside the night window, so
      fetching is intentionally paused.
    - We're in the morning alternating window (night_end - morning_end):
      main.py intentionally re-shows yesterday's already-final results on
      alternating cycles here, so a fetch gap inherited from the overnight
      quiet period is expected, not a sign anything is broken.
    - Smart polling determined there are no games until a future date, so
      the display is legitimately sitting out until then.
    """
    # Night window check
    if config.get('night_mode', False):
        try:
            night_start = config.get('night_start', 0)
            night_end = config.get('night_end', 7)
            tz = pytz.timezone(config.get('timezone', 'America/Chicago'))
            hour = datetime.now(tz).hour
            in_night = (
                hour >= night_start or hour < night_end
                if night_start >= night_end
                else night_start <= hour < night_end
            )
            if in_night:
                return True
        except Exception:
            pass

    # Morning alternating window check (mirrors main.py's date-selection logic)
    try:
        tz = pytz.timezone(config.get('timezone', 'America/Chicago'))
        now = datetime.now(tz)
        is_weekend = now.weekday() >= 5
        morning_end = (config.get('morning_end_weekend', 11) if is_weekend
                       else config.get('morning_end', 9))
        morning_start = config.get('night_end', 7)
        if morning_start <= now.hour < morning_end:
            return True
    except Exception:
        pass

    # Off-day / between-season skip
    next_game_date = sched.get('next_game_date')
    if next_game_date:
        try:
            today = datetime.now(timezone.utc).date().isoformat()
            if next_game_date > today:
                return True
        except Exception:
            pass

    return False


def _draw_debug_overlay(Himage, config):
    """Draw an uptime + last-fetch alarm in the bottom-right corner, but only
    once the fetch is actually stale (>2h since last fetch, and a fetch was
    expected) — "up 4h 12m  stale 3h 5m" in an inverted black box, white
    text, impossible to miss. Below that threshold this draws nothing, so
    the corner stays clean during normal operation instead of always
    showing a clock/uptime readout nobody needs to see.

    The alarm is suppressed during the night-mode window and on off-days
    (when smart polling has determined there are no games) to avoid false
    positives when long fetch gaps are intentional.
    """
    draw = ImageDraw.Draw(Himage)
    font = _get_font(9)

    uptime = _get_system_uptime()
    sched = load_json_file('schedule_state.json')
    last_fetch_iso = sched.get('last_game_fetch', '')

    fetch_age_hours = None
    if last_fetch_iso:
        try:
            dt = datetime.fromisoformat(last_fetch_iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            fetch_age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        except Exception:
            pass

    stale = (
        fetch_age_hours is not None
        and fetch_age_hours >= _DEBUG_STALE_HOURS
        and not _fetch_skip_is_expected(config, sched)
    )
    if not stale:
        return Himage

    h = int(fetch_age_hours)
    m = int((fetch_age_hours % 1) * 60)
    parts = []
    if uptime:
        parts.append(f"up {uptime}")
    parts.append(f"stale {h}h {m}m")
    text = '  '.join(parts)

    W, H = Himage.size
    tw = int(font.getlength(text))
    x = W - tw - 4
    y = H - 12

    # Inverted box: black background, white text — hard to miss
    draw.rectangle([x - 2, y - 2, x + tw + 2, y + 11], fill=0)
    draw.text((x, y), text, font=font, fill=255)

    return Himage


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
    # Compute the grid layout once and share it with both the renderer and the
    # partial-refresh region/reshuffle-detection math below — two independent
    # compute_grid_layout() calls can silently diverge (e.g. config.yaml
    # edited mid-render by the phone config server), leaving stale/blank
    # cells behind since the refresh regions would no longer match what was
    # actually drawn.
    _ordered, _slots = compute_grid_layout(game_state_data, team_data, config)
    Himage = draw_out_of_town_score_board(Himage, game_state_data, team_data, date_str, changed_game_ids=changed_game_ids, use_logos=use_logos, logo_x_offset=logo_x_offset, show_win_prob=show_win_prob, layout=(_ordered, _slots))

    standings_data = None
    if config.get('show_wildcard_standings', False) or config.get('show_standings_sidebar', False):
        standings_data = load_json_file('standings.json')

    # Playoff bracket auto-toggles on: it takes over the header strip only
    # when there's an actual current-season bracket to show (fetched by
    # main.py during the postseason calendar window), not just because the
    # config flag defaults to True — otherwise wildcard standings would
    # never render for the ~10 months a year there's no bracket data yet.
    _bracket = None
    if config.get('show_playoff_bracket', True) and league_mode != 'aaa':
        _candidate = load_json_file('playoff_bracket.json')
        if _candidate and _candidate.get('series') and _candidate.get('season') == datetime.now().year:
            _bracket = _candidate

    if _bracket:
        Himage = draw_playoff_bracket_header(Himage, _bracket)
    elif config.get('show_wildcard_standings', False) and league_mode != 'aaa':
        if standings_data and 'standings' in standings_data:
            wildcard_data = derive_wildcard_from_standings(standings_data)
            Himage = draw_wildcard_header(Himage, wildcard_data)

    if config.get('show_standings_sidebar', False):
        if standings_data and 'standings' in standings_data:
            Himage = draw_standings_sidebar(Himage, standings_data, team_data, side='left', league_mode=league_mode)
            Himage = draw_standings_sidebar(Himage, standings_data, team_data, side='right', league_mode=league_mode)

    if config.get('show_debug_overlay', False):
        Himage = _draw_debug_overlay(Himage, config)

    if config.get('dark_mode', False):
        Himage = ImageOps.invert(Himage.convert('L')).convert('1')

    # --- Compute changed regions from changed_game_ids ---
    # Reuses the exact _ordered/_slots draw_out_of_town_score_board was given
    # above, so wide (2-cell) games — which consume two slot units and may be
    # reordered — get a region that covers the whole tile rather than only
    # its left half.
    x_start = 32
    y_start = 30
    changed_regions = []
    for game, slot_info in zip(_ordered, _slots):
        slot_type, gx, gy = slot_info
        pk = str(game.get('game_pk', ''))
        if pk in refreshed_game_ids:
            # Align x to 8-pixel boundary
            rx = (gx * 150 + x_start) // 8 * 8
            ry = gy * 150 + y_start
            # Triple tiles span 3 columns (≈435px); wide 2 (≈300px); normal 1 (150px).
            # Pad to cover 8px alignment rounding and keep width divisible by 8.
            if slot_type == 'triple':
                rw = 440
            elif slot_type == 'wide':
                rw = 304
            else:
                rw = 152
            rh = 150
            changed_regions.append((rx, ry, rw, rh))

    # If 10+ cells changed, refresh the whole canvas as one partial region
    if len(changed_regions) >= 10:
        changed_regions = [(0, 0, 800, 480)]

    # A game can shift to a different cell purely because another game's live
    # state changed the grid packing (see _pack_grid in image_grid.py) — its
    # own data is identical, so it's never in refreshed_game_ids and its old
    # cell never gets marked for partial refresh. Partial refresh only
    # touches the regions we hand it, so that old cell keeps showing the
    # stale game underneath (ghosting) until something else happens to touch
    # it. Detect any such reshuffle and signal main.py to force a true full
    # (flashing) refresh instead, which repaints the entire screen.
    layout_changed = False
    if not bypass_cache:
        new_positions = {
            str(game.get('game_pk', '')): list(slot_info)
            for game, slot_info in zip(_ordered, _slots)
            if game.get('game_pk', '')
        }
        old_positions = load_json_file('old_grid_positions.json') or {}
        layout_changed = new_positions != old_positions
        save_off_results(new_positions, 'old_grid_positions')
        save_off_results({'needed': layout_changed}, 'force_full_refresh')

    return (Himage, changed_regions)
