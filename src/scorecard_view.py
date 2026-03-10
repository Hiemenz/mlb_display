import os
from PIL import Image, ImageDraw, ImageFont, ImageOps

from generate_image import picdir, _logo_small

EPD_WIDTH = 800
EPD_HEIGHT = 480

PITCHER_PANEL_WIDTH = 160
SCORECARD_WIDTH = 640          # EPD_WIDTH - PITCHER_PANEL_WIDTH

# Column layout constants
COL_ORDER = 16
COL_NAME = 120
COL_POS = 24
COL_INNING = 44
COL_RHE = 28

# Row layout constants
ROW_HEADER = 14
ROW_INN_HEADER = 14
ROW_BATTER = 21
ROW_TOTALS = 14
TEAM_HEIGHT = 238


def _load_fonts():
    font_path = os.path.join(picdir, 'Font.ttc')
    return {
        'f14': ImageFont.truetype(font_path, 14),
        'f11': ImageFont.truetype(font_path, 11),
        'f9': ImageFont.truetype(font_path, 9),
    }


def _draw_pitch_dots(draw, x, y, balls, strikes):
    """Draw filled circles for balls, outline circles for strikes."""
    r = 2  # radius → 4px diameter
    dx = x
    for _ in range(min(balls, 4)):
        draw.ellipse([dx, y, dx + r * 2, y + r * 2], fill=0)
        dx += r * 2 + 1
    dx += 2
    for _ in range(min(strikes, 3)):
        draw.ellipse([dx, y, dx + r * 2, y + r * 2], outline=0)
        dx += r * 2 + 1


def _draw_mini_diamond(draw, x, y, bases, size=10):
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
    draw.line([(x, y), (SCORECARD_WIDTH, y)], fill=0)

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

            # Player name / substitution display
            display_name = name[:17]
            orig = entry.get('sub_original')
            if orig:
                orig_name = orig['name'].split()[-1][:14]
                draw.text((x + COL_ORDER, by), orig_name, font=fonts['f9'], fill=0)
                draw.text((x + COL_ORDER + COL_NAME, by), orig['position'], font=fonts['f9'], fill=0)
                draw.text((x + COL_ORDER, by + 11), '\u2192' + display_name[:15], font=fonts['f9'], fill=0)
                draw.text((x + COL_ORDER + COL_NAME, by + 11), pos, font=fonts['f9'], fill=0)
            else:
                draw.text((x + COL_ORDER, by + 2), display_name, font=fonts['f11'], fill=0)
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
                    balls = ab.get('balls', 0)
                    strikes = ab.get('strikes', 0)
                    # Outcome code top-left
                    draw.text((col_x + 2, by + 1), code, font=fonts['f11'], fill=0)
                    # Pitch count dots to the right of code
                    _draw_pitch_dots(draw, col_x + 14, by + 3, balls, strikes)
                    # Bigger diamond centered bottom of cell
                    _draw_mini_diamond(draw, col_x + COL_INNING // 2, by + ROW_BATTER - 5, bases)

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
        draw.line([(ix, by + ROW_BATTER), (SCORECARD_WIDTH, by + ROW_BATTER)], fill=0)

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
    draw.line([(x, ty), (SCORECARD_WIDTH, ty)], fill=0, width=2)

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


def _draw_pitcher_panel(draw, fonts, away_pitchers, home_pitchers):
    """Draw the right-side pitcher panel."""
    px = SCORECARD_WIDTH + 4
    draw.line([(SCORECARD_WIDTH, 0), (SCORECARD_WIDTH, EPD_HEIGHT)], fill=0)

    def _draw_side(pitchers, y_start, y_end, label):
        y = y_start
        draw.text((px, y), label, font=fonts['f11'], fill=0)
        y += 12
        draw.text((px, y), 'Name       IP  H ER  K', font=fonts['f9'], fill=0)
        y += 10
        draw.line([(SCORECARD_WIDTH, y), (EPD_WIDTH, y)], fill=0)
        y += 2
        for p in pitchers:
            if y + 11 > y_end:
                break
            name = p['name'][:10].ljust(10)
            line = f"{name} {p['ip']:>3} {p['hits']:>2} {p['er']:>2} {p['k']:>2}"
            draw.text((px, y), line, font=fonts['f9'], fill=0)
            y += 11

    _draw_side(away_pitchers, 2, TEAM_HEIGHT - 2, 'AWAY')
    draw.line([(SCORECARD_WIDTH, TEAM_HEIGHT), (EPD_WIDTH, TEAM_HEIGHT)], fill=0, width=2)
    _draw_side(home_pitchers, TEAM_HEIGHT + 2, EPD_HEIGHT - 2, 'HOME')


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

    # Full-width divider (spans scorecard + pitcher panel)
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

    _draw_pitcher_panel(
        draw, fonts,
        away_pitchers=data.get('away_pitchers', []),
        home_pitchers=data.get('home_pitchers', []),
    )

    if dark_mode:
        img = ImageOps.invert(img.convert('L')).convert('1')

    return img
