from generate_image import orchestrate_score_board

from datetime import datetime, timedelta
import json
import os
import requests
import platform
import argparse

from display_eink import display_image, display_partial_regions
from refresh_tracker import needs_full_refresh
from util import load_json_file, load_yaml_file, save_off_results
from game_detail_fetch import select_game, fetch_field_view_data, fetch_scorecard_data, fetch_pitch_view_data
from field_view import render_field_view
from scorecard_view import render_scorecard_view
from pitch_view import render_pitch_view
import pytz
from PIL import Image, ImageDraw, ImageFont

# Spring Training Support:
# This module automatically fetches team abbreviations for any teams encountered in games,
# including spring training games with minor league affiliates or split-squad teams.
# Team data is cached in data/teams.json and merged with standings data.

# Platform Detection:
# On Darwin (macOS), e-ink display updates are skipped (hardware not available).
# Images are still generated and saved for testing/development.




def get_last_play_result(game_pk):
    """
    Fetch the last play result for a game in progress.
    Returns a string describing the last play.
    """
    try:
        response = requests.get(f'https://statsapi.mlb.com/api/v1/game/{game_pk}/feed/live')
        if response.status_code == 200:
            data = response.json()

            plays_data = data.get('liveData', {}).get('plays', {})

            # Try current play first (for in-progress games)
            current_play = plays_data.get('currentPlay', {})

            # Try to get the result description
            result = current_play.get('result', {}).get('description', '')
            if result:
                return result

            # Fallback to play event if description not available
            event = current_play.get('result', {}).get('event', '')
            if event:
                return event

            # For games that just finished or between plays, get last play from allPlays
            all_plays = plays_data.get('allPlays', [])
            if all_plays and len(all_plays) > 0:
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


# WBC abbreviations that collide with MLB team abbreviations.
# Colombia (ISO/ESPN: COL) conflicts with Colorado Rockies (MLB: COL).
_WBC_ABBR_OVERRIDES = {
    'COL': 'CLM',  # Colombia WBC → CLM to avoid collision with Colorado Rockies
}


def fetch_all_team_abbreviations(sport_id=1):
    """
    Fetch all team abbreviations for a given sport from MLB API.
    This pre-populates the cache so individual lookups aren't needed.

    Args:
        sport_id: Sport ID (1=MLB, 8=WBC, 11=College, etc.)

    Returns:
        Dictionary of team_id -> abbreviation
    """
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

            # Save to cache
            save_off_results({'team_abbreviation': team_abbreviations}, 'teams')
            print(f"✓ Cached {len(team_abbreviations)} team abbreviations")
        else:
            print(f"Error: API returned status code {response.status_code}")
    except Exception as e:
        print(f"Error fetching teams: {e}")

    return team_abbreviations


def get_team_abbreviation(team_id):
    """
    Fetch team abbreviation from MLB API.
    Returns the abbreviation or a fallback if not found.
    """
    try:
        response = requests.get(f'https://statsapi.mlb.com/api/v1/teams/{team_id}')
        if response.status_code == 200:
            data = response.json()
            team_abbreviation = data.get('teams', [{}])[0].get('abbreviation')
            if team_abbreviation:
                return team_abbreviation
    except Exception as e:
        print(f"Error fetching team {team_id}: {e}")

    # Fallback: return team ID as string
    return f"T{team_id}"




def convert_time_z_to(utc_time_str, time_zone='America/Chicago'):
    utc_time = datetime.strptime(utc_time_str, "%Y-%m-%dT%H:%M:%SZ")

    utc_time = pytz.utc.localize(utc_time)

    cst_timezone = pytz.timezone(time_zone)

    cst_time = utc_time.astimezone(cst_timezone)

    cst_hour_minutes = cst_time.strftime("%-I:%M %p")
    return cst_hour_minutes


