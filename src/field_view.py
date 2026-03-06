import os
import math
from PIL import Image, ImageDraw, ImageFont, ImageOps

from generate_image import (
    picdir, _logo_small, _load_logo_gray, draw_diamond, draw_circle,
)

EPD_WIDTH = 800
EPD_HEIGHT = 480

# Field geometry constants
HOME_PLATE = (200, 420)
FIRST_BASE = (275, 355)
SECOND_BASE = (200, 290)
THIRD_BASE = (125, 355)
MOUND = (200, 348)
FENCE_RADIUS = 260
FENCE_CENTER = HOME_PLATE


def _load_fonts():
    font_path = os.path.join(picdir, 'Font.ttc')
    return {
        'f24': ImageFont.truetype(font_path, 24),
        'f18': ImageFont.truetype(font_path, 18),
        'f14': ImageFont.truetype(font_path, 14),
        'f11': ImageFont.truetype(font_path, 11),
    }


def _draw_field(draw, data):
    """Draw the baseball field diagram on the left half (0-399)."""
    hx, hy = HOME_PLATE

    # Foul lines: extend the home→base direction vector out to fence radius
    def _foul_end(base):
        dx, dy = base[0] - hx, base[1] - hy
        mag = math.sqrt(dx * dx + dy * dy)
        return hx + FENCE_RADIUS * dx / mag, hy + FENCE_RADIUS * dy / mag

    lf_x, lf_y = _foul_end(THIRD_BASE)
    rf_x, rf_y = _foul_end(FIRST_BASE)

    # Outfield fence arc
    arc_bbox = [
        hx - FENCE_RADIUS, hy - FENCE_RADIUS,
        hx + FENCE_RADIUS, hy + FENCE_RADIUS,
    ]
    # Arc from right field foul line to left field foul line
    # PIL arc angles: 0=3 o'clock, 90=6 o'clock, etc.
    # We need the arc from ~225 degrees to ~315 degrees
    draw.arc(arc_bbox, 225, 315, fill=0, width=2)

    # Foul lines
    draw.line([HOME_PLATE, (int(lf_x), int(lf_y))], fill=0, width=1)
    draw.line([HOME_PLATE, (int(rf_x), int(rf_y))], fill=0, width=1)

    # Base paths (infield diamond)
    draw.line([HOME_PLATE, FIRST_BASE], fill=0, width=1)
    draw.line([FIRST_BASE, SECOND_BASE], fill=0, width=1)
    draw.line([SECOND_BASE, THIRD_BASE], fill=0, width=1)
    draw.line([THIRD_BASE, HOME_PLATE], fill=0, width=1)

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
    draw.ellipse([MOUND[0] - 4, MOUND[1] - 4, MOUND[0] + 4, MOUND[1] + 4], outline=0)

    # Bases (empty squares, will be filled if occupied)
    base_size = 6
    for bx, by in [FIRST_BASE, SECOND_BASE, THIRD_BASE]:
        draw.polygon([
            (bx, by - base_size), (bx + base_size, by),
            (bx, by + base_size), (bx - base_size, by),
        ], outline=0)


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


def _draw_hit_marker(draw, data):
    """Draw hit location marker on the field."""
    hit = data.get('hit_coords')
    if not hit:
        return
    px, py = _transform_hit_coords(hit[0], hit[1])
    r = 5
    draw.ellipse([px - r, py - r, px + r, py + r], fill=0)
    # Crosshair
    draw.line([px - r - 2, py, px + r + 2, py], fill=0)
    draw.line([px, py - r - 2, px, py + r + 2], fill=0)


