import math as _math
import re as _re
import time as _time
from dataclasses import dataclass, field
from typing import Optional
import pytz
from collections import namedtuple
from datetime import datetime as _datetime

from PIL import Image, ImageDraw, ImageOps

from image_assets import (
    _get_font, _logo_small, _logo_ghost, _paste_logo,
    _load_codepoint_ghost, _TEAM_ID_ABBR_OVERRIDE, _PPD_EMOJI_CODEPOINTS, _SUSP_EMOJI_CODEPOINTS,
)
from image_utils import (
    draw_diamond, draw_circle, draw_tight_number, check_if_two_chars,
    _format_player_name, _last_name, _pitcher_line, _clean_venue_name,
    _is_game_effectively_over,
)
from util import load_json_file, load_yaml_file, save_off_results
from stadium_polygons import get_polygon as _field_get_polygon
from stadium_polygons import get_infield_polygon as _field_get_infield_polygon

_final_time_cache: dict = {}       # game_pk (str) -> unix timestamp, in-memory layer
_historical_mode = False     # True for --date replays: skip linescore window

# Maps verbose MLB API event names (lowercased) to short header abbreviations.
# Checked with `key in raw.lower()` so partial matches work (e.g. "stolen base 2b" → "SB").
_PLAY_ABBR = {
    'grounded into dp': 'GDP',
    'triple play':      'TP',
    'double play':      'DP',
    'home run':         'HR',
    'triple':           '3B',
    'double':           '2B',
    'single':           '1B',
    'intentional walk': 'IBB',
    'hit by pitch':     'HBP',
    'walk':             'BB',
    'strikeout looking': 'Kl',
    'strikeout':        'K',
    'sac fly':          'SAC F',
    'sacrifice fly':    'SAC F',
    'sac bunt':         'SAC B',
    'sacrifice bunt':   'SAC B',
    'stolen base':      'SB',
    'caught stealing':  'CS',
    'wild pitch':       'WP',
    'passed ball':      'PB',
    "fielder's choice": 'FC',
    'fielders choice':  'FC',
    'field error':      'E',
    'call overturned':  'OVERTURN',
    'call stands':      'STANDS',
    'flyout':           'FO',
    'fly out':          'FO',
    'lineout':          'LO',
    'line out':         'LO',
    'groundout':        'GO',
    'ground out':       'GO',
    'pop out':          'PO',
    'popout':           'PO',
    'pickoff':          'PK',
    'balk':             'BLK',
    'forceout':         'FOUT',
    'force out':        'FOUT',
    'field out':        'FO',
    'runner out':       'RO',
    'infield fly':      'IF',
    'interference':     'INT',
}


def _abbr_play(raw):
    """Return a short abbreviation for a verbose MLB play-event string."""
    if not raw:
        return raw
    lower = raw.lower()
    for key, abbr in _PLAY_ABBR.items():
        if key in lower:
            return abbr
    return raw


# Ordered longest-first so "left fielder" matches before "fielder", etc.
_POS_KEYWORDS = [
    ('center fielder',  '8'),
    ('right fielder',   '9'),
    ('left fielder',    '7'),
    ('first baseman',   '3'),
    ('second baseman',  '4'),
    ('third baseman',   '5'),
    ('shortstop',       '6'),
    ('catcher',         '2'),
    ('pitcher',         '1'),
]


def _fielder_from_desc(description):
    """Return the primary (putout) fielder position code from a play description."""
    if not description:
        return ''
    dl = description.lower()
    for kw, code in _POS_KEYWORDS:
        if kw in dl:
            return code
    return ''


def _fielder_seq_from_desc(description, max_pos=5):
    """Return a fielder position sequence from a play description (up to max_pos fielders).

    Finds every occurrence of each position keyword in order so repeated touches
    (e.g. catcher in a rundown) are captured correctly.
    """
    if not description:
        return ''
    dl = description.lower()
    hits = []
    for kw, code in _POS_KEYWORDS:
        start = 0
        while True:
            idx = dl.find(kw, start)
            if idx < 0:
                break
            hits.append((idx, code))
            start = idx + 1
    hits.sort()
    if hits:
        return '-'.join(h[1] for h in hits[:max_pos])
    return ''


def _draw_backwards_k(img, x, y, fnt, fill=0):
    """Paste a horizontally-mirrored 'K' glyph at text anchor (x, y) on a mode-'1' img."""
    bbox = fnt.getbbox('K')
    ox, oy, ox2, oy2 = bbox
    gw, gh = ox2 - ox, oy2 - oy
    pad = 2
    # Render in mode '1' to match the main image — avoids anti-aliasing artifacts
    tmp = Image.new('1', (gw + 2 * pad, gh + 2 * pad), 255)
    ImageDraw.Draw(tmp).text((-ox + pad, -oy + pad), 'K', font=fnt, fill=0)
    tmp = tmp.transpose(Image.FLIP_LEFT_RIGHT)
    # Build mask: 255 where glyph is black, 0 where background is white
    mask = ImageOps.invert(tmp.convert('L'))
    px, py = x + ox - pad, y + oy - pad
    img.paste(fill, (px, py, px + gw + 2 * pad, py + gh + 2 * pad), mask)


def _draw_out_labels_in_circles(draw, Himage, cx_list, cy, outs_list, labels, s):
    """Draw scorecard labels centered inside each filled out circle (white on black).

    White fill (255) matches the runner-number convention: light mode shows white
    text on black circles; dark mode inverts the whole image so it becomes black
    text on white circles."""
    fnt = _get_font(max(7 * s, 7))
    max_w = 10 * s
    for i, (lbl, filled) in enumerate(zip(labels[:3], outs_list)):
        if not (filled and lbl):
            continue
        cx = cx_list[i]
        if lbl == 'Kl':
            bb = fnt.getbbox('K')
            tx = cx - (bb[0] + bb[2] - 1) // 2
            ty = cy - (bb[1] + bb[3] - 1) // 2
            _draw_backwards_k(Himage, tx, ty, fnt, fill=255)
            _draw_backwards_k(Himage, tx + 1, ty, fnt, fill=255)
            _draw_backwards_k(Himage, tx, ty + 1, fnt, fill=255)
            _draw_backwards_k(Himage, tx + 1, ty + 1, fnt, fill=255)
        else:
            disp = lbl
            while disp and int(fnt.getlength(disp)) > max_w:
                disp = disp[:-1]
            if not disp:
                continue
            draw_tight_number(draw, cx, cy, disp, fnt, 255, bold=True)


def set_historical_mode(enabled=True):
    """Set historical mode."""
    global _historical_mode
    _historical_mode = enabled


def _get_or_set_final_time(game_pk):
    """Return (and persist) the unix timestamp when game_pk first went Final."""
    pk = str(game_pk)
    if pk in _final_time_cache:
        return _final_time_cache[pk]
    stored = load_json_file('game_final_times.json') or {}
    if pk in stored:
        _final_time_cache[pk] = float(stored[pk])
        return _final_time_cache[pk]
    ts = _time.time()
    _final_time_cache[pk] = ts
    stored[pk] = ts
    save_off_results(stored, 'game_final_times')
    return ts


