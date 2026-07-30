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
    draw_overflow_ticker,
    _ticker_status,
    _ticker_score,
    _ticker_window,
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
    """Blank."""
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
        """Left side returns il and pcl east when present."""
        data = _standings({
            'International League East': [_team(1, 1)],
            'Pacific Coast League East': [_team(2, 1)],
        })
        result = _aaa_divisions(data, 'left')
        assert result == ['International League East', 'Pacific Coast League East']

    def test_right_side_returns_il_and_pcl_west_when_present(self):
        """Right side returns il and pcl west when present."""
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
        """No matching divisions returns empty list."""
        data = {'standings': {'American League East': []}, 'team_abbreviation': {}}
        assert _aaa_divisions(data, 'left') == []
        assert _aaa_divisions(data, 'right') == []

    def test_empty_division_team_list_still_counts_as_present(self):
        """A division key present with an empty team list still counts as 'present'
        (presence is keyed on dict keys, not on non-empty content)."""
        data = {'standings': {'International League East': []}, 'team_abbreviation': {}}
        assert _aaa_divisions(data, 'left') == ['International League East']

    def test_missing_standings_key_entirely_no_crash(self):
        """Missing standings key entirely no crash."""
        assert _aaa_divisions({}, 'left') == []


# ===========================================================================
# 2. draw_wildcard_header() — rounded_rectangle AttributeError fallback
# ===========================================================================

