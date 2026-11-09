"""Tests for fetch_comic (selection, local source) and image_comic (render, hook)."""
from datetime import date, datetime
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

import fetch_comic as fc
import image_comic as ic

NOW = datetime(2026, 11, 7, 10, 40)   # minute 40 → comic half-hour


def placeholder(aspect, height=200, panels=4):
    """A generated stand-in strip (never real comic art)."""
    w = round(height * aspect)
    im = Image.new('L', (w, height), 245)
    d = ImageDraw.Draw(im)
    pw = w / panels
    for i in range(panels):
        d.rectangle([i * pw + 4, 4, (i + 1) * pw - 4, height - 5], outline=20, width=3)
        d.ellipse([i * pw + pw * 0.3, height * 0.25, i * pw + pw * 0.7, height * 0.65], outline=20, width=3)
    d.text((8, height - 20), 'PLACEHOLDER', fill=20)
    return im


class FakeSource:
    def __init__(self, dates, images=None):
        self._dates, self._images = dates, images or {}

    def dates_for(self, month, day):
        return [d for d in self._dates if (d.month, d.day) == (month, day)]

    def load(self, when):
        return self._images.get(when)


# --- LocalCacheSource ---------------------------------------------------------

def _write(path, aspect=3.5):
    path.parent.mkdir(parents=True, exist_ok=True)
    placeholder(aspect, 40).save(path)


def test_local_source_lists_and_loads(tmp_path):
    root = tmp_path / 'peanuts'
    _write(root / '1963-11-07.png')
    _write(root / '1971-11-07.png')
    _write(root / '1971-11-08.png')
    _write(root / '1999-02-29.png')           # not a real date → skipped
    (root / 'notes.txt').write_text('x')
    (root / '1980-11-07.png').write_bytes(b'not an image')
    src = fc.LocalCacheSource('peanuts', root=str(tmp_path))
    assert src.dates_for(11, 7) == [date(1963, 11, 7), date(1971, 11, 7), date(1980, 11, 7)]
    assert src.dates_for(2, 29) == []
    assert src.load(date(1963, 11, 7)).mode == 'L'
    assert src.load(date(1980, 11, 7)) is None      # unreadable
    assert src.load(date(1950, 1, 1)) is None       # missing


def test_local_source_missing_directory(tmp_path):
    src = fc.LocalCacheSource('nope', root=str(tmp_path))
    assert src.dates_for(11, 7) == []


# --- selection ------------------------------------------------------------------

def test_pick_index_one_per_day_is_stable_and_in_range():
    a = fc.pick_index(50, date(2026, 11, 7), datetime(2026, 11, 7, 1, 0))
    b = fc.pick_index(50, date(2026, 11, 7), datetime(2026, 11, 7, 23, 59))
    assert a == b and 0 <= a < 50
    assert fc.pick_index(0, date(2026, 11, 7), NOW) == 0
    days = {fc.pick_index(50, date(2026, 11, d), NOW) for d in range(1, 29)}
    assert len(days) > 5     # different days pick different strips


def test_pick_index_rotates_on_the_clock():
    kw = dict(count=5, today=date(2026, 11, 7), rotate_hours=2)
    h0 = fc.pick_index(now=datetime(2026, 11, 7, 10, 0), **kw)
    assert fc.pick_index(now=datetime(2026, 11, 7, 11, 59), **kw) == h0
    assert fc.pick_index(now=datetime(2026, 11, 7, 12, 0), **kw) == (h0 + 1) % 5


def test_current_strip_carries_original_date_and_skips_bad_files():
    ds = [date(1963, 11, 7), date(1971, 11, 7), date(1980, 11, 7)]
    imgs = {d: placeholder(3.5) for d in ds}
    s = fc.current_strip({}, NOW, FakeSource(ds, imgs))
    assert s.date in ds and s.total == 3 and s.years == [1963, 1971, 1980]
    assert ds[s.position] == s.date
    only_last = FakeSource(ds, {ds[2]: placeholder(3.5)})       # others unreadable
    assert fc.current_strip({}, NOW, only_last).date == ds[2]
    assert fc.current_strip({}, NOW, FakeSource(ds, {})) is None
    assert fc.current_strip({}, NOW, FakeSource([], {})) is None


