"""Compact playoff bracket tile (300×300px) for a 2×2 grid slot.

Logos-only tree: each matchup is two team logos separated by a thin divider,
connected by L-shaped bracket lines.  No text, no boxes — just the tree.
"""
from image_assets import Image, ImageDraw, ImageOps

TILE_W = 300
TILE_H = 300

_N_BANDS  = 7
_BAND_W   = TILE_W // _N_BANDS   # 42 px per band
_LOGO_SZ  = 20                   # team logo diameter
_PAD      = 2                    # padding around each logo
_TEAM_H   = _LOGO_SZ + 2 * _PAD # height per team slot  (24 px)
_LABEL_H  = 10                   # round-label strip at top

_BANDS = (
    ('AL', 'WC'), ('AL', 'DS'), ('AL', 'CS'), (None, 'WS'),
    ('NL', 'CS'), ('NL', 'DS'), ('NL', 'WC'),
)
_ROUND_LABELS = {'WC': 'WC', 'DS': 'DS', 'CS': 'CS', 'WS': 'WS'}


def _band_cx(band):
    return band * _BAND_W + _BAND_W // 2


def _slot_center_y(index, count):
    body_top = _LABEL_H
    body_h   = TILE_H - body_top
    return body_top + int(body_h * (2 * index + 1) / (2 * count))


def _paste_logo(tile, abbr, tid, cx, cy, ghost=False):
    from image_assets import _logo_small, _logo_ghost
    logo = (_logo_ghost(abbr, tid, size=_LOGO_SZ, lightness=140)
            if ghost else _logo_small(abbr, tid, size=_LOGO_SZ))
    if logo is not None:
        lw, lh = logo.size
        tile.paste(logo, (cx - lw // 2, cy - lh // 2))
    else:
        draw = ImageDraw.Draw(tile)
        hw = _LOGO_SZ // 2 - 2
        draw.ellipse([cx - hw, cy - hw, cx + hw, cy + hw], outline=0)


def _logo_cys(slot_cy):
    """Away and home logo centre-y for a matchup at slot_cy."""
    return (slot_cy - _TEAM_H // 2 - _LOGO_SZ // 2,
            slot_cy + _TEAM_H // 2 + _LOGO_SZ // 2)


def _winner_exit_cy(series, slot_cy):
    """Y of the winner's logo (connector attachment).  Falls back to slot_cy."""
    if not series or not series.get('complete') or not series.get('winner_abbr'):
        return slot_cy
    away_abbr = (series.get('away_abbr') or '')[:3]
    cy0, cy1  = _logo_cys(slot_cy)
    return cy0 if series['winner_abbr'] == away_abbr else cy1


def _draw_matchup(tile, draw, band, slot_cy, series):
    """Draw two logos + thin divider for one matchup, centred at slot_cy."""
    cx   = _band_cx(band)
    cy0, cy1 = _logo_cys(slot_cy)

    # Thin divider between the two teams
    draw.line([(cx - _BAND_W // 2 + 2, slot_cy), (cx + _BAND_W // 2 - 2, slot_cy)], fill=0)

    if series is None:
        _paste_logo(tile, 'TBD', '', cx, cy0)
        _paste_logo(tile, 'TBD', '', cx, cy1)
        return

    away_abbr = (series.get('away_abbr') or '?')[:3]
    home_abbr = (series.get('home_abbr') or '?')[:3]
    away_id   = str(series.get('away_id', ''))
    home_id   = str(series.get('home_id', ''))
    complete  = series.get('complete', False)
    winner    = series.get('winner_abbr') or ''
    away_ghost = complete and bool(winner) and winner != away_abbr
    home_ghost = complete and bool(winner) and winner != home_abbr

    _paste_logo(tile, away_abbr, away_id, cx, cy0, ghost=away_ghost)
    _paste_logo(tile, home_abbr, home_id, cx, cy1, ghost=home_ghost)


def _draw_connector(draw, x_from, y_from, x_to, y_to):
    mid = (x_from + x_to) // 2
    draw.line([(x_from, y_from), (mid, y_from)], fill=0)
    if y_from != y_to:
        draw.line([(mid, y_from), (mid, y_to)], fill=0)
    draw.line([(mid, y_to), (x_to, y_to)], fill=0)


def draw_bracket_tile(Himage, sx, sy, bracket_data, standings_data=None, dark_mode=False):
    """Render a 300×300 logo-tree bracket tile at (sx, sy) into Himage."""
    if not (bracket_data or {}).get('series'):
        return Himage

    from bracket_view import _build_slots, _team_maps
    try:
        team_league, team_seed, abbr_league = _team_maps(standings_data or {})
        slots = _build_slots(bracket_data, team_league, team_seed, abbr_league)
    except Exception:
        return Himage

    tile = Image.new('1', (TILE_W, TILE_H), 255)
    draw = ImageDraw.Draw(tile)

    from image_assets import _get_font
    lbl_fnt = _get_font(8)

    # Round labels — bolded
    for band, (_lg, rnd) in enumerate(_BANDS):
        label = _ROUND_LABELS[rnd]
        lw = int(lbl_fnt.getlength(label))
        cx = _band_cx(band)
        for dx in (0, 1):
            draw.text((cx - lw // 2 + dx, 1), label, font=lbl_fnt, fill=0)

    _WC_SPREAD = 20  # extra px WC slots spread outward (top up, bottom down)

    # Draw matchups and record (band, index) → connector-attachment y
    placed = {}
    for band, (lg, rnd) in enumerate(_BANDS):
        series_list = [slots['WS']] if rnd == 'WS' else slots[lg][rnd]
        count = len(series_list)
        for i, series in enumerate(series_list):
            cy = _slot_center_y(i, count)
            if rnd == 'WC':
                cy += -_WC_SPREAD if i == 0 else _WC_SPREAD
            _draw_matchup(tile, draw, band, cy, series)
            # For WC, connect from the winner's logo; other rounds use slot centre
            exit_cy = _winner_exit_cy(series, cy) if rnd == 'WC' else cy
            placed[(band, i)] = exit_cy

    # Bracket connectors — AL left-to-right, NL right-to-left
    for src_b, dst_b, pairs in (
        (0, 1, ((0, 0), (1, 1))),
        (1, 2, ((0, 0), (1, 0))),
        (2, 3, ((0, 0),)),
        (6, 5, ((0, 0), (1, 1))),
        (5, 4, ((0, 0), (1, 0))),
        (4, 3, ((0, 0),)),
    ):
        right = src_b < dst_b
        for si, di in pairs:
            if (src_b, si) not in placed or (dst_b, di) not in placed:
                continue
            scy = placed[(src_b, si)]
            dcy = placed[(dst_b, di)]
            scx = _band_cx(src_b)
            dcx = _band_cx(dst_b)
            if right:
                _draw_connector(draw, scx + _BAND_W // 2, scy, dcx - _BAND_W // 2, dcy)
            else:
                _draw_connector(draw, scx - _BAND_W // 2, scy, dcx + _BAND_W // 2, dcy)

    if dark_mode:
        tile = ImageOps.invert(tile.convert('L')).convert('1')

    Himage.paste(tile, (sx, sy))
    return Himage
