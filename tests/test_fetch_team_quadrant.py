"""Tests for fetch_team_quadrant — window maths, the wRC+ proxy, and caching.

Everything network-touching goes through _get_json, so the suite patches that
one seam rather than requests, and builds Stats API-shaped payloads locally.
"""
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

import fetch_team_quadrant as ftq


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _hitting(runs=100, pa=1000, hits=250, doubles=50, triples=5, hr=30,
             bb=90, ibb=5, hbp=10, sf=8, ab=900, games=30):
    """A hitting split shaped like the Stats API's byDateRange response."""
    return {
        'runs': runs, 'plateAppearances': pa, 'hits': hits, 'doubles': doubles,
        'triples': triples, 'homeRuns': hr, 'baseOnBalls': bb,
        'intentionalWalks': ibb, 'hitByPitch': hbp, 'sacFlies': sf,
        'atBats': ab, 'gamesPlayed': games,
    }


def _pitching(era='4.00', innings='270.0', outs=810, games=30):
    """A pitching split shaped like the Stats API's byDateRange response."""
    return {'era': era, 'inningsPitched': innings, 'outs': outs, 'gamesPlayed': games}


def _stats_payload(by_team):
    """Wrap {team_id: stat} in the API's stats/splits envelope."""
    return {'stats': [{'splits': [
        {'team': {'id': tid}, 'stat': stat} for tid, stat in by_team.items()
    ]}]}


# ---------------------------------------------------------------------------
# Scalar helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('value,expected', [
    ('4.12', 4.12), (3, 3.0), (None, 0.0), ('-.--', 0.0), ('', 0.0),
])
def test_num_parses_or_falls_back(value, expected):
    """API stat values arrive as strings, numbers, or placeholders."""
    assert ftq._num(value) == expected


def test_num_honours_explicit_default():
    """A caller-supplied default replaces the 0.0 fallback."""
    assert ftq._num(None, default=9.0) == 9.0


def test_date_formatters():
    """API format is ISO; on-screen labels are M/D."""
    day = date(2026, 8, 4)
    assert ftq._fmt(day) == '2026-08-04'
    assert ftq._short(day) == '8/4'
    assert ftq._parse('2026-08-04') == day
    assert ftq._parse('nonsense') is None
    assert ftq._parse(None) is None


# ---------------------------------------------------------------------------
# Season dates
# ---------------------------------------------------------------------------

def test_fetch_season_dates_reads_api():
    """Regular-season start and first-half end come straight from /seasons."""
    payload = {'seasons': [{'regularSeasonStartDate': '2026-03-25',
                            'lastDate1stHalf': '2026-07-14'}]}
    with patch.object(ftq, '_get_json', return_value=payload):
        start, first_half = ftq.fetch_season_dates(2026)
    assert start == date(2026, 3, 25)
    assert first_half == date(2026, 7, 14)


def test_fetch_season_dates_falls_back_when_lookup_fails():
    """A failed lookup still yields a usable season window, not an exception."""
    with patch.object(ftq, '_get_json', return_value={}):
        start, first_half = ftq.fetch_season_dates(2026)
    assert start == date(2026, 3, 1)
    assert first_half == date(2026, 6, 30)


# ---------------------------------------------------------------------------
# Window selection — the thing that defines each grain
# ---------------------------------------------------------------------------

def test_season_grain_points_back_at_the_first_half():
    """After the break, the season arrow runs first half → season to date."""
    current, baseline = ftq.windows_for_grain(
        'season', date(2026, 8, 10), date(2026, 3, 25), date(2026, 7, 14))
    assert current['start'] == '2026-03-25' and current['end'] == '2026-08-10'
    assert baseline['start'] == '2026-03-25' and baseline['end'] == '2026-07-14'
    assert current['label'] == '3/25 - 8/10'


def test_season_grain_splits_elapsed_season_before_the_break():
    """Before the All-Star break there is no first half — split what's elapsed."""
    _, baseline = ftq.windows_for_grain(
        'season', date(2026, 5, 25), date(2026, 3, 25), date(2026, 7, 14))
    # 61 days elapsed → baseline ends at the 30-day midpoint.
    assert baseline['end'] == '2026-04-24'


