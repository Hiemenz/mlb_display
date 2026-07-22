"""Draw a recent-news headlines cell (150×150) for an empty grid slot.

Shows the most recent MLB headlines fetched by fetch_news.fetch_news()
(team-scoped when configured). Unlike the row-based leaders/transactions
panels, headlines are variable-length, so each is word-wrapped to the cell
width and drawn as a small bulleted block until the cell runs out of room.
"""
from image_assets import _get_font, ImageDraw

# Matches the visible footprint of a normal single-game grid box
# (mirrors image_leaders / image_transactions).
_CELL_W = 135
_CELL_H = 130
_PAD = 2
_HEADER = 'News'

_LINE_H = 13          # per-line height at row font size 11
_ITEM_GAP = 3         # blank space between consecutive headlines
_BULLET_R = 1         # bullet dot radius
_INDENT = 7           # text indent to clear the bullet
_MAX_LINES_PER_ITEM = 3


def _wrap(font, text, max_w):
    """Greedy word-wrap ``text`` to lines no wider than ``max_w`` pixels."""
    lines = []
    cur = ''
    for word in text.split():
        trial = f'{cur} {word}'.strip()
        if not cur or int(font.getlength(trial)) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def draw_news_cell(Himage, sx, sy, news_data, team_data, use_logos=False):
    """Draw a news-headlines panel into the cell at pixel position (sx, sy),
    the same 150x150 footprint as a normal single-game grid cell.

    news_data: the dict loaded from news.json (expects an 'articles' list),
        or the article list directly.
    team_data: unused, kept for parity with the other panel renderers.
    """
    draw = ImageDraw.Draw(Himage)

    if isinstance(news_data, dict):
        articles = news_data.get('articles', [])
    else:
        articles = list(news_data or [])

    font_hdr = _get_font(14)
    # 9pt fuses adjacent thin strokes on the 1-bit render — never below 10pt.
    font_row = _get_font(11)

    # Top border + header separator + centered bold header (matches draw_box).
    draw.line([(sx, sy), (sx + _CELL_W - 1, sy)], fill=0)
    draw.line([(sx, sy + 20), (sx + _CELL_W - 1, sy + 20)], fill=0)
    hdr_w = int(font_hdr.getlength(_HEADER))
    hdr_x = sx + (_CELL_W - hdr_w) // 2
    draw.text((hdr_x, sy + 3), _HEADER, font=font_hdr, fill=0)
    draw.text((hdr_x + 1, sy + 3), _HEADER, font=font_hdr, fill=0)

    # Bottom border
    draw.line([(sx, sy + _CELL_H - 1), (sx + _CELL_W - 1, sy + _CELL_H - 1)], fill=0, width=1)

    if not articles:
        draw.text((sx + _PAD, sy + 60), 'No news', font=font_row, fill=0)
        return Himage

    body_top = sy + 23
    body_bottom = sy + _CELL_H - 2
    text_x = sx + _PAD + _INDENT
    max_w = _CELL_W - _PAD - _INDENT - _PAD

    y = body_top
    for art in articles:
        headline = art.get('headline', '') if isinstance(art, dict) else str(art)
        if not headline:
            continue
        if y + _LINE_H > body_bottom:
            break

        lines = _wrap(font_row, headline, max_w)[:_MAX_LINES_PER_ITEM]

        # bullet dot aligned to the first line's text baseline-ish
        by = y + _LINE_H // 2
        draw.ellipse([(sx + _PAD, by - _BULLET_R), (sx + _PAD + 2 * _BULLET_R, by + _BULLET_R)], fill=0)

        for ln in lines:
            if y + _LINE_H > body_bottom:
                break
            draw.text((text_x, y), ln, font=font_row, fill=0)
            y += _LINE_H
        y += _ITEM_GAP

    return Himage
