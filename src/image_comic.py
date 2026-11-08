"""Full-panel (800x480, 1-bit) "on this day" comic strip screen.

The strip is the star: it is scaled to nearly the whole panel and everything
else is a slim band around it.

    ┌──────────────────────────────────────────────┐
    │ ⚾ PEANUTS                              NOV 7 │  thin title bar (20px)
    │ ┌──────────────────────────────────────────┐ │
    │ │                                          │ │
    │ │           the strip, dithered            │ │  fills everything between
    │ │                                          │ │  the bars; wide/short strips
    │ └──────────────────────────────────────────┘ │  are centred vertically
    │ Originally published Nov 7, 1963 |||▮|||  3 of 50│  one tiny footer line
    └──────────────────────────────────────────────┘

Tall (Sunday-style) strips use the full height; dark mode inverts the page but
keeps the strip itself black ink on white paper.
"""
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from fetch_comic import current_strip
from image_assets import _get_font
from image_idle import _invert_if_dark

_W, _H = 800, 480
_BAR_H = 20                  # thin title bar
_FOOT_H = 26                 # one-line footer
_MARGIN = 4
_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


# --- small drawing helpers (kept local so this module stands alone) ---------

def _bold(draw, xy, text, font, fill=0):
    """Faux-bold: the single-weight font drawn twice, 1px apart."""
    x, y = xy
    draw.text((x, y), text, font=font, fill=fill)
    draw.text((x + 1, y), text, font=font, fill=fill)


def _draw_ball(img, cx, cy, r=8):
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    d.arc([cx - 2 * r + 2, cy - r + 2, cx - 1, cy + r - 2], -70, 70, fill=0, width=1)
    d.arc([cx + 1, cy - r + 2, cx + 2 * r - 2, cy + r - 2], 110, 250, fill=0, width=1)


def _title_bar(img, title, right=''):
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, _W, _BAR_H - 1], fill=0)
    _draw_ball(img, 14, _BAR_H // 2)
    font = _get_font(13)
    _bold(d, (28, 2), title, font, 255)
    if right:
        d.text((_W - 10 - int(font.getlength(right)), 2), right, font=font, fill=255)


# --- strip preparation -------------------------------------------------------

def prepare_strip(gray, max_w, max_h):
    """Grayscale strip → 1-bit image scaled to fit max_w × max_h (aspect kept)."""
    gray = ImageOps.autocontrast(gray.convert('L'), cutoff=1)
    scale = min(max_w / gray.size[0], max_h / gray.size[1])
    size = (max(1, round(gray.size[0] * scale)), max(1, round(gray.size[1] * scale)))
    gray = gray.resize(size, Image.LANCZOS)
    if scale < 1:
        gray = gray.filter(ImageFilter.SHARPEN)
    return gray.convert('1')   # Floyd-Steinberg dither


def strip_layout(size):
    """Where a strip of pixel `size` (w, h) lands: (x, y, w, h) on the panel.

    The one fit rule: scale uniformly by min(avail_w / w, avail_h / h) so the
    strip is as large as the panel allows without distortion, where the
    available box is the 790 x 428 px between the title bar and the footer.
    Wide strips therefore fill the width, tall ones fill the height, and
    whichever dimension is left over is centred (a wide strip floats mid-panel).
    """
    avail_w = _W - 2 * _MARGIN - 2
    avail_h = _H - _FOOT_H - (_BAR_H + _MARGIN) - 2
    scale = min(avail_w / size[0], avail_h / size[1])
    w, h = max(1, round(size[0] * scale)), max(1, round(size[1] * scale))
    top, bot = _BAR_H + _MARGIN, _H - _FOOT_H
    return (_W - w) // 2, top + (bot - top - h) // 2, w, h


def _date_text(d):
    return f'{_MONTHS[d.month - 1]} {d.day}, {d.year}'


def _timeline(draw, years, current, x0, x1, cy):
    """Tiny tick per available year between x0 and x1, current year taller."""
    if x1 - x0 < 20:
        return
    lo, hi = min(years), max(years)

    def xpos(yr):
        return (x0 + x1) // 2 if hi == lo else x0 + round((yr - lo) * (x1 - x0) / (hi - lo))

    for yr in years:
        if yr != current:
            x = xpos(yr)
            draw.line([x, cy - 3, x, cy + 3], fill=0, width=1)
    cx = xpos(current)
    draw.rectangle([cx - 1, cy - 7, cx + 1, cy + 7], fill=0)


def draw_comic_screen(strip, config, now=None, title='PEANUTS'):
    """Render one Strip (see fetch_comic.Strip) as a full panel."""
    img = Image.new('1', (_W, _H), 1)
    draw = ImageDraw.Draw(img)
    right = f'{_MONTHS[now.month - 1].upper()} {now.day}' if now is not None else ''
    _title_bar(img, title, right)

    # Strip: as big as the area between the two bands allows, centred.
    ax, ay, aw, ah = strip_layout(strip.image.size)
    art = prepare_strip(strip.image, aw, ah)
    draw.rectangle([ax - 1, ay - 1, ax + art.size[0], ay + art.size[1]], outline=0, width=1)
    img.paste(art, (ax, ay))

    # One tiny footer line: caption left, year ticks, "n of N" right.
    small = _get_font(12)
    fy = _H - _FOOT_H + (_FOOT_H - 12) // 2 - 1
    caption = f'Originally published {_date_text(strip.date)}'
    draw.text((8, fy), caption, font=small, fill=0)
    count = f'{strip.position + 1} of {strip.total}' if strip.total > 1 else ''
    right_edge = _W - 8
    if count:
        draw.text((right_edge - int(small.getlength(count)), fy), count, font=small, fill=0)
        right_edge -= int(small.getlength(count)) + 14
    _timeline(draw, strip.years, strip.date.year,
              8 + int(small.getlength(caption)) + 16, right_edge, _H - _FOOT_H // 2)

    dark = config.get('dark_mode', False)
    out = _invert_if_dark(img, dark)
    if dark:   # keep the strip black ink on white paper, not a negative
        out.paste(art, (ax, ay))
    return out


# --- idle-screen hook ----------------------------------------------------------

def comic_idle_image(config, now, source=None, replay_running=None, load=None, all_blocks=False):
    """The comic screen for this moment, or None when it isn't its turn.

    Off unless `idle_comic_rotation` is on. Takes the 15-minute blocks listed in
    `comic_idle_blocks` (default [1, 3], the odd ones, leaving the even blocks to
    other idle views), never interrupts a running off-season replay, and yields
    quietly when the source has no strip for today's date. `all_blocks=True`
    ignores the block list (the off-season hook uses it when there are no moves
    to show, so the comic gets every block).
    """
    from util import load_json_file
    if not config.get('idle_comic_rotation', False):
        return None
    if not all_blocks and now.minute // 15 not in config.get('comic_idle_blocks', [1, 3]):
        return None
    if replay_running is None:
        from offseason_replay import _replay_running
        replay_running = _replay_running
    load = load or load_json_file
    if replay_running((load('offseason_replay.json') or {}).get('pid')):
        return None
    strip = current_strip(config, now, source)
    if strip is None:
        return None
    print(f'Idle: showing comic strip from {strip.date} ({strip.position + 1}/{strip.total})')
    return draw_comic_screen(strip, config, now, str(config.get('comic_name', 'peanuts')).upper())
