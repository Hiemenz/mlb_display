from PIL import Image, ImageDraw

from image_assets import _get_font, _logo_small
import time as _time

from util import load_json_file, save_off_results

_AL_DIV_ORDER = [
    'American League East',
    'American League Central',
    'American League West',
]
_NL_DIV_ORDER = [
    'National League East',
    'National League Central',
    'National League West',
]
_SIDEBAR_LOGO_SIZE = 20
_SIDEBAR_ROW_Y     = [25, 175, 325]   # y start for each division row (matches grid row spacing)
_SIDEBAR_ROW_H     = 150              # height per division section (grid row spacing)
_SIDEBAR_VERTICAL_PADDING = 5


# Wildcard header strip — aligned directly over the score boxes (x=32..767)
# Corners (x=0..31 and x=768..799) are left as dead space for the sidebar logos.
_WC_BOX_X_START = 32                              # matches x_start in draw_out_of_town_score_board
_WC_BOX_X_END   = 767                             # right edge of last box column (632+135)
_WC_MID         = (_WC_BOX_X_START + _WC_BOX_X_END) // 2   # = 399
_WC_SLOT_W      = 24                                        # px per slot (2px padding around 20px logo)
_WC_STRIP_H     = 30                              # matches y_start of boxes
_WC_LOGO_SZ     = _SIDEBAR_LOGO_SIZE              # same 20px as the sidebar

_AL_DIVISIONS = ['American League East', 'American League Central', 'American League West']
_NL_DIVISIONS = ['National League East', 'National League Central', 'National League West']

_WC_WILDCARD_SPOTS = 3   # number of wildcard playoff berths per league
_WC_MAX_TEAMS      = 12  # max eligible per league (15 teams - 3 division leaders)


def derive_wildcard_from_standings(standings_data):
    """Build {'AL': [...], 'NL': [...]} from standings.json.

    Collects all non-division-leader teams per league, sorts by league_rank
    (overall AL/NL rank already accounts for wildcard position correctly).
    Returns all eligible wildcard teams (max 12: 15 teams minus 3 division leaders).
    Each entry: {'abbr': str, 'team_id': str, 'gb': str}.
    """
    abbr_map = standings_data.get('team_abbreviation', {})
    divisions = standings_data.get('standings', {})
    result = {}

    for league_key, div_names in (('AL', _AL_DIVISIONS), ('NL', _NL_DIVISIONS)):
        teams = []
        for div in div_names:
            for t in divisions.get(div, []):
                if str(t.get('divisionRank', '')) == '1':
                    continue  # skip division leaders — they aren't competing for the wildcard
                team_id = str(t.get('team_id', ''))
                abbr = abbr_map.get(team_id, t.get('team_name', '???')[:3].upper())
                try:
                    rank = int(t.get('league_rank', 999))
                except (ValueError, TypeError):
                    rank = 999
                teams.append({
                    'abbr': abbr,
                    'team_id': team_id,
                    'gb': t.get('wild_card_games_back') or '-',
                    'rank': rank,
                })
        teams.sort(key=lambda t: t['rank'])
        result[league_key] = teams  # all eligible, no cap

    return result


