from generate_image import orchestrate_score_board
from fetch_games import fetch_win_probability, _fetch_pitcher_eras

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

SPORT_NAMES = {
    1: "MLB", 8: "World Baseball Classic", 11: "College Baseball",
    12: "Triple-A", 13: "Double-A", 14: "Winter Leagues",
    16: "Spring Training", 51: "International"
}

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


def parse_games(data, sport_id=None):

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

        # Extract nested dicts once to avoid repeated .get() chains
        game_teams = game.get('teams', {})
        away_team = game_teams.get('away', {})
        home_team = game_teams.get('home', {})
        away_team_info = away_team.get('team', {})
        home_team_info = home_team.get('team', {})
        linescore = game.get('linescore', {})
        ls_teams = linescore.get('teams', {})
        ls_away = ls_teams.get('away', {})
        ls_home = ls_teams.get('home', {})

        # Get team IDs
        away_team_id = away_team_info.get('id')
        home_team_id = home_team_info.get('id')

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
            current_inning = linescore.get('currentInning', 0) or 0
            away_runs = ls_away.get('runs') or 0
            home_runs = ls_home.get('runs') or 0
            run_diff = abs(away_runs - home_runs)
            if current_inning >= 7 and 1 <= run_diff <= 3:
                save_situation = True

        # Read abbreviations from the hydrated team data in the schedule response
        away_abbreviation = away_team_info.get('abbreviation')
        home_abbreviation = home_team_info.get('abbreviation')

        # Apply WBC abbreviation overrides (e.g. COL→CLM for Colombia) when sport is WBC
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

        if game_dict.get('detailed_state') == 'In Progress':
            away_wp, home_wp, last_play = fetch_win_probability(game_id)
            game_dict['last_play'] = last_play
            if config_data.get('scoreboard_win_probability', False):
                game_dict['away_win_probability'] = away_wp
                game_dict['home_win_probability'] = home_wp
            if config_data.get('scoreboard_live_details', False):
                from game_detail_fetch import fetch_scoreboard_live_extras
                extras = fetch_scoreboard_live_extras(game_id)
                game_dict.update(extras)

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
    try:
        with open(path) as f:
            state = json.load(f)
        if not state.get('applied', True):
            return state
    except (FileNotFoundError, Exception):
        pass
    return None


def mark_discord_state_applied():
    path = _data_path('discord_state.json')
    try:
        with open(path) as f:
            state = json.load(f)
        state['applied'] = True
        with open(path, 'w') as f:
            json.dump(state, f, indent=2)
    except (FileNotFoundError, Exception):
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
                # For MLB (sport_id=1), prefer regular/postseason games over spring training ('S')
                # but fall back to spring training if no regular games exist (avoids picking up
                # college baseball when spring training is the only MLB-affiliated action).
                if sport_id == 1:
                    regular = [g for g in games if g.get('gameType') not in ('S', 'E')]
                    if regular:
                        games = regular
                return len(games)
    except Exception as e:
        print(f"Error checking games for sport {sport_id}: {e}")

    return 0


def _local_time_to_timecode(date_str, time_str, timezone_str):
    """Convert local date+time to MLB API timecode in Eastern Time (YYYYMMDD_HHMMSS)."""
    eastern = pytz.timezone('America/New_York')
    local_tz = pytz.timezone(timezone_str)
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    dt_local = local_tz.localize(dt)
    dt_eastern = dt_local.astimezone(eastern)
    return dt_eastern.strftime("%Y%m%d_%H%M%S")


