"""Tests for the config-server QR cell on the out-of-town scoreboard grid.

Covers: _get_lan_ip, _free_grid_slot, _draw_config_qr_cell, and the
placement logic in draw_out_of_town_score_board (QR shown in the first
free cell when there are fewer than 15 games, never shown at 15/15).
"""
import socket
from unittest.mock import MagicMock, patch

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
    'show_config_qr': True,
    'config_server_port': 8080,
}

TEAM_DATA = {'team_abbreviation': {'119': 'LAD', '137': 'SF'}}


def _game(pk, state='Scheduled'):
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


def _render(games, config=None):
    import image_box
    white = Image.new('1', (800, 480), 255)
    cfg = config if config is not None else FIXED_CONFIG
    with patch('image_grid.load_yaml_file', return_value=cfg), \
         patch('image_box.load_yaml_file', return_value=cfg):
        from image_grid import draw_out_of_town_score_board
        image_box.set_historical_mode(True)
        try:
            return draw_out_of_town_score_board(white, games, TEAM_DATA)
        finally:
            image_box.set_historical_mode(False)


# ---------------------------------------------------------------------------
# _get_lan_ip
# ---------------------------------------------------------------------------

def test_get_lan_ip_success():
    from image_grid import _get_lan_ip
    mock_sock = MagicMock()
    mock_sock.getsockname.return_value = ('192.168.1.42', 51000)
    with patch('image_grid.socket.socket') as mock_socket_cls:
        mock_socket_cls.return_value.__enter__.return_value = mock_sock
        assert _get_lan_ip() == '192.168.1.42'


def test_get_lan_ip_falls_back_to_hostname():
    from image_grid import _get_lan_ip
    with patch('image_grid.socket.socket', side_effect=OSError('no route')), \
         patch('image_grid.socket.gethostbyname', return_value='10.0.0.5'):
        assert _get_lan_ip() == '10.0.0.5'


def test_get_lan_ip_returns_none_when_everything_fails():
    from image_grid import _get_lan_ip
    with patch('image_grid.socket.socket', side_effect=OSError('no route')), \
         patch('image_grid.socket.gethostbyname', side_effect=socket.gaierror('nope')):
        assert _get_lan_ip() is None


# ---------------------------------------------------------------------------
# _free_grid_slot
# ---------------------------------------------------------------------------

def test_free_grid_slot_empty_grid():
    from image_grid import _free_grid_slot
    assert _free_grid_slot([]) == (0, 0)


def test_free_grid_slot_skips_occupied_normal_cells():
    from image_grid import _free_grid_slot
    slots = [('normal', 0, 0), ('normal', 1, 0), ('normal', 2, 0)]
    assert _free_grid_slot(slots) == (3, 0)


def test_free_grid_slot_accounts_for_wide_cell_width():
    from image_grid import _free_grid_slot
    # A wide cell at col 0 occupies col 0 AND col 1 of row 0.
    slots = [('wide', 0, 0)]
    assert _free_grid_slot(slots) == (2, 0)


def test_free_grid_slot_none_when_grid_full():
    from image_grid import _free_grid_slot
    slots = [('normal', i % 5, i // 5) for i in range(15)]
    assert _free_grid_slot(slots) is None


# ---------------------------------------------------------------------------
# _draw_config_qr_cell
# ---------------------------------------------------------------------------

@needs_pil
def test_draw_config_qr_cell_pastes_into_expected_region():
    from image_grid import _draw_config_qr_cell
    white = Image.new('1', (800, 480), 255)
    result = _draw_config_qr_cell(white, 32, 30, 'http://192.168.1.1:8080/')
    assert result.size == (800, 480)
    # The 150x150 cell (minus padding) should no longer be entirely white.
    region = result.crop((32, 30, 32 + 150, 30 + 150))
    assert _has_black_pixels(region)


# ---------------------------------------------------------------------------
# End-to-end placement via draw_out_of_town_score_board
# ---------------------------------------------------------------------------

@needs_pil
def test_qr_cell_appears_with_spare_slot():
    result = _render([_game(i) for i in range(3)])
    # 4th cell (col=3, row=0) should be non-blank now.
    region = result.crop((3 * 150 + 32, 30, 3 * 150 + 32 + 150, 30 + 150))
    assert _has_black_pixels(region)


@needs_pil
def test_no_qr_cell_at_15_games():
    result = _render([_game(i) for i in range(15)])
    # No room left for a QR cell; rendering all 15 must not raise, and the
    # grid should be exactly as full as 15 games implies (spot check the
    # bottom-right cell has real game content, not a QR pasted over it).
    region = result.crop((4 * 150 + 32, 2 * 150 + 30, 4 * 150 + 32 + 150, 2 * 150 + 30 + 150))
    assert _has_black_pixels(region)


@needs_pil
def test_qr_cell_disabled_via_config():
    config = dict(FIXED_CONFIG, show_config_qr=False)
    result = _render([_game(i) for i in range(3)], config=config)
    region = result.crop((3 * 150 + 32, 30, 3 * 150 + 32 + 150, 30 + 150))
    assert not _has_black_pixels(region)


@needs_pil
def test_qr_cell_skipped_when_lan_ip_unavailable():
    with patch('image_grid._get_lan_ip', return_value=None):
        result = _render([_game(i) for i in range(3)])
    region = result.crop((3 * 150 + 32, 30, 3 * 150 + 32 + 150, 30 + 150))
    assert not _has_black_pixels(region)
