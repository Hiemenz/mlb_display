"""Free-agent signing screens (800x480, 1-bit).

Two layouts share one look — a baseball-seam title bar, rounded cards, portraits
with the whole head and shoulders, ringed team logos, and the contract terms in
a bold inverted band:

* draw_free_agent_grid   — 5 x 2 compact cards, ten signings per screen (default)
* draw_free_agent_screen — one signing full-panel: portrait, FROM -> TO team
  medallions and a big terms band

When no contract terms are known the band reads just "SIGNED".
"""
import os
from datetime import datetime, timedelta

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from image_assets import _get_font, _load_logo_gray, _logo_small, _try_download_logo
from image_idle import _invert_if_dark

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HEADSHOT_DIR = os.path.join(_REPO_ROOT, 'pic', 'headshots')
_HEADSHOT_URL = ('https://img.mlbstatic.com/mlb-photos/image/upload/'
                 'd_people:generic:headshot:67:current.png/w_426,q_auto:best/'
                 'v1/people/{pid}/headshot/67/current')

_W, _H = 800, 480
_HDR_H = 46               # black title bar (0-38) + stitched seam (42) + breathing room
_PHOTO_H = 320
_PHOTO_W = 213            # headshots are 426x640 (2:3); show the whole thing, chin included
_LOGO = 100
_PX, _PY = 34, _HDR_H + 24   # single-card portrait origin

def _load_headshot(player_id, width=_PHOTO_W, height=_PHOTO_H):
    """1-bit headshot at width×height (2:3 portrait, uncropped), cached under pic/headshots/. None on failure."""
    path = os.path.join(_HEADSHOT_DIR, f'{player_id}.png')
    if not os.path.exists(path):
        try:
            resp = requests.get(_HEADSHOT_URL.format(pid=player_id), timeout=10)
            if resp.status_code != 200:
                return None
            os.makedirs(_HEADSHOT_DIR, exist_ok=True)
            with open(path, 'wb') as f:
                f.write(resp.content)
        except Exception as e:
            print(f'Warning: headshot download failed for {player_id}: {e}')
            return None
    try:
        gray = Image.open(path).convert('L')
    except Exception:
        return None
    gray = ImageOps.fit(gray, (width, height), Image.LANCZOS, centering=(0.5, 0.0))
    gray = ImageOps.autocontrast(gray, cutoff=1).filter(ImageFilter.SHARPEN)
    return gray.convert('1')


def _team_logo(abbr, team_id, size=_LOGO):
    """1-bit team logo, downloading it if missing. None when unavailable."""
    if not abbr:
        return None
    if _load_logo_gray(abbr, team_id) is None:
        _try_download_logo(abbr, team_id)
    logo = _logo_small(abbr, team_id, size)
    if logo is None:
        return None
    if logo.size[0] < size and logo.size[1] < size:
        gray = logo.convert('L')
        gray = gray.resize((size, round(size * gray.size[1] / gray.size[0]))
                           if gray.size[0] >= gray.size[1]
                           else (round(size * gray.size[0] / gray.size[1]), size),
                           Image.LANCZOS)
        logo = gray.convert('1')
    return logo


def _fit_font(text, max_w, start, minimum=18):
    """Largest font ≤ start whose rendering of `text` fits max_w."""
    size = start
    while size > minimum:
        font = _get_font(size)
        if font.getlength(text) <= max_w:
            return font
        size -= 2
    return _get_font(minimum)


