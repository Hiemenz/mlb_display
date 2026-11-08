"""Fetch recent major-league free-agent signings and trades for the off-season screen.

The transactions API lists every "Signed as Free Agent" move, minor-league
deals included. We keep only major-league signings of players with real MLB
experience, and enrich each with the team they are leaving (from their
year-by-year stats) and, when available, the contract terms.

Trades ('TR') are included too, as entries with kind='trade'. The API emits
each trade as a mirrored pair of records whose from/to fields disagree, so
they are de-duplicated per player/date and the direction is read from the
description ("<from team> traded <pos> <name> to <to team> ...").

Contract terms are NOT in MLB's API. `terms` is parsed from the description
when the text happens to carry it ("... to a one-year contract worth $X") and
is otherwise None; the renderer then shows only "SIGNED". A news source can
be plugged in later by filling `terms` from `_lookup_terms`.

Each entry carries `seen_at`, the time it was first fetched (None for the very
first population, so a fresh install doesn't flag everything as breaking). Pass
the previous data as `previous=` to reuse already-processed entries and skip
re-fetching people: a 15-minute poll then costs one transactions call plus one
people call per genuinely new move.

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


def _is_trade(tx):
    return tx.get('typeCode') == 'TR'


def _trade_teams(tx):
    """(from_team, to_team) dicts for a trade record, direction from the description.

    The first team named at the start of the description is the one that gave
    the player up. Falls back to the record's own fromTeam/toTeam.
    """
    a, b = tx.get('fromTeam') or {}, tx.get('toTeam') or {}
    desc = tx.get('description') or ''
    for giver, other in ((a, b), (b, a)):
        if giver.get('name') and desc.startswith(giver['name'] + ' traded'):
            return giver, other
    return a, b


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


def _key(tx, trade):
    return f"{(tx.get('person') or {}).get('id')}:{tx.get('date')}:{'trade' if trade else 'signing'}"


def fetch_free_agents(lookback_days=21, min_mlb_days=_MIN_MLB_DAYS, today=None,
                      include_trades=True, previous=None):
    """Fetch and save recent major-league free-agent signings (and trades).

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

    prev = previous or {}
    known = {f"{m.get('player_id')}:{m.get('date')}:{m.get('kind', 'signing')}": m
             for m in prev.get('signings') or []}
    skipped_prev = set(prev.get('skipped') or [])
    now_ts = time.time()
    skipped = []
    wanted = [t for t in txs if _is_major_league_signing(t) or (include_trades and _is_trade(t))]
    signings, seen = [], set()
    for tx in sorted(wanted, key=lambda t: t.get('date', ''), reverse=True):
        pid = (tx.get('person') or {}).get('id')
        trade = _is_trade(tx)
        if trade:
            from_team, to_team = _trade_teams(tx)
            if (pid, tx.get('date')) in seen:
                continue
            seen.add((pid, tx.get('date')))
        else:
            from_team, to_team = None, tx.get('toTeam') or {}
        if not pid or not to_team or (trade and not from_team):
            continue
        key = _key(tx, trade)
        if key in known:                 # already processed on an earlier poll
            signings.append(known[key])
            continue
        if key in skipped_prev:
            skipped.append(key)
            continue
        person = _fetch_person(pid)
        if not person:
            continue                     # transient failure: retry next poll
        if not _experienced(person, today, min_mlb_days):
            skipped.append(key)
            continue
        if trade:
            from_id, from_name = from_team.get('id'), from_team.get('name')
        else:
            from_id, from_name = _previous_team(person)
        signings.append({
            'kind':        'trade' if trade else 'signing',
            'seen_at':     now_ts if prev else None,
            'player_id':   pid,
            'player_name': (tx.get('person') or {}).get('fullName', ''),
            'position':    (person.get('primaryPosition') or {}).get('abbreviation', ''),
            'date':        tx.get('date', ''),
            'from_team_id':   str(from_id) if from_id else '',
            'from_team_name': from_name or '',
            'to_team_id':     str(to_team.get('id', '')),
            'to_team_name':   to_team.get('name', ''),
            'terms':       None if trade else _lookup_terms(pid, tx.get('description', '')),
            'description': tx.get('description', ''),
        })

    data = {'fetched_at': time.time(), 'lookback_days': lookback_days,
            'signings': signings,
            'skipped': skipped}
    save_off_results(data, 'free_agents')
    return data
