"""Compact playoff bracket tile (300×300px) for a 2×2 grid slot.

Shows the same 7-band AL → WS ← NL tree as bracket_view.py, but built for
a 300×300 canvas and driven by team logos.  No connector lines — just boxes.

Layout (left to right):
  Band 0: AL WC   Band 1: AL DS   Band 2: AL CS
  Band 3: WS (centre)
  Band 4: NL CS   Band 5: NL DS   Band 6: NL WC

Each matchup slot draws two logos (away top / home bottom) separated by a
thin dividing line.  The series winner's logo is shown solid; the loser's is
ghosted. Pending slots show empty placeholder boxes.
"""
from image_assets import Image, ImageDraw

TILE_W = 300
TILE_H = 300

_HEADER_H = 20
_BANDS = (
    ('AL', 'WC'), ('AL', 'DS'), ('AL', 'CS'), (None, 'WS'),
    ('NL', 'CS'), ('NL', 'DS'), ('NL', 'WC'),
)
_N_BANDS  = len(_BANDS)
_BAND_W   = TILE_W // _N_BANDS   # ~42 px per band
_LOGO     = 20                    # logo size in px
_SLOT_PAD = 2                     # padding around each logo within a slot box


def _slot_h():
    """Height of one two-team slot: 2 logos + padding + 1px divider."""
    return 2 * (_LOGO + _SLOT_PAD * 2) + 1


def _slot_centre_y(index, count):
    """Vertical centre of the *index*-th slot out of *count* in the tile body."""
    body_top = _HEADER_H + 1
    body_h   = TILE_H - body_top - 1
    return body_top + int(body_h * (2 * index + 1) / (2 * count))


def _paste_logo_at(canvas, abbr, team_id, cx, cy, size, ghost=False):
    """Paste a logo centred at (cx, cy). Falls back to a small outlined box."""
    from image_assets import _logo_small, _logo_ghost
    logo = (_logo_ghost(abbr, team_id, size=size, lightness=140)
            if ghost else _logo_small(abbr, team_id, size=size))
    if logo is not None:
        lw, lh = logo.size
        canvas.paste(logo, (cx - lw // 2, cy - lh // 2))
    else:
        draw = ImageDraw.Draw(canvas)
        hw = size // 2
        draw.rectangle([cx - hw, cy - hw, cx + hw, cy + hw],
                       outline=0, fill=(255 if not ghost else 128))


def _draw_champ_box(canvas, draw, bx, matchup_cy, series):
    """Draw a double-bordered champion box below the WS matchup."""
    sh = _slot_h()
    match_bot = matchup_cy + sh // 2
    body_bot = TILE_H - 2
    avail = body_bot - match_bot
    box_h = _LOGO + _SLOT_PAD * 2
    if avail < box_h + 6:
        return
    top = match_bot + (avail - box_h) // 2
    cx = bx + _BAND_W // 2
    draw.rectangle([bx + 1, top, bx + _BAND_W - 2, top + box_h - 1], outline=0)
    draw.rectangle([bx + 3, top + 2, bx + _BAND_W - 4, top + box_h - 3], outline=0)
    w_abbr = (series.get('winner_abbr') or '')[:3]
    if w_abbr == series.get('away_abbr', ''):
        w_id = str(series.get('away_id', ''))
    else:
        w_id = str(series.get('home_id', ''))
    _paste_logo_at(canvas, w_abbr, w_id, cx, top + box_h // 2, _LOGO)


def _draw_matchup(canvas, draw, bx, slot_cy, series):
    """Draw a two-team matchup slot centred vertically at *slot_cy* within band starting at *bx*."""
    sh  = _slot_h()
    top = slot_cy - sh // 2
    mid = top + _LOGO + _SLOT_PAD * 2  # y of the divider line
    cx  = bx + _BAND_W // 2

    # Outer box
    draw.rectangle([bx + 1, top, bx + _BAND_W - 2, top + sh - 1], outline=0)
    # Divider between teams
    draw.line([(bx + 2, mid), (bx + _BAND_W - 3, mid)], fill=0)

    if series is None:
        return  # empty placeholder; box already drawn

    away_abbr = series.get('away_abbr', '?')[:3]
    home_abbr = series.get('home_abbr', '?')[:3]
    away_id   = str(series.get('away_id', ''))
    home_id   = str(series.get('home_id', ''))
    complete  = series.get('complete', False)
    winner    = series.get('winner_abbr', '')

    away_ghost = complete and bool(winner) and winner != away_abbr
    home_ghost = complete and bool(winner) and winner != home_abbr

    # Away logo (above divider)
    _paste_logo_at(canvas, away_abbr, away_id, cx,
                   top + _SLOT_PAD + _LOGO // 2, _LOGO, ghost=away_ghost)
    # Home logo (below divider)
    _paste_logo_at(canvas, home_abbr, home_id, cx,
                   mid + 1 + _SLOT_PAD + _LOGO // 2, _LOGO, ghost=home_ghost)


def _build_slots(bracket_data, standings_data):
    from bracket_view import _build_slots as _bv_slots, _team_maps
    team_league, team_seed, abbr_league = _team_maps(standings_data or {})
    return _bv_slots(bracket_data, team_league, team_seed, abbr_league)


def draw_bracket_tile(Himage, sx, sy, bracket_data, standings_data=None, dark_mode=False):
    """Render the logo bracket tile at (sx, sy) into Himage."""
    if not (bracket_data or {}).get('series'):
        return Himage
    try:
        slots = _build_slots(bracket_data, standings_data)
    except Exception:
        return Himage

    tile = Image.new('1', (TILE_W, TILE_H), 255)
    draw = ImageDraw.Draw(tile)

    # Outer border
    draw.rectangle([0, 0, TILE_W - 1, TILE_H - 1], outline=0)

    # Header — one label per band ("WC", "DS", "CS", "WS") centred in that band's column
    from image_assets import _get_font
    font = _get_font(10)
    draw.line([(1, _HEADER_H), (TILE_W - 2, _HEADER_H)], fill=0)
    for band_idx, (lg, rnd) in enumerate(_BANDS):
        bx = band_idx * _BAND_W
        cx = bx + _BAND_W // 2
        lw = int(font.getlength(rnd))
        draw.text((cx - lw // 2, 3), rnd, font=font, fill=0)

    # Draw each band
    for band_idx, (lg, rnd) in enumerate(_BANDS):
        bx = band_idx * _BAND_W
        series_list = [slots['WS']] if rnd == 'WS' else slots.get(lg, {}).get(rnd, [])
        count = max(len(series_list), 1)
        for i, series in enumerate(series_list):
            cy = _slot_centre_y(i, count)
            _draw_matchup(tile, draw, bx, cy, series)
            if rnd == 'WS' and (series or {}).get('complete') and (series or {}).get('winner_abbr'):
                _draw_champ_box(tile, draw, bx, cy, series)

    Himage.paste(tile, (sx, sy))
    return Himage
