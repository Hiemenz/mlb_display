import os
import math
from PIL import Image, ImageDraw, ImageFont, ImageOps

from generate_image import (
    picdir, _logo_small, _load_logo_gray, draw_diamond, draw_circle,
)

EPD_WIDTH = 800
EPD_HEIGHT = 480

# Field geometry constants — derived from FIELD_SCALE = 0.70 px/ft.
# Base paths: 90 ft × 0.70 = 63 px per side; at 45° → x/y offset ≈ 44.5 px.
# Home↔Second diagonal: 90√2 ≈ 127.3 ft × 0.70 ≈ 89 px straight up.
# Mound: 60.5 ft × 0.70 ≈ 42 px from home (47.5% of home-to-second).
HOME_PLATE = (200, 420)
FIRST_BASE = (245, 375)
SECOND_BASE = (200, 331)
THIRD_BASE = (155, 375)
MOUND = (200, 378)

# Pixels per foot for field rendering
FIELD_SCALE = 0.70

# Ballpark wall definitions: list of (distance_ft, angle_deg) pairs.
# angle_deg: negative=LF side, 0=straight CF, positive=RF side.
# Standard 9-point helper: LF pole, LF corner, LCF, L-CF, CF, R-CF, RCF, RF corner, RF pole
# angles: -45, -33, -22.5, -11, 0, +11, +22.5, +33, +45
_w = lambda a, b, c, d, e, f, g, h, i: [
    (a, -45), (b, -33), (c, -22.5), (d, -11), (e, 0), (f, 11), (g, 22.5), (h, 33), (i, 45)
]

BALLPARK_DIMENSIONS = {
    # AL East
    'Yankee Stadium':  _w(318, 390, 399, 405, 408, 400, 385, 353, 314),
    'Fenway Park': [
        # Green Monster: nearly-straight wall from LF foul pole (310) to LCF corner (379).
        # No straight-away CF — wall angles sharply from LCF to the Triangle (420),
        # then cuts back to the RC bullpen before the short Pesky Pole (302).
        (310, -45),   # LF foul pole (Green Monster base)
        (379, -25),   # LCF corner — end of Green Monster
        (390, -12),   # Left-center
        (420,  -4),   # Triangle — deepest (just left of dead center)
        (380,  17),   # Right-center (bullpen)
        (302,  45),   # Pesky Pole (RF foul pole)
    ],
    'Camden Yards':              _w(333, 357, 364, 390, 410, 390, 373, 347, 318),
    'Rogers Centre':             _w(328, 356, 375, 393, 400, 393, 375, 356, 328),
    'Tropicana Field':           _w(315, 345, 370, 392, 404, 392, 370, 348, 322),
    # AL Central
    'Guaranteed Rate Field':     _w(330, 357, 377, 392, 400, 387, 372, 356, 335),
    'Progressive Field':         _w(325, 350, 370, 393, 405, 390, 375, 352, 325),
    'Comerica Park':             _w(345, 360, 370, 403, 420, 395, 365, 352, 330),
    'Kauffman Stadium':          _w(330, 357, 375, 398, 410, 398, 375, 357, 330),
    'Target Field':              _w(339, 361, 377, 395, 404, 387, 367, 350, 328),
    # AL West
    'Minute Maid Park':          _w(315, 339, 362, 418, 435, 400, 373, 350, 326),
    'Angel Stadium':             _w(330, 360, 383, 397, 400, 388, 370, 353, 330),
    'Oakland Coliseum':          _w(330, 362, 388, 396, 400, 382, 362, 349, 330),
    'T-Mobile Park':             _w(331, 356, 378, 393, 401, 393, 381, 354, 326),
    'Globe Life Field':          _w(329, 355, 374, 396, 407, 396, 374, 352, 326),
    # NL East
    'Truist Park':               _w(335, 361, 380, 393, 400, 390, 375, 352, 325),
    'Citi Field':                _w(335, 348, 358, 390, 408, 393, 375, 354, 330),
    'Citizens Bank Park':        _w(329, 352, 369, 390, 401, 390, 369, 352, 330),
    'Nationals Park':            _w(336, 360, 377, 393, 402, 388, 370, 355, 335),
    'loanDepot park':            _w(344, 368, 386, 400, 407, 400, 392, 366, 335),
    # NL Central
    'Wrigley Field':             _w(355, 363, 368, 385, 400, 385, 368, 363, 353),
    'Great American Ball Park':  _w(328, 356, 379, 395, 404, 388, 370, 350, 325),
    'American Family Field':     _w(344, 361, 371, 390, 400, 390, 374, 363, 345),
    'PNC Park':                  _w(325, 360, 389, 396, 399, 390, 375, 350, 320),
    'Busch Stadium':             _w(336, 360, 375, 392, 400, 392, 375, 360, 335),
    # NL West
    'Dodger Stadium':            _w(330, 360, 375, 392, 400, 392, 375, 360, 330),
    'Chase Field':               _w(330, 357, 374, 396, 407, 396, 374, 358, 335),
    'Coors Field':               _w(347, 372, 390, 407, 415, 395, 375, 366, 350),
    'Oracle Park': [
        # Deep right-center (McCovey Cove) creates a distinctive bulge at RCF
        # before dropping sharply back to the short RF (309) foul pole.
        (339, -45),   # LF foul pole
        (362, -33),   # LF area
        (382, -22.5), # LCF
        (396, -11),   # Left-CF
        (399,   0),   # CF
        (410,  11),   # Right-CF toward Cove
        (421,  22.5), # Deep RCF — McCovey Cove (labeled '421')
        (360,  35),   # Sharp curve back toward RF pole
        (309,  45),   # RF foul pole (labeled '309')
    ],
    'Petco Park':                _w(336, 354, 367, 385, 396, 392, 391, 360, 322),
}

