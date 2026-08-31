"""Full-screen playoff-race view: every division race and both wild-card
races at once, with magic/elimination numbers.

Built entirely from data/standings.json (already fetched daily for the
sidebar and wildcard-header strip) — no new API surface. The magic/elim
arithmetic comes from image_utils.magic_or_elim_value and the wild-card
fields from image_standings.derive_wildcard_from_standings, the same
functions the compact in-grid badges use, so this view can't drift from them.
"""
from PIL import Image, ImageDraw, ImageOps

from image_assets import _get_font
from image_utils import division_rank, magic_or_elim_value
from image_standings import derive_wildcard_from_standings, _AL_DIV_ORDER, _NL_DIV_ORDER
from image_magic import _division_header
from panel_cell import rank_column_width, truncate, paste_row_logo

EPD_WIDTH = 800
EPD_HEIGHT = 480

_HEADER_H = 30
_PANEL_COLS = 4
_PANEL_ROWS = 2
_PANEL_W = EPD_WIDTH // _PANEL_COLS                      # 200
_PANEL_H = (EPD_HEIGHT - _HEADER_H) // _PANEL_ROWS        # 225
_PANEL_PAD = 4
_CHROME_HEADER_H = 20

# Keeps the wild-card panel legible even in a hypothetical 15-team league —
# the field beyond this is well outside playoff relevance anyway.
_WC_MAX_ROWS = 10


def _panel_origin(col, row):
    return col * _PANEL_W, _HEADER_H + row * _PANEL_H


def _row_font_for(row_h):
    """Row font sized to the space actually available — division panels
    (5 rows) get a lot more room per row than the wild-card ones (up to
    _WC_MAX_ROWS). 18px is the achievable floor: _WC_MAX_ROWS rows never
    divide the body shorter than that."""
    if row_h >= 34:
        return _get_font(16)
    if row_h >= 24:
        return _get_font(13)
    return _get_font(11)


def _draw_header(Himage):
    draw = ImageDraw.Draw(Himage)
    font = _get_font(14)
    title = 'PLAYOFF RACE'
    tw = int(font.getlength(title))
    tx = (EPD_WIDTH - tw) // 2
    draw.text((tx, 7), title, font=font, fill=0)
    draw.text((tx + 1, 7), title, font=font, fill=0)
    draw.line((0, _HEADER_H - 1, EPD_WIDTH - 1, _HEADER_H - 1), fill=0, width=1)


def _draw_panel_chrome(draw, sx, sy, w, h, header):
    font = _get_font(12)
    draw.rectangle((sx, sy, sx + w - 1, sy + h - 1), outline=0, width=1)
    draw.line((sx, sy + _CHROME_HEADER_H, sx + w - 1, sy + _CHROME_HEADER_H), fill=0, width=1)
    hdr_x = sx + (w - int(font.getlength(header))) // 2
    draw.text((hdr_x, sy + 4), header, font=font, fill=0)
    draw.text((hdr_x + 1, sy + 4), header, font=font, fill=0)


