"""Regression tests for bugs found in the whole-repo audit.

Each class pins one specific defect so it can't silently come back.
"""
import os
import sys
from unittest.mock import patch

import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from image_utils import division_rank  # noqa: E402
from image_magic import draw_magic_cell  # noqa: E402
from image_box import _draw_win_probability_bar, _draw_game_end_time  # noqa: E402
from image_standings import (  # noqa: E402
    draw_standings_sidebar, draw_standings_sidebar_fullscreen,
)


def _team(team_id, rank=None, wins=10, losses=5):
    """A standings row shaped exactly like standings.py persists it."""
    return {
        'team_id': team_id,
        'team_name': f'Team {team_id}',
        'divisionRank': rank,
        'league_record_wins': wins,
        'league_record_losses': losses,
        'games_back': '-',
        'clinch_indicator': '',
    }


def _standings(*ranks):
    return {
        'standings': {
            'American League East': [
                _team(tid, rank) for tid, rank in zip((147, 111), ranks)
            ],
        },
        'team_abbreviation': {'147': 'NYY', '111': 'BOS'},
    }


_TEAM_DATA = {'team_abbreviation': {'147': 'NYY', '111': 'BOS'}}


def _final_game_with_end_time():
    """A Final game carrying the API's end timestamp, dated today so the
    linescore window is still open."""
    from datetime import datetime, timedelta, timezone
    ended = datetime.now(timezone.utc) - timedelta(minutes=5)
    return {
        'game_pk': 2001,
        'away_team_id': 147, 'home_team_id': 111,
        'away_team_name': 'NYY', 'home_team_name': 'BOS',
        'detailed_state': 'Final',
        'away_runs': 3, 'home_runs': 5,
        'away_hits': 8, 'home_hits': 10,
        'away_errors': 0, 'home_errors': 1,
        'away_team_is_winner': False, 'home_team_is_winner': True,
        'current_inning': 9, 'inningState': 'End',
        'away_inning_runs': [0, 1, 0, 0, 0, 2, 0, 0, 0],
        'home_inning_runs': [1, 0, 2, 0, 0, 0, 1, 0, 1],
        'away_team_record_wins': 10, 'away_team_record_losses': 5,
        'home_team_record_wins': 12, 'home_team_record_losses': 3,
        'num_of_outs': 3,
        'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None,
        'game_start': '7:05 PM',
        'no_hitter': False, 'perfect_game': False, 'walk_off': False,
        'game_date': ended.strftime('%Y-%m-%d'),
        'game_end_time_utc': ended.strftime('%Y-%m-%dT%H:%M:%SZ'),
    }


def _render_box(draw_box, game):
    """Render one tile and return its bytes."""
    import image_box
    canvas = Image.new('1', (800, 480), 255)
    image_box.set_historical_mode(True)
    try:
        draw_box(canvas, 32, 30, game, _TEAM_DATA, scale=1)
    finally:
        image_box.set_historical_mode(False)
    return canvas.tobytes()


def _live_wide_game():
    """A live game shaped for the wide tile, carrying win probabilities."""
    return {
        'game_pk': 3001,
        'away_team_id': 147, 'home_team_id': 111,
        'away_team_name': 'NYY', 'home_team_name': 'BOS',
        'detailed_state': 'In Progress', 'inningState': 'Middle',
        'current_inning': 7,
        'away_runs': 4, 'home_runs': 3, 'away_hits': 8, 'home_hits': 6,
        'away_errors': 0, 'home_errors': 1,
        'num_of_outs': 3, 'balls': 0, 'strikes': 0,
        'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None,
        'away_inning_runs': [1, 0, 2, 0, 0, 1, 0],
        'home_inning_runs': [0, 1, 0, 2, 0, 0],
        'away_team_record_wins': 60, 'away_team_record_losses': 40,
        'home_team_record_wins': 55, 'home_team_record_losses': 45,
        'away_win_probability': 62, 'home_win_probability': 38,
        'game_start': '7:05 PM',
        'no_hitter': False, 'perfect_game': False, 'walk_off': False,
        'venue': 'Fenway Park', 'last_play': None,
    }


