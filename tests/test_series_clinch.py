"""Series-clinch banner: the tile header inverts when a postseason game could
end its series (leader one win short of the N//2 + 1 needed).

Unit-tests the predicate, then pixel-checks each header-inversion site (single
cell, wide, triple, fullscreen) and that the standing banner yields to the
event flashes instead of cancelling them out.
"""
import pytest
from PIL import Image

import image_box
from image_box import draw_box, draw_triple_box, draw_wide_box
from image_utils import series_clinch_chance

from test_wide_cell import _live_game, _base_game
from test_image_featured import _live_game as _fs_live_game, TEAM_DATA as FS_TEAM_DATA, CONFIG as FS_CONFIG

TEAM_DATA = {'team_abbreviation': {'119': 'LAD', '137': 'SF'}}


@pytest.fixture(autouse=True)
def _historical():
    image_box.set_historical_mode(True)
    yield
    image_box.set_historical_mode(False)


def _series(**overrides):
    g = dict(game_type='D', series_total_games=5, series_wins=2, series_losses=1,
             series_is_over=False, series_is_tied=False, detailed_state='In Progress')
    g.update(overrides)
    return g


class TestPredicate:
    def test_bo5_leader_on_two_wins(self):
        assert series_clinch_chance(_series())

    def test_orientation_independent(self):
        assert series_clinch_chance(_series(series_wins=1, series_losses=2))

    def test_bo3_wildcard(self):
        assert series_clinch_chance(_series(game_type='F', series_total_games=3,
                                            series_wins=1, series_losses=0))

    def test_bo7_needs_three(self):
        assert series_clinch_chance(_series(game_type='L', series_total_games=7,
                                            series_wins=3, series_losses=1))
        assert not series_clinch_chance(_series(game_type='L', series_total_games=7,
                                                series_wins=2, series_losses=2))

    def test_series_tied_below_threshold_is_not_a_clinch(self):
        assert not series_clinch_chance(_series(series_wins=1, series_losses=1))
        assert not series_clinch_chance(_series(series_wins=0, series_losses=0))

    def test_tied_at_the_threshold_is_a_clinch_chance(self):
        assert series_clinch_chance(_series(series_wins=2, series_losses=2))

    def test_regular_season_never(self):
        assert not series_clinch_chance(_series(game_type='R'))
        assert not series_clinch_chance(_series(game_type=None))

    def test_finished_or_decided_or_off(self):
        assert not series_clinch_chance(_series(detailed_state='Final'))
        assert not series_clinch_chance(_series(series_is_over=True))
        assert not series_clinch_chance(_series(detailed_state='Postponed'))

    def test_scheduled_game_qualifies(self):
        assert series_clinch_chance(_series(detailed_state='Scheduled'))

    def test_single_game_and_missing_totals(self):
        assert not series_clinch_chance(_series(series_total_games=1))
        assert not series_clinch_chance(_series(series_total_games=None))

    def test_missing_wins_and_losses(self):
        assert not series_clinch_chance(_series(series_wins=None, series_losses=None))


def _header_ink(img, box):
    return sum(1 for x in range(box[0], box[2]) for y in range(box[1], box[3])
               if img.getpixel((x, y)) == 0)


def _blank():
    return Image.new('1', (800, 480), 255)


def _clinching(**overrides):
    return _live_game(**_series(), **overrides)


def _plain(**overrides):
    return _live_game(**_series(game_type='R'), **overrides)