_DEFAULT_WALL = _w(330, 360, 375, 392, 400, 392, 375, 360, 330)


def _load_fonts():
    font_path = os.path.join(picdir, 'Font.ttc')
    return {
        'f24': ImageFont.truetype(font_path, 24),
        'f18': ImageFont.truetype(font_path, 18),
        'f14': ImageFont.truetype(font_path, 14),
        'f11': ImageFont.truetype(font_path, 11),
        'f9':  ImageFont.truetype(font_path, 9),
    }


def _field_pt(dist_ft, angle_deg):
    """Convert (feet from home plate, angle from center field) to pixel coords.
    angle_deg: negative = left/LF side, positive = right/RF side.
    """
    hx, hy = HOME_PLATE
    rad = math.radians(angle_deg)
    px = hx + dist_ft * FIELD_SCALE * math.sin(rad)
    py = hy - dist_ft * FIELD_SCALE * math.cos(rad)
    return int(px), int(py)


def _draw_field(draw, data, fonts=None):
    """Draw the baseball field diagram on the left half (0-399).
    Uses venue-specific outfield dimensions when available.
    """
    hx, hy = HOME_PLATE

    venue = data.get('venue', '')
    dims = BALLPARK_DIMENSIONS.get(venue, _DEFAULT_WALL)

    # Compute wall points from (distance, angle) pairs
    wall_pts = [_field_pt(dist, ang) for dist, ang in dims]
    lf_pole = wall_pts[0]
    rf_pole = wall_pts[-1]

    # Warning track: 15ft inside the outfield wall (thin inner arc)
    track_pts = [_field_pt(max(dist - 15, 50), ang) for dist, ang in dims]
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
    # Second base is ~89 px from home plate (127.3 ft × 0.70), so radius > 89 clears it.
    r_arc = 104  # ~15 px past second base (89 px from home)
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

    # Distance labels: foul poles + deepest CF point + intermediate labeled points
    font_tiny = fonts.get('f9') if fonts else None
    if font_tiny:
        deepest_idx = min(range(len(wall_pts)), key=lambda i: wall_pts[i][1])
        cf_pt   = wall_pts[deepest_idx]
        cf_dist = dims[deepest_idx][0]
        lf_dist = dims[0][0]
        rf_dist = dims[-1][0]

        # Always label: LF pole, deepest point, RF pole
        draw.text((cf_pt[0] - 10, cf_pt[1] - 10), str(cf_dist), font=font_tiny, fill=0)
        draw.text((lf_pole[0] + 2, lf_pole[1]),    str(lf_dist), font=font_tiny, fill=0)
        draw.text((rf_pole[0] - 18, rf_pole[1]),   str(rf_dist), font=font_tiny, fill=0)

        # For parks with 8+ wall points, also label 2 intermediate ones:
        # pick the most-left-of-center non-pole point and most-right-of-center non-pole point
        if len(dims) >= 8:
            inner = [(dims[i][0], dims[i][1], wall_pts[i])
                     for i in range(1, len(dims) - 1)
                     if i != deepest_idx]
            lf_mid = min(inner, key=lambda t: t[1], default=None)   # most-negative angle
            rf_mid = max(inner, key=lambda t: t[1], default=None)   # most-positive angle
            if lf_mid:
                pt = lf_mid[2]
                draw.text((pt[0] + 2, pt[1] - 2), str(lf_mid[0]), font=font_tiny, fill=0)
            if rf_mid:
                pt = rf_mid[2]
                draw.text((pt[0] - 18, pt[1] - 2), str(rf_mid[0]), font=font_tiny, fill=0)


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
