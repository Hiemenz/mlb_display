"""Tests for fetch_free_agents and image_free_agents."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

import fetch_free_agents as ffa
import image_free_agents as ifa

TODAY = datetime(2026, 11, 20)


def _resp(code=200, data=None):
    m = MagicMock()
    m.status_code = code
    m.json.return_value = data or {}
    return m


def _tx(pid=1, name='A Player', desc='Seattle Mariners signed free agent 1B A Player.',
        code='SFA', date='2026-11-18', to_id=136):
    return {'typeCode': code, 'description': desc, 'date': date,
            'person': {'id': pid, 'fullName': name},
            'toTeam': {'id': to_id, 'name': 'Seattle Mariners'}}


def _person(debut='2019-04-29', team=(116, 'Detroit Tigers'), sport=1):
    splits = [{'season': '2026', 'sport': {'id': sport}},
              {'season': '2026', 'sport': {'id': sport}, 'team': {'id': team[0], 'name': team[1]}}]
    return {'mlbDebutDate': debut, 'primaryPosition': {'abbreviation': '1B'},
            'stats': [{'splits': splits}]}


def test_parse_terms():
    assert ffa._parse_terms('signed to a 5-year, $120 million deal') == '5 yr / $120M'
    assert ffa._parse_terms('agreed to a one-year contract') == '1 yr'
    assert ffa._parse_terms('$2 billion') == '$2B'
    assert ffa._parse_terms('signed free agent 1B A Player.') is None
    assert ffa._parse_terms(None) is None


def test_major_league_filter():
    assert ffa._is_major_league_signing(_tx())
    assert not ffa._is_major_league_signing(_tx(desc='signed to a minor league contract.'))
    assert not ffa._is_major_league_signing(_tx(code='TR'))


def test_experienced():
    assert ffa._experienced({'mlbDebutDate': '2019-04-29'}, TODAY)
    assert not ffa._experienced({'mlbDebutDate': '2026-09-01'}, TODAY)
    assert not ffa._experienced({}, TODAY)
    assert not ffa._experienced({'mlbDebutDate': 'garbage'}, TODAY)


def test_previous_team_is_last_mlb_team():
    assert ffa._previous_team(_person()) == (116, 'Detroit Tigers')
    assert ffa._previous_team(_person(sport=11)) == (None, None)
    assert ffa._previous_team({}) == (None, None)


def _fetch(txs, person):
    def get(url, timeout=0):
        return _resp(200, {'transactions': txs}) if 'transactions' in url \
            else _resp(200, {'people': [person] if person else []})
    with patch('fetch_free_agents.requests.get', side_effect=get), \
         patch('fetch_free_agents.save_off_results') as save:
        return ffa.fetch_free_agents(today=TODAY), save


def test_fetch_keeps_experienced_major_league_signing():
    data, save = _fetch([_tx(), _tx(pid=2, desc='minor league contract')], _person())
    assert [s['player_name'] for s in data['signings']] == ['A Player']
    s = data['signings'][0]
    assert (s['from_team_name'], s['to_team_id'], s['terms']) == ('Detroit Tigers', '136', None)
    save.assert_called_once()


def test_fetch_drops_rookies_and_missing_people():
    assert _fetch([_tx()], _person(debut='2026-10-01'))[0]['signings'] == []
    assert _fetch([_tx()], None)[0]['signings'] == []


def test_fetch_skips_records_without_team_or_person():
    bad = _tx()
    bad['toTeam'] = None
    assert _fetch([bad], _person())[0]['signings'] == []


def test_fetch_api_failures_return_none():
    with patch('fetch_free_agents.requests.get', return_value=_resp(500)):
        assert ffa.fetch_free_agents(today=TODAY) is None
    with patch('fetch_free_agents.requests.get', side_effect=OSError('x')):
        assert ffa.fetch_free_agents(today=TODAY) is None


def test_fetch_person_failures():
    with patch('fetch_free_agents.requests.get', return_value=_resp(404)):
        assert ffa._fetch_person(1) is None
    with patch('fetch_free_agents.requests.get', side_effect=OSError('x')):
        assert ffa._fetch_person(1) is None


# --- rendering -------------------------------------------------------------

SIGNING = {'player_id': 1, 'player_name': 'Gleyber Torres', 'position': '2B',
           'date': '2026-11-18', 'from_team_id': '116', 'from_team_name': 'Detroit Tigers',
           'to_team_id': '147', 'to_team_name': 'New York Yankees', 'terms': '5 yr / $120M'}
TEAMS = {'team_abbreviation': {'116': 'DET', '147': 'NYY'}}


@pytest.fixture(autouse=True)
def _no_network():
    with patch('image_free_agents.requests.get', side_effect=OSError('offline')), \
         patch('image_free_agents._try_download_logo', return_value=False):
        yield


def test_draw_returns_panel_sized_1bit():
    img = ifa.draw_free_agent_screen(SIGNING, TEAMS, {}, 2, 9)
    assert img.size == (800, 480) and img.mode == '1'


def test_draw_handles_missing_terms_resign_and_bad_date():
    s = dict(SIGNING, terms=None, to_team_id='116', date='nope')
    assert ifa.draw_free_agent_screen(s, TEAMS, {}).size == (800, 480)


def _ts(day, hh, mm):
    return datetime(*map(int, day.split('-')), hh, mm).timestamp()


def test_when_label_adds_time_only_when_seen_the_same_day():
    same = dict(SIGNING, seen_at=_ts('2026-11-18', 15, 42))
    assert ifa._when_label(same) == 'NOV 18 · SEEN 3:42 PM'
    assert ifa._when_label(same, short=True) == 'NOV 18 3:42P'
    assert ifa._when_label(dict(same, seen_at=_ts('2026-11-18', 9, 5)), short=True) == 'NOV 18 9:05A'
    assert ifa._when_label(dict(SIGNING, seen_at=_ts('2026-11-19', 8, 0))) == 'NOV 18'   # seen a day later: date only
    assert ifa._when_label(dict(SIGNING, seen_at=None)) == 'NOV 18'                      # backlog from the first poll
    assert ifa._when_label(dict(SIGNING, seen_at=10 ** 30)) == 'NOV 18'                  # nonsense timestamp
    assert ifa._when_label(dict(SIGNING, date='nope', seen_at=_ts('2026-11-18', 1, 0))) == ''


def test_cards_and_grid_draw_with_a_seen_time():
    s = dict(SIGNING, seen_at=_ts('2026-11-18', 15, 42))
    plain = ifa.draw_free_agent_screen(SIGNING, TEAMS, {})
    assert ifa.draw_free_agent_screen(s, TEAMS, {}).tobytes() != plain.tobytes()
    grid = ifa.draw_free_agent_grid([s, SIGNING], TEAMS, {})
    assert grid.size == (800, 480)
    assert grid.tobytes() != ifa.draw_free_agent_grid([SIGNING, SIGNING], TEAMS, {}).tobytes()


def test_dark_mode_keeps_headshot_positive():
    photo = Image.new('1', (ifa._PHOTO_W, ifa._PHOTO_H), 1)   # an all-white portrait
    with patch('image_free_agents._load_headshot', return_value=photo):
        light = ifa.draw_free_agent_screen(SIGNING, TEAMS, {})
        dark = ifa.draw_free_agent_screen(SIGNING, TEAMS, {'dark_mode': True})
    probe = (ifa._PX + ifa._PHOTO_W // 2, ifa._PY + ifa._PHOTO_H // 2)
    assert light.getpixel(probe) == dark.getpixel(probe) == 1
    assert dark.getpixel((5, 100)) == 0   # while the page itself is dark


def test_headshot_download_and_cache(tmp_path):
    png = tmp_path / 'p.png'
    Image.new('L', (50, 50), 128).save(png)
    ok = MagicMock(status_code=200, content=png.read_bytes())
    with patch('image_free_agents._HEADSHOT_DIR', str(tmp_path / 'hs')), \
         patch('image_free_agents.requests.get', return_value=ok):
        assert ifa._load_headshot(7, 40, 60).size == (40, 60)
        assert ifa._load_headshot(7, 40, 60) is not None            # now from cache
        bad = MagicMock(status_code=404)
        with patch('image_free_agents.requests.get', return_value=bad):
            assert ifa._load_headshot(8) is None


def test_headshot_unreadable_cache(tmp_path):
    (tmp_path / '9.png').write_bytes(b'not an image')
    with patch('image_free_agents._HEADSHOT_DIR', str(tmp_path)):
        assert ifa._load_headshot(9) is None


# --- idle rotation ---------------------------------------------------------

SINGLE = {'free_agent_layout': 'single'}


def _store(**files):
    return lambda name: files.get(name)


def test_pick_signing_steps_and_wraps():
    sigs = ['a', 'b', 'c']
    t0 = datetime(2026, 11, 20, 9, 0)
    t1 = datetime(2026, 11, 20, 10, 0)
    assert ifa.pick_signing([], t0) == (None, 0)
    assert ifa.pick_signing(sigs, t0)[0] != ifa.pick_signing(sigs, t1)[0]
    assert ifa.pick_signing(sigs, t0) == ifa.pick_signing(sigs, datetime(2026, 11, 20, 9, 10))


def test_idle_image_gates():
    fresh = {'free_agents.json': {'fetched_at': 9e12, 'signings': [SIGNING]}, 'teams.json': TEAMS}
    even, odd = datetime(2026, 11, 20, 9, 0), datetime(2026, 11, 20, 9, 35)
    kw = dict(load=_store(**fresh), replay_running=lambda pid: False)
    assert ifa.free_agent_idle_image(SINGLE, even, **kw).size == (800, 480)
    assert ifa.free_agent_idle_image({}, odd, **kw) is None
    assert ifa.free_agent_idle_image({'idle_free_agent_rotation': False}, even, **kw) is None
    assert ifa.free_agent_idle_image({}, even, load=_store(**fresh),
                                     replay_running=lambda pid: True) is None
    empty = {'free_agents.json': {'fetched_at': 9e12, 'signings': []}}
    assert ifa.free_agent_idle_image({}, even, load=_store(**empty),
                                     replay_running=lambda pid: False) is None


def test_idle_image_refreshes_stale_data_and_survives_failures():
    even = datetime(2026, 11, 20, 9, 0)
    stale = _store(**{'teams.json': TEAMS})
    fetch = MagicMock(return_value={'signings': [SIGNING]})
    img = ifa.free_agent_idle_image({}, even, load=stale, fetch=fetch,
                                    replay_running=lambda pid: False)
    assert img is not None and fetch.call_args.kwargs == {'lookback_days': 21, 'include_trades': True, 'previous': {}}
    boom = MagicMock(side_effect=RuntimeError('x'))
    assert ifa.free_agent_idle_image({}, even, load=stale, fetch=boom,
                                     replay_running=lambda pid: False) is None
    assert ifa.free_agent_idle_image({}, even, load=stale, fetch=MagicMock(return_value=None),
                                     replay_running=lambda pid: False) is None


def test_grid_renders_ten_cells_and_pages():
    many = [dict(SIGNING, player_id=i, terms=None if i % 2 else '1 yr / $5M') for i in range(10)]
    many[3]['to_team_id'] = many[3]['from_team_id']        # a re-signing
    many[4]['player_name'] = 'A Very Long Hyphenated-Name Junior'
    img = ifa.draw_free_agent_grid(many + [SIGNING], TEAMS, {}, 1, 2)   # 11th is dropped
    assert img.size == (800, 480) and img.mode == '1'
    assert ifa.draw_free_agent_grid([], TEAMS, {}).size == (800, 480)


def test_grid_dark_mode_keeps_portraits_positive():
    photo = Image.new('1', (ifa._G_PHOTO_W, ifa._G_PHOTO_H), 1)
    with patch('image_free_agents._load_headshot', return_value=photo):
        dark = ifa.draw_free_agent_grid([SIGNING], TEAMS, {'dark_mode': True})
    assert dark.getpixel((ifa._G_PX + 45, ifa._HDR_H + ifa._G_PY + 67)) == 1
    assert dark.getpixel((790, 470)) == 0


def test_idle_image_defaults_to_grid_and_pages_through_signings():
    sigs = [dict(SIGNING, player_id=i) for i in range(27)]
    kw = dict(load=_store(**{'free_agents.json': {'fetched_at': 9e12, 'signings': sigs},
                            'teams.json': TEAMS}), replay_running=lambda pid: False)
    with patch('image_free_agents.draw_free_agent_grid', wraps=ifa.draw_free_agent_grid) as g:
        ifa.free_agent_idle_image({}, datetime(2026, 11, 20, 9, 0), **kw)
        ifa.free_agent_idle_image({}, datetime(2026, 11, 20, 10, 0), **kw)
    first, second = (c.args[0] for c in g.call_args_list)
    assert len(first) + len(second) == 27 and first != second


def test_team_logo_paths():
    assert ifa._team_logo('', '1') is None
    with patch('image_free_agents._load_logo_gray', return_value=None), \
         patch('image_free_agents._logo_small', return_value=None):
        assert ifa._team_logo('DET', '116') is None
    small_wide = Image.new('1', (40, 20), 0)
    small_tall = Image.new('1', (20, 40), 0)
    big = Image.new('1', (130, 100), 0)
    with patch('image_free_agents._load_logo_gray', return_value=object()):
        for logo, want in ((small_wide, (100, 50)), (small_tall, (50, 100)), (big, (130, 100))):
            with patch('image_free_agents._logo_small', return_value=logo):
                assert ifa._team_logo('DET', '116').size == want


def test_placeholder_initials_when_no_headshot():
    with patch('image_free_agents._load_headshot', return_value=None):
        assert ifa.draw_free_agent_screen(SIGNING, TEAMS, {}).size == (800, 480)
        assert ifa.draw_free_agent_grid([SIGNING], TEAMS, {'dark_mode': True}).size == (800, 480)
        no_teams = dict(SIGNING, from_team_id='', to_team_id='')
        assert ifa.draw_free_agent_grid([no_teams], {}, {}).size == (800, 480)


def test_idle_image_default_collaborators():
    even = datetime(2026, 11, 20, 9, 0)
    with patch('offseason_replay._replay_running', return_value=False), \
         patch('fetch_free_agents.fetch_free_agents', return_value={'signings': [SIGNING]}):
        img = ifa.free_agent_idle_image(SINGLE, even, load=_store(**{'teams.json': TEAMS}))
    assert img is not None


# --- trades ----------------------------------------------------------------

def _trade(pid=5, date='2026-11-18', frm=(111, 'Boston Red Sox'), to=(147, 'New York Yankees'),
           mirrored=False):
    """One half of the API's mirrored pair; `mirrored` swaps from/to like the bad half does."""
    a, b = ({'id': to[0], 'name': to[1]}, {'id': frm[0], 'name': frm[1]})
    tx = {'typeCode': 'TR', 'date': date, 'person': {'id': pid, 'fullName': 'T Rade'},
          'description': f'{frm[1]} traded RHP T Rade to {to[1]} for cash.'}
    tx['fromTeam'], tx['toTeam'] = (b, a) if not mirrored else (a, b)
    return tx


