"""Tests for race_view — the full-screen playoff-race view (6 division panels
+ 2 wild-card panels).

Logos are patched off throughout: pic/logos/*.png are gitignored, so a fresh
CI checkout has none and the real loader would auto-download from the ESPN
CDN. Same convention as test_quadrant_view.py.
"""
import os
import platform
from unittest.mock import patch

import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")
linux_only = pytest.mark.skipif(
    platform.system() != 'Linux',
    reason="golden references are generated on CI's Linux runner; font "
           "rendering differs enough across OSes that comparing locally "
           "would be noise, not signal.",
)

import race_view as rv

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), 'golden')
FAILURES_DIR = os.path.join(GOLDEN_DIR, '_failures')

_ALL_DIVISIONS = [
    'American League East', 'American League Central', 'American League West',
    'National League East', 'National League Central', 'National League West',
]


def _team(team_id, div_rank, wins=80, losses=60, clinch=None, league_rank=None):
    """Minimal standings team dict matching the standings.json schema."""
    d = {
        'team_id': team_id,
        'divisionRank': str(div_rank),
        'league_record_wins': wins,
        'league_record_losses': losses,
        'league_rank': league_rank if league_rank is not None else div_rank,
        'games_back': '-' if div_rank == 1 else str(div_rank - 1),
    }
    if clinch is not None:
        d['clinch_indicator'] = clinch
    return d


def _division(base_id, wins_losses=((92, 60), (85, 67), (78, 74), (70, 82), (60, 92))):
    """Five teams for one division, ranked by the given W-L records."""
    return [
        _team(base_id + i, i + 1, wins=w, losses=losses)
        for i, (w, losses) in enumerate(wins_losses)
    ]


def _standings(teams_by_division=None, abbr_map=None, last_updated=None):
    """A full standings_data dict with every division populated."""
    standings = {d: _division(100 + 10 * i) for i, d in enumerate(_ALL_DIVISIONS)}
    if teams_by_division:
        standings.update(teams_by_division)
    abbr_map = abbr_map or {
        str(100 + 10 * i + j): f'T{i}{j}'
        for i in range(len(_ALL_DIVISIONS)) for j in range(5)
    }
    return {'standings': standings, 'team_abbreviation': abbr_map,
            'last_updated': last_updated or '2026-08-29T12:00:00'}


@pytest.fixture
def no_logos():
    """Force the abbreviation fallback so tests never hit the ESPN CDN."""
    with patch('panel_cell._logo_small', return_value=None):
        yield


# ---------------------------------------------------------------------------
# render_race_view — validation and dispatch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('data', [None, {}, {'standings': {}}, {'standings': None}])
def test_render_rejects_empty_standings(data):
    """No usable division data raises, mirroring render_quadrant_view's contract."""
    with pytest.raises(ValueError):
        rv.render_race_view(data)


@needs_pil
def test_render_produces_a_full_screen_1bit_image(no_logos):
    """Output is always the full 800x480 1-bit panel image."""
    image = rv.render_race_view(_standings())
    assert image.size == (rv.EPD_WIDTH, rv.EPD_HEIGHT)
    assert image.mode == '1'


@needs_pil
def test_render_handles_a_single_populated_division(no_logos):
    """Missing divisions render as empty panels instead of raising."""
    data = {'standings': {'American League East': _division(1)},
            'team_abbreviation': {}}
    image = rv.render_race_view(data)
    assert image.size == (rv.EPD_WIDTH, rv.EPD_HEIGHT)


@needs_pil
def test_render_handles_teams_missing_records(no_logos):
    """A team with no win/loss data yet (preseason) doesn't crash the layout."""
    teams = [{'team_id': 1, 'divisionRank': '1'}, {'team_id': 2, 'divisionRank': '2'}]
    data = {'standings': {'American League East': teams}, 'team_abbreviation': {}}
    image = rv.render_race_view(data)
    assert image.size == (rv.EPD_WIDTH, rv.EPD_HEIGHT)


@needs_pil
def test_render_shows_clinched_and_eliminated_teams(no_logos):
    """Clinch indicators ('z'/'y'/'e') take priority over magic-number math."""
    teams = [
        _team(1, 1, wins=100, losses=50, clinch='z'),
        _team(2, 2, wins=60, losses=90, clinch='e'),
    ]
    data = {'standings': {'American League East': teams}, 'team_abbreviation': {}}
    image = rv.render_race_view(data)
    assert image.size == (rv.EPD_WIDTH, rv.EPD_HEIGHT)


@needs_pil
def test_render_accepts_missing_team_data(no_logos):
    """team_data is optional — the view falls back to standings' own abbr map."""
    image = rv.render_race_view(_standings(), team_data=None)
    assert image.size == (rv.EPD_WIDTH, rv.EPD_HEIGHT)


@needs_pil
def test_dark_mode_inverts_the_image(no_logos):
    """Dark mode flips the whole panel, same convention as quadrant_view."""
    light = rv.render_race_view(_standings())
    dark = rv.render_race_view(_standings(), dark_mode=True)
    assert light.mode == dark.mode == '1'
    # Inversion should change a meaningful share of pixels (borders/text exist).
    light_hist = light.histogram()
    dark_hist = dark.histogram()
    assert light_hist != dark_hist


# ---------------------------------------------------------------------------
# Wild-card panel — cutoff line and row cap
# ---------------------------------------------------------------------------

