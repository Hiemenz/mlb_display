#!/usr/bin/env python3
"""Splice the new draw_live_fullscreen_game (v4) into generate_image.py."""

NEW_FUNC = r'''def draw_live_fullscreen_game(game_data, team_data, config=None):
    """Full 800x480 canvas for a live (In Progress) featured game.

    Layout v4
    ---------
    y=0..91    Header  : inning (f80, left)  matchup (f56, right)  [thick line below]
    y=92..111  R / H / E column labels (f14)
    y=112..191 Away row : logo  abbr  R  H  E  |  bases diamond (right, spans rows)
    y=192..271 Home row : logo  abbr  R  H  E  |
    y=272..307 [blank left]  |  outs circles (right, under bases)
    y=308      Divider line
    y=309..479 Bottom :
        Live           : B/S/O circles + pitch info + last event (f36) + pitcher/batter (f28)
        Between-innings: last event (f36) + due-up batters (f24) + pitcher (f24)
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
    f22  = _get_font(22)    # runner jersey numbers inside bases (2× for fullscreen)
    f14  = _get_font(14)    # pitch info / column labels
    f24  = _get_font(24)    # between-innings batter/pitcher names
    f28  = _get_font(28)    # pitcher / batter line (bottom, live)
    f36  = _get_font(36)    # last event  (prominent)
    f42  = _get_font(42)    # BSO labels + team abbreviations
    f56  = _get_font(56)    # matchup header (4x f14)
    f72  = _get_font(72)    # R / H / E values
    f80  = _get_font(80)    # inning text (4x f20)

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

    _between_innings = _inn_state in ('Middle', 'End')
    _pitching_change = (game_data.get('sub_event') or '').startswith('PC:')

    # ---- Layout constants ----------------------------------------------------
    HEADER_H   = 92           # big header (f80 inning + breathing room)
    LABEL_H    = 20           # R/H/E column label row
    TEAM_ROW_H = 80           # away/home score rows
    AWAY_Y     = HEADER_H + LABEL_H          # 112
    HOME_Y     = AWAY_Y  + TEAM_ROW_H        # 192
    OUTS_Y_TOP = HOME_Y  + TEAM_ROW_H        # 272  (outs circles here)
    OUTS_H     = 36
    DIV_Y      = OUTS_Y_TOP + OUTS_H         # 308
    SIT_Y      = DIV_Y + 1                   # 309

    # Team row layout
    LOGO_SZ  = 72
    LOGO_X   = 2
    ABBR_X   = LOGO_X + LOGO_SZ + 6         # 80

    # R/H/E column centres
    R_CX = 240
    H_CX = 360
    E_CX = 480

    # Bases: right side, centre at the boundary between the two score rows
    DIAMOND_CX = 645
    DIAMOND_CY = HOME_Y                      # 192
    BASE_DIST  = 52
    BASE_SZ    = 24
    BASE_OW    = 3

    # BSO circles (bottom half)
    B_R   = 12
    O_R   = 16
    C_GAP = 5

    # ---- Last-event helper ---------------------------------------------------
    def _build_last_event():
        _sub_ev = (game_data.get('sub_event') or '').strip()
        _lp     = game_data.get('last_play') or ''
        _raw    = _sub_ev or _lp
        if not _raw:
            return ''
        _pd  = _abbr_play(_raw)
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

    # ---- HEADER (full-width thick line below) --------------------------------
    # Inning: f80, top-left
    draw.text((8, 4),  inning_str, font=f80, fill=0)
    draw.text((9, 4),  inning_str, font=f80, fill=0)   # pseudo-bold

    # Matchup + date: f56, right-aligned, vertically centred in header
    _gd_str   = (game_data.get('game_date') or '')[:10]
    _date_lbl = ''
    if _gd_str:
        try:
            _gd_dt    = datetime.strptime(_gd_str, '%Y-%m-%d')
            _date_lbl = _gd_dt.strftime('%b %-d')
        except Exception:
            _date_lbl = _gd_str
    _hdr_right = f'{away_abbr} @ {home_abbr}' + (f'  {_date_lbl}' if _date_lbl else '')
    _inn_w     = int(f80.getlength(inning_str)) + 8 + 16   # min gap after inning
    _hrw       = int(f56.getlength(_hdr_right))
    _hdr_x     = 800 - _hrw - 8
    if _hdr_x < _inn_w:
        # Fall back to teams-only if date makes it too wide
        _hdr_right = f'{away_abbr} @ {home_abbr}'
        _hrw       = int(f56.getlength(_hdr_right))
        _hdr_x     = 800 - _hrw - 8
    if _hdr_x > _inn_w:
        _hry = max(4, (HEADER_H - 56) // 2)
        draw.text((_hdr_x, _hry), _hdr_right, font=f56, fill=0)

    draw.line((0, HEADER_H - 1, 799, HEADER_H - 1), fill=0, width=2)

    # ---- R / H / E COLUMN LABELS --------------------------------------------
    for _lbl2, _cx2 in (('R', R_CX), ('H', H_CX), ('E', E_CX)):
        _lw2 = int(f14.getlength(_lbl2))
        draw.text((_cx2 - _lw2 // 2, HEADER_H + 3), _lbl2, font=f14, fill=0)

    # ---- SCORE DATA ---------------------------------------------------------
    away_runs = str(game_data.get('away_runs') or 0)
    home_runs = str(game_data.get('home_runs') or 0)
    away_hits = str(game_data.get('away_hits') or 0)
    home_hits = str(game_data.get('home_hits') or 0)
    away_errs = str(game_data.get('away_errors') or 0)
    home_errs = str(game_data.get('home_errors') or 0)

    _away_ahead = (game_data.get('away_runs') or 0) > (game_data.get('home_runs') or 0)
    _home_ahead = (game_data.get('home_runs') or 0) > (game_data.get('away_runs') or 0)

    def _draw_team_row(abbr, tid, row_y, runs, hits, errs, bold_score=False, batting=False):
        nonlocal draw, canvas
        if batting:
            _bi_r  = 7
            _bi_cy = row_y + TEAM_ROW_H // 2
            draw.ellipse([-_bi_r, _bi_cy - _bi_r, _bi_r, _bi_cy + _bi_r], fill=0)
        if use_logos:
            _lg = _logo_small(abbr, tid, size=LOGO_SZ)
            if _lg:
                _lw3, _lh3 = _lg.size
                _paste_logo(canvas, _lg,
                            (LOGO_X + (LOGO_SZ - _lw3) // 2,
                             row_y  + (TEAM_ROW_H - _lh3) // 2))
                draw = ImageDraw.Draw(canvas)
        _abbr_y = row_y + (TEAM_ROW_H - 42) // 2
        draw.text((ABBR_X,     _abbr_y), abbr, font=f42, fill=0)
        draw.text((ABBR_X + 1, _abbr_y), abbr, font=f42, fill=0)
        _ry = row_y + (TEAM_ROW_H - 72) // 2
        for val, cx, bold in ((runs, R_CX, bold_score), (hits, H_CX, False), (errs, E_CX, False)):
            _vw = int(f72.getlength(val))
            _vx = cx - _vw // 2
            draw.text((_vx,     _ry), val, font=f72, fill=0)
            if bold:
                draw.text((_vx + 1, _ry), val, font=f72, fill=0)

    _draw_team_row(away_abbr, away_id, AWAY_Y, away_runs, away_hits, away_errs,
                   bold_score=_away_ahead, batting=(_inn_state == 'Top'))
    _draw_team_row(home_abbr, home_id,  HOME_Y, home_runs, home_hits, home_errs,
                   bold_score=_home_ahead, batting=(_inn_state == 'Bottom'))

    # ---- BASES (right side, spanning both score rows) -----------------------
    _hi_third  = isinstance(game_data.get('runner_on_third'),  str)
    _hi_second = isinstance(game_data.get('runner_on_second'), str)
    _hi_first  = isinstance(game_data.get('runner_on_first'),  str)

    _b3 = (DIAMOND_CX - BASE_DIST, DIAMOND_CY)
    _b2 = (DIAMOND_CX,             DIAMOND_CY - BASE_DIST)
    _b1 = (DIAMOND_CX + BASE_DIST, DIAMOND_CY)
    _bH = (DIAMOND_CX,             DIAMOND_CY + BASE_DIST)   # home plate

    canvas = draw_diamond(canvas, _b3, BASE_SZ, _hi_third,  outline_width=BASE_OW)
    canvas = draw_diamond(canvas, _b2, BASE_SZ, _hi_second, outline_width=BASE_OW)
    canvas = draw_diamond(canvas, _b1, BASE_SZ, _hi_first,  outline_width=BASE_OW)
    canvas = draw_diamond(canvas, _bH, BASE_SZ - 8, False,  outline_width=BASE_OW)  # home plate
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
                _bnw = int(f22.getlength(_bnum))
                draw.text((_bc[0] - _bnw // 2, _bc[1] - 11), _bnum, font=f22, fill=255)

    # ---- OUTS circles (right side, under bases) -----------------------------
    _outs = game_data.get('num_of_outs') or 0
    _or   = 14
    _ogap = 8
    _otw  = 3 * (2 * _or) + 2 * _ogap    # total width = 100px
    _oxs  = DIAMOND_CX - _otw // 2       # x-start = 595
    _ocy  = OUTS_Y_TOP + _or + 4          # circle centres y
    for i in range(3):
        _ocx = _oxs + _or + i * (2 * _or + _ogap)
        canvas = draw_circle(canvas, (_ocx, _ocy), _or, i < _outs, outline_width=2)
    draw = ImageDraw.Draw(canvas)

    # ---- DIVIDER (full width, thick) ----------------------------------------
    draw.line((0, DIV_Y, 799, DIV_Y), fill=0, width=2)

    # ---- BOTTOM SITUATION AREA ----------------------------------------------
    _last_ev = _build_last_event()

    if _between_innings or _pitching_change:
        # ---- Between innings: last event  +  due-up batters  +  pitcher ----
        _by = SIT_Y + 8   # 317

        if _last_ev:
            draw.text((16, _by),     _last_ev, font=f36, fill=0)
            draw.text((17, _by),     _last_ev, font=f36, fill=0)
            _by += 40

        draw.line((16, _by, 420, _by), fill=0, width=1)
        _by += 10

        _batter_names = [
            _last_name(game_data.get('next_batter_1') or game_data.get('current_hitter') or ''),
            _last_name(game_data.get('next_batter_2') or game_data.get('due_up')         or ''),
            _last_name(game_data.get('next_batter_3') or game_data.get('in_hole')        or ''),
        ]
        _pc_raw = (game_data.get('sub_event') or '')[3:].strip() if _pitching_change else ''
        _pit_nm = _pc_raw or _last_name(
            game_data.get('next_pitcher') or game_data.get('current_pitcher') or ''
        )

        for _nm in _batter_names:
            if _nm and _by + 28 <= 476:
                draw.text((16, _by), _nm, font=f24, fill=0)
                _by += 28

        if _pit_nm and _by + 8 <= 476:
            draw.line((16, _by + 4, 320, _by + 4), fill=0, width=1)
            _by += 12
            if _by + 24 <= 476:
                draw.text((16, _by), _pit_nm, font=f24, fill=0)

    else:
        # ---- Active pitch: B/S/O  +  pitch info  +  last event  +  pitcher/batter ----

        _bso_y  = SIT_Y + 6    # 315  — top of BSO label text
        _bso_cy = _bso_y + 21  # 336  — circle centres (vertically centred in f42 cap-height)

        # Balls
        _bx = 16
        draw.text((_bx,     _bso_y), 'B', font=f42, fill=0)
        draw.text((_bx + 1, _bso_y), 'B', font=f42, fill=0)
        _bx += int(f42.getlength('B')) + 8
        _balls = game_data.get('balls') or 0
        for i in range(4):
            _cx = _bx + B_R
            canvas = draw_circle(canvas, (_cx, _bso_cy), B_R, i < _balls)
            _bx += 2 * B_R + C_GAP
        draw = ImageDraw.Draw(canvas)

        # Strikes
        _sx = _bx + 16
        draw.text((_sx,     _bso_y), 'S', font=f42, fill=0)
        draw.text((_sx + 1, _bso_y), 'S', font=f42, fill=0)
        _sx += int(f42.getlength('S')) + 8
        _strikes = game_data.get('strikes') or 0
        _scalls  = game_data.get('strike_calls', [])
        for i in range(2):
            _cx    = _sx + B_R
            _call  = _scalls[i] if i < len(_scalls) else None
            _swing = i < _strikes and _call in ('S', 'F')
            canvas = draw_circle(canvas, (_cx, _bso_cy), B_R, i < _strikes and not _swing)
            draw   = ImageDraw.Draw(canvas)
            if _swing:
                _ir = int(B_R * 0.8)
                draw.ellipse([_cx - _ir, _bso_cy - _ir, _cx + _ir, _bso_cy + _ir],
                             fill=0, outline=0)
            _sx += 2 * B_R + C_GAP

        # Outs
        _ox = _sx + 16
        draw.text((_ox,     _bso_y), 'O', font=f42, fill=0)
        draw.text((_ox + 1, _bso_y), 'O', font=f42, fill=0)
        _ox += int(f42.getlength('O')) + 8
        _outs2 = game_data.get('num_of_outs') or 0
        for i in range(3):
            _cx2 = _ox + O_R
            canvas = draw_circle(canvas, (_cx2, _bso_cy), O_R, i < _outs2, outline_width=2)
            _ox += 2 * O_R + C_GAP
        draw = ImageDraw.Draw(canvas)

        # Save situation badge
        if game_data.get('save_situation'):
            _sv_x = 800 - int(f28.getlength('SV')) - 16
            draw.text((_sv_x,     _bso_y + 6), 'SV', font=f28, fill=0)
            draw.text((_sv_x + 1, _bso_y + 6), 'SV', font=f28, fill=0)

        # Pitch info: count / speed / type  (f14, below circles)
        _lps = game_data.get('last_pitch_speed')
        _pt  = game_data.get('last_pitch_type', '')
        _pc  = game_data.get('pitch_count')
        _pitch_parts = []
        if _pc  is not None: _pitch_parts.append(f'{_pc}P')
        if _lps:             _pitch_parts.append(f'{int(_lps)}mph')
        if _pt:              _pitch_parts.append(_pt)
        if _pitch_parts:
            draw.text((16, _bso_y + 46), '  '.join(_pitch_parts), font=f14, fill=0)

        # Last event  (f36, prominent)
        _ev_y = _bso_y + 62   # 377
        if _last_ev:
            draw.text((16, _ev_y),     _last_ev, font=f36, fill=0)
            draw.text((17, _ev_y),     _last_ev, font=f36, fill=0)

        # Pitcher  (f28)
        _pb_y = _bso_y + 104  # 419
        _pitcher = _format_player_name(game_data.get('current_pitcher') or '')
        if _pitcher and _pb_y + 28 <= 478:
            draw.text((16, _pb_y), f'P: {_pitcher}', font=f28, fill=0)

        # Batter  (f28)
        _pb_y2  = _pb_y + 32  # 451
        _bh     = game_data.get('batter_hits')
        _ba     = game_data.get('batter_at_bats')
        _ba_str = f'({_bh}-{_ba})' if _bh is not None and _ba is not None else ''
        _ab_done = game_data.get('current_at_bat_complete', False)
        if _ab_done and not _is_game_effectively_over(game_data):
            _batter  = _format_player_name(
                game_data.get('due_up') or game_data.get('next_batter_1') or ''
            )
            _bat_lbl = 'Next'
        else:
            _batter  = _format_player_name(game_data.get('current_hitter') or '')
            _bat_lbl = 'AB'
        if _batter and _pb_y2 + 28 <= 478:
            draw.text((16, _pb_y2), f'{_bat_lbl}: {_batter}  {_ba_str}'.strip(), font=f28, fill=0)

    return canvas


'''

with open('src/generate_image.py', 'r', encoding='utf-8') as f:
    src = f.read()

MARKER_START = 'def draw_live_fullscreen_game('
MARKER_END   = 'def draw_featured_game_fullscreen('

start_idx = src.index(MARKER_START)
end_idx   = src.index(MARKER_END)

new_src = src[:start_idx] + NEW_FUNC + src[end_idx:]

with open('src/generate_image.py', 'w', encoding='utf-8') as f:
    f.write(new_src)

print('Splice complete.')
print(f'  Old function: {end_idx - start_idx} chars → replaced with {len(NEW_FUNC)} chars')
print(f'  New file length: {len(new_src)} chars')
