"""Tests for src/timelapse.py — the game-day GIF/MP4 timelapse generator.

Extracted from the old src/scoreboard_generate.py monolith (removed in this
same change). Covers the pure state-reconstruction functions with synthetic
timelines/plays, _fetch_game_timeline with a synthetic live-feed fixture
(mocked requests.get), and generate_gif's orchestration with every external
call mocked (network, file I/O, rendering).
"""
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import pytz

import timelapse as tl_mod
from timelapse import (
    _any_game_active,
    _fetch_game_timeline,
    _game_state_at_time,
    _inning_runs_at_time,
    _ordinal,
    _parse_mlb_time,
    generate_gif,
)

UTC = pytz.utc


def _dt(hour, minute=0, day=20):
    """Dt."""
    return UTC.localize(datetime(2026, 6, day, hour, minute, 0))


# ---------------------------------------------------------------------------
# _ordinal / _parse_mlb_time
# ---------------------------------------------------------------------------

def test_ordinal_known_innings():
    """Ordinal known innings."""
    assert _ordinal(1) == '1st'
    assert _ordinal(9) == '9th'
    assert _ordinal('5') == '5th'


def test_ordinal_unknown_falls_back_to_th_suffix():
    """Ordinal unknown falls back to th suffix."""
    assert _ordinal(23) == '23th'


def test_ordinal_invalid_returns_none():
    """Ordinal invalid returns none."""
    assert _ordinal(None) is None
    assert _ordinal('not-a-number') is None


def test_parse_mlb_time_with_fractional_seconds():
    """Parse mlb time with fractional seconds."""
    result = _parse_mlb_time('2026-06-20T23:05:00.123Z')
    assert result == _dt(23, 5).replace(microsecond=123000)


def test_parse_mlb_time_without_fractional_seconds():
    """Parse mlb time without fractional seconds."""
    result = _parse_mlb_time('2026-06-20T23:05:00Z')
    assert result == _dt(23, 5)


def test_parse_mlb_time_invalid_raises():
    """Parse mlb time invalid raises."""
    with pytest.raises(ValueError):
        _parse_mlb_time('not-a-timestamp')


# ---------------------------------------------------------------------------
# _fetch_game_timeline
# ---------------------------------------------------------------------------

def _play(inning=1, half='top', complete=True, start='2026-06-20T23:00:00Z',
          end='2026-06-20T23:03:00Z', away_score=0, home_score=0, outs_after=0,
          batter_id=1, batter_name='Mookie Betts', pitcher_name='Logan Webb',
          event='Strikeout', event_type='strikeout', description='Betts strikes out.',
          events=None, review=None):
    """Play."""
    ev = events if events is not None else []
    return {
        'about': {
            'inning': inning, 'halfInning': half, 'isComplete': complete,
            'startTime': start, 'endTime': end, 'outs': max(0, outs_after - 1),
        },
        'result': {
            'event': event, 'eventType': event_type, 'description': description,
            'awayScore': away_score, 'homeScore': home_score,
        },
        'matchup': {
            'batter': {'id': batter_id, 'fullName': batter_name},
            'pitcher': {'fullName': pitcher_name},
            'postOnFirst': None, 'postOnSecond': None, 'postOnThird': None,
        },
        'count': {'outs': outs_after},
        'playEvents': ev,
    }


def _pitch_event(time='2026-06-20T22:59:30Z', balls=1, strikes=1, outs=0,
                  challenge_team=None, in_progress=False, overturned=False):
    """Pitch event."""
    ev = {
        'type': 'pitch', 'startTime': time,
        'count': {'balls': balls, 'strikes': strikes, 'outs': outs},
    }
    if challenge_team is not None:
        ev['reviewDetails'] = {
            'inProgress': in_progress, 'isOverturned': overturned,
            'challengeTeamId': challenge_team,
        }
    return ev


def _live_feed(all_plays=None):
    """Live feed."""
    return {
        'gameData': {
            'datetime': {'dateTime': '2026-06-20T22:35:00Z'},
            'teams': {'away': {'id': 111}, 'home': {'id': 147}},
        },
        'liveData': {
            'boxscore': {
                'teams': {
                    'away': {
                        'battingOrder': [1],
                        'players': {'ID1': {'battingOrder': '100', 'person': {'fullName': 'Mookie Betts'}}},
                    },
                    'home': {
                        'battingOrder': [5],
                        'players': {'ID5': {'battingOrder': '100', 'person': {'fullName': 'Logan Webb'}}},
                    },
                },
            },
            'plays': {'allPlays': all_plays if all_plays is not None else []},
        },
    }


def _mock_requests_get(live_feed, wp_data=None):
    """Mock requests get."""
    def _get(url, timeout=None):
        """Get."""
        resp = MagicMock()
        if 'winProbability' in url:
            resp.json.return_value = wp_data or []
        else:
            resp.json.return_value = live_feed
        return resp
    return _get


def test_fetch_game_timeline_basic_completed_play():
    """Fetch game timeline basic completed play."""
    feed = _live_feed(all_plays=[
        _play(inning=1, half='top', away_score=1, home_score=0, outs_after=3,
              events=[_pitch_event()]),
    ])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert len(tl['plays']) == 1
    assert tl['plays'][0]['away_score'] == 1
    assert len(tl['pitch_events']) == 1
    assert tl['scheduled_start_utc'] == _dt(22, 35)
    assert tl['last_play_utc'] == _dt(23, 3)


def test_fetch_game_timeline_skips_incomplete_plays_for_timeline_but_keeps_pitch_events():
    """Fetch game timeline skips incomplete plays for timeline but keeps pitch events."""
    feed = _live_feed(all_plays=[
        _play(complete=False, events=[_pitch_event()]),
    ])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert tl['plays'] == []
    assert len(tl['pitch_events']) == 1


def test_fetch_game_timeline_tracks_abs_challenges():
    """Fetch game timeline tracks abs challenges."""
    feed = _live_feed(all_plays=[
        _play(outs_after=1, events=[
            _pitch_event(challenge_team=111, in_progress=False, overturned=False),
        ]),
    ])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert tl['challenge_events'][0]['away_remaining'] == 1  # max(2) - 1 used


def test_fetch_game_timeline_ignores_in_progress_and_overturned_challenges():
    """Fetch game timeline ignores in progress and overturned challenges."""
    feed = _live_feed(all_plays=[
        _play(outs_after=1, events=[
            _pitch_event(challenge_team=111, in_progress=True),
            _pitch_event(challenge_team=147, overturned=True),
        ]),
    ])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert tl['challenge_events'] == []


def test_fetch_game_timeline_win_probability_scaled_from_fraction():
    """Fetch game timeline win probability scaled from fraction."""
    feed = _live_feed(all_plays=[_play(outs_after=1)])
    wp = [{'atBatIndex': 0, 'awayTeamWinProbability': 0.55, 'homeTeamWinProbability': 0.45,
           'result': {'event': 'Groundout', 'eventType': 'field_out', 'description': 'ground out'}}]
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed, wp)):
        tl = _fetch_game_timeline(12345)
    assert tl['wp_events'][0]['away_wp'] == pytest.approx(55.0)
    assert tl['wp_events'][0]['home_wp'] == pytest.approx(45.0)
    assert tl['wp_events'][0]['last_play'] == 'Groundout'


def test_fetch_game_timeline_win_probability_already_percent():
    """Fetch game timeline win probability already percent."""
    feed = _live_feed(all_plays=[_play(outs_after=1)])
    wp = [{'atBatIndex': 0, 'awayTeamWinProbability': 55.0, 'homeTeamWinProbability': 45.0,
           'result': {'event': 'Groundout', 'eventType': 'field_out'}}]
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed, wp)):
        tl = _fetch_game_timeline(12345)
    assert tl['wp_events'][0]['away_wp'] == 55.0


