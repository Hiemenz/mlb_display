# Changelog

All notable changes to this project are documented here.
Entries link to the pull request where the work landed.

---

## [Unreleased] — PR #185

### Added
- **Streak badge** on standings sidebar logos — `W7` / `L3` in 7 px font, centered below each team logo in the inter-slot gap (no overlap with the logo). Appears in both the regular 32 px sidebar and the fullscreen standings columns.
- **No-hitter / perfect game alert** — tile header inverts (white-on-black) when a no-hitter or perfect game is active from the 6th inning on. Applies to the standard single-cell tile, the wide featured cell, and the fullscreen view. No double-inversion when a run also scored.
- **Docs screenshot pipeline** (`scripts/generate_docs.py`) — single command that renders all 14 `docs/` screenshots plus an animated `demo.gif` from deterministic fixture data (no live API, no logos required).
- **Nightly docs workflow** (`.github/workflows/docs-update.yml`) — auto-regenerates screenshots on a daily cron and on every push to `main` that touches a rendering source file; commits changes back with `[skip ci]`.
- **README overhaul** — animated `demo.gif` at the top, new _Standings Sidebar_ and _Wide Cell_ sections with screenshots, updated Feature Highlights table.

---

## 2026-06 — PRs #172–#184

### Added
- **Wide-cell featured tile** (#172, #174, #175, #182) — when fewer than 15 games are scheduled, a 2-slot (285 × 130 px) tile replaces two normal cells for the primary team's live game. Right panel shows the current at-bat's pitch zone, ball/strike/out count, pitcher/batter rows with last pitch type and speed, and a K strip.
- **K-strip milestone badge** (#183) — every 10th strikeout in the K strip renders as a `10`, `20`, etc. badge instead of a normal `K` so the sequence stays readable at a glance.
- **Mobile-first config web server** (#181) — `python src/config_server.py` serves a local web page for changing the most common settings (team, mode, dark mode, logos, standings, wide-cell toggle) from a phone without SSH. Writes via a line-based patcher that preserves YAML comments.
- **QR code in spare scoreboard cell** (#181, #182) — when fewer than 15 games are shown, a spare cell displays a QR code pointing to the config web server. Toggle via `show_config_qr` in `config.yaml`.
- **Playoff bracket display** (#171) — postseason bracket drawn on the scoreboard when enabled.
- **Pitch broadcast overlay** (#171) — strike-zone diagram overlay for individual pitch rendering.
- **DH scheduling fix** (#171) — corrects double-header game ordering for split-admit DH pairs.
- **PC base indicators** (#182) — pitching-change event now correctly shows base-runner state.
- **Golden-image regression tests** (#178) — snapshot comparison tests for all major render paths; mismatch artifacts uploaded as CI artifacts for easy promotion.

### Infrastructure
- CI pipeline expanded (#176, #177) — ruff, mypy, and coverage gates run on every PR and push to main.
- Test coverage raised from 31 % → 97 % (#180) then 99 % (#184); `fail_under` ratchet set to 99.
- Dead 2-linescore + standings renderer removed (#179).

---

## 2026-05 — PRs #151–#171

### Added
- **Between-innings linescore** (#167) — replaces bases/outs/count with a tic-tac-toe-style linescore grid during the break between half-innings. Adaptive font sizes based on inning count.
- **Fullscreen linescore** (#165, #166) — live fullscreen view gained a full per-inning linescore, end-of-game detection, and an always-inverted large header for easy reading.
- **Inning triangle indicator** (#154) — small triangle next to the inning number points up (top) or down (bottom) half.
- **Sac fly / sac bunt abbreviations** (#155) — play descriptions now render `SAC F` / `SAC B` instead of cryptic abbreviations.
- **Equal-width linescore cells** (#159) — each inning column is a fixed 10 × 12 px grid, centered in the tile, with `X` rendered as diagonal lines.
- **Linescore winner logo** (#105) — winning team's logo appears at the tail of the linescore after a game ends.
- **Series sweep detection** (#94) — postseason sweep gets a visual callout.
- **Tomorrow-game preview** (#121, #132) — Final tiles show the next scheduled game between the same teams in the win-probability strip.
- **Inversion events** — headers invert (white-on-black) for stolen bases (#124), mid-inning pitching changes (#123), challenge/review events (#125, #127), and run-scored highlights (#149).
- **Backwards K** (#115, #117, #118) — looking strikeouts rendered as a mirrored K in the K strip.
- **RBI prefix in play header** (#115) — play description line shows `RBI:` prefix when a run scores.
- **Walk-off detection** (#94) — end-of-game walk-off state handled cleanly.
- **Morning alternating mode** (#97, #150) — until `morning_end`, the display cycles between yesterday's finals and today's schedule so last night's results are visible after waking up. Weekday/weekend cutoff configurable.
- **Sweep / partial-refresh coordinator** (#94, #168) — up to 9 scoreboard cells can be refreshed individually per cycle; a full-screen refresh fires every 20 cycles to prevent burn-in.

### README (#151)
- Full docs overhaul with mode screenshots and per-tile state documentation.

---

## 2026-04 — PRs #97–#150

### Added
- **Featured team fullscreen mode** (#97) — set `FEATURED_TEAM_FULLSCREEN=true` for a dedicated 800 × 480 live view for your primary team.
- **Win probability bar** (#34, #35, #40) — live horizontal bar with each team's logo positioned at their real-time win percentage.
- **Wildcard standings strip** (#41, #43) — top row shows eligible AL / NL teams ordered by games back, with a bracket around the top-3 playoff spots.
- **Division standings movement indicators** (#102, #103, #104) — L-bracket appears on the outer edge of a standings logo when that team changed rank in the last 20 hours. Persisted across render cycles.
- **Clinch indicators** (#105) — thin / thick box around a standings slot when a team clinches a playoff spot or division.
- **Live tile details line** (#47–#50) — pitcher, current batter, fastball percentage, and pitch count shown below the linescore during active at-bats.
- **Rain delay display** (#51, #52) — delayed game state renders reason and expected restart time.
- **Linescore grid layout** (#53–#55) — per-inning grid replaced the old single-line format.
- **Next-batters between-innings** (#59) — tile switches to "due-up" panel (leadoff / on-deck / in-hole) plus incoming pitcher during the break.
- **Weather forecast on pre-game tiles** (#58) — temperature, wind speed/direction, and precipitation source from Open-Meteo.
- **Challenge circles on tile header** (#169) — challenge / review events render circles instead of inverting the full header.
- **Game duration in R/H/E header** (#72, #73) — total game time shown on Final tiles.
- **Suspended / completed-early states** handled consistently.
- **AAA / Triple-A league mode** (#86, #90) — `league_mode: aaa` swaps standings for IL/PCL divisions; AAA sport priority works in the fetch pipeline.

### Fixed
- Odds glyph alignment (#60, #133, #134).
- Sidebar vertical alignment (#61, #62).
- Pitcher ERA display (#44).
- Stale scoreboard mid-game state (#46).
- AB label flip-flop on batter transition (#156).
- Logo centering in linescore and scoreboard grid (#95).

---

## 2025–Early 2026 — PRs #20–#96

### Added
- **Field view** (#21, #29, #32) — venue-accurate outfield diagram for all 30 MLB parks drawn as a multi-segment wall with distance labels. Batted balls plotted by location.
- **Scorecard view** (#21, #105) — official scorer–style at-bat grid for both teams (K, BB, 1B, HR, GO, FO, etc.) with mini base diamonds and per-inning run totals.
- **Pitch view** (#21) — full 3 × 3 strike zone diagram with all pitches plotted for the current at-bat. Pitch type / velocity log on the right panel.
- **Discord bot** (#22) — prefix commands (`!display mode`, `!display team`, `!display status`) let you switch mode or team from a Discord channel; bot posts a preview image after each command.
- **Smart polling** (#22) — skips the schedule API when no games are scheduled for today; searches up to 30 days ahead for the next game date and caches the result.
- **WBC / international support** (#20, #22, #25) — `sport_id_priority` list lets WBC, Spring Training, Triple-A, and international games surface when MLB is off-season.
- **WBC logos** (#20) — downloaded from ESPN countries CDN; 19/20 teams covered.
- **Team logo pipeline** (#12–#14) — auto-fetched from ESPN CDN; per-team `invert` and `darken_white` settings in `logo_render_config.json`.
- **Dark mode** (#15) — `dark_mode: true` inverts the entire display.
- **Partial e-ink refresh** (#16, #17, #168) — changed regions only; burn-in prevention via full refresh every N cycles.
- **Save badge on Final tiles** — `SV` shown when a save was recorded.
- **Vegas moneyline odds** (#39, #69) — American-format odds on pre-game tiles, cached via env var.
- **Team records + streak on pre-game tiles** (#37, #57) — W-L record and current streak shown during Scheduled / Pre-Game / Warmup states.
- **Series record indicator** (#75, #76) — current series wins / losses shown in the tile header.
- **Ghost logo watermark** — winning team's logo rendered semi-transparent behind the Final score.
- **Auto timelapse** — `auto_generate_video: true` generates a `.gif` + `.mp4` after all games go Final each day.
- **Night mode** (#11) — suppresses display refreshes during a configurable overnight window (`night_start` / `night_end`).

### Fixed
- EPD deep-sleep init (#4) — use `epd.init()` instead of `init_fast()` after deep sleep.
- Probable pitcher name fitting (#2) — long names truncated to tile width before wrapping.

---

## v1.0 — Initial Release

- Basic 5 × 3 scoreboard grid (15 games) showing score, inning, and game state.
- Division standings sidebar (AL left, NL right).
- Waveshare 7.5″ V2 e-paper driver integration.
- Cron-based refresh pipeline: `fetch_games.py` → `render_scoreboard.py` → `display.py`.
- Poetry-managed Python environment.
