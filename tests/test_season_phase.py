"""season_phase: phase boundaries from season dates, the calendar fallback, and the
daily cache. Network and disk are mocked."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

import season_phase as sp
import offseason_replay

# Imported at module load, before the autouse fixture stubs it out.
REAL_GET_SEASON = sp.get_season

# The real 2026 record from /api/v1/seasons (trimmed to the fields we use).
S2026 = {
    'seasonId': '2026',
    'preSeasonStartDate': '2026-01-01',
    'springStartDate': '2026-02-20',
    'regularSeasonStartDate': '2026-03-25',
    'regularSeasonEndDate': '2026-09-27',
    'postSeasonStartDate': '2026-09-28',
    'postSeasonEndDate': '2026-10-28',
}
WS_DONE = [{'round': 'WS', 'complete': True}]
WS_LIVE = [{'round': 'WS', 'complete': False}]


def phase(y, m, d, series=None, season=S2026):
    return sp.season_phase(datetime(y, m, d, 12), series, season=season)


class TestPhaseFromSeasonDates:
    @pytest.mark.parametrize('ymd,expected', [
        ((2026, 1, 1), 'preseason'),
        ((2026, 2, 19), 'preseason'),
        ((2026, 2, 20), 'spring'),
        ((2026, 3, 24), 'spring'),
        ((2026, 3, 25), 'regular'),
        ((2026, 7, 14), 'regular'),
        ((2026, 9, 27), 'regular'),
        ((2026, 9, 28), 'postseason'),
        ((2026, 10, 28), 'postseason'),
        ((2026, 10, 29), 'offseason_hot'),
        ((2026, 11, 7), 'offseason_hot'),
        ((2026, 12, 20), 'offseason_hot'),
        ((2026, 12, 21), 'offseason_quiet'),
        ((2026, 12, 31), 'offseason_quiet'),
    ])
    def test_boundaries(self, ymd, expected):
        assert phase(*ymd) == expected

    def test_world_series_complete_ends_postseason_early(self):
        assert phase(2026, 10, 25, WS_DONE) == 'offseason_hot'
        assert phase(2026, 10, 25, WS_LIVE) == 'postseason'

    def test_live_world_series_runs_past_scheduled_end_until_cap(self):
        assert phase(2026, 10, 31, WS_LIVE) == 'postseason'
        assert phase(2026, 11, 10, WS_LIVE) == 'postseason'
        assert phase(2026, 11, 11, WS_LIVE) == 'offseason_hot'   # stale bracket

    def test_early_ending_year(self):
        short = dict(S2026, postSeasonEndDate='2026-10-20')
        assert phase(2026, 10, 21, season=short) == 'offseason_hot'

    def test_date_before_preseason_window(self):
        late = dict(S2026, preSeasonStartDate='2026-01-15')
        assert phase(2026, 1, 5, season=late) == 'offseason_quiet'

    def test_missing_preseason_date_still_works(self):
        no_pre = {k: v for k, v in S2026.items() if k != 'preSeasonStartDate'}
        assert phase(2026, 1, 5, season=no_pre) == 'preseason'

    def test_incomplete_record_uses_calendar_fallback(self):
        assert phase(2026, 7, 4, season={'seasonId': '2026'}) == 'regular'
        assert phase(2026, 7, 4, season={'springStartDate': 'garbage'}) == 'regular'

    def test_different_year_shifts_the_phases(self):
        late = dict(S2026, regularSeasonEndDate='2027-10-01', postSeasonStartDate='2027-10-02',
                    postSeasonEndDate='2027-11-04', springStartDate='2027-02-25',
                    regularSeasonStartDate='2027-03-30', preSeasonStartDate='2027-01-01')
        assert phase(2027, 11, 3, season=late) == 'postseason'
        assert phase(2027, 11, 5, season=late) == 'offseason_hot'


class TestCalendarFallback:
    @pytest.mark.parametrize('ymd,series,expected', [
        ((2026, 1, 10), None, 'preseason'),
        ((2026, 2, 10), None, 'preseason'),
        ((2026, 2, 25), None, 'spring'),
        ((2026, 3, 10), None, 'spring'),
        ((2026, 3, 25), None, 'regular'),
        ((2026, 7, 4), WS_DONE, 'regular'),
        ((2026, 9, 20), None, 'regular'),
        ((2026, 9, 30), None, 'postseason'),
        ((2026, 10, 9), None, 'postseason'),
        ((2026, 10, 9), WS_LIVE, 'postseason'),
        ((2026, 10, 30), WS_DONE, 'offseason_hot'),
        ((2026, 11, 5), WS_LIVE, 'postseason'),
        ((2026, 11, 11), None, 'offseason_hot'),
        ((2026, 12, 1), None, 'offseason_hot'),
        ((2026, 12, 25), None, 'offseason_quiet'),
    ])
    def test_matches_old_month_rules(self, ymd, series, expected):
        assert phase(*ymd, series=series, season=None) == expected

    def test_default_now_uses_get_season(self):
        # the autouse fixture makes get_season return None -> fallback, no network
        assert sp.season_phase() in sp.PHASES


def test_is_offseason_phase():
    assert all(sp.is_offseason_phase(p) for p in ('preseason', 'offseason_hot', 'offseason_quiet'))
    assert not any(sp.is_offseason_phase(p) for p in ('spring', 'regular', 'postseason'))


class TestIsOffseasonDelegates:
    def test_uses_real_season_dates_when_available(self):
        with patch('season_phase.get_season', return_value=S2026):
            # Oct 29 with no bracket data: the old rules said "still postseason"
            assert offseason_replay.is_offseason(datetime(2026, 10, 29), None)
            assert not offseason_replay.is_offseason(datetime(2026, 10, 28), None)
            assert not offseason_replay.is_offseason(datetime(2026, 7, 4), WS_DONE)

    def test_still_works_without_season_dates(self):
        assert offseason_replay.is_offseason(datetime(2026, 12, 15))
        assert not offseason_replay.is_offseason(datetime(2026, 10, 9), WS_LIVE)


# --- fetch + cache -----------------------------------------------------------

def _resp(status=200, seasons=None):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = {'seasons': seasons if seasons is not None else [S2026]}
    return m


class TestFetchSeason:
    def test_fetch_returns_matching_year(self):
        with patch('season_phase.requests.get', return_value=_resp()) as get:
            assert sp._fetch_season(2026) == S2026
        assert get.call_args.kwargs['params'] == {'sportId': 1, 'season': 2026, 'all': 'false'}

    def test_fetch_failures_return_none(self):
        with patch('season_phase.requests.get', return_value=_resp(500)):
            assert sp._fetch_season(2026) is None
        with patch('season_phase.requests.get', return_value=_resp(seasons=[])):
            assert sp._fetch_season(2026) is None
        with patch('season_phase.requests.get', return_value=_resp(seasons=[{'seasonId': '2025'}])):
            assert sp._fetch_season(2026) is None
        with patch('season_phase.requests.get', side_effect=OSError('down')):
            assert sp._fetch_season(2026) is None


class TestGetSeasonCache:
    NOW = 1_800_000_000

    def _get(self, cache, fetched, now=None):
        with patch('season_phase.load_json_file', return_value=cache), \
             patch('season_phase._fetch_season', return_value=fetched) as fetch, \
             patch('season_phase.save_off_results') as save:
            rec = REAL_GET_SEASON(2026, now_ts=now or self.NOW)
        return rec, fetch, save

    def test_fresh_cache_skips_the_network(self):
        cache = {'fetched_at': self.NOW - 3600, 'seasons': {'2026': S2026}}
        rec, fetch, save = self._get(cache, None)
        assert rec == S2026
        fetch.assert_not_called()
        save.assert_not_called()

    def test_stale_cache_refetches_and_saves(self):
        cache = {'fetched_at': self.NOW - 2 * 86400, 'seasons': {'2026': {'old': 1}, '2025': {'k': 1}}}
        rec, fetch, save = self._get(cache, S2026)
        assert rec == S2026
        saved = save.call_args.args[0]
        assert saved['fetched_at'] == self.NOW
        assert saved['seasons'] == {'2026': S2026, '2025': {'k': 1}}   # other years kept

    def test_empty_cache_fetches(self):
        rec, fetch, save = self._get({}, S2026)
        assert rec == S2026
        save.assert_called_once()

    def test_network_failure_falls_back_to_stale_cache(self):
        cache = {'fetched_at': 0, 'seasons': {'2026': S2026}}
        rec, _, save = self._get(cache, None)
        assert rec == S2026
        save.assert_not_called()

    def test_no_cache_and_no_network_is_none(self):
        assert self._get({}, None)[0] is None

    def test_save_failure_is_not_fatal(self):
        with patch('season_phase.load_json_file', return_value={}), \
             patch('season_phase._fetch_season', return_value=S2026), \
             patch('season_phase.save_off_results', side_effect=OSError('ro')):
            assert REAL_GET_SEASON(2026, now_ts=self.NOW) == S2026

    def test_default_timestamp_is_now(self):
        with patch('season_phase.load_json_file', return_value={}), \
             patch('season_phase._fetch_season', return_value=S2026), \
             patch('season_phase.save_off_results') as save:
            REAL_GET_SEASON(2026)
        assert save.call_args.args[0]['fetched_at'] > 1_700_000_000


def test_cli_prints_the_phase(capsys):
    with patch('season_phase.load_json_file', return_value={'series': WS_DONE}):
        sp.main()
    assert capsys.readouterr().out.strip() in sp.PHASES