def test_trade_direction_comes_from_description():
    for mirrored in (False, True):
        frm, to = ffa._trade_teams(_trade(mirrored=mirrored))
        assert (frm['name'], to['name']) == ('Boston Red Sox', 'New York Yankees')
    odd = {'description': 'nothing useful', 'fromTeam': {'name': 'A'}, 'toTeam': {'name': 'B'}}
    assert [t['name'] for t in ffa._trade_teams(odd)] == ['A', 'B']


def test_fetch_includes_deduplicated_trades():
    data, _ = _fetch([_trade(), _trade(mirrored=True), _tx()], _person())
    kinds = sorted(s['kind'] for s in data['signings'])
    assert kinds == ['signing', 'trade']
    trade = next(s for s in data['signings'] if s['kind'] == 'trade')
    assert (trade['from_team_name'], trade['to_team_id'], trade['terms']) == \
        ('Boston Red Sox', '147', None)


def test_fetch_can_exclude_trades_and_skips_teamless_trades():
    def get(url, timeout=0):
        return _resp(200, {'transactions': [_trade()]}) if 'transactions' in url \
            else _resp(200, {'people': [_person()]})
    with patch('fetch_free_agents.requests.get', side_effect=get), \
         patch('fetch_free_agents.save_off_results'):
        assert ffa.fetch_free_agents(today=TODAY, include_trades=False)['signings'] == []
    bad = _trade()
    bad['fromTeam'] = bad['toTeam'] = {}
    assert _fetch([bad], _person())[0]['signings'] == []


