from datetime import datetime

from util import load_json_file, load_yaml_file
from image_assets import (
    _get_font, _logo_small, _logo_ghost, _paste_logo,
    Image, ImageDraw, ImageOps,
)
import time as _time_feat

from image_utils import (
    draw_diamond, draw_circle, draw_tight_number,
    _last_name, _is_game_effectively_over,
    _series_display_str, _clean_venue_name,
)
from image_standings import (
    _WC_STRIP_H,
    derive_wildcard_from_standings, draw_wildcard_header,
    draw_standings_sidebar_fullscreen, draw_playoff_bracket_header,
)
from image_box import draw_box, _abbr_play, _draw_backwards_k


def _find_featured_game(game_state_data, team_data, primary_abbr):
    """Return the best game to display for primary_abbr in fullscreen mode.

    Priority: first Scheduled/Pre-Game/Warmup → first In Progress → last Final.
    Falls back to any live game in progress, then the first game, when the primary
    team has no game today.
    """
    abbr_map = team_data.get('team_abbreviation', {})
    primary_games = []
    for game in game_state_data:
        away = abbr_map.get(str(game.get('away_team_id', '')), '')
        home = abbr_map.get(str(game.get('home_team_id', '')), '')
        if primary_abbr in (away, home):
            primary_games.append(game)

    if not primary_games:
        _live_states = {'In Progress', 'Player challenge', 'Manager challenge'}
        for g in game_state_data:
            if g.get('detailed_state') in _live_states:
                return g
        return game_state_data[0] if game_state_data else None

    _scheduled = {'Scheduled', 'Pre-Game', 'Warmup', 'Delayed Start'}
    _final     = {'Final', 'Game Over', 'Final: Tied'}

    for g in primary_games:
        if g.get('detailed_state') in _scheduled:
            return g
    for g in primary_games:
        if g.get('detailed_state') == 'In Progress':
            return g
    for g in reversed(primary_games):
        if g.get('detailed_state', '').startswith('Completed Early') or g.get('detailed_state') in _final:
            return g
    return primary_games[-1]


