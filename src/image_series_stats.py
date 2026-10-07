"""Draw a series-leaders panel cell (135×130) for an empty grid slot.

Same look as the season-leaders tiles, but scoped to the primary team's
current series: the top hitters and pitchers of both teams, summed across the
series' games (data/series_leaders.json, built by fetch_series_stats).
"""
import panel_cell
from image_assets import ImageDraw

_MIN_ROWS = 5   # the fetch keeps the top 5; fewer entries must not stretch to fill the cell
CATEGORIES = ['homeRuns', 'hits', 'runsBattedIn', 'battingAverage', 'strikeOuts', 'inningsPitched']
_LABELS = {
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


def available_categories(series_data):
    """The categories that have at least one entry, in display order."""
    leaders = (series_data or {}).get('leaders') or {}
    return [c for c in CATEGORIES if leaders.get(c)]


def draw_series_stats_cell(Himage, sx, sy, series_data, team_data, category, use_logos=False):
    """Draw one series-leaders category into the cell at pixel (sx, sy)."""
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
