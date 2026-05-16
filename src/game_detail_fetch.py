import requests


def select_game(games, favorite_abbr, team_data):
    """Pick a game to display: favorite team's game (prefer live > scheduled > final),
    else first live game, else first game."""
    abbr_map = team_data.get('team_abbreviation', {})
    # Reverse map: abbr -> team_id strings
    id_for_abbr = {}
    for tid, ab in abbr_map.items():
        id_for_abbr[ab] = tid

    fav_ids = set()
    if favorite_abbr:
        fav_id = id_for_abbr.get(favorite_abbr)
        if fav_id:
            fav_ids.add(int(fav_id))

    fav_games = []
    live_games = []
    for g in games:
        is_fav = (g.get('away_team_id') in fav_ids or g.get('home_team_id') in fav_ids)
        state = g.get('detailed_state', '')
        is_live = state == 'In Progress'
        is_scheduled = state in ('Scheduled', 'Pre-Game', 'Warmup')
        is_final = state in ('Final', 'Game Over', 'Final: Tied', 'Completed Early')

        if is_fav:
            priority = 0 if is_live else (1 if is_scheduled else (2 if is_final else 3))
            fav_games.append((priority, g))
        if is_live:
            live_games.append(g)

    if fav_games:
        fav_games.sort(key=lambda x: x[0])
        return fav_games[0][1]
    if live_games:
        return live_games[0]
    if games:
        return games[0]
    return None


def fetch_live_feed(game_pk):
    """Fetch the full live feed for a game."""
    url = f'https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live'
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _extract_pitches_detailed(plays):
    """Extract pitch data with velocity and pitch type from current or last at-bat."""
    sources = [plays.get('currentPlay', {})]
    all_plays = plays.get('allPlays', [])
    if all_plays:
        sources.append(all_plays[-1])

    for play in sources:
        pitches = []
        seq = 0
        for event in play.get('playEvents', []):
            if not event.get('isPitch'):
                continue
            seq += 1
            pitch_data = event.get('pitchData', {})
            coords = pitch_data.get('coordinates', {})
            px = coords.get('pX')
            pz = coords.get('pZ')
            if px is None or pz is None:
                continue
            details = event.get('details', {})
            pitches.append({
                'seq': seq,
                'px': px,
                'pz': pz,
                'code': details.get('type', {}).get('code', ''),
                'pitch_type': details.get('type', {}).get('description', ''),
                'description': details.get('description', ''),
                'is_strike': details.get('isStrike', False),
                'is_ball': details.get('isBall', False),
                'speed': pitch_data.get('startSpeed'),
            })
        if pitches:
            return pitches
    return []


def fetch_pitch_view_data(game_pk):
    """Extract pitch view data from the live feed."""
    data = fetch_live_feed(game_pk)
    game_data = data.get('gameData', {})
    live_data = data.get('liveData', {})
    plays = live_data.get('plays', {})
    linescore = live_data.get('linescore', {})
    boxscore = live_data.get('boxscore', {})

    status = game_data.get('status', {})
    teams = game_data.get('teams', {})
    away_team = teams.get('away', {})
    home_team = teams.get('home', {})

    offense = linescore.get('offense', {})
    batter_id = offense.get('batter', {}).get('id')
    pitcher_id = linescore.get('defense', {}).get('pitcher', {}).get('id')

    return {
        'detailed_state': status.get('detailedState', ''),
        'away_abbr': away_team.get('abbreviation', ''),
        'home_abbr': home_team.get('abbreviation', ''),
        'away_id': away_team.get('id', 0),
        'home_id': home_team.get('id', 0),
        'away_runs': linescore.get('teams', {}).get('away', {}).get('runs', 0),
        'home_runs': linescore.get('teams', {}).get('home', {}).get('runs', 0),
        'inning_ordinal': linescore.get('currentInningOrdinal', ''),
        'inning_state': linescore.get('inningState', ''),
        'balls': linescore.get('balls', 0) or 0,
        'strikes': linescore.get('strikes', 0) or 0,
        'outs': linescore.get('outs', 0) or 0,
        'batter': _get_player_info(boxscore, batter_id, 'batting'),
        'pitcher': _get_player_info(boxscore, pitcher_id, 'pitching'),
        'pitches': _extract_pitches_detailed(plays),
    }


_ABS_CHALLENGE_MAX = 2
_REPLAY_CHALLENGE_MAX = 1


def _count_abs_challenges_used(plays, away_id, home_id):
    """Count unsuccessful ABS challenges (on pitch events) per team."""
    away_used, home_used = 0, 0
    if not (away_id and home_id):
        return away_used, home_used
    for play in plays.get('allPlays', []):
        for ev in play.get('playEvents', []):
            rd = ev.get('reviewDetails')
            if not rd or ev.get('type') != 'pitch':
                continue
            if rd.get('inProgress') or rd.get('isOverturned'):
                continue
            team = rd.get('challengeTeamId')
            if team == away_id:
                away_used += 1
            elif team == home_id:
                home_used += 1
    return away_used, home_used


def _count_replay_challenges_used(plays, away_id, home_id):
    """Count unsuccessful replay challenges (on non-pitch events) per team."""
    away_used, home_used = 0, 0
    if not (away_id and home_id):
        return away_used, home_used
    for play in plays.get('allPlays', []):
        for ev in play.get('playEvents', []):
            rd = ev.get('reviewDetails')
            if not rd or ev.get('type') == 'pitch':
                continue
            if rd.get('inProgress') or rd.get('isOverturned'):
                continue
            team = rd.get('challengeTeamId')
            if team == away_id:
                away_used += 1
            elif team == home_id:
                home_used += 1
    return away_used, home_used


