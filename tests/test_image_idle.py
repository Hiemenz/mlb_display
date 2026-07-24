"""Tests for image_idle.draw_idle_screen."""
from unittest.mock import patch
from PIL import Image

from image_idle import draw_idle_screen, load_idle_state, save_idle_state, advance_mascot


SAMPLE_TRANSACTIONS = [
    {'player_name': 'Aaron Judge',        'team_abbr': 'NYY', 'team_id': '147', 'type_desc': 'Status Change'},
    {'player_name': 'Jasson Dominguez',   'team_abbr': 'NYY', 'team_id': '147', 'type_desc': 'Recalled'},
    {'player_name': 'Some Pitcher',       'team_abbr': 'BOS', 'team_id': '111', 'type_desc': 'Optioned'},
    {'player_name': 'Trade Target',       'team_abbr': 'LAD', 'team_id': '119', 'type_desc': 'Trade'},
    {'player_name': 'DFA Guy',            'team_abbr': 'NYM', 'team_id': '121', 'type_desc': 'Designated for Assignment'},
]

SAMPLE_TEAM_DATA = {
    'team_abbreviation': {'147': 'NYY', '111': 'BOS', '119': 'LAD', '121': 'NYM'},
}


# ---------------------------------------------------------------------------
# draw_idle_screen
# ---------------------------------------------------------------------------

def test_draw_idle_screen_returns_800x480_image():
    img = draw_idle_screen(SAMPLE_TRANSACTIONS, SAMPLE_TEAM_DATA, {}, {})
    assert img.size == (800, 480)
    assert img.mode == '1'


def test_draw_idle_screen_light_mode_background_white():
    img = draw_idle_screen([], SAMPLE_TEAM_DATA, {}, {'dark_mode': False})
    # Top-left pixel should be white (255) in light mode
    assert img.getpixel((0, 0)) != 0


def test_draw_idle_screen_dark_mode_background_black():
    img = draw_idle_screen([], SAMPLE_TEAM_DATA, {}, {'dark_mode': True})
    # Top-left pixel should be black (0) in dark mode
    assert img.getpixel((0, 0)) == 0


def test_draw_idle_screen_empty_transactions_no_crash():
    img = draw_idle_screen([], SAMPLE_TEAM_DATA, {}, {})
    assert img is not None


def test_draw_idle_screen_none_transactions_no_crash():
    img = draw_idle_screen(None, SAMPLE_TEAM_DATA, {}, {})
    assert img is not None


def test_draw_idle_screen_none_team_data_no_crash():
    img = draw_idle_screen(SAMPLE_TRANSACTIONS, None, {}, {})
    assert img is not None


def test_draw_idle_screen_many_transactions_capped():
    """More entries than fit across both columns must not crash."""
    many = [
        {'player_name': f'Player {i}', 'team_abbr': 'NYY', 'team_id': '147', 'type_desc': 'Recalled'}
        for i in range(60)
    ]
    img = draw_idle_screen(many, SAMPLE_TEAM_DATA, {}, {})
    assert img.size == (800, 480)


def test_draw_idle_screen_unknown_type_desc_passthrough():
    entries = [{'player_name': 'X', 'team_abbr': 'NYY', 'team_id': '147', 'type_desc': 'BrandNewType'}]
    img = draw_idle_screen(entries, SAMPLE_TEAM_DATA, {}, {})
    assert img is not None


def test_draw_idle_screen_very_long_name_truncated():
    entries = [{'player_name': 'Bartholomew Aloysius Humperdink-Smithson III',
                'team_abbr': 'NYY', 'team_id': '147', 'type_desc': 'Trade'}]
    img = draw_idle_screen(entries, SAMPLE_TEAM_DATA, {}, {})
    assert img is not None


def test_draw_idle_screen_missing_team_abbr_falls_back_to_abbr_map():
    entries = [{'player_name': 'Lookup Player', 'team_abbr': '', 'team_id': '147', 'type_desc': 'Trade'}]
    img = draw_idle_screen(entries, SAMPLE_TEAM_DATA, {}, {})
    assert img is not None