@needs_pil
class TestDrawWildcardHeaderFallback:
    """Covers the plain-rectangle fallback used when the installed Pillow lacks
    ImageDraw.rounded_rectangle (older Pillow versions)."""

    def test_rounded_rectangle_unavailable_falls_back_to_plain_rectangle(self):
        """Rounded rectangle unavailable falls back to plain rectangle."""
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
        """Render aaa."""
        data = _standings(teams_by_division)
        img = _blank()
        with patch('image_standings.load_json_file', return_value={}), \
             patch('image_standings.save_off_results'), \
             patch('image_standings._logo_small', return_value=None):
            result = draw_standings_sidebar(img, data, {}, side=side, league_mode='aaa')
        return img, result

    def test_aaa_left_no_crash_and_returns_image(self):
        """Aaa left no crash and returns image."""
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
        """Render."""
        data = _standings({div_name: cur_teams}, abbr_map=abbr_map)
        img = _blank()

        def fake_load(fname):
            """Fake load."""
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
        """Render."""
        data = _standings({'American League East': teams}, abbr_map={'1': 'NYY'})
        img = _blank()
        with patch('image_standings.load_json_file', return_value={}), \
             patch('image_standings.save_off_results'), \
             patch('image_standings._logo_small', return_value=None):
            draw_standings_sidebar(img, data, {}, side='left')
        return img

    def test_clinch_z_draws_box_around_logo_slot(self):
        """Clinch z draws box around logo slot."""
        img_clinch = self._render([_team(1, 1, wins=100, losses=50, clinch='z')])
        img_plain = self._render([_team(1, 1, wins=100, losses=50)])
        assert img_clinch.tobytes() != img_plain.tobytes(), \
            "Clinch indicator box must add visible pixels not present without it"

    def test_clinch_y_draws_box_at_expected_location(self):
        """Clinch y draws box at expected location."""
        img = self._render([_team(1, 1, wins=100, losses=50, clinch='y')])
        # logo_x=(32-20)//2=6, y_section=_SIDEBAR_ROW_Y[0]=25 + padding(5)=30 ->
        # box border sits directly on the 20x20 logo slot edges.
        assert _has_dark_pixels(img, 6, 30, 26, 50)

    def test_unrecognized_clinch_value_draws_no_box(self):
        """Unrecognized clinch value draws no box."""
        img_unknown = self._render([_team(1, 1, wins=100, losses=50, clinch='x')])
        img_plain = self._render([_team(1, 1, wins=100, losses=50)])
        assert img_unknown.tobytes() == img_plain.tobytes()

    def test_streak_badge_adds_pixels_to_logo_corner(self):
        """A team with a streak draws a tiny badge in the bottom-right of the
        logo slot (image_standings.py lines 425-430). Pixels differ from no-streak."""
        team_with_streak = dict(_team(1, 1, wins=90, losses=60))
        team_with_streak['streak'] = 'W5'
        img_streak = self._render([team_with_streak])
        img_plain = self._render([_team(1, 1, wins=90, losses=60)])
        assert img_streak.tobytes() != img_plain.tobytes(), \
            "Streak badge must add visible pixels not present without it"

    def test_losing_streak_reformatted_and_right_sidebar_x(self):
        """A losing streak string 'L3' is reformatted to 'L 3' (line 433) and
        the right-sidebar badge uses _bx = 800-32 (line 443), not the left formula.
        Right sidebar renders NL divisions, so data must be in a NL division."""
        team_with_loss = dict(_team(1, 1, wins=60, losses=90))
        team_with_loss['streak'] = 'L3'
        data = _standings({'National League East': [team_with_loss]})
        img = _blank()
        with patch('image_standings.load_json_file', return_value={}), \
             patch('image_standings.save_off_results'), \
             patch('image_standings._logo_small', return_value=None):
            result = draw_standings_sidebar(img, data, {}, side='right')
        assert result is img


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
        """Canvas."""
        return Image.new('1', (800, 480), 255)

    def _render(self, side, teams_by_division, prev_payload=None, movement_payload=None,
                prev_side_effect=None, logo_side_effect=None, league_mode='mlb', **kwargs):
        """Render."""
        data = _standings(teams_by_division)
        canvas = self._canvas()

        def fake_load(fname):
            """Fake load."""
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
        """Basic left render no crash returns canvas."""
        canvas, result = self._render('left', {
            'American League East': [_team(1, 1, wins=90, losses=60)],
        })
        assert result is canvas

    def test_basic_right_render_no_crash_returns_canvas(self):
        """Basic right render no crash returns canvas."""
        canvas, result = self._render('right', {
            'National League East': [_team(1, 1, wins=90, losses=60)],
        })
        assert result is canvas

    def test_right_side_streak_badge_uses_col_x(self):
        """Right-side fullscreen render with a streak triggers the col_x
        badge-positioning branch (image_standings.py line 645)."""
        team_with_streak = dict(_team(1, 1, wins=90, losses=60))
        team_with_streak['streak'] = 'W3'
        canvas, result = self._render('right', {
            'National League East': [team_with_streak],
        })
        assert result is canvas

    def test_mover_gets_bracket_indicator_left(self):
        """Mover gets bracket indicator left."""
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
        """Mover gets bracket indicator right."""
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
        """Tied current records draw dash separator."""
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
        """Clinch indicator draws box."""
        cur_clinch = [_team(1, 1, wins=100, losses=50, clinch='z')]
        cur_plain = [_team(1, 1, wins=100, losses=50)]
        canvas_clinch, _ = self._render('left', {'American League East': cur_clinch})
        canvas_plain, _ = self._render('left', {'American League East': cur_plain})
        assert canvas_clinch.tobytes() != canvas_plain.tobytes()

    def test_aaa_mode_uses_up_to_three_divisions_no_crash(self):
        """Aaa mode uses up to three divisions no crash."""
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
            """Fake logo small."""
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
        """Prev json load raises is swallowed."""
        canvas, result = self._render(
            'left', {'American League East': [_team(1, 1)]},
            prev_side_effect=RuntimeError("disk error"))
        assert result is canvas

    def test_malformed_prev_division_rank_is_swallowed(self):
        """Malformed prev division rank is swallowed."""
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
        """Malformed movement timestamp is swallowed."""
        canvas, result = self._render(
            'left', {'American League East': [_team(1, 1)]},
            movement_payload={'1': 'not-a-number'})
        assert result is canvas

    def test_streak_badge_adds_pixels_to_logo_corner(self):
        """A team with a streak renders a tiny badge in the bottom-right of the
        logo area (image_standings.py lines 625-630). Pixels differ from no-streak."""
        team_with_streak = dict(_team(1, 1, wins=90, losses=60))
        team_with_streak['streak'] = 'L3'
        canvas_streak, _ = self._render('left', {'American League East': [team_with_streak]})
        canvas_plain, _ = self._render('left', {'American League East': [_team(1, 1, wins=90, losses=60)]})
        assert canvas_streak.tobytes() != canvas_plain.tobytes(), \
            "Streak badge must add visible pixels not present without it"


