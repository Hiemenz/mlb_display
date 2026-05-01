from PIL import Image, ImageDraw

from image_assets import _get_font, _logo_small
from util import load_json_file

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


def draw_standings_sidebar(Himage, standings_data, team_data, side='left'):
    """Draw a vertical strip of division-standings logos on the left (AL) or right (NL) edge.

    Logos are 26px, ordered 1st place (top) to 5th place (bottom) within each
    division section. Three sections align with the three scoreboard game rows:
      section 0 = East   (y=30–180)
      section 1 = Central (y=180–330)
      section 2 = West   (y=330–480)

    side='left'  → AL divisions, logo_x=6  (centered in 32px left margin)
    side='right' → NL divisions, logo_x=774 (centered in 32px right margin)
    """
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
    prev_rank = {}
    try:
        prev_data = load_json_file('standings_prev.json')
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

    for row_idx, div_name in enumerate(divisions):
        teams = standings_data.get('standings', {}).get(div_name, [])
        teams = sorted(teams, key=lambda t: int(t.get('divisionRank', 99)))
        y_section = _SIDEBAR_ROW_Y[row_idx]
        slot_h    = (_SIDEBAR_ROW_H - (_SIDEBAR_VERTICAL_PADDING * 2)) // 5

        # Find team IDs whose rank genuinely changed (record moved, not just API tie-break).
        # Any team that actually changed record is a "mover"; its swap partner gets marked too
        # even if the partner's own record didn't change (e.g. Texas climbs past a team that
        # didn't play — that team's rank still changed).
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

        for slot_idx, team in enumerate(teams[:5]):
            team_id = str(team.get('team_id', ''))
            abbr    = abbr_map.get(team_id, f'T{team_id}')
            logo_y  = y_section + _SIDEBAR_VERTICAL_PADDING + slot_idx * slot_h

            logo_img = _logo_small(abbr, team_id, size=_SIDEBAR_LOGO_SIZE)
            if logo_img is not None:
                lw, lh = logo_img.size
                paste_x = logo_x + (_SIDEBAR_LOGO_SIZE - lw) // 2
                Himage.paste(logo_img, (paste_x, logo_y))
            else:
                font = _get_font(9)
                tw = int(font.getlength(abbr[:3]))
                draw.text((logo_x + (_SIDEBAR_LOGO_SIZE - tw) // 2, logo_y + 8), abbr[:3], font=font, fill=0)

            if team_id in movers:
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

            # Draw --- between tied consecutive slots (same W-L record)
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

        # Removed separator lines between division sections

    return Himage
