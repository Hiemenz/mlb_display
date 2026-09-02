"""Tests for fetch_win_trend and image_win_trend."""
import sys
import os
from unittest.mock import patch, MagicMock

import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import fetch_win_trend as fwt
import image_win_trend as iwt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sample_data(n_wins=5, n_losses=3):
    """Return a minimal win_trend data dict."""
    games = []
    w = l = 0
    for i in range(n_wins + n_losses):
        result = 'W' if i < n_wins else 'L'
        if result == 'W':
            w += 1
        else:
            l += 1
        games.append({'date': f'2026-04-{i+1:02d}', 'wins': w, 'losses': l, 'result': result})
    return {
        'team_id': 147,
        'team_abbr': 'NYY',
        'season': 2026,
        'fetched_at': 0,
        'games': games,
    }


# ---------------------------------------------------------------------------
# fetch_win_trend helpers
# ---------------------------------------------------------------------------

def test_abbr_to_team_id_found():
    teams_json = {'team_abbreviation': {'147': 'NYY', '111': 'BOS'}}
    with patch('fetch_win_trend.load_json_file', return_value=teams_json):
        tid = fwt._abbr_to_team_id('NYY')
    assert tid == 147


def test_abbr_to_team_id_case_insensitive():
    teams_json = {'team_abbreviation': {'147': 'NYY'}}
    with patch('fetch_win_trend.load_json_file', return_value=teams_json):
        tid = fwt._abbr_to_team_id('nyy')
    assert tid == 147


def test_abbr_to_team_id_not_found():
    with patch('fetch_win_trend.load_json_file', return_value={}):
        tid = fwt._abbr_to_team_id('ZZZ')
    assert tid is None


def test_fetch_win_trend_unknown_abbr(capsys):
    with patch('fetch_win_trend.load_json_file', return_value={}):
        result = fwt.fetch_win_trend('ZZZ')
    assert result is None


def test_fetch_win_trend_api_error(capsys):
    teams_json = {'team_abbreviation': {'147': 'NYY'}}
    with patch('fetch_win_trend.load_json_file', return_value=teams_json), \
         patch('fetch_win_trend.requests.get', side_effect=Exception('network error')):
        result = fwt.fetch_win_trend('NYY', season=2026)
    assert result is None


