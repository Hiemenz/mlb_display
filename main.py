"""
MLB Display — full pipeline orchestrator.

Usage:
    python main.py [--date YYYY-MM-DD] [--sport-id N] [--fetch-teams] [--local] [--config PATH]
"""
import sys
import os
import json
import platform
import argparse
import time
from datetime import datetime, timedelta, timezone

import pytz

# Ensure src/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config_loader import load_config, add_config_arg
from fetch_games import fetch_scoreboard_for_date, fetch_all_team_abbreviations, find_next_game_date, fetch_tomorrow_games, SPORT_NAMES
from fetch_leaders import fetch_leaders
from fetch_news import fetch_news
from fetch_derby import fetch_and_save_derby_bracket, get_derby_date
from render_scoreboard import render
from display import send_to_display
from util import load_json_file
from standings import get_standings, fetch_playoff_bracket, fetch_transactions, is_postseason_window
from image_box import set_historical_mode
from image_idle import draw_idle_screen


# ---------------------------------------------------------------------------
# Private helpers (night mode, Discord, smart polling) — stay in main.py only
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv():
    """Load .env file into os.environ if not already set. Existing env vars take priority."""
    env_path = os.path.join(_REPO_ROOT, '.env')
    try:
        with open(env_path) as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line or _line.startswith('#') or '=' not in _line:
                    continue
                _key, _, _val = _line.partition('=')
                _key = _key.strip()
                _val = _val.strip().strip('"').strip("'")
                if _key and _key not in os.environ:
                    os.environ[_key] = _val
    except FileNotFoundError:
        pass
    except Exception as _e:
        print(f"Warning: failed to load .env: {_e}")


_load_dotenv()


def _data_path(filename):
    """Data path."""
    return os.path.join(_REPO_ROOT, 'data', filename)


def _in_night_window(config):
    """Return True if we are currently inside the configured night mode window."""
    night_start = config.get('night_start', 0)
    night_end = config.get('night_end', 7)
    tz = config.get('timezone', 'America/Chicago')
    local_tz = pytz.timezone(tz)
    current_hour = datetime.now(local_tz).hour
    if night_start >= night_end:
        return current_hour >= night_start or current_hour < night_end
    return night_start <= current_hour < night_end


def _in_dark_window(config):
    """Return True when the display should be in dark mode (evening through morning).

    Driven by dark_start / dark_end config keys (default 20 → 7) so that the
    display colour scheme is independent of the refresh-suppression night window.
    Falls back to night_start / night_end if the dark_* keys are absent.
    """
    dark_start = config.get('dark_start', config.get('night_start', 20))
    dark_end = config.get('dark_end', config.get('night_end', 7))
    tz = config.get('timezone', 'America/Chicago')
    local_tz = pytz.timezone(tz)
    current_hour = datetime.now(local_tz).hour
    if dark_start >= dark_end:
        return current_hour >= dark_start or current_hour < dark_end
    return dark_start <= current_hour < dark_end


