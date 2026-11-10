"""Tests for fetch_comic (selection, local source) and image_comic (render, hook)."""
from datetime import date, datetime, timedelta
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


def test_dark_mode_keeps_white_paper_no_black_edges():
    s = _strip(1.6)
    light = ic.draw_comic_screen(s, {})
    dark = ic.draw_comic_screen(s, {'dark_mode': True})
    assert list(light.getdata()) == list(dark.getdata())
    assert dark.getpixel((799, 100)) == 1 and dark.getpixel((400, 479)) == 1


def test_single_strip_and_single_year_render():
    one = fc.Strip(date(1963, 11, 7), placeholder(3.5), 0, 1, [1963])
    assert ic.draw_comic_screen(one, {}).size == (800, 480)


def test_timeline_skips_tiny_span():
    d = ImageDraw.Draw(Image.new('1', (800, 480), 1))
    ic._timeline(d, [1963], 1963, 9, 100, 110)            # too short → no-op


def test_timeline_spine_ticks_labels_and_marker():
    img = Image.new('1', (40, 300), 1)
    years = list(range(1950, 1991))
    ic._timeline(ImageDraw.Draw(img), years, 1970, 12, 0, 300)
    assert all(img.getpixel((12, y)) == 0 for y in range(10, 290))      # continuous spine
    assert img.getpixel((14, 4)) == 0                                    # decade tick at oldest year
    left = img.crop((0, 0, 11, 300)).convert('L').point(lambda v: 255 - v)
    assert left.getbbox() is not None                                    # decade labels left of spine
    mid = 4 + round(20 * 292 / 40)
    assert img.getpixel((16, mid)) == 0 and img.getpixel((16, mid + 4)) == 1   # marker triangle base


def test_timeline_single_year_and_dense_labels():
    img = Image.new('1', (40, 100), 1)
    ic._timeline(ImageDraw.Draw(img), [1960, 1961, 1962, 1970], 1961, 12, 0, 100)
    assert img.getbbox() is not None


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


# --- selection features: fallback, week mode, prefs, tags ----------------------

def _src(*ymd):
    ds = [date(*x) for x in ymd]
    return FakeSource(ds, {d: placeholder(3.5, 40) for d in ds})


def test_fallback_to_nearest_day_with_note():
    src = _src((1966, 11, 8), (1970, 11, 5))
    s = fc.current_strip({}, datetime(2026, 11, 7, 10), src, prefs={})
    assert s.date == date(1966, 11, 8) and s.note == 'Nearest day'


def test_fallback_disabled_or_out_of_range():
    src = _src((1966, 11, 20))
    assert fc.current_strip({'comic_fallback_days': 0}, datetime(2026, 11, 7), src, prefs={}) is None
    assert fc.current_strip({}, datetime(2026, 11, 7), src, prefs={}) is None


def test_blocked_and_favorites_only():
    src = _src((1960, 11, 7), (1970, 11, 7))
    prefs = {'blocked': ['1960-11-07', 'bad'], 'favorites': ['1970-11-07']}
    s = fc.current_strip({}, datetime(2026, 11, 7), src, prefs=prefs)
    assert s.date == date(1970, 11, 7)
    assert fc.current_strip({'comic_favorites_only': True}, datetime(2026, 11, 7), src, prefs=prefs).date.year == 1970
    assert fc.current_strip({'comic_favorites_only': True}, datetime(2026, 11, 7), src,
                            prefs={'favorites': []}) is None


def test_week_mode_stays_near_one_year_all_week():
    src = _src(*[(y, 11, d) for y in (1955, 1975, 1995) for d in range(2, 9)])
    cfg = {'comic_mode': 'week'}
    years = {fc.current_strip(cfg, datetime(2026, 11, d), src, prefs={}).date.year for d in range(2, 9)}
    assert len(years) <= 2
    s = fc.current_strip(cfg, datetime(2026, 11, 4), src, prefs={})   # a Wednesday
    assert s.note == ''


def test_tag_selects_across_whole_archive():
    src = _src((1966, 10, 31), (1970, 4, 5))
    prefs = {'tags': {'1970-04-05': ['baseball'], '1966-10-31': ['halloween'], 'x': ['baseball']}}
    s = fc.current_strip({'comic_tag': 'baseball'}, datetime(2026, 11, 7), src, prefs=prefs)
    assert s.date == date(1970, 4, 5) and s.note == 'Baseball'
    s = fc.current_strip({}, datetime(2026, 10, 31), src, tag='nope', prefs=prefs)
    assert s.date == date(1966, 10, 31) and s.note == ''


def test_unloadable_strips_skipped_in_week_mode():
    src = FakeSource([date(1960, 11, 7), date(1970, 11, 7)], {date(1970, 11, 7): placeholder(3.5, 40)})
    assert fc.current_strip({'comic_mode': 'week'}, datetime(2026, 11, 7), src, prefs={}).date.year == 1970
    assert fc.current_strip({}, datetime(2026, 11, 7), FakeSource([date(1960, 11, 7)]), prefs={}) is None


