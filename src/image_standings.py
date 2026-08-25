import re
from PIL import ImageDraw

from image_assets import _get_font, _logo_small
import time as _time

from util import load_json_file, save_off_results
from image_utils import (
    division_rank, magic_or_elim_value, MAGIC_BASE, ELIM_THRESHOLD,
)

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
_WC_SLOT_W      = 24                                        # px per slot (2px padding around 20px logo)
_WC_STRIP_H     = 30                              # matches y_start of boxes
_WC_LOGO_SZ     = _SIDEBAR_LOGO_SIZE              # same 20px as the sidebar

_AL_DIVISIONS = ['American League East', 'American League Central', 'American League West']
_NL_DIVISIONS = ['National League East', 'National League Central', 'National League West']

# Fullscreen sidebar — 3 division columns side-by-side, full content-area height
_FS_SIDEBAR_W   = 175   # left sidebar width (= game cell paste_x); game cell = 450px
_FS_LOGO_SZ     = 44    # default logo size (fits in 58px col with 7px padding each side)

_WC_WILDCARD_SPOTS = 3   # number of wildcard playoff berths per league
_WC_MAX_TEAMS      = 12  # max eligible per league (15 teams - 3 division leaders)


def _wc_elim_badge(team_entry, wc3_wins, wc3_losses):
    """Badge text for a wildcard bubble team (outside the top-3 spots).

    Returns 'E{n}' when the elimination number is ≤ ELIM_THRESHOLD, else ''.
    wc3_wins / wc3_losses are the record of the team currently holding the
    3rd wildcard spot — the benchmark a bubble team must chase.
    """
    clinch = (team_entry.get('clinch_indicator') or '').strip().lower()
    if clinch == 'e':
        return 'OUT'
    if wc3_wins is None:
        return ''
    losses = team_entry.get('losses')
    if losses is None:
        return ''
    elim = MAGIC_BASE - wc3_wins - losses
    if elim <= 0:
        return 'OUT'
    if elim <= ELIM_THRESHOLD:
        return f'E{elim}'
    return ''


def derive_wildcard_from_standings(standings_data):
    """Build {'AL': [...], 'NL': [...]} from standings.json.

    Collects all non-division-leader teams per league, sorts by league_rank
    (overall AL/NL rank already accounts for wildcard position correctly).
    Returns all eligible wildcard teams (max 12: 15 teams minus 3 division leaders).
    Each entry: {'abbr': str, 'team_id': str, 'gb': str, 'elim_badge': str}.
    """
    abbr_map = standings_data.get('team_abbreviation', {})
    divisions = standings_data.get('standings', {})
    result = {}

    for league_key, div_names in (('AL', _AL_DIVISIONS), ('NL', _NL_DIVISIONS)):
        teams = []
        for div in div_names:
            for t in divisions.get(div, []):
                if division_rank(t, default=None) == 1:
                    continue  # skip division leaders — they aren't competing for the wildcard
                team_id = str(t.get('team_id', ''))
                abbr = abbr_map.get(team_id, t.get('team_name', '???')[:3].upper())
                try:
                    rank = int(t.get('league_rank', 999))
                except (ValueError, TypeError):
                    rank = 999
                wins = t.get('league_record_wins')
                losses = t.get('league_record_losses')
                try:
                    wins = int(wins) if wins is not None else None
                    losses = int(losses) if losses is not None else None
                except (ValueError, TypeError):
                    wins = losses = None
                teams.append({
                    'abbr': abbr,
                    'team_id': team_id,
                    'gb': t.get('wild_card_games_back') or '-',
                    'rank': rank,
                    'wins': wins,
                    'losses': losses,
                    'clinch_indicator': t.get('clinch_indicator') or '',
                })
        teams.sort(key=lambda t: t['rank'])

        # Compute elimination badges for bubble teams (rank 4+).
        # The benchmark is the team holding the 3rd wildcard spot.
        wc3 = teams[2] if len(teams) >= 3 else None
        wc3_wins = wc3['wins'] if wc3 else None
        wc3_losses = wc3['losses'] if wc3 else None
        for i, team in enumerate(teams):
            if i < _WC_WILDCARD_SPOTS:
                team['elim_badge'] = ''
            else:
                team['elim_badge'] = _wc_elim_badge(team, wc3_wins, wc3_losses)

        result[league_key] = teams  # all eligible, no cap

    return result


_WC_BADGE_H = 7   # px font height for elim badge; logo shrinks by this when badge shown