def test_fetch_game_timeline_skips_substitution_events_for_last_play():
    """Fetch game timeline skips substitution events for last play."""
    feed = _live_feed(all_plays=[
        _play(outs_after=0, event='Pitching Substitution', event_type='substitution'),
        _play(outs_after=1, event='Strikeout', event_type='strikeout',
              start='2026-06-20T23:04:00Z', end='2026-06-20T23:06:00Z'),
    ])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert tl['wp_events'][-1]['last_play'] == 'Strikeout'


def test_fetch_game_timeline_live_feed_failure_propagates():
    """Unlike the winProbability sub-fetch (caught and ignored), a failure
    fetching the main live feed itself is not swallowed."""
    with patch('timelapse.requests.get', side_effect=ConnectionError('network down')):
        with pytest.raises(ConnectionError):
            _fetch_game_timeline(12345)


def test_fetch_game_timeline_next_batters_after_inning_break():
    """Fetch game timeline next batters after inning break."""
    feed = _live_feed(all_plays=[
        _play(inning=1, half='top', outs_after=3,
              start='2026-06-20T23:00:00Z', end='2026-06-20T23:05:00Z',
              events=[_pitch_event(time='2026-06-20T23:06:00Z')]),
    ])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert len(tl['next_batters_events']) == 1
    assert tl['next_batters_events'][0]['next_batter_1'] == 'Logan Webb'  # home team bats in bottom


def test_fetch_game_timeline_no_scheduled_start():
    """Fetch game timeline no scheduled start."""
    feed = _live_feed()
    feed['gameData']['datetime'] = {}
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert tl['scheduled_start_utc'] is None


def test_fetch_game_timeline_malformed_start_time_ignored():
    """Fetch game timeline malformed start time ignored."""
    feed = _live_feed()
    feed['gameData']['datetime'] = {'dateTime': 'garbage'}
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert tl['scheduled_start_utc'] is None


def test_fetch_game_timeline_play_missing_start_or_end_time_skipped():
    """Fetch game timeline play missing start or end time skipped."""
    play_no_end = _play()
    play_no_end['about']['endTime'] = ''
    feed = _live_feed(all_plays=[play_no_end])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert tl['plays'] == []


def test_fetch_game_timeline_first_actual_pitch_fallback_to_first_completed_play():
    """Fetch game timeline first actual pitch fallback to first completed play."""
    feed = _live_feed(all_plays=[_play(outs_after=1)])  # no pitch events at all
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert tl['first_actual_pitch_utc'] == tl['plays'][0]['end_time']


# ---------------------------------------------------------------------------
# _inning_runs_at_time
# ---------------------------------------------------------------------------

def _completed_play(inning, half, away_score, home_score, end_time):
    """Completed play."""
    return {'end_time': end_time, 'inning': inning, 'half_inning': half,
            'away_score': away_score, 'home_score': home_score}


def test_inning_runs_at_time_empty_plays():
    """Inning runs at time empty plays."""
    assert _inning_runs_at_time([], _dt(23)) == ([], [])


def test_inning_runs_at_time_top_only_no_bottom_yet():
    """Inning runs at time top only no bottom yet."""
    plays = [_completed_play(1, 'top', 1, 0, _dt(23, 5))]
    away, home = _inning_runs_at_time(plays, _dt(23, 10))
    assert away == [1]
    assert home == [None]


def test_inning_runs_at_time_full_inning():
    """Inning runs at time full inning."""
    plays = [
        _completed_play(1, 'top', 1, 0, _dt(23, 5)),
        _completed_play(1, 'bottom', 1, 2, _dt(23, 15)),
    ]
    away, home = _inning_runs_at_time(plays, _dt(23, 20))
    assert away == [1]
    assert home == [2]


def test_inning_runs_at_time_ignores_plays_after_target():
    """Inning runs at time ignores plays after target."""
    plays = [
        _completed_play(1, 'top', 1, 0, _dt(23, 5)),
        _completed_play(2, 'top', 3, 0, _dt(23, 40)),
    ]
    away, home = _inning_runs_at_time(plays, _dt(23, 10))
    assert away == [1]


def test_inning_runs_at_time_stops_at_first_missing_top():
    """Inning runs at time stops at first missing top."""
    # If inning 2's top half is missing but inning 3's exists, stop at 2.
    plays = [
        _completed_play(1, 'top', 1, 0, _dt(23, 5)),
        _completed_play(1, 'bottom', 1, 0, _dt(23, 10)),
        _completed_play(3, 'top', 2, 0, _dt(23, 40)),
    ]
    away, home = _inning_runs_at_time(plays, _dt(23, 45))
    assert away == [1]
    assert home == [0]


# ---------------------------------------------------------------------------
# _game_state_at_time
# ---------------------------------------------------------------------------

def _base_game(**overrides):
    """Base game."""
    g = {'game_pk': 1, 'detailed_state': 'Scheduled', 'away_team_id': 111, 'home_team_id': 147}
    g.update(overrides)
    return g


def _tl(**overrides):
    """Tl."""
    base = {
        'scheduled_start_utc': _dt(23),
        'first_pitch_utc': _dt(23, 5),
        'first_actual_pitch_utc': _dt(23, 5),
        'last_play_utc': _dt(23, 30),
        'plays': [],
        'pitch_events': [],
        'wp_events': [],
        'challenge_events': [],
        'next_batters_events': [],
    }
    base.update(overrides)
    return base


def test_game_state_before_first_pitch_is_scheduled():
    """Game state before first pitch is scheduled."""
    state = _game_state_at_time(_base_game(), _tl(), _dt(22, 50))
    assert state['detailed_state'] == 'Scheduled'
    assert state['away_runs'] is None


def test_game_state_after_last_play_buffer_is_final():
    """Game state after last play buffer is final."""
    plays = [_completed_play(9, 'bottom', 5, 3, _dt(23, 30))]
    state = _game_state_at_time(_base_game(), _tl(plays=plays), _dt(23, 40))
    assert state['detailed_state'] == 'Final'
    assert state['away_runs'] == 5
    assert state['home_runs'] == 3


def test_game_state_final_keeps_last_play_from_wp_events():
    """Game state final keeps last play from wp events."""
    plays = [_completed_play(9, 'bottom', 5, 3, _dt(23, 30))]
    wp_events = [{'time': _dt(23, 30), 'last_play': 'Groundout', 'last_play_inn': 9,
                  'last_play_top': False, 'last_play_desc': 'ground out to short'}]
    state = _game_state_at_time(_base_game(), _tl(plays=plays, wp_events=wp_events), _dt(23, 40))
    assert state['last_play'] == 'Groundout'


def test_game_state_terminal_status_preserved_without_plays():
    """Game state terminal status preserved without plays."""
    state = _game_state_at_time(_base_game(detailed_state='Postponed'), _tl(plays=[]), _dt(23, 10))
    assert state['detailed_state'] == 'Postponed'


def test_game_state_between_plays_inning_break_middle():
    """Game state between plays inning break middle."""
    plays = [_completed_play(1, 'top', 1, 0, _dt(23, 10))]
    plays[0]['outs_after'] = 3
    plays[0]['pitcher'] = 'Logan Webb'
    tl = _tl(plays=plays, last_play_utc=_dt(23, 10), pitch_events=[])
    state = _game_state_at_time(_base_game(), tl, _dt(23, 12))
    assert state['detailed_state'] == 'In Progress'
    assert state['inningState'] == 'Middle'
    assert state['num_of_outs'] == 3


def test_game_state_between_plays_inning_continues_bottom():
    """Game state between plays inning continues bottom."""
    plays = [_completed_play(1, 'top', 1, 0, _dt(23, 10))]
    plays[0]['outs_after'] = 2
    plays[0]['pitcher'] = 'Logan Webb'
    tl = _tl(plays=plays, last_play_utc=_dt(23, 10))
    state = _game_state_at_time(_base_game(), tl, _dt(23, 12))
    assert state['inningState'] == 'Top'


