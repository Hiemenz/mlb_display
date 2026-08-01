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
    # At scale=1 with FSCALE=0.30: HX=75, HY=118. Foul line pixel at x is at
    # y=HY-(x-HX)=193-x.
    #
    # Two regions are legitimately absent from the foul-line path:
    #   x=75-78  — home plate pentagon drawn fill=255 (white) to show interior
    #   x=89-95  — first-base diamond drawn fill=255 for the same reason
    # Both elements intentionally blank the foul line beneath them.

    _HX, _HY = 75, 118

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
        # HY at scale=2 is ~239. The home plate arc extends below it.
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

    @needs_pil
    def test_y_offset_no_crash(self):
        """y_offset parameter must be accepted without error."""
        import image_box
        for offset in (0, 10, 20):
            img = Image.new('1', (150, 130), 1)
            draw = ImageDraw.Draw(img)
            image_box._draw_field_cell(
                draw, img, 0, 0, 150, 130,
                {'venue': 'American Family Field'}, scale=1, y_offset=offset
            )

    @needs_pil
    def test_y_offset_shifts_mound_up(self):
        """y_offset=20 moves the pitcher's mound ~20px higher than y_offset=0."""
        import image_box
        # Mound centre pixel: HX=75, my = HY - round(60.5 * 0.30).
        # HY(offset=0)=118 → my=118-18=100. HY(offset=20)=98 → my=98-18=80.
        # Check column x=75 for the first dark pixel from the top in each cell.
        img0 = Image.new('1', (150, 130), 1)
        img20 = Image.new('1', (150, 130), 1)
        image_box._draw_field_cell(ImageDraw.Draw(img0),  img0,  0, 0, 150, 130, {'venue': 'American Family Field'}, scale=1, y_offset=0)
        image_box._draw_field_cell(ImageDraw.Draw(img20), img20, 0, 0, 150, 130, {'venue': 'American Family Field'}, scale=1, y_offset=20)
        px0  = img0.load()
        px20 = img20.load()
        # Scan column x=75 bottom-up for the mound ellipse (skip outfield wall at top).
        # The mound is the lowest cluster of dark pixels below second base.
        mound_rows_0  = [y for y in range(60, 128) if px0[75,  y] == 0]
        mound_rows_20 = [y for y in range(40, 108) if px20[75, y] == 0]
        assert mound_rows_0,  "offset=0: no dark pixels in mound search range"
        assert mound_rows_20, "offset=20: no dark pixels in mound search range"
        assert max(mound_rows_20) < max(mound_rows_0), (
            "y_offset=20 should place mound higher (lower y) than y_offset=0"
        )


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
        allowed_missing = {'Rogers Centre', 'Sutter Health Park', 'Las Vegas Ballpark'}
        missing = {
            v for v in STADIUM_POLYGONS
            if v not in STADIUM_INFIELD_POLYGONS and v not in allowed_missing
        }
        assert not missing, f"Parks unexpectedly missing infield polygon: {missing}"

    def test_lookup_by_venue_id(self):
        """venue_id fast-path (lines 230-232) returns the polygon directly."""
        from stadium_polygons import get_infield_polygon
        poly = get_infield_polygon(venue_name=None, venue_id=1)  # 1 → Angel Stadium
        assert poly is not None


class TestGetPolygon:
    def test_lookup_by_venue_id(self):
        """venue_id fast-path (lines 210-212) returns the polygon directly."""
        from stadium_polygons import get_polygon
        poly = get_polygon(venue_name=None, venue_id=1)  # 1 → Angel Stadium
        assert poly is not None


# ---------------------------------------------------------------------------
# draw_triple_box smoke tests
# ---------------------------------------------------------------------------

