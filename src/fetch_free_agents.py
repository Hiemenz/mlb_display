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
when the text happens to carry it, else from the MLB Trade Rumors transactions
feed (an article naming the player with an "N-year ... $X" pair). Moves still
without terms are re-checked against the feed on every poll, since the article
often lands hours after the transaction. No terms leaves None; the renderer
then shows only "SIGNED" / "RE-SIGNED".

Each entry carries `seen_at`, the time it was first fetched (None for the very
first population, so a fresh install doesn't flag everything as breaking). Pass
the previous data as `previous=` to reuse already-processed entries and skip
re-fetching people: a 15-minute poll then costs one transactions call plus one
people call per genuinely new move.

Writes data/free_agents.json.
"""
import html
import re
import unicodedata
import xml.etree.ElementTree as ET
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


_WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
          'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}
_YEARS = r'(\d+|one|two|three|four|five|six|seven|eight|nine|ten)[- ]year'
_MONEY = r'\$\s?([\d.,]+)\s?(million|billion|mm|m|b)\b'
_NEWS_URL = 'https://www.mlbtraderumors.com/category/transactions/feed'
_TERMS_PAIR = re.compile(_YEARS + r'[^.$]{0,80}?' + _MONEY, re.I)


def _format_terms(years, money_num, money_unit):
    parts = []
    if years:
        y = years.lower()
        parts.append(f'{_WORDS.get(y, y)} yr')
    if money_num:
        unit = 'B' if money_unit.lower() in ('billion', 'b') else 'M'
        parts.append(f'${money_num}{unit}')
    return ' / '.join(parts)


def _parse_terms(description):
    """Best-effort contract terms from a transaction description, else None.

    Looks for "$120 million" / "$12M" / "$12MM" and "N-year" / "N years" fragments.
    """
    text = description or ''
    money = re.search(_MONEY, text, re.I)
    years = re.search(_YEARS, text, re.I)
    if not (money or years):
        return None
    return _format_terms(years and years.group(1), money and money.group(1),
                         money.group(2) if money else '')


def _parse_news_terms(text):
    """Terms from a news article body: only an "N-year ... $X" pair counts.

    Articles mention earlier contracts too ("played on a one-year, $12.5MM deal
    with the Cardinals"), so a lone figure is ignored and the first pair wins.
    """
    m = _TERMS_PAIR.search(text or '')
    return _format_terms(m.group(1), m.group(2), m.group(3)) if m else None


def _norm(text):
    text = unicodedata.normalize('NFKD', text or '')
    return re.sub(r'[^a-z ]', '', ''.join(c for c in text if not unicodedata.combining(c)).lower().replace('.', ''))


def _fetch_news(url=_NEWS_URL):
    """Recent MLB Trade Rumors transaction articles as [{'title', 'body'}], [] on failure."""
    try:
        resp = requests.get(url, timeout=15, headers={'User-Agent': 'mlb-display'})
        if resp.status_code != 200:
            print(f'Warning: terms feed returned {resp.status_code}')
            return []
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f'Error fetching terms feed: {e}')
        return []
    ns = {'c': 'http://purl.org/rss/1.0/modules/content/'}
    items = []
    for it in root.iter('item'):
        raw = it.findtext('c:encoded', default='', namespaces=ns) or it.findtext('description') or ''
        body = html.unescape(re.sub(r'<[^>]+>', ' ', raw))
        items.append({'title': html.unescape(it.findtext('title') or ''), 'body': ' '.join(body.split())})
    return items


def _lookup_terms(player_name, description, news=()):
    """Terms from the transaction description, else from a news article naming the player."""
    found = _parse_terms(description)
    if found and ' / ' in found:
        return found
    name = _norm(player_name)
    for item in news:
        title = item['title'].lower()
        if not name or name not in _norm(item['title']) or 'minor league' in title or 'acquire' in title:
            continue
        terms = _parse_news_terms(item['body'])
        if terms:
            return terms
    return found


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
    news = None                          # fetched lazily, at most once per poll

    def terms_for(name, description):
        nonlocal news
        if news is None:
            news = _fetch_news()
        return _lookup_terms(name, description, news)

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
            move = known[key]
            if not trade and not move.get('terms'):
                move = dict(move, terms=terms_for(move.get('player_name', ''), move.get('description', '')))
            signings.append(move)
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
            'terms':       None if trade else terms_for((tx.get('person') or {}).get('fullName', ''), tx.get('description', '')),
            'description': tx.get('description', ''),
        })

    data = {'fetched_at': time.time(), 'lookback_days': lookback_days,
            'signings': signings,
            'skipped': skipped}
    save_off_results(data, 'free_agents')
    return data
