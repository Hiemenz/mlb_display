"""Golden-image regression tests for the out-of-town scoreboard grid.

Renders a handful of fixed scenarios through ``draw_out_of_town_score_board``
(the same entry point ``tests/test_wide_cell.py`` exercises) and diffs the
result against a reference PNG in ``tests/golden/``.

Two things keep this deterministic without freezegun or network mocking:

- ``draw_out_of_town_score_board`` is called directly rather than through
  ``orchestrate_score_board``, so cache/state-file comparisons never run.
- The only wall-clock-dependent / network-touching code in the draw path
  (the Final-game linescore window and the tomorrow's-game preview) is
  gated by ``image_box.set_historical_mode(True)``, which the app already
  uses for deterministic ``--date`` historical replays.

Reference PNGs are generated on GitHub Actions' ubuntu-latest runner (the
same platform the merge gate runs on), since FreeType/Pillow rendering can
differ slightly across OSes. These tests are a no-op on non-Linux so local
dev machines don't fight stale references. To (re)generate the references,
run on Linux (e.g. in CI):

    poetry run pytest tests/test_golden_scoreboard.py --update-golden
"""
import os
import platform
from unittest.mock import patch

import pytest

try:
    from PIL import Image, ImageChops
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")
linux_only = pytest.mark.skipif(
    platform.system() != 'Linux',
    reason="golden references are generated on CI's Linux runner; font "
           "rendering differs enough across OSes that comparing locally "
           "would be noise, not signal.",
)

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), 'golden')
FAILURES_DIR = os.path.join(GOLDEN_DIR, '_failures')

# Fixed config, independent of config/config.yaml, so edits to the real
# config don't change what these tests render.
_FIXED_CONFIG = {
    'timezone': 'America/Chicago',
    'use_team_logos': True,
    'small_logo_x_offset': 2,
    'wide_cell_always': False,
    'wide_cell_featured': False,
    'scoreboard_live_details': True,
    'final_linescore_minutes': 60,
}

TEAM_DATA = {
    'team_abbreviation': {
        '119': 'LAD', '137': 'SF', '133': 'OAK', '144': 'ATL',
        '147': 'NYY', '111': 'BOS', '121': 'NYM', '143': 'PHI',
        '116': 'DET', '158': 'MIL', '117': 'HOU', '141': 'TOR',
    }
}


