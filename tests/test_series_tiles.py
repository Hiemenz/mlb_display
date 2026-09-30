"""Tests for image_series.draw_series_cell and its grid placement."""
import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason='PIL not installed')

_WC_SERIES = {
    'round': 'WC', 'away_abbr': 'PHI', 'home_abbr': 'ATL',
    'away_id': '143', 'home_id': '144',
    'away_wins': 2, 'home_wins': 1,
    'complete': False, 'winner_abbr': None,
    'game_results': [
        {'winner_id': '143', 'game_pk': 1, 'date': '2026-10-01',
         'away_id': '143', 'home_id': '144', 'away_score': 4, 'home_score': 2},
        {'winner_id': '144', 'game_pk': 2, 'date': '2026-10-02',
         'away_id': '143', 'home_id': '144', 'away_score': 1, 'home_score': 6},
        {'winner_id': '143', 'game_pk': 3, 'date': '2026-10-04',
         'away_id': '143', 'home_id': '144', 'away_score': 8, 'home_score': 3},
    ],
}

_WC_COMPLETE = dict(_WC_SERIES, away_wins=2, home_wins=0, complete=True, winner_abbr='PHI',
                    game_results=[
                        {'winner_id': '143', 'game_pk': 1, 'date': '2026-10-01',
                         'away_id': '143', 'home_id': '144', 'away_score': 5, 'home_score': 3},
                        {'winner_id': '143', 'game_pk': 2, 'date': '2026-10-02',
                         'away_id': '143', 'home_id': '144', 'away_score': 4, 'home_score': 1},
                    ])

_NO_GAMES = dict(_WC_SERIES, away_wins=0, home_wins=0, game_results=[])


def _draw(series, x=10, y=10, use_logos=False):
    from image_series import draw_series_cell
    img = Image.new('1', (300, 200), 255)
    draw_series_cell(img, x, y, series, use_logos=use_logos)
    return img


