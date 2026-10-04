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


# Hatch spacing per shade, newest first: None is solid (yesterday), then a dense
# hatch (two days ago), then a sparse one (everything older in the window).
_SHADES = (None, 2, 4)


def _fill_shade(draw, x0, x1, y0, y1, step):
    """Fill columns x0..x1 (exclusive end) of a bar with one shade."""
    if x1 <= x0:
        return
    if step is None:
        draw.rectangle([x0, y0, x1 - 1, y1], fill=0)
    else:
        for hx in range(x0, x1, step):
            draw.line([(hx, y0), (hx, y1)], fill=0)


def _draw_bar(draw, x, y, w, yesterday, total, h=_BAR_H, day2=0):
    """Outlined bar scaled to ``_BAR_FULL_PITCHES``: solid for yesterday, dense
    hatch for two days ago, sparse hatch for the rest of the window."""
    draw.rectangle([x, y, x + w - 1, y + h - 1], outline=0)
    inner = w - 2

    def px(pitches):
        return min(inner, round(inner * pitches / _BAR_FULL_PITCHES))

    ends = [px(yesterday), px(yesterday + day2), px(total)]
    start = 0
    for end, step in zip(ends, _SHADES):
        end = max(end, start)
        _fill_shade(draw, x + 1 + start, x + 1 + end, y + 1, y + h - 2, step)
        start = end


def _draw_header(draw, sx, sy, abbr, days, key_font):
    """Frame plus a left title and, right-aligned, the key: one shade per day back
    (1 solid, 2 dense hatch, then sparse hatch labelled with the window, e.g. '3d')."""
    panel_cell.draw_chrome(draw, sx, sy, '')
    labels = ['1', '2', str(days)][:min(days, 3)]
    labels[-1] += 'd'
    sw = 7
    top = sy + (panel_cell.HEADER_H - sw) // 2 + 1
    x = sx + panel_cell.CELL_W - panel_cell.PAD - 1
    for label, step in reversed(list(zip(labels, _SHADES))):
        x -= int(key_font.getlength(label))
        draw.text((x, sy + 5), label, font=key_font, fill=0)
        x -= 1 + sw
        if step is None:
            draw.rectangle([x, top, x + sw - 1, top + sw - 1], fill=0)
        else:
            draw.rectangle([x, top, x + sw - 1, top + sw - 1], outline=0)
            _fill_shade(draw, x + 1, x + sw - 1, top + 1, top + sw - 2, step)
        x -= 3

    title = f'{abbr} Bullpen'
    tx = sx + panel_cell.PAD + 1
    for size in (12, 11, 10):
        title_font = _get_font(size)
        if tx + int(title_font.getlength(title)) + 1 < x:
            break
    draw.text((tx, sy + 4), title, font=title_font, fill=0)
    draw.text((tx + 1, sy + 4), title, font=title_font, fill=0)


def draw_bullpen_cell(Himage, sx, sy, team_entry, days=3):
    """Draw one team's bullpen tile into the cell at pixel (sx, sy).

    team_entry: one value of bullpen.json's 'teams' dict ('abbr', 'pitchers').
    """
    draw = ImageDraw.Draw(Himage)
    team_entry = team_entry or {}
    pitchers = team_entry.get('pitchers', [])[:MAX_ROWS]
    font = _get_font(10)

    _draw_header(draw, sx, sy, team_entry.get('abbr', ''), days, font)

    if not pitchers:
        panel_cell.draw_empty(draw, sx, sy, 'Fully rested', panel_cell.row_font(0))
        return Himage

    body_h = panel_cell.CELL_H - panel_cell.HEADER_H - 4
    row_h = max(_MIN_ROW_H, min(_MAX_ROW_H, body_h // len(pitchers)))
    bar_h = min(_BAR_H, row_h - 3)
    bar_x = sx + panel_cell.PAD + _NAME_W + 4
    bar_w = panel_cell.CELL_W - (bar_x - sx) - panel_cell.PAD - _NUM_W - 2

    for i, p in enumerate(pitchers):
        ry = sy + panel_cell.HEADER_H + 2 + i * row_h
        name = panel_cell.truncate(font, p.get('name', ''), _NAME_W)
        draw.text((sx + panel_cell.PAD, ry), name, font=font, fill=0)
        ptotal = p.get('total', 0)
        _draw_bar(draw, bar_x, ry + 10 - bar_h, bar_w, p.get('yesterday', 0), ptotal, bar_h,
                  p.get('day2', 0))
        lbl = '–' if ptotal == 0 else str(ptotal)
        draw.text((sx + panel_cell.CELL_W - panel_cell.PAD - int(font.getlength(lbl)), ry),
                  lbl, font=font, fill=0)

    return Himage
