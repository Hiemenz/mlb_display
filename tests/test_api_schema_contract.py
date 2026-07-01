"""MLB API schema-contract tests.

The existing test_api_contract.py checks that parse_games() transforms
*synthetic* API dicts correctly. That can't catch upstream drift, because the
synthetic fixtures move with the code.

This module does the opposite: it pins the exact nested fields our fetch code
depends on against a *recorded real* MLB API response (tests/fixtures/). If MLB
renames or drops one of these — the class of break behind commits like
"batch-fetch ERA since MLB API dropped note field" and "fields param must
include gameDurationMinutes" — these tests fail loudly instead of the field
silently going blank in production.

The recorded fixtures are frozen, so on their own they enforce the
request↔parse contract rather than detecting live drift. The `live` tests
(opt-in: `pytest -m live`) hit the real API to catch drift; wire them to a
schedule rather than every PR so CI stays offline and deterministic.
"""
import json
import os

import pytest
import requests

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')

# The exact hydrate params src/fetch_games.py sends. Kept here so the live
# tests request the same shape the code does — if the code changes what it
# asks for, this must change too.
SCHEDULE_HYDRATE = (
    'decisions,probablePitcher(note),linescore,flags,team,'
    'broadcasts(all),seriesStatus,gameInfo'
)
SCHEDULE_URL = 'https://statsapi.mlb.com/api/v1/schedule'
PEOPLE_URL = 'https://statsapi.mlb.com/api/v1/people'


def _get(obj, path):
    """Walk a dotted path (dict keys only); return (found, value)."""
    cur = obj
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


# --- Contract: what parse_games() reads off each schedule game ---------------
# Paths relative to a single game dict. Every FINAL game must carry these; if
# MLB drops one, the corresponding column on the scoreboard goes blank.
REQUIRED_GAME_FIELDS = [
    'gamePk',
    'gameDate',
    'gameType',
    'status.detailedState',
    'status.abstractGameState',
    'teams.away.team.id',
    'teams.away.team.abbreviation',
    'teams.away.leagueRecord.wins',
    'teams.away.leagueRecord.losses',
    'teams.home.team.id',
    'teams.home.team.abbreviation',
    'linescore.currentInning',
    'linescore.inningState',
    'linescore.teams.away.runs',
    'linescore.teams.home.runs',
]

# Fields the code depends on specifically for completed games. gameDurationMinutes
# and the decisions block are the two that have broken before.
REQUIRED_FINAL_GAME_FIELDS = [
    'gameInfo.gameDurationMinutes',
    'decisions.winner.id',
    'decisions.loser.id',
]


def _load_fixture(name):
    path = os.path.join(FIXTURE_DIR, name)
    if not os.path.exists(path):
        pytest.skip(f'fixture {name} not present')
    with open(path) as f:
        return json.load(f)


def _schedule_games(data):
    dates = data.get('dates', [])
    assert dates, 'schedule response has no dates[]'
    games = dates[0].get('games', [])
    assert games, 'schedule response date has no games[]'
    return games


@pytest.fixture(scope='module')
def games():
    return _schedule_games(_load_fixture('schedule_mlb_2025-07-18.json'))


@pytest.fixture(scope='module')
def stat():
    data = _load_fixture('people_era_2025.json')
    people = data.get('people', [])
    assert people, 'people[] missing'
    stats = people[0].get('stats', [])
    assert stats, 'people[].stats[] missing'
    splits = stats[0].get('splits', [])
    assert splits, 'people[].stats[].splits[] missing'
    return splits[0].get('stat', {})


class TestScheduleContractFixture:
    """Assert the recorded schedule response carries every field we parse."""

    @pytest.mark.parametrize('path', REQUIRED_GAME_FIELDS)
    def test_every_game_has_field(self, games, path):
        missing = [g.get('gamePk') for g in games if not _get(g, path)[0]]
        assert not missing, f'{path} missing from games {missing}'

    @pytest.mark.parametrize('path', REQUIRED_FINAL_GAME_FIELDS)
    def test_every_final_game_has_field(self, games, path):
        finals = [g for g in games
                  if g.get('status', {}).get('abstractGameState') == 'Final']
        assert finals, 'fixture has no Final games to check'
        missing = [g.get('gamePk') for g in finals if not _get(g, path)[0]]
        assert not missing, f'{path} missing from final games {missing}'

    def test_game_duration_is_numeric(self, games):
        for g in games:
            found, val = _get(g, 'gameInfo.gameDurationMinutes')
            if found:
                assert isinstance(val, int), (
                    f'gameDurationMinutes should be int, got {type(val).__name__}'
                )


class TestEraEndpointContractFixture:
    """Assert the people/stats endpoint (the ERA source that replaced the
    dropped probablePitcher note) still exposes era/wins/losses."""

    @pytest.mark.parametrize('key', ['era', 'wins', 'losses'])
    def test_stat_field_present(self, stat, key):
        assert key in stat, f'season pitching stat dropped {key!r}'


# --- Live drift detection (opt-in: `pytest -m live`) -------------------------
# Not collected by default. Point a scheduled job at these so upstream drift
# surfaces without making PR CI depend on the network or on there being games.
LIVE = os.environ.get('MLB_LIVE_CONTRACT') == '1'


@pytest.mark.live
@pytest.mark.skipif(not LIVE, reason='set MLB_LIVE_CONTRACT=1 to run live API checks')
class TestScheduleContractLive:
    def test_recent_final_day_matches_contract(self):
        # A fixed past date guarantees a completed slate regardless of when this runs.
        params = {
            'startDate': '2025-07-18', 'endDate': '2025-07-18',
            'sportId': 1, 'hydrate': SCHEDULE_HYDRATE,
        }
        resp = requests.get(SCHEDULE_URL, params=params, timeout=20)
        resp.raise_for_status()
        games = _schedule_games(resp.json())
        finals = [g for g in games
                  if g.get('status', {}).get('abstractGameState') == 'Final']
        assert finals, 'no final games returned by live API'
        for path in REQUIRED_GAME_FIELDS:
            assert all(_get(g, path)[0] for g in games), f'live: {path} missing'
        for path in REQUIRED_FINAL_GAME_FIELDS:
            assert all(_get(g, path)[0] for g in finals), f'live: {path} missing'