def test_current_strip_default_source_is_local_cache(tmp_path):
    _write(tmp_path / 'peanuts' / '1963-11-07.png')
    with patch('fetch_comic.COMICS_DIR', str(tmp_path)):
        assert fc.current_strip({}, NOW).date == date(1963, 11, 7)


# --- rendering: every strip shape ----------------------------------------------

SHAPES = {'daily': 3.5, 'wide': 4.4, 'sunday': 1.6, 'square': 1.0, 'tall': 0.55}
PANEL = 800 * 480


def _strip(aspect, years=(1963, 1971, 1999), idx=0):
    return fc.Strip(date(years[idx], 11, 7), placeholder(aspect), idx, len(years), list(years))


@pytest.mark.parametrize('name,aspect', SHAPES.items())
def test_every_shape_renders_and_fills_what_the_panel_allows(name, aspect):
    x, y, w, h = ic.strip_layout((round(200 * aspect), 200))
    assert ic._GUT <= x and x + w <= 800 and ic._MARGIN <= y and y + h <= 480 - ic._MARGIN
    # as large as the panel allows: it touches the full usable width or height
    assert w >= 800 - ic._GUT - ic._MARGIN - 3 or h >= 480 - 2 * ic._MARGIN - 3
    # …without distortion
    assert abs(w / h - aspect) / aspect < 0.02
    img = ic.draw_comic_screen(_strip(aspect), {})
    assert img.size == (800, 480) and img.mode == '1'


def test_strip_covers_majority_of_panel_for_sunday_style_strips():
    _, _, w, h = ic.strip_layout((round(200 * 1.6), 200))
    assert w * h > PANEL / 2
    # a 3.5:1 daily can't exceed the width limit (~49%), but spans the whole width
    _, _, w, h = ic.strip_layout((700, 200))
    assert w >= 776 and w * h > PANEL * 0.44


def test_wide_strip_is_centred_vertically():
    x, y, w, h = ic.strip_layout((880, 200))
    top, bot = ic._MARGIN, 480 - ic._MARGIN
    assert abs((y - top) - (bot - (y + h))) <= 1


def test_dark_mode_keeps_strip_positive_and_page_dark():
    s = _strip(1.6)
    x, y, w, h = ic.strip_layout(s.image.size)
    light = ic.draw_comic_screen(s, {})
    dark = ic.draw_comic_screen(s, {'dark_mode': True})
    probe = (x + 30, y + 30)
    assert light.getpixel(probe) == dark.getpixel(probe)
    assert dark.getpixel((2, 100)) == 0 and light.getpixel((2, 100)) == 1


def test_single_strip_and_single_year_render():
    one = fc.Strip(date(1963, 11, 7), placeholder(3.5), 0, 1, [1963])
    assert ic.draw_comic_screen(one, {}).size == (800, 480)


def test_timeline_skips_tiny_span():
    d = ImageDraw.Draw(Image.new('1', (800, 480), 1))
    ic._timeline(d, [1963], 1963, 9, 100, 110)            # too short → no-op


# --- idle hook -------------------------------------------------------------------

def _kw(**over):
    base = dict(source=FakeSource([date(1963, 11, 7)], {date(1963, 11, 7): placeholder(3.5)}),
                replay_running=lambda pid: False, load=lambda name: None)
    base.update(over)
    return base


def test_idle_hook_gates():
    on = {'idle_comic_rotation': True}
    assert ic.comic_idle_image({}, NOW, **_kw()) is None                       # off by default
    assert ic.comic_idle_image(on, NOW, **_kw()).size == (800, 480)
    assert ic.comic_idle_image(on, datetime(2026, 11, 7, 10, 5), **_kw()) is None   # moves' half-hour
    assert ic.comic_idle_image(dict(on, comic_idle_blocks=[0]),
                               datetime(2026, 11, 7, 10, 5), **_kw()).size == (800, 480)
    assert ic.comic_idle_image(on, NOW, **_kw(replay_running=lambda pid: True)) is None
    assert ic.comic_idle_image(on, NOW, **_kw(source=FakeSource([]))) is None


