import os
import math
from PIL import Image, ImageDraw, ImageFont, ImageOps

from generate_image import (
    picdir, _logo_small, _load_logo_gray, draw_diamond, draw_circle,
)
from stadium_polygons import get_polygon

EPD_WIDTH = 800
EPD_HEIGHT = 480

# Field geometry constants — derived from FIELD_SCALE = 0.75 px/ft.
# 0.75 is the maximum scale that keeps every MLB ballpark on the 400 px wide panel
# (binding constraint: Wrigley LF foul pole at 355 ft, -45° lands at x ≈ 12 px).
# Base paths: 90 ft × 0.75 = 67.5 px per side; at 45° → x/y offset ≈ 47.7 px.
# Home↔Second diagonal: 90√2 ≈ 127.3 ft × 0.75 ≈ 95.5 px straight up.
# Mound: 60.5 ft × 0.75 ≈ 45.4 px from home (47.5% of home-to-second).
HOME_PLATE = (200, 420)
FIRST_BASE = (248, 372)
SECOND_BASE = (200, 325)
THIRD_BASE = (152, 372)
MOUND = (200, 375)

# Pixels per foot for field rendering
FIELD_SCALE = 0.75

# Fallback wall polygon used when the venue isn't recognized.
# Generic symmetric 400-ft park. Cartesian (x_ft, y_ft), home plate at origin.
_DEFAULT_WALL_POLY = [
    (-233.3, 233.3),   # LF foul pole, 330 ft
    (-109.6, 343.6),   # LF-CF gap, 360 ft
    (0.0,    400.0),   # deep CF, 400 ft
    (109.6,  343.6),   # RF-CF gap, 360 ft
    (233.3,  233.3),   # RF foul pole, 330 ft
]


def _load_fonts():
    """Load fonts."""
    font_path = os.path.join(picdir, 'Font.ttc')
    return {
        'f24': ImageFont.truetype(font_path, 24),
        'f18': ImageFont.truetype(font_path, 18),
        'f14': ImageFont.truetype(font_path, 14),
        'f11': ImageFont.truetype(font_path, 11),
        'f9':  ImageFont.truetype(font_path, 9),
    }


def _poly_pt(x_ft, y_ft):
    """Convert Cartesian field feet to pixel coords.
    x_ft: positive = RF/1B side; y_ft: positive = toward CF.
    """
    hx, hy = HOME_PLATE
    return (int(hx + x_ft * FIELD_SCALE), int(hy - y_ft * FIELD_SCALE))


