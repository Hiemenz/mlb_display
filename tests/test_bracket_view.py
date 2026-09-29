"""Tests for bracket_view — the full-screen postseason tree.

Logos are patched off (pic/logos is gitignored; the real loader would download).
"""
from unittest.mock import patch

import pytest
from PIL import Image

import bracket_view as bv

AL_DIV = 'American League East'
NL_DIV = 'National League East'


def _t(tid, rank):
    return {'team_id': tid, 'league_rank': str(rank)}


STANDINGS = {
    'standings': {
        AL_DIV: [_t(139, 1), _t(114, 2), _t(111, 5), _t(147, 4), _t(145, 3), _t(117, 6)],
        NL_DIV: [_t(119, 1), _t(158, 2), _t(143, 5), _t(144, 4), _t(135, 3), _t(112, 6)],
        'bogus division': [_t(999, 1)],
    },
    'team_abbreviation': {'139': 'TB', '114': 'CLE', '111': 'BOS', '147': 'NYY', '145': 'CWS',
                          '117': 'HOU', '119': 'LAD', '158': 'MIL', '143': 'PHI', '144': 'ATL',
                          '135': 'SD', '112': 'CHC'},
}


def _s(rnd, away, home, aw=0, hw=0, complete=False, winner=None):
    """away/home are (abbr, id)."""
    return {'round': rnd, 'away_abbr': away[0], 'away_id': str(away[1]),
            'home_abbr': home[0], 'home_id': str(home[1]),
            'away_wins': aw, 'home_wins': hw, 'complete': complete, 'winner_abbr': winner}


def _bracket(**overrides):
    series = [
        # deliberately shuffled so slot placement has to be data-driven
        _s('WC', ('CHC', 112), ('SD', 135)),
        _s('WC', ('BOS', 111), ('NYY', 147)),
        _s('WC', ('PHI', 143), ('ATL', 144)),
        _s('WC', ('CWS', 145), ('HOU', 117)),
        _s('DS', ('SD/CHC', 5533), ('MIL', 158)),
        _s('DS', ('HOU/CWS', 5528), ('CLE', 114)),
        _s('DS', ('ATL/PHI', 5532), ('LAD', 119)),
        _s('DS', ('NYY/BOS', 5529), ('TB', 139)),
        _s('CS', ('NL Low', 5525), ('NL High', 5517)),
        _s('CS', ('AL Low', 5521), ('AL High', 5513)),
        _s('WS', ('Low', 2711), ('High', 2710)),
    ]
    data = {'series': series}
    data.update(overrides)
    return data


@pytest.fixture(autouse=True)
def no_logos():
    with patch('panel_cell._logo_small', return_value=None):
        yield


def _maps():
    return bv._team_maps(STANDINGS)


class TestTeamMaps:
    def test_league_seed_and_abbr_lookups(self):
        league, seed, abbr_league = _maps()
        assert league['139'] == 'AL' and league['119'] == 'NL'
        assert seed['114'] == 2
        assert abbr_league['SD'] == 'NL'
        assert '999' not in league  # unknown division skipped

    def test_bad_rank_falls_back_and_blank_ids_are_skipped(self):
        data = {'standings': {AL_DIV: [{'team_id': 1, 'league_rank': 'x'}, {'team_id': ''}]}}
        league, seed, _ = bv._team_maps(data)
        assert seed == {'1': 99}
        assert list(league) == ['1']

    def test_missing_sections_are_tolerated(self):
        assert bv._team_maps({}) == ({}, {}, {})


class TestSeriesLeague:
    def test_by_team_id(self):
        league, _, abbr_league = _maps()
        s = _s('WC', ('BOS', 111), ('NYY', 147))
        assert bv._series_league(s, league, abbr_league) == 'AL'

    def test_by_placeholder_token(self):
        _, _, abbr_league = _maps()
        assert bv._series_league(_s('DS', ('ATL/PHI', 1), ('???', 2)), {}, abbr_league) == 'NL'

    def test_by_league_prefixed_placeholder(self):
        assert bv._series_league(_s('CS', ('AL Low', 1), ('AL High', 2)), {}, {}) == 'AL'

    def test_ws_placeholder_has_no_league(self):
        assert bv._series_league(_s('WS', ('Low', 1), ('High', 2)), {}, {}) is None


