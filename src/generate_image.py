import os
import json
import random
import time as _time_mod
from datetime import datetime
import pytz
from util import load_json_file, load_yaml_file, save_off_results
from collections import OrderedDict

from image_assets import (
    picdir, _get_font, _logo_small, _load_logo_gray, _paste_logo,
    Image, ImageDraw, ImageFont, ImageOps,
)
from image_utils import (
    normalize_dict, standings_dict,
    draw_diamond, draw_circle, check_if_two_chars,
    _format_player_name, _last_name, _pitcher_line, _clean_venue_name, _is_game_effectively_over,
)
from image_standings import (
    _WC_STRIP_H,
    derive_wildcard_from_standings, draw_wildcard_header, draw_standings_sidebar,
)
from image_box import draw_box

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

    print('image is different')

    league_mode = config.get('league_mode', 'mlb')

    # --- Featured team full-screen mode ---
    if config.get('featured_team_fullscreen', False):
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


def _draw_fullscreen_linescore(draw, Himage, start_y, game_data, team_data, font_hdr, font_val):
    """Render a full-width inning-by-inning grid.  Returns the Y coord of the grid bottom."""
    W = 800
    MARGIN = 12
    TEAM_COL_W = 52
    HEADER_H = 22
    ROW_H = 28

    away_inn = game_data.get('away_inning_runs') or []
    home_inn = game_data.get('home_inning_runs') or []
    current  = game_data.get('current_inning') or max(len(away_inn), 9)
    N = max(9, current)

    MAX_INN = 12
    if N > MAX_INN:
        first_inn = N - MAX_INN + 1
        n_cols = MAX_INN
    else:
        first_inn = 1
        n_cols = N

    total_data_cols = n_cols + 3           # innings + R + H + E
    avail_w = W - 2 * MARGIN - TEAM_COL_W
    col_w = avail_w // total_data_cols
    x0 = MARGIN + TEAM_COL_W

    abbr_map = team_data.get('team_abbreviation', {})
    away_id  = str(game_data.get('away_team_id', ''))
    home_id  = str(game_data.get('home_team_id', ''))
    away_abbr = abbr_map.get(away_id, '???')
    home_abbr = abbr_map.get(home_id, '???')

    # Header row — inning numbers + RHE labels
    for i in range(n_cols):
        label = str(first_inn + i)
        lw = int(font_hdr.getlength(label))
        cx = x0 + i * col_w + col_w // 2
        draw.text((cx - lw // 2, start_y), label, font=font_hdr, fill=0)
    for j, lbl in enumerate(('R', 'H', 'E')):
        lw = int(font_hdr.getlength(lbl))
        cx = x0 + n_cols * col_w + j * col_w + col_w // 2
        draw.text((cx - lw // 2, start_y), lbl, font=font_hdr, fill=0)

    sep_y = start_y + HEADER_H
    draw.line((MARGIN, sep_y, W - MARGIN, sep_y), fill=0)

    rows = [
        (away_abbr, away_inn, game_data.get('away_runs') or 0,
         game_data.get('away_hits') or 0, game_data.get('away_errors') or 0),
        (home_abbr, home_inn, game_data.get('home_runs') or 0,
         game_data.get('home_hits') or 0, game_data.get('home_errors') or 0),
    ]
    for row_idx, (abbr, inn_runs, runs, hits, errors) in enumerate(rows):
        ry = sep_y + 2 + row_idx * ROW_H
        text_y = ry + (ROW_H - 18) // 2

        # Team abbreviation right-aligned in team column
        aw = int(font_val.getlength(abbr))
        draw.text((MARGIN + TEAM_COL_W - aw - 4, text_y), abbr, font=font_val, fill=0)

        # Per-inning cells
        for i in range(n_cols):
            idx = first_inn + i - 1
            if idx < len(inn_runs):
                cell = 'X' if inn_runs[idx] is None else str(inn_runs[idx])
            else:
                cell = '-'
            cw_val = int(font_val.getlength(cell))
            cx = x0 + i * col_w + col_w // 2
            draw.text((cx - cw_val // 2, text_y), cell, font=font_val, fill=0)

        # R H E
        for j, val in enumerate((str(runs), str(hits), str(errors))):
            vw = int(font_val.getlength(val))
            cx = x0 + n_cols * col_w + j * col_w + col_w // 2
            draw.text((cx - vw // 2, text_y), val, font=font_val, fill=0)

    bottom_y = sep_y + 2 + 2 * ROW_H
    draw.line((MARGIN, bottom_y, W - MARGIN, bottom_y), fill=0)
    return bottom_y


def draw_featured_game_fullscreen(game_data, team_data, config=None):
    """Render a single game at full 800×480 resolution for the featured team display."""
    if config is None:
        config = load_yaml_file('config.yaml')

    W, H = 800, 480
    Himage = Image.new('1', (W, H), 255)
    draw = ImageDraw.Draw(Himage)
    use_logos = config.get('use_team_logos', False)

    # Normalize states (mirrors draw_box)
    if game_data.get('detailed_state', '').startswith('Completed Early'):
        game_data = dict(game_data)
        game_data['detailed_state'] = 'Final'
    if game_data.get('detailed_state') == 'Delayed Start':
        game_data = dict(game_data)
        game_data['detailed_state'] = 'Pre-Game'
    if game_data.get('detailed_state') == 'In Progress':
        _has_play = (
            (game_data.get('balls') or 0) > 0
            or (game_data.get('strikes') or 0) > 0
            or (game_data.get('num_of_outs') or 0) > 0
            or (game_data.get('away_runs') or 0) > 0
            or (game_data.get('home_runs') or 0) > 0
            or game_data.get('inningState') in ('Middle', 'End')
            or (game_data.get('current_inning') or 1) > 1
            or game_data.get('runner_on_first')
            or game_data.get('runner_on_second')
            or game_data.get('runner_on_third')
            or game_data.get('last_play')
        )
        if not _has_play:
            game_data = dict(game_data)
            game_data['detailed_state'] = 'Pre-Game'

    state = game_data.get('detailed_state', '')
    abbr_map = team_data.get('team_abbreviation', {})
    away_id   = str(game_data.get('away_team_id', ''))
    home_id   = str(game_data.get('home_team_id', ''))
    away_abbr = abbr_map.get(away_id, '???')
    home_abbr = abbr_map.get(home_id, '???')
    away_runs = game_data.get('away_runs') or 0
    home_runs = game_data.get('home_runs') or 0

    _FINAL_STATES = {'Final', 'Game Over', 'Final: Tied'}
    _PRE_STATES   = {'Scheduled', 'Pre-Game', 'Warmup'}
    _ORDINALS     = {1:'1st',2:'2nd',3:'3rd',4:'4th',5:'5th',
                     6:'6th',7:'7th',8:'8th',9:'9th',10:'10th',11:'11th',12:'12th'}

    font72 = _get_font(72)
    font42 = _get_font(42)
    font30 = _get_font(30)
    font22 = _get_font(22)
    font18 = _get_font(18)
    LOGO_SIZE = 90

    # ── Status header (Y=0..54) ──────────────────────────────────────────────
    if state in _FINAL_STATES:
        status = 'FINAL (TIE)' if state == 'Final: Tied' else 'FINAL'
    elif state == 'In Progress':
        inning = game_data.get('current_inning') or 1
        inn_label = _ORDINALS.get(inning, f'{inning}th')
        status = f"{game_data.get('inningState', 'Top')} {inn_label}"
    elif state in _PRE_STATES:
        status = state
    elif state == 'Postponed':
        reason = game_data.get('postpone_reason') or ''
        status = f'PPD: {reason}' if reason else 'POSTPONED'
    else:
        status = state

    sw = int(font30.getlength(status))
    draw.text(((W - sw) // 2,     12), status, font=font30, fill=0)
    draw.text(((W - sw) // 2 + 1, 12), status, font=font30, fill=0)
    draw.line((0, 54, W, 54), fill=0)

    # ── Teams + scores (Y=60..229) ───────────────────────────────────────────
    ZONE_MID = 145   # vertical centre of this zone

    def _place_logo(abbr, team_id, cx, side):
        """Paste a logo at cx, clipped to screen edge. side='left' or 'right'."""
        logo = _logo_small(abbr, team_id, size=LOGO_SIZE)
        if not logo:
            return
        lx = (cx - LOGO_SIZE - 8) if side == 'left' else (cx + 8)
        lx = max(0, min(W - LOGO_SIZE, lx))
        ly = ZONE_MID - LOGO_SIZE // 2
        _paste_logo(Himage, logo, (lx, ly))

    if state in _FINAL_STATES or state == 'In Progress':
        a_str = str(away_runs)
        h_str = str(home_runs)
        dash   = '-'
        asw = int(font72.getlength(a_str))
        hsw = int(font72.getlength(h_str))
        dw  = int(font42.getlength(dash))

        total_score_w = asw + 30 + dw + 30 + hsw
        score_x = (W - total_score_w) // 2
        score_y = ZONE_MID - 36        # 72-px font: half-height = 36

        draw.text((score_x,                         score_y), a_str, font=font72, fill=0)
        draw.text((score_x + asw + 30,              score_y + 16), dash, font=font42, fill=0)
        draw.text((score_x + asw + 30 + dw + 30,   score_y), h_str, font=font72, fill=0)

        # Away team left of score block
        aaw = int(font42.getlength(away_abbr))
        ax  = score_x - aaw - 50
        draw.text((ax, ZONE_MID - 21), away_abbr, font=font42, fill=0)
        if use_logos:
            _place_logo(away_abbr, away_id, ax, 'left')

        # Home team right of score block
        hx = score_x + asw + 30 + dw + 30 + hsw + 50
        draw.text((hx, ZONE_MID - 21), home_abbr, font=font42, fill=0)
        if use_logos:
            haw = int(font42.getlength(home_abbr))
            _place_logo(home_abbr, home_id, hx + haw, 'right')

    else:
        # Scheduled / Pre-Game / Postponed: "AWAY @ HOME"
        matchup = f'{away_abbr}  @  {home_abbr}'
        mw = int(font42.getlength(matchup))
        mx = (W - mw) // 2
        draw.text((mx, ZONE_MID - 21), matchup, font=font42, fill=0)
        if use_logos:
            _place_logo(away_abbr, away_id, mx, 'left')
            _place_logo(home_abbr, home_id, mx + mw, 'right')

    draw.line((0, 233, W, 233), fill=0)

    # ── Details zone (Y=238..479) ────────────────────────────────────────────
    DETAIL_TOP = 240

    if state in _FINAL_STATES:
        ls_bottom = _draw_fullscreen_linescore(
            draw, Himage, DETAIL_TOP, game_data, team_data, font18, font18)

        # WP / LP / SV — one per column, centred
        winner  = game_data.get('winner_name') or ''
        loser   = game_data.get('loser_name') or ''
        saver   = game_data.get('saver_name') or ''
        wp_rec  = game_data.get('winner_record') or ''
        lp_rec  = game_data.get('loser_record') or ''
        sv_saves = game_data.get('saver_saves')
        is_walkoff = bool(game_data.get('walk_off'))

        lines = []
        if winner:
            s = f'WP: {_format_player_name(winner)}'
            if wp_rec: s += f' ({wp_rec})'
            lines.append(s)
        if loser:
            s = f'LP: {_format_player_name(loser)}'
            if lp_rec: s += f' ({lp_rec})'
            lines.append(s)
        if saver:
            s = f'SV: {_format_player_name(saver)}'
            if sv_saves is not None: s += f' (S{sv_saves})'
            lines.append(s)
        if is_walkoff and lines:
            lines.insert(0, 'Walk-off')

        if lines:
            pit_y = ls_bottom + 10
            gap = (W - 20) // max(len(lines), 1)
            for i, line in enumerate(lines):
                lw = int(font22.getlength(line))
                px = 10 + i * gap + (gap - lw) // 2
                draw.text((px, pit_y), line, font=font22, fill=0)

    elif state == 'In Progress':
        ls_bottom = _draw_fullscreen_linescore(
            draw, Himage, DETAIL_TOP, game_data, team_data, font18, font18)

        count_y = ls_bottom + 10
        balls   = game_data.get('balls') or 0
        strikes = game_data.get('strikes') or 0
        outs    = game_data.get('num_of_outs') or 0
        count_str = f'B:{balls}  S:{strikes}  O:{outs}'
        cw = int(font22.getlength(count_str))
        draw.text(((W - cw) // 2, count_y), count_str, font=font22, fill=0)

        last_play = game_data.get('last_play') or ''
        if last_play:
            lp_str = f'Last: {last_play}'
            lpw = int(font22.getlength(lp_str))
            if lpw > W - 20:
                lp_str = last_play
                lpw = int(font22.getlength(lp_str))
            draw.text(((W - lpw) // 2, count_y + 30), lp_str, font=font22, fill=0)

    elif state in _PRE_STATES:
        away_pitcher_name, away_pitcher_stat = _pitcher_line(
            game_data.get('away_probable'), game_data.get('away_probable_note'))
        home_pitcher_name, home_pitcher_stat = _pitcher_line(
            game_data.get('home_probable'), game_data.get('home_probable_note'))

        def _draw_fs_pitcher(y, team, name, stat):
            MARGIN_L = 12
            MARGIN_R = W - 12
            label = f'{team}:'
            lw = int(font22.getlength(label))
            draw.text((MARGIN_L,     y), label, font=font22, fill=0)
            draw.text((MARGIN_L + 1, y), label, font=font22, fill=0)
            name_x = MARGIN_L + lw + 10
            stat_w = int(font18.getlength(stat)) if stat else 0
            stat_x = MARGIN_R - stat_w
            avail = stat_x - name_x - 8
            n = name or 'TBD'
            while n and int(font22.getlength(n)) > avail:
                n = n[:-1]
            draw.text((name_x, y), n, font=font22, fill=0)
            if stat:
                draw.text((stat_x, y + 2), stat, font=font18, fill=0)

        _draw_fs_pitcher(DETAIL_TOP,      away_abbr, away_pitcher_name, away_pitcher_stat)
        _draw_fs_pitcher(DETAIL_TOP + 34, home_abbr, home_pitcher_name, home_pitcher_stat)

        # Weather
        weather_parts = []
        temp = game_data.get('weather_temp_f')
        if temp is not None:
            weather_parts.append(f'{temp}°F')
        wind_speed = game_data.get('weather_wind_mph')
        wind_dir   = (game_data.get('weather_wind_dir') or '').strip()
        if wind_speed is not None:
            weather_parts.append(f'{wind_speed}mph {wind_dir}'.strip())
        precip = game_data.get('weather_precip_pct')
        if precip is not None:
            weather_parts.append(f'{precip}% precip')

        if weather_parts:
            wx_str = '  •  '.join(weather_parts)
            ww = int(font22.getlength(wx_str))
            draw.text(((W - ww) // 2, DETAIL_TOP + 80), wx_str, font=font22, fill=0)

        venue = game_data.get('venue') or ''
        if venue:
            vw = int(font18.getlength(venue))
            draw.text(((W - vw) // 2, DETAIL_TOP + 112), venue, font=font18, fill=0)

    elif state == 'Postponed':
        msg = game_data.get('postpone_reason') or game_data.get('description') or 'Game Postponed'
        mw = int(font30.getlength(msg))
        draw.text(((W - mw) // 2, DETAIL_TOP + 80), msg, font=font30, fill=0)

    return Himage
