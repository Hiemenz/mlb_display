import os
import json
import random
import time as _time_mod
from datetime import datetime
import pytz
from util import load_json_file, load_yaml_file, save_off_results
from collections import OrderedDict

from image_assets import (
    picdir, _get_font, _logo_small, _load_logo_gray, _logo_ghost, _paste_logo,
    Image, ImageDraw, ImageFont, ImageOps,
)
from image_utils import (
    normalize_dict, standings_dict,
    draw_diamond, draw_circle, check_if_two_chars,
    _last_name, _pitcher_line, _clean_venue_name, _is_game_effectively_over,
    _format_player_name,
)
from image_standings import (
    _WC_STRIP_H,
    derive_wildcard_from_standings, draw_wildcard_header, draw_standings_sidebar,
    draw_standings_sidebar_fullscreen,
)
from image_box import draw_box, _abbr_play, _draw_linescore_grid

# ---------------------------------------------------------------------------
# logging.basicConfig(level=logging.DEBUG)
# ---------------------------------------------------------------------------


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

    # result_event = 'temp'
    # weather_condition =  'temp'
    # weather_temp = 'temp'
    # weather_wind = 'temp'


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

_LINESCORE_SHOW_SECONDS = 60 * 60  # show linescore for 60 min after last play


def _game_in_window(team_abbr, games_scheduled):
    """Return True if the team's game is live or ended less than 60 minutes ago."""
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
        return (datetime.now(pytz.utc) - end_utc).total_seconds() < _LINESCORE_SHOW_SECONDS
    except Exception:
        return False


def draw_boards():

    new_image_dict = {}
    config_data = load_yaml_file('config.yaml')
    linescore_data = load_json_file('linescore.json')
    games_scheduled = load_json_file('games_scheduled.json')
    # epd = epd7in5_V2.EPD()
    Himage = Image.new('1', (800, 480), 255)  # 255: clear the frame
    col_start = 100
    row_start = 40

    team_abbr = None
    for _candidate in [config_data.get('primary'), config_data.get('primary_backup'), config_data.get('primary_backup_2')]:
        if linescore_data.get(_candidate) and _game_in_window(_candidate, games_scheduled):
            team_abbr = _candidate
            break

    if team_abbr:
        Himage, new_image_dict = generate_linescore(col_start, row_start, team_abbr, Himage, new_image_dict)

    team_abbr = None
    for _candidate in [config_data.get('secondary'), config_data.get('secondary_backup'), config_data.get('secondary_backup_2')]:
        if linescore_data.get(_candidate) and _game_in_window(_candidate, games_scheduled):
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

    # bmp = Image.open(os.path.join('/home/pi/Documents/e-Paper/RaspberryPi_JetsonNano/python/examples/', 'qr.jpg'))
    # Himage.paste(bmp, (0,0))
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

    for i in range(13):
        # inning
        sub_header, sub_away, sub_home = 0,0,0
        if i < 12:


            if 1 < len(str(inning_header[i])):
                sub_header = -7
            if 1 < len(str(away[i])):
                sub_away = -7
            if 1 < len(str(home[i])):
                sub_home = -7

            if away[i] == None:
                away[i] = ''

            if home[i] == None:
                home[i] = ''

            draw.text((115 + sub_header + (40*i) + col_start, 0 + row_start), str(inning_header[i]), font = font24, fill = 0)
            draw.text((115 + sub_away + (40*i) + col_start, 30 + row_start), str(away[i]), font = font24, fill = 0)
            draw.text((115 + sub_home + (40*i) + col_start, 60 + row_start), str(home[i]), font = font24, fill = 0)

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


    # standings_list = [[name] + value for name, value in zip(standing_teams_name, standing_teams_values)]
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

    # Build per-team stats lookup {str(team_id): {'streak': ..., 'l10_wins': ..., 'l10_losses': ...}}
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
                }

    counter = 0
    for y in range(0,3):
        for x in range(0,5):
            if counter > len(game_list) - 1:
                continue
            if game_list[counter]:
                game_pk_key = str(game_list[counter].get('game_pk', ''))
                score_changed = changed_game_ids is not None and game_pk_key in changed_game_ids
                Himage = draw_box(Himage, x * 150 + x_start, y * 150 + y_start, game_list[counter], team_data, score_changed=score_changed, use_logos=use_logos, logo_x_offset=logo_x_offset, show_win_prob=show_win_prob, streak_map=streak_map)
            counter += 1

    Himage.save('score_board.bmp')
    return Himage

def compare_json_dicts_sorted(dict1, dict2):
    """Compare two JSON dictionaries to see if they are equal, ignoring key order."""
    return json.dumps(dict1, sort_keys=True) == json.dumps(dict2, sort_keys=True)


def load_and_sort_json(json_string):
    """Load JSON data from a string and sort it."""
    return json.loads(json_string, object_pairs_hook=OrderedDict)