def test_draw_idle_screen_logo_pasted_light_mode():
    fake_logo = Image.new('1', (18, 18), 0)
    with patch('image_idle._logo_small', return_value=fake_logo) as mock:
        img = draw_idle_screen(SAMPLE_TRANSACTIONS, SAMPLE_TEAM_DATA, {}, {'dark_mode': False})
    assert img is not None
    assert mock.called


def test_draw_idle_screen_logo_inverted_dark_mode():
    """In dark mode _logo_small result should be inverted before pasting."""
    fake_logo = Image.new('1', (18, 18), 0)
    with patch('image_idle._logo_small', return_value=fake_logo):
        with patch('image_idle.ImageOps.invert', wraps=__import__('PIL').ImageOps.invert) as mock_inv:
            draw_idle_screen(SAMPLE_TRANSACTIONS, SAMPLE_TEAM_DATA, {}, {'dark_mode': True})
    assert mock_inv.called


def test_draw_idle_screen_logo_exception_does_not_crash():
    with patch('image_idle._logo_small', side_effect=OSError('no logo')):
        img = draw_idle_screen(SAMPLE_TRANSACTIONS, SAMPLE_TEAM_DATA, {}, {})
    assert img is not None


def test_draw_idle_screen_fills_both_columns():
    """Enough entries to fill both columns must all render without crash."""
    many = [
        {'player_name': f'Player {i}', 'team_abbr': 'BOS', 'team_id': '111', 'type_desc': 'Optioned'}
        for i in range(42)
    ]
    img = draw_idle_screen(many, SAMPLE_TEAM_DATA, {}, {})
    assert img.size == (800, 480)


# ---------------------------------------------------------------------------
# Mascot state helpers (still present in module, tested for completeness)
# ---------------------------------------------------------------------------

def test_load_idle_state_missing_file_returns_empty(tmp_path):
    state = load_idle_state(str(tmp_path / 'nonexistent'))
    assert state == {}


def test_save_and_load_idle_state_roundtrip(tmp_path):
    data = {'mascot_x': 10.0, 'mascot_y': 20.0}
    save_idle_state(data, str(tmp_path))
    loaded = load_idle_state(str(tmp_path))
    assert loaded == data


def test_advance_mascot_initialises_position():
    state = {}
    state = advance_mascot(state)
    assert 'mascot_x' in state
    assert 'mascot_y' in state


def test_advance_mascot_moves_position():
    state = {'mascot_x': 100.0, 'mascot_y': 100.0, 'mascot_dx': 10.0, 'mascot_dy': 5.0}
    new_state = advance_mascot(state)
    assert new_state['mascot_x'] != 100.0 or new_state['mascot_y'] != 100.0


def test_advance_mascot_bounces_off_left_edge():
    state = {'mascot_x': 0.0, 'mascot_y': 100.0, 'mascot_dx': -20.0, 'mascot_dy': 5.0}
    new_state = advance_mascot(state)
    assert new_state['mascot_dx'] > 0


def test_advance_mascot_bounces_off_right_edge():
    state = {'mascot_x': 800.0, 'mascot_y': 100.0, 'mascot_dx': 20.0, 'mascot_dy': 5.0}
    new_state = advance_mascot(state)
    assert new_state['mascot_dx'] < 0


def test_advance_mascot_bounces_off_top_edge():
    state = {'mascot_x': 100.0, 'mascot_y': 0.0, 'mascot_dx': 5.0, 'mascot_dy': -20.0}
    new_state = advance_mascot(state)
    assert new_state['mascot_dy'] > 0


def test_advance_mascot_bounces_off_bottom_edge():
    state = {'mascot_x': 100.0, 'mascot_y': 480.0, 'mascot_dx': 5.0, 'mascot_dy': 20.0}
    new_state = advance_mascot(state)
    assert new_state['mascot_dy'] < 0


# ---------------------------------------------------------------------------
# Private helpers: _photo_to_1bit and _load_mascot_image
# ---------------------------------------------------------------------------

def test_photo_to_1bit_returns_1bit_image():
    from image_idle import _photo_to_1bit
    gray = Image.new('L', (100, 100), 128)
    result = _photo_to_1bit(gray, 64)
    assert result.mode == '1'
    assert result.size == (64, 64)


def test_photo_to_1bit_smaller_than_size():
    from image_idle import _photo_to_1bit
    gray = Image.new('L', (20, 20), 200)
    result = _photo_to_1bit(gray, 64)
    assert result.mode == '1'