def _find_recent_review_result(plays):
    """Return 'Call Overturned', 'Call Stands', or None if a review just resolved.

    A review is considered fresh if no pitch has been thrown since it completed:
    - ABS challenge mid-AB: check currentPlay events from the end
    - Play-ending challenge: check allPlays[-1] when currentPlay has no pitches yet
    """
    current_events = plays.get('currentPlay', {}).get('playEvents', [])
    current_has_pitches = any(ev.get('isPitch') for ev in current_events)

    # Scan currentPlay from end: a review before any pitch means it just resolved
    for ev in reversed(current_events):
        if ev.get('isPitch'):
            return None  # pitch thrown after review — stale
        rd = ev.get('reviewDetails')
        if rd and not rd.get('inProgress'):
            return 'Call Overturned' if rd.get('isOverturned') else 'Call Stands'

    # If current AB has no pitches yet, check the last completed play
    if not current_has_pitches:
        all_plays = plays.get('allPlays', [])
        if all_plays:
            for ev in reversed(all_plays[-1].get('playEvents', [])):
                rd = ev.get('reviewDetails')
                if rd and not rd.get('inProgress'):
                    return 'Call Overturned' if rd.get('isOverturned') else 'Call Stands'

    return None


_SUB_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'v'}


def _last_name_simple(full_name):
    """Return last name, skipping name suffixes."""
    parts = (full_name or '').split()
    for i in range(len(parts) - 1, 0, -1):
        if parts[i].lower().strip('.') not in _SUB_SUFFIXES:
            return parts[i]
    return parts[-1] if parts else ''


def _find_recent_sub_event(plays):
    """Return 'PC: Lastname', 'PH: Lastname', or None for the most recent pitching
    change or pinch hitter within the last 3 plays.

    Pitching changes between at-bats appear as standalone top-level allPlays entries
    (result.eventType = 'pitching_substitution').  Mid-at-bat subs appear as action
    events inside a play's playEvents list.  We check both.
    """
    all_plays = plays.get('allPlays') or []
    recent = all_plays[-3:] if len(all_plays) >= 3 else all_plays

    # 1. Top-level allPlays substitution entries (between-at-bat pitching changes)
    for play in reversed(recent):
        result_et = (play.get('result', {}).get('eventType') or '').lower()
        result_desc = (play.get('result', {}).get('description') or '').lower()
        if 'pitching_substitution' in result_et:
            pitcher = play.get('matchup', {}).get('pitcher', {}).get('fullName') or ''
            last = _last_name_simple(pitcher)
            return f'PC: {last}' if last else None
        if 'offensive_substitution' in result_et and 'pinch' in result_desc:
            batter = play.get('matchup', {}).get('batter', {}).get('fullName') or ''
            last = _last_name_simple(batter)
            return f'PH: {last}' if last else None

    # 2. Action events inside currentPlay or last completed play (mid-at-bat subs)
    sources = [p for p in [plays.get('currentPlay')] + ([all_plays[-1]] if all_plays else []) if p]
    for play in sources:
        for ev in reversed(play.get('playEvents', [])):
            et = (ev.get('details', {}).get('eventType') or '').lower()
            player_name = (ev.get('player', {}).get('fullName') or '').strip()
            if not player_name:
                continue
            last = _last_name_simple(player_name)
            if 'pitching_substitution' in et:
                return f'PC: {last}'
            if 'offensive_substitution' in et:
                desc = (ev.get('details', {}).get('description') or '').lower()
                if 'pinch' in desc:
                    return f'PH: {last}'
    return None


