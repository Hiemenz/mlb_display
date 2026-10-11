"""Off-season replay: is_offseason, pick_replay_date, maybe_start_replay, and the
_show_idle_screen hook. Network, subprocesses and disk are mocked."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import fetch_idle
import offseason_replay as orp

WS_DONE = [{'round': 'WS', 'complete': True}]
WS_LIVE = [{'round': 'WS', 'complete': False}]


class TestIsOffseason:
    def test_winter_months(self):
        for m in (12, 1, 2):
            assert orp.is_offseason(datetime(2026, m, 15))

    def test_regular_season_and_early_october(self):
        assert not orp.is_offseason(datetime(2026, 7, 4), WS_DONE)
        assert not orp.is_offseason(datetime(2026, 10, 9), WS_LIVE)
        assert not orp.is_offseason(datetime(2026, 10, 9))

    def test_world_series_complete(self):
        assert orp.is_offseason(datetime(2026, 10, 30), WS_DONE)
        assert orp.is_offseason(datetime(2026, 11, 3), WS_DONE)

    def test_november_after_the_tenth(self):
        assert orp.is_offseason(datetime(2026, 11, 11))
        assert not orp.is_offseason(datetime(2026, 11, 5), WS_LIVE)


def _resp(status=200, games=4):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = {'dates': [{'games': [{}] * games}] if games else []}
    return m


class TestPickReplayDate:
    def _pick(self, dates, responses, **kw):
        with patch('fetch_idle._random_past_date', side_effect=dates), \
             patch('fetch_idle.requests.get', side_effect=responses):
            return fetch_idle.pick_replay_date('2026-12-01', **kw)

    def test_full_slate_wins_immediately(self):
        assert self._pick(['2024-07-04'], [_resp(games=15)]) == '2024-07-04'

    def test_prefers_the_busiest_partial_slate(self):
        assert self._pick(['a', 'b', 'c'], [_resp(games=5), _resp(games=8), _resp(games=6)],
                          tries=3) == 'b'

    def test_skips_empty_bad_status_errors_and_tiny_slates(self):
        assert self._pick(['a', 'b', 'c', 'd', 'e'],
                          [_resp(games=0), _resp(status=503), OSError('x'), _resp(games=2),
                           _resp(games=12)], tries=5) == 'e'

    def test_gives_up(self):
        assert self._pick(['x'] * 3, [_resp(games=0)] * 3, tries=3) is None


class TestMaybeStartReplay:
    def test_disabled(self):
        assert not orp.maybe_start_replay({'offseason_replay': False}, '2026-12-01')

    def test_running_replay_is_left_alone(self):
        with patch('offseason_replay.load_json_file', return_value={'pid': 5, 'date': 'd'}), \
             patch('offseason_replay._replay_running', return_value=True), \
             patch('offseason_replay.subprocess.Popen') as popen:
            assert orp.maybe_start_replay({}, '2026-12-01')
        popen.assert_not_called()

    def test_starts_a_replay_and_writes_the_lock(self, tmp_path):
        lock = tmp_path / 'data' / 'offseason_replay.json'
        with patch('offseason_replay.load_json_file', return_value=None), \
             patch('offseason_replay._LOCK_PATH', str(lock)), \
             patch('offseason_replay.pick_replay_date', return_value='2024-07-04'), \
             patch('offseason_replay.subprocess.Popen', return_value=MagicMock(pid=42)) as popen:
            assert orp.maybe_start_replay({'offseason_replay_step_minutes': 2}, '2026-12-01')
        cmd = popen.call_args[0][0]
        assert cmd[-6:] == ['--date', '2024-07-04', '--step', '2', '--delay', '30']
        assert '"pid": 42' in lock.read_text()

    def _lock(self, day, count):
        return {'pid': 1, 'date': 'd', 'day': day, 'count': count}

    def test_daily_quota_stops_new_replays(self):
        with patch('offseason_replay.load_json_file', return_value=self._lock('2026-12-01', 2)), \
             patch('offseason_replay._replay_running', return_value=False), \
             patch('offseason_replay.subprocess.Popen') as popen:
            assert not orp.maybe_start_replay({}, '2026-12-01')
            assert not orp.maybe_start_replay({'offseason_replays_per_day': 1}, '2026-12-01')
        popen.assert_not_called()

    def test_second_replay_of_the_day_counts_up(self, tmp_path):
        lock = tmp_path / 'offseason_replay.json'
        with patch('offseason_replay.load_json_file', return_value=self._lock('2026-12-01', 1)), \
             patch('offseason_replay._replay_running', return_value=False), \
             patch('offseason_replay._LOCK_PATH', str(lock)), \
             patch('offseason_replay.pick_replay_date', return_value='2024-07-04'), \
             patch('offseason_replay.subprocess.Popen', return_value=MagicMock(pid=9)):
            assert orp.maybe_start_replay({}, '2026-12-01')
        assert '"count": 2' in lock.read_text()

    def test_quota_resets_on_a_new_day(self, tmp_path):
        lock = tmp_path / 'offseason_replay.json'
        with patch('offseason_replay.load_json_file', return_value=self._lock('2026-11-30', 2)), \
             patch('offseason_replay._replay_running', return_value=False), \
             patch('offseason_replay._LOCK_PATH', str(lock)), \
             patch('offseason_replay.pick_replay_date', return_value='2024-07-04'), \
             patch('offseason_replay.subprocess.Popen', return_value=MagicMock(pid=9)):
            assert orp.maybe_start_replay({}, '2026-12-01')
        assert '"count": 1' in lock.read_text()

    def test_no_usable_date(self):
        with patch('offseason_replay.load_json_file', return_value=None), \
             patch('offseason_replay.pick_replay_date', return_value=None):
            assert not orp.maybe_start_replay({}, '2026-12-01')

    def test_popen_failure(self):
        with patch('offseason_replay.load_json_file', return_value=None), \
             patch('offseason_replay.pick_replay_date', return_value='2024-07-04'), \
             patch('offseason_replay.subprocess.Popen', side_effect=OSError('nope')):
            assert not orp.maybe_start_replay({}, '2026-12-01')


class TestReplayRunning:
    def test_matches_only_replay_processes(self, tmp_path):
        import builtins
        real_open = builtins.open

        def fake_open(path, *a, **k):
            if str(path) == '/proc/7/cmdline':
                f = tmp_path / 'cmd'
                f.write_bytes(b'python\0src/replay.py\0')
                return real_open(f, *a, **k)
            return real_open(path, *a, **k)

        with patch('builtins.open', fake_open):
            assert orp._replay_running(7)
        assert not orp._replay_running(None)
        assert not orp._replay_running(2 ** 22 + 12345)


class TestIdleHook:
    def _run(self, started, now):
        import main
        with patch('main.datetime') as dt, \
             patch('main.load_json_file', return_value=None), \
             patch('offseason_replay.maybe_start_replay', return_value=started) as start, \
             patch('main._render_next_games', side_effect=RuntimeError('reached idle')):
            dt.now.return_value = now
            try:
                main._show_idle_screen({'timezone': 'UTC'})
                reached_idle = False
            except RuntimeError:
                reached_idle = True
        return start, reached_idle

    def test_replay_takes_over_in_the_offseason(self):
        start, reached_idle = self._run(True, datetime(2026, 12, 1, 12, 5))
        start.assert_called_once()
        assert not reached_idle

    def test_falls_through_when_no_replay_starts(self):
        _, reached_idle = self._run(False, datetime(2026, 12, 1, 12, 5))
        assert reached_idle

    def test_not_consulted_in_season(self):
        start, _ = self._run(True, datetime(2026, 7, 1, 12, 5))
        start.assert_not_called()