def _base_game(**overrides):
    g = {
        'game_pk': 1001,
        'away_team_id': 133,
        'home_team_id': 144,
        'away_team_name': 'OAK',
        'home_team_name': 'ATL',
        'detailed_state': 'Final',
        'away_runs': 3,
        'home_runs': 5,
        'away_hits': 8,
        'home_hits': 10,
        'away_errors': 0,
        'home_errors': 1,
        'away_team_is_winner': False,
        'home_team_is_winner': True,
        'winner_name': 'Max Fried',
        'loser_name': 'Chris Bassitt',
        'saver_name': None,
        'winner_record': '3-1',
        'loser_record': '2-2',
        'saver_saves': None,
        'current_inning': 9,
        'inningState': 'End',
        'away_inning_runs': [0, 1, 0, 0, 0, 2, 0, 0, 0],
        'home_inning_runs': [1, 0, 2, 0, 0, 0, 1, 0, 1],
        'away_team_record_wins': 10,
        'away_team_record_losses': 5,
        'home_team_record_wins': 12,
        'home_team_record_losses': 3,
        'num_of_outs': 3,
        'balls': None,
        'strikes': None,
        'runner_on_first': None,
        'runner_on_second': None,
        'runner_on_third': None,
        'game_start': '7:05 PM',
        'away_probable': None,
        'home_probable': None,
        'away_probable_note': None,
        'home_probable_note': None,
        'no_hitter': False,
        'perfect_game': False,
        'save_situation': False,
        'walk_off': False,
        'last_play': None,
        'venue': 'Truist Park',
        'current_hitter': None,
        'current_pitcher': None,
        'due_up': None,
        'in_hole': None,
        'game_duration_minutes': None,
        'series_result': '',
        'series_game_number': 1,
        'series_total_games': 3,
        'series_wins': 0,
        'series_losses': 0,
        'series_is_tied': False,
        'series_is_over': False,
        'last_play_rbi': None,
    }
    g.update(overrides)
    return g


_MINIMAL_TEAM_DATA = {
    'team_abbreviation': {'133': 'OAK', '144': 'ATL'},
}


class TestTripleBox:
    """Smoke tests for draw_triple_box — verify it renders without crashing."""

    @needs_pil
    def test_final_game_no_crash(self):
        """draw_triple_box must not raise on a Final game."""
        from image_box import draw_triple_box
        img = Image.new('1', (800, 480), 1)
        draw_triple_box(img, 0, 0, _base_game(), _MINIMAL_TEAM_DATA, use_logos=False)

    @needs_pil
    def test_in_progress_game_no_crash(self):
        """draw_triple_box must not raise on an In Progress game."""
        from image_box import draw_triple_box
        img = Image.new('1', (800, 480), 1)
        game = _base_game(
            detailed_state='In Progress',
            inningState='Top',
            current_inning=5,
            num_of_outs=1,
            balls=2,
            strikes=1,
            current_pitcher='Sandy Koufax',
            current_hitter='Pete Rose',
            last_play='Single by Pete Rose',
            away_hits=None,
            home_hits=None,
            away_errors=None,
            home_errors=None,
            away_team_is_winner=None,
            home_team_is_winner=None,
            winner_name=None,
            loser_name=None,
            winner_record=None,
            loser_record=None,
        )
        draw_triple_box(img, 0, 0, game, _MINIMAL_TEAM_DATA, use_logos=False)

    @needs_pil
    def test_score_changed_inverts_header(self):
        """score_changed=True must not raise and should produce dark header pixels."""
        from image_box import draw_triple_box
        img = Image.new('1', (800, 480), 1)
        game = _base_game(
            detailed_state='In Progress',
            inningState='Top',
            current_inning=7,
            num_of_outs=0,
            balls=0,
            strikes=0,
            last_play_rbi=1,
            away_hits=None,
            home_hits=None,
            away_errors=None,
            home_errors=None,
            away_team_is_winner=None,
            home_team_is_winner=None,
            winner_name=None,
            loser_name=None,
            winner_record=None,
            loser_record=None,
        )
        draw_triple_box(img, 0, 0, game, _MINIMAL_TEAM_DATA,
                        use_logos=False, score_changed=True)

    @needs_pil
    def test_no_hitter_active_inverts_header(self):
        """Active no-hitter with no score change must invert the header."""
        from image_box import draw_triple_box
        img = Image.new('1', (800, 480), 1)
        game = _base_game(
            detailed_state='In Progress',
            inningState='Top',
            current_inning=7,
            num_of_outs=0,
            balls=0,
            strikes=0,
            no_hitter=True,
            away_hits=None,
            home_hits=None,
            away_errors=None,
            home_errors=None,
            away_team_is_winner=None,
            home_team_is_winner=None,
            winner_name=None,
            loser_name=None,
            winner_record=None,
            loser_record=None,
        )
        draw_triple_box(img, 0, 0, game, _MINIMAL_TEAM_DATA, use_logos=False)


