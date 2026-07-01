"""Tests for generate_image.orchestrate_score_board — the main app orchestrator.

Covers cache-diff short-circuiting, score-change detection, the Final-game
linescore-window-expiry force-refresh path, FEATURED_TEAM_FULLSCREEN dispatch,
and partial-refresh region plumbing for wide (2-cell) tiles.

All file I/O is mocked via patch('generate_image.load_json_file', ...) /
patch('generate_image.save_off_results', ...) so tests never touch real
data/*.json files. Config is always pinned explicitly (never None) with
use_team_logos: False, and image_grid.load_yaml_file / image_box.load_yaml_file
are patched too whenever the real grid-rendering path runs, so the real
config/config.yaml (which has use_team_logos: True) can never leak in and
trigger a real ESPN CDN download. image_box.set_historical_mode(True) wraps
every call that renders a Final-state game through the real draw_box, to
neutralize the wall-clock-dependent "tomorrow's game preview" logic (which
otherwise fetches the real MLB schedule over the network).
"""
import os
import copy
from unittest.mock import patch, MagicMock

import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")


# ---------------------------------------------------------------------------
# Fixed config / team data — independent of config/config.yaml
# ---------------------------------------------------------------------------

FIXED_CONFIG = {
    'timezone': 'America/Chicago',
    'use_team_logos': False,
    'small_logo_x_offset': 2,
    'wide_cell_always': False,
    'wide_cell_featured': False,
    'scoreboard_live_details': True,
    'final_linescore_minutes': 60,
    'show_wildcard_standings': False,
    'show_standings_sidebar': False,
    'primary': '',
    'league_mode': 'mlb',
    'dark_mode': False,
    'scoreboard_win_probability': False,
    'favorite_team_first': False,
}

TEAM_DATA = {
    'team_abbreviation': {
        '119': 'LAD', '137': 'SF', '133': 'OAK', '144': 'ATL',
        '147': 'NYY', '111': 'BOS',
    }
}


def _base_game(**overrides):
    g = {
        'game_pk': 1001,
        'away_team_id': 119,
        'home_team_id': 137,
        'detailed_state': 'Final',
        'away_runs': 3,
        'home_runs': 5,
        'away_hits': 8,
        'home_hits': 10,
        'away_errors': 0,
        'home_errors': 1,
        'away_team_is_winner': False,
        'home_team_is_winner': True,
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
        # Ancient end time — guarantees "outside the linescore window" under the
        # real wall clock without needing to mock datetime.now.
        'game_end_time_utc': '2020-01-01T02:45:00Z',
        'venue': 'Oracle Park',
        'series_result': '',
    }
    g.update(overrides)
    return g


def _live_game(**overrides):
    g = _base_game(
        detailed_state='In Progress',
        current_inning=7,
        inningState='Top',
        num_of_outs=1,
        balls=2,
        strikes=1,
        strike_calls=['C', 'S'],
        runner_on_first='Mookie Betts',
        current_pitcher='Logan Webb',
        current_hitter='Mookie Betts',
        current_play_batter='Mookie Betts',
        pitch_count=82,
        last_pitch_type='FB',
        last_pitch_speed=93.4,
        current_at_bat_complete=False,
        ab_pitches=[],
        half_inning_plays=[],
        home_pitcher_ks=[],
        away_pitcher_ks=[],
        away_win_probability=42.0,
        home_win_probability=58.0,
    )
    g.pop('game_end_time_utc', None)
    g.update(overrides)
    return g


def _fake_loader(overrides):
    """Build a side_effect for generate_image.load_json_file keyed by filename.

    Any filename not present in `overrides` returns {} (matching util's
    default-empty-dict behavior for a missing file).
    """
    def _load(file_name, *args, **kwargs):
        return overrides.get(file_name, {})
    return _load


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv('FEATURED_TEAM_FULLSCREEN', raising=False)
    yield


