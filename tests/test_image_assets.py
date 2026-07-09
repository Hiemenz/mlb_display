"""
Coverage-focused unit tests for src/image_assets.py.

Every network path (logo CDN, emoji CDN) and every file-system path that would
otherwise touch pic/logos/*.png or pic/emojis/*.png is mocked or redirected to
a pytest tmp_path fixture. Nothing here is allowed to perform a real HTTP
request or write into the repo's committed asset directories.
"""

from unittest.mock import patch, MagicMock

import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")

import image_assets


# ---------------------------------------------------------------------------
# _get_logo_invert_config
# ---------------------------------------------------------------------------

def test_get_logo_invert_config_malformed_json_falls_back_to_empty_dict(monkeypatch):
    """Get logo invert config malformed json falls back to empty dict."""
    monkeypatch.setattr(image_assets, '_logo_invert_config', None)
    with patch('builtins.open', side_effect=OSError('boom')):
        result = image_assets._get_logo_invert_config()
    assert result == {}


# ---------------------------------------------------------------------------
# _try_download_logo
# ---------------------------------------------------------------------------

def _fake_ctx_response(data=b'FAKEPNGDATA'):
    """Fake ctx response."""
    m = MagicMock()
    m.__enter__.return_value = m
    m.read.return_value = data
    return m


def test_try_download_logo_digit_abbr_skips_download():
    """Try download logo digit abbr skips download."""
    assert image_assets._try_download_logo('123') is False


def test_try_download_logo_t_prefixed_abbr_skips_download():
    """Try download logo t prefixed abbr skips download."""
    assert image_assets._try_download_logo('T461') is False


@needs_pil
def test_try_download_logo_espn_mlb_success(monkeypatch, tmp_path):
    """Try download logo espn mlb success."""
    monkeypatch.setattr(image_assets, 'logodir', str(tmp_path))
    with patch('urllib.request.urlopen', return_value=_fake_ctx_response()):
        result = image_assets._try_download_logo('ZZFAKEMLB')
    assert result is True
    assert (tmp_path / 'ZZFAKEMLB.png').exists()


@needs_pil
def test_try_download_logo_svg_fallback_success(monkeypatch, tmp_path):
    """First (ESPN MLB) CDN fails; falls through to the mlbstatic SVG CDN,
    which succeeds for a numeric team_id. cairosvg.svg2png is mocked so no
    real SVG parsing is needed."""
    monkeypatch.setattr(image_assets, 'logodir', str(tmp_path))

    def fake_urlopen(url, timeout=5):
        """Fake urlopen."""
        if 'mlbstatic' in url:
            m = MagicMock()
            m.read.return_value = b'<svg></svg>'
            return m
        raise OSError('espn down')

    with patch('urllib.request.urlopen', side_effect=fake_urlopen), \
         patch('cairosvg.svg2png') as mock_svg2png:
        result = image_assets._try_download_logo('ZZFAKEMILB', team_id=777001)

    assert result is True
    mock_svg2png.assert_called_once()


@needs_pil
def test_try_download_logo_wbc_countries_fallback_success(monkeypatch, tmp_path):
    """ESPN MLB CDN fails, no team_id (SVG branch skipped), falls through to
    the ESPN countries CDN for a known WBC abbreviation."""
    monkeypatch.setattr(image_assets, 'logodir', str(tmp_path))

    def fake_urlopen(url, timeout=5):
        """Fake urlopen."""
        if 'countries' in url:
            return _fake_ctx_response()
        raise OSError('espn mlb down')

    with patch('urllib.request.urlopen', side_effect=fake_urlopen):
        result = image_assets._try_download_logo('USA')

    assert result is True
    assert (tmp_path / 'USA.png').exists()


@needs_pil
def test_try_download_logo_all_sources_fail_returns_false(monkeypatch, tmp_path):
    """A WBC abbreviation whose ESPN MLB CDN and countries CDN calls both
    fail exercises the countries-CDN except branch and the final `return
    False`."""
    monkeypatch.setattr(image_assets, 'logodir', str(tmp_path))
    with patch('urllib.request.urlopen', side_effect=OSError('network down')):
        result = image_assets._try_download_logo('USA')
    assert result is False
    assert not (tmp_path / 'USA.png').exists()