def _draw_empty_panel(draw, sx, sy, w, h, header, message):
    _draw_panel_chrome(draw, sx, sy, w, h, header)
    font = _get_font(11)
    draw.text((sx + _PANEL_PAD, sy + h // 2), message, font=font, fill=0)


def _draw_team_row(Himage, draw, sx, y, row_h, w, rank_label, rank_w,
                    team_id, abbr, record, value, font_row, logo_size):
    row_pad = max(1, (row_h - getattr(font_row, 'size', 12)) // 2)

    draw.text((sx + _PANEL_PAD, y + row_pad), rank_label, font=font_row, fill=0)

    logo_x = sx + _PANEL_PAD + rank_w + 3
    if abbr:
        paste_row_logo(Himage, abbr, team_id, logo_x, y, logo_size, row_h)
    text_x = logo_x + logo_size + 4

    val_x = sx + w - int(font_row.getlength(value)) - _PANEL_PAD
    label = truncate(font_row, f'{abbr} {record}'.strip(), val_x - 4 - text_x)

    draw.text((text_x, y + row_pad), label, font=font_row, fill=0)
    draw.text((val_x, y + row_pad), value, font=font_row, fill=0)


def _draw_division_panel(Himage, draw, sx, sy, w, h, header, teams, abbr_map):
    if not teams:
        _draw_empty_panel(draw, sx, sy, w, h, header, 'No standings')
        return

    _draw_panel_chrome(draw, sx, sy, w, h, header)

    ordered = sorted(teams, key=lambda t: division_rank(t))
    n = len(ordered)
    body_h = h - _CHROME_HEADER_H - 2
    row_h = body_h // max(n, 1)
    font_row = _row_font_for(row_h)
    logo_size = min(row_h - 6, 28)

    leader = ordered[0]
    rivals = ordered[1:]
    rival_losses = min(
        (t.get('league_record_losses') for t in rivals
         if t.get('league_record_losses') is not None),
        default=None,
    )

    ranks = [str(division_rank(t, default=i + 1)) for i, t in enumerate(ordered)]
    rank_w = rank_column_width(font_row, ranks)

    for i, team in enumerate(ordered):
        y = sy + _CHROME_HEADER_H + 2 + i * row_h
        team_id = team.get('team_id')
        abbr = abbr_map.get(str(team_id), '')
        wins = team.get('league_record_wins')
        losses = team.get('league_record_losses')
        record = f'{wins}-{losses}' if wins is not None and losses is not None else ''
        value = magic_or_elim_value(team, leader, i == 0, rival_losses)
        _draw_team_row(Himage, draw, sx, y, row_h, w, ranks[i] + '.', rank_w,
                       team_id, abbr, record, value, font_row, logo_size)


def _draw_wildcard_panel(Himage, draw, sx, sy, w, h, header, teams):
    if not teams:
        _draw_empty_panel(draw, sx, sy, w, h, header, 'No standings')
        return

    _draw_panel_chrome(draw, sx, sy, w, h, header)

    shown = teams[:_WC_MAX_ROWS]
    n = len(shown)
    body_h = h - _CHROME_HEADER_H - 2
    row_h = body_h // max(n, 1)
    font_row = _row_font_for(row_h)
    logo_size = min(row_h - 6, 28)

    ranks = [str(t.get('rank', i + 1)) for i, t in enumerate(shown)]
    rank_w = rank_column_width(font_row, ranks)

    for i, team in enumerate(shown):
        y = sy + _CHROME_HEADER_H + 2 + i * row_h
        wins = team.get('wins')
        losses = team.get('losses')
        record = f'{wins}-{losses}' if wins is not None and losses is not None else ''
        value = team.get('elim_badge') or team.get('gb') or '-'
        _draw_team_row(Himage, draw, sx, y, row_h, w, ranks[i] + '.', rank_w,
                       team.get('team_id'), team.get('abbr', ''), record, value,
                       font_row, logo_size)

        # Postseason cutoff line, right after the 3rd wild-card seed.
        if i == 2 and n > 3:
            line_y = y + row_h - 1
            draw.line((sx + 2, line_y, sx + w - 3, line_y), fill=0, width=1)


def render_race_view(standings_data, team_data=None, dark_mode=False):
    """Render the full-screen playoff-race view.

    Layout: a title strip, then a 4x2 grid — AL East/Central/West/Wild Card
    on top, NL East/Central/West/Wild Card on bottom.

    Raises ValueError when standings_data has no usable division data (e.g.
    before standings.py has ever run), the same contract render_quadrant_view
    uses, so render_scoreboard can catch it and fall back to the idle screen.
    """
    standings = (standings_data or {}).get('standings') or {}
    if not standings:
        raise ValueError('no standings data')

    team_data = team_data or {}
    abbr_map = {**(team_data.get('team_abbreviation') or {}),
                **(standings_data.get('team_abbreviation') or {})}

    wildcard = derive_wildcard_from_standings(standings_data)

    image = Image.new('1', (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    _draw_header(image)

    panels = (
        [(div, _division_header(div)) for div in _AL_DIV_ORDER]
        + [('__AL_WC__', 'AL WILD CARD')]
        + [(div, _division_header(div)) for div in _NL_DIV_ORDER]
        + [('__NL_WC__', 'NL WILD CARD')]
    )

    for idx, (key, header) in enumerate(panels):
        col = idx % _PANEL_COLS
        row = idx // _PANEL_COLS
        sx, sy = _panel_origin(col, row)
        if key == '__AL_WC__':
            _draw_wildcard_panel(image, draw, sx, sy, _PANEL_W, _PANEL_H, header,
                                 wildcard.get('AL', []))
        elif key == '__NL_WC__':
            _draw_wildcard_panel(image, draw, sx, sy, _PANEL_W, _PANEL_H, header,
                                 wildcard.get('NL', []))
        else:
            _draw_division_panel(image, draw, sx, sy, _PANEL_W, _PANEL_H, header,
                                 standings.get(key, []), abbr_map)

    if dark_mode:
        image = ImageOps.invert(image.convert('L')).convert('1')

    return image


def main():
    """CLI entry point: render the playoff-race view from cached data/standings.json."""
    import argparse

    from util import load_json_file

    parser = argparse.ArgumentParser(description='Render the full-screen playoff-race view')
    parser.add_argument('--dark', action='store_true', help='Render in dark mode')
    parser.add_argument('--output', type=str, default='race_view.bmp', help='Output image path')
    parser.add_argument('--open', action='store_true', help='Auto-open image after rendering (macOS)')
    args = parser.parse_args()

    standings_data = load_json_file('standings.json')
    team_data = load_json_file('teams.json')
    if not standings_data:
        print('No cached standings.json data found — run src/standings.py first')
        return

    image = render_race_view(standings_data, team_data=team_data, dark_mode=args.dark)
    image.save(args.output)
    print(f'Image saved to {args.output}')

    if args.open:
        import platform
        import subprocess
        if platform.system() == 'Darwin':
            subprocess.run(['open', args.output], check=False)


if __name__ == '__main__':  # pragma: no cover
    main()
