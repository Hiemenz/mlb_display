"""Tests for render_scoreboard.py — the CLI orchestrator tying fetch+render together.

Covers _get_display_mode (pure), _render_single_game_mode (mocked view/fetch
calls), render() (mocked generate_image.orchestrate_score_board /
_render_single_game_mode so we test render()'s own dispatch/save logic),
_pixel_diff_bands (direct, synthetic images), and a light argparse smoke test
for main(). Follows the local fixture-builder / mock-don't-hit-real-files
style established in tests/test_wide_cell.py and tests/test_golden_scoreboard.py.
"""
from unittest.mock import patch

import pytest

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")

import render_scoreboard


# ---------------------------------------------------------------------------
# 1. _get_display_mode — pure function, no mocking needed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('mode_value', ['scoreboard', 'linescore', 'field', 'scorecard', 'pitch'])
def test_get_display_mode_explicit(mode_value):
    config = {'display_mode': mode_value}
    assert render_scoreboard._get_display_mode(config) == mode_value


def test_get_display_mode_invalid_falls_through_to_scoreboard_true():
    config = {'display_mode': 'not-a-real-mode', 'scoreboard': True}
    assert render_scoreboard._get_display_mode(config) == 'scoreboard'


def test_get_display_mode_invalid_falls_through_to_linescore():
    config = {'display_mode': 'bogus', 'scoreboard': False}
    assert render_scoreboard._get_display_mode(config) == 'linescore'


def test_get_display_mode_scoreboard_true():
    assert render_scoreboard._get_display_mode({'scoreboard': True}) == 'scoreboard'


def test_get_display_mode_scoreboard_false():
    assert render_scoreboard._get_display_mode({'scoreboard': False}) == 'linescore'


def test_get_display_mode_default_when_absent():
    """Neither display_mode nor scoreboard key present → defaults to 'scoreboard'
    (config.get('scoreboard', True) defaults True)."""
    assert render_scoreboard._get_display_mode({}) == 'scoreboard'


# ---------------------------------------------------------------------------
# 2. _render_single_game_mode
# ---------------------------------------------------------------------------

def _game(game_pk=555, away_team_id=119, home_team_id=137):
    return {'game_pk': game_pk, 'away_team_id': away_team_id, 'home_team_id': home_team_id}


_TEAM_DATA = {'team_abbreviation': {'119': 'LAD', '137': 'SF'}}


@needs_pil
def test_render_single_game_mode_field(tmp_path):
    fake_image = Image.new('1', (800, 480), 255)
    out_path = str(tmp_path / 'out.bmp')
    with patch('render_scoreboard.select_game', return_value=_game()), \
         patch('render_scoreboard.fetch_field_view_data', return_value={'x': 1}) as m_fetch, \
         patch('render_scoreboard.render_field_view', return_value=fake_image) as m_render:
        result = render_scoreboard._render_single_game_mode(
            'field', [], _TEAM_DATA, {'primary': 'LAD'}, output_path=out_path)
    assert result is fake_image
    m_fetch.assert_called_once_with(555)
    m_render.assert_called_once()
    import os
    assert os.path.isfile(out_path)


@needs_pil
def test_render_single_game_mode_scorecard():
    fake_image = Image.new('1', (800, 480), 255)
    with patch('render_scoreboard.select_game', return_value=_game()), \
         patch('render_scoreboard.fetch_scorecard_data', return_value={}) as m_fetch, \
         patch('render_scoreboard.render_scorecard_view', return_value=fake_image) as m_render:
        result = render_scoreboard._render_single_game_mode(
            'scorecard', [], _TEAM_DATA, {}, output_path=None)
    assert result is fake_image
    m_fetch.assert_called_once_with(555)
    m_render.assert_called_once()


@needs_pil
def test_render_single_game_mode_pitch():
    fake_image = Image.new('1', (800, 480), 255)
    with patch('render_scoreboard.select_game', return_value=_game()), \
         patch('render_scoreboard.fetch_pitch_view_data', return_value={}) as m_fetch, \
         patch('render_scoreboard.render_pitch_view', return_value=fake_image) as m_render:
        result = render_scoreboard._render_single_game_mode(
            'pitch', [], _TEAM_DATA, {}, output_path=None)
    assert result is fake_image
    m_fetch.assert_called_once_with(555)
    m_render.assert_called_once()