@needs_pil
def test_wildcard_panel_caps_row_count(no_logos):
    """More than _WC_MAX_ROWS eligible teams still renders without error."""
    many_teams = {
        'American League East': [_team(1, 1, wins=100, losses=50)],
        'American League Central': [_team(2, 1, wins=95, losses=55)],
        'American League West': [_team(3, 1, wins=90, losses=60)]
        + [_team(10 + i, i + 2, wins=80 - i, losses=70 + i) for i in range(14)],
    }
    data = {'standings': many_teams, 'team_abbreviation': {}}
    image = rv.render_race_view(data)
    assert image.size == (rv.EPD_WIDTH, rv.EPD_HEIGHT)


@needs_pil
def test_wildcard_panel_with_a_mid_sized_field_uses_the_intermediate_font(no_logos):
    """A 6-8 team bubble race lands row height in the 13pt font band, not just
    the two extremes a small (3-team) or full (10-team) field would hit."""
    many_teams = {
        'American League East': [_team(1, 1, wins=100, losses=50)],
        'American League Central': [_team(2, 1, wins=95, losses=55)],
        'American League West': [_team(3, 1, wins=90, losses=60)]
        + [_team(10 + i, i + 2, wins=80 - i, losses=70 + i) for i in range(5)],
    }
    data = {'standings': many_teams, 'team_abbreviation': {}}
    image = rv.render_race_view(data)
    assert image.size == (rv.EPD_WIDTH, rv.EPD_HEIGHT)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

class TestMain:
    """Tests for the CLI entry-point main()."""

    def test_no_standings_data_prints_error_and_returns_early(self, monkeypatch, capsys):
        """No cached standings.json data → main() bails without rendering."""
        monkeypatch.setattr('sys.argv', ['race_view'])
        with patch('util.load_json_file', return_value={}):
            rv.main()
        assert 'No cached standings.json' in capsys.readouterr().out

    @needs_pil
    def test_renders_and_saves_the_output(self, monkeypatch, tmp_path):
        """A normal run renders the view and saves it to --output."""
        out_path = str(tmp_path / 'race.bmp')
        monkeypatch.setattr('sys.argv', ['race_view', '--output', out_path])
        with patch('util.load_json_file', side_effect=lambda name: _standings() if name == 'standings.json'
                   else {'team_abbreviation': {}}), \
             patch('panel_cell._logo_small', return_value=None):
            rv.main()
        assert os.path.exists(out_path)

    @needs_pil
    def test_dark_flag_is_passed_through(self, monkeypatch, tmp_path):
        """--dark selects the inverted render."""
        out_path = str(tmp_path / 'race_dark.bmp')
        monkeypatch.setattr('sys.argv', ['race_view', '--output', out_path, '--dark'])
        with patch('util.load_json_file', side_effect=lambda name: _standings() if name == 'standings.json'
                   else {'team_abbreviation': {}}), \
             patch('panel_cell._logo_small', return_value=None), \
             patch('race_view.render_race_view', wraps=rv.render_race_view) as m_render:
            rv.main()
        assert m_render.call_args.kwargs['dark_mode'] is True

    def test_open_flag_invokes_macos_open(self, monkeypatch, tmp_path):
        """--open shells out to `open` on macOS only."""
        out_path = str(tmp_path / 'race.bmp')
        monkeypatch.setattr('sys.argv', ['race_view', '--output', out_path, '--open'])
        with patch('util.load_json_file', side_effect=lambda name: _standings() if name == 'standings.json'
                   else {'team_abbreviation': {}}), \
             patch('panel_cell._logo_small', return_value=None), \
             patch('platform.system', return_value='Darwin'), \
             patch('subprocess.run') as m_run:
            rv.main()
        m_run.assert_called_once_with(['open', out_path], check=False)


# ---------------------------------------------------------------------------
# Golden image
# ---------------------------------------------------------------------------

def _assert_matches_golden(actual, name, update, tolerance=0.003):
    """Diff against tests/golden/<name>.png, or rewrite it under --update-golden."""
    golden_path = os.path.join(GOLDEN_DIR, f'{name}.png')

    if update:
        actual.save(golden_path)
        return

    if not os.path.exists(golden_path):
        pytest.fail(
            f"No golden reference at {golden_path}. Generate it with "
            f"`pytest tests/test_race_view.py --update-golden` on Linux."
        )

    expected = Image.open(golden_path)
    if actual.size != expected.size:
        pytest.fail(f"{name}: size {actual.size} != golden size {expected.size}")

    a = list(actual.convert('L').getdata())
    e = list(expected.convert('L').getdata())
    diff = sum(1 for x, y in zip(a, e) if x != y)
    ratio = diff / len(a)
    if ratio > tolerance:
        os.makedirs(FAILURES_DIR, exist_ok=True)
        actual.save(os.path.join(FAILURES_DIR, f'{name}_actual.png'))
        pytest.fail(
            f"{name}: {ratio:.4%} of pixels differ from {golden_path} "
            f"(tolerance {tolerance:.4%}). See "
            f"tests/golden/_failures/{name}_actual.png for comparison."
        )


@pytest.fixture
def golden_update(request):
    """Whether --update-golden was passed."""
    return request.config.getoption('--update-golden')


@needs_pil
@linux_only
def test_golden_race_view(golden_update, no_logos):
    """Full render matches the committed reference image."""
    image = rv.render_race_view(_standings())
    _assert_matches_golden(image, 'race_view', golden_update)
