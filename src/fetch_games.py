"""
Fetch and cache MLB game data from the Stats API.

Standalone CLI:
    python src/fetch_games.py --date 2025-04-01 [--sport-id 8] [--fetch-teams] [--config PATH]
"""
import os
import sys
import argparse
from datetime import datetime, timedelta

import requests
import pytz

# Allow running as a standalone script from any directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from util import load_json_file, load_yaml_file, save_off_results
from config_loader import load_config, add_config_arg

SPORT_NAMES = {
    1: "MLB", 8: "World Baseball Classic", 11: "College Baseball",
    12: "Triple-A", 13: "Double-A", 14: "Winter Leagues",
    16: "Spring Training", 51: "International"
}

# WBC abbreviations that collide with MLB team abbreviations.
_WBC_ABBR_OVERRIDES = {
    'COL': 'CLM',  # Colombia WBC → CLM to avoid collision with Colorado Rockies
}


def convert_time_z_to(utc_time_str, time_zone='America/Chicago'):
    utc_time = datetime.strptime(utc_time_str, "%Y-%m-%dT%H:%M:%SZ")
    utc_time = pytz.utc.localize(utc_time)
    local_tz = pytz.timezone(time_zone)
    local_time = utc_time.astimezone(local_tz)
    return local_time.strftime("%-I:%M %p")


_SUBSTITUTION_TYPES = ('substitution', 'timeout', 'advisory')
_PRE_GAME_STATES = ('Scheduled', 'Pre-Game', 'Warmup', 'Delayed Start')


def _pick_tv_channel(broadcasts, favorite_abbr, away_abbr, home_abbr):
    """Return one TV callSign/name to display, or None.

    Priority: favorite-team local TV > home-team local TV > first TV found.
    National broadcasts (ESPN, Peacock, etc.) are treated as home-side for
    this purpose and will appear if no local home/favorite broadcast exists.
    """
    tv = [b for b in (broadcasts or []) if b.get('type') == 'TV']
    if not tv:
        return None

    def _label(b):
        return b.get('callSign') or b.get('name') or ''

    # Favorite team override
    if favorite_abbr:
        fav_side = None
        if away_abbr and away_abbr.upper() == favorite_abbr.upper():
            fav_side = 'away'
        elif home_abbr and home_abbr.upper() == favorite_abbr.upper():
            fav_side = 'home'
        if fav_side:
            fav = [b for b in tv if b.get('homeAway') == fav_side]
            if fav:
                return _label(fav[0])

    # Home team local
    home_tv = [b for b in tv if b.get('homeAway') == 'home']
    if home_tv:
        return _label(home_tv[0])

    # National or first available
    return _label(tv[0])

_STADIUM_WEATHER_CACHE = None


def _load_stadium_weather():
    global _STADIUM_WEATHER_CACHE
    if _STADIUM_WEATHER_CACHE is None:
        _STADIUM_WEATHER_CACHE = load_json_file('stadium_weather.json') or {}
    return _STADIUM_WEATHER_CACHE


def _lookup_stadium(venue_id, venue_name):
    stadiums = _load_stadium_weather()
    if venue_id is not None:
        entry = stadiums.get(str(venue_id))
        if entry:
            return entry
    fallback = stadiums.get('_name_fallback', {})
    if venue_name:
        vid = fallback.get(venue_name)
        if vid:
            return stadiums.get(str(vid))
    return None


def _attach_pregame_weather(game_dict, schedule_game, config):
    """Fill weather_* and roof_state on game_dict for a scheduled game."""
    weather_cfg = config.get('weather') or {}
    if not weather_cfg.get('enabled', True):
        return
    venue = schedule_game.get('venue', {}) or {}
    venue_id = venue.get('id')
    stadium = _lookup_stadium(venue_id, venue.get('name'))
    if stadium is None:
        return
    # Fixed roof stadiums + retractable venues that never open in practice
    _ALWAYS_CLOSED_VENUE_IDS = {'2392'}  # Daikin Park (Houston) — never opens
    if stadium.get('roof') == 'fixed' or str(venue_id or '') in _ALWAYS_CLOSED_VENUE_IDS:
        game_dict['roof_state'] = 'fixed'
    try:
        from weather import get_forecast
    except ImportError:
        return
    forecast = get_forecast(
        str(venue_id or stadium.get('name')),
        stadium.get('lat'),
        stadium.get('lon'),
        game_dict.get('game_date'),
        cache_ttl_minutes=weather_cfg.get('cache_ttl_minutes', 60),
    )
    if not forecast:
        return
    game_dict['weather_temp_f'] = forecast.get('temp_f')
    game_dict['weather_wind_mph'] = forecast.get('wind_mph')
    game_dict['weather_wind_dir'] = forecast.get('wind_dir')
    game_dict['weather_precip_pct'] = forecast.get('precip_pct')

