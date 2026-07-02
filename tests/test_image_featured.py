"""Smoke tests for src/image_featured.py — the featured-team fullscreen views.

Covers:
  1. _find_featured_game: priority/fallback selection logic
  2. draw_live_fullscreen_game: full 800x480 live-game layout, many field combos
  3. draw_featured_game_fullscreen: live-delegation, non-live cell scaling,
     wildcard header / standings sidebar plumbing, date label

Follows the pattern established in tests/test_wide_cell.py (local fixture-dict
builders, needs_pil guard, isinstance(result, Image.Image) smoke assertions)
and the safety lessons from tests/test_golden_scoreboard.py:
  - use_team_logos is always False — pic/logos/*.png are gitignored, so
    enabling logos would trigger a real ESPN CDN download.
  - image_box.set_historical_mode(True) wraps every call that can reach a
    Final/Postponed game through draw_box (via draw_featured_game_fullscreen),
    since that code otherwise fetches tomorrow's real MLB schedule over the
    network once a Final game's linescore window "expires" under the real
    wall clock.
  - image_featured.load_json_file (standings.json) is always mocked so tests
    never depend on this machine's local data/standings.json contents.
"""
from unittest.mock import patch

import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEAM_DATA = {
    'team_abbreviation': {
        '147': 'NYY', '111': 'BOS', '119': 'LAD', '137': 'SF',
    }
}

CONFIG = {
    'use_team_logos': False,
    'small_logo_x_offset': 2,
    'scoreboard_win_probability': False,
    'show_wildcard_standings': False,
    'show_standings_sidebar': False,
    'league_mode': 'mlb',
}


@pytest.fixture(autouse=True)
def _historical_mode_guard():
    """Every test in this module either renders a live game (no wall-clock
    dependency) or a non-live game via draw_featured_game_fullscreen, which
    can reach draw_box's Final-game / tomorrow-preview logic. Wrapping every
    test in historical_mode(True) is a no-op for the live path and a
    required network guard for the non-live path."""
    import image_box
    image_box.set_historical_mode(True)
    yield
    image_box.set_historical_mode(False)


def _live_game(**overrides):
    """In-progress featured game with the full field set used by
    draw_live_fullscreen_game (header, R/H/E, bases, outs, pitcher/batter,
    win% bar, ABS/replay challenges)."""
    g = {
        'game_pk': 9001,
        'away_team_id': 147,
        'home_team_id': 111,
        'detailed_state': 'In Progress',
        'inningState': 'Top',
        'current_inning': 5,
        'currentInningOrdinal': '5th',
        'num_of_outs': 1,
        'away_runs': 2, 'home_runs': 1,
        'away_hits': 5, 'home_hits': 4,
        'away_errors': 0, 'home_errors': 0,
        'away_team_is_winner': False, 'home_team_is_winner': False,
        'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None,
        'runner_first_number': None, 'runner_second_number': None, 'runner_third_number': None,
        'balls': 1, 'strikes': 2, 'strike_calls': ['C', 'B', 'S'],
        'last_pitch_speed': 93.4, 'last_pitch_type': 'FB', 'pitch_count': 64,
        'current_pitcher': 'Logan Webb', 'current_hitter': 'Mookie Betts',
        'current_play_batter': 'Mookie Betts', 'current_at_bat_complete': False,
        'due_up': 'Freddie Freeman', 'in_hole': 'Will Smith',
        'next_batter_1': None, 'next_batter_2': None, 'next_batter_3': None, 'next_pitcher': None,
        'save_situation': False,
        'away_win_probability': 42.0, 'home_win_probability': 58.0,
        'away_inning_runs': [0, 1, 0, 0, 0], 'home_inning_runs': [1, 0, 0, 0, 0],
        'last_play': None, 'last_review_result': None, 'last_play_description': None,
        'last_play_rbi': 0, 'sub_event': None,
        'away_challenges_remaining': None, 'home_challenges_remaining': None,
        'away_replay_remaining': None, 'home_replay_remaining': None, 'abs_challenge_max': 2,
        'game_date': '2026-06-20',
    }
    g.update(overrides)
    return g


