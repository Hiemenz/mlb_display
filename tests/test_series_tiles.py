"""Tests for image_series.draw_series_cell and its grid placement."""
import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason='PIL not installed')

_WC_SERIES = {
    'round': 'WC', 'league': 'AL',
    'away_abbr': 'PHI', 'home_abbr': 'ATL',
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

_FAKE_SCHED = {'games': [{
    'detailed_state': 'Scheduled',
    'away_team_id': '143', 'home_team_id': '144',
    'away_team': 'PHI', 'home_team': 'ATL',
    'game_date': '2026-10-05T20:08:00Z',
}]}


def _draw(series, x=10, y=10, use_logos=False, fake_games=None):
    from unittest.mock import patch
    from image_series import draw_series_cell
    img = Image.new('1', (300, 200), 255)
    games_json = fake_games if fake_games is not None else {'games': []}
    with patch('image_series.load_json_file', return_value=games_json):
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
        from unittest.mock import patch
        from image_series import draw_series_cell
        img = Image.new('1', (300, 200), 255)
        with patch('image_series.load_json_file', return_value={'games': []}):
            result = draw_series_cell(img, 10, 10, None)
        assert result is not None

    def test_winner_floods_tile_body_black(self):
        img_win = _draw(_WC_COMPLETE)
        img_none = _draw(_NO_GAMES)
        win_body  = list(img_win.crop((10, 30, 145, 140)).getdata()).count(0)
        none_body = list(img_none.crop((10, 30, 145, 140)).getdata()).count(0)
        assert win_body > none_body

    def test_home_winner_also_floods_body(self):
        home_win = dict(_WC_SERIES, away_wins=0, home_wins=2,
                        complete=True, winner_abbr='ATL', game_results=[])
        img = _draw(home_win)
        img_none = _draw(_NO_GAMES)
        assert list(img.crop((10, 30, 145, 140)).getdata()).count(0) > \
               list(img_none.crop((10, 30, 145, 140)).getdata()).count(0)

    def test_logos_render_without_crash(self):
        img = _draw(_WC_COMPLETE, use_logos=True)
        assert img.getbbox() is not None

    def test_complete_series_more_ink_than_empty(self):
        assert list(_draw(_WC_COMPLETE).getdata()).count(0) > \
               list(_draw(_NO_GAMES).getdata()).count(0)

    def test_game_results_with_scores(self):
        assert list(_draw(_WC_SERIES).getdata()).count(0) > \
               list(_draw(_NO_GAMES).getdata()).count(0)

    def test_game_results_without_scores_use_dash(self):
        no_score = dict(_WC_SERIES, game_results=[
            {'winner_id': '143', 'game_pk': 1, 'date': '2026-10-01',
             'away_id': '143', 'home_id': '144'}
        ])
        img = _draw(no_score)
        assert img.getbbox() is not None

    @pytest.mark.parametrize('rnd,league', [('WC', 'AL'), ('DS', 'NL'), ('CS', 'AL'), ('WS', '')])
    def test_all_round_types_render(self, rnd, league):
        s = dict(_NO_GAMES, round=rnd, league=league)
        img = _draw(s)
        assert img.getbbox() is not None

    def test_league_label_al_wildcard(self):
        """Header should say 'AL Wild Card' when league='AL'."""
        s = dict(_NO_GAMES, round='WC', league='AL')
        img = _draw(s)
        # More ink than same series with empty league (extra chars → more pixels)
        s_no_league = dict(_NO_GAMES, round='WC', league='')
        assert list(img.getdata()).count(0) >= list(_draw(s_no_league).getdata()).count(0)

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

    @staticmethod
    def _make_games(n, round='WS'):
        return dict(_WC_SERIES, round=round, game_results=[
            {'winner_id': '143', 'game_pk': i,
             'date': f'2026-10-{i+1:02d}',
             'away_id': '143', 'home_id': '144',
             'away_score': 3, 'home_score': 1}
            for i in range(n)
        ])

    def test_wc_three_games_centred_g3(self):
        img = _draw(self._make_games(3, 'WC'))
        assert img.getbbox() is not None
        outside = img.crop((147, 0, 300, 200)).getextrema()
        assert outside == (255, 255)

    def test_ds_five_games_centred_g5(self):
        img = _draw(self._make_games(5, 'DS'))
        assert img.getbbox() is not None
        outside = img.crop((147, 0, 300, 200)).getextrema()
        assert outside == (255, 255)

    def test_seven_games_more_ink_than_six(self):
        ink6 = list(_draw(self._make_games(6, 'WS')).getdata()).count(0)
        ink7 = list(_draw(self._make_games(7, 'WS')).getdata()).count(0)
        assert ink7 > ink6

    def test_six_games_paired_rows_no_overflow(self):
        img = _draw(self._make_games(6, 'WS'))
        assert img.getbbox() is not None
        outside = img.crop((147, 0, 300, 200)).getextrema()
        assert outside == (255, 255)

    def test_result_row_with_no_score_draws_dash(self):
        no_score = dict(_WC_SERIES, game_results=[
            {'winner_id': '143', 'game_pk': 1, 'date': '2026-10-01',
             'away_id': '143', 'home_id': '144'}
        ])
        assert _draw(no_score).getbbox() is not None

    def test_upcoming_game_shown_in_empty_slot(self):
        """Scheduled game appears in G2 slot when only G1 is played."""
        one_game = dict(_WC_SERIES, game_results=[_WC_SERIES['game_results'][0]])
        img_with  = _draw(one_game, fake_games=_FAKE_SCHED)
        img_blank = _draw(one_game, fake_games={'games': []})
        assert list(img_with.getdata()).count(0) > list(img_blank.getdata()).count(0)

    def test_upcoming_game_with_logos(self):
        one_game = dict(_WC_SERIES, game_results=[_WC_SERIES['game_results'][0]])
        img = _draw(one_game, use_logos=True, fake_games=_FAKE_SCHED)
        assert img.getbbox() is not None

    def test_upcoming_skips_final_games(self):
        from image_series import _scheduled_games
        from unittest.mock import patch
        fake = {'games': [{'detailed_state': 'Final',
                           'away_team_id': '143', 'home_team_id': '144',
                           'game_date': '2026-10-01T17:00:00Z'}]}
        with patch('image_series.load_json_file', return_value=fake):
            assert _scheduled_games('143', '144') == []

    def test_upcoming_load_error_returns_empty(self):
        from image_series import _scheduled_games
        from unittest.mock import patch
        with patch('image_series.load_json_file', side_effect=Exception('boom')):
            assert _scheduled_games('143', '144') == []

    def test_upcoming_no_matching_teams(self):
        from image_series import _scheduled_games
        from unittest.mock import patch
        fake = {'games': [{'detailed_state': 'Scheduled',
                           'away_team_id': '111', 'home_team_id': '999',
                           'game_date': '2026-10-01T17:00:00Z'}]}
        with patch('image_series.load_json_file', return_value=fake):
            assert _scheduled_games('143', '144') == []

    def test_upcoming_invalid_date_handled(self):
        from image_series import _scheduled_games
        from unittest.mock import patch
        fake = {'games': [{'detailed_state': 'Scheduled',
                           'away_team_id': '143', 'home_team_id': '144',
                           'game_date': 'NOT_A_DATE'}]}
        with patch('image_series.load_json_file', return_value=fake):
            result = _scheduled_games('143', '144')
            # Entry should appear but with empty time
            assert result[0]['time'] == ''


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
         patch('image_series.load_json_file', return_value={'games': []}), \
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

    def test_all_rounds_shown_not_just_wc(self):
        """DS, CS, WS series should also appear when there are free slots."""
        bracket = {'series': [
            dict(_NO_GAMES, round='DS', away_abbr='LAD', home_abbr='ATL',
                 away_id='119', home_id='144'),
        ]}
        assert len(_render_grid(3, bracket=bracket)) == 1

    def test_finished_wc_dropped_once_ds_is_active(self):
        bracket = {'series': [
            dict(_NO_GAMES, round='WC', away_abbr='BOS', home_abbr='NYY',
                 away_id='111', home_id='147', away_wins=0, home_wins=2, complete=True,
                 winner_abbr='NYY'),
            dict(_NO_GAMES, round='DS', away_abbr='NYY', home_abbr='TB',
                 away_id='147', home_id='139', away_wins=1, home_wins=0),
        ]}
        calls = _render_grid(3, bracket=bracket)
        assert [c[2:] for c in calls] == [('NYY', 'TB')]

    def test_wc_still_shown_while_wc_is_active(self):
        bracket = {'series': [
            dict(_NO_GAMES, round='WC', away_abbr='BOS', home_abbr='NYY',
                 away_id='111', home_id='147', away_wins=1, home_wins=0),
        ]}
        assert len(_render_grid(3, bracket=bracket)) == 1

    def test_series_dropped_when_its_winner_starts_next_round(self):
        """AL DS tile goes once the ALCS starts, even though an NL DS is still running."""
        bracket = {'series': [
            dict(_NO_GAMES, round='DS', away_abbr='NYY', home_abbr='TB',
                 away_id='147', home_id='139', away_wins=3, home_wins=1,
                 complete=True, winner_abbr='NYY'),
            dict(_NO_GAMES, round='DS', away_abbr='ATL', home_abbr='LAD',
                 away_id='144', home_id='119', away_wins=1, home_wins=1),
            dict(_NO_GAMES, round='CS', away_abbr='NYY', home_abbr='CLE',
                 away_id='147', home_id='114', away_wins=1, home_wins=0),
        ]}
        calls = _render_grid(3, bracket=bracket)
        assert [c[2:] for c in calls] == [('ATL', 'LAD'), ('NYY', 'CLE')]

    def test_missing_bracket_data_shows_nothing(self):
        assert _render_grid(3, bracket={}) == []