def fetch_scoreboard_live_extras(game_pk, away_id=None, home_id=None):
    """Fetch pitch count, batter game stats, last at-bat result, and last pitch speed
    from the live feed for use in the scoreboard box.

    Returns a dict with keys: pitch_count, batter_hits, batter_at_bats,
    batter_last_result, last_pitch_speed, last_pitch_type, away_challenges_remaining,
    home_challenges_remaining.  All values default to None / '' on any failure.
    """
    try:
        data = fetch_live_feed(game_pk)
        live = data.get('liveData', {})
        plays = live.get('plays', {})
        linescore = live.get('linescore', {})
        boxscore = live.get('boxscore', {})

        pitcher_id = linescore.get('defense', {}).get('pitcher', {}).get('id')
        offense = linescore.get('offense', {})
        batter_id = offense.get('batter', {}).get('id')
        on_deck_name = offense.get('onDeck', {}).get('fullName') or None
        in_hole_name = offense.get('inHole', {}).get('fullName') or None

        def _runner_jersey(base_key):
            rid = offense.get(base_key, {}).get('id')
            if not rid:
                return None
            pid_str = f'ID{rid}'
            for side in ('away', 'home'):
                pdata = boxscore.get('teams', {}).get(side, {}).get('players', {}).get(pid_str, {})
                if pdata:
                    return pdata.get('jerseyNumber')
            return None

        runner_first_number = _runner_jersey('first')
        runner_second_number = _runner_jersey('second')
        runner_third_number = _runner_jersey('third')

        pitcher_info = _get_player_info(boxscore, pitcher_id, 'pitching')
        batter_info = _get_player_info(boxscore, batter_id, 'batting')

        pitch_count = pitcher_info.get('stats', {}).get('numberOfPitches')
        batter_hits = batter_info.get('stats', {}).get('hits')
        batter_at_bats = batter_info.get('stats', {}).get('atBats')

        # Last completed at-bat result for the current batter (e.g. HR, K, 2B)
        batter_last_result = ''
        for play in reversed(plays.get('allPlays', [])):
            if play.get('matchup', {}).get('batter', {}).get('id') == batter_id:
                batter_last_result = _build_scorecard_notation(play)
                break

        # Scan current at-bat: pitch count, last strike type, and whether AB is complete
        last_speed = None
        last_type = ''
        last_strike_call = ''
        at_bat_pitch_count = 0
        strike_calls = []  # per-strike call type: 'S' swinging, 'C' called, 'F' foul
        current_play_events = plays.get('currentPlay', {}).get('playEvents', [])
        for ev in current_play_events:
            if ev.get('isPitch'):
                at_bat_pitch_count += 1
                pd = ev.get('pitchData', {})
                details = ev.get('details', {})
                call_code = (details.get('call', {}).get('code', '') or '').upper()
                if call_code in ('S', 'W', 'T', 'O', 'M'):
                    last_strike_call = 'S'  # swinging
                    if len(strike_calls) < 2:
                        strike_calls.append('S')
                elif call_code == 'C':
                    last_strike_call = 'L'  # looking
                    if len(strike_calls) < 2:
                        strike_calls.append('C')
                elif call_code in ('F', 'L', 'R'):
                    last_strike_call = 'F'  # foul
                    if len(strike_calls) < 2:
                        strike_calls.append('F')
                # always overwrite so the last pitch in the AB is shown
                raw_code = details.get('type', {}).get('code', '') or ''
                last_type = _PITCH_TYPE_ABBR.get(raw_code, raw_code)
                last_speed = pd.get('startSpeed')

        current_at_bat_complete = bool(
            plays.get('currentPlay', {}).get('result', {}).get('event')
        )

        # ABS max grows by 1 per extra inning (10th = 3 total, 11th = 4, ...)
        current_inning = linescore.get('currentInning') or 9
        abs_max = _ABS_CHALLENGE_MAX + max(0, int(current_inning) - 9)

        away_used, home_used = _count_abs_challenges_used(plays, away_id, home_id)
        away_remaining = max(0, abs_max - away_used)
        home_remaining = max(0, abs_max - home_used)
        away_replay_used, home_replay_used = _count_replay_challenges_used(plays, away_id, home_id)
        away_replay_remaining = max(0, _REPLAY_CHALLENGE_MAX - away_replay_used)
        home_replay_remaining = max(0, _REPLAY_CHALLENGE_MAX - home_replay_used)

        sub_event = _find_recent_sub_event(plays)

        # Extract last completed play from the live feed — more timely than the win-prob endpoint.
        # For field errors include the position code (e.g. "E6" for shortstop error).
        _SUBST_EVENT_TYPES = {
            'pitching_substitution', 'defensive_substitution', 'offensive_substitution',
            'runner_substitution', 'game_advisory', 'ejection', 'defensive_switch',
        }
        live_last_play = None
        live_last_play_inning = None
        live_last_play_is_top = None
        for _lp in reversed(plays.get('allPlays', [])):
            if not _lp.get('about', {}).get('isComplete'):
                continue
            _et = (_lp.get('result', {}).get('eventType') or '').lower().replace(' ', '_')
            if _et in _SUBST_EVENT_TYPES:
                continue
            _ev = _lp.get('result', {}).get('event') or ''
            if not _ev:
                continue
            live_last_play = _build_scorecard_notation(_lp)
            live_last_play_inning = _lp.get('about', {}).get('inning')
            live_last_play_is_top = _lp.get('about', {}).get('isTopInning')
            break

        return {
            'pitch_count': pitch_count,
            'batter_hits': batter_hits,
            'batter_at_bats': batter_at_bats,
            'batter_last_result': batter_last_result,
            'last_pitch_speed': last_speed,
            'last_pitch_type': last_type,
            'due_up': on_deck_name,
            'in_hole': in_hole_name,
            'last_strike_call': last_strike_call,
            'strike_calls': strike_calls,
            'at_bat_pitch_count': at_bat_pitch_count,
            'current_at_bat_complete': current_at_bat_complete,
            'sub_event': sub_event,
            'abs_challenge_max': abs_max,
            'away_challenges_remaining': away_remaining,
            'home_challenges_remaining': home_remaining,
            'away_replay_remaining': away_replay_remaining,
            'home_replay_remaining': home_replay_remaining,
            'runner_first_number': runner_first_number,
            'runner_second_number': runner_second_number,
            'runner_third_number': runner_third_number,
            'last_review_result': _find_recent_review_result(plays),
            'last_play': live_last_play,
            'last_play_inning': live_last_play_inning,
            'last_play_is_top': live_last_play_is_top,
        }
    except Exception:
        return {}