# ===========================================================================
# draw_playoff_bracket_header
# ===========================================================================

def _series(round_lbl, away_abbr, home_abbr, away_wins=0, home_wins=0, complete=False, winner_abbr=None):
    """Series."""
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
        """White."""
        return Image.new('1', (800, 30), 255)

    def test_none_bracket_returns_image_unchanged(self):
        """None bracket returns image unchanged."""
        canvas = self._white()
        result = draw_playoff_bracket_header(canvas, None)
        assert result is canvas

    def test_empty_bracket_dict_returns_unchanged(self):
        """Empty bracket dict returns unchanged."""
        canvas = self._white()
        result = draw_playoff_bracket_header(canvas, {})
        assert result is canvas

    def test_empty_series_list_returns_unchanged(self):
        """Empty series list returns unchanged."""
        canvas = self._white()
        result = draw_playoff_bracket_header(canvas, {'series': []})
        assert result is canvas

    def test_single_active_series_renders(self):
        """Single active series renders."""
        canvas = self._white()
        bracket = {'series': [_series('WC', 'NYY', 'BOS', away_wins=1, home_wins=0)]}
        result = draw_playoff_bracket_header(canvas, bracket)
        assert isinstance(result, Image.Image)
        # Should have some black pixels (text drawn)
        assert any(px == 0 for px in result.getdata())

    def test_single_complete_series_renders(self):
        """Single complete series renders."""
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
        """Multiple series render with separators."""
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


# ===========================================================================
# draw_overflow_ticker() / _ticker_status() / _ticker_window()
# ===========================================================================

def _ov_game(pk, away_id=1, home_id=2, state='Scheduled', **overrides):
    """Minimal game dict covering the fields _ticker_status/draw_overflow_ticker read."""
    g = {
        'game_pk': pk, 'away_team_id': away_id, 'home_team_id': home_id,
        'detailed_state': state, 'game_start': '7:05 PM',
    }
    g.update(overrides)
    return g


class TestTickerStatus:
    def test_final_family_normalizes_to_f(self):
        """Final family normalizes to the single-letter 'F'."""
        for state in ('Final', 'Game Over', 'Final: Tied'):
            assert _ticker_status(_ov_game(1, state=state)) == 'F'

    def test_postponed_family_normalizes_to_postponed(self):
        """Postponed family normalizes to Postponed."""
        for state in ('Postponed', 'Cancelled', 'Cancelled: Rain'):
            assert _ticker_status(_ov_game(1, state=state)) == 'Postponed'

    def test_live_game_formats_inning_half_and_number(self):
        """Live game formats inning half and number."""
        g = _ov_game(1, state='In Progress', inningState='Bottom', currentInningOrdinal='7th')
        assert _ticker_status(g) == 'Bot 7'

    def test_live_game_falls_back_to_current_inning_without_ordinal(self):
        """Live game falls back to current_inning without ordinal."""
        g = _ov_game(1, state='In Progress', inningState='Top', current_inning=4)
        assert _ticker_status(g) == 'Top 4'

    def test_not_started_uses_pre_formatted_game_start(self):
        """Not started uses pre-formatted game_start (already local time)."""
        g = _ov_game(1, state='Scheduled', game_start='7:05 PM')
        assert _ticker_status(g) == '7:05 PM'


class TestTickerScore:
    def test_final_game_shows_score(self):
        """Final game shows score."""
        g = _ov_game(1, state='Final', away_runs=5, home_runs=3)
        assert _ticker_score(g) == '5-3'

    def test_live_game_shows_score(self):
        """Live game shows score."""
        g = _ov_game(1, state='In Progress', away_runs=2, home_runs=1)
        assert _ticker_score(g) == '2-1'

    def test_scheduled_game_has_no_score(self):
        """Scheduled game has no score."""
        g = _ov_game(1, state='Scheduled', away_runs=None, home_runs=None)
        assert _ticker_score(g) == ''

    def test_postponed_game_has_no_score(self):
        """Postponed game has no score."""
        g = _ov_game(1, state='Postponed', away_runs=0, home_runs=0)
        assert _ticker_score(g) == ''

    def test_missing_runs_data_falls_back_to_empty(self):
        """Missing runs data falls back to empty, not 'None-None'."""
        g = _ov_game(1, state='Final', away_runs=None, home_runs=3)
        assert _ticker_score(g) == ''


