"""Full-panel (800x480) card for one free-agent signing.

    ┌──────────────────────────────────────────────┐
    │ FREE AGENT SIGNING              Nov 18  2 / 9 │
    ├───────────┬──────────────────────────────────┤
    │ headshot  │  GLEYBER TORRES                  │
    │           │  2B                              │
    │           │  [old logo]  ──▶  [new logo]     │
    │           │  Guardians        Tigers         │
    ├───────────┴──────────────────────────────────┤
    │                 5 yr / $120M                  │
    └──────────────────────────────────────────────┘

When no contract terms are known the box reads just "SIGNED".
"""
import os
from datetime import datetime

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from image_assets import _get_font, _load_logo_gray, _logo_small, _try_download_logo
from image_idle import _invert_if_dark

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HEADSHOT_DIR = os.path.join(_REPO_ROOT, 'pic', 'headshots')
_HEADSHOT_URL = ('https://img.mlbstatic.com/mlb-photos/image/upload/'
                 'd_people:generic:headshot:67:current.png/w_426,q_auto:best/'
                 'v1/people/{pid}/headshot/67/current')

_W, _H = 800, 480
_HDR_H = 40
_PHOTO_H = 320
_PHOTO_W = 213            # headshots are 426x640 (2:3); show the whole thing, chin included
_LOGO = 130


def _load_headshot(player_id, width=_PHOTO_W, height=_PHOTO_H):
    """1-bit headshot at width×height (2:3 portrait, uncropped), cached under pic/headshots/. None on failure."""
    path = os.path.join(_HEADSHOT_DIR, f'{player_id}.png')
    if not os.path.exists(path):
        try:
            resp = requests.get(_HEADSHOT_URL.format(pid=player_id), timeout=10)
            if resp.status_code != 200:
                return None
            os.makedirs(_HEADSHOT_DIR, exist_ok=True)
            with open(path, 'wb') as f:
                f.write(resp.content)
        except Exception as e:
            print(f'Warning: headshot download failed for {player_id}: {e}')
            return None
    try:
        gray = Image.open(path).convert('L')
    except Exception:
        return None
    gray = ImageOps.fit(gray, (width, height), Image.LANCZOS, centering=(0.5, 0.0))
    gray = ImageOps.autocontrast(gray, cutoff=1).filter(ImageFilter.SHARPEN)
    return gray.convert('1')


def _team_logo(abbr, team_id, size=_LOGO):
    """1-bit team logo, downloading it if missing. None when unavailable."""
    if not abbr:
        return None
    if _load_logo_gray(abbr, team_id) is None:
        _try_download_logo(abbr, team_id)
    logo = _logo_small(abbr, team_id, size)
    if logo is None:
        return None
    if logo.size[0] < size and logo.size[1] < size:
        gray = logo.convert('L')
        gray = gray.resize((size, round(size * gray.size[1] / gray.size[0]))
                           if gray.size[0] >= gray.size[1]
                           else (round(size * gray.size[0] / gray.size[1]), size),
                           Image.LANCZOS)
        logo = gray.convert('1')
    return logo


def _fit_font(text, max_w, start, minimum=18):
    """Largest font ≤ start whose rendering of `text` fits max_w."""
    size = start
    while size > minimum:
        font = _get_font(size)
        if font.getlength(text) <= max_w:
            return font
        size -= 2
    return _get_font(minimum)


