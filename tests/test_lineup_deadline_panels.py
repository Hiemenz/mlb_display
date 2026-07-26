"""Tests for image_lineup and image_deadline spare-cell panels."""
import sys
import os
import pytest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# ──────────────────────────────────────────────────────────────────────────────
# image_deadline
# ──────────────────────────────────────────────────────────────────────────────

from image_deadline import _countdown, _DEADLINE_UTC


def test_countdown_before_deadline():
    before = datetime(2026, 7, 30, 0, 0, 0, tzinfo=timezone.utc)
    big, sub, is_past = _countdown(now_utc=before)
    assert not is_past
    assert 'remaining' in sub or 'deadline' in sub
    assert 'd' in big


def test_countdown_hours_only():
    near = datetime(2026, 8, 3, 18, 30, 0, tzinfo=timezone.utc)  # 3.5h before Aug 3 deadline
    big, sub, is_past = _countdown(now_utc=near)
    assert not is_past
    assert 'h' in big


def test_countdown_minutes_only():
    very_near = datetime(2026, 8, 3, 21, 40, 0, tzinfo=timezone.utc)  # 20m before Aug 3 deadline
    big, sub, is_past = _countdown(now_utc=very_near)
    assert not is_past
    assert 'm' in big and 'h' not in big


def test_countdown_past():
    after = datetime(2026, 8, 5, 0, 0, 0, tzinfo=timezone.utc)
    big, sub, is_past = _countdown(now_utc=after)
    assert is_past
    assert 'Passed' in big or 'Passed' in sub


def test_draw_deadline_cell_renders():
    try:
        from PIL import Image
    except ImportError:
        pytest.skip('PIL not available')

    from image_deadline import draw_deadline_cell

    img = Image.new('1', (800, 480), 1)
    txns = [
        {'team_abbr': 'NYY', 'player_name': 'John Smith', 'type_desc': 'Trade', 'date': '2026-07-25'},
        {'team_abbr': 'BOS', 'player_name': 'Jane Doe',   'type_desc': 'Signed', 'date': '2026-07-24'},
    ]
    result = draw_deadline_cell(img, 32, 30, txns, {})
    assert result is img


def test_draw_deadline_cell_no_transactions():
    try:
        from PIL import Image
    except ImportError:
        pytest.skip('PIL not available')

    from image_deadline import draw_deadline_cell

    img = Image.new('1', (800, 480), 1)
    result = draw_deadline_cell(img, 32, 30, [], {})
    assert result is img


# ──────────────────────────────────────────────────────────────────────────────
# image_lineup
# ──────────────────────────────────────────────────────────────────────────────

from image_lineup import _find_primary_game, game_within_minutes


NYY_LINEUP = [{'name': f'Player {i}', 'pos': 'RF'} for i in range(9)]
BOS_LINEUP = [{'name': f'Away {i}',   'pos': 'CF'} for i in range(9)]


def _make_games(has_lineup=True, game_date=None):
    home_lineup = NYY_LINEUP if has_lineup else []
    away_lineup = BOS_LINEUP if has_lineup else []
    return [{
        'game_pk': 1,
        'away_team_id': 111,   # BOS
        'home_team_id': 147,   # NYY
        'away_team_name': 'Boston Red Sox',
        'home_team_name': 'New York Yankees',
        'home_lineup': home_lineup,
        'away_lineup': away_lineup,
        'detailed_state': 'Scheduled',
        'game_date': game_date or '2026-07-25T23:05:00Z',
    }]


def test_find_primary_game_found(tmp_path, monkeypatch):
    import json
    (tmp_path / 'standings.json').write_text(json.dumps({
        'team_abbreviation': {'147': 'NYY', '111': 'BOS'}, 'standings': {},
    }))
    import util as _util
    monkeypatch.setattr(_util, '_DATA_DIR', str(tmp_path))

    game = _find_primary_game(_make_games(), 'NYY')
    assert game is not None
    assert game['home_team_id'] == 147


def test_find_primary_game_not_found(tmp_path, monkeypatch):
    import json
    (tmp_path / 'standings.json').write_text(json.dumps({
        'team_abbreviation': {'147': 'NYY', '111': 'BOS'}, 'standings': {},
    }))
    import util as _util
    monkeypatch.setattr(_util, '_DATA_DIR', str(tmp_path))

    game = _find_primary_game(_make_games(), 'LAD')
    assert game is None


def test_game_within_minutes_true():
    from datetime import timedelta
    start = datetime.now(timezone.utc) + timedelta(minutes=15)
    game = {'game_date': start.strftime('%Y-%m-%dT%H:%M:%SZ')}
    assert game_within_minutes(game, minutes=30) is True


def test_game_within_minutes_too_early():
    from datetime import timedelta
    start = datetime.now(timezone.utc) + timedelta(hours=3)
    game = {'game_date': start.strftime('%Y-%m-%dT%H:%M:%SZ')}
    assert game_within_minutes(game, minutes=30) is False


def test_game_within_minutes_past():
    from datetime import timedelta
    start = datetime.now(timezone.utc) - timedelta(minutes=10)
    game = {'game_date': start.strftime('%Y-%m-%dT%H:%M:%SZ')}
    assert game_within_minutes(game, minutes=30) is False


def test_draw_lineup_cell_with_lineup(tmp_path, monkeypatch):
    try:
        from PIL import Image
    except ImportError:
        pytest.skip('PIL not available')

    import json
    (tmp_path / 'standings.json').write_text(json.dumps({
        'team_abbreviation': {'147': 'NYY', '111': 'BOS'}, 'standings': {},
    }))
    import util as _util
    monkeypatch.setattr(_util, '_DATA_DIR', str(tmp_path))

    from image_lineup import draw_lineup_cell
    img = Image.new('1', (800, 480), 1)
    result = draw_lineup_cell(img, 32, 30, _make_games(has_lineup=True), 'NYY', {})
    assert result is img


def test_draw_lineup_cell_no_lineup(tmp_path, monkeypatch):
    try:
        from PIL import Image
    except ImportError:
        pytest.skip('PIL not available')

    import json
    (tmp_path / 'standings.json').write_text(json.dumps({
        'team_abbreviation': {'147': 'NYY', '111': 'BOS'}, 'standings': {},
    }))
    import util as _util
    monkeypatch.setattr(_util, '_DATA_DIR', str(tmp_path))

    from image_lineup import draw_lineup_cell
    img = Image.new('1', (800, 480), 1)
    result = draw_lineup_cell(img, 32, 30, _make_games(has_lineup=False), 'NYY', {})
    assert result is img