def test_idle_hook_default_collaborators():
    with patch('offseason_replay._replay_running', return_value=False), \
         patch('util.load_json_file', return_value=None):
        img = ic.comic_idle_image({'idle_comic_rotation': True}, NOW, source=_kw()['source'])
    assert img is not None


def test_main_idle_uses_comic_and_survives_failure():
    import main
    cfg = {'timezone': 'UTC', 'idle_comic_rotation': True}
    shown = []
    with patch('main.datetime') as dt, \
         patch('main.load_json_file', return_value=None), \
         patch('main.send_to_display', side_effect=lambda *a, **k: shown.append(a)), \
         patch('refresh_tracker.needs_full_refresh', return_value=True), \
         patch('PIL.Image.Image.save'), \
         patch('image_comic.comic_idle_image', return_value=Image.new('1', (800, 480), 1)):
        dt.now.return_value = NOW
        main._show_idle_screen(cfg)
    assert shown
    with patch('main.datetime') as dt, \
         patch('main.load_json_file', return_value=None), \
         patch('main._render_next_games', side_effect=RuntimeError('reached idle')), \
         patch('image_comic.comic_idle_image', side_effect=OSError('boom')), \
         patch('offseason_replay.maybe_start_replay', return_value=False):
        dt.now.return_value = datetime(2026, 7, 1, 12, 5)   # block 0, in season
        with pytest.raises(RuntimeError, match='reached idle'):
            main._show_idle_screen(cfg)


def test_all_blocks_ignores_the_block_list():
    on = {'idle_comic_rotation': True}
    even = datetime(2026, 11, 7, 10, 5)
    assert ic.comic_idle_image(on, even, **_kw()) is None
    assert ic.comic_idle_image(on, even, all_blocks=True, **_kw()).size == (800, 480)
    assert ic.comic_idle_image(on, even, all_blocks=True,
                               **_kw(replay_running=lambda pid: True)) is None   # replay still wins


def _idle(moves_image, has_moves, now, comic_cfg=True):
    """Run main._show_idle_screen in the off-season; return the comic hook's mock."""
    import main
    cfg = {'timezone': 'UTC', 'idle_comic_rotation': comic_cfg}
    with patch('main.datetime') as dt, \
         patch('main.load_json_file', return_value=None), \
         patch('main.send_to_display'), \
         patch('refresh_tracker.needs_full_refresh', return_value=True), \
         patch('PIL.Image.Image.save'), \
         patch('offseason_replay.is_offseason', return_value=True), \
         patch('image_free_agents.free_agent_idle_image', return_value=moves_image), \
         patch('image_free_agents.has_moves', return_value=has_moves), \
         patch('image_comic.comic_idle_image', return_value=Image.new('1', (800, 480), 1)) as comic:
        dt.now.return_value = now
        main._show_idle_screen(cfg)
    return comic


def test_offseason_rotation_moves_first_then_comic():
    img = Image.new('1', (800, 480), 0)
    # moves have this block: the comic is not consulted
    assert not _idle(img, True, NOW).called
    # odd block with moves available: comic runs, but only on its own blocks
    assert _idle(None, True, NOW).call_args.kwargs['all_blocks'] is False
    # nothing to show: the comic gets every off-season block
    assert _idle(None, False, NOW).call_args.kwargs['all_blocks'] is True


def test_no_title_bar_and_border_is_trimmed():
    from PIL import Image, ImageDraw
    img = ic.draw_comic_screen(_strip(3.5), {})
    assert all(img.getpixel((x, 2)) == 1 for x in range(0, 800, 7))   # no black bar across the top
    # a strip with a thick white scan border loses it, so the art gets bigger
    art = Image.new('L', (400, 200), 255)
    ImageDraw.Draw(art).rectangle([60, 40, 340, 160], fill=0)
    trimmed = ic.trim_border(art)
    assert trimmed.size == (280 + 1 + 4, 120 + 1 + 4)
    assert ic.trim_border(Image.new('L', (50, 50), 255)).size == (50, 50)   # blank: untouched
    assert ic.strip_layout(trimmed.size)[2] > ic.strip_layout(art.size)[2] * 0.99