# ---------------------------------------------------------------------------
# bypass_cache=True — always renders, skips the cache-diff check entirely
# ---------------------------------------------------------------------------

@needs_pil
def test_bypass_cache_always_renders():
    """bypass_cache=True skips load_json_file('old_scoreboard_state.json')
    entirely, so it must never return None even with no prior state."""
    import generate_image
    import image_box

    games = [_base_game(game_pk=1, detailed_state='Scheduled', away_runs=0, home_runs=0)]

    with patch('generate_image.load_json_file') as mock_load, \
         patch('generate_image.save_off_results') as mock_save, \
         patch('image_grid.load_yaml_file', return_value=FIXED_CONFIG), \
         patch('image_box.load_yaml_file', return_value=FIXED_CONFIG):
        image_box.set_historical_mode(True)
        try:
            result = generate_image.orchestrate_score_board(
                games, TEAM_DATA, date_str='2026-06-20', bypass_cache=True, config=FIXED_CONFIG,
            )
        finally:
            image_box.set_historical_mode(False)

    assert result is not None
    img, regions = result
    assert isinstance(img, Image.Image)
    assert img.size == (800, 480)
    assert img.mode == '1'
    assert isinstance(regions, list)
    # bypass_cache skips the old-state load/save path entirely.
    mock_load.assert_not_called()
    mock_save.assert_not_called()


@needs_pil
def test_bypass_cache_true_with_many_games_collapses_to_full_refresh():
    """bypass_cache=True treats every game as 'changed' (no prior state to
    diff against); with 10+ games this collapses to a single full-canvas
    region rather than one region per cell."""
    import generate_image
    import image_box

    games = [_base_game(game_pk=i, detailed_state='Scheduled') for i in range(12)]

    with patch('generate_image.load_json_file', return_value={}), \
         patch('generate_image.save_off_results'), \
         patch('image_grid.load_yaml_file', return_value=FIXED_CONFIG), \
         patch('image_box.load_yaml_file', return_value=FIXED_CONFIG):
        image_box.set_historical_mode(True)
        try:
            result = generate_image.orchestrate_score_board(
                games, TEAM_DATA, date_str='2026-06-20', bypass_cache=True, config=FIXED_CONFIG,
            )
        finally:
            image_box.set_historical_mode(False)

    assert result is not None
    _, regions = result
    assert regions == [(0, 0, 800, 480)]


# ---------------------------------------------------------------------------
# bypass_cache=False — cache-diff check
# ---------------------------------------------------------------------------

@needs_pil
def test_identical_old_and_new_data_returns_none():
    """Identical old vs. new game data (and no linescore-window change) →
    'images the same' → None."""
    import generate_image

    games = [_base_game(game_pk=1, detailed_state='Scheduled', away_runs=0, home_runs=0,
                         game_end_time_utc=None)]
    old_games = copy.deepcopy(games)

    with patch('generate_image.load_json_file',
               side_effect=_fake_loader({'old_scoreboard_state.json': old_games})), \
         patch('generate_image.save_off_results') as mock_save:
        result = generate_image.orchestrate_score_board(
            games, TEAM_DATA, date_str='2026-06-20', bypass_cache=False, config=FIXED_CONFIG,
        )

    assert result is None
    # The unchanged-image check still persists the new state for next time.
    mock_save.assert_any_call(games, 'old_scoreboard_state')


