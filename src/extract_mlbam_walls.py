#!/usr/bin/env python3
"""extract_mlbam_walls.py — Extract outfield wall shapes from MLBAM stadium data.

Reads the MLBStadiumsPathData dataset (from the GeomMLBStadiums R package)
and outputs detailed wall polygons for all 30 MLB stadiums.

Data source: https://github.com/bdilday/GeomMLBStadiums
The dataset contains MLBAM's canonical wall shapes used on Baseball Savant
spray charts, with 100 `outfield_outer` coordinate points per stadium.

Coordinate transform (MLBAM hc_x/hc_y → field feet):
    x_ft = 2.495671 * (hc_x - 125.0)
    y_ft = 2.495671 * (199.0 - hc_y)
    Home plate at (0, 0), +x = RF, +y = CF

Usage:
    python3 src/extract_mlbam_walls.py /tmp/MLBStadiaPathData.rda
    python3 src/extract_mlbam_walls.py /tmp/MLBStadiaPathData.rda --epsilon 3.0
"""

import argparse
import json
import math
import os
import sys

import pyreadr

# MLBAM coordinate transform constants
_SCALE = 2.495671
_HC_X_CENTER = 125.0
_HC_Y_CENTER = 199.0

# Minimum distance from home plate (feet) to be considered part of the wall
_MIN_WALL_DIST = 280.0

# Map from MLBAM team key to stadium name (matching stadium_polygons.py)
_TEAM_TO_STADIUM = {
    'angels':       'Angel Stadium',
    'astros':       'Minute Maid Park',
    'athletics':    'Oakland Coliseum',
    'blue_jays':    'Rogers Centre',
    'braves':       'Truist Park',
    'brewers':      'American Family Field',
    'cardinals':    'Busch Stadium',
    'cubs':         'Wrigley Field',
    'diamondbacks': 'Chase Field',
    'dodgers':      'Dodger Stadium',
    'giants':       'Oracle Park',
    'guardians':    'Progressive Field',
    'mariners':     'T-Mobile Park',
    'marlins':      'loanDepot park',
    'mets':         'Citi Field',
    'nationals':    'Nationals Park',
    'orioles':      'Camden Yards',
    'padres':       'Petco Park',
    'phillies':     'Citizens Bank Park',
    'pirates':      'PNC Park',
    'rangers':      'Globe Life Field',
    'rays':         'Tropicana Field',
    'red_sox':      'Fenway Park',
    'reds':         'Great American Ball Park',
    'rockies':      'Coors Field',
    'royals':       'Kauffman Stadium',
    'tigers':       'Comerica Park',
    'twins':        'Target Field',
    'white_sox':    'Guaranteed Rate Field',
    'yankees':      'Yankee Stadium',
}


def _mlbam_to_field(hc_x, hc_y):
    """Transform MLBAM coordinates to field feet (home plate at origin)."""
    x_ft = _SCALE * (hc_x - _HC_X_CENTER)
    y_ft = _SCALE * (_HC_Y_CENTER - hc_y)
    return x_ft, y_ft


def _extract_wall_arc(points):
    """Extract the contiguous wall arc from outfield_outer points.

    Filters to points with distance > _MIN_WALL_DIST from home plate,
    keeping only the longest contiguous run to avoid stray near-home points.
    Orders points from LF (most-negative x) to RF (most-positive x).
    """
    # Tag each point with its distance
    tagged = []
    for x, y in points:
        dist = math.sqrt(x * x + y * y)
        tagged.append((x, y, dist))

    # Find contiguous runs of points with dist > threshold
    runs = []
    current_run = []
    for x, y, dist in tagged:
        if dist > _MIN_WALL_DIST:
            current_run.append((x, y))
        else:
            if current_run:
                runs.append(current_run)
                current_run = []
    if current_run:
        runs.append(current_run)

    if not runs:
        return []

    # Take the longest contiguous run
    wall = max(runs, key=len)

    # Sort LF to RF (most-negative x to most-positive x)
    # The data is already ordered around the arc, but we want LF→RF
    # Check if first point is on LF or RF side
    if wall[0][0] > wall[-1][0]:
        wall = list(reversed(wall))

    return wall


def extract_all(rda_path, epsilon=None):
    """Extract wall polygons from the RDA file.

    Returns dict of stadium_name → [(x_ft, y_ft), ...].
    """
    result = pyreadr.read_r(rda_path)
    df = result['MLBStadiumsPathData']

    walls = {}
    for team_key, stadium_name in sorted(_TEAM_TO_STADIUM.items()):
        oo = df[(df['team'] == team_key) & (df['segment'] == 'outfield_outer')]
        if oo.empty:
            print(f'  WARNING: no outfield_outer data for {team_key}', file=sys.stderr)
            continue

        # Transform all points
        field_pts = [_mlbam_to_field(row['x'], row['y']) for _, row in oo.iterrows()]

        # Extract wall arc
        wall = _extract_wall_arc(field_pts)
        if not wall:
            print(f'  WARNING: no wall points for {team_key}', file=sys.stderr)
            continue

        # Optional RDP simplification
        if epsilon is not None:
            from fetch_stadium_polygons import rdp_simplify
            wall = rdp_simplify(wall, epsilon=epsilon)

        # Round to 1 decimal
        wall = [(round(x, 1), round(y, 1)) for x, y in wall]
        walls[stadium_name] = wall
        dists = [round(math.sqrt(x**2 + y**2)) for x, y in wall]
        print(f'  {stadium_name:<30s} {len(wall):2d} pts  '
              f'LF={dists[0]}  CF={max(dists)}  RF={dists[-1]}')

    return walls


def save_json(walls, output_path):
    """Save wall data as JSON."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w') as fh:
        json.dump(
            {name: [[x, y] for x, y in pts] for name, pts in walls.items()},
            fh,
            indent=2,
        )
    return output_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Extract outfield wall shapes from MLBAM stadium data.')
    parser.add_argument('rda_path', help='Path to MLBStadiaPathData.rda')
    parser.add_argument('--out', default='data/mlbam_walls.json',
                        help='Output JSON path (default: data/mlbam_walls.json)')
    parser.add_argument('--epsilon', type=float, default=None,
                        help='RDP simplification tolerance in feet (omit for no simplification)')
    args = parser.parse_args()

    # Resolve output path relative to repo root
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_path = os.path.join(root, args.out)

    # Add src to path for fetch_stadium_polygons import
    sys.path.insert(0, os.path.join(root, 'src'))

    print('Extracting MLBAM wall data...')
    walls = extract_all(args.rda_path, epsilon=args.epsilon)
    print(f'\nExtracted {len(walls)} stadiums')

    path = save_json(walls, out_path)
    print(f'Saved → {path}')
