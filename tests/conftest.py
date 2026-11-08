"""Pytest configuration: add src/ to sys.path so generate_image, fetch_games, etc. can be imported."""
import sys
import os

# Project root is one level up from this file
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, 'src')

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Change CWD to project root so config.yaml / data/*.json paths resolve
os.chdir(PROJECT_ROOT)


def pytest_addoption(parser):
    """Pytest addoption."""
    parser.addoption(
        '--update-golden', action='store_true', default=False,
        help='Write golden-image regression renders to tests/golden/ instead of asserting.',
    )


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_season_dates(monkeypatch):
    """Keep every test off the network and off data/season.json: with no season
    dates, season_phase() uses its calendar fallback, so results don't depend on
    the machine or the day. Tests of get_season() import the real function at
    module load (before this runs) and exercise it directly."""
    import season_phase
    monkeypatch.setattr(season_phase, 'get_season', lambda year, now_ts=None: None)