def  orchestrate_score_board(game_state_data, team_data, date_str=None, bypass_cache=False, config=None):
    """Returns (image, changed_regions) or None if nothing changed.

    changed_regions is a list of (x, y, w, h) tuples for partial refresh.
    An empty list signals that a full refresh should be used.

    bypass_cache=True skips the unchanged-image check and state persistence.
    Use this when generating GIFs or rendering historical snapshots.
    """
    if config is None:
        config = load_yaml_file('config.yaml')
    use_logos = config.get('use_team_logos', False)
    logo_x_offset = config.get('small_logo_x_offset', 2)
    show_win_prob = config.get('scoreboard_win_probability', False)

    if bypass_cache:
        new_dict = old_dict = None  # skip comparison below
    else:
        old_data = load_json_file('old_scoreboard_state.json')

        new_data_str = json.dumps(game_state_data)
        old_data_str = json.dumps(old_data)

        new_dict = load_and_sort_json(new_data_str)
        old_dict = load_and_sort_json(old_data_str)

        save_off_results(game_state_data, "old_scoreboard_state")

    # Build map of old game data by game_pk for per-game comparison
    old_by_pk = {}
    if not bypass_cache:
        if old_data and isinstance(old_data, list):
            for g in old_data:
                pk = str(g.get('game_pk', ''))
                if pk:
                    old_by_pk[pk] = g

    # Track all games with ANY data change (for partial refresh regions)
    refreshed_game_ids = set()
    for game in game_state_data:
        pk = str(game.get('game_pk', ''))
        if not pk:
            continue
        if old_by_pk.get(pk) != game:
            refreshed_game_ids.add(pk)

    changed_game_ids = set()
    if not bypass_cache:
        # --- Score change detection ---
        old_scores = load_json_file('score_alerts.json')
        new_scores = {}
        for game in game_state_data:
            pk = str(game.get('game_pk', ''))
            if not pk:
                continue
            away_runs = game.get('away_runs')
            home_runs = game.get('home_runs')
            new_scores[pk] = {'away_runs': away_runs, 'home_runs': home_runs}
            if pk in old_scores:
                old_entry = old_scores[pk]
                if away_runs != old_entry.get('away_runs') or home_runs != old_entry.get('home_runs'):
                    changed_game_ids.add(pk)
                    print(f'Score change detected for game {pk}: {old_entry} -> {new_scores[pk]}')
        save_off_results(new_scores, 'score_alerts')
        # --- End score change detection ---

        # Detect when a Final game's linescore window transitions True→False.
        # The visual content (linescore grid vs WP/LP) changes at the 60-min boundary
        # without any change to game_state_data, so the data comparison above won't
        # catch it. We track the window state separately and force a re-render when
        # any game exits the window.
        _final_state_set = {'Final', 'Game Over', 'Final: Tied'}
        _final_times = load_json_file('game_final_times.json') or {}
        _old_win_state = load_json_file('old_linescore_window_state.json') or {}
        _new_win_state = {}
        _linescore_window_changed = False
        _final_linescore_secs = config.get('final_linescore_minutes', 60) * 60
        for _g in game_state_data:
            if _g.get('detailed_state') in _final_state_set:
                _pk = str(_g.get('game_pk', ''))
                if not _pk:
                    continue
                _ft = _final_times.get(_pk)
                if _ft is None:
                    continue
                _end_utc = _g.get('game_end_time_utc')
                if _end_utc:
                    try:
                        _end_dt = pytz.utc.localize(datetime.strptime(_end_utc[:19], "%Y-%m-%dT%H:%M:%S"))
                        _in_win = (datetime.now(pytz.utc) - _end_dt).total_seconds() < _final_linescore_secs
                    except Exception:
                        _in_win = (_time_mod.time() - float(_ft)) < _final_linescore_secs
                else:
                    _in_win = (_time_mod.time() - float(_ft)) < _final_linescore_secs
                _new_win_state[_pk] = _in_win
                if _old_win_state.get(_pk) is True and not _in_win:
                    _linescore_window_changed = True
                    refreshed_game_ids.add(_pk)
                    print(f'Linescore window expired for game {_pk} — forcing re-render')
        save_off_results(_new_win_state, 'old_linescore_window_state')

        if compare_json_dicts_sorted(new_dict, old_dict) and not _linescore_window_changed:
            print('images the same')
            return None

        # In fullscreen mode the display shows only one game, so skip re-render
        # if that specific game's data hasn't changed, even if other games did.
        if os.environ.get('FEATURED_TEAM_FULLSCREEN', '').lower() in ('true', '1', 'yes'):
            primary = config.get('primary', '')
            featured_game = _find_featured_game(game_state_data, team_data, primary)
            if featured_game:
                featured_pk = str(featured_game.get('game_pk', ''))
                old_featured = old_by_pk.get(featured_pk)
                if old_featured is not None and featured_game == old_featured:
                    _feat_linescore_changed = (
                        _old_win_state.get(featured_pk) is True
                        and not _new_win_state.get(featured_pk, False)
                    )
                    if not _feat_linescore_changed:
                        print('images the same (fullscreen — featured game unchanged)')
                        return None

    print('image is different')

    league_mode = config.get('league_mode', 'mlb')

    # --- Featured team full-screen mode ---
    if os.environ.get('FEATURED_TEAM_FULLSCREEN', '').lower() in ('true', '1', 'yes'):
        primary = config.get('primary', '')
        featured_game = _find_featured_game(game_state_data, team_data, primary)
        if featured_game:
            Himage = draw_featured_game_fullscreen(featured_game, team_data, config)
        else:
            Himage = Image.new('1', (800, 480), 255)
            Himage = draw_out_of_town_score_board(Himage, game_state_data, team_data, date_str, changed_game_ids=changed_game_ids, use_logos=use_logos, logo_x_offset=logo_x_offset, show_win_prob=show_win_prob)

        if config.get('dark_mode', False):
            Himage = ImageOps.invert(Himage.convert('L')).convert('1')
        return (Himage, [])   # always full refresh for fullscreen

    # --- Normal scoreboard grid ---
    Himage = Image.new('1', (800, 480), 255)
    Himage = draw_out_of_town_score_board(Himage, game_state_data, team_data, date_str, changed_game_ids=changed_game_ids, use_logos=use_logos, logo_x_offset=logo_x_offset, show_win_prob=show_win_prob)

    standings_data = None
    if config.get('show_wildcard_standings', False) or config.get('show_standings_sidebar', False):
        standings_data = load_json_file('standings.json')

    if config.get('show_wildcard_standings', False) and league_mode != 'aaa':
        if standings_data and 'standings' in standings_data:
            wildcard_data = derive_wildcard_from_standings(standings_data)
            Himage = draw_wildcard_header(Himage, wildcard_data)

    if config.get('show_standings_sidebar', False):
        if standings_data and 'standings' in standings_data:
            Himage = draw_standings_sidebar(Himage, standings_data, team_data, side='left', league_mode=league_mode)
            Himage = draw_standings_sidebar(Himage, standings_data, team_data, side='right', league_mode=league_mode)

    if config.get('dark_mode', False):
        Himage = ImageOps.invert(Himage.convert('L')).convert('1')

    # --- Compute changed regions from changed_game_ids ---
    # Must use the same game ordering that draw_out_of_town_score_board used,
    # otherwise the favorite-team-first reorder causes grid positions to mismatch.
    x_start = 32
    y_start = 30
    _ordered = list(game_state_data)
    if config.get('favorite_team_first', False):
        _primary = config.get('primary', '')
        if _primary:
            _abbr_map = team_data.get('team_abbreviation', {})
            for _i, _g in enumerate(_ordered):
                _away = _abbr_map.get(str(_g.get('away_team_id', '')), '')
                _home = _abbr_map.get(str(_g.get('home_team_id', '')), '')
                if _primary in (_away, _home):
                    _ordered.insert(0, _ordered.pop(_i))
                    break
    changed_regions = []
    for i, game in enumerate(_ordered):
        if i >= 15:  # 5x3 grid max
            break
        pk = str(game.get('game_pk', ''))
        if pk in refreshed_game_ids:
            col = i % 5
            row = i // 5
            # Align x to 8-pixel boundary
            rx = (col * 150 + x_start) // 8 * 8
            ry = row * 150 + y_start
            rw = 152  # slightly wider to cover alignment rounding (divisible by 8)
            rh = 150
            changed_regions.append((rx, ry, rw, rh))

    # If too many regions changed, signal full refresh with empty list
    if len(changed_regions) > 5:
        changed_regions = []

    return (Himage, changed_regions)


