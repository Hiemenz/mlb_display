"""generate_wall_polygons.py — Generate accurate outfield wall polygons from
FanGraphs piecewise functions (Andrew Fox / garesborn/MLB-stadium-dimensions).

Evaluates wall distance at 1° intervals (0°–90°), converts polar → Cartesian,
and writes data/mlbam_walls.json.

Coordinate system (feet, home plate = origin):
  x positive → first base / RF side
  x negative → third base / LF side
  y positive → center field direction

FanGraphs angle convention: 0° = LF foul line, 90° = RF foul line.
"""

import json
import math
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_PATH = os.path.join(_ROOT, 'data', 'mlbam_walls.json')

# ═══════════════════════════════════════════════════════════════════════════════
# Piecewise coefficients — from garesborn/MLB-stadium-dimensions/stad_data.py
# Format 0: (c0, c1, θ_min, θ_max) → d = c0 / (sin(θ) + c1·cos(θ))
# Format 1: ([c0..c6], [c7, c8], θ_min, θ_max) → complex trig
# Format 2: (c0, 'sin'|'cos'|'con', θ_min, θ_max) → d = c0/sin(θ), c0/cos(θ), or c0
#            Also supports format-0 tuples within a format-2 stadium.
# ═══════════════════════════════════════════════════════════════════════════════

