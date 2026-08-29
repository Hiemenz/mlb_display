# CLAUDE.md — mlb_display

## Pipeline

E-ink scoreboard (800x480) for Raspberry Pi. `main.py` orchestrates:
`fetch_games.fetch_scoreboard_for_date()` → `render_scoreboard.render()` → `display.send_to_display()`

Each stage is also a standalone CLI (see `src/fetch_games.py`, `src/render_scoreboard.py`,
`src/display.py`). `src/generate_image.py::orchestrate_score_board()` is the core rendering
entry point.

## Environment

Poetry-managed. Run everything via `poetry run <cmd>` or `poetry shell`.

```
poetry install --no-root
poetry run pytest -q --tb=short --cov --cov-report=term-missing
poetry run ruff check .
poetry run mypy
```

## GitHub / CI setup

### Branch protection (`main`, via `.github/settings.yml`, Probot Settings app)
- Enforced for admins too, no force-pushes, no deletions.
- Required status checks (must be up-to-date before merge — `strict: true`):
  - `test` (from `ci.yml`)
  - `scan` (from `code-quality.yml`)
- PR reviews: `required_approving_review_count: 0` — checks gate merges, not human review.
- Conversation resolution required before merge.

### Workflows
- **`ci.yml`** — on push to `main` and on every PR. Poetry install → `py_compile` syntax
  check → `ruff check` → `mypy` → `pytest` with coverage (xml + terminal). Posts a sticky
  coverage-table PR comment. On failure, uploads golden-image mismatches as an artifact
  (`tests/golden/_failures/`) so a diff can be promoted to the new reference by hand.
- **`code-quality.yml`** — runs `codequality scan` against `.codequality-baseline.json`
  (external `Hiemenz/code-quality` tool) on push to `main` and on every PR. This is the
  `scan` required check.
- **`auto-merge.yml`** — on PR opened/marked ready-for-review, enables GitHub auto-merge
  (squash) so the PR merges itself once required checks pass. **Do not mark a draft PR
  ready-for-review without confirming with the user first** — doing so triggers
  auto-merge immediately.
- **`docs-update.yml`** — nightly (08:00 UTC) and on push to `main` touching rendering
  source files (`src/image_*.py`, `src/generate_image.py`, `src/field_view.py`,
  `src/scorecard_view.py`, `scripts/generate_docs.py`,
  `pic/Font.ttc`), regenerates doc screenshots/demo GIF and auto-commits to `main`
  (`[skip ci]`) if anything changed.

### Coverage
- `fail_under = 98` in `pyproject.toml` — a ratchet, not a fixed target. Raise it when
  coverage improves; don't lower it to make CI pass.
- Hardware/display-I/O and one-off asset-generation scripts are excluded from coverage
  (`[tool.coverage.run] omit`) — see `src/display.py`, `src/download_logos.py`, etc.
- `discord_bot.py` has a known gap: `discord` isn't an installed dependency, so it can't
  currently be imported or tested.

### Git workflow (from global instructions — applies here)
1. `git checkout main && git pull` before starting anything.
2. `git checkout -b feature/<short-description>` — never commit directly to `main`.
3. Push, then open a **draft PR** immediately (`gh pr create --draft`) — don't wait for
   the work to be finished.
4. Keep committing to the feature branch. Never `git push origin main` directly.
5. Confirm with the user before flipping the PR from draft to ready-for-review (this
   arms `auto-merge.yml`, which will squash-merge as soon as `test` + `scan` pass).

## Lint / type-check scope
- `ruff`: `select = ["F", "E4", "E7", "E9", "B"]` — correctness-focused (unused imports
  ignored via `F401` because some modules are deliberate re-export facades), not a style
  gate. Excludes `src/waveshare_epd` and `.claude`.
- `mypy`: checks `src/` and `main.py`, lenient (`ignore_missing_imports = true`), no
  blanket annotation requirement. Excludes `src/waveshare_epd/` and `src/test_*.py`.
- `pytest`: only collects `tests/`; live-API tests are marked `live` and skipped by
  default (`MLB_LIVE_CONTRACT=1` to opt in).

## Golden-image tests
Determinism matters: wall clock, network calls, and machine identity (LAN IP) must all
be mocked in golden-image tests, or renders will vary by machine/run and spuriously fail
CI. On a CI failure, download the `golden-image-failures` artifact, drop the `_actual`
suffix from the mismatched file, and commit it to promote the new reference — but verify
the visual change is intentional first.
