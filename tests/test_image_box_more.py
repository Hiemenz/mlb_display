"""Additional coverage for src/image_box.py.

Complements tests/test_wide_cell.py (draw_wide_box smoke coverage) and
tests/test_scoreboard_rules.py (private helper + draw_box smoke coverage) by
targeting specific branches those files don't reach: historical-mode gated
tomorrow-preview code, logo-found/logo-missing branches (via mocked
_logo_small/_logo_ghost so nothing ever touches the network or pic/logos/),
delayed/suspended/postponed/cancelled state formatting, extra-innings linescore
window sliding, ABS challenge dots, weather footer edge cases, and various
play-by-play / header-invert branches inside draw_box() and the wide-cell
right panel.

Safety rules followed throughout (see module docstring conventions used by
tests/test_golden_scoreboard.py):
  - Every Final/Postponed game render is wrapped in
    image_box.set_historical_mode(True) / finally: set_historical_mode(False)
    to avoid the wall-clock-gated tomorrow's-game-preview network path.
  - Any test that needs to exercise the *tomorrow preview* code itself mocks
    image_box._load_tomorrow_games directly (never touches fetch_games/urllib).
  - Any test that needs a "logo found" branch mocks image_box._logo_small /
    image_box._logo_ghost to return an in-memory PIL Image — never touches
    pic/logos/ or the network.
"""
import pytest
from unittest.mock import patch, Mock

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

needs_pil = pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")

from test_wide_cell import _base_game, _live_game, _between_innings_game  # noqa: E402


@pytest.fixture
def white_image():
    """White image."""
    return Image.new('1', (800, 480), 255)


@pytest.fixture
def team_data():
    """Team data."""
    return {
        'team_abbreviation': {
            '119': 'LAD', '137': 'SF', '133': 'OAK', '144': 'ATL',
            '147': 'NYY', '111': 'BOS',
        }
    }


def _tiny_logo(size=28):
    """A real in-memory '1'-mode image, standing in for a mocked logo lookup."""
    return Image.new('1', (size, size), 0)


# ---------------------------------------------------------------------------
# 1. set_historical_mode / _get_or_set_final_time
# ---------------------------------------------------------------------------

def test_set_historical_mode_toggles():
    """Set historical mode toggles."""
    import image_box
    image_box.set_historical_mode(True)
    assert image_box._historical_mode is True
    image_box.set_historical_mode(False)
    assert image_box._historical_mode is False


def test_get_or_set_final_time_cache_miss_writes_through():
    """No cache, no stored file entry -> sets a fresh timestamp and persists it."""
    import image_box
    with patch('image_box.load_json_file', return_value={}), \
         patch('image_box.save_off_results') as mock_save:
        ts = image_box._get_or_set_final_time(555001)
    assert isinstance(ts, float)
    assert mock_save.called


def test_get_or_set_final_time_from_stored_file():
    """Not in the in-memory cache, but present in the persisted file."""
    import image_box
    image_box._final_time_cache.pop('555002', None)
    with patch('image_box.load_json_file', return_value={'555002': 12345.0}):
        ts = image_box._get_or_set_final_time(555002)
    assert ts == 12345.0


def test_get_or_set_final_time_memory_cache_hit():
    """Get or set final time memory cache hit."""
    import image_box
    with patch('image_box.load_json_file', return_value={}), \
         patch('image_box.save_off_results'):
        ts1 = image_box._get_or_set_final_time(555003)
        ts2 = image_box._get_or_set_final_time(555003)
    assert ts1 == ts2


# ---------------------------------------------------------------------------
# 2. _draw_linescore_grid direct calls
# ---------------------------------------------------------------------------

@needs_pil
def test_linescore_grid_x_mark_when_bottom_not_played(white_image, team_data):
    """Home team's last inning is None while away has a value -> X mark drawn."""
    from image_box import _draw_linescore_grid
    draw = ImageDraw.Draw(white_image)
    game = _base_game(
        detailed_state='Final',
        away_inning_runs=[0, 1, 0, 0, 0, 2, 0, 0, 1],
        home_inning_runs=[1, 0, 2, 0, 0, 0, 1, 0],  # one shorter -> last is None
    )
    result_draw, result_img = _draw_linescore_grid(
        draw, white_image, 32, 30, game, team_data, use_logos=False,
    )
    assert isinstance(result_img, Image.Image)


@needs_pil
def test_linescore_grid_trailing_innings_show_x_when_final_early(white_image, team_data):
    """Game called before 9 innings: unplayed trailing columns show 'X' for both teams,
    plus the home row's own last inning if it didn't bat (walk-off/leading-after-top)."""
    from image_box import _draw_linescore_grid
    draw = ImageDraw.Draw(white_image)
    game = _base_game(
        detailed_state='Final',
        current_inning=6,
        away_inning_runs=[0, 0, 2, 2, 1, 3],
        home_inning_runs=[0, 0, 0, 0, 0],  # home didn't bat in the 6th
    )
    _draw_linescore_grid(draw, white_image, 32, 30, game, team_data, use_logos=False)

    px = white_image.load()

    def _has_ink(cx, cy, r=5):
        for x in range(cx - r, cx + r):
            for y in range(cy - r, cy + r):
                if 0 <= x < white_image.width and 0 <= y < white_image.height and px[x, y] == 0:
                    return True
        return False

    def _col_cx(k):
        return 39 + 12 + k * 12 + 6  # grid_x0(39) + LOGO_COL_W(12) + k*COL_W(12) + COL_W//2

    away_cy, home_cy = 135, 151

    # Innings 7-9 (k=6,7,8) never happened -> X in both rows.
    for k in (6, 7, 8):
        assert _has_ink(_col_cx(k), away_cy), f"expected 'X' in away row, inning {k + 1}"
        assert _has_ink(_col_cx(k), home_cy), f"expected 'X' in home row, inning {k + 1}"

    # Home didn't bat in inning 6 (k=5) -> X there too, even though away has a value.
    assert _has_ink(_col_cx(5), home_cy), "expected 'X' in home row, inning 6 (didn't bat)"


@needs_pil
def test_linescore_grid_use_logos_found(white_image, team_data):
    """use_logos=True with a logo present exercises the logo-paste branch."""
    from image_box import _draw_linescore_grid
    draw = ImageDraw.Draw(white_image)
    game = _base_game(detailed_state='Final')
    with patch('image_box._logo_small', return_value=_tiny_logo(10)):
        result_draw, result_img = _draw_linescore_grid(
            draw, white_image, 32, 30, game, team_data, use_logos=True,
        )
    assert isinstance(result_img, Image.Image)


@needs_pil
def test_linescore_grid_use_logos_missing_falls_back_to_text(white_image, team_data):
    """Linescore grid use logos missing falls back to text."""
    from image_box import _draw_linescore_grid
    draw = ImageDraw.Draw(white_image)
    game = _base_game(detailed_state='Final')
    with patch('image_box._logo_small', return_value=None):
        result_draw, result_img = _draw_linescore_grid(
            draw, white_image, 32, 30, game, team_data, use_logos=True,
        )
    assert isinstance(result_img, Image.Image)


@needs_pil
def test_linescore_grid_extra_innings_window_slides(white_image, team_data):
    """current_inning > 10 slides the display window so the 10th col isn't inning 1."""
    from image_box import _draw_linescore_grid
    draw = ImageDraw.Draw(white_image)
    game = _base_game(
        detailed_state='Final',
        current_inning=13,
        away_inning_runs=[0] * 12 + [1],
        home_inning_runs=[0] * 12 + [2],
    )
    result_draw, result_img = _draw_linescore_grid(
        draw, white_image, 32, 30, game, team_data, use_logos=False,
    )
    assert isinstance(result_img, Image.Image)


@needs_pil
def test_linescore_grid_double_digit_run_uses_font9(white_image, team_data):
    """Linescore grid double digit run uses font9."""
    from image_box import _draw_linescore_grid
    draw = ImageDraw.Draw(white_image)
    game = _base_game(
        detailed_state='Final',
        away_inning_runs=[10, 0, 0, 0, 0, 0, 0, 0, 0],
        home_inning_runs=[0, 0, 0, 0, 0, 0, 0, 0, 0],
    )
    result_draw, result_img = _draw_linescore_grid(
        draw, white_image, 32, 30, game, team_data, use_logos=False,
    )
    assert isinstance(result_img, Image.Image)


# ---------------------------------------------------------------------------
# 3. _draw_challenge_dots direct calls
# ---------------------------------------------------------------------------