def test_render_single_game_mode_no_game_found():
    with patch('render_scoreboard.select_game', return_value=None):
        result = render_scoreboard._render_single_game_mode('field', [], _TEAM_DATA, {})
    assert result is None


def test_render_single_game_mode_missing_game_pk():
    game = _game()
    del game['game_pk']
    with patch('render_scoreboard.select_game', return_value=game):
        result = render_scoreboard._render_single_game_mode('field', [], _TEAM_DATA, {})
    assert result is None


def test_render_single_game_mode_handles_exception():
    """An exception raised while fetching/rendering is caught and returns None
    (rather than propagating and crashing the whole pipeline)."""
    with patch('render_scoreboard.select_game', return_value=_game()), \
         patch('render_scoreboard.fetch_field_view_data', side_effect=RuntimeError('boom')):
        result = render_scoreboard._render_single_game_mode('field', [], _TEAM_DATA, {})
    assert result is None


# ---------------------------------------------------------------------------
# 3. render() — dispatch + save-to-disk logic
# ---------------------------------------------------------------------------

def _loader(games_payload=None, teams_payload=None):
    """Build a load_json_file side_effect that never touches real data/ files."""
    games_payload = games_payload if games_payload is not None else {'games': []}
    teams_payload = teams_payload if teams_payload is not None else {'team_abbreviation': {}}

    def _fn(filename, file_path=None):
        if filename == 'games.json':
            return games_payload
        if filename == 'teams.json':
            return teams_payload
        return {}
    return _fn


@needs_pil
def test_render_dispatches_single_game_mode(tmp_path):
    """render() routes field/scorecard/pitch modes through _render_single_game_mode
    and wraps a returned image in a full-image changed-region tuple."""
    fake_image = Image.new('1', (800, 480), 255)
    config = {'display_mode': 'field'}
    with patch('render_scoreboard.load_json_file', side_effect=_loader()), \
         patch('render_scoreboard._render_single_game_mode', return_value=fake_image) as m_single:
        result = render_scoreboard.render(config, output_path=str(tmp_path / 'out.bmp'))
    assert result == (fake_image, [(0, 0, 800, 480)])
    m_single.assert_called_once()


def test_render_single_game_mode_returns_none_propagates():
    """_render_single_game_mode returning None (no game found) → render() returns None."""
    config = {'display_mode': 'scorecard'}
    with patch('render_scoreboard.load_json_file', side_effect=_loader()), \
         patch('render_scoreboard._render_single_game_mode', return_value=None):
        result = render_scoreboard.render(config, output_path='/nonexistent/should/not/write.bmp')
    assert result is None


def test_render_orchestrate_returns_none_no_file_written(tmp_path):
    """orchestrate_score_board returning None (no change) → render() returns
    None and must not write output_path."""
    out_path = tmp_path / 'out.bmp'
    config = {'scoreboard': True}
    with patch('render_scoreboard.load_json_file', side_effect=_loader()), \
         patch('render_scoreboard.orchestrate_score_board', return_value=None):
        result = render_scoreboard.render(config, output_path=str(out_path))
    assert result is None
    assert not out_path.exists()


def test_render_default_output_path_used_when_none():
    """output_path=None falls back to the module's _DEFAULT_OUTPUT constant.
    orchestrate_score_board is mocked to return None so nothing actually
    gets written to that real repo-root path."""
    config = {'scoreboard': True}
    with patch('render_scoreboard.load_json_file', side_effect=_loader()), \
         patch('render_scoreboard.orchestrate_score_board', return_value=None):
        result = render_scoreboard.render(config, output_path=None)
    assert result is None


def test_render_team_data_missing_abbreviation_key_falls_back():
    """teams.json payload without 'team_abbreviation' → render() substitutes
    an empty-mapping default rather than propagating the bad shape."""
    config = {'scoreboard': True}
    captured = {}

    def _fake_orchestrate(game_state_data, team_data, date_str, bypass_cache, config):
        captured['team_data'] = team_data
        return None

    with patch('render_scoreboard.load_json_file',
               side_effect=_loader(teams_payload={'some_other_key': 1})), \
         patch('render_scoreboard.orchestrate_score_board', side_effect=_fake_orchestrate):
        render_scoreboard.render(config, output_path='/nonexistent/out.bmp')
    assert captured['team_data'] == {'team_abbreviation': {}}