def _base_game(**overrides):
    g = {
        'game_pk': 1001,
        'away_team_id': 119,
        'home_team_id': 137,
        'away_team_name': 'LAD',
        'home_team_name': 'SF',
        'detailed_state': 'Scheduled',
        'away_runs': 0,
        'home_runs': 0,
        'away_hits': 0,
        'home_hits': 0,
        'away_errors': 0,
        'home_errors': 0,
        'away_team_is_winner': False,
        'home_team_is_winner': False,
        'winner_name': None,
        'loser_name': None,
        'saver_name': None,
        'winner_record': None,
        'loser_record': None,
        'saver_saves': None,
        'current_inning': None,
        'inningState': '',
        'away_inning_runs': [],
        'home_inning_runs': [],
        'away_team_record_wins': 40,
        'away_team_record_losses': 30,
        'home_team_record_wins': 45,
        'home_team_record_losses': 25,
        'num_of_outs': None,
        'balls': None,
        'strikes': None,
        'runner_on_first': None,
        'runner_on_second': None,
        'runner_on_third': None,
        'game_start': '7:05 PM',
        'game_datetime': '2026-06-20T23:05:00Z',
        'game_end_time_utc': None,
        'away_probable': 'R. Ray',
        'home_probable': 'L. Webb',
        'away_probable_note': '3.10 ERA',
        'home_probable_note': '2.85 ERA',
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
    g = _base_game(
        detailed_state='In Progress',
        current_inning=5,
        inningState='Top',
        num_of_outs=1,
        balls=1,
        strikes=2,
        strike_calls=['C', 'B', 'S'],
        runner_on_first='Mookie Betts',
        runner_first_number=50,
        current_pitcher='Logan Webb',
        current_hitter='Mookie Betts',
        current_play_batter='Mookie Betts',
        pitch_count=64,
        last_pitch_type='FB',
        last_pitch_speed=93.4,
        batter_hits=1,
        batter_at_bats=2,
        current_at_bat_complete=False,
        ab_pitches=[
            {'seq': 1, 'px': -0.3, 'pz': 2.8, 'sz_top': 3.4, 'sz_bot': 1.6,
             'code': 'C', 'pt_abbr': 'FB'},
            {'seq': 2, 'px': 0.9, 'pz': 1.2, 'sz_top': 3.4, 'sz_bot': 1.6,
             'code': 'B', 'pt_abbr': 'SL'},
        ],
        half_inning_plays=['K', '1B'],
        home_pitcher_ks=['K', 'K', 'L'],
        away_pitcher_ks=['K'],
        away_win_probability=47.0,
        home_win_probability=53.0,
        away_runs=2,
        home_runs=1,
        away_hits=5,
        home_hits=4,
    )
    g.update(overrides)
    return g


def _final_game(**overrides):
    g = _base_game(
        detailed_state='Final',
        current_inning=9,
        inningState='End',
        num_of_outs=3,
        away_runs=3,
        home_runs=5,
        away_hits=8,
        home_hits=10,
        away_errors=0,
        home_errors=1,
        away_team_is_winner=False,
        home_team_is_winner=True,
        winner_name='Logan Webb',
        loser_name='Reid Ray',
        winner_record='5-2',
        loser_record='3-4',
        away_inning_runs=[0, 1, 0, 0, 0, 2, 0, 0, 0],
        home_inning_runs=[1, 0, 2, 0, 0, 0, 1, 0, 1],
        game_end_time_utc='2026-06-21T02:45:00Z',
    )
    g.update(overrides)
    return g


def _render(games, date_str='2026-06-20'):
    """Render games through the grid, with config pinned regardless of
    config/config.yaml, and return the resulting mode-'1' image.

    Always renders under set_historical_mode(True): any Final/Postponed game
    in the scenario would otherwise hit the real wall clock and, if its
    linescore window has "expired", fetch tomorrow's real schedule over the
    network to draw a next-game preview — nondeterministic and networked,
    exactly what historical_mode exists to bypass for --date replays.
    """
    import image_box
    white_image = Image.new('1', (800, 480), 255)
    with patch('image_grid.load_yaml_file', return_value=_FIXED_CONFIG), \
         patch('image_box.load_yaml_file', return_value=_FIXED_CONFIG):
        from image_grid import draw_out_of_town_score_board
        image_box.set_historical_mode(True)
        try:
            return draw_out_of_town_score_board(
                white_image, games, TEAM_DATA, date_str,
                use_logos=_FIXED_CONFIG['use_team_logos'],
                logo_x_offset=_FIXED_CONFIG['small_logo_x_offset'],
            )
        finally:
            image_box.set_historical_mode(False)


def _assert_matches_golden(actual, name, update, tolerance=0.001):
    """Diff `actual` against tests/golden/<name>.png, updating it in place
    when `update` is True (--update-golden)."""
    golden_path = os.path.join(GOLDEN_DIR, f'{name}.png')

    if update:
        os.makedirs(GOLDEN_DIR, exist_ok=True)
        actual.save(golden_path)
        return

    if not os.path.exists(golden_path):
        pytest.fail(
            f"No golden reference at {golden_path}. Generate it with "
            f"`pytest tests/test_golden_scoreboard.py --update-golden` on Linux."
        )

    expected = Image.open(golden_path)
    diff = ImageChops.difference(actual.convert('L'), expected.convert('L'))
    nonzero = sum(1 for px in diff.getdata() if px != 0)
    total = diff.size[0] * diff.size[1]
    ratio = nonzero / total

    if ratio > tolerance:
        os.makedirs(FAILURES_DIR, exist_ok=True)
        actual.save(os.path.join(FAILURES_DIR, f'{name}_actual.png'))

    assert ratio <= tolerance, (
        f"{name}: {ratio:.4%} of pixels differ from {golden_path} "
        f"(tolerance {tolerance:.4%}). Actual render saved to "
        f"tests/golden/_failures/{name}_actual.png for comparison."
    )


@pytest.fixture
def golden_update(request):
    return request.config.getoption('--update-golden')


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

@needs_pil
@linux_only
def test_golden_pregame(golden_update):
    """A slate of Scheduled/Pre-Game/Warmup games — no live state at all."""
    games = [
        _base_game(game_pk=1, away_team_id=119, home_team_id=137,
                   detailed_state='Scheduled'),
        _base_game(game_pk=2, away_team_id=147, home_team_id=111,
                   detailed_state='Pre-Game', game_start='1:10 PM',
                   venue='Fenway Park'),
        _base_game(game_pk=3, away_team_id=121, home_team_id=143,
                   detailed_state='Warmup', game_start='6:40 PM',
                   venue='Citizens Bank Park'),
        _base_game(game_pk=4, away_team_id=133, home_team_id=144,
                   detailed_state='Scheduled', game_start='9:38 PM',
                   venue='Truist Park'),
        _base_game(game_pk=5, away_team_id=116, home_team_id=158,
                   detailed_state='Scheduled', game_start='7:10 PM',
                   venue='American Family Field'),
        _base_game(game_pk=6, away_team_id=117, home_team_id=141,
                   detailed_state='Scheduled', game_start='7:07 PM',
                   venue='Rogers Centre'),
    ]
    actual = _render(games)
    _assert_matches_golden(actual, 'pregame', golden_update)


@needs_pil
@linux_only
def test_golden_live_mixed(golden_update):
    """Mostly Final/Scheduled games plus one In Progress game, which should
    pick up the wide cell (only live game among <15 total)."""
    games = [
        _live_game(game_pk=10, away_team_id=119, home_team_id=137),
        _final_game(game_pk=11, away_team_id=147, home_team_id=111),
        _base_game(game_pk=12, away_team_id=121, home_team_id=143,
                   detailed_state='Scheduled', game_start='8:05 PM'),
        _final_game(game_pk=13, away_team_id=133, home_team_id=144,
                     away_runs=6, home_runs=2, away_team_is_winner=True,
                     home_team_is_winner=False),
        _base_game(game_pk=14, away_team_id=116, home_team_id=158,
                   detailed_state='Warmup', game_start='7:10 PM'),
    ]
    actual = _render(games)
    _assert_matches_golden(actual, 'live_mixed', golden_update)


@needs_pil
@linux_only
def test_golden_final_mixed(golden_update):
    """Slate of Final games (linescores, decisions, a walk-off) — exercises
    the wall-clock-gated linescore-window code, neutralized by _render()'s
    set_historical_mode."""
    games = [
        _final_game(game_pk=20, away_team_id=119, home_team_id=137),
        _final_game(game_pk=21, away_team_id=147, home_team_id=111,
                     away_runs=4, home_runs=3, away_team_is_winner=True,
                     home_team_is_winner=False, walk_off=False),
        _final_game(game_pk=22, away_team_id=121, home_team_id=143,
                     walk_off=True, away_runs=2, home_runs=3,
                     away_team_is_winner=False, home_team_is_winner=True,
                     away_inning_runs=[0, 1, 0, 0, 0, 1, 0, 0, 0],
                     home_inning_runs=[0, 0, 0, 1, 0, 0, 0, 0, 2]),
    ]
    actual = _render(games)
    _assert_matches_golden(actual, 'final_mixed', golden_update)
