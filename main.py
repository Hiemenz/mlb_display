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
from collections import namedtuple
from datetime import datetime, timedelta, timezone

import pytz

# Ensure src/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config_loader import load_config, add_config_arg
from fetch_games import fetch_scoreboard_for_date, fetch_all_team_abbreviations, find_next_game_date, fetch_tomorrow_games, SPORT_NAMES
from fetch_leaders import fetch_leaders
from fetch_streaks import fetch_streaks
from fetch_news import fetch_news
from fetch_derby import fetch_and_save_derby_bracket, get_derby_date
from fetch_team_quadrant import fetch_team_quadrant
from render_scoreboard import render, _get_display_mode
from display import send_to_display
from util import load_json_file, in_hour_window
from standings import get_standings, fetch_playoff_bracket, fetch_transactions, is_postseason_window
from image_box import set_historical_mode
from image_idle import draw_idle_screen, draw_history_screen


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


def _local_now(config):
    """Current time in the configured display timezone.

    Every date decision in the pipeline must go through this rather than a bare
    datetime.now(): a Pi running on UTC with timezone: America/Chicago would
    otherwise roll over to "tomorrow" six hours early, fetching the wrong
    next-game schedule and mislabelling the scoreboard date.
    """
    return datetime.now(pytz.timezone(config.get('timezone', 'America/Chicago')))


def _in_night_window(config):
    """Return True if we are currently inside the configured night mode window.

    night_start == night_end is an empty window (see util.in_hour_window), so a
    misconfigured pair can't silently freeze the display all day.
    """
    return in_hour_window(
        config.get('night_start', 0),
        config.get('night_end', 7),
        _local_now(config).hour,
    )


def _in_dark_window(config):
    """Return True when the display should be in dark mode (evening through morning).

    Driven by dark_start / dark_end config keys (default 20 → 7) so that the
    display colour scheme is independent of the refresh-suppression night window.
    Falls back to night_start / night_end if the dark_* keys are absent.
    """
    return in_hour_window(
        config.get('dark_start', config.get('night_start', 20)),
        config.get('dark_end', config.get('night_end', 7)),
        _local_now(config).hour,
    )


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
_STREAKS_MAX_AGE_HOURS = 24    # refresh if streaks.json is older than this
_TRANSACTIONS_MAX_AGE_HOURS = 3  # refresh if transactions.json is older than this
_NEWS_MAX_AGE_HOURS = 6         # refresh if news.json is older than this
_PLAYOFF_BRACKET_MAX_AGE_HOURS = 1  # refresh cadence during an active postseason


def _cache_age_hours(filename):
    """Hours since data/<filename> was last written, or None if it doesn't exist."""
    path = _data_path(filename)
    if not os.path.exists(path):
        return None
    return (time.time() - os.path.getmtime(path)) / 3600


def _current_final_pks():
    """Set of game_pk strings currently in a terminal state, or None if unreadable."""
    try:
        games = load_json_file('games.json').get('games', [])
    except Exception:
        return None
    return {
        str(g['game_pk']) for g in games
        if g.get('detailed_state') in _STANDINGS_FINAL_STATES and g.get('game_pk')
    }


def _should_refresh(label, filename, max_age_hours, force=False,
                    sched=None, final_pks_key=None):
    """Return True when a cached data file needs refetching.

    Two independent triggers:
      * the cache is missing, or older than ``max_age_hours`` (catches the
        once-a-day / offline-for-a-day cases);
      * a game that is now Final wasn't Final at the last refresh of *this*
        file — only when ``sched`` and ``final_pks_key`` are supplied.

    Each caller must pass its own ``final_pks_key``. Sharing one key across two
    panels means whichever refreshes first records the Finals and starves the
    other for the rest of the day.

    force=True (--full-refresh) always refreshes regardless of cache state.
    """
    if force:
        return True

    age_hours = _cache_age_hours(filename)
    if age_hours is None:
        return True
    if age_hours >= max_age_hours:
        print(f"{label} stale ({age_hours:.1f}h old) — refreshing")
        return True

    if sched is None or final_pks_key is None:
        return False
    current_finals = _current_final_pks()
    if current_finals is None:
        return False
    return bool(current_finals - set(sched.get(final_pks_key, [])))


