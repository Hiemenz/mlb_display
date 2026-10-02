"""Tests for image_bracket_tile — 300×300 logos-only playoff bracket tree tile."""
from unittest.mock import patch

import pytest
from PIL import Image

import image_bracket_tile as bt


def _s(rnd, away, home, aw=0, hw=0, complete=False, winner=None):
    return {
        'round': rnd,
        'away_abbr': away[0], 'away_id': str(away[1]),
        'home_abbr': home[0], 'home_id': str(home[1]),
        'away_wins': aw, 'home_wins': hw,
        'complete': complete, 'winner_abbr': winner,
        'first_game_date': '2026-10-01',
    }


def _wc_bracket():
    return {
        'series': [
            _s('WC', ('NYY', 147), ('BOS', 111), 2, 0, True, 'NYY'),
            _s('WC', ('HOU', 117), ('CWS', 145), 1, 2, True, 'CWS'),
            _s('WC', ('ATL', 144), ('PHI', 143), 1, 1),
            _s('WC', ('SD',  135), ('CHC', 112), 2, 0, True, 'SD'),
        ]
    }


def _ds_bracket():
    return {
        'series': [
            _s('WC', ('NYY', 147), ('BOS', 111), 2, 0, True, 'NYY'),
            _s('WC', ('HOU', 117), ('CWS', 145), 0, 2, True, 'CWS'),
            _s('WC', ('ATL', 144), ('PHI', 143), 2, 1, True, 'ATL'),
            _s('WC', ('SD',  135), ('CHC', 112), 2, 0, True, 'SD'),
            _s('DS', ('NYY', 147), ('TB',  139), 1, 0),
            _s('DS', ('CWS', 145), ('CLE', 114), 0, 1),
            _s('DS', ('ATL', 144), ('LAD', 119), 0, 0),
            _s('DS', ('SD',  135), ('MIL', 158), 1, 0),
        ]
    }


def _ws_bracket():
    return {
        'series': [
            _s('WC', ('NYY', 147), ('BOS', 111), 2, 0, True, 'NYY'),
            _s('WC', ('HOU', 117), ('CWS', 145), 0, 2, True, 'CWS'),
            _s('WC', ('ATL', 144), ('PHI', 143), 2, 0, True, 'ATL'),
            _s('WC', ('SD',  135), ('CHC', 112), 2, 0, True, 'SD'),
            _s('DS', ('NYY', 147), ('TB',  139), 3, 1, True, 'NYY'),
            _s('DS', ('CWS', 145), ('CLE', 114), 1, 3, True, 'CLE'),
            _s('DS', ('ATL', 144), ('LAD', 119), 3, 2, True, 'ATL'),
            _s('DS', ('SD',  135), ('MIL', 158), 3, 0, True, 'SD'),
            _s('CS', ('NYY', 147), ('CLE', 114), 4, 2, True, 'NYY'),
            _s('CS', ('ATL', 144), ('SD',  135), 2, 4, True, 'SD'),
            _s('WS', ('NYY', 147), ('SD',  135), 3, 2),
        ]
    }


@pytest.fixture(autouse=True)
def no_logos():
    with patch('image_assets._logo_small', return_value=None), \
         patch('image_assets._logo_ghost', return_value=None):
        yield


def _canvas():
    return Image.new('1', (bt.TILE_W, bt.TILE_H), 255)


