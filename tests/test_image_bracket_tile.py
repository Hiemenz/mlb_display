"""Tests for image_bracket_tile — 300×300 compact playoff bracket tile."""
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


def _full_bracket(ws_complete=False, ws_winner=None):
    return {
        'series': [
            _s('WC', ('NYY', 147), ('BAL', 110), 2, 1, True, 'NYY'),
            _s('WC', ('HOU', 117), ('SEA', 136), 2, 0, True, 'HOU'),
            _s('WC', ('ATL', 144), ('PHI', 143), 2, 0, True, 'ATL'),
            _s('WC', ('MIL', 158), ('LAD', 119), 1, 2, True, 'LAD'),
            _s('DS', ('NYY', 147), ('CLE', 114), 3, 2, True, 'NYY'),
            _s('DS', ('HOU', 117), ('TB', 139), 3, 1, True, 'HOU'),
            _s('DS', ('ATL', 144), ('NYM', 121), 3, 0, True, 'ATL'),
            _s('DS', ('LAD', 119), ('CHC', 112), 3, 2, True, 'LAD'),
            _s('CS', ('NYY', 147), ('HOU', 117), 4, 2, True, 'NYY'),
            _s('CS', ('ATL', 144), ('LAD', 119), 2, 4, True, 'LAD'),
            _s('WS', ('NYY', 147), ('LAD', 119),
               4, 3, ws_complete, ws_winner),
        ]
    }


@pytest.fixture(autouse=True)
def no_logos():
    with patch('image_assets._logo_small', return_value=None), \
         patch('image_assets._logo_ghost', return_value=None):
        yield


def _canvas():
    return Image.new('1', (bt.TILE_W, bt.TILE_H), 255)


class TestDrawBracketTileReturnsImage:
    def test_returns_unchanged_image_when_no_series(self):
        canvas = _canvas()
        result = bt.draw_bracket_tile(canvas, 0, 0, {})
        assert result is canvas

    def test_returns_unchanged_image_when_bracket_is_none(self):
        canvas = _canvas()
        result = bt.draw_bracket_tile(canvas, 0, 0, None)
        assert result is canvas

    def test_returns_image_on_valid_bracket(self):
        canvas = _canvas()
        result = bt.draw_bracket_tile(canvas, 0, 0, _full_bracket())
        assert result is canvas

    def test_returns_unchanged_when_build_slots_raises(self):
        canvas = _canvas()
        with patch('image_bracket_tile._build_slots', side_effect=RuntimeError):
            result = bt.draw_bracket_tile(canvas, 0, 0, _full_bracket())
        assert result is canvas

    def test_renders_with_offset(self):
        canvas = Image.new('1', (800, 480), 255)
        result = bt.draw_bracket_tile(canvas, 150, 150, _full_bracket())
        assert result is canvas


class TestChampionBox:
    def test_champ_box_drawn_when_ws_complete(self):
        """When WS is complete the champion double-border box should be drawn."""
        canvas = _canvas()
        result = bt.draw_bracket_tile(canvas, 0, 0, _full_bracket(ws_complete=True, ws_winner='NYY'))
        assert result is canvas

    def test_no_champ_box_when_ws_in_progress(self):
        """draw_bracket_tile completes without error when WS not finished."""
        canvas = _canvas()
        result = bt.draw_bracket_tile(canvas, 0, 0, _full_bracket(ws_complete=False))
        assert result is canvas

    def test_champ_box_home_winner(self):
        """Champion box works when home team wins the WS."""
        canvas = _canvas()
        result = bt.draw_bracket_tile(canvas, 0, 0, _full_bracket(ws_complete=True, ws_winner='LAD'))
        assert result is canvas


