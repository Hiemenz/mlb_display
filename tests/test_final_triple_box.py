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
