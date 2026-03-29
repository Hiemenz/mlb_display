#!/usr/bin/env python3
"""fetch_stadium_polygons.py — Fetch and parse Baseball Savant park SVGs.

NOTE: The Baseball Savant park SVG endpoint is not publicly accessible (returns
404). This script is kept as a utility for future use if SVG access becomes
available. The primary data source for stadium wall polygons is now the
MLB Stats API fieldInfo endpoint combined with known wall topology research,
stored directly in stadium_polygons.py.

If the Savant SVG URL changes in the future, update SVG_URL and test with:
    python3 src/fetch_stadium_polygons.py --probe 3

Outputs Cartesian (x_ft, y_ft) wall polygons for all 30 MLB stadiums.
The result is printed as Python-literal dict entries that can be pasted
directly into the STADIUM_POLYGONS dict in stadium_polygons.py.

Usage:
    python3 src/fetch_stadium_polygons.py               # all stadiums
    python3 src/fetch_stadium_polygons.py Fenway        # single park (fuzzy match)
    python3 src/fetch_stadium_polygons.py --probe 3     # dump raw SVG paths for venueId=3

Coordinate system (output):
    Home plate = (0, 0) in feet
    +x = RF / 1B side,  -x = LF / 3B side,  +y = toward CF

Baseball Savant SVG coordinate system (input, when available):
    Home plate ≈ (125.42, 204.5) in SVG units.
    1 SVG unit ≈ 1 foot.  Y increases downward (SVG convention).
    Transform: x_ft = svg_x - 125.42,  y_ft = 204.5 - svg_y
"""

import json
import math
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from urllib.error import URLError, HTTPError

# ---------------------------------------------------------------------------
# Venue ID map (MLB Stats API venueId for all active 2024/2025 parks)
# ---------------------------------------------------------------------------
VENUE_IDS = {
    # AL East
    'Yankee Stadium':             3313,
    'Fenway Park':                3,
    'Camden Yards':               2,
    'Rogers Centre':              14,
    'Tropicana Field':            12,
    # AL Central
    'Guaranteed Rate Field':      4,
    'Progressive Field':          5,
    'Comerica Park':              2394,
    'Kauffman Stadium':           7,
    'Target Field':               3312,
    # AL West
    'Minute Maid Park':           2392,
    'Angel Stadium':              1,
    'T-Mobile Park':              680,
    'Globe Life Field':           5325,
    'Sutter Health Park':         2529,  # A's in Sacramento 2025
    # NL East
    'Truist Park':                4705,
    'Citi Field':                 3289,
    'Citizens Bank Park':         2681,
    'Nationals Park':             3309,
    'loanDepot park':             4169,
    # NL Central
    'Wrigley Field':              17,
    'Great American Ball Park':   2602,
    'American Family Field':      32,
    'PNC Park':                   31,
    'Busch Stadium':              2889,
    # NL West
    'Dodger Stadium':             22,
    'Chase Field':                15,
    'Coors Field':                16,
    'Oracle Park':                2395,
    'Petco Park':                 2680,
}

# URL template for Baseball Savant park SVGs
SVG_URL = 'https://baseballsavant.mlb.com/assets/img/gameday/park-SVGs/{venue_id}.svg'

# Home plate anchor in SVG coordinate space (SVG units ≈ feet)
HOME_PLATE_SVG_X = 125.42
HOME_PLATE_SVG_Y = 204.5

# Cache directory for raw SVG files (avoid re-fetching)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(_ROOT, 'data', 'savant_svgs')

# SVG namespaces used by Baseball Savant
_NS = {'svg': 'http://www.w3.org/2000/svg'}


# ---------------------------------------------------------------------------
# Fetch and cache
# ---------------------------------------------------------------------------

