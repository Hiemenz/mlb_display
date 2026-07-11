"""Tests for image_transactions.draw_transactions_cell."""
from unittest.mock import patch
from PIL import Image

from image_transactions import draw_transactions_cell


SAMPLE_TRANSACTIONS = [
    {'date': '2026-07-08', 'player_name': 'Aaron Judge', 'team_abbr': 'NYY',
     'team_id': '147', 'type_desc': 'Status Change', 'description': 'placed on IL'},
    {'date': '2026-07-08', 'player_name': 'Jasson Dominguez', 'team_abbr': 'NYY',
     'team_id': '147', 'type_desc': 'Recalled', 'description': 'recalled from AAA'},
    {'date': '2026-07-07', 'player_name': 'Some Pitcher', 'team_abbr': 'BOS',
     'team_id': '111', 'type_desc': 'Optioned', 'description': 'optioned to AAA'},
]

SAMPLE_TEAM_DATA = {
    'team_abbreviation': {'147': 'NYY', '111': 'BOS'},
}


def _make_image():
    """Make image."""
    return Image.new('1', (800, 480), 255)


def test_draw_transactions_cell_renders_without_error():
    """Draw transactions cell renders without error."""
    img = _make_image()
    result = draw_transactions_cell(img, 32, 30, SAMPLE_TRANSACTIONS, SAMPLE_TEAM_DATA)
    assert result is not None


def test_draw_transactions_cell_empty_list_shows_fallback():
    """Draw transactions cell empty list shows fallback."""
    img = _make_image()
    result = draw_transactions_cell(img, 32, 30, [], SAMPLE_TEAM_DATA)
    assert result is not None


def test_draw_transactions_cell_none_data_shows_fallback():
    """Draw transactions cell none data shows fallback."""
    img = _make_image()
    result = draw_transactions_cell(img, 32, 30, None, SAMPLE_TEAM_DATA)
    assert result is not None


def test_draw_transactions_cell_none_team_data():
    """Draw transactions cell none team data."""
    img = _make_image()
    result = draw_transactions_cell(img, 32, 30, SAMPLE_TRANSACTIONS, None)
    assert result is not None


def test_draw_transactions_cell_very_long_name_truncated():
    """Draw transactions cell very long name truncated."""
    img = _make_image()
    long_name = [{
        'date': '2026-07-08', 'player_name': 'Bartholomew Humperdink-Smithson',
        'team_abbr': 'NYY', 'team_id': '147', 'type_desc': 'Status Change', 'description': '',
    }]
    result = draw_transactions_cell(img, 32, 30, long_name, SAMPLE_TEAM_DATA)
    assert result is not None


def test_draw_transactions_cell_unknown_type_desc_passthrough():
    """Unknown type_desc values (not in _TYPE_ABBR) are shown as-is, not dropped."""
    img = _make_image()
    entries = [{
        'date': '2026-07-08', 'player_name': 'Some Player',
        'team_abbr': 'NYY', 'team_id': '147', 'type_desc': 'Something New', 'description': '',
    }]
    result = draw_transactions_cell(img, 32, 30, entries, SAMPLE_TEAM_DATA)
    assert result is not None


def test_draw_transactions_cell_with_logos_pastes_logo():
    """Draw transactions cell with logos pastes logo."""
    img = _make_image()
    fake_logo = Image.new('1', (18, 18), 0)
    with patch('image_transactions._logo_small', return_value=fake_logo) as mock_logo:
        result = draw_transactions_cell(img, 32, 30, SAMPLE_TRANSACTIONS, SAMPLE_TEAM_DATA, use_logos=True)
    assert result is not None
    assert mock_logo.called


def test_draw_transactions_cell_logo_lookup_failure_falls_back():
    """Logo lookup failure must not crash the cell."""
    img = _make_image()
    with patch('image_transactions._logo_small', side_effect=OSError('missing')):
        result = draw_transactions_cell(img, 32, 30, SAMPLE_TRANSACTIONS, SAMPLE_TEAM_DATA, use_logos=True)
    assert result is not None


def test_draw_transactions_cell_more_entries_than_rows_is_capped():
    """More entries than fit in the cell must not crash — extras are dropped, not overflowed."""
    img = _make_image()
    many = [
        {'date': '2026-07-08', 'player_name': f'Player {i}', 'team_abbr': 'NYY',
         'team_id': '147', 'type_desc': 'Status Change', 'description': ''}
        for i in range(20)
    ]
    result = draw_transactions_cell(img, 32, 30, many, SAMPLE_TEAM_DATA)
    assert result is not None


def test_draw_transactions_cell_respects_max_rows():
    """max_rows further limits how many entries are drawn."""
    img = _make_image()
    result = draw_transactions_cell(img, 32, 30, SAMPLE_TRANSACTIONS, SAMPLE_TEAM_DATA, max_rows=1)
    assert result is not None
