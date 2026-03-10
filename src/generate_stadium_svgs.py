#!/usr/bin/env python3
"""generate_stadium_svgs.py — Render clean SVG field diagrams for all 30 MLB stadiums.

Each SVG is optimized for E-Ink display:
  - Black strokes only, white background, no fills, no grays, no gradients
  - Outfield fence, warning track, foul lines, infield diamond, distance labels

Usage:
  python src/generate_stadium_svgs.py --all
  python src/generate_stadium_svgs.py --stadium "Fenway Park"
  python src/generate_stadium_svgs.py --all --outdir my_svgs --json my_data.json
"""

import argparse
import math
import os
import sys

# Ensure stadium_polygons (and transitively field_view) are importable
_SRC = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_SRC)
sys.path.insert(0, _SRC)

from stadium_polygons import (  # noqa: E402
    STADIUM_POLYGONS, TEAM_NAMES, export_json, BALLPARK_DIMENSIONS,
)

# ---------------------------------------------------------------------------
# SVG viewport constants (all in feet → 1 ft = 1 SVG unit)
# ---------------------------------------------------------------------------
# ViewBox: centered on home plate, +Y upward in field coords.
# In SVG Y increases downward, so we flip:  svg_y = VIEW_H - field_y - BOTTOM_PAD
# Home plate sits at (VIEW_W/2, VIEW_H - BOTTOM_PAD) in SVG space.

VIEW_W = 840          # SVG width  in SVG units (≈ ±420 ft either side)
VIEW_H = 480          # SVG height in SVG units
BOTTOM_PAD = 40       # px below home plate for labels / breathing room
ORIGIN_X = VIEW_W // 2  # 420 — SVG x of home plate
ORIGIN_Y = VIEW_H - BOTTOM_PAD  # SVG y of home plate

# Infield geometry (feet)
BASE_DIST = 63.64     # 90 ft / √2  — half-diagonal of 90-ft square
MOUND_DIST = 60.5
INFIELD_ARC_R = 95    # radius of infield grass arc (clears 2B at ~63.6 ft diagonal)

# Base square half-size in SVG units
BASE_HALF = 5

# Warning track setback (ft inside fence)
TRACK_SETBACK = 15


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def ft_to_svg(x_ft, y_ft):
    """Convert field (x, y) in feet to SVG pixel coords."""
    return ORIGIN_X + x_ft, ORIGIN_Y - y_ft


def polar_to_field(dist_ft, angle_deg):
    """(dist, angle_deg) → (x_ft, y_ft) in field coords."""
    rad = math.radians(angle_deg)
    return dist_ft * math.sin(rad), dist_ft * math.cos(rad)


def pts_to_polyline(points_ft):
    """List of (x_ft, y_ft) → SVG points= attribute string."""
    return ' '.join(f'{ORIGIN_X + x:.1f},{ORIGIN_Y - y:.1f}' for x, y in points_ft)


def arc_path(cx_ft, cy_ft, r, start_deg, end_deg, steps=64):
    """Return SVG <path d=...> for a circular arc in field coordinates.

    start_deg / end_deg are in standard math convention (0=right, CCW positive).
    Both refer to field-space angles, not SVG angles.
    """
    # Convert field origin to SVG
    cx, cy = ft_to_svg(cx_ft, cy_ft)
    # Build arc as polyline for simplicity
    pts = []
    for i in range(steps + 1):
        t = start_deg + (end_deg - start_deg) * i / steps
        rad = math.radians(t)
        sx = cx + r * math.cos(rad)
        sy = cy - r * math.sin(rad)   # flip Y
        pts.append(f'{sx:.1f},{sy:.1f}')
    return ' '.join(pts)


# ---------------------------------------------------------------------------
# Element builders (return SVG element strings)
# ---------------------------------------------------------------------------

def _rect_bg():
    return f'<rect x="0" y="0" width="{VIEW_W}" height="{VIEW_H}" fill="white"/>'


def _foul_lines(lf_pt, rf_pt):
    """Two thin lines from home plate to foul poles."""
    hx, hy = ft_to_svg(0, 0)
    lx, ly = ft_to_svg(*lf_pt)
    rx, ry = ft_to_svg(*rf_pt)
    return (
        f'<line x1="{hx:.1f}" y1="{hy:.1f}" x2="{lx:.1f}" y2="{ly:.1f}" '
        f'stroke="black" stroke-width="1"/>'
        f'<line x1="{hx:.1f}" y1="{hy:.1f}" x2="{rx:.1f}" y2="{ry:.1f}" '
        f'stroke="black" stroke-width="1"/>'
    )


