"""Tests for quadrant_view — grain selection, axis maths, layout, and rendering.

Logos are patched off throughout: pic/logos/*.png are gitignored, so a fresh CI
checkout has none and the real loader would auto-download from the ESPN CDN.
Patching _load_logo_gray to None also exercises the abbreviation fallback, which
is what a logo-less machine actually renders.
"""
import os
import platform
from datetime import datetime
from unittest.mock import patch

import pytest

try:
    from PIL import Image, ImageChops, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")
linux_only = pytest.mark.skipif(
    platform.system() != 'Linux',
    reason="golden references are generated on CI's Linux runner; font "
           "rendering differs enough across OSes that comparing locally "
           "would be noise, not signal.",
)

import quadrant_view as qv

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), 'golden')
FAILURES_DIR = os.path.join(GOLDEN_DIR, '_failures')


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

_TEAMS = [
    ('NYY', 147, 96.0, 3.30, 104.0, 3.80),
    ('BOS', 111, 122.5, 3.10, 100.8, 3.50),
    ('CHC', 112, 124.8, 2.95, 111.8, 4.05),
    ('COL', 115, 88.0, 5.60, 92.0, 5.40),
    ('ATH', 133, 91.0, 6.20, 95.0, 5.80),
    ('WSH', 120, 126.1, 4.52, 113.4, 4.71),
    ('SEA', 136, 82.0, 3.78, 90.2, 3.61),
    ('TOR', 141, 77.2, 3.64, 87.5, 4.02),
]


def _payload(teams=None, label='LAST 30 DAYS'):
    """One grain's payload, shaped like fetch_team_quadrant writes it."""
    teams = teams if teams is not None else _TEAMS
    rows = [{'id': tid, 'abbr': abbr, 'name': abbr, 'wrc': wrc, 'era': era,
             'games': 24, 'was_wrc': was_wrc, 'was_era': was_era}
            for abbr, tid, wrc, era, was_wrc, was_era in teams]
    return {
        'label': label,
        'current': {'start': '2026-07-12', 'end': '2026-08-10', 'label': '7/12 - 8/10'},
        'baseline': {'start': '2026-03-25', 'end': '2026-08-10', 'label': '3/25 - 8/10'},
        'avg': {'wrc': 100.0, 'era': 4.05},
        'teams': rows,
    }


def _data(*grains):
    """A full cache file containing the named grains."""
    return {'grains': {g: _payload(label=g.upper()) for g in (grains or qv.GRAINS)}}


@pytest.fixture
def no_logos():
    """Force the abbreviation fallback so tests never hit the ESPN CDN."""
    with patch.object(qv, '_load_logo_gray', return_value=None), \
         patch.object(qv, '_logo_small', return_value=None):
        yield


# ---------------------------------------------------------------------------
# Grain selection — the "three different views" switch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('grain', ['season', 'month', 'week'])
def test_configured_grain_is_used_verbatim(grain):
    """An explicit grain in config selects that view."""
    assert qv.current_grain({'quadrant_grain': grain}) == grain


def test_grain_is_case_insensitive():
    """Config values are normalised before matching."""
    assert qv.current_grain({'quadrant_grain': 'WEEK'}) == 'week'


@pytest.mark.parametrize('config', [
    {}, None, {'quadrant_grain': ''}, {'quadrant_grain': None},
    {'quadrant_grain': 'decade'},
])
def test_grain_defaults_to_season(config):
    """Missing or nonsense config falls back to the season view."""
    assert qv.current_grain(config) == 'season'


def test_rotate_is_stable_inside_a_window_and_changes_between_them():
    """Rotation is keyed to the clock block, so a render is reproducible."""
    config = {'quadrant_grain': 'rotate', 'quadrant_rotate_minutes': 30}
    first = qv.current_grain(config, now=datetime(2026, 8, 10, 12, 5))
    same_block = qv.current_grain(config, now=datetime(2026, 8, 10, 12, 25))
    assert first == same_block
    assert first in qv.GRAINS

    picks = {qv.current_grain(config, now=datetime(2026, 8, 10, hour, 5))
             for hour in range(24)}
    assert len(picks) > 1, 'rotation should not stick on one grain all day'


