from PIL import ImageDraw

EPD_WIDTH = 800
EPD_HEIGHT = 480

standings_dict = {
    1: 'American League East',
    2: 'American League Central',
    3: 'American League West',
    4: 'National League East',
    5: 'National League Central',
    6: 'National League West',
}


def normalize_dict(d):
    """Recursively replace None values with '' in a dict (including nested dicts and lists)."""
    for key, value in d.items():
        if value is None:
            d[key] = ''  # Convert None to ''
        elif isinstance(value, list):
            d[key] = [item if item is not None else '' for item in value]  # Convert None to '' in lists
        elif isinstance(value, dict):
            d[key] = normalize_dict(value)  # Recursively normalize nested dictionaries
    return d


def draw_tight_number(draw, cx, cy, text, font, fill, gap=None, bold=False):
    """Draw text centered at (cx, cy), spacing glyphs by their own ink width.

    Tabular-figure digit fonts give every glyph the same advance width so
    columns of numbers align, but that leaves a wide gap around narrow
    glyphs like '1'. Packing by each glyph's actual ink bbox instead keeps
    multi-digit runner numbers visually tight inside the small base diamonds.

    bold: double-draws each glyph offset by 1px, matching the bold pattern
    used elsewhere in the renderer.
    """
    full_bb = font.getbbox(text)
    if len(text) <= 1:
        x0 = cx - (full_bb[0] + full_bb[2]) // 2
        y0 = cy - (full_bb[1] + full_bb[3]) // 2
        draw.text((x0, y0), text, font=font, fill=fill)
        if bold:
            draw.text((x0 + 1, y0), text, font=font, fill=fill)
            draw.text((x0, y0 + 1), text, font=font, fill=fill)
            draw.text((x0 + 1, y0 + 1), text, font=font, fill=fill)
        return
    if gap is None:
        gap = 1
    char_bbs = [font.getbbox(ch) for ch in text]
    widths = [bb[2] - bb[0] for bb in char_bbs]
    total_w = sum(widths) + gap * (len(text) - 1)
    x = cx - total_w // 2
    y = cy - (full_bb[1] + full_bb[3]) // 2
    for ch, bb, w in zip(text, char_bbs, widths):
        draw.text((x - bb[0], y), ch, font=font, fill=fill)
        if bold:
            draw.text((x - bb[0] + 1, y), ch, font=font, fill=fill)
            draw.text((x - bb[0], y + 1), ch, font=font, fill=fill)
            draw.text((x - bb[0] + 1, y + 1), ch, font=font, fill=fill)
        x += w + gap


def draw_diamond(Himage, center, size, fill=False, outline_width=1):
    """Draw a diamond (rotated square) on Himage at center with the given size."""
    draw = ImageDraw.Draw(Himage)
    x, y = center
    diamond = [(x, y - size), (x + size, y), (x, y + size), (x - size, y)]

    if fill:
        draw.polygon(diamond, fill='black', outline='black', width=outline_width)
    else:
        draw.polygon(diamond, outline='black', width=outline_width)
    return Himage


# Function to draw a circle at a specific location with an option to fill
def draw_circle(Himage, center, radius, fill, outline_width=1):
    """Draw a circle on Himage at center with the given radius, filled or outlined."""
    draw = ImageDraw.Draw(Himage)

    x, y = center
    bounding_box = [x - radius, y - radius, x + radius, y + radius]  # Defines the square in which the circle will be drawn
    if fill:
        draw.ellipse(bounding_box, fill='black', outline='black', width=outline_width)
    else:
        draw.ellipse(bounding_box, outline='black', width=outline_width)
    return Himage


def check_if_two_chars(num):
    """Check if two chars."""
    if len(str(num)) == 2:
        return -6
    return 0


# Sorts unranked teams last, matching int(...) fallbacks used across the sidebars.
_UNRANKED = 99


