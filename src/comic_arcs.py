"""Find multi-day story arcs in the Peanuts dailies from the dataset's own metadata.

The Hugging Face dataset labels every panel with `characters`, `themes` and a
machine caption. None of those name a storyline, but the days of one share
characters and words. The tags and captions are noisy for any single day, so
boundaries are found TextTiling-style: at every gap between dailies the WINDOW
days before it are pooled and compared with the WINDOW days after it, and a gap
whose similarity falls below THRESH ends an arc. Pure and network-free;
scripts/build_comic_arcs.py is the I/O half and writes the result to
data/comics/<name>/prefs.json under "arcs".

Scored with scripts/eval_comic_arcs.py against storylines with known dates
(KNOWN_STORYLINES), including the strip's longest, Sep 13 - Oct 28 1976 (almost
seven weeks, per the Annotations of The Complete Peanuts), hence MAX_LEN 42.
Sundays stand alone (one self-contained strip).
"""
import math
import re
from collections import Counter, defaultdict
from datetime import date

THRESH, TEXT_WEIGHT = 0.25, 0.5
WINDOW = 3                       # dailies pooled on each side of a gap
EDGE_THRESH, EDGE_TEXT_WEIGHT = 0.34, 0.3   # one-to-one similarity that pulls a stray edge day into an arc
MIN_LEN, MAX_LEN = 3, 42         # 42 = seven weeks of dailies
MAX_GAP_DAYS = 3                 # Sat -> Mon is 2; one skipped day on top is tolerated

# Storylines with known (approximate) dates, the benchmark for scripts/eval_comic_arcs.py.
# 1976: Annotations of The Complete Peanuts ("the strip's longest storyline"); the rest were
# located from the dataset captions (e.g. 'hospital', 'big brother', 'president', 'sack').
KNOWN_STORYLINES = {
    'Great Pumpkin debut': ('1959-10-26', '1959-11-03'),
    'Linus runs for school president': ('1964-10-05', '1964-10-22'),
    'Living blanket': ('1965-03-11', '1965-03-25'),
    'Mr. Sack at camp': ('1973-06-16', '1973-07-04'),
    'Summer camp': ('1974-06-24', '1974-07-09'),
    'Ace Obedience School': ('1976-09-13', '1976-10-27'),
    'Charlie Brown in hospital': ('1979-07-03', '1979-08-03'),
}
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


def _pool(vectors):
    """Mean of sparse vectors (dicts)."""
    out = Counter()
    for v in vectors:
        out.update(v)
    return {k: x / len(vectors) for k, x in out.items()}


def _unit(v):
    norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {k: x / norm for k, x in v.items()}


def _runs(days):
    """Split sorted dates wherever the calendar gap exceeds MAX_GAP_DAYS (no arc spans it)."""
    cur = [days[0]]
    for a, b in zip(days, days[1:]):
        if (b - a).days <= MAX_GAP_DAYS:
            cur.append(b)
        else:
            yield cur
            cur = [b]
    yield cur


def _split(run, scores, lo, hi):
    """run[lo..hi] (inclusive) as arcs of at most MAX_LEN, cut at the weakest gaps (scores[i] = gap after run[i])."""
    if hi - lo + 1 <= MAX_LEN:
        return [run[lo:hi + 1]]
    cut = min(range(lo + MIN_LEN - 1, hi - MIN_LEN + 1), key=lambda i: scores[i])
    return _split(run, scores, lo, cut) + _split(run, scores, cut + 1, hi)


def find_arcs(strips, thresh=THRESH, text_weight=TEXT_WEIGHT, window=WINDOW):
    """List of arcs, each a sorted list of `date`s, in date order (TextTiling over the dailies)."""
    days = sorted(d for d in strips if d.weekday() != 6)
    if not days:
        return []
    tv, cv = _text_vectors(strips), _char_vectors(strips)

    def gap_score(left, right):                       # pooled similarity of the days either side
        text = _cos(_unit(_pool([tv[d] for d in left])), _unit(_pool([tv[d] for d in right])))
        chars = _wjaccard(_pool([cv[d] for d in left]), _pool([cv[d] for d in right]))
        return text_weight * text + (1 - text_weight) * chars

    def pair(a, b):                                   # one-to-one similarity of two days
        return EDGE_TEXT_WEIGHT * _cos(tv[a], tv[b]) + (1 - EDGE_TEXT_WEIGHT) * _wjaccard(cv[a], cv[b])

    arcs = []
    for run in _runs(days):
        scores = [gap_score(run[max(0, i - window + 1):i + 1], run[i + 1:i + 1 + window])
                  for i in range(len(run) - 1)]

        segs, start = [], 0                           # [lo, hi] index ranges between low-scoring gaps
        for i in range(len(scores) + 1):              # the extra index closes the last segment
            if i == len(scores) or scores[i] < thresh:
                segs.append([start, i])
                start = i + 1
        # A window straddling a boundary drags the gap before it down too, orphaning an arc's
        # first or last day in a short segment; give such days back when they match one-to-one.
        for k, seg in enumerate(segs):
            if seg[1] - seg[0] + 1 < MIN_LEN:
                continue
            while k + 1 < len(segs) and segs[k + 1][1] - segs[k + 1][0] + 1 < MIN_LEN \
                    and pair(run[seg[1]], run[seg[1] + 1]) >= EDGE_THRESH:
                seg[1] += 1
                segs[k + 1][0] += 1
                if segs[k + 1][0] > segs[k + 1][1]:
                    del segs[k + 1]
            while k and segs[k - 1][1] - segs[k - 1][0] + 1 < MIN_LEN and segs[k - 1][1] >= segs[k - 1][0] \
                    and pair(run[seg[0] - 1], run[seg[0]]) >= EDGE_THRESH:
                seg[0] -= 1
                segs[k - 1][1] -= 1
        arcs += [a for lo, hi in segs if hi >= lo for a in _split(run, scores, lo, hi) if len(a) >= MIN_LEN]
    return arcs


def score_arcs(arcs, days, known=None):
    """How well `arcs` recover the known storylines.

    `days` are all dailies in the corpus. Per storyline: pieces = arcs overlapping it,
    best = its dailies inside the single best arc, total = its dailies, spill = dailies
    outside it pulled in by those arcs. Returns (rows, mean coverage best/total).
    """
    known = KNOWN_STORYLINES if known is None else known
    rows = []
    for name, (s, e) in known.items():
        s, e = date.fromisoformat(s), date.fromisoformat(e)
        core = {d for d in days if s <= d <= e and d.weekday() != 6}
        pieces = [a for a in arcs if a[-1] >= s and a[0] <= e]
        best = max((len(core.intersection(a)) for a in pieces), default=0)
        spill = sum(1 for a in pieces for d in a if d < s or d > e)
        rows.append({'name': name, 'pieces': len(pieces), 'best': best, 'total': len(core), 'spill': spill})
    coverage = sum(r['best'] / r['total'] for r in rows if r['total']) / max(1, sum(1 for r in rows if r['total']))
    return rows, coverage


def arcs_to_json(arcs):
    """Compact form for prefs.json: [{'start', 'end', 'days', 'dates'}] (dates = the strips actually in the arc)."""
    return [{'start': a[0].isoformat(), 'end': a[-1].isoformat(), 'days': len(a),
             'dates': [d.isoformat() for d in a]} for a in arcs]
