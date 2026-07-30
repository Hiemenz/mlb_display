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
    """Extract pitch data with velocity, pitch type, and per-batter zone bounds."""
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
                'sz_top': pitch_data.get('strikeZoneTop'),
                'sz_bot': pitch_data.get('strikeZoneBottom'),
                'code': details.get('type', {}).get('code', ''),
                # Result/call code (B/C/S/F/X/D/E…) — drives strike-zone fill.
                'call': details.get('call', {}).get('code', '') or details.get('code', ''),
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


_REVIEW_CTX_SKIP = {'at', 'on', 'in', 'a', 'an', 'the', 'of'}


def _parse_review_context(description):
    """Extract a short play-context label from a review event description.

    'Manager challenge (out at first base): ...'  → 'Out 1B'
    'Manager challenge (safe at home plate): ...'  → 'Safe Home'
    'Player challenge (strike): ...'               → 'Strike'
    """
    import re as _re
    if not description:
        return ''
    m = _re.search(r'\(([^)]+)\)', description)
    if not m:
        return ''
    ctx = m.group(1).strip().lower()
    for old, new in [
        ('first base', '1B'), ('second base', '2B'), ('third base', '3B'),
        ('home plate', 'Home'), (' base', ''),
    ]:
        ctx = ctx.replace(old, new)
    # Capitalize content words; keep abbreviations and prepositions as-is
    def _cap(word):
        """Cap."""
        if word.isupper() or word in _REVIEW_CTX_SKIP:
            return word
        return '/'.join(s.capitalize() for s in word.split('/'))

    return ' '.join(_cap(p) for p in ctx.split())


