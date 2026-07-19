"""Generate an animated GIF (+ MP4) timelapse of a full game day's scoreboard.

Fetches each game's complete play-by-play feed once (O(N_games) API calls),
then reconstructs scoreboard state at every minute of the day in memory — no
per-minute API calls. Used by main.py's `auto_generate_video` feature once
all of a day's games go Final, and can also be run standalone:

    poetry run python src/timelapse.py --date 2026-04-01
    poetry run python src/timelapse.py --date 2026-04-01 --start 18:00 --end 23:00

Extracted from the old src/scoreboard_generate.py (which duplicated most of
fetch_games.py/util.py as a pre-refactor monolith) — this module keeps only
the state-reconstruction logic that has no equivalent elsewhere, and uses
the canonical fetch_games/util/standings/weather functions for everything
else.
"""
import argparse
import os
from datetime import datetime, timedelta

import pytz
import requests

from fetch_games import fetch_scoreboard_for_date, _lookup_stadium
from util import load_json_file, load_yaml_file
from game_detail_fetch import _PITCH_TYPE_ABBR, _EVENT_ABBR, _build_scorecard_notation

_INNING_ORDINALS = {
    1: '1st', 2: '2nd', 3: '3rd', 4: '4th', 5: '5th', 6: '6th',
    7: '7th', 8: '8th', 9: '9th', 10: '10th', 11: '11th', 12: '12th',
    13: '13th', 14: '14th', 15: '15th', 16: '16th', 17: '17th', 18: '18th',
}

_WP_SKIP_TYPES = ('substitution', 'timeout', 'advisory')
_GIF_ABS_CHALLENGE_MAX = 2
_TERMINAL_GAME_STATES = {'Postponed', 'Cancelled', 'Suspended'}

_HIT_EVENTS = frozenset({'Single', 'Double', 'Triple', 'Home Run'})
# Plate appearances that don't count as official at-bats
_NOT_AB_EVENTS = frozenset({
    'Walk', 'Intent Walk', 'Hit By Pitch',
    'Sacrifice Fly', 'Sacrifice Fly Double Play',
    'Sacrifice Bunt', "Catcher's Interference", 'Fan Interference',
})
# Inning threshold before displaying no-hitter / perfect game banner
_NO_HITTER_INNING_THRESHOLD = 5

# Header event ("half_inning_plays") reconstruction — mirrors
# game_detail_fetch.fetch_scoreboard_live_extras, which is only available for
# live games and can't be replayed for a historical timelapse.
_HEADER_ACTION_CODES = {
    'stolen_base':      'SB',
    'caught_stealing':  'CS',
    'pickoff':          'PK',
    'wild_pitch':       'WP',
    'passed_ball':      'PB',
    'balk':             'BLK',
    'pitching_substitution': 'PC',
}
_HEADER_SUBST_EVENT_TYPES = frozenset({
    'pitching_substitution', 'defensive_substitution', 'offensive_substitution',
    'runner_substitution', 'game_advisory', 'ejection', 'defensive_switch',
})


def _header_action_code(et):
    """Map a lowercased playEvent eventType to its header abbreviation, if any."""
    for kw, code in _HEADER_ACTION_CODES.items():
        if et.startswith(kw):
            return code
    return None


def _ordinal(n):
    """Ordinal."""
    try:
        return _INNING_ORDINALS.get(int(n), f'{n}th')
    except (TypeError, ValueError):
        return None