@needs_pil
@pytest.mark.parametrize("use_logos", [True, False])
def test_challenge_dots_full_and_partial(white_image, use_logos):
    """Challenge dots full and partial."""
    from image_box import _draw_challenge_dots
    draw = ImageDraw.Draw(white_image)
    game = _base_game(
        away_challenges_remaining=2,
        home_challenges_remaining=0,
        away_replay_remaining=1,
        home_replay_remaining=0,
    )
    _draw_challenge_dots(draw, 32, 30, game, use_logos=use_logos)


@needs_pil
def test_challenge_dots_grown_max_extra_innings(white_image):
    """abs_challenge_max override (extra-inning growth) draws more than 2 dots."""
    from image_box import _draw_challenge_dots
    draw = ImageDraw.Draw(white_image)
    game = _base_game(
        abs_challenge_max=4,
        away_challenges_remaining=4,
        home_challenges_remaining=3,
    )
    _draw_challenge_dots(draw, 32, 30, game, use_logos=False)


@needs_pil
def test_challenge_dots_replay_remaining_clamped_above_one(white_image):
    """Challenge dots replay remaining clamped above one."""
    from image_box import _draw_challenge_dots
    draw = ImageDraw.Draw(white_image)
    game = _base_game(away_replay_remaining=5, home_replay_remaining=-2)
    _draw_challenge_dots(draw, 32, 30, game, use_logos=False)


@needs_pil
def test_challenge_dots_no_data_no_crash(white_image):
    """Challenge dots no data no crash."""
    from image_box import _draw_challenge_dots
    draw = ImageDraw.Draw(white_image)
    game = _base_game()
    _draw_challenge_dots(draw, 32, 30, game, use_logos=False)


# ---------------------------------------------------------------------------
# 4. _draw_weather_footer direct calls
# ---------------------------------------------------------------------------

@needs_pil
def test_weather_footer_dome_takes_priority(white_image):
    """Weather footer dome takes priority."""
    from image_box import _draw_weather_footer
    from image_assets import _get_font
    draw = ImageDraw.Draw(white_image)
    game = _base_game(roof_state='dome', weather_temp_f=75)
    _draw_weather_footer(draw, 32, 30, 135, game, _get_font(14))


@needs_pil
def test_weather_footer_no_weather_data_returns_early(white_image):
    """Weather footer no weather data returns early."""
    from image_box import _draw_weather_footer
    from image_assets import _get_font
    draw = ImageDraw.Draw(white_image)
    game = _base_game(weather_temp_f=None, weather_wind_mph=None, weather_precip_pct=None)
    _draw_weather_footer(draw, 32, 30, 135, game, _get_font(14))


@needs_pil
def test_weather_footer_low_wind_and_zero_precip_excluded(white_image):
    """wind < 1 mph and precip == 0 are dropped from candidate strings."""
    from image_box import _draw_weather_footer
    from image_assets import _get_font
    draw = ImageDraw.Draw(white_image)
    game = _base_game(weather_temp_f=68, weather_wind_mph=0.4, weather_precip_pct=0)
    _draw_weather_footer(draw, 32, 30, 135, game, _get_font(14))


@needs_pil
def test_weather_footer_full_candidate_with_wind_dir(white_image):
    """Weather footer full candidate with wind dir."""
    from image_box import _draw_weather_footer
    from image_assets import _get_font
    draw = ImageDraw.Draw(white_image)
    game = _base_game(weather_temp_f=72, weather_wind_mph=12, weather_wind_dir='In', weather_precip_pct=20)
    _draw_weather_footer(draw, 32, 30, 135, game, _get_font(14), show_tv=False)


@needs_pil
def test_weather_footer_tv_channel_getlength_attributeerror_fallback(white_image):
    """A font missing getlength() forces the AttributeError fallback for TV width."""
    from image_box import _draw_weather_footer
    from image_assets import _get_font

    real_font = _get_font(14)

    class _NoGetLength:
        def __getattr__(self, name):
            """Getattr  ."""
            if name == 'getlength':
                raise AttributeError(name)
            return getattr(real_font, name)

    draw = ImageDraw.Draw(white_image)
    game = _base_game(weather_temp_f=70, weather_wind_mph=5)
    _draw_weather_footer(draw, 32, 30, 135, game, _NoGetLength(), show_tv=True)


@needs_pil
def test_weather_footer_candidate_getlength_attributeerror_fallback(white_image):
    """Same missing-getlength font used as the primary weather font hits the
    candidate-measurement except branch too."""
    from image_box import _draw_weather_footer
    from image_assets import _get_font

    real_font = _get_font(14)

    class _NoGetLength:
        def __getattr__(self, name):
            """Getattr  ."""
            if name == 'getlength':
                raise AttributeError(name)
            return getattr(real_font, name)

    draw = ImageDraw.Draw(white_image)
    game = _base_game(weather_temp_f=70, weather_wind_mph=5, weather_precip_pct=10)
    _draw_weather_footer(draw, 32, 30, 135, game, _NoGetLength(), show_tv=False)


# ---------------------------------------------------------------------------
# 5. _load_tomorrow_games direct calls
# ---------------------------------------------------------------------------

def test_load_tomorrow_games_cache_hit_returns_cached():
    """Load tomorrow games cache hit returns cached."""
    import image_box
    with patch('image_box.load_yaml_file', return_value={'timezone': 'America/Chicago'}), \
         patch('image_box.load_json_file') as mock_load:
        from datetime import date as _date, timedelta as _td
        tomorrow = (_date.today() + _td(days=1)).strftime('%Y-%m-%d')
        mock_load.return_value = {'date': tomorrow, 'games': [{'game_pk': 1}]}
        result = image_box._load_tomorrow_games()
    assert result['games'] == [{'game_pk': 1}]


def test_load_tomorrow_games_cache_miss_fetches_and_reloads():
    """Cache is stale/missing -> fetch_tomorrow_games is invoked (mocked) then reloaded."""
    import image_box
    from datetime import date as _date, timedelta as _td
    tomorrow = (_date.today() + _td(days=1)).strftime('%Y-%m-%d')
    calls = {'n': 0}

    def _fake_load(name, file_path=None):
        """Fake load."""
        calls['n'] += 1
        if calls['n'] == 1:
            return {'date': '2000-01-01', 'games': None}  # stale
        return {'date': tomorrow, 'games': [{'game_pk': 42}]}

    with patch('image_box.load_yaml_file', return_value={'timezone': 'America/Chicago'}), \
         patch('image_box.load_json_file', side_effect=_fake_load), \
         patch('fetch_games.fetch_tomorrow_games') as mock_fetch:
        result = image_box._load_tomorrow_games()
    assert mock_fetch.called
    assert result['games'] == [{'game_pk': 42}]


def test_load_tomorrow_games_exception_returns_none():
    """Load tomorrow games exception returns none."""
    import image_box
    with patch('image_box.load_yaml_file', return_value={'timezone': 'America/Chicago'}), \
         patch('image_box.load_json_file', side_effect=RuntimeError('boom')):
        result = image_box._load_tomorrow_games()
    assert result is None


def test_load_tomorrow_games_morning_window_exception_falls_back():
    """load_yaml_file raising inside the morning-window check must not propagate."""
    import image_box
    with patch('image_box.load_yaml_file', side_effect=RuntimeError('cfg boom')), \
         patch('image_box.load_json_file', return_value={'date': 'nope', 'games': None}), \
         patch('fetch_games.fetch_tomorrow_games'):
        result = image_box._load_tomorrow_games()
    # Should not raise; whatever load_json_file returns after the fetch attempt is fine.
    assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# 6. _draw_next_game_preview direct calls
# ---------------------------------------------------------------------------

_PREV_TEAM_DATA = {'team_abbreviation': {'119': 'LAD', '137': 'SF', '147': 'NYY', '111': 'BOS'}}


@needs_pil
def test_next_game_preview_no_games_found_noop(white_image):
    """Next game preview no games found noop."""
    from image_box import _draw_next_game_preview
    draw = ImageDraw.Draw(white_image)
    _draw_next_game_preview(
        draw, white_image, 32, 30, [{'home_team_id': 999, 'away_team_id': 998}],
        119, 137, _PREV_TEAM_DATA, use_logos=False, horizonta_len=135, vertical_len=110,
    )


@needs_pil
def test_next_game_preview_missing_utc_time(white_image):
    """game_start_utc missing -> _game_time returns '' (no crash, no time text)."""
    from image_box import _draw_next_game_preview
    draw = ImageDraw.Draw(white_image)
    tmrw_games = [{'home_team_id': 137, 'away_team_id': 119, 'game_pk': 5}]
    _draw_next_game_preview(
        draw, white_image, 32, 30, tmrw_games, 137, 119,
        _PREV_TEAM_DATA, use_logos=False, horizonta_len=135, vertical_len=110,
    )


