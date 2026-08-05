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
