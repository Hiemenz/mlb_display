"""Fetch historical game data for the idle (no-games-today) screen."""
import random
from datetime import datetime, timedelta

import requests


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