def fetch_svg(venue_id, force_refresh=False):
    """Return raw SVG bytes for *venue_id*, using disk cache when available."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, f'{venue_id}.svg')

    if not force_refresh and os.path.exists(cache_path):
        with open(cache_path, 'rb') as fh:
            return fh.read()

    url = SVG_URL.format(venue_id=venue_id)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'mlb-display/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
    except HTTPError as e:
        print(f'    HTTP {e.code} for venueId={venue_id}', file=sys.stderr)
        return None
    except URLError as e:
        print(f'    URL error for venueId={venue_id}: {e.reason}', file=sys.stderr)
        return None

    with open(cache_path, 'wb') as fh:
        fh.write(data)
    return data


# ---------------------------------------------------------------------------
# SVG path parsing
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r'([MmLlHhVvCcSsQqTtAaZz])|([+-]?[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)')


def _parse_path_d(d):
    """Parse an SVG path `d` attribute into a flat list of (cmd, [args]) tuples.

    Only M, L, H, V, C, S, Q, T, Z are handled (no A arcs — none in MLB SVGs).
    Returns a list of absolute (x, y) coordinate pairs representing the path.
    """
    tokens = _TOKEN_RE.findall(d)
    # tokens is list of (cmd_or_empty, num_or_empty)
    items = []
    for cmd_tok, num_tok in tokens:
        if cmd_tok:
            items.append(('CMD', cmd_tok))
        elif num_tok:
            items.append(('NUM', float(num_tok)))

    points = []
    cmd = 'M'
    cx, cy = 0.0, 0.0  # current position
    nums = []
    i = 0

    def consume_nums(count):
        nonlocal i
        result = []
        while len(result) < count and i < len(items):
            if items[i][0] == 'NUM':
                result.append(items[i][1])
                i += 1
            else:
                break
        return result

    while i < len(items):
        t, v = items[i]
        if t == 'CMD':
            cmd = v
            i += 1
            continue

        # Consume coordinates for current command
        if cmd in ('M', 'm'):
            xy = consume_nums(2)
            if len(xy) < 2:
                break
            if cmd == 'm':
                cx, cy = cx + xy[0], cy + xy[1]
            else:
                cx, cy = xy[0], xy[1]
            points.append((cx, cy))
            # Subsequent pairs treated as implicit lineto
            cmd = 'l' if cmd == 'm' else 'L'

        elif cmd in ('L', 'l'):
            xy = consume_nums(2)
            if len(xy) < 2:
                break
            if cmd == 'l':
                cx, cy = cx + xy[0], cy + xy[1]
            else:
                cx, cy = xy[0], xy[1]
            points.append((cx, cy))

        elif cmd in ('H', 'h'):
            n = consume_nums(1)
            if not n:
                break
            cx = (cx + n[0]) if cmd == 'h' else n[0]
            points.append((cx, cy))

        elif cmd in ('V', 'v'):
            n = consume_nums(1)
            if not n:
                break
            cy = (cy + n[0]) if cmd == 'v' else n[0]
            points.append((cx, cy))

        elif cmd in ('C', 'c'):
            # Cubic bezier — 6 params, take endpoint + 2 intermediate samples
            xy6 = consume_nums(6)
            if len(xy6) < 6:
                break
            if cmd == 'c':
                p1x, p1y = cx + xy6[0], cy + xy6[1]
                p2x, p2y = cx + xy6[2], cy + xy6[3]
                ex, ey   = cx + xy6[4], cy + xy6[5]
            else:
                p1x, p1y = xy6[0], xy6[1]
                p2x, p2y = xy6[2], xy6[3]
                ex, ey   = xy6[4], xy6[5]
            # Sample bezier at t=0.33 and t=0.67 to preserve curve shape
            for t in (0.33, 0.67):
                mt = 1 - t
                bx = mt**3*cx + 3*mt**2*t*p1x + 3*mt*t**2*p2x + t**3*ex
                by = mt**3*cy + 3*mt**2*t*p1y + 3*mt*t**2*p2y + t**3*ey
                points.append((bx, by))
            points.append((ex, ey))
            cx, cy = ex, ey

        elif cmd in ('S', 's'):
            # Smooth cubic bezier — 4 params
            xy4 = consume_nums(4)
            if len(xy4) < 4:
                break
            if cmd == 's':
                p2x, p2y = cx + xy4[0], cy + xy4[1]
                ex, ey   = cx + xy4[2], cy + xy4[3]
            else:
                p2x, p2y = xy4[0], xy4[1]
                ex, ey   = xy4[2], xy4[3]
            # Reflection of previous control point — use p2 only (approximation)
            for t in (0.33, 0.67):
                mt = 1 - t
                bx = mt**2*cx + 2*mt*t*p2x + t**2*ex
                by = mt**2*cy + 2*mt*t*p2y + t**2*ey
                points.append((bx, by))
            points.append((ex, ey))
            cx, cy = ex, ey

        elif cmd in ('Q', 'q'):
            # Quadratic bezier — 4 params
            xy4 = consume_nums(4)
            if len(xy4) < 4:
                break
            if cmd == 'q':
                p1x, p1y = cx + xy4[0], cy + xy4[1]
                ex, ey   = cx + xy4[2], cy + xy4[3]
            else:
                p1x, p1y = xy4[0], xy4[1]
                ex, ey   = xy4[2], xy4[3]
            for t in (0.33, 0.67):
                mt = 1 - t
                bx = mt**2*cx + 2*mt*t*p1x + t**2*ex
                by = mt**2*cy + 2*mt*t*p1y + t**2*ey
                points.append((bx, by))
            points.append((ex, ey))
            cx, cy = ex, ey

        elif cmd in ('T', 't'):
            xy = consume_nums(2)
            if len(xy) < 2:
                break
            if cmd == 't':
                cx, cy = cx + xy[0], cy + xy[1]
            else:
                cx, cy = xy[0], xy[1]
            points.append((cx, cy))

        elif cmd in ('Z', 'z'):
            # Close path — stop collecting
            break

        else:
            # Unknown command — skip
            i += 1

    return points


# ---------------------------------------------------------------------------
# Coordinate transform: SVG → field feet
# ---------------------------------------------------------------------------

def svg_to_field(svg_x, svg_y):
    """Transform a Baseball Savant SVG point to field-foot coordinates.

    Baseball Savant SVG space:
        - home plate ≈ (125.42, 204.5)
        - Y increases downward
        - units are approximately feet

    Field space (this project):
        - home plate = (0, 0)
        - +x = RF (1B side), -x = LF (3B side)
        - +y = toward CF
    """
    x_ft = svg_x - HOME_PLATE_SVG_X
    y_ft = HOME_PLATE_SVG_Y - svg_y   # flip Y
    return x_ft, y_ft


# ---------------------------------------------------------------------------
# Path bounding-box area helper
# ---------------------------------------------------------------------------

def _bbox_area(points):
    """Return bounding box area of a list of (x,y) SVG points."""
    if not points:
        return 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


# ---------------------------------------------------------------------------
# Wall path extraction
# ---------------------------------------------------------------------------

# IDs / CSS classes that typically identify the outfield wall in Savant SVGs
_WALL_IDS = {'outfield_outer', 'fence', 'wall', 'of-fence', 'outfield-fence', 'fence_outer'}
_WALL_CLASSES = {'outfield_outer', 'fence', 'wall'}


def _extract_paths(svg_bytes):
    """Return list of (id_attr, class_attr, raw_d) for every <path> element in the SVG."""
    try:
        root = ET.fromstring(svg_bytes)
    except ET.ParseError as e:
        print(f'  SVG parse error: {e}', file=sys.stderr)
        return []

    paths = []
    # Walk the entire tree (handles nested groups)
    for el in root.iter():
        tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
        if tag == 'path':
            d = el.get('d', '')
            if d:
                paths.append({
                    'id':    el.get('id', ''),
                    'class': el.get('class', ''),
                    'd':     d,
                })
    return paths


def find_wall_path(svg_bytes, probe=False):
    """Return the outfield wall path `d` string from raw SVG bytes.

    Strategy:
      1. Look for a <path> whose id or class matches known wall identifiers.
      2. Fall back to the <path> with the largest bounding-box area.

    Returns (d_string, id_used) or (None, None) on failure.
    """
    paths = _extract_paths(svg_bytes)
    if not paths:
        return None, None

    if probe:
        print(f'\n  Found {len(paths)} path elements:')
        for p in paths:
            pts = _parse_path_d(p['d'])
            area = _bbox_area(pts)
            print(f"    id={p['id']!r:30s}  class={p['class']!r:20s}  pts={len(pts):4d}  bbox_area={area:.0f}")
        print()

    # Priority 1: id match
    for p in paths:
        if p['id'].lower() in _WALL_IDS:
            return p['d'], f"id={p['id']!r}"

    # Priority 2: class match
    for p in paths:
        cls = set(p['class'].lower().split())
        if cls & _WALL_CLASSES:
            return p['d'], f"class={p['class']!r}"

    # Fallback: largest bounding box area
    best = max(paths, key=lambda p: _bbox_area(_parse_path_d(p['d'])))
    return best['d'], f"id={best['id']!r} (fallback: largest bbox)"


# ---------------------------------------------------------------------------
# Douglas-Peucker simplification
# ---------------------------------------------------------------------------

def _perp_dist(pt, line_start, line_end):
    """Perpendicular distance from *pt* to the line through *line_start*→*line_end*."""
    x0, y0 = pt
    x1, y1 = line_start
    x2, y2 = line_end
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return math.hypot(x0 - x1, y0 - y1)
    return abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / math.hypot(dx, dy)


def rdp_simplify(points, epsilon=2.0):
    """Ramer-Douglas-Peucker polyline simplification with tolerance *epsilon* feet."""
    if len(points) <= 2:
        return list(points)
    # Find point with max distance from start-end line
    max_dist = 0.0
    max_idx = 0
    for i in range(1, len(points) - 1):
        d = _perp_dist(points[i], points[0], points[-1])
        if d > max_dist:
            max_dist = d
            max_idx = i
    if max_dist > epsilon:
        left  = rdp_simplify(points[:max_idx + 1], epsilon)
        right = rdp_simplify(points[max_idx:], epsilon)
        return left[:-1] + right
    return [points[0], points[-1]]


# ---------------------------------------------------------------------------
# Trim polygon to outfield arc (drop points behind home plate)
# ---------------------------------------------------------------------------

def trim_to_outfield(field_pts):
    """Keep only points with y_ft > -10 (i.e., at or past home plate level)."""
    return [(x, y) for x, y in field_pts if y > -10.0]


def sort_lf_to_rf(field_pts):
    """Sort points left (most-negative x) to right (most-positive x)."""
    return sorted(field_pts, key=lambda p: p[0])


# ---------------------------------------------------------------------------
# Main extraction pipeline
# ---------------------------------------------------------------------------

def extract_wall_polygon(svg_bytes, probe=False, epsilon=2.0):
    """Full pipeline: SVG bytes → simplified [(x_ft, y_ft)] wall polygon.

    Returns (points, method_note) or (None, error_message).
    """
    d, method = find_wall_path(svg_bytes, probe=probe)
    if d is None:
        return None, 'no path found'

    # Parse SVG path to raw SVG coordinate list
    raw_svg_pts = _parse_path_d(d)
    if not raw_svg_pts:
        return None, 'path parsed to 0 points'

    # Transform to field feet
    field_pts = [svg_to_field(x, y) for x, y in raw_svg_pts]

    # Filter to outfield arc
    field_pts = trim_to_outfield(field_pts)
    if not field_pts:
        return None, 'no points in outfield region'

    # Sort LF → RF
    field_pts = sort_lf_to_rf(field_pts)

    # Simplify
    simplified = rdp_simplify(field_pts, epsilon=epsilon)

    return simplified, method


# ---------------------------------------------------------------------------
# Probe a single venue to inspect SVG structure
# ---------------------------------------------------------------------------

def probe_venue(venue_id):
    """Fetch and dump all path elements for *venue_id* for manual inspection."""
    print(f'\nProbing venueId={venue_id}...')
    data = fetch_svg(venue_id)
    if data is None:
        print('  Failed to fetch SVG')
        return
    d, method = find_wall_path(data, probe=True)
    if d is None:
        return
    print(f'  Selected path via: {method}')
    pts = _parse_path_d(d)
    print(f'  Raw points: {len(pts)}')
    field_pts = [svg_to_field(x, y) for x, y in pts]
    field_pts = trim_to_outfield(field_pts)
    field_pts = sort_lf_to_rf(field_pts)
    simplified = rdp_simplify(field_pts, epsilon=2.0)
    print(f'  Simplified points ({len(simplified)}):')
    for x, y in simplified:
        dist = math.sqrt(x**2 + y**2)
        print(f'    ({x:7.1f}, {y:7.1f})  dist={dist:.0f} ft')


# ---------------------------------------------------------------------------
# Process all venues
# ---------------------------------------------------------------------------

def process_all(name_filter=None, epsilon=2.0, force_refresh=False):
    """Fetch and parse all venues, returning dict of name → [(x_ft, y_ft)]."""
    results = {}
    seen_ids = {}  # venue_id → first name, to avoid duplicate fetches

    for name, vid in VENUE_IDS.items():
        if name_filter and name_filter.lower() not in name.lower():
            continue
        if vid is None:
            print(f'  {name}: SKIP (no venueId)')
            continue
        if vid in seen_ids:
            print(f'  {name}: SKIP (same venueId={vid} as {seen_ids[vid]})')
            continue
        seen_ids[vid] = name

        print(f'  {name} (venueId={vid})...', end=' ', flush=True)
        data = fetch_svg(vid, force_refresh=force_refresh)
        if data is None:
            print('FAILED')
            continue

        pts, method = extract_wall_polygon(data, epsilon=epsilon)
        if pts is None:
            print(f'ERROR: {method}')
            continue

        # Validate: should have at least 5 points and wall points should be >200 ft from home
        dists = [math.sqrt(x**2 + y**2) for x, y in pts]
        if len(pts) < 5 or max(dists) < 200:
            print(f'WARNING: suspicious result ({len(pts)} pts, max dist={max(dists):.0f} ft)')

        results[name] = pts
        print(f'{len(pts)} pts  [{method}]')
        time.sleep(0.1)  # polite rate limiting

    return results


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_python_literal(results):
    """Return a Python dict literal string suitable for pasting into stadium_polygons.py."""
    lines = ['STADIUM_POLYGONS = {']
    for name, pts in results.items():
        pts_str = ', '.join(f'({x:.1f}, {y:.1f})' for x, y in pts)
        lines.append(f"    {name!r}: [{pts_str}],")
    lines.append('}')
    return '\n'.join(lines)


def save_json(results, path):
    """Save results as JSON array (same schema as stadium_polygons.export_json)."""
    from stadium_polygons import TEAM_NAMES
    records = [
        {
            'stadium': name,
            'team': TEAM_NAMES.get(name, ''),
            'wall_polygon': [[round(x, 1), round(y, 1)] for x, y in pts],
        }
        for name, pts in results.items()
    ]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        json.dump(records, fh, indent=2)
    return path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Fetch Baseball Savant park SVGs and extract outfield wall polygons.')
    parser.add_argument('stadium', nargs='?', default=None,
                        help='Stadium name filter (fuzzy match). Omit for all 30.')
    parser.add_argument('--probe', metavar='VENUE_ID', type=int, default=None,
                        help='Dump all SVG path elements for a venue ID (debug mode)')
    parser.add_argument('--epsilon', type=float, default=2.0,
                        help='RDP simplification tolerance in feet (default: 2.0)')
    parser.add_argument('--refresh', action='store_true',
                        help='Force re-fetch (ignore disk cache)')
    parser.add_argument('--json', default=None,
                        help='Also save results to JSON file')
    args = parser.parse_args()

    # Add src dir to path so we can import stadium_polygons for TEAM_NAMES
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    if args.probe is not None:
        probe_venue(args.probe)
        sys.exit(0)

    print('Fetching park SVGs from Baseball Savant...')
    results = process_all(
        name_filter=args.stadium,
        epsilon=args.epsilon,
        force_refresh=args.refresh,
    )

    if not results:
        print('No results.', file=sys.stderr)
        sys.exit(1)

    print(f'\n--- Python literal (paste into stadium_polygons.py) ---\n')
    print(format_python_literal(results))

    if args.json:
        path = save_json(results, args.json)
        print(f'\nSaved JSON → {path}')