def _record_refreshed_finals(sched, final_pks_key):
    """Remember which games were Final at this refresh, so the next poll only
    re-triggers when a *new* game goes Final."""
    current_finals = _current_final_pks()
    if current_finals is not None:
        sched[final_pks_key] = sorted(current_finals)
        _save_schedule_state(sched)


def _should_refresh_leaders(sched, force=False):
    """Return True if leaders.json needs a refresh."""
    return _should_refresh('Leaders', 'leaders.json', _LEADERS_MAX_AGE_HOURS,
                           force, sched, 'leaders_final_pks')


def _should_refresh_streaks(sched, force=False):
    """Return True if streaks.json needs a refresh.

    Keyed on its own cache file and its own Finals marker rather than piggybacking
    on the leaders gate — sharing that gate meant a successful leaders refresh
    consumed the trigger and the streaks panel never updated.
    """
    return _should_refresh('Streaks', 'streaks.json', _STREAKS_MAX_AGE_HOURS,
                           force, sched, 'streaks_final_pks')


def _should_refresh_standings(sched, force=False):
    """Return True if standings.json needs a refresh."""
    return _should_refresh('Standings', 'standings.json', _STANDINGS_MAX_AGE_HOURS,
                           force, sched, 'standings_final_pks')


def _should_refresh_transactions(force=False):
    """Return True if transactions.json needs a refresh (simple age check)."""
    return _should_refresh('Transactions', 'transactions.json',
                           _TRANSACTIONS_MAX_AGE_HOURS, force)


def _should_refresh_news(force=False):
    """Return True if news.json needs a refresh (simple age check)."""
    return _should_refresh('News', 'news.json', _NEWS_MAX_AGE_HOURS, force)


def _should_refresh_playoff_bracket(force=False):
    """Return True if playoff_bracket.json needs a refresh (simple age check).

    Series win counts only change once per completed game, so hourly is
    frequent enough even during an active series.
    """
    return _should_refresh('Playoff bracket', 'playoff_bracket.json',
                           _PLAYOFF_BRACKET_MAX_AGE_HOURS, force)


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


def _maybe_show_quadrant(config, no_throttle=False, auto_open=False):
    """On a no-games day, show the team quadrant chart instead of the idle screen.

    Returns True when the chart rendered, so the caller skips its normal
    no-games handling. Off-days are the one time a season-shape view has the
    panel to itself, and it is strictly more interesting than an empty grid —
    but only when the user actually selected that mode.
    """
    if _get_display_mode(config) != 'quadrant':
        return False

    _refresh_team_quadrant(config, config.get('league_mode', 'mlb'),
                           context=' on no-games day')

    is_dark = _in_dark_window(config) if config.get('night_mode', True) else False
    output_path = os.path.join(_REPO_ROOT, 'resulting_image.bmp')
    result = render(dict(config, dark_mode=is_dark), output_path=output_path,
                    bypass_cache=no_throttle)
    if not result:
        return False

    image, changed_regions = result
    refresh_mode = send_to_display(output_path, changed_regions, force_full=no_throttle)
    print(f"Quadrant: {refresh_mode} refresh ({len(changed_regions)} region(s))")
    if auto_open:
        import subprocess
        subprocess.run(['open', output_path], check=False)
    return True