def draw_wildcard_header(Himage, wildcard_data):
    """Draw a compact wildcard standings strip across the top of the display (y=0..30).

    AL wildcard (all eligible, up to 12) left-to-right in the left half, rank 1 at left edge.
    NL wildcard (all eligible, up to 12) right-to-left in the right half, rank 1 at right edge.
    A rounded rectangle is drawn around the top-3 wildcard leaders on each side.
    Falls back to 3-letter abbreviation (font9) when no logo is available.
    Bubble teams (rank 4+) show an E# elimination badge below their slot when the
    number is ≤ ELIM_THRESHOLD (i.e. the race is tight enough to matter).
    """
    draw = ImageDraw.Draw(Himage)
    font = _get_font(9)
    font_badge = _get_font(_WC_BADGE_H)

    def _draw_slot(slot_x, team):
        """Draw one wildcard slot with optional elimination badge."""
        abbr    = (team.get('abbr') or '???')[:4]
        team_id = str(team.get('team_id', ''))
        badge   = team.get('elim_badge', '')

        # When a badge is present, shrink the logo to leave room at the bottom.
        logo_sz  = _WC_LOGO_SZ - _WC_BADGE_H if badge else _WC_LOGO_SZ
        logo_top = 1 if badge else (_WC_STRIP_H - _WC_LOGO_SZ) // 2

        logo = _logo_small(abbr, team_id, size=logo_sz)
        if logo is not None:
            lw, lh = logo.size
            logo_x = slot_x + (_WC_SLOT_W - lw) // 2
            Himage.paste(logo, (logo_x, logo_top))
        else:
            abbr_w = int(font.getlength(abbr))
            text_y = logo_top + (logo_sz - 9) // 2
            draw.text((slot_x + (_WC_SLOT_W - abbr_w) // 2, text_y), abbr, font=font, fill=0)

        if badge:
            bw = int(font_badge.getlength(badge))
            draw.text((slot_x + (_WC_SLOT_W - bw) // 2, _WC_STRIP_H - _WC_BADGE_H - 1),
                      badge, font=font_badge, fill=0)

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
        box_x0 = _WC_BOX_X_START + 1
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


def draw_playoff_bracket_header(Himage, bracket_data):
    """Draw current postseason series in the 30px top header strip (y=0..30).

    Shows every series as: ROUND  AWAY W-H HOME  (e.g. "WC  NYY 2-0 TEX")
    Active (incomplete) series are listed first and rendered bold (double-drawn).
    Complete series are shown dimmer by not double-drawing them.
    Series slots are evenly distributed across the full 800px width.
    """
    if not bracket_data:
        return Himage

    series = bracket_data.get('series', [])
    if not series:
        return Himage

    draw  = ImageDraw.Draw(Himage)
    font  = _get_font(9)
    font11 = _get_font(11)

    # Active series first so they appear on the left
    active   = [s for s in series if not s.get('complete')]
    complete = [s for s in series if s.get('complete')]
    to_show  = active + complete

    n        = len(to_show)
    entry_w  = 800 // n
    text_y   = (_WC_STRIP_H - 9) // 2   # vertically centre 9px text in 30px strip

    for i, s in enumerate(to_show):
        x0 = i * entry_w

        away_abbr  = s.get('away_abbr', '?')
        home_abbr  = s.get('home_abbr', '?')
        away_wins  = s.get('away_wins',  0)
        home_wins  = s.get('home_wins',  0)
        round_lbl  = s.get('round', '?')
        is_active  = not s.get('complete', False)

        # "WC  NYY 2-0 TEX" — when one team leads, its win count is rendered in
        # font11 (slightly larger). Built as three segments (prefix / leader
        # digit / suffix) with widths measured in their own fonts up front, so
        # the larger digit gets its own reserved space instead of being
        # overlaid on top of the font9 text and bleeding into its neighbors.
        if away_wins != home_wins:
            if away_wins > home_wins:
                prefix = f'{round_lbl}  {away_abbr} '
                ldr_str = str(away_wins)
                suffix = f'-{home_wins} {home_abbr}'
            else:
                prefix = f'{round_lbl}  {away_abbr} {away_wins}-'
                ldr_str = str(home_wins)
                suffix = f' {home_abbr}'
        else:
            prefix = f'{round_lbl}  {away_abbr} {away_wins}-{home_wins} {home_abbr}'
            ldr_str = ''
            suffix = ''

        # Font.ttc's glyphs have enough negative left-bearing at these odd
        # pixel sizes that font11's digit visually overlaps whatever's measured
        # as "before" it by getlength() alone — a small fixed gap on each side
        # of the leader digit compensates (verified visually, not just by width
        # math: font metrics said the spacing was already correct).
        _GAP = 2 if ldr_str else 0

        prefix_w = int(font.getlength(prefix))
        ldr_w = int(font11.getlength(ldr_str)) if ldr_str else 0
        suffix_w = int(font.getlength(suffix))
        tw = prefix_w + (ldr_w + 2 * _GAP if ldr_str else 0) + suffix_w
        tx = x0 + (entry_w - tw) // 2

        # Vertical separator between entries
        if i > 0:
            draw.line((x0, 3, x0, _WC_STRIP_H - 4), fill=0, width=1)

        # Bold (double-draw) for active series; single-draw for complete
        draw.text((tx, text_y), prefix, font=font, fill=0)
        if is_active:
            draw.text((tx + 1, text_y), prefix, font=font, fill=0)

        if ldr_str:
            _ldr_x = tx + prefix_w + _GAP
            draw.text((_ldr_x, text_y - 1), ldr_str, font=font11, fill=0)
            if is_active:
                draw.text((_ldr_x + 1, text_y - 1), ldr_str, font=font11, fill=0)

            _sfx_x = _ldr_x + ldr_w + _GAP
            draw.text((_sfx_x, text_y), suffix, font=font, fill=0)
            if is_active:
                draw.text((_sfx_x + 1, text_y), suffix, font=font, fill=0)

    # Draw top/bottom borders for the strip
    draw.line((0, 0, 799, 0), fill=0, width=1)
    draw.line((0, _WC_STRIP_H - 1, 799, _WC_STRIP_H - 1), fill=0, width=1)

    return Himage


# Local state-set duplication of image_grid.py's equivalents — image_grid
# already imports from this module, so importing back would be circular.
_TICKER_FINAL_STATES = {'Final', 'Game Over', 'Final: Tied'}
_TICKER_POSTPONED_STATES = {'Postponed', 'Cancelled', 'Cancelled: Rain'}
_TICKER_LIVE_STATES = {'In Progress', 'Player challenge', 'Manager challenge'}

_TICKER_MAX_ENTRIES = 12  # entries shown per render before rotation kicks in
_TICKER_SCORE_FONT_SIZE = 16   # bigger than the surrounding 9pt status text
_TICKER_ROW_H = _WC_STRIP_H // 2     # two stacked rows (away on top, home below)
_TICKER_LOGO_SZ = _TICKER_ROW_H - 2  # small enough to fit one row with a 1px margin
_TICKER_ROW_FONT_SIZE = 13           # R/H/E digits, one per row — all the same size
# Font.ttc's glyphs have enough negative left-bearing at these odd pixel sizes
# that the dash visually overlaps whatever getlength() alone measured as
# "before" it — a small fixed gap on each side compensates (same technique as
# draw_playoff_bracket_header's leader-digit spacing).


def _ticker_status(game):
    """Short status label for one overflow-ticker entry, based on game state:
    start time (not started), 'Top 4'/'Bot 7' (live), 'F' (final), or 'Postponed'."""
    state = game.get('detailed_state', '')
    if state in _TICKER_FINAL_STATES:
        _inn = game.get('current_inning') or 9
        return f'F/{_inn}' if _inn > 9 else 'F'
    if state in _TICKER_POSTPONED_STATES:
        return 'Postponed'
    if state in _TICKER_LIVE_STATES:
        _inn_state = game.get('inningState') or ''
        _inn_label = {'Top': 'Top', 'Bottom': 'Bot', 'Middle': 'Mid', 'End': 'End'}.get(
            _inn_state, _inn_state[:3].capitalize() if _inn_state else '')
        _inn_ord_raw = game.get('currentInningOrdinal') or str(game.get('current_inning') or 1)
        _inn_ord = re.sub(r'(?:st|nd|rd|th)$', '', _inn_ord_raw, flags=re.IGNORECASE)
        return f'{_inn_label} {_inn_ord}'.strip()
    # Scheduled / Pre-Game / Warmup / Delayed Start / anything else not-yet-started —
    # fetch_games.py pre-formats game_start as local time (e.g. "7:05 PM").
    return game.get('game_start') or state


def _ticker_score(game):
    """'5-3' scoreline for a Final or live game with runs recorded, '' for a
    Scheduled/Postponed game (nothing to score yet)."""
    state = game.get('detailed_state', '')
    if state not in _TICKER_FINAL_STATES and state not in _TICKER_LIVE_STATES:
        return ''
    away = game.get('away_runs')
    home = game.get('home_runs')
    if away is None or home is None:
        return ''
    return f'{away}-{home}'


def _ticker_hits_errors(game):
    """(away_hits, home_hits, away_errors, home_errors) as ints, or None if
    the game has no score yet (Scheduled/Postponed) or the fields are
    missing — same gating as _ticker_score, since H/E are only meaningful
    once a game is actually underway."""
    if not _ticker_score(game):
        return None
    vals = (game.get('away_hits'), game.get('home_hits'),
            game.get('away_errors'), game.get('home_errors'))
    if any(v is None for v in vals):
        return None
    return vals


def _ticker_window(dropped_games, max_entries=_TICKER_MAX_ENTRIES, rotation_minutes=2):
    """Return up to ``max_entries`` games to show this render.

    When there are more dropped games than fit at once, cycles through
    consecutive windows over time (stable within a rotation_minutes block,
    same time-block-seeded approach as image_leaders.py's rotating_categories)
    so every dropped game eventually gets shown instead of a fixed subset
    winning forever.
    """
    if len(dropped_games) <= max_entries:
        return dropped_games
    rotation_minutes = max(rotation_minutes, 1)
    n_chunks = -(-len(dropped_games) // max_entries)  # ceil division
    block_idx = int(_time.time() // (rotation_minutes * 60))
    i = (block_idx % n_chunks) * max_entries
    return dropped_games[i:i + max_entries]


def draw_overflow_ticker(Himage, dropped_games, team_data, rotation_minutes=2):
    """Draw games that couldn't fit on the grid as a compact scorebug ticker
    across the top header strip (y=0..30): a stacked away-logo/home-logo pair
    (one per 15px row) with each team's runs beside its own logo, then the
    game status ('F' for final, else the live inning or start time) trailing
    at the end of the entry.

    ``dropped_games`` are games compute_grid_layout couldn't place — bumped by
    live-game tile expansion, hide_non_live_games, or plain >15-game overflow.
    compute_grid_layout's _prioritize_live_over_final biases what gets dropped
    toward already-finished games, so in practice this is mostly Finals, but
    formats every state (see _ticker_status) since a live/scheduled/postponed
    game can still end up here (e.g. hide_non_live_games, doubleheader
    postponed eviction). Takes over the header strip outright — callers should
    only invoke this instead of draw_wildcard_header/draw_playoff_bracket_header,
    not alongside them. Rotates through a subset each render via _ticker_window
    when more games are dropped than fit on screen at once.
    """
    if not dropped_games:
        return Himage

    chunk = _ticker_window(dropped_games, rotation_minutes=rotation_minutes)

    draw = ImageDraw.Draw(Himage)
    font = _get_font(9)
    score_font = _get_font(_TICKER_SCORE_FONT_SIZE)
    row_font = _get_font(_TICKER_ROW_FONT_SIZE)
    abbr_map = team_data.get('team_abbreviation', {})
    text_y = (_WC_STRIP_H - 9) // 2

    n = len(chunk)
    entry_w = 800 // n

    for i, game in enumerate(chunk):
        x0 = i * entry_w

        away_id = str(game.get('away_team_id', ''))
        home_id = str(game.get('home_team_id', ''))
        away_abbr = abbr_map.get(away_id, '???')
        home_abbr = abbr_map.get(home_id, '???')
        score = _ticker_score(game)
        status = _ticker_status(game)

        def _draw_bold_status(xy, text, bold_font=font):
            """Bold via the same double-draw-offset-by-1px technique used
            for the live/final status below (and draw_wildcard_header's
            prefix) — keeps the not-yet-started start time visually
            consistent with 'Bot 7' / 'F'."""
            draw.text(xy, text, font=bold_font, fill=0)
            draw.text((xy[0] + 1, xy[1]), text, font=bold_font, fill=0)

        state = game.get('detailed_state', '')
        not_started = (
            state not in _TICKER_FINAL_STATES
            and state not in _TICKER_POSTPONED_STATES
            and state not in _TICKER_LIVE_STATES
        )
        if not_started:
            # Nothing to score yet — a single row is enough: away logo, a
            # dash, home logo, then the start time trailing (no stacked
            # rows/dividers, unlike the live/final layout below).
            _sched_logo_sz = _WC_STRIP_H - 2
            _a_logo = _logo_small(away_abbr, away_id, size=_sched_logo_sz)
            _h_logo = _logo_small(home_abbr, home_id, size=_sched_logo_sz)
            _a_w = _a_logo.size[0] if _a_logo else int(font.getlength(away_abbr))
            _h_w = _h_logo.size[0] if _h_logo else int(font.getlength(home_abbr))
            _dash_w = int(font.getlength(' - '))
            _time_w = int(font.getlength(status)) if status else 0
            _total_w = _a_w + _dash_w + _h_w + (4 + _time_w if status else 0)
            _cx = x0 + max(0, (entry_w - _total_w) // 2)
            if _a_logo:
                Himage.paste(_a_logo, (_cx, (_WC_STRIP_H - _a_logo.size[1]) // 2))
            else:
                draw.text((_cx, text_y), away_abbr, font=font, fill=0)
            _cx += _a_w
            draw.text((_cx, text_y), ' - ', font=font, fill=0)
            _cx += _dash_w
            if _h_logo:
                Himage.paste(_h_logo, (_cx, (_WC_STRIP_H - _h_logo.size[1]) // 2))
            else:
                draw.text((_cx, text_y), home_abbr, font=font, fill=0)
            _cx += _h_w
            if status:
                _cx += 4
                _draw_bold_status((_cx, text_y), status)
            continue

        away_logo = _logo_small(away_abbr, away_id, size=_TICKER_LOGO_SZ)
        home_logo = _logo_small(home_abbr, home_id, size=_TICKER_LOGO_SZ)

        away_w = away_logo.size[0] if away_logo else int(font.getlength(away_abbr))
        home_w = home_logo.size[0] if home_logo else int(font.getlength(home_abbr))
        logo_col_w = max(away_w, home_w)

        # 'F' (final) is drawn at the bigger score font for emphasis; every
        # other status (live inning, start time, 'Postponed') stays at the
        # small font.
        status_font = score_font if status == 'F' else font
        status_w = int(status_font.getlength(status)) if status else 0

        def _col_widths(away_val, home_val):
            """(away_w, home_w, col_w) for a stacked digit pair — col_w is
            the wider of the two, so the narrower digit can be centered
            within it rather than left-hugging the divider."""
            aw = int(row_font.getlength(away_val))
            hw = int(row_font.getlength(home_val))
            return aw, hw, max(aw, hw)

        if score:
            away_r, home_r = score.split('-')
            away_r_w, home_r_w, row_w = _col_widths(away_r, home_r)
        else:
            away_r = home_r = None
            away_r_w = home_r_w = row_w = 0

        # Hits/errors trail the runs column as two more stacked digit pairs —
        # only present once the game actually has a score (see
        # _ticker_hits_errors), same gating as the runs column itself.
        he = _ticker_hits_errors(game)
        if he:
            away_h, home_h, away_e, home_e = (str(v) for v in he)
            away_h_w, home_h_w, h_w = _col_widths(away_h, home_h)
            away_e_w, home_e_w, e_w = _col_widths(away_e, home_e)
        else:
            away_h = home_h = away_e = home_e = None
            away_h_w = home_h_w = h_w = 0
            away_e_w = home_e_w = e_w = 0

        # Layout: stacked logos, a divider, each team's R/H/E stacked beside
        # its own logo (each column separated by its own thin divider so the
        # digits don't run together), then the trailing status.
        total_w = logo_col_w
        if score:
            total_w += 2 + 1 + 2 + row_w
        if he:
            total_w += 2 + 1 + 2 + h_w + 2 + 1 + 2 + e_w
        if status:
            total_w += 4 + status_w

        cur_x = x0 + max(0, (entry_w - total_w) // 2)
        block_start_x = cur_x

        row_text_y = (_TICKER_ROW_H - 9) // 2
        if away_logo:
            Himage.paste(away_logo, (cur_x + (logo_col_w - away_w) // 2, (_TICKER_ROW_H - away_logo.size[1]) // 2))
        else:
            draw.text((cur_x + (logo_col_w - away_w) // 2, row_text_y), away_abbr, font=font, fill=0)
        if home_logo:
            Himage.paste(home_logo, (cur_x + (logo_col_w - home_w) // 2, _TICKER_ROW_H + (_TICKER_ROW_H - home_logo.size[1]) // 2))
        else:
            draw.text((cur_x + (logo_col_w - home_w) // 2, _TICKER_ROW_H + row_text_y), home_abbr, font=font, fill=0)
        cur_x += logo_col_w

        row_top_y = (_TICKER_ROW_H - _TICKER_ROW_FONT_SIZE) // 2
        row_bot_y = _TICKER_ROW_H + row_top_y

        def _draw_bold(xy, text, bold_font=row_font):
            """Bold via the same double-draw-offset-by-1px technique used
            elsewhere in this module (e.g. draw_wildcard_header's prefix)."""
            draw.text(xy, text, font=bold_font, fill=0)
            draw.text((xy[0] + 1, xy[1]), text, font=bold_font, fill=0)

        if score:
            cur_x += 2
            draw.line((cur_x, 1, cur_x, _WC_STRIP_H - 2), fill=0, width=1)
            cur_x += 1 + 2
            _draw_bold((cur_x + (row_w - away_r_w) // 2, row_top_y), away_r)
            _draw_bold((cur_x + (row_w - home_r_w) // 2, row_bot_y), home_r)
            cur_x += row_w

        if he:
            cur_x += 2
            draw.line((cur_x, 1, cur_x, _WC_STRIP_H - 2), fill=0, width=1)
            cur_x += 1 + 2
            _draw_bold((cur_x + (h_w - away_h_w) // 2, row_top_y), away_h)
            _draw_bold((cur_x + (h_w - home_h_w) // 2, row_bot_y), home_h)
            cur_x += h_w
            cur_x += 2
            draw.line((cur_x, 1, cur_x, _WC_STRIP_H - 2), fill=0, width=1)
            cur_x += 1 + 2
            _draw_bold((cur_x + (e_w - away_e_w) // 2, row_top_y), away_e)
            _draw_bold((cur_x + (e_w - home_e_w) // 2, row_bot_y), home_e)
            cur_x += e_w

        # Horizontal divider between the away (top) and home (bottom) rows,
        # spanning just the logo/R/H/E block — not under the trailing status,
        # which reads as one unit for the whole entry rather than per-team.
        draw.line((block_start_x, _TICKER_ROW_H, cur_x - 1, _TICKER_ROW_H), fill=0, width=1)

        if status:
            cur_x += 4
            _status_y = (_WC_STRIP_H - _TICKER_SCORE_FONT_SIZE) // 2 if status == 'F' else text_y
            _draw_bold((cur_x, _status_y), status, bold_font=status_font)

    return Himage


_RECAP_WALK_OFF_ABBR = {
    'Home Run': 'HR', 'Single': '1B', 'Double': '2B', 'Triple': '3B',
    'Walk': 'BB', 'Hit By Pitch': 'HBP', 'Error': 'E', 'Passed Ball': 'PB',
    'Wild Pitch': 'WP', 'Balk': 'BLK',
}


def _recap_row_labels(game):
    """(top_label, bot_label) for one game in the recap header.

    Walk-off games show the walk-off type ("Walk-off" / "HR") so the play
    gets the spotlight instead of the pitcher line. Normal finals show the
    winning and losing pitcher last names ("WP: Cole" / "LP: Pivetta").
    """
    if game.get('walk_off'):
        abbr = _RECAP_WALK_OFF_ABBR.get(game.get('last_play') or '', '')
        return 'Walk-off', abbr
    wp = game.get('winner_name') or ''
    lp = game.get('loser_name') or ''
    top = ('WP: ' + wp.split()[-1]) if wp else ''
    bot = ('LP: ' + lp.split()[-1]) if lp else ''
    return top, bot


def draw_recap_header(Himage, final_games, team_data, rotation_minutes=2):
    """Draw a game-recap strip across the 30px header (y=0..30) once all
    games for the day are Final.

    One entry per game, same stacked-logo format as draw_overflow_ticker.
    Walk-off games show the walk-off play type; others show WP/LP last names.
    Rotates through entries when more games than _TICKER_MAX_ENTRIES fit at once.
    """
    games = [g for g in (final_games or []) if g.get('away_runs') is not None]
    if not games:
        return Himage

    chunk = _ticker_window(games, rotation_minutes=rotation_minutes)

    draw = ImageDraw.Draw(Himage)
    font = _get_font(9)
    row_font = _get_font(_TICKER_ROW_FONT_SIZE)
    abbr_map = team_data.get('team_abbreviation', {})

    n = len(chunk)
    entry_w = 800 // n

    for i, game in enumerate(chunk):
        x0 = i * entry_w

        away_id = str(game.get('away_team_id', ''))
        home_id = str(game.get('home_team_id', ''))
        away_abbr = abbr_map.get(away_id, '???')
        home_abbr = abbr_map.get(home_id, '???')

        away_logo = _logo_small(away_abbr, away_id, size=_TICKER_LOGO_SZ)
        home_logo = _logo_small(home_abbr, home_id, size=_TICKER_LOGO_SZ)
        away_w = away_logo.size[0] if away_logo else int(font.getlength(away_abbr))
        home_w = home_logo.size[0] if home_logo else int(font.getlength(home_abbr))
        logo_col_w = max(away_w, home_w)

        away_r = str(game.get('away_runs', ''))
        home_r = str(game.get('home_runs', ''))
        away_r_w = int(row_font.getlength(away_r))
        home_r_w = int(row_font.getlength(home_r))
        row_w = max(away_r_w, home_r_w)

        top_label, bot_label = _recap_row_labels(game)
        top_w = int(font.getlength(top_label)) if top_label else 0
        bot_w = int(font.getlength(bot_label)) if bot_label else 0
        label_w = max(top_w, bot_w)

        total_w = logo_col_w + 2 + 1 + 2 + row_w
        if label_w:
            total_w += 4 + label_w

        cur_x = x0 + max(0, (entry_w - total_w) // 2)
        block_start_x = cur_x

        row_top_y = (_TICKER_ROW_H - _TICKER_ROW_FONT_SIZE) // 2
        row_bot_y = _TICKER_ROW_H + row_top_y

        if away_logo:
            Himage.paste(away_logo, (cur_x + (logo_col_w - away_w) // 2,
                                     (_TICKER_ROW_H - away_logo.size[1]) // 2))
        else:
            draw.text((cur_x + (logo_col_w - away_w) // 2, row_top_y),
                      away_abbr, font=font, fill=0)
        if home_logo:
            Himage.paste(home_logo, (cur_x + (logo_col_w - home_w) // 2,
                                     _TICKER_ROW_H + (_TICKER_ROW_H - home_logo.size[1]) // 2))
        else:
            draw.text((cur_x + (logo_col_w - home_w) // 2, _TICKER_ROW_H + row_top_y),
                      home_abbr, font=font, fill=0)
        cur_x += logo_col_w

        def _bold(xy, text, f=row_font):
            draw.text(xy, text, font=f, fill=0)
            draw.text((xy[0] + 1, xy[1]), text, font=f, fill=0)

        cur_x += 2
        draw.line((cur_x, 1, cur_x, _WC_STRIP_H - 2), fill=0, width=1)
        cur_x += 1 + 2
        _bold((cur_x + (row_w - away_r_w) // 2, row_top_y), away_r)
        _bold((cur_x + (row_w - home_r_w) // 2, row_bot_y), home_r)
        cur_x += row_w

        draw.line((block_start_x, _TICKER_ROW_H, cur_x - 1, _TICKER_ROW_H), fill=0, width=1)

        if label_w:
            cur_x += 4
            if top_label:
                _bold((cur_x, row_top_y), top_label, f=font)
            if bot_label:
                _bold((cur_x, row_bot_y), bot_label, f=font)

    return Himage


_TX_HEADER_MAX = 5
_TX_HEADER_ABBR = {
    'Status Change': 'IL', 'Recalled': 'Recall', 'Optioned': 'Option',
    'Selected': 'Select', 'Designated for Assignment': 'DFA',
    'Released': 'Release', 'Signed': 'Sign', 'Trade': 'Trade',
    'Claimed off Waivers': 'Waiver', 'Outrighted': 'Outright',
}


def draw_transactions_header(Himage, transactions_data, team_data, rotation_minutes=3):
    """Draw recent transactions in the 30px header strip (y=0..30).

    Called when the strip is otherwise blank (no overflow ticker, bracket, or
    wildcard standings). Rotates through entries when more than _TX_HEADER_MAX
    are available. Format per entry: 'ABBR LastName Type' (e.g. 'NYY Stanton IL').
    """
    entries = list(transactions_data or [])
    if not entries:
        return Himage

    rotation_minutes = max(rotation_minutes, 1)
    n = len(entries)
    if n <= _TX_HEADER_MAX:
        chunk = entries[:_TX_HEADER_MAX]
    else:
        n_chunks = -(-n // _TX_HEADER_MAX)
        block_idx = int(_time.time() // (rotation_minutes * 60))
        start = (block_idx % n_chunks) * _TX_HEADER_MAX
        chunk = entries[start:start + _TX_HEADER_MAX]

    draw = ImageDraw.Draw(Himage)
    font = _get_font(9)
    text_y = (_WC_STRIP_H - 9) // 2

    n_shown = len(chunk)
    entry_w = 800 // max(n_shown, 1)

    for i, entry in enumerate(chunk):
        x0 = i * entry_w

        abbr = entry.get('team_abbr', '')
        player = entry.get('player_name', '')
        last = player.split()[-1] if player else ''
        tag = _TX_HEADER_ABBR.get(entry.get('type_desc', ''), (entry.get('type_desc') or '')[:7])

        text = ' '.join(p for p in (abbr, last, tag) if p)
        tw = int(font.getlength(text))
        tx = x0 + max(0, (entry_w - tw) // 2)
        draw.text((tx, text_y), text, font=font, fill=0)

        if i > 0:
            draw.line((x0, 3, x0, _WC_STRIP_H - 4), fill=0, width=1)

    draw.line((0, 0, 799, 0), fill=0, width=1)
    draw.line((0, _WC_STRIP_H - 1, 799, _WC_STRIP_H - 1), fill=0, width=1)

    return Himage


def _aaa_divisions(standings_data, side):
    """Return division names for each sidebar side in AAA mode.

    Left:  IL East (top) + PCL East (bottom)
    Right: IL West (top) + PCL West (bottom)
    """
    all_divs = set(standings_data.get('standings', {}).keys())
    if side == 'left':
        candidates = ['International League East', 'Pacific Coast League East']
    else:
        candidates = ['International League West', 'Pacific Coast League West']
    return [d for d in candidates if d in all_divs]


# Magic/elimination arithmetic lives in image_utils so this and the magic-number
# grid cell (image_magic._magic_or_elim) can't drift apart.
_ME_BADGE_THRESHOLD = ELIM_THRESHOLD
_ME_MAGIC_BASE = MAGIC_BASE


def _me_badge_value(team, leader, is_leader, rival_losses):
    """Badge text for a standings row — see image_utils.magic_or_elim_value."""
    return magic_or_elim_value(team, leader, is_leader, rival_losses)


def draw_standings_sidebar(Himage, standings_data, team_data, side='left', league_mode='mlb',
                           show_magic_badges=False):
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

    _SLOT_H_STD = (_SIDEBAR_ROW_H - _SIDEBAR_VERTICAL_PADDING * 2) // 5  # 28px — standard MLB spacing

    if league_mode == 'aaa' and divisions:
        # Each section height is sized to its team count at standard spacing.
        # Sections stack from y=5 with a 5px gap between them.
        div_teams = [
            sorted(
                standings_data.get('standings', {}).get(d, []),
                key=lambda t: division_rank(t)
            )
            for d in divisions
        ]
        section_heights = [len(t) * _SLOT_H_STD + _SIDEBAR_VERTICAL_PADDING * 2 for t in div_teams]
        row_y_list = []
        y = _SIDEBAR_ROW_Y[0]
        for h in section_heights:
            row_y_list.append(y)
            y += h + 5
        max_per_section = None  # show all teams in AAA mode
    else:
        section_heights = [_SIDEBAR_ROW_H] * len(divisions)
        row_y_list      = _SIDEBAR_ROW_Y
        max_per_section = 5

    for row_idx, div_name in enumerate(divisions):
        teams = standings_data.get('standings', {}).get(div_name, [])
        teams = sorted(teams, key=lambda t: division_rank(t))
        y_section = row_y_list[row_idx]
        n_show    = len(teams) if max_per_section is None else min(len(teams), max_per_section)
        slot_h    = _SLOT_H_STD

        # --- Rank + record change detection ---
        # A team is a mover when its rank changed AND its record changed.
        movers = set()
        for team in teams[:n_show]:
            tid = str(team.get('team_id', ''))
            if tid not in prev_rank:
                continue
            cur_rank = division_rank(team)
            prev_r, prev_w, prev_l = prev_rank[tid]
            cur_w = int(team.get('league_record_wins') or 0)
            cur_l = int(team.get('league_record_losses') or 0)
            if cur_rank != prev_r and (cur_w != prev_w or cur_l != prev_l):
                movers.add(tid)

        # Any team displaced by a mover also changed rank — mark it too.
        if movers:
            for team in teams[:n_show]:
                tid = str(team.get('team_id', ''))
                if tid not in prev_rank or tid in movers:
                    continue
                cur_rank = division_rank(team)
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
        for _ct in teams[:n_show]:
            _tid = str(_ct.get('team_id', ''))
            try:
                cur_wl_by_tid[_tid] = (
                    int(_ct.get('league_record_wins') or 0),
                    int(_ct.get('league_record_losses') or 0),
                )
            except (ValueError, TypeError):
                pass

        for i in range(len(teams[:n_show]) - 1):
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
        for team in teams[:n_show]:
            tid = str(team.get('team_id', ''))
            ts = _movement_data.get(tid)
            if ts is not None:
                try:
                    if _now_ts - float(ts) < _20h_secs:
                        display_movers.add(tid)
                except (ValueError, TypeError):
                    pass

        # Precompute M/E badge data for this division (leader + minimum rival losses)
        _me_leader = teams[0] if teams else None
        _rival_losses = None
        if _me_leader and len(teams) > 1:
            _rl_vals = [
                t.get('league_record_losses')
                for t in teams[1:]
                if t.get('league_record_losses') is not None
            ]
            if _rl_vals:
                _rival_losses = min(_rl_vals)

        for slot_idx, team in enumerate(teams[:n_show]):
            team_id = str(team.get('team_id', ''))
            abbr    = abbr_map.get(team_id, f'T{team_id}')
            logo_y  = y_section + _SIDEBAR_VERTICAL_PADDING + slot_idx * slot_h

            logo_img = _logo_small(abbr, team_id, size=_SIDEBAR_LOGO_SIZE)
            if logo_img is not None:
                lw, lh = logo_img.size
                paste_x = logo_x + (_SIDEBAR_LOGO_SIZE - lw) // 2
                paste_y = logo_y + (_SIDEBAR_LOGO_SIZE - lh) // 2
                Himage.paste(logo_img, (paste_x, paste_y))
                _logo_img_bottom = paste_y + lh
            else:
                font = _get_font(9)
                tw = int(font.getlength(abbr[:3]))
                draw.text((logo_x + (_SIDEBAR_LOGO_SIZE - tw) // 2, logo_y + 8), abbr[:3], font=font, fill=0)
                _logo_img_bottom = logo_y + _SIDEBAR_LOGO_SIZE

            # M/E badge: outer sidebar wall, same vertical position and font as
            # the streak badge on the inner wall — mirrored to the opposite side.
            if show_magic_badges and league_mode == 'mlb' and _me_leader:
                _badge = _me_badge_value(team, _me_leader, slot_idx == 0, _rival_losses)
                if _badge:
                    _bf = _get_font(7)
                    _bw = int(_bf.getlength(_badge))
                    _by = _logo_img_bottom - 1
                    if side == 'left':
                        draw.text((sep_x0 + 1, _by), _badge, font=_bf, fill=0)
                    else:
                        draw.text((sep_x1 - _bw - 1, _by), _badge, font=_bf, fill=0)

            # Streak badge: tucked just below the actual logo image, flush with the inner sidebar wall.
            _streak_str = (team.get('streak') or '').strip()
            if len(_streak_str) > 1 and _streak_str[0] == 'L' and _streak_str[1:].isdigit():
                _streak_str = 'L ' + _streak_str[1:]
            if _streak_str:
                _sf8 = _get_font(7)
                _sw8 = int(_sf8.getlength(_streak_str))
                _by = _logo_img_bottom - 1
                if side == 'left':
                    # Right-align to inner (right) wall of left sidebar
                    _bx = 32 - _sw8
                else:
                    # Left-align to inner (left) wall of right sidebar
                    _bx = 800 - 32
                draw.text((_bx, _by), _streak_str, font=_sf8, fill=0)

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
            if slot_idx + 1 < n_show and slot_idx + 1 < len(teams):
                nxt = teams[slot_idx + 1]
                cur_wl = (int(team.get('league_record_wins') or 0), int(team.get('league_record_losses') or 0))
                nxt_wl = (int(nxt.get('league_record_wins') or 0),  int(nxt.get('league_record_losses') or 0))
                if cur_wl == nxt_wl:
                    # Center the 2px-tall dash strip in the gap between logos.
                    # (slot_h - logo_size - 2) // 2 leaves equal empty rows above and below;
                    # shifted up 2px from center.
                    gap_y = logo_y + _SIDEBAR_LOGO_SIZE + (slot_h - _SIDEBAR_LOGO_SIZE - 2) // 2 - 2
                    dash_w, gap_w = 4, 2
                    total_dash_w = 2 * dash_w + gap_w
                    dash_start = logo_x + (_SIDEBAR_LOGO_SIZE - total_dash_w) // 2
                    for d in range(2):
                        x0 = dash_start + d * (dash_w + gap_w)
                        draw.line((x0, gap_y, x0 + dash_w - 1, gap_y), fill=0, width=2)

    # Persist movement timestamps so indicators survive across render cycles
    if _movement_updated:
        save_off_results(_movement_data, 'standings_movement')

    return Himage


def draw_standings_sidebar_fullscreen(canvas, standings_data, team_data, side='left', league_mode='mlb',
                                      y_start=_WC_STRIP_H, height=450,
                                      x_anchor=None, sidebar_w=None, logo_sz=None):
    """Draw AL or NL divisions (E/C/W) as 3 side-by-side columns for the fullscreen game layout.

    Left side = AL, right side = NL.  x_anchor / sidebar_w / logo_sz can be overridden by the
    caller so each side uses the space actually available (the right sidebar starts where the
    scoreboard box's horizontal line stops, not at the far right edge of the game cell image).
    """
    if league_mode == 'aaa':
        divisions = _aaa_divisions(standings_data, side)[:3]
    else:
        divisions = _AL_DIV_ORDER if side == 'left' else _NL_DIV_ORDER

    abbr_map = {**standings_data.get('team_abbreviation', {}),
                **team_data.get('team_abbreviation', {})}

    if x_anchor is None:
        x_anchor = 0 if side == 'left' else (800 - _FS_SIDEBAR_W)
    if sidebar_w is None:
        sidebar_w = _FS_SIDEBAR_W
    col_w = sidebar_w // 3
    if logo_sz is None:
        logo_sz = _FS_LOGO_SZ

    n_teams     = 5
    team_area_h = height
    slot_h      = team_area_h // n_teams

    draw       = ImageDraw.Draw(canvas)

    # --- Movement indicator detection (same logic as draw_standings_sidebar) ---
    _now_ts   = _time.time()
    _20h_secs = 20 * 3600
    prev_rank = {}
    prev_data = {}
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

    _movement_data = load_json_file('standings_movement.json') or {}
    _movement_updated = False

    # Build display_movers across all divisions for this sidebar
    display_movers = set()
    for _div_name in divisions:
        _div_teams = standings_data.get('standings', {}).get(_div_name, [])
        _div_teams = sorted(_div_teams, key=lambda t: division_rank(t))
        _n = min(len(_div_teams), n_teams)

        movers = set()
        for team in _div_teams[:_n]:
            tid = str(team.get('team_id', ''))
            if tid not in prev_rank:
                continue
            cur_rank = division_rank(team)
            prev_r, prev_w, prev_l = prev_rank[tid]
            cur_w = int(team.get('league_record_wins') or 0)
            cur_l = int(team.get('league_record_losses') or 0)
            if cur_rank != prev_r and (cur_w != prev_w or cur_l != prev_l):
                movers.add(tid)

        if movers:
            for team in _div_teams[:_n]:
                tid = str(team.get('team_id', ''))
                if tid not in prev_rank or tid in movers:
                    continue
                cur_rank = division_rank(team)
                prev_r, _, _ = prev_rank[tid]
                if cur_rank != prev_r:
                    movers.add(tid)

        # Tie-break detection
        prev_div_teams = prev_data.get('standings', {}).get(_div_name, [])
        prev_wl = {str(_pt.get('team_id', '')): (int(_pt.get('league_record_wins') or 0),
                                                  int(_pt.get('league_record_losses') or 0))
                   for _pt in prev_div_teams}
        cur_wl  = {str(_ct.get('team_id', '')): (int(_ct.get('league_record_wins') or 0),
                                                  int(_ct.get('league_record_losses') or 0))
                   for _ct in _div_teams[:_n]}
        for i in range(_n - 1):
            t1 = str(_div_teams[i].get('team_id', ''))
            t2 = str(_div_teams[i + 1].get('team_id', ''))
            if t1 in prev_wl and t2 in prev_wl:
                if prev_wl[t1] == prev_wl[t2] and cur_wl.get(t1) != cur_wl.get(t2):
                    movers.add(t1)
                    movers.add(t2)

        for tid in movers:
            _movement_data[tid] = _now_ts
            _movement_updated = True

        for team in _div_teams[:_n]:
            tid = str(team.get('team_id', ''))
            ts = _movement_data.get(tid)
            if ts is not None:
                try:
                    if _now_ts - float(ts) < _20h_secs:
                        display_movers.add(tid)
                except (ValueError, TypeError):
                    pass

    if _movement_updated:
        save_off_results(_movement_data, 'standings_movement')

    for col_idx, div_name in enumerate(divisions[:3]):
        col_x = x_anchor + col_idx * col_w

        teams = standings_data.get('standings', {}).get(div_name, [])
        teams = sorted(teams, key=lambda t: division_rank(t))

        for slot_idx, team in enumerate(teams[:n_teams]):
            team_id = str(team.get('team_id', ''))
            abbr    = abbr_map.get(team_id, f'T{team_id}')

            slot_y = y_start + slot_idx * slot_h
            logo_x = col_x + (col_w - logo_sz) // 2
            logo_y = slot_y + (slot_h - logo_sz) // 2

            logo_img = _logo_small(abbr, team_id, size=logo_sz)
            if logo_img:
                lw2, lh = logo_img.size
                canvas.paste(logo_img, (logo_x + (logo_sz - lw2) // 2,
                                        logo_y + (logo_sz - lh) // 2))
                _fs_logo_bottom = logo_y + (logo_sz - lh) // 2 + lh
            else:
                font9 = _get_font(9)
                tw = int(font9.getlength(abbr[:3]))
                draw.text((logo_x + (logo_sz - tw) // 2, logo_y + (logo_sz - 9) // 2),
                          abbr[:3], font=font9, fill=0)
                _fs_logo_bottom = logo_y + logo_sz

            # Streak badge: tucked just below the actual logo image, aligned to inner edge of column.
            _fs_streak = (team.get('streak') or '').strip()
            if len(_fs_streak) > 1 and _fs_streak[0] == 'L' and _fs_streak[1:].isdigit():
                _fs_streak = 'L ' + _fs_streak[1:]
            if _fs_streak:
                _ssf8 = _get_font(7)
                _ssw8 = int(_ssf8.getlength(_fs_streak))
                _fs_by = _fs_logo_bottom - 1
                if side == 'left':
                    _fs_bx = col_x + col_w - _ssw8   # right-align to column's inner edge
                else:
                    _fs_bx = col_x                    # left-align to column's inner edge
                draw.text((_fs_bx, _fs_by), _fs_streak, font=_ssf8, fill=0)

            # Movement indicator: L-bracket around logo corner
            # AL (left): vertical on left + horizontal at bottom-left
            # NL (right): vertical on right + horizontal at bottom-right
            if team_id in display_movers:
                _arm  = logo_sz // 3
                _lw   = 4
                _foot = logo_y + logo_sz + 6        # 6px below logo bottom
                _vtop = _foot - logo_sz // 3         # vertical spans bottom 1/3 only
                if side == 'left':
                    _vx = col_x
                    draw.line((_vx, _vtop, _vx, _foot), fill=0, width=_lw)
                    draw.line((_vx, _foot, _vx + _arm, _foot), fill=0, width=_lw)
                else:
                    _vx = col_x + col_w - 1
                    draw.line((_vx, _vtop, _vx, _foot), fill=0, width=_lw)
                    draw.line((_vx - _arm, _foot, _vx, _foot), fill=0, width=_lw)

            # Clinch indicator
            clinch = (team.get('clinch_indicator') or '').lower()
            if clinch in ('y', 'z'):
                box_w = 2 if clinch == 'z' else 1
                draw.rectangle([logo_x, logo_y, logo_x + logo_sz - 1, logo_y + logo_sz - 1],
                               outline=0, width=box_w)

            # Tied-team dashes between consecutive slots with the same W-L record
            if slot_idx + 1 < n_teams and slot_idx + 1 < len(teams):
                nxt = teams[slot_idx + 1]
                cur_wl = (int(team.get('league_record_wins') or 0), int(team.get('league_record_losses') or 0))
                nxt_wl = (int(nxt.get('league_record_wins') or 0),  int(nxt.get('league_record_losses') or 0))
                if cur_wl == nxt_wl:
                    gap_y      = logo_y + logo_sz + (slot_h - logo_sz) // 2
                    dash_w, gap_w = 5, 3
                    dash_start = logo_x + (logo_sz - (5 * dash_w + 4 * gap_w)) // 2
                    for d in range(5):
                        x0 = dash_start + d * (dash_w + gap_w)
                        draw.line((x0, gap_y, x0 + dash_w - 1, gap_y), fill=0, width=1)

    return canvas
