import os
import json
import yaml


def load_json_file(file_name, file_path='data/'):
    data_dict = {}
    try:
        if not os.path.isfile(file_path + file_name):
            return data_dict
        with open(file_path + file_name, 'r') as file:
            data_dict = json.load(file)
            return data_dict
    except:
        print('parsing error in util returned empty payload')
        return data_dict


def load_yaml_file(file_name, file_path='config/'):
    data_dict = {}
    try:
        if not os.path.isfile(file_path + file_name):
            return data_dict
        with open(file_path + file_name, 'r') as file:
            data_dict = yaml.safe_load(file)
            return data_dict if data_dict else {}
    except Exception as e:
        print(f'Error parsing YAML file: {e}')
        return data_dict

   
def save_off_results(data, output, file_path='data/'):
    os.makedirs(file_path, exist_ok=True)
    with open(file_path + output + '.json', 'w') as f:
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