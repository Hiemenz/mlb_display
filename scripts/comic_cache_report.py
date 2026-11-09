"""Report on the local comic cache: how many strips, which years, which calendar days have none.

    uv run python scripts/comic_cache_report.py [comic]
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))
from fetch_comic import COMICS_DIR, LocalCacheSource, load_prefs  # noqa: E402


def report(comic='peanuts', root=None):
    src = LocalCacheSource(comic, root)
    per_day = {}
    d = date(2024, 1, 1)           # a leap year: covers Feb 29
    while d.year == 2024:
        per_day[(d.month, d.day)] = src.dates_for(d.month, d.day)
        d += timedelta(days=1)
    all_dates = sorted(x for v in per_day.values() for x in v)
    empty = [md for md, v in per_day.items() if not v]
    prefs = load_prefs(comic, root)
    lines = [f'comic: {comic}', f'strips: {len(all_dates)}']
    if all_dates:
        lines.append(f'years: {all_dates[0].year}-{all_dates[-1].year}')
    lines.append(f'calendar days with no strip: {len(empty)} of {len(per_day)}')
    if empty:
        lines.append('  ' + ', '.join(f'{m:02d}-{dd:02d}' for m, dd in empty[:40]) + (' ...' if len(empty) > 40 else ''))
    lines.append(f"favorites: {len(prefs.get('favorites', []))}, blocked: {len(prefs.get('blocked', []))}, "
                 f"tagged: {len(prefs.get('tags', {}))}")
    return '\n'.join(lines)


if __name__ == '__main__':   # pragma: no cover
    print(report(sys.argv[1] if len(sys.argv) > 1 else 'peanuts', COMICS_DIR if len(sys.argv) < 3 else sys.argv[2]))
