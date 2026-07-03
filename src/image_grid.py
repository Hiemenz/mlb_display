import os
# import socket  # disabled with QR code feature

# import qrcode  # disabled — not supported on this Pi build

from util import load_json_file, load_yaml_file
from image_assets import _get_font, ImageDraw, Image
from image_standings import _WC_STRIP_H
from image_box import draw_box, draw_wide_box


# Live game states that qualify for a wide (2-cell) tile. Challenge/review states
# are still an active game, so they must keep the wide slot they already had.
_LIVE_WIDE_STATES = ('In Progress', 'Player challenge', 'Manager challenge')


def _find_wide_games(game_list, config, team_data):
    """Return the set of game_list indices to show as wide (2-cell) tiles.

    Each wide cell consumes one extra grid slot, and the 5×3 grid holds only
    15 slot units total. So at most ``15 - len(game_list)`` games can be widened
    without pushing a game off the grid — e.g. with 13 games only 2 may be wide.
    When more games are in progress than that budget allows, the games farthest
    along (by inning) are chosen.

    When wide_cell_always=true in config, always show exactly one wide cell —
    the in-progress game farthest into the game by inning — even with 15+ games
    (one game will be dropped from the grid to accommodate the extra slot).

    When wide_cell_featured=true, the wide cell always goes to the featured
    (primary) team's game when it is live; otherwise it falls back to the game
    farthest along. Like wide_cell_always, this shows a wide cell even with 15+
    games — but the choice prefers the featured team over raw game progress.

    Geometry fix-up (col=4 conflicts) is handled separately by _reorder_for_wide,
    which swaps in-progress games with adjacent normal games so they land at a
    valid column. This function selects purely by priority.

    A game under review ('Player challenge'/'Manager challenge') is still live —
    it is treated as in-progress so it keeps its wide tile instead of collapsing
    to a single cell and handing the slot to another game mid-review.
    """
    in_progress = [i for i, g in enumerate(game_list) if g.get('detailed_state') in _LIVE_WIDE_STATES]

    # Featured-team preference: index of the primary team's live game, if enabled.
    featured_idx = None
    if config.get('wide_cell_featured', False):
        primary = config.get('primary', '')
        if primary:
            abbr_map = team_data.get('team_abbreviation', {})
            for i in in_progress:
                g = game_list[i]
                away = abbr_map.get(str(g.get('away_team_id', '')), '')
                home = abbr_map.get(str(g.get('home_team_id', '')), '')
                if primary in (away, home):
                    featured_idx = i
                    break

    # Find the in-progress game farthest along:
    # 1. highest inning  2. Bottom > Top  3. most outs  4. earliest start time
    def _progress(idx):
        g = game_list[idx]
        inning = g.get('current_inning') or 0
        # Order within an inning: Top < Middle (break) < Bottom < End (break). This
        # keeps a game that just went to break ranked at/above where it was, so it
        # doesn't lose its wide slot to another game when the inning turns over.
        half  = {'Top': 0, 'Middle': 1, 'Bottom': 2, 'End': 3}.get(g.get('inningState'), 0)
        outs  = g.get('num_of_outs') or 0
        # Earlier start = higher priority when all else equal; negate so max() works
        start = g.get('game_datetime') or ''
        return (inning, half, outs, start)

    # Ranking used when a subset must be chosen: the featured live game outranks
    # everything else; ties beyond that fall back to game progress.
    def _rank(idx):
        return (1 if idx == featured_idx else 0,) + _progress(idx)

    if len(game_list) < 15:
        # Only widen as many games as there are spare slots (15 - games).
        max_wide = 15 - len(game_list)
        if len(in_progress) <= max_wide:
            return set(in_progress)
        return set(sorted(in_progress, key=_rank, reverse=True)[:max_wide])

    # 15+ games: show a single wide cell if either always-on or featured preference
    # is enabled. The pick prefers the featured live game (via _rank) and otherwise
    # falls back to the game farthest along.
    if not in_progress:
        return set()
    if config.get('wide_cell_always', False) or config.get('wide_cell_featured', False):
        return {max(in_progress, key=_rank)}
    return set()


