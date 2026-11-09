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
from datetime import date as _Date    # Strip has a field named 'date' that shadows the type
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

    def available(self):
        """Every date that has a strip on disk (one directory listing)."""
        out = set()
        for name in self._files():
            m = _FILE_RE.match(name)
            if m:
                try:
                    out.add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
                except ValueError:
                    continue
        return out

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
    label: str = ''           # prefix for the gutter's 'n of N' counter, e.g. 'Day' (arcs mode)
    arc_start: Optional[_Date] = None   # first date of the arc being shown (arcs mode); keys the web page


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


def arc_dates(arc):
    """The strip dates of one prefs.json arc: its stored 'dates', else every non-Sunday from start to end."""
    try:
        if arc.get('dates'):
            return sorted(date.fromisoformat(x) for x in arc['dates'])
        start, end = date.fromisoformat(arc['start']), date.fromisoformat(arc['end'])
    except (AttributeError, KeyError, TypeError, ValueError):
        return []
    days = [start + timedelta(days=k) for k in range((end - start).days + 1)]
    return [d for d in days if d.weekday() != 6]


def find_arc(prefs, start):
    """(strip dates, previous arc start, next arc start) for the arc starting on `start`, or None."""
    arcs = sorted(((ds[0], ds) for ds in (arc_dates(a) for a in prefs.get('arcs') or []) if ds), key=lambda t: t[0])
    for i, (first, ds) in enumerate(arcs):
        if first == start:
            return ds, arcs[i - 1][0] if i else None, arcs[i + 1][0] if i + 1 < len(arcs) else None
    return None


def _arc_index(prefs):
    """{date: (day number, arc length)} for every day inside an arc in prefs['arcs'] (see comic_arcs)."""
    index = {}
    for arc in prefs.get('arcs') or []:
        ds = arc_dates(arc)
        for k, d in enumerate(ds):
            index[d] = (k + 1, len(ds))
    return index


def week_of_year(d):
    """ISO week number 1-52 (the occasional week 53 folds into 52), so the year splits into 52 groups."""
    return min(d.isocalendar()[1], 52)


def _mixed_order(n):
    """Indices 0..n-1 in an order whose neighbours are far apart (a golden-ratio stride).

    Arcs sorted by date, taken in this order, put different years and decades side by
    side, and every arc still comes up exactly once per pass.
    """
    from math import gcd
    stride = max(1, round(n * 0.618))
    while gcd(stride, n) != 1:
        stride += 1
    return [(i * stride) % n for i in range(n)]


def _eligible(source, prefs, config):
    """Predicate for a strip date: not blocked, in the cache, a favorite if favorites-only, a Sunday if sunday-only."""
    blocked = _parse_dates(prefs.get('blocked'))
    favs = _parse_dates(prefs.get('favorites')) if config.get('comic_favorites_only', False) else None
    present = source.available() if hasattr(source, 'available') else None
    sunday = config.get('comic_sunday_only', False)     # Sunday strips: biggest, best-laid-out

    def ok(d):
        return (d not in blocked and (favs is None or d in favs) and (present is None or d in present)
                and (not sunday or d.weekday() == 6))
    return ok


def arc_strip(config, now, source, prefs):
    """Arcs mode: arcs from many years through the day, each played strip by strip, in order.

    Arcs come from prefs.json, with blocked, uncached and (if favorites-only) non-favorite
    days dropped. `comic_arc_order` is 'mixed' (default: neighbouring arcs come from
    different years) or 'chronological'. They are flattened into one playlist and one
    strip shows per `comic_arc_minutes` slot (default 15). The slot counter is the
    minutes since the epoch, so it runs on across midnight with no jump, many arcs play
    through a day, and each shows its first strip to its last before the next begins.
    `comic_arc_offset` shifts the start. Strip.position/.total are 'Day x of N' within
    the arc. Sunday-only mode has no arcs (they are dailies), so it returns None.
    """
    if config.get('comic_sunday_only', False):
        return None
    ok = _eligible(source, prefs, config)
    arcs = sorted((ds for ds in ([d for d in arc_dates(a) if ok(d)] for a in prefs.get('arcs') or []) if ds),
                  key=lambda ds: ds[0])
    if not arcs:
        return None
    if config.get('comic_by_week', False):                  # only arcs that began in this week of the year
        this_week = week_of_year(now.date())
        arcs = [ds for ds in arcs if week_of_year(ds[0]) == this_week] or arcs
    if config.get('comic_arc_order', 'mixed') != 'chronological':
        arcs = [arcs[i] for i in _mixed_order(len(arcs))]
    playlist = [(k, i) for k, ds in enumerate(arcs) for i in range(len(ds))]
    step = max(1, int(config.get('comic_arc_minutes', 15)))
    slot = (now.date().toordinal() * 1440 + now.hour * 60 + now.minute) // step + int(config.get('comic_arc_offset', 0))
    for offset in range(len(playlist)):
        k, i = playlist[(slot + offset) % len(playlist)]
        ds = arcs[k]
        image = source.load(ds[i])
        if image is not None:
            return Strip(ds[i], image, i, len(ds), sorted({d.year for d in ds}), label='Day', arc_start=ds[0])
    return None


