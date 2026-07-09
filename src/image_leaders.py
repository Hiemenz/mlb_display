"""Draw a season-leaders panel cell (150×150) for an empty grid slot.

Rotates through HR / AVG / ERA based on the current time: each category
is shown for `rotation_minutes` minutes (default 5), cycling automatically.
"""
from datetime import datetime

from image_assets import _get_font, ImageDraw, _logo_small, Image

_CATEGORIES = ['homeRuns', 'battingAverage', 'earnedRunAverage']
_LABELS = {
    'homeRuns':         'HOME RUNS',
    'battingAverage':   'BATTING AVG',
    'earnedRunAverage': 'ERA',
}
_FORMAT = {
    'homeRuns':         lambda v: v,
    'battingAverage':   lambda v: f'.{v.lstrip("0.")}' if v and '.' in v else v,
    'earnedRunAverage': lambda v: v,
}

_CELL_W = 150
_CELL_H = 150
_PAD = 4


def _last_name(full_name):
    return full_name.split()[-1] if full_name else ''


def _current_category(rotation_minutes=5):
    minute_block = datetime.now().hour * 60 + datetime.now().minute
    idx = (minute_block // rotation_minutes) % len(_CATEGORIES)
    return _CATEGORIES[idx]


def draw_leaders_cell(Himage, sx, sy, leaders_data, team_data, rotation_minutes=5, use_logos=False):
    """Draw the season leaders panel into the cell at pixel position (sx, sy).

    leaders_data: the 'leaders' dict from leaders.json
    team_data: the teams dict (for team_abbreviation lookup)
    """
    draw = ImageDraw.Draw(Himage)
    cat = _current_category(rotation_minutes)
    entries = (leaders_data or {}).get(cat, [])
    label = _LABELS.get(cat, cat)

    abbr_map = (team_data or {}).get('team_abbreviation', {})

    font_hdr = _get_font(11)
    font_row = _get_font(11)
    font_val = _get_font(11)

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
        draw.text((sx + _PAD, ry + 2), rank + '.', font=font_row, fill=0)

        # small logo or abbreviation
        logo_drawn = False
        if use_logos and abbr:
            try:
                logo = _logo_small(abbr, size=18)
                if logo:
                    Himage.paste(logo, (sx + 20, ry + 2))
                    logo_drawn = True
            except Exception:
                pass

        name_x = sx + 40 if logo_drawn else sx + 20
        # truncate name if needed
        max_name_w = _CELL_W - name_x + sx - 35
        while name and int(font_row.getlength(name)) > max_name_w:
            name = name[:-1]

        draw.text((name_x, ry + 2), name, font=font_row, fill=0)

        # value right-aligned
        val_w = int(font_val.getlength(val))
        draw.text((sx + _CELL_W - val_w - _PAD, ry + 2), val, font=font_val, fill=0)

    return Himage
