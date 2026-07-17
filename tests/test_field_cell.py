"""Tests for _draw_field_cell in src/image_box.py.

Covers the foul-line geometry fixes (straight 45° lines, no kink from
crossing infield segments) and the infield dirt boundary rendering
(complete D-shape preserved, crossing segments clipped to fair territory).
"""
import pytest

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")


def _make_cell(venue, scale=1):
    """Return a rendered 1-bit cell image for *venue* at *scale*."""
    import image_box
    img = Image.new('1', (150 * scale, 130 * scale), 1)
    draw = ImageDraw.Draw(img)
    image_box._draw_field_cell(draw, img, 0, 0, 150, 130, {'venue': venue}, scale=scale)
    return img


# ---------------------------------------------------------------------------
# Foul-line straightness
# ---------------------------------------------------------------------------

class TestFoulLineStraightness:
    """RF foul line must be a clean straight diagonal with no kink."""

    # American Family Field has an exactly 45° RF pole (244, 244).
    # With round() in _ray_end the endpoint is (143, 51), giving dx=dy=68.
    # At scale=1: HX=75, HY=119. Foul line pixel at x is at y=HY-(x-HX)=194-x.
    #
    # Two regions are legitimately absent from the foul-line path:
    #   x=75-78  — home plate pentagon drawn fill=255 (white) to show interior
    #   x=89-95  — first-base diamond drawn fill=255 for the same reason
    # Both elements intentionally blank the foul line beneath them.

    _HX, _HY = 75, 119

    def _foul_y(self, x):
        return self._HY - (x - self._HX)

    @needs_pil
    def test_rf_foul_line_continuous_between_plate_and_first_base(self):
        """Foul line must be unbroken from just past home plate to first base."""
        img = _make_cell('American Family Field', scale=1)
        pixels = img.load()
        # x=79-88: past the home plate white-fill zone, before first base zone.
        missing = [x for x in range(79, 89) if pixels[x, self._foul_y(x)] != 0]
        assert not missing, f"foul line gap at x={missing}"

    @needs_pil
    def test_rf_foul_line_continuous_past_first_base_to_corner(self):
        """Foul line must be unbroken from past first base to the RF corner."""
        img = _make_cell('American Family Field', scale=1)
        pixels = img.load()
        # x=96-143: past the first-base white-fill zone.
        missing = [x for x in range(96, 143) if pixels[x, self._foul_y(x)] != 0]
        assert not missing, f"foul line gap at x={missing}"

    @needs_pil
    def test_rf_foul_line_no_kink_adjacent_pixel(self):
        """No pixel immediately below the foul line in the arc crossing zone.

        Before the fix, infield polygon segment 4→5 (one endpoint in RF foul
        territory) drew a pixel at (102, 94) — 2 rows below the foul line at
        that x — making the line appear kinked. After Liang-Barsky clipping
        that segment is trimmed to fair territory; the 1px-below position must
        be empty for x=98-104.
        """
        img = _make_cell('American Family Field', scale=1)
        pixels = img.load()
        kink = [
            x for x in range(98, 105)
            if pixels[x, self._foul_y(x) + 1] == 0
        ]
        assert not kink, (
            f"pixel immediately below foul line at x={kink} indicates "
            "kink-causing stray pixel from infield crossing segment"
        )

    @needs_pil
    def test_rf_foul_line_crossing_segment_kink_pixel_removed(self):
        """The specific pre-fix kink pixel must be gone.

        Before Liang-Barsky clipping, infield polygon segment 4→5 (one endpoint
        in RF foul territory) placed a dark pixel at (102, 94). The foul line
        at x=102 is y=92, so this pixel was 2 rows on the foul (home-plate)
        side of the line, creating a visible kink. After the fix that pixel
        must be white.
        """
        img = _make_cell('American Family Field', scale=1)
        pixels = img.load()
        assert pixels[102, 94] != 0, (
            "old kink pixel at (102, 94) is dark — crossing segment still bleeds "
            "into RF foul territory"
        )

    @needs_pil
    def test_rf_foul_line_45degree_slope(self):
        """For a 45° park the run and rise of the foul line must be equal (±1).

        We test by reading two known pixels on the Bresenham path directly —
        not by scanning all columns which would pick up fence labels and mound.
        """
        img = _make_cell('American Family Field', scale=1)
        pixels = img.load()
        # x=80 and x=140 are clear of home plate and first-base zones.
        x_start, x_end = 80, 140
        y_start = self._foul_y(x_start)
        y_end   = self._foul_y(x_end)
        assert pixels[x_start, y_start] == 0, f"foul line pixel missing at ({x_start},{y_start})"
        assert pixels[x_end,   y_end]   == 0, f"foul line pixel missing at ({x_end},{y_end})"
        run  = x_end - x_start
        rise = y_start - y_end
        assert abs(run - rise) <= 1, f"RF foul line slope not 45°: run={run}, rise={rise}"