def test_load_prefs(tmp_path):
    (tmp_path / 'peanuts').mkdir()
    assert fc.load_prefs('peanuts', str(tmp_path)) == {}
    (tmp_path / 'peanuts' / 'prefs.json').write_text('{"blocked": ["1960-01-01"]}')
    assert fc.load_prefs('peanuts', str(tmp_path)) == {'blocked': ['1960-01-01']}
    (tmp_path / 'peanuts' / 'prefs.json').write_text('[1]')
    assert fc.load_prefs('peanuts', str(tmp_path)) == {}
    (tmp_path / 'peanuts' / 'prefs.json').write_text('nope')
    assert fc.load_prefs('peanuts', str(tmp_path)) == {}


def test_caption_years_ago_and_note():
    assert ic._years_ago(date(1966, 11, 8), {'comic_today': date(2026, 11, 7)}) == 59
    assert ic._years_ago(date(1966, 11, 7), {'comic_today': date(2026, 11, 7)}) == 60
    s = fc.Strip(date(1966, 11, 7), placeholder(3.5, 40), 0, 1, [1966], 'Day 2 of 7')
    assert ic.draw_comic_screen(s, {'comic_today': date(2026, 11, 7)}).size == (800, 480)


def test_cli_no_strip(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ic, 'current_strip', lambda *a, **k: None)
    assert ic.main(['2026-10-31', str(tmp_path / 'o.png')]) == 1
    assert 'no strip' in capsys.readouterr().out


def test_cli_success(tmp_path, monkeypatch):
    s = fc.Strip(date(1966, 10, 31), placeholder(3.5, 40), 0, 1, [1966])
    monkeypatch.setattr(ic, 'current_strip', lambda *a, **k: s)
    out = tmp_path / 'o.png'
    assert ic.main(['2026-10-31', str(out), '--mode', 'week']) == 0 and out.exists()


def test_cache_report(tmp_path):
    import sys
    sys.path.insert(0, 'scripts')
    import comic_cache_report as r
    _write(tmp_path / 'peanuts' / '1966-10-31.png')
    text = r.report('peanuts', str(tmp_path))
    assert 'strips: 1' in text and 'years: 1966-1966' in text and 'no strip: 365 of 366' in text
    assert 'strips: 0' in r.report('missing', str(tmp_path))


# --- morning rotation ------------------------------------------------------------

def test_morning_rotation_includes_comic_only_when_enabled():
    import main as m
    base = m.morning_rotation({'idle_comic_rotation': False})
    assert 'comic' not in base
    assert m.morning_rotation({'idle_comic_rotation': True})[-1] == 'comic'
    assert 'comic' not in m.morning_rotation({'idle_comic_rotation': True, 'morning_alternate_comic': False})


def test_show_morning_comic(monkeypatch, tmp_path):
    import main as m
    img = Image.new('1', (800, 480), 1)
    sent = []
    monkeypatch.setattr(m, '_REPO_ROOT', str(tmp_path))
    monkeypatch.setattr(m, 'send_to_display', lambda p, force_full=False: sent.append(p))
    monkeypatch.setattr(ic, 'comic_idle_image', lambda *a, **k: img)
    assert m._show_morning_comic({'night_mode': False}, NOW) is True and sent
    monkeypatch.setattr(ic, 'comic_idle_image', lambda *a, **k: None)
    assert m._show_morning_comic({}, NOW) is False
    monkeypatch.setattr(ic, 'comic_idle_image', lambda *a, **k: 1 / 0)
    assert m._show_morning_comic({}, NOW) is False
    monkeypatch.setattr(ic, 'comic_idle_image', lambda *a, **k: img)
    monkeypatch.setattr(m, 'send_to_display', lambda *a, **k: 1 / 0)
    assert m._show_morning_comic({}, NOW) is True


def test_resolve_morning_comic_block(monkeypatch):
    import argparse
    import main as m
    cfg = {'idle_comic_rotation': True, 'night_end': 7}
    monkeypatch.setattr(m, 'morning_rotation', lambda c, now=None: ('comic',))
    monkeypatch.setattr(m, '_local_now', lambda c: datetime(2026, 6, 2, 8, 0))
    ctx = m._resolve_target_date(argparse.Namespace(date=None), cfg)
    assert ctx.mode_override == 'comic' and ctx.showing_previous_day is False


# --- arc mode ----------------------------------------------------------------------

def test_arc_mode_prefers_days_inside_an_arc():
    src = _src(*[(y, 11, 7) for y in (1955, 1975, 1995)])
    prefs = {'arcs': [{'start': '1975-11-05', 'end': '1975-11-09'}, {'start': 'x', 'end': 'y'}, {'bad': 1}]}
    s = fc.current_strip({'comic_mode': 'arc'}, datetime(2026, 11, 7), src, prefs=prefs)
    assert s.date.year == 1975 and s.note == ''
    s = fc.current_strip({'comic_mode': 'arc'}, datetime(2026, 11, 7), src, prefs={})
    assert s.note == '' and s.date.month == 11


# --- arc detection (comic_arcs) -------------------------------------------------------

def _rows(day, chars, cap, n=3):
    return [{'panel_name': f'{day}_{i:02d}', 'characters': chars, 'themes': [], 'caption': cap} for i in range(n)]


