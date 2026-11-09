"""Detect Peanuts story arcs and write them to data/comics/<name>/prefs.json ("arcs").

Reads only text columns (panel_name, characters, themes, caption) of the Hugging Face
shards with HTTP range requests, so it downloads megabytes, not gigabytes:

    uv run --group comics python scripts/build_comic_arcs.py [--name peanuts] [--metadata meta.jsonl]

Existing prefs.json keys (favorites, blocked, tags) are preserved.
"""
import argparse
import json
import os
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))
from comic_arcs import arcs_to_json, find_arcs, group_strips  # noqa: E402
from fetch_comic import COMICS_DIR  # noqa: E402

API = 'https://huggingface.co/api/datasets/afmck/peanuts-opt-6.7b/parquet/default/train'
COLUMNS = ['panel_name', 'characters', 'themes', 'caption']


class RangeFile:
    """Minimal seekable file over HTTP Range requests (what pyarrow needs)."""

    closed = False

    def __init__(self, url):
        head = requests.head(url, allow_redirects=True, timeout=30)
        self.url, self.size, self.pos = head.url, int(head.headers['Content-Length']), 0
        self.session = requests.Session()

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def tell(self):
        return self.pos

    def seekable(self):
        return True

    def readable(self):
        return True

    def read(self, n=-1):
        n = self.size - self.pos if n is None or n < 0 else min(n, self.size - self.pos)
        if n <= 0:
            return b''
        r = self.session.get(self.url, headers={'Range': f'bytes={self.pos}-{self.pos + n - 1}'}, timeout=120)
        r.raise_for_status()
        self.pos += len(r.content)
        return r.content

    def readinto(self, buf):
        data = self.read(len(buf))
        buf[:len(data)] = data
        return len(data)

    def close(self):
        pass


def metadata_rows():
    import pyarrow.parquet as pq
    for url in requests.get(API, timeout=30).json():
        for batch in pq.ParquetFile(RangeFile(url)).iter_batches(batch_size=2000, columns=COLUMNS):
            yield from batch.to_pylist()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name', default='peanuts')
    ap.add_argument('--metadata', help='read rows from this JSON-lines file instead of downloading')
    args = ap.parse_args()
    if args.metadata:
        rows = (json.loads(line) for line in open(args.metadata))
    else:
        rows = metadata_rows()
    arcs = find_arcs(group_strips(rows))
    path = os.path.join(COMICS_DIR, args.name, 'prefs.json')
    try:
        with open(path) as f:
            prefs = json.load(f)
    except (OSError, ValueError):
        prefs = {}
    prefs['arcs'] = arcs_to_json(arcs)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(prefs, f, indent=1)
    print(f'{len(arcs)} arcs -> {path}')


if __name__ == '__main__':
    main()
