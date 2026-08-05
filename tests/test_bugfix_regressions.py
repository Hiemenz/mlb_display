"""Regression tests for bugs found in the whole-repo audit.

Each class pins one specific defect so it can't silently come back.
"""
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from image_utils import division_rank  # noqa: E402
from image_magic import draw_magic_cell  # noqa: E402
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
