"""Per-player stats for the current series, summed from each game's boxscore.

The Stats API has no series-stats endpoint, so this finds the series' games on
the schedule, reads each boxscore, and adds the lines up. A finished game never
changes, so its summary is cached on disk (``data/series_stats_cache.json``)
and fetched once; the in-progress game, if any, is fetched fresh each call and
never cached. Cache entries are dropped ``_KEEP_DAYS`` after the game was played.

    series_stats(game_data) -> {'games': n, 'teams': {team_id: {'batters': [...], 'pitchers': [...]}}}
"""
from datetime import date, datetime, timedelta

import requests

from util import load_json_file, save_off_results

_API = 'https://statsapi.mlb.com/api/v1'
_CACHE_FILE = 'series_stats_cache'
_KEEP_DAYS = 7
_FINAL_STATES = ('Final', 'Game Over', 'Final: Tied')
_BAT_FIELDS = ('atBats', 'runs', 'hits', 'homeRuns', 'rbi', 'baseOnBalls', 'strikeOuts')
_PITCH_FIELDS = ('earnedRuns', 'hits', 'baseOnBalls', 'strikeOuts', 'wins', 'losses', 'saves')


def _innings_to_outs(ip):
    """'5.2' (five and two-thirds) -> 17 outs."""
    whole, _, frac = str(ip or '0').partition('.')
    return int(whole or 0) * 3 + int(frac or 0)


def outs_to_innings(outs):
    """17 outs -> '5.2'."""
    return f'{outs // 3}.{outs % 3}'


def _summarize_boxscore(box):
    """Reduce a boxscore to {team_id: {'batters': {pid: line}, 'pitchers': {pid: line}}}.

    Only players who batted or pitched are kept, and only the fields the
    display uses, so cached games stay small.
    """
    out = {}
    for side in ('away', 'home'):
        team = (box.get('teams') or {}).get(side) or {}
        batters, pitchers = {}, {}
        for p in (team.get('players') or {}).values():
            pid = str((p.get('person') or {}).get('id', ''))
            name = (p.get('person') or {}).get('fullName', '')
            stats = p.get('stats') or {}
            bat, pit = stats.get('batting') or {}, stats.get('pitching') or {}
            if bat.get('atBats') or bat.get('baseOnBalls') or bat.get('plateAppearances'):
                batters[pid] = {'name': name, **{f: int(bat.get(f) or 0) for f in _BAT_FIELDS}}
            if pit.get('inningsPitched') not in (None, '', '0.0') or pit.get('battersFaced'):
                pitchers[pid] = {'name': name,
                                 'outs': _innings_to_outs(pit.get('inningsPitched')),
                                 **{f: int(pit.get(f) or 0) for f in _PITCH_FIELDS}}
        out[str((team.get('team') or {}).get('id', side))] = {'batters': batters, 'pitchers': pitchers}
    return out


def series_game_pks(away_id, home_id, game_date, game_number):
    """(pk, state, date) for each game of the series up to and including this one, oldest first.

    ``game_date`` is the date of the game being shown and ``game_number`` its
    place in the series; the window looks back far enough to cover a series
    that was split by a postponement.
    """
    day = datetime.fromisoformat(game_date[:10]).date()
    params = {'sportId': 1, 'teamId': home_id, 'opponentId': away_id,
              'startDate': str(day - timedelta(days=game_number + 3)), 'endDate': str(day)}
    resp = requests.get(f'{_API}/schedule', params=params, timeout=10)
    games = [g for d in resp.json().get('dates', []) for g in d.get('games', [])
             if (g.get('teams', {}).get('home', {}).get('team', {}).get('id') == home_id)]
    games.sort(key=lambda g: g.get('gameDate', ''))
    games = [g for g in games if (g.get('seriesGameNumber') or 0) <= game_number][-game_number:]
    return [(g['gamePk'], g.get('status', {}).get('detailedState', ''), g.get('officialDate', str(day)))
            for g in games]


def _fetch_boxscore(pk):
    resp = requests.get(f'{_API}/game/{pk}/boxscore', timeout=10)
    return _summarize_boxscore(resp.json())


def _add_up(per_game):
    """Sum a list of per-game summaries into per-team lists, best performers first."""
    teams = {}
    for game in per_game:
        for tid, lines in game.items():
            t = teams.setdefault(tid, {'batters': {}, 'pitchers': {}})
            for kind, fields in (('batters', _BAT_FIELDS), ('pitchers', ('outs',) + _PITCH_FIELDS)):
                for pid, line in lines[kind].items():
                    acc = t[kind].setdefault(pid, {'name': line['name'], **{f: 0 for f in fields}})
                    for f in fields:
                        acc[f] += line[f]
    out = {}
    for tid, t in teams.items():
        batters = [{**b, 'avg': b['hits'] / b['atBats'] if b['atBats'] else 0.0} for b in t['batters'].values()]
        pitchers = [{**p, 'ip': outs_to_innings(p['outs']),
                     'era': p['earnedRuns'] * 27 / p['outs'] if p['outs'] else 0.0}
                    for p in t['pitchers'].values()]
        batters.sort(key=lambda b: (b['homeRuns'], b['rbi'], b['hits']), reverse=True)
        pitchers.sort(key=lambda p: (p['outs'], p['strikeOuts']), reverse=True)
        out[tid] = {'batters': batters, 'pitchers': pitchers}
    return out


def series_stats(game_data):
    """Series-to-date stats for the series ``game_data`` belongs to, or None if it can't be built.

    Needs ``away_team_id``, ``home_team_id``, ``game_date`` and
    ``series_game_number`` on ``game_data`` (all set by ``fetch_games``).
    """
    try:
        away, home = int(game_data['away_team_id']), int(game_data['home_team_id'])
        number = int(game_data.get('series_game_number') or 1)
        pks = series_game_pks(away, home, game_data['game_date'], number)
        cache = load_json_file(f'{_CACHE_FILE}.json') or {}
        per_game, dirty = [], False
        for pk, state, played in pks:
            if state in _FINAL_STATES and str(pk) in cache:
                per_game.append(cache[str(pk)]['teams'])
                continue
            if state not in _FINAL_STATES and state not in ('In Progress',):
                continue    # not played yet
            teams = _fetch_boxscore(pk)
            per_game.append(teams)
            if state in _FINAL_STATES:
                cache[str(pk)] = {'played': played, 'teams': teams}
                dirty = True
        if dirty:
            cutoff = (date.today() - timedelta(days=_KEEP_DAYS)).isoformat()
            for stale in [k for k, v in cache.items() if v.get('played', '') < cutoff]:
                del cache[stale]
            save_off_results(cache, _CACHE_FILE)
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        print(f'series_stats: {e}')
        return None
    return {'games': len(per_game), 'teams': _add_up(per_game)}
