"""Regular-season head-to-head footnote on postseason tiles."""
import os
import sys
from unittest.mock import MagicMock, patch

import requests
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import fetch_season_series as fss  # noqa: E402
from image_box import _TileCtx, _draw_season_series  # noqa: E402


def _game(away_id, home_id, away_won, state='Final'):
    return {'status': {'detailedState': state}, 'teams': {
        'away': {'team': {'id': away_id}, 'isWinner': away_won},
        'home': {'team': {'id': home_id}, 'isWinner': not away_won}}}


def _resp(games):
    r = MagicMock()
    r.json.return_value = {'dates': [{'games': games}]}
    return r


class TestSeasonSeriesFetch:
    def test_counts_wins_per_team_and_skips_unfinished(self):
        games = [_game(147, 111, True), _game(111, 147, True),
                 _game(147, 111, False), _game(147, 111, True, state='Scheduled')]
        with patch('fetch_season_series.load_json_file', return_value={}), \
             patch('fetch_season_series.save_off_results') as save, \
             patch('fetch_season_series.requests.get', return_value=_resp(games)):
            assert fss.season_series(147, 111, '2026') == {'147': 1, '111': 2}
        assert save.call_args[0][0] == {'2026:111-147': {'147': 1, '111': 2}}

    def test_cache_hit_skips_network_regardless_of_argument_order(self):
        cache = {'2026:111-147': {'147': 4, '111': 2}}
        with patch('fetch_season_series.load_json_file', return_value=cache), \
             patch('fetch_season_series.requests.get') as get:
            assert fss.season_series(111, 147, '2026') == {'147': 4, '111': 2}
        get.assert_not_called()

    def test_failure_returns_none_and_is_not_cached(self):
        with patch('fetch_season_series.load_json_file', return_value={}), \
             patch('fetch_season_series.save_off_results') as save, \
             patch('fetch_season_series.requests.get', side_effect=requests.ConnectionError):
            assert fss.season_series(147, 111, '2026') is None
        save.assert_not_called()


class TestSeasonSeriesDraw:
    @staticmethod
    def _draw(series, final=True, window=True):
        ctx = _TileCtx(Image.new('1', (800, 480), 255), 0, 0, 1, False, 2)
        before = ctx.Himage.tobytes()
        game = {'away_team_id': 147, 'home_team_id': 111, 'season_series': series}
        with patch('image_box.load_yaml_file', return_value={}):
            _draw_season_series(ctx, game, 'NYY', 'BOS', window, final)
        return ctx.Himage.tobytes() != before

    def test_drawn_when_final_in_window(self):
        assert self._draw({'147': 4, '111': 2})
        assert self._draw({'147': 3, '111': 3})

    def test_skipped_when_not_final_outside_window_or_missing(self):
        assert not self._draw({'147': 4, '111': 2}, final=False)
        assert not self._draw({'147': 4, '111': 2}, window=False)
        assert not self._draw(None)
