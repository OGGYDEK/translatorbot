import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
import aiosqlite
import datetime
import json
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
DB_NAME = 'translator_bot.db'
DAILY_LIMIT = 10

# --- Flag Emoji to Language Code Mapping ---
# Regional indicator pairs map to ISO 639-1 codes supported by LibreTranslate
FLAG_TO_LANG = {
    '\U0001f1fa\U0001f1f8': 'en',  # 🇸 USA → English
    '\U0001f1ec\U0001f1e7': 'en',  # � UK → English
    '\U0001f1e6\U0001f1fa': 'en',  # �� Australia → English
    '\U0001f1f7\U0001f1fa': 'ru',  # 🇷🇺 Russia → Russian
    '\U0001f1e8\U0001f1f3': 'zh',  # �� China → Chinese
}

# --- Database Initialization ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Table for usage tracking
        await db.execute('''
            CREATE TABLE IF NOT EXISTS usage (
                user_id INTEGER PRIMARY KEY,
                message_count INTEGER DEFAULT 0,
                last_reset TIMESTAMP
            )
        ''')
        # Table for whitelisted channels
        await db.execute('''
            CREATE TABLE IF NOT EXISTS whitelisted_channels (
                channel_id INTEGER PRIMARY KEY
            )
        ''')
        # Table for whitelisted roles
        await db.execute('''
            CREATE TABLE IF NOT EXISTS whitelisted_roles (
                role_id INTEGER PRIMARY KEY
            )
        ''')
        await db.commit()

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- Helper Functions ---
async def check_and_update_limit(user_id, channel_id, roles):
    """Checks if the user can translate and updates their usage."""
    async with aiosqlite.connect(DB_NAME) as db:
        # Check if channel is whitelisted
        async with db.execute('SELECT 1 FROM whitelisted_channels WHERE channel_id = ?', (channel_id,)) as cursor:
            if await cursor.fetchone():
                return True
        
        # Check if any role is whitelisted
        role_ids = [role.id for role in roles]
        placeholders = ', '.join(['?'] * len(role_ids))
        if role_ids:
            async with db.execute(f'SELECT 1 FROM whitelisted_roles WHERE role_id IN ({placeholders})', role_ids) as cursor:
                if await cursor.fetchone():
                    return True

        # Check user usage
        now = datetime.datetime.now()
        async with db.execute('SELECT message_count, last_reset FROM usage WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            
            if row:
                count, last_reset_str = row
                last_reset = datetime.datetime.fromisoformat(last_reset_str)
                
                # Reset if 24 hours have passed
                if now - last_reset > datetime.timedelta(days=1):
                    await db.execute('UPDATE usage SET message_count = 1, last_reset = ? WHERE user_id = ?', (now.isoformat(), user_id))
                    await db.commit()
                    return True
                
                if count < DAILY_LIMIT:
                    await db.execute('UPDATE usage SET message_count = message_count + 1 WHERE user_id = ?', (user_id,))
                    await db.commit()
                    return True
                else:
                    return False
            else:
                # First time user
                await db.execute('INSERT INTO usage (user_id, message_count, last_reset) VALUES (?, 1, ?)', (user_id, now.isoformat()))
                await db.commit()
                return True

async def translate_text(text, target_lang):
    """Sends text to MyMemory Translation API (free, no hosting needed)."""
    params = {
        'q': text,
        'langpair': f'autodetect|{target_lang}'
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

    # Check limit
    if not await check_and_update_limit(ctx.author.id, ctx.channel.id, ctx.author.roles):
        await ctx.send("Daily limit reached. Try again tomorrow or contact an admin.")
        return

    # Perform translation
    async with ctx.typing():
        result = await translate_text(text, target_lang)
        await ctx.send(f"**Translated ({target_lang}):** {result}")

@bot.command()
@commands.has_permissions(administrator=True)
async def botfree(ctx, target: discord.abc.Snowflake):
    """Whitelists a channel or role."""
    async with aiosqlite.connect(DB_NAME) as db:
        if isinstance(target, discord.TextChannel):
            await db.execute('INSERT OR IGNORE INTO whitelisted_channels (channel_id) VALUES (?)', (target.id,))
            await ctx.send(f"Channel {target.mention} is now whitelisted (unlimited translations).")
        elif isinstance(target, discord.Role):
            await db.execute('INSERT OR IGNORE INTO whitelisted_roles (role_id) VALUES (?)', (target.id,))
            await ctx.send(f"Role **{target.name}** is now whitelisted (unlimited translations).")
        else:
            await ctx.send("Please mention a #channel or @role.")
        await db.commit()

@bot.command()
@commands.has_permissions(administrator=True)
async def botrestrict(ctx, target: discord.abc.Snowflake):
    """Removes a channel or role from the whitelist."""
    async with aiosqlite.connect(DB_NAME) as db:
        if isinstance(target, discord.TextChannel):
            await db.execute('DELETE FROM whitelisted_channels WHERE channel_id = ?', (target.id,))
            await ctx.send(f"Channel {target.mention} restriction restored.")
        elif isinstance(target, discord.Role):
            await db.execute('DELETE FROM whitelisted_roles WHERE role_id = ?', (target.id,))
            await ctx.send(f"Role **{target.name}** restriction restored.")
        else:
            await ctx.send("Please mention a #channel or @role.")
        await db.commit()

# --- Slash Commands ---
@bot.tree.command(name='translate', description='Translate text to another language')
@app_commands.describe(
    target_lang='Target language code (e.g. fr, es, de, ja, hi)',
    text='The text to translate'
)
async def slash_translate(interaction: discord.Interaction, target_lang: str, text: str):
    """Slash command: /translate"""
    if not await check_and_update_limit(interaction.user.id, interaction.channel_id, interaction.user.roles):
        await interaction.response.send_message(
            "Daily limit reached. Try again tomorrow or contact an admin.",
            ephemeral=True
        )
        return

    await interaction.response.defer()
    result = await translate_text(text, target_lang)
    embed = discord.Embed(
        title=f"Translation → {target_lang.upper()}",
        description=result,
        color=discord.Color.blurple()
    )
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name='botfree', description='Whitelist a channel or role for unlimited translations (Admin only)')
@app_commands.describe(channel='Channel to whitelist', role='Role to whitelist')
@app_commands.default_permissions(administrator=True)
async def slash_botfree(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None,
    role: discord.Role = None
):
    """Slash command: /botfree"""
    if not channel and not role:
        await interaction.response.send_message("Please specify a channel or role.", ephemeral=True)
        return

    async with aiosqlite.connect(DB_NAME) as db:
        messages = []
        if channel:
            await db.execute('INSERT OR IGNORE INTO whitelisted_channels (channel_id) VALUES (?)', (channel.id,))
            messages.append(f"Channel {channel.mention} is now whitelisted.")
        if role:
            await db.execute('INSERT OR IGNORE INTO whitelisted_roles (role_id) VALUES (?)', (role.id,))
            messages.append(f"Role **{role.name}** is now whitelisted.")
        await db.commit()
    await interaction.response.send_message('\n'.join(messages))

@bot.tree.command(name='botrestrict', description='Remove a channel or role from the whitelist (Admin only)')
@app_commands.describe(channel='Channel to restrict', role='Role to restrict')
@app_commands.default_permissions(administrator=True)
async def slash_botrestrict(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None,
    role: discord.Role = None
):
    """Slash command: /botrestrict"""
    if not channel and not role:
        await interaction.response.send_message("Please specify a channel or role.", ephemeral=True)
        return

    async with aiosqlite.connect(DB_NAME) as db:
        messages = []
        if channel:
            await db.execute('DELETE FROM whitelisted_channels WHERE channel_id = ?', (channel.id,))
            messages.append(f"Channel {channel.mention} restriction restored.")
        if role:
            await db.execute('DELETE FROM whitelisted_roles WHERE role_id = ?', (role.id,))
            messages.append(f"Role **{role.name}** restriction restored.")
        await db.commit()
    await interaction.response.send_message('\n'.join(messages))

# --- Context Menu: Right-click → Translate ---
@bot.tree.context_menu(name='Translate to English')
async def translate_context_menu(interaction: discord.Interaction, message: discord.Message):
    """Right-click a message → Apps → Translate to English"""
    if not message.content:
        await interaction.response.send_message("This message has no text to translate.", ephemeral=True)
        return

    if not await check_and_update_limit(interaction.user.id, interaction.channel_id, interaction.user.roles):
        await interaction.response.send_message(
            "Daily limit reached. Try again tomorrow or contact an admin.",
            ephemeral=True
        )
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
    # Ignore bot's own reactions
    if payload.user_id == bot.user.id:
        return

    emoji_str = str(payload.emoji)
    target_lang = FLAG_TO_LANG.get(emoji_str)

    if not target_lang:
        return  # Not a recognized flag emoji

    channel = bot.get_channel(payload.channel_id)
    if not channel:
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.NotFound:
        return

    if not message.content:
        return  # Nothing to translate (image-only, embed, etc.)

    # Get the user who reacted for limit checking
    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
    member = payload.member or (guild.get_member(payload.user_id) if guild else None)

    if member and guild:
        if not await check_and_update_limit(member.id, channel.id, member.roles):
            await channel.send(
                f"{member.mention} Daily limit reached. Try again tomorrow or contact an admin.",
                delete_after=10
            )
            return

    # Translate and reply
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
    await init_db()
    # Start health check server for Render
    bot.loop.create_task(start_health_server())
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} slash command(s).')
    except Exception as e:
        print(f'Failed to sync commands: {e}')
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('Database initialized.')
    print(f'Flag reaction translation active for {len(FLAG_TO_LANG)} flags.')

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You don't have permission to use this command.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Invalid argument. Please mention a valid channel or role.")
    else:
        print(f"Error: {error}")

if __name__ == '__main__':
    bot.run(TOKEN)