def test_game_state_mid_at_bat_uses_pitch_event():
    """Game state mid at bat uses pitch event."""
    pitch_events = [{'time': _dt(23, 11), 'balls': 2, 'strikes': 1, 'outs': 0,
                      'inning': 1, 'half_inning': 'top', 'away_score': 0, 'home_score': 0,
                      'pitcher': 'Logan Webb', 'batter': 'Mookie Betts',
                      'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None}]
    tl = _tl(pitch_events=pitch_events, last_play_utc=_dt(23, 30))
    state = _game_state_at_time(_base_game(), tl, _dt(23, 11))
    assert state['balls'] == 2
    assert state['strikes'] == 1
    assert state['current_hitter'] == 'Mookie Betts'


def test_game_state_mid_at_bat_includes_win_probability_from_wp_events():
    """Game state mid at bat includes win probability from wp events."""
    pitch_events = [{'time': _dt(23, 11), 'balls': 2, 'strikes': 1, 'outs': 0,
                      'inning': 1, 'half_inning': 'top', 'away_score': 0, 'home_score': 0,
                      'pitcher': 'Logan Webb', 'batter': 'Mookie Betts',
                      'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None}]
    wp_events = [
        {'time': _dt(23, 10), 'away_wp': 60.0, 'home_wp': 40.0, 'last_play': 'Single',
         'last_play_inn': 1, 'last_play_top': True, 'last_play_desc': 'a single'},
        {'time': _dt(23, 20), 'away_wp': 65.0, 'home_wp': 35.0, 'last_play': 'Double',
         'last_play_inn': 1, 'last_play_top': True, 'last_play_desc': 'a double'},
    ]
    tl = _tl(pitch_events=pitch_events, wp_events=wp_events, last_play_utc=_dt(23, 30))
    state = _game_state_at_time(_base_game(), tl, _dt(23, 11))
    assert state['away_win_probability'] == 60.0  # the later wp_event (23:20) is still in the future
    assert state['last_play'] == 'Single'


def test_game_state_no_pitch_events_or_plays_is_scheduled():
    """Game state no pitch events or plays is scheduled."""
    tl = _tl(first_actual_pitch_utc=_dt(22, 50), last_play_utc=_dt(23, 30))
    state = _game_state_at_time(_base_game(), tl, _dt(22, 55))
    assert state['detailed_state'] == 'Scheduled'


def test_game_state_abs_challenges_default_full_allotment():
    """Game state abs challenges default full allotment."""
    pitch_events = [{'time': _dt(23, 11), 'balls': 0, 'strikes': 0, 'outs': 0,
                      'inning': 1, 'half_inning': 'top', 'away_score': 0, 'home_score': 0,
                      'pitcher': '', 'batter': '', 'runner_on_first': None,
                      'runner_on_second': None, 'runner_on_third': None}]
    tl = _tl(pitch_events=pitch_events, last_play_utc=_dt(23, 30))
    state = _game_state_at_time(_base_game(), tl, _dt(23, 11))
    assert state['away_challenges_remaining'] == 2
    assert state['home_challenges_remaining'] == 2


def test_game_state_abs_challenges_reflect_usage():
    """Game state abs challenges reflect usage."""
    pitch_events = [{'time': _dt(23, 11), 'balls': 0, 'strikes': 0, 'outs': 0,
                      'inning': 1, 'half_inning': 'top', 'away_score': 0, 'home_score': 0,
                      'pitcher': '', 'batter': '', 'runner_on_first': None,
                      'runner_on_second': None, 'runner_on_third': None}]
    challenge_events = [{'time': _dt(23, 10), 'away_remaining': 1, 'home_remaining': 2}]
    tl = _tl(pitch_events=pitch_events, challenge_events=challenge_events, last_play_utc=_dt(23, 30))
    state = _game_state_at_time(_base_game(), tl, _dt(23, 11))
    assert state['away_challenges_remaining'] == 1


def test_game_state_walk_off_cleared_for_in_progress_frames():
    """walk_off bleeds from base_game's Final state; _game_state_at_time must
    clear it so live frames don't show 'WALKOFF' in the header before the game ends."""
    pitch_events = [{'time': _dt(23, 11), 'balls': 1, 'strikes': 0, 'outs': 0,
                      'inning': 1, 'half_inning': 'top', 'away_score': 0, 'home_score': 0,
                      'pitcher': '', 'batter': '', 'runner_on_first': None,
                      'runner_on_second': None, 'runner_on_third': None,
                      'at_bat_pitch_count': 1, 'last_pitch_speed': None,
                      'last_pitch_type': '', 'last_strike_call': '', 'strike_calls': []}]
    tl = _tl(pitch_events=pitch_events, last_play_utc=_dt(23, 30))
    base = _base_game(walk_off=True)  # simulates a base_game from a completed walk-off
    state = _game_state_at_time(base, tl, _dt(23, 11))
    assert state['detailed_state'] == 'In Progress'
    assert state['walk_off'] is False


def test_game_state_walk_off_cleared_for_pre_game_frames():
    """walk_off is also cleared when the reconstructed state is Scheduled
    (before the first pitch)."""
    tl = _tl(first_actual_pitch_utc=_dt(23, 5))
    base = _base_game(walk_off=True)
    state = _game_state_at_time(base, tl, _dt(22, 50))
    assert state['detailed_state'] == 'Scheduled'
    assert state['walk_off'] is False


def test_game_state_save_situation_computed_from_reconstructed_scores():
    """save_situation must be recomputed from the reconstructed inning/scores,
    not inherited from base_game (which always has it False for Final games)."""
    pitch_events = [{'time': _dt(23, 11), 'balls': 1, 'strikes': 0, 'outs': 0,
                      'inning': 8, 'half_inning': 'top', 'away_score': 3, 'home_score': 5,
                      'pitcher': '', 'batter': '', 'runner_on_first': None,
                      'runner_on_second': None, 'runner_on_third': None,
                      'at_bat_pitch_count': 1, 'last_pitch_speed': None,
                      'last_pitch_type': '', 'last_strike_call': '', 'strike_calls': []}]
    tl = _tl(pitch_events=pitch_events, last_play_utc=_dt(23, 30))
    state = _game_state_at_time(_base_game(save_situation=False), tl, _dt(23, 11))
    assert state['detailed_state'] == 'In Progress'
    # inning 8, |5 - 3| = 2 → save situation
    assert state['save_situation'] is True


def test_game_state_save_situation_false_when_run_diff_too_large():
    """save_situation stays False when the run differential is outside 1-3."""
    pitch_events = [{'time': _dt(23, 11), 'balls': 0, 'strikes': 0, 'outs': 0,
                      'inning': 8, 'half_inning': 'top', 'away_score': 0, 'home_score': 5,
                      'pitcher': '', 'batter': '', 'runner_on_first': None,
                      'runner_on_second': None, 'runner_on_third': None,
                      'at_bat_pitch_count': 0, 'last_pitch_speed': None,
                      'last_pitch_type': '', 'last_strike_call': '', 'strike_calls': []}]
    tl = _tl(pitch_events=pitch_events, last_play_utc=_dt(23, 30))
    state = _game_state_at_time(_base_game(), tl, _dt(23, 11))
    assert state['save_situation'] is False


def test_game_state_pitch_details_copied_from_last_pitch_event():
    """Pitch speed, type, at-bat count, and strike calls are copied from the
    most recent pitch event so the wide box can display them."""
    pitch_events = [{'time': _dt(23, 11), 'balls': 1, 'strikes': 1, 'outs': 0,
                      'inning': 5, 'half_inning': 'top', 'away_score': 2, 'home_score': 1,
                      'pitcher': 'A', 'batter': 'B',
                      'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None,
                      'at_bat_pitch_count': 3,
                      'last_pitch_speed': 94.5,
                      'last_pitch_type': 'SL',
                      'last_strike_call': 'S',
                      'strike_calls': ['C', 'S']}]
    tl = _tl(pitch_events=pitch_events, last_play_utc=_dt(23, 30))
    state = _game_state_at_time(_base_game(), tl, _dt(23, 11))
    assert state['at_bat_pitch_count'] == 3
    assert state['last_pitch_speed'] == 94.5
    assert state['last_pitch_type'] == 'SL'
    assert state['last_strike_call'] == 'S'
    assert state['strike_calls'] == ['C', 'S']


def test_game_state_pitch_details_cleared_between_plays():
    """Between at-bats the pitch detail fields are reset to empty/zero."""
    play = _completed_play(3, 'top', 1, 0, _dt(23, 10))
    play['outs_after'] = 2
    play['pitcher'] = 'Pitcher'
    tl = _tl(plays=[play], last_play_utc=_dt(23, 10))
    state = _game_state_at_time(_base_game(), tl, _dt(23, 12))
    assert state['at_bat_pitch_count'] == 0
    assert state['last_pitch_speed'] is None
    assert state['last_pitch_type'] == ''
    assert state['strike_calls'] == []


def test_game_state_abs_challenge_max_scales_for_extra_innings():
    """ABS challenge max grows by 1 per extra inning (10th=3, 11th=4, …)."""
    pitch_events = [{'time': _dt(23, 11), 'balls': 0, 'strikes': 0, 'outs': 0,
                      'inning': 10, 'half_inning': 'top', 'away_score': 3, 'home_score': 3,
                      'pitcher': '', 'batter': '', 'runner_on_first': None,
                      'runner_on_second': None, 'runner_on_third': None,
                      'at_bat_pitch_count': 0, 'last_pitch_speed': None,
                      'last_pitch_type': '', 'last_strike_call': '', 'strike_calls': []}]
    tl = _tl(pitch_events=pitch_events, last_play_utc=_dt(23, 30))
    state = _game_state_at_time(_base_game(), tl, _dt(23, 11))
    assert state['current_inning'] == 10
    assert state['away_challenges_remaining'] == 3   # 2 base + 1 extra inning
    assert state['home_challenges_remaining'] == 3


def test_game_state_next_batters_shown_during_break():
    """Game state next batters shown during break."""
    plays = [_completed_play(1, 'top', 1, 0, _dt(23, 10))]
    plays[0]['outs_after'] = 3
    plays[0]['pitcher'] = 'Logan Webb'
    next_batters_events = [{'time': _dt(23, 10), 'next_batter_1': 'A', 'next_batter_2': 'B',
                             'next_batter_3': 'C', 'next_pitcher': 'D'}]
    tl = _tl(plays=plays, next_batters_events=next_batters_events, last_play_utc=_dt(23, 10))
    state = _game_state_at_time(_base_game(), tl, _dt(23, 12))
    assert state['next_batter_1'] == 'A'
    assert state['next_pitcher'] == 'D'


# ---------------------------------------------------------------------------
# _any_game_active
# ---------------------------------------------------------------------------

def test_any_game_active_true_within_window():
    """Any game active true within window."""
    timelines = {'1': {'pitch_events': [{'balls': 1, 'strikes': 0, 'time': _dt(23)}],
                        'plays': [], 'last_play_utc': None, 'first_pitch_utc': None}}
    assert _any_game_active(timelines, _dt(23, 5)) is True


def test_any_game_active_false_before_start():
    """Any game active false before start."""
    timelines = {'1': {'pitch_events': [{'balls': 1, 'strikes': 0, 'time': _dt(23)}],
                        'plays': [], 'last_play_utc': None, 'first_pitch_utc': None}}
    assert _any_game_active(timelines, _dt(22)) is False


def test_any_game_active_false_after_end_buffer():
    """Any game active false after end buffer."""
    timelines = {'1': {'pitch_events': [{'balls': 1, 'strikes': 0, 'time': _dt(23)}],
                        'plays': [], 'last_play_utc': _dt(23, 30), 'first_pitch_utc': None}}
    assert _any_game_active(timelines, _dt(23, 40)) is False


def test_any_game_active_falls_back_to_first_completed_play():
    """Any game active falls back to first completed play."""
    timelines = {'1': {'pitch_events': [], 'plays': [{'end_time': _dt(23)}],
                        'last_play_utc': None, 'first_pitch_utc': None}}
    assert _any_game_active(timelines, _dt(23, 5)) is True


def test_any_game_active_no_data_at_all():
    """Any game active no data at all."""
    timelines = {'1': {'pitch_events': [], 'plays': [], 'last_play_utc': None, 'first_pitch_utc': None}}
    assert _any_game_active(timelines, _dt(23)) is False


def test_any_game_active_empty_dict():
    """Any game active empty dict."""
    assert _any_game_active({}, _dt(23)) is False


# ---------------------------------------------------------------------------
# generate_gif — orchestration, everything external mocked
# ---------------------------------------------------------------------------

@pytest.fixture
def _no_games(monkeypatch):
    """No games."""
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file', MagicMock(return_value={'games': []}))


def test_generate_gif_no_games_found_returns_early(_no_games, capsys):
    """Generate gif no games found returns early."""
    generate_gif('2026-06-20', None, None, '/tmp/out.gif', 1, 300, 1, {})
    assert 'No games found' in capsys.readouterr().out


def test_generate_gif_no_timeline_data_returns_early(monkeypatch, capsys):
    """Generate gif no timeline data returns early."""
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file',
                         lambda f: {'games': [{'game_pk': 1}]} if 'games' in f else {})
    monkeypatch.setattr(tl_mod, '_lookup_stadium', lambda *a, **k: None)
    monkeypatch.setattr(tl_mod, '_fetch_game_timeline', MagicMock(side_effect=Exception('boom')))
    with patch('standings.get_standings'):
        generate_gif('2026-06-20', None, None, '/tmp/out.gif', 1, 300, 1, {'timezone': 'America/Chicago'})
    assert 'No timeline data fetched' in capsys.readouterr().out


def test_generate_gif_cannot_determine_window_without_hints(monkeypatch, capsys):
    """Generate gif cannot determine window without hints."""
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file',
                         lambda f: {'games': [{'game_pk': 1}]} if 'games' in f else {})
    monkeypatch.setattr(tl_mod, '_lookup_stadium', lambda *a, **k: None)
    monkeypatch.setattr(tl_mod, '_fetch_game_timeline', lambda pk: {
        'first_actual_pitch_utc': None, 'first_pitch_utc': None, 'scheduled_start_utc': None,
        'last_play_utc': None,
    })
    with patch('standings.get_standings'):
        generate_gif('2026-06-20', None, None, '/tmp/out.gif', 1, 300, 1, {'timezone': 'America/Chicago'})
    assert 'Cannot determine start time' in capsys.readouterr().out


def test_generate_gif_renders_frames_and_saves(monkeypatch, tmp_path, capsys):
    """Generate gif renders frames and saves."""
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file',
                         lambda f: {'games': [{'game_pk': 1, 'venue': 'Fenway Park', 'game_date': '2026-06-20'}]}
                         if 'games' in f else {'team_abbreviation': {}})
    monkeypatch.setattr(tl_mod, '_lookup_stadium', lambda *a, **k: None)

    start = _dt(23, 0)
    end = _dt(23, 2)
    fake_tl = {
        'first_actual_pitch_utc': start, 'first_pitch_utc': start, 'scheduled_start_utc': start,
        'last_play_utc': end, 'plays': [_completed_play(1, 'top', 0, 0, end)],
        'pitch_events': [], 'wp_events': [], 'challenge_events': [], 'next_batters_events': [],
    }
    monkeypatch.setattr(tl_mod, '_fetch_game_timeline', lambda pk: fake_tl)

    from PIL import Image
    fake_image = Image.new('1', (800, 480), 255)

    output = str(tmp_path / 'out.gif')
    with patch('standings.get_standings'), \
         patch('generate_image.orchestrate_score_board', return_value=(fake_image, [])):
        generate_gif('2026-06-20', '23:00', '23:02', output, 1, 300, 1, {'timezone': 'America/Chicago'})

    out = capsys.readouterr().out
    assert 'GIF saved' in out
    assert os.path.exists(output)


def test_generate_gif_end_before_start_returns_early(monkeypatch, capsys):
    """Generate gif end before start returns early."""
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file',
                         lambda f: {'games': [{'game_pk': 1}]} if 'games' in f else {})
    monkeypatch.setattr(tl_mod, '_lookup_stadium', lambda *a, **k: None)
    monkeypatch.setattr(tl_mod, '_fetch_game_timeline', lambda pk: {
        'first_actual_pitch_utc': _dt(23), 'first_pitch_utc': _dt(23), 'scheduled_start_utc': _dt(23),
        'last_play_utc': _dt(23, 30),
    })
    with patch('standings.get_standings'):
        generate_gif('2026-06-20', '23:30', '23:00', '/tmp/out.gif', 1, 300, 1, {'timezone': 'America/Chicago'})
    assert 'End time is before start time' in capsys.readouterr().out


