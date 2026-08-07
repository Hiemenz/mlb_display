"""Tests for image_news.draw_news_cell."""
from PIL import Image

from image_news import draw_news_cell, _wrap


def _make_image():
    return Image.new('1', (800, 480), 255)


SAMPLE_ARTICLES = [
    {'headline': 'Yankees crush Red Sox in extra innings thriller', 'published': ''},
    {'headline': 'Judge hits two-run homer', 'published': ''},
    {'headline': 'Bullpen struggles continue for NL teams', 'published': ''},
]

SAMPLE_NEWS_DATA = {'articles': SAMPLE_ARTICLES, 'fetched_at': 0.0, 'team': 'NYY'}


# ---------------------------------------------------------------------------
# _wrap helper
# ---------------------------------------------------------------------------

class TestWrap:
    def _font(self, char_px=7):
        """Stub font whose getlength == len(text) * char_px."""
        class _StubFont:
            def getlength(self, text):
                return len(text) * char_px
        return _StubFont()

    def test_single_short_word_is_one_line(self):
        assert _wrap(self._font(), 'Hello', 200) == ['Hello']

    def test_wraps_at_max_width(self):
        font = self._font(char_px=10)
        # "Hello World" = 11 chars * 10 = 110px → fits in 120; one line
        lines = _wrap(font, 'Hello World', 120)
        assert lines == ['Hello World']

    def test_breaks_into_two_lines(self):
        font = self._font(char_px=10)
        # max_w=50 → each word is ~5 chars × 10 = 50px; long words force splits
        lines = _wrap(font, 'Alpha Beta Gamma', 50)
        assert len(lines) >= 2

    def test_empty_string_returns_empty(self):
        assert _wrap(self._font(), '', 200) == []


# ---------------------------------------------------------------------------
# draw_news_cell
# ---------------------------------------------------------------------------

class TestDrawNewsCell:
    def test_renders_with_dict_news_data(self):
        img = _make_image()
        result = draw_news_cell(img, 32, 30, SAMPLE_NEWS_DATA, None)
        assert result is not None

    def test_renders_with_list_news_data(self):
        img = _make_image()
        result = draw_news_cell(img, 32, 30, SAMPLE_ARTICLES, None)
        assert result is not None

    def test_renders_with_empty_articles(self):
        img = _make_image()
        result = draw_news_cell(img, 32, 30, {'articles': []}, None)
        assert result is not None

    def test_renders_with_none_news_data(self):
        img = _make_image()
        result = draw_news_cell(img, 32, 30, None, None)
        assert result is not None

    def test_renders_with_empty_list(self):
        img = _make_image()
        result = draw_news_cell(img, 32, 30, [], None)
        assert result is not None

    def test_returns_image_object(self):
        img = _make_image()
        result = draw_news_cell(img, 0, 0, SAMPLE_NEWS_DATA, None)
        assert isinstance(result, Image.Image)

    def test_very_long_headline_does_not_crash(self):
        img = _make_image()
        long = [{'headline': 'A' * 200, 'published': ''}]
        result = draw_news_cell(img, 32, 30, {'articles': long}, None)
        assert result is not None

    def test_many_articles_does_not_overflow(self):
        img = _make_image()
        many = [{'headline': f'Headline number {i}', 'published': ''} for i in range(30)]
        result = draw_news_cell(img, 32, 30, {'articles': many}, None)
        assert result is not None

    def test_article_with_missing_headline_key_skipped(self):
        img = _make_image()
        articles = [{'published': ''}, {'headline': 'Valid headline', 'published': ''}]
        result = draw_news_cell(img, 32, 30, articles, None)
        assert result is not None

    def test_string_articles_accepted(self):
        img = _make_image()
        result = draw_news_cell(img, 32, 30, ['Headline one', 'Headline two'], None)
        assert result is not None

    def test_use_logos_flag_accepted(self):
        img = _make_image()
        result = draw_news_cell(img, 32, 30, SAMPLE_NEWS_DATA, {}, use_logos=True)
        assert result is not None

    def test_multi_line_headline_inner_break(self):
        """Inner loop break is hit when a wrapped line would exceed body_bottom."""
        img = _make_image()
        # Pack enough long headlines to fill the body so the inner per-line
        # y-overflow check fires during the multi-line wrap of a later headline.
        articles = [{'headline': f'Story word word word word word word word {i}', 'published': ''}
                    for i in range(20)]
        result = draw_news_cell(img, 32, 30, {'articles': articles}, None)
        assert result is not None
