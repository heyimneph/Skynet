import os
import discord
import logging

from datetime import datetime
from discord.ext import commands
from dotenv import load_dotenv

from discord.ext.commands import is_owner, Context


# Loads the .env file that resides on the same level as the script
load_dotenv("config.env.txt")

# Grab API tokens from the .env file and other things
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD')
OPENAI_MODERATION_KEY = os.getenv('OPENAI_MODERATION_KEY')
VIRUS_TOTAL_API = os.getenv('VIRUS_TOTAL_API')


# Discord
DISCORD_PREFIX = "%"

# Other External Keys
LAUNCH_TIME = datetime.utcnow()


# Login Clients
intents = discord.Intents.all()
intents.message_content = True

# Ensure the logs directory exists
os.makedirs('data', exist_ok=True)
os.makedirs('data/logs', exist_ok=True)
os.makedirs('data/databases', exist_ok=True)


# Setting up logging before anything else
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger('discord')
handler = logging.FileHandler(filename='data/logs/discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

client = commands.Bot(command_prefix=DISCORD_PREFIX, intents=intents, help_command=None,
                      activity=discord.Activity(type=discord.ActivityType.watching, name="you"))


async def perform_sync():
    synced = await client.tree.sync()
    return len(synced)

@client.command()
@is_owner()
async def sync(ctx: Context) -> None:
    synced = await client.tree.sync()
    await ctx.reply("{} commands synced".format(len(synced)))