def test_generate_gif_weather_attach_error_is_caught(monkeypatch, capsys):
    """Generate gif weather attach error is caught."""
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file',
                         lambda f: {'games': [{'game_pk': 1, 'venue': 'Fenway Park', 'game_date': '2026-06-20'}]}
                         if 'games' in f else {})

    def _boom(*a, **k):
        """Boom."""
        raise Exception('stadium lookup broke')
    monkeypatch.setattr(tl_mod, '_lookup_stadium', _boom)
    monkeypatch.setattr(tl_mod, '_fetch_game_timeline', MagicMock(side_effect=Exception('boom')))
    with patch('standings.get_standings'):
        generate_gif('2026-06-20', None, None, '/tmp/out.gif', 1, 300, 1,
                      {'timezone': 'America/Chicago', 'weather': {'enabled': True}})
    assert 'weather attach error' in capsys.readouterr().out


def test_generate_gif_standings_fetch_error_is_caught(monkeypatch, capsys):
    """Generate gif standings fetch error is caught."""
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file',
                         lambda f: {'games': [{'game_pk': 1}]} if 'games' in f else {})
    monkeypatch.setattr(tl_mod, '_lookup_stadium', lambda *a, **k: None)
    monkeypatch.setattr(tl_mod, '_fetch_game_timeline', MagicMock(side_effect=Exception('boom')))
    with patch('standings.get_standings', side_effect=Exception('standings down')):
        generate_gif('2026-06-20', None, None, '/tmp/out.gif', 1, 300, 1, {'timezone': 'America/Chicago'})
    assert 'standings error' in capsys.readouterr().out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_main_requires_start_and_end_together(monkeypatch, capsys):
    """Main requires start and end together."""
    monkeypatch.setattr('sys.argv', ['timelapse.py', '--date', '2026-06-20', '--start', '18:00'])
    with pytest.raises(SystemExit):
        tl_mod.main()
    assert '--start and --end must be used together' in capsys.readouterr().err


