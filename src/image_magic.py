"""Draw a magic-number / elimination-number panel cell (150×150) for an
empty grid slot, covering the primary team's division.

Reuses the standings already cached in data/standings.json — no extra API
call. For each team in the division:

  * Division leader → magic number ``M`` (games to clinch over the closest
    rival, i.e. the rival with the fewest losses).
  * Trailing team  → games back from the leader, until its elimination
    number drops below ``image_utils.ELIM_THRESHOLD`` (elimination numbers are too
    large to be meaningful for most of the season); once the race is
    actually close, the elimination number ``E`` takes over that same slot.

When the MLB Stats API's ``clinch_indicator`` already settles it, that wins
over the arithmetic: ``z``/``y`` → ``CL`` (clinched), ``e`` → ``OUT``.

Mirrors image_leaders.draw_leaders_cell's layout so it drops into a grid
slot identically.
"""
from image_assets import _get_font, ImageDraw, _logo_small
from image_utils import division_rank, magic_or_elim_value

# Matches the visible footprint of a normal single-game grid box
# (mirrors image_leaders / image_transactions).
_CELL_W = 135
_CELL_H = 130
_PAD = 2

# Magic/elimination arithmetic lives in image_utils (magic_or_elim_value) so
# the sidebar badges (image_standings._me_badge_value) and this cell can't
# drift apart.

# Collapse a division's full name into a compact header, e.g.
# "American League East" → "AL EAST".
_LEAGUE_ABBR = {
    'American League':    'AL',
    'National League':    'NL',
    'International League': 'IL',
    'Pacific Coast League': 'PCL',
}


def _division_header(division_name):
    """Compact header for a division name, e.g. 'AL EAST' / 'NL CENTRAL'."""
    for prefix, abbr in _LEAGUE_ABBR.items():
        if division_name.startswith(prefix):
            region = division_name[len(prefix):].strip()
            return f"{abbr} {region.upper()}".strip()
    return division_name.upper()


def _find_primary_division(standings, abbr_map, primary_abbr):
    """Return (division_name, sorted_team_list) for the division that
    contains primary_abbr, or (None, None) if not found."""
    for division_name, teams in (standings or {}).items():
        for team in teams:
            if abbr_map.get(str(team.get('team_id'))) == primary_abbr:
                ordered = sorted(
                    teams,
                    key=lambda t: (t.get('divisionRank') is None, division_rank(t)),
                )
                return division_name, ordered
    return None, None


def _magic_or_elim(team, leader, is_leader, rival_losses):
    """Value string for one team's row — see image_utils.magic_or_elim_value."""
    return magic_or_elim_value(team, leader, is_leader, rival_losses)


def draw_magic_cell(Himage, sx, sy, standings_data, team_data, primary_abbr, use_logos=False):
    """Draw the primary team's division magic/elimination panel into the cell
    at pixel position (sx, sy), the same 150x150 footprint as a normal
    single-game grid cell.

    standings_data: the full dict loaded from standings.json (expects
        'standings' and 'team_abbreviation' keys).
    team_data: the teams dict (for logo lookup / abbr fallback).
    primary_abbr: the configured primary team's abbreviation, e.g. 'NYY'.
    """
    draw = ImageDraw.Draw(Himage)

    abbr_map = (standings_data or {}).get('team_abbreviation', {}) \
        or (team_data or {}).get('team_abbreviation', {})
    division_name, teams = _find_primary_division(
        (standings_data or {}).get('standings', {}), abbr_map, primary_abbr)

    font_hdr = _get_font(14)
    header = _division_header(division_name) if division_name else 'Magic #'

    # Top border + header separator + centered bold header (matches draw_box).
    draw.line([(sx, sy), (sx + _CELL_W - 1, sy)], fill=0)
    draw.line([(sx, sy + 20), (sx + _CELL_W - 1, sy + 20)], fill=0)
    hdr_w = int(font_hdr.getlength(header))
    hdr_x = sx + (_CELL_W - hdr_w) // 2
    draw.text((hdr_x, sy + 3), header, font=font_hdr, fill=0)
    draw.text((hdr_x + 1, sy + 3), header, font=font_hdr, fill=0)

    # Bottom border
    draw.line([(sx, sy + _CELL_H - 1), (sx + _CELL_W - 1, sy + _CELL_H - 1)], fill=0, width=1)

    if not teams:
        font_row = _get_font(12)
        draw.text((sx + _PAD, sy + 60), 'No standings', font=font_row, fill=0)
        return Himage

    # 9pt fuses adjacent thin strokes on the 1-bit render — never below 10pt.
    row_font_size = 12 if len(teams) <= 5 else 11
    font_row = _get_font(row_font_size)

    leader = teams[0]
    rivals = teams[1:]
    rival_losses = min(
        (t.get('league_record_losses') for t in rivals
         if t.get('league_record_losses') is not None),
        default=None,
    )

    row_h = (_CELL_H - 20) // max(len(teams), 1)
    row_pad = 2 if row_h >= 13 else 1
    logo_size = min(18, row_h)

    # Fixed columns computed once so logos/records/values line up per row.
    rank_col_w = max(
        (int(font_row.getlength(str(division_rank(t, default=i + 1)) + '.'))
         for i, t in enumerate(teams)),
        default=0,
    )
    logo_col_x = sx + _PAD + rank_col_w + 2
    rec_x = logo_col_x + (logo_size + 3 if use_logos else 0)

    for i, team in enumerate(teams):
        ry = sy + 20 + i * row_h

        rank = str(division_rank(team, default=i + 1))
        team_id = team.get('team_id')
        abbr = abbr_map.get(str(team_id), '')
        wins = team.get('league_record_wins')
        losses = team.get('league_record_losses')
        record = f'{wins}-{losses}' if wins is not None and losses is not None else ''
        value = _magic_or_elim(team, leader, i == 0, rival_losses)

        draw.text((sx + _PAD, ry + row_pad), rank + '.', font=font_row, fill=0)

        if use_logos and abbr:
            try:
                logo = _logo_small(abbr, team_id, size=logo_size)
                if logo:
                    logo_x = logo_col_x + (logo_size - logo.width) // 2
                    logo_y = ry + (row_h - logo.height) // 2 + 2
                    Himage.paste(logo, (logo_x, logo_y))
            except Exception:
                pass
        elif abbr:
            draw.text((logo_col_x, ry + row_pad), abbr, font=font_row, fill=0)

        # Value right-aligned; record fills the middle.
        val_w = int(font_row.getlength(value))
        val_x = sx + _CELL_W - val_w - _PAD
        draw.text((val_x, ry + row_pad), value, font=font_row, fill=0)

        max_rec_w = val_x - 2 - rec_x
        rec = record
        while rec and int(font_row.getlength(rec)) > max_rec_w:
            rec = rec[:-1]
        draw.text((rec_x, ry + row_pad), rec, font=font_row, fill=0)

    return Himage