def fetch_win_probability(game_pk):
    """Return (away_wp, home_wp, last_play) from the winProbability endpoint, or (None, None, None)."""
    try:
        url = f'https://statsapi.mlb.com/api/v1/game/{game_pk}/winProbability'
        response = requests.get(url, timeout=5)
        data = response.json()
        if not isinstance(data, list) or not data:
            return None, None, None
        last = data[-1]
        away_wp = last.get('awayTeamWinProbability')
        home_wp = last.get('homeTeamWinProbability')
        # Scan backwards for the last real play (skip substitutions/challenges)
        last_play = None
        for entry in reversed(data):
            event_type = (entry.get('result', {}).get('eventType') or '').lower()
            event = entry.get('result', {}).get('event') or ''
            if event and not any(s in event_type for s in _SUBSTITUTION_TYPES):
                last_play = event
                break
        if away_wp is not None and home_wp is not None:
            away_wp = float(away_wp)
            home_wp = float(home_wp)
            if away_wp + home_wp <= 1.5:  # API returns 0-1 fractions
                away_wp *= 100
                home_wp *= 100
        else:
            away_wp, home_wp = None, None
        return away_wp, home_wp, last_play
    except Exception:
        return None, None, None


_PITCHER_CACHE_TTL_MINUTES = 30


def _pitcher_cache_key(pitcher_ids):
    return ','.join(str(p) for p in sorted(pitcher_ids))


def _load_pitcher_cache():
    return load_json_file('pitcher_cache.json')


def _save_pitcher_cache(cache):
    save_off_results(cache, 'pitcher_cache')


def _cache_get(cache, bucket, key, season):
    entry = cache.get(bucket, {}).get(key)
    if not entry or entry.get('season') != season:
        return None
    try:
        age = datetime.now() - datetime.fromisoformat(entry['fetched_at'])
        if age.total_seconds() < _PITCHER_CACHE_TTL_MINUTES * 60:
            return entry['data']
    except Exception:
        pass
    return None


def _cache_set(cache, bucket, key, season, data):
    if bucket not in cache:
        cache[bucket] = {}
    cache[bucket][key] = {
        'season': season,
        'data': data,
        'fetched_at': datetime.now().isoformat(timespec='seconds'),
    }


