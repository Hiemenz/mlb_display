"""
Smoke tests for the wide-cell (2-slot) scoreboard feature.

Covers:
  1. draw_wide_box: in-progress, between-innings, no-pitch-data edge cases
  2. _draw_wide_right_panel: pitch rendering with missing/partial data
  3. _find_wide_games: slot selection logic for <15 and 15+ game slates
  4. draw_out_of_town_score_board: end-to-end grid with wide cells
"""

import pytest
from unittest.mock import patch

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def white_image():
    return Image.new('1', (800, 480), 255)


@pytest.fixture
def team_data():
    return {
        'team_abbreviation': {
            '119': 'LAD',
            '137': 'SF',
            '133': 'OAK',
            '144': 'ATL',
            '147': 'NYY',
            '111': 'BOS',
        }
    }


def _base_game(**overrides):
    g = {
        'game_pk': 1001,
        'away_team_id': 119,
        'home_team_id': 137,
        'away_team_name': 'LAD',
        'home_team_name': 'SF',
        'detailed_state': 'Final',
        'away_runs': 3,
        'home_runs': 5,
        'away_hits': 8,
        'home_hits': 10,
        'away_errors': 0,
        'home_errors': 1,
        'away_team_is_winner': False,
        'home_team_is_winner': True,
        'winner_name': 'Logan Webb',
        'loser_name': 'Clayton Kershaw',
        'saver_name': None,
        'winner_record': '5-2',
        'loser_record': '3-4',
        'saver_saves': None,
        'current_inning': 9,
        'inningState': 'End',
        'away_inning_runs': [0, 1, 0, 0, 0, 2, 0, 0, 0],
        'home_inning_runs': [1, 0, 2, 0, 0, 0, 1, 0, 1],
        'away_team_record_wins': 40,
        'away_team_record_losses': 30,
        'home_team_record_wins': 45,
        'home_team_record_losses': 25,
        'num_of_outs': 3,
        'balls': None,
        'strikes': None,
        'runner_on_first': None,
        'runner_on_second': None,
        'runner_on_third': None,
        'game_start': '7:05 PM',
        'game_datetime': '2026-06-20T23:05:00Z',
        'away_probable': None,
        'home_probable': None,
        'away_probable_note': None,
        'home_probable_note': None,
        'no_hitter': False,
        'perfect_game': False,
        'save_situation': False,
        'walk_off': False,
        'last_play': None,
        'venue': 'Oracle Park',
        'current_hitter': None,
        'current_pitcher': None,
        'due_up': None,
        'in_hole': None,
        'game_duration_minutes': None,
        'series_result': '',
        'series_game_number': 1,
        'series_total_games': 3,
        'series_wins': 0,
        'series_losses': 0,
        'series_is_tied': False,
        'series_is_over': False,
    }
    g.update(overrides)
    return g


def _live_game(**overrides):
    """In-progress game with pitch data."""
    g = _base_game(
        detailed_state='In Progress',
        current_inning=7,
        inningState='Top',
        num_of_outs=1,
        balls=2,
        strikes=1,
        strike_calls=['C', 'S'],
        runner_on_first='Mookie Betts',
        runner_on_second=None,
        runner_on_third=None,
        runner_first_number=50,
        runner_second_number=None,
        runner_third_number=None,
        current_pitcher='Logan Webb',
        current_hitter='Mookie Betts',
        current_play_batter='Mookie Betts',
        pitch_count=82,
        last_pitch_type='FB',
        last_pitch_speed=93.4,
        batter_hits=2,
        batter_at_bats=3,
        current_at_bat_complete=False,
        ab_pitches=[
            {'seq': 1, 'px': -0.3, 'pz': 2.8, 'sz_top': 3.4, 'sz_bot': 1.6,
             'code': 'C', 'pt_abbr': 'FB'},
            {'seq': 2, 'px': 0.9,  'pz': 1.2, 'sz_top': 3.4, 'sz_bot': 1.6,
             'code': 'B', 'pt_abbr': 'SL'},
            {'seq': 3, 'px': 0.1,  'pz': 2.5, 'sz_top': 3.4, 'sz_bot': 1.6,
             'code': 'S', 'pt_abbr': 'CH'},
        ],
        half_inning_plays=['K', '1B'],
        home_pitcher_ks=['K', 'K', 'L', 'K'],
        away_pitcher_ks=['K', 'L'],
        away_win_probability=42.0,
        home_win_probability=58.0,
    )
    g.update(overrides)
    return g