def _centered(draw, cx, y, text, font, fill=0):
    draw.text((cx - int(font.getlength(text)) // 2, y), text, font=font, fill=fill)


def _date_label(date_str):
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%b %-d').upper()
    except (ValueError, TypeError):
        return ''


def _abbr(team_data, team_id):
    return ((team_data or {}).get('team_abbreviation') or {}).get(str(team_id), '')


def draw_free_agent_screen(signing, team_data, config, page=None, total=None):
    """Render one signing card.

    signing  : dict from fetch_free_agents (player_id, player_name, position,
               date, from_team_id/name, to_team_id/name, terms)
    team_data: {'team_abbreviation': {id: abbr}}
    page/total: shown as "n / N" in the header when total > 1
    """
    bg, fg = 255, 0
    img = Image.new('1', (_W, _H), bg)
    draw = ImageDraw.Draw(img)

    # Header bar (inverted)
    draw.rectangle([0, 0, _W, _HDR_H], fill=fg)
    hdr = _get_font(22)
    draw.text((14, 8), 'FREE AGENT SIGNING', font=hdr, fill=bg)
    right = _date_label(signing.get('date'))
    if total and total > 1 and page:
        right = f'{right}   {page} / {total}'.strip()
    if right:
        draw.text((_W - 14 - int(hdr.getlength(right)), 8), right, font=hdr, fill=bg)

    # Headshot (or an initials placeholder)
    px, py = 24, _HDR_H + 24
    photo = _load_headshot(signing.get('player_id'))
    if photo is not None:
        img.paste(photo, (px, py))
    else:
        initials = ''.join(w[0] for w in signing.get('player_name', '?').split()[:2])
        draw.rectangle([px, py, px + _PHOTO_W - 1, py + _PHOTO_H - 1], outline=fg)
        _centered(draw, px + _PHOTO_W // 2, py + _PHOTO_H // 2 - 30, initials, _get_font(64))
    draw.rectangle([px - 3, py - 3, px + _PHOTO_W + 2, py + _PHOTO_H + 2], outline=fg, width=3)

    # Right column
    col_x, col_w = px + _PHOTO_W + 40, _W - (px + _PHOTO_W + 40) - 24
    cx_mid = col_x + col_w // 2
    name = signing.get('player_name', '').upper()
    draw.text((col_x, _HDR_H + 18), name, font=_fit_font(name, col_w, 46), fill=fg)
    if signing.get('position'):
        draw.text((col_x, _HDR_H + 74), signing['position'], font=_get_font(24), fill=fg)

    # old → new
    ly = _HDR_H + 108
    old_id, new_id = signing.get('from_team_id'), signing.get('to_team_id')
    slots = [(col_x + _LOGO // 2 + 4, old_id, signing.get('from_team_name')),
             (col_x + col_w - _LOGO // 2 - 4, new_id, signing.get('to_team_name'))]
    for cx, tid, tname in slots:
        logo = _team_logo(_abbr(team_data, tid), tid)
        if logo is not None:
            img.paste(logo, (cx - logo.size[0] // 2, ly + (_LOGO - logo.size[1]) // 2))
        label = (tname or '').split()[-1] if tname else ''
        _centered(draw, cx, ly + _LOGO + 6, label, _fit_font(label, 170, 22, 12))
    ay = ly + _LOGO // 2
    ax0, ax1 = col_x + _LOGO + 24, col_x + col_w - _LOGO - 24
    if signing.get('from_team_id') and signing.get('from_team_id') == signing.get('to_team_id'):
        _centered(draw, cx_mid, ay - 12, 'RE-SIGNED', _get_font(22))
    else:
        draw.line([ax0, ay, ax1 - 4, ay], fill=fg, width=5)
        draw.polygon([(ax1, ay), (ax1 - 20, ay - 14), (ax1 - 20, ay + 14)], fill=fg)

    # Terms box
    terms = signing.get('terms') or 'SIGNED'
    by0, by1 = py + _PHOTO_H + 14, _H - 22
    draw.rectangle([px - 3, by0, _W - 24, by1], outline=fg, width=4)
    font = _fit_font(terms, _W - 2 * px - 24, 50, 20)
    _centered(draw, _W // 2, by0 + (by1 - by0 - font.size) // 2 - 4, terms, font)

    dark = config.get('dark_mode', False)
    out = _invert_if_dark(img, dark)
    if dark and photo is not None:
        out.paste(photo, (px, py))   # keep the portrait a positive, not a negative
    return out


# ---------------------------------------------------------------------------
# 10-up grid (5 x 2) — one page of signings per screen
# ---------------------------------------------------------------------------

GRID_COLS, GRID_ROWS = 5, 2
GRID_PER_PAGE = GRID_COLS * GRID_ROWS
_CELL_W = _W // GRID_COLS
_CELL_H = (_H - _HDR_H) // GRID_ROWS
_G_PHOTO_W, _G_PHOTO_H = 100, 150
_G_LOGO = 40


def _draw_grid_cell(img, draw, x, y, signing, team_data):
    """One compact signing card inside the cell whose top-left is (x, y)."""
    fg = 0
    draw.rectangle([x + 1, y + 1, x + _CELL_W - 2, y + _CELL_H - 2], outline=fg)
    px, py = x + 5, y + 5
    photo = _load_headshot(signing.get('player_id'), _G_PHOTO_W, _G_PHOTO_H)
    if photo is not None:
        img.paste(photo, (px, py))
    else:
        initials = ''.join(w[0] for w in signing.get('player_name', '?').split()[:2])
        _centered(draw, px + _G_PHOTO_W // 2, py + _G_PHOTO_H // 2 - 18, initials, _get_font(36))
    draw.rectangle([px - 1, py - 1, px + _G_PHOTO_W, py + _G_PHOTO_H], outline=fg)

    # old logo ↓ new logo, stacked beside the portrait
    cx = px + _G_PHOTO_W + 5 + (x + _CELL_W - 5 - (px + _G_PHOTO_W + 5)) // 2
    old_id, new_id = signing.get('from_team_id'), signing.get('to_team_id')
    for ty, tid in ((py + 2, old_id), (py + _G_PHOTO_H - _G_LOGO - 2, new_id)):
        logo = _team_logo(_abbr(team_data, tid), tid, _G_LOGO)
        if logo is not None:
            img.paste(logo, (cx - logo.size[0] // 2, ty + (_G_LOGO - logo.size[1]) // 2))
    ay = py + _G_PHOTO_H // 2
    if old_id and old_id == new_id:
        _centered(draw, cx, ay - 7, 'RE-UP', _get_font(11))
    else:
        draw.line([cx, ay - 14, cx, ay + 8], fill=fg, width=3)
        draw.polygon([(cx, ay + 14), (cx - 8, ay + 4), (cx + 8, ay + 4)], fill=fg)

    mid = x + _CELL_W // 2
    name = signing.get('player_name', '')
    _centered(draw, mid, py + _G_PHOTO_H + 5, name, _fit_font(name, _CELL_W - 12, 17, 11))
    terms = signing.get('terms') or 'SIGNED'
    _centered(draw, mid, py + _G_PHOTO_H + 28, terms, _fit_font(terms, _CELL_W - 12, 18, 11))
    old_a, new_a = _abbr(team_data, old_id), _abbr(team_data, new_id)
    if old_a and new_a and old_a != new_a:
        sub = f'{old_a} > {new_a}'
    else:
        sub = signing.get('position', '')
    _centered(draw, mid, py + _G_PHOTO_H + 50, sub, _get_font(12))


def draw_free_agent_grid(signings, team_data, config, page=1, pages=1):
    """Render up to 10 signings (5 x 2) on one 800x480 screen."""
    bg, fg = 255, 0
    img = Image.new('1', (_W, _H), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, _W, _HDR_H], fill=fg)
    hdr = _get_font(22)
    draw.text((14, 8), 'FREE AGENT SIGNINGS', font=hdr, fill=bg)
    right = f'{page} / {pages}' if pages > 1 else ''
    if right:
        draw.text((_W - 14 - int(hdr.getlength(right)), 8), right, font=hdr, fill=bg)

    shown = list(signings)[:GRID_PER_PAGE]
    photos_at = []
    for i, sg in enumerate(shown):
        x, y = (i % GRID_COLS) * _CELL_W, _HDR_H + (i // GRID_COLS) * _CELL_H
        _draw_grid_cell(img, draw, x, y, sg, team_data)
        photos_at.append((x + 5, y + 5, sg))

    dark = config.get('dark_mode', False)
    out = _invert_if_dark(img, dark)
    if dark:   # keep every portrait a positive
        for px, py, sg in photos_at:
            photo = _load_headshot(sg.get('player_id'), _G_PHOTO_W, _G_PHOTO_H)
            if photo is not None:
                out.paste(photo, (px, py))
    return out


# ---------------------------------------------------------------------------
# Idle-screen rotation
# ---------------------------------------------------------------------------

_REFRESH_SECONDS = 6 * 3600


def pick_signing(signings, now):
    """The signing for this 30-minute slot, stepping through the list in order.

    Keyed to the wall clock so every cron tick in the same slot draws the same
    card (the idle screen skips the panel push when the image is unchanged).
    """
    if not signings:
        return None, 0
    slot = now.timetuple().tm_yday * 48 + now.hour * 2 + now.minute // 30
    idx = slot % len(signings)
    return signings[idx], idx


def free_agent_idle_image(config, now, load=None, fetch=None, replay_running=None):
    """Card for the current slot, or None when it isn't the free agents' turn.

    Takes the even 15-minute blocks (0 and 2) so the other idle views keep the
    odd ones, never interrupts a running off-season replay, and quietly yields
    when there are no qualifying signings (they age out after the lookback).
    """
    import time as _time
    from util import load_json_file
    load = load or load_json_file
    if not config.get('idle_free_agent_rotation', True):
        return None
    if (now.minute // 15) % 2:
        return None
    if replay_running is None:
        from offseason_replay import _replay_running
        replay_running = _replay_running
    if replay_running((load('offseason_replay.json') or {}).get('pid')):
        return None

    data = load('free_agents.json') or {}
    if _time.time() - data.get('fetched_at', 0) > _REFRESH_SECONDS:
        try:
            if fetch is None:
                from fetch_free_agents import fetch_free_agents as fetch
            data = fetch(lookback_days=config.get('free_agent_lookback_days', 21)) or data
        except Exception as e:
            print(f'Warning: free-agent refresh failed: {e}')
    signings = data.get('signings') or []
    if not signings:
        return None
    team_data = load('teams.json') or {}
    if config.get('free_agent_layout', 'grid') == 'grid':
        pages = -(-len(signings) // GRID_PER_PAGE)
        page = (now.timetuple().tm_yday * 48 + now.hour * 2 + now.minute // 30) % pages
        chunk = signings[page * GRID_PER_PAGE:(page + 1) * GRID_PER_PAGE]
        print(f'Idle: showing free-agent grid page {page + 1}/{pages}')
        return draw_free_agent_grid(chunk, team_data, config, page + 1, pages)
    signing, idx = pick_signing(signings, now)
    print(f'Idle: showing free-agent card {idx + 1}/{len(signings)} ({signing.get("player_name")})')
    return draw_free_agent_screen(signing, team_data, config, idx + 1, len(signings))
