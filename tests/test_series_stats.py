"""Tests for fetch_series_stats and the cache-pruning helpers in util."""
import json
import os
from datetime import date, timedelta
from unittest.mock import patch

import pytest
import requests

import fetch_series_stats as fss
import util


def _player(pid, name, bat=None, pit=None):
    stats = {}
    if bat:
        stats['batting'] = bat
    if pit:
        stats['pitching'] = pit
    return {'person': {'id': pid, 'fullName': name}, 'stats': stats}


def _box(away_players, home_players):
    return {'teams': {'away': {'team': {'id': 1}, 'players': {f'ID{i}': p for i, p in enumerate(away_players)}},
                      'home': {'team': {'id': 2}, 'players': {f'ID{i}': p for i, p in enumerate(home_players)}}}}


BOX = _box(
    [_player(10, 'A Hitter', bat={'atBats': 4, 'hits': 2, 'homeRuns': 1, 'rbi': 3}),
     _player(11, 'Bench', bat={}),
     _player(12, 'A Pitcher', pit={'inningsPitched': '5.2', 'earnedRuns': 2, 'strikeOuts': 7, 'wins': 1})],
    [_player(20, 'H Hitter', bat={'atBats': 3, 'hits': 0, 'baseOnBalls': 1}),
     _player(21, 'H Pitcher', pit={'inningsPitched': '0.0', 'battersFaced': 3})])


class TestPruneStale:
    def test_drops_old_and_unreadable_keeps_fresh(self):
        d = {'old': 0, 'new': 1000, 'bad': 'x', 'none': None}
        removed = util.prune_stale(d, float, 100, now=1050)
        assert removed == 3
        assert d == {'new': 1000}

    def test_empty(self):
        assert util.prune_stale({}, float, 1) == 0


class TestAtomicSave:
    def test_roundtrip_and_no_temp_left(self, tmp_path):
        util.save_off_results({'a': 1}, 'x', file_path=str(tmp_path))
        util.save_off_results({'a': 2}, 'x', file_path=str(tmp_path))
        assert json.load(open(tmp_path / 'x.json')) == {'a': 2}
        assert os.listdir(tmp_path) == ['x.json']

    def test_failure_keeps_old_file_and_cleans_temp(self, tmp_path):
        util.save_off_results({'a': 1}, 'x', file_path=str(tmp_path))
        with pytest.raises(TypeError):
            util.save_off_results({'a': object()}, 'x', file_path=str(tmp_path))
        assert json.load(open(tmp_path / 'x.json')) == {'a': 1}
        assert os.listdir(tmp_path) == ['x.json']


class TestSummarize:
    def test_keeps_only_players_who_played(self):
        s = fss._summarize_boxscore(BOX)
        assert list(s['1']['batters']) == ['10']
        assert s['1']['batters']['10']['rbi'] == 3
        assert s['1']['pitchers']['12']['outs'] == 17
        assert list(s['2']['batters']) == ['20']   # walk-only line still counts
        assert s['2']['pitchers']['21']['outs'] == 0  # faced batters, no outs

    def test_innings_conversion(self):
        assert fss._innings_to_outs('5.2') == 17
        assert fss._innings_to_outs(None) == 0
        assert fss.outs_to_innings(17) == '5.2'


class TestAddUp:
    def test_sums_across_games_and_sorts(self):
        g = fss._summarize_boxscore(BOX)
        out = fss._add_up([g, g])
        b = out['1']['batters'][0]
        assert (b['atBats'], b['hits'], b['homeRuns'], b['rbi']) == (8, 4, 2, 6)
        assert b['avg'] == 0.5
        p = out['1']['pitchers'][0]
        assert p['ip'] == '11.1' and p['strikeOuts'] == 14
        assert p['era'] == pytest.approx(4 * 27 / 34)
        assert out['2']['batters'][0]['avg'] == 0.0


class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def _sched(games):
    return _Resp({'dates': [{'games': games}]})


def _sg(pk, num, state, day, home=2):
    return {'gamePk': pk, 'seriesGameNumber': num, 'gameDate': f'{day}T20:00:00Z', 'officialDate': day,
            'status': {'detailedState': state}, 'teams': {'home': {'team': {'id': home}}}}


class TestSeriesGamePks:
    def test_filters_to_series_and_orders(self):
        day = '2026-07-10'
        games = [_sg(3, 3, 'Scheduled', day), _sg(1, 1, 'Final', '2026-07-08'), _sg(2, 2, 'Final', '2026-07-09'),
                 _sg(9, 3, 'Final', '2026-07-01', home=1), _sg(8, 3, 'Final', '2026-07-02')]
        with patch('fetch_series_stats.requests.get', return_value=_sched(games)):
            out = fss.series_game_pks(1, 2, f'{day}T20:00:00Z', 3)
        assert [pk for pk, _, _ in out] == [8, 1, 2, 3][-3:]


class TestSeriesStats:
    def _game(self):
        return {'away_team_id': 1, 'home_team_id': 2, 'game_date': '2026-07-10T20:00:00Z',
                'series_game_number': 3}

    def test_caches_finals_not_live_and_prunes(self, tmp_path):
        old = (date.today() - timedelta(days=30)).isoformat()
        cache = {'555': {'played': old, 'teams': {}}}
        pks = [(100, 'Final', date.today().isoformat()), (101, 'In Progress', date.today().isoformat()),
               (102, 'Scheduled', date.today().isoformat())]
        saved = {}
        with patch('fetch_series_stats.series_game_pks', return_value=pks), \
             patch('fetch_series_stats._fetch_boxscore', return_value=fss._summarize_boxscore(BOX)) as fb, \
             patch('fetch_series_stats.load_json_file', return_value=cache), \
             patch('fetch_series_stats.save_off_results', side_effect=lambda d, n: saved.update(d)):
            r = fss.series_stats(self._game())
        assert r['games'] == 2
        assert fb.call_count == 2          # scheduled game skipped
        assert set(saved) == {'100'}       # live game not cached, stale entry pruned

    def test_cached_final_not_refetched(self):
        today = date.today().isoformat()
        cache = {'100': {'played': today, 'teams': fss._summarize_boxscore(BOX)}}
        with patch('fetch_series_stats.series_game_pks', return_value=[(100, 'Final', today)]), \
             patch('fetch_series_stats._fetch_boxscore') as fb, \
             patch('fetch_series_stats.load_json_file', return_value=cache), \
             patch('fetch_series_stats.save_off_results') as sv:
            r = fss.series_stats(self._game())
        fb.assert_not_called()
        sv.assert_not_called()
        assert r['games'] == 1

    @pytest.mark.parametrize('exc', [requests.ConnectionError('x'), KeyError('k'), ValueError('v')])
    def test_failure_returns_none(self, exc):
        with patch('fetch_series_stats.series_game_pks', side_effect=exc):
            assert fss.series_stats(self._game()) is None

    def test_missing_fields_returns_none(self):
        assert fss.series_stats({}) is None


def test_fetch_boxscore_summarizes_response():
    with patch('fetch_series_stats.requests.get', return_value=_Resp(BOX)):
        assert '10' in fss._fetch_boxscore(1)['1']['batters']
