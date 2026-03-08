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

ESPN_LOGO_URL_DARK      = 'https://a.espncdn.com/i/teamlogos/mlb/500-dark/{abbr}.png'
ESPN_LOGO_URL_NORMAL    = 'https://a.espncdn.com/i/teamlogos/mlb/500/{abbr}.png'
ESPN_COUNTRIES_LOGO_URL = 'https://a.espncdn.com/i/teamlogos/countries/500/{abbr}.png'

# WBC teams with their ESPN countries CDN abbreviations (lowercase).
# Key = MLB abbreviation used in the API, Value = ESPN countries path abbreviation.
WBC_ESPN_ABBR = {
    'USA': 'usa', 'DOM': 'dom', 'JPN': 'jpn', 'MEX': 'mex', 'KOR': 'kor',
    'PUR': 'pur', 'CUB': 'cub', 'AUS': 'aus', 'NED': 'ned', 'ITA': 'ita',
    'CAN': 'can', 'VEN': 'ven', 'PAN': 'pan', 'CLM': 'col', 'GBR': 'gbr',
    'ISR': 'isr', 'CZE': 'cze', 'NIC': 'nic', 'TPE': 'tpe', 'CHN': 'chn',
}

MLB_TEAMS_API = (
    'https://statsapi.mlb.com/api/v1/teams'
    '?sportId={sport_id}&fields=teams,id,abbreviation'
)


def fetch_team_list(sport_id=1):
    """Return {team_id_str: abbr} from the MLB Stats API."""
    url = MLB_TEAMS_API.format(sport_id=sport_id)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
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


def download_logos(abbr_map, logodir, render_config=None, sport_id=1):
    os.makedirs(logodir, exist_ok=True)
    success, failed = 0, []
    non_dark = set((render_config or {}).get('non_dark', []))
    is_wbc = sport_id == 8

    for team_id, abbr in sorted(abbr_map.items(), key=lambda x: x[1]):
        dest = os.path.join(logodir, f'{abbr}.png')

        if os.path.exists(dest):
            print(f'  {abbr:<4} already exists — skipping')
            success += 1
            continue

        urls_to_try = []
        if is_wbc:
            countries_abbr = WBC_ESPN_ABBR.get(abbr.upper(), abbr.lower())
            urls_to_try.append(ESPN_COUNTRIES_LOGO_URL.format(abbr=countries_abbr))
        # Always try MLB CDN as fallback (some WBC teams are also MLB)
        espn_abbr = ESPN_ABBR_OVERRIDES.get(abbr, abbr.lower())
        url_template = ESPN_LOGO_URL_NORMAL if abbr in non_dark else ESPN_LOGO_URL_DARK
        urls_to_try.append(url_template.format(abbr=espn_abbr))

        saved = False
        for url in urls_to_try:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data_bytes = resp.read()
                with open(dest, 'wb') as f:
                    f.write(data_bytes)
                print(f'  {abbr:<4} saved  ({len(data_bytes) // 1024} KB)  [{url}]')
                success += 1
                saved = True
                break
            except Exception as e:
                print(f'  {abbr:<4} try failed: {url} — {e}')

        if not saved:
            print(f'  {abbr:<4} FAILED — all URLs exhausted')
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
    parser.add_argument('--sport-id', type=int, default=1,
                        help='Sport ID to fetch logos for (1=MLB, 8=WBC, etc.). Default: 1')
    parser.add_argument('--wbc', action='store_true',
                        help='Shortcut for --sport-id 8 --fetch-teams (download WBC logos)')
    args = parser.parse_args()

    if args.wbc:
        args.sport_id = 8

    root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    logodir = os.path.join(root, 'pic', 'logos')

    sport_names = {1: 'MLB', 8: 'World Baseball Classic', 11: 'College Baseball',
                   12: 'Triple-A', 13: 'Double-A', 14: 'Winter Leagues', 16: 'Spring Training'}
    sport_name = sport_names.get(args.sport_id, f'Sport {args.sport_id}')

    if args.sport_id == 8:
        # WBC: use hardcoded team list (MLB API doesn't expose WBC teams outside active seasons)
        abbr_map = {str(i): abbr for i, abbr in enumerate(WBC_ESPN_ABBR.keys(), 1)}
        print(f'Using hardcoded WBC team list ({len(abbr_map)} teams)')
    elif args.fetch_teams:
        print(f'Fetching {sport_name} team list from MLB Stats API…')
        try:
            abbr_map = fetch_team_list(args.sport_id)
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
    print(f'Downloading {sport_name} logos to {logodir} …\n')
    download_logos(abbr_map, logodir, render_config, sport_id=args.sport_id)


if __name__ == '__main__':
    main()
