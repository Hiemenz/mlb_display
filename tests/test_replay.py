"""Tests for src/replay.py — pitch-by-pitch game replay on the e-ink display."""
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest
import pytz

import replay as replay_mod
from replay import (
    _find_game_by_team,
    _lookup_date_for_game,
    replay_game,
)

UTC = pytz.utc


def _dt(hour, minute=0):
    return UTC.localize(datetime(2026, 8, 1, hour, minute, 0))


# ---------------------------------------------------------------------------
# _find_game_by_team
# ---------------------------------------------------------------------------

_TEAM_DATA = {
    'team_abbreviation': {
        '112': 'CHC',
        '158': 'MIL',
        '147': 'NYY',
        '111': 'BOS',
    }
}

_BASE_GAMES = [
    {'game_pk': 1001, 'away_team_id': 112, 'home_team_id': 158,
     'away_team_name': 'Chicago Cubs', 'home_team_name': 'Milwaukee Brewers'},
    {'game_pk': 1002, 'away_team_id': 147, 'home_team_id': 111,
     'away_team_name': 'New York Yankees', 'home_team_name': 'Boston Red Sox'},
]


def test_find_game_by_team_home_match():
    """Matches by home-team abbreviation."""
    g = _find_game_by_team(_BASE_GAMES, _TEAM_DATA, 'MIL')
    assert g is not None
    assert g['game_pk'] == 1001


def test_find_game_by_team_away_match():
    """Matches by away-team abbreviation."""
    g = _find_game_by_team(_BASE_GAMES, _TEAM_DATA, 'nyy')
    assert g is not None
    assert g['game_pk'] == 1002


def test_find_game_by_team_not_found():
    """Returns None when no game matches the abbreviation."""
    assert _find_game_by_team(_BASE_GAMES, _TEAM_DATA, 'LAD') is None


# ---------------------------------------------------------------------------
# _lookup_date_for_game
# ---------------------------------------------------------------------------

def test_lookup_date_for_game_returns_date():
    """Returns the originalDate from the live feed."""
    resp = MagicMock()
    resp.json.return_value = {
        'gameData': {'datetime': {'originalDate': '2026-08-01'}}
    }
    with patch('replay.requests.get', return_value=resp):
        date = _lookup_date_for_game(1001)
    assert date == '2026-08-01'


def test_lookup_date_for_game_raises_on_http_error():
    """Propagates requests exceptions."""
    import requests as _req
    with patch('replay.requests.get', side_effect=_req.RequestException('timeout')):
        with pytest.raises(_req.RequestException):
            _lookup_date_for_game(9999)


# ---------------------------------------------------------------------------
# replay_game — core loop
# ---------------------------------------------------------------------------

def _pitch_ev(balls=0, strikes=0, outs=0, inning=1, half='top',
              is_pitch=True, speed=91.5, ptype='FF'):
    return {
        'time': _dt(20),
        'balls': balls,
        'strikes': strikes,
        'outs': outs,
        'inning': inning,
        'half_inning': half,
        'away_score': 0,
        'home_score': 0,
        'is_pitch': is_pitch,
        'last_pitch_speed': speed,
        'last_pitch_type': ptype,
    }


def _make_tl(events=None):
    return {
        'pitch_events': events if events is not None else [],
        'plays': [],
        'wp_events': [],
        'hit_events': [],
        'header_events': [],
        'pitcher_k_events': [],
        'challenge_events': [],
        'next_batters_events': [],
        'first_pitch_utc': _dt(20),
        'last_play_utc': _dt(23),
        'scheduled_start_utc': _dt(20),
        'first_actual_pitch_utc': _dt(20),
    }


def _mock_games_json(game_pk=1001):
    return {
        'games': [
            {
                'game_pk': game_pk,
                'away_team_id': 112,
                'home_team_id': 158,
                'away_team_name': 'Chicago Cubs',
                'home_team_name': 'Milwaukee Brewers',
                'detailed_state': 'Final',
            }
        ]
    }