@needs_pil
class TestDrawSeriesCell:
    def test_draws_within_cell_bounds(self):
        img = _draw(_WC_SERIES)
        outside = img.crop((147, 0, 300, 200)).getextrema()
        assert outside == (255, 255)

    def test_in_progress_series_produces_ink(self):
        img = _draw(_WC_SERIES)
        assert img.getbbox() is not None

    def test_no_games_does_not_crash(self):
        img = _draw(_NO_GAMES)
        assert img.getbbox() is not None

    def test_none_entry_does_not_crash(self):
        from image_series import draw_series_cell
        img = Image.new('1', (300, 200), 255)
        result = draw_series_cell(img, 10, 10, None)
        assert result is not None

    def test_winner_floods_tile_body_black(self):
        """Completed series: body floods black (more black pixels than no-games tile)."""
        img_win = _draw(_WC_COMPLETE)
        img_none = _draw(_NO_GAMES)
        # Body = everything below the header rule
        win_body  = list(img_win.crop((10, 30, 145, 140)).getdata()).count(0)
        none_body = list(img_none.crop((10, 30, 145, 140)).getdata()).count(0)
        assert win_body > none_body

    def test_home_winner_also_floods_body(self):
        home_win = dict(_WC_SERIES, away_wins=0, home_wins=2,
                        complete=True, winner_abbr='ATL', game_results=[])
        img = _draw(home_win)
        img_none = _draw(_NO_GAMES)
        win_body  = list(img.crop((10, 30, 145, 140)).getdata()).count(0)
        none_body = list(img_none.crop((10, 30, 145, 140)).getdata()).count(0)
        assert win_body > none_body

    def test_logos_render_without_crash(self):
        """use_logos=True should not raise even when logo files are absent."""
        img = _draw(_WC_COMPLETE, use_logos=True)
        assert img.getbbox() is not None

    def test_complete_series_more_ink_than_empty(self):
        img_done = _draw(_WC_COMPLETE)
        img_empty = _draw(_NO_GAMES)
        assert list(img_done.getdata()).count(0) > list(img_empty.getdata()).count(0)

    def test_game_results_with_scores(self):
        img_scored = _draw(_WC_SERIES)
        img_empty = _draw(_NO_GAMES)
        assert list(img_scored.getdata()).count(0) > list(img_empty.getdata()).count(0)

    def test_game_results_without_scores_use_dash(self):
        no_score = dict(_WC_SERIES, game_results=[
            {'winner_id': '143', 'game_pk': 1, 'date': '2026-10-01',
             'away_id': '143', 'home_id': '144'}
        ])
        img = _draw(no_score)
        assert img.getbbox() is not None

    @pytest.mark.parametrize('rnd', ['WC', 'DS', 'CS', 'WS'])
    def test_all_round_types_render(self, rnd):
        s = dict(_NO_GAMES, round=rnd)
        img = _draw(s)
        assert img.getbbox() is not None

    def test_many_game_results_clipped_to_cell(self):
        many = dict(_WC_SERIES, round='WS',
                    game_results=[
                        {'winner_id': '143', 'game_pk': i, 'date': '2026-10-0' + str(i + 1),
                         'away_id': '143', 'home_id': '144', 'away_score': 3, 'home_score': 1}
                        for i in range(7)
                    ])
        img = _draw(many)
        outside = img.crop((147, 0, 300, 200)).getextrema()
        assert outside == (255, 255)

    def test_seven_games_two_column_has_more_ink_than_five(self):
        """7-game series (2-col layout) has more ink than 5-game (1-col)."""
        five = dict(_WC_SERIES, round='WS',
                    game_results=[
                        {'winner_id': '143', 'game_pk': i, 'date': '2026-10-0' + str(i + 1),
                         'away_id': '143', 'home_id': '144', 'away_score': 3, 'home_score': 1}
                        for i in range(5)
                    ])
        seven = dict(five, game_results=[
                        {'winner_id': '143', 'game_pk': i, 'date': '2026-10-0' + str(i + 1),
                         'away_id': '143', 'home_id': '144', 'away_score': 3, 'home_score': 1}
                        for i in range(7)
                    ])
        ink5 = list(_draw(five).getdata()).count(0)
        ink7 = list(_draw(seven).getdata()).count(0)
        assert ink7 > ink5

    def test_six_games_two_column_no_g7_row(self):
        """6 results → 2-col layout but no G7 row."""
        six = dict(_WC_SERIES, round='WS',
                   game_results=[
                       {'winner_id': '143', 'game_pk': i, 'date': '2026-10-0' + str(i + 1),
                        'away_id': '143', 'home_id': '144', 'away_score': 3, 'home_score': 1}
                       for i in range(6)
                   ])
        img = _draw(six)
        assert img.getbbox() is not None
        outside = img.crop((147, 0, 300, 200)).getextrema()
        assert outside == (255, 255)

    def test_result_row_with_no_score_draws_dash(self):
        no_score = dict(_WC_SERIES, game_results=[
            {'winner_id': '143', 'game_pk': 1, 'date': '2026-10-01',
             'away_id': '143', 'home_id': '144'}
        ])
        img = _draw(no_score)
        assert img.getbbox() is not None

    def test_next_game_time_shown_when_no_games(self):
        from unittest.mock import patch
        from image_series import draw_series_cell
        fake_games = {'games': [{
            'detailed_state': 'Scheduled',
            'away_team_id': '143', 'home_team_id': '144',
            'game_date': '2026-10-05T17:05:00Z',
        }]}
        img = Image.new('1', (300, 200), 255)
        with patch('image_series.load_json_file', return_value=fake_games):
            draw_series_cell(img, 10, 10, _NO_GAMES, use_logos=False)
        blank_img = Image.new('1', (300, 200), 255)
        from image_series import draw_series_cell as dsc2
        with patch('image_series.load_json_file', return_value={'games': []}):
            dsc2(blank_img, 10, 10, _NO_GAMES, use_logos=False)
        assert list(img.getdata()).count(0) > list(blank_img.getdata()).count(0)

    def test_next_game_time_no_matching_game_returns_none(self):
        from unittest.mock import patch
        from image_series import _next_game_time
        with patch('image_series.load_json_file', return_value={'games': []}):
            assert _next_game_time('143', '144') is None

    def test_next_game_time_wrong_state_skipped(self):
        from unittest.mock import patch
        from image_series import _next_game_time
        fake = {'games': [{'detailed_state': 'Final', 'away_team_id': '143',
                           'home_team_id': '144', 'game_date': '2026-10-01T17:00:00Z'}]}
        with patch('image_series.load_json_file', return_value=fake):
            assert _next_game_time('143', '144') is None

    def test_next_game_time_load_error_returns_none(self):
        from unittest.mock import patch
        from image_series import _next_game_time
        with patch('image_series.load_json_file', side_effect=Exception('boom')):
            assert _next_game_time('143', '144') is None