def fetch_between_inning_info(game_pk, inning_state):
    """Return the next 3 batters, pitcher, and last-play notation for the break.

    Computes from the live feed batting order so the result is always the true
    leadoff + next two, not whatever the linescore offense fields happen to hold.

    inning_state: 'Middle' → home bats next (bottom); 'End' → away bats next (top).
    Returns dict with keys: next_batter_1/2/3 (full names), next_pitcher (full name),
    last_play (scorecard notation), last_play_inning, last_play_is_top.
    """
    try:
        data = fetch_live_feed(game_pk)
        live = data.get('liveData', {})
        linescore = live.get('linescore', {})
        boxscore = live.get('boxscore', {})
        plays = live.get('plays', {})

        batting_side = 'home' if inning_state == 'Middle' else 'away'
        pitching_side = 'away' if batting_side == 'home' else 'home'
        # The half-inning in which this team bats
        batting_half = 'bottom' if batting_side == 'home' else 'top'

        team_box = boxscore.get('teams', {}).get(batting_side, {})
        batting_order_ids = team_box.get('battingOrder', [])
        players = team_box.get('players', {})

        if not batting_order_ids:
            return {}

        # Build slot (1-9) -> current player id map; last entry per slot = current player
        slot_to_pid = {}
        for pid in batting_order_ids:
            pdata = players.get(f'ID{pid}', {})
            bat_str = str(pdata.get('battingOrder', ''))
            slot = int(bat_str[0]) if bat_str and bat_str[0].isdigit() else None
            if slot:
                slot_to_pid[slot] = pid

        ordered_pids = [slot_to_pid[s] for s in sorted(slot_to_pid.keys())]
        if not ordered_pids:
            return {}

        # Find the last batter from this team's most recent half-inning
        all_plays = plays.get('allPlays', [])
        last_batter_pid = None
        for play in reversed(all_plays):
            if play.get('about', {}).get('halfInning', '') != batting_half:
                continue
            bid = play.get('matchup', {}).get('batter', {}).get('id')
            if bid and bid in ordered_pids:
                last_batter_pid = bid
                break

        if last_batter_pid and last_batter_pid in ordered_pids:
            last_idx = ordered_pids.index(last_batter_pid)
            start = (last_idx + 1) % len(ordered_pids)
        else:
            start = 0  # team hasn't batted yet → start from top of order

        n = len(ordered_pids)
        next_3_pids = [ordered_pids[(start + i) % n] for i in range(min(3, n))]

        def _name(pid):
            return players.get(f'ID{pid}', {}).get('person', {}).get('fullName', '')

        names = [_name(pid) for pid in next_3_pids]

        # Pitcher warming up for the next half (linescore.defense is the fielding team)
        pitcher_name = linescore.get('defense', {}).get('pitcher', {}).get('fullName', '')
        if not pitcher_name:
            pit_id = linescore.get('defense', {}).get('pitcher', {}).get('id')
            if pit_id:
                pit_box = boxscore.get('teams', {}).get(pitching_side, {})
                pitcher_name = (
                    pit_box.get('players', {})
                    .get(f'ID{pit_id}', {})
                    .get('person', {})
                    .get('fullName', '')
                )

        # Extract the last completed play from the half-inning that just ended.
        # This provides scorecard notation (e.g. 'F7', '6-3') for the header display,
        # sourced from the live feed which has credits/fielder position data.
        _ended_half = 'top' if inning_state == 'Middle' else 'bottom'
        _SUBST_TYPES = {
            'pitching_substitution', 'defensive_substitution', 'offensive_substitution',
            'runner_substitution', 'game_advisory', 'ejection', 'defensive_switch',
        }
        last_play_notation = None
        last_play_inning = None
        last_play_is_top = None
        for _lp in reversed(plays.get('allPlays', [])):
            if not _lp.get('about', {}).get('isComplete'):
                continue
            _et = (_lp.get('result', {}).get('eventType') or '').lower().replace(' ', '_')
            if _et in _SUBST_TYPES:
                continue
            if not (_lp.get('result', {}).get('event') or ''):
                continue
            if _lp.get('about', {}).get('halfInning', '') == _ended_half:
                last_play_notation = _build_scorecard_notation(_lp)
                last_play_inning = _lp.get('about', {}).get('inning')
                last_play_is_top = _lp.get('about', {}).get('isTopInning')
                break

        return {
            'next_batter_1': names[0] if len(names) > 0 else '',
            'next_batter_2': names[1] if len(names) > 1 else '',
            'next_batter_3': names[2] if len(names) > 2 else '',
            'next_pitcher':  pitcher_name,
            'last_play':         last_play_notation,
            'last_play_inning':  last_play_inning,
            'last_play_is_top':  last_play_is_top,
        }
    except Exception:
        return {}



    """Extract pitch locations from the current at-bat, falling back to the last completed at-bat."""
    sources = [plays.get('currentPlay', {})]
    all_plays = plays.get('allPlays', [])
    if all_plays:
        sources.append(all_plays[-1])

    for play in sources:
        pitches = []
        for event in play.get('playEvents', []):
            if not event.get('isPitch'):
                continue
            coords = event.get('pitchData', {}).get('coordinates', {})
            px = coords.get('pX')
            pz = coords.get('pZ')
            if px is None or pz is None:
                continue
            details = event.get('details', {})
            pitches.append({
                'px': px,
                'pz': pz,
                'code': details.get('type', {}).get('code', ''),
                'is_strike': details.get('isStrike', False),
                'is_ball': details.get('isBall', False),
            })
        if pitches:
            return pitches
    return []


_HIT_EVENTS = {'Single', 'Double', 'Triple', 'Home Run'}


