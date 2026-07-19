import sys
import os
import json

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance

picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')
emojidir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic', 'emojis')
logodir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic', 'logos')
logo_cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic', 'logos_cache')
libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')

if os.path.exists(libdir):  # pragma: no cover
    sys.path.append(libdir)

# ESPN CDN abbreviation overrides
_ESPN_ABBR_MAP = {'AZ': 'ari', 'CWS': 'chw', 'WSH': 'wsh'}
# Maps our internal WBC abbreviations to ESPN's country CDN slug (used in fallback path)
_COUNTRY_ESPN_MAP = {'CLM': 'col'}  # Colombia WBC uses 'col' on ESPN countries CDN
# Team IDs whose cached abbreviation must be overridden (WBC teams that collide with MLB)
_TEAM_ID_ABBR_OVERRIDE = {'792': 'CLM'}  # Colombia WBC team ID → CLM
# Only try ESPN countries CDN for known national-team abbreviations (WBC, sport_id 8,
# plus other international/Olympic-style entries under sport_id 51). This prevents false
# positives where AAA team abbreviations like CHA/POR/SOM accidentally match country codes.
# Most sport_id 51 national teams already resolve via the mlbstatic-by-team_id fallback
# above, so this list only needs to cover the ones that don't (verified against ESPN's
# countries CDN and the live MLB Stats API team list for sport_id 51).
_WBC_ABBRS = {
    'USA', 'DOM', 'JPN', 'MEX', 'KOR', 'PUR', 'CUB', 'AUS', 'NED',
    'ITA', 'CAN', 'VEN', 'PAN', 'CLM', 'GBR', 'ISR', 'CZE', 'NIC', 'TPE', 'CHN',
    'CRO', 'LTU', 'GUA',
}

# Font cache — avoids re-parsing Font.ttc on every draw_box() call (called once per game cell)
_font_cache: dict = {}

def _get_font(size: int):
    """Get font."""
    if size not in _font_cache:
        _font_cache[size] = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), size)
    return _font_cache[size]


_logo_cache: dict = {}        # (abbr, team_id) -> grayscale PIL Image or None
_logo_invert_config = None  # loaded once from pic/logo_render_config.json


def _get_logo_invert_config():
    """Get logo invert config."""
    global _logo_invert_config
    if _logo_invert_config is None:
        config_path = os.path.join(picdir, 'logo_render_config.json')
        try:
            with open(config_path) as f:
                _logo_invert_config = json.load(f)
        except Exception:
            _logo_invert_config = {}
    return _logo_invert_config


def _milb_logo_dir(sport_id):
    """Return the per-sport logo subdirectory for MiLB teams (created on demand)."""
    d = os.path.join(logodir, str(sport_id))
    os.makedirs(d, exist_ok=True)
    return d


