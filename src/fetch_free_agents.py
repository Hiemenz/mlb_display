"""Fetch recent major-league free-agent signings for the off-season screen.

The transactions API lists every "Signed as Free Agent" move, minor-league
deals included. We keep only major-league signings of players with real MLB
experience, and enrich each with the team they are leaving (from their
year-by-year stats) and, when available, the contract terms.

Contract terms are NOT in MLB's API. `terms` is parsed from the description
when the text happens to carry it ("... to a one-year contract worth $X") and
is otherwise None; the renderer then shows only "SIGNED". A news source can
be plugged in later by filling `terms` from `_lookup_terms`.

Writes data/free_agents.json.
"""
import re
import time
from datetime import datetime, timedelta

import requests

from util import save_off_results

_API = 'https://statsapi.mlb.com/api/v1'
_MIN_MLB_DAYS = 180   # "at least ~6 months of MLB experience", measured from debut


def _is_major_league_signing(tx):
    """An SFA record whose description does not say minor league."""
    return (tx.get('typeCode') == 'SFA'
            and 'minor league' not in (tx.get('description') or '').lower())


def _parse_terms(description):
    """Best-effort contract terms from a transaction description, else None.

    Looks for "$120 million" / "$12M" and "N-year" / "N years" fragments.
    """
    text = description or ''
    money = re.search(r'\$\s?([\d.,]+)\s?(million|m|billion|b)\b', text, re.I)
    years = re.search(r'(\d+|one|two|three|four|five|six|seven|eight|nine|ten)[- ]year', text, re.I)
    if not (money or years):
        return None
    words = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
             'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}
    parts = []
    if years:
        y = years.group(1).lower()
        parts.append(f'{words.get(y, y)} yr')
    if money:
        unit = 'B' if money.group(2).lower() in ('billion', 'b') else 'M'
        parts.append(f'${money.group(1)}{unit}')
    return ' / '.join(parts)


def _lookup_terms(player_id, description):
    """Hook for an external contract-terms source. Today: description only."""
    return _parse_terms(description)


def _experienced(person, today, min_days=_MIN_MLB_DAYS):
    """True when the player debuted in MLB at least `min_days` ago."""
    debut = person.get('mlbDebutDate')
    if not debut:
        return False
    try:
        return (today - datetime.strptime(debut, '%Y-%m-%d')).days >= min_days
    except ValueError:
        return False


def _previous_team(person):
    """(id, name) of the last MLB team in the player's year-by-year stats."""
    last = None
    for group in person.get('stats') or []:
        for split in group.get('splits') or []:
            team = split.get('team')
            if team and (split.get('sport') or {}).get('id') == 1:
                key = split.get('season', '')
                if last is None or key >= last[0]:
                    last = (key, team)
    if last is None:
        return None, None
    return last[1].get('id'), last[1].get('name')


def _fetch_person(player_id):
    """Hydrated person record, or None on any failure."""
    url = (f'{_API}/people/{player_id}'
           f'?hydrate=stats(group=[hitting,pitching],type=[yearByYear])')
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None
        people = resp.json().get('people') or []
        return people[0] if people else None
    except Exception as e:
        print(f'Warning: free-agent person fetch failed for {player_id}: {e}')
        return None


def fetch_free_agents(lookback_days=21, min_mlb_days=_MIN_MLB_DAYS, today=None):
    """Fetch and save recent major-league free-agent signings.

    Newest first. Returns the saved dict, or None when the API call fails.
    """
    today = today or datetime.now()
    start = today - timedelta(days=lookback_days)
    url = (f'{_API}/transactions?sportId=1&startDate={start:%Y-%m-%d}'
           f'&endDate={today:%Y-%m-%d}')
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            print(f'Warning: free-agent fetch returned {resp.status_code}')
            return None
        txs = resp.json().get('transactions', [])
    except Exception as e:
        print(f'Error fetching free agents: {e}')
        return None

    signings = []
    for tx in sorted((t for t in txs if _is_major_league_signing(t)),
                     key=lambda t: t.get('date', ''), reverse=True):
        pid = (tx.get('person') or {}).get('id')
        to_team = tx.get('toTeam') or {}
        if not pid or not to_team:
            continue
        person = _fetch_person(pid)
        if not person or not _experienced(person, today, min_mlb_days):
            continue
        from_id, from_name = _previous_team(person)
        signings.append({
            'player_id':   pid,
            'player_name': (tx.get('person') or {}).get('fullName', ''),
            'position':    (person.get('primaryPosition') or {}).get('abbreviation', ''),
            'date':        tx.get('date', ''),
            'from_team_id':   str(from_id) if from_id else '',
            'from_team_name': from_name or '',
            'to_team_id':     str(to_team.get('id', '')),
            'to_team_name':   to_team.get('name', ''),
            'terms':       _lookup_terms(pid, tx.get('description', '')),
            'description': tx.get('description', ''),
        })

    data = {'fetched_at': time.time(), 'lookback_days': lookback_days,
            'signings': signings}
    save_off_results(data, 'free_agents')
    return data
