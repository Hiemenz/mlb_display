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
    """Full 800×480 canvas for a live (In Progress) featured game.

    Called from draw_featured_game_fullscreen when the featured game is
    actively In Progress (any sub-state: active pitch, between innings, or
    pitching change).  No standings sidebars — the game fills the entire
    display.

    Layout (top → bottom)
    ---------------------
    y=0..29    Header strip  : inning label | last play | matchup + date
    y=30..47   R / H / E column labels
    y=48..146  Away team row : logo  abbr  R  H  E
    y=147..245 Home team row : logo  abbr  R  H  E
    y=246      Divider line
    y=247..479 Situation (233 px):
        Active pitch    : bases diamond (left)  +  B/S/O circles (right)
                          pitcher / batter info at bottom
        Between innings : upcoming batters + pitcher (left)
                          outs + per-inning linescore (right)
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

    # ── Fonts ─────────────────────────────────────────────────────────────────
    f11 = _get_font(11)   # runner jersey numbers inside bases
    f14 = _get_font(14)   # header detail, column labels, pitch info
    f20 = _get_font(20)   # pitcher / batter lines
    f28 = _get_font(28)   # between-innings batter / pitcher names
    f36 = _get_font(36)   # errors column value
    f42 = _get_font(42)   # team abbreviations + B/S/O labels (= draw_box scale×3 font14)
    f48 = _get_font(48)   # hits column value
    f72 = _get_font(72)   # runs column value  (= draw_box scale×3 font24)

    # ── Team identifiers ──────────────────────────────────────────────────────
    abbr_map  = team_data.get('team_abbreviation', {})
    away_id   = str(game_data.get('away_team_id', ''))
    home_id   = str(game_data.get('home_team_id', ''))
    away_abbr = abbr_map.get(away_id, f'T{away_id}')
    home_abbr = abbr_map.get(home_id, f'T{home_id}')

    # ── Inning state ──────────────────────────────────────────────────────────
    _inn_state   = game_data.get('inningState') or ''
    _cur_inn     = game_data.get('current_inning') or 1
    _inn_ord_raw = game_data.get('currentInningOrdinal') or str(_cur_inn)
    _inn_ord     = _re_lf.sub(r'(?:st|nd|rd|th)$', '', _inn_ord_raw, flags=_re_lf.IGNORECASE)
    _lbl_map     = {'Top': '▲', 'Bottom': '▼', 'Middle': 'Mid', 'End': 'End'}
    _inn_lbl     = _lbl_map.get(_inn_state, (_inn_state[:3] if _inn_state else ''))
    inning_str   = f'{_inn_lbl} {_inn_ord}'.strip()

    _between_innings = _inn_state in ('Middle', 'End')
    _pitching_change = (game_data.get('sub_event') or '').startswith('PC:')

    # ── Layout constants ──────────────────────────────────────────────────────
    HEADER_H   = 30
    LABEL_H    = 18
    TEAM_ROW_H = 99           # tall enough for 84 px logo + 7 px margin each side
    AWAY_Y     = HEADER_H + LABEL_H          # y = 48
    HOME_Y     = AWAY_Y + TEAM_ROW_H         # y = 147
    DIV_Y      = HOME_Y + TEAM_ROW_H         # y = 246
    SIT_Y      = DIV_Y + 1                   # y = 247

    LOGO_SZ  = 84             # matches draw_box scale=3 logo size
    LOGO_X   = 14
    ABBR_X   = LOGO_X + LOGO_SZ + 6          # x = 104

    R_CX = 310                # x-centre of Runs column
    H_CX = 490                # x-centre of Hits column
    E_CX = 655                # x-centre of Errors column

    # Situation: bases diamond (left half of situation area)
    # 2nd-base top  = DIAMOND_CY - BASE_DIST - BASE_SZ = 360-55-28 = 277 > SIT_Y ✓
    # home-base bot = DIAMOND_CY + BASE_DIST + BASE_SZ = 360+55+28 = 443 < 480 ✓
    DIAMOND_CX = 170
    DIAMOND_CY = 360
    BASE_DIST  = 55
    BASE_SZ    = 28

    # Situation: B/S/O circles — 20 % larger than the normal 3× scale view
    # Normal 3× = r12 balls/strikes, r18 outs → +25 %/+17 % → r15/r21
    BSO_Y = DIAMOND_CY        # same vertical centre as diamond
    B_R   = 15
    O_R   = 21
    C_GAP = 6

    INFO_Y = 402              # y-start for pitcher / batter text

    # ── HEADER ────────────────────────────────────────────────────────────────
    draw.text((10, 5), inning_str, font=f20, fill=0)
    draw.text((11, 5), inning_str, font=f20, fill=0)   # pseudo-bold

    _gd_str = (game_data.get('game_date') or '')[:10]
    _date_lbl = ''
    if _gd_str:
        try:
            _gd_dt = datetime.strptime(_gd_str, '%Y-%m-%d')
            _date_lbl = _gd_dt.strftime('%b %-d')
        except Exception:
            _date_lbl = _gd_str
    _hdr_right = f'{away_abbr} @ {home_abbr}' + (f'  ·  {_date_lbl}' if _date_lbl else '')
    _hrw = int(f14.getlength(_hdr_right))
    draw.text((800 - _hrw - 8, 8), _hdr_right, font=f14, fill=0)

    # Last play / sub-event centred in header (active pitch only)
    if not _between_innings:
        _sub_ev_hdr = (game_data.get('sub_event') or '').strip()
        _lp_hdr     = game_data.get('last_play') or ''
        _play_raw   = _sub_ev_hdr or _lp_hdr
        if _play_raw:
            _pd = _abbr_play(_play_raw)
            _rbi = int(game_data.get('last_play_rbi') or 0)
            if _rbi > 0 and not _sub_ev_hdr:
                if _pd == 'HR':
                    if _rbi >= 2:
                        _pd = f'{_rbi}R HR'
                elif _rbi == 1:
                    _pd = f'RBI {_pd}'
                else:
                    _pd = f'{_rbi}RBI {_pd}'
            _inn_end_x  = 10 + int(f20.getlength(inning_str)) + 10
            _hdr_x_end  = 800 - _hrw - 16
            _pw         = int(f14.getlength(_pd))
            _avail      = _hdr_x_end - _inn_end_x - 4
            if _avail > 0 and _pw <= _avail:
                _ppx = _inn_end_x + (_avail - _pw) // 2
                draw.text((_ppx,     8), _pd, font=f14, fill=0)
                draw.text((_ppx + 1, 8), _pd, font=f14, fill=0)

    draw.line((0, HEADER_H - 1, 799, HEADER_H - 1), fill=0)

    # ── R / H / E COLUMN LABELS ───────────────────────────────────────────────
    for _lbl2, _cx2 in (('R', R_CX), ('H', H_CX), ('E', E_CX)):
        _lw2 = int(f14.getlength(_lbl2))
        draw.text((_cx2 - _lw2 // 2,     HEADER_H + 2), _lbl2, font=f14, fill=0)
        draw.text((_cx2 - _lw2 // 2 + 1, HEADER_H + 2), _lbl2, font=f14, fill=0)

    # ── SCORE DATA ────────────────────────────────────────────────────────────
    away_runs = str(game_data.get('away_runs') or 0)
    home_runs = str(game_data.get('home_runs') or 0)
    away_hits = str(game_data.get('away_hits') or 0)
    home_hits = str(game_data.get('home_hits') or 0)
    away_errs = str(game_data.get('away_errors') or 0)
    home_errs = str(game_data.get('home_errors') or 0)

    _away_ahead = (game_data.get('away_runs') or 0) > (game_data.get('home_runs') or 0)
    _home_ahead = (game_data.get('home_runs') or 0) > (game_data.get('away_runs') or 0)

    def _draw_team_row(abbr, tid, row_y, runs, hits, errs, bold_score=False, batting=False):
        nonlocal draw, canvas
        # Batting indicator: filled dot at far-left edge
        if batting:
            _bi_r  = 7
            _bi_cy = row_y + TEAM_ROW_H // 2
            draw.ellipse([5 - _bi_r, _bi_cy - _bi_r,
                          5 + _bi_r, _bi_cy + _bi_r], fill=0)
        # Logo (84 px square, vertically centred in 99 px row)
        if use_logos:
            _lg = _logo_small(abbr, tid, size=LOGO_SZ)
            if _lg:
                _lw3, _lh3 = _lg.size
                _paste_logo(canvas, _lg,
                            (LOGO_X + (LOGO_SZ - _lw3) // 2,
                             row_y  + (TEAM_ROW_H - _lh3) // 2))
                draw = ImageDraw.Draw(canvas)
        # Abbreviation (f42, vertically centred)
        _abbr_y = row_y + (TEAM_ROW_H - 42) // 2
        draw.text((ABBR_X,     _abbr_y), abbr, font=f42, fill=0)
        draw.text((ABBR_X + 1, _abbr_y), abbr, font=f42, fill=0)
        # Runs (f72, centred in R column)
        _rw3 = int(f72.getlength(runs))
        _rx  = R_CX - _rw3 // 2
        _ry  = row_y + (TEAM_ROW_H - 72) // 2
        draw.text((_rx,     _ry), runs, font=f72, fill=0)
        if bold_score:
            draw.text((_rx + 1, _ry), runs, font=f72, fill=0)
        # Hits (f48, centred in H column)
        _hw4 = int(f48.getlength(hits))
        draw.text((H_CX - _hw4 // 2, row_y + (TEAM_ROW_H - 48) // 2), hits, font=f48, fill=0)
        # Errors (f36, centred in E column)
        _ew3 = int(f36.getlength(errs))
        draw.text((E_CX - _ew3 // 2, row_y + (TEAM_ROW_H - 36) // 2), errs, font=f36, fill=0)

    _draw_team_row(away_abbr, away_id, AWAY_Y, away_runs, away_hits, away_errs,
                   bold_score=_away_ahead, batting=(_inn_state == 'Top'))
    _draw_team_row(home_abbr, home_id,  HOME_Y, home_runs, home_hits, home_errs,
                   bold_score=_home_ahead, batting=(_inn_state == 'Bottom'))

    draw.line((0, DIV_Y, 799, DIV_Y), fill=0)

    # ── SITUATION AREA ────────────────────────────────────────────────────────
    if _between_innings or _pitching_change:
        # ── Between innings / pitching change ─────────────────────────────────
        _batter_names = [
            _last_name(game_data.get('next_batter_1') or game_data.get('current_hitter') or ''),
            _last_name(game_data.get('next_batter_2') or game_data.get('due_up')         or ''),
            _last_name(game_data.get('next_batter_3') or game_data.get('in_hole')        or ''),
        ]
        _pc_raw = (game_data.get('sub_event') or '')[3:].strip() if _pitching_change else ''
        _pit_nm = _pc_raw or _last_name(
            game_data.get('next_pitcher') or game_data.get('current_pitcher') or ''
        )

        # Left side: next three batters + pitcher (f28)
        _ny = SIT_Y + 12
        for _nm in _batter_names:
            if _nm:
                draw.text((20, _ny), _nm, font=f28, fill=0)
            _ny += 34
        _sep_y = _ny + 6
        draw.line((20, _sep_y, 290, _sep_y), fill=0)
        if _pit_nm:
            draw.text((20, _sep_y + 8), _pit_nm, font=f28, fill=0)

        # Outs indicator (right side, above linescore)
        _outs  = game_data.get('num_of_outs') or 0
        _oc_cy = SIT_Y + 55          # ≈ y=302; circles span 281..323
        _o_lbl_y = _oc_cy - O_R - 10
        draw.text((392, _o_lbl_y), 'O', font=f28, fill=0)
        draw.text((393, _o_lbl_y), 'O', font=f28, fill=0)
        for i in range(3):
            _ocx = 414 + i * (2 * O_R + C_GAP) + O_R
            canvas = draw_circle(canvas, (_ocx, _oc_cy), O_R, i < _outs, outline_width=2)
        draw = ImageDraw.Draw(canvas)

        # Per-inning linescore (scale=2, right panel beginning at x=340)
        # grid top = _ls_sy + 83*2; target grid top ≈ SIT_Y + 100 = 347
        _ls_sy = SIT_Y + 100 - 83 * 2
        draw, canvas = _draw_linescore_grid(
            draw, canvas, 340, _ls_sy,
            game_data, team_data, use_logos, scale=2,
        )

    else:
        # ── Active pitch ──────────────────────────────────────────────────────

        # Bases diamond (centred at DIAMOND_CX=170, DIAMOND_CY=360)
        _hi_third  = isinstance(game_data.get('runner_on_third'),  str)
        _hi_second = isinstance(game_data.get('runner_on_second'), str)
        _hi_first  = isinstance(game_data.get('runner_on_first'),  str)

        _b3 = (DIAMOND_CX - BASE_DIST, DIAMOND_CY)
        _b2 = (DIAMOND_CX,             DIAMOND_CY - BASE_DIST)
        _b1 = (DIAMOND_CX + BASE_DIST, DIAMOND_CY)

        canvas = draw_diamond(canvas, _b3, BASE_SZ, _hi_third)
        canvas = draw_diamond(canvas, _b2, BASE_SZ, _hi_second)
        canvas = draw_diamond(canvas, _b1, BASE_SZ, _hi_first)
        draw   = ImageDraw.Draw(canvas)

        # Runner jersey numbers (white text inside filled base diamonds)
        for _bfill, _bc, _bkey in (
            (_hi_third,  _b3, 'runner_third_number'),
            (_hi_second, _b2, 'runner_second_number'),
            (_hi_first,  _b1, 'runner_first_number'),
        ):
            if _bfill:
                _raw  = game_data.get(_bkey)
                _bnum = str(_raw) if _raw is not None else ''
                if _bnum:
                    _bnw = int(f11.getlength(_bnum))
                    draw.text((_bc[0] - _bnw // 2, _bc[1] - 7), _bnum, font=f11, fill=255)

        # ── B / S / O circles ─────────────────────────────────────────────────
        # Horizontal layout, vertically centred at BSO_Y=360, starting at x=295.
        # B label(f42~28px) + gap8 + 4×(2×15+6) → right≈469
        # S label + gap8 + 2×(2×15+6) → right≈585
        # O label + gap8 + 3×(2×21+6) → right≈773  (fits within 800)
        _bx = 295

        # B label + 4 ball circles
        draw.text((_bx, BSO_Y - 21), 'B', font=f42, fill=0)
        draw.text((_bx + 1, BSO_Y - 21), 'B', font=f42, fill=0)
        _bx += int(f42.getlength('B')) + 8
        _balls = game_data.get('balls') or 0
        for i in range(4):
            _cx = _bx + B_R
            canvas = draw_circle(canvas, (_cx, BSO_Y), B_R, i < _balls)
            _bx += 2 * B_R + C_GAP
        draw = ImageDraw.Draw(canvas)

        # S label + 2 strike circles
        _sx = _bx + 14
        draw.text((_sx, BSO_Y - 21), 'S', font=f42, fill=0)
        draw.text((_sx + 1, BSO_Y - 21), 'S', font=f42, fill=0)
        _sx += int(f42.getlength('S')) + 8
        _strikes = game_data.get('strikes') or 0
        _scalls  = game_data.get('strike_calls', [])
        for i in range(2):
            _cx   = _sx + B_R
            _call = _scalls[i] if i < len(_scalls) else None
            if i < _strikes and _call in ('S', 'F'):
                # Swinging / foul: ring outline with solid centre dot
                canvas = draw_circle(canvas, (_cx, BSO_Y), B_R, False)
                draw   = ImageDraw.Draw(canvas)
                draw.ellipse([_cx - 5, BSO_Y - 5, _cx + 5, BSO_Y + 5],
                             fill='black', outline='black')
            else:
                canvas = draw_circle(canvas, (_cx, BSO_Y), B_R, i < _strikes)
                draw   = ImageDraw.Draw(canvas)
            _sx += 2 * B_R + C_GAP

        # O label + 3 out circles
        _ox = _sx + 14
        draw.text((_ox, BSO_Y - 21), 'O', font=f42, fill=0)
        draw.text((_ox + 1, BSO_Y - 21), 'O', font=f42, fill=0)
        _ox += int(f42.getlength('O')) + 8
        _outs2 = game_data.get('num_of_outs') or 0
        for i in range(3):
            _cx = _ox + O_R
            canvas = draw_circle(canvas, (_cx, BSO_Y), O_R, i < _outs2, outline_width=2)
            _ox += 2 * O_R + C_GAP
        draw = ImageDraw.Draw(canvas)

        # Pitch info (count · speed · type) — just below circles
        _lps = game_data.get('last_pitch_speed')
        _pt  = game_data.get('last_pitch_type', '')
        _pc  = game_data.get('pitch_count')
        _pitch_parts = []
        if _pc is not None:
            _pitch_parts.append(f'{_pc}P')
        if _lps:
            _pitch_parts.append(f'{int(_lps)}mph')
        if _pt:
            _pitch_parts.append(_pt)
        if _pitch_parts:
            draw.text((295, BSO_Y + O_R + 8), '  '.join(_pitch_parts), font=f14, fill=0)

        # Save situation indicator (above BSO row)
        if game_data.get('save_situation'):
            draw.text((295,     BSO_Y - O_R - 28), 'SV', font=f14, fill=0)
            draw.text((295 + 1, BSO_Y - O_R - 28), 'SV', font=f14, fill=0)

        # ── Pitcher / batter info ─────────────────────────────────────────────
        _pitcher = _format_player_name(game_data.get('current_pitcher') or '')
        if _pitcher:
            draw.text((12, INFO_Y), f'P: {_pitcher}', font=f20, fill=0)

        _bh      = game_data.get('batter_hits')
        _ba      = game_data.get('batter_at_bats')
        _ba_str2 = f'({_bh}-{_ba})' if _bh is not None and _ba is not None else ''
        _ab_done = game_data.get('current_at_bat_complete', False)
        if _ab_done and not _is_game_effectively_over(game_data):
            _batter  = _format_player_name(
                game_data.get('due_up') or game_data.get('next_batter_1') or ''
            )
            _bat_lbl = 'Next'
        else:
            _batter  = _format_player_name(game_data.get('current_hitter') or '')
            _bat_lbl = 'AB'
        if _batter:
            _bat_str2 = f'{_bat_lbl}: {_batter}  {_ba_str2}'.strip()
            draw.text((12, INFO_Y + 26), _bat_str2, font=f20, fill=0)

        # Last play — right-aligned beside pitcher/batter lines
        _sub_ev2 = (game_data.get('sub_event') or '').strip()
        _lp_val  = game_data.get('last_play') or ''
        _play_f  = _sub_ev2 or _lp_val
        if _play_f:
            _pd2  = _abbr_play(_play_f) if not _sub_ev2 else _play_f
            _rbi2 = int(game_data.get('last_play_rbi') or 0)
            if _rbi2 > 0 and not _sub_ev2:
                if _pd2 == 'HR':
                    if _rbi2 >= 2:
                        _pd2 = f'{_rbi2}R HR'
                elif _rbi2 == 1:
                    _pd2 = f'RBI {_pd2}'
                else:
                    _pd2 = f'{_rbi2}RBI {_pd2}'
            _pdw = int(f20.getlength(_pd2))
            draw.text((799 - _pdw - 10, INFO_Y), _pd2, font=f20, fill=0)
            draw.text((800 - _pdw - 10, INFO_Y), _pd2, font=f20, fill=0)

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