def test_find_arcs_groups_linked_days_and_splits_unlinked():
    import comic_arcs as ca
    rows = []
    for d in range(1, 6):                                   # Mon-Fri: Linus+Lucy blanket arc
        rows += _rows(f'196503{d + 7:02d}', ['Linus van Pelt', 'Lucy van Pelt'], 'blanket attacks lucy')
    for d in range(15, 18):                                 # an unrelated gag run, different characters
        rows += _rows(f'196503{d}', ['Snoopy'], 'doghouse sleeping')
    rows += _rows('19650320', ['Schroeder'], 'piano beethoven')   # lone strip
    rows += _rows('19650319', ['Violet Gray'], 'mud pie')
    rows += [{'panel_name': 'bad', 'characters': None}, {'panel_name': '19650230_00'}]   # ignored
    strips = ca.group_strips(rows)
    arcs = ca.find_arcs(strips)
    assert any(len(a) >= 5 for a in arcs)
    out = ca.arcs_to_json(arcs)
    assert out[0]['days'] == len(arcs[0]) and out[0]['start'] <= out[0]['end']
    assert ca.find_arcs({}) == []


def test_find_arcs_splits_overlong_chain_and_skips_overlap():
    import comic_arcs as ca
    from datetime import date as D
    rows, d = [], D(1970, 1, 5)
    for _ in range(40):                                     # one 40-day chain of identical strips
        while d.weekday() == 6:
            d += timedelta(days=1)
        rows += _rows(d.strftime('%Y%m%d'), ['Snoopy', 'Woodstock'], 'flying ace red baron')
        d += timedelta(days=1)
    rows += _rows('19700106', ['Rerun van Pelt'], 'bicycle ride') + _rows('19700301', ['Marcie'], 'school')
    arcs = ca.find_arcs(ca.group_strips(rows))
    assert arcs and all(ca.MIN_LEN <= len(a) <= ca.MAX_LEN for a in arcs)
    spans = [(a[0], a[-1]) for a in arcs]
    assert all(b[0] > a[1] for a, b in zip(spans, spans[1:]))


def test_build_comic_arcs_script(tmp_path, monkeypatch):
    import json
    import sys
    sys.path.insert(0, 'scripts')
    import build_comic_arcs as b
    meta = tmp_path / 'm.jsonl'
    rows = []
    for d in range(8, 13):
        rows += _rows(f'196503{d:02d}', ['Linus van Pelt', 'Lucy van Pelt'], 'blanket attacks lucy')
    for d in range(1, 30):                                  # unrelated filler so IDF has a corpus
        rows += _rows(f'197005{d:02d}', [f'Kid {d}'], f'topic{d} word{d}')
    meta.write_text('\n'.join(json.dumps(r) for r in rows))
    monkeypatch.setattr(b, 'COMICS_DIR', str(tmp_path))
    (tmp_path / 'peanuts').mkdir()
    (tmp_path / 'peanuts' / 'prefs.json').write_text('{"blocked": ["1960-01-01"]}')
    monkeypatch.setattr(sys, 'argv', ['x', '--metadata', str(meta)])
    b.main()
    saved = json.loads((tmp_path / 'peanuts' / 'prefs.json').read_text())
    assert saved['blocked'] == ['1960-01-01'] and saved['arcs']
    (tmp_path / 'peanuts' / 'prefs.json').write_text('garbage')
    with pytest.raises(SystemExit):                          # never overwrite a prefs file it cannot read
        b.main()
    assert (tmp_path / 'peanuts' / 'prefs.json').read_text() == 'garbage'
    (tmp_path / 'peanuts' / 'prefs.json').write_text('[1]')
    with pytest.raises(SystemExit):
        b.main()
    (tmp_path / 'peanuts' / 'prefs.json').unlink()
    b.main()                                                 # no file yet: created
    assert json.loads((tmp_path / 'peanuts' / 'prefs.json').read_text())['arcs']


def test_range_file_and_rows(monkeypatch):
    import sys
    sys.path.insert(0, 'scripts')
    import build_comic_arcs as b

    class Resp:
        def __init__(self, content=b'', headers=None, url='u'):
            self.content, self.headers, self.url = content, headers or {}, url

        def raise_for_status(self):
            pass

    data = b'0123456789'
    monkeypatch.setattr(b.requests, 'head', lambda url, **k: Resp(headers={'Content-Length': '10'}, url='real'))

    class Sess:
        def get(self, url, headers=None, timeout=0):
            lo, hi = headers['Range'].split('=')[1].split('-')
            return Resp(data[int(lo):int(hi) + 1])

    monkeypatch.setattr(b.requests, 'Session', Sess)
    f = b.RangeFile('x')
    assert f.seekable() and f.readable() and f.seek(2) == 2 and f.read(3) == b'234' and f.tell() == 5
    assert f.seek(-2, 2) == 8 and f.read() == b'89' and f.read(5) == b''
    f.seek(1)
    assert f.seek(2, 1) == 3
    buf = bytearray(4)
    assert f.readinto(buf) == 4 and bytes(buf) == b'3456'
    f.close()

    import types
    batch = types.SimpleNamespace(to_pylist=lambda: [{'panel_name': 'a'}])
    pf = types.SimpleNamespace(iter_batches=lambda **k: [batch])
    fake_pq = types.SimpleNamespace(ParquetFile=lambda fh: pf)
    monkeypatch.setitem(sys.modules, 'pyarrow.parquet', fake_pq)
    monkeypatch.setitem(sys.modules, 'pyarrow', types.SimpleNamespace(parquet=fake_pq))
    monkeypatch.setattr(b.requests, 'get', lambda url, timeout=0: types.SimpleNamespace(json=lambda: ['u1', 'u2']))
    assert list(b.metadata_rows()) == [{'panel_name': 'a'}, {'panel_name': 'a'}]


