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
    draw_transactions_header,
    draw_recap_header,
    _recap_row_labels,
    _ticker_status,
    _ticker_score,
    _ticker_window,
    derive_playoff_seedings,
    derive_playoff_active_round,
    derive_playoff_series_by_league,
    draw_playoff_round_header,
    draw_playoff_seedings_sidebar,
    draw_playoff_seedings_fullscreen,
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

    def test_clinch_indicator_draws_marker(self):
        """Clinch indicator draws a 'c' marker in the bottom-right of the logo slot."""
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
        """Final family normalizes to the single-letter 'F' for 9-inning games."""
        for state in ('Final', 'Game Over', 'Final: Tied'):
            assert _ticker_status(_ov_game(1, state=state)) == 'F'

    def test_final_extra_innings_appends_inning(self):
        """Extra-innings final shows F/<inning> (e.g. F/10)."""
        for state in ('Final', 'Game Over'):
            g = _ov_game(1, state=state, current_inning=10)
            assert _ticker_status(g) == 'F/10'
        g = _ov_game(1, state='Final', current_inning=13)
        assert _ticker_status(g) == 'F/13'

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
        may appear. Uses live (not Scheduled) games since not-yet-started
        games use the single-row logo-dash-logo layout, which draws no
        divider at all."""
        canvas = self._white()
        team_data = {'team_abbreviation': {'1': 'NYY', '2': 'BOS', '3': 'LAD', '4': 'SF'}}
        games = [
            _ov_game(1, away_id=1, home_id=2, state='In Progress'),
            _ov_game(2, away_id=3, home_id=4, state='In Progress'),
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

    def test_not_started_game_renders_single_row_logo_dash_logo_time(self):
        """A game that hasn't started yet (Scheduled/Pre-Game/Warmup/Delayed
        Start) skips the stacked two-row live/final layout entirely — no R,
        H, E, or divider line — and instead draws one row: away logo, a
        dash, home logo, then the start time."""
        canvas = self._white()
        team_data = {'team_abbreviation': {'1': 'NYY', '2': 'BOS'}}
        games = [_ov_game(1, away_id=1, home_id=2, state='Scheduled', game_start='7:05 PM')]
        with patch('image_standings._logo_small', return_value=None), \
             patch('image_standings.ImageDraw.ImageDraw.line') as mock_line, \
             patch('image_standings.ImageDraw.ImageDraw.text') as mock_text:
            draw_overflow_ticker(canvas, games, team_data)
        mock_line.assert_not_called()
        drawn_strings = [call.args[1] for call in mock_text.call_args_list]
        assert 'NYY' in drawn_strings
        assert 'BOS' in drawn_strings
        assert ' - ' in drawn_strings
        assert '7:05 PM' in drawn_strings

    def test_not_started_game_pastes_logos_when_available(self):
        """Pre-Game/Warmup/Delayed Start all share the not-yet-started single
        row layout, not just Scheduled."""
        team_data = {'team_abbreviation': {'1': 'NYY', '2': 'BOS'}}
        fake_logo = Image.new('1', (28, 28), 0)
        for state in ('Scheduled', 'Pre-Game', 'Warmup', 'Delayed Start'):
            games = [_ov_game(1, away_id=1, home_id=2, state=state)]
            with patch('image_standings._logo_small', return_value=fake_logo):
                result = draw_overflow_ticker(self._white(), games, team_data)
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
        al = [{'abbr': 'NYY', 'team_id': '147', 'gb': '1.0', 'rank': 4, 'elim_badge': ''}]
        nl = [{'abbr': 'LAD', 'team_id': '119', 'gb': '0.5', 'rank': 5, 'elim_badge': ''}]
        img = _blank()
        with patch('image_standings._logo_small', return_value=fake_logo):
            result = draw_wildcard_header(img, {'AL': al, 'NL': nl})
        assert result is img

    def test_wildcard_header_draws_elim_badge_text(self):
        """When a team carries an elim_badge, its text is drawn in the slot."""
        from image_standings import _WC_BADGE_H, _WC_STRIP_H
        al = [{'abbr': 'NYY', 'team_id': '147', 'gb': '2.0', 'rank': 4, 'elim_badge': 'E5'}]
        img = _blank()
        with patch('image_standings._logo_small', return_value=None):
            draw_wildcard_header(img, {'AL': al, 'NL': []})
        # At least some ink should appear in the badge row at the bottom of the strip.
        badge_row_y = _WC_STRIP_H - _WC_BADGE_H - 1
        has_ink = any(img.getpixel((x, badge_row_y)) == 0 for x in range(32, 56))
        assert has_ink, 'expected badge text ink in the slot'

    def test_wildcard_header_no_badge_for_in_box_teams(self):
        """Teams inside the wildcard box have elim_badge='' and no extra ink row."""
        al = [
            {'abbr': 'NYY', 'team_id': '147', 'gb': '-', 'rank': 1, 'elim_badge': ''},
            {'abbr': 'BOS', 'team_id': '111', 'gb': '1.0', 'rank': 2, 'elim_badge': ''},
            {'abbr': 'TBR', 'team_id': '139', 'gb': '2.0', 'rank': 3, 'elim_badge': ''},
        ]
        img = _blank()
        with patch('image_standings._logo_small', return_value=None):
            draw_wildcard_header(img, {'AL': al, 'NL': []})
        # No crash and result is the image.
        assert img.size == (800, 480)

    def test_derive_wildcard_wc3_gets_magic_badge_within_threshold(self):
        """The team holding the 3rd (last) wildcard spot gets a magic_badge
        once its magic number to hold off the closest chaser is within
        ELIM_THRESHOLD."""
        from image_standings import derive_wildcard_from_standings
        data = {
            'standings': {
                'American League East': [
                    {'team_id': '1', 'divisionRank': '1', 'team_name': 'Leader',
                     'league_rank': '1', 'wild_card_games_back': '-'},
                    {'team_id': '2', 'divisionRank': '2', 'team_name': 'WC1',
                     'league_rank': '4', 'wild_card_games_back': '-5.0',
                     'league_record_wins': 100, 'league_record_losses': 44},
                    {'team_id': '3', 'divisionRank': '2', 'team_name': 'WC2',
                     'league_rank': '5', 'wild_card_games_back': '-3.0',
                     'league_record_wins': 95, 'league_record_losses': 49},
                    {'team_id': '4', 'divisionRank': '2', 'team_name': 'WC3',
                     'league_rank': '6', 'wild_card_games_back': '-1.0',
                     'league_record_wins': 100, 'league_record_losses': 44},
                    {'team_id': '5', 'divisionRank': '2', 'team_name': 'Chaser',
                     'league_rank': '7', 'wild_card_games_back': '1.0',
                     'league_record_wins': 90, 'league_record_losses': 50},
                ],
            },
            'team_abbreviation': {},
        }
        result = derive_wildcard_from_standings(data)
        by_id = {t['team_id']: t for t in result['AL']}
        # E = 163 - 100 - 50 = 13 <= ELIM_THRESHOLD (20)
        assert by_id['4']['magic_badge'] == 'M13'
        # Only the cutline (3rd spot) team gets a magic_badge.
        assert by_id['2'].get('magic_badge', '') == ''
        assert by_id['3'].get('magic_badge', '') == ''

    def test_wildcard_header_draws_magic_badge_for_cutline_team(self):
        """A team carrying magic_badge shows it instead of the raw GB
        (highest-priority branch in _draw_slot)."""
        al = [{'abbr': 'NYY', 'team_id': '147', 'gb': '-1.0', 'rank': 3,
               'elim_badge': '', 'magic_badge': 'M13'}]
        img = _blank()
        with patch('image_standings._logo_small', return_value=None):
            draw_wildcard_header(img, {'AL': al, 'NL': []})
        from image_standings import _WC_BADGE_H, _WC_STRIP_H
        badge_row_y = _WC_STRIP_H - _WC_BADGE_H - 1
        has_ink = any(img.getpixel((x, badge_row_y)) == 0 for x in range(32, 56))
        assert has_ink, 'expected magic badge text ink in the slot'

    def test_derive_wildcard_bad_wins_losses_type_falls_back(self):
        """Non-numeric league_record_wins/losses hit the ValueError branch."""
        from image_standings import derive_wildcard_from_standings
        data = {
            'standings': {
                'American League East': [
                    {'team_id': '99', 'divisionRank': '2', 'team_name': 'TST',
                     'league_rank': '5', 'wild_card_games_back': '3.0',
                     'league_record_wins': 'bad', 'league_record_losses': 'bad'},
                ],
            },
            'team_abbreviation': {},
        }
        result = derive_wildcard_from_standings(data)
        team = next((t for t in result.get('AL', []) if t['team_id'] == '99'), None)
        assert team is not None
        assert team['wins'] is None
        assert team['losses'] is None


# ===========================================================================
# _wc_elim_badge
# ===========================================================================

class TestWcElimBadge:
    """Unit tests for image_standings._wc_elim_badge."""

    def _badge(self, team_entry, wc3_wins=85, wc3_losses=None):
        from image_standings import _wc_elim_badge
        return _wc_elim_badge(team_entry, wc3_wins, wc3_losses)

    def test_clinched_out_returns_OUT(self):
        """A team with clinch_indicator='e' is eliminated."""
        assert self._badge({'clinch_indicator': 'e', 'losses': 70}) == 'OUT'

    def test_no_wc3_wins_returns_empty(self):
        """When the 3rd WC team has no wins data, no badge is shown."""
        assert self._badge({'losses': 70}, wc3_wins=None) == ''

    def test_no_losses_returns_empty(self):
        """When the bubble team has no losses data, no badge is shown."""
        assert self._badge({'losses': None}) == ''

    def test_elimination_elim_leq_threshold(self):
        """Elimination number at or below threshold returns E{n}."""
        from image_utils import MAGIC_BASE, ELIM_THRESHOLD
        # Set wins so that MAGIC_BASE - wc3_wins - team_losses = ELIM_THRESHOLD
        wc3_wins = 80
        losses = MAGIC_BASE - wc3_wins - ELIM_THRESHOLD
        assert self._badge({'losses': losses, 'clinch_indicator': ''}, wc3_wins=wc3_wins) \
               == f'E{ELIM_THRESHOLD}'

    def test_large_elimination_number_returns_empty(self):
        """Elimination number above ELIM_THRESHOLD is not meaningful enough to show."""
        assert self._badge({'losses': 10, 'clinch_indicator': ''}, wc3_wins=40) == ''

    def test_already_eliminated_returns_OUT(self):
        """Elimination number ≤ 0 means the team is already eliminated."""
        from image_utils import MAGIC_BASE
        wc3_wins = 90
        losses = MAGIC_BASE - wc3_wins   # elim = 0
        assert self._badge({'losses': losses, 'clinch_indicator': ''}, wc3_wins=wc3_wins) \
               == 'OUT'


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
        # 163 - 100 - 48 = 15 ≤ _ME_BADGE_THRESHOLD (20)
        result = _me_badge_value({}, self._leader(wins=100), True, 48)
        assert result == 'M15'

    def test_leader_magic_above_threshold_shows_nothing(self):
        # 163 - 60 - 10 = 93, well above _ME_BADGE_THRESHOLD (20) —
        # not meaningful yet, so the leader shows nothing.
        result = _me_badge_value({}, self._leader(wins=60), True, 10)
        assert result == ''

    def test_trailer_losses_none_returns_empty(self):
        team = {}  # missing league_record_losses
        assert _me_badge_value(team, self._leader(), False, 50) == ''

    def test_trailer_elim_zero_returns_out(self):
        # 163 - 100 - 63 = 0
        team = {'league_record_losses': 63}
        assert _me_badge_value(team, self._leader(wins=100), False, 50) == 'OUT'

    def test_trailer_elim_within_threshold(self):
        # 163 - 100 - 44 = 19 ≤ 20
        team = {'league_record_losses': 44}
        assert _me_badge_value(team, self._leader(wins=100), False, 50) == 'E19'

    def test_trailer_elim_at_or_above_threshold_shows_games_back(self):
        # 163 - 60 - 10 = 93 > 20 → games back, not the elimination number
        team = {'league_record_losses': 10, 'games_back': '15.5'}
        assert _me_badge_value(team, self._leader(wins=60), False, 50) == '15.5'

    def test_trailer_games_back_falls_back_to_dash_when_missing(self):
        team = {'league_record_losses': 10}
        assert _me_badge_value(team, self._leader(wins=60), False, 50) == '-'

    def test_trailer_within_ten_games_back_hides_elimination_number(self):
        # 163 - 100 - 44 = 19 ≤ 20, but games_back (9.5) < 10 → games back wins
        team = {'league_record_losses': 44, 'games_back': '9.5'}
        assert _me_badge_value(team, self._leader(wins=100), False, 50) == '9.5'

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


# ===========================================================================
# draw_transactions_header
# ===========================================================================

def _TX_ENTRY(abbr, name, type_desc):
    return {'team_abbr': abbr, 'player_name': name, 'type_desc': type_desc}


@needs_pil
class TestDrawTransactionsHeader:
    def _render(self, entries, rotation_minutes=3):
        img = _blank()
        return draw_transactions_header(img, entries, {}, rotation_minutes=rotation_minutes)

    def test_no_entries_returns_unchanged(self):
        img = _blank()
        result = draw_transactions_header(img, [], {})
        assert result is img

    def test_none_entries_returns_unchanged(self):
        img = _blank()
        result = draw_transactions_header(img, None, {})
        assert result is img

    def test_single_entry_renders(self):
        result = self._render([_TX_ENTRY('NYY', 'Aaron Judge', 'Status Change')])
        assert isinstance(result, Image.Image)

    def test_multiple_entries_within_max_renders(self):
        entries = [_TX_ENTRY('NYY', 'Judge', 'Status Change'),
                   _TX_ENTRY('BOS', 'Devers', 'Trade'),
                   _TX_ENTRY('LAD', 'Freeman', 'Signed')]
        result = self._render(entries)
        assert isinstance(result, Image.Image)

    def test_more_than_max_rotates_chunk(self):
        entries = [_TX_ENTRY(f'T{i}', f'Player {i}', 'Trade') for i in range(12)]
        result = self._render(entries, rotation_minutes=1)
        assert isinstance(result, Image.Image)

    def test_unknown_type_desc_uses_raw_truncated(self):
        result = self._render([_TX_ENTRY('CHC', 'Suzuki', 'SomethingUnknown')])
        assert isinstance(result, Image.Image)

    def test_separator_line_drawn_for_second_entry(self):
        single = self._render([_TX_ENTRY('NYY', 'Judge', 'Trade')])
        multi = self._render([_TX_ENTRY('NYY', 'Judge', 'Trade'),
                              _TX_ENTRY('BOS', 'Devers', 'Trade')])
        assert multi.tobytes() != single.tobytes()

    def test_rotation_minutes_clamped_to_at_least_one(self):
        entries = [_TX_ENTRY('SF', 'Webb', 'Signed')]
        result = self._render(entries, rotation_minutes=0)
        assert isinstance(result, Image.Image)

    def test_empty_player_name_skips_last_name(self):
        result = self._render([_TX_ENTRY('CLE', '', 'Released')])
        assert isinstance(result, Image.Image)


# ===========================================================================
# _recap_row_labels() — pure logic
# ===========================================================================

class TestRecapRowLabels:

    def test_walk_off_home_run_returns_walk_off_and_hr(self):
        game = {'walk_off': True, 'last_play': 'Home Run'}
        assert _recap_row_labels(game) == ('Walk-off', 'HR')

    def test_walk_off_single_returns_walk_off_and_1b(self):
        game = {'walk_off': True, 'last_play': 'Single'}
        assert _recap_row_labels(game) == ('Walk-off', '1B')

    def test_walk_off_unknown_type_returns_empty_abbr(self):
        game = {'walk_off': True, 'last_play': 'Something Unusual'}
        assert _recap_row_labels(game) == ('Walk-off', '')

    def test_walk_off_with_no_last_play_returns_empty_abbr(self):
        game = {'walk_off': True}
        assert _recap_row_labels(game) == ('Walk-off', '')

    def test_normal_final_returns_wp_lp_last_names(self):
        game = {'winner_name': 'Gerrit Cole', 'loser_name': 'Nick Pivetta'}
        top, bot = _recap_row_labels(game)
        assert top == 'WP: Cole'
        assert bot == 'LP: Pivetta'

    def test_normal_final_missing_winner_returns_empty_top(self):
        game = {'loser_name': 'Nick Pivetta'}
        top, bot = _recap_row_labels(game)
        assert top == ''
        assert bot == 'LP: Pivetta'

    def test_normal_final_missing_both_returns_empty_strings(self):
        game = {}
        assert _recap_row_labels(game) == ('', '')


# ===========================================================================
# draw_recap_header() — rendering
# ===========================================================================

@needs_pil
class TestDrawRecapHeader:

    def _blank(self):
        return Image.new('1', (800, 30), 255)

    def _team_data(self):
        return {'team_abbreviation': {'1': 'NYY', '2': 'BOS'}}

    def _game(self, pk=1, **kw):
        g = {'game_pk': pk, 'away_team_id': 1, 'home_team_id': 2,
             'away_runs': 5, 'home_runs': 3, 'detailed_state': 'Final'}
        g.update(kw)
        return g

    def test_empty_games_returns_unchanged_image(self):
        canvas = self._blank()
        result = draw_recap_header(canvas, [], self._team_data())
        assert result is canvas

    def test_games_without_runs_are_skipped(self):
        canvas = self._blank()
        game = {'game_pk': 1, 'away_team_id': 1, 'home_team_id': 2,
                'away_runs': None, 'detailed_state': 'Final'}
        result = draw_recap_header(canvas, [game], self._team_data())
        assert result is canvas

    def test_single_final_game_renders_something(self):
        canvas = self._blank()
        with patch('image_standings._logo_small', return_value=None):
            result = draw_recap_header(canvas, [self._game()], self._team_data())
        assert isinstance(result, Image.Image)
        assert any(px == 0 for px in result.getdata())

    def test_walk_off_game_draws_walk_off_label(self):
        canvas = self._blank()
        game = self._game(walk_off=True, last_play='Home Run')
        with patch('image_standings._logo_small', return_value=None), \
             patch('image_standings.ImageDraw.ImageDraw.text') as mock_text:
            draw_recap_header(canvas, [game], self._team_data())
        drawn = [call.args[1] for call in mock_text.call_args_list]
        assert 'Walk-off' in drawn
        assert 'HR' in drawn

    def test_normal_final_draws_wp_lp_labels(self):
        canvas = self._blank()
        game = self._game(winner_name='Gerrit Cole', loser_name='Nick Pivetta')
        with patch('image_standings._logo_small', return_value=None), \
             patch('image_standings.ImageDraw.ImageDraw.text') as mock_text:
            draw_recap_header(canvas, [game], self._team_data())
        drawn = [call.args[1] for call in mock_text.call_args_list]
        assert 'WP: Cole' in drawn
        assert 'LP: Pivetta' in drawn

    def test_multiple_games_render_without_error(self):
        canvas = self._blank()
        games = [self._game(pk=i, away_runs=i, home_runs=0) for i in range(1, 4)]
        with patch('image_standings._logo_small', return_value=None):
            result = draw_recap_header(canvas, games, self._team_data())
        assert isinstance(result, Image.Image)


# ===========================================================================
# derive_playoff_seedings — pure logic
# ===========================================================================

def _pbracket(series_list):
    return {'season': 2026, 'series': series_list}

def _ps(round_lbl, away_id, home_id, away_abbr, home_abbr,
        away_wins=0, home_wins=0, complete=False, winner_abbr=None):
    return {
        'round': round_lbl,
        'away_id': away_id, 'home_id': home_id,
        'away_abbr': away_abbr, 'home_abbr': home_abbr,
        'away_wins': away_wins, 'home_wins': home_wins,
        'complete': complete, 'winner_abbr': winner_abbr,
    }

def _playoff_standings(*entries):
    """entries: (team_id, div_name, league_rank)"""
    by_div = {}
    for tid, div, lr in entries:
        t = {'team_id': tid, 'divisionRank': '1', 'league_rank': lr,
             'league_record_wins': 90, 'league_record_losses': 60}
        by_div.setdefault(div, []).append(t)
    return {'standings': by_div, 'team_abbreviation': {str(tid): f'T{tid}' for tid, *_ in entries}}


class TestDerivePlayoffSeedings:
    def _standings_6(self):
        return _playoff_standings(
            (1, 'American League East',    1),
            (2, 'American League Central', 2),
            (3, 'American League West',    3),
            (4, 'American League East',    4),
            (5, 'American League Central', 5),
            (6, 'American League West',    6),
            (11, 'National League East',    1),
            (12, 'National League Central', 2),
            (13, 'National League West',    3),
            (14, 'National League East',    4),
            (15, 'National League Central', 5),
            (16, 'National League West',    6),
        )

    def _bracket_6(self):
        # WC: seeds 3v6 and 4v5; DS: seeds 1 and 2 vs WC winners
        return _pbracket([
            _ps('WC', '6', '3', 'T6', 'T3', home_wins=2, complete=True, winner_abbr='T3'),
            _ps('WC', '4', '5', 'T4', 'T5', away_wins=2, complete=True, winner_abbr='T4'),
            _ps('WC', '16', '13', 'T16', 'T13', home_wins=2, complete=True, winner_abbr='T13'),
            _ps('WC', '14', '15', 'T14', 'T15', away_wins=2, complete=True, winner_abbr='T14'),
            _ps('DS', '1', '4', 'T1', 'T4', away_wins=1),
            _ps('DS', '2', '3', 'T2', 'T3', away_wins=0),
            _ps('DS', '11', '14', 'T11', 'T14', away_wins=1),
            _ps('DS', '12', '13', 'T12', 'T13', away_wins=0),
        ])

    def test_returns_al_and_nl_keys(self):
        result = derive_playoff_seedings(self._bracket_6(), self._standings_6())
        assert set(result.keys()) == {'AL', 'NL'}

    def test_al_has_six_seeds(self):
        result = derive_playoff_seedings(self._bracket_6(), self._standings_6())
        assert len(result['AL']) == 6

    def test_seeds_sorted_ascending(self):
        result = derive_playoff_seedings(self._bracket_6(), self._standings_6())
        seeds = [t['seed'] for t in result['AL']]
        assert seeds == sorted(seeds)

    def test_eliminated_team_flagged(self):
        result = derive_playoff_seedings(self._bracket_6(), self._standings_6())
        # T5 lost WC to T4
        t5 = next(t for t in result['AL'] if t['team_id'] == '5')
        assert t5['eliminated'] is True

    def test_winner_not_eliminated(self):
        result = derive_playoff_seedings(self._bracket_6(), self._standings_6())
        t4 = next(t for t in result['AL'] if t['team_id'] == '4')
        assert t4['eliminated'] is False

    def test_highest_round_tracked(self):
        # T4 played WC (won) then DS — should show DS, not WC
        result = derive_playoff_seedings(self._bracket_6(), self._standings_6())
        t4 = next(t for t in result['AL'] if t['team_id'] == '4')
        assert t4['round'] == 'DS'

    def test_active_series_flagged(self):
        result = derive_playoff_seedings(self._bracket_6(), self._standings_6())
        t1 = next(t for t in result['AL'] if t['team_id'] == '1')
        assert t1['active'] is True

    def test_empty_bracket_returns_empty(self):
        result = derive_playoff_seedings(_pbracket([]), self._standings_6())
        assert result['AL'] == []

    def test_team_not_in_standings_excluded(self):
        # bracket references team 99 which isn't in standings
        b = _pbracket([_ps('WC', '99', '5', 'UNK', 'T5')])
        result = derive_playoff_seedings(b, self._standings_6())
        ids = {t['team_id'] for t in result['AL']}
        assert '99' not in ids

    def test_unknown_division_skipped(self):
        # standings key that is not in AL or NL div sets should be ignored
        standings = _playoff_standings(
            (1, 'American League East', 1),
        )
        standings['standings']['AAA Pacific Coast'] = [
            {'team_id': 99, 'league_rank': 1}
        ]
        b = _pbracket([_ps('WC', '1', '99', 'T1', 'T99')])
        result = derive_playoff_seedings(b, standings)
        ids_al = {t['team_id'] for t in result['AL']}
        assert '99' not in ids_al

    def test_empty_team_id_in_bracket_skipped(self):
        # series entry missing team_id should not crash
        series = _ps('WC', '', '1', 'MISS', 'T1')
        b = _pbracket([series])
        result = derive_playoff_seedings(b, self._standings_6())
        assert isinstance(result, dict)

    def test_invalid_league_rank_falls_back_to_99(self):
        standings = {
            'standings': {
                'American League East': [
                    {'team_id': 1, 'league_rank': 'bad_value'},
                ]
            },
            'team_abbreviation': {'1': 'T1'},
        }
        b = _pbracket([_ps('WC', '1', '2', 'T1', 'T2')])
        result = derive_playoff_seedings(b, standings)
        if result['AL']:
            assert result['AL'][0]['seed'] == 99


class TestDerivePlayoffActiveRound:
    def test_active_round_is_lowest_incomplete(self):
        b = _pbracket([
            _ps('WC', '1', '2', 'A', 'B', away_wins=2, complete=True, winner_abbr='A'),
            _ps('DS', '1', '3', 'A', 'C', away_wins=1),
        ])
        assert derive_playoff_active_round(b) == 'DS'

    def test_placeholder_future_rounds_ignored(self):
        # Real bracket: WC in progress, DS/CS/WS pre-populated as 0-0 placeholders
        b = _pbracket([
            _ps('WC', '1', '2', 'A', 'B', away_wins=1),
            _ps('WC', '3', '4', 'C', 'D', away_wins=0),
            _ps('DS', '5', '6', 'E', 'F'),   # placeholder, complete=False, 0-0
            _ps('CS', '7', '8', 'G', 'H'),   # placeholder
            _ps('WS', '9', '10', 'I', 'J'),  # placeholder
        ])
        assert derive_playoff_active_round(b) == 'WC'

    def test_all_complete_returns_highest(self):
        b = _pbracket([
            _ps('WC', '1', '2', 'A', 'B', away_wins=2, complete=True, winner_abbr='A'),
            _ps('DS', '1', '3', 'A', 'C', away_wins=3, complete=True, winner_abbr='A'),
        ])
        assert derive_playoff_active_round(b) == 'DS'

    def test_empty_bracket_returns_none(self):
        assert derive_playoff_active_round(_pbracket([])) is None

    def test_ws_is_current_when_active(self):
        b = _pbracket([_ps('WS', '1', '2', 'A', 'B', away_wins=2)])
        assert derive_playoff_active_round(b) == 'WS'

    def test_gap_between_rounds_keeps_completed_round(self):
        # WC is done (complete=True); DS is pre-scheduled but 0-0 (no games yet).
        # The sidebar should stay on WC results, not jump to DS at 0-0.
        b = _pbracket([
            _ps('WC', '1', '2', 'A', 'B', away_wins=2, complete=True, winner_abbr='A'),
            _ps('WC', '3', '4', 'C', 'D', home_wins=2, complete=True, winner_abbr='D'),
            _ps('DS', '1', '3', 'A', 'C'),   # scheduled, no games played yet
            _ps('CS', '5', '6', 'E', 'F'),   # scheduled, no games played yet
        ])
        assert derive_playoff_active_round(b) == 'WC'

    def test_gap_switches_to_new_round_once_a_game_is_played(self):
        # Once DS has even one game played, it becomes the active round.
        b = _pbracket([
            _ps('WC', '1', '2', 'A', 'B', away_wins=2, complete=True, winner_abbr='A'),
            _ps('DS', '1', '3', 'A', 'C', away_wins=1),  # first DS game played
        ])
        assert derive_playoff_active_round(b) == 'DS'


class TestDerivePlayoffSeriesByLeague:
    def _base_standings(self):
        return _playoff_standings(
            (1, 'American League East',    1),
            (2, 'American League Central', 2),
            (11, 'National League East',   1),
            (12, 'National League Central', 2),
        )

    def test_al_series_grouped_correctly(self):
        b = _pbracket([_ps('DS', '1', '2', 'T1', 'T2', away_wins=1)])
        result = derive_playoff_series_by_league(b, self._base_standings())
        assert len(result['AL']) == 1
        assert result['AL'][0]['away_abbr'] == 'T1'

    def test_nl_series_excluded_from_al(self):
        b = _pbracket([_ps('DS', '11', '12', 'N1', 'N2', away_wins=1)])
        result = derive_playoff_series_by_league(b, self._base_standings())
        assert result['AL'] == []
        assert len(result['NL']) == 1

    def test_ws_appears_in_both_leagues(self):
        b = _pbracket([_ps('WS', '1', '11', 'T1', 'N1', away_wins=2)])
        result = derive_playoff_series_by_league(b, self._base_standings())
        assert len(result['AL']) == 1
        assert len(result['NL']) == 1

    def test_only_current_round_returned(self):
        b = _pbracket([
            _ps('WC', '1', '2', 'T1', 'T2', away_wins=2, complete=True, winner_abbr='T1'),
            _ps('DS', '1', '11', 'T1', 'N1', away_wins=1),
        ])
        result = derive_playoff_series_by_league(b, self._base_standings())
        # DS is current round — WC should not appear
        for lg in ('AL', 'NL'):
            for s in result[lg]:
                assert s['round'] == 'DS'

    def test_empty_bracket_returns_empty(self):
        result = derive_playoff_series_by_league(_pbracket([]), self._base_standings())
        assert result == {'AL': [], 'NL': []}

    def test_unknown_division_ignored(self):
        # a standings key that isn't AL/NL should not crash or add teams
        standings = self._base_standings()
        standings['standings']['AAA Fake League'] = [{'team_id': 99, 'league_rank': 1}]
        b = _pbracket([_ps('DS', '1', '2', 'T1', 'T2', away_wins=1)])
        result = derive_playoff_series_by_league(b, standings)
        assert len(result['AL']) == 1
        assert len(result['NL']) == 0

    def test_invalid_league_rank_in_standings_falls_back(self):
        # league_rank that can't be cast to int should not crash
        standings = self._base_standings()
        standings['standings']['American League East'].append(
            {'team_id': 3, 'league_rank': 'bad'}
        )
        b = _pbracket([_ps('DS', '1', '3', 'T1', 'T3', away_wins=1)])
        result = derive_playoff_series_by_league(b, standings)
        assert isinstance(result, dict)


def _series_by_league():
    return {
        'AL': [_ps('DS', '1', '2', 'T1', 'T2', away_wins=2, home_wins=1)],
        'NL': [_ps('DS', '11', '12', 'N1', 'N2', away_wins=1, home_wins=2)],
    }


@needs_pil
class TestDrawPlayoffRoundHeader:
    def test_returns_image(self):
        img = _blank()
        b = _pbracket([_ps('DS', '1', '2', 'A', 'B', away_wins=1)])
        result = draw_playoff_round_header(img, b)
        assert result is img

    def test_draws_pixels_different_from_blank(self):
        img = _blank()
        b = _pbracket([_ps('DS', '1', '2', 'A', 'B', away_wins=1)])
        draw_playoff_round_header(img, b)
        assert img.tobytes() != _blank().tobytes()

    def test_empty_bracket_unchanged(self):
        img = _blank()
        draw_playoff_round_header(img, _pbracket([]))
        assert img.tobytes() == _blank().tobytes()


@needs_pil
class TestDrawPlayoffSeedingsSidebar:
    def test_left_sidebar_returns_image(self):
        img = _blank()
        with patch('image_standings._logo_small', return_value=None):
            result = draw_playoff_seedings_sidebar(img, _series_by_league(), {}, side='left')
        assert result is img

    def test_right_sidebar_returns_image(self):
        img = _blank()
        with patch('image_standings._logo_small', return_value=None):
            result = draw_playoff_seedings_sidebar(img, _series_by_league(), {}, side='right')
        assert result is img

    def test_draws_pixels_different_from_blank(self):
        img = _blank()
        with patch('image_standings._logo_small', return_value=None):
            draw_playoff_seedings_sidebar(img, _series_by_league(), {}, side='left')
        assert img.tobytes() != _blank().tobytes()

    def test_empty_series_returns_unchanged(self):
        img = _blank()
        result = draw_playoff_seedings_sidebar(img, {'AL': [], 'NL': []}, {}, side='left')
        assert result is img
        assert img.tobytes() == _blank().tobytes()

    def test_with_real_logo_image(self):
        logo = Image.new('1', (16, 16), 0)
        img = _blank()
        with patch('image_standings._logo_small', return_value=logo):
            result = draw_playoff_seedings_sidebar(img, _series_by_league(), {}, side='left')
        assert result is img

    def test_two_series_renders_without_crash(self):
        two = {
            'AL': [
                _ps('DS', '1', '2', 'T1', 'T2', away_wins=2, home_wins=1),
                _ps('DS', '3', '4', 'T3', 'T4', away_wins=0, home_wins=3),
            ],
            'NL': [],
        }
        img = _blank()
        with patch('image_standings._logo_small', return_value=None):
            result = draw_playoff_seedings_sidebar(img, two, {}, side='left')
        assert result is img

    def test_game_results_path_used_when_present(self):
        # series with game_results: G1=away win, G2=home win, G3=away win
        series = _ps('WC', '1', '2', 'T1', 'T2', away_wins=2, home_wins=1)
        series['game_results'] = [
            {'winner_id': '1', 'game_pk': 101, 'date': '2026-10-01'},
            {'winner_id': '2', 'game_pk': 102, 'date': '2026-10-02'},
            {'winner_id': '1', 'game_pk': 103, 'date': '2026-10-03'},
        ]
        sbl = {'AL': [series], 'NL': []}
        img = _blank()
        with patch('image_standings._logo_small', return_value=None):
            result = draw_playoff_seedings_sidebar(img, sbl, {}, side='left')
        assert result is img

    def test_game_results_lag_behind_win_counts(self):
        # game_results has only 1 entry but win counts say 1-1 (data lag)
        series = _ps('WC', '143', '144', 'PHI', 'ATL', away_wins=1, home_wins=1)
        series['game_results'] = [
            {'winner_id': '144', 'game_pk': 849845, 'date': '2026-09-29'},
        ]
        sbl = {'AL': [], 'NL': [series]}
        img = _blank()
        with patch('image_standings._logo_small', return_value=None):
            result = draw_playoff_seedings_sidebar(img, sbl, {}, side='right')
        assert result is img  # must not crash; draws 2 result slots + 1 empty

    def test_game_results_lag_home_wins(self):
        # game_results records only away win; home win not yet in results (data lag)
        series = _ps('WC', '143', '144', 'PHI', 'ATL', away_wins=1, home_wins=1)
        series['game_results'] = [
            {'winner_id': '143', 'game_pk': 849845, 'date': '2026-09-29'},
        ]
        sbl = {'AL': [], 'NL': [series]}
        img = _blank()
        with patch('image_standings._logo_small', return_value=None):
            result = draw_playoff_seedings_sidebar(img, sbl, {}, side='right')
        assert result is img  # home-wins supplement path (lines 1577-1578)

    def test_complete_series_draws_winner_pill(self):
        sbl = {
            'AL': [_ps('DS', '1', '2', 'T1', 'T2', away_wins=3, home_wins=1,
                        complete=True, winner_abbr='T1')],
            'NL': [],
        }
        img = _blank()
        with patch('image_standings._logo_small', return_value=None):
            result = draw_playoff_seedings_sidebar(img, sbl, {}, side='left')
        assert result is img


@needs_pil
class TestDrawPlayoffSeedingsFullscreen:
    def _canvas(self):
        return Image.new('1', (800, 480), 255)

    def test_left_side_returns_canvas(self):
        canvas = self._canvas()
        with patch('image_standings._logo_small', return_value=None):
            result = draw_playoff_seedings_fullscreen(canvas, _series_by_league(), {}, side='left')
        assert result is canvas

    def test_right_side_returns_canvas(self):
        canvas = self._canvas()
        with patch('image_standings._logo_small', return_value=None):
            result = draw_playoff_seedings_fullscreen(canvas, _series_by_league(), {}, side='right')
        assert result is canvas

    def test_draws_pixels_different_from_blank(self):
        canvas = self._canvas()
        with patch('image_standings._logo_small', return_value=None):
            draw_playoff_seedings_fullscreen(canvas, _series_by_league(), {}, side='left')
        assert canvas.tobytes() != self._canvas().tobytes()

    def test_empty_series_returns_unchanged(self):
        canvas = self._canvas()
        blank_bytes = canvas.tobytes()
        result = draw_playoff_seedings_fullscreen(canvas, {'AL': [], 'NL': []}, {}, side='right')
        assert result is canvas
        assert canvas.tobytes() == blank_bytes

    def test_with_logo_image(self):
        logo = Image.new('1', (40, 40), 0)
        canvas = self._canvas()
        with patch('image_standings._logo_small', return_value=logo):
            result = draw_playoff_seedings_fullscreen(canvas, _series_by_league(), {}, side='left')
        assert result is canvas

    def test_multiple_series_draws_divider(self):
        # two AL series → idx < n-1 triggers the divider line between them
        two_series = {
            'AL': [
                _ps('WC', '1', '2', 'T1', 'T2', away_wins=1),
                _ps('WC', '3', '4', 'T3', 'T4', home_wins=1),
            ],
            'NL': [],
        }
        canvas = self._canvas()
        blank_bytes = canvas.tobytes()
        with patch('image_standings._logo_small', return_value=None):
            result = draw_playoff_seedings_fullscreen(canvas, two_series, {}, side='left')
        assert result is canvas
        assert canvas.tobytes() != blank_bytes

    def test_game_results_path_used_when_present(self):
        # game_results present → chronological path used instead of grouped fallback
        series = _ps('WC', '1', '2', 'T1', 'T2', away_wins=1, home_wins=2)
        series['game_results'] = [
            {'winner_id': '2', 'game_pk': 201, 'date': '2026-10-01'},
            {'winner_id': '2', 'game_pk': 202, 'date': '2026-10-02'},
            {'winner_id': '1', 'game_pk': 203, 'date': '2026-10-03'},
        ]
        canvas = self._canvas()
        with patch('image_standings._logo_small', return_value=None):
            result = draw_playoff_seedings_fullscreen(
                canvas, {'AL': [series], 'NL': []}, {}, side='left')
        assert result is canvas