def _draw_field(draw, data, fonts=None):
    """Draw the baseball field diagram on the left half (0-399).
    Uses venue-specific outfield dimensions when available.
    """
    hx, hy = HOME_PLATE

    venue = data.get('venue', '')
    wall_poly = get_polygon(venue) or _DEFAULT_WALL_POLY  # [(x_ft, y_ft), ...]

    wall_pts = [_poly_pt(x, y) for x, y in wall_poly]
    lf_pole  = wall_pts[0]
    rf_pole  = wall_pts[-1]

    # Warning track: 15ft inside the outfield wall (thin inner arc)
    track_pts = []
    for x_ft, y_ft in wall_poly:
        dist   = math.sqrt(x_ft ** 2 + y_ft ** 2)
        factor = max(dist - 15, 50) / dist if dist > 0 else 1.0
        track_pts.append(_poly_pt(x_ft * factor, y_ft * factor))
    for i in range(len(track_pts) - 1):
        draw.line([track_pts[i], track_pts[i + 1]], fill=0, width=1)

    # Outfield fence (multi-segment, thicker line for prominence)
    for i in range(len(wall_pts) - 1):
        draw.line([wall_pts[i], wall_pts[i + 1]], fill=0, width=2)

    # Foul lines (home plate to foul poles)
    draw.line([HOME_PLATE, lf_pole], fill=0, width=1)
    draw.line([HOME_PLATE, rf_pole], fill=0, width=1)

    # Infield arc: edge of infield grass, arcing from 3B side to 1B side through CF
    # PIL arc angles: 0=east, 90=south, 180=west, 270=north (up on screen = toward CF)
    # Second base is ~95 px from home plate (127.3 ft × 0.75), so radius > 95 clears it.
    r_arc = 110  # ~15 px past second base (95 px from home)
    bb_arc = [hx - r_arc, hy - r_arc, hx + r_arc, hy + r_arc]
    draw.arc(bb_arc, start=225, end=315, fill=0, width=1)

    # Base paths (infield diamond) — slightly bolder
    draw.line([HOME_PLATE, FIRST_BASE],  fill=0, width=2)
    draw.line([FIRST_BASE, SECOND_BASE], fill=0, width=2)
    draw.line([SECOND_BASE, THIRD_BASE], fill=0, width=2)
    draw.line([THIRD_BASE, HOME_PLATE],  fill=0, width=2)

    # Home plate (small pentagon)
    hp_size = 5
    draw.polygon([
        (hx, hy + hp_size),
        (hx - hp_size, hy),
        (hx - hp_size + 2, hy - hp_size),
        (hx + hp_size - 2, hy - hp_size),
        (hx + hp_size, hy),
    ], outline=0)

    # Pitcher's mound
    draw.ellipse([MOUND[0] - 8, MOUND[1] - 8, MOUND[0] + 8, MOUND[1] + 8], outline=0)

    # Bases (empty squares — filled by _draw_runners if occupied)
    base_size = 6
    for bx, by in [FIRST_BASE, SECOND_BASE, THIRD_BASE]:
        draw.polygon([
            (bx, by - base_size), (bx + base_size, by),
            (bx, by + base_size), (bx - base_size, by),
        ], outline=0)

    # Distance labels: foul poles, deepest CF, and power alleys
    font_tiny = fonts.get('f9') if fonts else None
    if font_tiny:
        def _dist(xy):
            """Dist."""
            return round(math.sqrt(xy[0] ** 2 + xy[1] ** 2))

        def _angle(xy):
            """Bearing in degrees from CF axis: -45=LF pole, 0=CF, +45=RF pole."""
            return math.degrees(math.atan2(xy[0], xy[1]))

        # Deepest CF point (highest y on screen = lowest pixel y)
        deepest_idx = min(range(len(wall_pts)), key=lambda i: wall_pts[i][1])
        cf_pt   = wall_pts[deepest_idx]
        cf_dist = _dist(wall_poly[deepest_idx])
        lf_dist = _dist(wall_poly[0])
        rf_dist = _dist(wall_poly[-1])

        # Always label: LF pole, deepest point, RF pole
        draw.text((cf_pt[0] - 10, cf_pt[1] - 10), str(cf_dist), font=font_tiny, fill=0)
        draw.text((lf_pole[0] + 2, lf_pole[1]),    str(lf_dist), font=font_tiny, fill=0)
        draw.text((rf_pole[0] - 18, rf_pole[1]),   str(rf_dist), font=font_tiny, fill=0)

        # Label power alleys: find points closest to ±22° bearing (LF/RF alleys)
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
    """Fill in occupied bases."""
    base_size = 6
    bases = [
        (data.get('runner_first'), FIRST_BASE),
        (data.get('runner_second'), SECOND_BASE),
        (data.get('runner_third'), THIRD_BASE),
    ]
    for occupied, (bx, by) in bases:
        if occupied:
            draw.polygon([
                (bx, by - base_size), (bx + base_size, by),
                (bx, by + base_size), (bx - base_size, by),
            ], fill=0, outline=0)


def _transform_hit_coords(api_x, api_y):
    """Transform API hit coordinates to pixel space.
    API: home plate ~(125, 200), X right, Y decreases toward outfield
    Pixel: home plate (200, 420)
    """
    px = 200 + (api_x - 125) * 1.5
    py = 420 - (200 - api_y) * 1.5
    # Clamp to field region
    px = max(5, min(395, px))
    py = max(5, min(475, py))
    return int(px), int(py)


