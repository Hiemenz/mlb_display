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
import json
import os
import re
from datetime import date, timedelta
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
    note: str = ''            # extra caption, e.g. 'Day 3 of 7' or 'Nearest day'


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


def load_prefs(comic, root=None):
    """Optional hand-edited data/comics/<comic>/prefs.json.

        {"favorites": ["1966-10-31"], "blocked": ["1971-03-02"],
         "tags": {"1966-10-31": ["halloween"], "1970-04-05": ["baseball"]}}

    Missing or unreadable files mean no preferences. Dates are ISO strings.
    """
    path = os.path.join(root or COMICS_DIR, comic, 'prefs.json')
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_dates(values):
    out = set()
    for v in values or []:
        try:
            out.add(date.fromisoformat(v))
        except (TypeError, ValueError):
            continue
    return out


def _week_anchor_year(years, today):
    """A year for this ISO week, stable all week, so consecutive days come from
    nearby publication years (Peanuts story arcs run several days)."""
    iso = today.isocalendar()
    digest = hashlib.sha256(f'{iso[0]}-{iso[1]}'.encode()).digest()
    lo, hi = min(years), max(years)
    return lo + int.from_bytes(digest[:4], 'big') % (hi - lo + 1)


def _arc_index(prefs):
    """{date: (day number, arc length)} for every day inside an arc in prefs['arcs'] (see comic_arcs)."""
    index = {}
    for arc in prefs.get('arcs') or []:
        try:
            start, end = date.fromisoformat(arc['start']), date.fromisoformat(arc['end'])
        except (KeyError, TypeError, ValueError):
            continue
        n = (end - start).days + 1
        for k in range(n):
            index[start + timedelta(days=k)] = (k + 1, n)
    return index


def _candidates(source, now, window, blocked):
    """(dates, note): this month/day's strips, else the nearest day within `window` days."""
    for offset in range(window + 1):
        for sign in ((1,) if offset == 0 else (1, -1)):
            d = now.date() + timedelta(days=sign * offset)
            dates = [x for x in source.dates_for(d.month, d.day) if x not in blocked]
            if dates:
                return sorted(dates), ('' if offset == 0 else 'Nearest day')
    return [], ''


def current_strip(config, now, source=None, tag=None, prefs=None):
    """The Strip to show right now, or None when the source has nothing usable.

    Selection (all optional, via config):
      comic_mode 'day' (default) | 'week' | 'arc'
                                            week = same-ish year all week
                                            arc  = week, but only days inside a story arc
                                            (prefs.json 'arcs', built by scripts/build_comic_arcs.py)
      comic_fallback_days N (default 3)     nearest day when today has none
      comic_tag / `tag`                     pick from prefs.json tagged dates
      comic_favorites_only                  restrict to prefs.json favorites
    Blocked dates (prefs.json) are never shown. Unreadable files are skipped,
    falling through to the next strip in order.
    """
    comic = config.get('comic_name', 'peanuts')
    source = source or LocalCacheSource(comic)
    prefs = load_prefs(comic) if prefs is None else prefs
    blocked = _parse_dates(prefs.get('blocked'))
    note = ''
    tag = tag or config.get('comic_tag')
    dates = []
    if tag:
        dates = sorted(_parse_dates((prefs.get('tags') or {}).keys()) - blocked)
        dates = [d for d in dates if tag in (prefs['tags'].get(d.isoformat()) or [])]
        note = tag.title() if dates else ''
    if not dates:
        window = max(0, int(config.get('comic_fallback_days', 3)))
        dates, note = _candidates(source, now, window, blocked)
    if config.get('comic_sunday_only', False):
        dates = [d for d in dates if d.weekday() == 6]   # Sunday strips: biggest, best-laid-out
    if config.get('comic_favorites_only', False):
        favs = _parse_dates(prefs.get('favorites'))
        dates = [d for d in dates if d in favs]
    if not dates:
        return None
    years = [d.year for d in dates]
    mode = config.get('comic_mode', 'day')
    if mode in ('week', 'arc') and not tag:
        arcs = _arc_index(prefs) if mode == 'arc' else {}
        pool = [d for d in dates if d in arcs] or dates
        anchor = _week_anchor_year([d.year for d in pool], now.date())
        best = min(pool, key=lambda d: (abs(d.year - anchor), d))
        start = dates.index(best)
        if not note:
            note = f'Arc day {arcs[best][0]} of {arcs[best][1]}' if best in arcs else f'Day {now.weekday() + 1} of 7'
    else:
        minutes = config.get('comic_rotate_minutes', config.get('comic_rotate_hours', 0) * 60)
        start = pick_index(len(dates), now.date(), now, minutes / 60)
    for offset in range(len(dates)):
        i = (start + offset) % len(dates)
        image = source.load(dates[i])
        if image is not None:
            return Strip(dates[i], image, i, len(dates), years, note)
    return None