@needs_pil
def test_next_game_preview_malformed_utc_time_falls_back(white_image):
    """A garbage game_start_utc string hits the except-Exception branch in _game_time."""
    from image_box import _draw_next_game_preview
    draw = ImageDraw.Draw(white_image)
    tmrw_games = [{'home_team_id': 137, 'away_team_id': 119, 'game_pk': 5,
                   'game_start_utc': 'not-a-date'}]
    _draw_next_game_preview(
        draw, white_image, 32, 30, tmrw_games, 137, 119,
        _PREV_TEAM_DATA, use_logos=False, horizonta_len=135, vertical_len=110,
    )


@needs_pil
def test_next_game_preview_same_series_full_time(white_image):
    """Both teams' next game is the same matchup -> single centered entry, full time."""
    from image_box import _draw_next_game_preview
    draw = ImageDraw.Draw(white_image)
    tmrw_games = [{'home_team_id': 137, 'away_team_id': 119, 'game_pk': 5,
                   'game_start_utc': '2026-06-21T23:05:00Z'}]
    _draw_next_game_preview(
        draw, white_image, 32, 30, tmrw_games, 137, 119,
        _PREV_TEAM_DATA, use_logos=False, horizonta_len=135, vertical_len=110,
    )


@needs_pil
def test_next_game_preview_away_only(white_image):
    """Next game preview away only."""
    from image_box import _draw_next_game_preview
    draw = ImageDraw.Draw(white_image)
    tmrw_games = [{'home_team_id': 111, 'away_team_id': 119, 'game_pk': 6,
                   'game_start_utc': '2026-06-21T23:05:00Z'}]
    _draw_next_game_preview(
        draw, white_image, 32, 30, tmrw_games, 999, 119,
        _PREV_TEAM_DATA, use_logos=False, horizonta_len=135, vertical_len=110,
    )


@needs_pil
def test_next_game_preview_home_only(white_image):
    """Next game preview home only."""
    from image_box import _draw_next_game_preview
    draw = ImageDraw.Draw(white_image)
    tmrw_games = [{'home_team_id': 137, 'away_team_id': 111, 'game_pk': 7,
                   'game_start_utc': '2026-06-21T23:05:00Z'}]
    _draw_next_game_preview(
        draw, white_image, 32, 30, tmrw_games, 137, 999,
        _PREV_TEAM_DATA, use_logos=False, horizonta_len=135, vertical_len=110,
    )


@needs_pil
def test_next_game_preview_both_different_games_split_strip(white_image):
    """Away and home each have a different next-day game -> split strip, abbreviated times."""
    from image_box import _draw_next_game_preview
    draw = ImageDraw.Draw(white_image)
    tmrw_games = [
        {'home_team_id': 111, 'away_team_id': 119, 'game_pk': 8,
         'game_start_utc': '2026-06-21T23:05:00Z'},
        {'home_team_id': 137, 'away_team_id': 147, 'game_pk': 9,
         'game_start_utc': '2026-06-22T01:10:00Z'},
    ]
    _draw_next_game_preview(
        draw, white_image, 32, 30, tmrw_games, 137, 119,
        _PREV_TEAM_DATA, use_logos=False, horizonta_len=135, vertical_len=110,
    )


@needs_pil
def test_next_game_preview_logos_found(white_image):
    """use_logos=True with a mocked logo hit exercises _logo_w/_place_logo's logo branch."""
    from image_box import _draw_next_game_preview
    draw = ImageDraw.Draw(white_image)
    tmrw_games = [{'home_team_id': 137, 'away_team_id': 119, 'game_pk': 10,
                   'game_start_utc': '2026-06-21T23:05:00Z'}]
    with patch('image_box._logo_small', return_value=_tiny_logo(14)):
        _draw_next_game_preview(
            draw, white_image, 32, 30, tmrw_games, 137, 119,
            _PREV_TEAM_DATA, use_logos=True, horizonta_len=135, vertical_len=110,
        )


@needs_pil
def test_next_game_preview_logos_missing_falls_back_to_text(white_image):
    """Next game preview logos missing falls back to text."""
    from image_box import _draw_next_game_preview
    draw = ImageDraw.Draw(white_image)
    tmrw_games = [
        {'home_team_id': 111, 'away_team_id': 119, 'game_pk': 11,
         'game_start_utc': '2026-06-21T23:05:00Z'},
        {'home_team_id': 137, 'away_team_id': 147, 'game_pk': 12,
         'game_start_utc': '2026-06-22T01:10:00Z'},
    ]
    with patch('image_box._logo_small', return_value=None):
        _draw_next_game_preview(
            draw, white_image, 32, 30, tmrw_games, 137, 119,
            _PREV_TEAM_DATA, use_logos=True, horizonta_len=135, vertical_len=110,
        )


@needs_pil
def test_next_game_preview_narrow_strip_time_does_not_fit(white_image):
    """A very small horizonta_len leaves no room for the time string (_fit_time -> '')."""
    from image_box import _draw_next_game_preview
    draw = ImageDraw.Draw(white_image)
    tmrw_games = [{'home_team_id': 137, 'away_team_id': 119, 'game_pk': 13,
                   'game_start_utc': '2026-06-21T23:05:00Z'}]
    _draw_next_game_preview(
        draw, white_image, 32, 30, tmrw_games, 137, 119,
        _PREV_TEAM_DATA, use_logos=False, horizonta_len=40, vertical_len=110,
    )


# ---------------------------------------------------------------------------
# 7. draw_box(): Final-game flags, series, sweeps, logos
# ---------------------------------------------------------------------------

