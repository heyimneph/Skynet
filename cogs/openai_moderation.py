import datetime
import logging
import aiosqlite
import discord

from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Select, View
from openai import AsyncOpenAI

from core.utils import log_command_usage
from config import OPENAI_MODERATION_KEY

#  ---------------------------------------------------------------------------------------------------------------------
#  Configuration
#  ---------------------------------------------------------------------------------------------------------------------
db_path = './data/databases/filter.db'
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

MODERATION_CATEGORIES = [
    "sexual", "sexual/minors",
    "harassment", "harassment/threatening",
    "hate", "hate/threatening",
    "illicit", "illicit/violent",
    "self-harm", "self-harm/intent", "self-harm/instructions",
    "violence", "violence/graphic"
]

class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        key = OPENAI_MODERATION_KEY
        if not key:
            raise RuntimeError("OPENAI_MODERATION_KEY must be set")
        self.client = AsyncOpenAI(api_key=key)

    async def is_enabled(self, guild_id: int) -> bool:
        async with aiosqlite.connect(db_path) as db:
            cur = await db.execute(
                "SELECT enabled FROM moderation_config WHERE guild_id = ?", (guild_id,)
            )
            row = await cur.fetchone()
        return bool(row and row[0])

    async def get_threshold(self, guild_id: int) -> float:
        async with aiosqlite.connect(db_path) as db:
            cur = await db.execute(
                "SELECT threshold FROM moderation_config WHERE guild_id = ?", (guild_id,)
            )
            row = await cur.fetchone()
        return row[0] if row else 0.5

    async def get_triggers(self, guild_id: int) -> list[str]:
        async with aiosqlite.connect(db_path) as db:
            cur = await db.execute(
                "SELECT label FROM moderation_trigger_labels WHERE guild_id = ?", (guild_id,)
            )
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    async def add_trigger(self, guild_id: int, label: str):
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "INSERT INTO moderation_trigger_labels(guild_id,label) VALUES(?,?) "
                "ON CONFLICT(guild_id,label) DO NOTHING",
                (guild_id, label)
            )
            await db.commit()

    async def remove_trigger(self, guild_id: int, label: str):
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "DELETE FROM moderation_trigger_labels WHERE guild_id=? AND label=?",
                (guild_id, label)
            )
            await db.commit()

    async def _log_channel(self, guild: discord.Guild) -> discord.TextChannel:
        name = "logs-moderation"
        ch = discord.utils.get(guild.text_channels, name=name)
        if ch:
            return ch
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True)
        }
        return await guild.create_text_channel(name, overwrites=overwrites)

    #  ---------------------------------------------------------------------------------------------------------------------
    #  Listeners
    #  ---------------------------------------------------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.author.bot or not msg.guild:
            return
        if not await self.is_enabled(msg.guild.id):
            return

        try:
            resp = await self.client.moderations.create(
                input=msg.content,
                model="omni-moderation-latest"
            )
        except Exception as e:
            logger.error(f"Moderation API failure: {e}")
            return

        result = resp.results[0]
        scores = result.category_scores.dict()
        threshold = await self.get_threshold(msg.guild.id)
        # pick all categories whose score >= threshold
        triggered = [cat for cat, sc in scores.items() if sc >= threshold]

        # if guild has configured triggers, intersect
        custom = await self.get_triggers(msg.guild.id)
        if custom:
            triggered = [t for t in triggered if t in custom]

        if not triggered:
            return

        # delete & notify
        try:
            await msg.delete()
        except discord.Forbidden:
            pass

        try:
            await msg.channel.send(
                f"{msg.author.mention}, your message was removed (violates community guidelines)."
            )
        except discord.Forbidden:
            pass

        # send log
        logs = await self._log_channel(msg.guild)
        embed = discord.Embed(
            title="Moderation Alert",
            description="A message was removed by OpenAI moderation.",
            color=discord.Color.red()
        )
        embed.add_field(name="User", value=msg.author.mention, inline=True)
        embed.add_field(name="Channel", value=msg.channel.mention, inline=True)
        embed.add_field(name="Content", value=msg.content or "*empty*", inline=False)
        embed.add_field(name="Triggered Cats", value=", ".join(triggered), inline=False)
        embed.add_field(name="Scores", value="\n".join(f"{c}: {scores[c]:.2f}" for c in triggered), inline=False)
        embed.set_footer(text=f"{datetime.datetime.utcnow():%Y-%m-%d %H:%M UTC}")
        await logs.send(embed=embed)

#  ---------------------------------------------------------------------------------------------------------------------
#  Dropdown View
#  ---------------------------------------------------------------------------------------------------------------------
    class _LabelDropdown(Select):
        def __init__(self, parent: "ModerationCog", action: str, options: list[str]):
            opts = [discord.SelectOption(label=o, value=o) for o in options]
            super().__init__(placeholder="Choose a label", min_values=1, max_values=1, options=opts)
            self.parent = parent
            self.action = action

        async def callback(self, interaction: discord.Interaction):
            label = self.values[0]
            if self.action == "add":
                await self.parent.add_trigger(interaction.guild.id, label)
                msg = f"`Added trigger label: {label}`"
            else:
                await self.parent.remove_trigger(interaction.guild.id, label)
                msg = f"`Removed trigger label: {label}`"
            await interaction.response.send_message(msg, ephemeral=True)

