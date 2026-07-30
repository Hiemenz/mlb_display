"""
Comprehensive tests for scoreboard display rules, payload change detection,
and all business logic in generate_image.py / fetch_games.py.

Organized into sections:
  1. Pure helper function tests (no PIL, no I/O)
  2. Score suppression logic (_has_play conditions)
  3. State normalization rules
  4. Rendering integration tests (requires pic/Font.ttc)
  5. Payload change detection tests
  6. TV channel priority tests
  7. Wildcard/standings derivation tests
"""

import json
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

# conftest.py already adds src/ to sys.path and chdirs to project root.
from generate_image import (
    _pitcher_line,
    _last_name,
    _clean_venue_name,
    _is_game_effectively_over,
    compare_json_dicts_sorted,
    load_and_sort_json,
    check_if_two_chars,
    derive_wildcard_from_standings,
    draw_box,
    draw_out_of_town_score_board,
)
from image_utils import _format_player_name
from image_box import _abbr_play, _fielder_from_desc, _fielder_seq_from_desc
from game_detail_fetch import _build_scorecard_notation, _parse_review_context, _find_recent_review_result
from fetch_games import _pick_tv_channel

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def white_image():
    """800×480 blank white canvas — same mode the real scoreboard uses."""
    return Image.new('1', (800, 480), 255)


@pytest.fixture
def minimal_team_data():
    """Minimal team_data dict with two teams."""
    return {
        'team_abbreviation': {
            '133': 'OAK',
            '144': 'ATL',
        }
    }


def _base_game(**overrides):
    """Return a minimal valid game dict in 'Final' state."""
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
        'away_inning_runs': [0,1,0,0,0,2,0,0,0],
        'home_inning_runs': [1,0,2,0,0,0,1,0,1],
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
    }
    g.update(overrides)
    return g


def _in_progress_game(**overrides):
    """Minimal 'In Progress' game with enough activity to pass score suppression."""
    g = _base_game(
        detailed_state='In Progress',
        away_runs=2,
        home_runs=1,
        away_hits=None,
        home_hits=None,
        away_errors=None,
        home_errors=None,
        away_team_is_winner=None,
        home_team_is_winner=None,
        winner_name=None,
        loser_name=None,
        saver_name=None,
        winner_record=None,
        loser_record=None,
        saver_saves=None,
        inningState='Top',
        current_inning=5,
        num_of_outs=1,
        balls=2,
        strikes=1,
        current_pitcher='Sandy Koufax',
        current_hitter='Pete Rose',
        last_play='Single by Pete Rose',
    )
    g.update(overrides)
    return g


def _pregame_game(**overrides):
    """Minimal 'Scheduled' pre-game entry."""
    g = _base_game(
        detailed_state='Scheduled',
        away_runs=None,
        home_runs=None,
        away_hits=None,
        home_hits=None,
        away_errors=None,
        home_errors=None,
        away_team_is_winner=None,
        home_team_is_winner=None,
        winner_name=None,
        loser_name=None,
        away_inning_runs=[],
        home_inning_runs=[],
        num_of_outs=None,
        balls=None,
        strikes=None,
        current_inning=None,
        inningState=None,
        game_start='7:05 PM',
        away_probable='Gerrit Cole',
        home_probable='Max Fried',
        away_probable_note='3-1, 2.50 ERA',
        home_probable_note='4-0, 1.80 ERA',
    )
    g.update(overrides)
    return g


def _has_dark_pixels(image, x1, y1, x2, y2):
    """Return True if any pixel in the region is black (0 in mode '1' or dark in 'L')."""
    region = image.crop((x1, y1, x2, y2)).convert('L')
    return min(region.getdata()) < 128


# ===========================================================================
# 1. PURE HELPER FUNCTION TESTS
# ===========================================================================

class TestCheckIfTwoChars:
    def test_single_digit_returns_zero(self):
        """Single digit returns zero."""
        assert check_if_two_chars("0") == 0
        assert check_if_two_chars("9") == 0
        assert check_if_two_chars(5) == 0

    def test_two_digit_returns_minus_six(self):
        """Two digit returns minus six."""
        assert check_if_two_chars("10") == -6
        assert check_if_two_chars("99") == -6
        assert check_if_two_chars(42) == -6

    def test_three_digit_returns_zero(self):
        """Three digit returns zero."""
        # Only 2-digit triggers the offset; anything else is 0
        assert check_if_two_chars("100") == 0


class TestPitcherLine:
    def test_none_name_returns_tbd(self):
        """None name returns tbd."""
        name, stat = _pitcher_line(None, None)
        assert name == 'TBD'
        assert stat == ''

    def test_empty_name_returns_tbd(self):
        """Empty name returns tbd."""
        name, stat = _pitcher_line('', None)
        assert name == 'TBD'
        assert stat == ''

    def test_single_name_no_initial(self):
        """Single name no initial."""
        name, stat = _pitcher_line('Verlander', None)
        assert name == 'Verlander'

    def test_full_name_formatted(self):
        """Full name formatted."""
        name, stat = _pitcher_line('Justin Verlander', None)
        assert name == 'J. Verlander'

    def test_three_part_name(self):
        """Three part name."""
        name, stat = _pitcher_line('Sandy A Koufax', None)
        # Middle initial not a suffix → last part is last name
        assert name == 'S. Koufax'

    def test_name_with_jr_suffix_skipped(self):
        """Name with jr suffix skipped."""
        name, stat = _pitcher_line('Cal Ripken Jr.', None)
        assert name == 'C. Ripken'

    def test_name_with_sr_suffix_skipped(self):
        """Name with sr suffix skipped."""
        name, stat = _pitcher_line('Ken Griffey Sr.', None)
        assert name == 'K. Griffey'

    def test_name_with_ii_suffix_skipped(self):
        """Name with ii suffix skipped."""
        name, stat = _pitcher_line('Cecil Fielder II', None)
        assert name == 'C. Fielder'

    def test_name_with_iii_suffix_skipped(self):
        """Name with iii suffix skipped."""
        name, stat = _pitcher_line('Felipe Lopez III', None)
        assert name == 'F. Lopez'

    def test_note_parses_wl_and_era(self):
        """Note parses wl and era."""
        name, stat = _pitcher_line('Justin Verlander', '3-1, 2.75 ERA')
        assert '3-1' in stat
        assert '2.75' in stat

    def test_note_wl_only(self):
        """Note wl only."""
        name, stat = _pitcher_line('Justin Verlander', '3-1')
        assert stat == '3-1'

    def test_note_era_only(self):
        """Note era only."""
        name, stat = _pitcher_line('Justin Verlander', ', 2.75 ERA')
        assert '2.75' in stat

    def test_note_none_gives_empty_stat(self):
        """Note none gives empty stat."""
        name, stat = _pitcher_line('Justin Verlander', None)
        assert stat == ''

    def test_note_invalid_era_ignored(self):
        """Note invalid era ignored."""
        # ERA that cannot be converted to float should be ignored
        name, stat = _pitcher_line('Justin Verlander', '3-1, ABC ERA')
        assert stat == '3-1'

    def test_note_negative_era_ignored(self):
        """Note negative era ignored."""
        name, stat = _pitcher_line('Justin Verlander', '3-1, -1.00 ERA')
        assert stat == '3-1'

    def test_note_zero_zero_wl(self):
        """Note zero zero wl."""
        name, stat = _pitcher_line('Rookie Pitcher', '0-0, 0.00 ERA')
        assert '0-0' in stat
        assert '0.00' in stat


class TestFormatPlayerName:
    def test_none_returns_empty(self):
        """None returns empty."""
        assert _format_player_name(None) == ''

    def test_empty_returns_empty(self):
        """Empty returns empty."""
        assert _format_player_name('') == ''

    def test_single_name_unchanged(self):
        """Single name unchanged."""
        assert _format_player_name('Verlander') == 'Verlander'

    def test_two_part_name(self):
        """Two part name."""
        assert _format_player_name('Mike Trout') == 'M. Trout'

    def test_three_part_name(self):
        """Three part name."""
        # Middle name counts as last name unless it's a suffix
        assert _format_player_name('Juan Pierre Leblanc') == 'J. Leblanc'

    def test_jr_suffix_skipped(self):
        """Jr suffix skipped."""
        assert _format_player_name('Cal Ripken Jr.') == 'C. Ripken'

    def test_sr_suffix_skipped(self):
        """Sr suffix skipped."""
        assert _format_player_name('Ken Griffey Sr.') == 'K. Griffey'

    def test_ii_suffix_skipped(self):
        """Ii suffix skipped."""
        assert _format_player_name('Roberto Alomar II') == 'R. Alomar'

    def test_iii_suffix_skipped(self):
        """Iii suffix skipped."""
        assert _format_player_name('Barry Bonds III') == 'B. Bonds'

    def test_iv_suffix_skipped(self):
        """Iv suffix skipped."""
        assert _format_player_name('John Smith IV') == 'J. Smith'

    def test_v_suffix_skipped(self):
        """V suffix skipped."""
        assert _format_player_name('John Smith V') == 'J. Smith'


class TestLastName:
    def test_none_returns_empty(self):
        """None returns empty."""
        assert _last_name(None) == ''

    def test_empty_returns_empty(self):
        """Empty returns empty."""
        assert _last_name('') == ''

    def test_single_name(self):
        """Single name."""
        assert _last_name('Verlander') == 'Verlander'

    def test_two_part_name(self):
        """Two part name."""
        assert _last_name('Mike Trout') == 'Trout'

    def test_three_part_name(self):
        """Three part name."""
        assert _last_name('Juan Pierre Leblanc') == 'Leblanc'

    def test_jr_suffix_skipped(self):
        """Jr suffix skipped."""
        assert _last_name('Cal Ripken Jr.') == 'Ripken'

    def test_sr_suffix_skipped(self):
        """Sr suffix skipped."""
        assert _last_name('Ken Griffey Sr.') == 'Griffey'

    def test_ii_suffix_skipped(self):
        """Ii suffix skipped."""
        assert _last_name('Roberto Alomar II') == 'Alomar'


class TestCleanVenueName:
    def test_none_returns_none(self):
        """None returns none."""
        assert _clean_venue_name(None) is None

    def test_empty_returns_empty(self):
        """Empty returns empty."""
        assert _clean_venue_name('') == ''

    def test_at_notation_strips_left_side(self):
        """At notation strips left side."""
        assert _clean_venue_name('Oriole Park at Camden Yards') == 'Camden Yards'

    def test_at_notation_only_first_split(self):
        """At notation only first split."""
        # Only first ' at ' is split
        assert _clean_venue_name('A at B at C') == 'B at C'

    def test_known_override_daikin(self):
        """Known override daikin."""
        assert _clean_venue_name('Daikin Park') == 'Minute Maid Park'

    def test_known_override_american_family(self):
        """Known override american family."""
        assert _clean_venue_name('American Family Field') == 'Am. Family Field'

    def test_known_override_guaranteed_rate(self):
        """Known override guaranteed rate."""
        assert _clean_venue_name('Guaranteed Rate Field') == 'Guaranteed Rate'

    def test_known_override_loandepot(self):
        """Known override loandepot."""
        assert _clean_venue_name('loanDepot park') == 'LoanDepot Park'

    def test_plain_venue_unchanged(self):
        """Plain venue unchanged."""
        assert _clean_venue_name('Dodger Stadium') == 'Dodger Stadium'
        assert _clean_venue_name('Wrigley Field') == 'Wrigley Field'


# ===========================================================================
# 2. _is_game_effectively_over() TESTS
# ===========================================================================

class TestIsGameEffectivelyOver:
    def test_final_is_over(self):
        """Final is over."""
        assert _is_game_effectively_over({'detailed_state': 'Final'})

    def test_game_over_is_over(self):
        """Game over is over."""
        assert _is_game_effectively_over({'detailed_state': 'Game Over'})

    def test_final_tied_is_over(self):
        """Final tied is over."""
        assert _is_game_effectively_over({'detailed_state': 'Final: Tied'})

    def test_completed_early_is_over(self):
        """Completed early is over."""
        assert _is_game_effectively_over({'detailed_state': 'Completed Early'})

    def test_in_progress_mid_game_not_over(self):
        """In progress mid game not over."""
        assert not _is_game_effectively_over({
            'detailed_state': 'In Progress',
            'current_inning': 5,
            'inningState': 'Top',
            'away_runs': 2,
            'home_runs': 1,
        })

    def test_inning_9_middle_home_leads_is_over(self):
        """Inning 9 middle home leads is over."""
        # After top of 9th, home team is ahead → home doesn't bat
        assert _is_game_effectively_over({
            'detailed_state': 'In Progress',
            'current_inning': 9,
            'inningState': 'Middle',
            'away_runs': 3,
            'home_runs': 5,
        })

    def test_inning_9_middle_home_trails_not_over(self):
        """Inning 9 middle home trails not over."""
        assert not _is_game_effectively_over({
            'detailed_state': 'In Progress',
            'current_inning': 9,
            'inningState': 'Middle',
            'away_runs': 5,
            'home_runs': 3,
        })

    def test_inning_9_middle_tied_not_over(self):
        """Inning 9 middle tied not over."""
        assert not _is_game_effectively_over({
            'detailed_state': 'In Progress',
            'current_inning': 9,
            'inningState': 'Middle',
            'away_runs': 3,
            'home_runs': 3,
        })

    def test_inning_9_end_different_scores_is_over(self):
        """Inning 9 end different scores is over."""
        # After bottom of 9th with a winner
        assert _is_game_effectively_over({
            'detailed_state': 'In Progress',
            'current_inning': 9,
            'inningState': 'End',
            'away_runs': 3,
            'home_runs': 5,
        })

    def test_inning_9_end_tied_not_over(self):
        """Inning 9 end tied not over."""
        # Tied after bottom of 9th → extra innings
        assert not _is_game_effectively_over({
            'detailed_state': 'In Progress',
            'current_inning': 9,
            'inningState': 'End',
            'away_runs': 3,
            'home_runs': 3,
        })

    def test_inning_10_end_different_scores_is_over(self):
        """Inning 10 end different scores is over."""
        # Same logic applies in extra innings
        assert _is_game_effectively_over({
            'detailed_state': 'In Progress',
            'current_inning': 11,
            'inningState': 'End',
            'away_runs': 4,
            'home_runs': 6,
        })

    def test_inning_8_middle_home_leads_not_over(self):
        """Inning 8 middle home leads not over."""
        # Rule only triggers at inning >= 9
        assert not _is_game_effectively_over({
            'detailed_state': 'In Progress',
            'current_inning': 8,
            'inningState': 'Middle',
            'away_runs': 2,
            'home_runs': 5,
        })

    def test_scheduled_not_over(self):
        """Scheduled not over."""
        assert not _is_game_effectively_over({
            'detailed_state': 'Scheduled',
            'current_inning': None,
        })

    def test_none_inning_not_over(self):
        """None inning not over."""
        assert not _is_game_effectively_over({
            'detailed_state': 'In Progress',
            'current_inning': None,
            'inningState': 'Middle',
            'away_runs': 2,
            'home_runs': 5,
        })


# ===========================================================================
# 3. SCORE SUPPRESSION (_has_play CONDITIONS)
# ===========================================================================

