
import sys
import os

import json

import random
from util import load_json_file, load_yaml_file, save_off_results
from collections import OrderedDict

_logo_cache = {}        # (abbr, team_id) -> grayscale PIL Image or None
_logo_invert_config = None  # loaded once from pic/logo_render_config.json
_emoji_cache = {}       # abbr -> grayscale PIL Image or None
_team_emojis = None     # loaded once from config.yaml

emojidir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic', 'emojis')


def _get_logo_invert_config():
    global _logo_invert_config
    if _logo_invert_config is None:
        config_path = os.path.join(picdir, 'logo_render_config.json')
        try:
            with open(config_path) as f:
                _logo_invert_config = json.load(f)
        except Exception:
            _logo_invert_config = {}
    return _logo_invert_config

def _get_team_emojis():
    """Load team_emojis mapping from config.yaml, cached per process."""
    global _team_emojis
    if _team_emojis is None:
        _team_emojis = load_yaml_file('config.yaml').get('team_emojis', {}) or {}
    return _team_emojis


def _emoji_codepoint(char):
    """Convert an emoji character to its Twemoji hex filename (e.g. 💩 -> 1f4a9).

    Strips variation selectors (U+FE0F) so compound emojis resolve correctly.
    """
    codepoints = [f'{ord(c):x}' for c in char if ord(c) != 0xfe0f]
    return '-'.join(codepoints)


def _try_download_emoji(emoji_char):
    """Download an emoji PNG from the Twemoji CDN (via jsDelivr). Returns True on success."""
    try:
        import urllib.request
        codepoint = _emoji_codepoint(emoji_char)
        os.makedirs(emojidir, exist_ok=True)
        path = os.path.join(emojidir, f'{codepoint}.png')
        url = f'https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/{codepoint}.png'
        with urllib.request.urlopen(url, timeout=5) as response:
            with open(path, 'wb') as f:
                f.write(response.read())
        print(f'Auto-downloaded emoji: {emoji_char} ({codepoint})')
        return True
    except Exception as e:
        print(f'Could not auto-download emoji {emoji_char}: {e}')
        return False


def _load_emoji_gray(abbr):
    """If abbr has an emoji mapping, load its PNG and return a grayscale Image, else None."""
    if abbr in _emoji_cache:
        return _emoji_cache[abbr]

    emojis = _get_team_emojis()
    emoji_char = emojis.get(abbr)
    if not emoji_char:
        _emoji_cache[abbr] = None
        return None

    codepoint = _emoji_codepoint(emoji_char)
    path = os.path.join(emojidir, f'{codepoint}.png')
    if not os.path.exists(path):
        _try_download_emoji(emoji_char)

    result = None
    if os.path.exists(path):
        try:
            from PIL import ImageStat
            img = Image.open(path).convert('RGBA')
            # Detect predominantly white/bright emojis and invert so they
            # don't vanish against the white e-ink background.
            alpha_mask = img.split()[3].point(lambda p: 255 if p > 32 else 0)
            avg_brightness = ImageStat.Stat(img.convert('L'), mask=alpha_mask).mean[0]
            if avg_brightness > 180:
                r, g, b, a = img.split()
                r = r.point(lambda p: 255 - p)
                g = g.point(lambda p: 255 - p)
                b = b.point(lambda p: 255 - p)
                img = Image.merge('RGBA', (r, g, b, a))
            bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            result = bg.convert('L')
            # Sharpen edges (eyes, mouth) so they survive aggressive
            # thumbnail + contrast dithering in _logo_small / _logo_ghost.
            from PIL import ImageFilter
            result = ImageOps.autocontrast(result, cutoff=1)
            result = result.filter(ImageFilter.UnsharpMask(radius=2, percent=250, threshold=0))
        except Exception:
            pass

    _emoji_cache[abbr] = result
    return result



_char_emoji_cache: dict = {}


def _load_char_emoji(emoji_char, size=12):
    """Load a single emoji character as a grayscale PIL Image resized to size×size, or None."""
    cache_key = (emoji_char, size)
    if cache_key in _char_emoji_cache:
        return _char_emoji_cache[cache_key]

    codepoint = _emoji_codepoint(emoji_char)
    path = os.path.join(emojidir, f'{codepoint}.png')
    if not os.path.exists(path):
        _try_download_emoji(emoji_char)

    result = None
    if os.path.exists(path):
        try:
            from PIL import ImageStat
            img = Image.open(path).convert('RGBA')
            alpha_mask = img.split()[3].point(lambda p: 255 if p > 32 else 0)
            avg_brightness = ImageStat.Stat(img.convert('L'), mask=alpha_mask).mean[0]
            if avg_brightness > 180:
                r, g, b, a = img.split()
                r = r.point(lambda p: 255 - p)
                g = g.point(lambda p: 255 - p)
                b = b.point(lambda p: 255 - p)
                img = Image.merge('RGBA', (r, g, b, a))
            bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            gray = bg.convert('L')
            result = gray.resize((size, size), Image.LANCZOS)
        except Exception:
            pass

    _char_emoji_cache[cache_key] = result
    return result


standings_dict = {
    1: 'American League East',
    2: 'American League Central',
    3: 'American League West',
    4: 'National League East',
    5: 'National League Central',
    6: 'National League West',
}

picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')
libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')
logodir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic', 'logos')
logo_cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic', 'logos_cache')

# ESPN CDN abbreviation overrides
_ESPN_ABBR_MAP = {'AZ': 'ari', 'CWS': 'chw', 'WSH': 'wsh'}
# Maps our internal WBC abbreviations to ESPN's country CDN slug (used in fallback path)
_COUNTRY_ESPN_MAP = {'CLM': 'col'}  # Colombia WBC uses 'col' on ESPN countries CDN
# Team IDs whose cached abbreviation must be overridden (WBC teams that collide with MLB)
_TEAM_ID_ABBR_OVERRIDE = {'792': 'CLM'}  # Colombia WBC team ID → CLM

# Font cache — avoids re-parsing Font.ttc on every draw_box() call (called once per game cell)
_font_cache: dict = {}

def _get_font(size: int):
    if size not in _font_cache:
        _font_cache[size] = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), size)
    return _font_cache[size]

def _try_download_logo(abbr):
    """Download a missing team logo from ESPN CDN using stdlib only (no pip needed).

    Tries MLB CDN first, then falls back to countries CDN for international/WBC teams.
    Skips numeric or T{id} fallback abbreviations — those are unknown spring training
    teams that won't exist on any CDN.
    """
    # Skip fallback IDs like "T792" or pure numeric strings — no logo exists for them
    if abbr.isdigit() or (abbr.startswith('T') and abbr[1:].isdigit()):
        return False

    import urllib.request
    path = os.path.join(logodir, f'{abbr}.png')
    os.makedirs(logodir, exist_ok=True)

    # Try MLB CDN first
    try:
        espn = _ESPN_ABBR_MAP.get(abbr.upper(), abbr.lower())
        non_dark = _get_logo_invert_config().get('non_dark', [])
        variant = 'mlb/500' if abbr.upper() in non_dark else 'mlb/500-dark'
        url = f'https://a.espncdn.com/i/teamlogos/{variant}/{espn}.png'
        with urllib.request.urlopen(url, timeout=5) as response:
            with open(path, 'wb') as f:
                f.write(response.read())
        print(f'Auto-downloaded logo: {abbr}')
        return True
    except Exception:
        pass

    # Fallback: try ESPN countries CDN for international/WBC teams
    try:
        espn = _COUNTRY_ESPN_MAP.get(abbr.upper(), abbr.lower())
        url = f'https://a.espncdn.com/i/teamlogos/countries/500/{espn}.png'
        with urllib.request.urlopen(url, timeout=5) as response:
            with open(path, 'wb') as f:
                f.write(response.read())
        print(f'Auto-downloaded country logo: {abbr}')
        return True
    except Exception as e:
        print(f'Could not auto-download logo for {abbr}: {e}')
        return False

if os.path.exists(libdir):
    sys.path.append(libdir)

EPD_WIDTH = 800
EPD_HEIGHT = 480

import logging
import time
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance
import traceback


# logging.basicConfig(level=logging.DEBUG)

def normalize_dict(d):
    for key, value in d.items():
        if value is None:
            d[key] = ''  # Convert None to ''
        elif isinstance(value, list):
            d[key] = [item if item is not None else '' for item in value]  # Convert None to '' in lists
        elif isinstance(value, dict):
            d[key] = normalize_dict(value)  # Recursively normalize nested dictionaries
    return d


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
                            home_team_id=home_team_id, away_team_id=away_team_id)
    return Himage, new_image_dict

def draw_boards():
    
    new_image_dict = {}
    config_data = load_yaml_file('config.yaml')
    linescore_data = load_json_file('linescore.json')
    # epd = epd7in5_V2.EPD()
    Himage = Image.new('1', (800, 480), 255)  # 255: clear the frame
    col_start = 100
    row_start = 40
    
    team_abbr = None
    if linescore_data.get(config_data.get('primary')):
        team_abbr = config_data.get('primary')
    elif linescore_data.get(config_data.get('primary_backup')):
        team_abbr = config_data.get('primary_backup')
    elif linescore_data.get(config_data.get('primary_backup_2')):
        team_abbr = config_data.get('primary_backup_2')
    
    
    
    if team_abbr:   
        Himage, new_image_dict = generate_linescore(col_start, row_start, team_abbr, Himage, new_image_dict)
    
    team_abbr = None
    if linescore_data.get(config_data.get('secondary')):
        team_abbr = config_data.get('secondary')
    elif linescore_data.get(config_data.get('secondary_backup')):
        
        team_abbr = config_data.get('secondary_backup')
        
    elif linescore_data.get(config_data.get('secondary_backup_2')):
        team_abbr = config_data.get('secondary_backup_2')
        
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

        # Compute per-panel changed regions
        # Panel layout: primary (y:0-179), secondary (y:180-319), standings (y:320-480)
        panels = [
            (0, 0, 800, 180),    # primary game
            (0, 180, 800, 140),  # secondary game
            (0, 320, 800, 160),  # standings
        ]
        old_flat = json.dumps(n1, sort_keys=True) if n1 else ''
        new_flat = json.dumps(n2, sort_keys=True)
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
                   home_team_id=None, away_team_id=None):
    draw = ImageDraw.Draw(Himage)

    # Team logos in team name rows (24px, fits in 30px row with 3px top/bottom padding)
    _logo_size = 24
    _logo_x = col_start + 2
    if away_team_id:
        _away_logo = _logo_small(away_team, away_team_id, size=_logo_size)
        if _away_logo:
            Himage.paste(_away_logo, (_logo_x, row_start + 33))
            draw = ImageDraw.Draw(Himage)
    if home_team_id:
        _home_logo = _logo_small(home_team, home_team_id, size=_logo_size)
        if _home_logo:
            Himage.paste(_home_logo, (_logo_x, row_start + 63))
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


def draw_diamond(Himage, center, size, fill=False):
    draw = ImageDraw.Draw(Himage)
    x, y = center
    diamond = [(x, y - size), (x + size, y), (x, y + size), (x - size, y)]
    
    if fill:
        draw.polygon(diamond,fill='black', outline='black')
    else :
        draw.polygon(diamond, outline='black')
    return Himage
        

