import os
import random
from datetime import datetime

import pytz

from util import load_json_file, load_yaml_file, save_off_results
from image_assets import (
    picdir, _get_font, _logo_small,
    Image, ImageDraw, ImageFont, ImageOps,
)
from image_utils import (
    normalize_dict, standings_dict,
    draw_diamond, draw_circle,
    _pitcher_line, _clean_venue_name,
)
from image_standings import _WC_STRIP_H
from image_box import draw_box, draw_wide_box


def generate_linescore(col_start, row_start, team_abbr, Himage, new_image_dict):

    data_linescore = load_json_file('linescore.json').get(team_abbr)
    data = load_json_file('games_scheduled.json')
    standings_data = load_json_file('standings.json')

    if team_abbr == 'LIVE':
        game_id = load_json_file('linescore.json').get('live_game_id')
    else:
        game_id = data.get('team_to_game_id').get(team_abbr)

    game_info = data.get('games_scheduled').get(game_id)
    away_probable = _pitcher_line(game_info.get('away_probable'), game_info.get('away_probable_note'))
    home_probable = _pitcher_line(game_info.get('home_probable'), game_info.get('home_probable_note'))
    winner_name = game_info.get('winner_name')
    loser_name = game_info.get('loser_name')
    venue = game_info.get('venue')
    home_team_win_probability = str(data_linescore.get('home_team_win_probability'))[:4] + '%'
    away_team_win_probability = str(data_linescore.get('away_team_win_probability'))[:4] + '%'

    result_event = data_linescore.get('result_event')

    weather_condition = game_info.get('weather_condition',)
    weather_temp = game_info.get('weather_temp',)
    weather_wind = game_info.get('weather_wind',)

    # magic string to account for extra innings
    if int(data_linescore.get('current_inning', 0)) > 9:
        start_inning = int(data_linescore.get('current_inning')) - 8
    else:
        start_inning = 1

    inning_header = [ i + start_inning for i in range(9)] + ['R', 'H', 'E']

    # Handle missing team abbreviations gracefully for linescore
    home_team_id = str(game_info.get('home_team_id'))
    away_team_id = str(game_info.get('away_team_id'))

    home_team = standings_data.get('team_abbreviation', {}).get(home_team_id, f'T{home_team_id}')
    away_team = standings_data.get('team_abbreviation', {}).get(away_team_id, f'T{away_team_id}')

    away = data_linescore.get('away_runs_innings') + [data_linescore.get('away_runs'),data_linescore.get('away_hits'),data_linescore.get('away_errors')]
    home = data_linescore.get('home_runs_innings') + [data_linescore.get('home_runs'),data_linescore.get('home_hits'),data_linescore.get('home_errors')]
    game_state = game_info.get('detailed_state')
    start_time = game_info.get('game_start')

    home_is_winner = None
    if game_info.get('away_team_is_winner'):
        home_is_winner = 'L'
    elif game_info.get('home_team_is_winner'):
        home_is_winner = 'W'

    if (game_state == 'Final' or game_state == 'Game Over') and home[8] == None:
        home[8] = 'X'

    game_end_time = None
    _end_utc_str = game_info.get('game_end_time_utc')
    if _end_utc_str and game_state in ('Final', 'Game Over'):
        try:
            _tz_str = load_yaml_file('config.yaml').get('timezone', 'America/Chicago')
            _utc_dt = datetime.strptime(_end_utc_str[:19], "%Y-%m-%dT%H:%M:%S")
            game_end_time = pytz.utc.localize(_utc_dt).astimezone(pytz.timezone(_tz_str)).strftime("%I:%M:%S%p")
        except Exception:
            pass

    first_base = data_linescore.get('runner_first')
    second_base = data_linescore.get('runner_second')
    third_base = data_linescore.get('runner_third', None)
    outs = data_linescore.get('outs')

    if game_state == 'In Progress' and  data_linescore.get('inning_half')[:3] == 'Top' and  outs == 3:
        game_state = 'Mid ' + data_linescore.get('current_inning_ordinal')

    if game_state == 'In Progress' and  data_linescore.get('inning_half')[:3] == 'Bot' and  outs == 3:
        game_state = 'End ' + data_linescore.get('current_inning_ordinal')

    if game_state == 'In Progress':
        game_state = data_linescore.get('inning_half')[:3] + ' ' + data_linescore.get('current_inning_ordinal')

    new_image_dict[team_abbr] = {
        'home_team': home_team,
        'away_team': away_team,
        'away': away,
        'home': home,
        'game_state': game_state,
        'start_time': start_time,
        'first_base': first_base,
        'second_base': second_base,
        'third_base': third_base,
        'outs': outs,
        'winner_name': winner_name,
        'loser_name': loser_name,
        'result_event': result_event,
    }

    Himage = generate_image(Himage, col_start, row_start, away_team, home_team, away,
                            home, game_state, inning_header, first_base, second_base,
                            third_base, outs, start_time, home_is_winner, away_probable,
                            home_probable, winner_name, loser_name, venue,
                            home_team_win_probability, away_team_win_probability,
                            result_event, weather_condition, weather_temp, weather_wind,
                            home_team_id=home_team_id, away_team_id=away_team_id,
                            game_end_time=game_end_time)
    return Himage, new_image_dict

