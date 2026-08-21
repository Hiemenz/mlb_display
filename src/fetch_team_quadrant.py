"""
Fetch team offense-vs-pitching quadrant data and cache to data/team_quadrant.json.

Each team gets two coordinates per grain: where they sit *now* (the grain's
window) and where they sat over the baseline window. The view draws an arrow
from baseline to now, so the chart shows which direction a team is coming from.

Grains and their baselines:
    season  regular-season start → today, arrow from the first half
    month   trailing 30 days,             arrow from season-to-date
    week    trailing 15 days,             arrow from season-to-date

The X axis is a wRC+ *proxy*. FanGraphs' real wRC+ is not reachable from here
(their API rejects non-browser clients), so it is rebuilt from the raw counting
stats the MLB Stats API does expose: wOBA from linear weights, converted to
runs above average per PA, expressed against the league. The one input we
cannot reconstruct is park factors, so a team's number can drift a few points
from the published figure — COL high, SD/SEA low. It is labelled wRC+* to keep
that honest.

Standalone CLI:
    python src/fetch_team_quadrant.py [--season 2026] [--date 2026-08-10] [--force]
"""
import os
import sys
import json
import argparse
from datetime import datetime, timedelta

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util import save_off_results, load_json_file

_BASE_URL = 'https://statsapi.mlb.com/api/v1'
_CACHE_FILE = 'team_quadrant'
_CACHE_TTL_HOURS = 6
_TIMEOUT = 15

# wOBA linear weights (FanGraphs, recent-season averages). The absolute values
# matter far less than their ratios: wRC+ divides out to the league mean, so a
# weight set from a neighbouring season shifts the spread slightly, never the
# ordering.
_W_UBB = 0.690
_W_HBP = 0.720
_W_1B = 0.890
_W_2B = 1.271
_W_3B = 1.616
_W_HR = 2.101
# wOBA-to-runs divisor. Sets how wide the offense axis spreads; a wrong value
# compresses or stretches the plot without reordering it.
_WOBA_SCALE = 1.157

GRAINS = ('season', 'month', 'week')
_GRAIN_DAYS = {'month': 30, 'week': 15}
_GRAIN_LABEL = {'season': 'SEASON', 'month': 'LAST 30 DAYS', 'week': 'LAST 15 DAYS'}