class TestDivisionRankNone:
    """standings.py always writes the 'divisionRank' key, storing None when the
    MLB Stats API omits a rank. dict.get(key, default) does NOT substitute the
    default for a present-but-None value, so int(...)/str(...) on it blew up or
    rendered a literal 'None'."""

    def test_helper_falls_back_when_value_is_none(self):
        assert division_rank({'divisionRank': None}) == 99
        assert division_rank({'divisionRank': None}, default=3) == 3

    def test_helper_falls_back_when_key_absent(self):
        assert division_rank({}) == 99

    def test_helper_handles_blank_and_unparseable(self):
        assert division_rank({'divisionRank': ''}) == 99
        assert division_rank({'divisionRank': 'N/A'}) == 99
        assert division_rank({'divisionRank': []}) == 99

    def test_helper_handles_missing_team(self):
        assert division_rank(None) == 99

    def test_helper_parses_ints_and_numeric_strings(self):
        assert division_rank({'divisionRank': 2}) == 2
        assert division_rank({'divisionRank': '3'}) == 3

    def test_sidebar_does_not_crash_on_null_rank(self):
        """Previously TypeError: int() argument must be ... not 'NoneType'."""
        draw_standings_sidebar(
            Image.new('1', (800, 480), 255), _standings(None, None), _TEAM_DATA, side='left')

    def test_fullscreen_sidebar_does_not_crash_on_null_rank(self):
        draw_standings_sidebar_fullscreen(
            Image.new('1', (800, 480), 255), _standings(None, None), _TEAM_DATA, side='left')

    def test_magic_cell_does_not_render_literal_none(self):
        """The rank column fell back to str(None) -> a literal 'None.' label.

        With ranks missing, each row falls back to its positional index, so the
        cell must render byte-identically to one with those ranks supplied.
        """
        blank = Image.new('1', (800, 480), 255)
        with_null = draw_magic_cell(
            blank.copy(), 0, 0, _standings(None, None), _TEAM_DATA, 'NYY')
        with_rank = draw_magic_cell(
            blank.copy(), 0, 0, _standings(1, 2), _TEAM_DATA, 'NYY')
        assert with_null.tobytes() == with_rank.tobytes()

    def test_magic_cell_still_uses_real_ranks_when_present(self):
        """Sanity check that the comparison above isn't vacuous."""
        blank = Image.new('1', (800, 480), 255)
        a = draw_magic_cell(blank.copy(), 0, 0, _standings(1, 2), _TEAM_DATA, 'NYY')
        b = draw_magic_cell(blank.copy(), 0, 0, _standings(3, 4), _TEAM_DATA, 'NYY')
        assert a.tobytes() != b.tobytes()


class TestStreaksRefreshGate:
    """The streaks/scoreless panels were gated on _should_refresh_leaders, so a
    successful leaders refresh consumed the shared Finals trigger and streaks
    never refetched (and with the leaders panel off, refetched every poll)."""

    @pytest.fixture()
    def main_mod(self, tmp_path, monkeypatch):
        import main as m
        monkeypatch.setattr(m, '_data_path', lambda f: str(tmp_path / f))
        monkeypatch.setattr(m, '_save_schedule_state', lambda state: None)
        monkeypatch.setattr(
            m, 'load_json_file',
            lambda f: {'games': [{'game_pk': 777, 'detailed_state': 'Final'}]})
        return m

    def test_gates_use_separate_cache_files(self, main_mod, tmp_path):
        (tmp_path / 'leaders.json').write_text('{}')
        # streaks.json missing -> streaks still needs a refresh
        sched = {'leaders_final_pks': ['777'], 'streaks_final_pks': ['777']}
        assert main_mod._should_refresh_leaders(sched) is False
        assert main_mod._should_refresh_streaks(sched) is True

    def test_leaders_refresh_does_not_starve_streaks(self, main_mod, tmp_path):
        """The original bug: 7d records leaders_final_pks, then 7e re-checked the
        same gate and returned False."""
        (tmp_path / 'leaders.json').write_text('{}')
        (tmp_path / 'streaks.json').write_text('{}')
        sched = {}
        assert main_mod._should_refresh_leaders(sched) is True
        main_mod._record_refreshed_finals(sched, 'leaders_final_pks')
        # Streaks keeps its own marker, so the new Final still triggers it.
        assert main_mod._should_refresh_streaks(sched) is True
        main_mod._record_refreshed_finals(sched, 'streaks_final_pks')
        assert main_mod._should_refresh_streaks(sched) is False

    def test_missing_cache_forces_refresh(self, main_mod):
        assert main_mod._should_refresh_streaks({}) is True

    def test_force_bypasses_all_gates(self, main_mod, tmp_path):
        (tmp_path / 'streaks.json').write_text('{}')
        sched = {'streaks_final_pks': ['777']}
        assert main_mod._should_refresh_streaks(sched, force=True) is True