# Function to draw a circle at a specific location with an option to fill
def draw_circle(Himage, center, radius, fill):
    draw = ImageDraw.Draw(Himage)

    x, y = center
    bounding_box = [x - radius, y - radius, x + radius, y + radius]  # Defines the square in which the circle will be drawn
    if fill:
        draw.ellipse(bounding_box, fill='black', outline='black')
    else:
        draw.ellipse(bounding_box, outline='black')
    return Himage

def check_if_two_chars(num):
    
    if len(str(num)) == 2:
        return -6
    return 0

def _load_logo_gray(abbr, team_id):
    """Load a team logo PNG and return it as a grayscale (L-mode) PIL Image, or None.

    Inversion is determined by pic/logo_render_config.json (committed to git) so
    every machine renders logos identically. Falls back to brightness detection for
    any team not in the config. Results are cached in _logo_cache per process.
    """
    emoji_img = _load_emoji_gray(abbr)
    if emoji_img is not None:
        return emoji_img

    cache_key = (abbr, str(team_id))
    if cache_key in _logo_cache:
        return _logo_cache[cache_key]

    invert_config = _get_logo_invert_config()

    result = None
    for name in (abbr, str(team_id)):
        path = os.path.join(logodir, f'{name}.png')
        if not os.path.exists(path):
            _try_download_logo(name)
        if os.path.exists(path):
            try:
                img = Image.open(path).convert('RGBA')
                _alpha_bbox = img.split()[3].getbbox()
                if _alpha_bbox:
                    img = img.crop(_alpha_bbox)

                # Use committed config if available, else fall back to brightness detection
                if abbr in invert_config:
                    should_invert = invert_config[abbr]
                else:
                    from PIL import ImageStat
                    alpha_mask = img.split()[3].point(lambda p: 255 if p > 32 else 0)
                    avg_brightness = ImageStat.Stat(img.convert('L'), mask=alpha_mask).mean[0]
                    should_invert = avg_brightness > 180

                if should_invert:
                    r, g, b, a = img.split()
                    r = r.point(lambda p: 255 - p)
                    g = g.point(lambda p: 255 - p)
                    b = b.point(lambda p: 255 - p)
                    img = Image.merge('RGBA', (r, g, b, a))

                # For logos with white outlines/text on colored backgrounds,
                # turn near-white visible pixels black so they show on e-ink
                if abbr in invert_config.get('darken_white', []):
                    r, g, b, a = img.split()
                    pixels_r = list(r.getdata())
                    pixels_g = list(g.getdata())
                    pixels_b = list(b.getdata())
                    pixels_a = list(a.getdata())
                    new_r, new_g, new_b = [], [], []
                    for rv, gv, bv, av in zip(pixels_r, pixels_g, pixels_b, pixels_a):
                        if av > 32 and rv > 200 and gv > 200 and bv > 200:
                            new_r.append(0); new_g.append(0); new_b.append(0)
                        else:
                            new_r.append(rv); new_g.append(gv); new_b.append(bv)
                    r.putdata(new_r); g.putdata(new_g); b.putdata(new_b)
                    img = Image.merge('RGBA', (r, g, b, a))

                bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                result = bg.convert('L')
                break
            except Exception:
                pass

    _logo_cache[cache_key] = result
    return result


def _paste_logo(image, logo, pos):
    """Paste a 1-bit logo without its white background (only dark pixels are drawn)."""
    image.paste(logo, pos, mask=ImageOps.invert(logo.convert('L')))


def _logo_small(abbr, team_id, size=28):
    """Small 1-bit logo for the team name row. Returns a '1'-mode image or None."""
    gray = _load_logo_gray(abbr, team_id)
    if gray is None:
        return None
    gray = gray.copy()
    gray.thumbnail((size, size), Image.LANCZOS)
    # Normalize histogram so inherently dark logos (like BAL/MIL) get lifted
    # to a visible range before dithering, preserving internal detail.
    gray = ImageOps.autocontrast(gray, cutoff=2)
    gray = ImageEnhance.Contrast(gray).enhance(3.0)
    return gray.convert('1')


def _logo_ghost(abbr, team_id, size=110):
    """Large, very-light ghost logo for the winner watermark on finished games.

    The logo is dramatically brightened before Floyd-Steinberg dithering so only
    ~30-35 % of the logo's darkest pixels survive as black dots — giving a clearly
    recognisable watermark crest without obscuring the score text drawn on top.
    Returns a '1'-mode image or None.
    """
    gray = _load_logo_gray(abbr, team_id)
    if gray is None:
        return None
    gray = gray.copy()
    gray.thumbnail((size, size), Image.LANCZOS)
    # Lift dark pixels moderately so ~30-35% survive as black dots
    gray = gray.point(lambda p: 255 if p > 180 else min(255, int(p * 0.3 + 160)))
    return gray.convert('1')


_NAME_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'v'}

def _format_player_name(name):
    """Return 'F. Lastname' for a full player name, skipping suffixes like Jr./Sr./II."""
    if not name:
        return ''
    parts = name.split()
    last_name = parts[-1]
    for i in range(len(parts) - 1, 0, -1):
        if parts[i].lower().strip('.') not in _NAME_SUFFIXES:
            last_name = parts[i]
            break
    first_initial = parts[0][0] + '.' if len(parts) > 1 else ''
    return f'{first_initial} {last_name}' if first_initial else last_name


def _last_name(name):
    """Return just the last name, skipping suffixes like Jr./Sr./II."""
    if not name:
        return ''
    parts = name.split()
    if not parts:
        return ''
    for i in range(len(parts) - 1, 0, -1):
        if parts[i].lower().strip('.') not in _NAME_SUFFIXES:
            return parts[i]
    return parts[-1]


def _render_linescore_row(draw, x, y, inning_runs, fnt, max_width=130):
    """Draw per-inning run values as a space-separated strip."""
    if not inning_runs:
        return
    parts = [str(r) if r is not None else 'x' for r in inning_runs[:15]]
    # Try progressively tighter separators if the string is too wide
    for sep in ('  ', ' ', ''):
        txt = sep.join(parts)
        if int(fnt.getlength(txt)) <= max_width:
            break
    draw.text((x, y), txt, font=fnt, fill=0)


def _pitcher_line(name, note):
    """Return (name_str, stat_str) for probable pitcher display.

    name_str is 'Lastname F.' format.
    stat_str combines W-L and ERA, e.g. '1-0 3.45', or just one if the other
    is missing, or '' if neither is available.
    """
    if not name:
        return ('TBD', '')
    parts = name.split()
    last_name = parts[-1]
    for i in range(len(parts) - 1, 0, -1):
        if parts[i].lower().strip('.') not in _NAME_SUFFIXES:
            last_name = parts[i]
            break
    first_initial = parts[0][0] + '.' if len(parts) > 1 else ''
    display_name = f'{first_initial} {last_name}' if first_initial else last_name

    wl_str = ''
    era_str = ''
    if note:
        note_parts = note.split(', ')
        if note_parts:
            candidate = note_parts[0].strip()
            if '-' in candidate:
                left, right = candidate.split('-', 1)
                if left.strip().isdigit() and right.strip().isdigit():
                    wl_str = candidate
        if len(note_parts) >= 2:
            era_candidate = note_parts[1].replace(' ERA', '').strip()
            if era_candidate and not era_candidate.startswith('-'):
                try:
                    float(era_candidate)
                    era_str = era_candidate
                except ValueError:
                    pass

    if wl_str and era_str:
        stat = f'{wl_str} {era_str}'
    elif wl_str:
        stat = wl_str
    elif era_str:
        stat = era_str
    else:
        stat = ''
    return (display_name, stat)


_VENUE_OVERRIDES = {
    'loanDepot park': 'LoanDepot Park',
    'Daikin Park': 'Minute Maid Park',
    'Guaranteed Rate Field': 'Guaranteed Rate',
    'American Family Field': 'Am. Family Field',
    'Great American Ball Park': 'Great American',
}

def _series_display_str(game_data):
    """Return a short series record string for the header, or None if not applicable."""
    total = game_data.get('series_total_games') or 1
    if total <= 1:
        return None
    wins = game_data.get('series_wins') or 0
    losses = game_data.get('series_losses') or 0
    if wins == 0 and losses == 0:
        gn = game_data.get('series_game_number') or 1
        return f'Gm {gn}/{total}'
    if wins == losses:
        return f'Tied {wins}-{losses}'
    result = (game_data.get('series_result') or '').replace('Series ', '').strip()
    if result:
        return result[0].upper() + result[1:]
    return None


def _clean_venue_name(venue):
    """Return a short, ad-free venue name for display in the scoreboard header."""
    if not venue:
        return venue
    # Check for known overrides first
    if venue in _VENUE_OVERRIDES:
        return _VENUE_OVERRIDES[venue]
    # Strip 'X at Y' qualifiers (e.g. 'Oriole Park at Camden Yards' → 'Camden Yards')
    if ' at ' in venue:
        venue = venue.split(' at ', 1)[1]
    return venue


_AL_DIV_ORDER = [
    'American League East',
    'American League Central',
    'American League West',
]
_NL_DIV_ORDER = [
    'National League East',
    'National League Central',
    'National League West',
]
_SIDEBAR_LOGO_SIZE = 20
_SIDEBAR_ROW_Y     = [25, 175, 325]   # y start for each division row (matches grid row spacing)
_SIDEBAR_ROW_H     = 150              # height per division section (grid row spacing)
_SIDEBAR_VERTICAL_PADDING = 5


# Wildcard header strip — aligned directly over the score boxes (x=32..767)
# Corners (x=0..31 and x=768..799) are left as dead space for the sidebar logos.
_WC_BOX_X_START = 32                              # matches x_start in draw_out_of_town_score_board
_WC_BOX_X_END   = 767                             # right edge of last box column (632+135)
_WC_MID         = (_WC_BOX_X_START + _WC_BOX_X_END) // 2   # = 399
_WC_SLOT_W      = 24                                        # px per slot (2px padding around 20px logo)
_WC_STRIP_H     = 30                              # matches y_start of boxes
_WC_LOGO_SZ     = _SIDEBAR_LOGO_SIZE              # same 20px as the sidebar

_AL_DIVISIONS = ['American League East', 'American League Central', 'American League West']
_NL_DIVISIONS = ['National League East', 'National League Central', 'National League West']


def derive_wildcard_from_standings(standings_data):
    """Build {'AL': [...], 'NL': [...]} from standings.json.

    Collects all non-division-leader teams per league, sorts by league_rank
    (overall AL/NL rank already accounts for wildcard position correctly).
    Returns all eligible wildcard teams (max 12: 15 teams minus 3 division leaders).
    Each entry: {'abbr': str, 'team_id': str, 'gb': str}.
    """
    abbr_map = standings_data.get('team_abbreviation', {})
    divisions = standings_data.get('standings', {})
    result = {}

    for league_key, div_names in (('AL', _AL_DIVISIONS), ('NL', _NL_DIVISIONS)):
        teams = []
        for div in div_names:
            for t in divisions.get(div, []):
                if str(t.get('divisionRank', '')) == '1':
                    continue  # skip division leaders — they aren't competing for the wildcard
                team_id = str(t.get('team_id', ''))
                abbr = abbr_map.get(team_id, t.get('team_name', '???')[:3].upper())
                try:
                    rank = int(t.get('league_rank', 999))
                except (ValueError, TypeError):
                    rank = 999
                teams.append({
                    'abbr': abbr,
                    'team_id': team_id,
                    'gb': t.get('wild_card_games_back') or '-',
                    'rank': rank,
                })
        teams.sort(key=lambda t: t['rank'])
        result[league_key] = teams  # all eligible, no cap

    return result


