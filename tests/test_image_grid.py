"""Tests for src/image_grid.py helpers that don't require PIL or network access.

The QR-code-specific tests (for the commented-out _get_lan_ip and
_draw_config_qr_cell) remain in test_image_grid_qr.py (fully skipped).
This file covers the still-active helpers.
"""
import pytest

from image_grid import _free_grid_slot, compute_grid_layout, _find_wide_games, _move_non_live_to_fillers


# ---------------------------------------------------------------------------
# _free_grid_slot
# ---------------------------------------------------------------------------

class TestFreeGridSlot:
    def test_empty_grid_returns_first_slot(self):
        """Empty grid returns first slot."""
        assert _free_grid_slot([]) == (0, 0)

    def test_skips_occupied_normal_cells(self):
        """Skips occupied normal cells."""
        slots = [('normal', 0, 0), ('normal', 1, 0), ('normal', 2, 0)]
        assert _free_grid_slot(slots) == (3, 0)

    def test_accounts_for_wide_cell_consuming_two_columns(self):
        """Accounts for wide cell consuming two columns."""
        # A wide cell at col=0 occupies both col=0 and col=1 of row 0.
        slots = [('wide', 0, 0)]
        assert _free_grid_slot(slots) == (2, 0)

    def test_returns_none_when_full_grid(self):
        """Returns none when full grid."""
        slots = [('normal', i % 5, i // 5) for i in range(15)]
        assert _free_grid_slot(slots) is None

    def test_wraps_to_second_row(self):
        """Wraps to second row."""
        slots = [('normal', c, 0) for c in range(5)]
        assert _free_grid_slot(slots) == (0, 1)

    def test_wide_cell_at_col3_blocks_col4_too(self):
        """Wide cell at col3 blocks col4 too."""
        slots = [('normal', 0, 0), ('normal', 1, 0), ('normal', 2, 0),
                 ('wide', 3, 0)]   # occupies col 3 and 4
        assert _free_grid_slot(slots) == (0, 1)


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

    def test_live_game_gets_wide_slot_when_room(self):
        """Live game gets wide slot when room."""
        games = [_game(0, state='In Progress')] + [_game(i) for i in range(1, 5)]
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        wide_count = sum(1 for s in slots if s[0] == 'wide')
        assert wide_count == 1

    def test_no_wide_slot_at_15_games_without_always_flag(self):
        """No wide slot at 15 games without always flag."""
        games = [_game(0, state='In Progress')] + [_game(i) for i in range(1, 15)]
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        assert all(s[0] == 'normal' for s in slots)

    def test_wide_cell_always_forces_wide_at_15_games(self):
        """Wide cell always forces wide at 15 games."""
        cfg = dict(BASE_CONFIG, wide_cell_always=True)
        games = [_game(0, state='In Progress')] + [_game(i) for i in range(1, 15)]
        ordered, slots = compute_grid_layout(games, TEAM_DATA, cfg)
        wide_count = sum(1 for s in slots if s[0] == 'wide')
        assert wide_count == 1

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

    def test_live_games_all_cluster_into_one_bottom_row(self):
        """Live games all cluster into one bottom row."""
        # 13 games, 3 live spread among finals → all 3 must land together in
        # the same (bottom) row, widening exactly enough (2) to fill it
        # (2+2+1=5) rather than leaving one live game behind as a filler
        # among earlier finished games.
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
        live_rows = {row for (g, (stype, col, row)) in zip(ordered, slots)
                     if g.get('detailed_state') == 'In Progress'}
        assert len(live_rows) == 1, f"Live games split across rows: {live_rows}"
        wide_count = sum(1 for s in slots if s[0] == 'wide')
        assert wide_count == 2

    def test_four_live_games_cluster_with_one_wide_to_fit_row(self):
        """Four live games cluster with one wide to fit row."""
        # 11 games, 4 live spaced with a normal between pairs. Widening all 4
        # would take 8 units — more than one row holds — so only 1 (farthest
        # along) is widened, filling the row exactly (2+1+1+1=5) with every
        # live game grouped together in it.
        games = (
            [_game(0, state='In Progress'), _game(1, state='In Progress')]
            + [_game(2)]
            + [_game(3, state='In Progress'), _game(4, state='In Progress')]
            + [_game(i + 10) for i in range(6)]
        )
        assert len(games) == 11
        ordered, slots = compute_grid_layout(games, TEAM_DATA, BASE_CONFIG)
        live_rows = {row for (g, (stype, col, row)) in zip(ordered, slots)
                     if g.get('detailed_state') == 'In Progress'}
        assert len(live_rows) == 1, f"Live games split across rows: {live_rows}"
        wide_count = sum(1 for s in slots if s[0] == 'wide')
        assert wide_count == 1

    def test_filler_swap_leaves_all_games_rendered(self):
        """Filler swap leaves all games rendered."""
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
