# MLB Game Tracker for E-Paper Display

## Overview
Fetches and displays MLB game data on a 7.5-inch Waveshare e-paper display (800×480). Supports two display modes configured in `config/config.yaml`.

## Display Modes

### Scoreboard Mode (`scoreboard: true`)

Shows up to 15 games in a 5×3 grid. Each game tile adapts to the game state:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ...  │
│ │7:05 PM      │ │TOP 7  HR... │ │Final        │ │Final/12     │       │
│ │             │ │             │ │             │ │             │       │
│ │NYY   47-38  │ │NYY   4   ◇◇│ │NYY   7  11 0│ │CHC   3   8 0│      │
│ │BOS   41-43  │ │BOS   2   ◇ │ │BOS   3   8 1│ │MIL   4   9 0│      │
│ │             │ │B ●●○  S ●○ │ │             │ │             │       │
│ │C.Sale       │ │Last:        │ │WP: G.Cole   │ │WP: B.Lauer  │      │
│ │G.Cole       │ │Ohtani HR(42)│ │LP: C.Sale   │ │LP: J.Taillon│      │
│ └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘       │
│                                                                         │
│ ┌─────────────┐ ┌─────────────┐ ...                                    │
│ │Postponed    │ │Warmup       │                                         │
│ │             │ │             │                                         │
│ │HOU          │ │LAD          │                                         │
│ │TEX          │ │SF           │                                         │
│ │             │ │             │                                         │
│ └─────────────┘ └─────────────┘                                         │
│                                                               2025-07-04│
└─────────────────────────────────────────────────────────────────────────┘
```

Each tile shows:
- **Scheduled/Pre-Game**: start time, team records, probable pitchers
- **In Progress**: inning, score, base runners (◇), outs (●), ball/strike count, last play
- **Final**: score, hits, errors, winning/losing pitcher; `/N` appended if not 9 innings
- **Postponed/Delayed**: state displayed

### Linescore Mode (`scoreboard: false`)

Shows two detailed game scoreboards plus a live division standings table:

```
┌────────────────────────────────────────────────────────────────────────────────┐
│  75°F | Partly Cloudy | 8 mph out to CF                                        │
│         Bot 7th   1   2   3   4   5   6   7   8   9  │ R ║ H   E    Away 42% │
│  ◇      ─────────────────────────────────────────────────────────────          │
│◇   ◇    NYY        0   0   2   0   1   0   1            4   7   0    Home 57% │
│  ◇      ─────────────────────────────────────────────────────────────          │
│ ● ● ○   BOS        0   0   0   2   0   0   0            2   5   1              │
│                                                                                 │
│         Rodriguez strikes out swinging                   Fenway Park           │
├────────────────────────────────────────────────────────────────────────────────┤
│  82°F | Clear | 5 mph in from LF                                               │
│         Final     1   2   3   4   5   6   7   8   9  │ R ║ H   E              │
│         ─────────────────────────────────────────────────────────────          │
│ ●       CHC        0   1   0   0   2   0   0   0   0    3   7   0              │
│         ─────────────────────────────────────────────────────────────          │
│         MIL        0   0   0   1   0   2   0   1   X    4   9   1              │
│                                                                                 │
│         WP: B.Lauer   LP: J.Taillon              American Family Field         │
├────────────────────────────────────────────────────────────────────────────────┤
│  American League Central                                                        │
│  ────────────────────────────────────────────────────────────────────          │
│  Team          W    L    PCT    GB   STRK  L10   Home   Away                  │
│  Cleveland    52   35   .598   —    W3    7-3   28-16  24-19                  │
│  Minnesota    48   39   .552   4    L1    5-5   25-18  23-21                  │
│  Chicago      40   47   .460  12    W1    4-6   22-20  18-27                  │
│  Kansas City  38   49   .437  14    L2    3-7   21-21  17-28                  │
│  Detroit      37   50   .425  15    W2    4-6   18-24  19-26                  │
└────────────────────────────────────────────────────────────────────────────────┘
```

Each linescore shows:
- Weather (temperature, condition, wind)
- Per-inning runs with R/H/E totals
- Base runners (◇ filled = occupied), outs (●), win probability (live games)
- Last play event / WP+LP (final) / probable pitchers (pre-game)
- Venue

The standings section rotates through a randomly selected division on each refresh.

## Installation

```bash
git clone <repo>
cd mlb_display
pip install requests Pillow pytz pyyaml
```

Or with Poetry:
```bash
poetry install
```

Hardware setup: connect a Waveshare 7.5-inch V2 e-paper display to a Raspberry Pi and verify SPI is enabled.

## Configuration

Edit `config/config.yaml`:

```yaml
# Display mode
scoreboard: true          # true = 15-game grid, false = 2 linescores + standings

# Linescore mode: teams to follow (in priority order)
primary: NYY
primary_backup: BOS
primary_backup_2: NYM
secondary: NYY_DOUBLE     # second game of a doubleheader
secondary_backup: LIVE    # any in-progress game
secondary_backup_2: STL

# Refresh interval (minutes) between schedule API calls
update_interval: 14

# Scoreboard mode: live game data limits
max_live_game_calls: 15
fetch_last_play: true

# Timezone for game start times
timezone: America/Chicago

# Sport priority (first sport with games on the date wins)
sport_id_priority:
  - 1    # MLB
  - 8    # World Baseball Classic
  - 16   # Spring Training
  - 51   # International
  - 11   # College Baseball
  - 14   # Winter Leagues
```

## Usage

Run via cron or a systemd timer:

```bash
# Scoreboard mode (reads scoreboard: true from config)
python3 src/scoreboard_generate.py

# With a specific date or sport
python3 src/scoreboard_generate.py --date 2024-07-26
python3 src/scoreboard_generate.py --sport-id 8   # World Baseball Classic

# Linescore mode (reads scoreboard: false from config)
python3 src/linescore.py

# With a specific date
python3 src/linescore.py 2024-07-26

# Pre-populate team abbreviation cache (useful for non-MLB sports)
python3 src/scoreboard_generate.py --sport-id 8 --fetch-teams
```

The output image is saved to `resulting_image.bmp`. On macOS the e-ink display update is skipped automatically (development mode).

## Project Structure

```
mlb_display/
├── src/
│   ├── scoreboard_generate.py  # Scoreboard mode entry point
│   ├── linescore.py            # Linescore mode entry point
│   ├── generate_image.py       # Image rendering (both modes)
│   ├── game_data.py            # MLB API data fetching
│   ├── standings.py            # Standings data fetching
│   ├── display_eink.py         # Waveshare e-ink driver wrapper
│   ├── util.py                 # JSON/YAML helpers
│   └── waveshare_epd/          # Waveshare hardware library
├── config/
│   └── config.yaml
├── data/                       # Runtime cache (gitignored)
└── pic/
    └── Font.ttc
```

## Contributing

Fork the repository, make your changes, and open a pull request.

## License

MIT License.