@needs_pil
class TestDrawBoxFinalFlags:
    def _render_final(self, white_image, team_data, **overrides):
        """Render final."""
        import image_box
        game = _base_game(detailed_state='Final', **overrides)
        image_box.set_historical_mode(True)
        try:
            from image_box import draw_box
            return draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        finally:
            image_box.set_historical_mode(False)

    def test_no_hitter_flag(self, white_image, team_data):
        """No hitter flag."""
        result = self._render_final(white_image, team_data, no_hitter=True)
        assert isinstance(result, Image.Image)

    def test_perfect_game_flag(self, white_image, team_data):
        """Perfect game flag."""
        result = self._render_final(white_image, team_data, perfect_game=True)
        assert isinstance(result, Image.Image)

    def test_walk_off_flag(self, white_image, team_data):
        """Walk off flag."""
        result = self._render_final(white_image, team_data, walk_off=True)
        assert isinstance(result, Image.Image)

    def test_tied_final_game(self, white_image, team_data):
        """Tied final game."""
        result = self._render_final(white_image, team_data, away_runs=4, home_runs=4,
                                      winner_name=None, loser_name=None)
        assert isinstance(result, Image.Image)

    def test_saver_with_saves_count(self, white_image, team_data):
        """Saver with saves count."""
        result = self._render_final(white_image, team_data, saver_name='Josh Hader',
                                      saver_saves=30)
        assert isinstance(result, Image.Image)

    def test_long_winner_name_with_initial_triggers_truncation(self, white_image, team_data):
        """WP/LP name longer than cell width hits _truncate_keep_suffix lines 884-901."""
        long_name = 'C. Bartholomew-Christopherson-McLongname'
        result = self._render_final(
            white_image, team_data,
            winner_name=long_name,
            loser_name=long_name,
        )
        assert isinstance(result, Image.Image)

    def test_long_winner_name_no_record_char_truncation(self, white_image, team_data):
        """No parens in WP string forces char-by-char truncation (lines 902-904)."""
        long_name = 'Bartholomew Christopherson-McLongname-III'
        result = self._render_final(
            white_image, team_data,
            winner_name=long_name,
            loser_name=long_name,
            winner_record='',
            loser_record='',
        )
        assert isinstance(result, Image.Image)

    def test_extra_innings_final(self, white_image, team_data):
        """Extra innings final."""
        result = self._render_final(
            white_image, team_data, current_inning=11,
            away_inning_runs=[0] * 9 + [1, 0],
            home_inning_runs=[0] * 9 + [0, 2],
        )
        assert isinstance(result, Image.Image)

    def test_sweep_early_ghost_and_series_score(self, white_image, team_data):
        """Sweep early ghost and series score."""
        result = self._render_final(
            white_image, team_data,
            series_total_games=4, series_wins=4, series_losses=0,
            series_description='Regular Season', series_result='LAD wins 4-0',
            away_team_is_winner=True, home_team_is_winner=False,
        )
        assert isinstance(result, Image.Image)

    def test_sweep_takes_priority_over_walkoff_in_header(self, white_image, team_data):
        """When a Final is both a series-clinching sweep and a walk-off win, the
        header ghost must show SWEEP, not WALKOFF — sweep is the higher-priority
        headline. Renders sweep+walkoff and sweep-only and asserts they're pixel
        identical, proving the WALKOFF text is fully suppressed.
        """
        sweep_kwargs = dict(
            series_total_games=4, series_wins=4, series_losses=0,
            series_description='Regular Season', series_result='LAD wins 4-0',
            away_team_is_winner=True, home_team_is_winner=False,
        )
        img_sweep_only = self._render_final(white_image, team_data, **sweep_kwargs)
        img_sweep_walkoff = self._render_final(
            Image.new('1', (800, 480), 255), team_data, walk_off=True, **sweep_kwargs,
        )
        assert list(img_sweep_only.getdata()) == list(img_sweep_walkoff.getdata()), \
            "sweep + walk_off should render identically to sweep alone (WALKOFF hidden)"

    def test_sweep_with_logo_found(self, white_image, team_data):
        """Sweep with logo found."""
        with patch('image_box._logo_small', return_value=_tiny_logo(14)):
            result = self._render_final(
                white_image, team_data,
                series_total_games=3, series_wins=3, series_losses=0,
                series_description='Regular Season', series_result='LAD wins 3-0',
                away_team_is_winner=True, home_team_is_winner=False,
            )
        assert isinstance(result, Image.Image)

    def test_series_clinched_playoffs_logo_missing(self, white_image, team_data):
        """Series clinched playoffs logo missing."""
        with patch('image_box._logo_small', return_value=None):
            result = self._render_final(
                white_image, team_data,
                series_total_games=7, series_wins=4, series_losses=2,
                series_description='League Championship Series',
                series_is_over=True, series_result='LAD wins 4-2',
                away_team_is_winner=True, home_team_is_winner=False,
            )
        assert isinstance(result, Image.Image)

    def test_series_tied(self, white_image, team_data):
        """Series tied."""
        result = self._render_final(
            white_image, team_data,
            series_total_games=5, series_wins=2, series_losses=2,
            series_is_tied=True, series_is_over=False,
        )
        assert isinstance(result, Image.Image)

    def test_series_leading_logo_found(self, white_image, team_data):
        """Series leading logo found."""
        with patch('image_box._logo_small', return_value=_tiny_logo(14)):
            result = self._render_final(
                white_image, team_data,
                series_total_games=5, series_wins=2, series_losses=1,
                series_is_over=False, series_is_tied=False,
                series_result='LAD wins 2-1',
                away_team_is_winner=True, home_team_is_winner=False,
            )
        assert isinstance(result, Image.Image)

    def test_series_leading_logo_missing(self, white_image, team_data):
        """Series leading logo missing."""
        with patch('image_box._logo_small', return_value=None):
            result = self._render_final(
                white_image, team_data,
                series_total_games=5, series_wins=2, series_losses=1,
                series_is_over=False, series_is_tied=False,
                away_team_is_winner=True, home_team_is_winner=False,
            )
        assert isinstance(result, Image.Image)

    def test_winner_ghost_logo_use_logos(self, white_image, team_data):
        """Winner ghost logo use logos."""
        with patch('image_box._logo_ghost', return_value=_tiny_logo(110)):
            result = self._render_final(white_image, team_data)
            import image_box
            image_box.set_historical_mode(True)
            try:
                from image_box import draw_box
                game = _base_game(detailed_state='Final')
                result = draw_box(white_image, 32, 30, game, team_data, use_logos=True,
                                   show_winner_logo=True)
            finally:
                image_box.set_historical_mode(False)
        assert isinstance(result, Image.Image)

    def test_team_logos_found(self, white_image, team_data):
        """Team logos found."""
        import image_box
        with patch('image_box._logo_small', return_value=_tiny_logo(28)):
            image_box.set_historical_mode(True)
            try:
                from image_box import draw_box
                game = _base_game(detailed_state='Final')
                result = draw_box(white_image, 32, 30, game, team_data, use_logos=True)
            finally:
                image_box.set_historical_mode(False)
        assert isinstance(result, Image.Image)

    def test_team_logos_missing_falls_back_to_text(self, white_image, team_data):
        """Team logos missing falls back to text."""
        import image_box
        with patch('image_box._logo_small', return_value=None), \
             patch('image_box._logo_ghost', return_value=None):
            image_box.set_historical_mode(True)
            try:
                from image_box import draw_box
                game = _base_game(detailed_state='Final')
                result = draw_box(white_image, 32, 30, game, team_data, use_logos=True)
            finally:
                image_box.set_historical_mode(False)
        assert isinstance(result, Image.Image)

    def test_game_duration_sweep(self, white_image, team_data):
        """Game duration sweep."""
        result = self._render_final(
            white_image, team_data, game_duration_minutes=185,
            series_total_games=3, series_wins=3, series_losses=0,
            series_description='Regular Season', series_result='LAD wins 3-0',
            away_team_is_winner=True, home_team_is_winner=False,
        )
        assert isinstance(result, Image.Image)

    def test_game_duration_doubleheader_non_sweep(self, white_image, team_data):
        """Game duration doubleheader non sweep."""
        result = self._render_final(
            white_image, team_data, game_duration_minutes=145,
            double_header='Y', game_number=1,
        )
        assert isinstance(result, Image.Image)

    def test_game_duration_non_dh_centered(self, white_image, team_data):
        """Game duration non dh centered."""
        result = self._render_final(white_image, team_data, game_duration_minutes=210)
        assert isinstance(result, Image.Image)

    def test_doubleheader_game_number_in_header(self, white_image, team_data):
        """Doubleheader game number in header."""
        result = self._render_final(
            white_image, team_data, double_header='Y', game_number=2,
            game_duration_minutes=None,
        )
        assert isinstance(result, Image.Image)

    def test_end_time_shown_when_show_always_configured(self, white_image, team_data):
        """End time shown when show always configured."""
        import image_box
        with patch('image_box.load_yaml_file', return_value={'show_game_end_time_always': True,
                                                               'final_linescore_minutes': 60}):
            image_box.set_historical_mode(True)
            try:
                from image_box import draw_box
                game = _base_game(detailed_state='Final',
                                   game_end_time_utc='2026-06-21T02:45:00Z')
                result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
            finally:
                image_box.set_historical_mode(False)
        assert isinstance(result, Image.Image)

    def test_no_hitter_header_invert_on_final(self, white_image, team_data):
        """No hitter header invert on final."""
        result = self._render_final(white_image, team_data, no_hitter=True)
        assert isinstance(result, Image.Image)


@needs_pil
def test_next_game_preview_triggered_from_draw_box_final(white_image, team_data):
    """Final game whose linescore window has fully expired shows tomorrow's preview.

    _load_tomorrow_games is mocked directly (never touches the network), and
    _get_or_set_final_time's disk usage is mocked too, so nothing hits the
    filesystem or network even though _historical_mode is left False here.
    """
    import image_box
    game = _base_game(
        detailed_state='Final',
        game_end_time_utc='2020-01-01T00:00:00Z',  # long expired
    )
    fake_tomorrow = {
        'date': '2026-06-21',
        'games': [{'home_team_id': 137, 'away_team_id': 119, 'game_pk': 999,
                   'game_start_utc': '2026-06-21T23:05:00Z'}],
    }
    with patch('image_box._load_tomorrow_games', return_value=fake_tomorrow), \
         patch('image_box.load_json_file', return_value={}), \
         patch('image_box.save_off_results'):
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
    assert isinstance(result, Image.Image)


@needs_pil
def test_next_game_preview_triggered_from_draw_box_postponed(white_image, team_data):
    """Next game preview triggered from draw box postponed."""
    import image_box
    game = _base_game(detailed_state='Postponed', away_runs=None, home_runs=None)
    fake_tomorrow = {
        'date': '2026-06-21',
        'games': [{'home_team_id': 137, 'away_team_id': 119, 'game_pk': 998,
                   'game_start_utc': '2026-06-21T23:05:00Z'}],
    }
    with patch('image_box._load_tomorrow_games', return_value=fake_tomorrow):
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
    assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# 8. draw_box(): non-Final game states
# ---------------------------------------------------------------------------