def _game_in_window(team_abbr, games_scheduled, window_secs=3600):
    """Return True if the team's game is live or ended within window_secs ago.

    window_secs defaults to 3600 (1 hour) but callers should pass
    ``config.get('final_linescore_minutes', 60) * 60`` so the value
    stays in sync with the YAML setting used everywhere else.
    """
    game_id = (games_scheduled or {}).get('team_to_game_id', {}).get(team_abbr)
    if not game_id:
        return True
    game_info = (games_scheduled or {}).get('games_scheduled', {}).get(game_id, {})
    if game_info.get('detailed_state') not in ('Final', 'Game Over', 'Final: Tied'):
        return True
    end_utc_str = game_info.get('game_end_time_utc')
    if not end_utc_str:
        return False
    try:
        end_utc = pytz.utc.localize(datetime.strptime(end_utc_str[:19], "%Y-%m-%dT%H:%M:%S"))
        return (datetime.now(pytz.utc) - end_utc).total_seconds() < window_secs
    except Exception:
        return False


def draw_boards():

    new_image_dict = {}
    config_data = load_yaml_file('config.yaml')
    linescore_data = load_json_file('linescore.json')
    games_scheduled = load_json_file('games_scheduled.json')
    Himage = Image.new('1', (800, 480), 255)  # 255: clear the frame
    col_start = 100
    row_start = 40

    _window_secs = config_data.get('final_linescore_minutes', 60) * 60

    team_abbr = None
    for _candidate in [config_data.get('primary'), config_data.get('primary_backup'), config_data.get('primary_backup_2')]:
        if linescore_data.get(_candidate) and _game_in_window(_candidate, games_scheduled, _window_secs):
            team_abbr = _candidate
            break

    if team_abbr:
        Himage, new_image_dict = generate_linescore(col_start, row_start, team_abbr, Himage, new_image_dict)

    team_abbr = None
    for _candidate in [config_data.get('secondary'), config_data.get('secondary_backup'), config_data.get('secondary_backup_2')]:
        if linescore_data.get(_candidate) and _game_in_window(_candidate, games_scheduled, _window_secs):
            team_abbr = _candidate
            break

    col_start = 100
    row_start = 180
    if team_abbr:
        Himage, new_image_dict = generate_linescore(col_start, row_start, team_abbr, Himage, new_image_dict)

    Himage = generate_standings(Himage, col_start=100, row_start=320)

    data = load_json_file('old_image_state.json')

    n1 = normalize_dict(data)
    n2 = normalize_dict(new_image_dict)

    changed_regions = []

    if n1 == n2:
        print('images the same')
        linescore_data['update_display'] = None
    else:
        print('image is different')

        print('saving off image...')
        linescore_data['update_display'] = True

        # Simple heuristic: check which keys changed and map to panels
        old_keys = set(data.keys()) if data else set()
        new_keys = set(new_image_dict.keys())
        all_keys = old_keys | new_keys
        for key in all_keys:
            old_val = data.get(key) if data else None
            new_val = new_image_dict.get(key)
            if old_val != new_val:
                # Map key to panel by checking row_start used in generate_linescore calls
                # Primary panel uses row_start=40, secondary uses row_start=180
                # Standings uses row_start=320
                # Since we can't easily map keys to panels, mark all panels changed
                changed_regions = []
                break
        # If we couldn't determine specific panels, empty list signals full refresh

        save_off_results(new_image_dict, "old_image_state")
    if config_data.get('dark_mode', False):
        Himage = ImageOps.invert(Himage.convert('L')).convert('1')
    Himage.save('temp.bmp')
    if not data:
        save_off_results(new_image_dict, "old_image_state")

    linescore_data['changed_regions'] = changed_regions
    save_off_results(linescore_data, "linescore")