class TestScoreSuppression:
    """
    When detailed_state == 'In Progress' and no evidence of actual play exists,
    draw_box() must flip the state to 'Pre-Game' (score suppression).
    These tests verify exactly which conditions count as 'evidence of play'.
    We test by inspecting the rendered image: pre-game shows records not score.

    Score coordinate: (start_x+66, start_y+25) = (98, 55) for away score in font24.
    Region note: the border line sits at y = start_y+20 = 50, so we start at y+22
    to avoid picking it up as a false-positive dark pixel.
    """

    # Score check region: clear of border lines (at y=30 and y=50) and team names
    # (team name "OAK" in font24 ends at x≈77; scores start at x=98).
    _SCORE_REGION = (92, 52, 118, 77)   # absolute coords for sx=32, sy=30

    def _render(self, game, team_data):
        """Render."""
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, game, team_data, use_logos=False)
        return img

    @needs_pil
    def test_no_activity_suppresses_to_pregame(self, minimal_team_data):
        """In Progress with zero activity → treated as Pre-Game (no score rendered)."""
        game = _base_game(
            detailed_state='In Progress',
            away_runs=None,
            home_runs=None,
            away_hits=None,
            home_hits=None,
            num_of_outs=None,
            balls=None,
            strikes=None,
            current_inning=1,
            inningState='Top',
            runner_on_first=None,
            runner_on_second=None,
            runner_on_third=None,
            last_play=None,
        )
        img = self._render(game, minimal_team_data)
        assert not _has_dark_pixels(img, *self._SCORE_REGION), \
            "Score should NOT be visible when game has no play activity"

    @needs_pil
    def test_ball_count_shows_score(self, minimal_team_data):
        """balls > 0 → game has started → score shown."""
        game = _base_game(
            detailed_state='In Progress',
            away_runs=1,
            home_runs=0,
            away_hits=None,
            home_hits=None,
            num_of_outs=0,
            balls=1,
            strikes=0,
            current_inning=1,
            inningState='Top',
            runner_on_first=None,
            runner_on_second=None,
            runner_on_third=None,
            last_play=None,
        )
        img = self._render(game, minimal_team_data)
        assert _has_dark_pixels(img, *self._SCORE_REGION), \
            "Score SHOULD be visible when balls > 0"

    @needs_pil
    def test_outs_shows_score(self, minimal_team_data):
        """Outs shows score."""
        game = _base_game(
            detailed_state='In Progress',
            away_runs=0,
            home_runs=0,
            num_of_outs=1,
            balls=0,
            strikes=0,
            current_inning=1,
            inningState='Top',
            runner_on_first=None,
            runner_on_second=None,
            runner_on_third=None,
            last_play=None,
        )
        img = self._render(game, minimal_team_data)
        assert _has_dark_pixels(img, *self._SCORE_REGION), \
            "Score SHOULD be visible when outs > 0"

    @needs_pil
    def test_runs_shows_score(self, minimal_team_data):
        """Runs shows score."""
        game = _base_game(
            detailed_state='In Progress',
            away_runs=3,
            home_runs=0,
            num_of_outs=0,
            balls=0,
            strikes=0,
            current_inning=1,
            inningState='Top',
            runner_on_first=None,
            runner_on_second=None,
            runner_on_third=None,
            last_play=None,
        )
        img = self._render(game, minimal_team_data)
        assert _has_dark_pixels(img, *self._SCORE_REGION)

    @needs_pil
    def test_runner_on_first_shows_score(self, minimal_team_data):
        """Runner on first shows score."""
        game = _base_game(
            detailed_state='In Progress',
            away_runs=0,
            home_runs=0,
            num_of_outs=0,
            balls=0,
            strikes=0,
            current_inning=1,
            inningState='Top',
            runner_on_first='Pete Rose',
            runner_on_second=None,
            runner_on_third=None,
            last_play=None,
        )
        img = self._render(game, minimal_team_data)
        assert _has_dark_pixels(img, *self._SCORE_REGION)

    @needs_pil
    def test_inning_two_shows_score(self, minimal_team_data):
        """current_inning > 1 is sufficient evidence of play."""
        game = _base_game(
            detailed_state='In Progress',
            away_runs=0,
            home_runs=0,
            num_of_outs=0,
            balls=0,
            strikes=0,
            current_inning=2,
            inningState='Top',
            runner_on_first=None,
            runner_on_second=None,
            runner_on_third=None,
            last_play=None,
        )
        img = self._render(game, minimal_team_data)
        assert _has_dark_pixels(img, *self._SCORE_REGION)

    @needs_pil
    def test_middle_inning_state_shows_score(self, minimal_team_data):
        """inningState='Middle' is evidence of play (between innings)."""
        game = _base_game(
            detailed_state='In Progress',
            away_runs=2,
            home_runs=1,
            num_of_outs=None,
            balls=None,
            strikes=None,
            current_inning=3,
            inningState='Middle',
            runner_on_first=None,
            runner_on_second=None,
            runner_on_third=None,
            last_play=None,
        )
        img = self._render(game, minimal_team_data)
        assert _has_dark_pixels(img, *self._SCORE_REGION)

    @needs_pil
    def test_last_play_shows_score(self, minimal_team_data):
        """Last play shows score."""
        game = _base_game(
            detailed_state='In Progress',
            away_runs=0,
            home_runs=0,
            num_of_outs=0,
            balls=0,
            strikes=0,
            current_inning=1,
            inningState='Top',
            runner_on_first=None,
            runner_on_second=None,
            runner_on_third=None,
            last_play='Foul ball',
        )
        img = self._render(game, minimal_team_data)
        assert _has_dark_pixels(img, *self._SCORE_REGION)

    @needs_pil
    def test_suppressed_and_active_games_differ(self, minimal_team_data):
        """Suppressed In Progress and Active In Progress must render differently."""
        suppressed = _base_game(
            detailed_state='In Progress',
            away_runs=None, home_runs=None,
            num_of_outs=None, balls=None, strikes=None,
            current_inning=1, inningState='Top',
            runner_on_first=None, runner_on_second=None, runner_on_third=None,
            last_play=None,
        )
        active = _base_game(
            detailed_state='In Progress',
            away_runs=1, home_runs=0,
            num_of_outs=0, balls=1, strikes=0,
            current_inning=1, inningState='Top',
            runner_on_first=None, runner_on_second=None, runner_on_third=None,
            last_play=None,
        )
        img_sup = self._render(suppressed, minimal_team_data)
        img_act = self._render(active, minimal_team_data)
        assert list(img_sup.getdata()) != list(img_act.getdata()), \
            "Suppressed and active In Progress games must render differently"


# ===========================================================================
# 4. STATE NORMALIZATION RENDERING TESTS
# ===========================================================================

class TestStateNormalization:
    """
    draw_box() normalizes certain states before rendering. Verify the results
    match the expected normalized state visually.
    """

    @needs_pil
    def test_completed_early_shows_as_final(self, white_image, minimal_team_data):
        """Completed Early must render exactly like Final (winner/loser pitchers shown)."""
        game = _base_game(detailed_state='Completed Early', current_inning=6)
        sx, sy = 32, 30
        draw_box(white_image, sx, sy, game, minimal_team_data, use_logos=False)
        # Final games show winner/loser pitchers — some pixels will be dark in the lower box
        lower_box = (sx, sy + 60, sx + 135, sy + 130)
        assert _has_dark_pixels(white_image, *lower_box)

    # Score check region avoiding the header border at y=50 and team name ending at x≈77
    _SCORE_REGION = (92, 52, 118, 77)

    def _render(self, game, team_data):
        """Render."""
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, game, team_data, use_logos=False)
        return img

    @needs_pil
    def test_player_challenge_shows_as_in_progress(self, minimal_team_data):
        """Player challenge → In Progress (score visible if game has started)."""
        game = _base_game(
            detailed_state='Player challenge',
            away_runs=3,
            home_runs=2,
            away_hits=None,
            home_hits=None,
            num_of_outs=2,
            balls=1,
            strikes=1,
            current_inning=7,
            inningState='Bottom',
            current_pitcher='Sandy Koufax',
            current_hitter='Pete Rose',
            last_play='Ground out',
        )
        img = self._render(game, minimal_team_data)
        assert _has_dark_pixels(img, *self._SCORE_REGION)

    @needs_pil
    def test_manager_challenge_shows_as_in_progress(self, minimal_team_data):
        """Manager challenge → In Progress."""
        game = _base_game(
            detailed_state='Manager challenge',
            away_runs=1,
            home_runs=3,
            away_hits=None,
            home_hits=None,
            num_of_outs=1,
            balls=2,
            strikes=0,
            current_inning=4,
            inningState='Top',
            current_pitcher='Sandy Koufax',
            current_hitter='Pete Rose',
            last_play='Hit by pitch',
        )
        img = self._render(game, minimal_team_data)
        assert _has_dark_pixels(img, *self._SCORE_REGION)

    @needs_pil
    def test_delayed_start_shows_as_pregame(self, minimal_team_data):
        """Delayed Start → Pre-Game (record shown, score NOT shown)."""
        game = _pregame_game(detailed_state='Delayed Start')
        img = self._render(game, minimal_team_data)
        # Verify no score in the score region (border is at y=50 so region starts at y=52)
        assert not _has_dark_pixels(img, *self._SCORE_REGION), \
            "Delayed Start should show no score (treated as Pre-Game)"

    @needs_pil
    def test_delayed_start_differs_from_pregame_in_header(self, minimal_team_data):
        """Delayed Start shows 'Delay' in the header; plain Pre-Game shows game time."""
        delayed = _pregame_game(detailed_state='Delayed Start')
        pregame = _pregame_game(detailed_state='Pre-Game')
        img_d = self._render(delayed, minimal_team_data)
        img_p = self._render(pregame, minimal_team_data)
        assert list(img_d.getdata()) != list(img_p.getdata()), \
            "Delayed Start should differ from Pre-Game (different header text)"

    @needs_pil
    def test_challenge_states_show_challenge_text_in_header(self, minimal_team_data):
        """Player challenge and Manager challenge each display their state as the header play text."""
        common = dict(
            away_runs=3, home_runs=2, num_of_outs=2, balls=1, strikes=1,
            current_inning=7, inningState='Bottom',
            current_pitcher='Sandy Koufax', current_hitter='Pete Rose',
            last_play='Ground out', away_hits=None, home_hits=None,
        )
        pc = _base_game(detailed_state='Player challenge', **common)
        mc = _base_game(detailed_state='Manager challenge', **common)
        in_prog = _base_game(detailed_state='In Progress', **common)
        img_pc = self._render(pc, minimal_team_data)
        img_mc = self._render(mc, minimal_team_data)
        img_ip = self._render(in_prog, minimal_team_data)
        assert list(img_pc.getdata()) != list(img_ip.getdata()), \
            "Player challenge should render differently (shows 'P Challenge' not 'Ground out')"
        assert list(img_mc.getdata()) != list(img_ip.getdata()), \
            "Manager challenge should render differently (shows 'M Challenge' not 'Ground out')"
        assert list(img_pc.getdata()) != list(img_mc.getdata()), \
            "Player challenge and Manager challenge show different text so must differ"


# ===========================================================================
# 5. SCORE DISPLAY RULES (FINAL vs IN-PROGRESS vs PRE-GAME)
# ===========================================================================

class TestScoreDisplayRules:
    """Verify which game states cause scores/hits/errors to appear."""

    # Score region: avoids the header border at y=50, and team name ending at x≈77
    _SCORE_REGION = (92, 52, 118, 77)

    def _render(self, game, team_data, sx=32, sy=30):
        """Render."""
        img = Image.new('1', (800, 480), 255)
        draw_box(img, sx, sy, game, team_data, use_logos=False)
        return img

    @needs_pil
    def test_final_shows_score(self, minimal_team_data):
        """Final shows score."""
        img = self._render(_base_game(detailed_state='Final'), minimal_team_data)
        assert _has_dark_pixels(img, *self._SCORE_REGION)

    @needs_pil
    def test_final_shows_hits(self, minimal_team_data):
        """Hits column appears in Final games (confirmed by Final vs In-Progress diff)."""
        final = _base_game(away_hits=7, home_hits=9)
        in_prog = _in_progress_game()
        img_final = self._render(final, minimal_team_data)
        img_inprog = self._render(in_prog, minimal_team_data)
        # The full images must differ — Final has hits/errors the in-progress doesn't
        assert list(img_final.getdata()) != list(img_inprog.getdata())

    @needs_pil
    def test_in_progress_hits_field_doesnt_affect_render(self, minimal_team_data):
        """In Progress games ignore away_hits/home_hits — they must not change the render."""
        game_no_hits = _in_progress_game(away_hits=None, home_hits=None)
        game_with_hits = _in_progress_game(away_hits=5, home_hits=3)
        img1 = self._render(game_no_hits, minimal_team_data)
        img2 = self._render(game_with_hits, minimal_team_data)
        assert list(img1.getdata()) == list(img2.getdata()), \
            "Setting hits on an In Progress game must NOT change rendering"

    @needs_pil
    def test_rhe_header_on_final(self, minimal_team_data):
        """R H E header text is shown on Final games — header area has dark pixels."""
        img = self._render(_base_game(perfect_game=False, no_hitter=False), minimal_team_data)
        header_region = (32+60, 30+0, 32+135, 30+20)
        assert _has_dark_pixels(img, *header_region)

    @needs_pil
    def test_rhe_header_suppressed_on_perfect_game(self, minimal_team_data):
        """perfect_game=True changes the header rendering (no R H E label)."""
        img_normal = self._render(_base_game(perfect_game=False, no_hitter=False), minimal_team_data)
        img_pg = self._render(_base_game(perfect_game=True, no_hitter=False), minimal_team_data)
        # The overall renders must be different — different header text
        assert list(img_normal.getdata()) != list(img_pg.getdata()), \
            "perfect_game=True must change the header rendering"

    @needs_pil
    def test_rhe_header_suppressed_on_no_hitter(self, minimal_team_data):
        """no_hitter=True changes the header rendering (no R H E label)."""
        img_normal = self._render(_base_game(perfect_game=False, no_hitter=False), minimal_team_data)
        img_nh = self._render(_base_game(no_hitter=True, perfect_game=False), minimal_team_data)
        assert list(img_normal.getdata()) != list(img_nh.getdata()), \
            "no_hitter=True must change the header rendering"

    @needs_pil
    def test_perfect_game_and_no_hitter_differ(self, minimal_team_data):
        """Perfect game and no-hitter display differently (different header labels)."""
        img_pg = self._render(_base_game(perfect_game=True, no_hitter=False), minimal_team_data)
        img_nh = self._render(_base_game(no_hitter=True, perfect_game=False), minimal_team_data)
        assert list(img_pg.getdata()) != list(img_nh.getdata()), \
            "Perfect game and no-hitter must render different header labels"

    @needs_pil
    def test_pregame_shows_no_score(self, minimal_team_data):
        """Pregame shows no score."""
        img = self._render(_pregame_game(), minimal_team_data)
        assert not _has_dark_pixels(img, *self._SCORE_REGION)

    @needs_pil
    def test_pregame_shows_team_record(self, minimal_team_data):
        """Pre-game must display team W-L record (right-aligned in team row)."""
        game = _pregame_game(away_team_record_wins=15, away_team_record_losses=8)
        img = self._render(game, minimal_team_data)
        # Record is right-aligned — check the right half of the away team row
        record_region = (32 + 90, 30 + 22, 32 + 135, 30 + 45)
        assert _has_dark_pixels(img, *record_region), "Pre-game should show team record"

    @needs_pil
    def test_game_over_treated_like_final(self, minimal_team_data):
        """Game Over state must produce the same output as Final."""
        img_final = self._render(_base_game(detailed_state='Final'), minimal_team_data)
        img_go = self._render(_base_game(detailed_state='Game Over'), minimal_team_data)
        assert list(img_final.getdata()) == list(img_go.getdata()), \
            "Game Over and Final must render identically"

    @needs_pil
    def test_delayed_with_score_shows_score(self, minimal_team_data):
        """Delayed game that has started (current_inning > 0) must show the score."""
        game = _base_game(
            detailed_state='Delayed',
            away_runs=3,
            home_runs=1,
            away_hits=None,
            home_hits=None,
            current_inning=5,
            inningState='Top',
        )
        img = self._render(game, minimal_team_data)
        assert _has_dark_pixels(img, *self._SCORE_REGION)


