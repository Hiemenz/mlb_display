#!/usr/bin/env python3
"""Build the local Peanuts strip cache from the Hugging Face panel dataset.

    uv run --group comics python scripts/build_comic_cache.py

Downloads the dataset's parquet shards one at a time (about 620 MB each, deleted
after use), stitches each date's panels into a whole strip (src/comic_stitch.py)
and writes data/comics/peanuts/YYYY-MM-DD.png for `fetch_comic.LocalCacheSource`.
Existing files are kept, so an interrupted run resumes. Nothing here is committed:
data/comics/ is gitignored.

Dataset: afmck/peanuts-opt-6.7b (license tag "other"; the strips are Charles
Schulz's copyrighted work). Keep the output private, for personal display only.
"""
import argparse
import os
import sys
import tempfile
from collections import Counter

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from comic_stitch import build_strip, iter_date_groups  # noqa: E402

DATASET = 'afmck/peanuts-opt-6.7b'
_API = f'https://huggingface.co/api/datasets/{DATASET}/parquet/default/train'


def shard_urls():
    resp = requests.get(_API, timeout=30)
    resp.raise_for_status()
    return resp.json()


def download(url, dest):
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


def panel_rows(path):
    """(panel_name, image_bytes) from one parquet shard, a batch at a time."""
    import pyarrow.parquet as pq   # optional 'comics' dependency group
    for batch in pq.ParquetFile(path).iter_batches(batch_size=200, columns=['panel_name', 'image']):
        for name, img in zip(batch.column('panel_name').to_pylist(),
                             batch.column('image').to_pylist()):
            yield name, (img or {}).get('bytes')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--out', default=os.path.join('data', 'comics', 'peanuts'))
    ap.add_argument('--shards-dir', help='use already-downloaded *.parquet shards from here')
    ap.add_argument('--max-shards', type=int, help='stop after N shards (testing)')
    ap.add_argument('--daily-rows', type=int, choices=(1, 2), default=None,
                    help='default: pick whatever layout makes each strip largest on the panel '
                         '(usually a 2x2 block for weekdays); 1 forces one wide row, 2 forces 2x2')
    ap.add_argument('--force', action='store_true', help='rebuild strips that already exist')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    stats, written = Counter(), set()

    def handle(day, panels):
        if day in written:
            stats['duplicate date (ignored)'] += 1
            return
        path = os.path.join(args.out, f'{day}.png')
        if os.path.exists(path) and not args.force:
            stats['already built'] += 1
            written.add(day)
            return
        img, meta = build_strip(day, panels, daily_rows=args.daily_rows)
        if img is None:
            stats[f"skipped: {meta['skipped'].split(' (')[0]}"] += 1
            return
        img.save(path, optimize=True)
        written.add(day)
        stats['built'] += 1
        stats['incomplete' if meta['incomplete'] else 'complete'] += 1
        if stats['built'] % 500 == 0:
            print(f"  {stats['built']} strips built (at {day})", flush=True)

    if args.shards_dir:
        shards = sorted(os.path.join(args.shards_dir, f) for f in os.listdir(args.shards_dir)
                        if f.endswith('.parquet'))
        fetch = None
    else:
        shards, fetch = shard_urls(), download
    if args.max_shards:
        shards = shards[:args.max_shards]

    # A strip can straddle two shards: hold the last group back until the next
    # shard shows whether it continues.
    pending = None
    with tempfile.TemporaryDirectory() as tmp:
        for n, shard in enumerate(shards, 1):
            path = shard
            if fetch:
                path = os.path.join(tmp, f'{n}.parquet')
                print(f'[{n}/{len(shards)}] downloading {shard}', flush=True)
                fetch(shard, path)
            print(f'[{n}/{len(shards)}] stitching', flush=True)
            for day, panels in iter_date_groups(panel_rows(path)):
                if pending and pending[0] == day:      # continuation across the shard boundary
                    for idx, data in panels.items():
                        if idx not in pending[1] or len(data) > len(pending[1][idx]):
                            pending[1][idx] = data
                    continue
                if pending:
                    handle(*pending)
                pending = (day, panels)
            if fetch:
                os.remove(path)
        if pending:
            handle(*pending)

    print('\nDone.')
    for k, v in sorted(stats.items()):
        print(f'  {k}: {v}')


if __name__ == '__main__':
    main()