def _centered(draw, cx, y, text, font, fill=0):
    draw.text((cx - int(font.getlength(text)) // 2, y), text, font=font, fill=fill)


def _verb(signing):
    return 'TRADED' if signing.get('kind') == 'trade' else 'SIGNED'


def _is_resign(signing):
    """A signing with the player's own team: show the team once, as 'RE-SIGNED'."""
    return bool(signing.get('from_team_id')) and signing.get('from_team_id') == signing.get('to_team_id')


def _sc(v, k):
    """Scale a design-size measurement by k (never below 1px)."""
    return max(1, round(v * k))


def _title_for(moves, single=False):
    """Title-bar text for a set of moves: signings, trades, or both."""
    kinds = {m.get('kind', 'signing') for m in moves}
    if kinds == {'trade'}:
        return 'TRADE' if single else 'TRADES'
    if len(kinds) > 1:
        return 'SIGNINGS & TRADES'
    return 'FREE AGENT SIGNING' if single else 'FREE AGENT SIGNINGS'


def _date_label(date_str):
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%b %-d').upper()
    except (ValueError, TypeError):
        return ''


def _seen_time(signing):
    """'3:42 PM' when this move was first spotted on the day it happened, else ''.

    MLB's transactions API gives only a date, so the clock time is when this scoreboard first
    polled the move (`seen_at`). It is only a good stand-in when that is the same calendar day;
    moves already in the first poll's backlog have no `seen_at` and show the date alone.
    """
    seen = signing.get('seen_at')
    if not seen:
        return ''
    try:
        when = datetime.fromtimestamp(seen)
    except (OverflowError, OSError, ValueError, TypeError):
        return ''
    if when.strftime('%Y-%m-%d') != signing.get('date'):
        return ''
    return when.strftime('%-I:%M %p')


def _when_label(signing, short=False):
    """'NOV 8' (or 'NOV 8 3:42P' with `short`, 'NOV 8 · SEEN 3:42 PM' otherwise)."""
    day = _date_label(signing.get('date'))
    clock = _seen_time(signing)
    if not clock:
        return day
    if short:
        return f"{day} {clock.replace(' AM', 'A').replace(' PM', 'P')}".strip()
    return f'{day} · SEEN {clock}'.strip(' ·')


def _abbr(team_data, team_id):
    return ((team_data or {}).get('team_abbreviation') or {}).get(str(team_id), '')



def _bold(draw, xy, text, font, fill=0):
    """Faux-bold: the single-weight font drawn twice, 1px apart."""
    x, y = xy
    draw.text((x, y), text, font=font, fill=fill)
    draw.text((x + 1, y), text, font=font, fill=fill)


def _bold_centered(draw, cx, y, text, font, fill=0):
    _bold(draw, (cx - int(font.getlength(text)) // 2, y), text, font, fill)


def _stitch(draw, y, x0=8, x1=_W - 8, dash=9, gap=6, fill=0):
    """A dashed 'seam' line."""
    x = x0
    while x < x1:
        draw.line([x, y, min(x + dash, x1), y], fill=fill, width=2)
        x += dash + gap


def _draw_ball(img, cx, cy, r=13):
    """A tiny baseball (white disc, curved seams) for the title bar."""
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    d.arc([cx - 2 * r + 3, cy - r + 3, cx - 2, cy + r - 3], -70, 70, fill=0, width=2)
    d.arc([cx + 2, cy - r + 3, cx + 2 * r - 3, cy + r - 3], 110, 250, fill=0, width=2)


def _title_bar(img, title, right='', badge=''):
    """Black bar with a baseball, bold title, optional right-hand text, stitched seam."""
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, _W, 38], fill=0)
    _draw_ball(img, 26, 19)
    hdr = _get_font(22)
    _bold(d, (50, 7), title, hdr, 255)
    if badge:   # white pill, black text — reads as a news-flash tag on the bar
        bf = _get_font(16)
        bx = 50 + int(hdr.getlength(title)) + 16
        d.rounded_rectangle([bx, 6, bx + int(bf.getlength(badge)) + 20, 32], 13, fill=255)
        _bold(d, (bx + 10, 9), badge, bf, 0)
    if right:
        d.text((_W - 16 - int(hdr.getlength(right)), 8), right, font=hdr, fill=255)
    _stitch(d, 42)


def _paste_rounded(img, photo, xy, radius=8):
    """Paste a 1-bit photo through a rounded-corner mask."""
    mask = Image.new('L', photo.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, photo.size[0] - 1, photo.size[1] - 1],
                                           radius, fill=255)
    img.paste(photo, xy, mask)


def _frame_photo(img, draw, photo, x, y, w, h, shadow=6, radius=9, name=''):
    """Portrait with a drop shadow and rounded frame (initials when no photo)."""
    if shadow:
        draw.rounded_rectangle([x + shadow, y + shadow, x + w + shadow, y + h + shadow],
                               radius, fill=0)
    draw.rounded_rectangle([x - 2, y - 2, x + w + 1, y + h + 1], radius, fill=255,
                           outline=0, width=3)
    if photo is not None:
        _paste_rounded(img, photo, (x, y), radius - 2)
    else:
        initials = ''.join(w_[0] for w_ in name.split()[:2]) or '?'
        _bold_centered(draw, x + w // 2, y + h // 2 - h // 8, initials, _get_font(max(24, w // 3)))


def _medallion(img, draw, cx, cy, r, team_data, team_id, size):
    """A team logo inside a ring."""
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255, outline=0, width=3)
    logo = _team_logo(_abbr(team_data, team_id), team_id, size)
    if logo is not None:
        img.paste(logo, (cx - logo.size[0] // 2, cy - logo.size[1] // 2))


def _arrow(draw, x0, x1, y):
    """Dashed shaft with a solid triangular head, pointing right."""
    x = x0
    while x < x1 - 26:
        draw.line([x, y, min(x + 14, x1 - 26), y], fill=0, width=5)
        x += 22
    draw.polygon([(x1, y), (x1 - 24, y - 15), (x1 - 24, y + 15)], fill=0)


def draw_free_agent_screen(signing, team_data, config, page=None, total=None, breaking=False):
    """Render one signing as a full-panel card.

    signing  : dict from fetch_free_agents (player_id, player_name, position,
               date, from_team_id/name, to_team_id/name, terms)
    team_data: {'team_abbreviation': {id: abbr}}
    page/total: shown as "n / N" in the title bar when total > 1
    """
    img = Image.new('1', (_W, _H), 1)
    draw = ImageDraw.Draw(img)
    right = f'{page} / {total}' if total and total > 1 and page else ''
    _title_bar(img, _title_for([signing], single=True), right, 'BREAKING' if breaking else '')

    photo = _load_headshot(signing.get('player_id'))
    _frame_photo(img, draw, photo, _PX, _PY, _PHOTO_W, _PHOTO_H, name=signing.get('player_name', ''))

    col_x = _PX + _PHOTO_W + 54
    col_w = _W - 30 - col_x
    name = signing.get('player_name', '').upper()
    nfont = _fit_font(name, col_w, 52)
    _bold(draw, (col_x, _HDR_H + 8), name, nfont)

    # position pill + date
    py = _HDR_H + 8 + nfont.size + 10
    pill_font = _get_font(17)
    label = signing.get('position') or ''
    px_end = col_x
    if label:
        w = int(pill_font.getlength(label)) + 22
        draw.rounded_rectangle([col_x, py, col_x + w, py + 26], 13, fill=0)
        draw.text((col_x + 11, py + 3), label, font=pill_font, fill=255)
        px_end = col_x + w + 12
    date = _when_label(signing)
    if date:
        draw.text((px_end, py + 3), f'{_verb(signing)} {date}', font=_fit_font(f'{_verb(signing)} {date}', _W - 30 - px_end, 17, 12), fill=0)

    # FROM  ──▶  TO medallions (or one medallion for a re-signing)
    r = 66
    cy = py + 34 + 18 + r
    old_cx, new_cx = col_x + r + 4, col_x + col_w - r - 4
    small = _get_font(14)
    if _is_resign(signing):
        cx = col_x + col_w // 2
        _centered(draw, cx, cy - r - 22, 'RE-SIGNED WITH', small)
        _medallion(img, draw, cx, cy, r, team_data, signing.get('to_team_id'), _LOGO)
        nick = (signing.get('to_team_name') or '').split()[-1]
        _bold_centered(draw, cx, cy + r + 8, nick, _fit_font(nick, 2 * r + 60, 24, 12))
    else:
        for cx, tid, tname, tag in ((old_cx, signing.get('from_team_id'), signing.get('from_team_name'), 'FROM'),
                                    (new_cx, signing.get('to_team_id'), signing.get('to_team_name'), 'TO')):
            _centered(draw, cx, cy - r - 22, tag, small)
            _medallion(img, draw, cx, cy, r, team_data, tid, _LOGO)
            nick = (tname or '').split()[-1] if tname else ''
            _bold_centered(draw, cx, cy + r + 8, nick, _fit_font(nick, 2 * r + 20, 24, 12))
        _arrow(draw, old_cx + r + 14, new_cx - r - 14, cy)

    # terms band — the focal point
    terms = signing.get('terms') or _verb(signing)
    by0, by1 = _PY + _PHOTO_H + 20, _H - 16
    draw.rounded_rectangle([_PX - 2, by0, _W - 30, by1], 12, fill=0)
    font = _fit_font(terms, _W - 2 * _PX - 40, 46, 20)
    _bold_centered(draw, (_PX + _W - 30) // 2, by0 + (by1 - by0 - font.size) // 2 - 3, terms, font, 255)

    dark = config.get('dark_mode', False)
    out = _invert_if_dark(img, dark)
    if dark and photo is not None:   # keep the portrait a positive, not a negative
        _paste_rounded(out, photo, (_PX, _PY), 7)
    return out


# ---------------------------------------------------------------------------
# 10-up grid (5 x 2) — one page of signings per screen
# ---------------------------------------------------------------------------

GRID_COLS, GRID_ROWS = 5, 2
GRID_PER_PAGE = GRID_COLS * GRID_ROWS
_CELL_W = _W // GRID_COLS                  # design size of a roomy card: 160 x 217,
_CELL_H = (_H - _HDR_H) // GRID_ROWS       # scaled by k to fill whatever cell it gets
_G_PHOTO_W, _G_PHOTO_H = 90, 135
_G_PX, _G_PY = 9, 8          # portrait origin inside the design card
_G_LOGO = 34


def _grid_geom(cw, ch):
    """(k, ox, oy): scale and centring offset for a roomy card in a cw x ch cell."""
    k = min(cw / _CELL_W, ch / _CELL_H)
    return k, (cw - _CELL_W * k) / 2, (ch - _CELL_H * k) / 2


def choose_grid(n):
    """(cols, rows) for n <= 10 roomy cards: the layout whose cells scale the card
    up the most, then fewer empty cells, then cells shaped like the card."""
    area = _H - _HDR_H
    best = None
    for cols in range(1, GRID_COLS + 1):
        for rows in range(1, GRID_ROWS + 1):
            if cols * rows < n:
                continue
            cw, ch = _W // cols, area // rows
            k = min(cw / _CELL_W, ch / _CELL_H)
            shape = abs((cw / ch) / (_CELL_W / _CELL_H) - 1)
            key = (round(k, 2), -(cols * rows - n), -shape)
            if best is None or key > best[0]:
                best = (key, cols, rows)
    return best[1], best[2]


def _draw_grid_cell(img, draw, x, y, signing, team_data, cw=_CELL_W, ch=_CELL_H):
    """One roomy signing card, scaled to fill the cw x ch cell whose top-left is (x, y)."""
    k, ox, oy = _grid_geom(cw, ch)
    S = lambda v: max(1, round(v * k))   # noqa: E731 — scale a design-size measurement
    x, y = x + round(ox), y + round(oy)
    W, H = S(_CELL_W), S(_CELL_H)
    draw.rounded_rectangle([x + S(3), y + S(2), x + W - S(4), y + H - S(3)], S(9),
                           outline=0, width=max(2, S(2)))
    pw, ph = S(_G_PHOTO_W), S(_G_PHOTO_H)
    px, py = x + S(_G_PX), y + S(_G_PY)
    photo = _load_headshot(signing.get('player_id'), pw, ph)
    _frame_photo(img, draw, photo, px, py, pw, ph, shadow=0, radius=S(7),
                 name=signing.get('player_name', ''))

    # FROM / old logo, arrow, TO / new logo — stacked beside the portrait
    col0 = px + pw + S(6)
    cx = col0 + (x + W - S(7) - col0) // 2
    old_id, new_id = signing.get('from_team_id'), signing.get('to_team_id')
    lg = S(_G_LOGO)
    tiny = _get_font(max(10, S(10)))
    if _is_resign(signing):          # the team once, labelled — no arrow
        col_w = x + W - S(7) - col0
        big = min(round(lg * 1.25), col_w)
        _centered(draw, cx, py + ph // 2 - big // 2 - S(16), 'RE-SIGNED',
                  _fit_font('RE-SIGNED', col_w, tiny.size, 7))
        logo = _team_logo(_abbr(team_data, new_id), new_id, big)
        if logo is not None:
            img.paste(logo, (cx - logo.size[0] // 2, py + ph // 2 - logo.size[1] // 2 + S(4)))
    else:
        _centered(draw, cx, py - 1, 'FROM', tiny)
        _centered(draw, cx, py + ph - lg - S(13), 'TO', tiny)
        for ty, tid in ((py + S(11), old_id), (py + ph - lg + 1, new_id)):
            logo = _team_logo(_abbr(team_data, tid), tid, lg)
            if logo is not None:
                img.paste(logo, (cx - logo.size[0] // 2, ty + (lg - logo.size[1]) // 2))
        ay = py + ph // 2 - 2
        draw.line([cx, ay - S(16), cx, ay + S(6)], fill=0, width=max(3, S(3)))
        draw.polygon([(cx, ay + S(14)), (cx - S(8), ay + S(3)), (cx + S(8), ay + S(3))], fill=0)

    mid = x + W // 2
    ny = py + ph + S(5)
    name = signing.get('player_name', '')
    nf = _fit_font(name, W - S(16), max(16, S(16)), 11)
    _bold_centered(draw, mid, ny, name, nf)
    terms = signing.get('terms') or _verb(signing)
    bh = S(24)
    bx0, bx1, by0 = x + S(9), x + W - S(10), ny + nf.size + S(5)
    draw.rounded_rectangle([bx0, by0, bx1, by0 + bh], S(8), fill=0)
    tf = _fit_font(terms, bx1 - bx0 - 10, max(17, S(17)), 11)
    _bold_centered(draw, mid, by0 + (bh - tf.size) // 2 - 1, terms, tf, 255)
    old_a, new_a = _abbr(team_data, old_id), _abbr(team_data, new_id)
    sub = f'{old_a} > {new_a}' if old_a and new_a and old_a != new_a else signing.get('position', '')
    when = _when_label(signing, short=True)
    if when:
        sub = f'{sub} · {when}' if sub else when
    _centered(draw, mid, by0 + bh + S(4), sub, _fit_font(sub, W - S(14), max(11, S(11)), 8))


# Dense tier: 5 columns x 3-4 rows of compact cards (up to 20 per page) once there
# are more than 10 moves. Cells stretch to fill the panel height.
DENSE_ROWS = 4
DENSE_PER_PAGE = GRID_COLS * DENSE_ROWS
_D_PX, _D_PY = 7, 8
_D_LOGO = 26


def _dense_geom(cell_h):
    """(photo_w, photo_h) for a dense cell of height cell_h (2:3, capped for width)."""
    ph = cell_h - 21
    return min(ph * 2 // 3, 72), ph


def _draw_dense_cell(img, draw, x, y, signing, team_data, cell_h):
    """Compact card: portrait left; name, FROM > TO logos and terms right."""
    draw.rounded_rectangle([x + 3, y + 2, x + _CELL_W - 4, y + cell_h - 3], 8, outline=0, width=2)
    pw, ph = _dense_geom(cell_h)
    px, py = x + _D_PX, y + _D_PY
    photo = _load_headshot(signing.get('player_id'), pw, ph)
    _frame_photo(img, draw, photo, px, py, pw, ph, shadow=0, radius=6,
                 name=signing.get('player_name', ''))
    rx0, rx1 = px + pw + 8, x + _CELL_W - 8
    rw, mid = rx1 - rx0, (rx0 + rx1) // 2
    words = signing.get('player_name', '').split()
    first, last = (' '.join(words[:-1]), words[-1]) if len(words) > 1 else ('', ' '.join(words))
    if first:
        draw.text((rx0, py - 3), first, font=_fit_font(first, rw, 11, 9), fill=0)
    _bold(draw, (rx0, py + 8), last, _fit_font(last, rw, 15, 10))
    # old logo > new logo, centred in the room between the name and the terms pill
    old_id, new_id = signing.get('from_team_id'), signing.get('to_team_id')
    pill_y = py + ph - 22
    ly = py + 26 + max(0, (pill_y - py - 26 - _D_LOGO) // 2)
    resign = _is_resign(signing)
    spots = ((mid, new_id),) if resign else ((rx0 + _D_LOGO // 2, old_id), (rx1 - _D_LOGO // 2, new_id))
    lsize = min(_D_LOGO + 8, rw) if resign else _D_LOGO
    for lx, tid in spots:
        logo = _team_logo(_abbr(team_data, tid), tid, lsize)
        if logo is not None:
            img.paste(logo, (lx - logo.size[0] // 2, ly + (_D_LOGO - logo.size[1]) // 2))
    if not resign:
        ay = ly + _D_LOGO // 2
        draw.line([mid - 8, ay, mid + 3, ay], fill=0, width=3)
        draw.polygon([(mid + 9, ay), (mid + 1, ay - 6), (mid + 1, ay + 6)], fill=0)
    terms = signing.get('terms') or _verb(signing)
    draw.rounded_rectangle([rx0, pill_y, rx1, pill_y + 21], 7, fill=0)
    tf = _fit_font(terms, rw - 6, 14, 9)
    _bold_centered(draw, mid, pill_y + (21 - tf.size) // 2 - 1, terms, tf, 255)


def paginate(moves):
    """Split moves into balanced pages. More than 10 switches every page to the
    dense 5 x 4 tier; up to 10 use the roomy 5 x 2 cards."""
    moves = list(moves)
    if not moves:
        return []
    per = GRID_PER_PAGE if len(moves) <= GRID_PER_PAGE else DENSE_PER_PAGE
    pages = -(-len(moves) // per)
    size = -(-len(moves) // pages)
    return [moves[i:i + size] for i in range(0, len(moves), size)]


def draw_free_agent_grid(signings, team_data, config, page=1, pages=1, dense=None, breaking=False):
    """Render a page of moves on one 800x480 screen, sized to fill it.

    * 1 move  : the full-panel card.
    * 2-10    : roomy cards in whichever grid scales them up the most
                (2 -> 2x1, 4 -> 4x1, 6 -> 3x2, 10 -> 5x2 ...); a short last row
                is centred.
    * 11-20+  : compact cards, 5 per row, rows stretched to fill the height.
    dense=None picks the tier from the count.
    """
    moves = list(signings)
    if len(moves) == 1 and dense is None:
        return draw_free_agent_screen(moves[0], team_data, config, breaking=breaking)
    if dense is None:
        dense = len(moves) > GRID_PER_PAGE
    shown = moves[:DENSE_PER_PAGE if dense else GRID_PER_PAGE]
    area = _H - _HDR_H
    if dense:
        cols, rows = GRID_COLS, max(1, -(-len(shown) // GRID_COLS))
    else:
        cols, rows = choose_grid(len(shown))
    cw, ch = _W // cols, area // rows

    img = Image.new('1', (_W, _H), 1)
    draw = ImageDraw.Draw(img)
    _title_bar(img, _title_for(moves), f'{page} / {pages}' if pages > 1 else '',
               'BREAKING' if breaking else '')

    placed = []   # (x, y, signing) of each portrait, for the dark-mode re-paste
    for i, sg in enumerate(shown):
        r, c = divmod(i, cols)
        in_row = min(cols, len(shown) - r * cols)
        x = (_W - in_row * cw) // 2 + c * cw
        y = _HDR_H + r * ch
        if dense:
            _draw_dense_cell(img, draw, x, y, sg, team_data, ch)
            pw, ph = _dense_geom(ch)
            placed.append((x + _D_PX, y + _D_PY, pw, ph, sg))
        else:
            _draw_grid_cell(img, draw, x, y, sg, team_data, cw, ch)
            k, ox, oy = _grid_geom(cw, ch)
            placed.append((x + round(ox) + _sc(_G_PX, k), y + round(oy) + _sc(_G_PY, k),
                           _sc(_G_PHOTO_W, k), _sc(_G_PHOTO_H, k), sg))

    dark = config.get('dark_mode', False)
    out = _invert_if_dark(img, dark)
    if dark:   # keep every portrait a positive
        for px, py, pw, ph, sg in placed:
            photo = _load_headshot(sg.get('player_id'), pw, ph)
            if photo is not None:
                _paste_rounded(out, photo, (px, py), 5)
    return out


# ---------------------------------------------------------------------------
# Idle-screen rotation
# ---------------------------------------------------------------------------

_REFRESH_MINUTES = 15            # poll for new moves every 15 min (config: free_agent_poll_minutes)
_BREAKING_MINUTES = 30           # a new move counts as breaking for this long
_SHOW_HOURS = 24                 # only moves from this many hours back are shown (config: free_agent_show_hours)


def recent_moves(moves, now, hours=_SHOW_HOURS):
    """Moves dated within the last `hours` hours (0/None disables the filter).

    MLB dates a transaction by day only, so this keeps every move dated on or
    after the calendar day `hours` ago: a "last 24 hours" window is today plus
    whatever yesterday had left of it.
    """
    if not hours:
        return list(moves)
    cutoff = (now - timedelta(hours=hours)).strftime('%Y-%m-%d')
    return [m for m in moves if (m.get('date') or '') >= cutoff]


def pick_signing(signings, now):
    """The signing for this hour, stepping through the list in order.

    Keyed to the wall clock so every cron tick in the same slot draws the same
    card (the idle screen skips the panel push when the image is unchanged).
    """
    if not signings:
        return None, 0
    slot = now.timetuple().tm_yday * 24 + now.hour
    idx = slot % len(signings)
    return signings[idx], idx


def has_moves(config, load=None, now=None):
    """True when there are free-agent/trade moves from the last day to show (after the last poll)."""
    from util import load_json_file
    if not config.get('idle_free_agent_rotation', True):
        return False
    moves = ((load or load_json_file)('free_agents.json') or {}).get('signings') or []
    if not config.get('free_agent_include_trades', True):
        moves = [m for m in moves if m.get('kind', 'signing') != 'trade']
    moves = recent_moves(moves, now or datetime.now(), config.get('free_agent_show_hours', _SHOW_HOURS))
    return bool(moves)


def _is_breaking(move, now_ts, minutes):
    """True for a move first seen within the last `minutes` minutes."""
    seen = move.get('seen_at')
    return bool(seen) and 0 <= now_ts - seen <= minutes * 60


def free_agent_idle_image(config, now, load=None, fetch=None, replay_running=None, now_ts=None):
    """Card/grid for the current slot, or None when it isn't the free agents' turn.

    Polls for new moves every 15 minutes (`free_agent_poll_minutes`). Normally takes the 15-minute blocks in
    `free_agent_idle_blocks` (default [0, 1]: minutes 0-29) so the comic keeps the rest. Only
    moves from the last 24 hours (`free_agent_show_hours`) are shown. While a newly
    detected move is "breaking" (config `free_agent_breaking_minutes`, default
    30) the screen shows just those moves under a BREAKING badge and takes
    every block. Never interrupts a running off-season replay, and quietly
    yields when there is nothing to show (moves age out after the lookback).
    """
    import time as _time
    from util import load_json_file
    load = load or load_json_file
    if not config.get('idle_free_agent_rotation', True):
        return None
    now_ts = _time.time() if now_ts is None else now_ts

    data = load('free_agents.json') or {}
    if now_ts - data.get('fetched_at', 0) > config.get('free_agent_poll_minutes', _REFRESH_MINUTES) * 60:
        try:
            if fetch is None:
                from fetch_free_agents import fetch_free_agents as fetch
            data = fetch(lookback_days=config.get('free_agent_lookback_days', 21),
                         include_trades=config.get('free_agent_include_trades', True),
                         previous=data) or data
        except Exception as e:
            print(f'Warning: free-agent refresh failed: {e}')
    signings = data.get('signings') or []
    if not config.get('free_agent_include_trades', True):
        signings = [m for m in signings if m.get('kind', 'signing') != 'trade']
    signings = recent_moves(signings, now, config.get('free_agent_show_hours', _SHOW_HOURS))
    if not signings:
        return None
    window = config.get('free_agent_breaking_minutes', _BREAKING_MINUTES)
    breaking = [m for m in signings if _is_breaking(m, now_ts, window)]

    if not breaking and now.minute // 15 not in config.get('free_agent_idle_blocks', [0, 1]):
        return None
    if replay_running is None:
        from offseason_replay import _replay_running
        replay_running = _replay_running
    if replay_running((load('offseason_replay.json') or {}).get('pid')):
        return None

    team_data = load('teams.json') or {}
    shown = breaking or signings
    slot = now.timetuple().tm_yday * 24 + now.hour
    if config.get('free_agent_layout', 'grid') == 'grid' or breaking:
        chunks = paginate(shown)
        page = slot % len(chunks)
        print(f'Idle: showing {"BREAKING " if breaking else ""}move grid page '
              f'{page + 1}/{len(chunks)} ({len(shown)} moves)')
        return draw_free_agent_grid(chunks[page], team_data, config, page + 1, len(chunks),
                                    dense=len(shown) > GRID_PER_PAGE, breaking=bool(breaking))
    signing, idx = pick_signing(shown, now)
    print(f'Idle: showing free-agent card {idx + 1}/{len(shown)} ({signing.get("player_name")})')
    return draw_free_agent_screen(signing, team_data, config, idx + 1, len(shown))