def test_sunday_only_filters_to_sunday_strips():
    sun, mon = date(1963, 11, 7), date(1971, 11, 7)
    assert sun.weekday() == 3 and mon.weekday() == 6   # sanity: 1971-11-07 was a Sunday
    ds = [sun, mon]
    src = FakeSource(ds, {d: placeholder(1.8) for d in ds})
    assert fc.current_strip({'comic_sunday_only': True}, NOW, src).date == mon
    assert fc.current_strip({'comic_sunday_only': True}, NOW,
                            FakeSource([sun], {sun: placeholder(1.8)})) is None
    assert fc.current_strip({}, NOW, FakeSource([sun], {sun: placeholder(1.8)})).date == sun


def test_offseason_baseball_off_skips_final_and_replay():
    import main
    cfg = {'timezone': 'UTC', 'offseason_baseball': False}
    with patch('main.datetime') as dt, \
         patch('main.load_json_file', return_value=None), \
         patch('main.send_to_display'), \
         patch('refresh_tracker.needs_full_refresh', return_value=True), \
         patch('PIL.Image.Image.save'), \
         patch('offseason_replay.is_offseason', return_value=True), \
         patch('offseason_replay.maybe_start_replay') as replay, \
         patch('main._show_final_world_series') as final, \
         patch('image_free_agents.free_agent_idle_image', return_value=None), \
         patch('image_free_agents.has_moves', return_value=False):
        dt.now.return_value = NOW
        main._show_idle_screen(cfg)
    assert not replay.called and not final.called


def test_sunday_is_all_comic_and_falls_back_to_moves():
    sunday = datetime(2026, 11, 8, 10, 5)      # first half-hour: moves would normally win
    img = Image.new('1', (800, 480), 0)
    comic = _idle(img, True, sunday)
    assert comic.call_args.kwargs['all_blocks'] is True
    # no strip for today: the moves screen fills in
    import main
    with patch('main.datetime') as dt, patch('main.load_json_file', return_value=None), \
         patch('main.send_to_display'), patch('refresh_tracker.needs_full_refresh', return_value=True), \
         patch('PIL.Image.Image.save'), patch('offseason_replay.is_offseason', return_value=True), \
         patch('image_free_agents.free_agent_idle_image', return_value=img) as moves, \
         patch('image_free_agents.has_moves', return_value=True), \
         patch('image_comic.comic_idle_image', return_value=None):
        dt.now.return_value = sunday
        main._show_idle_screen({'timezone': 'UTC', 'idle_comic_rotation': True})
    assert moves.called


def test_comic_failure_falls_through():
    import main
    with patch('main.datetime') as dt, patch('main.load_json_file', return_value=None), \
         patch('main.send_to_display'), patch('refresh_tracker.needs_full_refresh', return_value=True), \
         patch('PIL.Image.Image.save'), patch('offseason_replay.is_offseason', return_value=True), \
         patch('image_free_agents.free_agent_idle_image', return_value=None), \
         patch('image_free_agents.has_moves', return_value=False), \
         patch('image_comic.comic_idle_image', side_effect=RuntimeError('x')), \
         patch('main._show_final_world_series', return_value=False):
        dt.now.return_value = datetime(2026, 11, 8, 10, 5)
        main._show_idle_screen({'timezone': 'UTC', 'idle_comic_rotation': True, 'offseason_baseball': False})


def test_rotate_minutes_steps_every_half_hour():
    ds = [date(1950 + i, 11, 7) for i in range(4)]
    src = FakeSource(ds, {d: placeholder(3.5) for d in ds})
    cfg = {'comic_rotate_minutes': 30}
    a = fc.current_strip(cfg, datetime(2026, 11, 7, 10, 0), src).position
    b = fc.current_strip(cfg, datetime(2026, 11, 7, 10, 29), src).position
    c = fc.current_strip(cfg, datetime(2026, 11, 7, 10, 30), src).position
    assert a == b and c == (a + 1) % 4
