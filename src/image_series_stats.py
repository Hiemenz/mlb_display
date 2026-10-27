"""Draw a series-leaders panel cell (135×130) for an empty grid slot.

Same look as the season-leaders tiles, but scoped to the primary team's
current series: the top hitters and pitchers of both teams, summed across the
series' games (data/series_leaders.json, built by fetch_series_stats).
"""
from datetime import date, timedelta

import panel_cell
from image_assets import ImageDraw

_MAX_AGE_DAYS = 2   # a series is "current" while a game was played in the last 2 days
_MIN_ROWS = 5   # the fetch keeps the top 5; fewer entries must not stretch to fill the cell
KEY_PLAYERS = 'keyPlayers'
CATEGORIES = [KEY_PLAYERS, 'homeRuns', 'hits', 'runsBattedIn', 'battingAverage', 'strikeOuts', 'inningsPitched']
_LABELS = {
    KEY_PLAYERS:      'Series Stars',
    'homeRuns':       'Series HR',
    'hits':           'Series Hits',
    'runsBattedIn':   'Series RBI',
    'battingAverage': 'Series AVG',
    'strikeOuts':     'Series K',
    'inningsPitched': 'Series IP',
}


def _format(cat, value):
    """Strip only the leading zero of an average ('0.345' -> '.345', '1.000' stays)."""
    if cat == 'battingAverage' and value.startswith('0.'):
        return value[1:]
    return value


def is_current(series_data, today=None):
    """True for a series that is in progress or finished within the last ``_MAX_AGE_DAYS`` days.

    The data file is only rewritten when the primary team has a game, so on an
    off day or after elimination it still holds the last series; its newest
    played game's date says how stale that is.
    """
    last = (series_data or {}).get('last_played')
    if not last:
        return False
    try:
        newest = date.fromisoformat(last)
    except ValueError:
        return False
    return (today or date.today()) - newest <= timedelta(days=_MAX_AGE_DAYS)


def available_categories(series_data, today=None):
    """The categories that have at least one entry, in display order; none for a stale series."""
    if not is_current(series_data, today):
        return []
    leaders = (series_data or {}).get('leaders') or {}
    teams = (series_data or {}).get('teams') or {}
    has_key = any(t.get('batters') or t.get('pitchers') for t in teams.values())
    return [c for c in CATEGORIES if (has_key if c == KEY_PLAYERS else leaders.get(c))]


def _key_lines(team):
    """Display rows for one team: (name, stat) for each hitter, then each pitcher."""
    rows = [(b['name'], f"{b['homeRuns']}HR {b['rbi']}RBI" if b['homeRuns'] or b['rbi']
             else f"{b['hits']}-{b['atBats']}") for b in team.get('batters', [])]
    rows += [(p['name'], f"{p['ip']}IP {p['strikeOuts']}K") for p in team.get('pitchers', [])]
    return rows


def _draw_key_players(Himage, sx, sy, series_data, team_data, use_logos):
    """Both teams' standout hitters and pitchers, each team under its own logo/abbr band."""
    draw = ImageDraw.Draw(Himage)
    panel_cell.draw_chrome(draw, sx, sy, _LABELS[KEY_PLAYERS])
    abbrs = (team_data or {}).get('team_abbreviation', {})
    teams = [(tid, _key_lines(t)) for tid, t in ((series_data or {}).get('teams') or {}).items()]
    teams = [(tid, rows) for tid, rows in teams if rows]
    if not teams:
        panel_cell.draw_empty(draw, sx, sy, 'No data', panel_cell.row_font(_MIN_ROWS))
        return Himage

    font = panel_cell.row_font(_MIN_ROWS + 1)
    band_h = 14
    n_rows = sum(len(r) for _, r in teams)
    row_h = min(12, (panel_cell.CELL_H - panel_cell.HEADER_H - 2 - band_h * len(teams)) // max(n_rows, 1))
    y = sy + panel_cell.HEADER_H + 1
    for tid, rows in teams:
        abbr = abbrs.get(str(tid), '')
        if use_logos and abbr:
            panel_cell.paste_row_logo(Himage, abbr, str(tid), sx + panel_cell.PAD, y - 2, 14, band_h)
        draw.text((sx + panel_cell.PAD + (17 if use_logos else 0), y), abbr, font=font, fill=0)
        draw.text((sx + panel_cell.PAD + (17 if use_logos else 0) + 1, y), abbr, font=font, fill=0)
        draw.line([(sx + panel_cell.PAD, y + band_h - 2), (sx + panel_cell.CELL_W - panel_cell.PAD, y + band_h - 2)], fill=0)
        y += band_h
        for name, stat in rows:
            val_x = sx + panel_cell.CELL_W - int(font.getlength(stat)) - panel_cell.PAD
            draw.text((sx + panel_cell.PAD, y), panel_cell.truncate(font, name, val_x - 3 - sx - panel_cell.PAD),
                      font=font, fill=0)
            draw.text((val_x, y), stat, font=font, fill=0)
            y += row_h
    return Himage


def draw_series_stats_cell(Himage, sx, sy, series_data, team_data, category, use_logos=False):
    """Draw one series-leaders category into the cell at pixel (sx, sy)."""
    if category == KEY_PLAYERS:
        return _draw_key_players(Himage, sx, sy, series_data, team_data, use_logos)
    draw = ImageDraw.Draw(Himage)
    entries = ((series_data or {}).get('leaders') or {}).get(category, [])
    font_row = panel_cell.row_font(max(len(entries), _MIN_ROWS))
    panel_cell.draw_chrome(draw, sx, sy, _LABELS.get(category, category))

    if not entries:
        panel_cell.draw_empty(draw, sx, sy, 'No data', font_row)
        return Himage

    return panel_cell.draw_ranked_rows(
        Himage, draw, sx, sy, entries, font_row,
        lambda e: _format(category, e.get('value', '')),
        abbr_map=(team_data or {}).get('team_abbreviation', {}),
        use_logos=use_logos, min_rows=_MIN_ROWS,
    )