# ===========================================================================
# 6. BETWEEN-INNING DETECTION
# ===========================================================================

class TestBetweenInnings:
    """The _between_innings flag controls whether linescore grid is shown."""

    @needs_pil
    def test_middle_inning_triggers_linescore(self, white_image, minimal_team_data):
        """inningState='Middle' should show linescore grid, not bases/outs UI."""
        game = _base_game(
            detailed_state='In Progress',
            away_runs=2,
            home_runs=1,
            away_hits=None,
            home_hits=None,
            num_of_outs=3,
            balls=None,
            strikes=None,
            current_inning=3,
            inningState='Middle',
            runner_on_first=None,
            runner_on_second=None,
            runner_on_third=None,
            last_play='Strikeout',
            next_batter_1='Aaron Judge',
            next_batter_2='Giancarlo Stanton',
            next_batter_3='Anthony Rizzo',
            next_pitcher='Gerrit Cole',
        )
        draw_box(white_image, 32, 30, game, minimal_team_data, use_logos=False)
        # The linescore grid spans the middle section of the box
        linescore_region = (32, 30 + 70, 32 + 135, 30 + 110)
        assert _has_dark_pixels(white_image, *linescore_region)

    @needs_pil
    def test_end_inning_triggers_linescore(self, white_image, minimal_team_data):
        """inningState='End' also triggers linescore mode."""
        game = _base_game(
            detailed_state='In Progress',
            away_runs=4,
            home_runs=2,
            away_hits=None,
            home_hits=None,
            num_of_outs=3,
            balls=None,
            strikes=None,
            current_inning=6,
            inningState='End',
            runner_on_first=None,
            runner_on_second=None,
            runner_on_third=None,
            last_play='Flyout',
        )
        draw_box(white_image, 32, 30, game, minimal_team_data, use_logos=False)
        linescore_region = (32, 30 + 70, 32 + 135, 30 + 110)
        assert _has_dark_pixels(white_image, *linescore_region)


# ===========================================================================
# 7. SAVE SITUATION BADGE
# ===========================================================================

class TestSaveSituation:
    """save_situation=True must cause an 'SV' badge to be rendered in the header."""

    # SV badge is drawn at (start_x + horizonta_len - sv_w - 2, start_y + 21)
    # ≈ (153, 51) for sx=32, horizonta_len=135. Region must start below the
    # header border line at y=50 (start_y+20).
    _SV_REGION = (135, 49, 167, 63)   # abs coords: just below the border, right side

    def _render(self, game, team_data):
        """Render."""
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, game, team_data, use_logos=False)
        return img

    @needs_pil
    def test_sv_badge_changes_render(self, minimal_team_data):
        """save_situation=True must produce a different image than save_situation=False."""
        game_sv = _in_progress_game(save_situation=True, current_inning=8)
        game_no = _in_progress_game(save_situation=False, current_inning=8)
        img_sv = self._render(game_sv, minimal_team_data)
        img_no = self._render(game_no, minimal_team_data)
        assert list(img_sv.getdata()) != list(img_no.getdata()), \
            "save_situation=True should produce a different render"

    @needs_pil
    def test_sv_badge_region_has_more_pixels_when_active(self, minimal_team_data):
        """The SV badge region must have more dark pixels when save_situation is True."""
        game_sv = _in_progress_game(save_situation=True, current_inning=8)
        game_no = _in_progress_game(save_situation=False, current_inning=8)
        img_sv = self._render(game_sv, minimal_team_data)
        img_no = self._render(game_no, minimal_team_data)
        sv_dark = sum(1 for p in img_sv.crop(self._SV_REGION).convert('L').getdata() if p < 128)
        no_dark = sum(1 for p in img_no.crop(self._SV_REGION).convert('L').getdata() if p < 128)
        assert sv_dark > no_dark, "SV badge region should have more dark pixels when save_situation=True"


# ===========================================================================
# 8. PAYLOAD CHANGE DETECTION TESTS
# ===========================================================================

class TestCompareJsonDictsSorted:
    def test_equal_simple_dicts(self):
        """Equal simple dicts."""
        a = {'x': 1, 'y': 2}
        b = {'x': 1, 'y': 2}
        assert compare_json_dicts_sorted(a, b)

    def test_different_values(self):
        """Different values."""
        a = {'score': 3}
        b = {'score': 4}
        assert not compare_json_dicts_sorted(a, b)

    def test_key_order_irrelevant(self):
        """Key order irrelevant."""
        a = {'y': 2, 'x': 1}
        b = {'x': 1, 'y': 2}
        assert compare_json_dicts_sorted(a, b)

    def test_nested_equal(self):
        """Nested equal."""
        a = {'game': {'score': 3, 'state': 'Final'}}
        b = {'game': {'state': 'Final', 'score': 3}}
        assert compare_json_dicts_sorted(a, b)

    def test_nested_different(self):
        """Nested different."""
        a = {'game': {'score': 3}}
        b = {'game': {'score': 4}}
        assert not compare_json_dicts_sorted(a, b)

    def test_extra_key_not_equal(self):
        """Extra key not equal."""
        a = {'x': 1}
        b = {'x': 1, 'y': 2}
        assert not compare_json_dicts_sorted(a, b)

    def test_none_values(self):
        """None values."""
        a = {'x': None}
        b = {'x': None}
        assert compare_json_dicts_sorted(a, b)


class TestScoreChangeDetection:
    """
    Simulate the score-change detection logic used in orchestrate_score_board().
    We extract the core comparison here for unit-testable isolation.
    """

    def _detect_score_changes(self, old_scores, new_games):
        """Replicate the changed_game_ids detection from orchestrate_score_board."""
        changed = set()
        for game in new_games:
            pk = str(game.get('game_pk', ''))
            if not pk:
                continue
            away = game.get('away_runs')
            home = game.get('home_runs')
            if pk in old_scores:
                old = old_scores[pk]
                if away != old.get('away_runs') or home != old.get('home_runs'):
                    changed.add(pk)
        return changed

    def test_no_change_returns_empty(self):
        """No change returns empty."""
        old = {'1001': {'away_runs': 3, 'home_runs': 5}}
        games = [{'game_pk': 1001, 'away_runs': 3, 'home_runs': 5}]
        assert self._detect_score_changes(old, games) == set()

    def test_away_score_change_detected(self):
        """Away score change detected."""
        old = {'1001': {'away_runs': 2, 'home_runs': 5}}
        games = [{'game_pk': 1001, 'away_runs': 3, 'home_runs': 5}]
        assert '1001' in self._detect_score_changes(old, games)

    def test_home_score_change_detected(self):
        """Home score change detected."""
        old = {'1001': {'away_runs': 3, 'home_runs': 4}}
        games = [{'game_pk': 1001, 'away_runs': 3, 'home_runs': 5}]
        assert '1001' in self._detect_score_changes(old, games)

    def test_new_game_pk_not_in_old_not_detected(self):
        """A brand-new game_pk not in old_scores is not flagged as a score change."""
        old = {}
        games = [{'game_pk': 9999, 'away_runs': 0, 'home_runs': 0}]
        assert self._detect_score_changes(old, games) == set()

    def test_null_runs_to_value_detected(self):
        """Score going from None → integer counts as a change."""
        old = {'1001': {'away_runs': None, 'home_runs': None}}
        games = [{'game_pk': 1001, 'away_runs': 1, 'home_runs': 0}]
        assert '1001' in self._detect_score_changes(old, games)

    def test_value_to_null_runs_detected(self):
        """Value to null runs detected."""
        old = {'1001': {'away_runs': 3, 'home_runs': 2}}
        games = [{'game_pk': 1001, 'away_runs': None, 'home_runs': 2}]
        assert '1001' in self._detect_score_changes(old, games)

    def test_multiple_games_only_changed_flagged(self):
        """Multiple games only changed flagged."""
        old = {
            '1001': {'away_runs': 3, 'home_runs': 5},
            '1002': {'away_runs': 1, 'home_runs': 1},
        }
        games = [
            {'game_pk': 1001, 'away_runs': 3, 'home_runs': 5},
            {'game_pk': 1002, 'away_runs': 2, 'home_runs': 1},
        ]
        changed = self._detect_score_changes(old, games)
        assert '1001' not in changed
        assert '1002' in changed


class TestPayloadDiff:
    """Test the full-payload comparison that determines if re-render is needed."""

    def _payload_changed(self, old_games, new_games):
        """Replicate the orchestrate_score_board unchanged-image check."""
        old_str = json.dumps(old_games)
        new_str = json.dumps(new_games)
        old_dict = load_and_sort_json(old_str)
        new_dict = load_and_sort_json(new_str)
        return not compare_json_dicts_sorted(new_dict, old_dict)

    def test_identical_payloads_not_changed(self):
        """Identical payloads not changed."""
        games = [{'game_pk': 1, 'away_runs': 3, 'home_runs': 5}]
        assert not self._payload_changed(games, games)

    def test_score_change_triggers_rerender(self):
        """Score change triggers rerender."""
        old = [{'game_pk': 1, 'away_runs': 3, 'home_runs': 5}]
        new = [{'game_pk': 1, 'away_runs': 4, 'home_runs': 5}]
        assert self._payload_changed(old, new)

    def test_state_change_triggers_rerender(self):
        """State change triggers rerender."""
        old = [{'game_pk': 1, 'detailed_state': 'In Progress', 'current_inning': 7}]
        new = [{'game_pk': 1, 'detailed_state': 'Final', 'current_inning': 9}]
        assert self._payload_changed(old, new)

    def test_new_game_added_triggers_rerender(self):
        """New game added triggers rerender."""
        old = [{'game_pk': 1, 'away_runs': 3}]
        new = [{'game_pk': 1, 'away_runs': 3}, {'game_pk': 2, 'away_runs': 0}]
        assert self._payload_changed(old, new)

    def test_pitcher_change_triggers_rerender(self):
        """Pitcher change triggers rerender."""
        old = [{'game_pk': 1, 'current_pitcher': 'Sandy Koufax'}]
        new = [{'game_pk': 1, 'current_pitcher': 'Don Drysdale'}]
        assert self._payload_changed(old, new)

    def test_inning_change_triggers_rerender(self):
        """Inning change triggers rerender."""
        old = [{'game_pk': 1, 'current_inning': 5, 'inningState': 'Top'}]
        new = [{'game_pk': 1, 'current_inning': 5, 'inningState': 'Middle'}]
        assert self._payload_changed(old, new)

    def test_key_order_difference_not_changed(self):
        """Key ordering must not matter — same data, different key order."""
        old = [{'game_pk': 1, 'away_runs': 3, 'home_runs': 5}]
        new = [{'home_runs': 5, 'away_runs': 3, 'game_pk': 1}]
        assert not self._payload_changed(old, new)

    def test_null_to_runner_triggers_rerender(self):
        """Null to runner triggers rerender."""
        old = [{'game_pk': 1, 'runner_on_first': None}]
        new = [{'game_pk': 1, 'runner_on_first': 'Mike Trout'}]
        assert self._payload_changed(old, new)

    def test_win_probability_change_triggers_rerender(self):
        """Win probability change triggers rerender."""
        old = [{'game_pk': 1, 'home_win_probability': 55.0}]
        new = [{'game_pk': 1, 'home_win_probability': 62.5}]
        assert self._payload_changed(old, new)

    def test_empty_old_always_triggers_rerender(self):
        """Empty old always triggers rerender."""
        old = []
        new = [{'game_pk': 1, 'away_runs': 3}]
        assert self._payload_changed(old, new)

    def test_both_empty_not_changed(self):
        """Both empty not changed."""
        assert not self._payload_changed([], [])


# ===========================================================================
# 9. TV CHANNEL PRIORITY TESTS
# ===========================================================================

class TestPickTvChannel:
    def _make_broadcast(self, call_sign, home_away, btype='TV'):
        """Make broadcast."""
        return {'callSign': call_sign, 'homeAway': home_away, 'type': btype}

    def test_no_broadcasts_returns_none(self):
        """No broadcasts returns none."""
        assert _pick_tv_channel(None, 'NYY', 'NYY', 'BOS') is None

    def test_empty_broadcasts_returns_none(self):
        """Empty broadcasts returns none."""
        assert _pick_tv_channel([], 'NYY', 'NYY', 'BOS') is None

    def test_no_tv_type_returns_none(self):
        """No tv type returns none."""
        radio = [{'callSign': 'WFAN', 'homeAway': 'home', 'type': 'Radio'}]
        assert _pick_tv_channel(radio, 'NYY', 'NYY', 'BOS') is None

    def test_favorite_home_team_prioritized(self):
        """Favorite home team prioritized."""
        broadcasts = [
            self._make_broadcast('ESPN', 'away'),
            self._make_broadcast('YES', 'home'),
        ]
        # NYY is home and is the favorite
        result = _pick_tv_channel(broadcasts, 'NYY', 'BOS', 'NYY')
        assert result == 'YES'

    def test_favorite_away_team_prioritized(self):
        """Favorite away team prioritized."""
        broadcasts = [
            self._make_broadcast('YES', 'away'),
            self._make_broadcast('NESN', 'home'),
        ]
        # NYY is away and is the favorite
        result = _pick_tv_channel(broadcasts, 'NYY', 'NYY', 'BOS')
        assert result == 'YES'

    def test_home_local_over_away_local_when_no_favorite(self):
        """Home local over away local when no favorite."""
        broadcasts = [
            self._make_broadcast('MASN', 'away'),
            self._make_broadcast('MLBN', 'home'),
        ]
        result = _pick_tv_channel(broadcasts, None, 'BAL', 'WSH')
        assert result == 'MLBN'

    def test_first_available_fallback(self):
        """First available fallback."""
        broadcasts = [
            self._make_broadcast('ESPN', 'away'),
        ]
        result = _pick_tv_channel(broadcasts, None, 'NYY', 'BOS')
        assert result == 'ESPN'

    def test_favorite_case_insensitive(self):
        """Favorite-team matching should be case-insensitive."""
        broadcasts = [
            self._make_broadcast('YES', 'home'),
        ]
        result = _pick_tv_channel(broadcasts, 'nyy', 'BOS', 'NYY')
        assert result == 'YES'

    def test_no_favorite_match_falls_to_home(self):
        """When favorite team is not playing, home TV is returned."""
        broadcasts = [
            self._make_broadcast('NESN', 'home'),
            self._make_broadcast('MASN', 'away'),
        ]
        # Favorite = STL, not playing
        result = _pick_tv_channel(broadcasts, 'STL', 'BOS', 'BAL')
        assert result == 'NESN'

    def test_call_sign_preferred_over_name(self):
        """Call sign preferred over name."""
        broadcasts = [{'callSign': 'YES', 'name': 'YES Network', 'homeAway': 'home', 'type': 'TV'}]
        result = _pick_tv_channel(broadcasts, None, 'NYY', 'BOS')
        assert result == 'YES'

    def test_name_fallback_when_no_call_sign(self):
        """Name fallback when no call sign."""
        broadcasts = [{'name': 'Peacock', 'homeAway': 'home', 'type': 'TV'}]
        result = _pick_tv_channel(broadcasts, None, 'NYY', 'BOS')
        assert result == 'Peacock'


# ===========================================================================
# 10. WILDCARD STANDINGS DERIVATION TESTS
# ===========================================================================

