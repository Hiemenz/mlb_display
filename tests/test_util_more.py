"""Additional coverage for src/util.py gaps: file-not-found / malformed-file
branches of load_json_file/load_yaml_file, save_off_results(), and
merge_team_abbreviations()."""
import json
from unittest.mock import patch

import pytest

import util


# ===========================================================================
# load_json_file
# ===========================================================================

class TestLoadJsonFile:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        """Missing file returns empty dict."""
        result = util.load_json_file('does_not_exist.json', file_path=str(tmp_path))
        assert result == {}

    def test_valid_file_returns_data(self, tmp_path):
        """Valid file returns data."""
        p = tmp_path / 'data.json'
        p.write_text(json.dumps({'a': 1}))
        result = util.load_json_file('data.json', file_path=str(tmp_path))
        assert result == {'a': 1}

    def test_malformed_json_returns_empty_dict_and_prints(self, tmp_path, capsys):
        """Malformed json returns empty dict and prints."""
        p = tmp_path / 'bad.json'
        p.write_text('{not valid json')
        result = util.load_json_file('bad.json', file_path=str(tmp_path))
        assert result == {}
        captured = capsys.readouterr()
        assert 'parsing error' in captured.out

    def test_oserror_returns_empty_dict(self, tmp_path):
        """Oserror returns empty dict."""
        p = tmp_path / 'data.json'
        p.write_text(json.dumps({'a': 1}))
        with patch('builtins.open', side_effect=OSError('boom')):
            result = util.load_json_file('data.json', file_path=str(tmp_path))
        assert result == {}

    def test_default_path_used_when_none(self):
        """Default path used when none."""
        # No file_path passed -> uses _DATA_DIR; just confirm no crash and dict/list-like return.
        result = util.load_json_file('definitely_missing_file_xyz.json')
        assert result == {}


# ===========================================================================
# load_yaml_file
# ===========================================================================

class TestLoadYamlFile:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        """Missing file returns empty dict."""
        result = util.load_yaml_file('does_not_exist.yaml', file_path=str(tmp_path))
        assert result == {}

    def test_valid_file_returns_data(self, tmp_path):
        """Valid file returns data."""
        p = tmp_path / 'config.yaml'
        p.write_text('key: value\nnum: 5\n')
        result = util.load_yaml_file('config.yaml', file_path=str(tmp_path))
        assert result == {'key': 'value', 'num': 5}

    def test_empty_yaml_returns_empty_dict(self, tmp_path):
        """Empty yaml returns empty dict."""
        p = tmp_path / 'empty.yaml'
        p.write_text('')
        result = util.load_yaml_file('empty.yaml', file_path=str(tmp_path))
        assert result == {}

    def test_malformed_yaml_returns_empty_dict_and_prints(self, tmp_path, capsys):
        """Malformed yaml returns empty dict and prints."""
        p = tmp_path / 'bad.yaml'
        # Unbalanced flow mapping triggers a yaml.YAMLError
        p.write_text('key: [unterminated\n')
        result = util.load_yaml_file('bad.yaml', file_path=str(tmp_path))
        assert result == {}
        captured = capsys.readouterr()
        assert 'Error parsing YAML file' in captured.out


# ===========================================================================
# save_off_results
# ===========================================================================

class TestSaveOffResults:
    def test_writes_json_file(self, tmp_path):
        """Writes json file."""
        util.save_off_results({'a': 1}, 'myoutput', file_path=str(tmp_path))
        out = tmp_path / 'myoutput.json'
        assert out.exists()
        assert json.loads(out.read_text()) == {'a': 1}

    def test_creates_directory_if_missing(self, tmp_path):
        """Creates directory if missing."""
        target_dir = tmp_path / 'nested'
        util.save_off_results({'x': 2}, 'out', file_path=str(target_dir))
        assert (target_dir / 'out.json').exists()


# ===========================================================================
# merge_team_abbreviations
# ===========================================================================

class TestMergeTeamAbbreviations:
    def test_merges_standings_into_teams(self, tmp_path, monkeypatch):
        """Merges standings into teams."""
        monkeypatch.setattr(util, '_DATA_DIR', str(tmp_path))
        (tmp_path / 'teams.json').write_text(json.dumps({
            'team_abbreviation': {'147': 'NYY'},
        }))
        (tmp_path / 'standings.json').write_text(json.dumps({
            'team_abbreviation': {'111': 'BOS'},
        }))
        result = util.merge_team_abbreviations()
        assert result == {'147': 'NYY', '111': 'BOS'}
        saved = json.loads((tmp_path / 'teams.json').read_text())
        assert saved == {'team_abbreviation': {'147': 'NYY', '111': 'BOS'}}

    def test_standings_overrides_teams_on_conflict(self, tmp_path, monkeypatch):
        """Standings overrides teams on conflict."""
        monkeypatch.setattr(util, '_DATA_DIR', str(tmp_path))
        (tmp_path / 'teams.json').write_text(json.dumps({
            'team_abbreviation': {'147': 'OLD'},
        }))
        (tmp_path / 'standings.json').write_text(json.dumps({
            'team_abbreviation': {'147': 'NEW'},
        }))
        result = util.merge_team_abbreviations()
        assert result['147'] == 'NEW'

    def test_missing_standings_file_keeps_teams_only(self, tmp_path, monkeypatch):
        """Missing standings file keeps teams only."""
        monkeypatch.setattr(util, '_DATA_DIR', str(tmp_path))
        (tmp_path / 'teams.json').write_text(json.dumps({
            'team_abbreviation': {'147': 'NYY'},
        }))
        result = util.merge_team_abbreviations()
        assert result == {'147': 'NYY'}

    def test_missing_both_files_returns_empty_dict(self, tmp_path, monkeypatch):
        """Missing both files returns empty dict."""
        monkeypatch.setattr(util, '_DATA_DIR', str(tmp_path))
        result = util.merge_team_abbreviations()
        assert result == {}

    def test_standings_without_abbreviation_key_ignored(self, tmp_path, monkeypatch):
        """Standings without abbreviation key ignored."""
        monkeypatch.setattr(util, '_DATA_DIR', str(tmp_path))
        (tmp_path / 'teams.json').write_text(json.dumps({
            'team_abbreviation': {'147': 'NYY'},
        }))
        (tmp_path / 'standings.json').write_text(json.dumps({
            'standings': {},
        }))
        result = util.merge_team_abbreviations()
        assert result == {'147': 'NYY'}
