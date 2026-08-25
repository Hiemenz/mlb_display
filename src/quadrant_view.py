"""Team offense-vs-pitching quadrant chart (800x480, 1-bit e-ink).

Every club is plotted at both its current-window position (full-size logo) and
its season-baseline position (small logo), with an arrow connecting the two so
direction and magnitude of the move are both literal. The four corners show
strong both ways, strong one way, or neither.

Three grains — season, month, week — are three separate views over the same
data, selected by config (or rotated through). Data comes from
data/team_quadrant.json (see fetch_team_quadrant.py).
"""
import random as _random
from datetime import datetime

from PIL import ImageOps

from image_assets import Image, ImageDraw, _get_font, _load_logo_gray, _logo_small, _paste_logo

EPD_WIDTH = 800
EPD_HEIGHT = 480

GRAINS = ('season', 'month', 'week')

_HEADER_H = 32
_PLOT_L = 54
_PLOT_R = 790
_PLOT_T = 40
_PLOT_B = 442

_LOGO_SIZE = 26
_LOGO_R = _LOGO_SIZE // 2
_LOGO_SIZE_SMALL = 14
_LOGO_R_SMALL = _LOGO_SIZE_SMALL // 2
# Share of each logo's box that should end up black. Keeps busy and sparse
# logos at a similar visual weight instead of some vanishing and some blobbing.
_INK_TARGET = 0.34
# Minimum gap between logo centres. The +9 is a legibility gutter, not slack:
# at _LOGO_SIZE exactly, neighbours touch and a cluster reads as one smear at
# 1-bit; a few px of white between them is what makes each club identifiable.
# It must never drop to or below _LOGO_SIZE — each marker clears its own
# footprint to white before pasting, so closer centres let a later team erase
# a sliver of one already drawn.
_MIN_SEP = _LOGO_SIZE + 9
_RELAX_PASSES = 140
# Moves shorter than this are noise, not a trend, and only add clutter.
_MIN_TREND_PX = 7
_BIG_TREND_PX = 150
_TREND_LEN = 10
_TREND_LEN_BIG = 15

# Axis breathing room past the outermost team, as a fraction of the data span.
# Deliberately tight: the point of the chart is separating the field, and every
# unused percent of axis squeezes the teams closer together.
_AXIS_PAD = 0.03
# Upper bound on gridlines per axis. Higher means a finer step, which also
# means less waste when the bounds snap outward to a multiple of it.
_MAX_TICKS = 10

_CORNERS = {
    'tl': 'SEND HELP',
    'tr': 'NO PITCHING',
    'bl': 'NO OFFENSE',
    'br': 'BALANCED',
}
_CORNER_FONT_PX = 12
_CORNER_PAD = 6
_CORNER_H = 14
_caption_rect_cache = None


def _caption_rects():
    """(corner_key, x0, y0, x1, y1) for each quadrant caption, measured once.

    Layout placement reads these so logos can be kept clear of the captions:
    a marker paints a white box over its own footprint, so a logo landing on a
    caption would erase it outright.
    """
    global _caption_rect_cache
    if _caption_rect_cache is None:
        font = _get_font(_CORNER_FONT_PX)
        rects = []
        for key, text in _CORNERS.items():
            width = font.getbbox(text)[2]
            x0 = _PLOT_L + _CORNER_PAD if key[1] == 'l' else _PLOT_R - _CORNER_PAD - width
            y0 = _PLOT_T + _CORNER_PAD if key[0] == 't' else _PLOT_B - _CORNER_PAD - _CORNER_H
            rects.append((key, x0, y0, x0 + width, y0 + _CORNER_H))
        _caption_rect_cache = rects
    return _caption_rect_cache


def _clear_of_captions(x, y):
    """Nudge a logo centre vertically out of any caption it would cover."""
    for key, x0, y0, x1, y1 in _caption_rects():
        if x + _LOGO_R > x0 and x - _LOGO_R < x1 and y + _LOGO_R > y0 and y - _LOGO_R < y1:
            y = y1 + _LOGO_R if key[0] == 't' else y0 - _LOGO_R
    return x, y


