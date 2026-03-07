"""
Discord bot for controlling the MLB e-ink display.

Commands (prefix: !display):
  !display team <ABBR>   — change the primary team (e.g. !display team NYY)
  !display mode <MODE>   — change display mode: scoreboard|linescore|field|scorecard|pitch
  !display status        — show current settings

Run: python3 src/discord_bot.py
The bot writes pending changes to data/discord_state.json.
The display script reads and applies them on its next scheduled run.
"""

import discord
from discord.ext import commands
import json
import os
import sys
from datetime import datetime

# Resolve paths relative to this file
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_SRC_DIR)
sys.path.insert(0, _SRC_DIR)

from util import load_yaml_file

VALID_MODES = ('scoreboard', 'linescore', 'field', 'scorecard', 'pitch')


def _data_path(filename):
    return os.path.join(_BASE_DIR, 'data', filename)


def _load_config():
    return load_yaml_file('config.yaml')


def _save_discord_state(state):
    path = _data_path('discord_state.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(state, f, indent=2)


def _get_display_image_path():
    """Return path to the current display image (BMP → converted to PNG for Discord)."""
    bmp = os.path.join(_BASE_DIR, 'resulting_image.bmp')
    png = os.path.join(_BASE_DIR, 'data', 'discord_preview.png')
    if os.path.exists(bmp):
        try:
            from PIL import Image
            img = Image.open(bmp).convert('RGB')
            os.makedirs(os.path.dirname(png), exist_ok=True)
            img.save(png)
            return png
        except Exception:
            pass
    return None


async def _post_display_image(ctx):
    """Post the current display image as a PNG to the channel."""
    img_path = _get_display_image_path()
    if img_path and os.path.exists(img_path):
        await ctx.send(file=discord.File(img_path, filename='display.png'))


def _current_settings():
    config = _load_config()
    mode = config.get('display_mode') or ('scoreboard' if config.get('scoreboard', True) else 'linescore')
    team = config.get('primary', 'N/A')
    return mode, team


# ---- Bot setup ----

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!display ', intents=intents, help_command=None)


@bot.event
async def on_ready():
    print(f'MLB Display bot ready as {bot.user}')


@bot.command(name='team')
async def cmd_team(ctx, abbr: str = None):
    """Change the primary team. Usage: !display team NYY"""
    if not abbr:
        await ctx.send('Usage: `!display team <ABBR>` (e.g. `!display team NYY`)')
        return

    abbr = abbr.upper()
    config = _load_config()
    allowed_channel = config.get('discord_channel_id')
    if allowed_channel and ctx.channel.id != int(allowed_channel):
        return

    state = {
        'pending_mode': None,
        'pending_team': abbr,
        'requested_by': str(ctx.author.name),
        'timestamp': datetime.now().isoformat(timespec='seconds'),
        'applied': False,
    }
    _save_discord_state(state)
    await ctx.send(f'Got it @{ctx.author.name} — switching to team **{abbr}** on next refresh.')
    await _post_display_image(ctx)


@bot.command(name='mode')
async def cmd_mode(ctx, mode: str = None):
    """Change display mode. Usage: !display mode field"""
    if not mode or mode.lower() not in VALID_MODES:
        await ctx.send(f'Usage: `!display mode <mode>` — valid modes: {", ".join(VALID_MODES)}')
        return

    mode = mode.lower()
    config = _load_config()
    allowed_channel = config.get('discord_channel_id')
    if allowed_channel and ctx.channel.id != int(allowed_channel):
        return

    state = {
        'pending_mode': mode,
        'pending_team': None,
        'requested_by': str(ctx.author.name),
        'timestamp': datetime.now().isoformat(timespec='seconds'),
        'applied': False,
    }
    _save_discord_state(state)
    await ctx.send(f'Got it @{ctx.author.name} — switching to **{mode}** mode on next refresh.')
    await _post_display_image(ctx)


@bot.command(name='status')
async def cmd_status(ctx):
    """Show current display settings. Usage: !display status"""
    config = _load_config()
    allowed_channel = config.get('discord_channel_id')
    if allowed_channel and ctx.channel.id != int(allowed_channel):
        return

    mode, team = _current_settings()

    # Check for pending change
    pending = ''
    path = _data_path('discord_state.json')
    if os.path.exists(path):
        try:
            with open(path) as f:
                ds = json.load(f)
            if not ds.get('applied', True):
                parts = []
                if ds.get('pending_mode'):
                    parts.append(f"mode→{ds['pending_mode']}")
                if ds.get('pending_team'):
                    parts.append(f"team→{ds['pending_team']}")
                by = ds.get('requested_by', '?')
                pending = f'\n⏳ Pending change by @{by}: {", ".join(parts)}'
        except Exception:
            pass

    await ctx.send(
        f'**MLB Display Status**\n'
        f'Mode: `{mode}`\n'
        f'Team: `{team}`{pending}'
    )


@bot.command(name='help')
async def cmd_help(ctx):
    """Show help. Usage: !display help"""
    await ctx.send(
        '**MLB Display Commands**\n'
        '`!display team <ABBR>` — change primary team (e.g. `!display team NYY`)\n'
        f'`!display mode <mode>` — change display mode. Options: {", ".join(VALID_MODES)}\n'
        '`!display status` — show current settings\n'
        '`!display help` — show this message'
    )


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f'Unknown command. Try `!display help`.')
    else:
        print(f'Command error: {error}')


def main():
    os.chdir(_BASE_DIR)
    config = _load_config()
    token = config.get('discord_token', '')
    if not token:
        print('Error: discord_token not set in config/config.yaml')
        sys.exit(1)
    bot.run(token)


if __name__ == '__main__':
    main()
