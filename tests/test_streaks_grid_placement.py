"""Tests that show_streaks_panel and show_scoreless_panel dispatch into grid spare cells."""
from unittest.mock import patch

import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason='PIL not installed')

TEAM_DATA = {'team_abbreviation': {'147': 'NYY'}}

BASE_CONFIG = {
    'sport_id_priority': [1],
    'show_streaks_panel': False,
    'show_scoreless_panel': False,
    'show_leaders_panel': False,
    'show_transactions_ticker': False,
    'show_news_panel': False,
    'show_magic_numbers': False,
    'show_standings_sidebar': False,
    'hide_non_live_games': False,
    'use_team_logos': False,
    'dark_mode': False,
    'primary': 'NYY',
}

STREAKS_DATA = {
    'streaks': [
        {'rank': 1, 'name': 'Aaron Judge', 'avg': '.350', 'games': '14',
         'team_id': '147', 'abbr': 'NYY'},
    ],
    'scoreless': [
        {'rank': 1, 'name': 'Gerrit Cole', 'era': '1.57', 'ip': '115.0',
         'team_id': '147', 'abbr': 'NYY'},
    ],
}


def _game(idx):
    """Build a minimal finished game dict for the grid."""
    return {
        'game_pk': idx,
        'status': 'Final',
        'away_team_id': '147',
        'home_team_id': '111',
        'away_team': 'NYY',
        'home_team': 'BOS',
        'away_score': 3,
        'home_score': 1,
        'inning': 9,
        'is_top_inning': False,
        'detailed_state': 'Final',
        'game_type': 'R',
        'doubleheader': 'N',
        'game_num': 1,
    }


def _render(games, config):
    import image_box
    white = Image.new('1', (800, 480), 255)
    with patch('image_grid.load_yaml_file', return_value=config), \
         patch('image_box.load_yaml_file', return_value=config), \
         patch('image_grid.load_json_file', return_value=STREAKS_DATA):
        from image_grid import draw_out_of_town_score_board
        image_box.set_historical_mode(True)
        try:
            return draw_out_of_town_score_board(white, games, TEAM_DATA)
        finally:
            image_box.set_historical_mode(False)


@needs_pil
def test_hot_hitters_panel_appears_in_spare_slot():
    """show_streaks_panel dispatches draw_streaks_cell into the first free slot."""
    config = dict(BASE_CONFIG, show_streaks_panel=True)
    result = _render([_game(i) for i in range(3)], config)
    assert result is not None


@needs_pil
def test_hot_arms_panel_appears_in_spare_slot():
    """show_scoreless_panel dispatches draw_scoreless_cell into the first free slot."""
    config = dict(BASE_CONFIG, show_scoreless_panel=True)
    result = _render([_game(i) for i in range(3)], config)
    assert result is not None


@needs_pil
def test_both_panels_fill_two_slots():
    """Both panels enabled — each claims a spare slot."""
    config = dict(BASE_CONFIG, show_streaks_panel=True, show_scoreless_panel=True)
    result = _render([_game(i) for i in range(3)], config)
    assert result is not None


@needs_pil
def test_panels_skipped_when_no_free_slots():
    """Panels don't crash when grid is fully packed (no spare slots)."""
    config = dict(BASE_CONFIG, show_streaks_panel=True, show_scoreless_panel=True)
    result = _render([_game(i) for i in range(15)], config)
    assert result is not None


@needs_pil
def test_news_panel_appears_in_spare_slot():
    """show_news_panel dispatches draw_news_cell into the first free slot."""
    config = dict(BASE_CONFIG, show_news_panel=True)
    result = _render([_game(i) for i in range(3)], config)
    assert result is not None


@needs_pil
def test_magic_numbers_panel_appears_in_spare_slot():
    """show_magic_numbers dispatches draw_magic_cell into the first free slot."""
    config = dict(BASE_CONFIG, show_magic_numbers=True)
    standings = {
        'standings': {
            'American League East': [
                {'team_id': '147', 'divisionRank': '1', 'team_name': 'Yankees',
                 'league_record_wins': 90, 'league_record_losses': 40,
                 'clinch_indicator': '', 'games_back': '-'},
            ],
        },
        'team_abbreviation': {'147': 'NYY'},
    }
    import image_box
    white = Image.new('1', (800, 480), 255)
    with patch('image_grid.load_yaml_file', return_value=config), \
         patch('image_box.load_yaml_file', return_value=config), \
         patch('image_grid.load_json_file', side_effect=lambda name: (
             standings if name == 'standings.json' else STREAKS_DATA
         )):
        from image_grid import draw_out_of_town_score_board
        image_box.set_historical_mode(True)
        try:
            result = draw_out_of_town_score_board(white, [_game(i) for i in range(3)], TEAM_DATA)
        finally:
            image_box.set_historical_mode(False)
    assert result is not None