@needs_pil
def test_try_download_logo_svg_exception_falls_through_to_false(monkeypatch, tmp_path):
    """ESPN MLB CDN fails and the mlbstatic SVG CDN also raises — the SVG
    try/except swallows it and, for a non-WBC abbreviation, execution falls
    all the way through to `return False`."""
    monkeypatch.setattr(image_assets, 'logodir', str(tmp_path))
    with patch('urllib.request.urlopen', side_effect=OSError('all cdns down')):
        result = image_assets._try_download_logo('ZZNONWBC', team_id=777002)
    assert result is False


# ---------------------------------------------------------------------------
# _load_logo_gray
# ---------------------------------------------------------------------------

@needs_pil
def test_load_logo_gray_returns_emoji_early(monkeypatch):
    """When the abbr has an emoji mapping, _load_logo_gray defers to
    _load_emoji_gray and returns its result directly without touching the
    logo cache/filesystem at all."""
    fake_emoji_img = Image.new('L', (10, 10), 50)
    monkeypatch.setattr(image_assets, '_load_emoji_gray', lambda abbr: fake_emoji_img)
    result = image_assets._load_logo_gray('ZZEMOJIABBR', 900001)
    assert result is fake_emoji_img


@needs_pil
def test_load_logo_gray_darken_white_branch(monkeypatch, tmp_path):
    """Logos flagged in invert_config['darken_white'] get near-white visible
    pixels turned black so they remain legible on e-ink."""
    monkeypatch.setattr(image_assets, 'logodir', str(tmp_path))
    monkeypatch.setattr(image_assets, '_load_emoji_gray', lambda abbr: None)
    monkeypatch.setattr(
        image_assets, '_get_logo_invert_config',
        lambda: {'ZZDARKEN': False, 'darken_white': ['ZZDARKEN']},
    )
    img = Image.new('RGBA', (4, 4), (0, 100, 200, 255))
    img.putpixel((0, 0), (255, 255, 255, 255))
    img.putpixel((1, 0), (250, 250, 250, 255))
    img.save(tmp_path / 'ZZDARKEN.png')

    result = image_assets._load_logo_gray('ZZDARKEN', 900002)

    assert result is not None
    assert result.mode == 'L'


@needs_pil
def test_load_logo_gray_corrupt_file_returns_none(monkeypatch, tmp_path):
    """Load logo gray corrupt file returns none."""
    monkeypatch.setattr(image_assets, 'logodir', str(tmp_path))
    monkeypatch.setattr(image_assets, '_load_emoji_gray', lambda abbr: None)
    (tmp_path / 'ZZCORRUPT.png').write_bytes(b'not a real png')

    result = image_assets._load_logo_gray('ZZCORRUPT', 900003)

    assert result is None


@needs_pil
def test_load_logo_gray_result_is_cached(monkeypatch, tmp_path):
    """Second call with the same (abbr, team_id) hits the in-memory cache
    instead of re-reading the filesystem."""
    monkeypatch.setattr(image_assets, 'logodir', str(tmp_path))
    monkeypatch.setattr(image_assets, '_load_emoji_gray', lambda abbr: None)
    img = Image.new('RGBA', (4, 4), (10, 20, 30, 255))
    img.save(tmp_path / 'ZZCACHEHIT.png')

    first = image_assets._load_logo_gray('ZZCACHEHIT', 900004)
    second = image_assets._load_logo_gray('ZZCACHEHIT', 900004)

    assert first is not None
    assert second is first


@needs_pil
def test_load_logo_gray_triggers_download_when_neither_file_exists(monkeypatch, tmp_path):
    """When neither {team_id}.png nor {abbr}.png exists yet, _load_logo_gray
    calls _try_download_logo (mocked here, never hitting the real network)."""
    monkeypatch.setattr(image_assets, 'logodir', str(tmp_path))
    monkeypatch.setattr(image_assets, '_load_emoji_gray', lambda abbr: None)
    mock_download = MagicMock(return_value=False)
    monkeypatch.setattr(image_assets, '_try_download_logo', mock_download)

    result = image_assets._load_logo_gray('ZZMISSING', 900005)

    mock_download.assert_called_once_with('ZZMISSING', team_id=900005)
    assert result is None


@needs_pil
def test_load_logo_gray_brightness_fallback_inverts_bright_logo(monkeypatch, tmp_path):
    """When the abbr isn't in the committed invert_config, brightness
    detection kicks in: a predominantly bright logo gets inverted."""
    monkeypatch.setattr(image_assets, 'logodir', str(tmp_path))
    monkeypatch.setattr(image_assets, '_load_emoji_gray', lambda abbr: None)
    monkeypatch.setattr(image_assets, '_get_logo_invert_config', lambda: {})
    img = Image.new('RGBA', (4, 4), (250, 250, 250, 255))
    img.save(tmp_path / 'ZZBRIGHTLOGO.png')

    result = image_assets._load_logo_gray('ZZBRIGHTLOGO', 900006)

    assert result is not None
    assert result.mode == 'L'


