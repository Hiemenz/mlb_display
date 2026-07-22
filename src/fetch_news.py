"""
Fetch recent MLB news headlines and cache to data/news.json.

Source is ESPN's public MLB news endpoint (no API key). When a primary team
is given and team_only is set, headlines are filtered to that team using the
full team name already cached in data/standings.json (so no hard-coded
nickname table is needed); if fewer than a handful of team-specific stories
are found, it falls back to league-wide headlines.

Standalone CLI:
    python src/fetch_news.py [--team NYY] [--all]
"""
import os
import sys
import time
import argparse

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util import save_off_results, load_json_file

_NEWS_URL = 'https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/news?limit=40'
_CACHE_TTL_HOURS = 6
_TOP_N = 15
_MIN_TEAM_HITS = 3   # below this, fall back to league-wide headlines


def _primary_full_name(primary_abbr):
    """Full team name for an abbreviation (e.g. NYY → 'New York Yankees'),
    read from the cached standings, or None if unavailable."""
    standings = load_json_file('standings.json')
    abbr_map = standings.get('team_abbreviation', {})
    target_id = next((tid for tid, ab in abbr_map.items() if ab == primary_abbr), None)
    if target_id is None:
        return None
    for teams in standings.get('standings', {}).values():
        for team in teams:
            if str(team.get('team_id')) == str(target_id):
                return team.get('team_name')
    return None


def _article_team_names(article):
    """Team names referenced by an article's categories, lowercased."""
    names = []
    for cat in article.get('categories', []) or []:
        if cat.get('type') == 'team':
            desc = cat.get('description') or (cat.get('team') or {}).get('description')
            if desc:
                names.append(desc.lower())
    return names


def _mentions_team(article, nickname, full_name):
    """True if the article headline or its team tags reference the team."""
    hl = (article.get('headline') or '').lower()
    if nickname and nickname in hl:
        return True
    full_l = full_name.lower() if full_name else None
    for name in _article_team_names(article):
        if nickname and nickname in name:
            return True
        if full_l and full_l in name:
            return True
    return False


def fetch_news(primary_abbr=None, team_only=True, force=False):
    """Fetch recent MLB headlines and cache to data/news.json.

    force=True bypasses this function's own TTL cache (the caller makes its
    own refresh-worthiness decision upstream).

    Returns the cached dict (possibly stale) or {} on total failure.
    """
    scope = primary_abbr if (team_only and primary_abbr) else None

    cached = load_json_file('news.json')
    if cached and not force:
        age_h = (time.time() - cached.get('fetched_at', 0)) / 3600
        if age_h < _CACHE_TTL_HOURS and cached.get('team') == scope:
            print(f"News cache fresh ({age_h:.1f}h old) — skipping fetch")
            return cached

    print(f"Fetching MLB news (scope={scope or 'league-wide'})...")
    try:
        resp = requests.get(_NEWS_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        articles = []
        for art in data.get('articles', []):
            headline = (art.get('headline') or '').strip()
            if headline:
                articles.append({'article': art, 'headline': headline,
                                 'published': art.get('published', '')})

        selected = articles
        if scope:
            full = _primary_full_name(primary_abbr)
            nickname = full.split()[-1].lower() if full else primary_abbr.lower()
            hits = [a for a in articles if _mentions_team(a['article'], nickname, full)]
            if len(hits) >= _MIN_TEAM_HITS:
                selected = hits

        result = {
            'fetched_at': time.time(),
            'team': scope,
            'articles': [{'headline': a['headline'], 'published': a['published']}
                         for a in selected[:_TOP_N]],
        }
        save_off_results(result, 'news')
        print(f"News fetched: {len(result['articles'])} headlines")
        return result
    except Exception as e:
        print(f"Warning: news fetch failed: {e}")
        return cached or {}


def main():  # pragma: no cover
    """CLI entry point: fetch MLB news headlines and write to data/news.json."""
    parser = argparse.ArgumentParser(description='Fetch recent MLB news headlines')
    parser.add_argument('--team', help='Primary team abbreviation to filter to, e.g. NYY')
    parser.add_argument('--all', action='store_true', help='League-wide headlines (no team filter)')
    args = parser.parse_args()

    result = fetch_news(primary_abbr=args.team, team_only=not args.all)
    for a in result.get('articles', []):
        print(f"  • {a['headline']}")


if __name__ == '__main__':  # pragma: no cover
    main()