def test_season_grain_baseline_never_precedes_opening_day():
    """On opening day itself the baseline collapses to that single date."""
    _, baseline = ftq.windows_for_grain(
        'season', date(2026, 3, 25), date(2026, 3, 25), date(2026, 7, 14))
    assert baseline['start'] == baseline['end'] == '2026-03-25'


@pytest.mark.parametrize('grain,expected_start', [
    ('month', '2026-07-12'),   # 30 days inclusive
    ('week', '2026-08-04'),    # 7 days inclusive
])
def test_short_grains_are_trailing_windows_off_season_baseline(grain, expected_start):
    """Month/week plot recent form against the season-to-date baseline."""
    current, baseline = ftq.windows_for_grain(
        grain, date(2026, 8, 10), date(2026, 3, 25), date(2026, 7, 14))
    assert current['start'] == expected_start
    assert current['end'] == '2026-08-10'
    assert baseline['start'] == '2026-03-25' and baseline['end'] == '2026-08-10'


def test_short_grain_window_clamps_to_season_start():
    """A trailing window early in the year cannot reach into spring training."""
    current, _ = ftq.windows_for_grain(
        'month', date(2026, 4, 2), date(2026, 3, 25), date(2026, 7, 14))
    assert current['start'] == '2026-03-25'


def test_unknown_grain_falls_back_to_the_month_length():
    """An unrecognised grain behaves like month rather than blowing up."""
    current, _ = ftq.windows_for_grain(
        'fortnight', date(2026, 8, 10), date(2026, 3, 25), date(2026, 7, 14))
    assert current['start'] == '2026-07-12'


# ---------------------------------------------------------------------------
# The wRC+ proxy
# ---------------------------------------------------------------------------

def test_woba_matches_hand_computed_linear_weights():
    """wOBA is the weighted numerator over (AB + uBB + SF + HBP)."""
    stat = _hitting(hits=250, doubles=50, triples=5, hr=30, bb=90, ibb=5,
                    hbp=10, sf=8, ab=900)
    singles = 250 - 50 - 5 - 30
    expected_num = (0.690 * 85 + 0.720 * 10 + 0.890 * singles
                    + 1.271 * 50 + 1.616 * 5 + 2.101 * 30)
    expected_den = 900 + 85 + 8 + 10
    assert ftq._woba(stat) == pytest.approx(expected_num / expected_den)


def test_woba_singles_and_walks_never_go_negative():
    """Malformed splits (more HR than hits) clamp instead of producing negatives."""
    numerator, _ = ftq.woba_parts(_hitting(hits=5, doubles=10, triples=10, hr=10,
                                           bb=2, ibb=9))
    assert numerator >= 0


def test_woba_is_zero_without_plate_appearances():
    """An empty split has no denominator to divide by."""
    assert ftq._woba({}) == 0.0


def test_league_average_team_scores_100():
    """A team identical to the league is exactly average by construction."""
    hitting = {147: _hitting(), 111: _hitting()}
    lg_woba, lg_r_pa = ftq.league_context(hitting)
    assert ftq.wrc_plus(_hitting(), lg_woba, lg_r_pa) == pytest.approx(100.0)


def test_better_offense_scores_above_100():
    """More extra-base hits on the same PA moves a team up the offense axis."""
    league = {147: _hitting(), 111: _hitting()}
    lg_woba, lg_r_pa = ftq.league_context(league)
    masher = _hitting(hr=60, hits=280, doubles=70)
    assert ftq.wrc_plus(masher, lg_woba, lg_r_pa) > 100.0
    assert ftq.wrc_plus(_hitting(hr=5, hits=190), lg_woba, lg_r_pa) < 100.0


def test_wrc_plus_defaults_to_average_without_league_context():
    """No league runs per PA (preseason) means everyone is nominally average."""
    assert ftq.wrc_plus(_hitting(), 0.320, 0.0) == 100.0


def test_league_context_is_zero_for_an_empty_league():
    """Guards the division when no team has batted yet."""
    assert ftq.league_context({}) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# ERA
