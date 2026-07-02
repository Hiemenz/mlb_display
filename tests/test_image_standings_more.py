"""
Extended coverage for src/image_standings.py.

Focus areas not already exercised by tests/test_api_contract.py:
  - _aaa_divisions() pure logic
  - draw_wildcard_header() rounded-rectangle AttributeError fallback (older Pillow)
  - draw_standings_sidebar() AAA-mode branch, malformed-data exception branches,
    and clinch indicators
  - draw_standings_sidebar_fullscreen() (previously ~0% covered): movement
    brackets, tie-break dashes, clinch boxes, AAA-mode column slicing, the
    logo-paste branch, and its own malformed-data exception branches.

Conventions follow tests/test_api_contract.py: local fixture-dict builders,
the needs_pil skip guard, patch('image_standings.load_json_file', ...) /
patch('image_standings.save_off_results') to avoid touching real data files,
and patch('image_standings._logo_small', ...) to avoid touching real
pic/logos/*.png files or any network path (logos aren't committed to git).
"""

from unittest.mock import patch

import pytest

from image_standings import (
    _aaa_divisions,
    draw_playoff_bracket_header,
    draw_wildcard_header,
    draw_standings_sidebar,
    draw_standings_sidebar_fullscreen,
)

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")


ALL_DIVISIONS = [
    'American League East', 'American League Central', 'American League West',
    'National League East', 'National League Central', 'National League West',
    'International League East', 'International League West',
    'Pacific Coast League East', 'Pacific Coast League West',
]


def _team(team_id, div_rank, wins=80, losses=60, clinch=None):
    """Minimal standings team dict matching the standings.json schema."""
    d = {
        'team_id': team_id,
        'divisionRank': str(div_rank),
        'league_record_wins': wins,
        'league_record_losses': losses,
    }
    if clinch is not None:
        d['clinch_indicator'] = clinch
    return d


def _standings(teams_by_division, abbr_map=None):
    """Build a standings_data dict with every known division key present."""
    standings = {d: [] for d in ALL_DIVISIONS}
    standings.update(teams_by_division)
    return {'standings': standings, 'team_abbreviation': abbr_map or {}}


def _blank():
    return Image.new('1', (800, 480), 255)


def _has_dark_pixels(image, x1, y1, x2, y2):
    """Return True if any pixel in region [x1:x2, y1:y2] is black (<128)."""
    region = image.crop((x1, y1, x2, y2)).convert('L')
    return any(p < 128 for p in region.getdata())


# ===========================================================================
# 1. _aaa_divisions() — pure logic, no PIL/mocking required
# ===========================================================================

class TestAaaDivisions:

    def test_left_side_returns_il_and_pcl_east_when_present(self):
        data = _standings({
            'International League East': [_team(1, 1)],
            'Pacific Coast League East': [_team(2, 1)],
        })
        result = _aaa_divisions(data, 'left')
        assert result == ['International League East', 'Pacific Coast League East']

    def test_right_side_returns_il_and_pcl_west_when_present(self):
        data = _standings({
            'International League West': [_team(1, 1)],
            'Pacific Coast League West': [_team(2, 1)],
        })
        result = _aaa_divisions(data, 'right')
        assert result == ['International League West', 'Pacific Coast League West']

    def test_missing_division_key_is_filtered_out(self):
        """If a candidate division key is entirely absent from standings, it's dropped."""
        data = {'standings': {'International League East': [_team(1, 1)]}, 'team_abbreviation': {}}
        assert _aaa_divisions(data, 'left') == ['International League East']

    def test_no_matching_divisions_returns_empty_list(self):
        data = {'standings': {'American League East': []}, 'team_abbreviation': {}}
        assert _aaa_divisions(data, 'left') == []
        assert _aaa_divisions(data, 'right') == []

    def test_empty_division_team_list_still_counts_as_present(self):
        """A division key present with an empty team list still counts as 'present'
        (presence is keyed on dict keys, not on non-empty content)."""
        data = {'standings': {'International League East': []}, 'team_abbreviation': {}}
        assert _aaa_divisions(data, 'left') == ['International League East']

    def test_missing_standings_key_entirely_no_crash(self):
        assert _aaa_divisions({}, 'left') == []