#  ---------------------------------------------------------------------------------------------------------------------
#  Moderation Commands
#  ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(description="Enable moderation in this server")
    @app_commands.checks.has_permissions(administrator=True)
    async def moderation_enable(self, inter: discord.Interaction):
        try:
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "INSERT INTO moderation_config(guild_id,enabled) VALUES(?,1) "
                    "ON CONFLICT(guild_id) DO UPDATE SET enabled=1",
                    (inter.guild.id,)
                )
                await db.commit()
            await inter.response.send_message("`Moderation Enabled`", ephemeral=True)
        except Exception as e:
            logger.error(f"Error enabling moderation for {inter.guild.id}: {e}")
            await inter.response.send_message(f"`Error: {e}`", ephemeral=True)
        finally:
            await log_command_usage(self.bot, inter)

    @app_commands.command(description="Disable moderation in this server")
    @app_commands.checks.has_permissions(administrator=True)
    async def moderation_disable(self, inter: discord.Interaction):
        try:
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "INSERT INTO moderation_config(guild_id,enabled) VALUES(?,0) "
                    "ON CONFLICT(guild_id) DO UPDATE SET enabled=0",
                    (inter.guild.id,)
                )
                await db.commit()
            await inter.response.send_message("`Moderation Disabled`", ephemeral=True)
        except Exception as e:
            logger.error(f"Error disabling moderation for {inter.guild.id}: {e}")
            await inter.response.send_message(f"`Error: {e}`", ephemeral=True)
        finally:
            await log_command_usage(self.bot, inter)

    @app_commands.command(description="Add a moderation trigger label")
    @app_commands.checks.has_permissions(administrator=True)
    async def moderation_add_trigger_label(self, inter: discord.Interaction):
        try:
            view = View()
            view.add_item(self._LabelDropdown(self, "add", MODERATION_CATEGORIES))
            await inter.response.send_message("Choose a category to add:", view=view, ephemeral=True)
        except Exception as e:
            logger.error(f"Error adding trigger label for {inter.guild.id}: {e}")
            await inter.response.send_message(f"`Error: {e}`", ephemeral=True)
        finally:
            await log_command_usage(self.bot, inter)

    @app_commands.command(description="Remove a moderation trigger label")
    @app_commands.checks.has_permissions(administrator=True)
    async def moderation_remove_trigger_label(self, inter: discord.Interaction):
        try:
            current = await self.get_triggers(inter.guild.id)
            if not current:
                await inter.response.send_message("`No trigger labels configured.`", ephemeral=True)
                return
            view = View()
            view.add_item(self._LabelDropdown(self, "remove", current))
            await inter.response.send_message("Choose a category to remove:", view=view, ephemeral=True)
        except Exception as e:
            logger.error(f"Error removing trigger label for {inter.guild.id}: {e}")
            await inter.response.send_message(f"`Error: {e}`", ephemeral=True)
        finally:
            await log_command_usage(self.bot, inter)

    @app_commands.command(description="Set the moderation score threshold (0–1)")
    @app_commands.checks.has_permissions(administrator=True)
    async def moderation_set_threshold(self, inter: discord.Interaction, threshold: float):
        try:
            if not 0 <= threshold <= 1:
                await inter.response.send_message("`Threshold must be between 0 and 1`", ephemeral=True)
                return
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "INSERT INTO moderation_config(guild_id,threshold) VALUES(?,?) "
                    "ON CONFLICT(guild_id) DO UPDATE SET threshold=excluded.threshold",
                    (inter.guild.id, threshold)
                )
                await db.commit()
            await inter.response.send_message(f"`Threshold set to {threshold:.2f}`", ephemeral=True)
        except Exception as e:
            logger.error(f"Error setting threshold for {inter.guild.id}: {e}")
            await inter.response.send_message(f"`Error: {e}`", ephemeral=True)
        finally:
            await log_command_usage(self.bot, inter)

    @app_commands.command(description="View the current moderation score threshold")
    @app_commands.checks.has_permissions(administrator=True)
    async def moderation_view_threshold(self, inter: discord.Interaction):
        try:
            th = await self.get_threshold(inter.guild.id)
            await inter.response.send_message(f"`Current threshold: {th:.2f}`", ephemeral=True)
        except Exception as e:
            logger.error(f"Error viewing threshold for {inter.guild.id}: {e}")
            await inter.response.send_message(f"`Error: {e}`", ephemeral=True)
        finally:
            await log_command_usage(self.bot, inter)

    @app_commands.command(description="Show moderation settings")
    @app_commands.checks.has_permissions(administrator=True)
    async def moderation_settings(self, inter: discord.Interaction):
        try:
            enabled = await self.is_enabled(inter.guild.id)
            th = await self.get_threshold(inter.guild.id)
            triggers = await self.get_triggers(inter.guild.id)

            embed = discord.Embed(title="Moderation Settings", color=discord.Color.blue())
            embed.add_field(name="Enabled", value=f"```{enabled}```", inline=False)
            embed.add_field(name="Threshold", value=f"```{th:.2f}```", inline=False)
            if triggers:
                embed.add_field(name="Trigger Labels", value=f"```\n{chr(10).join(triggers)}\n```", inline=False)
            else:
                embed.add_field(name="Trigger Labels", value="`(none)`", inline=False)

            await inter.response.send_message(embed=embed)
        except Exception as e:
            logger.error(f"Error showing settings for {inter.guild.id}: {e}")
            await inter.response.send_message(f"`Error: {e}`", ephemeral=True)
        finally:
            await log_command_usage(self.bot, inter)


#  ---------------------------------------------------------------------------------------------------------------------
#  Setup Function
#  ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS moderation_config (
                guild_id INTEGER PRIMARY KEY,
                enabled   BOOLEAN DEFAULT 0,
                threshold REAL    DEFAULT 0.5
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS moderation_trigger_labels (
                guild_id INTEGER,
                label    TEXT,
                PRIMARY KEY(guild_id,label)
            )
        """)
        await conn.commit()
    await bot.add_cog(ModerationCog(bot))