def _show_idle_screen(config, auto_open=False):
    """Render and display the idle 'no games today' screen.

    Alternates between the recent-transactions view and the team quadrant
    chart every 20 minutes (keyed to the wall clock so the output is
    deterministic for any given cron tick).  The quadrant slot is skipped
    when quadrant data isn't cached — transactions are shown instead.
    """
    _is_dark = _in_dark_window(config) if config.get('night_mode', True) else False
    idle_config = dict(config, dark_mode=_is_dark)

    # Determine which view this 20-minute block should show.
    # Block 0 (min 0-19) → transactions
    # Block 1 (min 20-39) → quadrant chart (if data available)
    # Block 2 (min 40-59) → this day in history (if data available)
    _block = datetime.now().minute // 20
    _show_quadrant_slot = (
        config.get('idle_quadrant_rotation', True)
        and _block == 1
    )
    _show_history_slot = (
        config.get('idle_history_rotation', True)
        and _block == 2
    )
    if _show_history_slot:
        try:
            from fetch_idle import fetch_this_day_in_history
            _today = datetime.now().strftime('%Y-%m-%d')
            _hist_year, _hist_games = fetch_this_day_in_history(_today)
            if _hist_games:
                _team_data = load_json_file('teams.json')
                if not _team_data or 'team_abbreviation' not in _team_data:
                    _team_data = {'team_abbreviation': {}}
                image = draw_history_screen(_hist_games, _hist_year, _team_data, idle_config)
                print(f"Idle: showing history screen (year={_hist_year})")
            else:
                _show_history_slot = False
        except Exception as _he:
            print(f"Idle: history render failed ({_he}), falling back to transactions")
            _show_history_slot = False

    if not _show_history_slot and _show_quadrant_slot:
        quadrant_data = load_json_file('team_quadrant.json')
        if quadrant_data:
            try:
                from quadrant_view import render_quadrant_view
                image = render_quadrant_view(
                    quadrant_data, config=idle_config,
                    dark_mode=idle_config.get('dark_mode', False),
                )
                print("Idle: showing quadrant view")
            except Exception as _qe:
                print(f"Idle: quadrant render failed ({_qe}), falling back to transactions")
                _show_quadrant_slot = False
        else:
            _show_quadrant_slot = False

    if not _show_history_slot and not _show_quadrant_slot:
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


_DateContext = namedtuple(
    '_DateContext',
    ['date_str', 'showing_previous_day', 'morning_block', 'now', 'mode_override'])


def morning_rotation(config):
    """The views the morning window cycles through, one per 5-minute block.

    'quadrant' is a display mode rather than a date, so it rides along as a
    mode override; the other two are ordinary game grids for a given day.
    """
    if config.get('morning_alternate_quadrant', True):
        return ('today', 'yesterday', 'quadrant')
    return ('yesterday', 'today')


def _resolve_target_date(args, config):
    """Pick which date's games to show, returning a _DateContext.

    * ``--date`` wins outright and flips the renderer into historical mode.
    * After the morning cutoff (9am, 11am at weekends) → today.
    * Inside the morning window → the previous day, so last night's finals stay
      up through breakfast. With ``morning_alternate_games`` enabled the window
      instead cycles through morning_rotation() every 5 minutes;
      ``morning_block`` carries that block index (None when not alternating, and
      the only thing the morning throttle may key on).
    """
    if args.date:
        set_historical_mode(True)
        print(f"Using specified date: {args.date}")
        return _DateContext(args.date, False, None, _local_now(config), None)

    now = _local_now(config)
    today = now.date().strftime('%Y-%m-%d')
    yesterday = (now.date() - timedelta(days=1)).strftime('%Y-%m-%d')

    is_weekend = now.weekday() >= 5  # 5=Sat, 6=Sun
    morning_end = (config.get('morning_end_weekend', 11) if is_weekend
                   else config.get('morning_end', 9))
    morning_start = config.get('night_end', 7)

    if now.hour >= morning_end:
        print(f"Using today's date: {today}")
        return _DateContext(today, False, None, now, None)

    if now.hour >= morning_start and config.get('morning_alternate_games', True):
        block = (now.hour * 60 + now.minute) // 5
        rotation = morning_rotation(config)
        view = rotation[block % len(rotation)]
        if view == 'quadrant':
            print(f"Morning alternating (block {block}) — showing team quadrant")
            return _DateContext(today, False, block, now, 'quadrant')
        date_str = yesterday if view == 'yesterday' else today
        print(f"Morning alternating (block {block}) — showing {view}: {date_str}")
        return _DateContext(date_str, view == 'yesterday', block, now, None)

    print(f"Before {morning_end}am — showing previous day: {yesterday}")
    return _DateContext(yesterday, True, None, now, None)


