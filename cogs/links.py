import os
import re
import time
import logging
import aiohttp
import aiosqlite
import discord

from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import View, button, Button
from collections import defaultdict, deque
from typing import Optional

from config import VIRUS_TOTAL_API

# ---------------------------------------------------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------------------------------------------------
db_path = './data/databases/filter.db'

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------------------------------
# VirusTotal Endpoints
# ---------------------------------------------------------------------------------------------------------------------
if not VIRUS_TOTAL_API:
    logger.error("VIRUSTOTAL_API_KEY not set in environment; link scanning will fail.")

VT_URL_SUBMIT = "https://www.virustotal.com/api/v3/urls"
VT_ANALYSES   = "https://www.virustotal.com/api/v3/analyses/{}"
HEADERS       = {"x-apikey": VIRUS_TOTAL_API}


# ---------------------------------------------------------------------------------------------------------------------
# Delete/Restore Views
# ---------------------------------------------------------------------------------------------------------------------
class DeleteLinkView(View):
    @button(label="Delete Link Message", style=discord.ButtonStyle.danger)
    async def delete_button(self, interaction: discord.Interaction, button: Button):
        embed = interaction.message.embeds[0]
        msg_id = int(embed.fields[-2].value)
        ch_id  = int(embed.fields[-1].value)
        channel = interaction.guild.get_channel(ch_id)
        if channel:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.delete()
                await interaction.response.send_message("Original link message deleted.", ephemeral=True)
            except discord.NotFound:
                await interaction.response.send_message("Original message not found.", ephemeral=True)
        await interaction.message.delete()

class RestoreLinkView(View):
    def __init__(self, fragments, user, deletion_msg_id, deletion_ch_id):
        super().__init__(timeout=None)
        self.fragments   = fragments
        self.user        = user
        self.del_msg_id  = deletion_msg_id
        self.del_ch_id   = deletion_ch_id

    @button(label="Restore Link Message", style=discord.ButtonStyle.success)
    async def restore_button(self, interaction: discord.Interaction, button: Button):
        channel = interaction.guild.get_channel(self.del_ch_id)
        try:
            deletion_msg = await channel.fetch_message(self.del_msg_id)
            content = "".join(txt for _, txt, _ in self.fragments)
            restored = discord.Embed(
                title="Restored Link Message",
                description=f"*{content}*",
                color=discord.Color.green()
            )
            restored.set_footer(text=f"Sent by {self.user}", icon_url=self.user.display_avatar.url)
            await deletion_msg.edit(embed=restored)
            await interaction.response.send_message("Message restored.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Could not restore message.", ephemeral=True)
        finally:
            await interaction.message.delete()


# ---------------------------------------------------------------------------------------------------------------------
# MaliciousLinkCog
# ---------------------------------------------------------------------------------------------------------------------
class MaliciousLinkCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_message_fragments = defaultdict(deque)
        self.fragment_timeout = 10
        self.cleanup_task.start()

    def cog_unload(self):
        self.cleanup_task.cancel()

    def extract_and_normalize_urls(self, content: str):
        pattern = re.compile(r'(https?://\S+|www\.\S+|\S+\.\S+)')
        out = []
        for u in pattern.findall(content):
            if not u.startswith(("http://", "https://")):
                u = "https://" + u
            out.append(u)
        return out

    def check_and_reassemble_fragments(self, message):
        user_id = message.author.id
        ch_id   = message.channel.id
        now     = time.time()

        frags = [
            (m, txt, ts)
            for m, txt, ts in self.user_message_fragments[user_id]
            if m.channel.id == ch_id and now - ts < self.fragment_timeout
        ]
        frags.append((message, message.content, now))
        self.user_message_fragments[user_id] = deque(frags)

        urls = []
        for _, txt, _ in frags:
            urls.extend(self.extract_and_normalize_urls(txt))
        return urls, frags

    async def analyze_url(self, url: str):
        import asyncio
        async with aiohttp.ClientSession() as session:
            resp1 = await session.post(VT_URL_SUBMIT, headers=HEADERS, data={"url": url})
            body1 = await resp1.text()
            if resp1.status != 200:
                return None
            j1 = await resp1.json()
            aid = j1["data"]["id"]

            for _ in range(10):
                await asyncio.sleep(2)
                resp2 = await session.get(VT_ANALYSES.format(aid), headers=HEADERS)
                body2 = await resp2.text()
                if resp2.status != 200:
                    continue
                j2    = await resp2.json()
                attrs = j2["data"]["attributes"]
                if attrs.get("status") == "completed":
                    stats = attrs.get("stats") or attrs.get("last_analysis_stats")
                    return stats

            return None

    def create_alert_embed(self, message, stats, del_msg_id, del_ch_id):
        e = discord.Embed(
            title="Malicious Link Alert",
            description="VirusTotal flagged this link as malicious.",
            color=discord.Color.red()
        )
        e.add_field(name="Message Content", value=message.content, inline=False)
        stats_text = "\n".join(f"{k}: {v}" for k, v in stats.items())
        e.add_field(name="Analysis Stats", value=f"```{stats_text}```", inline=False)
        e.add_field(name="Message ID", value=str(message.id), inline=True)
        e.add_field(name="Channel ID", value=str(message.channel.id), inline=True)
        e.add_field(name="Deletion Msg ID", value=str(del_msg_id), inline=True)
        e.add_field(name="Deletion Ch ID", value=str(del_ch_id), inline=True)
        e.set_footer(text=f"Posted by {message.author}", icon_url=message.author.display_avatar.url)
        return e

    def create_log_embed(self, message, url, stats):
        e = discord.Embed(
            title="URL Logged (Clean)",
            description="VirusTotal returned zero malicious detections.",
            color=discord.Color.orange()
        )
        e.add_field(name="Message Content", value=message.content, inline=False)
        e.add_field(name="URL", value=url, inline=False)
        stats_text = "\n".join(f"{k}: {v}" for k, v in stats.items())
        e.add_field(name="Analysis Stats", value=f"```{stats_text}```", inline=False)
        e.set_footer(text=f"Posted by {message.author}", icon_url=message.author.display_avatar.url)
        return e