def fetch_scoreboard_for_date(date, sport_id=None, timecode=None):
    """
    Fetch scoreboard for a specific date and sport.

    Args:
        date: Date string in format 'YYYY-MM-DD'
        sport_id: Sport ID (1=MLB, 8=WBC, 11=College, etc.). If None, reads from config.
        timecode: Optional MLB API timecode (YYYYMMDD_HHMMSS in Eastern Time) to fetch
                  historical game state at a specific minute.

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
            print(f"Checking sports in priority order: {[SPORT_NAMES.get(sid, f'Sport {sid}') for sid in sport_id_priority]}")

            for sid in sport_id_priority:
                game_count = check_games_for_sport(date, sid)
                if game_count > 0:
                    print(f"✓ Found {game_count} game(s) for {SPORT_NAMES.get(sid, f'Sport {sid}')}")
                    sport_id = sid
                    break
                else:
                    print(f"  No games for {SPORT_NAMES.get(sid, f'Sport {sid}')}")

            # If no games found for any sport, use the first priority
            if sport_id is None:
                sport_id = sport_id_priority[0]
                print(f"No games found, defaulting to {SPORT_NAMES.get(sport_id, f'Sport {sport_id}')}")
        else:
            # Fall back to single sport_id
            sport_id = config_data.get('sport_id', 1)

    tc_info = f" @ {timecode}" if timecode else ""
    print(f"Fetching games for {date}{tc_info} (sportId={sport_id})")

    endpoint_url = (
        'https://statsapi.mlb.com/api/v1/schedule?'
        f'startDate={date}&endDate={date}&sportId={sport_id}&hydrate=decisions,probablePitcher(note),linescore,flags,team'
    )
    if timecode:
        endpoint_url += f'&timecode={timecode}'
    response = requests.get(endpoint_url)
    data = response.json()

    parse_games(data, sport_id)



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
        parse_games(game_data, sport_id)
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


_INNING_ORDINALS = {
    1:'1st', 2:'2nd', 3:'3rd', 4:'4th', 5:'5th', 6:'6th',
    7:'7th', 8:'8th', 9:'9th', 10:'10th', 11:'11th', 12:'12th',
    13:'13th', 14:'14th', 15:'15th', 16:'16th', 17:'17th', 18:'18th',
}

def _ordinal(n):
    try:
        return _INNING_ORDINALS.get(int(n), f'{n}th')
    except (TypeError, ValueError):
        return None


def _parse_mlb_time(time_str):
    """Parse an MLB API ISO timestamp to a UTC-aware datetime."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return pytz.utc.localize(datetime.strptime(time_str, fmt))
        except ValueError:
            continue
    raise ValueError(f"Cannot parse MLB timestamp: {time_str!r}")


_WP_SKIP_TYPES = ('substitution', 'timeout', 'advisory')