def _extract_all_hit_coordinates(plays):
    """Collect all hit coordinates from allPlays in chronological order.
    Returns list of dicts: {x, y, is_hr, is_hit, is_out, player (last name)}.
    is_hit = ball in play resulting in a hit (incl. HR).
    is_out = ball in play resulting in an out.
    """
    all_plays = plays.get('allPlays', [])
    hits = []
    for play in all_plays:
        result = play.get('result', {})
        event = result.get('event', '')
        is_hr = event == 'Home Run'
        is_hit = event in _HIT_EVENTS
        is_out = not is_hit
        full_name = play.get('matchup', {}).get('batter', {}).get('fullName', '')
        last_name = full_name.split()[-1] if full_name else ''

        about = play.get('about', {})
        hit_inning = about.get('inning', 0)
        hit_half = about.get('halfInning', '')  # 'top' or 'bottom'

        hit_data = play.get('hitData', {})
        cx = hit_data.get('coordinates', {}).get('coordX')
        cy = hit_data.get('coordinates', {}).get('coordY')
        if cx is not None and cy is not None:
            hits.append({'x': cx, 'y': cy, 'is_hr': is_hr, 'is_hit': is_hit, 'is_out': is_out,
                         'player': last_name, 'inning': hit_inning, 'half': hit_half})
            continue
        # Fall back to playEvents
        for ev in play.get('playEvents', []):
            hit_data = ev.get('hitData', {})
            cx = hit_data.get('coordinates', {}).get('coordX')
            cy = hit_data.get('coordinates', {}).get('coordY')
            if cx is not None and cy is not None:
                hits.append({'x': cx, 'y': cy, 'is_hr': is_hr, 'is_hit': is_hit, 'is_out': is_out,
                             'player': last_name, 'inning': hit_inning, 'half': hit_half})
                break
    return hits


def fetch_field_view_data(game_pk):
    """Extract field view data from the live feed."""
    data = fetch_live_feed(game_pk)
    game_data = data.get('gameData', {})
    live_data = data.get('liveData', {})
    plays = live_data.get('plays', {})
    linescore = live_data.get('linescore', {})
    boxscore = live_data.get('boxscore', {})

    status = game_data.get('status', {})
    detailed_state = status.get('detailedState', '')

    # Teams
    teams = game_data.get('teams', {})
    away_team = teams.get('away', {})
    home_team = teams.get('home', {})

    # Score
    away_runs = linescore.get('teams', {}).get('away', {}).get('runs', 0)
    home_runs = linescore.get('teams', {}).get('home', {}).get('runs', 0)
    away_hits = linescore.get('teams', {}).get('away', {}).get('hits', 0)
    home_hits = linescore.get('teams', {}).get('home', {}).get('hits', 0)
    away_errors = linescore.get('teams', {}).get('away', {}).get('errors', 0)
    home_errors = linescore.get('teams', {}).get('home', {}).get('errors', 0)

    # Inning state
    current_inning = linescore.get('currentInning', 0)
    inning_ordinal = linescore.get('currentInningOrdinal', '')
    inning_state = linescore.get('inningState', '')  # Top/Bottom/Middle/End

    # Count and outs
    balls = linescore.get('balls', 0) or 0
    strikes = linescore.get('strikes', 0) or 0
    outs = linescore.get('outs', 0) or 0

    # Runners
    offense = linescore.get('offense', {})
    runner_first = bool(offense.get('first'))
    runner_second = bool(offense.get('second'))
    runner_third = bool(offense.get('third'))

    # Current batter/pitcher
    batter_id = offense.get('batter', {}).get('id')
    pitcher_id = linescore.get('defense', {}).get('pitcher', {}).get('id')

    on_deck_id = offense.get('onDeck', {}).get('id')

    batter_info = _get_player_info(boxscore, batter_id, 'batting')
    pitcher_info = _get_player_info(boxscore, pitcher_id, 'pitching')
    on_deck_info = _get_player_info(boxscore, on_deck_id, 'batting')

    # Pitch locations and hit coordinates
    pitches = _extract_pitches(plays)
    all_hits = _extract_all_hit_coordinates(plays)
    last_hit = all_hits[-1] if all_hits else None
    hit_coords = (last_hit['x'], last_hit['y']) if last_hit else None

    # Last play description — only show plays from the current half inning so the
    # previous half inning's last play doesn't bleed into the new half inning header.
    current_play = plays.get('currentPlay', {})
    last_play_desc = current_play.get('result', {}).get('description', '')
    if not last_play_desc:
        all_plays = plays.get('allPlays', [])
        if all_plays:
            last_completed = all_plays[-1]
            cur_half = 'bottom' if inning_state == 'Bottom' else 'top'
            play_inning = last_completed.get('about', {}).get('inning')
            play_half = last_completed.get('about', {}).get('halfInning', '')
            if play_inning == current_inning and play_half == cur_half:
                last_play_desc = last_completed.get('result', {}).get('description', '')

    # Linescore innings for mini table
    innings_list = linescore.get('innings', [])
    innings = []
    for inn in innings_list:
        innings.append({
            'num': inn.get('num', 0),
            'away_runs': inn.get('away', {}).get('runs'),
            'home_runs': inn.get('home', {}).get('runs'),
        })

    # Decisions (WP/LP/SV)
    decisions = live_data.get('decisions', {})
    winner = decisions.get('winner', {}).get('fullName', '')
    loser = decisions.get('loser', {}).get('fullName', '')
    save = decisions.get('save', {}).get('fullName', '')

    # Probable pitchers
    away_probable = game_data.get('probablePitchers', {}).get('away', {}).get('fullName', '')
    home_probable = game_data.get('probablePitchers', {}).get('home', {}).get('fullName', '')

    # Game time
    game_date = game_data.get('datetime', {}).get('dateTime', '')

    # Venue
    venue = game_data.get('venue', {}).get('name', '')

    return {
        'detailed_state': detailed_state,
        'away_abbr': away_team.get('abbreviation', ''),
        'home_abbr': home_team.get('abbreviation', ''),
        'away_id': away_team.get('id', 0),
        'home_id': home_team.get('id', 0),
        'away_runs': away_runs,
        'home_runs': home_runs,
        'away_hits': away_hits,
        'home_hits': home_hits,
        'away_errors': away_errors,
        'home_errors': home_errors,
        'current_inning': current_inning,
        'inning_ordinal': inning_ordinal,
        'inning_state': inning_state,
        'balls': balls,
        'strikes': strikes,
        'outs': outs,
        'runner_first': runner_first,
        'runner_second': runner_second,
        'runner_third': runner_third,
        'batter': batter_info,
        'pitcher': pitcher_info,
        'on_deck': on_deck_info,
        'pitches': pitches,
        'hit_coords': hit_coords,
        'all_hits': all_hits,
        'venue_id': game_data.get('venue', {}).get('id', 0),
        'last_play': last_play_desc,
        'innings': innings,
        'winner': winner,
        'loser': loser,
        'save': save,
        'away_probable': away_probable,
        'home_probable': home_probable,
        'game_date': game_date,
        'venue': venue,
    }


