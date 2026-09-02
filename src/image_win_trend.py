"""Season win-trend renderer.

Provides:
  draw_win_trend_cell(Himage, x, y, data, config)          – 135×130 px grid tile
  render_win_trend_view(data, config, dark_mode)           – 800×480 single-team chart
  render_all_teams_win_trend_view(data, config, dark_mode) – 800×480 30-team sparkline grid
  render_divisions_win_trend_view(data, config, dark_mode) – 800×480 6-division race charts

Single-team data from win_trend.json; all-teams/division data from all_teams_trend.json.
See fetch_win_trend.py.
"""
from PIL import Image, ImageDraw

from image_assets import _get_font, _logo_ghost

EPD_W = 800
EPD_H = 480

_CELL_W = 135
_CELL_H = 130
_HEADER_H = 20


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _games_above_500(games):
    """Return list of (game_index, games_above_500) for each completed game."""
    pts = []
    for i, g in enumerate(games):
        pts.append((i + 1, g['wins'] - g['losses']))
    return pts


def _draw_trend_line(draw, pts, x0, y0, w, h, dark_mode=False):
    """Draw a games-above-.500 trend line into a pixel rect (x0,y0,w,h).

    pts is a list of (game_num, diff) from _games_above_500.
    Positive diff → above .500; negative → below.
    Centre line at y-midpoint; line drawn in foreground colour.
    """
    if len(pts) < 2:
        return
    fg = 255 if dark_mode else 0

    n_games = pts[-1][0]
    diffs = [d for _, d in pts]
    d_min, d_max = min(diffs), max(diffs)
    # Ensure centre (0) is always visible; pad symmetrically
    pad = max(abs(d_min), abs(d_max), 1)
    d_min_padded = -pad
    d_max_padded = pad

    def _px(game_num, diff):
        gx = x0 + int((game_num - 1) / max(n_games - 1, 1) * (w - 1))
        gy = y0 + h - 1 - int((diff - d_min_padded) / (d_max_padded - d_min_padded) * (h - 1))
        return gx, gy

    # Centre line (y for diff=0)
    _, cy = _px(1, 0)
    draw.line((x0, cy, x0 + w - 1, cy), fill=fg)

    # Trend line
    prev = None
    for game_num, diff in pts:
        cur = _px(game_num, diff)
        if prev is not None:
            draw.line((prev[0], prev[1], cur[0], cur[1]), fill=fg)
        prev = cur


# ---------------------------------------------------------------------------
# Tile (135 × 130 px)
# ---------------------------------------------------------------------------

def draw_win_trend_cell(Himage, x, y, data, config=None):
    """Draw a 135×130 win-trend tile at (x, y) on Himage.

    Shows team abbreviation + record in the header, then a games-above-.500
    sparkline in the body.
    """
    if not data or not data.get('games'):
        return Himage

    dark_mode = (config or {}).get('dark_mode', False)
    bg = 0 if dark_mode else 255
    fg = 255 if dark_mode else 0

    draw = ImageDraw.Draw(Himage)

    # Outer border
    draw.rectangle([x, y, x + _CELL_W - 1, y + _CELL_H - 1], outline=fg)

    # Header
    draw.line((x, y + _HEADER_H, x + _CELL_W - 1, y + _HEADER_H), fill=fg)

    abbr = data.get('team_abbr', '')
    games = data.get('games', [])
    wins = games[-1]['wins'] if games else 0
    losses = games[-1]['losses'] if games else 0
    record_str = f'{wins}–{losses}'
    diff = wins - losses
    diff_str = ('+' if diff > 0 else '') + str(diff)

    font_hdr = _get_font(12)
    font_sm  = _get_font(9)

    # Left: abbr bold; right: record
    draw.text((x + 3, y + 3), abbr, font=font_hdr, fill=fg)
    draw.text((x + 4, y + 3), abbr, font=font_hdr, fill=fg)
    rw = int(font_sm.getlength(record_str))
    draw.text((x + _CELL_W - rw - 3, y + 5), record_str, font=font_sm, fill=fg)

    # Body: sparkline
    pts = _games_above_500(games)
    body_pad = 4
    _draw_trend_line(
        draw, pts,
        x + body_pad, y + _HEADER_H + body_pad,
        _CELL_W - 2 * body_pad,
        _CELL_H - _HEADER_H - 2 * body_pad - 14,
        dark_mode=dark_mode,
    )

    # Footer: diff label
    font_ft = _get_font(9)
    ft_label = f'{diff_str} vs .500'
    ftw = int(font_ft.getlength(ft_label))
    ftx = x + (_CELL_W - ftw) // 2
    fty = y + _CELL_H - 13
    draw.rectangle([ftx - 1, fty, ftx + ftw + 1, fty + 11], fill=bg)
    draw.text((ftx, fty), ft_label, font=font_ft, fill=fg)

    return Himage