@needs_pil
def test_render_orchestrate_returns_image_saves_file(tmp_path):
    """orchestrate_score_board returning (image, regions) → render() saves the
    image to output_path and returns the tuple through (non-fullscreen path)."""
    out_path = tmp_path / 'out.bmp'
    fake_image = Image.new('1', (800, 480), 255)
    regions = [(0, 0, 150, 96)]
    config = {'scoreboard': True}
    with patch('render_scoreboard.load_json_file', side_effect=_loader()), \
         patch('render_scoreboard.orchestrate_score_board', return_value=(fake_image, regions)):
        result = render_scoreboard.render(config, output_path=str(out_path))
    assert result == (fake_image, regions)
    assert out_path.exists()


@needs_pil
def test_render_fullscreen_pixel_diff_replaces_regions(tmp_path, monkeypatch):
    """FEATURED_TEAM_FULLSCREEN=true plus an existing output snapshot on disk →
    the zone-based changed_regions get replaced with real pixel-diff bands."""
    monkeypatch.setenv('FEATURED_TEAM_FULLSCREEN', 'true')
    out_path = tmp_path / 'out.bmp'

    old_image = Image.new('1', (800, 480), 255)
    old_image.save(out_path)

    new_image = Image.new('1', (800, 480), 255)
    draw = ImageDraw.Draw(new_image)
    draw.rectangle([100, 100, 200, 120], fill=0)

    config = {'scoreboard': True}
    zone_placeholder = [('zone-based-placeholder',)]
    with patch('render_scoreboard.load_json_file', side_effect=_loader()), \
         patch('render_scoreboard.orchestrate_score_board',
               return_value=(new_image, zone_placeholder)):
        result = render_scoreboard.render(config, output_path=str(out_path), bypass_cache=False)

    assert result is not None
    image, changed_regions = result
    assert image is new_image
    assert changed_regions != zone_placeholder
    assert len(changed_regions) >= 1


@needs_pil
def test_render_fullscreen_corrupt_snapshot_falls_back_gracefully(tmp_path, monkeypatch):
    """If the existing output_path file can't be opened as an image (corrupt/
    truncated), the snapshot-read exception is swallowed and render() still
    completes, returning the zone-based regions untouched."""
    monkeypatch.setenv('FEATURED_TEAM_FULLSCREEN', 'true')
    out_path = tmp_path / 'out.bmp'
    out_path.write_bytes(b'not a real image')

    new_image = Image.new('1', (800, 480), 255)
    zone_regions = [(0, 0, 150, 96)]
    config = {'scoreboard': True}
    with patch('render_scoreboard.load_json_file', side_effect=_loader()), \
         patch('render_scoreboard.orchestrate_score_board', return_value=(new_image, zone_regions)):
        result = render_scoreboard.render(config, output_path=str(out_path))
    assert result == (new_image, zone_regions)


@needs_pil
def test_render_fullscreen_disabled_by_default_keeps_zone_regions(tmp_path, monkeypatch):
    """Without FEATURED_TEAM_FULLSCREEN set, zone-based regions pass through
    untouched even though an old snapshot exists on disk."""
    monkeypatch.delenv('FEATURED_TEAM_FULLSCREEN', raising=False)
    out_path = tmp_path / 'out.bmp'

    old_image = Image.new('1', (800, 480), 255)
    old_image.save(out_path)

    new_image = Image.new('1', (800, 480), 255)
    zone_regions = [(0, 0, 150, 96)]
    config = {'scoreboard': True}
    with patch('render_scoreboard.load_json_file', side_effect=_loader()), \
         patch('render_scoreboard.orchestrate_score_board', return_value=(new_image, zone_regions)):
        result = render_scoreboard.render(config, output_path=str(out_path))
    assert result == (new_image, zone_regions)


# ---------------------------------------------------------------------------
# _pixel_diff_bands — direct tests with synthetic images
# ---------------------------------------------------------------------------