def division_rank(team, default=_UNRANKED):
    """Return a team's divisionRank as an int, falling back to ``default``.

    standings.py always writes the 'divisionRank' key, storing None whenever the
    MLB Stats API omits a rank (preseason, spring training, some minor-league
    responses). A plain ``team.get('divisionRank', 99)`` therefore yields None
    rather than the default — ``int(None)`` raises TypeError and ``str(None)``
    renders a literal 'None'. Always go through this helper.
    """
    raw = (team or {}).get('divisionRank')
    if raw is None or raw == '':
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


_NAME_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'v'}


# Magic / elimination numbers. A full MLB season is 162 games; a team clinches
# over a rival the moment the rival can no longer tie it, i.e. when
# (162 + 1) - wins - rival_losses hits 0.
MAGIC_BASE = 163
# At or below this, a trailing team's elimination number is dramatic enough to
# show instead of games back — early/mid-season elimination numbers (60+) aren't
# meaningful. Also gates the leader's magic number: a leader whose magic number
# is still above this shows nothing at all.
ELIM_THRESHOLD = 20


def magic_or_elim_value(team, leader, is_leader, rival_losses):
    """Value string for one standings row: 'M4' / 'E7' / 'CL' / 'OUT' / games back.

    Shared by the magic-number grid cell (image_magic) and the standings sidebar
    badges (image_standings) — both render the same statistic and must agree.

    Returns '' when the underlying win/loss data isn't available yet, or when
    the number isn't meaningful yet (magic still above ELIM_THRESHOLD).
    """
    clinch = (team.get('clinch_indicator') or '').strip().lower()
    if clinch in ('z', 'y'):
        return 'CL'
    if clinch == 'e':
        return 'OUT'

    lead_w = leader.get('league_record_wins')
    if lead_w is None:
        return ''

    if is_leader:
        if rival_losses is None:
            return 'CL'          # no rivals left to hold off
        magic = MAGIC_BASE - lead_w - rival_losses
        if magic <= 0:
            return 'CL'
        return f'M{magic}' if magic <= ELIM_THRESHOLD else ''

    team_l = team.get('league_record_losses')
    if team_l is None:
        return ''
    elim = MAGIC_BASE - lead_w - team_l
    if elim <= 0:
        return 'OUT'
    if elim <= ELIM_THRESHOLD:
        return f'E{elim}'
    return str(team.get('games_back') or '-')


def _format_player_name(name):
    """Return 'F. Lastname' for a full player name, skipping suffixes like Jr./Sr./II."""
    if not name:
        return ''
    parts = name.split()
    last_name = parts[-1]
    for i in range(len(parts) - 1, 0, -1):
        if parts[i].lower().strip('.') not in _NAME_SUFFIXES:
            last_name = parts[i]
            break
    first_initial = parts[0][0] + '.' if len(parts) > 1 else ''
    return f'{first_initial} {last_name}' if first_initial else last_name


def _last_name(name):
    """Return just the last name, skipping suffixes like Jr./Sr./II."""
    if not name:
        return ''
    parts = name.split()
    if not parts:
        return ''
    for i in range(len(parts) - 1, 0, -1):
        if parts[i].lower().strip('.') not in _NAME_SUFFIXES:
            return parts[i]
    return parts[-1]


def _render_linescore_row(draw, x, y, inning_runs, fnt, max_width=130):
    """Draw per-inning run values as a space-separated strip."""
    if not inning_runs:
        return
    parts = [str(r) if r is not None else 'x' for r in inning_runs[:15]]
    # Try progressively tighter separators if the string is too wide
    for sep in ('  ', ' ', ''):
        txt = sep.join(parts)
        if int(fnt.getlength(txt)) <= max_width:
            break
    draw.text((x, y), txt, font=fnt, fill=0)