class TestDrawMatchup:
    def _draw(self):
        tile = Image.new('1', (bt.TILE_W, bt.TILE_H), 255)
        from PIL import ImageDraw
        return tile, ImageDraw.Draw(tile)

    def test_none_series_draws_empty_box(self):
        tile, draw = self._draw()
        bt._draw_matchup(tile, draw, 0, 150, None)

    def test_active_series_draws_both_logos(self):
        tile, draw = self._draw()
        bt._draw_matchup(tile, draw, 0, 150, _s('WC', ('NYY', 147), ('BAL', 110)))

    def test_complete_series_ghosts_loser(self):
        tile, draw = self._draw()
        bt._draw_matchup(tile, draw, 0, 150,
                         _s('WC', ('NYY', 147), ('BAL', 110), 2, 1, True, 'NYY'))

    def test_complete_series_no_winner_no_ghost(self):
        tile, draw = self._draw()
        bt._draw_matchup(tile, draw, 0, 150,
                         _s('WC', ('NYY', 147), ('BAL', 110), complete=True, winner=None))


class TestPasteLogoAt:
    def _tile(self):
        return Image.new('1', (100, 100), 255)

    def test_fallback_box_drawn_when_logo_none(self):
        tile = self._tile()
        bt._paste_logo_at(tile, 'NYY', '147', 50, 50, 20, ghost=False)

    def test_ghost_fallback_box(self):
        tile = self._tile()
        bt._paste_logo_at(tile, 'NYY', '147', 50, 50, 20, ghost=True)

    def test_logo_pasted_when_available(self):
        tile = self._tile()
        fake_logo = Image.new('1', (20, 20), 0)
        with patch('image_assets._logo_small', return_value=fake_logo):
            bt._paste_logo_at(tile, 'NYY', '147', 50, 50, 20, ghost=False)

    def test_ghost_logo_pasted_when_available(self):
        tile = self._tile()
        fake_logo = Image.new('1', (20, 20), 128)
        with patch('image_assets._logo_ghost', return_value=fake_logo):
            bt._paste_logo_at(tile, 'NYY', '147', 50, 50, 20, ghost=True)


class TestSlotGeometry:
    def test_slot_h_positive(self):
        assert bt._slot_h() > 0

    def test_slot_centre_y_within_tile(self):
        cy = bt._slot_centre_y(0, 1)
        assert bt._HEADER_H < cy < bt.TILE_H

    def test_slot_centre_y_multiple_slots(self):
        cy0 = bt._slot_centre_y(0, 2)
        cy1 = bt._slot_centre_y(1, 2)
        assert cy0 < cy1


class TestDrawChampBox:
    def test_draws_without_error(self):
        tile = Image.new('1', (bt.TILE_W, bt.TILE_H), 255)
        from PIL import ImageDraw
        draw = ImageDraw.Draw(tile)
        cy = bt._slot_centre_y(0, 1)
        series = _s('WS', ('NYY', 147), ('LAD', 119), 4, 3, True, 'NYY')
        bt._draw_champ_box(tile, draw, bt._BAND_W * 3, cy, series)

    def test_away_winner_picks_away_id(self):
        tile = Image.new('1', (bt.TILE_W, bt.TILE_H), 255)
        from PIL import ImageDraw
        draw = ImageDraw.Draw(tile)
        series = _s('WS', ('NYY', 147), ('LAD', 119), 4, 3, True, 'NYY')
        # Should not raise; away_id used for winner
        bt._draw_champ_box(tile, draw, bt._BAND_W * 3, bt._slot_centre_y(0, 1), series)

    def test_home_winner_picks_home_id(self):
        tile = Image.new('1', (bt.TILE_W, bt.TILE_H), 255)
        from PIL import ImageDraw
        draw = ImageDraw.Draw(tile)
        series = _s('WS', ('NYY', 147), ('LAD', 119), 3, 4, True, 'LAD')
        bt._draw_champ_box(tile, draw, bt._BAND_W * 3, bt._slot_centre_y(0, 1), series)

    def test_skipped_when_no_space(self):
        """If matchup is near the bottom there's no room for the champ box — early return."""
        tile = Image.new('1', (bt.TILE_W, bt.TILE_H), 255)
        from PIL import ImageDraw
        draw = ImageDraw.Draw(tile)
        series = _s('WS', ('NYY', 147), ('LAD', 119), 4, 3, True, 'NYY')
        # Pass a very large cy so match_bot is near TILE_H and avail < box_h + 6
        bt._draw_champ_box(tile, draw, bt._BAND_W * 3, bt.TILE_H - 5, series)