def _parse_mlb_time(time_str):
    """Parse an MLB API ISO timestamp to a UTC-aware datetime."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return pytz.utc.localize(datetime.strptime(time_str, fmt))
        except ValueError:
            continue
    raise ValueError(f"Cannot parse MLB timestamp: {time_str!r}")


def _fetch_game_timeline(game_pk):
    """Fetch the full live feed for one game and return a play-by-play timeline.

    Returns a dict:
      scheduled_start_utc  — UTC-aware datetime of scheduled first pitch
      first_pitch_utc      — UTC-aware datetime when first play began (or None)
      last_play_utc        — UTC-aware datetime when last play completed (or None)
      plays                — list of dicts sorted by end_time, each:
                               end_time, away_score, home_score, inning,
                               half_inning ('top'|'bottom'), outs, batter_id
      pitch_events         — list of dicts sorted by time, one per pitch/action event:
                               time, balls, strikes, outs, inning, half_inning,
                               away_score, home_score
                             Used to reconstruct mid-at-bat state minute by minute.
      wp_events            — list of dicts sorted by time, one per completed play:
                               time, away_wp, home_wp, last_play
                             Win probability and last-play description at each play boundary.
      challenge_events     — list of dicts sorted by time, one per play where challenge
                               state changed: time, away_remaining, home_remaining
      next_batters_events  — list of dicts sorted by time, one per inning break:
                               time, next_batter_1/2/3 (full names), next_pitcher
    """
    url = f'https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live'
    resp = requests.get(url, timeout=20)
    data = resp.json()

    scheduled_start = None
    dt_str = data.get('gameData', {}).get('datetime', {}).get('dateTime', '')
    if dt_str:
        try:
            scheduled_start = _parse_mlb_time(dt_str)
        except ValueError:
            pass

    # Team IDs for challenge attribution
    game_data_sec = data.get('gameData', {})
    away_id = game_data_sec.get('teams', {}).get('away', {}).get('id')
    home_id = game_data_sec.get('teams', {}).get('home', {}).get('id')

    # Batting orders from boxscore (final state; good enough for GIF reconstruction)
    bscore_teams = data.get('liveData', {}).get('boxscore', {}).get('teams', {})

    def _build_order(team_box):
        """Build order."""
        batting_order_ids = team_box.get('battingOrder', [])
        players = team_box.get('players', {})
        slot_map = {}
        for pid in batting_order_ids:
            pdata = players.get(f'ID{pid}', {})
            bat_str = str(pdata.get('battingOrder', ''))
            slot = int(bat_str[0]) if bat_str and bat_str[0].isdigit() else None
            if slot:
                slot_map[slot] = (pid, pdata.get('person', {}).get('fullName', ''))
        return [slot_map[s] for s in sorted(slot_map)]

    away_order = _build_order(bscore_teams.get('away', {}))  # [(pid, name), ...]
    home_order = _build_order(bscore_teams.get('home', {}))

    # Jersey numbers by player id, for runner-on-base labels (mirrors
    # game_detail_fetch._runner_jersey, which is only available for live games).
    player_jersey = {}
    for _side in ('away', 'home'):
        for _pdata in bscore_teams.get(_side, {}).get('players', {}).values():
            _pid = _pdata.get('person', {}).get('id')
            _jn = _pdata.get('jerseyNumber')
            if _pid is not None and _jn is not None:
                player_jersey[_pid] = _jn

    all_plays = data.get('liveData', {}).get('plays', {}).get('allPlays', [])
    timeline = []
    hit_events = []
    first_pitch = None
    pitch_events = []
    wp_events = []
    challenge_events = []
    away_chal_used = 0
    home_chal_used = 0

    # Fetch win probability timeline (one entry per completed play)
    wp_by_index = {}
    try:
        wp_resp = requests.get(
            f'https://statsapi.mlb.com/api/v1/game/{game_pk}/winProbability',
            timeout=10,
        )
        wp_data = wp_resp.json()
        if isinstance(wp_data, list):
            for entry in wp_data:
                idx = entry.get('atBatIndex')
                if idx is not None:
                    wp_by_index[idx] = entry
    except Exception:
        pass

    # Running score/runners: state after last completed play (used for pitch events mid-at-bat)
    running_away = 0
    running_home = 0
    running_runners = {'first': None, 'second': None, 'third': None}
    running_runner_ids = {'first': None, 'second': None, 'third': None}
    cumulative_last_play      = None  # last non-substitution event name seen so far
    cumulative_last_play_inn  = None  # inning of that event
    cumulative_last_play_top  = None  # True if top half, False if bottom
    cumulative_last_play_desc = None  # full description (for fielder notation)

    # Running hit counts and perfect-game state for no-hitter reconstruction.
    # away_hits/home_hits = hits BY that team.  pg_intact = pitching team's
    # perfect game is still alive (no opposing batter has reached base).
    running_away_hits   = 0
    running_home_hits   = 0
    home_pg_intact      = True   # home pitcher's PG (away team has no baserunners)
    away_pg_intact      = True   # away pitcher's PG (home team has no baserunners)

    # Header event stream: (time, token) pairs feeding half_inning_plays
    # reconstruction, mirroring game_detail_fetch's game_plays list.
    header_events = []
    _last_header_half = None   # (inning, isTopInning) of the last appended token

    for i, play in enumerate(all_plays):
        about  = play.get('about', {})
        result = play.get('result', {})
        inning      = about.get('inning', 1)
        half_inning = about.get('halfInning', 'top')

        if first_pitch is None:
            st = about.get('startTime', '')
            if st:
                try:
                    first_pitch = _parse_mlb_time(st)
                except ValueError:
                    pass

        # --- Extract pitch-level events for minute-by-minute state ---
        # Score during this at-bat = score as of the end of the last completed play.
        at_bat_away = running_away
        at_bat_home = running_home

        matchup = play.get('matchup', {})
        at_bat_pitcher   = matchup.get('pitcher', {}).get('fullName') or ''
        at_bat_batter    = matchup.get('batter',  {}).get('fullName') or ''
        at_bat_batter_id = matchup.get('batter',  {}).get('id')
        # Runners at START of this at-bat = running_runners before the play completes
        at_bat_runners = dict(running_runners)
        at_bat_runner_ids = dict(running_runner_ids)

        # Per-at-bat pitch detail state (reset for each play/at-bat)
        ab_pitch_num       = 0
        ab_strike_calls    = []
        ab_last_pitch_spd  = None
        ab_last_pitch_type = None
        ab_last_strike     = ''
        ab_last_call_code  = ''
        _review_added_this_play = False

        for ev in play.get('playEvents', []):
            # Header events: in-play actions (steals, pickoffs, wild pitches, ...)
            # and challenge/replay reviews, timestamped by the event itself so
            # they can be filtered to "as of target_utc" later.
            if ev.get('type') == 'action':
                _hcode = _header_action_code((ev.get('details', {}).get('eventType') or '').lower())
                if _hcode and (not header_events or header_events[-1][1] != _hcode):
                    _hev_time_str = ev.get('startTime', '')
                    try:
                        _hev_time = _parse_mlb_time(_hev_time_str) if _hev_time_str else None
                    except ValueError:
                        _hev_time = None
                    if _hev_time:
                        _this_half = (inning, half_inning == 'top')
                        if _last_header_half and _this_half != _last_header_half:
                            header_events.append((_hev_time, '^' if _this_half[1] else 'v'))
                        header_events.append((_hev_time, _hcode))
                        _last_header_half = _this_half
            _hrd = ev.get('reviewDetails')
            if _hrd and not _hrd.get('inProgress') and not _review_added_this_play:
                _hev_time_str2 = ev.get('startTime', '')
                try:
                    _hev_time2 = _parse_mlb_time(_hev_time_str2) if _hev_time_str2 else None
                except ValueError:
                    _hev_time2 = None
                if _hev_time2:
                    header_events.append(
                        (_hev_time2, 'CHAL W' if _hrd.get('isOverturned') else 'CHAL L')
                    )
                    _review_added_this_play = True
            # ABS challenge tracking
            rd = ev.get('reviewDetails')
            if rd and ev.get('type') == 'pitch':
                if not rd.get('inProgress') and not rd.get('isOverturned'):
                    ch_team = rd.get('challengeTeamId')
                    if ch_team == away_id:
                        away_chal_used += 1
                    elif ch_team == home_id:
                        home_chal_used += 1

            # Per-at-bat pitch details — only for actual pitch deliveries
            is_pitch = ev.get('isPitch', False)
            pitch_data = ev.get('pitchData', {}) if is_pitch else {}
            coords     = pitch_data.get('coordinates', {})
            ab_px = coords.get('pX') if is_pitch else None
            ab_pz = coords.get('pZ') if is_pitch else None
            if is_pitch:
                ab_pitch_num += 1
                details   = ev.get('details', {})
                call_code = (details.get('call', {}).get('code', '') or '').upper()
                raw_type  = details.get('type', {}).get('code', '') or ''
                ab_last_pitch_type = _PITCH_TYPE_ABBR.get(raw_type, raw_type) if raw_type else None
                ab_last_pitch_spd  = pitch_data.get('startSpeed')
                ab_last_call_code  = call_code
                ab_last_strike = ''
                if call_code in ('S', 'W', 'T', 'O', 'M'):   # swinging / missed bunt
                    ab_last_strike = 'S'
                    if len(ab_strike_calls) < 2:
                        ab_strike_calls.append('S')
                elif call_code == 'C':                          # called strike
                    ab_last_strike = 'L'
                    if len(ab_strike_calls) < 2:
                        ab_strike_calls.append('C')
                elif call_code in ('F', 'L', 'R'):             # foul
                    ab_last_strike = 'F'
                    if len(ab_strike_calls) < 2:
                        ab_strike_calls.append('F')

            ev_time_str = ev.get('startTime', '')
            if not ev_time_str:
                continue
            try:
                ev_time = _parse_mlb_time(ev_time_str)
            except ValueError:
                continue
            count = ev.get('count', {})
            pitch_events.append({
                'time':               ev_time,
                'balls':              count.get('balls', 0) or 0,
                'strikes':            count.get('strikes', 0) or 0,
                'outs':               count.get('outs', about.get('outs', 0)) or 0,
                'inning':             inning,
                'half_inning':        half_inning,
                'away_score':         at_bat_away,
                'home_score':         at_bat_home,
                'pitcher':            at_bat_pitcher,
                'batter':             at_bat_batter,
                'batter_id':          at_bat_batter_id,
                'runner_on_first':    at_bat_runners['first'],
                'runner_on_second':   at_bat_runners['second'],
                'runner_on_third':    at_bat_runners['third'],
                'runner_first_number':  player_jersey.get(at_bat_runner_ids['first']),
                'runner_second_number': player_jersey.get(at_bat_runner_ids['second']),
                'runner_third_number':  player_jersey.get(at_bat_runner_ids['third']),
                # Pitch detail fields — populated for pitch events; non-pitch
                # events carry over the last pitch values so they're always fresh.
                'is_pitch':           is_pitch,
                'at_bat_pitch_count': ab_pitch_num,
                'last_pitch_speed':   ab_last_pitch_spd,
                'last_pitch_type':    ab_last_pitch_type or '',
                'last_strike_call':   ab_last_strike,
                'strike_calls':       list(ab_strike_calls),
                # Pitch location + call code — only meaningful for isPitch events;
                # None/'' for action/substitution events in the same at-bat.
                'px':         ab_px,
                'pz':         ab_pz,
                'sz_top':     pitch_data.get('strikeZoneTop') if is_pitch else None,
                'sz_bot':     pitch_data.get('strikeZoneBottom') if is_pitch else None,
                'call_code':  ab_last_call_code if is_pitch else '',
                'pt_abbr':    ab_last_pitch_type or '' if is_pitch else '',
                'ab_seq':     ab_pitch_num if is_pitch else 0,
            })

        # --- Completed-play timeline (for score/inning snapshots) ---
        if not about.get('isComplete', False):
            continue
        end_str = about.get('endTime', '')
        if not end_str:
            continue
        try:
            end_time = _parse_mlb_time(end_str)
        except ValueError:
            continue

        away_score = result.get('awayScore', 0) or 0
        home_score = result.get('homeScore', 0) or 0

        post_first  = (matchup.get('postOnFirst')  or {}).get('fullName') or None
        post_second = (matchup.get('postOnSecond') or {}).get('fullName') or None
        post_third  = (matchup.get('postOnThird')  or {}).get('fullName') or None
        post_first_id  = (matchup.get('postOnFirst')  or {}).get('id')
        post_second_id = (matchup.get('postOnSecond') or {}).get('id')
        post_third_id  = (matchup.get('postOnThird')  or {}).get('id')
        running_runners = {'first': post_first, 'second': post_second, 'third': post_third}
        running_runner_ids = {'first': post_first_id, 'second': post_second_id, 'third': post_third_id}

        # Track hits and perfect-game state for no-hitter reconstruction.
        play_event = result.get('event', '')
        _is_hit = play_event in _HIT_EVENTS
        _counts_as_ab = bool(play_event) and play_event not in _NOT_AB_EVENTS
        # result.isOut=False → batter reached base → breaks the pitching team's PG.
        _batter_reached = not result.get('isOut', True)
        if half_inning == 'top':     # away team batting
            if _is_hit:
                running_away_hits += 1
            if _batter_reached:
                home_pg_intact = False  # home pitcher's PG is broken
        else:                        # home team batting
            if _is_hit:
                running_home_hits += 1
            if _batter_reached:
                away_pg_intact = False  # away pitcher's PG is broken

        # Finalized play notation for the header (e.g. '6-3', 'K', 'F9', '3R HR'),
        # mirroring game_detail_fetch's game_plays construction.
        _et_h = (result.get('eventType') or '').lower().replace(' ', '_')
        _this_header_half = (inning, half_inning == 'top')
        if _et_h == 'pitching_substitution':
            if not header_events or header_events[-1][1] != 'PC':
                if _last_header_half and _this_header_half != _last_header_half:
                    header_events.append((end_time, '^' if _this_header_half[1] else 'v'))
                header_events.append((end_time, 'PC'))
                _last_header_half = _this_header_half
        elif _et_h not in _HEADER_SUBST_EVENT_TYPES and play_event.strip():
            _note = _build_scorecard_notation(play)
            _rbi = int(result.get('rbi') or 0)
            _is_err = _note.startswith('E') or ' E' in _note
            if _rbi > 0 and not _is_err:
                if _note == 'HR':
                    if _rbi == 4:
                        _note = 'Grand Slam'
                    elif _rbi >= 2:
                        _note = f'{_rbi}R HR'
                elif _rbi == 1:
                    _note = f'RBI {_note}'
                else:
                    _note = f'{_rbi}RBI {_note}'
            if _last_header_half and _this_header_half != _last_header_half:
                header_events.append((end_time, '^' if _this_header_half[1] else 'v'))
            header_events.append((end_time, _note))
            _last_header_half = _this_header_half

        # Batted-ball landing spot for the field diagram (mirrors
        # game_detail_fetch._extract_all_hit_coordinates, unavailable for past games).
        _hit_data = play.get('hitData', {})
        _hx = _hit_data.get('coordinates', {}).get('coordX')
        _hy = _hit_data.get('coordinates', {}).get('coordY')
        if _hx is None or _hy is None:
            for _pe in play.get('playEvents', []):
                _pe_hit_data = _pe.get('hitData', {})
                _hx = _pe_hit_data.get('coordinates', {}).get('coordX')
                _hy = _pe_hit_data.get('coordinates', {}).get('coordY')
                if _hx is not None and _hy is not None:
                    break
        if _hx is not None and _hy is not None:
            hit_events.append({
                'time':     end_time,
                'x':        _hx,
                'y':        _hy,
                'is_hr':    play_event == 'Home Run',
                'is_out':   not _is_hit,
                # Credits-based notation (e.g. 'F9', 'L4') shows the fielder who
                # made the catch/play, matching the live-game field diagram.
                'abbr':     _build_scorecard_notation(play) or
                            _EVENT_ABBR.get(play_event, play_event[:2].upper() if play_event else '?'),
                'distance': _hit_data.get('totalDistance'),
            })

        timeline.append({
            'end_time':           end_time,
            'away_score':         away_score,
            'home_score':         home_score,
            'inning':             inning,
            'half_inning':        half_inning,
            'outs':               about.get('outs', 0),
            'outs_after':         play.get('count', {}).get('outs', 0) or 0,
            'pitcher':            at_bat_pitcher,
            'batter':             at_bat_batter,
            'batter_id':          at_bat_batter_id,
            'runner_on_first':    post_first,
            'runner_on_second':   post_second,
            'runner_on_third':    post_third,
            'runner_first_number':  player_jersey.get(post_first_id),
            'runner_second_number': player_jersey.get(post_second_id),
            'runner_third_number':  player_jersey.get(post_third_id),
            # Cumulative hit counts and PG state as of this play's completion.
            'away_hits_so_far':   running_away_hits,
            'home_hits_so_far':   running_home_hits,
            'home_pg_intact':     home_pg_intact,
            'away_pg_intact':     away_pg_intact,
            'is_hit':             _is_hit,
            'counts_as_ab':       _counts_as_ab,
        })

        if away_chal_used > 0 or home_chal_used > 0:
            challenge_events.append({
                'time':           end_time,
                'away_remaining': max(0, _GIF_ABS_CHALLENGE_MAX - away_chal_used),
                'home_remaining': max(0, _GIF_ABS_CHALLENGE_MAX - home_chal_used),
            })

        running_away = away_score
        running_home = home_score

        # --- Win probability and last-play at this play boundary ---
        wp_entry = wp_by_index.get(i, {})
        away_wp = wp_entry.get('awayTeamWinProbability')
        home_wp = wp_entry.get('homeTeamWinProbability')
        if away_wp is not None:
            away_wp = float(away_wp)
            if away_wp <= 1.0:
                away_wp *= 100
        if home_wp is not None:
            home_wp = float(home_wp)
            if home_wp <= 1.0:
                home_wp *= 100

        # Advance last_play description (skip substitutions/timeouts)
        wp_result    = wp_entry.get('result', {})
        event        = wp_result.get('event') or result.get('event') or ''
        event_type   = (wp_result.get('eventType') or '').lower()
        if event and not any(s in event_type for s in _WP_SKIP_TYPES):
            cumulative_last_play      = event
            cumulative_last_play_inn  = inning
            cumulative_last_play_top  = (half_inning == 'top')
            cumulative_last_play_desc = (
                wp_result.get('description') or result.get('description') or ''
            )

        wp_events.append({
            'time':            end_time,
            'away_wp':         away_wp,
            'home_wp':         home_wp,
            'last_play':       cumulative_last_play,
            'last_play_inn':   cumulative_last_play_inn,
            'last_play_top':   cumulative_last_play_top,
            'last_play_desc':  cumulative_last_play_desc,
        })

    timeline.sort(key=lambda p: p['end_time'])
    pitch_events.sort(key=lambda e: e['time'])
    wp_events.sort(key=lambda e: e['time'])
    hit_events.sort(key=lambda e: e['time'])
    header_events.sort(key=lambda t: t[0])

    # First pitch event where a ball or strike was actually registered
    first_actual_pitch = None
    for pe in pitch_events:
        if (pe.get('balls', 0) or 0) + (pe.get('strikes', 0) or 0) > 0:
            first_actual_pitch = pe['time']
            break
    if first_actual_pitch is None and timeline:
        first_actual_pitch = timeline[0]['end_time']  # first completed play as fallback

    # Build next_batters_events: for each inning break, compute the 3 upcoming batters
    away_pids   = [pid for pid, _ in away_order]
    home_pids   = [pid for pid, _ in home_order]
    pid_to_name = {pid: name for pid, name in away_order + home_order}
    next_batters_events = []

    for i, play in enumerate(timeline):
        if play.get('outs_after', 0) < 3:
            continue
        curr_half = play['half_inning']
        if curr_half == 'top':
            batting_side = 'home'
            batting_half = 'bottom'
        else:
            batting_side = 'away'
            batting_half = 'top'

        batting_pids = home_pids if batting_side == 'home' else away_pids
        if not batting_pids:
            continue

        # Last batter from this team in their most recent prior half-inning
        last_batter_id = None
        for prev in reversed(timeline[:i + 1]):
            if prev['half_inning'] == batting_half:
                last_batter_id = prev.get('batter_id')
                break

        if last_batter_id and last_batter_id in batting_pids:
            start = (batting_pids.index(last_batter_id) + 1) % len(batting_pids)
        else:
            start = 0

        n = len(batting_pids)
        next_3 = [batting_pids[(start + k) % n] for k in range(min(3, n))]
        names  = [pid_to_name.get(pid, '') for pid in next_3]

        # Pitcher for the upcoming half: first pitch event after this break in that half
        next_pitcher = ''
        for pe in pitch_events:
            if pe['time'] > play['end_time'] and pe.get('half_inning') == batting_half:
                next_pitcher = pe.get('pitcher', '')
                break

        next_batters_events.append({
            'time':          play['end_time'],
            'next_batter_1': names[0] if len(names) > 0 else '',
            'next_batter_2': names[1] if len(names) > 1 else '',
            'next_batter_3': names[2] if len(names) > 2 else '',
            'next_pitcher':  next_pitcher,
        })

    return {
        'scheduled_start_utc':   scheduled_start,
        'first_pitch_utc':       first_pitch,
        'first_actual_pitch_utc': first_actual_pitch,
        'last_play_utc':         timeline[-1]['end_time'] if timeline else None,
        'plays':                 timeline,
        'hit_events':            hit_events,
        'header_events':         header_events,
        'pitch_events':          pitch_events,
        'wp_events':             wp_events,
        'challenge_events':      challenge_events,
        'next_batters_events':   next_batters_events,
    }


def _inning_runs_at_time(plays, target_utc):
    """Return (away_inning_runs, home_inning_runs) lists reconstructed from plays up to target_utc.

    Away team scores in 'top' halves; home team scores in 'bottom' halves.
    A None value in home_inning_runs means the bottom half hasn't been played yet.
    """
    half_final = {}
    for play in plays:
        if play['end_time'] > target_utc:
            break
        key = (play['inning'], play['half_inning'])
        half_final[key] = (play['away_score'], play['home_score'])

    if not half_final:
        return [], []

    max_inning = max(k[0] for k in half_final)
    away_runs = []
    home_runs = []
    prev_away = 0
    prev_home = 0

    for inn in range(1, max_inning + 1):
        top_key = (inn, 'top')
        bot_key = (inn, 'bottom')

        if top_key not in half_final:
            break
        top_away, _ = half_final[top_key]
        away_runs.append(top_away - prev_away)
        prev_away = top_away

        if bot_key in half_final:
            _, bot_home = half_final[bot_key]
            home_runs.append(bot_home - prev_home)
            prev_home = bot_home
        else:
            home_runs.append(None)

    return away_runs, home_runs


def _build_ab_pitches(pitch_events, last_play, target_utc):
    """Assemble ab_pitches for the current at-bat from stored pitch coordinates.

    Includes only is_pitch events that happened after the last completed play
    and on or before target_utc and have recorded coordinates (pX/pZ).
    Returns a list in the same format consumed by _draw_wide_right_panel.
    """
    cutoff = last_play['end_time'] if last_play else None
    result = []
    seq = 0
    for ev in pitch_events:
        if ev['time'] > target_utc:
            break
        if cutoff and ev['time'] <= cutoff:
            continue
        if not ev.get('is_pitch'):
            continue
        px = ev.get('px')
        pz = ev.get('pz')
        if px is None or pz is None:
            continue
        seq += 1
        result.append({
            'seq':     seq,
            'px':      px,
            'pz':      pz,
            'sz_top':  ev.get('sz_top'),
            'sz_bot':  ev.get('sz_bot'),
            'call':    ev.get('call_code', ''),
            'pt_abbr': ev.get('pt_abbr', ''),
        })
    return result


def _game_state_at_time(base_game, tl, target_utc):
    """Return a copy of base_game with dynamic fields set to game state at target_utc."""
    state = dict(base_game)

    # Preserve terminal non-game statuses (Postponed, Cancelled, Suspended).
    # These have no play data, so the timeline-based logic would otherwise
    # overwrite them with 'Scheduled'.
    if base_game.get('detailed_state') in _TERMINAL_GAME_STATES and not tl.get('plays'):
        return state

    scheduled_start     = tl.get('scheduled_start_utc')
    first_pitch         = tl.get('first_pitch_utc') or scheduled_start
    first_actual_pitch  = tl.get('first_actual_pitch_utc') or first_pitch
    last_play_time      = tl.get('last_play_utc')
    plays               = tl.get('plays', [])

    # --- Before first actual pitch (first ball or strike recorded) ---
    if first_actual_pitch and target_utc < first_actual_pitch:
        state.update({
            'detailed_state': 'Scheduled',
            'away_runs': None, 'home_runs': None,
            'current_inning': None, 'currentInningOrdinal': None, 'inningState': None,
            'num_of_outs': None, 'balls': None, 'strikes': None,
            'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None,
            'away_win_probability': None, 'home_win_probability': None, 'last_play': None,
            'last_play_inning': None, 'last_play_is_top': None, 'last_play_description': '',
            'away_team_is_winner': False, 'home_team_is_winner': False,
            # Final-game attributes; clear them for pre-game frames
            'walk_off': False, 'save_situation': False,
            'no_hitter': False, 'perfect_game': False,
            'away_hits': 0, 'home_hits': 0,
            'sub_event': None, 'ab_pitches': [],
            'batter_hits': None, 'batter_at_bats': None,
            'current_at_bat_complete': False, 'pitch_count': None,
        })
        return state

    # --- After last play with buffer ---
    if last_play_time and target_utc > last_play_time + timedelta(minutes=5):
        final = plays[-1] if plays else None
        state['detailed_state'] = 'Final'
        if final:
            state['away_runs']      = final['away_score']
            state['home_runs']      = final['home_score']
            state['current_inning'] = final['inning']
        state.update({
            'num_of_outs': None, 'balls': None, 'strikes': None,
            'runner_on_first': None, 'runner_on_second': None, 'runner_on_third': None,
            'inningState': None, 'away_win_probability': None,
            'home_win_probability': None,
        })
        # Keep last_play and inning context from final wp_event if available
        wp_events = tl.get('wp_events', [])
        last_wp = wp_events[-1] if wp_events else None
        state['last_play']             = last_wp['last_play'] if last_wp else None
        state['last_play_inning']      = last_wp.get('last_play_inn') if last_wp else None
        state['last_play_is_top']      = last_wp.get('last_play_top') if last_wp else None
        state['last_play_description'] = (last_wp.get('last_play_desc') or '') if last_wp else ''
        return state

    # --- In Progress: reconstruct detailed state from pitch events and completed plays ---
    state['detailed_state'] = 'In Progress'
    # Clear all fields that carry Final-game semantics and would bleed into
    # reconstructed in-progress frames if inherited from base_game unchanged.
    state['walk_off']              = False
    state['no_hitter']             = False
    state['perfect_game']          = False
    state['sub_event']             = None
    state['current_at_bat_complete'] = False
    state['batter_hits']           = None
    state['batter_at_bats']        = None
    state['ab_pitches']            = []
    pitch_events = tl.get('pitch_events', [])

    # Last pitch event before target_utc
    last_event = None
    for ev in pitch_events:
        if ev['time'] <= target_utc:
            last_event = ev
        else:
            break

    # Last completed play before target_utc
    last_play = None
    for play in plays:
        if play['end_time'] <= target_utc:
            last_play = play
        else:
            break

    # Between-plays: last play resolved AFTER the most recent pitch event.
    # This covers the inning break and the gap between plate appearances.
    between_plays = (
        last_play is not None and
        (last_event is None or last_play['end_time'] > last_event['time'])
    )

    if between_plays:
        outs_after = last_play.get('outs_after', 0)
        half = last_play.get('half_inning', 'top')
        state['away_runs']            = last_play['away_score']
        state['home_runs']            = last_play['home_score']
        state['current_inning']       = last_play['inning']
        state['currentInningOrdinal'] = _ordinal(last_play['inning'])
        state['num_of_outs']          = outs_after
        state['balls']                = 0
        state['strikes']              = 0
        state['current_pitcher']      = last_play.get('pitcher') or None
        # Find the first batter of the next half inning so "Due:" can be shown
        _next_event = next(
            (ev for ev in pitch_events if ev['time'] > last_play['end_time']),
            None,
        )
        state['current_hitter'] = _next_event.get('batter') if _next_event else None
        if outs_after >= 3:
            # Inning break: top half done → Mid, bottom half done → End
            state['inningState'] = 'Middle' if half == 'top' else 'End'
        else:
            state['inningState'] = 'Top' if half == 'top' else 'Bottom'
        # No active at-bat during a between-plays gap — clear pitch detail fields.
        state['at_bat_pitch_count'] = 0
        state['last_pitch_speed']   = None
        state['last_pitch_type']    = ''
        state['last_strike_call']   = ''
        state['strike_calls']       = []
    elif last_event:
        # Mid-at-bat: pitch events are more recent than the last play completion
        state['away_runs']            = last_event['away_score']
        state['home_runs']            = last_event['home_score']
        state['current_inning']       = last_event['inning']
        state['currentInningOrdinal'] = _ordinal(last_event['inning'])
        state['num_of_outs']          = last_event['outs']
        state['balls']                = last_event['balls']
        state['strikes']              = last_event['strikes']
        state['current_pitcher']      = last_event.get('pitcher') or None
        state['current_hitter']       = last_event.get('batter') or None
        half = last_event.get('half_inning', 'top')
        state['inningState']          = 'Top' if half == 'top' else 'Bottom'
        # Copy pitch detail fields from the most recent pitch event so the wide
        # box can display pitch speed, type, per-at-bat count, and strike calls.
        state['at_bat_pitch_count'] = last_event.get('at_bat_pitch_count') or 0
        state['last_pitch_speed']   = last_event.get('last_pitch_speed')
        state['last_pitch_type']    = last_event.get('last_pitch_type') or ''
        state['last_strike_call']   = last_event.get('last_strike_call') or ''
        state['strike_calls']       = list(last_event.get('strike_calls') or [])
    else:
        # No pitch events and no completed plays at this timestamp —
        # the game hasn't officially started yet (no first pitch thrown).
        state.update({
            'detailed_state': 'Scheduled',
            'away_runs': None, 'home_runs': None,
            'current_inning': None, 'currentInningOrdinal': None,
            'inningState': None, 'num_of_outs': None,
            'balls': None, 'strikes': None,
            'current_pitcher': None, 'current_hitter': None,
        })

    # Compute save_situation from the reconstructed inning and run differential.
    # base_game always has save_situation=False (Final games have no save situation),
    # so we must recompute it rather than inheriting.
    _inn  = state.get('current_inning') or 0
    _diff = abs((state.get('away_runs') or 0) - (state.get('home_runs') or 0))
    state['save_situation'] = (
        state.get('detailed_state') == 'In Progress'
        and _inn >= 7
        and 1 <= _diff <= 3
    )

    # Reconstruct per-inning run lists from play history so linescore grid shows correct data.
    away_inn, home_inn = _inning_runs_at_time(plays, target_utc)
    state['away_inning_runs'] = away_inn
    state['home_inning_runs'] = home_inn

    # --- Reconstruct fields normally provided by game_detail_fetch ---

    # Hit counts and no-hitter / perfect-game state from play history.
    # These must be derived from plays to target_utc, not inherited from the
    # Final base_game (which would show the final totals from pitch 1).
    _away_hits = 0
    _home_hits = 0
    _home_pg   = True   # home pitcher's perfect game still intact
    _away_pg   = True   # away pitcher's perfect game still intact
    for _p in plays:
        if _p['end_time'] > target_utc:
            break
        _away_hits = _p.get('away_hits_so_far', _away_hits)
        _home_hits = _p.get('home_hits_so_far', _home_hits)
        _home_pg   = _p.get('home_pg_intact', _home_pg)
        _away_pg   = _p.get('away_pg_intact', _away_pg)
    state['away_hits'] = _away_hits
    state['home_hits'] = _home_hits
    # Show no-hitter / perfect-game banner only once the game is past inning 5
    # (mirrors when the MLB API starts setting the flags during a live game).
    if _inn >= _NO_HITTER_INNING_THRESHOLD:
        if _home_pg or _away_pg:
            state['perfect_game'] = True
            state['no_hitter']    = True
        elif _away_hits == 0 or _home_hits == 0:
            state['no_hitter'] = True

    # Strike-zone pitch visualization for the current at-bat.
    state['ab_pitches'] = _build_ab_pitches(pitch_events, last_play, target_utc)

    # Game-level pitch count for the current pitcher, counted from pitch_events.
    _cur_pitcher = state.get('current_pitcher') or ''
    if _cur_pitcher:
        state['pitch_count'] = sum(
            1 for _e in pitch_events
            if _e.get('is_pitch') and _e['time'] <= target_utc
            and _e.get('pitcher') == _cur_pitcher
        )
    else:
        state['pitch_count'] = None

    # Batter game stats (hits / at-bats) for the current batter.
    _cur_batter_id = (
        (last_event.get('batter_id') if last_event else None)
        or (last_play.get('batter_id') if last_play else None)
    )
    if _cur_batter_id:
        _b_hits = sum(1 for _p in plays if _p['end_time'] <= target_utc
                      and _p.get('batter_id') == _cur_batter_id
                      and _p.get('is_hit'))
        _b_abs  = sum(1 for _p in plays if _p['end_time'] <= target_utc
                      and _p.get('batter_id') == _cur_batter_id
                      and _p.get('counts_as_ab'))
        state['batter_hits']     = _b_hits
        state['batter_at_bats']  = _b_abs
        state['current_play_batter'] = state.get('current_hitter') or ''

    # --- Win probability and last-play: find last wp_event before target_utc ---
    wp_events = tl.get('wp_events', [])
    last_wp = None
    for wp in wp_events:
        if wp['time'] <= target_utc:
            last_wp = wp
        else:
            break

    if last_wp:
        state['away_win_probability']  = last_wp['away_wp']
        state['home_win_probability']  = last_wp['home_wp']
        state['last_play']             = last_wp['last_play']
        state['last_play_inning']      = last_wp.get('last_play_inn')
        state['last_play_is_top']      = last_wp.get('last_play_top')
        state['last_play_description'] = last_wp.get('last_play_desc') or ''
    else:
        state['away_win_probability']  = None
        state['home_win_probability']  = None
        state['last_play']             = None
        state['last_play_inning']      = None
        state['last_play_is_top']      = None
        state['last_play_description'] = ''

    # Runner state: use last_event (mid-at-bat) or last_play (between at-bats).
    # During an inning break (outs_after >= 3) bases are empty.
    if last_event and not between_plays:
        state['runner_on_first']  = last_event.get('runner_on_first')
        state['runner_on_second'] = last_event.get('runner_on_second')
        state['runner_on_third']  = last_event.get('runner_on_third')
        state['runner_first_number']  = last_event.get('runner_first_number')
        state['runner_second_number'] = last_event.get('runner_second_number')
        state['runner_third_number']  = last_event.get('runner_third_number')
    elif between_plays and last_play and last_play.get('outs_after', 0) < 3:
        state['runner_on_first']  = last_play.get('runner_on_first')
        state['runner_on_second'] = last_play.get('runner_on_second')
        state['runner_on_third']  = last_play.get('runner_on_third')
        state['runner_first_number']  = last_play.get('runner_first_number')
        state['runner_second_number'] = last_play.get('runner_second_number')
        state['runner_third_number']  = last_play.get('runner_third_number')
    else:
        state['runner_on_first']  = None
        state['runner_on_second'] = None
        state['runner_on_third']  = None
        state['runner_first_number']  = None
        state['runner_second_number'] = None
        state['runner_third_number']  = None

    # Batted-ball markers for the field diagram: last 7 balls in play up to target_utc.
    state['recent_hits'] = [
        h for h in tl.get('hit_events', []) if h['time'] <= target_utc
    ][-7:]

    # Header play-by-play strip (same "half_inning_plays" field the live 2-cell/
    # 3-cell header reads): last 7 events, plus interleaved inning-break markers,
    # as of target_utc.
    _header_tokens = [tok for (t, tok) in tl.get('header_events', []) if t <= target_utc]
    _kept_tokens = []
    _header_event_count = 0
    for _tok in reversed(_header_tokens):
        _kept_tokens.append(_tok)
        if _tok not in ('^', 'v'):
            _header_event_count += 1
            if _header_event_count >= 7:
                break
    state['half_inning_plays'] = list(reversed(_kept_tokens))

    # ABS challenges: replay cumulative state up to target_utc.
    # Default to full allotment when no challenges have been used yet.
    if state.get('detailed_state') == 'In Progress':
        challenge_events = tl.get('challenge_events', [])
        last_challenge = None
        for ce in challenge_events:
            if ce['time'] <= target_utc:
                last_challenge = ce
            else:
                break
        # ABS challenge max grows by 1 per extra inning (10th = 3, 11th = 4, …)
        _cur_inn = state.get('current_inning') or 9
        _abs_max = _GIF_ABS_CHALLENGE_MAX + max(0, int(_cur_inn) - 9)
        if last_challenge:
            state['away_challenges_remaining'] = last_challenge['away_remaining']
            state['home_challenges_remaining'] = last_challenge['home_remaining']
        else:
            state['away_challenges_remaining'] = _abs_max
            state['home_challenges_remaining'] = _abs_max

    # Next 3 batters + pitcher: shown during inning breaks (Middle/End)
    if state.get('inningState') in ('Middle', 'End'):
        next_batters_events = tl.get('next_batters_events', [])
        last_nb = None
        for nbe in next_batters_events:
            if nbe['time'] <= target_utc:
                last_nb = nbe
            else:
                break
        if last_nb:
            state['next_batter_1'] = last_nb['next_batter_1']
            state['next_batter_2'] = last_nb['next_batter_2']
            state['next_batter_3'] = last_nb['next_batter_3']
            state['next_pitcher']  = last_nb.get('next_pitcher', '')

    return state


def _any_game_active(game_timelines, current_utc):
    """Return True if any game has had at least one pitch thrown by current_utc
    and hasn't ended more than 5 minutes ago.

    pitch_events includes pre-game advisory/action events (mound visits, lineup
    substitutions) with count 0-0.  Use the first event where balls+strikes > 0
    (an actual pitch registered) or the first completed play, so pre-game
    advisory events don't count as the game start.
    """
    for tl in game_timelines.values():
        last_play    = tl.get('last_play_utc')
        pitch_events = tl.get('pitch_events', [])
        plays        = tl.get('plays', [])

        # First pitch event that registered a ball or strike
        game_start = None
        for ev in pitch_events:
            if (ev.get('balls', 0) or 0) + (ev.get('strikes', 0) or 0) > 0:
                game_start = ev['time']
                break
        # Fall back to first completed play (handles first-pitch-hit where count stays 0-0)
        if game_start is None and plays:
            game_start = plays[0]['end_time']
        # Last resort: first_pitch_utc from the schedule
        if game_start is None:
            game_start = tl.get('first_pitch_utc')

        if not game_start or current_utc < game_start:
            continue
        game_end = (last_play + timedelta(minutes=5)) if last_play else (game_start + timedelta(hours=4))
        if current_utc <= game_end:
            return True
    return False


def generate_gif(date_str, gif_start, gif_end, output_path, interval_min, frame_delay_ms, sport_id, config_data):
    """Generate an animated GIF of the scoreboard for a game day.

    Fetches each game's full play-by-play feed once (O(N_games) API calls),
    then reconstructs game state at every minute in memory — no per-minute
    API calls.  Time window is auto-detected from first pitch / last play
    when --gif-start / --gif-end are not provided.
    """
    from generate_image import orchestrate_score_board

    tz_str   = config_data.get('timezone', 'America/Chicago')
    local_tz = pytz.timezone(tz_str)

    # --- Step 1: Fetch base schedule (final/current state for team/game metadata) ---
    print(f"Fetching schedule for {date_str}...")
    fetch_scoreboard_for_date(date_str, sport_id)
    base_games = load_json_file('games.json').get('games', [])
    team_data  = load_json_file('teams.json') or {}
    if 'team_abbreviation' not in team_data:
        team_data = {'team_abbreviation': {}}

    if not base_games:
        print(f"No games found for {date_str}")
        return

    # --- Step 1a: Attach pre-game weather to every game for Scheduled frames ---
    print("Attaching weather data...")
    try:
        from weather import get_forecast
        _weather_cfg = config_data.get('weather') or {}
        if _weather_cfg.get('enabled', True):
            for _g in base_games:
                _venue = _g.get('venue')
                _gdate = _g.get('game_date')
                if not _venue or not _gdate:
                    continue
                _stadium = _lookup_stadium(None, _venue)
                if _stadium is None:
                    continue
                if _stadium.get('roof') == 'fixed':
                    _g['roof_state'] = 'fixed'
                _fc = get_forecast(
                    _venue,
                    _stadium.get('lat'),
                    _stadium.get('lon'),
                    _gdate,
                    cache_ttl_minutes=_weather_cfg.get('cache_ttl_minutes', 60),
                )
                if _fc:
                    _g['weather_temp_f']    = _fc.get('temp_f')
                    _g['weather_wind_mph']  = _fc.get('wind_mph')
                    _g['weather_wind_dir']  = _fc.get('wind_dir')
                    _g['weather_precip_pct'] = _fc.get('precip_pct')
    except Exception as _we:
        print(f"  weather attach error: {_we}")

    # --- Step 1b: Fetch standings as of this date so wildcard/division data is accurate ---
    print(f"Fetching standings for {date_str}...")
    try:
        from standings import get_standings
        _date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        get_standings([103, 104], season=_date_obj.year, date=_date_obj.strftime('%m/%d/%Y'))
        print("  standings ok")
        _prev_date = _date_obj - timedelta(days=1)
        get_standings([103, 104], season=_prev_date.year,
                      date=_prev_date.strftime('%m/%d/%Y'), save_as='standings_prev')
        print("  prev standings ok")
    except Exception as _e:
        print(f"  standings error: {_e} (using cached)")

    # --- Step 2: Fetch play-by-play timeline once per game ---
    print(f"Fetching play-by-play for {len(base_games)} game(s)...")
    game_timelines   = {}
    all_first_pitches = []
    all_last_plays    = []

    for game in base_games:
        game_pk = game.get('game_pk')
        if not game_pk:
            continue
        print(f"  game {game_pk}...", end=' ', flush=True)
        try:
            tl = _fetch_game_timeline(game_pk)
            game_timelines[str(game_pk)] = tl
            anchor = tl.get('first_actual_pitch_utc') or tl.get('first_pitch_utc') or tl.get('scheduled_start_utc')
            if anchor:
                all_first_pitches.append(anchor)
            if tl.get('last_play_utc'):
                all_last_plays.append(tl['last_play_utc'])
            print("ok")
        except Exception as e:
            print(f"error: {e}")

    if not game_timelines:
        print("No timeline data fetched — aborting.")
        return

    # --- Step 3: Determine time window ---
    if gif_start and gif_end:
        start_dt = local_tz.localize(datetime.strptime(f"{date_str} {gif_start}", "%Y-%m-%d %H:%M"))
        end_dt   = local_tz.localize(datetime.strptime(f"{date_str} {gif_end}",   "%Y-%m-%d %H:%M"))
    else:
        if not all_first_pitches:
            print("Cannot determine start time — provide --gif-start/--gif-end")
            return
        start_utc = min(all_first_pitches)
        end_utc   = (max(all_last_plays) + timedelta(minutes=5)) if all_last_plays \
                    else max(all_first_pitches) + timedelta(hours=4)
        start_dt = start_utc.astimezone(local_tz)
        end_dt   = end_utc.astimezone(local_tz)
        print(f"Auto-detected window: {start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')} {tz_str}")

    if end_dt <= start_dt:
        print("End time is before start time — aborting.")
        return

    total_steps = int((end_dt - start_dt).total_seconds() / 60 / interval_min) + 1
    print(f"Generating {total_steps}-frame GIF ({interval_min}min intervals, {frame_delay_ms}ms/frame)")
    print(f"  Output: {output_path}")

    # --- Step 4: Render each frame from in-memory timelines ---
    frames     = []
    durations  = []   # per-frame delay in ms; final frame holds longer
    current_dt = start_dt
    step = 0

    while current_dt <= end_dt:
        step += 1
        current_utc = current_dt.astimezone(pytz.utc)
        time_label  = current_dt.strftime("%H:%M")

        if not _any_game_active(game_timelines, current_utc):
            print(f"  [    dead] {current_dt.strftime('%H:%M')} — no active games, skipping")
            current_dt += timedelta(minutes=interval_min)
            continue

        print(f"  [{step:4d}/{total_steps}] {time_label}...", end=' ', flush=True)

        frame_games = []
        for game in base_games:
            pk_str = str(game.get('game_pk', ''))
            tl = game_timelines.get(pk_str)
            frame_games.append(_game_state_at_time(game, tl, current_utc) if tl else dict(game))

        try:
            result = orchestrate_score_board(frame_games, team_data, date_str, bypass_cache=True)
            if result:
                image, _ = result
                frames.append(image.convert('L').convert('P'))
                durations.append(frame_delay_ms)
                print("ok")
            else:
                print("skip")
        except Exception as e:
            print(f"error: {e}")

        current_dt += timedelta(minutes=interval_min)

    # --- Step 4b: Trailing final frame — all games in their end state ---
    # Use a target time well past all last plays so every game enters the Final
    # branch of _game_state_at_time (requires target > last_play + 5 min).
    # Skip when any game is still active (no last_play_utc) — generating a
    # "final" frame with in-progress games would misrepresent the scoreboard.
    _any_active = any(
        game_timelines.get(str(g.get('game_pk', '')), {}).get('last_play_utc') is None
        for g in base_games if str(g.get('game_pk', '')) in game_timelines
    )
    if all_last_plays and not _any_active:
        final_utc = max(all_last_plays) + timedelta(minutes=10)
        print("  [final ] rendering trailing end-state frame...", end=' ', flush=True)
        final_games = []
        for game in base_games:
            pk_str = str(game.get('game_pk', ''))
            tl = game_timelines.get(pk_str)
            final_games.append(_game_state_at_time(game, tl, final_utc) if tl else dict(game))
        try:
            result = orchestrate_score_board(final_games, team_data, date_str, bypass_cache=True)
            if result:
                image, _ = result
                frames.append(image.convert('L').convert('P'))
                durations.append(3000)  # hold the final scoreboard for 3 s
                print("ok")
            else:
                print("skip")
        except Exception as e:
            print(f"error: {e}")

    # --- Step 5: Save GIF ---
    if not frames:
        print("No frames generated — GIF not saved.")
        return

    print(f"Assembling {len(frames)}-frame GIF...")
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        optimize=False,
        duration=durations,
        loop=0,
    )
    print(f"✓ GIF saved to {output_path}")

    mp4_path = os.path.splitext(output_path)[0] + '.mp4'
    try:
        import imageio
        import numpy as np
        fps = 1000 / frame_delay_ms
        final_hold_frames = max(1, round(3000 / frame_delay_ms))
        writer = imageio.get_writer(mp4_path, fps=fps, codec='libx264', quality=8)
        for frame in frames[:-1]:
            writer.append_data(np.array(frame.convert('RGB')))
        # Repeat the final frame so it holds for ~3 seconds in the MP4
        if frames:
            final_arr = np.array(frames[-1].convert('RGB'))
            for _ in range(final_hold_frames):
                writer.append_data(final_arr)
        writer.close()
        print(f"✓ MP4 saved to {mp4_path}")
    except ImportError:
        print("imageio not installed — skipping MP4 (pip install imageio[ffmpeg])")


def main():
    """CLI entry point: generate a GIF/MP4 timelapse of scoreboard frames for a past game day."""
    parser = argparse.ArgumentParser(
        description='Generate a GIF/MP4 timelapse of the scoreboard for a past game day.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Auto-detect window (first pitch to last out)
  python src/timelapse.py --date 2026-04-01

  # Manual window override
  python src/timelapse.py --date 2026-04-01 --start 18:00 --end 23:00 --interval 5 --delay 300
        ''',
    )
    parser.add_argument('--date', required=True, help='Date to generate the timelapse for (YYYY-MM-DD)')
    parser.add_argument('--start', metavar='HH:MM', help='Window start (local time). Auto-detected if omitted.')
    parser.add_argument('--end', metavar='HH:MM', help='Window end (local time). Requires --start.')
    parser.add_argument('--output', default='scoreboard_timelapse.gif', metavar='FILE',
                         help='Output path for the GIF (default: scoreboard_timelapse.gif)')
    parser.add_argument('--interval', type=int, default=1, metavar='MINUTES',
                         help='Minutes between frames (default: 1)')
    parser.add_argument('--delay', type=int, default=500, metavar='MS',
                         help='Delay between frames in milliseconds (default: 500)')
    parser.add_argument('--sport-id', type=int, help='Sport ID (1=MLB, 8=WBC, etc). Default: from config.yaml')
    args = parser.parse_args()

    if bool(args.start) != bool(args.end):
        parser.error('--start and --end must be used together')

    config_data = load_yaml_file('config.yaml')
    generate_gif(
        args.date, args.start, args.end, args.output,
        args.interval, args.delay, args.sport_id, config_data,
    )


if __name__ == '__main__':
    main()
