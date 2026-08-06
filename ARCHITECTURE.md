# Architecture

How `mlb_display` turns the MLB Stats API into pixels on an 800×480 e-ink panel.

This document covers structure and the reasoning behind it. For setup, configuration
keys and screenshots see [README.md](README.md); for contributor workflow and CI rules
see [CLAUDE.md](CLAUDE.md).

---

## 1. The pipeline

Three stages, orchestrated by `main.py`, each also runnable as a standalone CLI:

```
                    ┌─────────────┐
   MLB Stats API ──▶│    fetch    │──▶ data/*.json
                    └─────────────┘
                           │
                    ┌─────────────┐
   data/*.json ────▶│   render    │──▶ resulting_image.bmp + changed_regions
                    └─────────────┘
                           │
                    ┌─────────────┐
   .bmp ───────────▶│   display   │──▶ e-ink panel (partial or full refresh)
                    └─────────────┘
```

| Stage | Entry point | Standalone CLI |
|---|---|---|
| Fetch | `fetch_games.fetch_scoreboard_for_date()` | `python src/fetch_games.py` |
| Render | `render_scoreboard.render()` → `generate_image.orchestrate_score_board()` | `python src/render_scoreboard.py` |
| Display | `display.send_to_display()` | `python src/display.py` |

`main.py` is the only place the three meet. It also owns everything about *when* to run
them — night windows, smart polling, refresh gates — which is the bulk of its logic.

**The filesystem is the interface between stages.** Nothing is passed in memory across
stage boundaries; every stage reads and writes `data/*.json`. That is what makes each
stage independently runnable, makes the render path testable without network access, and
lets the GIF/timelapse tooling replay a day from disk.

---

## 2. Why it is shaped this way

Three constraints drive nearly every design decision. If a piece of code looks
over-complicated, it is usually one of these:

### 2.1 E-ink refreshes are expensive and visible

A *full* refresh flashes the entire panel black/white for about a second. A *partial*
refresh updates a rectangle silently, but leaves residual charge that accumulates as
ghosting. So the renderer does not just produce an image — it produces an image **plus
the list of rectangles that actually changed**, and the display layer refreshes only
those.

This is why `orchestrate_score_board()` returns `(image, changed_regions)` rather than
just an image, and why so much state is persisted between runs: to compute a diff, you
must remember the previous frame.

An empty `changed_regions` list means "full refresh".

### 2.2 The API lies about time, and the Pi's clock may not be local

Games are reported `In Progress` from their scheduled start, before a pitch is thrown.
Final games take minutes to receive decisions. `divisionRank` is present-but-`null` for
much of the year.

Separately, the Pi's system clock is often UTC while the display is configured for a
local timezone. **All date arithmetic must go through `main._local_now(config)`** — a
bare `datetime.now()` rolls over to "tomorrow" six hours early on a UTC-clocked Pi and
silently fetches the wrong day's schedule.

### 2.3 Every API call costs latency on a Raspberry Pi

Polling is adaptive rather than fixed (§4), and each auxiliary data source has its own
staleness gate so a panel nobody enabled never costs a request.

---

## 3. Module map

### Fetch layer — network in, `data/*.json` out

| Module | Responsibility |
|---|---|
| `fetch_games.py` | Scoreboard for a date; the largest fetcher. Also next-day schedule, team abbreviations, win probability, odds, pitcher stats |
| `standings.py` | Division standings, playoff bracket, transactions, postseason-window detection |
| `fetch_leaders.py` | Season stat leaders (HR/AVG/ERA/Saves/Hits) |
| `fetch_streaks.py` | Hot Hitters / Hot Arms rolling streaks |
| `fetch_news.py` | Team or league headlines |
| `fetch_derby.py` | Home Run Derby bracket |
| `game_detail_fetch.py` | Per-game detail for the scorecard, pitch and field views |
| `weather.py` | Open-Meteo forecasts, with its own TTL cache |

### Render layer — `data/*.json` in, `PIL.Image` out

| Module | Responsibility |
|---|---|
| `generate_image.py` | **Core orchestrator.** Change detection, layout selection, refresh regions |
| `image_grid.py` | Grid packing — which game gets which cell, and at what size |
| `image_box.py` | The game tile itself, in all four sizes (normal / wide / triple / fields) |
| `image_featured.py` | Single-game fullscreen mode |
| `image_standings.py` | Sidebars, wildcard header, playoff bracket, tickers |
| `image_idle.py` | The no-games-today screen |
| `image_assets.py` | Fonts, logos, mascots — all asset loading and caching |
| `image_utils.py` | Shared pure helpers (name formatting, geometry, magic numbers, rank parsing) |
| `image_<panel>.py` | One module per filler panel: leaders, streaks, magic, news, transactions, deadline, lineup, scoreless, derby |
| `scorecard_view.py`, `pitch_view.py` | Alternate display modes (scorecard, pitch plot) |
| `stadium_polygons.py` | Per-park field geometry for the spray chart, consumed by `image_box._draw_field_cell` |

