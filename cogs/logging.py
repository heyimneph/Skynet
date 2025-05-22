import datetime
import discord
import logging
import aiosqlite
import os
from discord.ext import commands
from logging.handlers import RotatingFileHandler

# ---------------------------------------------------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------------------------------------------------

db_path = './data/databases/filter.db'

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------------------------------
# Log Class
# ---------------------------------------------------------------------------------------------------------------------

class LogsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------------------------------------------------------------------------------------------------------------------
    # Logging Functions
    # ---------------------------------------------------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member):
        try:
            async with aiosqlite.connect(db_path) as conn:
                async with conn.execute('SELECT log_channel_id FROM config WHERE guild_id = ?', (member.guild.id,)) as cursor:
                    result = await cursor.fetchone()
            if result:
                log_channel_id = result[0]
                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel:
                    embed = discord.Embed(
                        description="Action: `Member Joined`",
                        color=discord.Color.blue()
                    )
                    embed.add_field(name="User", value=member.mention, inline=True)
                    embed.add_field(name="Guild ID", value=str(member.guild.id), inline=True)
                    embed.set_footer(text=f"User ID: {member.id}")
                    embed.set_author(name=str(member), icon_url=member.display_avatar.url)
                    embed.timestamp = discord.utils.utcnow()

                    await log_channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Error logging member join: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        try:
            async with aiosqlite.connect(db_path) as conn:
                async with conn.execute('SELECT log_channel_id FROM config WHERE guild_id = ?', (member.guild.id,)) as cursor:
                    result = await cursor.fetchone()
            if result:
                log_channel_id = result[0]
                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel:
                    embed = discord.Embed(
                        description="Action: `Member Left`",
                        color=discord.Color.blue()
                    )
                    embed.add_field(name="User", value=member.mention, inline=True)
                    embed.add_field(name="Guild ID", value=str(member.guild.id), inline=True)
                    embed.set_footer(text=f"User ID: {member.id}")
                    embed.set_author(name=str(member), icon_url=member.display_avatar.url)
                    embed.timestamp = discord.utils.utcnow()

                    await log_channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Error logging member leave: {e}")

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        try:
            if before.content == after.content:
                return

            async with aiosqlite.connect(db_path) as conn:
                async with conn.execute('SELECT log_channel_id FROM config WHERE guild_id = ?', (before.guild.id,)) as cursor:
                    result = await cursor.fetchone()
            if result:
                log_channel_id = result[0]
                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel:
                    embed = discord.Embed(
                        description="Action: `Message Edited`",
                        color=discord.Color.blue()
                    )
                    embed.add_field(name="User", value=before.author.mention, inline=True)
                    embed.add_field(name="Channel", value=before.channel.mention, inline=True)
                    embed.add_field(name="Before", value=f"*{before.content}*", inline=False)
                    embed.add_field(name="After", value=f"*{after.content}*", inline=False)
                    embed.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
                    embed.set_footer(text=f"User ID: {before.author.id}")
                    embed.timestamp = discord.utils.utcnow()

                    await log_channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in on_message_edit event: {e}")

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        try:
            async with aiosqlite.connect(db_path) as conn:
                async with conn.execute('SELECT log_channel_id FROM config WHERE guild_id = ?', (message.guild.id,)) as cursor:
                    result = await cursor.fetchone()
            if result:
                log_channel_id = result[0]
                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel:
                    embed = discord.Embed(
                        description="Action: `Message Deleted`",
                        color=discord.Color.red()
                    )
                    embed.add_field(name="User", value=message.author.mention, inline=True)
                    embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                    embed.add_field(name="Content", value=f"*{message.content}*" or "*Content not available*", inline=False)
                    embed.set_footer(text=f"User ID: {message.author.id}")
                    embed.timestamp = discord.utils.utcnow()

                    await log_channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in on_message_delete event: {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        try:
            async with aiosqlite.connect(db_path) as conn:
                async with conn.execute('SELECT log_channel_id FROM config WHERE guild_id = ?', (member.guild.id,)) as cursor:
                    result = await cursor.fetchone()
            if result:
                log_channel_id = result[0]
                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel:
                    action_description = "Action: `Voice State Updated`"
                    if before.channel is None and after.channel is not None:
                        action_description = "Action: `Joined Voice Channel`"
                    elif before.channel is not None and after.channel is None:
                        action_description = "Action: `Left Voice Channel`"
                    elif before.channel != after.channel:
                        action_description = "Action: `Moved Voice Channels`"

                    embed = discord.Embed(
                        description=action_description,
                        color=discord.Color.green() if after.channel else discord.Color.red()
                    )
                    embed.add_field(name="User", value=member.mention, inline=False)
                    if before.channel:
                        embed.add_field(name="From", value=before.channel.mention, inline=True)
                    if after.channel:
                        embed.add_field(name="To", value=after.channel.mention, inline=True)
                    embed.set_author(name=str(member), icon_url=member.display_avatar.url)
                    embed.set_footer(text=f"User ID: {member.id}")
                    embed.timestamp = discord.utils.utcnow()
                    await log_channel.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in on_voice_state_update event: {e}")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        try:
            async with aiosqlite.connect(db_path) as conn:
                async with conn.execute('SELECT log_channel_id FROM config WHERE guild_id = ?', (channel.guild.id,)) as cursor:
                    result = await cursor.fetchone()
            if result:
                log_channel_id = result[0]
                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel:
                    embed = discord.Embed(
                        description="Action: `Channel Created`",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="Channel", value=channel.mention, inline=True)
                    embed.add_field(name="Type", value=str(channel.type), inline=True)
                    embed.set_footer(text=f"Channel ID: {channel.id}")
                    embed.timestamp = discord.utils.utcnow()

                    await log_channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in on_guild_channel_create event: {e}")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        try:
            async with aiosqlite.connect(db_path) as conn:
                async with conn.execute('SELECT log_channel_id FROM config WHERE guild_id = ?', (channel.guild.id,)) as cursor:
                    result = await cursor.fetchone()
            if result:
                log_channel_id = result[0]
                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel:
                    embed = discord.Embed(
                        description="Action: `Channel Deleted`",
                        color=discord.Color.red()
                    )
                    embed.add_field(name="Channel Name", value=channel.name, inline=True)
                    embed.add_field(name="Type", value=str(channel.type), inline=True)
                    embed.set_footer(text=f"Channel ID: {channel.id}")
                    embed.timestamp = discord.utils.utcnow()

                    await log_channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in on_guild_channel_delete event: {e}")

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        try:
            async with aiosqlite.connect(db_path) as conn:
                async with conn.execute('SELECT log_channel_id FROM config WHERE guild_id = ?', (after.guild.id,)) as cursor:
                    result = await cursor.fetchone()
            if result:
                log_channel_id = result[0]
                log_channel = self.bot.get_channel(log_channel_id)
                if log_channel:
                    embed = discord.Embed(
                        description="Action: `Channel Updated`",
                        color=discord.Color.blue()
                    )
                    embed.add_field(name="Channel", value=after.mention, inline=True)
                    changes = []
                    if before.name != after.name:
                        changes.append(f"Name: {before.name} → {after.name}")
                    if changes:  # Add more checks for other properties as needed
                        embed.add_field(name="Changes", value="\n".join(changes), inline=False)
                    embed.set_footer(text=f"Channel ID: {after.id}")
                    embed.timestamp = discord.utils.utcnow()

                    await log_channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in on_guild_channel_update event: {e}")

# ---------------------------------------------------------------------------------------------------------------------
# Setup Function
# ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute('''
        CREATE TABLE IF NOT EXISTS config (
            guild_id INTEGER PRIMARY KEY,
            log_channel_id INTEGER
        )
        ''')
        await conn.commit()
    await bot.add_cog(LogsCog(bot))