def test_rotate_survives_a_bogus_interval():
    """A zero or unparsable interval must not divide by zero."""
    assert qv.current_grain({'quadrant_grain': 'rotate',
                             'quadrant_rotate_minutes': 0}) in qv.GRAINS


# ---------------------------------------------------------------------------
# Axis maths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('value,step,expected', [
    (87.2, 5, 85), (85.0, 5, 85), (0.0, 5, 0), (-3.1, 1, -4), (-3.0, 1, -3),
])
def test_floor_to_step(value, step, expected):
    """Rounding down to the tick grid, including across zero."""
    assert qv._floor_to(value, step) == expected


@pytest.mark.parametrize('value,step,expected', [
    (87.2, 5, 90), (85.0, 5, 85), (0.1, 1, 1),
])
def test_ceil_to_step(value, step, expected):
    """Rounding up leaves exact multiples alone."""
    assert qv._ceil_to(value, step) == expected


def test_axis_bounds_enclose_the_data_on_round_numbers():
    """Bounds pad the data, then snap outward to the chosen step."""
    lo, hi, step = qv._axis_bounds([88.0, 122.0], 0.06, [2, 5, 10, 20], 10.0)
    assert lo <= 88.0 and hi >= 122.0
    assert lo % step == 0 and hi % step == 0


def test_axis_bounds_keep_a_minimum_span():
    """A single clustered value still yields a readable axis, not a zero range."""
    lo, hi, _ = qv._axis_bounds([100.0, 100.0], 0.06, [2, 5, 10, 20], 10.0)
    assert hi - lo >= 1.0


def test_axis_bounds_handle_no_data():
    """An empty axis degrades to a unit range rather than raising."""
    lo, hi, step = qv._axis_bounds([], 0.06, [2, 5], 10.0)
    assert (lo, hi, step) == (0.0, 1.0, 2)


def test_nice_step_grows_until_the_axis_is_readable():
    """Step selection caps the tick count."""
    assert qv._nice_step(300, [2, 5, 10, 20]) == 20
    assert qv._nice_step(12, [2, 5, 10, 20]) == 2


def test_ticks_span_the_axis_inclusively():
    """Both endpoints get a tick."""
    assert qv._ticks(80, 100, 5) == [80, 85, 90, 95, 100]


@pytest.mark.parametrize('value,step,expected', [
    (100.0, 5, '100'), (4.25, 0.25, '4.2'), (4.5, 0.5, '4.5'),
])
def test_tick_formatting_follows_the_step(value, step, expected):
    """Whole steps print as integers; fractional steps get one decimal."""
    assert qv._fmt_tick(value, step) == expected


def test_scale_maps_bounds_onto_the_plot_with_era_increasing_upward():
    """Higher ERA is worse, so it climbs the screen — the source chart's convention."""
    scale = qv._Scale(80.0, 120.0, 3.0, 6.0)
    assert scale.x(80.0) == pytest.approx(qv._PLOT_L)
    assert scale.x(120.0) == pytest.approx(qv._PLOT_R)
    assert scale.y(3.0) == pytest.approx(qv._PLOT_B)
    assert scale.y(6.0) == pytest.approx(qv._PLOT_T)
    assert scale.y(6.0) < scale.y(3.0)


def test_scale_tolerates_a_degenerate_range():
    """Equal bounds must not divide by zero."""
    scale = qv._Scale(100.0, 100.0, 4.0, 4.0)
    assert scale.x(100.0) == pytest.approx(qv._PLOT_L)
    assert scale.y(4.0) == pytest.approx(qv._PLOT_B)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