def parse_games(data):

    config_data = load_yaml_file('config.yaml')
    tz = config_data.get('timezone', 'America/Chicago')

    game_dates = data.get('dates', [])

    # Check if there are any games
    if not game_dates or len(game_dates) == 0:
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
    game_list = {}

    max_live_calls = config_data.get('max_live_game_calls', 5)
    fetch_last_play = config_data.get('fetch_last_play', True)
    live_calls_made = 0

    # Load existing team abbreviations or create new dict
    team_abbreviations = load_json_file('teams.json').get('team_abbreviation', {})

    for game in games:
        game_id = game.get('gamePk')

        detailed_state = game.get('status', {}).get('detailedState')

        # Get team IDs
        away_team_id = game.get('teams', {}).get('away', {}).get('team', {}).get('id')
        home_team_id = game.get('teams', {}).get('home', {}).get('team', {}).get('id')

        # For in-progress games, fetch the last play result (up to configured limit)
        last_play_result = None
        if fetch_last_play and detailed_state == 'In Progress':
            if live_calls_made < max_live_calls:
                print(f"Fetching live game data for game {game_id} ({live_calls_made + 1}/{max_live_calls})")
                last_play_result = get_last_play_result(game_id)
                live_calls_made += 1
            else:
                print(f"Skipping live game data for game {game_id} (limit of {max_live_calls} reached)")

        # Compute save situation flag
        save_situation = False
        if detailed_state == 'In Progress':
            current_inning = game.get('linescore', {}).get('currentInning', 0) or 0
            away_runs = game.get('linescore', {}).get('teams', {}).get('away', {}).get('runs') or 0
            home_runs = game.get('linescore', {}).get('teams', {}).get('home', {}).get('runs') or 0
            run_diff = abs(away_runs - home_runs)
            if current_inning >= 7 and 1 <= run_diff <= 3:
                save_situation = True

        # Read abbreviations from the hydrated team data in the schedule response
        away_abbreviation = game.get('teams', {}).get('away', {}).get('team', {}).get('abbreviation')
        home_abbreviation = game.get('teams', {}).get('home', {}).get('team', {}).get('abbreviation')

        if away_team_id and away_abbreviation:
            team_abbreviations[str(away_team_id)] = away_abbreviation
        if home_team_id and home_abbreviation:
            team_abbreviations[str(home_team_id)] = home_abbreviation

        game_dict = {
            'away_team_name': game.get('teams', {}).get('away', {}).get('team', {}).get('name'),
            'away_team_id': away_team_id,
            'away_team_is_winner': game.get('teams', {}).get('away', {}).get('isWinner'),
            'away_probable': game.get('teams', {}).get('away', {}).get('probablePitcher',{}).get('fullName'),
            'away_team_series_number': game.get('teams', {}).get('away', {}).get('seriesNumber'),
            'home_team_name': game.get('teams', {}).get('home', {}).get('team', {}).get('name'),
            'home_team_id': home_team_id,
            'home_team_is_winner': game.get('teams', {}).get('home', {}).get('isWinner'),
            'home_probable': game.get('teams', {}).get('home', {}).get('probablePitcher',{}).get('fullName'),
            'home_team_series_number': game.get('teams', {}).get('home', {}).get('seriesNumber'),
            'double_header': game.get('doubleHeader'),
            'series_description': game.get('seriesDescription'),
            'day_night': game.get('dayNight'),
            'description': game.get('description'),
            'game_number': game.get('gameNumber'),
            'games_in_series': game.get('gamesInSeries'),
            'game_date': game.get('gameDate'),
            'game_start': convert_time_z_to(game.get('gameDate'), tz),
            'detailed_state': detailed_state,
            'venue': game.get('venue',{}).get('name'),
            'current_inning': game.get('linescore',{}).get('currentInning'),
            'currentInningOrdinal': game.get('linescore',{}).get('currentInningOrdinal'),
            'inningState': game.get('linescore',{}).get('inningState'),
            'winner_name': game.get('decisions',{}).get('winner',{}).get('fullName'),
            'loser_name': game.get('decisions',{}).get('loser',{}).get('fullName'),
            'num_of_outs': game.get('linescore',{}).get('outs'),
            'balls': game.get('linescore',{}).get('balls'),
            'strikes': game.get('linescore',{}).get('strikes'),
            'away_runs': game.get('linescore',{}).get('teams',{}).get('away',{}).get('runs'),
            'home_runs': game.get('linescore',{}).get('teams',{}).get('home',{}).get('runs'),
            'away_hits': game.get('linescore',{}).get('teams',{}).get('away',{}).get('hits'),
            'home_hits': game.get('linescore',{}).get('teams',{}).get('home',{}).get('hits'),
            'away_errors': game.get('linescore',{}).get('teams',{}).get('away',{}).get('errors'),
            'home_errors': game.get('linescore',{}).get('teams',{}).get('home',{}).get('errors'),
            'away_left_on_base': game.get('linescore',{}).get('teams',{}).get('away',{}).get('leftOnBase'),
            'home_left_on_base': game.get('linescore',{}).get('teams',{}).get('home',{}).get('leftOnBase'),
            'runner_on_first': game.get('linescore',{}).get('offense',{}).get('first',{}).get('fullName'),
            'runner_on_second': game.get('linescore',{}).get('offense',{}).get('second',{}).get('fullName'),
            'runner_on_third': game.get('linescore',{}).get('offense',{}).get('third',{}).get('fullName'),
            'away_team_record_wins': game.get('teams',{}).get('away',{}).get('leagueRecord',{}).get('wins'),
            'away_team_record_losses': game.get('teams',{}).get('away',{}).get('leagueRecord',{}).get('losses'),
            'home_team_record_wins': game.get('teams',{}).get('home',{}).get('leagueRecord',{}).get('wins'),
            'home_team_record_losses': game.get('teams',{}).get('home',{}).get('leagueRecord',{}).get('losses'),
            'no_hitter': game.get('flags',{}).get('noHitter'),
            'perfect_game': game.get('flags',{}).get('perfectGame'),
            'current_hitter': game.get('linescore',{}).get('offense',{}).get('batter', {}).get('fullName'),
            'current_pitcher': game.get('linescore',{}).get('defense',{}).get('pitcher', {}).get('fullName'),
            'last_play': last_play_result,
            'save_situation': save_situation,
            'game_pk': game_id,
            }

        game_array.append(game_dict)

    # Save both games and updated team abbreviations
    save_off_results({'games': game_array}, 'games')
    save_off_results({'team_abbreviation': team_abbreviations}, 'teams')

