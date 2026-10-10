"""Fetch data for the idle (no-games-today) screens: history and next game day."""
import random
import time
from datetime import datetime, timedelta

import requests

from util import POSTSEASON_GAME_TYPES, load_json_file, save_off_results


_MLB_SEASON_START_MONTH = 4   # April
_MLB_SEASON_END_MONTH   = 10  # October


def _random_past_date(today_str):
    """Return a random past date in the MLB season, 1-8 years before today_str."""
    today = datetime.strptime(today_str, '%Y-%m-%d').date()
    for _ in range(50):
        years_back = random.randint(1, 8)
        day_offset = random.randint(-14, 14)
        try:
            candidate = today.replace(year=today.year - years_back) + timedelta(days=day_offset)
        except ValueError:
            continue
        if _MLB_SEASON_START_MONTH <= candidate.month <= _MLB_SEASON_END_MONTH:
            return candidate.strftime('%Y-%m-%d')
    # Fallback: same month/day last year, clamped to season
    fallback = today.replace(year=today.year - 1)
    if not (_MLB_SEASON_START_MONTH <= fallback.month <= _MLB_SEASON_END_MONTH):
        fallback = fallback.replace(month=7, day=4)
    return fallback.strftime('%Y-%m-%d')


def pick_replay_date(today_str, sport_id=1, tries=8, min_games=4):
    """A random past regular-season date that actually had games, or None.

    Candidates come from _random_past_date; each is checked against the
    schedule so a replay is never started on an empty day.
    """
    for _ in range(tries):
        candidate = _random_past_date(today_str)
        try:
            resp = requests.get(
                f'https://statsapi.mlb.com/api/v1/schedule?startDate={candidate}'
                f'&endDate={candidate}&sportId={sport_id}&gameType=R', timeout=10)
            if resp.status_code != 200:
                continue
            dates = resp.json().get('dates', [])
            if dates and len(dates[0].get('games', [])) >= min_games:
                return candidate
        except Exception as e:
            print(f"pick_replay_date {candidate}: {e}")
    return None


def _parse_idle_game(game):
    """Convert a raw schedule API game entry into a minimal draw_box-compatible dict."""
    teams = game.get('teams', {})
    away  = teams.get('away', {})
    home  = teams.get('home', {})
    away_info = away.get('team', {})
    home_info = home.get('team', {})
    linescore = game.get('linescore', {})
    ls_teams  = linescore.get('teams', {})
    ls_away   = ls_teams.get('away', {})
    ls_home   = ls_teams.get('home', {})
    decisions = game.get('decisions', {})
    innings   = linescore.get('innings', [])

    detailed_state = game.get('status', {}).get('detailedState', 'Final')
    # Normalise early-completion variants
    if detailed_state.startswith('Completed Early'):
        detailed_state = 'Final'

    away_runs = ls_away.get('runs') or 0
    home_runs = ls_home.get('runs') or 0
    home_won  = home.get('isWinner', False)

    return {
        'game_pk':               game.get('gamePk'),
        'away_team_id':          away_info.get('id'),
        'home_team_id':          home_info.get('id'),
        'away_team_name':        away_info.get('name'),
        'home_team_name':        home_info.get('name'),
        'away_team_is_winner':   away.get('isWinner'),
        'home_team_is_winner':   home.get('isWinner'),
        'away_runs':             away_runs,
        'home_runs':             home_runs,
        'away_hits':             ls_away.get('hits'),
        'home_hits':             ls_home.get('hits'),
        'away_errors':           ls_away.get('errors'),
        'home_errors':           ls_home.get('errors'),
        'away_inning_runs':      [inn.get('away', {}).get('runs') for inn in innings],
        'home_inning_runs':      [inn.get('home', {}).get('runs') for inn in innings],
        'detailed_state':        detailed_state,
        'winner_name':           decisions.get('winner', {}).get('fullName'),
        'loser_name':            decisions.get('loser', {}).get('fullName'),
        'saver_name':            decisions.get('save', {}).get('fullName'),
        'no_hitter':             game.get('flags', {}).get('noHitter'),
        'perfect_game':          game.get('flags', {}).get('perfectGame'),
        'walk_off':              home_won and home_runs > away_runs,
        'double_header':         None,
        'game_number':           game.get('gameNumber'),
        'series_description':    None,
        'series_game_number':    None,
        'series_total_games':    None,
        'series_wins':           None,
        'series_losses':         None,
        'series_is_tied':        None,
        'series_is_over':        None,
        'series_result':         '',
        'current_inning':        linescore.get('currentInning'),
        'currentInningOrdinal':  linescore.get('currentInningOrdinal'),
        'inningState':           linescore.get('inningState'),
        'num_of_outs':           None,
        'balls':                 None,
        'strikes':               None,
        'runner_on_first':       None,
        'runner_on_second':      None,
        'runner_on_third':       None,
        'current_hitter':        None,
        'due_up':                None,
        'in_hole':               None,
        'current_pitcher':       None,
        'last_play':             None,
        'sub_event':             None,
        'challenge_team_abbr':   None,
        'save_situation':        False,
        'away_team_record_wins':    None,
        'away_team_record_losses':  None,
        'home_team_record_wins':    None,
        'home_team_record_losses':  None,
        'away_probable':         None,
        'home_probable':         None,
        'away_probable_note':    None,
        'home_probable_note':    None,
        'away_left_on_base':     None,
        'home_left_on_base':     None,
        'game_date':             game.get('gameDate'),
        'game_start':            None,
        'day_night':             game.get('dayNight'),
        'description':           game.get('description'),
        'postpone_reason':       None,
        'tv_channel':            None,
        'win_probability':       None,
        'win_prob_home':         None,
        'weather_temp_f':        None,
        'weather_wind_mph':      None,
        'weather_wind_dir':      None,
        'weather_precip_pct':    None,
        'roof_state':            None,
    }


