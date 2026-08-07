"""Draw a recent-transactions ticker cell (150x150) for an empty grid slot.

Shows the most recent MLB transactions (IL moves, call-ups/demotions,
signings, etc.) fetched by standings.fetch_transactions(). Mirrors
image_leaders.draw_leaders_cell's layout so it drops into a grid slot
identically.
"""
import panel_cell
from image_assets import _get_font, ImageDraw, _logo_small
from image_utils import TRANSACTION_TYPE_ABBR

_HEADER = 'Transactions'


def draw_transactions_cell(Himage, sx, sy, transactions_data, team_data, max_rows=None, use_logos=False):
    """Draw a recent-transactions panel into the cell at pixel position
    (sx, sy), the same 150x150 footprint as a normal single-game grid cell.

    transactions_data: the 'transactions' list from transactions.json
    team_data: the teams dict (for team_abbreviation lookup, currently unused
        since team_abbr is already embedded per-entry, kept for parity with
        draw_leaders_cell's signature)
    """
    draw = ImageDraw.Draw(Himage)
    entries = list(transactions_data or [])

    font_row = panel_cell.row_font(len(entries))
    panel_cell.draw_chrome(draw, sx, sy, _HEADER)

    if not entries:
        panel_cell.draw_empty(draw, sx, sy, 'No recent moves', font_row)
        return Himage

    # Row count is capped by available vertical space; 13px is the smallest
    # row height that stays legible at row_font_size 11 (mirrors image_leaders).
    _max_by_height = (panel_cell.CELL_H - 20) // 13
    n_rows = min(len(entries), max_rows if max_rows is not None else _max_by_height, _max_by_height)
    shown = entries[:n_rows]
    row_h = (panel_cell.CELL_H - 20) // max(n_rows, 1)
    row_pad = 2 if row_h >= 13 else 1

    logo_size = min(18, row_h)
    abbr_col_w = max((int(font_row.getlength(e.get('team_abbr', '') + ' ')) for e in shown), default=0)
    logo_col_x = sx + panel_cell.PAD
    name_x = logo_col_x + (logo_size + 2 if use_logos else abbr_col_w)

    for i, entry in enumerate(shown):
        ry = sy + 20 + i * row_h

        abbr = entry.get('team_abbr', '')
        team_id = entry.get('team_id', '')
        name = entry.get('player_name', '')
        type_desc = entry.get('type_desc', '')
        tag = TRANSACTION_TYPE_ABBR.get(type_desc, type_desc)

        if use_logos and abbr:
            try:
                logo = _logo_small(abbr, team_id, size=logo_size)
                if logo:
                    logo_y = ry + (row_h - logo.height) // 2
                    Himage.paste(logo, (logo_col_x, logo_y))
            except Exception:
                pass
        else:
            draw.text((sx + panel_cell.PAD, ry + row_pad), abbr, font=font_row, fill=0)

        # tag right-aligned; measured first so the name gets whatever's left.
        tag_w = int(font_row.getlength(tag))
        tag_x = sx + panel_cell.CELL_W - tag_w - panel_cell.PAD

        name = panel_cell.truncate(font_row, name, tag_x - 2 - name_x)

        draw.text((name_x, ry + row_pad), name, font=font_row, fill=0)
        draw.text((tag_x, ry + row_pad), tag, font=font_row, fill=0)

    return Himage
