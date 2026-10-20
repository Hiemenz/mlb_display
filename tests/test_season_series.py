"""Regular-season head-to-head footnote on postseason tiles."""
import os
import sys
from unittest.mock import MagicMock, patch

import requests
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import fetch_season_series as fss  # noqa: E402
from image_series import _draw_season_series  # noqa: E402


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
    def _drawn(series):
        img = Image.new('1', (800, 480), 255)
        before = img.tobytes()
        _draw_season_series(ImageDraw.Draw(img), 0, 0, series)
        return img.tobytes() != before

    def test_drawn_for_leader_and_tie(self):
        base = {'away_id': 147, 'home_id': 111, 'away_abbr': 'NYY', 'home_abbr': 'BOS'}
        assert self._drawn(dict(base, season_series={'147': 4, '111': 2}))
        assert self._drawn(dict(base, season_series={'147': 2, '111': 4}))
        assert self._drawn(dict(base, season_series={'147': 3, '111': 3}))

    def test_removed_once_series_has_started(self):
        base = {'away_id': 147, 'home_id': 111, 'away_abbr': 'NYY', 'home_abbr': 'BOS',
                'season_series': {'147': 4, '111': 2}}
        assert self._drawn(dict(base, away_wins=0, home_wins=0, game_results=[]))
        assert not self._drawn(dict(base, away_wins=1, home_wins=0))
        assert not self._drawn(dict(base, game_results=[{'winner_id': 147}]))

    def test_skipped_when_missing(self):
        assert not self._drawn({'away_id': 147, 'home_id': 111})
        assert not self._drawn({'season_series': None})
