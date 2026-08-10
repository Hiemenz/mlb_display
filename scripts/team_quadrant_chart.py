#!/usr/bin/env python3
"""Render the team quadrant chart as a full-colour PNG.

Same data and same four corners as the e-ink `quadrant` display mode, but sized
for a screen instead of a 1-bit panel: shaded quadrants, colour team logos, and
grey movement arrows back to each team's baseline position.

The e-ink view (src/quadrant_view.py) and this script deliberately share only
the fetch layer — the layouts have nothing in common at 800x480 versus 1600x900.

Usage (from the repo root):
    python scripts/team_quadrant_chart.py                      # month grain
    python scripts/team_quadrant_chart.py --grain week --fetch
    python scripts/team_quadrant_chart.py --grain all --out output/
"""
import os
import sys
import argparse
import urllib.request

from PIL import Image, ImageDraw, ImageFont

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, 'src'))

from util import load_json_file  # noqa: E402
from fetch_team_quadrant import fetch_team_quadrant, GRAINS  # noqa: E402
from download_logos import ESPN_ABBR_OVERRIDES, ESPN_LOGO_URL_NORMAL  # noqa: E402

_FONT_PATH = os.path.join(_REPO_ROOT, 'pic', 'Font.ttc')
_COLOR_LOGO_DIR = os.path.join(_REPO_ROOT, 'pic', 'logos_color')

# Supersampling factor — everything is drawn at 2x and downsampled at the end,
# which is the cheapest way to get antialiased lines and text out of Pillow.
_SS = 2

_W, _H = 1600, 900
_MARGIN_L, _MARGIN_R = 110, 40
_MARGIN_T, _MARGIN_B = 90, 100

_BG = (255, 255, 255)
_INK = (36, 42, 52)
_AXIS = (90, 127, 166)
_GRID = (232, 236, 241)
_FRAME = (203, 211, 221)
_ARROW = (150, 158, 170)
_DASH = (150, 165, 185)

_QUAD_FILL = {
    'tl': (253, 237, 236),   # send help — bad offense, bad pitching
    'tr': (245, 247, 250),
    'bl': (245, 247, 250),
    'br': (234, 247, 239),   # balanced — good offense, good pitching
}
_CORNERS = [
    ('tl', 'SEND HELP', (192, 57, 43)),
    ('tr', 'NO PITCHING', (44, 95, 141)),
    ('bl', 'NO OFFENSE', (127, 140, 141)),
    ('br', 'BALANCED', (39, 174, 96)),
]

_LOGO_PX = 54
_MIN_SEP = 52
_RELAX_PASSES = 160
_MIN_ARROW = 14
_MAX_ARROW = 150


def _font(size):
    """Load the shared display font at a supersampled size."""
    return ImageFont.truetype(_FONT_PATH, int(size * _SS))


def _espn_abbr(abbr):
    """MLB abbreviation → ESPN CDN path segment."""
    return ESPN_ABBR_OVERRIDES.get(abbr, abbr.lower())


def color_logo(abbr):
    """Return the team's colour logo as RGBA, downloading and caching on first use."""
    os.makedirs(_COLOR_LOGO_DIR, exist_ok=True)
    path = os.path.join(_COLOR_LOGO_DIR, f'{abbr}.png')
    if not os.path.exists(path):
        url = ESPN_LOGO_URL_NORMAL.format(abbr=_espn_abbr(abbr))
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read()
            with open(path, 'wb') as f:
                f.write(data)
            print(f'Downloaded colour logo: {abbr}')
        except Exception as e:
            print(f'Could not download colour logo for {abbr}: {e}')
            return None
    try:
        img = Image.open(path).convert('RGBA')
        bbox = img.split()[3].getbbox()
        return img.crop(bbox) if bbox else img
    except Exception:
        return None


def _nice_bounds(values, pad_frac, candidates):
    """(lo, hi, step) covering values with padding, snapped to a round step."""
    lo, hi = min(values), max(values)
    pad = (hi - lo) * pad_frac or 1.0
    lo, hi = lo - pad, hi + pad
    step = next((c for c in candidates if (hi - lo) / c <= 9), candidates[-1])
    lo = step * (int(lo / step) - (1 if lo % step else 0))
    hi = step * (int(hi / step) + (1 if hi % step else 0))
    return lo, hi, step


