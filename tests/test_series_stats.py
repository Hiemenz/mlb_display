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


# ---------------------------------------------------------------------------
# Series leaders: build, fetch gating, tile, grid and main wiring
# ---------------------------------------------------------------------------
import time
from unittest.mock import MagicMock
from PIL import Image

import image_series_stats as iss
import main as main_mod


def _stats():
    return {'games': 1, 'teams': fss._add_up([fss._summarize_boxscore(BOX)])}


class TestBuildSeriesLeaders:
    def test_categories_ranked_across_teams(self):
        stats = {'games': 1, 'teams': {
            '1': {'batters': [{'name': 'A', 'atBats': 4, 'hits': 2, 'homeRuns': 1, 'rbi': 3, 'avg': 0.5},
                              {'name': 'Pinch', 'atBats': 1, 'hits': 1, 'homeRuns': 0, 'rbi': 0, 'avg': 1.0}],
                  'pitchers': [{'name': 'P', 'outs': 17, 'ip': '5.2', 'strikeOuts': 7}]},
            '2': {'batters': [{'name': 'B', 'atBats': 3, 'hits': 2, 'homeRuns': 1, 'rbi': 1, 'avg': 0.667},
                              {'name': 'Z', 'atBats': 3, 'hits': 0, 'homeRuns': 0, 'rbi': 0, 'avg': 0.0}],
                  'pitchers': [{'name': 'Q', 'outs': 0, 'ip': '0.0', 'strikeOuts': 0}]}}}
        out = fss.build_series_leaders(stats)
        assert [e['name'] for e in out['homeRuns']] == ['A', 'B']        # tie on HR broken by RBI
        assert [e['rank'] for e in out['homeRuns']] == [1, 1]            # equal HR share a rank
        assert out['battingAverage'][0]['name'] == 'B'                   # pinch hitter lacks 2 AB
        assert [e['name'] for e in out['battingAverage']] == ['B', 'A']
        assert out['inningsPitched'][0]['value'] == '5.2'
        assert 'Z' not in str(out) and 'Q' not in str(out)               # zero lines dropped

    def test_equal_values_share_rank(self):
        stats = {'games': 1, 'teams': {'1': {'batters': [
            {'name': 'A', 'atBats': 3, 'hits': 1, 'homeRuns': 0, 'rbi': 0, 'avg': .3},
            {'name': 'B', 'atBats': 3, 'hits': 1, 'homeRuns': 0, 'rbi': 0, 'avg': .3}], 'pitchers': []}}}
        assert [e['rank'] for e in fss.build_series_leaders(stats)['hits']] == [1, 1]


GAMES = [{'game_pk': 1, 'away_team_id': 147, 'home_team_id': 111, 'detailed_state': 'Final'},
         {'game_pk': 2, 'away_team_id': 147, 'home_team_id': 111, 'detailed_state': 'In Progress'},
         {'game_pk': 3, 'away_team_id': 119, 'home_team_id': 137, 'detailed_state': 'Final'}]
ABBRS = {'team_abbreviation': {'147': 'NYY', '111': 'BOS', '119': 'LAD', '137': 'SF'}}


def _loader(cached):
    """load_json_file stand-in: standings.json -> ABBRS, anything else -> cached."""
    return lambda name, *a, **k: ABBRS if name == 'standings.json' else cached