# ---------------------------------------------------------------------------

def test_era_reads_the_pitching_split():
    """ERA comes from the API rather than being recomputed."""
    assert ftq._era(_pitching(era='3.71')) == 3.71


@pytest.mark.parametrize('stat', [
    {},                                             # nothing at all
    {'outs': 0, 'gamesPlayed': 0, 'era': '4.00'},   # hasn't pitched
    _pitching(innings='0.0'),                       # no innings to average over
])
def test_era_is_none_when_a_team_has_not_pitched(stat):
    """Teams without innings are dropped rather than plotted at ERA 0."""
    assert ftq._era(stat) is None


# ---------------------------------------------------------------------------
# Stats fetching and assembly
# ---------------------------------------------------------------------------

def test_fetch_team_stats_keys_by_team_id():
    """Splits collapse to {team_id: stat}."""
    payload = _stats_payload({147: _hitting(), 111: _hitting(runs=120)})
    with patch.object(ftq, '_get_json', return_value=payload):
        result = ftq.fetch_team_stats(2026, '2026-08-01', '2026-08-10', 'hitting')
    assert set(result) == {147, 111}
    assert result[111]['runs'] == 120


def test_fetch_team_stats_tolerates_an_empty_response():
    """A failed call yields no teams instead of raising."""
    with patch.object(ftq, '_get_json', return_value={}):
        assert ftq.fetch_team_stats(2026, 'a', 'b', 'hitting') == {}


def test_fetch_team_stats_skips_splits_without_a_team():
    """League-wide rows in the splits array are ignored."""
    payload = {'stats': [{'splits': [{'stat': _hitting()}]}]}
    with patch.object(ftq, '_get_json', return_value=payload):
        assert ftq.fetch_team_stats(2026, 'a', 'b', 'hitting') == {}


def test_coordinates_pair_offense_with_pitching():
    """Each team gets one (wRC+, ERA) point per window."""
    hitting = _stats_payload({147: _hitting(), 111: _hitting()})
    pitching = _stats_payload({147: _pitching('3.50'), 111: _pitching('4.50')})
    with patch.object(ftq, '_get_json', side_effect=[hitting, pitching]):
        points = ftq.coordinates_for_window(2026, ftq._window(date(2026, 8, 1),
                                                              date(2026, 8, 10)))
    assert points[147]['era'] == 3.50
    assert points[111]['era'] == 4.50
    assert points[147]['games'] == 30


def test_coordinates_drop_teams_missing_a_pitching_split():
    """A team with offense but no innings has no Y coordinate to plot."""
    hitting = _stats_payload({147: _hitting(), 111: _hitting()})
    pitching = _stats_payload({147: _pitching('3.50')})
    with patch.object(ftq, '_get_json', side_effect=[hitting, pitching]):
        points = ftq.coordinates_for_window(2026, ftq._window(date(2026, 8, 1),
                                                              date(2026, 8, 10)))
    assert set(points) == {147}


def test_coordinates_are_empty_when_either_group_fails():
    """Half a dataset is not plottable."""
    hitting = _stats_payload({147: _hitting()})
    with patch.object(ftq, '_get_json', side_effect=[hitting, {}]):
        assert ftq.coordinates_for_window(2026, ftq._window(date(2026, 8, 1),
                                                            date(2026, 8, 10))) == {}


def test_fetch_team_list_maps_ids_to_abbreviations():
    """Team metadata is keyed by the same integer ids as the stat splits."""
    payload = {'teams': [{'id': 147, 'abbreviation': 'NYY', 'teamName': 'Yankees'},
                         {'abbreviation': 'XXX'}]}
    with patch.object(ftq, '_get_json', return_value=payload):
        teams = ftq.fetch_team_list()
    assert teams == {147: {'abbr': 'NYY', 'name': 'Yankees'}}