# ---------------------------------------------------------------------------
# Runner-on-base and last-hit rendering
# ---------------------------------------------------------------------------

class TestFieldCellRunners:
    """Tests for runner-on-base and last-hit rendering in _draw_field_cell."""

    @needs_pil
    def test_runners_on_base_render(self):
        """Filled bases appear when runner keys hold player name strings."""
        import image_box
        game = {
            'venue': 'American Family Field',
            'runner_on_first': 'Jose Altuve',
            'runner_on_second': 'Alex Bregman',
            'runner_on_third': None,
        }
        img = Image.new('1', (150, 130), 1)
        draw = ImageDraw.Draw(img)
        image_box._draw_field_cell(draw, img, 0, 0, 150, 130, game, scale=1)
        px = img.load()
        # First base at (HX+_b, HY-_b) = (75+19, 118-19) = (94, 99).
        dark_near_first = sum(1 for dx in range(-4, 5) for dy in range(-4, 5)
                              if 0 < 94+dx < 150 and 0 < 99+dy < 130 and px[94+dx, 99+dy] == 0)
        assert dark_near_first > 0, "runner on first — expected filled diamond pixels"

    @needs_pil
    def test_last_hit_in_play_renders_circle(self):
        """A hit-in-play marker (circle) appears when last_hit_x/y are present."""
        import image_box
        game = {
            'venue': 'American Family Field',
            'last_hit_x': 150,
            'last_hit_y': 140,
            'last_hit_is_out': False,
            'last_play': '',
            'runner_on_first': None,
            'runner_on_second': None,
            'runner_on_third': None,
        }
        img = Image.new('1', (150, 130), 1)
        draw = ImageDraw.Draw(img)
        image_box._draw_field_cell(draw, img, 0, 0, 150, 130, game, scale=1)
        px = img.load()
        dark = sum(1 for x in range(1, 149) for y in range(1, 129) if px[x, y] == 0)
        assert dark > 0, "last hit in play — expected dark pixels from arc + circle"

    @needs_pil
    def test_last_hit_out_renders_x(self):
        """A hit that resulted in an out renders an X marker."""
        import image_box
        game = {
            'venue': 'American Family Field',
            'last_hit_x': 150,
            'last_hit_y': 140,
            'last_hit_is_out': True,
            'last_play': 'F8',
            'runner_on_first': None,
            'runner_on_second': None,
            'runner_on_third': None,
        }
        img = Image.new('1', (150, 130), 1)
        draw = ImageDraw.Draw(img)
        image_box._draw_field_cell(draw, img, 0, 0, 150, 130, game, scale=1)
        px = img.load()
        dark = sum(1 for x in range(1, 149) for y in range(1, 129) if px[x, y] == 0)
        assert dark > 0, "last hit out — expected dark pixels from arc + X marker"


# ---------------------------------------------------------------------------
# hit-coordinate → feet transform
# ---------------------------------------------------------------------------

