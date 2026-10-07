"""Series-leaders tiles share the grid's free slots with the season-leaders tiles."""
from unittest.mock import patch

from test_streaks_grid_placement import BASE_CONFIG, TEAM_DATA, _game
from PIL import Image

SERIES = {'leaders': {
    'homeRuns': [{'rank': 1, 'value': '2', 'name': 'A. Hitter', 'team_id': '147'}],
    'strikeOuts': [{'rank': 1, 'value': '9', 'name': 'P. Pitcher', 'team_id': '111'}],
}}
SEASON = {'leaders': {'homeRuns': [{'rank': 1, 'value': '50', 'name': 'A. Judge', 'team_id': '147'}]}}


def _render(n_games, config, series=SERIES):
    import image_box
    files = {'leaders.json': SEASON, 'series_leaders.json': series}
    white = Image.new('1', (800, 480), 255)
    with patch('image_grid.load_yaml_file', return_value=config), \
         patch('image_box.load_yaml_file', return_value=config), \
         patch('image_grid.load_json_file', side_effect=lambda name, *a, **k: files.get(name, {})), \
         patch('image_grid.draw_series_stats_cell', wraps=__import__('image_grid').draw_series_stats_cell) as ds, \
         patch('image_grid.draw_leaders_cell', wraps=__import__('image_grid').draw_leaders_cell) as dl:
        from image_grid import draw_out_of_town_score_board
        image_box.set_historical_mode(True)
        try:
            draw_out_of_town_score_board(white, [_game(i) for i in range(n_games)], TEAM_DATA)
        finally:
            image_box.set_historical_mode(False)
    return ds, dl


def test_series_only_draws_one_tile_per_available_category():
    ds, dl = _render(3, dict(BASE_CONFIG, show_series_panel=True))
    assert [c.args[5] for c in ds.call_args_list] == ['homeRuns', 'strikeOuts']
    dl.assert_not_called()


def test_both_panels_share_slots():
    ds, dl = _render(3, dict(BASE_CONFIG, show_series_panel=True, show_leaders_panel=True))
    assert ds.call_count == 2 and dl.call_count == 7      # 12 free slots hold all 9 tiles


def test_rotation_when_slots_are_scarce():
    ds, dl = _render(13, dict(BASE_CONFIG, show_series_panel=True, show_leaders_panel=True))
    assert ds.call_count + dl.call_count == 2             # only 2 slots free


def test_series_panel_off_by_default_skips_series_file():
    ds, dl = _render(3, dict(BASE_CONFIG, show_leaders_panel=True))
    ds.assert_not_called()
    assert dl.call_count == 7


def test_no_series_data_draws_no_series_tiles():
    ds, dl = _render(3, dict(BASE_CONFIG, show_series_panel=True), series={})
    ds.assert_not_called()
