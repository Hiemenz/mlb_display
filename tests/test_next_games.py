"""Tests for the off-day "next games" screen: fetch_idle.fetch_next_game_day /
get_next_game_day, image_idle.draw_next_games_screen, and main's idle rotation.

Network, disk, logos and the display are all mocked. Logos are patched off
because pic/logos/*.png are gitignored and the real loader would download them.
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytz

import fetch_idle
import image_idle
import main

CHI = pytz.timezone('America/Chicago')


def _resp(status=200, payload=None):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = payload if payload is not None else {}
    return m


def _raw_game(pk, gtype='R', start='2026-09-29T23:05:00Z', state='Scheduled',
              away=('NYY', 147), home=('BOS', 111), series=None, away_pitcher=None):
    teams = {
        'away': {'team': {'id': away[1], 'abbreviation': away[0]},
                 'leagueRecord': {'wins': 90, 'losses': 70}},
        'home': {'team': {'id': home[1], 'abbreviation': home[0]},
                 'leagueRecord': {'wins': 88, 'losses': 72}},
    }
    if away_pitcher:
        teams['away']['probablePitcher'] = {'fullName': away_pitcher}
    g = {'gamePk': pk, 'gameType': gtype, 'gameDate': start,
         'status': {'detailedState': state}, 'teams': teams,
         'venue': {'name': 'Fenway Park'}}
    if series:
        g['seriesStatus'] = series
        g['seriesGameNumber'] = 2
        g['gamesInSeries'] = 5
        g['seriesDescription'] = 'AL Division Series'
    return g


def _next_day(games, date='2026-09-29'):
    return {'date': date, 'games': games}


def _parsed(pk=1, gtype='R', start='2026-09-29T23:05:00Z', series=None,
            away_probable=None, home_probable=None, away=('NYY', 147), home=('BOS', 111)):
    return {
        'game_pk': pk, 'start_utc': start, 'game_type': gtype, 'venue': 'Fenway Park',
        'away': {'id': away[1], 'abbr': away[0], 'record': '90-70', 'probable': away_probable},
        'home': {'id': home[1], 'abbr': home[0], 'record': '88-72', 'probable': home_probable},
        'series': series,
    }


# ---------------------------------------------------------------------------
# fetch_idle.fetch_next_game_day
# ---------------------------------------------------------------------------

class TestParseNextGame:
    def test_regular_season_game_has_no_series(self):
        g = fetch_idle._parse_next_game(_raw_game(1, away_pitcher='Gerrit Cole'))
        assert g['series'] is None
        assert g['away'] == {'id': 147, 'abbr': 'NYY', 'record': '90-70', 'probable': 'Gerrit Cole'}
        assert g['home']['probable'] is None
        assert g['venue'] == 'Fenway Park'

    def test_postseason_game_carries_series_status(self):
        series = {'shortDescription': 'ALDS Game 2', 'result': 'TOR leads 1-0'}
        g = fetch_idle._parse_next_game(_raw_game(1, gtype='D', series=series))
        assert g['series'] == {'desc': 'ALDS Game 2', 'result': 'TOR leads 1-0',
                               'game_number': 2, 'total_games': 5}

    def test_series_description_is_the_fallback_label(self):
        g = fetch_idle._parse_next_game(_raw_game(1, gtype='D', series={'result': 'TOR leads 1-0'}))
        assert g['series']['desc'] == 'AL Division Series'

    def test_missing_record_and_abbr_are_tolerated(self):
        g = fetch_idle._parse_next_game({'gamePk': 9, 'teams': {}})
        assert g['away'] == {'id': None, 'abbr': '???', 'record': None, 'probable': None}
        assert g['series'] is None


class TestFetchNextGameDay:
    def _fetch(self, payload, **kwargs):
        with patch('fetch_idle.requests.get', return_value=_resp(payload=payload)):
            return fetch_idle.fetch_next_game_day('2026-09-29', **kwargs)

    def test_returns_first_date_with_games_sorted_by_first_pitch(self):
        payload = {'dates': [
            {'date': '2026-09-29', 'games': []},
            {'date': '2026-09-30', 'games': [
                _raw_game(2, start='2026-10-01T01:00:00Z'),
                _raw_game(1, start='2026-09-30T18:00:00Z'),
            ]},
            {'date': '2026-10-01', 'games': [_raw_game(3)]},
        ]}
        result = self._fetch(payload)
        assert result['date'] == '2026-09-30'
        assert [g['game_pk'] for g in result['games']] == [1, 2]
        assert result['sport_id'] == 1

    def test_drops_spring_training_when_real_games_share_the_day(self):
        payload = {'dates': [{'date': '2026-09-29', 'games': [
            _raw_game(1, gtype='S'), _raw_game(2, gtype='R')]}]}
        assert [g['game_pk'] for g in self._fetch(payload)['games']] == [2]

    def test_keeps_spring_training_when_it_is_all_there_is(self):
        payload = {'dates': [{'date': '2026-09-29', 'games': [_raw_game(1, gtype='S')]}]}
        assert [g['game_pk'] for g in self._fetch(payload)['games']] == [1]

    def test_postponed_games_are_skipped(self):
        payload = {'dates': [
            {'date': '2026-09-29', 'games': [_raw_game(1, state='Postponed')]},
            {'date': '2026-09-30', 'games': [_raw_game(2)]},
        ]}
        assert self._fetch(payload)['date'] == '2026-09-30'

    def test_nothing_scheduled_returns_none(self):
        assert self._fetch({'dates': []}) is None

    def test_non_200_falls_through_to_the_next_sport(self):
        good = _resp(payload={'dates': [{'date': '2026-09-29', 'games': [_raw_game(7)]}]})
        with patch('fetch_idle.requests.get', side_effect=[_resp(status=503), good]):
            result = fetch_idle.fetch_next_game_day('2026-09-29', sport_id_priority=(1, 11))
        assert result['sport_id'] == 11

    def test_network_error_returns_none(self):
        with patch('fetch_idle.requests.get', side_effect=OSError('down')):
            assert fetch_idle.fetch_next_game_day('2026-09-29') is None


class TestGetNextGameDay:
    def _cached(self, **overrides):
        data = {'date': '2026-09-29', 'from_date': '2026-09-29', 'games': [_parsed()],
                'fetched_at': 1000.0}
        data.update(overrides)
        return data

    def test_fresh_cache_for_same_date_skips_the_network(self):
        with patch('fetch_idle.load_json_file', return_value=self._cached()), \
             patch('fetch_idle.time.time', return_value=1100.0), \
             patch('fetch_idle.fetch_next_game_day') as fetch:
            result = fetch_idle.get_next_game_day('2026-09-29')
        fetch.assert_not_called()
        assert result['games']

    def test_stale_cache_refetches_and_saves(self):
        fresh = {'date': '2026-09-29', 'sport_id': 1, 'games': [_parsed(5)]}
        with patch('fetch_idle.load_json_file', return_value=self._cached()), \
             patch('fetch_idle.time.time', return_value=1000.0 + 7200), \
             patch('fetch_idle.fetch_next_game_day', return_value=fresh), \
             patch('fetch_idle.save_off_results') as save:
            result = fetch_idle.get_next_game_day('2026-09-29')
        assert result['games'][0]['game_pk'] == 5
        save.assert_called_once()
        assert save.call_args[0][1] == 'next_games'
        assert result['from_date'] == '2026-09-29'

    def test_new_from_date_refetches_even_when_fresh(self):
        fresh = {'date': '2026-09-30', 'sport_id': 1, 'games': [_parsed(6)]}
        with patch('fetch_idle.load_json_file', return_value=self._cached()), \
             patch('fetch_idle.time.time', return_value=1100.0), \
             patch('fetch_idle.fetch_next_game_day', return_value=fresh) as fetch, \
             patch('fetch_idle.save_off_results'):
            fetch_idle.get_next_game_day('2026-09-30')
        fetch.assert_called_once()

    def test_failed_refetch_falls_back_to_a_still_future_cache(self):
        with patch('fetch_idle.load_json_file', return_value=self._cached()), \
             patch('fetch_idle.time.time', return_value=1000.0 + 7200), \
             patch('fetch_idle.fetch_next_game_day', return_value=None):
            result = fetch_idle.get_next_game_day('2026-09-29')
        assert result['games']

    def test_failed_refetch_with_a_past_cache_returns_none(self):
        with patch('fetch_idle.load_json_file', return_value=self._cached(date='2026-09-20')), \
             patch('fetch_idle.time.time', return_value=1000.0 + 7200), \
             patch('fetch_idle.fetch_next_game_day', return_value=None):
            assert fetch_idle.get_next_game_day('2026-09-29') is None

    def test_no_cache_and_failed_fetch_returns_none(self):
        with patch('fetch_idle.load_json_file', return_value=None), \
             patch('fetch_idle.fetch_next_game_day', return_value=None):
            assert fetch_idle.get_next_game_day('2026-09-29') is None


# ---------------------------------------------------------------------------
# image_idle helpers
# ---------------------------------------------------------------------------

class TestCountdown:
    NOW = pytz.utc.localize(datetime(2026, 9, 28, 12, 0))

    def test_days_and_hours(self):
        assert image_idle._first_pitch_countdown('2026-09-30T17:00:00Z', self.NOW) == '2D 5H'

    def test_hours_only_inside_a_day(self):
        assert image_idle._first_pitch_countdown('2026-09-28T17:30:00Z', self.NOW) == '5H'

    def test_under_an_hour(self):
        assert image_idle._first_pitch_countdown('2026-09-28T12:40:00Z', self.NOW) == '<1H'

    def test_started_returns_none(self):
        assert image_idle._first_pitch_countdown('2026-09-28T11:00:00Z', self.NOW) is None

    def test_missing_or_garbled_start_returns_none(self):
        assert image_idle._first_pitch_countdown(None, self.NOW) is None
        assert image_idle._first_pitch_countdown('soon', self.NOW) is None


class TestLocalTimeLabel:
    def test_converts_to_the_display_timezone(self):
        assert image_idle._local_time_label('2026-09-29T23:05:00Z', CHI) == '6:05 PM'

    def test_unknown_time_is_tbd(self):
        assert image_idle._local_time_label(None, CHI) == 'TBD'
        assert image_idle._local_time_label('nope', CHI) == 'TBD'


class TestTitle:
    TODAY = datetime(2026, 9, 28).date()

    def test_tomorrow(self):
        assert image_idle._next_games_title('2026-09-29', [_parsed()], self.TODAY) == 'TOMORROW  TUE SEP 29'

    def test_later_date(self):
        assert image_idle._next_games_title('2026-10-02', [_parsed()], self.TODAY) == 'NEXT GAMES  FRI OCT 2'

    def test_today(self):
        assert image_idle._next_games_title('2026-09-28', [_parsed()], self.TODAY) == 'TODAY  MON SEP 28'

    def test_postseason_prefix(self):
        title = image_idle._next_games_title('2026-09-29', [_parsed(gtype='F')], self.TODAY)
        assert title == 'POSTSEASON - TOMORROW  TUE SEP 29'


# ---------------------------------------------------------------------------
# image_idle.draw_next_games_screen
# ---------------------------------------------------------------------------

NOW = CHI.localize(datetime(2026, 9, 28, 14, 0))


def _draw(games, config=None, now=NOW, date='2026-09-29'):
    with patch('image_idle._logo_small', return_value=None):
        return image_idle.draw_next_games_screen(_next_day(games, date), config or {}, now=now)


def _ink(img, box):
    return sum(1 for x in range(box[0], box[2]) for y in range(box[1], box[3])
               if img.getpixel((x, y)) == 0)


class TestDrawNextGamesScreen:
    def test_returns_800x480_one_bit_image(self):
        img = _draw([_parsed()])
        assert img.size == (800, 480)
        assert img.mode == '1'

    def test_default_now_is_used_when_not_injected(self):
        with patch('image_idle._logo_small', return_value=None):
            img = image_idle.draw_next_games_screen(_next_day([_parsed()]), {})
        assert img.size == (800, 480)

    def test_single_game_draws_below_the_header(self):
        img = _draw([_parsed(gtype='D', series={'desc': 'ALDS Game 2', 'result': 'TOR leads 1-0'},
                             away_probable='Gerrit Cole')])
        assert _ink(img, (0, 40, 800, 480)) > 0

    def test_no_games_draws_only_the_header(self):
        img = _draw([])
        assert _ink(img, (0, 0, 800, 28)) > 0
        assert _ink(img, (0, 40, 800, 480)) == 0

    def test_countdown_is_drawn_in_the_header_right_half_only_when_pending(self):
        pending = _draw([_parsed(start='2026-09-29T23:05:00Z')])
        started = _draw([_parsed(start='2026-09-28T13:00:00Z')])
        assert _ink(pending, (500, 0, 800, 26)) > _ink(started, (500, 0, 800, 26))

    def test_two_column_layout_for_a_full_slate(self):
        games = [_parsed(pk=i, away_probable='A Pitcher', home_probable='B Pitcher') for i in range(15)]
        img = _draw(games)
        assert _ink(img, (0, 40, 400, 480)) > 0
        assert _ink(img, (401, 40, 800, 480)) > 0
        assert img.getpixel((400, 200)) == 0  # column divider

    def test_more_than_sixteen_games_are_truncated(self):
        assert _draw([_parsed(pk=i) for i in range(30)]).size == (800, 480)

    def test_dark_mode_inverts(self):
        assert _draw([_parsed()], {'dark_mode': True}).getpixel((0, 300)) == 0
        assert _draw([_parsed()], {'dark_mode': False}).getpixel((0, 300)) == 255

    def test_long_series_text_is_truncated_to_the_cell(self):
        long_series = {'desc': 'X' * 200, 'result': 'Y' * 200}
        img = _draw([_parsed(gtype='D', series=long_series)])
        assert _ink(img, (0, 40, 800, 480)) > 0

    def test_logos_are_pasted_when_available(self):
        logo = MagicMock()
        logo.width = logo.height = 20
        with patch('image_idle._logo_small', return_value=None) as none_logo:
            without = image_idle.draw_next_games_screen(_next_day([_parsed()]), {}, now=NOW)
        assert none_logo.called
        from PIL import Image
        solid = Image.new('1', (20, 20), 0)
        with patch('image_idle._logo_small', return_value=solid):
            with_logo = image_idle.draw_next_games_screen(_next_day([_parsed()]), {}, now=NOW)
        assert _ink(with_logo, (0, 28, 800, 480)) > _ink(without, (0, 28, 800, 480))

    def test_time_is_skipped_when_it_would_overlap_the_matchup(self):
        narrow = image_idle._draw_next_game_cell
        from PIL import Image, ImageDraw
        img = Image.new('1', (800, 480), 255)
        with patch('image_idle._logo_small', return_value=None):
            narrow(img, ImageDraw.Draw(img), 0, 30, 120, 100, _parsed(), CHI)
        assert img.size == (800, 480)


# ---------------------------------------------------------------------------
# main: next-games rendering and the idle rotation
# ---------------------------------------------------------------------------

def _config(**overrides):
    cfg = {'night_mode': False, 'timezone': 'America/Chicago'}
    cfg.update(overrides)
    return cfg


class TestIdleSportPriority:
    def test_aaa_uses_triple_a(self):
        assert main._idle_sport_priority(_config(league_mode='aaa')) == [11]

    def test_priority_list_is_used(self):
        assert main._idle_sport_priority(_config(sport_id_priority=[1, 8])) == [1, 8]

    def test_falls_back_to_sport_id(self):
        assert main._idle_sport_priority(_config(sport_id=8)) == [8]
        assert main._idle_sport_priority(_config()) == [1]


class TestRenderNextGames:
    def test_returns_the_rendered_image(self):
        with patch('fetch_idle.get_next_game_day', return_value=_next_day([_parsed()])) as get, \
             patch('image_idle.draw_next_games_screen', return_value='IMG') as draw:
            assert main._render_next_games(_config(), {}) == 'IMG'
        assert get.call_args[0][1] == [1]
        draw.assert_called_once()

    def test_no_schedule_returns_none(self):
        with patch('fetch_idle.get_next_game_day', return_value=None):
            assert main._render_next_games(_config(), {}) is None
        with patch('fetch_idle.get_next_game_day', return_value={'games': []}):
            assert main._render_next_games(_config(), {}) is None

    def test_errors_are_swallowed(self):
        with patch('fetch_idle.get_next_game_day', side_effect=RuntimeError('boom')):
            assert main._render_next_games(_config(), {}) is None


def _run_idle(tmp_path, minute, config=None, *, next_games='NEXT', tx=None,
              quadrant=None, history=(None, []), bracket=None, date=(2026, 9, 28)):
    """Run _show_idle_screen at a given minute; returns which views were drawn."""
    from PIL import Image
    calls = []

    def _mark(name):
        def _f(*a, **k):
            calls.append(name)
            return Image.new('1', (800, 480), 255)
        return _f

    def _load(name):
        return {'transactions.json': {'transactions': tx or [], 'fetched_at': 9e12},
                'team_quadrant.json': quadrant,
                'playoff_bracket.json': {'series': bracket} if bracket else None,
                'teams.json': {'team_abbreviation': {}}}.get(name)

    fake_now = datetime(*date, 12, minute)
    with patch('main.datetime') as dt, \
         patch('main._REPO_ROOT', str(tmp_path)), \
         patch('main.load_json_file', side_effect=_load), \
         patch('main._render_next_games',
               side_effect=lambda *a: (calls.append('next') or Image.new('1', (800, 480), 255))
               if next_games else None), \
         patch('main.draw_idle_screen', side_effect=_mark('transactions')), \
         patch('main.draw_history_screen', side_effect=_mark('history')), \
         patch('quadrant_view.render_quadrant_view', side_effect=_mark('quadrant')), \
         patch('fetch_idle.fetch_this_day_in_history', return_value=history), \
         patch('standings.fetch_transactions', return_value=None), \
         patch('main.send_to_display'), \
         patch('refresh_tracker.needs_full_refresh', return_value=True):
        dt.now.return_value = fake_now
        main._show_idle_screen(config or _config())
    return calls


class TestIdleRotation:
    def test_block_0_shows_next_games(self, tmp_path):
        assert _run_idle(tmp_path, 5) == ['next']

    def test_block_1_shows_transactions(self, tmp_path):
        assert _run_idle(tmp_path, 20, tx=[{'player_name': 'A'}]) == ['transactions']

    def test_block_2_shows_the_quadrant(self, tmp_path):
        assert _run_idle(tmp_path, 35, quadrant={'x': 1}) == ['quadrant']

    def test_block_3_shows_history(self, tmp_path):
        assert _run_idle(tmp_path, 50, history=(2019, [{'g': 1}])) == ['history']

    def test_schedule_rotation_can_be_disabled(self, tmp_path):
        calls = _run_idle(tmp_path, 5, _config(idle_schedule_rotation=False),
                          tx=[{'player_name': 'A'}])
        assert calls == ['transactions']

    def test_block_0_without_a_schedule_falls_back_to_transactions(self, tmp_path):
        assert _run_idle(tmp_path, 5, next_games=None, tx=[{'player_name': 'A'}]) == ['transactions']

    def test_history_with_no_games_falls_back(self, tmp_path):
        assert _run_idle(tmp_path, 50, tx=[{'player_name': 'A'}]) == ['transactions']

    def test_history_error_falls_back(self, tmp_path):
        with patch('fetch_idle.fetch_this_day_in_history', side_effect=RuntimeError('x')):
            pass
        calls = _run_idle(tmp_path, 50, history=(2019, [{'g': 1}]), tx=[{'player_name': 'A'}])
        assert calls == ['history']

    def test_quadrant_without_data_falls_back(self, tmp_path):
        assert _run_idle(tmp_path, 35, quadrant=None, tx=[{'player_name': 'A'}]) == ['transactions']

    def test_empty_transactions_prefer_the_schedule_over_a_blank_screen(self, tmp_path):
        assert _run_idle(tmp_path, 20, tx=[]) == ['next']

    def test_empty_transactions_and_no_schedule_still_draw_something(self, tmp_path):
        assert _run_idle(tmp_path, 20, next_games=None, tx=[]) == ['transactions']

    def test_empty_transactions_respect_the_schedule_toggle(self, tmp_path):
        calls = _run_idle(tmp_path, 20, _config(idle_schedule_rotation=False), tx=[])
        assert calls == ['transactions']


class TestPostseasonIdle:
    SERIES = [{'id': 'ALDS1'}]
    OCT = (2026, 10, 9)

    def test_transactions_slot_shows_next_games(self, tmp_path):
        calls = _run_idle(tmp_path, 20, tx=[{'player_name': 'A'}], bracket=self.SERIES, date=self.OCT)
        assert calls == ['next']

    def test_quadrant_slot_shows_next_games(self, tmp_path):
        calls = _run_idle(tmp_path, 35, quadrant={'x': 1}, bracket=self.SERIES, date=self.OCT)
        assert calls == ['next']

    def test_history_keeps_its_slot(self, tmp_path):
        calls = _run_idle(tmp_path, 50, history=(2019, [{'g': 1}]), bracket=self.SERIES, date=self.OCT)
        assert calls == ['history']

    def test_ignores_the_schedule_toggle(self, tmp_path):
        calls = _run_idle(tmp_path, 20, _config(idle_schedule_rotation=False),
                          tx=[{'player_name': 'A'}], bracket=self.SERIES, date=self.OCT)
        assert calls == ['next']

    def test_no_schedule_still_falls_back_to_transactions(self, tmp_path):
        calls = _run_idle(tmp_path, 20, next_games=None, tx=[{'player_name': 'A'}],
                          bracket=self.SERIES, date=self.OCT)
        assert calls == ['transactions']

    def test_regular_season_late_september_unchanged(self, tmp_path):
        calls = _run_idle(tmp_path, 20, tx=[{'player_name': 'A'}], bracket=None,
                          date=(2026, 9, 28))
        assert calls == ['transactions']

    def test_bracket_outside_window_is_ignored(self, tmp_path):
        calls = _run_idle(tmp_path, 20, tx=[{'player_name': 'A'}], bracket=self.SERIES,
                          date=(2026, 7, 4))
        assert calls == ['transactions']