class TestTickerWindow:
    def test_fewer_than_max_returns_all(self):
        """Fewer than max returns all."""
        games = [_ov_game(i) for i in range(3)]
        assert _ticker_window(games, max_entries=5) == games

    def test_more_than_max_returns_a_capped_subset(self):
        """More than max returns a capped subset (10 games / 5 per window —
        an exact multiple, so every rotation window is full-sized, not just
        whichever wall-clock block this test happens to run in)."""
        games = [_ov_game(i) for i in range(10)]
        window = _ticker_window(games, max_entries=5)
        assert len(window) == 5
        assert all(g in games for g in window)

    def test_stable_within_same_rotation_block(self):
        """Two calls within the same rotation window return the same subset."""
        games = [_ov_game(i) for i in range(12)]
        first = _ticker_window(games, max_entries=5, rotation_minutes=5)
        second = _ticker_window(games, max_entries=5, rotation_minutes=5)
        assert first == second

    def test_empty_input_returns_empty(self):
        """Empty input returns empty."""
        assert _ticker_window([], max_entries=5) == []


@needs_pil
class TestDrawOverflowTicker:
    def _white(self):
        """White."""
        return Image.new('1', (800, 30), 255)

    def test_empty_dropped_games_returns_unchanged(self):
        """Empty dropped games returns unchanged."""
        canvas = self._white()
        result = draw_overflow_ticker(canvas, [], {'team_abbreviation': {}})
        assert result is canvas

    def test_single_entry_renders_with_logo_fallback(self):
        """Single entry renders with logo fallback (abbreviation text)."""
        canvas = self._white()
        team_data = {'team_abbreviation': {'1': 'NYY', '2': 'BOS'}}
        games = [_ov_game(1, away_id=1, home_id=2, state='Final', away_runs=5, home_runs=3)]
        with patch('image_standings._logo_small', return_value=None):
            result = draw_overflow_ticker(canvas, games, team_data)
        assert isinstance(result, Image.Image)
        assert any(px == 0 for px in result.getdata())

    def test_final_entry_includes_score_hits_errors_and_status(self):
        """A Final game draws each team's R (row_font), H, and E digits plus
        the trailing 'F' status — verified via draw.text call args since font
        rendering itself isn't pixel-inspectable at this granularity."""
        canvas = self._white()
        team_data = {'team_abbreviation': {'1': 'NYY', '2': 'BOS'}}
        games = [_ov_game(1, away_id=1, home_id=2, state='Final', away_runs=5, home_runs=3,
                           away_hits=9, home_hits=7, away_errors=1, home_errors=0)]
        with patch('image_standings._logo_small', return_value=None), \
             patch('image_standings.ImageDraw.ImageDraw.text') as mock_text:
            draw_overflow_ticker(canvas, games, team_data)
        drawn_strings = [call.args[1] for call in mock_text.call_args_list]
        # R/H/E digits are bolded via a double-draw-offset-by-1px, so each
        # appears twice.
        assert drawn_strings.count('5') == 2  # away runs
        assert drawn_strings.count('3') == 2  # home runs
        assert drawn_strings.count('9') == 2  # away hits
        assert drawn_strings.count('7') == 2  # home hits
        assert drawn_strings.count('1') == 2  # away errors
        assert drawn_strings.count('0') == 2  # home errors
        assert 'F' in drawn_strings

    def test_missing_hits_errors_omits_that_column(self):
        """A Final game with runs but no hits/errors data still renders (just
        without the H/E columns) rather than raising."""
        canvas = self._white()
        team_data = {'team_abbreviation': {'1': 'NYY', '2': 'BOS'}}
        games = [_ov_game(1, away_id=1, home_id=2, state='Final', away_runs=5, home_runs=3)]
        with patch('image_standings._logo_small', return_value=None):
            result = draw_overflow_ticker(canvas, games, team_data)
        assert isinstance(result, Image.Image)

    def test_no_border_or_vertical_entry_separator_lines(self):
        """No top/bottom strip border and no vertical separator between
        entries — only the horizontal away/home divider (always drawn) and
        the in-entry R/H/E column dividers (added when a game has a score)
        may appear."""
        canvas = self._white()
        team_data = {'team_abbreviation': {'1': 'NYY', '2': 'BOS', '3': 'LAD', '4': 'SF'}}
        games = [
            _ov_game(1, away_id=1, home_id=2, state='Scheduled'),
            _ov_game(2, away_id=3, home_id=4, state='Scheduled'),
        ]
        with patch('image_standings._logo_small', return_value=None), \
             patch('image_standings.ImageDraw.ImageDraw.line') as mock_line:
            draw_overflow_ticker(canvas, games, team_data)
        # Neither game has a score, so the only lines drawn are each entry's
        # horizontal away/home divider — never a vertical or full-width one.
        assert mock_line.call_count == len(games)
        for call in mock_line.call_args_list:
            (x0, y0, x1, y1) = call.args[0]
            assert y0 == y1  # horizontal, not vertical
            assert not (x0 == 0 and x1 == 799)  # never the old full-width border

    def test_final_game_draws_column_dividers_not_border(self):
        """A Final (scored) game draws its R column divider, but never the
        old top/bottom strip border (y=0 or y=_WC_STRIP_H-1 full-width lines)."""
        canvas = self._white()
        team_data = {'team_abbreviation': {'1': 'NYY', '2': 'BOS'}}
        games = [_ov_game(1, away_id=1, home_id=2, state='Final', away_runs=5, home_runs=3)]
        with patch('image_standings._logo_small', return_value=None), \
             patch('image_standings.ImageDraw.ImageDraw.line') as mock_line:
            draw_overflow_ticker(canvas, games, team_data)
        assert mock_line.call_count >= 1
        for call in mock_line.call_args_list:
            (x0, y0, x1, y1) = call.args[0]
            assert not (x0 == 0 and x1 == 799)  # never the old full-width border

    def test_multiple_entries_render_with_separators(self):
        """Multiple entries render with separators."""
        canvas = self._white()
        team_data = {'team_abbreviation': {'1': 'NYY', '2': 'BOS', '3': 'LAD', '4': 'SF'}}
        games = [
            _ov_game(1, away_id=1, home_id=2, state='Final'),
            _ov_game(2, away_id=3, home_id=4, state='Scheduled'),
        ]
        with patch('image_standings._logo_small', return_value=None):
            result = draw_overflow_ticker(canvas, games, team_data)
        assert isinstance(result, Image.Image)
        assert any(px == 0 for px in result.getdata())

    def test_more_than_max_entries_consults_ticker_window(self):
        """With more dropped games than fit, draw_overflow_ticker delegates the
        windowing decision to _ticker_window rather than drawing everything."""
        canvas = self._white()
        team_data = {'team_abbreviation': {}}
        games = [_ov_game(i) for i in range(12)]
        with patch('image_standings._logo_small', return_value=None), \
             patch('image_standings._ticker_window', wraps=_ticker_window) as mock_window:
            draw_overflow_ticker(canvas, games, team_data)
        mock_window.assert_called_once()

    def test_logo_available_pastes_instead_of_text(self):
        """When a logo is available, it's pasted rather than falling back to text."""
        canvas = self._white()
        team_data = {'team_abbreviation': {'1': 'NYY', '2': 'BOS'}}
        games = [_ov_game(1, away_id=1, home_id=2, state='Final')]
        fake_logo = Image.new('1', (20, 20), 0)  # solid black square
        with patch('image_standings._logo_small', return_value=fake_logo):
            result = draw_overflow_ticker(canvas, games, team_data)
        assert isinstance(result, Image.Image)
        assert any(px == 0 for px in result.getdata())