class TestMorningThrottle:
    """With morning_alternate_games disabled, the morning window produced
    showing_previous_day=True but morning_block=None. The poll gate and the
    schedule-state write both keyed on the former, so the block check was a
    no-op, _should_skip_poll never ran, last_game_fetch was never written, and
    every cron tick refetched and repushed the panel."""

    @pytest.fixture()
    def main_mod(self):
        import main as m
        return m

    @staticmethod
    def _args(date=None):
        class _A:
            pass
        a = _A()
        a.date = date
        return a

    def test_alternating_enabled_sets_a_block(self, main_mod, monkeypatch):
        import datetime as _dt

        class _Now(_dt.datetime):
            pass
        monkeypatch.setattr(
            main_mod, '_local_now',
            lambda cfg: _Now(2025, 6, 3, 8, 12, tzinfo=_dt.timezone.utc))
        ctx = main_mod._resolve_target_date(
            self._args(), {'morning_alternate_games': True})
        assert ctx.morning_block is not None
        assert ctx.showing_previous_day is True

    def test_alternating_disabled_has_no_block(self, main_mod, monkeypatch):
        """The regression case: still showing yesterday, but with no block the
        normal smart-polling gate must take over."""
        import datetime as _dt
        monkeypatch.setattr(
            main_mod, '_local_now',
            lambda cfg: _dt.datetime(2025, 6, 3, 8, 12, tzinfo=_dt.timezone.utc))
        ctx = main_mod._resolve_target_date(
            self._args(), {'morning_alternate_games': False})
        assert ctx.morning_block is None
        assert ctx.showing_previous_day is True
        assert ctx.date_str == '2025-06-02'

    def test_after_morning_cutoff_uses_today(self, main_mod, monkeypatch):
        import datetime as _dt
        monkeypatch.setattr(
            main_mod, '_local_now',
            lambda cfg: _dt.datetime(2025, 6, 3, 14, 0, tzinfo=_dt.timezone.utc))
        ctx = main_mod._resolve_target_date(self._args(), {})
        assert ctx.date_str == '2025-06-03'
        assert ctx.showing_previous_day is False
        assert ctx.morning_block is None

    def test_explicit_date_wins(self, main_mod):
        ctx = main_mod._resolve_target_date(self._args('2024-04-01'), {})
        assert ctx.date_str == '2024-04-01'
        assert ctx.morning_block is None
        assert ctx.showing_previous_day is False


class TestLocalTimezone:
    """Date math mixed bare datetime.now() with the configured display timezone.
    On a UTC-clocked Pi with timezone: America/Chicago that rolls over to
    'tomorrow' six hours early."""

    def test_local_now_honours_configured_timezone(self):
        import main as m
        chicago = m._local_now({'timezone': 'America/Chicago'})
        tokyo = m._local_now({'timezone': 'Asia/Tokyo'})
        assert str(chicago.tzinfo) == 'America/Chicago'
        assert str(tokyo.tzinfo) == 'Asia/Tokyo'
        # Same instant, different wall clocks.
        assert abs((chicago - tokyo).total_seconds()) < 5

    def test_local_now_defaults_to_chicago(self):
        import main as m
        assert str(m._local_now({}).tzinfo) == 'America/Chicago'


class TestGameStateNormalization:
    """Unit coverage for the state-normalization and layout-flag logic pulled
    out of the 1600-line draw_box()."""

    @staticmethod
    def _norm(**game):
        from image_box import _normalize_game_state
        return _normalize_game_state(game)

    def test_completed_early_becomes_final(self):
        gd, _, _ = self._norm(detailed_state='Completed Early: Rain')
        assert gd['detailed_state'] == 'Final'

    def test_delayed_start_becomes_pregame(self):
        gd, _, original = self._norm(detailed_state='Delayed Start')
        assert gd['detailed_state'] == 'Pre-Game'
        assert original == 'Delayed Start'

    def test_challenge_normalizes_and_captures_abbr(self):
        gd, abbr, original = self._norm(
            detailed_state='Player challenge', challenge_team_abbr='NYY')
        assert gd['detailed_state'] == 'In Progress'
        assert gd['sub_event'] == 'ABS CHAL'
        assert gd['last_play'] == 'ABS CHAL'
        assert abbr == 'NYY'
        # Captured after the challenge normalization, as the header expects.
        assert original == 'In Progress'

    def test_manager_challenge_uses_its_own_prefix(self):
        gd, _, _ = self._norm(detailed_state='Manager challenge')
        assert gd['sub_event'] == 'M CHAL'

    def test_in_progress_before_first_pitch_is_pregame(self):
        gd, _, _ = self._norm(detailed_state='In Progress')
        assert gd['detailed_state'] == 'Pre-Game'

    @pytest.mark.parametrize('evidence', [
        {'balls': 1}, {'strikes': 2}, {'num_of_outs': 1}, {'away_runs': 1},
        {'home_runs': 3}, {'inningState': 'Middle'}, {'current_inning': 4},
        {'runner_on_first': True}, {'runner_on_second': True},
        {'runner_on_third': True}, {'last_play': 'Single'},
    ])
    def test_in_progress_stays_live_with_evidence_of_play(self, evidence):
        gd, _, _ = self._norm(detailed_state='In Progress', **evidence)
        assert gd['detailed_state'] == 'In Progress'

    def test_hits_alone_do_not_count_as_started(self):
        """Excluded deliberately: the GIF path inherits them from the final box
        score, so they are non-zero on every pre-game frame."""
        gd, _, _ = self._norm(
            detailed_state='In Progress', away_hits=9, home_hits=7)
        assert gd['detailed_state'] == 'Pre-Game'

    def test_caller_dict_is_never_mutated(self):
        from image_box import _normalize_game_state
        original = {'detailed_state': 'Delayed Start'}
        _normalize_game_state(original)
        assert original['detailed_state'] == 'Delayed Start'


