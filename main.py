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
from datetime import datetime, timedelta

import pytz

# Ensure src/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config_loader import load_config, add_config_arg
from fetch_games import fetch_scoreboard_for_date, fetch_all_team_abbreviations, find_next_game_date, SPORT_NAMES
from render_scoreboard import render
from display import send_to_display
from util import load_json_file
from standings import get_standings
from image_box import set_historical_mode


# ---------------------------------------------------------------------------
# Private helpers (night mode, Discord, smart polling) — stay in main.py only
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def _data_path(filename):
    return os.path.join(_REPO_ROOT, 'data', filename)


def _config_path():
    return os.path.join(_REPO_ROOT, 'config', 'config.yaml')


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


def _load_discord_state():
    path = _data_path('discord_state.json')
    try:
        with open(path) as f:
            state = json.load(f)
        if not state.get('applied', True):
            return state
    except (FileNotFoundError, Exception):
        pass
    return None


def _mark_discord_applied():
    path = _data_path('discord_state.json')
    try:
        with open(path) as f:
            state = json.load(f)
        state['applied'] = True
        with open(path, 'w') as f:
            json.dump(state, f, indent=2)
    except (FileNotFoundError, Exception):
        pass


def _apply_discord_change(state, config):
    """Apply pending Discord changes to in-memory config and persist config.yaml."""
    import yaml
    changed = False
    if state.get('pending_mode') and state['pending_mode'] in ('scoreboard', 'linescore', 'field', 'scorecard', 'pitch'):
        config['display_mode'] = state['pending_mode']
        changed = True
    if state.get('pending_team'):
        config['primary'] = state['pending_team'].upper()
        changed = True
    if changed:
        try:
            with open(_config_path(), 'w') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            print(f"Warning: could not save config.yaml after Discord change: {e}")
    return changed