def test_main_invokes_generate_gif(monkeypatch):
    """Main invokes generate gif."""
    monkeypatch.setattr('sys.argv', ['timelapse.py', '--date', '2026-06-20'])
    monkeypatch.setattr(tl_mod, 'load_yaml_file', lambda f: {'timezone': 'America/Chicago'})
    called = {}

    def _fake_generate_gif(*args, **kwargs):
        """Fake generate gif."""
        called['args'] = args

    monkeypatch.setattr(tl_mod, 'generate_gif', _fake_generate_gif)
    tl_mod.main()
    assert called['args'][0] == '2026-06-20'


# ---------------------------------------------------------------------------
# _fetch_game_timeline — remaining edge branches
# ---------------------------------------------------------------------------

def test_fetch_game_timeline_win_probability_endpoint_failure_ignored():
    """Fetch game timeline win probability endpoint failure ignored."""
    feed = _live_feed(all_plays=[_play(outs_after=1)])

    def _get(url, timeout=None):
        """Get."""
        if 'winProbability' in url:
            raise Exception('wp endpoint down')
        resp = MagicMock()
        resp.json.return_value = feed
        return resp

    with patch('timelapse.requests.get', side_effect=_get):
        tl = _fetch_game_timeline(12345)
    assert len(tl['plays']) == 1  # timeline still built despite wp failure


def test_fetch_game_timeline_malformed_play_start_time_ignored():
    """Fetch game timeline malformed play start time ignored."""
    play = _play(start='garbage-timestamp')
    feed = _live_feed(all_plays=[play])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert tl['first_pitch_utc'] is None


def test_fetch_game_timeline_home_team_challenge_attribution():
    """Fetch game timeline home team challenge attribution."""
    feed = _live_feed(all_plays=[
        _play(outs_after=1, events=[_pitch_event(challenge_team=147)]),  # home_id=147
    ])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert tl['challenge_events'][0]['home_remaining'] == 1


def test_fetch_game_timeline_pitch_event_missing_start_time_skipped():
    """Fetch game timeline pitch event missing start time skipped."""
    play = _play(events=[{'type': 'pitch', 'startTime': '', 'count': {}}])
    feed = _live_feed(all_plays=[play])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert tl['pitch_events'] == []


def test_fetch_game_timeline_pitch_event_malformed_time_skipped():
    """Fetch game timeline pitch event malformed time skipped."""
    play = _play(events=[{'type': 'pitch', 'startTime': 'garbage', 'count': {}}])
    feed = _live_feed(all_plays=[play])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert tl['pitch_events'] == []


def test_fetch_game_timeline_malformed_end_time_play_dropped():
    """Fetch game timeline malformed end time play dropped."""
    play = _play(end='garbage-end-time')
    feed = _live_feed(all_plays=[play])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert tl['plays'] == []


def test_fetch_game_timeline_next_batters_bottom_half_break_uses_away_lineup():
    """Fetch game timeline next batters bottom half break uses away lineup."""
    # Bottom half ends (outs_after=3) -> next up is the away team, top half.
    play = _play(inning=1, half='bottom', outs_after=3,
                 start='2026-06-20T23:00:00Z', end='2026-06-20T23:05:00Z')
    feed = _live_feed(all_plays=[play])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert tl['next_batters_events'][0]['next_batter_1'] == 'Mookie Betts'  # away team


def test_fetch_game_timeline_next_batters_empty_lineup_skipped():
    """Fetch game timeline next batters empty lineup skipped."""
    feed = _live_feed(all_plays=[
        _play(inning=1, half='top', outs_after=3,
              start='2026-06-20T23:00:00Z', end='2026-06-20T23:05:00Z'),
    ])
    feed['liveData']['boxscore']['teams']['home']['battingOrder'] = []
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert tl['next_batters_events'] == []


def test_fetch_game_timeline_next_batters_resumes_after_last_known_batter():
    """Top half ends -> the next-batter break looks for a pitch event in the
    upcoming bottom half to identify the next pitcher; a bottom-half play's
    own pitch event (even if that play isn't complete yet) satisfies that."""
    bottom_pitch_play = _play(
        inning=1, half='bottom', complete=False, batter_id=5,
        events=[_pitch_event(time='2026-06-20T23:06:00Z')],
    )
    feed = _live_feed(all_plays=[
        _play(inning=1, half='top', outs_after=3, batter_id=1,
              start='2026-06-20T23:00:00Z', end='2026-06-20T23:05:00Z'),
        bottom_pitch_play,
    ])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert len(tl['next_batters_events']) == 1
    # Pitcher for the home team's upcoming (bottom) half, found via the pitch event.
    assert tl['next_batters_events'][0]['next_pitcher'] == 'Logan Webb'