def test_build_grain_attaches_baseline_coordinates():
    """Every team carries both endpoints of its arrow plus the league means."""
    now = {147: {'wrc': 110.0, 'era': 3.5, 'games': 30},
           111: {'wrc': 90.0, 'era': 4.5, 'games': 30}}
    was = {147: {'wrc': 100.0, 'era': 4.0, 'games': 90}}
    teams = {147: {'abbr': 'NYY', 'name': 'Yankees'},
             111: {'abbr': 'BOS', 'name': 'Red Sox'}}
    with patch.object(ftq, 'coordinates_for_window', side_effect=[now, was]):
        payload = ftq.build_grain(2026, 'month', date(2026, 8, 10),
                                  date(2026, 3, 25), date(2026, 7, 14), teams)

    assert payload['label'] == 'LAST 30 DAYS'
    assert payload['avg'] == {'wrc': 100.0, 'era': 4.0}
    by_abbr = {t['abbr']: t for t in payload['teams']}
    assert by_abbr['NYY']['was_wrc'] == 100.0
    # No baseline row for Boston — the view simply draws no arrow.
    assert by_abbr['BOS']['was_wrc'] is None and by_abbr['BOS']['was_era'] is None


def test_build_grain_returns_none_without_current_data():
    """A grain with no current window is skipped rather than half-built."""
    with patch.object(ftq, 'coordinates_for_window', return_value={}):
        assert ftq.build_grain(2026, 'week', date(2026, 8, 10), date(2026, 3, 25),
                               date(2026, 7, 14), {}) is None


def test_build_grain_labels_unknown_grains():
    """An unnamed grain still gets a printable label."""
    now = {147: {'wrc': 100.0, 'era': 4.0, 'games': 5}}
    with patch.object(ftq, 'coordinates_for_window', side_effect=[now, {}]):
        payload = ftq.build_grain(2026, 'fortnight', date(2026, 8, 10),
                                  date(2026, 3, 25), date(2026, 7, 14), {})
    assert payload['label'] == 'FORTNIGHT'
    assert payload['teams'][0]['abbr'] == '147'


def test_average_of_nothing_is_zero():
    """Guards the mean when a grain somehow has no teams."""
    assert ftq._average([]) == 0.0


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------

def test_cache_is_fresh_within_the_ttl():
    """Same date and recent enough — no refetch."""
    cached = {'date': '2026-08-10',
              'generated': datetime.now().isoformat(timespec='seconds')}
    assert ftq._cache_is_fresh(cached, '2026-08-10') is True


@pytest.mark.parametrize('cached', [
    None,
    {},
    {'date': '2026-08-09', 'generated': datetime.now().isoformat()},   # yesterday
    {'date': '2026-08-10', 'generated': 'not-a-timestamp'},
    {'date': '2026-08-10'},
])
def test_cache_is_stale(cached):
    """Missing, day-old, or unparseable cache entries all force a refetch."""
    assert ftq._cache_is_fresh(cached, '2026-08-10') is False


def test_cache_expires_after_the_ttl():
    """A cache written this morning goes stale by evening."""
    old = (datetime.now() - timedelta(hours=ftq._CACHE_TTL_HOURS + 1)).isoformat()
    assert ftq._cache_is_fresh({'date': '2026-08-10', 'generated': old},
                               '2026-08-10') is False


# ---------------------------------------------------------------------------
# Top-level fetch
# ---------------------------------------------------------------------------

def test_fetch_returns_cache_without_touching_the_network():
    """A fresh cache short-circuits every API call."""
    cached = {'date': '2026-08-10', 'grains': {'season': {}},
              'generated': datetime.now().isoformat(timespec='seconds')}
    with patch.object(ftq, 'load_json_file', return_value=cached), \
         patch.object(ftq, '_get_json') as get_json:
        result = ftq.fetch_team_quadrant(today=date(2026, 8, 10))
    assert result is cached
    get_json.assert_not_called()


def test_fetch_refuses_before_opening_day():
    """Preseason has no date-ranged splits to plot."""
    with patch.object(ftq, 'load_json_file', return_value={}), \
         patch.object(ftq, 'fetch_season_dates',
                      return_value=(date(2026, 3, 25), date(2026, 7, 14))), \
         patch.object(ftq, 'build_grain') as build:
        assert ftq.fetch_team_quadrant(today=date(2026, 2, 1)) == {}
    build.assert_not_called()