def _draw_linescore_grid(draw, Himage, start_x, start_y, game_data, team_data, use_logos, scale=1):
    """Per-inning linescore grid for between-inning scoreboard tiles.

    Standard games: 10 cells (1 logo + 9 inning) × 12px = 120px centred in 135px box.
    Extra-inning games: expand to 11 cells (+ 10th column) when current_inning >= 10,
    then slide the window for innings beyond 10 so the current inning stays rightmost.
    Row dividers span the full box width for a clean framed look.
    """
    s = scale
    BOX_W      = 135 * s   # full tile width
    COL_W      = 12 * s    # all cells equal width
    LOGO_COL_W = COL_W     # logo column same width as inning columns
    ROW_H_HDR  = 14 * s
    ROW_H_TEAM = 16 * s

    current_inning = game_data.get('current_inning') or 1
    # Expand to 10 inning columns once extra innings begin; slide window beyond that
    N_COLS    = 10 if current_inning >= 10 else 9
    first_inn = max(1, current_inning - N_COLS + 1) if current_inning > N_COLS else 1

    # Centre the grid (logo col + N_COLS inning cols) inside the 135px box
    _total_w  = LOGO_COL_W + N_COLS * COL_W
    grid_x0   = start_x + (BOX_W - _total_w) // 2

    y0 = start_y + 83 * s            # grid top
    y1 = y0 + ROW_H_HDR              # away row top
    y2 = y1 + ROW_H_TEAM             # home row top
    y3 = y2 + ROW_H_TEAM             # grid bottom

    away_inn = game_data.get('away_inning_runs') or []
    home_inn = game_data.get('home_inning_runs') or []

    font9  = _get_font(9 * s)
    font11 = _get_font(11 * s)

    grid_x0 + _total_w

    # --- horizontal row dividers span full box width ---
    draw.line((start_x, y1, start_x + BOX_W, y1), fill=0)
    draw.line((start_x, y2, start_x + BOX_W, y2), fill=0)

    # --- vertical column dividers within the centred grid ---
    draw.line((grid_x0 + LOGO_COL_W, y0, grid_x0 + LOGO_COL_W, y3), fill=0)
    for k in range(1, N_COLS):
        vx = grid_x0 + LOGO_COL_W + k * COL_W
        draw.line((vx, y0, vx, y3), fill=0)

    def _draw_centered(fnt, val, cx, cy):
        """Draw val pixel-centered at (cx, cy) by scanning actual rendered ink bounds.

        getbbox() returns the advance-width cell for this bitmap/pixel font (all digits
        share the same box), so centering by bounding-box width leaves narrow glyphs
        like '1' visually off-center.  Rendering to a scratch buffer at a known anchor
        (ox, oy) and measuring the real ink extents gives ≤0.5 px accuracy in both axes.
        """
        txt = str(val)
        if not txt:  # pragma: no cover
            return
        try:
            bb = fnt.getbbox(txt)
            ox, oy = 2, 2          # guard border; draw at (ox, oy) so subtracting them
            buf_w = max(bb[2] + ox + 2, 6)   # gives center relative to draw position
            buf_h = max(bb[3] + oy + 2, 6)
            buf = Image.new('L', (buf_w, buf_h), 255)
            ImageDraw.Draw(buf).text((ox, oy), txt, font=fnt, fill=0)
            bpx = buf.load()
            ink_xs = [c for r in range(buf_h) for c in range(buf_w) if bpx[c, r] < 128]
            ink_ys = [r for r in range(buf_h) for c in range(buf_w) if bpx[c, r] < 128]
            if not ink_xs:  # pragma: no cover
                draw.text((cx, cy), txt, font=fnt, fill=0, anchor='mm')
                return
            # Center of ink relative to the draw anchor (ox, oy)
            ink_cx = (min(ink_xs) + max(ink_xs)) / 2 - ox
            ink_cy = (min(ink_ys) + max(ink_ys)) / 2 - oy
            x_nudge = -1 if txt == '1' else 1  # '1' sits 2px left of the general +1 nudge
            draw.text((round(cx - ink_cx) + x_nudge, round(cy - ink_cy) + 1), txt, font=fnt, fill=0)
        except Exception:  # pragma: no cover
            draw.text((cx, cy), txt, font=fnt, fill=0, anchor='mm')

    # --- inning header labels ---
    for k in range(N_COLS):
        inn_label = str(first_inn + k)
        cell_x = grid_x0 + LOGO_COL_W + k * COL_W
        cx = cell_x + COL_W // 2
        cy = y0 + ROW_H_HDR // 2
        _draw_centered(font9, inn_label, cx, cy)

    # --- logos / abbr in team rows ---
    away_id  = str(game_data.get('away_team_id', ''))
    home_id  = str(game_data.get('home_team_id', ''))
    abbr_map = team_data.get('team_abbreviation', {})
    away_abbr = abbr_map.get(away_id, away_id)
    home_abbr = abbr_map.get(home_id, home_id)

    def _place(abbr, tid, row_y):
        """Place."""
        nonlocal draw
        lsz = 10 * s  # slightly smaller than column width so logo has a 1px margin
        logo = _logo_small(abbr, tid, size=lsz) if use_logos else None
        if logo:
            lw, lh = logo.size
            Himage.paste(logo, (grid_x0 + (LOGO_COL_W - lw) // 2, row_y + 1 + (ROW_H_TEAM - 1 - lh) // 2))
            draw = ImageDraw.Draw(Himage)
        else:
            # 12px column — use at most 2 chars at font9 to avoid overflow
            abbr_str = (abbr or '')[:2]
            tw = int(font9.getlength(abbr_str))
            draw.text((grid_x0 + max(0, (LOGO_COL_W - tw) // 2), row_y + (ROW_H_TEAM - 9 * s) // 2), abbr_str, font=font9, fill=0)

    _place(away_abbr, away_id, y1)
    _place(home_abbr, home_id, y2)

    # A Final game that didn't reach a given inning (called early, or a half not
    # needed — e.g. a walk-off, or the home team already leading after the top half)
    # shows 'X' in that team's cell instead of leaving it blank.
    _is_final = game_data.get('detailed_state') in ('Final', 'Game Over', 'Final: Tied')
    _has_linescore = bool(away_inn or home_inn)

    # --- per-inning scores ---
    def _draw_row(inn_runs, row_y):
        """Draw row."""
        for k in range(N_COLS):
            idx = first_inn - 1 + k
            cell_x = grid_x0 + LOGO_COL_W + k * COL_W
            cx = cell_x + COL_W // 2
            cy = row_y + ROW_H_TEAM // 2
            if idx < len(inn_runs) and inn_runs[idx] is not None:
                val = str(inn_runs[idx])
                # Use font9 for double-digit values that won't fit in font11
                fnt = font11 if int(font11.getlength(val)) <= COL_W - 1 else font9
                _draw_centered(fnt, val, cx, cy)
            elif _is_final and _has_linescore and idx <= 8:
                _draw_centered(font11, 'X', cx, cy)

    _draw_row(away_inn, y1)
    _draw_row(home_inn, y2)

    return draw, Himage


_ABS_CHALLENGE_MAX = 2


def _draw_challenge_dots(draw, start_x, start_y, game_data, use_logos=False, logo_x_offset=2, scale=1):
    """ABS challenge circles over each team's abbreviation; replay circle under it. Filled=remaining."""
    s = scale
    _LOGO_SIZE = 28 * s
    r = 3 * s
    dot_spacing = 8 * s

    abs_max = game_data.get('abs_challenge_max') or _ABS_CHALLENGE_MAX

    if use_logos:
        # x: first dot centred just inside the team abbreviation left edge
        dot_x = start_x + logo_x_offset + _LOGO_SIZE + 2 * s + r
        # ABS dots over the abbreviation, replay dot under it
        away_abs_y    = start_y + 30 * s
        home_abs_y    = start_y + 60 * s
        away_replay_y = start_y + (25 + 7 + 14 + 4) * s   # = start_y + 50*s
        home_replay_y = start_y + (55 + 7 + 14 + 4) * s   # = start_y + 80*s
    else:
        dot_x = start_x + 5 * s + r
        away_abs_y    = start_y + 30 * s
        home_abs_y    = start_y + 60 * s
        away_replay_y = start_y + (25 + 23 + 4) * s        # = start_y + 52*s
        home_replay_y = start_y + (55 + 23 + 4) * s        # = start_y + 82*s

    def _draw_dot(cx, cy_center, filled):
        """Draw one circle centred on (cx, cy_center)."""
        box = (cx - r, cy_center - r, cx + r, cy_center + r)
        if filled:
            draw.ellipse(box, fill=0, outline=0)
        else:
            draw.ellipse(box, fill=255, outline=0, width=max(1, s))

    for side, abs_y, replay_y in (
        ('away', away_abs_y, away_replay_y),
        ('home', home_abs_y, home_replay_y),
    ):
        abs_remaining = game_data.get(f'{side}_challenges_remaining')
        replay_remaining = game_data.get(f'{side}_replay_remaining')

        # ABS dots — one per challenge slot (fixed allotment, does not grow in extras)
        if abs_remaining is not None:
            abs_remaining = max(0, min(abs_max, int(abs_remaining)))
            for i in range(abs_max):
                _draw_dot(dot_x + i * dot_spacing, abs_y, i < abs_remaining)

        # Replay dot — always 1 slot, under the abbreviation
        if replay_remaining is not None:
            replay_remaining = max(0, min(1, int(replay_remaining)))
            _draw_dot(dot_x, replay_y, replay_remaining > 0)


def _draw_weather_footer(draw, start_x, start_y, horiz_len, game_data, fnt, show_tv=True, scale=1):
    """Pre-game footer: weather left-aligned, TV channel right-aligned, in the inter-row gap."""
    y = start_y + 112 * scale

    # TV channel: right-aligned
    tv = (game_data.get('tv_channel') or '') if show_tv else ''
    tv_w = 0
    if tv:
        try:
            tv_w = int(fnt.getlength(tv)) + 2
        except AttributeError:  # pragma: no cover
            tv_w = len(tv) * 5 + 2
        draw.text((start_x + horiz_len - tv_w, y), tv, font=fnt, fill=0)

    avail_w = horiz_len - tv_w - 6 * scale

    # Dome takes full priority — no weather shown
    roof = game_data.get('roof_state')
    if roof in ('fixed', 'dome'):
        draw.text((start_x + 2 * scale, y), 'Dome', font=fnt, fill=0)
        return

    temp = game_data.get('weather_temp_f')
    wind = game_data.get('weather_wind_mph')
    wd = game_data.get('weather_wind_dir')
    precip = game_data.get('weather_precip_pct')

    if temp is None and wind is None and precip is None:
        return

    # Build candidate strings from most to least detailed (drop direction → drop 'mph' → temp only)
    candidates = []
    _t = f'{temp}°' if temp is not None else None
    _w_full = (f'{wind}mph {wd}' if wd else f'{wind}mph') if (wind is not None and wind >= 1) else None
    _w_nolabel = f'{int(wind)}' if (wind is not None and wind >= 1) else None
    _p = f'{precip}%' if (precip is not None and precip > 0) else None

    for _w in (_w_full, _w_nolabel, None):
        parts = [x for x in (_t, _w, _p) if x]
        if parts:
            candidate = ' '.join(parts)
            if candidate not in candidates:
                candidates.append(candidate)
    if _t and _t not in candidates:
        candidates.append(_t)

    # Try largest font first; within each font try shorter text variants
    for try_fnt in (fnt, _get_font(11), _get_font(9)):
        for text in candidates:
            try:
                tw = int(try_fnt.getlength(text))
            except AttributeError:
                tw = len(text) * 5
            if tw <= avail_w:
                draw.text((start_x + 2 * scale, y), text, font=try_fnt, fill=0)
                return


def _next_preview_date(after_date=None):
    """The date whose schedule the 'next game' strip should show.

    Derived from the date of the game being drawn — the next game after a game
    played on D is on D+1 — rather than from the wall clock. Guessing from the
    clock got the morning alternating window wrong: on the blocks showing
    *today's* games it still targeted today, so a game postponed earlier that
    day advertised its own date as the next one.

    Falls back to tomorrow when the game carries no usable date.
    """
    from datetime import date as _date, timedelta as _td, datetime as _dt
    if after_date:
        try:
            base = _dt.strptime(str(after_date)[:10], '%Y-%m-%d').date()
            return (base + _td(days=1)).strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            pass
    return (_date.today() + _td(days=1)).strftime('%Y-%m-%d')


def _load_tomorrow_games(after_date=None):
    """Load the schedule for the day after ``after_date``, fetching if not cached.

    Reads the multi-day ``by_date`` map written by fetch_games, so the morning
    alternating window can flip between two target dates without refetching on
    every 5-minute block change.
    """
    target = _next_preview_date(after_date)

    try:
        data = load_json_file('tomorrow_games.json') or {}

        cached = (data.get('by_date') or {}).get(target)
        if cached and cached.get('games') is not None:
            return {'date': target, 'games': cached['games'],
                    'fetched_at': cached.get('fetched_at', 0)}
        if data.get('date') == target and data.get('games') is not None:
            return data

        # Not cached for this date — fetch it.
        from fetch_games import fetch_tomorrow_games
        fetch_tomorrow_games(for_date=target)
        data = load_json_file('tomorrow_games.json') or {}
        if data.get('date') == target and data.get('games') is not None:
            return data
        return None
    except Exception as _e:
        print(f"Warning: could not load tomorrow's games: {_e}")
        return None


def _draw_next_game_preview(draw, Himage, start_x, start_y, tmrw_games, today_home_id, today_away_id,
                             team_data, use_logos, horizonta_len, vertical_len, scale=1, left_offset=0):
    """Draw tomorrow's matchup in the win-prob strip.

    Away team's next game is left-aligned; home team's next game is right-aligned.
    If the same series continues, a single entry is shown left-aligned.
    left_offset: pixels to skip on the left edge (e.g. to clear a doubleheader "Game X" label).
    Text and time use font14 to match the game-end-time display.
    """
    s = scale
    BAR_Y = start_y + vertical_len + 21 * s
    BAR_H = 19 * s
    BAR_X = start_x + 1 * s
    BAR_W = horizonta_len - 2 * s

    abbr_map = team_data.get('team_abbreviation', {})
    LOGO_SZ = 14 * s
    font14 = _get_font(14 * s)
    _text_y = BAR_Y + (BAR_H - 14 * s) // 2
    _time_y = _text_y
    _vs_y = _text_y
    at_str = '@'
    at_w = int(font14.getlength(at_str))

    _cfg = load_yaml_file('config.yaml')
    _tz_str = _cfg.get('timezone', 'America/Chicago')

    def _game_time(game, full=False):
        """Return a localised start-time string for game.

        full=False  →  '7p'     (hour + am/pm letter, no minutes)
        full=True   →  '7:05p'  (hour:minute + am/pm letter)
        """
        utc_str = game.get('game_start_utc', '')
        if not utc_str:
            return ''
        try:
            _utc = pytz.utc.localize(_datetime.strptime(utc_str[:19], '%Y-%m-%dT%H:%M:%S'))
            _local = _utc.astimezone(pytz.timezone(_tz_str))
            _ampm = _local.strftime('%p').lower()[0]
            if full:
                return _local.strftime('%-I:%M') + _ampm
            else:
                return _local.strftime('%-I') + _ampm
        except Exception:
            return ''

    def _find_game(team_id):
        """Find game."""
        for g in tmrw_games:
            if g.get('home_team_id') == team_id or g.get('away_team_id') == team_id:
                return g
        return None

    VS_PAD = 1 * s   # pixels on each side of the vs. text
    TIME_PAD = 2 * s # gap between matchup and time string

    def _logo_w(abbr, team_id):
        """Return the pixel width of the logo or abbreviation text for sizing."""
        if use_logos and team_id:
            lg = _logo_small(str(abbr), str(team_id), size=LOGO_SZ)
            if lg:
                return lg.size[0]
        return int(font14.getlength((str(abbr) or '')[:3]))

    def _place_logo(abbr, team_id, x):
        """Place logo."""
        nonlocal draw
        if use_logos and team_id:
            lg = _logo_small(str(abbr), str(team_id), size=LOGO_SZ)
            if lg:
                actual_y = BAR_Y + (BAR_H - lg.size[1]) // 2
                _paste_logo(Himage, lg, (x, actual_y))
                draw = ImageDraw.Draw(Himage)
                return x + lg.size[0]
        t = (str(abbr) or '')[:3]
        draw.text((x, _text_y), t, font=font14, fill=0)
        return x + int(font14.getlength(t))

    def _draw_vs(x):
        """Draw vs."""
        draw.text((x + VS_PAD, _vs_y), at_str, font=font14, fill=0)
        return x + VS_PAD + at_w + VS_PAD

    away_game = _find_game(today_away_id)
    home_game = _find_game(today_home_id)

    if not away_game and not home_game:
        return

    same_series = (
        away_game and home_game and
        away_game.get('game_pk') == home_game.get('game_pk') and
        away_game.get('away_team_id') == today_away_id and
        away_game.get('home_team_id') == today_home_id
    )

    # _fit_time prefers the full "H:MMp" form and falls back to abbreviated "Hp"
    # when space is tight, so shared-strip layouts degrade automatically.
    strip_right = BAR_X + BAR_W - 1 * s   # rightmost pixel the strip may use

    def _fit_time(t_full, t_abbr, cx, right_limit):
        """Return the best time string that fits to the right of cx, or '' if none fits."""
        for t in (t_full, t_abbr):
            if t and cx + TIME_PAD + int(font14.getlength(t)) <= right_limit:
                return t
        return ''

    def _draw_single(g):
        """Left-to-right: away logo  @  home logo  TIME (immediately after, if it fits)."""
        a_abbr = abbr_map.get(str(g['away_team_id']), '')
        h_abbr = abbr_map.get(str(g['home_team_id']), '')
        cx = BAR_X + 1 * s + left_offset
        cx = _place_logo(a_abbr, g['away_team_id'], cx)
        cx = _draw_vs(cx)
        cx = _place_logo(h_abbr, g['home_team_id'], cx)
        t_full  = _game_time(g, full=True)
        t_abbr  = _game_time(g, full=False)
        t_str   = _fit_time(t_full, t_abbr, cx, strip_right)
        if t_str:
            _tx = cx + TIME_PAD
            _draw_bold_text(draw, (_tx, _time_y), t_str, font14, s)

    if same_series:
        _draw_single(away_game)
        return

    # New series — only draw the entry for each team that actually has a game.
    # Single-team entries use full "H:MMp" time if it fits, abbreviated otherwise.
    # Two different games share the strip → abbreviated preferred; each half checked independently.

    if away_game and not home_game:
        _draw_single(away_game)
        return

    if home_game and not away_game:
        _draw_single(home_game)
        return

    # Both teams have different games.
    # Away entry is left-anchored; home entry is right-anchored.
    def _draw_half(g, start_cx, right_limit):
        """Draw half."""
        a_abbr = abbr_map.get(str(g['away_team_id']), '')
        h_abbr = abbr_map.get(str(g['home_team_id']), '')
        cx = start_cx
        cx = _place_logo(a_abbr, g['away_team_id'], cx)
        cx = _draw_vs(cx)
        cx = _place_logo(h_abbr, g['home_team_id'], cx)
        t_abbr = _game_time(g, full=False)
        t_str  = _fit_time('', t_abbr, cx, right_limit)   # abbreviated only for split strip
        if t_str:
            _tx = cx + TIME_PAD
            _draw_bold_text(draw, (_tx, _time_y), t_str, font14, s)

    def _measure_half(g):
        """Return pixel width of one game entry (away @ home + optional time)."""
        a_abbr = abbr_map.get(str(g['away_team_id']), '')
        h_abbr = abbr_map.get(str(g['home_team_id']), '')
        w  = _logo_w(a_abbr, g['away_team_id'])
        w += VS_PAD + at_w + VS_PAD
        w += _logo_w(h_abbr, g['home_team_id'])
        t_abbr = _game_time(g, full=False)
        if t_abbr:
            w += TIME_PAD + int(font14.getlength(t_abbr))
        return int(w)

    if away_game and home_game:
        # Right-anchor the home game so it ends flush with the right edge.
        home_w     = _measure_half(home_game)
        home_start = strip_right - home_w
        # Left-anchor the away game; limit it to just before the home game starts.
        _draw_half(away_game, BAR_X + left_offset, home_start - 2 * s)
        _draw_half(home_game, home_start, strip_right)
    elif away_game:  # pragma: no cover
        _draw_half(away_game, BAR_X + left_offset, strip_right)
    elif home_game:  # pragma: no cover
        home_w     = _measure_half(home_game)
        home_start = strip_right - home_w
        _draw_half(home_game, home_start, strip_right)


def _game_within_minutes_check(game_data, minutes=30):
    """Return True once the game is within `minutes` of its scheduled start.

    No lower bound: once first pitch is within the window, this stays True
    indefinitely past the scheduled start time too — the caller's own
    detailed_state check (Scheduled/Pre-Game/Warmup) is what actually cuts
    lineup mode off, the moment the game goes live. Without this, a game
    running a few minutes late at its scheduled start would revert from the
    lineup display back to the plain pre-game tile before the first pitch.
    """
    from datetime import datetime, timezone, timedelta
    game_date = game_data.get('game_date') or ''
    if not game_date:
        return False
    try:
        gd = game_date.replace('Z', '+00:00')
        start = datetime.fromisoformat(gd)
        now   = datetime.now(timezone.utc)
        return (start - now) <= timedelta(minutes=minutes)
    except (ValueError, TypeError):
        return False


_SeriesState = namedtuple('_SeriesState', [
    'game_is_final', 'active_no_no', 'total_games', 'wins', 'losses', 'description',
    'is_sweep', 'clinched', 'tied', 'leading', 'show_overline',
])


def _compute_series_state(game_data):
    """Derive the series-context flags shown in a finished game's header.

    Regular-season and postseason series end differently: a regular-season
    series is only complete once every scheduled game has been played
    (wins + losses == total), whereas a postseason series ends as soon as one
    side clinches, often before all games are needed. ``series_is_over`` is
    therefore authoritative for the postseason but not the regular season.

    Series context is suppressed outside finished games, so every series flag is
    False for pre-game and live tiles.
    """
    game_is_final = game_data.get('detailed_state') in ('Final', 'Game Over', 'Final: Tied')
    active_no_no = bool(
        game_data['detailed_state'] == 'In Progress'
        and (game_data.get('no_hitter') or game_data.get('perfect_game'))
        and (game_data.get('current_inning') or 0) >= 6
    )

    total = game_data.get('series_total_games') or 1
    wins = game_data.get('series_wins', 0) or 0
    losses = game_data.get('series_losses', 0) or 0
    desc = game_data.get('series_description', '')
    is_over = bool(game_data.get('series_is_over'))

    # A multi-game series in a finished state is the precondition for every flag.
    in_series = game_is_final and total > 1
    series_complete = ((wins + losses) == total if desc == 'Regular Season' else is_over)

    is_sweep = bool(in_series and (losses == 0 or wins == 0) and series_complete)
    clinched = bool(in_series and is_over and not is_sweep)
    tied = bool(in_series and game_data.get('series_is_tied') and not is_over)
    leading = bool(in_series and not is_over
                   and not game_data.get('series_is_tied') and wins > 0)

    return _SeriesState(
        game_is_final=game_is_final, active_no_no=active_no_no, total_games=total,
        wins=wins, losses=losses, description=desc, is_sweep=is_sweep,
        clinched=clinched, tied=tied, leading=leading,
        show_overline=bool(in_series and series_complete),
    )


# (font point size, y offset from the top of the header) — largest first.
_VENUE_FONT_LADDER = ((16, 2), (14, 3), (11, 4), (9, 5), (8, 6))
_DELAY_FONT_LADDER = ((14, 3), (11, 4), (9, 5))


def _draw_header_right_text(ctx, text, right_x, max_w, ladder, truncate=False):
    """Right-anchor a label in the tile header, shrinking it to fit.

    Walks ``ladder`` from the largest size down. The two callers want different
    things when nothing fits cleanly:

    * venue (truncate=False) — use the largest size whose whole name fits, and
      fall back to the smallest size rather than cutting a stadium name short.
    * delay reason (truncate=True) — clip the text to the available width and
      use the largest size that still leaves at least one character.
    """
    if not text or max_w <= 0:
        return

    chosen = None
    for size, vy in ladder:
        font = _get_font(size * ctx.s)
        if truncate:
            clipped = text
            while clipped and font.getlength(clipped) > max_w:
                clipped = clipped[:-1]
            if clipped:
                chosen = (clipped, font, vy)
                break
        elif font.getlength(text) <= max_w:
            chosen = (text, font, vy)
            break

    if chosen is None:
        if truncate:
            return                      # not even one character fits
        size, vy = ladder[-1]           # smallest size, allowed to overflow
        chosen = (text, _get_font(size * ctx.s), vy)

    label, font, vy = chosen
    ctx.bold((right_x - int(font.getlength(label)), ctx.y + vy * ctx.s), label, font)


class _TileCtx:
    """Canvas, geometry and fonts for one game tile.

    draw_box and its helpers all position content relative to the same handful
    of values — tile origin, scale, tile size, the five font sizes, and whether
    logos are enabled. Threading those through every helper individually meant
    signatures of ten-plus parameters, which is what made the function resist
    being broken up. Passing one context instead keeps extracted helpers to two
    or three arguments.

    ``draw`` is an attribute rather than a parameter because pasting onto the
    image invalidates the current ImageDraw. Going through ``paste()`` refreshes
    it centrally, so a helper can't silently draw into a stale handle — a bug
    class that previously had to be remembered at each call site.
    """

    __slots__ = ('Himage', 'draw', 'x', 'y', 's', 'w', 'h',
                 'font24', 'font18', 'font14', 'font11', 'font9',
                 'use_logos', 'logo_x_offset')

    def __init__(self, Himage, start_x, start_y, scale, use_logos, logo_x_offset):
        self.Himage = Himage
        self.draw = ImageDraw.Draw(Himage)
        self.x = start_x
        self.y = start_y
        self.s = scale
        self.w = 135 * scale   # horizonta_len
        self.h = 110 * scale   # vertical_len
        self.font24 = _get_font(24 * scale)
        self.font18 = _get_font(18 * scale)
        self.font14 = _get_font(14 * scale)
        self.font11 = _get_font(11 * scale)   # also used for base-runner numbers
        self.font9 = _get_font(9 * scale)
        self.use_logos = use_logos
        self.logo_x_offset = logo_x_offset

    def paste(self, img, xy):
        """Paste onto the tile and refresh ``draw``, which the paste invalidates."""
        self.Himage.paste(img, xy)
        self.draw = ImageDraw.Draw(self.Himage)

    def bold(self, xy, text, font):
        """Draw text with the renderer's 1px-offset bold effect."""
        _draw_bold_text(self.draw, xy, text, font, self.s)

    def centred_x(self, text, font):
        """x that centres ``text`` horizontally within the tile."""
        return self.x + self.w // 2 - int(font.getlength(text)) // 2

    def bold_centred(self, text, font, y):
        """Draw bold text centred horizontally at ``y``."""
        self.bold((self.centred_x(text, font), y), text, font)

    def corner_xy(self):
        """The small slot beside the away logo, used by the moved duration label
        and the pre-game 'Game N' label."""
        return (_duration_corner_x(self.x, self.s, self.use_logos, self.logo_x_offset),
                self.y + 50 * self.s)


def _final_linescore_window_expired(game_data, final_linescore_secs):
    """True once a Final game's linescore window has elapsed.

    Prefers the API's precise UTC end time. Without one, falls back to the
    game's local date — a game dated before today is definitively over — and
    then to when this app first saw the game as Final. The date comparison is
    deliberately done in local time: game_date is a local date, so comparing it
    against a UTC "today" would expire evening games early once they cross
    midnight UTC.
    """
    end_utc_str = game_data.get('game_end_time_utc')
    if end_utc_str:
        try:
            end_utc = pytz.utc.localize(
                _datetime.strptime(end_utc_str[:19], '%Y-%m-%dT%H:%M:%S'))
            elapsed = (_datetime.now(pytz.utc) - end_utc).total_seconds()
            return elapsed >= final_linescore_secs
        except Exception:
            pass  # authoritative source unusable — fall through

    try:
        tz_str = load_yaml_file('config.yaml').get('timezone', 'America/Chicago')
        today_local = _datetime.now(pytz.timezone(tz_str)).strftime('%Y-%m-%d')
    except Exception:  # pragma: no cover - bad tz in config
        today_local = _datetime.now(pytz.utc).strftime('%Y-%m-%d')

    game_date = (game_data.get('game_date') or '')[:10]
    if game_date and game_date < today_local:
        return True

    first_seen = _get_or_set_final_time(game_data.get('game_pk'))
    return (_time.time() - first_seen) >= final_linescore_secs


def _invert_region(Himage, x1, y1, x2, y2):
    """Invert a rectangular region of Himage in place (for header-flash effects)."""
    region = Himage.crop((x1, y1, x2, y2))
    Himage.paste(ImageOps.invert(region.convert('L')).convert('1'), (x1, y1))


def _draw_bold_text(draw, xy, text, font, s=1):
    """Draw text twice, offset 1px horizontally — the renderer's bold effect.

    The e-ink panel is 1-bit, so there is no synthetic weight to fall back on.
    """
    x, y = xy
    draw.text((x, y), text, font=font, fill=0)
    draw.text((x + 1 * s, y), text, font=font, fill=0)


def _duration_corner_x(start_x, s, use_logos, logo_x_offset):
    """x of the small corner slot beside the away logo, shared by the moved
    duration label and the pre-game 'Game N' label."""
    if use_logos:
        return start_x + logo_x_offset + 28 * s + 2 * s + 3 * s
    return start_x + 8 * s


def _draw_duration_and_dh_labels(ctx, game_data, game_is_final, is_sweep, is_walkoff,
                                 dh_is_active, dh_scheduled, gnum):
    """Draw the game-duration and doubleheader 'Game N' / 'GMn' labels.

    Placement is a single decision shared by both, which is why they are drawn
    together: the centred header slot normally holds the duration, but a sweep
    or walkoff banner takes that slot over, pushing the duration down to the
    small corner spot beside the away logo and the game number in next to it.
    """
    s = ctx.s
    header_y = ctx.y + 3 * s
    corner_x, corner_y = ctx.corner_xy()

    sweep_dur_right_x = None    # right edge of a moved duration; GM anchors to it
    gm_drawn_in_header = False  # GM already rendered alongside the duration

    # No-hitters and perfect games keep the header for their own banner.
    duration_mins = game_data.get('game_duration_minutes')
    if (game_is_final and duration_mins
            and not game_data.get('perfect_game') and not game_data.get('no_hitter')):
        duration = f'{duration_mins // 60}:{duration_mins % 60:02d}'

        if is_sweep or is_walkoff:
            # Header taken by the banner — duration drops to the corner.
            sweep_dur_right_x = corner_x + int(ctx.font9.getlength(duration))
            ctx.bold((corner_x, corner_y), duration, ctx.font9)
        elif dh_is_active:
            # DH final: duration to the corner, 'Game N' centred alone in the header.
            ctx.bold((corner_x, corner_y), duration, ctx.font9)
            ctx.bold_centred(f'Game {gnum}', ctx.font14, header_y)
            gm_drawn_in_header = True
        else:
            ctx.bold_centred(duration, ctx.font14, header_y)

    # Not-yet-started DH game: 'Game N' in the corner, freeing the header for the venue.
    if dh_scheduled:
        ctx.bold((corner_x, corner_y), f'Game {gnum}', ctx.font9)

    # Finished/postponed DH game: 'GMn' beside a moved duration, else centred.
    # Not-yet-started games are handled just above, so they're excluded here.
    dh_state = game_data['detailed_state'] in (
        'Final', 'Game Over', 'Final: Tied', 'Postponed')
    if dh_is_active and dh_state:
        gm = f'GM{gnum}'
        if (is_sweep or is_walkoff) and sweep_dur_right_x is not None:
            ctx.bold((sweep_dur_right_x + 3 * s, corner_y), gm, ctx.font9)
        elif not gm_drawn_in_header:
            ctx.bold_centred(gm, ctx.font14, header_y)
        # else: GM was already drawn with the duration above.


def _draw_game_end_time(ctx, end_utc_str, in_linescore_window, game_is_final):
    """Right-align the game's local end time in the strip below the box.

    Shown only while the linescore window is active, so it disappears together
    with the linescore grid. Set show_game_end_time_always in config to keep it
    visible after the window closes.

    ``game_is_final`` gates the whole thing: a game still in progress has an
    end time only in the sense that the API hasn't set one, and the strip this
    draws into belongs to the live win-probability bar until the game ends.
    """
    if not game_is_final:
        return
    cfg = load_yaml_file('config.yaml')
    if not (in_linescore_window or cfg.get('show_game_end_time_always', False)):
        return
    if not end_utc_str:
        return

    try:
        end_utc = pytz.utc.localize(
            _datetime.strptime(end_utc_str[:19], "%Y-%m-%dT%H:%M:%S"))
        end_local = end_utc.astimezone(
            pytz.timezone(cfg.get('timezone', 'America/Chicago')))
        text = (end_local.strftime("%I:%M").lstrip("0") + " "
                + end_local.strftime("%p").lower())
    except Exception:  # pragma: no cover - malformed API timestamp
        return

    strip_y = ctx.y + ctx.h + 21 * ctx.s   # same y as the win-prob bar
    strip_h = 19 * ctx.s
    x = ctx.x + ctx.w - int(ctx.font14.getlength(text)) - 1 * ctx.s
    ctx.bold((x, strip_y + (strip_h - 14 * ctx.s) // 2), text, ctx.font14)


def _draw_win_probability_bar(ctx, game_data, away_team, home_team, center_line=True):
    """Draw the live win-probability strip below the box.

    A 'LOSS'/'WIN' ghost watermark with each team positioned along it by win
    probability — as logos when logos are enabled, otherwise as tick marks.

    ``center_line`` draws the solid rule the logos sit on. The wide and triple
    tiles pass False: the strip cannot be widened past the left cell there,
    because the space to its right in the same gap belongs to the K-strikeout
    strip, and a rule that stops at the cell boundary reads as a stray line
    crossing the tile rather than as a bar.
    """
    away_wp = game_data.get('away_win_probability')
    home_wp = game_data.get('home_win_probability')
    if away_wp is None or home_wp is None:
        return

    try:
        away_wp = float(away_wp)
        home_wp = float(home_wp)
        if away_wp + home_wp <= 1.5:   # API sometimes returns 0-1 fractions
            away_wp *= 100
            home_wp *= 100
    except (ValueError, TypeError):
        away_wp, home_wp = 50.0, 50.0

    s = ctx.s
    LOGO_SZ = 18 * s
    BAR_Y = ctx.y + ctx.h + 21 * s  # 1px below bottom border, in the inter-row gap
    BAR_H = 19 * s                  # available inter-row height
    BAR_X = ctx.x + 1 * s
    BAR_W = ctx.w - 2 * s

    # Ghost 'LOSS' / 'WIN' watermarks, then a solid horizontal centre line.
    ghost = Image.new('L', (BAR_W, BAR_H), 255)
    ghost_draw = ImageDraw.Draw(ghost)
    ghost_draw.text((1 * s, (BAR_H - 18 * s) // 2), 'LOSS', font=ctx.font18, fill=0)
    win_w = int(ctx.font18.getlength('WIN'))
    ghost_draw.text((BAR_W - win_w - 1 * s, (BAR_H - 18 * s) // 2), 'WIN',
                    font=ctx.font18, fill=0)
    ghost = ghost.point(lambda p: 255 if p > 180 else min(255, int(p * 0.35 + 155)))
    if center_line:
        # Drawn after the ghost transform so it stays solid black.
        ImageDraw.Draw(ghost).line((0, BAR_H // 2, BAR_W, BAR_H // 2), fill=0)
    ctx.paste(ghost.convert('1'), (BAR_X, BAR_Y))

    def _clamp(px):
        """Keep a logo fully inside the bar."""
        return max(BAR_X, min(BAR_X + BAR_W - LOGO_SZ, px - LOGO_SZ // 2))

    away_px = BAR_X + int(BAR_W * away_wp / 100.0)
    home_px = BAR_X + int(BAR_W * home_wp / 100.0)
    away_logo_x = _clamp(away_px)
    home_logo_x = _clamp(home_px)

    # Push the logos apart when the probabilities are close enough to overlap.
    MIN_SEP = LOGO_SZ + 1 * s
    if abs(away_logo_x - home_logo_x) < MIN_SEP:
        mid = (away_logo_x + home_logo_x) // 2
        right = min(BAR_X + BAR_W - LOGO_SZ, mid + MIN_SEP // 2)
        left = max(BAR_X, mid - MIN_SEP // 2)
        if away_logo_x > home_logo_x:
            away_logo_x, home_logo_x = right, left
        else:
            away_logo_x, home_logo_x = left, right

    if ctx.use_logos:
        away_logo = _logo_small(away_team[0], away_team[1], size=LOGO_SZ)
        home_logo = _logo_small(home_team[0], home_team[1], size=LOGO_SZ)
        if away_logo:
            _paste_logo(ctx.Himage, away_logo,
                        (away_logo_x, BAR_Y + (BAR_H - away_logo.size[1]) // 2))
        if home_logo:
            _paste_logo(ctx.Himage, home_logo,
                        (home_logo_x, BAR_Y + (BAR_H - home_logo.size[1]) // 2))
    else:
        ctx.draw.line((away_px, BAR_Y, away_px, BAR_Y + BAR_H), fill=0)
        ctx.draw.line((home_px, BAR_Y, home_px, BAR_Y + BAR_H), fill=0)


def _game_has_started(game_data):
    """True once there's evidence a pitch has actually been thrown.

    The API reports 'In Progress' from the scheduled start time, before first
    pitch. Evidence of play: a ball/strike in the current at-bat, any out, any
    run, a runner on base, an inning break, a last-play description, or the game
    being past the 1st.

    away_hits/home_hits are deliberately excluded: in the GIF replay path they
    are inherited from the final box score and are always non-zero, which would
    make every pre-game frame look live.
    """
    return bool(
        (game_data.get('balls') or 0) > 0
        or (game_data.get('strikes') or 0) > 0
        or (game_data.get('num_of_outs') or 0) > 0
        or (game_data.get('away_runs') or 0) > 0
        or (game_data.get('home_runs') or 0) > 0
        or game_data.get('inningState') in ('Middle', 'End')
        or (game_data.get('current_inning') or 1) > 1
        or game_data.get('runner_on_first')
        or game_data.get('runner_on_second')
        or game_data.get('runner_on_third')
        or game_data.get('last_play')
    )


def _normalize_game_state(game_data):
    """Collapse API states into the handful the renderer actually branches on.

    Returns ``(game_data, challenge_abbr, original_detailed_state)``. game_data is
    copied before any write, so the caller's dict is never mutated.

    * 'Completed Early' (e.g. spring games called after 6) → 'Final'
    * 'Player challenge' / 'Manager challenge' → 'In Progress', with the label
      written into sub_event so it outranks last_play (stopping a "PC: Name"
      from overriding the challenge banner)
    * 'Delayed Start' → 'Pre-Game' (the game hasn't begun)
    * 'In Progress' before first pitch → 'Pre-Game'

    original_detailed_state is captured after the challenge normalization but
    before the pre-game ones, matching what the header renderer expects.
    """
    challenge_abbr = ''

    if game_data.get('detailed_state', '').startswith('Completed Early'):
        game_data = dict(game_data)
        game_data['detailed_state'] = 'Final'

    if game_data.get('detailed_state') in ('Player challenge', 'Manager challenge'):
        game_data = dict(game_data)
        prefix = 'ABS CHAL' if game_data['detailed_state'] == 'Player challenge' else 'M CHAL'
        challenge_abbr = game_data.get('challenge_team_abbr', '')
        # Logo rendering shows the team; keep the text label as a prefix only.
        game_data['sub_event'] = prefix
        game_data['last_play'] = prefix
        game_data['detailed_state'] = 'In Progress'

    original_detailed_state = game_data.get('detailed_state', '')

    if game_data.get('detailed_state') == 'Delayed Start':
        game_data = dict(game_data)
        game_data['detailed_state'] = 'Pre-Game'

    if game_data.get('detailed_state') == 'In Progress' and not _game_has_started(game_data):
        game_data = dict(game_data)
        game_data['detailed_state'] = 'Pre-Game'

    return game_data, challenge_abbr, original_detailed_state


def _draw_background_ghosts(ctx, game_data, show_winner_logo, away_team, home_team):
    """Paste the large faded background graphic for this game state, if any.

    Postponed and Suspended games get a rotating weather emoji; a finished game
    gets the winning team's logo. Called before any text so everything else
    renders on top.
    """
    state = game_data['detailed_state']
    s = ctx.s

    emoji_codepoints = None
    if state == 'Postponed':
        emoji_codepoints = _PPD_EMOJI_CODEPOINTS
    elif state == 'Suspended':
        emoji_codepoints = _SUSP_EMOJI_CODEPOINTS

    if emoji_codepoints:
        import random as _random
        # Seeded per game and per minute, so the icon rotates but stays stable
        # within a single minute's renders rather than flickering every poll.
        seed = game_data.get('game_pk', 0) ^ int(_time.time() // 60)
        codepoint = _random.Random(seed).choice(emoji_codepoints)
        ghost = _load_codepoint_ghost(codepoint, size=90 * s)
        if ghost:
            gw, gh = ghost.size
            ctx.paste(ghost, (ctx.x + (ctx.w - gw) // 2,
                              ctx.y + (ctx.h + 20 * s - gh) // 2))
        return

    if show_winner_logo and ctx.use_logos and state in ('Final', 'Game Over', 'Final: Tied'):
        winner = None
        if game_data.get('away_team_is_winner'):
            winner = away_team
        elif game_data.get('home_team_is_winner'):
            winner = home_team
        if winner and winner[0]:
            ghost = _logo_ghost(winner[0], winner[1], size=110 * s)
            if ghost:
                gw, gh = ghost.size
                ctx.paste(ghost, (ctx.x + (135 * s - gw) // 2,
                                  ctx.y + 20 * s + (ctx.h - gh) // 2))


def _in_final_linescore_window(game_data, final_linescore_secs):
    """True while a finished game should still show its linescore grid.

    Anchored to the actual game end time when the API supplies one, falling back
    to when this app first observed the game as Final. Always False in historical
    mode, where "now" bears no relation to when the game ended.
    """
    if _historical_mode:
        return False

    game_pk = game_data.get('game_pk')
    final_ts = _get_or_set_final_time(game_pk) if game_pk else None

    end_utc_str = game_data.get('game_end_time_utc')
    if end_utc_str:
        try:
            end_dt = pytz.utc.localize(
                _datetime.strptime(end_utc_str[:19], "%Y-%m-%dT%H:%M:%S"))
            elapsed = (_datetime.now(pytz.utc) - end_dt).total_seconds()
            return elapsed < final_linescore_secs
        except Exception:
            pass  # fall back to the first-seen-Final timestamp

    return final_ts is not None and (_time.time() - final_ts) < final_linescore_secs


def _compute_game_state_str(game_data, original_detailed_state, game_ending_state, between_innings):
    """Return the short header string for the current game state (pure computation)."""
    state = game_data['detailed_state']

    if state in ('Final', 'Game Over', 'Final: Tied', 'Postponed', 'Delayed'):
        if state == 'Game Over':
            s = 'Final'
        elif state == 'Final: Tied':
            s = 'Tied'
        elif state == 'Delayed':
            inn = game_data.get('current_inning') or 0
            s = f'DLY {inn}' if inn > 0 else 'Delay'
        else:
            s = state
        if s == 'Final':
            if (game_data.get('away_runs') or 0) == (game_data.get('home_runs') or 0):
                s = 'Tied'
        if state not in ('Delayed', 'Postponed'):
            inn = game_data.get('current_inning') or 9
            if inn > 9:
                s = 'F/' + str(inn)
            elif inn != 9 and s not in ('Tied',):
                s += '/' + str(inn)
        return s

    if state == 'Warmup':
        return game_data.get('game_start') or state

    if state in ('Scheduled', 'Pre-Game'):
        if original_detailed_state == 'Delayed Start':
            return 'Delay'
        try:
            from datetime import datetime
            dt = datetime.strptime(game_data.get('game_start', ''), "%Y-%m-%dT%H:%M:%SZ")
            return dt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            return game_data.get('game_start', '')

    if state in ('Suspended', 'Cancelled', 'Cancelled: Rain'):
        s = 'Susp' if state == 'Suspended' else 'Canc'
        inn = game_data.get('current_inning')
        if inn:
            half = {'Top': 'Top', 'Bottom': 'Bot', 'Middle': 'Mid', 'End': 'End'}.get(
                game_data.get('inningState') or '', '')
            s += f' {half} {inn}' if half else f' {inn}'
        return s

    # In Progress (and any other live state not matched above)
    inn_state = game_data.get('inningState') or ''
    inn_label = {'Top': 'Top', 'Bottom': 'Bot', 'Middle': 'Mid', 'End': 'End'}.get(
        inn_state, inn_state[:3].capitalize() if inn_state else '')
    inn_ord_raw = game_data.get('currentInningOrdinal') or str(game_data.get('current_inning') or 1)
    inn_ord = _re.sub(r'(?:st|nd|rd|th)$', '', inn_ord_raw, flags=_re.IGNORECASE)
    if game_ending_state and between_innings:
        return 'End of Game'
    return f'{inn_label} {inn_ord}'.strip()


def _resolve_series_team(game_data, away_team_name, home_team_name):
    """Return (abbr, team_id_str) for the series leader/winner, or (None, None)."""
    result = game_data.get('series_result', '')
    parts = result.split()
    if len(parts) >= 2 and parts[1] == 'wins':
        leading = parts[0].upper()
        if leading == away_team_name.upper():
            return away_team_name, str(game_data['away_team_id'])
        if leading == home_team_name.upper():
            return home_team_name, str(game_data['home_team_id'])
    if game_data.get('away_team_is_winner'):
        return away_team_name, str(game_data['away_team_id'])
    if game_data.get('home_team_is_winner'):
        return home_team_name, str(game_data['home_team_id'])
    return None, None


def _draw_series_header_state(ctx, game_data, away_team_name, home_team_name,
                               away_team_id, home_team_id, ser):
    """Draw series context (sweep/clinched/tied/leading/postponed) in the tile header.

    Returns ser_content_left_x — the left edge of the drawn content.
    May call ctx.paste(), so callers should refresh draw = ctx.draw after.
    """
    s = ctx.s
    start_x, start_y = ctx.x, ctx.y
    horizonta_len = ctx.w
    font14, font11 = ctx.font14, ctx.font11

    ser_content_left_x = start_x + horizonta_len - 2 * s

    def _place_logo_score(abbr, team_id, score_str, score_w, bold):
        """Draw [logo] score right-anchored; return left edge of content."""
        _logo = _logo_small(abbr, team_id, size=14 * s) if abbr else None
        _rx = start_x + horizonta_len - 2 * s
        if _logo:
            _lw, _lh = _logo.size
            _score_x = _rx - score_w
            _logo_x  = _score_x - 2 * s - _lw
            _logo_y  = start_y + (20 * s - _lh) // 2
            ctx.paste(_logo, (_logo_x, _logo_y))
            _left_x = _logo_x
        else:
            _score_x = _rx - score_w
            _left_x  = _score_x
        if bold:
            _draw_bold_text(ctx.draw, (_score_x, start_y + 3 * s), score_str, font14, s)
        else:
            ctx.draw.text((_score_x, start_y + 3 * s), score_str, font=font14, fill=0)
        if ser.show_overline:
            ctx.draw.line((_score_x, start_y + 3 * s,
                           _score_x + score_w, start_y + 3 * s), fill=0, width=2)
        return _left_x

    if ser.is_sweep or ser.clinched:
        _sw = game_data.get('series_wins') or 0
        _sl = game_data.get('series_losses') or 0
        _score_str = f'{_sw}-{_sl}'
        _score_w = int(font14.getlength(_score_str))
        _abbr, _tid = _resolve_series_team(game_data, away_team_name, home_team_name)
        ser_content_left_x = _place_logo_score(_abbr, _tid, _score_str, _score_w, bold=True)

    elif ser.tied:
        _sw = game_data.get('series_wins') or 0
        _sl = game_data.get('series_losses') or 0
        _tied_str = f'{_sw}-{_sl}'
        _tied_w = int(font14.getlength(_tied_str))
        _tx = start_x + horizonta_len - 2 * s - _tied_w
        ser_content_left_x = _tx
        _draw_bold_text(ctx.draw, (_tx, start_y + 3 * s), _tied_str, font14, s)
        if ser.show_overline:
            ctx.draw.line((_tx, start_y + 3 * s,
                           _tx + _tied_w, start_y + 3 * s), fill=0, width=2)

    elif ser.leading:
        _sw = game_data.get('series_wins') or 0
        _sl = game_data.get('series_losses') or 0
        _score_str = f'{_sw}-{_sl}'
        _score_w = int(font14.getlength(_score_str))
        _abbr, _tid = _resolve_series_team(game_data, away_team_name, home_team_name)
        ser_content_left_x = _place_logo_score(_abbr, _tid, _score_str, _score_w, bold=False)

    # Series context in header for postponed games
    if game_data['detailed_state'] == 'Postponed' and (game_data.get('series_total_games') or 1) > 1:
        _ppd_sr = game_data.get('series_result') or ''
        _ppd_parts = _ppd_sr.split()
        _ppd_is_tied = 'tied' in _ppd_sr.lower()
        _ppd_sw = game_data.get('series_wins') or 0
        _ppd_sl = game_data.get('series_losses') or 0
        _rx = start_x + horizonta_len - 2 * s

        if (_ppd_sw + _ppd_sl) > 0 and not _ppd_is_tied and len(_ppd_parts) >= 3 and _ppd_parts[1] == 'leads':
            _ppd_score = _ppd_parts[2]
            _ppd_leader_str = _ppd_parts[0].upper()
            _ppd_logo_abbr = _ppd_logo_id = None
            if _ppd_leader_str == away_team_name.upper():
                _ppd_logo_abbr, _ppd_logo_id = away_team_name, str(game_data['away_team_id'])
            elif _ppd_leader_str == home_team_name.upper():
                _ppd_logo_abbr, _ppd_logo_id = home_team_name, str(game_data['home_team_id'])
            _ppd_score_w = int(font11.getlength(_ppd_score))
            _ppd_score_x = _rx - _ppd_score_w
            ctx.draw.text((_ppd_score_x, start_y + 5 * s), _ppd_score, font=font11, fill=0)
            ser_content_left_x = _ppd_score_x
            if _ppd_logo_abbr:
                _ppd_logo = _logo_small(_ppd_logo_abbr, _ppd_logo_id, size=14 * s)
                if _ppd_logo:
                    _lw, _lh = _ppd_logo.size
                    _ppd_logo_x = _ppd_score_x - 2 * s - _lw
                    _ppd_logo_y = start_y + (20 * s - _lh) // 2
                    ctx.paste(_ppd_logo, (_ppd_logo_x, _ppd_logo_y))
                    ser_content_left_x = _ppd_logo_x

    return ser_content_left_x


_LayoutFlags = namedtuple('_LayoutFlags', [
    'delayed_with_score', 'between_innings', 'pitching_change',
    'mid_inning_pc', 'game_ending_state',
])


def _compute_layout_flags(game_data):
    """Derive the layout decisions that select the linescore grid over the
    normal score layout, as a _LayoutFlags tuple."""
    state = game_data.get('detailed_state')

    delayed_with_score = (
        state == 'Delayed' and (game_data.get('current_inning') or 0) > 0
    )
    between_innings = (
        state == 'In Progress' and game_data.get('inningState') in ('Middle', 'End')
    )
    # Any pitching change shows the linescore grid.
    pitching_change = (
        state == 'In Progress' and (game_data.get('sub_event') or '').startswith('PC:')
    )
    # A PC during a live half-inning: fewer than 3 outs and the inning has
    # already started (an out recorded, or a pitch already thrown).
    mid_inning_pc = bool(
        pitching_change and not between_innings
        and (
            (game_data.get('num_of_outs') or 0) > 0
            or (game_data.get('at_bat_pitch_count') or 0) > 0
        )
    )
    # End of 9th+ with one team leading, or Mid 9th+ with the home team ahead —
    # the game is effectively over.
    inn_state = game_data.get('inningState') or ''
    away_runs = game_data.get('away_runs') or 0
    home_runs = game_data.get('home_runs') or 0
    game_ending_state = bool(
        (game_data.get('current_inning') or 0) >= 9
        and (
            (inn_state == 'End' and away_runs != home_runs)
            or (inn_state == 'Middle' and home_runs > away_runs)
        )
    )

    return _LayoutFlags(delayed_with_score, between_innings, pitching_change,
                        mid_inning_pc, game_ending_state)


def _draw_live_situation_panel(ctx, game_data, team_data, between_innings,
                              game_ending_state, pitching_change, mid_inning_pc,
                              force_linescore, ser_content_left_x):
    """Draw the live-game situation area: bases, count, outs and next batters.

    Which variant appears depends on where play currently is. An inning break —
    or a pitching change made before the half-inning is underway, which reads the
    same way — shows the upcoming batters and the incoming pitcher above the
    linescore grid. A mid-inning change keeps the live bases/outs and leaves the
    incoming pitcher to the ``P:`` line below, which names both pitchers. Normal
    live play shows bases/count/outs. The else branch covers every non-live
    state, which still needs the no-hitter banner.
    """
    # Names the body below reads; ctx owns the canvas and geometry.
    Himage, draw = ctx.Himage, ctx.draw
    start_x, start_y, s = ctx.x, ctx.y, ctx.s
    scale = ctx.s
    horizonta_len = ctx.w
    font14, font11, font9 = ctx.font14, ctx.font11, ctx.font9
    use_logos = ctx.use_logos
    _between_innings = between_innings
    _game_ending_state = game_ending_state
    _pitching_change = pitching_change
    _mid_inning_pc = mid_inning_pc
    _ser_content_left_x = ser_content_left_x

    # A pitching change made before the half-inning is underway sits above the
    # linescore grid, exactly like the inning break itself — mirrors _pc_grid.
    _break_panel = _between_innings or (_pitching_change and not _mid_inning_pc)

    if game_data['detailed_state'] == 'In Progress' and not force_linescore:
        if _between_innings and _game_ending_state:
            pass  # end of 9th+ with a lead — linescore shown, no next-batters panel
        elif _break_panel:
            # Between-innings break (including pitching changes announced during the break):
            # show the next three batters for the upcoming half-inning and the pitcher.
            _right_x = start_x + horizonta_len - 2 * s
            _left_x = start_x + 88 * s
            _max_name_w = _right_x - _left_x
            # Next half-inning order: leadoff first (top), on-deck, in-hole (bottom)
            _batter_names = [
                _last_name(game_data.get('next_batter_1') or game_data.get('current_hitter') or ''),
                _last_name(game_data.get('next_batter_2') or game_data.get('due_up') or ''),
                _last_name(game_data.get('next_batter_3') or game_data.get('in_hole') or ''),
            ]
            # If there's a pitching change announced between innings, use that pitcher name.
            _pc_raw = (game_data.get('sub_event') or '')[3:].strip() if _pitching_change else ''
            _pit_name = _pc_raw or _last_name(game_data.get('next_pitcher') or game_data.get('current_pitcher') or '')
            _name_y = start_y + 21 * s
            for _nm in _batter_names:
                if _nm:
                    _nm_disp = _nm
                    while _nm_disp and int(font14.getlength(_nm_disp)) > _max_name_w:
                        _nm_disp = _nm_disp[:-1]
                    draw.text((_left_x, _name_y), _nm_disp, font=font14, fill=0)
                _name_y += 12 * s
            # Separator line + pitcher name (no outs shown between innings)
            _sep_y = _name_y + 5 * s
            draw.line((start_x + 87 * s, _sep_y, _right_x, _sep_y), fill=0)
            _pit_max_w = _max_name_w
            if _pit_name:
                _pit_fnt = font14
                if int(font14.getlength(_pit_name)) > _pit_max_w:
                    _pit_fnt = font11
                    if int(font11.getlength(_pit_name)) > _pit_max_w:
                        _pit_fnt = font9
                        while _pit_name and int(font9.getlength(_pit_name)) > _pit_max_w:
                            _pit_name = _pit_name[:-1]
                draw.text((_left_x, _sep_y + 2 * s), _pit_name, font=_pit_fnt, fill=0)
        elif _mid_inning_pc:
            # Mid-inning PC: bases + outs at normal positions. The incoming pitcher
            # is named on the 'P:' line below (as "OUTGOING→INCOMING"), not here —
            # this row is where the pitch-count/speed line lands.
            _pc_outs = game_data.get('num_of_outs') or 0
            if _pc_outs < 3:
                _hi_third  = isinstance(game_data['runner_on_third'],  str)
                _hi_second = isinstance(game_data['runner_on_second'], str)
                _hi_first  = isinstance(game_data['runner_on_first'],  str)
                Himage = draw_diamond(Himage, (start_x + 97 * s,  start_y + 52 * s), 10 * s, _hi_third)
                Himage = draw_diamond(Himage, (start_x + 109 * s, start_y + 40 * s), 10 * s, _hi_second)
                Himage = draw_diamond(Himage, (start_x + 121 * s, start_y + 52 * s), 10 * s, _hi_first)
                draw = ImageDraw.Draw(Himage)
                for _bfill, _bcx, _bcy, _bkey in (
                    (_hi_third,  start_x + 97 * s,  start_y + 52 * s, 'runner_third_number'),
                    (_hi_second, start_x + 109 * s, start_y + 40 * s, 'runner_second_number'),
                    (_hi_first,  start_x + 121 * s, start_y + 52 * s, 'runner_first_number'),
                ):
                    if _bfill:
                        _raw = game_data.get(_bkey)
                        _bnum = str(_raw) if _raw is not None else ''
                        if _bnum:
                            draw_tight_number(draw, _bcx, _bcy, _bnum, font11, 255, bold=True)
            _pc_outs_list = [i + 1 <= _pc_outs for i in range(3)]
            Himage = draw_circle(Himage, (start_x + 97 * s,  start_y + 73 * s), 6 * s, _pc_outs_list[0], outline_width=2)
            Himage = draw_circle(Himage, (start_x + 111 * s, start_y + 73 * s), 6 * s, _pc_outs_list[1], outline_width=2)
            Himage = draw_circle(Himage, (start_x + 125 * s, start_y + 73 * s), 6 * s, _pc_outs_list[2], outline_width=2)
            draw = ImageDraw.Draw(Himage)
            _draw_out_labels_in_circles(
                draw, Himage,
                [start_x + 97 * s, start_x + 111 * s, start_x + 125 * s], start_y + 73 * s,
                _pc_outs_list, game_data.get('outs_this_half') or [], s,
            )
        else:
            # If 3 outs are recorded but inningState hasn't flipped to Middle/End yet
            # (API lag), show the linescore instead — prevents filled base diamonds
            # with no runner numbers from appearing at the end of a half-inning.
            if (game_data.get('num_of_outs') or 0) >= 3:
                draw, Himage = _draw_linescore_grid(
                    draw, Himage, start_x, start_y, game_data, team_data, use_logos, scale=scale
                )
            else:
                _hi_third = isinstance(game_data['runner_on_third'], str)
                _hi_second = isinstance(game_data['runner_on_second'], str)
                _hi_first = isinstance(game_data['runner_on_first'], str)

                Himage = draw_diamond(Himage, (start_x + 97 * s,  start_y + 52 * s), 10 * s, _hi_third)
                Himage = draw_diamond(Himage, (start_x + 109 * s, start_y + 40 * s), 10 * s, _hi_second)
                Himage = draw_diamond(Himage, (start_x + 121 * s, start_y + 52 * s), 10 * s, _hi_first)
                draw = ImageDraw.Draw(Himage)
                for _bfill, _bcx, _bcy, _bkey in (
                    (_hi_third,  start_x + 97 * s,  start_y + 52 * s, 'runner_third_number'),
                    (_hi_second, start_x + 109 * s, start_y + 40 * s, 'runner_second_number'),
                    (_hi_first,  start_x + 121 * s, start_y + 52 * s, 'runner_first_number'),
                ):
                    if _bfill:
                        _raw = game_data.get(_bkey)
                        _bnum = str(_raw) if _raw is not None else ''
                        if _bnum:
                            draw_tight_number(draw, _bcx, _bcy, _bnum, font11, 255, bold=True)

                outs_list = [None] * 3
                for i in range(1, 4):
                    outs_list[i-1] = i <= game_data['num_of_outs']
                Himage = draw_circle(Himage, (start_x + 97 * s,  start_y + 73 * s), 6 * s, outs_list[0], outline_width=2)
                Himage = draw_circle(Himage, (start_x + 111 * s, start_y + 73 * s), 6 * s, outs_list[1], outline_width=2)
                Himage = draw_circle(Himage, (start_x + 125 * s, start_y + 73 * s), 6 * s, outs_list[2], outline_width=2)
                draw = ImageDraw.Draw(Himage)
                _draw_out_labels_in_circles(
                    draw, Himage,
                    [start_x + 97 * s, start_x + 111 * s, start_x + 125 * s], start_y + 73 * s,
                    outs_list, game_data.get('outs_this_half') or [], s,
                )

                balls_list = [None] * 4
                for i in range(1, 4):
                    balls_list[i-1] = i <= game_data['balls']

                draw.text((start_x + 2 * s, start_y + 25 * s + 59 * s), 'B', font=font14, fill=0)
                Himage = draw_circle(Himage, (start_x + 19 * s, start_y + 25 * s + 68 * s), 4 * s, balls_list[0])
                Himage = draw_circle(Himage, (start_x + 31 * s, start_y + 25 * s + 68 * s), 4 * s, balls_list[1])
                Himage = draw_circle(Himage, (start_x + 43 * s, start_y + 25 * s + 68 * s), 4 * s, balls_list[2])

                _num_strikes = game_data.get('strikes') or 0
                strikes_list = [i + 1 <= _num_strikes for i in range(2)]
                _strike_calls = game_data.get('strike_calls', [])

                draw.text((start_x + 19 * s + 39 * s, start_y + 25 * s + 59 * s), 'S', font=font14, fill=0)
                for _si, (_scx, _scy) in enumerate([
                    (start_x + 19 * s + 55 * s, start_y + 25 * s + 68 * s),
                    (start_x + 31 * s + 55 * s, start_y + 25 * s + 68 * s),
                ]):
                    _call = _strike_calls[_si] if _si < len(_strike_calls) else None
                    if strikes_list[_si] and _call in ('S', 'F'):
                        # Swinging or foul: outline ring with ~80%-filled center
                        _ir = 4 * s - 2
                        Himage = draw_circle(Himage, (_scx, _scy), 4 * s, False)
                        draw = ImageDraw.Draw(Himage)
                        draw.ellipse([_scx - _ir, _scy - _ir, _scx + _ir, _scy + _ir], fill='black', outline='black')
                    else:
                        # Looking / empty: solid filled circle
                        Himage = draw_circle(Himage, (_scx, _scy), 4 * s, strikes_list[_si])
                        draw = ImageDraw.Draw(Himage)

        if game_data.get('save_situation') and not _between_innings and not _pitching_change:
            _sv_w = int(font9.getlength('SV'))
            _sv_x = start_x + horizonta_len - _sv_w - 2 * s
            _draw_bold_text(draw, (_sv_x, start_y + 25 * s), 'SV', font9, s)
    else:

        # Perfect game takes precedence over no-hitter display — right-aligned in header
        if game_data.get('perfect_game') or game_data.get('no_hitter'):
            _nh_label = 'Perfect Game' if game_data.get('perfect_game') else 'No-Hitter'
            _nh_lw = int(font14.getlength(_nh_label))
            _nh_lx = (_ser_content_left_x - 2 * s) - _nh_lw
            _draw_bold_text(draw, (_nh_lx, start_y + 3 * s), _nh_label, font14, s)

    # _draw_linescore_grid returns a new canvas/draw pair; hand both back.
    ctx.Himage, ctx.draw = Himage, draw


def _draw_pitchers_of_record(ctx, game_data, is_walkoff):
    """Draw the WP/LP/SV decision lines for a completed game.

    The block is anchored to the bottom of the tile and built upward, so a game
    with no save decision leaves whitespace above the two pitcher lines rather
    than moving them.
    """
    draw = ctx.draw
    s = ctx.s
    font14 = ctx.font14

    LINE_H = 15 * s
    BOTTOM_Y = ctx.y + ctx.h + 20 * s - 3 * s  # 3px margin above the bottom border
    max_w = ctx.w - 2 * s

    def _truncate_keep_suffix(text):
        """Fit ``text`` to the tile width, preferring to keep a trailing record."""
        if int(font14.getlength(text)) <= max_w:
            return text
        # Try dropping the first initial: "WP: W. Warren (2-2)" → "WP: Warren (2-2)"
        for _pfx in ('WP: ', 'LP: ', 'SV: '):
            if text.startswith(_pfx):
                _rest = text[len(_pfx):]
                if len(_rest) > 2 and _rest[1:3] == '. ':
                    _no_init = _pfx + _rest[3:]
                    if int(font14.getlength(_no_init)) <= max_w:
                        return _no_init
                    text = _no_init
                break
        # Still too wide: eat into the name and keep the record intact.
        paren = text.rfind(' (')
        if paren != -1:
            suffix = text[paren:]
            prefix = text[:paren]
            avail = max_w - int(font14.getlength(suffix))
            while prefix and int(font14.getlength(prefix)) > avail:
                prefix = prefix[:-1]
            return prefix + suffix
        while text and int(font14.getlength(text)) > max_w:
            text = text[:-1]
        return text

    winner_record = game_data.get('winner_record')
    loser_record = game_data.get('loser_record')
    wp_name = _format_player_name(game_data.get('winner_name') or '')
    lp_name = _format_player_name(game_data.get('loser_name') or '')
    lines = [
        f'LP: {lp_name} ({loser_record})' if loser_record else f'LP: {lp_name}',
        f'WP: {wp_name} ({winner_record})' if winner_record else f'WP: {wp_name}',
    ]
    # A walk-off ends the game on the winning run, so there is no save to show.
    saver = game_data.get('saver_name')
    if saver and not is_walkoff:
        sv_name = _format_player_name(saver)
        saver_saves = game_data.get('saver_saves')
        lines.append(f'SV: {sv_name} (S{saver_saves})' if saver_saves is not None else f'SV: {sv_name}')

    for i, txt in enumerate(reversed(lines)):
        draw.text((ctx.x + 2 * s, BOTTOM_Y - LINE_H * (i + 1)),
                  _truncate_keep_suffix(txt), font=font14, fill=0)


def _fit_text(font14, font11, text, max_w):
    """Return (text, font) shrunk to fit max_w pixels, preferring font14 then font11."""
    try:
        if font14.getlength(text) <= max_w:
            return text, font14
        if font11.getlength(text) <= max_w:  # pragma: no cover
            return text, font11
        while text and font11.getlength(text) > max_w:
            text = text[:-1]
        return text, font11
    except AttributeError:  # pragma: no cover
        return text[:17], font14


def _draw_body_live_active(ctx, game_data, mid_inning_pc):
    """Render pitch/pitcher/batter panel for an active (non-linescore) live game.

    Called from draw_box when the game is In Progress and neither between-innings
    nor a between-inning pitching change — i.e. actual play is happening.
    """
    draw = ctx.draw
    s = ctx.s
    start_x, start_y = ctx.x, ctx.y
    horizonta_len = ctx.w
    font14, font11 = ctx.font14, ctx.font11
    max_text_width = horizonta_len - 14 * s

    _pc = game_data.get('pitch_count')
    _ab_pc = game_data.get('at_bat_pitch_count') or 0
    _pt = game_data.get('last_pitch_type', '')
    _lps = game_data.get('last_pitch_speed')
    _pc_disp = f'{_pc}P' if _pc is not None else (f'AB{_ab_pc}' if _ab_pc else None)

    _pc_incoming = (game_data.get('sub_event') or '')[3:].strip() if mid_inning_pc else ''
    if _pc_incoming:
        _outgoing = _last_name(game_data.get('current_pitcher') or '')
        _pit_str = f'P: {_outgoing}→{_pc_incoming}' if _outgoing else f'P: {_pc_incoming}'
    else:
        _pit_str = f'P: {_format_player_name(game_data.get("current_pitcher") or "")}'
    _pit_y = start_y + 25 * s + 74 * s
    _pcb_w = int(font11.getlength(_pc_disp)) + 2 * s if _pc_disp else 0
    _pit_avail = max(1, max_text_width - _pcb_w)
    if font14.getlength(_pit_str) <= _pit_avail:
        pitcher_str, pitcher_font = _pit_str, font14
    else:
        pitcher_str, pitcher_font = _fit_text(font14, font11, _pit_str, _pit_avail)
    draw.text((start_x + 2 * s, _pit_y), pitcher_str, font=pitcher_font, fill=0)
    if _pc_disp:
        draw.text((start_x + horizonta_len - _pcb_w, _pit_y), _pc_disp, font=font11, fill=0)

    _speed_y = start_y + 25 * s + 62 * s
    if _lps:
        _speed_str = f'{_pt} {int(_lps)}' if _pt else str(int(_lps))
        _speed_w = int(font11.getlength(_speed_str)) + 2 * s
        _draw_bold_text(draw, (start_x + horizonta_len - _speed_w, _speed_y), _speed_str, font11, s)
    elif _pt:
        _pt_w = int(font11.getlength(_pt)) + 2 * s
        draw.text((start_x + horizonta_len - _pt_w, _speed_y), _pt, font=font11, fill=0)

    _bh = game_data.get('batter_hits')
    _ba = game_data.get('batter_at_bats')
    _ba_str = f'{_bh}-{_ba}' if _bh is not None and _ba is not None else ''
    _ba_w = min(int(font11.getlength(_ba_str)) + 2 * s, horizonta_len - 8 * s) if _ba_str else 0
    _ab_done = game_data.get('current_at_bat_complete', False)
    if _ab_done and not _is_game_effectively_over(game_data):
        _next_hitter = _format_player_name(
            game_data.get('due_up') or game_data.get('next_batter_1') or ''
        )
        if _next_hitter:
            _next_str, _next_font = _fit_text(font14, font11,
                                               f'AB: {_next_hitter}',
                                               max(1, max_text_width - _ba_w))
            draw.text((start_x + 2 * s, start_y + 25 * s + 89 * s), _next_str, font=_next_font, fill=0)
    else:
        _hitter_name = _format_player_name(
            game_data.get('current_play_batter') or game_data.get('current_hitter') or ''
        )
        hitter_str, hitter_font = _fit_text(font14, font11,
                                             f'AB: {_hitter_name}',
                                             max(1, max_text_width - _ba_w))
        draw.text((start_x + 2 * s, start_y + 25 * s + 89 * s), hitter_str, font=hitter_font, fill=0)
    if _ba_str:
        draw.text((start_x + horizonta_len - _ba_w, start_y + 25 * s + 89 * s), _ba_str, font=font11, fill=0)


def _draw_body_pregame(ctx, game_data, team_data, is_lineup_mode, cfg):
    """Render the pre-game cell body (Scheduled / Pre-Game / Warmup).

    Two paths:
    - Lineup mode (≤60 min to first pitch, lineups posted): two-column batting order.
    - Default: pitcher-probables with ERA.
    Mutates ctx.draw / ctx.Himage when logos are pasted.
    """
    draw = ctx.draw
    Himage = ctx.Himage
    s = ctx.s
    start_x, start_y = ctx.x, ctx.y
    horizonta_len = ctx.w
    font14, font11, font9 = ctx.font14, ctx.font11, ctx.font9
    use_logos = ctx.use_logos
    max_text_width = horizonta_len - 14 * s

    away_team_id = str(game_data['away_team_id'])
    home_team_id = str(game_data['home_team_id'])
    abbr_map = team_data.get('team_abbreviation', {})
    away_team_name = _TEAM_ID_ABBR_OVERRIDE.get(away_team_id) or abbr_map.get(away_team_id, f'T{away_team_id}')
    home_team_name = _TEAM_ID_ABBR_OVERRIDE.get(home_team_id) or abbr_map.get(home_team_id, f'T{home_team_id}')

    if is_lineup_mode:
        _lu_away = game_data.get('away_lineup') or []
        _lu_home = game_data.get('home_lineup') or []
        _lu_away_sp = _format_player_name(game_data.get('away_probable') or '')
        _lu_home_sp = _format_player_name(game_data.get('home_probable') or '')
        _lu_cell_h  = 150 * s
        _lu_body_y0 = start_y + 31 * s
        _lu_logo_h  = 26 * s
        _lu_body_y  = _lu_body_y0 + _lu_logo_h
        _lu_sp_h    = 11 * s
        _lu_n_rows  = 9
        _lu_col_w   = (135 * s) // 2
        _lu_mid_x   = start_x + _lu_col_w
        _lu_pad     = 2 * s

        if use_logos:
            _lu_logo_bottom = _lu_body_y0 + _lu_logo_h - 2 * s
            _lu_logo_sz = min(30 * s, _lu_col_w - 10 * s)
            _lu_logo_y  = _lu_logo_bottom - _lu_logo_sz
            _lu_away_logo = _logo_small(away_team_name, away_team_id, size=_lu_logo_sz)
            _lu_home_logo = _logo_small(home_team_name, home_team_id, size=_lu_logo_sz)
            if _lu_away_logo:
                _lu_alx = start_x + (_lu_col_w - _lu_away_logo.width) // 2
                Himage.paste(_lu_away_logo, (_lu_alx, _lu_logo_bottom - _lu_away_logo.height))
            if _lu_home_logo:
                _lu_hlx = _lu_mid_x + (_lu_col_w - _lu_home_logo.width) // 2
                Himage.paste(_lu_home_logo, (_lu_hlx, _lu_logo_bottom - _lu_home_logo.height))
            _lu_vs_txt = 'vs'
            _lu_vs_w   = int(font11.getlength(_lu_vs_txt))
            draw.text((_lu_mid_x - _lu_vs_w // 2, _lu_logo_y + (_lu_logo_sz - 11 * s) // 2),
                      _lu_vs_txt, font=font11, fill=0)
            draw = ImageDraw.Draw(Himage)

        draw.line([(_lu_mid_x, _lu_body_y), (_lu_mid_x, start_y + _lu_cell_h - s)], fill=0)

        if use_logos and cfg.get('lineup_logo_background', False):
            _lu_body_h   = _lu_cell_h - (_lu_body_y0 - start_y) - _lu_logo_h - _lu_sp_h
            _lu_ghost_sz = min(_lu_col_w - 4 * s, _lu_body_h - 4 * s)
            for _lu_abbr, _lu_tid, _lu_cx in (
                (away_team_name, away_team_id, start_x),
                (home_team_name, home_team_id, _lu_mid_x),
            ):
                _lu_ghost = _logo_ghost(_lu_abbr, _lu_tid, size=_lu_ghost_sz, lightness=160)
                if _lu_ghost:
                    _lu_gw, _lu_gh = _lu_ghost.size
                    _lu_gx = _lu_cx + (_lu_col_w - _lu_gw) // 2
                    _lu_gy = _lu_body_y + (_lu_body_h - _lu_gh) // 2
                    _paste_logo(Himage, _lu_ghost, (_lu_gx, _lu_gy))
            draw = ImageDraw.Draw(Himage)

        _lu_row_top = _lu_body_y
        _lu_avail_h = _lu_cell_h - (_lu_body_y0 - start_y) - _lu_logo_h - _lu_sp_h
        _lu_row_h   = _lu_avail_h // _lu_n_rows
        _lu_all_pos = [p.get('pos', '') for p in _lu_away + _lu_home]
        _lu_gpw = max((int(font9.getlength(p)) for p in _lu_all_pos), default=0)
        _lu_pos_gap = _lu_col_w - _lu_gpw - _lu_pad - s

        def _lu_render_col(lineup, col_x):
            for _ri in range(_lu_n_rows):
                _ry = _lu_row_top + _ri * _lu_row_h
                if _ri < len(lineup):
                    _rname = _format_player_name(lineup[_ri].get('name', ''))
                    _rpos  = lineup[_ri].get('pos', '')
                else:
                    _rname, _rpos = '', ''
                if _rpos:
                    _rpw = int(font9.getlength(_rpos))
                    draw.text((col_x + _lu_pos_gap + (_lu_gpw - _rpw), _ry), _rpos, font=font9, fill=0)
                _max_rw = _lu_pos_gap - 2 * s - _lu_pad
                while _rname and int(font9.getlength(_rname)) > _max_rw:
                    _rname = _rname[:-1]
                if _rname:
                    draw.text((col_x + _lu_pad, _ry), _rname, font=font9, fill=0)

        _lu_render_col(_lu_away, start_x)
        _lu_render_col(_lu_home, _lu_mid_x)

        _lu_sp_y = start_y + _lu_cell_h - _lu_sp_h
        draw.line([(start_x, _lu_sp_y + s), (start_x + 135 * s - s, _lu_sp_y + s)], fill=0)
        _lu_pw = int(font9.getlength('P'))
        for _lu_sp, _lu_sx in ((_lu_away_sp, start_x), (_lu_home_sp, _lu_mid_x)):
            draw.text((_lu_sx + _lu_pos_gap + (_lu_gpw - _lu_pw), _lu_sp_y + s), 'P', font=font9, fill=0)
            _max_sw = _lu_pos_gap - 2 * s - _lu_pad
            _sp_trunc = _lu_sp
            while _sp_trunc and int(font9.getlength(_sp_trunc)) > _max_sw:
                _sp_trunc = _sp_trunc[:-1]
            if _sp_trunc:
                draw.text((_lu_sx + _lu_pad, _lu_sp_y + s), _sp_trunc, font=font9, fill=0)
    else:
        def _draw_pitcher_era(name_part, stat_part, y_pos):
            if stat_part:
                stat_w = int(font14.getlength(stat_part))
                stat_x = start_x + horizonta_len - stat_w - 1 * s
                draw.text((stat_x, y_pos), stat_part, font=font14, fill=0)
                max_name_w = stat_x - (start_x + 2 * s) - 2 * s
                name_str, name_fnt = _fit_text(font14, font11, name_part, max(max_name_w, 20 * s))
                draw.text((start_x + 2 * s, y_pos), name_str, font=name_fnt, fill=0)
            else:
                name_str, name_fnt = _fit_text(font14, font11, name_part, max_text_width)
                draw.text((start_x + 2 * s, y_pos), name_str, font=name_fnt, fill=0)

        away_name, away_stat = _pitcher_line(game_data.get('away_probable'), game_data.get('away_probable_note'))
        home_name, home_stat = _pitcher_line(game_data.get('home_probable'), game_data.get('home_probable_note'))
        _draw_pitcher_era(away_name, away_stat, start_y + 25 * s + 59 * s)
        _draw_pitcher_era(home_name, home_stat, start_y + 25 * s + 74 * s)

    ctx.draw = draw
    ctx.Himage = Himage


@dataclass
class DrawOptions:
    """Optional settings for draw_box / draw_wide_box / draw_triple_box.

    Callers can pass individual keyword arguments (backwards-compatible) or
    construct a DrawOptions instance and spread it, whichever is cleaner.
    """
    score_changed: bool = False
    use_logos: bool = False
    logo_x_offset: int = 2
    show_win_prob: bool = False
    streak_map: Optional[dict] = field(default=None)
    show_winner_logo: bool = True
    scale: int = 1
    force_linescore: bool = False
    always_show_hits: bool = False
    hide_last_play: bool = False
    skip_header_invert: bool = False
    win_prob_center_line: bool = True


def draw_box(Himage, start_x, start_y, game_data, team_data, score_changed=False, use_logos=False, logo_x_offset=2, show_win_prob=False, streak_map=None, show_winner_logo=True, scale=1, force_linescore=False, always_show_hits=False, hide_last_play=False, skip_header_invert=False, win_prob_center_line=True):
    """Render a single game score box onto Himage at (start_x, start_y)."""
    s = scale
    _is_walkoff = bool(game_data.get('walk_off'))
    game_data, _challenge_abbr, _original_detailed_state = _normalize_game_state(game_data)

    ctx = _TileCtx(Himage, start_x, start_y, s, use_logos, logo_x_offset)
    # Local aliases for the geometry and fonts the body reads constantly. New
    # code should prefer ctx directly; these keep the existing body readable
    # rather than prefixing several hundred references.
    draw = ctx.draw
    font24, font18, font14 = ctx.font24, ctx.font18, ctx.font14
    font11, font9 = ctx.font11, ctx.font9

    # Lineup mode: within 1 hour of first pitch with lineup data posted.
    # Replaces pitcher-probables body and team-records section with batting orders.
    _is_lineup_mode = (
        game_data.get('detailed_state') in ('Scheduled', 'Pre-Game', 'Warmup')
        and _game_within_minutes_check(game_data, 60)
        and bool(game_data.get('away_lineup') or game_data.get('home_lineup'))
    )

    _cfg = load_yaml_file('config.yaml')
    _FINAL_LINESCORE_SECS = _cfg.get('final_linescore_minutes', 60) * 60

    vertical_len = ctx.h
    horizonta_len = ctx.w
    max_text_width = horizonta_len - 14 * s

    # Layout flags consumed by the elif chain below — computed up front so every
    # branch can reference them.
    _flags = _compute_layout_flags(game_data)
    _delayed_with_score = _flags.delayed_with_score
    _between_innings = _flags.between_innings
    _pitching_change = _flags.pitching_change
    _mid_inning_pc = _flags.mid_inning_pc
    _game_ending_state = _flags.game_ending_state

    _in_linescore_window = False  # set True inside Final block when within the linescore window
    # Read unconditionally: the end-time footer and the next-game preview below
    # both use it, and it used to be defined only inside the Final branch.
    _end_utc_str = game_data.get('game_end_time_utc')

    def fit_text(text, max_w):
        return _fit_text(font14, font11, text, max_w)

    # team names short
    away_team_id = str(game_data['away_team_id'])
    home_team_id = str(game_data['home_team_id'])

    # Handle missing team abbreviations gracefully
    abbr_map = team_data.get('team_abbreviation', {})
    away_team_name = _TEAM_ID_ABBR_OVERRIDE.get(away_team_id) or abbr_map.get(away_team_id, f'T{away_team_id}')
    home_team_name = _TEAM_ID_ABBR_OVERRIDE.get(home_team_id) or abbr_map.get(home_team_id, f'T{home_team_id}')

    # Background ghosts — drawn first so all content renders on top.
    _draw_background_ghosts(
        ctx, game_data, show_winner_logo=show_winner_logo,
        away_team=(away_team_name, away_team_id),
        home_team=(home_team_name, home_team_id),
    )
    draw = ctx.draw

    # Game-state body dispatch — each branch renders what goes inside the cell.
    _state = game_data['detailed_state']
    if _state in ('Final', 'Game Over', 'Final: Tied'):
        away_inning_runs = game_data.get('away_inning_runs') or []
        home_inning_runs = game_data.get('home_inning_runs') or []
        winner_name = game_data.get('winner_name')
        loser_name = game_data.get('loser_name')
        _in_linescore_window = _in_final_linescore_window(game_data, _FINAL_LINESCORE_SECS)
        _decisions_ready = bool(winner_name and loser_name)
        _show_linescore = (away_inning_runs or home_inning_runs) and (
            _in_linescore_window or not _decisions_ready
        )
        if _show_linescore:
            draw, Himage = _draw_linescore_grid(draw, Himage, start_x, start_y, game_data, team_data, use_logos, scale=scale)
        else:
            _draw_pitchers_of_record(ctx, game_data, _is_walkoff)

    elif _state in ('Warmup', 'Pre-Game', 'Scheduled'):
        _draw_body_pregame(ctx, game_data, team_data, _is_lineup_mode, _cfg)
        draw, Himage = ctx.draw, ctx.Himage

    elif _state == 'Postponed':
        reason = game_data.get('postpone_reason') or game_data.get('description') or ''
        postponed_line, postponed_fnt = fit_text(f'PPD: {reason}' if reason else 'Postponed', max_text_width)
        draw.text((start_x + 7 * s, start_y + 25 * s + 59 * s), postponed_line, font=postponed_fnt, fill=0)
        desc = game_data.get('description') or ''
        if desc.lower().startswith('makeup') and game_data.get('postpone_reason'):
            makeup_line, makeup_fnt = fit_text(desc, max_text_width)
            draw.text((start_x + 7 * s, start_y + 25 * s + 74 * s), makeup_line, font=makeup_fnt, fill=0)

    elif _state == 'Suspended' or _delayed_with_score:
        draw, Himage = _draw_linescore_grid(draw, Himage, start_x, start_y, game_data, team_data, use_logos, scale=scale)
        if _delayed_with_score:
            _right_x = start_x + horizonta_len - 2 * s
            _max_name_w = 46 * s
            _batter_names = [
                _last_name(game_data.get('next_batter_1') or game_data.get('current_hitter') or ''),
                _last_name(game_data.get('next_batter_2') or game_data.get('due_up') or ''),
                _last_name(game_data.get('next_batter_3') or game_data.get('in_hole') or ''),
            ]
            _name_y = start_y + 21 * s
            for _nm in _batter_names:
                if _nm:
                    _nm_disp = _nm
                    while _nm_disp and int(font14.getlength(_nm_disp)) > _max_name_w:
                        _nm_disp = _nm_disp[:-1]
                    _nw = int(font14.getlength(_nm_disp))
                    draw.text((_right_x - _nw, _name_y), _nm_disp, font=font14, fill=0)
                _name_y += 12 * s
            _sep_y = _name_y + 5 * s
            draw.line((start_x + 87 * s, _sep_y, _right_x, _sep_y), fill=0)
            _pit_name = _last_name(game_data.get('next_pitcher') or game_data.get('current_pitcher') or '')
            _pit_max_w = horizonta_len - 2 * s - 87 * s
            if _pit_name:
                _pit_fnt = font14
                if int(font14.getlength(_pit_name)) > _pit_max_w:
                    _pit_fnt = font11
                    if int(font11.getlength(_pit_name)) > _pit_max_w:
                        _pit_fnt = font9
                        while _pit_name and int(font9.getlength(_pit_name)) > _pit_max_w:
                            _pit_name = _pit_name[:-1]
                _pit_w = int(_pit_fnt.getlength(_pit_name))
                draw.text((_right_x - _pit_w, _sep_y + 2 * s), _pit_name, font=_pit_fnt, fill=0)

    elif _state == 'In Progress':
        _pc_grid = _pitching_change and not _mid_inning_pc
        _show_grid = _between_innings or _pc_grid or force_linescore
        if _show_grid:
            draw, Himage = _draw_linescore_grid(draw, Himage, start_x, start_y, game_data, team_data, use_logos, scale=scale)
        else:
            _draw_body_live_active(ctx, game_data, _mid_inning_pc)

    game_state_str = _compute_game_state_str(
        game_data, _original_detailed_state, _game_ending_state, _between_innings)

    # DH label vars — defined early so both the header-override block below
    # and the later duration block can use them.
    _dh    = game_data.get('double_header', 'N')
    _gnum  = game_data.get('game_number')
    _dh_is_active = _dh in ('Y', 'S') and _gnum
    _dh_scheduled = _dh_is_active and game_data['detailed_state'] in ('Scheduled', 'Pre-Game', 'Warmup')

    # Pre-draw SWEEP ghost before header text so Final / logo sit on top
    _gf_early = game_data.get('detailed_state') in ('Final', 'Game Over', 'Final: Tied')
    _st_early  = game_data.get('series_total_games') or 1
    _se_wins   = game_data.get('series_wins', 0) or 0
    _se_losses = game_data.get('series_losses', 0) or 0
    _se_desc   = game_data.get('series_description', '')
    _se_one_side_won = (_se_losses == 0 or _se_wins == 0)
    _is_sweep_early = (
        _gf_early and
        _st_early > 1 and
        _se_one_side_won and
        (
            (_se_desc == 'Regular Season' and (_se_wins + _se_losses) == _st_early) or
            (_se_desc != 'Regular Season' and bool(game_data.get('series_is_over')))
        )
    )
    if _is_sweep_early:
        _sw_text = 'SWEEP'
        _sw_w    = int(font18.getlength(_sw_text))
        _sw_x    = (horizonta_len - _sw_w) // 2
        _sw_y    = (20 * s - 18 * s) // 2
        _draw_bold_text(draw, (start_x + _sw_x, start_y + _sw_y), _sw_text, font18, s)
    elif _is_walkoff:
        # Walkoff replaces the header duration (which moves between the team
        # rows below, mirroring the SWEEP layout) — font14 (not font18, like
        # SWEEP) so the wider word doesn't collide with the "Final" label.
        _wo_text = 'WALKOFF'
        _wo_w    = int(font14.getlength(_wo_text))
        _wo_x    = (horizonta_len - _wo_w) // 2
        _wo_y    = 3 * s
        _draw_bold_text(draw, (start_x + _wo_x, start_y + _wo_y), _wo_text, font14, s)
    # _dh_scheduled's "Game N" label is drawn later, in the same small corner
    # spot the moved duration uses for sweep/walkoff finals (see below), so the
    # header stays free for the venue name.

    # game state — bold via double draw; for pre-game times render AM/PM smaller + bold
    if game_data['detailed_state'] in ('Scheduled', 'Pre-Game', 'Warmup') and ' ' in game_state_str:
        _time_parts = game_state_str.rsplit(' ', 1)
        _time_main, _time_ampm = _time_parts[0], _time_parts[1].lower()
        for _dx in (2 * s, 3 * s):
            draw.text((start_x + _dx, start_y + 3 * s), _time_main, font=font14, fill=0)
        _main_w = int(font14.getlength(_time_main))
        _ampm_x = start_x + 3 * s + _main_w + 1 * s
        _ampm_y = start_y + 8 * s
        draw.text((_ampm_x, _ampm_y), _time_ampm, font=font9, fill=0)
        _total_time_w = _main_w + int(font9.getlength(_time_ampm)) + 2 * s
    else:
        draw.text((start_x + 2 * s, start_y + 3 * s), game_state_str, font=font14, fill=0)
        draw.text((start_x + 3 * s, start_y + 3 * s), game_state_str, font=font14, fill=0)
        _total_time_w = int(font14.getlength(game_state_str))

    # Series display — only shown when the game is Final/over, not pre-game or live
    _ser = _compute_series_state(game_data)
    _game_is_final = _ser.game_is_final
    _active_no_no = _ser.active_no_no
    _is_sweep = _ser.is_sweep

    _ser_content_left_x = _draw_series_header_state(
        ctx, game_data, away_team_name, home_team_name, away_team_id, home_team_id, _ser)
    draw = ctx.draw  # refresh after potential paste inside the helper

    # Delay reason — right-anchored where the venue normally lives.
    _is_any_delay = (
        _original_detailed_state == 'Delayed Start'
        or game_data['detailed_state'] == 'Delayed'
        or bool(game_data.get('postpone_reason'))
    )
    _hdr_right = _ser_content_left_x - 2 * s
    _hdr_max_w = max(_hdr_right - start_x - _total_time_w - 6 * s, 0)

    if _is_any_delay:
        _draw_header_right_text(
            ctx, game_data.get('postpone_reason') or '', _hdr_right, _hdr_max_w,
            _DELAY_FONT_LADDER, truncate=True)

    # Venue — right-anchored in header, as large as possible without overlapping
    # the time. Always shown for a scheduled game, including doubleheaders:
    # "Game N" lives in the corner spot below (see the _dh_scheduled block near
    # the duration code) rather than the header, so it no longer collides.
    elif game_data['detailed_state'] in ('Scheduled', 'Pre-Game', 'Warmup'):
        _draw_header_right_text(
            ctx, _clean_venue_name(game_data.get('venue')) or '',
            _hdr_right, _hdr_max_w, _VENUE_FONT_LADDER)

    if game_data['detailed_state'] == 'In Progress':
        _sub_ev = (game_data.get('sub_event') or '').strip()
        # Only include last_play when it belongs to the current half-inning.
        # The API stores inning + isTopInning on every play; compare to the live linescore.
        _cur_inn = game_data.get('current_inning')
        _cur_is_top = game_data.get('inningState') in ('Top', 'Middle')
        _lp_inn = game_data.get('last_play_inning')
        _lp_is_top = game_data.get('last_play_is_top')
        _lp_same_half = (
            _lp_inn is not None and
            _lp_inn == _cur_inn and
            bool(_lp_is_top) == _cur_is_top
        )
        _last_play_val = game_data.get('last_play') if _lp_same_half else None
        # Between innings: suppress sub_event so the last real play (out) shows instead.
        # Mid-inning PC: include sub_event so the PC label appears in the header.
        if _between_innings:
            raw_play = (game_data.get('last_review_result') or _last_play_val or '').replace('**', '').strip()
        else:
            raw_play = (_sub_ev or game_data.get('last_review_result') or _last_play_val or '').replace('**', '').strip()
        # Abbreviate verbose play names so they fit cleanly without truncation
        play_display = _abbr_play(raw_play) if raw_play else ''
        # Enhance bare out-type abbreviations with fielder position from description.
        # Only applies when last_play came from the winProbability endpoint (e.g. "Flyout"→"FO").
        # When the live-feed path already returned scorecard notation (e.g. "F7"), _abbr_play
        # leaves it unchanged and it won't match any of the bare types below.
        _lp_desc = game_data.get('last_play_description', '') or ''
        if _lp_desc and not game_data.get('last_review_result'):
            if play_display == 'FO':
                _fp = _fielder_from_desc(_lp_desc)
                if _fp:
                    play_display = f'F{_fp}'
            elif play_display == 'LO':
                _fp = _fielder_from_desc(_lp_desc)
                if _fp:
                    play_display = f'L{_fp}'
            elif play_display == 'PO':
                _fp = _fielder_from_desc(_lp_desc)
                if _fp:
                    play_display = f'P{_fp}'
            elif play_display in ('SAC F', 'SAC B'):
                _fp = _fielder_from_desc(_lp_desc)
                if _fp:
                    play_display = f'{play_display}{_fp}'
            elif play_display in ('GO', 'FOUT'):
                _fseq = _fielder_seq_from_desc(_lp_desc)
                if _fseq:
                    play_display = f'{_fseq}'
            elif play_display in ('GDP', 'DP'):
                _fseq = _fielder_seq_from_desc(_lp_desc)
                if _fseq:
                    play_display = f'{_fseq} DP'
            elif play_display == 'TP':
                _fseq = _fielder_seq_from_desc(_lp_desc)
                if _fseq:
                    play_display = f'{_fseq} TP'
            elif play_display == 'CS':
                _fseq = _fielder_seq_from_desc(_lp_desc)
                if _fseq:
                    play_display = f'CS {_fseq}'
            elif play_display == 'PK':
                _fseq = _fielder_seq_from_desc(_lp_desc)
                play_display = f'PO {_fseq}' if _fseq else 'PO'
            elif play_display == 'E':
                _ep = _fielder_from_desc(_lp_desc)
                if _ep:
                    play_display = f'E{_ep}'
            elif play_display == 'K':
                # Win-probability endpoint sometimes returns 'Strikeout' for called strikeouts.
                # When the description says "called out on strikes" / "strikes out looking",
                # upgrade to 'Kl' so the backwards K is rendered.
                _dl = _lp_desc.lower()
                if 'called out on strikes' in _dl or 'strikes out looking' in _dl:
                    play_display = 'Kl'
        # Prepend RBI count when the play drove in runs.
        # Between innings the inning ended on an out — only tag-out plays (CS/PO/RO) can
        # legitimately have an RBI credited on the same play as the final out.
        # Errors never receive RBI credit.
        _rbi = int(game_data.get('last_play_rbi') or 0)
        _is_error = bool(play_display) and (
            play_display.startswith('E') or ' E' in play_display
        )
        _is_tag_out = bool(play_display) and play_display.startswith(('CS', 'PO', 'RO'))
        if _rbi > 0 and play_display and not _sub_ev and not game_data.get('last_review_result') and not _is_error:
            if not _between_innings or _is_tag_out:
                if play_display == 'HR':
                    if _rbi == 4:
                        play_display = 'Grand Slam'
                    elif _rbi >= 2:
                        play_display = f'{_rbi}R HR'
                    # solo HR: no prefix
                elif _rbi == 1:
                    play_display = f'RBI {play_display}'
                else:
                    play_display = f'{_rbi}RBI {play_display}'
        # Extra-inning automatic runner: show "Manfred Man" before any play this half
        if (
            not _between_innings and not play_display and not _pitching_change and
            (game_data.get('current_inning') or 0) >= 10 and
            game_data.get('runner_on_second') and
            not (game_data.get('num_of_outs') or 0) and
            not (game_data.get('at_bat_pitch_count') or 0)
        ):
            play_display = 'Manfred Man'

        _header_right = _ser_content_left_x - 2 * s

        def _draw_play_right(text, fnt=None, y_off=4):
            """Draw a right-anchored header label, shrinking it to the space left
            of the series block. Returns the drawn (x, width), or None if it
            didn't fit — callers that decorate the label need its extent."""
            if not text:  # pragma: no cover
                return None
            _fnt = fnt or _get_font(12 * s)
            _max_w = max(_header_right - start_x - _total_time_w - 10 * s, 0)
            _t = text
            _meas = _t.replace('Kl', 'K')
            while len(_t) > 1 and int(_fnt.getlength(_meas)) > _max_w:  # pragma: no cover
                _t = _t[:-2] + '.'
                _meas = _t.replace('Kl', 'K')
            if _meas and int(_fnt.getlength(_meas)) <= _max_w:
                _pw = int(_fnt.getlength(_meas))
                _px = _header_right - _pw
                _py = start_y + y_off * s
                if 'Kl' not in _t:
                    _draw_bold_text(draw, (_px, _py), _t, _fnt, s)
                else:
                    _parts = _t.split('Kl')
                    for _bx in (_px, _px + 1 * s):
                        _cx = _bx
                        for _i, _seg in enumerate(_parts):
                            if _seg:
                                draw.text((_cx, _py), _seg, font=_fnt, fill=0)
                                _cx += int(_fnt.getlength(_seg))
                            if _i < len(_parts) - 1:
                                _draw_backwards_k(Himage, _cx, _py, _fnt)
                                _cx += int(_fnt.getlength('K'))
                return _px, _pw
            return None  # pragma: no cover - only when the label can't be shrunk to fit

        if hide_last_play:
            # Wide cell: events live in the spanning header, not the left cell.
            pass
        elif _active_no_no:
            # Right-align label; inning state stays on left as-is
            _nh_label = 'Perfect Game' if game_data.get('perfect_game') else 'No-Hitter'
            _nh_lw = int(font14.getlength(_nh_label))
            _nh_lx = _header_right - _nh_lw
            _draw_bold_text(draw, (_nh_lx, start_y + 3 * s), _nh_label, font14, s)
        elif _mid_inning_pc:
            # A change with the half-inning still live is an event, not the
            # routine between-innings swap: the out count says why the manager
            # came out, and the inverted chip separates the two at a glance.
            # Never labelled 'Mid' — that reads as the Middle-of-inning break
            # the header shows on the left, which is the opposite state.
            _pc_label = f'PC {game_data.get("num_of_outs") or 0} OUT'
            _pc_span = _draw_play_right(_pc_label)
            if _pc_span:
                # Right edge stops 1px past the text (the bold offset) rather than
                # padding symmetrically — the series block starts 2px further right.
                _chip = (_pc_span[0] - 2 * s, start_y + 2 * s, _header_right + 1 * s, start_y + 19 * s)
                ctx.paste(ImageOps.invert(Himage.crop(_chip).convert('L')).convert('1'),
                          (_chip[0], _chip[1]))
                draw = ctx.draw
        elif _pitching_change:
            _draw_play_right('P.CHG')
        elif _between_innings and play_display:
            # Mid-inning break: show abbreviated play that ended the half-inning
            _draw_play_right(play_display)
        elif _between_innings:
            # No last-play text — fall back to who's due up
            _due_name = _format_player_name(game_data.get('current_hitter') or '')
            if _due_name:
                _due_str = f'Due: {_due_name}'
                _due_fnt = font11
                _max_due_w = max(_header_right - start_x - _total_time_w - 6 * s, 0)
                while _due_str and int(_due_fnt.getlength(_due_str)) > _max_due_w:
                    _due_str = _due_str[:-1]
                if _due_str:
                    _due_w = int(_due_fnt.getlength(_due_str))
                    _due_x = _header_right - _due_w
                    _draw_bold_text(draw, (_due_x, start_y + 5 * s), _due_str, _due_fnt, s)
        elif _challenge_abbr and play_display and use_logos:
            # Challenge: show challenging team logo to the left of right-aligned challenge text
            _fnt = _get_font(12 * s)
            _chal_w = int(_fnt.getlength(play_display))
            _chal_tid = away_team_id if _challenge_abbr == away_team_name else (
                home_team_id if _challenge_abbr == home_team_name else None
            )
            _chal_logo = _logo_small(_challenge_abbr, str(_chal_tid), size=14 * s) if _chal_tid else None
            if _chal_logo:
                _lw, _lh = _chal_logo.size
                _tx = _header_right - _chal_w
                _ly = start_y + (21 * s - _lh) // 2
                Himage.paste(_chal_logo, (_tx - 2 * s - _lw, _ly))
                draw = ImageDraw.Draw(Himage)
                _draw_bold_text(draw, (_tx, start_y + 4 * s), play_display, _fnt, s)
            else:
                _draw_play_right(f'{play_display} {_challenge_abbr}'.strip())
        elif play_display:
            _draw_play_right(play_display)

    # Initialize score variables (will be used later for winner display)
    away_runs = str(game_data.get('away_runs', 0) if game_data.get('away_runs', 0) is not None else 0)
    home_runs = str(game_data.get('home_runs', 0) if game_data.get('home_runs', 0) is not None else 0)

    is_game_started = game_data['detailed_state'] in ['Final', 'Game Over', 'In Progress', 'Final: Tied', 'Suspended'] or _delayed_with_score
    is_game_finished = game_data['detailed_state'] in ['Final', 'Game Over', 'Final: Tied']

    # Display score if game has started
    if is_game_started:
        draw.text((start_x + 68 * s + check_if_two_chars(away_runs), start_y + 25 * s), away_runs, font=font24, fill=0)
        draw.text((start_x + 68 * s + check_if_two_chars(home_runs), start_y + 55 * s), home_runs, font=font24, fill=0)

        if is_game_finished or always_show_hits:
            # hits
            away_hits = str(game_data.get('away_hits', 0) if game_data.get('away_hits', 0) is not None else 0)
            home_hits = str(game_data.get('home_hits', 0) if game_data.get('home_hits', 0) is not None else 0)
            draw.text((start_x + 95 * s + check_if_two_chars(away_hits), start_y + 25 * s),  away_hits, font=font24, fill=0)
            draw.text((start_x + 95 * s + check_if_two_chars(home_hits), start_y + 55 * s), home_hits , font=font24, fill=0)

        if is_game_finished or always_show_hits:
            # errors
            draw.text((start_x + 123 * s, start_y + 25 * s),  str(game_data.get('away_errors', 0) if game_data.get('away_errors', 0) is not None else 0), font=font24, fill=0)
            draw.text((start_x + 123 * s, start_y + 55 * s),  str( game_data.get('home_errors', 0) if game_data.get('home_errors', 0) is not None else 0), font=font24, fill=0)

    elif game_data['detailed_state'] in ['Scheduled', 'Pre-Game', 'Warmup', 'Postponed']:
        # Game hasn't started — show record stacked above L10/streak, both right-anchored
        def _team_stats(team_id):
            """Team stats."""
            if streak_map:
                return streak_map.get(str(team_id)) or {}
            return {}

        def _draw_record(wins, losses, team_id, y_pos):
            """Draw record."""
            # Primary: W-L in font14, bold via double-draw, aligned to top of logo row
            main_txt = f'{wins}-{losses}'
            main_w = int(font14.getlength(main_txt))
            rx = start_x + horizonta_len - main_w - 1 * s
            _draw_bold_text(draw, (rx, y_pos), main_txt, font14, s)

            # Secondary: L10 and streak on the line below in font9
            stats = _team_stats(team_id)
            w10, l10 = stats.get('l10_wins'), stats.get('l10_losses')
            streak_val = stats.get('streak') or ''
            parts = []
            if w10 is not None and l10 is not None:
                parts.append(f'{w10}-{l10}')
            if streak_val:
                parts.append(streak_val)
            if parts:
                sub_txt = ' '.join(parts)
                sub_w = int(font11.getlength(sub_txt))
                sx = start_x + horizonta_len - sub_w - 1 * s
                draw.text((sx, y_pos + 15 * s), sub_txt, font=font11, fill=0)

        _away_wins  = game_data.get("away_team_record_wins", "0")
        _away_losses = game_data.get("away_team_record_losses", "0")
        _home_wins  = game_data.get("home_team_record_wins", "0")
        _home_losses = game_data.get("home_team_record_losses", "0")

        _is_ppd = game_data['detailed_state'] == 'Postponed'
        if not _is_lineup_mode or _is_ppd:
            _draw_record(_away_wins, _away_losses, game_data.get("away_team_id"), start_y + 25 * s)
            _draw_record(_home_wins, _home_losses, game_data.get("home_team_id"), start_y + 55 * s)

            # Betting moneylines — right-aligned just left of each team's record (not on postponed)
            _away_ml = game_data.get('away_ml')
            _home_ml = game_data.get('home_ml')
            if _away_ml is not None and _home_ml is not None and not _is_ppd:
                _away_rec_left = start_x + horizonta_len - int(font14.getlength(f'{_away_wins}-{_away_losses}')) - 5 * s
                _home_rec_left = start_x + horizonta_len - int(font14.getlength(f'{_home_wins}-{_home_losses}')) - 5 * s
                _odds_right = min(_away_rec_left, _home_rec_left) - 4 * s

                def _ml_str(v):
                    """Ml str."""
                    return f'+{v}' if v > 0 else str(v)

                _aml_s = _ml_str(_away_ml)
                _hml_s = _ml_str(_home_ml)
                _abbr_draw_y_away = start_y + 25 * s + ((28 * s - 14 * s) // 2 if use_logos else 0)
                _abbr_draw_y_home = start_y + 55 * s + ((28 * s - 14 * s) // 2 if use_logos else 0)
                _away_odds_y = _abbr_draw_y_away + 2 * s
                _home_odds_y = _abbr_draw_y_home + 2 * s
                _odds_x = _odds_right - max(int(font11.getlength(_aml_s)), int(font11.getlength(_hml_s)))
                draw.text((_odds_x, _away_odds_y), _aml_s, font=font11, fill=0)
                draw.text((_odds_x, _home_odds_y), _hml_s, font=font11, fill=0)

            _draw_weather_footer(draw, start_x, start_y, horizonta_len, game_data, font14, show_tv=not _is_ppd, scale=s)

    # Game duration + doubleheader labels — placement depends on whether the
    # header slot is already taken by SWEEP/WALKOFF.
    _draw_duration_and_dh_labels(
        ctx, game_data,
        game_is_final=_game_is_final, is_sweep=_is_sweep, is_walkoff=_is_walkoff,
        dh_is_active=_dh_is_active, dh_scheduled=_dh_scheduled, gnum=_gnum,
    )

    # End time — right-aligned in the strip below the box, beside the duration.
    _draw_game_end_time(ctx, _end_utc_str, _in_linescore_window, _game_is_final)

    # ABS challenges remaining — small stacked dots to the left of each team's logo
    if game_data['detailed_state'] == 'In Progress':
        _draw_challenge_dots(draw, start_x, start_y, game_data, use_logos=use_logos, logo_x_offset=logo_x_offset, scale=s)

    # top border + header separator
    end_x = start_x + horizonta_len
    end_y = start_y
    draw.line((start_x, start_y, end_x, start_y), fill=0)
    draw.line((start_x, start_y + 20 * s, end_x, end_y + 20 * s), fill=0)

    # Win probability bar — all In Progress states, including inning breaks.
    if show_win_prob and game_data['detailed_state'] == 'In Progress':
        _draw_win_probability_bar(
            ctx, game_data,
            away_team=(away_team_name, away_team_id),
            home_team=(home_team_name, home_team_id),
            center_line=win_prob_center_line,
        )
        draw = ctx.draw

    end_x = start_x + horizonta_len
    if not _is_lineup_mode:
        end_y = start_y + vertical_len + 20 * s
        draw.line((start_x, end_y, end_x, end_y), fill=0)

    # Next game preview — replaces the win-prob strip once a Final game's
    # linescore window expires, and immediately for a postponed game.
    # Guard on historical mode first: the expiry check calls
    # _get_or_set_final_time, which records a first-seen-Final timestamp, and a
    # replayed render must not write into that cache.
    _show_preview = False
    if not _historical_mode:
        if _game_is_final:
            _show_preview = _final_linescore_window_expired(game_data, _FINAL_LINESCORE_SECS)
        else:
            _show_preview = game_data['detailed_state'] == 'Postponed'
    if _show_preview:
        _tmrw = _load_tomorrow_games(game_data.get('game_date'))
        if _tmrw and _tmrw.get('games'):
            _draw_next_game_preview(
                draw, Himage, start_x, start_y, _tmrw['games'],
                game_data.get('home_team_id'), game_data.get('away_team_id'),
                team_data, use_logos, horizonta_len, vertical_len, s,
                left_offset=0,
            )


    # Show bases/outs/count only once the game is actually in progress (first pitch thrown).
    # force_linescore (wide-cell mode) suppresses this block — the right panel handles live context.
    _draw_live_situation_panel(
        ctx, game_data, team_data,
        between_innings=_between_innings, game_ending_state=_game_ending_state,
        pitching_change=_pitching_change, mid_inning_pc=_mid_inning_pc,
        force_linescore=force_linescore,
        ser_content_left_x=_ser_content_left_x)
    Himage, draw = ctx.Himage, ctx.draw




    # Team names / logos (skipped when lineup is shown in body)
    _LOGO_SIZE = 28 * s  # matches _logo_small default size
    if not _is_lineup_mode:
        if use_logos:
            away_logo = _logo_small(away_team_name, away_team_id, size=_LOGO_SIZE)
            home_logo = _logo_small(home_team_name, home_team_id, size=_LOGO_SIZE)
            if away_logo:
                lw, lh = away_logo.size
                lx = start_x + logo_x_offset + (_LOGO_SIZE - lw) // 2
                ly = start_y + 25 * s + (_LOGO_SIZE - lh) // 2
                _paste_logo(Himage, away_logo, (lx, ly))
                abbr_x = start_x + logo_x_offset + _LOGO_SIZE + 2 * s
                abbr_y = start_y + 25 * s + (_LOGO_SIZE - 14 * s) // 2
                _draw_bold_text(draw, (abbr_x, abbr_y), away_team_name, font14, s)
            else:
                draw.text((start_x + 5 * s, start_y + 25 * s), away_team_name, font=font24, fill=0)
            if home_logo:
                lw, lh = home_logo.size
                lx = start_x + logo_x_offset + (_LOGO_SIZE - lw) // 2
                ly = start_y + 55 * s + (_LOGO_SIZE - lh) // 2
                _paste_logo(Himage, home_logo, (lx, ly))
                abbr_x = start_x + logo_x_offset + _LOGO_SIZE + 2 * s
                abbr_y = start_y + 55 * s + (_LOGO_SIZE - 14 * s) // 2
                _draw_bold_text(draw, (abbr_x, abbr_y), home_team_name, font14, s)
            else:
                draw.text((start_x + 5 * s, start_y + 55 * s), home_team_name, font=font24, fill=0)
        else:
            draw.text((start_x + 5 * s, start_y + 25 * s), away_team_name, font=font24, fill=0)
            draw.text((start_x + 5 * s, start_y + 55 * s), home_team_name, font=font24, fill=0)
            # Bold-offset re-draw to emphasise winner name (text mode only)
            if game_data.get('away_team_is_winner'):
                draw.text((start_x + 7 * s, start_y + 25 * s), away_team_name, font=font24, fill=0)
            if game_data.get('home_team_is_winner'):
                draw.text((start_x + 7 * s, start_y + 55 * s), home_team_name, font=font24, fill=0)

    # Bold-offset score for winner (both modes) — only when the score itself
    # is shown; lineup mode replaces the score area with the batting order.
    if not _is_lineup_mode:
        if game_data.get('away_team_is_winner'):
            draw.text((start_x + 69 * s + check_if_two_chars(away_runs), start_y + 25 * s), away_runs, font=font24, fill=0)
        if game_data.get('home_team_is_winner'):
            draw.text((start_x + 69 * s + check_if_two_chars(home_runs), start_y + 55 * s), home_runs, font=font24, fill=0)

    # Invert header to indicate a score change or run-scoring play during an active game
    _run_scored = game_data['detailed_state'] == 'In Progress' and not is_game_finished and int(game_data.get('last_play_rbi') or 0) > 0
    if (score_changed or _run_scored) and is_game_started and not is_game_finished and not _between_innings and not _pitching_change and not skip_header_invert:
        _invert_region(Himage, start_x, start_y, start_x + horizonta_len + 1 * s, start_y + 21 * s)

    # Invert header for stolen base events
    _lp_lower = (game_data.get('last_play') or '').lower()
    _sb_event = (
        game_data['detailed_state'] == 'In Progress' and not is_game_finished and not _between_innings and not _pitching_change and
        ('stolen base' in _lp_lower or _lp_lower == 'sb')
    )
    if _sb_event and not skip_header_invert:
        _invert_region(Himage, start_x, start_y, start_x + horizonta_len + 1 * s, start_y + 21 * s)

    # Invert header for special states: no-hitter (>= 6 innings), perfect game
    if (game_data.get('no_hitter') or game_data.get('perfect_game')) and \
       (is_game_finished or _active_no_no) and not skip_header_invert:
        _invert_region(Himage, start_x, start_y, start_x + horizonta_len + 1 * s, start_y + 21 * s)

    return Himage


# ---------------------------------------------------------------------------
# Wide (2-cell) featured game box
# ---------------------------------------------------------------------------

_WIDE_PITCH_TYPE = {
    'FF': 'FB', 'FA': 'FB', 'FT': '2F', 'SI': 'SI',
    'FC': 'CT', 'SL': 'SL', 'ST': 'SW', 'SW': 'SW',
    'CH': 'CH', 'CU': 'CB', 'CS': 'CB', 'KC': 'KC',
    'FS': 'SP', 'KN': 'KN', 'EP': 'EP',
}

# Strike zone coordinate bounds (MLB standard)
_SZ_HALF_W = 0.708  # ±0.708 ft = 17-inch plate
_SZ_PZ_LO  = 1.5
_SZ_PZ_HI  = 3.5


def _draw_wide_pregame_lineups(draw, Himage, rp_x, rp_y, rp_w, rp_h, header_h, game_data, scale=1):
    """Fill the wide right panel body with both teams' batting lineups for pre-game tiles.

    Layout: two columns split at the midpoint.
    Left = away team, Right = home team.
    Team abbr header row, then up to 9 player rows (slot + last name + pos).
    Falls back to a centered 'Lineups TBD' message when neither lineup is posted.
    """
    from image_utils import _last_name as _ln
    s = scale
    font_team = _get_font(10 * s)
    font_row  = _get_font(9 * s)

    body_y = rp_y + header_h
    body_h = rp_h - header_h
    col_w  = rp_w // 2
    mid_x  = rp_x + col_w

    away_lineup = game_data.get('away_lineup') or []
    home_lineup = game_data.get('home_lineup') or []

    if not away_lineup and not home_lineup:
        msg = 'Lineups TBD'
        mw  = int(font_row.getlength(msg))
        mx  = rp_x + (rp_w - mw) // 2
        my  = body_y + (body_h - 9 * s) // 2
        draw.text((mx, my), msg, font=font_row, fill=0)
        return

    # Vertical divider between columns
    draw.line([(mid_x, body_y), (mid_x, rp_y + rp_h - 1)], fill=0)

    def _render_col(lineup, col_x, label):
        lw = int(font_team.getlength(label))
        lx = col_x + (col_w - lw) // 2
        draw.text((lx,     body_y + 1 * s), label, font=font_team, fill=0)
        draw.text((lx + 1, body_y + 1 * s), label, font=font_team, fill=0)

        avail_h = body_h - 11 * s
        n = min(len(lineup), 9)
        row_h = avail_h // max(n, 1)
        pad = 2

        for i, entry in enumerate(lineup[:9]):
            ry  = body_y + 11 * s + i * row_h
            slot_str = f'{i + 1}.'
            name = _ln(entry.get('name', ''))
            pos  = entry.get('pos', '')

            sw = int(font_row.getlength(slot_str))
            draw.text((col_x + pad, ry), slot_str, font=font_row, fill=0)

            pw  = int(font_row.getlength(pos))
            px2 = col_x + col_w - pw - pad - 1
            draw.text((px2, ry), pos, font=font_row, fill=0)

            name_x = col_x + pad + sw + 2
            max_nw  = px2 - 2 - name_x
            while name and int(font_row.getlength(name)) > max_nw:
                name = name[:-1]
            draw.text((name_x, ry), name, font=font_row, fill=0)

    away_name = (game_data.get('away_team_name') or 'Away')
    home_name = (game_data.get('home_team_name') or 'Home')
    # Use the last word of the team name (e.g. "Yankees") as the column header
    away_label = away_name.split()[-1] if away_name else 'Away'
    home_label = home_name.split()[-1] if home_name else 'Home'
    # Truncate if too wide for the column
    for lbl_font in (font_team,):
        while away_label and int(lbl_font.getlength(away_label)) > col_w - 4:
            away_label = away_label[:-1]
        while home_label and int(lbl_font.getlength(home_label)) > col_w - 4:
            home_label = home_label[:-1]

    _render_col(away_lineup, rp_x,  away_label)
    _render_col(home_lineup, mid_x, home_label)


def _draw_wide_right_panel(draw, Himage, rp_x, rp_y, rp_w, rp_h, header_h, game_data, team_data, use_logos=False, scale=1):
    """Right panel of 2-cell wide tile.

    Header strip (20 px): last half-inning event (cycling 8-sec) + count right-aligned.
    Active at-bat content:
      Left strip  (x+0 .. x+~32):  pitch list vertically from top (1-FB, 2-SL …)
      Middle      (x+42 .. x+88):  bases (shifted right) + outs
      Right       (x+90 .. x+148): strike zone (location-based fill)
      Lower rows: P: pitcher | AB: batter (same font) | B/S indicators
    Between-innings content: next 3 batters (outs hidden).
    Bottom strip (below rp_h): K strikeouts for each pitcher.
    """
    s = scale
    font11 = _get_font(11 * s)   # base-runner numbers
    font9  = _get_font(9 * s)
    font7  = _get_font(max(7 * s, 7))

    state = game_data.get('detailed_state', '')
    _between_innings = game_data.get('inningState') in ('Middle', 'End')
    _rp_flags = _compute_layout_flags(game_data)
    _mid_inning_pc = _rp_flags.mid_inning_pc
    _game_ending_state = _rp_flags.game_ending_state

    # ── Header: last 5 game events + count ─────────────────────────────
    # Events render in the same size as the single-cell last-play text (font12),
    # bold, on the inning's baseline, spanning the full two-cell width (the left
    # cell no longer draws its own event).
    font14 = _get_font(14 * s)   # inning label size, used to reserve its width
    font12 = _get_font(12 * s)   # event text size (matches 1-cell last-play)
    balls   = min(game_data.get('balls', 0) or 0, 3)
    min(game_data.get('strikes', 0) or 0, 2)

    # The ball-strike count lives in the panel body (B/S rows); no count in the header.
    _cnt_w = 0

    # Reserve space for the inning label drawn in the left cell ("Top 7", "Bot 12"…).
    _tile_left = rp_x - 135 * s
    _inn_state = game_data.get('inningState') or ''
    _inn_label = {'Top': 'Top', 'Bottom': 'Bot', 'Middle': 'Mid', 'End': 'End'}.get(
        _inn_state, (_inn_state[:3] or ''))
    _inn_text = 'End of Game' if (_game_ending_state and _between_innings) \
        else f"{_inn_label} {game_data.get('current_inning') or 1}".strip()
    _inn_w = int(font14.getlength(_inn_text)) + 2 * s   # +2 for the inning's bold strike

    half_inning_plays = game_data.get('half_inning_plays') or []
    # Keep the last 7 *events* plus intervening half-inning markers ('^'/'v').
    # A plain [-7:] would count markers as entries and show fewer than 7 events.
    _recent_plays = []
    _rp_events = 0
    for _tok in reversed(half_inning_plays):
        _recent_plays.append(_tok)
        if _tok not in ('^', 'v'):
            _rp_events += 1
            if _rp_events >= 7:
                break
    _recent_plays.reverse()
    # Right-anchor against the count; left bound clears the inning label.
    _hdr_left = _tile_left + 2 * s + _inn_w + 6 * s
    _hdr_right = rp_x + rp_w - _cnt_w - (7 * s if _cnt_w else 3 * s)
    _hdr_max_w = _hdr_right - _hdr_left - 1 * s   # -1 for the bold double-strike

    # Inning-break triangle: '^' heading into the top half, 'v' into the bottom.
    _TRI_W = 7 * s
    _TRI_H = 7 * s

    def _draw_triangle(x, y, direction):
        """Draw a small filled up/down triangle, vertically aligned with the text."""
        top = y + 2 * s + 2
        bot = top + _TRI_H
        cx = x + _TRI_W / 2
        if direction == 'up':
            pts = [(cx, top), (x, bot), (x + _TRI_W, bot)]
        else:
            pts = [(x, top), (x + _TRI_W, top), (cx, bot)]
        draw.polygon(pts, fill=0)

    def _build_items(plays):
        """Turn play tokens into render segments: ('text', str) | ('tri', 'up'|'dn').

        '^'/'v' tokens become triangle inning-break separators; consecutive
        events in the same half-inning are joined with ' | '.
        A trailing '^'/'v' with no following event is emitted as a lone arrow
        so the display shows which half-inning is now active.
        """
        items = []
        pending = None   # None | 'bar' | 'up' | 'dn'
        for ev in plays:
            if ev == '^':
                pending = 'up'
            elif ev == 'v':
                pending = 'dn'
            else:
                if pending == 'bar':
                    items.append(('text', ' | '))
                elif pending in ('up', 'dn'):
                    items.append(('text', ' '))
                    items.append(('tri', pending))
                    items.append(('text', ' '))
                items.append(('text', str(ev)))
                pending = 'bar'
        if pending in ('up', 'dn'):
            if items:
                items.append(('text', ' '))
            items.append(('tri', pending))
        return items

    def _measure_items(items):
        """Measure items."""
        total = 0
        for kind, val in items:
            if kind == 'tri':
                total += int(_TRI_W)
            else:
                total += int(font12.getlength(val.replace('Kl', 'K')))
        return total

    def _draw_text_seg(x, y, seg):
        """Draw one text segment (bold double-strike, backwards-K aware); return new x."""
        if 'Kl' not in seg:
            _draw_bold_text(draw, (x, y), seg, font12, s)
            return x + int(font12.getlength(seg))
        _parts = seg.split('Kl')
        for _bx in (x, x + 1 * s):
            _cx = _bx
            for _i, _p in enumerate(_parts):
                if _p:
                    draw.text((_cx, y), _p, font=font12, fill=0)
                    _cx += int(font12.getlength(_p))
                if _i < len(_parts) - 1:
                    _draw_backwards_k(Himage, _cx, y, font12)
                    _cx += int(font12.getlength('K'))
        return x + int(font12.getlength(seg.replace('Kl', 'K')))

    def _draw_items(x, y, items):
        """Draw items."""
        cx = x
        for kind, val in items:
            if kind == 'tri':
                _draw_triangle(cx, y, 'up' if val == 'up' else 'dn')
                cx += int(_TRI_W)
            else:
                cx = _draw_text_seg(cx, y, val)

    # Show up to the last 7 events; drop oldest (leftmost) until it fits so the
    # most recent events always stay visible.
    _hdr_items = []
    while _recent_plays:
        _hdr_items = _build_items(_recent_plays)
        if _measure_items(_hdr_items) <= _hdr_max_w:
            break
        _recent_plays.pop(0)
        # Don't leave a lone triangle boundary marker at the front
        while _recent_plays and _recent_plays[0] in ('^', 'v'):
            _recent_plays.pop(0)
    if _recent_plays and _hdr_items:
        _tx = max(_hdr_left, _hdr_right - _measure_items(_hdr_items))
        _draw_items(_tx, rp_y + 4 * s, _hdr_items)

    if state in ('Scheduled', 'Pre-Game', 'Warmup'):
        _draw_wide_pregame_lineups(draw, Himage, rp_x, rp_y, rp_w, rp_h, header_h, game_data, scale)
        return

    if state != 'In Progress':
        return

    if _between_innings and _game_ending_state:
        return Himage

    ab_pitches = game_data.get('ab_pitches') or []

    # ── Strike zone bounds: use per-batter sz from pitch data ──────────
    _zone_top = _SZ_PZ_HI
    _zone_bot = _SZ_PZ_LO
    for _p in ab_pitches:
        _st = _p.get('sz_top')
        _sb = _p.get('sz_bot')
        if _st is not None and _sb is not None:
            _zone_top = float(_st)
            _zone_bot = float(_sb)
            break

    # ── Strike zone (RIGHT side, fixed pixel dimensions) ───────────────
    ZONE_W = 56 * s
    ZONE_H = 58 * s
    zone_rx = rp_x + rp_w - 17 * s   # nudged left 7px more to leave room for outside pitches
    zone_lx = zone_rx - ZONE_W
    zone_ty = rp_y + header_h + 12 * s   # nudged down
    zone_by = zone_ty + ZONE_H

    if not _between_innings:
        draw.rectangle([zone_lx, zone_ty, zone_rx, zone_by], outline=0)
        tw = ZONE_W // 3
        th = ZONE_H // 3
        draw.line([zone_lx + tw,     zone_ty, zone_lx + tw,     zone_by], fill=0)
        draw.line([zone_lx + 2 * tw, zone_ty, zone_lx + 2 * tw, zone_by], fill=0)
        draw.line([zone_lx, zone_ty + th,     zone_rx, zone_ty + th    ], fill=0)
        draw.line([zone_lx, zone_ty + 2 * th, zone_rx, zone_ty + 2 * th], fill=0)

        # Called balls (incl. intentional 'I', pitchout 'P', automatic ball 'V')
        # are highlighted/filled; everything else (strikes, fouls, in-play) is outlined.
        _BALL_CODES = frozenset({'B', 'I', 'P', 'V'})

        def _to_pixel(px_c, pz_c):
            """To pixel."""
            tx = zone_lx + (px_c + _SZ_HALF_W) / (2 * _SZ_HALF_W) * ZONE_W
            ty = zone_by  - (pz_c - _zone_bot)  / (_zone_top - _zone_bot)  * ZONE_H
            return int(tx), int(ty)

        # Pitch circles: invert only strikes that are in the zone
        PITCH_R = max(5 * s, 5)
        # Pitches well outside the strike zone must still render — pinned just
        # outside the drawn box — rather than bleeding past the panel into
        # whatever's drawn next to this tile (the neighboring game's cell).
        _pitch_min_x = zone_lx - 20 * s
        _pitch_max_x = rp_x + rp_w - PITCH_R - 2 * s
        _pitch_min_y = rp_y + header_h + PITCH_R + 2 * s
        _pitch_max_y = rp_y + rp_h - PITCH_R - 2 * s
        for pitch_num, pitch in enumerate(ab_pitches, start=1):
            px_c, pz_c = pitch.get('px'), pitch.get('pz')
            if px_c is None or pz_c is None:
                continue
            bx, by = _to_pixel(px_c, pz_c)
            bx = max(_pitch_min_x, min(_pitch_max_x, bx))
            by = max(_pitch_min_y, min(_pitch_max_y, by))
            # Prefer the result/call code; fall back to 'code' for callers that
            # supply the call code there directly.
            _code = (pitch.get('call') or pitch.get('code') or '').upper()
            # Highlight (fill) called balls; strikes / fouls / contact are outlines.
            filled = _code in _BALL_CODES
            box = [bx - PITCH_R, by - PITCH_R, bx + PITCH_R, by + PITCH_R]
            seq_str = str(pitch_num)
            _sb = font7.getbbox(seq_str)
            _tx = bx - (_sb[0] + _sb[2]) // 2 + 1
            _ty = by - (_sb[1] + _sb[3]) // 2
            if filled:
                draw.ellipse(box, fill=0, outline=0)
                draw.text((_tx, _ty), seq_str, font=font7, fill=255)
            else:
                draw.ellipse(box, fill=255, outline=0)
                draw.text((_tx, _ty), seq_str, font=font7, fill=0)

        # ── Bases: left side of panel ──────────────────────────────────
        _outs_count = game_data.get('num_of_outs') or 0
        if _outs_count < 3:
            _hi_third  = isinstance(game_data.get('runner_on_third'), str)
            _hi_second = isinstance(game_data.get('runner_on_second'), str)
            _hi_first  = isinstance(game_data.get('runner_on_first'), str)
            _b3x, _b3y = rp_x + 18 * s, rp_y + 52 * s
            _b2x, _b2y = rp_x + 30 * s, rp_y + 40 * s
            _b1x, _b1y = rp_x + 42 * s, rp_y + 52 * s
            Himage = draw_diamond(Himage, (_b3x, _b3y), 9 * s, _hi_third)
            Himage = draw_diamond(Himage, (_b2x, _b2y), 9 * s, _hi_second)
            Himage = draw_diamond(Himage, (_b1x, _b1y), 9 * s, _hi_first)
            draw = ImageDraw.Draw(Himage)
            for _bfill, _bcx, _bcy, _bkey in (
                (_hi_third,  _b3x, _b3y, 'runner_third_number'),
                (_hi_second, _b2x, _b2y, 'runner_second_number'),
                (_hi_first,  _b1x, _b1y, 'runner_first_number'),
            ):
                if _bfill:
                    _raw = game_data.get(_bkey)
                    _bnum = str(_raw) if _raw is not None else ''
                    if _bnum:
                        _bb = font11.getbbox(_bnum)
                        draw.text((_bcx - (_bb[0] + _bb[2] - 1) // 2, _bcy - (_bb[1] + _bb[3] - 1) // 2), _bnum, font=font11, fill=255)

        # ── Outs circles: left side, below bases ──────────────────────
        outs_list = [i + 1 <= _outs_count for i in range(3)]
        _outs_x = [rp_x + 18 * s, rp_x + 32 * s, rp_x + 46 * s]
        _outs_y = rp_y + 71 * s
        Himage = draw_circle(Himage, (_outs_x[0], _outs_y), 6 * s, outs_list[0], outline_width=2)
        Himage = draw_circle(Himage, (_outs_x[1], _outs_y), 6 * s, outs_list[1], outline_width=2)
        Himage = draw_circle(Himage, (_outs_x[2], _outs_y), 6 * s, outs_list[2], outline_width=2)
        draw = ImageDraw.Draw(Himage)

        # Play-type label under each recorded out this half-inning (e.g. 'K', 'F8').
        # Only outs the batter makes at the plate are labelled — base-running
        # outs (caught stealing, pickoffs) aren't tracked here.
        _outs_labels = game_data.get('outs_this_half') or []
        _ol_max_w = 12 * s
        for _oi, _olabel in enumerate(_outs_labels[:3]):
            if not (outs_list[_oi] and _olabel):
                continue
            _ol_str = _olabel
            while _ol_str and int(font7.getlength(_ol_str)) > _ol_max_w:
                _ol_str = _ol_str[:-1]
            if not _ol_str:  # pragma: no cover
                continue
            _ol_w = int(font7.getlength(_ol_str))
            draw.text((_outs_x[_oi] - _ol_w / 2, _outs_y + 7 * s), _ol_str, font=font7, fill=0)

        # ── Pitch list: vertical, right of bases/outs, left of zone ───
        # Anchored to a fixed top (not the zone) so moving the zone down doesn't
        # shrink the list — keeps room to show more of the at-bat's pitches.
        _pt_x = rp_x + 56 * s   # nudged 3px right
        _pt_max_w = zone_lx - _pt_x - 2 * s
        _pt_step = 9 * s
        _pt_top = rp_y + header_h + 2 * s
        for _pn, _pp in enumerate(ab_pitches, start=1):
            _ey = _pt_top + (_pn - 1) * _pt_step
            if _ey + _pt_step > rp_y + rp_h - 37 * s:
                break
            _abbr = _pp.get('pt_abbr') or _WIDE_PITCH_TYPE.get(_pp.get('code', ''), _pp.get('code', ''))
            _label = f'{_pn}-{_abbr}' if _abbr else str(_pn)
            _lw = int(font7.getlength(_label))
            if _lw > _pt_max_w:
                _label = _label[:4]
            draw.text((int(_pt_x), int(_ey)), _label, font=font7, fill=0)

        # ── Strikes / Balls indicators ─────────────────────────────────
        balls_list = [i + 1 <= balls for i in range(3)]
        _num_strikes = min(game_data.get('strikes') or 0, 2)
        strikes_list = [i + 1 <= _num_strikes for i in range(2)]
        _strike_calls = game_data.get('strike_calls') or []

        # Centre each label glyph with its circle row
        _bs_lbl_bbox = font11.getbbox('B')
        _bs_lbl_cy   = (_bs_lbl_bbox[1] + _bs_lbl_bbox[3]) // 2

        # Strikes row (above balls)
        _s_circ_y = rp_y + 91 * s
        draw.text((rp_x + 5 * s, _s_circ_y - _bs_lbl_cy), 'S', font=font11, fill=0)
        for _si, (_scx, _scy) in enumerate([
            (rp_x + 22 * s, _s_circ_y),
            (rp_x + 34 * s, _s_circ_y),
        ]):
            _call = _strike_calls[_si] if _si < len(_strike_calls) else None
            if strikes_list[_si] and _call in ('S', 'F'):
                _ir = max(4 * s - 2, 2)
                Himage = draw_circle(Himage, (_scx, _scy), 4 * s, False)
                draw = ImageDraw.Draw(Himage)
                draw.ellipse([_scx - _ir, _scy - _ir, _scx + _ir, _scy + _ir], fill='black', outline='black')
            else:
                Himage = draw_circle(Himage, (_scx, _scy), 4 * s, strikes_list[_si])
                draw = ImageDraw.Draw(Himage)

        # Balls row (below strikes)
        _b_circ_y = rp_y + 102 * s
        draw.text((rp_x + 5 * s, _b_circ_y - _bs_lbl_cy), 'B', font=font11, fill=0)
        Himage = draw_circle(Himage, (rp_x + 22 * s, _b_circ_y), 4 * s, balls_list[0])
        Himage = draw_circle(Himage, (rp_x + 34 * s, _b_circ_y), 4 * s, balls_list[1])
        Himage = draw_circle(Himage, (rp_x + 46 * s, _b_circ_y), 4 * s, balls_list[2])
        draw = ImageDraw.Draw(Himage)

    else:
        # ── Between innings: next 3 batters, outs hidden ───────────────
        _batter_names = [
            _last_name(game_data.get('next_batter_1') or game_data.get('current_hitter') or ''),
            _last_name(game_data.get('next_batter_2') or game_data.get('due_up') or ''),
            _last_name(game_data.get('next_batter_3') or game_data.get('in_hole') or ''),
        ]
        _bat_y = rp_y + header_h + 10 * s
        _bat_max_w = rp_w - 4 * s - 3
        for _nm in _batter_names:
            if _nm:
                _bat_str = _nm
                while _bat_str and int(font11.getlength(_bat_str)) > _bat_max_w:
                    _bat_str = _bat_str[:-1]
                if _bat_str:
                    _draw_bold_text(draw, (rp_x + 2 * s + 3, _bat_y), _bat_str, font11, s)
            _bat_y += 16 * s

    # ── Pitcher row (pushed below B/S indicators) ──────────────────────
    _py = rp_y + 107 * s
    _max_w = rp_w - 7 * s
    _pc = game_data.get('pitch_count')
    _ab_pc = game_data.get('at_bat_pitch_count') or 0
    _pt_last = game_data.get('last_pitch_type', '') or ''
    _lps = game_data.get('last_pitch_speed')
    # Mid-inning change: name both ends of it ("P: Warren→King"). current_pitcher
    # still reports the departing arm until the API catches up.
    _pc_incoming = (game_data.get('sub_event') or '')[3:].strip() if _mid_inning_pc else ''
    if _pc_incoming:
        _outgoing = _last_name(game_data.get('current_pitcher') or '')
        _pitcher_name = f'{_outgoing}→{_pc_incoming}' if _outgoing else _pc_incoming
    else:
        _pitcher_name = _format_player_name(game_data.get('current_pitcher') or '')
        _pitch_hand = game_data.get('pitch_hand', '')
        if _pitcher_name and _pitch_hand:
            _pitcher_name = f'{_pitcher_name} ({_pitch_hand})'

    # Game-level pitch count when available (live); fall back to per-at-bat count
    # for timelapse frames where only at_bat_pitch_count is reconstructed.
    _pc_badge = f'{_pc}P' if _pc is not None else (f'AB{_ab_pc}' if _ab_pc else '')
    _rb_parts = [p for p in [
        _pt_last,
        str(int(_lps)) if _lps else '',
        _pc_badge,
    ] if p]
    _right_badge = ' '.join(_rb_parts)
    _rb_w = int(font9.getlength(_right_badge)) + 2 * s if _right_badge else 0
    _pit_avail = _max_w - _rb_w
    _pit_str = f'P: {_pitcher_name}'
    _pf = font11
    if int(_pf.getlength(_pit_str)) > _pit_avail:
        _pf = font9
        while _pit_str and int(font9.getlength(_pit_str)) > _pit_avail:
            _pit_str = _pit_str[:-1]
    _draw_bold_text(draw, (rp_x + 5 * s, _py), _pit_str, _pf, s)
    if _right_badge:
        draw.text((rp_x + rp_w - _rb_w, _py), _right_badge, font=font9, fill=0)

    # ── Batter row (hidden between innings — no one is at bat, and the
    #    linescore's current-batter fields go stale during the break) ────
    if not _between_innings:
        _by = rp_y + 117 * s
        _bh = game_data.get('batter_hits')
        _ba = game_data.get('batter_at_bats')
        _ba_str = f'{_bh}-{_ba}' if _bh is not None and _ba is not None else ''
        _ba_w = int(font9.getlength(_ba_str)) + 2 * s if _ba_str else 0
        _hit_avail = _max_w - _ba_w
        _ab_done = game_data.get('current_at_bat_complete', False)
        if _ab_done and not _is_game_effectively_over(game_data):
            _next = _format_player_name(game_data.get('due_up') or game_data.get('next_batter_1') or '')
            _batter_label = f'AB: {_next}' if _next else ''
        else:
            _hitter = _format_player_name(
                game_data.get('current_play_batter') or game_data.get('current_hitter') or ''
            )
            _bat_side = game_data.get('bat_side', '')
            _side_suffix = f' ({_bat_side})' if _hitter and _bat_side else ''
            _batter_label = f'AB: {_hitter}{_side_suffix}'
        if _batter_label:
            _bf = font11
            if int(_bf.getlength(_batter_label)) > _hit_avail:
                _bf = font9
                while _batter_label and int(font9.getlength(_batter_label)) > _hit_avail:
                    _batter_label = _batter_label[:-1]
            draw.text((rp_x + 5 * s, _by), _batter_label, font=_bf, fill=0)
        if _ba_str:
            draw.text((rp_x + rp_w - _ba_w, _by), _ba_str, font=font9, fill=0)

    # ── K strikeouts: current pitcher only, full width — hide between innings ─
    if _between_innings:
        return Himage
    # Top half → home team pitching; Bottom half → away team pitching
    _inning_state = game_data.get('inningState', '')
    if _inning_state in ('Top', 'Middle'):
        _pitcher_ks = game_data.get('home_pitcher_ks') or []
    else:
        _pitcher_ks = game_data.get('away_pitcher_ks') or []
    if not _pitcher_ks:
        return Himage
    # Every 10 Ks compress to a milestone badge ("10K", "20K", …); the leftover
    # 0–9 Ks are shown individually after the badge, preserving K/L distinction.
    _total_ks = len(_pitcher_ks)
    _milestone = (_total_ks // 10) * 10
    _milestone_label = f'{_milestone}K' if _milestone else ''
    _rem_ks = _pitcher_ks[_milestone:]

    # Bold via a 1px horizontal double-strike. Shrink the font until everything
    # — badge + individual Ks — fits across the strip on one line.
    _k_gap = max(2 * s, 2)
    _k_avail = rp_w - 4 * s

    def _strip_width(f):
        """Strip width."""
        bb = f.getbbox('K')
        k_adv = (bb[2] - bb[0]) + 3
        parts = ([int(f.getlength(_milestone_label)) + 3] if _milestone_label else []) + \
                [k_adv] * len(_rem_ks)
        if not parts:  # pragma: no cover
            return 0
        return sum(parts) + _k_gap * (len(parts) - 1)

    _k_font = None
    _k_bbox = None
    for _px in range(18, 6, -1):
        _f = _get_font(_px * s)
        if _strip_width(_f) <= _k_avail:
            _k_font, _k_bbox = _f, _f.getbbox('K')
            break
    if _k_font is None:  # pragma: no cover
        _k_font = _get_font(7 * s)
        _k_bbox = _k_font.getbbox('K')

    _k_glyph_h = _k_bbox[3] - _k_bbox[1]
    _k_tmp_w = max(_k_bbox[2] - _k_bbox[0] + 3, 4)
    _k_tmp_h = max(_k_glyph_h + 3, 4)
    # Center the glyphs vertically in the 20px gap below the tile border.
    _k_strip_y = rp_y + rp_h + (20 * s - _k_glyph_h) // 2 - 1 * s
    # Individual Ks sit 1px lower than a plain baseline within their temp
    # tile (see _k_top below) — the milestone badge must use the same
    # vertical offset so "10K" lands on the same plane as the loose Ks.
    _k_top = 2
    _k_x = rp_x + 2 * s

    # Draw milestone badge ("10K", "20K", …)
    if _milestone_label:
        _bl_y = _k_strip_y + _k_top - _k_bbox[1]
        _draw_bold_text(draw, (_k_x, _bl_y), _milestone_label, _k_font, s)
        _k_x += int(_k_font.getlength(_milestone_label)) + 3
        if _rem_ks:
            _k_x += _k_gap

    # Draw remaining individual Ks
    _k_spacing = _k_tmp_w + _k_gap
    for _k in _rem_ks:
        if _k_x + _k_tmp_w > rp_x + rp_w - 2:  # pragma: no cover
            break
        _k_tmp = Image.new('1', (_k_tmp_w, _k_tmp_h), 1)
        _ktd = ImageDraw.Draw(_k_tmp)
        _ktd.text((1 - _k_bbox[0], _k_top - _k_bbox[1]), 'K', font=_k_font, fill=0)
        _ktd.text((2 - _k_bbox[0], _k_top - _k_bbox[1]), 'K', font=_k_font, fill=0)  # bold strike
        if _k == 'L':
            _k_tmp = _k_tmp.transpose(Image.FLIP_LEFT_RIGHT)
        Himage.paste(_k_tmp, (int(_k_x), int(_k_strip_y)))
        draw = ImageDraw.Draw(Himage)
        _k_x += _k_spacing


def draw_wide_box(Himage, start_x, start_y, game_data, team_data,
                  score_changed=False, use_logos=False, logo_x_offset=2,
                  show_win_prob=False, streak_map=None, scale=1):
    """Featured 2-cell (285×130 px) game tile.

    Left panel (135 px): standard draw_box content with linescore always
    visible and hits shown even in-progress. Win probability bar shown when
    show_win_prob=True (same as single cells).
    Right panel (150 px): pitch list (vertical left), strike zone (right),
    bases/outs/count, pitcher/batter rows, K strip below.
    """
    s = scale
    CELL_W  = 135 * s   # left panel — same as normal cell width
    RIGHT_W = 150 * s   # right panel
    TOTAL_W = CELL_W + RIGHT_W  # 285 px
    HEADER_H = 20 * s
    TOTAL_H  = 130 * s

    # Left panel via draw_box: force linescore + always show hits
    Himage = draw_box(
        Himage, start_x, start_y, game_data, team_data,
        score_changed=score_changed,
        use_logos=use_logos,
        logo_x_offset=logo_x_offset,
        show_win_prob=show_win_prob,
        streak_map=streak_map,
        show_winner_logo=True,
        scale=scale,
        force_linescore=True,
        always_show_hits=True,
        hide_last_play=True,
        skip_header_invert=True,   # the wide cell inverts the full header itself
        # No centre rule: the bar can't extend past the left cell (the K strip
        # owns the rest of this gap), and a rule ending mid-tile reads as a
        # stray line rather than a bar.
        win_prob_center_line=False,
    )

    # Extend top, header-separator, and bottom borders across the right panel (no center divider)
    draw = ImageDraw.Draw(Himage)
    rp_x = start_x + CELL_W
    rp_right = start_x + TOTAL_W
    draw.line((rp_x, start_y,            rp_right, start_y),            fill=0)  # top
    draw.line((rp_x, start_y + HEADER_H, rp_right, start_y + HEADER_H), fill=0)  # header sep
    draw.line((rp_x, start_y + TOTAL_H,  rp_right, start_y + TOTAL_H),  fill=0)  # bottom

    # Right panel content
    _draw_wide_right_panel(
        draw, Himage,
        rp_x=rp_x, rp_y=start_y,
        rp_w=RIGHT_W, rp_h=TOTAL_H,
        header_h=HEADER_H,
        game_data=game_data,
        team_data=team_data,
        use_logos=use_logos,
        scale=scale,
    )

    # Invert the whole two-cell header when a run scores (or the score changed),
    # spanning both cells — mirrors the single-cell run-scored header flash.
    _between = game_data.get('inningState') in ('Middle', 'End')
    _run_scored = (
        game_data.get('detailed_state') == 'In Progress'
        and int(game_data.get('last_play_rbi') or 0) > 0
    )
    if (score_changed or _run_scored) and not _between:
        _invert_region(Himage, start_x, start_y, start_x + TOTAL_W, start_y + HEADER_H)
        draw = ImageDraw.Draw(Himage)

    # No-hitter / perfect game: invert the spanning header (same as single-cell).
    # Only fires when the run-scored inversion hasn't already fired (double-invert = no-op).
    _wide_is_final = game_data.get('detailed_state') in ('Final', 'Game Over', 'Final: Tied')
    _wide_active_no_no = (
        game_data.get('detailed_state') == 'In Progress' and
        (game_data.get('no_hitter') or game_data.get('perfect_game')) and
        (game_data.get('current_inning') or 0) >= 6
    )
    if (game_data.get('no_hitter') or game_data.get('perfect_game')) and \
       (_wide_is_final or _wide_active_no_no) and \
       not (score_changed or _run_scored):
        _invert_region(Himage, start_x, start_y, start_x + TOTAL_W, start_y + HEADER_H)

    return Himage


# MLBAM hit-coordinate → field-feet transform. These constants MUST match the
# ones used to build the wall/infield polygons in data/mlbam_walls.json and
# data/mlbam_infield.json (see src/extract_infield_polygons.py) — otherwise
# batted balls are plotted in a different coordinate system than the fence they
# are drawn against, and every ball lands short of where it really was.
_HC_SCALE    = 2.495671   # ft per hc unit
_HC_X_CENTER = 125.0
_HC_Y_CENTER = 199.0


def _hit_coord_to_feet(cx, cy):
    """Convert MLBAM hit coordinates (coordX, coordY) to field feet.

    Home plate at (0, 0); +x toward RF, +y toward CF.
    """
    return (_HC_SCALE * (cx - _HC_X_CENTER),
            _HC_SCALE * (_HC_Y_CENTER - cy))


# Generic outfield wall used when venue is unknown (symmetric 330-400-330 park).
_FIELD_FALLBACK_POLY = [
    (-233.3,  233.3),
    (-127.3,  307.3),
    (   0.0,  400.0),
    ( 127.3,  307.3),
    ( 233.3,  233.3),
]


def _draw_field_cell(draw, Himage, fx, fy, fw, fh, game_data, scale=1, y_offset=0, vis_h=None):
    """Draw compact field diagram in a 150×130 px tile cell.

    Draws the venue outfield wall with 5 fence distance markers, the infield
    diamond with mound and home plate, fills occupied bases, and plots the
    last batted ball in play (circle=hit, X=out, HR gets a trajectory line)
    when last_hit_x/last_hit_y are present in game_data.

    vis_h: visible tile height in unscaled pixels.  When provided, home plate
    is positioned so the field (CF wall line to home plate tip) is centred
    within [fy, fy + vis_h*s] with at least 3 px of white space above the
    outfield wall and below the home plate pentagon.  For parks whose field
    is taller than the tile (e.g. Comerica at 427 ft), the top margin is
    preserved and home plate extends into the fh drawing gap below the tile.

    y_offset (legacy): shifts the diagram up when vis_h is not supplied.
    """
    s = scale
    FSCALE = 0.30 * s
    HX = int(fx + 75 * s)

    venue     = game_data.get('venue', '')
    venue_id  = game_data.get('venue_id')
    wall_poly = _field_get_polygon(venue, venue_id) or _FIELD_FALLBACK_POLY
    infield_poly = (_field_get_infield_polygon(venue, venue_id)
                     or _field_get_infield_polygon('Yankee Stadium'))

    _cx0 = fx + 1
    _cx1 = fx + fw * s - 2
    _cy0 = fy + 1
    _cy1 = fy + fh * s - 2

    # Home plate pentagon half-width — needed for HY centering below.
    hp = max(round(3 * s), 3)

    if vis_h is not None:
        # Centre the field (CF arc → home plate bottom) in the visible tile.
        cf_y_ft   = max(y for _, y in wall_poly)
        tile_h_px = vis_h * s
        margin_px = round(3 * s)
        HY_ideal  = fy + (tile_h_px + cf_y_ft * FSCALE - hp) / 2
        HY_lo     = fy + margin_px + cf_y_ft * FSCALE  # 3 px above CF wall
        HY_hi     = fy + tile_h_px - margin_px - hp    # 3 px below home plate
        HY        = int(max(HY_lo, min(HY_hi, HY_ideal)))
    else:
        _bottom_extent_ft = max([-y for _, y in infield_poly] + [0]) if infield_poly else 0
        HY = int(min(fy + 126 * s, _cy1 - _bottom_extent_ft * FSCALE)) - round(y_offset * s)

    # Base positions (90ft diamond rotated 45°)
    _b = round(63.64 * FSCALE)   # 90 * cos45 ≈ 63.64 ft
    FIRST  = (HX + _b, HY - _b)
    SECOND = (HX,      HY - 2 * _b)
    THIRD  = (HX - _b, HY - _b)

    def _fpt(x_ft, y_ft):
        px = int(HX + x_ft * FSCALE)
        py = int(HY - y_ft * FSCALE)
        return (max(_cx0, min(_cx1, px)), max(_cy0, min(_cy1, py)))

    def _ray_end(x_ft, y_ft):
        """Pixel where the ray from home plate toward (x_ft, y_ft) exits the cell.

        _fpt() clips x and y independently, which misplaces the endpoint when
        the pole is outside the cell (e.g. 325ft RF pole at 0.28px/ft = 91px,
        but the cell is only ~73px wide from centre). Independent clipping
        produces an endpoint that is off the foul-line direction. This function
        instead finds the t at which the ray first hits a cell wall and uses
        that single t for both axes, keeping the direction correct.
        """
        dx = x_ft * FSCALE
        dy = -y_ft * FSCALE
        ts = []
        if dx > 0:  ts.append((_cx1 - HX) / dx)
        elif dx < 0: ts.append((_cx0 - HX) / dx)
        if dy > 0:  ts.append((_cy1 - HY) / dy)
        elif dy < 0: ts.append((_cy0 - HY) / dy)
        t = min((v for v in ts if v > 0), default=1.0)
        t = min(t, 1.0)
        px = round(HX + t * dx)
        py = round(HY + t * dy)
        return (max(_cx0, min(_cx1, px)), max(_cy0, min(_cy1, py)))

    wall_pts = [_fpt(x, y) for x, y in wall_poly]

    # Warning track: scale each wall point 10 ft closer to home
    for idx in range(len(wall_poly) - 1):
        x_ft, y_ft = wall_poly[idx]
        d  = _math.sqrt(x_ft**2 + y_ft**2)
        f  = max(d - 10, 40) / d if d > 0 else 1.0
        x2, y2 = wall_poly[idx + 1]
        d2 = _math.sqrt(x2**2 + y2**2)
        f2 = max(d2 - 10, 40) / d2 if d2 > 0 else 1.0
        draw.line([_fpt(x_ft * f, y_ft * f), _fpt(x2 * f2, y2 * f2)], fill=0, width=1)

    # Outfield fence
    for idx in range(len(wall_pts) - 1):
        draw.line([wall_pts[idx], wall_pts[idx + 1]], fill=0, width=1)

    # Infield dirt cutout: real per-park boundary when available (see
    # src/extract_infield_polygons.py). Yankee Stadium's shape is the
    # default for any venue without its own data; a hand-drawn arc is the
    # last-resort fallback if even that lookup somehow comes up empty.
    #
    # The polygon also traces the baseline sides (from the outfield arc down
    # toward home plate along the 1B/3B lines) and the home plate arc. We:
    #   - Draw the home plate arc unconditionally (min y < 5 ft behind plate)
    #   - Clip all other segments to fair territory via Liang-Barsky so that
    #     baseline-side segments are skipped and crossing segments don't bleed
    #     into foul territory (which would create a visual kink on the foul line).
    lf_x_ft, lf_y_ft = wall_poly[0]
    rf_x_ft, rf_y_ft = wall_poly[-1]

    def _rf_foul(x, y): return rf_x_ft * y - rf_y_ft * x < 0
    def _lf_foul(x, y): return lf_x_ft * y - lf_y_ft * x > 0

    def _clip_to_fair(x0, y0, x1, y1):
        """Liang-Barsky clip of foot-coord segment to fair territory.

        Returns (xa, ya, xb, yb) of the clipped portion, or None if the
        segment lies entirely in foul territory.
        """
        t0, t1 = 0.0, 1.0
        dx, dy = x1 - x0, y1 - y0
        # RF boundary: keep rf_x_ft*y - rf_y_ft*x >= 0
        c0 = rf_x_ft * y0 - rf_y_ft * x0
        c1 = rf_x_ft * y1 - rf_y_ft * x1
        if c0 < 0 and c1 < 0:  # pragma: no cover
            return None
        if c0 != c1:
            tc = c0 / (c0 - c1)
            if c0 < 0:
                t0 = max(t0, tc)
            elif c1 < 0:  # pragma: no cover
                t1 = min(t1, tc)
        # LF boundary: keep lf_x_ft*y - lf_y_ft*x <= 0
        c0 = lf_x_ft * y0 - lf_y_ft * x0
        c1 = lf_x_ft * y1 - lf_y_ft * x1
        if c0 > 0 and c1 > 0:  # pragma: no cover
            return None
        if c0 != c1:
            tc = c0 / (c0 - c1)
            if c0 > 0:  # pragma: no cover
                t0 = max(t0, tc)
            elif c1 > 0:  # pragma: no cover
                t1 = min(t1, tc)
        if t0 >= t1:  # pragma: no cover
            return None
        return (x0 + t0 * dx, y0 + t0 * dy, x0 + t1 * dx, y0 + t1 * dy)

    if infield_poly:
        for idx in range(len(infield_poly) - 1):
            x0, y0 = infield_poly[idx]
            x1, y1 = infield_poly[idx + 1]
            rf0, rf1 = _rf_foul(x0, y0), _rf_foul(x1, y1)
            lf0, lf1 = _lf_foul(x0, y0), _lf_foul(x1, y1)
            if min(y0, y1) < 5.0 or not (rf0 != rf1 or lf0 != lf1):
                # Home plate arc or segment entirely on one side of the foul
                # lines — draw in full. This preserves the complete D-shape
                # including the 1B/3B baseline sides (which are in foul
                # territory but are needed to show the full infield boundary).
                draw.line([_fpt(x0, y0), _fpt(x1, y1)], fill=0, width=1)
            else:
                # Segment crosses a foul line: clip to the fair-territory
                # portion only so stray pixels don't appear on the foul line.
                clipped = _clip_to_fair(x0, y0, x1, y1)
                if clipped is not None:
                    xa, ya, xb, yb = clipped
                    draw.line([_fpt(xa, ya), _fpt(xb, yb)], fill=0, width=1)
    else:  # pragma: no cover — infield_poly always falls back to Yankee Stadium above
        r_2b  = 2 * _b  # home-to-second distance
        r_arc = round(r_2b * 1.9)  # top bulge, behind second base

        _d_arc = round(r_arc / _math.sqrt(2))
        arc_end_1b_side = (HX + _d_arc, HY - _d_arc)
        arc_end_3b_side = (HX - _d_arc, HY - _d_arc)

        draw.line([FIRST, arc_end_1b_side], fill=0, width=1)
        draw.arc([HX - r_arc, HY - r_arc, HX + r_arc, HY + r_arc], start=225, end=315, fill=0, width=1)
        draw.line([arc_end_3b_side, THIRD], fill=0, width=1)

    # Foul lines: drawn after infield so they paint over any residual crossing
    # segments near the boundary between fair and foul territory.
    draw.line([(HX, HY), _ray_end(lf_x_ft, lf_y_ft)], fill=0, width=1)
    draw.line([(HX, HY), _ray_end(rf_x_ft, rf_y_ft)], fill=0, width=1)

    # Pitcher's mound dirt circle (~9ft radius) — drawn before the home
    # plate circle so the latter, which is larger at every scale, reads as
    # the more prominent of the two.
    mr = max(round(9 * FSCALE), 3)
    mx = int(HX)
    my = int(HY - round(60.5 * FSCALE))
    draw.ellipse([mx - mr, my - mr, mx + mr, my + mr], outline=0)

    # Home plate sits close to the tile's bottom edge, so its centre is
    # nudged up as needed to keep the pentagon fully inside the tile instead
    # of clipped flat by the boundary. `hr` is a clearance radius (not drawn)
    # used to keep the baselines from cutting into the plate — it must clear
    # the pentagon's corners, which sit farther out than its half-width.
    hr = max(round(13 * FSCALE), mr + 2, round(_math.hypot(hp - 1, hp)) + 1)
    hcy = HY - max(0, (HY + hr) - _cy1)

    def _diamond_exit(ax, ay, bx, by, half):
        """Point where segment a->b enters the diamond of half-size `half`
        centred at b, so lines stop at a base's outline instead of its middle."""
        dx, dy = bx - ax, by - ay

        def _dist(t):
            x, y = ax + t * dx, ay + t * dy
            return abs(x - bx) + abs(y - by)

        if _dist(0) <= half:  # pragma: no cover
            return (ax, ay)
        lo, hi = 0.0, 1.0
        for _ in range(30):
            mid = (lo + hi) / 2
            if _dist(mid) > half:
                lo = mid
            else:
                hi = mid
        return (ax + hi * dx, ay + hi * dy)

    # Bases: filled diamond if runner present, outline-only if empty
    bsz = max(round(4 * s), 4)

    # Baselines: home→1st and home→3rd are already drawn by the foul lines to the
    # outfield poles, so only the top two sides of the diamond need explicit lines.
    draw.line([_diamond_exit(*FIRST,  *SECOND, bsz), _diamond_exit(*SECOND, *FIRST,  bsz)], fill=0, width=1)
    draw.line([_diamond_exit(*SECOND, *THIRD,  bsz), _diamond_exit(*THIRD,  *SECOND, bsz)], fill=0, width=1)

    # Home plate — only drawn when it falls inside the visible cell.
    if hcy <= _cy1:
        draw.polygon([
            (HX,          hcy + hp),
            (HX - hp,     hcy),
            (HX - hp,     hcy - hp),
            (HX + hp,     hcy - hp),
            (HX + hp,     hcy),
        ], fill=255, outline=0)

    for runner_key, (bx, by) in [
        ('runner_on_first',  FIRST),
        ('runner_on_second', SECOND),
        ('runner_on_third',  THIRD),
    ]:
        occ = isinstance(game_data.get(runner_key), str)
        pts = [(bx, by - bsz), (bx + bsz, by), (bx, by + bsz), (bx - bsz, by)]
        if occ:
            draw.polygon(pts, fill=0, outline=0)
        else:
            draw.polygon(pts, fill=255, outline=0)

    # Coaches' boxes: rotated rectangles in foul territory, aligned with each
    # foul line (16ft long, centered closer to home than the base, x 5ft
    # deep, offset 15ft out from the foul line). u = home->base unit
    # direction (ft-space, x right / y toward CF), n = its outward normal
    # (away from the infield). Real feet scaled by FSCALE, same geometry as
    # field_view.py — but floored to a minimum scale so the box stays
    # legible at this tile's tiny FSCALE instead of rounding away to
    # nothing.
    _coach_scale = max(FSCALE, 0.45)

    _coach_px_nudge = 2    # fine-tune: extra px along the line, away from home
    _coach_screen_dx = -2  # fine-tune: flat screen-space shift, mirrored per side (left for 3B)
    _coach_screen_dy = 2   # fine-tune: flat screen-space shift, down (same both sides)

    def _coach_box_poly(u, n):
        da_near = 50 - 16 / 2
        da_far  = 50 + 16 / 2
        dp_near = 15
        dp_far  = 15 + 5
        # Mirror the horizontal shift by side so 1B and 3B look symmetric:
        # u[0] < 0 is the 3B (left) side, keeping the shift as-is (left);
        # u[0] > 0 is the 1B (right) side, flipping it to move right instead.
        _dx = _coach_screen_dx if u[0] < 0 else -_coach_screen_dx
        pts = []
        for da, dp in [(da_near, dp_near), (da_far, dp_near), (da_far, dp_far), (da_near, dp_far)]:
            pts.append((int(HX + (da * u[0] + dp * n[0]) * _coach_scale + _coach_px_nudge * u[0]) + _dx,
                         int(HY - (da * u[1] + dp * n[1]) * _coach_scale - _coach_px_nudge * u[1]) + _coach_screen_dy))
        return pts

    _u1, _n1 = (0.7071, 0.7071), (0.7071, -0.7071)    # home->first, outward
    _u3, _n3 = (-0.7071, 0.7071), (-0.7071, -0.7071)  # home->third, outward
    for _pts in (_coach_box_poly(_u1, _n1), _coach_box_poly(_u3, _n3)):
        # Omit the far side (parallel to the foul line, farthest from it) —
        # only draw the near side and the two perpendicular ends.
        _near, _far_near, _far_far, _near_far = _pts
        draw.line([_near, _far_near], fill=0)
        draw.line([_far_near, _far_far], fill=0)
        draw.line([_near_far, _near], fill=0)

    # Fence distance markers: 5 points evenly spaced by angle from home plate
    # (mirrors real outfield wall signage — LF pole, two power-alley gaps, CF, RF pole)
    _wall_font_size = max(round(9 * s), 9)
    font_tiny = _get_font(_wall_font_size)
    thetas = [_math.atan2(x_ft, y_ft) for x_ft, y_ft in wall_poly]
    theta_lo, theta_hi = thetas[0], thetas[-1]
    n_markers = 5
    _label_offs = max(round(9 * s), 9)  # px to push label outside the fence arc
    _fence_labels = []  # (tx, ty, lw, lh, label) — drawn after play labels
    for k in range(n_markers):
        target = theta_lo + (k / (n_markers - 1)) * (theta_hi - theta_lo)
        idx = min(range(len(thetas)), key=lambda i: abs(thetas[i] - target))
        x_ft, y_ft = wall_poly[idx]
        pt = wall_pts[idx]
        dist = round(_math.sqrt(x_ft**2 + y_ft**2))
        norm = _math.sqrt(x_ft**2 + y_ft**2) or 1
        ux, uy = x_ft / norm, y_ft / norm
        lx_c = int(pt[0] + ux * _label_offs)
        ly_c = int(pt[1] - uy * _label_offs)
        label = str(dist)
        lw = int(font_tiny.getlength(label))
        lh = font_tiny.getbbox('0')[3]
        tx = lx_c - lw // 2
        ty = ly_c - lh // 2
        tx = max(_cx0 + 1, min(_cx1 - lw - 1, tx))
        ty = max(_cy0 + 1, min(_cy1 - lh - 1, ty))
        _fence_labels.append((tx, ty, lw, lh, label))

    def _wall_dist_at_angle(theta):
        """Fence distance (ft) at a given angle from home plate, interpolated
        along wall_poly (same theta = atan2(x_ft, y_ft) convention as `thetas` above)."""
        t = max(thetas[0], min(thetas[-1], theta))
        for i in range(len(thetas) - 1):
            if thetas[i] <= t <= thetas[i + 1]:
                x0, y0 = wall_poly[i]
                x1, y1 = wall_poly[i + 1]
                d0, d1 = _math.hypot(x0, y0), _math.hypot(x1, y1)
                span = thetas[i + 1] - thetas[i]
                frac = (t - thetas[i]) / span if span else 0
                return d0 + (d1 - d0) * frac
        return _math.hypot(*wall_poly[-1])

    # Between innings: show full-game spray chart (all batted balls as dots).
    _between_innings = game_data.get('inningState') in ('Middle', 'End')
    _all_game_hits   = game_data.get('all_game_hits') or []
    if _between_innings and _all_game_hits:
        for h in _all_game_hits:
            hx_ft, hy_ft = _hit_coord_to_feet(h['x'], h['y'])
            if _lf_foul(hx_ft, hy_ft) or _rf_foul(hx_ft, hy_ft):
                continue
            is_hr  = h.get('is_hr',  False)
            is_hit = h.get('is_hit', not h.get('is_out', False))
            if is_hr:
                _ang = _math.atan2(hx_ft, hy_ft)
                _d_final = max(_math.hypot(hx_ft, hy_ft), _wall_dist_at_angle(_ang) + 8)
                hx_ft, hy_ft = _d_final * _math.sin(_ang), _d_final * _math.cos(_ang)
                pt = _fpt(hx_ft, hy_ft)
                px, py = int(pt[0]), int(pt[1])
                px = max(_cx0 + 1, min(_cx1 - 1, px))
                py = max(_cy0 + 1, min(_cy1 - 1, py))
                r = max(round(2 * s), 2)
                draw.ellipse([px - r, py - r, px + r, py + r], fill=0)
            else:
                pt = _fpt(hx_ft, hy_ft)
                px, py = int(pt[0]), int(pt[1])
                px = max(_cx0 + 1, min(_cx1 - 1, px))
                py = max(_cy0 + 1, min(_cy1 - 1, py))
                r = max(round(2 * s), 2)
                if is_hit:
                    draw.ellipse([px - r, py - r, px + r, py + r], fill=0)
                else:
                    draw.ellipse([px - r, py - r, px + r, py + r], outline=0)
        return Himage

    # Batted-ball markers — last 7 balls put in play (fair or foul).
    # API hit coordinates are converted with _hit_coord_to_feet(), the same
    # transform the fence polygons were built with.
    # recent_hits is newest-last; fall back to single last_hit_x/y.
    recent_hits = game_data.get('recent_hits') or []
    if not recent_hits:
        lhx = game_data.get('last_hit_x')
        lhy = game_data.get('last_hit_y')
        if lhx is not None and lhy is not None:
            recent_hits = [{
                'x': lhx, 'y': lhy,
                'is_hr':  bool(game_data.get('last_hit_is_hr')),
                'is_out': bool(game_data.get('last_hit_is_out')),
            }]

    def _bezier_trajectory(p0x, p0y, p1x, p1y, launch_angle=None, hx_ft=0.0):
        mx_, my_ = (p0x + p1x) / 2, (p0y + p1y) / 2
        dx_, dy_ = p1x - p0x, p1y - p0y
        dist_ = _math.sqrt(dx_ ** 2 + dy_ ** 2) or 1
        # Steeper launch angle → taller arc
        curve = 0.05 + max(0.0, min(90.0, launch_angle)) / 90.0 * 0.35
        # Right-field hits bow right; left-field hits bow left
        side = 1.0 if hx_ft >= 0 else -1.0
        ctrl_x = mx_ - dy_ / dist_ * dist_ * curve * side
        ctrl_y = my_ + dx_ / dist_ * dist_ * curve * side
        pts = []
        for i in range(13):
            t = i / 12
            pts.append(((1-t)**2 * p0x + 2*(1-t)*t * ctrl_x + t**2 * p1x,
                         (1-t)**2 * p0y + 2*(1-t)*t * ctrl_y + t**2 * p1y))
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i+1]], fill=0, width=1)

    # recent_hits is oldest-first; the last entry is the most recent play.
    most_recent_idx = len(recent_hits) - 1
    _recent_play_rect = None  # bounding box of the most recent play label

    for idx, h in enumerate(recent_hits):
        hx_ft, hy_ft = _hit_coord_to_feet(h['x'], h['y'])
        if _lf_foul(hx_ft, hy_ft) or _rf_foul(hx_ft, hy_ft):
            continue
        is_hr  = h.get('is_hr',  False)
        is_out = h.get('is_out', False)
        abbr   = h.get('abbr', 'HR' if is_hr else ('F' if is_out else '1B'))
        if is_hr:
            abbr = 'HR'

        # Landing spot: real hit coordinates for every ball. A confirmed HR must
        # clear the fence visually — if the API coordinates land short of the wall
        # in that direction (coordinate imprecision), push it out to just past
        # the fence rather than forcing every HR to the cell edge.
        if is_hr:
            _ang = _math.atan2(hx_ft, hy_ft)
            _d_ball = _math.hypot(hx_ft, hy_ft)
            _d_wall = _wall_dist_at_angle(_ang)
            _d_final = max(_d_ball, _d_wall + 8)
            hx_ft, hy_ft = _d_final * _math.sin(_ang), _d_final * _math.cos(_ang)
        land_pt = _fpt(hx_ft, hy_ft)

        if idx == most_recent_idx and h.get('launch_angle') is not None:
            _bezier_trajectory(HX, HY, *land_pt,
                               launch_angle=h.get('launch_angle'),
                               hx_ft=hx_ft)

        # Play abbreviation label (F, L, G, HR, 1B, 2B, 3B …) at the landing spot.
        tw = max(int(font_tiny.getlength(abbr)), 1)
        _tx = max(_cx0, min(_cx1 - tw, land_pt[0] - tw // 2))
        _ty = max(_cy0 + 1, land_pt[1] - 9)
        draw.text((_tx, _ty), abbr, font=font_tiny, fill=0)
        if idx == most_recent_idx:
            lh = font_tiny.getbbox('Ay')[3]
            _recent_play_rect = (_tx - 1, _ty, _tx + tw + 1, _ty + lh)

    # Draw fence distance labels, suppressing any that overlap the most recent
    # play label (they reappear once that play fades into an older hit).
    for tx, ty, lw, lh, label in _fence_labels:
        if _recent_play_rect is not None:
            rx0, ry0, rx1, ry1 = _recent_play_rect
            if not (tx + lw < rx0 or tx > rx1 or ty + lh < ry0 or ty > ry1):
                continue
        draw.rectangle([tx - 1, ty, tx + lw + 1, ty + lh], fill=255)
        draw.text((tx, ty), label, font=font_tiny, fill=0)

    return Himage


def draw_fields_box(Himage, start_x, start_y, game_data, team_data, scale=1):
    """Single 150×130 field-diagram cell for the 'fields' scoreboard mode.

    Shows the venue field diagram (with spray chart) plus a compact
    header strip: away @ home, score, inning, and out count.
    """
    s = scale
    W = 150 * s
    HDR_H = 20 * s
    CELL_H = 130 * s  # main cell body (matches standard box height)

    away_id = str(game_data.get('away_team_id', ''))
    home_id = str(game_data.get('home_team_id', ''))
    abbrevs = team_data.get('team_abbreviation', {})
    away = abbrevs.get(away_id, '???')
    home = abbrevs.get(home_id, '???')

    state = game_data.get('detailed_state', '')
    # Normalize review/challenge states
    if state in ('Player challenge', 'Manager challenge', 'Completed Early'):
        state = 'In Progress'

    inning = game_data.get('current_inning') or 0
    ing_state = game_data.get('inningState', '')
    outs = game_data.get('num_of_outs') or 0
    away_r = game_data.get('away_runs')
    home_r = game_data.get('home_runs')

    draw = ImageDraw.Draw(Himage)
    font = _get_font(9 * s)

    # Header strip: white background + border
    draw.rectangle(
        [start_x, start_y, start_x + W - 1, start_y + HDR_H - 1],
        fill=255, outline=0,
    )

    if state in ('Final', 'Game Over', 'Final: Tied'):
        score = f'{away_r}-{home_r}' if away_r is not None and home_r is not None else ''
        hdr = f'{away} {score} {home} F' if score else f'{away} @ {home} F'
    elif state in ('In Progress',):
        score = f'{away_r}-{home_r}' if away_r is not None and home_r is not None else ''
        _side = {'Top': 'T', 'Bottom': 'B', 'Middle': 'M', 'End': 'E'}.get(ing_state, '')
        _ing = f'{_side}{inning}' if inning else ''
        _outs = f' {outs}o' if _ing else ''
        hdr = f'{away} {score} {home} {_ing}{_outs}'.strip() if score else f'{away} @ {home}'
    else:
        start_time = game_data.get('game_start', '')
        hdr = f'{away} @ {home}' + (f' {start_time}' if start_time else '')

    _hdr_w = int(font.getlength(hdr))
    _hdr_x = start_x + max(0, (W - _hdr_w) // 2)
    draw.text((_hdr_x, start_y + (HDR_H - font.getbbox('Ay')[3]) // 2), hdr, font=font, fill=0)

    # Field diagram — fills the cell below the header
    _draw_field_cell(
        draw, Himage, start_x, start_y + HDR_H, W, CELL_H, game_data,
        scale=s, vis_h=CELL_H,
    )

    # Outer border
    draw.rectangle([start_x, start_y, start_x + W - 1, start_y + HDR_H + CELL_H - 1], outline=0)

    return Himage


def draw_triple_box(Himage, start_x, start_y, game_data, team_data,
                    score_changed=False, use_logos=False, logo_x_offset=2,
                    show_win_prob=False, streak_map=None, scale=1):
    """Featured 3-cell (435×130 px) game tile.

    Cell 1 (left, 135 px):  standard game box — score, linescore, logo.
    Cell 2 (middle, 150 px): pitch zone + bases/outs/count + pitcher/batter.
    Cell 3 (right, 150 px):  venue field diagram with outfield wall,
                              infield diamond, and runner positions.
    """
    s = scale
    CELL_W  = 135 * s
    RIGHT_W = 150 * s
    FIELD_W = 150 * s
    TOTAL_W = CELL_W + RIGHT_W + FIELD_W   # 435 px
    HEADER_H = 20 * s
    TOTAL_H  = 130 * s

    Himage = draw_box(
        Himage, start_x, start_y, game_data, team_data,
        score_changed=score_changed,
        use_logos=use_logos,
        logo_x_offset=logo_x_offset,
        show_win_prob=show_win_prob,
        streak_map=streak_map,
        show_winner_logo=True,
        scale=scale,
        force_linescore=True,
        always_show_hits=True,
        hide_last_play=True,
        skip_header_invert=True,
        win_prob_center_line=False,   # same as the wide tile — see draw_wide_box
    )

    draw = ImageDraw.Draw(Himage)
    rp_x        = start_x + CELL_W
    fp_x        = rp_x + RIGHT_W
    total_right = start_x + TOTAL_W

    # Extend outer top border across all right panels; bottom only through cells 1+2
    draw.line((rp_x, start_y,              total_right, start_y),              fill=0)
    draw.line((rp_x, start_y + TOTAL_H,    fp_x,        start_y + TOTAL_H),    fill=0)
    # Header divider only under panel 2 — panel 3 (field diagram) has no header row
    draw.line((rp_x, start_y + HEADER_H,   fp_x,        start_y + HEADER_H),   fill=0)

    # Cell 2: pitch zone / situation
    _draw_wide_right_panel(
        draw, Himage,
        rp_x=rp_x, rp_y=start_y,
        rp_w=RIGHT_W, rp_h=TOTAL_H,
        header_h=HEADER_H,
        game_data=game_data,
        team_data=team_data,
        use_logos=use_logos,
        scale=scale,
    )

    # Cell 3: field diagram. vis_h=150 centres the field across the full
    # 150 px grid slot (tile + footer gap), since cell 3 has no bottom border.
    # This gives ~13 px above CF and places home plate ~6 px into the footer.
    draw = ImageDraw.Draw(Himage)
    _draw_field_cell(draw, Himage, fp_x, start_y, 150, 150, game_data, scale=scale, vis_h=150)

    # Batted-ball stat badge: right-aligned in the bottom-right corner of the
    # field cell, directly above the venue name, for the most recent ball put
    # in play (any outcome) — play type, exit velo, launch angle, and (for
    # home runs) distance.
    _recent_hits = game_data.get('recent_hits') or []
    if not _recent_hits and game_data.get('last_hit_is_hr'):
        _recent_hits = [{'is_hr': True}]
    _last_hit = _recent_hits[-1] if _recent_hits else None
    if _last_hit is not None:
        _hit_is_hr = _last_hit.get('is_hr', False)
        _hit_label = 'HR' if _hit_is_hr else (_last_hit.get('abbr') or '')
        _hit_dist  = _last_hit.get('distance')
        _hit_velo  = _last_hit.get('exit_velo')
        _hit_angle = _last_hit.get('launch_angle')
        _stat_lines = [p for p in [
            f'{round(_hit_angle)}°' if _hit_angle is not None else '',
            f'{int(_hit_dist)} ft' if _hit_dist is not None else '',
            f'{round(_hit_velo)} Mph' if _hit_velo is not None else '',
        ] if p]
        if _stat_lines:
            _hr_font = _get_font(round(10 * scale))
            _line_h  = _hr_font.getbbox('Ay')[3]
            _hr_y    = start_y + int(TOTAL_H) + 9 - _line_h - 1
            for _line in reversed(_stat_lines):
                _lw = int(_hr_font.getlength(_line))
                _lx = int(fp_x + FIELD_W) - _lw - 1
                draw.rectangle([_lx, _hr_y, _lx + _lw, _hr_y + _line_h], fill=255)
                draw.text((_lx, _hr_y), _line, font=_hr_font, fill=0)
                draw.text((_lx + 1 * scale, _hr_y), _line, font=_hr_font, fill=0)
                _hr_y -= _line_h

        # Result badge (HR, F9, 1B, …): bottom-left corner of the field cell,
        # sized the same way the pitcher-K milestone badge in the footer strip
        # is — largest point size (18pt down to 7pt) that fits the available
        # width — so it reads as a matching bold "footer badge" style. Vertical
        # placement is centred in the same 20px footer band the K badge uses.
        if _hit_label:
            _res_max_w = int(FIELD_W // 2) - 4 * scale
            _res_font = _get_font(7 * scale)
            for _px in range(18, 6, -1):
                _f = _get_font(_px * scale)
                if int(_f.getlength(_hit_label)) <= _res_max_w:
                    _res_font = _f
                    break
            _res_h = _res_font.getbbox('Ay')[3]
            _res_w = int(_res_font.getlength(_hit_label))
            _res_x = fp_x + 2 * scale + 8
            _res_y = (start_y + int(TOTAL_H)
                      + (20 * scale - _res_h) // 2 - 1 * scale - 5)
            draw.rectangle([_res_x, _res_y, _res_x + _res_w, _res_y + _res_h], fill=255)
            draw.text((_res_x, _res_y), _hit_label, font=_res_font, fill=0)
            draw.text((_res_x + 1 * scale, _res_y), _hit_label, font=_res_font, fill=0)

    # Venue name: right-aligned label in the footer gap below the cell border.
    # A tight white rectangle erases the infield polygon lines behind the glyphs.
    # Max width is capped so the label stays right of the home-plate dirt area;
    # font shrinks (never truncates) until the full name fits inside that cap.
    _venue_name = _clean_venue_name(game_data.get('venue', '')) or ''
    if _venue_name:
        _vy        = start_y + int(TOTAL_H) + 9
        _field_bot = start_y + int(150 * scale)
        # Left boundary: 2 px right of home plate centre (HX = FIELD_W/2) plus margin.
        _max_vw    = int(FIELD_W // 2) - 8   # = 67 px at scale=1
        # Grow from 5 pt upward; stop at the last size where the full name fits
        # both horizontally (≤ _max_vw) and vertically (≤ _field_bot).
        _vfont = _get_font(5)
        for _fs in range(6, 20):
            _cand = _get_font(_fs)
            if _vy + _cand.getbbox('Ay')[3] > _field_bot:
                break
            if int(_cand.getlength(_venue_name)) > _max_vw:
                break
            _vfont = _cand
        _vfont_h = _vfont.getbbox('Ay')[3]
        if _vy + _vfont_h <= _field_bot and int(_vfont.getlength(_venue_name)) <= _max_vw:
            _vw = int(_vfont.getlength(_venue_name))
            _vx = int(fp_x + FIELD_W) - _vw - 1
            draw.rectangle([_vx, _vy, _vx + _vw, _vy + _vfont_h], fill=255)
            draw.text((_vx, _vy), _venue_name, font=_vfont, fill=0)

    # Invert spanning header when a run scored or score changed
    _between   = game_data.get('inningState') in ('Middle', 'End')
    _run_scored = (
        game_data.get('detailed_state') == 'In Progress'
        and int(game_data.get('last_play_rbi') or 0) > 0
    )
    if (score_changed or _run_scored) and not _between:
        # Only cells 1+2 (up to fp_x) light up — cell 3 is the field diagram
        # and has no header row of its own.
        _invert_region(Himage, start_x, start_y, fp_x, start_y + HEADER_H)
        draw = ImageDraw.Draw(Himage)

    # No-hitter / perfect game header inversion
    _triple_is_final = game_data.get('detailed_state') in ('Final', 'Game Over', 'Final: Tied')
    _triple_active_no_no = (
        game_data.get('detailed_state') == 'In Progress' and
        (game_data.get('no_hitter') or game_data.get('perfect_game')) and
        (game_data.get('current_inning') or 0) >= 6
    )
    if (game_data.get('no_hitter') or game_data.get('perfect_game')) and \
       (_triple_is_final or _triple_active_no_no) and \
       not (score_changed or _run_scored):
        _invert_region(Himage, start_x, start_y, start_x + TOTAL_W, start_y + HEADER_H)

    return Himage
