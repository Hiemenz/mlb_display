#!/usr/bin/env python3
"""
Test emoji mapping functionality end-to-end.
Run from project root: poetry run python src/test_emoji.py
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from PIL import Image
from datetime import date
import generate_image as gi

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")

# ── Test 1: _emoji_codepoint ────────────────────────────────────
print("\n[1] _emoji_codepoint")
check("poop -> 1f4a9", gi._emoji_codepoint("\U0001f4a9") == "1f4a9",
      f"got {gi._emoji_codepoint(chr(0x1f4a9))!r}")
check("baseball -> 26be", gi._emoji_codepoint("\u26be") == "26be",
      f"got {gi._emoji_codepoint(chr(0x26be))!r}")
check("flag US -> 1f1fa-1f1f8", gi._emoji_codepoint("\U0001f1fa\U0001f1f8") == "1f1fa-1f1f8",
      f"got {gi._emoji_codepoint(chr(0x1f1fa)+chr(0x1f1f8))!r}")

# ── Test 2: _try_download_emoji ─────────────────────────────────
print("\n[2] _try_download_emoji (downloads poop emoji)")
ok = gi._try_download_emoji("\U0001f4a9")
check("download succeeded", ok)
dl_path = os.path.join(gi.emojidir, "1f4a9.png")
check("file exists on disk", os.path.exists(dl_path))
if os.path.exists(dl_path):
    check("file is non-empty", os.path.getsize(dl_path) > 100,
          f"size={os.path.getsize(dl_path)}")

# ── Test 3: _load_emoji_gray with injected mapping ─────────────
print("\n[3] _load_emoji_gray (inject BOS -> poop)")
# Clear caches so our injection takes effect
gi._emoji_cache.clear()
gi._team_emojis = {"BOS": "\U0001f4a9"}

img = gi._load_emoji_gray("BOS")
check("returns an Image", img is not None)
if img is not None:
    check("mode is grayscale L", img.mode == "L", f"got {img.mode}")
    check("size is reasonable", img.size[0] > 10 and img.size[1] > 10,
          f"got {img.size}")

no_img = gi._load_emoji_gray("NYY")
check("unmapped team returns None", no_img is None)

# ── Test 4: _load_logo_gray returns emoji when mapped ──────────
print("\n[4] _load_logo_gray returns emoji for mapped team")
gi._emoji_cache.clear()
gi._team_emojis = {"BOS": "\U0001f4a9"}
logo = gi._load_logo_gray("BOS", "111")
check("_load_logo_gray returns image for mapped team", logo is not None)
if logo is not None:
    check("returned image is grayscale", logo.mode == "L")

# ── Test 5: Generate a full scoreboard with emoji mapping ──────
print("\n[5] Full scoreboard render with BOS mapped to poop emoji")
gi._emoji_cache.clear()
gi._team_emojis = {"BOS": "\U0001f4a9", "LAD": "\u26be"}

# Reuse the test_scoreboard matchup approach
MATCHUPS = [
    ('NYY', 'BOS', 7, 3),
    ('TB',  'TOR', 2, 5),
    ('BAL', 'CWS', 10, 1),
    ('CLE', 'DET', 3, 6),
    ('KC',  'MIN', 8, 2),
    ('HOU', 'TEX', 4, 7),
    ('LAA', 'ATH', 1, 9),
    ('SEA', 'NYM', 6, 3),
    ('PHI', 'ATL', 2, 5),
    ('MIA', 'WSH', 7, 0),
    ('CHC', 'MIL', 4, 3),
    ('STL', 'PIT', 9, 2),
    ('CIN', 'LAD', 1, 4),
    ('SF',  'SD',  6, 5),
    ('COL', 'AZ',  3, 8),
]
all_teams = sorted({t for m in MATCHUPS for t in (m[0], m[1])})
_id = {t: str(i + 1) for i, t in enumerate(all_teams)}
team_data = {'team_abbreviation': {v: k for k, v in _id.items()}}

WP = ['Smith'] * 15
LP = ['Jones'] * 15

games = []
for g, (away, home, asc, hsc) in enumerate(MATCHUPS):
    games.append({
        'game_pk': g + 2000,
        'away_team_id': _id[away],
        'home_team_id': _id[home],
        'detailed_state': 'Final',
        'away_runs': asc, 'home_runs': hsc,
        'away_hits': asc + 3, 'home_hits': hsc + 2,
        'away_errors': 0, 'home_errors': 0,
        'away_team_is_winner': asc > hsc,
        'home_team_is_winner': hsc > asc,
        'winner_name': WP[g], 'loser_name': LP[g],
        'current_inning': 9,
        'game_start': '7:05 PM',
        'away_probable': None, 'home_probable': None,
        'away_team_record_wins': '50', 'away_team_record_losses': '40',
        'home_team_record_wins': '45', 'home_team_record_losses': '45',
        'perfect_game': False, 'no_hitter': False,
        'save_situation': False, 'last_play': None,
    })

canvas = Image.new('1', (800, 480), 255)
result_img = gi.draw_out_of_town_score_board(
    canvas, games, team_data, str(date.today()),
    changed_game_ids=None, use_logos=True,
)

out_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
out_path = os.path.join(out_dir, 'test_emoji_scoreboard.png')
result_img.save(out_path)
check("scoreboard image saved", os.path.exists(out_path))
check("image is non-trivial size", os.path.getsize(out_path) > 500,
      f"size={os.path.getsize(out_path)}")
print(f"  -> saved to {out_path}")

# ── Summary ─────────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed} checks")
if failed:
    sys.exit(1)
else:
    print("All checks passed!")