def current_grain(config=None, now=None):
    """Resolve the configured grain, expanding 'rotate' to a time-block choice.

    Rotation is seeded by the clock block rather than random state so every
    render inside a window picks the same grain (and tests stay deterministic).
    """
    config = config or {}
    grain = str(config.get('quadrant_grain', 'season') or 'season').lower()
    if grain in GRAINS:
        return grain
    if grain != 'rotate':
        return 'season'

    minutes = max(int(config.get('quadrant_rotate_minutes', 30) or 30), 1)
    now = now or datetime.now()
    block = (now.hour * 60 + now.minute) // minutes
    return _random.Random(block).choice(GRAINS)


def _nice_step(span, candidates):
    """Smallest candidate step that keeps the axis under _MAX_TICKS gridlines.

    A finer step also means less rounding waste: bounds snap outward to a
    multiple of the step, so a coarse step can silently pad the axis by most
    of a tick on each side.
    """
    for step in candidates:
        if span / step <= _MAX_TICKS:
            return step
    return candidates[-1]


def _axis_bounds(values, pad_frac, candidates, minimum_span):
    """Return (lo, hi, step) covering values with a little padding.

    The bounds sit exactly at the padded data, deliberately *not* rounded out
    to the tick grid: snapping the ends to a round number gave away up to a
    full step on each side, which on the ERA axis is most of the visible range.
    Ticks are placed at round values inside these bounds instead, so the axis
    ends need no label and the teams get the whole plot.
    """
    if not values:
        return 0.0, 1.0, candidates[0]
    lo = min(values)
    hi = max(values)
    span = max(hi - lo, minimum_span)
    pad = span * pad_frac
    lo -= pad
    hi += pad
    return lo, hi, _nice_step(hi - lo, candidates)


def _floor_to(value, step):
    """Round down to a multiple of step."""
    return step * int(value / step) - (step if value < 0 and value % step else 0)


def _ceil_to(value, step):
    """Round up to a multiple of step."""
    floored = _floor_to(value, step)
    return floored if abs(floored - value) < 1e-9 else floored + step


def _ticks(lo, hi, step):
    """Round multiples of step lying inside [lo, hi].

    The bounds are no longer multiples of the step (see _axis_bounds), so the
    first tick is the first round value at or above lo, not lo itself.
    """
    first = _ceil_to(lo, step)
    out = []
    value = first
    while value <= hi + 1e-9:
        out.append(round(value, 6))
        value += step
    return out


def _fmt_tick(value, step):
    """Format a tick with just enough decimals to distinguish adjacent ticks.

    A 0.25 ERA step printed to one decimal renders 3.25 and 3.5 as "3.2" and
    "3.5" — the label would be wrong, not merely coarse.
    """
    if abs(step - round(step)) < 1e-9:
        return str(int(round(value)))
    if abs(step * 10 - round(step * 10)) < 1e-9:
        return f'{value:.1f}'
    return f'{value:.2f}'


class _Scale:
    """Maps (wRC+, ERA) data space onto plot pixels. ERA increases upward."""

    def __init__(self, x_lo, x_hi, y_lo, y_hi):
        self.x_lo, self.x_hi = x_lo, x_hi
        self.y_lo, self.y_hi = y_lo, y_hi

    def x(self, wrc):
        """Data wRC+ → pixel column."""
        frac = (wrc - self.x_lo) / (self.x_hi - self.x_lo or 1)
        return _PLOT_L + frac * (_PLOT_R - _PLOT_L)

    def y(self, era):
        """Data ERA → pixel row (higher ERA sits higher on screen)."""
        frac = (era - self.y_lo) / (self.y_hi - self.y_lo or 1)
        return _PLOT_B - frac * (_PLOT_B - _PLOT_T)


def _dashed_line(draw, start, end, dash=4, gap=4, fill=0):
    """Draw a dashed horizontal or vertical line."""
    x0, y0 = start
    x1, y1 = end
    if y0 == y1:
        x = x0
        while x < x1:
            draw.line([(x, y0), (min(x + dash, x1), y0)], fill=fill)
            x += dash + gap
    else:
        y = y0
        while y < y1:
            draw.line([(x0, y), (x0, min(y + dash, y1))], fill=fill)
            y += dash + gap