@needs_pil
class TestDrawBoxGameStates:
    @pytest.mark.parametrize("state", [
        'Delayed', 'Suspended', 'Postponed', 'Cancelled', 'Cancelled: Rain',
    ])
    def test_state_no_crash(self, white_image, team_data, state):
        """State no crash."""
        import image_box
        game = _base_game(detailed_state=state, current_inning=5, inningState='Top',
                           away_runs=2, home_runs=1)
        image_box.set_historical_mode(True)
        try:
            from image_box import draw_box
            result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        finally:
            image_box.set_historical_mode(False)
        assert isinstance(result, Image.Image)

    def test_delayed_pregame_no_inning_yet(self, white_image, team_data):
        """Delayed with current_inning falsy -> plain 'Delay' label."""
        import image_box
        game = _base_game(detailed_state='Delayed', current_inning=0, away_runs=None,
                           home_runs=None)
        image_box.set_historical_mode(True)
        try:
            from image_box import draw_box
            result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        finally:
            image_box.set_historical_mode(False)
        assert isinstance(result, Image.Image)

    def test_delayed_with_score_batter_and_pitcher_truncation(self, white_image, team_data):
        """Delayed mid-game shows next batters + pitcher; very long names force truncation."""
        import image_box
        game = _base_game(
            detailed_state='Delayed', current_inning=5, inningState='Top',
            away_runs=2, home_runs=1,
            next_batter_1='Bartholomew Longname-Extraordinaire',
            next_batter_2='Christopher Anotherverylongname',
            next_batter_3='Maximilian Yetanotherlongname',
            next_pitcher='Ferdinand Pitchernameiswaytoolongforthebox',
            postpone_reason='Rain',
        )
        image_box.set_historical_mode(True)
        try:
            from image_box import draw_box
            result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        finally:
            image_box.set_historical_mode(False)
        assert isinstance(result, Image.Image)

    def test_postponed_with_makeup_description(self, white_image, team_data):
        """Postponed with makeup description."""
        import image_box
        game = _base_game(
            detailed_state='Postponed', away_runs=None, home_runs=None,
            postpone_reason='Rain', description='Makeup of 6/1 postponement',
        )
        image_box.set_historical_mode(True)
        try:
            from image_box import draw_box
            result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        finally:
            image_box.set_historical_mode(False)
        assert isinstance(result, Image.Image)

    def test_postponed_series_leader_logo_found(self, white_image, team_data):
        """Postponed series leader logo found."""
        import image_box
        game = _base_game(
            detailed_state='Postponed', away_runs=None, home_runs=None,
            series_total_games=4, series_wins=1, series_losses=0,
            series_result='LAD leads 1-0',
        )
        with patch('image_box._logo_small', return_value=_tiny_logo(14)):
            image_box.set_historical_mode(True)
            try:
                from image_box import draw_box
                result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
            finally:
                image_box.set_historical_mode(False)
        assert isinstance(result, Image.Image)

    def test_postponed_series_not_started_no_score_shown(self, white_image, team_data):
        """Postponed series not started no score shown."""
        import image_box
        game = _base_game(
            detailed_state='Postponed', away_runs=None, home_runs=None,
            series_total_games=4, series_wins=0, series_losses=0,
        )
        image_box.set_historical_mode(True)
        try:
            from image_box import draw_box
            result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        finally:
            image_box.set_historical_mode(False)
        assert isinstance(result, Image.Image)

    def test_scheduled_iso_game_start_parses(self, white_image, team_data):
        """game_start in ISO format hits the successful strptime branch."""
        from image_box import draw_box
        game = _base_game(
            detailed_state='Scheduled', away_runs=None, home_runs=None,
            game_start='2026-06-20T19:05:00Z',
            winner_name=None, loser_name=None,
        )
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_scheduled_with_moneylines(self, white_image, team_data):
        """Scheduled with moneylines."""
        from image_box import draw_box
        game = _base_game(
            detailed_state='Scheduled', away_runs=None, home_runs=None,
            away_ml=150, home_ml=-180,
        )
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_scheduled_no_weather_fields_at_all(self, white_image, team_data):
        """Scheduled no weather fields at all."""
        from image_box import draw_box
        game = _base_game(detailed_state='Scheduled', away_runs=None, home_runs=None)
        for f in ('weather_temp_f', 'weather_wind_mph', 'weather_wind_dir',
                  'weather_precip_pct', 'roof_state', 'tv_channel'):
            game.pop(f, None)
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# 9. draw_box(): In Progress edge branches
# ---------------------------------------------------------------------------

@needs_pil
class TestDrawBoxInProgress:
    def test_long_pitcher_name_fit_text_fallback(self, white_image, team_data):
        """Long pitcher name fit text fallback."""
        game = _live_game(
            current_pitcher='Bartholomew Christopherson-Longname',
            last_pitch_type='FB', last_pitch_speed=97.2,
        )
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_pitch_count_without_speed(self, white_image, team_data):
        """Pitch count without speed."""
        game = _live_game(last_pitch_speed=None, pitch_count=55)
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_at_bat_pitch_count_fallback_with_speed(self, white_image, team_data):
        """at_bat_pitch_count renders when pitch_count (game-level) is absent —
        timelapse frames only have the per-at-bat count."""
        game = _live_game(at_bat_pitch_count=3)
        game.pop('pitch_count', None)
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_at_bat_pitch_count_fallback_no_speed(self, white_image, team_data):
        """at_bat_pitch_count fallback also works when last_pitch_speed is absent."""
        game = _live_game(at_bat_pitch_count=5, last_pitch_speed=None)
        game.pop('pitch_count', None)
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_ab_done_shows_next_batter(self, white_image, team_data):
        """Ab done shows next batter."""
        game = _live_game(
            current_at_bat_complete=True, due_up='Freddie Freeman',
            current_inning=5, inningState='Top',
        )
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_save_situation_flag(self, white_image, team_data):
        """Save situation flag."""
        game = _live_game(save_situation=True, current_inning=9, inningState='Bottom',
                           num_of_outs=2)
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_active_no_no_perfect_game_label(self, white_image, team_data):
        """Active no no perfect game label."""
        game = _live_game(perfect_game=True, current_inning=7, inningState='Top')
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_active_no_no_no_hitter_label(self, white_image, team_data):
        """Active no no no hitter label."""
        game = _live_game(no_hitter=True, current_inning=8, inningState='Bottom')
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_all_strike_call_codes(self, white_image, team_data):
        """strike_calls covering every code exercises both swinging/foul and looking paths."""
        game = _live_game(strikes=2, strike_calls=['S', 'F'])
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_strike_calls_looking(self, white_image, team_data):
        """Strike calls looking."""
        game = _live_game(strikes=2, strike_calls=['C', 'C'])
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_stolen_base_header_invert(self, white_image, team_data):
        """Stolen base header invert."""
        game = _live_game(last_play='Stolen Base 2B', last_play_rbi=0)
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_manfred_man_extra_innings_no_play_yet(self, white_image, team_data):
        """Manfred man extra innings no play yet."""
        game = _live_game(
            current_inning=10, inningState='Top', num_of_outs=0,
            runner_on_second='Auto Runner', last_play=None, sub_event=None,
            at_bat_pitch_count=0, balls=0, strikes=0,
        )
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_challenge_state_with_logo_found(self, white_image, team_data):
        """Challenge state with logo found."""
        game = _live_game(
            detailed_state='Player challenge', challenge_team_abbr='LAD',
        )
        from image_box import draw_box
        with patch('image_box._logo_small', return_value=_tiny_logo(14)):
            result = draw_box(white_image, 32, 30, game, team_data, use_logos=True)
        assert isinstance(result, Image.Image)

    def test_challenge_state_with_logo_missing(self, white_image, team_data):
        """Challenge state with logo missing."""
        game = _live_game(
            detailed_state='Manager challenge', challenge_team_abbr='SF',
        )
        from image_box import draw_box
        with patch('image_box._logo_small', return_value=None):
            result = draw_box(white_image, 32, 30, game, team_data, use_logos=True)
        assert isinstance(result, Image.Image)

    def test_mid_inning_pitching_change_long_names(self, white_image, team_data):
        """Mid-inning PC panel with very long names forces the font-shrink truncation loop."""
        game = _live_game(
            sub_event='PC: Ferdinand Newpitchernameiswaytoolong',
            in_hole='Christopher Inholelongname',
            due_up='Alexander Duelongname',
            current_hitter='Maximilian Currentlongname',
            num_of_outs=1, at_bat_pitch_count=3,
            inningState='Top',
        )
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_between_innings_pitching_change_long_pitcher_name(self, white_image, team_data):
        """Between innings pitching change long pitcher name."""
        game = _between_innings_game(
            sub_event='PC: Bartholomew Longpitchernamefortruncation',
            next_pitcher=None,
        )
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_between_innings_game_ending_state_suppresses_panel(self, white_image, team_data):
        """Between innings game ending state suppresses panel."""
        game = _between_innings_game(
            current_inning=9, inningState='End', away_runs=5, home_runs=3,
        )
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_num_outs_ge_3_shows_linescore_not_diamonds(self, white_image, team_data):
        """API lag: 3 outs recorded but inningState hasn't flipped yet."""
        game = _live_game(inningState='Top', num_of_outs=3)
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_win_prob_bar_with_logos_found(self, white_image, team_data):
        """Win prob bar with logos found."""
        game = _live_game(away_win_probability=48.0, home_win_probability=52.0)
        from image_box import draw_box
        with patch('image_box._logo_small', return_value=_tiny_logo(18)):
            result = draw_box(white_image, 32, 30, game, team_data, use_logos=True,
                               show_win_prob=True)
        assert isinstance(result, Image.Image)

    def test_win_prob_bar_overlap_adjustment(self, white_image, team_data):
        """Near-identical win probabilities force the logo-overlap separation logic."""
        game = _live_game(away_win_probability=50.0, home_win_probability=50.0)
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False,
                           show_win_prob=True)
        assert isinstance(result, Image.Image)

    def test_win_prob_fractional_values_scaled(self, white_image, team_data):
        """Probabilities given as fractions (<=1.5 sum) get scaled to percentages."""
        game = _live_game(away_win_probability=0.4, home_win_probability=0.6)
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False,
                           show_win_prob=True)
        assert isinstance(result, Image.Image)

    def test_run_scored_header_invert(self, white_image, team_data):
        """Run scored header invert."""
        game = _live_game(last_play_rbi=2, score_changed=True)
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False,
                           score_changed=True)
        assert isinstance(result, Image.Image)

    def test_fielder_enhanced_flyout_from_description(self, white_image, team_data):
        """Fielder enhanced flyout from description."""
        game = _live_game(
            last_play='Flyout', last_play_description='Fly out to center fielder',
            last_play_inning=7, last_play_is_top=True, current_inning=7,
            inningState='Top',
        )
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_grounded_into_double_play_from_description(self, white_image, team_data):
        """Grounded into double play from description."""
        game = _live_game(
            last_play='Grounded Into DP', last_play_description='shortstop to second baseman to first baseman',
            last_play_inning=7, last_play_is_top=True, current_inning=7,
            inningState='Top',
        )
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_strikeout_looking_upgrades_to_kl(self, white_image, team_data):
        """Strikeout looking upgrades to kl."""
        game = _live_game(
            last_play='Strikeout', last_play_description='strikes out looking',
            last_play_inning=7, last_play_is_top=True, current_inning=7,
            inningState='Top',
        )
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_rbi_home_run_grand_slam_label(self, white_image, team_data):
        """Rbi home run grand slam label."""
        game = _live_game(
            last_play='Home Run', last_play_rbi=4,
            last_play_inning=7, last_play_is_top=True, current_inning=7,
            inningState='Top',
        )
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_rbi_two_run_home_run_label(self, white_image, team_data):
        """Rbi two run home run label."""
        game = _live_game(
            last_play='Home Run', last_play_rbi=2,
            last_play_inning=7, last_play_is_top=True, current_inning=7,
            inningState='Top',
        )
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_between_innings_due_up_fallback(self, white_image, team_data):
        """Between innings due up fallback."""
        game = _between_innings_game(last_play=None, sub_event=None,
                                      current_hitter='Mookie Betts')
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# 10. draw_wide_box() / _draw_wide_right_panel edge branches
# ---------------------------------------------------------------------------

