"""Shared layout primitives for the 135x130 panel cells that fill empty grid slots.

Six panels — leaders, hot hitters, hot arms, magic numbers, transactions and
news — all occupy a normal single-game grid slot and are drawn to look like one.
Each had reimplemented the same chrome: the two top rules with a centred bold
header between them, the bottom rule, the empty-state message, and (for the
ranked panels) the rank/logo/name/value column arithmetic.

Keeping six copies in step by hand did not work. image_streaks and
image_scoreless had drifted into byte-identical duplicates of each other, and
image_streaks still carried a no-op left over from a since-removed abbreviation
fallback. This module is the single definition; the panels supply only what
actually differs between them.

The footprint matches the visible extent of a game box (``horizonta_len`` by
``vertical_len + 20`` in image_box.draw_box), not the full 150x150 grid slot,
so a panel and a game tile line up exactly.
"""
from image_assets import _get_font, _logo_small

CELL_W = 135
CELL_H = 130
PAD = 2

# The header band: both rules and the text baseline between them.
HEADER_H = 20
_HEADER_TEXT_Y = 3


def header_font():
    """Font for a panel header — the same size and weight as draw_box's 'Final'."""
    return _get_font(14)


def row_font(n_entries, dense_above=6):
    """Row font, one step smaller once the rows get tight.

    Never goes below 10pt: at 9pt adjacent thin strokes (e.g. 'r' next to 'n')
    visually fuse on the 1-bit e-ink render.

    ``dense_above`` is the last entry count that still gets the larger size.
    The magic panel steps down one row earlier than the rest because its rows
    carry a third column.
    """
    return _get_font(12 if n_entries <= dense_above else 11)


def draw_chrome(draw, sx, sy, header, font=None):
    """Draw the panel frame: top rule, header separator, centred bold header
    and bottom rule.

    Bold is the renderer's 1px-offset double draw rather than a bold font face,
    matching how draw_box emphasises text.
    """
    font = font or header_font()
    draw.line([(sx, sy), (sx + CELL_W - 1, sy)], fill=0)
    draw.line([(sx, sy + HEADER_H), (sx + CELL_W - 1, sy + HEADER_H)], fill=0)

    hdr_x = sx + (CELL_W - int(font.getlength(header))) // 2
    draw.text((hdr_x, sy + _HEADER_TEXT_Y), header, font=font, fill=0)
    draw.text((hdr_x + 1, sy + _HEADER_TEXT_Y), header, font=font, fill=0)

    draw.line([(sx, sy + CELL_H - 1), (sx + CELL_W - 1, sy + CELL_H - 1)], fill=0, width=1)


def draw_empty(draw, sx, sy, message, font):
    """Draw a panel's empty-state message in the vertical middle of the body."""
    draw.text((sx + PAD, sy + 60), message, font=font, fill=0)


def row_metrics(n_rows):
    """Return ``(row_h, row_pad, logo_size)`` for ``n_rows`` evenly-split rows.

    The body is everything below the header separator. row_pad tightens by a
    pixel once rows are short enough that the text would otherwise touch the
    row above.
    """
    row_h = (CELL_H - HEADER_H) // max(n_rows, 1)
    return row_h, (2 if row_h >= 13 else 1), min(18, row_h)


def rank_column_width(font, labels):
    """Width of the widest rank label, so every row's logo and name start at the
    same x regardless of that row's own rank string."""
    return max((int(font.getlength(str(label) + '.')) for label in labels), default=0)


def truncate(font, text, max_w):
    """Trim from the right until ``text`` fits ``max_w``."""
    while text and int(font.getlength(text)) > max_w:
        text = text[:-1]
    return text


def paste_row_logo(Himage, abbr, team_id, logo_col_x, ry, logo_size, row_h):
    """Paste a team logo centred in its fixed column and row band.

    Centring matters because logos preserve their aspect ratio and so are not
    square; without it, rows visibly stagger. A missing or unreadable logo is
    not an error — the panel just renders without it.
    """
    try:
        logo = _logo_small(abbr, team_id, size=logo_size)
        if logo:
            Himage.paste(logo, (logo_col_x + (logo_size - logo.width) // 2,
                                ry + (row_h - logo.height) // 2 + 2))
    except Exception:
        pass


def draw_ranked_rows(Himage, draw, sx, sy, entries, font_row, value_of,
                     abbr_map=None, use_logos=False, name_gap=2):
    """Draw the rank / logo / name / right-aligned-value row layout.

    Shared by the leaders, hot-hitters and hot-arms panels, which differ only in
    how a row's value string is derived — ``value_of(entry)`` supplies that.

    Each entry is a dict with 'rank', 'name', 'team_id' and optionally 'abbr'.
    Ranks fall back to positional index, so a feed that omits them still renders
    1..n rather than a column of 'None'.
    """
    abbr_map = abbr_map or {}
    row_h, row_pad, logo_size = row_metrics(len(entries))

    ranks = [str(e.get('rank', i + 1)) for i, e in enumerate(entries)]
    logo_col_x = sx + PAD + rank_column_width(font_row, ranks) + 2
    name_x = logo_col_x + (logo_size + name_gap if use_logos else 0)

    for i, entry in enumerate(entries):
        ry = sy + HEADER_H + i * row_h
        team_id = entry.get('team_id', '')
        abbr = entry.get('abbr') or abbr_map.get(team_id, '')
        value = value_of(entry)

        draw.text((sx + PAD, ry + row_pad), ranks[i] + '.', font=font_row, fill=0)

        if use_logos and abbr:
            paste_row_logo(Himage, abbr, team_id, logo_col_x, ry, logo_size, row_h)

        # Measure the value first so the name gets all the space that's left
        # rather than a fixed reservation.
        val_x = sx + CELL_W - int(font_row.getlength(value)) - PAD
        name = truncate(font_row, entry.get('name', ''), val_x - 2 - name_x)

        draw.text((name_x, ry + row_pad), name, font=font_row, fill=0)
        draw.text((val_x, ry + row_pad), value, font=font_row, fill=0)

    return Himage