def _fetch_pitcher_eras(pitcher_ids, season):
    """Batch-fetch season ERA for a list of pitcher IDs. Returns {id: 'W-L, ERA ERA'}."""
    if not pitcher_ids:
        return {}
    key = _pitcher_cache_key(pitcher_ids)
    cache = _load_pitcher_cache()
    cached = _cache_get(cache, 'era', key, season)
    if cached is not None:
        return {int(k): v for k, v in cached.items()}
    ids_str = ','.join(str(p) for p in pitcher_ids)
    try:
        url = (
            f'https://statsapi.mlb.com/api/v1/people?personIds={ids_str}'
            f'&hydrate=stats(group=pitching,type=season,season={season})'
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()
    except Exception:
        return {}
    result = {}
    for person in data.get('people', []):
        pid = person.get('id')
        for stat_group in person.get('stats', []):
            splits = stat_group.get('splits', [])
            if splits:
                stat = splits[0].get('stat', {})
                era = stat.get('era', '')
                wins = stat.get('wins', '')
                losses = stat.get('losses', '')
                if era and not str(era).startswith('-'):
                    result[pid] = f'{wins}-{losses}, {era} ERA'
    _cache_set(cache, 'era', key, season, {str(k): v for k, v in result.items()})
    _save_pitcher_cache(cache)
    return result


def _fetch_decision_pitcher_stats(pitcher_ids, season):
    """Batch-fetch wins, losses, and saves for decision pitchers.

    Returns {id: {'record': 'W-L', 'saves': int}}.
    """
    ids = [p for p in pitcher_ids if p]
    if not ids:
        return {}
    key = _pitcher_cache_key(ids)
    cache = _load_pitcher_cache()
    cached = _cache_get(cache, 'decision', key, season)
    if cached is not None:
        return {int(k): v for k, v in cached.items()}
    ids_str = ','.join(str(p) for p in ids)
    try:
        url = (
            f'https://statsapi.mlb.com/api/v1/people?personIds={ids_str}'
            f'&hydrate=stats(group=pitching,type=season,season={season})'
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()
    except Exception:
        return {}
    result = {}
    for person in data.get('people', []):
        pid = person.get('id')
        for stat_group in person.get('stats', []):
            splits = stat_group.get('splits', [])
            if splits:
                stat = splits[0].get('stat', {})
                wins = stat.get('wins', '')
                losses = stat.get('losses', '')
                saves = stat.get('saves', 0)
                if wins != '' and losses != '':
                    result[pid] = {
                        'record': f'{wins}-{losses}',
                        'saves': int(saves) if saves else 0,
                    }
    _cache_set(cache, 'decision', key, season, {str(k): v for k, v in result.items()})
    _save_pitcher_cache(cache)
    return result


def fetch_all_team_abbreviations(sport_id=1):
    """Fetch all team abbreviations for a given sport and cache to data/teams.json."""
    team_abbreviations = {}
    try:
        print(f"Fetching all teams for sport_id {sport_id}...")
        response = requests.get(f'https://statsapi.mlb.com/api/v1/teams?sportId={sport_id}')
        if response.status_code == 200:
            data = response.json()
            teams = data.get('teams', [])
            for team in teams:
                team_id = str(team.get('id'))
                abbreviation = team.get('abbreviation')
                if team_id and abbreviation:
                    if sport_id == 8:
                        abbreviation = _WBC_ABBR_OVERRIDES.get(abbreviation, abbreviation)
                    team_abbreviations[team_id] = abbreviation
                    print(f"  {abbreviation}: {team.get('name')}")
            save_off_results({'team_abbreviation': team_abbreviations}, 'teams')
            print(f"✓ Cached {len(team_abbreviations)} team abbreviations")
        else:
            print(f"Error: API returned status code {response.status_code}")
    except Exception as e:
        print(f"Error fetching teams: {e}")
    return team_abbreviations


def get_team_abbreviation(team_id):
    """Fetch a single team abbreviation from MLB API."""
    try:
        response = requests.get(f'https://statsapi.mlb.com/api/v1/teams/{team_id}')
        if response.status_code == 200:
            data = response.json()
            abbreviation = data.get('teams', [{}])[0].get('abbreviation')
            if abbreviation:
                return abbreviation
    except Exception as e:
        print(f"Error fetching team {team_id}: {e}")
    return f"T{team_id}"


def check_games_for_sport(date, sport_id):
    """Return count of games for a sport on a date (MLB filters out spring training
    only when regular-season games exist on the same day)."""
    endpoint_url = (
        'https://statsapi.mlb.com/api/v1/schedule?'
        f'startDate={date}&endDate={date}&sportId={sport_id}'
    )
    try:
        response = requests.get(endpoint_url)
        if response.status_code == 200:
            data = response.json()
            game_dates = data.get('dates', [])
            if game_dates:
                games = game_dates[0].get('games', [])
                if sport_id == 1:
                    regular = [g for g in games if g.get('gameType') not in ('S', 'E')]
                    if regular:
                        games = regular
                return len(games)
    except Exception as e:
        print(f"Error checking games for sport {sport_id}: {e}")
    return 0


def find_next_game_date(sport_id_priority, from_date_str):
    """Search up to 30 days ahead for the next date with games. Returns 'YYYY-MM-DD' or None."""
    from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
    end_str = (from_date + timedelta(days=30)).strftime('%Y-%m-%d')

    for sid in sport_id_priority:
        endpoint = (
            f'https://statsapi.mlb.com/api/v1/schedule?'
            f'startDate={from_date_str}&endDate={end_str}&sportId={sid}'
        )
        try:
            resp = requests.get(endpoint, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for date_entry in data.get('dates', []):
                    games = date_entry.get('games', [])
                    if sid == 1:
                        regular = [g for g in games if g.get('gameType') not in ('S', 'E')]
                        if regular:
                            games = regular
                    if games:
                        found = date_entry['date']
                        if found != from_date_str:
                            print(f"Next game date: {found} (sport_id={sid})")
                            return found
        except Exception as e:
            print(f"Error searching for next game date: {e}")
    return None


def parse_games(data, sport_id=None, config=None):
    """Parse schedule API response and write data/games.json + data/teams.json."""
    if config is None:
        config = load_config()
    tz = config.get('timezone', 'America/Chicago')

    game_dates = data.get('dates', [])
    if not game_dates:
        print("No games found for this date")
        save_off_results({'games': []}, 'games')
        save_off_results({'team_abbreviation': {}}, 'teams')
        return

    games = game_dates[0].get('games', [])
    if not games:
        print("No games found for this date")
        save_off_results({'games': []}, 'games')
        save_off_results({'team_abbreviation': {}}, 'teams')
        return

    game_array = []
    max_live_calls = config.get('max_live_game_calls', 5)
    live_calls_made = 0

    team_abbreviations = load_json_file('teams.json').get('team_abbreviation', {})

    for game in games:
        game_id = game.get('gamePk')
        detailed_state = game.get('status', {}).get('detailedState')
        postpone_reason = game.get('status', {}).get('reason')

        game_teams = game.get('teams', {})
        away_team = game_teams.get('away', {})
        home_team = game_teams.get('home', {})
        away_team_info = away_team.get('team', {})
        home_team_info = home_team.get('team', {})
        linescore = game.get('linescore', {})
        ls_teams = linescore.get('teams', {})
        ls_away = ls_teams.get('away', {})
        ls_home = ls_teams.get('home', {})

        away_team_id = away_team_info.get('id')
        home_team_id = home_team_info.get('id')

        last_play_result = None

        save_situation = False
        if detailed_state == 'In Progress':
            current_inning = linescore.get('currentInning', 0) or 0
            away_runs = ls_away.get('runs') or 0
            home_runs = ls_home.get('runs') or 0
            run_diff = abs(away_runs - home_runs)
            if current_inning >= 7 and 1 <= run_diff <= 3:
                save_situation = True

        away_abbreviation = away_team_info.get('abbreviation')
        home_abbreviation = home_team_info.get('abbreviation')

        if sport_id == 8:
            away_abbreviation = _WBC_ABBR_OVERRIDES.get(away_abbreviation, away_abbreviation)
            home_abbreviation = _WBC_ABBR_OVERRIDES.get(home_abbreviation, home_abbreviation)

        if away_team_id and away_abbreviation:
            team_abbreviations[str(away_team_id)] = away_abbreviation
        if home_team_id and home_abbreviation:
            team_abbreviations[str(home_team_id)] = home_abbreviation

        ls_offense = linescore.get('offense', {})
        decisions = game.get('decisions', {})
        away_record = away_team.get('leagueRecord', {})
        home_record = home_team.get('leagueRecord', {})

        game_dict = {
            'away_team_name': away_team_info.get('name'),
            'away_team_id': away_team_id,
            'away_team_is_winner': away_team.get('isWinner'),
            'away_probable': away_team.get('probablePitcher', {}).get('fullName'),
            '_away_probable_id': away_team.get('probablePitcher', {}).get('id'),
            'away_probable_note': away_team.get('probablePitcher', {}).get('note'),
            'away_team_series_number': away_team.get('seriesNumber'),
            'home_team_name': home_team_info.get('name'),
            'home_team_id': home_team_id,
            'home_team_is_winner': home_team.get('isWinner'),
            'home_probable': home_team.get('probablePitcher', {}).get('fullName'),
            '_home_probable_id': home_team.get('probablePitcher', {}).get('id'),
            'home_probable_note': home_team.get('probablePitcher', {}).get('note'),
            'home_team_series_number': home_team.get('seriesNumber'),
            'double_header': game.get('doubleHeader'),
            'series_description': game.get('seriesDescription'),
            'day_night': game.get('dayNight'),
            'description': game.get('description'),
            'postpone_reason': postpone_reason,
            'game_number': game.get('gameNumber'),
            'games_in_series': game.get('gamesInSeries'),
            'game_date': game.get('gameDate'),
            'game_start': convert_time_z_to(game.get('gameDate'), tz),
            'detailed_state': detailed_state,
            'venue': game.get('venue', {}).get('name'),
            'current_inning': linescore.get('currentInning'),
            'currentInningOrdinal': linescore.get('currentInningOrdinal'),
            'inningState': linescore.get('inningState'),
            'winner_name': decisions.get('winner', {}).get('fullName'),
            '_winner_id': decisions.get('winner', {}).get('id'),
            'loser_name': decisions.get('loser', {}).get('fullName'),
            '_loser_id': decisions.get('loser', {}).get('id'),
            'saver_name': decisions.get('save', {}).get('fullName'),
            '_saver_id': decisions.get('save', {}).get('id'),
            'winner_record': None,
            'loser_record': None,
            'saver_saves': None,
            'num_of_outs': linescore.get('outs'),
            'balls': linescore.get('balls'),
            'strikes': linescore.get('strikes'),
            'away_runs': ls_away.get('runs'),
            'home_runs': ls_home.get('runs'),
            'away_hits': ls_away.get('hits'),
            'home_hits': ls_home.get('hits'),
            'away_errors': ls_away.get('errors'),
            'home_errors': ls_home.get('errors'),
            'away_left_on_base': ls_away.get('leftOnBase'),
            'home_left_on_base': ls_home.get('leftOnBase'),
            'away_inning_runs': [inn.get('away', {}).get('runs') for inn in linescore.get('innings', [])],
            'home_inning_runs': [inn.get('home', {}).get('runs') for inn in linescore.get('innings', [])],
            'runner_on_first': ls_offense.get('first', {}).get('fullName'),
            'runner_on_second': ls_offense.get('second', {}).get('fullName'),
            'runner_on_third': ls_offense.get('third', {}).get('fullName'),
            'away_team_record_wins': away_record.get('wins'),
            'away_team_record_losses': away_record.get('losses'),
            'home_team_record_wins': home_record.get('wins'),
            'home_team_record_losses': home_record.get('losses'),
            'no_hitter': game.get('flags', {}).get('noHitter'),
            'perfect_game': game.get('flags', {}).get('perfectGame'),
            'current_hitter': ls_offense.get('batter', {}).get('fullName'),
            'due_up': ls_offense.get('onDeck', {}).get('fullName'),
            'in_hole': ls_offense.get('inHole', {}).get('fullName'),
            'current_pitcher': linescore.get('defense', {}).get('pitcher', {}).get('fullName'),
            'last_play': last_play_result,
            'save_situation': save_situation,
            'game_pk': game_id,
            'tv_channel': _pick_tv_channel(
                game.get('broadcasts', []),
                config.get('primary'),
                away_abbreviation,
                home_abbreviation,
            ),
        }
        if game_dict.get('detailed_state') == 'In Progress' and live_calls_made < max_live_calls:
            away_wp, home_wp, last_play = fetch_win_probability(game_id)
            live_calls_made += 1
            game_dict['last_play'] = last_play
            if config.get('scoreboard_win_probability', False):
                game_dict['away_win_probability'] = away_wp
                game_dict['home_win_probability'] = home_wp
            if config.get('scoreboard_live_details', False):
                from game_detail_fetch import fetch_scoreboard_live_extras
                extras = fetch_scoreboard_live_extras(game_id, away_team_id, home_team_id)
                game_dict.update(extras)
            if game_dict.get('inningState') in ('Middle', 'End') and live_calls_made < max_live_calls:
                from game_detail_fetch import fetch_between_inning_info
                bi_info = fetch_between_inning_info(game_id, game_dict['inningState'])
                live_calls_made += 1
                game_dict.update(bi_info)
        elif game_dict.get('detailed_state') == 'Delayed' and (game_dict.get('current_inning') or 0) > 0 and live_calls_made < max_live_calls:
            # Fetch upcoming batters/pitcher so the delay screen can show who's due up
            from game_detail_fetch import fetch_between_inning_info
            _inning_state = game_dict.get('inningState') or ''
            _bi_state = 'Middle' if _inning_state in ('Bottom', 'Middle') else 'End'
            bi_info = fetch_between_inning_info(game_id, _bi_state)
            live_calls_made += 1
            game_dict.update(bi_info)
        elif game_dict.get('detailed_state') in _PRE_GAME_STATES:
            _attach_pregame_weather(game_dict, game, config)
        game_array.append(game_dict)

    # Batch-fetch probable pitcher ERA (MLB API no longer returns note field)
    pitcher_ids = set()
    for gd in game_array:
        if gd.get('_away_probable_id'):
            pitcher_ids.add(gd['_away_probable_id'])
        if gd.get('_home_probable_id'):
            pitcher_ids.add(gd['_home_probable_id'])
    if pitcher_ids:
        from datetime import date as _date
        season = str(_date.today().year)
        eras = _fetch_pitcher_eras(pitcher_ids, season)
        for gd in game_array:
            away_id = gd.pop('_away_probable_id', None)
            home_id = gd.pop('_home_probable_id', None)
            if away_id and away_id in eras and not gd.get('away_probable_note'):
                gd['away_probable_note'] = eras[away_id]
            if home_id and home_id in eras and not gd.get('home_probable_note'):
                gd['home_probable_note'] = eras[home_id]
    else:
        for gd in game_array:
            gd.pop('_away_probable_id', None)
            gd.pop('_home_probable_id', None)

    # Batch-fetch decision pitcher records (W-L + saves)
    decision_ids = set()
    for gd in game_array:
        decision_ids.add(gd.get('_winner_id'))
        decision_ids.add(gd.get('_loser_id'))
        decision_ids.add(gd.get('_saver_id'))
    decision_ids.discard(None)
    if decision_ids:
        from datetime import date as _date
        season = str(_date.today().year)
        decision_stats = _fetch_decision_pitcher_stats(decision_ids, season)
        for gd in game_array:
            winner_id = gd.pop('_winner_id', None)
            loser_id = gd.pop('_loser_id', None)
            saver_id = gd.pop('_saver_id', None)
            if winner_id and winner_id in decision_stats:
                gd['winner_record'] = decision_stats[winner_id]['record']
            if loser_id and loser_id in decision_stats:
                gd['loser_record'] = decision_stats[loser_id]['record']
            if saver_id and saver_id in decision_stats:
                gd['saver_saves'] = decision_stats[saver_id]['saves']
    else:
        for gd in game_array:
            gd.pop('_winner_id', None)
            gd.pop('_loser_id', None)
            gd.pop('_saver_id', None)

    save_off_results({'games': game_array}, 'games')
    save_off_results({'team_abbreviation': team_abbreviations}, 'teams')


def fetch_scoreboard_for_date(date, sport_id=None, config=None):
    """Fetch schedule API for date, parse games, write data/games.json + data/teams.json."""
    if config is None:
        config = load_config()

    if sport_id is None:
        sport_id_priority = config.get('sport_id_priority')
        if sport_id_priority and isinstance(sport_id_priority, list):
            print(f"Checking sports in priority order: {[SPORT_NAMES.get(sid, f'Sport {sid}') for sid in sport_id_priority]}")
            for sid in sport_id_priority:
                game_count = check_games_for_sport(date, sid)
                if game_count > 0:
                    print(f"✓ Found {game_count} game(s) for {SPORT_NAMES.get(sid, f'Sport {sid}')}")
                    sport_id = sid
                    break
                else:
                    print(f"  No games for {SPORT_NAMES.get(sid, f'Sport {sid}')}")
            if sport_id is None:
                sport_id = sport_id_priority[0]
                print(f"No games found, defaulting to {SPORT_NAMES.get(sport_id, f'Sport {sport_id}')}")
        else:
            sport_id = config.get('sport_id', 1)

    print(f"Fetching games for {date} (sportId={sport_id})")
    endpoint_url = (
        'https://statsapi.mlb.com/api/v1/schedule?'
        f'startDate={date}&endDate={date}&sportId={sport_id}'
        '&hydrate=decisions,probablePitcher(note),linescore,flags,team,broadcasts(all)'
    )
    response = requests.get(endpoint_url)
    data = response.json()
    parse_games(data, sport_id, config)


def main():
    parser = argparse.ArgumentParser(
        description='Fetch MLB game data to data/games.json',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python src/fetch_games.py --date 2025-04-01
  python src/fetch_games.py --date 2025-03-21 --sport-id 8
  python src/fetch_games.py --fetch-teams --sport-id 1
        ''',
    )
    parser.add_argument('--date', type=str, help='Date (YYYY-MM-DD). Default: today')
    parser.add_argument('--sport-id', type=int, help='Sport ID override')
    parser.add_argument('--fetch-teams', action='store_true',
                        help='Fetch and cache all team abbreviations, then exit')
    add_config_arg(parser)
    args = parser.parse_args()

    config = load_config(args.config)

    if args.sport_id:
        sport_id = args.sport_id
    else:
        sport_id_priority = config.get('sport_id_priority')
        sport_id = sport_id_priority[0] if sport_id_priority else config.get('sport_id', 1)

    if args.fetch_teams:
        fetch_all_team_abbreviations(sport_id)
        return

    if args.date:
        date_str = args.date
    else:
        from datetime import date
        date_str = date.today().strftime('%Y-%m-%d')

    sport_id_arg = args.sport_id  # None means let priority logic decide
    fetch_scoreboard_for_date(date_str, sport_id_arg, config)
    print("✓ Games written to data/games.json")


if __name__ == '__main__':
    main()
