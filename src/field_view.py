import os
import math
from PIL import Image, ImageDraw, ImageFont, ImageOps

from generate_image import (
    picdir, _logo_small, _load_logo_gray, draw_diamond, draw_circle,
)
from stadium_polygons import get_polygon

EPD_WIDTH = 800
EPD_HEIGHT = 480

# ---------------------------------------------------------------------------
# Three-cell layout
# Cell 1 (left):   x=0..266     — field diagram
# Cell 2 (middle): x=267..532   — game info (score, inning, matchup, linescore)
# Cell 3 (right):  x=534..799   — pitch zone
# ---------------------------------------------------------------------------
CELL1_X, CELL1_W = 0, 267
CELL2_X, CELL2_W = 267, 266
CELL3_X, CELL3_W = 534, 266

DIV1_X = 267   # divider between cells 1 and 2
DIV2_X = 534   # divider between cells 2 and 3

# ---------------------------------------------------------------------------
# Field geometry — FIELD_SCALE = 0.5 px/ft fits all MLB parks in a 267px cell.
#
# At 0.5 px/ft:
#   90-ft basepath diagonal (90*cos45°=63.6ft) → 31.8px offset each axis
#   Home↔Second: 127.3 ft → 63.6px
#   Pitcher's mound: 60.5 ft → 30.3px
#   LF/RF foul poles (~355 ft at ±45°): ±125px → x range 8..258  (within 267)
#   CF depth (400+ ft): ~200px above home — well within 480px height
# ---------------------------------------------------------------------------
FIELD_SCALE = 0.5

HOME_PLATE  = (133, 440)
FIRST_BASE  = (165, 408)    # home + (32, -32)
SECOND_BASE = (133, 376)    # home + (0, -64)
THIRD_BASE  = (101, 408)    # home + (-32, -32)
MOUND       = (133, 410)    # 60.5 ft * 0.5 = 30 px above home

# Infield arc radius: ~10px past second base (76 > 64)
_INFIELD_ARC_R = 76

# Fallback wall polygon — generic symmetric 400-ft park
_DEFAULT_WALL_POLY = [
    (-233.3, 233.3),
    (-109.6, 343.6),
    (0.0,    400.0),
    (109.6,  343.6),
    (233.3,  233.3),
]


def _load_fonts():
    font_path = os.path.join(picdir, 'Font.ttc')
    return {
        'f24': ImageFont.truetype(font_path, 24),
        'f18': ImageFont.truetype(font_path, 18),
        'f14': ImageFont.truetype(font_path, 14),
        'f11': ImageFont.truetype(font_path, 11),
        'f9':  ImageFont.truetype(font_path, 9),
    }


def _poly_pt(x_ft, y_ft):
    """Convert Cartesian field feet to Cell 1 pixel coords."""
    hx, hy = HOME_PLATE
    return (int(hx + x_ft * FIELD_SCALE), int(hy - y_ft * FIELD_SCALE))


# ---------------------------------------------------------------------------
# Cell 1: Field diagram
# ---------------------------------------------------------------------------

