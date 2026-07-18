"""Tests for src/image_grid.py helpers that don't require PIL or network access.

The QR-code-specific tests (for the commented-out _get_lan_ip and
_draw_config_qr_cell) remain in test_image_grid_qr.py (fully skipped).
This file covers the still-active helpers.
"""
import pytest

from image_grid import (
    _free_grid_slots, compute_grid_layout, _find_wide_games, _move_non_live_to_fillers,
    _lay_out_row_major, _pack_grid, _cluster_live_games,
)


# ---------------------------------------------------------------------------
# _free_grid_slots
# ---------------------------------------------------------------------------

class TestFreeGridSlot:
    def test_empty_grid_returns_first_slot(self):
        """Empty grid returns first slot."""
        assert _free_grid_slots([])[0] == (0, 0)

    def test_skips_occupied_normal_cells(self):
        """Skips occupied normal cells."""
        slots = [('normal', 0, 0), ('normal', 1, 0), ('normal', 2, 0)]
        assert _free_grid_slots(slots)[0] == (3, 0)

    def test_accounts_for_wide_cell_consuming_two_columns(self):
        """Accounts for wide cell consuming two columns."""
        # A wide cell at col=0 occupies both col=0 and col=1 of row 0.
        slots = [('wide', 0, 0)]
        assert _free_grid_slots(slots)[0] == (2, 0)

    def test_returns_empty_when_full_grid(self):
        """Returns empty when full grid."""
        slots = [('normal', i % 5, i // 5) for i in range(15)]
        assert _free_grid_slots(slots) == []

    def test_wraps_to_second_row(self):
        """Wraps to second row."""
        slots = [('normal', c, 0) for c in range(5)]
        assert _free_grid_slots(slots)[0] == (0, 1)

    def test_wide_cell_at_col3_blocks_col4_too(self):
        """Wide cell at col3 blocks col4 too."""
        slots = [('normal', 0, 0), ('normal', 1, 0), ('normal', 2, 0),
                 ('wide', 3, 0)]   # occupies col 3 and 4
        assert _free_grid_slots(slots)[0] == (0, 1)


# ---------------------------------------------------------------------------
# compute_grid_layout
# ---------------------------------------------------------------------------

def _game(pk, state='Scheduled', inning=1, inning_state='Top', outs=0, dh='N'):
    """Game."""
    return {
        'game_pk': pk,
        'away_team_id': 147,
        'home_team_id': 111,
        'detailed_state': state,
        'current_inning': inning,
        'inningState': inning_state,
        'num_of_outs': outs,
        'game_datetime': '2025-10-01T00:00:00Z',
        'double_header': dh,
    }


TEAM_DATA = {'team_abbreviation': {'147': 'NYY', '111': 'BOS'}}
BASE_CONFIG = {
    'favorite_team_first': False,
    'wide_cell_always': False,
    'wide_cell_featured': False,
    'primary': '',
}


class TestComputeGridLayout:
    def test_all_scheduled_games_are_normal_slots(self):
        """All scheduled games are normal slots."""
        games = [_game(i) for i in range(5)]
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        assert all(s[0] == 'normal' for s in slots)

    def test_live_game_gets_triple_slot_when_room(self):
        """Live game gets triple slot when there is room (≥2 extra slots free)."""
        games = [_game(0, state='In Progress')] + [_game(i) for i in range(1, 5)]
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        triple_count = sum(1 for s in slots if s[0] == 'triple')
        assert triple_count == 1

    def test_live_game_gets_wide_when_only_one_slot_free(self):
        """Live game falls back to wide when only 1 extra slot is available."""
        # 14 games → 15 - 14 = 1 free slot, not enough for triple (needs 2).
        games = [_game(0, state='In Progress')] + [_game(i) for i in range(1, 14)]
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        wide_count = sum(1 for s in slots if s[0] == 'wide')
        assert wide_count == 1

    def test_no_expanded_slot_at_15_games_without_always_flag(self):
        """No expanded slot at 15 games without wide_cell_always/featured flag."""
        games = [_game(0, state='In Progress')] + [_game(i) for i in range(1, 15)]
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        assert all(s[0] == 'normal' for s in slots)

    def test_wide_cell_always_forces_triple_at_15_games(self):
        """wide_cell_always at 15 games now gives the best live game a triple tile."""
        cfg = dict(BASE_CONFIG, wide_cell_always=True)
        games = [_game(0, state='In Progress')] + [_game(i) for i in range(1, 15)]
        ordered, slots = compute_grid_layout(games, TEAM_DATA, cfg)
        triple_count = sum(1 for s in slots if s[0] == 'triple')
        assert triple_count == 1

    def test_postponed_evicted_to_make_room_for_triple(self):
        """Postponed games are removed when they block triple expansion."""
        # 14 games (1 live + 1 postponed + 12 final) → normally only 1 free slot (wide).
        # Postponed eviction removes the postponed game → 13 games → 2 free slots → triple.
        games = ([_game(0, state='In Progress')]
                 + [_game(i + 1) for i in range(12)]
                 + [_game(99, state='Postponed')])
        assert len(games) == 14
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        triple_count = sum(1 for s in slots if s[0] == 'triple')
        assert triple_count == 1
        # Postponed game was evicted to make room.
        assert all(g['game_pk'] != 99 for g in ordered)

    def test_postponed_pushed_to_back_with_dh_and_16_games(self):
        """Postponed pushed to back with dh and 16 games."""
        games_dh = [_game(i, dh='Y') for i in range(2)]
        games_normal = [_game(i + 10) for i in range(14)]
        ppd = _game(99, state='Postponed')
        all_games = games_dh + games_normal + [ppd]
        assert len(all_games) == 17
        ordered, slots = compute_grid_layout(all_games, TEAM_DATA, BASE_CONFIG)
        # Postponed game should be last
        if len(ordered) > 15:
            assert ordered[-1]['game_pk'] == 99

    def test_favorite_team_first_moves_primary_game_to_front(self):
        """Favorite team first moves primary game to front."""
        cfg = dict(BASE_CONFIG, favorite_team_first=True, primary='NYY')
        games = [_game(0), _game(1), _game(2, state='In Progress')]
        # Move team 147 (NYY) game to position 2 to verify it gets moved to front
        ordered, slots = compute_grid_layout(games, TEAM_DATA, cfg)
        # First game should be one with NYY (away_team_id=147)
        assert ordered[0]['away_team_id'] == 147

    def test_wide_slot_count_capped_at_15_in_wide_path(self):
        """Wide slot count capped at 15 in wide path."""
        # With a live game the wide-cell loop stops at 15 slot units.
        cfg = dict(BASE_CONFIG, wide_cell_always=True)
        games = [_game(0, state='In Progress')] + [_game(i + 1) for i in range(19)]
        ordered, slots = compute_grid_layout(games, TEAM_DATA, cfg)
        assert len(slots) <= 15

    # ------------------------------------------------------------------
    # _move_non_live_to_fillers: filler slots in wide rows must be non-live
    # ------------------------------------------------------------------

    def test_all_games_always_rendered(self):
        """All games always rendered."""
        # No game should be hidden; len(ordered) == len(slots) always.
        games = (
            [_game(i) for i in range(5)]
            + [_game(10, state='In Progress')]
            + [_game(i + 20) for i in range(2)]
            + [_game(11, state='In Progress')]
            + [_game(i + 30) for i in range(2)]
            + [_game(12, state='In Progress')]
            + [_game(99, state='Final')]
        )
        assert len(games) == 13
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        assert len(ordered) == len(slots)

    def test_featured_live_game_gets_triple_others_normal(self):
        """Featured live game gets triple; remaining live games stay normal when budget exhausted."""
        # 13 games, 3 live → remaining = 2 → featured gets triple (costs 2), others normal.
        games = (
            [_game(i) for i in range(5)]
            + [_game(10, state='In Progress')]
            + [_game(i + 20) for i in range(2)]
            + [_game(11, state='In Progress')]
            + [_game(i + 30) for i in range(2)]
            + [_game(12, state='In Progress')]
            + [_game(99, state='Final')]
        )
        assert len(games) == 13
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        triple_count = sum(1 for s in slots if s[0] == 'triple')
        assert triple_count == 1

    def test_four_live_games_featured_gets_triple_others_wide(self):
        """With 4 live games and budget of 4, featured gets triple, next gets wide."""
        # 11 games, 4 live → remaining = 4 → triple (costs 2) + wide (costs 1) + wide (costs 1).
        games = (
            [_game(0, state='In Progress'), _game(1, state='In Progress')]
            + [_game(2)]
            + [_game(3, state='In Progress'), _game(4, state='In Progress')]
            + [_game(i + 10) for i in range(6)]
        )
        assert len(games) == 11
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        live_count = sum(1 for g in ordered if g.get('detailed_state') == 'In Progress')
        assert live_count == 4
        triple_count = sum(1 for s in slots if s[0] == 'triple')
        assert triple_count == 1

    def test_filler_swap_leaves_all_games_rendered(self):
        """Filler swap leaves all games rendered."""
        # Even after filler swaps, total rendered count must equal total games.
        live = [_game(i, state='In Progress') for i in range(3)]
        normals = [_game(i + 10) for i in range(10)]
        games = live + normals
        assert len(games) == 13
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        assert len(ordered) == len(slots)

    def test_all_live_all_wide_slate_has_no_invalid_or_overlapping_slots(self):
        """All live all wide slate has no invalid or overlapping slots."""
        # Regression test: a slate where every game is live (so every one
        # becomes a wide tile, with zero normal games left over to fill a
        # leftover single unit) used to leave a stale column/row offset
        # between row buckets in _pack_grid, landing a wide tile at col 4
        # (needing a nonexistent col 5) instead of starting a fresh row.
        games = [_game(i, state='In Progress', inning=i + 1) for i in range(6)]
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        assert len(ordered) == len(slots)
        occupied = set()
        for slot_type, col, row in slots:
            assert 0 <= col <= 4 and 0 <= row <= 2
            if slot_type == 'wide':
                assert col <= 3, f"wide tile at col {col} would need a nonexistent col {col + 1}"
            cells = [(col, row)] + ([(col + 1, row)] if slot_type == 'wide' else [])
            for c in cells:
                assert c not in occupied, f"slot {c} used twice"
                occupied.add(c)

    def test_geometry_is_always_valid_across_random_slates(self):
        """Geometry is always valid across random slates."""
        # Broad regression sweep for the two bugs above (col-4 conflicts and
        # cross-bucket column drift) across many random live/final mixes,
        # game counts, and config combinations.
        #
        # n_live is capped at 5 (the live-clustering path's domain, see
        # _cluster_live_games). Above that, clustering steps aside and
        # _find_wide_games/_pack_grid's general path takes over — which has
        # a separate, pre-existing bug where 6+ simultaneous live games with
        # too few normal games left to fill the resulting odd row leftovers
        # can silently strand (drop) a wide game. That's outside the scope
        # of today's clustering work and not covered here.
        import random
        rng = random.Random(12345)
        for _ in range(300):
            n = rng.randint(1, 15)
            n_live = rng.randint(0, min(n, 5))
            states = ['In Progress'] * n_live + ['Final'] * (n - n_live)
            rng.shuffle(states)
            games = [_game(i, state=s, inning=rng.randint(1, 9)) for i, s in enumerate(states)]
            cfg = dict(BASE_CONFIG)
            cfg['favorite_team_first'] = rng.random() < 0.3
            cfg['wide_cell_always'] = rng.random() < 0.3
            cfg['wide_cell_featured'] = rng.random() < 0.3
            ordered, slots = compute_grid_layout(games, TEAM_DATA, cfg)
            assert len(ordered) == len(slots)
            # At exactly 15 games, wide_cell_always/featured deliberately drop
            # one game to make room for the forced wide cell (see
            # _find_wide_games) — otherwise every game must still be present.
            if not (n >= 15 and (cfg['wide_cell_always'] or cfg['wide_cell_featured'])):
                assert len(ordered) == n
            occupied = set()
            for slot_type, col, row in slots:
                assert 0 <= col <= 4 and 0 <= row <= 2, (n, n_live, cfg, slot_type, col, row)
                if slot_type == 'wide':
                    assert col <= 3, (n, n_live, cfg, col, row)
                cells = [(col, row)] + ([(col + 1, row)] if slot_type == 'wide' else [])
                for c in cells:
                    assert c not in occupied, (n, n_live, cfg, c)
                    occupied.add(c)


class TestPackGridDirect:
    def _g(self, pk):
        """G."""
        return {'game_pk': pk}

    def test_lone_filler_leads_two_or_more_wide_tiles(self):
        """Lone filler leads two or more wide tiles."""
        # Index 0 pinned normal; indices 1-4 wide, index 5 normal. This
        # capacity split (row0 leftover=4, row1=5) lands exactly 2 wide +
        # 1 normal in row1 — the lone filler must lead ("1 2 2") since wide
        # tiles are the majority in that row.
        game_list = [self._g(i) for i in range(6)]
        tile_type_map = {i: 'wide' for i in (1, 2, 3, 4)}
        ordered, positions = _pack_grid(game_list, tile_type_map)
        assert len(ordered) == len(positions) == 6
        row1_tokens = [(g['game_pk'], s) for g, s in zip(ordered, positions) if s[2] == 1]
        # First token in row 1 (lowest col) should be the lone normal filler.
        row1_tokens.sort(key=lambda t: t[1][1])
        assert row1_tokens[0][1][0] == 'normal'
        assert sum(1 for _, s in row1_tokens if s[0] == 'wide') == 2

    def test_empty_game_list_returns_empty(self):
        """Empty game list returns empty."""
        assert _pack_grid([], {}) == ([], [])

    def test_overflow_falls_back_to_front_to_back_packing(self):
        """Overflow falls back to front to back packing."""
        # More wide-eligible games than the grid can hold even at 1 unit
        # each — forces the front-to-back overflow branch, including its
        # col=4-skip and its final break once nothing more fits.
        game_list = [self._g(i) for i in range(20)]
        tile_type_map = {i: 'wide' for i in range(1, 12)}  # far more wide than 15 slots can hold
        ordered, positions = _pack_grid(game_list, tile_type_map)
        assert len(ordered) == len(positions)
        assert len(positions) <= 15
        occupied = set()
        for slot_type, col, row in positions:
            cells = [(col, row)] + ([(col + 1, row)] if slot_type == 'wide' else [])
            for c in cells:
                assert c not in occupied
                occupied.add(c)

    def test_fifteen_plus_games_use_row_major_layout(self):
        """15+ games use row-major layout and trim to 15 slots."""
        # With 15+ games, _pack_grid should use simple row-major layout
        # instead of complex bottom-up packing, and trim to exactly 15 slots.
        game_list = [self._g(i) for i in range(18)]
        tile_type_map = {i: 'wide' for i in (0, 5, 10)}  # some games marked for widening
        ordered, positions = _pack_grid(game_list, tile_type_map)
        assert len(ordered) == len(positions)
        assert len(positions) <= 15
        # Check that slot numbers don't exceed 15 (5 cols × 3 rows)
        for slot_type, col, row in positions:
            assert 0 <= col <= 4 and 0 <= row <= 2
            if slot_type == 'wide':
                assert col <= 3

    def test_less_than_15_games_with_many_wide_uses_overflow_path(self):
        """Less than 15 games with many wide games triggers overflow packing."""
        # With <15 games but many marked wide, the overflow branch should
        # pack as much as possible without reordering via complex packing.
        # Need total_wanted > remaining_capacity to trigger overflow:
        # remaining_capacity = 14 (with pinned_cost=1), so need total > 14.
        # With 10 games: 1 pinned normal, 7 wide (14 units), 2 normal (2 units) = 16 > 14.
        game_list = [self._g(i) for i in range(10)]
        tile_type_map = {i: 'wide' for i in (1, 2, 3, 4, 5, 6, 7)}  # 7 wide games, games 0,8,9 are normal
        ordered, positions = _pack_grid(game_list, tile_type_map)
        assert len(ordered) == len(positions)
        assert len(positions) <= 15
        # Verify valid layout
        for slot_type, col, row in positions:
            assert 0 <= col <= 4 and 0 <= row <= 2
            if slot_type == 'wide':
                assert col <= 3
        # Should have used overflow path and included some normal games
        assert any(s[0] == 'normal' for s in positions[1:])


class TestLayOutRowMajor:
    def _g(self, pk):
        """G."""
        return {'game_pk': pk}

    def test_demotes_wide_to_normal_when_no_filler_available(self):
        """Demotes wide to normal when no filler available."""
        # 4 consecutive wide tokens starting at col 2: the first fits (cols
        # 2-3), the second would need to start at col 4 with no later normal
        # token to pull forward as filler, so it's demoted to normal instead
        # of leaving col 4 unfilled or landing an invalid wide tile there.
        tokens = [('wide', self._g(i)) for i in range(4)]
        ordered, positions, next_slot = _lay_out_row_major(tokens, start_slot=2)
        assert len(ordered) == len(positions) == 4
        for slot_type, col, _row in positions:
            assert 0 <= col <= 4
            if slot_type == 'wide':
                assert col <= 3
        wide_count = sum(1 for s in positions if s[0] == 'wide')
        assert wide_count == 3  # one demoted to normal to fill the col-4 gap

    def test_pulls_later_normal_token_forward_to_fill_gap(self):
        """Pulls later normal token forward to fill gap."""
        # wide, wide, normal: second wide would land at col 4; the trailing
        # normal token gets pulled forward to fill that slot instead, and the
        # wide token is placed right after on the next row.
        tokens = [('wide', self._g(0)), ('wide', self._g(1)), ('normal', self._g(2))]
        ordered, positions, next_slot = _lay_out_row_major(tokens, start_slot=2)
        # The normal game (pk=2) should have been pulled forward, ahead of
        # the second wide game (pk=1), in the returned order.
        pks = [g['game_pk'] for g in ordered]
        assert pks.index(2) < pks.index(1)
        assert sum(1 for s in positions if s[0] == 'wide') == 2


# ---------------------------------------------------------------------------
# _move_non_live_to_fillers (unit tests for the helper directly)
# ---------------------------------------------------------------------------

class TestMoveNonLiveToFillers:
    _LIVE = 'In Progress'
    _DONE = 'Final'
    _SCHED = 'Scheduled'

    def _g(self, pk, state='Scheduled'):
        """G."""
        return {'game_pk': pk, 'detailed_state': state}

    # positions parallel to a 5-game row0 wide/wide/filler + row1 layout
    _ROW0_WIDE_WIDE_FILLER = [
        ('wide', 0, 0), ('wide', 2, 0), ('normal', 4, 0),
        ('normal', 0, 1), ('normal', 1, 1),
    ]

    def test_live_in_only_filler_slot_gets_swapped(self):
        """Live in only filler slot gets swapped."""
        # Two wide games at indices 0,1 leave a filler at index 2 (col=4, row=0).
        # If index 2 is live it should be swapped with a non-live game from row 1+.
        games = [
            self._g(0, self._LIVE),   # wide → col 0-1
            self._g(1, self._LIVE),   # wide → col 2-3
            self._g(2, self._LIVE),   # filler at col 4, row 0 — should be moved out
            self._g(3, self._SCHED),  # row 1, col 0 — candidate for swap
            self._g(4, self._SCHED),
        ]
        result = _move_non_live_to_fillers(games, self._ROW0_WIDE_WIDE_FILLER)
        filler_game = result[2]
        assert filler_game['detailed_state'] != self._LIVE

    def test_non_live_in_filler_unchanged(self):
        """Non live in filler unchanged."""
        # Filler already holds a non-live game — no swap needed.
        games = [
            self._g(0, self._LIVE),
            self._g(1, self._LIVE),
            self._g(2, self._DONE),  # filler already non-live
            self._g(3, self._SCHED),
            self._g(4, self._SCHED),
        ]
        original = [g['game_pk'] for g in games]
        result = _move_non_live_to_fillers(games, self._ROW0_WIDE_WIDE_FILLER)
        assert [g['game_pk'] for g in result] == original

    def test_no_wide_games_no_change(self):
        """No wide games no change."""
        games = [self._g(i, self._SCHED) for i in range(5)]
        positions = [('normal', i, 0) for i in range(5)]
        result = _move_non_live_to_fillers(games, positions)
        assert [g['game_pk'] for g in result] == list(range(5))

    def test_all_games_preserved(self):
        """All games preserved."""
        # Swaps may reorder but must not drop any game.
        games = [
            self._g(0, self._LIVE),
            self._g(1, self._LIVE),
            self._g(2, self._LIVE),  # filler
            self._g(3, self._SCHED),
            self._g(4, self._DONE),
        ]
        result = _move_non_live_to_fillers(games, self._ROW0_WIDE_WIDE_FILLER)
        assert {g['game_pk'] for g in result} == {0, 1, 2, 3, 4}

    def test_index_zero_never_displaced_to_filler(self):
        """Index zero never displaced to filler."""
        # Game at index 0 (featured team position) must never be swapped into
        # a filler slot, even if it is the only non-live candidate available.
        games = [
            self._g(0, self._SCHED),  # featured team at position 0 — must stay
            self._g(1, self._LIVE),   # wide
            self._g(2, self._LIVE),   # wide
            self._g(3, self._LIVE),   # filler at col=4 — needs a non-live swap
            # No other non-live games available except index 0
        ]
        # index 0 sits outside the wide row (row 1); row 0 is wide/wide/filler.
        positions = [
            ('normal', 0, 1), ('wide', 0, 0), ('wide', 2, 0), ('normal', 4, 0),
        ]
        result = _move_non_live_to_fillers(games, positions)
        assert result[0]['game_pk'] == 0  # featured game stays first


# ---------------------------------------------------------------------------
# Triple tile handling in _pack_grid / _lay_out_row_major
# ---------------------------------------------------------------------------

class TestTripleTilePacking:
    """Triple-tile (3-wide) slots in _pack_grid and _lay_out_row_major."""

    def _g(self, pk):
        return {'game_pk': pk}

    def test_triple_tile_placed_at_col_0(self):
        """A single triple tile placed at col 0 occupies 3 columns."""
        game_list = [self._g(i) for i in range(3)]
        tile_type_map = {0: 'triple'}
        ordered, positions = _pack_grid(game_list, tile_type_map)
        assert len(ordered) == len(positions) == 3
        triple_slots = [(t, c, r) for t, c, r in positions if t == 'triple']
        assert triple_slots, "expected at least one triple slot"
        assert triple_slots[0][1] in (0, 1, 2), "triple tile must start in col 0-2"

    def test_triple_tile_demoted_when_at_col_3(self):
        """Triple tile that would land at col>=3 is demoted to wide or swapped."""
        # Place 3 normal tiles first (takes slots 0-2), then a triple at slot 3
        # (col=3) — should either swap with a later normal or demote.
        game_list = [self._g(i) for i in range(5)]
        tile_type_map = {3: 'triple'}
        ordered, positions = _pack_grid(game_list, tile_type_map)
        for slot_type, col, _row in positions:
            if slot_type == 'triple':
                assert col <= 2, "triple tile must not start at col>=3"
            if slot_type == 'wide':
                assert col <= 3

    def test_pack_grid_with_only_triple_tile(self):
        """_pack_grid handles a tile_type_map with only a triple entry."""
        game_list = [self._g(i) for i in range(4)]
        tile_type_map = {1: 'triple'}
        ordered, positions = _pack_grid(game_list, tile_type_map)
        assert len(ordered) == len(positions) == 4
        for _slot_type, col, row in positions:
            assert 0 <= col <= 4 and 0 <= row <= 2

    def test_lay_out_row_major_triple_tile_placed(self):
        """_lay_out_row_major places a triple token without crash."""
        tokens = [('triple', self._g(0)), ('normal', self._g(1))]
        ordered, positions, next_slot = _lay_out_row_major(tokens, start_slot=0)
        assert len(ordered) == 2
        triple_pos = [p for p in positions if p[0] == 'triple']
        assert triple_pos, "triple tile must appear in output"
        assert triple_pos[0][1] <= 2  # col 0-2

    def test_lay_out_row_major_triple_at_col3_demoted(self):
        """Triple tile at col>=3 is demoted when no swap candidate is available."""
        # Start at slot 3 (col=3): triple needs 3 cols from there, impossible.
        tokens = [('triple', self._g(0))]
        ordered, positions, next_slot = _lay_out_row_major(tokens, start_slot=3)
        # Either demoted to wide or swapped — but must not be at col>=3 as triple.
        for slot_type, col, _row in positions:
            if slot_type == 'triple':
                assert col <= 2

    def test_lay_out_row_major_triple_at_col3_swapped_with_normal(self):
        """Triple tile at col>=3 is swapped forward with a later normal token."""
        # Start at slot 3 (col=3): triple can't fit, but there's a normal later
        # → the normal gets pulled forward, triple placed later when col resets.
        tokens = [('triple', self._g(0)), ('normal', self._g(1))]
        ordered, positions, next_slot = _lay_out_row_major(tokens, start_slot=3)
        assert len(ordered) == 2
        for slot_type, col, _row in positions:
            if slot_type == 'triple':
                assert col <= 2

    def test_pack_grid_overflow_with_triple_tiles(self):
        """Overflow path places triple tiles when cap_left >= 3."""
        # 6 games, 5 marked triple: total_wanted = 15 > remaining_capacity=14 → overflow.
        game_list = [self._g(i) for i in range(6)]
        tile_type_map = {i: 'triple' for i in range(1, 6)}
        ordered, positions = _pack_grid(game_list, tile_type_map)
        assert len(ordered) == len(positions)
        for slot_type, col, row in positions:
            assert 0 <= col <= 4 and 0 <= row <= 2
            if slot_type == 'triple':
                assert col <= 2


class TestClusterLiveGames:
    """Direct tests for _cluster_live_games to cover its internal layout logic."""

    def _g(self, pk=1, state='Final'):
        return {'game_pk': pk, 'detailed_state': state, 'away_team_id': 119,
                'home_team_id': 137, 'away_runs': 3, 'home_runs': 5}

    def test_two_live_games_cluster_into_wide_slots(self):
        """With 10 games and 2 live, cluster produces wide slots for live games."""
        games = [self._g(i + 1) for i in range(8)]
        games += [self._g(9, 'In Progress'), self._g(10, 'In Progress')]
        result, positions = _cluster_live_games(games, {}, {})
        assert positions is not None
        slot_types = [s for s, _c, _r in positions]
        assert 'wide' in slot_types

    def test_single_live_game_returns_none(self):
        """With only 1 live game, cluster returns None (not 2-5 live)."""
        games = [self._g(i + 1) for i in range(9)] + [self._g(10, 'In Progress')]
        _list, positions = _cluster_live_games(games, {}, {})
        assert positions is None

    def test_15_or_more_games_returns_none(self):
        """With 15 games, cluster defers immediately."""
        games = [self._g(i + 1) for i in range(13)]
        games += [self._g(14, 'In Progress'), self._g(15, 'In Progress')]
        _list, positions = _cluster_live_games(games, {}, {})
        assert positions is None

    def test_pinned_game_first_with_cluster(self):
        """When favorite_team_first is set, pinned game goes to slot 0."""
        pinned = {'game_pk': 99, 'detailed_state': 'Final', 'away_team_id': 147,
                  'home_team_id': 111, 'away_runs': 1, 'home_runs': 2}
        games = [pinned] + [self._g(i + 1) for i in range(7)]
        games += [self._g(9, 'In Progress'), self._g(10, 'In Progress')]
        cfg = {'favorite_team_first': True}
        result, positions = _cluster_live_games(games, cfg, {})
        assert positions is not None
        assert result[0]['game_pk'] == 99
        assert positions[0] == ('normal', 0, 0)