def generate_image(Himage, col_start, row_start, away_team, home_team, away,
                   home, game_state, inning_header, first_base, second_base,
                   third_base, outs, start_time, home_is_winner, away_probable,
                   home_probable,winner_name, loser_name,  venue,
                   home_team_win_probability, away_team_win_probability, result_event,
                    weather_condition, weather_temp, weather_wind,
                   home_team_id=None, away_team_id=None, game_end_time=None):
    draw = ImageDraw.Draw(Himage)

    # Team logos in team name rows (24px bounding box, centered in 30px logo cell)
    _logo_size = 24
    if away_team_id:
        _away_logo = _logo_small(away_team, away_team_id, size=_logo_size)
        if _away_logo:
            _lw, _lh = _away_logo.size
            Himage.paste(_away_logo, (col_start + (30 - _lw) // 2, row_start + 31 + (29 - _lh) // 2))
            draw = ImageDraw.Draw(Himage)
    if home_team_id:
        _home_logo = _logo_small(home_team, home_team_id, size=_logo_size)
        if _home_logo:
            _lw, _lh = _home_logo.size
            Himage.paste(_home_logo, (col_start + (30 - _lw) // 2, row_start + 61 + (29 - _lh) // 2))
            draw = ImageDraw.Draw(Himage)

    font24 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 24)
    font18 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)
    font14 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 14)

    if game_state not in ('Final', 'Game Over','Scheduled','Pre-Game','Delayed','Postponed', 'Warmup') :
        outs_list = [None] * 3

        for i in range(1,4):
            outs_list[i-1] =  i <= outs

        draw_circle(Himage, (col_start + 20 - 95, row_start + 82), 8, outs_list[0])  # Circle 1 filled
        draw_circle(Himage, (col_start + 45 - 95, row_start + 82), 8, outs_list[1]) # Circle 2 not filled
        draw_circle(Himage, (col_start + 70 - 95, row_start + 82), 8, outs_list[2]) # Circle 3 filled

        draw_diamond(Himage, (col_start + 70 - 95, row_start + 45), 20, first_base) # first base at (150, 100) with size 20
        draw_diamond(Himage, (col_start + 45 - 95, row_start + 20), 20, second_base) # second base
        draw_diamond(Himage, (col_start + 20 - 95, row_start + 45), 20, third_base)  # third base

        draw.text(( col_start + 0 , row_start + 93), result_event , font = font18, fill = 0)

        # Win probability bar — away (left) filled, home (right) outlined
        try:
            home_wp = float(str(home_team_win_probability).replace('%', '').strip())
            away_wp = float(str(away_team_win_probability).replace('%', '').strip())
            if home_wp + away_wp <= 1.5:   # API returned 0-1 decimals
                home_wp *= 100
                away_wp *= 100
        except (ValueError, AttributeError):
            home_wp, away_wp = 50.0, 50.0

        BAR_X, BAR_Y, BAR_W, BAR_H = col_start, row_start + 113, 580, 14
        away_fill_px = max(0, min(BAR_W, int(BAR_W * away_wp / 100.0)))

        if away_fill_px > 0:
            draw.rectangle([BAR_X, BAR_Y, BAR_X + away_fill_px, BAR_Y + BAR_H], fill=0)
        draw.rectangle([BAR_X, BAR_Y, BAR_X + BAR_W, BAR_Y + BAR_H], outline=0)

        LOGO_SZ = 12
        logo_y = BAR_Y + (BAR_H - LOGO_SZ) // 2
        if home_wp >= away_wp:
            # Home leads — logo on right (white) side
            logo = _logo_small(home_team, home_team_id or 0, size=LOGO_SZ)
            if logo:
                Himage.paste(logo, (BAR_X + BAR_W - LOGO_SZ - 2, logo_y))
        else:
            # Away leads — logo on left (dark) side, inverted to white-on-black
            logo = _logo_small(away_team, away_team_id or 0, size=LOGO_SZ)
            if logo:
                white_patch = Image.new('1', logo.size, 255)
                mask = ImageOps.invert(logo.convert('L'))
                Himage.paste(white_patch, (BAR_X + 2, logo_y), mask=mask)

    if home_is_winner == 'L':
        draw_circle(Himage, (col_start + 85, row_start + 45), 8, True)
    elif home_is_winner == 'W':
        draw_circle(Himage, (col_start + 85, row_start + 75), 8, True)

    if not away_probable:
        away_probable = ''
    if not home_probable:
        home_probable = ''

    DISPLAY_PROBS = False

    if game_state in ('Scheduled', 'Pre-Game', 'Warmup', 'Delayed Start'):
        innings = [None] * 12
        away, home = innings, innings
        if game_state not in ('Warmup', 'Delayed Start'):
            game_state = start_time
        elif game_state == 'Delayed Start':
            game_state = 'Delayed'
        DISPLAY_PROBS = True

        draw.text((25 + col_start + 82, 30 + row_start), away_probable, font = font24, fill = 0)
        draw.text((25 + col_start + 82, 60 + row_start), home_probable, font = font24, fill = 0)

    elif game_state in ('Final', 'Game Over') and winner_name and loser_name:
        draw.text(( col_start + 0 , row_start + 93), f'WP: {winner_name}  LP: {loser_name}' , font = font18, fill = 0)

    if game_state in ('Final', 'Game Over') and game_end_time:
        _et_w = font14.getlength(game_end_time)
        draw.text((col_start + 580 - _et_w, row_start + 113), game_end_time, font=font14, fill=0)

    draw.text((0 + col_start, 8 + row_start), game_state, font = font18, fill = 0, stroke_width=1, stroke_fill=0)
    draw.text((30 + col_start, 30 + row_start), away_team, font = font24, fill = 0)
    draw.text((30 + col_start, 60 + row_start), home_team, font = font24, fill = 0)

    if game_state == 'Delayed Start':
        game_state = 'Delayed'

    if weather_temp and weather_condition and weather_wind:
        draw.text(( col_start + 0 , row_start - 18), f'{weather_temp}°F | {weather_condition} | {weather_wind}', font = font14, fill = 0)
    _venue_str = _clean_venue_name(venue) or (venue or '')
    _venue_max_x = 800 - (col_start + 460)
    for _vfont in (font18, font14, _get_font(5)):
        if _vfont.getlength(_venue_str) <= _venue_max_x:
            break
    draw.text((col_start + 460, row_start + 93), _venue_str, font=_vfont, fill=0)

    # lines horizontal (top border closes the box; left/right borders via verticals at i=0 and i=12)
    draw.line((col_start, row_start,       580 + col_start, row_start),       fill=0)  # top border
    draw.line((col_start, row_start,       col_start,       90 + row_start),  fill=0)  # left border
    draw.line((col_start, 30 + row_start, 580 + col_start, 30 + row_start), fill = 0)
    draw.line((col_start, 60 + row_start, 580 + col_start, 60 + row_start), fill = 0)
    draw.line((col_start, 90 + row_start, 580 + col_start, 90 + row_start), fill = 0)

    def _cell_center(fnt, val, cell_idx, y):
        """Draw val horizontally centred in the 40-px column at index cell_idx.

        Renders to a scratch buffer at a known anchor (ox, oy) and measures
        the actual leftmost/rightmost ink pixel so the ink center lands at
        the column midpoint.  Max horizontal error ≤ 0.5 px (rounding).
        """
        cell_left = 100 + 40 * cell_idx + col_start
        cell_cx = cell_left + 20   # midpoint of the 40-px column
        txt = str(val)
        if not txt:
            return
        try:
            bb = fnt.getbbox(txt)
            ox, oy = 2, 2
            buf_w = max(bb[2] + ox + 2, 6)
            buf_h = max(bb[3] + oy + 2, 6)
            buf = Image.new('L', (buf_w, buf_h), 255)
            ImageDraw.Draw(buf).text((ox, oy), txt, font=fnt, fill=0)
            bpx = buf.load()
            ink_xs = [c for r in range(buf_h) for c in range(buf_w) if bpx[c, r] < 128]
            if not ink_xs:
                draw.text((cell_left + 10, y), txt, font=fnt, fill=0)
                return
            ink_cx = (min(ink_xs) + max(ink_xs)) / 2 - ox   # relative to draw anchor
            draw.text((round(cell_cx - ink_cx), y), txt, font=fnt, fill=0)
        except Exception:
            tw = int(fnt.getlength(txt))
            draw.text((cell_left + (40 - tw) // 2, y), txt, font=fnt, fill=0)

    for i in range(13):
        if i < 12:
            if away[i] is None:
                away[i] = ''
            if home[i] is None:
                home[i] = ''

            _cell_center(font24, inning_header[i], i, 0 + row_start)
            _cell_center(font24, away[i], i, 30 + row_start)
            _cell_center(font24, home[i], i, 60 + row_start)

        # vertical line
        if i >= 1 and i <= 8 and DISPLAY_PROBS:
            continue
        if i == 9 or i == 10:

            if i == 9:
                draw.line((100 + (40*i) + col_start, 0 + row_start + 88, 100 + (40*i) + 40 + col_start, +88 + row_start), fill = 0)
                draw.line((100 + (40*i) + col_start, 0 + row_start + 89, 100 + (40*i) + 40 + col_start, +89 + row_start), fill = 0)

            draw.line((101 + (40*i) + col_start, 0 + row_start, 101 + (40*i) + col_start, 90 + row_start), fill = 0)
            draw.line((102 + (40*i) + col_start, 0 + row_start, 102 + (40*i) + col_start, 90 + row_start), fill = 0)
            draw.line((103 + (40*i) + col_start, 0 + row_start, 103 + (40*i) + col_start, 90 + row_start), fill = 0)
        draw.line((100 + (40*i) + col_start, 0 + row_start, 100 + (40*i) + col_start, 90 + row_start), fill = 0)
    return Himage

def generate_standings(Himage, col_start=100, row_start=320):
    data = load_json_file('standings.json')

    ran_num = random.randint(1, 6)

    teams_in_division = data.get('standings').get(standings_dict.get(ran_num))

    font24 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 24)
    font18 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)
    font15 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 15)
    draw = ImageDraw.Draw(Himage)

    # draw lines
    # 'W', 'L', 'PCT', 'GB', 'HOME', 'AWAY', 'RS', 'RA', 'DIFF', 'STRK', 'L10'
    for item in range(6):
        padding = item * 30
        draw.line((col_start, padding + row_start, 580 +
                  col_start, padding + row_start), fill=0)

    verticle_lines = [160, 200, 240, 290, 340, 395, 440, 510, 580]

    # verticle lines
    for line in verticle_lines:
        draw.line((line + col_start, -20 + row_start,
                   line + col_start, 150 + row_start), fill=0)
    # draw text
    row_start += 5
    padding = -30
    draw.text((0 + col_start, padding + row_start),
              'Team', font=font18, fill=0)
    # wins
    draw.text((verticle_lines[0] + 8 + col_start, padding + row_start),
              'W', font=font18, fill=0)
    # losses
    draw.text((verticle_lines[1] + 8 + col_start, padding + row_start),
              'L', font=font18, fill=0)
    # percentage
    draw.text((verticle_lines[2] + 8 + col_start, padding + row_start),
              'PCT', font=font18, fill=0)
    # games back
    draw.text((verticle_lines[3] + 8 + col_start, padding + row_start),
              'GB', font=font18, fill=0)
    # streak
    draw.text((verticle_lines[4] + 8 + col_start, padding + row_start),
              'STRK', font=font18, fill=0)
    # last 10
    draw.text((verticle_lines[5] + 8 + col_start, padding + row_start),
              'L10', font=font18, fill=0)
    # home record
    draw.text((verticle_lines[6] + 8 + col_start, padding + row_start),
              'Home', font=font18, fill=0)
    # away record
    draw.text((verticle_lines[7] + 8 + col_start, padding + row_start),
              'Away', font=font18, fill=0)

    for item, team in enumerate(teams_in_division):
        print(item, team.get('team_name'))
        padding = item * 30
        draw.text((0 + col_start, padding + row_start),
                  team.get('team_name'), font=font15, fill=0)
        # wins
        draw.text((verticle_lines[0] + 8 + col_start, padding + row_start),
                  str(team.get('league_record_wins')), font=font18, fill=0)
        # losses
        draw.text((verticle_lines[1] + 8 + col_start, padding + row_start),
                  str(team.get('league_record_losses')), font=font18, fill=0)
    #     # percentage
        draw.text((verticle_lines[2] + 8 + col_start, padding + row_start),
                  str(team.get('league_record_percent')), font=font18, fill=0)
    #     # games back
        draw.text((verticle_lines[3] + 8 + col_start, padding + row_start),
                  str(team.get('games_back')), font=font18, fill=0)
    #     # streak
        draw.text((verticle_lines[4] + 8 + col_start, padding + row_start),
                  team.get('streak'), font=font18, fill=0)
    #     # last 10
        draw.text((verticle_lines[5] + 8 + col_start, padding + row_start),
                 f'{team.get("last_ten_wins")}-{team.get("last_ten_losses")}' , font=font18, fill=0)
    #     # home record
        draw.text((verticle_lines[6] + 8 + col_start, padding + row_start),
                  f'{team.get("home_wins")}-{team.get("home_losses")}', font=font18, fill=0)
    #     # away record
        draw.text((verticle_lines[7] + 8 + col_start, padding + row_start),
                  f'{team.get("away_wins")}-{team.get("away_losses")}', font=font18, fill=0)
    return Himage