class TestLayoutFlags:
    @staticmethod
    def _flags(**game):
        from image_box import _compute_layout_flags
        return _compute_layout_flags(game)

    def test_delayed_with_score_requires_an_inning(self):
        assert self._flags(detailed_state='Delayed', current_inning=5).delayed_with_score
        assert not self._flags(detailed_state='Delayed').delayed_with_score

    def test_between_innings(self):
        assert self._flags(
            detailed_state='In Progress', inningState='Middle').between_innings
        assert not self._flags(
            detailed_state='In Progress', inningState='Top').between_innings

    def test_pitching_change_and_mid_inning_variant(self):
        mid = self._flags(detailed_state='In Progress', sub_event='PC: Smith',
                          inningState='Top', num_of_outs=1)
        assert mid.pitching_change and mid.mid_inning_pc

        between = self._flags(detailed_state='In Progress', sub_event='PC: Smith',
                              inningState='Middle', num_of_outs=1)
        assert between.pitching_change and not between.mid_inning_pc

        start_of_inning = self._flags(detailed_state='In Progress',
                                      sub_event='PC: Smith', inningState='Top')
        assert not start_of_inning.mid_inning_pc

    def test_game_ending_state(self):
        # End of 9th with a leader
        assert self._flags(current_inning=9, inningState='End',
                           away_runs=3, home_runs=2).game_ending_state
        # End of 9th tied -> extra innings, not ending
        assert not self._flags(current_inning=9, inningState='End',
                               away_runs=2, home_runs=2).game_ending_state
        # Middle of 9th with home ahead -> home doesn't bat
        assert self._flags(current_inning=9, inningState='Middle',
                           away_runs=1, home_runs=5).game_ending_state
        # Middle of 9th with home behind -> they still bat
        assert not self._flags(current_inning=9, inningState='Middle',
                               away_runs=5, home_runs=1).game_ending_state
        # Too early
        assert not self._flags(current_inning=7, inningState='End',
                               away_runs=3, home_runs=2).game_ending_state