def fetch_this_day_in_history(today_str, sport_id=1, max_games=12):
    """Fetch completed games from today's calendar date (same month/day) in past years.

    Tries years 1–10 in reverse order. Returns (year, game_list) or (None, [])
    when no year produced enough games.
    """
    today = datetime.strptime(today_str, '%Y-%m-%d').date()
    for years_back in range(1, 11):
        target_year = today.year - years_back
        try:
            past_date = today.replace(year=target_year)
        except ValueError:
            continue   # Feb 29 in a non-leap year
        if not (_MLB_SEASON_START_MONTH <= past_date.month <= _MLB_SEASON_END_MONTH):
            continue
        past_str = past_date.strftime('%Y-%m-%d')
        try:
            url = (
                f'https://statsapi.mlb.com/api/v1/schedule?'
                f'startDate={past_str}&endDate={past_str}&sportId={sport_id}'
                '&hydrate=linescore,decisions,flags'
            )
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
            dates = data.get('dates', [])
            if not dates:
                continue
            games = dates[0].get('games', [])
            finals = [
                g for g in games
                if g.get('status', {}).get('detailedState', '').startswith(('Final', 'Completed Early'))
                and g.get('gameType') not in ('S', 'E', 'A')
            ]
            if len(finals) < 4:
                continue
            parsed = [_parse_idle_game(g) for g in finals[:max_games]]
            print(f"History screen: {len(parsed)} games from {past_str}")
            return target_year, parsed
        except Exception as e:
            print(f"fetch_this_day_in_history year={target_year}: {e}")
    return None, []


def fetch_idle_games(today_str, sport_id=1, max_games=5):
    """Fetch completed games from a random past MLB date.

    Returns (date_str, game_list) or (None, []) on failure.
    """
    for attempt in range(8):
        past_str = _random_past_date(today_str)
        try:
            url = (
                f'https://statsapi.mlb.com/api/v1/schedule?'
                f'startDate={past_str}&endDate={past_str}&sportId={sport_id}'
                '&hydrate=linescore,decisions,flags'
            )
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
            dates = data.get('dates', [])
            if not dates:
                continue
            games = dates[0].get('games', [])
            # Filter to regular-season final games only
            finals = [
                g for g in games
                if g.get('status', {}).get('detailedState', '').startswith(('Final', 'Completed Early'))
                and g.get('gameType') not in ('S', 'E', 'A')
            ]
            if len(finals) < 3:
                continue
            random.shuffle(finals)
            parsed = [_parse_idle_game(g) for g in finals[:max_games]]
            print(f"Idle screen: fetched {len(parsed)} historical games from {past_str}")
            return past_str, parsed
        except Exception as e:
            print(f"fetch_idle_games attempt {attempt+1}: {e}")

    return None, []


