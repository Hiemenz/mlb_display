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

The page stays white paper with black ink in dark mode too (no black edges).
"""
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from fetch_comic import current_strip
import os

from image_assets import _get_font, picdir

_W, _H = 800, 480
_GUT = 18                    # left gutter: rotated caption + year timeline
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


def strip_layout(size, reserve_right=0):
    """Where a strip of pixel `size` (w, h) lands: (x, y, w, h) on the panel.

    The one fit rule: scale uniformly by min(avail_w / w, avail_h / h) so the
    strip is as large as the panel allows without distortion. The available box
    is everything right of the slim left gutter (which holds the caption and
    year timeline), inside a hairline frame. Wide strips fill the width, tall
    ones fill the height, and whichever dimension is left over is centred.
    """
    avail_w = _W - _GUT - _MARGIN - 2 - reserve_right
    avail_h = _H - 2 * _MARGIN - 2
    scale = min(avail_w / size[0], avail_h / size[1])
    w, h = max(1, round(size[0] * scale)), max(1, round(size[1] * scale))
    left, right = _GUT, _W - _MARGIN - reserve_right
    return left + (right - left - w) // 2, _MARGIN + (_H - 2 * _MARGIN - h) // 2, w, h


# --- QR code to the arc's web page ----------------------------------------------------

_QR_MODULE = 2               # px per module (a short URL fits a 25-29 module code)
_QR_QUIET = 2                # white modules around it


def get_lan_ip():
    """This machine's LAN address (the interface that would reach the internet), else 127.0.0.1."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('10.255.255.255', 1))      # UDP connect sends nothing; it just picks a route
        return sock.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        sock.close()


def arc_url(config, strip):
    """Where the QR code points: this strip's arc on the config server, or None when there is no arc."""
    if strip.arc_start is None:
        return None
    host = config.get('comic_qr_host') or get_lan_ip()
    port = config.get('config_server_port', 8080)
    comic = config.get('comic_name', 'peanuts')
    query = '' if comic == 'peanuts' else f'?comic={comic}'
    return f'http://{host}:{port}/arc/{strip.arc_start.isoformat()}{query}'