# ---------------------------------------------------------------------------
# Infield dirt (D-shape completeness)
# ---------------------------------------------------------------------------

class TestInfieldDirt:
    """Infield dirt boundary must draw a complete D-shape."""

    @needs_pil
    def test_infield_arc_visible_at_scale2(self):
        """The outfield-facing arc (top of the D) must have dark pixels."""
        img = _make_cell('American Family Field', scale=2)
        pixels = img.load()
        # The arc spans roughly x=100..200, y=140..200 at scale=2.
        arc_pixels = sum(
            1 for x in range(100, 200) for y in range(140, 200)
            if pixels[x, y] == 0
        )
        assert arc_pixels > 20, "infield arc has too few dark pixels — arc may be missing"

    @needs_pil
    def test_home_plate_arc_visible_at_scale2(self):
        """The home plate arc (bottom of the D) must have dark pixels below HY."""
        img = _make_cell('American Family Field', scale=2)
        pixels = img.load()
        # HY at scale=2 is ~238. The home plate arc extends below it.
        arc_pixels = sum(
            1 for x in range(120, 180) for y in range(235, 260)
            if pixels[x, y] == 0
        )
        assert arc_pixels > 5, "home plate arc has too few dark pixels — arc may be missing"

    @needs_pil
    def test_infield_sides_visible_between_arc_and_plate(self):
        """The RF infield side (connecting arc to home plate) must have pixels.

        Segments 51-64 of the infield polygon are in RF foul territory but must
        still be drawn to give the complete D shape — not filtered out.
        """
        img = _make_cell('American Family Field', scale=2)
        pixels = img.load()
        # RF side runs diagonally from roughly (160, 196) to (204, 234) at scale=2.
        side_pixels = sum(
            1 for x in range(155, 215) for y in range(195, 240)
            if pixels[x, y] == 0
        )
        assert side_pixels > 5, (
            "RF infield side has too few dark pixels — D-shape sides may be missing"
        )

    @needs_pil
    def test_no_crash_for_all_30_parks(self):
        """_draw_field_cell must not raise for any of the 30 MLB stadiums."""
        from stadium_polygons import STADIUM_POLYGONS
        import image_box
        for venue in STADIUM_POLYGONS:
            img = Image.new('1', (150, 130), 1)
            draw = ImageDraw.Draw(img)
            image_box._draw_field_cell(draw, img, 0, 0, 150, 130, {'venue': venue}, scale=1)

    @needs_pil
    def test_unknown_venue_uses_fallback_no_crash(self):
        """An unknown venue falls back gracefully without raising."""
        import image_box
        img = Image.new('1', (150, 130), 1)
        draw = ImageDraw.Draw(img)
        image_box._draw_field_cell(draw, img, 0, 0, 150, 130, {'venue': 'Nonexistent Park'}, scale=1)

    @needs_pil
    def test_infield_dirt_present_at_scale1(self):
        """At scale=1 the infield D must produce dark pixels in the arc region."""
        img = _make_cell('American Family Field', scale=1)
        pixels = img.load()
        # The outfield arc spans roughly x=50..100, y=70..95 at scale=1.
        dark = sum(
            1 for x in range(45, 105) for y in range(70, 98)
            if pixels[x, y] == 0
        )
        assert dark > 5, "infield arc missing — too few dark pixels in outfield-arc region"


# ---------------------------------------------------------------------------
# get_infield_polygon helper
# ---------------------------------------------------------------------------

class TestGetInfieldPolygon:
    def test_returns_polygon_for_known_venue(self):
        from stadium_polygons import get_infield_polygon
        poly = get_infield_polygon('American Family Field')
        assert poly is not None
        assert len(poly) > 10

    def test_fuzzy_match(self):
        from stadium_polygons import get_infield_polygon
        poly = get_infield_polygon('american family field')
        assert poly is not None

    def test_unknown_venue_returns_none(self):
        from stadium_polygons import get_infield_polygon
        assert get_infield_polygon('No Such Park') is None

    def test_infield_polygon_is_closed(self):
        """First and last point should be the same (closed polygon)."""
        from stadium_polygons import get_infield_polygon
        poly = get_infield_polygon('American Family Field')
        assert poly[0] == poly[-1]

    def test_all_major_parks_have_infield_data(self):
        """All MLBAM-sourced parks except Rogers Centre have infield data."""
        from stadium_polygons import STADIUM_POLYGONS, STADIUM_INFIELD_POLYGONS
        allowed_missing = {'Rogers Centre', 'Sutter Health Park'}
        missing = {
            v for v in STADIUM_POLYGONS
            if v not in STADIUM_INFIELD_POLYGONS and v not in allowed_missing
        }
        assert not missing, f"Parks unexpectedly missing infield polygon: {missing}"