def _resolve_overlaps(points):
    """Nudge logo centres apart so clustered teams stay legible.

    Simple pairwise relaxation: any two centres closer than _MIN_SEP push each
    other half the shortfall, repeated until the field settles. Ties (identical
    coordinates) break on index so the layout is reproducible.
    """
    coords = [[x, y] for x, y in points]
    n = len(coords)
    for _ in range(_RELAX_PASSES):
        moved = False
        for i in range(n):
            for j in range(i + 1, n):
                dx = coords[j][0] - coords[i][0]
                dy = coords[j][1] - coords[i][1]
                dist = (dx * dx + dy * dy) ** 0.5
                if dist >= _MIN_SEP:
                    continue
                if dist < 1e-6:
                    dx, dy, dist = 1.0 if i % 2 else -1.0, 1.0, 1.0
                push = (_MIN_SEP - dist) / 2.0
                ux, uy = dx / dist, dy / dist
                coords[i][0] -= ux * push
                coords[i][1] -= uy * push
                coords[j][0] += ux * push
                coords[j][1] += uy * push
                moved = True
        for c in coords:
            c[0] = min(max(c[0], _PLOT_L + _LOGO_R), _PLOT_R - _LOGO_R)
            c[1] = min(max(c[1], _PLOT_T + _LOGO_R), _PLOT_B - _LOGO_R)
            c[0], c[1] = _clear_of_captions(c[0], c[1])
        if not moved:
            break
    return [(x, y) for x, y in coords]


def _tail_room(head, ux, uy):
    """How far back along the bearing a tail can run before leaving the plot."""
    limit = float('inf')
    for delta, lo, hi, pos in ((-ux, _PLOT_L + 1, _PLOT_R - 1, head[0]),
                               (-uy, _PLOT_T + 1, _PLOT_B - 1, head[1])):
        if abs(delta) < 1e-9:
            continue
        limit = min(limit, ((hi if delta > 0 else lo) - pos) / delta)
    return max(limit, 0.0)


def _draw_trend_badge(draw, tail, head, fill=0):
    """A short directional tick beside the logo, pointing back toward the baseline.

    Bearing is exact; length is not. See _BIG_TREND_PX: with a full-season
    baseline the true tail point is almost always too far away to reach with
    a readable line, so the tick stays a fixed short length and a second
    parallel stroke flags a big swing instead of drawing toward a point it
    could never actually reach.
    """
    x1, y1 = head
    dx, dy = x1 - tail[0], y1 - tail[1]
    dist = (dx * dx + dy * dy) ** 0.5
    if dist < _MIN_TREND_PX:
        return
    ux, uy = dx / dist, dy / dist

    big = dist >= _BIG_TREND_PX
    length = _TREND_LEN_BIG if big else _TREND_LEN

    # _tail_room measures room from the logo centre, not the shaft's near end
    # at the logo edge, so clamp the full centre-to-tail-end distance and
    # subtract the edge radius back out — shortening if it would run past the
    # axis frame, since the axes are scaled to the teams' current positions
    # and a badge can start near the edge.
    total = min(_LOGO_R + length, _tail_room(head, ux, uy))
    length = total - _LOGO_R
    if length < _MIN_TREND_PX:
        return

    # Stop the shaft at the logo's edge so the head stays visible.
    tip_x = x1 - ux * _LOGO_R
    tip_y = y1 - uy * _LOGO_R
    x0, y0 = x1 - ux * total, y1 - uy * total

    draw.line([(x0, y0), (tip_x, tip_y)], fill=fill)
    if big:
        ox, oy = -uy * 1.6, ux * 1.6
        draw.line([(x0 + ox, y0 + oy), (tip_x + ox, tip_y + oy)], fill=fill)

    head_len, head_w = (6.0, 3.2) if big else (4.0, 2.2)
    bx, by = tip_x - ux * head_len, tip_y - uy * head_len
    draw.polygon(
        [(tip_x, tip_y), (bx - uy * head_w, by + ux * head_w), (bx + uy * head_w, by - ux * head_w)],
        fill=fill,
    )


_ARROW_MAX_PX = 28


