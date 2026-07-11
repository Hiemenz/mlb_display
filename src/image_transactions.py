"""Draw a recent-transactions ticker cell (150x150) for an empty grid slot.

Shows the most recent MLB transactions (IL moves, call-ups/demotions,
signings, etc.) fetched by standings.fetch_transactions(). Mirrors
image_leaders.draw_leaders_cell's layout so it drops into a grid slot
identically.
"""
from image_assets import _get_font, ImageDraw, _logo_small

# Matches the visible footprint of a normal single-game grid box
# (horizonta_len x vertical_len+20 in image_box.draw_box), not the full
# 150x150 grid slot, so the two line up exactly.
_CELL_W = 135
_CELL_H = 130
_PAD = 2
_HEADER = 'Transactions'

# Trim MLB's verbose typeDesc down to something that fits a narrow ticker row.
_TYPE_ABBR = {
    'Status Change':     'IL',
    'Recalled':          'Recall',
    'Optioned':          'Option',
    'Selected':          'Select',
    'Designated for Assignment': 'DFA',
    'Released':          'Release',
    'Signed':            'Sign',
    'Trade':             'Trade',
    'Claimed off Waivers': 'Waiver',
    'Outrighted':        'Outright',
}


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

    font_hdr = _get_font(14)
    # 9pt caused adjacent thin strokes to visually fuse together on the
    # 1-bit e-ink render — never go below 10pt (mirrors image_leaders.py).
    row_font_size = 12 if len(entries) <= 6 else 11
    font_row = _get_font(row_font_size)

    # Top border + header separator (matches draw_box's header row layout)
    draw.line([(sx, sy), (sx + _CELL_W - 1, sy)], fill=0)
    draw.line([(sx, sy + 20), (sx + _CELL_W - 1, sy + 20)], fill=0)
    hdr_w = int(font_hdr.getlength(_HEADER))
    hdr_x = sx + (_CELL_W - hdr_w) // 2
    draw.text((hdr_x, sy + 3), _HEADER, font=font_hdr, fill=0)
    draw.text((hdr_x + 1, sy + 3), _HEADER, font=font_hdr, fill=0)

    # Bottom border
    draw.line([(sx, sy + _CELL_H - 1), (sx + _CELL_W - 1, sy + _CELL_H - 1)], fill=0, width=1)

    if not entries:
        draw.text((sx + _PAD, sy + 60), 'No recent moves', font=font_row, fill=0)
        return Himage

    # Row count is capped by available vertical space; 13px is the smallest
    # row height that stays legible at row_font_size 11 (mirrors image_leaders).
    _max_by_height = (_CELL_H - 20) // 13
    n_rows = min(len(entries), max_rows if max_rows is not None else _max_by_height, _max_by_height)
    shown = entries[:n_rows]
    row_h = (_CELL_H - 20) // max(n_rows, 1)
    row_pad = 2 if row_h >= 13 else 1

    logo_size = min(18, row_h)
    abbr_col_w = max((int(font_row.getlength(e.get('team_abbr', '') + ' ')) for e in shown), default=0)
    logo_col_x = sx + _PAD
    name_x = logo_col_x + (logo_size + 2 if use_logos else abbr_col_w)

    for i, entry in enumerate(shown):
        ry = sy + 20 + i * row_h

        abbr = entry.get('team_abbr', '')
        team_id = entry.get('team_id', '')
        name = entry.get('player_name', '')
        type_desc = entry.get('type_desc', '')
        tag = _TYPE_ABBR.get(type_desc, type_desc)

        if use_logos and abbr:
            try:
                logo = _logo_small(abbr, team_id, size=logo_size)
                if logo:
                    logo_y = ry + (row_h - logo.height) // 2
                    Himage.paste(logo, (logo_col_x, logo_y))
            except Exception:
                pass
        else:
            draw.text((sx + _PAD, ry + row_pad), abbr, font=font_row, fill=0)

        # tag right-aligned; measured first so the name gets whatever's left.
        tag_w = int(font_row.getlength(tag))
        tag_x = sx + _CELL_W - tag_w - _PAD

        max_name_w = tag_x - 2 - name_x
        while name and int(font_row.getlength(name)) > max_name_w:
            name = name[:-1]

        draw.text((name_x, ry + row_pad), name, font=font_row, fill=0)
        draw.text((tag_x, ry + row_pad), tag, font=font_row, fill=0)

    return Himage