# ---------------------------------------------------------------------------
# Full-screen view (800 × 480 px)
# ---------------------------------------------------------------------------

def render_win_trend_view(data, config=None, dark_mode=False):
    """Render an 800×480 season win/loss trend chart.

    Shows cumulative wins vs. .500 pace as two lines, with the team logo
    ghosted in the background.
    """
    config = config or {}
    bg = 0 if dark_mode else 255
    fg = 255 if dark_mode else 0

    Himage = Image.new('1', (EPD_W, EPD_H), bg)
    draw = ImageDraw.Draw(Himage)

    if not data or not data.get('games'):
        f = _get_font(18)
        draw.text((20, 200), 'No win-trend data — run fetch_win_trend.py', font=f, fill=fg)
        return Himage

    abbr   = data.get('team_abbr', '?')
    season = data.get('season', '')
    games  = data.get('games', [])
    wins   = games[-1]['wins']
    losses = games[-1]['losses']
    n      = len(games)
    diff   = wins - losses
    diff_str = ('+' if diff >= 0 else '') + str(diff)

    # Ghost team logo in background
    team_id = data.get('team_id')
    if team_id:
        try:
            ghost = _logo_ghost(abbr, team_id, size=320, lightness=220)
            if ghost:
                gx = (EPD_W - ghost.width) // 2
                gy = (EPD_H - ghost.height) // 2 + 20
                Himage.paste(ghost, (gx, gy))
                draw = ImageDraw.Draw(Himage)
        except Exception:
            pass

    # ── Header ────────────────────────────────────────────────────────────
    HEADER_H = 34
    draw.line((0, HEADER_H, EPD_W, HEADER_H), fill=fg)

    font_title = _get_font(22)
    font_rec   = _get_font(16)
    font_sm    = _get_font(12)

    title = f'{abbr} {season} SEASON PACE'
    draw.text((8, 6), title, font=font_title, fill=fg)
    draw.text((9, 6), title, font=font_title, fill=fg)

    rec_str = f'{wins}–{losses}  ({diff_str})'
    rw = int(font_rec.getlength(rec_str))
    draw.text((EPD_W - rw - 8, 9), rec_str, font=font_rec, fill=fg)

    # ── Chart area ────────────────────────────────────────────────────────
    PAD_L = 52
    PAD_R = 16
    PAD_T = 14
    PAD_B = 40
    cx0 = PAD_L
    cy0 = HEADER_H + PAD_T
    cw  = EPD_W - PAD_L - PAD_R
    ch  = EPD_H - HEADER_H - PAD_T - PAD_B

    # Y-axis: games above / below .500
    diffs = [g['wins'] - g['losses'] for g in games]
    d_max = max(max(diffs), 1)
    d_min = min(min(diffs), -1)
    pad_y = max(int((d_max - d_min) * 0.08), 2)
    y_hi = d_max + pad_y
    y_lo = d_min - pad_y
    y_rng = y_hi - y_lo

    def _gx(game_num):
        return cx0 + int((game_num - 1) / max(n - 1, 1) * (cw - 1))

    def _gy(diff):
        return cy0 + ch - 1 - int((diff - y_lo) / y_rng * (ch - 1))

    # Centre (0) line
    cy_zero = _gy(0)
    draw.line((cx0, cy_zero, cx0 + cw - 1, cy_zero), fill=fg)

    # Dashed .500 pace reference (win == games/2)
    # represented as a straight diagonal from (0,0) to (n, 0) since we track above-.500
    # The centre line IS the .500 pace — label it.
    font_axis = _get_font(10)
    draw.text((cx0 - 36, cy_zero - 6), '.500', font=font_axis, fill=fg)

    # Y-axis tick marks and labels
    tick_step = max(1, round(y_rng / 8))
    tick_val = 0
    while tick_val <= y_hi:
        ty = _gy(tick_val)
        if cy0 <= ty <= cy0 + ch:
            draw.line((cx0 - 4, ty, cx0, ty), fill=fg)
            lbl = ('+' if tick_val > 0 else '') + str(tick_val)
            lw = int(font_axis.getlength(lbl))
            draw.text((cx0 - lw - 6, ty - 6), lbl, font=font_axis, fill=fg)
        tick_val += tick_step
    tick_val = -tick_step
    while tick_val >= y_lo:
        ty = _gy(tick_val)
        if cy0 <= ty <= cy0 + ch:
            draw.line((cx0 - 4, ty, cx0, ty), fill=fg)
            lbl = str(tick_val)
            lw = int(font_axis.getlength(lbl))
            draw.text((cx0 - lw - 6, ty - 6), lbl, font=font_axis, fill=fg)
        tick_val -= tick_step

    # Y-axis line
    draw.line((cx0, cy0, cx0, cy0 + ch - 1), fill=fg)

    # X-axis tick marks: every ~20 games
    x_step = max(10, round(n / 8 / 10) * 10)
    g_num = x_step
    while g_num <= n:
        tx = _gx(g_num)
        draw.line((tx, cy0 + ch, tx, cy0 + ch + 4), fill=fg)
        lbl = str(g_num)
        lw = int(font_axis.getlength(lbl))
        draw.text((tx - lw // 2, cy0 + ch + 6), lbl, font=font_axis, fill=fg)
        g_num += x_step

    # X-axis label
    xl_str = 'GAME NUMBER'
    xl_w = int(font_axis.getlength(xl_str))
    draw.text((cx0 + (cw - xl_w) // 2, cy0 + ch + 20), xl_str, font=font_axis, fill=fg)

    # X-axis line
    draw.line((cx0, cy0 + ch, cx0 + cw - 1, cy0 + ch), fill=fg)

    # ── Win trend line ─────────────────────────────────────────────────────
    prev = None
    for i, g in enumerate(games):
        game_num = i + 1
        d = g['wins'] - g['losses']
        cur = (_gx(game_num), _gy(d))
        if prev is not None:
            draw.line((prev[0], prev[1], cur[0], cur[1]), fill=fg)
            # Second pass for thicker line on every other segment
            draw.line((prev[0], prev[1] + 1, cur[0], cur[1] + 1), fill=fg)
        prev = cur

    # Dot at current position
    if games:
        ex, ey = _gx(n), _gy(diffs[-1])
        draw.ellipse((ex - 4, ey - 4, ex + 4, ey + 4), fill=fg)
        # Label current diff next to the dot
        end_lbl = f'G{n}: {diff_str}'
        el_w = int(font_sm.getlength(end_lbl))
        el_x = min(ex + 6, cx0 + cw - el_w - 2)
        el_y = ey - 8
        draw.text((el_x, el_y), end_lbl, font=font_sm, fill=fg)

    return Himage


# ---------------------------------------------------------------------------
# All-teams full-screen view (800 × 480 px)
# ---------------------------------------------------------------------------

_AT_COLS = 6
_AT_ROWS = 5
_AT_HEADER_H = 22
_AT_CELL_W = 800 // _AT_COLS          # 133 px
_AT_CELL_H = (EPD_H - _AT_HEADER_H) // _AT_ROWS   # 91 px
_AT_HDR_ROW_H = 14  # px of header inside each mini-cell
_AT_PAD = 3         # inner padding for sparkline


def _at_cell_header(draw, cx, cy, abbr, wins, losses, diff, font_abbr, font_rec, fg):
    """Draw the top row (abbr + record) inside one all-teams mini-cell."""
    diff_str = ('+' if diff >= 0 else '') + str(diff)
    rec = f'{wins}-{losses}'
    draw.text((cx + 2, cy + 1), abbr, font=font_abbr, fill=fg)
    rw = int(font_rec.getlength(rec))
    draw.text((cx + _AT_CELL_W - rw - 2, cy + 2), rec, font=font_rec, fill=fg)
    dw = int(font_rec.getlength(diff_str))
    draw.text((cx + _AT_CELL_W - dw - 2, cy + _AT_HDR_ROW_H - 9), diff_str,
              font=font_rec, fill=fg)


def render_all_teams_win_trend_view(data, config=None, dark_mode=False):
    """Render an 800×480 grid of all MLB teams' season win-loss sparklines.

    data is the dict from all_teams_trend.json (fetch_win_trend.fetch_all_teams_trend).
    Teams are sorted best-to-worst by current games-above-.500, laid out 6×5.
    """
    config = config or {}
    bg = 0 if dark_mode else 255
    fg = 255 if dark_mode else 0

    Himage = Image.new('1', (EPD_W, EPD_H), bg)
    draw = ImageDraw.Draw(Himage)

    if not data or not data.get('teams'):
        f = _get_font(16)
        draw.text((20, 200), 'No data — run fetch_win_trend.py --all', font=f, fill=fg)
        return Himage

    season = data.get('season', '')
    teams_map = data['teams']

    def _sort_key(entry):
        games = entry.get('games', [])
        if not games:
            return (0, 0)
        last = games[-1]
        return (last['wins'] - last['losses'], last['wins'])

    sorted_teams = sorted(teams_map.values(), key=_sort_key, reverse=True)

    # ── Global header ─────────────────────────────────────────────────────
    font_title = _get_font(14)
    font_abbr  = _get_font(10)
    font_rec   = _get_font(8)

    title = f'{season} SEASON PACE — ALL TEAMS'
    draw.text((4, 3), title, font=font_title, fill=fg)
    draw.text((5, 3), title, font=font_title, fill=fg)
    draw.line((0, _AT_HEADER_H, EPD_W, _AT_HEADER_H), fill=fg)

    y_base = _AT_HEADER_H

    for idx, team_entry in enumerate(sorted_teams[:_AT_COLS * _AT_ROWS]):
        col = idx % _AT_COLS
        row = idx // _AT_COLS

        cx = col * _AT_CELL_W
        cy = y_base + row * _AT_CELL_H

        # Cell border — right and bottom lines only (avoids double-drawing)
        if col > 0:
            draw.line((cx, cy, cx, cy + _AT_CELL_H - 1), fill=fg)
        draw.line((cx, cy + _AT_CELL_H - 1, cx + _AT_CELL_W - 1, cy + _AT_CELL_H - 1), fill=fg)

        games = team_entry.get('games', [])
        abbr  = team_entry.get('team_abbr', '???')

        if not games:
            draw.text((cx + 2, cy + 2), abbr, font=font_abbr, fill=fg)
            continue

        last   = games[-1]
        wins   = last['wins']
        losses = last['losses']
        diff   = wins - losses

        # Header row separator
        draw.line((cx, cy + _AT_HDR_ROW_H, cx + _AT_CELL_W - 1, cy + _AT_HDR_ROW_H), fill=fg)
        _at_cell_header(draw, cx, cy, abbr, wins, losses, diff, font_abbr, font_rec, fg)

        # Sparkline
        pts   = _games_above_500(games)
        sp_y0 = cy + _AT_HDR_ROW_H + _AT_PAD
        sp_h  = _AT_CELL_H - _AT_HDR_ROW_H - _AT_PAD * 2
        sp_x0 = cx + _AT_PAD
        sp_w  = _AT_CELL_W - _AT_PAD * 2
        _draw_trend_line(draw, pts, sp_x0, sp_y0, sp_w, sp_h, dark_mode=dark_mode)

    return Himage


# ---------------------------------------------------------------------------
# Division race view (800 × 480 px) — 3 AL + 3 NL panels, 3 cols × 2 rows
# ---------------------------------------------------------------------------

_DIVISIONS = [
    ('AL East',    ['NYY', 'BOS', 'BAL', 'TOR', 'TB']),
    ('AL Central', ['CLE', 'MIN', 'DET', 'CWS', 'KC']),
    ('AL West',    ['HOU', 'TEX', 'SEA', 'OAK', 'LAA']),
    ('NL East',    ['ATL', 'NYM', 'PHI', 'MIA', 'WSH']),
    ('NL Central', ['MIL', 'CHC', 'STL', 'CIN', 'PIT']),
    ('NL West',    ['LAD', 'SF',  'SD',  'ARI', 'COL']),
]

_DIV_COLS    = 3
_DIV_ROWS    = 2
_DIV_GL_H    = 22          # global header height
_DIV_PANEL_W = EPD_W // _DIV_COLS                       # 266
_DIV_PANEL_H = (EPD_H - _DIV_GL_H) // _DIV_ROWS        # 229
_DIV_HDR_H   = 16          # per-panel header height
_DIV_PAD_L   = 26          # left margin (y-axis labels)
_DIV_PAD_R   = 22          # right margin (end labels)
_DIV_PAD_T   = 3
_DIV_PAD_B   = 3

_LINE_PATTERNS = [
    None,       # 0: solid
    'bold',     # 1: solid + y+1 (thicker)
    (4, 4),     # 2: dashed
    (2, 4),     # 3: dotted
    (8, 3),     # 4: long-dash
]


def _draw_styled_line(draw, x1, y1, x2, y2, style, fg, counter):
    """Draw a line segment with a pattern; counter is a mutable [int] for continuity."""
    pat = _LINE_PATTERNS[style % len(_LINE_PATTERNS)]
    if pat is None:
        draw.line((x1, y1, x2, y2), fill=fg)
        return
    if pat == 'bold':
        draw.line((x1, y1, x2, y2), fill=fg)
        draw.line((x1, y1 + 1, x2, y2 + 1), fill=fg)
        return
    on, off = pat
    dx, dy = x2 - x1, y2 - y1
    length = max(int((dx * dx + dy * dy) ** 0.5), 1)
    for t in range(length + 1):
        if (counter[0] % (on + off)) < on:
            px = int(x1 + t / length * dx)
            py = int(y1 + t / length * dy)
            draw.point((px, py), fill=fg)
        counter[0] += 1


def _draw_div_panel(draw, data_by_abbr, px, py, pw, ph, div_name, team_abbrs, fg, bg):
    """Render one division panel at pixel rect (px, py, pw, ph)."""
    font_hdr = _get_font(11)
    font_sm  = _get_font(8)

    # Panel header
    draw.text((px + 3, py + 2), div_name.upper(), font=font_hdr, fill=fg)
    draw.text((px + 4, py + 2), div_name.upper(), font=font_hdr, fill=fg)
    draw.line((px, py + _DIV_HDR_H, px + pw - 1, py + _DIV_HDR_H), fill=fg)

    # Chart area
    cx0 = px + _DIV_PAD_L
    cy0 = py + _DIV_HDR_H + _DIV_PAD_T
    cw  = pw - _DIV_PAD_L - _DIV_PAD_R
    ch  = ph - _DIV_HDR_H - _DIV_PAD_T - _DIV_PAD_B

    # Shared y-scale: global min/max across all 5 teams
    all_diffs = []
    team_games = {}
    for abbr in team_abbrs:
        gs = (data_by_abbr.get(abbr) or {}).get('games', [])
        team_games[abbr] = gs
        for g in gs:
            all_diffs.append(g['wins'] - g['losses'])
    if not all_diffs:
        return

    d_max = max(max(all_diffs), 1)
    d_min = min(min(all_diffs), -1)
    pad_y = max(int((d_max - d_min) * 0.08), 2)
    y_hi, y_lo = d_max + pad_y, d_min - pad_y
    y_rng = max(y_hi - y_lo, 1)

    all_n = max((len(team_games[a]) for a in team_abbrs), default=2)
    all_n = max(all_n, 2)

    def _gx(gn):
        return cx0 + int((gn - 1) / (all_n - 1) * (cw - 1))

    def _gy(d):
        return cy0 + ch - 1 - int((d - y_lo) / y_rng * (ch - 1))

    # Axes
    draw.line((cx0, cy0, cx0, cy0 + ch - 1), fill=fg)
    cy_zero = _gy(0)
    draw.line((cx0, cy_zero, cx0 + cw - 1, cy_zero), fill=fg)

    # Y-axis ticks
    tick_step = max(5, (round((y_hi - y_lo) / 4 / 5) * 5) or 5)
    for tv in range(int(y_lo), int(y_hi) + 1, tick_step):
        ty = _gy(tv)
        if cy0 <= ty <= cy0 + ch and tv != 0:
            draw.line((cx0 - 3, ty, cx0, ty), fill=fg)
            lbl = ('+' if tv > 0 else '') + str(tv)
            lw = int(font_sm.getlength(lbl))
            draw.text((cx0 - lw - 4, ty - 4), lbl, font=font_sm, fill=fg)

    # Sort teams best-to-worst for consistent style assignment
    sorted_teams = sorted(
        team_abbrs,
        key=lambda a: (team_games[a][-1]['wins'] - team_games[a][-1]['losses'])
                      if team_games[a] else 0,
        reverse=True,
    )

    for style_idx, abbr in enumerate(sorted_teams):
        games = team_games[abbr]
        if not games:
            continue
        counter = [0]
        prev_pt = None
        for j, g in enumerate(games):
            gx = _gx(j + 1)
            gy = _gy(g['wins'] - g['losses'])
            if prev_pt is not None:
                _draw_styled_line(draw, prev_pt[0], prev_pt[1], gx, gy,
                                  style_idx, fg, counter)
            prev_pt = (gx, gy)

        # End label
        last = games[-1]
        end_x = _gx(len(games))
        end_y = _gy(last['wins'] - last['losses'])
        lw = int(font_sm.getlength(abbr))
        lx = min(end_x + 2, px + pw - lw - 2)
        ly = max(cy0, min(cy0 + ch - 9, end_y - 4))
        draw.rectangle([lx - 1, ly - 1, lx + lw, ly + 8], fill=bg)
        draw.text((lx, ly), abbr, font=font_sm, fill=fg)


def render_divisions_win_trend_view(data, config=None, dark_mode=False):
    """Render an 800×480 grid of 6 division win-trend panels.

    Each panel shows all 5 teams in a division on shared axes so divisional
    races are directly comparable. data is from all_teams_trend.json.
    """
    config = config or {}
    bg = 0 if dark_mode else 255
    fg = 255 if dark_mode else 0

    Himage = Image.new('1', (EPD_W, EPD_H), bg)
    draw = ImageDraw.Draw(Himage)

    if not data or not data.get('teams'):
        f = _get_font(16)
        draw.text((20, 200), 'No data — run fetch_win_trend.py --all', font=f, fill=fg)
        return Himage

    season = data.get('season', '')
    data_by_abbr = {v['team_abbr']: v for v in data['teams'].values()}

    # Global header
    font_title = _get_font(14)
    title = f'{season} SEASON PACE — BY DIVISION'
    draw.text((4, 3), title, font=font_title, fill=fg)
    draw.text((5, 3), title, font=font_title, fill=fg)
    draw.line((0, _DIV_GL_H, EPD_W, _DIV_GL_H), fill=fg)

    for idx, (div_name, team_abbrs) in enumerate(_DIVISIONS):
        col = idx % _DIV_COLS
        row = idx // _DIV_COLS
        px = col * _DIV_PANEL_W
        py = _DIV_GL_H + row * _DIV_PANEL_H

        # Panel borders (right divider and bottom rule)
        if col > 0:
            draw.line((px, py, px, py + _DIV_PANEL_H - 1), fill=fg)
        draw.line((px, py + _DIV_PANEL_H - 1, px + _DIV_PANEL_W - 1, py + _DIV_PANEL_H - 1), fill=fg)

        _draw_div_panel(draw, data_by_abbr, px, py, _DIV_PANEL_W, _DIV_PANEL_H,
                        div_name, team_abbrs, fg, bg)

    return Himage
