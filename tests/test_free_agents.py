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


def test_dark_mode_keeps_headshot_positive():
    photo = Image.new('1', (ifa._PHOTO_W, ifa._PHOTO_H), 1)   # an all-white portrait
    with patch('image_free_agents._load_headshot', return_value=photo):
        light = ifa.draw_free_agent_screen(SIGNING, TEAMS, {})
        dark = ifa.draw_free_agent_screen(SIGNING, TEAMS, {'dark_mode': True})
    probe = (24 + ifa._PHOTO_W // 2, ifa._HDR_H + 24 + ifa._PHOTO_H // 2)
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
    t1 = datetime(2026, 11, 20, 9, 30)
    assert ifa.pick_signing([], t0) == (None, 0)
    assert ifa.pick_signing(sigs, t0)[0] != ifa.pick_signing(sigs, t1)[0]
    assert ifa.pick_signing(sigs, t0) == ifa.pick_signing(sigs, datetime(2026, 11, 20, 9, 10))


def test_idle_image_gates():
    fresh = {'free_agents.json': {'fetched_at': 9e12, 'signings': [SIGNING]}, 'teams.json': TEAMS}
    even, odd = datetime(2026, 11, 20, 9, 0), datetime(2026, 11, 20, 9, 15)
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
    assert img is not None and fetch.call_args.kwargs == {'lookback_days': 21}
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
    assert dark.getpixel((5 + 50, ifa._HDR_H + 5 + 75)) == 1
    assert dark.getpixel((790, 470)) == 0


def test_idle_image_defaults_to_grid_and_pages_through_signings():
    sigs = [dict(SIGNING, player_id=i) for i in range(12)]
    kw = dict(load=_store(**{'free_agents.json': {'fetched_at': 9e12, 'signings': sigs},
                            'teams.json': TEAMS}), replay_running=lambda pid: False)
    with patch('image_free_agents.draw_free_agent_grid', wraps=ifa.draw_free_agent_grid) as g:
        ifa.free_agent_idle_image({}, datetime(2026, 11, 20, 9, 0), **kw)
        ifa.free_agent_idle_image({}, datetime(2026, 11, 20, 9, 30), **kw)
    first, second = (c.args[0] for c in g.call_args_list)
    assert len(first) + len(second) == 12 and first != second


def test_team_logo_paths():
    assert ifa._team_logo('', '1') is None
    with patch('image_free_agents._load_logo_gray', return_value=None), \
         patch('image_free_agents._logo_small', return_value=None):
        assert ifa._team_logo('DET', '116') is None
    small_wide = Image.new('1', (40, 20), 0)
    small_tall = Image.new('1', (20, 40), 0)
    big = Image.new('1', (130, 100), 0)
    with patch('image_free_agents._load_logo_gray', return_value=object()):
        for logo, want in ((small_wide, (130, 65)), (small_tall, (65, 130)), (big, (130, 100))):
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
