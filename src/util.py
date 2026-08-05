import os
import json
import yaml

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_REPO_ROOT, 'data')
_CONFIG_DIR = os.path.join(_REPO_ROOT, 'config')


def in_hour_window(start_hour, end_hour, hour):
    """True when ``hour`` falls inside the [start, end) window of a 24h clock.

    Windows may wrap past midnight (start 20, end 7 covers 20:00–06:59).

    ``start == end`` is an EMPTY window, not a 24-hour one. Treating it as
    always-inside would let a single config value (e.g. night_start and
    night_end both 0) suppress every refresh and freeze the display
    indefinitely, with no obvious cause. Disabling a window is what the
    explicit night_mode: false flag is for, so the harmless reading wins.
    """
    if start_hour == end_hour:
        return False
    if start_hour > end_hour:  # wraps past midnight
        return hour >= start_hour or hour < end_hour
    return start_hour <= hour < end_hour


def load_json_file(file_name, file_path=None):
    """Load a JSON file from the data directory (or file_path if given), returning {} on missing/error."""
    base = file_path if file_path is not None else _DATA_DIR
    full = os.path.join(base, file_name)
    data_dict = {}
    try:
        if not os.path.isfile(full):
            return data_dict
        with open(full, 'r') as file:
            data_dict = json.load(file)
            return data_dict
    except (OSError, ValueError):
        print('parsing error in util returned empty payload')
        return data_dict


def load_yaml_file(file_name, file_path=None):
    """Load a YAML file from the config directory (or file_path if given), returning {} on missing/error."""
    base = file_path if file_path is not None else _CONFIG_DIR
    full = os.path.join(base, file_name)
    data_dict = {}
    try:
        if not os.path.isfile(full):
            return data_dict
        with open(full, 'r') as file:
            data_dict = yaml.safe_load(file)
            return data_dict if data_dict else {}
    except Exception as e:
        print(f'Error parsing YAML file: {e}')
        return data_dict


def save_off_results(data, output, file_path=None):
    """Save off results."""
    base = file_path if file_path is not None else _DATA_DIR
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, output + '.json'), 'w') as f:
        json.dump(data, f, indent=4)


def merge_team_abbreviations():
    """
    Merge team abbreviations from standings.json and teams.json.
    This ensures we have abbreviations for all teams including spring training teams.
    """
    standings_data = load_json_file('standings.json')
    teams_data = load_json_file('teams.json')

    # Start with existing team data
    all_abbreviations = teams_data.get('team_abbreviation', {})

    # Merge in standings data
    if standings_data and 'team_abbreviation' in standings_data:
        all_abbreviations.update(standings_data.get('team_abbreviation', {}))

    # Save the merged data
    save_off_results({'team_abbreviation': all_abbreviations}, 'teams')

    return all_abbreviations