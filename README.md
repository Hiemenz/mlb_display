# MLB E-Ink Display

Real-time MLB scoreboard for a **Waveshare 7.5″ V2 e-paper display** (800×480) running on a Raspberry Pi. Fetches live MLB data and renders it in five switchable display modes. Controllable via Discord bot.

![Full scoreboard — May 31 2026, pre-game](docs/scoreboard_pregame.png)

---

## Display Modes

Switch modes any time via `display_mode` in `config/config.yaml` or via the Discord bot.

### Scoreboard — 5×3 grid (15 games)

The default mode. All 15 games fit on one screen, with a **division standings sidebar** along both edges and a **wildcard standings strip** across the top showing team logos ordered by games back.

Each tile adapts to game state — see [Tile States](#scoreboard-tile-states) below.

**Pre-game** — shows start time, stadium, probable pitchers with season stats, team records, current streak, Vegas moneyline, and a weather forecast (temp, wind, precip source).

![Scoreboard — pre-game](docs/scoreboard_pregame.png)

**Live** — shows score, inning/half, base runners, outs, ball/strike count, per-inning linescore, and a **win probability bar** with team logos sliding to their live win probability position. Live detail line shows current pitcher, batter, fastball %, and pitch count.

![Scoreboard — live games](docs/scoreboard_live.png)

**Finals** — shows R/H/E, winning/losing pitcher (with record), save, and the winning team's logo as a large ghost watermark behind the score.

![Scoreboard — all finals](docs/scoreboard_finals.png)

---

### Linescore Mode

Two selected games shown in full detail side by side, with live division standings below.

![Linescore Mode](docs/linescore_mode.png)

---

### Field View

Single-game display with a venue-accurate outfield diagram. All 30 MLB parks are supported — the fence is drawn as a multi-segment wall with LF/LCF/CF/RCF/RF distance labels. Every batted ball is plotted on the field (most recent: filled circle with crosshair; earlier hits: open circles). A mini strike zone overlay shows pitches for the current at-bat. The right panel shows score, inning, count, outs, batter/pitcher matchup, last play text, and a mini per-inning linescore.

![Field View](docs/field_mode.png)

---

### Scorecard View

Official scorer–style at-bat grid for both teams. Each cell shows the batter's result per inning (K, BB, 1B, 2B, HR, GO, FO, etc.) with a mini base diamond indicating bases reached. Per-inning run totals and R/H/E summary at the right.

![Scorecard View](docs/scorecard_mode.png)

---

### Pitch View

Full 3×3 strike zone diagram with all pitches for the current at-bat plotted by location. Pitch types are visually differentiated (strike/ball/foul/in-play). The right panel shows the batter/pitcher matchup, season stats, and a scrollable pitch-by-pitch log with pitch type, velocity, and result.

![Pitch View](docs/pitch_mode.png)

---

## Scoreboard Tile States

Every tile in the 5×3 grid is self-contained and adapts to real-time game state.

### Pre-Game

Shows start time, stadium, **probable pitchers** with W-L and ERA, **team records** with current win/loss streak, **Vegas moneyline** odds, and a **weather forecast** for first pitch (temp, wind speed/direction, precipitation source).

![Pre-Game tile](docs/tile_pregame.png)

### Live / In Progress

Shows inning and half (e.g. `END 6`), score, **base runner diamonds** (open = empty, filled = occupied), **outs** as filled circles, **ball/strike count**, and a rolling per-inning linescore grid. Live detail shows current pitcher and batter. A win probability bar anchors the bottom with each team's logo positioned at their live win chance.

![Live tile](docs/tile_live.png)

For a closer look at the live tile layout:

![Live tile — detail](docs/tile_live_detail.png)

### Final

Shows R/H/E, **winning/losing pitcher** with record, and save. The winning team's logo renders as a large semi-transparent **ghost watermark** centered behind the score.

![Final tile](docs/tile_final.png)

---

## Feature Highlights

| Feature | Detail |
|---|---|
| **Wildcard strip** | Top row of team logos, AL left → NL right, ordered by games back |
| **Standings sidebar** | AL East/Central/West on left edge, NL on right — 1st through 5th |
| **Win probability** | Live bar with logos at their real-time win % position |
| **Live details** | Pitcher, current batter, fastball %, pitch count, last pitch speed |
| **Team logos** | Auto-fetched from ESPN CDN; per-team invert/darken config |
| **Ghost logo** | Winning team logo as watermark on Final tiles |
| **Weather** | Open-Meteo (no key needed) with stadium GPS coordinates |
| **Vegas odds** | Moneyline displayed on pre-game tiles |
| **Smart polling** | Skips API on off-days; finds next game date up to 30 days ahead |
| **Night mode** | Suppresses refreshes during configurable overnight window |
| **Morning mode** | Alternates yesterday finals ↔ today schedule until `morning_end` hour |
| **Auto timelapse** | Generates `.gif` + `.mp4` after all games go Final |
| **Discord bot** | Switch mode or team from a Discord channel; bot posts preview image |
| **Dark mode** | White-on-black; toggled via `dark_mode: true` |
| **WBC / MiLB** | Sport priority list — WBC, Triple-A, Spring Training, International |
| **Partial refresh** | Changed regions refreshed without full-screen flash |

---

## Configuration

Edit `config/config.yaml`:

```yaml
# ── Display mode ──────────────────────────────────────────────
# scoreboard | linescore | field | scorecard | pitch
display_mode: scoreboard

# ── Primary team (for single-game modes and favorite-first slot) ──
primary: NYY
primary_backup: BOS
primary_backup_2: NYM
favorite_team_first: true   # pin primary team to top-left slot

# ── Refresh ───────────────────────────────────────────────────
update_interval: 14          # minutes between schedule API calls
live_game_interval: 0        # 0 = use update_interval during live games
max_live_game_calls: 15      # max live-feed calls per game per run

# ── Timezone ──────────────────────────────────────────────────
timezone: America/Chicago

# ── Sport priority (first sport with regular-season games wins) ──
sport_id_priority:
  - 1    # MLB
  - 8    # World Baseball Classic
  - 16   # Spring Training
  - 51   # International
  - 11   # Triple-A

# ── Night / morning modes ─────────────────────────────────────
night_mode: true
night_start: 2               # hour (24h) to stop refreshing
night_end: 7                 # hour (24h) to resume
morning_alternate_games: true
morning_end: 11              # hour when "yesterday" mode gives way to today

# ── Appearance ────────────────────────────────────────────────
dark_mode: true
use_team_logos: true
small_logo_x_offset: 2

# ── Scoreboard extras ─────────────────────────────────────────
show_wildcard_standings: true
show_standings_sidebar: true
scoreboard_win_probability: true
scoreboard_live_details: true
final_linescore_minutes: 60  # minutes to keep linescore visible after Final

# ── Weather ───────────────────────────────────────────────────
weather:
  enabled: true
  cache_ttl_minutes: 60

# ── Timelapse ─────────────────────────────────────────────────
auto_generate_video: false
video_interval_min: 5
video_frame_delay_ms: 300

# ── Discord bot ───────────────────────────────────────────────
discord_token: ""
discord_guild_id: 0
discord_channel_id: 0
```

---

## Installation

```bash
git clone <repo>
cd mlb_display
poetry install

# Download team logos (MLB + WBC)
poetry run python src/download_logos.py
poetry run python src/download_logos.py --wbc

# Seed standings cache before enabling show_standings_sidebar
poetry run python src/standings.py
```

**Hardware:** Waveshare 7.5″ V2 e-paper display connected to a Raspberry Pi with SPI enabled.

**macOS / dev mode:** e-ink hardware update is skipped automatically; images are saved to `resulting_image.bmp` for local preview.

---

## Usage

```bash
# Single run (reads display_mode from config)
poetry run python main.py --local        # macOS / no hardware
poetry run python main.py                # Raspberry Pi

# Specific date or sport
poetry run python main.py --date 2026-04-19
poetry run python main.py --sport-id 8   # World Baseball Classic

# Linescore mode
poetry run python src/render_scoreboard.py --mode linescore
```

**Crontab** — run every 14 minutes:

```cron
*/14 * * * * cd /home/pi/mlb_display && poetry run python main.py >> logs/display.log 2>&1
```

**systemd** — recommended for auto-start on boot:

```ini
[Unit]
Description=MLB E-Ink Display
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/pi/mlb_display
ExecStart=/home/pi/.local/bin/poetry run python main.py
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
```

---

## Discord Bot

Control the display from a Discord channel using `!display` prefix commands.

```
!display mode scoreboard    — switch to 15-game scoreboard grid
!display mode linescore     — switch to linescore + standings
!display mode field         — switch to single-game field view
!display mode scorecard     — switch to at-bat scorecard grid
!display mode pitch         — switch to pitch location view

!display team NYY           — change the primary team
!display status             — show current mode, team, and uptime
!display help               — show all commands
```

After each command the bot posts the current display image to the channel.

### Setup

1. Create a bot at [discord.com/developers](https://discord.com/developers/applications)
2. Enable **Message Content Intent** under Bot → Privileged Gateway Intents
3. Add the token and IDs to `config/config.yaml`
4. Run alongside the display:

```bash
poetry run python src/discord_bot.py &
```

Changes are written to `data/discord_state.json`. On the next refresh cycle the display shows a brief announcement screen then switches mode.

---

## Project Structure

```
mlb_display/
├── main.py                       # Pipeline orchestrator: fetch → render → display
├── config/
│   └── config.yaml               # All settings
├── src/
│   ├── fetch_games.py            # MLB Stats API fetcher → data/games.json
│   ├── render_scoreboard.py      # Render image from cached data (CLI)
│   ├── generate_image.py         # Core rendering logic (orchestrate_score_board)
│   ├── image_box.py              # Per-tile drawing (draw_box)
│   ├── image_standings.py        # Standings sidebar + wildcard strip
│   ├── field_view.py             # Field diagram renderer
│   ├── scorecard_view.py         # At-bat scorecard renderer
│   ├── pitch_view.py             # Pitch location renderer
│   ├── game_detail_fetch.py      # MLB live feed API (pitch-by-pitch)
│   ├── standings.py              # Standings fetcher + cache
│   ├── discord_bot.py            # Discord control bot
│   ├── download_logos.py         # Bulk logo downloader (MLB + WBC)
│   ├── display_eink.py           # Waveshare driver wrapper (macOS-safe)
│   ├── display.py                # CLI wrapper for display_eink
│   ├── refresh_tracker.py        # Full-refresh interval tracker (burn-in prevention)
│   ├── config_loader.py          # load_config() — canonical config loader
│   └── util.py                   # JSON/YAML helpers, repo-root-relative paths
├── data/                         # Runtime cache (gitignored)
│   ├── games.json                # Cached game state from last fetch
│   ├── teams.json                # Team abbreviation cache
│   ├── standings.json            # Standings cache (refreshed on Final)
│   ├── discord_state.json        # Pending Discord mode changes
│   └── schedule_state.json       # Next game date (smart polling)
├── docs/                         # README screenshots
├── pic/
│   ├── Font.ttc                  # Display font
│   ├── logo_render_config.json   # Per-team logo invert/darken settings
│   └── logos/                    # Team logo PNGs (auto-downloaded)
└── output/                       # Generated images and timelapses
```

---

## License

MIT