def _scheduled_game(**overrides):
    """Pre-game featured game for the non-live draw_featured_game_fullscreen path."""
    g = {
        'game_pk': 7001,
        'away_team_id': 147,
        'home_team_id': 111,
        'detailed_state': 'Scheduled',
        'away_runs': 0, 'home_runs': 0,
        'away_hits': 0, 'home_hits': 0, 'away_errors': 0, 'home_errors': 0,
        'away_team_is_winner': False, 'home_team_is_winner': False,
        'current_inning': None, 'inningState': '',
        'away_inning_runs': [], 'home_inning_runs': [],
        'away_team_record_wins': 40, 'away_team_record_losses': 30,
        'home_team_record_wins': 45, 'home_team_record_losses': 25,
        'num_of_outs': None, 'balls': None, 'strikes': None,
        'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None,
        'game_start': '7:05 PM', 'game_datetime': '2026-06-20T23:05:00Z',
        'game_end_time_utc': None,
        'away_probable': 'R. Ray', 'home_probable': 'L. Webb',
        'venue': 'Fenway Park', 'game_date': '2026-06-20',
        'series_result': '', 'series_game_number': 1, 'series_total_games': 3,
    }
    g.update(overrides)
    return g


def _final_game(**overrides):
    g = _scheduled_game(
        detailed_state='Final', away_runs=3, home_runs=5,
        away_hits=8, home_hits=10, away_errors=0, home_errors=1,
        away_team_is_winner=False, home_team_is_winner=True,
        current_inning=9, inningState='End',
        away_inning_runs=[0, 1, 0, 0, 0, 2, 0, 0, 0], home_inning_runs=[1, 0, 2, 0, 0, 0, 1, 0, 1],
        # Ancient — guarantees "outside the linescore window" under the real
        # wall clock; historical_mode(True) (set by the autouse fixture above)
        # still prevents the tomorrow-preview network call regardless.
        game_end_time_utc='2020-01-01T02:45:00Z',
        winner_name='Logan Webb', loser_name='R. Ray',
    )
    g.update(overrides)
    return g


# ---------------------------------------------------------------------------
# 1. _find_featured_game
# ---------------------------------------------------------------------------

def _g(pk, away, home, state):
    return {'game_pk': pk, 'away_team_id': away, 'home_team_id': home, 'detailed_state': state}


def test_find_featured_game_scheduled_priority():
    from image_featured import _find_featured_game
    games = [_g(1, 119, 137, 'Final'), _g(2, 147, 111, 'Scheduled')]
    result = _find_featured_game(games, TEAM_DATA, 'NYY')
    assert result['game_pk'] == 2


def test_find_featured_game_in_progress_priority_over_final():
    from image_featured import _find_featured_game
    games = [_g(1, 147, 111, 'Final'), _g(2, 147, 111, 'In Progress')]
    result = _find_featured_game(games, TEAM_DATA, 'NYY')
    assert result['game_pk'] == 2


def test_find_featured_game_final_returns_last_matching():
    from image_featured import _find_featured_game
    games = [_g(1, 147, 111, 'Final'), _g(2, 147, 111, 'Completed Early: Rain')]
    result = _find_featured_game(games, TEAM_DATA, 'NYY')
    assert result['game_pk'] == 2


def test_find_featured_game_primary_not_playing_falls_back_to_live():
    from image_featured import _find_featured_game
    games = [_g(1, 119, 137, 'Final'), _g(2, 133, 144, 'In Progress')]
    result = _find_featured_game(games, TEAM_DATA, 'NYY')
    assert result['game_pk'] == 2


def test_find_featured_game_primary_not_playing_no_live_falls_back_to_first():
    from image_featured import _find_featured_game
    games = [_g(1, 119, 137, 'Final'), _g(2, 133, 144, 'Final')]
    result = _find_featured_game(games, TEAM_DATA, 'NYY')
    assert result['game_pk'] == 1


def test_find_featured_game_empty_list_returns_none():
    from image_featured import _find_featured_game
    assert _find_featured_game([], TEAM_DATA, 'NYY') is None