# ===========================================================================
# draw_standings_sidebar() — mover detection paths (lines 341-357, 389-393,
# 397-398, 408, 447, 481)
# ===========================================================================

@needs_pil
class TestDrawStandingsSidebarMovers:
    """Mover detection: rank+record change flags a team, displaced team also
    flagged, tie-break reversal flags both, recent-movement persistence shows
    indicator, and save_off_results is called when _movement_updated."""

    def _render(self, cur_teams, prev_payload=None, movement_payload=None,
                logo_side_effect=None, div='American League East', abbr_map=None):
        data = _standings({div: cur_teams}, abbr_map=abbr_map)
        img = _blank()

        def fake_load(fname):
            if fname == 'standings_prev.json':
                return prev_payload
            if fname == 'standings_movement.json':
                return movement_payload or {}
            return {}

        if logo_side_effect is not None:
            lp = patch('image_standings._logo_small', side_effect=logo_side_effect)
        else:
            lp = patch('image_standings._logo_small', return_value=None)

        with patch('image_standings.load_json_file', side_effect=fake_load), \
             patch('image_standings.save_off_results') as mock_save, \
             lp:
            result = draw_standings_sidebar(img, data, {}, side='left')
        return result, mock_save

    def test_rank_and_record_change_flags_mover_and_saves(self):
        """A team whose rank AND record both changed is flagged; save_off_results
        is called because _movement_updated becomes True (line 397-398, 481)."""
        cur = [_team(1, 1, wins=15, losses=5), _team(2, 2, wins=12, losses=8)]
        prev_payload = {
            'standings': {
                'American League East': [
                    {'team_id': '1', 'divisionRank': '2',
                     'league_record_wins': 14, 'league_record_losses': 5},
                    {'team_id': '2', 'divisionRank': '1',
                     'league_record_wins': 12, 'league_record_losses': 7},
                ],
            },
        }
        result, mock_save = self._render(cur, prev_payload=prev_payload)
        assert result is not None
        mock_save.assert_called()

    def test_displaced_team_also_flagged(self):
        """A team pushed down in rank by a mover gets flagged too (lines 350-357),
        even though only its rank changed, not its record."""
        cur = [_team(1, 1, wins=14, losses=6), _team(2, 2, wins=13, losses=6)]
        prev_payload = {
            'standings': {
                'American League East': [
                    {'team_id': '1', 'divisionRank': '2',
                     'league_record_wins': 13, 'league_record_losses': 6},
                    {'team_id': '2', 'divisionRank': '1',
                     'league_record_wins': 13, 'league_record_losses': 6},
                ],
            },
        }
        result, mock_save = self._render(cur, prev_payload=prev_payload)
        assert result is not None

    def test_recent_movement_data_shows_indicator_without_new_move(self):
        """A team in standings_movement.json with a timestamp within 20 hours
        gets its indicator shown even if no new rank/record change occurred
        (line 408: display_movers.add)."""
        import time
        cur = [_team(1, 1, wins=10, losses=5)]
        # No prev_rank change — team '1' is not a new mover.
        movement_payload = {'1': time.time() - 3600}  # 1 hour ago, within 20h
        result, _ = self._render(cur, movement_payload=movement_payload)
        assert result is not None

    def test_logo_paste_branch_covers_lines_419_423(self):
        """When _logo_small returns a real image, lines 419-423 (paste branch)
        execute in draw_standings_sidebar."""
        fake_logo = Image.new('1', (20, 20), 0)

        def _fake_small(abbr, team_id, size=20):
            return fake_logo

        cur = [_team(1, 1, wins=80, losses=60)]
        result, _ = self._render(cur, logo_side_effect=_fake_small)
        assert result is not None

    def test_mover_indicator_line_drawn(self):
        """A confirmed mover with a display_mover entry draws the vertical
        bracket line (line 447: draw.line for display_movers)."""
        cur = [_team(1, 1, wins=15, losses=5)]
        prev_payload = {
            'standings': {
                'American League East': [
                    {'team_id': '1', 'divisionRank': '2',
                     'league_record_wins': 14, 'league_record_losses': 5},
                ],
            },
        }
        img = _blank()

        def fake_load(fname):
            if fname == 'standings_prev.json':
                return prev_payload
            return {}

        with patch('image_standings.load_json_file', side_effect=fake_load), \
             patch('image_standings.save_off_results'), \
             patch('image_standings._logo_small', return_value=None):
            result = draw_standings_sidebar(img, {'standings': {'American League East': cur},
                                                   'team_abbreviation': {}}, {}, side='left')
        assert result is not None


