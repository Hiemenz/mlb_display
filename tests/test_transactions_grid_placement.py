"""Tests for transactions-ticker placement in draw_out_of_town_score_board.

Covers: ticker shown in the first free cell when there are fewer than 15
games, disabled via config, and taking priority over the leaders panel for
that first slot (mirrors tests/test_image_grid_qr.py's placement pattern).
"""
from unittest.mock import patch

import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")

FIXED_CONFIG = {
    'timezone': 'America/Chicago',
    'use_team_logos': False,
    'show_transactions_ticker': True,
    'show_leaders_panel': False,
}

TEAM_DATA = {'team_abbreviation': {'119': 'LAD', '137': 'SF'}}

SAMPLE_TRANSACTIONS = [
    {'date': '2026-07-08', 'player_name': 'Aaron Judge', 'team_abbr': 'NYY',
     'team_id': '147', 'type_desc': 'Status Change', 'description': ''},
]


def _game(pk, state='Scheduled'):
    """Game."""
    return {
        'game_pk': pk, 'away_team_id': 119, 'home_team_id': 137,
        'detailed_state': state, 'game_start': '7:05 PM',
        'game_datetime': '2026-06-20T23:05:00Z',
        'away_runs': 0, 'home_runs': 0, 'away_hits': 0, 'home_hits': 0,
        'away_errors': 0, 'home_errors': 0,
        'away_team_record_wins': 1, 'away_team_record_losses': 1,
        'home_team_record_wins': 1, 'home_team_record_losses': 1,
        'away_probable': 'X', 'home_probable': 'Y',
    }


def _has_black_pixels(region):
    """In mode '1', white=255 (non-zero) is background, black=0 is content —
    Image.getbbox() treats any non-zero pixel as content, so an all-white
    region still returns a bbox. Count actual black pixels instead."""
    return any(px == 0 for px in region.getdata())


def _render(games, config=None, transactions=None):
    """Render."""
    import image_box
    white = Image.new('1', (800, 480), 255)
    cfg = config if config is not None else FIXED_CONFIG
    tx = transactions if transactions is not None else SAMPLE_TRANSACTIONS
    with patch('image_grid.load_yaml_file', return_value=cfg), \
         patch('image_box.load_yaml_file', return_value=cfg), \
         patch('image_grid.load_json_file', side_effect=lambda name: (
             {'transactions': tx} if name == 'transactions.json' else {}
         )):
        from image_grid import draw_out_of_town_score_board
        image_box.set_historical_mode(True)
        try:
            return draw_out_of_town_score_board(white, games, TEAM_DATA)
        finally:
            image_box.set_historical_mode(False)


@needs_pil
def test_ticker_appears_in_first_free_slot():
    """Ticker appears in first free slot."""
    result = _render([_game(i) for i in range(3)])
    region = result.crop((3 * 150 + 32, 30, 3 * 150 + 32 + 150, 30 + 150))
    assert _has_black_pixels(region)


@needs_pil
def test_no_ticker_at_15_games():
    """No ticker at 15 games — no room left, rendering all 15 must not raise."""
    result = _render([_game(i) for i in range(15)])
    region = result.crop((4 * 150 + 32, 2 * 150 + 30, 4 * 150 + 32 + 150, 2 * 150 + 30 + 150))
    assert _has_black_pixels(region)


@needs_pil
def test_ticker_disabled_via_config():
    """Ticker disabled via config."""
    config = dict(FIXED_CONFIG, show_transactions_ticker=False)
    result = _render([_game(i) for i in range(3)], config=config)
    region = result.crop((3 * 150 + 32, 30, 3 * 150 + 32 + 150, 30 + 150))
    assert not _has_black_pixels(region)


@needs_pil
def test_ticker_takes_priority_over_leaders_panel_for_first_slot():
    """When both are enabled, the ticker claims the first free slot and the
    leaders panel fills whatever's left over, not the other way around."""
    config = dict(FIXED_CONFIG, show_leaders_panel=True)
    leaders_data = {'leaders': {'homeRuns': [
        {'rank': 1, 'value': '28', 'name': 'Someone', 'team_id': '147'},
    ]}}
    with patch('image_grid.load_yaml_file', return_value=config), \
         patch('image_box.load_yaml_file', return_value=config), \
         patch('image_grid.load_json_file', side_effect=lambda name: (
             {'transactions': SAMPLE_TRANSACTIONS} if name == 'transactions.json'
             else leaders_data if name == 'leaders.json' else {}
         )), \
         patch('image_grid.draw_leaders_cell') as mock_leaders_cell, \
         patch('image_grid.draw_transactions_cell', wraps=None) as mock_tx_cell:
        import image_box
        from image_grid import draw_out_of_town_score_board
        white = Image.new('1', (800, 480), 255)
        image_box.set_historical_mode(True)
        try:
            mock_tx_cell.return_value = white
            draw_out_of_town_score_board(white, [_game(i) for i in range(3)], TEAM_DATA)
        finally:
            image_box.set_historical_mode(False)

    assert mock_tx_cell.called
    _tx_call_slot = (mock_tx_cell.call_args[0][1], mock_tx_cell.call_args[0][2])
    assert _tx_call_slot == (3 * 150 + 32, 30)  # first free slot (col 3, row 0)

    assert mock_leaders_cell.called
    for _call in mock_leaders_cell.call_args_list:
        _slot = (_call[0][1], _call[0][2])
        assert _slot != _tx_call_slot  # leaders never reuses the ticker's slot