# ---------------------------------------------------------------------------
# _logo_small
# ---------------------------------------------------------------------------

@needs_pil
def test_logo_small_returns_none_when_no_logo(monkeypatch):
    """Logo small returns none when no logo."""
    monkeypatch.setattr(image_assets, '_load_logo_gray', lambda abbr, team_id: None)
    assert image_assets._logo_small('ZZ', 1) is None


@needs_pil
def test_logo_small_returns_1bit_image(monkeypatch):
    """Logo small returns 1bit image."""
    fake = Image.new('L', (60, 60), 90)
    monkeypatch.setattr(image_assets, '_load_logo_gray', lambda abbr, team_id: fake)
    result = image_assets._logo_small('ZZ', 1, size=28)
    assert result is not None
    assert result.mode == '1'


# ---------------------------------------------------------------------------
# _paste_logo
# ---------------------------------------------------------------------------

@needs_pil
def test_paste_logo_pastes_dark_pixels_only():
    """Paste logo pastes dark pixels only."""
    canvas = Image.new('1', (10, 10), 255)  # all white
    logo = Image.new('L', (4, 4), 0).convert('1')  # all black

    image_assets._paste_logo(canvas, logo, (2, 2))

    # Black logo -> inverted mask is fully opaque -> the black pixels paste through.
    assert canvas.getpixel((3, 3)) == 0
    # Untouched area remains white.
    assert canvas.getpixel((0, 0)) == 255


# ---------------------------------------------------------------------------
# _logo_ghost
# ---------------------------------------------------------------------------

@needs_pil
def test_logo_ghost_returns_none_when_no_logo(monkeypatch):
    """Logo ghost returns none when no logo."""
    monkeypatch.setattr(image_assets, '_load_logo_gray', lambda abbr, team_id: None)
    assert image_assets._logo_ghost('ZZ', 1) is None


@needs_pil
def test_logo_ghost_returns_1bit_watermark(monkeypatch):
    """Logo ghost returns 1bit watermark."""
    fake = Image.new('L', (200, 200), 100)
    monkeypatch.setattr(image_assets, '_load_logo_gray', lambda abbr, team_id: fake)
    result = image_assets._logo_ghost('ZZ', 1, size=50)
    assert result is not None
    assert result.mode == '1'


# ---------------------------------------------------------------------------
# _emoji_codepoint
# ---------------------------------------------------------------------------

def test_emoji_codepoint_simple_char():
    """Emoji codepoint simple char."""
    assert image_assets._emoji_codepoint('⚡') == '26a1'


def test_emoji_codepoint_strips_variation_selector():
    """Emoji codepoint strips variation selector."""
    result = image_assets._emoji_codepoint('❤️')
    assert result == format(ord('❤'), 'x')


def test_emoji_codepoint_compound_emoji_joins_with_dash():
    """Emoji codepoint compound emoji joins with dash."""
    # man + ZWJ + woman: multiple non-fe0f codepoints joined by '-'
    s = '\U0001F468‍\U0001F469'
    result = image_assets._emoji_codepoint(s)
    assert '-' in result
    assert result == f"{ord(chr(0x1F468)):x}-{ord(chr(0x200d)):x}-{ord(chr(0x1F469)):x}"


# ---------------------------------------------------------------------------
# _try_download_emoji
# ---------------------------------------------------------------------------

@needs_pil
def test_try_download_emoji_success(monkeypatch, tmp_path):
    """Try download emoji success."""
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))
    with patch('urllib.request.urlopen', return_value=_fake_ctx_response()):
        result = image_assets._try_download_emoji('⚡')
    assert result is True
    assert (tmp_path / '26a1.png').exists()


@needs_pil
def test_try_download_emoji_failure_returns_false(monkeypatch, tmp_path):
    """Try download emoji failure returns false."""
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))
    with patch('urllib.request.urlopen', side_effect=OSError('no network')):
        result = image_assets._try_download_emoji('⚡')
    assert result is False


# ---------------------------------------------------------------------------
# _get_team_emojis
# ---------------------------------------------------------------------------

