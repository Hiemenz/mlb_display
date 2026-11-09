"""Find multi-day story arcs in the Peanuts dailies from the dataset's own metadata.

The Hugging Face dataset labels every panel with `characters`, `themes` and a
machine caption. None of those name a storyline, but consecutive days of one
share characters and words, so consecutive dailies are linked when their
similarity is high enough and the chains become arcs. Pure and network-free;
scripts/build_comic_arcs.py is the I/O half and writes the result to
data/comics/<name>/prefs.json under "arcs".

Tuned against arcs with known dates: the Living Blanket (March 1965), the
Great Pumpkin's debut (Oct 26 1959) and the October 1965 Red Baron start.
Sundays stand alone (one self-contained strip), and arcs are 3-14 days.
"""
import math
import re
from collections import Counter, defaultdict
from datetime import date

THRESH, TEXT_WEIGHT = 0.34, 0.3
MIN_TEXT = 0.0                   # a link also needs at least this much caption-text overlap
MIN_LEN, MAX_LEN = 3, 14
MAX_GAP_DAYS = 3                 # Sat -> Mon is 2; one skipped day on top is tolerated
_STOP = set('a an the and or but of to in on at is it its was be he she they his her their that this with for as by '
            'from not no you we me my your do does did have has had so if then than there here what who how said '
            'says say one two just very out up down all are were been into over about'.split())
_GENERIC = {'panel', 'comic', 'strip', 'cartoon', 'shows', 'showing', 'drawing', 'picture', 'image', 'black',
            'white', 'speech', 'bubble', 'text', 'saying', 'thought', 'character', 'characters', 'brown',
            'charlie', 'peanuts', 'words', 'word', 'coloring', 'page'}
_PANEL = re.compile(r'^(\d{4})(\d{2})(\d{2})_')


def _tokens(text):
    return [w for w in re.findall(r"[a-z']+", (text or '').lower())
            if len(w) > 2 and w not in _STOP and w not in _GENERIC]


def group_strips(rows):
    """{date: {'caps': [...], 'chars': set, 'themes': set}} from metadata rows (dicts)."""
    strips = defaultdict(lambda: {'caps': [], 'chars': set(), 'themes': set()})
    for r in rows:
        m = _PANEL.match(r.get('panel_name') or '')
        if not m:
            continue
        try:
            d = date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            continue
        s = strips[d]
        s['caps'].append(r.get('caption') or '')
        s['chars'].update(r.get('characters') or [])
        s['themes'].update(r.get('themes') or [])
    return dict(strips)


def _text_vectors(strips):
    docs = {d: Counter(_tokens(' '.join(s['caps'])) + [f'T:{t}' for t in s['themes']]) for d, s in strips.items()}
    df = Counter(w for c in docs.values() for w in c)
    n = len(docs)
    vec = {}
    for d, c in docs.items():
        v = {w: (1 + math.log(k)) * math.log(n / df[w]) for w, k in c.items() if df[w] < n * 0.2}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vec[d] = {w: x / norm for w, x in v.items()}
    return vec


def _char_vectors(strips):
    df = Counter(c for s in strips.values() for c in s['chars'])
    n = len(strips)
    return {d: {c: math.log(n / df[c]) for c in s['chars']} for d, s in strips.items()}


def _cos(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(w, 0.0) for w, x in a.items())


def _wjaccard(a, b):
    union = sum(max(a.get(c, 0.0), b.get(c, 0.0)) for c in set(a) | set(b))
    return sum(min(a[c], b[c]) for c in a if c in b) / union if union else 0.0


def find_arcs(strips, thresh=THRESH, text_weight=TEXT_WEIGHT, min_text=MIN_TEXT):
    """List of arcs, each a sorted list of `date`s, longest-first de-overlapped, in date order."""
    days = sorted(d for d in strips if d.weekday() != 6)
    if not days:
        return []
    tv, cv = _text_vectors(strips), _char_vectors(strips)

    def sim(a, b):
        return text_weight * _cos(tv[a], tv[b]) + (1 - text_weight) * _wjaccard(cv[a], cv[b])

    parent = {d: d for d in days}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(days):                      # link each day to the next two
        for b in days[i + 1:i + 3]:
            if (b - a).days > MAX_GAP_DAYS + 1:
                break
            if sim(a, b) >= thresh and _cos(tv[a], tv[b]) >= min_text:
                parent[find(b)] = find(a)
    groups = defaultdict(list)
    for d in days:
        groups[find(d)].append(d)

    def runs(ds):
        cur = [ds[0]]
        for a, b in zip(ds, ds[1:]):
            if (b - a).days <= MAX_GAP_DAYS:
                cur.append(b)
            else:
                yield cur
                cur = [b]
        yield cur

    def split(run):                                   # cut over-long chains at their weakest link
        if len(run) <= MAX_LEN:
            return [run]
        links = [(sim(run[i], run[i + 1]), i) for i in range(MIN_LEN - 1, len(run) - MIN_LEN)]
        _, i = min(links)
        return split(run[:i + 1]) + split(run[i + 1:])

    pieces = [p for g in groups.values() for r in runs(sorted(g)) for p in split(r) if len(p) >= MIN_LEN]
    accepted, taken = [], []                          # longest first; reject any whose span overlaps
    for p in sorted(pieces, key=lambda p: (-len(p), p[0])):
        if all(p[-1] < lo or p[0] > hi for lo, hi in taken):
            accepted.append(p)
            taken.append((p[0], p[-1]))
    return sorted(accepted)


def arcs_to_json(arcs):
    """Compact form for prefs.json: [{'start', 'end', 'days', 'dates'}] (dates = the strips actually in the arc)."""
    return [{'start': a[0].isoformat(), 'end': a[-1].isoformat(), 'days': len(a),
             'dates': [d.isoformat() for d in a]} for a in arcs]