TEAM_DATA = {'team_abbreviation': {'147': 'NYY'}}
BASE_CONFIG = {
    'sport_id_priority': [1], 'show_series_panel': True, 'show_leaders_panel': False,
    'show_bullpen_panel': False, 'show_standings_sidebar': False,
    'hide_non_live_games': False, 'use_team_logos': False, 'dark_mode': False, 'primary': 'NYY',
}
_BRACKET = {
    'series': [
        dict(_NO_GAMES, away_abbr='BOS', home_abbr='NYY', away_id='111', home_id='147'),
        dict(_NO_GAMES, away_abbr='CHC', home_abbr='SD', away_id='112', home_id='135'),
    ]
}


def _final(idx):
    return {'game_pk': idx, 'status': 'Final', 'away_team_id': '147', 'home_team_id': '111',
            'away_team': 'NYY', 'home_team': 'BOS', 'away_score': 3, 'home_score': 1,
            'inning': 9, 'is_top_inning': False, 'detailed_state': 'Final',
            'game_type': 'R', 'doubleheader': 'N', 'game_num': 1}


def _render_grid(n_games, config=BASE_CONFIG, bracket=_BRACKET):
    from unittest.mock import patch
    import image_box
    from image_grid import draw_out_of_town_score_board
    calls = []
    from image_series import draw_series_cell as real

    def spy(img, x, y, s, use_logos=True):
        calls.append((x, y, s.get('away_abbr'), s.get('home_abbr')))
        return real(img, x, y, s, use_logos=use_logos)

    with patch('image_grid.load_yaml_file', return_value=config), \
         patch('image_box.load_yaml_file', return_value=config), \
         patch('image_grid.load_json_file', return_value=bracket), \
         patch('image_series.draw_series_cell', spy):
        image_box.set_historical_mode(True)
        try:
            draw_out_of_town_score_board(
                Image.new('1', (800, 480), 255), [_final(i) for i in range(n_games)], TEAM_DATA)
        finally:
            image_box.set_historical_mode(False)
    return calls


@needs_pil
class TestSeriesGridPlacement:
    def test_two_series_fill_two_free_slots(self):
        calls = _render_grid(3)
        assert len(calls) == 2
        assert calls[0][2:] == ('BOS', 'NYY')
        assert calls[1][2:] == ('CHC', 'SD')

    def test_single_free_slot_shows_one_series(self):
        assert len(_render_grid(14)) == 1

    def test_full_grid_shows_nothing(self):
        assert _render_grid(15) == []

    def test_disabled_shows_nothing(self):
        assert _render_grid(3, config=dict(BASE_CONFIG, show_series_panel=False)) == []

    def test_no_wc_series_shows_nothing(self):
        bracket = {'series': [dict(_NO_GAMES, round='DS', away_abbr='LAD', home_abbr='ATL',
                                   away_id='119', home_id='144')]}
        assert _render_grid(3, bracket=bracket) == []

    def test_missing_bracket_data_shows_nothing(self):
        assert _render_grid(3, bracket={}) == []