# Live game states that qualify for a wide (2-cell) tile. Challenge/review states
# are still an active game, so they must keep the wide slot they already had.
_LIVE_WIDE_STATES = ('In Progress', 'Player challenge', 'Manager challenge')


def _find_wide_games(game_list, config, team_data):
    """Return the set of game_list indices to show as wide (2-cell) tiles.

    Each wide cell consumes one extra grid slot, and the 5×3 grid holds only
    15 slot units total. So at most ``15 - len(game_list)`` games can be widened
    without pushing a game off the grid — e.g. with 13 games only 2 may be wide.
    When more games are in progress than that budget allows, the games farthest
    along (by inning) are chosen.

    When wide_cell_always=true in config, always show exactly one wide cell —
    the in-progress game farthest into the game by inning — even with 15+ games
    (one game will be dropped from the grid to accommodate the extra slot).

    When wide_cell_featured=true, the wide cell always goes to the featured
    (primary) team's game when it is live; otherwise it falls back to the game
    farthest along. Like wide_cell_always, this shows a wide cell even with 15+
    games — but the choice prefers the featured team over raw game progress.

    Geometry fix-up (col=4 conflicts) is handled separately by _reorder_for_wide,
    which swaps in-progress games with adjacent normal games so they land at a
    valid column. This function selects purely by priority.

    A game under review ('Player challenge'/'Manager challenge') is still live —
    it is treated as in-progress so it keeps its wide tile instead of collapsing
    to a single cell and handing the slot to another game mid-review.
    """
    in_progress = [i for i, g in enumerate(game_list) if g.get('detailed_state') in _LIVE_WIDE_STATES]

    # Featured-team preference: index of the primary team's live game, if enabled.
    featured_idx = None
    if config.get('wide_cell_featured', False):
        primary = config.get('primary', '')
        if primary:
            abbr_map = team_data.get('team_abbreviation', {})
            for i in in_progress:
                g = game_list[i]
                away = abbr_map.get(str(g.get('away_team_id', '')), '')
                home = abbr_map.get(str(g.get('home_team_id', '')), '')
                if primary in (away, home):
                    featured_idx = i
                    break

    # Find the in-progress game farthest along:
    # 1. highest inning  2. Bottom > Top  3. most outs  4. earliest start time
    def _progress(idx):
        g = game_list[idx]
        inning = g.get('current_inning') or 0
        # Order within an inning: Top < Middle (break) < Bottom < End (break). This
        # keeps a game that just went to break ranked at/above where it was, so it
        # doesn't lose its wide slot to another game when the inning turns over.
        half  = {'Top': 0, 'Middle': 1, 'Bottom': 2, 'End': 3}.get(g.get('inningState'), 0)
        outs  = g.get('num_of_outs') or 0
        # Earlier start = higher priority when all else equal; negate so max() works
        start = g.get('game_datetime') or ''
        return (inning, half, outs, start)

    # Ranking used when a subset must be chosen: the featured live game outranks
    # everything else; ties beyond that fall back to game progress.
    def _rank(idx):
        return (1 if idx == featured_idx else 0,) + _progress(idx)

    if len(game_list) < 15:
        # Only widen as many games as there are spare slots (15 - games).
        max_wide = 15 - len(game_list)
        if len(in_progress) <= max_wide:
            return set(in_progress)
        return set(sorted(in_progress, key=_rank, reverse=True)[:max_wide])

    # 15+ games: show a single wide cell if either always-on or featured preference
    # is enabled. The pick prefers the featured live game (via _rank) and otherwise
    # falls back to the game farthest along.
    if not in_progress:
        return set()
    if config.get('wide_cell_always', False) or config.get('wide_cell_featured', False):
        return {max(in_progress, key=_rank)}
    return set()


