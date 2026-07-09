"""Additional coverage for src/config_loader.py gaps: _load_dotenv's early
return, load_config's FileNotFoundError / generic-exception paths, and
add_config_arg()."""
import argparse
import os
from unittest.mock import patch

import pytest

import config_loader


# ===========================================================================
# _load_dotenv
# ===========================================================================

class TestLoadDotenv:
    def test_no_env_file_returns_early(self, tmp_path, monkeypatch):
        """No env file returns early."""
        missing = tmp_path / '.env'
        monkeypatch.setattr(config_loader, '_ENV_FILE', str(missing))
        # Should simply return without raising and without touching os.environ.
        sentinel = 'CONFIG_LOADER_TEST_SENTINEL_VAR'
        os.environ.pop(sentinel, None)
        config_loader._load_dotenv()
        assert sentinel not in os.environ

    def test_loads_new_vars_from_env_file(self, tmp_path, monkeypatch):
        """Loads new vars from env file."""
        env_file = tmp_path / '.env'
        env_file.write_text('MY_TEST_VAR=hello\n# comment line\n\nBAD_LINE_NO_EQUALS\nQUOTED="wrapped"\n')
        monkeypatch.setattr(config_loader, '_ENV_FILE', str(env_file))
        for key in ('MY_TEST_VAR', 'QUOTED'):
            os.environ.pop(key, None)
        try:
            config_loader._load_dotenv()
            assert os.environ['MY_TEST_VAR'] == 'hello'
            assert os.environ['QUOTED'] == 'wrapped'
        finally:
            os.environ.pop('MY_TEST_VAR', None)
            os.environ.pop('QUOTED', None)

    def test_does_not_overwrite_existing_env_var(self, tmp_path, monkeypatch):
        """Does not overwrite existing env var."""
        env_file = tmp_path / '.env'
        env_file.write_text('EXISTING_VAR=from_file\n')
        monkeypatch.setattr(config_loader, '_ENV_FILE', str(env_file))
        os.environ['EXISTING_VAR'] = 'from_shell'
        try:
            config_loader._load_dotenv()
            assert os.environ['EXISTING_VAR'] == 'from_shell'
        finally:
            os.environ.pop('EXISTING_VAR', None)


# ===========================================================================
# load_config
# ===========================================================================

class TestLoadConfig:
    def test_valid_config_returns_dict(self, tmp_path):
        """Valid config returns dict."""
        p = tmp_path / 'config.yaml'
        p.write_text('key: value\n')
        result = config_loader.load_config(str(p))
        assert result == {'key': 'value'}

    def test_missing_file_returns_empty_dict(self, tmp_path, capsys):
        """Missing file returns empty dict."""
        missing = tmp_path / 'nope.yaml'
        result = config_loader.load_config(str(missing))
        assert result == {}
        captured = capsys.readouterr()
        assert 'Config file not found' in captured.out

    def test_empty_file_returns_empty_dict(self, tmp_path):
        """Empty file returns empty dict."""
        p = tmp_path / 'empty.yaml'
        p.write_text('')
        result = config_loader.load_config(str(p))
        assert result == {}

    def test_generic_exception_returns_empty_dict(self, tmp_path, capsys):
        """Generic exception returns empty dict."""
        p = tmp_path / 'config.yaml'
        p.write_text('key: value\n')
        with patch('config_loader.yaml.safe_load', side_effect=ValueError('boom')):
            result = config_loader.load_config(str(p))
        assert result == {}
        captured = capsys.readouterr()
        assert 'Error loading config' in captured.out

    def test_no_path_uses_default(self):
        """No path uses default."""
        # Default config.yaml should exist in this repo and load as a dict.
        result = config_loader.load_config()
        assert isinstance(result, dict)


# ===========================================================================
# add_config_arg
# ===========================================================================

class TestAddConfigArg:
    def test_adds_config_argument(self):
        """Adds config argument."""
        parser = argparse.ArgumentParser()
        config_loader.add_config_arg(parser)
        args = parser.parse_args([])
        assert args.config is None

    def test_config_argument_parses_value(self):
        """Config argument parses value."""
        parser = argparse.ArgumentParser()
        config_loader.add_config_arg(parser)
        args = parser.parse_args(['--config', '/some/path.yaml'])
        assert args.config == '/some/path.yaml'