@needs_pil
class TestDrawWideBoxMore:
    def test_run_scored_header_invert_both_cells(self, white_image, team_data):
        """Run scored header invert both cells."""
        from image_box import draw_wide_box
        game = _live_game(last_play_rbi=1)
        result = draw_wide_box(white_image, 0, 0, game, team_data, score_changed=True)
        assert isinstance(result, Image.Image)

    def test_between_innings_no_header_invert(self, white_image, team_data):
        """Between innings no header invert."""
        from image_box import draw_wide_box
        game = _between_innings_game(last_play_rbi=3)
        result = draw_wide_box(white_image, 0, 0, game, team_data, score_changed=True)
        assert isinstance(result, Image.Image)

    def test_right_panel_strike_calls_swinging_and_foul(self, white_image, team_data):
        """Right panel strike calls swinging and foul."""
        from image_box import draw_wide_box
        game = _live_game(strikes=2, strike_calls=['S', 'F'])
        result = draw_wide_box(white_image, 0, 0, game, team_data)
        assert isinstance(result, Image.Image)

    def test_right_panel_pitches_off_tile_clipped(self, white_image, team_data):
        """Pitches far outside the panel's vertical range are clipped, not drawn."""
        from image_box import draw_wide_box
        game = _live_game(ab_pitches=[
            {'seq': 1, 'px': 0.0, 'pz': 50.0, 'sz_top': 3.4, 'sz_bot': 1.6,
             'code': 'C', 'pt_abbr': 'FB'},
            {'seq': 2, 'px': 0.0, 'pz': -50.0, 'sz_top': 3.4, 'sz_bot': 1.6,
             'code': 'B', 'pt_abbr': 'FB'},
        ])
        result = draw_wide_box(white_image, 0, 0, game, team_data)
        assert isinstance(result, Image.Image)

    def test_right_panel_pitch_label_too_wide_truncated(self, white_image, team_data):
        """Right panel pitch label too wide truncated."""
        from image_box import draw_wide_box
        game = _live_game(ab_pitches=[
            {'seq': 1, 'px': 0.0, 'pz': 2.5, 'sz_top': 3.4, 'sz_bot': 1.6,
             'code': 'C', 'pt_abbr': 'SUPERLONGPITCHNAME'},
        ])
        result = draw_wide_box(white_image, 0, 0, game, team_data)
        assert isinstance(result, Image.Image)

    def test_right_panel_three_outs_hides_bases(self, white_image, team_data):
        """Right panel three outs hides bases."""
        from image_box import draw_wide_box
        game = _live_game(num_of_outs=3)
        result = draw_wide_box(white_image, 0, 0, game, team_data)
        assert isinstance(result, Image.Image)

    def test_right_panel_no_pitcher_ks_bottom_half(self, white_image, team_data):
        """Right panel no pitcher ks bottom half."""
        from image_box import draw_wide_box
        game = _live_game(inningState='Bottom', away_pitcher_ks=[])
        result = draw_wide_box(white_image, 0, 0, game, team_data)
        assert isinstance(result, Image.Image)

    def test_right_panel_away_pitcher_ks_bottom_half(self, white_image, team_data):
        """Right panel away pitcher ks bottom half."""
        from image_box import draw_wide_box
        game = _live_game(inningState='Bottom', away_pitcher_ks=['K', 'L', 'K'])
        result = draw_wide_box(white_image, 0, 0, game, team_data)
        assert isinstance(result, Image.Image)

    def test_right_panel_ab_done_shows_next_batter(self, white_image, team_data):
        """Right panel ab done shows next batter."""
        from image_box import draw_wide_box
        game = _live_game(current_at_bat_complete=True, due_up='Will Smith',
                           current_inning=5, inningState='Top')
        result = draw_wide_box(white_image, 0, 0, game, team_data)
        assert isinstance(result, Image.Image)

    def test_right_panel_long_pitcher_name_shrinks_font(self, white_image, team_data):
        """Right panel long pitcher name shrinks font."""
        from image_box import draw_wide_box
        game = _live_game(current_pitcher='Bartholomew Christopherson-Longname',
                           last_pitch_type='FB', last_pitch_speed=98.1, pitch_count=90)
        result = draw_wide_box(white_image, 0, 0, game, team_data)
        assert isinstance(result, Image.Image)

    def test_right_panel_long_batter_label_shrinks_font(self, white_image, team_data):
        """Right panel long batter label shrinks font."""
        from image_box import draw_wide_box
        game = _live_game(current_play_batter='Maximilian Verylongbattername',
                           batter_hits=3, batter_at_bats=4)
        result = draw_wide_box(white_image, 0, 0, game, team_data)
        assert isinstance(result, Image.Image)

    def test_right_panel_not_in_progress_returns_early(self, white_image, team_data):
        """detailed_state != 'In Progress' -> header-only, no pitch/zone content."""
        from image_box import draw_wide_box
        game = _base_game(detailed_state='Final')
        import image_box
        image_box.set_historical_mode(True)
        try:
            result = draw_wide_box(white_image, 0, 0, game, team_data)
        finally:
            image_box.set_historical_mode(False)
        assert isinstance(result, Image.Image)