def _candidates(source, now, window, ok):
    """(dates, note): this month/day's eligible strips, else the nearest day within `window` days that has some."""
    for offset in range(window + 1):
        for sign in ((1,) if offset == 0 else (1, -1)):
            d = now.date() + timedelta(days=sign * offset)
            dates = [x for x in source.dates_for(d.month, d.day) if ok(x)]
            if dates:
                return sorted(dates), ('' if offset == 0 else 'Nearest day')
    return [], ''


def current_strip(config, now, source=None, tag=None, prefs=None):
    """The Strip to show right now, or None when the source has nothing usable.

    Selection (all optional, via config):
      comic_mode 'day' (default) | 'week' | 'arc' | 'arcs'
                                            arcs = many arcs a day from mixed years, each in order (see arc_strip)
                                            week = same-ish year all week
                                            arc  = week, but only days inside a story arc
                                            (prefs.json 'arcs', built by scripts/build_comic_arcs.py)
      comic_by_week                         split the archive by week of the year: strips (and, in
                                            arcs mode, arcs) from this week number in any year
      comic_fallback_days N (default 3)     nearest day when today has none
      comic_tag / `tag`                     pick from prefs.json tagged dates
      comic_favorites_only                  restrict to prefs.json favorites (every mode)
    Blocked dates (prefs.json) are never shown, in any mode. Unreadable files are skipped,
    falling through to the next strip in order.
    """
    comic = config.get('comic_name', 'peanuts')
    source = source or LocalCacheSource(comic)
    prefs = load_prefs(comic) if prefs is None else prefs
    tag = tag or config.get('comic_tag')
    if config.get('comic_mode', 'day') == 'arcs' and not tag:
        found = arc_strip(config, now, source, prefs)
        if found is not None:
            return found
    ok = _eligible(source, prefs, config)
    note = ''
    dates = []
    if tag:
        tags = prefs.get('tags')
        tags = tags if isinstance(tags, dict) else {}
        want = str(tag).lower()
        dates = sorted(d for d in _parse_dates(tags.keys())
                       if ok(d) and want in [str(t).lower() for t in tags.get(d.isoformat()) or []])
        note = str(tag).title() if dates else ''
    if not dates and config.get('comic_by_week', False) and hasattr(source, 'available'):
        this_week = week_of_year(now.date())                # every strip from this week of the year, any year
        dates = sorted(d for d in source.available() if week_of_year(d) == this_week and ok(d))
    if not dates:
        window = max(0, int(config.get('comic_fallback_days', 3)))
        dates, note = _candidates(source, now, window, ok)
    result = _pick(config, now, source, prefs, dates, note, bool(tag))
    if result is None and tag:                           # tagged strips missing: fall back to the plain day
        return current_strip(dict(config, comic_tag=None), now, source, None, prefs)
    return result


def _pick(config, now, source, prefs, dates, note, tagged):
    """Choose among `dates` by the configured mode and load the first strip that opens."""
    if not dates:
        return None
    years = [d.year for d in dates]
    mode = config.get('comic_mode', 'day')
    if mode in ('week', 'arc') and not tagged:
        arcs = _arc_index(prefs) if mode == 'arc' else {}
        pool = [d for d in dates if d in arcs] or dates
        anchor = _week_anchor_year([d.year for d in pool], now.date())
        best = min(pool, key=lambda d: (abs(d.year - anchor), d))
        start = dates.index(best)
    else:
        minutes = config.get('comic_rotate_minutes', config.get('comic_rotate_hours', 0) * 60)
        start = pick_index(len(dates), now.date(), now, minutes / 60)
    for offset in range(len(dates)):
        i = (start + offset) % len(dates)
        image = source.load(dates[i])
        if image is not None:
            return Strip(dates[i], image, i, len(dates), years, note)
    return None