@needs_pil
def test_overlap_resolution_separates_stacked_logos():
    """Teams landing on the same point are pushed apart, not drawn on top."""
    stacked = [(400.0, 240.0)] * 6
    placed = qv._resolve_overlaps(stacked)
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            dx = placed[i][0] - placed[j][0]
            dy = placed[i][1] - placed[j][1]
            assert (dx * dx + dy * dy) ** 0.5 > 1.0


@needs_pil
def test_overlap_resolution_is_deterministic():
    """Identical input must place identically — the golden test depends on it."""
    stacked = [(400.0, 240.0)] * 6
    assert qv._resolve_overlaps(stacked) == qv._resolve_overlaps(stacked)


@needs_pil
def test_overlap_resolution_keeps_logos_inside_the_plot():
    """Pushed-apart logos stay clear of the axis frame."""
    crowded = [(qv._PLOT_L + 2.0, qv._PLOT_T + 2.0)] * 8
    for x, y in qv._resolve_overlaps(crowded):
        assert qv._PLOT_L + qv._LOGO_R <= x <= qv._PLOT_R - qv._LOGO_R
        assert qv._PLOT_T + qv._LOGO_R <= y <= qv._PLOT_B - qv._LOGO_R


@needs_pil
def test_widely_spaced_points_are_left_alone():
    """Relaxation is a no-op when nothing overlaps."""
    spread = [(100.0, 100.0), (400.0, 300.0)]
    assert qv._resolve_overlaps(spread) == spread


# ---------------------------------------------------------------------------
# Arrows
# ---------------------------------------------------------------------------

def _arrow_ink(tail, head):
    """Draw one arrow on a blank canvas and count the black pixels."""
    image = Image.new('1', (qv.EPD_WIDTH, qv.EPD_HEIGHT), 1)
    qv._draw_arrow(ImageDraw.Draw(image), tail, head)
    return sum(1 for p in image.getdata() if p == 0)


@needs_pil
def test_a_real_move_draws_an_arrow():
    """A team that moved gets a shaft, a tail dot, and a head."""
    assert _arrow_ink((200.0, 200.0), (320.0, 260.0)) > 0


@needs_pil
def test_a_negligible_move_draws_nothing():
    """Sub-threshold jitter is suppressed so the plot stays readable."""
    assert _arrow_ink((200.0, 200.0), (202.0, 201.0)) == 0


@needs_pil
def test_a_move_swallowed_by_the_logo_draws_nothing():
    """When the tail sits under the logo there is no shaft worth drawing."""
    assert _arrow_ink((200.0, 200.0), (200.0, 211.0)) == 0


@needs_pil
def test_long_arrows_are_capped_but_keep_their_bearing():
    """The week grain's converging tails are truncated, not redirected."""
    image = Image.new('1', (qv.EPD_WIDTH, qv.EPD_HEIGHT), 1)
    qv._draw_arrow(ImageDraw.Draw(image), (100.0, 240.0), (700.0, 240.0))
    columns = [x for x in range(qv.EPD_WIDTH)
               if any(image.getpixel((x, y)) == 0 for y in range(230, 251))]
    # Ink starts near the cap, not back at the true tail 600px away.
    assert min(columns) > 700 - qv._MAX_ARROW_PX - 5
    assert max(columns) <= 700


# ---------------------------------------------------------------------------
# Logo markers
# ---------------------------------------------------------------------------

@needs_pil
def test_logo_marker_thresholds_to_the_target_ink_share():
    """A gradient logo comes back roughly _INK_TARGET black, not a solid disc."""
    gradient = Image.linear_gradient('L').resize((60, 60))
    with patch.object(qv, '_load_logo_gray', return_value=gradient):
        marker = qv._logo_marker('NYY', 147)
    black = sum(1 for p in marker.getdata() if p == 0)
    assert 0.15 < black / (marker.width * marker.height) < 0.6


