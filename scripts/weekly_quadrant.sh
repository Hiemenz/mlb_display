#!/usr/bin/env bash
# Refresh the team quadrant data and render the week + season charts.
#
# Run by hand: ./scripts/weekly_quadrant.sh
# Nothing schedules this — there is deliberately no cron entry or timer.
#
# It is written to stay cron-safe should that ever change (PATH is restored
# below, flock guards against overlap), following the same shape as
# real_estate/scripts/monthly_update.sh.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# A minimal PATH (as under cron) has neither poetry nor the venv on it.
export PATH="/home/pi/.local/bin:$PATH"

LOCKFILE="/tmp/mlb_quadrant.lock"
LOGFILE="data/quadrant.log"

exec 200>"$LOCKFILE"
if ! flock -n 200; then
    echo "$(date -Iseconds) — previous run still in progress, skipping" >> "$LOGFILE"
    exit 0
fi

{
    echo "===== $(date -Iseconds) starting weekly quadrant refresh ====="
    # --force: the fetch's own 6-hour TTL would otherwise skip the weekly run
    # whenever the display happened to refresh the data earlier the same day.
    poetry run python src/fetch_team_quadrant.py --force

    # Last 7 days is the weekly view: logo at this week's position, arrow back
    # to a dot at the season-to-date position. Season is rendered alongside it
    # for context.
    poetry run python scripts/team_quadrant_chart.py --grain week \
        --out output/quadrant_week.png
    poetry run python scripts/team_quadrant_chart.py --grain season \
        --out output/quadrant_season.png

    echo "$(date -Iseconds) wrote output/quadrant_week.png and output/quadrant_season.png"
    echo "===== $(date -Iseconds) finished ====="
} >> "$LOGFILE" 2>&1