def _draw_all_hits(draw, data, fonts=None):
    """Plot all batted balls accumulated this game.

    Current half-inning events → filled markers.
    Previous half-inning events → outline/ghost markers.

    Marker key:
      HR  — filled diamond + player last name  (outline diamond if prev inning)
      Hit — filled circle r=4                  (open circle r=3 if prev inning)
      Out — X mark r=3                         (tiny dot r=1 if prev inning)

    Each hit may be a (x, y) tuple (legacy) or a dict with
    x, y, is_hr, is_hit, is_out, player, inning, half keys.
    """
    all_hits = data.get('all_hits', [])
    if not all_hits and data.get('hit_coords'):
        all_hits = [data['hit_coords']]
    if not all_hits:
        return

    current_inning = data.get('current_inning', 0)
    inning_state = data.get('inning_state', 'Top')
    # 'Top'/'Middle' = currently playing/just finished top half
    current_half = 'top' if inning_state in ('Top', 'Middle') else 'bottom'

    font_tiny = fonts.get('f9') if fonts else None

    for hit in all_hits:
        if isinstance(hit, dict):
            hx_coord, hy_coord = hit['x'], hit['y']
            is_hr  = hit.get('is_hr', False)
            is_hit = hit.get('is_hit', not hit.get('is_out', False))
            player = hit.get('player', '')
            this_half = (hit.get('inning') == current_inning
                         and hit.get('half', '').lower() == current_half)
        else:
            hx_coord, hy_coord = hit
            is_hr = False
            is_hit = True
            player = ''
            this_half = True  # legacy tuples treated as current

        px, py = _transform_hit_coords(hx_coord, hy_coord)

        if is_hr:
            r = 7
            if this_half:
                # Filled diamond + player name
                draw.polygon([(px, py-r),(px+r, py),(px, py+r),(px-r, py)], fill=0, outline=0)
                if player and font_tiny:
                    draw.text((px + r + 2, py - 4), player, font=font_tiny, fill=0)
            else:
                # Outline diamond only
                draw.polygon([(px, py-r),(px+r, py),(px, py+r),(px-r, py)], outline=0)
        elif is_hit:
            if this_half:
                # Filled circle
                r = 4
                draw.ellipse([px-r, py-r, px+r, py+r], fill=0, outline=0)
            else:
                # Open circle (smaller)
                r = 3
                draw.ellipse([px-r, py-r, px+r, py+r], outline=0)
        else:
            if this_half:
                # X mark
                r = 3
                draw.line([px-r, py-r, px+r, py+r], fill=0, width=1)
                draw.line([px+r, py-r, px-r, py+r], fill=0, width=1)
            else:
                # Tiny dot for previous-inning outs
                draw.point((px, py), fill=0)


def _section_label(draw, fonts, x, y, text):
    """Draw a small inverted label rectangle (e.g. 'BATTING')."""
    w = int(fonts['f9'].getlength(text)) + 6
    draw.rectangle([x, y, x + w, y + 11], fill=0)
    draw.text((x + 3, y + 1), text, font=fonts['f9'], fill=255)


def _draw_score_header(img, draw, fonts, data):
    """Inverted score panel: black background, white text. y 0-77."""
    x = 408
    rhe_x = x + 222   # R/H/E columns

    # Black scoreboard header background
    draw.rectangle([x - 2, 0, 799, 77], fill=0)

    # Column headers in white
    draw.text((rhe_x,    5), 'R', font=fonts['f9'], fill=255)
    draw.text((rhe_x+22, 5), 'H', font=fonts['f9'], fill=255)
    draw.text((rhe_x+44, 5), 'E', font=fonts['f9'], fill=255)

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
            # Invert logo for dark background
            logo_inv = ImageOps.invert(logo.convert('L')).convert('1')
            img.paste(logo_inv, (lx, ty))
            lx += 30
        draw.text((lx,      ty + 2),  abbr,      font=fonts['f18'], fill=255)
        draw.text((lx + 55, ty - 2),  str(runs), font=fonts['f24'], fill=255)
        draw.text((rhe_x,    ty + 8), str(runs), font=fonts['f11'], fill=255)
        draw.text((rhe_x+22, ty + 8), str(hits), font=fonts['f11'], fill=255)
        draw.text((rhe_x+44, ty + 8), str(errs), font=fonts['f11'], fill=255)