def _fetch_game_timeline(game_pk):
    """Fetch the full live feed for one game and return a play-by-play timeline.

    Returns a dict:
      scheduled_start_utc — UTC-aware datetime of scheduled first pitch
      first_pitch_utc     — UTC-aware datetime when first play began (or None)
      last_play_utc       — UTC-aware datetime when last play completed (or None)
      plays               — list of dicts sorted by end_time, each:
                              end_time, away_score, home_score, inning,
                              half_inning ('top'|'bottom'), outs
      pitch_events        — list of dicts sorted by time, one per pitch/action event:
                              time, balls, strikes, outs, inning, half_inning,
                              away_score, home_score
                            Used to reconstruct mid-at-bat state minute by minute.
      wp_events           — list of dicts sorted by time, one per completed play:
                              time, away_wp, home_wp, last_play
                            Win probability and last-play description at each play boundary.
    """
    url = f'https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live'
    resp = requests.get(url, timeout=20)
    data = resp.json()

    scheduled_start = None
    dt_str = data.get('gameData', {}).get('datetime', {}).get('dateTime', '')
    if dt_str:
        try:
            scheduled_start = _parse_mlb_time(dt_str)
        except ValueError:
            pass

    all_plays = data.get('liveData', {}).get('plays', {}).get('allPlays', [])
    timeline = []
    first_pitch = None
    pitch_events = []
    wp_events = []

    # Fetch win probability timeline (one entry per completed play)
    wp_by_index = {}
    try:
        wp_resp = requests.get(
            f'https://statsapi.mlb.com/api/v1/game/{game_pk}/winProbability',
            timeout=10,
        )
        wp_data = wp_resp.json()
        if isinstance(wp_data, list):
            for entry in wp_data:
                idx = entry.get('atBatIndex')
                if idx is not None:
                    wp_by_index[idx] = entry
    except Exception:
        pass

    # Running score: score after last completed play (used for pitch events mid-at-bat)
    running_away = 0
    running_home = 0
    cumulative_last_play = None  # last non-substitution event description seen so far

    for i, play in enumerate(all_plays):
        about  = play.get('about', {})
        result = play.get('result', {})
        inning      = about.get('inning', 1)
        half_inning = about.get('halfInning', 'top')

        if first_pitch is None:
            st = about.get('startTime', '')
            if st:
                try:
                    first_pitch = _parse_mlb_time(st)
                except ValueError:
                    pass

        # --- Extract pitch-level events for minute-by-minute state ---
        # Score during this at-bat = score as of the end of the last completed play.
        at_bat_away = running_away
        at_bat_home = running_home

        matchup = play.get('matchup', {})
        at_bat_pitcher = matchup.get('pitcher', {}).get('fullName') or ''
        at_bat_batter  = matchup.get('batter',  {}).get('fullName') or ''

        for ev in play.get('playEvents', []):
            ev_time_str = ev.get('startTime', '')
            if not ev_time_str:
                continue
            try:
                ev_time = _parse_mlb_time(ev_time_str)
            except ValueError:
                continue
            count = ev.get('count', {})
            pitch_events.append({
                'time':        ev_time,
                'balls':       count.get('balls', 0) or 0,
                'strikes':     count.get('strikes', 0) or 0,
                'outs':        count.get('outs', about.get('outs', 0)) or 0,
                'inning':      inning,
                'half_inning': half_inning,
                'away_score':  at_bat_away,
                'home_score':  at_bat_home,
                'pitcher':     at_bat_pitcher,
                'batter':      at_bat_batter,
            })

        # --- Completed-play timeline (for score/inning snapshots) ---
        if not about.get('isComplete', False):
            continue
        end_str = about.get('endTime', '')
        if not end_str:
            continue
        try:
            end_time = _parse_mlb_time(end_str)
        except ValueError:
            continue

        away_score = result.get('awayScore', 0) or 0
        home_score = result.get('homeScore', 0) or 0

        timeline.append({
            'end_time':    end_time,
            'away_score':  away_score,
            'home_score':  home_score,
            'inning':      inning,
            'half_inning': half_inning,
            'outs':        about.get('outs', 0),
            'outs_after':  play.get('count', {}).get('outs', 0) or 0,
            'pitcher':     at_bat_pitcher,
            'batter':      at_bat_batter,
        })

        running_away = away_score
        running_home = home_score

        # --- Win probability and last-play at this play boundary ---
        wp_entry = wp_by_index.get(i, {})
        away_wp = wp_entry.get('awayTeamWinProbability')
        home_wp = wp_entry.get('homeTeamWinProbability')
        if away_wp is not None:
            away_wp = float(away_wp)
            if away_wp <= 1.0:
                away_wp *= 100
        if home_wp is not None:
            home_wp = float(home_wp)
            if home_wp <= 1.0:
                home_wp *= 100

        # Advance last_play description (skip substitutions/timeouts)
        wp_result    = wp_entry.get('result', {})
        event        = wp_result.get('event') or result.get('event') or ''
        event_type   = (wp_result.get('eventType') or '').lower()
        if event and not any(s in event_type for s in _WP_SKIP_TYPES):
            cumulative_last_play = event

        wp_events.append({
            'time':      end_time,
            'away_wp':   away_wp,
            'home_wp':   home_wp,
            'last_play': cumulative_last_play,
        })

    timeline.sort(key=lambda p: p['end_time'])
    pitch_events.sort(key=lambda e: e['time'])
    wp_events.sort(key=lambda e: e['time'])

    return {
        'scheduled_start_utc': scheduled_start,
        'first_pitch_utc':     first_pitch,
        'last_play_utc':       timeline[-1]['end_time'] if timeline else None,
        'plays':               timeline,
        'pitch_events':        pitch_events,
        'wp_events':           wp_events,
    }


_TERMINAL_GAME_STATES = {'Postponed', 'Cancelled', 'Suspended'}


