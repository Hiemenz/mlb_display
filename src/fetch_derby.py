"""
Fetch live Home Run Derby bracket data from the MLB Stats API and write
data/derby_bracket.json in the shape image_derby.render_derby_bracket() expects.

There's no dedicated "derby" entry in the regular schedule/gameType endpoints —
the event lives in the non-game "events" calendar (scheduleTypes=events) under
a name like "<year> MLB All-Star Workout Day: Home Run Derby", and its bracket
is served by GET /api/v1/homeRunDerby/{event_id}/bracket once the event starts.

Standalone CLI:
    python src/fetch_derby.py [--season 2026] [--event-id 838655]
"""
import argparse
import re
import sys
import os
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util import save_off_results
from config_loader import load_config, add_config_arg

_STATS_API = 'https://statsapi.mlb.com/api/v1'
_DERBY_NAME_RE = re.compile(r'All-Star Workout Day: Home Run Derby', re.IGNORECASE)


def _find_asg_date(season):
    """Return the All-Star Game's officialDate string for a season, or None."""
    resp = requests.get(f'{_STATS_API}/schedule', params={
        'sportId': 1, 'gameType': 'A', 'season': season,
    }, timeout=10)
    resp.raise_for_status()
    for day in resp.json().get('dates', []):
        for game in day.get('games', []):
            if game.get('gameType') == 'A':
                return game.get('officialDate')
    return None


def find_derby_event_id(season):
    """Locate this season's Home Run Derby non-game event id.

    Searches the events calendar on and around the day before the All-Star
    Game (where the Derby is traditionally held) for an event named
    "<year> MLB All-Star Workout Day: Home Run Derby".
    """
    asg_date_str = _find_asg_date(season)
    if not asg_date_str:
        return None, None

    asg_date = datetime.strptime(asg_date_str, '%Y-%m-%d')
    for offset in (1, 2, 3):  # derby is usually 1 day before ASG; scan a small window
        candidate = (asg_date - timedelta(days=offset)).strftime('%Y-%m-%d')
        resp = requests.get(f'{_STATS_API}/schedule', params={
            'sportId': 1, 'date': candidate, 'scheduleTypes': 'events',
        }, timeout=10)
        resp.raise_for_status()
        for day in resp.json().get('dates', []):
            for event in day.get('events', []):
                if _DERBY_NAME_RE.search(event.get('name', '')):
                    return event.get('id'), candidate
    return None, None


def fetch_derby_bracket_raw(event_id):
    """GET the raw homeRunDerby bracket payload for an event id, or None."""
    resp = requests.get(f'{_STATS_API}/homeRunDerby/{event_id}/bracket', timeout=10)
    if resp.status_code != 200:
        return None
    data = resp.json()
    if 'rounds' not in data:
        return None
    return data


def _team_abbr_by_player_id(raw):
    return {
        p['id']: p.get('currentTeam', {}).get('abbreviation', '')
        for p in raw.get('players', [])
    }


def _short_name(full_name):
    """'Cal Raleigh' -> 'C. Raleigh'."""
    parts = full_name.split(' ', 1)
    if len(parts) != 2:
        return full_name
    first, last = parts
    return f'{first[0]}. {last}'


def _seed_to_player(seed, team_abbr):
    if not seed or not seed.get('player'):
        return {'name': 'TBD', 'abbr': '', 'hr': None, 'winner': False}
    player = seed['player']
    return {
        'name': _short_name(player.get('fullName', 'TBD')),
        'abbr': team_abbr.get(player.get('id'), ''),
        'hr': seed.get('numHomeRuns') if seed.get('started') else None,
        'winner': bool(seed.get('winner')),
    }


def _matchup_complete(matchup):
    top, bottom = matchup.get('topSeed'), matchup.get('bottomSeed')
    return bool(top and top.get('complete') and bottom and bottom.get('complete'))


def transform_bracket(raw, event_date):
    """Convert the raw MLB Stats API bracket payload into our derby_bracket.json shape."""
    team_abbr = _team_abbr_by_player_id(raw)
    rounds = sorted(raw.get('rounds', []), key=lambda r: r['round'])

    def _round_matchups(round_data):
        if not round_data:
            return []
        return [
            {
                'complete': _matchup_complete(m),
                'players': [
                    _seed_to_player(m.get('topSeed'), team_abbr),
                    _seed_to_player(m.get('bottomSeed'), team_abbr),
                ],
            }
            for m in round_data.get('matchups', [])
        ]

    qf = _round_matchups(rounds[0] if len(rounds) > 0 else None)
    sf = _round_matchups(rounds[1] if len(rounds) > 1 else None)
    final_list = _round_matchups(rounds[2] if len(rounds) > 2 else None)
    final = final_list[0] if final_list else {
        'complete': False,
        'players': [
            {'name': 'TBD', 'abbr': '', 'hr': None, 'winner': False},
            {'name': 'TBD', 'abbr': '', 'hr': None, 'winner': False},
        ],
    }

    # Pad qf/sf out to the expected slot counts with TBD placeholders so
    # render_derby_bracket always has 4 qf / 2 sf entries to lay out.
    _tbd_matchup = {
        'complete': False,
        'players': [
            {'name': 'TBD', 'abbr': '', 'hr': None, 'winner': False},
            {'name': 'TBD', 'abbr': '', 'hr': None, 'winner': False},
        ],
    }
    while len(qf) < 4:
        qf.append(dict(_tbd_matchup))
    while len(sf) < 2:
        sf.append(dict(_tbd_matchup))

    status = raw.get('status', {})
    state = status.get('state', '')
    current_round = status.get('currentRound')
    round_status = f'Round {current_round} - {state}' if current_round else state

    champion = None
    for p in final.get('players', []):
        if p.get('winner'):
            champion = p.get('name')

    return {
        'event_date': event_date,
        'round_status': round_status,
        'matchups': {'qf': qf, 'sf': sf, 'final': final},
        'champion': champion,
    }


def fetch_and_save_derby_bracket(season=None, event_id=None):
    """Fetch the live derby bracket and write data/derby_bracket.json. Returns the saved dict or None."""
    if season is None:
        season = datetime.now().year

    event_date = None
    if event_id is None:
        event_id, event_date = find_derby_event_id(season)
        if event_id is None:
            print(f'No Home Run Derby event found for season {season}')
            return None

    raw = fetch_derby_bracket_raw(event_id)
    if raw is None:
        print(f'No derby bracket data yet for event {event_id} (event may not have started)')
        return None

    if event_date is None:
        event_date = raw.get('info', {}).get('eventDate', '')[:10]

    result = transform_bracket(raw, event_date)
    save_off_results(result, 'derby_bracket')
    print(f'Derby bracket saved: {result["round_status"]}')
    return result


def main():
    parser = argparse.ArgumentParser(description='Fetch live Home Run Derby bracket data')
    parser.add_argument('--season', type=int, default=None, help='Season year (default: current year)')
    parser.add_argument('--event-id', type=int, default=None, help='Derby event id override (skip lookup)')
    add_config_arg(parser)
    args = parser.parse_args()

    load_config(args.config)  # validated for CLI consistency with other fetch_* scripts
    result = fetch_and_save_derby_bracket(season=args.season, event_id=args.event_id)
    if not result:
        sys.exit(1)


if __name__ == '__main__':  # pragma: no cover
    main()
