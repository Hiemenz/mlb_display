"""
Render the pitch (plate) view with hand-written example data — no MLB API call.

Standalone CLI:
    python src/example_pitch_view.py [--output output/pitch_example.bmp] [--dark]
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pitch_view import render_pitch_view

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_OUTPUT = os.path.join(_REPO_ROOT, 'output', 'pitch_example.bmp')

EXAMPLE_DATA = {
    'detailed_state': 'In Progress',
    'away_abbr': 'NYY',
    'home_abbr': 'BOS',
    'away_id': 147,
    'home_id': 111,
    'away_runs': 3,
    'home_runs': 2,
    'inning_ordinal': '7th',
    'inning_state': 'Top',
    'balls': 2,
    'strikes': 1,
    'outs': 1,
    'batter': {
        'name': 'Aaron Judge',
        'stats': {},
        'season': {'avg': '.301', 'homeRuns': 28, 'rbi': 61},
    },
    'pitcher': {
        'name': 'Brayan Bello',
        'stats': {'inningsPitched': '6.0', 'strikeOuts': 5},
        'season': {'era': '3.85'},
    },
    'pitches': [
        {'seq': 1, 'px': -0.9, 'pz': 2.8, 'code': 'B', 'call': 'B', 'pitch_type': 'Four-Seam Fastball', 'speed': 96.4},
        {'seq': 2, 'px': 0.3, 'pz': 3.6, 'code': 'B', 'call': 'B', 'pitch_type': 'Sinker', 'speed': 94.1},
        {'seq': 3, 'px': -0.1, 'pz': 2.4, 'code': 'C', 'call': 'C', 'pitch_type': 'Slider', 'speed': 84.7},
        {'seq': 4, 'px': 0.6, 'pz': 1.9, 'code': 'F', 'call': 'F', 'pitch_type': 'Changeup', 'speed': 87.2},
    ],
}


def main():
    parser = argparse.ArgumentParser(description='Render pitch view from example data')
    parser.add_argument('--output', default=_DEFAULT_OUTPUT)
    parser.add_argument('--dark', action='store_true')
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()

    image = render_pitch_view(EXAMPLE_DATA, dark_mode=args.dark)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    image.save(args.output)
    print(f"Image saved to {args.output}")

    if args.open:
        image.show()


if __name__ == '__main__':
    main()