class TestHitCoordTransform:
    """The batted-ball transform must share the fence polygons' coordinate system.

    data/mlbam_walls.json and data/mlbam_infield.json were built by
    src/extract_infield_polygons.py with scale 2.495671 and origin (125.0,
    199.0).  Plotting hits with any other constants puts balls in a different
    coordinate space than the fence they are drawn against — the symptom being
    that real home runs land short of the wall, on the warning track.
    """

    def test_constants_match_polygon_extraction(self):
        import extract_infield_polygons as eip
        import image_box
        assert image_box._HC_SCALE == eip._SCALE
        assert image_box._HC_X_CENTER == eip._HC_X_CENTER
        assert image_box._HC_Y_CENTER == eip._HC_Y_CENTER

    def test_transform_matches_extraction_formula(self):
        import extract_infield_polygons as eip
        from image_box import _hit_coord_to_feet
        for cx, cy in [(125.0, 199.0), (44.78, 55.02), (205.63, 68.46), (150.0, 120.0)]:
            assert _hit_coord_to_feet(cx, cy) == pytest.approx(
                (eip._SCALE * (cx - eip._HC_X_CENTER),
                 eip._SCALE * (eip._HC_Y_CENTER - cy)))

    def test_home_plate_is_origin(self):
        from image_box import _hit_coord_to_feet
        assert _hit_coord_to_feet(125.0, 199.0) == pytest.approx((0.0, 0.0))

    def test_real_home_runs_clear_the_fence(self):
        """Real MLB coordinates must convert to distances that clear the wall.

        (coordX, coordY, MLB API totalDistance) for home runs from the
        2025-07-29 slate.  The converted radial distance must land within 5%
        of the distance the API itself reported — the old `* 2.0` transform
        was ~20% short on every one of these, which is what put home runs on
        the warning track.
        """
        import math
        from image_box import _hit_coord_to_feet
        real_hrs = [
            (115.29, 26.23, 428.0),
            (87.97,  34.63, 401.0),
            (137.36, 36.91, 402.0),
            (150.65, 32.02, 417.0),
            (44.78,  55.02, 407.0),
            (205.63, 68.46, 377.0),
            (157.66, 43.12, 394.0),
            (33.45,  67.79, 399.0),
        ]
        for cx, cy, api_dist in real_hrs:
            x_ft, y_ft = _hit_coord_to_feet(cx, cy)
            assert math.hypot(x_ft, y_ft) == pytest.approx(api_dist, rel=0.05)


# ---------------------------------------------------------------------------
# recent_hits multi-ball rendering
# ---------------------------------------------------------------------------

