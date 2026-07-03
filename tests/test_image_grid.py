"""Tests for src/image_grid.py helpers that don't require PIL or network access.

The QR-code-specific tests (for the commented-out _get_lan_ip and
_draw_config_qr_cell) remain in test_image_grid_qr.py (fully skipped).
This file covers the still-active helpers.
"""
import pytest

from image_grid import _free_grid_slot, compute_grid_layout, _find_wide_games, _reorder_for_wide, _move_non_live_to_fillers


# ---------------------------------------------------------------------------
# _free_grid_slot
# ---------------------------------------------------------------------------

class TestFreeGridSlot:
    def test_empty_grid_returns_first_slot(self):
        assert _free_grid_slot([]) == (0, 0)

    def test_skips_occupied_normal_cells(self):
        slots = [('normal', 0, 0), ('normal', 1, 0), ('normal', 2, 0)]
        assert _free_grid_slot(slots) == (3, 0)

    def test_accounts_for_wide_cell_consuming_two_columns(self):
        # A wide cell at col=0 occupies both col=0 and col=1 of row 0.
        slots = [('wide', 0, 0)]
        assert _free_grid_slot(slots) == (2, 0)

    def test_returns_none_when_full_grid(self):
        slots = [('normal', i % 5, i // 5) for i in range(15)]
        assert _free_grid_slot(slots) is None

    def test_wraps_to_second_row(self):
        slots = [('normal', c, 0) for c in range(5)]
        assert _free_grid_slot(slots) == (0, 1)

    def test_wide_cell_at_col3_blocks_col4_too(self):
        slots = [('normal', 0, 0), ('normal', 1, 0), ('normal', 2, 0),
                 ('wide', 3, 0)]   # occupies col 3 and 4
        assert _free_grid_slot(slots) == (0, 1)


# ---------------------------------------------------------------------------
# _reorder_for_wide
# ---------------------------------------------------------------------------

class TestReorderForWide:
    def _games(self, n):
        return [{'game_pk': i} for i in range(n)]

    def test_no_wide_games_returns_unchanged(self):
        games = self._games(5)
        new_games, new_wide = _reorder_for_wide(games, set())
        assert [g['game_pk'] for g in new_games] == list(range(5))
        assert new_wide == set()

    def test_wide_game_at_col4_swaps_with_next(self):
        # 5 games → slots 0-4; game at index 4 would be col=4; swap with next
        games = self._games(6)  # 6 games; game[4] lands at col=4, swap with game[5]
        wide_set = {4}
        new_games, new_wide = _reorder_for_wide(games, wide_set)
        # game[4] and game[5] should have been swapped
        assert new_games[4]['game_pk'] == 5
        assert new_games[5]['game_pk'] == 4
        assert 5 in new_wide

    def test_wide_game_not_at_col4_unchanged(self):
        games = self._games(5)
        wide_set = {0}  # col=0 — no conflict
        new_games, new_wide = _reorder_for_wide(games, wide_set)
        assert [g['game_pk'] for g in new_games] == list(range(5))
        assert new_wide == {0}

    def test_conflict_with_another_wide_drops_the_conflicting_game(self):
        # Two consecutive wide games starting at col=3 (wide at 3, wide at 5?)
        # Actually: index 4 is col=4. If the next game is also wide, can't swap → drop.
        games = self._games(6)
        wide_set = {4, 5}
        new_games, new_wide = _reorder_for_wide(games, wide_set)
        # The one at col=4 should have been dropped from wide_set
        assert len(new_wide) <= 1


# ---------------------------------------------------------------------------
# compute_grid_layout
# ---------------------------------------------------------------------------

def _game(pk, state='Scheduled', inning=1, inning_state='Top', outs=0, dh='N'):
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
        games = [_game(i) for i in range(5)]
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        assert all(s[0] == 'normal' for s in slots)

    def test_live_game_gets_wide_slot_when_room(self):
        games = [_game(0, state='In Progress')] + [_game(i) for i in range(1, 5)]
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        wide_count = sum(1 for s in slots if s[0] == 'wide')
        assert wide_count == 1

    def test_no_wide_slot_at_15_games_without_always_flag(self):
        games = [_game(0, state='In Progress')] + [_game(i) for i in range(1, 15)]
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        assert all(s[0] == 'normal' for s in slots)

    def test_wide_cell_always_forces_wide_at_15_games(self):
        cfg = dict(BASE_CONFIG, wide_cell_always=True)
        games = [_game(0, state='In Progress')] + [_game(i) for i in range(1, 15)]
        ordered, slots = compute_grid_layout(games, TEAM_DATA, cfg)
        wide_count = sum(1 for s in slots if s[0] == 'wide')
        assert wide_count == 1

    def test_postponed_pushed_to_back_with_dh_and_16_games(self):
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
        cfg = dict(BASE_CONFIG, favorite_team_first=True, primary='NYY')
        games = [_game(0), _game(1), _game(2, state='In Progress')]
        # Move team 147 (NYY) game to position 2 to verify it gets moved to front
        ordered, slots = compute_grid_layout(games, TEAM_DATA, cfg)
        # First game should be one with NYY (away_team_id=147)
        assert ordered[0]['away_team_id'] == 147

    def test_wide_slot_count_capped_at_15_in_wide_path(self):
        # With a live game the wide-cell loop stops at 15 slot units.
        cfg = dict(BASE_CONFIG, wide_cell_always=True)
        games = [_game(0, state='In Progress')] + [_game(i + 1) for i in range(19)]
        ordered, slots = compute_grid_layout(games, TEAM_DATA, cfg)
        assert len(slots) <= 15

    # ------------------------------------------------------------------
    # _move_non_live_to_fillers: filler slots in wide rows must be non-live
    # ------------------------------------------------------------------

    def test_all_games_always_rendered(self):
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

    def test_filler_slot_in_wide_row_is_non_live(self):
        # 13 games, 3 live → budget=2, 2 wide per row leaves 1 filler each.
        # The filler must not be a live game.
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
        wide_rows = {row for (stype, col, row) in slots if stype == 'wide'}
        for i, (stype, col, row) in enumerate(slots):
            if stype == 'normal' and row in wide_rows:
                assert ordered[i].get('detailed_state') not in ('In Progress', 'Player challenge', 'Manager challenge'), \
                    f"Live game found in filler slot at row {row}, col {col}"

    def test_four_live_games_all_wide_when_spaced_with_normal(self):
        # 11 games, 4 live spaced with a normal between pairs so no col=4 conflict.
        # budget=4, all 4 live can be wide, no filler-swap needed.
        games = (
            [_game(0, state='In Progress'), _game(1, state='In Progress')]
            + [_game(2)]
            + [_game(3, state='In Progress'), _game(4, state='In Progress')]
            + [_game(i + 10) for i in range(6)]
        )
        assert len(games) == 11
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        wide_count = sum(1 for s in slots if s[0] == 'wide')
        assert wide_count == 4

    def test_filler_swap_leaves_all_games_rendered(self):
        # Even after filler swaps, total rendered count must equal total games.
        live = [_game(i, state='In Progress') for i in range(3)]
        normals = [_game(i + 10) for i in range(10)]
        games = live + normals
        assert len(games) == 13
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        assert len(ordered) == len(slots)


# ---------------------------------------------------------------------------
# _move_non_live_to_fillers (unit tests for the helper directly)
# ---------------------------------------------------------------------------

class TestMoveNonLiveToFillers:
    _LIVE = 'In Progress'
    _DONE = 'Final'
    _SCHED = 'Scheduled'

    def _g(self, pk, state='Scheduled'):
        return {'game_pk': pk, 'detailed_state': state}

    def test_live_in_only_filler_slot_gets_swapped(self):
        # Two wide games at indices 0,1 leave a filler at index 2 (col=4, row=0).
        # If index 2 is live it should be swapped with a non-live game from row 1+.
        games = [
            self._g(0, self._LIVE),   # wide → col 0-1
            self._g(1, self._LIVE),   # wide → col 2-3
            self._g(2, self._LIVE),   # filler at col 4, row 0 — should be moved out
            self._g(3, self._SCHED),  # row 1, col 0 — candidate for swap
            self._g(4, self._SCHED),
        ]
        result = _move_non_live_to_fillers(games, {0, 1})
        filler_game = result[2]
        assert filler_game['detailed_state'] != self._LIVE

    def test_non_live_in_filler_unchanged(self):
        # Filler already holds a non-live game — no swap needed.
        games = [
            self._g(0, self._LIVE),
            self._g(1, self._LIVE),
            self._g(2, self._DONE),  # filler already non-live
            self._g(3, self._SCHED),
            self._g(4, self._SCHED),
        ]
        original = [g['game_pk'] for g in games]
        result = _move_non_live_to_fillers(games, {0, 1})
        assert [g['game_pk'] for g in result] == original

    def test_no_wide_games_no_change(self):
        games = [self._g(i, self._SCHED) for i in range(5)]
        result = _move_non_live_to_fillers(games, set())
        assert [g['game_pk'] for g in result] == list(range(5))

    def test_all_games_preserved(self):
        # Swaps may reorder but must not drop any game.
        games = [
            self._g(0, self._LIVE),
            self._g(1, self._LIVE),
            self._g(2, self._LIVE),  # filler
            self._g(3, self._SCHED),
            self._g(4, self._DONE),
        ]
        result = _move_non_live_to_fillers(games, {0, 1})
        assert {g['game_pk'] for g in result} == {0, 1, 2, 3, 4}

    def test_index_zero_never_displaced_to_filler(self):
        # Game at index 0 (featured team position) must never be swapped into
        # a filler slot, even if it is the only non-live candidate available.
        games = [
            self._g(0, self._SCHED),  # featured team at position 0 — must stay
            self._g(1, self._LIVE),   # wide
            self._g(2, self._LIVE),   # wide
            self._g(3, self._LIVE),   # filler at col=4 — needs a non-live swap
            # No other non-live games available except index 0
        ]
        result = _move_non_live_to_fillers(games, {1, 2})
        assert result[0]['game_pk'] == 0  # featured game stays first