def _reorder_for_wide(game_list, wide_set):
    """Reorder game_list so every game in wide_set can actually render wide.

    A wide cell must start at col 0-3 (can't span from col 4 into col 5).
    When a wide game lands at col 4, swap it with the normal game immediately
    after it; the wide game shifts to col 0 of the next row and can span right.
    If the next game is also wide (can't swap), drop the conflicting wide game.

    Returns (new_game_list, new_wide_set).
    """
    game_list = list(game_list)
    wide_set = set(wide_set)

    for _ in range(len(wide_set) + 1):  # converges in at most one pass per wide game
        slot = 0
        conflict = None
        for gi in range(len(game_list)):
            if slot >= 15:
                break
            col = slot % 5
            if gi in wide_set:
                if col >= 4:
                    conflict = gi
                    break
                slot += 2
            else:
                slot += 1

        if conflict is None:
            break

        b = conflict
        next_b = b + 1
        if next_b < len(game_list) and next_b not in wide_set:
            game_list[b], game_list[next_b] = game_list[next_b], game_list[b]
            wide_set.discard(b)
            wide_set.add(next_b)
        else:
            wide_set.discard(b)

    return game_list, wide_set


def compute_grid_layout(game_state_data, team_data, config):
    """Return (ordered_game_list, slots) for the 5×3 scoreboard grid.

    ``slots`` is a list parallel to the returned game_list, each entry a
    ``(slot_type, grid_col, grid_row)`` tuple where slot_type is 'wide' or
    'normal'. This is the single source of truth for grid geometry: both the
    renderer (draw_out_of_town_score_board) and the partial-refresh region
    calculation must use it so wide cells (which consume 2 slot units and may
    be reordered) line up exactly.
    """
    # Reorder games so the primary team's game appears first in the grid
    game_list = list(game_state_data)
    if config.get('favorite_team_first', False):
        primary = config.get('primary', '')
        if primary:
            abbr_map = team_data.get('team_abbreviation', {})
            for i, g in enumerate(game_list):
                away_abbr = abbr_map.get(str(g.get('away_team_id', '')), '')
                home_abbr = abbr_map.get(str(g.get('home_team_id', '')), '')
                if primary in (away_abbr, home_abbr):
                    game_list.insert(0, game_list.pop(i))
                    break

    # With 16+ games, a doubleheader, and a rainout, push postponed/cancelled games
    # off the 5×3 grid (to position 16+) so the doubleheader pair stays visible
    # instead. This applies even if the affected team is the featured team.
    _RAINOUT_STATES = {'Postponed', 'Cancelled', 'Cancelled: Rain'}
    _has_dh = any(g.get('double_header', 'N') not in ('N', '', None) for g in game_list)
    _ppd_games = [g for g in game_list if g.get('detailed_state', '') in _RAINOUT_STATES]
    if len(game_list) >= 16 and _has_dh and _ppd_games:
        for _ppd_g in _ppd_games:
            game_list.remove(_ppd_g)
            game_list.append(_ppd_g)

    # Determine which games show as wide (2-cell) tiles, then reorder so any
    # wide game that would land at col=4 swaps with the normal game after it.
    _wide_set = _find_wide_games(game_list, config, team_data)
    if _wide_set:
        game_list, _wide_set = _reorder_for_wide(game_list, _wide_set)

    # Build an ordered list of (slot_type, grid_col, grid_row).
    # Each wide game consumes 2 horizontal slot units; normal games consume 1.
    # Wide games on the last column (col 4) fall back to normal (can't span right).
    # Stop adding slots once the 5×3 grid is full (15 slot units).
    if _wide_set:
        _slots = []
        _slot_idx = 0
        for _gi in range(len(game_list)):
            if _slot_idx >= 15:
                break
            _row = _slot_idx // 5
            _col = _slot_idx % 5
            if _gi in _wide_set and _col < 4:
                _slots.append(('wide', _col, _row))
                _slot_idx += 2
            else:
                _slots.append(('normal', _col, _row))
                _slot_idx += 1
    else:
        _slots = [('normal', _gi % 5, _gi // 5) for _gi in range(len(game_list))]

    return game_list, _slots


def draw_out_of_town_score_board(Himage, game_state_data, team_data, date_str=None, changed_game_ids=None, use_logos=False, logo_x_offset=2, show_win_prob=False):

    draw = ImageDraw.Draw(Himage)
    config = load_yaml_file('config.yaml')

    # --- Date label: centered in the top strip, as large as possible, bold ---
    if date_str:
        from datetime import datetime as _dt
        try:
            _d = _dt.strptime(date_str, '%Y-%m-%d')
            _label_full  = _d.strftime('%B %-d, %Y')   # e.g. "February 28, 2026"
            _label_short = _d.strftime('%b %-d, %Y')   # e.g. "Feb 28, 2026"
        except (ValueError, AttributeError):
            _label_full = _label_short = date_str

        # When wildcard standings fill the header strip the center gap shrinks to ~159px.
        # Without wildcard standings there is ~560px of clear space.
        if config.get('show_wildcard_standings', False):
            _MAX_LABEL_W = 155
        else:
            _MAX_LABEL_W = 560

        _font_date = _get_font(14)
        _fsize = 14
        _label = _label_full
        for _candidate in (_label_full, _label_short):
            for _fsize in (24, 22, 20, 18, 16, 14):
                _font_date = _get_font(_fsize)
                if int(_font_date.getlength(_candidate)) <= _MAX_LABEL_W:
                    _label = _candidate
                    break
            else:
                continue  # this format didn't fit at any size; try shorter one
            break          # found a fitting size

        _lw = int(_font_date.getlength(_label))
        _lx = (800 - _lw) // 2
        _ly = max(0, (_WC_STRIP_H - _fsize) // 2)
        draw.text((_lx,     _ly), _label, font=_font_date, fill=0)
        draw.text((_lx + 1, _ly), _label, font=_font_date, fill=0)  # bold stroke

    x_start = 32
    y_start = 30

    game_list, _slots = compute_grid_layout(game_state_data, team_data, config)

    # Build per-team stats lookup {str(team_id): {'streak', 'l10_wins', 'l10_losses', 'wins', 'losses'}}
    _standings = load_json_file('standings.json')
    streak_map = {}
    for _div_teams in _standings.get('standings', {}).values():
        for _t in _div_teams:
            _tid = str(_t.get('team_id', ''))
            if _tid:
                streak_map[_tid] = {
                    'streak': _t.get('streak'),
                    'l10_wins': _t.get('last_ten_wins'),
                    'l10_losses': _t.get('last_ten_losses'),
                    'wins': _t.get('league_record_wins'),
                    'losses': _t.get('league_record_losses'),
                }

    for game, slot_info in zip(game_list, _slots):
        slot_type, gx, gy = slot_info
        game_pk_key = str(game.get('game_pk', ''))
        score_changed = changed_game_ids is not None and game_pk_key in changed_game_ids
        sx = gx * 150 + x_start
        sy = gy * 150 + y_start
        if slot_type == 'wide':
            Himage = draw_wide_box(
                Himage, sx, sy, game, team_data,
                score_changed=score_changed,
                use_logos=use_logos,
                logo_x_offset=logo_x_offset,
                show_win_prob=show_win_prob,
                streak_map=streak_map,
            )
        else:
            Himage = draw_box(
                Himage, sx, sy, game, team_data,
                score_changed=score_changed,
                use_logos=use_logos,
                logo_x_offset=logo_x_offset,
                show_win_prob=show_win_prob,
                streak_map=streak_map,
            )

    Himage.save('score_board.bmp')
    return Himage