def test_get_team_emojis_loads_from_config(monkeypatch):
    """Get team emojis loads from config."""
    monkeypatch.setattr(image_assets, '_team_emojis', None)
    with patch('util.load_yaml_file', return_value={'team_emojis': {'ZZCFG': '⚡'}}):
        result = image_assets._get_team_emojis()
    assert result == {'ZZCFG': '⚡'}


# ---------------------------------------------------------------------------
# _load_emoji_gray
# ---------------------------------------------------------------------------

@needs_pil
def test_load_emoji_gray_no_mapping_returns_none(monkeypatch):
    """Load emoji gray no mapping returns none."""
    monkeypatch.setattr(image_assets, '_team_emojis', {})
    result = image_assets._load_emoji_gray('ZZNOEMOJIMAP')
    assert result is None


@needs_pil
def test_load_emoji_gray_result_is_cached(monkeypatch, tmp_path):
    """Load emoji gray result is cached."""
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))
    monkeypatch.setattr(image_assets, '_team_emojis', {'ZZCACHEEMOJI': '\U0001F386'})
    codepoint = image_assets._emoji_codepoint('\U0001F386')
    Image.new('RGBA', (72, 72), (40, 40, 40, 255)).save(tmp_path / f'{codepoint}.png')

    first = image_assets._load_emoji_gray('ZZCACHEEMOJI')
    second = image_assets._load_emoji_gray('ZZCACHEEMOJI')

    assert first is not None
    assert second is first


@needs_pil
def test_load_emoji_gray_downloads_when_file_missing(monkeypatch, tmp_path):
    """No cached PNG yet: _load_emoji_gray downloads it (mocked CDN) and
    then loads the freshly written file."""
    import io
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))
    monkeypatch.setattr(image_assets, '_team_emojis', {'ZZDOWNLOADEMOJI': '\U0001F387'})

    def fake_urlopen(url, timeout=5):
        """Fake urlopen."""
        buf = io.BytesIO()
        Image.new('RGBA', (72, 72), (60, 60, 60, 255)).save(buf, format='PNG')
        m = MagicMock()
        m.__enter__.return_value = m
        m.read.return_value = buf.getvalue()
        return m

    with patch('urllib.request.urlopen', side_effect=fake_urlopen):
        result = image_assets._load_emoji_gray('ZZDOWNLOADEMOJI')

    assert result is not None
    codepoint = image_assets._emoji_codepoint('\U0001F387')
    assert (tmp_path / f'{codepoint}.png').exists()


@needs_pil
def test_load_emoji_gray_dark_image_no_invert(monkeypatch, tmp_path):
    """Load emoji gray dark image no invert."""
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))
    monkeypatch.setattr(image_assets, '_team_emojis', {'ZZDARKEMOJI': '⚡'})
    codepoint = image_assets._emoji_codepoint('⚡')
    Image.new('RGBA', (72, 72), (20, 20, 20, 255)).save(tmp_path / f'{codepoint}.png')

    result = image_assets._load_emoji_gray('ZZDARKEMOJI')

    assert result is not None
    assert result.mode == 'L'


@needs_pil
def test_load_emoji_gray_bright_image_gets_inverted(monkeypatch, tmp_path):
    """Load emoji gray bright image gets inverted."""
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))
    monkeypatch.setattr(image_assets, '_team_emojis', {'ZZBRIGHTEMOJI': '\U0001F320'})
    codepoint = image_assets._emoji_codepoint('\U0001F320')
    Image.new('RGBA', (72, 72), (250, 250, 250, 255)).save(tmp_path / f'{codepoint}.png')

    result = image_assets._load_emoji_gray('ZZBRIGHTEMOJI')

    assert result is not None
    assert result.mode == 'L'


@needs_pil
def test_load_emoji_gray_corrupt_file_returns_none(monkeypatch, tmp_path):
    """Load emoji gray corrupt file returns none."""
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))
    monkeypatch.setattr(image_assets, '_team_emojis', {'ZZCORRUPTEMOJI': '\U0001F3AF'})
    codepoint = image_assets._emoji_codepoint('\U0001F3AF')
    (tmp_path / f'{codepoint}.png').write_bytes(b'not a real png')

    result = image_assets._load_emoji_gray('ZZCORRUPTEMOJI')

    assert result is None


# ---------------------------------------------------------------------------
# _load_char_emoji
# ---------------------------------------------------------------------------

@needs_pil
def test_load_char_emoji_success_resizes(monkeypatch, tmp_path):
    """Load char emoji success resizes."""
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))
    codepoint = image_assets._emoji_codepoint('\U0001F525')
    Image.new('RGBA', (72, 72), (10, 10, 10, 255)).save(tmp_path / f'{codepoint}.png')

    result = image_assets._load_char_emoji('\U0001F525', size=16)

    assert result is not None
    assert result.size == (16, 16)