def _inning_runs_at_time(plays, target_utc):
    """Return (away_inning_runs, home_inning_runs) lists reconstructed from plays up to target_utc.

    Away team scores in 'top' halves; home team scores in 'bottom' halves.
    A None value in home_inning_runs means the bottom half hasn't been played yet.
    """
    half_final = {}
    for play in plays:
        if play['end_time'] > target_utc:
            break
        key = (play['inning'], play['half_inning'])
        half_final[key] = (play['away_score'], play['home_score'])

    if not half_final:
        return [], []

    max_inning = max(k[0] for k in half_final)
    away_runs = []
    home_runs = []
    prev_away = 0
    prev_home = 0

    for inn in range(1, max_inning + 1):
        top_key = (inn, 'top')
        bot_key = (inn, 'bottom')

        if top_key not in half_final:
            break
        top_away, _ = half_final[top_key]
        away_runs.append(top_away - prev_away)
        prev_away = top_away

        if bot_key in half_final:
            _, bot_home = half_final[bot_key]
            home_runs.append(bot_home - prev_home)
            prev_home = bot_home
        else:
            home_runs.append(None)

    return away_runs, home_runs


def _game_state_at_time(base_game, tl, target_utc):
    """Return a copy of base_game with dynamic fields set to game state at target_utc."""
    state = dict(base_game)

    # Preserve terminal non-game statuses (Postponed, Cancelled, Suspended).
    # These have no play data, so the timeline-based logic would otherwise
    # overwrite them with 'Scheduled'.
    if base_game.get('detailed_state') in _TERMINAL_GAME_STATES and not tl.get('plays'):
        return state

    scheduled_start = tl.get('scheduled_start_utc')
    first_pitch     = tl.get('first_pitch_utc') or scheduled_start
    last_play_time  = tl.get('last_play_utc')
    plays           = tl.get('plays', [])

    # --- Before first pitch ---
    if first_pitch and target_utc < first_pitch - timedelta(seconds=30):
        state.update({
            'detailed_state': 'Scheduled',
            'away_runs': None, 'home_runs': None,
            'current_inning': None, 'currentInningOrdinal': None, 'inningState': None,
            'num_of_outs': None, 'balls': None, 'strikes': None,
            'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None,
            'away_win_probability': None, 'home_win_probability': None, 'last_play': None,
        })
        return state

    # --- After last play with buffer ---
    if last_play_time and target_utc > last_play_time + timedelta(minutes=5):
        final = plays[-1] if plays else None
        state['detailed_state'] = 'Final'
        if final:
            state['away_runs']      = final['away_score']
            state['home_runs']      = final['home_score']
            state['current_inning'] = final['inning']
        state.update({
            'num_of_outs': None, 'balls': None, 'strikes': None,
            'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None,
            'inningState': None, 'away_win_probability': None,
            'home_win_probability': None,
        })
        # Keep last_play from final play if available
        wp_events = tl.get('wp_events', [])
        state['last_play'] = wp_events[-1]['last_play'] if wp_events else None
        return state

    # --- In Progress: reconstruct detailed state from pitch events and completed plays ---
    state['detailed_state'] = 'In Progress'
    pitch_events = tl.get('pitch_events', [])

    # Last pitch event before target_utc
    last_event = None
    for ev in pitch_events:
        if ev['time'] <= target_utc:
            last_event = ev
        else:
            break

    # Last completed play before target_utc
    last_play = None
    for play in plays:
        if play['end_time'] <= target_utc:
            last_play = play
        else:
            break

    # Between-plays: last play resolved AFTER the most recent pitch event.
    # This covers the inning break and the gap between plate appearances.
    between_plays = (
        last_play is not None and
        (last_event is None or last_play['end_time'] > last_event['time'])
    )

    if between_plays:
        outs_after = last_play.get('outs_after', 0)
        half = last_play.get('half_inning', 'top')
        state['away_runs']            = last_play['away_score']
        state['home_runs']            = last_play['home_score']
        state['current_inning']       = last_play['inning']
        state['currentInningOrdinal'] = _ordinal(last_play['inning'])
        state['num_of_outs']          = outs_after
        state['balls']                = 0
        state['strikes']              = 0
        state['current_pitcher']      = last_play.get('pitcher') or None
        # Find the first batter of the next half inning so "Due:" can be shown
        _next_event = next(
            (ev for ev in pitch_events if ev['time'] > last_play['end_time']),
            None,
        )
        state['current_hitter'] = _next_event.get('batter') if _next_event else None
        if outs_after >= 3:
            # Inning break: top half done → Mid, bottom half done → End
            state['inningState'] = 'Middle' if half == 'top' else 'End'
        else:
            state['inningState'] = 'Top' if half == 'top' else 'Bottom'
    elif last_event:
        # Mid-at-bat: pitch events are more recent than the last play completion
        state['away_runs']            = last_event['away_score']
        state['home_runs']            = last_event['home_score']
        state['current_inning']       = last_event['inning']
        state['currentInningOrdinal'] = _ordinal(last_event['inning'])
        state['num_of_outs']          = last_event['outs']
        state['balls']                = last_event['balls']
        state['strikes']              = last_event['strikes']
        state['current_pitcher']      = last_event.get('pitcher') or None
        state['current_hitter']       = last_event.get('batter') or None
        half = last_event.get('half_inning', 'top')
        state['inningState']          = 'Top' if half == 'top' else 'Bottom'
    else:
        # No pitch events and no completed plays at this timestamp —
        # the game hasn't officially started yet (no first pitch thrown).
        state.update({
            'detailed_state': 'Scheduled',
            'away_runs': None, 'home_runs': None,
            'current_inning': None, 'currentInningOrdinal': None,
            'inningState': None, 'num_of_outs': None,
            'balls': None, 'strikes': None,
            'current_pitcher': None, 'current_hitter': None,
        })

    # Reconstruct per-inning run lists from play history so linescore grid shows correct data.
    away_inn, home_inn = _inning_runs_at_time(plays, target_utc)
    state['away_inning_runs'] = away_inn
    state['home_inning_runs'] = home_inn

    # --- Win probability and last-play: find last wp_event before target_utc ---
    wp_events = tl.get('wp_events', [])
    last_wp = None
    for wp in wp_events:
        if wp['time'] <= target_utc:
            last_wp = wp
        else:
            break

    if last_wp:
        state['away_win_probability'] = last_wp['away_wp']
        state['home_win_probability'] = last_wp['home_wp']
        state['last_play']            = last_wp['last_play']
    else:
        state['away_win_probability'] = None
        state['home_win_probability'] = None
        state['last_play']            = None

    state.update({
        'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None,
    })
    return state