def _load_schedule_state():
    """Load schedule state."""
    path = _data_path('schedule_state.json')
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_schedule_state(state):
    """Save schedule state."""
    path = _data_path('schedule_state.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(state, f, indent=2)


_STANDINGS_FINAL_STATES = {'Final', 'Game Over', 'Final: Tied', 'Postponed', 'Completed Early'}
_VIDEO_FINAL_STATES = {'Final', 'Game Over', 'Final: Tied', 'Postponed', 'Completed Early'}


def _maybe_generate_video(date_str, config):
    """Generate an end-of-day timelapse once all games are final, if enabled in config."""
    if not config.get('auto_generate_video', False):
        return

    sentinel = _data_path(f'video_generated_{date_str}.done')
    if os.path.exists(sentinel):
        print(f"Video already generated for {date_str} — skipping")
        return

    try:
        games = load_json_file('games.json').get('games', [])
    except Exception:
        return

    if not games:
        return

    if not all(g.get('detailed_state') in _VIDEO_FINAL_STATES for g in games):
        return  # at least one game still in progress

    print(f"All games final — generating day timelapse for {date_str}...")
    try:
        from timelapse import generate_gif

        output_dir = os.path.join(_REPO_ROOT, 'output')
        os.makedirs(output_dir, exist_ok=True)
        gif_path = os.path.join(output_dir, f'scoreboard_{date_str}.gif')

        sport_priority = config.get('sport_id_priority', [1])
        sport_id = sport_priority[0] if isinstance(sport_priority, list) else sport_priority

        generate_gif(
            date_str,
            gif_start=None,
            gif_end=None,
            output_path=gif_path,
            interval_min=config.get('video_interval_min', 5),
            frame_delay_ms=config.get('video_frame_delay_ms', 300),
            sport_id=sport_id,
            config_data=config,
        )

        # Sentinel prevents this from running again today
        with open(sentinel, 'w') as _f:
            _f.write(datetime.now().isoformat())
        print(f"Timelapse saved to {gif_path}")
    except Exception as e:
        print(f"Video generation error: {e}")


_STANDINGS_MAX_AGE_HOURS = 20  # refresh if standings.json is older than this
_LEADERS_MAX_AGE_HOURS = 24    # refresh if leaders.json is older than this
_TRANSACTIONS_MAX_AGE_HOURS = 3  # refresh if transactions.json is older than this
_NEWS_MAX_AGE_HOURS = 6         # refresh if news.json is older than this
_PLAYOFF_BRACKET_MAX_AGE_HOURS = 1  # refresh cadence during an active postseason


def _should_refresh_leaders(sched, force=False):
    """Return True if leaders.json needs a refresh.

    Mirrors _should_refresh_standings: season stat leaders barely move
    mid-game, so we only refetch when the cache is missing/stale (catches
    the once-a-day / offline-for-a-day cases) or a game that is now Final
    wasn't Final during the last leaders refresh — i.e. once games wrap up.

    force=True (--full-refresh) always refreshes regardless of cache state.
    """
    if force:
        return True

    leaders_path = _data_path('leaders.json')
    if not os.path.exists(leaders_path):
        return True

    import time as _t
    age_hours = (_t.time() - os.path.getmtime(leaders_path)) / 3600
    if age_hours >= _LEADERS_MAX_AGE_HOURS:
        print(f"Leaders stale ({age_hours:.1f}h old) — refreshing")
        return True

    try:
        games = load_json_file('games.json').get('games', [])
    except Exception:
        return False
    current_finals = {
        str(g['game_pk']) for g in games
        if g.get('detailed_state') in _STANDINGS_FINAL_STATES and g.get('game_pk')
    }
    known_finals = set(sched.get('leaders_final_pks', []))
    return bool(current_finals - known_finals)


def _should_refresh_transactions(force=False):
    """Return True if transactions.json needs a refresh.

    Unlike standings/leaders, transactions aren't tied to games going Final —
    just a simple age check (missing or older than _TRANSACTIONS_MAX_AGE_HOURS).

    force=True (--full-refresh) always refreshes regardless of cache state.
    """
    if force:
        return True

    transactions_path = _data_path('transactions.json')
    if not os.path.exists(transactions_path):
        return True

    import time as _t
    age_hours = (_t.time() - os.path.getmtime(transactions_path)) / 3600
    if age_hours >= _TRANSACTIONS_MAX_AGE_HOURS:
        print(f"Transactions stale ({age_hours:.1f}h old) — refreshing")
        return True
    return False


def _should_refresh_news(force=False):
    """Return True if news.json needs a refresh (simple age check)."""
    if force:
        return True
    news_path = _data_path('news.json')
    if not os.path.exists(news_path):
        return True
    import time as _t
    age_hours = (_t.time() - os.path.getmtime(news_path)) / 3600
    if age_hours >= _NEWS_MAX_AGE_HOURS:
        print(f"News stale ({age_hours:.1f}h old) — refreshing")
        return True
    return False


def _should_refresh_playoff_bracket(force=False):
    """Return True if playoff_bracket.json needs a refresh.

    Simple age check — series win counts only change once per completed
    game, so hourly is frequent enough even during an active series.

    force=True (--full-refresh) always refreshes regardless of cache state.
    """
    if force:
        return True

    bracket_path = _data_path('playoff_bracket.json')
    if not os.path.exists(bracket_path):
        return True

    import time as _t
    age_hours = (_t.time() - os.path.getmtime(bracket_path)) / 3600
    if age_hours >= _PLAYOFF_BRACKET_MAX_AGE_HOURS:
        print(f"Playoff bracket stale ({age_hours:.1f}h old) — refreshing")
        return True
    return False


def _should_refresh_standings(sched, force=False):
    """Return True if standings.json needs a refresh.

    Triggers when: the file is missing, the file is older than 20 hours
    (catches the case where the program was offline for a day or more),
    or a game that is now Final was not Final during the last standings refresh.

    force=True (--full-refresh) always refreshes regardless of cache state.
    """
    if force:
        return True

    standings_path = _data_path('standings.json')
    if not os.path.exists(standings_path):
        return True

    import time as _t
    age_hours = (_t.time() - os.path.getmtime(standings_path)) / 3600
    if age_hours >= _STANDINGS_MAX_AGE_HOURS:
        print(f"Standings stale ({age_hours:.1f}h old) — refreshing")
        return True

    try:
        games = load_json_file('games.json').get('games', [])
    except Exception:
        return False
    current_finals = {
        str(g['game_pk']) for g in games
        if g.get('detailed_state') in _STANDINGS_FINAL_STATES and g.get('game_pk')
    }
    known_finals = set(sched.get('standings_final_pks', []))
    return bool(current_finals - known_finals)


def _should_skip_poll(date_str, config, sched):
    """Return (should_skip, reason_str) based on smart polling state."""
    next_game_date = sched.get('next_game_date')
    if next_game_date and next_game_date > date_str:
        return True, f"No games until {next_game_date} — skipping API call"

    # If the last fetch was for a different date, always fetch fresh data.
    if sched.get('last_fetch_date') and sched['last_fetch_date'] != date_str:
        return False, ""

    try:
        cached_games = load_json_file('games.json').get('games', [])
    except Exception:
        cached_games = []

    _final_states = {'Final', 'Game Over', 'Final: Tied', 'Postponed', 'Completed Early'}
    # Any game that has started (current_inning > 0) but isn't in a terminal state —
    # catches 'In Progress', rain delays, and any other mid-game API state.
    # 'Delayed' is intentionally excluded from _final_states so delayed games keep polling.
    any_live = any(
        g.get('detailed_state') not in _final_states and (g.get('current_inning') or 0) > 0
        for g in cached_games
    )
    all_done = bool(cached_games) and all(g.get('detailed_state') in _final_states for g in cached_games)

    # Final games that haven't received decisions yet (API lag after game ends)
    _final_no_decision_states = {'Final', 'Game Over', 'Final: Tied', 'Completed Early'}
    any_final_undecided = any(
        g.get('detailed_state') in _final_no_decision_states
        and g.get('winner_name') is None
        for g in cached_games
    )

    all_pregame = bool(cached_games) and all(
        g.get('detailed_state') in {'Scheduled', 'Pre-Game', 'Warmup'}
        for g in cached_games
    )

    # Doubleheader game 2 is pre-game while game 1 is already Final — poll every 5 min
    # so we catch the moment game 2 is live without waiting the full 15/60 min interval.
    _dh_game2_soon = any(
        g.get('double_header') in ('Y', 'S')
        and g.get('game_number') == 2
        and g.get('detailed_state') in {'Scheduled', 'Pre-Game', 'Warmup'}
        for g in cached_games
    )

    if any_final_undecided:
        interval_min = 2
    elif any_live:
        interval_min = config.get('live_game_interval', 1)
    elif _dh_game2_soon:
        interval_min = 5  # between DH games: check every 5 min for game 2 start
    elif all_done:
        interval_min = 60
    elif not cached_games or all_pregame:
        interval_min = 60
    else:
        interval_min = config.get('update_interval', 15)

    # When all games just became Final (cached state was live, now all_done), force one
    # immediate refresh so the display shows the clean final state without waiting 60 min.
    if all_done and not sched.get('all_done_refreshed'):
        return False, ""

    last_fetch = sched.get('last_game_fetch')
    if last_fetch:
        try:
            last_dt = datetime.fromisoformat(last_fetch)
            if last_dt.tzinfo is None:
                # State written before the UTC-aware format (pre-#202 files)
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            elapsed = datetime.now(timezone.utc) - last_dt
            if elapsed < timedelta(minutes=interval_min):
                mins = int(elapsed.total_seconds() // 60)
                state_label = (
                    'final_undecided' if any_final_undecided
                    else 'live' if any_live
                    else 'dh_between' if _dh_game2_soon
                    else 'all_done' if all_done
                    else 'pregame' if all_pregame
                    else 'mixed'
                )
                return True, f"Throttled — {mins}min since last fetch (interval={interval_min}min, state={state_label})"
        except Exception:
            pass

    return False, ""


_DERBY_LIVE_POLL_SECONDS = 60          # re-check every minute while the derby is actually in progress
_DERBY_LIVE_POLL_MAX_SECONDS = 3 * 60 * 60  # safety cap in case the API never reports "Final"


def _run_derby_mode(config, event_id=None, no_throttle=False, auto_open=False):
    """Fetch the live Derby bracket and render/display it, overriding display_mode.

    The rest of the day this runs once per invocation like every other mode
    (paced by cron, e.g. every 14 min — see README). But once the event's
    status flips to "In Progress" it blocks in a minute-by-minute poll loop
    right here so the display tracks the live bracket without waiting for
    the next cron tick, exiting once the derby is no longer in progress (or
    after a safety cap in case the API never reports "Final").
    """
    start = time.monotonic()
    while True:
        try:
            bracket = fetch_and_save_derby_bracket(event_id=event_id)
        except Exception as _derby_e:
            print(f"Warning: derby bracket fetch failed: {_derby_e}")
            bracket = None

        derby_config = dict(config, display_mode='derby')
        output_path = os.path.join(_REPO_ROOT, 'resulting_image.bmp')
        result = render(derby_config, output_path=output_path, bypass_cache=no_throttle)
        if result:
            image, changed_regions = result
            refresh_mode = send_to_display(output_path, changed_regions, force_full=no_throttle)
            print(f"Derby: {refresh_mode} refresh ({len(changed_regions)} region(s))")
            if auto_open:
                import subprocess
                subprocess.run(['open', output_path], check=False)
        else:
            print("No display update needed - image unchanged")

        if not bracket or bracket.get('state') != 'In Progress':
            break
        if time.monotonic() - start > _DERBY_LIVE_POLL_MAX_SECONDS:
            print("Derby live-poll safety cap reached — stopping (next cron tick will resume)")
            break
        print(f"Derby in progress — checking again in {_DERBY_LIVE_POLL_SECONDS}s")
        time.sleep(_DERBY_LIVE_POLL_SECONDS)


def _maybe_show_derby_bracket(config, no_throttle=False, auto_open=False):
    """When there are no games, check whether today is actually Derby day and show it.

    Returns True if today is Derby day (bracket fetched/rendered/displayed, or
    already up to date) so the caller can skip its normal "no games" handling.
    Returns False otherwise (auto_derby_mode disabled, lookup failed, or it's
    just not Derby day) so the caller falls back to normal no-game behavior.
    """
    if not config.get('auto_derby_mode', True):
        return False
    try:
        tz = config.get('timezone', 'America/Chicago')
        today_str = datetime.now(pytz.timezone(tz)).strftime('%Y-%m-%d')
        derby_date, derby_event_id = get_derby_date()
    except Exception as _derby_lookup_e:
        print(f"Warning: derby day auto-detection failed: {_derby_lookup_e}")
        return False
    if derby_date != today_str:
        return False
    print(f"No games today, but it's Derby day ({today_str}) — showing Home Run Derby bracket")
    _run_derby_mode(config, event_id=derby_event_id, no_throttle=no_throttle, auto_open=auto_open)
    return True


def _show_idle_screen(config, sched, auto_open=False):
    """Render and display the idle 'no games today' screen with recent transactions."""
    _is_dark = _in_dark_window(config) if config.get('night_mode', True) else False
    idle_config = dict(config, dark_mode=_is_dark)

    team_data = load_json_file('teams.json')
    if not team_data or 'team_abbreviation' not in team_data:
        team_data = {'team_abbreviation': {}}

    # Load transactions — fetch fresh if missing or older than 1 hour
    tx_data = load_json_file('transactions.json') or {}
    tx_age  = time.time() - tx_data.get('fetched_at', 0)
    if not tx_data.get('transactions') or tx_age > 3600:
        try:
            from standings import fetch_transactions
            tx_data = fetch_transactions(lookback_days=config.get('transactions_lookback_days', 3)) or tx_data
        except Exception as _e:
            print(f"Warning: idle transactions fetch failed: {_e}")
    transactions = tx_data.get('transactions', [])

    # Render
    image = draw_idle_screen(transactions, team_data, {}, idle_config)

    output_path = os.path.join(_REPO_ROOT, 'resulting_image.bmp')

    # Skip the push when the idle screen is pixel-identical to what's already
    # on disk — off-days hit this path on every cron tick, and an unconditional
    # force_full would flash the e-ink panel all day. Still let the hourly
    # full-refresh timer through for the anti-ghosting flash.
    from refresh_tracker import needs_full_refresh
    if not needs_full_refresh() and os.path.isfile(output_path):
        try:
            from PIL import Image as _PILImage, ImageChops as _ImageChops
            _prev = _PILImage.open(output_path)
            _unchanged = (
                _prev.size == image.size and
                _ImageChops.difference(_prev.convert('L'), image.convert('L')).getbbox() is None
            )
            if _unchanged:
                print("Idle screen unchanged — skipping display update")
                return
        except Exception:
            pass

    image.save(output_path)
    print(f"Idle screen saved → {output_path}")

    try:
        send_to_display(output_path, force_full=True)
    except Exception as _disp_e:
        print(f"Warning: display send failed: {_disp_e}")

    if auto_open:
        import subprocess
        subprocess.run(['open', output_path], check=False)


def _update_schedule_state(game_state_data, date_str, config, sched):
    """Update schedule state."""
    sched['last_game_fetch'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    sched['last_fetch_date'] = date_str
    if not game_state_data:
        priority = config.get('sport_id_priority', [1, 8, 16])
        tomorrow = (datetime.now().date() + timedelta(days=1)).strftime('%Y-%m-%d')
        next_date = find_next_game_date(priority, tomorrow)
        sched['next_game_date'] = next_date
        _save_schedule_state(sched)
        if next_date:
            print(f"No games today. Next games: {next_date}")
        return True  # signal: no games, caller should return early
    else:
        sched.pop('next_game_date', None)
        _final_states = {'Final', 'Game Over', 'Final: Tied', 'Postponed', 'Completed Early'}
        _all_done_now = all(g.get('detailed_state') in _final_states for g in game_state_data)
        # Don't mark all_done if a DH game 2 is still unplayed — game 2 might not have
        # appeared in the schedule yet, causing a false "all done" that would skip it.
        _dh_g1_final = any(
            g.get('double_header') in ('Y', 'S')
            and g.get('game_number') == 1
            and g.get('detailed_state') in _final_states
            for g in game_state_data
        )
        _dh_g2_present = any(g.get('game_number') == 2 for g in game_state_data)
        if _all_done_now and not (_dh_g1_final and not _dh_g2_present):
            sched['all_done_refreshed'] = True
        else:
            sched.pop('all_done_refreshed', None)
        _save_schedule_state(sched)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """CLI entry point: run the full fetch → render → display pipeline."""
    parser = argparse.ArgumentParser(
        description='MLB Display — fetch → render → display pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python main.py
  python main.py --date 2025-04-01
  python main.py --sport-id 8 --date 2023-03-21
  python main.py --local
  python main.py --full-refresh
        ''',
    )
    parser.add_argument('--date', type=str, help='Date (YYYY-MM-DD). Default: today')
    parser.add_argument('--sport-id', type=int, help='Sport ID override')
    parser.add_argument('--fetch-teams', action='store_true',
                        help='Fetch and cache all team abbreviations, then exit')
    parser.add_argument('--local', action='store_true',
                        help='Local dev mode: bypass night mode and smart polling, auto-open output')
    parser.add_argument('--full-refresh', action='store_true',
                        help='Bypass all throttling/staleness caches and force a fresh fetch of '
                             'games, standings, leaders, transactions, and the playoff bracket')
    add_config_arg(parser)
    args = parser.parse_args()

    system_platform = platform.system()
    print(f"Running on platform: {system_platform}")
    if system_platform == 'Darwin':
        print("Development mode - e-ink display updates will be skipped")

    def _env_is_test():
        """Env is test."""
        if os.environ.get('ENV', '').lower() == 'test':
            return True
        try:
            with open(os.path.join(_REPO_ROOT, '.env')) as _ef:
                for _line in _ef:
                    _line = _line.strip()
                    if _line.startswith('ENV=') or _line.startswith('ENV ='):
                        return _line.split('=', 1)[1].strip().strip('"').strip("'").lower() == 'test'
        except Exception:
            pass
        return False

    _is_test = _env_is_test()
    _no_throttle = args.local or args.full_refresh or system_platform == 'Darwin' or _is_test
    print(f"Throttle bypass: {_no_throttle} (local={args.local}, platform={system_platform}, env_test={_is_test})")

    config = load_config(args.config)

    # 3. Night mode gate (default True to match the dark-mode checks below)
    if config.get('night_mode', True) and not _no_throttle:
        if _in_night_window(config):
            tz = config.get('timezone', 'America/Chicago')
            now_str = datetime.now(pytz.timezone(tz)).strftime('%H:%M')
            print(f"Night mode: skipping refresh ({now_str})")
            return

    # Home Run Derby bracket mode: explicit manual override. Bypasses the normal
    # game-schedule pipeline entirely (there's no "game" to fetch/poll for).
    if config.get('display_mode') == 'derby':
        _run_derby_mode(config, event_id=None, no_throttle=_no_throttle,
                        auto_open=args.local and system_platform == 'Darwin')
        return

    league_mode = (os.environ.get('LEAGUE_MODE', '').lower().strip()
                   or config.get('league_mode', 'mlb'))

    # Handle --sport-id / --fetch-teams
    if args.sport_id:
        sport_id = args.sport_id
        print(f"Using specified sport: {SPORT_NAMES.get(sport_id, f'Sport ID {sport_id}')}")
        if sport_id == 11 and league_mode != 'aaa':
            league_mode = 'aaa'
            config['league_mode'] = 'aaa'
        if args.fetch_teams:
            fetch_all_team_abbreviations(sport_id)
            return
    elif league_mode == 'aaa':
        sport_id = 11
        print("League mode: AAA (Triple-A)")
        if args.fetch_teams:
            fetch_all_team_abbreviations(sport_id)
            return
    else:
        sport_id_priority = config.get('sport_id_priority')
        if sport_id_priority and isinstance(sport_id_priority, list):
            print(f"Using sport priority: {' > '.join([SPORT_NAMES.get(sid, str(sid)) for sid in sport_id_priority])}")
            sport_id = None
        else:
            sport_id = config.get('sport_id', 1)
            print(f"Tracking: {SPORT_NAMES.get(sport_id, f'Sport ID {sport_id}')}")
        if args.fetch_teams:
            target = sport_id if sport_id else (sport_id_priority[0] if sport_id_priority else 1)
            fetch_all_team_abbreviations(target)
            return

    # Determine date
    _pre9am = False
    _morning_block = None  # set only in morning alternating mode
    if args.date:
        date_str = args.date
        set_historical_mode(True)
        print(f"Using specified date: {date_str}")
    else:
        tz = config.get('timezone', 'America/Chicago')
        _now = datetime.now(pytz.timezone(tz))
        _is_weekend = _now.weekday() >= 5  # 5=Sat, 6=Sun
        _morning_end = (config.get('morning_end_weekend', 11) if _is_weekend
                        else config.get('morning_end', 9))
        _morning_start = config.get('night_end', 7)
        if _now.hour >= _morning_end:
            date_str = _now.date().strftime('%Y-%m-%d')
            print(f"Using today's date: {date_str}")
        elif _now.hour >= _morning_start and config.get('morning_alternate_games', True):
            # 7am–9am: alternate between yesterday and today every 5 minutes
            _pre9am = True
            _morning_block = (_now.hour * 60 + _now.minute) // 5
            if _morning_block % 2 == 0:
                date_str = (_now.date() - timedelta(days=1)).strftime('%Y-%m-%d')
                print(f"Morning alternating (block {_morning_block}) — showing previous day: {date_str}")
            else:
                date_str = _now.date().strftime('%Y-%m-%d')
                print(f"Morning alternating (block {_morning_block}) — showing today: {date_str}")
        else:
            date_str = (_now.date() - timedelta(days=1)).strftime('%Y-%m-%d')
            _pre9am = True
            print(f"Before 9am — showing previous day: {date_str}")

    # 5. Smart polling gate
    _is_fullscreen = os.environ.get('FEATURED_TEAM_FULLSCREEN', '').lower() in ('true', '1', 'yes')
    sched = {}
    if not args.date and not _no_throttle:
        sched = _load_schedule_state()
        if _pre9am:
            # Morning alternating mode: only fetch/render when the 5-minute block changes.
            # Each block switch toggles the display between yesterday and today, so there
            # is nothing new to show within the same block.
            _today_key = _now.date().isoformat()
            if (
                _morning_block is not None
                and sched.get('last_morning_block') == _morning_block
                and sched.get('last_morning_block_date') == _today_key
            ):
                print(f"Morning: same 5-min block ({_morning_block}) — skipping")
                return
        else:
            skip, reason = _should_skip_poll(date_str, config, sched)
            if skip:
                print(reason)
                if reason.startswith("No games until"):
                    if not _maybe_show_derby_bracket(
                            config, no_throttle=_no_throttle,
                            auto_open=args.local and system_platform == 'Darwin'):
                        _show_idle_screen(config, sched,
                                          auto_open=args.local and system_platform == 'Darwin')
                    return
                # Still refresh standings if needed — sidebar/fullscreen must stay current
                # even when the game-data poll is throttled.
                _sl_needs = (
                    config.get('show_standings_sidebar', False) or
                    config.get('show_wildcard_standings', False) or
                    _is_fullscreen
                )
                _sl_ids = [117, 112] if league_mode == 'aaa' else [103, 104]
                if _sl_needs and _should_refresh_standings(sched):
                    try:
                        _sl_today = datetime.now()
                        get_standings(_sl_ids, season=_sl_today.year)
                        _sl_prev = _sl_today - timedelta(days=1)
                        get_standings(_sl_ids, season=_sl_prev.year,
                                      date=_sl_prev.strftime('%m/%d/%Y'), save_as='standings_prev')
                    except Exception as _sl_e:
                        print(f"Warning: standings refresh on poll-skip: {_sl_e}")
                if config.get('show_playoff_bracket', True) and league_mode != 'aaa' \
                        and is_postseason_window() and _should_refresh_playoff_bracket():
                    try:
                        fetch_playoff_bracket()
                    except Exception as _bp_e:
                        print(f"Warning: playoff bracket fetch on poll-skip: {_bp_e}")
                if config.get('show_transactions_ticker', False) and _should_refresh_transactions():
                    try:
                        fetch_transactions(config.get('transactions_lookback_days', 2))
                    except Exception as _tx_e:
                        print(f"Warning: transactions fetch on poll-skip: {_tx_e}")
                if config.get('show_news_panel', False) and _should_refresh_news():
                    try:
                        fetch_news(primary_abbr=config.get('primary'),
                                   team_only=config.get('news_team_only', True))
                    except Exception as _nx_e:
                        print(f"Warning: news fetch on poll-skip: {_nx_e}")
                return

    # 6. Fetch
    fetch_scoreboard_for_date(date_str, sport_id, config)

    # 6b. Fetch the "next-day" schedule for next-game preview strips (cached, refreshes hourly).
    # In morning mode (showing yesterday's games) the "next" day relative to last night is
    # today, so we fetch today instead of actual tomorrow — keeping image_box._load_tomorrow_games
    # in sync and avoiding a silent cache-miss every render.
    if not args.date:
        import time as _tm_mod
        _tmrw_cache = load_json_file('tomorrow_games.json') or {}
        _today_str  = datetime.now().date().strftime('%Y-%m-%d')
        _tmrw_str   = (datetime.now().date() + timedelta(days=1)).strftime('%Y-%m-%d')
        _tmrw_target = _today_str if _pre9am else _tmrw_str
        _for_date_arg = _today_str if _pre9am else None   # None → fetch_tomorrow_games uses tomorrow
        _tmrw_age = _tm_mod.time() - _tmrw_cache.get('fetched_at', 0)
        if _tmrw_cache.get('date') != _tmrw_target or _tmrw_age > 3600 or args.full_refresh:
            try:
                fetch_tomorrow_games(config, for_date=_for_date_arg)
            except Exception as _e:
                print(f"Warning: fetch_tomorrow_games failed: {_e}")

    # 7. Update schedule state
    if not args.date and not _no_throttle:
        if _pre9am:
            # Record which block just ran so the next cron tick within the same
            # 5-minute window is skipped (morning gate above).
            if _morning_block is not None:
                sched['last_morning_block'] = _morning_block
                sched['last_morning_block_date'] = _now.date().isoformat()
                _save_schedule_state(sched)
        else:
            game_state_data = load_json_file('games.json').get('games', [])
            no_games = _update_schedule_state(game_state_data, date_str, config, sched)
            if no_games:
                # Leaders only otherwise refresh once games go Final, so a
                # multi-day gap (All-Star break, rainouts) leaves the cache
                # frozen.  Run the staleness check here too.
                if config.get('show_leaders_panel', False) and league_mode != 'aaa' \
                        and _should_refresh_leaders(sched, force=args.full_refresh):
                    print("Refreshing leaders during no-games gap (stale cache)...")
                    try:
                        _leaders_sport = sport_id if sport_id else (config.get('sport_id_priority', [1])[0])
                        fetch_leaders(sport_id=_leaders_sport)
                    except Exception as _e:
                        print(f"Warning: leaders fetch failed: {_e}")
                if not _maybe_show_derby_bracket(config, no_throttle=_no_throttle,
                                                 auto_open=args.local and system_platform == 'Darwin'):
                    _show_idle_screen(config, sched,
                                      auto_open=args.local and system_platform == 'Darwin')
                return

    # 7a. Auto dark/light mode: day = light, night = dark.
    # Uses dark_start / dark_end config keys (defaults: 20 → 7) so the display
    # dark window is independent of the refresh-suppression night window.
    # Detect day↔night transitions and force a full refresh — of the render/
    # display (below) *and* of standings/leaders/transactions/bracket data
    # (7b-7d) — since a mode flip is exactly the kind of moment stale data
    # would be most visible (e.g. a fresh light-mode morning screen showing
    # last night's leaders).
    _is_dark = _in_dark_window(config) if config.get('night_mode', True) else False
    config['dark_mode'] = _is_dark
    _dark_transitioned = False
    if not _no_throttle and not args.date:
        _last_dark = sched.get('last_dark_mode')
        if _last_dark is None or _last_dark != _is_dark:
            # None = first run after Pi boot/state reset — force a full refresh so the
            # display is guaranteed to start in the correct mode without ghosting.
            label = 'first-run' if _last_dark is None else ('light→dark' if _is_dark else 'dark→light')
            print(f"Dark mode transition: {label} — forcing full refresh")
            _dark_transitioned = True
        sched['last_dark_mode'] = _is_dark
        _save_schedule_state(sched)
    _force_data_refresh = args.full_refresh or _dark_transitioned

    # 7b. Standings refresh
    _needs_standings = (
        config.get('show_standings_sidebar', False) or
        config.get('show_wildcard_standings', False) or
        _is_fullscreen
    )
    _standings_league_ids = [117, 112] if league_mode == 'aaa' else [103, 104]
    if _needs_standings:
        if args.date:
            # Historical replay: fetch standings as of that specific date so the sidebar
            # reflects what the standings actually looked like on that day.
            print(f"Fetching historical standings for {date_str}...")
            try:
                _hist = datetime.strptime(date_str, '%Y-%m-%d')
                get_standings(_standings_league_ids, season=_hist.year,
                              date=_hist.strftime('%m/%d/%Y'))
                _prev = _hist - timedelta(days=1)
                get_standings(_standings_league_ids, season=_prev.year,
                              date=_prev.strftime('%m/%d/%Y'), save_as='standings_prev')
            except Exception as e:
                print(f"Warning: historical standings fetch failed: {e}")
        elif _should_refresh_standings(sched, force=_force_data_refresh):
            print("Refreshing standings (new Finals detected or no cache)...")
            try:
                today = datetime.now()
                get_standings(_standings_league_ids, season=today.year)
                prev_day = today - timedelta(days=1)
                get_standings(_standings_league_ids, season=prev_day.year,
                              date=prev_day.strftime('%m/%d/%Y'), save_as='standings_prev')
                games = load_json_file('games.json').get('games', [])
                sched['standings_final_pks'] = [
                    str(g['game_pk']) for g in games
                    if g.get('detailed_state') in _STANDINGS_FINAL_STATES and g.get('game_pk')
                ]
                _save_schedule_state(sched)
            except Exception as e:
                print(f"Warning: standings refresh failed: {e}")

    # 7c. Playoff bracket refresh — auto-detects postseason via the calendar
    # window (mid-Sept to mid-Nov) rather than requiring a manual config
    # toggle each year; show_playoff_bracket now just lets a user force it
    # off entirely if they never want the header taken over.
    if config.get('show_playoff_bracket', True) and league_mode != 'aaa' \
            and is_postseason_window() and _should_refresh_playoff_bracket(force=_force_data_refresh):
        try:
            fetch_playoff_bracket()
        except Exception as e:
            print(f"Warning: playoff bracket fetch failed: {e}")

    # 7c2. Transactions ticker refresh — recent IL moves/call-ups/signings,
    # only when the panel is enabled, and only when the cache is stale
    # (transactions don't change fast enough to warrant fetching every poll).
    if config.get('show_transactions_ticker', False) and _should_refresh_transactions(force=_force_data_refresh):
        try:
            fetch_transactions(config.get('transactions_lookback_days', 2))
        except Exception as e:
            print(f"Warning: transactions fetch failed: {e}")

    # 7c3. News headlines refresh — team-scoped or league-wide, every 6 hours.
    if config.get('show_news_panel', False) and _should_refresh_news(force=_force_data_refresh):
        try:
            fetch_news(primary_abbr=config.get('primary'),
                       team_only=config.get('news_team_only', True),
                       force=_force_data_refresh)
        except Exception as e:
            print(f"Warning: news fetch failed: {e}")

    # 7d. Season leaders refresh (HR/AVG/ERA/Saves/Hits) — only when panel is
    # enabled, and only once games have gone Final (or cache is stale/missing),
    # not on every poll — leaders barely move mid-game.
    if config.get('show_leaders_panel', False) and league_mode != 'aaa' \
            and _should_refresh_leaders(sched, force=_force_data_refresh):
        print("Refreshing leaders (new Finals detected or no cache)...")
        try:
            _leaders_sport = sport_id if sport_id else (config.get('sport_id_priority', [1])[0])
            fetch_leaders(sport_id=_leaders_sport, force=_force_data_refresh)
            games = load_json_file('games.json').get('games', [])
            sched['leaders_final_pks'] = [
                str(g['game_pk']) for g in games
                if g.get('detailed_state') in _STANDINGS_FINAL_STATES and g.get('game_pk')
            ]
            _save_schedule_state(sched)
        except Exception as e:
            print(f"Warning: leaders fetch failed: {e}")

    # 9. Render
    # On a dark-mode transition the rendered image inverts even when the game
    # data is byte-identical, but render()'s unchanged-data cache only compares
    # game JSON — it would return None and the forced full refresh below would
    # be silently skipped (with last_dark_mode already saved above, no later
    # run re-detects the flip). Cells whose games never change again that
    # night (e.g. long-final games) would then keep the old polarity until the
    # hourly full-refresh timer fired, leaving a washed-out light-mode band on
    # an otherwise dark screen. Bypass the cache so the transition always
    # renders and reaches the display.
    output_path = os.path.join(_REPO_ROOT, 'resulting_image.bmp')
    result = render(config, date_str=date_str, output_path=output_path,
                    bypass_cache=_no_throttle or _dark_transitioned)

    if not result:
        print("No display update needed - image unchanged")
        return

    image, changed_regions = result

    # 9. Send to display
    # Morning alternating mode swaps the entire screen between last night's
    # results and today's schedule every 5 minutes — a partial refresh can't
    # fully clear the previous frame's residual charge across a change that
    # large, causing visible ghosting/bleeding. Force a full (flashing)
    # refresh on every render during this window instead.
    #
    # Also force a full refresh whenever the scoreboard grid packing shifted
    # a game to a different cell (e.g. another game going live repacked the
    # wide-cell layout) — orchestrate_score_board flags this in
    # force_full_refresh.json since a game whose own data is unchanged never
    # gets a partial-refresh region, leaving its old cell showing a stale
    # game behind.
    _layout_changed = load_json_file('force_full_refresh.json').get('needed', False)
    _force_full = _morning_block is not None or _layout_changed or _dark_transitioned
    refresh_mode = send_to_display(output_path, changed_regions, force_full=_force_full)
    print(f"Scoreboard: {refresh_mode} refresh ({len(changed_regions)} region(s))")

    print("\n✓ Display updated successfully!")
    print(f"  Image: {output_path}")

    # 10. --local: auto-open on macOS
    if args.local and system_platform == 'Darwin':
        import subprocess
        subprocess.run(['open', output_path], check=False)

    # 11. Auto-generate end-of-day timelapse (once all games are final, runs once per day)
    if not args.date and not _pre9am:
        _maybe_generate_video(date_str, config)


if __name__ == '__main__':
    main()