def test_find_arcs_splits_a_linked_chain_across_a_long_gap():
    import comic_arcs as ca
    rows = []
    for day in ('19691230', '19691231', '19700101', '19700105', '19700106', '19700107'):
        rows += _rows(day, ['Linus van Pelt', 'Lucy van Pelt'], 'blanket attacks lucy')
    for d in range(1, 30):
        rows += _rows(f'197005{d:02d}', [f'Kid {d}'], f'topic{d} word{d}')
    arcs = ca.find_arcs(ca.group_strips(rows))
    assert [len(a) for a in arcs if a[0].year < 1971] == [3, 3]


# --- arcs mode: one arc per day, played in order ---------------------------------------

def _arc_prefs():
    return {'arcs': [
        {'start': '1970-01-05', 'end': '1970-01-07', 'dates': ['1970-01-05', '1970-01-06', '1970-01-07']},
        {'start': '1960-03-04', 'end': '1960-03-07'},          # no 'dates': Fri, Sat, (Sun skipped), Mon
        {'start': 'x', 'end': 'y'}, 'junk', {'dates': ['bad']},
    ]}


def _arc_src():
    ds = [date(1970, 1, 5), date(1970, 1, 6), date(1970, 1, 7), date(1960, 3, 4), date(1960, 3, 5), date(1960, 3, 7)]
    return FakeSource(ds, {d: placeholder(3.5, 40) for d in ds})


def test_arc_dates_variants():
    assert fc.arc_dates({'dates': ['1970-01-06', '1970-01-05']}) == [date(1970, 1, 5), date(1970, 1, 6)]
    assert fc.arc_dates({'start': '1960-03-04', 'end': '1960-03-07'}) == [date(1960, 3, 4), date(1960, 3, 5), date(1960, 3, 7)]
    assert fc.arc_dates({'start': 'x', 'end': 'y'}) == [] and fc.arc_dates('junk') == []


def test_arc_index_counts_real_strips_not_sundays():
    idx = fc._arc_index(_arc_prefs())
    assert idx[date(1960, 3, 7)] == (3, 3) and idx[date(1970, 1, 6)] == (2, 3)


def test_arcs_mode_plays_every_arc_in_order_through_the_day():
    cfg = {'comic_mode': 'arcs', 'comic_arc_minutes': 60}
    day = datetime(2026, 11, 7, 0, 0)
    seen = []
    for hour in range(24):
        s = fc.current_strip(cfg, day.replace(hour=hour), _arc_src(), prefs=_arc_prefs())
        seen.append((s.date, s.position + 1, s.total))
    # the playlist is 1960's 3-strip arc then 1970's 3-strip arc, repeating: strips 1..3 in order each time
    assert [p for _, p, _ in seen] == [1, 2, 3] * 8
    assert {d.year for d, _, _ in seen} == {1960, 1970}                      # many arcs in one day
    for start in range(0, 24, 3):
        trio = [d for d, _, _ in seen[start:start + 3]]
        assert trio == sorted(trio) and len({d.year for d in trio}) == 1     # each arc plays whole, in order


def test_arcs_mode_continues_across_midnight():
    cfg = {'comic_mode': 'arcs', 'comic_arc_minutes': 60}
    last = fc.current_strip(cfg, datetime(2026, 11, 7, 23, 0), _arc_src(), prefs=_arc_prefs())
    first = fc.current_strip(cfg, datetime(2026, 11, 8, 0, 0), _arc_src(), prefs=_arc_prefs())
    assert first.position == (last.position + 1) % 3          # the very next strip: no jump at midnight


def test_arcs_mode_fallbacks():
    cfg = {'comic_mode': 'arcs', 'comic_arc_offset': 1, 'comic_arc_minutes': 0}   # 0 is clamped to 1 minute
    assert fc.current_strip(cfg, NOW, _arc_src(), prefs=_arc_prefs()) is not None
    # no arcs in prefs -> normal on-this-day selection
    s = fc.current_strip({'comic_mode': 'arcs'}, datetime(2026, 1, 5), _arc_src(), prefs={})
    assert s.date == date(1970, 1, 5)
    # arcs whose strips never load -> falls through to the normal path too
    empty = FakeSource([date(1970, 1, 5)], {})
    assert fc.current_strip({'comic_mode': 'arcs'}, datetime(2026, 1, 5), empty, prefs=_arc_prefs()) is None


def test_arcs_mode_counter_reads_day_x_of_n():
    s = fc.current_strip({'comic_mode': 'arcs'}, datetime(2026, 11, 7, 1), _arc_src(), prefs=_arc_prefs())
    assert s.label == 'Day' and s.position == 1
    img = ic.draw_comic_screen(s, {})
    plain = ic.draw_comic_screen(s._replace(label=''), {})
    assert img.tobytes() != plain.tobytes()          # 'Day ' lengthens the gutter counter


