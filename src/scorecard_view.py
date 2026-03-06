import os
from PIL import Image, ImageDraw, ImageFont, ImageOps

from generate_image import picdir, _logo_small

EPD_WIDTH = 800
EPD_HEIGHT = 480

# Column layout constants
COL_ORDER = 16
COL_NAME = 140
COL_POS = 24
COL_INNING = 50
COL_RHE = 28

# Row layout constants
ROW_HEADER = 14
ROW_INN_HEADER = 16
ROW_BATTER = 21
ROW_TOTALS = 16
TEAM_HEIGHT = 238


def _load_fonts():
    font_path = os.path.join(picdir, 'Font.ttc')
    return {
        'f14': ImageFont.truetype(font_path, 14),
        'f11': ImageFont.truetype(font_path, 11),
        'f9': ImageFont.truetype(font_path, 9),
    }


def _draw_mini_diamond(draw, x, y, bases, size=4):
    """Draw a tiny diamond showing bases reached. bases=0-4."""
    # Draw empty diamond outline
    pts = [(x, y - size), (x + size, y), (x, y + size), (x - size, y)]
    draw.polygon(pts, outline=0)

    # Fill segments based on bases reached
    if bases >= 1:
        # First base side
        draw.line([(x + size, y), (x, y - size)], fill=0, width=2)
    if bases >= 2:
        # Second base side
        draw.line([(x, y - size), (x - size, y)], fill=0, width=2)
    if bases >= 3:
        # Third base side
        draw.line([(x - size, y), (x, y + size)], fill=0, width=2)
    if bases >= 4:
        # Home (fill entire diamond)
        draw.polygon(pts, fill=0, outline=0)