def _draw_score_header(img, draw, fonts, data):
    """Draw score panel at top of right half (400-799, y 5-75)."""
    x_base = 410
    y = 8

    away_abbr = data.get('away_abbr', '')
    home_abbr = data.get('home_abbr', '')
    away_id = str(data.get('away_id', ''))
    home_id = str(data.get('home_id', ''))

    # Away team line
    logo = _logo_small(away_abbr, away_id)
    lx = x_base
    if logo:
        img.paste(logo, (lx, y + 2))
        lx += 30
    draw.text((lx, y), away_abbr, font=fonts['f18'], fill=0)
    draw.text((lx + 55, y), str(data.get('away_runs', 0)), font=fonts['f24'], fill=0)

    # Home team line
    y2 = y + 32
    logo = _logo_small(home_abbr, home_id)
    lx = x_base
    if logo:
        img.paste(logo, (lx, y2 + 2))
        lx += 30
    draw.text((lx, y2), home_abbr, font=fonts['f18'], fill=0)
    draw.text((lx + 55, y2), str(data.get('home_runs', 0)), font=fonts['f24'], fill=0)

    # R/H/E labels
    rhe_x = lx + 100
    draw.text((rhe_x, y - 2), 'R', font=fonts['f11'], fill=0)
    draw.text((rhe_x + 25, y - 2), 'H', font=fonts['f11'], fill=0)
    draw.text((rhe_x + 50, y - 2), 'E', font=fonts['f11'], fill=0)

    draw.text((rhe_x, y + 14), str(data.get('away_runs', 0)), font=fonts['f14'], fill=0)
    draw.text((rhe_x + 25, y + 14), str(data.get('away_hits', 0)), font=fonts['f14'], fill=0)
    draw.text((rhe_x + 50, y + 14), str(data.get('away_errors', 0)), font=fonts['f14'], fill=0)

    draw.text((rhe_x, y + 14 + 32), str(data.get('home_runs', 0)), font=fonts['f14'], fill=0)
    draw.text((rhe_x + 25, y + 14 + 32), str(data.get('home_hits', 0)), font=fonts['f14'], fill=0)
    draw.text((rhe_x + 50, y + 14 + 32), str(data.get('home_errors', 0)), font=fonts['f14'], fill=0)


