
import os 
import json


def load_json_file(file_name, file_path='data/'):
    data_dict = {}
    if not os.path.isfile(file_path + file_name):
        return data_dict
    with open(file_path + file_name, 'r') as file:
        data_dict = json.load(file)
        return data_dict

   
def save_off_results(data, output, file_path='data/'):
    with open(file_path + output + '.json', 'w') as f:
        json.dump(data, f, indent=4)
        
        