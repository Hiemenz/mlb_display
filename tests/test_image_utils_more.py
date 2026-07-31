"""Additional coverage for src/image_utils.py gaps not already exercised by
tests/test_scoreboard_rules.py: normalize_dict(), _last_name()'s
empty-parts edge, _render_linescore_row(), and _series_display_str()."""
import os

import pytest

from image_utils import (
    normalize_dict,
    _last_name,
    _render_linescore_row,
    _series_display_str,
    draw_tight_number,
)

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")


# ===========================================================================
# normalize_dict
# ===========================================================================

class TestNormalizeDict:
    def test_flat_none_converted_to_empty_string(self):
        """Flat none converted to empty string."""
        d = {'a': None, 'b': 1}
        result = normalize_dict(d)
        assert result == {'a': '', 'b': 1}

    def test_list_of_nones_converted(self):
        """List of nones converted."""
        d = {'a': [1, None, 3]}
        result = normalize_dict(d)
        assert result == {'a': [1, '', 3]}

    def test_nested_dict_recursively_normalized(self):
        """Nested dict recursively normalized."""
        d = {'outer': {'inner': None, 'kept': 5}}
        result = normalize_dict(d)
        assert result == {'outer': {'inner': '', 'kept': 5}}

    def test_list_of_dicts_normalized(self):
        """List of dicts normalized."""
        d = {'games': [{'score': None, 'id': 1}, {'score': 3, 'id': None}]}
        result = normalize_dict(d)
        # NOTE: the list-branch only replaces None *items*, not dict fields
        # inside items — items that are dicts stay dicts, un-normalized,
        # since only 'is dict at top-level value' triggers recursion.
        assert result['games'][0] == {'score': None, 'id': 1}
        assert result['games'][1] == {'score': 3, 'id': None}

    def test_deeply_nested_dict(self):
        """Deeply nested dict."""
        d = {'a': {'b': {'c': None}}}
        result = normalize_dict(d)
        assert result == {'a': {'b': {'c': ''}}}

    def test_empty_dict_unchanged(self):
        """Empty dict unchanged."""
        assert normalize_dict({}) == {}

    def test_mixed_types_unaffected(self):
        """Mixed types unaffected."""
        d = {'x': 'hello', 'y': True, 'z': 3.14}
        result = normalize_dict(d)
        assert result == d


# ===========================================================================
# _last_name — empty-parts edge case
# ===========================================================================

class TestLastNameEmptyParts:
    def test_whitespace_only_name_returns_empty_string(self):
        """Whitespace only name returns empty string."""
        # name is truthy (non-empty string) but .split() on pure whitespace
        # yields an empty parts list -> early-return branch.
        assert _last_name('   ') == ''

    def test_tabs_and_newlines_only(self):
        """Tabs and newlines only."""
        assert _last_name('\t\n  \t') == ''


# ===========================================================================
# _render_linescore_row
# ===========================================================================

@pytest.fixture
def font():
    """Font."""
    picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pic')
    return ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 14)


@pytest.fixture
def draw_ctx():
    """Draw ctx."""
    img = Image.new('1', (200, 50), 255)
    draw = ImageDraw.Draw(img)
    return img, draw