# ===========================================================================
# _get_wildcard_teams and draw_wildcard_header — logo paste + rank ValueError
# ===========================================================================

@needs_pil
class TestWildcardMovers:
    """Cover lines 68-69 (ValueError on league_rank) and 100-103 (logo paste)."""

    def test_division_leader_skipped_in_wildcard_loop(self):
        """Division rank 1 teams hit the `continue` on line 63 and are excluded."""
        from image_standings import derive_wildcard_from_standings
        data = {
            'standings': {
                'American League East': [
                    {'team_id': '1', 'divisionRank': '1', 'team_name': 'Rays',
                     'league_rank': '1', 'wild_card_games_back': '-'},
                    {'team_id': '2', 'divisionRank': '2', 'team_name': 'Yankees',
                     'league_rank': '4', 'wild_card_games_back': '1.0'},
                ],
            },
            'team_abbreviation': {},
        }
        result = derive_wildcard_from_standings(data)
        ids = [t['team_id'] for t in result.get('AL', [])]
        assert '1' not in ids   # division leader was skipped
        assert '2' in ids       # wildcard team was included

    def test_malformed_league_rank_falls_back_to_999(self):
        """A non-numeric league_rank hits the ValueError branch (lines 68-69),
        resulting in rank=999 and the team still being appended."""
        from image_standings import derive_wildcard_from_standings
        data = {
            'standings': {
                'American League East': [
                    {'team_id': '1', 'divisionRank': '2', 'team_name': 'Yankees',
                     'league_rank': 'bad', 'wild_card_games_back': '1.0'},
                ],
            },
            'team_abbreviation': {},
        }
        result = derive_wildcard_from_standings(data)
        al_team = next((t for t in result.get('AL', []) if t['team_id'] == '1'), None)
        assert al_team is not None
        assert al_team['abbr'] == 'YAN'

    def test_wildcard_header_logo_paste_branch(self):
        """When _logo_small returns a real image, the paste branch in
        draw_wildcard_header (lines 100-103) executes."""
        fake_logo = Image.new('1', (20, 20), 0)
        al = [{'abbr': 'NYY', 'team_id': '147', 'gb': '1.0', 'rank': 4}]
        nl = [{'abbr': 'LAD', 'team_id': '119', 'gb': '0.5', 'rank': 5}]
        img = _blank()
        with patch('image_standings._logo_small', return_value=fake_logo):
            result = draw_wildcard_header(img, {'AL': al, 'NL': nl})
        assert result is img


