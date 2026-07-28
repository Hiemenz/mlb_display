"""Draw a batting lineup panel (135×130) for an empty grid slot.

Shows both teams' batting orders side-by-side (Away left, Home right) with
the starting pitchers in a strip at the bottom.  The header replicates the
standard scheduled-game tile style: game time on the left, venue on the right.

Only shown by image_grid when the game is within 45 minutes of first pitch.
"""
from image_assets import _get_font, ImageDraw, _logo_ghost, _paste_logo
from image_utils import _clean_venue_name, _pitcher_line


def _short_name(full_name):
    """Return 'F. Last' format from a full player name."""
    parts = (full_name or '').split()
    if not parts:
        return ''
    if len(parts) == 1:
        return parts[0]
    return parts[0][0] + '. ' + parts[-1]

_CELL_W = 135
_CELL_H = 140
_PAD    = 2

# Heights of the fixed sections (px at scale 1)
_HDR_H  = 20   # top header: time + venue
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


def game_within_minutes(game, minutes=45):
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
    font8  = _get_font(8)

    # ── Borders ────────────────────────────────────────────────────────────
    draw.line([(sx, sy),              (sx + _CELL_W - 1, sy)],               fill=0)
    draw.line([(sx, sy + _HDR_H),     (sx + _CELL_W - 1, sy + _HDR_H)],      fill=0)
    draw.line([(sx, sy + _CELL_H - 1),(sx + _CELL_W - 1, sy + _CELL_H - 1)], fill=0, width=1)

    game = _find_primary_game(games_data, primary_abbr)

    # ── Header: game time (left) + venue (right) — mirrors draw_box scheduled ──
    if game:
        game_start = game.get('game_start') or ''
        if game_start and ' ' in game_start:
            time_main, time_ampm = game_start.rsplit(' ', 1)
            time_ampm = time_ampm.lower()
        else:
            time_main, time_ampm = game_start, ''

        # Time left-anchored, bold via double-draw
        for _dx in (2, 3):
            draw.text((sx + _dx, sy + 3), time_main, font=font14, fill=0)
        _total_time_w = int(font14.getlength(time_main))
        if time_ampm:
            mw = _total_time_w
            draw.text((sx + 3 + mw + 1, sy + 8), time_ampm, font=font9, fill=0)
            _total_time_w += int(font9.getlength(time_ampm)) + 2

        # Venue right-anchored — pick the largest font where the full name fits
        venue_clean = _clean_venue_name(game.get('venue'))
        if venue_clean:
            _venue_right = sx + _CELL_W - _PAD
            _max_venue_w = max(_venue_right - sx - _total_time_w - 6, 0)
            if _max_venue_w > 0:
                _sizes = ((font14, 3), (font11, 4), (font10, 5), (font9, 6), (font8, 6),
                          (_get_font(7), 7), (_get_font(6), 7))
                vfont, vy = _sizes[-1]
                for _f, _vy in _sizes:
                    if int(_f.getlength(venue_clean)) <= _max_venue_w:
                        vfont, vy = _f, _vy
                        break
                vw = int(vfont.getlength(venue_clean))
                vx = _venue_right - vw
                draw.text((vx,     sy + vy), venue_clean, font=vfont, fill=0)
                draw.text((vx + 1, sy + vy), venue_clean, font=vfont, fill=0)
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
    col_w  = _CELL_W // 2   # 67 px
    mid_x  = sx + col_w
    body_y = sy + _HDR_H

    # Vertical divider (full body height)
    draw.line([(mid_x, body_y), (mid_x, sy + _CELL_H - 1)], fill=0)

    # ── Ghost logos in each column background ──────────────────────────────
    if use_logos:
        body_h    = _CELL_H - _HDR_H - _SP_H
        ghost_sz  = min(col_w - 4, body_h - 4)
        for abbr, tid, col_x in (
            (game.get('away_team_name'), str(game.get('away_team_id', '')), sx),
            (game.get('home_team_name'), str(game.get('home_team_id', '')), mid_x),
        ):
            ghost = _logo_ghost(abbr, tid, size=ghost_sz, lightness=160)
            if ghost:
                gw, gh = ghost.size
                gx = col_x + (col_w - gw) // 2
                gy = sy + _HDR_H + (body_h - gh) // 2
                _paste_logo(Himage, ghost, (gx, gy))
        draw = ImageDraw.Draw(Himage)

    # ── Batting order rows ──────────────────────────────────────────────────
    avail_h = _CELL_H - _HDR_H - _SP_H
    row_h   = avail_h // _N_ROWS   # ≈ 10–11 px with team names removed

    # Choose the largest font that fits comfortably in the row height
    name_font = font10 if row_h >= 10 else font9

    # Single global position-column width so both columns are symmetric
    all_positions = [p.get('pos', '') for p in away_lineup + home_lineup]
    global_pos_w  = max((int(name_font.getlength(p)) for p in all_positions), default=0)
    pos_gap       = col_w - global_pos_w - _PAD - 1   # offset from col_x to pos left edge
    max_name_w    = pos_gap - _PAD - 2                 # name width budget

    def _render_col(lineup, col_x):
        for i in range(_N_ROWS):
            ry = body_y + 1 + i * row_h
            name = _short_name(lineup[i].get('name', '')) if i < len(lineup) else ''
            pos  = lineup[i].get('pos', '')              if i < len(lineup) else ''
            nm = name
            while nm and int(name_font.getlength(nm)) > max_name_w:
                nm = nm[:-1]
            if nm:
                draw.text((col_x + _PAD, ry), nm, font=name_font, fill=0)
            if pos:
                pw = int(name_font.getlength(pos))
                draw.text((col_x + pos_gap + (global_pos_w - pw), ry), pos, font=name_font, fill=0)

    _render_col(away_lineup, sx)
    _render_col(home_lineup, mid_x)

    # ── Starting pitcher strip (name row + stat row) ───────────────────────
    sp_y = sy + _CELL_H - _SP_H
    draw.line([(sx, sp_y), (sx + _CELL_W - 1, sp_y)], fill=0)

    away_name, away_stat = _pitcher_line(game.get('away_probable'), game.get('away_probable_note'))
    home_name, home_stat = _pitcher_line(game.get('home_probable'), game.get('home_probable_note'))

    sp_pw  = int(font9.getlength('P'))
    sp_px  = col_w - sp_pw - _PAD - 1   # fixed position column offset within each half
    for sp_nm, col_x in ((away_name, sx), (home_name, mid_x)):
        draw.text((col_x + sp_px, sp_y + 1), 'P', font=font9, fill=0)
        nm = sp_nm
        while nm and int(font9.getlength(nm)) > sp_px - 2 - _PAD:
            nm = nm[:-1]
        if nm:
            draw.text((col_x + _PAD, sp_y + 1), nm, font=font9, fill=0)

    return Himage
