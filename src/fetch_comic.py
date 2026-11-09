"""Pick the "on this day" comic strip to show when there are no games.

This module deliberately contains NO downloader. Where strips come from is a
`ComicSource`; the one that ships, `LocalCacheSource`, reads image files the
user has put in a gitignored folder:

    data/comics/<comic>/YYYY-MM-DD.png      (.jpg / .jpeg / .gif also work)

so strips the user supplies, or a future licensed/permitted downloader writes
there, just work. To plug in a different source, implement `dates_for` and
`load` (see the `ComicSource` protocol) and pass it to `current_strip`.

Selection is deterministic: one strip per calendar date chosen by a stable hash
of that date (`comic_rotate_minutes: 0`, the default), or every strip published
on this month/day rotating through the day every `comic_rotate_minutes` minutes.
Each strip carries its original publication date.
"""
import hashlib
import os
import re
from datetime import date
from typing import NamedTuple, Optional, Protocol

from PIL import Image

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMICS_DIR = os.path.join(_REPO_ROOT, 'data', 'comics')   # gitignored

_FILE_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})\.(png|jpe?g|gif)$', re.I)


class ComicSource(Protocol):
    """Where strips come from. Implement these two methods to add a source."""

    def dates_for(self, month: int, day: int) -> list:
        """Publication dates (datetime.date) of every strip on this month/day."""
        ...

    def load(self, when: date) -> Optional[Image.Image]:
        """The strip published on `when` as a PIL image, or None if unavailable."""
        ...


class LocalCacheSource:
    """Strips stored as data/comics/<comic>/YYYY-MM-DD.<ext>."""

    def __init__(self, comic='peanuts', root=None):
        self.comic = comic
        self.dir = os.path.join(root or COMICS_DIR, comic)

    def _files(self):
        try:
            return os.listdir(self.dir)
        except OSError:
            return []

    def _path(self, when):
        stem = when.isoformat()
        for name in self._files():
            if _FILE_RE.match(name) and name.startswith(stem + '.'):
                return os.path.join(self.dir, name)
        return None

    def dates_for(self, month, day):
        found = set()
        for name in self._files():
            m = _FILE_RE.match(name)
            if not m or (int(m.group(2)), int(m.group(3))) != (month, day):
                continue
            try:
                found.add(date(int(m.group(1)), month, day))
            except ValueError:
                continue
        return sorted(found)

    def load(self, when):
        path = self._path(when)
        if path is None:
            return None
        try:
            with Image.open(path) as im:
                return im.convert('L')
        except Exception:
            return None


class Strip(NamedTuple):
    date: date                # original publication date
    image: Image.Image        # grayscale
    position: int             # 0-based position among this date's strips
    total: int                # how many strips exist for this month/day
    years: list               # publication years of all of them (sorted)


def pick_index(count, today, now, rotate_hours=0):
    """Which of `count` strips to show.

    rotate_hours <= 0: one strip all day (stable hash of today's date).
    Otherwise: step through them every `rotate_hours` hours, keyed to the wall
    clock so every cron tick in the same slot picks the same strip.
    """
    if count <= 0:
        return 0
    step = int((rotate_hours or 0) * 60)
    if step >= 1:
        minute_of_epoch = today.toordinal() * 1440 + now.hour * 60 + now.minute
        return (minute_of_epoch // step) % count
    digest = hashlib.sha256(today.isoformat().encode()).digest()
    return int.from_bytes(digest[:4], 'big') % count


def current_strip(config, now, source=None):
    """The Strip to show right now, or None when the source has nothing usable.

    Unreadable files are skipped, falling through to the next strip in order.
    """
    source = source or LocalCacheSource(config.get('comic_name', 'peanuts'))
    dates = sorted(source.dates_for(now.month, now.day))
    if config.get('comic_sunday_only', False):
        dates = [d for d in dates if d.weekday() == 6]   # Sunday strips: biggest, best-laid-out
    if not dates:
        return None
    minutes = config.get('comic_rotate_minutes', config.get('comic_rotate_hours', 0) * 60)
    start = pick_index(len(dates), now.date(), now, minutes / 60)
    years = [d.year for d in dates]
    for offset in range(len(dates)):
        i = (start + offset) % len(dates)
        image = source.load(dates[i])
        if image is not None:
            return Strip(dates[i], image, i, len(dates), years)
    return None
