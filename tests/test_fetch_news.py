"""Tests for fetch_news.fetch_news and helpers."""
import time
from unittest.mock import patch, MagicMock

import pytest

import fetch_news
from fetch_news import (
    fetch_news as _fetch_news,
    _primary_full_name,
    _article_team_names,
    _mentions_team,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resp(status_code=200, json_data=None):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data or {}
    m.raise_for_status = MagicMock()
    if status_code != 200:
        m.raise_for_status.side_effect = Exception(f'HTTP {status_code}')
    return m


def _article(headline='Yankees win big', teams=None):
    """Build a minimal ESPN article dict."""
    cats = []
    for name in (teams or []):
        cats.append({'type': 'team', 'description': name})
    return {'headline': headline, 'published': '2026-07-01T00:00:00Z', 'categories': cats}


_SAMPLE_STANDINGS = {
    'team_abbreviation': {'147': 'NYY', '111': 'BOS'},
    'standings': {
        'American League East': [
            {'team_id': 147, 'team_name': 'New York Yankees'},
            {'team_id': 111, 'team_name': 'Boston Red Sox'},
        ]
    },
}

_ESPN_PAYLOAD = {
    'articles': [
        _article('Yankees crush Red Sox'),
        _article('Yankees sign reliever', teams=['New York Yankees']),
        _article('Red Sox lose starter', teams=['Boston Red Sox']),
        _article('League news item'),
    ]
}


# ---------------------------------------------------------------------------
# _primary_full_name
# ---------------------------------------------------------------------------

class TestPrimaryFullName:
    def test_returns_full_name_for_known_abbr(self):
        with patch('fetch_news.load_json_file', return_value=_SAMPLE_STANDINGS):
            assert _primary_full_name('NYY') == 'New York Yankees'

    def test_returns_none_for_unknown_abbr(self):
        with patch('fetch_news.load_json_file', return_value=_SAMPLE_STANDINGS):
            assert _primary_full_name('XYZ') is None

    def test_returns_none_when_standings_empty(self):
        with patch('fetch_news.load_json_file', return_value={}):
            assert _primary_full_name('NYY') is None

    def test_returns_none_when_team_id_missing_from_standings(self):
        standings = {
            'team_abbreviation': {'147': 'NYY'},
            'standings': {'AL East': []},
        }
        with patch('fetch_news.load_json_file', return_value=standings):
            assert _primary_full_name('NYY') is None


# ---------------------------------------------------------------------------
# _article_team_names
# ---------------------------------------------------------------------------

class TestArticleTeamNames:
    def test_extracts_description_field(self):
        art = {'categories': [{'type': 'team', 'description': 'New York Yankees'}]}
        assert 'new york yankees' in _article_team_names(art)

    def test_falls_back_to_team_description(self):
        art = {'categories': [{'type': 'team', 'team': {'description': 'Boston Red Sox'}}]}
        assert 'boston red sox' in _article_team_names(art)

    def test_ignores_non_team_categories(self):
        art = {'categories': [{'type': 'league', 'description': 'American League'}]}
        assert _article_team_names(art) == []

    def test_empty_categories_returns_empty(self):
        assert _article_team_names({}) == []
        assert _article_team_names({'categories': None}) == []

    def test_category_with_no_description_skipped(self):
        art = {'categories': [{'type': 'team'}]}
        assert _article_team_names(art) == []


# ---------------------------------------------------------------------------
# _mentions_team
# ---------------------------------------------------------------------------

class TestMentionsTeam:
    def test_headline_contains_nickname(self):
        art = _article('Yankees rout Cubs')
        assert _mentions_team(art, 'yankees', 'New York Yankees')

    def test_category_team_name_matches_nickname(self):
        art = _article('Big trade announced', teams=['New York Yankees'])
        assert _mentions_team(art, 'yankees', 'New York Yankees')

    def test_full_name_in_category_matches(self):
        art = _article('Trade rumor', teams=['New York Yankees'])
        assert _mentions_team(art, None, 'New York Yankees')

    def test_no_match_returns_false(self):
        art = _article('Cubs lose', teams=['Chicago Cubs'])
        assert not _mentions_team(art, 'yankees', 'New York Yankees')

    def test_none_nickname_skips_nickname_check(self):
        art = _article('No team headline')
        assert not _mentions_team(art, None, 'New York Yankees')


# ---------------------------------------------------------------------------
# fetch_news — cache path
# ---------------------------------------------------------------------------

class TestFetchNewsCache:
    def test_returns_cache_when_fresh_and_same_scope(self):
        cached = {
            'fetched_at': time.time() - 100,
            'team': 'NYY',
            'articles': [{'headline': 'cached', 'published': ''}],
        }
        with patch('fetch_news.load_json_file', return_value=cached), \
             patch('fetch_news.requests.get') as mock_get:
            result = _fetch_news(primary_abbr='NYY', team_only=True)
        mock_get.assert_not_called()
        assert result['articles'][0]['headline'] == 'cached'

    def test_bypasses_cache_when_force(self):
        cached = {'fetched_at': time.time() - 100, 'team': 'NYY', 'articles': []}
        with patch('fetch_news.load_json_file', return_value=cached), \
             patch('fetch_news.requests.get', return_value=_resp(json_data=_ESPN_PAYLOAD)) as mock_get, \
             patch('fetch_news.save_off_results'):
            _fetch_news(primary_abbr='NYY', team_only=True, force=True)
        mock_get.assert_called_once()

    def test_bypasses_cache_when_scope_changed(self):
        cached = {'fetched_at': time.time() - 100, 'team': 'BOS', 'articles': []}
        with patch('fetch_news.load_json_file', return_value=cached), \
             patch('fetch_news.requests.get', return_value=_resp(json_data=_ESPN_PAYLOAD)), \
             patch('fetch_news.save_off_results'):
            result = _fetch_news(primary_abbr='NYY', team_only=True, force=False)
        assert result is not None

    def test_bypasses_cache_when_stale(self):
        cached = {'fetched_at': time.time() - 25 * 3600, 'team': 'NYY', 'articles': []}
        with patch('fetch_news.load_json_file', return_value=cached), \
             patch('fetch_news.requests.get', return_value=_resp(json_data=_ESPN_PAYLOAD)), \
             patch('fetch_news.save_off_results'):
            result = _fetch_news(primary_abbr='NYY', team_only=True)
        assert result is not None


# ---------------------------------------------------------------------------
# fetch_news — network path
# ---------------------------------------------------------------------------

class TestFetchNewsNetwork:
    def _patch_standings(self):
        return patch('fetch_news.load_json_file', side_effect=lambda name: (
            _SAMPLE_STANDINGS if name == 'standings.json' else {}
        ))

    def test_league_wide_when_no_primary(self):
        with patch('fetch_news.load_json_file', return_value={}), \
             patch('fetch_news.requests.get', return_value=_resp(json_data=_ESPN_PAYLOAD)), \
             patch('fetch_news.save_off_results') as mock_save:
            result = _fetch_news(primary_abbr=None)
        assert result['team'] is None
        assert len(result['articles']) == 4
        mock_save.assert_called_once()

    def test_team_filter_applied_when_enough_hits(self):
        payload = {
            'articles': [
                _article('Yankees win 1', teams=['New York Yankees']),
                _article('Yankees win 2', teams=['New York Yankees']),
                _article('Yankees win 3', teams=['New York Yankees']),
                _article('League news'),
            ]
        }
        with self._patch_standings(), \
             patch('fetch_news.requests.get', return_value=_resp(json_data=payload)), \
             patch('fetch_news.save_off_results'):
            result = _fetch_news(primary_abbr='NYY', team_only=True)
        assert all('Yankees' in a['headline'] for a in result['articles'])

    def test_falls_back_to_league_when_too_few_team_hits(self):
        payload = {
            'articles': [
                _article('Yankees blurb', teams=['New York Yankees']),
                _article('League-wide 1'),
                _article('League-wide 2'),
            ]
        }
        with self._patch_standings(), \
             patch('fetch_news.requests.get', return_value=_resp(json_data=payload)), \
             patch('fetch_news.save_off_results'):
            result = _fetch_news(primary_abbr='NYY', team_only=True)
        assert len(result['articles']) == 3  # league-wide, not filtered

    def test_network_exception_returns_cached(self):
        cached = {'fetched_at': 0.0, 'team': None, 'articles': [{'headline': 'old'}]}
        with patch('fetch_news.load_json_file', return_value=cached), \
             patch('fetch_news.requests.get', side_effect=OSError('timeout')):
            result = _fetch_news(primary_abbr=None)
        assert result['articles'][0]['headline'] == 'old'

    def test_network_exception_with_no_cache_returns_empty(self):
        with patch('fetch_news.load_json_file', return_value={}), \
             patch('fetch_news.requests.get', side_effect=OSError('timeout')):
            result = _fetch_news(primary_abbr=None)
        assert result == {}

    def test_blank_headlines_excluded(self):
        payload = {
            'articles': [
                {'headline': '   ', 'published': '', 'categories': []},
                _article('Real headline'),
            ]
        }
        with patch('fetch_news.load_json_file', return_value={}), \
             patch('fetch_news.requests.get', return_value=_resp(json_data=payload)), \
             patch('fetch_news.save_off_results'):
            result = _fetch_news()
        assert len(result['articles']) == 1

    def test_result_has_fetched_at(self):
        with patch('fetch_news.load_json_file', return_value={}), \
             patch('fetch_news.requests.get', return_value=_resp(json_data=_ESPN_PAYLOAD)), \
             patch('fetch_news.save_off_results'):
            result = _fetch_news()
        assert 'fetched_at' in result
        assert isinstance(result['fetched_at'], float)

    def test_top_n_limit_applied(self):
        payload = {'articles': [_article(f'Story {i}') for i in range(30)]}
        with patch('fetch_news.load_json_file', return_value={}), \
             patch('fetch_news.requests.get', return_value=_resp(json_data=payload)), \
             patch('fetch_news.save_off_results'):
            result = _fetch_news()
        assert len(result['articles']) <= fetch_news._TOP_N

    def test_full_name_none_falls_back_to_abbr_nickname(self):
        payload = {
            'articles': [
                _article('NYY win', teams=['NYY']),
                _article('NYY sign player', teams=['NYY']),
                _article('NYY dominant', teams=['NYY']),
                _article('League news'),
            ]
        }
        # standings has no data → _primary_full_name returns None
        with patch('fetch_news.load_json_file', return_value={}), \
             patch('fetch_news.requests.get', return_value=_resp(json_data=payload)), \
             patch('fetch_news.save_off_results'):
            result = _fetch_news(primary_abbr='NYY', team_only=True)
        assert result is not None