def _ticks(lo, hi, step):
    """Tick values from lo to hi inclusive."""
    return [lo + i * step for i in range(int(round((hi - lo) / step)) + 1)]


def _fmt(value, step):
    """Integer ticks when the step is whole, else one decimal."""
    return str(int(round(value))) if abs(step - round(step)) < 1e-9 else f'{value:.1f}'


def _relax(points, plot):
    """Push overlapping logo centres apart, keeping them inside the plot."""
    left, top, right, bottom = plot
    coords = [[x, y] for x, y in points]
    sep = _MIN_SEP * _SS
    for _ in range(_RELAX_PASSES):
        moved = False
        for i in range(len(coords)):
            for j in range(i + 1, len(coords)):
                dx = coords[j][0] - coords[i][0]
                dy = coords[j][1] - coords[i][1]
                dist = (dx * dx + dy * dy) ** 0.5
                if dist >= sep:
                    continue
                if dist < 1e-6:
                    dx, dy, dist = (1.0 if i % 2 else -1.0), 1.0, 1.0
                push = (sep - dist) / 2.0
                ux, uy = dx / dist, dy / dist
                coords[i][0] -= ux * push
                coords[i][1] -= uy * push
                coords[j][0] += ux * push
                coords[j][1] += uy * push
                moved = True
        radius = _LOGO_PX * _SS / 2
        for c in coords:
            c[0] = min(max(c[0], left + radius), right - radius)
            c[1] = min(max(c[1], top + radius), bottom - radius)
        if not moved:
            break
    return coords


def _dashed(draw, start, end, color, dash=10, gap=8, width=2):
    """Dashed straight line (horizontal or vertical only)."""
    x0, y0 = start
    x1, y1 = end
    if y0 == y1:
        x = x0
        while x < x1:
            draw.line([(x, y0), (min(x + dash * _SS, x1), y0)], fill=color, width=width * _SS)
            x += (dash + gap) * _SS
    else:
        y = y0
        while y < y1:
            draw.line([(x0, y), (x0, min(y + dash * _SS, y1))], fill=color, width=width * _SS)
            y += (dash + gap) * _SS


def _arrow(draw, tail, head, color):
    """Grey shaft from the baseline position to the edge of the logo, with a head."""
    x1, y1 = head
    dx, dy = x1 - tail[0], y1 - tail[1]
    dist = (dx * dx + dy * dy) ** 0.5
    if dist < _MIN_ARROW * _SS:
        return
    ux, uy = dx / dist, dy / dist
    dist = min(dist, _MAX_ARROW * _SS)
    x0, y0 = x1 - ux * dist, y1 - uy * dist

    tip_x, tip_y = x1 - ux * (_LOGO_PX * _SS / 2), y1 - uy * (_LOGO_PX * _SS / 2)
    draw.line([(x0, y0), (tip_x, tip_y)], fill=color, width=2 * _SS)
    r = 4 * _SS
    draw.ellipse([x0 - r, y0 - r, x0 + r, y0 + r], fill=color)

    head_len, head_w = 13 * _SS, 6 * _SS
    bx, by = tip_x - ux * head_len, tip_y - uy * head_len
    draw.polygon([(tip_x, tip_y),
                  (bx - uy * head_w, by + ux * head_w),
                  (bx + uy * head_w, by - ux * head_w)], fill=color)


