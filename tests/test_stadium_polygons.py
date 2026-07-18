"""Tests for src/stadium_polygons.py — outfield wall polygon data and helpers."""
import json
import math

import pytest

import stadium_polygons as sp


# ===========================================================================
# _cartesian_to_polar
# ===========================================================================

class TestCartesianToPolar:
    def test_straight_center_field(self):
        """Straight center field."""
        # x=0, y=400 -> straight-away CF: dist=400, angle=0
        result = sp._cartesian_to_polar([(0.0, 400.0)])
        assert result == [(400.0, 0.0)]

    def test_right_field_positive_angle(self):
        """Right field positive angle."""
        # x positive (RF side) -> positive angle
        result = sp._cartesian_to_polar([(300.0, 300.0)])
        dist, angle = result[0]
        assert dist == pytest.approx(math.sqrt(300**2 + 300**2), abs=0.1)
        assert angle == pytest.approx(45.0, abs=0.1)

    def test_left_field_negative_angle(self):
        """Left field negative angle."""
        # x negative (LF side) -> negative angle
        result = sp._cartesian_to_polar([(-300.0, 300.0)])
        dist, angle = result[0]
        assert angle == pytest.approx(-45.0, abs=0.1)

    def test_multiple_points(self):
        """Multiple points."""
        pts = [(-233.3, 233.3), (0.0, 403.0), (229.8, 229.8)]
        result = sp._cartesian_to_polar(pts)
        assert len(result) == 3
        # Center point is straight away (angle ~0)
        assert result[1][1] == pytest.approx(0.0, abs=0.1)

    def test_rounding(self):
        """Rounding."""
        result = sp._cartesian_to_polar([(100.0, 100.0)])
        dist, angle = result[0]
        assert dist == round(dist, 1)
        assert angle == round(angle, 2)


# ===========================================================================
# dimensions_to_polygon (inverse of the above, roughly)
# ===========================================================================

class TestDimensionsToPolygon:
    def test_straight_center_field(self):
        """Straight center field."""
        result = sp.dimensions_to_polygon([(400.0, 0.0)])
        assert result == [[0.0, 400.0]]

    def test_left_foul_pole(self):
        """Left foul pole."""
        # -45 deg = LF foul pole -> negative x
        result = sp.dimensions_to_polygon([(330.0, -45.0)])
        x, y = result[0]
        assert x < 0
        assert y > 0

    def test_right_foul_pole(self):
        """Right foul pole."""
        result = sp.dimensions_to_polygon([(330.0, 45.0)])
        x, y = result[0]
        assert x > 0
        assert y > 0

    def test_roundtrip_with_cartesian_to_polar(self):
        """Roundtrip with cartesian to polar."""
        original = [(-233.3, 233.3), (0.0, 403.0), (229.8, 229.8)]
        polar = sp._cartesian_to_polar(original)
        back = sp.dimensions_to_polygon(polar)
        for (ox, oy), (bx, by) in zip(original, back):
            assert bx == pytest.approx(ox, abs=0.5)
            assert by == pytest.approx(oy, abs=0.5)

    def test_multiple_dims(self):
        """Multiple dims."""
        result = sp.dimensions_to_polygon([(300.0, -30.0), (400.0, 0.0), (300.0, 30.0)])
        assert len(result) == 3


# ===========================================================================
# get_polygon
# ===========================================================================

class TestGetPolygon:
    def test_exact_match(self):
        """Exact match."""
        result = sp.get_polygon('Sutter Health Park')
        assert result is not None
        assert result == sp.STADIUM_POLYGONS['Sutter Health Park']

    def test_case_insensitive_match(self):
        """Case insensitive match."""
        result = sp.get_polygon('sutter health park')
        assert result is not None
        assert result == sp.STADIUM_POLYGONS['Sutter Health Park']

    def test_fuzzy_substring_match(self):
        """Fuzzy substring match."""
        # A substring of a known venue name should still match
        result = sp.get_polygon('Wrigley')
        assert result is not None
        assert result == sp.STADIUM_POLYGONS['Wrigley Field']

    def test_unknown_venue_returns_none(self):
        """Unknown venue returns none."""
        assert sp.get_polygon('Nonexistent Stadium XYZ') is None

    def test_empty_string_returns_none_or_no_crash(self):
        """Empty string returns none or no crash."""
        # Empty string is a substring of everything under `lower in k.lower()`,
        # so it will actually match the first stadium — just ensure no crash.
        result = sp.get_polygon('')
        assert result is None or isinstance(result, list)


# ===========================================================================
# export_json
# ===========================================================================

class TestExportJson:
    def test_writes_valid_json_array(self, tmp_path):
        """Writes valid json array."""
        out_path = tmp_path / 'out.json'
        result_path = sp.export_json(str(out_path))
        assert result_path == str(out_path)
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert isinstance(data, list)
        assert len(data) == len(sp.STADIUM_POLYGONS)

    def test_record_shape(self, tmp_path):
        """Record shape."""
        out_path = tmp_path / 'out.json'
        sp.export_json(str(out_path))
        data = json.loads(out_path.read_text())
        for rec in data:
            assert set(rec.keys()) == {'stadium', 'team', 'wall_polygon'}
            assert isinstance(rec['wall_polygon'], list)

    def test_known_team_mapping_present(self, tmp_path):
        """Known team mapping present."""
        out_path = tmp_path / 'out.json'
        sp.export_json(str(out_path))
        data = json.loads(out_path.read_text())
        by_name = {rec['stadium']: rec for rec in data}
        assert by_name['Wrigley Field']['team'] == 'Chicago Cubs'

    def test_creates_parent_directories(self, tmp_path):
        """Creates parent directories."""
        out_path = tmp_path / 'nested' / 'dir' / 'out.json'
        sp.export_json(str(out_path))
        assert out_path.exists()

    def test_unmapped_team_defaults_to_empty_string(self, tmp_path):
        """Unmapped team defaults to empty string."""
        out_path = tmp_path / 'out.json'
        sp.export_json(str(out_path))
        data = json.loads(out_path.read_text())
        # Sutter Health Park is mapped; verify no KeyError-style crash and
        # that any name not in TEAM_NAMES would get '' (can't force this
        # without mutating module state, so just confirm well-formed output).
        assert all(isinstance(rec['team'], str) for rec in data)


# ===========================================================================
# Module-level data sanity
# ===========================================================================

class TestLoadMlbamWalls:
    def test_missing_file_returns_empty_dict(self):
        """When the JSON file doesn't exist, _load_polygon_json returns {}."""
        from unittest.mock import patch
        with patch('os.path.exists', return_value=False):
            result = sp._load_polygon_json(sp._MLBAM_WALLS_PATH)
        assert result == {}


class TestModuleData:
    def test_sutter_health_park_present(self):
        """Sutter health park present."""
        assert 'Sutter Health Park' in sp.STADIUM_POLYGONS

    def test_ballpark_dimensions_mirrors_polygons(self):
        """Ballpark dimensions mirrors polygons."""
        assert set(sp.BALLPARK_DIMENSIONS.keys()) == set(sp.STADIUM_POLYGONS.keys())

    def test_team_names_cover_sutter(self):
        """Team names cover sutter."""
        assert sp.TEAM_NAMES.get('Sutter Health Park') == 'Oakland Athletics'