### Display layer

| Module | Responsibility |
|---|---|
| `display.py` | Dispatch — real panel, or a no-op on macOS/dev |
| `display_eink.py` | Waveshare driver wrapper; partial vs full refresh |
| `refresh_tracker.py` | Hourly anti-ghosting full-refresh timer |
| `waveshare_epd/` | Vendored hardware driver (excluded from lint and coverage) |

---

## 4. Scheduling and polling

`main.py` decides whether to do anything at all, in this order:

1. **Night window** — inside it, return immediately (`_in_night_window`).
2. **Date selection** (`_resolve_target_date`) — `--date` wins; after the morning cutoff
   use today; inside the morning window show the previous day so last night's finals
   stay up through breakfast. With `morning_alternate_games` on, that window instead
   alternates between yesterday and today every 5 minutes.
3. **Smart polling gate** (`_should_skip_poll`) — adaptive interval by slate state:

   | Slate state | Interval |
   |---|---|
   | A Final game still missing decisions | 2 min |
   | Any game live | `live_game_interval` (default 1 min) |
   | Between doubleheader games | 5 min |
   | All games done, or all pre-game | 60 min |
   | Mixed | `update_interval` (default 15 min) |

4. **Support-data refresh** — standings, bracket, transactions, news, leaders, streaks.

### Window semantics

`util.in_hour_window(start, end, hour)` is the single implementation for both the night
and dark windows. Windows may wrap past midnight (`20 → 7`). **`start == end` is an
empty window, not a 24-hour one** — treating equal bounds as always-inside meant one
misconfigured pair could suppress every refresh indefinitely with no visible cause.
Turning a window off is what `night_mode: false` is for.

### Refresh gates

Every auxiliary source goes through `main._should_refresh()`, which fires on either a
stale/missing cache or a game going Final since *that source's* last refresh.

> **Each caller must pass its own `final_pks_key`.** Two panels sharing one key means
> whichever refreshes first records the Finals and starves the other for the rest of the
> day. This was a real bug: the streaks panel shared the leaders gate and consequently
> never updated whenever the leaders panel was enabled.

---

## 5. Change detection

`orchestrate_score_board()` decides whether to render at all, and what changed. It
compares against several persisted snapshots, because different things change for
different reasons:

| File | Detects |
|---|---|
| `old_scoreboard_state.json` | Any game-data change — the primary "did anything happen" check |
| `score_alerts.json` | Score changes specifically, which invert the tile header |
| `old_grid_positions.json` | A game moving cells because the packing changed |
| `old_linescore_window_state.json` | A Final game's linescore window expiring |
| `old_header_state.json` | Header strip content (ticker rotation, bracket, wildcard) |
| `force_full_refresh.json` | Signal to `main.py` that a full refresh is required |

Three of these exist to catch changes **that game data alone cannot reveal**:

- A Final game's linescore grid gives way to WP/LP after `final_linescore_minutes` — the
  visuals change with no data change at all.
- A game can move to a different cell purely because *another* game went live and
  repacked the grid. Its own data is identical, so it never appears in the changed set
  and its old cell would keep showing a stale tile.
- A ticker rotating to the next page changes only the header strip.

Without these, a partial refresh would leave stale pixels on screen indefinitely — until
the hourly anti-ghosting refresh happened to clear them.

Similarly, a **dark-mode transition** inverts the whole image while game data stays
byte-identical, so `main.py` bypasses the render cache across that boundary rather than
letting `render()` short-circuit and skip the forced full refresh.

---

## 6. Grid layout

`image_grid.compute_grid_layout()` returns `(ordered_games, slots)` where each slot is
`(slot_type, grid_col, grid_row)`. It is computed **once** and handed to both the
renderer and the refresh-region math — two independent calls could diverge (config
edited mid-render by the phone config server) and leave regions that no longer match
what was drawn.

Tiles come in four widths, and live games are promoted to larger tiles when space allows:

| Tile | Columns | Renderer |
|---|---|---|
| normal | 1 (150px) | `draw_box` |
| wide | 2 (~300px) | `draw_wide_box` |
| triple | 3 (~435px) | `draw_triple_box` |
| fields | varies | `draw_fields_box` |

Games that cannot be placed (live-tile expansion, `hide_non_live_games`, or more than 15
games) do not vanish — they are surfaced in the header strip via the overflow ticker.

Header strip priority: **overflow ticker → playoff bracket → wildcard standings →
transactions.**

---

## 7. `image_box.py` and the size of `draw_box`

`image_box.py` is the largest module in the repo, and `draw_box()` is the largest
function in it (~1300 lines). This is acknowledged debt, being reduced incrementally.