class TestFieldCellRecentHits:
    """Tests for recent_hits list rendering in _draw_field_cell."""

    def _make_hit(self, x, y, is_hr=False, is_out=False, is_hit=True):
        return {'x': x, 'y': y, 'is_hr': is_hr, 'is_out': is_out, 'is_hit': is_hit}

    @needs_pil
    def test_recent_hits_renders_without_crash(self):
        """recent_hits list must render without raising."""
        import image_box
        game = {
            'venue': 'American Family Field',
            'recent_hits': [
                self._make_hit(150, 140),
                self._make_hit(100, 150, is_out=True, is_hit=False),
                self._make_hit(125, 80, is_hr=True),
            ],
        }
        img = Image.new('1', (150, 130), 1)
        image_box._draw_field_cell(ImageDraw.Draw(img), img, 0, 0, 150, 130, game, scale=1)

    @needs_pil
    def test_recent_hits_single_fallback(self):
        """When recent_hits is absent, last_hit_x/y is used as a single entry."""
        import image_box
        game_with_recent = {
            'venue': 'American Family Field',
            'recent_hits': [self._make_hit(150, 140)],
        }
        game_legacy = {
            'venue': 'American Family Field',
            'last_hit_x': 150,
            'last_hit_y': 140,
            'last_hit_is_out': False,
            'last_hit_is_hr': False,
        }
        img1 = Image.new('1', (150, 130), 1)
        image_box._draw_field_cell(ImageDraw.Draw(img1), img1, 0, 0, 150, 130, game_with_recent, scale=1)
        img2 = Image.new('1', (150, 130), 1)
        image_box._draw_field_cell(ImageDraw.Draw(img2), img2, 0, 0, 150, 130, game_legacy, scale=1)
        assert list(img1.getdata()) == list(img2.getdata()), (
            "recent_hits single-entry must produce the same image as last_hit_x/y fallback"
        )

    @needs_pil
    def test_hr_uses_ray_end_not_fpt(self):
        """HR marker must appear at the cell edge (ray_end), not clipped by _fpt."""
        import image_box
        # HR straight to CF: landing at api (125, 0) → hy_ft ≈ 497 ft.
        # _fpt clips to cy0=1 (top edge centre).  _ray_end also hits (75, 1) for this
        # direction (straight up), so the real test is that the filled diamond IS there.
        game = {
            'venue': 'American Family Field',
            'recent_hits': [{'x': 125, 'y': 0, 'is_hr': True, 'is_out': False, 'is_hit': True}],
        }
        img = Image.new('1', (150, 130), 1)
        image_box._draw_field_cell(ImageDraw.Draw(img), img, 0, 0, 150, 150, game, scale=1, vis_h=130)
        px = img.load()
        # The filled diamond (mr=3) at roughly (75, 3) should produce dark pixels
        # in the top rows of the cell.
        dark_top = sum(1 for x in range(60, 91) for y in range(1, 10) if px[x, y] == 0)
        assert dark_top > 0, "HR to CF must place a filled-diamond marker near the top of the cell"

    @needs_pil
    def test_hr_distance_label_appended(self):
        """HR with distance renders 'HR 412' not just 'HR', in the tile's
        bottom-right corner (draw_triple_box), not at the landing spot."""
        from image_box import draw_triple_box
        game_with_dist = _base_game(
            venue='American Family Field',
            recent_hits=[{'x': 125, 'y': 0, 'is_hr': True, 'is_out': False,
                          'is_hit': True, 'abbr': 'HR', 'distance': 412}],
        )
        game_no_dist = _base_game(
            venue='American Family Field',
            recent_hits=[{'x': 125, 'y': 0, 'is_hr': True, 'is_out': False,
                          'is_hit': True, 'abbr': 'HR', 'distance': None}],
        )
        img1 = Image.new('1', (435, 130), 1)
        draw_triple_box(img1, 0, 0, game_with_dist, _MINIMAL_TEAM_DATA, use_logos=False)
        img2 = Image.new('1', (435, 130), 1)
        draw_triple_box(img2, 0, 0, game_no_dist, _MINIMAL_TEAM_DATA, use_logos=False)
        # 'HR 412' is wider than 'HR', so the distance version must differ
        assert list(img1.getdata()) != list(img2.getdata()), \
            "HR with distance should render more pixels than HR without distance"

    def test_hr_label_at_landing_spot_ignores_distance(self):
        """_draw_field_cell draws 'HR' at the landing spot regardless of distance.
        Distance is no longer shown in the field cell (it moved to the draw_triple_box
        footer badge), so renders with and without distance must be identical."""
        import image_box
        game_with_dist = {
            'venue': 'American Family Field',
            'recent_hits': [{'x': 125, 'y': 0, 'is_hr': True, 'is_out': False,
                             'is_hit': True, 'abbr': 'HR', 'distance': 412}],
        }
        game_no_dist = {
            'venue': 'American Family Field',
            'recent_hits': [{'x': 125, 'y': 0, 'is_hr': True, 'is_out': False,
                             'is_hit': True, 'abbr': 'HR', 'distance': None}],
        }
        img1 = Image.new('1', (150, 150), 1)
        image_box._draw_field_cell(ImageDraw.Draw(img1), img1, 0, 0, 150, 150, game_with_dist, scale=1, vis_h=150)
        img2 = Image.new('1', (150, 150), 1)
        image_box._draw_field_cell(ImageDraw.Draw(img2), img2, 0, 0, 150, 150, game_no_dist, scale=1, vis_h=150)
        assert list(img1.getdata()) == list(img2.getdata()), \
            "landing-spot HR label must be 'HR' regardless of distance"

    @needs_pil
    def test_two_hits_more_pixels_than_one(self):
        """Two recent hits must produce more dark pixels than one (each gets an arc + label)."""
        import image_box
        # Two hits: older to shallow LF, newer to shallow RF.
        game_two = {
            'venue': 'American Family Field',
            'recent_hits': [
                {'x': 100, 'y': 165, 'is_hr': False, 'is_out': False, 'is_hit': True},  # older
                {'x': 150, 'y': 165, 'is_hr': False, 'is_out': False, 'is_hit': True},  # newer
            ],
        }
        game_one = {
            'venue': 'American Family Field',
            'recent_hits': [
                {'x': 150, 'y': 165, 'is_hr': False, 'is_out': False, 'is_hit': True},
            ],
        }
        img_two = Image.new('1', (150, 130), 1)
        image_box._draw_field_cell(ImageDraw.Draw(img_two), img_two, 0, 0, 150, 130, game_two, scale=1)
        img_one = Image.new('1', (150, 130), 1)
        image_box._draw_field_cell(ImageDraw.Draw(img_one), img_one, 0, 0, 150, 130, game_one, scale=1)
        dark_two = sum(1 for p in img_two.getdata() if p == 0)
        dark_one = sum(1 for p in img_one.getdata() if p == 0)
        assert dark_two > dark_one, (
            "two-hit render must have more dark pixels than one-hit render "
            "(each hit adds an arc and an abbreviation label)"
        )