@needs_pil
def test_load_char_emoji_bright_image_gets_inverted(monkeypatch, tmp_path):
    """Load char emoji bright image gets inverted."""
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))
    codepoint = image_assets._emoji_codepoint('\U0001F31F')
    Image.new('RGBA', (72, 72), (250, 250, 250, 255)).save(tmp_path / f'{codepoint}.png')

    result = image_assets._load_char_emoji('\U0001F31F', size=16)

    assert result is not None
    assert result.size == (16, 16)


@needs_pil
def test_load_char_emoji_result_is_cached(monkeypatch, tmp_path):
    """Load char emoji result is cached."""
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))
    codepoint = image_assets._emoji_codepoint('\U0001F3B0')
    Image.new('RGBA', (72, 72), (5, 5, 5, 255)).save(tmp_path / f'{codepoint}.png')

    first = image_assets._load_char_emoji('\U0001F3B0', size=16)
    second = image_assets._load_char_emoji('\U0001F3B0', size=16)

    assert first is not None
    assert second is first


@needs_pil
def test_load_char_emoji_downloads_when_file_missing(monkeypatch, tmp_path):
    """No cached PNG yet: _load_char_emoji downloads it (mocked CDN) and
    then resizes the freshly written file."""
    import io
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))

    def fake_urlopen(url, timeout=5):
        """Fake urlopen."""
        buf = io.BytesIO()
        Image.new('RGBA', (72, 72), (70, 70, 70, 255)).save(buf, format='PNG')
        m = MagicMock()
        m.__enter__.return_value = m
        m.read.return_value = buf.getvalue()
        return m

    with patch('urllib.request.urlopen', side_effect=fake_urlopen):
        result = image_assets._load_char_emoji('\U0001F388', size=16)

    assert result is not None
    assert result.size == (16, 16)


@needs_pil
def test_load_char_emoji_download_fails_returns_none(monkeypatch, tmp_path):
    """Load char emoji download fails returns none."""
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))
    with patch('urllib.request.urlopen', side_effect=OSError('no network')):
        result = image_assets._load_char_emoji('\U0001F3B2', size=16)
    assert result is None


@needs_pil
def test_load_char_emoji_corrupt_file_returns_none(monkeypatch, tmp_path):
    """Load char emoji corrupt file returns none."""
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))
    codepoint = image_assets._emoji_codepoint('\U0001F3B3')
    (tmp_path / f'{codepoint}.png').write_bytes(b'garbage')

    result = image_assets._load_char_emoji('\U0001F3B3', size=16)

    assert result is None


# ---------------------------------------------------------------------------
# _load_codepoint_ghost
# ---------------------------------------------------------------------------

@needs_pil
def test_load_codepoint_ghost_downloads_and_renders(monkeypatch, tmp_path):
    """Load codepoint ghost downloads and renders."""
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))
    codepoint = 'deadbeef1'

    def fake_urlopen(url, timeout=5):
        """Fake urlopen."""
        import io
        buf = io.BytesIO()
        Image.new('RGBA', (72, 72), (30, 30, 30, 255)).save(buf, format='PNG')
        m = MagicMock()
        m.__enter__.return_value = m
        m.read.return_value = buf.getvalue()
        return m

    with patch('urllib.request.urlopen', side_effect=fake_urlopen):
        result = image_assets._load_codepoint_ghost(codepoint, size=32)

    assert result is not None
    assert (tmp_path / f'{codepoint}.png').exists()


@needs_pil
def test_load_codepoint_ghost_download_fails_returns_none(monkeypatch, tmp_path):
    """Load codepoint ghost download fails returns none."""
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))
    with patch('urllib.request.urlopen', side_effect=OSError('no network')):
        result = image_assets._load_codepoint_ghost('nonexistentcp', size=32)
    assert result is None
    assert not (tmp_path / 'nonexistentcp.png').exists()


@needs_pil
def test_load_codepoint_ghost_corrupt_file_returns_none(monkeypatch, tmp_path):
    """Load codepoint ghost corrupt file returns none."""
    monkeypatch.setattr(image_assets, 'emojidir', str(tmp_path))
    codepoint = 'corruptcp'
    (tmp_path / f'{codepoint}.png').write_bytes(b'not valid png data')

    result = image_assets._load_codepoint_ghost(codepoint, size=32)

    assert result is None
