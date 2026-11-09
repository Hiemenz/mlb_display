"""Reassemble whole comic strips from per-panel images.

The Hugging Face Peanuts dataset ships individual panels named
``YYYYMMDD_NN`` (NN = panel order within the strip). This module is the pure,
network-free half of the importer (scripts/build_comic_cache.py is the I/O
half): validate names, group panels by date, lay them out in rows, and stitch
them into one grayscale image per strip that `fetch_comic.LocalCacheSource`
can read from data/comics/<comic>/YYYY-MM-DD.png.

Edge cases handled here:
  * malformed names and impossible dates (e.g. 19500230) are ignored;
  * duplicate panel indexes keep the larger image; gaps in the sequence still
    stitch what exists (and are reported as `incomplete`);
  * undecodable, tiny, or blank panels are dropped;
  * panels of slightly different sizes are normalised to a common height per row;
  * single-panel strips pass through unchanged;
  * every strip is laid out in 1-3 rows, whichever makes it largest on the
    comic screen (a four-panel daily usually becomes a 2x2 block), with a
    short last row centred;
  * strips the dataset over-segmented (a detector that sliced word balloons and
    sub-panels out of the art) are rejected: more than MAX_DAILY_PANELS on a
    weekday or MAX_SUNDAY_PANELS on a Sunday can't be reassembled reliably;
  * panels are split as evenly as possible across rows (7 -> 3+2+2), so no
    row of three or more ever ends with a lone orphan panel;
  * the result is capped in size so a 3 GB dataset doesn't become a 3 GB cache.
"""
import io
import math
import re
from datetime import date, datetime

from PIL import Image, ImageOps

_NAME = re.compile(r'^(\d{8})_(\d{1,3})$')

PANEL_W, PANEL_H = 776, 468   # room the comic screen gives a strip (see image_comic.strip_layout)
MIN_PANEL_PX = 24       # anything smaller is a detection artefact
GAP = 6                 # white gutter between panels
MARGIN = 8              # white border around the finished strip
MAX_W, MAX_H = 1000, 640
MAX_DAILY_PANELS = 5     # dailies are 4 panels; more means fragments were detected
MAX_SUNDAY_PANELS = 9    # Sundays are 7-8 panels; beyond 9 the data is fragments
BLANK_STDDEV = 2.0      # a panel this flat (all white / all black) carries nothing


def parse_panel_name(name):
    """('YYYY-MM-DD', index) for a valid panel name, else None."""
    m = _NAME.match(name or '')
    if not m:
        return None
    try:
        d = datetime.strptime(m.group(1), '%Y%m%d').date()
    except ValueError:
        return None
    return d.isoformat(), int(m.group(2))


def is_sunday(date_str):
    return date.fromisoformat(date_str).weekday() == 6


def group_panels(items):
    """Group (panel_name, image_bytes) pairs into {date: {index: bytes}}.

    Invalid names are skipped. A repeated index keeps the larger payload (the
    cleaner crop, in practice).
    """
    out = {}
    for name, data in items:
        parsed = parse_panel_name(name)
        if parsed is None or not data:
            continue
        day, idx = parsed
        panels = out.setdefault(day, {})
        if idx not in panels or len(data) > len(panels[idx]):
            panels[idx] = data
    return out


def iter_date_groups(items):
    """Stream (day, {index: bytes}) groups from (panel_name, bytes) pairs in dataset order.

    The dataset is sorted by date, so a group is complete when the date changes;
    this keeps memory to one strip at a time. A date that reappears later
    (out-of-order data) yields a second group; callers decide how to handle it.
    Invalid names and empty payloads are skipped; duplicate indexes keep the
    larger payload.
    """
    cur, panels = None, {}
    for name, data in items:
        parsed = parse_panel_name(name)
        if parsed is None or not data:
            continue
        day, idx = parsed
        if day != cur:
            if panels:
                yield cur, panels
            cur, panels = day, {}
        if idx not in panels or len(data) > len(panels[idx]):
            panels[idx] = data
    if panels:
        yield cur, panels