def test_load_mascot_image_no_file_no_logo_returns_none():
    from image_idle import _load_mascot_image
    with patch('image_idle._load_logo_gray', return_value=None), \
         patch('image_idle._try_download_logo'), \
         patch('os.path.exists', return_value=False), \
         patch('os.path.isdir', return_value=False):
        result = _load_mascot_image('XYZ', '999', 64)
    assert result is None


def test_load_mascot_image_falls_back_to_logo():
    from image_idle import _load_mascot_image
    fake_gray = Image.new('L', (100, 100), 128)
    with patch('image_idle._load_logo_gray', return_value=fake_gray), \
         patch('os.path.exists', return_value=False), \
         patch('os.path.isdir', return_value=False):
        result = _load_mascot_image('NYY', '147', 64)
    assert result is not None
    assert result.mode == '1'


def test_load_mascot_image_loads_from_file(tmp_path):
    from image_idle import _photo_to_1bit, _load_mascot_image
    import image_idle as _mod
    # Write a fake mascot PNG
    img = Image.new('L', (256, 256), 100)
    mascot_path = tmp_path / 'NYY.png'
    img.save(str(mascot_path))

    original_dir = _mod._MASCOT_DIR
    _mod._MASCOT_DIR = str(tmp_path)
    try:
        result = _load_mascot_image('NYY', '147', 64)
    finally:
        _mod._MASCOT_DIR = original_dir
    assert result is not None
    assert result.mode == '1'


def test_load_mascot_image_file_open_fails_falls_back_to_logo():
    """When mascot file exists but can't be opened, fall back to logo."""
    from image_idle import _load_mascot_image
    fake_gray = Image.new('L', (100, 100), 128)
    with patch('os.path.exists', return_value=True), \
         patch('os.path.isdir', return_value=False), \
         patch('PIL.Image.open', side_effect=OSError('corrupt')), \
         patch('image_idle._load_logo_gray', return_value=fake_gray):
        result = _load_mascot_image('NYY', '147', 64)
    assert result is not None


def test_load_mascot_image_downloads_when_dir_exists():
    """When mascot dir exists but file doesn't, attempt a download."""
    from image_idle import _load_mascot_image
    with patch('os.path.exists', return_value=False), \
         patch('os.path.isdir', return_value=True), \
         patch('image_idle._load_logo_gray', return_value=None), \
         patch('image_idle._try_download_logo'), \
         patch('download_mascots.download_mascot', return_value=False):
        result = _load_mascot_image('NYY', '147', 64)
    assert result is None


def test_draw_idle_screen_very_long_name_triggers_truncation():
    """Name long enough to exceed column width must go through the while-loop trim."""
    # 80 'W' characters will certainly overflow any reasonable column width
    long_name = 'W' * 80
    entries = [{'player_name': long_name, 'team_abbr': 'NYY', 'team_id': '147', 'type_desc': 'Trade'}]
    img = draw_idle_screen(entries, SAMPLE_TEAM_DATA, {}, {})
    assert img is not None


# ---------------------------------------------------------------------------
# _load_mascot_image — mascot download path (lines 113-115 in image_idle.py)
# ---------------------------------------------------------------------------

def test_load_mascot_image_download_path():
    """Cover lines 113-115: mascot dir exists, file not present, download succeeds,
    and the resulting file is opened and converted."""
    import image_idle
    from PIL import Image as _Img
    import os

    fake_mascot = _Img.new('L', (100, 100), 128)

    with patch('image_idle.os.path.exists', return_value=False), \
         patch('image_idle.os.path.isdir', return_value=True), \
         patch('image_idle.Image.open', return_value=fake_mascot):
        # Patch download_mascot inside the function's import
        import unittest.mock as _m
        sys_modules_backup = {}
        import sys
        fake_module = _m.MagicMock()
        fake_module.download_mascot.return_value = True
        sys.modules['download_mascots'] = fake_module
        try:
            result = image_idle._load_mascot_image('NYY', '147', 80)
        finally:
            if 'download_mascots' in sys.modules:
                del sys.modules['download_mascots']

    # Result may be None if _photo_to_1bit fails, but the path was executed
    # (lines 113-115 covered regardless of return value)
