"""Draw a playoff series tile (135x130) for an empty grid slot.

Shows the matchup (AWAY vs HOME) with team logos, win-dots, and game-by-game
scores. When the series is over a large ghost logo of the winning team fills
the tile body as a background watermark.  For series not yet started, the
next scheduled game time is shown from games.json.
"""
from datetime import datetime

import panel_cell
from image_assets import ImageDraw, _get_font, _logo_small, _logo_ghost
from util import load_json_file

_WIN_GOAL   = {'WC': 2, 'DS': 3, 'CS': 4, 'WS': 4}
_ROUND_LABEL = {'WC': 'Wild Card', 'DS': 'Div Series', 'CS': 'Champ Series', 'WS': 'World Series'}
_DOT_R      = 4
_DOT_GAP    = 3
_LOGO_SZ    = 28
_SCORE_LOGO = 9    # logo height inside a game-result row
_GAME_ROW_H = 10   # vertical step between game-result rows


def _dot_row(draw, cx, cy, filled, total, fg, bg):
    span = total * (_DOT_R * 2 + _DOT_GAP) - _DOT_GAP
    ox = cx - span // 2
    for i in range(total):
        x = ox + i * (_DOT_R * 2 + _DOT_GAP)
        draw.ellipse([x, cy - _DOT_R, x + _DOT_R * 2, cy + _DOT_R],
                     fill=fg if i < filled else bg, outline=fg)


def _paste_small_logo(Himage, abbr, team_id, cx, cy, size):
    logo = _logo_small(abbr, team_id, size=size)
    if logo is None:
        return
    Himage.paste(logo, (cx - logo.width // 2, cy - logo.height // 2))


def _next_game_time(away_id, home_id):
    """Return 'Day H:MMam/pm' for the next scheduled game, or None."""
    try:
        games = load_json_file('games.json').get('games', [])
    except Exception:
        return None
    for g in games:
        if g.get('detailed_state') not in ('Scheduled', 'Pre-Game', 'Warmup'):
            continue
        a_id = str(g.get('away_team_id', ''))
        h_id = str(g.get('home_team_id', ''))
        if {a_id, h_id} != {str(away_id), str(home_id)}:
            continue
        raw = g.get('game_date', '')
        if not raw:
            continue
        try:
            dt    = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            local = dt.astimezone()
            day   = local.strftime('%a')
            time  = local.strftime('%-I:%M%p').lower().rstrip('m') + 'm'
            return f'{day} {time}'
        except Exception:
            return None
    return None


def _draw_result_row(draw, Himage, gx, gy, game_num, gr,
                     away_abbr, away_id, home_abbr, home_id,
                     use_logos, font_sm, fg):
    """Draw one game-result row starting at (gx, gy)."""
    label = f'G{game_num}'
    draw.text((gx, gy), label, font=font_sm, fill=fg)
    lx = gx + int(font_sm.getlength(label)) + 2

    a_sc = gr.get('away_score')
    h_sc = gr.get('home_score')
    if a_sc is None or h_sc is None:
        draw.text((lx, gy), '—', font=font_sm, fill=fg)
        return

    a_sc, h_sc = int(a_sc), int(h_sc)
    win_id   = gr.get('winner_id', '')
    win_abbr = away_abbr if win_id == away_id else home_abbr
    win_tid  = away_id   if win_id == away_id else home_id
    score    = f'{max(a_sc, h_sc)}-{min(a_sc, h_sc)}'

    if use_logos:
        logo = _logo_small(win_abbr, win_tid, size=_SCORE_LOGO)
        if logo:
            Himage.paste(logo, (lx, gy + (_SCORE_LOGO - logo.height) // 2 + 1))
            lx += logo.width + 2
        else:
            draw.text((lx, gy), win_abbr, font=font_sm, fill=fg)
            lx += int(font_sm.getlength(win_abbr)) + 2
    else:
        draw.text((lx, gy), win_abbr, font=font_sm, fill=fg)
        lx += int(font_sm.getlength(win_abbr)) + 2

    draw.text((lx, gy), score, font=font_sm, fill=fg)


def draw_series_cell(Himage, sx, sy, series, use_logos=True):
    """Draw one playoff series into the 135x130 cell at (sx, sy).

    ≤5 games: single-column list.
    6-7 games: two columns (G1-G3 left, G4-G6 right) with G7 centred below.
    """
    draw = ImageDraw.Draw(Himage)
    series = series or {}

    rnd    = series.get('round', 'WC')
    winner = series.get('winner_abbr')

    # Ghost watermark behind everything.
    if winner:
        winner_id = (series.get('away_id', '') if winner == series.get('away_abbr')
                     else series.get('home_id', ''))
        ghost = _logo_ghost(winner, winner_id,
                            size=panel_cell.CELL_H - panel_cell.HEADER_H - 4,
                            lightness=200)
        if ghost is not None:
            body_h = panel_cell.CELL_H - panel_cell.HEADER_H
            gx = sx + (panel_cell.CELL_W - ghost.width) // 2
            gy = sy + panel_cell.HEADER_H + (body_h - ghost.height) // 2
            Himage.paste(ghost, (gx, gy))

    fg = 0
    panel_cell.draw_chrome(draw, sx, sy, _ROUND_LABEL.get(rnd, rnd))

    away_abbr = series.get('away_abbr', '???')
    home_abbr = series.get('home_abbr', '???')
    away_id   = series.get('away_id',   '')
    home_id   = series.get('home_id',   '')
    away_wins = series.get('away_wins', 0)
    home_wins = series.get('home_wins', 0)
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

    game_results = series.get('game_results', [])
    games_start  = dots_y + _DOT_R + 6

    # No games yet — show next scheduled game time.
    if not game_results and not winner:
        next_time = _next_game_time(away_id, home_id)
        if next_time:
            tw = int(font_sm.getlength(next_time))
            draw.text((sx + (panel_cell.CELL_W - tw) // 2, games_start), next_time,
                      font=font_sm, fill=fg)
        return Himage

    kw = dict(away_abbr=away_abbr, away_id=away_id,
              home_abbr=home_abbr, home_id=home_id,
              use_logos=use_logos, font_sm=font_sm, fg=fg)
    n = len(game_results)

    if n <= 5:
        # Single column — show up to what fits.
        body_bottom = sy + panel_cell.CELL_H - 2
        available_h = body_bottom - games_start
        n_fit = min(n, total_wins * 2, available_h // _GAME_ROW_H)
        for i, gr in enumerate(game_results[-n_fit:]):
            game_num = n - n_fit + i + 1
            _draw_result_row(draw, Himage, sx + panel_cell.PAD + 2,
                             games_start + i * _GAME_ROW_H,
                             game_num, gr, **kw)
    else:
        # Two-column layout: G1-G3 left, G4-G6 right, G7 centred below.
        left_x  = sx + panel_cell.PAD + 2
        right_x = sx + panel_cell.CELL_W // 2 + 1

        for i in range(min(3, n)):
            _draw_result_row(draw, Himage, left_x,
                             games_start + i * _GAME_ROW_H,
                             i + 1, game_results[i], **kw)

        for i in range(min(3, n - 3)):
            _draw_result_row(draw, Himage, right_x,
                             games_start + i * _GAME_ROW_H,
                             i + 4, game_results[i + 3], **kw)

        if n >= 7:
            g7_y = games_start + 3 * _GAME_ROW_H
            # Centre G7 by placing it at the left-of-centre column.
            g7_x  = sx + (panel_cell.CELL_W - 60) // 2
            _draw_result_row(draw, Himage, g7_x, g7_y, 7, game_results[6], **kw)

    return Himage