def test_fetch_game_timeline_next_batters_resumes_lineup_after_known_last_batter():
    """A bottom-half inning break looks back through the timeline for the away
    team's most recent top-half batter, and resumes the lineup after them
    (rather than starting over at slot 0)."""
    feed = _live_feed(all_plays=[
        _play(inning=1, half='top', outs_after=1, batter_id=1,
              start='2026-06-20T23:00:00Z', end='2026-06-20T23:01:00Z'),
        _play(inning=1, half='bottom', outs_after=3, batter_id=5,
              start='2026-06-20T23:05:00Z', end='2026-06-20T23:10:00Z'),
    ])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)
    assert len(tl['next_batters_events']) == 1
    # Away team's only batter (id 1) already hit — lineup resumes at slot 0 again.
    assert tl['next_batters_events'][0]['next_batter_1'] == 'Mookie Betts'


# ---------------------------------------------------------------------------
# _game_state_at_time / _any_game_active — loop-break branches
# ---------------------------------------------------------------------------

def test_game_state_mid_at_bat_stops_at_first_future_pitch_event():
    """Game state mid at bat stops at first future pitch event."""
    pitch_events = [
        {'time': _dt(23, 10), 'balls': 1, 'strikes': 0, 'outs': 0, 'inning': 1,
         'half_inning': 'top', 'away_score': 0, 'home_score': 0, 'pitcher': 'A', 'batter': 'B',
         'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None},
        {'time': _dt(23, 20), 'balls': 3, 'strikes': 2, 'outs': 1, 'inning': 1,
         'half_inning': 'top', 'away_score': 0, 'home_score': 0, 'pitcher': 'A', 'batter': 'B',
         'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None},
    ]
    tl = _tl(pitch_events=pitch_events, last_play_utc=_dt(23, 30))
    state = _game_state_at_time(_base_game(), tl, _dt(23, 12))
    assert state['balls'] == 1  # only the first event should apply


def test_game_state_challenge_events_stops_at_first_future_entry():
    """Game state challenge events stops at first future entry."""
    pitch_events = [{'time': _dt(23, 5), 'balls': 0, 'strikes': 0, 'outs': 0, 'inning': 1,
                      'half_inning': 'top', 'away_score': 0, 'home_score': 0,
                      'pitcher': '', 'batter': '', 'runner_on_first': None,
                      'runner_on_second': None, 'runner_on_third': None}]
    challenge_events = [
        {'time': _dt(23, 4), 'away_remaining': 1, 'home_remaining': 2},
        {'time': _dt(23, 20), 'away_remaining': 0, 'home_remaining': 2},
    ]
    tl = _tl(pitch_events=pitch_events, challenge_events=challenge_events, last_play_utc=_dt(23, 30))
    state = _game_state_at_time(_base_game(), tl, _dt(23, 10))
    assert state['away_challenges_remaining'] == 1


def test_game_state_next_batters_stops_at_first_future_entry():
    """Game state next batters stops at first future entry."""
    plays = [_completed_play(1, 'top', 1, 0, _dt(23, 10))]
    plays[0]['outs_after'] = 3
    plays[0]['pitcher'] = 'Logan Webb'
    next_batters_events = [
        {'time': _dt(23, 10), 'next_batter_1': 'A', 'next_batter_2': 'B', 'next_batter_3': 'C', 'next_pitcher': 'D'},
        {'time': _dt(23, 25), 'next_batter_1': 'Z', 'next_batter_2': 'Y', 'next_batter_3': 'X', 'next_pitcher': 'W'},
    ]
    tl = _tl(plays=plays, next_batters_events=next_batters_events, last_play_utc=_dt(23, 10))
    state = _game_state_at_time(_base_game(), tl, _dt(23, 12))
    assert state['next_batter_1'] == 'A'


def test_game_state_last_event_loop_stops_at_first_future_play():
    """Game state last event loop stops at first future play."""
    plays = [
        _completed_play(1, 'top', 1, 0, _dt(23, 5)),
        _completed_play(1, 'bottom', 1, 1, _dt(23, 25)),
    ]
    plays[0]['outs_after'] = 3
    plays[0]['pitcher'] = 'A'
    plays[1]['outs_after'] = 3
    plays[1]['pitcher'] = 'B'
    tl = _tl(plays=plays, last_play_utc=_dt(23, 25))
    state = _game_state_at_time(_base_game(), tl, _dt(23, 10))
    assert state['current_inning'] == 1
    assert state['inningState'] == 'Middle'


# ---------------------------------------------------------------------------
# generate_gif — remaining branches
# ---------------------------------------------------------------------------

def test_generate_gif_skips_game_with_no_game_pk(monkeypatch, capsys):
    """Generate gif skips game with no game pk."""
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file',
                         lambda f: {'games': [{}]} if 'games' in f else {})
    monkeypatch.setattr(tl_mod, '_lookup_stadium', lambda *a, **k: None)
    with patch('standings.get_standings'):
        generate_gif('2026-06-20', None, None, '/tmp/out.gif', 1, 300, 1, {'timezone': 'America/Chicago'})
    assert 'No timeline data fetched' in capsys.readouterr().out


def test_generate_gif_attaches_weather_when_stadium_and_forecast_available(monkeypatch):
    """Generate gif attaches weather when stadium and forecast available."""
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    games = [{'game_pk': 1, 'venue': 'Fenway Park', 'game_date': '2026-06-20'}]
    monkeypatch.setattr(tl_mod, 'load_json_file',
                         lambda f: {'games': games} if 'games' in f else {})
    monkeypatch.setattr(tl_mod, '_lookup_stadium',
                         lambda *a, **k: {'lat': 42.0, 'lon': -71.0, 'roof': 'fixed'})
    monkeypatch.setattr(tl_mod, '_fetch_game_timeline', MagicMock(side_effect=Exception('stop after weather')))
    fake_forecast = {'temp_f': 70, 'wind_mph': 5, 'wind_dir': 'NW', 'precip_pct': 10}
    with patch('standings.get_standings'), \
         patch('weather.get_forecast', return_value=fake_forecast):
        generate_gif('2026-06-20', None, None, '/tmp/out.gif', 1, 300, 1,
                      {'timezone': 'America/Chicago', 'weather': {'enabled': True}})
    assert games[0]['roof_state'] == 'fixed'
    assert games[0]['weather_temp_f'] == 70


def test_generate_gif_auto_detects_window_and_renders_active_frame(monkeypatch, tmp_path, capsys):
    """Generate gif auto detects window and renders active frame."""
    from PIL import Image
    games = [{'game_pk': 1}]
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file',
                         lambda f: {'games': games} if 'games' in f else {'team_abbreviation': {}})
    monkeypatch.setattr(tl_mod, '_lookup_stadium', lambda *a, **k: None)

    start = _dt(23, 0)
    end = _dt(23, 2)
    play = _completed_play(1, 'top', 0, 0, end)
    play['outs_after'] = 1
    fake_tl = {
        'first_actual_pitch_utc': start, 'first_pitch_utc': start, 'scheduled_start_utc': start,
        'last_play_utc': None,  # game still active -> no trailing final frame
        'plays': [play],
        'pitch_events': [{'time': start, 'balls': 0, 'strikes': 0, 'outs': 0, 'inning': 1,
                           'half_inning': 'top', 'away_score': 0, 'home_score': 0,
                           'pitcher': '', 'batter': '', 'runner_on_first': None,
                           'runner_on_second': None, 'runner_on_third': None}],
        'wp_events': [], 'challenge_events': [], 'next_batters_events': [],
    }
    monkeypatch.setattr(tl_mod, '_fetch_game_timeline', lambda pk: fake_tl)

    fake_image = Image.new('1', (800, 480), 255)
    output = str(tmp_path / 'out.gif')
    with patch('standings.get_standings'), \
         patch('generate_image.orchestrate_score_board', return_value=(fake_image, [])):
        generate_gif('2026-06-20', None, None, output, 1, 300, 1, {'timezone': 'America/Chicago'})

    out = capsys.readouterr().out
    assert 'Auto-detected window' in out
    assert os.path.exists(output)


