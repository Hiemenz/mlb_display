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
    assert s.note == 'Day 3 of 7'


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
    assert s.date.year == 1975 and s.note == 'Arc day 3 of 5'
    s = fc.current_strip({'comic_mode': 'arc'}, datetime(2026, 11, 7), src, prefs={})
    assert s.note == 'Day 6 of 7'


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
    from datetime import date as D, timedelta
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
    b.main()
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