class TestFetchSeriesLeaders:
    def test_primary_game_selection(self):
        assert fss._primary_game(GAMES, 147)['game_pk'] == 2
        assert fss._primary_game(GAMES[:1] + GAMES[2:], 119)['game_pk'] == 3
        sched = [{'game_pk': 9, 'away_team_id': 1, 'home_team_id': 2, 'detailed_state': 'Scheduled'}]
        assert fss._primary_game(sched, 1)['game_pk'] == 9
        assert fss._primary_game(GAMES, None) is None

    def test_team_ids(self):
        with patch('fetch_series_stats.load_json_file', side_effect=_loader({})):
            assert fss._team_ids('NYY')[0] == 147
            assert fss._team_ids('XXX')[0] is None

    def test_no_primary_game_returns_empty(self):
        with patch('fetch_series_stats.load_json_file', side_effect=_loader({})):
            assert fss.fetch_series_leaders(GAMES, 'XXX') == {}

    def test_fresh_cache_skips_fetch(self):
        cached = {'key': '2:In Progress', 'fetched_at': time.time(), 'leaders': {}}
        with patch('fetch_series_stats.load_json_file', side_effect=_loader(cached)), \
             patch('fetch_series_stats.series_stats') as ss:
            assert fss.fetch_series_leaders(GAMES, 'NYY') == cached
        ss.assert_not_called()

    def test_live_cache_expires_after_five_minutes_but_idle_does_not(self):
        old = {'key': '2:In Progress', 'fetched_at': time.time() - 400, 'leaders': {}}
        with patch('fetch_series_stats.load_json_file', side_effect=_loader(old)), \
             patch('fetch_series_stats.series_stats', return_value=_stats()) as ss, \
             patch('fetch_series_stats.save_off_results') as sv:
            out = fss.fetch_series_leaders(GAMES, 'NYY')
        ss.assert_called_once()
        assert out['matchup'] == 'NYY @ BOS' and 'homeRuns' in out['leaders']
        sv.assert_called_once()
        final = [GAMES[0]]
        idle = {'key': '1:Final', 'fetched_at': time.time() - 400, 'leaders': {}}
        with patch('fetch_series_stats.load_json_file', side_effect=_loader(idle)), \
             patch('fetch_series_stats.series_stats') as ss:
            fss.fetch_series_leaders(final, 'NYY')
        ss.assert_not_called()

    def test_failure_keeps_previous_file(self):
        cached = {'key': 'old', 'fetched_at': 0, 'leaders': {'hits': []}}
        with patch('fetch_series_stats.load_json_file', side_effect=_loader(cached)), \
             patch('fetch_series_stats.series_stats', return_value=None), \
             patch('fetch_series_stats.save_off_results') as sv:
            assert fss.fetch_series_leaders(GAMES, 'NYY') == cached
        sv.assert_not_called()


DATA = {'leaders': {'homeRuns': [{'rank': 1, 'value': '2', 'name': 'A Hitter', 'team_id': '1'}],
                    'battingAverage': [{'rank': 1, 'value': '0.500', 'name': 'B', 'team_id': '2'}]}}


class TestSeriesTile:
    def test_available_categories_in_display_order(self):
        assert iss.available_categories(DATA) == ['homeRuns', 'battingAverage']
        assert iss.available_categories(None) == []

    def test_average_format(self):
        assert iss._format('battingAverage', '0.500') == '.500'
        assert iss._format('battingAverage', '1.000') == '1.000'
        assert iss._format('homeRuns', '2') == '2'

    def test_draws_and_marks_pixels(self):
        img = Image.new('1', (800, 480), 255)
        iss.draw_series_stats_cell(img, 32, 30, DATA, {'team_abbreviation': {'1': 'NYY'}}, 'homeRuns')
        assert img.getbbox() is not None
        assert img.crop((32, 30, 167, 160)).getextrema() == (0, 255)

    def test_empty_category_says_no_data(self):
        img = Image.new('1', (800, 480), 255)
        iss.draw_series_stats_cell(img, 32, 30, DATA, {}, 'strikeOuts')
        assert img.crop((32, 30, 167, 160)).getextrema() == (0, 255)


def test_main_refresh_gated_on_config_and_league():
    with patch.object(main_mod, 'fetch_series_leaders') as f:
        main_mod._refresh_series_leaders({'show_series_panel': False}, 'mlb')
        main_mod._refresh_series_leaders({'show_series_panel': True}, 'aaa')
        f.assert_not_called()
        with patch.object(main_mod, 'load_json_file', return_value={'games': GAMES}):
            main_mod._refresh_series_leaders({'show_series_panel': True, 'primary': 'NYY'}, 'mlb', force=True)
        f.assert_called_once_with(GAMES, 'NYY', force=True)


def test_main_refresh_swallows_errors(capsys):
    with patch.object(main_mod, 'fetch_series_leaders', side_effect=RuntimeError('boom')), \
         patch.object(main_mod, 'load_json_file', return_value={}):
        main_mod._refresh_series_leaders({'show_series_panel': True}, 'mlb')
    assert 'boom' in capsys.readouterr().out


def test_short_name():
    assert fss._short_name('Munetaka Murakami') == 'M. Murakami'
    assert fss._short_name('Fernando Tatis Jr.') == 'F. Tatis Jr.'
    assert fss._short_name('Ohtani') == 'Ohtani'
    assert fss._short_name('') == ''