def draw_wildcard_header(Himage, wildcard_data):
    """Draw a compact wildcard standings strip across the top of the display (y=0..30).

    AL wildcard (all eligible, up to 12) left-to-right in the left half, rank 1 at left edge.
    NL wildcard (all eligible, up to 12) right-to-left in the right half, rank 1 at right edge.
    A rounded rectangle is drawn around the top-3 wildcard leaders on each side.
    Falls back to 3-letter abbreviation (font9) when no logo is available.
    """
    draw = ImageDraw.Draw(Himage)
    font = _get_font(9)

    def _draw_slot(slot_x, team):
        abbr    = (team.get('abbr') or '???')[:4]
        team_id = str(team.get('team_id', ''))

        logo = _logo_small(abbr, team_id, size=_WC_LOGO_SZ)
        if logo is not None:
            lw, lh = logo.size
            logo_x = slot_x + (_WC_SLOT_W - lw) // 2
            logo_y = (_WC_STRIP_H - lh) // 2
            Himage.paste(logo, (logo_x, logo_y))
        else:
            abbr_w = int(font.getlength(abbr))
            draw.text((slot_x + (_WC_SLOT_W - abbr_w) // 2, (_WC_STRIP_H - 9) // 2), abbr, font=font, fill=0)

    al_teams = wildcard_data.get('AL', [])[:_WC_MAX_TEAMS]
    nl_teams = wildcard_data.get('NL', [])[:_WC_MAX_TEAMS]

    # AL: rank 1 at left box edge (x=32), higher ranks toward center
    for i, team in enumerate(al_teams):
        _draw_slot(_WC_BOX_X_START + i * _WC_SLOT_W, team)

    # NL: rank 1 at right box edge (x=767), higher ranks toward center
    for i, team in enumerate(nl_teams):
        _draw_slot(_WC_BOX_X_END - (i + 1) * _WC_SLOT_W, team)

    # Draw a rounded box around the wildcard leaders (top _WC_WILDCARD_SPOTS per league)
    n_al = min(len(al_teams), _WC_WILDCARD_SPOTS)
    n_nl = min(len(nl_teams), _WC_WILDCARD_SPOTS)

    if n_al > 0:
        box_x0 = _WC_BOX_X_START
        box_x1 = _WC_BOX_X_START + n_al * _WC_SLOT_W
        try:
            draw.rounded_rectangle([box_x0, 1, box_x1, _WC_STRIP_H - 2], radius=3, outline=0, width=1)
        except AttributeError:
            draw.rectangle([box_x0, 1, box_x1, _WC_STRIP_H - 2], outline=0, width=1)

    if n_nl > 0:
        box_x0 = _WC_BOX_X_END - n_nl * _WC_SLOT_W
        box_x1 = _WC_BOX_X_END
        try:
            draw.rounded_rectangle([box_x0, 1, box_x1, _WC_STRIP_H - 2], radius=3, outline=0, width=1)
        except AttributeError:
            draw.rectangle([box_x0, 1, box_x1, _WC_STRIP_H - 2], outline=0, width=1)

    return Himage


def _aaa_divisions(standings_data, side):
    """Return ordered IL (left) or PCL (right) division names from standings data."""
    all_divs = [d for d in standings_data.get('standings', {}).keys() if d]
    if side == 'left':
        divs = sorted(d for d in all_divs if 'International' in d)
    else:
        divs = sorted(d for d in all_divs if 'Pacific' in d)
    # Prefer East → South → West order (alphabetical happens to match)
    return divs


def draw_standings_sidebar(Himage, standings_data, team_data, side='left', league_mode='mlb'):
    """Draw a vertical strip of division-standings logos on the left or right edge.

    MLB: left=AL divisions, right=NL divisions.
    AAA: left=IL divisions, right=PCL divisions.
    """
    if league_mode == 'aaa':
        divisions = _aaa_divisions(standings_data, side)
    else:
        divisions = _AL_DIV_ORDER if side == 'left' else _NL_DIV_ORDER
    abbr_map  = {**standings_data.get('team_abbreviation', {}),
                 **team_data.get('team_abbreviation', {})}

    logo_x = (32 - _SIDEBAR_LOGO_SIZE) // 2 if side == 'left' else (800 - 32) + (32 - _SIDEBAR_LOGO_SIZE) // 2
    sep_x0, sep_x1 = (0, 31) if side == 'left' else (768, 800)
    # Line drawn on the outer edge of the logo (between logo and display edge)
    line_x = logo_x - 4 if side == 'left' else logo_x + _SIDEBAR_LOGO_SIZE + 3

    draw = ImageDraw.Draw(Himage)

    # Build previous-rank lookup from standings_prev.json for movement indicators
    # Stores (rank, wins, losses) so tied teams that didn't change record are not flagged.
    prev_data = {}
    prev_rank = {}
    try:
        _pd = load_json_file('standings_prev.json')
        if _pd:
            prev_data = _pd
            for _teams in prev_data.get('standings', {}).values():
                for _t in _teams:
                    _tid = str(_t.get('team_id', ''))
                    _r = _t.get('divisionRank')
                    if _tid and _r is not None:
                        try:
                            prev_rank[_tid] = (
                                int(_r),
                                int(_t.get('league_record_wins') or 0),
                                int(_t.get('league_record_losses') or 0),
                            )
                        except (ValueError, TypeError):
                            pass
    except Exception:
        pass

    # Load 20-hour movement persistence state: {team_id: unix_timestamp_of_last_move}
    _now_ts = _time.time()
    _20h_secs = 20 * 3600
    _movement_data = load_json_file('standings_movement.json') or {}
    _movement_updated = False

    for row_idx, div_name in enumerate(divisions):
        teams = standings_data.get('standings', {}).get(div_name, [])
        teams = sorted(teams, key=lambda t: int(t.get('divisionRank', 99)))
        y_section = _SIDEBAR_ROW_Y[row_idx]
        slot_h    = (_SIDEBAR_ROW_H - (_SIDEBAR_VERTICAL_PADDING * 2)) // 5

        # --- Rank + record change detection ---
        # A team is a mover when its rank changed AND its record changed.
        movers = set()
        for team in teams[:5]:
            tid = str(team.get('team_id', ''))
            if tid not in prev_rank:
                continue
            cur_rank = int(team.get('divisionRank', 99))
            prev_r, prev_w, prev_l = prev_rank[tid]
            cur_w = int(team.get('league_record_wins') or 0)
            cur_l = int(team.get('league_record_losses') or 0)
            if cur_rank != prev_r and (cur_w != prev_w or cur_l != prev_l):
                movers.add(tid)

        # Any team displaced by a mover also changed rank — mark it too.
        if movers:
            for team in teams[:5]:
                tid = str(team.get('team_id', ''))
                if tid not in prev_rank or tid in movers:
                    continue
                cur_rank = int(team.get('divisionRank', 99))
                prev_r, _, _ = prev_rank[tid]
                if cur_rank != prev_r:
                    movers.add(tid)

        # --- Tie-break detection: teams that were tied and now aren't ---
        # When two teams share a record, they're indistinguishable in the standings.
        # The moment one pulls ahead, both are considered movers.
        prev_div_teams = prev_data.get('standings', {}).get(div_name, [])
        prev_wl_by_tid = {}
        for _pt in prev_div_teams:
            _tid = str(_pt.get('team_id', ''))
            try:
                prev_wl_by_tid[_tid] = (
                    int(_pt.get('league_record_wins') or 0),
                    int(_pt.get('league_record_losses') or 0),
                )
            except (ValueError, TypeError):
                pass

        cur_wl_by_tid = {}
        for _ct in teams[:5]:
            _tid = str(_ct.get('team_id', ''))
            try:
                cur_wl_by_tid[_tid] = (
                    int(_ct.get('league_record_wins') or 0),
                    int(_ct.get('league_record_losses') or 0),
                )
            except (ValueError, TypeError):
                pass

        for i in range(len(teams[:5]) - 1):
            tid1 = str(teams[i].get('team_id', ''))
            tid2 = str(teams[i + 1].get('team_id', ''))
            if tid1 in prev_wl_by_tid and tid2 in prev_wl_by_tid:
                was_tied = prev_wl_by_tid[tid1] == prev_wl_by_tid[tid2]
                is_tied  = cur_wl_by_tid.get(tid1) == cur_wl_by_tid.get(tid2)
                if was_tied and not is_tied:
                    movers.add(tid1)
                    movers.add(tid2)

        # Record timestamps for newly detected movers
        for tid in movers:
            _movement_data[tid] = _now_ts
            _movement_updated = True

        # Show indicator for current movers AND any move within the last 20 hours
        display_movers = set(movers)
        for team in teams[:5]:
            tid = str(team.get('team_id', ''))
            ts = _movement_data.get(tid)
            if ts is not None:
                try:
                    if _now_ts - float(ts) < _20h_secs:
                        display_movers.add(tid)
                except (ValueError, TypeError):
                    pass

        for slot_idx, team in enumerate(teams[:5]):
            team_id = str(team.get('team_id', ''))
            abbr    = abbr_map.get(team_id, f'T{team_id}')
            logo_y  = y_section + _SIDEBAR_VERTICAL_PADDING + slot_idx * slot_h

            logo_img = _logo_small(abbr, team_id, size=_SIDEBAR_LOGO_SIZE)
            if logo_img is not None:
                lw, lh = logo_img.size
                paste_x = logo_x + (_SIDEBAR_LOGO_SIZE - lw) // 2
                paste_y = logo_y + (_SIDEBAR_LOGO_SIZE - lh) // 2
                Himage.paste(logo_img, (paste_x, paste_y))
            else:
                font = _get_font(9)
                tw = int(font.getlength(abbr[:3]))
                draw.text((logo_x + (_SIDEBAR_LOGO_SIZE - tw) // 2, logo_y + 8), abbr[:3], font=font, fill=0)

            if team_id in display_movers:
                draw.line(
                    (line_x, logo_y, line_x, logo_y + _SIDEBAR_LOGO_SIZE - 1),
                    fill=0, width=2,
                )

            # Clinch indicator: box around the logo slot
            # 'y' = division clinched (thin), 'z' = #1 seed/home field (thick)
            clinch = (team.get('clinch_indicator') or '').lower()
            if clinch in ('y', 'z'):
                box_w = 2 if clinch == 'z' else 1
                draw.rectangle(
                    [logo_x, logo_y, logo_x + _SIDEBAR_LOGO_SIZE - 1, logo_y + _SIDEBAR_LOGO_SIZE - 1],
                    outline=0, width=box_w,
                )

            # Always draw --- between consecutive slots with the same W-L record (tied teams)
            if slot_idx + 1 < 5 and slot_idx + 1 < len(teams):
                nxt = teams[slot_idx + 1]
                cur_wl = (int(team.get('league_record_wins') or 0), int(team.get('league_record_losses') or 0))
                nxt_wl = (int(nxt.get('league_record_wins') or 0),  int(nxt.get('league_record_losses') or 0))
                if cur_wl == nxt_wl:
                    gap_y      = logo_y + _SIDEBAR_LOGO_SIZE + (slot_h - _SIDEBAR_LOGO_SIZE) // 2
                    dash_w, gap_w = 4, 2
                    dash_start = logo_x + (_SIDEBAR_LOGO_SIZE - (3 * dash_w + 2 * gap_w)) // 2
                    for d in range(3):
                        x0 = dash_start + d * (dash_w + gap_w)
                        draw.line((x0, gap_y, x0 + dash_w - 1, gap_y), fill=0, width=1)

    # Persist movement timestamps so indicators survive across render cycles
    if _movement_updated:
        save_off_results(_movement_data, 'standings_movement')

    return Himage
