import math as _math
import re as _re
import time as _time
import pytz
from datetime import datetime as _datetime

from PIL import Image, ImageDraw, ImageOps

from image_assets import (
    _get_font, _logo_small, _logo_ghost, _paste_logo,
    _load_codepoint_ghost, _TEAM_ID_ABBR_OVERRIDE, _PPD_EMOJI_CODEPOINTS, _SUSP_EMOJI_CODEPOINTS,
)
from image_utils import (
    draw_diamond, draw_circle, check_if_two_chars,
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


def _draw_backwards_k(img, x, y, fnt):
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
    img.paste(0, (px, py, px + gw + 2 * pad, py + gh + 2 * pad), mask)


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

    # --- per-inning scores ---
    def _draw_row(inn_runs, row_y):
        """Draw row."""
        for k in range(N_COLS):
            idx = first_inn - 1 + k
            if idx < len(inn_runs) and inn_runs[idx] is not None:
                val = str(inn_runs[idx])
                cell_x = grid_x0 + LOGO_COL_W + k * COL_W
                # Use font9 for double-digit values that won't fit in font11
                fnt = font11 if int(font11.getlength(val)) <= COL_W - 1 else font9
                cx = cell_x + COL_W // 2
                cy = row_y + ROW_H_TEAM // 2
                _draw_centered(fnt, val, cx, cy)

    _draw_row(away_inn, y1)
    _draw_row(home_inn, y2)

    # X mark in the home team's last column when the bottom half wasn't played.
    _is_final = game_data.get('detailed_state') in ('Final', 'Game Over', 'Final: Tied')
    if _is_final and away_inn:
        last_idx = len(away_inn) - 1
        away_last = away_inn[last_idx]
        home_last = home_inn[last_idx] if last_idx < len(home_inn) else None
        if home_last is None and away_last is not None:
            col_k = last_idx - (first_inn - 1)
            if 0 <= col_k < N_COLS:
                cell_x = grid_x0 + LOGO_COL_W + col_k * COL_W
                cx = cell_x + COL_W // 2
                cy = y2 + ROW_H_TEAM // 2
                hx = 2 * s  # narrow horizontal spread → skinny X
                hy = 4 * s  # taller vertical spread
                draw.line((cx - hx, cy - hy, cx + hx, cy + hy), fill=0)
                draw.line((cx + hx, cy - hy, cx - hx, cy + hy), fill=0)

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

        # ABS dots — one per challenge slot, max grows +1 per extra inning
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


def _load_tomorrow_games():
    """Load the next-day schedule, fetching from the API if the cache is missing or stale.

    In the morning window (before 9am local time) the 'next game' relative to
    last night's results is today, so we accept today's date and fall back to
    fetching today rather than actual tomorrow.
    """
    from datetime import date as _date, timedelta as _td, datetime as _dt
    today    = _date.today().strftime('%Y-%m-%d')
    tomorrow = (_date.today() + _td(days=1)).strftime('%Y-%m-%d')

    # Determine whether we're in the morning window (before morning_end local)
    try:
        _cfg = load_yaml_file('config.yaml')
        _tz_str = _cfg.get('timezone', 'America/Chicago')
        _now_local = _dt.now(pytz.timezone(_tz_str))
        _is_wkend = _now_local.weekday() >= 5
        _morning_end = (_cfg.get('morning_end_weekend', 11) if _is_wkend
                        else _cfg.get('morning_end', 9))
        _is_morning = _now_local.hour < _morning_end
    except Exception:
        _is_morning = False
    _target = today if _is_morning else tomorrow

    try:
        data = load_json_file('tomorrow_games.json') or {}
        if data.get('date') == _target and data.get('games') is not None:
            return data
        # Cache is missing or has wrong date — fetch for the right target date
        from fetch_games import fetch_tomorrow_games
        fetch_tomorrow_games(for_date=_target)
        data = load_json_file('tomorrow_games.json') or {}
        return data if data.get('games') is not None else None
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
            draw.text((_tx,         _time_y), t_str, font=font14, fill=0)
            draw.text((_tx + 1 * s, _time_y), t_str, font=font14, fill=0)

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
            draw.text((_tx,         _time_y), t_str, font=font14, fill=0)
            draw.text((_tx + 1 * s, _time_y), t_str, font=font14, fill=0)

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


def draw_box(Himage, start_x, start_y, game_data, team_data, score_changed=False, use_logos=False, logo_x_offset=2, show_win_prob=False, streak_map=None, show_winner_logo=True, scale=1, force_linescore=False, always_show_hits=False, hide_last_play=False, skip_header_invert=False):
    """Render a single game score box onto Himage at (start_x, start_y)."""
    s = scale
    _is_walkoff = bool(game_data.get('walk_off'))
    # Normalize early-completion states (e.g. spring training games called after 6 innings)
    if game_data.get('detailed_state', '').startswith('Completed Early'):
        game_data = dict(game_data)
        game_data['detailed_state'] = 'Final'

    # Normalize mid-game review/challenge states to In Progress
    _challenge_abbr = ''
    if game_data.get('detailed_state') in ('Player challenge', 'Manager challenge'):
        game_data = dict(game_data)
        _chal_prefix = 'ABS CHAL' if game_data['detailed_state'] == 'Player challenge' else 'M CHAL'
        _challenge_abbr = game_data.get('challenge_team_abbr', '')
        # Write into sub_event so the challenge label has highest display priority
        # (sub_event wins over last_play, preventing "PC: Name" from overriding it).
        # Logo rendering shows the team; keep text label as prefix only.
        game_data['sub_event'] = _chal_prefix
        game_data['last_play'] = _chal_prefix
        game_data['detailed_state'] = 'In Progress'

    # Delayed Start = game hasn't begun yet; treat like Pre-Game (show pitcher probables)
    if game_data.get('detailed_state') == 'Delayed Start':
        game_data = dict(game_data)
        game_data['detailed_state'] = 'Pre-Game'

    # Only show score once the first pitch has been thrown. Evidence of play:
    # a ball/strike in the current at-bat, any out, any hit, a runner on base,
    # an inning break, or the game past inning 1. If none of these are present
    # the game hasn't officially started despite the API saying "In Progress".
    if game_data.get('detailed_state') == 'In Progress':
        # Only show score once the first pitch has been thrown.
        # away_hits/home_hits are intentionally excluded: in the GIF path they
        # are inherited from the final game box score and are always non-zero,
        # causing false positives before the game starts.
        _has_play = (
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
        if not _has_play:
            game_data = dict(game_data)
            game_data['detailed_state'] = 'Pre-Game'

    draw = ImageDraw.Draw(Himage)
    font24 = _get_font(24 * s)
    font18 = _get_font(18 * s)
    font14 = _get_font(14 * s)
    font11 = _get_font(11 * s)
    font9 = _get_font(9 * s)

    _cfg = load_yaml_file('config.yaml')
    _FINAL_LINESCORE_SECS = _cfg.get('final_linescore_minutes', 60) * 60

    vertical_len = 110 * s
    horizonta_len = 135 * s
    max_text_width = horizonta_len - 14 * s

    # Needed by the elif chain below — define early so all branches can reference it
    _delayed_with_score = (
        game_data['detailed_state'] == 'Delayed'
        and (game_data.get('current_inning') or 0) > 0
    )

    # True when we should show the linescore grid instead of the normal score layout
    _between_innings = (
        game_data['detailed_state'] == 'In Progress'
        and game_data.get('inningState') in ('Middle', 'End')
    )
    # Any pitching change — always show linescore grid.
    _pitching_change = (
        game_data['detailed_state'] == 'In Progress'
        and (game_data.get('sub_event') or '').startswith('PC:')
    )
    # True when the PC happens during a live half-inning (< 3 outs AND the inning
    # has already started — at least one out recorded or a pitch already thrown).
    _mid_inning_pc = (
        _pitching_change and not _between_innings
        and (
            (game_data.get('num_of_outs') or 0) > 0
            or (game_data.get('at_bat_pitch_count') or 0) > 0
        )
    )
    # End of 9th+ with one team leading, or Mid 9th+ with home team winning — game is effectively over
    _inn_state_ge = game_data.get('inningState') or ''
    _game_ending_state = (
        (game_data.get('current_inning') or 0) >= 9 and
        (
            (_inn_state_ge == 'End' and (game_data.get('away_runs') or 0) != (game_data.get('home_runs') or 0)) or
            (_inn_state_ge == 'Middle' and (game_data.get('home_runs') or 0) > (game_data.get('away_runs') or 0))
        )
    )

    _in_linescore_window = False  # set True inside Final block when within the linescore window

    def fit_text(text, max_w):
        """Fit text."""
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

    # team names short
    away_team_id = str(game_data['away_team_id'])
    home_team_id = str(game_data['home_team_id'])

    # Handle missing team abbreviations gracefully
    abbr_map = team_data.get('team_abbreviation', {})
    away_team_name = _TEAM_ID_ABBR_OVERRIDE.get(away_team_id) or abbr_map.get(away_team_id, f'T{away_team_id}')
    home_team_name = _TEAM_ID_ABBR_OVERRIDE.get(home_team_id) or abbr_map.get(home_team_id, f'T{home_team_id}')

    # Postponed rain emoji ghost — drawn first so all content renders on top
    if game_data['detailed_state'] == 'Postponed':
        import random as _random
        _ppd_cp = _random.Random(game_data.get('game_pk', 0) ^ int(_time.time() // 60)).choice(_PPD_EMOJI_CODEPOINTS)
        _ppd_ghost = _load_codepoint_ghost(_ppd_cp, size=90 * s)
        if _ppd_ghost:
            _gw, _gh = _ppd_ghost.size
            _gx = start_x + (horizonta_len - _gw) // 2
            _gy = start_y + (vertical_len + 20 * s - _gh) // 2
            Himage.paste(_ppd_ghost, (_gx, _gy))
            draw = ImageDraw.Draw(Himage)

    # Suspended lightning emoji ghost
    if game_data['detailed_state'] == 'Suspended':
        import random as _random
        _susp_cp = _random.Random(game_data.get('game_pk', 0) ^ int(_time.time() // 60)).choice(_SUSP_EMOJI_CODEPOINTS)
        _susp_ghost = _load_codepoint_ghost(_susp_cp, size=90 * s)
        if _susp_ghost:
            _gw, _gh = _susp_ghost.size
            _gx = start_x + (horizonta_len - _gw) // 2
            _gy = start_y + (vertical_len + 20 * s - _gh) // 2
            Himage.paste(_susp_ghost, (_gx, _gy))
            draw = ImageDraw.Draw(Himage)

    # Winner ghost logo — drawn first so all text/scores render on top of it
    if show_winner_logo and use_logos and game_data['detailed_state'] in ('Final', 'Game Over', 'Final: Tied'):
        winner_abbr = winner_id = None
        if game_data.get('away_team_is_winner'):
            winner_abbr, winner_id = away_team_name, away_team_id
        elif game_data.get('home_team_is_winner'):
            winner_abbr, winner_id = home_team_name, home_team_id
        if winner_abbr:
            ghost = _logo_ghost(winner_abbr, winner_id, size=110 * s)
            if ghost:
                gw, gh = ghost.size
                gx = start_x + (135 * s - gw) // 2 + 0
                gy = start_y + 20 * s + (vertical_len - gh) // 2
                Himage.paste(ghost, (gx, gy))
                draw = ImageDraw.Draw(Himage)

    # inning or game state
    if game_data['detailed_state'] in ('Final', 'Game Over', 'Final: Tied'):
        away_inning_runs = game_data.get('away_inning_runs') or []
        home_inning_runs = game_data.get('home_inning_runs') or []
        winner_name = game_data.get('winner_name')
        loser_name = game_data.get('loser_name')

        # Anchor the 60-min linescore window to the actual game end time when available,
        # falling back to when the app first saw this game as Final.
        _game_pk = game_data.get('game_pk')
        _final_ts = _get_or_set_final_time(_game_pk) if _game_pk else None
        _end_utc_str = game_data.get('game_end_time_utc')
        if _end_utc_str:
            try:
                _end_utc_dt = pytz.utc.localize(_datetime.strptime(_end_utc_str[:19], "%Y-%m-%dT%H:%M:%S"))
                _elapsed = (_datetime.now(pytz.utc) - _end_utc_dt).total_seconds()
                _in_linescore_window = not _historical_mode and _elapsed < _FINAL_LINESCORE_SECS
            except Exception:
                _in_linescore_window = (
                    not _historical_mode and _final_ts is not None and
                    (_time.time() - _final_ts) < _FINAL_LINESCORE_SECS
                )
        else:
            _in_linescore_window = (
                not _historical_mode and _final_ts is not None and
                (_time.time() - _final_ts) < _FINAL_LINESCORE_SECS
            )

        _decisions_ready = bool(winner_name and loser_name)
        _show_linescore = (away_inning_runs or home_inning_runs) and (
            _in_linescore_window or not _decisions_ready
        )

        if _show_linescore:
            # Show linescore for 10 min after game ends; switch once both window
            # has elapsed AND decisions are posted.
            draw, Himage = _draw_linescore_grid(draw, Himage, start_x, start_y, game_data, team_data, use_logos, scale=scale)
        else:
            # Pitchers of record — anchored to bottom of box, working upward.
            # bottom border is at start_y + vertical_len + 20 = start_y + 130
            LINE_H = 15 * s
            BOTTOM_Y = start_y + vertical_len + 20 * s - 3 * s  # 3px margin above bottom border
            saver = game_data.get('saver_name')
            winner_record = game_data.get('winner_record')
            loser_record = game_data.get('loser_record')
            saver_saves = game_data.get('saver_saves')
            lines = []
            wp_name = _format_player_name(winner_name or '')
            lp_name = _format_player_name(loser_name or '')
            wp_str = f'WP: {wp_name} ({winner_record})' if winner_record else f'WP: {wp_name}'
            lp_str = f'LP: {lp_name} ({loser_record})' if loser_record else f'LP: {lp_name}'
            lines.append((lp_str, font14, False))
            lines.append((wp_str, font14, False))
            if saver and not _is_walkoff:
                sv_name = _format_player_name(saver)
                sv_str = f'SV: {sv_name} (S{saver_saves})' if saver_saves is not None else f'SV: {sv_name}'
                lines.append((sv_str, font14, False))

            _wpname_max_w = horizonta_len - 2 * s

            def _truncate_keep_suffix(s):
                """Truncate keep suffix."""
                if int(font14.getlength(s)) <= _wpname_max_w:
                    return s
                # Try dropping first initial: "WP: W. Warren (2-2)" → "WP: Warren (2-2)"
                for _pfx in ('WP: ', 'LP: ', 'SV: '):
                    if s.startswith(_pfx):
                        _rest = s[len(_pfx):]
                        if len(_rest) > 2 and _rest[1:3] == '. ':
                            _no_init = _pfx + _rest[3:]
                            if int(font14.getlength(_no_init)) <= _wpname_max_w:
                                return _no_init
                            s = _no_init
                        break
                paren = s.rfind(' (')
                if paren != -1:
                    suffix = s[paren:]
                    prefix = s[:paren]
                    suffix_w = int(font14.getlength(suffix))
                    avail = _wpname_max_w - suffix_w
                    while prefix and int(font14.getlength(prefix)) > avail:
                        prefix = prefix[:-1]
                    return prefix + suffix
                while s and int(font14.getlength(s)) > _wpname_max_w:
                    s = s[:-1]
                return s

            for i, (txt, fnt, bold) in enumerate(reversed(lines)):
                y = BOTTOM_Y - LINE_H * (i + 1)
                t = _truncate_keep_suffix(txt)
                draw.text((start_x + 2 * s, y), t, font=fnt, fill=0)
                if bold:  # pragma: no cover
                    draw.text((start_x + 3 * s, y), t, font=fnt, fill=0)

    elif game_data['detailed_state'] == 'Warmup' or game_data['detailed_state'] == 'Pre-Game' or  game_data['detailed_state'] == 'Scheduled':
        def _draw_pitcher_era(name_part, stat_part, y_pos):
            """Draw pitcher name left-aligned and stat right-anchored."""
            if stat_part:
                stat_w = int(font14.getlength(stat_part))
                stat_x = start_x + horizonta_len - stat_w - 1 * s
                draw.text((stat_x, y_pos), stat_part, font=font14, fill=0)
                max_name_w = stat_x - (start_x + 2 * s) - 2 * s
                name_str, name_fnt = fit_text(name_part, max(max_name_w, 20 * s))
                draw.text((start_x + 2 * s, y_pos), name_str, font=name_fnt, fill=0)
            else:
                name_str, name_fnt = fit_text(name_part, max_text_width)
                draw.text((start_x + 2 * s, y_pos), name_str, font=name_fnt, fill=0)

        away_name, away_stat = _pitcher_line(game_data.get("away_probable"), game_data.get("away_probable_note"))
        home_name, home_stat = _pitcher_line(game_data.get("home_probable"), game_data.get("home_probable_note"))
        _draw_pitcher_era(away_name, away_stat, start_y + 25 * s + 59 * s)
        _draw_pitcher_era(home_name, home_stat, start_y + 25 * s + 74 * s)
    elif game_data['detailed_state'] == 'Postponed':
        reason = game_data.get('postpone_reason') or game_data.get('description') or ''
        postponed_line, postponed_fnt = fit_text(f'PPD: {reason}' if reason else 'Postponed', max_text_width)
        draw.text((start_x + 7 * s, start_y + 25 * s + 59 * s), postponed_line, font=postponed_fnt, fill=0)
        desc = game_data.get('description') or ''
        if desc.lower().startswith('makeup') and game_data.get('postpone_reason'):
            makeup_line, makeup_fnt = fit_text(desc, max_text_width)
            draw.text((start_x + 7 * s, start_y + 25 * s + 74 * s), makeup_line, font=makeup_fnt, fill=0)
    elif game_data['detailed_state'] == 'Suspended':
        draw, Himage = _draw_linescore_grid(draw, Himage, start_x, start_y, game_data, team_data, use_logos, scale=scale)
    elif _delayed_with_score:
        draw, Himage = _draw_linescore_grid(draw, Himage, start_x, start_y, game_data, team_data, use_logos, scale=scale)
        # Next 3 batters + pitcher — same panel used for between-innings
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
    elif game_data['detailed_state'] == 'In Progress':
        # A mid-inning pitching change keeps the active (bases/diamond) display —
        # only between-inning/start-of-inning PCs swap in the linescore grid.
        _pc_grid = _pitching_change and not _mid_inning_pc
        _show_grid = _between_innings or _pc_grid or force_linescore
        if _show_grid:
            draw, Himage = _draw_linescore_grid(draw, Himage, start_x, start_y, game_data, team_data, use_logos, scale=scale)
        if not _show_grid:
            # Active play: pitch/pitcher/batter info
            _pc = game_data.get('pitch_count')
            _ab_pc = game_data.get('at_bat_pitch_count') or 0
            _pt = game_data.get('last_pitch_type', '')   # e.g. "FB", "SL", "CH"
            _lps = game_data.get('last_pitch_speed')
            # Game-level pitch count when available; fall back to per-at-bat for timelapse.
            _pc_disp = f'{_pc}P' if _pc is not None else (f'AB{_ab_pc}' if _ab_pc else None)

            # Pitcher line — full width, no right badge (type moves to speed line)
            _pitcher_name = _format_player_name(game_data.get("current_pitcher") or "")
            _pit_str = f'P: {_pitcher_name}'
            if font14.getlength(_pit_str) <= max_text_width:
                pitcher_str, pitcher_font = _pit_str, font14
            else:
                pitcher_str, pitcher_font = fit_text(_pit_str, max_text_width)
            draw.text((start_x + 2 * s, start_y + 25 * s + 74 * s), pitcher_str, font=pitcher_font, fill=0)

            # Speed line: "FB 95" right-aligned; pitch count left of that
            _speed_y = start_y + 25 * s + 62 * s
            if _lps:
                # Combine type+speed broadcast-style ("FB 95" or just "95" if no type)
                _speed_str = f'{_pt} {int(_lps)}' if _pt else str(int(_lps))
                _speed_w = int(font11.getlength(_speed_str)) + 2 * s
                _speed_x = start_x + horizonta_len - _speed_w
                draw.text((_speed_x,         _speed_y), _speed_str, font=font11, fill=0)
                draw.text((_speed_x + 1 * s, _speed_y), _speed_str, font=font11, fill=0)
                if _pc_disp:
                    _pc_w = int(font11.getlength(_pc_disp))
                    draw.text((_speed_x - _pc_w - 3 * s, _speed_y), _pc_disp, font=font11, fill=0)
            elif _pt or _pc_disp:
                # No speed: show "FB 47P", "FB AB3", "47P", or "AB3"
                _no_speed_str = f'{_pt} {_pc_disp}' if _pt and _pc_disp else (_pt or _pc_disp or '')
                _ns_w = int(font11.getlength(_no_speed_str)) + 2 * s
                draw.text((start_x + horizonta_len - _ns_w, _speed_y), _no_speed_str, font=font11, fill=0)

            # Batter record for the night "2-4" right-anchored on hitter line
            _bh = game_data.get('batter_hits')
            _ba = game_data.get('batter_at_bats')
            _ba_str = f'{_bh}-{_ba}' if _bh is not None and _ba is not None else ''
            _ba_w = min(int(font11.getlength(_ba_str)) + 2 * s, horizonta_len - 8 * s) if _ba_str else 0
            _ab_done = game_data.get('current_at_bat_complete', False)
            if _ab_done and not _is_game_effectively_over(game_data):
                _next_hitter = _format_player_name(game_data.get('due_up') or game_data.get('next_batter_1') or '')
                if _next_hitter:
                    _next_str, _next_font = fit_text(f'AB: {_next_hitter}', max(1, max_text_width - _ba_w))
                    draw.text((start_x + 2 * s, start_y + 25 * s + 89 * s), _next_str, font=_next_font, fill=0)
            else:
                # Prefer current_play_batter (from currentPlay.matchup) over current_hitter
                # (from linescore.offense.batter) — both fields update when the at-bat changes,
                # but linescore can lag by one poll cycle, causing the AB label to briefly flip
                # back to the previous batter.
                _hitter_name = _format_player_name(
                    game_data.get('current_play_batter') or game_data.get('current_hitter') or ''
                )
                hitter_str, hitter_font = fit_text(
                    f'AB: {_hitter_name}',
                    max(1, max_text_width - _ba_w),
                )
                draw.text((start_x + 2 * s, start_y + 25 * s + 89 * s), hitter_str, font=hitter_font, fill=0)
            if _ba_str:
                draw.text((start_x + horizonta_len - _ba_w, start_y + 25 * s + 89 * s), _ba_str, font=font11, fill=0)

    if game_data['detailed_state'] in ('Final', 'Game Over', 'Final: Tied', 'Postponed', 'Delayed'):
        # Normalize display labels
        if game_data['detailed_state'] == 'Game Over':
            game_state_str = 'Final'
        elif game_data['detailed_state'] == 'Final: Tied':
            game_state_str = 'Tied'
        elif game_data['detailed_state'] == 'Delayed':
            # Show inning when the delay happened mid-game (e.g. "DLY 5"); just "Delay" pre-game
            _dly_inn = game_data.get('current_inning') or 0
            game_state_str = f'DLY {_dly_inn}' if _dly_inn > 0 else 'Delay'
        else:
            game_state_str = game_data['detailed_state']

        # Catch tied games the API marks as plain "Final" (spring training, international)
        if game_state_str == 'Final':
            _ar = game_data.get('away_runs') or 0
            _hr = game_data.get('home_runs') or 0
            if _ar == _hr:
                game_state_str = 'Tied'

        if game_data['detailed_state'] not in ('Delayed', 'Postponed'):
            _fin_inning = game_data.get('current_inning') or 9
            if _fin_inning > 9:
                game_state_str = 'F/' + str(_fin_inning)
            elif _fin_inning != 9 and game_state_str not in ('Tied',):
                game_state_str += '/' + str(_fin_inning)

    elif game_data['detailed_state'] == 'Warmup':
        game_state_str = game_data['detailed_state']

    elif game_data['detailed_state'] in ('Scheduled', 'Pre-Game'):
        try:
            from datetime import datetime
            dt = datetime.strptime(game_data['game_start'], "%Y-%m-%dT%H:%M:%SZ")
            game_state_str = dt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            game_state_str = game_data['game_start']
    elif game_data['detailed_state'] in ('Suspended', 'Cancelled', 'Cancelled: Rain'):
        game_state_str = 'Susp' if game_data['detailed_state'] == 'Suspended' else 'Canc'
        _inn = game_data.get('current_inning')
        if _inn:
            _susp_half = {'Top': 'Top', 'Bottom': 'Bot', 'Middle': 'Mid', 'End': 'End'}.get(
                game_data.get('inningState') or '', '')
            game_state_str += f' {_susp_half} {_inn}' if _susp_half else f' {_inn}'
    else:
        # In Progress (and any other live state not matched above)
        _inn_state = game_data.get('inningState') or ''
        _inn_label = {'Top': 'Top', 'Bottom': 'Bot', 'Middle': 'Mid', 'End': 'End'}.get(_inn_state, _inn_state[:3].capitalize() if _inn_state else '')
        _inn_ord_raw = game_data.get('currentInningOrdinal') or str(game_data.get('current_inning') or 1)
        _inn_ord = _re.sub(r'(?:st|nd|rd|th)$', '', _inn_ord_raw, flags=_re.IGNORECASE)
        game_state_str = (f'{_inn_label} {_inn_ord}').strip()

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
        draw.text((start_x + _sw_x,         start_y + _sw_y), _sw_text, font=font18, fill=0)
        draw.text((start_x + _sw_x + 1 * s, start_y + _sw_y), _sw_text, font=font18, fill=0)
    elif _is_walkoff:
        # Walkoff replaces the header duration (which moves between the team
        # rows below, mirroring the SWEEP layout) — font14 (not font18, like
        # SWEEP) so the wider word doesn't collide with the "Final" label.
        _wo_text = 'WALKOFF'
        _wo_w    = int(font14.getlength(_wo_text))
        _wo_x    = (horizonta_len - _wo_w) // 2
        _wo_y    = 3 * s
        draw.text((start_x + _wo_x,         start_y + _wo_y), _wo_text, font=font14, fill=0)
        draw.text((start_x + _wo_x + 1 * s, start_y + _wo_y), _wo_text, font=font14, fill=0)
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
    _game_is_final = game_data.get('detailed_state') in ('Final', 'Game Over', 'Final: Tied')
    _active_no_no = (
        game_data['detailed_state'] == 'In Progress' and
        (game_data.get('no_hitter') or game_data.get('perfect_game')) and
        (game_data.get('current_inning') or 0) >= 6
    )
    _ser_total = (game_data.get('series_total_games') or 1)
    _sw_wins   = game_data.get('series_wins', 0) or 0
    _sw_losses = game_data.get('series_losses', 0) or 0
    _sw_desc   = game_data.get('series_description', '')
    _sw_one_side_won = (_sw_losses == 0 or _sw_wins == 0)
    _is_sweep = (
        _game_is_final and
        _ser_total > 1 and
        _sw_one_side_won and
        (
            (_sw_desc == 'Regular Season' and (_sw_wins + _sw_losses) == _ser_total) or
            (_sw_desc != 'Regular Season' and bool(game_data.get('series_is_over')))
        )
    )
    _series_clinched = (
        _game_is_final and
        _ser_total > 1 and
        game_data.get('series_is_over') and
        not _is_sweep
    )
    _series_tied = (
        _game_is_final and
        _ser_total > 1 and
        game_data.get('series_is_tied') and
        not game_data.get('series_is_over')
    )
    _series_leading = (
        _game_is_final and
        _ser_total > 1 and
        not game_data.get('series_is_over') and
        not game_data.get('series_is_tied') and
        (game_data.get('series_wins') or 0) > 0
    )

    # Overline when the full series has concluded.
    # Regular Season: all scheduled games must have been played (wins+losses == total).
    # Playoffs: series_is_over is sufficient (series ends before all games are needed).
    _show_overline = (
        _game_is_final and
        _ser_total > 1 and
        (
            (_sw_desc == 'Regular Season' and (_sw_wins + _sw_losses) == _ser_total) or
            (_sw_desc != 'Regular Season' and bool(game_data.get('series_is_over')))
        )
    )

    # _ser_content_left_x tracks left edge of series/broom content for G:X:XX positioning
    _ser_content_left_x = start_x + horizonta_len - 2 * s

    if _is_sweep or _series_clinched:
        # Series win: draw winner logo + series score (e.g. 3-1)
        _sw = game_data.get('series_wins') or 0
        _sl = game_data.get('series_losses') or 0
        _score_str = f'{_sw}-{_sl}'
        _score_w = int(font14.getlength(_score_str))
        _ser_logo_size = 14 * s
        # Determine series winner from series_result (e.g. "NYY wins 2-1")
        _ser_winner_abbr = _ser_winner_id = None
        _ser_result_sw = game_data.get('series_result', '')
        _ser_result_sw_parts = _ser_result_sw.split()
        if len(_ser_result_sw_parts) >= 2 and _ser_result_sw_parts[1] == 'wins':
            _leading_sw = _ser_result_sw_parts[0].upper()
            if _leading_sw == away_team_name.upper():
                _ser_winner_abbr, _ser_winner_id = away_team_name, str(game_data['away_team_id'])
            elif _leading_sw == home_team_name.upper():
                _ser_winner_abbr, _ser_winner_id = home_team_name, str(game_data['home_team_id'])
        if not _ser_winner_abbr:
            if game_data.get('away_team_is_winner'):
                _ser_winner_abbr, _ser_winner_id = away_team_name, str(game_data['away_team_id'])
            elif game_data.get('home_team_is_winner'):
                _ser_winner_abbr, _ser_winner_id = home_team_name, str(game_data['home_team_id'])
        _ser_logo = _logo_small(_ser_winner_abbr, _ser_winner_id, size=_ser_logo_size) if _ser_winner_abbr else None
        _rx = start_x + horizonta_len - 2 * s
        if _ser_logo:
            _logo_w, _logo_h = _ser_logo.size
            _score_x = _rx - _score_w
            _logo_x = _score_x - 2 * s - _logo_w
            _logo_y = start_y + (20 * s - _logo_h) // 2
            Himage.paste(_ser_logo, (_logo_x, _logo_y))
            draw = ImageDraw.Draw(Himage)
            _ser_content_left_x = _logo_x
        else:
            _score_x = _rx - _score_w
            _ser_content_left_x = _score_x
        draw.text((_score_x,         start_y + 3 * s), _score_str, font=font14, fill=0)
        draw.text((_score_x + 1 * s, start_y + 3 * s), _score_str, font=font14, fill=0)
        if _show_overline:
            draw.line((_score_x, start_y + 3 * s, _score_x + _score_w, start_y + 3 * s), fill=0, width=2)

    elif _series_tied:
        _sw = game_data.get('series_wins') or 0
        _sl = game_data.get('series_losses') or 0
        _tied_str = f'{_sw}-{_sl}'
        _tied_w = int(font14.getlength(_tied_str))
        _rx = start_x + horizonta_len - 2 * s
        _tx = _rx - _tied_w
        _ser_content_left_x = _tx
        draw.text((_tx,         start_y + 3 * s), _tied_str, font=font14, fill=0)
        draw.text((_tx + 1 * s, start_y + 3 * s), _tied_str, font=font14, fill=0)
        if _show_overline:
            draw.line((_tx, start_y + 3 * s, _tx + _tied_w, start_y + 3 * s), fill=0, width=2)

    elif _series_leading:
        # Series leader: draw leading team's logo + score (e.g. [NYY logo] 1-0)
        _sw = game_data.get('series_wins') or 0
        _sl = game_data.get('series_losses') or 0
        _score_str = f'{_sw}-{_sl}'
        _score_w = int(font14.getlength(_score_str))
        _ser_logo_size = 14 * s
        _ser_leader_abbr = _ser_leader_id = None
        _ser_result = game_data.get('series_result', '')
        _ser_result_parts = _ser_result.split()
        if len(_ser_result_parts) >= 2 and _ser_result_parts[1] == 'wins':
            _leading = _ser_result_parts[0].upper()
            if _leading == away_team_name.upper():
                _ser_leader_abbr, _ser_leader_id = away_team_name, str(game_data['away_team_id'])
            elif _leading == home_team_name.upper():
                _ser_leader_abbr, _ser_leader_id = home_team_name, str(game_data['home_team_id'])
        if not _ser_leader_abbr:
            if game_data.get('away_team_is_winner'):
                _ser_leader_abbr, _ser_leader_id = away_team_name, str(game_data['away_team_id'])
            elif game_data.get('home_team_is_winner'):
                _ser_leader_abbr, _ser_leader_id = home_team_name, str(game_data['home_team_id'])
        _ser_logo = _logo_small(_ser_leader_abbr, _ser_leader_id, size=_ser_logo_size) if _ser_leader_abbr else None
        _rx = start_x + horizonta_len - 2 * s
        if _ser_logo:
            _logo_w, _logo_h = _ser_logo.size
            _score_x = _rx - _score_w
            _logo_x = _score_x - 2 * s - _logo_w
            _logo_y = start_y + (20 * s - _logo_h) // 2
            Himage.paste(_ser_logo, (_logo_x, _logo_y))
            draw = ImageDraw.Draw(Himage)
            _ser_content_left_x = _logo_x
        else:
            _score_x = _rx - _score_w
            _ser_content_left_x = _score_x
        draw.text((_score_x, start_y + 3 * s), _score_str, font=font14, fill=0)
        if _show_overline:
            draw.line((_score_x, start_y + 3 * s, _score_x + _score_w, start_y + 3 * s), fill=0, width=2)

    # Series context in header for postponed games
    if game_data['detailed_state'] == 'Postponed' and (game_data.get('series_total_games') or 1) > 1:
        _ppd_sr = game_data.get('series_result') or ''
        _ppd_parts = _ppd_sr.split()
        _ppd_is_tied = 'tied' in _ppd_sr.lower()
        _ppd_sw = game_data.get('series_wins') or 0
        _ppd_sl = game_data.get('series_losses') or 0
        _rx = start_x + horizonta_len - 2 * s

        if (_ppd_sw + _ppd_sl) == 0:
            # Series hasn't started (or API returned stale 0-0 data for a mid-series PPD).
            # Don't show "0/X" — the count is unreliable; teams may have played yesterday.
            pass
        elif not _ppd_is_tied and len(_ppd_parts) >= 3 and _ppd_parts[1] == 'leads':
            _ppd_score = _ppd_parts[2]
            _ppd_leader_str = _ppd_parts[0].upper()
            _ppd_logo_abbr = _ppd_logo_id = None
            if _ppd_leader_str == away_team_name.upper():
                _ppd_logo_abbr, _ppd_logo_id = away_team_name, str(game_data['away_team_id'])
            elif _ppd_leader_str == home_team_name.upper():
                _ppd_logo_abbr, _ppd_logo_id = home_team_name, str(game_data['home_team_id'])
            _ppd_score_w = int(font11.getlength(_ppd_score))
            _ppd_score_x = _rx - _ppd_score_w
            draw.text((_ppd_score_x, start_y + 5 * s), _ppd_score, font=font11, fill=0)
            _ser_content_left_x = _ppd_score_x
            if _ppd_logo_abbr:
                _ppd_logo = _logo_small(_ppd_logo_abbr, _ppd_logo_id, size=14 * s)
                if _ppd_logo:
                    _lw, _lh = _ppd_logo.size
                    _ppd_logo_x = _ppd_score_x - 2 * s - _lw
                    _ppd_logo_y = start_y + (20 * s - _lh) // 2
                    Himage.paste(_ppd_logo, (_ppd_logo_x, _ppd_logo_y))
                    draw = ImageDraw.Draw(Himage)
                    _ser_content_left_x = _ppd_logo_x

    # Venue — right-anchored in header, as large as possible without overlapping the time.
    # Always shown for a scheduled game, including doubleheaders: "Game N" now
    # lives in the corner spot below (see _dh_scheduled block near the duration
    # code) instead of the header, so it no longer collides with the venue.
    if game_data['detailed_state'] in ('Scheduled', 'Pre-Game', 'Warmup'):
        venue_clean = _clean_venue_name(game_data.get('venue'))
        if venue_clean:
            try:
                _venue_right = _ser_content_left_x - 2 * s
                max_venue_w = max(_venue_right - start_x - _total_time_w - 6 * s, 0)
                if max_venue_w > 0:
                    for vfont, vy in ((_get_font(16 * s), 2 * s), (font14, 3 * s), (font11, 4 * s), (font9, 5 * s), (_get_font(8 * s), 6 * s)):  # noqa: B007 (vy used after break)
                        if vfont.getlength(venue_clean) <= max_venue_w:
                            break
                    vw = int(vfont.getlength(venue_clean))
                    vx = _venue_right - vw
                    draw.text((vx,         start_y + vy), venue_clean, font=vfont, fill=0)
                    draw.text((vx + 1 * s, start_y + vy), venue_clean, font=vfont, fill=0)  # bold
            except AttributeError:  # pragma: no cover
                pass
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
            """Draw play right."""
            if not text:  # pragma: no cover
                return
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
                    draw.text((_px,         _py), _t, font=_fnt, fill=0)
                    draw.text((_px + 1 * s, _py), _t, font=_fnt, fill=0)
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

        if hide_last_play:
            # Wide cell: events live in the spanning header, not the left cell.
            pass
        elif _active_no_no:
            # Right-align label; inning state stays on left as-is
            _nh_label = 'Perfect Game' if game_data.get('perfect_game') else 'No-Hitter'
            _nh_lw = int(font14.getlength(_nh_label))
            _nh_lx = _header_right - _nh_lw
            draw.text((_nh_lx,         start_y + 3 * s), _nh_label, font=font14, fill=0)
            draw.text((_nh_lx + 1 * s, start_y + 3 * s), _nh_label, font=font14, fill=0)
        elif _pitching_change:
            _draw_play_right('Mid PC' if _mid_inning_pc else 'P.CHG')
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
                    draw.text((_due_x,         start_y + 5 * s), _due_str, font=_due_fnt, fill=0)
                    draw.text((_due_x + 1 * s, start_y + 5 * s), _due_str, font=_due_fnt, fill=0)
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
                draw.text((_tx,         start_y + 4 * s), play_display, font=_fnt, fill=0)
                draw.text((_tx + 1 * s, start_y + 4 * s), play_display, font=_fnt, fill=0)
            else:
                _draw_play_right(f'{play_display} {_challenge_abbr}'.strip())
        elif play_display:
            _draw_play_right(play_display)

    if _delayed_with_score:
        _delay_reason = game_data.get('postpone_reason') or ''
        if _delay_reason:
            _delay_str = f'R: {_delay_reason}'
            _max_delay_w = max(horizonta_len - _total_time_w - 10 * s, 0)
            _delay_fnt = _get_font(12 * s)
            while len(_delay_str) > 1 and int(_delay_fnt.getlength(_delay_str)) > _max_delay_w:
                _delay_str = _delay_str[:-2] + '.'
            if _delay_str and int(_delay_fnt.getlength(_delay_str)) <= _max_delay_w:
                _dw = int(_delay_fnt.getlength(_delay_str))
                _dx_pos = start_x + horizonta_len - _dw - 2 * s
                draw.text((_dx_pos,         start_y + 4 * s), _delay_str, font=_delay_fnt, fill=0)
                draw.text((_dx_pos + 1 * s, start_y + 4 * s), _delay_str, font=_delay_fnt, fill=0)

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
            draw.text((rx,         y_pos), main_txt, font=font14, fill=0)
            draw.text((rx + 1 * s, y_pos), main_txt, font=font14, fill=0)

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

        _draw_record(_away_wins, _away_losses, game_data.get("away_team_id"), start_y + 25 * s)
        _draw_record(_home_wins, _home_losses, game_data.get("home_team_id"), start_y + 55 * s)

        # Betting moneylines — right-aligned just left of each team's record (not on postponed)
        _away_ml = game_data.get('away_ml')
        _home_ml = game_data.get('home_ml')
        if _away_ml is not None and _home_ml is not None and game_data['detailed_state'] != 'Postponed':
            _away_rec_left = start_x + horizonta_len - int(font14.getlength(f'{_away_wins}-{_away_losses}')) - 5 * s
            _home_rec_left = start_x + horizonta_len - int(font14.getlength(f'{_home_wins}-{_home_losses}')) - 5 * s
            _odds_right = min(_away_rec_left, _home_rec_left) - 4 * s

            def _ml_str(v):
                """Ml str."""
                return f'+{v}' if v > 0 else str(v)

            _aml_s = _ml_str(_away_ml)
            _hml_s = _ml_str(_home_ml)
            # Pixel-align font11 odds with the font14 abbreviation.
            # Measured glyph centres: font14 bbox top=4 bottom=14 → centre=+9 from draw_y.
            #                         font11 bbox top=3 bottom=11 → centre=+7 from draw_y.
            # font14 abbr draw_y (with logos) = start_y + 25 + (28-14)//2 = start_y + 32.
            # To share that glyph centre: font11 draw_y = abbr_draw_y + (9-7) = abbr_draw_y + 2.
            _abbr_draw_y_away = start_y + 25 * s + ((28 * s - 14 * s) // 2 if use_logos else 0)
            _abbr_draw_y_home = start_y + 55 * s + ((28 * s - 14 * s) // 2 if use_logos else 0)
            _away_odds_y = _abbr_draw_y_away + 2 * s
            _home_odds_y = _abbr_draw_y_home + 2 * s
            # Left-align both strings from the same x so +/- signs are column-aligned.
            _odds_x = _odds_right - max(int(font11.getlength(_aml_s)), int(font11.getlength(_hml_s)))
            draw.text((_odds_x, _away_odds_y), _aml_s, font=font11, fill=0)
            draw.text((_odds_x, _home_odds_y), _hml_s, font=font11, fill=0)

        _is_ppd = game_data['detailed_state'] == 'Postponed'
        _draw_weather_footer(draw, start_x, start_y, horizonta_len, game_data, font14, show_tv=not _is_ppd, scale=s)

    # Game duration — header for non-sweep/non-walkoff finals (GM+duration centred
    # together for DH); between team rows for sweep or walkoff (GM placed immediately
    # right of duration), since the header text slot is occupied by SWEEP/WALKOFF.
    _sweep_dur_right_x  = None   # right edge of sweep/walkoff duration; GM uses this for x
    _gm_drawn_in_header = False  # True once GM was already rendered inside this block
    if _game_is_final and not game_data.get('perfect_game') and not game_data.get('no_hitter'):
        _dur_mins = game_data.get('game_duration_minutes')
        if _dur_mins:
            _dur_str = f'{_dur_mins // 60}:{_dur_mins % 60:02d}'
            if _is_sweep or _is_walkoff:
                _dur_font = font9
                _dur_x = start_x + logo_x_offset + 28 * s + 2 * s + 3 * s if use_logos else start_x + 8 * s
                _dur_y = start_y + 50 * s
                _sweep_dur_right_x = _dur_x + int(_dur_font.getlength(_dur_str))
                draw.text((_dur_x,         _dur_y), _dur_str, font=_dur_font, fill=0)
                draw.text((_dur_x + 1 * s, _dur_y), _dur_str, font=_dur_font, fill=0)
            elif _dh_is_active:
                # DH non-sweep/non-walkoff Final: duration moves to the same small
                # corner spot a walkoff uses (freeing the header), and "Game N" is
                # centered alone in the header, same as the walkoff/scheduled slot.
                _dur_font = font9
                _dur_x = start_x + logo_x_offset + 28 * s + 2 * s + 3 * s if use_logos else start_x + 8 * s
                _dur_y = start_y + 50 * s
                draw.text((_dur_x,         _dur_y), _dur_str, font=_dur_font, fill=0)
                draw.text((_dur_x + 1 * s, _dur_y), _dur_str, font=_dur_font, fill=0)
                _gn_str_h = f'Game {_gnum}'
                _gn_w     = int(font14.getlength(_gn_str_h))
                _gn_x     = start_x + horizonta_len // 2 - _gn_w // 2
                _hdr_y    = start_y + 3 * s
                draw.text((_gn_x,         _hdr_y), _gn_str_h, font=font14, fill=0)
                draw.text((_gn_x + 1 * s, _hdr_y), _gn_str_h, font=font14, fill=0)
                _gm_drawn_in_header = True
            else:
                # Non-DH: centre duration alone
                _dur_font = font14
                _dur_x = start_x + horizonta_len // 2 - int(_dur_font.getlength(_dur_str)) // 2
                _dur_y = start_y + 3 * s
                draw.text((_dur_x,         _dur_y), _dur_str, font=_dur_font, fill=0)
                draw.text((_dur_x + 1 * s, _dur_y), _dur_str, font=_dur_font, fill=0)

    # End time — right-aligned in the win-probability strip below the box.
    # Default: shown only while the linescore window is active (disappears with the linescore).
    # Set show_game_end_time_always: true in config to keep it visible after the window closes.
    _et_cfg = load_yaml_file('config.yaml')
    _show_end_time_always = _et_cfg.get('show_game_end_time_always', False)
    if _game_is_final and (_in_linescore_window or _show_end_time_always) and _end_utc_str:
        try:
            _tz_str = _et_cfg.get('timezone', 'America/Chicago')
            _end_utc_parsed = pytz.utc.localize(_datetime.strptime(_end_utc_str[:19], "%Y-%m-%dT%H:%M:%S"))
            _end_local = _end_utc_parsed.astimezone(pytz.timezone(_tz_str))
            _end_str = _end_local.strftime("%I:%M").lstrip("0") + " " + _end_local.strftime("%p").lower()
            _et_strip_y = start_y + vertical_len + 21 * s  # same y as win-prob bar
            _et_strip_h = 19 * s
            _et_w = int(font14.getlength(_end_str))
            _et_x = start_x + horizonta_len - _et_w - 1 * s
            _et_y = _et_strip_y + (_et_strip_h - 14 * s) // 2
            draw.text((_et_x,         _et_y), _end_str, font=font14, fill=0)
            draw.text((_et_x + 1 * s, _et_y), _end_str, font=font14, fill=0)
        except Exception:  # pragma: no cover
            pass

    # Doubleheader game number, not-yet-started game: same small corner spot the
    # moved duration uses for sweep/walkoff finals, freeing the header for venue.
    if _dh_scheduled:
        _gm_pre_text = f'Game {_gnum}'
        _gm_pre_x = start_x + logo_x_offset + 28 * s + 2 * s + 3 * s if use_logos else start_x + 8 * s
        _gm_pre_y = start_y + 50 * s
        draw.text((_gm_pre_x,         _gm_pre_y), _gm_pre_text, font=font9, fill=0)
        draw.text((_gm_pre_x + 1 * s, _gm_pre_y), _gm_pre_text, font=font9, fill=0)

    # Doubleheader game number — in header for non-sweep/non-walkoff finals; beside the
    # moved duration for sweeps/walkoffs. Not-yet-started DH games are handled just
    # above ("Game N" in the corner spot), so they're excluded here.
    _dh_state = game_data['detailed_state'] in (
        'Final', 'Game Over', 'Final: Tied', 'Postponed')
    if _dh_is_active and _dh_state:
        _gn_str = f'GM{_gnum}'
        if (_is_sweep or _is_walkoff) and _sweep_dur_right_x is not None:
            # Sweep/Walkoff Final: GM immediately right of the moved duration (font9, +50 row)
            _gn_x = _sweep_dur_right_x + 3 * s
            _gn_y = start_y + 50 * s
            draw.text((_gn_x,         _gn_y), _gn_str, font=font9, fill=0)
            draw.text((_gn_x + 1 * s, _gn_y), _gn_str, font=font9, fill=0)
        elif not _gm_drawn_in_header:
            # Non-Final DH (Scheduled / Pre-Game / Warmup / Postponed) or no duration:
            # centre GM alone in the header
            _gn_w = int(font14.getlength(_gn_str))
            _gn_x = start_x + horizonta_len // 2 - _gn_w // 2
            _gn_y = start_y + 3 * s
            draw.text((_gn_x,         _gn_y), _gn_str, font=font14, fill=0)
            draw.text((_gn_x + 1 * s, _gn_y), _gn_str, font=font14, fill=0)
        # else: GM already drawn together with duration above — nothing to do

    # ABS challenges remaining — small stacked dots to the left of each team's logo
    if game_data['detailed_state'] == 'In Progress':
        _draw_challenge_dots(draw, start_x, start_y, game_data, use_logos=use_logos, logo_x_offset=logo_x_offset, scale=s)

    # top border + header separator
    end_x = start_x + horizonta_len
    end_y = start_y
    draw.line((start_x, start_y, end_x, start_y), fill=0)
    draw.line((start_x, start_y + 20 * s, end_x, end_y + 20 * s), fill=0)

    # Win probability bar — live games only, when show_win_prob enabled
    # Win prob bar — all In Progress states including between-inning breaks
    if show_win_prob and game_data['detailed_state'] == 'In Progress':
        away_wp = game_data.get('away_win_probability')
        home_wp = game_data.get('home_win_probability')
        if away_wp is not None and home_wp is not None:
            try:
                away_wp = float(away_wp)
                home_wp = float(home_wp)
                if away_wp + home_wp <= 1.5:
                    away_wp *= 100
                    home_wp *= 100
            except (ValueError, TypeError):
                away_wp, home_wp = 50.0, 50.0

            LOGO_SZ = 18 * s
            BAR_Y = start_y + vertical_len + 21 * s  # 1px below bottom border, in the inter-row gap
            BAR_H = 19 * s                            # available inter-row height
            BAR_X = start_x + 1 * s
            BAR_W = horizonta_len - 2 * s

            # Ghost "LOSS" / "WIN" watermarks, then a solid horizontal center line
            _ghost_strip = Image.new('L', (BAR_W, BAR_H), 255)
            _ghost_draw = ImageDraw.Draw(_ghost_strip)
            _ghost_draw.text((1 * s, (BAR_H - 18 * s) // 2), 'LOSS', font=font18, fill=0)
            _win_w = int(font18.getlength('WIN'))
            _ghost_draw.text((BAR_W - _win_w - 1 * s, (BAR_H - 18 * s) // 2), 'WIN', font=font18, fill=0)
            _ghost_strip = _ghost_strip.point(lambda p: 255 if p > 180 else min(255, int(p * 0.35 + 155)))
            # Solid center line drawn after ghost transform so it stays black
            _ghost_draw.line((0, BAR_H // 2, BAR_W, BAR_H // 2), fill=0)
            Himage.paste(_ghost_strip.convert('1'), (BAR_X, BAR_Y))
            draw = ImageDraw.Draw(Himage)

            away_px = BAR_X + int(BAR_W * away_wp / 100.0)
            away_logo_x = max(BAR_X, min(BAR_X + BAR_W - LOGO_SZ, away_px - LOGO_SZ // 2))

            home_px = BAR_X + int(BAR_W * home_wp / 100.0)
            home_logo_x = max(BAR_X, min(BAR_X + BAR_W - LOGO_SZ, home_px - LOGO_SZ // 2))

            # Prevent logos from overlapping each other
            MIN_SEP = LOGO_SZ + 1 * s
            if away_logo_x > home_logo_x:
                if away_logo_x - home_logo_x < MIN_SEP:
                    mid = (away_logo_x + home_logo_x) // 2
                    away_logo_x = min(BAR_X + BAR_W - LOGO_SZ, mid + MIN_SEP // 2)
                    home_logo_x = max(BAR_X, mid - MIN_SEP // 2)
            else:
                if home_logo_x - away_logo_x < MIN_SEP:
                    mid = (away_logo_x + home_logo_x) // 2
                    home_logo_x = min(BAR_X + BAR_W - LOGO_SZ, mid + MIN_SEP // 2)
                    away_logo_x = max(BAR_X, mid - MIN_SEP // 2)

            if use_logos:
                away_logo = _logo_small(away_team_name, away_team_id, size=LOGO_SZ)
                home_logo = _logo_small(home_team_name, home_team_id, size=LOGO_SZ)
                if away_logo:
                    _paste_logo(Himage, away_logo, (away_logo_x, BAR_Y + (BAR_H - away_logo.size[1]) // 2))
                if home_logo:
                    _paste_logo(Himage, home_logo, (home_logo_x, BAR_Y + (BAR_H - home_logo.size[1]) // 2))

                # During inning breaks, draw each team's % in the AB area
                # directly above their logo position in the bar
            else:
                draw.line((away_px, BAR_Y, away_px, BAR_Y + BAR_H), fill=0)
                draw.line((home_px, BAR_Y, home_px, BAR_Y + BAR_H), fill=0)

    end_x = start_x + horizonta_len
    end_y = start_y + vertical_len + 20 * s
    draw.line((start_x, start_y + vertical_len + 20 * s, end_x, end_y), fill=0)

    # Next game preview — shown in the win-prob strip for Final games after final_linescore_minutes expires
    if _game_is_final and not _historical_mode:
        _window_expired = False
        _end_time_resolved = False
        if _end_utc_str:
            try:
                _end_utc = pytz.utc.localize(_datetime.strptime(_end_utc_str[:19], '%Y-%m-%dT%H:%M:%S'))
                _window_expired = (_datetime.now(pytz.utc) - _end_utc).total_seconds() >= _FINAL_LINESCORE_SECS
                _end_time_resolved = True  # authoritative — skip all fallbacks
            except Exception:
                pass
        if not _end_time_resolved:
            # No precise UTC end time — use game_date (local date) or first-seen timestamp.
            # game_date is in local time so compare in local tz, not UTC, to avoid false
            # expiry for evening games that cross midnight UTC.
            try:
                _cfg2 = load_yaml_file('config.yaml')
                _tz_str2 = _cfg2.get('timezone', 'America/Chicago')
                _today_local = _datetime.now(pytz.timezone(_tz_str2)).strftime('%Y-%m-%d')
            except Exception:  # pragma: no cover
                _today_local = _datetime.now(pytz.utc).strftime('%Y-%m-%d')
            _gd_prefix = (game_data.get('game_date') or '')[:10]
            if _gd_prefix and _gd_prefix < _today_local:
                _window_expired = True
            else:
                _fts = _get_or_set_final_time(game_data.get('game_pk'))
                _window_expired = (_time.time() - _fts) >= _FINAL_LINESCORE_SECS
        if _window_expired:
            _tmrw = _load_tomorrow_games()
            if _tmrw and _tmrw.get('games'):
                # GM label is now in the header, so the full strip width is available.
                _draw_next_game_preview(
                    draw, Himage, start_x, start_y, _tmrw['games'],
                    game_data.get('home_team_id'), game_data.get('away_team_id'),
                    team_data, use_logos, horizonta_len, vertical_len, s,
                    left_offset=0,
                )

    # Next game preview — shown immediately for postponed games (game will not be played today)
    elif game_data['detailed_state'] == 'Postponed' and not _historical_mode:
        _tmrw = _load_tomorrow_games()
        if _tmrw and _tmrw.get('games'):
            _draw_next_game_preview(
                draw, Himage, start_x, start_y, _tmrw['games'],
                game_data.get('home_team_id'), game_data.get('away_team_id'),
                team_data, use_logos, horizonta_len, vertical_len, s,
                left_offset=0,
            )

    # vertical line
    end_x = start_x
    end_y = start_y + vertical_len  # noqa: F841
    # draw.line((start_x, start_y, end_x, end_y), fill = 0)

    end_x = start_x + horizonta_len
    end_y = start_y + vertical_len  # noqa: F841
    # draw.line((start_x + horizonta_len , start_y, end_x, end_y), fill = 0)


    # line down the middle
    # vert_start_x =  start_x + horizonta_len / 2
    # vert_start_y = start_y + 12
    # end_x = vert_start_x
    # end_y = vert_start_y + 85

    # draw.line((vert_start_x, vert_start_y, end_x, end_y), fill = 0)


    # Show bases/outs/count only once the game is actually in progress (first pitch thrown).
    # force_linescore (wide-cell mode) suppresses this block — the right panel handles live context.
    if game_data['detailed_state'] == 'In Progress' and not force_linescore:
        if _between_innings and _game_ending_state:
            pass  # end of 9th+ with a lead — linescore shown, no next-batters panel
        elif _between_innings:
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
        elif _pitching_change:
            # Mid-inning PC: bases + outs at normal positions, new pitcher name below.
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
                        _bnw = int(font9.getlength(_bnum)) if _bnum else 0
                        draw.text((_bcx - _bnw // 2, _bcy - 5 * s), _bnum, font=font9, fill=255)
            _pc_outs_list = [i + 1 <= _pc_outs for i in range(3)]
            Himage = draw_circle(Himage, (start_x + 97 * s,  start_y + 73 * s), 6 * s, _pc_outs_list[0], outline_width=2)
            Himage = draw_circle(Himage, (start_x + 111 * s, start_y + 73 * s), 6 * s, _pc_outs_list[1], outline_width=2)
            Himage = draw_circle(Himage, (start_x + 125 * s, start_y + 73 * s), 6 * s, _pc_outs_list[2], outline_width=2)
            draw = ImageDraw.Draw(Himage)
            # New pitcher name from sub_event
            _pc_name = (game_data.get('sub_event') or '')[3:].strip()
            if _pc_name:
                _right_x   = start_x + horizonta_len - 2 * s
                _left_x    = start_x + 88 * s
                _pc_name_w = _right_x - _left_x
                _pit_fnt   = font14
                if int(font14.getlength(_pc_name)) > _pc_name_w:
                    _pit_fnt = font11
                    if int(font11.getlength(_pc_name)) > _pc_name_w:
                        _pit_fnt = font9
                        while _pc_name and int(font9.getlength(_pc_name)) > _pc_name_w:
                            _pc_name = _pc_name[:-1]
                draw.text((_left_x, start_y + 83 * s), _pc_name, font=_pit_fnt, fill=0)
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
                        _bnw = int(font9.getlength(_bnum)) if _bnum else 0
                        draw.text((_bcx - _bnw // 2, _bcy - 5 * s), _bnum, font=font9, fill=255)

                outs_list = [None] * 3
                for i in range(1, 4):
                    outs_list[i-1] = i <= game_data['num_of_outs']
                Himage = draw_circle(Himage, (start_x + 97 * s,  start_y + 73 * s), 6 * s, outs_list[0], outline_width=2)
                Himage = draw_circle(Himage, (start_x + 111 * s, start_y + 73 * s), 6 * s, outs_list[1], outline_width=2)
                Himage = draw_circle(Himage, (start_x + 125 * s, start_y + 73 * s), 6 * s, outs_list[2], outline_width=2)

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
            draw.text((_sv_x,         start_y + 25 * s), 'SV', font=font9, fill=0)
            draw.text((_sv_x + 1 * s, start_y + 25 * s), 'SV', font=font9, fill=0)
    else:

        # Perfect game takes precedence over no-hitter display — right-aligned in header
        if game_data.get('perfect_game') or game_data.get('no_hitter'):
            _nh_label = 'Perfect Game' if game_data.get('perfect_game') else 'No-Hitter'
            _nh_lw = int(font14.getlength(_nh_label))
            _nh_lx = (_ser_content_left_x - 2 * s) - _nh_lw
            draw.text((_nh_lx,         start_y + 3 * s), _nh_label, font=font14, fill=0)
            draw.text((_nh_lx + 1 * s, start_y + 3 * s), _nh_label, font=font14, fill=0)



    # Team names / logos
    _LOGO_SIZE = 28 * s  # matches _logo_small default size
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
            draw.text((abbr_x,         abbr_y), away_team_name, font=font14, fill=0)
            draw.text((abbr_x + 1 * s, abbr_y), away_team_name, font=font14, fill=0)
        else:
            draw.text((start_x + 5 * s, start_y + 25 * s), away_team_name, font=font24, fill=0)
        if home_logo:
            lw, lh = home_logo.size
            lx = start_x + logo_x_offset + (_LOGO_SIZE - lw) // 2
            ly = start_y + 55 * s + (_LOGO_SIZE - lh) // 2
            _paste_logo(Himage, home_logo, (lx, ly))
            abbr_x = start_x + logo_x_offset + _LOGO_SIZE + 2 * s
            abbr_y = start_y + 55 * s + (_LOGO_SIZE - 14 * s) // 2
            draw.text((abbr_x,         abbr_y), home_team_name, font=font14, fill=0)
            draw.text((abbr_x + 1 * s, abbr_y), home_team_name, font=font14, fill=0)
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

    # Bold-offset score for winner (both modes)
    if game_data.get('away_team_is_winner'):
        draw.text((start_x + 69 * s + check_if_two_chars(away_runs), start_y + 25 * s), away_runs, font=font24, fill=0)
    if game_data.get('home_team_is_winner'):
        draw.text((start_x + 69 * s + check_if_two_chars(home_runs), start_y + 55 * s), home_runs, font=font24, fill=0)

    # Invert header to indicate a score change or run-scoring play during an active game
    _run_scored = game_data['detailed_state'] == 'In Progress' and not is_game_finished and int(game_data.get('last_play_rbi') or 0) > 0
    if (score_changed or _run_scored) and is_game_started and not is_game_finished and not _between_innings and not _pitching_change and not skip_header_invert:
        header_box = Himage.crop((start_x, start_y, start_x + horizonta_len + 1 * s, start_y + 21 * s))
        Himage.paste(ImageOps.invert(header_box.convert('L')).convert('1'), (start_x, start_y))

    # Invert header for stolen base events
    _lp_lower = (game_data.get('last_play') or '').lower()
    _sb_event = (
        game_data['detailed_state'] == 'In Progress' and not is_game_finished and not _between_innings and not _pitching_change and
        ('stolen base' in _lp_lower or _lp_lower == 'sb')
    )
    if _sb_event and not skip_header_invert:
        header_box = Himage.crop((start_x, start_y, start_x + horizonta_len + 1 * s, start_y + 21 * s))
        Himage.paste(ImageOps.invert(header_box.convert('L')).convert('1'), (start_x, start_y))

    # Invert header for special states: no-hitter (>= 6 innings), perfect game
    if (game_data.get('no_hitter') or game_data.get('perfect_game')) and \
       (is_game_finished or _active_no_no) and not skip_header_invert:
        header_box = Himage.crop((start_x, start_y, start_x + horizonta_len + 1 * s, start_y + 21 * s))
        Himage.paste(ImageOps.invert(header_box.convert('L')).convert('1'), (start_x, start_y))

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


def _draw_backward_k(Himage, x, y, font):
    """Paste a horizontally-mirrored K (looking strikeout) at (x, y)."""
    bbox = font.getbbox('K')
    w = max(bbox[2] - bbox[0] + 2, 4)
    h = max(bbox[3] - bbox[1] + 4, 8)
    tmp = Image.new('1', (w, h), 1)
    ImageDraw.Draw(tmp).text((-bbox[0] + 1, -bbox[1] + 1), 'K', font=font, fill=0)
    Himage.paste(tmp.transpose(Image.FLIP_LEFT_RIGHT), (int(x), int(y)))


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
    font11 = _get_font(11 * s)
    font9  = _get_font(9 * s)
    font7  = _get_font(max(7 * s, 7))

    state = game_data.get('detailed_state', '')
    _between_innings = game_data.get('inningState') in ('Middle', 'End')

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
    _inn_text = f"{_inn_label} {game_data.get('current_inning') or 1}".strip()
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
            draw.text((x,         y), seg, font=font12, fill=0)
            draw.text((x + 1 * s, y), seg, font=font12, fill=0)
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

    if state != 'In Progress':
        return

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
            sw = int(font7.getlength(seq_str))
            if filled:
                draw.ellipse(box, fill=0, outline=0)
                draw.text((bx - sw // 2, by - 4 * s), seq_str, font=font7, fill=255)
            else:
                draw.ellipse(box, fill=255, outline=0)
                draw.text((bx - sw // 2, by - 4 * s), seq_str, font=font7, fill=0)

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
                    _bnw = int(font9.getlength(_bnum)) if _bnum else 0
                    draw.text((_bcx - _bnw // 2, _bcy - 5 * s), _bnum, font=font9, fill=255)

        # ── Outs circles: left side, below bases ──────────────────────
        outs_list = [i + 1 <= _outs_count for i in range(3)]
        Himage = draw_circle(Himage, (rp_x + 18 * s, rp_y + 71 * s), 6 * s, outs_list[0], outline_width=2)
        Himage = draw_circle(Himage, (rp_x + 32 * s, rp_y + 71 * s), 6 * s, outs_list[1], outline_width=2)
        Himage = draw_circle(Himage, (rp_x + 46 * s, rp_y + 71 * s), 6 * s, outs_list[2], outline_width=2)
        draw = ImageDraw.Draw(Himage)

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
        _bat_max_w = rp_w - 4 * s
        for _nm in _batter_names:
            if _nm:
                _bat_str = _nm
                while _bat_str and int(font11.getlength(_bat_str)) > _bat_max_w:
                    _bat_str = _bat_str[:-1]
                if _bat_str:
                    draw.text((rp_x + 2 * s, _bat_y), _bat_str, font=font11, fill=0)
            _bat_y += 16 * s

    # ── Pitcher row (pushed below B/S indicators) ──────────────────────
    _py = rp_y + 107 * s
    _max_w = rp_w - 7 * s
    _pc = game_data.get('pitch_count')
    _ab_pc = game_data.get('at_bat_pitch_count') or 0
    _pt_last = game_data.get('last_pitch_type', '') or ''
    _lps = game_data.get('last_pitch_speed')
    _pitcher_name = _format_player_name(game_data.get('current_pitcher') or '')

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
    draw.text((rp_x + 5 * s, _py), _pit_str, font=_pf, fill=0)
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
            _batter_label = f'AB: {_hitter}'
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
        draw.text((_k_x,         _bl_y), _milestone_label, font=_k_font, fill=0)
        draw.text((_k_x + 1 * s, _bl_y), _milestone_label, font=_k_font, fill=0)
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
        header_box = Himage.crop((start_x, start_y, start_x + TOTAL_W, start_y + HEADER_H))
        Himage.paste(ImageOps.invert(header_box.convert('L')).convert('1'), (start_x, start_y))
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
        header_box = Himage.crop((start_x, start_y, start_x + TOTAL_W, start_y + HEADER_H))
        Himage.paste(ImageOps.invert(header_box.convert('L')).convert('1'), (start_x, start_y))

    return Himage


def _draw_rotated_text(Himage, center_xy, text, font, angle_deg, bounds=None, font_size=None):
    """Draw text rotated to lie along angle_deg (screen-space, atan2(dy,dx) convention),
    centered at center_xy. Used to align outfield wall distance labels with the fence.

    Renders at 4x scale and rotates with bicubic resampling before downsampling —
    rotating a tiny bitmap font directly (nearest-neighbor) produces illegible,
    blocky glyphs at these font sizes.

    bounds, if given, is (cx0, cy0, cx1, cy1) — the paste box is clamped to stay
    fully inside it, rather than clamping center_xy itself, so a centered label
    near an edge is pushed inward instead of spilling half off the edge.
    """
    SS = 4  # supersample factor
    ss_font = _get_font(font_size * SS) if font_size else font
    bbox = ss_font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad = 2 * SS
    txt_img = Image.new('L', (tw + pad * 2, th + pad * 2), 0)
    ImageDraw.Draw(txt_img).text((pad - bbox[0], pad - bbox[1]), text, font=ss_font, fill=255)
    rotated = txt_img.rotate(-angle_deg, expand=True, fillcolor=0, resample=Image.BICUBIC)
    rotated = rotated.resize((max(1, rotated.width // SS), max(1, rotated.height // SS)),
                              resample=Image.LANCZOS)
    # Threshold to pure black/white before pasting — Himage is mode '1' (bilevel),
    # and a grayscale mask with anti-aliased edges blends to near-invisible gray.
    rotated = rotated.point(lambda p: 255 if p > 80 else 0).convert('1')
    black_img = Image.new('1', rotated.size, 0)
    cx, cy = center_xy
    px = int(cx - rotated.width / 2)
    py = int(cy - rotated.height / 2)
    if bounds is not None:
        cx0, cy0, cx1, cy1 = bounds
        px = max(cx0, min(cx1 - rotated.width, px))
        py = max(cy0, min(cy1 - rotated.height, py))
    Himage.paste(black_img, (px, py), rotated)


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
    wall_poly = _field_get_polygon(venue) or _FIELD_FALLBACK_POLY
    infield_poly = (_field_get_infield_polygon(venue)
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
            (HX - hp + 1, hcy - hp),
            (HX + hp - 1, hcy - hp),
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

    # Fence distance markers: 5 points evenly spaced by angle from home plate
    # (mirrors real outfield wall signage — LF pole, two power-alley gaps, CF, RF pole)
    _wall_font_size = max(round(10 * s), 10)
    font_tiny = _get_font(_wall_font_size)
    thetas = [_math.atan2(x_ft, y_ft) for x_ft, y_ft in wall_poly]
    theta_lo, theta_hi = thetas[0], thetas[-1]
    n_markers = 5
    _label_offs = max(round(9 * s), 9)  # px to push label outside the fence arc
    for k in range(n_markers):
        target = theta_lo + (k / (n_markers - 1)) * (theta_hi - theta_lo)
        idx = min(range(len(thetas)), key=lambda i: abs(thetas[i] - target))
        x_ft, y_ft = wall_poly[idx]
        pt = wall_pts[idx]
        dist = round(_math.sqrt(x_ft**2 + y_ft**2))

        # Radial unit vector pointing away from home plate (i.e. into the stands).
        norm = _math.sqrt(x_ft**2 + y_ft**2) or 1
        ux, uy = x_ft / norm, y_ft / norm
        # Place label outside the wall: move in the outward radial direction in pixel space.
        # x-pixel and x-field share the same sign; y-pixel is inverted vs y-field.
        lx_c = int(pt[0] + ux * _label_offs)
        ly_c = int(pt[1] - uy * _label_offs)

        # Local wall angle at this point (screen-space), from the neighbouring
        # fence points, so the label's baseline runs parallel to the fence.
        i0, i1 = max(0, idx - 1), min(len(wall_pts) - 1, idx + 1)
        (nx0, ny0), (nx1, ny1) = wall_pts[i0], wall_pts[i1]
        wall_angle = _math.degrees(_math.atan2(ny1 - ny0, nx1 - nx0))
        # A wall segment has two equivalent directions 180° apart; pick the one
        # that keeps the label upright/readable instead of upside-down.
        if wall_angle > 90:
            wall_angle -= 180
        elif wall_angle < -90:
            wall_angle += 180

        _draw_rotated_text(Himage, (lx_c, ly_c), str(dist), font_tiny, wall_angle,
                            bounds=(_cx0, _cy0, _cx1, _cy1), font_size=_wall_font_size)

    # Batted-ball markers — last 7 balls put in play (fair or foul).
    # API hit coordinates: home plate ≈ (125, 200); scale ≈ 2 ft per unit.
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

    def _bezier_trajectory(p0x, p0y, p1x, p1y):
        mx_, my_ = (p0x + p1x) / 2, (p0y + p1y) / 2
        dx_, dy_ = p1x - p0x, p1y - p0y
        dist_ = _math.sqrt(dx_ ** 2 + dy_ ** 2) or 1
        ctrl_x = mx_ - dy_ / dist_ * dist_ * 0.15
        ctrl_y = my_ + dx_ / dist_ * dist_ * 0.15
        pts = []
        for i in range(13):
            t = i / 12
            pts.append(((1-t)**2 * p0x + 2*(1-t)*t * ctrl_x + t**2 * p1x,
                         (1-t)**2 * p0y + 2*(1-t)*t * ctrl_y + t**2 * p1y))
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i+1]], fill=0, width=1)

    # recent_hits is oldest-first; the last entry is the most recent play.
    most_recent_idx = len(recent_hits) - 1

    for idx, h in enumerate(recent_hits):
        hx_ft = (h['x'] - 125) * 2.0
        hy_ft = (200  - h['y']) * 2.0
        is_hr  = h.get('is_hr',  False)
        is_out = h.get('is_out', False)
        abbr   = h.get('abbr', 'HR' if is_hr else ('F' if is_out else '1B'))
        if is_hr:
            dist_ft = h.get('distance')
            if dist_ft is not None:
                abbr = f'HR {int(dist_ft)}'

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

        if idx == most_recent_idx:
            _bezier_trajectory(HX, HY, *land_pt)

        # Play abbreviation label (F, L, G, HR, 1B, 2B, 3B …) at the landing spot.
        # HR lands at the cell edge; keep text inside by clamping y.
        tw = max(int(font_tiny.getlength(abbr)), 1)
        _tx = max(_cx0, min(_cx1 - tw, land_pt[0] - tw // 2))
        _ty = max(_cy0 + 1, land_pt[1] - 9)
        draw.text((_tx, _ty), abbr, font=font_tiny, fill=0)

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

    # Invert spanning header when a run scored or score changed
    _between   = game_data.get('inningState') in ('Middle', 'End')
    _run_scored = (
        game_data.get('detailed_state') == 'In Progress'
        and int(game_data.get('last_play_rbi') or 0) > 0
    )
    if (score_changed or _run_scored) and not _between:
        header_box = Himage.crop((start_x, start_y, start_x + TOTAL_W, start_y + HEADER_H))
        Himage.paste(ImageOps.invert(header_box.convert('L')).convert('1'), (start_x, start_y))
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
        header_box = Himage.crop((start_x, start_y, start_x + TOTAL_W, start_y + HEADER_H))
        Himage.paste(ImageOps.invert(header_box.convert('L')).convert('1'), (start_x, start_y))

    return Himage