def _get_player_info(boxscore, player_id, stat_type):
    """Extract player name and stats from boxscore."""
    if not player_id:
        return {'name': '', 'stats': {}}
    pid_str = f'ID{player_id}'
    for side in ('away', 'home'):
        players = boxscore.get('teams', {}).get(side, {}).get('players', {})
        for key, pdata in players.items():
            if key == pid_str or pdata.get('person', {}).get('id') == player_id:
                name = pdata.get('person', {}).get('fullName', '')
                stats = pdata.get('stats', {}).get(stat_type, {})
                season = pdata.get('seasonStats', {}).get(stat_type, {})
                return {
                    'name': name,
                    'stats': stats,
                    'season': season,
                }
    return {'name': '', 'stats': {}, 'season': {}}


# --- Pitch type display abbreviations (Statcast code → scoreboard label) ---

_PITCH_TYPE_ABBR = {
    'FF': 'FB',  # Four-seam fastball
    'FA': 'FB',  # Generic fastball
    'FT': 'FB',  # Two-seam fastball
    'SI': 'SI',  # Sinker
    'FC': 'CT',  # Cutter
    'SL': 'SL',  # Slider
    'ST': 'SW',  # Sweeper
    'SW': 'SW',
    'CH': 'CH',  # Changeup
    'CU': 'CB',  # Curveball
    'CS': 'CB',
    'KC': 'KC',  # Knuckle-curve
    'FS': 'SP',  # Splitter
    'KN': 'KN',  # Knuckleball
    'EP': 'EP',  # Eephus
    'SC': 'SC',  # Screwball
}


# --- Scorecard Data ---

_EVENT_CODE_MAP = {
    'Strikeout': 'K',
    'Strikeout Looking': 'Kl',
    'Strikeout Double Play': 'K',
    'Walk': 'BB',
    'Intent Walk': 'IBB',
    'Runner Placed On Base': 'PR',
    'Hit By Pitch': 'HBP',
    'Single': '1B',
    'Double': '2B',
    'Triple': '3B',
    'Home Run': 'HR',
    'Groundout': 'GO',
    'Flyout': 'FO',
    'Lineout': 'LO',
    'Pop Out': 'PO',
    'Grounded Into DP': 'GDP',
    'Double Play': 'DP',
    'Triple Play': 'TP',
    'Sac Fly': 'SF',
    'Sac Bunt': 'SAC',
    'Sacrifice Bunt DP': 'SAC',
    'Fielders Choice': 'FC',
    'Fielders Choice Out': 'FC',
    'Field Error': 'E',
    'Catcher Interf': 'CI',
    'Batter Interference': 'BI',
    'Runner Out': 'RO',
    'Force Out': 'FO',
    'Field Out': 'FO',
}


def _map_event_to_code(event):
    """Map an API event string to a scorecard abbreviation."""
    return _EVENT_CODE_MAP.get(event, event[:3] if event else '')