def _fence_polyline(polygon_ft):
    """Bold polyline tracing the outfield fence."""
    pts = pts_to_polyline(polygon_ft)
    return (
        f'<polyline points="{pts}" '
        f'fill="none" stroke="black" stroke-width="2.5" stroke-linejoin="round"/>'
    )


def _warning_track(dims):
    """Dotted polyline 15 ft inside the fence."""
    track = []
    for dist, angle in dims:
        inner = max(dist - TRACK_SETBACK, 50)
        track.append(polar_to_field(inner, angle))
    pts = pts_to_polyline(track)
    return (
        f'<polyline points="{pts}" '
        f'fill="none" stroke="black" stroke-width="1" '
        f'stroke-dasharray="4 4"/>'
    )


def _infield_arc():
    """Arc of infield grass from LF side to RF side, passing through CF."""
    # In SVG coords: home plate center, radius = INFIELD_ARC_R
    # The arc spans from ~225° to ~315° in screen math (measuring from +x axis CCW)
    # which corresponds to the portion facing CF (upward in field space).
    # We'll use a polyline approximation for compatibility.
    cx, cy = ft_to_svg(0, 0)
    pts = []
    # SVG: 0° = right, 90° = up (because we flip Y).
    # We want the arc that faces CF (upward), from SW to SE quadrant
    # In SVG-flipped space: from 225° to 315° (measuring standard math angle with flipped Y)
    for i in range(65):
        t = 225 + 90 * i / 64
        rad = math.radians(t)
        sx = cx + INFIELD_ARC_R * math.cos(rad)
        sy = cy - INFIELD_ARC_R * math.sin(rad)
        pts.append(f'{sx:.1f},{sy:.1f}')
    pts_str = ' '.join(pts)
    return (
        f'<polyline points="{pts_str}" '
        f'fill="none" stroke="black" stroke-width="1"/>'
    )


def _bases():
    """Four bases as small rotated squares (diamonds)."""
    # Base positions in field feet (90 ft square, rotated 45°)
    positions = [
        (BASE_DIST,  BASE_DIST),   # 1B
        (0,          2 * BASE_DIST), # 2B
        (-BASE_DIST, BASE_DIST),   # 3B
        (0,          0),           # home plate
    ]
    elems = []
    h = BASE_HALF
    for fx, fy in positions:
        sx, sy = ft_to_svg(fx, fy)
        if fx == 0 and fy == 0:
            # Home plate: small pentagon shape
            pts = (
                f'{sx},{sy + h} '
                f'{sx - h},{sy} '
                f'{sx - h + 2},{sy - h} '
                f'{sx + h - 2},{sy - h} '
                f'{sx + h},{sy}'
            )
            elems.append(
                f'<polygon points="{pts}" fill="none" stroke="black" stroke-width="1.5"/>'
            )
        else:
            pts = f'{sx},{sy - h} {sx + h},{sy} {sx},{sy + h} {sx - h},{sy}'
            elems.append(
                f'<polygon points="{pts}" fill="none" stroke="black" stroke-width="1.5"/>'
            )
    return '\n'.join(elems)


def _mound():
    """Pitcher's mound as small circle."""
    mx, my = ft_to_svg(0, MOUND_DIST)
    return (
        f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="6" '
        f'fill="none" stroke="black" stroke-width="1"/>'
    )


def _base_paths():
    """Thin lines connecting the 4 bases."""
    corners = [
        (BASE_DIST,  BASE_DIST),
        (0,          2 * BASE_DIST),
        (-BASE_DIST, BASE_DIST),
        (0,          0),
    ]
    pts = ' '.join(f'{ORIGIN_X + x:.1f},{ORIGIN_Y - y:.1f}' for x, y in corners)
    # Close the diamond back to home
    return (
        f'<polygon points="{pts}" '
        f'fill="none" stroke="black" stroke-width="1.5"/>'
    )


def _distance_labels(dims, polygon_ft, font_size=13):
    """Distance labels at LF pole, RF pole, deepest CF, and 2 intermediate points."""
    elems = []
    n = len(dims)

    # Always label: LF pole (index 0), RF pole (index -1)
    # Deepest = point with greatest y value
    deepest_idx = max(range(n), key=lambda i: polygon_ft[i][1])

    label_indices = {0, n - 1, deepest_idx}

    # Add 2 intermediate points (leftmost non-pole angle, rightmost non-pole angle)
    if n >= 8:
        inner = [i for i in range(1, n - 1) if i != deepest_idx]
        if inner:
            lf_mid = min(inner, key=lambda i: dims[i][1])
            rf_mid = max(inner, key=lambda i: dims[i][1])
            label_indices.add(lf_mid)
            label_indices.add(rf_mid)

    for i in label_indices:
        dist = int(dims[i][0])
        fx, fy = polygon_ft[i]
        sx, sy = ft_to_svg(fx, fy)

        # Nudge labels away from wall
        angle = dims[i][1]
        if angle < -10:       # LF side: nudge right + up
            tx, ty = sx + 4, sy - 4
            anchor = 'start'
        elif angle > 10:      # RF side: nudge left + up
            tx, ty = sx - 4, sy - 4
            anchor = 'end'
        else:                 # CF: center above
            tx, ty = sx, sy - 6
            anchor = 'middle'

        elems.append(
            f'<text x="{tx:.1f}" y="{ty:.1f}" '
            f'font-family="Arial,Helvetica,sans-serif" font-size="{font_size}" '
            f'text-anchor="{anchor}" fill="black">{dist}</text>'
        )

    return '\n'.join(elems)