def _draw_between_innings(draw, game_data, away_abbr, home_abbr, cur_inn,
                          pit_nm, batter_names, SIT_Y, DIV_Y, WIN_PCT_Y):
    """Draw linescore + pitcher/due-up names in the between-innings situation area."""
    _bot = WIN_PCT_Y - 4

    _ls_col_t   = 44
    _ls_n_cols  = 9
    _ls_first_inn = max(1, cur_inn - _ls_n_cols + 1)
    _ls_col_w   = 37
    _ls_grid_w  = _ls_col_t + _ls_n_cols * _ls_col_w
    _ls_x0      = (800 - _ls_grid_w) // 2
    _ls_x1      = _ls_x0 + _ls_grid_w

    _ls_y_top = SIT_Y + 3
    _ls_y_bot = WIN_PCT_Y - 3
    _ls_hdr_h = 25
    _ls_row_h = (_ls_y_bot - _ls_y_top - _ls_hdr_h) // 2
    _ls_y1    = _ls_y_top + _ls_hdr_h
    _ls_y2    = _ls_y1 + _ls_row_h

    f_ls_hdr  = _get_font(20)
    f_ls_team = _get_font(18)
    f_ls_runs = _get_font(36)

    draw.line((_ls_x0, _ls_y1, _ls_x1, _ls_y1), fill=0, width=2)
    draw.line((_ls_x0, _ls_y2, _ls_x1, _ls_y2), fill=0, width=1)

    _ls_div_x = _ls_x0 + _ls_col_t
    draw.line((_ls_div_x, DIV_Y, _ls_div_x, WIN_PCT_Y - 1), fill=0, width=2)
    for _k in range(1, _ls_n_cols):
        _vx = _ls_div_x + _k * _ls_col_w
        draw.line((_vx, DIV_Y, _vx, WIN_PCT_Y - 1), fill=0, width=1)

    for _k in range(_ls_n_cols):
        _inn_n   = str(_ls_first_inn + _k)
        _cell_cx = _ls_div_x + _k * _ls_col_w + _ls_col_w // 2
        _hdr_cy  = _ls_y_top + _ls_hdr_h // 2
        _nw = int(f_ls_hdr.getlength(_inn_n))
        _nx = _cell_cx - _nw // 2
        _ny = _hdr_cy - 10
        draw.text((_nx,     _ny), _inn_n, font=f_ls_hdr, fill=0)
        draw.text((_nx + 1, _ny), _inn_n, font=f_ls_hdr, fill=0)

    away_inn_runs = game_data.get('away_inning_runs') or []
    home_inn_runs = game_data.get('home_inning_runs') or []
    for _t_abbr, _row_y, _row_h in (
        (away_abbr, _ls_y1, _ls_row_h),
        (home_abbr, _ls_y2, _ls_y_bot - _ls_y2),
    ):
        _aw = int(f_ls_team.getlength(_t_abbr))
        _ax = _ls_x0 + (_ls_col_t - _aw) // 2
        _ay = _row_y + (_row_h - 18) // 2
        draw.text((_ax,     _ay), _t_abbr, font=f_ls_team, fill=0)
        draw.text((_ax + 1, _ay), _t_abbr, font=f_ls_team, fill=0)

    for _k in range(_ls_n_cols):
        _cell_cx = _ls_div_x + _k * _ls_col_w + _ls_col_w // 2
        _inn_idx = _ls_first_inn - 1 + _k
        for _runs_list, _row_y, _row_h in (
            (away_inn_runs, _ls_y1, _ls_row_h),
            (home_inn_runs, _ls_y2, _ls_y_bot - _ls_y2),
        ):
            if _inn_idx < len(_runs_list) and _runs_list[_inn_idx] is not None:
                _rv = str(_runs_list[_inn_idx])
                _rw = int(f_ls_runs.getlength(_rv))
                _rx = _cell_cx - _rw // 2
                _ry = _row_y + (_row_h - 36) // 2
                draw.text((_rx,     _ry), _rv, font=f_ls_runs, fill=0)
                draw.text((_rx + 1, _ry), _rv, font=f_ls_runs, fill=0)

    if pit_nm:
        _pit_max_w = _ls_x0 - 16 - 8
        _f_pit = _get_font(18)
        for _fsize in (42, 36, 28, 24, 20, 18):
            _f = _get_font(_fsize)
            if int(_f.getlength(pit_nm)) <= _pit_max_w:
                _f_pit = _f
                break
        _pit_h = _f_pit.size
        _pit_y = (SIT_Y + 8 + _bot) // 2 - _pit_h // 2
        draw.text((16, _pit_y),     pit_nm, font=_f_pit, fill=0)
        draw.text((17, _pit_y),     pit_nm, font=_f_pit, fill=0)

    if batter_names:
        _bat_max_w = 800 - _ls_x1 - 16 - 8
        _f_bat = _get_font(18)
        for _fsize in (42, 36, 28, 24, 20, 18):
            _f = _get_font(_fsize)
            if all(int(_f.getlength(nm)) <= _bat_max_w for nm in batter_names):
                _f_bat = _f
                break
        _bat_h      = _f_bat.size
        _avail_h    = _bot - (SIT_Y + 8)
        _n          = len(batter_names)
        _bat_gap    = min(6, max(0, (_avail_h - _n * _bat_h) // max(1, _n)))
        _bat_stride = _bat_h + _bat_gap
        _stack_h    = _n * _bat_stride - _bat_gap
        _by         = (SIT_Y + 8 + _bot - _stack_h) // 2
        for _nm in batter_names:
            if _by + _bat_h <= _bot:
                _nm_w = int(_f_bat.getlength(_nm))
                _nm_x = 800 - _nm_w - 16
                draw.text((_nm_x, _by),     _nm, font=_f_bat, fill=0)
                draw.text((_nm_x + 1, _by), _nm, font=_f_bat, fill=0)
            _by += _bat_stride


def _draw_active_pitch(canvas, draw, game_data, f42, f36, B_R, C_GAP,
                       SIT_Y, WIN_PCT_Y, mid_inning_pc):
    """Draw BSO circles, pitch info, and pitcher/batter in the live situation area.

    Returns (canvas, draw) — callers must use the returned pair.
    """
    _bso_y  = SIT_Y + 6
    _b_bbox = f42.getbbox('B')
    _bso_cy = _bso_y + (_b_bbox[1] + _b_bbox[3]) // 2

    _bx = 16
    draw.text((_bx,     _bso_y), 'B', font=f42, fill=0)
    draw.text((_bx + 1, _bso_y), 'B', font=f42, fill=0)
    _bx += int(f42.getlength('B')) + 8
    _balls = game_data.get('balls') or 0
    for i in range(3):
        _cx = _bx + B_R
        canvas = draw_circle(canvas, (_cx, _bso_cy), B_R, i < _balls)
        _bx += 2 * B_R + C_GAP
    draw = ImageDraw.Draw(canvas)

    _sx = _bx + 16
    draw.text((_sx,     _bso_y), 'S', font=f42, fill=0)
    draw.text((_sx + 1, _bso_y), 'S', font=f42, fill=0)
    _sx += int(f42.getlength('S')) + 8
    _strikes = game_data.get('strikes') or 0
    _scalls  = game_data.get('strike_calls', [])
    for i in range(2):
        _cx   = _sx + B_R
        _call = _scalls[i] if i < len(_scalls) else None
        if i < _strikes and _call in ('S', 'F'):
            canvas = draw_circle(canvas, (_cx, _bso_cy), B_R, False, outline_width=10)
            draw   = ImageDraw.Draw(canvas)
        else:
            canvas = draw_circle(canvas, (_cx, _bso_cy), B_R, i < _strikes)
            draw   = ImageDraw.Draw(canvas)
        _sx += 2 * B_R + C_GAP

    _lps = game_data.get('last_pitch_speed')
    _pt  = game_data.get('last_pitch_type', '')
    _pc  = game_data.get('pitch_count')
    _pitch_parts = []
    if _pt:              _pitch_parts.append(_pt)
    if _lps:             _pitch_parts.append(f'{int(_lps)}mph')
    if _pc  is not None: _pitch_parts.append(f'{_pc}P')
    if _pitch_parts:
        _ptxt    = '  '.join(_pitch_parts)
        _ptw     = int(f36.getlength(_ptxt))
        _pt_bbox = f36.getbbox(_ptxt)
        _pty     = _bso_cy - (_pt_bbox[1] + _pt_bbox[3]) // 2
        draw.text((800 - _ptw - 8, _pty), _ptxt, font=f36, fill=0)

    _lbl_x        = 400
    _pb_y         = _bso_y + 48
    _pitcher_full = (game_data.get('current_pitcher') or '').strip()
    _pc_incoming  = (game_data.get('sub_event') or '')[3:].strip() if mid_inning_pc else ''
    if _pc_incoming:
        _out_nm  = _last_name(_pitcher_full)
        _pit_txt = f'P: {_out_nm}→{_pc_incoming}' if _out_nm else f'P: {_pc_incoming}'
    else:
        _pit_txt = f'P: {_pitcher_full}' if _pitcher_full else ''
    if _pit_txt and _pb_y + 42 <= WIN_PCT_Y:
        _p_max_w = _lbl_x - 16 - 8
        _f_pit   = _get_font(20)
        for _fsize in (42, 36, 28, 24, 20):
            _f = _get_font(_fsize)
            if int(_f.getlength(_pit_txt)) <= _p_max_w:
                _f_pit = _f
                break
        else:
            while _pit_txt and int(_f_pit.getlength(_pit_txt)) > _p_max_w:
                _pit_txt = _pit_txt[:-1]
        _pit_ty = _pb_y + (42 - _f_pit.size)
        draw.text((16, _pit_ty),     _pit_txt, font=_f_pit, fill=0)
        draw.text((17, _pit_ty),     _pit_txt, font=_f_pit, fill=0)

    _ab_done = game_data.get('current_at_bat_complete', False)
    if _ab_done and not _is_game_effectively_over(game_data):
        _batter_full = (game_data.get('due_up') or game_data.get('next_batter_1') or '').strip()
        _od_full     = (game_data.get('in_hole') or '').strip()
    else:
        _batter_full = (
            game_data.get('current_play_batter') or game_data.get('current_hitter') or ''
        ).strip()
        _od_full = (game_data.get('due_up') or '').strip()
    if _od_full == _batter_full:
        _od_full = ''

    _lbl_col = _lbl_x + max(int(f42.getlength('AB:')), int(f42.getlength('OD:')))
    _name_x  = _lbl_col + 8

    if _batter_full and _pb_y + 42 <= WIN_PCT_Y:
        _ab_w = int(f42.getlength('AB:'))
        draw.text((_lbl_col - _ab_w,      _pb_y), 'AB:', font=f42, fill=0)
        draw.text((_lbl_col - _ab_w + 1,  _pb_y), 'AB:', font=f42, fill=0)
        draw.text((_name_x,     _pb_y), _batter_full, font=f42, fill=0)
        draw.text((_name_x + 1, _pb_y), _batter_full, font=f42, fill=0)

    _od_y = _pb_y + 46
    if _od_full and _od_y + 42 <= WIN_PCT_Y - 2:
        _od_w = int(f42.getlength('OD:'))
        draw.text((_lbl_col - _od_w,      _od_y), 'OD:', font=f42, fill=0)
        draw.text((_lbl_col - _od_w + 1,  _od_y), 'OD:', font=f42, fill=0)
        draw.text((_name_x,     _od_y), _od_full, font=f42, fill=0)
        draw.text((_name_x + 1, _od_y), _od_full, font=f42, fill=0)

    return canvas, draw


def _draw_win_pct_bar(canvas, draw, game_data, away_abbr, away_id, home_abbr, home_id,
                      WIN_PCT_Y, WIN_PCT_H, f36, f14, use_logos):
    """Draw the separator line and win probability bar at the bottom of the canvas.

    Returns (canvas, draw).
    """
    draw.line((0, WIN_PCT_Y - 1, 799, WIN_PCT_Y - 1), fill=0, width=2)

    _away_wp = game_data.get('away_win_probability')
    _home_wp = game_data.get('home_win_probability')
    if _away_wp is None or _home_wp is None:
        return canvas, draw
    try:
        _awp = float(_away_wp)
        _hwp = float(_home_wp)
        if _awp + _hwp > 1.5:
            _awp /= 100.0
            _hwp /= 100.0

        BAR_W   = 800
        BAR_H   = WIN_PCT_H
        LOGO_SZ = BAR_H - 4

        _ghost = Image.new('L', (BAR_W, BAR_H), 255)
        _gd    = ImageDraw.Draw(_ghost)
        _wf    = f36
        _gd.text((6, (BAR_H - 36) // 2),                  'LOSS', font=_wf, fill=0)
        _win_w = int(_wf.getlength('WIN'))
        _gd.text((BAR_W - _win_w - 6, (BAR_H - 36) // 2), 'WIN',  font=_wf, fill=0)
        _ghost = _ghost.point(lambda p: 255 if p > 180 else min(255, int(p * 0.35 + 155)))
        _gd.line((0, BAR_H // 2, BAR_W, BAR_H // 2), fill=0)
        canvas.paste(_ghost.convert('1'), (0, WIN_PCT_Y))
        draw = ImageDraw.Draw(canvas)

        _away_px = int(BAR_W * _awp)
        _home_px = int(BAR_W * _hwp)
        _away_lx = max(0, min(BAR_W - LOGO_SZ, _away_px - LOGO_SZ // 2))
        _home_lx = max(0, min(BAR_W - LOGO_SZ, _home_px - LOGO_SZ // 2))
        MIN_SEP  = LOGO_SZ + 2
        if _away_lx > _home_lx:
            if _away_lx - _home_lx < MIN_SEP:
                _mid     = (_away_lx + _home_lx) // 2
                _away_lx = min(BAR_W - LOGO_SZ, _mid + MIN_SEP // 2)
                _home_lx = max(0, _mid - MIN_SEP // 2)
        else:
            if _home_lx - _away_lx < MIN_SEP:
                _mid     = (_away_lx + _home_lx) // 2
                _home_lx = min(BAR_W - LOGO_SZ, _mid + MIN_SEP // 2)
                _away_lx = max(0, _mid - MIN_SEP // 2)

        if use_logos:
            _awl = _logo_small(away_abbr, away_id, size=LOGO_SZ)
            _hwl = _logo_small(home_abbr, home_id, size=LOGO_SZ)
            if _awl:
                _paste_logo(canvas, _awl, (_away_lx, WIN_PCT_Y + (BAR_H - _awl.size[1]) // 2))
            if _hwl:
                _paste_logo(canvas, _hwl, (_home_lx, WIN_PCT_Y + (BAR_H - _hwl.size[1]) // 2))
            draw = ImageDraw.Draw(canvas)
        else:
            draw.line((_away_px, WIN_PCT_Y, _away_px, WIN_PCT_Y + BAR_H), fill=0, width=2)
            draw.line((_home_px, WIN_PCT_Y, _home_px, WIN_PCT_Y + BAR_H), fill=0, width=2)
            _astr = f'{_awp:.0%}'
            _hstr = f'{_hwp:.0%}'
            draw.text((_away_px + 4, WIN_PCT_Y + (BAR_H - 14) // 2), _astr, font=f14, fill=0)
            _hsw = int(f14.getlength(_hstr))
            draw.text((_home_px - _hsw - 4, WIN_PCT_Y + (BAR_H - 14) // 2), _hstr, font=f14, fill=0)
    except (ValueError, TypeError):
        pass

    return canvas, draw


def draw_live_fullscreen_game(game_data, team_data, config=None):
    """Full 800x480 canvas for a live (In Progress) featured game.

    Layout v4
    ---------
    y=0..91    Header  : inning (f56, left)  last event/matchup (f56, right)
    y=92..111  R / H / E column labels (f14)
    y=112..191 Away row : logo  abbr  R  H  E  |  bases diamond (right, spans rows)
    y=192..271 Home row : logo  abbr  R  H  E  |
    y=272..307 [blank left]  |  outs circles (right, under bases)
    y=308      Divider line
    y=309..479 Bottom :
        Live           : B/S/O circles + pitch info (f36) + pitcher/batter (f42)
        Between-innings: pitcher (f42, left, centred) + due-up batters (f42, right)
    y=425      Win % divider
    y=426..479 Win % bar (54 px)
    """
    import re as _re_lf

    if config is None:
        config = load_yaml_file('config.yaml')

    use_logos = config.get('use_team_logos', False)

    # Normalise mid-game review/challenge states
    if game_data.get('detailed_state') in ('Player challenge', 'Manager challenge'):
        game_data = dict(game_data)
        game_data['sub_event'] = (
            'ABS CHAL' if game_data['detailed_state'] == 'Player challenge' else 'M CHAL'
        )
        game_data['detailed_state'] = 'In Progress'

    canvas = Image.new('1', (800, 480), 255)
    draw   = ImageDraw.Draw(canvas)

    # ---- Fonts ---------------------------------------------------------------
    f14  = _get_font(14)    # ABS / challenge labels
    _get_font(24)    # between-innings batters + OD
    f28  = _get_font(28)    # between-innings pitcher + SV badge
    f36  = _get_font(36)    # pitch info right-aligned
    f42  = _get_font(42)    # BSO labels + pitcher/batter + team abbreviations
    f52  = _get_font(52)    # runner jersey numbers inside bases
    f56  = _get_font(56)    # header inning + last-event text
    f72  = _get_font(72)    # R / H / E values in score rows

    # ---- Team identifiers ----------------------------------------------------
    abbr_map  = team_data.get('team_abbreviation', {})
    away_id   = str(game_data.get('away_team_id', ''))
    home_id   = str(game_data.get('home_team_id', ''))
    away_abbr = abbr_map.get(away_id, f'T{away_id}')
    home_abbr = abbr_map.get(home_id, f'T{home_id}')

    # ---- Inning state --------------------------------------------------------
    _inn_state   = game_data.get('inningState') or ''
    _cur_inn     = game_data.get('current_inning') or 1
    _inn_ord_raw = game_data.get('currentInningOrdinal') or str(_cur_inn)
    _inn_ord     = _re_lf.sub(r'(?:st|nd|rd|th)$', '', _inn_ord_raw, flags=_re_lf.IGNORECASE)
    _lbl_map     = {'Top': '▲', 'Bottom': '▼', 'Middle': 'Mid', 'End': 'End'}
    _inn_lbl     = _lbl_map.get(_inn_state, (_inn_state[:3] if _inn_state else ''))
    inning_str   = f'{_inn_lbl} {_inn_ord}'.strip()

    _three_outs_lag = _inn_state in ('Top', 'Bottom') and (game_data.get('num_of_outs') or 0) >= 3
    _between_innings = _inn_state in ('Middle', 'End') or _three_outs_lag
    _pitching_change = (game_data.get('sub_event') or '').startswith('PC:')
    # A PC during a live half-inning (an out recorded, or a pitch already thrown)
    # keeps the active display; only pre-half-inning changes swap in the linescore.
    # Mirrors _compute_layout_flags() in image_box.py.
    _mid_inning_pc = bool(
        _pitching_change and not _between_innings
        and (
            (game_data.get('num_of_outs') or 0) > 0
            or (game_data.get('at_bat_pitch_count') or 0) > 0
        )
    )

    # ---- Layout constants -------------------------------------------------------
    HEADER_H   = 69
    LABEL_H    = 20
    TEAM_ROW_H = 80
    AWAY_Y     = HEADER_H + LABEL_H          # 89
    HOME_Y     = AWAY_Y  + TEAM_ROW_H        # 169
    OUTS_Y_TOP = HOME_Y  + TEAM_ROW_H - 21  # 228
    OUTS_H     = 48
    DIV_Y      = OUTS_Y_TOP + OUTS_H         # 276
    SIT_Y      = DIV_Y + 1                   # 277
    WIN_PCT_H  = 54
    WIN_PCT_Y  = 480 - WIN_PCT_H             # 426  (situation area = 149 px)

    # Team row layout
    LOGO_SZ  = 72
    LOGO_X   = 2
    ABBR_X   = LOGO_X + LOGO_SZ + 6         # 80

    # R/H/E column centres
    R_CX = 240
    H_CX = 360
    E_CX = 480

    # Bases: right side, spanning both score rows
    DIAMOND_CX = 645
    DIAMOND_CY = 178
    BASE_DIST  = 58
    BASE_SZ    = 46
    BASE_OW    = 4

    # BSO circles
    B_R   = 16
    O_R   = 20
    C_GAP = 5

    # ---- Last-event helper (built early for header use) ----------------------
    _FLD_POS = [
        ('center fielder', '8'), ('right fielder', '9'), ('left fielder', '7'),
        ('first baseman', '3'), ('second baseman', '4'), ('third baseman', '5'),
        ('shortstop', '6'), ('catcher', '2'), ('pitcher', '1'),
    ]

    def _build_last_event():
        """Build last event."""
        _sub_ev = (game_data.get('sub_event') or '').strip()
        # PC notices display in the bottom panel; show the last real play in the header.
        if _sub_ev.startswith('PC:'):
            _sub_ev = ''
        _review = game_data.get('last_review_result') or ''
        _lp     = game_data.get('last_play') or ''
        _raw    = _sub_ev or _review or _lp
        if not _raw:
            return ''
        _pd  = _abbr_play(_raw)
        # Resolve flyout/lineout to F7/L6 etc. using the play description
        if _pd in ('FO', 'LO', 'PO'):
            _prefix = _pd[0]
            _desc   = (game_data.get('last_play_description') or '').lower()
            for _kw, _code in _FLD_POS:
                if _kw in _desc:
                    _pd = f'{_prefix}{_code}'
                    break
        _rbi = int(game_data.get('last_play_rbi') or 0)
        if _rbi > 0 and not _sub_ev:
            if _pd == 'HR':
                if _rbi >= 2:
                    _pd = f'{_rbi}R HR'
            elif _rbi == 1:
                _pd = f'RBI {_pd}'
            else:
                _pd = f'{_rbi}RBI {_pd}'
        return _pd

    _last_ev    = _build_last_event()
    _run_scored = int(game_data.get('last_play_rbi') or 0) > 0

    # ---- HEADER (69px — full-width thick line below) ------------------------
    # Inning: f56 fits in 69px header. Triangle 80% of numeral height.
    # Suppress arrow when 3 outs recorded but API hasn't flipped inningState yet.
    _inn_x = 8
    _inn_y = 4
    _inn_font = f56
    if _inn_lbl in ('▲', '▼') and not _three_outs_lag:
        _nbbox   = _inn_font.getbbox(_inn_ord)
        _n_top   = _inn_y + _nbbox[1]
        _n_bot   = _inn_y + _nbbox[3]
        _n_h     = _n_bot - _n_top
        _tri_h   = int(_n_h * 0.80)
        _tri_mid = (_n_top + _n_bot) // 2
        _tri_top = _tri_mid - _tri_h // 2
        _tri_bot = _tri_top + _tri_h
        _t_cx    = _inn_x + _tri_h // 2
        _t_rgt   = _inn_x + _tri_h
        if _inn_lbl == '▲':
            draw.polygon([(_t_cx, _tri_top), (_inn_x, _tri_bot), (_t_rgt, _tri_bot)], fill=0)
        else:
            draw.polygon([(_inn_x, _tri_top), (_t_rgt, _tri_top), (_t_cx, _tri_bot)], fill=0)
        _num_x = _t_rgt + 8
        draw.text((_num_x,     _inn_y), _inn_ord, font=_inn_font, fill=0)
        draw.text((_num_x + 1, _inn_y), _inn_ord, font=_inn_font, fill=0)
        _inn_right_edge = _num_x + int(_inn_font.getlength(_inn_ord))
    else:
        _hdr_inn_str = f'Mid {_inn_ord}' if _three_outs_lag else inning_str
        draw.text((_inn_x,     _inn_y), _hdr_inn_str, font=_inn_font, fill=0)
        draw.text((_inn_x + 1, _inn_y), _hdr_inn_str, font=_inn_font, fill=0)
        _inn_right_edge = _inn_x + int(_inn_font.getlength(_hdr_inn_str))

    # Right side of header: last event (f56) right-aligned; fall back to matchup (f36)
    _inn_min_right = _inn_right_edge + 16
    if _last_ev:
        _hdr_right_txt  = _last_ev
        _hdr_right_font = f56
    else:
        _hdr_right_txt  = f'{away_abbr} @ {home_abbr}'
        _hdr_right_font = f36
    _hrw   = int(_hdr_right_font.getlength(_hdr_right_txt))
    _hdr_x = 800 - _hrw - 8
    if _hdr_x > _inn_min_right:
        _hry = max(4, (HEADER_H - _hdr_right_font.size) // 2)
        if 'Kl' not in _hdr_right_txt:
            draw.text((_hdr_x,     _hry), _hdr_right_txt, font=_hdr_right_font, fill=0)
            draw.text((_hdr_x + 1, _hry), _hdr_right_txt, font=_hdr_right_font, fill=0)
        else:
            _parts = _hdr_right_txt.split('Kl')
            for _ox in (_hdr_x, _hdr_x + 1):
                _cx = _ox
                for _i, _seg in enumerate(_parts):
                    if _seg:
                        draw.text((_cx, _hry), _seg, font=_hdr_right_font, fill=0)
                        _cx += int(_hdr_right_font.getlength(_seg))
                    if _i < len(_parts) - 1:
                        _draw_backwards_k(canvas, _cx, _hry, _hdr_right_font)
                        _cx += int(_hdr_right_font.getlength('K'))

    draw.line((0, HEADER_H - 1, 799, HEADER_H - 1), fill=0, width=5)

    if _run_scored:
        _hdr_crop = canvas.crop((0, 0, 800, HEADER_H))
        canvas.paste(ImageOps.invert(_hdr_crop.convert('L')).convert('1'), (0, 0))
        draw = ImageDraw.Draw(canvas)

    # No-hitter / perfect game: invert header when active (≥ 6 innings).
    # Skip when run-scored already inverted it (double-invert = no-op).
    _fs_active_no_no = (
        (game_data.get('no_hitter') or game_data.get('perfect_game')) and
        (game_data.get('current_inning') or 0) >= 6
    )
    if _fs_active_no_no and not _run_scored:
        _hdr_crop = canvas.crop((0, 0, 800, HEADER_H))
        canvas.paste(ImageOps.invert(_hdr_crop.convert('L')).convert('1'), (0, 0))
        draw = ImageDraw.Draw(canvas)

    # ---- SCORE DATA ---------------------------------------------------------
    away_runs = str(game_data.get('away_runs') or 0)
    home_runs = str(game_data.get('home_runs') or 0)
    away_hits = str(game_data.get('away_hits') or 0)
    home_hits = str(game_data.get('home_hits') or 0)
    away_errs = str(game_data.get('away_errors') or 0)
    home_errs = str(game_data.get('home_errors') or 0)

    _away_ahead = (game_data.get('away_runs') or 0) > (game_data.get('home_runs') or 0)
    _home_ahead = (game_data.get('home_runs') or 0) > (game_data.get('away_runs') or 0)

    def _draw_team_row(abbr, tid, row_y, runs, hits, errs, bold_score=False,
                       batting=False, abs_remaining=None, replay_remaining=None):
        """Draw team row."""
        nonlocal draw
        if use_logos:
            _lg = _logo_small(abbr, tid, size=LOGO_SZ)
            if _lg:
                _lw3, _lh3 = _lg.size
                _paste_logo(canvas, _lg,
                            (LOGO_X + (LOGO_SZ - _lw3) // 2,
                             row_y  + (TEAM_ROW_H - _lh3) // 2))
                draw = ImageDraw.Draw(canvas)
        _abbr_y = row_y + (TEAM_ROW_H - 56) // 2
        draw.text((ABBR_X,     _abbr_y), abbr, font=f56, fill=0)
        draw.text((ABBR_X + 1, _abbr_y), abbr, font=f56, fill=0)

        # ABS challenges — rectangles above abbreviation, starting at ABBR_X
        # filled = challenge available, empty outline = challenge used
        if abs_remaining is not None:
            _abs_max = game_data.get('abs_challenge_max') or 2
            _rw, _rh = 36, 10
            _r_gap   = 4
            _r_top   = _abbr_y - _rh + 5
            _r_left  = ABBR_X
            if _r_top >= row_y:
                for i in range(_abs_max):
                    _rx0, _ry0 = _r_left, _r_top
                    _rx1, _ry1 = _rx0 + _rw, _ry0 + _rh
                    if i < abs_remaining:   # filled = available
                        draw.rectangle([_rx0, _ry0, _rx1, _ry1], fill=0)
                    else:                   # outline only = used
                        draw.rectangle([_rx0, _ry0, _rx1, _ry1], outline=0, width=2)
                    _r_left += _rw + _r_gap

        # Manager replay challenge — rectangle below abbreviation, starting at ABBR_X
        # filled = challenge available, empty outline = used
        if replay_remaining is not None:
            _rw, _rh = 36, 10
            _r_top   = _abbr_y + 56 + 3
            _r_left  = ABBR_X
            if _r_top + _rh <= row_y + TEAM_ROW_H:  # pragma: no cover
                if replay_remaining > 0:    # filled = has challenge
                    draw.rectangle([_r_left, _r_top, _r_left + _rw, _r_top + _rh], fill=0)
                else:                       # outline = used
                    draw.rectangle([_r_left, _r_top, _r_left + _rw, _r_top + _rh], outline=0, width=2)

        _ry = row_y + (TEAM_ROW_H - 72) // 2
        for val, cx, bold in ((runs, R_CX, bold_score), (hits, H_CX, False), (errs, E_CX, False)):
            _vw = int(f72.getlength(val))
            _vx = cx - _vw // 2
            draw.text((_vx,     _ry), val, font=f72, fill=0)
            if bold:
                draw.text((_vx + 1, _ry), val, font=f72, fill=0)

    _away_abs = game_data.get('away_challenges_remaining')
    _home_abs = game_data.get('home_challenges_remaining')
    _away_rep = game_data.get('away_replay_remaining')
    _home_rep = game_data.get('home_replay_remaining')

    _draw_team_row(away_abbr, away_id, AWAY_Y, away_runs, away_hits, away_errs,
                   bold_score=_away_ahead, batting=(_inn_state == 'Top'),
                   abs_remaining=_away_abs, replay_remaining=_away_rep)
    _draw_team_row(home_abbr, home_id,  HOME_Y, home_runs, home_hits, home_errs,
                   bold_score=_home_ahead, batting=(_inn_state == 'Bottom'),
                   abs_remaining=_home_abs, replay_remaining=_home_rep)

    # ---- SAVE SITUATION badge (upper-right, just below header line) ---------
    if game_data.get('save_situation'):
        _sv_w = int(f28.getlength('SV'))
        _sv_x = 800 - _sv_w - 8
        _sv_y = HEADER_H + 3
        draw.text((_sv_x,     _sv_y), 'SV', font=f28, fill=0)
        draw.text((_sv_x + 1, _sv_y), 'SV', font=f28, fill=0)

    # ---- BASES (right side, spanning both score rows) -----------------------
    _hi_third  = isinstance(game_data.get('runner_on_third'),  str)
    _hi_second = isinstance(game_data.get('runner_on_second'), str)
    _hi_first  = isinstance(game_data.get('runner_on_first'),  str)

    _b3 = (DIAMOND_CX - BASE_DIST, DIAMOND_CY)
    _b2 = (DIAMOND_CX,             DIAMOND_CY - BASE_DIST)
    _b1 = (DIAMOND_CX + BASE_DIST, DIAMOND_CY)
    # home plate removed

    canvas = draw_diamond(canvas, _b3, BASE_SZ, _hi_third,  outline_width=BASE_OW)
    canvas = draw_diamond(canvas, _b2, BASE_SZ, _hi_second, outline_width=BASE_OW)
    canvas = draw_diamond(canvas, _b1, BASE_SZ, _hi_first,  outline_width=BASE_OW)
    draw   = ImageDraw.Draw(canvas)

    # Runner jersey numbers in white inside filled bases
    for _bfill, _bc, _bkey in (
        (_hi_third,  _b3, 'runner_third_number'),
        (_hi_second, _b2, 'runner_second_number'),
        (_hi_first,  _b1, 'runner_first_number'),
    ):
        if _bfill:
            _raw  = game_data.get(_bkey)
            _bnum = str(_raw) if _raw is not None else ''
            if _bnum:
                draw_tight_number(draw, _bc[0], _bc[1], _bnum, f52, 255)

    # ---- OUTS circles (right side, moved up, bigger) ------------------------
    _outs = game_data.get('num_of_outs') or 0
    _ogap = 8
    _otw  = 3 * (2 * O_R) + 2 * _ogap
    _oxs  = DIAMOND_CX - _otw // 2
    _ocy  = OUTS_Y_TOP + O_R + 4
    for i in range(3):
        _ocx = _oxs + O_R + i * (2 * O_R + _ogap)
        canvas = draw_circle(canvas, (_ocx, _ocy), O_R, i < _outs, outline_width=2)
    draw = ImageDraw.Draw(canvas)

    # ---- DIVIDER (full width, thick) ----------------------------------------
    draw.line((0, DIV_Y, 799, DIV_Y), fill=0, width=2)

    # ---- BOTTOM SITUATION AREA ----------------------------------------------
    _batter_names = [nm for nm in [
        _last_name(game_data.get('next_batter_1') or game_data.get('current_hitter') or ''),
        _last_name(game_data.get('next_batter_2') or game_data.get('due_up')         or ''),
        _last_name(game_data.get('next_batter_3') or game_data.get('in_hole')        or ''),
    ] if nm]
    _pc_raw = (game_data.get('sub_event') or '')[3:].strip() if _pitching_change else ''
    _pit_nm = _pc_raw or _last_name(
        game_data.get('next_pitcher') or game_data.get('current_pitcher') or ''
    )

    if _between_innings or (_pitching_change and not _mid_inning_pc):
        _draw_between_innings(draw, game_data, away_abbr, home_abbr, _cur_inn,
                              _pit_nm, _batter_names, SIT_Y, DIV_Y, WIN_PCT_Y)
    else:
        canvas, draw = _draw_active_pitch(canvas, draw, game_data, f42, f36, B_R, C_GAP,
                                          SIT_Y, WIN_PCT_Y, _mid_inning_pc)

    canvas, draw = _draw_win_pct_bar(canvas, draw, game_data,
                                     away_abbr, away_id, home_abbr, home_id,
                                     WIN_PCT_Y, WIN_PCT_H, f36, f14, use_logos)

    return canvas


def draw_featured_game_fullscreen(game_data, team_data, config=None):
    """Enlarge a single scoreboard cell while preserving its 1:1 aspect ratio.

    The cell is scaled to fill the content area (inside the standings chrome)
    uniformly, then the wildcard header and standings sidebars are drawn on top
    exactly as they appear in the normal scoreboard view.
    """
    if config is None:
        config = load_yaml_file('config.yaml')

    _ds = game_data.get('detailed_state', '')
    _is_live = _ds in ('In Progress', 'Player challenge', 'Manager challenge')

    # Live game: custom full-screen layout (no sidebars, R/H/E + bases)
    if _is_live:
        return draw_live_fullscreen_game(game_data, team_data, config)

    use_logos   = config.get('use_team_logos', False)
    logo_offset = config.get('small_logo_x_offset', 2)
    win_prob    = config.get('scoreboard_win_probability', False)
    league_mode = config.get('league_mode', 'mlb')

    # Scale game cell to fill the content height at integer scale (3×).
    # Center the 405px box content (135*3) horizontally so the 45px dead zone in the
    # cell image is split ~22px on each side, giving equal-width sidebars.
    CELL   = 150
    AREA_H = 480 - _WC_STRIP_H       # 450 px
    SCALED = (AREA_H // CELL) * CELL  # 450 px at scale 3
    _scale = SCALED // CELL           # 3
    _box_w = 135 * _scale             # 405 px — where draw_box's horizontal line ends
    paste_x = (800 - _box_w) // 2    # 197 — centers box content in the display
    paste_y = _WC_STRIP_H            # 30

    # Build streak_map from standings so L10/streak show in pre-game boxes
    standings_data = load_json_file('standings.json')
    _streak_map = {}
    if standings_data:
        for _div_teams in standings_data.get('standings', {}).values():
            for _t in _div_teams:
                _tid = str(_t.get('team_id', ''))
                if _tid:
                    _streak_map[_tid] = {
                        'streak': _t.get('streak'),
                        'l10_wins': _t.get('last_ten_wins'),
                        'l10_losses': _t.get('last_ten_losses'),
                    }

    # Render at full target resolution — no upscaling needed, fonts/logos are native size
    cell = Image.new('L', (SCALED, SCALED), 255)
    cell = draw_box(cell, 0, 0, game_data, team_data,
                    use_logos=use_logos, logo_x_offset=logo_offset,
                    show_win_prob=win_prob, show_winner_logo=False,
                    streak_map=_streak_map, scale=_scale)
    scaled_cell = cell.point(lambda p: 0 if p < 128 else 255).convert('1')

    # Overlay winner ghost rendered natively at SCALED px — no upscaling artifacts.
    # lightness=215 → ~15% dot density: recognisable watermark that doesn't obscure text.
    if use_logos and game_data.get('detailed_state') in ('Final', 'Game Over', 'Final: Tied'):
        abbr_map = team_data.get('team_abbreviation', {})
        winner_abbr = winner_id = None
        if game_data.get('away_team_is_winner'):
            winner_abbr = abbr_map.get(str(game_data.get('away_team_id', '')))
            winner_id   = str(game_data.get('away_team_id', ''))
        elif game_data.get('home_team_is_winner'):
            winner_abbr = abbr_map.get(str(game_data.get('home_team_id', '')))
            winner_id   = str(game_data.get('home_team_id', ''))
        if winner_abbr and winner_id:
            sf = float(_scale)
            GHOST_SZ = round(110 * sf)
            ghost = _logo_ghost(winner_abbr, winner_id, size=GHOST_SZ, lightness=215)
            if ghost:
                gw, gh = ghost.size
                gx = (round(135 * sf) - gw) // 2
                gy = round(20 * sf) + (round(110 * sf) - gh) // 2
                _paste_logo(scaled_cell, ghost, (gx, gy))

    canvas = Image.new('1', (800, 480), 255)
    canvas.paste(scaled_cell, (paste_x, paste_y))

    # Sidebars: left = x=0..paste_x-1, right = x=(paste_x+_box_w)..799
    # Both widths are ~197-198px so logos are the same size on each side.
    _left_sb_w  = paste_x             # 197
    _right_sb_x = paste_x + _box_w   # 602
    _right_sb_w = 800 - _right_sb_x  # 198
    _sb_logo_sz = 52

    # Overlay wildcard/bracket header and standings sidebars (skipped for live games)
    if not _is_live:
        # See generate_image.py for why this checks actual bracket content
        # rather than just the (now default-True) config flag.
        _bracket = None
        if config.get('show_playoff_bracket', True) and league_mode != 'aaa':
            _candidate = load_json_file('playoff_bracket.json')
            if _candidate and _candidate.get('series') and _candidate.get('season') == datetime.now().year:
                _bracket = _candidate

        if _bracket:
            canvas = draw_playoff_bracket_header(canvas, _bracket)
        elif standings_data and 'standings' in standings_data and \
                config.get('show_wildcard_standings', False) and league_mode != 'aaa':
            wildcard_data = derive_wildcard_from_standings(standings_data)
            canvas = draw_wildcard_header(canvas, wildcard_data)
    if not _is_live and standings_data and 'standings' in standings_data:
        if config.get('show_standings_sidebar', False):
            canvas = draw_standings_sidebar_fullscreen(
                canvas, standings_data, team_data, side='left', league_mode=league_mode,
                x_anchor=0, sidebar_w=_left_sb_w, logo_sz=_sb_logo_sz)
            canvas = draw_standings_sidebar_fullscreen(
                canvas, standings_data, team_data, side='right', league_mode=league_mode,
                x_anchor=_right_sb_x, sidebar_w=_right_sb_w, logo_sz=_sb_logo_sz)

    # Game-state-specific header label centered in the top strip.
    # 4 states: Scheduled, Finished, Postponed/Cancelled, other (fallback).
    # Each state has its own set of rotating candidates.
    # Skipped entirely when the bracket fills the whole strip.
    if not _bracket:
        _state_candidates = []
        _ds_now = game_data.get('detailed_state', '')
        _scheduled_states = {'Scheduled', 'Pre-Game', 'Warmup', 'Delayed Start', 'Delayed'}
        _final_states = {'Final', 'Game Over', 'Final: Tied'}
        _postponed_states = {'Postponed', 'Cancelled', 'Cancelled: Rain', 'Suspended', 'Suspended: Rain'}

        if _ds_now in _scheduled_states:
            # Scheduled: series context → venue → TV channel → game time
            _s = _series_display_str(game_data)
            if _s:
                _state_candidates.append(_s)
            _v = _clean_venue_name(game_data.get('venue') or '')
            if _v:
                _state_candidates.append(_v)
            _tv = (game_data.get('tv_channel') or '').strip()
            if _tv:
                _state_candidates.append(_tv)
            _gt = (game_data.get('game_date') or '').strip()
            if _gt:
                # parse ISO datetime → "7:05 PM" local display
                try:
                    import datetime as _dt_mod
                    _gdt = _dt_mod.datetime.fromisoformat(_gt.replace('Z', '+00:00'))
                    _state_candidates.append(_gdt.astimezone().strftime('%-I:%M %p'))
                except Exception:
                    pass

        elif _ds_now in _final_states or _ds_now.startswith('Completed Early'):
            # Finished: series result → WP → LP → SV
            _s = _series_display_str(game_data)
            if _s:
                _state_candidates.append(_s)
            _wp = _last_name(game_data.get('winner_name') or '')
            if _wp:
                _state_candidates.append(f'WP: {_wp}')
            _lp = _last_name(game_data.get('loser_name') or '')
            if _lp:
                _state_candidates.append(f'LP: {_lp}')
            _sv = _last_name(game_data.get('saver_name') or '')
            if _sv:
                _state_candidates.append(f'SV: {_sv}')

        elif _ds_now in _postponed_states:
            # Postponed/Cancelled: status label → reason → venue
            _ppd_lbl = 'POSTPONED' if 'Postponed' in _ds_now else 'CANCELLED'
            _state_candidates.append(_ppd_lbl)
            _reason = (game_data.get('postpone_reason') or '').strip()
            if _reason:
                _state_candidates.append(_reason)
            _v = _clean_venue_name(game_data.get('venue') or '')
            if _v:
                _state_candidates.append(_v)

        else:
            # Fallback for any unlisted state
            _s = _series_display_str(game_data)
            if _s:
                _state_candidates.append(_s)
            _v = _clean_venue_name(game_data.get('venue') or '')
            if _v:
                _state_candidates.append(_v)

        if _state_candidates:
            _rot_mins = max(config.get('overflow_ticker_rotation_minutes', 2), 1)
            _block = int(_time_feat.time() // (_rot_mins * 60))
            _state_label = _state_candidates[_block % len(_state_candidates)]
            _show_wc = config.get('show_wildcard_standings', False)
            _MAX_LABEL_W = 151 if _show_wc else (_box_w - 8)
            _center_x = 400
            _hdr_draw = ImageDraw.Draw(canvas)
            for _fsize in (16, 14, 11, 9):
                _f = _get_font(_fsize)
                if int(_f.getlength(_state_label)) <= _MAX_LABEL_W:
                    _lw = int(_f.getlength(_state_label))
                    _lx = _center_x - _lw // 2
                    _ly = max(0, (_WC_STRIP_H - _fsize) // 2)
                    _hdr_draw.text((_lx,     _ly), _state_label, font=_f, fill=0)
                    _hdr_draw.text((_lx + 1, _ly), _state_label, font=_f, fill=0)
                    break

    return canvas
