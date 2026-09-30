"""Draw a playoff series tile (135x130) for an empty grid slot.

Shows the matchup (AWAY vs HOME), win-dots for each team, and individual
game scores. When the series is complete the winning team's half of the
header is inverted — same treatment as a finished game tile.
"""
import panel_cell
from image_assets import ImageDraw, _get_font

_WIN_GOAL = {'WC': 2, 'DS': 3, 'CS': 4, 'WS': 4}
_ROUND_LABEL = {'WC': 'Wild Card', 'DS': 'Div Series', 'CS': 'Champ Series', 'WS': 'World Series'}
_DOT_R = 4   # dot radius
_DOT_GAP = 3


def _dot_row(draw, cx, cy, filled, total, fg):
    """Draw ``total`` dots centred at (cx, cy): first ``filled`` solid, rest hollow."""
    span = total * (_DOT_R * 2 + _DOT_GAP) - _DOT_GAP
    ox = cx - span // 2
    for i in range(total):
        x = ox + i * (_DOT_R * 2 + _DOT_GAP)
        bbox = [x, cy - _DOT_R, x + _DOT_R * 2, cy + _DOT_R]
        if i < filled:
            draw.ellipse(bbox, fill=fg, outline=fg)
        else:
            draw.ellipse(bbox, fill=255 if fg == 0 else 0, outline=fg)


def draw_series_cell(Himage, sx, sy, series):
    """Draw one playoff series into the 135x130 cell at (sx, sy).

    When the series is complete the winning team's half of the team-name row
    is painted solid black (inverted), matching how a finished game box marks
    the winner.

    series: one entry from playoff_bracket.json 'series' list.
    """
    draw = ImageDraw.Draw(Himage)
    series = series or {}

    rnd = series.get('round', 'WC')
    header = _ROUND_LABEL.get(rnd, rnd)
    panel_cell.draw_chrome(draw, sx, sy, header)

    away_abbr = series.get('away_abbr', '???')
    home_abbr = series.get('home_abbr', '???')
    away_wins = series.get('away_wins', 0)
    home_wins = series.get('home_wins', 0)
    total_wins_needed = _WIN_GOAL.get(rnd, 2)
    winner = series.get('winner_abbr')

    fg = 0
    font_team = _get_font(14)
    font_rec  = _get_font(9)
    font_game = _get_font(9)

    body_top = sy + panel_cell.HEADER_H + 3
    away_cx = sx + panel_cell.CELL_W // 4
    home_cx = sx + 3 * panel_cell.CELL_W // 4
    mid_x   = sx + panel_cell.CELL_W // 2
    name_h  = 16

    # Winner-background: invert the winning team's half of the name row.
    if winner == away_abbr:
        draw.rectangle([sx, body_top - 1, mid_x - 1, body_top + name_h], fill=0)
    elif winner == home_abbr:
        draw.rectangle([mid_x, body_top - 1, sx + panel_cell.CELL_W - 1, body_top + name_h], fill=0)

    # Team names — white-on-black for the winner's half, black otherwise.
    away_fill = 255 if winner == away_abbr else 0
    home_fill = 255 if winner == home_abbr else 0

    aw = int(font_team.getlength(away_abbr))
    hw = int(font_team.getlength(home_abbr))
    draw.text((away_cx - aw // 2, body_top), away_abbr, font=font_team, fill=away_fill)
    draw.text((away_cx - aw // 2 + 1, body_top), away_abbr, font=font_team, fill=away_fill)
    draw.text((home_cx - hw // 2, body_top), home_abbr, font=font_team, fill=home_fill)
    draw.text((home_cx - hw // 2 + 1, body_top), home_abbr, font=font_team, fill=home_fill)

    # "@" separator
    vs = '@'
    vsw = int(font_rec.getlength(vs))
    draw.text((mid_x - vsw // 2, body_top + 3), vs, font=font_rec, fill=fg)

    # Win-dot rows
    dots_y = body_top + name_h + 5
    _dot_row(draw, away_cx, dots_y, away_wins, total_wins_needed, fg)
    _dot_row(draw, home_cx, dots_y, home_wins, total_wins_needed, fg)

    # Win counts below dots
    aw_str = str(away_wins)
    hw_str = str(home_wins)
    draw.text((away_cx - int(font_rec.getlength(aw_str)) // 2, dots_y + _DOT_R + 2),
              aw_str, font=font_rec, fill=fg)
    draw.text((home_cx - int(font_rec.getlength(hw_str)) // 2, dots_y + _DOT_R + 2),
              hw_str, font=font_rec, fill=fg)

    # Per-game scores
    game_results = series.get('game_results', [])
    away_id = series.get('away_id', '')
    games_start = dots_y + _DOT_R + 14
    for i, gr in enumerate(game_results[:total_wins_needed * 2]):
        gy = games_start + i * 11
        if gy + 10 > sy + panel_cell.CELL_H - 2:
            break
        gn = f'G{i + 1}'
        a_sc = gr.get('away_score')
        h_sc = gr.get('home_score')
        if a_sc is None or h_sc is None:
            line = f'{gn}  —'
        else:
            a_sc, h_sc = int(a_sc), int(h_sc)
            if gr.get('winner_id') == away_id:
                line = f'{gn}  {away_abbr} {a_sc}-{h_sc}'
            else:
                line = f'{gn}  {home_abbr} {h_sc}-{a_sc}'
        draw.text((sx + panel_cell.PAD + 2, gy), line, font=font_game, fill=fg)

    return Himage