def _decode(data):
    """Grayscale PIL image from bytes, or None when unusable."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return None
    img = img.convert('L')
    if min(img.size) < MIN_PANEL_PX:
        return None
    extrema = img.getextrema()
    if extrema[1] - extrema[0] <= BLANK_STDDEV:
        return None
    return img


def row_sizes(n, rows):
    """Panels per row, as even as possible (7 in 3 rows -> [3, 2, 2], never 3+3+1)."""
    base, extra = divmod(n, rows)
    return [base + (1 if i < extra else 0) for i in range(rows)]


def choose_rows(n, sizes, sunday=False):
    """Number of rows (1-3) that makes the strip as large as possible on the panel.

    Each candidate layout (panels split evenly across rows) has an estimated
    aspect; the one that fills the largest area of the PANEL_W x PANEL_H box
    (the comic screen minus its gutter) wins. Ties keep fewer rows. `sunday`
    is accepted for callers' convenience; size alone decides.

    sizes: [(w, h)] of the panels; used to estimate the finished aspect.
    """
    if n <= 1:
        return 1
    avg_aspect = sum(w / h for w, h in sizes) / len(sizes)
    best, best_area = 1, 0.0
    for rows in range(1, min(3, n) + 1):
        aspect = max(row_sizes(n, rows)) * avg_aspect / rows
        width = min(PANEL_W, PANEL_H * aspect)
        area = width * width / aspect
        if area > best_area * 1.01:      # must win by 1% to add a row
            best, best_area = rows, area
    return best


def _row_image(imgs):
    """Panels side by side at the median height, white gutters between."""
    h = sorted(i.size[1] for i in imgs)[len(imgs) // 2]
    scaled = [i.resize((max(1, round(i.size[0] * h / i.size[1])), h), Image.LANCZOS) for i in imgs]
    w = sum(i.size[0] for i in scaled) + GAP * (len(scaled) - 1)
    row = Image.new('L', (w, h), 255)
    x = 0
    for i in scaled:
        row.paste(i, (x, 0))
        x += i.size[0] + GAP
    return row


def stitch(images, sunday=False, rows=None):
    """One grayscale strip from ordered panel images.

    rows=None picks the row count automatically; an int forces it (capped at the
    panel count) - e.g. rows=2 reflows a four-panel daily into a 2x2 block.
    """
    if len(images) == 1:
        return ImageOps.expand(images[0], MARGIN, fill=255)
    rows_n = (min(rows, len(images)) if rows
              else choose_rows(len(images), [i.size for i in images], sunday))
    rows, start = [], 0
    for count in row_sizes(len(images), rows_n):
        rows.append(_row_image(images[start:start + count]))
        start += count
    width = max(r.size[0] for r in rows)
    height = sum(r.size[1] for r in rows) + GAP * (len(rows) - 1)
    canvas = Image.new('L', (width, height), 255)
    y = 0
    for r in rows:
        canvas.paste(r, ((width - r.size[0]) // 2, y))    # short last row is centred
        y += r.size[1] + GAP
    return ImageOps.expand(canvas, MARGIN, fill=255)


def cap_size(img, max_w=MAX_W, max_h=MAX_H):
    """Downscale (never upscale) so the strip fits within max_w x max_h."""
    scale = min(max_w / img.size[0], max_h / img.size[1], 1.0)
    if scale >= 1.0:
        return img
    return img.resize((max(1, round(img.size[0] * scale)), max(1, round(img.size[1] * scale))),
                      Image.LANCZOS)


def skip_reason(day, n_panels):
    """Why a date's strip should not be built, or None when the panel count is sane."""
    limit = MAX_SUNDAY_PANELS if is_sunday(day) else MAX_DAILY_PANELS
    if n_panels > limit:
        return f'over-segmented ({n_panels} panels)'
    return None


def build_strip(day, panels, daily_rows=None):
    """(image, meta) for one date's {index: bytes} panels.

    daily_rows forces that many rows for weekday strips (None = choose the
    layout that comes out largest on screen).
    image is None when the date is skipped; meta['skipped'] then says why
    ('over-segmented (N panels)' or 'no usable panels'). Otherwise meta is
    {'panels': used, 'expected': highest index + 1, 'incomplete': bool}.
    """
    reason = skip_reason(day, len(panels))
    if reason:
        return None, {'skipped': reason}
    decoded = []
    for idx in sorted(panels):
        img = _decode(panels[idx])
        if img is not None:
            decoded.append((idx, img))
    if not decoded:
        return None, {'skipped': 'no usable panels'}
    expected = max(panels) + 1
    sunday = is_sunday(day)
    img = cap_size(stitch([i for _, i in decoded], sunday=sunday,
                          rows=None if sunday else daily_rows))
    return img, {'panels': len(decoded), 'expected': expected,
                 'incomplete': len(decoded) < expected}