def render_chart(payload, width=_W, height=_H):
    """Render one grain's payload to an RGB PIL image."""
    teams = payload.get('teams') or []
    if not teams:
        raise ValueError('no teams in payload')

    avg = payload.get('avg') or {}
    avg_wrc = avg.get('wrc', 100.0)
    avg_era = avg.get('era', 4.0)

    xs = [t['wrc'] for t in teams] + [t['was_wrc'] for t in teams if t.get('was_wrc') is not None]
    ys = [t['era'] for t in teams] + [t['was_era'] for t in teams if t.get('was_era') is not None]
    x_lo, x_hi, x_step = _nice_bounds(xs + [avg_wrc], 0.05, [2, 5, 10, 20])
    y_lo, y_hi, y_step = _nice_bounds(ys + [avg_era], 0.05, [0.25, 0.5, 1.0, 2.0])

    image = Image.new('RGB', (width * _SS, height * _SS), _BG)
    draw = ImageDraw.Draw(image)

    left, right = _MARGIN_L * _SS, (width - _MARGIN_R) * _SS
    top, bottom = _MARGIN_T * _SS, (height - _MARGIN_B) * _SS

    def px(wrc):
        """Data wRC+ → pixel column."""
        return left + (wrc - x_lo) / (x_hi - x_lo) * (right - left)

    def py(era):
        """Data ERA → pixel row (higher ERA higher on screen)."""
        return bottom - (era - y_lo) / (y_hi - y_lo) * (bottom - top)

    ax, ay = px(avg_wrc), py(avg_era)

    # Quadrant shading, then gridlines over it.
    draw.rectangle([left, top, ax, ay], fill=_QUAD_FILL['tl'])
    draw.rectangle([ax, top, right, ay], fill=_QUAD_FILL['tr'])
    draw.rectangle([left, ay, ax, bottom], fill=_QUAD_FILL['bl'])
    draw.rectangle([ax, ay, right, bottom], fill=_QUAD_FILL['br'])

    for value in _ticks(x_lo, x_hi, x_step):
        draw.line([(px(value), top), (px(value), bottom)], fill=_GRID, width=_SS)
    for value in _ticks(y_lo, y_hi, y_step):
        draw.line([(left, py(value)), (right, py(value))], fill=_GRID, width=_SS)

    _dashed(draw, (ax, top), (ax, bottom), _DASH)
    _dashed(draw, (left, ay), (right, ay), _DASH)
    draw.rectangle([left, top, right, bottom], outline=_FRAME, width=_SS)

    _draw_labels(image, draw, payload, (left, top, right, bottom), (ax, ay),
                 (x_lo, x_hi, x_step, y_lo, y_hi, y_step), px, py)

    placed = _relax([(px(t['wrc']), py(t['era'])) for t in teams],
                    (left, top, right, bottom))

    for team, center in zip(teams, placed):
        if team.get('was_wrc') is None or team.get('was_era') is None:
            continue
        _arrow(draw, (px(team['was_wrc']), py(team['was_era'])), center, _ARROW)

    logo_px = int(_LOGO_PX * _SS)
    for team, (cx, cy) in zip(teams, placed):
        logo = color_logo(team.get('abbr', ''))
        if logo is None:
            font = _font(13)
            text = team.get('abbr', '')
            bbox = draw.textbbox((0, 0), text, font=font)
            draw.text((cx - bbox[2] / 2, cy - bbox[3] / 2), text, font=font, fill=_INK)
            continue
        logo = logo.copy()
        logo.thumbnail((logo_px, logo_px), Image.LANCZOS)
        image.paste(logo, (int(cx - logo.width / 2), int(cy - logo.height / 2)), logo)

    return image.resize((width, height), Image.LANCZOS)


def _vertical_text(image, text, x, y_center, font, fill):
    """Paste 90°-rotated text, vertically centred on y_center."""
    box = ImageDraw.Draw(image).textbbox((0, 0), text, font=font)
    label = Image.new('RGBA', (box[2] + 4, box[3] + 4), (0, 0, 0, 0))
    ImageDraw.Draw(label).text((2, 2), text, font=font, fill=fill)
    label = label.rotate(90, expand=True)
    image.paste(label, (int(x), int(y_center - label.height / 2)), label)


