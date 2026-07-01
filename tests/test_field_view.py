"""Smoke tests for field_view.py — single-game field diagram rendering.

Covers:
  1. render_field_view happy path (In Progress, runners on, hits plotted)
  2. Pitch-code / count / balls-strikes branches (via _draw_pitch_zone)
  3. Hit-marker branches: none, multiple (HR / hit / out), legacy tuple, ghost markers
  4. Base-occupancy branches: empty vs all occupied
  5. Missing optional keys (batter/pitcher/on_deck, last_play, innings) don't crash
  6. detailed_state branches: Scheduled, Warmup, In Progress, Final
  7. dark_mode True/False
  8. Unknown venue -> stadium_polygons.get_polygon fallback path
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

# Prevent any accidental network calls if a fixture ever supplies an
# abbreviation without a locally-cached logo PNG.
@pytest.fixture(autouse=True)
def _no_network(request):
    if not PIL_AVAILABLE:
        yield
        return
    with patch('image_assets._try_download_logo', return_value=False):
        yield


def _base_game(**overrides):
    g = {
        'venue': 'Oracle Park',
        'detailed_state': 'In Progress',
        'inning_state': 'Top',
        'inning_ordinal': '7th',
        'current_inning': 7,
        'outs': 1,
        'balls': 2,
        'strikes': 1,
        'away_abbr': 'LAD',
        'home_abbr': 'SF',
        'away_id': 119,
        'home_id': 137,
        'away_runs': 3,
        'home_runs': 2,
        'away_hits': 7,
        'home_hits': 5,
        'away_errors': 0,
        'home_errors': 1,
        'runner_first': 'Mookie Betts',
        'runner_second': None,
        'runner_third': None,
        'batter': {
            'name': 'Freddie Freeman',
            'season': {'avg': '.312', 'homeRuns': '15', 'rbi': '55'},
        },
        'pitcher': {
            'name': 'Logan Webb',
            'season': {'era': '2.85'},
            'stats': {'inningsPitched': '150.0', 'strikeOuts': '140'},
        },
        'on_deck': {
            'name': 'Will Smith',
            'season': {'avg': '.290', 'homeRuns': '10'},
        },
        'last_play': 'Freeman singled to right field.',
        'pitches': [
            {'px': -0.3, 'pz': 2.8, 'code': 'C'},
            {'px': 0.9, 'pz': 1.2, 'code': 'B'},
            {'px': 0.1, 'pz': 2.5, 'code': 'S'},
        ],
        'all_hits': [
            {'x': 150, 'y': 180, 'is_hr': False, 'is_hit': True,
             'player': 'Freeman', 'inning': 7, 'half': 'top'},
        ],
        'innings': [
            {'num': i + 1, 'away_runs': 0, 'home_runs': 0} for i in range(7)
        ],
    }
    g.update(overrides)
    return g


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

@needs_pil
def test_happy_path_in_progress():
    from field_view import render_field_view
    result = render_field_view(_base_game())
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)
    assert result.mode == '1'
    assert result.getbbox() is not None


# ---------------------------------------------------------------------------
# 2. Pitch codes / counts
# ---------------------------------------------------------------------------

@needs_pil
def test_no_pitches():
    from field_view import render_field_view
    result = render_field_view(_base_game(pitches=[]))
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)


@needs_pil
def test_all_pitch_codes():
    from field_view import render_field_view
    pitches = [
        {'px': -0.5, 'pz': 2.0, 'code': 'S'},   # swinging strike
        {'px': -0.2, 'pz': 2.2, 'code': 'C'},   # called strike
        {'px': 0.0, 'pz': 2.4, 'code': 'T'},    # foul tip
        {'px': 0.2, 'pz': 2.6, 'code': 'F'},    # foul
        {'px': 0.4, 'pz': 2.8, 'code': 'X'},    # in play
        {'px': -0.8, 'pz': 3.9, 'code': 'B'},   # ball
        {'px': None, 'pz': None, 'code': 'B'},  # missing coords, skipped
    ]
    result = render_field_view(_base_game(pitches=pitches))
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)


@needs_pil
def test_final_state_hides_count():
    from field_view import render_field_view
    result = render_field_view(_base_game(detailed_state='Final'))
    assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# 3. Hit markers
# ---------------------------------------------------------------------------

@needs_pil
def test_no_hits():
    from field_view import render_field_view
    result = render_field_view(_base_game(all_hits=[]))
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)


@needs_pil
def test_multiple_hits_hr_and_out_current_half():
    from field_view import render_field_view
    game = _base_game(all_hits=[
        {'x': 200, 'y': 100, 'is_hr': True, 'is_hit': True,
         'player': 'Betts', 'inning': 7, 'half': 'top'},
        {'x': 100, 'y': 220, 'is_hr': False, 'is_hit': True,
         'player': 'Freeman', 'inning': 7, 'half': 'top'},
        {'x': 160, 'y': 250, 'is_hr': False, 'is_hit': False, 'is_out': True,
         'player': 'Muncy', 'inning': 7, 'half': 'top'},
    ])
    result = render_field_view(game)
    assert isinstance(result, Image.Image)
    assert result.getbbox() is not None


@needs_pil
def test_hits_previous_half_ghost_markers():
    """Hits from a previous inning/half render as outline/ghost markers."""
    from field_view import render_field_view
    game = _base_game(current_inning=7, inning_state='Top', all_hits=[
        {'x': 200, 'y': 100, 'is_hr': True, 'is_hit': True,
         'player': 'Betts', 'inning': 6, 'half': 'bottom'},
        {'x': 100, 'y': 220, 'is_hr': False, 'is_hit': True,
         'player': 'Freeman', 'inning': 6, 'half': 'bottom'},
        {'x': 160, 'y': 250, 'is_hr': False, 'is_hit': False, 'is_out': True,
         'player': 'Muncy', 'inning': 6, 'half': 'bottom'},
    ])
    result = render_field_view(game)
    assert isinstance(result, Image.Image)


@needs_pil
def test_legacy_tuple_hit_coords():
    """hit_coords legacy single-tuple fallback when all_hits is absent."""
    from field_view import render_field_view
    game = _base_game()
    game.pop('all_hits', None)
    game['hit_coords'] = (140, 190)
    result = render_field_view(game)
    assert isinstance(result, Image.Image)


@needs_pil
def test_legacy_tuple_list_in_all_hits():
    """all_hits containing raw (x, y) tuples instead of dicts."""
    from field_view import render_field_view
    game = _base_game(all_hits=[(120, 160), (180, 240)])
    result = render_field_view(game)
    assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# 4. Base occupancy
# ---------------------------------------------------------------------------

@needs_pil
def test_bases_all_empty():
    from field_view import render_field_view
    game = _base_game(runner_first=None, runner_second=None, runner_third=None)
    result = render_field_view(game)
    assert isinstance(result, Image.Image)


@needs_pil
def test_bases_all_occupied():
    from field_view import render_field_view
    game = _base_game(
        runner_first='Mookie Betts',
        runner_second='Freddie Freeman',
        runner_third='Will Smith',
    )
    result = render_field_view(game)
    assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# 5. Missing optional keys
# ---------------------------------------------------------------------------

@needs_pil
def test_missing_batter_pitcher_on_deck():
    from field_view import render_field_view
    game = _base_game()
    for key in ('batter', 'pitcher', 'on_deck', 'last_play', 'innings'):
        game.pop(key, None)
    result = render_field_view(game)
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)


@needs_pil
def test_none_batter_pitcher_on_deck():
    from field_view import render_field_view
    game = _base_game(batter=None, pitcher=None, on_deck=None)
    result = render_field_view(game)
    assert isinstance(result, Image.Image)


@needs_pil
def test_empty_data_dict():
    """An almost-empty data dict must not crash — every field falls back to .get() defaults."""
    from field_view import render_field_view
    result = render_field_view({})
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)
    assert result.mode == '1'


# ---------------------------------------------------------------------------
# 6. detailed_state branches
# ---------------------------------------------------------------------------

@needs_pil
@pytest.mark.parametrize('state', ['Scheduled', 'Pre-Game', 'Warmup', 'In Progress', 'Final', 'Game Over'])
def test_detailed_state_variants(state):
    from field_view import render_field_view
    game = _base_game(detailed_state=state)
    if state in ('Scheduled', 'Pre-Game', 'Warmup'):
        game['away_probable'] = 'TBD Pitcher'
        game['home_probable'] = 'Logan Webb'
    if state in ('Final', 'Game Over'):
        game['winner'] = 'Logan Webb'
        game['loser'] = 'Clayton Kershaw'
        game['save'] = 'Camilo Doval'
    result = render_field_view(game)
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)


# ---------------------------------------------------------------------------
# 7. dark_mode
# ---------------------------------------------------------------------------

@needs_pil
def test_dark_mode_true():
    from field_view import render_field_view
    result = render_field_view(_base_game(), dark_mode=True)
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)
    assert result.mode == '1'


@needs_pil
def test_dark_mode_false():
    from field_view import render_field_view
    result = render_field_view(_base_game(), dark_mode=False)
    assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# 8. Unknown venue -> fallback polygon
# ---------------------------------------------------------------------------

@needs_pil
def test_unknown_venue_fallback_polygon():
    from field_view import render_field_view
    result = render_field_view(_base_game(venue='Some Made Up Stadium XYZ'))
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)


@needs_pil
def test_missing_venue():
    from field_view import render_field_view
    game = _base_game()
    game.pop('venue', None)
    result = render_field_view(game)
    assert isinstance(result, Image.Image)


@needs_pil
def test_long_last_play_wraps_lines():
    """A long last_play string wraps to multiple lines (only first 2 shown)."""
    from field_view import render_field_view
    game = _base_game(
        last_play=('Freeman doubled to deep right center field, Betts scored, '
                    'Smith advanced to third, Muncy advanced to second on the play.')
    )
    result = render_field_view(game)
    assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# _word_wrap unit tests — direct coverage of the wrap + AttributeError fallback
# ---------------------------------------------------------------------------

@needs_pil
def test_word_wrap_wraps_on_overflow():
    from field_view import _word_wrap

    class _RealFont:
        def getlength(self, text):
            return len(text) * 10

    lines = _word_wrap('one two three four five six seven eight', _RealFont(), 40)
    assert len(lines) > 1


@needs_pil
def test_word_wrap_font_without_getlength_falls_back():
    from field_view import _word_wrap

    class _NoGetLengthFont:
        pass

    lines = _word_wrap('some words here', _NoGetLengthFont(), 5)
    assert lines
    assert isinstance(lines, list)