def _draw_inning_state(img, draw, fonts, data):
    """Inning indicator bar with count, outs, mini bases. y 78-107."""
    x  = 408
    y  = 80
    sz = 8

    state = data.get('detailed_state', '')
    if state in ('Final', 'Game Over', 'Final: Tied'):
        draw.text((x, y), 'FINAL', font=fonts['f18'], fill=0)
    elif state in ('Scheduled', 'Pre-Game', 'Warmup'):
        draw.text((x, y), state, font=fonts['f14'], fill=0)
    else:
        # f18 for the inning — dominant element in this row
        draw.text((x, y), f"{data.get('inning_state','')} {data.get('inning_ordinal','')}", font=fonts['f18'], fill=0)
        draw.text((x + 135, y + 2), f"{data.get('balls',0)}-{data.get('strikes',0)}", font=fonts['f14'], fill=0)
        outs = data.get('outs', 0)
        for i in range(3):
            cx = x + 185 + i * 15
            cy = y + 10
            if i < outs:
                draw.ellipse([cx-5, cy-5, cx+5, cy+5], fill=0, outline=0)
            else:
                draw.ellipse([cx-5, cy-5, cx+5, cy+5], outline=0)

    # Mini bases (always shown)
    mx, my = x + 290, y + 10
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

    draw.line([(x, 107), (798, 107)], fill=0)


def _draw_matchup(draw, fonts, data):
    """Batter + pitcher stats + on deck. y 110-185."""
    x = 408
    y = 110

    state = data.get('detailed_state', '')
    if state in ('Scheduled', 'Pre-Game', 'Warmup'):
        draw.text((x, y), 'Probable Pitchers:', font=fonts['f11'], fill=0)
        away, home = data.get('away_abbr', ''), data.get('home_abbr', '')
        draw.text((x, y+16), f"{away}: {data.get('away_probable','TBD')}", font=fonts['f14'], fill=0)
        draw.text((x, y+34), f"{home}: {data.get('home_probable','TBD')}", font=fonts['f14'], fill=0)
        draw.line([(x, 185), (798, 185)], fill=0)
        return

    if state in ('Final', 'Game Over', 'Final: Tied'):
        draw.text((x, y),    f"WP: {data.get('winner','')}", font=fonts['f14'], fill=0)
        draw.text((x, y+18), f"LP: {data.get('loser','')}", font=fonts['f14'], fill=0)
        if data.get('save'):
            draw.text((x, y+36), f"SV: {data.get('save','')}", font=fonts['f14'], fill=0)
        draw.line([(x, 185), (798, 185)], fill=0)
        return

    batter  = data.get('batter', {}) or {}
    pitcher = data.get('pitcher', {}) or {}
    on_deck = data.get('on_deck', {}) or {}

    # Batter
    _section_label(draw, fonts, x, y, 'BATTING')
    draw.text((x + 2, y + 13), batter.get('name', ''), font=fonts['f14'], fill=0)
    bs = batter.get('season', {})
    avg, hr, rbi = bs.get('avg',''), bs.get('homeRuns',''), bs.get('rbi','')
    if avg:
        draw.text((x + 2, y + 28), f"{avg}  {hr}HR  {rbi}RBI", font=fonts['f9'], fill=0)

    # Pitcher
    py2 = y + 42
    _section_label(draw, fonts, x, py2, 'PITCHING')
    draw.text((x + 2, py2 + 13), pitcher.get('name', ''), font=fonts['f14'], fill=0)
    ps = pitcher.get('stats', {})
    pe = pitcher.get('season', {})
    era, ip, k = pe.get('era',''), ps.get('inningsPitched',''), ps.get('strikeOuts','')
    if era:
        draw.text((x + 2, py2 + 28), f"{era} ERA  {ip}IP  {k}K", font=fonts['f9'], fill=0)

    # On Deck
    od_name = on_deck.get('name', '')
    if od_name:
        py3 = y + 86
        _section_label(draw, fonts, x, py3, 'ON DECK')
        draw.text((x + 2, py3 + 13), od_name, font=fonts['f11'], fill=0)
        os_ = on_deck.get('season', {})
        od_avg, od_hr = os_.get('avg',''), os_.get('homeRuns','')
        if od_avg:
            draw.text((x + 2, py3 + 25), f"{od_avg}  {od_hr}HR", font=fonts['f9'], fill=0)

    draw.line([(x, 222), (798, 222)], fill=0)


