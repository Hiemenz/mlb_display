#!/usr/bin/env python3
"""Download MLB team logos and save them to pic/logos/{ABBR}.png.

Logos are fetched from ESPN's CDN as ~500 px PNGs (dark variant = dark graphic
on transparent background, which renders well on a white e-ink display).
generate_image.py resizes them automatically at render time.

Usage (run from the repo root):
    python3 src/download_logos.py

Requires at least one prior run of the scoreboard so data/teams.json exists,
OR pass --fetch-teams to download the team list from the MLB Stats API first.
"""

import os
import sys
import json
import argparse
import urllib.request

# Some ESPN abbreviations differ from the MLB Stats API abbreviations
ESPN_ABBR_OVERRIDES = {
    'AZ':  'ari',   # Arizona Diamondbacks
    'CWS': 'chw',   # Chicago White Sox
    'WSH': 'wsh',   # Washington Nationals
}

ESPN_LOGO_URL_DARK   = 'https://a.espncdn.com/i/teamlogos/mlb/500-dark/{abbr}.png'
ESPN_LOGO_URL_NORMAL = 'https://a.espncdn.com/i/teamlogos/mlb/500/{abbr}.png'

MLB_TEAMS_API = (
    'https://statsapi.mlb.com/api/v1/teams'
    '?sportId=1&season=2025&fields=teams,id,abbreviation'
)


def fetch_team_list():
    """Return {team_id_str: abbr} from the MLB Stats API."""
    req = urllib.request.Request(MLB_TEAMS_API, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    return {str(t['id']): t['abbreviation'] for t in data.get('teams', [])}


def load_local_team_list(root):
    teams_path = os.path.join(root, 'data', 'teams.json')
    if not os.path.exists(teams_path):
        return None
    with open(teams_path) as f:
        data = json.load(f)
    return data.get('team_abbreviation', {})


def _load_render_config(root):
    config_path = os.path.join(root, 'pic', 'logo_render_config.json')
    try:
        with open(config_path) as f:
            return json.load(f)
    except Exception:
        return {}


def download_logos(abbr_map, logodir, render_config=None):
    os.makedirs(logodir, exist_ok=True)
    success, failed = 0, []
    non_dark = set((render_config or {}).get('non_dark', []))

    for team_id, abbr in sorted(abbr_map.items(), key=lambda x: x[1]):
        espn_abbr = ESPN_ABBR_OVERRIDES.get(abbr, abbr.lower())
        url_template = ESPN_LOGO_URL_NORMAL if abbr in non_dark else ESPN_LOGO_URL_DARK
        url = url_template.format(abbr=espn_abbr)
        dest = os.path.join(logodir, f'{abbr}.png')

        if os.path.exists(dest):
            print(f'  {abbr:<4} already exists — skipping')
            success += 1
            continue

        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data_bytes = resp.read()
            with open(dest, 'wb') as f:
                f.write(data_bytes)
            print(f'  {abbr:<4} saved  ({len(data_bytes) // 1024} KB)')
            success += 1
        except Exception as e:
            print(f'  {abbr:<4} FAILED — {e}')
            failed.append(abbr)

    print(f'\nDone: {success} logo(s) in {logodir}')
    if failed:
        print(f'Failed ({len(failed)}): {", ".join(failed)}')
        print('Add missing logos manually as pic/logos/{ABBR}.png')
        print('The scoreboard falls back to text abbreviations for any missing file.')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--fetch-teams', action='store_true',
                        help='Fetch team list from MLB Stats API instead of data/teams.json')
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    logodir = os.path.join(root, 'pic', 'logos')

    if args.fetch_teams:
        print('Fetching team list from MLB Stats API…')
        try:
            abbr_map = fetch_team_list()
            print(f'  Found {len(abbr_map)} teams')
        except Exception as e:
            print(f'ERROR fetching team list: {e}')
            sys.exit(1)
    else:
        abbr_map = load_local_team_list(root)
        if not abbr_map:
            print(
                'ERROR: data/teams.json not found or empty.\n'
                'Run the scoreboard at least once first, or use --fetch-teams.'
            )
            sys.exit(1)
        print(f'Loaded {len(abbr_map)} teams from data/teams.json')

    render_config = _load_render_config(root)
    print(f'Downloading logos to {logodir} …\n')
    download_logos(abbr_map, logodir, render_config)


if __name__ == '__main__':
    main()
