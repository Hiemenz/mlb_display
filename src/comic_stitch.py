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
  * daily strips lay out in one row, Sunday strips (taller) in 2-3 rows chosen
    to land near a target aspect, with a short last row centred;
  * strips the dataset over-segmented (a detector that sliced word balloons and
    sub-panels out of the art) are rejected: more than MAX_DAILY_PANELS on a
    weekday or MAX_SUNDAY_PANELS on a Sunday can't be reassembled reliably;
  * a lone orphan panel on the last row is avoided when another row count works;
  * the result is capped in size so a 3 GB dataset doesn't become a 3 GB cache.
"""
import io
import math
import re
from datetime import date, datetime

from PIL import Image, ImageOps

_NAME = re.compile(r'^(\d{8})_(\d{1,3})$')

DAILY_ASPECT = 3.8      # four panels side by side
SUNDAY_ASPECT = 1.8     # two or three rows of panels
MIN_PANEL_PX = 24       # anything smaller is a detection artefact
GAP = 6                 # white gutter between panels
MARGIN = 8              # white border around the finished strip
MAX_W, MAX_H = 1000, 640
MAX_DAILY_PANELS = 5     # dailies are 4 panels; more means fragments were detected
MAX_SUNDAY_PANELS = 9    # Sundays are 7-8 panels; beyond 9 the data is fragments
ORPHAN_PENALTY = 0.5     # error added when the last row would hold a single panel
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


def choose_rows(n, sizes, sunday):
    """Number of rows (1-3) whose stitched aspect is closest to the target.

    sizes: [(w, h)] of the panels; used to estimate the finished aspect.
    """
    if n <= 1:
        return 1
    target = SUNDAY_ASPECT if sunday else DAILY_ASPECT
    avg_aspect = sum(w / h for w, h in sizes) / len(sizes)
    best, best_err = 1, float('inf')
    for rows in range(1, min(3, n) + 1):
        per_row = math.ceil(n / rows)
        aspect = per_row * avg_aspect / rows
        err = abs(math.log(aspect / target))
        if per_row > 2 and n - per_row * (rows - 1) == 1:
            err += ORPHAN_PENALTY
        if err < best_err - 1e-9:
            best, best_err = rows, err
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
    per_row = math.ceil(len(images) / rows_n)
    rows = [_row_image(images[i:i + per_row]) for i in range(0, len(images), per_row)]
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

    daily_rows reflows weekday strips into that many rows (2 = a 2x2 block that
    fills more of the panel; None keeps the original single row).
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