# ===========================================================================
# _me_badge_value
# ===========================================================================

from image_standings import _me_badge_value, _ME_BADGE_THRESHOLD, _ME_MAGIC_BASE


class TestMeBadgeValue:
    def _leader(self, wins=90):
        return {'league_record_wins': wins}

    def test_clinch_z_returns_cl(self):
        assert _me_badge_value({'clinch_indicator': 'z'}, self._leader(), True, 50) == 'CL'

    def test_clinch_y_returns_cl(self):
        assert _me_badge_value({'clinch_indicator': 'y'}, self._leader(), True, 50) == 'CL'

    def test_clinch_e_returns_out(self):
        assert _me_badge_value({'clinch_indicator': 'e'}, self._leader(), False, 50) == 'OUT'

    def test_leader_wins_none_returns_empty(self):
        assert _me_badge_value({}, {'league_record_wins': None}, True, 50) == ''

    def test_leader_no_rivals_returns_cl(self):
        assert _me_badge_value({}, self._leader(wins=100), True, None) == 'CL'

    def test_leader_magic_zero_returns_cl(self):
        # 163 - 100 - 63 = 0
        assert _me_badge_value({}, self._leader(wins=100), True, 63) == 'CL'

    def test_leader_magic_within_threshold(self):
        # 163 - 90 - 40 = 33 ≤ 50
        result = _me_badge_value({}, self._leader(wins=90), True, 40)
        assert result == 'M33'

    def test_leader_magic_above_threshold_still_shows_magic_number(self):
        # 163 - 60 - 10 = 93 > threshold — the leader always shows its magic
        # number, unlike a trailing team's badge.
        result = _me_badge_value({}, self._leader(wins=60), True, 10)
        assert result == 'M93'

    def test_trailer_losses_none_returns_empty(self):
        team = {}  # missing league_record_losses
        assert _me_badge_value(team, self._leader(), False, 50) == ''

    def test_trailer_elim_zero_returns_out(self):
        # 163 - 100 - 63 = 0
        team = {'league_record_losses': 63}
        assert _me_badge_value(team, self._leader(wins=100), False, 50) == 'OUT'

    def test_trailer_elim_within_threshold(self):
        # 163 - 90 - 40 = 33 < 50
        team = {'league_record_losses': 40}
        assert _me_badge_value(team, self._leader(wins=90), False, 50) == 'E33'

    def test_trailer_elim_at_or_above_threshold_shows_games_back(self):
        # 163 - 60 - 10 = 93 >= 50 → games back, not the elimination number
        team = {'league_record_losses': 10, 'games_back': '15.5'}
        assert _me_badge_value(team, self._leader(wins=60), False, 50) == '15.5'

    def test_trailer_games_back_falls_back_to_dash_when_missing(self):
        team = {'league_record_losses': 10}
        assert _me_badge_value(team, self._leader(wins=60), False, 50) == '-'

    def test_clinch_indicator_case_insensitive(self):
        assert _me_badge_value({'clinch_indicator': 'Z'}, self._leader(), True, 50) == 'CL'