def _draw_last_play(draw, fonts, data):
    """Last play description, word-wrapped. y 225-252."""
    x = 408
    y = 225
    last_play = data.get('last_play', '')
    if not last_play:
        return
    _section_label(draw, fonts, x, y, 'LAST PLAY')
    lines = _word_wrap(last_play, fonts['f11'], 385)
    for i, line in enumerate(lines[:2]):
        draw.text((x, y + 13 + i * 13), line, font=fonts['f11'], fill=0)
    draw.line([(x, 254), (798, 254)], fill=0)


def _draw_pitch_zone(draw, fonts, data):
    """Strike zone with current at-bat pitches. y 257-end.

    The strike zone box IS the coordinate reference:
      - px: -0.708 to +0.708 ft  →  zl to zr  (17-inch plate width)
      - pz:  1.5   to  3.5   ft  →  zb to zt  (typical zone height)
    Pitches outside those ranges naturally plot outside the box.
    """
    x = 408
    panel_cx = 604   # (408 + 800) // 2

    # Strike zone box — large and centered in the right panel
    zone_w, zone_h = 120, 100
    zl = panel_cx - zone_w // 2   # 544
    zr = panel_cx + zone_w // 2   # 664
    zt = 275
    zb = zt + zone_h               # 375

    # px in [-0.708, 0.708], pz in [1.5, 3.5]  →  pixel coords
    # Pitches outside these ranges land outside the zone box.
    ZONE_PX = 0.708
    ZONE_PZ_LO, ZONE_PZ_HI = 1.5, 3.5

    def to_px(px_c, pz_c):
        """To px."""
        tx = zl + int((px_c + ZONE_PX) / (2 * ZONE_PX) * zone_w)
        ty = zb - int((pz_c - ZONE_PZ_LO) / (ZONE_PZ_HI - ZONE_PZ_LO) * zone_h)
        # Clamp so markers don't fall off the right panel
        tx = max(x + 4, min(797, tx))
        ty = max(258, min(zb + 30, ty))
        return tx, ty

    pitches = data.get('pitches', [])
    state   = data.get('detailed_state', '')
    balls   = data.get('balls', 0)
    strikes = data.get('strikes', 0)

    # Section label + count
    _section_label(draw, fonts, x, 257, 'PITCH ZONE')
    n_p = len(pitches)
    count_txt = f"{n_p} pitches"
    if state not in ('Final', 'Game Over', 'Final: Tied', 'Completed Early'):
        count_txt += f"  {balls}-{strikes}"
    draw.text((x + 68, 258), count_txt, font=fonts['f9'], fill=0)

    # Strike zone box
    draw.rectangle([zl, zt, zr, zb], outline=0)

    # 9-zone grid lines
    tw = zone_w // 3   # 40px
    th = zone_h // 3   # 33px
    draw.line([zl+tw,   zt, zl+tw,   zb], fill=0)
    draw.line([zl+2*tw, zt, zl+2*tw, zb], fill=0)
    draw.line([zl, zt+th,   zr, zt+th  ], fill=0)
    draw.line([zl, zt+2*th, zr, zt+2*th], fill=0)

    # Home plate indicator (V below zone, centered on zone)
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
        if code in ('S', 'C', 'T'):       # Strike (swinging / called / foul tip)
            draw.ellipse([bx-r, by-r, bx+r, by+r], fill=0, outline=0)
        elif code == 'F':                  # Foul — open with crossbar
            draw.ellipse([bx-r, by-r, bx+r, by+r], outline=0)
            draw.line([bx-r, by, bx+r, by], fill=0)
        elif code == 'X':                  # In play — filled square
            draw.rectangle([bx-r, by-r, bx+r, by+r], fill=0)
        else:                              # Ball — open circle
            draw.ellipse([bx-r, by-r, bx+r, by+r], outline=0)

    draw.line([(x, zb + 22), (798, zb + 22)], fill=0)