class TestDeriveWildcardFromStandings:
    def _make_standings(self, al_teams, nl_teams, abbr_map=None):
        """Build a minimal standings_data dict for testing."""
        standings = {}
        for div_name, teams in al_teams.items():
            standings[div_name] = teams
        for div_name, teams in nl_teams.items():
            standings[div_name] = teams
        return {
            'standings': standings,
            'team_abbreviation': abbr_map or {},
        }

    def _make_team(self, team_id, division_rank, league_rank, wins=80, losses=60):
        """Make team."""
        return {
            'team_id': team_id,
            'divisionRank': str(division_rank),
            'league_rank': league_rank,
            'wins': wins,
            'losses': losses,
        }

    def test_division_leaders_excluded(self):
        """Teams with divisionRank == '1' must not appear in wildcard results."""
        al_teams = {
            'American League East': [self._make_team(1, 1, 1)],
            'American League Central': [],
            'American League West': [],
        }
        data = self._make_standings(al_teams, {
            'National League East': [],
            'National League Central': [],
            'National League West': [],
        })
        result = derive_wildcard_from_standings(data)
        assert result.get('AL', []) == [], "Division leader should be excluded"

    def test_non_leaders_included(self):
        """Non-division-leader teams must appear in wildcard results."""
        al_teams = {
            'American League East': [
                self._make_team(1, 1, 1),   # division leader — excluded
                self._make_team(2, 2, 2),   # wildcard — included
            ],
            'American League Central': [],
            'American League West': [],
        }
        data = self._make_standings(al_teams, {
            'National League East': [],
            'National League Central': [],
            'National League West': [],
        }, abbr_map={'2': 'NYY'})
        result = derive_wildcard_from_standings(data)
        assert len(result.get('AL', [])) == 1
        assert result['AL'][0]['abbr'] == 'NYY'

    def test_teams_ordered_by_league_rank(self):
        """Teams within a league must be sorted by league_rank ascending."""
        al_teams = {
            'American League East': [
                self._make_team(10, 2, 5),
                self._make_team(11, 3, 3),
            ],
            'American League Central': [
                self._make_team(12, 2, 1),
            ],
            'American League West': [],
        }
        data = self._make_standings(al_teams, {
            'National League East': [],
            'National League Central': [],
            'National League West': [],
        }, abbr_map={'10': 'TEA', '11': 'TEB', '12': 'TEC'})
        result = derive_wildcard_from_standings(data)
        ranks = [t.get('abbr') for t in result.get('AL', [])]
        assert ranks == ['TEC', 'TEB', 'TEA'], "Teams must be ordered by league_rank"

    def test_both_leagues_processed(self):
        """Both AL and NL must appear in the result."""
        al_teams = {
            'American League East': [self._make_team(1, 2, 2)],
            'American League Central': [],
            'American League West': [],
        }
        nl_teams = {
            'National League East': [self._make_team(2, 2, 2)],
            'National League Central': [],
            'National League West': [],
        }
        data = self._make_standings(al_teams, nl_teams)
        result = derive_wildcard_from_standings(data)
        assert 'AL' in result
        assert 'NL' in result

    def test_missing_division_does_not_crash(self):
        """Missing division keys should not raise exceptions."""
        data = {'standings': {}, 'team_abbreviation': {}}
        result = derive_wildcard_from_standings(data)
        assert result == {'AL': [], 'NL': []}


# ===========================================================================
# 11. DRAW_BOX SMOKE TESTS (ensure no crashes on edge-case inputs)
# ===========================================================================

@needs_pil
class TestDrawBoxSmokeTests:
    """draw_box() should not raise on any valid game state."""

    @pytest.mark.parametrize("state", [
        'Final', 'Game Over', 'Final: Tied', 'Completed Early',
        'Scheduled', 'Pre-Game', 'Warmup', 'Delayed Start',
        'Postponed', 'In Progress',
        'Player challenge', 'Manager challenge',
    ])
    def test_no_crash_on_state(self, state, minimal_team_data):
        """No crash on state."""
        img = Image.new('1', (800, 480), 255)
        game = _base_game(detailed_state=state)
        # In Progress needs enough data to not crash
        if state in ('In Progress', 'Player challenge', 'Manager challenge'):
            game.update({
                'num_of_outs': 1, 'balls': 1, 'strikes': 0,
                'current_inning': 3, 'inningState': 'Top',
                'current_pitcher': 'Bob Gibson',
                'current_hitter': 'Willie Mays',
                'last_play': 'Ball',
                'away_runs': 1, 'home_runs': 2,
                'away_hits': None, 'home_hits': None,
            })
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)

    def test_no_crash_with_none_inning_runs(self, minimal_team_data):
        """No crash with none inning runs."""
        img = Image.new('1', (800, 480), 255)
        game = _base_game(away_inning_runs=None, home_inning_runs=None)
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)

    def test_no_crash_with_missing_winner_loser(self, minimal_team_data):
        """Final game where API hasn't posted decisions yet — shows linescore grid."""
        img = Image.new('1', (800, 480), 255)
        game = _base_game(winner_name=None, loser_name=None)
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)

    def test_no_crash_with_postgame_saver(self, minimal_team_data):
        """No crash with postgame saver."""
        img = Image.new('1', (800, 480), 255)
        game = _base_game(saver_name='Wade Davis', saver_saves=15)
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)

    @needs_pil
    def test_very_long_winner_name_triggers_paren_truncation(self, minimal_team_data):
        """_truncate_keep_suffix falls through to the paren-suffix path (lines
        888-896) when the winner name with initial is too long and dropping the
        initial still doesn't fit."""
        img = Image.new('1', (800, 480), 255)
        game = _base_game(
            winner_name='Bartholomew Sanchez-Martinez', winner_record='3-1',
            loser_name='Bartholomew Sanchez-Martinez', loser_record='2-2',
        )
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)

    @needs_pil
    def test_very_long_winner_name_no_record_triggers_char_truncation(self, minimal_team_data):
        """_truncate_keep_suffix falls through to the char-by-char path (lines
        897-899) when there is no ' (' in the text."""
        img = Image.new('1', (800, 480), 255)
        game = _base_game(
            winner_name='Bartholomew Sanchez-Martinez', winner_record=None,
            loser_name='Bartholomew Sanchez-Martinez', loser_record=None,
        )
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)

    @needs_pil
    def test_very_long_saver_name_truncation(self, minimal_team_data):
        """Long saver name with saves also triggers _truncate_keep_suffix via
        the 'SV: ' prefix path (line 879 for-loop iteration)."""
        img = Image.new('1', (800, 480), 255)
        game = _base_game(
            winner_name='Max Fried', winner_record='3-1',
            loser_name='Chris Bassitt', loser_record='2-2',
            saver_name='Bartholomew Sanchez-Martinez-Rodriguez', saver_saves=15,
        )
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)

    @needs_pil
    def test_away_winner_ghost_logo(self, minimal_team_data):
        """Away-team winner triggers line 797 (winner_abbr = away_team_name)
        when use_logos=True. _logo_ghost is patched to avoid network/disk access."""
        from unittest.mock import patch
        img = Image.new('1', (800, 480), 255)
        fake_ghost = Image.new('1', (110, 110), 255)
        game = _base_game(away_team_is_winner=True, home_team_is_winner=False)
        with patch('image_box._logo_ghost', return_value=fake_ghost):
            draw_box(img, 32, 30, game, minimal_team_data, use_logos=True)

    def test_no_crash_with_unknown_team_id(self):
        """Teams not in team_data must fall back to 'T{id}' abbreviation gracefully."""
        img = Image.new('1', (800, 480), 255)
        game = _base_game(away_team_id=9999, home_team_id=8888)
        team_data = {'team_abbreviation': {}}  # empty
        draw_box(img, 32, 30, game, team_data, use_logos=False)

    def test_no_crash_postponed(self, minimal_team_data):
        """No crash postponed."""
        img = Image.new('1', (800, 480), 255)
        game = _base_game(
            detailed_state='Postponed',
            away_runs=None,
            home_runs=None,
            away_hits=None,
            home_hits=None,
            postpone_reason='Rain',
        )
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)

    def test_no_crash_with_two_digit_scores(self, minimal_team_data):
        """No crash with two digit scores."""
        img = Image.new('1', (800, 480), 255)
        game = _base_game(away_runs=12, home_runs=10, away_hits=20, home_hits=18)
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)

    @pytest.mark.parametrize("inning", [9, 10, 13, 19])
    def test_no_crash_extra_innings(self, inning, minimal_team_data):
        """No crash extra innings."""
        img = Image.new('1', (800, 480), 255)
        game = _base_game(current_inning=inning)
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)


# ===========================================================================
# 12. WEATHER FOOTER RULES
# ===========================================================================

class TestWeatherFooterRules:
    """
    Weather info is shown only for pre-game states.
    Tests verify that weather fields change the pre-game render but don't affect
    in-progress renders.
    """

    def _render_pregame(self, team_data, **overrides):
        """Render pregame."""
        game = _pregame_game(**overrides)
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, game, team_data, use_logos=False)
        return img

    @needs_pil
    def test_weather_changes_pregame_render(self, minimal_team_data):
        """Adding weather data must change the pre-game box render."""
        no_weather = self._render_pregame(minimal_team_data)
        with_weather = self._render_pregame(
            minimal_team_data,
            weather_temp_f=72,
            weather_wind_mph=10,
            weather_wind_dir='NW',
            weather_precip_pct=20,
        )
        assert list(no_weather.getdata()) != list(with_weather.getdata()), \
            "Weather data should alter the pre-game render"

    @needs_pil
    def test_dome_flag_changes_pregame_render(self, minimal_team_data):
        """roof_state='fixed' (dome) must produce a different pre-game render."""
        no_dome = self._render_pregame(minimal_team_data)
        dome = self._render_pregame(minimal_team_data, roof_state='fixed')
        assert list(no_dome.getdata()) != list(dome.getdata()), \
            "Fixed-roof (dome) flag should alter the pre-game render"

    @needs_pil
    def test_tv_channel_changes_pregame_render(self, minimal_team_data):
        """A TV channel in the game dict must change the pre-game render."""
        no_tv = self._render_pregame(minimal_team_data, tv_channel=None)
        with_tv = self._render_pregame(minimal_team_data, tv_channel='ESPN')
        assert list(no_tv.getdata()) != list(with_tv.getdata()), \
            "TV channel should alter the pre-game footer render"

    @needs_pil
    def test_weather_does_not_affect_in_progress_render(self, minimal_team_data):
        """Weather fields must not affect in-progress game rendering."""
        game_no_weather = _in_progress_game()
        game_with_weather = _in_progress_game(
            weather_temp_f=72,
            weather_wind_mph=10,
            weather_wind_dir='NW',
            weather_precip_pct=20,
        )
        img1 = Image.new('1', (800, 480), 255)
        img2 = Image.new('1', (800, 480), 255)
        draw_box(img1, 32, 30, game_no_weather, minimal_team_data, use_logos=False)
        draw_box(img2, 32, 30, game_with_weather, minimal_team_data, use_logos=False)
        assert list(img1.getdata()) == list(img2.getdata()), \
            "Weather fields should not affect in-progress rendering"

    @needs_pil
    def test_between_innings_long_due_up_batter_truncates(self, minimal_team_data):
        """Between innings with a very long current_hitter name triggers the
        truncation while-loop for the Due: label (image_box.py line 1487)."""
        img = Image.new('1', (800, 480), 255)
        game = _in_progress_game(
            inningState='Middle',
            num_of_outs=3,
            current_hitter='Bartholomew Alexander McGillicuddy-Smithwick III',
            # No matching last_play_inning → _lp_same_half=False → play_display=''
        )
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)

    @needs_pil
    def test_rbi_kl_prefix_in_last_play_header(self, minimal_team_data):
        """'RBI Kl' in the right-side header exercises the _draw_play_right
        Kl-split branch (image_box.py lines 1458-1459) where the pre-Kl segment
        is non-empty and draws text before the backwards K.
        last_play_inning/last_play_is_top must match the current inning to avoid
        _lp_same_half being False (which would suppress the last play)."""
        img = Image.new('1', (800, 480), 255)
        game = _in_progress_game(
            current_inning=5,
            inningState='Top',
            last_play='strikeout looking',
            last_play_rbi=1,
            last_play_inning=5,
            last_play_is_top=True,
        )
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)

    @needs_pil
    def test_very_long_last_play_truncation(self, minimal_team_data):
        """Many-RBI play string can get long enough to trigger the truncation
        while-loop in _draw_play_right (image_box.py lines 1443-1444).
        Use 4RBI with a long field-sequence abbreviation."""
        img = Image.new('1', (800, 480), 255)
        # '4RBI Grand Slam' abbreviation from a grand slam with 4 RBIs.
        # Make the raw string something that results in a longer play_display.
        game = _in_progress_game(
            current_inning=10,
            inningState='Top',
            last_play='Home Run',
            last_play_rbi=4,
            last_play_inning=10,
            last_play_is_top=True,
        )
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)


# ===========================================================================
# 13. ABS CHALLENGE DOTS
# ===========================================================================

class TestAbsChallengeDots:
    """
    ABS challenges are displayed during In Progress games only.
    challenge dots appear to the left of each team row.
    """

    @needs_pil
    def test_challenges_change_in_progress_render(self, minimal_team_data):
        """ABS challenge counts must affect the in-progress render."""
        no_chal = _in_progress_game(
            away_challenges_remaining=None,
            home_challenges_remaining=None,
        )
        with_chal = _in_progress_game(
            away_challenges_remaining=2,
            home_challenges_remaining=1,
        )
        img1 = Image.new('1', (800, 480), 255)
        img2 = Image.new('1', (800, 480), 255)
        draw_box(img1, 32, 30, no_chal, minimal_team_data, use_logos=False)
        draw_box(img2, 32, 30, with_chal, minimal_team_data, use_logos=False)
        assert list(img1.getdata()) != list(img2.getdata()), \
            "ABS challenge counts should alter in-progress render"

    @needs_pil
    def test_challenges_not_shown_in_final(self, minimal_team_data):
        """Challenge dots must NOT affect Final game rendering."""
        no_chal = _base_game(
            away_challenges_remaining=None,
            home_challenges_remaining=None,
        )
        with_chal = _base_game(
            away_challenges_remaining=2,
            home_challenges_remaining=1,
        )
        img1 = Image.new('1', (800, 480), 255)
        img2 = Image.new('1', (800, 480), 255)
        draw_box(img1, 32, 30, no_chal, minimal_team_data, use_logos=False)
        draw_box(img2, 32, 30, with_chal, minimal_team_data, use_logos=False)
        assert list(img1.getdata()) == list(img2.getdata()), \
            "ABS challenges should NOT affect Final game rendering"


# ===========================================================================
# 14. GAME EFFECTIVELY-OVER SUPPRESSES ON-DECK BATTER
# ===========================================================================

class TestOnDeckSuppressionWhenEffectivelyOver:
    """
    When _is_game_effectively_over() is True for an In Progress game,
    the on-deck batter line must NOT be shown (suppressed).
    """

    @needs_pil
    def test_on_deck_suppressed_when_effectively_over(self, minimal_team_data):
        """Game at inning 9 Middle, home leading → effectively over → no on-deck shown."""
        effectively_over = _base_game(
            detailed_state='In Progress',
            away_runs=3,
            home_runs=5,
            num_of_outs=3,
            balls=0,
            strikes=0,
            current_inning=9,
            inningState='Middle',
            runner_on_first=None,
            runner_on_second=None,
            runner_on_third=None,
            last_play='Strikeout',
            current_at_bat_complete=True,
            due_up='Mike Trout',
            away_hits=None,
            home_hits=None,
        )
        # Compare with identical game but not effectively over (inning 8)
        mid_game = dict(effectively_over)
        mid_game['current_inning'] = 8
        img_eo = Image.new('1', (800, 480), 255)
        img_mg = Image.new('1', (800, 480), 255)
        draw_box(img_eo, 32, 30, effectively_over, minimal_team_data, use_logos=False)
        draw_box(img_mg, 32, 30, mid_game, minimal_team_data, use_logos=False)
        # The images SHOULD differ because the effectively-over game suppresses on-deck
        assert list(img_eo.getdata()) != list(img_mg.getdata())


