import discord
from discord.ext import commands
import logging
from datetime import datetime, timezone
import asyncio
import json

logger = logging.getLogger('discord_bot')

class BotNotifications(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config_path = "data/channels.json"
        
    def _read_config(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    async def get_notification_channel(self):
        config = self._read_config()
        channel_id = config.get("bot_log_channel", 1359893324969808203)
        try:
            return self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        except Exception:
            return None

    def _now(self):
        return datetime.now(timezone.utc)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """เมื่อบอทถูกเชิญเข้าเซิร์ฟเวอร์"""
        # 1. แจ้งเตือนไปยังช่องแจ้งเตือนหลักของบอท
        channel = await self.get_notification_channel()
        
        # ค้นหาคนเชิญจาก Audit Log
        inviter = None
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.bot_add):
                if entry.target.id == self.bot.user.id:
                    inviter = entry.user
                    break
        except Exception:
            pass

        embed = discord.Embed(
            title="📥 บอทถูกเชิญเข้าเซิร์ฟเวอร์ใหม่",
            color=discord.Color.green(),
            timestamp=self._now()
        )
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
        embed.add_field(name="ชื่อเซิร์ฟเวอร์", value=f"**{guild.name}**", inline=True)
        embed.add_field(name="ID เซิร์ฟเวอร์", value=f"`{guild.id}`", inline=True)
        embed.add_field(name="เจ้าของเซิร์ฟเวอร์", value=f"{guild.owner.mention} (`{guild.owner.name}`)" if guild.owner else "ไม่พบข้อมูล", inline=False)
        embed.add_field(name="จำนวนสมาชิก", value=f"{guild.member_count} คน", inline=True)
        
        if inviter:
            embed.add_field(name="ผู้เชิญเข้าร่วม", value=f"{inviter.mention} (`{inviter.name}`)", inline=True)
        
        if channel:
            await channel.send(embed=embed)

        # 2. ตรวจสอบสิทธิ์ Administrator
        if not guild.me.guild_permissions.administrator:
            warning_msg = (
                f"⚠️ **แจ้งเตือน: สิทธิ์การใช้งานไม่ครบถ้วน**\n"
                f"บอทเข้าสู่เซิร์ฟเวอร์ **{guild.name}** เรียบร้อยแล้ว! แต่ตอนนี้ยังขาดสิทธิ์ **Administrator** ครับ\n"
                f"เพื่อให้ระบบต่างๆ (เช่น การเล่นเพลง) ทำงานได้ลื่นไหล รบกวนช่วยมอบสิทธิ์นี้ให้บอทหน่อยนะครับ!"
            )

            
            # แจ้งเตือนคนเชิญ
            target_to_notify = inviter or guild.owner
            if target_to_notify:
                try:
                    await target_to_notify.send(warning_msg)
                    logger.info(f"Sent missing admin warning to {target_to_notify.name} for guild {guild.name}")
                except discord.Forbidden:
                    # ถ้าส่ง DM ไม่ได้ ให้ลองส่งในแชแนลแรกที่พิมพ์ได้
                    for text_channel in guild.text_channels:
                        if text_channel.permissions_for(guild.me).send_messages:
                            await text_channel.send(f"{target_to_notify.mention} " + warning_msg)
                            break

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """เมื่อบอทถูกเตะหรือออกจากเซิร์ฟเวอร์"""
        channel = await self.get_notification_channel()
        if not channel:
            return

        embed = discord.Embed(
            title="📤 บอทออกจากเซิร์ฟเวอร์",
            color=discord.Color.red(),
            timestamp=self._now()
        )
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
        embed.add_field(name="ชื่อเซิร์ฟเวอร์", value=f"**{guild.name}**", inline=True)
        embed.add_field(name="ID เซิร์ฟเวอร์", value=f"`{guild.id}`", inline=True)
        embed.add_field(name="จำนวนสมาชิก (ก่อนออก)", value=f"{guild.member_count} คน", inline=True)
        
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_ready(self):
        """เมื่อบอทพร้อมทำงาน"""
        channel = await self.get_notification_channel()
        if not channel:
            return

        # คำนวณจำนวนคำสั่งทั้งหมด
        all_commands = self.bot.tree.get_commands()
        total_cmds = len(all_commands)
        
        # แยกหมวดหมู่คำสั่งเด่นๆ
        featured_cmds = ["`/เล่น`", "`/พูดตาม`", "`/เชิญบอทเต็ม`", "`/สถานะ`", "`/ความหน่วง`"]
        new_features = [
            "🔍 `/ค้นหาเพื่อนร่วมกลุ่ม` - ค้นหาคนในกลุ่มร่วมกันและวาดแผนผัง",
            "📻 `Auto Play` - ระบบเล่นเพลงอัตโนมัติเมื่อคิวหมด",
            "🛡️ `Persistent Admins` - ระบบจดจำแอดมินบอทถาวร"
        ]

        embed = discord.Embed(
            title="🚀 SYSTEM ONLINE & OPERATIONAL",
            description=f"```🤖 บอทออนไลน์แล้วใน {len(self.bot.guilds)} เซิร์ฟเวอร์```",
            color=discord.Color.from_rgb(0, 221, 255),
            timestamp=self._now()
        )

        embed.add_field(
            name="📊 สรุปภาพรวม",
            value=f"```🌐 {len(self.bot.guilds)} เซิร์ฟเวอร์\n📡 {total_cmds} คำสั่งพร้อมใช้งาน\n🟢 สถานะ: พร้อมรบ 100%```",
            inline=False
        )

        embed.add_field(
            name="✨ คำสั่งที่แนะนำ",
            value=" · ".join(featured_cmds),
            inline=False
        )

        embed.add_field(
            name="🆕 มีอะไรใหม่?",
            value="\n".join(new_features),
            inline=False
        )

        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        embed.set_footer(
            text=f"Alpha Bot System | Total {total_cmds} Commands Loaded",
            icon_url=self.bot.user.display_avatar.url
        )

        await channel.send(embed=embed)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BotNotifications(bot))