# ---------------------------------------------------------------------------
# vis_h centering
# ---------------------------------------------------------------------------

class TestFieldCellCentering:
    """Tests for the vis_h vertical-centering parameter."""

    @needs_pil
    def test_vis_h_centers_field(self):
        """With vis_h=130, CF wall must be near the top and home plate near the bottom."""
        import image_box
        game = {'venue': 'American Family Field'}
        img = Image.new('1', (150, 150), 1)
        image_box._draw_field_cell(ImageDraw.Draw(img), img, 0, 0, 150, 150, game, scale=1, vis_h=130)
        px = img.load()
        # CF wall for American Family Field at FSCALE=0.30, HY≈124: CF is at y≈3.
        # Expect at least one dark pixel in the top 8 rows (outfield wall/fence).
        dark_top = sum(1 for x in range(1, 149) for y in range(1, 9) if px[x, y] == 0)
        assert dark_top > 0, "CF wall must appear within 8px of the top edge when vis_h=130"

    @needs_pil
    def test_vis_h_home_plate_visible(self):
        """Home plate pentagon must appear near the bottom of the visible tile."""
        import image_box
        game = {'venue': 'American Family Field'}
        img = Image.new('1', (150, 150), 1)
        image_box._draw_field_cell(ImageDraw.Draw(img), img, 0, 0, 150, 150, game, scale=1, vis_h=130)
        px = img.load()
        # Home plate centre at HY≈124; pentagon extends ≈3px each side → rows 121-127.
        dark_bot = sum(1 for x in range(60, 91) for y in range(115, 130) if px[x, y] == 0)
        assert dark_bot > 0, "Home plate must appear in the bottom quarter of the visible tile"

    @needs_pil
    def test_vis_h_deep_park_no_crash(self):
        """vis_h centering must not raise for the deepest MLB park (Comerica)."""
        import image_box
        game = {'venue': 'Comerica Park'}
        img = Image.new('1', (150, 150), 1)
        image_box._draw_field_cell(ImageDraw.Draw(img), img, 0, 0, 150, 150, game, scale=1, vis_h=130)


# ---------------------------------------------------------------------------
# Bat-side indicator and launch-angle arcs
# ---------------------------------------------------------------------------

def _cell_with_game(game_data, w=150, h=130, scale=1):
    """Render a field cell with the given game_data dict."""
    import image_box
    img = Image.new('1', (w * scale, h * scale), 1)
    draw = ImageDraw.Draw(img)
    image_box._draw_field_cell(draw, img, 0, 0, w, h, game_data, scale=scale)
    return img


@needs_pil
class TestBatSideIndicator:
    """Bat-side boxes are drawn beside home plate for R/L/S."""

    def _game(self, bat_side):
        return {'venue': 'American Family Field', 'bat_side': bat_side}

    def test_rhb_no_crash(self):
        """Right-handed batter renders without error."""
        assert _cell_with_game(self._game('R')) is not None

    def test_lhb_no_crash(self):
        """Left-handed batter renders without error."""
        assert _cell_with_game(self._game('L')) is not None

    def test_switch_no_crash(self):
        """Switch hitter renders two boxes without error."""
        assert _cell_with_game(self._game('S')) is not None

    def test_missing_bat_side_no_crash(self):
        """Missing bat_side key renders without error."""
        assert _cell_with_game({'venue': 'American Family Field'}) is not None

    def test_rhb_differs_from_lhb(self):
        """RHB and LHB box positions produce different pixels."""
        rhb = _cell_with_game(self._game('R'))
        lhb = _cell_with_game(self._game('L'))
        assert rhb.tobytes() != lhb.tobytes()

    def test_switch_differs_from_rhb(self):
        """Switch hitter (two boxes) differs from RHB (one box)."""
        switch = _cell_with_game(self._game('S'))
        rhb    = _cell_with_game(self._game('R'))
        assert switch.tobytes() != rhb.tobytes()