def test_find_featured_game_challenge_state_falls_back_to_last_primary_game():
    """A primary-team game under review isn't 'In Progress' by exact match,
    isn't Scheduled/Final either, so it falls through to the final fallback
    (last primary game) rather than being skipped."""
    from image_featured import _find_featured_game
    games = [_g(1, 147, 111, 'Player challenge')]
    result = _find_featured_game(games, TEAM_DATA, 'NYY')
    assert result['game_pk'] == 1


# ---------------------------------------------------------------------------
# 2. draw_live_fullscreen_game
# ---------------------------------------------------------------------------

@needs_pil
def test_live_fullscreen_basic():
    from image_featured import draw_live_fullscreen_game
    img = draw_live_fullscreen_game(_live_game(), TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)
    assert img.size == (800, 480)
    assert img.mode == '1'


@needs_pil
def test_live_fullscreen_bases_loaded():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(
        runner_on_first='Mookie Betts', runner_on_second='Freddie Freeman',
        runner_on_third='Will Smith',
        runner_first_number=50, runner_second_number=5, runner_third_number=16,
    )
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_bases_empty():
    from image_featured import draw_live_fullscreen_game
    img = draw_live_fullscreen_game(_live_game(), TEAM_DATA, CONFIG)  # defaults: all None
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_challenges_present():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(
        away_challenges_remaining=1, home_challenges_remaining=0,
        away_replay_remaining=1, home_replay_remaining=0, abs_challenge_max=2,
    )
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_challenges_none():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(
        away_challenges_remaining=None, home_challenges_remaining=None,
        away_replay_remaining=None, home_replay_remaining=None,
    )
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_win_probability_as_fraction():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(away_win_probability=0.42, home_win_probability=0.58)
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_win_probability_as_percentage():
    """away+home > 1.5 → treated as already-percentage (0-100) and divided by 100."""
    from image_featured import draw_live_fullscreen_game
    game = _live_game(away_win_probability=42.0, home_win_probability=58.0)
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_win_probability_missing():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(away_win_probability=None, home_win_probability=58.0)
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_win_probability_invalid_value_does_not_crash():
    """Non-numeric probability values hit the except (ValueError, TypeError) branch."""
    from image_featured import draw_live_fullscreen_game
    game = _live_game(away_win_probability='N/A', home_win_probability=58.0)
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_sub_event_pitching_change():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(inningState='Middle', sub_event='PC:New Pitcher', next_pitcher='Camilo Doval')
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_player_challenge_normalizes_sub_event():
    """detailed_state='Player challenge' is normalized to sub_event='ABS CHAL'
    and detailed_state='In Progress' before rendering."""
    from image_featured import draw_live_fullscreen_game
    game = _live_game(detailed_state='Player challenge')
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_manager_challenge_normalizes_sub_event():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(detailed_state='Manager challenge')
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_between_innings_with_due_up_batters():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(
        inningState='Middle',
        next_batter_1='Freddie Freeman', next_batter_2='Will Smith', next_batter_3='Max Muncy',
    )
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_three_outs_lag_shows_mid_label():
    """num_of_outs>=3 while inningState is still Top/Bottom (API hasn't
    flipped yet) suppresses the arrow and forces the between-innings layout."""
    from image_featured import draw_live_fullscreen_game
    game = _live_game(inningState='Top', num_of_outs=3)
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_extra_innings_sliding_linescore_window():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(
        inningState='Middle', current_inning=11,
        away_inning_runs=[0] * 11, home_inning_runs=[0] * 11,
    )
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_save_situation_badge():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(save_situation=True)
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_strikeout_looking_draws_backwards_k():
    """last_play containing 'strikeout looking' abbreviates to 'Kl', which
    triggers the mirrored-K glyph rendering branch in the header."""
    from image_featured import draw_live_fullscreen_game
    game = _live_game(last_play='Player strikeout looking')
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_flyout_resolves_fielder_position():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(last_play='Flyout', last_play_description='fly ball to right fielder')
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@pytest.mark.parametrize('last_play,rbi', [
    ('Home Run', 2),
    ('Single', 1),
    ('Double', 2),
])
@needs_pil
def test_live_fullscreen_rbi_event_labels(last_play, rbi):
    from image_featured import draw_live_fullscreen_game
    game = _live_game(last_play=last_play, last_play_rbi=rbi)
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_run_scored_inverts_header():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(last_play='Home Run', last_play_rbi=1)
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_long_pitcher_name_shrinks_font():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(
        inningState='Middle',
        next_pitcher='Christopher Alexander Bartholomew Doval-Rodriguez',
    )
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_long_batter_names_shrink_font():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(
        inningState='Middle',
        next_batter_1='Christopher Alexander Bartholomew',
        next_batter_2='Frederick Charles Freeman The Third',
        next_batter_3='William Dean Smith',
    )
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_at_bat_complete_uses_due_up():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(current_at_bat_complete=True, due_up='Freddie Freeman', in_hole='Will Smith')
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_on_deck_equal_to_batter_is_suppressed():
    from image_featured import draw_live_fullscreen_game
    game = _live_game(
        current_at_bat_complete=True, due_up='Same Guy',
        next_batter_1='Same Guy', in_hole='Same Guy',
    )
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_config_none_loads_real_yaml_mocked():
    from image_featured import draw_live_fullscreen_game
    with patch('image_featured.load_yaml_file', return_value=CONFIG) as mock_load:
        img = draw_live_fullscreen_game(_live_game(), TEAM_DATA, None)
    assert isinstance(img, Image.Image)
    mock_load.assert_called_once_with('config.yaml')