def _title(stadium, team, font_size=15):
    """Stadium name + team centered at top."""
    cx = VIEW_W / 2
    return (
        f'<text x="{cx}" y="22" '
        f'font-family="Arial,Helvetica,sans-serif" font-size="{font_size}" '
        f'font-weight="bold" text-anchor="middle" fill="black">{stadium}</text>'
        f'<text x="{cx}" y="38" '
        f'font-family="Arial,Helvetica,sans-serif" font-size="{font_size - 2}" '
        f'text-anchor="middle" fill="black">{team}</text>'
    )


# ---------------------------------------------------------------------------
# Main SVG builder
# ---------------------------------------------------------------------------

def make_svg(stadium_name, dims):
    """Return full SVG string for one stadium."""
    polygon_ft = [(x, y) for x, y in STADIUM_POLYGONS[stadium_name]]
    team = TEAM_NAMES.get(stadium_name, '')

    lf_pt = polygon_ft[0]
    rf_pt = polygon_ft[-1]

    elements = [
        _rect_bg(),
        _foul_lines(lf_pt, rf_pt),
        _warning_track(dims),
        _fence_polyline(polygon_ft),
        _infield_arc(),
        _base_paths(),
        _bases(),
        _mound(),
        _distance_labels(dims, polygon_ft),
        _title(stadium_name, team),
    ]

    body = '\n'.join(elements)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{VIEW_W}" height="{VIEW_H}" '
        f'viewBox="0 0 {VIEW_W} {VIEW_H}">\n'
        f'{body}\n'
        f'</svg>\n'
    )


# ---------------------------------------------------------------------------
# File name slug
# ---------------------------------------------------------------------------

def slugify(name):
    return (
        name.lower()
        .replace(' ', '_')
        .replace("'", '')
        .replace('/', '_')
        .replace('.', '')
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Generate E-Ink-optimized SVG diagrams for MLB stadiums.')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--all', action='store_true', default=True,
                       help='Render all 30 stadiums (default)')
    group.add_argument('--stadium', type=str, metavar='NAME',
                       help='Render a single stadium by name')
    parser.add_argument('--outdir', default='data/stadium_svgs',
                        help='Directory for SVG output files')
    parser.add_argument('--json', default='data/stadium_polygons.json',
                        help='Path for the polygon JSON export')
    args = parser.parse_args()

    # Resolve paths relative to project root
    outdir = os.path.join(_ROOT, args.outdir)
    json_path = os.path.join(_ROOT, args.json)

    os.makedirs(outdir, exist_ok=True)

    # Determine which stadiums to render
    if args.stadium:
        # Single stadium — try exact then fuzzy match
        targets = {}
        if args.stadium in BALLPARK_DIMENSIONS:
            targets[args.stadium] = BALLPARK_DIMENSIONS[args.stadium]
        else:
            low = args.stadium.lower()
            for k, v in BALLPARK_DIMENSIONS.items():
                if low in k.lower() or k.lower() in low:
                    targets[k] = v
                    break
        if not targets:
            print(f'ERROR: Stadium "{args.stadium}" not found.', file=sys.stderr)
            print('Available stadiums:')
            for k in BALLPARK_DIMENSIONS:
                print(f'  {k}')
            sys.exit(1)
    else:
        targets = dict(BALLPARK_DIMENSIONS)

    # Render SVGs
    for name, dims in targets.items():
        svg = make_svg(name, dims)
        filename = slugify(name) + '.svg'
        path = os.path.join(outdir, filename)
        with open(path, 'w') as fh:
            fh.write(svg)
        print(f'  {name:35s} → {os.path.relpath(path, _ROOT)}')

    print(f'\nGenerated {len(targets)} SVG(s) in {os.path.relpath(outdir, _ROOT)}/')

    # Always export JSON
    export_json(json_path)
    print(f'Polygon JSON → {os.path.relpath(json_path, _ROOT)}')


if __name__ == '__main__':
    main()
