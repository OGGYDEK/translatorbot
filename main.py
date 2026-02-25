import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
import asyncio

# Load .env file if present (for local development)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- Configuration ---
TOKEN = os.environ.get('DISCORD_TOKEN', '')  # Set via environment variable
TRANSLATE_API_URL = 'https://api.mymemory.translated.net/get'

# --- Flag Emoji to Language Code Mapping ---
FLAG_TO_LANG = {
    '\U0001f1fa\U0001f1f8': 'en',  # 🇺🇸 USA → English
    '\U0001f1ec\U0001f1e7': 'en',  # 🇬🇧 UK → English
    '\U0001f1e6\U0001f1fa': 'en',  # 🇦🇺 Australia → English
    '\U0001f1f7\U0001f1fa': 'ru',  # 🇷🇺 Russia → Russian
    '\U0001f1e8\U0001f1f3': 'zh',  # 🇨🇳 China → Chinese
}

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- Helper Functions ---
async def translate_text(text, target_lang, source_lang='en'):
    """Sends text to MyMemory Translation API (free, no hosting needed)."""
    params = {
        'q': text,
        'langpair': f'{source_lang}|{target_lang}'
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(TRANSLATE_API_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('responseStatus') == 200:
                        return data['responseData']['translatedText']
                    else:
                        return f"Error: Translation failed ({data.get('responseDetails', 'Unknown error')})"
                else:
                    return f"Error: Translation API returned status {response.status}"
    except asyncio.TimeoutError:
        return "Error: Translation request timed out"
    except Exception as e:
        return f"Error: Could not connect to translation service ({str(e)})"

# --- Prefix Commands ---
@bot.command()
async def translate(ctx, target_lang: str, *, text: str = None):
    """Translates text. If text is missing, checks for a reply."""

    # Handle reply logic
    if text is None:
        if ctx.message.reference:
            replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            text = replied_message.content
        else:
            await ctx.send("Usage: `!translate [target_lang] [text]` or reply to a message with `!translate [target_lang]`")
            return

    # Perform translation
    async with ctx.typing():
        result = await translate_text(text, target_lang)
        await ctx.send(f"**Translated ({target_lang}):** {result}")

# --- Slash Commands ---
@bot.tree.command(name='translate', description='Translate text to another language')
@app_commands.describe(
    target_lang='Target language code (e.g. fr, es, de, ja, hi)',
    text='The text to translate'
)
async def slash_translate(interaction: discord.Interaction, target_lang: str, text: str):
    """Slash command: /translate"""
    await interaction.response.defer()
    result = await translate_text(text, target_lang)
    embed = discord.Embed(
        title=f"Translation → {target_lang.upper()}",
        description=result,
        color=discord.Color.blurple()
    )
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")
    await interaction.followup.send(embed=embed)

# --- Context Menu: Right-click → Translate ---
@bot.tree.context_menu(name='Translate to English')
async def translate_context_menu(interaction: discord.Interaction, message: discord.Message):
    """Right-click a message → Apps → Translate to English"""
    if not message.content:
        await interaction.response.send_message("This message has no text to translate.", ephemeral=True)
        return

    await interaction.response.defer()
    result = await translate_text(message.content, 'en')
    embed = discord.Embed(
        title="Translation → EN",
        description=result,
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Original by {message.author.display_name} • Translated by {interaction.user.display_name}")
    await interaction.followup.send(embed=embed)

# --- Flag Reaction Handler ---
@bot.event
async def on_raw_reaction_add(payload):
    """Translates a message when a flag emoji reaction is added."""
    if payload.user_id == bot.user.id:
        return

    emoji_str = str(payload.emoji)
    target_lang = FLAG_TO_LANG.get(emoji_str)

    if not target_lang:
        return

    channel = bot.get_channel(payload.channel_id)
    if not channel:
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.NotFound:
        return

    if not message.content:
        return

    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
    member = payload.member or (guild.get_member(payload.user_id) if guild else None)

    result = await translate_text(message.content, target_lang)
    if result and not result.startswith('Error'):
        lang_name = target_lang.upper()
        embed = discord.Embed(
            description=result,
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"Translated to {lang_name} • Reacted by {member.display_name if member else 'Unknown'}")
        await message.reply(embed=embed, mention_author=False)
    elif result:
        await channel.send(result, delete_after=10)

# --- Health Check Server (for Render free Web Service) ---
from aiohttp import web

async def health_handler(request):
    return web.Response(text="Luspa bot is running!")

async def start_health_server():
    app = web.Application()
    app.router.add_get('/', health_handler)
    port = int(os.environ.get('PORT', 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f'Health server running on port {port}')

# --- Bot Events ---
@bot.event
async def on_ready():
    bot.loop.create_task(start_health_server())
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} slash command(s).')
    except Exception as e:
        print(f'Failed to sync commands: {e}')
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print(f'Flag reaction translation active for {len(FLAG_TO_LANG)} flags.')
    print('Unlimited translations enabled.')

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You don't have permission to use this command.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Invalid argument.")
    else:
        print(f"Error: {error}")

if __name__ == '__main__':
    bot.run(TOKEN)