The reason it resisted decomposition: it renders a single 150×150 tile whose every
element — header text, score, bases, count, ghosts, banners, footers — is positioned
relative to shared geometry (`start_x`, `start_y`, `s`, `horizonta_len`) and gated on the
same set of state flags. Extracting a block meant threading eight to twelve parameters
through it, which cost more clarity than it bought.

### `_TileCtx`

The unlock was a per-tile context object holding what every helper needs anyway:

```python
ctx = _TileCtx(Himage, start_x, start_y, scale, use_logos, logo_x_offset)
ctx.x, ctx.y, ctx.s        # origin and scale
ctx.w, ctx.h               # tile size (135×110, scaled)
ctx.font24 … ctx.font9     # the five sizes, pre-loaded at this scale
ctx.bold(xy, text, font)   # the 1px-offset bold effect
ctx.bold_centred(...)      # centred horizontally in the tile
ctx.paste(img, xy)         # paste AND refresh ctx.draw
```

Helpers now take two or three arguments instead of ten-plus, which is what makes further
extraction cheap rather than a net loss.

**`ctx.paste()` exists specifically because pasting invalidates the current `ImageDraw`.**
Routing pastes through the context refreshes the handle centrally, so a helper can't
silently draw into a stale one — previously that had to be remembered at every call site,
and forgetting it produces drawing that goes nowhere with no error.

`draw_box` still keeps local aliases (`draw`, `font14`, `start_x`, …) for the body it has
not yet absorbed; new code should use `ctx` directly.

### What has been extracted

Pieces that are genuinely self-contained, where the parameter list stays honest:

- `_normalize_game_state` / `_game_has_started` — collapse API states into the handful
  the renderer branches on. Pure, and copies before mutating.
- `_compute_layout_flags` — the booleans selecting the linescore grid over the normal
  score layout.
- `_draw_background_ghosts` — the postponed/suspended emoji and winner-logo watermarks.
- `_in_final_linescore_window` / `_final_linescore_window_expired` — the two ends of the
  Final-game linescore window.
- `_compute_series_state` — the series-context flags. Regular-season and postseason
  series complete on different conditions (see §9), so the shared "is this series over"
  test is computed once rather than repeated across the sweep and overline conditions.
- `_draw_win_probability_bar`, `_draw_game_end_time`, `_draw_duration_and_dh_labels`.
- `_draw_live_situation_panel` — bases, count, outs and the next-batters panel.
- `_draw_pitchers_of_record` — the WP/LP/SV lines on a completed game, including the
  fit strategy that shortens the name before it drops the (W-L) record.
- `_draw_header_right_text` — the right-anchored, shrink-to-fit header label. Venue and
  delay-reason were the same shape with different fit strategies (shrink vs truncate).
- `_draw_bold_text` — the 1-bit panel has no synthetic font weight, so "bold" is the same
  string drawn twice one pixel apart. This pattern appeared ~30 times inline.

`draw_box` is now ~1,060 lines, down from 1,630. The largest block left is the live
score/pitch-detail body (~180 lines), which shares more local state with its surroundings
than anything extracted so far.

Golden-image tests make this refactoring safe: any extraction that changes a single pixel
fails immediately. They are the reason a mechanical, script-driven extraction is viable
here at all.

---

## 8. Testing

```bash
poetry run pytest -q --tb=short --cov --cov-report=term-missing
poetry run ruff check .
poetry run mypy
```

**Golden-image tests** render known fixtures and compare byte-for-byte against references
in `tests/golden/`. They are the safety net for all rendering work.

Determinism is a hard requirement: **wall clock, network calls, and machine identity (LAN
IP) must all be mocked**, or renders vary by machine and fail CI spuriously.

On a CI failure, download the `golden-image-failures` artifact, drop the `_actual` suffix
from the mismatched file and commit it to promote the new reference — but confirm the
visual change was intended first.

Coverage is a **ratchet** (`fail_under = 98`): raise it when coverage improves, never
lower it to make CI pass. Hardware I/O and one-off asset scripts are excluded via
`[tool.coverage.run] omit`.

Live-API tests are marked `live` and skipped unless `MLB_LIVE_CONTRACT=1`.

---

## 9. Gotchas

Things that have caused real bugs, worth knowing before editing:

- **`dict.get(key, default)` does not substitute the default for a present-but-`None`
  value.** `standings.py` always writes `divisionRank`, storing `None` when the API omits
  it, so `int(t.get('divisionRank', 99))` raises `TypeError`. Use
  `image_utils.division_rank()`.
- **Never call a bare `datetime.now()` for date arithmetic** — see §2.2.
- **Do not share a refresh gate between two panels** — see §4.
- **`game_date` is a local date**, so compare it against a local "today". Comparing
  against a UTC today expires evening games early once they cross midnight UTC.
- **Historical mode (`--date`) must not write to caches** — `_get_or_set_final_time()`
  records a first-seen-Final timestamp, so guard on `_historical_mode` before calling it.
- **`config.yaml` can change mid-render** (phone config server), so compute layout once
  and pass it around rather than recomputing.