@needs_pil
def test_different_data_renders_and_returns_result():
    """A non-score field changing (e.g. venue) is different enough to render."""
    import generate_image
    import image_box

    old_games = [_base_game(game_pk=1, detailed_state='Scheduled', away_runs=0, home_runs=0,
                             game_end_time_utc=None, venue='Old Park')]
    new_games = [_base_game(game_pk=1, detailed_state='Warmup', away_runs=0, home_runs=0,
                             game_end_time_utc=None, venue='New Park')]

    with patch('generate_image.load_json_file',
               side_effect=_fake_loader({'old_scoreboard_state.json': old_games})), \
         patch('generate_image.save_off_results'), \
         patch('image_grid.load_yaml_file', return_value=FIXED_CONFIG), \
         patch('image_box.load_yaml_file', return_value=FIXED_CONFIG):
        image_box.set_historical_mode(True)
        try:
            result = generate_image.orchestrate_score_board(
                new_games, TEAM_DATA, date_str='2026-06-20', bypass_cache=False, config=FIXED_CONFIG,
            )
        finally:
            image_box.set_historical_mode(False)

    assert result is not None
    img, regions = result
    assert isinstance(img, Image.Image)
    assert regions == [(32, 30, 152, 150)]


@needs_pil
def test_score_change_detected_and_persisted():
    """A pure score change (same detailed_state, different runs) is detected
    and persisted to score_alerts.json via save_off_results."""
    import generate_image
    import image_box

    old_games = [_base_game(game_pk=3001, detailed_state='In Progress', away_runs=1, home_runs=0,
                             current_inning=3, inningState='Top', game_end_time_utc=None,
                             ab_pitches=[], half_inning_plays=[], home_pitcher_ks=[], away_pitcher_ks=[])]
    new_games = [_base_game(game_pk=3001, detailed_state='In Progress', away_runs=2, home_runs=0,
                             current_inning=3, inningState='Top', game_end_time_utc=None,
                             ab_pitches=[], half_inning_plays=[], home_pitcher_ks=[], away_pitcher_ks=[])]

    old_scores = {'3001': {'away_runs': 1, 'home_runs': 0}}
    mock_save = MagicMock()

    with patch('generate_image.load_json_file', side_effect=_fake_loader({
            'old_scoreboard_state.json': old_games,
            'score_alerts.json': old_scores,
        })), \
         patch('generate_image.save_off_results', mock_save), \
         patch('image_grid.load_yaml_file', return_value=FIXED_CONFIG), \
         patch('image_box.load_yaml_file', return_value=FIXED_CONFIG):
        image_box.set_historical_mode(True)
        try:
            result = generate_image.orchestrate_score_board(
                new_games, TEAM_DATA, date_str='2026-06-20', bypass_cache=False, config=FIXED_CONFIG,
            )
        finally:
            image_box.set_historical_mode(False)

    assert result is not None
    mock_save.assert_any_call({'3001': {'away_runs': 2, 'home_runs': 0}}, 'score_alerts')


@needs_pil
def test_linescore_window_expiry_forces_rerender_even_if_nothing_else_changed():
    """A Final game whose stored old_linescore_window_state.json says True
    (in-window) but whose game_end_time_utc is now ancient enough that the
    real wall clock says it's out of the window → forced re-render, even
    though old and new game_state_data are byte-for-byte identical.

    Note: this exercises generate_image's OWN window check, which uses the
    real datetime.now(pytz.utc) directly (no historical_mode gate in that
    module) — hence the deliberately ancient game_end_time_utc rather than
    a mocked clock. image_box.set_historical_mode(True) still wraps the
    actual grid render below, to keep image_box's separate (also real-clock)
    tomorrow-preview logic from hitting the network.
    """
    import generate_image
    import image_box

    games = [_base_game(game_pk=2001)]  # detailed_state='Final', ancient game_end_time_utc

    with patch('generate_image.load_json_file', side_effect=_fake_loader({
            'old_scoreboard_state.json': copy.deepcopy(games),
            'old_linescore_window_state.json': {'2001': True},
            'game_final_times.json': {'2001': 1000.0},
        })), \
         patch('generate_image.save_off_results'), \
         patch('image_grid.load_yaml_file', return_value=FIXED_CONFIG), \
         patch('image_box.load_yaml_file', return_value=FIXED_CONFIG):
        image_box.set_historical_mode(True)
        try:
            result = generate_image.orchestrate_score_board(
                games, TEAM_DATA, date_str='2026-06-20', bypass_cache=False, config=FIXED_CONFIG,
            )
        finally:
            image_box.set_historical_mode(False)

    assert result is not None, "linescore-window expiry must force a re-render"
    _, regions = result
    assert regions == [(32, 30, 152, 150)]


