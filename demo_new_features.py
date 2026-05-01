"""
Demo: render a scoreboard showing all new features.

Games included:
  Box 1 — Middle inning (SV, last_play, 3 outs, no B/S, base animation phase 0)
  Box 2 — End of inning (same features, phase 1 forced → 1st+3rd highlighted)
  Box 3 — In Progress active at-bat (control, for comparison)
  Box 4 — Win prob 50/50 (logos pushed apart, W/L labels)
  Box 5 — Win prob 80/20 (logos near ends, W/L labels)
  Box 6 — Scheduled pre-game (control)
  Box 7 — Final with SV (control)
  Box 8 — No-hitter in progress (inverted header, "No-Hitter" label, inning 7)
  Box 9 — Postponed with rain emoji ghost watermark
  Box 10 — Active at-bat showing sub_event (pitching change / play event in header)
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from generate_image import draw_box
from util import load_json_file
from PIL import Image

TEAM_DATA = load_json_file('teams.json')

# ---------------------------------------------------------------------------
# Shared game template helper
# ---------------------------------------------------------------------------
BASE_GAME = {
    "double_header": "N", "series_description": "Regular Season",
    "day_night": "night", "description": "", "postpone_reason": None,
    "game_number": 1, "games_in_series": 3,
    "game_date": "2026-04-16T01:10:00Z", "game_start": "2026-04-16T01:10:00Z",
    "venue": "Fenway Park",
    "no_hitter": False, "perfect_game": False,
    "away_team_is_winner": False, "home_team_is_winner": False,
    "away_probable": None, "home_probable": None,
    "away_probable_note": None, "home_probable_note": None,
    "away_team_series_number": 1, "home_team_series_number": 1,
    "away_team_record_wins": 10, "away_team_record_losses": 8,
    "home_team_record_wins": 9, "home_team_record_losses": 9,
    "winner_name": None, "loser_name": None, "saver_name": None,
    "winner_record": None, "loser_record": None, "saver_saves": None,
    "away_hits": 0, "home_hits": 0, "away_errors": 0, "home_errors": 0,
    "away_left_on_base": 0, "home_left_on_base": 0,
    "last_pitch_type": "FB", "last_pitch_speed": 94,
    "pitch_count": 78,
}

def make_game(**kw):
    g = dict(BASE_GAME)
    g.update(kw)
    return g


# ---------------------------------------------------------------------------
# The seven demo game boxes
# ---------------------------------------------------------------------------

# Box 1 — Mid inning, save situation, last_play visible, phase 0 (1st base)
BOX_MID_SV = make_game(
    game_pk=1001,
    away_team_id=147, home_team_id=111,   # NYY vs BOS
    away_runs=3, home_runs=2,
    current_inning=8, currentInningOrdinal="8th",
    detailed_state="In Progress", inningState="Middle",
    num_of_outs=3, balls=0, strikes=0,
    runner_on_first=None, runner_on_second=None, runner_on_third=None,
    current_pitcher="D. Holmes", current_hitter=None,
    save_situation=True,
    last_play="Strikeout",
    away_win_probability=62, home_win_probability=38,
)

# Box 2 — End of inning, same setup but phase 1 forced (1st+3rd)
# We'll force phase=1 by patching time inside the render call (see below)
BOX_END = make_game(
    game_pk=1002,
    away_team_id=116, home_team_id=121,   # DET vs NYM
    away_runs=1, home_runs=3,
    current_inning=5, currentInningOrdinal="5th",
    detailed_state="In Progress", inningState="End",
    num_of_outs=3, balls=0, strikes=0,
    runner_on_first=None, runner_on_second=None, runner_on_third=None,
    current_pitcher="S. Matz", current_hitter=None,
    save_situation=False,
    last_play="Fly out",
    away_win_probability=28, home_win_probability=72,
)

# Box 3 — Active at-bat: B/S circles visible, runners on 1st and 2nd
BOX_LIVE = make_game(
    game_pk=1003,
    away_team_id=144, home_team_id=143,  # ATL vs PHI
    away_runs=4, home_runs=4,
    current_inning=7, currentInningOrdinal="7th",
    detailed_state="In Progress", inningState="Bottom",
    num_of_outs=1, balls=2, strikes=1,
    runner_on_first="Trea Turner", runner_on_second="Bryce Harper", runner_on_third=None,
    current_pitcher="A. Minter", current_hitter="K. Schwarber",
    save_situation=False,
    last_play="Single",
    away_win_probability=49, home_win_probability=51,
)

# Box 4 — Win prob 50/50: logos should be pushed apart, W/L labels visible
BOX_WP_5050 = make_game(
    game_pk=1004,
    away_team_id=139, home_team_id=142,  # TB vs MIN
    away_runs=2, home_runs=2,
    current_inning=9, currentInningOrdinal="9th",
    detailed_state="In Progress", inningState="Top",
    num_of_outs=0, balls=0, strikes=0,
    runner_on_first=None, runner_on_second=None, runner_on_third=None,
    current_pitcher="E. Fairbanks", current_hitter="C. Correa",
    save_situation=True,
    last_play=None,
    away_win_probability=50, home_win_probability=50,
)

# Box 5 — Win prob 80/20: away team heavily favoured
BOX_WP_8020 = make_game(
    game_pk=1005,
    away_team_id=136, home_team_id=158,  # SEA vs MIL
    away_runs=6, home_runs=1,
    current_inning=8, currentInningOrdinal="8th",
    detailed_state="In Progress", inningState="Top",
    num_of_outs=2, balls=1, strikes=2,
    runner_on_first=None, runner_on_second=None, runner_on_third="M. Vargas",
    current_pitcher="A. Brash", current_hitter="W. Renfroe",
    save_situation=False,
    last_play="Walk",
    away_win_probability=80, home_win_probability=20,
)

# Box 6 — Scheduled (pre-game control)
BOX_PRE = make_game(
    game_pk=1006,
    away_team_id=119, home_team_id=137,  # LAD vs SF
    away_runs=0, home_runs=0,
    current_inning=1, currentInningOrdinal="1st",
    detailed_state="Scheduled", inningState="Top",
    num_of_outs=0, balls=0, strikes=0,
    runner_on_first=None, runner_on_second=None, runner_on_third=None,
    current_pitcher=None, current_hitter=None,
    save_situation=False,
    last_play=None,
    away_win_probability=None, home_win_probability=None,
    away_probable="Y. Yamamoto", away_probable_note="3-1, 2.14 ERA",
    home_probable="L. Webb", home_probable_note="2-1, 3.12 ERA",
    game_start="2026-04-16T22:15:00Z",
)

# Box 7 — Final with save
BOX_FINAL = make_game(
    game_pk=1007,
    away_team_id=134, home_team_id=138,  # PIT vs STL
    away_runs=5, home_runs=3,
    current_inning=9,
    detailed_state="Final", inningState="Bottom",
    num_of_outs=3, balls=0, strikes=0,
    runner_on_first=None, runner_on_second=None, runner_on_third=None,
    away_team_is_winner=True,
    current_pitcher="D. Bednar", current_hitter=None,
    save_situation=False,
    winner_name="M. Keller", loser_name="S. Gray",
    saver_name="D. Bednar", saver_saves=4,
    winner_record="3-1", loser_record="1-3",
    away_hits=9, home_hits=6, away_errors=0, home_errors=1,
    last_play=None,
    away_win_probability=None, home_win_probability=None,
)

# Box 8 — No-hitter in progress: inverted header + "No-Hitter" label right-aligned
# Threshold for the label is inning >= 4; use inning 7 to make it clearly visible.
BOX_NO_HITTER = make_game(
    game_pk=1008,
    away_team_id=116, home_team_id=113,   # DET vs CIN
    away_runs=0, home_runs=2,
    current_inning=7, currentInningOrdinal="7th",
    detailed_state="In Progress", inningState="Top",
    num_of_outs=1, balls=1, strikes=2,
    runner_on_first=None, runner_on_second=None, runner_on_third=None,
    current_pitcher="C. Rodon", current_hitter="M. Vierling",
    no_hitter=True, perfect_game=False,
    save_situation=False,
    last_play="Strikeout",
    away_win_probability=30, home_win_probability=70,
)

# Box 9 — Postponed with rain emoji ghost watermark
BOX_POSTPONED = make_game(
    game_pk=1009,
    away_team_id=120, home_team_id=121,   # WSH vs NYM
    away_runs=0, home_runs=0,
    current_inning=1, currentInningOrdinal="1st",
    detailed_state="Postponed", inningState="Top",
    num_of_outs=0, balls=0, strikes=0,
    runner_on_first=None, runner_on_second=None, runner_on_third=None,
    current_pitcher=None, current_hitter=None,
    postpone_reason="Rain",
    save_situation=False,
    last_play=None,
    away_win_probability=None, home_win_probability=None,
    away_team_record_wins=12, away_team_record_losses=10,
    home_team_record_wins=11, home_team_record_losses=11,
)

# Box 10 — Active at-bat with sub_event shown in header (simulates a pitching change
# or notable play event displayed right-aligned in the inning header strip).
BOX_SUB_EVENT = make_game(
    game_pk=1010,
    away_team_id=147, home_team_id=110,   # NYY vs BAL
    away_runs=3, home_runs=3,
    current_inning=6, currentInningOrdinal="6th",
    detailed_state="In Progress", inningState="Bottom",
    num_of_outs=2, balls=3, strikes=2,
    runner_on_first="G. Stanton", runner_on_second=None, runner_on_third=None,
    current_pitcher="G. Cole", current_hitter="A. Rutschman",
    save_situation=False,
    sub_event="Pitching Change",
    last_play="Walk",
    away_win_probability=51, home_win_probability=49,
)

GAMES = [BOX_MID_SV, BOX_END, BOX_LIVE, BOX_WP_5050, BOX_WP_8020, BOX_PRE, BOX_FINAL,
         BOX_NO_HITTER, BOX_POSTPONED, BOX_SUB_EVENT]


# ---------------------------------------------------------------------------
# Render all boxes into a single 800x480 panel
# ---------------------------------------------------------------------------
img = Image.new('1', (800, 480), 1)

x_start, y_start = 32, 30
for idx, game in enumerate(GAMES):
    col = idx % 5
    row = idx // 5
    x = col * 150 + x_start
    y = row * 150 + y_start
    draw_box(img, x, y, game, TEAM_DATA,
             score_changed=False, use_logos=True, logo_x_offset=2,
             show_win_prob=True, streak_map=None)

out = os.path.join(os.path.dirname(__file__), 'demo_features.png')
img.convert('L').save(out)
print(f"Saved: {out}")

import subprocess
subprocess.run(['open', out], check=False)
