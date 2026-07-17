#!/usr/bin/env python3
"""extract_infield_polygons.py — Extract infield dirt cutout shapes from MLBAM
stadium path data.

Data source: https://github.com/bdilday/GeomMLBStadiums
  inst/extdata/mlb_stadia_paths.csv — the same MLBAM canonical field-shape
  dataset used by src/generate_wall_polygons.py's predecessor, but as a plain
  CSV (no R/pyreadr dependency). Each row is one point along a named
  `segment` path for one `team`; the `infield_outer` segment traces the
  dirt/grass cutout boundary — the shape drawn as the infield "waist" in
  src/image_box.py's field diagram tile.

Coordinate transform (MLBAM hc_x/hc_y → field feet), matching
stadium_polygons.py's wall data:
    x_ft = 2.495671 * (hc_x - 125.0)
    y_ft = 2.495671 * (199.0 - hc_y)
    Home plate at (0, 0), +x = RF, +y = CF

Usage:
    python3 src/extract_infield_polygons.py /path/to/mlb_stadia_paths.csv
"""

import argparse
import csv
import json
import math
import os
import sys

_SCALE = 2.495671
_HC_X_CENTER = 125.0
_HC_Y_CENTER = 199.0

# Map from MLBAM team key to stadium name (matches stadium_polygons.py /
# extract_mlbam_walls.py). No entry for the A's: the CSV's "athletics" key
# reflects the old Oakland Coliseum, not the current Sutter Health Park.
_TEAM_TO_STADIUM = {
    'angels':       'Angel Stadium',
    'astros':       'Minute Maid Park',
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

# Teams to skip even though the CSV has data for them.
# blue_jays: GeomMLBStadiums' infield_outer path for Rogers Centre is broken —
# it's an 87-point open arc that never dips down to the home-plate cutout
# (min y = 85.8 ft, vs. -30ish for every other park), so it renders as a
# floating arc instead of the usual keyhole. Skip it and let
# get_infield_polygon() fall back to the generic Yankee Stadium shape.
_EXCLUDE_TEAMS = {'blue_jays'}


def _mlbam_to_field(hc_x, hc_y):
    x_ft = _SCALE * (hc_x - _HC_X_CENTER)
    y_ft = _SCALE * (_HC_Y_CENTER - hc_y)
    return round(x_ft, 1), round(y_ft, 1)


def extract_all(csv_path):
    """Return dict of stadium_name → [(x_ft, y_ft), ...] closed polygon."""
    by_team = {}
    with open(csv_path, newline='') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row['segment'] != 'infield_outer':
                continue
            by_team.setdefault(row['team'], []).append(
                (float(row['x']), float(row['y'])))

    polygons = {}
    for team_key, stadium_name in sorted(_TEAM_TO_STADIUM.items()):
        if team_key in _EXCLUDE_TEAMS:
            continue
        pts = by_team.get(team_key)
        if not pts:
            print(f'  WARNING: no infield_outer data for {team_key}', file=sys.stderr)
            continue
        field_pts = [_mlbam_to_field(x, y) for x, y in pts]
        polygons[stadium_name] = field_pts
        dists = [round(math.hypot(x, y)) for x, y in field_pts]
        print(f'  {stadium_name:<30s} {len(field_pts):2d} pts  '
              f'min={min(dists)}  max={max(dists)}')

    return polygons


def save_json(polygons, output_path):
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w') as fh:
        json.dump(
            {name: [[x, y] for x, y in pts] for name, pts in polygons.items()},
            fh,
            indent=2,
        )
    return output_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Extract infield dirt cutout polygons from MLBAM stadium path data.')
    parser.add_argument('csv_path', help='Path to mlb_stadia_paths.csv')
    parser.add_argument('--out', default='data/mlbam_infield.json',
                        help='Output JSON path (default: data/mlbam_infield.json)')
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_path = os.path.join(root, args.out)

    print('Extracting MLBAM infield dirt data...')
    polygons = extract_all(args.csv_path)
    print(f'\nExtracted {len(polygons)} stadiums')

    path = save_json(polygons, out_path)
    print(f'Saved -> {path}')