def _build_scorecard_notation(play):
    """Return scorecard notation (e.g. 'F7', '6-4-3 DP', 'K', '1B') from a play dict."""
    result  = play.get('result', {})
    event   = result.get('event', '')
    et      = (result.get('eventType') or '').lower().replace(' ', '_')
    credits = play.get('credits', [])

    _SIMPLE = {
        'Strikeout': 'K', 'Strikeout Looking': 'Kl', 'Strikeout Double Play': 'K',
        'Walk': 'BB', 'Intent Walk': 'IBB', 'Hit By Pitch': 'HBP',
        'Runner Placed On Base': 'PR',
        'Single': '1B', 'Double': '2B', 'Triple': '3B', 'Home Run': 'HR',
        'Balk': 'BLK', 'Wild Pitch': 'WP', 'Passed Ball': 'PB',
        'Catcher Interf': 'CI', 'Batter Interference': 'BI',
        'Stolen Base 2B': 'SB', 'Stolen Base 3B': 'SB', 'Stolen Base Home': 'SB',
    }
    if event in _SIMPLE:
        return _SIMPLE[event]

    if event == 'Field Error':
        for cr in credits:
            if 'error' in (cr.get('credit') or '').lower():
                pos = cr.get('position', {}).get('code', '')
                if pos and pos.isdigit():
                    return f'E{pos}'
        return 'E'

    is_dp = 'double_play' in et or event in (
        'Grounded Into DP', 'Double Play', 'Sac Fly Double Play', 'Sac Bunt Double Play',
    )
    is_tp = 'triple_play' in et or event == 'Triple Play'
    dp_suffix = ' DP' if is_dp else (' TP' if is_tp else '')

    # Build fielder sequence from credits; deduplicate consecutive positions.
    pos_seq = []
    for cr in credits:
        pos = cr.get('position', {}).get('code', '')
        if pos and pos.isdigit():
            if not pos_seq or pos_seq[-1] != pos:
                pos_seq.append(pos)

    # Position of last fielder to record a putout (rightmost in sequence).
    putout_pos = ''
    for cr in credits:
        if cr.get('credit') == 'f_putout':
            p = cr.get('position', {}).get('code', '')
            if p and p.isdigit():
                putout_pos = p

    if event in ('Flyout',):
        if is_dp and pos_seq:
            return '-'.join(pos_seq) + dp_suffix
        return f'F{putout_pos}' if putout_pos else 'FO'

    if event in ('Lineout',):
        if is_dp and pos_seq:
            return '-'.join(pos_seq) + dp_suffix
        return f'L{putout_pos}' if putout_pos else 'LO'

    if event in ('Pop Out', 'Popout'):
        return f'P{putout_pos}' if putout_pos else 'PO'

    if event in ('Sac Fly', 'Sac Fly Double Play'):
        if is_dp and pos_seq:
            return '-'.join(pos_seq) + dp_suffix
        return f'SF{putout_pos}' if putout_pos else 'SF'

    if event in ('Sac Bunt', 'Sacrifice Bunt DP', 'Sac Bunt Double Play'):
        seq = '-'.join(pos_seq) if pos_seq else ''
        return f'SAC {seq}{dp_suffix}' if seq else 'SAC'

    if event in ('Fielders Choice', 'Fielders Choice Out'):
        seq = '-'.join(pos_seq) if pos_seq else ''
        return f'{seq} FC{dp_suffix}' if seq else 'FC'

    # All out events: return fielder sequence from credits.
    if pos_seq:
        return '-'.join(pos_seq) + dp_suffix

    # Fallbacks when credits are absent.
    if event.startswith('Caught Stealing'):
        return 'CS'
    if event.startswith('Pickoff'):
        return 'PK'
    return _EVENT_CODE_MAP.get(event, event[:3] if event else '')


