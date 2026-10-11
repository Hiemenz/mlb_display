"""Draw a playoff series tile (135x130) for an empty grid slot.

Game slots (G1…Gmax) show either a completed result or the scheduled
away-logo home-logo time for upcoming games.  The decisive last game when a
series goes to its maximum is centred; all others pair left|right per row.
"""
from datetime import datetime

from PIL import Image

import panel_cell
from image_assets import ImageDraw, _get_font, _logo_small, _logo_ghost
from util import load_json_file

_WIN_GOAL    = {'WC': 2, 'DS': 3, 'CS': 4, 'WS': 4}
_ROUND_LABEL = {
    'WC': '{l} Wild Card',
    'DS': '{l} Div Series',
    'CS': '{l} Champ Series',
    'WS': 'World Series',
}
_DOT_R        = 4
_DOT_GAP      = 3
_LOGO_SZ      = 28
_SCORE_LOGO   = 14   # logo height inside a game-result / upcoming row
_GAME_ROW_H   = 15   # vertical step between game rows (4 rows fit in cell)
_GAME_FONT_SZ = 11   # font size for scores and upcoming time


def _dot_row(draw, cx, cy, filled, total, fg, bg):
    span = total * (_DOT_R * 2 + _DOT_GAP) - _DOT_GAP
    ox = cx - span // 2
    for i in range(total):
        x = ox + i * (_DOT_R * 2 + _DOT_GAP)
        draw.ellipse([x, cy - _DOT_R, x + _DOT_R * 2, cy + _DOT_R],
                     fill=fg if i < filled else bg, outline=fg)


def _paste_logo_transparent(Himage, logo, px, py):
    """Paste only the dark pixels so the ghost watermark shows through."""
    mask = logo.convert('L').point(lambda p: 255 - p)
    Himage.paste(Image.new('1', logo.size, 0), (px, py), mask)


