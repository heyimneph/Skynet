import discord
import os
import logging
import aiosqlite


from discord.ext import commands


# ---------------------------------------------------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------------------------------------------------
db_path = './data/databases/filter.db'

#  ---------------------------------------------------------------------------------------------------------------------
#  Command Logging
#  ---------------------------------------------------------------------------------------------------------------------
async def log_command_usage(bot, interaction):
    try:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                'SELECT log_channel_id FROM config WHERE guild_id = ?', (interaction.guild.id,)
            ) as cursor:
                row = await cursor.fetchone()

                if row:
                    log_channel_id = row[0]
                    log_channel = bot.get_channel(log_channel_id)
                    if log_channel:
                        embed = discord.Embed(
                            description=f"Command: `{interaction.command.name}`",
                            color=discord.Color.blue()
                        )
                        embed.add_field(name="User", value=interaction.user.mention, inline=True)
                        embed.add_field(name="Guild ID", value=interaction.guild_id, inline=True)
                        embed.add_field(name="Channel", value=interaction.channel.mention, inline=True)
                        embed.set_footer(text=f"User ID: {interaction.user.id}")
                        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
                        embed.timestamp = discord.utils.utcnow()
                        await log_channel.send(embed=embed)
    except aiosqlite.Error as e:
        logging.error(f"Error logging command usage: {e}")
    except Exception as e:
        logging.error(f"Unexpected error logging command usage: {e}")