def _update_schedule_state(game_state_data, date_str, config, sched):
    """Update schedule state."""
    sched['last_game_fetch'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    sched['last_fetch_date'] = date_str
    if not game_state_data:
        priority = config.get('sport_id_priority', [1, 8, 16])
        tomorrow = (_local_now(config).date() + timedelta(days=1)).strftime('%Y-%m-%d')
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



def _resolve_league_mode(config):
    """Effective league mode — LEAGUE_MODE env var wins over config."""
    return (os.environ.get('LEAGUE_MODE', '').lower().strip()
            or config.get('league_mode', 'mlb'))


def _resolve_sport(args, config):
    """Resolve (sport_id, league_mode, handled) from args + config.

    sport_id is None when a sport_id_priority list is configured — that tells
    fetch_scoreboard_for_date to walk the priority list instead of pinning one
    sport. ``handled`` is True when --fetch-teams already did its work and the
    caller should exit.
    """
    league_mode = _resolve_league_mode(config)

    if args.sport_id:
        sport_id = args.sport_id
        print(f"Using specified sport: {SPORT_NAMES.get(sport_id, f'Sport ID {sport_id}')}")
        if sport_id == 11 and league_mode != 'aaa':
            league_mode = 'aaa'
            config['league_mode'] = 'aaa'
        if args.fetch_teams:
            fetch_all_team_abbreviations(sport_id)
            return sport_id, league_mode, True
        return sport_id, league_mode, False

    if league_mode == 'aaa':
        print("League mode: AAA (Triple-A)")
        if args.fetch_teams:
            fetch_all_team_abbreviations(11)
            return 11, league_mode, True
        return 11, league_mode, False

    sport_id_priority = config.get('sport_id_priority')
    if sport_id_priority and isinstance(sport_id_priority, list):
        print("Using sport priority: "
              + ' > '.join(SPORT_NAMES.get(sid, str(sid)) for sid in sport_id_priority))
        sport_id = None
    else:
        sport_id = config.get('sport_id', 1)
        print(f"Tracking: {SPORT_NAMES.get(sport_id, f'Sport ID {sport_id}')}")

    if args.fetch_teams:
        target = sport_id if sport_id else (sport_id_priority[0] if sport_id_priority else 1)
        fetch_all_team_abbreviations(target)
        return sport_id, league_mode, True
    return sport_id, league_mode, False


def _primary_sport_id(sport_id, config):
    """A concrete sport id for the season-stat fetchers, which can't take None."""
    return sport_id if sport_id else (config.get('sport_id_priority', [1]) or [1])[0]



# ---------------------------------------------------------------------------
# Support-data refresh — standings, bracket, transactions, news, leaders, streaks.
#
# These run from three places with different subsets and force flags: the
# poll-skip path (game poll throttled, panels must still stay current), the
# no-games path, and the normal post-fetch path. One function per source keeps
# the gate, the fetch and the error message together instead of repeating the
# same try/except shape at each call site.
# ---------------------------------------------------------------------------

def _standings_league_ids(league_mode):
    """League ids to request standings for (AAA uses its own two leagues)."""
    return [117, 112] if league_mode == 'aaa' else [103, 104]


def _needs_standings(config, is_fullscreen):
    """True when some enabled panel actually consumes standings.json."""
    return bool(
        config.get('show_standings_sidebar', False)
        or config.get('show_wildcard_standings', False)
        or is_fullscreen
    )


def _refresh_standings(config, sched, league_mode, is_fullscreen, force=False, context=''):
    """Refetch today's + yesterday's standings when the cache is stale."""
    if not _needs_standings(config, is_fullscreen):
        return
    if not _should_refresh_standings(sched, force=force):
        return
    if not context:
        print("Refreshing standings (new Finals detected or no cache)...")
    league_ids = _standings_league_ids(league_mode)
    try:
        today = _local_now(config)
        get_standings(league_ids, season=today.year)
        prev_day = today - timedelta(days=1)
        get_standings(league_ids, season=prev_day.year,
                      date=prev_day.strftime('%m/%d/%Y'), save_as='standings_prev')
        _record_refreshed_finals(sched, 'standings_final_pks')
    except Exception as e:
        print(f"Warning: standings refresh{context} failed: {e}")


def _refresh_historical_standings(config, date_str, league_mode):
    """Fetch standings as of a replayed --date, so the sidebar matches that day."""
    print(f"Fetching historical standings for {date_str}...")
    league_ids = _standings_league_ids(league_mode)
    try:
        hist = datetime.strptime(date_str, '%Y-%m-%d')
        get_standings(league_ids, season=hist.year, date=hist.strftime('%m/%d/%Y'))
        prev = hist - timedelta(days=1)
        get_standings(league_ids, season=prev.year,
                      date=prev.strftime('%m/%d/%Y'), save_as='standings_prev')
    except Exception as e:
        print(f"Warning: historical standings fetch failed: {e}")


def _refresh_playoff_bracket(config, league_mode, force=False, context=''):
    """Refetch the postseason bracket during the postseason calendar window."""
    if not (config.get('show_playoff_bracket', True) and league_mode != 'aaa'):
        return
    if not (is_postseason_window() and _should_refresh_playoff_bracket(force=force)):
        return
    try:
        fetch_playoff_bracket()
    except Exception as e:
        print(f"Warning: playoff bracket fetch{context} failed: {e}")


def _refresh_transactions(config, force=False, context=''):
    """Refetch recent transactions when the ticker or deadline panel needs them."""
    if not (config.get('show_transactions_ticker', False)
            or config.get('show_deadline_panel', False)):
        return
    if not _should_refresh_transactions(force=force):
        return
    try:
        fetch_transactions(config.get('transactions_lookback_days', 2))
    except Exception as e:
        print(f"Warning: transactions fetch{context} failed: {e}")


def _refresh_news(config, force=False, context=''):
    """Refetch news headlines for the news panel."""
    if not (config.get('show_news_panel', False) and _should_refresh_news(force=force)):
        return
    try:
        fetch_news(primary_abbr=config.get('primary'),
                   team_only=config.get('news_team_only', True),
                   force=force)
    except Exception as e:
        print(f"Warning: news fetch{context} failed: {e}")


def _refresh_leaders(config, sched, league_mode, sport_id, force=False, context=''):
    """Refetch season stat leaders once games go Final or the cache goes stale."""
    if not (config.get('show_leaders_panel', False) and league_mode != 'aaa'):
        return
    if not _should_refresh_leaders(sched, force=force):
        return
    print(f"Refreshing leaders{context} (new Finals detected or no cache)...")
    try:
        fetch_leaders(sport_id=_primary_sport_id(sport_id, config), force=force)
        _record_refreshed_finals(sched, 'leaders_final_pks')
    except Exception as e:
        print(f"Warning: leaders fetch{context} failed: {e}")


def _refresh_streaks(config, sched, league_mode, sport_id, force=False, context=''):
    """Refetch Hot Hitters / Hot Arms data for the streaks and scoreless panels.

    Same TTL and trigger shape as leaders, but gated on its own cache file and
    its own Finals marker — sharing the leaders gate let whichever ran first
    consume the trigger and starve the other.
    """
    if not (config.get('show_streaks_panel', False)
            or config.get('show_scoreless_panel', False)):
        return
    if league_mode == 'aaa' or not _should_refresh_streaks(sched, force=force):
        return
    try:
        fetch_streaks(sport_id=_primary_sport_id(sport_id, config), force=force)
        _record_refreshed_finals(sched, 'streaks_final_pks')
    except Exception as e:
        print(f"Warning: streaks fetch{context} failed: {e}")



def _refresh_team_quadrant(config, league_mode, force=False, context=''):
    """Refetch the offense-vs-pitching quadrant data when that mode is on screen.

    Costs four date-ranged team-stat calls per grain, so it is gated on the
    display mode rather than a panel toggle; fetch_team_quadrant's own 6-hour
    TTL absorbs the repeat calls across refresh cycles. MLB-only — the
    date-range team splits have no Triple-A equivalent.
    """
    if league_mode == 'aaa' or _get_display_mode(config) != 'quadrant':
        return
    try:
        fetch_team_quadrant(force=force)
    except Exception as e:
        print(f"Warning: team quadrant fetch{context} failed: {e}")


_NEXT_DAY_CACHE_TTL_SECONDS = 3600


def _fetch_next_day_schedule(config, date_str, force=False):
    """Refresh tomorrow_games.json, the source for next-game preview strips.

    The target is the day after ``date_str`` — the date actually being rendered
    — matching how image_box._load_tomorrow_games derives it per game. While the
    morning window shows yesterday's results the target is therefore today, not
    actual tomorrow.

    The cache keeps several days (see fetch_games._save_tomorrow_games), so the
    morning alternating window flipping between two targets does not refetch on
    every block change.
    """
    target = (datetime.strptime(date_str, '%Y-%m-%d').date()
              + timedelta(days=1)).strftime('%Y-%m-%d')

    cache = load_json_file('tomorrow_games.json') or {}
    entry = (cache.get('by_date') or {}).get(target)
    if entry is None and cache.get('date') == target:
        entry = cache
    if entry is not None and not force:
        age = time.time() - entry.get('fetched_at', 0)
        if age <= _NEXT_DAY_CACHE_TTL_SECONDS:
            return

    try:
        fetch_tomorrow_games(config, for_date=target)
    except Exception as e:
        print(f"Warning: fetch_tomorrow_games failed: {e}")



def _apply_dark_mode(config, sched, track_transition):
    """Set config['dark_mode'] for this run and report whether it just flipped.

    A day↔night flip inverts the whole image even when the game data is
    byte-identical, so the caller uses the return value to force both a data
    refresh and a full (flashing) panel refresh. ``last_dark_mode`` unset means
    first run after a boot/state reset, which counts as a transition so the
    display is guaranteed to start in the right polarity without ghosting.
    """
    is_dark = _in_dark_window(config) if config.get('night_mode', True) else False
    config['dark_mode'] = is_dark
    if not track_transition:
        return False

    last_dark = sched.get('last_dark_mode')
    transitioned = last_dark is None or last_dark != is_dark
    if transitioned:
        label = ('first-run' if last_dark is None
                 else ('light→dark' if is_dark else 'dark→light'))
        print(f"Dark mode transition: {label} — forcing full refresh")
    sched['last_dark_mode'] = is_dark
    _save_schedule_state(sched)
    return transitioned


def _render_and_display(config, date_str, output_path, no_throttle,
                        dark_transitioned, morning_block):
    """Render the scoreboard and push it to the panel. False if nothing changed.

    On a dark-mode transition the image inverts even when the game data is
    byte-identical, but render()'s unchanged-data cache only compares game JSON
    — it would return None and the forced full refresh below would be silently
    skipped (last_dark_mode is already saved, so no later run re-detects the
    flip). Cells whose games never change again that night would then keep the
    old polarity until the hourly full-refresh timer fired, leaving a washed-out
    light-mode band on an otherwise dark screen. Bypass the cache so the
    transition always renders and reaches the display.
    """
    result = render(config, date_str=date_str, output_path=output_path,
                    bypass_cache=no_throttle or dark_transitioned)
    if not result:
        print("No display update needed - image unchanged")
        return False

    _image, changed_regions = result

    # Force a full (flashing) refresh rather than a partial one when:
    #  * morning alternating mode swapped the whole screen between last night's
    #    results and today's schedule — a partial refresh can't clear residual
    #    charge across a change that large, so it ghosts;
    #  * the grid packing moved a game to a different cell (flagged by
    #    orchestrate_score_board in force_full_refresh.json) — a game whose own
    #    data is unchanged never gets a partial-refresh region, so its old cell
    #    would keep showing the stale game behind it;
    #  * the display just flipped between light and dark mode.
    layout_changed = load_json_file('force_full_refresh.json').get('needed', False)
    force_full = morning_block is not None or layout_changed or dark_transitioned

    refresh_mode = send_to_display(output_path, changed_regions, force_full=force_full)
    print(f"Scoreboard: {refresh_mode} refresh ({len(changed_regions)} region(s))")
    print("\n✓ Display updated successfully!")
    print(f"  Image: {output_path}")
    return True


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

    sport_id, league_mode, done = _resolve_sport(args, config)
    if done:
        return  # --fetch-teams: cache abbreviations and exit

    # Determine date
    _date_ctx = _resolve_target_date(args, config)
    date_str = _date_ctx.date_str
    _pre9am = _date_ctx.showing_previous_day
    _morning_block = _date_ctx.morning_block
    _now = _date_ctx.now

    # 5. Smart polling gate
    _is_fullscreen = os.environ.get('FEATURED_TEAM_FULLSCREEN', '').lower() in ('true', '1', 'yes')
    sched = {}
    if not args.date and not _no_throttle:
        sched = _load_schedule_state()
        # Gate on morning_block, not showing_previous_day: with
        # morning_alternate_games off we still show the previous day during the
        # morning window but there is no block to throttle on, so that path has
        # to fall through to the normal smart-polling gate below rather than
        # skipping every check and refetching on every cron tick.
        if _morning_block is not None:
            # Morning alternating mode: only fetch/render when the 5-minute block changes.
            # Each block switch toggles the display between yesterday and today, so there
            # is nothing new to show within the same block.
            _today_key = _now.date().isoformat()
            if (
                sched.get('last_morning_block') == _morning_block
                and sched.get('last_morning_block_date') == _today_key
            ):
                print(f"Morning: same 5-min block ({_morning_block}) — skipping")
                return
        else:
            skip, reason = _should_skip_poll(date_str, config, sched)
            if skip:
                print(reason)
                if reason.startswith("No games until"):
                    _auto_open = args.local and system_platform == 'Darwin'
                    if not _maybe_show_derby_bracket(
                            config, no_throttle=_no_throttle, auto_open=_auto_open):
                        if not _maybe_show_quadrant(
                                config, no_throttle=_no_throttle, auto_open=_auto_open):
                            _show_idle_screen(config, auto_open=_auto_open)
                    return
                # The game poll is throttled, but the panels around the grid
                # must still stay current — refresh them on their own gates.
                _ctx = ' on poll-skip'
                _refresh_standings(config, sched, league_mode, _is_fullscreen, context=_ctx)
                _refresh_playoff_bracket(config, league_mode, context=_ctx)
                _refresh_transactions(config, context=_ctx)
                _refresh_news(config, context=_ctx)
                return

    # 6. Fetch
    fetch_scoreboard_for_date(date_str, sport_id, config)

    # 6b. Next-day schedule for the next-game preview strips.
    if not args.date:
        _fetch_next_day_schedule(config, date_str, force=args.full_refresh)

    # 7. Update schedule state
    if not args.date and not _no_throttle:
        # Mirrors the poll gate above: only true morning-alternating runs do
        # block bookkeeping. Every other path — including the morning window
        # with morning_alternate_games off — must fall through and record
        # last_game_fetch, or _should_skip_poll has no timestamp to throttle on
        # and refetches on every cron tick.
        if _morning_block is not None:
            # Record which block just ran so the next cron tick within the same
            # 5-minute window is skipped (morning gate above).
            sched['last_morning_block'] = _morning_block
            sched['last_morning_block_date'] = _now.date().isoformat()
            _save_schedule_state(sched)
        else:
            game_state_data = load_json_file('games.json').get('games', [])
            no_games = _update_schedule_state(game_state_data, date_str, config, sched)
            if no_games:
                # Leaders/streaks otherwise only refresh once games go Final, so a
                # multi-day gap (All-Star break, rainouts) leaves the cache frozen.
                # Run their staleness checks here too.
                _ctx = ' during no-games gap'
                _refresh_leaders(config, sched, league_mode, sport_id,
                                 force=args.full_refresh, context=_ctx)
                _refresh_streaks(config, sched, league_mode, sport_id,
                                 force=args.full_refresh, context=_ctx)
                _auto_open = args.local and system_platform == 'Darwin'
                if not _maybe_show_derby_bracket(config, no_throttle=_no_throttle,
                                                 auto_open=_auto_open):
                    if not _maybe_show_quadrant(config, no_throttle=_no_throttle,
                                                auto_open=_auto_open):
                        _show_idle_screen(config, auto_open=_auto_open)
                return

    # 7a. Auto dark/light mode: day = light, night = dark.
    # Uses dark_start / dark_end config keys (defaults: 20 → 7) so the display
    # dark window is independent of the refresh-suppression night window.
    # Detect day↔night transitions and force a full refresh — of the render/
    # display (below) *and* of standings/leaders/transactions/bracket data
    # (7b-7d) — since a mode flip is exactly the kind of moment stale data
    # would be most visible (e.g. a fresh light-mode morning screen showing
    # last night's leaders).
    _dark_transitioned = _apply_dark_mode(
        config, sched, track_transition=not _no_throttle and not args.date)
    _force_data_refresh = args.full_refresh or _dark_transitioned

    # 7b-7e. Support-data refresh — standings, playoff bracket, transactions,
    # news, leaders and streaks, each on its own staleness/Finals gate so a
    # panel nobody has enabled never costs an API call.
    if args.date:
        # Historical replay: standings as of that specific date.
        if _needs_standings(config, _is_fullscreen):
            _refresh_historical_standings(config, date_str, league_mode)
    else:
        _refresh_standings(config, sched, league_mode, _is_fullscreen,
                           force=_force_data_refresh)
    _refresh_playoff_bracket(config, league_mode, force=_force_data_refresh)
    _refresh_transactions(config, force=_force_data_refresh)
    _refresh_news(config, force=_force_data_refresh)
    _refresh_leaders(config, sched, league_mode, sport_id, force=_force_data_refresh)
    _refresh_streaks(config, sched, league_mode, sport_id, force=_force_data_refresh)

    # A morning rotation block showing the quadrant overrides the display mode
    # for this run only — config itself is left alone so the mode the user
    # actually configured comes back on the next block. Built before the
    # quadrant refresh so that refresh sees the mode it gates on.
    view_config = config
    if _date_ctx.mode_override:
        view_config = dict(config, display_mode=_date_ctx.mode_override)
    _refresh_team_quadrant(view_config, league_mode, force=_force_data_refresh)

    # 9. Render and push to the panel.
    output_path = os.path.join(_REPO_ROOT, 'resulting_image.bmp')
    if not _render_and_display(view_config, date_str, output_path,
                               no_throttle=_no_throttle,
                               dark_transitioned=_dark_transitioned,
                               morning_block=_morning_block):
        return

    # 10. --local: auto-open on macOS
    if args.local and system_platform == 'Darwin':
        import subprocess
        subprocess.run(['open', output_path], check=False)

    # 11. Auto-generate end-of-day timelapse (once all games are final, runs once per day)
    if not args.date and not _pre9am:
        _maybe_generate_video(date_str, config)


if __name__ == '__main__':
    main()
