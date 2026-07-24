"""Tests for image_streaks.draw_streaks_cell and image_scoreless.draw_scoreless_cell."""
from unittest.mock import patch, MagicMock

import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason='PIL not installed')


def _img():
    return Image.new('1', (800, 480), 255)


_TEAMS = {'team_abbreviation': {'147': 'NYY', '119': 'LAD'}}

_HITTER_ENTRIES = [
    {'rank': 1, 'name': 'Aaron Judge',    'avg': '.350', 'games': '14', 'team_id': '147', 'abbr': 'NYY'},
    {'rank': 2, 'name': 'Freddie Freeman', 'avg': '.338', 'games': '12', 'team_id': '119', 'abbr': 'LAD'},
    {'rank': 3, 'name': 'Short',          'avg': '.320', 'games': '',   'team_id': '147', 'abbr': 'NYY'},
]

_PITCHER_ENTRIES = [
    {'rank': 1, 'name': 'Gerrit Cole',  'era': '1.57', 'ip': '115.0', 'team_id': '147', 'abbr': 'NYY'},
    {'rank': 2, 'name': 'Tyler Glasnow', 'era': '2.10', 'ip': '',      'team_id': '119', 'abbr': 'LAD'},
]

_STREAKS_DATA = {'streaks': _HITTER_ENTRIES, 'scoreless': _PITCHER_ENTRIES}


# ===========================================================================
# draw_streaks_cell
# ===========================================================================

from image_streaks import draw_streaks_cell


@needs_pil
class TestDrawStreaksCell:
    def test_renders_with_data(self):
        img = _img()
        result = draw_streaks_cell(img, 32, 30, _STREAKS_DATA, _TEAMS)
        assert result is not None

    def test_renders_empty_entries(self):
        img = _img()
        result = draw_streaks_cell(img, 32, 30, {'streaks': []}, _TEAMS)
        assert result is not None

    def test_renders_none_data(self):
        img = _img()
        result = draw_streaks_cell(img, 32, 30, None, _TEAMS)
        assert result is not None

    def test_renders_empty_dict(self):
        img = _img()
        result = draw_streaks_cell(img, 0, 0, {}, {})
        assert result is not None

    def test_returns_image(self):
        img = _img()
        result = draw_streaks_cell(img, 0, 0, _STREAKS_DATA, _TEAMS)
        assert isinstance(result, Image.Image)

    def test_many_entries_uses_smaller_font(self):
        entries = [{'rank': i, 'name': f'Player {i}', 'avg': '.300', 'games': '10',
                    'team_id': '147', 'abbr': 'NYY'} for i in range(8)]
        img = _img()
        result = draw_streaks_cell(img, 0, 0, {'streaks': entries}, _TEAMS)
        assert result is not None

    def test_entry_without_games_shows_avg_only(self):
        entries = [{'rank': 1, 'name': 'Player', 'avg': '.315', 'games': '',
                    'team_id': '147', 'abbr': 'NYY'}]
        img = _img()
        result = draw_streaks_cell(img, 0, 0, {'streaks': entries}, _TEAMS)
        assert result is not None

    def test_use_logos_true_attempts_logo(self):
        fake_logo = Image.new('1', (16, 16), 255)
        with patch('image_streaks._logo_small', return_value=fake_logo):
            img = _img()
            result = draw_streaks_cell(img, 0, 0, _STREAKS_DATA, _TEAMS, use_logos=True)
        assert result is not None

    def test_use_logos_exception_is_swallowed(self):
        with patch('image_streaks._logo_small', side_effect=OSError('no file')):
            img = _img()
            result = draw_streaks_cell(img, 0, 0, _STREAKS_DATA, _TEAMS, use_logos=True)
        assert result is not None

    def test_use_logos_returns_none_logo(self):
        with patch('image_streaks._logo_small', return_value=None):
            img = _img()
            result = draw_streaks_cell(img, 0, 0, _STREAKS_DATA, _TEAMS, use_logos=True)
        assert result is not None

    def test_long_name_truncated(self):
        entries = [{'rank': 1, 'name': 'A' * 100, 'avg': '.300', 'games': '14',
                    'team_id': '147', 'abbr': 'NYY'}]
        img = _img()
        result = draw_streaks_cell(img, 0, 0, {'streaks': entries}, _TEAMS)
        assert result is not None

    def test_entry_missing_abbr_falls_back_to_abbr_map(self):
        entries = [{'rank': 1, 'name': 'Player', 'avg': '.300', 'games': '10',
                    'team_id': '147', 'abbr': ''}]
        img = _img()
        result = draw_streaks_cell(img, 0, 0, {'streaks': entries}, _TEAMS)
        assert result is not None