def _setup_replay_patches(tl, game_pk=1001, games_json=None, state_override=None):
    """Return a dict of patch kwargs for the core replay_game dependencies."""
    if games_json is None:
        games_json = _mock_games_json(game_pk)

    reconstructed = state_override or {'game_pk': game_pk, 'detailed_state': 'In Progress'}

    fake_image = MagicMock()
    fake_image.save = MagicMock()

    return {
        'games_json': games_json,
        'tl': tl,
        'reconstructed': reconstructed,
        'fake_image': fake_image,
    }


@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._game_state_at_time')
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file')
@patch('replay.fetch_scoreboard_for_date')
def test_replay_game_calls_display_per_pitch(
        mock_fetch, mock_load, mock_tl, mock_gsat, mock_orc, mock_disp,
):
    """send_to_display is called once per pitch event."""
    events = [_pitch_ev(strikes=0), _pitch_ev(strikes=1), _pitch_ev(strikes=2)]
    tl = _make_tl(events)

    mock_tl.return_value = tl
    mock_gsat.return_value = {'game_pk': 1001}

    fake_image = MagicMock()
    mock_orc.return_value = (fake_image, [])

    def _load(name, *a, **kw):
        if 'games' in name:
            return _mock_games_json()
        return _TEAM_DATA
    mock_load.side_effect = _load

    replay_game(
        game_pk=1001, date_str='2026-08-01', delay_seconds=0,
        pitches_only=True, config={}, local_mode=False,
    )

    assert mock_disp.call_count == 3
    assert fake_image.save.call_count == 3


@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._game_state_at_time')
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file')
@patch('replay.fetch_scoreboard_for_date')
def test_replay_game_no_pitch_events_exits_early(
        mock_fetch, mock_load, mock_tl, mock_gsat, mock_orc, mock_disp,
):
    """No pitch events: prints message and returns without rendering."""
    mock_tl.return_value = _make_tl([])  # empty

    def _load(name, *a, **kw):
        if 'games' in name:
            return _mock_games_json()
        return _TEAM_DATA
    mock_load.side_effect = _load

    replay_game(
        game_pk=1001, date_str='2026-08-01', delay_seconds=0,
        pitches_only=True, config={}, local_mode=False,
    )

    mock_orc.assert_not_called()
    mock_disp.assert_not_called()


@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._game_state_at_time')
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file')
@patch('replay.fetch_scoreboard_for_date')
def test_replay_game_unknown_game_pk_exits_early(
        mock_fetch, mock_load, mock_tl, mock_gsat, mock_orc, mock_disp,
):
    """game_pk not in base_games: returns without calling timeline or display."""
    def _load(name, *a, **kw):
        if 'games' in name:
            return {'games': []}  # empty — game_pk will not be found
        return _TEAM_DATA
    mock_load.side_effect = _load

    replay_game(
        game_pk=9999, date_str='2026-08-01', delay_seconds=0,
        pitches_only=True, config={}, local_mode=False,
    )

    mock_tl.assert_not_called()
    mock_orc.assert_not_called()


@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._game_state_at_time')
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file')
@patch('replay.fetch_scoreboard_for_date')
def test_replay_game_local_mode_skips_display(
        mock_fetch, mock_load, mock_tl, mock_gsat, mock_orc, mock_disp,
):
    """local_mode=True: orchestrate_score_board still runs but send_to_display is not called."""
    events = [_pitch_ev()]
    mock_tl.return_value = _make_tl(events)
    mock_gsat.return_value = {'game_pk': 1001}
    fake_image = MagicMock()
    mock_orc.return_value = (fake_image, [])

    def _load(name, *a, **kw):
        if 'games' in name:
            return _mock_games_json()
        return _TEAM_DATA
    mock_load.side_effect = _load

    replay_game(
        game_pk=1001, date_str='2026-08-01', delay_seconds=0,
        pitches_only=True, config={}, local_mode=True,
    )

    mock_orc.assert_called_once()
    mock_disp.assert_not_called()