def _find_recent_review_result(plays, away_id=None, home_id=None, away_abbr='', home_abbr=''):
    """Return a formatted review result string, or None if no review just resolved.

    Format: 'OVR: {ctx}' or 'CFM: {ctx}' with play context when available,
    falling back to 'OVR {team}' / 'CFM {team}'.
    A review is considered fresh if no pitch has been thrown since it completed.
    """
    def _fmt(rd, desc=''):
        """Fmt."""
        label = 'OVR' if rd.get('isOverturned') else 'CFM'
        ctx = _parse_review_context(desc)
        if ctx:
            return f'{label}: {ctx}'
        cid = rd.get('challengeTeamId')
        if cid and away_id and home_id:
            abbr = away_abbr if cid == away_id else (home_abbr if cid == home_id else '')
            if abbr:
                return f'{label} {abbr}'
        return label

    current_events = plays.get('currentPlay', {}).get('playEvents', [])
    current_has_pitches = any(ev.get('isPitch') for ev in current_events)

    # Scan currentPlay from end: a review before any pitch means it just resolved
    for ev in reversed(current_events):
        if ev.get('isPitch'):
            return None  # pitch thrown after review — stale
        rd = ev.get('reviewDetails')
        if rd and not rd.get('inProgress'):
            return _fmt(rd, ev.get('details', {}).get('description', ''))

    # If current AB has no pitches yet, check the last completed play
    if not current_has_pitches:
        all_plays = plays.get('allPlays', [])
        if all_plays:
            for ev in reversed(all_plays[-1].get('playEvents', [])):
                rd = ev.get('reviewDetails')
                if rd and not rd.get('inProgress'):
                    return _fmt(rd, ev.get('details', {}).get('description', ''))

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
    """Return 'PC: Lastname', 'PH: Lastname', or None for a fresh pitching change
    or pinch hitter.

    A substitution is considered fresh only while no pitch has been thrown in the
    current at-bat since the change occurred.  This mirrors the freshness guard used
    by _find_recent_review_result and prevents the label from persisting for 3+ ABs.

    Pitching changes between at-bats appear as standalone top-level allPlays entries
    (result.eventType = 'pitching_substitution').  Mid-at-bat subs appear as action
    events inside a play's playEvents list.
    """
    all_plays = plays.get('allPlays') or []
    current_events = plays.get('currentPlay', {}).get('playEvents', [])
    current_has_pitches = any(ev.get('isPitch') for ev in current_events)

    # 1. Mid-at-bat subs inside currentPlay — fresh only if no pitch thrown after the sub.
    for ev in reversed(current_events):
        if ev.get('isPitch'):
            break  # pitch thrown after sub — stale
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

    # 2. Between-at-bat substitution (standalone allPlays entry) — fresh only if the
    # new pitcher/batter hasn't faced a pitch yet in the current at-bat.
    if not current_has_pitches and all_plays:
        last_play = all_plays[-1]
        result_et = (last_play.get('result', {}).get('eventType') or '').lower()
        result_desc = (last_play.get('result', {}).get('description') or '').lower()
        if 'pitching_substitution' in result_et:
            pitcher = last_play.get('matchup', {}).get('pitcher', {}).get('fullName') or ''
            last = _last_name_simple(pitcher)
            return f'PC: {last}' if last else None
        if 'offensive_substitution' in result_et and 'pinch' in result_desc:
            batter = last_play.get('matchup', {}).get('batter', {}).get('fullName') or ''
            last = _last_name_simple(batter)
            return f'PH: {last}' if last else None

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
            """Runner jersey."""
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

        _current_play = plays.get('currentPlay', {})
        current_at_bat_complete = bool(
            _current_play.get('result', {}).get('event')
        )
        # Batter name from currentPlay.matchup — updates atomically with current_at_bat_complete,
        # so it never lags behind the linescore like linescore.offense.batter can.
        current_play_batter = (
            _current_play.get('matchup', {}).get('batter', {}).get('fullName') or None
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
        live_last_play_rbi = 0
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
            live_last_play_rbi = int(_lp.get('result', {}).get('rbi') or 0)
            break

        # Batted-ball landing spot for the last completed play, if it was hit into play.
        last_hit_x = None
        last_hit_y = None
        last_hit_is_out = None
        last_hit_is_hr = False
        if live_last_play is not None:
            _lp_result = _lp.get('result', {})
            _lp_event = _lp_result.get('event', '')
            _lp_hit_data = _lp.get('hitData', {})
            _hx = _lp_hit_data.get('coordinates', {}).get('coordX')
            _hy = _lp_hit_data.get('coordinates', {}).get('coordY')
            if _hx is None or _hy is None:
                for _pe in _lp.get('playEvents', []):
                    _pe_hit_data = _pe.get('hitData', {})
                    _hx = _pe_hit_data.get('coordinates', {}).get('coordX')
                    _hy = _pe_hit_data.get('coordinates', {}).get('coordY')
                    if _hx is not None and _hy is not None:
                        break
            if _hx is not None and _hy is not None:
                last_hit_x = _hx
                last_hit_y = _hy
                last_hit_is_out = _lp_event not in _HIT_EVENTS
                last_hit_is_hr = (_lp_event == 'Home Run')

        # Last 7 batted balls in play (fair or foul) for the field diagram.
        # Uses the same coord extraction as _extract_all_hit_coordinates but
        # keeps only the most recent 7 and adds is_hr/is_out flags.
        recent_hits = _extract_all_hit_coordinates(plays)[-7:]

        # Wide-cell extras: current AB pitches (locations + type) and the last 5 game events.
        ab_pitches = _extract_pitches_detailed(plays)
        for _p in ab_pitches:
            _p['pt_abbr'] = _PITCH_TYPE_ABBR.get(_p.get('code', ''), _p.get('code', ''))

        # Mid-at-bat "action" events worth surfacing in the header, oldest-first.
        _ACTION_CODES = {
            'stolen_base':      'SB',
            'caught_stealing':  'CS',
            'pickoff':          'PK',
            'wild_pitch':       'WP',
            'passed_ball':      'PB',
            'balk':             'BLK',
            'pitching_substitution': 'PC',
        }

        def _action_code(et):
            """Action code."""
            for _k, _v in _ACTION_CODES.items():
                if et.startswith(_k):
                    return _v
            return None

        # Last 7 events of the whole game for the header, oldest-first, in scorecard
        # notation (e.g. '6-3', 'K', 'F9', '3R HR'). Runs-batted-in plays are prefixed
        # with the run count. Includes in-play actions (steals, pickoffs, wild pitches,
        # pitching changes) and challenge/replay reviews.
        # A direction token is inserted wherever the half-inning changes so the
        # renderer can show an inning-break delimiter: '^' when heading into the
        # top half (away bats), 'v' when heading into the bottom half (home bats).
        game_plays = []
        _last_play_half = None   # (inning, isTopInning) of the last appended play
        for _ap in plays.get('allPlays', []):
            _about = _ap.get('about', {})
            _this_half = (_about.get('inning', 0), bool(_about.get('isTopInning', True)))
            # In-play actions and challenge/replay reviews, in the order they occurred.
            _review_added = False
            for _pe in _ap.get('playEvents', []):
                if _pe.get('type') == 'action':
                    _code = _action_code((_pe.get('details', {}).get('eventType') or '').lower())
                    if _code and (not game_plays or game_plays[-1] != _code):
                        if _last_play_half and _this_half != _last_play_half:
                            game_plays.append('^' if _this_half[1] else 'v')
                        game_plays.append(_code)
                        _last_play_half = _this_half
                _rd = _pe.get('reviewDetails')
                if _rd and not _rd.get('inProgress') and not _review_added:
                    game_plays.append('CHAL W' if _rd.get('isOverturned') else 'CHAL L')
                    _review_added = True
            # Final result of a completed at-bat.
            if _ap.get('about', {}).get('isComplete', False):
                _result = _ap.get('result', {})
                _ap_et = (_result.get('eventType') or '').lower().replace(' ', '_')
                if _ap_et == 'pitching_substitution':
                    if not game_plays or game_plays[-1] != 'PC':
                        game_plays.append('PC')
                elif _ap_et not in _SUBST_EVENT_TYPES:
                    _ev = (_result.get('event') or '').strip()
                    if _ev:
                        # Same scorecard notation + RBI prefixes the normal cells use.
                        _note = _build_scorecard_notation(_ap)
                        _rbi = int(_result.get('rbi') or 0)
                        _is_err = _note.startswith('E') or ' E' in _note
                        if _rbi > 0 and not _is_err:
                            if _note == 'HR':
                                if _rbi == 4:
                                    _note = 'Grand Slam'
                                elif _rbi >= 2:
                                    _note = f'{_rbi}R HR'
                                # solo HR: no prefix
                            elif _rbi == 1:
                                _note = f'RBI {_note}'
                            else:
                                _note = f'{_rbi}RBI {_note}'
                        if _last_play_half and _this_half != _last_play_half:
                            game_plays.append('^' if _this_half[1] else 'v')
                        game_plays.append(_note)
                        _last_play_half = _this_half
        # Keep the last 7 *events* (plus the half-inning markers that fall between
        # them). Slicing game_plays[-7:] directly would count '^'/'v' markers as
        # entries and leave fewer than 7 real events showing.
        _kept = []
        _event_count = 0
        for _tok in reversed(game_plays):
            _kept.append(_tok)
            if _tok not in ('^', 'v'):
                _event_count += 1
                if _event_count >= 7:
                    break
        half_inning_plays = list(reversed(_kept))

        # K strikeouts for wide-cell header: track swinging (K) vs looking (L) per pitcher side
        away_pitcher_ks = []   # Ks by away pitcher (home batters struck out, isTopInning=False)
        home_pitcher_ks = []   # Ks by home pitcher (away batters struck out, isTopInning=True)
        for _kp in plays.get('allPlays', []):
            if (_kp.get('result', {}).get('eventType') or '').lower() == 'strikeout':
                _k_is_top = _kp.get('about', {}).get('isTopInning', True)
                _k_last_code = ''
                for _kpe in reversed(_kp.get('playEvents', [])):
                    if _kpe.get('isPitch'):
                        _k_last_code = _kpe.get('details', {}).get('code', '')
                        break
                _k_type = 'L' if _k_last_code == 'C' else 'K'
                if _k_is_top:
                    home_pitcher_ks.append(_k_type)
                else:
                    away_pitcher_ks.append(_k_type)

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
            'current_play_batter': current_play_batter,
            'sub_event': sub_event,
            'abs_challenge_max': abs_max,
            'away_challenges_remaining': away_remaining,
            'home_challenges_remaining': home_remaining,
            'away_replay_remaining': away_replay_remaining,
            'home_replay_remaining': home_replay_remaining,
            'runner_first_number': runner_first_number,
            'runner_second_number': runner_second_number,
            'runner_third_number': runner_third_number,
            'last_review_result': _find_recent_review_result(
                plays,
                away_id=away_id,
                home_id=home_id,
                away_abbr=data.get('gameData', {}).get('teams', {}).get('away', {}).get('abbreviation', ''),
                home_abbr=data.get('gameData', {}).get('teams', {}).get('home', {}).get('abbreviation', ''),
            ),
            'last_play': live_last_play,
            'last_play_rbi': live_last_play_rbi,
            'last_play_inning': live_last_play_inning,
            'last_play_is_top': live_last_play_is_top,
            'last_hit_x': last_hit_x,
            'last_hit_y': last_hit_y,
            'last_hit_is_out': last_hit_is_out,
            'last_hit_is_hr': last_hit_is_hr,
            'recent_hits': recent_hits,
            'ab_pitches': ab_pitches,
            'half_inning_plays': half_inning_plays,
            'away_pitcher_ks': away_pitcher_ks,
            'home_pitcher_ks': home_pitcher_ks,
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
        team_box.get('players', {})

        # Build all_players: both teams combined (needed for sub lookups)
        all_players = {}
        for _side in ('away', 'home'):
            all_players.update(boxscore.get('teams', {}).get(_side, {}).get('players', {}))

        def _full_name(pid):
            """Full name."""
            pdata = all_players.get(f'ID{pid}', {})
            return pdata.get('person', {}).get('fullName', '')

        all_plays = plays.get('allPlays', [])

        # Build the 9-slot batting order from play history — much more reliable than
        # parsing 'battingOrder' field which can be null or missing in the API response.
        # Walk through all plays for this team's half-inning in forward order:
        # the first 9 unique batter IDs encountered are the original batting order slots.
        # Subsequent new batters are substitutes; resolve their slot via 'battingOrder'
        # field (first digit = slot, e.g. '300' → slot 3) and update that slot.
        ordered_pids = [None] * 9  # slots 0-8 (batting positions 1-9)
        seen_pids = set()
        original_slot = 0  # tracks next available slot for first-seen original batters
        for play in all_plays:
            if play.get('about', {}).get('halfInning') != batting_half:
                continue
            bid = play.get('matchup', {}).get('batter', {}).get('id')
            if not bid or bid in seen_pids:
                continue
            seen_pids.add(bid)
            if original_slot < 9:
                # Original lineup member — assign to next open slot
                ordered_pids[original_slot] = bid
                original_slot += 1
            else:
                # Substitute — use battingOrder field to find their slot
                pdata = all_players.get(f'ID{bid}', {})
                bat_str = str(pdata.get('battingOrder', ''))
                if bat_str and bat_str[0].isdigit():
                    slot_idx = int(bat_str[0]) - 1  # 0-indexed
                    if 0 <= slot_idx < 9:
                        ordered_pids[slot_idx] = bid

        # Remove unfilled slots (team hasn't sent all 9 batters up yet)
        ordered_pids = [p for p in ordered_pids if p is not None]

        # Fallback for teams that haven't batted yet (e.g. home team in Middle of 1st):
        # no plays exist for batting_half, so build order from battingOrder field instead.
        if not ordered_pids:
            batting_order_ids = team_box.get('battingOrder', [])
            slot_to_pid = {}
            for pid in batting_order_ids:
                pdata = all_players.get(f'ID{pid}', {})
                bat_str = str(pdata.get('battingOrder', ''))
                slot = int(bat_str[0]) if bat_str and bat_str[0].isdigit() else None
                if slot:
                    slot_to_pid[slot] = pid
            ordered_pids = [slot_to_pid[s] for s in sorted(slot_to_pid.keys())]

        if not ordered_pids:
            return {}

        # Find the last batter from this team's most recent half-inning
        last_batter_pid = None
        for play in reversed(all_plays):
            if play.get('about', {}).get('halfInning', '') != batting_half:
                continue
            bid = play.get('matchup', {}).get('batter', {}).get('id')
            if bid:
                last_batter_pid = bid
                break

        start = 0  # default: top of order if team hasn't batted yet
        if last_batter_pid:
            if last_batter_pid in ordered_pids:
                last_idx = ordered_pids.index(last_batter_pid)
                start = (last_idx + 1) % len(ordered_pids)
            else:
                # Subbed-out player — resolve slot from battingOrder field
                pdata = all_players.get(f'ID{last_batter_pid}', {})
                bat_str = str(pdata.get('battingOrder', ''))
                if bat_str and bat_str[0].isdigit():
                    last_slot = int(bat_str[0])
                    start = last_slot % len(ordered_pids)

        n = len(ordered_pids)
        next_3_pids = [ordered_pids[(start + i) % n] for i in range(min(3, n))]

        def _name(pid):
            """Name."""
            return _full_name(pid)

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

_EVENT_ABBR = {
    'Single': '1B', 'Double': '2B', 'Triple': '3B', 'Home Run': 'HR',
    'Flyout': 'F', 'Fly Out': 'F', 'Pop Out': 'PO', 'Foul Flyout': 'FF',
    'Lineout': 'L', 'Line Out': 'L',
    'Groundout': 'G', 'Ground Out': 'G', 'Bunt Groundout': 'BG',
    'Double Play': 'DP', 'Grounded Into Double Play': 'DP',
    "Fielder's Choice Out": 'FC', "Fielder's Choice": 'FC',
    'Sacrifice Fly': 'SF', 'Sacrifice Bunt': 'SB', 'Bunt Pop Out': 'BPO',
    'Field Error': 'E',
}


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
        # Use the same credits-based notation as the scorecard (e.g. 'F9', 'L4')
        # so flyouts/lineouts on the field diagram show the fielder who made the play.
        abbr = _build_scorecard_notation(play) or _EVENT_ABBR.get(event, event[:2].upper() if event else '?')
        if cx is not None and cy is not None:
            distance = hit_data.get('totalDistance')
            exit_velo = hit_data.get('launchSpeed')
            launch_angle = hit_data.get('launchAngle')
            hits.append({'x': cx, 'y': cy, 'is_hr': is_hr, 'is_hit': is_hit, 'is_out': is_out,
                         'player': last_name, 'inning': hit_inning, 'half': hit_half,
                         'abbr': abbr, 'distance': distance,
                         'exit_velo': exit_velo, 'launch_angle': launch_angle})
            continue
        # Fall back to playEvents
        for ev in play.get('playEvents', []):
            hit_data = ev.get('hitData', {})
            cx = hit_data.get('coordinates', {}).get('coordX')
            cy = hit_data.get('coordinates', {}).get('coordY')
            if cx is not None and cy is not None:
                distance = hit_data.get('totalDistance')
                exit_velo = hit_data.get('launchSpeed')
                launch_angle = hit_data.get('launchAngle')
                hits.append({'x': cx, 'y': cy, 'is_hr': is_hr, 'is_hit': is_hit, 'is_out': is_out,
                             'player': last_name, 'inning': hit_inning, 'half': hit_half,
                             'abbr': abbr, 'distance': distance,
                             'exit_velo': exit_velo, 'launch_angle': launch_angle})
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
    pitches = _extract_pitches_detailed(plays)
    # Keep only the last 7 batted balls so old markers are removed from the
    # field diagram instead of accumulating for the whole game.
    all_hits = _extract_all_hit_coordinates(plays)[-7:]
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
    'Interference': 'INT',
    'Runner Out': 'RO',
    'Force Out': 'FOUT',
    'Field Out': 'FO',
    'Infield Fly': 'IF',
}