# ===========================================================================
# 2. draw_wildcard_header() — rounded_rectangle AttributeError fallback
# ===========================================================================

@needs_pil
class TestDrawWildcardHeaderFallback:
    """Covers the plain-rectangle fallback used when the installed Pillow lacks
    ImageDraw.rounded_rectangle (older Pillow versions)."""

    def test_rounded_rectangle_unavailable_falls_back_to_plain_rectangle(self):
        al = [{'abbr': f'A{i}', 'team_id': str(i), 'gb': '-'} for i in range(3)]
        nl = [{'abbr': f'N{i}', 'team_id': str(100 + i), 'gb': '-'} for i in range(3)]
        img = _blank()
        with patch('image_standings.ImageDraw.ImageDraw.rounded_rectangle',
                   side_effect=AttributeError("no rounded_rectangle")), \
             patch('image_standings._logo_small', return_value=None):
            result = draw_wildcard_header(img, {'AL': al, 'NL': nl})
        assert result is img
        # AL box top border (3 slots * 24px = 72px wide starting at x=32).
        assert _has_dark_pixels(img, 32, 1, 104, 3)
        # NL box top border (right side, mirrored).
        assert _has_dark_pixels(img, 695, 1, 767, 3)


# ===========================================================================
# 3. draw_standings_sidebar() — AAA-mode branch
# ===========================================================================

@needs_pil
class TestDrawStandingsSidebarAaaMode:
    """AAA-mode branch: _aaa_divisions() lookup + variable-height section stacking."""

    def _render_aaa(self, side, teams_by_division):
        data = _standings(teams_by_division)
        img = _blank()
        with patch('image_standings.load_json_file', return_value={}), \
             patch('image_standings.save_off_results'), \
             patch('image_standings._logo_small', return_value=None):
            result = draw_standings_sidebar(img, data, {}, side=side, league_mode='aaa')
        return img, result

    def test_aaa_left_no_crash_and_returns_image(self):
        img, result = self._render_aaa('left', {
            'International League East': [_team(1, 1), _team(2, 2)],
            'Pacific Coast League East': [_team(3, 1)],
        })
        assert result is img

    def test_aaa_right_variable_height_sections_render(self):
        """More teams in one AAA division than another exercises the variable
        section-height stacking logic (section_heights / row_y_list)."""
        img, _ = self._render_aaa('right', {
            'International League West': [_team(i, i) for i in range(1, 6)],
            'Pacific Coast League West': [_team(20, 1)],
        })
        assert _has_dark_pixels(img, 768, 25, 800, 480)

    def test_aaa_mode_with_no_matching_divisions_no_crash(self):
        """No IL/PCL divisions present at all -> _aaa_divisions returns [] -> the
        'divisions truthy' guard on the variable-height branch is False."""
        data = {'standings': {'American League East': []}, 'team_abbreviation': {}}
        img = _blank()
        with patch('image_standings.load_json_file', return_value={}), \
             patch('image_standings.save_off_results'), \
             patch('image_standings._logo_small', return_value=None):
            result = draw_standings_sidebar(img, data, {}, side='left', league_mode='aaa')
        assert result is img


# ===========================================================================
# 4. draw_standings_sidebar() — malformed-data exception branches
# ===========================================================================

