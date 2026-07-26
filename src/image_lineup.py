"""Draw a batting lineup panel (135×130) for an empty grid slot.

Shows both teams' batting orders side-by-side (Away left, Home right) with
the starting pitchers in a strip at the bottom.  The header replicates the
standard game-tile style: game time on the left, state on the right.

Only shown by image_grid when the game is within 30 minutes of first pitch.
"""
from image_assets import _get_font, ImageDraw
from image_utils import _last_name

_CELL_W = 135
_CELL_H = 130
_PAD    = 2

# Heights of the fixed sections (px at scale 1)
_HDR_H  = 20   # top header: time + state
_TEAM_H = 11   # team-name sub-header inside body
_SP_H   = 12   # starting-pitcher strip at bottom
_N_ROWS = 9    # batting-order slots


def _find_primary_game(games_data, primary_abbr):
    """Return the game dict for the primary team, or None."""
    from util import load_json_file
    teams = load_json_file('standings.json').get('team_abbreviation', {})
    abbr_to_id = {v: str(k) for k, v in teams.items()}
    target_id = abbr_to_id.get(primary_abbr or '')

    for game in (games_data or []):
        away_id = str(game.get('away_team_id', ''))
        home_id = str(game.get('home_team_id', ''))
        if target_id and (away_id == target_id or home_id == target_id):
            return game
    return None


def game_within_minutes(game, minutes=30):
    """Return True when the game's UTC start time is within `minutes` of now."""
    from datetime import datetime, timezone, timedelta
    game_date = game.get('game_date') or ''
    if not game_date:
        return False
    try:
        gd    = game_date.replace('Z', '+00:00')
        start = datetime.fromisoformat(gd)
        now   = datetime.now(timezone.utc)
        return timedelta(0) <= (start - now) <= timedelta(minutes=minutes)
    except (ValueError, TypeError):
        return False


def draw_lineup_cell(Himage, sx, sy, games_data, primary_abbr, team_data, use_logos=False):
    """Draw the batting lineup panel at pixel position (sx, sy)."""
    draw = ImageDraw.Draw(Himage)

    font14 = _get_font(14)
    font11 = _get_font(11)
    font10 = _get_font(10)
    font9  = _get_font(9)

    # ── Borders ────────────────────────────────────────────────────────────
    draw.line([(sx, sy),              (sx + _CELL_W - 1, sy)],               fill=0)
    draw.line([(sx, sy + _HDR_H),     (sx + _CELL_W - 1, sy + _HDR_H)],      fill=0)
    draw.line([(sx, sy + _CELL_H - 1),(sx + _CELL_W - 1, sy + _CELL_H - 1)], fill=0, width=1)

    game = _find_primary_game(games_data, primary_abbr)

    # ── Header: game time (left) + state (right) — mirrors draw_box ────────
    if game:
        game_start = game.get('game_start') or ''
        state      = game.get('detailed_state') or ''
        if game_start and ' ' in game_start:
            time_main, time_ampm = game_start.rsplit(' ', 1)
            time_ampm = time_ampm.lower()
        else:
            time_main, time_ampm = game_start, ''

        # Time left-anchored, bold via double-draw
        for _dx in (2, 3):
            draw.text((sx + _dx, sy + 3), time_main, font=font14, fill=0)
        if time_ampm:
            mw = int(font14.getlength(time_main))
            draw.text((sx + 3 + mw + 1, sy + 8), time_ampm, font=font9, fill=0)

        # State right-anchored in small font
        _state_abbr = {'Scheduled': 'Sched', 'Pre-Game': 'Pre-Game', 'Warmup': 'Warmup'}.get(state, state)
        if _state_abbr:
            sw = int(font9.getlength(_state_abbr))
            draw.text((sx + _CELL_W - sw - _PAD, sy + 8), _state_abbr, font=font9, fill=0)
    else:
        # Fallback header when no game found
        lbl = 'Lineups'
        lw  = int(font11.getlength(lbl))
        draw.text((sx + (_CELL_W - lw) // 2,     sy + 4), lbl, font=font11, fill=0)
        draw.text((sx + (_CELL_W - lw) // 2 + 1, sy + 4), lbl, font=font11, fill=0)

    if game is None:
        return Himage

    away_lineup = game.get('away_lineup') or []
    home_lineup = game.get('home_lineup') or []

    if not away_lineup and not home_lineup:
        msg = 'Not Yet Posted'
        mw  = int(font9.getlength(msg))
        draw.text((sx + (_CELL_W - mw) // 2, sy + 65), msg, font=font9, fill=0)
        return Himage

    # ── Two-column layout ───────────────────────────────────────────────────
    col_w = _CELL_W // 2   # 67 px
    mid_x = sx + col_w
    body_y = sy + _HDR_H

    # Vertical divider (full body height)
    draw.line([(mid_x, body_y), (mid_x, sy + _CELL_H - 1)], fill=0)

    # Team-name sub-headers
    away_name = game.get('away_team_name') or 'Away'
    home_name = game.get('home_team_name') or 'Home'
    away_label = away_name.split()[-1]
    home_label = home_name.split()[-1]
    for lbl, col_x in ((away_label, sx), (home_label, mid_x)):
        while lbl and int(font10.getlength(lbl)) > col_w - 2:
            lbl = lbl[:-1]
        lw = int(font10.getlength(lbl))
        lx = col_x + (col_w - lw) // 2
        draw.text((lx,     body_y + 1), lbl, font=font10, fill=0)
        draw.text((lx + 1, body_y + 1), lbl, font=font10, fill=0)

    # ── Batting order rows (no slot numbers) ───────────────────────────────
    row_top = body_y + _TEAM_H
    avail_h = _CELL_H - _HDR_H - _TEAM_H - _SP_H
    row_h   = avail_h // _N_ROWS   # ≈ 9–10 px

    def _render_col(lineup, col_x):
        for i in range(_N_ROWS):
            ry = row_top + i * row_h
            if i < len(lineup):
                name = _last_name(lineup[i].get('name', ''))
                pos  = lineup[i].get('pos', '')
            else:
                name, pos = '', ''

            pw   = int(font9.getlength(pos))
            px2  = col_x + col_w - pw - _PAD - 1
            draw.text((px2, ry), pos, font=font9, fill=0)

            max_name_w = px2 - 2 - (col_x + _PAD)
            while name and int(font9.getlength(name)) > max_name_w:
                name = name[:-1]
            if name:
                draw.text((col_x + _PAD, ry), name, font=font9, fill=0)

    _render_col(away_lineup, sx)
    _render_col(home_lineup, mid_x)

    # ── Starting pitcher strip ──────────────────────────────────────────────
    sp_y = sy + _CELL_H - _SP_H
    draw.line([(sx, sp_y), (sx + _CELL_W - 1, sp_y)], fill=0)

    away_sp = _last_name(game.get('away_probable') or '')
    home_sp = _last_name(game.get('home_probable') or '')

    for sp, col_x in ((away_sp, sx), (home_sp, mid_x)):
        sp_trunc = sp
        while sp_trunc and int(font9.getlength(sp_trunc)) > col_w - 2 * _PAD:
            sp_trunc = sp_trunc[:-1]
        if sp_trunc:
            sw = int(font9.getlength(sp_trunc))
            lx = col_x + (col_w - sw) // 2
            draw.text((lx, sp_y + 1), sp_trunc, font=font9, fill=0)

    return Himage