class TestSlots:
    def test_ds_ordered_by_bye_seed_and_wc_lined_up_with_feeder(self):
        league, seed, abbr_league = _maps()
        slots = bv._build_slots(_bracket(), league, seed, abbr_league)
        al = slots['AL']
        assert [s['home_abbr'] for s in al['DS']] == ['TB', 'CLE']
        assert [s['home_abbr'] for s in al['WC']] == ['NYY', 'HOU']
        nl = slots['NL']
        assert [s['home_abbr'] for s in nl['DS']] == ['LAD', 'MIL']
        assert [s['home_abbr'] for s in nl['WC']] == ['ATL', 'SD']
        assert al['CS'][0]['away_abbr'] == 'AL Low'
        assert slots['WS']['away_abbr'] == 'Low'

    def test_feeder_match_after_wc_decided_uses_team_ids(self):
        b = _bracket()
        b['series'][0] = _s('WC', ('CHC', 112), ('SD', 135), 0, 2, True, 'SD')
        # DS now names the real team instead of the placeholder
        b['series'][4] = _s('DS', ('SD', 135), ('MIL', 158))
        league, seed, abbr_league = _maps()
        nl = bv._build_slots(b, league, seed, abbr_league)['NL']
        assert nl['WC'][1]['winner_abbr'] == 'SD'

    def test_unlinked_wc_series_fill_empty_slots_higher_seed_gap_first(self):
        b = {'series': [_s('WC', ('BOS', 111), ('NYY', 147)),
                        _s('WC', ('CWS', 145), ('HOU', 117))]}
        league, seed, abbr_league = _maps()
        al = bv._build_slots(b, league, seed, abbr_league)['AL']
        assert al['DS'] == [None, None]
        assert [s['home_abbr'] for s in al['WC']] == ['NYY', 'HOU']  # 4v5 (BOS=5) above 3v6

    def test_missing_rounds_are_none(self):
        league, seed, abbr_league = _maps()
        slots = bv._build_slots({'series': [_s('WC', ('BOS', 111), ('NYY', 147))]},
                                league, seed, abbr_league)
        assert slots['WS'] is None
        assert slots['NL'] == {'WC': [None, None], 'DS': [None, None], 'CS': [None]}


class TestCaption:
    def test_none_and_unstarted_are_blank(self):
        assert bv._caption(None) == ''
        assert bv._caption(_s('DS', ('A', 1), ('B', 2))) == ''

    def test_tied(self):
        assert bv._caption(_s('DS', ('A', 1), ('B', 2), 1, 1)) == 'Tied 1-1'

    def test_leader_first_for_either_side(self):
        assert bv._caption(_s('DS', ('AAA', 1), ('BBB', 2), 2, 1)) == 'AAA 2-1'
        assert bv._caption(_s('DS', ('AAA', 1), ('BBB', 2), 0, 1)) == 'BBB 1-0'

    def test_complete(self):
        assert bv._caption(_s('DS', ('A', 1), ('B', 2), 3, 1, True, 'A')) == 'FINAL'


def _render(bracket=None, standings=STANDINGS, **kw):
    return bv.render_bracket_view(bracket or _bracket(), standings, **kw)


def _ink(img, box):
    return sum(1 for x in range(box[0], box[2]) for y in range(box[1], box[3])
               if img.getpixel((x, y)) == 0)


