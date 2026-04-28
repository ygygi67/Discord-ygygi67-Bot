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
                    logger.info(f"Loaded status channel: {self.status_channel_id}")
        except Exception as e:
            logger.error(f"Error loading channels: {e}")

    @tasks.loop(minutes=10)
    async def update_status_task(self):
        """Periodically update the status message"""
        if not self.status_channel_id or getattr(self.bot, '_is_shutting_down', False):
            return

        await self.bot.wait_until_ready()
        if getattr(self.bot, '_is_shutting_down', False):
            return
            
        channel = self.bot.get_channel(self.status_channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(self.status_channel_id)
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

            embed = self.create_status_embed()
            await channel.send(embed=embed)
            logger.info("Sent professional status update")
        except Exception as e:
            logger.error(f"Error in update_status_task: {e}")

    def create_status_embed(self):
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
        try:
            status_path = 'data/network_status.json'
            if os.path.exists(status_path):
                with open(status_path, 'r', encoding='utf-8') as f:
                    n_data = json.load(f)
                    last_outage = n_data.get("last_outage")
                    is_recovering = n_data.get("recovery_pending", False)
                    unexpected_event = n_data.get("unexpected_event", False)
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
                  f"**เน็ตหลุดล่าสุด:** {last_outage_str}",
            inline=True
        )

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
        embed.add_field(
            name="📊 สถิติเครือข่าย",
            value=f"**จำนวนเซิร์ฟเวอร์:** `{len(self.bot.guilds)}` แห่ง\n"
                  f"**สมาชิกทั้งหมด:** `{total_members:,}` ท่าน\n"
                  f"**ช่องสัญญาณ:** `{sum(len(guild.channels) for guild in self.bot.guilds)}` ช่อง",
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
 