def _reorder_for_wide(game_list, wide_set):
    """Reorder game_list so every game in wide_set can actually render wide.

    A wide cell must start at col 0-3 (can't span from col 4 into col 5).
    When a wide game lands at col 4, swap it with the normal game immediately
    after it; the wide game shifts to col 0 of the next row and can span right.
    If the next game is also wide (can't swap), drop the conflicting wide game.

    Returns (new_game_list, new_wide_set).
    """
    game_list = list(game_list)
    wide_set = set(wide_set)

    for _ in range(len(wide_set) + 1):  # converges in at most one pass per wide game
        slot = 0
        conflict = None
        for gi in range(len(game_list)):
            if slot >= 15:
                break
            col = slot % 5
            if gi in wide_set:
                if col >= 4:
                    conflict = gi
                    break
                slot += 2
            else:
                slot += 1

        if conflict is None:
            break

        b = conflict
        next_b = b + 1
        if next_b < len(game_list) and next_b not in wide_set:
            game_list[b], game_list[next_b] = game_list[next_b], game_list[b]
            wide_set.discard(b)
            wide_set.add(next_b)
        else:
            wide_set.discard(b)

    return game_list, wide_set


def _move_non_live_to_fillers(game_list, wide_set):
    """Swap live games out of filler slots in wide rows.

    Every row that contains a wide (2-cell) tile must also have at least one
    single-cell slot to fill the 5-column width (e.g. 2+2+1=5).  That slot
    should show a finished or not-yet-started game, not a live game — a live
    game wasted in a narrow filler cell is better placed as a normal single
    cell in a non-wide row.

    Scans the visible 15-slot boundary for live games sitting in filler slots
    (normal cells whose row contains at least one wide tile) and swaps each
    with the last non-live normal game from a non-wide row, perturbing the
    ordering as little as possible.  Returns the updated game_list.
    """
    game_list = list(game_list)

    # Simulate slot positions for every game within the 15-unit boundary.
    positions = []
    slot_idx = 0
    for gi in range(len(game_list)):
        if slot_idx >= 15:
            break
        col = slot_idx % 5
        row = slot_idx // 5
        if gi in wide_set and col < 4:
            positions.append(('wide', col, row))
            slot_idx += 2
        else:
            positions.append(('normal', col, row))
            slot_idx += 1

    wide_rows = {pos[2] for pos in positions if pos[0] == 'wide'}
    if not wide_rows:
        return game_list

    # Filler slots: normal cells that share a row with at least one wide tile.
    filler_idxs = [
        i for i, pos in enumerate(positions)
        if pos[0] == 'normal' and pos[2] in wide_rows
    ]

    # Swap candidates: non-live games in normal slots in non-wide rows,
    # iterated from the end to minimise disruption to the earlier ordering.
    non_wide_non_live = [
        i for i in range(len(positions) - 1, -1, -1)
        if positions[i][0] == 'normal'
        and positions[i][2] not in wide_rows
        and game_list[i].get('detailed_state') not in _LIVE_WIDE_STATES
    ]
    cand_iter = iter(non_wide_non_live)

    for fi in filler_idxs:
        if game_list[fi].get('detailed_state') in _LIVE_WIDE_STATES:
            try:
                ti = next(cand_iter)
                game_list[fi], game_list[ti] = game_list[ti], game_list[fi]
            except StopIteration:
                break  # no more non-live games available to swap in

    return game_list