def snoopy_head(size):
    """A small drawn Snoopy head (white face, black ear and nose, eye), `size` px square, 1-bit.

    Drawn procedurally at 4x and averaged down, so there is no image asset to ship.
    """
    k = 4
    big = size * k
    img = Image.new('L', (big, big), 255)
    d = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1):
        return [round(v * big / 100) for v in (x0, y0, x1, y1)]

    w = max(2, big // 16)
    d.ellipse(box(24, 20, 90, 86), fill=255, outline=0, width=w)       # head
    d.ellipse(box(6, 40, 52, 70), fill=255, outline=0, width=w)        # snout
    d.ellipse(box(0, 42, 18, 60), fill=0)                              # nose
    d.ellipse(box(46, 36, 56, 48), fill=0)                             # eye
    d.ellipse(box(66, 22, 96, 78), fill=0)                             # ear
    small = img.resize((size, size), Image.LANCZOS)
    return small.point(lambda v: 255 if v > 140 else 0).convert('1')


def qr_image(url, logo=True):
    """1-bit QR code for `url` with its quiet zone, _QR_MODULE px per module.

    With `logo`, a Snoopy head sits on a white plate in the middle. That needs the
    highest error correction (the logo hides a few percent of the code, well inside
    what level H can restore), so the code is a little bigger than a plain one.
    """
    import segno
    matrix = segno.make(url, error='h' if logo else 'l').matrix
    n = len(matrix) + 2 * _QR_QUIET
    img = Image.new('1', (n * _QR_MODULE, n * _QR_MODULE), 1)
    draw = ImageDraw.Draw(img)
    for y, row in enumerate(matrix):
        for x, cell in enumerate(row):
            if cell:
                px, py = (x + _QR_QUIET) * _QR_MODULE, (y + _QR_QUIET) * _QR_MODULE
                draw.rectangle([px, py, px + _QR_MODULE - 1, py + _QR_MODULE - 1], fill=0)
    if logo:
        side = max(12, round(img.size[0] * 0.27)) // 2 * 2            # even, ~7% of the code's area
        plate = side + 4
        c = img.size[0] // 2
        draw.rectangle([c - plate // 2, c - plate // 2, c + plate // 2 - 1, c + plate // 2 - 1], fill=1)
        img.paste(snoopy_head(side), (c - side // 2, c - side // 2))
    return img


def _date_text(d):
    return f'{_MONTHS[d.month - 1]} {d.day}, {d.year}'


def _years_ago(published, config):
    """Whole years between the strip and the reference date (config['comic_today'] or today)."""
    from datetime import date as _date
    ref = config.get('comic_today') or _date.today()
    return max(0, ref.year - published.year - ((ref.month, ref.day) < (published.month, published.day)))


_HAND_FONT = os.path.join(picdir, 'fonts', 'PatrickHand-Regular.ttf')   # OFL; see pic/fonts/OFL-PatrickHand.txt
_hand_cache: dict = {}


def _hand_font(size):
    """Hand-lettered font for the 'Day x of N' counter (comic-strip feel); the panel font if the file is missing."""
    if size not in _hand_cache:
        try:
            from PIL import ImageFont
            _hand_cache[size] = ImageFont.truetype(_HAND_FONT, size)
        except OSError:
            _hand_cache[size] = _get_font(size)
    return _hand_cache[size]


def _vtext(img, text, font, x, y_bottom, h=14):
    """Draw `text` rotated to read bottom-to-top, its bottom end at y_bottom. Returns its length."""
    w = int(font.getlength(text)) + 2
    tile = Image.new('1', (w, h), 1)
    ImageDraw.Draw(tile).text((1, 0), text, font=font, fill=0)
    tile = tile.rotate(90, expand=True)
    img.paste(tile, (x, y_bottom - tile.size[1]))
    return tile.size[1]


def _timeline(draw, years, current, cx, y0, y1):
    """Year timeline down the gutter, oldest at the top.

    A hairline spine at x=cx, a short tick to its right per available year (longer at
    decades, which also get a tiny two-digit label on the left), and a filled triangle
    pointing at the spine from the right for the current year.
    """
    if y1 - y0 < 20:
        return
    lo, hi = min(years), max(years)
    y0, y1 = y0 + 4, y1 - 4          # room for the marker at either end

    def ypos(yr):
        return (y0 + y1) // 2 if hi == lo else y0 + round((yr - lo) * (y1 - y0) / (hi - lo))

    draw.line([cx, ypos(lo) - 2, cx, ypos(hi) + 2], fill=0, width=1)
    font = _get_font(8)
    last_label = -99
    for yr in years:
        y = ypos(yr)
        if yr % 10 == 0:
            draw.line([cx + 1, y, cx + 3, y], fill=0, width=1)
            if y - last_label >= 10:
                draw.text((cx - 2, y), f'{yr % 100:02d}', font=font, fill=0, anchor='rm')
                last_label = y
        else:
            draw.line([cx + 1, y, cx + 1, y], fill=0, width=1)
    cy = ypos(current)
    draw.polygon([(cx + 1, cy), (cx + 4, cy - 3), (cx + 4, cy + 3)], fill=0)


def draw_comic_screen(strip, config):
    """Render one Strip (see fetch_comic.Strip) as a full panel."""
    img = Image.new('1', (_W, _H), 1)
    draw = ImageDraw.Draw(img)

    # Strip: border trimmed, then as big as the area right of the gutter allows.
    gray = trim_border(strip.image.convert('L'))
    ax, ay, aw, ah = strip_layout(gray.size)
    qr = None
    if config.get('comic_qr', False) and (url := arc_url(config, strip)):
        qr = qr_image(url, logo=config.get('comic_qr_logo', True))
    qr_xy = None
    if qr is not None:
        qw, qh = qr.size
        if ay + ah <= _H - qh - _MARGIN - 2:                       # wide strip: free band underneath
            qr_xy = (ax, _H - qh - _MARGIN)
        elif ax + aw <= _W - _MARGIN - qw - 2:                     # strip leaves a side margin (2x2, Sundays, ...)
            qr_xy = (_W - qw - _MARGIN, _H - qh - _MARGIN)
        else:                                                      # fills both ways: shrink it for a column
            ax, ay, aw, ah = strip_layout(gray.size, reserve_right=qw + 2)
            qr_xy = (_W - qw - _MARGIN, _H - qh - _MARGIN)
    art = prepare_strip(gray, aw, ah)
    img.paste(art, (ax, ay))
    if qr is not None:
        img.paste(qr, qr_xy)

    # Left gutter, bottom to top: caption, year ticks, "n of N" at the top.
    small = _get_font(12)
    gx = 2
    low = _H - 6
    caption = _date_text(strip.date)
    ago = _years_ago(strip.date, config)
    if ago:
        caption += f' · {ago} yr ago' if ago == 1 else f' · {ago} yrs ago'
    if strip.note:
        caption += f' · {strip.note}'
    low -= _vtext(img, caption, small, gx, low) + 8
    high = 6
    if strip.total > 1:
        count = f'{strip.label + " " if strip.label else ""}{strip.position + 1} of {strip.total}'
        hand = _hand_font(14)
        high += _vtext(img, count, hand, gx, high + int(hand.getlength(count)) + 2, h=16) + 8
    _timeline(draw, strip.years, strip.date.year, _GUT - 6, high, low)

    return img    # always white paper, even at night: no black edges around the strip


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
    return draw_comic_screen(strip, dict(config, comic_today=now.date()))


def main(argv=None):
    """CLI: render a strip for any date, e.g. `image_comic.py 1966-10-31 out.png`.

    The date picks the month/day (and so that day's strips); --tag picks from
    prefs.json tags instead. Handy for previewing without the idle rotation.
    """
    import argparse
    from datetime import datetime
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument('date', help='YYYY-MM-DD')
    ap.add_argument('out', help='output image path')
    ap.add_argument('--comic', default='peanuts')
    ap.add_argument('--tag')
    ap.add_argument('--mode', choices=['day', 'week', 'arc', 'arcs'], default='day')
    args = ap.parse_args(argv)
    now = datetime.fromisoformat(args.date)
    config = {'comic_name': args.comic, 'comic_mode': args.mode, 'comic_today': now.date()}
    strip = current_strip(config, now, tag=args.tag)
    if strip is None:
        print('no strip available')
        return 1
    draw_comic_screen(strip, config).save(args.out)
    print(f'wrote {args.out} ({strip.date})')
    return 0


if __name__ == '__main__':   # pragma: no cover
    raise SystemExit(main())