# ---------------------------------------------------------------------------------------------------------------------
# Loops
# ---------------------------------------------------------------------------------------------------------------------
    @tasks.loop(seconds=10)
    async def cleanup_task(self):
        cutoff = time.time() - self.fragment_timeout
        for user_id, frags in list(self.user_message_fragments.items()):
            new_frags = deque((m, t, ts) for m, t, ts in frags if ts >= cutoff)
            if new_frags:
                self.user_message_fragments[user_id] = new_frags
            else:
                del self.user_message_fragments[user_id]

# ---------------------------------------------------------------------------------------------------------------------
# Listeners
# ---------------------------------------------------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        urls, frags = self.check_and_reassemble_fragments(message)
        if not urls:
            return

        logs = discord.utils.get(message.guild.text_channels, name="logs-malicious-links")
        if not logs:
            overwrites = {message.guild.default_role: discord.PermissionOverwrite(read_messages=False)}
            logs = await message.guild.create_text_channel("logs-malicious-links", overwrites=overwrites)

        for url in urls:
            stats = await self.analyze_url(url)
            if stats is None:
                continue

            if stats.get("malicious", 0) > 0:
                for msg_obj, _, _ in frags:
                    try:
                        await msg_obj.delete()
                    except discord.NotFound:
                        pass
                deletion = await message.channel.send(
                    f"{message.author.mention}, your message was deleted due to a malicious link."
                )
                view = RestoreLinkView(frags, message.author, deletion.id, deletion.channel.id)
                await logs.send(embed=self.create_alert_embed(message, stats, deletion.id, deletion.channel.id),
                                view=view)
                break
            else:
                view = DeleteLinkView()
                await logs.send(embed=self.create_log_embed(message, url, stats), view=view)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        await self.on_message(after)

# ---------------------------------------------------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(
        name="link_detection",
        description="Toggle or set malicious‑link detection (omit to toggle)"
    )
    @app_commands.describe(state="true to enable, false to disable")
    @app_commands.checks.has_permissions(administrator=True)
    async def link_detection(
        self,
        interaction: discord.Interaction,
        state: Optional[bool] = None
    ):
        async with aiosqlite.connect(db_path) as conn:
            cur = await conn.execute(
                "SELECT link_detection_enabled FROM link_filter_config WHERE guild_id = ?",
                (interaction.guild.id,)
            )
            row = await cur.fetchone()

            if state is None:
                new = 0 if (row and row[0] == 1) else 1
            else:
                new = 1 if state else 0

            await conn.execute(
                """
                INSERT INTO link_filter_config (guild_id, link_detection_enabled)
                VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE
                  SET link_detection_enabled = excluded.link_detection_enabled
                """,
                (interaction.guild.id, new)
            )
            await conn.commit()

        await interaction.response.send_message(
            f"`Link detection is now {'ENABLED' if new else 'DISABLED'}.`",
            ephemeral=True
        )

# ---------------------------------------------------------------------------------------------------------------------
# Setup Function
# ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS link_filter_config (
                guild_id INTEGER PRIMARY KEY,
                link_detection_enabled BOOLEAN DEFAULT 1
            )
        ''')
        await conn.commit()
    await bot.add_cog(MaliciousLinkCog(bot))
