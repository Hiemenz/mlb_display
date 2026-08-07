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
import panel_cell
from image_assets import _get_font, ImageDraw
from image_utils import division_rank, magic_or_elim_value

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

    header = _division_header(division_name) if division_name else 'Magic #'
    panel_cell.draw_chrome(draw, sx, sy, header)

    if not teams:
        panel_cell.draw_empty(draw, sx, sy, 'No standings', _get_font(12))
        return Himage

    # Steps down a row earlier than the other panels: these rows carry a third
    # (record) column, so they run out of width sooner.
    font_row = panel_cell.row_font(len(teams), dense_above=5)

    leader = teams[0]
    rivals = teams[1:]
    rival_losses = min(
        (t.get('league_record_losses') for t in rivals
         if t.get('league_record_losses') is not None),
        default=None,
    )

    row_h, row_pad, logo_size = panel_cell.row_metrics(len(teams))

    ranks = [str(division_rank(t, default=i + 1)) for i, t in enumerate(teams)]
    logo_col_x = sx + panel_cell.PAD + panel_cell.rank_column_width(font_row, ranks) + 2
    rec_x = logo_col_x + (logo_size + 3 if use_logos else 0)

    for i, team in enumerate(teams):
        ry = sy + panel_cell.HEADER_H + i * row_h

        team_id = team.get('team_id')
        abbr = abbr_map.get(str(team_id), '')
        wins = team.get('league_record_wins')
        losses = team.get('league_record_losses')
        record = f'{wins}-{losses}' if wins is not None and losses is not None else ''
        value = _magic_or_elim(team, leader, i == 0, rival_losses)

        draw.text((sx + panel_cell.PAD, ry + row_pad), ranks[i] + '.', font=font_row, fill=0)

        if use_logos and abbr:
            panel_cell.paste_row_logo(Himage, abbr, team_id, logo_col_x, ry, logo_size, row_h)
        elif abbr:
            # Without logos the abbreviation stands in for the team, in the
            # column the logo would have occupied.
            draw.text((logo_col_x, ry + row_pad), abbr, font=font_row, fill=0)

        # Value right-aligned; the record fills whatever is left in the middle.
        val_x = sx + panel_cell.CELL_W - int(font_row.getlength(value)) - panel_cell.PAD
        draw.text((val_x, ry + row_pad), value, font=font_row, fill=0)

        rec = panel_cell.truncate(font_row, record, val_x - 2 - rec_x)
        draw.text((rec_x, ry + row_pad), rec, font=font_row, fill=0)

    return Himage