class TestRender:
    @pytest.mark.parametrize('data', [None, {}, {'series': []}])
    def test_no_bracket_raises(self, data):
        with pytest.raises(ValueError):
            bv.render_bracket_view(data, STANDINGS)

    def test_full_screen_one_bit(self):
        img = _render()
        assert img.size == (800, 480)
        assert img.mode == '1'

    def test_standings_are_optional(self):
        assert _render(standings=None).size == (800, 480)

    def test_partial_bracket_draws_tbd_boxes(self):
        img = bv.render_bracket_view({'series': [_s('WC', ('BOS', 111), ('NYY', 147))]}, STANDINGS)
        assert img.size == (800, 480)

    def test_winner_row_is_inverted_and_loser_struck(self):
        b = _bracket()
        b['series'][1] = _s('WC', ('BOS', 111), ('NYY', 147), 0, 2, True, 'NYY')
        img = _render(b)
        league, seed, abbr_league = _maps()
        slots = bv._build_slots(b, league, seed, abbr_league)
        idx = slots['AL']['WC'].index(b['series'][1])
        cy = bv._slot_center_y(idx, 2)
        x, y = bv._box_origin(0, cy)
        home_row = (x + 2, y + bv._ROW_H + 2, x + bv._BOX_W - 2, y + 2 * bv._ROW_H - 2)
        away_row = (x + 2, y + 2, x + bv._BOX_W - 2, y + bv._ROW_H - 2)
        assert _ink(img, home_row) > 0.5 * (home_row[2] - home_row[0]) * (home_row[3] - home_row[1])
        mid = y + bv._ROW_H // 2
        assert all(img.getpixel((px, mid)) == 0 for px in range(x + 6, x + bv._BOX_W - 6))
        assert _ink(img, away_row) < 0.5 * (away_row[2] - away_row[0]) * (away_row[3] - away_row[1])

    def test_series_in_progress_draws_score_and_caption(self):
        b = _bracket()
        b['series'][1] = _s('WC', ('BOS', 111), ('NYY', 147), 1, 0)
        assert _ink(_render(b), (0, 40, 800, 480)) > _ink(_render(), (0, 40, 800, 480))

    def test_placeholder_wins_are_hidden_until_nonzero(self):
        b = _bracket()
        assert _render(b).size == (800, 480)
        b['series'][8] = _s('CS', ('NL Low', 5525), ('NL High', 5517), 1, 0)
        assert _render(b).size == (800, 480)

    def test_dark_mode_inverts(self):
        assert _render(dark_mode=False).getpixel((400, 470)) == 255
        assert _render(dark_mode=True).getpixel((400, 470)) == 0

    def test_logos_pasted_when_available(self):
        solid = Image.new('1', (20, 20), 0)
        with patch('panel_cell._logo_small', return_value=solid):
            with_logos = _render()
        with patch('panel_cell._logo_small', return_value=None):
            without = _render()
        assert _ink(with_logos, (0, 40, 800, 480)) > _ink(without, (0, 40, 800, 480))


class TestMain:
    def _run(self, tmp_path, monkeypatch, argv, bracket, standings):
        import sys
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, 'argv', ['bracket_view.py'] + argv)
        data = {'playoff_bracket.json': bracket, 'standings.json': standings}
        with patch('util.load_json_file', side_effect=lambda name, *a, **k: data.get(name)):
            bv.main()

    def test_writes_image(self, tmp_path, monkeypatch, capsys):
        self._run(tmp_path, monkeypatch, ['--output', 'out.bmp', '--dark'], _bracket(), STANDINGS)
        assert (tmp_path / 'out.bmp').exists()
        assert 'Image saved' in capsys.readouterr().out

    def test_missing_data_message(self, tmp_path, monkeypatch, capsys):
        self._run(tmp_path, monkeypatch, [], None, None)
        assert 'run src/standings.py' in capsys.readouterr().out

    def test_unusable_data_message(self, tmp_path, monkeypatch, capsys):
        self._run(tmp_path, monkeypatch, [], {'series': []}, STANDINGS)
        assert 'Bracket view unavailable' in capsys.readouterr().out

    def test_open_flag_only_opens_on_macos(self, tmp_path, monkeypatch):
        with patch('platform.system', return_value='Darwin'), \
             patch('subprocess.run') as run:
            self._run(tmp_path, monkeypatch, ['--output', 'o.bmp', '--open'], _bracket(), STANDINGS)
        run.assert_called_once()
        with patch('platform.system', return_value='Linux'), \
             patch('subprocess.run') as run:
            self._run(tmp_path, monkeypatch, ['--output', 'o.bmp', '--open'], _bracket(), STANDINGS)
        run.assert_not_called()
