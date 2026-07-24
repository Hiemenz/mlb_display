"""Draw an active hitting-streak panel cell (135×130) for an empty grid slot.

Shows the current top hitting streaks fetched from the MLB Stats API
(data/streaks.json). Mirrors image_leaders.draw_leaders_cell layout so it
drops into a grid slot identically.
"""
from image_assets import _get_font, ImageDraw, _logo_small

_CELL_W = 135
_CELL_H = 130
_PAD = 2

_HEADER = 'Hot Hitters'


def draw_streaks_cell(Himage, sx, sy, streaks_data, team_data, use_logos=False):
    """Draw the hot-hitters panel into the cell at pixel (sx, sy).

    Shows batting-average leaders over a rolling 14-day window (position
    players only — pitchers excluded by statGroup filter in the fetch).

    streaks_data: dict loaded from streaks.json (expects 'streaks' key).
    team_data: teams dict for abbreviation lookup.
    """
    draw = ImageDraw.Draw(Himage)

    entries = (streaks_data or {}).get('streaks', [])
    abbr_map = (team_data or {}).get('team_abbreviation', {})

    font_hdr = _get_font(14)
    row_font_size = 12 if len(entries) <= 6 else 11
    font_row = _get_font(row_font_size)

    draw.line([(sx, sy), (sx + _CELL_W - 1, sy)], fill=0)
    draw.line([(sx, sy + 20), (sx + _CELL_W - 1, sy + 20)], fill=0)
    hdr_w = int(font_hdr.getlength(_HEADER))
    hdr_x = sx + (_CELL_W - hdr_w) // 2
    draw.text((hdr_x, sy + 3), _HEADER, font=font_hdr, fill=0)
    draw.text((hdr_x + 1, sy + 3), _HEADER, font=font_hdr, fill=0)

    draw.line([(sx, sy + _CELL_H - 1), (sx + _CELL_W - 1, sy + _CELL_H - 1)], fill=0, width=1)

    if not entries:
        draw.text((sx + _PAD, sy + 60), 'No data', font=font_row, fill=0)
        return Himage

    row_h = (_CELL_H - 20) // max(len(entries), 1)
    row_pad = 2 if row_h >= 13 else 1

    rank_col_w = max(
        (int(font_row.getlength(str(e.get('rank', i + 1)) + '.')) for i, e in enumerate(entries)),
        default=0,
    )
    logo_size = min(18, row_h)
    logo_col_x = sx + _PAD + rank_col_w + 2
    name_x = logo_col_x + (logo_size + 2 if use_logos else 0)

    for i, entry in enumerate(entries):
        ry = sy + 20 + i * row_h

        rank = str(entry.get('rank', i + 1))
        name = entry.get('name', '')
        team_id = entry.get('team_id', '')
        abbr = entry.get('abbr') or abbr_map.get(team_id, '')
        avg = entry.get('avg', '')
        games = entry.get('games', '')
        val = f'{avg} {games}G' if games else avg

        draw.text((sx + _PAD, ry + row_pad), rank + '.', font=font_row, fill=0)

        if use_logos and abbr:
            try:
                logo = _logo_small(abbr, team_id, size=logo_size)
                if logo:
                    lx = logo_col_x + (logo_size - logo.width) // 2
                    ly = ry + (row_h - logo.height) // 2 + 2
                    Himage.paste(logo, (lx, ly))
            except Exception:
                pass

        val_w = int(font_row.getlength(val))
        val_x = sx + _CELL_W - val_w - _PAD

        # Suffix team abbr before name when no logos; shows "Judge NYY" style
        display_name = name
        if not use_logos and abbr:
            display_name = name

        max_name_w = val_x - 2 - name_x
        while display_name and int(font_row.getlength(display_name)) > max_name_w:
            display_name = display_name[:-1]

        draw.text((name_x, ry + row_pad), display_name, font=font_row, fill=0)
        draw.text((val_x, ry + row_pad), val, font=font_row, fill=0)

    return Himage
