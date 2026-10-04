"""Draw a bullpen-workload panel cell (135x130) for an empty grid slot.

One tile per team, from data/bullpen.json: each reliever who pitched in the last
few days gets a bar. The solid part is the last game's pitches, the hatched part is
the rest of the window, and the number is the window total.
"""
import panel_cell
from image_assets import ImageDraw, _get_font

MAX_ROWS = 11
_MIN_ROW_H = 9
_MAX_ROW_H = 16
_BAR_FULL_PITCHES = 50
_NAME_W = 46
_NUM_W = 16
_BAR_H = 8


def _draw_bar(draw, x, y, w, yesterday, total, h=_BAR_H):
    """Outlined bar scaled to ``_BAR_FULL_PITCHES``; solid for the last game, hatched for the earlier days."""
    draw.rectangle([x, y, x + w - 1, y + h - 1], outline=0)
    inner = w - 2
    total_w = min(inner, round(inner * total / _BAR_FULL_PITCHES))
    yday_w = min(total_w, round(inner * yesterday / _BAR_FULL_PITCHES))
    if yday_w:
        draw.rectangle([x + 1, y + 1, x + yday_w, y + h - 2], fill=0)
    for hx in range(x + 1 + yday_w, x + 1 + total_w, 2):
        draw.line([(hx, y + 1), (hx, y + h - 2)], fill=0)


def _draw_header(draw, sx, sy, abbr, days, title_font, key_font):
    """Frame plus a left title and, right-aligned, the key: solid = yesterday, hatched = the window."""
    panel_cell.draw_chrome(draw, sx, sy, '')
    title = f'{abbr} Bullpen'
    tx = sx + panel_cell.PAD + 1
    draw.text((tx, sy + 4), title, font=title_font, fill=0)
    draw.text((tx + 1, sy + 4), title, font=title_font, fill=0)

    sw = 7
    top = sy + (panel_cell.HEADER_H - sw) // 2 + 1
    hatched = f'{days}d'
    x = sx + panel_cell.CELL_W - panel_cell.PAD - 1 - int(key_font.getlength(hatched))
    draw.text((x, sy + 5), hatched, font=key_font, fill=0)
    x -= 2 + sw
    draw.rectangle([x, top, x + sw - 1, top + sw - 1], outline=0)
    for hx in range(x + 1, x + sw - 1, 2):
        draw.line([(hx, top + 1), (hx, top + sw - 2)], fill=0)
    x -= 5 + int(key_font.getlength('1d'))
    draw.text((x, sy + 5), '1d', font=key_font, fill=0)
    x -= 2 + sw
    draw.rectangle([x, top, x + sw - 1, top + sw - 1], fill=0)


def draw_bullpen_cell(Himage, sx, sy, team_entry, days=3):
    """Draw one team's bullpen tile into the cell at pixel (sx, sy).

    team_entry: one value of bullpen.json's 'teams' dict ('abbr', 'pitchers').
    """
    draw = ImageDraw.Draw(Himage)
    team_entry = team_entry or {}
    pitchers = team_entry.get('pitchers', [])[:MAX_ROWS]
    font = _get_font(10)

    _draw_header(draw, sx, sy, team_entry.get('abbr', ''), days,
                 panel_cell.row_font(0), font)

    if not pitchers:
        panel_cell.draw_empty(draw, sx, sy, 'Fully rested', panel_cell.row_font(0))
        return Himage

    body_h = panel_cell.CELL_H - panel_cell.HEADER_H - 4
    row_h = max(_MIN_ROW_H, min(_MAX_ROW_H, body_h // len(pitchers)))
    bar_h = min(_BAR_H, row_h - 3)
    bar_x = sx + panel_cell.PAD + _NAME_W + 2
    bar_w = panel_cell.CELL_W - (bar_x - sx) - panel_cell.PAD - _NUM_W - 2

    for i, p in enumerate(pitchers):
        ry = sy + panel_cell.HEADER_H + 2 + i * row_h
        name = panel_cell.truncate(font, p.get('name', ''), _NAME_W)
        draw.text((sx + panel_cell.PAD, ry), name, font=font, fill=0)
        ptotal = p.get('total', 0)
        _draw_bar(draw, bar_x, ry + 3 - (bar_h - 6) // 2, bar_w, p.get('yesterday', 0), ptotal, bar_h)
        lbl = '–' if ptotal == 0 else str(ptotal)
        draw.text((sx + panel_cell.CELL_W - panel_cell.PAD - int(font.getlength(lbl)), ry),
                  lbl, font=font, fill=0)

    return Himage
