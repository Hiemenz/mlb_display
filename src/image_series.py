"""Draw a playoff series tile (135x130) for an empty grid slot.

Completed games stack in the column under the team that won them (away left,
home right); scheduled games follow as full-width away-logo home-logo time rows.
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


def _scheduled_games(away_id, home_id, extra=None, bracket_show_time=True):
    """Return upcoming scheduled games for this series, sorted by date.

    Each entry: {time, away_id, home_id, away_abbr, home_abbr}.

    ``extra`` is an optional list of {game_start_utc, away_id, home_id,
    away_abbr, home_abbr} dicts from playoff_bracket.json.  When games.json
    has no upcoming game for this series (e.g. an off-day between CS/WS games)
    these are used as a fallback, filtered to future start times.

    ``bracket_show_time`` controls how bracket fallback times are formatted:
    True (CS) → always render the time string ("Mon 8pm"); False (WS) →
    always render just the date ("10/23") since WS times may be unconfirmed.
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

    if extra:
        # Merge bracket-level scheduled games as future slots.  On a game day
        # games.json supplies today's entry; bracket games fill the remaining
        # upcoming slots (10/12, 10/13, 10/14…).  On an off-day games.json has
        # nothing, so all bracket entries become the upcoming list.
        from datetime import timezone
        now = datetime.now(timezone.utc)
        covered = {g['sort_key'][:10] for g in out}   # 'YYYY-MM-DD' dates already from games.json
        for g in extra:
            a_id = str(g.get('away_id', ''))
            h_id = str(g.get('home_id', ''))
            if {a_id, h_id} != {str(away_id), str(home_id)}:
                continue
            raw = g.get('game_start_utc', '')
            if raw[:10] in covered:
                continue   # games.json already has this date
            try:
                dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
                if dt <= now:
                    continue
                local = dt.astimezone()
                if bracket_show_time:
                    time_str = local.strftime('%a') + ' ' + local.strftime('%-I%p').lower()
                else:
                    time_str = local.strftime('%-m/%-d')
            except Exception:
                time_str = ''
            out.append({
                'time':      time_str,
                'away_id':   a_id,
                'home_id':   h_id,
                'away_abbr': g.get('away_abbr') or abbr_map.get(a_id) or a_id,
                'home_abbr': g.get('home_abbr') or abbr_map.get(h_id) or h_id,
                'sort_key':  raw,
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

    # Gaps are tight: this row has to fit a ~67px half-column.
    logo_gap = 2
    logo_w   = (win_logo.width + logo_gap) if win_logo else 0
    total    = label_w + 3 + score_w + logo_w
    gx       = cx - total // 2
    _bold_text(draw, gx, gy, label, font, fg)
    _bold_text(draw, gx + label_w + 3, gy, score, font, fg)
    if win_logo:
        lx = gx + label_w + 3 + score_w + logo_gap
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


def _draw_season_series(draw, sx, sy, series):
    """Regular-season head-to-head in the strip below the tile, e.g. 'RS: TB 4-2'."""
    wins = series.get('season_series')
    if not wins:
        return
    a = wins.get(str(series.get('away_id')), 0)
    h = wins.get(str(series.get('home_id')), 0)
    if a == h:
        text = f'RS: tied {a}-{h}'
    else:
        lead, hi, lo = ((series.get('away_abbr'), a, h) if a > h
                        else (series.get('home_abbr'), h, a))
        text = f'RS: {lead} {hi}-{lo}'
    font = _get_font(14)
    x = sx + (panel_cell.CELL_W - int(font.getlength(text))) // 2
    _bold_text(draw, x, sy + panel_cell.CELL_H + 3, text, font, 0)


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
    # For CS/WS, also pass bracket-level scheduled games as a fallback so the
    # next game appears on off-days when games.json has nothing for this series.
    _bracket_sched = series.get('scheduled_games') if rnd in ('CS', 'WS') else None
    upcoming = [] if winner else _scheduled_games(
        away_id, home_id,
        extra=_bracket_sched,
        bracket_show_time=(rnd == 'CS'),   # CS times are confirmed; WS shows date-only
    )

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

    # Results stack in the column of the team that won each game; upcoming
    # games follow as full-width rows beneath the taller column.
    columns = {str(away_id): [], str(home_id): []}
    for n, gr in enumerate(game_results, 1):
        wid = str(gr.get('winner_id', ''))
        if wid not in columns:
            wid = str(away_id) if (gr.get('away_score') or 0) > (gr.get('home_score') or 0) else str(home_id)
        columns[wid].append((n, gr))

    def _row_y(row):
        return games_start + row * _GAME_ROW_H

    def fits(row):
        return _row_y(row) + _GAME_ROW_H <= body_bottom

    for tid, cx in ((str(away_id), away_cx), (str(home_id), home_cx)):
        for row, (n, gr) in enumerate(columns[tid]):
            if fits(row):
                _draw_result_row(draw, Himage, cx, _row_y(row), n, gr, **kw_result)

    row = max(len(columns[str(away_id)]), len(columns[str(home_id)]))
    for slot in range(n_played + 1, max_games + 1):
        if not fits(row):
            break
        kind, data = _slot(slot)
        if kind != 'upcoming':
            break
        _draw_upcoming_row(draw, Himage, mid_x, _row_y(row), data, use_logos, fg)
        row += 1

    _draw_season_series(draw, sx, sy, series)
    return Himage