# ---------------------------------------------------------------------------
# 3. draw_featured_game_fullscreen
# ---------------------------------------------------------------------------

@needs_pil
def test_featured_fullscreen_delegates_to_live_for_in_progress():
    from image_featured import draw_featured_game_fullscreen
    stub = Image.new('1', (800, 480), 255)
    with patch('image_featured.draw_live_fullscreen_game', return_value=stub) as mock_live:
        game = _scheduled_game(detailed_state='In Progress')
        img = draw_featured_game_fullscreen(game, TEAM_DATA, CONFIG)
    mock_live.assert_called_once_with(game, TEAM_DATA, CONFIG)
    assert img is stub


@pytest.mark.parametrize('state', ['Player challenge', 'Manager challenge'])
@needs_pil
def test_featured_fullscreen_delegates_to_live_for_challenge_states(state):
    from image_featured import draw_featured_game_fullscreen
    stub = Image.new('1', (800, 480), 255)
    with patch('image_featured.draw_live_fullscreen_game', return_value=stub) as mock_live:
        game = _scheduled_game(detailed_state=state)
        img = draw_featured_game_fullscreen(game, TEAM_DATA, CONFIG)
    mock_live.assert_called_once()
    assert img is stub


@needs_pil
def test_featured_fullscreen_scheduled_game_no_standings():
    from image_featured import draw_featured_game_fullscreen
    with patch('image_featured.load_json_file', return_value={}):
        img = draw_featured_game_fullscreen(_scheduled_game(), TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)
    assert img.size == (800, 480)
    assert img.mode == '1'