def _draw_arrow(draw, tail, head, fill=0):
    """Fixed-length directional arrow from the current logo edge toward the baseline.

    Bearing is exact; length is capped at _ARROW_MAX_PX so lines don't cross
    the whole chart. The small baseline logo shows where the baseline actually
    is; the arrow shows direction and a proportional (but capped) magnitude.
    """
    dx, dy = head[0] - tail[0], head[1] - tail[1]
    dist = (dx * dx + dy * dy) ** 0.5
    if dist < _MIN_TREND_PX:
        return
    ux, uy = dx / dist, dy / dist
    length = min(dist - _LOGO_R - _LOGO_R_SMALL, _ARROW_MAX_PX)
    if length < _MIN_TREND_PX:
        return
    tip_x, tip_y = head[0] - ux * _LOGO_R, head[1] - uy * _LOGO_R
    x0, y0 = tip_x - ux * length, tip_y - uy * length
    draw.line([(x0, y0), (tip_x, tip_y)], fill=fill)
    head_len, head_w = 4.0, 2.2
    bx, by = tip_x - ux * head_len, tip_y - uy * head_len
    draw.polygon(
        [(tip_x, tip_y), (bx - uy * head_w, by + ux * head_w), (bx + uy * head_w, by - ux * head_w)],
        fill=fill,
    )


def _draw_vertical_text(image, text, x, y_center, font):
    """Paste 90°-rotated text (used for the ERA axis title)."""
    bbox = font.getbbox(text)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    label = Image.new('1', (w + 2, h + 4), 1)
    ImageDraw.Draw(label).text((1 - bbox[0], 2 - bbox[1]), text, font=font, fill=0)
    label = label.rotate(90, expand=True)
    # Mask on the glyphs only, so the label's white box never erases the frame.
    image.paste(label, (int(x), int(y_center - label.height / 2)),
                mask=ImageOps.invert(label.convert('L')))


def _draw_header(image, draw, payload, grain_label):
    """Title row: baseline window → current window on the left, grain on the right."""
    baseline = (payload.get('baseline') or {}).get('label', '')
    current = (payload.get('current') or {}).get('label', '')
    f_small = _get_font(13)

    x = 10
    draw.text((x, 9), baseline, font=f_small, fill=0)
    x += f_small.getbbox(baseline)[2] + 10

    # Arrow between the two window labels, matching the on-plot movement arrows.
    draw.line([(x, 15), (x + 20, 15)], fill=0)
    draw.polygon([(x + 24, 15), (x + 17, 12), (x + 17, 18)], fill=0)
    x += 32

    draw.text((x, 9), current, font=f_small, fill=0)

    right = grain_label
    draw.text((EPD_WIDTH - 10 - f_small.getbbox(right)[2], 9), right, font=f_small, fill=0)
    draw.line([(0, _HEADER_H), (EPD_WIDTH, _HEADER_H)], fill=0)


def _draw_axes(image, draw, scale, x_step, y_step, avg):
    """Frame, ticks, gridline crosshair at the league average, and axis titles."""
    f_tick = _get_font(11)
    f_axis = _get_font(12)

    draw.rectangle([_PLOT_L, _PLOT_T, _PLOT_R, _PLOT_B], outline=0)

    # No range guard needed: _ticks only emits values inside the axis bounds,
    # so every tick maps inside the frame by construction.
    for value in _ticks(scale.x_lo, scale.x_hi, x_step):
        px = int(scale.x(value))
        draw.line([(px, _PLOT_B), (px, _PLOT_B + 4)], fill=0)
        text = _fmt_tick(value, x_step)
        draw.text((px - f_tick.getbbox(text)[2] / 2, _PLOT_B + 6), text, font=f_tick, fill=0)

    for value in _ticks(scale.y_lo, scale.y_hi, y_step):
        py = int(scale.y(value))
        draw.line([(_PLOT_L - 4, py), (_PLOT_L, py)], fill=0)
        text = _fmt_tick(value, y_step)
        draw.text((_PLOT_L - 7 - f_tick.getbbox(text)[2], py - 6), text, font=f_tick, fill=0)

    # League-average crosshair — the lines that make the four quadrants.
    avg_x = int(scale.x(avg['wrc']))
    avg_y = int(scale.y(avg['era']))
    _dashed_line(draw, (avg_x, _PLOT_T + 1), (avg_x, _PLOT_B - 1))
    _dashed_line(draw, (_PLOT_L + 1, avg_y), (_PLOT_R - 1, avg_y))
    draw.text((avg_x + 3, _PLOT_T + 2), 'AVG', font=_get_font(9), fill=0)
    draw.text((_PLOT_R - 26, avg_y + 2), 'AVG', font=_get_font(9), fill=0)

    title = 'wRC+*  (offense)'
    draw.text(((_PLOT_L + _PLOT_R) / 2 - f_axis.getbbox(title)[2] / 2, _PLOT_B + 22),
              title, font=f_axis, fill=0)
    _draw_vertical_text(image, 'ERA', 2, (_PLOT_T + _PLOT_B) / 2, f_axis)