def test_generate_gif_frame_render_returns_none_is_skipped(monkeypatch, capsys):
    """Generate gif frame render returns none is skipped."""
    games = [{'game_pk': 1}]
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file',
                         lambda f: {'games': games} if 'games' in f else {'team_abbreviation': {}})
    monkeypatch.setattr(tl_mod, '_lookup_stadium', lambda *a, **k: None)

    start = _dt(23, 0)
    fake_tl = {
        'first_actual_pitch_utc': start, 'first_pitch_utc': start, 'scheduled_start_utc': start,
        'last_play_utc': None,
        'plays': [], 'pitch_events': [{'time': start, 'balls': 0, 'strikes': 0, 'outs': 0,
                                        'inning': 1, 'half_inning': 'top', 'away_score': 0,
                                        'home_score': 0, 'pitcher': '', 'batter': '',
                                        'runner_on_first': None, 'runner_on_second': None,
                                        'runner_on_third': None}],
        'wp_events': [], 'challenge_events': [], 'next_batters_events': [],
    }
    monkeypatch.setattr(tl_mod, '_fetch_game_timeline', lambda pk: fake_tl)

    with patch('standings.get_standings'), \
         patch('generate_image.orchestrate_score_board', return_value=None):
        generate_gif('2026-06-20', '23:00', '23:01', '/tmp/out.gif', 1, 300, 1, {'timezone': 'America/Chicago'})

    out = capsys.readouterr().out
    assert 'No frames generated' in out


def test_generate_gif_frame_render_exception_is_caught(monkeypatch, capsys):
    """Generate gif frame render exception is caught."""
    games = [{'game_pk': 1}]
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file',
                         lambda f: {'games': games} if 'games' in f else {'team_abbreviation': {}})
    monkeypatch.setattr(tl_mod, '_lookup_stadium', lambda *a, **k: None)

    start = _dt(23, 0)
    fake_tl = {
        'first_actual_pitch_utc': start, 'first_pitch_utc': start, 'scheduled_start_utc': start,
        'last_play_utc': None,
        'plays': [], 'pitch_events': [{'time': start, 'balls': 0, 'strikes': 0, 'outs': 0,
                                        'inning': 1, 'half_inning': 'top', 'away_score': 0,
                                        'home_score': 0, 'pitcher': '', 'batter': '',
                                        'runner_on_first': None, 'runner_on_second': None,
                                        'runner_on_third': None}],
        'wp_events': [], 'challenge_events': [], 'next_batters_events': [],
    }
    monkeypatch.setattr(tl_mod, '_fetch_game_timeline', lambda pk: fake_tl)

    with patch('standings.get_standings'), \
         patch('generate_image.orchestrate_score_board', side_effect=Exception('render broke')):
        generate_gif('2026-06-20', None, None, '/tmp/out.gif', 1, 300, 1, {'timezone': 'America/Chicago'})

    assert 'error: render broke' in capsys.readouterr().out


def test_generate_gif_trailing_frame_skip_and_error_paths(monkeypatch, capsys):
    """Generate gif trailing frame skip and error paths."""
    games = [{'game_pk': 1}]
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file',
                         lambda f: {'games': games} if 'games' in f else {'team_abbreviation': {}})
    monkeypatch.setattr(tl_mod, '_lookup_stadium', lambda *a, **k: None)

    start = _dt(23, 0)
    end = _dt(23, 1)
    play = _completed_play(1, 'top', 0, 0, end)
    play['outs_after'] = 1
    fake_tl = {
        'first_actual_pitch_utc': start, 'first_pitch_utc': start, 'scheduled_start_utc': start,
        'last_play_utc': end,  # game finished -> trailing frame block runs
        'plays': [play], 'pitch_events': [], 'wp_events': [], 'challenge_events': [],
        'next_batters_events': [],
    }
    monkeypatch.setattr(tl_mod, '_fetch_game_timeline', lambda pk: fake_tl)

    call_count = {'n': 0}

    def _orchestrate(*args, **kwargs):
        """Orchestrate."""
        call_count['n'] += 1
        if call_count['n'] == 1:
            return None  # main-loop frame skipped
        raise Exception('trailing frame broke')

    with patch('standings.get_standings'), \
         patch('generate_image.orchestrate_score_board', side_effect=_orchestrate):
        generate_gif('2026-06-20', None, None, '/tmp/out.gif', 1, 300, 1, {'timezone': 'America/Chicago'})

    out = capsys.readouterr().out
    assert 'error: trailing frame broke' in out


def test_generate_gif_trailing_frame_skip_when_render_returns_none(monkeypatch, capsys):
    """Generate gif trailing frame skip when render returns none."""
    from PIL import Image
    games = [{'game_pk': 1}]
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file',
                         lambda f: {'games': games} if 'games' in f else {'team_abbreviation': {}})
    monkeypatch.setattr(tl_mod, '_lookup_stadium', lambda *a, **k: None)

    start = _dt(23, 0)
    end = _dt(23, 1)
    play = _completed_play(1, 'top', 0, 0, end)
    play['outs_after'] = 1
    fake_tl = {
        'first_actual_pitch_utc': start, 'first_pitch_utc': start, 'scheduled_start_utc': start,
        'last_play_utc': end,
        'plays': [play], 'pitch_events': [], 'wp_events': [], 'challenge_events': [],
        'next_batters_events': [],
    }
    monkeypatch.setattr(tl_mod, '_fetch_game_timeline', lambda pk: fake_tl)

    fake_image = Image.new('1', (800, 480), 255)
    call_count = {'n': 0}

    def _orchestrate(*args, **kwargs):
        """Orchestrate."""
        call_count['n'] += 1
        # First call (main loop) succeeds so "No frames generated" doesn't fire;
        # every later call — including the trailing frame, always called last —
        # returns None (skipped).
        return (fake_image, []) if call_count['n'] == 1 else None

    with patch('standings.get_standings'), \
         patch('generate_image.orchestrate_score_board', side_effect=_orchestrate):
        generate_gif('2026-06-20', None, None, '/tmp/out.gif', 1, 300, 1, {'timezone': 'America/Chicago'})

    out = capsys.readouterr().out
    assert '[final ] rendering trailing end-state frame... skip' in out


def test_generate_gif_writes_mp4_with_multiple_frames(monkeypatch, tmp_path, capsys):
    """Generate gif writes mp4 with multiple frames."""
    from PIL import Image
    games = [{'game_pk': 1}]
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file',
                         lambda f: {'games': games} if 'games' in f else {'team_abbreviation': {}})
    monkeypatch.setattr(tl_mod, '_lookup_stadium', lambda *a, **k: None)

    start = _dt(23, 0)
    end = _dt(23, 2)
    play = _completed_play(1, 'top', 0, 0, end)
    play['outs_after'] = 1
    pitch_events = [{'time': start, 'balls': 0, 'strikes': 0, 'outs': 0, 'inning': 1,
                      'half_inning': 'top', 'away_score': 0, 'home_score': 0,
                      'pitcher': '', 'batter': '', 'runner_on_first': None,
                      'runner_on_second': None, 'runner_on_third': None}]
    fake_tl = {
        'first_actual_pitch_utc': start, 'first_pitch_utc': start, 'scheduled_start_utc': start,
        'last_play_utc': end, 'plays': [play], 'pitch_events': pitch_events,
        'wp_events': [], 'challenge_events': [], 'next_batters_events': [],
    }
    monkeypatch.setattr(tl_mod, '_fetch_game_timeline', lambda pk: fake_tl)

    fake_image = Image.new('1', (800, 480), 255)
    output = str(tmp_path / 'out.gif')
    with patch('standings.get_standings'), \
         patch('generate_image.orchestrate_score_board', return_value=(fake_image, [])):
        generate_gif('2026-06-20', '23:00', '23:02', output, 1, 50, 1, {'timezone': 'America/Chicago'})

    out = capsys.readouterr().out
    assert 'MP4 saved' in out or 'imageio not installed' in out


