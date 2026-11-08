"""Tests for comic_stitch: panel grouping, layout, stitching and quality gates."""
import io
from datetime import date

import pytest
from PIL import Image, ImageDraw

import comic_stitch as cs

DAILY, SUNDAY = '2026-11-07', '2026-11-08'   # a Saturday and a Sunday


def _png(w=200, h=150, ink=True):
    img = Image.new('L', (w, h), 255)
    if ink:
        m = min(10, w // 4, h // 4)
        ImageDraw.Draw(img).rectangle([m, m, w - m, h - m], outline=0, width=2)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


def _panels(n, **kw):
    return {i: _png(**kw) for i in range(n)}


def test_parse_panel_name():
    assert cs.parse_panel_name('19501002_00') == ('1950-10-02', 0)
    assert cs.parse_panel_name('20000213_12') == ('2000-02-13', 12)
    for bad in ('19500230_00', 'x', '', None, '19501002', '19501002_', '1950100_00'):
        assert cs.parse_panel_name(bad) is None


def test_is_sunday():
    assert cs.is_sunday(SUNDAY) and not cs.is_sunday(DAILY)


def test_group_panels_skips_junk_and_keeps_larger_duplicate():
    small, big = _png(50, 50), _png(300, 200)
    g = cs.group_panels([('20261107_00', small), ('20261107_00', big), ('bogus', big),
                         ('20261107_01', b''), ('20261107_02', small)])
    assert g == {'2026-11-07': {0: big, 2: small}}


def test_iter_date_groups_streams_in_order():
    items = [('20261107_00', b'a'), ('20261107_01', b'b'), ('20261108_00', b'c'),
             ('nope', b'x'), ('20261108_00', b'bigger'), ('20261109_00', b'')]
    assert list(cs.iter_date_groups(items)) == [
        ('2026-11-07', {0: b'a', 1: b'b'}), ('2026-11-08', {0: b'bigger'})]
    assert list(cs.iter_date_groups([])) == []
    # a date that reappears later yields a second group
    again = [('20261107_00', b'a'), ('20261108_00', b'b'), ('20261107_01', b'c')]
    assert [d for d, _ in cs.iter_date_groups(again)] == ['2026-11-07', '2026-11-08', '2026-11-07']


def test_decode_rejects_bad_tiny_and_blank_panels():
    assert cs._decode(b'not an image') is None
    assert cs._decode(_png(10, 10)) is None                 # below MIN_PANEL_PX
    assert cs._decode(_png(200, 150, ink=False)) is None    # blank
    assert cs._decode(_png()).mode == 'L'


def test_choose_rows():
    sq = [(200, 150)] * 4
    assert cs.choose_rows(1, [(200, 150)], False) == 1
    assert cs.choose_rows(4, sq, sunday=False) == 1          # four panels: one row
    assert cs.choose_rows(4, sq, sunday=True) == 2           # a Sunday page: two rows
    assert cs.choose_rows(2, sq[:2], sunday=True) in (1, 2)


def test_choose_rows_avoids_a_lone_orphan_panel():
    sizes = [(200, 150)] * 7
    rows = cs.choose_rows(7, sizes, sunday=True)
    per = -(-7 // rows)
    assert 7 - per * (rows - 1) != 1                          # never 3+3+1


def test_stitch_daily_is_one_wide_row():
    imgs = [cs._decode(_png()) for _ in range(4)]
    out = cs.stitch(imgs)
    assert out.mode == 'L' and out.size[0] > out.size[1] * 3
    assert out.getpixel((0, 0)) == 255                        # white margin


def test_stitch_single_panel_passes_through_with_margin():
    img = cs._decode(_png(200, 150))
    assert cs.stitch([img]).size == (200 + 2 * cs.MARGIN, 150 + 2 * cs.MARGIN)


def test_stitch_normalises_mismatched_panel_sizes_and_centres_short_rows():
    imgs = [cs._decode(_png(w, h)) for w, h in
            [(200, 150), (180, 160), (210, 140), (200, 150), (190, 150)]]
    out = cs.stitch(imgs, sunday=True)
    assert out.size[0] > 0 and out.size[1] > 0
    # a 5-panel Sunday is two rows, the short one centred inside the margin
    assert out.getpixel((out.size[0] // 2, out.size[1] - 1)) == 255


def test_cap_size_only_shrinks():
    big = Image.new('L', (3000, 600), 255)
    out = cs.cap_size(big)
    assert out.size[0] <= cs.MAX_W and out.size[1] <= cs.MAX_H
    assert abs(out.size[0] / out.size[1] - 5) < 0.05          # aspect preserved
    small = Image.new('L', (300, 100), 255)
    assert cs.cap_size(small) is small
    tall = cs.cap_size(Image.new('L', (400, 2000), 255))
    assert tall.size[1] <= cs.MAX_H


def test_skip_reason_thresholds():
    assert cs.skip_reason(DAILY, 4) is None
    assert cs.skip_reason(DAILY, cs.MAX_DAILY_PANELS) is None
    assert 'over-segmented' in cs.skip_reason(DAILY, cs.MAX_DAILY_PANELS + 1)
    assert cs.skip_reason(SUNDAY, cs.MAX_SUNDAY_PANELS) is None
    assert 'over-segmented' in cs.skip_reason(SUNDAY, cs.MAX_SUNDAY_PANELS + 1)


def test_build_strip_complete_incomplete_and_skipped():
    img, meta = cs.build_strip(DAILY, _panels(4))
    assert img is not None and meta == {'panels': 4, 'expected': 4, 'incomplete': False}
    gappy = {0: _png(), 3: _png()}                            # panels 1 and 2 are missing
    img, meta = cs.build_strip(DAILY, gappy)
    assert img is not None and meta['incomplete'] and meta['expected'] == 4
    img, meta = cs.build_strip(DAILY, _panels(cs.MAX_DAILY_PANELS + 1))
    assert img is None and meta['skipped'].startswith('over-segmented')
    img, meta = cs.build_strip(DAILY, {0: b'junk', 1: _png(200, 150, ink=False)})
    assert img is None and meta == {'skipped': 'no usable panels'}


@pytest.mark.parametrize('n', [1, 2, 3, 4, 5])
def test_build_strip_any_daily_panel_count(n):
    img, _ = cs.build_strip(DAILY, _panels(n))
    assert img.size[0] <= cs.MAX_W and img.size[1] <= cs.MAX_H


@pytest.mark.parametrize('n', [4, 5, 6, 7, 8, 9])
def test_build_strip_any_sunday_panel_count(n):
    img, _ = cs.build_strip(SUNDAY, _panels(n))
    assert img.size[0] <= cs.MAX_W and img.size[1] <= cs.MAX_H


def test_cache_output_is_readable_by_the_local_cache_source(tmp_path):
    """A built strip saved the way the script saves it loads through LocalCacheSource."""
    from fetch_comic import LocalCacheSource
    img, _ = cs.build_strip(DAILY, _panels(4))
    (tmp_path / 'peanuts').mkdir()
    img.save(tmp_path / 'peanuts' / f'{DAILY}.png', optimize=True)
    src = LocalCacheSource('peanuts', root=str(tmp_path))
    assert src.load(date.fromisoformat(DAILY)) is not None
    assert src.dates_for(11, 7) == [date.fromisoformat(DAILY)]


def test_forced_rows_reflow_a_daily_into_a_block():
    one = cs.build_strip(DAILY, _panels(4))[0]
    two = cs.build_strip(DAILY, _panels(4), daily_rows=2)[0]
    assert one.size[0] / one.size[1] > 3 and two.size[0] / two.size[1] < 2.2
    assert cs.stitch([cs._decode(_png())] * 2, rows=5).size[1] > 0       # capped at the panel count
    # Sundays keep their automatic layout whatever daily_rows says
    assert cs.build_strip(SUNDAY, _panels(8), daily_rows=1)[0].size == \
        cs.build_strip(SUNDAY, _panels(8))[0].size