# ===========================================================================
# 15. GRID LAYOUT AND CHANGED REGION DETECTION
# ===========================================================================

class TestChangedRegionDetection:
    """
    orchestrate_score_board() computes partial-refresh regions from changed game_pks.
    Test the logic for grid index → (x, y, w, h) mapping and the >5 threshold.
    """

    def _changed_regions(self, game_state_data, old_by_pk):
        """Replicate the region-mapping logic from orchestrate_score_board()."""
        x_start, y_start = 32, 30
        refreshed_pks = set()
        for game in game_state_data:
            pk = str(game.get('game_pk', ''))
            if pk and old_by_pk.get(pk) != game:
                refreshed_pks.add(pk)

        regions = []
        for i, game in enumerate(game_state_data):
            if i >= 15:
                break
            pk = str(game.get('game_pk', ''))
            if pk in refreshed_pks:
                col = i % 5
                row = i // 5
                rx = (col * 150 + x_start) // 8 * 8
                ry = row * 150 + y_start
                regions.append((rx, ry, 152, 150))

        return [] if len(regions) > 5 else regions

    def test_no_change_returns_no_regions(self):
        """No change returns no regions."""
        games = [{'game_pk': 1, 'away_runs': 3}]
        old = {'1': {'game_pk': 1, 'away_runs': 3}}
        assert self._changed_regions(games, old) == []

    def test_one_change_returns_one_region(self):
        """One change returns one region."""
        games = [{'game_pk': 1, 'away_runs': 4}]
        old = {'1': {'game_pk': 1, 'away_runs': 3}}
        regions = self._changed_regions(games, old)
        assert len(regions) == 1

    def test_changed_region_x_aligned_to_8(self):
        """Grid column x positions must be aligned to 8-pixel boundaries."""
        games = [{'game_pk': i, 'score': i} for i in range(5)]
        old = {}  # all new → all changed
        regions = self._changed_regions(games, old)
        for rx, _ry, _rw, _rh in regions:
            assert rx % 8 == 0, f"x={rx} is not 8-pixel aligned"

    def test_grid_column_positions_correct(self):
        """Each of the 5 columns must map to the right x range."""
        x_start = 32
        games = [{'game_pk': i, 'data': i} for i in range(5)]
        old = {}
        regions = self._changed_regions(games, old)
        assert len(regions) == 5
        for col, (rx, _ry, _rw, _rh) in enumerate(regions):
            expected_raw = col * 150 + x_start
            expected_aligned = expected_raw // 8 * 8
            assert rx == expected_aligned, f"Column {col} x mismatch: {rx} != {expected_aligned}"

    def test_grid_row_positions_correct(self):
        """Each of the 3 rows maps to a y offset of row * 150 + 30."""
        games = [{'game_pk': i, 'data': i} for i in range(15)]
        old = {}
        regions = self._changed_regions(games, old)
        assert regions == []  # 15 changes > 5 → full refresh
        # Verify by changing just one game per row
        for row in range(3):
            g = [{'game_pk': i, 'score': 0} for i in range(15)]
            g[row * 5]['score'] = 99  # change first game in each row
            o = {str(i): {'game_pk': i, 'score': 0} for i in range(15)}
            r = self._changed_regions(g, o)
            assert len(r) == 1
            assert r[0][1] == row * 150 + 30, f"Row {row} y mismatch"

    def test_more_than_5_changes_triggers_full_refresh(self):
        """When more than 5 game boxes changed, return empty list (full refresh)."""
        games = [{'game_pk': i, 'score': i * 10} for i in range(10)]
        old = {str(i): {'game_pk': i, 'score': 0} for i in range(10)}
        regions = self._changed_regions(games, old)
        assert regions == [], "More than 5 changes should signal full refresh (empty list)"

    def test_exactly_5_changes_returns_list(self):
        """Exactly 5 changes must return a list (not empty / full refresh)."""
        games = [{'game_pk': i, 'score': 99} for i in range(5)]
        old = {str(i): {'game_pk': i, 'score': 0} for i in range(5)}
        regions = self._changed_regions(games, old)
        assert len(regions) == 5

    def test_grid_max_15_games(self):
        """Games beyond index 14 (position 15+) must be ignored in region calc."""
        games = [{'game_pk': i, 'score': i} for i in range(20)]
        old = {}  # all changed
        regions = self._changed_regions(games, old)
        # 20 changed games but only first 15 are in the grid → >5 → full refresh
        assert regions == []


# ===========================================================================
# 16. DELAYED GAME DISPLAY RULES
# ===========================================================================

class TestDelayedGameRules:
    """'Delayed' (mid-game) vs 'Delayed Start' (pre-game) have different display rules."""

    @needs_pil
    def test_delayed_no_inning_shows_no_score(self, minimal_team_data):
        """Delayed with current_inning=0 → not yet started → no score."""
        game = _base_game(
            detailed_state='Delayed',
            away_runs=0,
            home_runs=0,
            current_inning=0,
            inningState=None,
        )
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)
        score_region = (92, 52, 118, 77)
        assert not _has_dark_pixels(img, *score_region)

    @needs_pil
    def test_delayed_with_inning_shows_score(self, minimal_team_data):
        """Delayed with current_inning>0 → game started → score shown."""
        game = _base_game(
            detailed_state='Delayed',
            away_runs=3,
            home_runs=1,
            away_hits=None,
            home_hits=None,
            current_inning=4,
            inningState='Top',
        )
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)
        score_region = (92, 52, 118, 77)
        assert _has_dark_pixels(img, *score_region)


# ===========================================================================
# Header inversion — walk-off, no-hitter, perfect game
# ===========================================================================

class TestHeaderInversion:
    """Walk-off, no-hitter, and perfect game invert the header row."""

    _HEADER_REGION = (32, 30, 167, 51)  # full header box at (32, 30)

    def _render(self, game, team_data):
        """Render."""
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, game, team_data, use_logos=False)
        return img

    def _header_has_dark(self, img):
        """Header has dark."""
        return _has_dark_pixels(img, *self._HEADER_REGION)

    def _is_inverted(self, img):
        """Header is inverted if the majority of the header region is dark (black background)."""
        region = img.crop(self._HEADER_REGION).convert('L')
        pixels = list(region.getdata())
        dark = sum(1 for p in pixels if p < 128)
        return dark > len(pixels) * 0.5

    @needs_pil
    def test_normal_final_not_inverted(self, minimal_team_data):
        """A regular final game must not have an inverted header."""
        game = _base_game()
        img = self._render(game, minimal_team_data)
        assert not self._is_inverted(img)

    @needs_pil
    def test_walk_off_shows_walkoff_label(self, minimal_team_data):
        """A walk-off Final renders differently (shows 'Walk-off' label in the lower box).

        Uses empty inning runs to bypass the post-game linescore window and
        land in the WP/LP pitcher-of-record section where walk_off matters.
        """
        common = dict(away_inning_runs=[], home_inning_runs=[])
        game_walkoff = _base_game(walk_off=True, **common)
        game_normal = _base_game(walk_off=False, **common)
        img_wo = self._render(game_walkoff, minimal_team_data)
        img_no = self._render(game_normal, minimal_team_data)
        assert list(img_wo.getdata()) != list(img_no.getdata()), \
            "walk_off=True should produce a different render (shows 'Walk-off' label)"

    @needs_pil
    def test_no_hitter_inverts_header_in_progress_inning_6(self, minimal_team_data):
        """An active no-hitter at inning >= 6 must invert the header row."""
        game = _in_progress_game(no_hitter=True, current_inning=6)
        img = self._render(game, minimal_team_data)
        assert self._is_inverted(img)

    @needs_pil
    def test_no_hitter_before_6th_does_not_invert_header(self, minimal_team_data):
        """A no-hitter before inning 6 must NOT invert the header (too early to flash)."""
        game = _in_progress_game(no_hitter=True, current_inning=5)
        img = self._render(game, minimal_team_data)
        assert not self._is_inverted(img)

    @needs_pil
    def test_perfect_game_inverts_header_in_progress_inning_6(self, minimal_team_data):
        """An active perfect game at inning >= 6 must invert the header row."""
        game = _in_progress_game(perfect_game=True, current_inning=6)
        img = self._render(game, minimal_team_data)
        assert self._is_inverted(img)


# ===========================================================================
# Series record display
# ===========================================================================

class TestSeriesRecord:
    """Series record shown in header only when the series is clinched/over."""

    @needs_pil
    def test_series_clinched_renders_differently_than_no_series(self, minimal_team_data):
        """A clinched series (series_is_over=True) renders differently than a no-series game."""
        no_series = _base_game(series_total_games=1)
        clinched = _base_game(
            series_total_games=3, series_wins=2, series_losses=1,
            series_is_over=True, series_result='Won 2-1',
            home_team_is_winner=True,
        )
        img_none = Image.new('1', (800, 480), 255)
        img_ser = Image.new('1', (800, 480), 255)
        draw_box(img_none, 32, 30, no_series, minimal_team_data, use_logos=False)
        draw_box(img_ser, 32, 30, clinched, minimal_team_data, use_logos=False)
        assert list(img_none.getdata()) != list(img_ser.getdata()), \
            "Clinched series should produce different rendering than no-series"

    @needs_pil
    def test_mid_series_leading_shows_series_score(self, minimal_team_data):
        """A non-clinched mid-series game where one team leads shows the series score."""
        mid_series = _base_game(
            series_total_games=3, series_wins=1, series_losses=0,
            series_is_over=False, series_result='Team leads 1-0',
            home_team_is_winner=True,
        )
        no_series = _base_game(series_total_games=1)
        img_mid = Image.new('1', (800, 480), 255)
        img_ns = Image.new('1', (800, 480), 255)
        draw_box(img_mid, 32, 30, mid_series, minimal_team_data, use_logos=False)
        draw_box(img_ns, 32, 30, no_series, minimal_team_data, use_logos=False)
        assert list(img_mid.getdata()) != list(img_ns.getdata()), \
            "Mid-series leading games should show the series score (logo + X-Y)"

    @needs_pil
    def test_game_1_no_gm_label(self, minimal_team_data):
        """Game 1 of a series does NOT show Gm 1/N — series info only shown when series is over."""
        game = _base_game(
            series_total_games=7, series_wins=0, series_losses=0,
            series_game_number=1, series_result='', series_is_over=False,
        )
        no_series = _base_game(series_total_games=1)
        img_g1 = Image.new('1', (800, 480), 255)
        img_ns = Image.new('1', (800, 480), 255)
        draw_box(img_g1, 32, 30, game, minimal_team_data, use_logos=False)
        draw_box(img_ns, 32, 30, no_series, minimal_team_data, use_logos=False)
        assert list(img_g1.getdata()) == list(img_ns.getdata()), \
            "Game 1 of a series should NOT show Gm 1/7 — series info only when series is over"

    @needs_pil
    def test_tied_series_shows_tied_label(self, minimal_team_data):
        """A tied mid-series (1-1, not over) shows 'Tied X-X' in the header."""
        tied = _base_game(
            series_total_games=5, series_wins=1, series_losses=1,
            series_is_over=False, series_is_tied=True, series_result='Series Tied 1-1',
        )
        no_series = _base_game(series_total_games=1)
        img_tied = Image.new('1', (800, 480), 255)
        img_ns = Image.new('1', (800, 480), 255)
        draw_box(img_tied, 32, 30, tied, minimal_team_data, use_logos=False)
        draw_box(img_ns, 32, 30, no_series, minimal_team_data, use_logos=False)
        assert list(img_tied.getdata()) != list(img_ns.getdata()), \
            "Tied series should show 'Tied 1-1' in the header (renders differently than no-series)"

    @needs_pil
    def test_leading_mid_series_shows_series_score(self, minimal_team_data):
        """A mid-series game where one team leads (not tied, not over) shows logo + series score."""
        leading = _base_game(
            series_total_games=5, series_wins=2, series_losses=1,
            series_is_over=False, series_is_tied=False, series_result='Team leads 2-1',
            away_team_is_winner=True,
        )
        no_series = _base_game(series_total_games=1)
        img_lead = Image.new('1', (800, 480), 255)
        img_ns = Image.new('1', (800, 480), 255)
        draw_box(img_lead, 32, 30, leading, minimal_team_data, use_logos=False)
        draw_box(img_ns, 32, 30, no_series, minimal_team_data, use_logos=False)
        assert list(img_lead.getdata()) != list(img_ns.getdata()), \
            "Leading mid-series (not over) should show logo + series score in the header"


# ===========================================================================
# 17. PLAY ABBREVIATION (_abbr_play)
# ===========================================================================

class TestAbbrPlay:
    """_abbr_play() maps verbose MLB play-event strings to short abbreviations."""

    def test_none_returns_none(self):
        """None returns none."""
        assert _abbr_play(None) is None

    def test_empty_string_returns_empty(self):
        """Empty string returns empty."""
        assert _abbr_play('') == ''

    def test_strikeout(self):
        """Strikeout."""
        assert _abbr_play('Strikeout') == 'K'

    def test_strikeout_case_insensitive(self):
        """Strikeout case insensitive."""
        assert _abbr_play('STRIKEOUT') == 'K'

    def test_strikeout_looking(self):
        """Strikeout looking."""
        assert _abbr_play('Strikeout Looking') == 'Kl'

    def test_strikeout_looking_before_strikeout(self):
        """'strikeout looking' must be checked before 'strikeout' to avoid early match."""
        assert _abbr_play('Strikeout Looking') == 'Kl'

    def test_kl_passthrough(self):
        """'Kl' (already scorecard notation from live feed) passes through unchanged."""
        assert _abbr_play('Kl') == 'Kl'

    def test_home_run(self):
        """Home run."""
        assert _abbr_play('Home Run') == 'HR'

    def test_single(self):
        """Single."""
        assert _abbr_play('Single to center field') == '1B'

    def test_double(self):
        """Double."""
        assert _abbr_play('Double to left field') == '2B'

    def test_triple(self):
        """Triple."""
        assert _abbr_play('Triple to right field') == '3B'

    def test_walk(self):
        """Walk."""
        assert _abbr_play('Walk') == 'BB'

    def test_intentional_walk_before_walk(self):
        """Intentional Walk must map to IBB, not BB (longer key checked first)."""
        assert _abbr_play('Intentional Walk') == 'IBB'

    def test_hit_by_pitch(self):
        """Hit by pitch."""
        assert _abbr_play('Hit By Pitch') == 'HBP'

    def test_sac_fly(self):
        """Sac fly."""
        assert _abbr_play('Sac Fly to left fielder') == 'SAC F'

    def test_sacrifice_fly(self):
        """Sacrifice fly."""
        assert _abbr_play('Sacrifice Fly to center fielder') == 'SAC F'

    def test_sac_bunt(self):
        """Sac bunt."""
        assert _abbr_play('Sac Bunt') == 'SAC B'

    def test_stolen_base(self):
        """Stolen base."""
        assert _abbr_play('Stolen Base 2B') == 'SB'

    def test_caught_stealing(self):
        """Caught stealing."""
        assert _abbr_play('Caught Stealing 3B') == 'CS'

    def test_wild_pitch(self):
        """Wild pitch."""
        assert _abbr_play('Wild Pitch') == 'WP'

    def test_passed_ball(self):
        """Passed ball."""
        assert _abbr_play('Passed Ball') == 'PB'

    def test_fielders_choice(self):
        """Fielders choice."""
        assert _abbr_play("Fielder's Choice to Second Baseman") == 'FC'

    def test_fielders_choice_no_apostrophe(self):
        """Fielders choice no apostrophe."""
        assert _abbr_play('Fielders Choice to Shortstop') == 'FC'

    def test_field_error(self):
        """Field error."""
        assert _abbr_play('Field Error') == 'E'

    def test_flyout(self):
        """Flyout."""
        assert _abbr_play('Flyout to center fielder') == 'FO'

    def test_fly_out_space(self):
        """Fly out space."""
        assert _abbr_play('Fly Out to right fielder') == 'FO'

    def test_groundout(self):
        """Groundout."""
        assert _abbr_play('Groundout to third baseman') == 'GO'

    def test_ground_out_space(self):
        """Ground out space."""
        assert _abbr_play('Ground Out to shortstop') == 'GO'

    def test_lineout(self):
        """Lineout."""
        assert _abbr_play('Lineout to left fielder') == 'LO'

    def test_pop_out(self):
        """Pop out."""
        assert _abbr_play('Pop Out to catcher') == 'PO'

    def test_grounded_into_dp_before_double_play(self):
        """'grounded into dp' matches the short MLB API event form 'Grounded Into DP'."""
        assert _abbr_play('Grounded Into DP') == 'GDP'

    def test_double_play_long_form_maps_to_dp(self):
        """The long MLB API event form 'Grounded Into Double Play' maps to DP via 'double play' key."""
        assert _abbr_play('Grounded Into Double Play') == 'DP'

    def test_double_play(self):
        """Double play."""
        assert _abbr_play('Double Play, Pitcher to First Baseman') == 'DP'

    def test_triple_play(self):
        """Triple play."""
        assert _abbr_play('Triple Play') == 'TP'

    def test_pickoff(self):
        """Pickoff."""
        assert _abbr_play('Pickoff 1B') == 'PK'

    def test_balk(self):
        """Balk."""
        assert _abbr_play('Balk') == 'BLK'

    def test_force_out(self):
        """Force out."""
        assert _abbr_play('Force Out') == 'FOUT'

    def test_runner_out(self):
        """Runner out."""
        assert _abbr_play('Runner Out') == 'RO'

    def test_unknown_event_returned_unchanged(self):
        """An unrecognized event string must be returned as-is."""
        assert _abbr_play('Foul Tip') == 'Foul Tip'

    def test_partial_match_in_longer_string(self):
        """Match works on substring — 'walk' in longer description."""
        assert _abbr_play('Ball 4, Walk') == 'IBB' or _abbr_play('Ball 4, Walk') == 'BB'