def _map_event_to_code(event):
    """Map an API event string to a scorecard abbreviation."""
    return _EVENT_CODE_MAP.get(event, event[:3] if event else '')


_POS_KEYWORDS_FETCH = [
    ('center fielder', '8'), ('right fielder', '9'), ('left fielder', '7'),
    ('first baseman', '3'), ('second baseman', '4'), ('third baseman', '5'),
    ('shortstop', '6'), ('catcher', '2'), ('pitcher', '1'),
]


def _pos_from_desc(description):
    """Return the primary putout fielder position code from a play description."""
    if not description:
        return ''
    dl = description.lower()
    for kw, code in _POS_KEYWORDS_FETCH:
        if kw in dl:
            return code
    return ''


def _build_scorecard_notation(play):
    """Return scorecard notation (e.g. 'F7', '6-4-3 DP', 'K', '1B') from a play dict."""
    result  = play.get('result', {})
    event   = result.get('event', '')
    et      = (result.get('eventType') or '').lower().replace(' ', '_')
    credits = play.get('credits', [])

    _SIMPLE = {
        'Strikeout': 'K', 'Strikeout Looking': 'Kl',
        'Walk': 'BB', 'Intent Walk': 'IBB', 'Hit By Pitch': 'HBP',
        'Runner Placed On Base': 'PR',
        'Single': '1B', 'Double': '2B', 'Triple': '3B', 'Home Run': 'HR',
        'Balk': 'BLK', 'Wild Pitch': 'WP', 'Passed Ball': 'PB',
        'Catcher Interf': 'CI', 'Batter Interference': 'BI',
        'Stolen Base': 'SB', 'Stolen Base 2B': 'SB', 'Stolen Base 3B': 'SB', 'Stolen Base Home': 'SB',
    }
    if event in _SIMPLE:
        code = _SIMPLE[event]
        # MLB API sometimes returns 'Strikeout' for both swinging and looking.
        # Fall back to checking the last pitch call code: 'C' = called strike.
        if code == 'K':
            for pe in reversed(play.get('playEvents', [])):
                if pe.get('isPitch'):
                    if (pe.get('details', {}).get('call', {}).get('code') or '').upper() == 'C':
                        code = 'Kl'
                    break
            # Final fallback: check the play description when pitch data is absent or incomplete.
            if code == 'K':
                _desc = (result.get('description') or '').lower()
                if 'called out on strikes' in _desc or 'strikes out looking' in _desc:
                    code = 'Kl'
        return code

    if event == 'Field Error':
        assists = []
        error_pos = ''
        for cr in credits:
            credit = (cr.get('credit') or '').lower()
            pos = cr.get('position', {}).get('code', '')
            if not (pos and pos.isdigit()):
                continue
            if 'error' in credit:
                error_pos = pos
            elif 'assist' in credit:
                if not assists or assists[-1] != pos:
                    assists.append(pos)
        if assists and error_pos:
            return f'{"-".join(assists)} E{error_pos}'
        if error_pos:
            return f'E{error_pos}'
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

    _desc = result.get('description', '')

    if event in ('Flyout',):
        if is_dp and pos_seq:
            return '-'.join(pos_seq) + dp_suffix
        if putout_pos:
            return f'F{putout_pos}'
        _fp = _pos_from_desc(_desc)
        return f'F{_fp}' if _fp else 'FO'

    if event in ('Lineout',):
        if is_dp and pos_seq:
            return '-'.join(pos_seq) + dp_suffix
        if putout_pos:
            return f'L{putout_pos}'
        _fp = _pos_from_desc(_desc)
        return f'L{_fp}' if _fp else 'LO'

    if event in ('Pop Out', 'Popout'):
        if putout_pos:
            return f'P{putout_pos}'
        _fp = _pos_from_desc(_desc)
        return f'P{_fp}' if _fp else 'PO'

    if event in ('Sac Fly', 'Sac Fly Double Play'):
        if is_dp and pos_seq:
            return '-'.join(pos_seq) + dp_suffix
        if putout_pos:
            return f'SF{putout_pos}'
        _fp = _pos_from_desc(_desc)
        return f'SF{_fp}' if _fp else 'SF'

    if event in ('Sac Bunt', 'Sacrifice Bunt DP', 'Sac Bunt Double Play'):
        seq = '-'.join(pos_seq) if pos_seq else ''
        return f'SAC {seq}{dp_suffix}' if seq else 'SAC'

    if event in ('Fielders Choice', 'Fielders Choice Out'):
        seq = '-'.join(pos_seq) if pos_seq else ''
        return f'{seq} FC{dp_suffix}' if seq else 'FC'

    _is_cs  = event.startswith('Caught Stealing')
    _is_pk  = event.startswith('Pickoff')
    _is_sdp = event == 'Strikeout Double Play'

    # All out events: return fielder sequence from credits.
    if pos_seq:
        seq = '-'.join(pos_seq) + dp_suffix
        if _is_cs:  return f'CS {seq}'
        if _is_pk:  return f'PO {seq}'
        if _is_sdp: return f'K {"-".join(pos_seq)}'
        return seq

    # Credits absent — parse fielder positions from the play description.
    # Find every occurrence of each position keyword so repeated touches
    # (e.g. catcher in a rundown) are captured; cap at 5 fielders.
    if _desc:
        _dl = _desc.lower()
        _pos_kws = [
            ('center fielder', '8'), ('right fielder', '9'), ('left fielder', '7'),
            ('first baseman', '3'), ('second baseman', '4'), ('third baseman', '5'),
            ('shortstop', '6'), ('catcher', '2'), ('pitcher', '1'),
        ]
        _hits = []
        for _kw, _code in _pos_kws:
            _start = 0
            while True:
                _idx = _dl.find(_kw, _start)
                if _idx < 0:
                    break
                _hits.append((_idx, _code))
                _start = _idx + 1
        _hits.sort()
        if _hits:
            _seq = '-'.join(c for _, c in _hits[:5]) + dp_suffix
            if _is_cs:  return f'CS {_seq}'
            if _is_pk:  return f'PO {_seq}'
            if _is_sdp: return f'K {_seq}'
            return _seq

    # Fallbacks when credits are absent.
    if _is_cs:  return 'CS'
    if _is_pk:  return 'PO'
    if _is_sdp: return 'K'
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
    team_info.get('id')

    # Build player lookup
    player_map = {}
    for _key, pdata in players.items():
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
        result.get('rbi', 0)
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
