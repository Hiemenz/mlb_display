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


def _extract_pitches(plays):
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


def _extract_hit_coordinates(plays):
    """Walk backward through allPlays to find most recent play with hitData coordinates."""
    all_plays = plays.get('allPlays', [])
    for play in reversed(all_plays):
        hit_data = play.get('hitData', {})
        cx = hit_data.get('coordinates', {}).get('coordX')
        cy = hit_data.get('coordinates', {}).get('coordY')
        if cx is not None and cy is not None:
            return (cx, cy)
        # Also check playEvents for hit data
        for event in reversed(play.get('playEvents', [])):
            hit_data = event.get('hitData', {})
            cx = hit_data.get('coordinates', {}).get('coordX')
            cy = hit_data.get('coordinates', {}).get('coordY')
            if cx is not None and cy is not None:
                return (cx, cy)
    return None


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

    batter_info = _get_player_info(boxscore, batter_id, 'batting')
    pitcher_info = _get_player_info(boxscore, pitcher_id, 'pitching')

    # Pitch locations and hit coordinates
    pitches = _extract_pitches(plays)
    hit_coords = _extract_hit_coordinates(plays)

    # Last play description
    current_play = plays.get('currentPlay', {})
    last_play_desc = current_play.get('result', {}).get('description', '')
    if not last_play_desc:
        all_plays = plays.get('allPlays', [])
        if all_plays:
            last_play_desc = all_plays[-1].get('result', {}).get('description', '')

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
        'pitches': pitches,
        'hit_coords': hit_coords,
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


# --- Scorecard Data ---

_EVENT_CODE_MAP = {
    'Strikeout': 'K',
    'Strikeout Looking': 'Kl',
    'Strikeout Double Play': 'K',
    'Walk': 'BB',
    'Intent Walk': 'IBB',
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
        # Shorten to last name
        parts = name.split()
        last_name = parts[-1] if parts else name
        position = pdata.get('position', {}).get('abbreviation', '')
        bat_order = pdata.get('battingOrder', '')
        order_slot = int(str(bat_order)[:1]) if bat_order else len(lineup) + 1

        bat_stats = pdata.get('stats', {}).get('batting', {})

        entry = {
            'name': last_name,
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
            entry['sub'] = True
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
            if inning not in lineup[slot]['at_bats']:
                lineup[slot]['at_bats'][inning] = []
            lineup[slot]['at_bats'][inning].append({
                'code': code,
                'bases': bases,
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
    }
