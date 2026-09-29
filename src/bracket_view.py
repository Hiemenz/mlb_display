"""Full-screen postseason bracket: Wild Card through World Series in one tree.

AL runs left-to-right (Wild Card, Division Series, LCS), the World Series sits
in the middle, and the NL mirrors the AL on the right.

Built from data/playoff_bracket.json plus data/standings.json (league and seed
lookup). MLB publishes the whole tree up front with placeholder teams for
undecided slots ("ATL/PHI", "AL Low"), so unresolved series are drawn as-is;
a slot with no series at all is drawn as an empty TBD box.
"""
from PIL import Image, ImageDraw, ImageOps

from image_assets import _get_font
from image_standings import _AL_DIVS, _NL_DIVS
from panel_cell import paste_row_logo, truncate

EPD_WIDTH = 800
EPD_HEIGHT = 480

_HEADER_H = 30
_LABEL_H = 18
_BAND_W = 114
_BOX_W = 98
_ROW_H = 34
_CAPTION_H = 16
_BOX_H = 2 * _ROW_H + _CAPTION_H
_LOGO = 26
_PAD = 4

# Band index -> (league, round); the World Series band has no league.
_BANDS = (
    ('AL', 'WC'), ('AL', 'DS'), ('AL', 'CS'), (None, 'WS'),
    ('NL', 'CS'), ('NL', 'DS'), ('NL', 'WC'),
)
_ROUND_LABELS = {'WC': 'WILD CARD', 'DS': 'DIVISION', 'CS': 'LCS', 'WS': 'WORLD SERIES'}
_MAX_SEED = 6


def _team_maps(standings_data):
    """({team_id: league}, {team_id: seed}, {abbr: league}) from standings."""
    league, seed, abbr_league = {}, {}, {}
    abbrs = standings_data.get('team_abbreviation') or {}
    for div, teams in (standings_data.get('standings') or {}).items():
        lg = 'AL' if div in _AL_DIVS else 'NL' if div in _NL_DIVS else None
        if lg is None:
            continue
        for t in teams:
            tid = str(t.get('team_id', ''))
            if not tid:
                continue
            league[tid] = lg
            if abbrs.get(tid):
                abbr_league[abbrs[tid]] = lg
            try:
                seed[tid] = int(t.get('league_rank') or 99)
            except (ValueError, TypeError):
                seed[tid] = 99
    return league, seed, abbr_league


def _series_league(series, team_league, abbr_league):
    """League of a series, from either team's id/abbr, else an 'AL ...'/'NL ...' placeholder."""
    for side in ('home', 'away'):
        lg = team_league.get(str(series.get(f'{side}_id', '')))
        if lg:
            return lg
    for side in ('home', 'away'):
        abbr = series.get(f'{side}_abbr') or ''
        for token in abbr.split('/'):
            if token in abbr_league:
                return abbr_league[token]
        if abbr[:3] in ('AL ', 'NL '):
            return abbr[:2]
    return None


def _feeds(feeder, target):
    """True when the ``feeder`` series' winner takes a place in ``target``."""
    tokens = set((target.get('away_abbr') or '').split('/')) | set((target.get('home_abbr') or '').split('/'))
    ids = {str(target.get('away_id', '')), str(target.get('home_id', ''))}
    return bool(
        {feeder.get('away_abbr'), feeder.get('home_abbr')} & tokens
        or {str(feeder.get('away_id', '')), str(feeder.get('home_id', ''))} & ids
    )


def _best_seed(series, team_seed):
    seeds = [team_seed.get(str(series.get(f'{s}_id', '')), 99) for s in ('home', 'away')]
    return min(seeds)


def _build_slots(bracket_data, team_league, team_seed, abbr_league):
    """{'AL': {'WC': [top, bottom], 'DS': [...], 'CS': [s]}, 'NL': {...}, 'WS': s}.

    A missing series is None. DS boxes are ordered by the better seed they
    hold (the bye team, #1 on top); each WC box is then lined up beside the DS
    series it feeds so the connectors run straight.
    """
    by_round = {'WC': [], 'DS': [], 'CS': [], 'WS': []}
    for s in bracket_data.get('series', []):
        if s.get('round') in by_round:
            by_round[s['round']].append(s)

    slots = {'WS': (by_round['WS'] or [None])[0]}
    for lg in ('AL', 'NL'):
        mine = {rnd: [s for s in by_round[rnd]
                      if _series_league(s, team_league, abbr_league) == lg]
                for rnd in ('WC', 'DS', 'CS')}
        ds = sorted(mine['DS'], key=lambda s: _best_seed(s, team_seed))[:2]
        ds += [None] * (2 - len(ds))

        wc_pool = list(mine['WC'])
        wc = []
        for target in ds:
            match = next((w for w in wc_pool if target and _feeds(w, target)), None)
            if match:
                wc_pool.remove(match)
            wc.append(match)
        # Whatever the feeder match missed fills the empty slots, 4v5 above 3v6.
        wc_pool.sort(key=lambda s: -_best_seed(s, team_seed))
        wc = [w if w is not None else (wc_pool.pop(0) if wc_pool else None) for w in wc]

        slots[lg] = {'WC': wc, 'DS': ds, 'CS': (mine['CS'] or [None])[:1]}
    return slots


