"""Replay a full MLB game day on the e-ink display.

Steps through the day in baseball time: every --delay real seconds the
display advances --step minutes of actual game time, showing all games
as they unfolded.

Usage:
    poetry run python src/replay.py --date 2026-08-01
    poetry run python src/replay.py --date 2026-08-01 --step 2 --delay 30
    poetry run python src/replay.py --date 2026-08-01 --local
"""
import argparse
import os
import platform
import subprocess
import sys
import time
from datetime import timedelta

import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_loader import load_config, add_config_arg
from fetch_games import fetch_scoreboard_for_date
from generate_image import orchestrate_score_board
from display import send_to_display
from image_box import set_historical_mode
from util import load_json_file
from timelapse import _fetch_game_timeline, _game_state_at_time, _any_game_active

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DEFAULT_STEP_MINUTES = 1    # advance 1 baseball minute per display refresh
_DEFAULT_DELAY_SECONDS = 20  # wait 20 real seconds between refreshes


def replay_day(date_str, step_minutes, real_delay, config, local_mode):
    """Replay all games from date_str, advancing step_minutes of baseball time per refresh.

    Pushes a fresh scoreboard to the display every real_delay seconds.
    Dead periods (before first pitch, between games) are skipped instantly.
    """
    set_historical_mode(True)

    tz_str = config.get('timezone', 'America/Chicago')
    local_tz = pytz.timezone(tz_str)

    print(f"Fetching schedule for {date_str}...")
    fetch_scoreboard_for_date(date_str, sport_id=None, config=config)
    base_games = load_json_file('games.json').get('games', [])
    team_data = load_json_file('teams.json') or {}
    if 'team_abbreviation' not in team_data:
        team_data = {'team_abbreviation': {}}

    if not base_games:
        print("No games found — nothing to replay.")
        return

    print(f"Fetching play-by-play for {len(base_games)} game(s)...")
    game_timelines = {}
    all_first_pitches = []
    all_last_plays = []

    for game in base_games:
        game_pk = game.get('game_pk')
        if not game_pk:
            continue
        print(f"  game {game_pk}...", end=' ', flush=True)
        try:
            tl = _fetch_game_timeline(game_pk)
            game_timelines[str(game_pk)] = tl
            anchor = (tl.get('first_actual_pitch_utc')
                      or tl.get('first_pitch_utc')
                      or tl.get('scheduled_start_utc'))
            if anchor:
                all_first_pitches.append(anchor)
            if tl.get('last_play_utc'):
                all_last_plays.append(tl['last_play_utc'])
            print("ok")
        except Exception as e:
            print(f"error: {e}")

    if not game_timelines or not all_first_pitches:
        print("No timeline data — aborting.")
        return

    start_utc = min(all_first_pitches)
    end_utc = (max(all_last_plays) + timedelta(minutes=5)) if all_last_plays \
              else start_utc + timedelta(hours=5)

    start_local = start_utc.astimezone(local_tz)
    end_local = end_utc.astimezone(local_tz)
    total_steps = int((end_utc - start_utc).total_seconds() / 60 / step_minutes) + 1

    print(f"Replaying {start_local.strftime('%H:%M')}–{end_local.strftime('%H:%M')} {tz_str}")
    print(f"{total_steps} step(s) × {step_minutes} baseball min  "
          f"→ {real_delay}s real time between each")

    output_path = os.path.join(_REPO_ROOT, 'resulting_image.bmp')
    is_mac = platform.system() == 'Darwin'
    current_utc = start_utc
    step = 0

    while current_utc <= end_utc:
        step += 1
        time_label = current_utc.astimezone(local_tz).strftime('%H:%M')

        if not _any_game_active(game_timelines, current_utc):
            current_utc += timedelta(minutes=step_minutes)
            continue

        frame_games = []
        for game in base_games:
            pk_str = str(game.get('game_pk', ''))
            tl = game_timelines.get(pk_str)
            frame_games.append(
                _game_state_at_time(game, tl, current_utc) if tl else dict(game)
            )

        try:
            result = orchestrate_score_board(
                frame_games, team_data, date_str, bypass_cache=True, config=config,
            )
        except Exception as e:
            print(f"  [{step:4d}/{total_steps}] {time_label} render error: {e}")
            current_utc += timedelta(minutes=step_minutes)
            continue

        if result:
            image, changed_regions = result
            image.save(output_path)
            print(f"  [{step:4d}/{total_steps}] {time_label}")

            if local_mode:
                if is_mac:
                    subprocess.run(['open', output_path], check=False)
            else:
                try:
                    send_to_display(output_path, changed_regions)
                except Exception as e:
                    print(f"  display error: {e}")

        current_utc += timedelta(minutes=step_minutes)

        try:
            time.sleep(real_delay)
        except KeyboardInterrupt:
            print("\nStopped.")
            return

    print("\n✓ Replay complete.")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Replay a full MLB game day on the e-ink display.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--date',
                        help='Game date to replay (YYYY-MM-DD). '
                             'Falls back to replay_date in config.yaml.')
    parser.add_argument('--step', type=float, default=None,
                        help=f'Baseball minutes to advance per refresh. '
                             f'Falls back to replay_step_minutes in config.yaml '
                             f'(default: {_DEFAULT_STEP_MINUTES}).')
    parser.add_argument('--delay', type=float, default=None,
                        help=f'Real seconds between display updates. '
                             f'Falls back to replay_delay_seconds in config.yaml '
                             f'(default: {_DEFAULT_DELAY_SECONDS}).')
    parser.add_argument('--local', action='store_true',
                        help='Dev mode: skip display push; auto-open output on macOS.')
    add_config_arg(parser)
    args = parser.parse_args()

    config = load_config(args.config)

    date_str = args.date or config.get('replay_date', '').strip()
    if not date_str:
        parser.error(
            'No date supplied. Pass --date or set replay_date in config.yaml '
            '(editable via the config server).'
        )

    step_minutes = args.step if args.step is not None \
        else float(config.get('replay_step_minutes', _DEFAULT_STEP_MINUTES))
    real_delay = args.delay if args.delay is not None \
        else float(config.get('replay_delay_seconds', _DEFAULT_DELAY_SECONDS))

    replay_day(
        date_str=date_str,
        step_minutes=step_minutes,
        real_delay=real_delay,
        config=config,
        local_mode=args.local,
    )


if __name__ == '__main__':
    main()