def _num(value, default=0.0):
    """Parse an API stat value that may be a str, None, or a placeholder like '-.--'."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get_json(url, params=None):
    """GET a Stats API endpoint, returning {} on any failure."""
    try:
        response = requests.get(url, params=params, timeout=_TIMEOUT)
        if response.status_code != 200:
            print(f'Warning: {url} returned status {response.status_code}')
            return {}
        return response.json()
    except Exception as e:
        print(f'Error fetching {url}: {e}')
        return {}


def _fmt(date):
    """Date → 'YYYY-MM-DD' for the API."""
    return date.strftime('%Y-%m-%d')


def _short(date):
    """Date → 'M/D' for on-screen window labels."""
    return f'{date.month}/{date.day}'


def _parse(date_str):
    """'YYYY-MM-DD' → date, or None."""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def fetch_season_dates(season):
    """Return (regular_season_start, first_half_end) dates for the season.

    Falls back to March 1 / June 30 so a failed lookup still produces a chart
    rather than no chart at all.
    """
    data = _get_json(f'{_BASE_URL}/seasons', {'sportId': 1, 'season': season})
    entries = data.get('seasons') or [{}]
    entry = entries[0]
    start = _parse(entry.get('regularSeasonStartDate'))
    first_half_end = _parse(entry.get('lastDate1stHalf'))
    if start is None:
        start = datetime(int(season), 3, 1).date()
    if first_half_end is None:
        first_half_end = datetime(int(season), 6, 30).date()
    return start, first_half_end


def last_completed_day(today, season_start):
    """The most recent day whose games are all final — yesterday, not today.

    Today's games are in progress or unplayed, so including them mixes partial
    box scores into every window: a team that has played two innings shows up
    with two innings of ERA. Every window therefore ends here instead. Clamped
    so opening day still produces a (single-day) window rather than reaching
    back before the season.
    """
    return max(today - timedelta(days=1), season_start)


def _window(start, end):
    """A window dict: API-ready bounds plus the label the chart prints."""
    return {
        'start': _fmt(start),
        'end': _fmt(end),
        'label': f'{_short(start)} - {_short(end)}',
    }


def windows_for_grain(grain, today, season_start, first_half_end):
    """Return (current_window, baseline_window) for a grain.

    The two windows never overlap. For the trailing grains the baseline is the
    season *up to* the window, not the season to date: comparing the last seven
    days against a figure that already contains those seven days damps the very
    move the arrow exists to show, and the shorter the window the worse it gets.
    So the arrow reads "where they were before this stretch → where they are in
    it".

    Season is the exception, and deliberately: its current position is the whole
    season to date, because that is the view's entire point. It points back at
    the first half.
    """
    if grain == 'season':
        # Before the All-Star break there is no first half to point back from,
        # so split the elapsed season down the middle instead.
        split = first_half_end if first_half_end < today else (
            season_start + timedelta(days=(today - season_start).days // 2)
        )
        split = max(split, season_start)
        return _window(season_start, today), _window(season_start, split)

    days = _GRAIN_DAYS.get(grain, _GRAIN_DAYS['month'])
    start = max(today - timedelta(days=days - 1), season_start)
    # Everything before the window. Clamped so a window reaching back to opening
    # day still yields a (single-day) baseline rather than an inverted range.
    baseline_end = max(start - timedelta(days=1), season_start)
    return _window(start, today), _window(season_start, baseline_end)


def fetch_team_stats(season, start, end, group):
    """Return {team_id: stat_dict} for a date-ranged team split ('hitting'/'pitching')."""
    data = _get_json(f'{_BASE_URL}/teams/stats', {
        'season': season,
        'group': group,
        'stats': 'byDateRange',
        'startDate': start,
        'endDate': end,
        'sportIds': 1,
    })
    stats = data.get('stats') or []
    if not stats:
        return {}
    result = {}
    for split in stats[0].get('splits') or []:
        team_id = (split.get('team') or {}).get('id')
        if team_id is not None:
            result[int(team_id)] = split.get('stat') or {}
    return result


def woba_parts(stat):
    """Return (weighted_numerator, wOBA_denominator) for one hitting split."""
    hits = _num(stat.get('hits'))
    doubles = _num(stat.get('doubles'))
    triples = _num(stat.get('triples'))
    homers = _num(stat.get('homeRuns'))
    singles = max(hits - doubles - triples - homers, 0.0)
    walks = _num(stat.get('baseOnBalls'))
    intentional = _num(stat.get('intentionalWalks'))
    unintentional = max(walks - intentional, 0.0)
    hbp = _num(stat.get('hitByPitch'))
    sac_flies = _num(stat.get('sacFlies'))
    at_bats = _num(stat.get('atBats'))

    numerator = (_W_UBB * unintentional + _W_HBP * hbp + _W_1B * singles
                 + _W_2B * doubles + _W_3B * triples + _W_HR * homers)
    denominator = at_bats + unintentional + sac_flies + hbp
    return numerator, denominator


def _woba(stat):
    """wOBA for one hitting split (0.0 when the team has no plate appearances)."""
    numerator, denominator = woba_parts(stat)
    return numerator / denominator if denominator else 0.0


def league_context(hitting):
    """Return (league_wOBA, league_runs_per_PA) from every team's hitting split."""
    total_num = 0.0
    total_den = 0.0
    total_runs = 0.0
    total_pa = 0.0
    for stat in hitting.values():
        numerator, denominator = woba_parts(stat)
        total_num += numerator
        total_den += denominator
        total_runs += _num(stat.get('runs'))
        total_pa += _num(stat.get('plateAppearances'))
    lg_woba = total_num / total_den if total_den else 0.0
    lg_r_pa = total_runs / total_pa if total_pa else 0.0
    return lg_woba, lg_r_pa


def wrc_plus(stat, lg_woba, lg_r_pa):
    """wRC+ proxy for one hitting split: league-relative runs created per PA.

    wRAA/PA = (wOBA - lgwOBA) / wOBAScale, added to the league's runs per PA
    and expressed as a percentage of it. No park adjustment (see module docs).
    """
    if not lg_r_pa:
        return 100.0
    wraa_per_pa = (_woba(stat) - lg_woba) / _WOBA_SCALE
    return 100.0 * (wraa_per_pa + lg_r_pa) / lg_r_pa


def _era(stat):
    """ERA for one pitching split, or None when the team hasn't pitched."""
    if not _num(stat.get('outs')) and not _num(stat.get('gamesPlayed')):
        return None
    innings = _num(stat.get('inningsPitched'))
    if not innings:
        return None
    return round(_num(stat.get('era')), 3)


def coordinates_for_window(season, window):
    """Return {team_id: {'wrc': float, 'era': float, 'games': int}} for one window."""
    hitting = fetch_team_stats(season, window['start'], window['end'], 'hitting')
    pitching = fetch_team_stats(season, window['start'], window['end'], 'pitching')
    if not hitting or not pitching:
        return {}

    lg_woba, lg_r_pa = league_context(hitting)
    points = {}
    for team_id, stat in hitting.items():
        era = _era(pitching.get(team_id) or {})
        if era is None:
            continue
        points[team_id] = {
            'wrc': round(wrc_plus(stat, lg_woba, lg_r_pa), 1),
            'era': era,
            'games': int(_num(stat.get('gamesPlayed'))),
        }
    return points