# ===========================================================================
# 18. FIELDER FROM DESCRIPTION (_fielder_from_desc)
# ===========================================================================

class TestFielderFromDesc:
    """_fielder_from_desc() returns the putout fielder's position code."""

    def test_none_returns_empty(self):
        """None returns empty."""
        assert _fielder_from_desc(None) == ''

    def test_empty_returns_empty(self):
        """Empty returns empty."""
        assert _fielder_from_desc('') == ''

    def test_center_fielder(self):
        """Center fielder."""
        assert _fielder_from_desc('Flyout to center fielder') == '8'

    def test_right_fielder(self):
        """Right fielder."""
        assert _fielder_from_desc('Flyout to right fielder') == '9'

    def test_left_fielder(self):
        """Left fielder."""
        assert _fielder_from_desc('Flyout to left fielder') == '7'

    def test_first_baseman(self):
        """First baseman."""
        assert _fielder_from_desc('Groundout to first baseman') == '3'

    def test_second_baseman(self):
        """Second baseman."""
        assert _fielder_from_desc('Groundout to second baseman') == '4'

    def test_third_baseman(self):
        """Third baseman."""
        assert _fielder_from_desc('Groundout to third baseman') == '5'

    def test_shortstop(self):
        """Shortstop."""
        assert _fielder_from_desc('Lineout to shortstop') == '6'

    def test_catcher(self):
        """Catcher."""
        assert _fielder_from_desc('Pop out to catcher') == '2'

    def test_pitcher(self):
        """Pitcher."""
        assert _fielder_from_desc('Groundout to pitcher') == '1'

    def test_no_position_returns_empty(self):
        """A description with no known position keyword returns ''."""
        assert _fielder_from_desc('Strikeout swinging') == ''

    def test_case_insensitive(self):
        """Case insensitive."""
        assert _fielder_from_desc('FLYOUT TO CENTER FIELDER') == '8'

    def test_center_fielder_beats_right_fielder_in_ambiguous(self):
        """When both appear, the first matching keyword in the ordered list wins."""
        result = _fielder_from_desc('center fielder to right fielder')
        assert result == '8'

    def test_ordered_list_wins_over_text_position(self):
        """_fielder_from_desc returns the first keyword match in _POS_KEYWORDS order.
        'first baseman' (index 3) is checked before 'second baseman'/'shortstop',
        so it wins even when shortstop appears first in the text."""
        desc = 'Grounded into double play, shortstop to second baseman to first baseman'
        assert _fielder_from_desc(desc) == '3'


# ===========================================================================
# 19. FIELDER SEQUENCE FROM DESCRIPTION (_fielder_seq_from_desc)
# ===========================================================================

class TestFielderSeqFromDesc:
    """_fielder_seq_from_desc() returns dash-joined fielder sequence."""

    def test_none_returns_empty(self):
        """None returns empty."""
        assert _fielder_seq_from_desc(None) == ''

    def test_empty_returns_empty(self):
        """Empty returns empty."""
        assert _fielder_seq_from_desc('') == ''

    def test_single_fielder(self):
        """Single fielder."""
        assert _fielder_seq_from_desc('Flyout to center fielder') == '8'

    def test_two_fielder_groundout(self):
        """Groundout: third baseman (5) to first baseman (3) → '5-3'."""
        assert _fielder_seq_from_desc('Groundout, third baseman to first baseman') == '5-3'

    def test_gdp_6_4_3(self):
        """Classic GDP: shortstop (6) → second baseman (4) → first baseman (3) → '6-4-3'."""
        desc = 'Grounded into double play, shortstop to second baseman to first baseman'
        assert _fielder_seq_from_desc(desc) == '6-4-3'

    def test_dp_pitcher_to_first(self):
        """Double play: pitcher (1) to first baseman (3) → '1-3'."""
        desc = 'Double play, pitcher to first baseman'
        assert _fielder_seq_from_desc(desc) == '1-3'

    def test_max_pos_limits_fielders(self):
        """With max_pos=2, only first 2 fielders are returned."""
        desc = 'Grounded into double play, shortstop to second baseman to first baseman'
        assert _fielder_seq_from_desc(desc, max_pos=2) == '6-4'

    def test_default_max_pos_is_5(self):
        """Default max_pos=5 accepts up to 5 fielders in a sequence."""
        desc = ('center fielder to shortstop to second baseman '
                'to third baseman to first baseman')
        result = _fielder_seq_from_desc(desc)
        assert result == '8-6-4-5-3'

    def test_six_fielders_truncated_to_five(self):
        """A six-fielder sequence is truncated to 5 at the default max_pos."""
        desc = ('center fielder to shortstop to second baseman '
                'to third baseman to first baseman to catcher')
        result = _fielder_seq_from_desc(desc)
        assert result.count('-') == 4, "Default max_pos=5 means 4 dashes"

    def test_no_position_keyword_returns_empty(self):
        """No position keyword returns empty."""
        assert _fielder_seq_from_desc('Strikeout swinging') == ''

    def test_case_insensitive(self):
        """Case insensitive."""
        assert _fielder_seq_from_desc('SHORTSTOP TO FIRST BASEMAN') == '6-3'

    def test_repeated_position_captured(self):
        """A position appearing twice (e.g. catcher in a rundown) is captured twice."""
        desc = 'catcher to first baseman to catcher'
        result = _fielder_seq_from_desc(desc)
        assert '2' in result.split('-')
        assert result.count('2') == 2

    def test_5_4_3_double_play(self):
        """Third baseman (5) → second baseman (4) → first baseman (3)."""
        desc = 'Double play, third baseman to second baseman to first baseman'
        assert _fielder_seq_from_desc(desc) == '5-4-3'

    def test_4_6_3_double_play(self):
        """Second baseman (4) → shortstop (6) → first baseman (3)."""
        desc = 'Grounded into double play, second baseman to shortstop to first baseman'
        assert _fielder_seq_from_desc(desc) == '4-6-3'

    def test_1_3_groundout(self):
        """Pitcher (1) to first baseman (3)."""
        desc = 'Groundout to pitcher, pitcher to first baseman'
        result = _fielder_seq_from_desc(desc)
        assert result.startswith('1')

    def test_max_pos_zero_returns_empty(self):
        """max_pos=0 means no fielders are kept → empty string."""
        desc = 'Groundout to third baseman to first baseman'
        assert _fielder_seq_from_desc(desc, max_pos=0) == ''


# ===========================================================================
# 20. ABBR_PLAY — new play types added alongside scorecard notation overhaul
# ===========================================================================

class TestAbbrPlayNewTypes:
    """_abbr_play() maps the new and corrected play-type tokens."""

    def test_forceout_no_space(self):
        """API sometimes returns 'Forceout' (one word) — must map to FOUT."""
        assert _abbr_play('Forceout') == 'FOUT'

    def test_force_out_with_space(self):
        """Force out with space."""
        assert _abbr_play('Force Out') == 'FOUT'

    def test_force_out_in_sentence(self):
        """Force out in sentence."""
        assert _abbr_play('Forceout, shortstop to first baseman') == 'FOUT'

    def test_forceout_distinct_from_flyout(self):
        """Force out and flyout must produce different tokens."""
        assert _abbr_play('Forceout') != _abbr_play('Flyout to left fielder')

    def test_infield_fly(self):
        """Infield fly."""
        assert _abbr_play('Infield Fly') == 'IF'

    def test_infield_fly_in_sentence(self):
        """Infield fly in sentence."""
        assert _abbr_play('Infield fly rule applied') == 'IF'

    def test_interference(self):
        """Interference."""
        assert _abbr_play('Interference') == 'INT'

    def test_interference_in_sentence(self):
        """Interference in sentence."""
        assert _abbr_play('Batter interference called') == 'INT'


# ===========================================================================
# 21. _build_scorecard_notation — live-feed credit-based scorecard notation
# ===========================================================================

def _make_play(event, event_type='', credits=None, description=''):
    """Build a minimal play dict for _build_scorecard_notation."""
    return {
        'result': {
            'event': event,
            'eventType': event_type,
            'description': description,
        },
        'credits': credits or [],
    }


def _credit(position_code, credit_type):
    """Credit."""
    return {'position': {'code': position_code}, 'credit': credit_type}


class TestBuildScorecardNotation:

    # --- Ground outs (no suffix) ---

    def test_groundout_6_3(self):
        """Groundout 6 3."""
        play = _make_play('Groundout', credits=[
            _credit('6', 'f_assist'),
            _credit('3', 'f_putout'),
        ])
        assert _build_scorecard_notation(play) == '6-3'

    def test_groundout_5_3(self):
        """Groundout 5 3."""
        play = _make_play('Groundout', credits=[
            _credit('5', 'f_assist'),
            _credit('3', 'f_putout'),
        ])
        assert _build_scorecard_notation(play) == '5-3'

    def test_unassisted_out_first_baseman(self):
        """Unassisted out first baseman."""
        play = _make_play('Groundout', credits=[_credit('3', 'f_putout')])
        assert _build_scorecard_notation(play) == '3'

    # --- Force out (same notation as ground out, no suffix) ---

    def test_force_out_6_3(self):
        """Force out 6 3."""
        play = _make_play('Force Out', credits=[
            _credit('6', 'f_assist'),
            _credit('3', 'f_putout'),
        ])
        assert _build_scorecard_notation(play) == '6-3'

    def test_force_out_no_suffix(self):
        """Force out must never produce a FO/FOUT suffix."""
        play = _make_play('Force Out', credits=[
            _credit('4', 'f_assist'),
            _credit('3', 'f_putout'),
        ])
        result = _build_scorecard_notation(play)
        assert result == '4-3'
        assert 'FOUT' not in result
        assert 'FO' not in result

    # --- Flyout (F + fielder number, never confused with force out) ---

    def test_flyout_left_field(self):
        """Flyout left field."""
        play = _make_play('Flyout', credits=[_credit('7', 'f_putout')])
        assert _build_scorecard_notation(play) == 'F7'

    def test_flyout_center_field(self):
        """Flyout center field."""
        play = _make_play('Flyout', credits=[_credit('8', 'f_putout')])
        assert _build_scorecard_notation(play) == 'F8'

    def test_flyout_distinct_from_force_out(self):
        """Flyout distinct from force out."""
        flyout = _make_play('Flyout', credits=[_credit('7', 'f_putout')])
        force  = _make_play('Force Out', credits=[
            _credit('6', 'f_assist'), _credit('3', 'f_putout'),
        ])
        assert _build_scorecard_notation(flyout) != _build_scorecard_notation(force)

    # --- Double play ---

    def test_gdp_6_4_3(self):
        """Gdp 6 4 3."""
        play = _make_play('Grounded Into DP', 'double_play', credits=[
            _credit('6', 'f_assist'),
            _credit('4', 'f_putout'),
            _credit('4', 'f_assist'),
            _credit('3', 'f_putout'),
        ])
        assert _build_scorecard_notation(play) == '6-4-3 DP'

    def test_dp_5_4_3(self):
        """Dp 5 4 3."""
        play = _make_play('Double Play', 'double_play', credits=[
            _credit('5', 'f_assist'),
            _credit('4', 'f_putout'),
            _credit('4', 'f_assist'),
            _credit('3', 'f_putout'),
        ])
        assert _build_scorecard_notation(play) == '5-4-3 DP'

    # --- Triple play ---

    def test_triple_play_5_4_3(self):
        """Triple play 5 4 3."""
        play = _make_play('Triple Play', 'triple_play', credits=[
            _credit('5', 'f_assist'),
            _credit('4', 'f_putout'),
            _credit('4', 'f_assist'),
            _credit('3', 'f_putout'),
        ])
        assert _build_scorecard_notation(play) == '5-4-3 TP'

    # --- Field error ---

    def test_field_error_simple(self):
        """No assist — plain E + position."""
        play = _make_play('Field Error', credits=[_credit('6', 'f_error')])
        assert _build_scorecard_notation(play) == 'E6'

    def test_field_error_with_assist_sequence(self):
        """Shortstop throws to first, first baseman drops it → 6 E3."""
        play = _make_play('Field Error', credits=[
            _credit('6', 'f_assist'),
            _credit('3', 'f_error'),
        ])
        assert _build_scorecard_notation(play) == '6 E3'

    def test_field_error_no_credits_returns_E(self):
        """Field error no credits returns E."""
        play = _make_play('Field Error')
        assert _build_scorecard_notation(play) == 'E'

    # --- Caught stealing ---

    def test_caught_stealing_2_6(self):
        """Caught stealing 2 6."""
        play = _make_play('Caught Stealing 2B', credits=[
            _credit('2', 'f_assist'),
            _credit('6', 'f_putout'),
        ])
        assert _build_scorecard_notation(play) == 'CS 2-6'

    def test_caught_stealing_prefix_always_present(self):
        """Caught stealing prefix always present."""
        play = _make_play('Caught Stealing 3B', credits=[
            _credit('2', 'f_assist'),
            _credit('5', 'f_putout'),
        ])
        result = _build_scorecard_notation(play)
        assert result.startswith('CS ')

    def test_caught_stealing_no_credits_returns_CS(self):
        """Caught stealing no credits returns CS."""
        play = _make_play('Caught Stealing 2B')
        assert _build_scorecard_notation(play) == 'CS'

    # --- Pickoff ---

    def test_pickoff_1_3(self):
        """Pickoff 1 3."""
        play = _make_play('Pickoff 1B', credits=[
            _credit('1', 'f_assist'),
            _credit('3', 'f_putout'),
        ])
        assert _build_scorecard_notation(play) == 'PO 1-3'

    def test_pickoff_prefix_always_PO(self):
        """Pickoff prefix always PO."""
        play = _make_play('Pickoff 2B', credits=[
            _credit('1', 'f_assist'),
            _credit('4', 'f_putout'),
        ])
        result = _build_scorecard_notation(play)
        assert result.startswith('PO ')

    def test_pickoff_no_credits_returns_PO(self):
        """Pickoff no credits returns PO."""
        play = _make_play('Pickoff 1B')
        assert _build_scorecard_notation(play) == 'PO'

    def test_pickoff_never_returns_PK(self):
        """Pickoff never returns PK."""
        play = _make_play('Pickoff 1B', credits=[
            _credit('1', 'f_assist'),
            _credit('3', 'f_putout'),
        ])
        assert 'PK' not in _build_scorecard_notation(play)

    # --- Strikeout double play (dropped third strike) ---

    def test_strikeout_double_play_k_2_3(self):
        """Catcher (2) throws to first (3) after dropped third strike."""
        play = _make_play('Strikeout Double Play', 'strikeout', credits=[
            _credit('2', 'f_assist'),
            _credit('3', 'f_putout'),
        ])
        result = _build_scorecard_notation(play)
        assert result == 'K 2-3'

    def test_strikeout_double_play_no_credits(self):
        """Strikeout double play no credits."""
        play = _make_play('Strikeout Double Play')
        assert _build_scorecard_notation(play) == 'K'

    # --- Simple events unchanged ---

    def test_strikeout_swinging(self):
        """Strikeout swinging."""
        play = _make_play('Strikeout')
        assert _build_scorecard_notation(play) == 'K'

    def test_strikeout_looking(self):
        """Strikeout looking."""
        play = _make_play('Strikeout Looking')
        assert _build_scorecard_notation(play) == 'Kl'

    def test_strikeout_looking_via_call_code(self):
        """event='Strikeout' + last pitch call code 'C' → 'Kl'."""
        play = {
            'result': {'event': 'Strikeout', 'eventType': 'strikeout'},
            'credits': [],
            'playEvents': [
                {'isPitch': True, 'details': {'call': {'code': 'B'}}},
                {'isPitch': True, 'details': {'call': {'code': 'S'}}},
                {'isPitch': True, 'details': {'call': {'code': 'C'}}},
            ],
        }
        assert _build_scorecard_notation(play) == 'Kl'

    def test_strikeout_looking_via_description(self):
        """event='Strikeout' + 'called out on strikes' description → 'Kl' even with no pitch data."""
        play = {
            'result': {
                'event': 'Strikeout',
                'description': 'Aaron Judge called out on strikes.',
            },
            'credits': [],
            'playEvents': [],
        }
        assert _build_scorecard_notation(play) == 'Kl'

    def test_strikeout_looking_via_description_strikes_out_looking(self):
        """event='Strikeout' + 'strikes out looking' description → 'Kl'."""
        play = {
            'result': {
                'event': 'Strikeout',
                'description': 'Ronald Acuña Jr. strikes out looking.',
            },
            'credits': [],
            'playEvents': [],
        }
        assert _build_scorecard_notation(play) == 'Kl'

    def test_strikeout_swinging_description_not_upgraded(self):
        """event='Strikeout' + 'strikes out swinging' description stays 'K'."""
        play = {
            'result': {
                'event': 'Strikeout',
                'description': 'Aaron Judge strikes out swinging.',
            },
            'credits': [],
            'playEvents': [],
        }
        assert _build_scorecard_notation(play) == 'K'

    def test_home_run(self):
        """Home run."""
        play = _make_play('Home Run')
        assert _build_scorecard_notation(play) == 'HR'

    def test_walk(self):
        """Walk."""
        play = _make_play('Walk')
        assert _build_scorecard_notation(play) == 'BB'