def _any_game_active(game_timelines, current_utc):
    """Return True if any game has had at least one pitch thrown by current_utc
    and hasn't ended more than 5 minutes ago.

    pitch_events includes pre-game advisory/action events (mound visits, lineup
    substitutions) with count 0-0.  Use the first event where balls+strikes > 0
    (an actual pitch registered) or the first completed play, so pre-game
    advisory events don't count as the game start.
    """
    for tl in game_timelines.values():
        last_play    = tl.get('last_play_utc')
        pitch_events = tl.get('pitch_events', [])
        plays        = tl.get('plays', [])

        # First pitch event that registered a ball or strike
        game_start = None
        for ev in pitch_events:
            if (ev.get('balls', 0) or 0) + (ev.get('strikes', 0) or 0) > 0:
                game_start = ev['time']
                break
        # Fall back to first completed play (handles first-pitch-hit where count stays 0-0)
        if game_start is None and plays:
            game_start = plays[0]['end_time']
        # Last resort: first_pitch_utc from the schedule
        if game_start is None:
            game_start = tl.get('first_pitch_utc')

        if not game_start or current_utc < game_start:
            continue
        game_end = (last_play + timedelta(minutes=5)) if last_play else (game_start + timedelta(hours=4))
        if current_utc <= game_end:
            return True
    return False


