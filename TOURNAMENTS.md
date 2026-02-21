# Following Different Baseball Tournaments

Your MLB display can track multiple baseball tournaments and leagues by changing the `sport_id` in the configuration file.

## Quick Start: World Baseball Classic

To follow World Baseball Classic games:

1. **Edit `config/config.json`**:
   ```json
   {
     "sport_id": 12
   }
   ```

2. **Run the scoreboard**:
   ```bash
   python3 src/scoreboard_generate.py
   ```

The display will automatically:
- ✅ Fetch WBC games for the current date
- ✅ Download team abbreviations for national teams (USA, JPN, DOM, etc.)
- ✅ Display live scores and game states
- ✅ Show tournament matchups on your e-ink display

## Available Sport IDs

| Sport ID | Tournament/League | Notes |
|----------|------------------|-------|
| **1** | MLB (Regular Season & Playoffs) | Default setting |
| **8** | World Baseball Classic | International tournament (March) |
| **11** | College Baseball | NCAA games |
| **12** | Triple-A (AAA) | Top minor league |
| **13** | Double-A (AA) | Minor league |
| **14** | Winter Leagues | Caribbean leagues, etc. |
| **16** | Spring Training | Pre-season MLB games (also uses sportId=1) |
| **51** | International Games | Various international competitions |

## Configuration

Edit `config/config.json`:

```json
{
  "scoreboard": true,
  "primary": "NYY",           // Not used for WBC/international
  "primary_backup": "BOS",
  "primary_backup_2": "NYM",
  "secondary": "NYY_DOUBLE",
  "secondary_backup": "LIVE",
  "secondary_backup_2": "STL",
  "update_interval": "8",
  "sport_id": 8               // Change this to switch tournaments!
}
```

## WBC Team Abbreviations

The system automatically fetches team abbreviations from the MLB API. Common WBC teams include:

- **USA** - United States
- **JPN** - Japan
- **DOM** - Dominican Republic
- **PUR** - Puerto Rico
- **VEN** - Venezuela
- **MEX** - Mexico
- **CUB** - Cuba
- **KOR** - South Korea
- **NED** - Netherlands
- **ITA** - Italy
- **CAN** - Canada
- **COL** - Colombia
- **GBR** - Great Britain
- **ISR** - Israel
- **CHN** - China
- **TPE** - Chinese Taipei

## Examples

### Follow WBC during tournament
```json
{
  "sport_id": 8
}
```

### Follow Spring Training
```json
{
  "sport_id": 1
}
```
Note: Spring Training games use the same sportId as regular MLB (1).

### Follow College Baseball
```json
{
  "sport_id": 11
}
```

### Follow Caribbean Series / Winter Leagues
```json
{
  "sport_id": 14
}
```

## Important Notes

1. **Automatic Team Detection**: The recent updates handle unfamiliar teams automatically, so WBC national teams will work without additional configuration.

2. **Date Specific Games**: WBC only runs during tournament dates (typically March). Outside tournament dates, you won't see any games.

3. **Testing on macOS**: You can test WBC game fetching on your Mac - the system will generate images without attempting e-ink display updates.

4. **Team Favorites**: The `primary`, `secondary`, etc. settings are designed for MLB teams and may not work with WBC national teams. For WBC, the system shows all games.

## Troubleshooting

**No games showing up?**
- Check that the tournament is currently running
- Verify the date range (WBC runs in March typically)
- Try a specific date: `fetch_scoreboard_for_date('2023-03-09', sport_id=8)`

**Unknown team abbreviations?**
- The system auto-fetches them from the API
- If a team can't be fetched, it shows as "T{team_id}"
- Check `data/teams.json` to see cached team data

**Want to see past WBC games?**
- Uncomment and modify the date in the main function:
  ```python
  fetch_scoreboard_for_date('2023-03-21', sport_id=8)  # WBC Final 2023
  ```

## API Resources

For more information on the MLB Stats API:
- Documentation: https://statsapi.mlb.com/docs/
- Explore sports: https://statsapi.mlb.com/api/v1/sports
- View schedules: https://statsapi.mlb.com/api/v1/schedule?sportId=8&startDate=2023-03-01&endDate=2023-03-21

---

**Ready to follow the next World Baseball Classic!** 🌎⚾
