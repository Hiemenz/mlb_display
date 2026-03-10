"""stadium_polygons.py — Outfield fence polygon data for all 30 MLB stadiums.

Coordinate system (feet, home plate = origin):
  x positive → first base / RF side
  x negative → third base / LF side
  y positive → center field direction

Conversion from field_view.py BALLPARK_DIMENSIONS (dist_ft, angle_deg):
  x = dist_ft * sin(radians(angle_deg))
  y = dist_ft * cos(radians(angle_deg))
"""

import json
import math
import os

# ---------------------------------------------------------------------------
# Raw ballpark wall data (mirrored from field_view.py to avoid PIL dependency).
# Each value is a list of (distance_ft, angle_deg) pairs.
# angle_deg: -45 = LF foul pole, 0 = straight CF, +45 = RF foul pole.
# ---------------------------------------------------------------------------
def _w(a, b, c, d, e, f, g, h, i):
    return [
        (a, -45), (b, -33), (c, -22.5), (d, -11),
        (e,   0), (f,  11), (g,  22.5), (h,  33), (i,  45),
    ]

BALLPARK_DIMENSIONS = {
    # AL East
    'Yankee Stadium':  _w(318, 390, 399, 405, 408, 400, 385, 353, 314),
    'Fenway Park': [
        (310, -45), (379, -25), (390, -12), (420, -4),
        (380,  17), (302,  45),
    ],
    'Camden Yards':              _w(333, 357, 364, 390, 410, 390, 373, 347, 318),
    'Rogers Centre':             _w(328, 356, 375, 393, 400, 393, 375, 356, 328),
    'Tropicana Field':           _w(315, 345, 370, 392, 404, 392, 370, 348, 322),
    # AL Central
    'Guaranteed Rate Field':     _w(330, 357, 377, 392, 400, 387, 372, 356, 335),
    'Progressive Field':         _w(325, 350, 370, 393, 405, 390, 375, 352, 325),
    'Comerica Park':             _w(345, 360, 370, 403, 420, 395, 365, 352, 330),
    'Kauffman Stadium':          _w(330, 357, 375, 398, 410, 398, 375, 357, 330),
    'Target Field':              _w(339, 361, 377, 395, 404, 387, 367, 350, 328),
    # AL West
    'Minute Maid Park':          _w(315, 339, 362, 418, 435, 400, 373, 350, 326),
    'Angel Stadium':             _w(330, 360, 383, 397, 400, 388, 370, 353, 330),
    'Oakland Coliseum':          _w(330, 362, 388, 396, 400, 382, 362, 349, 330),
    'T-Mobile Park':             _w(331, 356, 378, 393, 401, 393, 381, 354, 326),
    'Globe Life Field':          _w(329, 355, 374, 396, 407, 396, 374, 352, 326),
    # NL East
    'Truist Park':               _w(335, 361, 380, 393, 400, 390, 375, 352, 325),
    'Citi Field':                _w(335, 348, 358, 390, 408, 393, 375, 354, 330),
    'Citizens Bank Park':        _w(329, 352, 369, 390, 401, 390, 369, 352, 330),
    'Nationals Park':            _w(336, 360, 377, 393, 402, 388, 370, 355, 335),
    'loanDepot park':            _w(344, 368, 386, 400, 407, 400, 392, 366, 335),
    # NL Central
    'Wrigley Field':             _w(355, 363, 368, 385, 400, 385, 368, 363, 353),
    'Great American Ball Park':  _w(328, 356, 379, 395, 404, 388, 370, 350, 325),
    'American Family Field':     _w(344, 361, 371, 390, 400, 390, 374, 363, 345),
    'PNC Park':                  _w(325, 360, 389, 396, 399, 390, 375, 350, 320),
    'Busch Stadium':             _w(336, 360, 375, 392, 400, 392, 375, 360, 335),
    # NL West
    'Dodger Stadium':            _w(330, 360, 375, 392, 400, 392, 375, 360, 330),
    'Chase Field':               _w(330, 357, 374, 396, 407, 396, 374, 358, 335),
    'Coors Field':               _w(347, 372, 390, 407, 415, 395, 375, 366, 350),
    'Oracle Park': [
        (339, -45), (362, -33), (382, -22.5), (396, -11), (399, 0),
        (410,  11), (421,  22.5), (360,  35), (309,  45),
    ],
    'Petco Park':                _w(336, 354, 367, 385, 396, 392, 391, 360, 322),
}

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
    'Oakland Coliseum':         'Oakland Athletics',
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
# Core conversion
# ---------------------------------------------------------------------------

def dimensions_to_polygon(dims):
    """Convert list of (dist_ft, angle_deg) to list of [x_ft, y_ft].

    angle_deg convention (from field_view.py):
      -45 = LF foul pole,  0 = straight-away CF,  +45 = RF foul pole
    """
    pts = []
    for dist, angle in dims:
        rad = math.radians(angle)
        x = round(dist * math.sin(rad), 1)
        y = round(dist * math.cos(rad), 1)
        pts.append([x, y])
    return pts


# Build polygon dict at import time (fast — pure arithmetic on 270 pairs)
STADIUM_POLYGONS = {
    name: dimensions_to_polygon(dims)
    for name, dims in BALLPARK_DIMENSIONS.items()
}


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


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def export_json(filepath):
    """Write all 30 stadiums to *filepath* as a JSON array.

    Each element: {"stadium": str, "team": str, "wall_polygon": [[x,y], ...]}
    Returns the resolved filepath.
    """
    parent = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(parent, exist_ok=True)

    records = [
        {
            "stadium": name,
            "team": TEAM_NAMES.get(name, ""),
            "wall_polygon": poly,
        }
        for name, poly in STADIUM_POLYGONS.items()
    ]

    with open(filepath, 'w') as fh:
        json.dump(records, fh, indent=2)

    return filepath


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------

if __name__ == '__main__':
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