def _generate_gif(date_str, gif_start, gif_end, output_path, interval_min, frame_delay_ms, sport_id, config_data):
    """Generate an animated GIF of the scoreboard for a game day.

    Fetches each game's full play-by-play feed once (O(N_games) API calls),
    then reconstructs game state at every minute in memory — no per-minute
    API calls.  Time window is auto-detected from first pitch / last play
    when --gif-start / --gif-end are not provided.
    """
    from generate_image import orchestrate_score_board

    tz_str   = config_data.get('timezone', 'America/Chicago')
    local_tz = pytz.timezone(tz_str)

    # --- Step 1: Fetch base schedule (final/current state for team/game metadata) ---
    print(f"Fetching schedule for {date_str}...")
    fetch_scoreboard_for_date(date_str, sport_id)
    base_games = read_json_file('data/games.json').get('games', [])
    team_data  = read_json_file('data/teams.json') or {}
    if 'team_abbreviation' not in team_data:
        team_data = {'team_abbreviation': {}}

    if not base_games:
        print(f"No games found for {date_str}")
        return

    # --- Step 1b: Fetch standings as of this date so wildcard/division data is accurate ---
    print(f"Fetching standings for {date_str}...")
    try:
        from standings import get_standings
        from datetime import datetime as _dt, timedelta as _td
        _date_obj = _dt.strptime(date_str, '%Y-%m-%d')
        get_standings([103, 104], season=_date_obj.year, date=_date_obj.strftime('%m/%d/%Y'))
        print("  standings ok")
        _prev_date = _date_obj - _td(days=1)
        get_standings([103, 104], season=_prev_date.year,
                      date=_prev_date.strftime('%m/%d/%Y'), save_as='standings_prev')
        print("  prev standings ok")
    except Exception as _e:
        print(f"  standings error: {_e} (using cached)")

    # --- Step 2: Fetch play-by-play timeline once per game ---
    print(f"Fetching play-by-play for {len(base_games)} game(s)...")
    game_timelines   = {}
    all_first_pitches = []
    all_last_plays    = []

    for game in base_games:
        game_pk = game.get('game_pk')
        if not game_pk:
            continue
        print(f"  game {game_pk}...", end=' ', flush=True)
        try:
            tl = _fetch_game_timeline(game_pk)
            game_timelines[str(game_pk)] = tl
            anchor = tl.get('first_pitch_utc') or tl.get('scheduled_start_utc')
            if anchor:
                all_first_pitches.append(anchor)
            if tl.get('last_play_utc'):
                all_last_plays.append(tl['last_play_utc'])
            print("ok")
        except Exception as e:
            print(f"error: {e}")

    if not game_timelines:
        print("No timeline data fetched — aborting.")
        return

    # --- Step 3: Determine time window ---
    if gif_start and gif_end:
        start_dt = local_tz.localize(datetime.strptime(f"{date_str} {gif_start}", "%Y-%m-%d %H:%M"))
        end_dt   = local_tz.localize(datetime.strptime(f"{date_str} {gif_end}",   "%Y-%m-%d %H:%M"))
    else:
        if not all_first_pitches:
            print("Cannot determine start time — provide --gif-start/--gif-end")
            return
        start_utc = min(all_first_pitches)
        end_utc   = (max(all_last_plays) + timedelta(minutes=5)) if all_last_plays \
                    else max(all_first_pitches) + timedelta(hours=4)
        start_dt = start_utc.astimezone(local_tz)
        end_dt   = end_utc.astimezone(local_tz)
        print(f"Auto-detected window: {start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')} {tz_str}")

    if end_dt <= start_dt:
        print("End time is before start time — aborting.")
        return

    total_steps = int((end_dt - start_dt).total_seconds() / 60 / interval_min) + 1
    print(f"Generating {total_steps}-frame GIF ({interval_min}min intervals, {frame_delay_ms}ms/frame)")
    print(f"  Output: {output_path}")

    # --- Step 4: Render each frame from in-memory timelines ---
    frames = []
    current_dt = start_dt
    step = 0

    while current_dt <= end_dt:
        step += 1
        current_utc = current_dt.astimezone(pytz.utc)
        time_label  = current_dt.strftime("%H:%M")

        if not _any_game_active(game_timelines, current_utc):
            print(f"  [    dead] {current_dt.strftime('%H:%M')} — no active games, skipping")
            current_dt += timedelta(minutes=interval_min)
            continue

        print(f"  [{step:4d}/{total_steps}] {time_label}...", end=' ', flush=True)

        frame_games = []
        for game in base_games:
            pk_str = str(game.get('game_pk', ''))
            tl = game_timelines.get(pk_str)
            frame_games.append(_game_state_at_time(game, tl, current_utc) if tl else dict(game))

        try:
            result = orchestrate_score_board(frame_games, team_data, date_str, bypass_cache=True)
            if result:
                image, _ = result
                frames.append(image.convert('L').convert('P'))
                print("ok")
            else:
                print("skip")
        except Exception as e:
            print(f"error: {e}")

        current_dt += timedelta(minutes=interval_min)

    # --- Step 5: Save GIF ---
    if not frames:
        print("No frames generated — GIF not saved.")
        return

    print(f"Assembling {len(frames)}-frame GIF...")
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        optimize=False,
        duration=frame_delay_ms,
        loop=0,
    )
    print(f"✓ GIF saved to {output_path}")

    mp4_path = os.path.splitext(output_path)[0] + '.mp4'
    try:
        import imageio
        import numpy as np
        fps = 1000 / frame_delay_ms
        writer = imageio.get_writer(mp4_path, fps=fps, codec='libx264', quality=8)
        for frame in frames:
            writer.append_data(np.array(frame.convert('RGB')))
        writer.close()
        print(f"✓ MP4 saved to {mp4_path}")
    except ImportError:
        print("imageio not installed — skipping MP4 (pip install imageio[ffmpeg])")


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

  # Time-travel: show scoreboard as it appeared at 7:32 PM local time
  python scoreboard_generate.py --date 2025-04-01 --time 19:32

  # Generate a GIF for the full game day (auto-detects first pitch to last out)
  python scoreboard_generate.py --date 2025-04-01 --gif

  # GIF with manual window override
  python scoreboard_generate.py --date 2025-04-01 --gif --gif-start 18:00 --gif-end 23:00 --gif-interval 5 --gif-delay 300

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
        '--time',
        type=str,
        metavar='HH:MM',
        help='Time-travel: show the scoreboard as it appeared at this local time on --date'
    )
    parser.add_argument(
        '--gif',
        action='store_true',
        help='Generate a GIF for --date (auto-detects time window from first pitch to last out)'
    )
    parser.add_argument(
        '--gif-start',
        type=str,
        metavar='HH:MM',
        help='GIF start time override (local HH:MM). Auto-detected if omitted.'
    )
    parser.add_argument(
        '--gif-end',
        type=str,
        metavar='HH:MM',
        help='GIF end time (local, HH:MM). Requires --date and --gif-start.'
    )
    parser.add_argument(
        '--gif-output',
        type=str,
        metavar='FILE',
        default='scoreboard_timelapse.gif',
        help='Output path for the generated GIF (default: scoreboard_timelapse.gif)'
    )
    parser.add_argument(
        '--gif-interval',
        type=int,
        metavar='MINUTES',
        default=1,
        help='Minutes between each GIF frame (default: 1)'
    )
    parser.add_argument(
        '--gif-delay',
        type=int,
        metavar='MS',
        default=500,
        help='Delay between GIF frames in milliseconds (default: 500)'
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

    # --gif-start and --gif-end must always be used together
    if bool(args.gif_start) != bool(args.gif_end):
        parser.error("--gif-start and --gif-end must be used together")
    # --gif / --gif-start / --gif-end all require --date
    gif_mode = args.gif or bool(args.gif_start)
    if gif_mode and not args.date:
        parser.error("--gif / --gif-start / --gif-end require --date")
    if args.time and not args.date:
        parser.error("--time requires --date")

    # Time-travel and GIF modes are treated as explicit offline requests — bypass
    # night mode, smart polling, and Discord state checks.
    offline_mode = bool(args.time or gif_mode or args.local)

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
            if offline_mode:
                print(f"Night mode: bypassed for offline/local request ({now_local.strftime('%H:%M')})")
            else:
                print(f"Night mode: skipping refresh ({now_local.strftime('%H:%M')})")
                return

    dark_mode = config_data.get('dark_mode', False)

    # --- Discord state check ---
    # Skip Discord changes for offline/time-travel/GIF modes — they're historical queries.
    discord_state = None if offline_mode else load_discord_state()
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
        print(f"Using specified sport: {SPORT_NAMES.get(sport_id, f'Sport ID {sport_id}')}")

        # If --fetch-teams flag is set, fetch all teams and exit
        if args.fetch_teams:
            fetch_all_team_abbreviations(sport_id)
            return
    else:
        # Check if using priority list
        sport_id_priority = config_data.get('sport_id_priority')
        if sport_id_priority and isinstance(sport_id_priority, list):
            print(f"Using sport priority: {' > '.join([SPORT_NAMES.get(sid, str(sid)) for sid in sport_id_priority])}")
            sport_id = None  # Let fetch_scoreboard_for_date handle priority
        else:
            sport_id = config_data.get('sport_id', 1)
            print(f"Tracking: {SPORT_NAMES.get(sport_id, f'Sport ID {sport_id}')}")

        # If --fetch-teams flag is set with priority list, fetch for first priority
        if args.fetch_teams:
            if sport_id_priority:
                sport_id = sport_id_priority[0]
                print(f"Fetching teams for: {SPORT_NAMES.get(sport_id, f'Sport ID {sport_id}')}")
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

    # --- GIF generation mode ---
    if gif_mode:
        gif_output = args.gif_output
        if gif_output == 'scoreboard_timelapse.gif':
            gif_output = f'scoreboard_{date_str}.gif'
        _generate_gif(
            date_str,
            args.gif_start or None,  # None triggers auto-detection
            args.gif_end   or None,
            gif_output, args.gif_interval, args.gif_delay,
            sport_id, config_data,
        )
        return

    # --- Smart polling: rate-limit MLB API calls based on game state ---
    # Only applies when running on today's date without any offline/explicit flags
    if not args.date and not offline_mode:
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
            polling_interval = 0
        elif all_done:
            # All games finished — check once per hour (scores won't change)
            polling_interval = 60
        elif not cached_games:
            # No cached data yet today — use hourly until we confirm games exist
            polling_interval = 60
        else:
            # Pre-game / scheduled — respect update_interval from config
            polling_interval = config_data.get('update_interval', 14)

        if polling_interval > 0:
            last_fetch = sched.get('last_game_fetch')
            if last_fetch:
                try:
                    elapsed = datetime.now() - datetime.fromisoformat(last_fetch)
                    if elapsed < timedelta(minutes=polling_interval):
                        mins = int(elapsed.total_seconds() // 60)
                        print(f"Throttled — {mins}min since last fetch (interval={polling_interval}min, state={'all_done' if all_done else 'pre-game'})")
                        return
                except Exception:
                    pass

    # --- Time-travel: convert local HH:MM to MLB API timecode ---
    timecode = None
    if args.time:
        tz_str = config_data.get('timezone', 'America/Chicago')
        timecode = _local_time_to_timecode(date_str, args.time, tz_str)
        print(f"Time-travel: {date_str} {args.time} ({tz_str}) → timecode {timecode} ET")

    fetch_scoreboard_for_date(date_str, sport_id, timecode=timecode)

    game_state_data = read_json_file('data/games.json')['games']
    team_data = read_json_file('data/teams.json')

    # Ensure team_data has the required structure
    if not team_data or 'team_abbreviation' not in team_data:
        team_data = {'team_abbreviation': {}}

    # After fetching: update schedule state (only for normal live-polling runs)
    if not args.date and not offline_mode:
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
        if offline_mode and platform.system() == 'Darwin':
            import subprocess
            subprocess.run(['open', 'resulting_image.bmp'], check=False)
        return

    # bypass_cache=True for time-travel so the image always renders (no stale-state skip)
    result = orchestrate_score_board(game_state_data, team_data, date_str,
                                     bypass_cache=bool(args.time))

    if result:
        sccoreboard_image, changed_regions = result
        if args.time:
            # Time-travel: just save the image, no e-ink update
            sccoreboard_image.save('resulting_image.bmp')
            print(f"\n✓ Time-travel snapshot saved to resulting_image.bmp")
        else:
            if needs_full_refresh() or not changed_regions:
                print("Scoreboard: full refresh")
                display_image(sccoreboard_image)
            else:
                print(f"Scoreboard: partial refresh ({len(changed_regions)} region(s))")
                display_partial_regions(sccoreboard_image, changed_regions)
            print(f"\n✓ Scoreboard generated successfully!")
            print(f"  View image at: resulting_image.bmp")
        if offline_mode and platform.system() == 'Darwin':
            import subprocess
            subprocess.run(['open', 'resulting_image.bmp'], check=False)
    else:
        print("No display update needed - image unchanged")

if __name__ == '__main__':
    main()