@needs_pil
class TestDrawStandingsSidebarExceptions:
    """Exercise the try/except guards around int()/float() casts of untrusted
    persisted state (standings_prev.json / standings_movement.json)."""

    def _render(self, cur_teams, prev_payload=None, movement_payload=None,
                prev_side_effect=None, div_name='American League East', abbr_map=None):
        data = _standings({div_name: cur_teams}, abbr_map=abbr_map)
        img = _blank()

        def fake_load(fname):
            if fname == 'standings_prev.json':
                if prev_side_effect is not None:
                    raise prev_side_effect
                return prev_payload
            if fname == 'standings_movement.json':
                return movement_payload or {}
            return {}

        with patch('image_standings.load_json_file', side_effect=fake_load), \
             patch('image_standings.save_off_results'), \
             patch('image_standings._logo_small', return_value=None):
            result = draw_standings_sidebar(img, data, {}, side='left')
        return result

    def test_prev_json_load_raises_is_swallowed(self):
        """If load_json_file('standings_prev.json') raises outright, the outer
        except swallows it and rendering proceeds with no previous-state data."""
        cur = [_team(1, 1, wins=10, losses=5)]
        result = self._render(cur, prev_side_effect=RuntimeError("disk error"))
        assert result is not None

    def test_malformed_prev_division_rank_is_swallowed(self):
        """A previous-standings team with a non-numeric divisionRank must not crash
        prev_rank construction (inner ValueError/TypeError except)."""
        cur = [_team(1, 1, wins=10, losses=5), _team(2, 2, wins=9, losses=6)]
        prev_payload = {
            'standings': {
                'American League East': [
                    {'team_id': '1', 'divisionRank': 'bad',
                     'league_record_wins': 10, 'league_record_losses': 5},
                ],
            },
        }
        result = self._render(cur, prev_payload=prev_payload)
        assert result is not None

    def test_malformed_prev_record_in_tie_break_is_swallowed(self):
        """A previous-standings team with a non-numeric win/loss count hits the
        prev_wl_by_tid except branch in tie-break detection without crashing."""
        cur = [_team(1, 1, wins=10, losses=5), _team(2, 2, wins=9, losses=6)]
        prev_payload = {
            'standings': {
                'American League East': [
                    {'team_id': '9', 'divisionRank': '3',
                     'league_record_wins': 'bad', 'league_record_losses': 5},
                ],
            },
        }
        result = self._render(cur, prev_payload=prev_payload)
        assert result is not None

    def test_malformed_current_record_in_tie_break_is_swallowed(self):
        """A current team with a non-numeric win/loss count hits the cur_wl_by_tid
        except branch. It must be the *only* team in the division: the later
        unguarded tie-dash int() cast runs whenever a valid slot looks ahead at
        the next one, so any second team (before or after) would still crash."""
        cur = [
            {'team_id': '2', 'divisionRank': '1',
             'league_record_wins': 'N/A', 'league_record_losses': 6},
        ]
        result = self._render(cur)
        assert result is not None

    def test_malformed_movement_timestamp_is_swallowed(self):
        """A non-numeric stored movement timestamp hits the float() except branch
        without crashing display_movers detection."""
        cur = [_team(1, 1, wins=10, losses=5)]
        result = self._render(cur, movement_payload={'1': 'not-a-number'})
        assert result is not None


# ===========================================================================
# 5. draw_standings_sidebar() — clinch indicator
# ===========================================================================

@needs_pil
class TestDrawStandingsSidebarClinch:

    def _render(self, teams):
        data = _standings({'American League East': teams}, abbr_map={'1': 'NYY'})
        img = _blank()
        with patch('image_standings.load_json_file', return_value={}), \
             patch('image_standings.save_off_results'), \
             patch('image_standings._logo_small', return_value=None):
            draw_standings_sidebar(img, data, {}, side='left')
        return img

    def test_clinch_z_draws_box_around_logo_slot(self):
        img_clinch = self._render([_team(1, 1, wins=100, losses=50, clinch='z')])
        img_plain = self._render([_team(1, 1, wins=100, losses=50)])
        assert img_clinch.tobytes() != img_plain.tobytes(), \
            "Clinch indicator box must add visible pixels not present without it"

    def test_clinch_y_draws_box_at_expected_location(self):
        img = self._render([_team(1, 1, wins=100, losses=50, clinch='y')])
        # logo_x=(32-20)//2=6, y_section=_SIDEBAR_ROW_Y[0]=25 + padding(5)=30 ->
        # box border sits directly on the 20x20 logo slot edges.
        assert _has_dark_pixels(img, 6, 30, 26, 50)

    def test_unrecognized_clinch_value_draws_no_box(self):
        img_unknown = self._render([_team(1, 1, wins=100, losses=50, clinch='x')])
        img_plain = self._render([_team(1, 1, wins=100, losses=50)])
        assert img_unknown.tobytes() == img_plain.tobytes()