def _build_lineup_at_bats(boxscore, plays, team_side):
    """Build 9-slot lineup with per-inning at-bat results.

    Returns list of dicts: {
        'name': str, 'position': str, 'order': int,
        'at_bats': {inning_num: [{'code': str, 'bases': int}, ...]},
        'sub': bool,  # True if substitution
        'totals': {'runs': int, 'hits': int}
    }
    """
    team_box = boxscore.get('teams', {}).get(team_side, {})
    batting_order = team_box.get('battingOrder', [])
    players = team_box.get('players', {})
    team_info = team_box.get('team', {})
    team_id = team_info.get('id')

    # Build player lookup
    player_map = {}
    for key, pdata in players.items():
        pid = pdata.get('person', {}).get('id')
        if pid:
            player_map[pid] = pdata

    # Initialize lineup slots (up to 9)
    lineup = []
    seen_orders = {}  # batting_order_slot -> lineup index

    for pid in batting_order:
        pdata = player_map.get(pid, {})
        person = pdata.get('person', {})
        name = person.get('fullName', '')
        position = pdata.get('position', {}).get('abbreviation', '')
        bat_order = pdata.get('battingOrder', '')
        order_slot = int(str(bat_order)[:1]) if bat_order else len(lineup) + 1

        bat_stats = pdata.get('stats', {}).get('batting', {})

        entry = {
            'name': name,
            'position': position,
            'order': order_slot,
            'player_id': pid,
            'at_bats': {},
            'sub': False,
            'totals': {
                'runs': bat_stats.get('runs', 0),
                'hits': bat_stats.get('hits', 0),
            }
        }

        if order_slot in seen_orders:
            # Substitution — replace the player in that slot
            idx = seen_orders[order_slot]
            original = lineup[idx]
            entry['sub'] = True
            entry['sub_original'] = {'name': original['name'], 'position': original['position']}
            lineup[idx] = entry
        else:
            seen_orders[order_slot] = len(lineup)
            lineup.append(entry)

    # Build player_id -> lineup index mapping
    pid_to_slot = {}
    for i, entry in enumerate(lineup):
        pid_to_slot[entry['player_id']] = i

    # Walk through all plays to assign at-bats to lineup slots
    all_plays = plays.get('allPlays', [])
    for play in all_plays:
        about = play.get('about', {})
        inning = about.get('inning', 0)
        half = about.get('halfInning', '')  # 'top' or 'bottom'

        # Determine if this play belongs to our team
        is_away = (half == 'top' and team_side == 'away')
        is_home = (half == 'bottom' and team_side == 'home')
        if not (is_away or is_home):
            continue

        batter_id = play.get('matchup', {}).get('batter', {}).get('id')
        if batter_id is None:
            continue

        result = play.get('result', {})
        event = result.get('event', '')
        code = _map_event_to_code(event)
        if not code:
            continue

        # Determine bases reached (0=out, 1=1B, 2=2B, 3=3B, 4=HR)
        bases = 0
        if event in ('Single',):
            bases = 1
        elif event in ('Double',):
            bases = 2
        elif event in ('Triple',):
            bases = 3
        elif event in ('Home Run',):
            bases = 4
        elif event in ('Walk', 'Intent Walk', 'Hit By Pitch'):
            bases = 1

        slot = pid_to_slot.get(batter_id)
        if slot is None:
            # Player not in current lineup (was subbed out), find their order
            pdata = player_map.get(batter_id, {})
            bat_order = pdata.get('battingOrder', '')
            order_slot = int(str(bat_order)[:1]) if bat_order else None
            if order_slot and order_slot in seen_orders:
                slot = seen_orders[order_slot]

        if slot is not None and slot < len(lineup):
            ball_count = 0
            strike_count = 0
            for evt in play.get('playEvents', []):
                if not evt.get('isPitch'):
                    continue
                details = evt.get('details', {})
                if details.get('isBall'):
                    ball_count += 1
                elif details.get('isStrike'):
                    strike_count += 1
            if inning not in lineup[slot]['at_bats']:
                lineup[slot]['at_bats'][inning] = []
            lineup[slot]['at_bats'][inning].append({
                'code': code,
                'bases': bases,
                'balls': ball_count,
                'strikes': strike_count,
            })

    # Build inning totals
    inning_totals = {}
    for play in all_plays:
        about = play.get('about', {})
        inning = about.get('inning', 0)
        half = about.get('halfInning', '')
        is_away = (half == 'top' and team_side == 'away')
        is_home = (half == 'bottom' and team_side == 'home')
        if not (is_away or is_home):
            continue
        if inning not in inning_totals:
            inning_totals[inning] = 0
        # Count runs scored on this play
        result = play.get('result', {})
        rbi = result.get('rbi', 0)
        # Actually use the runs from the scoring plays
        runners = play.get('runners', [])
        for runner in runners:
            movement = runner.get('movement', {})
            if movement.get('end') == 'score':
                inning_totals[inning] = inning_totals.get(inning, 0) + 1

    return lineup[:9], inning_totals


def _extract_pitchers(boxscore, team_side):
    """Return ordered list of pitchers used with game stats."""
    team_box = boxscore.get('teams', {}).get(team_side, {})
    pitcher_ids = team_box.get('pitchers', [])
    players = team_box.get('players', {})
    pitchers = []
    for pid in pitcher_ids:
        pdata = players.get(f'ID{pid}', {})
        full = pdata.get('person', {}).get('fullName', '')
        parts = full.split()
        last = parts[-1] if parts else full
        stats = pdata.get('stats', {}).get('pitching', {})
        pitchers.append({
            'name': last,
            'ip': stats.get('inningsPitched', '0.0'),
            'hits': stats.get('hits', 0),
            'er': stats.get('earnedRuns', 0),
            'k': stats.get('strikeOuts', 0),
        })
    return pitchers


def fetch_scorecard_data(game_pk):
    """Extract scorecard data from the live feed."""
    data = fetch_live_feed(game_pk)
    game_data = data.get('gameData', {})
    live_data = data.get('liveData', {})
    plays = live_data.get('plays', {})
    linescore = live_data.get('linescore', {})
    boxscore = live_data.get('boxscore', {})

    status = game_data.get('status', {})
    detailed_state = status.get('detailedState', '')

    teams = game_data.get('teams', {})
    away_team = teams.get('away', {})
    home_team = teams.get('home', {})

    # Linescore for totals
    away_ls = linescore.get('teams', {}).get('away', {})
    home_ls = linescore.get('teams', {}).get('home', {})

    # Build lineups
    away_lineup, away_inning_totals = _build_lineup_at_bats(boxscore, plays, 'away')
    home_lineup, home_inning_totals = _build_lineup_at_bats(boxscore, plays, 'home')
    away_pitchers = _extract_pitchers(boxscore, 'away')
    home_pitchers = _extract_pitchers(boxscore, 'home')

    # Count innings
    innings_list = linescore.get('innings', [])
    num_innings = len(innings_list)

    return {
        'detailed_state': detailed_state,
        'away_abbr': away_team.get('abbreviation', ''),
        'home_abbr': home_team.get('abbreviation', ''),
        'away_id': away_team.get('id', 0),
        'home_id': home_team.get('id', 0),
        'away_lineup': away_lineup,
        'home_lineup': home_lineup,
        'away_inning_totals': away_inning_totals,
        'home_inning_totals': home_inning_totals,
        'num_innings': max(num_innings, 9),
        'away_runs': away_ls.get('runs', 0),
        'away_hits': away_ls.get('hits', 0),
        'away_errors': away_ls.get('errors', 0),
        'home_runs': home_ls.get('runs', 0),
        'home_hits': home_ls.get('hits', 0),
        'home_errors': home_ls.get('errors', 0),
        'away_pitchers': away_pitchers,
        'home_pitchers': home_pitchers,
    }
