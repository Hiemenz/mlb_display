"""Team offense-vs-pitching quadrant chart (800x480, 1-bit e-ink).

Every club is plotted by offense (wRC+ proxy, X) against run prevention (ERA,
Y, worse upward), splitting the field into the four corners the chart is really
about: strong both ways, strong one way, or neither. An arrow trails each logo
back to where that team sat over the baseline window, so the direction a team
is heading is visible without an animation the display cannot show.

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
# Share of each logo's box that should end up black. Keeps busy and sparse
# logos at a similar visual weight instead of some vanishing and some blobbing.
_INK_TARGET = 0.34
# Minimum gap between logo centres. Below the logo width, so dense clusters
# still nudge apart instead of exploding across the whole plot.
_MIN_SEP = 25
_RELAX_PASSES = 140
# Arrows shorter than this are noise, not a trend, and only add clutter.
_MIN_ARROW_PX = 7
# ...and longer than this stop being readable. At the week grain every team's
# baseline is the same season-to-date point, so uncapped shafts all converge
# into one hairball across the middle of the plot. Clamping keeps the bearing
# exact — which is the thing being communicated — and only truncates length.
_MAX_ARROW_PX = 58

_CORNERS = {
    'tl': 'SEND HELP',
    'tr': 'NO PITCHING',
    'bl': 'NO OFFENSE',
    'br': 'BALANCED',
}


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
    """Smallest candidate step that keeps the axis under ~8 ticks."""
    for step in candidates:
        if span / step <= 8:
            return step
    return candidates[-1]


def _axis_bounds(values, pad_frac, candidates, minimum_span):
    """Return (lo, hi, step) covering values with padding, snapped to the step grid."""
    if not values:
        return 0.0, 1.0, candidates[0]
    lo = min(values)
    hi = max(values)
    span = max(hi - lo, minimum_span)
    pad = span * pad_frac
    lo -= pad
    hi += pad

    step = _nice_step(hi - lo, candidates)
    lo = _floor_to(lo, step)
    hi = _ceil_to(hi, step)
    return lo, hi, step


def _floor_to(value, step):
    """Round down to a multiple of step."""
    return step * int(value / step) - (step if value < 0 and value % step else 0)


def _ceil_to(value, step):
    """Round up to a multiple of step."""
    floored = _floor_to(value, step)
    return floored if abs(floored - value) < 1e-9 else floored + step


def _ticks(lo, hi, step):
    """Tick values from lo to hi inclusive."""
    out = []
    steps = int(round((hi - lo) / step))
    for i in range(steps + 1):
        out.append(lo + i * step)
    return out


def _fmt_tick(value, step):
    """Format a tick: integers when the step is whole, else one decimal."""
    if abs(step - round(step)) < 1e-9:
        return str(int(round(value)))
    return f'{value:.1f}'


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
        if not moved:
            break
    return [(x, y) for x, y in coords]


def _draw_arrow(draw, tail, head, fill=0):
    """Line from the baseline position to just outside the logo, tipped with a head."""
    x1, y1 = head
    dx, dy = x1 - tail[0], y1 - tail[1]
    dist = (dx * dx + dy * dy) ** 0.5
    if dist < _MIN_ARROW_PX:
        return
    ux, uy = dx / dist, dy / dist

    # Pull an over-long tail in along its own bearing (see _MAX_ARROW_PX).
    dist = min(dist, _MAX_ARROW_PX)
    x0, y0 = x1 - ux * dist, y1 - uy * dist

    # Stop the shaft at the logo's edge so the head stays visible.
    tip_x = x1 - ux * _LOGO_R
    tip_y = y1 - uy * _LOGO_R
    if ((tip_x - x0) ** 2 + (tip_y - y0) ** 2) ** 0.5 < 3:
        return

    draw.line([(x0, y0), (tip_x, tip_y)], fill=fill)
    draw.ellipse([x0 - 2, y0 - 2, x0 + 2, y0 + 2], outline=fill)

    head_len, head_w = 6.0, 3.0
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
    f_big = _get_font(18)

    x = 10
    draw.text((x, 9), baseline, font=f_small, fill=0)
    x += f_small.getbbox(baseline)[2] + 10

    # Arrow between the two window labels, matching the on-plot movement arrows.
    draw.line([(x, 15), (x + 20, 15)], fill=0)
    draw.polygon([(x + 24, 15), (x + 17, 12), (x + 17, 18)], fill=0)
    x += 32

    draw.text((x, 5), current, font=f_big, fill=0)
    # Faux-bold: the e-ink font has no bold face, so overdraw one pixel across.
    draw.text((x + 1, 5), current, font=f_big, fill=0)

    right = grain_label
    draw.text((EPD_WIDTH - 10 - f_small.getbbox(right)[2], 9), right, font=f_small, fill=0)
    draw.line([(0, _HEADER_H), (EPD_WIDTH, _HEADER_H)], fill=0)


def _draw_axes(image, draw, scale, x_step, y_step, avg):
    """Frame, ticks, gridline crosshair at the league average, and axis titles."""
    f_tick = _get_font(11)
    f_axis = _get_font(12)

    draw.rectangle([_PLOT_L, _PLOT_T, _PLOT_R, _PLOT_B], outline=0)

    for value in _ticks(scale.x_lo, scale.x_hi, x_step):
        px = int(scale.x(value))
        if px < _PLOT_L or px > _PLOT_R:
            continue
        draw.line([(px, _PLOT_B), (px, _PLOT_B + 4)], fill=0)
        text = _fmt_tick(value, x_step)
        draw.text((px - f_tick.getbbox(text)[2] / 2, _PLOT_B + 6), text, font=f_tick, fill=0)

    for value in _ticks(scale.y_lo, scale.y_hi, y_step):
        py = int(scale.y(value))
        if py < _PLOT_T or py > _PLOT_B:
            continue
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
    """The four quadrant captions, inset from each corner of the plot."""
    font = _get_font(12)
    pad = 6
    draw.text((_PLOT_L + pad, _PLOT_T + pad), _CORNERS['tl'], font=font, fill=0)
    tr = _CORNERS['tr']
    draw.text((_PLOT_R - pad - font.getbbox(tr)[2], _PLOT_T + pad), tr, font=font, fill=0)
    draw.text((_PLOT_L + pad, _PLOT_B - pad - 14), _CORNERS['bl'], font=font, fill=0)
    br = _CORNERS['br']
    draw.text((_PLOT_R - pad - font.getbbox(br)[2], _PLOT_B - pad - 14), br, font=font, fill=0)


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

    # Bound the axes over both endpoints of every arrow so no tail falls off-plot.
    xs = [t['wrc'] for t in teams] + [t['was_wrc'] for t in teams if t.get('was_wrc') is not None]
    ys = [t['era'] for t in teams] + [t['was_era'] for t in teams if t.get('was_era') is not None]
    xs.append(avg['wrc'])
    ys.append(avg['era'])

    x_lo, x_hi, x_step = _axis_bounds(xs, 0.06, [2, 5, 10, 20], 10.0)
    y_lo, y_hi, y_step = _axis_bounds(ys, 0.06, [0.25, 0.5, 1.0, 2.0], 1.0)
    scale = _Scale(x_lo, x_hi, y_lo, y_hi)

    _draw_header(image, draw, payload, payload.get('label', grain.upper()))
    _draw_axes(image, draw, scale, x_step, y_step, avg)
    _draw_corner_labels(draw)

    raw = [(scale.x(t['wrc']), scale.y(t['era'])) for t in teams]
    placed = _resolve_overlaps(raw)

    # Arrows first so every logo paints over its own shaft, not a neighbour's.
    for team, center in zip(teams, placed):
        if team.get('was_wrc') is None or team.get('was_era') is None:
            continue
        tail = (scale.x(team['was_wrc']), scale.y(team['was_era']))
        _draw_arrow(draw, tail, center)

    for team, center in zip(teams, placed):
        _team_marker(image, draw, team, center)

    if dark_mode:
        image = ImageOps.invert(image.convert('L')).convert('1')
    return image
