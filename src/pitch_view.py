import os
from PIL import Image, ImageDraw, ImageFont, ImageOps

from generate_image import picdir, _logo_small

EPD_WIDTH = 800
EPD_HEIGHT = 480

# Strike zone geometry (left half, centered at x=200)
SZ_CENTER_X = 200
SZ_BOTTOM_Y = 430      # pixel row for ground level (pZ=0)
PX_SCALE = 80.0        # pixels per foot, horizontal
PZ_SCALE = 80.0        # pixels per foot, vertical

# Standard strike zone boundaries in feet
SZ_HALF_WIDTH = 0.708  # half of 17-inch plate
SZ_Z_BOT = 1.5
SZ_Z_TOP = 3.5


def _load_fonts():
    """Load fonts."""
    font_path = os.path.join(picdir, 'Font.ttc')
    return {
        'f18': ImageFont.truetype(font_path, 18),
        'f14': ImageFont.truetype(font_path, 14),
        'f11': ImageFont.truetype(font_path, 11),
        'f9':  ImageFont.truetype(font_path, 9),
    }


def _to_pixel(px_ft, pz_ft):
    """Convert (pX feet from center, pZ feet off ground) to pixel coordinates."""
    x = int(SZ_CENTER_X + px_ft * PX_SCALE)
    y = int(SZ_BOTTOM_Y - pz_ft * PZ_SCALE)
    return x, y


def _draw_zone(draw):
    """Draw the strike zone rectangle with 9-zone grid and home plate."""
    zl, zt = _to_pixel(-SZ_HALF_WIDTH, SZ_Z_TOP)
    zr, zb = _to_pixel(SZ_HALF_WIDTH, SZ_Z_BOT)

    # Outer zone rectangle
    draw.rectangle([zl, zt, zr, zb], outline=0, width=2)

    # 9-zone grid
    tw = (zr - zl) // 3
    th = (zb - zt) // 3
    draw.line([zl + tw,     zt + 1, zl + tw,     zb - 1], fill=0)
    draw.line([zl + 2 * tw, zt + 1, zl + 2 * tw, zb - 1], fill=0)
    draw.line([zl + 1, zt + th,     zr - 1, zt + th],     fill=0)
    draw.line([zl + 1, zt + 2 * th, zr - 1, zt + 2 * th], fill=0)

    # Ground line
    ground_y = SZ_BOTTOM_Y
    draw.line([(SZ_CENTER_X - 130, ground_y), (SZ_CENTER_X + 130, ground_y)], fill=0)

    # Home plate (pentagon)
    hx = SZ_CENTER_X
    hy = ground_y - 4
    s = 12
    draw.polygon([
        (hx,     hy + s),
        (hx - s, hy),
        (hx - s + 3, hy - s),
        (hx + s - 3, hy - s),
        (hx + s, hy),
    ], outline=0)

    # Catcher's perspective labels
    draw.text((_to_pixel(-SZ_HALF_WIDTH - 0.3, SZ_Z_BOT - 0.25)[0], ground_y - 14),
              'RHB', font=None, fill=0)


def _draw_pitches(draw, fonts, pitches):
    """Plot each pitch. Filled = strike, open = ball, F inside = foul, square = in play."""
    r = 7
    for pitch in pitches:
        px, pz = pitch.get('px'), pitch.get('pz')
        if px is None or pz is None:
            continue
        bx, by = _to_pixel(px, pz)
        code = pitch.get('code', '')
        seq = str(pitch.get('seq', ''))

        if code in ('S', 'C', 'T'):
            # Strike — filled circle, seq number to the right
            draw.ellipse([bx - r, by - r, bx + r, by + r], fill=0, outline=0)
            draw.text((bx + r + 2, by - 5), seq, font=fonts['f9'], fill=0)
        elif code == 'F':
            # Foul — open circle with 'F' inside
            draw.ellipse([bx - r, by - r, bx + r, by + r], outline=0, width=2)
            draw.text((bx - 3, by - 5), 'F', font=fonts['f9'], fill=0)
        elif code == 'X':
            # In play — filled square, seq to the right
            draw.rectangle([bx - r, by - r, bx + r, by + r], fill=0)
            draw.text((bx + r + 2, by - 5), seq, font=fonts['f9'], fill=0)
        else:
            # Ball — open circle with seq number inside
            draw.ellipse([bx - r, by - r, bx + r, by + r], outline=0, width=2)
            draw.text((bx - 3, by - 5), seq, font=fonts['f9'], fill=0)


