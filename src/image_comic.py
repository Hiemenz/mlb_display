"""Full-panel (800x480, 1-bit) "on this day" comic strip screen.

The strip is the screen: no title bar, no frame, and a slim left gutter
that carries everything else (rotated caption, year ticks, "n of N") so the art
gets the full height. Its white scan border is trimmed first, then it is scaled
as large as the panel allows.

    ┌─┬────────────────────────────────────────────┐
    │3│ ┌────────────────────────────────────────┐ │
    │o│ │                                        │ │
    │f│ │         the strip, dithered            │ │
    │5│ │                                        │ │
    │0│ │                                        │ │
    │▬│ └────────────────────────────────────────┘ │
    │-│                                            │
    │O│   (wide strips are centred vertically)     │
    └─┴────────────────────────────────────────────┘

Dark mode inverts the page but keeps the strip itself black ink on white paper.
"""
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from fetch_comic import current_strip
from image_assets import _get_font
from image_idle import _invert_if_dark

_W, _H = 800, 480
_GUT = 28                    # left gutter: rotated caption + year timeline
_MARGIN = 2                  # gap above/beside the frame
_TRIM_BELOW = 240            # pixels lighter than this are scan-border white
_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


# --- strip preparation -------------------------------------------------------

def trim_border(gray, pad=2):
    """Crop the white scan border off a grayscale strip (keeps `pad` px; a blank image is returned as is)."""
    box = gray.point(lambda v: 255 if v < _TRIM_BELOW else 0).getbbox()
    if box is None:
        return gray
    left, top, right, bottom = box
    return gray.crop((max(0, left - pad), max(0, top - pad),
                      min(gray.size[0], right + pad), min(gray.size[1], bottom + pad)))


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
    strip is as large as the panel allows without distortion. The available box
    is everything right of the slim left gutter (which holds the caption and
    year timeline), inside a hairline frame. Wide strips fill the width, tall
    ones fill the height, and whichever dimension is left over is centred.
    """
    avail_w = _W - _GUT - _MARGIN - 2
    avail_h = _H - 2 * _MARGIN - 2
    scale = min(avail_w / size[0], avail_h / size[1])
    w, h = max(1, round(size[0] * scale)), max(1, round(size[1] * scale))
    left, right = _GUT, _W - _MARGIN
    return left + (right - left - w) // 2, _MARGIN + (_H - 2 * _MARGIN - h) // 2, w, h


def _date_text(d):
    return f'{_MONTHS[d.month - 1]} {d.day}, {d.year}'


def _vtext(img, text, font, x, y_bottom):
    """Draw `text` rotated to read bottom-to-top, its bottom end at y_bottom. Returns its length."""
    w, h = int(font.getlength(text)) + 2, 14
    tile = Image.new('1', (w, h), 1)
    ImageDraw.Draw(tile).text((1, 0), text, font=font, fill=0)
    tile = tile.rotate(90, expand=True)
    img.paste(tile, (x, y_bottom - tile.size[1]))
    return tile.size[1]


def _timeline(draw, years, current, cx, y0, y1):
    """Year timeline down the gutter, oldest at the top, drawn bold enough to read on e-ink.

    A 2px spine at x=cx (width 2); a 1px tick to its right for every available year,
    a longer 2px tick at each decade with a small two-digit label to its left; and a
    chunky marker (bar + arrowhead) across the spine at the current year.
    """
    if y1 - y0 < 24:
        return
    lo, hi = min(years), max(years)
    y0, y1 = y0 + 6, y1 - 6          # room for the marker at either end

    def ypos(yr):
        return (y0 + y1) // 2 if hi == lo else y0 + round((yr - lo) * (y1 - y0) / (hi - lo))

    draw.rectangle([cx, ypos(lo) - 3, cx + 1, ypos(hi) + 3], fill=0)
    font = _get_font(10)
    last_label = -99
    for yr in years:
        y = ypos(yr)
        if yr % 10 == 0:
            draw.rectangle([cx + 2, y, cx + 9, y + 1], fill=0)
            if y - last_label >= 13:
                draw.text((cx - 2, y + 1), f'{yr % 100:02d}', font=font, fill=0, anchor='rm')
                last_label = y
        else:
            draw.line([cx + 2, y, cx + 5, y], fill=0, width=1)
    cy = ypos(current)
    draw.rectangle([cx - 3, cy - 1, cx + 11, cy + 2], fill=0)
    draw.polygon([(cx + 12, cy - 4), (cx + 12, cy + 5), (cx + 17, cy)], fill=0)


def draw_comic_screen(strip, config):
    """Render one Strip (see fetch_comic.Strip) as a full panel."""
    img = Image.new('1', (_W, _H), 1)
    draw = ImageDraw.Draw(img)

    # Strip: border trimmed, then as big as the area right of the gutter allows.
    gray = trim_border(strip.image.convert('L'))
    ax, ay, aw, ah = strip_layout(gray.size)
    art = prepare_strip(gray, aw, ah)
    img.paste(art, (ax, ay))

    # Left gutter, bottom to top: caption, year ticks, "n of N" at the top.
    small = _get_font(12)
    gx = 2
    low = _H - 6
    low -= _vtext(img, f'Originally published {_date_text(strip.date)}', small, gx, low) + 8
    high = 6
    if strip.total > 1:
        count = f'{strip.position + 1} of {strip.total}'
        high += _vtext(img, count, small, gx, high + int(small.getlength(count)) + 2) + 8
    _timeline(draw, strip.years, strip.date.year, 13, high, low)

    dark = config.get('dark_mode', False)
    out = _invert_if_dark(img, dark)
    if dark:   # keep the strip black ink on white paper, not a negative
        out.paste(art, (ax, ay))
    return out


# --- idle-screen hook ----------------------------------------------------------

def comic_idle_image(config, now, source=None, replay_running=None, load=None, all_blocks=False):
    """The comic screen for this moment, or None when it isn't its turn.

    Off unless `idle_comic_rotation` is on. Takes the 15-minute blocks listed in
    `comic_idle_blocks` (default [2, 3], the odd ones, leaving the even blocks to
    other idle views), never interrupts a running off-season replay, and yields
    quietly when the source has no strip for today's date. `all_blocks=True`
    ignores the block list (the off-season hook uses it when there are no moves
    to show, so the comic gets every block).
    """
    from util import load_json_file
    if not config.get('idle_comic_rotation', False):
        return None
    if not all_blocks and now.minute // 15 not in config.get('comic_idle_blocks', [2, 3]):
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
    return draw_comic_screen(strip, config)
