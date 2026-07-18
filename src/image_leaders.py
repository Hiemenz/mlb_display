"""Draw a season-leaders panel cell (150×150) for an empty grid slot.

Cycles randomly through HR / AVG / ERA / Saves / Hits / RBI / SB: each
category is shown for `rotation_minutes` minutes (default 5), then a new
category is picked at random (seeded by the time block, so it stays stable
for the duration of that window instead of changing on every render).
"""
import random as _random
from datetime import datetime

from image_assets import _get_font, ImageDraw, _logo_small, Image

_CATEGORIES = [
    'homeRuns', 'battingAverage', 'earnedRunAverage', 'saves', 'hits',
    'runsBattedIn', 'stolenBases',
]
_LABELS = {
    'homeRuns':         'Home Runs',
    'battingAverage':   'Batting Avg',
    'earnedRunAverage': 'ERA',
    'saves':            'Saves',
    'hits':             'Hits',
    'runsBattedIn':     'RBIs',
    'stolenBases':      'Stolen Bases',
}
_FORMAT = {
    'homeRuns':         lambda v: v,
    # Strip only the leading zero, not any dots — "0.345" → ".345", "0.000" → ".000"
    'battingAverage':   lambda v: v.lstrip('0') if v and '.' in v else v,
    'earnedRunAverage': lambda v: v,
    'saves':            lambda v: v,
    'hits':             lambda v: v,
    'runsBattedIn':     lambda v: v,
    'stolenBases':      lambda v: v,
}

# Matches the visible footprint of a normal single-game grid box
# (horizonta_len x vertical_len+20 in image_box.draw_box), not the full
# 150x150 grid slot, so the two line up exactly.
_CELL_W = 135
_CELL_H = 130
_PAD = 2


def _current_category(rotation_minutes=5):
    """Current category, randomly chosen for the current time block."""
    rotation_minutes = max(rotation_minutes, 1)
    minute_block = datetime.now().hour * 60 + datetime.now().minute
    block_idx = minute_block // rotation_minutes
    return _random.Random(block_idx).choice(_CATEGORIES)


def rotating_categories(n, rotation_minutes=5):
    """Return ``n`` categories in a random (but time-block-stable) order.

    Used when there are fewer free grid slots than categories: instead of
    always showing the same subset, the set of categories on display is
    reshuffled at random each rotation window so every category eventually
    gets shown.
    """
    n = max(0, min(n, len(_CATEGORIES)))
    rotation_minutes = max(rotation_minutes, 1)
    minute_block = datetime.now().hour * 60 + datetime.now().minute
    block_idx = minute_block // rotation_minutes
    shuffled = _CATEGORIES[:]
    _random.Random(block_idx).shuffle(shuffled)
    return shuffled[:n]


def draw_leaders_cell(Himage, sx, sy, leaders_data, team_data, category=None, rotation_minutes=5, use_logos=False):
    """Draw a season-leaders panel for one category into the cell at pixel
    position (sx, sy), the same 150x150 footprint as a normal single-game
    grid cell.

    leaders_data: the 'leaders' dict from leaders.json
    team_data: the teams dict (for team_abbreviation lookup)
    category: which _CATEGORIES entry to show; defaults to the
        time-rotated category (single-slot fallback) when not given.
    """
    draw = ImageDraw.Draw(Himage)
    cat = category if category is not None else _current_category(rotation_minutes)
    entries = (leaders_data or {}).get(cat, [])
    label = _LABELS.get(cat, cat)

    abbr_map = (team_data or {}).get('team_abbreviation', {})

    # Same header text style as the "Final" label in draw_box: font14, bold
    # via double-offset draw, black on white (not inverted).
    font_hdr = _get_font(14)
    # 9pt caused adjacent thin strokes (e.g. "r"+"n") to visually fuse
    # together on the 1-bit e-ink render — never go below 10pt.
    row_font_size = 12 if len(entries) <= 6 else 11
    font_row = _get_font(row_font_size)
    font_val = font_row

    # Top border + header separator (matches draw_box's header row layout)
    draw.line([(sx, sy), (sx + _CELL_W - 1, sy)], fill=0)
    draw.line([(sx, sy + 20), (sx + _CELL_W - 1, sy + 20)], fill=0)
    hdr_w = int(font_hdr.getlength(label))
    hdr_x = sx + (_CELL_W - hdr_w) // 2
    draw.text((hdr_x, sy + 3), label, font=font_hdr, fill=0)
    draw.text((hdr_x + 1, sy + 3), label, font=font_hdr, fill=0)

    # Bottom border
    draw.line([(sx, sy + _CELL_H - 1), (sx + _CELL_W - 1, sy + _CELL_H - 1)], fill=0, width=1)

    if not entries:
        draw.text((sx + _PAD, sy + 60), 'No data', font=font_row, fill=0)
        return Himage

    row_h = (_CELL_H - 20) // max(len(entries), 1)
    row_pad = 2 if row_h >= 13 else 1

    # Fixed columns, computed once so every row's logo and name line up
    # regardless of that row's rank-string length or the pasted logo's own
    # (aspect-preserved, so non-square) width.
    rank_col_w = max(
        (int(font_row.getlength(str(e.get('rank', i + 1)) + '.')) for i, e in enumerate(entries)),
        default=0,
    )
    logo_col_x = sx + _PAD + rank_col_w + 2
    logo_size = min(18, row_h)
    name_x = logo_col_x + (logo_size + 2 if use_logos else 0)

    for i, entry in enumerate(entries):
        ry = sy + 20 + i * row_h

        rank = str(entry.get('rank', i + 1))
        name = entry.get('name', '')
        team_id = entry.get('team_id', '')
        abbr = abbr_map.get(team_id, '')
        raw_val = entry.get('value', '')
        fmt_fn = _FORMAT.get(cat, lambda v: v)
        val = fmt_fn(raw_val)

        # rank number
        draw.text((sx + _PAD, ry + row_pad), rank + '.', font=font_row, fill=0)

        # small logo, centered in its fixed column/row band so it lines up
        # with every other row regardless of the logo's own aspect ratio
        if use_logos and abbr:
            try:
                logo = _logo_small(abbr, team_id, size=logo_size)
                if logo:
                    logo_x = logo_col_x + (logo_size - logo.width) // 2
                    logo_y = ry + (row_h - logo.height) // 2 + 2
                    Himage.paste(logo, (logo_x, logo_y))
            except Exception:
                pass

        # value right-aligned; measured first so the name gets to use all
        # remaining space instead of a fixed reservation.
        val_w = int(font_val.getlength(val))
        val_x = sx + _CELL_W - val_w - _PAD

        # truncate name if needed
        max_name_w = val_x - 2 - name_x
        while name and int(font_row.getlength(name)) > max_name_w:
            name = name[:-1]

        draw.text((name_x, ry + row_pad), name, font=font_row, fill=0)
        draw.text((val_x, ry + row_pad), val, font=font_val, fill=0)

    return Himage