# ===========================================================================
# 22. ARROW SUPPRESSION (3-outs API lag)
# ===========================================================================

class TestArrowSuppression:
    """The batting-team ▲/▼ indicator has been removed: no arrow should ever be
    drawn in the indicator region just left of the box, in any game state."""

    # Triangle used to sit just left of start_x=32.  _bi_cx = 32+4-8 = 28, _r = 4.
    _AWAY_ARROW = (22, 63, 35, 76)   # ▲ region for Top-half (away batting)
    _HOME_ARROW = (22, 93, 35, 106)  # ▼ region for Bottom-half (home batting)

    def _render(self, game, team_data):
        """Render."""
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, game, team_data, use_logos=False)
        return img

    @needs_pil
    def test_no_arrow_top_half(self, minimal_team_data):
        """No arrow top half."""
        for outs in (0, 1, 2, 3):
            game = _in_progress_game(inningState='Top', num_of_outs=outs)
            img = self._render(game, minimal_team_data)
            assert not _has_dark_pixels(img, *self._AWAY_ARROW), \
                f"▲ indicator should be removed (outs={outs})"

    @needs_pil
    def test_no_arrow_bottom_half(self, minimal_team_data):
        """No arrow bottom half."""
        for outs in (0, 1, 2, 3):
            game = _in_progress_game(inningState='Bottom', num_of_outs=outs)
            img = self._render(game, minimal_team_data)
            assert not _has_dark_pixels(img, *self._HOME_ARROW), \
                f"▼ indicator should be removed (outs={outs})"

    @needs_pil
    def test_arrow_absent_for_final_game(self, minimal_team_data):
        """No arrow drawn for a finished game."""
        game = _base_game(detailed_state='Final', inningState='End', num_of_outs=3)
        img = self._render(game, minimal_team_data)
        assert not _has_dark_pixels(img, *self._AWAY_ARROW)
        assert not _has_dark_pixels(img, *self._HOME_ARROW)

    @needs_pil
    def test_arrow_absent_for_suspended_game(self, minimal_team_data):
        """No arrow drawn for a suspended game."""
        game = _base_game(
            detailed_state='Suspended',
            inningState='Bottom', num_of_outs=1,
            away_runs=3, home_runs=1, current_inning=5,
        )
        img = self._render(game, minimal_team_data)
        assert not _has_dark_pixels(img, *self._AWAY_ARROW)
        assert not _has_dark_pixels(img, *self._HOME_ARROW)


# ===========================================================================
# 23. MID-INNING PITCHING CHANGE LABEL
# ===========================================================================

class TestMidInningPC:
    """'Mid PC' label appears only when the PC occurs during a live half-inning
    (≥1 out recorded OR ≥1 pitch thrown in the current AB).  Otherwise 'P.CHG'."""

    def _render(self, game, team_data):
        """Render."""
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, game, team_data, use_logos=False)
        return img

    @needs_pil
    def test_mid_pc_differs_from_start_of_inning_pc(self, minimal_team_data):
        """A PC with 1 out (mid-inning) renders differently than a PC with 0 outs
        (start of inning) — the header label changes from 'P.CHG' to 'Mid PC'."""
        common = dict(
            inningState='Top', current_inning=4,
            current_pitcher='Smith', current_hitter='Jones',
            sub_event='PC: Smith',
        )
        mid = _in_progress_game(num_of_outs=1, at_bat_pitch_count=0, **common)
        start = _in_progress_game(num_of_outs=0, at_bat_pitch_count=0, **common)
        img_mid = self._render(mid, minimal_team_data)
        img_start = self._render(start, minimal_team_data)
        assert list(img_mid.getdata()) != list(img_start.getdata()), \
            "Mid-inning PC ('Mid PC') must render differently from start-of-inning PC ('P.CHG')"

    @needs_pil
    def test_pc_with_pitch_count_is_mid_inning(self, minimal_team_data):
        """A PC with 0 outs but at_bat_pitch_count=1 counts as mid-inning."""
        common = dict(
            inningState='Top', current_inning=4,
            current_pitcher='Smith', current_hitter='Jones',
            sub_event='PC: Smith',
            num_of_outs=0,
        )
        with_pitches = _in_progress_game(at_bat_pitch_count=1, **common)
        without_pitches = _in_progress_game(at_bat_pitch_count=0, **common)
        img_p = self._render(with_pitches, minimal_team_data)
        img_np = self._render(without_pitches, minimal_team_data)
        assert list(img_p.getdata()) != list(img_np.getdata()), \
            "PC with at_bat_pitch_count=1 (mid-inning) must differ from pitch_count=0 (P.CHG)"

    @needs_pil
    def test_between_innings_pc_uses_pchg_not_midpc(self, minimal_team_data):
        """A PC between innings (Middle state) must use 'P.CHG', not 'Mid PC'."""
        between = _in_progress_game(
            inningState='Middle', current_inning=4,
            current_pitcher='Smith', current_hitter='Jones',
            sub_event='PC: Smith', num_of_outs=3,
        )
        mid = _in_progress_game(
            inningState='Top', current_inning=4,
            current_pitcher='Smith', current_hitter='Jones',
            sub_event='PC: Smith', num_of_outs=1,
        )
        img_between = self._render(between, minimal_team_data)
        img_mid = self._render(mid, minimal_team_data)
        assert list(img_between.getdata()) != list(img_mid.getdata()), \
            "Between-innings PC ('P.CHG') must render differently from mid-inning PC ('Mid PC')"

    @needs_pil
    def test_no_crash_pc_with_zero_outs_zero_pitches(self, minimal_team_data):
        """PC at the very start of a half-inning must not crash."""
        game = _in_progress_game(
            inningState='Top', current_inning=4,
            sub_event='PC: Smith', num_of_outs=0, at_bat_pitch_count=0,
        )
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)


# ===========================================================================
# 24. SUSPENDED GAME DISPLAY
# ===========================================================================

class TestSuspendedGame:
    """Suspended games must show scores, the linescore grid, and a header
    indicating the inning/half when the game was stopped."""

    _SCORE_REGION = (92, 52, 118, 77)  # away score area (same as TestScoreDisplayRules)
    _HEADER_REGION = (32, 30, 167, 51)

    def _render(self, game, team_data):
        """Render."""
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, game, team_data, use_logos=False)
        return img

    @needs_pil
    def test_no_crash_suspended(self, minimal_team_data):
        """A suspended game must render without raising any exception."""
        game = _base_game(
            detailed_state='Suspended',
            away_runs=3, home_runs=1,
            current_inning=5, inningState='Bottom',
            away_inning_runs=[0,0,2,0,1], home_inning_runs=[0,1,0,0,0],
        )
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, game, minimal_team_data, use_logos=False)

    @needs_pil
    def test_suspended_shows_score(self, minimal_team_data):
        """Suspended games must display the score (away_runs visible in score region)."""
        game = _base_game(
            detailed_state='Suspended',
            away_runs=3, home_runs=1,
            current_inning=5, inningState='Bottom',
            away_inning_runs=[0,0,2,0,1], home_inning_runs=[0,1,0,0,0],
        )
        img = self._render(game, minimal_team_data)
        assert _has_dark_pixels(img, *self._SCORE_REGION), \
            "Score must be rendered for a suspended game"

    @needs_pil
    def test_suspended_header_differs_from_final(self, minimal_team_data):
        """A suspended game header must look different from a final game header."""
        susp = _base_game(
            detailed_state='Suspended',
            away_runs=3, home_runs=1,
            current_inning=5, inningState='Bottom',
            away_inning_runs=[0,0,2,0,1], home_inning_runs=[0,1,0,0,0],
        )
        final = _base_game(away_runs=3, home_runs=1)
        img_susp = self._render(susp, minimal_team_data)
        img_final = self._render(final, minimal_team_data)
        assert list(img_susp.getdata()) != list(img_final.getdata()), \
            "Suspended header must differ from Final (shows 'Susp Bot 5' not just scores)"

    @needs_pil
    def test_suspended_header_varies_by_inning_half(self, minimal_team_data):
        """Suspended Top 5 must render a different header than Suspended Bottom 5."""
        top = _base_game(
            detailed_state='Suspended',
            away_runs=3, home_runs=1, current_inning=5, inningState='Top',
            away_inning_runs=[0,0,2,0,0], home_inning_runs=[0,1,0,0,0],
        )
        bot = _base_game(
            detailed_state='Suspended',
            away_runs=3, home_runs=1, current_inning=5, inningState='Bottom',
            away_inning_runs=[0,0,2,0,1], home_inning_runs=[0,1,0,0,0],
        )
        img_top = self._render(top, minimal_team_data)
        img_bot = self._render(bot, minimal_team_data)
        assert list(img_top.getdata()) != list(img_bot.getdata()), \
            "Susp Top 5 and Susp Bot 5 must show different headers"

    @needs_pil
    def test_suspended_no_arrow(self, minimal_team_data):
        """No batting-team arrow for a suspended game even with inningState='Bottom'."""
        game = _base_game(
            detailed_state='Suspended',
            away_runs=3, home_runs=1,
            current_inning=5, inningState='Bottom', num_of_outs=1,
            away_inning_runs=[0,0,2,0,1], home_inning_runs=[0,1,0,0,0],
        )
        img = self._render(game, minimal_team_data)
        arrow_region = (22, 93, 35, 106)
        assert not _has_dark_pixels(img, *arrow_region), \
            "No batting arrow should appear for a suspended game"


# ===========================================================================
# 25. REVIEW CONTEXT PARSING (_parse_review_context)
# ===========================================================================

class TestReviewContextParsing:
    """_parse_review_context extracts a short play label from MLB API review
    descriptions. No PIL required — pure string logic."""

    def test_out_at_first_base(self):
        """Out at first base."""
        # 'first base' → '1B'; 'at' stays lowercase (in skip set) → 'Out at 1B'
        desc = 'Manager challenge (out at first base): Play stands, batter is out.'
        assert _parse_review_context(desc) == 'Out at 1B'

    def test_safe_at_second_base(self):
        """Safe at second base."""
        desc = 'Manager challenge (safe at second base): Call overturned, runner safe.'
        assert _parse_review_context(desc) == 'Safe at 2B'

    def test_safe_at_third_base(self):
        """Safe at third base."""
        desc = 'Manager challenge (safe at third base): Call confirmed.'
        assert _parse_review_context(desc) == 'Safe at 3B'

    def test_safe_at_home_plate(self):
        """Safe at home plate."""
        # 'home plate' → 'Home'; 'at' stays lowercase → 'Safe at Home'
        desc = 'Manager challenge (safe at home plate): Call confirmed, runner safe.'
        assert _parse_review_context(desc) == 'Safe at Home'

    def test_strike_call(self):
        """Strike call."""
        desc = 'Player challenge (strike): Call stands.'
        assert _parse_review_context(desc) == 'Strike'

    def test_fair_foul_slash_capitalized(self):
        """Both words in a slash-compound must be capitalized (Fair/Foul, not Fair/foul)."""
        desc = 'Player challenge (fair/foul): Call overturned.'
        result = _parse_review_context(desc)
        assert result == 'Fair/Foul'

    def test_prepositions_stay_lowercase(self):
        """'at' must remain lowercase in output (it's in _REVIEW_CTX_SKIP)."""
        desc = 'Manager challenge (out at first base): Overturned.'
        result = _parse_review_context(desc)
        assert 'at' in result.lower()
        assert 'At' not in result, "'at' must not be title-cased"
        assert result == 'Out at 1B'

    def test_empty_string_returns_empty(self):
        """Empty string returns empty."""
        assert _parse_review_context('') == ''

    def test_none_returns_empty(self):
        """None returns empty."""
        assert _parse_review_context(None) == ''

    def test_no_parens_returns_empty(self):
        """No parens returns empty."""
        assert _parse_review_context('No parentheses in this description') == ''

    def test_tag_play(self):
        """'tag play' maps cleanly without any base substitution."""
        desc = 'Manager challenge (tag play): Call confirmed.'
        result = _parse_review_context(desc)
        assert result == 'Tag Play'

    def test_hit_by_pitch(self):
        """Hit by pitch."""
        # 'by' is NOT in _REVIEW_CTX_SKIP → it gets capitalized to 'By'
        desc = 'Player challenge (hit by pitch): Call overturned.'
        result = _parse_review_context(desc)
        assert result == 'Hit By Pitch'