def _pitcher_line(name, note):
    """Return (name_str, stat_str) for probable pitcher display.

    name_str is 'Lastname F.' format.
    stat_str combines W-L and ERA, e.g. '1-0 3.45', or just one if the other
    is missing, or '' if neither is available.
    """
    if not name:
        return ('TBD', '')
    parts = name.split()
    last_name = parts[-1]
    for i in range(len(parts) - 1, 0, -1):
        if parts[i].lower().strip('.') not in _NAME_SUFFIXES:
            last_name = parts[i]
            break
    first_initial = parts[0][0] + '.' if len(parts) > 1 else ''
    display_name = f'{first_initial} {last_name}' if first_initial else last_name

    wl_str = ''
    era_str = ''
    if note:
        note_parts = note.split(', ')
        if note_parts:
            candidate = note_parts[0].strip()
            if '-' in candidate:
                left, right = candidate.split('-', 1)
                if left.strip().isdigit() and right.strip().isdigit():
                    wl_str = candidate
        if len(note_parts) >= 2:
            era_candidate = note_parts[1].replace(' ERA', '').strip()
            if era_candidate and not era_candidate.startswith('-'):
                try:
                    float(era_candidate)
                    era_str = era_candidate
                except ValueError:
                    pass

    if wl_str and era_str:
        stat = f'{wl_str} {era_str}'
    elif wl_str:
        stat = wl_str
    elif era_str:
        stat = era_str
    else:
        stat = ''
    return (display_name, stat)


_VENUE_OVERRIDES = {
    'loanDepot park': 'LoanDepot Park',
    'Daikin Park': 'Minute Maid Park',
    'Guaranteed Rate Field': 'Guaranteed Rate',
    'American Family Field': 'Am. Family Field',
    'Great American Ball Park': 'Great American',
}


def _series_display_str(game_data):
    """Return a short series record string for the header, or None if not applicable."""
    total = game_data.get('series_total_games') or 1
    if total <= 1:
        return None
    wins = game_data.get('series_wins') or 0
    losses = game_data.get('series_losses') or 0
    if wins == 0 and losses == 0:
        gn = game_data.get('series_game_number') or 1
        return f'Gm {gn}/{total}'
    if wins == losses:
        return f'Tied {wins}-{losses}'
    result = (game_data.get('series_result') or '').replace('Series ', '').strip()
    if result:
        return result[0].upper() + result[1:]
    return None


def _clean_venue_name(venue):
    """Return a short, ad-free venue name for display in the scoreboard header."""
    if not venue:
        return venue
    # Check for known overrides first
    if venue in _VENUE_OVERRIDES:
        return _VENUE_OVERRIDES[venue]
    # Strip 'X at Y' qualifiers (e.g. 'Oriole Park at Camden Yards' → 'Camden Yards')
    if ' at ' in venue:
        venue = venue.split(' at ', 1)[1]
    return venue


def _is_game_effectively_over(game_data):
    """True if MLB will mark the game Final shortly — used to suppress upcoming-batter text
    during the lag between the final out and detailed_state flipping to Final."""
    if game_data.get('detailed_state') in ('Final', 'Game Over', 'Final: Tied', 'Completed Early'):
        return True
    inning = game_data.get('current_inning') or 0
    state = game_data.get('inningState') or ''
    away = game_data.get('away_runs') or 0
    home = game_data.get('home_runs') or 0
    if inning >= 9:
        # Top of 9+ complete and home already ahead → home doesn't bat
        if state == 'Middle' and home > away:
            return True
        # Bottom of 9+ complete with a non-tie → game over
        if state == 'End' and home != away:
            return True
    return False


# MLB's typeDesc strings are too verbose for a narrow ticker row. Shared by the
# transactions panel, the deadline countdown and the idle screen, which all
# render the same feed at different sizes and used to keep private copies that
# had to be edited in lockstep.
TRANSACTION_TYPE_ABBR = {
    'Status Change':             'IL',
    'Recalled':                  'Recall',
    'Optioned':                  'Option',
    'Selected':                  'Select',
    'Designated for Assignment': 'DFA',
    'Released':                  'Release',
    'Signed':                    'Sign',
    'Trade':                     'Trade',
    'Claimed off Waivers':       'Waiver',
    'Outrighted':                'Outright',
}