# --- QR code + web server -----------------------------------------------------------------

def _arc_strip_obj(aspect=3.5, arc_start=date(1970, 1, 5)):
    return fc.Strip(date(1970, 1, 6), placeholder(aspect, 120), 1, 3, [1970], label='Day', arc_start=arc_start)


def test_arc_url_variants(monkeypatch):
    s = _arc_strip_obj()
    cfg = {'comic_qr_host': 'pi.local', 'config_server_port': 9000}
    code = fc.arc_code(date(1970, 1, 5))
    assert ic.arc_url(cfg, s) == f'HTTP://PI.LOCAL:9000/A/{code}'
    assert ic.arc_url({'comic_qr_host': 'h', 'comic_name': 'garfield'}, s) == f'HTTP://H:8080/A/{code}/GARFIELD'
    old = s._replace(arc_start=date(1949, 12, 31))      # no short code before 1950: fall back to the date link
    assert ic.arc_url({'comic_qr_host': 'h', 'comic_name': 'garfield'}, old) == 'http://h:8080/arc/1949-12-31?comic=garfield'
    assert ic.arc_url(cfg, old) == 'http://pi.local:9000/arc/1949-12-31'
    assert ic.arc_url(cfg, s._replace(arc_start=None)) is None
    monkeypatch.setattr(ic, 'get_lan_ip', lambda: '192.0.2.1')
    assert ic.arc_url({}, s).startswith('HTTP://192.0.2.1:8080/')


def test_get_lan_ip_real_and_failing(monkeypatch):
    assert ic.get_lan_ip().count('.') == 3

    class Boom:
        def connect(self, *_):
            raise OSError('no route')

        def close(self):
            pass

    import socket
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: Boom())
    assert ic.get_lan_ip() == '127.0.0.1'


def test_qr_image_is_square_and_has_quiet_zone():
    q = ic.qr_image('http://192.0.2.1:8080/arc/1970-01-05')
    assert q.mode == '1' and q.size[0] == q.size[1] and q.size[0] % ic._QR_MODULE == 0
    n = q.size[0]
    px = q.load()
    q2 = q.convert('L')
    assert all(q2.getpixel((x, 0)) == 255 for x in range(n))       # top quiet-zone row is white
    assert any(px[x, y] == 0 for x in range(n) for y in range(n))


def test_qr_drawn_under_wide_strip_and_beside_tall_strip():
    cfg = {'comic_qr': True, 'comic_qr_host': '192.0.2.1'}
    for aspect in (3.6, 1.2, 1.7):                              # wide strip, tall (side margin), then one that fills both ways
        s = _arc_strip_obj(aspect)
        with_qr = ic.draw_comic_screen(s, cfg)
        without = ic.draw_comic_screen(s, {})
        assert with_qr.tobytes() != without.tobytes() and with_qr.size == (800, 480)
        qr = ic.qr_image(ic.arc_url(cfg, s))
        corner = with_qr.crop((800 - qr.size[0] - 2, 480 - qr.size[1] - 2, 800, 480)) if aspect < 2 else \
            with_qr.crop((20, 480 - qr.size[1] - 2, 20 + qr.size[0], 480))
        assert any(p == 0 for p in corner.getdata())            # ink in the QR spot
    off = ic.draw_comic_screen(_arc_strip_obj(), {'comic_qr': False})
    assert off.size == (800, 480)
    assert ic.draw_comic_screen(_arc_strip_obj(arc_start=None), cfg).size == (800, 480)   # no arc -> no QR


def test_strip_layout_reserve_right_shrinks_strip():
    full = ic.strip_layout((1000, 1000))
    reserved = ic.strip_layout((1000, 1000), reserve_right=70)
    assert reserved[2] <= full[2] and reserved[0] + reserved[2] <= 800 - 2 - 70


def _client(tmp_path, monkeypatch, arcs=True):
    import json
    import comic_server as cs
    from flask import Flask
    root = tmp_path / 'peanuts'
    _write(root / '1970-01-05.png')
    _write(root / '1970-01-06.png')
    _write(root / '1971-02-01.png')
    prefs = {'arcs': [{'start': '1970-01-05', 'end': '1970-01-06', 'dates': ['1970-01-05', '1970-01-06']},
                      {'start': '1971-02-01', 'end': '1971-02-03', 'dates': ['1971-02-01']}]} if arcs else {}
    (root / 'prefs.json').write_text(json.dumps(prefs))
    monkeypatch.setattr(fc, 'COMICS_DIR', str(tmp_path))
    monkeypatch.setattr(fc.LocalCacheSource, '__init__',
                        lambda self, comic='peanuts', root=None: (setattr(self, 'comic', comic),
                                                                  setattr(self, 'dir', str(tmp_path / comic)))[0])
    app = Flask(__name__)
    app.register_blueprint(cs.comic_bp)
    return app.test_client()