def test_generate_gif_imageio_missing_is_reported(monkeypatch, tmp_path, capsys):
    """Generate gif imageio missing is reported."""
    from PIL import Image
    games = [{'game_pk': 1}]
    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file',
                         lambda f: {'games': games} if 'games' in f else {'team_abbreviation': {}})
    monkeypatch.setattr(tl_mod, '_lookup_stadium', lambda *a, **k: None)

    start = _dt(23, 0)
    end = _dt(23, 1)
    play = _completed_play(1, 'top', 0, 0, end)
    play['outs_after'] = 1
    fake_tl = {
        'first_actual_pitch_utc': start, 'first_pitch_utc': start, 'scheduled_start_utc': start,
        'last_play_utc': end, 'plays': [play], 'pitch_events': [], 'wp_events': [],
        'challenge_events': [], 'next_batters_events': [],
    }
    monkeypatch.setattr(tl_mod, '_fetch_game_timeline', lambda pk: fake_tl)

    fake_image = Image.new('1', (800, 480), 255)
    output = str(tmp_path / 'out.gif')
    with patch('standings.get_standings'), \
         patch('generate_image.orchestrate_score_board', return_value=(fake_image, [])), \
         patch.dict('sys.modules', {'imageio': None}):
        generate_gif('2026-06-20', '23:00', '23:01', output, 1, 300, 1, {'timezone': 'America/Chicago'})

    assert 'imageio not installed' in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _fetch_game_timeline pitch-detail extraction
# ---------------------------------------------------------------------------

def test_fetch_game_timeline_extracts_pitch_speed_type_and_strike_call():
    """_fetch_game_timeline must extract last_pitch_speed, last_pitch_type,
    at_bat_pitch_count, last_strike_call, and strike_calls from isPitch events
    so _game_state_at_time can populate the wide-box pitch-detail fields."""
    pitch_ev = {
        'type': 'pitch',
        'isPitch': True,
        'startTime': '2026-06-20T23:05:00Z',
        'count': {'balls': 0, 'strikes': 1, 'outs': 0},
        'pitchData': {'startSpeed': 95.2},
        'details': {
            'type': {'code': 'FF'},               # Four-seam fastball → 'FB'
            'call': {'code': 'C'},                 # Called strike → 'L'
        },
    }
    play = _play(
        inning=1, half='top', complete=False,
        start='2026-06-20T23:04:00Z', end='2026-06-20T23:09:00Z',
        events=[pitch_ev],
    )
    feed = _live_feed(all_plays=[play])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)

    assert tl['pitch_events'], "Expected at least one pitch event"
    ev = tl['pitch_events'][0]
    assert ev['last_pitch_speed'] == 95.2
    assert ev['last_pitch_type'] == 'FB'     # mapped from 'FF'
    assert ev['at_bat_pitch_count'] == 1
    assert ev['last_strike_call'] == 'L'     # called strike
    assert ev['strike_calls'] == ['C']


def test_fetch_game_timeline_non_pitch_events_carry_last_pitch_data():
    """A non-pitch event (action, mound visit) in the same at-bat carries over
    the last pitch's speed/type so _game_state_at_time always has fresh data."""
    pitch_ev = {
        'type': 'pitch', 'isPitch': True,
        'startTime': '2026-06-20T23:05:00Z',
        'count': {'balls': 0, 'strikes': 1, 'outs': 0},
        'pitchData': {'startSpeed': 88.0},
        'details': {'type': {'code': 'SL'}, 'call': {'code': 'S'}},
    }
    action_ev = {
        'type': 'action', 'isPitch': False,
        'startTime': '2026-06-20T23:06:00Z',
        'count': {'balls': 0, 'strikes': 1, 'outs': 0},
        'pitchData': {},
        'details': {'description': 'Mound visit'},
    }
    play = _play(
        inning=1, half='top', complete=False,
        start='2026-06-20T23:04:00Z', end='2026-06-20T23:09:00Z',
        events=[pitch_ev, action_ev],
    )
    feed = _live_feed(all_plays=[play])
    with patch('timelapse.requests.get', side_effect=_mock_requests_get(feed)):
        tl = _fetch_game_timeline(12345)

    # The second event (action) should carry over the pitch's speed and type
    pitch_events_with_time = [e for e in tl['pitch_events'] if e.get('last_pitch_speed')]
    assert any(e['last_pitch_speed'] == 88.0 for e in pitch_events_with_time)


# ---------------------------------------------------------------------------
# Wide (2-cell) slot allocation in rendered frames
# ---------------------------------------------------------------------------

def test_generate_gif_live_games_get_wide_slots_in_frames(monkeypatch, tmp_path):
    """When games are in progress during the timelapse window the frames passed
    to orchestrate_score_board contain 'In Progress' states, and those states
    cause compute_grid_layout to allocate wide (2-cell) slots for the live games.

    This test keeps the full compute_grid_layout→_cluster_live_games path real
    (no mocking), using a spy on orchestrate_score_board to capture what game
    data the timelapse actually hands to the renderer at each frame.
    """
    from image_grid import compute_grid_layout

    game1 = {'game_pk': 1001, 'away_team_id': 147, 'home_team_id': 111,
              'venue': None, 'game_date': None}
    game2 = {'game_pk': 1002, 'away_team_id': 119, 'home_team_id': 136,
              'venue': None, 'game_date': None}

    # Both games are live across the whole window (23:03–23:07 UTC).
    window_start = _dt(23, 0)
    window_end = _dt(23, 10)
    live_tl = _tl(
        first_actual_pitch_utc=window_start,
        first_pitch_utc=window_start,
        scheduled_start_utc=window_start,
        last_play_utc=window_end,
        plays=[_completed_play(5, 'top', 3, 2, _dt(23, 5))],
        pitch_events=[{
            'time': _dt(23, 3),
            'balls': 1, 'strikes': 0, 'outs': 0,
            'inning': 5, 'half_inning': 'top',
            'away_score': 3, 'home_score': 2,
            'pitcher': 'Pitcher A', 'batter': 'Batter B',
            'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None,
        }],
    )

    monkeypatch.setattr(tl_mod, 'fetch_scoreboard_for_date', MagicMock())
    monkeypatch.setattr(tl_mod, 'load_json_file',
                        lambda f: {'games': [game1, game2]} if 'games' in f
                        else {'team_abbreviation': {}})
    monkeypatch.setattr(tl_mod, '_lookup_stadium', lambda *a, **k: None)
    monkeypatch.setattr(tl_mod, '_fetch_game_timeline', lambda pk: live_tl)

    captured_frames = []
    from PIL import Image
    fake_image = Image.new('1', (800, 480), 255)

    def _spy(frame_games, *args, **kwargs):
        captured_frames.append(list(frame_games))
        return (fake_image, [])

    with patch('generate_image.orchestrate_score_board', side_effect=_spy), \
         patch('standings.get_standings'):
        generate_gif('2026-06-20', '23:03', '23:07', str(tmp_path / 'out.gif'),
                     2, 300, 1, {'timezone': 'UTC'})

    assert captured_frames, "Expected at least one frame rendered during the live window"

    # Every frame should have both games reconstructed as 'In Progress'.
    first_frame = captured_frames[0]
    states = [g.get('detailed_state') for g in first_frame]
    assert all(s == 'In Progress' for s in states), (
        f"All games should be 'In Progress' during live window, got: {states}"
    )

    # compute_grid_layout must allocate wide slots for those live games.
    cfg = {
        'wide_cell_always': False,
        'wide_cell_featured': False,
        'favorite_team_first': False,
        'primary': '',
    }
    team_data = {'team_abbreviation': {}}
    _, slots = compute_grid_layout(first_frame, team_data, cfg)
    wide_count = sum(1 for s in slots if s[0] == 'wide')
    assert wide_count >= 1, (
        f"Expected wide slots for live games in timelapse frame, got slots: {slots}"
    )
