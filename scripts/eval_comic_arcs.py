"""Score Peanuts story-arc detection (src/comic_arcs.py) against storylines with known dates.

    uv run --group comics python scripts/eval_comic_arcs.py [--metadata meta.jsonl] [--dump meta.jsonl]

Without --metadata it downloads the dataset's text columns (as build_comic_arcs does);
--dump saves them to a JSON-lines file so later runs can use --metadata and skip the download.
Prints, per storyline in comic_arcs.KNOWN_STORYLINES, how many arcs it was cut into, how
much of it the best arc holds, and how many outside strips leaked in, plus corpus totals.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comic_arcs import find_arcs, group_strips, score_arcs  # noqa: E402


def report(rows):
    """Text report for `rows` (metadata dicts)."""
    strips = group_strips(rows)
    arcs = find_arcs(strips)
    days = sorted(strips)
    per, coverage = score_arcs(arcs, days)
    lens = [len(a) for a in arcs]
    lines = [f'{len(arcs)} arcs, {sum(lens)} strips, longest {max(lens, default=0)}',
             f'known storylines: mean coverage {coverage:.2f}, '
             f'{sum(r["pieces"] for r in per)} pieces, {sum(r["spill"] for r in per)} spilled strips']
    lines += [f'  {r["name"]:34s} {r["pieces"]} piece(s), best {r["best"]}/{r["total"]}, spill {r["spill"]}'
              for r in per]
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--metadata', help='read rows from this JSON-lines file instead of downloading')
    ap.add_argument('--dump', help='save the downloaded rows to this JSON-lines file')
    args = ap.parse_args(argv)
    if args.metadata:
        with open(args.metadata) as f:
            rows = [json.loads(line) for line in f if line.strip()]
    else:
        from build_comic_arcs import COLUMNS, metadata_rows
        rows = [{k: r.get(k) for k in COLUMNS} for r in metadata_rows()]
        if args.dump:
            with open(args.dump, 'w') as f:
                f.writelines(json.dumps(r) + '\n' for r in rows)
    print(report(rows))
    return 0


if __name__ == '__main__':   # pragma: no cover
    raise SystemExit(main())