# ---------------------------------------------------------------------------
# Featured team full-screen rendering
# ---------------------------------------------------------------------------

def _find_featured_game(game_state_data, team_data, primary_abbr):
    """Return the best game to display for primary_abbr in fullscreen mode.

    Priority: first Scheduled/Pre-Game/Warmup → first In Progress → last Final.
    Falls back to the first game in the list if the primary team has no game.
    """
    abbr_map = team_data.get('team_abbreviation', {})
    primary_games = []
    for game in game_state_data:
        away = abbr_map.get(str(game.get('away_team_id', '')), '')
        home = abbr_map.get(str(game.get('home_team_id', '')), '')
        if primary_abbr in (away, home):
            primary_games.append(game)

    if not primary_games:
        return game_state_data[0] if game_state_data else None

    _scheduled = {'Scheduled', 'Pre-Game', 'Warmup', 'Delayed Start'}
    _final     = {'Final', 'Game Over', 'Final: Tied'}

    for g in primary_games:
        if g.get('detailed_state') in _scheduled:
            return g
    for g in primary_games:
        if g.get('detailed_state') == 'In Progress':
            return g
    for g in reversed(primary_games):
        if g.get('detailed_state', '').startswith('Completed Early') or g.get('detailed_state') in _final:
            return g
    return primary_games[-1]


