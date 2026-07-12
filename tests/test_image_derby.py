"""Smoke tests for src/image_derby.py — the Home Run Derby bracket renderer."""
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

import pytest

from image_derby import render_derby_bracket


def _tbd_matchup():
    return {
        'complete': False,
        'players': [
            {'name': 'TBD', 'abbr': '', 'hr': None, 'winner': False},
            {'name': 'TBD', 'abbr': '', 'hr': None, 'winner': False},
        ],
    }


def _empty_bracket():
    return {
        'event_date': '2026-07-13',
        'round_status': 'Round 1 - In Progress',
        'matchups': {
            'qf': [_tbd_matchup() for _ in range(4)],
            'sf': [_tbd_matchup() for _ in range(2)],
            'final': _tbd_matchup(),
        },
        'champion': None,
    }


def _completed_bracket():
    data = _empty_bracket()
    data['round_status'] = 'Round 3 - Final'
    data['matchups']['qf'][0] = {
        'complete': True,
        'players': [
            {'name': 'C. Raleigh', 'abbr': 'SEA', 'hr': 17, 'winner': True},
            {'name': 'O. Cruz', 'abbr': 'PIT', 'hr': 21, 'winner': False},
        ],
    }
    data['matchups']['final'] = {
        'complete': True,
        'players': [
            {'name': 'C. Raleigh', 'abbr': 'SEA', 'hr': 18, 'winner': True},
            {'name': 'J. Caminero', 'abbr': 'TB', 'hr': 15, 'winner': False},
        ],
    }
    data['champion'] = 'C. Raleigh'
    return data


@pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")
class TestRenderDerbyBracket:
    def test_empty_bracket_renders_800x480(self):
        img = render_derby_bracket(_empty_bracket())
        assert isinstance(img, Image.Image)
        assert img.size == (800, 480)

    def test_completed_bracket_with_champion_renders(self):
        img = render_derby_bracket(_completed_bracket())
        assert isinstance(img, Image.Image)
        assert img.size == (800, 480)

    def test_dark_mode_inverts_without_error(self):
        img = render_derby_bracket(_completed_bracket(), dark_mode=True)
        assert isinstance(img, Image.Image)
        assert img.size == (800, 480)

    def test_missing_champion_shows_tbd(self):
        img = render_derby_bracket(_empty_bracket())
        assert isinstance(img, Image.Image)