def read_json_file(file_name):
    """
    Reads a JSON file and returns the parsed JSON data.
    
    :param file_name: str, the name of the JSON file to read
    :return: dict or list, the parsed JSON data
    """
    try:
        with open(file_name, 'r') as file:
            data = json.load(file)
        return data
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        return None
    except FileNotFoundError:
        print("File not found")
        return None



def _data_path(filename):
    """Return absolute path to a file in the data/ directory."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'data', filename)


def _config_path():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'config', 'config.yaml')


def load_discord_state():
    """Load pending Discord display change, or return None if none pending."""
    path = _data_path('discord_state.json')
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            state = json.load(f)
        if not state.get('applied', True):
            return state
    except Exception:
        pass
    return None


def mark_discord_state_applied():
    path = _data_path('discord_state.json')
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            state = json.load(f)
        state['applied'] = True
        with open(path, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def apply_discord_change(state, config_data):
    """Apply pending Discord changes to in-memory config and persist to config.yaml."""
    import yaml
    changed = False
    if state.get('pending_mode') and state['pending_mode'] in ('scoreboard', 'linescore', 'field', 'scorecard', 'pitch'):
        config_data['display_mode'] = state['pending_mode']
        changed = True
    if state.get('pending_team'):
        config_data['primary'] = state['pending_team'].upper()
        changed = True
    if changed:
        try:
            with open(_config_path(), 'w') as f:
                yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            print(f"Warning: could not save config.yaml after Discord change: {e}")
    return changed


def render_discord_overlay(state, dark_mode=False):
    """Render an 800x480 announcement image for a Discord display change."""
    picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pic')
    img = Image.new('1', (800, 480), 255)
    draw = ImageDraw.Draw(img)
    try:
        font_lg = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 48)
        font_md = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 28)
        font_sm = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 22)
    except Exception:
        font_lg = font_md = font_sm = ImageFont.load_default()

    mode = state.get('pending_mode', '').upper()
    team = state.get('pending_team', '').upper()
    user = state.get('requested_by', '')

    lines = [
        ('Display Changing', font_md, 120),
        (mode or team, font_lg, 185),
    ]
    if mode and team:
        lines.append((f'Team: {team}', font_md, 265))
    lines.append((f'Requested by @{user}', font_sm, 340))

    for text, font, y in lines:
        try:
            w = font.getlength(text)
        except AttributeError:
            w = len(text) * 12
        draw.text(((800 - w) // 2, y), text, font=font, fill=0)

    # Border
    draw.rectangle([10, 10, 789, 469], outline=0, width=3)

    if dark_mode:
        img = img.point(lambda p: 0 if p == 255 else 255)
    return img


def find_next_game_date(sport_id_priority, from_date_str):
    """
    Search up to 30 days ahead for the next date with games.
    Returns 'YYYY-MM-DD' string or None.
    """
    from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
    end_date = from_date + timedelta(days=30)
    end_str = end_date.strftime('%Y-%m-%d')

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
                        games = [g for g in games if g.get('gameType') not in ('S', 'E')]
                    if games:
                        found = date_entry['date']
                        if found != from_date_str:
                            print(f"Next game date: {found} (sport_id={sid})")
                            return found
        except Exception as e:
            print(f"Error searching for next game date: {e}")

    return None


def load_schedule_state():
    path = _data_path('schedule_state.json')
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_schedule_state(state):
    path = _data_path('schedule_state.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(state, f, indent=2)


def check_games_for_sport(date, sport_id):
    """
    Check if there are games for a specific sport on a date.

    Args:
        date: Date string in format 'YYYY-MM-DD'
        sport_id: Sport ID to check

    Returns:
        Number of games found, or 0 if none
    """
    endpoint_url = (
        'https://statsapi.mlb.com/api/v1/schedule?'
        f'startDate={date}&endDate={date}&sportId={sport_id}'
    )
    try:
        response = requests.get(endpoint_url)
        if response.status_code == 200:
            data = response.json()
            game_dates = data.get('dates', [])
            if game_dates and len(game_dates) > 0:
                games = game_dates[0].get('games', [])
                # For MLB (sport_id=1), only count regular/postseason games — not spring training ('S')
                # This allows WBC (sport_id=8) to take priority during spring training period
                if sport_id == 1:
                    games = [g for g in games if g.get('gameType') not in ('S', 'E')]
                return len(games)
    except Exception as e:
        print(f"Error checking games for sport {sport_id}: {e}")

    return 0


def fetch_scoreboard_for_date(date, sport_id=None):
    """
    Fetch scoreboard for a specific date and sport.

    Args:
        date: Date string in format 'YYYY-MM-DD'
        sport_id: Sport ID (1=MLB, 8=WBC, 11=College, etc.). If None, reads from config.

    Sport IDs:
        1  = MLB (default)
        8  = World Baseball Classic
        11 = College Baseball
        12 = Triple-A
        13 = Double-A
        14 = Winter Leagues
        16 = Spring Training (also uses 1)
        51 = International
    """
    # Read sport_id from config if not provided
    if sport_id is None:
        config_data = load_yaml_file('config.yaml')

        # Check if sport_id_priority is configured
        sport_id_priority = config_data.get('sport_id_priority')

        if sport_id_priority and isinstance(sport_id_priority, list):
            # Check each sport in priority order
            sport_names = {
                1: "MLB", 8: "World Baseball Classic", 11: "College Baseball",
                12: "Triple-A", 13: "Double-A", 14: "Winter Leagues",
                16: "Spring Training", 51: "International"
            }

            print(f"Checking sports in priority order: {[sport_names.get(sid, f'Sport {sid}') for sid in sport_id_priority]}")

            for sid in sport_id_priority:
                game_count = check_games_for_sport(date, sid)
                if game_count > 0:
                    print(f"✓ Found {game_count} game(s) for {sport_names.get(sid, f'Sport {sid}')}")
                    sport_id = sid
                    break
                else:
                    print(f"  No games for {sport_names.get(sid, f'Sport {sid}')}")

            # If no games found for any sport, use the first priority
            if sport_id is None:
                sport_id = sport_id_priority[0]
                print(f"No games found, defaulting to {sport_names.get(sport_id, f'Sport {sport_id}')}")
        else:
            # Fall back to single sport_id
            sport_id = config_data.get('sport_id', 1)

    print(f"Fetching games for {date} (sportId={sport_id})")

    endpoint_url = (
        'https://statsapi.mlb.com/api/v1/schedule?'
        f'startDate={date}&endDate={date}&sportId={sport_id}&hydrate=decisions,probablePitcher(note),linescore,flags,team'
    )
    response = requests.get(endpoint_url)
    data = response.json()

    parse_games(data)
    
    

def _get_display_mode(config):
    """Determine display mode from config. Returns 'scoreboard', 'linescore', 'field', or 'scorecard'."""
    mode = config.get('display_mode')
    if mode and mode in ('scoreboard', 'linescore', 'field', 'scorecard', 'pitch'):
        return mode
    # Backward compat: use scoreboard flag
    if config.get('scoreboard', True):
        return 'scoreboard'
    return 'linescore'


def _run_single_game_mode(mode, game_state_data, team_data, config):
    """Run field or scorecard mode for a single game."""
    favorite = config.get('primary', '')
    game = select_game(game_state_data, favorite, team_data)
    if not game:
        print("No game found for single-game display mode")
        return

    game_pk = game.get('game_pk')
    if not game_pk:
        print("No game_pk found")
        return

    dark_mode = config.get('dark_mode', False)

    away_id = str(game.get('away_team_id', ''))
    home_id = str(game.get('home_team_id', ''))
    away_abbr = team_data.get('team_abbreviation', {}).get(away_id, '')
    home_abbr = team_data.get('team_abbreviation', {}).get(home_id, '')
    print(f"Selected game: {away_abbr} @ {home_abbr} (pk={game_pk}, mode={mode})")

    try:
        if mode == 'field':
            data = fetch_field_view_data(game_pk)
            image = render_field_view(data, dark_mode=dark_mode)
        elif mode == 'pitch':
            data = fetch_pitch_view_data(game_pk)
            image = render_pitch_view(data, dark_mode=dark_mode)
        else:
            data = fetch_scorecard_data(game_pk)
            image = render_scorecard_view(data, dark_mode=dark_mode)

        display_image(image)
        print(f"{mode.title()} view generated successfully")
    except Exception as e:
        print(f"Error generating {mode} view: {e}")
        import traceback
        traceback.print_exc()


def scoreboard_generate(date_str, game_data, sport_id=None):
    """
    Generate scoreboard for a specific date and sport.

    Args:
        date_str: Date string in format 'YYYY-MM-DD'
        game_data: Optional pre-fetched game data (if None, will fetch from API)
        sport_id: Sport ID to fetch (if None, reads from config)
    """
    if game_data:
        parse_games(game_data)
    else:
        fetch_scoreboard_for_date(date_str, sport_id)

    game_state_data = read_json_file('data/games.json')['games']
    team_data = read_json_file('data/teams.json')

    # Ensure team_data has the required structure
    if not team_data or 'team_abbreviation' not in team_data:
        team_data = {'team_abbreviation': {}}

    config_data = load_yaml_file('config.yaml')
    mode = _get_display_mode(config_data)

    if mode in ('field', 'scorecard', 'pitch'):
        _run_single_game_mode(mode, game_state_data, team_data, config_data)
        return

    result = orchestrate_score_board(game_state_data, team_data, date_str)

    if result:
        sccoreboard_image, changed_regions = result
        if needs_full_refresh() or not changed_regions:
            print("Scoreboard: full refresh")
            display_image(sccoreboard_image)
        else:
            print(f"Scoreboard: partial refresh ({len(changed_regions)} region(s))")
            display_partial_regions(sccoreboard_image, changed_regions)
    else:
        print("No display update needed - image unchanged")


def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='Generate MLB scoreboard for e-ink display',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Use today's date with config sport_id
  python scoreboard_generate.py

  # Specify a date
  python scoreboard_generate.py --date 2024-07-26

  # World Baseball Classic game from 2023
  python scoreboard_generate.py --date 2023-03-21 --sport-id 8

  # Spring training game
  python scoreboard_generate.py --date 2024-02-28 --sport-id 1
        '''
    )
    parser.add_argument(
        '--date',
        type=str,
        help='Date to fetch games for (format: YYYY-MM-DD). Default: today'
    )
    parser.add_argument(
        '--sport-id',
        type=int,
        help='Sport ID (1=MLB, 8=WBC, 11=College, etc.). Default: from config.yaml'
    )
    parser.add_argument(
        '--fetch-teams',
        action='store_true',
        help='Fetch and cache all team abbreviations for the sport, then exit'
    )
    parser.add_argument(
        '--local',
        action='store_true',
        help='Local dev mode: bypass night mode and smart polling, auto-open output image'
    )

    args = parser.parse_args()

    # Display platform information
    system_platform = platform.system()
    print(f"Running on platform: {system_platform}")
    if system_platform == 'Darwin':
        print("Development mode - e-ink display updates will be skipped")

    # Read config to determine which sport to track
    config_data = load_yaml_file('config.yaml')

    # Night mode check
    night_mode = config_data.get('night_mode', False)
    if night_mode:
        night_start = config_data.get('night_start', 0)
        night_end = config_data.get('night_end', 7)
        tz = config_data.get('timezone', 'America/Chicago')
        local_tz = pytz.timezone(tz)
        now_local = datetime.now(local_tz)
        current_hour = now_local.hour
        if night_start >= night_end:
            # Window crosses midnight (e.g. 22 to 6): active if hour >= start OR hour < end
            in_night_window = current_hour >= night_start or current_hour < night_end
        else:
            # Window within same day (e.g. 0 to 7): active if start <= hour < end
            in_night_window = night_start <= current_hour < night_end
        if in_night_window:
            if args.local:
                print(f"Night mode: bypassed for local testing ({now_local.strftime('%H:%M')})")
            else:
                print(f"Night mode: skipping refresh ({now_local.strftime('%H:%M')})")
                return

    sport_names = {
        1: "MLB",
        8: "World Baseball Classic",
        11: "College Baseball",
        12: "Triple-A",
        13: "Double-A",
        14: "Winter Leagues",
        16: "Spring Training",
        51: "International"
    }

    dark_mode = config_data.get('dark_mode', False)

    # --- Discord state check ---
    # Apply any pending changes from the Discord bot before doing anything else
    discord_state = load_discord_state()
    if discord_state:
        user = discord_state.get('requested_by', 'unknown')
        mode_req = discord_state.get('pending_mode', '')
        team_req = discord_state.get('pending_team', '')
        print(f"Discord change requested by @{user}: mode={mode_req or '(unchanged)'} team={team_req or '(unchanged)'}")
        apply_discord_change(discord_state, config_data)
        overlay = render_discord_overlay(discord_state, dark_mode=dark_mode)
        display_image(overlay)
        mark_discord_state_applied()

    # Handle --sport-id override or --fetch-teams flag
    if args.sport_id:
        sport_id = args.sport_id
        print(f"Using specified sport: {sport_names.get(sport_id, f'Sport ID {sport_id}')}")

        # If --fetch-teams flag is set, fetch all teams and exit
        if args.fetch_teams:
            fetch_all_team_abbreviations(sport_id)
            return
    else:
        # Check if using priority list
        sport_id_priority = config_data.get('sport_id_priority')
        if sport_id_priority and isinstance(sport_id_priority, list):
            print(f"Using sport priority: {' > '.join([sport_names.get(sid, str(sid)) for sid in sport_id_priority])}")
            sport_id = None  # Let fetch_scoreboard_for_date handle priority
        else:
            sport_id = config_data.get('sport_id', 1)
            print(f"Tracking: {sport_names.get(sport_id, f'Sport ID {sport_id}')}")

        # If --fetch-teams flag is set with priority list, fetch for first priority
        if args.fetch_teams:
            if sport_id_priority:
                sport_id = sport_id_priority[0]
                print(f"Fetching teams for: {sport_names.get(sport_id, f'Sport ID {sport_id}')}")
            fetch_all_team_abbreviations(sport_id if sport_id else config_data.get('sport_id', 1))
            return

    # Get the date (from argument or use today)
    if args.date:
        date_str = args.date
        print(f"Using specified date: {date_str}")
    else:
        now = datetime.now().date()
        date_str = now.strftime('%Y-%m-%d')
        print(f"Using today's date: {date_str}")

    # --- Smart polling: rate-limit MLB API calls based on game state ---
    # Only applies when running on today's date (not a manual --date override or --local)
    if not args.date and not args.local:
        sched = load_schedule_state()

        # Skip entirely if next game is a future date
        next_game_date = sched.get('next_game_date')
        if next_game_date and next_game_date > date_str:
            print(f"No games until {next_game_date} — skipping API call")
            return

        # Determine polling interval from cached game state
        try:
            cached_games = (read_json_file('data/games.json') or {}).get('games', [])
        except Exception:
            cached_games = []

        _final_states = {'Final', 'Game Over', 'Final: Tied', 'Postponed', 'Delayed', 'Completed Early'}
        any_live = any(g.get('detailed_state') == 'In Progress' for g in cached_games)
        all_done = bool(cached_games) and all(g.get('detailed_state') in _final_states for g in cached_games)

        if any_live:
            # Game in progress — always fetch, no throttle
            interval_min = 0
        elif all_done:
            # All games finished — check once per hour (scores won't change)
            interval_min = 60
        elif not cached_games:
            # No cached data yet today — use hourly until we confirm games exist
            interval_min = 60
        else:
            # Pre-game / scheduled — respect update_interval from config
            interval_min = config_data.get('update_interval', 14)

        if interval_min > 0:
            last_fetch = sched.get('last_game_fetch')
            if last_fetch:
                try:
                    elapsed = datetime.now() - datetime.fromisoformat(last_fetch)
                    if elapsed < timedelta(minutes=interval_min):
                        mins = int(elapsed.total_seconds() // 60)
                        print(f"Throttled — {mins}min since last fetch (interval={interval_min}min, state={'all_done' if all_done else 'pre-game'})")
                        return
                except Exception:
                    pass

    fetch_scoreboard_for_date(date_str, sport_id)

    game_state_data = read_json_file('data/games.json')['games']
    team_data = read_json_file('data/teams.json')

    # Ensure team_data has the required structure
    if not team_data or 'team_abbreviation' not in team_data:
        team_data = {'team_abbreviation': {}}

    # After fetching: update schedule state
    if not args.date and not args.local:
        sched = load_schedule_state()
        sched['last_game_fetch'] = datetime.now().isoformat(timespec='seconds')
        if not game_state_data:
            # No games today — find and store the next game date
            priority = config_data.get('sport_id_priority', [1, 8, 16])
            tomorrow = (datetime.now().date() + timedelta(days=1)).strftime('%Y-%m-%d')
            next_date = find_next_game_date(priority, tomorrow)
            sched['next_game_date'] = next_date
            save_schedule_state(sched)
            if next_date:
                print(f"No games today. Next games: {next_date}")
            return
        else:
            sched.pop('next_game_date', None)
            save_schedule_state(sched)

    mode = _get_display_mode(config_data)

    if mode in ('field', 'scorecard', 'pitch'):
        _run_single_game_mode(mode, game_state_data, team_data, config_data)
        print(f"\n✓ {mode.title()} view generated successfully!")
        print(f"  View image at: resulting_image.bmp")
        if args.local and platform.system() == 'Darwin':
            import subprocess
            subprocess.run(['open', 'resulting_image.bmp'], check=False)
        return

    result = orchestrate_score_board(game_state_data, team_data, date_str)

    if result:
        sccoreboard_image, changed_regions = result
        if needs_full_refresh() or not changed_regions:
            print("Scoreboard: full refresh")
            display_image(sccoreboard_image)
        else:
            print(f"Scoreboard: partial refresh ({len(changed_regions)} region(s))")
            display_partial_regions(sccoreboard_image, changed_regions)
        print(f"\n✓ Scoreboard generated successfully!")
        print(f"  View image at: resulting_image.bmp")
        if args.local and platform.system() == 'Darwin':
            import subprocess
            subprocess.run(['open', 'resulting_image.bmp'], check=False)
    else:
        print("No display update needed - image unchanged")

if __name__ == '__main__':
    main()