def _draw_corner_labels(draw):
    """The four quadrant captions, drawn in the rects layout keeps clear.

    Top-right ("NO PITCHING") is faux-bolded by overdrawing one pixel across
    — the e-ink font has no bold face — to draw the eye there first: a team
    with no pitching is the more actionable read of the four corners.
    """
    font = _get_font(_CORNER_FONT_PX)
    for key, x0, y0, _, _ in _caption_rects():
        draw.text((x0, y0), _CORNERS[key], font=font, fill=0)
        if key == 'tr':
            draw.text((x0 + 1, y0), _CORNERS[key], font=font, fill=0)


def _logo_marker(abbr, team_id, size=_LOGO_SIZE):
    """A 1-bit logo tuned for a dense scatter, or None when no artwork exists.

    _logo_small's 3x contrast boost is right for a name row but crushes the
    busier logos (LAA, AZ, BAL, MIN...) into solid black discs when they sit
    30-to-a-plot at this size. Instead, threshold each logo at the percentile
    that leaves roughly _INK_TARGET of its box inked, so every club lands at a
    comparable visual weight and keeps its internal detail.
    """
    gray = _load_logo_gray(abbr, team_id)
    if gray is None:
        return _logo_small(abbr, team_id, size=size)

    gray = gray.copy()
    gray.thumbnail((size, size), Image.LANCZOS)
    gray = ImageOps.autocontrast(gray, cutoff=1)

    histogram = gray.histogram()
    total = sum(histogram)
    if not total:
        return _logo_small(abbr, team_id, size=size)

    target = total * _INK_TARGET
    running = 0
    threshold = 0
    for level, count in enumerate(histogram):
        running += count
        if running >= target:
            threshold = level
            break

    # A flat or near-flat logo has no percentile to find; keep it visible anyway.
    threshold = min(max(threshold, 1), 240)
    return gray.point(lambda p: 0 if p <= threshold else 255).convert('1')


