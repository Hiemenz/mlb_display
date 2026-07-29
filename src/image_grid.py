import os
from collections import deque
# import socket  # disabled with QR code feature

# import qrcode  # disabled — not supported on this Pi build

from util import load_json_file, load_yaml_file
from image_assets import _get_font, ImageDraw
from image_standings import _WC_STRIP_H
from image_box import draw_box, draw_wide_box, draw_triple_box
from image_leaders import draw_leaders_cell, rotating_categories, _CATEGORIES as _LEADER_CATEGORIES
from image_transactions import draw_transactions_cell
from image_news import draw_news_cell
from image_magic import draw_magic_cell
from image_streaks import draw_streaks_cell
from image_scoreless import draw_scoreless_cell
from image_lineup import draw_lineup_cell
from image_deadline import draw_deadline_cell


# Live game states that qualify for a wide (2-cell) tile. Challenge/review states
# are still an active game, so they must keep the wide slot they already had.
_LIVE_WIDE_STATES = ('In Progress', 'Player challenge', 'Manager challenge')

_FINAL_STATES = {'Final', 'Game Over', 'Final: Tied'}

# Games that haven't started yet — grouped with _FINAL_STATES by
# _hide_non_live_games_enabled since neither shows anything worth the slot
# once a live game could use the room instead.
_PRE_GAME_STATES = {'Scheduled', 'Pre-Game', 'Warmup', 'Delayed Start'}

_NON_LIVE_HIDE_STATES = _FINAL_STATES | _PRE_GAME_STATES

# Number of live games that can be shown as a triple (3-cell) tile at once,
# ranked by how far along they are (see _game_progress).
_MAX_TRIPLE_TILES = 3


def _hide_non_live_games_enabled(config):
    """Whether finished/not-yet-started games should be dropped from the grid,
    per config.yaml's hide_non_live_games key or the HIDE_NON_LIVE_GAMES env
    var (env wins)."""
    _env = os.environ.get('HIDE_NON_LIVE_GAMES')
    if _env is not None:
        return _env.lower() in ('true', '1', 'yes')
    return config.get('hide_non_live_games', False)


def _overflow_priority(g):
    """Sort key used when there are more games than grid slots: live games
    first, Final games last, everything else in between."""
    state = g.get('detailed_state')
    if state in _LIVE_WIDE_STATES:
        return 0
    if state in _FINAL_STATES:
        return 2
    return 1


def _game_progress(g):
    """How far into the game a live game is: 1. highest inning  2. Bottom >
    Top  3. most outs  4. earliest start time. Used to rank live games when
    only some of them can be shown as wide tiles."""
    inning = g.get('current_inning') or 0
    # Order within an inning: Top < Middle (break) < Bottom < End (break). This
    # keeps a game that just went to break ranked at/above where it was, so it
    # doesn't lose its wide slot to another game when the inning turns over.
    half  = {'Top': 0, 'Middle': 1, 'Bottom': 2, 'End': 3}.get(g.get('inningState'), 0)
    outs  = g.get('num_of_outs') or 0
    # Earlier start = higher priority when all else equal; negate so max() works
    start = g.get('game_datetime') or ''
    return (inning, half, outs, start)


def _featured_live_index(games, indices, config, team_data):
    """Return the index (from ``indices``) of the featured (primary) team's
    live game, or None if wide_cell_featured is off or the team isn't live."""
    if not config.get('wide_cell_featured', False):
        return None
    primary = config.get('primary', '')
    if not primary:
        return None
    abbr_map = team_data.get('team_abbreviation', {})
    for i in indices:
        g = games[i]
        away = abbr_map.get(str(g.get('away_team_id', '')), '')
        home = abbr_map.get(str(g.get('home_team_id', '')), '')
        if primary in (away, home):
            return i
    return None