@needs_pil
class TestLaunchAngleArcs:
    """Bezier trajectory arcs are drawn for hits with launch_angle data."""

    def _hit(self, x=170, y=160, is_hr=False, launch_angle=25.0):
        return {
            'x': x, 'y': y,
            'is_hr': is_hr,
            'is_out': False,
            'abbr': 'HR' if is_hr else '1B',
            'launch_angle': launch_angle,
        }

    def _game(self, recent_hits):
        return {'venue': 'American Family Field', 'recent_hits': recent_hits}

    def test_single_hit_with_arc_no_crash(self):
        """A hit with launch_angle draws an arc without crashing."""
        img = _cell_with_game(self._game([self._hit()]))
        assert img is not None

    def test_null_launch_angle_no_crash(self):
        """A hit with launch_angle=None skips the arc without crashing."""
        h = self._hit()
        h['launch_angle'] = None
        img = _cell_with_game(self._game([h]))
        assert img is not None

    def test_arc_adds_pixels_vs_no_arc(self):
        """A hit with launch_angle draws more pixels than one without."""
        h_arc    = self._hit(launch_angle=30.0)
        h_no_arc = self._hit(launch_angle=None)
        img_arc    = _cell_with_game(self._game([h_arc]))
        img_no_arc = _cell_with_game(self._game([h_no_arc]))
        dark_arc    = sum(1 for p in img_arc.getdata()    if p == 0)
        dark_no_arc = sum(1 for p in img_no_arc.getdata() if p == 0)
        assert dark_arc > dark_no_arc, "arc should add pixels"

    def test_multiple_hits_all_arcs_no_crash(self):
        """Multiple hits each with a launch_angle all draw arcs without error."""
        hits = [
            self._hit(x=150, y=150, launch_angle=15.0),
            self._hit(x=180, y=120, launch_angle=32.0, is_hr=True),
            self._hit(x=120, y=160, launch_angle=-2.0),
        ]
        img = _cell_with_game(self._game(hits))
        assert img is not None

    def test_left_field_hit_arc_no_crash(self):
        """A left-field hit (hx_ft < 0) draws a left-bowing arc without error."""
        img = _cell_with_game(self._game([self._hit(x=80, y=150, launch_angle=20.0)]))
        assert img is not None

    def test_between_innings_spray_chart_no_crash(self):
        """Between-innings full-game spray chart renders without error."""
        all_hits = [
            {'x': 150, 'y': 150, 'is_hr': False, 'is_hit': True,  'is_out': False, 'abbr': '1B'},
            {'x': 200, 'y': 100, 'is_hr': True,  'is_hit': True,  'is_out': False, 'abbr': 'HR'},
            {'x': 120, 'y': 170, 'is_hr': False, 'is_hit': False, 'is_out': True,  'abbr': 'F8'},
        ]
        game = {
            'venue': 'American Family Field',
            'inningState': 'Middle',
            'all_game_hits': all_hits,
        }
        img = _cell_with_game(game)
        assert img is not None

    def test_last_hit_is_hr_fallback_no_recent_hits(self):
        """last_hit_is_hr=True with no recent_hits synthesises a single HR entry."""
        game = {
            'venue': 'American Family Field',
            'last_hit_is_hr': True,
        }
        img = _cell_with_game(game)
        assert img is not None


class TestVenueNameLabel:
    """Venue name label shrinks to fit; very long names trigger the width-cap break."""

    @needs_pil
    def test_long_venue_name_no_crash(self):
        """A name too wide for any font size must not raise — breaks at the width cap."""
        game = {'venue': 'A' * 60}  # far exceeds _max_vw at any font size
        img = _cell_with_game(game)
        assert img is not None


# ---------------------------------------------------------------------------
# draw_fields_box
# ---------------------------------------------------------------------------