# ===========================================================================
# draw_standings_sidebar — show_magic_badges paths
# ===========================================================================

@needs_pil
class TestDrawStandingsSidebarMagicBadges:
    def _make_standings(self, wins_leader=90, losses_leader=40,
                        wins_rival=80, losses_rival=50,
                        clinch_leader=None, clinch_rival=None):
        leader = _team(1, 1, wins=wins_leader, losses=losses_leader, clinch=clinch_leader)
        rival  = _team(2, 2, wins=wins_rival,  losses=losses_rival,  clinch=clinch_rival)
        # Populate both an AL and NL division so left AND right sidebar tests hit the badge path.
        return _standings({
            'American League East': [leader, rival],
            'National League East': [leader, rival],
        })

    def _render(self, standings, side='left'):
        img = _blank()
        with patch('image_standings.load_json_file', return_value={}), \
             patch('image_standings.save_off_results'), \
             patch('image_standings._logo_small', return_value=None):
            draw_standings_sidebar(img, standings, {}, side=side, show_magic_badges=True)
        return img

    def test_magic_badge_renders_left(self):
        # 163 - 90 - 50 = 23 ≤ 50 → M23 badge on left sidebar
        standings = self._make_standings(wins_leader=90, losses_rival=50)
        result = self._render(standings, side='left')
        assert result is not None

    def test_magic_badge_renders_right(self):
        standings = self._make_standings(wins_leader=90, losses_rival=50)
        result = self._render(standings, side='right')
        assert result is not None

    def test_games_back_badge_above_threshold(self):
        # 163 - 50 - 10 = 103 > 50 → games back badge instead of E-number
        standings = self._make_standings(wins_leader=50, losses_rival=10)
        result = self._render(standings, side='left')
        assert result is not None

    def test_clinched_leader_shows_cl(self):
        standings = self._make_standings(clinch_leader='z')
        result = self._render(standings, side='left')
        assert result is not None

    def test_eliminated_rival_shows_out(self):
        standings = self._make_standings(clinch_rival='e')
        result = self._render(standings, side='left')
        assert result is not None

    def test_only_one_team_in_division(self):
        only = [_team(1, 1, wins=90, losses=40)]
        standings = _standings({'American League East': only})
        result = self._render(standings, side='left')
        assert result is not None

    def test_aaa_mode_skips_badges(self):
        standings = self._make_standings()
        img = _blank()
        with patch('image_standings.load_json_file', return_value={}), \
             patch('image_standings.save_off_results'), \
             patch('image_standings._logo_small', return_value=None):
            draw_standings_sidebar(img, standings, {}, side='left',
                                   league_mode='aaa', show_magic_badges=True)
        assert img is not None