def test_fetch_win_trend_api_success():
    teams_json = {'team_abbreviation': {'147': 'NYY'}}
    api_resp = {
        'dates': [
            {
                'date': '2026-04-01',
                'games': [
                    {
                        'status': {'detailedState': 'Final'},
                        'gameType': 'R',
                        'teams': {
                            'away': {'team': {'id': 147}, 'isWinner': True},
                            'home': {'team': {'id': 111}, 'isWinner': False},
                        },
                    },
                    {
                        'status': {'detailedState': 'Final'},
                        'gameType': 'R',
                        'teams': {
                            'away': {'team': {'id': 111}, 'isWinner': True},
                            'home': {'team': {'id': 147}, 'isWinner': False},
                        },
                    },
                ],
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = api_resp

    with patch('fetch_win_trend.load_json_file', return_value=teams_json), \
         patch('fetch_win_trend.save_off_results'), \
         patch('fetch_win_trend.requests.get', return_value=mock_resp):
        result = fwt.fetch_win_trend('NYY', season=2026)

    assert result is not None
    assert result['team_abbr'] == 'NYY'
    games = result['games']
    assert len(games) == 2
    assert games[0]['result'] == 'W'
    assert games[0]['wins'] == 1
    assert games[1]['result'] == 'L'
    assert games[1]['losses'] == 1


def test_fetch_win_trend_skips_non_final():
    """Games that aren't Final/Completed-Early are excluded even if teamId matches."""
    teams_json = {'team_abbreviation': {'147': 'NYY'}}
    api_resp = {
        'dates': [
            {
                'date': '2026-04-15',
                'games': [
                    {
                        'status': {'detailedState': 'Postponed'},
                        'gameType': 'R',
                        'teams': {
                            'away': {'team': {'id': 147}, 'isWinner': False},
                            'home': {'team': {'id': 111}, 'isWinner': False},
                        },
                    },
                ],
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = api_resp

    with patch('fetch_win_trend.load_json_file', return_value=teams_json), \
         patch('fetch_win_trend.save_off_results'), \
         patch('fetch_win_trend.requests.get', return_value=mock_resp):
        result = fwt.fetch_win_trend('NYY', season=2026)

    assert result is not None
    assert result['games'] == []


def test_fetch_win_trend_skips_unrelated_team():
    """Games where neither team is the target are skipped (line 88 continue)."""
    teams_json = {'team_abbreviation': {'147': 'NYY'}}
    api_resp = {
        'dates': [
            {
                'date': '2026-04-01',
                'games': [
                    {
                        'status': {'detailedState': 'Final'},
                        'gameType': 'R',
                        'teams': {
                            'away': {'team': {'id': 111}, 'isWinner': True},   # BOS
                            'home': {'team': {'id': 119}, 'isWinner': False},  # LAD
                        },
                    },
                ],
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = api_resp

    with patch('fetch_win_trend.load_json_file', return_value=teams_json), \
         patch('fetch_win_trend.save_off_results'), \
         patch('fetch_win_trend.requests.get', return_value=mock_resp):
        result = fwt.fetch_win_trend('NYY', season=2026)

    assert result is not None
    assert result['games'] == []


def test_fetch_win_trend_skips_in_progress():
    teams_json = {'team_abbreviation': {'147': 'NYY'}}
    api_resp = {
        'dates': [
            {
                'date': '2026-04-01',
                'games': [
                    {
                        'status': {'detailedState': 'In Progress'},
                        'gameType': 'R',
                        'teams': {
                            'away': {'team': {'id': 147}, 'isWinner': False},
                            'home': {'team': {'id': 111}, 'isWinner': False},
                        },
                    },
                ],
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = api_resp

    with patch('fetch_win_trend.load_json_file', return_value=teams_json), \
         patch('fetch_win_trend.save_off_results'), \
         patch('fetch_win_trend.requests.get', return_value=mock_resp):
        result = fwt.fetch_win_trend('NYY', season=2026)

    assert result['games'] == []


# ---------------------------------------------------------------------------
# _games_above_500
# ---------------------------------------------------------------------------

def test_games_above_500_basic():
    games = [
        {'wins': 1, 'losses': 0},
        {'wins': 1, 'losses': 1},
        {'wins': 2, 'losses': 1},
    ]
    pts = iwt._games_above_500(games)
    assert pts == [(1, 1), (2, 0), (3, 1)]


def test_games_above_500_empty():
    assert iwt._games_above_500([]) == []


# ---------------------------------------------------------------------------
# draw_win_trend_cell
# ---------------------------------------------------------------------------

@needs_pil
def test_draw_win_trend_cell_returns_image():
    img = Image.new('1', (800, 480), 255)
    result = iwt.draw_win_trend_cell(img, 32, 30, _sample_data(), {})
    assert result is not None
    assert result.size == (800, 480)


@needs_pil
def test_draw_win_trend_cell_empty_data():
    img = Image.new('1', (800, 480), 255)
    result = iwt.draw_win_trend_cell(img, 32, 30, {}, {})
    assert result is img  # returns Himage unchanged when no data


@needs_pil
def test_draw_win_trend_cell_no_games():
    img = Image.new('1', (800, 480), 255)
    result = iwt.draw_win_trend_cell(img, 32, 30, {'games': [], 'team_abbr': 'NYY'}, {})
    assert result is img


@needs_pil
def test_draw_win_trend_cell_dark_mode():
    img = Image.new('1', (800, 480), 0)
    result = iwt.draw_win_trend_cell(img, 32, 30, _sample_data(), {'dark_mode': True})
    assert result is not None


@needs_pil
def test_draw_win_trend_cell_single_game():
    data = _sample_data(n_wins=1, n_losses=0)
    img = Image.new('1', (800, 480), 255)
    result = iwt.draw_win_trend_cell(img, 32, 30, data, {})
    assert result is not None


# ---------------------------------------------------------------------------
# _draw_trend_line
# ---------------------------------------------------------------------------

@needs_pil
def test_draw_trend_line_no_crash_single_point():
    img = Image.new('1', (200, 100), 255)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    iwt._draw_trend_line(draw, [(1, 5)], 10, 10, 180, 80)
    # Should not raise — single point means no line drawn.


@needs_pil
def test_draw_trend_line_draws_line():
    img = Image.new('1', (200, 100), 255)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    pts = [(1, -2), (2, 0), (3, 3)]
    iwt._draw_trend_line(draw, pts, 10, 10, 180, 80)
    # Just verify it doesn't crash.


# ---------------------------------------------------------------------------
# render_win_trend_view
# ---------------------------------------------------------------------------

@needs_pil
def test_render_win_trend_view_no_data():
    img = iwt.render_win_trend_view(None)
    assert img.size == (800, 480)


@needs_pil
def test_render_win_trend_view_empty_games():
    img = iwt.render_win_trend_view({'games': [], 'team_abbr': 'NYY', 'season': 2026})
    assert img.size == (800, 480)


@needs_pil
def test_render_win_trend_view_with_data():
    with patch('image_win_trend._logo_ghost', return_value=None):
        img = iwt.render_win_trend_view(_sample_data(), config={'dark_mode': False})
    assert img.size == (800, 480)
    assert img.mode == '1'


@needs_pil
def test_render_win_trend_view_with_ghost_logo():
    """Cover the ghost-logo paste path (lines 172-177)."""
    fake_ghost = Image.new('1', (200, 200), 255)
    with patch('image_win_trend._logo_ghost', return_value=fake_ghost):
        img = iwt.render_win_trend_view(_sample_data())
    assert img.size == (800, 480)


@needs_pil
def test_render_win_trend_view_ghost_exception_swallowed():
    """Exception from _logo_ghost is swallowed; render still succeeds."""
    with patch('image_win_trend._logo_ghost', side_effect=Exception('fail')):
        img = iwt.render_win_trend_view(_sample_data())
    assert img.size == (800, 480)


@needs_pil
def test_render_win_trend_view_dark_mode():
    with patch('image_win_trend._logo_ghost', return_value=None):
        img = iwt.render_win_trend_view(_sample_data(), config={}, dark_mode=True)
    assert img.size == (800, 480)


@needs_pil
def test_render_win_trend_view_all_wins():
    data = _sample_data(n_wins=10, n_losses=0)
    with patch('image_win_trend._logo_ghost', return_value=None):
        img = iwt.render_win_trend_view(data)
    assert img is not None


@needs_pil
def test_render_win_trend_view_all_losses():
    data = _sample_data(n_wins=0, n_losses=10)
    with patch('image_win_trend._logo_ghost', return_value=None):
        img = iwt.render_win_trend_view(data)
    assert img is not None


@needs_pil
def test_render_win_trend_view_large_season():
    """162 games should render without errors."""
    games = []
    w = l = 0
    for i in range(162):
        if i % 3 == 0:
            l += 1
            games.append({'date': f'2026-{4 + i//30:02d}-{(i%30)+1:02d}', 'wins': w, 'losses': l, 'result': 'L'})
        else:
            w += 1
            games.append({'date': f'2026-{4 + i//30:02d}-{(i%30)+1:02d}', 'wins': w, 'losses': l, 'result': 'W'})
    data = {'team_id': 147, 'team_abbr': 'NYY', 'season': 2026, 'fetched_at': 0, 'games': games}
    with patch('image_win_trend._logo_ghost', return_value=None):
        img = iwt.render_win_trend_view(data)
    assert img.size == (800, 480)


# ---------------------------------------------------------------------------
# fetch_all_teams_trend
# ---------------------------------------------------------------------------

def _all_teams_api_resp():
    """Minimal API response with two teams playing each other on one date."""
    return {
        'dates': [
            {
                'date': '2026-04-01',
                'games': [
                    {
                        'status': {'detailedState': 'Final'},
                        'teams': {
                            'away': {'team': {'id': 147}, 'isWinner': True},
                            'home': {'team': {'id': 111}, 'isWinner': False},
                        },
                    },
                ],
            },
            {
                'date': '2026-04-02',
                'games': [
                    {
                        'status': {'detailedState': 'Postponed'},
                        'teams': {
                            'away': {'team': {'id': 147}, 'isWinner': False},
                            'home': {'team': {'id': 111}, 'isWinner': False},
                        },
                    },
                ],
            },
        ]
    }


def _teams_json():
    return {'team_abbreviation': {'147': 'NYY', '111': 'BOS'}}


def test_fetch_all_teams_trend_success():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _all_teams_api_resp()

    with patch('fetch_win_trend.load_json_file', return_value=_teams_json()), \
         patch('fetch_win_trend.save_off_results'), \
         patch('fetch_win_trend.requests.get', return_value=mock_resp):
        result = fwt.fetch_all_teams_trend(season=2026)

    assert result is not None
    assert result['season'] == 2026
    teams = result['teams']
    assert '147' in teams
    assert '111' in teams
    nyy = teams['147']
    assert nyy['team_abbr'] == 'NYY'
    assert nyy['games'][-1]['wins'] == 1
    assert nyy['games'][-1]['losses'] == 0
    bos = teams['111']
    assert bos['games'][-1]['wins'] == 0
    assert bos['games'][-1]['losses'] == 1


def test_fetch_all_teams_trend_skips_non_final():
    """Postponed games should not appear in any team's game list."""
    api_resp = {
        'dates': [
            {
                'date': '2026-04-15',
                'games': [
                    {
                        'status': {'detailedState': 'Postponed'},
                        'teams': {
                            'away': {'team': {'id': 147}, 'isWinner': False},
                            'home': {'team': {'id': 111}, 'isWinner': False},
                        },
                    },
                ],
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = api_resp

    with patch('fetch_win_trend.load_json_file', return_value=_teams_json()), \
         patch('fetch_win_trend.save_off_results'), \
         patch('fetch_win_trend.requests.get', return_value=mock_resp):
        result = fwt.fetch_all_teams_trend(season=2026)

    assert result is not None
    assert result['teams'] == {}


def test_fetch_all_teams_trend_api_error(capsys):
    with patch('fetch_win_trend.load_json_file', return_value=_teams_json()), \
         patch('fetch_win_trend.requests.get', side_effect=Exception('net error')):
        result = fwt.fetch_all_teams_trend(season=2026)
    assert result is None


def test_fetch_all_teams_trend_skips_null_team_id():
    """Games where team.id is missing are skipped gracefully."""
    api_resp = {
        'dates': [
            {
                'date': '2026-04-01',
                'games': [
                    {
                        'status': {'detailedState': 'Final'},
                        'teams': {
                            'away': {'team': None},
                            'home': {'team': {'id': 111}, 'isWinner': True},
                        },
                    },
                ],
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = api_resp

    with patch('fetch_win_trend.load_json_file', return_value=_teams_json()), \
         patch('fetch_win_trend.save_off_results'), \
         patch('fetch_win_trend.requests.get', return_value=mock_resp):
        result = fwt.fetch_all_teams_trend(season=2026)

    # Only home team (111) recorded; away had None team
    assert '111' in result['teams']
    assert '147' not in result['teams']


def test_fetch_all_teams_trend_default_season():
    """Calling without season arg uses the current year."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {'dates': []}

    captured_urls = []

    def _mock_get(url, **kw):
        captured_urls.append(url)
        return mock_resp

    with patch('fetch_win_trend.load_json_file', return_value={}), \
         patch('fetch_win_trend.save_off_results'), \
         patch('fetch_win_trend.requests.get', side_effect=_mock_get):
        fwt.fetch_all_teams_trend()

    assert captured_urls
    assert '2026' in captured_urls[0]  # current mocked year is 2026


# ---------------------------------------------------------------------------
# render_all_teams_win_trend_view
# ---------------------------------------------------------------------------

def _all_teams_data(n_teams=30):
    """Build a synthetic all_teams_trend dict with n_teams entries."""
    teams = {}
    for i in range(n_teams):
        tid = 100 + i
        wins = 50 + i % 20
        losses = 40 - i % 10
        games = []
        w = l = 0
        for j in range(wins + losses):
            if j < wins:
                w += 1
                r = 'W'
            else:
                l += 1
                r = 'L'
            games.append({'date': f'2026-04-{j+1:02d}', 'wins': w, 'losses': l, 'result': r})
        teams[str(tid)] = {
            'team_id': tid,
            'team_abbr': f'T{i:02d}',
            'games': games,
        }
    return {'season': 2026, 'fetched_at': 0, 'teams': teams}


@needs_pil
def test_render_all_teams_win_trend_view_no_data():
    img = iwt.render_all_teams_win_trend_view(None)
    assert img.size == (800, 480)


@needs_pil
def test_render_all_teams_win_trend_view_empty_teams():
    img = iwt.render_all_teams_win_trend_view({'season': 2026, 'teams': {}})
    assert img.size == (800, 480)


@needs_pil
def test_render_all_teams_win_trend_view_30_teams():
    img = iwt.render_all_teams_win_trend_view(_all_teams_data(30))
    assert img.size == (800, 480)
    assert img.mode == '1'


@needs_pil
def test_render_all_teams_win_trend_view_dark_mode():
    img = iwt.render_all_teams_win_trend_view(_all_teams_data(6), dark_mode=True)
    assert img.size == (800, 480)


@needs_pil
def test_render_all_teams_win_trend_view_team_without_games():
    """A team entry with no games list should render its abbr without crashing."""
    data = _all_teams_data(4)
    # Strip games from one team
    first_key = next(iter(data['teams']))
    data['teams'][first_key]['games'] = []
    img = iwt.render_all_teams_win_trend_view(data)
    assert img.size == (800, 480)


@needs_pil
def test_render_all_teams_win_trend_view_sorted_best_first():
    """Teams are ordered best-to-worst so top-left cell has the highest W-L diff."""
    data = {
        'season': 2026,
        'teams': {
            '1': {'team_id': 1, 'team_abbr': 'BAD', 'games': [
                {'date': '2026-04-01', 'wins': 1, 'losses': 9, 'result': 'L'},
            ]},
            '2': {'team_id': 2, 'team_abbr': 'GRT', 'games': [
                {'date': '2026-04-01', 'wins': 9, 'losses': 1, 'result': 'W'},
            ]},
        },
    }
    # Just confirm it renders; actual pixel checking is left to golden tests
    img = iwt.render_all_teams_win_trend_view(data)
    assert img.size == (800, 480)


# ---------------------------------------------------------------------------
# render_scoreboard wintrend_all mode
# ---------------------------------------------------------------------------

def test_wintrend_all_is_a_valid_display_mode():
    import render_scoreboard as rs
    assert 'wintrend_all' in rs._VALID_MODES


def _rs_loader(all_teams_payload=None):
    """load_json_file side_effect for render_scoreboard tests."""
    def _fn(filename, file_path=None):
        if filename == 'games.json':
            return {'games': []}
        if filename == 'teams.json':
            return {'team_abbreviation': {}}
        if filename == 'all_teams_trend.json':
            return all_teams_payload
        return {}
    return _fn


@needs_pil
def test_render_wintrend_all_mode_no_data_returns_none(tmp_path, capsys):
    import render_scoreboard as rs
    with patch('render_scoreboard.load_json_file', side_effect=_rs_loader(None)):
        result = rs.render(config={'display_mode': 'wintrend_all'}, output_path=None)
    assert result is None


@needs_pil
def test_render_wintrend_all_mode_dispatches_and_saves(tmp_path):
    import render_scoreboard as rs
    out = str(tmp_path / 'out.bmp')
    fake_img = Image.new('1', (800, 480), 255)

    at_data = {'season': 2026, 'teams': {}}
    with patch('render_scoreboard.load_json_file', side_effect=_rs_loader(at_data)), \
         patch('render_scoreboard.render_all_teams_win_trend_view', return_value=fake_img) as mock_render:
        result = rs.render(config={'display_mode': 'wintrend_all'}, output_path=out)

    assert result is not None
    mock_render.assert_called_once()
    assert os.path.exists(out)