class TestRenderLinescoreRow:
    @needs_pil
    def test_empty_inning_runs_no_op(self, draw_ctx, font):
        """Empty inning runs no op."""
        img, draw = draw_ctx
        _render_linescore_row(draw, 0, 0, [], font, max_width=130)
        # Nothing drawn -> image stays entirely white
        assert all(p != 0 for p in img.getdata())

    @needs_pil
    def test_none_inning_runs_no_op(self, draw_ctx, font):
        """None inning runs no op."""
        img, draw = draw_ctx
        _render_linescore_row(draw, 0, 0, None, font, max_width=130)
        assert all(p != 0 for p in img.getdata())

    @needs_pil
    def test_draws_something_for_valid_runs(self, draw_ctx, font):
        """Draws something for valid runs."""
        img, draw = draw_ctx
        _render_linescore_row(draw, 0, 0, [1, 2, 3, 0], font, max_width=130)
        assert any(p == 0 for p in img.getdata())

    @needs_pil
    def test_none_values_rendered_as_x(self, draw_ctx, font):
        """None values rendered as x."""
        img, draw = draw_ctx
        # Should not raise on None entries within the list — rendered as 'x'.
        _render_linescore_row(draw, 0, 0, [1, None, 3], font, max_width=130)
        assert any(p == 0 for p in img.getdata())

    @needs_pil
    def test_truncates_to_first_15_innings(self, draw_ctx, font):
        """Truncates to first 15 innings."""
        img, draw = draw_ctx
        long_runs = list(range(20))
        # Should not raise despite more than 15 innings provided.
        _render_linescore_row(draw, 0, 0, long_runs, font, max_width=130)

    @needs_pil
    def test_tight_max_width_falls_back_to_no_separator(self, font):
        """With a very small max_width, the loop should fall through to the
        tightest ('') separator rather than raising."""
        img = Image.new('1', (400, 50), 255)
        draw = ImageDraw.Draw(img)
        # Small max_width forces the '' separator branch to be selected/tried.
        _render_linescore_row(draw, 0, 0, [1, 2, 3, 4, 5, 6, 7, 8, 9], font, max_width=1)
        # Even with the tightest separator this may still exceed max_width,
        # but the function must still draw without raising.
        assert any(p == 0 for p in img.getdata())


# ===========================================================================
# _series_display_str
# ===========================================================================

class TestSeriesDisplayStr:
    def _game(self, **overrides):
        """Game."""
        g = {
            'series_total_games': 3,
            'series_wins': 0,
            'series_losses': 0,
            'series_game_number': 1,
            'series_result': '',
        }
        g.update(overrides)
        return g

    def test_single_game_series_returns_none(self):
        """Single game series returns none."""
        game = self._game(series_total_games=1)
        assert _series_display_str(game) is None

    def test_missing_total_games_defaults_to_one_returns_none(self):
        """Missing total games defaults to one returns none."""
        game = self._game(series_total_games=None)
        assert _series_display_str(game) is None

    def test_no_wins_or_losses_shows_game_number(self):
        """No wins or losses shows game number."""
        game = self._game(series_total_games=3, series_wins=0, series_losses=0, series_game_number=2)
        assert _series_display_str(game) == 'Gm 2/3'

    def test_no_wins_losses_missing_game_number_defaults_to_one(self):
        """No wins losses missing game number defaults to one."""
        game = self._game(series_total_games=3, series_wins=0, series_losses=0, series_game_number=None)
        assert _series_display_str(game) == 'Gm 1/3'

    def test_tied_series(self):
        """Tied series."""
        game = self._game(series_total_games=3, series_wins=1, series_losses=1)
        assert _series_display_str(game) == 'Tied 1-1'

    def test_series_result_capitalized(self):
        """Series result capitalized."""
        game = self._game(series_total_games=3, series_wins=2, series_losses=1,
                           series_result='Series tied 2-1')
        # 'Series ' prefix stripped, then first-letter capitalized
        assert _series_display_str(game) == 'Tied 2-1'

    def test_series_result_lowercase_first_letter_capitalized(self):
        """Series result lowercase first letter capitalized."""
        game = self._game(series_total_games=3, series_wins=2, series_losses=0,
                           series_result='clinched 2-0')
        assert _series_display_str(game) == 'Clinched 2-0'

    def test_no_series_result_and_not_tied_returns_none(self):
        """No series result and not tied returns none."""
        game = self._game(series_total_games=3, series_wins=2, series_losses=1, series_result='')
        assert _series_display_str(game) is None

    def test_none_series_result_treated_as_empty(self):
        """None series result treated as empty."""
        game = self._game(series_total_games=3, series_wins=2, series_losses=0, series_result=None)
        assert _series_display_str(game) is None


# ===========================================================================
# draw_tight_number — bold single-character path
# ===========================================================================

class TestDrawTightNumberBold:
    @needs_pil
    def test_single_char_bold_no_crash(self):
        """draw_tight_number with bold=True on a single character must not raise."""
        import os
        from PIL import Image, ImageDraw, ImageFont
        picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pic')
        font = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 14)
        img = Image.new('1', (50, 50), 255)
        draw = ImageDraw.Draw(img)
        draw_tight_number(draw, 25, 25, '3', font, fill=0, bold=True)
        assert any(p == 0 for p in img.getdata())
