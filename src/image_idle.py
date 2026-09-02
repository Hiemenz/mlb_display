"""Idle-screen renderer: shown when there are no games today.

Layout (800x480):
  Header (28px): "RECENT MOVES"
  Two equal transaction columns (each 398px wide, ~20 rows each → ~40 total)
  Mascot photo bounces over the full screen as an overlay

Also provides draw_history_screen() for the "on this date in history" rotation slot.
"""
import json
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageEnhance

from image_assets import _get_font, _load_logo_gray, _logo_small, _try_download_logo
from image_utils import TRANSACTION_TYPE_ABBR

_REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
_MASCOT_DIR = os.path.join(_REPO_ROOT, 'pic', 'mascots')

_HEADER_H    = 28      # height of the top header strip
_COL_DIV_X   = 400    # vertical divider between left and right transaction columns
_COL_W       = 398    # usable width of each column
_MASCOT_SIZE = 160    # mascot image dimension (smaller so it overlays cleanly)

# Bounce over the full screen
_BOUNCE_X_MIN = 0
_BOUNCE_X_MAX = 800 - _MASCOT_SIZE          # 640
_BOUNCE_Y_MIN = _HEADER_H + 2               # just below header
_BOUNCE_Y_MAX = 480 - _MASCOT_SIZE          # 320



# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def load_idle_state(data_dir):
    path = os.path.join(data_dir, 'idle_state.json')
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def save_idle_state(state, data_dir):
    path = os.path.join(data_dir, 'idle_state.json')
    os.makedirs(data_dir, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Mascot animation
# ---------------------------------------------------------------------------

def advance_mascot(state):
    """Advance mascot position one bounce-tick. Initialises on first call."""
    if 'mascot_x' not in state:
        state['mascot_x']  = float(random.randint(_BOUNCE_X_MIN, _BOUNCE_X_MAX))
        state['mascot_y']  = float(random.randint(_BOUNCE_Y_MIN, _BOUNCE_Y_MAX))
        state['mascot_dx'] = random.choice([-1, 1]) * random.uniform(18, 30)
        state['mascot_dy'] = random.choice([-1, 1]) * random.uniform(14, 26)

    x, y   = state['mascot_x'] + state['mascot_dx'], state['mascot_y'] + state['mascot_dy']
    dx, dy = state['mascot_dx'], state['mascot_dy']

    if x < _BOUNCE_X_MIN: x, dx = float(_BOUNCE_X_MIN),  abs(dx)
    elif x > _BOUNCE_X_MAX: x, dx = float(_BOUNCE_X_MAX), -abs(dx)
    if y < _BOUNCE_Y_MIN: y, dy = float(_BOUNCE_Y_MIN),  abs(dy)
    elif y > _BOUNCE_Y_MAX: y, dy = float(_BOUNCE_Y_MAX), -abs(dy)

    state.update(mascot_x=x, mascot_y=y, mascot_dx=dx, mascot_dy=dy)
    return state


# ---------------------------------------------------------------------------
# Mascot image loading
# ---------------------------------------------------------------------------

def _photo_to_1bit(gray, size):
    """Grayscale photo → 1-bit with gentle autocontrast + sharpen + F-S dither."""
    gray = gray.copy()
    gray.thumbnail((size, size), Image.LANCZOS)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = gray.filter(ImageFilter.SHARPEN)
    return gray.convert('1')


def _load_mascot_image(abbr, team_id, size):
    """1-bit mascot at `size`×`size`. Tries pic/mascots/ then falls back to logo."""
    mascot_path = os.path.join(_MASCOT_DIR, f'{abbr}.png')

    if os.path.exists(mascot_path):
        try:
            return _photo_to_1bit(Image.open(mascot_path).convert('L'), size)
        except Exception:
            pass

    if os.path.isdir(_MASCOT_DIR):
        try:
            from download_mascots import download_mascot
            if download_mascot(abbr):
                return _photo_to_1bit(Image.open(mascot_path).convert('L'), size)
        except Exception:
            pass

    # Fallback: team logo
    gray = _load_logo_gray(abbr, team_id)
    if gray is None:
        _try_download_logo(abbr, team_id)
        gray = _load_logo_gray(abbr, team_id)
    if gray is None:
        return None
    logo = gray.copy()
    logo.thumbnail((size, size), Image.LANCZOS)
    logo = ImageOps.autocontrast(logo, cutoff=2)
    logo = ImageEnhance.Contrast(logo).enhance(2.8)
    return logo.convert('1')


# ---------------------------------------------------------------------------
# Main renderer
# ---------------------------------------------------------------------------

def draw_idle_screen(transactions, team_data, idle_state, config):
    """Render the idle screen (800x480, mode '1').

    transactions : list of transaction dicts (from transactions.json)
    team_data    : {'team_abbreviation': {id: abbr, ...}}
    idle_state   : dict with mascot_x/y/dx/dy, mascot_abbr, mascot_team_id,
                   next_game_date
    config       : app config dict (dark_mode, use_team_logos, ...)
    """
    dark_mode = config.get('dark_mode', False)
    bg = 0 if dark_mode else 255
    fg = 255 if dark_mode else 0

    Himage = Image.new('1', (800, 480), bg)
    draw   = ImageDraw.Draw(Himage)

    # ── Header ────────────────────────────────────────────────────────────
    font_hdr = _get_font(18)
    draw.text((6, 5), 'RECENT MOVES', font=font_hdr, fill=fg)
    draw.text((7, 5), 'RECENT MOVES', font=font_hdr, fill=fg)   # bold stroke
    draw.line((0, _HEADER_H, 800, _HEADER_H), fill=fg)

    # ── Two transaction columns ───────────────────────────────────────────
    entries  = list(transactions or [])
    abbr_map = (team_data or {}).get('team_abbreviation', {})

    _PAD      = 4
    _AVAIL_H  = 480 - _HEADER_H - 2
    _ROW_H    = 22
    _MAX_ROWS = _AVAIL_H // _ROW_H           # rows per column (~20)
    _TOTAL    = _MAX_ROWS * 2                 # ~40 transactions shown

    font_row = _get_font(13)
    logo_sz  = 18
    abbr_sz  = 30

    # Measure the widest type tag across all shown entries
    tag_w = max(
        (int(font_row.getlength(TRANSACTION_TYPE_ABBR.get(e.get('type_desc', ''), e.get('type_desc', ''))))
         for e in entries[:_TOTAL]),
        default=44,
    )

    def _draw_column(col_entries, col_x_offset):
        """Render one column of transactions starting at col_x_offset."""
        logo_x = col_x_offset + _PAD
        abbr_x = logo_x + logo_sz + 3
        name_x = abbr_x + abbr_sz
        tag_x  = col_x_offset + _COL_W - tag_w - _PAD

        for i, entry in enumerate(col_entries):
            ry      = _HEADER_H + 2 + i * _ROW_H
            team_id = entry.get('team_id', '')
            abbr    = entry.get('team_abbr', '') or abbr_map.get(str(team_id), '')
            name    = entry.get('player_name', '')
            tag     = TRANSACTION_TYPE_ABBR.get(entry.get('type_desc', ''), entry.get('type_desc', ''))

            if abbr:
                try:
                    logo = _logo_small(abbr, team_id, size=logo_sz)
                    if logo:
                        ly = ry + (_ROW_H - logo.height) // 2
                        if dark_mode:
                            # Invert so logo pixels become white; use as own mask
                            # so the white background doesn't overwrite the black bg.
                            inv  = ImageOps.invert(logo.convert('L'))
                            mask = inv.point(lambda p: 255 if p > 30 else 0)
                            Himage.paste(inv.convert('1'), (logo_x, ly), mask)
                        else:
                            Himage.paste(logo, (logo_x, ly))
                except Exception:
                    pass

            draw.text((abbr_x, ry + 4), abbr, font=font_row, fill=fg)

            max_name_w = tag_x - name_x - 4
            while name and int(font_row.getlength(name)) > max_name_w:
                name = name[:-1]
            draw.text((name_x, ry + 4), name, font=font_row, fill=fg)
            draw.text((tag_x,  ry + 4), tag,  font=font_row, fill=fg)

    _draw_column(entries[:_MAX_ROWS],                   col_x_offset=0)
    draw.line((_COL_DIV_X, 0, _COL_DIV_X, 480), fill=fg)   # column divider
    _draw_column(entries[_MAX_ROWS:_MAX_ROWS * 2],      col_x_offset=_COL_DIV_X + 2)

    if not entries:
        draw.text((_PAD, _HEADER_H + 20), 'No recent transactions', font=font_row, fill=fg)

    return Himage


# ---------------------------------------------------------------------------
# "On this date in history" screen
# ---------------------------------------------------------------------------

def _draw_history_badge(draw, sx, sy, game, fg, bg):
    """Overlay a small badge on a history game cell for notable events."""
    if game.get('perfect_game'):
        label = 'PERFECT GAME'
    elif game.get('no_hitter'):
        label = 'NO-HITTER'
    elif game.get('walk_off'):
        label = 'WALK-OFF'
    else:
        return

    font = _get_font(8)
    cell_w, badge_h = 135, 11
    badge_y = sy + 130 - badge_h
    draw.rectangle([sx, badge_y, sx + cell_w - 1, sy + 129], fill=fg)
    lw = int(font.getlength(label))
    draw.text((sx + (cell_w - lw) // 2, badge_y + 1), label, font=font, fill=bg)


def draw_history_screen(games, year, team_data, config):
    """Render an 800×480 screen showing historical games from today's date in a past year.

    games    : list of game dicts from fetch_idle.fetch_this_day_in_history()
    year     : the historical year (int) shown in the header
    team_data: {'team_abbreviation': {id: abbr, ...}}
    config   : app config dict (dark_mode, ...)
    """
    from image_box import draw_box, set_historical_mode

    dark_mode = config.get('dark_mode', False)
    bg = 0 if dark_mode else 255
    fg = 255 if dark_mode else 0

    Himage = Image.new('1', (800, 480), bg)
    draw   = ImageDraw.Draw(Himage)

    # ── Header ────────────────────────────────────────────────────────────
    HDR_H    = 28
    font_hdr = _get_font(18)

    if year:
        header_text = f'ON THIS DATE IN {year}'
    else:
        header_text = 'ON THIS DATE IN HISTORY'

    draw.text((6, 5),  header_text, font=font_hdr, fill=fg)
    draw.text((7, 5),  header_text, font=font_hdr, fill=fg)   # bold stroke
    draw.line((0, HDR_H, 800, HDR_H), fill=fg)

    if not games:
        draw.text((6, HDR_H + 20), 'No historical games found for this date', font=_get_font(14), fill=fg)
        return Himage

    # ── Game grid (5 col × up to 3 rows, 150 px slots, matching main board) ──
    set_historical_mode(True)
    try:
        x_start  = 32
        y_start  = HDR_H + 2
        slot_w   = 150
        slot_h   = 150
        max_cols = 5
        max_rows = 3

        for idx, game in enumerate(games[:max_cols * max_rows]):
            col = idx % max_cols
            row = idx // max_cols
            sx  = x_start + col * slot_w
            sy  = y_start + row * slot_h
            Himage = draw_box(
                Himage, sx, sy, game, team_data or {},
                use_logos=config.get('use_team_logos', False),
                logo_x_offset=config.get('small_logo_x_offset', 2),
                show_winner_logo=True,
                force_linescore=True,
            )
            _draw_history_badge(ImageDraw.Draw(Himage), sx, sy, game, fg, bg)
    finally:
        set_historical_mode(False)

    return Himage