def _slot_center_y(index, count):
    body_top = _HEADER_H + _LABEL_H
    body_h = EPD_HEIGHT - body_top
    return body_top + int(body_h * (2 * index + 1) / (2 * count))


def _band_x(band):
    return 1 + band * _BAND_W


def _box_origin(band, cy):
    return _band_x(band) + (_BAND_W - _BOX_W) // 2, cy - _BOX_H // 2


def _caption(series):
    if series is None:
        return ''
    if series.get('complete'):
        return 'FINAL'
    aw, hw = series.get('away_wins', 0), series.get('home_wins', 0)
    if aw == hw == 0:
        return ''
    if aw == hw:
        return f'Tied {aw}-{hw}'
    lead, lead_w, trail_w = ((series.get('away_abbr'), aw, hw) if aw > hw
                             else (series.get('home_abbr'), hw, aw))
    return f'{lead} {lead_w}-{trail_w}'


def _draw_team_row(image, draw, x, y, side, series, team_seed, font):
    """One team row: seed, logo, abbr, wins. Placeholders get text only."""
    tid = str(series.get(f'{side}_id', ''))
    abbr = series.get(f'{side}_abbr') or 'TBD'
    wins = series.get(f'{side}_wins', 0)
    seed = team_seed.get(tid)
    is_real = seed is not None
    winner = series.get('complete') and series.get('winner_abbr') == abbr
    loser = series.get('complete') and not winner

    if winner:
        draw.rectangle((x + 1, y, x + _BOX_W - 2, y + _ROW_H - 1), fill=0)
    fill = 255 if winner else 0

    text_y = y + (_ROW_H - getattr(font, 'size', 12)) // 2 - 1
    cursor = x + _PAD
    if is_real:
        if seed <= _MAX_SEED:
            draw.text((cursor, text_y), str(seed), font=font, fill=fill)
        cursor += 10
        if not winner:
            paste_row_logo(image, abbr, tid, cursor, y, _LOGO, _ROW_H)
        cursor += _LOGO + 3

    wins_txt = str(wins) if (is_real or wins) else ''
    wins_w = int(font.getlength(wins_txt)) if wins_txt else 0
    label = truncate(font, abbr, x + _BOX_W - _PAD - wins_w - 3 - cursor)
    draw.text((cursor, text_y), label, font=font, fill=fill)
    if wins_txt:
        draw.text((x + _BOX_W - _PAD - wins_w, text_y), wins_txt, font=font, fill=fill)

    if loser:
        mid = y + _ROW_H // 2
        draw.line((x + _PAD, mid, x + _BOX_W - _PAD, mid), fill=0, width=1)


