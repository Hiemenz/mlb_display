"""Replay a completed MLB game pitch-by-pitch on the e-ink display.

Fetches the full play-by-play feed once, then steps through each pitch
and renders the reconstructed game state to the display in sequence.

Usage:
    # By game primary key
    poetry run python src/replay.py --game-pk 745503

    # By date and team abbreviation (custom delay)
    poetry run python src/replay.py --date 2026-08-01 --team CHC --delay 60

    # Include non-pitch events (substitutions, pickoffs, etc.)
    poetry run python src/replay.py --date 2026-08-01 --team NYY --all-events

    # Dev mode: no display push, auto-open output image on macOS
    poetry run python src/replay.py --date 2026-08-01 --team BOS --local
"""
import argparse
import os
import platform
import subprocess
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_loader import load_config, add_config_arg
from fetch_games import fetch_scoreboard_for_date
from generate_image import orchestrate_score_board
from display import send_to_display
from image_box import set_historical_mode
from util import load_json_file
from timelapse import _fetch_game_timeline, _game_state_at_time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _lookup_date_for_game(game_pk):
    """Return the YYYY-MM-DD date for a game_pk by querying the live feed."""
    resp = requests.get(
        f'https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live'
        '?fields=gameData,datetime,originalDate',
        timeout=15,
    )
    resp.raise_for_status()
    return (resp.json()
            .get('gameData', {})
            .get('datetime', {})
            .get('originalDate', ''))


def _find_game_by_team(base_games, team_data, team_abbr):
    """Return the game dict for team_abbr from base_games, or None."""
    abbr_map = team_data.get('team_abbreviation', {})
    target = team_abbr.upper()
    for g in base_games:
        away_id = str(g.get('away_team_id', ''))
        home_id = str(g.get('home_team_id', ''))
        if (abbr_map.get(away_id, '').upper() == target
                or abbr_map.get(home_id, '').upper() == target):
            return g
    return None


def replay_game(game_pk, date_str, delay_seconds, pitches_only, config, local_mode):
    """Fetch play-by-play for game_pk and step through it pitch-by-pitch on the display."""
    set_historical_mode(True)

    print(f"Fetching schedule for {date_str}...")
    fetch_scoreboard_for_date(date_str, sport_id=None, config=config)
    base_games = load_json_file('games.json').get('games', [])
    team_data = load_json_file('teams.json') or {}
    if 'team_abbreviation' not in team_data:
        team_data = {'team_abbreviation': {}}

    base_game = next(
        (g for g in base_games if str(g.get('game_pk', '')) == str(game_pk)),
        None,
    )
    if base_game is None:
        print(f"Error: game {game_pk} not found in {date_str} schedule.")
        return

    abbr_map = team_data.get('team_abbreviation', {})
    away_abbr = abbr_map.get(str(base_game.get('away_team_id', '')), '???')
    home_abbr = abbr_map.get(str(base_game.get('home_team_id', '')), '???')
    print(f"Replaying: {away_abbr} @ {home_abbr}  (game_pk={game_pk}, {date_str})")

    print("Fetching play-by-play...")
    tl = _fetch_game_timeline(game_pk)

    all_events = tl.get('pitch_events', [])
    events = [e for e in all_events if e.get('is_pitch')] if pitches_only else all_events
    if not events:
        print("No pitch events found — nothing to replay.")
        return

    print(f"{len(events)} event(s) to display  ({delay_seconds}s between each)")

    output_path = os.path.join(_REPO_ROOT, 'resulting_image.bmp')
    is_mac = platform.system() == 'Darwin'

    for i, ev in enumerate(events):
        target_utc = ev['time']

        frame_games = []
        for g in base_games:
            if str(g.get('game_pk', '')) == str(game_pk):
                frame_games.append(_game_state_at_time(g, tl, target_utc))
            else:
                frame_games.append(dict(g))

        try:
            result = orchestrate_score_board(
                frame_games, team_data, date_str, bypass_cache=True, config=config,
            )
        except Exception as e:
            print(f"  [{i + 1}/{len(events)}] render error: {e}")
            continue

        if not result:
            continue

        image, changed_regions = result
        image.save(output_path)

        half = ev.get('half_inning', 'top')
        inn = ev.get('inning', '?')
        balls = ev.get('balls', 0)
        strikes = ev.get('strikes', 0)
        outs = ev.get('outs', 0)
        if ev.get('is_pitch') and ev.get('last_pitch_type'):
            spd = ev.get('last_pitch_speed')
            pitch_info = f"{ev['last_pitch_type']}" + (f" {spd}mph" if spd else "")
        else:
            pitch_info = "action"
        half_label = 'Top' if half == 'top' else 'Bot'
        print(f"  [{i + 1:4d}/{len(events)}] {half_label} {inn}  {balls}-{strikes}, "
              f"{outs} out — {pitch_info}")

        if local_mode:
            if is_mac:
                subprocess.run(['open', output_path], check=False)
        else:
            try:
                send_to_display(output_path, changed_regions)
            except Exception as e:
                print(f"  display error: {e}")

        if i < len(events) - 1:
            try:
                time.sleep(delay_seconds)
            except KeyboardInterrupt:
                print("\nStopped.")
                return

    print(f"\n✓ Replay complete — {len(events)} pitches shown.")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Replay a completed MLB game pitch-by-pitch on the e-ink display.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--game-pk', type=int,
                        help='Game primary key (from the MLB API).')
    parser.add_argument('--date',
                        help='Game date YYYY-MM-DD. Required when --game-pk is not given.')
    parser.add_argument('--team',
                        help='Team abbreviation (e.g. CHC, NYY). Selects the game on --date.')
    parser.add_argument('--delay', type=float, default=30.0,
                        help='Seconds to pause between pitches (default: 30).')
    parser.add_argument('--all-events', action='store_true',
                        help='Step through every event including substitutions and '
                             'pickoffs, not only actual pitch deliveries.')
    parser.add_argument('--local', action='store_true',
                        help='Dev mode: skip display push; auto-open output on macOS.')
    add_config_arg(parser)
    args = parser.parse_args()

    if not args.game_pk and not (args.date and args.team):
        parser.error('Provide --game-pk, or both --date and --team.')

    config = load_config(args.config)

    if args.game_pk:
        game_pk = args.game_pk
        if args.date:
            date_str = args.date
        else:
            print(f"Looking up date for game {game_pk}...")
            try:
                date_str = _lookup_date_for_game(game_pk)
            except Exception as e:
                parser.error(f'Could not determine date from game_pk ({e}). Pass --date.')
            if not date_str:
                parser.error('Game date not found — pass --date explicitly.')
            print(f"  Date: {date_str}")
    else:
        date_str = args.date
        set_historical_mode(True)
        fetch_scoreboard_for_date(date_str, sport_id=None, config=config)
        base_games = load_json_file('games.json').get('games', [])
        team_data = load_json_file('teams.json') or {}
        game = _find_game_by_team(base_games, team_data, args.team)
        if game is None:
            parser.error(f'No game found for team {args.team!r} on {date_str}.')
        game_pk = game['game_pk']
        away = game.get('away_team_name', '?')
        home = game.get('home_team_name', '?')
        print(f"Found: {away} @ {home}  (game_pk={game_pk})")

    replay_game(
        game_pk=game_pk,
        date_str=date_str,
        delay_seconds=args.delay,
        pitches_only=not args.all_events,
        config=config,
        local_mode=args.local,
    )


if __name__ == '__main__':
    main()
