"""Draw an active hitting-streak panel cell (135×130) for an empty grid slot.

Shows batting-average leaders over a rolling 14-day window (position players
only — pitchers are excluded by the statGroup filter in the fetch), from
data/streaks.json.

Layout and chrome come from panel_cell; only the header, the data key and the
value format differ from the other ranked panels.
"""
import panel_cell
from image_assets import ImageDraw

_HEADER = 'Hot Hitters'


def _value(entry):
    """Batting average, with games played when the feed supplies it."""
    avg = entry.get('avg', '')
    games = entry.get('games', '')
    return f'{avg} {games}G' if games else avg


def draw_streaks_cell(Himage, sx, sy, streaks_data, team_data, use_logos=False):
    """Draw the hot-hitters panel into the cell at pixel (sx, sy).

    streaks_data: dict loaded from streaks.json (expects a 'streaks' key).
    team_data: teams dict for abbreviation lookup.
    """
    draw = ImageDraw.Draw(Himage)
    entries = (streaks_data or {}).get('streaks', [])

    font_row = panel_cell.row_font(len(entries))
    panel_cell.draw_chrome(draw, sx, sy, _HEADER)

    if not entries:
        panel_cell.draw_empty(draw, sx, sy, 'No data', font_row)
        return Himage

    return panel_cell.draw_ranked_rows(
        Himage, draw, sx, sy, entries, font_row, _value,
        abbr_map=(team_data or {}).get('team_abbreviation', {}),
        use_logos=use_logos,
    )