@needs_pil
def test_logo_marker_falls_back_when_there_is_no_artwork(no_logos):
    """No logo file anywhere means no marker image."""
    assert qv._logo_marker('NYY', 147) is None


@needs_pil
def test_logo_marker_falls_back_on_an_empty_image():
    """A zero-pixel logo has no histogram to threshold."""
    with patch.object(qv, '_load_logo_gray', return_value=Image.new('L', (0, 0))), \
         patch.object(qv, '_logo_small', return_value='fallback') as small:
        assert qv._logo_marker('NYY', 147) == 'fallback'
    small.assert_called_once()


@needs_pil
def test_team_marker_draws_the_abbreviation_without_a_logo(no_logos):
    """The logo-less fallback still identifies the team."""
    image = Image.new('1', (qv.EPD_WIDTH, qv.EPD_HEIGHT), 1)
    qv._team_marker(image, ImageDraw.Draw(image), {'abbr': 'NYY', 'id': 147}, (400, 240))
    assert any(p == 0 for p in image.getdata())


@needs_pil
def test_team_marker_pastes_a_logo_when_one_exists():
    """With artwork present the logo is pasted instead of the text box."""
    logo = Image.new('1', (qv._LOGO_SIZE, qv._LOGO_SIZE), 0)
    image = Image.new('1', (qv.EPD_WIDTH, qv.EPD_HEIGHT), 1)
    with patch.object(qv, '_logo_marker', return_value=logo):
        qv._team_marker(image, ImageDraw.Draw(image), {'abbr': 'NYY', 'id': 147}, (400, 240))
    assert image.getpixel((400, 240)) == 0


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

@needs_pil
def test_render_produces_a_full_screen_1bit_image(no_logos):
    """The panel expects exactly 800x480 in mode '1'."""
    image = qv.render_quadrant_view(_data(), grain='month')
    assert image.size == (qv.EPD_WIDTH, qv.EPD_HEIGHT)
    assert image.mode == '1'
    assert any(p == 0 for p in image.getdata())


@needs_pil
def test_render_selects_the_configured_grain(no_logos):
    """Config drives which of the three views is drawn."""
    with patch.object(qv, 'current_grain', return_value='week') as chooser:
        qv.render_quadrant_view(_data(), config={'quadrant_grain': 'week'})
    chooser.assert_called_once()


@needs_pil
def test_render_falls_back_when_the_configured_grain_is_missing(no_logos):
    """A partial fetch shows the grain that did arrive rather than failing."""
    image = qv.render_quadrant_view(_data('week'), grain='season')
    assert image.size == (qv.EPD_WIDTH, qv.EPD_HEIGHT)


@needs_pil
@pytest.mark.parametrize('data', [None, {}, {'grains': {}}])
def test_render_rejects_empty_data(data):
    """No data raises so render_scoreboard can fall back instead of showing a blank plot."""
    with pytest.raises(ValueError):
        qv.render_quadrant_view(data)


@needs_pil
def test_render_rejects_a_grain_with_no_teams():
    """An empty team list is not a chart."""
    with pytest.raises(ValueError):
        qv.render_quadrant_view({'grains': {'season': _payload(teams=[])}}, grain='season')


@needs_pil
def test_render_handles_teams_without_a_baseline(no_logos):
    """Teams missing a baseline point are plotted without an arrow."""
    teams = [('NYY', 147, 96.0, 3.30, None, None),
             ('BOS', 111, 122.5, 3.10, 100.8, 3.50)]
    image = qv.render_quadrant_view({'grains': {'season': _payload(teams=teams)}},
                                    grain='season')
    assert image.size == (qv.EPD_WIDTH, qv.EPD_HEIGHT)


@needs_pil
def test_render_supplies_defaults_for_a_missing_average(no_logos):
    """A payload without league means still draws its crosshair."""
    payload = _payload()
    del payload['avg']
    image = qv.render_quadrant_view({'grains': {'season': payload}}, grain='season')
    assert image.size == (qv.EPD_WIDTH, qv.EPD_HEIGHT)


