"""Draw a trade deadline countdown cell (135×130) for an empty grid slot.

Shows time remaining until the MLB trade deadline plus the most recent
transactions from data/transactions.json as a transaction ticker beneath.

MLB has no fixed rule for the deadline date/time — the Commissioner's Office
picks a specific date each year (per the CBA, between July 28 and Aug 3) to
avoid a game being played at the moment of the deadline, and announces it via
press release. There's nothing to compute or fetch it from, so the date comes
from config.yaml's `trade_deadline` (local ET, e.g. "2026-08-03 18:00") and
must be updated there once MLB announces the date each season.
`_DEADLINE_UTC` below is only a fallback for when config.yaml has no value.
"""
from datetime import datetime, timedelta, timezone
import pytz
from image_assets import _get_font, ImageDraw

_CELL_W = 135
_CELL_H = 130
_PAD = 2
_HEADER = 'Trade Deadline'

_DEADLINE_TZ = pytz.timezone('America/New_York')

# Fallback if config.yaml has no (or an unparseable) trade_deadline value.
# 2026 MLB trade deadline: August 3, 6 PM ET (UTC-4 in summer = 22:00 UTC)
_DEADLINE_UTC = datetime(2026, 8, 3, 22, 0, 0, tzinfo=timezone.utc)

# The countdown is only relevant this close to the deadline; outside this
# window the panel stays off so a free slot doesn't sit on a months-away date.
_SHOW_WINDOW_DAYS = 14


def _deadline_utc(config=None):
    """Resolve the deadline as a UTC datetime from config's `trade_deadline`
    ("YYYY-MM-DD HH:MM" local ET), falling back to _DEADLINE_UTC when config
    is absent or the value can't be parsed."""
    raw = (config or {}).get('trade_deadline')
    if raw:
        try:
            naive = datetime.strptime(raw, '%Y-%m-%d %H:%M')
            return _DEADLINE_TZ.localize(naive).astimezone(timezone.utc)
        except ValueError:
            print(f"Warning: invalid trade_deadline config value {raw!r}, using fallback")
    return _DEADLINE_UTC


def in_countdown_window(now_utc=None, config=None):
    """Return True if now is within _SHOW_WINDOW_DAYS of the deadline (and not past it)."""
    now = now_utc or datetime.now(timezone.utc)
    deadline = _deadline_utc(config)
    return deadline - timedelta(days=_SHOW_WINDOW_DAYS) <= now < deadline

_TYPE_ABBR = {
    'Status Change':              'IL',
    'Recalled':                   'Recall',
    'Optioned':                   'Option',
    'Selected':                   'Select',
    'Designated for Assignment':  'DFA',
    'Released':                   'Release',
    'Signed':                     'Sign',
    'Trade':                      'Trade',
    'Claimed off Waivers':        'Waiver',
    'Outrighted':                 'Outright',
}


def _countdown(now_utc=None, config=None):
    """Return (big_str, small_str, is_past)."""
    now = now_utc or datetime.now(timezone.utc)
    delta = _deadline_utc(config) - now
    if delta.total_seconds() <= 0:
        return 'Passed', 'Trade Deadline', True
    s = int(delta.total_seconds())
    days  = s // 86400
    hours = (s % 86400) // 3600
    mins  = (s % 3600) // 60
    if days >= 1:
        return f'{days}d {hours}h', 'until deadline', False
    if hours >= 1:
        return f'{hours}h {mins}m', 'until deadline', False
    return f'{mins}m', 'until deadline', False


def draw_deadline_cell(Himage, sx, sy, transactions_data, team_data, use_logos=False, config=None):
    """Draw the trade deadline countdown panel at pixel position (sx, sy)."""
    draw = ImageDraw.Draw(Himage)

    font_hdr = _get_font(12)
    font_big = _get_font(20)
    font_sub = _get_font(9)
    font_row = _get_font(10)

    # Borders + header
    draw.line([(sx, sy),              (sx + _CELL_W - 1, sy)],              fill=0)
    draw.line([(sx, sy + 20),         (sx + _CELL_W - 1, sy + 20)],         fill=0)
    draw.line([(sx, sy + _CELL_H - 1),(sx + _CELL_W - 1, sy + _CELL_H - 1)],fill=0, width=1)

    hdr_w = int(font_hdr.getlength(_HEADER))
    hdr_x = sx + (_CELL_W - hdr_w) // 2
    draw.text((hdr_x,     sy + 4), _HEADER, font=font_hdr, fill=0)
    draw.text((hdr_x + 1, sy + 4), _HEADER, font=font_hdr, fill=0)

    # Countdown
    big_str, sub_str, is_past = _countdown(config=config)
    big_y = sy + 24
    bw = int(font_big.getlength(big_str))
    bx = sx + (_CELL_W - bw) // 2
    draw.text((bx,     big_y), big_str, font=font_big, fill=0)
    draw.text((bx + 1, big_y), big_str, font=font_big, fill=0)

    sw = int(font_sub.getlength(sub_str))
    sx2 = sx + (_CELL_W - sw) // 2
    draw.text((sx2, big_y + 22), sub_str, font=font_sub, fill=0)

    # Divider + recent transactions
    sep_y = sy + 56
    draw.line([(sx + _PAD, sep_y), (sx + _CELL_W - _PAD, sep_y)], fill=0)

    entries = list(transactions_data or [])
    if not entries:
        msg = 'No recent moves'
        mw = int(font_row.getlength(msg))
        draw.text((sx + (_CELL_W - mw) // 2, sep_y + 5), msg, font=font_row, fill=0)
        return Himage

    body_top = sep_y + 3
    avail_h = sy + _CELL_H - 1 - body_top
    row_h = 12
    n_rows = max(avail_h // row_h, 1)

    for i, entry in enumerate(entries[:n_rows]):
        ry = body_top + i * row_h
        abbr = entry.get('team_abbr', '')
        name = entry.get('player_name', '')
        type_desc = entry.get('type_desc', '')
        tag = _TYPE_ABBR.get(type_desc, type_desc[:6] if type_desc else '')

        abbr_w = int(font_row.getlength(abbr + ' '))
        tag_w  = int(font_row.getlength(tag))
        tag_x  = sx + _CELL_W - tag_w - _PAD
        name_x = sx + _PAD + abbr_w
        max_name_w = tag_x - 3 - name_x
        while name and int(font_row.getlength(name)) > max_name_w:
            name = name[:-1]

        draw.text((sx + _PAD, ry), abbr, font=font_row, fill=0)
        draw.text((name_x,    ry), name, font=font_row, fill=0)
        draw.text((tag_x,     ry), tag,  font=font_row, fill=0)

    return Himage