def _draw_team_scorecard(img, draw, fonts, y_offset, team_data, team_abbr, team_id,
                          num_innings, inning_totals, runs, hits, errors):
    """Draw a single team's scorecard at y_offset."""
    x = 0

    # Cap displayed innings at 9, with 10+ summary if needed
    display_innings = min(num_innings, 9)
    has_extras = num_innings > 9

    # Team header row
    logo = _logo_small(team_abbr, str(team_id), size=12)
    hx = x + 4
    if logo:
        small = logo.copy()
        small.thumbnail((12, 12))
        img.paste(small, (hx, y_offset + 1))
        hx += 14
    draw.text((hx, y_offset), team_abbr, font=fonts['f11'], fill=0)
    y = y_offset + ROW_HEADER

    # Inning headers
    ix = x + COL_ORDER + COL_NAME + COL_POS
    draw.text((x + 2, y), '#', font=fonts['f9'], fill=0)
    draw.text((x + COL_ORDER, y), 'Player', font=fonts['f9'], fill=0)
    draw.text((x + COL_ORDER + COL_NAME, y + 2), 'P', font=fonts['f9'], fill=0)

    for i in range(display_innings):
        col_x = ix + i * COL_INNING
        draw.text((col_x + 18, y), str(i + 1), font=fonts['f11'], fill=0)

    if has_extras:
        col_x = ix + display_innings * COL_INNING
        draw.text((col_x + 10, y), '10+', font=fonts['f9'], fill=0)
        extra_col = display_innings
    else:
        extra_col = None

    # R H E headers
    rhe_x = ix + (display_innings + (1 if has_extras else 0)) * COL_INNING
    draw.text((rhe_x + 8, y), 'R', font=fonts['f11'], fill=0)
    draw.text((rhe_x + 8 + COL_RHE, y), 'H', font=fonts['f11'], fill=0)
    draw.text((rhe_x + 8 + 2 * COL_RHE, y), 'E', font=fonts['f11'], fill=0)

    y += ROW_INN_HEADER

    # Horizontal line under header
    draw.line([(x, y), (EPD_WIDTH, y)], fill=0)

    # Batter rows
    lineup = team_data
    for slot_idx in range(9):
        by = y + slot_idx * ROW_BATTER

        if slot_idx < len(lineup):
            entry = lineup[slot_idx]
            name = entry.get('name', '')
            pos = entry.get('position', '')
            order = entry.get('order', slot_idx + 1)
            sub = entry.get('sub', False)
            at_bats = entry.get('at_bats', {})
            totals = entry.get('totals', {})

            # Order number
            order_str = f"{'*' if sub else ''}{order}"
            draw.text((x + 2, by + 2), order_str, font=fonts['f9'], fill=0)

            # Player name (truncate if needed)
            display_name = name[:16]
            draw.text((x + COL_ORDER, by + 2), display_name, font=fonts['f11'], fill=0)

            # Position
            draw.text((x + COL_ORDER + COL_NAME, by + 2), pos, font=fonts['f9'], fill=0)

            # Per-inning at-bat cells
            for inn_num in range(1, display_innings + 1):
                col_x = ix + (inn_num - 1) * COL_INNING
                abs_list = at_bats.get(inn_num, [])
                if abs_list:
                    # Show most recent at-bat in this inning
                    ab = abs_list[-1]
                    code = ab.get('code', '')
                    bases = ab.get('bases', 0)
                    draw.text((col_x + 4, by + 2), code, font=fonts['f11'], fill=0)
                    # Mini diamond
                    _draw_mini_diamond(draw, col_x + COL_INNING - 8, by + ROW_BATTER - 7, bases)

            # Extra innings summary
            if has_extras:
                col_x = ix + display_innings * COL_INNING
                extra_abs = []
                for inn_num in range(10, num_innings + 1):
                    extra_abs.extend(at_bats.get(inn_num, []))
                if extra_abs:
                    ab = extra_abs[-1]
                    draw.text((col_x + 4, by + 2), ab.get('code', ''), font=fonts['f11'], fill=0)

            # R and H for this batter
            draw.text((rhe_x + 10, by + 2), str(totals.get('runs', 0)), font=fonts['f11'], fill=0)
            draw.text((rhe_x + 10 + COL_RHE, by + 2), str(totals.get('hits', 0)), font=fonts['f11'], fill=0)

        # Horizontal grid line
        draw.line([(ix, by + ROW_BATTER), (EPD_WIDTH, by + ROW_BATTER)], fill=0)

    # Vertical grid lines for inning columns
    grid_top = y
    grid_bottom = y + 9 * ROW_BATTER + ROW_TOTALS
    for i in range(display_innings + (1 if has_extras else 0) + 1):
        lx = ix + i * COL_INNING
        draw.line([(lx, grid_top - ROW_INN_HEADER), (lx, grid_bottom)], fill=0)

    # RHE vertical lines
    for i in range(4):
        lx = rhe_x + i * COL_RHE
        draw.line([(lx, grid_top - ROW_INN_HEADER), (lx, grid_bottom)], fill=0)

    # Totals row
    ty = y + 9 * ROW_BATTER
    draw.line([(x, ty), (EPD_WIDTH, ty)], fill=0, width=2)

    for inn_num in range(1, display_innings + 1):
        col_x = ix + (inn_num - 1) * COL_INNING
        inn_runs = inning_totals.get(inn_num, 0)
        draw.text((col_x + 18, ty + 2), str(inn_runs), font=fonts['f11'], fill=0)

    if has_extras:
        col_x = ix + display_innings * COL_INNING
        extra_runs = sum(inning_totals.get(i, 0) for i in range(10, num_innings + 1))
        draw.text((col_x + 18, ty + 2), str(extra_runs), font=fonts['f11'], fill=0)

    draw.text((rhe_x + 10, ty + 2), str(runs), font=fonts['f11'], fill=0)
    draw.text((rhe_x + 10 + COL_RHE, ty + 2), str(hits), font=fonts['f11'], fill=0)
    draw.text((rhe_x + 10 + 2 * COL_RHE, ty + 2), str(errors), font=fonts['f11'], fill=0)


def render_scorecard_view(data, dark_mode=False):
    """Render the scorecard view display. Returns an 800x480 1-bit PIL Image."""
    img = Image.new('1', (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(img)
    fonts = _load_fonts()

    num_innings = data.get('num_innings', 9)

    # Away team (top half: y=0 to 237)
    _draw_team_scorecard(
        img, draw, fonts,
        y_offset=2,
        team_data=data.get('away_lineup', []),
        team_abbr=data.get('away_abbr', ''),
        team_id=data.get('away_id', 0),
        num_innings=num_innings,
        inning_totals=data.get('away_inning_totals', {}),
        runs=data.get('away_runs', 0),
        hits=data.get('away_hits', 0),
        errors=data.get('away_errors', 0),
    )

    # Divider
    draw.line([(0, TEAM_HEIGHT), (EPD_WIDTH, TEAM_HEIGHT)], fill=0, width=2)

    # Home team (bottom half: y=240 to 479)
    _draw_team_scorecard(
        img, draw, fonts,
        y_offset=TEAM_HEIGHT + 2,
        team_data=data.get('home_lineup', []),
        team_abbr=data.get('home_abbr', ''),
        team_id=data.get('home_id', 0),
        num_innings=num_innings,
        inning_totals=data.get('home_inning_totals', {}),
        runs=data.get('home_runs', 0),
        hits=data.get('home_hits', 0),
        errors=data.get('home_errors', 0),
    )

    if dark_mode:
        img = ImageOps.invert(img.convert('L')).convert('1')

    return img
