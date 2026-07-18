"""stadium_polygons.py — Outfield fence polygon data for all 30 MLB stadiums.

Coordinate system (feet, home plate = origin):
  x positive → first base / RF side
  x negative → third base / LF side
  y positive → center field direction

Wall polygons are loaded from data/mlbam_walls.json (detailed ~50-point shapes
extracted from MLBAM's canonical stadium data). Points are ordered left
(LF foul pole) to right (RF foul pole).

Sutter Health Park (A's temporary Sacramento stadium) is not in the MLBAM
dataset and uses a simple 5-point polygon from the MLB Stats API.
"""

import json
import math
import os

# ---------------------------------------------------------------------------
# Load detailed MLBAM wall polygons from JSON data file.
# Falls back to empty dict if file is missing.
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MLBAM_WALLS_PATH = os.path.join(_ROOT, 'data', 'mlbam_walls.json')
_MLBAM_INFIELD_PATH = os.path.join(_ROOT, 'data', 'mlbam_infield.json')


def _load_polygon_json(path):
    """Load a {stadium_name: [[x, y], ...]} JSON file as tuples."""
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        raw = json.load(fh)
    return {name: [tuple(pt) for pt in pts] for name, pts in raw.items()}


STADIUM_POLYGONS = _load_polygon_json(_MLBAM_WALLS_PATH)

# Infield dirt cutout boundary per park (data/mlbam_infield.json), extracted
# from GeomMLBStadiums' infield_outer path segment — see
# src/extract_infield_polygons.py. Comerica Park's shape here matches the
# generic modern cutout: the pre-2025 "keyhole" strip (removed before the
# 2025 season) only ever appeared in that dataset's infield_inner segment,
# not infield_outer, so no override is needed. Rogers Centre has no entry:
# its infield_outer path is a broken open arc in the source data (never
# reaches the home-plate cutout), so extract_infield_polygons.py excludes
# it and get_infield_polygon() falls back to the Yankee Stadium shape.
STADIUM_INFIELD_POLYGONS = _load_polygon_json(_MLBAM_INFIELD_PATH)

# Sutter Health Park — not in MLBAM dataset (A's temporary Sacramento stadium)
if 'Sutter Health Park' not in STADIUM_POLYGONS:
    STADIUM_POLYGONS['Sutter Health Park'] = [
        (-233.3, 233.3),   # LF foul pole, 330 ft
        (-111.1, 363.4),   # LF-CF gap, 380 ft
        (0.0,    403.0),   # deep CF, 403 ft
        (111.1,  363.4),   # RF-CF gap, 380 ft
        (229.8,  229.8),   # RF foul pole, 325 ft
    ]


# ---------------------------------------------------------------------------
# Team name mapping (stadium → franchise name)
# ---------------------------------------------------------------------------
TEAM_NAMES = {
    # AL East
    'Yankee Stadium':           'New York Yankees',
    'Fenway Park':              'Boston Red Sox',
    'Camden Yards':             'Baltimore Orioles',
    'Rogers Centre':            'Toronto Blue Jays',
    'Tropicana Field':          'Tampa Bay Rays',
    # AL Central
    'Guaranteed Rate Field':    'Chicago White Sox',
    'Progressive Field':        'Cleveland Guardians',
    'Comerica Park':            'Detroit Tigers',
    'Kauffman Stadium':         'Kansas City Royals',
    'Target Field':             'Minnesota Twins',
    # AL West
    'Minute Maid Park':         'Houston Astros',
    'Angel Stadium':            'Los Angeles Angels',
    'Sutter Health Park':       'Oakland Athletics',
    'T-Mobile Park':            'Seattle Mariners',
    'Globe Life Field':         'Texas Rangers',
    # NL East
    'Truist Park':              'Atlanta Braves',
    'Citi Field':               'New York Mets',
    'Citizens Bank Park':       'Philadelphia Phillies',
    'Nationals Park':           'Washington Nationals',
    'loanDepot park':           'Miami Marlins',
    # NL Central
    'Wrigley Field':            'Chicago Cubs',
    'Great American Ball Park': 'Cincinnati Reds',
    'American Family Field':    'Milwaukee Brewers',
    'PNC Park':                 'Pittsburgh Pirates',
    'Busch Stadium':            'St. Louis Cardinals',
    # NL West
    'Dodger Stadium':           'Los Angeles Dodgers',
    'Chase Field':              'Arizona Diamondbacks',
    'Coors Field':              'Colorado Rockies',
    'Oracle Park':              'San Francisco Giants',
    'Petco Park':               'San Diego Padres',
}


