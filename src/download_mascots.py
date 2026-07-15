"""Download MLB team mascot images from Wikipedia and save to pic/mascots/.

Usage:
    python src/download_mascots.py [--abbr PHI,NYM,...]

Each image is saved as pic/mascots/{abbr}.png (grayscale PNG).
Teams with no official mascot are skipped silently.
"""
import argparse
import os
import sys
import urllib.request

from PIL import Image, ImageOps, ImageEnhance
import io

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
_MASCOT_DIR = os.path.join(_REPO_ROOT, 'pic', 'mascots')

# Wikipedia article title for each team's primary mascot.
# None = no official mascot; falls back to team logo at display time.
_MASCOT_WIKI = {
    'ARI': None,                       # Baxter — no image on Wikipedia
    'ATL': 'Blooper_(mascot)',
    'BAL': None,                       # The Oriole Bird — no Wikipedia article
    'BOS': 'Wally_the_Green_Monster',
    'CHC': 'Clark_(mascot)',
    'CWS': None,                       # Southpaw — no standalone Wikipedia article
    'CIN': None,                       # Mr. Redlegs — no Wikipedia article
    'CLE': None,                       # Slider — no standalone Wikipedia article
    'COL': None,                       # Dinger — no image on Wikipedia
    'DET': None,                       # PAWS — no Wikipedia article
    'HOU': 'Orbit_(mascot)',
    'KC':  None,                       # Sluggerrr — no standalone Wikipedia article
    'LAA': None,                       # Rally Monkey — not an official mascot
    'LAD': None,                       # No current official mascot
    'MIA': 'Billy_the_Marlin',
    'MIL': 'Bernie_Brewer',
    'MIN': 'TC_Bear',
    'NYM': 'Mr._Met',
    'NYY': None,                       # No official mascot
    'OAK': None,                       # Stomper — no standalone Wikipedia article
    'PHI': 'Phillie_Phanatic',
    'PIT': 'Pirate_Parrot',
    'SD':  None,                       # Swinging Friar — no standalone Wikipedia article
    'SEA': 'Mariner_Moose',
    'SF':  None,                       # Lou Seal — no standalone Wikipedia article
    'STL': 'Fredbird',
    'TB':  None,                       # Raymond — no standalone Wikipedia article
    'TEX': None,                       # Rangers Captain — no Wikipedia article
    'TOR': 'Ace_(mascot)',
    'WSH': 'Screech_(mascot)',
}

_WIKI_API = 'https://en.wikipedia.org/api/rest_v1/page/summary/{title}'
_USER_AGENT = 'mlb-display/1.0 (scoreboard project; github.com/hiemenz/mlb_display)'


def _fetch_image_url(article_title):
    """Return a direct image URL for a Wikipedia article, or None.

    Prefers the full-resolution original; falls back to the default thumbnail.
    """
    import json
    url = _WIKI_API.format(title=article_title)
    req = urllib.request.Request(url, headers={'User-Agent': _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        # originalimage is the full-resolution file — no size restrictions
        original = (data.get('originalimage') or {}).get('source')
        if original:
            return original
        # Fallback: use the thumbnail URL as-is (pre-approved size)
        return (data.get('thumbnail') or {}).get('source')
    except Exception as e:
        print(f"  Wikipedia lookup failed for {article_title!r}: {e}")
        return None


def download_mascot(abbr, force=False):
    """Download and save mascot image for team abbreviation. Returns True on success."""
    article = _MASCOT_WIKI.get(abbr.upper())
    if article is None:
        print(f"  {abbr}: no official mascot defined — skip")
        return False

    out_path = os.path.join(_MASCOT_DIR, f'{abbr}.png')
    if os.path.exists(out_path) and not force:
        print(f"  {abbr}: already downloaded — skip (use --force to re-download)")
        return True

    print(f"  {abbr}: fetching from Wikipedia/{article} …")
    img_url = _fetch_image_url(article)
    if not img_url:
        return False

    try:
        req = urllib.request.Request(img_url, headers={'User-Agent': _USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as r:
            img_bytes = r.read()
    except Exception as e:
        print(f"  {abbr}: image download failed: {e}")
        return False

    try:
        img = Image.open(io.BytesIO(img_bytes)).convert('L')
        # Crop to a square centred on the image (mascots tend to be centred)
        w, h = img.size
        side  = min(w, h)
        left  = (w - side) // 2
        top   = max(0, (h - side) // 3)   # slightly above centre — faces/heads
        top   = min(top, h - side)
        img   = img.crop((left, top, left + side, top + side))
        img   = img.resize((256, 256), Image.LANCZOS)
        img   = ImageOps.autocontrast(img, cutoff=2)
        img   = ImageEnhance.Contrast(img).enhance(1.5)
        os.makedirs(_MASCOT_DIR, exist_ok=True)
        img.save(out_path)
        print(f"  {abbr}: saved → {out_path}")
        return True
    except Exception as e:
        print(f"  {abbr}: image processing failed: {e}")
        return False


def download_all(force=False, abbrs=None):
    import time
    targets = abbrs if abbrs else sorted(_MASCOT_WIKI.keys())
    ok = fail = skip = 0
    for i, abbr in enumerate(targets):
        if i > 0:
            time.sleep(1.5)   # polite rate-limiting for Wikipedia
        result = download_mascot(abbr, force=force)
        if result is True:
            ok += 1
        elif _MASCOT_WIKI.get(abbr.upper()) is None:
            skip += 1
        else:
            fail += 1
    print(f"\nDone: {ok} downloaded, {skip} skipped (no mascot), {fail} failed")


def main():
    parser = argparse.ArgumentParser(description='Download MLB mascot images to pic/mascots/')
    parser.add_argument('--abbr', help='Comma-separated team abbreviations (default: all)')
    parser.add_argument('--force', action='store_true', help='Re-download even if file exists')
    args = parser.parse_args()

    abbrs = [a.strip().upper() for a in args.abbr.split(',')] if args.abbr else None
    download_all(force=args.force, abbrs=abbrs)


if __name__ == '__main__':
    main()
