"""Tests for src/config_server.py — the mobile config web server.

Covers the Flask routes (GET /, POST /save) and the line-based YAML/.env
patchers that write back changes without disturbing comments.
"""
import os

import pytest

import config_loader
import config_server

SAMPLE_YAML = """\
# MLB Display Configuration
# scoreboard: true = 15 game grid, false = 2 detailed linescores + standings
scoreboard: true

display_mode: "scoreboard"

primary: NYY
primary_backup: BOS

league_mode: mlb

use_team_logos: True
show_standings_sidebar: true
show_wildcard_standings: true
wide_cell_always: false
show_leaders_panel: false
show_debug_overlay: false
"""

SAMPLE_ENV = """\
# Copy this file to .env and fill in your values.
LEAGUE_MODE=mlb
ODDS_API_KEY=your_key_here
FEATURED_TEAM_FULLSCREEN=false
"""


@pytest.fixture
def isolated_files(tmp_path, monkeypatch):
    """Point config_loader (and therefore config_server) at throwaway copies
    of config.yaml / .env so tests never touch the real repo files."""
    yaml_path = tmp_path / 'config.yaml'
    env_path = tmp_path / '.env'
    yaml_path.write_text(SAMPLE_YAML)
    env_path.write_text(SAMPLE_ENV)
    monkeypatch.setattr(config_loader, '_DEFAULT_CONFIG', str(yaml_path))
    monkeypatch.setattr(config_loader, '_ENV_FILE', str(env_path))
    return yaml_path, env_path


@pytest.fixture
def client():
    config_server.app.testing = True
    return config_server.app.test_client()


# ---------------------------------------------------------------------------
# read_env_file / _load_dotenv (config_loader.py)
# ---------------------------------------------------------------------------

def test_read_env_file_parses_key_value_pairs(isolated_files):
    _, env_path = isolated_files
    result = config_loader.read_env_file(str(env_path))
    assert result == {
        'LEAGUE_MODE': 'mlb',
        'ODDS_API_KEY': 'your_key_here',
        'FEATURED_TEAM_FULLSCREEN': 'false',
    }


def test_read_env_file_missing_file_returns_empty_dict(tmp_path):
    assert config_loader.read_env_file(str(tmp_path / 'nope.env')) == {}


def test_load_dotenv_does_not_overwrite_existing_env(isolated_files, monkeypatch):
    monkeypatch.setenv('LEAGUE_MODE', 'aaa')
    config_loader._load_dotenv()
    assert os.environ['LEAGUE_MODE'] == 'aaa'


# ---------------------------------------------------------------------------
# _set_yaml_scalar / _set_env_var
# ---------------------------------------------------------------------------

def test_set_yaml_scalar_preserves_comments_and_other_keys(isolated_files):
    yaml_path, _ = isolated_files
    before = yaml_path.read_text()
    config_server._set_yaml_scalar(str(yaml_path), 'primary', '"BOS"')
    after = yaml_path.read_text()

    assert 'primary: "BOS"' in after
    # Every comment line from the original file must still be present verbatim.
    for line in before.splitlines():
        if line.strip().startswith('#'):
            assert line in after
    # Untouched keys must be byte-for-byte identical.
    assert 'primary_backup: BOS' in after
    assert 'show_leaders_panel: false' in after


def test_set_yaml_scalar_appends_when_key_absent(isolated_files):
    yaml_path, _ = isolated_files
    config_server._set_yaml_scalar(str(yaml_path), 'show_config_qr', 'true')
    after = yaml_path.read_text()
    assert 'show_config_qr: true' in after


def test_set_env_var_replaces_existing_key(isolated_files):
    _, env_path = isolated_files
    config_server._set_env_var(str(env_path), 'LEAGUE_MODE', 'aaa')
    after = env_path.read_text()
    assert 'LEAGUE_MODE=aaa' in after
    assert 'ODDS_API_KEY=your_key_here' in after  # untouched


def test_set_env_var_appends_when_key_absent(isolated_files):
    _, env_path = isolated_files
    config_server._set_env_var(str(env_path), 'NEW_KEY', 'value')
    after = env_path.read_text()
    assert 'NEW_KEY=value' in after


def test_set_env_var_creates_file_if_missing(tmp_path):
    env_path = tmp_path / '.env'
    assert not env_path.exists()
    config_server._set_env_var(str(env_path), 'FOO', 'bar')
    assert env_path.read_text() == 'FOO=bar\n'


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

def test_index_renders_current_values(client, isolated_files):
    resp = client.get('/')
    assert resp.status_code == 200
    assert b'NYY' in resp.data
    assert b'Primary Team' in resp.data


def test_index_shows_saved_banner_when_query_param_set(client, isolated_files):
    resp = client.get('/?saved=1')
    assert b'Saved' in resp.data
    resp2 = client.get('/')
    assert b'Saved' not in resp2.data


def test_save_updates_yaml_bool_field(client, isolated_files):
    yaml_path, env_path = isolated_files
    resp = client.post('/save', data={
        'primary': 'BOS', 'display_mode': 'scoreboard', 'league_mode': 'mlb',
        'show_leaders_panel': 'on', 'use_team_logos': 'on', 'show_standings_sidebar': 'on',
        'show_wildcard_standings': 'on', 'wide_cell_always': '',
        'show_config_qr': 'on', 'show_debug_overlay': '',
        'FEATURED_TEAM_FULLSCREEN': '', 'LEAGUE_MODE': 'mlb',
    })
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/?saved=1'
    after = yaml_path.read_text()
    assert 'primary: "BOS"' in after
    assert 'wide_cell_always: false' in after


def test_save_unchecked_checkbox_writes_false(client, isolated_files):
    yaml_path, _ = isolated_files
    client.post('/save', data={
        'primary': 'NYY', 'display_mode': 'scoreboard', 'league_mode': 'mlb',
        # show_leaders_panel omitted entirely == unchecked checkbox
        'use_team_logos': 'on', 'show_standings_sidebar': 'on',
        'show_wildcard_standings': 'on', 'wide_cell_always': '',
        'show_config_qr': '', 'show_debug_overlay': 'on',
        'FEATURED_TEAM_FULLSCREEN': '', 'LEAGUE_MODE': 'mlb',
    })
    after = yaml_path.read_text()
    assert 'show_leaders_panel: false' in after


def test_save_env_field(client, isolated_files):
    _, env_path = isolated_files
    client.post('/save', data={
        'primary': 'NYY', 'display_mode': 'scoreboard', 'league_mode': 'mlb',
        'show_leaders_panel': 'on', 'use_team_logos': 'on', 'show_standings_sidebar': 'on',
        'show_wildcard_standings': 'on', 'wide_cell_always': '',
        'show_config_qr': 'on', 'show_debug_overlay': '',
        'FEATURED_TEAM_FULLSCREEN': 'on', 'LEAGUE_MODE': 'aaa',
    })
    after = env_path.read_text()
    assert 'FEATURED_TEAM_FULLSCREEN=true' in after
    assert 'LEAGUE_MODE=aaa' in after