# ===========================================================================
# 6. draw_standings_sidebar_fullscreen() — previously ~0% covered
# ===========================================================================

@needs_pil
class TestDrawStandingsSidebarFullscreen:
    """draw_standings_sidebar_fullscreen(): 3-column AL/NL (or AAA) layout used by
    the fullscreen featured-game view. Exercises movement brackets, tie-break
    dashes, clinch boxes, AAA-mode column slicing, the logo-paste branch, and its
    own malformed-data exception branches (same shape as draw_standings_sidebar)."""

    def _canvas(self):
        return Image.new('1', (800, 480), 255)

    def _render(self, side, teams_by_division, prev_payload=None, movement_payload=None,
                prev_side_effect=None, logo_side_effect=None, league_mode='mlb', **kwargs):
        data = _standings(teams_by_division)
        canvas = self._canvas()

        def fake_load(fname):
            if fname == 'standings_prev.json':
                if prev_side_effect is not None:
                    raise prev_side_effect
                return prev_payload
            if fname == 'standings_movement.json':
                return movement_payload or {}
            return {}

        if logo_side_effect is not None:
            logo_patch = patch('image_standings._logo_small', side_effect=logo_side_effect)
        else:
            logo_patch = patch('image_standings._logo_small', return_value=None)

        with patch('image_standings.load_json_file', side_effect=fake_load), \
             patch('image_standings.save_off_results'), \
             logo_patch:
            result = draw_standings_sidebar_fullscreen(
                canvas, data, {}, side=side, league_mode=league_mode, **kwargs)
        return canvas, result

    def test_basic_left_render_no_crash_returns_canvas(self):
        canvas, result = self._render('left', {
            'American League East': [_team(1, 1, wins=90, losses=60)],
        })
        assert result is canvas

    def test_basic_right_render_no_crash_returns_canvas(self):
        canvas, result = self._render('right', {
            'National League East': [_team(1, 1, wins=90, losses=60)],
        })
        assert result is canvas

    def test_mover_gets_bracket_indicator_left(self):
        cur = [
            _team(1, 1, wins=15, losses=5),
            _team(2, 2, wins=12, losses=8),
        ]
        prev_payload = {
            'standings': {
                'American League East': [
                    _team(1, 2, wins=14, losses=5),
                    _team(2, 1, wins=12, losses=7),
                ],
            },
        }
        canvas_mover, _ = self._render(
            'left', {'American League East': cur}, prev_payload=prev_payload)
        canvas_plain, _ = self._render('left', {'American League East': cur})
        assert canvas_mover.tobytes() != canvas_plain.tobytes(), \
            "Mover bracket indicator must add pixels not present without prior standings"

    def test_mover_gets_bracket_indicator_right(self):
        cur = [
            _team(1, 1, wins=15, losses=5),
            _team(2, 2, wins=12, losses=8),
        ]
        prev_payload = {
            'standings': {
                'National League East': [
                    _team(1, 2, wins=14, losses=5),
                    _team(2, 1, wins=12, losses=7),
                ],
            },
        }
        canvas_mover, _ = self._render(
            'right', {'National League East': cur}, prev_payload=prev_payload)
        canvas_plain, _ = self._render('right', {'National League East': cur})
        assert canvas_mover.tobytes() != canvas_plain.tobytes()

    def test_displaced_team_also_gets_bracket_indicator(self):
        """A team pushed down in rank by a mover gets flagged too, even though its
        own record didn't change (the 'displaced team' pass over movers)."""
        cur = [
            _team(1, 1, wins=14, losses=6),
            _team(2, 2, wins=13, losses=6),
        ]
        prev_payload = {
            'standings': {
                'American League East': [
                    _team(1, 2, wins=13, losses=6),
                    _team(2, 1, wins=13, losses=6),
                ],
            },
        }
        canvas_displaced, _ = self._render(
            'left', {'American League East': cur}, prev_payload=prev_payload)
        canvas_plain, _ = self._render('left', {'American League East': cur})
        assert canvas_displaced.tobytes() != canvas_plain.tobytes()

    def test_tie_break_reversal_flags_both_teams(self):
        """Two teams tied in the previous snapshot but now separated must both be
        flagged as movers via the tie-break path, even though neither individually
        satisfies the 'rank changed AND record changed' rule on its own."""
        cur = [
            _team(1, 1, wins=11, losses=8),
            _team(2, 2, wins=10, losses=9),
        ]
        prev_payload = {
            'standings': {
                'American League East': [
                    _team(1, 1, wins=10, losses=9),
                    _team(2, 1, wins=10, losses=9),
                ],
            },
        }
        canvas_tie, _ = self._render(
            'left', {'American League East': cur}, prev_payload=prev_payload)
        canvas_plain, _ = self._render('left', {'American League East': cur})
        assert canvas_tie.tobytes() != canvas_plain.tobytes()

    def test_tied_current_records_draw_dash_separator(self):
        cur_tied = [
            _team(1, 1, wins=10, losses=10),
            _team(2, 2, wins=10, losses=10),
        ]
        cur_untied = [
            _team(1, 1, wins=10, losses=10),
            _team(2, 2, wins=9, losses=10),
        ]
        canvas_tied, _ = self._render('left', {'American League East': cur_tied})
        canvas_untied, _ = self._render('left', {'American League East': cur_untied})
        assert canvas_tied.tobytes() != canvas_untied.tobytes()

    def test_clinch_indicator_draws_box(self):
        cur_clinch = [_team(1, 1, wins=100, losses=50, clinch='z')]
        cur_plain = [_team(1, 1, wins=100, losses=50)]
        canvas_clinch, _ = self._render('left', {'American League East': cur_clinch})
        canvas_plain, _ = self._render('left', {'American League East': cur_plain})
        assert canvas_clinch.tobytes() != canvas_plain.tobytes()

    def test_aaa_mode_uses_up_to_three_divisions_no_crash(self):
        canvas, result = self._render('left', {
            'International League East': [_team(1, 1)],
            'Pacific Coast League East': [_team(2, 1)],
        }, league_mode='aaa')
        assert result is canvas

    def test_logo_paste_branch_invoked(self):
        """Mock _logo_small to return a real (fake) logo image so the paste branch,
        rather than the text fallback, actually executes."""
        fake_logo = Image.new('1', (44, 44), 0)

        def fake_logo_small(abbr, team_id, size=28):
            return fake_logo

        canvas, _ = self._render(
            'left', {'American League East': [_team(1, 1)]},
            logo_side_effect=fake_logo_small)
        # Solid-black 44x44 logo pasted into the first column/slot of the sidebar.
        assert _has_dark_pixels(canvas, 0, 30, 58, 480)

    def test_custom_x_anchor_sidebar_w_and_logo_sz_overrides(self):
        """The real caller (image_featured.py) always overrides x_anchor/sidebar_w/
        logo_sz — exercise that override path explicitly."""
        canvas, result = self._render(
            'right', {'National League East': [_team(1, 1)]},
            x_anchor=602, sidebar_w=198, logo_sz=52)
        assert result is canvas

    def test_prev_json_load_raises_is_swallowed(self):
        canvas, result = self._render(
            'left', {'American League East': [_team(1, 1)]},
            prev_side_effect=RuntimeError("disk error"))
        assert result is canvas

    def test_malformed_prev_division_rank_is_swallowed(self):
        prev_payload = {
            'standings': {
                'American League East': [
                    {'team_id': '9', 'divisionRank': 'bad',
                     'league_record_wins': 10, 'league_record_losses': 5},
                ],
            },
        }
        canvas, result = self._render(
            'left', {'American League East': [_team(1, 1)]}, prev_payload=prev_payload)
        assert result is canvas

    def test_malformed_movement_timestamp_is_swallowed(self):
        canvas, result = self._render(
            'left', {'American League East': [_team(1, 1)]},
            movement_payload={'1': 'not-a-number'})
        assert result is canvas