@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._game_state_at_time')
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file')
@patch('replay.fetch_scoreboard_for_date')
def test_replay_game_includes_non_pitch_events_when_not_pitches_only(
        mock_fetch, mock_load, mock_tl, mock_gsat, mock_orc, mock_disp,
):
    """pitches_only=False includes action events in the replay."""
    pitch = _pitch_ev(is_pitch=True)
    action = _pitch_ev(is_pitch=False, speed=None, ptype='')
    events = [pitch, action]
    mock_tl.return_value = _make_tl(events)
    mock_gsat.return_value = {'game_pk': 1001}
    fake_image = MagicMock()
    mock_orc.return_value = (fake_image, [])

    def _load(name, *a, **kw):
        if 'games' in name:
            return _mock_games_json()
        return _TEAM_DATA
    mock_load.side_effect = _load

    replay_game(
        game_pk=1001, date_str='2026-08-01', delay_seconds=0,
        pitches_only=False, config={}, local_mode=False,
    )

    # Both pitch and action events rendered
    assert mock_orc.call_count == 2
    assert mock_disp.call_count == 2


@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._game_state_at_time')
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file')
@patch('replay.fetch_scoreboard_for_date')
def test_replay_game_skips_frame_when_orchestrate_returns_none(
        mock_fetch, mock_load, mock_tl, mock_gsat, mock_orc, mock_disp,
):
    """No display push when orchestrate_score_board returns None (unchanged frame)."""
    events = [_pitch_ev(), _pitch_ev()]
    mock_tl.return_value = _make_tl(events)
    mock_gsat.return_value = {'game_pk': 1001}
    mock_orc.return_value = None  # unchanged — skip

    def _load(name, *a, **kw):
        if 'games' in name:
            return _mock_games_json()
        return _TEAM_DATA
    mock_load.side_effect = _load

    replay_game(
        game_pk=1001, date_str='2026-08-01', delay_seconds=0,
        pitches_only=True, config={}, local_mode=False,
    )

    mock_disp.assert_not_called()


@patch('replay.send_to_display')
@patch('replay.orchestrate_score_board')
@patch('replay._game_state_at_time')
@patch('replay._fetch_game_timeline')
@patch('replay.load_json_file')
@patch('replay.fetch_scoreboard_for_date')
def test_replay_game_other_games_stay_as_dict_copy(
        mock_fetch, mock_load, mock_tl, mock_gsat, mock_orc, mock_disp,
):
    """Other games on the day keep their final-state dict; only the target game is reconstructed."""
    events = [_pitch_ev()]
    mock_tl.return_value = _make_tl(events)
    mock_gsat.return_value = {'game_pk': 1001, 'reconstructed': True}
    fake_image = MagicMock()
    mock_orc.return_value = (fake_image, [])

    other_game = {
        'game_pk': 2002, 'away_team_id': 147, 'home_team_id': 111,
        'away_team_name': 'Yankees', 'home_team_name': 'Red Sox',
        'detailed_state': 'Final',
    }
    games_json = {
        'games': [
            {
                'game_pk': 1001,
                'away_team_id': 112,
                'home_team_id': 158,
                'away_team_name': 'Cubs',
                'home_team_name': 'Brewers',
                'detailed_state': 'Final',
            },
            other_game,
        ]
    }

    def _load(name, *a, **kw):
        if 'games' in name:
            return games_json
        return _TEAM_DATA
    mock_load.side_effect = _load

    replay_game(
        game_pk=1001, date_str='2026-08-01', delay_seconds=0,
        pitches_only=True, config={}, local_mode=False,
    )

    frame_games = mock_orc.call_args[0][0]
    assert frame_games[0].get('reconstructed') is True  # target: reconstructed
    assert frame_games[1]['game_pk'] == 2002             # other: unchanged dict