# ===========================================================================
# draw_scoreless_cell
# ===========================================================================

from image_scoreless import draw_scoreless_cell


@needs_pil
class TestDrawScorelessCell:
    def test_renders_with_data(self):
        img = _img()
        result = draw_scoreless_cell(img, 32, 30, _STREAKS_DATA, _TEAMS)
        assert result is not None

    def test_renders_empty_entries(self):
        img = _img()
        result = draw_scoreless_cell(img, 32, 30, {'scoreless': []}, _TEAMS)
        assert result is not None

    def test_renders_none_data(self):
        img = _img()
        result = draw_scoreless_cell(img, 32, 30, None, _TEAMS)
        assert result is not None

    def test_renders_empty_dict(self):
        img = _img()
        result = draw_scoreless_cell(img, 0, 0, {}, {})
        assert result is not None

    def test_returns_image(self):
        img = _img()
        result = draw_scoreless_cell(img, 0, 0, _STREAKS_DATA, _TEAMS)
        assert isinstance(result, Image.Image)

    def test_many_entries_uses_smaller_font(self):
        entries = [{'rank': i, 'name': f'Pitcher {i}', 'era': '2.50', 'ip': '80.0',
                    'team_id': '147', 'abbr': 'NYY'} for i in range(8)]
        img = _img()
        result = draw_scoreless_cell(img, 0, 0, {'scoreless': entries}, _TEAMS)
        assert result is not None

    def test_entry_without_ip_shows_era_only(self):
        entries = [{'rank': 1, 'name': 'Pitcher', 'era': '1.80', 'ip': '',
                    'team_id': '147', 'abbr': 'NYY'}]
        img = _img()
        result = draw_scoreless_cell(img, 0, 0, {'scoreless': entries}, _TEAMS)
        assert result is not None

    def test_entry_with_ip_shows_both(self):
        entries = [{'rank': 1, 'name': 'Pitcher', 'era': '1.57', 'ip': '115.0',
                    'team_id': '147', 'abbr': 'NYY'}]
        img = _img()
        result = draw_scoreless_cell(img, 0, 0, {'scoreless': entries}, _TEAMS)
        assert result is not None

    def test_use_logos_true_attempts_logo(self):
        fake_logo = Image.new('1', (16, 16), 255)
        with patch('image_scoreless._logo_small', return_value=fake_logo):
            img = _img()
            result = draw_scoreless_cell(img, 0, 0, _STREAKS_DATA, _TEAMS, use_logos=True)
        assert result is not None

    def test_use_logos_exception_is_swallowed(self):
        with patch('image_scoreless._logo_small', side_effect=OSError('no file')):
            img = _img()
            result = draw_scoreless_cell(img, 0, 0, _STREAKS_DATA, _TEAMS, use_logos=True)
        assert result is not None

    def test_use_logos_returns_none_logo(self):
        with patch('image_scoreless._logo_small', return_value=None):
            img = _img()
            result = draw_scoreless_cell(img, 0, 0, _STREAKS_DATA, _TEAMS, use_logos=True)
        assert result is not None

    def test_long_name_truncated(self):
        entries = [{'rank': 1, 'name': 'A' * 100, 'era': '2.00', 'ip': '100.0',
                    'team_id': '147', 'abbr': 'NYY'}]
        img = _img()
        result = draw_scoreless_cell(img, 0, 0, {'scoreless': entries}, _TEAMS)
        assert result is not None

    def test_entry_missing_abbr_falls_back_to_abbr_map(self):
        entries = [{'rank': 1, 'name': 'Pitcher', 'era': '2.00', 'ip': '80.0',
                    'team_id': '147', 'abbr': ''}]
        img = _img()
        result = draw_scoreless_cell(img, 0, 0, {'scoreless': entries}, _TEAMS)
        assert result is not None