def _draw_box(image, draw, x, y, series, team_seed):
    draw.rectangle((x, y, x + _BOX_W - 1, y + _BOX_H - 1), outline=0, width=1)
    font = _get_font(15)
    if series is None:
        for i in range(2):
            ry = y + i * _ROW_H
            draw.text((x + _PAD, ry + (_ROW_H - 15) // 2 - 1), 'TBD', font=font, fill=0)
        draw.line((x, y + _ROW_H, x + _BOX_W - 1, y + _ROW_H), fill=0, width=1)
        draw.line((x, y + 2 * _ROW_H, x + _BOX_W - 1, y + 2 * _ROW_H), fill=0, width=1)
        return

    for i, side in enumerate(('away', 'home')):
        _draw_team_row(image, draw, x, y + i * _ROW_H, side, series, team_seed, font)
    draw.line((x, y + _ROW_H, x + _BOX_W - 1, y + _ROW_H), fill=0, width=1)
    draw.line((x, y + 2 * _ROW_H, x + _BOX_W - 1, y + 2 * _ROW_H), fill=0, width=1)

    caption = _caption(series)
    if caption:
        cap_font = _get_font(10)
        caption = truncate(cap_font, caption, _BOX_W - 2 * _PAD)
        cw = int(cap_font.getlength(caption))
        draw.text((x + (_BOX_W - cw) // 2, y + 2 * _ROW_H + 2), caption, font=cap_font, fill=0)


def _draw_connector(draw, x_from, y_from, x_to, y_to):
    """Elbow from one box's edge to the next round's box edge."""
    mid = (x_from + x_to) // 2
    draw.line((x_from, y_from, mid, y_from), fill=0, width=1)
    if y_from != y_to:
        draw.line((mid, y_from, mid, y_to), fill=0, width=1)
    draw.line((mid, y_to, x_to, y_to), fill=0, width=1)


def _draw_header(draw):
    font = _get_font(14)
    title = 'POSTSEASON BRACKET'
    tx = (EPD_WIDTH - int(font.getlength(title))) // 2
    draw.text((tx, 7), title, font=font, fill=0)
    draw.text((tx + 1, 7), title, font=font, fill=0)
    for text, x in (('AL', 8), ('NL', EPD_WIDTH - 8 - int(font.getlength('NL')))):
        draw.text((x, 7), text, font=font, fill=0)
        draw.text((x + 1, 7), text, font=font, fill=0)
    draw.line((0, _HEADER_H - 1, EPD_WIDTH - 1, _HEADER_H - 1), fill=0, width=1)


def _draw_round_labels(draw):
    font = _get_font(10)
    for band, (_lg, rnd) in enumerate(_BANDS):
        label = _ROUND_LABELS[rnd]
        lw = int(font.getlength(label))
        draw.text((_band_x(band) + (_BAND_W - lw) // 2, _HEADER_H + 3), label, font=font, fill=0)


def render_bracket_view(bracket_data, standings_data=None, dark_mode=False):
    """Render the full postseason tree.

    Raises ValueError when there is no bracket data yet, the same contract as
    render_race_view, so render_scoreboard can fall back instead of drawing an
    empty tree.
    """
    if not (bracket_data or {}).get('series'):
        raise ValueError('no playoff bracket data')

    team_league, team_seed, abbr_league = _team_maps(standings_data or {})
    slots = _build_slots(bracket_data, team_league, team_seed, abbr_league)

    image = Image.new('1', (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    _draw_header(draw)
    _draw_round_labels(draw)

    # (band, center_y) of each drawn box, for wiring connectors afterwards.
    placed = {}
    for band, (lg, rnd) in enumerate(_BANDS):
        if rnd == 'WS':
            series_list = [slots['WS']]
        else:
            series_list = slots[lg][rnd]
        count = len(series_list)
        for i, series in enumerate(series_list):
            cy = _slot_center_y(i, count)
            x, y = _box_origin(band, cy)
            _draw_box(image, draw, x, y, series, team_seed)
            placed[(band, i)] = (x, y, cy)

    # Connectors: left half flows right, right half flows left.
    for src_band, dst_band, pairs in (
        (0, 1, ((0, 0), (1, 1))), (1, 2, ((0, 0), (1, 0))), (2, 3, ((0, 0),)),
        (6, 5, ((0, 0), (1, 1))), (5, 4, ((0, 0), (1, 0))), (4, 3, ((0, 0),)),
    ):
        going_right = src_band < dst_band
        for src_i, dst_i in pairs:
            sx, _sy, scy = placed[(src_band, src_i)]
            dx, _dy, dcy = placed[(dst_band, dst_i)]
            if going_right:
                _draw_connector(draw, sx + _BOX_W, scy, dx, dcy)
            else:
                _draw_connector(draw, sx, scy, dx + _BOX_W, dcy)

    if dark_mode:
        image = ImageOps.invert(image.convert('L')).convert('1')
    return image


def main():
    """CLI entry point: render the bracket from cached data/playoff_bracket.json."""
    import argparse

    from util import load_json_file

    parser = argparse.ArgumentParser(description='Render the full-screen postseason bracket')
    parser.add_argument('--dark', action='store_true', help='Render in dark mode')
    parser.add_argument('--output', type=str, default='bracket_view.bmp', help='Output image path')
    parser.add_argument('--open', action='store_true', help='Auto-open image after rendering (macOS)')
    args = parser.parse_args()

    bracket_data = load_json_file('playoff_bracket.json')
    standings_data = load_json_file('standings.json')
    if not bracket_data:
        print('No cached playoff_bracket.json found — run src/standings.py first')
        return
    try:
        image = render_bracket_view(bracket_data, standings_data, dark_mode=args.dark)
    except ValueError as e:
        print(f'Bracket view unavailable: {e}')
        return
    image.save(args.output)
    print(f'Image saved to {args.output}')

    if args.open:
        import platform
        import subprocess
        if platform.system() == 'Darwin':
            subprocess.run(['open', args.output], check=False)


if __name__ == '__main__':  # pragma: no cover
    main()