@needs_pil
def test_pixel_diff_bands_no_changes():
    img = Image.new('1', (64, 64), 255)
    bands = render_scoreboard._pixel_diff_bands(img, img)
    assert bands == []


@needs_pil
def test_pixel_diff_bands_localized_change():
    old = Image.new('L', (64, 64), 255)
    new = old.copy()
    draw = ImageDraw.Draw(new)
    draw.rectangle([10, 20, 20, 25], fill=0)
    bands = render_scoreboard._pixel_diff_bands(old, new)
    assert bands is not None
    assert len(bands) == 1
    x, y, w, h = bands[0]
    assert y <= 20 and y + h >= 26
    assert x <= 10
    assert x + w >= 21
    assert x % 8 == 0
    assert (x + w) % 8 == 0


@needs_pil
def test_pixel_diff_bands_two_separate_clusters():
    old = Image.new('L', (64, 100), 255)
    new = old.copy()
    draw = ImageDraw.Draw(new)
    draw.rectangle([5, 5, 10, 8], fill=0)
    draw.rectangle([5, 80, 10, 85], fill=0)
    bands = render_scoreboard._pixel_diff_bands(old, new, row_gap=4)
    assert bands is not None
    assert len(bands) == 2


@needs_pil
def test_pixel_diff_bands_large_change_returns_full_frame():
    old = Image.new('L', (64, 64), 255)
    new = Image.new('L', (64, 64), 0)  # every pixel differs
    bands = render_scoreboard._pixel_diff_bands(old, new)
    assert bands == [(0, 0, 64, 64)]


def test_pixel_diff_bands_exception_returns_none():
    """Non-image arguments break .convert() internally; the helper must
    swallow the exception and return None so callers fall back to their own
    region list."""
    bands = render_scoreboard._pixel_diff_bands(None, None)
    assert bands is None


# ---------------------------------------------------------------------------
# 4. main() / argparse — light smoke coverage
# ---------------------------------------------------------------------------

def test_main_help_exits_cleanly(monkeypatch):
    monkeypatch.setattr('sys.argv', ['render_scoreboard.py', '--help'])
    with pytest.raises(SystemExit) as exc_info:
        render_scoreboard.main()
    assert exc_info.value.code == 0


def test_main_invokes_render_with_mode_override_and_output(monkeypatch, tmp_path):
    out_path = str(tmp_path / 'out.bmp')
    monkeypatch.setattr(
        'sys.argv',
        ['render_scoreboard.py', '--mode', 'field', '--output', out_path],
    )
    with patch('render_scoreboard.load_config', return_value={}) as m_load_config, \
         patch('render_scoreboard.render', return_value=None) as m_render:
        render_scoreboard.main()
    m_load_config.assert_called_once()
    args, kwargs = m_render.call_args
    assert args[0]['display_mode'] == 'field'
    assert kwargs['output_path'] == out_path


@needs_pil
def test_main_prints_output_path_on_success(monkeypatch, tmp_path, capsys):
    out_path = str(tmp_path / 'out.bmp')
    fake_image = Image.new('1', (800, 480), 255)
    monkeypatch.setattr('sys.argv', ['render_scoreboard.py', '--output', out_path])
    with patch('render_scoreboard.load_config', return_value={}), \
         patch('render_scoreboard.render', return_value=(fake_image, [(0, 0, 800, 480)])):
        render_scoreboard.main()
    captured = capsys.readouterr()
    assert out_path in captured.out


def test_main_open_flag_invokes_macos_open(monkeypatch, tmp_path):
    """--open on a 'Darwin' platform shells out to `open <output_path>`."""
    out_path = str(tmp_path / 'out.bmp')
    fake_image = Image.new('1', (800, 480), 255) if PIL_AVAILABLE else object()
    monkeypatch.setattr('sys.argv', ['render_scoreboard.py', '--output', out_path, '--open'])
    with patch('render_scoreboard.load_config', return_value={}), \
         patch('render_scoreboard.render', return_value=(fake_image, [(0, 0, 800, 480)])), \
         patch('platform.system', return_value='Darwin'), \
         patch('subprocess.run') as m_run:
        render_scoreboard.main()
    m_run.assert_called_once_with(['open', out_path], check=False)