def fetch_team_list():
    """Return {team_id: {'abbr','name'}} for the 30 MLB clubs."""
    data = _get_json(f'{_BASE_URL}/teams', {
        'sportId': 1,
        'fields': 'teams,id,abbreviation,teamName',
    })
    return {
        int(team['id']): {
            'abbr': team.get('abbreviation', ''),
            'name': team.get('teamName', ''),
        }
        for team in data.get('teams') or []
        if team.get('id') is not None
    }


def _average(values):
    """Mean of a list, or 0.0 when empty."""
    return sum(values) / len(values) if values else 0.0


def build_grain(season, grain, today, season_start, first_half_end, teams):
    """Assemble one grain's payload: both windows, every team's arrow, league means."""
    current, baseline = windows_for_grain(grain, today, season_start, first_half_end)
    now_points = coordinates_for_window(season, current)
    if not now_points:
        return None
    was_points = coordinates_for_window(season, baseline)

    entries = []
    for team_id, point in sorted(now_points.items()):
        info = teams.get(team_id, {})
        was = was_points.get(team_id)
        entries.append({
            'id': team_id,
            'abbr': info.get('abbr', str(team_id)),
            'name': info.get('name', ''),
            'wrc': point['wrc'],
            'era': point['era'],
            'games': point['games'],
            'was_wrc': was['wrc'] if was else None,
            'was_era': was['era'] if was else None,
        })

    return {
        'label': _GRAIN_LABEL.get(grain, grain.upper()),
        'current': current,
        'baseline': baseline,
        'avg': {
            'wrc': round(_average([e['wrc'] for e in entries]), 1),
            'era': round(_average([e['era'] for e in entries]), 2),
        },
        'teams': entries,
    }


def _cache_is_fresh(cached, today_str):
    """True when the cache was written today's date and inside the TTL."""
    if not cached or cached.get('date') != today_str:
        return False
    generated = cached.get('generated')
    try:
        age = datetime.now() - datetime.fromisoformat(generated)
    except (TypeError, ValueError):
        return False
    return age < timedelta(hours=_CACHE_TTL_HOURS)


def fetch_team_quadrant(season=None, today=None, force=False):
    """Fetch every grain and cache to data/team_quadrant.json. Returns the payload."""
    today = today or datetime.now().date()
    season = int(season or today.year)
    today_str = _fmt(today)

    cached = load_json_file(f'{_CACHE_FILE}.json')
    if not force and _cache_is_fresh(cached, today_str):
        print('Team quadrant cache is fresh, skipping fetch')
        return cached

    season_start, first_half_end = fetch_season_dates(season)
    if today < season_start:
        print(f'Season {season} has not started yet ({season_start})')
        return cached or {}

    # Windows end on the last day whose games are final, never on today's
    # partial slate — see last_completed_day.
    as_of = last_completed_day(today, season_start)

    teams = fetch_team_list()
    grains = {}
    for grain in GRAINS:
        payload = build_grain(season, grain, as_of, season_start, first_half_end, teams)
        if payload:
            grains[grain] = payload
        else:
            print(f'Warning: no data for grain {grain}')

    if not grains:
        print('Team quadrant fetch produced no grains; keeping previous cache')
        return cached or {}

    result = {
        'season': season,
        'date': today_str,
        'as_of': _fmt(as_of),
        'generated': datetime.now().isoformat(timespec='seconds'),
        'grains': grains,
    }
    save_off_results(result, _CACHE_FILE)
    print(f'Saved team quadrant data for {len(grains)} grain(s) to data/{_CACHE_FILE}.json')
    return result


def main():
    """CLI entry point: fetch team quadrant data for every grain."""
    parser = argparse.ArgumentParser(
        description='Fetch team offense-vs-pitching quadrant data',
    )
    parser.add_argument('--season', type=int, default=None, help='Season year (default: current)')
    parser.add_argument('--date', type=str, default=None,
                        help='Treat this YYYY-MM-DD as "today" (default: actual today)')
    parser.add_argument('--force', action='store_true', help='Ignore the cache TTL')
    args = parser.parse_args()

    today = _parse(args.date) if args.date else None
    result = fetch_team_quadrant(season=args.season, today=today, force=args.force)
    if result:
        print(json.dumps({g: p['current']['label'] for g, p in result['grains'].items()}, indent=2))


if __name__ == '__main__':  # pragma: no cover
    main()