def _draw_right_panel(img, draw, fonts, data):
    """Draw score, count, batter/pitcher, legend, and pitch log on the right half."""
    x = 415

    # --- Score header ---
    y = 8
    for _side, abbr_key, id_key, runs_key in (
        ('away', 'away_abbr', 'away_id', 'away_runs'),
        ('home', 'home_abbr', 'home_id', 'home_runs'),
    ):
        abbr = data.get(abbr_key, '')
        team_id = str(data.get(id_key, ''))
        runs = data.get(runs_key, 0)
        logo = _logo_small(abbr, team_id)
        lx = x
        if logo:
            img.paste(logo, (lx, y + 2))
            lx += 30
        draw.text((lx, y), abbr, font=fonts['f18'], fill=0)
        draw.text((lx + 55, y), str(runs), font=fonts['f18'], fill=0)
        y += 32

    # --- Inning / count / outs ---
    y += 4
    state = data.get('detailed_state', '')
    if state in ('Final', 'Game Over', 'Final: Tied'):
        draw.text((x, y), 'FINAL', font=fonts['f18'], fill=0)
    else:
        inning = f"{data.get('inning_state', '')} {data.get('inning_ordinal', '')}".strip()
        draw.text((x, y), inning, font=fonts['f14'], fill=0)
        balls = data.get('balls', 0)
        strikes = data.get('strikes', 0)
        outs = data.get('outs', 0)
        draw.text((x, y + 18), f'Count: {balls}-{strikes}  Outs: {outs}', font=fonts['f14'], fill=0)
    y += 42

    # --- Batter ---
    batter = data.get('batter', {})
    draw.text((x, y), 'AB:', font=fonts['f11'], fill=0)
    draw.text((x + 24, y), batter.get('name', ''), font=fonts['f14'], fill=0)
    b = batter.get('season', {})
    if b.get('avg'):
        draw.text((x + 24, y + 17),
                  f"AVG {b.get('avg')}  HR {b.get('homeRuns', 0)}  RBI {b.get('rbi', 0)}",
                  font=fonts['f9'], fill=0)
    y += 36

    # --- Pitcher ---
    pitcher = data.get('pitcher', {})
    draw.text((x, y), 'P:', font=fonts['f11'], fill=0)
    draw.text((x + 16, y), pitcher.get('name', ''), font=fonts['f14'], fill=0)
    p = pitcher.get('season', {})
    ps = pitcher.get('stats', {})
    if p.get('era'):
        draw.text((x + 16, y + 17),
                  f"ERA {p.get('era')}  IP {ps.get('inningsPitched', '')}  K {ps.get('strikeOuts', '')}",
                  font=fonts['f9'], fill=0)
    y += 36

    # --- Legend ---
    draw.text((x, y), 'Legend:', font=fonts['f11'], fill=0)
    y += 14
    draw.ellipse([x, y + 1, x + 10, y + 11], fill=0)
    draw.text((x + 13, y), 'Strike (called/swinging)', font=fonts['f9'], fill=0)
    y += 13
    draw.ellipse([x, y + 1, x + 10, y + 11], outline=0, width=2)
    draw.text((x + 4, y + 1), 'n', font=fonts['f9'], fill=0)
    draw.text((x + 13, y), 'Ball (# = sequence)', font=fonts['f9'], fill=0)
    y += 13
    draw.ellipse([x, y + 1, x + 10, y + 11], outline=0, width=2)
    draw.text((x + 3, y + 1), 'F', font=fonts['f9'], fill=0)
    draw.text((x + 13, y), 'Foul', font=fonts['f9'], fill=0)
    y += 13
    draw.rectangle([x, y + 1, x + 10, y + 11], fill=0)
    draw.text((x + 13, y), 'In play', font=fonts['f9'], fill=0)
    y += 18

    # --- Pitch log ---
    draw.line([(x, y), (x + 375, y)], fill=0)
    y += 4
    pitches = data.get('pitches', [])
    for pitch in pitches:
        seq = pitch.get('seq', '')
        code = pitch.get('code', '')
        ptype = pitch.get('pitch_type', '')
        speed = pitch.get('speed')
        speed_str = f'{speed:.0f}' if speed else '--'
        line = f"{seq:>2}. {code:<3} {ptype[:14]:<14} {speed_str}mph"
        draw.text((x, y), line, font=fonts['f9'], fill=0)
        y += 11
        if y > 468:
            break


def render_pitch_view(data, dark_mode=False):
    """Render the pitch location view. Returns an 800x480 1-bit PIL Image."""
    img = Image.new('1', (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(img)
    fonts = _load_fonts()

    # Vertical divider
    draw.line([(400, 0), (400, EPD_HEIGHT)], fill=0, width=2)

    # Left half: strike zone + pitches
    _draw_zone(draw)
    _draw_pitches(draw, fonts, data.get('pitches', []))

    # Right half: game info
    _draw_right_panel(img, draw, fonts, data)

    if dark_mode:
        img = ImageOps.invert(img.convert('L')).convert('1')

    return img