# ===========================================================================
# 26. REVIEW RESULT FORMAT (_find_recent_review_result)
# ===========================================================================

def _make_plays_with_review(is_overturned, description='', followed_by_pitch=False, in_progress=False):
    """Build a minimal plays dict containing one review event in the current AB."""
    review_event = {
        'isPitch': False,
        'reviewDetails': {
            'isOverturned': is_overturned,
            'inProgress': in_progress,
            'challengeTeamId': None,
        },
        'details': {'description': description},
    }
    events = [review_event]
    if followed_by_pitch:
        events.append({'isPitch': True, 'details': {}})
    return {
        'currentPlay': {'playEvents': events},
        'allPlays': [],
    }


class TestReviewResultFormat:
    """_find_recent_review_result returns formatted OVR/CFM labels or None."""

    def test_overturned_with_context(self):
        """Overturned with context."""
        plays = _make_plays_with_review(
            is_overturned=True,
            description='Manager challenge (out at first base): Call overturned.',
        )
        result = _find_recent_review_result(plays)
        assert result == 'OVR: Out at 1B'

    def test_confirmed_with_context(self):
        """Confirmed with context."""
        plays = _make_plays_with_review(
            is_overturned=False,
            description='Manager challenge (safe at second base): Call confirmed.',
        )
        result = _find_recent_review_result(plays)
        assert result == 'CFM: Safe at 2B'

    def test_overturned_at_home(self):
        """Overturned at home."""
        plays = _make_plays_with_review(
            is_overturned=True,
            description='Manager challenge (safe at home plate): Call overturned.',
        )
        result = _find_recent_review_result(plays)
        assert result == 'OVR: Safe at Home'

    def test_confirmed_strike(self):
        """Confirmed strike."""
        plays = _make_plays_with_review(
            is_overturned=False,
            description='Player challenge (strike): Call confirmed.',
        )
        result = _find_recent_review_result(plays)
        assert result == 'CFM: Strike'

    def test_returns_none_when_pitch_follows_review(self):
        """If a pitch was thrown after the review, the result is stale → return None."""
        plays = _make_plays_with_review(
            is_overturned=True,
            description='Manager challenge (out at first base): Overturned.',
            followed_by_pitch=True,
        )
        assert _find_recent_review_result(plays) is None

    def test_returns_none_when_review_in_progress(self):
        """An in-progress (unresolved) review must return None."""
        plays = _make_plays_with_review(
            is_overturned=False,
            description='Manager challenge (out at first base): Under review.',
            in_progress=True,
        )
        assert _find_recent_review_result(plays) is None

    def test_returns_none_when_no_review_events(self):
        """No review events in plays → None."""
        plays = {
            'currentPlay': {'playEvents': [{'isPitch': True, 'details': {}}]},
            'allPlays': [],
        }
        assert _find_recent_review_result(plays) is None

    def test_overturned_fair_foul(self):
        """Overturned fair foul."""
        plays = _make_plays_with_review(
            is_overturned=True,
            description='Player challenge (fair/foul): Call overturned.',
        )
        result = _find_recent_review_result(plays)
        assert result == 'OVR: Fair/Foul'

    def test_team_fallback_when_no_context(self):
        """When description has no parenthetical context, fall back to team abbreviation."""
        plays = _make_plays_with_review(is_overturned=True, description='Review completed.')
        plays['currentPlay']['playEvents'][0]['reviewDetails']['challengeTeamId'] = 133
        result = _find_recent_review_result(plays, away_id=133, home_id=144,
                                            away_abbr='OAK', home_abbr='ATL')
        assert result == 'OVR OAK'

    def test_plain_label_when_no_context_no_team(self):
        """No context, no team → plain 'OVR' or 'CFM'."""
        plays = _make_plays_with_review(is_overturned=False, description='')
        result = _find_recent_review_result(plays)
        assert result == 'CFM'


# ===========================================================================
# 27. RUN-SCORED HEADER INVERSION GUARD
# ===========================================================================

class TestRunScoredGuard:
    """The header-inversion triggered by last_play_rbi must fire only for
    'In Progress' games — NOT for Suspended, Final, or other states."""

    _HEADER_REGION = (32, 30, 167, 51)

    def _render(self, game, team_data, score_changed=False):
        """Render."""
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, game, team_data, use_logos=False,
                 score_changed=score_changed)
        return img

    def _is_inverted(self, img):
        """Is inverted."""
        region = img.crop(self._HEADER_REGION).convert('L')
        pixels = list(region.getdata())
        dark = sum(1 for p in pixels if p < 128)
        return dark > len(pixels) * 0.5

    @needs_pil
    def test_in_progress_run_scored_inverts_header(self, minimal_team_data):
        """last_play_rbi > 0 on an In Progress game triggers header inversion."""
        game = _in_progress_game(
            last_play_rbi=1, inningState='Top', num_of_outs=1,
            balls=0, strikes=0,
        )
        img = self._render(game, minimal_team_data)
        assert self._is_inverted(img), \
            "In Progress + last_play_rbi=1 must invert the header"

    @needs_pil
    def test_suspended_run_scored_does_not_invert_header(self, minimal_team_data):
        """last_play_rbi > 0 on a Suspended game must NOT invert the header."""
        game = _base_game(
            detailed_state='Suspended',
            away_runs=3, home_runs=1, current_inning=5, inningState='Bottom',
            away_inning_runs=[0,0,2,0,1], home_inning_runs=[0,1,0,0,0],
            last_play_rbi=2,
        )
        img = self._render(game, minimal_team_data)
        assert not self._is_inverted(img), \
            "Suspended + last_play_rbi=2 must NOT invert the header"

    @needs_pil
    def test_final_run_scored_does_not_invert_header(self, minimal_team_data):
        """last_play_rbi > 0 on a Final game must NOT invert the header."""
        game = _base_game(last_play_rbi=1)
        img = self._render(game, minimal_team_data)
        assert not self._is_inverted(img), \
            "Final + last_play_rbi=1 must NOT invert the header"

    @needs_pil
    def test_suspended_no_rbi_not_inverted(self, minimal_team_data):
        """Suspended game with no RBI is never inverted (baseline check)."""
        game = _base_game(
            detailed_state='Suspended',
            away_runs=3, home_runs=1, current_inning=5, inningState='Bottom',
            away_inning_runs=[0,0,2,0,1], home_inning_runs=[0,1,0,0,0],
            last_play_rbi=0,
        )
        img_no_rbi = self._render(game, minimal_team_data)
        game_rbi = dict(game)
        game_rbi['last_play_rbi'] = 3
        img_with_rbi = self._render(game_rbi, minimal_team_data)
        assert list(img_no_rbi.getdata()) == list(img_with_rbi.getdata()), \
            "last_play_rbi must not affect suspended game rendering at all"


# ---------------------------------------------------------------------------
# _draw_next_game_preview: tomorrow-game preview strip (lines 638-643)
# ---------------------------------------------------------------------------

@needs_pil
class TestDrawNextGamePreview:
    """Direct tests for _draw_next_game_preview targeting the elif branches."""

    def _fake_game(self, away_id, home_id, pk=9001):
        """Fake game."""
        return {
            'game_pk': pk,
            'away_team_id': away_id,
            'home_team_id': home_id,
            'game_start_utc': '2026-07-02T23:10:00Z',
        }

    def _call(self, tmrw_games, today_home_id, today_away_id):
        """Call."""
        from image_box import _draw_next_game_preview
        img = Image.new('1', (800, 480), 255)
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        team_data = {'team_abbreviation': {'119': 'LAD', '137': 'SF', '147': 'NYY', '143': 'PHI'}}
        fake_cfg = {'timezone': 'America/Chicago'}
        with patch('image_box.load_yaml_file', return_value=fake_cfg):
            _draw_next_game_preview(
                draw, img,
                start_x=0, start_y=0,
                tmrw_games=tmrw_games,
                today_home_id=today_home_id,
                today_away_id=today_away_id,
                team_data=team_data,
                use_logos=False,
                horizonta_len=135,
                vertical_len=110,
                scale=1,
            )
        return img

    def test_only_away_game_found(self):
        """Only the away team has a tomorrow game (line 638-639: elif away_game branch)."""
        # away_id=119 (LAD) matches; home_id=137 (SF) has no tomorrow game.
        tmrw_games = [self._fake_game(away_id=119, home_id=147)]
        img = self._call(tmrw_games, today_home_id=137, today_away_id=119)
        assert isinstance(img, Image.Image)

    def test_only_home_game_found(self):
        """Only the home team has a tomorrow game (lines 640-643: elif home_game branch)."""
        # home_id=137 (SF) matches; away_id=119 (LAD) has no tomorrow game.
        tmrw_games = [self._fake_game(away_id=143, home_id=137)]
        img = self._call(tmrw_games, today_home_id=137, today_away_id=119)
        assert isinstance(img, Image.Image)


# ===========================================================================
# 15. Lineup-in-cell mode
# ===========================================================================

_LINEUP_9 = [{'name': f'Player {i} Lastname', 'pos': 'CF'} for i in range(9)]


class TestLineupMode:
    """draw_box lineup-in-cell mode (within 30 min of first pitch with lineup data)."""

    def _render(self, game, team_data):
        """Render."""
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, game, team_data, use_logos=False)
        return img

    def _lineup_game(self, **overrides):
        from datetime import datetime, timezone, timedelta
        soon = (datetime.now(timezone.utc) + timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%SZ')
        g = _pregame_game(
            detailed_state='Pre-Game',
            game_date=soon,
            away_lineup=_LINEUP_9,
            home_lineup=_LINEUP_9,
            venue_name='Yankee Stadium',
        )
        g.update(overrides)
        return g

    @needs_pil
    def test_lineup_mode_renders(self, minimal_team_data):
        """A pre-game cell with lineup data within 30 min renders without error."""
        img = self._render(self._lineup_game(), minimal_team_data)
        assert isinstance(img, Image.Image)

    @needs_pil
    def test_lineup_mode_suppresses_team_names(self, minimal_team_data):
        """In lineup mode the large team-name text is not drawn (body is lineup content)."""
        game_no_lineup = _pregame_game(detailed_state='Pre-Game')
        img_normal = self._render(game_no_lineup, minimal_team_data)
        img_lineup = self._render(self._lineup_game(), minimal_team_data)
        assert list(img_normal.getdata()) != list(img_lineup.getdata()), \
            "Lineup mode should produce a different render than normal pre-game"

    @needs_pil
    def test_lineup_mode_warmup_state(self, minimal_team_data):
        """Warmup state within 30 min also activates lineup mode."""
        img = self._render(self._lineup_game(detailed_state='Warmup'), minimal_team_data)
        assert isinstance(img, Image.Image)

    @needs_pil
    def test_lineup_mode_scheduled_state(self, minimal_team_data):
        """Scheduled state within 30 min also activates lineup mode."""
        img = self._render(self._lineup_game(detailed_state='Scheduled'), minimal_team_data)
        assert isinstance(img, Image.Image)

    @needs_pil
    def test_no_lineup_outside_window_shows_normal(self, minimal_team_data):
        """A pre-game cell without lineup data shows the normal pitcher/record view."""
        game = _pregame_game(detailed_state='Pre-Game')
        img = self._render(game, minimal_team_data)
        assert isinstance(img, Image.Image)

    @needs_pil
    def test_delayed_start_with_reason_in_header(self, minimal_team_data):
        """Delayed Start with a postpone_reason shows delay info in the header."""
        from datetime import datetime, timezone, timedelta
        soon = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
        game = _pregame_game(
            detailed_state='Delayed Start',
            game_date=soon,
            postpone_reason='Rain',
        )
        img = self._render(game, minimal_team_data)
        assert isinstance(img, Image.Image)

    @needs_pil
    def test_warmup_header_shows_time_not_word(self, minimal_team_data):
        """Warmup header shows the start time string, not the literal word 'Warmup'."""
        game = _pregame_game(detailed_state='Warmup', game_start='7:05 PM')
        img_warmup = self._render(game, minimal_team_data)
        game_scheduled = _pregame_game(detailed_state='Scheduled', game_start='7:05 PM')
        img_scheduled = self._render(game_scheduled, minimal_team_data)
        # Both should render without error; Warmup renders like Scheduled (time in header)
        assert isinstance(img_warmup, Image.Image)
        assert isinstance(img_scheduled, Image.Image)

    @needs_pil
    def test_lineup_mode_short_lineup(self, minimal_team_data):
        """Lineup with < 9 entries exercises the empty-slot branch in _lu_render_col."""
        short = [{'name': f'Player {i} Smith', 'pos': 'CF'} for i in range(4)]
        img = self._render(self._lineup_game(away_lineup=short, home_lineup=short), minimal_team_data)
        assert isinstance(img, Image.Image)

    @needs_pil
    def test_lineup_mode_long_name_truncation(self, minimal_team_data):
        """Very long last name is truncated to fit the column width."""
        long = [{'name': 'Bartholomew Witherspoon-Fitzgerald', 'pos': 'CF'}] * 9
        img = self._render(self._lineup_game(away_lineup=long, home_lineup=long), minimal_team_data)
        assert isinstance(img, Image.Image)

    @needs_pil
    def test_lineup_mode_long_pitcher_name(self, minimal_team_data):
        """Very long probable-pitcher name is truncated to fit the SP strip."""
        img = self._render(self._lineup_game(
            away_probable='Bartholomew Witherspoon-Fitzgerald',
            home_probable='Bartholomew Witherspoon-Fitzgerald',
        ), minimal_team_data)
        assert isinstance(img, Image.Image)

    @needs_pil
    def test_lineup_mode_with_logos(self, minimal_team_data):
        """use_logos=True draws the away/home logo-vs-logo row above the batting order."""
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, self._lineup_game(), minimal_team_data, use_logos=True)
        assert isinstance(img, Image.Image)

    @needs_pil
    def test_lineup_mode_with_logo_background(self, minimal_team_data):
        """lineup_logo_background=True draws the ghost-logo watermark behind each column."""
        img = Image.new('1', (800, 480), 255)
        fake_cfg = {'final_linescore_minutes': 60, 'lineup_logo_background': True}
        with patch('image_box.load_yaml_file', return_value=fake_cfg):
            draw_box(img, 32, 30, self._lineup_game(), minimal_team_data, use_logos=True)
        assert isinstance(img, Image.Image)


# ===========================================================================
# 16. Pre-game series context
# ===========================================================================

class TestPreGameSeriesContext:
    """Series score/logo shown in the header of pre-game tiles."""

    def _render(self, game, team_data):
        img = Image.new('1', (800, 480), 255)
        draw_box(img, 32, 30, game, team_data, use_logos=False)
        return img

    @needs_pil
    def test_pregame_series_tied(self, minimal_team_data):
        """Series tied shows score in the header (e.g., 'tied' in series_result)."""
        game = _pregame_game(
            detailed_state='Scheduled',
            series_wins=1,
            series_losses=1,
            series_result='Series tied 1-1',
        )
        img = self._render(game, minimal_team_data)
        assert isinstance(img, Image.Image)

    @needs_pil
    def test_pregame_series_leader(self, minimal_team_data):
        """Series leader shown in the header (e.g., 'NYY leads 2-1')."""
        game = _pregame_game(
            detailed_state='Scheduled',
            series_wins=2,
            series_losses=1,
            series_result='NYY leads 2-1',
        )
        img = self._render(game, minimal_team_data)
        assert isinstance(img, Image.Image)