def compute_grid_layout(game_state_data, team_data, config):
    """Return (ordered_game_list, slots) for the 5×3 scoreboard grid.

    ``slots`` is a list parallel to the returned game_list, each entry a
    ``(slot_type, grid_col, grid_row)`` tuple where slot_type is 'wide' or
    'normal'. This is the single source of truth for grid geometry: both the
    renderer (draw_out_of_town_score_board) and the partial-refresh region
    calculation must use it so wide cells (which consume 2 slot units and may
    be reordered) line up exactly.
    """
    # Reorder games so the primary team's game appears first in the grid
    game_list = list(game_state_data)
    if config.get('favorite_team_first', False):
        primary = config.get('primary', '')
        if primary:
            abbr_map = team_data.get('team_abbreviation', {})
            for i, g in enumerate(game_list):
                away_abbr = abbr_map.get(str(g.get('away_team_id', '')), '')
                home_abbr = abbr_map.get(str(g.get('home_team_id', '')), '')
                if primary in (away_abbr, home_abbr):
                    game_list.insert(0, game_list.pop(i))
                    break

    # With 16+ games, a doubleheader, and a rainout, push postponed/cancelled games
    # off the 5×3 grid (to position 16+) so the doubleheader pair stays visible
    # instead. This applies even if the affected team is the featured team.
    _RAINOUT_STATES = {'Postponed', 'Cancelled', 'Cancelled: Rain'}
    _has_dh = any(g.get('double_header', 'N') not in ('N', '', None) for g in game_list)
    _ppd_games = [g for g in game_list if g.get('detailed_state', '') in _RAINOUT_STATES]
    if len(game_list) >= 16 and _has_dh and _ppd_games:
        for _ppd_g in _ppd_games:
            game_list.remove(_ppd_g)
            game_list.append(_ppd_g)

    # Determine which games show as wide (2-cell) tiles, then reorder so any
    # wide game that would land at col=4 swaps with the normal game after it.
    # Finally, move non-live games into the filler single-cell slots that exist
    # in every wide row (e.g. 2-wide + 1-filler = 5 cols) so a live game never
    # sits in a filler slot when a finished or not-yet-started game can take it.
    _wide_set = _find_wide_games(game_list, config, team_data)
    if _wide_set:
        game_list, _wide_set = _reorder_for_wide(game_list, _wide_set)
        game_list = _move_non_live_to_fillers(game_list, _wide_set)

    # Build an ordered list of (slot_type, grid_col, grid_row).
    # Each wide game consumes 2 horizontal slot units; normal games consume 1.
    # Wide games on the last column (col 4) fall back to normal (can't span right).
    # Stop adding slots once the 5×3 grid is full (15 slot units).
    if _wide_set:
        _slots = []
        _slot_idx = 0
        for _gi in range(len(game_list)):
            if _slot_idx >= 15:
                break
            _row = _slot_idx // 5
            _col = _slot_idx % 5
            if _gi in _wide_set and _col < 4:
                _slots.append(('wide', _col, _row))
                _slot_idx += 2
            else:
                _slots.append(('normal', _col, _row))
                _slot_idx += 1
    else:
        _slots = [('normal', _gi % 5, _gi // 5) for _gi in range(len(game_list))]

    return game_list, _slots


# def _get_lan_ip():
#     """Best-effort local-network IP for this machine, for the config-server QR
#     code. Doesn't actually send any packets (UDP connect() just picks a route)."""
#     try:
#         with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
#             s.connect(('8.8.8.8', 80))
#             return s.getsockname()[0]
#     except OSError:
#         try:
#             return socket.gethostbyname(socket.gethostname())
#         except OSError:
#             return None


def _free_grid_slot(slots):
    """Return the first free (col, row) slot-unit in the 5x3 grid given the
    already-occupied slots (wide slots consume 2 horizontal units), or None
    if all 15 are taken."""
    occupied = set()
    for slot_type, col, row in slots:
        occupied.add((col, row))
        if slot_type == 'wide':
            occupied.add((col + 1, row))
    for _idx in range(15):
        _col, _row = _idx % 5, _idx // 5
        if (_col, _row) not in occupied:
            return (_col, _row)
    return None


# def _draw_config_qr_cell(Himage, sx, sy, url):
#     """Paste a QR code linking to the config web server into a normal
#     (150x150) grid cell at (sx, sy)."""
#     qr_img = qrcode.make(url).convert('1')
#     _pad = 8
#     _size = 150 - 2 * _pad
#     qr_img = qr_img.resize((_size, _size), Image.NEAREST)
#     Himage.paste(qr_img, (sx + _pad, sy + _pad))
#     return Himage


def draw_out_of_town_score_board(Himage, game_state_data, team_data, date_str=None, changed_game_ids=None, use_logos=False, logo_x_offset=2, show_win_prob=False):

    draw = ImageDraw.Draw(Himage)
    config = load_yaml_file('config.yaml')

    # --- Date label: centered in the top strip, as large as possible, bold ---
    if date_str:
        from datetime import datetime as _dt
        try:
            _d = _dt.strptime(date_str, '%Y-%m-%d')
            _label_full  = _d.strftime('%B %-d, %Y')   # e.g. "February 28, 2026"
            _label_short = _d.strftime('%b %-d, %Y')   # e.g. "Feb 28, 2026"
        except (ValueError, AttributeError):
            _label_full = _label_short = date_str

        # When wildcard standings fill the header strip the center gap shrinks to ~159px.
        # Without wildcard standings there is ~560px of clear space.
        if config.get('show_wildcard_standings', False):
            _MAX_LABEL_W = 155
        else:
            _MAX_LABEL_W = 560

        _font_date = _get_font(14)
        _fsize = 14
        _label = _label_full
        for _candidate in (_label_full, _label_short):
            for _fsize in (24, 22, 20, 18, 16, 14):
                _font_date = _get_font(_fsize)
                if int(_font_date.getlength(_candidate)) <= _MAX_LABEL_W:
                    _label = _candidate
                    break
            else:
                continue  # this format didn't fit at any size; try shorter one
            break          # found a fitting size

        _lw = int(_font_date.getlength(_label))
        _lx = (800 - _lw) // 2
        _ly = max(0, (_WC_STRIP_H - _fsize) // 2)
        draw.text((_lx,     _ly), _label, font=_font_date, fill=0)
        draw.text((_lx + 1, _ly), _label, font=_font_date, fill=0)  # bold stroke

    x_start = 32
    y_start = 30

    game_list, _slots = compute_grid_layout(game_state_data, team_data, config)

    # Build per-team stats lookup {str(team_id): {'streak', 'l10_wins', 'l10_losses', 'wins', 'losses'}}
    _standings = load_json_file('standings.json')
    streak_map = {}
    for _div_teams in _standings.get('standings', {}).values():
        for _t in _div_teams:
            _tid = str(_t.get('team_id', ''))
            if _tid:
                streak_map[_tid] = {
                    'streak': _t.get('streak'),
                    'l10_wins': _t.get('last_ten_wins'),
                    'l10_losses': _t.get('last_ten_losses'),
                    'wins': _t.get('league_record_wins'),
                    'losses': _t.get('league_record_losses'),
                }

    for game, slot_info in zip(game_list, _slots):
        slot_type, gx, gy = slot_info
        game_pk_key = str(game.get('game_pk', ''))
        score_changed = changed_game_ids is not None and game_pk_key in changed_game_ids
        sx = gx * 150 + x_start
        sy = gy * 150 + y_start
        if slot_type == 'wide':
            Himage = draw_wide_box(
                Himage, sx, sy, game, team_data,
                score_changed=score_changed,
                use_logos=use_logos,
                logo_x_offset=logo_x_offset,
                show_win_prob=show_win_prob,
                streak_map=streak_map,
            )
        else:
            Himage = draw_box(
                Himage, sx, sy, game, team_data,
                score_changed=score_changed,
                use_logos=use_logos,
                logo_x_offset=logo_x_offset,
                show_win_prob=show_win_prob,
                streak_map=streak_map,
            )

    # QR code disabled — not supported on this Pi build
    # if config.get('show_config_qr', True):
    #     _free = _free_grid_slot(_slots)
    #     if _free is not None:
    #         _ip = _get_lan_ip()
    #         if _ip:
    #             _port = config.get('config_server_port', 8080)
    #             _qx = _free[0] * 150 + x_start
    #             _qy = _free[1] * 150 + y_start
    #             Himage = _draw_config_qr_cell(Himage, _qx, _qy, f'http://{_ip}:{_port}/')

    Himage.save('score_board.bmp')
    return Himage
