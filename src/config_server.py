"""Mobile-first local web server for editing config/config.yaml and .env.

Standalone entry point, run separately from the cron-triggered main.py
pipeline (it doesn't render or fetch anything itself):

    poetry run python src/config_server.py

Binds 0.0.0.0:<config_server_port> (default 8080) so it's reachable from any
phone on the same network. No authentication — trusts the local network.

config/config.yaml is heavily hand-commented, so writes go through
_set_yaml_scalar() (a line-based patch: find "key:", replace only the value)
rather than a full yaml.safe_dump() round-trip, which would strip every
comment. Same idea for .env via _set_env_var().
"""
import argparse
import os
import re
import sys

# Allow running as a standalone script from any directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, redirect, render_template, request, url_for  # noqa: E402

import config_loader  # noqa: E402

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates')

app = Flask(__name__, template_folder=_TEMPLATE_DIR)

# Curated set of settings worth changing from a phone. Anything not listed
# here is left alone — this is deliberately not a full config editor.
FIELD_SPECS = [
    {'key': 'primary', 'source': 'yaml', 'type': 'text',
     'label': 'Primary Team', 'help': 'Abbreviation shown first / highlighted, e.g. NYY'},
    {'key': 'display_mode', 'source': 'yaml', 'type': 'select',
     'label': 'Display Mode', 'options': ['scoreboard', 'linescore', 'field', 'scorecard', 'pitch']},
    {'key': 'league_mode', 'source': 'yaml', 'type': 'select',
     'label': 'League Mode', 'options': ['mlb', 'aaa']},
    {'key': 'dark_mode', 'source': 'yaml', 'type': 'bool', 'label': 'Dark Mode'},
    {'key': 'use_team_logos', 'source': 'yaml', 'type': 'bool', 'label': 'Team Logos'},
    {'key': 'show_standings_sidebar', 'source': 'yaml', 'type': 'bool', 'label': 'Standings Sidebar'},
    {'key': 'show_wildcard_standings', 'source': 'yaml', 'type': 'bool', 'label': 'Wildcard Standings Strip'},
    {'key': 'wide_cell_always', 'source': 'yaml', 'type': 'bool', 'label': 'Always Show Wide Cell'},
    {'key': 'show_config_qr', 'source': 'yaml', 'type': 'bool', 'label': 'Show Config QR Code'},
    {'key': 'FEATURED_TEAM_FULLSCREEN', 'source': 'env', 'type': 'bool', 'label': 'Fullscreen Featured Game'},
    {'key': 'LEAGUE_MODE', 'source': 'env', 'type': 'select',
     'label': 'League Mode Override (.env)', 'options': ['', 'mlb', 'aaa'],
     'help': 'Overrides League Mode above when set. Leave blank to use it.'},
]

def _set_yaml_scalar(path, key, value):
    """Patch a single top-level "key: value" line in a YAML file in place,
    leaving every comment/blank-line/other key untouched. Appends the line
    if the key isn't present yet."""
    with open(path) as f:
        lines = f.readlines()
    pattern = re.compile(rf'^{re.escape(key)}:\s')
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f'{key}: {value}\n'
            break
    else:
        lines.append(f'{key}: {value}\n')
    with open(path, 'w') as f:
        f.writelines(lines)


def _set_env_var(path, key, value):
    """Patch a single "KEY=value" line in a .env file in place, appending
    it if the key isn't present yet (and the file itself if missing)."""
    lines = []
    if os.path.exists(path):
        with open(path) as f:
            lines = f.readlines()
    pattern = re.compile(rf'^{re.escape(key)}=')
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f'{key}={value}\n'
            break
    else:
        lines.append(f'{key}={value}\n')
    with open(path, 'w') as f:
        f.writelines(lines)


def _current_values():
    config = config_loader.load_config()
    env = config_loader.read_env_file()
    values = {}
    for spec in FIELD_SPECS:
        if spec['source'] == 'yaml':
            values[spec['key']] = config.get(spec['key'])
        else:
            values[spec['key']] = env.get(spec['key'], '')
    return values


@app.route('/', methods=['GET'])
def index():
    return render_template(
        'config_server.html',
        fields=FIELD_SPECS,
        values=_current_values(),
        saved=request.args.get('saved') == '1',
    )


@app.route('/save', methods=['POST'])
def save():
    for spec in FIELD_SPECS:
        key = spec['key']
        path = config_loader._DEFAULT_CONFIG if spec['source'] == 'yaml' else config_loader._ENV_FILE
        if spec['type'] == 'bool':
            value = 'true' if request.form.get(key) == 'on' else 'false'
        elif spec['source'] == 'yaml':
            # Quote so bare team abbreviations / mode strings are always
            # valid YAML scalars regardless of characters typed in.
            value = f'"{request.form.get(key, "").strip()}"'
        else:
            value = request.form.get(key, '').strip()

        if spec['source'] == 'yaml':
            _set_yaml_scalar(path, key, value)
        else:
            _set_env_var(path, key, value)

    return redirect(url_for('index', saved='1'))


def main():
    parser = argparse.ArgumentParser(description='Mobile-first config editor for mlb_display.')
    parser.add_argument('--port', type=int, default=None, help='Override config_server_port from config.yaml')
    args = parser.parse_args()

    config = config_loader.load_config()
    port = args.port or config.get('config_server_port', 8080)
    app.run(host='0.0.0.0', port=port)  # noqa: S104 -- deliberately LAN-reachable, no auth by design


if __name__ == '__main__':
    main()