_WC_WILDCARD_SPOTS = 3   # number of wildcard playoff berths per league
_WC_MAX_TEAMS      = 12  # max eligible per league (15 teams - 3 division leaders)


def draw_wildcard_header(Himage, wildcard_data):
    """Draw a compact wildcard standings strip across the top of the display (y=0..30).

    AL wildcard (all eligible, up to 12) left-to-right in the left half, rank 1 at left edge.
    NL wildcard (all eligible, up to 12) right-to-left in the right half, rank 1 at right edge.
    A rounded rectangle is drawn around the top-3 wildcard leaders on each side.
    Falls back to 3-letter abbreviation (font9) when no logo is available.
    """
    draw = ImageDraw.Draw(Himage)
    font = _get_font(9)

    def _draw_slot(slot_x, team):
        abbr    = (team.get('abbr') or '???')[:4]
        team_id = str(team.get('team_id', ''))

        logo = _logo_small(abbr, team_id, size=_WC_LOGO_SZ)
        if logo is not None:
            lw, lh = logo.size
            logo_x = slot_x + (_WC_SLOT_W - lw) // 2
            logo_y = (_WC_STRIP_H - lh) // 2
            Himage.paste(logo, (logo_x, logo_y))
        else:
            abbr_w = int(font.getlength(abbr))
            draw.text((slot_x + (_WC_SLOT_W - abbr_w) // 2, (_WC_STRIP_H - 9) // 2), abbr, font=font, fill=0)

    al_teams = wildcard_data.get('AL', [])[:_WC_MAX_TEAMS]
    nl_teams = wildcard_data.get('NL', [])[:_WC_MAX_TEAMS]

    # AL: rank 1 at left box edge (x=32), higher ranks toward center
    for i, team in enumerate(al_teams):
        _draw_slot(_WC_BOX_X_START + i * _WC_SLOT_W, team)

    # NL: rank 1 at right box edge (x=767), higher ranks toward center
    for i, team in enumerate(nl_teams):
        _draw_slot(_WC_BOX_X_END - (i + 1) * _WC_SLOT_W, team)

    # Draw a rounded box around the wildcard leaders (top _WC_WILDCARD_SPOTS per league)
    n_al = min(len(al_teams), _WC_WILDCARD_SPOTS)
    n_nl = min(len(nl_teams), _WC_WILDCARD_SPOTS)

    if n_al > 0:
        box_x0 = _WC_BOX_X_START
        box_x1 = _WC_BOX_X_START + n_al * _WC_SLOT_W
        try:
            draw.rounded_rectangle([box_x0, 1, box_x1, _WC_STRIP_H - 2], radius=3, outline=0, width=1)
        except AttributeError:
            draw.rectangle([box_x0, 1, box_x1, _WC_STRIP_H - 2], outline=0, width=1)

    if n_nl > 0:
        box_x0 = _WC_BOX_X_END - n_nl * _WC_SLOT_W
        box_x1 = _WC_BOX_X_END
        try:
            draw.rounded_rectangle([box_x0, 1, box_x1, _WC_STRIP_H - 2], radius=3, outline=0, width=1)
        except AttributeError:
            draw.rectangle([box_x0, 1, box_x1, _WC_STRIP_H - 2], outline=0, width=1)

    return Himage


def draw_standings_sidebar(Himage, standings_data, team_data, side='left'):
    """Draw a vertical strip of division-standings logos on the left (AL) or right (NL) edge.

    Logos are 26px, ordered 1st place (top) to 5th place (bottom) within each
    division section. Three sections align with the three scoreboard game rows:
      section 0 = East   (y=30–180)
      section 1 = Central (y=180–330)
      section 2 = West   (y=330–480)

    side='left'  → AL divisions, logo_x=6  (centered in 32px left margin)
    side='right' → NL divisions, logo_x=774 (centered in 32px right margin)
    """
    divisions = _AL_DIV_ORDER if side == 'left' else _NL_DIV_ORDER
    abbr_map  = {**standings_data.get('team_abbreviation', {}),
                 **team_data.get('team_abbreviation', {})}

    logo_x = (32 - _SIDEBAR_LOGO_SIZE) // 2 if side == 'left' else (800 - 32) + (32 - _SIDEBAR_LOGO_SIZE) // 2
    sep_x0, sep_x1 = (0, 31) if side == 'left' else (768, 800)
    # Line drawn on the outer edge of the logo (between logo and display edge)
    line_x = logo_x - 4 if side == 'left' else logo_x + _SIDEBAR_LOGO_SIZE + 3

    draw = ImageDraw.Draw(Himage)

    # Build previous-rank lookup from standings_prev.json for movement indicators
    # Stores (rank, wins, losses) so tied teams that didn't change record are not flagged.
    prev_rank = {}
    try:
        prev_data = load_json_file('standings_prev.json')
        for _teams in prev_data.get('standings', {}).values():
            for _t in _teams:
                _tid = str(_t.get('team_id', ''))
                _r = _t.get('divisionRank')
                if _tid and _r is not None:
                    try:
                        prev_rank[_tid] = (
                            int(_r),
                            int(_t.get('league_record_wins') or 0),
                            int(_t.get('league_record_losses') or 0),
                        )
                    except (ValueError, TypeError):
                        pass
    except Exception:
        pass

    for row_idx, div_name in enumerate(divisions):
        teams = standings_data.get('standings', {}).get(div_name, [])
        teams = sorted(teams, key=lambda t: int(t.get('divisionRank', 99)))
        y_section = _SIDEBAR_ROW_Y[row_idx]
        slot_h    = (_SIDEBAR_ROW_H - (_SIDEBAR_VERTICAL_PADDING * 2)) // 5

        # Find team IDs whose rank genuinely changed (record moved, not just API tie-break).
        # Any team that actually changed record is a "mover"; its swap partner gets marked too
        # even if the partner's own record didn't change (e.g. Texas climbs past a team that
        # didn't play — that team's rank still changed).
        movers = set()
        for team in teams[:5]:
            tid = str(team.get('team_id', ''))
            if tid not in prev_rank:
                continue
            cur_rank = int(team.get('divisionRank', 99))
            prev_r, prev_w, prev_l = prev_rank[tid]
            cur_w = int(team.get('league_record_wins') or 0)
            cur_l = int(team.get('league_record_losses') or 0)
            if cur_rank != prev_r and (cur_w != prev_w or cur_l != prev_l):
                movers.add(tid)

        # Any team displaced by a mover also changed rank — mark it too.
        if movers:
            for team in teams[:5]:
                tid = str(team.get('team_id', ''))
                if tid not in prev_rank or tid in movers:
                    continue
                cur_rank = int(team.get('divisionRank', 99))
                prev_r, _, _ = prev_rank[tid]
                if cur_rank != prev_r:
                    movers.add(tid)

        for slot_idx, team in enumerate(teams[:5]):
            team_id = str(team.get('team_id', ''))
            abbr    = abbr_map.get(team_id, f'T{team_id}')
            logo_y  = y_section + _SIDEBAR_VERTICAL_PADDING + slot_idx * slot_h

            logo_img = _logo_small(abbr, team_id, size=_SIDEBAR_LOGO_SIZE)
            if logo_img is not None:
                lw, lh = logo_img.size
                paste_x = logo_x + (_SIDEBAR_LOGO_SIZE - lw) // 2
                Himage.paste(logo_img, (paste_x, logo_y))
            else:
                font = _get_font(9)
                tw = int(font.getlength(abbr[:3]))
                draw.text((logo_x + (_SIDEBAR_LOGO_SIZE - tw) // 2, logo_y + 8), abbr[:3], font=font, fill=0)

            if team_id in movers:
                draw.line(
                    (line_x, logo_y, line_x, logo_y + _SIDEBAR_LOGO_SIZE - 1),
                    fill=0, width=2,
                )

            # Draw --- between tied consecutive slots (same W-L record)
            if slot_idx + 1 < 5 and slot_idx + 1 < len(teams):
                nxt = teams[slot_idx + 1]
                cur_wl = (int(team.get('league_record_wins') or 0), int(team.get('league_record_losses') or 0))
                nxt_wl = (int(nxt.get('league_record_wins') or 0),  int(nxt.get('league_record_losses') or 0))
                if cur_wl == nxt_wl:
                    gap_y      = logo_y + _SIDEBAR_LOGO_SIZE + (slot_h - _SIDEBAR_LOGO_SIZE) // 2
                    dash_w, gap_w = 4, 2
                    dash_start = logo_x + (_SIDEBAR_LOGO_SIZE - (3 * dash_w + 2 * gap_w)) // 2
                    for d in range(3):
                        x0 = dash_start + d * (dash_w + gap_w)
                        draw.line((x0, gap_y, x0 + dash_w - 1, gap_y), fill=0, width=1)

        # Removed separator lines between division sections

    return Himage


def _draw_linescore_grid(draw, Himage, start_x, start_y, game_data, team_data, use_logos):
    """Full-width per-inning linescore grid for between-inning scoreboard tiles.

    Layout (135px wide box):
      Row 0 (14px): inning number labels  — starts at start_y+20 (header line)
      Row 1 (16px): away logo + per-inning runs
      Row 2 (16px): home logo + per-inning runs

    Columns: 15px logo col + 9 × 13px inning cols = 132px
    Extra-innings: window shifts so the current inning is the rightmost column.
    """
    LOGO_COL_W = 15
    ROW_H_HDR  = 14
    ROW_H_TEAM = 16
    N_COLS     = 9
    COL_W      = 13   # 15 + 9×13 = 132 ≤ 135

    y0 = start_y + 83            # grid top — bottom half of box (scores/logos/bases stay above)
    y1 = y0 + ROW_H_HDR          # = start_y + 97  (away row top)
    y2 = y1 + ROW_H_TEAM         # = start_y + 113 (home row top)
    y3 = y2 + ROW_H_TEAM         # = start_y + 129 (grid bottom)

    current_inning = game_data.get('current_inning') or 1
    first_inn = max(1, current_inning - N_COLS + 1) if current_inning > N_COLS else 1

    away_inn = game_data.get('away_inning_runs') or []
    home_inn = game_data.get('home_inning_runs') or []

    font9  = _get_font(9)
    font11 = _get_font(11)

    grid_right = start_x + LOGO_COL_W + N_COLS * COL_W

    # --- tic-tac-toe grid: internal lines only, no outer border ---
    draw.line((start_x, y1, grid_right, y1), fill=0)  # row divider 1
    draw.line((start_x, y2, grid_right, y2), fill=0)  # row divider 2
    draw.line((start_x + LOGO_COL_W, y0, start_x + LOGO_COL_W, y3), fill=0)  # logo col divider
    for k in range(1, N_COLS):
        cx = start_x + LOGO_COL_W + k * COL_W
        draw.line((cx, y0, cx, y3), fill=0)

    # --- inning header labels ---
    for k in range(N_COLS):
        s = str(first_inn + k)
        cell_x = start_x + LOGO_COL_W + k * COL_W
        bbox = font9.getbbox(s)
        vis_w = bbox[2] - bbox[0]
        tx = cell_x + (COL_W - vis_w) // 2 - bbox[0] + 1
        draw.text((tx, y0 + (ROW_H_HDR - 9) // 2), s, font=font9, fill=0)

    # --- logos / abbr in team rows ---
    away_id  = str(game_data.get('away_team_id', ''))
    home_id  = str(game_data.get('home_team_id', ''))
    abbr_map = team_data.get('team_abbreviation', {})
    away_abbr = abbr_map.get(away_id, away_id)
    home_abbr = abbr_map.get(home_id, home_id)

    def _place(abbr, tid, row_y):
        nonlocal draw
        lsz = 12
        logo = _logo_small(abbr, tid, size=lsz) if use_logos else None
        if logo:
            Himage.paste(logo, (start_x + (LOGO_COL_W - lsz) // 2, row_y + (ROW_H_TEAM - lsz) // 2))
            draw = ImageDraw.Draw(Himage)
        else:
            s = (abbr or '')[:3]
            tw = int(font9.getlength(s))
            draw.text((start_x + (LOGO_COL_W - tw) // 2, row_y + (ROW_H_TEAM - 9) // 2), s, font=font9, fill=0)

    _place(away_abbr, away_id, y1)
    _place(home_abbr, home_id, y2)

    # --- per-inning scores (blank for incomplete innings) ---
    def _draw_row(inn_runs, row_y):
        for k in range(N_COLS):
            idx = first_inn - 1 + k
            if idx < len(inn_runs) and inn_runs[idx] is not None:
                val = str(inn_runs[idx])
                cell_x = start_x + LOGO_COL_W + k * COL_W
                # Use font9 for double-digit values that won't fit in font11
                fnt = font11 if int(font11.getlength(val)) <= COL_W - 2 else font9
                fnt_h = 11 if fnt is font11 else 9
                bbox = fnt.getbbox(val)
                vis_w = bbox[2] - bbox[0]
                tx = cell_x + (COL_W - vis_w) // 2 - bbox[0] + 1
                draw.text((tx, row_y + (ROW_H_TEAM - fnt_h) // 2), val, font=fnt, fill=0)

    _draw_row(away_inn, y1)
    _draw_row(home_inn, y2)

    return draw, Himage


_ABS_CHALLENGE_MAX = 2


def _draw_challenge_dots(draw, start_x, start_y, game_data, use_logos=False, logo_x_offset=2):
    """ABS dots at original position beside the team row; replay dot below the abbreviation."""
    _LOGO_SIZE = 28
    r = 3
    dot_spacing = 8

    if use_logos:
        # x: immediately right of logo + abbr (original position)
        dot_x = start_x + logo_x_offset + _LOGO_SIZE + 2 + 3
        # ABS y: original positions, vertically centred in each team row
        away_abs_y    = start_y + 30
        home_abs_y    = start_y + 60
        # Replay y: below the abbr text (abbr at row_base+7, font14 14px tall → bottom at row_base+21)
        # Add a small gap so it doesn't touch the text
        away_replay_y = start_y + 25 + 7 + 14 + 4   # = start_y + 50
        home_replay_y = start_y + 55 + 7 + 14 + 4   # = start_y + 80
    else:
        dot_x = start_x + 5 + 3
        away_abs_y    = start_y + 30
        home_abs_y    = start_y + 60
        # font24 glyph height ~17px, top offset ~6px → bottom at row_base + 23
        away_replay_y = start_y + 25 + 23 + 4        # = start_y + 52
        home_replay_y = start_y + 55 + 23 + 4        # = start_y + 82

    abs_max = game_data.get('abs_challenge_max') or _ABS_CHALLENGE_MAX

    for side, abs_y, replay_y in (
        ('away', away_abs_y, away_replay_y),
        ('home', home_abs_y, home_replay_y),
    ):
        abs_remaining = game_data.get(f'{side}_challenges_remaining')
        replay_remaining = game_data.get(f'{side}_replay_remaining')

        # ABS dots (original position, max grows +1 per extra inning)
        if abs_remaining is not None:
            abs_remaining = max(0, min(abs_max, int(abs_remaining)))
            for i in range(abs_max):
                cx = dot_x + i * dot_spacing
                box = (cx - r, abs_y - r, cx + r, abs_y + r)
                if i < abs_remaining:
                    draw.ellipse(box, fill=0, outline=0)
                else:
                    draw.ellipse(box, fill=255, outline=0)

        # Replay dot below the abbreviation (max 1)
        if replay_remaining is not None:
            replay_remaining = max(0, min(1, int(replay_remaining)))
            box = (dot_x - r, replay_y - r, dot_x + r, replay_y + r)
            if replay_remaining > 0:
                draw.ellipse(box, fill=0, outline=0)
            else:
                draw.ellipse(box, fill=255, outline=0)


def _draw_weather_footer(draw, start_x, start_y, horiz_len, game_data, fnt):
    """Pre-game footer: weather left-aligned, TV channel right-aligned, in the inter-row gap."""
    y = start_y + 112

    # TV channel: right-aligned
    tv = game_data.get('tv_channel') or ''
    tv_w = 0
    if tv:
        try:
            tv_w = int(fnt.getlength(tv)) + 2
        except AttributeError:
            tv_w = len(tv) * 5 + 2
        draw.text((start_x + horiz_len - tv_w, y), tv, font=fnt, fill=0)

    avail_w = horiz_len - tv_w - 6

    # Dome takes full priority — no weather shown
    roof = game_data.get('roof_state')
    if roof in ('fixed', 'dome'):
        draw.text((start_x + 2, y), 'Dome', font=fnt, fill=0)
        return

    temp = game_data.get('weather_temp_f')
    wind = game_data.get('weather_wind_mph')
    wd = game_data.get('weather_wind_dir')
    precip = game_data.get('weather_precip_pct')

    if temp is None and wind is None and precip is None:
        return

    # Build candidate strings from most to least detailed (drop direction → drop 'mph' → temp only)
    candidates = []
    _t = f'{temp}°' if temp is not None else None
    _w_full = (f'{wind}mph {wd}' if wd else f'{wind}mph') if (wind is not None and wind >= 1) else None
    _w_nolabel = f'{int(wind)}' if (wind is not None and wind >= 1) else None
    _p = f'{precip}%' if (precip is not None and precip > 0) else None

    for _w in (_w_full, _w_nolabel, None):
        parts = [x for x in (_t, _w, _p) if x]
        if parts:
            candidate = ' '.join(parts)
            if candidate not in candidates:
                candidates.append(candidate)
    if _t and _t not in candidates:
        candidates.append(_t)

    # Try largest font first; within each font try shorter text variants
    for try_fnt in (fnt, _get_font(11), _get_font(9)):
        for text in candidates:
            try:
                tw = int(try_fnt.getlength(text))
            except AttributeError:
                tw = len(text) * 5
            if tw <= avail_w:
                draw.text((start_x + 2, y), text, font=try_fnt, fill=0)
                return


def _is_game_effectively_over(game_data):
    """True if MLB will mark the game Final shortly — used to suppress upcoming-batter text
    during the lag between the final out and detailed_state flipping to Final."""
    if game_data.get('detailed_state') in ('Final', 'Game Over', 'Final: Tied', 'Completed Early'):
        return True
    inning = game_data.get('current_inning') or 0
    state = game_data.get('inningState') or ''
    away = game_data.get('away_runs') or 0
    home = game_data.get('home_runs') or 0
    if inning >= 9:
        # Top of 9+ complete and home already ahead → home doesn't bat
        if state == 'Middle' and home > away:
            return True
        # Bottom of 9+ complete with a non-tie → game over
        if state == 'End' and home != away:
            return True
    return False


def draw_box(Himage, start_x, start_y, game_data, team_data, score_changed=False, use_logos=False, logo_x_offset=2, show_win_prob=False, streak_map=None):
    # Normalize early-completion states (e.g. spring training games called after 6 innings)
    if game_data.get('detailed_state', '').startswith('Completed Early'):
        game_data = dict(game_data)
        game_data['detailed_state'] = 'Final'

    # Normalize mid-game review/challenge states to In Progress
    if game_data.get('detailed_state') in ('Player challenge', 'Manager challenge'):
        game_data = dict(game_data)
        game_data['last_play'] = 'P Challenge' if game_data['detailed_state'] == 'Player challenge' else 'M Challenge'
        game_data['detailed_state'] = 'In Progress'

    # Delayed Start = game hasn't begun yet; treat like Pre-Game (show pitcher probables)
    if game_data.get('detailed_state') == 'Delayed Start':
        game_data = dict(game_data)
        game_data['detailed_state'] = 'Pre-Game'

    # Only show score once the first pitch has been thrown. Evidence of play:
    # a ball/strike in the current at-bat, any out, any hit, a runner on base,
    # an inning break, or the game past inning 1. If none of these are present
    # the game hasn't officially started despite the API saying "In Progress".
    if game_data.get('detailed_state') == 'In Progress':
        # Only show score once the first pitch has been thrown.
        # away_hits/home_hits are intentionally excluded: in the GIF path they
        # are inherited from the final game box score and are always non-zero,
        # causing false positives before the game starts.
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

    draw = ImageDraw.Draw(Himage)
    font26 = _get_font(26)
    font24 = _get_font(24)
    font18 = _get_font(18)
    font14 = _get_font(14)
    font11 = _get_font(11)
    font9 = _get_font(9)

    vertical_len = 110
    horizonta_len = 135
    max_text_width = horizonta_len - 14

    # Needed by the elif chain below — define early so all branches can reference it
    _delayed_with_score = (
        game_data['detailed_state'] == 'Delayed'
        and (game_data.get('current_inning') or 0) > 0
    )

    # True when we should show the linescore grid instead of the normal score layout
    _between_innings = (
        game_data['detailed_state'] == 'In Progress'
        and game_data.get('inningState') in ('Middle', 'End')
    )
    # End of 9th+ with one team leading — game is effectively over, don't show next batters
    _game_ending_state = (
        game_data.get('inningState') == 'End' and
        (game_data.get('current_inning') or 0) >= 9 and
        (game_data.get('away_runs') or 0) != (game_data.get('home_runs') or 0)
    )

    def fit_text(text, max_w):
        try:
            if font14.getlength(text) <= max_w:
                return text, font14
            if font11.getlength(text) <= max_w:
                return text, font11
            while text and font11.getlength(text) > max_w:
                text = text[:-1]
            return text, font11
        except AttributeError:
            return text[:17], font14

    # team names short
    away_team_id = str(game_data['away_team_id'])
    home_team_id = str(game_data['home_team_id'])

    # Handle missing team abbreviations gracefully
    abbr_map = team_data.get('team_abbreviation', {})
    away_team_name = _TEAM_ID_ABBR_OVERRIDE.get(away_team_id) or abbr_map.get(away_team_id, f'T{away_team_id}')
    home_team_name = _TEAM_ID_ABBR_OVERRIDE.get(home_team_id) or abbr_map.get(home_team_id, f'T{home_team_id}')

    # Winner ghost logo — drawn first so all text/scores render on top of it
    if use_logos and game_data['detailed_state'] in ('Final', 'Game Over', 'Final: Tied'):
        winner_abbr = winner_id = None
        if game_data.get('away_team_is_winner'):
            winner_abbr, winner_id = away_team_name, away_team_id
        elif game_data.get('home_team_is_winner'):
            winner_abbr, winner_id = home_team_name, home_team_id
        if winner_abbr:
            ghost = _logo_ghost(winner_abbr, winner_id)
            if ghost:
                gw, gh = ghost.size
                gx = start_x + (135 - gw) // 2 + 0
                gy = start_y + 20 + (vertical_len - gh) // 2
                Himage.paste(ghost, (gx, gy))
                draw = ImageDraw.Draw(Himage)

    # inning or game state
    if game_data['detailed_state'] in ('Final', 'Game Over', 'Final: Tied'):
        away_inning_runs = game_data.get('away_inning_runs') or []
        home_inning_runs = game_data.get('home_inning_runs') or []
        winner_name = game_data.get('winner_name')
        loser_name = game_data.get('loser_name')

        if (away_inning_runs or home_inning_runs) and not (winner_name and loser_name):
            # Game over but decisions not yet posted — show the tic-tac-toe linescore grid.
            draw, Himage = _draw_linescore_grid(draw, Himage, start_x, start_y, game_data, team_data, use_logos)
        else:
            # Pitchers of record — anchored to bottom of box, working upward.
            # bottom border is at start_y + vertical_len + 20 = start_y + 130
            LINE_H = 15
            BOTTOM_Y = start_y + vertical_len + 20 - 3  # 3px margin above bottom border
            saver = game_data.get('saver_name')
            winner_record = game_data.get('winner_record')
            loser_record = game_data.get('loser_record')
            saver_saves = game_data.get('saver_saves')
            lines = []
            wp_name = _format_player_name(winner_name or '')
            lp_name = _format_player_name(loser_name or '')
            wp_str = f'WP: {wp_name} ({winner_record})' if winner_record else f'WP: {wp_name}'
            lp_str = f'LP: {lp_name} ({loser_record})' if loser_record else f'LP: {lp_name}'
            lines.append((lp_str, font14))
            lines.append((wp_str, font14))
            if saver:
                sv_name = _format_player_name(saver)
                sv_str = f'SV: {sv_name} (S{saver_saves})' if saver_saves is not None else f'SV: {sv_name}'
                lines.append((sv_str, font14))

            def _truncate_keep_suffix(s):
                if int(font14.getlength(s)) <= max_text_width:
                    return s
                paren = s.rfind(' (')
                if paren != -1:
                    suffix = s[paren:]
                    prefix = s[:paren]
                    suffix_w = int(font14.getlength(suffix))
                    avail = max_text_width - suffix_w
                    while prefix and int(font14.getlength(prefix)) > avail:
                        prefix = prefix[:-1]
                    return prefix + suffix
                while s and int(font14.getlength(s)) > max_text_width:
                    s = s[:-1]
                return s

            for i, (txt, fnt) in enumerate(reversed(lines)):
                y = BOTTOM_Y - LINE_H * (i + 1)
                draw.text((start_x + 2, y), _truncate_keep_suffix(txt), font=fnt, fill=0)

    elif game_data['detailed_state'] == 'Warmup' or game_data['detailed_state'] == 'Pre-Game' or  game_data['detailed_state'] == 'Scheduled':
        def _draw_pitcher_era(name_part, stat_part, y_pos):
            """Draw pitcher name left-aligned and stat right-anchored."""
            if stat_part:
                stat_w = int(font14.getlength(stat_part))
                stat_x = start_x + horizonta_len - stat_w - 1
                draw.text((stat_x, y_pos), stat_part, font=font14, fill=0)
                max_name_w = stat_x - (start_x + 2) - 2
                name_str, name_fnt = fit_text(name_part, max(max_name_w, 20))
                draw.text((start_x + 2, y_pos), name_str, font=name_fnt, fill=0)
            else:
                name_str, name_fnt = fit_text(name_part, max_text_width)
                draw.text((start_x + 2, y_pos), name_str, font=name_fnt, fill=0)

        away_name, away_stat = _pitcher_line(game_data.get("away_probable"), game_data.get("away_probable_note"))
        home_name, home_stat = _pitcher_line(game_data.get("home_probable"), game_data.get("home_probable_note"))
        _draw_pitcher_era(away_name, away_stat, start_y + 25 + 59)
        _draw_pitcher_era(home_name, home_stat, start_y + 25 + 74)
    elif game_data['detailed_state'] == 'Postponed':
        reason = game_data.get('postpone_reason') or game_data.get('description') or ''
        postponed_line, postponed_fnt = fit_text(f'PPD: {reason}' if reason else 'Postponed', max_text_width)
        draw.text((start_x + 7, start_y + 25 + 59), postponed_line, font=postponed_fnt, fill=0)
    elif _delayed_with_score:
        draw, Himage = _draw_linescore_grid(draw, Himage, start_x, start_y, game_data, team_data, use_logos)
        # Next 3 batters + pitcher — same panel used for between-innings
        _right_x = start_x + horizonta_len - 2
        _max_name_w = 46
        _batter_names = [
            _last_name(game_data.get('next_batter_1') or game_data.get('current_hitter') or ''),
            _last_name(game_data.get('next_batter_2') or game_data.get('due_up') or ''),
            _last_name(game_data.get('next_batter_3') or game_data.get('in_hole') or ''),
        ]
        _name_y = start_y + 21
        for _nm in _batter_names:
            if _nm:
                _nm_disp = _nm
                while _nm_disp and int(font14.getlength(_nm_disp)) > _max_name_w:
                    _nm_disp = _nm_disp[:-1]
                _nw = int(font14.getlength(_nm_disp))
                draw.text((_right_x - _nw, _name_y), _nm_disp, font=font14, fill=0)
            _name_y += 12
        _sep_y = _name_y + 5
        draw.line((start_x + 87, _sep_y, _right_x, _sep_y), fill=0)
        _pit_name = _last_name(game_data.get('next_pitcher') or game_data.get('current_pitcher') or '')
        _pit_max_w = horizonta_len - 2 - 87
        if _pit_name:
            _pit_fnt = font14
            if int(font14.getlength(_pit_name)) > _pit_max_w:
                _pit_fnt = font11
                if int(font11.getlength(_pit_name)) > _pit_max_w:
                    _pit_fnt = font9
                    while _pit_name and int(font9.getlength(_pit_name)) > _pit_max_w:
                        _pit_name = _pit_name[:-1]
            _pit_w = int(_pit_fnt.getlength(_pit_name))
            draw.text((_right_x - _pit_w, _sep_y + 2), _pit_name, font=_pit_fnt, fill=0)
    elif game_data['detailed_state'] == 'In Progress':
        if _between_innings:
            draw, Himage = _draw_linescore_grid(draw, Himage, start_x, start_y, game_data, team_data, use_logos)
        else:
            # Active play: pitch/pitcher/batter info
            _pc = game_data.get('pitch_count')
            _pt = game_data.get('last_pitch_type', '')   # e.g. "FB", "SL", "CH"
            _lps = game_data.get('last_pitch_speed')

            # Pitcher line right badge: pitch type only; count moves into the label
            _right_str = _pt if _pt else ''
            _right_w = int(font11.getlength(_right_str)) + 2 if _right_str else 0

            _pitcher_name = _format_player_name(game_data.get("current_pitcher") or "")
            _pit_avail = max_text_width - _right_w
            _pit_str = f'P: {_pitcher_name}'
            if font14.getlength(_pit_str) <= _pit_avail:
                pitcher_str, pitcher_font = _pit_str, font14
            else:
                pitcher_str, pitcher_font = fit_text(_pit_str, _pit_avail)
            draw.text((start_x + 2, start_y + 25 + 74), pitcher_str, font=pitcher_font, fill=0)
            if _right_str:
                draw.text((start_x + horizonta_len - _right_w, start_y + 25 + 74), _right_str, font=font11, fill=0)

            # Speed right-aligned; pitch count left of speed on same row
            _speed_y = start_y + 25 + 62
            if _lps:
                _speed_str = str(int(_lps))
                _speed_w = int(font11.getlength(_speed_str)) + 2
                _speed_x = start_x + horizonta_len - _speed_w
                draw.text((_speed_x,     _speed_y), _speed_str, font=font11, fill=0)
                draw.text((_speed_x + 1, _speed_y), _speed_str, font=font11, fill=0)
                if _pc is not None:
                    _pc_disp = f'{_pc}P'
                    _pc_w = int(font11.getlength(_pc_disp))
                    draw.text((_speed_x - _pc_w - 3, _speed_y), _pc_disp, font=font11, fill=0)
            elif _pc is not None:
                _pc_disp = f'{_pc}P'
                _pc_w = int(font11.getlength(_pc_disp)) + 2
                draw.text((start_x + horizonta_len - _pc_w, _speed_y), _pc_disp, font=font11, fill=0)

            # Batter record for the night "2-4" right-anchored on hitter line
            _bh = game_data.get('batter_hits')
            _ba = game_data.get('batter_at_bats')
            _ba_str = f'{_bh}-{_ba}' if _bh is not None and _ba is not None else ''
            _ba_w = min(int(font11.getlength(_ba_str)) + 2, horizonta_len - 8) if _ba_str else 0
            _ab_done = game_data.get('current_at_bat_complete', False)
            if _ab_done and not _is_game_effectively_over(game_data):
                _next_hitter = _format_player_name(game_data.get('due_up') or game_data.get('next_batter_1') or '')
                if _next_hitter:
                    _next_str, _next_font = fit_text(f'AB: {_next_hitter}', max(1, max_text_width - _ba_w))
                    draw.text((start_x + 2, start_y + 25 + 89), _next_str, font=_next_font, fill=0)
            else:
                _hitter_name = _format_player_name(game_data.get('current_hitter') or '')
                hitter_str, hitter_font = fit_text(
                    f'AB: {_hitter_name}',
                    max(1, max_text_width - _ba_w),
                )
                draw.text((start_x + 2, start_y + 25 + 89), hitter_str, font=hitter_font, fill=0)
            if _ba_str:
                draw.text((start_x + horizonta_len - _ba_w, start_y + 25 + 89), _ba_str, font=font11, fill=0)
        
    if game_data['detailed_state'] in ('Final', 'Game Over', 'Final: Tied', 'Postponed', 'Delayed'):
        # Normalize display labels
        if game_data['detailed_state'] == 'Game Over':
            game_state_str = 'Final'
        elif game_data['detailed_state'] == 'Final: Tied':
            game_state_str = 'Tied'
        else:
            game_state_str = game_data['detailed_state']

        _fin_inning = game_data.get('current_inning') or 9
        if _fin_inning > 9:
            game_state_str = 'F'
        elif _fin_inning != 9:
            game_state_str += '/' + str(_fin_inning)
            
    elif game_data['detailed_state'] == 'Warmup':
        game_state_str = game_data['detailed_state'] 
        
    elif game_data['detailed_state'] == 'Scheduled'  or game_data['detailed_state'] == 'Pre-Game':
        try:
            from datetime import datetime
            dt = datetime.strptime(game_data['game_start'], "%Y-%m-%dT%H:%M:%SZ")
            game_state_str = dt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            game_state_str = game_data['game_start']
    else:
        extra = ''
        if game_data.get('inningState'):
            extra = game_data.get('inningState').upper()
        
        if game_data['inningState'] == 'Bottom':
            extra = 'Bot'.upper()
            
        if game_data['inningState'] == 'Middle':
            extra = 'Mid'.upper()
            

        game_state_str = extra + ' ' + str(game_data['current_inning'])
    

    # game state — bold via double draw; for pre-game times render AM/PM smaller + bold
    if game_data['detailed_state'] in ('Scheduled', 'Pre-Game', 'Warmup') and ' ' in game_state_str:
        _time_parts = game_state_str.rsplit(' ', 1)
        _time_main, _time_ampm = _time_parts[0], _time_parts[1].lower()
        for _dx in (2, 3):
            draw.text((start_x + _dx, start_y + 3), _time_main, font=font14, fill=0)
        _main_w = int(font14.getlength(_time_main))
        _ampm_x = start_x + 3 + _main_w + 1
        _ampm_y = start_y + 8
        draw.text((_ampm_x, _ampm_y), _time_ampm, font=font9, fill=0)
        draw.text((_ampm_x + 1, _ampm_y), _time_ampm, font=font9, fill=0)
        _total_time_w = _main_w + int(font9.getlength(_time_ampm)) + 2
    else:
        draw.text((start_x + 2, start_y + 3), game_state_str, font=font14, fill=0)
        draw.text((start_x + 3, start_y + 3), game_state_str, font=font14, fill=0)
        _total_time_w = int(font14.getlength(game_state_str))

    if game_data.get('walk_off'):
        _wo_x = start_x + 3 + _total_time_w + 2
        draw.text((_wo_x,     start_y + 4), 'W/O', font=font9, fill=0)
        draw.text((_wo_x + 1, start_y + 4), 'W/O', font=font9, fill=0)

    # Series display — only shown when the game is Final/over, not pre-game or live
    _game_is_final = game_data.get('detailed_state') in ('Final', 'Game Over', 'Final: Tied')
    _active_no_no = (
        game_data['detailed_state'] == 'In Progress' and
        (game_data.get('no_hitter') or game_data.get('perfect_game')) and
        (game_data.get('current_inning') or 0) >= 4
    )
    _ser_total = (game_data.get('series_total_games') or 1)
    _is_sweep = (
        _game_is_final and
        _ser_total > 1 and
        game_data.get('series_is_over') and
        (game_data.get('series_losses') == 0 or game_data.get('series_wins') == 0)
    )
    _series_clinched = (
        _game_is_final and
        _ser_total > 1 and
        game_data.get('series_is_over') and
        not _is_sweep
    )
    _series_tied = (
        _game_is_final and
        _ser_total > 1 and
        game_data.get('series_is_tied') and
        not game_data.get('series_is_over')
    )
    _series_leading = (
        _game_is_final and
        _ser_total > 1 and
        not game_data.get('series_is_over') and
        not game_data.get('series_is_tied') and
        (game_data.get('series_wins') or 0) > 0
    )

    # _ser_content_left_x tracks left edge of series/broom content for G:X:XX positioning
    _ser_content_left_x = start_x + horizonta_len - 2

    if _is_sweep or _series_clinched:
        # Series win (non-sweep): draw winner logo + series score (e.g. 🏆 3-1)
        _sw = game_data.get('series_wins') or 0
        _sl = game_data.get('series_losses') or 0
        _score_str = f'{_sw}-{_sl}'
        _score_w = int(font14.getlength(_score_str))
        _ser_logo_size = 14
        # Determine series winner from current game's winner flag
        _ser_winner_abbr = _ser_winner_id = None
        if game_data.get('away_team_is_winner'):
            _ser_winner_abbr, _ser_winner_id = away_team_name, str(game_data['away_team_id'])
        elif game_data.get('home_team_is_winner'):
            _ser_winner_abbr, _ser_winner_id = home_team_name, str(game_data['home_team_id'])
        _ser_logo = _logo_small(_ser_winner_abbr, _ser_winner_id, size=_ser_logo_size) if _ser_winner_abbr else None
        _rx = start_x + horizonta_len - 2
        if _ser_logo:
            _logo_w, _logo_h = _ser_logo.size
            _score_x = _rx - _score_w
            _logo_x = _score_x - 2 - _logo_w
            _logo_y = start_y + (20 - _logo_h) // 2
            Himage.paste(_ser_logo, (_logo_x, _logo_y))
            draw = ImageDraw.Draw(Himage)
            _ser_content_left_x = _logo_x
        else:
            _score_x = _rx - _score_w
            _ser_content_left_x = _score_x
        draw.text((_score_x,     start_y + 3), _score_str, font=font14, fill=0)
        draw.text((_score_x + 1, start_y + 3), _score_str, font=font14, fill=0)

    elif _series_tied:
        _sw = game_data.get('series_wins') or 0
        _sl = game_data.get('series_losses') or 0
        _tied_str = f'{_sw}-{_sl}'
        _tied_w = int(font14.getlength(_tied_str))
        _rx = start_x + horizonta_len - 2
        _tx = _rx - _tied_w
        _ser_content_left_x = _tx
        draw.text((_tx,     start_y + 3), _tied_str, font=font14, fill=0)
        draw.text((_tx + 1, start_y + 3), _tied_str, font=font14, fill=0)

    elif _series_leading:
        # Series leader: draw leading team's logo + score (e.g. [NYY logo] 1-0)
        _sw = game_data.get('series_wins') or 0
        _sl = game_data.get('series_losses') or 0
        _score_str = f'{_sw}-{_sl}'
        _score_w = int(font14.getlength(_score_str))
        _ser_logo_size = 14
        _ser_leader_abbr = _ser_leader_id = None
        if game_data.get('away_team_is_winner'):
            _ser_leader_abbr, _ser_leader_id = away_team_name, str(game_data['away_team_id'])
        elif game_data.get('home_team_is_winner'):
            _ser_leader_abbr, _ser_leader_id = home_team_name, str(game_data['home_team_id'])
        _ser_logo = _logo_small(_ser_leader_abbr, _ser_leader_id, size=_ser_logo_size) if _ser_leader_abbr else None
        _rx = start_x + horizonta_len - 2
        if _ser_logo:
            _logo_w, _logo_h = _ser_logo.size
            _score_x = _rx - _score_w
            _logo_x = _score_x - 2 - _logo_w
            _logo_y = start_y + (20 - _logo_h) // 2
            Himage.paste(_ser_logo, (_logo_x, _logo_y))
            draw = ImageDraw.Draw(Himage)
            _ser_content_left_x = _logo_x
        else:
            _score_x = _rx - _score_w
            _ser_content_left_x = _score_x
        draw.text((_score_x, start_y + 3), _score_str, font=font14, fill=0)

    # Duration — centered in header for Final games (h:mm format, same font as Final)
    if _game_is_final and not game_data.get('perfect_game') and not game_data.get('no_hitter'):
        _dur_mins = game_data.get('game_duration_minutes')
        if _dur_mins:
            _dur_str = f'{_dur_mins // 60}:{_dur_mins % 60:02d}'
            _dur_w = int(font14.getlength(_dur_str))
            _dur_cx = start_x + horizonta_len // 2 - _dur_w // 2
            draw.text((_dur_cx,     start_y + 3), _dur_str, font=font14, fill=0)
            draw.text((_dur_cx + 1, start_y + 3), _dur_str, font=font14, fill=0)

    # Venue — right-anchored in header, as large as possible without overlapping the time
    if game_data['detailed_state'] in ('Scheduled', 'Pre-Game', 'Warmup', 'Postponed'):
        venue_clean = _clean_venue_name(game_data.get('venue'))
        if venue_clean:
            try:
                _venue_right = _ser_content_left_x - 2
                max_venue_w = max(_venue_right - start_x - _total_time_w - 6, 0)
                if max_venue_w > 0:
                    for vfont, vy in ((font14, 3), (font11, 4), (font9, 5), (_get_font(8), 6), (_get_font(7), 7)):
                        if vfont.getlength(venue_clean) <= max_venue_w:
                            break
                    vw = int(vfont.getlength(venue_clean))
                    vx = _venue_right - vw
                    draw.text((vx, start_y + vy), venue_clean, font=vfont, fill=0)
            except AttributeError:
                pass
    if game_data['detailed_state'] == 'In Progress' and not _is_game_effectively_over(game_data):
        _sub_ev = (game_data.get('sub_event') or '').strip()
        raw_play = (_sub_ev or game_data.get('last_review_result') or game_data.get('last_play') or '').replace('**', '').strip()
        _header_right = _ser_content_left_x - 2
        if _active_no_no:
            # Right-align label; inning state stays on left as-is
            _nh_label = 'Perfect Game' if game_data.get('perfect_game') else 'No-Hitter'
            _nh_lw = int(font14.getlength(_nh_label))
            _nh_lx = _header_right - _nh_lw
            draw.text((_nh_lx,     start_y + 3), _nh_label, font=font14, fill=0)
            draw.text((_nh_lx + 1, start_y + 3), _nh_label, font=font14, fill=0)
        elif _between_innings and raw_play:
            # Mid-inning break: show the play that ended the half-inning
            max_play_w = max(_header_right - start_x - _total_time_w - 10, 0)
            play_text = raw_play
            _play_font = _get_font(12)
            while len(play_text) > 1 and int(_play_font.getlength(play_text)) > max_play_w:
                play_text = play_text[:-2] + '.'
            if play_text and int(_play_font.getlength(play_text)) <= max_play_w:
                pw = int(_play_font.getlength(play_text))
                px = _header_right - pw
                draw.text((px, start_y + 4), play_text, font=_play_font, fill=0)
                draw.text((px + 1, start_y + 4), play_text, font=_play_font, fill=0)
        elif _between_innings:
            # No last-play text available — fall back to showing who's due
            _due_name = _format_player_name(game_data.get('current_hitter') or '')
            if _due_name:
                _due_str = f'Due: {_due_name}'
                _due_fnt = font11
                _max_due_w = max(_header_right - start_x - _total_time_w - 6, 0)
                while _due_str and int(_due_fnt.getlength(_due_str)) > _max_due_w:
                    _due_str = _due_str[:-1]
                if _due_str:
                    _due_w = int(_due_fnt.getlength(_due_str))
                    _due_x = _header_right - _due_w
                    draw.text((_due_x,     start_y + 5), _due_str, font=_due_fnt, fill=0)
                    draw.text((_due_x + 1, start_y + 5), _due_str, font=_due_fnt, fill=0)
        elif raw_play:
            max_play_w = max(_header_right - start_x - _total_time_w - 10, 0)
            play_text = raw_play
            _play_font = _get_font(12)
            while len(play_text) > 1 and int(_play_font.getlength(play_text)) > max_play_w:
                play_text = play_text[:-2] + '.'
            if play_text and int(_play_font.getlength(play_text)) <= max_play_w:
                pw = int(_play_font.getlength(play_text))
                px = _header_right - pw
                draw.text((px, start_y + 4), play_text, font=_play_font, fill=0)
                draw.text((px + 1, start_y + 4), play_text, font=_play_font, fill=0)

    if _delayed_with_score:
        _delay_reason = game_data.get('postpone_reason') or ''
        if _delay_reason:
            _delay_str = f'R: {_delay_reason}'
            _max_delay_w = max(horizonta_len - _total_time_w - 10, 0)
            _delay_fnt = _get_font(12)
            while len(_delay_str) > 1 and int(_delay_fnt.getlength(_delay_str)) > _max_delay_w:
                _delay_str = _delay_str[:-2] + '.'
            if _delay_str and int(_delay_fnt.getlength(_delay_str)) <= _max_delay_w:
                _dw = int(_delay_fnt.getlength(_delay_str))
                _dx_pos = start_x + horizonta_len - _dw - 2
                draw.text((_dx_pos, start_y + 4), _delay_str, font=_delay_fnt, fill=0)
                draw.text((_dx_pos + 1, start_y + 4), _delay_str, font=_delay_fnt, fill=0)

    # Initialize score variables (will be used later for winner display)
    away_runs = str(game_data.get('away_runs', 0) if game_data.get('away_runs', 0) is not None else 0)
    home_runs = str(game_data.get('home_runs', 0) if game_data.get('home_runs', 0) is not None else 0)

    is_game_started = game_data['detailed_state'] in ['Final', 'Game Over', 'In Progress', 'Final: Tied'] or _delayed_with_score
    is_game_finished = game_data['detailed_state'] in ['Final', 'Game Over', 'Final: Tied']

    # Display score if game has started
    if is_game_started:
        draw.text((start_x + 66 + check_if_two_chars(away_runs), start_y + 25), away_runs, font=font24, fill=0)
        draw.text((start_x + 66 + check_if_two_chars(home_runs), start_y + 55), home_runs, font=font24, fill=0)

        if is_game_finished:
            # hits
            away_hits = str(game_data.get('away_hits', 0) if game_data.get('away_hits', 0) is not None else 0)
            home_hits = str(game_data.get('home_hits', 0) if game_data.get('home_hits', 0) is not None else 0)
            draw.text((start_x + 95 + check_if_two_chars(away_hits), start_y + 25),  away_hits, font=font24, fill=0)
            draw.text((start_x + 95 + check_if_two_chars(home_hits), start_y + 55), home_hits , font=font24, fill=0)

            # errors
            draw.text((start_x + 123, start_y + 25),  str(game_data.get('away_errors', 0) if game_data.get('away_errors', 0) is not None else 0), font=font24, fill=0)
            draw.text((start_x + 123 , start_y + 55),  str( game_data.get('home_errors', 0) if game_data.get('home_errors', 0) is not None else 0), font=font24, fill=0)

            # header: R H E label (only when no duration — duration is centered above)
            if not game_data.get('game_duration_minutes') and not game_data.get('perfect_game') and not game_data.get('no_hitter'):
                header = 'R     H     E'
                draw.text((start_x + 68, start_y + 3), header, font=font14, fill=0)
                draw.text((start_x + 69, start_y + 3), header, font=font14, fill=0)
    elif game_data['detailed_state'] in ['Scheduled', 'Pre-Game', 'Warmup']:
        # Game hasn't started — show record stacked above L10/streak, both right-anchored
        def _team_stats(team_id):
            if streak_map:
                return streak_map.get(str(team_id)) or {}
            return {}

        def _draw_record(wins, losses, team_id, y_pos):
            # Primary: W-L in font14, bold via double-draw, aligned to top of logo row
            main_txt = f'{wins}-{losses}'
            main_w = int(font14.getlength(main_txt))
            rx = start_x + horizonta_len - main_w - 1
            draw.text((rx,     y_pos), main_txt, font=font14, fill=0)
            draw.text((rx + 1, y_pos), main_txt, font=font14, fill=0)

            # Secondary: L10 and streak on the line below in font9
            stats = _team_stats(team_id)
            w10, l10 = stats.get('l10_wins'), stats.get('l10_losses')
            s = stats.get('streak') or ''
            parts = []
            if w10 is not None and l10 is not None:
                parts.append(f'{w10}-{l10}')
            if s:
                parts.append(s)
            if parts:
                sub_txt = ' '.join(parts)
                sub_w = int(font11.getlength(sub_txt))
                sx = start_x + horizonta_len - sub_w - 1
                draw.text((sx, y_pos + 15), sub_txt, font=font11, fill=0)

        _away_wins  = game_data.get("away_team_record_wins", "0")
        _away_losses = game_data.get("away_team_record_losses", "0")
        _home_wins  = game_data.get("home_team_record_wins", "0")
        _home_losses = game_data.get("home_team_record_losses", "0")

        _draw_record(_away_wins, _away_losses, game_data.get("away_team_id"), start_y + 25)
        _draw_record(_home_wins, _home_losses, game_data.get("home_team_id"), start_y + 55)

        # Betting moneylines — right-aligned just left of each team's record
        _away_ml = game_data.get('away_ml')
        _home_ml = game_data.get('home_ml')
        if _away_ml is not None and _home_ml is not None:
            _away_rec_left = start_x + horizonta_len - int(font14.getlength(f'{_away_wins}-{_away_losses}')) - 5
            _home_rec_left = start_x + horizonta_len - int(font14.getlength(f'{_home_wins}-{_home_losses}')) - 5
            _odds_right = min(_away_rec_left, _home_rec_left) - 4

            def _ml_str(v):
                return f'+{v}' if v > 0 else str(v)

            _aml_s = _ml_str(_away_ml)
            _hml_s = _ml_str(_home_ml)
            _away_odds_y = start_y + (32 if use_logos else 25)
            _home_odds_y = start_y + (62 if use_logos else 55)
            draw.text((_odds_right - int(font11.getlength(_aml_s)), _away_odds_y), _aml_s, font=font11, fill=0)
            draw.text((_odds_right - int(font11.getlength(_hml_s)), _home_odds_y), _hml_s, font=font11, fill=0)

        _draw_weather_footer(draw, start_x, start_y, horizonta_len, game_data, font14)

    # ABS challenges remaining — small stacked dots to the left of each team's logo
    if game_data['detailed_state'] == 'In Progress':
        _draw_challenge_dots(draw, start_x, start_y, game_data, use_logos=use_logos, logo_x_offset=logo_x_offset)

    # horizontal line
    end_x = start_x + horizonta_len
    end_y = start_y
    draw.line((start_x, start_y, end_x, end_y), fill = 0)
    draw.line((start_x, start_y + 20, end_x, end_y  + 20), fill = 0)

    # Win probability bar — live games only, when show_win_prob enabled
    # Win prob bar — all In Progress states including between-inning breaks
    if show_win_prob and game_data['detailed_state'] == 'In Progress':
        away_wp = game_data.get('away_win_probability')
        home_wp = game_data.get('home_win_probability')
        if away_wp is not None and home_wp is not None:
            try:
                away_wp = float(away_wp)
                home_wp = float(home_wp)
                if away_wp + home_wp <= 1.5:
                    away_wp *= 100
                    home_wp *= 100
            except (ValueError, TypeError):
                away_wp, home_wp = 50.0, 50.0

            LOGO_SZ = 18
            BAR_Y = start_y + vertical_len + 21  # 1px below bottom border, in the inter-row gap
            BAR_H = 19                            # available inter-row height
            BAR_X = start_x + 1
            BAR_W = horizonta_len - 2

            # Ghost "LOSS" / "WIN" watermarks, then a solid horizontal center line
            _ghost_strip = Image.new('L', (BAR_W, BAR_H), 255)
            _ghost_draw = ImageDraw.Draw(_ghost_strip)
            _ghost_draw.text((1, (BAR_H - 18) // 2), 'LOSS', font=font18, fill=0)
            _win_w = int(font18.getlength('WIN'))
            _ghost_draw.text((BAR_W - _win_w - 1, (BAR_H - 18) // 2), 'WIN', font=font18, fill=0)
            _ghost_strip = _ghost_strip.point(lambda p: 255 if p > 180 else min(255, int(p * 0.35 + 155)))
            # Solid center line drawn after ghost transform so it stays black
            _ghost_draw.line((0, BAR_H // 2, BAR_W, BAR_H // 2), fill=0)
            Himage.paste(_ghost_strip.convert('1'), (BAR_X, BAR_Y))
            draw = ImageDraw.Draw(Himage)

            logo_y = BAR_Y + (BAR_H - LOGO_SZ) // 2  # center logo in strip

            away_px = BAR_X + int(BAR_W * away_wp / 100.0)
            away_logo_x = max(BAR_X, min(BAR_X + BAR_W - LOGO_SZ, away_px - LOGO_SZ // 2))

            home_px = BAR_X + int(BAR_W * home_wp / 100.0)
            home_logo_x = max(BAR_X, min(BAR_X + BAR_W - LOGO_SZ, home_px - LOGO_SZ // 2))

            # Prevent logos from overlapping each other
            MIN_SEP = LOGO_SZ + 1
            if away_logo_x > home_logo_x:
                if away_logo_x - home_logo_x < MIN_SEP:
                    mid = (away_logo_x + home_logo_x) // 2
                    away_logo_x = min(BAR_X + BAR_W - LOGO_SZ, mid + MIN_SEP // 2)
                    home_logo_x = max(BAR_X, mid - MIN_SEP // 2)
            else:
                if home_logo_x - away_logo_x < MIN_SEP:
                    mid = (away_logo_x + home_logo_x) // 2
                    home_logo_x = min(BAR_X + BAR_W - LOGO_SZ, mid + MIN_SEP // 2)
                    away_logo_x = max(BAR_X, mid - MIN_SEP // 2)

            if use_logos:
                away_logo = _logo_small(away_team_name, away_team_id, size=LOGO_SZ)
                home_logo = _logo_small(home_team_name, home_team_id, size=LOGO_SZ)
                if away_logo:
                    _paste_logo(Himage, away_logo, (away_logo_x, logo_y))
                if home_logo:
                    _paste_logo(Himage, home_logo, (home_logo_x, logo_y))

                # During inning breaks, draw each team's % in the AB area
                # directly above their logo position in the bar
            else:
                draw.line((away_px, BAR_Y, away_px, BAR_Y + BAR_H), fill=0)
                draw.line((home_px, BAR_Y, home_px, BAR_Y + BAR_H), fill=0)

    end_x = start_x + horizonta_len
    end_y = start_y + vertical_len + 20
    draw.line((start_x, start_y + vertical_len + 20, end_x, end_y), fill=0)
    
    
    # vertical line
    end_x = start_x
    end_y = start_y + vertical_len
    # draw.line((start_x, start_y, end_x, end_y), fill = 0)
    
    end_x = start_x + horizonta_len
    end_y = start_y + vertical_len
    # draw.line((start_x + horizonta_len , start_y, end_x, end_y), fill = 0)


    # line down the middle
    # vert_start_x =  start_x + horizonta_len / 2
    # vert_start_y = start_y + 12
    # end_x = vert_start_x
    # end_y = vert_start_y + 85
    
    # draw.line((vert_start_x, vert_start_y, end_x, end_y), fill = 0)
    

    # Show bases/outs/count only once the game is actually in progress (first pitch thrown)
    if game_data['detailed_state'] == 'In Progress':
        if _between_innings and _game_ending_state:
            pass  # End of 9th+ with a lead — linescore already shown, no next-batters panel
        elif _between_innings:
            # Next 3 batters (last names) + pitcher, right-aligned in the bases/outs space.
            # Prefer the batting-order-derived fields; fall back to linescore fields.
            _right_x = start_x + horizonta_len - 2
            _max_name_w = 46
            _batter_names = [
                _last_name(game_data.get('next_batter_1') or game_data.get('current_hitter') or ''),
                _last_name(game_data.get('next_batter_2') or game_data.get('due_up') or ''),
                _last_name(game_data.get('next_batter_3') or game_data.get('in_hole') or ''),
            ]
            _name_y = start_y + 21
            for _nm in _batter_names:
                if _nm:
                    _nm_disp = _nm
                    while _nm_disp and int(font14.getlength(_nm_disp)) > _max_name_w:
                        _nm_disp = _nm_disp[:-1]
                    _nw = int(font14.getlength(_nm_disp))
                    draw.text((_right_x - _nw, _name_y), _nm_disp, font=font14, fill=0)
                _name_y += 12
            _sep_y = _name_y + 5
            draw.line((start_x + 87, _sep_y, _right_x, _sep_y), fill=0)
            _pit_name = _last_name(game_data.get('next_pitcher') or game_data.get('current_pitcher') or '')
            _pit_max_w = horizonta_len - 2 - 87  # full panel width between innings (no diamond)
            if _pit_name:
                _pit_fnt = font14
                if int(font14.getlength(_pit_name)) > _pit_max_w:
                    _pit_fnt = font11
                    if int(font11.getlength(_pit_name)) > _pit_max_w:
                        _pit_fnt = font9
                        while _pit_name and int(font9.getlength(_pit_name)) > _pit_max_w:
                            _pit_name = _pit_name[:-1]
                _pit_w = int(_pit_fnt.getlength(_pit_name))
                draw.text((_right_x - _pit_w, _sep_y + 2), _pit_name, font=_pit_fnt, fill=0)
        else:
            _hi_third = isinstance(game_data['runner_on_third'], str)
            _hi_second = isinstance(game_data['runner_on_second'], str)
            _hi_first = isinstance(game_data['runner_on_first'], str)

            Himage = draw_diamond(Himage, (start_x + 97,  start_y + 52), 10, _hi_third)
            Himage = draw_diamond(Himage, (start_x + 109, start_y + 40), 10, _hi_second)
            Himage = draw_diamond(Himage, (start_x + 121, start_y + 52), 10, _hi_first)
            draw = ImageDraw.Draw(Himage)
            for _bfill, _bcx, _bcy, _bkey in (
                (_hi_third,  start_x + 97,  start_y + 52, 'runner_third_number'),
                (_hi_second, start_x + 109, start_y + 40, 'runner_second_number'),
                (_hi_first,  start_x + 121, start_y + 52, 'runner_first_number'),
            ):
                if _bfill:
                    _raw = game_data.get(_bkey)
                    _bnum = str(_raw) if _raw is not None else ''
                    _bnw = int(font9.getlength(_bnum)) if _bnum else 0
                    draw.text((_bcx - _bnw // 2, _bcy - 5), _bnum, font=font9, fill=255)

            outs_list = [None] * 3
            for i in range(1, 4):
                outs_list[i-1] = i <= game_data['num_of_outs']
            Himage = draw_circle(Himage, (start_x + 97,  start_y + 73), 5, outs_list[0])
            Himage = draw_circle(Himage, (start_x + 109, start_y + 73), 5, outs_list[1])
            Himage = draw_circle(Himage, (start_x + 121, start_y + 73), 5, outs_list[2])

            balls_list = [None] * 4
            for i in range(1, 4):
                balls_list[i-1] = i <= game_data['balls']

            draw.text((start_x + 2, start_y + 25 + 59), 'B', font=font14, fill=0)
            Himage = draw_circle(Himage, (start_x + 19, start_y + 25 + 68), 4, balls_list[0])
            Himage = draw_circle(Himage, (start_x + 31, start_y + 25 + 68), 4, balls_list[1])
            Himage = draw_circle(Himage, (start_x + 43, start_y + 25 + 68), 4, balls_list[2])

            _num_strikes = game_data.get('strikes') or 0
            strikes_list = [i + 1 <= _num_strikes for i in range(2)]
            _strike_calls = game_data.get('strike_calls', [])

            draw.text((start_x + 19 + 39, start_y + 25 + 59), 'S', font=font14, fill=0)
            for _si, (_scx, _scy) in enumerate([
                (start_x + 19 + 55, start_y + 25 + 68),
                (start_x + 31 + 55, start_y + 25 + 68),
            ]):
                _call = _strike_calls[_si] if _si < len(_strike_calls) else None
                if strikes_list[_si] and _call in ('S', 'F'):
                    # Swinging or foul: outline ring with filled center dot
                    Himage = draw_circle(Himage, (_scx, _scy), 4, False)
                    draw = ImageDraw.Draw(Himage)
                    draw.ellipse([_scx - 2, _scy - 2, _scx + 2, _scy + 2], fill='black', outline='black')
                else:
                    # Looking / empty: solid filled circle
                    Himage = draw_circle(Himage, (_scx, _scy), 4, strikes_list[_si])
                    draw = ImageDraw.Draw(Himage)

        if game_data.get('save_situation') and not _between_innings:
            _sv_w = int(font9.getlength('SV'))
            _sv_x = start_x + horizonta_len - _sv_w - 2
            draw.text((_sv_x,     start_y + 25), 'SV', font=font9, fill=0)
            draw.text((_sv_x + 1, start_y + 25), 'SV', font=font9, fill=0)
    else:

        # Perfect game takes precedence over no-hitter display — right-aligned in header
        if game_data.get('perfect_game') or game_data.get('no_hitter'):
            _nh_label = 'Perfect Game' if game_data.get('perfect_game') else 'No-Hitter'
            _nh_lw = int(font14.getlength(_nh_label))
            _nh_lx = (_ser_content_left_x - 2) - _nh_lw
            draw.text((_nh_lx,     start_y + 3), _nh_label, font=font14, fill=0)
            draw.text((_nh_lx + 1, start_y + 3), _nh_label, font=font14, fill=0)

        


    # Team names / logos
    _LOGO_SIZE = 28  # matches _logo_small default size
    if use_logos:
        away_logo = _logo_small(away_team_name, away_team_id)
        home_logo = _logo_small(home_team_name, home_team_id)
        if away_logo:
            lw, lh = away_logo.size
            lx = start_x + logo_x_offset + (_LOGO_SIZE - lw) // 2
            ly = start_y + 25 + (_LOGO_SIZE - lh) // 2
            _paste_logo(Himage, away_logo, (lx, ly))
            abbr_x = start_x + logo_x_offset + _LOGO_SIZE + 2
            abbr_y = start_y + 25 + (_LOGO_SIZE - 14) // 2
            draw.text((abbr_x, abbr_y), away_team_name, font=font14, fill=0)
            draw.text((abbr_x + 1, abbr_y), away_team_name, font=font14, fill=0)
        else:
            draw.text((start_x + 5, start_y + 25), away_team_name, font=font24, fill=0)
        if home_logo:
            lw, lh = home_logo.size
            lx = start_x + logo_x_offset + (_LOGO_SIZE - lw) // 2
            ly = start_y + 55 + (_LOGO_SIZE - lh) // 2
            _paste_logo(Himage, home_logo, (lx, ly))
            abbr_x = start_x + logo_x_offset + _LOGO_SIZE + 2
            abbr_y = start_y + 55 + (_LOGO_SIZE - 14) // 2
            draw.text((abbr_x, abbr_y), home_team_name, font=font14, fill=0)
            draw.text((abbr_x + 1, abbr_y), home_team_name, font=font14, fill=0)
        else:
            draw.text((start_x + 5, start_y + 55), home_team_name, font=font24, fill=0)
    else:
        draw.text((start_x + 5, start_y + 25), away_team_name, font=font24, fill=0)
        draw.text((start_x + 5, start_y + 55), home_team_name, font=font24, fill=0)
        # Bold-offset re-draw to emphasise winner name (text mode only)
        if game_data.get('away_team_is_winner'):
            draw.text((start_x + 7, start_y + 25), away_team_name, font=font24, fill=0)
        if game_data.get('home_team_is_winner'):
            draw.text((start_x + 7, start_y + 55), home_team_name, font=font24, fill=0)

    # Bold-offset score for winner (both modes)
    if game_data.get('away_team_is_winner'):
        draw.text((start_x + 67 + check_if_two_chars(away_runs), start_y + 25), away_runs, font=font24, fill=0)
    if game_data.get('home_team_is_winner'):
        draw.text((start_x + 67 + check_if_two_chars(home_runs), start_y + 55), home_runs, font=font24, fill=0)

    # Invert header to indicate a score change during an active game
    if score_changed and is_game_started and not is_game_finished:
        header_box = Himage.crop((start_x, start_y, start_x + horizonta_len + 1, start_y + 21))
        Himage.paste(ImageOps.invert(header_box.convert('L')).convert('1'), (start_x, start_y))

    # Invert header for special states: walk-off, no-hitter, perfect game
    if (is_game_finished and game_data.get('walk_off')) or \
       ((game_data.get('no_hitter') or game_data.get('perfect_game')) and
        (is_game_finished or _active_no_no)):
        header_box = Himage.crop((start_x, start_y, start_x + horizonta_len + 1, start_y + 21))
        Himage.paste(ImageOps.invert(header_box.convert('L')).convert('1'), (start_x, start_y))

    return Himage


def draw_out_of_town_score_board(Himage, game_state_data, team_data, date_str=None, changed_game_ids=None, use_logos=False, logo_x_offset=2, show_win_prob=False):

    draw = ImageDraw.Draw(Himage)

    # --- Date label: centered in the top strip, as large as possible, bold ---
    if date_str:
        from datetime import datetime as _dt
        try:
            _d = _dt.strptime(date_str, '%Y-%m-%d')
            _label = _d.strftime('%B %-d, %Y')
        except (ValueError, AttributeError):
            _label = date_str
        _font_date = _get_font(24)
        _lw = int(_font_date.getlength(_label))
        _lx = (800 - _lw) // 2
        _ly = max(0, (_WC_STRIP_H - 24) // 2)
        draw.text((_lx,     _ly), _label, font=_font_date, fill=0)
        draw.text((_lx + 1, _ly), _label, font=_font_date, fill=0)  # bold stroke

    x_start = 32
    y_start = 30

    # Reorder games so the primary team's game appears first in the grid
    config = load_yaml_file('config.yaml')
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



def  orchestrate_score_board(game_state_data, team_data, date_str=None, bypass_cache=False):
    """Returns (image, changed_regions) or None if nothing changed.

    changed_regions is a list of (x, y, w, h) tuples for partial refresh.
    An empty list signals that a full refresh should be used.

    bypass_cache=True skips the unchanged-image check and state persistence.
    Use this when generating GIFs or rendering historical snapshots.
    """
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

        if compare_json_dicts_sorted(new_dict, old_dict):
            print('images the same')
            return None

    print('image is different')
    Himage = Image.new('1', (800, 480), 255)
    Himage = draw_out_of_town_score_board(Himage, game_state_data, team_data, date_str, changed_game_ids=changed_game_ids, use_logos=use_logos, logo_x_offset=logo_x_offset, show_win_prob=show_win_prob)

    standings_data = None
    if config.get('show_wildcard_standings', False) or config.get('show_standings_sidebar', False):
        standings_data = load_json_file('standings.json')

    if config.get('show_wildcard_standings', False):
        if standings_data and 'standings' in standings_data:
            wildcard_data = derive_wildcard_from_standings(standings_data)
            Himage = draw_wildcard_header(Himage, wildcard_data)

    if config.get('show_standings_sidebar', False):
        if standings_data and 'standings' in standings_data:
            Himage = draw_standings_sidebar(Himage, standings_data, team_data, side='left')
            Himage = draw_standings_sidebar(Himage, standings_data, team_data, side='right')

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
    

