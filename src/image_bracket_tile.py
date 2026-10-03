"""Compact playoff bracket tile (300×300px) for a 2×2 grid slot."""
from image_assets import Image, ImageDraw, ImageOps

TILE_W = 300
TILE_H = 300

_N_BANDS  = 7
_BAND_W   = TILE_W // _N_BANDS   # 42 px per band
_LOGO_SZ  = 20
_PAD      = 2
_TEAM_H   = _LOGO_SZ + 2 * _PAD  # 24 px
_LABEL_H  = 10
_CS_LOGO_SZ = _LOGO_SZ + 6       # 26 px — CS winner logo, slightly larger

# Connector lines start/end at the logo edge so adjacent bands still produce
# an L-shape rather than a degenerate vertical-only line.
_CONN_INSET = _LOGO_SZ // 2  # 10 px from band centre (logo radius)

_BANDS = (
    ('AL', 'WC'), ('AL', 'DS'), ('AL', 'CS'), (None, 'WS'),
    ('NL', 'CS'), ('NL', 'DS'), ('NL', 'WC'),
)
_WS_BAND = 3
_ROUND_LABELS = {'WC': 'WC', 'DS': 'DS', 'CS': 'CS', 'WS': 'WS'}


def _band_cx(band):
    return band * _BAND_W + _BAND_W // 2


def _slot_center_y(index, count):
    body_top = _LABEL_H
    body_h   = TILE_H - body_top
    return body_top + int(body_h * (2 * index + 1) / (2 * count))


