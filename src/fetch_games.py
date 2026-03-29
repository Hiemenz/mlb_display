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


def get_last_play_result(game_pk):
    """Fetch the last play result for a game in progress."""
    try:
        response = requests.get(f'https://statsapi.mlb.com/api/v1/game/{game_pk}/feed/live')
        if response.status_code == 200:
            data = response.json()
            plays_data = data.get('liveData', {}).get('plays', {})
            current_play = plays_data.get('currentPlay', {})
            result = current_play.get('result', {}).get('description', '')
            if result:
                return result
            event = current_play.get('result', {}).get('event', '')
            if event:
                return event
            all_plays = plays_data.get('allPlays', [])
            if all_plays:
                last_play = all_plays[-1]
                result = last_play.get('result', {}).get('description', '')
                if result:
                    return result
                event = last_play.get('result', {}).get('event', '')
                if event:
                    return event
    except Exception as e:
        print(f"Error fetching last play for game {game_pk}: {e}")
    return None


def fetch_win_probability(game_pk):
    """Return (away_wp, home_wp) as floats 0-100 for the most recent play, or (None, None)."""
    try:
        url = f'https://statsapi.mlb.com/api/v1/game/{game_pk}/winProbability'
        response = requests.get(url, timeout=5)
        data = response.json()
        if not isinstance(data, list) or not data:
            return None, None
        last = data[-1]
        away_wp = last.get('awayTeamWinProbability')
        home_wp = last.get('homeTeamWinProbability')
        if away_wp is not None and home_wp is not None:
            away_wp = float(away_wp)
            home_wp = float(home_wp)
            if away_wp + home_wp <= 1.5:  # API returns 0-1 fractions
                away_wp *= 100
                home_wp *= 100
            return away_wp, home_wp
        return None, None
    except Exception:
        return None, None


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
    fetch_last_play = config.get('fetch_last_play', True)
    live_calls_made = 0

    team_abbreviations = load_json_file('teams.json').get('team_abbreviation', {})

    for game in games:
        game_id = game.get('gamePk')
        detailed_state = game.get('status', {}).get('detailedState')

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
        if fetch_last_play and detailed_state == 'In Progress':
            if live_calls_made < max_live_calls:
                print(f"Fetching live game data for game {game_id} ({live_calls_made + 1}/{max_live_calls})")
                last_play_result = get_last_play_result(game_id)
                live_calls_made += 1
            else:
                print(f"Skipping live game data for game {game_id} (limit of {max_live_calls} reached)")

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
            'away_probable_note': away_team.get('probablePitcher', {}).get('note'),
            'away_team_series_number': away_team.get('seriesNumber'),
            'home_team_name': home_team_info.get('name'),
            'home_team_id': home_team_id,
            'home_team_is_winner': home_team.get('isWinner'),
            'home_probable': home_team.get('probablePitcher', {}).get('fullName'),
            'home_probable_note': home_team.get('probablePitcher', {}).get('note'),
            'home_team_series_number': home_team.get('seriesNumber'),
            'double_header': game.get('doubleHeader'),
            'series_description': game.get('seriesDescription'),
            'day_night': game.get('dayNight'),
            'description': game.get('description'),
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
            'loser_name': decisions.get('loser', {}).get('fullName'),
            'saver_name': decisions.get('save', {}).get('fullName'),
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
            'current_pitcher': linescore.get('defense', {}).get('pitcher', {}).get('fullName'),
            'last_play': last_play_result,
            'save_situation': save_situation,
            'game_pk': game_id,
        }
        if config.get('scoreboard_win_probability', False) and game_dict.get('detailed_state') == 'In Progress':
            away_wp, home_wp = fetch_win_probability(game_id)
            game_dict['away_win_probability'] = away_wp
            game_dict['home_win_probability'] = home_wp
        game_array.append(game_dict)

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
        '&hydrate=decisions,probablePitcher(note),linescore,flags,team'
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
