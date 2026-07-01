"""Smoke tests for the scorecard view (src/scorecard_view.py).

Covers the single public entry point, render_scorecard_view(data, dark_mode),
exercising the batter grid, pitch-dot / mini-diamond helpers (indirectly),
substitution display, extra-inning summary column, shortened games, and the
pitcher panel — following the local fixture-dict-builder style established in
tests/test_wide_cell.py.
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
# Fixture builders
# ---------------------------------------------------------------------------

def _at_bat(code='1B', bases=1, balls=0, strikes=0):
    return {'code': code, 'bases': bases, 'balls': balls, 'strikes': strikes}


def _batter(order, name='John Smith', position='CF', sub=False,
            sub_original=None, at_bats=None, totals=None):
    return {
        'name': name,
        'position': position,
        'order': order,
        'sub': sub,
        'sub_original': sub_original,
        'at_bats': at_bats if at_bats is not None else {},
        'totals': totals if totals is not None else {'runs': 0, 'hits': 0},
    }


def _make_lineup(n=9):
    """A realistic 9-batter lineup with a handful of at-bats sprinkled in and
    one late-inning substitution (batter 9)."""
    codes = ['1B', 'K', 'HR', '6-3', 'BB', '2B', 'F9', '3B', 'K']
    lineup = []
    for i in range(n):
        order = i + 1
        at_bats = {
            1: [_at_bat(codes[i % len(codes)], bases=(i % 5), balls=i % 5, strikes=i % 4)],
            4: [_at_bat('K', bases=0, balls=1, strikes=3)],
        }
        totals = {'runs': 1 if i % 3 == 0 else 0, 'hits': 1 if i % 2 == 0 else 0}
        if order == 9:
            lineup.append(_batter(
                order, name='Pinch Hitter', position='PH', sub=True,
                sub_original={'name': 'Original Starter', 'position': 'C'},
                at_bats=at_bats, totals=totals,
            ))
        else:
            lineup.append(_batter(order, name=f'Player {order}', position='CF',
                                   at_bats=at_bats, totals=totals))
    return lineup


def _make_lineup_no_subs(n=9):
    lineup = []
    for i in range(n):
        order = i + 1
        at_bats = {1: [_at_bat('1B', bases=1, balls=0, strikes=1)]}
        lineup.append(_batter(order, name=f'Player {order}', position='SS',
                               at_bats=at_bats, totals={'runs': 0, 'hits': 1}))
    return lineup


def _pitcher(name='Ace Reliever', ip='1.0', hits=1, er=0, k=2):
    return {'name': name, 'ip': ip, 'hits': hits, 'er': er, 'k': k}


def _base_data(**overrides):
    data = {
        'num_innings': 9,
        'away_abbr': 'LAD',
        'away_id': 119,
        'home_abbr': 'SF',
        'home_id': 137,
        'away_runs': 4,
        'away_hits': 8,
        'away_errors': 0,
        'home_runs': 3,
        'home_hits': 6,
        'home_errors': 1,
        'away_lineup': _make_lineup(),
        'home_lineup': _make_lineup(),
        'away_inning_totals': {1: 1, 4: 0, 6: 3},
        'home_inning_totals': {2: 2, 5: 1},
        'away_pitchers': [_pitcher('Starter One', '6.0', 5, 2, 7),
                          _pitcher('Reliever Two', '2.0', 1, 0, 3)],
        'home_pitchers': [_pitcher('Starter Two', '7.0', 4, 1, 8)],
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# render_scorecard_view: basic + variations
# ---------------------------------------------------------------------------

@needs_pil
@patch('scorecard_view._logo_small', return_value=None)
def test_render_basic(_mock_logo):
    from scorecard_view import render_scorecard_view
    result = render_scorecard_view(_base_data())
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)
    assert result.mode == '1'


@needs_pil
@patch('scorecard_view._logo_small', return_value=None)
def test_render_dark_mode(_mock_logo):
    from scorecard_view import render_scorecard_view
    result = render_scorecard_view(_base_data(), dark_mode=True)
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)
    assert result.mode == '1'


@needs_pil
@patch('scorecard_view._logo_small', return_value=None)
def test_render_shortened_game(_mock_logo):
    """num_innings < 9 (rain-shortened game) — no extras column."""
    from scorecard_view import render_scorecard_view
    data = _base_data(num_innings=6, away_inning_totals={1: 1, 3: 2},
                       home_inning_totals={2: 1})
    result = render_scorecard_view(data)
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)


@needs_pil
@patch('scorecard_view._logo_small', return_value=None)
def test_render_extra_innings(_mock_logo):
    """num_innings > 9 exercises the has_extras / '10+' summary column path."""
    from scorecard_view import render_scorecard_view
    lineup = _make_lineup()
    # Give the leadoff batter an at-bat in extra innings so the "10+" summary
    # cell actually has something to draw.
    lineup[0]['at_bats'][10] = [_at_bat('2B', bases=2, balls=1, strikes=2)]
    lineup[0]['at_bats'][11] = [_at_bat('HR', bases=4, balls=0, strikes=0)]
    data = _base_data(num_innings=11, away_lineup=lineup,
                       away_inning_totals={1: 1, 10: 0, 11: 1})
    result = render_scorecard_view(data)
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)


@needs_pil
@patch('scorecard_view._logo_small', return_value=None)
def test_render_no_substitutions(_mock_logo):
    from scorecard_view import render_scorecard_view
    data = _base_data(away_lineup=_make_lineup_no_subs(), home_lineup=_make_lineup_no_subs())
    result = render_scorecard_view(data)
    assert isinstance(result, Image.Image)


@needs_pil
@patch('scorecard_view._logo_small', return_value=None)
def test_render_batter_with_no_at_bats_yet(_mock_logo):
    """Early-game state: a batter slot with an empty at_bats dict must not crash
    the per-inning cell drawing or the pitch-dot/diamond helpers."""
    from scorecard_view import render_scorecard_view
    lineup = _make_lineup_no_subs()
    lineup[-1]['at_bats'] = {}
    lineup[-1]['totals'] = {'runs': 0, 'hits': 0}
    data = _base_data(away_lineup=lineup)
    result = render_scorecard_view(data)
    assert isinstance(result, Image.Image)


@needs_pil
@patch('scorecard_view._logo_small', return_value=None)
def test_render_short_lineup(_mock_logo):
    """Fewer than 9 entries in the lineup list (slot_idx >= len(lineup))."""
    from scorecard_view import render_scorecard_view
    data = _base_data(away_lineup=_make_lineup_no_subs(n=4))
    result = render_scorecard_view(data)
    assert isinstance(result, Image.Image)


@needs_pil
@patch('scorecard_view._logo_small', return_value=None)
def test_render_missing_pitchers(_mock_logo):
    """away_pitchers absent entirely; home_pitchers empty list."""
    from scorecard_view import render_scorecard_view
    data = _base_data(home_pitchers=[])
    del data['away_pitchers']
    result = render_scorecard_view(data)
    assert isinstance(result, Image.Image)


@needs_pil
@patch('scorecard_view._logo_small', return_value=None)
def test_render_many_pitchers_truncates(_mock_logo):
    """More pitchers than fit in the panel height must truncate, not crash."""
    from scorecard_view import render_scorecard_view
    pitchers = [_pitcher(f'Pitcher {i}', '1.0', i % 3, i % 2, i) for i in range(30)]
    data = _base_data(away_pitchers=pitchers, home_pitchers=pitchers)
    result = render_scorecard_view(data)
    assert isinstance(result, Image.Image)


@needs_pil
@patch('scorecard_view._logo_small', return_value=None)
def test_render_various_at_bat_codes_and_bases(_mock_logo):
    """Exercise _draw_pitch_dots / _draw_mini_diamond across the full range of
    bases (0-4), balls (0-4, capped), and strikes (0-3, capped) values."""
    from scorecard_view import render_scorecard_view
    lineup = _make_lineup_no_subs()
    all_codes = ['K', 'BB', '1B', '2B', '3B', 'HR', '6-3', 'F7', '4-3']
    for i, entry in enumerate(lineup):
        entry['at_bats'] = {
            (i % 9) + 1: [_at_bat(all_codes[i % len(all_codes)],
                                   bases=i % 5, balls=min(i, 5), strikes=min(i, 4))],
        }
    data = _base_data(away_lineup=lineup)
    result = render_scorecard_view(data)
    assert isinstance(result, Image.Image)


@needs_pil
@patch('scorecard_view._logo_small', return_value=None)
def test_render_empty_data(_mock_logo):
    """Completely empty data dict — everything falls back to defaults."""
    from scorecard_view import render_scorecard_view
    result = render_scorecard_view({})
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)
    assert result.mode == '1'


@needs_pil
def test_render_with_logo_present():
    """When _logo_small returns a real small image, the paste-thumbnail branch
    in _draw_team_scorecard's header row is exercised instead of the no-logo path."""
    from scorecard_view import render_scorecard_view
    fake_logo = Image.new('1', (28, 28), 0)
    with patch('scorecard_view._logo_small', return_value=fake_logo):
        result = render_scorecard_view(_base_data())
    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)