def _paste_logo(tile, abbr, tid, cx, cy, ghost=False, size=None):
    from image_assets import _logo_small, _logo_ghost
    sz = size or _LOGO_SZ
    logo = (_logo_ghost(abbr, tid, size=sz, lightness=140)
            if ghost else _logo_small(abbr, tid, size=sz))
    if logo is not None:
        lw, lh = logo.size
        tile.paste(logo, (cx - lw // 2, cy - lh // 2))
    else:
        draw = ImageDraw.Draw(tile)
        hw = sz // 2 - 2
        draw.ellipse([cx - hw, cy - hw, cx + hw, cy + hw], outline=0)


def _logo_cys(slot_cy):
    """Away and home logo centre-y for a matchup at slot_cy."""
    return (slot_cy - _TEAM_H // 2 - _LOGO_SZ // 2,
            slot_cy + _TEAM_H // 2 + _LOGO_SZ // 2)


def _is_real_team(tid):
    # The MLB API gives undecided slots ("AL Low", "High") ids in the 2700/5500 range;
    # real clubs are all below 1000.
    return str(tid).isdigit() and int(tid) < 1000


def _has_real_team(series):
    return bool(series) and (_is_real_team(series.get('away_id', ''))
                             or _is_real_team(series.get('home_id', '')))


def _draw_matchup(tile, draw, band, slot_cy, series):
    """Draw two logos + thin divider for one matchup, centred at slot_cy.

    Undecided slots (no series, or seed placeholders like "AL Low") draw nothing.
    """
    cx   = _band_cx(band)
    cy0, cy1 = _logo_cys(slot_cy)

    if not _has_real_team(series):
        return

    if band != _WS_BAND:
        draw.line([(cx - _BAND_W // 2 + 2, slot_cy), (cx + _BAND_W // 2 - 2, slot_cy)], fill=0)

    away_abbr = (series.get('away_abbr') or '?')[:3]
    home_abbr = (series.get('home_abbr') or '?')[:3]
    away_id   = str(series.get('away_id', ''))
    home_id   = str(series.get('home_id', ''))
    complete  = series.get('complete', False)
    winner    = series.get('winner_abbr') or ''
    away_ghost = complete and bool(winner) and winner != away_abbr
    home_ghost = complete and bool(winner) and winner != home_abbr

    if _is_real_team(away_id):
        _paste_logo(tile, away_abbr, away_id, cx, cy0, ghost=away_ghost)
    if _is_real_team(home_id):
        _paste_logo(tile, home_abbr, home_id, cx, cy1, ghost=home_ghost)


def _draw_cs_champion(tile, draw, band, slot_cy, series):
    """CS band: single winner logo (connector endpoint) when complete, else compact matchup."""
    cx = _band_cx(band)
    if series is None:
        return
    complete = series.get('complete', False)
    winner   = series.get('winner_abbr') or ''
    if complete and winner:
        away_abbr = (series.get('away_abbr') or '?')[:3]
        tid = str(series.get(
            'away_id' if winner == away_abbr else 'home_id', ''))
        _paste_logo(tile, winner, tid, cx, slot_cy, size=_CS_LOGO_SZ)
    else:
        _draw_matchup(tile, draw, band, slot_cy, series)


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
            if rnd == 'CS':
                # CS shows a single logo: the winner (or matchup if still in progress)
                _draw_cs_champion(tile, draw, band, cy, series)
            else:
                _draw_matchup(tile, draw, band, cy, series)
            placed[(band, i)] = cy

    # WC → DS: 1-to-1 L-shaped connectors
    for src_b, dst_b, pairs in (
        (0, 1, ((0, 0), (1, 1))),
        (6, 5, ((0, 0), (1, 1))),
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
                _draw_connector(draw, scx + _CONN_INSET, scy, dcx - _CONN_INSET, dcy)
            else:
                _draw_connector(draw, scx - _CONN_INSET, scy, dcx + _CONN_INSET, dcy)

    # DS → CS gather connector: two DS exits meet at a vertical spine then a
    # single line continues to the CS winner logo.
    for ds_b, cs_b, right in ((1, 2, True), (5, 4, False)):
        if not all(k in placed for k in ((ds_b, 0), (ds_b, 1), (cs_b, 0))):
            continue
        y0   = placed[(ds_b, 0)]
        y1   = placed[(ds_b, 1)]
        ycs  = placed[(cs_b, 0)]
        x_ds = _band_cx(ds_b) + ( _CONN_INSET if right else -_CONN_INSET)
        x_cs = _band_cx(cs_b) + (-_CONN_INSET if right else  _CONN_INSET)
        gx   = (x_ds + x_cs) // 2
        draw.line([(x_ds, y0),  (gx, y0)],  fill=0)
        draw.line([(x_ds, y1),  (gx, y1)],  fill=0)
        draw.line([(gx,   y0),  (gx, y1)],  fill=0)
        draw.line([(gx, ycs), (x_cs, ycs)], fill=0)

    # CS → WS: each CS winner logo connects to the specific WS team logo
    # (AL CS → WS away/top, NL CS → WS home/bottom) so the lines arrive at
    # the correct logo rather than the midpoint of the WS box.
    ws_cy = placed.get((3, 0))
    if ws_cy is not None:
        ws_away_y, ws_home_y = _logo_cys(ws_cy)
        # With no CS logo drawn, the line runs straight through the empty band.
        if (2, 0) in placed:
            inset = _CONN_INSET if _has_real_team(slots['AL']['CS'][0]) else -_CONN_INSET
            _draw_connector(draw,
                            _band_cx(2) + inset, placed[(2, 0)],
                            _band_cx(3) - _CONN_INSET, ws_away_y)
        if (4, 0) in placed:
            inset = _CONN_INSET if _has_real_team(slots['NL']['CS'][0]) else -_CONN_INSET
            _draw_connector(draw,
                            _band_cx(4) - inset, placed[(4, 0)],
                            _band_cx(3) + _CONN_INSET, ws_home_y)

    # WS winner: when the World Series is complete, draw the champion's logo
    # below the WS matchup in a prominent border box.
    ws_series = slots.get('WS')
    if ws_series and ws_series.get('complete') and ws_series.get('winner_abbr'):
        w_abbr = ws_series['winner_abbr']
        w_id   = str(ws_series.get(
            'away_id' if w_abbr == (ws_series.get('away_abbr') or '')[:3] else 'home_id', ''))
        ws_cx   = _band_cx(3)
        _cy0, _cy1 = _logo_cys(ws_cy or _slot_center_y(0, 1))
        champ_sz  = 50
        champ_y   = _cy1 + champ_sz // 2 + 38
        if champ_y + champ_sz // 2 + 4 <= TILE_H:
            box_pad = 4
            draw.rectangle([
                ws_cx - champ_sz // 2 - box_pad, champ_y - champ_sz // 2 - box_pad,
                ws_cx + champ_sz // 2 + box_pad, champ_y + champ_sz // 2 + box_pad,
            ], outline=0)
            _paste_logo(tile, w_abbr, w_id, ws_cx, champ_y, size=champ_sz)

    if dark_mode:
        tile = ImageOps.invert(tile.convert('L')).convert('1')

    Himage.paste(tile, (sx, sy))
    return Himage