# ---------------------------------------------------------------------------
# main() — argument routing
# ---------------------------------------------------------------------------

@patch('replay.replay_game')
@patch('replay.load_config', return_value={})
def test_main_with_game_pk_and_date(mock_cfg, mock_rg):
    """--game-pk + --date calls replay_game with correct args."""
    import sys
    with patch.object(sys, 'argv', ['replay.py', '--game-pk', '745503', '--date', '2026-08-01']):
        replay_mod.main()

    mock_rg.assert_called_once()
    _, kwargs = mock_rg.call_args
    assert kwargs['game_pk'] == 745503
    assert kwargs['date_str'] == '2026-08-01'
    assert kwargs['pitches_only'] is True
    assert kwargs['local_mode'] is False


@patch('replay.replay_game')
@patch('replay.load_config', return_value={})
@patch('replay._lookup_date_for_game', return_value='2026-08-01')
def test_main_game_pk_without_date_looks_up_date(mock_lookup, mock_cfg, mock_rg):
    """--game-pk without --date auto-derives the date from the API."""
    import sys
    with patch.object(sys, 'argv', ['replay.py', '--game-pk', '745503']):
        replay_mod.main()

    mock_lookup.assert_called_once_with(745503)
    mock_rg.assert_called_once()


@patch('replay.replay_game')
@patch('replay.load_config', return_value={})
@patch('replay.load_json_file')
@patch('replay.fetch_scoreboard_for_date')
@patch('replay.set_historical_mode')
def test_main_with_date_and_team(mock_shm, mock_fetch, mock_load, mock_cfg, mock_rg):
    """--date + --team resolves to a game_pk and calls replay_game."""
    import sys

    def _load(name, *a, **kw):
        if 'games' in name:
            return _mock_games_json(1001)
        return _TEAM_DATA
    mock_load.side_effect = _load

    with patch.object(sys, 'argv', ['replay.py', '--date', '2026-08-01', '--team', 'CHC']):
        replay_mod.main()

    mock_rg.assert_called_once()
    _, kwargs = mock_rg.call_args
    assert kwargs['game_pk'] == 1001


@patch('replay.replay_game')
@patch('replay.load_config', return_value={})
@patch('replay.load_json_file')
@patch('replay.fetch_scoreboard_for_date')
@patch('replay.set_historical_mode')
def test_main_with_all_events_flag(mock_shm, mock_fetch, mock_load, mock_cfg, mock_rg):
    """--all-events flag sets pitches_only=False."""
    import sys

    def _load(name, *a, **kw):
        if 'games' in name:
            return _mock_games_json(1001)
        return _TEAM_DATA
    mock_load.side_effect = _load

    with patch.object(sys, 'argv', [
        'replay.py', '--date', '2026-08-01', '--team', 'CHC', '--all-events',
    ]):
        replay_mod.main()

    _, kwargs = mock_rg.call_args
    assert kwargs['pitches_only'] is False


@patch('replay.replay_game')
@patch('replay.load_config', return_value={})
@patch('replay.load_json_file')
@patch('replay.fetch_scoreboard_for_date')
@patch('replay.set_historical_mode')
def test_main_team_not_found_exits(mock_shm, mock_fetch, mock_load, mock_cfg, mock_rg):
    """Exits with error when no game matches the requested team."""
    import sys

    def _load(name, *a, **kw):
        if 'games' in name:
            return {'games': []}
        return _TEAM_DATA
    mock_load.side_effect = _load

    with patch.object(sys, 'argv', ['replay.py', '--date', '2026-08-01', '--team', 'LAD']):
        with pytest.raises(SystemExit):
            replay_mod.main()

    mock_rg.assert_not_called()


def test_main_no_args_exits():
    """No --game-pk and no --date/--team exits with an error."""
    import sys
    with patch.object(sys, 'argv', ['replay.py']):
        with pytest.raises(SystemExit):
            replay_mod.main()