def _try_download_logo(abbr, team_id=None, sport_id=None):
    """Download a missing team logo from ESPN CDN using stdlib only (no pip needed).

    Tries MLB CDN first, then midfield PNG CDN for MiLB (no cairosvg required),
    then mlbstatic SVG fallback (requires cairosvg + libcairo2),
    then ESPN countries CDN only for known WBC abbreviations.
    Skips numeric or T{id} fallback abbreviations.

    MiLB logos are stored in pic/logos/{sport_id}/{team_id}.png to keep leagues
    separate and avoid ID collisions between sports.
    """
    if abbr.isdigit() or (abbr.startswith('T') and abbr[1:].isdigit()):
        return False

    import urllib.request
    path = os.path.join(logodir, f'{abbr}.png')
    os.makedirs(logodir, exist_ok=True)

    # Try ESPN MLB CDN first
    try:
        espn = _ESPN_ABBR_MAP.get(abbr.upper(), abbr.lower())
        non_dark = _get_logo_invert_config().get('non_dark', [])
        variant = 'mlb/500' if abbr.upper() in non_dark else 'mlb/500-dark'
        url = f'https://a.espncdn.com/i/teamlogos/{variant}/{espn}.png'
        with urllib.request.urlopen(url, timeout=5) as response:
            with open(path, 'wb') as f:
                f.write(response.read())
        print(f'Auto-downloaded logo: {abbr}')
        return True
    except Exception:
        pass

    # MiLB teams: validate via mlbstatic SVG (404s for non-existent teams), then download
    # PNG from midfield CDN (no cairosvg required).
    # Stored in pic/logos/{sport_id}/{team_id}.png; sport_id defaults to 0 when unknown.
    if team_id and str(team_id).isdigit():
        sid = sport_id if sport_id is not None else 0
        id_path = os.path.join(_milb_logo_dir(sid), f'{team_id}.png')
        try:
            # HEAD the SVG first — mlbstatic returns 404 for invalid/non-existent teams
            # while midfield CDN returns 200 with a generic placeholder for any ID.
            svg_url = f'https://www.mlbstatic.com/team-logos/{team_id}.svg'
            head_req = urllib.request.Request(svg_url, method='HEAD',
                                              headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(head_req, timeout=5):
                pass  # 200 = team exists; 404 raises HTTPError → skip download

            png_url = f'https://midfield.mlbstatic.com/v1/team/{team_id}/spots/96'
            req = urllib.request.Request(png_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
            with open(id_path, 'wb') as f:
                f.write(data)
            print(f'Auto-downloaded MiLB logo: {abbr}')
            return True
        except Exception:
            pass

        # Fallback: convert SVG to PNG via cairosvg (requires libcairo2 system lib)
        try:
            import cairosvg
            svg_data = urllib.request.urlopen(svg_url, timeout=5).read()
            cairosvg.svg2png(bytestring=svg_data, write_to=id_path, output_width=500)
            print(f'Auto-downloaded MiLB logo (SVG): {abbr}')
            return True
        except Exception:
            pass

    # ESPN countries CDN — only for known WBC abbreviations to avoid false positives
    if abbr.upper() in _WBC_ABBRS:
        try:
            espn = _COUNTRY_ESPN_MAP.get(abbr.upper(), abbr.lower())
            url = f'https://a.espncdn.com/i/teamlogos/countries/500/{espn}.png'
            with urllib.request.urlopen(url, timeout=5) as response:
                with open(path, 'wb') as f:
                    f.write(response.read())
            print(f'Auto-downloaded country logo: {abbr}')
            return True
        except Exception as e:
            print(f'Could not auto-download logo for {abbr}: {e}')

    return False


def _load_logo_gray(abbr, team_id):
    """Load a team logo PNG and return it as a grayscale (L-mode) PIL Image, or None.

    Inversion is determined by pic/logo_render_config.json (committed to git) so
    every machine renders logos identically. Falls back to brightness detection for
    any team not in the config. Results are cached in _logo_cache per process.
    """
    emoji_img = _load_emoji_gray(abbr)
    if emoji_img is not None:
        return emoji_img

    cache_key = (abbr, str(team_id))
    if cache_key in _logo_cache:
        return _logo_cache[cache_key]

    invert_config = _get_logo_invert_config()

    abbr_path = os.path.join(logodir, f'{abbr}.png')
    id_path   = os.path.join(logodir, f'{str(team_id)}.png')

    # MiLB logos live in pic/logos/{sport_id}/{team_id}.png subdirs.
    # Scan all numeric subdirs to find one that has this team_id.
    subdir_id_path = None
    if team_id and str(team_id).isdigit() and not os.path.exists(id_path):
        import glob as _glob
        matches = _glob.glob(os.path.join(logodir, '*', f'{team_id}.png'))
        if matches:
            subdir_id_path = matches[0]

    # Auto-download once if no logo file exists anywhere
    if not os.path.exists(abbr_path) and not os.path.exists(id_path) and not subdir_id_path:
        _try_download_logo(abbr, team_id=team_id)
        # Re-check subdir after download
        if team_id and str(team_id).isdigit():
            import glob as _glob
            matches = _glob.glob(os.path.join(logodir, '*', f'{team_id}.png'))
            if matches:
                subdir_id_path = matches[0]

    # Prefer team_id path over abbr — avoids collisions where a MiLB team shares an
    # abbreviation with an MLB team (e.g. COL = Rockies AND Clippers). The MiLB subdir
    # match comes last: it's keyed by sport_id (defaulting to 0 when unknown, since
    # _try_download_logo is never called with an explicit sport_id), so a flat file
    # here is always a deliberate, known-good logo — it must win over a generic
    # subdir cache entry even when both exist for the same team_id.
    result = None
    for path in (id_path, abbr_path, subdir_id_path):
        if path and os.path.exists(path):
            try:
                img = Image.open(path).convert('RGBA')
                _alpha_bbox = img.split()[3].getbbox()
                if _alpha_bbox:
                    img = img.crop(_alpha_bbox)

                # Use committed config if available, else fall back to brightness detection
                if abbr in invert_config:
                    should_invert = invert_config[abbr]
                else:
                    from PIL import ImageStat
                    alpha_mask = img.split()[3].point(lambda p: 255 if p > 32 else 0)
                    avg_brightness = ImageStat.Stat(img.convert('L'), mask=alpha_mask).mean[0]
                    should_invert = avg_brightness > 180

                if should_invert:
                    r, g, b, a = img.split()
                    r = r.point(lambda p: 255 - p)
                    g = g.point(lambda p: 255 - p)
                    b = b.point(lambda p: 255 - p)
                    img = Image.merge('RGBA', (r, g, b, a))

                # For logos with white outlines/text on colored backgrounds,
                # turn near-white visible pixels black so they show on e-ink
                if abbr in invert_config.get('darken_white', []):
                    r, g, b, a = img.split()
                    pixels_r = list(r.getdata())
                    pixels_g = list(g.getdata())
                    pixels_b = list(b.getdata())
                    pixels_a = list(a.getdata())
                    new_r, new_g, new_b = [], [], []
                    for rv, gv, bv, av in zip(pixels_r, pixels_g, pixels_b, pixels_a):
                        if av > 32 and rv > 200 and gv > 200 and bv > 200:
                            new_r.append(0); new_g.append(0); new_b.append(0)
                        else:
                            new_r.append(rv); new_g.append(gv); new_b.append(bv)
                    r.putdata(new_r); g.putdata(new_g); b.putdata(new_b)
                    img = Image.merge('RGBA', (r, g, b, a))

                bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                result = bg.convert('L')
                break
            except Exception:
                pass

    _logo_cache[cache_key] = result
    return result


def _paste_logo(image, logo, pos):
    """Paste a 1-bit logo without its white background (only dark pixels are drawn)."""
    image.paste(logo, pos, mask=ImageOps.invert(logo.convert('L')))


def _ensure_visible_1bit(gray):
    """Convert an L-mode image to '1', guaranteeing at least some black pixels survive.

    A logo that's very light overall (e.g. a pale color that a team's config doesn't
    flag for inversion) can dither down to an all-white '1'-mode image — invisible on
    the white e-ink background, since only dark pixels get pasted. When that happens,
    fall back to an adaptive threshold keyed off the image's own darkest pixels so its
    outline stays visible instead of silently vanishing. Returns None only when the
    source has no variance at all (a single flat color — nothing to show either way).
    """
    result = gray.convert('1')
    if result.getextrema() != (255, 255):
        return result
    lo, hi = gray.getextrema()
    if lo >= hi:
        return None
    threshold = lo + max(1, (hi - lo) // 4)  # darkest quartile becomes visible
    return gray.point(lambda p: 0 if p <= threshold else 255).convert('1')


def _logo_small(abbr, team_id, size=28):
    """Small 1-bit logo for the team name row. Returns a '1'-mode image or None."""
    gray = _load_logo_gray(abbr, team_id)
    if gray is None:
        return None
    gray = gray.copy()
    gray.thumbnail((size, size), Image.LANCZOS)
    # Normalize histogram so inherently dark logos (like BAL/MIL) get lifted
    # to a visible range before dithering, preserving internal detail.
    gray = ImageOps.autocontrast(gray, cutoff=2)
    gray = ImageEnhance.Contrast(gray).enhance(3.0)
    return _ensure_visible_1bit(gray)


def _logo_ghost(abbr, team_id, size=110, lightness=140):
    """Large, ghost logo for the winner watermark on finished games.

    lightness controls how bright (faint) the watermark is.  140 = normal (~45%
    black dots); higher values produce fewer dots (e.g. 215 ≈ 15% for fullscreen use
    where the logo is rendered at native resolution instead of being upscaled).
    Returns a '1'-mode image or None.
    """
    gray = _load_logo_gray(abbr, team_id)
    if gray is None:
        return None
    gray = gray.copy()
    gray.thumbnail((size, size), Image.LANCZOS)
    gray = gray.point(lambda p: 255 if p > 180 else min(255, int(p * 0.3 + lightness)))
    return _ensure_visible_1bit(gray)


_emoji_cache: dict = {}       # abbr -> grayscale PIL Image or None
_team_emojis = None     # loaded once from config.yaml
_char_emoji_cache: dict = {}

# Rain/weather emojis cycled on postponed cards (Twemoji codepoints)
_PPD_EMOJI_CODEPOINTS = ['1f327', '2602', '1f302', '1f4a7']  # 🌧 ☂ 🌂 💧
# Lightning/storm emojis for suspended games
_SUSP_EMOJI_CODEPOINTS = ['26a1', '1f329', '1f4a8', '1f300']  # ⚡ 🌩 💨 🌀


def _get_team_emojis():
    """Load team_emojis mapping from config.yaml, cached per process."""
    global _team_emojis
    if _team_emojis is None:
        from util import load_yaml_file
        _team_emojis = load_yaml_file('config.yaml').get('team_emojis', {}) or {}
    return _team_emojis


def _emoji_codepoint(char):
    """Convert an emoji character to its Twemoji hex filename (e.g. 💩 -> 1f4a9).

    Strips variation selectors (U+FE0F) so compound emojis resolve correctly.
    """
    codepoints = [f'{ord(c):x}' for c in char if ord(c) != 0xfe0f]
    return '-'.join(codepoints)


def _try_download_emoji(emoji_char):
    """Download an emoji PNG from the Twemoji CDN (via jsDelivr). Returns True on success."""
    try:
        import urllib.request
        codepoint = _emoji_codepoint(emoji_char)
        os.makedirs(emojidir, exist_ok=True)
        path = os.path.join(emojidir, f'{codepoint}.png')
        url = f'https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/{codepoint}.png'
        with urllib.request.urlopen(url, timeout=5) as response:
            with open(path, 'wb') as f:
                f.write(response.read())
        print(f'Auto-downloaded emoji: {emoji_char} ({codepoint})')
        return True
    except Exception as e:
        print(f'Could not auto-download emoji {emoji_char}: {e}')
        return False


def _load_emoji_gray(abbr):
    """If abbr has an emoji mapping, load its PNG and return a grayscale Image, else None."""
    if abbr in _emoji_cache:
        return _emoji_cache[abbr]

    emojis = _get_team_emojis()
    emoji_char = emojis.get(abbr)
    if not emoji_char:
        _emoji_cache[abbr] = None
        return None

    codepoint = _emoji_codepoint(emoji_char)
    path = os.path.join(emojidir, f'{codepoint}.png')
    if not os.path.exists(path):
        _try_download_emoji(emoji_char)

    result = None
    if os.path.exists(path):
        try:
            from PIL import ImageStat, ImageFilter
            img = Image.open(path).convert('RGBA')
            # Detect predominantly white/bright emojis and invert so they
            # don't vanish against the white e-ink background.
            alpha_mask = img.split()[3].point(lambda p: 255 if p > 32 else 0)
            avg_brightness = ImageStat.Stat(img.convert('L'), mask=alpha_mask).mean[0]
            if avg_brightness > 180:
                r, g, b, a = img.split()
                r = r.point(lambda p: 255 - p)
                g = g.point(lambda p: 255 - p)
                b = b.point(lambda p: 255 - p)
                img = Image.merge('RGBA', (r, g, b, a))
            bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            result = bg.convert('L')
            # Sharpen edges (eyes, mouth) so they survive aggressive
            # thumbnail + contrast dithering in _logo_small / _logo_ghost.
            result = ImageOps.autocontrast(result, cutoff=1)
            result = result.filter(ImageFilter.UnsharpMask(radius=2, percent=250, threshold=0))
        except Exception:
            pass

    _emoji_cache[abbr] = result
    return result


def _load_char_emoji(emoji_char, size=12):
    """Load a single emoji character as a grayscale PIL Image resized to size×size, or None."""
    cache_key = (emoji_char, size)
    if cache_key in _char_emoji_cache:
        return _char_emoji_cache[cache_key]

    codepoint = _emoji_codepoint(emoji_char)
    path = os.path.join(emojidir, f'{codepoint}.png')
    if not os.path.exists(path):
        _try_download_emoji(emoji_char)

    result = None
    if os.path.exists(path):
        try:
            from PIL import ImageStat
            img = Image.open(path).convert('RGBA')
            alpha_mask = img.split()[3].point(lambda p: 255 if p > 32 else 0)
            avg_brightness = ImageStat.Stat(img.convert('L'), mask=alpha_mask).mean[0]
            if avg_brightness > 180:
                r, g, b, a = img.split()
                r = r.point(lambda p: 255 - p)
                g = g.point(lambda p: 255 - p)
                b = b.point(lambda p: 255 - p)
                img = Image.merge('RGBA', (r, g, b, a))
            bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            gray = bg.convert('L')
            result = gray.resize((size, size), Image.LANCZOS)
        except Exception:
            pass

    _char_emoji_cache[cache_key] = result
    return result


def _load_codepoint_ghost(codepoint, size=90):
    """Load an emoji PNG by raw Twemoji codepoint and return it as a ghost watermark."""
    path = os.path.join(emojidir, f'{codepoint}.png')
    if not os.path.exists(path):
        try:
            import urllib.request
            url = f'https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/{codepoint}.png'
            os.makedirs(emojidir, exist_ok=True)
            with urllib.request.urlopen(url, timeout=5) as response:
                with open(path, 'wb') as f:
                    f.write(response.read())
            print(f'Auto-downloaded weather emoji: {codepoint}')
        except Exception as e:
            print(f'Could not download weather emoji {codepoint}: {e}')
    if not os.path.exists(path):
        return None
    try:
        img = Image.open(path).convert('RGBA')
        bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        gray = bg.convert('L')
        gray = ImageOps.autocontrast(gray, cutoff=1)
        gray.thumbnail((size, size), Image.LANCZOS)
        gray = gray.point(lambda p: 255 if p > 210 else min(255, int(p * 0.45 + 70)))
        return gray.convert('1')
    except Exception:
        return None
