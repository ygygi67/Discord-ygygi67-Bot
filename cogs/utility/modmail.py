import discord
from discord.ext import commands
import logging
import asyncio
import json
import os
from datetime import datetime, timezone

logger = logging.getLogger('discord_bot')

class Modmail(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.category_id = 1478650262833987687
        # We find or use a specific server for these channels. 
        # Usually, the bot is in a main server. We'll use the first one it's in or a config ID.
        self.main_guild_id = 1171254331643789332 # The sync guild ID used in bot.py
        self.state_path = "data/modmail_state.json"
        self.state = self.load_state()
        self.backfill_task = asyncio.create_task(self.backfill_offline_dms())

    def cog_unload(self):
        if self.backfill_task:
            self.backfill_task.cancel()

    def load_state(self):
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"[Modmail] failed to load state: {e}")
        return {"users": {}}

    def save_state(self):
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[Modmail] failed to save state: {e}")

    def get_last_outage_datetime(self):
        try:
            path = "data/network_status.json"
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("last_outage")
            if not raw:
                return None
            local_tz = datetime.now().astimezone().tzinfo
            return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=local_tz).astimezone(timezone.utc)
        except Exception:
            return None

    async def forward_dm_message(self, message, channel, is_backfill=False):
        title = "📥 ข้อความย้อนหลังจากผู้ใช้" if is_backfill else "📥 ข้อความใหม่จากผู้ใช้"
        embed = discord.Embed(
            title=title,
            description=f"**ผู้ส่ง:** {message.author.mention} ({message.author.name})\n\n**เนื้อหา:**\n{message.content or '*[ไม่มีข้อความ]*'}",
            color=discord.Color.orange() if is_backfill else discord.Color.blue(),
            timestamp=message.created_at or datetime.now(timezone.utc)
        )
        embed.set_author(name=f"คุยกับ: {message.author.name}", icon_url=message.author.display_avatar.url)
        embed.set_footer(text=f"User ID: {message.author.id} | Message ID: {message.id}")

        if message.attachments:
            embed.set_image(url=message.attachments[0].url)

        await channel.send(embed=embed)
        user_state = self.state.setdefault("users", {}).setdefault(str(message.author.id), {})
        user_state["last_dm_message_id"] = str(message.id)
        user_state["last_dm_at"] = (message.created_at or datetime.now(timezone.utc)).isoformat()
        self.save_state()
        logger.info(f"[Modmail] forwarded {'backfill ' if is_backfill else ''}DM message={message.id} user={message.author.id} channel={channel.id}")

    async def backfill_offline_dms(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(5)

        guild = self.bot.get_guild(self.main_guild_id)
        if not guild:
            return

        category = guild.get_channel(self.category_id)
        if not category or not isinstance(category, discord.CategoryChannel):
            return

        outage_dt = self.get_last_outage_datetime()
        users = []
        for channel in category.text_channels:
            if channel.topic and channel.topic.isdigit():
                users.append((int(channel.topic), channel))

        total = 0
        for user_id, modmail_channel in users:
            try:
                user = await self.bot.fetch_user(user_id)
                dm = await user.create_dm()
                user_state = self.state.setdefault("users", {}).setdefault(str(user_id), {})
                last_id = user_state.get("last_dm_message_id")
                after = discord.Object(id=int(last_id)) if last_id and str(last_id).isdigit() else outage_dt
                if after is None:
                    continue

                messages = []
                async for msg in dm.history(limit=50, after=after, oldest_first=True):
                    if msg.author.id == self.bot.user.id:
                        continue
                    messages.append(msg)

                if messages:
                    await modmail_channel.send(f"📜 พบข้อความ DM ย้อนหลัง {len(messages)} ข้อความ ระหว่างที่บอทออฟไลน์/เน็ตหลุด")
                for msg in messages:
                    await self.forward_dm_message(msg, modmail_channel, is_backfill=True)
                    total += 1
            except Exception as e:
                logger.warning(f"[Modmail] backfill failed for user={user_id}: {e}")

        if total:
            logger.warning(f"[Modmail] backfilled {total} offline DM message(s)")

    async def get_or_create_channel(self, guild, user):
        """Find existing member channel in category or create new one"""
        category = guild.get_channel(self.category_id)
        if not category or not isinstance(category, discord.CategoryChannel):
            logger.warning(f"Category {self.category_id} not found in guild {guild.name}")
            return None

        channel_name = f"💬︰{user.name}".lower().replace(" ", "-")
        # Seek by topic or name
        for channel in category.text_channels:
            if channel.topic == str(user.id):
                return channel
        
        # Create new channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        
        try:
            new_channel = await category.create_text_channel(
                name=channel_name,
                topic=str(user.id),
                overwrites=overwrites,
                reason=f"Support channel for {user.name}"
            )
            return new_channel
        except Exception as e:
            logger.error(f"Failed to create support channel: {e}")
            return None

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # Case 1: Message is a Direct Message to the bot (User -> Bot/Staff)
        if isinstance(message.channel, discord.DMChannel):
            guild = self.bot.get_guild(self.main_guild_id)
            if not guild:
                return

            channel = await self.get_or_create_channel(guild, message.author)
            if not channel:
                return

            await self.forward_dm_message(message, channel)
            # Add reaction to user's DM to confirm receipt

        # Case 2: Message is in a Modmail channel (Staff -> User)
        elif message.guild and message.guild.id == self.main_guild_id:
            if message.channel.category_id == self.category_id:
                # The topic stores the User ID
                try:
                    user_id_str = message.channel.topic
                    if not user_id_str or not user_id_str.isdigit():
                        return
                        
                    user_id = int(user_id_str)
                    user = await self.bot.fetch_user(user_id)
                    if not user:
                        return
                    
                    # Create relay embed for the USER
                    embed = discord.Embed(
                        title="💬 การตอบกลับจากแอดมิน",
                        description=f"**แอดมิน {message.author.name} ส่งถึงคุณ:**\n\n{message.content or '*[ไม่มีข้อความ]*'}",
                        color=discord.Color.green(),
                        timestamp=datetime.now()
                    )
                    embed.set_author(name=f"Admin: {message.author.name}", icon_url=message.author.display_avatar.url)
                    embed.set_footer(text=f"ตอบจากเซิร์ฟเวอร์ {message.guild.name}")
                    
                    if message.attachments:
                        embed.set_image(url=message.attachments[0].url)
                    
                    await user.send(embed=embed)

                except Exception as e:
                    logger.warning(f"Modmail relay error: {e}")

async def setup(bot):
    await bot.add_cog(Modmail(bot))
    logger.info("Modmail cog loaded: DM Relay System active")