@needs_pil
def test_linescore_window_still_in_window_does_not_force_rerender():
    """Sanity check for the above: identical data AND the window is still
    considered 'in window' (recent game_end_time_utc) → returns None."""
    import generate_image
    from datetime import datetime, timedelta
    import pytz

    recent = (datetime.now(pytz.utc) - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S')
    games = [_base_game(game_pk=2002, game_end_time_utc=recent)]

    with patch('generate_image.load_json_file', side_effect=_fake_loader({
            'old_scoreboard_state.json': copy.deepcopy(games),
            'old_linescore_window_state.json': {'2002': True},
            'game_final_times.json': {'2002': 1000.0},
        })), \
         patch('generate_image.save_off_results'):
        result = generate_image.orchestrate_score_board(
            games, TEAM_DATA, date_str='2026-06-20', bypass_cache=False, config=FIXED_CONFIG,
        )

    assert result is None


# ---------------------------------------------------------------------------
# FEATURED_TEAM_FULLSCREEN dispatch
# ---------------------------------------------------------------------------

@needs_pil
def test_featured_fullscreen_dispatches_to_draw_featured_game_fullscreen(monkeypatch):
    """With the env var set and the primary team's game present, orchestrate
    must dispatch to draw_featured_game_fullscreen rather than the grid."""
    import generate_image

    monkeypatch.setenv('FEATURED_TEAM_FULLSCREEN', 'true')
    config = dict(FIXED_CONFIG, primary='NYY')
    game = {'game_pk': 5001, 'away_team_id': 147, 'home_team_id': 111, 'detailed_state': 'In Progress'}
    games = [game]
    stub_img = Image.new('1', (800, 480), 255)

    with patch('generate_image.draw_featured_game_fullscreen', return_value=stub_img) as mock_feat, \
         patch('generate_image.draw_out_of_town_score_board') as mock_grid:
        result = generate_image.orchestrate_score_board(
            games, TEAM_DATA, date_str='2026-06-20', bypass_cache=True, config=config,
        )

    mock_feat.assert_called_once_with(game, TEAM_DATA, config)
    mock_grid.assert_not_called()
    assert result is not None
    img, regions = result
    assert isinstance(img, Image.Image)
    assert img.size == (800, 480)
    assert img.mode == '1'
    # bypass_cache=True short-circuits the fine-grained fullscreen zone logic.
    assert regions == []


@needs_pil
def test_featured_fullscreen_falls_back_to_grid_when_no_games(monkeypatch):
    """With the env var set but an empty game list, _find_featured_game
    returns None, so orchestrate must fall back to the normal grid path."""
    import generate_image

    monkeypatch.setenv('FEATURED_TEAM_FULLSCREEN', 'true')
    config = dict(FIXED_CONFIG, primary='NYY')
    stub_img = Image.new('1', (800, 480), 255)

    with patch('generate_image.draw_featured_game_fullscreen', return_value=stub_img) as mock_feat, \
         patch('generate_image.draw_out_of_town_score_board', return_value=stub_img) as mock_grid:
        result = generate_image.orchestrate_score_board(
            [], TEAM_DATA, date_str='2026-06-20', bypass_cache=True, config=config,
        )

    mock_feat.assert_not_called()
    mock_grid.assert_called_once()
    assert result is not None
    img, regions = result
    assert isinstance(img, Image.Image)
    assert regions == []


@needs_pil
def test_no_featured_fullscreen_env_uses_grid_path():
    """Without the env var set at all, orchestrate always uses the grid path
    regardless of a configured primary team."""
    import generate_image

    assert os.environ.get('FEATURED_TEAM_FULLSCREEN') is None
    config = dict(FIXED_CONFIG, primary='NYY')
    games = [{'game_pk': 5002, 'away_team_id': 147, 'home_team_id': 111, 'detailed_state': 'In Progress'}]
    stub_img = Image.new('1', (800, 480), 255)

    with patch('generate_image.draw_featured_game_fullscreen') as mock_feat, \
         patch('generate_image.draw_out_of_town_score_board', return_value=stub_img) as mock_grid:
        result = generate_image.orchestrate_score_board(
            games, TEAM_DATA, date_str='2026-06-20', bypass_cache=True, config=config,
        )

    mock_feat.assert_not_called()
    mock_grid.assert_called_once()
    assert result is not None


# ---------------------------------------------------------------------------
# Partial-refresh region plumbing — wide (2-cell) vs normal tiles
# ---------------------------------------------------------------------------

@needs_pil
def test_changed_region_for_wide_game_covers_full_wide_tile():
    """A changed wide (2-cell) game must produce a region with width 304
    (covering the whole tile), not the normal 152px single-cell width —
    verifying orchestrate_score_board plumbs compute_grid_layout's slot math
    through to its returned changed_regions, matching
    tests/test_wide_cell.py::test_changed_region_covers_full_wide_tile."""
    import generate_image
    import image_box

    old_games = [_live_game(game_pk=1, balls=1)] + [_base_game(game_pk=i + 2) for i in range(5)]
    new_games = [_live_game(game_pk=1, balls=2)] + [_base_game(game_pk=i + 2) for i in range(5)]

    with patch('generate_image.load_json_file',
               side_effect=_fake_loader({'old_scoreboard_state.json': old_games})), \
         patch('generate_image.save_off_results'), \
         patch('image_grid.load_yaml_file', return_value=FIXED_CONFIG), \
         patch('image_box.load_yaml_file', return_value=FIXED_CONFIG):
        image_box.set_historical_mode(True)
        try:
            result = generate_image.orchestrate_score_board(
                new_games, TEAM_DATA, date_str='2026-06-20', bypass_cache=False, config=FIXED_CONFIG,
            )
        finally:
            image_box.set_historical_mode(False)

    assert result is not None
    _, regions = result
    assert regions == [(32, 30, 304, 150)]


@needs_pil
def test_changed_region_for_normal_game_is_single_cell_width():
    """A changed normal (1-cell) game produces a 152px-wide region, not 304."""
    import generate_image
    import image_box

    old_games = [_base_game(game_pk=1, away_runs=1)]
    new_games = [_base_game(game_pk=1, away_runs=9)]

    with patch('generate_image.load_json_file',
               side_effect=_fake_loader({'old_scoreboard_state.json': old_games})), \
         patch('generate_image.save_off_results'), \
         patch('image_grid.load_yaml_file', return_value=FIXED_CONFIG), \
         patch('image_box.load_yaml_file', return_value=FIXED_CONFIG):
        image_box.set_historical_mode(True)
        try:
            result = generate_image.orchestrate_score_board(
                new_games, TEAM_DATA, date_str='2026-06-20', bypass_cache=False, config=FIXED_CONFIG,
            )
        finally:
            image_box.set_historical_mode(False)

    assert result is not None
    _, regions = result
    assert regions == [(32, 30, 152, 150)]


@needs_pil
def test_config_none_loads_real_yaml_mocked():
    """config=None triggers load_yaml_file('config.yaml') — mocked so the
    real config/config.yaml (use_team_logos: True) never leaks in."""
    import generate_image

    stub_img = Image.new('1', (800, 480), 255)
    games = [{'game_pk': 5}]

    with patch('generate_image.load_yaml_file', return_value=dict(FIXED_CONFIG)) as mock_yaml, \
         patch('generate_image.draw_out_of_town_score_board', return_value=stub_img) as mock_grid:
        result = generate_image.orchestrate_score_board(
            games, TEAM_DATA, date_str='2026-06-20', bypass_cache=True, config=None,
        )

    mock_yaml.assert_called_once_with('config.yaml')
    mock_grid.assert_called_once()
    assert result is not None


@needs_pil
def test_malformed_game_end_time_falls_back_to_final_times_cache():
    """An unparsable game_end_time_utc hits the except branch and falls back
    to the game_final_times.json timestamp for the in-window calculation."""
    import generate_image

    stub_img = Image.new('1', (800, 480), 255)
    game = {'game_pk': 2001, 'detailed_state': 'Final', 'game_end_time_utc': 'not-a-valid-datetime'}

    with patch('generate_image.load_json_file', side_effect=_fake_loader({
            'old_scoreboard_state.json': [dict(game)],
            'old_linescore_window_state.json': {'2001': True},
            'game_final_times.json': {'2001': 1000.0},  # ancient → outside window
        })), \
         patch('generate_image.save_off_results'), \
         patch('generate_image.draw_out_of_town_score_board', return_value=stub_img):
        result = generate_image.orchestrate_score_board(
            [game], TEAM_DATA, date_str='2026-06-20', bypass_cache=False, config=FIXED_CONFIG,
        )

    assert result is not None


@needs_pil
def test_games_without_game_pk_are_skipped_in_refresh_and_score_tracking():
    """Games with no/empty game_pk hit the early `continue` in both the
    refreshed-game-ids loop and the score-change-detection loop."""
    import generate_image

    stub_img = Image.new('1', (800, 480), 255)
    games = [{'detailed_state': 'Scheduled'}]  # no game_pk at all

    with patch('generate_image.load_json_file', return_value={}), \
         patch('generate_image.save_off_results'), \
         patch('generate_image.draw_out_of_town_score_board', return_value=stub_img):
        result = generate_image.orchestrate_score_board(
            games, TEAM_DATA, date_str='2026-06-20', bypass_cache=False, config=FIXED_CONFIG,
        )

    assert result is not None
    _, regions = result
    assert regions == []


@needs_pil
def test_grid_path_wildcard_sidebar_and_dark_mode():
    """Normal grid path: show_wildcard_standings / show_standings_sidebar /
    dark_mode all call into their respective helpers (mocked here since
    image_standings is a separate coverage target — we're only verifying
    generate_image's own plumbing)."""
    import generate_image

    stub_img = Image.new('1', (800, 480), 255)
    wc_config = dict(FIXED_CONFIG, show_wildcard_standings=True,
                      show_standings_sidebar=True, dark_mode=True)
    games = [{'game_pk': 1, 'away_team_id': 119, 'home_team_id': 137, 'detailed_state': 'Scheduled'}]
    standings_data = {'standings': {'1': [{'team_id': 119, 'streak': 'W2'}]}}

    with patch('generate_image.load_json_file',
               side_effect=_fake_loader({'standings.json': standings_data})), \
         patch('generate_image.save_off_results'), \
         patch('generate_image.draw_out_of_town_score_board', return_value=stub_img), \
         patch('generate_image.derive_wildcard_from_standings', return_value={'x': 1}) as mock_derive, \
         patch('generate_image.draw_wildcard_header', side_effect=lambda img, wc: img) as mock_hdr, \
         patch('generate_image.draw_standings_sidebar', side_effect=lambda img, *a, **k: img) as mock_sb:
        result = generate_image.orchestrate_score_board(
            games, TEAM_DATA, date_str='2026-06-20', bypass_cache=True, config=wc_config,
        )

    mock_derive.assert_called_once_with(standings_data)
    mock_hdr.assert_called_once()
    assert mock_sb.call_count == 2
    assert result is not None


@needs_pil
def test_grid_path_wildcard_skipped_for_aaa_league_mode():
    import generate_image

    stub_img = Image.new('1', (800, 480), 255)
    aaa_config = dict(FIXED_CONFIG, show_wildcard_standings=True, league_mode='aaa')
    games = [{'game_pk': 1, 'away_team_id': 119, 'home_team_id': 137, 'detailed_state': 'Scheduled'}]
    standings_data = {'standings': {'1': [{'team_id': 119, 'streak': 'W2'}]}}

    with patch('generate_image.load_json_file',
               side_effect=_fake_loader({'standings.json': standings_data})), \
         patch('generate_image.save_off_results'), \
         patch('generate_image.draw_out_of_town_score_board', return_value=stub_img), \
         patch('generate_image.derive_wildcard_from_standings') as mock_derive:
        result = generate_image.orchestrate_score_board(
            games, TEAM_DATA, date_str='2026-06-20', bypass_cache=True, config=aaa_config,
        )

    mock_derive.assert_not_called()
    assert result is not None


# ---------------------------------------------------------------------------
# FEATURED_TEAM_FULLSCREEN — cache short-circuit + partial-refresh zones
# ---------------------------------------------------------------------------

def _live_fs_game(**overrides):
    g = {
        'game_pk': 9001, 'away_team_id': 147, 'home_team_id': 111,
        'detailed_state': 'In Progress', 'inningState': 'Top', 'current_inning': 5,
        'balls': 1, 'strikes': 2, 'away_runs': 2, 'home_runs': 1,
        'current_pitcher': 'Logan Webb', 'due_up': 'Freddie Freeman',
        'away_win_probability': 42.0, 'home_win_probability': 58.0,
        'last_play': None,
    }
    g.update(overrides)
    return g


@needs_pil
def test_featured_fullscreen_unchanged_featured_game_skips_even_if_others_changed(monkeypatch):
    """In fullscreen mode only the featured game's own data matters; another
    game changing (here a different Final game's runs) must not force a
    re-render if the featured game itself is byte-identical."""
    import generate_image

    monkeypatch.setenv('FEATURED_TEAM_FULLSCREEN', 'true')
    config = dict(FIXED_CONFIG, primary='NYY')
    featured = _live_fs_game()
    other_old = {'game_pk': 2, 'away_team_id': 119, 'home_team_id': 137,
                 'detailed_state': 'Final', 'away_runs': 0}
    other_new = dict(other_old, away_runs=1)

    with patch('generate_image.load_json_file', side_effect=_fake_loader({
            'old_scoreboard_state.json': [featured, other_old],
        })), \
         patch('generate_image.save_off_results'), \
         patch('generate_image.draw_featured_game_fullscreen') as mock_feat:
        result = generate_image.orchestrate_score_board(
            [featured, other_new], TEAM_DATA, date_str='2026-06-20', bypass_cache=False, config=config,
        )

    assert result is None
    mock_feat.assert_not_called()


@pytest.mark.parametrize('field,old_val,new_val,expected_regions', [
    ('last_play', None, 'Home Run', [(0, 0, 800, 76)]),
    ('away_runs', 2, 3, [(0, 69, 800, 208)]),
    ('balls', 1, 2, [(0, 277, 800, 203)]),
])
@needs_pil
def test_featured_fullscreen_partial_refresh_zone_for_single_field(monkeypatch, field, old_val, new_val, expected_regions):
    """A single changed field maps to exactly its owning zone (header, score,
    or bottom) for the featured live game's partial refresh."""
    import generate_image

    monkeypatch.setenv('FEATURED_TEAM_FULLSCREEN', 'true')
    config = dict(FIXED_CONFIG, primary='NYY')
    old_game = _live_fs_game(**{field: old_val})
    new_game = _live_fs_game(**{field: new_val})
    stub_img = Image.new('1', (800, 480), 255)

    with patch('generate_image.load_json_file', side_effect=_fake_loader({
            'old_scoreboard_state.json': [old_game],
        })), \
         patch('generate_image.save_off_results'), \
         patch('generate_image.draw_featured_game_fullscreen', return_value=stub_img):
        result = generate_image.orchestrate_score_board(
            [new_game], TEAM_DATA, date_str='2026-06-20', bypass_cache=False, config=config,
        )

    assert result is not None
    _, regions = result
    assert regions == expected_regions


@needs_pil
def test_featured_fullscreen_all_three_zones_changed_falls_back_to_full_refresh(monkeypatch):
    import generate_image

    monkeypatch.setenv('FEATURED_TEAM_FULLSCREEN', 'true')
    config = dict(FIXED_CONFIG, primary='NYY')
    old_game = _live_fs_game(last_play=None, away_runs=2, balls=1)
    new_game = _live_fs_game(last_play='Home Run', away_runs=3, balls=2)
    stub_img = Image.new('1', (800, 480), 255)

    with patch('generate_image.load_json_file', side_effect=_fake_loader({
            'old_scoreboard_state.json': [old_game],
        })), \
         patch('generate_image.save_off_results'), \
         patch('generate_image.draw_featured_game_fullscreen', return_value=stub_img):
        result = generate_image.orchestrate_score_board(
            [new_game], TEAM_DATA, date_str='2026-06-20', bypass_cache=False, config=config,
        )

    assert result is not None
    _, regions = result
    assert regions == [(0, 0, 800, 480)]


@needs_pil
def test_featured_fullscreen_unknown_field_change_forces_full_refresh(monkeypatch):
    """A changed field outside all three known zone sets can't be mapped to a
    partial region, so the fine-grained logic bails out to a full refresh
    (empty list) rather than guessing."""
    import generate_image

    monkeypatch.setenv('FEATURED_TEAM_FULLSCREEN', 'true')
    config = dict(FIXED_CONFIG, primary='NYY')
    old_game = _live_fs_game(some_unmapped_field='a')
    new_game = _live_fs_game(some_unmapped_field='b')
    stub_img = Image.new('1', (800, 480), 255)

    with patch('generate_image.load_json_file', side_effect=_fake_loader({
            'old_scoreboard_state.json': [old_game],
        })), \
         patch('generate_image.save_off_results'), \
         patch('generate_image.draw_featured_game_fullscreen', return_value=stub_img):
        result = generate_image.orchestrate_score_board(
            [new_game], TEAM_DATA, date_str='2026-06-20', bypass_cache=False, config=config,
        )

    assert result is not None
    _, regions = result
    assert regions == []


@needs_pil
def test_unchanged_games_produce_no_region():
    """Games identical to their prior state contribute no region, even when
    other games in the same slate did change."""
    import generate_image
    import image_box

    old_games = [_base_game(game_pk=1, away_runs=1), _base_game(game_pk=2, away_runs=1)]
    new_games = [_base_game(game_pk=1, away_runs=1), _base_game(game_pk=2, away_runs=9)]

    with patch('generate_image.load_json_file',
               side_effect=_fake_loader({'old_scoreboard_state.json': old_games})), \
         patch('generate_image.save_off_results'), \
         patch('image_grid.load_yaml_file', return_value=FIXED_CONFIG), \
         patch('image_box.load_yaml_file', return_value=FIXED_CONFIG):
        image_box.set_historical_mode(True)
        try:
            result = generate_image.orchestrate_score_board(
                new_games, TEAM_DATA, date_str='2026-06-20', bypass_cache=False, config=FIXED_CONFIG,
            )
        finally:
            image_box.set_historical_mode(False)

    assert result is not None
    _, regions = result
    # Only game_pk=2 (row0,col1) changed → single normal-width region, aligned
    # to the second grid column (150px stride + x_start=32, 8px-rounded).
    assert len(regions) == 1
    assert regions[0][2] == 152
