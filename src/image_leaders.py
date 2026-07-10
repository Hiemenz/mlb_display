"""Draw a season-leaders panel cell (150×150) for an empty grid slot.

Rotates through HR / AVG / ERA based on the current time: each category
is shown for `rotation_minutes` minutes (default 5), cycling automatically.
"""
from datetime import datetime

from image_assets import _get_font, ImageDraw, _logo_small, Image

_CATEGORIES = ['homeRuns', 'battingAverage', 'earnedRunAverage', 'saves', 'hits']
_LABELS = {
    'homeRuns':         'HOME RUNS',
    'battingAverage':   'BATTING AVG',
    'earnedRunAverage': 'ERA',
    'saves':            'SAVES',
    'hits':             'HITS',
}
_FORMAT = {
    'homeRuns':         lambda v: v,
    # Strip only the leading zero, not any dots — "0.345" → ".345", "0.000" → ".000"
    'battingAverage':   lambda v: v.lstrip('0') if v and '.' in v else v,
    'earnedRunAverage': lambda v: v,
    'saves':            lambda v: v,
    'hits':             lambda v: v,
}

_CELL_W = 150
_CELL_H = 150
_PAD = 4


def _last_name(full_name):
    """Last name."""
    return full_name.split()[-1] if full_name else ''


def _current_category(rotation_minutes=5):
    """Current category."""
    rotation_minutes = max(rotation_minutes, 1)
    minute_block = datetime.now().hour * 60 + datetime.now().minute
    idx = (minute_block // rotation_minutes) % len(_CATEGORIES)
    return _CATEGORIES[idx]


def rotating_categories(n, rotation_minutes=5):
    """Return ``n`` categories (wrapping) starting from a time-rotated offset.

    Used when there are fewer free grid slots than categories: instead of
    always showing the same subset, the window of categories on display
    slides over time so every category eventually gets shown.
    """
    n = max(0, min(n, len(_CATEGORIES)))
    rotation_minutes = max(rotation_minutes, 1)
    minute_block = datetime.now().hour * 60 + datetime.now().minute
    offset = (minute_block // rotation_minutes) % len(_CATEGORIES)
    return [_CATEGORIES[(offset + i) % len(_CATEGORIES)] for i in range(n)]


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

    font_hdr = _get_font(11)
    # More entries (up to 10) need a smaller row font to all fit without
    # clipping against the cell's bottom border.
    row_font_size = 11 if len(entries) <= 6 else (10 if len(entries) <= 8 else 9)
    font_row = _get_font(row_font_size)
    font_val = font_row

    # Header bar
    draw.rectangle([sx, sy, sx + _CELL_W - 1, sy + 18], fill=0)
    hdr_w = int(font_hdr.getlength(label))
    draw.text((sx + (_CELL_W - hdr_w) // 2, sy + 3), label, font=font_hdr, fill=255)

    # Bottom border
    draw.line([(sx, sy + _CELL_H - 1), (sx + _CELL_W - 1, sy + _CELL_H - 1)], fill=0, width=1)

    if not entries:
        draw.text((sx + _PAD, sy + 60), 'No data', font=font_row, fill=0)
        return Himage

    row_h = (_CELL_H - 20) // max(len(entries), 1)
    row_pad = 2 if row_h >= 13 else 1
    for i, entry in enumerate(entries):
        ry = sy + 20 + i * row_h

        rank = str(entry.get('rank', i + 1))
        name = _last_name(entry.get('name', ''))
        team_id = entry.get('team_id', '')
        abbr = abbr_map.get(team_id, '')
        raw_val = entry.get('value', '')
        fmt_fn = _FORMAT.get(cat, lambda v: v)
        val = fmt_fn(raw_val)

        # rank number
        draw.text((sx + _PAD, ry + row_pad), rank + '.', font=font_row, fill=0)

        # small logo or abbreviation
        logo_drawn = False
        if use_logos and abbr:
            try:
                logo_size = min(18, row_h - 2)
                logo = _logo_small(abbr, size=logo_size)
                if logo:
                    Himage.paste(logo, (sx + 20, ry + row_pad))
                    logo_drawn = True
            except Exception:
                pass

        name_x = sx + 40 if logo_drawn else sx + 20
        # truncate name if needed
        max_name_w = _CELL_W - name_x + sx - 35
        while name and int(font_row.getlength(name)) > max_name_w:
            name = name[:-1]

        draw.text((name_x, ry + row_pad), name, font=font_row, fill=0)

        # value right-aligned
        val_w = int(font_val.getlength(val))
        draw.text((sx + _CELL_W - val_w - _PAD, ry + row_pad), val, font=font_val, fill=0)

    return Himage