def _draw_inning_state(img, draw, fonts, data):
    """Draw inning, count, outs, and mini bases (y 80-140)."""
    x_base = 410
    y = 82

    state = data.get('detailed_state', '')
    if state in ('Final', 'Game Over', 'Final: Tied'):
        draw.text((x_base, y), 'FINAL', font=fonts['f18'], fill=0)
    elif state in ('Scheduled', 'Pre-Game', 'Warmup'):
        draw.text((x_base, y), state, font=fonts['f18'], fill=0)
    else:
        inning_text = f"{data.get('inning_state', '')} {data.get('inning_ordinal', '')}"
        draw.text((x_base, y), inning_text, font=fonts['f18'], fill=0)

        # Count
        count_text = f"{data.get('balls', 0)}-{data.get('strikes', 0)}"
        draw.text((x_base + 160, y), count_text, font=fonts['f18'], fill=0)

        # Outs circles
        outs = data.get('outs', 0)
        ox = x_base + 230
        oy = y + 10
        for i in range(3):
            cx = ox + i * 18
            filled = i < outs
            if filled:
                draw.ellipse([cx - 5, oy - 5, cx + 5, oy + 5], fill=0, outline=0)
            else:
                draw.ellipse([cx - 5, oy - 5, cx + 5, oy + 5], outline=0)

    # Mini diamond for bases
    mini_x = x_base + 320
    mini_y = y + 10
    sz = 8
    bases_pts = [
        (data.get('runner_first'), (mini_x + sz, mini_y)),
        (data.get('runner_second'), (mini_x, mini_y - sz)),
        (data.get('runner_third'), (mini_x - sz, mini_y)),
    ]
    for occupied, (bx, by) in bases_pts:
        pts = [(bx, by - sz // 2), (bx + sz // 2, by), (bx, by + sz // 2), (bx - sz // 2, by)]
        if occupied:
            draw.polygon(pts, fill=0, outline=0)
        else:
            draw.polygon(pts, outline=0)


def _draw_matchup(draw, fonts, data):
    """Draw batter/pitcher info (y 145-225)."""
    x_base = 410
    y = 148

    state = data.get('detailed_state', '')
    if state in ('Scheduled', 'Pre-Game', 'Warmup'):
        # Pre-game: show probable pitchers
        draw.text((x_base, y), 'Probable Pitchers:', font=fonts['f14'], fill=0)
        away = data.get('away_abbr', '')
        home = data.get('home_abbr', '')
        draw.text((x_base, y + 18), f"{away}: {data.get('away_probable', 'TBD')}", font=fonts['f14'], fill=0)
        draw.text((x_base, y + 36), f"{home}: {data.get('home_probable', 'TBD')}", font=fonts['f14'], fill=0)
        return

    if state in ('Final', 'Game Over', 'Final: Tied'):
        # Show WP/LP
        draw.text((x_base, y), f"WP: {data.get('winner', '')}", font=fonts['f14'], fill=0)
        draw.text((x_base, y + 18), f"LP: {data.get('loser', '')}", font=fonts['f14'], fill=0)
        if data.get('save'):
            draw.text((x_base, y + 36), f"SV: {data.get('save', '')}", font=fonts['f14'], fill=0)
        return

    # In progress: batter and pitcher
    batter = data.get('batter', {})
    pitcher = data.get('pitcher', {})

    batter_name = batter.get('name', '')
    pitcher_name = pitcher.get('name', '')

    draw.text((x_base, y), 'AB:', font=fonts['f11'], fill=0)
    draw.text((x_base + 22, y), batter_name, font=fonts['f14'], fill=0)

    # Batter season stats
    b_season = batter.get('season', {})
    avg = b_season.get('avg', '')
    hr = b_season.get('homeRuns', '')
    rbi = b_season.get('rbi', '')
    if avg:
        draw.text((x_base + 22, y + 18), f"AVG {avg}  HR {hr}  RBI {rbi}", font=fonts['f11'], fill=0)

    draw.text((x_base, y + 38), 'P:', font=fonts['f11'], fill=0)
    draw.text((x_base + 16, y + 38), pitcher_name, font=fonts['f14'], fill=0)

    # Pitcher game stats
    p_stats = pitcher.get('stats', {})
    ip = p_stats.get('inningsPitched', '')
    k = p_stats.get('strikeOuts', '')
    p_season = pitcher.get('season', {})
    era = p_season.get('era', '')
    if era:
        draw.text((x_base + 16, y + 56), f"ERA {era}  IP {ip}  K {k}", font=fonts['f11'], fill=0)


def _draw_strike_zone(draw, fonts, data):
    """Draw pitch locations for the current at-bat in the upper-left corner (x=5-125, y=5-130)."""
    pitches = data.get('pitches', [])
    if not pitches:
        return

    # Display area (upper-left, clear of the field diagram)
    ax, ay, aw, ah = 5, 5, 120, 125

    # Coordinate ranges: pX in feet from plate center, pZ in feet off ground
    px_min, px_max = -1.5, 1.5
    pz_min, pz_max = 1.0, 4.5

    def to_px(px, pz):
        x = ax + int((px - px_min) / (px_max - px_min) * aw)
        y = ay + ah - int((pz - pz_min) / (pz_max - pz_min) * ah)
        return x, y

    # Strike zone rectangle (plate ±0.708 ft wide, typical zone 1.5–3.5 ft)
    zl, zt = to_px(-0.708, 3.5)
    zr, zb = to_px(0.708, 1.5)
    draw.rectangle([zl, zt, zr, zb], outline=0)

    # Nine-zone grid lines inside the zone
    third_w = (zr - zl) // 3
    third_h = (zb - zt) // 3
    draw.line([zl + third_w, zt, zl + third_w, zb], fill=0)
    draw.line([zl + 2 * third_w, zt, zl + 2 * third_w, zb], fill=0)
    draw.line([zl, zt + third_h, zr, zt + third_h], fill=0)
    draw.line([zl, zt + 2 * third_h, zr, zt + 2 * third_h], fill=0)

    # Plot pitches
    r = 4
    for pitch in pitches:
        px, pz = pitch.get('px'), pitch.get('pz')
        if px is None or pz is None:
            continue
        bx, by = to_px(px, pz)
        code = pitch.get('code', '')
        if code in ('S', 'C', 'T'):       # Strike (swinging, called, foul tip)
            draw.ellipse([bx - r, by - r, bx + r, by + r], fill=0, outline=0)
        elif code == 'F':                  # Foul — open with crossbar
            draw.ellipse([bx - r, by - r, bx + r, by + r], outline=0)
            draw.line([bx - r, by, bx + r, by], fill=0)
        elif code == 'X':                  # In play — filled square
            draw.rectangle([bx - r, by - r, bx + r, by + r], fill=0)
        else:                              # Ball — open circle
            draw.ellipse([bx - r, by - r, bx + r, by + r], outline=0)

    # Count label below the zone area
    balls = data.get('balls', 0)
    strikes = data.get('strikes', 0)
    draw.text((ax, ay + ah + 4), f'{balls}-{strikes}', font=fonts['f11'], fill=0)


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


def _draw_last_play(draw, fonts, data):
    """Draw last play description, word-wrapped (y 230-320)."""
    x_base = 410
    y = 232

    last_play = data.get('last_play', '')
    if not last_play:
        return

    draw.text((x_base, y), 'Last Play:', font=fonts['f11'], fill=0)
    lines = _word_wrap(last_play, fonts['f14'], 370)
    for i, line in enumerate(lines[:4]):
        draw.text((x_base, y + 14 + i * 18), line, font=fonts['f14'], fill=0)


def _draw_mini_linescore(draw, fonts, data):
    """Draw mini linescore table (y 325-475)."""
    x_base = 410
    y = 330

    innings = data.get('innings', [])
    if not innings:
        return

    away_abbr = data.get('away_abbr', '')
    home_abbr = data.get('home_abbr', '')

    # Determine how many innings to show (cap at what fits)
    max_inn = min(len(innings), 12)
    col_w = 26
    label_w = 40

    # Header row
    draw.text((x_base, y), '', font=fonts['f11'], fill=0)
    for i in range(max_inn):
        ix = x_base + label_w + i * col_w
        draw.text((ix, y), str(innings[i]['num']), font=fonts['f11'], fill=0)

    # R H E headers
    rhe_x = x_base + label_w + max_inn * col_w + 5
    draw.text((rhe_x, y), 'R', font=fonts['f11'], fill=0)
    draw.text((rhe_x + 20, y), 'H', font=fonts['f11'], fill=0)
    draw.text((rhe_x + 40, y), 'E', font=fonts['f11'], fill=0)

    # Away row
    ay = y + 16
    draw.text((x_base, ay), away_abbr, font=fonts['f11'], fill=0)
    for i in range(max_inn):
        ix = x_base + label_w + i * col_w
        val = innings[i].get('away_runs')
        draw.text((ix, ay), str(val if val is not None else ''), font=fonts['f11'], fill=0)
    draw.text((rhe_x, ay), str(data.get('away_runs', 0)), font=fonts['f11'], fill=0)
    draw.text((rhe_x + 20, ay), str(data.get('away_hits', 0)), font=fonts['f11'], fill=0)
    draw.text((rhe_x + 40, ay), str(data.get('away_errors', 0)), font=fonts['f11'], fill=0)

    # Home row
    hy = ay + 16
    draw.text((x_base, hy), home_abbr, font=fonts['f11'], fill=0)
    for i in range(max_inn):
        ix = x_base + label_w + i * col_w
        val = innings[i].get('home_runs')
        draw.text((ix, hy), str(val if val is not None else ''), font=fonts['f11'], fill=0)
    draw.text((rhe_x, hy), str(data.get('home_runs', 0)), font=fonts['f11'], fill=0)
    draw.text((rhe_x + 20, hy), str(data.get('home_hits', 0)), font=fonts['f11'], fill=0)
    draw.text((rhe_x + 40, hy), str(data.get('home_errors', 0)), font=fonts['f11'], fill=0)

    # Venue
    venue = data.get('venue', '')
    if venue:
        draw.text((x_base, hy + 22), venue, font=fonts['f11'], fill=0)


def render_field_view(data, dark_mode=False):
    """Render the field view display. Returns an 800x480 1-bit PIL Image."""
    img = Image.new('1', (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(img)
    fonts = _load_fonts()

    # Vertical divider
    draw.line([(400, 0), (400, EPD_HEIGHT)], fill=0, width=2)

    # Left half: baseball field
    _draw_field(draw, data)
    _draw_runners(draw, data)
    _draw_hit_marker(draw, data)
    _draw_strike_zone(draw, fonts, data)

    # Right half: game info
    _draw_score_header(img, draw, fonts, data)
    _draw_inning_state(img, draw, fonts, data)
    _draw_matchup(draw, fonts, data)
    _draw_last_play(draw, fonts, data)
    _draw_mini_linescore(draw, fonts, data)

    if dark_mode:
        img = ImageOps.invert(img.convert('L')).convert('1')

    return img