def test_titles_and_verbs_follow_kind():
    sg, tr = dict(SIGNING), dict(SIGNING, kind='trade')
    assert ifa._title_for([sg]) == 'FREE AGENT SIGNINGS'
    assert ifa._title_for([sg], single=True) == 'FREE AGENT SIGNING'
    assert ifa._title_for([tr]) == 'TRADES' and ifa._title_for([tr], single=True) == 'TRADE'
    assert ifa._title_for([sg, tr]) == 'SIGNINGS & TRADES'
    assert ifa._verb(tr) == 'TRADED' and ifa._verb(sg) == 'SIGNED'
    assert ifa.draw_free_agent_screen(dict(tr, terms=None), TEAMS, {}).size == (800, 480)


# --- density & paging ------------------------------------------------------

def test_paginate_balances_and_switches_tier():
    assert ifa.paginate([]) == []
    assert [len(c) for c in ifa.paginate(range(7))] == [7]
    assert [len(c) for c in ifa.paginate(range(10))] == [10]
    assert [len(c) for c in ifa.paginate(range(11))] == [11]
    assert [len(c) for c in ifa.paginate(range(20))] == [20]
    assert [len(c) for c in ifa.paginate(range(27))] == [14, 13]
    assert sum(len(c) for c in ifa.paginate(range(61))) == 61