_NEXT_GAMES_TTL_SECONDS = 3600
_NEXT_GAMES_LOOKAHEAD_DAYS = 30


def _parse_next_game(game):
    """Reduce a raw schedule entry to what the next-games screen draws.

    Series context is kept for postseason games only — "Game 2 of 3" is noise
    in the regular season, but in October it is the whole story.
    """
    teams = game.get('teams', {})
    sides = {}
    for side in ('away', 'home'):
        entry = teams.get(side, {})
        info = entry.get('team', {})
        record = entry.get('leagueRecord') or {}
        wins, losses = record.get('wins'), record.get('losses')
        sides[side] = {
            'id': info.get('id'),
            'abbr': info.get('abbreviation') or '???',
            'record': f'{wins}-{losses}' if wins is not None and losses is not None else None,
            'probable': (entry.get('probablePitcher') or {}).get('fullName'),
        }

    game_type = game.get('gameType')
    series = None
    if game_type in POSTSEASON_GAME_TYPES:
        status = game.get('seriesStatus') or {}
        series = {
            'desc': status.get('shortDescription') or game.get('seriesDescription'),
            'result': status.get('result'),
            'game_number': game.get('seriesGameNumber'),
            'total_games': game.get('gamesInSeries'),
        }

    return {
        'game_pk': game.get('gamePk'),
        'start_utc': game.get('gameDate'),
        'game_type': game_type,
        'venue': (game.get('venue') or {}).get('name'),
        'away': sides['away'],
        'home': sides['home'],
        'series': series,
    }


def fetch_next_game_day(from_date_str, sport_id_priority=(1,),
                        lookahead_days=_NEXT_GAMES_LOOKAHEAD_DAYS):
    """Find the first date on/after ``from_date_str`` with games and return them.

    Walks ``sport_id_priority`` in order and stops at the first sport with games
    in the window, mirroring how the scoreboard picks its league. Spring
    training / exhibition games are dropped when real games share the day.

    Returns ``{'date', 'sport_id', 'games'}`` (games sorted by first pitch) or
    None when nothing is scheduled or the API is unreachable.
    """
    start = datetime.strptime(from_date_str, '%Y-%m-%d').date()
    end_str = (start + timedelta(days=lookahead_days)).strftime('%Y-%m-%d')

    for sid in sport_id_priority:
        url = (
            f'https://statsapi.mlb.com/api/v1/schedule?'
            f'startDate={from_date_str}&endDate={end_str}&sportId={sid}'
            '&hydrate=team,probablePitcher,seriesStatus'
        )
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                print(f"fetch_next_game_day sport={sid}: HTTP {resp.status_code}")
                continue
            for entry in resp.json().get('dates', []):
                games = entry.get('games', [])
                if sid == 1:
                    regular = [g for g in games if g.get('gameType') not in ('S', 'E')]
                    if regular:
                        games = regular
                games = [g for g in games
                         if g.get('status', {}).get('detailedState') not in ('Postponed', 'Cancelled')]
                if not games:
                    continue
                parsed = sorted((_parse_next_game(g) for g in games),
                                key=lambda g: g.get('start_utc') or '')
                print(f"Next games: {len(parsed)} on {entry.get('date')} (sport_id={sid})")
                return {'date': entry.get('date'), 'sport_id': sid, 'games': parsed}
        except Exception as e:
            print(f"fetch_next_game_day sport={sid}: {e}")
    return None


def get_next_game_day(from_date_str, sport_id_priority=(1,), ttl=_NEXT_GAMES_TTL_SECONDS):
    """Cached wrapper around fetch_next_game_day (data/next_games.json).

    The idle screen re-renders every cron tick, so the schedule is only
    refetched once the cache is stale or no longer starts on/after the
    requested date. A failed refetch falls back to the last cached copy as
    long as it is still in the future — a stale schedule beats a blank panel.
    """
    cached = load_json_file('next_games.json') or {}
    fresh = time.time() - cached.get('fetched_at', 0) <= ttl
    usable = bool(cached.get('games')) and (cached.get('date') or '') >= from_date_str
    if usable and fresh and cached.get('from_date') == from_date_str:
        return cached

    result = fetch_next_game_day(from_date_str, sport_id_priority)
    if result:
        result.update({'fetched_at': time.time(), 'from_date': from_date_str})
        save_off_results(result, 'next_games')
        return result
    return cached if usable else None