class TestDrawBracketTile:
    def test_returns_unchanged_when_no_series(self):
        assert bt.draw_bracket_tile(_canvas(), 0, 0, {}) is not None

    def test_returns_unchanged_when_bracket_none(self):
        assert bt.draw_bracket_tile(_canvas(), 0, 0, None) is not None

    def test_renders_wc_bracket(self):
        canvas = _canvas()
        assert bt.draw_bracket_tile(canvas, 0, 0, _wc_bracket()) is canvas

    def test_renders_ds_bracket(self):
        canvas = _canvas()
        assert bt.draw_bracket_tile(canvas, 0, 0, _ds_bracket()) is canvas

    def test_renders_ws_bracket(self):
        canvas = _canvas()
        assert bt.draw_bracket_tile(canvas, 0, 0, _ws_bracket()) is canvas

    def test_renders_with_offset(self):
        canvas = Image.new('1', (800, 480), 255)
        assert bt.draw_bracket_tile(canvas, 32, 30, _wc_bracket()) is canvas

    def test_returns_unchanged_when_build_slots_raises(self):
        with patch('bracket_view._build_slots', side_effect=RuntimeError('boom')):
            assert bt.draw_bracket_tile(_canvas(), 0, 0, _wc_bracket()) is not None

    def test_renders_dark_mode(self):
        canvas = _canvas()
        assert bt.draw_bracket_tile(canvas, 0, 0, _wc_bracket(), dark_mode=True) is canvas

    def test_renders_with_standings(self):
        canvas = _canvas()
        standings = {'standings': {}, 'team_abbreviation': {}}
        assert bt.draw_bracket_tile(canvas, 0, 0, _wc_bracket(), standings_data=standings) is canvas

    def test_sparse_bracket_skips_missing_connectors(self):
        sparse = {'series': [
            _s('WC', ('NYY', 147), ('BOS', 111), 2, 0, True, 'NYY'),
            _s('WC', ('SD',  135), ('CHC', 112), 2, 0, True, 'SD'),
        ]}
        canvas = _canvas()
        assert bt.draw_bracket_tile(canvas, 0, 0, sparse) is canvas


class TestDrawMatchup:
    def _tile_and_draw(self):
        tile = Image.new('1', (bt.TILE_W, bt.TILE_H), 255)
        from PIL import ImageDraw
        return tile, ImageDraw.Draw(tile)

    def test_none_series_draws_placeholder(self):
        tile, draw = self._tile_and_draw()
        cy = bt._slot_center_y(0, 1)
        bt._draw_matchup(tile, draw, 0, cy, None)

    def test_active_series(self):
        tile, draw = self._tile_and_draw()
        bt._draw_matchup(tile, draw, 0, bt._slot_center_y(0, 1),
                         _s('WC', ('NYY', 147), ('BOS', 111)))

    def test_complete_series_ghosts_loser(self):
        tile, draw = self._tile_and_draw()
        bt._draw_matchup(tile, draw, 3, bt._slot_center_y(0, 1),
                         _s('WS', ('NYY', 147), ('SD', 135), 4, 2, True, 'NYY'))

    def test_complete_no_winner_no_ghost(self):
        tile, draw = self._tile_and_draw()
        bt._draw_matchup(tile, draw, 0, bt._slot_center_y(0, 1),
                         _s('WC', ('NYY', 147), ('BOS', 111), complete=True, winner=None))

    def test_logo_pasted_when_available(self):
        tile, draw = self._tile_and_draw()
        fake = Image.new('1', (bt._LOGO_SZ, bt._LOGO_SZ), 0)
        with patch('image_assets._logo_small', return_value=fake):
            bt._draw_matchup(tile, draw, 0, bt._slot_center_y(0, 1),
                             _s('WC', ('NYY', 147), ('BOS', 111)))

    def test_ghost_logo_pasted_when_available(self):
        tile, draw = self._tile_and_draw()
        fake = Image.new('1', (bt._LOGO_SZ, bt._LOGO_SZ), 128)
        with patch('image_assets._logo_ghost', return_value=fake):
            bt._draw_matchup(tile, draw, 0, bt._slot_center_y(0, 1),
                             _s('WC', ('NYY', 147), ('BOS', 111), 2, 0, True, 'NYY'))


class TestDrawConnector:
    def _draw(self):
        tile = Image.new('1', (300, 300), 255)
        from PIL import ImageDraw
        return ImageDraw.Draw(tile)

    def test_straight_horizontal(self):
        bt._draw_connector(self._draw(), 10, 50, 50, 50)

    def test_elbow_down(self):
        bt._draw_connector(self._draw(), 10, 30, 50, 70)

    def test_elbow_up(self):
        bt._draw_connector(self._draw(), 10, 70, 50, 30)


class TestSlotGeometry:
    def test_slot_center_y_within_tile(self):
        cy = bt._slot_center_y(0, 1)
        assert bt._LABEL_H < cy < bt.TILE_H

    def test_slot_center_y_two_slots_ordered(self):
        assert bt._slot_center_y(0, 2) < bt._slot_center_y(1, 2)

    def test_band_cx_increases(self):
        for i in range(bt._N_BANDS - 1):
            assert bt._band_cx(i) < bt._band_cx(i + 1)

    def test_logo_sz_positive(self):
        assert bt._LOGO_SZ > 0

    def test_team_h_positive(self):
        assert bt._TEAM_H > 0