# ===========================================================================
# draw_playoff_bracket_header
# ===========================================================================

def _series(round_lbl, away_abbr, home_abbr, away_wins=0, home_wins=0, complete=False, winner_abbr=None):
    return {
        'round': round_lbl,
        'away_abbr': away_abbr,
        'home_abbr': home_abbr,
        'away_wins': away_wins,
        'home_wins': home_wins,
        'complete': complete,
        'winner_abbr': winner_abbr,
    }


@needs_pil
class TestDrawPlayoffBracketHeader:
    def _white(self):
        return Image.new('1', (800, 30), 255)

    def test_none_bracket_returns_image_unchanged(self):
        canvas = self._white()
        result = draw_playoff_bracket_header(canvas, None)
        assert result is canvas

    def test_empty_bracket_dict_returns_unchanged(self):
        canvas = self._white()
        result = draw_playoff_bracket_header(canvas, {})
        assert result is canvas

    def test_empty_series_list_returns_unchanged(self):
        canvas = self._white()
        result = draw_playoff_bracket_header(canvas, {'series': []})
        assert result is canvas

    def test_single_active_series_renders(self):
        canvas = self._white()
        bracket = {'series': [_series('WC', 'NYY', 'BOS', away_wins=1, home_wins=0)]}
        result = draw_playoff_bracket_header(canvas, bracket)
        assert isinstance(result, Image.Image)
        # Should have some black pixels (text drawn)
        assert any(px == 0 for px in result.getdata())

    def test_single_complete_series_renders(self):
        canvas = self._white()
        bracket = {'series': [
            _series('WC', 'NYY', 'BOS', away_wins=2, home_wins=0,
                    complete=True, winner_abbr='NYY'),
        ]}
        result = draw_playoff_bracket_header(canvas, bracket)
        assert isinstance(result, Image.Image)

    def test_tied_series_no_leader_renders(self):
        """Tied scores take the non-leader branch (prefix only, no ldr_str)."""
        canvas = self._white()
        bracket = {'series': [_series('DS', 'LAD', 'SF', away_wins=1, home_wins=1)]}
        result = draw_playoff_bracket_header(canvas, bracket)
        assert isinstance(result, Image.Image)

    def test_away_leader_renders(self):
        """Away leading takes away-leader branch (away_wins > home_wins)."""
        canvas = self._white()
        bracket = {'series': [_series('DS', 'LAD', 'SF', away_wins=2, home_wins=1)]}
        result = draw_playoff_bracket_header(canvas, bracket)
        assert isinstance(result, Image.Image)

    def test_home_leader_renders(self):
        """Home leading takes home-leader branch (home_wins > away_wins)."""
        canvas = self._white()
        bracket = {'series': [_series('DS', 'LAD', 'SF', away_wins=1, home_wins=2)]}
        result = draw_playoff_bracket_header(canvas, bracket)
        assert isinstance(result, Image.Image)

    def test_multiple_series_render_with_separators(self):
        canvas = self._white()
        bracket = {
            'series': [
                _series('WC', 'NYY', 'BOS'),
                _series('DS', 'LAD', 'SF', away_wins=2, home_wins=1),
                _series('CS', 'HOU', 'CLE', complete=True, winner_abbr='HOU',
                        away_wins=4, home_wins=2),
                _series('WS', 'NYY', 'HOU'),
            ],
        }
        result = draw_playoff_bracket_header(canvas, bracket)
        assert isinstance(result, Image.Image)

    def test_active_before_complete_in_output(self):
        """Active series should sort before complete ones in the header."""
        canvas = self._white()
        bracket = {
            'series': [
                _series('WC', 'NYY', 'BOS', complete=True, away_wins=2,
                        winner_abbr='NYY'),
                _series('DS', 'LAD', 'SF', away_wins=1),  # active
            ],
        }
        result = draw_playoff_bracket_header(canvas, bracket)
        assert isinstance(result, Image.Image)
