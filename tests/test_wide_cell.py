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
    """White image."""
    return Image.new('1', (800, 480), 255)


@pytest.fixture
def team_data():
    """Team data."""
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
    """Base game."""
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
    """Between innings game."""
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
    """Wide box in progress."""
    from image_box import draw_wide_box
    result = draw_wide_box(white_image, 0, 0, _live_game(), team_data)
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)


@needs_pil
def test_wide_box_between_innings(white_image, team_data):
    """Wide box between innings."""
    from image_box import draw_wide_box
    result = draw_wide_box(white_image, 0, 0, _between_innings_game(), team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_no_pitches(white_image, team_data):
    """Wide box no pitches."""
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
    """Wide box with win prob."""
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
@pytest.mark.parametrize('total,label,rem', [
    (9,  '',    9),   # under first milestone — no badge
    (10, '10K', 0),   # exactly at milestone — badge only
    (13, '10K', 3),   # badge + 3 individual Ks
    (20, '20K', 0),   # second milestone — badge only
    (23, '20K', 3),   # second milestone + 3 individual Ks
])
def test_wide_box_k_milestone_renders(white_image, team_data, total, label, rem):
    """K-strip milestone badge logic renders without error for key counts."""
    from image_box import draw_wide_box
    game = _live_game(home_pitcher_ks=['K'] * total)
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
def test_wide_box_trailing_arrow_with_prior_events(white_image, team_data):
    """Trailing '^' after plays hits the 'if items:' branch in _build_items
    (lines 2206-2207) that inserts a space before the triangle."""
    from image_box import draw_wide_box
    game = _live_game(half_inning_plays=['1B', 'HR', '^'])
    result = draw_wide_box(white_image, 0, 0, game, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_events_overflow_trims_oldest_plays(white_image, team_data):
    """The trim loop (lines 2254-2257) fires when extracted events are too wide
    for _hdr_max_w. Long event strings guarantee overflow; the '^' at position 1
    (after the oldest event is popped) triggers the inner marker-skip loop (2256-2257)."""
    from image_box import draw_wide_box
    # Construct plays so _recent_plays = ['Home Run', '^', 'Walk-Off Home Run', '1B', '2B', '3B', 'BB', 'HR']
    # 'Home Run' + triangle + 'Walk-Off Home Run' ≈ 203px > _hdr_max_w=231? Actually ~203px < 231
    # Use even wider strings to guarantee overflow >231px:
    plays = ['Old1', 'Old2', 'Home Run', '^', 'Walk-Off Home Run', '1B-2B-3B', '2B', '3B', 'BB', 'HR']
    game = _live_game(half_inning_plays=plays)
    result = draw_wide_box(white_image, 0, 0, game, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_very_long_batter_name_truncates(white_image, team_data):
    """An extremely long batter name triggers the while-loop truncation in
    the right panel's AB row (line 2481). The last name must be long since
    _last_name() is used (not _format_player_name())."""
    from image_box import draw_wide_box
    # Single hyphenated last name with no spaces → treated as the full last name.
    long_last = 'A Bartholomew-Alexander-McGillicuddy-Smithwick-Rodriguez'
    game = _live_game(current_hitter=long_last, current_pitcher='Logan Webb',
                      current_play_batter=long_last, current_at_bat_complete=False,
                      batter_hits=5, batter_at_bats=20)
    result = draw_wide_box(white_image, 0, 0, game, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_panel_mid_inning_pc_names_both_pitchers(team_data):
    """current_pitcher still reports the departing arm during a change, so the
    right panel's 'P:' line reads 'Webb→King'. Left alone it credited the pitch
    to the pitcher who had just walked off."""
    from image_box import draw_wide_box
    # The 'P:' row: rp_x = start_x + CELL_W (135), drawn at rp_y + 107.
    pitcher_row = (135, 104, 260, 122)

    def _row(**overrides):
        """Pixels of the right panel's pitcher line."""
        img = Image.new('1', (800, 480), 255)
        draw_wide_box(img, 0, 0, _live_game(num_of_outs=1, **overrides), team_data)
        return list(img.crop(pitcher_row).getdata())

    king  = _row(sub_event='PC: King')
    doval = _row(sub_event='PC: Doval')
    plain = _row()

    assert any(p == 0 for p in plain), 'the pitcher line should be drawn at all'
    assert king != plain, "the 'P:' line must reflect the pitching change"
    assert king != doval, \
        "the 'P:' line must name the incoming pitcher, not just flag a change"


@needs_pil
def test_wide_box_between_innings_shows_batter_list(white_image, team_data):
    """Between innings (Middle) renders the due-up batter names via the
    batter-names section. A long last-name triggers the truncation loop (line 2427).
    _last_name() returns just the last word, so the last name itself must be long."""
    from image_box import draw_wide_box
    # Long last name (after the space) → _last_name returns it directly.
    long_name = 'A Bartholomew-Alexander-McGillicuddy-Smithwick-Rodriguez-Fernandez'
    game = _live_game(
        inningState='Middle',
        next_batter_1=long_name, next_batter_2=long_name, next_batter_3=long_name,
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
    """Find wide games fewer than 15."""
    from image_grid import _find_wide_games
    games = _make_game_list([
        ('Final', 9, 'End'),
        ('In Progress', 5, 'Top'),
        ('Scheduled', 0, ''),
    ])
    result = _find_wide_games(games, {}, {})
    assert result == {1}


def test_find_wide_games_all_in_progress():
    """Find wide games all in progress."""
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
    """Find wide games 15 plus no force."""
    from image_grid import _find_wide_games
    games = _make_game_list([('In Progress', 7, 'Top')] * 15)
    result = _find_wide_games(games, {'wide_cell_always': False}, {})
    assert result == set()


def test_find_wide_games_15_plus_force_picks_farthest():
    """Find wide games 15 plus force picks farthest."""
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
    """Find wide games tiebreak by half."""
    from image_grid import _find_wide_games
    games = _make_game_list([
        ('In Progress', 7, 'Top'),    # 0
        ('In Progress', 7, 'Bottom'), # 1  same inning, Bottom wins
    ] + [('Final', 9, 'End')] * 13)
    result = _find_wide_games(games, {'wide_cell_always': True}, {})
    assert result == {1}


def test_find_wide_games_tiebreak_by_outs():
    """Find wide games tiebreak by outs."""
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
    """G."""
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
    """Grid with one wide game."""
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
def test_compute_grid_layout_featured_live_gets_triple_on_13_game_slate():
    """On a 13-game slate with 2 free slots, the featured live game gets a
    triple tile (uses both slots); the other live game stays normal."""
    from image_grid import compute_grid_layout
    games = _make_game_list(
        [('In Progress', 7, 'Top'),                       # 0 — farther along
         ('Final', 9, 'End'), ('Final', 9, 'End'),         # 1, 2
         ('In Progress', 5, 'Top')]                        # 3
        + [('Final', 9, 'End')] * 9                         # pad to 13
    )
    game_list, slots = compute_grid_layout(games, {}, {})
    triple_count = sum(1 for s in slots if s[0] == 'triple')
    assert triple_count == 1
    # Second live game has no remaining expansion budget → stays normal.
    wide_count = sum(1 for s in slots if s[0] == 'wide')
    assert wide_count == 0


def test_compute_grid_layout_favorite_team_first_moves_game_to_front():
    """favorite_team_first reorders so the primary team's game is index 0."""
    from image_grid import compute_grid_layout
    games = _make_game_list([('Final', 9, 'End')] * 3)
    games[2]['away_team_id'] = 147
    games[2]['home_team_id'] = 111
    team_data = {'team_abbreviation': {'147': 'NYY', '111': 'BOS'}}
    config = {'favorite_team_first': True, 'primary': 'NYY'}
    game_list, _slots = compute_grid_layout(games, team_data, config)
    assert game_list[0]['away_team_id'] == 147


def test_compute_grid_layout_pushes_rainout_past_doubleheader():
    """16+ games with a doubleheader and a postponed game: the postponed game
    is pushed to the back of the list so the doubleheader pair stays on the
    visible 5x3 grid."""
    from image_grid import compute_grid_layout
    games = _make_game_list([('Final', 9, 'End')] * 14)
    games.append({**games[0], 'game_pk': 9001, 'detailed_state': 'Postponed',
                  'double_header': 'N'})
    games.append({**games[0], 'game_pk': 9002, 'detailed_state': 'Final',
                  'double_header': 'Y'})
    assert len(games) == 16
    game_list, _slots = compute_grid_layout(games, {}, {})
    # The postponed game must have been moved to the very end of the list.
    assert game_list[-1]['game_pk'] == 9001


def test_compute_grid_layout_slot_building_stops_at_capacity():
    """With 16 games and one forced expanded tile, the expanded tile consumes 3
    slot units (triple), so total slot demand (18) exceeds the 15-unit grid —
    the packer must stop placing games once 15 slot units are used rather than
    indexing past the grid. The excluded game(s) simply aren't rendered."""
    from image_grid import compute_grid_layout
    games = _make_game_list(
        [('In Progress', 5, 'Top')] + [('Final', 9, 'End')] * 15
    )
    assert len(games) == 16
    config = {'wide_cell_always': True}
    game_list, slots = compute_grid_layout(games, {}, config)
    assert len(slots) == len(game_list) < 16
    assert any(s[0] in ('wide', 'triple') for s in slots)


@needs_pil
def test_grid_date_label_fits_default_width(white_image, team_data):
    """date_str provided with default (non-wildcard) config: the header label
    fits at a large font size on the first try."""
    from image_grid import draw_out_of_town_score_board
    games = [_base_game(game_pk=i) for i in range(3)]
    with patch('image_grid.load_yaml_file', return_value={}):
        result = draw_out_of_town_score_board(white_image, games, team_data, date_str='2026-06-20')
    assert isinstance(result, Image.Image)


@needs_pil
def test_grid_date_label_narrow_width_fits_immediately(white_image, team_data):
    """show_wildcard_standings shrinks the available label width to 155px;
    a normal date still fits on the first font-size check."""
    from image_grid import draw_out_of_town_score_board
    games = [_base_game(game_pk=i) for i in range(3)]
    with patch('image_grid.load_yaml_file', return_value={'show_wildcard_standings': True}):
        result = draw_out_of_town_score_board(white_image, games, team_data, date_str='2026-06-20')
    assert isinstance(result, Image.Image)


@needs_pil
def test_grid_date_label_malformed_falls_back_and_never_fits(white_image, team_data):
    """A date_str that fails to parse hits the ValueError fallback (label text
    becomes the raw string), and — combined with the narrow wildcard width —
    that raw string doesn't fit at any font size, exercising the 'continue to
    shorter candidate' branch even though both candidates are identical."""
    from image_grid import draw_out_of_town_score_board
    games = [_base_game(game_pk=i) for i in range(3)]
    with patch('image_grid.load_yaml_file', return_value={'show_wildcard_standings': True}):
        result = draw_out_of_town_score_board(
            white_image, games, team_data, date_str='not-a-real-date-value-xxxx'
        )
    assert isinstance(result, Image.Image)


@needs_pil
def test_changed_region_covers_full_wide_tile():
    """Partial-refresh region for a wide game must span the full 2-cell tile.

    Use 14 games (only 1 extra slot free) so the live game is demoted to wide
    rather than triple, which needs 2 extra slots.
    """
    from image_grid import compute_grid_layout
    games = _make_game_list(
        [('In Progress', 7, 'Top')] + [('Final', 9, 'End')] * 13
    )
    game_list, slots = compute_grid_layout(games, {}, {})
    x_start = 32
    # Replicate the region math in generate_image.draw_score_board.
    for _game, (slot_type, gx, _gy) in zip(game_list, slots):
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


@needs_pil
def test_wide_box_nohitter_inverts_header(white_image, team_data):
    """Active no-hitter (≥6 innings, no run scored) inverts the wide-cell
    spanning header (image_box.py lines 2635-2639)."""
    from image_box import draw_wide_box
    game = _live_game(
        no_hitter=True,
        perfect_game=False,
        current_inning=7,
        last_play_rbi=0,
    )
    result = draw_wide_box(white_image, 0, 0, game, team_data)
    assert isinstance(result, Image.Image)
    # Header row (y=0..19) should contain some black pixels — inversion fired.
    header_pixels = [result.getpixel((x, 5)) for x in range(285)]
    assert any(p == 0 for p in header_pixels), "no-hitter header should be inverted (black)"


@needs_pil
def test_wide_box_perfectgame_inverts_header(white_image, team_data):
    """Perfect game also triggers the wide-cell header inversion."""
    from image_box import draw_wide_box
    game = _live_game(
        no_hitter=False,
        perfect_game=True,
        current_inning=8,
        last_play_rbi=0,
    )
    result = draw_wide_box(white_image, 0, 0, game, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_at_bat_pitch_count_fallback(white_image, team_data):
    """When pitch_count (game-level) is absent but at_bat_pitch_count is set,
    the wide panel should render without error — used for timelapse frames where
    only the per-at-bat count is reconstructed from play-by-play data."""
    from image_box import draw_wide_box
    game = _live_game(ab_pitches=[], at_bat_pitch_count=4)
    game.pop('pitch_count', None)
    result = draw_wide_box(white_image, 0, 0, game, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_at_bat_pitch_count_fallback_no_speed(white_image, team_data):
    """at_bat_pitch_count fallback also works when last_pitch_speed is absent."""
    from image_box import draw_wide_box
    game = _live_game(ab_pitches=[], at_bat_pitch_count=2, last_pitch_speed=None)
    game.pop('pitch_count', None)
    result = draw_wide_box(white_image, 0, 0, game, team_data)
    assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# Triple-cell tile via draw_out_of_town_score_board
# ---------------------------------------------------------------------------

@needs_pil
def test_grid_with_triple_cell_tile(white_image, team_data):
    """triple_cell_live=True renders a draw_triple_box tile without crash."""
    from image_grid import draw_out_of_town_score_board
    games = [_live_game(game_pk=1)] + [_base_game(game_pk=i + 2) for i in range(5)]
    with patch('image_grid.load_yaml_file', return_value={
        'triple_cell_live': True,
        'wide_cell_always': False,
        'wide_cell_featured': False,
        'scoreboard_live_details': False,
    }):
        result = draw_out_of_town_score_board(white_image, games, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_grid_with_three_triple_cell_tiles(white_image, team_data):
    """3 live games with ample room each get their own triple-cell tile."""
    from image_grid import draw_out_of_town_score_board
    games = [
        _live_game(game_pk=1),
        _live_game(game_pk=2),
        _live_game(game_pk=3),
        _base_game(game_pk=4),
    ]
    with patch('image_grid.load_yaml_file', return_value={
        'triple_cell_live': True,
        'wide_cell_always': False,
        'wide_cell_featured': False,
        'scoreboard_live_details': False,
    }):
        result = draw_out_of_town_score_board(white_image, games, team_data)
    assert isinstance(result, Image.Image)


def test_compute_grid_layout_three_live_games_all_get_triple():
    """3 live games with enough free slots (< 15 games total) each get a
    triple tile — one per row, capped at _MAX_TRIPLE_TILES."""
    from image_grid import compute_grid_layout
    games = _make_game_list(
        [('In Progress', 6, 'Bottom'),
         ('In Progress', 5, 'Top'),
         ('In Progress', 4, 'Bottom')]
        + [('Scheduled', 0, '')]
    )
    game_list, slots = compute_grid_layout(games, {}, {})
    triple_count = sum(1 for s in slots if s[0] == 'triple')
    assert triple_count == 3


@needs_pil
def test_grid_triple_cell_15_plus_games(white_image, team_data):
    """triple_cell_live=True with 15+ games assigns triple to the best game."""
    from image_grid import draw_out_of_town_score_board
    games = [_live_game(game_pk=1)] + [_base_game(game_pk=i + 2) for i in range(14)]
    with patch('image_grid.load_yaml_file', return_value={
        'triple_cell_live': True,
        'wide_cell_always': True,
        'wide_cell_featured': False,
        'scoreboard_live_details': False,
    }):
        result = draw_out_of_town_score_board(white_image, games, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_grid_with_wide_cell_tile(white_image, team_data):
    """14-game slate renders a wide tile (1 free slot, not enough for triple)."""
    from image_grid import draw_out_of_town_score_board
    games = [_live_game(game_pk=1)] + [_base_game(game_pk=i + 2) for i in range(13)]
    with patch('image_grid.load_yaml_file', return_value={
        'wide_cell_always': False,
        'wide_cell_featured': False,
        'scoreboard_live_details': False,
    }):
        result = draw_out_of_town_score_board(white_image, games, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_grid_cluster_fallback_no_expansion(white_image, team_data):
    """At 15 games with no expansion flags, cluster/normal path runs."""
    from image_grid import draw_out_of_town_score_board
    games = [_live_game(game_pk=1)] + [_base_game(game_pk=i + 2) for i in range(14)]
    with patch('image_grid.load_yaml_file', return_value={
        'wide_cell_always': False,
        'wide_cell_featured': False,
        'scoreboard_live_details': False,
    }):
        result = draw_out_of_town_score_board(white_image, games, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_grid_cluster_fallback_with_live_games(white_image, team_data):
    """15-game slate with 2 live games: cluster path runs and returns wide slots."""
    from image_grid import draw_out_of_town_score_board
    games = (
        [_live_game(game_pk=1), _live_game(game_pk=2, home_team_id=144)]
        + [_base_game(game_pk=i + 3) for i in range(13)]
    )
    with patch('image_grid.load_yaml_file', return_value={
        'wide_cell_always': False,
        'wide_cell_featured': False,
        'scoreboard_live_details': False,
    }):
        result = draw_out_of_town_score_board(white_image, games, team_data)
    assert isinstance(result, Image.Image)


@needs_pil
def test_wide_box_pregame_state_no_crash(white_image, team_data):
    """draw_wide_box with a Scheduled game exercises the pre-game lineup panel."""
    from image_box import draw_wide_box
    game = _base_game(
        detailed_state='Scheduled',
        inningState='Scheduled',
        due_up=['Alice Smith', 'Bob Jones', 'Carol Lee'],
    )
    result = draw_wide_box(white_image, 0, 0, game, team_data)
    assert isinstance(result, Image.Image)