@pytest.mark.parametrize('n', [1, 5, 10, 11, 15, 16, 20])
def test_grid_renders_any_count(n):
    moves = [dict(SIGNING, player_id=i, kind='trade' if i % 2 else 'signing',
                  terms=None if i % 3 else '1 yr / $5M') for i in range(n)]
    for dark in (False, True):
        img = ifa.draw_free_agent_grid(moves, TEAMS, {'dark_mode': dark})
        assert img.size == (800, 480)


def test_dense_pages_fill_the_panel_height():
    for n, rows in ((11, 3), (15, 3), (16, 4), (20, 4)):
        img = ifa.draw_free_agent_grid([dict(SIGNING)] * n, TEAMS, {})
        bottom_row_top = ifa._HDR_H + (rows - 1) * ((480 - ifa._HDR_H) // rows)
        # something is drawn in the last row's band, and nothing past the rows
        assert any(img.getpixel((x, bottom_row_top + 20)) == 0 for x in range(0, 800, 3))


def test_idle_image_dense_and_trade_filter():
    sigs = [dict(SIGNING, player_id=i, kind='trade' if i < 20 else 'signing') for i in range(23)]
    store = _store(**{'free_agents.json': {'fetched_at': 9e12, 'signings': sigs}, 'teams.json': TEAMS})
    even = datetime(2026, 11, 20, 9, 0)
    with patch('image_free_agents.draw_free_agent_grid', wraps=ifa.draw_free_agent_grid) as g:
        ifa.free_agent_idle_image({}, even, load=store, replay_running=lambda p: False)
        assert g.call_args.kwargs['dense'] is True
        ifa.free_agent_idle_image({'free_agent_include_trades': False}, even, load=store,
                                  replay_running=lambda p: False)
        assert g.call_args.kwargs['dense'] is False and len(g.call_args.args[0]) == 3


def test_choose_grid_fills_the_panel():
    assert ifa.choose_grid(2) == (2, 1)
    assert ifa.choose_grid(4) == (4, 1)
    assert ifa.choose_grid(6) == (3, 2)
    assert ifa.choose_grid(10) == (5, 2)
    for n in range(2, 11):
        cols, rows = ifa.choose_grid(n)
        assert cols * rows >= n


def test_single_move_uses_the_full_card_and_short_rows_are_centred():
    one = ifa.draw_free_agent_grid([SIGNING], TEAMS, {})
    assert one.tobytes() == ifa.draw_free_agent_screen(SIGNING, TEAMS, {}).tobytes()
    assert ifa.draw_free_agent_grid([SIGNING] * 7, TEAMS, {}).size == (800, 480)   # 4 + 3, centred


def test_resign_shows_the_team_once_in_every_layout():
    rs = dict(SIGNING, to_team_id='116', terms='1 yr / $5M')
    assert ifa._is_resign(rs) and not ifa._is_resign(SIGNING)
    assert not ifa._is_resign(dict(SIGNING, from_team_id='', to_team_id=''))
    single = ifa.draw_free_agent_screen(rs, TEAMS, {})
    roomy = ifa.draw_free_agent_grid([rs, SIGNING], TEAMS, {'dark_mode': True})
    dense = ifa.draw_free_agent_grid([rs] * 12, TEAMS, {})
    assert {i.size for i in (single, roomy, dense)} == {(800, 480)}


# --- polling & breaking ------------------------------------------

def test_fetch_reuses_known_moves_and_flags_new_ones_as_new():
    first, _ = _fetch([_tx(pid=1)], _person())
    assert first['signings'][0]['seen_at'] is None            # initial population: not breaking
    calls = []

    def get(url, timeout=0):
        calls.append(url)
        return _resp(200, {'transactions': [_tx(pid=1), _tx(pid=2)]}) if 'transactions' in url \
            else _resp(200, {'people': [_person()]})
    with patch('fetch_free_agents.requests.get', side_effect=get), \
         patch('fetch_free_agents.save_off_results'):
        second = ffa.fetch_free_agents(today=TODAY, previous=first)
    assert sum('/people/' in c for c in calls) == 1            # only the new player is looked up
    by_id = {m['player_id']: m for m in second['signings']}
    assert by_id[1]['seen_at'] is None and by_id[2]['seen_at']  # the new one is stamped


def test_fetch_remembers_rookies_and_retries_failures():
    rookie = _person(debut='2026-10-01')
    first, _ = _fetch([_tx(pid=3)], rookie)
    assert first['skipped'] == ['3:2026-11-18:signing'] and first['signings'] == []
    calls = []

    def get(url, timeout=0):
        calls.append(url)
        return _resp(200, {'transactions': [_tx(pid=3), _tx(pid=4)]}) if 'transactions' in url \
            else _resp(500)
    with patch('fetch_free_agents.requests.get', side_effect=get), \
         patch('fetch_free_agents.save_off_results'):
        out = ffa.fetch_free_agents(today=TODAY, previous=first)
    assert sum('/people/3' in c for c in calls) == 0           # known rookie: no refetch
    assert sum('/people/4' in c for c in calls) == 1           # failure: not remembered
    assert out['skipped'] == ['3:2026-11-18:signing'] and out['signings'] == []


def test_breaking_badge_and_window():
    assert ifa._is_breaking({'seen_at': 1000}, 1000 + 59 * 60, 60)
    assert not ifa._is_breaking({'seen_at': 1000}, 1000 + 61 * 60, 60)
    assert not ifa._is_breaking({'seen_at': None}, 1000, 60)
    assert not ifa._is_breaking({}, 1000, 60)
    plain = ifa.draw_free_agent_grid([SIGNING, SIGNING], TEAMS, {})
    badged = ifa.draw_free_agent_grid([SIGNING, SIGNING], TEAMS, {}, breaking=True)
    assert plain.tobytes() != badged.tobytes()
    assert ifa.draw_free_agent_screen(SIGNING, TEAMS, {}, breaking=True).tobytes() != \
        ifa.draw_free_agent_screen(SIGNING, TEAMS, {}).tobytes()


def test_idle_breaking_overrides_the_odd_block_and_shows_only_new_moves():
    old = dict(SIGNING, player_id=1, seen_at=None)
    new = dict(SIGNING, player_id=2, seen_at=5000)
    store = _store(**{'free_agents.json': {'fetched_at': 5000, 'signings': [old, new]}, 'teams.json': TEAMS})
    odd = datetime(2026, 11, 20, 9, 45)
    kw = dict(load=store, replay_running=lambda p: False)
    assert ifa.free_agent_idle_image({}, odd, now_ts=5000 + 600, **kw) is not None     # breaking
    assert ifa.free_agent_idle_image({}, odd, now_ts=5000 + 29 * 60, **kw) is not None  # still breaking
    assert ifa.free_agent_idle_image({}, odd, now_ts=5000 + 31 * 60, **kw) is None     # aged out of the 30-min window
    with patch('image_free_agents.draw_free_agent_grid', wraps=ifa.draw_free_agent_grid) as g:
        ifa.free_agent_idle_image({}, odd, now_ts=5000 + 600, **kw)
    assert g.call_args.args[0] == [new] and g.call_args.kwargs['breaking'] is True
    # a running replay still wins, even over breaking news
    assert ifa.free_agent_idle_image({}, odd, now_ts=5600, load=store, replay_running=lambda p: True) is None
    # single layout also switches to the grid path while breaking
    assert ifa.free_agent_idle_image({'free_agent_layout': 'single'}, odd, now_ts=5600, **kw) is not None


def test_poll_interval_is_quarter_hourly_and_configurable():
    even = datetime(2026, 11, 20, 9, 0)
    fetch = MagicMock(return_value={'signings': [SIGNING]})
    kw = dict(fetch=fetch, replay_running=lambda p: False, now_ts=10_000)

    def store(fetched_at):
        return _store(**{'free_agents.json': {'fetched_at': fetched_at, 'signings': [SIGNING]},
                         'teams.json': TEAMS})
    ifa.free_agent_idle_image({}, even, load=store(10_000 - 14 * 60), **kw)
    assert not fetch.called                                   # 14 min old: still fresh
    ifa.free_agent_idle_image({}, even, load=store(10_000 - 16 * 60), **kw)
    assert fetch.call_count == 1                              # 16 min old: re-poll
    ifa.free_agent_idle_image({'free_agent_poll_minutes': 60}, even, load=store(10_000 - 20 * 60), **kw)
    assert fetch.call_count == 1                              # configurable


def test_has_moves_respects_toggles():
    store = _store(**{'free_agents.json': {'signings': [dict(SIGNING, kind='trade')]}})
    assert ifa.has_moves({}, load=store)
    assert not ifa.has_moves({'free_agent_include_trades': False}, load=store)
    assert not ifa.has_moves({'idle_free_agent_rotation': False}, load=store)
    assert not ifa.has_moves({}, load=_store())
    with patch('util.load_json_file', return_value={'signings': [SIGNING]}):
        assert ifa.has_moves({})


def test_idle_blocks_alternate_every_15_minutes_when_configured():
    fresh = {'free_agents.json': {'fetched_at': 9e12, 'signings': [SIGNING]}, 'teams.json': TEAMS}
    kw = dict(load=_store(**fresh), replay_running=lambda pid: False)
    cfg = dict(SINGLE, free_agent_idle_blocks=[0, 2])
    shown = [m for m in (0, 15, 30, 45)
             if ifa.free_agent_idle_image(cfg, datetime(2026, 11, 20, 9, m), **kw) is not None]
    assert shown == [0, 30]