def _draw_field(draw, data, fonts=None):
    """Draw the baseball field in Cell 1 (x=0..266).

    Renders venue-specific outfield wall, warning track, foul lines, infield
    grass arc, base paths, mound, home plate, bases, and distance labels.
    """
    hx, hy = HOME_PLATE

    venue = data.get('venue', '')
    wall_poly = get_polygon(venue) or _DEFAULT_WALL_POLY
    wall_pts = [_poly_pt(x, y) for x, y in wall_poly]
    lf_pole  = wall_pts[0]
    rf_pole  = wall_pts[-1]

    # Warning track (15 ft inside wall)
    track_pts = []
    for x_ft, y_ft in wall_poly:
        dist   = math.sqrt(x_ft ** 2 + y_ft ** 2)
        factor = max(dist - 15, 50) / dist if dist > 0 else 1.0
        track_pts.append(_poly_pt(x_ft * factor, y_ft * factor))
    for i in range(len(track_pts) - 1):
        draw.line([track_pts[i], track_pts[i + 1]], fill=0, width=1)

    # Outfield fence
    for i in range(len(wall_pts) - 1):
        draw.line([wall_pts[i], wall_pts[i + 1]], fill=0, width=2)

    # Foul lines
    draw.line([HOME_PLATE, lf_pole], fill=0, width=1)
    draw.line([HOME_PLATE, rf_pole], fill=0, width=1)

    # Infield grass arc (from 3B side to 1B side, arcing through CF direction)
    r = _INFIELD_ARC_R
    bb_arc = [hx - r, hy - r, hx + r, hy + r]
    draw.arc(bb_arc, start=225, end=315, fill=0, width=1)

    # Base paths
    draw.line([HOME_PLATE, FIRST_BASE],  fill=0, width=2)
    draw.line([FIRST_BASE, SECOND_BASE], fill=0, width=2)
    draw.line([SECOND_BASE, THIRD_BASE], fill=0, width=2)
    draw.line([THIRD_BASE, HOME_PLATE],  fill=0, width=2)

    # Home plate (small pentagon)
    hp = 4
    draw.polygon([
        (hx,      hy + hp),
        (hx - hp, hy),
        (hx - hp + 2, hy - hp),
        (hx + hp - 2, hy - hp),
        (hx + hp, hy),
    ], outline=0)

    # Pitcher's mound
    draw.ellipse([MOUND[0] - 6, MOUND[1] - 6, MOUND[0] + 6, MOUND[1] + 6], outline=0)

    # Base diamonds (empty squares — _draw_runners fills occupied ones)
    base_sz = 5
    for bx, by in [FIRST_BASE, SECOND_BASE, THIRD_BASE]:
        draw.polygon([
            (bx, by - base_sz), (bx + base_sz, by),
            (bx, by + base_sz), (bx - base_sz, by),
        ], outline=0)

    # Distance labels at foul poles, deepest CF, and power alleys
    font_tiny = fonts.get('f9') if fonts else None
    if font_tiny:
        def _dist(xy):
            return round(math.sqrt(xy[0] ** 2 + xy[1] ** 2))

        def _angle(xy):
            return math.degrees(math.atan2(xy[0], xy[1]))

        deepest_idx = min(range(len(wall_pts)), key=lambda i: wall_pts[i][1])
        cf_pt   = wall_pts[deepest_idx]
        cf_dist = _dist(wall_poly[deepest_idx])
        lf_dist = _dist(wall_poly[0])
        rf_dist = _dist(wall_poly[-1])

        draw.text((cf_pt[0] - 10, cf_pt[1] - 10), str(cf_dist), font=font_tiny, fill=0)
        draw.text((lf_pole[0] + 2, lf_pole[1]),    str(lf_dist), font=font_tiny, fill=0)
        draw.text((rf_pole[0] - 18, rf_pole[1]),   str(rf_dist), font=font_tiny, fill=0)

        if len(wall_poly) >= 5:
            inner = [(i, wall_poly[i], wall_pts[i])
                     for i in range(1, len(wall_poly) - 1)
                     if i != deepest_idx]
            lf_alley = min(inner, key=lambda t: abs(_angle(t[1]) - (-22)), default=None)
            rf_alley = min(inner, key=lambda t: abs(_angle(t[1]) - 22), default=None)
            if lf_alley:
                pt = lf_alley[2]
                draw.text((pt[0] + 2, pt[1] - 2), str(_dist(lf_alley[1])), font=font_tiny, fill=0)
            if rf_alley:
                pt = rf_alley[2]
                draw.text((pt[0] - 18, pt[1] - 2), str(_dist(rf_alley[1])), font=font_tiny, fill=0)


def _draw_runners(draw, data):
    """Fill occupied base diamonds in Cell 1."""
    base_sz = 5
    for occupied, (bx, by) in [
        (data.get('runner_first'),  FIRST_BASE),
        (data.get('runner_second'), SECOND_BASE),
        (data.get('runner_third'),  THIRD_BASE),
    ]:
        if occupied:
            draw.polygon([
                (bx, by - base_sz), (bx + base_sz, by),
                (bx, by + base_sz), (bx - base_sz, by),
            ], fill=0, outline=0)


