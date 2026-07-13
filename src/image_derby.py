"""Home Run Derby bracket rendering (single elimination, 8 batters).

Data source: data/derby_bracket.json — there is no MLB Stats API endpoint for
Derby bracket progress, so this file is maintained by hand (or a small manual
update script) during the event: fill in real names/seeds ahead of time, then
flip "complete"/"winner"/"hr" as each round finishes.
"""
from image_assets import Image, ImageDraw, _get_font

EPD_WIDTH = 800
EPD_HEIGHT = 480

_HEADER_H = 46
_AREA_TOP = _HEADER_H
_AREA_H = EPD_HEIGHT - _AREA_TOP - 10

_QF_X = 15
_SF_X = 260
_FINAL_X = 500
_CHAMP_X = 715

_BOX_W_QF = 175
_BOX_W_SF = 175
_BOX_W_FINAL = 175
_BOX_H = 40  # two player rows @ ~20px each

_COL_LABEL_Y = _AREA_TOP - 14


def _slot_centers(n):
    """Evenly spaced vertical centers for n boxes across the bracket area."""
    slot_h = _AREA_H / n
    return [_AREA_TOP + slot_h * (i + 0.5) for i in range(n)]


def _player_row_text(player):
    """'J. Judge (NYY)' left side; 'TBD' when not yet determined."""
    name = player.get('name') or 'TBD'
    abbr = player.get('abbr') or ''
    label = f"{name} ({abbr})" if abbr else name
    hr = player.get('hr')
    score = '' if hr is None else str(hr)
    return label, score


def _draw_matchup_box(draw, x, y_center, w, matchup, font):
    """Draw a two-player matchup card centered at y_center. Returns box (x0,y0,x1,y1)."""
    h = _BOX_H
    y0 = int(y_center - h / 2)
    y1 = y0 + h
    draw.rectangle([x, y0, x + w, y1], outline=0, width=1)
    draw.line([x, y0 + h // 2, x + w, y0 + h // 2], fill=0, width=1)

    players = matchup.get('players', [{}, {}])
    for i, player in enumerate(players[:2]):
        row_y = y0 + (i * h // 2)
        label, score = _player_row_text(player)
        text_y = row_y + (h // 2 - 11) // 2 + 1
        draw.text((x + 4, text_y), label, font=font, fill=0)
        if score:
            sw = draw.textlength(score, font=font)
            draw.text((x + w - sw - 6, text_y), score, font=font, fill=0)
        if player.get('winner'):
            # bold the winning row by double-drawing offset by 1px
            draw.text((x + 5, text_y), label, font=font, fill=0)

    return (x, y0, x + w, y1)


def _connect(draw, box_a, box_b, target_x, target_y_center):
    """Elbow connector from the right-mid of two feeder boxes into a target box's left-mid."""
    for box in (box_a, box_b):
        x1, y0, x1r, y1 = box
        mid_y = (y0 + y1) // 2
        mid_x = (x1r + target_x) // 2
        draw.line([x1r, mid_y, mid_x, mid_y], fill=0, width=1)
        draw.line([mid_x, mid_y, mid_x, target_y_center], fill=0, width=1)
        draw.line([mid_x, target_y_center, target_x, target_y_center], fill=0, width=1)


def render_derby_bracket(derby_data, dark_mode=False):
    """Render the 8-man Home Run Derby single-elimination bracket as an 800x480 image."""
    canvas = Image.new('1', (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(canvas)

    f28 = _get_font(28)
    f14 = _get_font(14)
    f11 = _get_font(11)
    f9 = _get_font(9)

    title = "HOME RUN DERBY"
    tw = draw.textlength(title, font=f28)
    draw.text(((EPD_WIDTH - tw) / 2, 4), title, font=f28, fill=0)

    status = derby_data.get('round_status', '')
    date_str = derby_data.get('event_date', '')
    sub = f"{date_str}   {status}".strip()
    sw = draw.textlength(sub, font=f9)
    draw.text(((EPD_WIDTH - sw) / 2, 34), sub, font=f9, fill=0)

    matchups = derby_data.get('matchups', {})
    qf_list = matchups.get('qf', [])
    sf_list = matchups.get('sf', [])
    final_m = matchups.get('final', {})

    for label, x in (("QUARTERFINALS", _QF_X), ("SEMIFINALS", _SF_X),
                      ("FINAL", _FINAL_X), ("CHAMPION", _CHAMP_X)):
        draw.text((x, _COL_LABEL_Y), label, font=f9, fill=0)

    qf_centers = _slot_centers(4)
    qf_boxes = []
    for center, matchup in zip(qf_centers, qf_list):
        box = _draw_matchup_box(draw, _QF_X, center, _BOX_W_QF, matchup, f11)
        qf_boxes.append(box)

    sf_centers = [
        (qf_centers[0] + qf_centers[1]) / 2,
        (qf_centers[2] + qf_centers[3]) / 2,
    ]
    sf_boxes = []
    for i, (center, matchup) in enumerate(zip(sf_centers, sf_list)):
        box = _draw_matchup_box(draw, _SF_X, center, _BOX_W_SF, matchup, f11)
        sf_boxes.append(box)
        _connect(draw, qf_boxes[i * 2], qf_boxes[i * 2 + 1], _SF_X, center)

    final_center = (sf_centers[0] + sf_centers[1]) / 2
    final_box = _draw_matchup_box(draw, _FINAL_X, final_center, _BOX_W_FINAL, final_m, f14)
    _connect(draw, sf_boxes[0], sf_boxes[1], _FINAL_X, final_center)

    champion = derby_data.get('champion')
    champ_players = final_m.get('players', [])
    if not champion:
        for p in champ_players:
            if p.get('winner'):
                champion = p.get('name')
                break

    cx = _CHAMP_X
    cy = final_center
    draw.rectangle([cx, cy - 30, EPD_WIDTH - 10, cy + 30], outline=0, width=2)
    star = "★"
    if champion:
        sw = draw.textlength(star, font=f14)
        draw.text((cx + (EPD_WIDTH - 10 - cx - sw) / 2, cy - 24), star, font=f14, fill=0)
        cw = draw.textlength(champion, font=f14)
        draw.text((cx + (EPD_WIDTH - 10 - cx - cw) / 2, cy + 2), champion, font=f14, fill=0)
    else:
        tbd = "TBD"
        tw = draw.textlength(tbd, font=f14)
        draw.text((cx + (EPD_WIDTH - 10 - cx - tw) / 2, cy - 7), tbd, font=f14, fill=0)
    # Final -> champion connector (single feeder, not the two-box elbow helper)
    x1r = final_box[2]
    mid_x = (x1r + cx) // 2
    draw.line([x1r, final_center, mid_x, final_center], fill=0, width=1)
    draw.line([mid_x, final_center, mid_x, cy], fill=0, width=1)
    draw.line([mid_x, cy, cx, cy], fill=0, width=1)

    if dark_mode:
        from PIL import ImageOps
        canvas = ImageOps.invert(canvas.convert('L')).convert('1')

    return canvas
