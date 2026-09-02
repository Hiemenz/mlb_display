"""Tests for fetch_idle.fetch_this_day_in_history."""
from unittest.mock import patch, MagicMock

import fetch_idle as fi


def _make_resp(games):
    """Build a mock requests.Response with the given list of raw game dicts."""
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {
        'dates': [{'games': games}]
    } if games else {'dates': []}
    return mock


def _final_game():
    """Minimal Final regular-season game dict."""
    return {
        'gamePk': 123,
        'status': {'detailedState': 'Final'},
        'gameType': 'R',
        'gameNumber': 1,
        'gameDate': '2024-09-01T17:10:00Z',
        'dayNight': 'day',
        'teams': {
            'away': {
                'team': {'id': 147, 'name': 'New York Yankees'},
                'isWinner': True,
            },
            'home': {
                'team': {'id': 111, 'name': 'Boston Red Sox'},
                'isWinner': False,
            },
        },
        'linescore': {
            'currentInning': 9,
            'currentInningOrdinal': '9th',
            'inningState': 'End',
            'teams': {
                'away': {'runs': 5, 'hits': 10, 'errors': 0},
                'home': {'runs': 3, 'hits': 8, 'errors': 1},
            },
            'innings': [],
        },
        'decisions': {},
        'flags': {'noHitter': False, 'perfectGame': False},
    }


def test_fetch_this_day_in_history_success():
    """Returns (year, games) when a past year has >= 4 final games."""
    games_list = [_final_game() for _ in range(6)]
    resp = _make_resp(games_list)

    with patch('fetch_idle.requests.get', return_value=resp):
        year, games = fi.fetch_this_day_in_history('2026-09-01')

    assert year is not None
    assert year < 2026
    assert len(games) > 0


def test_fetch_this_day_in_history_insufficient_games():
    """Returns (None, []) when no past year has >= 4 final games."""
    games_list = [_final_game(), _final_game()]  # only 2 — below threshold
    resp = _make_resp(games_list)

    with patch('fetch_idle.requests.get', return_value=resp):
        year, games = fi.fetch_this_day_in_history('2026-09-01')

    assert year is None
    assert games == []


def test_fetch_this_day_in_history_non_season_date():
    """A calendar date outside MLB season months (Jan) produces (None, [])."""
    year, games = fi.fetch_this_day_in_history('2026-01-15')
    assert year is None
    assert games == []


def test_fetch_this_day_in_history_network_error():
    """Network errors are caught; returns (None, [])."""
    with patch('fetch_idle.requests.get', side_effect=Exception('timeout')):
        year, games = fi.fetch_this_day_in_history('2026-09-01')
    assert year is None
    assert games == []


def test_fetch_this_day_in_history_http_error():
    """Non-200 response causes retry; returns (None, []) when all fail."""
    bad_resp = MagicMock()
    bad_resp.status_code = 503

    with patch('fetch_idle.requests.get', return_value=bad_resp):
        year, games = fi.fetch_this_day_in_history('2026-09-01')

    assert year is None
    assert games == []


def test_fetch_this_day_in_history_caps_at_max_games():
    """Returns at most max_games entries."""
    games_list = [_final_game() for _ in range(20)]
    resp = _make_resp(games_list)

    with patch('fetch_idle.requests.get', return_value=resp):
        year, games = fi.fetch_this_day_in_history('2026-09-01', max_games=5)

    assert len(games) <= 5


def test_fetch_this_day_in_history_skips_spring_training():
    """Spring-training games are filtered out; must have >=4 regular-season finals."""
    st_game = _final_game()
    st_game['gameType'] = 'S'
    games_list = [st_game] * 6  # all spring-training — should fail threshold
    resp = _make_resp(games_list)

    with patch('fetch_idle.requests.get', return_value=resp):
        year, games = fi.fetch_this_day_in_history('2026-09-01')

    assert year is None


def test_fetch_this_day_in_history_feb29_skipped():
    """Feb 29 in a non-leap target year is skipped without crashing."""
    # 2026-02-29 does not exist. Should gracefully skip those years and return None
    # (all past years for Feb 29 that aren't leap years are skipped, and the
    # season is out of range anyway in February).
    year, games = fi.fetch_this_day_in_history('2028-02-29')
    # February is outside the MLB season, so result is always (None, [])
    assert year is None
    assert games == []