def _word_wrap(text, font, max_width):
    """Simple word wrap. Returns list of lines."""
    words = text.split()
    lines = []
    current = ''
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


def _draw_mini_linescore(draw, fonts, data):
    """Inning-by-inning linescore table anchored to bottom of display."""
    x = 408
    # Anchor linescore to bottom: 3 rows of f9 (~11px each) + header + venue = ~55px
    y = EPD_HEIGHT - 58

    innings = data.get('innings', [])
    if not innings:
        return

    away_abbr = data.get('away_abbr', '')
    home_abbr = data.get('home_abbr', '')

    max_inn = min(len(innings), 10)
    col_w   = 24
    label_w = 36
    rhe_x   = x + label_w + max_inn * col_w + 4

    # Header
    for i in range(max_inn):
        draw.text((x + label_w + i * col_w, y), str(innings[i]['num']), font=fonts['f9'], fill=0)
    draw.text((rhe_x,    y), 'R', font=fonts['f9'], fill=0)
    draw.text((rhe_x+18, y), 'H', font=fonts['f9'], fill=0)
    draw.text((rhe_x+36, y), 'E', font=fonts['f9'], fill=0)

    # Away
    ay2 = y + 13
    draw.text((x, ay2), away_abbr, font=fonts['f9'], fill=0)
    for i in range(max_inn):
        val = innings[i].get('away_runs')
        draw.text((x + label_w + i * col_w, ay2), str(val if val is not None else ''), font=fonts['f9'], fill=0)
    draw.text((rhe_x,    ay2), str(data.get('away_runs',   0)), font=fonts['f9'], fill=0)
    draw.text((rhe_x+18, ay2), str(data.get('away_hits',   0)), font=fonts['f9'], fill=0)
    draw.text((rhe_x+36, ay2), str(data.get('away_errors', 0)), font=fonts['f9'], fill=0)

    # Home
    hy2 = ay2 + 13
    draw.text((x, hy2), home_abbr, font=fonts['f9'], fill=0)
    for i in range(max_inn):
        val = innings[i].get('home_runs')
        draw.text((x + label_w + i * col_w, hy2), str(val if val is not None else ''), font=fonts['f9'], fill=0)
    draw.text((rhe_x,    hy2), str(data.get('home_runs',   0)), font=fonts['f9'], fill=0)
    draw.text((rhe_x+18, hy2), str(data.get('home_hits',   0)), font=fonts['f9'], fill=0)
    draw.text((rhe_x+36, hy2), str(data.get('home_errors', 0)), font=fonts['f9'], fill=0)

    venue = data.get('venue', '')
    if venue:
        draw.text((x, hy2 + 14), venue, font=fonts['f9'], fill=0)


def render_field_view(data, dark_mode=False):
    """Render the field view display. Returns an 800x480 1-bit PIL Image."""
    img = Image.new('1', (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(img)
    fonts = _load_fonts()

    # Vertical divider (3px for a bolder split)
    draw.line([(400, 0), (400, EPD_HEIGHT)], fill=0, width=3)

    # Left half: field + all accumulated hit/out markers
    _draw_field(draw, data, fonts)
    _draw_runners(draw, data)
    _draw_all_hits(draw, data, fonts)

    # Right half: all game info
    _draw_score_header(img, draw, fonts, data)
    _draw_inning_state(img, draw, fonts, data)
    _draw_matchup(draw, fonts, data)
    _draw_last_play(draw, fonts, data)
    _draw_pitch_zone(draw, fonts, data)
    _draw_mini_linescore(draw, fonts, data)

    if dark_mode:
        img = ImageOps.invert(img.convert('L')).convert('1')

    return img