def _render_discord_overlay(state, dark_mode=False):
    from PIL import Image, ImageDraw, ImageFont
    picdir = os.path.join(_REPO_ROOT, 'pic')
    img = Image.new('1', (800, 480), 255)
    draw = ImageDraw.Draw(img)
    try:
        font_lg = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 48)
        font_md = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 28)
        font_sm = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 22)
    except Exception:
        font_lg = font_md = font_sm = ImageFont.load_default()

    mode = state.get('pending_mode', '').upper()
    team = state.get('pending_team', '').upper()
    user = state.get('requested_by', '')

    lines = [
        ('Display Changing', font_md, 120),
        (mode or team, font_lg, 185),
    ]
    if mode and team:
        lines.append((f'Team: {team}', font_md, 265))
    lines.append((f'Requested by @{user}', font_sm, 340))

    for text, font, y in lines:
        try:
            w = font.getlength(text)
        except AttributeError:
            w = len(text) * 12
        draw.text(((800 - w) // 2, y), text, font=font, fill=0)

    draw.rectangle([10, 10, 789, 469], outline=0, width=3)
    if dark_mode:
        img = img.point(lambda p: 0 if p == 255 else 255)
    return img


def _load_schedule_state():
    path = _data_path('schedule_state.json')
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_schedule_state(state):
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
        from scoreboard_generate import _generate_gif

        output_dir = os.path.join(_REPO_ROOT, 'output')
        os.makedirs(output_dir, exist_ok=True)
        gif_path = os.path.join(output_dir, f'scoreboard_{date_str}.gif')

        sport_priority = config.get('sport_id_priority', [1])
        sport_id = sport_priority[0] if isinstance(sport_priority, list) else sport_priority

        _generate_gif(
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


def _should_refresh_standings(sched):
    """Return True if standings.json needs a refresh.

    Triggers when: the file is missing, the file is older than 20 hours
    (catches the case where the program was offline for a day or more),
    or a game that is now Final was not Final during the last standings refresh.
    """
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

    if any_live:
        return False, ""

    all_pregame = bool(cached_games) and all(
        g.get('detailed_state') in {'Scheduled', 'Pre-Game', 'Warmup'}
        for g in cached_games
    )

    if any_final_undecided:
        interval_min = 2
    elif all_done:
        interval_min = 60
    elif not cached_games or all_pregame:
        interval_min = 60
    else:
        interval_min = config.get('update_interval', 14)

    last_fetch = sched.get('last_game_fetch')
    if last_fetch:
        try:
            elapsed = datetime.now() - datetime.fromisoformat(last_fetch)
            if elapsed < timedelta(minutes=interval_min):
                mins = int(elapsed.total_seconds() // 60)
                state_label = (
                    'final_undecided' if any_final_undecided
                    else 'all_done' if all_done
                    else 'pregame' if all_pregame
                    else 'pre-game'
                )
                return True, f"Throttled — {mins}min since last fetch (interval={interval_min}min, state={state_label})"
        except Exception:
            pass

    return False, ""


def _update_schedule_state(game_state_data, date_str, config, sched):
    sched['last_game_fetch'] = datetime.now().isoformat(timespec='seconds')
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
        _save_schedule_state(sched)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='MLB Display — fetch → render → display pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python main.py
  python main.py --date 2025-04-01
  python main.py --sport-id 8 --date 2023-03-21
  python main.py --local
        ''',
    )
    parser.add_argument('--date', type=str, help='Date (YYYY-MM-DD). Default: today')
    parser.add_argument('--sport-id', type=int, help='Sport ID override')
    parser.add_argument('--fetch-teams', action='store_true',
                        help='Fetch and cache all team abbreviations, then exit')
    parser.add_argument('--local', action='store_true',
                        help='Local dev mode: bypass night mode and smart polling, auto-open output')
    add_config_arg(parser)
    args = parser.parse_args()

    system_platform = platform.system()
    print(f"Running on platform: {system_platform}")
    if system_platform == 'Darwin':
        print("Development mode - e-ink display updates will be skipped")

    def _env_is_test():
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
    _no_throttle = args.local or system_platform == 'Darwin' or _is_test
    print(f"Throttle bypass: {_no_throttle} (local={args.local}, platform={system_platform}, env_test={_is_test})")

    config = load_config(args.config)

    # 3. Night mode gate
    if config.get('night_mode', False) and not _no_throttle:
        if _in_night_window(config):
            tz = config.get('timezone', 'America/Chicago')
            now_str = datetime.now(pytz.timezone(tz)).strftime('%H:%M')
            print(f"Night mode: skipping refresh ({now_str})")
            return

    dark_mode = config.get('dark_mode', False)

    # 4. Discord state gate
    discord_state = _load_discord_state()
    if discord_state:
        user = discord_state.get('requested_by', 'unknown')
        mode_req = discord_state.get('pending_mode', '')
        team_req = discord_state.get('pending_team', '')
        print(f"Discord change requested by @{user}: mode={mode_req or '(unchanged)'} team={team_req or '(unchanged)'}")
        _apply_discord_change(discord_state, config)
        overlay = _render_discord_overlay(discord_state, dark_mode=dark_mode)
        from display_eink import display_image
        display_image(overlay)
        _mark_discord_applied()

    league_mode = config.get('league_mode', 'mlb')

    # Handle --sport-id / --fetch-teams
    if args.sport_id:
        sport_id = args.sport_id
        print(f"Using specified sport: {SPORT_NAMES.get(sport_id, f'Sport ID {sport_id}')}")
        if args.fetch_teams:
            fetch_all_team_abbreviations(sport_id)
            return
    elif league_mode == 'aaa':
        sport_id = 12
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
    if args.date:
        date_str = args.date
        set_historical_mode(True)
        print(f"Using specified date: {date_str}")
    else:
        tz = config.get('timezone', 'America/Chicago')
        _now = datetime.now(pytz.timezone(tz))
        if _now.hour < 9:
            date_str = (_now.date() - timedelta(days=1)).strftime('%Y-%m-%d')
            _pre9am = True
            print(f"Before 9am — showing previous day: {date_str}")
        else:
            date_str = _now.date().strftime('%Y-%m-%d')
            print(f"Using today's date: {date_str}")

    # 5. Smart polling gate (only for automatic runs on today's date, skip in pre-5am mode)
    if not args.date and not _no_throttle and not _pre9am:
        sched = _load_schedule_state()
        skip, reason = _should_skip_poll(date_str, config, sched)
        if skip:
            print(reason)
            return
    else:
        sched = {}

    # 6. Fetch
    fetch_scoreboard_for_date(date_str, sport_id, config)

    # 7. Update schedule state
    if not args.date and not _no_throttle and not _pre9am:
        game_state_data = load_json_file('games.json').get('games', [])
        no_games = _update_schedule_state(game_state_data, date_str, config, sched)
        if no_games:
            return

    # 7b. Standings refresh
    _needs_standings = config.get('show_standings_sidebar', False) or config.get('show_wildcard_standings', False)
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
        elif not _pre9am and _should_refresh_standings(sched):
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


    # 8. Render
    output_path = os.path.join(_REPO_ROOT, 'resulting_image.bmp')
    result = render(config, date_str=date_str, output_path=output_path, bypass_cache=_no_throttle)

    if not result:
        print("No display update needed - image unchanged")
        return

    image, changed_regions = result

    # 9. Send to display
    from refresh_tracker import needs_full_refresh
    if needs_full_refresh() or not changed_regions:
        print("Scoreboard: full refresh")
        refresh_mode = 'full'
    else:
        print(f"Scoreboard: partial refresh ({len(changed_regions)} region(s))")
        refresh_mode = 'partial'

    send_to_display(output_path, changed_regions if refresh_mode == 'partial' else None)

    print(f"\n✓ Display updated successfully!")
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