def _draw_labels(image, draw, payload, plot, avg_px, bounds, px, py):
    """Header, axis ticks, axis titles and the four corner captions."""
    left, top, right, bottom = plot
    ax, ay = avg_px
    x_lo, x_hi, x_step, y_lo, y_hi, y_step = bounds

    f_tick = _font(15)
    f_axis = _font(17)
    f_corner = _font(18)
    f_head = _font(26)
    f_sub = _font(19)

    baseline = (payload.get('baseline') or {}).get('label', '')
    current = (payload.get('current') or {}).get('label', '')
    draw.text((left, 30 * _SS), baseline, font=f_sub, fill=(163, 172, 184))
    offset = draw.textbbox((0, 0), baseline, font=f_sub)[2] + 24 * _SS
    draw.line([(left + offset, 44 * _SS), (left + offset + 34 * _SS, 44 * _SS)],
              fill=_INK, width=2 * _SS)
    draw.polygon([(left + offset + 42 * _SS, 44 * _SS),
                  (left + offset + 30 * _SS, 38 * _SS),
                  (left + offset + 30 * _SS, 50 * _SS)], fill=_INK)
    draw.text((left + offset + 56 * _SS, 26 * _SS), current, font=f_head, fill=_INK)

    grain = payload.get('label', '')
    draw.text((right - draw.textbbox((0, 0), grain, font=f_sub)[2], 30 * _SS),
              grain, font=f_sub, fill=(163, 172, 184))

    for value in _ticks(x_lo, x_hi, x_step):
        text = _fmt(value, x_step)
        w = draw.textbbox((0, 0), text, font=f_tick)[2]
        draw.text((px(value) - w / 2, bottom + 14 * _SS), text, font=f_tick, fill=_AXIS)
    for value in _ticks(y_lo, y_hi, y_step):
        text = _fmt(value, y_step)
        box = draw.textbbox((0, 0), text, font=f_tick)
        draw.text((left - 16 * _SS - box[2], py(value) - box[3] / 2), text,
                  font=f_tick, fill=_AXIS)

    draw.text((ax + 6 * _SS, top + 8 * _SS), 'AVG', font=_font(11), fill=_AXIS)
    draw.text((right - 44 * _SS, ay + 6 * _SS), 'AVG', font=_font(11), fill=_AXIS)

    title = 'wRC+*'
    draw.text(((left + right) / 2 - draw.textbbox((0, 0), title, font=f_axis)[2] / 2,
               bottom + 48 * _SS), title, font=f_axis, fill=_AXIS)
    _vertical_text(image, 'ERA', 18 * _SS, (top + bottom) / 2, f_axis, _AXIS)

    note = 'wRC+* — wOBA-based approximation, no park factors  ·  data: MLB Stats API'
    draw.text((left, bottom + 74 * _SS), note, font=_font(12), fill=(163, 172, 184))

    pad = 16 * _SS
    for key, text, color in _CORNERS:
        box = draw.textbbox((0, 0), text, font=f_corner)
        x = left + pad if key[1] == 'l' else right - pad - box[2]
        y = top + pad if key[0] == 't' else bottom - pad - box[3]
        draw.text((x, y), text, font=f_corner, fill=color)


def main():
    """CLI entry point: render the colour quadrant chart."""
    parser = argparse.ArgumentParser(description='Render the team quadrant chart as a PNG')
    parser.add_argument('--grain', default='month', choices=list(GRAINS) + ['all'],
                        help='Which window to plot (default: month)')
    parser.add_argument('--fetch', action='store_true', help='Refresh the data before rendering')
    parser.add_argument('--out', default=None, help='Output PNG path, or a directory for --grain all')
    parser.add_argument('--size', default=f'{_W}x{_H}', help='Output size, e.g. 1600x900')
    args = parser.parse_args()

    if args.fetch:
        fetch_team_quadrant(force=True)

    data = load_json_file('team_quadrant.json')
    grains = (data or {}).get('grains') or {}
    if not grains:
        print('No data — run with --fetch (or python src/fetch_team_quadrant.py) first')
        return 1

    width, _, height = args.size.partition('x')
    width, height = int(width), int(height)

    targets = list(GRAINS) if args.grain == 'all' else [args.grain]
    out_dir = os.path.join(_REPO_ROOT, 'output')
    if args.out and args.grain == 'all':
        out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)

    for grain in targets:
        payload = grains.get(grain)
        if not payload:
            print(f'No data for grain {grain}, skipping')
            continue
        image = render_chart(payload, width=width, height=height)
        if args.out and args.grain != 'all':
            path = args.out
        else:
            path = os.path.join(out_dir, f'quadrant_{grain}.png')
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        image.save(path)
        print(f'Wrote {path}')
    return 0


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
