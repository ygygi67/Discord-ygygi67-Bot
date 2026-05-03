import discord
from discord.ext import commands, tasks
import logging
import json
import os
from datetime import datetime, timezone
import psutil
import platform
import asyncio

logger = logging.getLogger('discord_bot')

class Status(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.status_channel_id = None
        self.status_channels = {}
        self.load_channels()
        self.update_status_task.start()

    def cog_unload(self):
        self.update_status_task.cancel()

    def load_channels(self):
        """Load saved channel IDs from file"""
        try:
            path = 'data/channels.json'
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.status_channel_id = data.get('status_channel')
                    self.status_channels = {
                        str(guild_id): int(channel_id)
                        for guild_id, channel_id in data.get("status_channels", {}).items()
                        if channel_id
                    }
                    logger.info(f"Loaded status channel: {self.status_channel_id}")
                    logger.info(f"Loaded guild status channels: {len(self.status_channels)}")
        except Exception as e:
            logger.error(f"Error loading channels: {e}")

    def save_channels(self):
        try:
            path = 'data/channels.json'
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = {}
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            data["status_channel"] = self.status_channel_id
            data["status_channels"] = self.status_channels
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Error saving channels: {e}")

    async def set_status_channel(self, guild_id: int, channel_id: int, global_channel: bool = False):
        if global_channel:
            self.status_channel_id = channel_id
        self.status_channels[str(guild_id)] = int(channel_id)
        self.save_channels()
        await self.update_status_channel(channel_id, guild_id=guild_id)

    @tasks.loop(minutes=10)
    async def update_status_task(self):
        """Periodically update the status message"""
        if getattr(self.bot, '_is_shutting_down', False):
            return

        await self.bot.wait_until_ready()
        if getattr(self.bot, '_is_shutting_down', False):
            return

        targets = []
        if self.status_channel_id:
            targets.append((self.status_channel_id, None))
        for guild_id, channel_id in self.status_channels.items():
            if channel_id not in [target[0] for target in targets]:
                targets.append((channel_id, int(guild_id) if str(guild_id).isdigit() else None))

        for channel_id, guild_id in targets:
            await self.update_status_channel(channel_id, guild_id=guild_id)

    async def update_status_channel(self, channel_id: int, guild_id: int | None = None):
        if getattr(self.bot, '_is_shutting_down', False):
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except:
                return

        try:
            # Purge the channel first for a professional, clean look
            try:
                # Deleting messages one by one or via purge
                await channel.purge(limit=100)
                logger.info(f"Purged status channel {channel.name}")
            except Exception as e:
                logger.error(f"Failed to purge status channel: {e}")

            guild = self.bot.get_guild(guild_id) if guild_id else getattr(channel, "guild", None)
            embed = self.create_status_embed(guild)
            await channel.send(embed=embed)
            logger.info(f"Sent professional status update to {channel_id}")
        except Exception as e:
            logger.error(f"Error updating status channel {channel_id}: {e}")

    def create_status_embed(self, guild: discord.Guild | None = None):
        """Create a professional status embed"""
        embed = discord.Embed(
            title="🌐 ระบบจัดการอัลฟ่า | Alpha System Dashboard",
            description="ตรวจสอบความปลอดภัยและสถานะทรัพยากรของบอทแบบเรียลไทม์",
            color=0x2b2d31, # Midnight dark theme
            timestamp=datetime.now(timezone.utc)
        )

        # Bot Information
        uptime = datetime.now(timezone.utc) - self.bot.start_time
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{days}วัน {hours}ชม. {minutes}นาที"

        # Network Status / Outage info
        last_outage_str = "ไม่พบประวัติ"
        is_recovering = False
        unexpected_event = False
        network_kind = None
        network_detail = None
        try:
            status_path = 'data/network_status.json'
            if os.path.exists(status_path):
                with open(status_path, 'r', encoding='utf-8') as f:
                    n_data = json.load(f)
                    last_outage = n_data.get("last_outage")
                    is_recovering = n_data.get("recovery_pending", False)
                    unexpected_event = n_data.get("unexpected_event", False)
                    network_kind = n_data.get("network_kind")
                    network_detail = n_data.get("network_detail")
                    if last_outage:
                        try:
                            dt = datetime.strptime(last_outage, '%Y-%m-%d %H:%M:%S')
                            last_outage_str = f"<t:{int(dt.timestamp())}:R>"
                        except:
                            last_outage_str = last_outage
                
                # ถ้ากำลังประมวลผลการฟื้นฟู ให้ติ๊กออกหลังจากอ่านแล้ว
                needs_save = False
                if is_recovering:
                    n_data["recovery_pending"] = False
                    needs_save = True
                if unexpected_event:
                    n_data["unexpected_event"] = False
                    needs_save = True
                
                if needs_save:
                    with open(status_path, 'w', encoding='utf-8') as f:
                        json.dump(n_data, f, indent=4)
        except: pass

        status_emoji = "🟢" if not is_recovering else "🟡"
        status_text = "ออนไลน์ (เสถียร)" if not is_recovering else "กำลังฟื้นฟูระบบ..."

        embed.add_field(
            name="🤖 ข้อมูลโปรเซส",
            value=f"**สถานะ:** `{status_emoji} {status_text}`\n"
                  f"**ความหน่วง:** `{round(self.bot.latency * 1000)}ms`\n"
                  f"**Uptime:** `{uptime_str}`",
            inline=True
        )

        # System Resources
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        embed.add_field(
            name="💻 ทรัพยากรระบบ",
            value=f"**CPU Usage:** `{cpu}%`\n"
                  f"**RAM Usage:** `{ram}%`\n"
                  f"**เน็ตหลุดล่าสุด:** {last_outage_str}\n"
                  f"**สาเหตุเน็ต:** `{network_kind or 'ไม่ทราบ'}`",
            inline=True
        )
        if network_detail:
            embed.add_field(name="🔎 รายละเอียดเครือข่าย", value=str(network_detail)[:1000], inline=False)

        if unexpected_event:
            embed.set_author(name="🚨 ตรวจพบการหยุดทำงานที่ไม่ปกติในครั้งล่าสุด")
            embed.color = 0xff4757 # Bright red for security event
        elif is_recovering:
            embed.set_author(name="🛡️ ระบบเพิ่งฟื้นฟูจากสภาวะเครือข่ายขัดข้อง")
            embed.color = 0xf1c40f # Yellow for recovery status
        else:
            embed.color = 0x2b2d31 # Normal midnight theme

        # Metadata
        total_members = sum(guild.member_count for guild in self.bot.guilds)
        guild_text = ""
        if guild:
            guild_text = f"\n**เซิร์ฟเวอร์บอร์ดนี้:** `{guild.name}` (`{guild.member_count or 0:,}` สมาชิก)"
        embed.add_field(
            name="📊 สถิติเครือข่าย",
            value=f"**จำนวนเซิร์ฟเวอร์:** `{len(self.bot.guilds)}` แห่ง\n"
                  f"**สมาชิกทั้งหมด:** `{total_members:,}` ท่าน\n"
                  f"**ช่องสัญญาณ:** `{sum(len(guild.channels) for guild in self.bot.guilds)}` ช่อง"
                  f"{guild_text}",
            inline=False
        )

        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text="ระบบจะทำการล้างข้อความและอัปเดตทุก 10 นาทีอัตโนมัติ", icon_url=self.bot.user.display_avatar.url)
        
        return embed

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Trigger update when bot joins a guild"""
        await self.update_status_task()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Trigger update when bot leaves a guild"""
        await self.update_status_task()

async def setup(bot):
    await bot.add_cog(Status(bot))