# ---------------------------------------------------------------------------
# 11. draw_out_of_town_score_board end-to-end sanity with the above scenarios
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 12. Additional targeted branch coverage (round 2)
# ---------------------------------------------------------------------------

@needs_pil
def test_draw_backward_k_dead_code_direct(white_image):
    """_draw_backward_k (no trailing 's') is unused dead code in the module but
    still importable — call it directly for coverage."""
    from image_box import _draw_backward_k
    from image_assets import _get_font
    _draw_backward_k(white_image, 10, 10, _get_font(14))


@needs_pil
def test_next_game_preview_logo_w_found(white_image):
    """_logo_w's use_logos branch (measuring an existing logo) is exercised via
    the two-different-games path, which calls _measure_half -> _logo_w."""
    from image_box import _draw_next_game_preview
    draw = ImageDraw.Draw(white_image)
    tmrw_games = [
        {'home_team_id': 111, 'away_team_id': 119, 'game_pk': 20,
         'game_start_utc': '2026-06-21T23:05:00Z'},
        {'home_team_id': 137, 'away_team_id': 147, 'game_pk': 21,
         'game_start_utc': '2026-06-22T01:10:00Z'},
    ]
    with patch('image_box._logo_small', return_value=_tiny_logo(14)):
        _draw_next_game_preview(
            draw, white_image, 32, 30, tmrw_games, 137, 119,
            _PREV_TEAM_DATA, use_logos=True, horizonta_len=135, vertical_len=110,
        )


@needs_pil
class TestSeriesWinnerResolution:
    def _render_final(self, white_image, team_data, **overrides):
        """Render final."""
        import image_box
        game = _base_game(detailed_state='Final', **overrides)
        image_box.set_historical_mode(True)
        try:
            from image_box import draw_box
            with patch('image_box.load_json_file', return_value={}), \
                 patch('image_box.save_off_results'):
                return draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        finally:
            image_box.set_historical_mode(False)

    def test_sweep_home_wins_via_series_result(self, white_image, team_data):
        """series_result names the HOME team as the sweeper (SF)."""
        result = self._render_final(
            white_image, team_data,
            series_total_games=3, series_wins=3, series_losses=0,
            series_description='Regular Season', series_result='SF wins 3-0',
            away_team_is_winner=False, home_team_is_winner=True,
        )
        assert isinstance(result, Image.Image)

    def test_sweep_fallback_to_is_winner_flag(self, white_image, team_data):
        """No parseable series_result -> falls back to away_team_is_winner."""
        result = self._render_final(
            white_image, team_data,
            series_total_games=3, series_wins=3, series_losses=0,
            series_description='Regular Season', series_result='',
            away_team_is_winner=True, home_team_is_winner=False,
        )
        assert isinstance(result, Image.Image)

    def test_series_leading_home_via_series_result(self, white_image, team_data):
        """Series leading home via series result."""
        result = self._render_final(
            white_image, team_data,
            series_total_games=5, series_wins=2, series_losses=1,
            series_is_over=False, series_is_tied=False,
            series_result='SF wins 2-1',
            away_team_is_winner=False, home_team_is_winner=True,
        )
        assert isinstance(result, Image.Image)

    def test_series_leading_with_overline(self, white_image, team_data):
        """Coincidental wins+losses==total while series_is_over is still False."""
        result = self._render_final(
            white_image, team_data,
            series_total_games=3, series_wins=2, series_losses=1,
            series_description='Regular Season',
            series_is_over=False, series_is_tied=False,
            series_result='', away_team_is_winner=True, home_team_is_winner=False,
        )
        assert isinstance(result, Image.Image)

    def test_series_tied_with_overline(self, white_image, team_data):
        """Series tied with overline."""
        result = self._render_final(
            white_image, team_data,
            series_total_games=4, series_wins=2, series_losses=2,
            series_description='Regular Season',
            series_is_tied=True, series_is_over=False,
        )
        assert isinstance(result, Image.Image)

    def test_postponed_series_leader_home(self, white_image, team_data):
        """Postponed series leader home."""
        import image_box
        game = _base_game(
            detailed_state='Postponed', away_runs=None, home_runs=None,
            series_total_games=4, series_wins=1, series_losses=0,
            series_result='SF leads 1-0',
        )
        image_box.set_historical_mode(True)
        try:
            from image_box import draw_box
            result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        finally:
            image_box.set_historical_mode(False)
        assert isinstance(result, Image.Image)


@needs_pil
class TestEndUtcExceptionPaths:
    def test_final_malformed_end_time_hits_fallback_window_calc(self, white_image, team_data):
        """A malformed game_end_time_utc under historical_mode is safe (no network is
        ever reached because _historical_mode short-circuits the preview block) but
        still exercises the except-Exception fallback for _in_linescore_window."""
        import image_box
        game = _base_game(detailed_state='Final', game_end_time_utc='not-a-real-timestamp')
        image_box.set_historical_mode(True)
        try:
            from image_box import draw_box
            with patch('image_box.load_json_file', return_value={}), \
                 patch('image_box.save_off_results'):
                result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        finally:
            image_box.set_historical_mode(False)
        assert isinstance(result, Image.Image)

    def test_final_malformed_end_time_in_preview_block(self, white_image, team_data):
        """Same malformed timestamp but with historical_mode OFF so the next-game
        preview block's own try/except around _end_utc_str is reached too. Every
        network/disk touchpoint downstream is mocked."""
        import image_box
        game = _base_game(detailed_state='Final', game_end_time_utc='not-a-real-timestamp')
        with patch('image_box._load_tomorrow_games', return_value=None), \
             patch('image_box.load_json_file', return_value={}), \
             patch('image_box.save_off_results'):
            from image_box import draw_box
            result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_final_stale_game_date_marks_window_expired(self, white_image, team_data):
        """No end-time at all, but game_date is clearly in the past -> window_expired
        via the game_date comparison branch, without touching _get_or_set_final_time."""
        import image_box
        game = _base_game(detailed_state='Final', game_end_time_utc=None,
                           game_date='2000-01-01')
        fake_tomorrow = {'date': '2026-06-21', 'games': [
            {'home_team_id': 137, 'away_team_id': 119, 'game_pk': 30,
             'game_start_utc': '2026-06-21T23:05:00Z'},
        ]}
        with patch('image_box._load_tomorrow_games', return_value=fake_tomorrow), \
             patch('image_box.load_json_file', return_value={}), \
             patch('image_box.save_off_results'):
            from image_box import draw_box
            result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)

    def test_final_no_end_time_no_game_date_uses_final_time_cache(self, white_image, team_data):
        """No end-time and no game_date -> falls all the way to _get_or_set_final_time."""
        import image_box
        game = _base_game(detailed_state='Final', game_end_time_utc=None, game_date=None,
                           game_pk=777001)
        with patch('image_box._load_tomorrow_games', return_value=None), \
             patch('image_box.load_json_file', return_value={}), \
             patch('image_box.save_off_results'):
            from image_box import draw_box
            result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
        assert isinstance(result, Image.Image)