class TestFinalLinescoreWindow:
    def test_historical_mode_is_always_closed(self, monkeypatch):
        import image_box
        monkeypatch.setattr(image_box, '_historical_mode', True)
        assert image_box._in_final_linescore_window(
            {'game_end_time_utc': '2025-06-03T22:00:00Z'}, 3600) is False

    def test_recent_end_time_is_inside_the_window(self, monkeypatch):
        import datetime as _dt
        import image_box
        monkeypatch.setattr(image_box, '_historical_mode', False)
        recent = _dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
        assert image_box._in_final_linescore_window(
            {'game_end_time_utc': recent}, 3600) is True

    def test_old_end_time_is_outside_the_window(self, monkeypatch):
        import datetime as _dt
        import image_box
        monkeypatch.setattr(image_box, '_historical_mode', False)
        old = (_dt.datetime.now(_dt.timezone.utc)
               - _dt.timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M:%S')
        assert image_box._in_final_linescore_window(
            {'game_end_time_utc': old}, 3600) is False

    def test_falls_back_to_first_seen_final_time(self, monkeypatch):
        import time as _t
        import image_box
        monkeypatch.setattr(image_box, '_historical_mode', False)
        monkeypatch.setattr(image_box, '_get_or_set_final_time', lambda pk: _t.time())
        # Unparseable end time -> falls through to the first-seen timestamp
        assert image_box._in_final_linescore_window(
            {'game_pk': 1, 'game_end_time_utc': 'not-a-date'}, 3600) is True

    def test_no_end_time_and_no_final_timestamp(self, monkeypatch):
        import image_box
        monkeypatch.setattr(image_box, '_historical_mode', False)
        monkeypatch.setattr(image_box, '_get_or_set_final_time', lambda pk: None)
        assert image_box._in_final_linescore_window({'game_pk': 1}, 3600) is False


class TestHourWindow:
    """night_start == night_end used to mean 'always inside', so a single
    misconfigured pair (e.g. both 0) suppressed every refresh and froze the
    display all day with no obvious cause."""

    @staticmethod
    def _fn():
        from util import in_hour_window
        return in_hour_window

    def test_equal_bounds_is_an_empty_window(self):
        in_window = self._fn()
        assert all(in_window(0, 0, h) is False for h in range(24))
        assert all(in_window(7, 7, h) is False for h in range(24))

    def test_normal_window(self):
        in_window = self._fn()
        assert in_window(0, 7, 3) is True
        assert in_window(0, 7, 0) is True    # inclusive start
        assert in_window(0, 7, 7) is False   # exclusive end
        assert in_window(0, 7, 12) is False

    def test_window_wrapping_past_midnight(self):
        in_window = self._fn()
        assert in_window(20, 7, 22) is True
        assert in_window(20, 7, 3) is True
        assert in_window(20, 7, 20) is True   # inclusive start
        assert in_window(20, 7, 7) is False   # exclusive end
        assert in_window(20, 7, 12) is False

    def test_night_mode_not_frozen_by_equal_bounds(self, monkeypatch):
        import main as m
        cfg = {'night_start': 0, 'night_end': 0, 'timezone': 'America/Chicago'}
        for hour in (0, 3, 9, 15, 23):
            monkeypatch.setattr(
                m, '_local_now',
                lambda c, _h=hour: __import__('datetime').datetime(2025, 6, 3, _h))
            assert m._in_night_window(cfg) is False

    def test_dark_window_honours_equal_bounds(self, monkeypatch):
        import datetime as _dt
        import main as m
        monkeypatch.setattr(m, '_local_now',
                            lambda c: _dt.datetime(2025, 6, 3, 22))
        assert m._in_dark_window({'dark_start': 0, 'dark_end': 0}) is False
        assert m._in_dark_window({'dark_start': 20, 'dark_end': 7}) is True


class TestNextPreviewDate:
    """The 'next game' strip guessed its target date from the wall clock, so in
    the morning alternating window the blocks showing *today's* games still
    targeted today — a game postponed earlier that day advertised its own date
    as the next one."""

    @staticmethod
    def _fn(after_date):
        from image_box import _next_preview_date
        return _next_preview_date(after_date)

    def test_target_is_day_after_the_drawn_game(self):
        assert self._fn('2025-06-03') == '2025-06-04'

    def test_accepts_a_full_iso_timestamp(self):
        assert self._fn('2025-06-03T18:10:00Z') == '2025-06-04'

    def test_postponed_game_today_points_at_tomorrow(self):
        """The specific regression: previously this resolved to today."""
        assert self._fn('2025-06-03') != '2025-06-03'

    def test_month_and_year_rollover(self):
        assert self._fn('2025-06-30') == '2025-07-01'
        assert self._fn('2025-12-31') == '2026-01-01'

    def test_falls_back_to_tomorrow_without_a_date(self):
        import datetime as _dt
        expected = (_dt.date.today() + _dt.timedelta(days=1)).strftime('%Y-%m-%d')
        assert self._fn(None) == expected
        assert self._fn('') == expected
        assert self._fn('not-a-date') == expected


class TestTomorrowGamesMultiDayCache:
    """A single-slot cache made the morning alternating window refetch the
    schedule on every 5-minute block flip once the two blocks stopped agreeing
    on a target date."""

    def test_retains_multiple_days(self, tmp_path, monkeypatch):
        import fetch_games
        saved = {}
        monkeypatch.setattr(fetch_games, 'save_off_results',
                            lambda data, name: saved.update({name: data}))
        monkeypatch.setattr(fetch_games, 'load_json_file',
                            lambda name: saved.get('tomorrow_games', {}))

        fetch_games._save_tomorrow_games('2025-06-04', [{'game_pk': 1}])
        fetch_games._save_tomorrow_games('2025-06-05', [{'game_pk': 2}])

        cache = saved['tomorrow_games']
        # Most recent fetch stays at the top level for older readers.
        assert cache['date'] == '2025-06-05'
        # Both days remain retrievable, so flipping back doesn't refetch.
        assert cache['by_date']['2025-06-04']['games'] == [{'game_pk': 1}]
        assert cache['by_date']['2025-06-05']['games'] == [{'game_pk': 2}]

    def test_prunes_to_the_retention_limit(self, monkeypatch):
        import fetch_games
        saved = {}
        monkeypatch.setattr(fetch_games, 'save_off_results',
                            lambda data, name: saved.update({name: data}))
        monkeypatch.setattr(fetch_games, 'load_json_file',
                            lambda name: saved.get('tomorrow_games', {}))

        for day in range(1, 8):
            fetch_games._save_tomorrow_games(f'2025-06-0{day}', [{'game_pk': day}])

        by_date = saved['tomorrow_games']['by_date']
        assert len(by_date) == fetch_games._TOMORROW_CACHE_KEEP_DAYS
        assert '2025-06-07' in by_date      # newest kept
        assert '2025-06-01' not in by_date  # oldest pruned

    def test_upgrades_a_legacy_single_slot_file(self, monkeypatch):
        import fetch_games
        saved = {'tomorrow_games': {'date': '2025-06-04', 'fetched_at': 111,
                                    'games': [{'game_pk': 1}]}}
        monkeypatch.setattr(fetch_games, 'save_off_results',
                            lambda data, name: saved.update({name: data}))
        monkeypatch.setattr(fetch_games, 'load_json_file',
                            lambda name: saved.get('tomorrow_games', {}))

        fetch_games._save_tomorrow_games('2025-06-05', [{'game_pk': 2}])
        by_date = saved['tomorrow_games']['by_date']
        # The pre-existing day is carried into the map rather than dropped.
        assert by_date['2025-06-04']['games'] == [{'game_pk': 1}]
        assert by_date['2025-06-05']['games'] == [{'game_pk': 2}]

    def test_loader_reads_by_date_without_refetching(self, monkeypatch):
        import image_box
        monkeypatch.setattr(image_box, 'load_json_file', lambda name: {
            'date': '2025-06-05',
            'games': [{'game_pk': 2}],
            'by_date': {'2025-06-04': {'fetched_at': 1, 'games': [{'game_pk': 1}]},
                        '2025-06-05': {'fetched_at': 2, 'games': [{'game_pk': 2}]}},
        })

        def _boom(*a, **k):  # pragma: no cover - must not be reached
            raise AssertionError('refetched a date already in the cache')
        monkeypatch.setattr('fetch_games.fetch_tomorrow_games', _boom)

        # Drawn game on 06-03 -> wants 06-04, which is cached.
        assert image_box._load_tomorrow_games('2025-06-03')['games'] == [{'game_pk': 1}]
        # Drawn game on 06-04 -> wants 06-05, also cached.
        assert image_box._load_tomorrow_games('2025-06-04')['games'] == [{'game_pk': 2}]


class TestDrawBoxHelpers:
    """Unit coverage for the blocks extracted from draw_box()."""

    def test_bold_text_draws_twice_offset_by_scale(self):
        from image_box import _draw_bold_text

        calls = []

        class _Rec:
            def text(self, xy, text, font=None, fill=None):
                calls.append(xy)

        _draw_bold_text(_Rec(), (10, 20), 'HI', font=None, s=2)
        assert calls == [(10, 20), (12, 20)]

    def test_duration_corner_x_shifts_for_logos(self):
        from image_box import _duration_corner_x
        assert _duration_corner_x(0, 1, use_logos=False, logo_x_offset=2) == 8
        # With logos the slot clears the away logo instead.
        assert _duration_corner_x(0, 1, use_logos=True, logo_x_offset=2) == 35

    @staticmethod
    def _ctx(use_logos=False):
        from PIL import Image as _Img
        from image_box import _TileCtx
        return _TileCtx(_Img.new('1', (800, 480), 255), 0, 0, 1, use_logos, 2)

    def test_ctx_exposes_tile_geometry(self):
        from PIL import Image as _Img
        from image_box import _TileCtx
        assert (self._ctx().w, self._ctx().h) == (135, 110)
        # Geometry and fonts scale together.
        scaled = _TileCtx(_Img.new('1', (800, 480), 255), 0, 0, 2, False, 2)
        assert (scaled.w, scaled.h) == (270, 220)

    def test_ctx_paste_refreshes_draw_handle(self):
        """Pasting invalidates the ImageDraw; ctx.paste must hand back a fresh one."""
        from PIL import Image as _Img
        ctx = self._ctx()
        before = ctx.draw
        ctx.paste(_Img.new('1', (4, 4), 0), (0, 0))
        assert ctx.draw is not before

    def test_ctx_centres_text(self):
        ctx = self._ctx()
        text = 'ABC'
        expected = ctx.x + ctx.w // 2 - int(ctx.font14.getlength(text)) // 2
        assert ctx.centred_x(text, ctx.font14) == expected

    def test_win_prob_bar_no_op_when_data_missing(self):
        ctx = self._ctx()
        before = ctx.Himage.tobytes()
        _draw_win_probability_bar(ctx, {}, ('NYY', 147), ('BOS', 111))
        assert ctx.Himage.tobytes() == before

    def test_win_prob_bar_renders_with_probabilities(self):
        ctx = self._ctx()
        before = ctx.Himage.tobytes()
        _draw_win_probability_bar(
            ctx, {'away_win_probability': 70, 'home_win_probability': 30},
            ('NYY', 147), ('BOS', 111))
        assert ctx.Himage.tobytes() != before

    def test_win_prob_bar_accepts_fractional_probabilities(self):
        """The API sometimes returns 0-1 fractions rather than percentages."""
        ctx = self._ctx()
        before = ctx.Himage.tobytes()
        _draw_win_probability_bar(
            ctx, {'away_win_probability': 0.7, 'home_win_probability': 0.3},
            ('NYY', 147), ('BOS', 111))
        assert ctx.Himage.tobytes() != before

    @staticmethod
    def _longest_run(image, y, x0, x1):
        """Longest unbroken run of black pixels on row ``y``.

        The rule has to be told apart from the ghosted LOSS/WIN watermark, which
        also puts black pixels on that row. The watermark is dithered, so its
        runs are a pixel or two; the rule is the full width of the strip.
        """
        px = image.load()
        best = cur = 0
        for x in range(x0, x1):
            cur = cur + 1 if px[x, y] == 0 else 0
            best = max(best, cur)
        return best

    @staticmethod
    def _wp_ctx():
        from image_box import _TileCtx
        img = Image.new('1', (800, 480), 255)
        return _TileCtx(img, 0, 0, 1, False, 2), img

    @staticmethod
    def _bar_y(ctx):
        return ctx.y + ctx.h + 21 * ctx.s + (19 * ctx.s) // 2

    def test_win_prob_center_line_suppressed_for_multi_cell_tiles(self):
        """On a wide/triple tile the strip can only span the 135px left cell —
        the rest of that gap belongs to the K-strikeout strip — so the rule ended
        mid-tile and read as a stray line crossing the panel."""
        ctx, img = self._wp_ctx()
        _draw_win_probability_bar(
            ctx, {'away_win_probability': 46, 'home_win_probability': 54},
            ('NYY', 147), ('BOS', 111), center_line=False)
        assert self._longest_run(img, self._bar_y(ctx), 0, ctx.x + ctx.w) <= 2

    def test_win_prob_center_line_kept_by_default(self):
        """Single cells are unaffected: the rule still spans the cell."""
        ctx, img = self._wp_ctx()
        _draw_win_probability_bar(
            ctx, {'away_win_probability': 46, 'home_win_probability': 54},
            ('NYY', 147), ('BOS', 111))
        assert self._longest_run(img, self._bar_y(ctx), 0, ctx.x + ctx.w) >= 130

    def test_win_prob_bar_never_reaches_the_k_strip(self):
        """The K strip starts at the left cell's right edge in the same gap, so
        nothing the win-probability bar draws may cross that boundary."""
        ctx, img = self._wp_ctx()
        _draw_win_probability_bar(
            ctx, {'away_win_probability': 99, 'home_win_probability': 1},
            ('NYY', 147), ('BOS', 111))
        px = img.load()
        bar_top = ctx.y + ctx.h + 21 * ctx.s
        for y in range(bar_top, bar_top + 19 * ctx.s):
            for x in range(ctx.x + ctx.w, img.width):
                assert px[x, y] != 0, f'bar drew into the K strip at ({x}, {y})'

    def test_wide_tile_suppresses_the_center_line_end_to_end(self):
        """Pins the wiring, not just the helper: rendering a live wide tile must
        leave no rule in the strip below it."""
        from image_box import draw_wide_box
        import image_box
        game = _live_wide_game()
        img = Image.new('1', (800, 480), 255)
        with patch('image_box.load_yaml_file',
                   return_value={'timezone': 'America/Chicago',
                                 'final_linescore_minutes': 60}):
            image_box.set_historical_mode(True)
            try:
                draw_wide_box(img, 32, 30, game, _TEAM_DATA, show_win_prob=True)
            finally:
                image_box.set_historical_mode(False)
        # The strip's centre row, across the left cell only.
        assert self._longest_run(img, 30 + 110 + 21 + 9, 33, 33 + 133) <= 2

    def test_end_time_skipped_outside_linescore_window(self):
        ctx = self._ctx()
        before = ctx.Himage.tobytes()
        _draw_game_end_time(ctx, '2025-06-03T22:00:00Z', in_linescore_window=False,
                            game_is_final=True)
        assert ctx.Himage.tobytes() == before

    def test_end_time_drawn_inside_linescore_window(self):
        ctx = self._ctx()
        before = ctx.Himage.tobytes()
        _draw_game_end_time(ctx, '2025-06-03T22:00:00Z', in_linescore_window=True,
                            game_is_final=True)
        assert ctx.Himage.tobytes() != before

    def test_end_time_ignores_malformed_timestamp(self):
        ctx = self._ctx()
        before = ctx.Himage.tobytes()
        _draw_game_end_time(ctx, 'garbage', in_linescore_window=True, game_is_final=True)
        assert ctx.Himage.tobytes() == before

    def test_end_time_skipped_while_game_still_in_progress(self):
        """The strip below the box belongs to the live win-probability bar until
        the game ends; PR #278 extracted this helper but dropped both the call
        site and this guard, so the end time never rendered at all."""
        ctx = self._ctx()
        before = ctx.Himage.tobytes()
        _draw_game_end_time(ctx, '2025-06-03T22:00:00Z', in_linescore_window=True,
                            game_is_final=False)
        assert ctx.Himage.tobytes() == before

    def test_end_time_reaches_the_canvas_through_draw_box(self):
        """Guards the regression itself: exercising the real draw_box path must
        put the end time on the canvas, not just calling the helper directly."""
        from image_box import draw_box
        game = _final_game_with_end_time()
        with patch('image_box.load_yaml_file',
                   return_value={'timezone': 'America/Chicago',
                                 'final_linescore_minutes': 60,
                                 'show_game_end_time_always': True}):
            with_end = _render_box(draw_box, game)
            without_end = _render_box(draw_box, dict(game, game_end_time_utc=None))
        assert with_end != without_end

    def test_linescore_window_expiry_prefers_api_end_time(self):
        import datetime as _dt
        from image_box import _final_linescore_window_expired

        recent = _dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        assert _final_linescore_window_expired(
            {'game_end_time_utc': recent}, 3600) is False

        old = (_dt.datetime.now(_dt.timezone.utc)
               - _dt.timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M:%SZ')
        assert _final_linescore_window_expired(
            {'game_end_time_utc': old}, 3600) is True

    def test_linescore_window_expiry_falls_back_to_game_date(self):
        """A game dated before today is definitively over, regardless of clock."""
        from image_box import _final_linescore_window_expired
        assert _final_linescore_window_expired(
            {'game_date': '2001-06-03'}, 3600) is True


class TestSeriesState:
    """Regular-season and postseason series end differently: a regular-season
    series is complete only once every scheduled game is played, whereas a
    postseason series ends the moment one side clinches. series_is_over is
    authoritative for one and not the other."""

    @staticmethod
    def _state(**game):
        from image_box import _compute_series_state
        game.setdefault('detailed_state', 'Final')
        return _compute_series_state(game)

    def test_no_series_flags_when_game_not_final(self):
        st = self._state(detailed_state='In Progress', series_total_games=3,
                         series_wins=3, series_losses=0, series_is_over=True)
        assert not (st.is_sweep or st.clinched or st.tied or st.leading)
        assert st.show_overline is False

    def test_single_game_series_has_no_context(self):
        st = self._state(series_total_games=1, series_wins=1)
        assert not (st.is_sweep or st.clinched or st.leading)

    def test_regular_season_sweep_needs_all_games_played(self):
        played = dict(series_total_games=3, series_wins=3, series_losses=0,
                      series_description='Regular Season')
        assert self._state(**played).is_sweep is True
        # 2-0 with a game still to play is not yet a sweep.
        partial = dict(played, series_wins=2)
        assert self._state(**partial).is_sweep is False

    def test_postseason_sweep_uses_series_is_over(self):
        """A 3-0 postseason sweep ends a 5-game series before all games needed."""
        st = self._state(series_total_games=5, series_wins=3, series_losses=0,
                         series_description='Division Series', series_is_over=True)
        assert st.is_sweep is True
        assert st.show_overline is True

    def test_clinched_is_a_non_sweep_finished_series(self):
        st = self._state(series_total_games=5, series_wins=3, series_losses=1,
                         series_description='Division Series', series_is_over=True)
        assert st.clinched is True
        assert st.is_sweep is False

    def test_tied_and_leading_are_mid_series(self):
        tied = self._state(series_total_games=3, series_wins=1, series_losses=1,
                           series_is_tied=True)
        assert tied.tied is True and tied.leading is False

        leading = self._state(series_total_games=3, series_wins=1, series_losses=0)
        assert leading.leading is True and leading.tied is False

    def test_active_no_hitter_requires_six_innings(self):
        assert self._state(detailed_state='In Progress', no_hitter=True,
                           current_inning=6).active_no_no is True
        assert self._state(detailed_state='In Progress', no_hitter=True,
                           current_inning=5).active_no_no is False


class TestHeaderRightText:
    @staticmethod
    def _ctx():
        from PIL import Image as _Img
        from image_box import _TileCtx
        return _TileCtx(_Img.new('1', (800, 480), 255), 0, 0, 1, False, 2)

    def test_nothing_drawn_without_text_or_width(self):
        from image_box import _draw_header_right_text, _VENUE_FONT_LADDER
        ctx = self._ctx()
        before = ctx.Himage.tobytes()
        _draw_header_right_text(ctx, '', 130, 100, _VENUE_FONT_LADDER)
        _draw_header_right_text(ctx, 'Wrigley Field', 130, 0, _VENUE_FONT_LADDER)
        assert ctx.Himage.tobytes() == before

    def test_venue_renders_and_is_right_anchored(self):
        from image_box import _draw_header_right_text, _VENUE_FONT_LADDER
        ctx = self._ctx()
        before = ctx.Himage.tobytes()
        _draw_header_right_text(ctx, 'Wrigley Field', 130, 120, _VENUE_FONT_LADDER)
        assert ctx.Himage.tobytes() != before

    def test_venue_falls_back_to_smallest_rather_than_clipping(self):
        """A long stadium name shrinks rather than being cut short."""
        from image_box import _draw_header_right_text, _VENUE_FONT_LADDER
        ctx = self._ctx()
        before = ctx.Himage.tobytes()
        _draw_header_right_text(ctx, 'A Very Long Stadium Name Indeed', 130, 20,
                                _VENUE_FONT_LADDER)
        assert ctx.Himage.tobytes() != before

    def test_delay_reason_truncates_to_fit(self):
        from image_box import _draw_header_right_text, _DELAY_FONT_LADDER
        ctx = self._ctx()
        before = ctx.Himage.tobytes()
        _draw_header_right_text(ctx, 'Rain delay in progress', 130, 40,
                                _DELAY_FONT_LADDER, truncate=True)
        assert ctx.Himage.tobytes() != before

    def test_delay_reason_draws_nothing_when_no_character_fits(self):
        from image_box import _draw_header_right_text, _DELAY_FONT_LADDER
        ctx = self._ctx()
        before = ctx.Himage.tobytes()
        _draw_header_right_text(ctx, 'Rain', 130, 1, _DELAY_FONT_LADDER, truncate=True)
        assert ctx.Himage.tobytes() == before