def test_arc_page_lists_strips_in_order(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get('/arc/1970-01-05')
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and 'Day 1 of 2' in html and 'Day 2 of 2' in html
    assert html.index('1970-01-05') < html.index('1970-01-06')
    assert 'Next arc' in html and 'Previous arc' not in html
    assert 'Previous arc' in c.get('/arc/1971-02-01').get_data(as_text=True)


def test_arc_code_round_trip_and_invalid():
    for d in (date(1950, 10, 2), date(1970, 1, 5), date(1987, 11, 25), date(2000, 2, 13), date(2026, 11, 9)):
        code = fc.arc_code(d)
        assert code == code.upper() and 1 <= len(code) <= 4
        assert fc.arc_start_from_code(code) == d and fc.arc_start_from_code(code.lower()) == d
    assert fc.arc_code(date(1950, 1, 1)) == '0'
    with pytest.raises(ValueError):
        fc.arc_code(date(1949, 12, 31))
    for bad in ('', None, '!!', 'ABCDEF', 'a b', 'ZZZZZ'):    # empty, junk, too long, past the max date
        assert fc.arc_start_from_code(bad) is None


def test_short_arc_route_matches_long_page(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    code = fc.arc_code(date(1970, 1, 5))
    long_html = c.get('/arc/1970-01-05').get_data(as_text=True)
    for url in (f'/a/{code}', f'/a/{code.lower()}', f'/a/{code}/PEANUTS'):
        r = c.get(url)
        assert r.status_code == 200 and r.get_data(as_text=True) == long_html
    assert c.get(f'/a/{fc.arc_code(date(1999, 1, 1))}').status_code == 404    # not an arc start
    assert c.get('/a/!!').status_code == 404
    assert c.get(f'/a/{code}/..%2Fetc').status_code in (400, 404)
    assert c.get(f'/a/{code}/GARFIELD').status_code == 404                     # no such comic: no prefs


def test_qr_for_arc_url_is_alphanumeric_and_compact():
    import segno
    url = ic.arc_url({'comic_qr_host': '192.168.100.123'}, _arc_strip_obj(arc_start=date(1987, 11, 25)))
    assert segno.make(url, error='h').mode == 'alphanumeric'
    assert ic.qr_image(url).size[0] == (29 + 4) * 3        # 29 modules + quiet zone at 3 px


def test_arc_page_errors(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get('/arc/1999-01-01').status_code == 404          # not an arc start
    assert c.get('/arc/not-a-date').status_code == 404
    assert c.get('/arc/1970-01-05?comic=../etc').status_code == 400


def test_strip_image_served_and_validated(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get('/comic/img/1970-01-05')
    assert r.status_code == 200 and r.data[:4] == b'\x89PNG'
    assert c.get('/comic/img/1999-01-01').status_code == 404
    assert c.get('/comic/img/xx').status_code == 404
    assert c.get('/comic/img/1970-01-05?comic=a%2Fb').status_code == 400


def test_config_server_registers_comic_blueprint():
    import config_server
    assert 'comic.arc_page' in {r.endpoint for r in config_server.app.url_map.iter_rules()}


def test_find_arc_neighbors():
    prefs = _arc_prefs()
    ds, prev, nxt = fc.find_arc(prefs, date(1970, 1, 5))
    assert len(ds) == 3 and prev == date(1960, 3, 4) and nxt is None
    assert fc.find_arc(prefs, date(2000, 1, 1)) is None
    assert fc.find_arc({}, date(1970, 1, 5)) is None


# --- review fixes -----------------------------------------------------------------------

def test_arcs_mode_default_step_is_fifteen_minutes():
    cfg = {'comic_mode': 'arcs'}
    seen = [fc.current_strip(cfg, datetime(2026, 11, 7, 10, m), _arc_src(), prefs=_arc_prefs()).position for m in (0, 15, 30, 45)]
    assert seen == [(seen[0] + k) % 3 for k in range(4)]


def test_arcs_step_not_dividing_a_day_does_not_repeat_at_midnight():
    cfg = {'comic_mode': 'arcs', 'comic_arc_minutes': 7}
    a = fc.current_strip(cfg, datetime(2026, 11, 7, 23, 59), _arc_src(), prefs=_arc_prefs())
    b = fc.current_strip(cfg, datetime(2026, 11, 8, 0, 0), _arc_src(), prefs=_arc_prefs())
    assert a is not None and b is not None
    c = fc.current_strip(cfg, datetime(2026, 11, 8, 0, 7), _arc_src(), prefs=_arc_prefs())
    assert (c.position - b.position) % 3 == 1


def test_mixed_order_spreads_years_and_visits_every_arc_once():
    order = fc._mixed_order(10)
    assert sorted(order) == list(range(10))
    assert all(abs(a - b) >= 3 for a, b in zip(order, order[1:]))   # neighbours are far apart in the date-sorted list
    assert fc._mixed_order(1) == [0] and sorted(fc._mixed_order(7)) == list(range(7))


def _many_arcs():
    ds, prefs = [], {'arcs': []}
    for k in range(6):
        year = 1950 + k * 8
        days = [date(year, 3, 2 + j) for j in range(3)]
        ds += days
        prefs['arcs'].append({'start': days[0].isoformat(), 'end': days[-1].isoformat(), 'dates': [d.isoformat() for d in days]})
    return FakeSource(ds, {d: placeholder(3.5, 40) for d in ds}), prefs


def test_arcs_mode_mixes_years_within_a_day_and_chronological_option():
    src, prefs = _many_arcs()
    def years(cfg):
        out = []
        for q in range(24):
            s = fc.current_strip(cfg, datetime(2026, 11, 7, 6 + q // 4, (q % 4) * 15), src, prefs=prefs)
            out.append(s.date.year)
        return out
    mixed = years({'comic_mode': 'arcs'})
    chrono = years({'comic_mode': 'arcs', 'comic_arc_order': 'chronological'})
    assert len(set(mixed)) >= 5 and len(set(chrono)) >= 5
    first_arc = [mixed[i] for i in range(0, 24, 3)]
    assert max(abs(a - b) for a, b in zip(first_arc, first_arc[1:])) >= 16        # decades apart
    descents = sum(b < a for a, b in zip(chrono, chrono[1:]))
    assert descents <= 1                                                           # chronological: only the wrap-around goes back


def test_arcs_mode_honours_blocked_favorites_cache_and_sunday_only():
    src, prefs = _many_arcs()
    now = datetime(2026, 11, 7, 10)
    prefs = dict(prefs, blocked=[d.isoformat() for d in (date(1950, 3, 2), date(1950, 3, 3), date(1950, 3, 4))])
    seen = {fc.current_strip({'comic_mode': 'arcs'}, now.replace(hour=h, minute=m), src, prefs=prefs).date
            for h in range(24) for m in (0, 15, 30, 45)}
    assert not any(d.year == 1950 for d in seen) and seen
    only = dict(prefs, favorites=['1966-03-02'])
    fav = [fc.current_strip({'comic_mode': 'arcs', 'comic_favorites_only': True}, now.replace(hour=h), src, prefs=only)
           for h in range(24)]
    assert {s.date for s in fav} == {date(1966, 3, 2)} and {s.total for s in fav} == {1}      # counter reflects what is eligible
    assert fc.arc_strip({'comic_sunday_only': True}, now, src, prefs) is None
    src.available = lambda: {date(1958, 3, 2)}                                                # only one strip actually cached
    s = fc.current_strip({'comic_mode': 'arcs'}, now, src, prefs=prefs)
    assert s.date == date(1958, 3, 2) and s.total == 1


def test_filters_apply_before_nearest_day_search():
    src = _src((1966, 11, 6), (1966, 11, 7), (1971, 11, 8))
    now = datetime(2026, 11, 7, 10)                                   # a Saturday in 2026; Sunday strips are 1966-11-06
    assert fc.current_strip({'comic_sunday_only': True}, now, src, prefs={}).date == date(1966, 11, 6)
    prefs = {'favorites': ['1971-11-08']}
    assert fc.current_strip({'comic_favorites_only': True}, now, src, prefs=prefs).date == date(1971, 11, 8)


def test_tag_mode_falls_back_and_tolerates_bad_tags():
    src = _src((1966, 11, 7))
    now = datetime(2026, 11, 7, 10)
    # tagged date is not in the source -> plain on-this-day strip instead of nothing
    s = fc.current_strip({'comic_tag': 'halloween'}, now, src, prefs={'tags': {'1966-10-31': ['halloween']}})
    assert s.date == date(1966, 11, 7)
    # a malformed tags value does not raise; matching ignores case
    assert fc.current_strip({'comic_tag': 'x'}, now, src, prefs={'tags': ['oops']}).date == date(1966, 11, 7)
    src2 = _src((1966, 10, 31), (1970, 4, 5))
    s = fc.current_strip({'comic_tag': 'HALLOWEEN'}, now, src2, prefs={'tags': {'1966-10-31': ['Halloween']}})
    assert s.date == date(1966, 10, 31)


def test_years_ago_singular_and_local_date():
    assert ic._years_ago(date(1965, 11, 7), {'comic_today': date(2026, 11, 7)}) == 61
    s = fc.Strip(date(1965, 11, 8), placeholder(3.5, 40), 0, 1, [1965])
    seen = {}
    from unittest.mock import patch as _patch
    with _patch.object(ic, 'draw_comic_screen', lambda strip, cfg: seen.setdefault('cfg', cfg)), \
            _patch.object(ic, 'current_strip', lambda *a, **k: s):
        ic.comic_idle_image({'idle_comic_rotation': True}, datetime(2026, 11, 7, 23, 50), replay_running=lambda pid: False,
                            load=lambda name: {}, all_blocks=True)
    assert seen['cfg']['comic_today'] == date(2026, 11, 7)            # caption uses the display's local date


def test_cache_report_tolerates_null_prefs(tmp_path):
    import json
    import sys
    sys.path.insert(0, 'scripts')
    import comic_cache_report as r
    _write(tmp_path / 'peanuts' / '1966-10-31.png')
    (tmp_path / 'peanuts' / 'prefs.json').write_text(json.dumps({'favorites': None, 'blocked': None, 'tags': None}))
    assert 'favorites: 0, blocked: 0, tagged: 0' in r.report('peanuts', str(tmp_path))


def test_local_source_available(tmp_path):
    _write(tmp_path / 'peanuts' / '1966-10-31.png')
    _write(tmp_path / 'peanuts' / '1999-02-29.png')
    (tmp_path / 'peanuts' / 'readme.txt').write_text('x')
    assert fc.LocalCacheSource('peanuts', str(tmp_path)).available() == {date(1966, 10, 31)}
    assert fc.LocalCacheSource('nope', str(tmp_path)).available() == set()


def test_counter_uses_hand_font_and_falls_back(monkeypatch):
    f = ic._hand_font(14)
    assert f is ic._hand_font(14) and f.getlength('Day 3 of 14') > 0
    assert 'PatrickHand' in str(getattr(f, 'path', ''))
    monkeypatch.setattr(ic, '_HAND_FONT', '/nonexistent/font.ttf')
    ic._hand_cache.clear()
    try:
        assert ic._hand_font(14).getlength('Day 3 of 14') > 0         # panel font instead of a crash
    finally:
        ic._hand_cache.clear()


def test_snoopy_head_has_ink_and_white_face_and_logo_sits_mid_code():
    h = ic.snoopy_head(24)
    assert h.size == (24, 24) and h.mode == '1'
    px = list(h.convert('L').getdata())
    assert 0.2 < px.count(0) / len(px) < 0.6 and px.count(255) > 80      # black ear/nose/outline, white face
    with_logo, plain = ic.qr_image('http://h:8080/arc/1970-01-05'), ic.qr_image('http://h:8080/arc/1970-01-05', logo=False)
    assert with_logo.size[0] > plain.size[0]                              # level H needs a bigger code
    c = with_logo.size[0] // 2
    assert with_logo.convert('L').getpixel((c - 11, c - 11)) == 255       # white plate corner around the head


# --- week-of-year split + body logo ----------------------------------------------------

def test_week_of_year_folds_53_into_52():
    assert fc.week_of_year(date(2026, 1, 5)) == 2
    assert date(2020, 12, 31).isocalendar()[1] == 53 and fc.week_of_year(date(2020, 12, 31)) == 52


class _WeekSource(FakeSource):
    def available(self):
        return set(self._dates)


def test_by_week_shows_strips_from_this_week_number_in_any_year():
    # 1960-01-26 and 1971-01-27 are week 4; 1960-03-01 and 1971-07-04 are not (2026-01-22 is week 4 too)
    ds = [date(1960, 1, 26), date(1971, 1, 27), date(1960, 3, 1), date(1971, 7, 4)]
    src = _WeekSource(ds, {d: placeholder(3.5, 40) for d in ds})
    now = datetime(2026, 1, 22, 10)
    assert fc.week_of_year(now.date()) == 4
    seen = set()
    for day in range(19, 26):
        s = fc.current_strip({'comic_by_week': True}, datetime(2026, 1, day, 10), src, prefs={})
        seen.add(s.date)
    assert seen <= {date(1960, 1, 26), date(1971, 1, 27)} and seen
    # a source with no listing, or no strips that week, falls back to the on-this-day strips
    assert fc.current_strip({'comic_by_week': True}, datetime(2026, 7, 4, 10), src, prefs={}).date == date(1971, 7, 4)
    plain = FakeSource([date(1960, 1, 22)], {date(1960, 1, 22): placeholder(3.5, 40)})
    assert fc.current_strip({'comic_by_week': True}, now, plain, prefs={}).date == date(1960, 1, 22)


def test_by_week_arcs_only_from_this_week_with_fallback():
    src, prefs = _many_arcs()                       # six arcs, each starting March 2 (week 10 in those years)
    in_week = {fc.current_strip({'comic_mode': 'arcs', 'comic_by_week': True}, datetime(2026, 3, 9, h, m), src, prefs=prefs).date
               for h in range(24) for m in (0, 30)}
    assert in_week
    prefs['arcs'][0] = {'start': '1950-06-05', 'end': '1950-06-07', 'dates': ['1950-06-05', '1950-06-06', '1950-06-07']}
    wk = fc.week_of_year(date(1958, 3, 2))
    got = {fc.week_of_year(fc.current_strip({'comic_mode': 'arcs', 'comic_by_week': True}, datetime(2026, 3, 9, h), src, prefs=prefs).arc_start)
           for h in range(24)}
    assert got <= {wk, fc.week_of_year(date(1950, 6, 5))} and wk in got
    only_june = {fc.week_of_year(fc.current_strip({'comic_mode': 'arcs', 'comic_by_week': True}, datetime(2026, 9, 14, h), src, prefs=prefs).arc_start)
                 for h in range(24)}                # no arc began that week -> falls back to every arc
    assert only_june


def test_body_logo_is_bigger_code_and_scales_with_module():
    body = ic.snoopy_body(40, 32)
    assert body.size == (40, 32) and body.mode == '1'
    px = list(body.convert('L').getdata())
    assert 0.1 < px.count(0) / len(px) < 0.5
    url = 'http://h:8080/arc/1970-01-05'
    head, full = ic.qr_image(url, logo='head'), ic.qr_image(url, logo='body')
    assert full.size == head.size                            # both default to 3 px modules
    assert ic.qr_image(url, logo='body', module=2).size[0] == head.size[0] // 3 * 2
    assert ic.qr_image(url, logo=False).size[0] < head.size[0]
    cfg = {'comic_qr': True, 'comic_qr_host': 'h', 'comic_qr_logo': 'body', 'comic_qr_module': 2}
    assert ic.draw_comic_screen(_arc_strip_obj(), cfg).size == (800, 480)
