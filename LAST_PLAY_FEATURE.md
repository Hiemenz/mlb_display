# Last Play Result Feature

## Overview

When a game is **In Progress**, the scoreboard now displays the last batter result in the game box instead of showing the current pitcher/hitter matchup.

## What It Shows

The last play result includes descriptions like:
- **"Single to left field"**
- **"Home run to center"**
- **"Strikeout swinging"**
- **"Ground ball double play"**
- **"Walk"**
- **"Fly out to right field"**
- etc.

## How It Works

### For In-Progress Games:
1. The system detects games with `detailed_state = "In Progress"`
2. Makes an additional API call to get live game feed data
3. Extracts the last play description
4. Displays it in the game box

### For Completed/Scheduled Games:
- Shows pitcher names (Final games)
- Shows probable pitchers (Scheduled games)
- No additional API calls made

## Display Format

```
┌─────────────────────────┐
│ BOT 7                   │
│ NYY    5    7    0      │
│ BOS    3    6    1      │
│ Last:                   │
│ Single to left field    │
└─────────────────────────┘
```

## Technical Details

### API Calls
- **Schedule endpoint**: Gets basic game info (always called)
- **Game feed endpoint**: Gets live play-by-play (only for in-progress games)
  - URL: `https://statsapi.mlb.com/api/v1/game/{gamePk}/feed/live`
  - Only called when `detailed_state == "In Progress"`

### Performance
- Minimal impact: Only 1 extra API call per in-progress game
- Typically 0-5 in-progress games at any time
- Cached in `data/games.json` between refreshes

### Fallback Behavior
If the last play data isn't available:
- Shows current pitcher and hitter instead
- No error messages
- Graceful degradation

## Testing

### Test with a Live Game:
```bash
# When games are in progress (afternoon/evening during season)
poetry run python src/scoreboard_generate.py

# View the scoreboard
open resulting_image.bmp
```

### Find Live Games:
```bash
# Check today's schedule
curl "https://statsapi.mlb.com/api/v1/schedule?sportId=1" | python3 -m json.tool
```

## Code Locations

### Fetching Logic:
- **File**: `src/scoreboard_generate.py`
- **Function**: `get_last_play_result(game_pk)`
- **Called from**: `parse_games()` for in-progress games

### Display Logic:
- **File**: `src/generate_image.py`
- **Function**: `draw_box()`
- **Section**: Lines 481-493 (In Progress games)

## Examples

### What You'll See During Live Games:

**Exciting plays:**
- ✅ "Home run to right center"
- ✅ "Triple to right field"
- ✅ "Ground ball double play"

**Regular plays:**
- ✅ "Single to center field"
- ✅ "Ground out to second"
- ✅ "Fly out to left field"

**Long descriptions are truncated:**
- ✅ "Ground ball to shortstop, throw to fir..." (if > 45 chars)

### What You Won't See:

For **scheduled games**:
- Shows probable pitchers instead

For **final games**:
- Shows winning/losing pitchers instead

For **historical games** (testing old dates):
- Last play data not available (API limitation)
- Falls back to pitcher/hitter display

## Customization

### Change Display Text:
Edit `src/generate_image.py` line 487:
```python
draw.text((start_x + 5, start_y + 25 + 59), 'Last:', font=font14, fill=0)
```
Change `'Last:'` to `'Result:'`, `'Play:'`, etc.

### Change Truncation Length:
Edit `src/generate_image.py` line 485:
```python
if len(last_play) > 45:
    last_play = last_play[:42] + '...'
```
Adjust the `45` and `42` values.

### Always Show Pitcher/Hitter:
Comment out the last play logic in `src/generate_image.py`:
```python
# if last_play:
#     ...
# else:
    draw.text(...)  # Show pitcher/hitter
```

## Troubleshooting

**"Fetching live game data" messages:**
- Normal! Shows it's getting last play data
- Only happens for in-progress games

**No last play showing:**
- Game might not have recent play data yet
- Falls back to showing pitcher/hitter
- Check game actually has `detailed_state = "In Progress"`

**Slow loading:**
- Extra API call per in-progress game
- Usually only 1-3 seconds delay
- Only happens when games are live

## Future Enhancements

Potential improvements:
- Cache last plays for a few minutes to reduce API calls
- Show pitch count or velocity
- Show runner advancement on the play
- Color code based on play type (out vs hit)

---

**Enjoy the live action!** ⚾🔥