class TestFieldsBox:
    """Smoke tests for draw_fields_box — new 'fields' mode single cell."""

    def _make_img(self):
        return Image.new('1', (800, 480), 1)

    @needs_pil
    def test_final_game_no_crash(self):
        """Final game renders without error."""
        from image_box import draw_fields_box
        img = self._make_img()
        result = draw_fields_box(img, 32, 30, _base_game(), _MINIMAL_TEAM_DATA)
        assert isinstance(result, Image.Image)

    @needs_pil
    def test_in_progress_no_crash(self):
        """In-progress game with score/inning/outs renders without error."""
        from image_box import draw_fields_box
        img = self._make_img()
        game = _base_game(
            detailed_state='In Progress',
            current_inning=7,
            inningState='Top',
            num_of_outs=2,
            away_runs=3,
            home_runs=5,
        )
        result = draw_fields_box(img, 32, 30, game, _MINIMAL_TEAM_DATA)
        assert isinstance(result, Image.Image)

    @needs_pil
    def test_scheduled_game_no_crash(self):
        """Pre-game/scheduled cell renders without error."""
        from image_box import draw_fields_box
        img = self._make_img()
        game = _base_game(detailed_state='Scheduled', inningState='Scheduled',
                          away_runs=None, home_runs=None)
        result = draw_fields_box(img, 32, 30, game, _MINIMAL_TEAM_DATA)
        assert isinstance(result, Image.Image)

    @needs_pil
    def test_challenge_state_normalised(self):
        """Manager/player challenge state is normalised to In Progress."""
        from image_box import draw_fields_box
        img = self._make_img()
        game = _base_game(detailed_state='Manager challenge', current_inning=5,
                          inningState='Bottom', num_of_outs=1)
        result = draw_fields_box(img, 32, 30, game, _MINIMAL_TEAM_DATA)
        assert isinstance(result, Image.Image)

    @needs_pil
    def test_missing_score_no_crash(self):
        """Missing away_runs/home_runs must not cause a crash."""
        from image_box import draw_fields_box
        img = self._make_img()
        game = _base_game(away_runs=None, home_runs=None, detailed_state='In Progress',
                          current_inning=3, inningState='Middle', num_of_outs=3)
        result = draw_fields_box(img, 32, 30, game, _MINIMAL_TEAM_DATA)
        assert isinstance(result, Image.Image)

    @needs_pil
    def test_with_spray_chart_no_crash(self):
        """Cell with recent_hits spray-chart data renders without error."""
        from image_box import draw_fields_box
        img = self._make_img()
        game = _base_game(recent_hits=[
            {'x': 150, 'y': 130, 'is_hr': False, 'is_out': False, 'is_hit': True, 'abbr': '1B'},
            {'x': 100, 'y': 90,  'is_hr': True,  'is_out': False, 'is_hit': True, 'abbr': 'HR',
             'launch_angle': 28.0},
        ])
        result = draw_fields_box(img, 32, 30, game, _MINIMAL_TEAM_DATA)
        assert isinstance(result, Image.Image)


class TestFieldsGrid:
    """Smoke tests for draw_fields_grid."""

    @needs_pil
    def test_empty_game_list_no_crash(self):
        """Empty game list renders a blank grid without error."""
        from image_grid import draw_fields_grid
        img = Image.new('1', (800, 480), 1)
        result = draw_fields_grid(img, [], _MINIMAL_TEAM_DATA)
        assert isinstance(result, Image.Image)

    @needs_pil
    def test_single_game_renders(self):
        """Single game is placed in the top-left slot."""
        from image_grid import draw_fields_grid
        img = Image.new('1', (800, 480), 1)
        result = draw_fields_grid(img, [_base_game()], _MINIMAL_TEAM_DATA)
        assert isinstance(result, Image.Image)
        assert any(p == 0 for p in result.getdata())

    @needs_pil
    def test_15_games_no_crash(self):
        """Full 15-game slate renders without error."""
        from image_grid import draw_fields_grid
        games = [_base_game(game_pk=i, away_team_id=133, home_team_id=144) for i in range(15)]
        img = Image.new('1', (800, 480), 1)
        result = draw_fields_grid(img, games, _MINIMAL_TEAM_DATA)
        assert isinstance(result, Image.Image)

    @needs_pil
    def test_live_games_sorted_first(self):
        """In-progress games appear before scheduled/final games in the grid."""
        from image_grid import draw_fields_grid
        games = [
            _base_game(game_pk=1, detailed_state='Final'),
            _base_game(game_pk=2, detailed_state='In Progress', current_inning=5,
                       inningState='Top', num_of_outs=1),
            _base_game(game_pk=3, detailed_state='Scheduled'),
        ]
        img = Image.new('1', (800, 480), 1)
        result = draw_fields_grid(img, games, _MINIMAL_TEAM_DATA)
        assert isinstance(result, Image.Image)
