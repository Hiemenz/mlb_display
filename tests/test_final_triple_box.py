"""Postseason finished-game tile: normal final box + linescore + full spray chart."""
from unittest.mock import patch

from PIL import Image

from image_box import draw_final_triple_box

TEAM_DATA = {'team_abbreviation': {'139': 'TB', '147': 'NYY'}}


def _final(hits):
    return {
        'detailed_state': 'Final', 'abstract_game_state': 'Final',
        'away_team_id': 139, 'home_team_id': 147, 'away_abbr': 'TB', 'home_abbr': 'NYY',
        'away_runs': 3, 'home_runs': 5, 'away_hits': 7, 'home_hits': 10,
        'away_errors': 0, 'home_errors': 1, 'current_inning': 9,
        'away_inning_runs': [0, 0, 1, 0, 0, 2, 0, 0, 0],
        'home_inning_runs': [1, 0, 0, 2, 0, 0, 2, 0, None],
        'winner_name': 'Gerrit Cole', 'loser_name': 'Zach Eflin',
        'winner_record': '1-0', 'loser_record': '0-1',
        'away_team_is_winner': False, 'home_team_is_winner': True,
        'venue': 'Yankee Stadium', 'all_game_hits': hits,
    }


def _render(game):
    img = Image.new('1', (800, 480), 255)
    with patch('image_assets._logo_small', return_value=None), \
         patch('image_assets._logo_ghost', return_value=None):
        return draw_final_triple_box(img, 32, 18, game, TEAM_DATA)


def test_spray_chart_only_appears_in_the_field_cell():
    hit = {'x': 150, 'y': 150, 'is_hr': False, 'is_hit': True, 'is_out': False}
    out = {'x': 100, 'y': 130, 'is_hr': False, 'is_hit': False, 'is_out': True}
    with_hits, without = _render(_final([hit, out])), _render(_final([]))
    diff = Image.eval(with_hits.convert('L'), lambda v: v).copy()
    changed = [(x, y) for x in range(800) for y in range(480)
               if with_hits.getpixel((x, y)) != without.getpixel((x, y))]
    field_x0 = 32 + 135 + 150
    in_field = [p for p in changed if p[0] >= field_x0]
    in_mid = [p for p in changed if 32 + 135 <= p[0] < field_x0]
    assert in_field                      # dots drawn on the field
    assert len(in_mid) > 0               # tally in the middle cell changes with the counts
    assert diff is not None


def test_handles_missing_pitchers_and_hits():
    game = _final([])
    game.update(winner_name=None, loser_name=None)
    assert _render(game).size == (800, 480)


# ---------------------------------------------------------------------------
# Grid wiring and data fetch
# ---------------------------------------------------------------------------
import image_grid as ig
import game_detail_fetch as gdf

_ABBRS = {'team_abbreviation': {'139': 'TB', '147': 'NYY', '111': 'BOS', '119': 'LAD'}}
_SPRAY = [{'x': 100, 'y': 100, 'is_hr': False, 'is_hit': True, 'is_out': False}]


def _g(away, home, state='Final', gtype='L', hits=_SPRAY):
    return {'away_team_id': away, 'home_team_id': home, 'detailed_state': state,
            'game_type': gtype, 'all_game_hits': hits}


def test_final_spray_game_needs_postseason_final_with_hits():
    assert ig._is_final_spray_game(_g(139, 147))
    assert not ig._is_final_spray_game(_g(139, 147, gtype='R'))
    assert not ig._is_final_spray_game(_g(139, 147, state='In Progress'))
    assert not ig._is_final_spray_game(_g(139, 147, hits=[]))


def test_finals_get_triples_featured_first_within_budget():
    games = [_g(111, 119), _g(139, 147), _g(1, 2)]
    tiles = {}
    ig._add_final_triples(tiles, games, {'primary': 'NYY'}, _ABBRS)
    assert tiles == {1: 'triple', 0: 'triple', 2: 'triple'}
    tiles = {}
    ig._add_final_triples(tiles, games * 5, {'primary': 'NYY'}, _ABBRS)   # 15 games: no room
    assert tiles == {}


def test_live_triples_use_budget_first():
    games = [_g(139, 147)] + [_g(1, 2, hits=[]) for _ in range(11)]
    tiles = {5: 'triple', 6: 'triple'}           # 12 games + 2 triples leave 1 spare unit
    ig._add_final_triples(tiles, games, {}, _ABBRS)
    assert 0 not in tiles


def test_grid_draws_final_triple_for_finished_postseason_game():
    game = _final(_SPRAY)
    game.update(game_type='L', game_pk=1)
    with patch('image_grid.draw_final_triple_box', side_effect=lambda img, *a, **k: img) as d, \
         patch('image_grid.load_yaml_file', return_value={}):
        ig.draw_out_of_town_score_board(Image.new('1', (800, 480), 255), [game], TEAM_DATA)
    d.assert_called_once()


class _Feed:
    def __init__(self, plays):
        self._plays = plays

    def raise_for_status(self):
        pass

    def json(self):
        return {'liveData': {'plays': {'allPlays': self._plays}}}


_PLAY = {'result': {'event': 'Single'}, 'about': {'inning': 1, 'halfInning': 'top'},
         'matchup': {'batter': {'fullName': 'A Hitter'}},
         'hitData': {'coordinates': {'coordX': 120, 'coordY': 150}}}


def test_fetch_final_spray_caches_and_reuses():
    saved = {}
    with patch('game_detail_fetch.requests.get', return_value=_Feed([_PLAY])) as get, \
         patch('util.load_json_file', side_effect=lambda n, *a, **k: saved), \
         patch('util.save_off_results', side_effect=lambda d, n: saved.update(d)):
        first = gdf.fetch_final_spray(7)
        second = gdf.fetch_final_spray(7)
    assert first == second == [{'x': 120, 'y': 150, 'is_hr': False, 'is_hit': True, 'is_out': False}]
    assert get.call_count == 1


def test_fetch_final_spray_failure_returns_none_and_caches_nothing():
    import requests
    with patch('game_detail_fetch.requests.get', side_effect=requests.RequestException('boom')), \
         patch('util.load_json_file', return_value={}), \
         patch('util.save_off_results') as sv:
        assert gdf.fetch_final_spray(8) is None
    sv.assert_not_called()


def test_fetch_final_spray_prunes_week_old_entries():
    cache = {'old': {'saved': 0, 'hits': []}}
    with patch('game_detail_fetch.requests.get', return_value=_Feed([_PLAY])), \
         patch('util.load_json_file', return_value=cache), \
         patch('util.save_off_results', side_effect=lambda d, n: cache.update(d) if False else None) as sv:
        gdf.fetch_final_spray(9)
    assert set(sv.call_args.args[0]) == {'9'}