@needs_pil
def test_dark_mode_inverts_the_render(no_logos):
    """Night mode flips the panel, same as the other full-screen views."""
    light = qv.render_quadrant_view(_data(), grain='month')
    dark = qv.render_quadrant_view(_data(), grain='month', dark_mode=True)
    assert ImageChops.difference(light.convert('L'), dark.convert('L')).getbbox() is not None
    light_black = sum(1 for p in light.getdata() if p == 0)
    dark_black = sum(1 for p in dark.getdata() if p == 0)
    assert dark_black > light_black


@needs_pil
def test_axes_skip_ticks_that_fall_outside_the_plot():
    """Rounding can push a tick a pixel past the frame — those are dropped, not clipped."""
    image = Image.new('1', (qv.EPD_WIDTH, qv.EPD_HEIGHT), 1)
    draw = ImageDraw.Draw(image)
    # Steps that don't divide the range evenly put the last tick beyond the axis.
    scale = qv._Scale(80.0, 120.0, 3.0, 6.0)
    qv._draw_axes(image, draw, scale, 15, 2.0, {'wrc': 100.0, 'era': 4.5})

    # Nothing was drawn outside the frame despite the overshooting ticks.
    assert all(image.getpixel((x, qv._PLOT_T - 6)) == 1
               for x in range(qv._PLOT_L, qv._PLOT_R))


@needs_pil
def test_dashed_line_draws_both_orientations():
    """The average crosshair uses horizontal and vertical dashes."""
    image = Image.new('1', (200, 200), 1)
    draw = ImageDraw.Draw(image)
    qv._dashed_line(draw, (10, 50), (190, 50))
    qv._dashed_line(draw, (100, 10), (100, 190))
    row = [image.getpixel((x, 50)) for x in range(10, 190)]
    assert 0 in row and 1 in row, 'a dashed line has both ink and gaps'
    column = [image.getpixel((100, y)) for y in range(10, 190)]
    assert 0 in column and 1 in column


# ---------------------------------------------------------------------------
# Golden image
# ---------------------------------------------------------------------------

def _assert_matches_golden(actual, name, update, tolerance=0.003):
    """Diff against tests/golden/<name>.png, or rewrite it under --update-golden."""
    golden_path = os.path.join(GOLDEN_DIR, f'{name}.png')

    if update:
        os.makedirs(GOLDEN_DIR, exist_ok=True)
        actual.save(golden_path)
        return

    if not os.path.exists(golden_path):
        pytest.fail(
            f"No golden reference at {golden_path}. Generate it with "
            f"`pytest tests/test_quadrant_view.py --update-golden` on Linux."
        )

    expected = Image.open(golden_path)
    diff = ImageChops.difference(actual.convert('L'), expected.convert('L'))
    nonzero = sum(1 for px in diff.getdata() if px != 0)
    ratio = nonzero / (diff.size[0] * diff.size[1])

    if ratio > tolerance:
        os.makedirs(FAILURES_DIR, exist_ok=True)
        actual.save(os.path.join(FAILURES_DIR, f'{name}_actual.png'))

    assert ratio <= tolerance, (
        f"{name}: {ratio:.4%} of pixels differ from {golden_path} "
        f"(tolerance {tolerance:.4%}). Actual render saved to "
        f"tests/golden/_failures/{name}_actual.png for comparison."
    )


@pytest.fixture
def golden_update(request):
    """Whether --update-golden was passed."""
    return request.config.getoption('--update-golden')


@needs_pil
@linux_only
def test_golden_quadrant(golden_update, no_logos):
    """Full-chart regression: axes, crosshair, corner captions, arrows, markers."""
    image = qv.render_quadrant_view(_data(), grain='month')
    _assert_matches_golden(image, 'quadrant_month', golden_update)