def _transform_hit_coords(api_x, api_y):
    """Transform MLB API hit coords to Cell 1 pixel space.

    API system: home plate ≈ (125, 200); X increases toward RF; Y decreases
    toward outfield.  Pixel home plate: (133, 440); FIELD_SCALE = 0.5 px/ft.
    Derivation: 1 API unit ≈ 2 ft; new_scale = 2 * 0.5 = 1.0.
    """
    px = 133 + (api_x - 125) * 1.0
    py = 440 - (200 - api_y) * 1.0
    return int(max(2, min(262, px))), int(max(5, min(475, py)))


def _draw_all_hits(draw, data, fonts=None):
    """Plot accumulated batted-ball markers in Cell 1.

    Current half-inning → filled/solid.  Previous half-innings → outline/ghost.

    Marker legend (matches ``_draw_pitch_zone`` legend in Cell 3):
      HR  — filled diamond + player last name
      Hit — filled circle r=4
      Out — X mark r=3
    """
    all_hits = data.get('all_hits', [])
    if not all_hits and data.get('hit_coords'):
        all_hits = [data['hit_coords']]
    if not all_hits:
        return

    current_inning = data.get('current_inning', 0)
    inning_state   = data.get('inning_state', 'Top')
    current_half   = 'top' if inning_state in ('Top', 'Middle') else 'bottom'
    font_tiny      = fonts.get('f9') if fonts else None

    for hit in all_hits:
        if isinstance(hit, dict):
            hx_c, hy_c = hit['x'], hit['y']
            is_hr  = hit.get('is_hr', False)
            is_hit = hit.get('is_hit', not hit.get('is_out', False))
            player = hit.get('player', '')
            this_half = (hit.get('inning') == current_inning
                         and hit.get('half', '').lower() == current_half)
        else:
            hx_c, hy_c = hit
            is_hr = False
            is_hit = True
            player = ''
            this_half = True

        px, py = _transform_hit_coords(hx_c, hy_c)

        if is_hr:
            r = 6
            if this_half:
                draw.polygon([(px, py-r), (px+r, py), (px, py+r), (px-r, py)], fill=0, outline=0)
                if player and font_tiny:
                    draw.text((px + r + 2, py - 4), player, font=font_tiny, fill=0)
            else:
                draw.polygon([(px, py-r), (px+r, py), (px, py+r), (px-r, py)], outline=0)
        elif is_hit:
            r = 4 if this_half else 3
            if this_half:
                draw.ellipse([px-r, py-r, px+r, py+r], fill=0, outline=0)
            else:
                draw.ellipse([px-r, py-r, px+r, py+r], outline=0)
        else:
            if this_half:
                r = 3
                draw.line([px-r, py-r, px+r, py+r], fill=0, width=1)
                draw.line([px+r, py-r, px-r, py+r], fill=0, width=1)
            else:
                draw.point((px, py), fill=0)


# ---------------------------------------------------------------------------
# Cell 2: Game info helpers
# ---------------------------------------------------------------------------

def _section_label(draw, fonts, x, y, text):
    """Small inverted label rectangle (e.g. 'BATTING')."""
    w = int(fonts['f9'].getlength(text)) + 6
    draw.rectangle([x, y, x + w, y + 11], fill=0)
    draw.text((x + 3, y + 1), text, font=fonts['f9'], fill=255)


def _draw_score_header(img, draw, fonts, data):
    """Inverted score panel in Cell 2. y 0-77."""
    x     = CELL2_X
    x_end = CELL2_X + CELL2_W - 1
    # Columns: abbr at x, big runs at x+85, R/H/E at x+172
    rhe_x = x + 172

    draw.rectangle([x, 0, x_end, 77], fill=0)

    draw.text((rhe_x,    5), 'R', font=fonts['f9'], fill=255)
    draw.text((rhe_x+18, 5), 'H', font=fonts['f9'], fill=255)
    draw.text((rhe_x+36, 5), 'E', font=fonts['f9'], fill=255)

    for i, team in enumerate(('away', 'home')):
        ty   = 14 + i * 30
        abbr = data.get(f'{team}_abbr', '')
        tid  = str(data.get(f'{team}_id', ''))
        runs = data.get(f'{team}_runs', 0)
        hits = data.get(f'{team}_hits', 0)
        errs = data.get(f'{team}_errors', 0)
        logo = _logo_small(abbr, tid)
        lx = x
        if logo:
            logo_inv = ImageOps.invert(logo.convert('L')).convert('1')
            img.paste(logo_inv, (lx, ty))
            lx += 30
        draw.text((lx,      ty + 2),  abbr,      font=fonts['f18'], fill=255)
        draw.text((lx + 55, ty - 2),  str(runs), font=fonts['f24'], fill=255)
        draw.text((rhe_x,    ty + 8), str(runs), font=fonts['f11'], fill=255)
        draw.text((rhe_x+18, ty + 8), str(hits), font=fonts['f11'], fill=255)
        draw.text((rhe_x+36, ty + 8), str(errs), font=fonts['f11'], fill=255)