STADIUMS = {
    'Chase Field': {
        'dform': 0,
        'coeffs': [
            (-389.4194, -1.1624467, 0, 4.9),
            (423.5471, 1.085346, 4.9, 6.6),
            (6211.3885, 17.49789, 6.6, 31.7),
            (559.10919, 1.0073058, 31.7, 38.9),
            (-91.557622, -1.10398598, 38.9, 39.1),
            (571.92441, 1.0070058, 39.1, 50.5),
            (114.59269, -0.76826977, 50.5, 50.8),
            (557.962, 1.0031979, 50.8, 57.7),
            (353.793768, 0.06108017, 57.7, 82.5),
            (395.0241, 0.9533913, 82.5, 84.2),
            (327, -0.9060869, 84.2, 90),
        ],
    },
    'Camden Yards': {
        'dform': 0,
        'coeffs': [
            (-1789.977, -5.61943, 0, 25.5),
            (801.702, 1.83, 25.5, 49),
            (359.7761, 0.187168, 49, 82),
            (331, -0.396914, 82, 90),
        ],
    },
    'Fenway Park': {
        'dform': 0,
        'coeffs': [
            (-119.0423, -0.3941798, 0, 3.8),
            (-402.289, -1.17404, 3.8, 4.9),
            (-808.953, -2.274195, 4.9, 6),
            (-2332.79083, -6.3601456, 6, 7.1),
            (-20759.85313, -55.616, 7.1, 8.1),
            (1129.33168, 2.875435, 8.1, 31),
            (-417.143116, -1.8849057, 31, 33.8),
            (431.2604, 0.587157, 33.8, 52.2),
            (2077.8716, 7.7513156, 52.2, 53.1),
            (306, 0.00577087, 53.1, 90),
        ],
    },
    'Wrigley Field': {
        'dform': 1,
        'coeffs': [
            [-4499.413, -12.7462, 0, 10.9],
            [297.1748, 0.636566, 10.9, 13.1],
            [18363.859, 53.4839, 13.1, 29.4],
            [[9353823.75, 33.2, 2540504.25, 146.8, 33526.25, 9105.75, 180],
             [22815.51, 155682], 29.4, 49.2],
            [357.8732, 0.245827, 49.2, 73.2],
            [496.86435, 1.62768, 73.2, 74.8],
            [355, 0.112061, 74.8, 90],
        ],
    },
    'Guaranteed Rate Field': {
        'dform': 0,
        'coeffs': [
            [-7014.6043, -20.939117, 0, 24.1],
            [1495.6997, 3.92207, 24.1, 30.6],
            [820.61, 1.88324, 30.6, 36.6],
            [1969.1759, 5.562717, 36.6, 39.1],
            [561.4967, 1.00525, 39.1, 50.6],
            [363.2118, 0.2203438, 50.6, 54],
            [426.18439, 0.49718, 54, 58.7],
            [378.8179, 0.259128, 58.7, 63.4],
            [340.82399, 0.03285, 63.4, 79],
            [327, -0.177146, 79, 90],
        ],
    },
    'Great American Ball Park': {
        'dform': 1,
        'coeffs': [
            [[11951552.5, 25.2, 8986447.5, 164.8, 41212.25, 30987.75, 190],
             [19212.09, 168200], 0, 44.7],
            [436.311, 0.52231577, 44.7, 60.3],
            [336.435, 0.0014347, 60.3, 86.6],
            [326, -0.5206991, 86.6, 90],
        ],
    },
    'Progressive Field': {
        'dform': 0,
        'coeffs': [
            (-1609.844, -4.98404, 0, 20.3),
            (906.183, 2.2274, 20.3, 48.2),
            (356.7465, 0.197554, 48.2, 78.2),
            (321, -0.303978, 78.2, 90),
        ],
    },
    'Coors Field': {
        'dform': 0,
        'coeffs': [
            (-551.417, -1.57548, 0, 1.2),
            (4061.537, 11.422, 1.2, 37.5),
            (536.536, 0.84288, 37.5, 60.2),
            (345, -0.08135, 60.2, 90),
        ],
    },
    'Comerica Park': {
        'dform': 2,
        'coeffs': [
            (-410, -1.23813, 0, 1.3),
            (337.21, 'cos', 1.3, 22.5),
            (-430.4868, -1.6908, 22.5, 24.6),
            (347.675, 'cos', 24.6, 35.3),
            (593.97, 1, 35.3, 54),
            (345, 'sin', 54, 90),
        ],
    },
    'Minute Maid Park': {
        'dform': 1,
        'coeffs': [
            (-2738.7177, -8.400974, 0, 23),
            (315.172, 0.493462, 23, 24.1),
            (-2943.702, -9.23423, 24.1, 35.2),
            (522, 0.81, 35.2, 51.2),
            (347.579, 0.120368, 51.2, 67.7),
            (42.673422, -2.124119, 67.7, 67.9),
            (315, 0.0366002, 67.9, 90),
        ],
    },
    'Kauffman Stadium': {
        'dform': 1,
        'coeffs': [
            [[1738857, 10.1, 495945, 169.9, 5417, 1545, 180],
             [3671.3, 206082], 0, 5.9],
            [25650.376, 71.503534, 5.9, 22.1],
            [[19759218, 50.9, 1837968, -76.9, 111634, 10384, -26],
             [78594.9, 62658], 22.1, 59],
            [[5643864, 68.7, 4885920, -80.7, 16218, 14040, -12],
             [5740.3, 242208], 59, 76.9],
            [361.884, 0.01803985, 76.9, 82.7],
            [[958907, 82.6, 322725, -44.6, 2897, 975, 38],
             [1929, 219122], 82.7, 90],
        ],
    },
    'Angel Stadium': {
        'dform': 0,
        'coeffs': [
            (-352.2388, -1.06739, 0, 1.6),
            (-496.7696, -1.493901, 1.6, 3.2),
            (-641.02615, -1.9114787, 3.2, 4.8),
            (-1020.3203, -2.9928111, 4.8, 6.6),
            (6919.533, 19.3875915, 6.6, 11.2),
            (1240.50705, 3.314747, 11.2, 42.6),
            (437.37565, 0.5733725, 42.6, 68),
            (351.0005, -0.0286525, 68, 84),
            (340.789, -0.3046164, 84, 85.6),
            (329.5441, -0.72339596, 85.6, 87),
            (324.50638, -1.0040283, 87, 88.4),
            (328, -0.629411, 88.4, 90),
        ],
    },
    'Dodger Stadium': {
        'dform': 0,
        'coeffs': [
            (-443.8081, -1.344873, 0, 4.2),
            (-829.5118, -2.44985, 4.2, 7.8),
            (-10942.3745, -30.646819, 7.8, 9.5),
            (1719.756, 4.622957, 9.5, 25.1),
            (1115.073, 2.83277, 25.1, 31.1),
            (928.868, 2.258998, 31.1, 42.6),
            (742.26267, 1.620443, 42.6, 44),
            (562.6864, 0.9947777, 44, 46.3),
            (472.8006, 0.66870534, 46.3, 49.2),
            (423.6147, 0.478618, 49.2, 55.3),
            (395.11776, 0.349269, 55.3, 59),
            (392.2193, 0.3344991, 59, 63.1),
            (381.7462, 0.2729345, 63.1, 69.2),
            (372.8431, 0.2051737, 69.2, 74.7),
            (368.8506, 0.163833, 74.7, 80.5),
            (362.23, 0.053704, 80.5, 82.1),
            (353.007, -0.131245, 82.1, 83.3),
            (334.774, -0.564136, 83.3, 85.6),
            (333.006, -0.629807, 85.6, 87.2),
            (328.317, -0.90885, 87.2, 88.4),
            (330, -0.729958, 88.4, 90),
        ],
    },
    'loanDepot park': {
        'dform': 0,
        'coeffs': [
            (-3285.092, -9.80624, 0, 23.7),
            (5130.955, 14.1917, 23.7, 27.1),
            (1260.2215, 3.099602, 27.1, 33.1),
            (928.6866, 2.112672, 33.1, 37.2),
            (822.69397, 1.78492, 37.2, 41.2),
            (697.69, 1.380693, 41.2, 44.6),
            (624.24997, 1.1315557, 44.6, 47.9),
            (567.2531, 0.927191, 47.9, 51.2),
            (123.3194, -0.7717922, 51.2, 51.3),
            (163.1114, -0.618006, 51.3, 51.6),
            (263.849, -0.2205658, 51.6, 52.3),
            (333.1776, 0.061447, 52.3, 53.6),
            (333.94836, 0.06472688, 53.6, 55),
            (391.363, 0.32139203, 55, 56.5),
            (457.485, 0.630953, 56.5, 59),
            (389.587, 0.2903055, 59, 60.8),
            (387.8902, 0.281246, 60.8, 63.6),
            (367.932, 0.163124, 63.6, 68.2),
            (360.9411, 0.112519, 68.2, 72.1),
            (349.332, 0.00931917, 72.1, 79.2),
            (339.562, -0.137541, 79.2, 84.3),
            (337, -0.212114, 84.3, 90),
        ],
    },
    'American Family Field': {
        'dform': 0,
        'coeffs': [
            [4068.1011, 11.7916, 0, 16.5],
            [-60.8626, -0.47706, 16.5, 16.8],
            [3834.475, 10.73232, 16.8, 23.3],
            [1042.985, 2.60569, 23.3, 35.5],
            [-1107.4106, -4.237288, 35.5, 37.7],
            [566.71123, 1, 37.7, 52.3],
            [287.52, -0.130068, 52.3, 56.2],
            [393.82239, 0.374126, 56.2, 74],
            [358.50448, 0.027826, 74, 85],
            [344, -0.435742, 85, 90],
        ],
    },
    'Target Field': {
        'dform': 0,
        'coeffs': [
            (-2731.998, -8.3292, 0, 20),
            (1691.285, 4.5671, 20, 38.5),
            (629.3765, 1.2001, 38.5, 51.2),
            (382.741, 0.24243, 51.2, 67),
            (339, -0.05651, 67, 90),
        ],
    },
    'Citi Field': {
        'dform': 0,
        'coeffs': [
            (-2766.825, -8.3843195, 0, 5.2),
            (-371.523921, -1.204617, 5.2, 7),
            (-1855.73071, -5.52645, 7, 18.8),
            (682.2307, 1.566132, 18.8, 23.3),
            (-40721.387, -119.6616683, 23.3, 29.5),
            (1281.67692, 3.1812751, 29.5, 38.2),
            (575.86589, 0.9960149, 38.2, 49.1),
            (358.6125, 0.1847292, 49.1, 82.1),
            (335, -0.30194697, 82.1, 90),
        ],
    },
    'Yankee Stadium': {
        'dform': 2,
        'coeffs': [
            (-752.7416, -2.397266, 0, 3.2),
            (-1341.4764, -4.22849, 3.2, 4.9),
            (323.639, 'cos', 4.9, 30.6),
            (2683.6147, 7.700602, 30.6, 36.1),
            (913.27186, 2.139572, 36.1, 40.4),
            (707.36801, 1.4643105, 40.4, 44.4),
            (600.6388, 1.096466, 44.4, 48.4),
            (496.311752, 0.7103813, 48.4, 52.1),
            (445.2994, 0.5053365, 52.1, 56.7),
            (390.30014, 0.2548946, 56.7, 62.8),
            (345.39856, 0.001719809, 62.8, 80.6),
            (324.4985, -0.3638949, 80.6, 84.8),
            (316, -0.6421425, 84.8, 90),
        ],
    },
    'Citizens Bank Park': {
        'dform': 2,
        'coeffs': [
            (330, 'cos', 0, 34.3),
            (644.15, 1.277017, 34.3, 50.7),
            (308.591, -0.02468, 50.7, 55.9),
            (543.4657, 1.08071, 55.9, 59.3),
            (331, 'sin', 59.3, 88.3),
            (325, -0.596191, 88.3, 90),
        ],
    },
    'PNC Park': {
        'dform': 0,
        'coeffs': [
            (-1759.947, -5.4827, 0, 22.3),
            (1120.146, 2.8184, 22.3, 34.1),
            (716.884, 1.56, 34.1, 44.3),
            (478.809, 0.71785, 44.3, 58.5),
            (-4560.837, -24.0136, 58.5, 59.6),
            (366.846, 0.089958, 59.6, 81.5),
            (321, -0.75751, 81.5, 90),
        ],
    },
    'Petco Park': {
        'dform': 2,
        'coeffs': [
            (321.433, 'cos', 0, 3.4),
            (-311.7359, -1.029242, 3.4, 7.2),
            (346.87116, 'cos', 7.2, 27.8),
            (1425.7353, 3.59492, 27.8, 31.8),
            (740.2202, 1.568309, 31.8, 38.3),
            (543.05468, 0.9402139, 38.3, 49.2),
            (318.3662, 0.0718681, 49.2, 50.4),
            (539.44852, 0.9611939, 50.4, 56.2),
            (393.566469, 0.2972994, 56.2, 63.5),
            (344.316, 0.0091096, 63.5, 83.8),
            (336, -0.2134522, 83.8, 90),
        ],
    },
    'Oracle Park': {
        'dform': 0,
        'coeffs': [
            (-697.339, -2.25676, 0, 15),
            (946.0859, 2.4155, 15, 18),
            (-712.5915, -2.389, 18, 26),
            (565, 1.025, 26, 55),
            (347.526, 0.07905, 55, 86.5),
            (335, -0.513097, 86.5, 90),
        ],
    },
    'T-Mobile Park': {
        'dform': 0,
        'coeffs': [
            (-3502.437, -10.74367, 0, 26.5),
            (825.224, 1.9153, 26.5, 47),
            (414.291, 0.427476, 47, 59.6),
            (377.4922, 0.2382, 59.6, 66.5),
            (336.559, -0.037016, 66.5, 88.5),
            (331, -0.6671, 88.5, 90),
        ],
    },
    'Busch Stadium': {
        'dform': 2,
        'coeffs': [
            (-436.689, -1.3173, 0, 3.3),
            (346.303, 'cos', 3.3, 25.6),
            (857.076, 1.995805, 25.6, 39.9),
            (569.534, 1.04571, 39.9, 50),
            (434.192, 0.514, 50, 64),
            (346.76, 'sin', 64, 88.4),
            (330, -1.73033, 88.4, 90),
        ],
    },
    'Tropicana Field': {
        'dform': 2,
        'coeffs': [
            (-357.101, -1.109, 0, 1.7),
            (331, 'cos', 1.7, 33.7),
            (1678.156, 4.403, 33.7, 36.2),
            (596.756, 1.09406, 36.2, 55),
            (275.103, -0.2654, 55, 56.4),
            (477.013, 0.6444, 56.4, 58),
            (342.43, 0.011121, 58, 86),
            (315, -1.13533, 86, 90),
        ],
    },
    'Rogers Centre': {
        'dform': 2,
        'coeffs': [
            [-1725.1974, -5.2597, 0, 20],
            [2160.354, 5.7667, 20, 32.5],
            [400, 'con', 32.5, 57.5],
            [374.6429, 0.17341, 57.5, 70],
            [328, -0.19012, 70, 90],
        ],
    },
    'Nationals Park': {
        'dform': 0,
        'coeffs': [
            (-1192.9, -3.56091, 0, 13.1),
            (1018.837, 2.609847, 13.1, 46.5),
            (372.8599, 0.286983, 46.5, 57.9),
            (1089.6378, 3.903208, 57.9, 59),
            (383.87617, 0.297133, 59, 74.1),
            (163.401, -1.88975, 74.1, 74.2),
            (377.1893, 0.261412, 74.2, 76.5),
            (336, -0.221987, 76.5, 90),
        ],
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# Piecewise evaluator
# ═══════════════════════════════════════════════════════════════════════════════


def _eval_distance(theta_deg, coeffs, dform):
    """Evaluate wall distance at *theta_deg* (0=LF, 90=RF) using piecewise coefficients."""
    theta = math.radians(theta_deg)
    sin_t = math.sin(theta)
    cos_t = math.cos(theta)

    for piece in coeffs:
        # Unpack: last two elements are always theta_min, theta_max
        if isinstance(piece[0], list):
            # Format 1: [[c0..c6], [c7, c8], θ_min, θ_max]
            c = piece[0]
            c2 = piece[1]
            t_min, t_max = piece[2], piece[3]
        else:
            t_min = piece[-2]
            t_max = piece[-1]

        if not (t_min <= theta_deg < t_max or
                (theta_deg == 90 and t_max == 90)):
            continue

        # Format 2: string-based sub-equations
        if dform == 2 and isinstance(piece[1], str):
            if piece[1] == 'cos':
                return piece[0] / cos_t
            elif piece[1] == 'sin':
                return piece[0] / sin_t
            elif piece[1] == 'con':
                return piece[0]

        # Format 1: complex trig (list-of-lists coefficient)
        if isinstance(piece[0], list):
            c = piece[0]
            c2 = piece[1]
            den = c[4] - c[5] * math.cos(2 * theta - math.radians(c[6]))
            m1 = (c[0] * math.cos(theta - math.radians(c[1]))
                   - c[2] * math.cos(theta - math.radians(c[3]))) / den
            s = math.sin(theta - math.radians(c[1])) ** 2
            m2 = (c2[0] * math.sqrt(abs(den - c2[1] * s))) / den
            return m1 + m2

        # Format 0: c0 / (sin(θ) + c1·cos(θ))
        return piece[0] / (sin_t + piece[1] * cos_t)

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Polar → Cartesian conversion
# ═══════════════════════════════════════════════════════════════════════════════


def _polar_to_cartesian(dist, theta_deg):
    """Convert (distance, FanGraphs angle) to (x_ft, y_ft).

    FanGraphs piecewise coefficients: 0°=RF foul line, 45°≈CF, 90°=LF foul line.
    Our coords: x+=RF, x-=LF, y+=CF.
    Bearing from CF = 45 - theta (positive theta goes toward LF).
    """
    bearing = math.radians(45 - theta_deg)
    x = round(dist * math.sin(bearing), 1)
    y = round(dist * math.cos(bearing), 1)
    return x, y


# ═══════════════════════════════════════════════════════════════════════════════
# Calibrate MLBAM polygon for parks not in FanGraphs data
# ═══════════════════════════════════════════════════════════════════════════════

# Official dimensions: list of (bearing_deg, real_distance_ft)
# bearings: -45=LF pole, -22.5=LC power alley, 0=CF, +22.5=RC power alley, +45=RF pole
_CALIBRATE_PARKS = {
    'Truist Park': {
        'refs': [(-45, 335), (-22.5, 385), (0, 400), (22.5, 375), (45, 325)],
        'polygon': [
            [-208.0, 192.9], [-217.9, 203.3], [-227.8, 213.7], [-237.7, 224.1],
            [-244.7, 235.4], [-238.5, 248.4], [-232.1, 261.3], [-225.9, 274.2],
            [-219.7, 287.2], [-213.5, 300.1], [-207.2, 313.1], [-198.3, 324.0],
            [-186.6, 332.4], [-174.9, 340.7], [-163.1, 348.9], [-151.4, 357.2],
            [-138.5, 363.4], [-125.1, 368.6], [-111.7, 373.9], [-98.4, 379.1],
            [-85.2, 384.8], [-71.8, 390.2], [-58.5, 395.5], [-45.2, 400.9],
            [-31.3, 403.8], [-16.9, 404.0], [-2.5, 404.0], [11.8, 404.0],
            [26.2, 404.0], [40.6, 403.6], [53.8, 398.4], [66.5, 391.8],
            [79.3, 385.3], [92.0, 378.6], [104.8, 372.0], [117.6, 365.4],
            [130.4, 358.9], [143.1, 352.3], [153.8, 343.0], [162.4, 331.5],
            [171.0, 320.0], [179.6, 308.5], [188.2, 297.0], [196.9, 285.5],
            [205.5, 274.1], [214.1, 262.5], [222.7, 251.0], [231.2, 239.5],
            [236.6, 227.1],
        ],
    },
    'Globe Life Field': {
        'refs': [(-45, 329), (-22.5, 372), (0, 407), (22.5, 374), (45, 326)],
        'polygon': [
            [-216.1, 189.7], [-225.2, 201.3], [-234.3, 212.9], [-243.4, 224.4],
            [-244.2, 237.8], [-239.9, 251.9], [-235.6, 265.9], [-228.6, 278.5],
            [-218.4, 289.1], [-207.9, 299.4], [-197.5, 309.8], [-187.1, 320.3],
            [-176.7, 330.7], [-166.3, 341.1], [-155.9, 351.4], [-145.4, 361.8],
            [-134.6, 371.6], [-121.3, 377.8], [-107.8, 383.5], [-94.2, 389.3],
            [-80.7, 395.0], [-67.1, 400.7], [-53.5, 405.5], [-38.8, 405.6],
            [-24.1, 405.6], [-9.4, 405.7], [5.3, 405.8], [20.0, 405.8],
            [34.7, 405.8], [49.4, 405.9], [64.2, 406.1], [78.8, 405.2],
            [89.8, 395.8], [100.2, 385.5], [110.6, 375.1], [121.1, 364.8],
            [133.2, 358.0], [146.6, 353.9], [157.0, 343.4], [167.4, 333.0],
            [177.8, 322.6], [188.2, 312.3], [198.6, 301.9], [209.0, 291.5],
            [219.4, 281.1], [229.8, 270.7], [238.5, 259.4], [240.1, 244.8],
            [241.2, 230.1],
        ],
    },
}

def _calibrate_polygon(polygon, refs):
    """Scale an MLBAM polygon so distances match official dimensions at reference bearings.

    *refs* is a list of (bearing_deg, real_distance_ft) sorted by bearing.
    First entry is pinned to the first polygon point (LF pole), last entry
    to the last polygon point (RF pole). Interior refs match closest polygon point.
    Uses piecewise-linear interpolation of scale factors between reference bearings.
    """
    refs = sorted(refs, key=lambda r: r[0])

    # Compute actual bearing of each polygon point
    bearings = [math.degrees(math.atan2(p[0], p[1])) for p in polygon]

    # Build scale factors at reference bearings
    ref_scales = []
    for idx, (ref_bearing, ref_dist) in enumerate(refs):
        if idx == 0:
            # Pin to first polygon point (LF pole)
            pi = 0
        elif idx == len(refs) - 1:
            # Pin to last polygon point (RF pole)
            pi = len(polygon) - 1
        else:
            # Find closest polygon point to this bearing
            pi = min(range(len(polygon)),
                     key=lambda i: abs(bearings[i] - ref_bearing))
        mlbam_dist = math.sqrt(polygon[pi][0] ** 2 + polygon[pi][1] ** 2)
        sf = ref_dist / mlbam_dist if mlbam_dist > 0 else 1.0
        # Use the actual bearing of the matched point for interpolation
        actual_bearing = bearings[pi] if idx in (0, len(refs) - 1) else ref_bearing
        ref_scales.append((actual_bearing, sf))

    # Interpolate scale factor at any bearing
    def _interp_scale(bearing):
        if bearing <= ref_scales[0][0]:
            return ref_scales[0][1]
        if bearing >= ref_scales[-1][0]:
            return ref_scales[-1][1]
        for i in range(len(ref_scales) - 1):
            b0, s0 = ref_scales[i]
            b1, s1 = ref_scales[i + 1]
            if b0 <= bearing <= b1:
                t = (bearing - b0) / (b1 - b0)
                return s0 + t * (s1 - s0)
        return 1.0

    result = []
    for x, y in polygon:
        dist = math.sqrt(x * x + y * y)
        bearing = math.degrees(math.atan2(x, y))
        sf = _interp_scale(bearing)
        new_dist = dist * sf
        bearing_rad = math.radians(bearing)
        nx = round(new_dist * math.sin(bearing_rad), 1)
        ny = round(new_dist * math.cos(bearing_rad), 1)
        result.append((nx, ny))

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Main generation
# ═══════════════════════════════════════════════════════════════════════════════


def generate_all():
    """Generate wall polygons for all 30 MLB parks. Returns dict."""
    all_polygons = {}

    # 27 FanGraphs parks
    for name, data in STADIUMS.items():
        pts = []
        for theta in range(91):  # 0° to 90° inclusive
            d = _eval_distance(theta, data['coeffs'], data['dform'])
            if d is not None:
                x, y = _polar_to_cartesian(d, theta)
                pts.append((x, y))
        # theta=0 → RF (positive x), theta=90 → LF (negative x); reverse for LF→RF order
        pts.reverse()
        all_polygons[name] = pts

    # 2 calibrated parks (not in FanGraphs dataset)
    for name, info in _CALIBRATE_PARKS.items():
        calibrated = _calibrate_polygon(info['polygon'], info['refs'])
        all_polygons[name] = calibrated

    return all_polygons


def main():
    polygons = generate_all()

    # Write JSON
    json_data = {name: [[p[0], p[1]] for p in pts]
                 for name, pts in polygons.items()}
    with open(_OUT_PATH, 'w') as fh:
        json.dump(json_data, fh, indent=2)

    print(f'Wrote {len(polygons)} stadiums to {_OUT_PATH}')
    print()

    # Print LF/CF/RF distances for verification
    for name, pts in sorted(polygons.items()):
        dists = [round(math.sqrt(x**2 + y**2), 1) for x, y in pts]
        lf = dists[0]
        cf = max(dists)
        rf = dists[-1]
        print(f'  {name:<30s}  {len(pts):2d} pts  LF={lf:>6.1f}  CF={cf:>6.1f}  RF={rf:>6.1f}')


if __name__ == '__main__':
    main()
