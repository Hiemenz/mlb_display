"""Tests for image_lineup and image_deadline spare-cell panels."""
import sys
import os
import pytest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# ──────────────────────────────────────────────────────────────────────────────
# image_deadline
# ──────────────────────────────────────────────────────────────────────────────

from image_deadline import _countdown, _DEADLINE_UTC, in_countdown_window


def test_in_countdown_window_within_two_weeks():
    within = datetime(2026, 7, 25, 0, 0, 0, tzinfo=timezone.utc)  # 9 days before deadline
    assert in_countdown_window(now_utc=within)


def test_in_countdown_window_more_than_two_weeks_out():
    far = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)  # ~2 months before deadline
    assert not in_countdown_window(now_utc=far)


def test_in_countdown_window_after_deadline():
    after = datetime(2026, 8, 5, 0, 0, 0, tzinfo=timezone.utc)
    assert not in_countdown_window(now_utc=after)


def test_countdown_uses_config_trade_deadline_over_fallback():
    """A config trade_deadline in a different year overrides the hardcoded fallback."""
    config = {'trade_deadline': '2027-07-27 18:00'}
    just_before = datetime(2027, 7, 27, 21, 0, 0, tzinfo=timezone.utc)  # 1h before 22:00 UTC
    big, sub, is_past = _countdown(now_utc=just_before, config=config)
    assert not is_past
    assert 'h' in big
    # The hardcoded 2026 fallback would already show this as long past.
    assert in_countdown_window(now_utc=just_before, config=config)
    assert not in_countdown_window(now_utc=just_before)


def test_countdown_falls_back_on_invalid_config_value():
    config = {'trade_deadline': 'not-a-date'}
    before = datetime(2026, 7, 30, 0, 0, 0, tzinfo=timezone.utc)
    big, sub, is_past = _countdown(now_utc=before, config=config)
    assert not is_past
    assert 'd' in big


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


def _make_games(has_lineup=True, game_date=None, **extra):
    home_lineup = NYY_LINEUP if has_lineup else []
    away_lineup = BOS_LINEUP if has_lineup else []
    g = {
        'game_pk': 1,
        'away_team_id': 111,   # BOS
        'home_team_id': 147,   # NYY
        'away_team_name': 'Boston Red Sox',
        'home_team_name': 'New York Yankees',
        'home_lineup': home_lineup,
        'away_lineup': away_lineup,
        'detailed_state': 'Scheduled',
        'game_date': game_date or '2026-07-25T23:05:00Z',
    }
    g.update(extra)
    return [g]


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


def test_game_within_minutes_no_game_date():
    assert game_within_minutes({}, minutes=30) is False
    assert game_within_minutes({'game_date': ''}, minutes=30) is False


def test_game_within_minutes_invalid_date():
    assert game_within_minutes({'game_date': 'not-a-date'}, minutes=30) is False


def _standings_monkeypatch(tmp_path, monkeypatch):
    import json
    (tmp_path / 'standings.json').write_text(json.dumps({
        'team_abbreviation': {'147': 'NYY', '111': 'BOS'}, 'standings': {},
    }))
    import util as _util
    monkeypatch.setattr(_util, '_DATA_DIR', str(tmp_path))


def test_draw_lineup_cell_with_game_start(tmp_path, monkeypatch):
    """game_start with an AM/PM space triggers the time_ampm split branch."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip('PIL not available')
    _standings_monkeypatch(tmp_path, monkeypatch)
    from image_lineup import draw_lineup_cell
    img = Image.new('1', (800, 480), 1)
    games = _make_games(has_lineup=True, game_start='7:05 PM')
    result = draw_lineup_cell(img, 32, 30, games, 'NYY', {})
    assert result is img


def test_draw_lineup_cell_team_not_found(tmp_path, monkeypatch):
    """Primary team not in games list → fallback 'Lineups' header, return early."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip('PIL not available')
    _standings_monkeypatch(tmp_path, monkeypatch)
    from image_lineup import draw_lineup_cell
    img = Image.new('1', (800, 480), 1)
    result = draw_lineup_cell(img, 32, 30, _make_games(), 'LAD', {})
    assert result is img


def test_draw_lineup_cell_short_lineup(tmp_path, monkeypatch):
    """Lineup with < 9 players exercises the empty-slot branch."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip('PIL not available')
    _standings_monkeypatch(tmp_path, monkeypatch)
    from image_lineup import draw_lineup_cell
    img = Image.new('1', (800, 480), 1)
    short = [{'name': f'Player {i}', 'pos': 'CF'} for i in range(4)]
    games = _make_games(has_lineup=False)
    games[0]['away_lineup'] = short
    games[0]['home_lineup'] = short
    result = draw_lineup_cell(img, 32, 30, games, 'NYY', {})
    assert result is img


def test_draw_lineup_cell_long_name_and_pitcher(tmp_path, monkeypatch):
    """Very long player/pitcher names trigger truncation loops."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip('PIL not available')
    _standings_monkeypatch(tmp_path, monkeypatch)
    from image_lineup import draw_lineup_cell
    img = Image.new('1', (800, 480), 1)
    long_name = [{'name': 'Bartholomew Witherspoon-Fitzgerald', 'pos': 'CF'}] * 9
    games = _make_games(
        has_lineup=False,
        away_probable='Bartholomew Witherspoon-Fitzgerald',
        home_probable='Bartholomew Witherspoon-Fitzgerald',
    )
    games[0]['away_lineup'] = long_name
    games[0]['home_lineup'] = long_name
    result = draw_lineup_cell(img, 32, 30, games, 'NYY', {})
    assert result is img


def test_image_grid_spare_cell_lineup(tmp_path, monkeypatch):
    """image_grid dispatches to draw_lineup_cell when show_lineup_panel=True and game within 45 min."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip('PIL not available')

    import json
    from datetime import datetime, timezone, timedelta
    from unittest.mock import patch

    _standings_monkeypatch(tmp_path, monkeypatch)

    soon = (datetime.now(timezone.utc) + timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%SZ')
    games = _make_games(has_lineup=True, game_date=soon)

    team_data = {'team_abbreviation': {'147': 'NYY', '111': 'BOS'}}
    config = {
        'timezone': 'America/Chicago',
        'use_team_logos': False,
        'small_logo_x_offset': 2,
        'wide_cell_always': False,
        'wide_cell_featured': False,
        'scoreboard_live_details': True,
        'final_linescore_minutes': 60,
        'show_config_qr': False,
        'primary': 'NYY',
        'show_lineup_panel': True,
    }

    with patch('image_grid.load_yaml_file', return_value=config), \
         patch('image_box.load_yaml_file', return_value=config):
        from image_grid import draw_out_of_town_score_board
        img = Image.new('1', (800, 480), 255)
        result = draw_out_of_town_score_board(
            img, games, team_data, '2026-07-26',
            use_logos=False,
            logo_x_offset=2,
        )
    assert result is not None
