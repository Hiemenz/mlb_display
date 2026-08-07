"""Draw a "Hot Arms" panel cell (135×130) for an empty grid slot.

Shows starting pitchers with the lowest ERA over the last 14 days, from
data/streaks.json — the same daily cache as the Hot Hitters panel.

Layout and chrome come from panel_cell; only the header, the data key and the
value format differ from the other ranked panels.
"""
import panel_cell
from image_assets import ImageDraw

_HEADER = 'Hot Arms'


def _value(entry):
    """Rolling ERA, with innings pitched when the feed supplies it."""
    era = entry.get('era', '')
    ip = entry.get('ip', '')
    return f'{era} {ip}IP' if ip else era


def draw_scoreless_cell(Himage, sx, sy, streaks_data, team_data, use_logos=False):
    """Draw the hot-arms panel into the cell at pixel (sx, sy).

    Pitchers are ordered best (lowest ERA) first.

    streaks_data: dict loaded from streaks.json (expects a 'scoreless' key).
    team_data: teams dict for abbreviation lookup.
    """
    draw = ImageDraw.Draw(Himage)
    entries = (streaks_data or {}).get('scoreless', [])

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