def _team_marker(image, draw, team, center):
    """Paste the team logo at center, falling back to a boxed abbreviation."""
    cx, cy = int(center[0]), int(center[1])
    logo = _logo_marker(team.get('abbr', ''), team.get('id'))
    if logo is not None:
        # Clear the logo's footprint so arrows and gridlines don't read through it.
        draw.rectangle([cx - _LOGO_R, cy - _LOGO_R, cx + _LOGO_R, cy + _LOGO_R], fill=1)
        _paste_logo(image, logo, (cx - logo.width // 2, cy - logo.height // 2))
        return

    abbr = team.get('abbr', '')
    font = _get_font(11)
    bbox = font.getbbox(abbr)
    w = bbox[2] + 4
    draw.rectangle([cx - w / 2, cy - 8, cx + w / 2, cy + 8], fill=1, outline=0)
    draw.text((cx - bbox[2] / 2, cy - 6), abbr, font=font, fill=0)


def _team_marker_small(image, draw, team, center):
    """Small logo at the baseline position."""
    cx, cy = int(center[0]), int(center[1])
    logo = _logo_marker(team.get('abbr', ''), team.get('id'), size=_LOGO_SIZE_SMALL)
    if logo is not None:
        draw.rectangle([cx - _LOGO_R_SMALL, cy - _LOGO_R_SMALL,
                        cx + _LOGO_R_SMALL, cy + _LOGO_R_SMALL], fill=1)
        _paste_logo(image, logo, (cx - logo.width // 2, cy - logo.height // 2))
        return
    abbr = team.get('abbr', '')
    font = _get_font(9)
    bbox = font.getbbox(abbr)
    w = bbox[2] + 2
    draw.rectangle([cx - w / 2, cy - 6, cx + w / 2, cy + 6], fill=1, outline=0)
    draw.text((cx - bbox[2] / 2, cy - 4), abbr, font=font, fill=0)


def render_quadrant_view(data, grain=None, config=None, dark_mode=False, now=None):
    """Render the quadrant chart for one grain. Returns an 800x480 '1'-mode image.

    Raises ValueError when the payload has no usable grain, so callers can fall
    back to another display mode rather than show an empty plot.
    """
    grains = (data or {}).get('grains') or {}
    if not grains:
        raise ValueError('no quadrant data available')

    grain = grain or current_grain(config, now=now)
    payload = grains.get(grain)
    if not payload:
        # Configured grain missing (e.g. a partial fetch) — show whatever we have.
        grain = next(g for g in GRAINS if g in grains)
        payload = grains[grain]

    teams = payload.get('teams') or []
    if not teams:
        raise ValueError(f'no teams in quadrant grain {grain}')

    image = Image.new('1', (EPD_WIDTH, EPD_HEIGHT), 1)
    draw = ImageDraw.Draw(image)

    avg = payload.get('avg') or {}
    avg = {'wrc': avg.get('wrc', 100.0), 'era': avg.get('era', 4.0)}

    xs = ([t['wrc'] for t in teams]
          + [t['was_wrc'] for t in teams if t.get('was_wrc') is not None]
          + [avg['wrc']])
    ys = ([t['era'] for t in teams]
          + [t['was_era'] for t in teams if t.get('was_era') is not None]
          + [avg['era']])

    x_lo, x_hi, x_step = _axis_bounds(xs, _AXIS_PAD, [1, 2, 5, 10, 20], 10.0)
    y_lo, y_hi, y_step = _axis_bounds(ys, _AXIS_PAD, [0.1, 0.25, 0.5, 1.0, 2.0], 1.0)
    scale = _Scale(x_lo, x_hi, y_lo, y_hi)

    _draw_header(image, draw, payload, payload.get('label', grain.upper()))
    _draw_axes(image, draw, scale, x_step, y_step, avg)
    _draw_corner_labels(draw)

    raw = [(scale.x(t['wrc']), scale.y(t['era'])) for t in teams]
    placed = _resolve_overlaps(raw)

    # Arrows first, then small baseline logos over arrow tails, then full logos on top.
    for team, center in zip(teams, placed):
        if team.get('was_wrc') is None or team.get('was_era') is None:
            continue
        tail = (scale.x(team['was_wrc']), scale.y(team['was_era']))
        _draw_arrow(draw, tail, center)

    for team, _center in zip(teams, placed):
        if team.get('was_wrc') is None or team.get('was_era') is None:
            continue
        tail = (scale.x(team['was_wrc']), scale.y(team['was_era']))
        _team_marker_small(image, draw, team, tail)

    for team, center in zip(teams, placed):
        _team_marker(image, draw, team, center)

    if dark_mode:
        image = ImageOps.invert(image.convert('L')).convert('1')
    return image


def main():
    """CLI: render the cached quadrant chart and export as a PNG."""
    import argparse
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from util import load_json_file

    parser = argparse.ArgumentParser(
        description='Render the team offense-vs-pitching quadrant chart.',
    )
    parser.add_argument('--grain', choices=GRAINS, default=None,
                        help='Which grain to render (default: from config / season).')
    parser.add_argument('--export-png', metavar='PATH', default='quadrant.png',
                        help='Output path for the exported PNG (default: quadrant.png).')
    parser.add_argument('--dark', action='store_true', help='Dark/inverted output.')
    parser.add_argument('--scale', type=int, default=2,
                        help='Integer upscale factor for the export (default: 2 → 1600×960).')
    args = parser.parse_args()

    data = load_json_file('team_quadrant.json')
    if not data:
        print('No team_quadrant.json cached. Run: python src/fetch_team_quadrant.py')
        sys.exit(1)

    try:
        image = render_quadrant_view(data, grain=args.grain, dark_mode=args.dark)
    except ValueError as e:
        print(f'Render failed: {e}')
        sys.exit(1)

    export = image.convert('L')
    if args.scale > 1:
        export = export.resize(
            (image.width * args.scale, image.height * args.scale),
            resample=Image.NEAREST,
        )
    export.save(args.export_png)
    grain_used = args.grain or 'season'
    print(f'Saved {args.export_png} ({export.width}×{export.height}, grain={grain_used})')


if __name__ == '__main__':  # pragma: no cover
    main()