@needs_pil
def test_featured_fullscreen_final_game_no_standings():
    """Final game exercises draw_box's Final-game linescore path; wrapped in
    historical_mode(True) by the module's autouse fixture to avoid the
    real-network tomorrow's-schedule fetch."""
    from image_featured import draw_featured_game_fullscreen
    with patch('image_featured.load_json_file', return_value={}):
        img = draw_featured_game_fullscreen(_final_game(), TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


_STANDINGS_DATA = {
    'standings': {
        '1': [{'team_id': 147, 'streak': 'W2', 'last_ten_wins': 6, 'last_ten_losses': 4}],
    }
}


@needs_pil
def test_featured_fullscreen_wildcard_header_calls_image_standings():
    """show_wildcard_standings=True must call into image_standings' derive +
    draw functions — mocked here since image_standings is a separate
    coverage target; we're only verifying image_featured calls it correctly."""
    from image_featured import draw_featured_game_fullscreen
    wc_config = dict(CONFIG, show_wildcard_standings=True)
    with patch('image_featured.load_json_file', return_value=_STANDINGS_DATA), \
         patch('image_featured.derive_wildcard_from_standings', return_value={'x': 1}) as mock_derive, \
         patch('image_featured.draw_wildcard_header', side_effect=lambda canvas, wc: canvas) as mock_hdr:
        img = draw_featured_game_fullscreen(_scheduled_game(), TEAM_DATA, wc_config)
    mock_derive.assert_called_once_with(_STANDINGS_DATA)
    mock_hdr.assert_called_once()
    assert isinstance(img, Image.Image)


@needs_pil
def test_featured_fullscreen_standings_sidebar_calls_left_and_right():
    from image_featured import draw_featured_game_fullscreen
    sb_config = dict(CONFIG, show_standings_sidebar=True)
    with patch('image_featured.load_json_file', return_value=_STANDINGS_DATA), \
         patch('image_featured.draw_standings_sidebar_fullscreen',
               side_effect=lambda canvas, *a, **k: canvas) as mock_sidebar:
        img = draw_featured_game_fullscreen(_scheduled_game(), TEAM_DATA, sb_config)
    assert mock_sidebar.call_count == 2
    sides = [call.kwargs.get('side') for call in mock_sidebar.call_args_list]
    assert sides == ['left', 'right']
    assert isinstance(img, Image.Image)


@needs_pil
def test_featured_fullscreen_wildcard_and_sidebar_both_off():
    from image_featured import draw_featured_game_fullscreen
    with patch('image_featured.load_json_file', return_value=_STANDINGS_DATA), \
         patch('image_featured.derive_wildcard_from_standings') as mock_derive, \
         patch('image_featured.draw_standings_sidebar_fullscreen') as mock_sidebar:
        img = draw_featured_game_fullscreen(_scheduled_game(), TEAM_DATA, CONFIG)
    mock_derive.assert_not_called()
    mock_sidebar.assert_not_called()
    assert isinstance(img, Image.Image)


@needs_pil
def test_featured_fullscreen_aaa_league_mode_skips_wildcard_header():
    """league_mode='aaa' skips wildcard standings even when the flag is on
    (wildcard races don't apply to AAA)."""
    from image_featured import draw_featured_game_fullscreen
    aaa_config = dict(CONFIG, show_wildcard_standings=True, league_mode='aaa')
    with patch('image_featured.load_json_file', return_value=_STANDINGS_DATA), \
         patch('image_featured.derive_wildcard_from_standings') as mock_derive:
        img = draw_featured_game_fullscreen(_scheduled_game(), TEAM_DATA, aaa_config)
    mock_derive.assert_not_called()
    assert isinstance(img, Image.Image)


@needs_pil
def test_featured_fullscreen_missing_standings_data_skips_without_crash():
    """Flags on but no usable standings.json content → both overlays skipped,
    no crash."""
    from image_featured import draw_featured_game_fullscreen
    wc_config = dict(CONFIG, show_wildcard_standings=True, show_standings_sidebar=True)
    with patch('image_featured.load_json_file', return_value={}):
        img = draw_featured_game_fullscreen(_scheduled_game(), TEAM_DATA, wc_config)
    assert isinstance(img, Image.Image)


@needs_pil
def test_featured_fullscreen_date_label_full_format():
    from image_featured import draw_featured_game_fullscreen
    with patch('image_featured.load_json_file', return_value={}):
        img = draw_featured_game_fullscreen(_scheduled_game(game_date='2026-06-20'), TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_featured_fullscreen_date_label_malformed_falls_back_to_raw_string():
    from image_featured import draw_featured_game_fullscreen
    with patch('image_featured.load_json_file', return_value={}):
        img = draw_featured_game_fullscreen(_scheduled_game(game_date='not-a-date'), TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_featured_fullscreen_no_date_skips_date_label():
    from image_featured import draw_featured_game_fullscreen
    with patch('image_featured.load_json_file', return_value={}):
        img = draw_featured_game_fullscreen(_scheduled_game(game_date=None), TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_featured_fullscreen_date_label_narrow_with_wildcard_standings():
    """With show_wildcard_standings on, the date label's max width shrinks to
    151px, exercising the short-format / smaller-font fallback."""
    from image_featured import draw_featured_game_fullscreen
    wc_config = dict(CONFIG, show_wildcard_standings=True)
    with patch('image_featured.load_json_file', return_value=_STANDINGS_DATA), \
         patch('image_featured.derive_wildcard_from_standings', return_value={'x': 1}), \
         patch('image_featured.draw_wildcard_header', side_effect=lambda canvas, wc: canvas):
        img = draw_featured_game_fullscreen(
            _scheduled_game(game_date='2026-06-20'), TEAM_DATA, wc_config,
        )
    assert isinstance(img, Image.Image)


@needs_pil
def test_featured_fullscreen_config_none_loads_real_yaml_mocked():
    from image_featured import draw_featured_game_fullscreen
    with patch('image_featured.load_yaml_file', return_value=CONFIG) as mock_load, \
         patch('image_featured.load_json_file', return_value={}):
        img = draw_featured_game_fullscreen(_scheduled_game(), TEAM_DATA, None)
    assert isinstance(img, Image.Image)
    mock_load.assert_called_once_with('config.yaml')


# ---------------------------------------------------------------------------
# Additional branch coverage
# ---------------------------------------------------------------------------

@needs_pil
def test_live_fullscreen_bottom_half_draws_down_triangle():
    """inningState='Bottom' selects the ▼ triangle branch (line 217)."""
    from image_featured import draw_live_fullscreen_game
    game = _live_game(inningState='Bottom', current_inning=3)
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_swinging_strike_circle_outline_branch():
    """Strike call 'S' (swinging) draws an outline-only circle (lines 547-548)."""
    from image_featured import draw_live_fullscreen_game
    game = _live_game(strikes=2, strike_calls=['S', 'F'])
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_foul_strike_circle_outline_branch():
    """Strike call 'F' (foul) also draws the outline-only circle."""
    from image_featured import draw_live_fullscreen_game
    game = _live_game(strikes=1, strike_calls=['F'])
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_replay_remaining_filled_rect():
    """replay_remaining > 0 draws a filled rectangle (line 314)."""
    from image_featured import draw_live_fullscreen_game
    game = _live_game(away_replay_remaining=1, home_replay_remaining=1)
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_replay_remaining_outline_rect():
    """replay_remaining == 0 draws an outline rectangle (line 316)."""
    from image_featured import draw_live_fullscreen_game
    game = _live_game(away_replay_remaining=0, home_replay_remaining=0)
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_with_logos_mocked():
    """use_logos=True with a mocked logo exercises the logo-paste branch
    inside _draw_team_row (lines 277-283)."""
    from image_featured import draw_live_fullscreen_game
    logo_cfg = dict(CONFIG, use_team_logos=True)
    fake_logo = Image.new('1', (32, 32), 255)
    with patch('image_featured._logo_small', return_value=fake_logo):
        img = draw_live_fullscreen_game(_live_game(), TEAM_DATA, logo_cfg)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_win_prob_logos_same_side_separation():
    """Win probabilities close together force the logo separation path
    (lines 646-654): both logos pushed to avoid overlap."""
    from image_featured import draw_live_fullscreen_game
    logo_cfg = dict(CONFIG, use_team_logos=True, scoreboard_win_probability=True)
    fake_logo = Image.new('1', (28, 28), 255)
    # away=51%, home=49% → logos almost at center → overlap separation triggered
    game = _live_game(away_win_probability=0.51, home_win_probability=0.49)
    with patch('image_featured._logo_small', return_value=fake_logo):
        img = draw_live_fullscreen_game(game, TEAM_DATA, logo_cfg)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_win_prob_with_logos_different_sides():
    """Win probabilities well apart exercises the logo paste path (lines 657-663)."""
    from image_featured import draw_live_fullscreen_game
    logo_cfg = dict(CONFIG, use_team_logos=True, scoreboard_win_probability=True)
    fake_logo = Image.new('1', (28, 28), 255)
    game = _live_game(away_win_probability=0.15, home_win_probability=0.85)
    with patch('image_featured._logo_small', return_value=fake_logo):
        img = draw_live_fullscreen_game(game, TEAM_DATA, logo_cfg)
    assert isinstance(img, Image.Image)


@needs_pil
def test_featured_fullscreen_winner_ghost_logo_on_final():
    """Final game with home winner and use_logos=True exercises the
    winner-ghost-logo branch in draw_featured_game_fullscreen (lines 737-753)."""
    from image_featured import draw_featured_game_fullscreen
    logo_cfg = dict(CONFIG, use_team_logos=True)
    fake_logo = Image.new('1', (110, 110), 255)
    with patch('image_featured.load_json_file', return_value={}), \
         patch('image_featured._logo_ghost', return_value=fake_logo), \
         patch('image_featured._logo_small', return_value=Image.new('1', (20, 20), 255)):
        img = draw_featured_game_fullscreen(_final_game(), TEAM_DATA, logo_cfg)
    assert isinstance(img, Image.Image)


@needs_pil
def test_featured_fullscreen_winner_ghost_logo_away_winner():
    """Away winner also reaches the ghost-logo branch."""
    from image_featured import draw_featured_game_fullscreen
    logo_cfg = dict(CONFIG, use_team_logos=True)
    fake_logo = Image.new('1', (110, 110), 255)
    game = _final_game(away_team_is_winner=True, home_team_is_winner=False)
    with patch('image_featured.load_json_file', return_value={}), \
         patch('image_featured._logo_ghost', return_value=fake_logo), \
         patch('image_featured._logo_small', return_value=Image.new('1', (20, 20), 255)):
        img = draw_featured_game_fullscreen(game, TEAM_DATA, logo_cfg)
    assert isinstance(img, Image.Image)


@needs_pil
def test_featured_fullscreen_playoff_bracket_header_branch():
    """show_playoff_bracket=True exercises the playoff-bracket header path."""
    from image_featured import draw_featured_game_fullscreen
    bracket_cfg = dict(CONFIG, show_playoff_bracket=True, league_mode='mlb')
    bracket_data = {'series': [{'round': 'WS', 'away_abbr': 'NYY', 'home_abbr': 'BOS',
                                'away_wins': 2, 'home_wins': 1, 'complete': False}]}
    with patch('image_featured.load_json_file', return_value=bracket_data), \
         patch('image_featured.draw_playoff_bracket_header',
               side_effect=lambda canvas, b: canvas) as mock_bracket:
        img = draw_featured_game_fullscreen(_scheduled_game(), TEAM_DATA, bracket_cfg)
    mock_bracket.assert_called_once()
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_kl_in_header_right_text():
    """last_play resulting in 'Kl' in the right-side header text exercises the
    Kl-rendering branch when the right text fits on screen."""
    from image_featured import draw_live_fullscreen_game
    game = _live_game(last_play='strikeout looking', last_play_description=None)
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_kl_with_rbi_prefix_non_empty_segment():
    """'RBI Kl' splits into ['RBI ', ''] — the first segment is non-empty, so
    draw.text fires for the pre-Kl text (image_featured.py lines 249-250)."""
    from image_featured import draw_live_fullscreen_game
    game = _live_game(last_play='strikeout looking', last_play_rbi=1,
                      last_play_description=None)
    img = draw_live_fullscreen_game(game, TEAM_DATA, CONFIG)
    assert isinstance(img, Image.Image)


@needs_pil
def test_live_fullscreen_win_prob_home_slightly_higher_overlap():
    """home > away by a tiny margin puts home logo to the right of away logo
    but close enough to trigger the MIN_SEP separation in the else branch
    (image_featured.py lines 651-654)."""
    from image_featured import draw_live_fullscreen_game
    wp_cfg = dict(CONFIG, scoreboard_win_probability=True, use_team_logos=True)
    fake_logo = Image.new('1', (20, 20), 255)
    game = _live_game(away_win_probability=49.0, home_win_probability=51.0)
    with patch('image_featured._logo_small', return_value=fake_logo):
        img = draw_live_fullscreen_game(game, TEAM_DATA, wp_cfg)
    assert isinstance(img, Image.Image)
