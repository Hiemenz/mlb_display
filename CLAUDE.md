# CLAUDE.md — mlb_display

## Pipeline

E-ink scoreboard (800x480) for Raspberry Pi. `main.py` orchestrates:
`fetch_games.fetch_scoreboard_for_date()` → `render_scoreboard.render()` → `display.send_to_display()`

Each stage is also a standalone CLI (see `src/fetch_games.py`, `src/render_scoreboard.py`,
`src/display.py`). `src/generate_image.py::orchestrate_score_board()` is the core rendering
entry point.

## Environment

uv-managed. Run everything via `uv run <cmd>`.

```
uv sync
uv run pytest -q --tb=short --cov --cov-report=term-missing
uv run ruff check .
uv run mypy
```

## GitHub / CI setup

### Branch protection (`main`, via `.github/settings.yml`, Probot Settings app)
- Enforced for admins too, no force-pushes, no deletions.
- Required status checks (must be up-to-date before merge — `strict: true`):
  - `test` (from `ci.yml`)
  - `scan` (from `code-quality.yml`)
- PR reviews: `required_approving_review_count: 0` — checks gate merges, not human review.
- Conversation resolution required before merge.
- Repo settings (same file): `allow_auto_merge: true`, `delete_branch_on_merge: true` —
  a PR's head branch is deleted on merge.
- Because of `strict: true`, once one PR merges every other open PR is BEHIND and its
  auto-merge waits. Bring it up to date with
  `gh api -X PUT repos/Hiemenz/mlb_display/pulls/<N>/update-branch` (the installed `gh`
  has no `gh pr update-branch`); checks re-run and auto-merge fires.

### Workflows
- **`ci.yml`** — on push to `main` and on every PR. uv sync → `py_compile` syntax
  check → `ruff check` → `mypy` → `pytest` with coverage (xml + terminal). Posts a sticky
  coverage-table PR comment. On failure, uploads golden-image mismatches as an artifact
  (`tests/golden/_failures/`) so a diff can be promoted to the new reference by hand.
- **`code-quality.yml`** — runs `codequality scan` against `.codequality-baseline.json`
  (external `Hiemenz/code-quality` tool) on push to `main` and on every PR. This is the
  `scan` required check.
- **`auto-merge.yml`** — on PR `opened`, `ready_for_review` and `synchronize`, for any
  non-draft PR, enables GitHub auto-merge (squash) so the PR merges itself once required
  checks pass. A PR opened as non-draft is armed at once, so always open drafts. **Do not
  mark a draft PR ready-for-review without confirming with the user first** — doing so
  triggers auto-merge immediately.
- **`docs-update.yml`** — nightly (08:00 UTC), manual (`workflow_dispatch`), and on push to
  `main` touching `src/image_box.py`, `src/image_grid.py`, `src/image_standings.py`,
  `src/image_featured.py`, `src/image_assets.py`, `src/image_utils.py`,
  `src/generate_image.py`, `src/field_view.py`, `src/scorecard_view.py`,
  `scripts/generate_docs.py` or `pic/Font.ttc` (other `image_*` modules, e.g. the comic,
  don't trigger it). Regenerates doc screenshots/demo GIF and auto-commits to `main`
  (`[skip ci]`) if anything changed.

### Coverage
- `fail_under = 98` in `pyproject.toml` — a ratchet, not a fixed target. Raise it when
  coverage improves; don't lower it to make CI pass.
- Hardware/display-I/O, one-off asset-generation scripts and the Slack bot
  (`src/slack_bot.py`) are excluded from coverage (`[tool.coverage.run] omit`) — see
  `src/display.py`, `src/download_logos.py`, etc.

### Config keys
- Every top-level key in `config/config.yaml` needs an entry in `SETTINGS` in
  `src/slack_settings.py` (bool / int / select / int_list / …), or
  `tests/test_slack_settings.py::test_every_real_config_key_is_covered` fails CI.

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
  The repo root has an `__init__.py`, so mypy refuses to run in a checkout whose folder
  name isn't a valid Python identifier (e.g. a `.claude/worktrees/some-name` worktree):
  name worktrees without hyphens, or run mypy on a copy.
- `pytest`: only collects `tests/`; live-API tests are marked `live` and skipped by
  default (`MLB_LIVE_CONTRACT=1` to opt in).

## Golden-image tests
Determinism matters: wall clock, network calls, and machine identity (LAN IP) must all
be mocked in golden-image tests, or renders will vary by machine/run and spuriously fail
CI. On a CI failure, download the `golden-image-failures` artifact, drop the `_actual`
suffix from the mismatched file, and commit it to promote the new reference — but verify
the visual change is intentional first.

## Comic story arcs
`src/comic_arcs.py` splits the Peanuts dailies into story arcs (written to the gitignored
`data/comics/<name>/prefs.json` by `scripts/build_comic_arcs.py`; re-run it on the display
Pi after changing the detector). Score any change against the dated storylines in
`KNOWN_STORYLINES` with `uv run --group comics python scripts/eval_comic_arcs.py`
(`--dump meta.jsonl` once, then `--metadata meta.jsonl` to skip the download), before and
after.