def _paste_small_logo(Himage, abbr, team_id, cx, cy, size):
    logo = _logo_small(abbr, team_id, size=size)
    if logo is None:
        return
    _paste_logo_transparent(Himage, logo,
                             cx - logo.width // 2, cy - logo.height // 2)


def _bold_text(draw, x, y, text, font, fill):
    """Simulate bold by double-printing with a 1px horizontal offset."""
    draw.text((x,     y), text, font=font, fill=fill)
    draw.text((x + 1, y), text, font=font, fill=fill)


def _scheduled_games(away_id, home_id):
    """Return upcoming scheduled games for this series, sorted by date.

    Each entry: {time, away_id, home_id, away_abbr, home_abbr}.
    """
    try:
        games = load_json_file('games.json').get('games', [])
    except Exception:
        return []
    # games.json carries team ids and full names but no abbreviation; without the
    # lookup the row falls back to the numeric id and no logo can be found.
    abbr_map = (load_json_file('teams.json') or {}).get('team_abbreviation', {})
    out = []
    for g in games:
        if g.get('detailed_state') not in ('Scheduled', 'Pre-Game', 'Warmup'):
            continue
        a_id = str(g.get('away_team_id', ''))
        h_id = str(g.get('home_team_id', ''))
        if {a_id, h_id} != {str(away_id), str(home_id)}:
            continue
        raw = g.get('game_date', '')
        try:
            dt    = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            local = dt.astimezone()
            time_str = local.strftime('%a') + ' ' + local.strftime('%-I%p').lower()  # e.g. "Sun 8pm"
        except Exception:
            time_str = ''
        out.append({
            'time':       time_str,
            'away_id':    a_id,
            'home_id':    h_id,
            'away_abbr':  abbr_map.get(a_id) or g.get('away_team') or a_id,
            'home_abbr':  abbr_map.get(h_id) or g.get('home_team') or h_id,
            'sort_key':   raw,
        })
    out.sort(key=lambda x: x['sort_key'])
    return out


def _draw_result_row(draw, Himage, cx, gy, game_num, gr,
                     away_abbr, away_id, home_abbr, home_id,
                     use_logos, fg):
    """Draw a completed game result centred at (cx, gy)."""
    font     = _get_font(_GAME_FONT_SZ)
    label    = f'GM {game_num}'
    label_w  = int(font.getlength(label))

    a_sc = gr.get('away_score')
    h_sc = gr.get('home_score')
    if a_sc is None or h_sc is None:
        dash_w = int(font.getlength('—'))
        gx = cx - (label_w + 2 + dash_w) // 2
        _bold_text(draw, gx, gy, label, font, fg)
        draw.text((gx + label_w + 2, gy), '—', font=font, fill=fg)
        return

    a_sc, h_sc = int(a_sc), int(h_sc)
    score      = f'{max(a_sc, h_sc)}-{min(a_sc, h_sc)}'
    score_w    = int(font.getlength(score))

    # Winner logo after the score.
    winner_id  = str(gr.get('winner_id', ''))
    if use_logos and winner_id:
        win_abbr = away_abbr if str(away_id) == winner_id else home_abbr
        win_tid  = away_id   if str(away_id) == winner_id else home_id
        win_logo = _logo_small(win_abbr, win_tid, size=_SCORE_LOGO)
    else:
        win_logo = None

    logo_gap = 3
    logo_w   = (win_logo.width + logo_gap) if win_logo else 0
    total    = label_w + 4 + score_w + logo_w
    gx       = cx - total // 2
    _bold_text(draw, gx, gy, label, font, fg)
    _bold_text(draw, gx + label_w + 4, gy, score, font, fg)
    if win_logo:
        lx = gx + label_w + 4 + score_w + logo_gap
        _paste_logo_transparent(Himage, win_logo,
                                lx, gy + (_SCORE_LOGO - win_logo.height) // 2 + 1)


def _draw_upcoming_row(draw, Himage, cx, gy, sched, use_logos, fg):
    """Draw an upcoming game slot: away-logo home-logo time, centred at cx."""
    font      = _get_font(_GAME_FONT_SZ)
    a_abbr    = sched.get('away_abbr', '?')
    h_abbr    = sched.get('home_abbr', '?')
    a_id      = sched.get('away_id', '')
    h_id      = sched.get('home_id', '')
    time_str  = sched.get('time', '')

    at_str = '@'
    at_w   = int(font.getlength(at_str)) + 2
    a_logo = _logo_small(a_abbr, a_id, size=_SCORE_LOGO) if use_logos else None
    h_logo = _logo_small(h_abbr, h_id, size=_SCORE_LOGO) if use_logos else None
    a_w    = (a_logo.width + 2) if a_logo else (int(font.getlength(a_abbr)) + 2)
    h_w    = (h_logo.width + 5) if h_logo else (int(font.getlength(h_abbr)) + 5)
    t_w    = int(font.getlength(time_str))
    total  = a_w + at_w + h_w + t_w

    lx = cx - total // 2

    if a_logo:
        _paste_logo_transparent(Himage, a_logo, lx, gy + (_SCORE_LOGO - a_logo.height) // 2 + 1)
        lx += a_logo.width + 2
    else:
        draw.text((lx, gy), a_abbr, font=font, fill=fg)
        lx += int(font.getlength(a_abbr)) + 2

    draw.text((lx, gy), at_str, font=font, fill=fg)
    lx += at_w

    if h_logo:
        _paste_logo_transparent(Himage, h_logo, lx, gy + (_SCORE_LOGO - h_logo.height) // 2 + 1)
        lx += h_logo.width + 5
    else:
        draw.text((lx, gy), h_abbr, font=font, fill=fg)
        lx += int(font.getlength(h_abbr)) + 5

    draw.text((lx, gy), time_str, font=font, fill=fg)


def draw_series_cell(Himage, sx, sy, series, use_logos=True):
    """Draw one playoff series into the 135x130 cell at (sx, sy).

    Each game slot (G1…Gmax) shows either a completed result or, if not yet
    played and scheduled, 'away-logo home-logo time'.  When a series goes to
    its maximum games the decisive last game is centred under the '@' sign;
    all other slots pair left|right on the same row.
    """
    draw   = ImageDraw.Draw(Himage)
    series = series or {}

    rnd    = series.get('round', 'WC')
    winner = series.get('winner_abbr')
    league = series.get('league', '')

    # Ghost watermark.
    if winner:
        winner_id = (series.get('away_id', '') if winner == series.get('away_abbr')
                     else series.get('home_id', ''))
        ghost = _logo_ghost(winner, winner_id,
                            size=panel_cell.CELL_H - panel_cell.HEADER_H - 4,
                            lightness=140)
        if ghost is not None:
            body_h = panel_cell.CELL_H - panel_cell.HEADER_H
            gx = sx + (panel_cell.CELL_W - ghost.width) // 2
            gy = sy + panel_cell.HEADER_H + (body_h - ghost.height) // 2
            Himage.paste(ghost, (gx, gy))

    fg = 0
    label_tmpl  = _ROUND_LABEL.get(rnd, rnd)
    header_text = label_tmpl.format(l=league).strip() if '{l}' in label_tmpl else label_tmpl
    panel_cell.draw_chrome(draw, sx, sy, header_text)

    away_abbr  = series.get('away_abbr', '???')
    home_abbr  = series.get('home_abbr', '???')
    away_id    = series.get('away_id',   '')
    home_id    = series.get('home_id',   '')
    away_wins  = series.get('away_wins', 0)
    home_wins  = series.get('home_wins', 0)
    total_wins = _WIN_GOAL.get(rnd, 2)

    font_sm  = _get_font(9)
    away_cx  = sx + panel_cell.CELL_W // 4
    home_cx  = sx + 3 * panel_cell.CELL_W // 4
    mid_x    = sx + panel_cell.CELL_W // 2
    body_top = sy + panel_cell.HEADER_H + 3

    logo_cy = body_top + _LOGO_SZ // 2 + 1
    if use_logos:
        _paste_small_logo(Himage, away_abbr, away_id, away_cx, logo_cy, _LOGO_SZ)
        _paste_small_logo(Himage, home_abbr, home_id, home_cx, logo_cy, _LOGO_SZ)

    vsw = int(font_sm.getlength('@'))
    draw.text((mid_x - vsw // 2, logo_cy - 4), '@', font=font_sm, fill=fg)

    dots_y = logo_cy + _LOGO_SZ // 2 + 6
    _dot_row(draw, away_cx, dots_y, away_wins, total_wins, fg, 255)
    _dot_row(draw, home_cx, dots_y, home_wins, total_wins, fg, 255)

    game_results  = series.get('game_results', [])
    games_start   = dots_y + _DOT_R + 6
    body_bottom   = sy + panel_cell.CELL_H - 2
    max_games     = total_wins * 2 - 1   # 3, 5, or 7
    n_played      = len(game_results)

    # Upcoming scheduled games — filled into slots after the played games.
    upcoming = [] if winner else _scheduled_games(away_id, home_id)

    kw_result = dict(away_abbr=away_abbr, away_id=away_id,
                     home_abbr=home_abbr, home_id=home_id,
                     use_logos=use_logos, fg=fg)

    def _slot(slot_num):
        """Return (kind, data) for a game slot number (1-indexed)."""
        if slot_num <= n_played:
            return ('result', game_results[slot_num - 1])
        idx = slot_num - n_played - 1
        if idx < len(upcoming):
            return ('upcoming', upcoming[idx])
        return ('empty', None)

    def _draw_slot(cx, gy, slot_num):
        kind, data = _slot(slot_num)
        if kind == 'result':
            _draw_result_row(draw, Himage, cx, gy, slot_num, data, **kw_result)
        elif kind == 'upcoming':
            _draw_upcoming_row(draw, Himage, cx, gy, data, use_logos, fg)

    row = 0
    slot = 1
    while slot <= max_games and games_start + row * _GAME_ROW_H + _GAME_ROW_H <= body_bottom:
        gy   = games_start + row * _GAME_ROW_H
        kind, _ = _slot(slot)

        if slot == max_games:
            # Decisive last game — always centred.
            _draw_slot(mid_x, gy, slot)
            row += 1
            slot += 1
        elif kind == 'upcoming':
            # Upcoming game: full-width row so "logo @ logo day Xpm" has room.
            _draw_slot(mid_x, gy, slot)
            row += 1
            slot += 1
        else:
            # Completed result: pair with the next slot if it's also a result;
            # otherwise draw it full-width so there's no orphaned left-aligned row.
            next_kind, _ = _slot(slot + 1) if slot + 1 <= max_games else ('empty', None)
            if next_kind == 'result':
                _draw_slot(away_cx, gy, slot)
                _draw_slot(home_cx, gy, slot + 1)
                slot += 2
            else:
                _draw_slot(mid_x, gy, slot)
                slot += 1
            row += 1

    return Himage
