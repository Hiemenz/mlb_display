"""Draw a bullpen-workload panel cell (135x130) for an empty grid slot.

One tile per team, from data/bullpen.json: each reliever who pitched in the last
few days gets a bar. The solid part is the last game's pitches, the hatched part is
the rest of the window, and the number is the window total.
"""
import panel_cell
from image_assets import ImageDraw, _get_font

MAX_ROWS = 6
# More than MAX_ROWS pitchers switches to two columns of 'Name  total' rows so a
# whole roster's relievers fit in the tile: no bars, and a pitcher who threw
# yesterday gets an inverted number.
COMPACT_ROWS = 8
_COMPACT_NUM_W = 19
_COMPACT_COL_GAP = 7
_BAR_FULL_PITCHES = 50
_NAME_W = 46
_NUM_W = 16
_BAR_H = 8
_FOOTER_H = 14


def _draw_bar(draw, x, y, w, yesterday, total):
    """Outlined bar scaled to ``_BAR_FULL_PITCHES``; solid for the last game, hatched for the earlier days."""
    draw.rectangle([x, y, x + w - 1, y + _BAR_H - 1], outline=0)
    inner = w - 2
    total_w = min(inner, round(inner * total / _BAR_FULL_PITCHES))
    yday_w = min(total_w, round(inner * yesterday / _BAR_FULL_PITCHES))
    if yday_w:
        draw.rectangle([x + 1, y + 1, x + yday_w, y + _BAR_H - 2], fill=0)
    for hx in range(x + 1 + yday_w, x + 1 + total_w, 2):
        draw.line([(hx, y + 1), (hx, y + _BAR_H - 2)], fill=0)


def _draw_footer(draw, sx, sy, days, font):
    """Legend along the bottom edge: solid = yesterday, hatched = the rest of the window."""
    fy = sy + panel_cell.CELL_H - _FOOTER_H
    sw = 8
    x = sx + panel_cell.PAD + 2
    draw.rectangle([x, fy + 3, x + sw - 1, fy + 3 + sw - 1], fill=0)
    label = 'Yesterday'
    draw.text((x + sw + 2, fy + 1), label, font=font, fill=0)
    x += sw + 2 + int(font.getlength(label)) + 8
    _draw_bar(draw, x, fy + 3, sw + 4, 0, _BAR_FULL_PITCHES)
    draw.text((x + sw + 6, fy + 1), f'{days}d', font=font, fill=0)


def _draw_compact(draw, sx, sy, pitchers, font):
    """Two columns of 'Name  23', heaviest first, filled column by column."""
    body_h = panel_cell.CELL_H - panel_cell.HEADER_H - _FOOTER_H
    row_h = body_h // COMPACT_ROWS
    col_w = (panel_cell.CELL_W - 2 * panel_cell.PAD - _COMPACT_COL_GAP) // 2
    name_w = col_w - _COMPACT_NUM_W - 2
    for i, p in enumerate(pitchers[:2 * COMPACT_ROWS]):
        col, row = divmod(i, COMPACT_ROWS)
        cx = sx + panel_cell.PAD + col * (col_w + _COMPACT_COL_GAP)
        ry = sy + panel_cell.HEADER_H + 2 + row * row_h
        full = p.get('name', '')
        last = full.partition(' ')[2] or full
        draw.text((cx, ry), panel_cell.truncate(font, last, name_w), font=font, fill=0)
        ptotal = p.get('total', 0)
        lbl = '–' if ptotal == 0 else str(ptotal)
        lx = cx + col_w - 1 - int(font.getlength(lbl))
        if p.get('yesterday', 0):
            draw.rectangle([lx - 1, ry, cx + col_w - 1, ry + row_h - 2], fill=0)
            draw.text((lx, ry), lbl, font=font, fill=255)
        else:
            draw.text((lx, ry), lbl, font=font, fill=0)


def _draw_compact_footer(draw, sx, sy, days, font):
    """Legend for the compact layout: inverted number = yesterday, number = window total."""
    fy = sy + panel_cell.CELL_H - _FOOTER_H
    x = sx + panel_cell.PAD + 2
    draw.rectangle([x, fy + 3, x + 7, fy + 10], fill=0)
    draw.text((x + 10, fy + 1), 'Yesterday', font=font, fill=0)
    x += 10 + int(font.getlength('Yesterday')) + 8
    draw.text((x, fy + 1), f'{days}d total', font=font, fill=0)


def draw_bullpen_cell(Himage, sx, sy, team_entry, days=3):
    """Draw one team's bullpen tile into the cell at pixel (sx, sy).

    team_entry: one value of bullpen.json's 'teams' dict ('abbr', 'pitchers').
    """
    draw = ImageDraw.Draw(Himage)
    team_entry = team_entry or {}
    pitchers = team_entry.get('pitchers', [])
    compact = len(pitchers) > MAX_ROWS
    pitchers = pitchers[:2 * COMPACT_ROWS if compact else MAX_ROWS]
    font = _get_font(10)

    panel_cell.draw_chrome(draw, sx, sy, f"{team_entry.get('abbr', '')} Bullpen")

    if not pitchers:
        panel_cell.draw_empty(draw, sx, sy, 'Fully rested', panel_cell.row_font(0))
        return Himage

    if compact:
        _draw_compact(draw, sx, sy, pitchers, font)
        _draw_compact_footer(draw, sx, sy, days, font)
        return Himage

    body_h = panel_cell.CELL_H - panel_cell.HEADER_H - _FOOTER_H
    row_h = min(16, body_h // MAX_ROWS)
    bar_x = sx + panel_cell.PAD + _NAME_W + 2
    bar_w = panel_cell.CELL_W - (bar_x - sx) - panel_cell.PAD - _NUM_W - 2

    for i, p in enumerate(pitchers):
        ry = sy + panel_cell.HEADER_H + 2 + i * row_h
        name = panel_cell.truncate(font, p.get('name', ''), _NAME_W)
        draw.text((sx + panel_cell.PAD, ry), name, font=font, fill=0)
        ptotal = p.get('total', 0)
        _draw_bar(draw, bar_x, ry + 2, bar_w, p.get('yesterday', 0), ptotal)
        lbl = '–' if ptotal == 0 else str(ptotal)
        draw.text((sx + panel_cell.CELL_W - panel_cell.PAD - int(font.getlength(lbl)), ry),
                  lbl, font=font, fill=0)

    _draw_footer(draw, sx, sy, days, font)
    return Himage