def draw_live_fullscreen_game(game_data, team_data, config=None):
    """Full 800x480 canvas for a live (In Progress) featured game.

    Layout v4
    ---------
    y=0..91    Header  : inning (f80, left)  matchup (f56, right)  [thick line below]
    y=92..111  R / H / E column labels (f14)
    y=112..191 Away row : logo  abbr  R  H  E  |  bases diamond (right, spans rows)
    y=192..271 Home row : logo  abbr  R  H  E  |
    y=272..307 [blank left]  |  outs circles (right, under bases)
    y=308      Divider line
    y=309..479 Bottom :
        Live           : B/S/O circles + pitch info + last event (f36) + pitcher/batter (f28)
        Between-innings: last event (f36) + due-up batters (f24) + pitcher (f24)
    """
    import re as _re_lf

    if config is None:
        config = load_yaml_file('config.yaml')

    use_logos = config.get('use_team_logos', False)

    # Normalise mid-game review/challenge states
    if game_data.get('detailed_state') in ('Player challenge', 'Manager challenge'):
        game_data = dict(game_data)
        game_data['sub_event'] = (
            'ABS CHAL' if game_data['detailed_state'] == 'Player challenge' else 'M CHAL'
        )
        game_data['detailed_state'] = 'In Progress'

    canvas = Image.new('1', (800, 480), 255)
    draw   = ImageDraw.Draw(canvas)

    # ---- Fonts ---------------------------------------------------------------
    f14  = _get_font(14)    # ABS / challenge labels
    f22  = _get_font(22)    # runner jersey numbers inside bases (doubled)
    f24  = _get_font(24)    # pitch info / between-innings names
    f28  = _get_font(28)    # misc
    f36  = _get_font(36)    # misc
    f42  = _get_font(42)    # BSO labels + pitcher/batter + team abbreviations
    f56  = _get_font(56)    # matchup header fallback
    f72  = _get_font(72)    # R / H / E values
    f80  = _get_font(80)    # inning text + last event in header

    # ---- Team identifiers ----------------------------------------------------
    abbr_map  = team_data.get('team_abbreviation', {})
    away_id   = str(game_data.get('away_team_id', ''))
    home_id   = str(game_data.get('home_team_id', ''))
    away_abbr = abbr_map.get(away_id, f'T{away_id}')
    home_abbr = abbr_map.get(home_id, f'T{home_id}')

    # ---- Inning state --------------------------------------------------------
    _inn_state   = game_data.get('inningState') or ''
    _cur_inn     = game_data.get('current_inning') or 1
    _inn_ord_raw = game_data.get('currentInningOrdinal') or str(_cur_inn)
    _inn_ord     = _re_lf.sub(r'(?:st|nd|rd|th)$', '', _inn_ord_raw, flags=_re_lf.IGNORECASE)
    _lbl_map     = {'Top': '▲', 'Bottom': '▼', 'Middle': 'Mid', 'End': 'End'}
    _inn_lbl     = _lbl_map.get(_inn_state, (_inn_state[:3] if _inn_state else ''))
    inning_str   = f'{_inn_lbl} {_inn_ord}'.strip()

    _between_innings = _inn_state in ('Middle', 'End')
    _pitching_change = (game_data.get('sub_event') or '').startswith('PC:')

    # ---- Layout constants ----------------------------------------------------
    HEADER_H   = 69           # 25% smaller than original 92 → freed pixels go to bottom bar
    LABEL_H    = 20           # space between header and first team row
    TEAM_ROW_H = 80           # away/home score rows
    AWAY_Y     = HEADER_H + LABEL_H          # 89
    HOME_Y     = AWAY_Y  + TEAM_ROW_H        # 169
    OUTS_Y_TOP = HOME_Y  + TEAM_ROW_H - 21  # 228 → 8px below bases bottom (224)
    OUTS_H     = 48                          # circles bottom at 272, +4px gap = div at 276
    DIV_Y      = OUTS_Y_TOP + OUTS_H         # 276
    SIT_Y      = DIV_Y + 1                   # 277
    WIN_PCT_H  = 54                          # 3× win % bar
    WIN_PCT_Y  = 480 - WIN_PCT_H             # 426

    # Team row layout
    LOGO_SZ  = 72
    LOGO_X   = 2
    ABBR_X   = LOGO_X + LOGO_SZ + 6         # 80

    # R/H/E column centres
    R_CX = 240
    H_CX = 360
    E_CX = 480

    # Bases: right side — doubled size, repositioned to fit
    DIAMOND_CX = 645
    DIAMOND_CY = 178                         # shifted up more
    BASE_DIST  = 58                          # closer together
    BASE_SZ    = 46                          # ~2x the original 24
    BASE_OW    = 4

    # BSO circles (bottom half)
    B_R   = 16                               # 30% bigger than original 12
    O_R   = 20                               # bigger outs circles
    C_GAP = 5

    # ---- Last-event helper (built early for header use) ----------------------
    _FLD_POS = [
        ('center fielder', '8'), ('right fielder', '9'), ('left fielder', '7'),
        ('first baseman', '3'), ('second baseman', '4'), ('third baseman', '5'),
        ('shortstop', '6'), ('catcher', '2'), ('pitcher', '1'),
    ]

    def _build_last_event():
        _sub_ev = (game_data.get('sub_event') or '').strip()
        _lp     = game_data.get('last_play') or ''
        _raw    = _sub_ev or _lp
        if not _raw:
            return ''
        _pd  = _abbr_play(_raw)
        # Resolve flyout/lineout to F7/L6 etc. using the play description
        if _pd in ('FO', 'LO', 'PO'):
            _prefix = _pd[0]
            _desc   = (game_data.get('last_play_description') or '').lower()
            for _kw, _code in _FLD_POS:
                if _kw in _desc:
                    _pd = f'{_prefix}{_code}'
                    break
        _rbi = int(game_data.get('last_play_rbi') or 0)
        if _rbi > 0 and not _sub_ev:
            if _pd == 'HR':
                if _rbi >= 2:
                    _pd = f'{_rbi}R HR'
            elif _rbi == 1:
                _pd = f'RBI {_pd}'
            else:
                _pd = f'{_rbi}RBI {_pd}'
        return _pd

    _last_ev = _build_last_event()

    # ---- HEADER (69px — full-width thick line below) ------------------------
    # Inning: f56 fits in 69px header. Triangle 80% of numeral height.
    _inn_x = 8
    _inn_y = 4
    _inn_font = f56
    if _inn_lbl in ('▲', '▼'):
        _nbbox   = _inn_font.getbbox(_inn_ord)
        _n_top   = _inn_y + _nbbox[1]
        _n_bot   = _inn_y + _nbbox[3]
        _n_h     = _n_bot - _n_top
        _tri_h   = int(_n_h * 0.80)
        _tri_mid = (_n_top + _n_bot) // 2
        _tri_top = _tri_mid - _tri_h // 2
        _tri_bot = _tri_top + _tri_h
        _t_cx    = _inn_x + _tri_h // 2
        _t_rgt   = _inn_x + _tri_h
        if _inn_lbl == '▲':
            draw.polygon([(_t_cx, _tri_top), (_inn_x, _tri_bot), (_t_rgt, _tri_bot)], fill=0)
        else:
            draw.polygon([(_inn_x, _tri_top), (_t_rgt, _tri_top), (_t_cx, _tri_bot)], fill=0)
        _num_x = _t_rgt + 8
        draw.text((_num_x,     _inn_y), _inn_ord, font=_inn_font, fill=0)
        draw.text((_num_x + 1, _inn_y), _inn_ord, font=_inn_font, fill=0)
        _inn_right_edge = _num_x + int(_inn_font.getlength(_inn_ord))
    else:
        draw.text((_inn_x,     _inn_y), inning_str, font=_inn_font, fill=0)
        draw.text((_inn_x + 1, _inn_y), inning_str, font=_inn_font, fill=0)
        _inn_right_edge = _inn_x + int(_inn_font.getlength(inning_str))

    # Right side of header: last event (f56) right-aligned; fall back to matchup (f36)
    _inn_min_right = _inn_right_edge + 16
    if _last_ev:
        _hdr_right_txt  = _last_ev
        _hdr_right_font = f56
    else:
        _hdr_right_txt  = f'{away_abbr} @ {home_abbr}'
        _hdr_right_font = f36
    _hrw   = int(_hdr_right_font.getlength(_hdr_right_txt))
    _hdr_x = 800 - _hrw - 8
    if _hdr_x > _inn_min_right:
        _hry = max(4, (HEADER_H - _hdr_right_font.size) // 2)
        draw.text((_hdr_x,     _hry), _hdr_right_txt, font=_hdr_right_font, fill=0)
        draw.text((_hdr_x + 1, _hry), _hdr_right_txt, font=_hdr_right_font, fill=0)

    draw.line((0, HEADER_H - 1, 799, HEADER_H - 1), fill=0, width=5)

    # ---- SCORE DATA ---------------------------------------------------------
    away_runs = str(game_data.get('away_runs') or 0)
    home_runs = str(game_data.get('home_runs') or 0)
    away_hits = str(game_data.get('away_hits') or 0)
    home_hits = str(game_data.get('home_hits') or 0)
    away_errs = str(game_data.get('away_errors') or 0)
    home_errs = str(game_data.get('home_errors') or 0)

    _away_ahead = (game_data.get('away_runs') or 0) > (game_data.get('home_runs') or 0)
    _home_ahead = (game_data.get('home_runs') or 0) > (game_data.get('away_runs') or 0)

    def _draw_team_row(abbr, tid, row_y, runs, hits, errs, bold_score=False,
                       batting=False, abs_remaining=None, replay_remaining=None):
        nonlocal draw, canvas
        if use_logos:
            _lg = _logo_small(abbr, tid, size=LOGO_SZ)
            if _lg:
                _lw3, _lh3 = _lg.size
                _paste_logo(canvas, _lg,
                            (LOGO_X + (LOGO_SZ - _lw3) // 2,
                             row_y  + (TEAM_ROW_H - _lh3) // 2))
                draw = ImageDraw.Draw(canvas)
        _abbr_y = row_y + (TEAM_ROW_H - 42) // 2
        draw.text((ABBR_X,     _abbr_y), abbr, font=f42, fill=0)
        draw.text((ABBR_X + 1, _abbr_y), abbr, font=f42, fill=0)

        # ABS challenges — rectangles above abbreviation, starting at ABBR_X
        # filled = challenge available, empty outline = challenge used
        if abs_remaining is not None:
            _abs_max = game_data.get('abs_challenge_max') or 2
            _rw, _rh = 36, 10
            _r_gap   = 4
            _r_top   = _abbr_y - _rh + 5   # moved down 4px more
            _r_left  = ABBR_X
            if _r_top >= row_y:
                for i in range(_abs_max):
                    _rx0, _ry0 = _r_left, _r_top
                    _rx1, _ry1 = _rx0 + _rw, _ry0 + _rh
                    if i < abs_remaining:   # filled = available
                        draw.rectangle([_rx0, _ry0, _rx1, _ry1], fill=0)
                    else:                   # outline only = used
                        draw.rectangle([_rx0, _ry0, _rx1, _ry1], outline=0, width=2)
                    _r_left += _rw + _r_gap

        # Manager replay challenge — rectangle below abbreviation, starting at ABBR_X
        # filled = challenge available, empty outline = used
        if replay_remaining is not None:
            _rw, _rh = 36, 10
            _r_top   = _abbr_y + 42 + 3
            _r_left  = ABBR_X
            if _r_top + _rh <= row_y + TEAM_ROW_H:
                if replay_remaining > 0:    # filled = has challenge
                    draw.rectangle([_r_left, _r_top, _r_left + _rw, _r_top + _rh], fill=0)
                else:                       # outline = used
                    draw.rectangle([_r_left, _r_top, _r_left + _rw, _r_top + _rh], outline=0, width=2)

        _ry = row_y + (TEAM_ROW_H - 72) // 2
        for val, cx, bold in ((runs, R_CX, bold_score), (hits, H_CX, False), (errs, E_CX, False)):
            _vw = int(f72.getlength(val))
            _vx = cx - _vw // 2
            draw.text((_vx,     _ry), val, font=f72, fill=0)
            if bold:
                draw.text((_vx + 1, _ry), val, font=f72, fill=0)

    _away_abs = game_data.get('away_challenges_remaining')
    _home_abs = game_data.get('home_challenges_remaining')
    _away_rep = game_data.get('away_replay_remaining')
    _home_rep = game_data.get('home_replay_remaining')

    _draw_team_row(away_abbr, away_id, AWAY_Y, away_runs, away_hits, away_errs,
                   bold_score=_away_ahead, batting=(_inn_state == 'Top'),
                   abs_remaining=_away_abs, replay_remaining=_away_rep)
    _draw_team_row(home_abbr, home_id,  HOME_Y, home_runs, home_hits, home_errs,
                   bold_score=_home_ahead, batting=(_inn_state == 'Bottom'),
                   abs_remaining=_home_abs, replay_remaining=_home_rep)

    # ---- SAVE SITUATION badge (upper-right, just below header line) ---------
    if game_data.get('save_situation'):
        _sv_w = int(f28.getlength('SV'))
        _sv_x = 800 - _sv_w - 8
        _sv_y = HEADER_H + 3
        draw.text((_sv_x,     _sv_y), 'SV', font=f28, fill=0)
        draw.text((_sv_x + 1, _sv_y), 'SV', font=f28, fill=0)

    # ---- BASES (right side, spanning both score rows) -----------------------
    _hi_third  = isinstance(game_data.get('runner_on_third'),  str)
    _hi_second = isinstance(game_data.get('runner_on_second'), str)
    _hi_first  = isinstance(game_data.get('runner_on_first'),  str)

    _b3 = (DIAMOND_CX - BASE_DIST, DIAMOND_CY)
    _b2 = (DIAMOND_CX,             DIAMOND_CY - BASE_DIST)
    _b1 = (DIAMOND_CX + BASE_DIST, DIAMOND_CY)
    # home plate removed

    canvas = draw_diamond(canvas, _b3, BASE_SZ, _hi_third,  outline_width=BASE_OW)
    canvas = draw_diamond(canvas, _b2, BASE_SZ, _hi_second, outline_width=BASE_OW)
    canvas = draw_diamond(canvas, _b1, BASE_SZ, _hi_first,  outline_width=BASE_OW)
    draw   = ImageDraw.Draw(canvas)

    # Runner jersey numbers in white inside filled bases (f22 = doubled from f11)
    for _bfill, _bc, _bkey in (
        (_hi_third,  _b3, 'runner_third_number'),
        (_hi_second, _b2, 'runner_second_number'),
        (_hi_first,  _b1, 'runner_first_number'),
    ):
        if _bfill:
            _raw  = game_data.get(_bkey)
            _bnum = str(_raw) if _raw is not None else ''
            if _bnum:
                _bnw = int(f22.getlength(_bnum))
                draw.text((_bc[0] - _bnw // 2, _bc[1] - 11), _bnum, font=f22, fill=255)

    # ---- OUTS circles (right side, moved up, bigger) ------------------------
    _outs = game_data.get('num_of_outs') or 0
    _ogap = 8
    _otw  = 3 * (2 * O_R) + 2 * _ogap
    _oxs  = DIAMOND_CX - _otw // 2
    _ocy  = OUTS_Y_TOP + O_R + 4
    for i in range(3):
        _ocx = _oxs + O_R + i * (2 * O_R + _ogap)
        canvas = draw_circle(canvas, (_ocx, _ocy), O_R, i < _outs, outline_width=2)
    draw = ImageDraw.Draw(canvas)

    # ---- DIVIDER (full width, thick) ----------------------------------------
    draw.line((0, DIV_Y, 799, DIV_Y), fill=0, width=2)

    # ---- BOTTOM SITUATION AREA ----------------------------------------------
    if _between_innings or _pitching_change:
        # ---- Between innings: due-up batters (big, left) + pitcher (right-aligned) ----
        _by = SIT_Y + 8

        _batter_names = [nm for nm in [
            _last_name(game_data.get('next_batter_1') or game_data.get('current_hitter') or ''),
            _last_name(game_data.get('next_batter_2') or game_data.get('due_up')         or ''),
            _last_name(game_data.get('next_batter_3') or game_data.get('in_hole')        or ''),
        ] if nm]
        _pc_raw = (game_data.get('sub_event') or '')[3:].strip() if _pitching_change else ''
        _pit_nm = _pc_raw or _last_name(
            game_data.get('next_pitcher') or game_data.get('current_pitcher') or ''
        )

        # Batters: stack vertically, bounded by WIN_PCT_Y
        _bot = WIN_PCT_Y - 4
        _avail_h = _bot - _by
        _n = len(_batter_names) or 1
        _bat_spacing = min(48, _avail_h // _n)
        for _nm in _batter_names:
            if _by + 42 <= _bot:
                draw.text((16, _by),     _nm, font=f42, fill=0)
                draw.text((17, _by),     _nm, font=f42, fill=0)
                _by += _bat_spacing

        # Pitcher: right-aligned, vertically centred in the bottom section
        if _pit_nm:
            _pit_w = int(f42.getlength(_pit_nm))
            _pit_x = 800 - _pit_w - 16
            _pit_y = (SIT_Y + 8 + _bot) // 2 - 21
            draw.text((_pit_x, _pit_y),     _pit_nm, font=f42, fill=0)
            draw.text((_pit_x + 1, _pit_y), _pit_nm, font=f42, fill=0)

    else:
        # ---- Active pitch: B/S (no O)  +  pitch info  +  pitcher/batter ----

        _bso_y  = SIT_Y + 6    # top of BSO label text
        # Circle centres: vertically centred on the cap-height of the 'B' glyph
        _b_bbox = f42.getbbox('B')
        _bso_cy = _bso_y + (_b_bbox[1] + _b_bbox[3]) // 2

        # Balls (3 circles)
        _bx = 16
        draw.text((_bx,     _bso_y), 'B', font=f42, fill=0)
        draw.text((_bx + 1, _bso_y), 'B', font=f42, fill=0)
        _bx += int(f42.getlength('B')) + 8
        _balls = game_data.get('balls') or 0
        for i in range(3):
            _cx = _bx + B_R
            canvas = draw_circle(canvas, (_cx, _bso_cy), B_R, i < _balls)
            _bx += 2 * B_R + C_GAP
        draw = ImageDraw.Draw(canvas)

        # Strikes
        _sx = _bx + 16
        draw.text((_sx,     _bso_y), 'S', font=f42, fill=0)
        draw.text((_sx + 1, _bso_y), 'S', font=f42, fill=0)
        _sx += int(f42.getlength('S')) + 8
        _strikes = game_data.get('strikes') or 0
        _scalls  = game_data.get('strike_calls', [])
        for i in range(2):
            _cx   = _sx + B_R
            _call = _scalls[i] if i < len(_scalls) else None
            if i < _strikes and _call in ('S', 'F'):
                canvas = draw_circle(canvas, (_cx, _bso_cy), B_R, False)
                draw   = ImageDraw.Draw(canvas)
                draw.ellipse([_cx - 5, _bso_cy - 5, _cx + 5, _bso_cy + 5],
                             fill='black', outline='black')
            else:
                canvas = draw_circle(canvas, (_cx, _bso_cy), B_R, i < _strikes)
                draw   = ImageDraw.Draw(canvas)
            _sx += 2 * B_R + C_GAP

        # Pitch info: f36, right-aligned, same row as B/S
        _lps = game_data.get('last_pitch_speed')
        _pt  = game_data.get('last_pitch_type', '')
        _pc  = game_data.get('pitch_count')
        _pitch_parts = []
        if _pc  is not None: _pitch_parts.append(f'{_pc}P')
        if _lps:             _pitch_parts.append(f'{int(_lps)}mph')
        if _pt:              _pitch_parts.append(_pt)
        # SV shown in top half of display, not here
        if _pitch_parts:
            _ptxt = '  '.join(_pitch_parts)
            _ptw  = int(f36.getlength(_ptxt))
            _pt_bbox = f36.getbbox(_ptxt)
            _pty = _bso_cy - (_pt_bbox[1] + _pt_bbox[3]) // 2
            draw.text((800 - _ptw - 8, _pty), _ptxt, font=f36, fill=0)

        # Pitcher (left) + Batter (x=400) on one line
        _pb_y = _bso_y + 48
        _pitcher_full = (game_data.get('current_pitcher') or '').strip()
        if _pitcher_full and _pb_y + 42 <= WIN_PCT_Y:
            draw.text((16, _pb_y),     f'P: {_pitcher_full}', font=f42, fill=0)
            draw.text((17, _pb_y),     f'P: {_pitcher_full}', font=f42, fill=0)

        # Batter — due_up when at-bat complete, else current_hitter
        _ab_done = game_data.get('current_at_bat_complete', False)
        if _ab_done and not _is_game_effectively_over(game_data):
            _batter_full = (game_data.get('due_up') or game_data.get('next_batter_1') or '').strip()
            _od_full     = (game_data.get('in_hole') or '').strip()
        else:
            _batter_full = (game_data.get('current_hitter') or '').strip()
            _od_full     = (game_data.get('due_up') or '').strip()
        # Safety: on-deck must never be the same person as at-bat
        if _od_full == _batter_full:
            _od_full = ''
        # Label column: right-align "AB:" and "OD:" so colons line up,
        # then names start at the same x
        _ab_lbl_w = int(f42.getlength('AB:'))
        _od_lbl_w = int(f42.getlength('OD:'))
        _lbl_col  = max(_ab_lbl_w, _od_lbl_w)
        _name_x   = 400 + _lbl_col + 8

        if _batter_full and _pb_y + 42 <= WIN_PCT_Y:
            _ax = 400 + (_lbl_col - _ab_lbl_w)
            draw.text((_ax,      _pb_y), 'AB:', font=f42, fill=0)
            draw.text((_ax+1,    _pb_y), 'AB:', font=f42, fill=0)
            draw.text((_name_x,  _pb_y), _batter_full, font=f42, fill=0)
            draw.text((_name_x+1,_pb_y), _batter_full, font=f42, fill=0)

        # On-deck hitter below AB batter — same font, labels right-aligned
        _od_y = _pb_y + 46
        if _od_full and _od_y + 42 <= WIN_PCT_Y - 2:
            _ox = 400 + (_lbl_col - _od_lbl_w)
            draw.text((_ox,      _od_y), 'OD:', font=f42, fill=0)
            draw.text((_ox+1,    _od_y), 'OD:', font=f42, fill=0)
            draw.text((_name_x,  _od_y), _od_full, font=f42, fill=0)
            draw.text((_name_x+1,_od_y), _od_full, font=f42, fill=0)

    # ---- SEPARATOR LINE above win % bar -------------------------------------
    draw.line((0, WIN_PCT_Y - 1, 799, WIN_PCT_Y - 1), fill=0, width=2)

    # ---- WIN PERCENTAGE BAR (3× height — full-width with LOSS/WIN watermarks + logos) --
    _away_wp = game_data.get('away_win_probability')
    _home_wp = game_data.get('home_win_probability')
    if _away_wp is not None and _home_wp is not None:
        try:
            _awp = float(_away_wp)
            _hwp = float(_home_wp)
            if _awp + _hwp > 1.5:          # already percentage (0-100)
                _awp /= 100.0
                _hwp /= 100.0

            BAR_W = 800
            BAR_H = WIN_PCT_H              # 54px
            LOGO_SZ = BAR_H - 4            # 50px logos

            # Ghost strip: "LOSS" left, "WIN" right, semi-transparent
            _ghost = Image.new('L', (BAR_W, BAR_H), 255)
            _gd    = ImageDraw.Draw(_ghost)
            _wf    = f36
            _gd.text((6, (BAR_H - 36) // 2),                        'LOSS', font=_wf, fill=0)
            _win_w = int(_wf.getlength('WIN'))
            _gd.text((BAR_W - _win_w - 6, (BAR_H - 36) // 2),       'WIN',  font=_wf, fill=0)
            _ghost = _ghost.point(lambda p: 255 if p > 180 else min(255, int(p * 0.35 + 155)))
            _gd.line((0, BAR_H // 2, BAR_W, BAR_H // 2), fill=0)
            canvas.paste(_ghost.convert('1'), (0, WIN_PCT_Y))
            draw = ImageDraw.Draw(canvas)

            # Logo positions along the bar
            _away_px   = int(BAR_W * _awp)
            _home_px   = int(BAR_W * _hwp)
            _away_lx   = max(0, min(BAR_W - LOGO_SZ, _away_px - LOGO_SZ // 2))
            _home_lx   = max(0, min(BAR_W - LOGO_SZ, _home_px - LOGO_SZ // 2))
            MIN_SEP    = LOGO_SZ + 2
            if _away_lx > _home_lx:
                if _away_lx - _home_lx < MIN_SEP:
                    _mid = (_away_lx + _home_lx) // 2
                    _away_lx = min(BAR_W - LOGO_SZ, _mid + MIN_SEP // 2)
                    _home_lx = max(0, _mid - MIN_SEP // 2)
            else:
                if _home_lx - _away_lx < MIN_SEP:
                    _mid = (_away_lx + _home_lx) // 2
                    _home_lx = min(BAR_W - LOGO_SZ, _mid + MIN_SEP // 2)
                    _away_lx = max(0, _mid - MIN_SEP // 2)

            if use_logos:
                _awl = _logo_small(away_abbr, away_id, size=LOGO_SZ)
                _hwl = _logo_small(home_abbr, home_id, size=LOGO_SZ)
                if _awl:
                    _paste_logo(canvas, _awl, (_away_lx, WIN_PCT_Y + (BAR_H - _awl.size[1]) // 2))
                if _hwl:
                    _paste_logo(canvas, _hwl, (_home_lx, WIN_PCT_Y + (BAR_H - _hwl.size[1]) // 2))
                draw = ImageDraw.Draw(canvas)
            else:
                # No logos: draw vertical markers + percentage text
                draw.line((_away_px, WIN_PCT_Y, _away_px, WIN_PCT_Y + BAR_H), fill=0, width=2)
                draw.line((_home_px, WIN_PCT_Y, _home_px, WIN_PCT_Y + BAR_H), fill=0, width=2)
                _astr = f'{_awp:.0%}'
                _hstr = f'{_hwp:.0%}'
                draw.text((_away_px + 4, WIN_PCT_Y + (BAR_H - 14) // 2), _astr, font=f14, fill=0)
                _hsw = int(f14.getlength(_hstr))
                draw.text((_home_px - _hsw - 4, WIN_PCT_Y + (BAR_H - 14) // 2), _hstr, font=f14, fill=0)
        except (ValueError, TypeError):
            pass

    return canvas


def draw_featured_game_fullscreen(game_data, team_data, config=None):
    """Enlarge a single scoreboard cell while preserving its 1:1 aspect ratio.

    The cell is scaled to fill the content area (inside the standings chrome)
    uniformly, then the wildcard header and standings sidebars are drawn on top
    exactly as they appear in the normal scoreboard view.
    """
    if config is None:
        config = load_yaml_file('config.yaml')

    _ds = game_data.get('detailed_state', '')
    _is_live = _ds in ('In Progress', 'Player challenge', 'Manager challenge')

    # Live game: custom full-screen layout (no sidebars, R/H/E + bases)
    if _is_live:
        _live_canvas = draw_live_fullscreen_game(game_data, team_data, config)
        if config.get('dark_mode', False):
            _live_canvas = ImageOps.invert(_live_canvas.convert('L')).convert('1')
        return _live_canvas

    use_logos   = config.get('use_team_logos', False)
    logo_offset = config.get('small_logo_x_offset', 2)
    win_prob    = config.get('scoreboard_win_probability', False)
    league_mode = config.get('league_mode', 'mlb')

    # Scale game cell to fill the content height at integer scale (3×).
    # Center the 405px box content (135*3) horizontally so the 45px dead zone in the
    # cell image is split ~22px on each side, giving equal-width sidebars.
    CELL   = 150
    AREA_H = 480 - _WC_STRIP_H       # 450 px
    SCALED = (AREA_H // CELL) * CELL  # 450 px at scale 3
    _scale = SCALED // CELL           # 3
    _box_w = 135 * _scale             # 405 px — where draw_box's horizontal line ends
    paste_x = (800 - _box_w) // 2    # 197 — centers box content in the display
    paste_y = _WC_STRIP_H            # 30

    # Build streak_map from standings so L10/streak show in pre-game boxes
    standings_data = load_json_file('standings.json')
    _streak_map = {}
    if standings_data:
        for _div_teams in standings_data.get('standings', {}).values():
            for _t in _div_teams:
                _tid = str(_t.get('team_id', ''))
                if _tid:
                    _streak_map[_tid] = {
                        'streak': _t.get('streak'),
                        'l10_wins': _t.get('last_ten_wins'),
                        'l10_losses': _t.get('last_ten_losses'),
                    }

    # Render at full target resolution — no upscaling needed, fonts/logos are native size
    cell = Image.new('L', (SCALED, SCALED), 255)
    cell = draw_box(cell, 0, 0, game_data, team_data,
                    use_logos=use_logos, logo_x_offset=logo_offset,
                    show_win_prob=win_prob, show_winner_logo=False,
                    streak_map=_streak_map, scale=_scale)
    scaled_cell = cell.point(lambda p: 0 if p < 128 else 255).convert('1')

    # Overlay winner ghost rendered natively at SCALED px — no upscaling artifacts.
    # lightness=215 → ~15% dot density: recognisable watermark that doesn't obscure text.
    if use_logos and game_data.get('detailed_state') in ('Final', 'Game Over', 'Final: Tied'):
        abbr_map = team_data.get('team_abbreviation', {})
        winner_abbr = winner_id = None
        if game_data.get('away_team_is_winner'):
            winner_abbr = abbr_map.get(str(game_data.get('away_team_id', '')))
            winner_id   = str(game_data.get('away_team_id', ''))
        elif game_data.get('home_team_is_winner'):
            winner_abbr = abbr_map.get(str(game_data.get('home_team_id', '')))
            winner_id   = str(game_data.get('home_team_id', ''))
        if winner_abbr and winner_id:
            sf = float(_scale)
            GHOST_SZ = round(110 * sf)
            ghost = _logo_ghost(winner_abbr, winner_id, size=GHOST_SZ, lightness=215)
            if ghost:
                gw, gh = ghost.size
                gx = (round(135 * sf) - gw) // 2
                gy = round(20 * sf) + (round(110 * sf) - gh) // 2
                _paste_logo(scaled_cell, ghost, (gx, gy))

    canvas = Image.new('1', (800, 480), 255)
    canvas.paste(scaled_cell, (paste_x, paste_y))

    # Sidebars: left = x=0..paste_x-1, right = x=(paste_x+_box_w)..799
    # Both widths are ~197-198px so logos are the same size on each side.
    _left_sb_w  = paste_x             # 197
    _right_sb_x = paste_x + _box_w   # 602
    _right_sb_w = 800 - _right_sb_x  # 198
    _sb_logo_sz = 52

    # Overlay wildcard header and standings sidebars (skipped for live games)
    if not _is_live and standings_data and 'standings' in standings_data:
        if config.get('show_wildcard_standings', False) and league_mode != 'aaa':
            wildcard_data = derive_wildcard_from_standings(standings_data)
            canvas = draw_wildcard_header(canvas, wildcard_data)
        if config.get('show_standings_sidebar', False):
            canvas = draw_standings_sidebar_fullscreen(
                canvas, standings_data, team_data, side='left', league_mode=league_mode,
                x_anchor=0, sidebar_w=_left_sb_w, logo_sz=_sb_logo_sz)
            canvas = draw_standings_sidebar_fullscreen(
                canvas, standings_data, team_data, side='right', league_mode=league_mode,
                x_anchor=_right_sb_x, sidebar_w=_right_sb_w, logo_sz=_sb_logo_sz)

    # Date label centered in the top strip — use the largest font that fits
    _gd_str = (game_data.get('game_date') or '')[:10]
    if _gd_str:
        try:
            _gd = datetime.strptime(_gd_str, '%Y-%m-%d')
            _date_label_full  = _gd.strftime('%A, %B %-d, %Y')   # Monday, May 11, 2026
            _date_label_short = _gd.strftime('%a · %b %-d, %Y')  # Mon · May 11, 2026
        except Exception:
            _date_label_full = _date_label_short = _gd_str
        _date_draw = ImageDraw.Draw(canvas)
        # When wildcard standings are shown they fill the strip leaving only ~155px
        # clear in the center (same constraint as the normal scoreboard header).
        # Without wildcard the full strip is free so the content-area width applies.
        _show_wc = config.get('show_wildcard_standings', False)
        _MAX_DATE_W = 151 if _show_wc else (_box_w - 8)
        _center_x = 400  # midpoint of the 800px display (matches _WC_MID = 399)
        _date_font = _get_font(14)
        _date_label = _date_label_short
        _fsize_used = 14
        for _fsize in (20, 18, 16, 14):
            _f = _get_font(_fsize)
            for _candidate in (_date_label_full, _date_label_short):
                if int(_f.getlength(_candidate)) <= _MAX_DATE_W:
                    _date_font = _f
                    _date_label = _candidate
                    _fsize_used = _fsize
                    break
            else:
                continue
            break
        _dw = int(_date_font.getlength(_date_label))
        _dx = _center_x - _dw // 2
        _dy = max(0, (_WC_STRIP_H - _fsize_used) // 2)
        _date_draw.text((_dx,     _dy), _date_label, font=_date_font, fill=0)
        _date_draw.text((_dx + 1, _dy), _date_label, font=_date_font, fill=0)

    return canvas