def test_fetch_keeps_previous_cache_when_every_grain_fails():
    """A bad API day must not overwrite good data with nothing."""
    cached = {'date': '2026-08-09', 'grains': {'season': {}}}
    with patch.object(ftq, 'load_json_file', return_value=cached), \
         patch.object(ftq, 'fetch_season_dates',
                      return_value=(date(2026, 3, 25), date(2026, 7, 14))), \
         patch.object(ftq, 'fetch_team_list', return_value={}), \
         patch.object(ftq, 'build_grain', return_value=None), \
         patch.object(ftq, 'save_off_results') as save:
        assert ftq.fetch_team_quadrant(today=date(2026, 8, 10)) is cached
    save.assert_not_called()


def test_fetch_saves_every_grain():
    """The happy path writes one payload per grain to the cache file."""
    grain_payload = {'label': 'X', 'current': {}, 'baseline': {}, 'avg': {}, 'teams': []}
    with patch.object(ftq, 'load_json_file', return_value={}), \
         patch.object(ftq, 'fetch_season_dates',
                      return_value=(date(2026, 3, 25), date(2026, 7, 14))), \
         patch.object(ftq, 'fetch_team_list', return_value={}), \
         patch.object(ftq, 'build_grain', return_value=grain_payload), \
         patch.object(ftq, 'save_off_results') as save:
        result = ftq.fetch_team_quadrant(today=date(2026, 8, 10), force=True)

    assert set(result['grains']) == set(ftq.GRAINS)
    assert result['season'] == 2026 and result['date'] == '2026-08-10'
    save.assert_called_once()


def test_fetch_infers_the_season_from_the_date():
    """Season defaults to the year of the day being fetched."""
    with patch.object(ftq, 'load_json_file', return_value={}), \
         patch.object(ftq, 'fetch_season_dates',
                      return_value=(date(2025, 3, 27), date(2025, 7, 15))) as dates, \
         patch.object(ftq, 'fetch_team_list', return_value={}), \
         patch.object(ftq, 'build_grain', return_value=None):
        ftq.fetch_team_quadrant(today=date(2025, 9, 1), force=True)
    dates.assert_called_once_with(2025)


# ---------------------------------------------------------------------------
# HTTP seam and CLI
# ---------------------------------------------------------------------------

def test_get_json_returns_empty_on_a_bad_status():
    """Non-200s are logged and swallowed."""
    class _Response:
        status_code = 500

        def json(self):
            """Never reached."""
            return {'unused': True}

    with patch.object(ftq.requests, 'get', return_value=_Response()):
        assert ftq._get_json('http://example.invalid') == {}


def test_get_json_returns_empty_on_a_transport_error():
    """Network failures never propagate out of the fetch layer."""
    with patch.object(ftq.requests, 'get', side_effect=OSError('down')):
        assert ftq._get_json('http://example.invalid') == {}


def test_get_json_returns_parsed_body():
    """The happy path hands back decoded JSON."""
    class _Response:
        status_code = 200

        def json(self):
            """Decoded body."""
            return {'ok': True}

    with patch.object(ftq.requests, 'get', return_value=_Response()):
        assert ftq._get_json('http://example.invalid') == {'ok': True}


def test_cli_prints_the_window_of_each_grain(capsys):
    """`python src/fetch_team_quadrant.py --date ...` summarises what it fetched."""
    payload = {'grains': {'week': {'current': {'label': '8/4 - 8/10'}}}}
    with patch.object(ftq, 'fetch_team_quadrant', return_value=payload), \
         patch('sys.argv', ['fetch_team_quadrant.py', '--date', '2026-08-10', '--force']):
        ftq.main()
    assert '8/4 - 8/10' in capsys.readouterr().out


def test_cli_is_quiet_when_the_fetch_yields_nothing():
    """No payload, no summary — and no traceback."""
    with patch.object(ftq, 'fetch_team_quadrant', return_value={}), \
         patch('sys.argv', ['fetch_team_quadrant.py']):
        ftq.main()