def _between_innings_game(**overrides):
    g = _live_game(
        inningState='Middle',
        num_of_outs=3,
        ab_pitches=[],
        next_batter_1='Freddie Freeman',
        next_batter_2='Will Smith',
        next_batter_3='Max Muncy',
    )
    g.update(overrides)
    return g


# ---------------------------------------------------------------------------
# 1. draw_wide_box smoke tests
# ---------------------------------------------------------------------------

@needs_pil
def test_wide_box_in_progress(white_image, team_data):
    from image_box import draw_wide_box
    result = draw_wide_box(white_image, 0, 0, _live_game(), team_data)
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)


@needs_pil
def test_wide_box_between_innings(white_image, team_data):
    from image_box import draw_wide_box
    result = draw_wide_box(white_image, 0, 0, _between_innings_game(), team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_no_pitches(white_image, team_data):
    from image_box import draw_wide_box
    result = draw_wide_box(white_image, 0, 0, _live_game(ab_pitches=[]), team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_missing_optional_fields(white_image, team_data):
    """All optional right-panel fields absent — must not raise."""
    from image_box import draw_wide_box
    game = _live_game()
    for field in ('current_pitcher', 'current_hitter', 'current_play_batter',
                  'pitch_count', 'last_pitch_type', 'last_pitch_speed',
                  'batter_hits', 'batter_at_bats', 'half_inning_plays',
                  'home_pitcher_ks', 'away_pitcher_ks',
                  'away_win_probability', 'home_win_probability'):
        game.pop(field, None)
    result = draw_wide_box(white_image, 0, 0, game, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_no_sz_bounds(white_image, team_data):
    """Pitches without sz_top/sz_bot fall back to MLB average constants."""
    from image_box import draw_wide_box
    game = _live_game(ab_pitches=[
        {'seq': 1, 'px': 0.0, 'pz': 2.5, 'code': 'C', 'pt_abbr': 'FB'},
    ])
    result = draw_wide_box(white_image, 0, 0, game, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_none_pitch_coords(white_image, team_data):
    """Pitches with None px/pz are skipped without crashing."""
    from image_box import draw_wide_box
    game = _live_game(ab_pitches=[
        {'seq': 1, 'px': None, 'pz': None, 'code': 'B', 'pt_abbr': 'FB'},
        {'seq': 2, 'px': 0.1,  'pz': 2.8,  'code': 'S', 'pt_abbr': 'SL'},
    ])
    result = draw_wide_box(white_image, 0, 0, game, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_many_pitches(white_image, team_data):
    """10-pitch at-bat — zone list truncates, no crash."""
    from image_box import draw_wide_box
    pitches = [
        {'seq': i, 'px': 0.1 * (i % 3 - 1), 'pz': 2.0 + 0.2 * i,
         'sz_top': 3.4, 'sz_bot': 1.6, 'code': 'S' if i % 2 else 'B', 'pt_abbr': 'FB'}
        for i in range(1, 11)
    ]
    result = draw_wide_box(white_image, 0, 0, _live_game(ab_pitches=pitches), team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_with_win_prob(white_image, team_data):
    from image_box import draw_wide_box
    result = draw_wide_box(
        white_image, 0, 0, _live_game(), team_data, show_win_prob=True
    )
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_many_ks(white_image, team_data):
    """More Ks than fit in panel — strip truncates gracefully."""
    from image_box import draw_wide_box
    game = _live_game(home_pitcher_ks=['K'] * 20)
    result = draw_wide_box(white_image, 0, 0, game, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_events_with_inning_triangles(white_image, team_data):
    """Events strip with '^'/'v' half-inning markers renders up/down triangles."""
    from image_box import draw_wide_box
    game = _live_game(
        half_inning_plays=['K', '6-3', 'v', '1B', 'F9', '^', 'Kl', '2B'],
    )
    result = draw_wide_box(white_image, 0, 0, game, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_seven_events_with_markers(white_image, team_data):
    """Half-inning markers ('^'/'v') must not count against the 7-event budget:
    9 events with 2 interspersed markers should still surface 7 real events."""
    from image_box import draw_wide_box
    game = _live_game(
        half_inning_plays=['K', '6-3', '1B', 'v', 'F9', 'L7', '2B', '^', 'Kl',
                           '5-3', 'BB'],
    )
    result = draw_wide_box(white_image, 0, 0, game, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_events_leading_triangle_trimmed(white_image, team_data):
    """A leading boundary marker left after trimming doesn't crash or render alone."""
    from image_box import draw_wide_box
    # Long events force trimming; a triangle may end up at the front and must be dropped.
    game = _live_game(
        half_inning_plays=['3RBI 2B', 'v', 'RBI 1B', 'Grand Slam', '^', 'Kl',
                           '4-3', 'F7', 'v', '2B', '1B', '^', 'K', 'L3'],
    )
    result = draw_wide_box(white_image, 0, 0, game, team_data)
    assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# 2. _find_wide_games logic
# ---------------------------------------------------------------------------

def _make_game_list(states_and_innings):
    """Build a minimal game list. Each entry: (detailed_state, inning, half)."""
    games = []
    for i, (state, inning, half) in enumerate(states_and_innings):
        games.append({
            'game_pk': 1000 + i,
            'detailed_state': state,
            'current_inning': inning,
            'inningState': half,
            'num_of_outs': 0,
            'game_datetime': f'2026-06-20T2{i}:00:00Z',
        })
    return games


def test_find_wide_games_fewer_than_15():
    from image_grid import _find_wide_games
    games = _make_game_list([
        ('Final', 9, 'End'),
        ('In Progress', 5, 'Top'),
        ('Scheduled', 0, ''),
    ])
    result = _find_wide_games(games, {}, {})
    assert result == {1}


def test_find_wide_games_all_in_progress():
    from image_grid import _find_wide_games
    games = _make_game_list([('In Progress', i + 1, 'Top') for i in range(5)])
    result = _find_wide_games(games, {}, {})
    assert result == {0, 1, 2, 3, 4}


def test_find_wide_games_caps_to_spare_slots():
    """13 games with 4 in progress → only 2 spare slots, so 2 widest games chosen."""
    from image_grid import _find_wide_games
    states = [
        ('In Progress', 3, 'Top'),    # 0
        ('In Progress', 8, 'Top'),    # 1  ← farthest
        ('In Progress', 6, 'Bottom'), # 2  ← second farthest
        ('In Progress', 2, 'Top'),    # 3
    ] + [('Final', 9, 'End')] * 9     # pad to 13
    games = _make_game_list(states)
    result = _find_wide_games(games, {}, {})
    assert result == {1, 2}


def test_find_wide_games_14_games_one_wide():
    """14 games → 1 spare slot → exactly 1 wide cell."""
    from image_grid import _find_wide_games
    states = [('In Progress', 7, 'Top'), ('In Progress', 4, 'Top')] + \
             [('Final', 9, 'End')] * 12
    games = _make_game_list(states)
    result = _find_wide_games(games, {}, {})
    assert result == {0}


def test_find_wide_games_15_plus_no_force():
    from image_grid import _find_wide_games
    games = _make_game_list([('In Progress', 7, 'Top')] * 15)
    result = _find_wide_games(games, {'wide_cell_always': False}, {})
    assert result == set()


def test_find_wide_games_15_plus_force_picks_farthest():
    from image_grid import _find_wide_games
    games = _make_game_list([
        ('In Progress', 5, 'Top'),   # 0
        ('In Progress', 8, 'Top'),   # 1  ← highest inning
        ('Final',       9, 'End'),   # 2  not in progress
        ('In Progress', 7, 'Bottom'),# 3
    ] + [('Final', 9, 'End')] * 11)  # pad to 15
    result = _find_wide_games(games, {'wide_cell_always': True}, {})
    assert result == {1}


def test_find_wide_games_tiebreak_by_half():
    from image_grid import _find_wide_games
    games = _make_game_list([
        ('In Progress', 7, 'Top'),    # 0
        ('In Progress', 7, 'Bottom'), # 1  same inning, Bottom wins
    ] + [('Final', 9, 'End')] * 13)
    result = _find_wide_games(games, {'wide_cell_always': True}, {})
    assert result == {1}


def test_find_wide_games_tiebreak_by_outs():
    from image_grid import _find_wide_games
    games = [
        {'game_pk': 0, 'detailed_state': 'In Progress', 'current_inning': 7,
         'inningState': 'Top', 'num_of_outs': 0, 'game_datetime': 'A'},
        {'game_pk': 1, 'detailed_state': 'In Progress', 'current_inning': 7,
         'inningState': 'Top', 'num_of_outs': 2, 'game_datetime': 'B'},
    ] + [{'game_pk': i + 2, 'detailed_state': 'Final', 'current_inning': 9,
          'inningState': 'End', 'num_of_outs': 3, 'game_datetime': 'C'} for i in range(13)]
    result = _find_wide_games(games, {'wide_cell_always': True}, {})
    assert result == {1}


def test_find_wide_games_15_plus_force_no_live_game():
    """15+ games, force=True, but no in-progress games → empty set."""
    from image_grid import _find_wide_games
    games = _make_game_list([('Final', 9, 'End')] * 15)
    result = _find_wide_games(games, {'wide_cell_always': True}, {})
    assert result == set()


def test_find_wide_games_challenge_state_stays_wide():
    """A game under review ('Player challenge'/'Manager challenge') is still live
    and must keep its wide tile rather than handing the slot to another game."""
    from image_grid import _find_wide_games
    games = _make_game_list([
        ('Player challenge', 7, 'Top'),   # 0 — under review, still live
        ('Manager challenge', 5, 'Bottom'),  # 1 — under review, still live
    ] + [('Final', 9, 'End')] * 11)       # pad to 13 → 2 spare slots
    result = _find_wide_games(games, {}, {})
    assert result == {0, 1}


def test_find_wide_games_challenge_does_not_displace_in_progress():
    """With only 1 spare slot, an In Progress game farther along still wins, but a
    challenge game counts toward the live pool (not silently dropped)."""
    from image_grid import _find_wide_games
    games = _make_game_list([
        ('In Progress', 9, 'Bottom'),     # 0 — farthest along
        ('Player challenge', 2, 'Top'),   # 1 — live but earlier
    ] + [('Final', 9, 'End')] * 12)       # pad to 14 → 1 spare slot
    result = _find_wide_games(games, {}, {})
    assert result == {0}


# ---------------------------------------------------------------------------
# 3b. wide_cell_featured — featured team gets the wide tile when live
# ---------------------------------------------------------------------------

_FEAT_TD = {'team_abbreviation': {'147': 'NYY', '111': 'BOS', '119': 'LAD', '137': 'SF'}}


def _g(pk, away_id, home_id, state, inning=5, half='Top'):
    return {
        'game_pk': pk, 'away_team_id': away_id, 'home_team_id': home_id,
        'detailed_state': state, 'current_inning': inning, 'inningState': half,
        'num_of_outs': 1, 'game_datetime': f'2026-06-20T{20 + pk % 4}:00:00Z',
    }


def test_featured_live_gets_wide_at_15_games():
    """wide_cell_featured: the featured team's live game is the wide cell even at 15 games."""
    from image_grid import _find_wide_games
    games = [_g(i, 119, 137, 'Final', 9, 'End') for i in range(14)]
    games.append(_g(99, 111, 147, 'In Progress', 3, 'Top'))   # index 14 — NYY (home) live
    result = _find_wide_games(games, {'wide_cell_featured': True, 'primary': 'NYY'}, _FEAT_TD)
    assert result == {14}


def test_featured_not_live_falls_back_to_latest():
    """wide_cell_featured: when the featured game is not live, the farthest-along game wins."""
    from image_grid import _find_wide_games
    games = [_g(i, 119, 137, 'Final', 9, 'End') for i in range(13)]
    games.append(_g(50, 111, 133, 'In Progress', 4, 'Top'))   # index 13 — non-featured, earlier
    games.append(_g(51, 137, 133, 'In Progress', 8, 'Top'))   # index 14 — non-featured, farther
    # NYY isn't playing live → fall back to the game farthest along (index 14).
    result = _find_wide_games(games, {'wide_cell_featured': True, 'primary': 'NYY'}, _FEAT_TD)
    assert result == {14}


def test_featured_preferred_over_farther_game_when_capping():
    """wide_cell_featured beats raw progress: the featured game wins the lone slot
    even though another live game is farther along."""
    from image_grid import _find_wide_games
    games = [_g(i, 119, 137, 'Final', 9, 'End') for i in range(12)]
    games.append(_g(60, 111, 147, 'In Progress', 2, 'Top'))   # index 12 — NYY, earlier
    games.append(_g(61, 137, 133, 'In Progress', 8, 'Top'))   # index 13 — non-featured, farther
    # 14 games → 1 spare slot. Featured preference picks NYY (12) over the farther game.
    result = _find_wide_games(games, {'wide_cell_featured': True, 'primary': 'NYY'}, _FEAT_TD)
    assert result == {12}


def test_featured_default_off_preserves_old_behavior():
    """Without wide_cell_featured, 15 games with a live featured game shows no wide cell
    (identical to the prior behavior)."""
    from image_grid import _find_wide_games
    games = [_g(i, 119, 137, 'Final', 9, 'End') for i in range(14)]
    games.append(_g(99, 111, 147, 'In Progress', 3, 'Top'))   # NYY live
    assert _find_wide_games(games, {'primary': 'NYY'}, _FEAT_TD) == set()
    assert _find_wide_games(games, {'wide_cell_featured': False, 'primary': 'NYY'}, _FEAT_TD) == set()


# ---------------------------------------------------------------------------
# 3. End-to-end grid with wide cells
# ---------------------------------------------------------------------------

@needs_pil
def test_grid_with_one_wide_game(white_image, team_data):
    from image_grid import draw_out_of_town_score_board
    games = [_live_game(game_pk=1)] + [
        _base_game(game_pk=i + 2) for i in range(5)
    ]
    result = draw_out_of_town_score_board(white_image, games, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_grid_15_games_no_wide(white_image, team_data):
    """15 games, wide_cell_always off → all normal cells, no crash."""
    from image_grid import draw_out_of_town_score_board
    games = [_base_game(game_pk=i) for i in range(14)] + [_live_game(game_pk=99)]
    result = draw_out_of_town_score_board(white_image, games, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_grid_15_games_wide_cell_always(white_image, team_data):
    """15 games, wide_cell_always on → one wide cell rendered, no crash."""
    from image_grid import draw_out_of_town_score_board
    games = [_base_game(game_pk=i) for i in range(14)] + [_live_game(game_pk=99)]
    with patch('image_grid.load_yaml_file', return_value={
        'wide_cell_always': True,
        'scoreboard_live_details': False,
    }):
        result = draw_out_of_town_score_board(white_image, games, team_data)
    assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# 4. compute_grid_layout geometry + partial-refresh region alignment
# ---------------------------------------------------------------------------

@needs_pil
def test_compute_grid_layout_two_wide_at_col0():
    """Two in-progress games on a 13-game slate both land at col 0 (reordered)."""
    from image_grid import compute_grid_layout
    # In-progress games at indices 0 and 3; reorder pushes the second to col 0
    # of row 1 instead of leaving it stranded at col 4.
    games = _make_game_list(
        [('In Progress', 7, 'Top'),                       # 0
         ('Final', 9, 'End'), ('Final', 9, 'End'),         # 1, 2
         ('In Progress', 5, 'Top')]                        # 3
        + [('Final', 9, 'End')] * 9                         # pad to 13
    )
    game_list, slots = compute_grid_layout(games, {}, {})
    wide_slots = [(gl.get('game_pk'), s) for gl, s in zip(game_list, slots)
                  if s[0] == 'wide']
    assert len(wide_slots) == 2
    # Both wide tiles begin at column 0 so each can span rightward.
    assert all(s[1] == 0 for _, s in wide_slots)


@needs_pil
def test_changed_region_covers_full_wide_tile():
    """Partial-refresh region for a wide game must span the full 2-cell tile."""
    from image_grid import compute_grid_layout
    games = _make_game_list(
        [('In Progress', 7, 'Top')] + [('Final', 9, 'End')] * 5
    )
    game_list, slots = compute_grid_layout(games, {}, {})
    x_start = 32
    # Replicate the region math in generate_image.draw_score_board.
    for game, (slot_type, gx, gy) in zip(game_list, slots):
        if slot_type != 'wide':
            continue
        rx = (gx * 150 + x_start) // 8 * 8
        rw = 304
        tile_left = gx * 150 + x_start
        tile_right = tile_left + 285  # draw_wide_box TOTAL_W
        assert rx <= tile_left
        assert rx + rw >= tile_right
        break
    else:
        pytest.fail('expected a wide slot in the layout')