class TestHeaderInversion:
    def test_single_cell_header_inverts(self):
        hdr = (32, 30, 32 + 120, 30 + 20)
        a = draw_box(_blank(), 32, 30, _clinching(), TEAM_DATA, use_logos=False)
        b = draw_box(_blank(), 32, 30, _plain(), TEAM_DATA, use_logos=False)
        assert _header_ink(a, hdr) != _header_ink(b, hdr)

    def test_single_cell_skip_header_invert_is_respected(self):
        a = draw_box(_blank(), 32, 30, _clinching(), TEAM_DATA, use_logos=False,
                     skip_header_invert=True)
        b = draw_box(_blank(), 32, 30, _plain(), TEAM_DATA, use_logos=False,
                     skip_header_invert=True)
        assert list(a.getdata()) == list(b.getdata())

    def test_single_cell_yields_to_a_run_scoring_flash(self):
        a = draw_box(_blank(), 32, 30, _clinching(last_play_rbi=1), TEAM_DATA, use_logos=False)
        b = draw_box(_blank(), 32, 30, _plain(last_play_rbi=1), TEAM_DATA, use_logos=False)
        assert list(a.getdata()) == list(b.getdata())

    def test_single_cell_yields_to_a_stolen_base_flash(self):
        a = draw_box(_blank(), 32, 30, _clinching(last_play='Stolen Base 2B'), TEAM_DATA, use_logos=False)
        b = draw_box(_blank(), 32, 30, _plain(last_play='Stolen Base 2B'), TEAM_DATA, use_logos=False)
        assert list(a.getdata()) == list(b.getdata())

    def test_single_cell_yields_to_an_active_no_hitter(self):
        kw = dict(no_hitter=True, current_inning=7)
        a = draw_box(_blank(), 32, 30, _clinching(**kw), TEAM_DATA, use_logos=False)
        b = draw_box(_blank(), 32, 30, _plain(**kw), TEAM_DATA, use_logos=False)
        assert list(a.getdata()) == list(b.getdata())

    def test_wide_header_inverts(self):
        a = draw_wide_box(_blank(), 0, 0, _clinching(), TEAM_DATA)
        b = draw_wide_box(_blank(), 0, 0, _plain(), TEAM_DATA)
        assert list(a.getdata()) != list(b.getdata())

    def test_wide_yields_to_a_run_scoring_flash(self):
        a = draw_wide_box(_blank(), 0, 0, _clinching(last_play_rbi=1), TEAM_DATA)
        b = draw_wide_box(_blank(), 0, 0, _plain(last_play_rbi=1), TEAM_DATA)
        assert list(a.getdata()) == list(b.getdata())

    def test_triple_header_inverts(self):
        a = draw_triple_box(_blank(), 0, 0, _clinching(), TEAM_DATA, use_logos=False)
        b = draw_triple_box(_blank(), 0, 0, _plain(), TEAM_DATA, use_logos=False)
        assert list(a.getdata()) != list(b.getdata())

    def test_triple_yields_to_a_run_scoring_flash(self):
        a = draw_triple_box(_blank(), 0, 0, _clinching(last_play_rbi=1), TEAM_DATA, use_logos=False)
        b = draw_triple_box(_blank(), 0, 0, _plain(last_play_rbi=1), TEAM_DATA, use_logos=False)
        assert list(a.getdata()) == list(b.getdata())

    def test_finished_game_header_is_not_inverted(self):
        fin = _base_game(**_series(detailed_state='Final'))
        plain = _base_game(**_series(detailed_state='Final', game_type='R'))
        a = draw_box(_blank(), 32, 30, fin, TEAM_DATA, use_logos=False)
        b = draw_box(_blank(), 32, 30, plain, TEAM_DATA, use_logos=False)
        assert list(a.getdata()) == list(b.getdata())


class TestFullscreen:
    def _fs(self, **kw):
        from image_featured import draw_live_fullscreen_game
        return draw_live_fullscreen_game(_fs_live_game(**kw), FS_TEAM_DATA, FS_CONFIG)

    def test_header_inverts(self):
        a = self._fs(**_series())
        b = self._fs(**_series(game_type='R'))
        assert _header_ink(a, (0, 0, 800, 40)) != _header_ink(b, (0, 0, 800, 40))

    def test_yields_to_a_run_scoring_flash(self):
        a = self._fs(**_series(), last_play_rbi=1)
        b = self._fs(**_series(game_type='R'), last_play_rbi=1)
        assert list(a.getdata()) == list(b.getdata())

    def test_yields_to_an_active_no_hitter(self):
        a = self._fs(**_series(), no_hitter=True, current_inning=7)
        b = self._fs(**_series(game_type='R'), no_hitter=True, current_inning=7)
        assert list(a.getdata()) == list(b.getdata())
