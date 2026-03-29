"""Canonical config loader. Every standalone script imports this."""
import os
import yaml

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CONFIG = os.path.join(_REPO_ROOT, 'config', 'config.yaml')


def load_config(config_path=None):
    """Load config.yaml from default path or given path. Returns dict."""
    path = config_path or _DEFAULT_CONFIG
    try:
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
            return data if data else {}
    except FileNotFoundError:
        print(f"Config file not found: {path}")
        return {}
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}


def add_config_arg(parser):
    """Add --config PATH argument to any ArgumentParser."""
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        metavar='PATH',
        help=f'Path to config.yaml (default: {_DEFAULT_CONFIG})',
    )