def _lay_out_row_major(tokens, start_slot):
    """Place (slot_type, game) tokens row-major from ``start_slot`` (5 units
    per row: 3 for 'triple', 2 for 'wide', 1 for 'normal'), never leaving a
    dead gap.

    A 'triple' tile needs 3 free columns and is demoted to 'wide' when only
    1-2 columns remain in its row.  A 'wide' tile can't start in the last
    column (only 1 unit left) and is demoted to 'normal' there.  When
    demoting a tile, a later token of the right type is pulled forward if one
    exists; otherwise the tile itself is demoted to fill the gap.

    Returns (ordered_games, positions, next_slot_idx).
    """
    tokens = list(tokens)
    ordered = []
    positions = []
    slot_idx = start_slot
    i = 0
    while i < len(tokens):
        slot_type, g = tokens[i]
        col = slot_idx % 5
        # Triple tile needs cols 0-2 (3 free); demote to 'wide' when col>=3
        if slot_type == 'triple' and col >= 3:
            j = next((k for k in range(i + 1, len(tokens)) if tokens[k][0] in ('wide', 'normal')), None)
            if j is not None:
                tokens[i], tokens[j] = tokens[j], tokens[i]
                slot_type, g = tokens[i]
            else:
                slot_type = 'wide'   # best-effort demotion
        # Wide tile needs 2 free cols; demote to 'normal' when col==4
        if slot_type == 'wide' and col == 4:
            j = next((k for k in range(i + 1, len(tokens)) if tokens[k][0] == 'normal'), None)
            if j is not None:
                tokens[i], tokens[j] = tokens[j], tokens[i]
                slot_type, g = tokens[i]
            else:
                slot_type = 'normal'
        ordered.append(g)
        positions.append((slot_type, slot_idx % 5, slot_idx // 5))
        slot_idx += {'triple': 3, 'wide': 2, 'normal': 1}[slot_type]
        i += 1
    return ordered, positions, slot_idx


def _cluster_live_games(game_list, config, team_data):
    """When there are 2-5 live games (and no grid overflow), group them all
    into their own block at the bottom instead of leaving some behind in
    earlier rows next to finished games. A single live game has nothing to
    be split from, so it's left for _find_wide_games/_pack_grid as before.

    Places every non-live game first, row-major from the top (right after a
    pinned favorite-team game, if any), then starts the live games fresh at
    the next row boundary so they can never be split across a row shared
    with a finished game. As many of them as the grid's overall wide budget
    allows are widened — farthest-along first, featured team preferred when
    wide_cell_featured is set — even if that spills the live block across
    more than one row: filling that room with live games takes priority over
    leaving slots free for other panels (e.g. the leaders tiles), which only
    ever claim whatever grid slots end up genuinely unused. If the non-live
    games don't end on a row boundary, the row before the live block is left
    short instead (the tradeoff that keeps every live game together).

    This bypasses _pack_grid entirely: that function always reserves slot
    (0, 0) for whatever sits at game_list[0], which throws off the row-unit
    math needed to land the live block exactly on a full final row.

    Returns (new_game_list, positions) with positions already computed, or
    (game_list, None) if clustering doesn't apply (fewer than 2 or more than
    5 live games, or grid overflow) — signalling the caller should fall back
    to the general _find_wide_games/_pack_grid path instead.
    """
    if len(game_list) >= 15:
        # At 15+ games there's no spare capacity for a full live row anyway;
        # defer to _find_wide_games, which has its own wide_cell_always /
        # wide_cell_featured handling for this boundary (including the
        # deliberate one-game drop those options allow).
        return game_list, None

    pinned = 1 if (config.get('favorite_team_first', False) and game_list) else 0
    rest = game_list[pinned:]
    live_idxs = [i for i, g in enumerate(rest) if g.get('detailed_state') in _LIVE_WIDE_STATES]
    if not (2 <= len(live_idxs) <= 5):
        return game_list, None

    live_set = set(live_idxs)
    others = [g for i, g in enumerate(rest) if i not in live_set]
    lives = [rest[i] for i in live_idxs]

    global_max_wide = max(0, 15 - len(game_list))
    w = min(len(lives), global_max_wide)

    chosen = set()
    if w > 0:
        featured = _featured_live_index(lives, range(len(lives)), config, team_data)

        def _rank(i):
            return (1 if i == featured else 0,) + _game_progress(lives[i])

        chosen = set(sorted(range(len(lives)), key=_rank, reverse=True)[:w])

    wide_lives = [g for i, g in enumerate(lives) if i in chosen]
    normal_lives = [g for i, g in enumerate(lives) if i not in chosen]
    # Wide tiles lead the live row, with any lone filler cell trailing (e.g.
    # 2+2+1), so the widened/featured games read first left-to-right.
    live_row = [('wide', g) for g in wide_lives] + [('normal', g) for g in normal_lives]

    new_game_list = []
    positions = []
    slot_idx = 0
    if pinned:
        new_game_list.append(game_list[0])
        positions.append(('normal', 0, 0))
        slot_idx = 1
    for g in others:
        new_game_list.append(g)
        positions.append(('normal', slot_idx % 5, slot_idx // 5))
        slot_idx += 1
    # Start the live block at a fresh row boundary — but only if there's
    # still room left for it there; rounding up unconditionally can push it
    # past the 15-slot grid (e.g. 11 others + 2 wide live = 15 units exactly,
    # with no room to spare for the row-alignment gap).
    _live_units = len(lives) + len(wide_lives)
    _rounded = slot_idx + (5 - slot_idx % 5) % 5
    if _rounded + _live_units <= 15:
        slot_idx = _rounded
    _live_ordered, _live_positions, _ = _lay_out_row_major(live_row, slot_idx)
    new_game_list.extend(_live_ordered)
    positions.extend(_live_positions)

    return new_game_list, positions


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

    Geometry fix-up (col=4 conflicts) is handled separately in
    compute_grid_layout's slot builder, which skips a wide game to the next
    row rather than dropping it. This function selects purely by priority.

    A game under review ('Player challenge'/'Manager challenge') is still live —
    it is treated as in-progress so it keeps its wide tile instead of collapsing
    to a single cell and handing the slot to another game mid-review.
    """
    in_progress = [i for i, g in enumerate(game_list) if g.get('detailed_state') in _LIVE_WIDE_STATES]

    # Featured-team preference: index of the primary team's live game, if enabled.
    featured_idx = _featured_live_index(game_list, in_progress, config, team_data)

    # Ranking used when a subset must be chosen: the featured live game outranks
    # everything else; ties beyond that fall back to game progress.
    def _rank(idx):
        """Rank."""
        return (1 if idx == featured_idx else 0,) + _game_progress(game_list[idx])

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


def _find_tile_types(game_list, config, team_data):
    """Return {index: 'triple'|'wide'} for games that should get an expanded tile.

    Up to _MAX_TRIPLE_TILES live games try triple (3-cell) first — the
    featured live game (if any) ranked highest, then whichever games are
    farthest along by inning — falling back to wide (2-cell) once the triple
    budget is used up or the slot budget is tight, and landing on normal
    (1-cell) if there is no room at all. Remaining live games fill leftover
    budget as wide, then normal. The dict is empty when no in-progress games
    exist.
    """
    in_progress = [i for i, g in enumerate(game_list) if g.get('detailed_state') in _LIVE_WIDE_STATES]
    if not in_progress:
        return {}

    featured_idx = _featured_live_index(game_list, in_progress, config, team_data)

    def _rank(idx):
        return (1 if idx == featured_idx else 0,) + _game_progress(game_list[idx])

    sorted_live = sorted(in_progress, key=_rank, reverse=True)

    if len(game_list) < 15:
        # Extra slot units available beyond what normal tiles would consume.
        remaining = 15 - len(game_list)
        tile_map = {}
        triples_assigned = 0
        for idx in sorted_live:
            if triples_assigned < _MAX_TRIPLE_TILES and remaining >= 2:
                tile_map[idx] = 'triple'
                remaining -= 2
                triples_assigned += 1
            elif remaining >= 1:
                tile_map[idx] = 'wide'
                remaining -= 1
        return tile_map

    # 15+ games: expanding forces a game off the grid — only do it if the
    # config explicitly opts in (wide_cell_always or wide_cell_featured).
    if not (config.get('wide_cell_always', False) or config.get('wide_cell_featured', False)):
        return {}
    best = max(in_progress, key=_rank)
    return {best: 'triple'}


def _pack_multi_triple_rows(game_list, tile_type_map):
    """Pack the grid when 2+ games need a triple (3-cell) tile.

    _pack_grid's bucket packer assumes at most one triple tile ever exists
    (true before multiple live games could all rank for a triple); its
    row_caps bucketing silently strands extra triples when 2+ are requested
    in the same packing pass. This function is the safe alternative: each
    triple claims its own row outright (column 0-2) up front, in original
    relative order — the grid has exactly 3 rows, matching
    _MAX_TRIPLE_TILES, so this never runs out of rows in practice. Every
    other (wide/normal) game is then packed row-major into whatever's left —
    starting with the 2 leftover columns of each triple's row, then any
    fully-free rows — demoting wide to normal in place when a row has just
    1 column left, so no game's slot capacity is ever wasted and nothing
    gets dropped.

    Returns (new_game_list, positions).
    """
    _STEP = {'triple': 3, 'wide': 2, 'normal': 1}
    n_rows = 3

    triple_idxs = [i for i in range(len(game_list)) if tile_type_map.get(i) == 'triple']
    other_idxs = [i for i in range(len(game_list)) if tile_type_map.get(i) != 'triple']

    # _find_tile_types caps triples at _MAX_TRIPLE_TILES (== n_rows), so this
    # only trims in the impossible case of a mismatched tile_type_map.
    n_triple_rows = min(len(triple_idxs), n_rows)
    demoted = set(triple_idxs[n_triple_rows:])
    triple_idxs = triple_idxs[:n_triple_rows]
    if demoted:
        other_idxs = list(demoted) + other_idxs

    new_order = []
    positions = []
    row_next_col = [0] * n_rows

    for row_i, gi in enumerate(triple_idxs):
        new_order.append(game_list[gi])
        positions.append(('triple', 0, row_i))
        row_next_col[row_i] = 3

    cur_row = 0
    for gi in other_idxs:
        slot_type = 'wide' if gi in demoted else tile_type_map.get(gi, 'normal')
        needed = _STEP[slot_type]
        while cur_row < n_rows:
            cap_left = 5 - row_next_col[cur_row]
            if cap_left >= needed:
                break
            if slot_type == 'wide' and cap_left >= 1:
                slot_type, needed = 'normal', 1
                break
            cur_row += 1
        if cur_row >= n_rows:
            break  # grid is genuinely full
        col = row_next_col[cur_row]
        new_order.append(game_list[gi])
        positions.append((slot_type, col, cur_row))
        row_next_col[cur_row] += needed

    return new_order, positions


def _pack_grid(game_list, tile_type_map):
    """Pack games into 5-unit-wide rows. With <15 games, uses complex bottom-up
    packing to efficiently place triple (3-cell) and wide (2-cell) tiles.
    With 15+ games, uses simple row-major layout to preserve game order while
    staying within the 15-slot limit.

    ``tile_type_map`` is a dict {index: 'triple'|'wide'} from _find_tile_types.

    Index 0 (the favorite team's game when favorite_team_first is set) is
    always placed first, in row 0 col 0.

    Returns (new_game_list, positions) where positions is a list of
    (slot_type, grid_col, grid_row) parallel to new_game_list.
    """
    if not game_list:
        return [], []

    _STEP = {'triple': 3, 'wide': 2, 'normal': 1}

    def _tile_type(i):
        return tile_type_map.get(i, 'normal')

    # 2+ triple tiles: the bucket packer below assumes at most one triple
    # ever exists and silently strands extra ones. Use the dedicated packer
    # instead, which gives each triple its own row.
    if sum(1 for i in range(len(game_list)) if _tile_type(i) == 'triple') >= 2:
        return _pack_multi_triple_rows(game_list, tile_type_map)

    # With 15+ games, use simple row-major layout to preserve order
    if len(game_list) >= 15:
        tokens = [(_tile_type(i), game_list[i]) for i in range(len(game_list))]
        ordered, positions, slot_idx = _lay_out_row_major(tokens, 0)
        if slot_idx > 15:
            trim_count = 0
            for i in range(len(positions)):
                col, row = positions[i][1], positions[i][2]
                slot_num = row * 5 + col
                if slot_num >= 15:
                    break
                trim_count = i + 1
            ordered = ordered[:trim_count]
            positions = positions[:trim_count]
        return ordered, positions

    # With <15 games, use complex packing for efficient tile placement
    pinned_type = _tile_type(0)
    pinned_cost = _STEP[pinned_type]

    rest = range(1, len(game_list))
    triple_queue = [i for i in rest if _tile_type(i) == 'triple']
    wide_queue   = [i for i in rest if _tile_type(i) == 'wide']
    normal_queue = [i for i in rest if _tile_type(i) == 'normal']

    remaining_capacity = 15 - pinned_cost
    total_wanted = 3 * len(triple_queue) + 2 * len(wide_queue) + len(normal_queue)

    new_order = [0]
    positions = [(pinned_type, 0, 0)]

    # Without normal tiles to fill row remainders, bucket packing can orphan
    # wide/triple games when row capacities don't align with tile sizes.
    # Use the row-major overflow path instead in that case.
    if not normal_queue and (triple_queue or wide_queue):
        total_wanted = remaining_capacity + 1  # force overflow path

    if total_wanted > remaining_capacity:
        # More games than the grid can hold — pack front-to-back, largest first
        slot_idx = pinned_cost
        ti = wi = ni = 0
        while slot_idx < 15 and (ti < len(triple_queue) or wi < len(wide_queue) or ni < len(normal_queue)):
            col = slot_idx % 5
            row = slot_idx // 5
            cap_left = 5 - col
            if ti < len(triple_queue) and cap_left >= 3:
                new_order.append(triple_queue[ti])
                positions.append(('triple', col, row))
                ti += 1
                slot_idx += 3
            elif wi < len(wide_queue) and cap_left >= 2:
                new_order.append(wide_queue[wi])
                positions.append(('wide', col, row))
                wi += 1
                slot_idx += 2
            elif ni < len(normal_queue):
                new_order.append(normal_queue[ni])
                positions.append(('normal', col, row))
                ni += 1
                slot_idx += 1
            elif cap_left < 2 and (ti < len(triple_queue) or wi < len(wide_queue)):
                slot_idx += cap_left  # skip to next row
            else:
                break
        return [game_list[i] for i in new_order], positions

    # No overflow: split remaining capacity into row-sized buckets
    row_caps = [5 - pinned_cost]
    left = total_wanted - row_caps[0]
    while left > 5:
        row_caps.append(5)
        left -= 5
    if left > 0 or len(row_caps) == 1:
        row_caps.append(left)

    # Fill buckets bottom-up: triple (3 units) first, wide (2 units) next,
    # normal (1 unit) as filler.  Pop from the end of each queue so later-
    # queued games land in lower rows, preserving original relative order top-to-bottom.
    triple_dq = deque(triple_queue)
    wide_dq   = deque(wide_queue)
    normal_dq = deque(normal_queue)
    bucket_tokens = [None] * len(row_caps)
    for bi in range(len(row_caps) - 1, -1, -1):
        cap = row_caps[bi]
        triple_tokens = []
        wide_tokens   = []
        normal_tokens = []
        while cap >= 3 and triple_dq:
            triple_tokens.append(('triple', triple_dq.pop()))
            cap -= 3
        while cap >= 2 and wide_dq:
            wide_tokens.append(('wide', wide_dq.pop()))
            cap -= 2
        while cap >= 1 and normal_dq:
            normal_tokens.append(('normal', normal_dq.pop()))
            cap -= 1
        triple_tokens.reverse()
        wide_tokens.reverse()
        normal_tokens.reverse()
        # Lone filler cell leads when it shares a row with 2+ wide tiles (1+2+2)
        if len(normal_tokens) == 1 and len(wide_tokens) >= 2 and not triple_tokens:
            bucket_tokens[bi] = normal_tokens + wide_tokens
        else:
            bucket_tokens[bi] = triple_tokens + wide_tokens + normal_tokens

    slot_idx = pinned_cost
    for bi, tokens in enumerate(bucket_tokens):
        row = slot_idx // 5
        col = slot_idx % 5
        row_start = slot_idx
        for slot_type, gi in tokens:
            new_order.append(gi)
            positions.append((slot_type, col, row))
            step = _STEP[slot_type]
            col += step
            slot_idx += step
        slot_idx = row_start + row_caps[bi]

    return [game_list[i] for i in new_order], positions


def _move_non_live_to_fillers(game_list, positions):
    """Swap live games out of filler slots in wide rows.

    Every row that contains a wide (2-cell) tile must also have at least one
    single-cell slot to fill the 5-column width (e.g. 2+2+1=5).  That slot
    should show a finished or not-yet-started game, not a live game — a live
    game wasted in a narrow filler cell is better placed as a normal single
    cell in a non-wide row.

    ``positions`` is the (slot_type, col, row) list already computed for
    ``game_list`` (by _pack_grid) — swapping two games that both sit in
    'normal' slots never changes the geometry, so this can reshuffle
    game_list in place without needing to recompute positions afterward.

    Scans the visible 15-slot boundary for live games sitting in filler slots
    (normal cells whose row contains at least one wide tile) and swaps each
    with the last non-live normal game from a non-wide row, perturbing the
    ordering as little as possible.  Returns the updated game_list.
    """
    game_list = list(game_list)

    wide_rows = {pos[2] for pos in positions if pos[0] in ('wide', 'triple')}
    if not wide_rows:
        return game_list

    # Filler slots: normal cells that share a row with at least one wide tile.
    filler_idxs = [
        i for i, pos in enumerate(positions)
        if pos[0] == 'normal' and pos[2] in wide_rows
    ]

    # Swap candidates: non-live games in normal slots in non-wide rows,
    # iterated from the end to minimise disruption to the earlier ordering.
    # Index 0 is always protected — it holds the featured team's game when
    # favorite_team_first is enabled, and should never be displaced to a filler.
    non_wide_non_live = [
        i for i in range(len(positions) - 1, 0, -1)
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


def _prioritize_live_over_final(full_game_list, placed_list, positions):
    """If tile-packing dropped a live/scheduled/postponed game while a Final
    game still occupies a normal (single-cell) slot, swap them in place — a
    game that's still worth watching should never lose its slot to one that's
    already over, and this is a game the overflow header ticker can pick up.

    Only swaps within 'normal' slots, so slot geometry never changes and no
    repacking is needed. positions is parallel to placed_list.
    """
    placed_pks = {g.get('game_pk') for g in placed_list}
    dropped_worth_showing = [
        g for g in full_game_list
        if g.get('game_pk') not in placed_pks and _overflow_priority(g) < 2
    ]
    if not dropped_worth_showing:
        return placed_list

    # Index 0 is protected — same as _move_non_live_to_fillers — since it may
    # hold the favorite team's game when favorite_team_first is enabled, and
    # that should never be displaced regardless of its state.
    final_normal_idxs = [
        i for i, (g, pos) in enumerate(zip(placed_list, positions))
        if i != 0 and pos[0] == 'normal' and _overflow_priority(g) == 2
    ]
    for dg in dropped_worth_showing:
        if not final_normal_idxs:
            break
        placed_list[final_normal_idxs.pop(0)] = dg
    return placed_list


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

    # Hide finished and not-yet-started games so their slots free up for the
    # remaining live games to expand into wide/triple tiles. Only applies
    # while at least one game is actually live — otherwise there's nothing
    # for the freed slots to expand into. The pinned favorite-team game
    # (index 0) is exempt so it stays visible regardless of its state.
    if _hide_non_live_games_enabled(config):
        _live_exists_for_hide = any(g.get('detailed_state') in _LIVE_WIDE_STATES for g in game_list)
        if _live_exists_for_hide:
            _pinned_game = game_list[0] if (config.get('favorite_team_first', False) and game_list) else None
            _kept = [g for g in game_list if g is _pinned_game or g.get('detailed_state') not in _NON_LIVE_HIDE_STATES]
            if _kept:
                game_list = _kept

    # More games than the 15-slot grid can hold: games still In Progress must
    # not be bumped off (or drawn past the visible rows) in favor of games
    # that have already finished. Stable-sort everyone after the pinned slot
    # so live games sort first, Final games sort last, and every other state
    # (scheduled/warmup/postponed) keeps its original relative order between
    # them — only priority changes, not the underlying data.
    if len(game_list) > 15:
        _pinned = game_list[:1] if config.get('favorite_team_first', False) else []
        _rest = game_list[1:] if _pinned else game_list
        _rest = sorted(_rest, key=_overflow_priority)
        game_list = _pinned + _rest if _pinned else _rest

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

    # If live games exist and postponed/cancelled games are occupying slots that
    # prevent expansion (triple needs 2 free slots, wide needs 1), evict the
    # postponed games — they display no useful score — to make room.
    _live_exists = any(g.get('detailed_state') in _LIVE_WIDE_STATES for g in game_list)
    if _live_exists:
        _ppd_evictable = [g for g in reversed(game_list)
                          if g.get('detailed_state', '') in _RAINOUT_STATES]
        while _ppd_evictable and len(game_list) > 13:  # >13 means <2 free slots
            game_list.remove(_ppd_evictable.pop(0))

    # Determine which games get expanded tiles (triple or wide), then pack the
    # grid so normal games fill in around them with zero gaps.  Finally, move
    # non-live games into filler single-cell slots within expanded rows so a
    # live game never sits in a filler slot when a finished or not-yet-started
    # game can take it instead.
    _pre_pack_list = list(game_list)
    _tile_map = _find_tile_types(game_list, config, team_data)
    if _tile_map:
        game_list, _slots = _pack_grid(game_list, _tile_map)
        game_list = _move_non_live_to_fillers(game_list, _slots)
        game_list = _prioritize_live_over_final(_pre_pack_list, game_list, _slots)
    else:
        # No expansion — try clustering live games into the bottom row instead.
        # When 1-5 live games exist and everyone fits on the grid, group all of
        # them into the bottom row (rather than splitting some off into earlier
        # rows next to finished games), widening just enough to fill that row.
        _clustered_list, _clustered_slots = _cluster_live_games(game_list, config, team_data)
        if _clustered_slots is not None:  # pragma: no cover
            return _clustered_list, _clustered_slots
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


def _free_grid_slots(slots):
    """Return every free (col, row) slot-unit in the 5x3 grid, in slot order,
    given the already-occupied slots (wide=2, triple=3 horizontal units)."""
    occupied = set()
    for slot_type, col, row in slots:
        occupied.add((col, row))
        if slot_type in ('wide', 'triple'):
            occupied.add((col + 1, row))
        if slot_type == 'triple':
            occupied.add((col + 2, row))
    return [(_idx % 5, _idx // 5) for _idx in range(15) if (_idx % 5, _idx // 5) not in occupied]


# def _draw_config_qr_cell(Himage, sx, sy, url):
#     """Paste a QR code linking to the config web server into a normal
#     (150x150) grid cell at (sx, sy)."""
#     qr_img = qrcode.make(url).convert('1')
#     _pad = 8
#     _size = 150 - 2 * _pad
#     qr_img = qr_img.resize((_size, _size), Image.NEAREST)
#     Himage.paste(qr_img, (sx + _pad, sy + _pad))
#     return Himage


def draw_out_of_town_score_board(Himage, game_state_data, team_data, date_str=None, changed_game_ids=None, use_logos=False, logo_x_offset=2, show_win_prob=False, layout=None):
    """Render the full scoreboard grid of game boxes onto Himage."""

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

    # Accept a precomputed (game_list, slots) so callers that also need the
    # layout for partial-refresh region math (generate_image.py) can compute
    # it once and share it — two independent calls to compute_grid_layout
    # (even with "the same" inputs) can silently diverge if config.yaml is
    # edited mid-render (e.g. via the phone config server), since this
    # function reloads config from disk itself while a caller-supplied
    # layout was computed from whatever config snapshot it already had.
    if layout is not None:
        game_list, _slots = layout
    else:
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
        if slot_type == 'triple':
            Himage = draw_triple_box(
                Himage, sx, sy, game, team_data,
                score_changed=score_changed,
                use_logos=use_logos,
                logo_x_offset=logo_x_offset,
                show_win_prob=show_win_prob,
                streak_map=streak_map,
            )
        elif slot_type == 'wide':
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

    _free_slots = _free_grid_slots(_slots)

    # Free-slot panels, in priority order (first match claims the slot).
    # Trade deadline countdown is first — it's the most time-sensitive panel.
    # It only appears within the two weeks before the deadline, and disappears
    # automatically once the deadline passes.
    if config.get('show_deadline_panel', False) and _free_slots:
        from image_deadline import in_countdown_window as _dl_in_window
        if _dl_in_window(config=config):
            _dl_col, _dl_row = _free_slots.pop(0)
            _dl_data = load_json_file('transactions.json').get('transactions', [])
            _dl_lx = _dl_col * 150 + x_start
            _dl_ly = _dl_row * 150 + y_start
            Himage = draw_deadline_cell(Himage, _dl_lx, _dl_ly, _dl_data, team_data,
                                         use_logos=use_logos, config=config)

    # Transactions ticker.
    if config.get('show_transactions_ticker', False) and _free_slots:
        _tx_col, _tx_row = _free_slots.pop(0)
        _tx_data = load_json_file('transactions.json').get('transactions', [])
        _tx_lx = _tx_col * 150 + x_start
        _tx_ly = _tx_row * 150 + y_start
        Himage = draw_transactions_cell(
            Himage, _tx_lx, _tx_ly, _tx_data, team_data, use_logos=use_logos,
        )

    # Batting lineup panel — both teams' orders, shown within 30 min of first pitch.
    if config.get('show_lineup_panel', False) and _free_slots:
        _primary_abbr = config.get('primary', '')
        from image_lineup import _find_primary_game, game_within_minutes
        _lu_game = _find_primary_game(game_state_data, _primary_abbr)
        if _lu_game and game_within_minutes(_lu_game, minutes=45):
            _lu_col, _lu_row = _free_slots.pop(0)
            _lu_lx = _lu_col * 150 + x_start
            _lu_ly = _lu_row * 150 + y_start
            Himage = draw_lineup_cell(
                Himage, _lu_lx, _lu_ly, game_state_data, _primary_abbr, team_data, use_logos=use_logos,
            )

    # News headlines panel — team-scoped or league-wide.
    if config.get('show_news_panel', False) and _free_slots:
        _nx_col, _nx_row = _free_slots.pop(0)
        _nx_data = load_json_file('news.json')
        _nx_lx = _nx_col * 150 + x_start
        _nx_ly = _nx_row * 150 + y_start
        Himage = draw_news_cell(Himage, _nx_lx, _nx_ly, _nx_data, team_data, use_logos=use_logos)

    # Magic / elimination numbers for the primary team's division.
    if config.get('show_magic_numbers', False) and _free_slots:
        _mn_col, _mn_row = _free_slots.pop(0)
        _mn_standings = load_json_file('standings.json')
        _mn_lx = _mn_col * 150 + x_start
        _mn_ly = _mn_row * 150 + y_start
        _primary_abbr = config.get('primary', '')
        Himage = draw_magic_cell(
            Himage, _mn_lx, _mn_ly, _mn_standings, team_data,
            primary_abbr=_primary_abbr, use_logos=use_logos,
        )

    # Hot Hitters panel (14-day rolling batting avg).
    if config.get('show_streaks_panel', False) and _free_slots:
        _sk_col, _sk_row = _free_slots.pop(0)
        _sk_data = load_json_file('streaks.json')
        _sk_lx = _sk_col * 150 + x_start
        _sk_ly = _sk_row * 150 + y_start
        Himage = draw_streaks_cell(Himage, _sk_lx, _sk_ly, _sk_data, team_data, use_logos=use_logos)

    # Hot Arms panel (14-day rolling ERA, sorted ascending).
    if config.get('show_scoreless_panel', False) and _free_slots:
        _sc_col, _sc_row = _free_slots.pop(0)
        _sc_data = load_json_file('streaks.json')
        _sc_lx = _sc_col * 150 + x_start
        _sc_ly = _sc_row * 150 + y_start
        Himage = draw_scoreless_cell(Himage, _sc_lx, _sc_ly, _sc_data, team_data, use_logos=use_logos)

    if config.get('show_leaders_panel', False) and _free_slots:
        _leaders_data = load_json_file('leaders.json').get('leaders', {})
        _rotation_min = config.get('leaders_rotation_minutes', 5)
        # One tile per category when there's room for all of them; with
        # fewer free slots than categories, the subset shown slides over
        # time (via rotating_categories) so every category still appears.
        _n = min(len(_free_slots), len(_LEADER_CATEGORIES))
        _cats = (
            list(_LEADER_CATEGORIES) if _n == len(_LEADER_CATEGORIES)
            else rotating_categories(_n, _rotation_min)
        )
        for (_col, _row), _cat in zip(_free_slots, _cats):
            _lx = _col * 150 + x_start
            _ly = _row * 150 + y_start
            Himage = draw_leaders_cell(
                Himage, _lx, _ly, _leaders_data, team_data,
                category=_cat,
                use_logos=use_logos,
            )

    Himage.save('score_board.bmp')
    return Himage
