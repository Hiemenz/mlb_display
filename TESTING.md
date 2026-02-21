# Local Testing Guide

Test the MLB display locally on your Mac without the e-ink hardware!

## Quick Start

```bash
# Navigate to project directory
cd /Users/kevinhiemenz/git/mlb_display

# Test with today's games (uses config.json sport_id)
python3 src/scoreboard_generate.py

# View the generated image
open resulting_image.bmp
```

## Testing with Specific Dates

### Test with any MLB game date:
```bash
python3 src/scoreboard_generate.py --date 2024-07-26
```

### Test recent MLB games:
```bash
# MLB games from 2024 (15 games!)
python3 src/scoreboard_generate.py --date 2024-07-26 --sport-id 1

# MLB Opening Day 2024
python3 src/scoreboard_generate.py --date 2024-03-28 --sport-id 1
```

### Test World Baseball Classic:
```bash
# Note: Historical WBC data may not be available in the API
# When WBC 2026 happens, use dates during the tournament
python3 src/scoreboard_generate.py --date 2026-03-15 --sport-id 8
```

### Test Spring Training:
```bash
python3 src/scoreboard_generate.py --date 2024-02-28 --sport-id 1
```

### Test MLB Playoffs:
```bash
# 2024 World Series Game 1
python3 src/scoreboard_generate.py --date 2024-10-25 --sport-id 1
```

## Command-Line Options

| Option | Description | Example |
|--------|-------------|---------|
| `--date` | Specify game date (YYYY-MM-DD) | `--date 2024-07-26` |
| `--sport-id` | Override config sport_id | `--sport-id 8` |
| No arguments | Use today + config sport_id | (default) |

## Available Sport IDs

- `1` = MLB (regular season & playoffs)
- `8` = World Baseball Classic
- `11` = College Baseball
- `12` = Triple-A
- `13` = Double-A
- `14` = Winter Leagues
- `51` = International

## Viewing Generated Images

The script creates `resulting_image.bmp` in the project root:

```bash
# macOS
open resulting_image.bmp

# Or view in VS Code
code resulting_image.bmp
```

## Example Testing Workflow

### 1. Test WBC Final 2023 (Japan vs USA):
```bash
python3 src/scoreboard_generate.py --date 2023-03-21 --sport-id 8
open resulting_image.bmp
```

### 2. Check what teams were found:
```bash
cat data/teams.json | grep -A 2 "team_abbreviation"
```

### 3. View game data:
```bash
cat data/games.json
```

## Verifying API Responses

### Test if games exist for a date:
```bash
# Check MLB games on a date
curl "https://statsapi.mlb.com/api/v1/schedule?startDate=2024-07-26&endDate=2024-07-26&sportId=1"

# Check WBC games
curl "https://statsapi.mlb.com/api/v1/schedule?startDate=2023-03-21&endDate=2023-03-21&sportId=8"
```

### Get help:
```bash
python3 src/scoreboard_generate.py --help
```

## Troubleshooting

### "No games found"
- Check that games actually occurred on that date
- Verify the sport_id is correct
- Try the curl command above to check API response

### "Module not found" errors
Install dependencies:
```bash
# If using poetry
poetry install

# Or with pip
pip3 install pillow requests pytz
```

### Image not updating
- Check that the game data actually changed
- The system skips updates if data is identical (to preserve e-ink)
- Delete `data/old_scoreboard_state.json` to force refresh

### Team abbreviations showing as "T123"
- This is normal for some minor league or international teams
- The API might not have abbreviation data for that team
- Check `data/teams.json` to see what was cached

## Data Files Created

When you run the script, these files are created/updated:

```
data/
├── games.json                    # Parsed game data
├── teams.json                    # Team abbreviations cache
├── old_scoreboard_state.json     # Previous state (for change detection)
└── standings.json                # Division standings (if run)

resulting_image.bmp               # Generated scoreboard image
```

## Finding Good Test Dates

### WBC 2023 dates:
- **Pool Play**: March 8-15, 2023
- **Quarterfinals**: March 16-17, 2023
- **Semifinals**: March 20, 2023
- **Final**: March 21, 2023 (Japan vs USA)

### MLB 2024 notable dates:
- **Opening Day**: March 28, 2024
- **All-Star Game**: July 16, 2024
- **Playoffs Start**: October 1, 2024
- **World Series**: October 25 - November 1, 2024

### Finding current games:
```bash
# Today's MLB games
python3 src/scoreboard_generate.py

# Yesterday's games (if today has none)
python3 src/scoreboard_generate.py --date $(date -v-1d +%Y-%m-%d)
```

## Pro Tips

1. **Start with recent MLB games** - easier to verify results
2. **Use WBC 2023-03-21** - guaranteed to have exciting games (Finals!)
3. **Check API first** with curl if no games show up
4. **View teams.json** after each run to see what teams were discovered
5. **macOS = safe testing** - won't try to use e-ink hardware

## Next Steps

Once tested locally:
1. Deploy to Raspberry Pi
2. Set up as a scheduled service (cron/systemd timer)
3. Let it automatically update with live games!

---

**Happy Testing!** 🧪⚾