def _draw_inning_state(img, draw, fonts, data):
    """Inning indicator + count + outs + mini bases in Cell 2. y 78-107."""
    x = CELL2_X
    y = 80
    sz = 8

    state = data.get('detailed_state', '')
    if state in ('Final', 'Game Over', 'Final: Tied'):
        draw.text((x, y), 'FINAL', font=fonts['f18'], fill=0)
    elif state in ('Scheduled', 'Pre-Game', 'Warmup'):
        draw.text((x, y), state, font=fonts['f14'], fill=0)
    else:
        inning_str = f"{data.get('inning_state','')} {data.get('inning_ordinal','')}"
        draw.text((x, y), inning_str, font=fonts['f18'], fill=0)
        draw.text((x + 120, y + 2), f"{data.get('balls',0)}-{data.get('strikes',0)}", font=fonts['f14'], fill=0)
        outs = data.get('outs', 0)
        for i in range(3):
            cx = x + 165 + i * 14
            cy = y + 10
            if i < outs:
                draw.ellipse([cx-5, cy-5, cx+5, cy+5], fill=0, outline=0)
            else:
                draw.ellipse([cx-5, cy-5, cx+5, cy+5], outline=0)

    # Mini base diamond — always shown
    mx, my = x + 228, y + 10
    for occupied, (bx, by) in [
        (data.get('runner_first'),  (mx + sz, my)),
        (data.get('runner_second'), (mx,      my - sz)),
        (data.get('runner_third'),  (mx - sz, my)),
    ]:
        pts = [(bx, by-sz//2), (bx+sz//2, by), (bx, by+sz//2), (bx-sz//2, by)]
        if occupied:
            draw.polygon(pts, fill=0, outline=0)
        else:
            draw.polygon(pts, outline=0)

    draw.line([(x, 107), (CELL2_X + CELL2_W - 1, 107)], fill=0)


def _draw_matchup(draw, fonts, data):
    """Batter + pitcher stats + on deck in Cell 2. y 110-220."""
    x = CELL2_X
    y = 110

    state = data.get('detailed_state', '')
    if state in ('Scheduled', 'Pre-Game', 'Warmup'):
        away, home = data.get('away_abbr', ''), data.get('home_abbr', '')
        draw.text((x, y),    'Probable Pitchers:', font=fonts['f11'], fill=0)
        draw.text((x, y+16), f"{away}: {data.get('away_probable','TBD')}", font=fonts['f14'], fill=0)
        draw.text((x, y+34), f"{home}: {data.get('home_probable','TBD')}", font=fonts['f14'], fill=0)
        draw.line([(x, 185), (CELL2_X + CELL2_W - 1, 185)], fill=0)
        return

    if state in ('Final', 'Game Over', 'Final: Tied'):
        draw.text((x, y),    f"WP: {data.get('winner','')}", font=fonts['f14'], fill=0)
        draw.text((x, y+18), f"LP: {data.get('loser','')}", font=fonts['f14'], fill=0)
        if data.get('save'):
            draw.text((x, y+36), f"SV: {data.get('save','')}", font=fonts['f14'], fill=0)
        draw.line([(x, 185), (CELL2_X + CELL2_W - 1, 185)], fill=0)
        return

    batter  = data.get('batter', {}) or {}
    pitcher = data.get('pitcher', {}) or {}
    on_deck = data.get('on_deck', {}) or {}

    _section_label(draw, fonts, x, y, 'BATTING')
    draw.text((x + 2, y + 13), batter.get('name', ''), font=fonts['f14'], fill=0)
    bs = batter.get('season', {})
    avg, hr, rbi = bs.get('avg', ''), bs.get('homeRuns', ''), bs.get('rbi', '')
    if avg:
        draw.text((x + 2, y + 28), f"{avg}  {hr}HR  {rbi}RBI", font=fonts['f9'], fill=0)

    py2 = y + 42
    _section_label(draw, fonts, x, py2, 'PITCHING')
    draw.text((x + 2, py2 + 13), pitcher.get('name', ''), font=fonts['f14'], fill=0)
    ps = pitcher.get('stats', {})
    pe = pitcher.get('season', {})
    era, ip, k = pe.get('era', ''), ps.get('inningsPitched', ''), ps.get('strikeOuts', '')
    if era:
        draw.text((x + 2, py2 + 28), f"{era} ERA  {ip}IP  {k}K", font=fonts['f9'], fill=0)

    od_name = on_deck.get('name', '')
    if od_name:
        py3 = y + 86
        _section_label(draw, fonts, x, py3, 'ON DECK')
        draw.text((x + 2, py3 + 13), od_name, font=fonts['f11'], fill=0)
        os_ = on_deck.get('season', {})
        od_avg, od_hr = os_.get('avg', ''), os_.get('homeRuns', '')
        if od_avg:
            draw.text((x + 2, py3 + 25), f"{od_avg}  {od_hr}HR", font=fonts['f9'], fill=0)

    draw.line([(x, 222), (CELL2_X + CELL2_W - 1, 222)], fill=0)


def _draw_last_play(draw, fonts, data):
    """Last play description, word-wrapped, in Cell 2. y 225-254."""
    x = CELL2_X
    y = 225
    last_play = data.get('last_play', '')
    if not last_play:
        return
    _section_label(draw, fonts, x, y, 'LAST PLAY')
    lines = _word_wrap(last_play, fonts['f11'], CELL2_W - 4)
    for i, line in enumerate(lines[:2]):
        draw.text((x, y + 13 + i * 13), line, font=fonts['f11'], fill=0)
    draw.line([(x, 254), (CELL2_X + CELL2_W - 1, 254)], fill=0)


def _draw_mini_linescore(draw, fonts, data):
    """Inning-by-inning linescore in Cell 2, anchored to bottom."""
    x = CELL2_X
    # Anchor near bottom: 3 rows of f9 (~11px), header, venue ≈ 58px
    y = EPD_HEIGHT - 58

    innings = data.get('innings', [])
    if not innings:
        return

    away_abbr = data.get('away_abbr', '')
    home_abbr = data.get('home_abbr', '')

    max_inn  = min(len(innings), 9)
    col_w    = 16    # narrower columns to fit CELL2_W=266
    label_w  = 30
    rhe_col  = 15
    rhe_x    = x + label_w + max_inn * col_w + 4

    # Header
    for i in range(max_inn):
        draw.text((x + label_w + i * col_w, y), str(innings[i]['num']), font=fonts['f9'], fill=0)
    draw.text((rhe_x,          y), 'R', font=fonts['f9'], fill=0)
    draw.text((rhe_x+rhe_col,  y), 'H', font=fonts['f9'], fill=0)
    draw.text((rhe_x+2*rhe_col,y), 'E', font=fonts['f9'], fill=0)

    # Away row
    ay2 = y + 13
    draw.text((x, ay2), away_abbr, font=fonts['f9'], fill=0)
    for i in range(max_inn):
        val = innings[i].get('away_runs')
        draw.text((x + label_w + i * col_w, ay2), str(val if val is not None else ''), font=fonts['f9'], fill=0)
    draw.text((rhe_x,          ay2), str(data.get('away_runs',   0)), font=fonts['f9'], fill=0)
    draw.text((rhe_x+rhe_col,  ay2), str(data.get('away_hits',   0)), font=fonts['f9'], fill=0)
    draw.text((rhe_x+2*rhe_col,ay2), str(data.get('away_errors', 0)), font=fonts['f9'], fill=0)

    # Home row
    hy2 = ay2 + 13
    draw.text((x, hy2), home_abbr, font=fonts['f9'], fill=0)
    for i in range(max_inn):
        val = innings[i].get('home_runs')
        draw.text((x + label_w + i * col_w, hy2), str(val if val is not None else ''), font=fonts['f9'], fill=0)
    draw.text((rhe_x,          hy2), str(data.get('home_runs',   0)), font=fonts['f9'], fill=0)
    draw.text((rhe_x+rhe_col,  hy2), str(data.get('home_hits',   0)), font=fonts['f9'], fill=0)
    draw.text((rhe_x+2*rhe_col,hy2), str(data.get('home_errors', 0)), font=fonts['f9'], fill=0)

    venue = data.get('venue', '')
    if venue:
        draw.text((x, hy2 + 14), venue, font=fonts['f9'], fill=0)


# ---------------------------------------------------------------------------
# Cell 3: Pitch zone
# ---------------------------------------------------------------------------

def _draw_pitch_zone(draw, fonts, data):
    """Strike zone diagram with current at-bat pitches in Cell 3.

    Strike zone box is the coordinate reference:
      px: -0.708 to +0.708 ft  (17-inch plate width)
      pz:  1.5   to  3.5   ft  (typical zone height)
    """
    x        = CELL3_X
    panel_cx = CELL3_X + CELL3_W // 2    # 667

    # Strike zone box — centred in Cell 3
    zone_w, zone_h = 120, 120
    zl = panel_cx - zone_w // 2    # 607
    zr = panel_cx + zone_w // 2    # 727
    zt = 100
    zb = zt + zone_h               # 220

    ZONE_PX   = 0.708
    ZONE_PZ_LO, ZONE_PZ_HI = 1.5, 3.5

    def to_px(px_c, pz_c):
        tx = zl + int((px_c + ZONE_PX) / (2 * ZONE_PX) * zone_w)
        ty = zb - int((pz_c - ZONE_PZ_LO) / (ZONE_PZ_HI - ZONE_PZ_LO) * zone_h)
        tx = max(x + 4, min(797, tx))
        ty = max(zt + 2, min(zb + 30, ty))
        return tx, ty

    pitches = data.get('pitches', [])
    state   = data.get('detailed_state', '')
    balls   = data.get('balls', 0)
    strikes = data.get('strikes', 0)

    # Section label + count
    _section_label(draw, fonts, x, 5, 'PITCH ZONE')
    n_p = len(pitches)
    count_txt = f"{n_p} pitches"
    if state not in ('Final', 'Game Over', 'Final: Tied', 'Completed Early'):
        count_txt += f"  {balls}-{strikes}"
    draw.text((x + 72, 6), count_txt, font=fonts['f9'], fill=0)

    # Venue name (ballpark context)
    venue = data.get('venue', '')
    if venue:
        vw = int(fonts['f9'].getlength(venue))
        vx = max(x, panel_cx - vw // 2)
        draw.text((vx, 20), venue, font=fonts['f9'], fill=0)

    # Batter/pitcher brief
    batter_name  = (data.get('batter') or {}).get('name', '')
    pitcher_name = (data.get('pitcher') or {}).get('name', '')
    if batter_name:
        draw.text((x, 35), f"AB: {batter_name}", font=fonts['f9'], fill=0)
    if pitcher_name:
        draw.text((x, 47), f"P:  {pitcher_name}", font=fonts['f9'], fill=0)

    # "RHB" catcher-perspective label
    draw.text((x + 2, zb + 4), 'RHB', font=fonts['f9'], fill=0)

    # Horizontal line separating batter labels from zone
    draw.line([(x, 60), (x + CELL3_W - 1, 60)], fill=0)

    # Strike zone box
    draw.rectangle([zl, zt, zr, zb], outline=0)

    # 9-zone grid lines
    tw = zone_w // 3    # 40px
    th = zone_h // 3    # 40px
    draw.line([zl+tw,   zt, zl+tw,   zb], fill=0)
    draw.line([zl+2*tw, zt, zl+2*tw, zb], fill=0)
    draw.line([zl, zt+th,   zr, zt+th  ], fill=0)
    draw.line([zl, zt+2*th, zr, zt+2*th], fill=0)

    # Home plate indicator (V below zone)
    phy = zb + 6
    draw.line([panel_cx - 10, phy, panel_cx,      phy + 11], fill=0)
    draw.line([panel_cx + 10, phy, panel_cx,      phy + 11], fill=0)
    draw.line([panel_cx - 10, phy, panel_cx + 10, phy     ], fill=0)

    # Pitch markers
    r = 5
    for pitch in pitches:
        px_c = pitch.get('px')
        pz_c = pitch.get('pz')
        if px_c is None or pz_c is None:
            continue
        bx, by = to_px(px_c, pz_c)
        code = pitch.get('code', '')
        if code in ('S', 'C', 'T'):
            draw.ellipse([bx-r, by-r, bx+r, by+r], fill=0, outline=0)
        elif code == 'F':
            draw.ellipse([bx-r, by-r, bx+r, by+r], outline=0)
            draw.line([bx-r, by, bx+r, by], fill=0)
        elif code == 'X':
            draw.rectangle([bx-r, by-r, bx+r, by+r], fill=0)
        else:
            draw.ellipse([bx-r, by-r, bx+r, by+r], outline=0)

    # Separator below zone + plate indicator
    draw.line([(x, zb + 24), (x + CELL3_W - 1, zb + 24)], fill=0)

    # Pitch log (type, speed, code) below separator
    log_y = zb + 30
    draw.text((x, log_y), 'SEQ  TYPE      SPD  CODE', font=fonts['f9'], fill=0)
    log_y += 12
    draw.line([(x, log_y - 1), (x + CELL3_W - 1, log_y - 1)], fill=0)
    for pitch in pitches:
        if log_y + 11 > EPD_HEIGHT - 2:
            break
        seq   = pitch.get('seq', '')
        ptype = pitch.get('pitch_type', '')[:9]
        speed = pitch.get('speed')
        code  = pitch.get('code', '')
        spd_s = f'{speed:.0f}' if speed else '--'
        line  = f"{str(seq):>2}  {ptype:<9}  {spd_s:>3}  {code}"
        draw.text((x, log_y), line, font=fonts['f9'], fill=0)
        log_y += 11


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _word_wrap(text, font, max_width):
    """Simple word wrap returning a list of lines."""
    words = text.split()
    lines, current = [], ''
    for word in words:
        test = f"{current} {word}".strip()
        try:
            w = font.getlength(test)
        except AttributeError:
            w = len(test) * 8
        if w > max_width and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def render_field_view(data, dark_mode=False):
    """Render the three-cell field view. Returns an 800x480 1-bit PIL Image.

    Cell 1 (left, x=0..266):   Venue-specific field diagram — outfield wall with
                                ballpark dimensions, infield diamond, mound, base
                                runners, and accumulated hit/out markers.
    Cell 2 (middle, x=267..532): Live game info — score, inning/count/outs,
                                batter, pitcher, last play, inning linescore.
    Cell 3 (right, x=534..799): Pitch zone — current at-bat pitches plotted on
                                the 9-zone strike zone grid with pitch log.
    """
    img  = Image.new('1', (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(img)
    fonts = _load_fonts()

    # Cell dividers
    draw.line([(DIV1_X, 0), (DIV1_X, EPD_HEIGHT)], fill=0, width=2)
    draw.line([(DIV2_X, 0), (DIV2_X, EPD_HEIGHT)], fill=0, width=2)

    # Cell 1: field
    _draw_field(draw, data, fonts)
    _draw_runners(draw, data)
    _draw_all_hits(draw, data, fonts)

    # Cell 2: game info
    _draw_score_header(img, draw, fonts, data)
    _draw_inning_state(img, draw, fonts, data)
    _draw_matchup(draw, fonts, data)
    _draw_last_play(draw, fonts, data)
    _draw_mini_linescore(draw, fonts, data)

    # Cell 3: pitch zone
    _draw_pitch_zone(draw, fonts, data)

    if dark_mode:
        img = ImageOps.invert(img.convert('L')).convert('1')

    return img