# ---------------------------------------------------------------------------
# Backward-compatibility shim for callers that expect (dist, angle) pairs,
# derived from the Cartesian polygon data above — angles are geometrically
# correct (not the old fixed 9-slot scheme).
# ---------------------------------------------------------------------------
def _cartesian_to_polar(pts):
    """Convert [(x_ft, y_ft)] to [(dist_ft, angle_deg)] for compat callers."""
    result = []
    for x, y in pts:
        dist = math.sqrt(x * x + y * y)
        angle = math.degrees(math.atan2(x, y))  # atan2(x,y) gives bearing from +y axis
        result.append((round(dist, 1), round(angle, 2)))
    return result


BALLPARK_DIMENSIONS = {
    name: _cartesian_to_polar(pts)
    for name, pts in STADIUM_POLYGONS.items()
}


# ---------------------------------------------------------------------------
# Legacy conversion helper — retained for field_view.py's _DEFAULT_WALL_POLY.
# ---------------------------------------------------------------------------

def dimensions_to_polygon(dims):
    """Convert list of (dist_ft, angle_deg) to list of [x_ft, y_ft].

    angle_deg convention:
      -45 = LF foul pole,  0 = straight-away CF,  +45 = RF foul pole
    """
    pts = []
    for dist, angle in dims:
        rad = math.radians(angle)
        x = round(dist * math.sin(rad), 1)
        y = round(dist * math.cos(rad), 1)
        pts.append([x, y])
    return pts


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_polygon(venue_name):
    """Return wall polygon for *venue_name*, with case-insensitive fuzzy fallback.

    Returns None if no reasonable match is found; callers should fall back to
    a generic 400-ft symmetric polygon.
    """
    if venue_name in STADIUM_POLYGONS:
        return STADIUM_POLYGONS[venue_name]
    lower = venue_name.lower()
    for k, v in STADIUM_POLYGONS.items():
        if lower in k.lower() or k.lower() in lower:
            return v
    return None


def get_infield_polygon(venue_name):
    """Return infield dirt cutout polygon for *venue_name*, fuzzy-matched.

    Returns None if no match is found; callers should fall back to a
    generic cutout shape.
    """
    if venue_name in STADIUM_INFIELD_POLYGONS:
        return STADIUM_INFIELD_POLYGONS[venue_name]
    lower = venue_name.lower()
    for k, v in STADIUM_INFIELD_POLYGONS.items():
        if lower in k.lower() or k.lower() in lower:
            return v
    return None


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def export_json(filepath):
    """Write all stadiums to *filepath* as a JSON array.

    Each element: {"stadium": str, "team": str, "wall_polygon": [[x,y], ...]}
    Returns the resolved filepath.
    """
    parent = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(parent, exist_ok=True)

    records = [
        {
            "stadium": name,
            "team": TEAM_NAMES.get(name, ""),
            "wall_polygon": [[round(x, 1), round(y, 1)] for x, y in pts],
        }
        for name, pts in STADIUM_POLYGONS.items()
    ]

    with open(filepath, 'w') as fh:
        json.dump(records, fh, indent=2)

    return filepath


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------

if __name__ == '__main__':  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description='Export MLB stadium polygon data to JSON.')
    parser.add_argument('--out', default='data/stadium_polygons.json',
                        help='Output JSON file path')
    args = parser.parse_args()

    out = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        args.out,
    )
    path = export_json(out)
    print(f'Wrote {len(STADIUM_POLYGONS)} stadiums to {path}')
    for name, pts in STADIUM_POLYGONS.items():
        dists = [round(math.sqrt(x**2 + y**2)) for x, y in pts]
        print(f'  {name:<35s} {len(pts):2d} pts  LF={dists[0]}  CF={max(dists)}  RF={dists[-1]}')
