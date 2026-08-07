"""Draw a season-leaders panel cell (150×150) for an empty grid slot.

Cycles randomly through HR / AVG / ERA / Saves / Hits / RBI / SB: each
category is shown for `rotation_minutes` minutes (default 5), then a new
category is picked at random (seeded by the time block, so it stays stable
for the duration of that window instead of changing on every render).
"""
import random as _random
from datetime import datetime

import panel_cell
from image_assets import ImageDraw

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

    font_row = panel_cell.row_font(len(entries))
    panel_cell.draw_chrome(draw, sx, sy, label)

    if not entries:
        panel_cell.draw_empty(draw, sx, sy, 'No data', font_row)
        return Himage

    fmt = _FORMAT.get(cat, lambda v: v)
    return panel_cell.draw_ranked_rows(
        Himage, draw, sx, sy, entries, font_row,
        lambda e: fmt(e.get('value', '')),
        abbr_map=(team_data or {}).get('team_abbreviation', {}),
        use_logos=use_logos,
    )