@needs_pil
class TestPlayByPlayFielderMapping:
    """Covers the remaining _abbr_play -> fielder-position enhancement branches."""

    def _render(self, white_image, team_data, **overrides):
        """Render."""
        game = _live_game(
            last_play_inning=7, last_play_is_top=True, current_inning=7,
            inningState='Top', **overrides,
        )
        from image_box import draw_box
        return draw_box(white_image, 32, 30, game, team_data, use_logos=False)

    def test_lineout_with_fielder(self, white_image, team_data):
        """Lineout with fielder."""
        result = self._render(white_image, team_data, last_play='Lineout',
                               last_play_description='line out to left fielder')
        assert isinstance(result, Image.Image)

    def test_popout_with_fielder(self, white_image, team_data):
        """Popout with fielder."""
        result = self._render(white_image, team_data, last_play='Popout',
                               last_play_description='pop out to catcher')
        assert isinstance(result, Image.Image)

    def test_sac_fly_with_fielder(self, white_image, team_data):
        """Sac fly with fielder."""
        result = self._render(white_image, team_data, last_play='Sac Fly',
                               last_play_description='sac fly to right fielder')
        assert isinstance(result, Image.Image)

    def test_sac_bunt_with_fielder(self, white_image, team_data):
        """Sac bunt with fielder."""
        result = self._render(white_image, team_data, last_play='Sac Bunt',
                               last_play_description='sac bunt, third baseman to first baseman')
        assert isinstance(result, Image.Image)

    def test_groundout_fielder_sequence(self, white_image, team_data):
        """Groundout fielder sequence."""
        result = self._render(white_image, team_data, last_play='Groundout',
                               last_play_description='shortstop to second baseman to first baseman')
        assert isinstance(result, Image.Image)

    def test_triple_play_fielder_sequence(self, white_image, team_data):
        """Triple play fielder sequence."""
        result = self._render(white_image, team_data, last_play='Triple Play',
                               last_play_description='shortstop to second baseman to first baseman')
        assert isinstance(result, Image.Image)

    def test_caught_stealing_fielder_sequence(self, white_image, team_data):
        """Caught stealing fielder sequence."""
        result = self._render(white_image, team_data, last_play='Caught Stealing',
                               last_play_description='catcher to shortstop')
        assert isinstance(result, Image.Image)

    def test_pickoff_with_fielder(self, white_image, team_data):
        """Pickoff with fielder."""
        result = self._render(white_image, team_data, last_play='Pickoff',
                               last_play_description='pitcher to first baseman')
        assert isinstance(result, Image.Image)

    def test_pickoff_without_fielder_description(self, white_image, team_data):
        """Pickoff without fielder description."""
        result = self._render(white_image, team_data, last_play='Pickoff',
                               last_play_description='')
        assert isinstance(result, Image.Image)

    def test_field_error_with_fielder(self, white_image, team_data):
        """Field error with fielder."""
        result = self._render(white_image, team_data, last_play='Field Error',
                               last_play_description='field error by third baseman')
        assert isinstance(result, Image.Image)

    def test_rbi_single_gets_rbi_prefix(self, white_image, team_data):
        """Rbi single gets rbi prefix."""
        result = self._render(white_image, team_data, last_play='Single', last_play_rbi=1)
        assert isinstance(result, Image.Image)

    def test_rbi_double_gets_multi_rbi_prefix(self, white_image, team_data):
        """Rbi double gets multi rbi prefix."""
        result = self._render(white_image, team_data, last_play='Double', last_play_rbi=2)
        assert isinstance(result, Image.Image)


@needs_pil
def test_between_innings_play_display_from_matching_last_play(white_image, team_data):
    """A last_play matching the current half-inning is shown between innings."""
    game = _between_innings_game(
        last_play='Single', last_play_rbi=0,
        last_play_inning=7, last_play_is_top=True, current_inning=7,
    )
    from image_box import draw_box
    result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
    assert isinstance(result, Image.Image)


@needs_pil
def test_between_innings_due_up_name_truncated(white_image, team_data):
    """Between innings due up name truncated."""
    game = _between_innings_game(
        last_play=None, sub_event=None,
        current_hitter='Bartholomew Christopherson Longname The Third',
    )
    from image_box import draw_box
    result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
    assert isinstance(result, Image.Image)


@needs_pil
def test_delayed_reason_truncated(white_image, team_data):
    """Delayed reason truncated."""
    game = _base_game(
        detailed_state='Delayed', current_inning=4, inningState='Top',
        away_runs=1, home_runs=0,
        postpone_reason='A very long delay reason description that will not fit',
    )
    import image_box
    image_box.set_historical_mode(True)
    try:
        from image_box import draw_box
        result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
    finally:
        image_box.set_historical_mode(False)
    assert isinstance(result, Image.Image)


@needs_pil
def test_scheduled_with_streak_map_shows_l10_and_streak(white_image, team_data):
    """Scheduled with streak map shows l10 and streak."""
    from image_box import draw_box
    game = _base_game(detailed_state='Scheduled', away_runs=None, home_runs=None)
    streak_map = {
        '119': {'l10_wins': 7, 'l10_losses': 3, 'streak': 'W3'},
        '137': {'l10_wins': 4, 'l10_losses': 6, 'streak': 'L2'},
    }
    result = draw_box(white_image, 32, 30, game, team_data, use_logos=False,
                       streak_map=streak_map)
    assert isinstance(result, Image.Image)


@needs_pil
def test_sweep_with_doubleheader_game_number_beside_duration(white_image, team_data):
    """Sweep with doubleheader game number beside duration."""
    import image_box
    game = _base_game(
        detailed_state='Final', game_duration_minutes=175,
        series_total_games=3, series_wins=3, series_losses=0,
        series_description='Regular Season', series_result='LAD wins 3-0',
        away_team_is_winner=True, home_team_is_winner=False,
        double_header='Y', game_number=2,
    )
    image_box.set_historical_mode(True)
    try:
        from image_box import draw_box
        with patch('image_box.load_json_file', return_value={}), \
             patch('image_box.save_off_results'):
            result = draw_box(white_image, 32, 30, game, team_data, use_logos=False)
    finally:
        image_box.set_historical_mode(False)
    assert isinstance(result, Image.Image)


@needs_pil
def test_win_prob_invalid_string_values_default_to_50_50(white_image, team_data):
    """Win prob invalid string values default to 50 50."""
    game = _live_game(away_win_probability='N/A', home_win_probability='N/A')
    from image_box import draw_box
    result = draw_box(white_image, 32, 30, game, team_data, use_logos=False,
                       show_win_prob=True)
    assert isinstance(result, Image.Image)


@needs_pil
def test_win_prob_away_greater_triggers_overlap_shift(white_image, team_data):
    """away_wp slightly higher than home_wp with both high -> away_logo_x > home_logo_x
    and closer than MIN_SEP, exercising the away-greater overlap-adjustment branch."""
    game = _live_game(away_win_probability=58.0, home_win_probability=55.0)
    from image_box import draw_box
    result = draw_box(white_image, 32, 30, game, team_data, use_logos=False,
                       show_win_prob=True)
    assert isinstance(result, Image.Image)


@needs_pil
class TestWidePanelExtra:
    def test_header_events_with_embedded_kl_token(self, white_image, team_data):
        """A play token containing 'Kl' with surrounding text exercises the
        text-segment-before-backwards-K draw path in _draw_text_seg."""
        from image_box import draw_wide_box
        game = _live_game(half_inning_plays=['RBI Kl', '1B', 'F9'])
        result = draw_wide_box(white_image, 0, 0, game, team_data)
        assert isinstance(result, Image.Image)

    def test_header_events_trims_leading_marker_after_pop(self, white_image, team_data):
        """First event is long enough to force a pop; the new front token is a
        half-inning marker and must itself be trimmed (inner while loop)."""
        from image_box import draw_wide_box
        game = _live_game(half_inning_plays=[
            'Grand Slam Down The Line In The Corner', '^',
            'K', 'K', 'K', 'K', 'K', 'K', 'K',
        ])
        result = draw_wide_box(white_image, 0, 0, game, team_data)
        assert isinstance(result, Image.Image)

    def test_between_innings_next_batter_truncated(self, white_image, team_data):
        """Between innings next batter truncated."""
        from image_box import draw_wide_box
        game = _between_innings_game(
            next_batter_1='Bartholomew Christopherson Longname The Third Esquire',
        )
        result = draw_wide_box(white_image, 0, 0, game, team_data)
        assert isinstance(result, Image.Image)

    def test_batter_label_shrinks_past_font9(self, white_image, team_data):
        """Batter label shrinks past font9."""
        from image_box import draw_wide_box
        game = _live_game(
            current_play_batter='Maximilian Bartholomew Christopherson-Longname The Fourth',
            batter_hits=1, batter_at_bats=1,
        )
        result = draw_wide_box(white_image, 0, 0, game, team_data)
        assert isinstance(result, Image.Image)


@needs_pil
def test_grid_final_with_flags_and_series(white_image, team_data):
    """Grid final with flags and series."""
    import image_box
    from image_grid import draw_out_of_town_score_board
    games = [
        _base_game(game_pk=1, detailed_state='Final', no_hitter=True),
        _base_game(game_pk=2, detailed_state='Final', walk_off=True),
        _base_game(game_pk=3, detailed_state='Suspended', current_inning=6, inningState='Top'),
        _base_game(game_pk=4, detailed_state='Cancelled: Rain'),
        _live_game(game_pk=5, save_situation=True),
    ]
    image_box.set_historical_mode(True)
    try:
        result = draw_out_of_town_score_board(white_image, games, team_data)
    finally:
        image_box.set_historical_mode(False)
    assert isinstance(result, Image.Image)
