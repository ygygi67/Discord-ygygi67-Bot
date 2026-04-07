import discord
from discord import app_commands
from discord.ext import commands
import logging
import traceback
from datetime import datetime, timedelta, timezone
import platform
import psutil
import os
import asyncio
import aiohttp
import zipfile
import tempfile
import shutil
import re
import csv
import io
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import yt_dlp

logger = logging.getLogger('discord_bot')


class AudioFallbackView(discord.ui.View):
    def __init__(self, cog, url: str, requester_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.url = url
        self.requester_id = requester_id
        self.is_processing = False

    @discord.ui.button(label="🎧 โหลดเป็น MP3 แทน", style=discord.ButtonStyle.green)
    async def switch_to_mp3(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.requester_id:
            return await interaction.response.send_message("❌ ปุ่มนี้สำหรับคนที่สั่งคำสั่งเท่านั้น", ephemeral=True)
        if self.is_processing:
            return await interaction.response.send_message("⏳ กำลังสลับเป็นโหมด MP3 อยู่ กรุณารอสักครู่", ephemeral=True)

        self.is_processing = True
        button.disabled = True
        button.label = "⏳ กำลังโหลด MP3..."

        await interaction.response.defer(ephemeral=False)
        try:
            await interaction.edit_original_response(view=self)
        except Exception:
            pass

        await self.cog._download_clip_core(interaction, self.url, "mp3", defer_response=False)

class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = datetime.now()
        self.active_monitors = {}  # Store active monitors for admin version
        self.public_monitors = {}  # Store active monitors for public version
        self.walking_frames = ["🚶", "🏃", "🚶", "🏃"]  # Walking animation frames
        self.current_frame = 0
        self.bot_admin_id = 1034845842709958786
        self.main_only_mode = os.getenv("UTILITY_MAIN_ONLY", "1").strip().lower() in {"1", "true", "yes", "on"}
        default_core = ["คำสั่ง", "โหลดคลิป", "เสียง", "ระบบ", "ติดตาม", "สถิติ", "เชิญบอทเต็ม"]
        raw_core = os.getenv("UTILITY_CORE_COMMANDS", ",".join(default_core)).strip()
        self.core_commands = {x.strip() for x in re.split(r"[,\s;|]+", raw_core) if x.strip()}
        logging.info("Utility cog initialized")

    def get_app_commands(self):
        commands_list = super().get_app_commands()
        if not self.main_only_mode:
            return commands_list
        return [cmd for cmd in commands_list if cmd.name in self.core_commands]

    def _is_bot_admin(self, user_id: int) -> bool:
        """ตรวจสอบว่าเป็นแอดมินบอทหรือไม่"""
        admin_cog = self.bot.get_cog('Admin')
        if admin_cog:
            if hasattr(admin_cog, 'is_admin'):
                return admin_cog.is_admin(user_id)
            if hasattr(admin_cog, 'allowed_user_id'):
                return str(user_id) == str(admin_cog.allowed_user_id)
        return user_id == self.bot_admin_id

    async def _check_permission(self, interaction: discord.Interaction) -> bool:
        """ตรวจสอบว่าผู้ใช้มีสิทธิ์ Administrator ในเซิร์ฟเวอร์ หรือเป็นแอดมินบอท"""
        if interaction.user.guild_permissions.administrator or self._is_bot_admin(interaction.user.id):
            return True
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้ (ต้องการสิทธิ์ Administrator หรือแอดมินบอท)", ephemeral=True)
        return False

    async def cog_load(self):
        """Called when the cog is loaded"""
        pass

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Handle errors for all commands in this cog"""
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏳ กรุณารอ {error.retry_after:.2f} วินาทีก่อนใช้คำสั่งนี้อีกครั้ง",
                ephemeral=True
            )
        elif isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้",
                ephemeral=True
            )
        elif isinstance(error, app_commands.BotMissingPermissions):
            await interaction.response.send_message(
                "❌ บอทไม่มีสิทธิ์ที่จำเป็นในการใช้คำสั่งนี้",
                ephemeral=True
            )
        else:
            error_embed = discord.Embed(
                title="❌ เกิดข้อผิดพลาด",
                description=f"```{str(error)}```",
                color=discord.Color.red()
            )
            error_embed.set_footer(text="กรุณาลองใหม่อีกครั้งหรือติดต่อผู้ดูแลระบบ")
            try:
                await interaction.response.send_message(embed=error_embed, ephemeral=True)
            except:
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            logger.error(f"Command error: {error}")

    def get_uptime(self):
        """คำนวณเวลาทำงานของบอท"""
        uptime = datetime.now() - self.start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours} ชั่วโมง {minutes} นาที {seconds} วินาที"

    @app_commands.command(name="ความหน่วง", description="ตรวจสอบความหน่วงของบอท")
    async def ping(self, interaction: discord.Interaction):
        """ตรวจสอบความหน่วงของบอท"""
        try:
            # Create loading message
            await interaction.response.send_message("⏳ กำลังตรวจสอบความหน่วง...")
            
            # Calculate bot latency
            latency = round(self.bot.latency * 1000)
            
            # Calculate API latency
            start_ts = datetime.now().timestamp()
            api_latency = round((datetime.now().timestamp() - start_ts) * 1000)
            
            # Create embed with better formatting
            embed = discord.Embed(
                title="🏓 ตรวจสอบความหน่วง",
                color=discord.Color.green() if latency < 100 else discord.Color.orange() if latency < 200 else discord.Color.red()
            )
            
            # Add latency information with emojis
            embed.add_field(
                name="🌐 ความหน่วงของบอท",
                value=f"**{latency}ms**",
                inline=True
            )
            
            embed.add_field(
                name="⚡ ความหน่วงของ API",
                value=f"**{api_latency}ms**",
                inline=True
            )
            
            # Add status indicator
            status = "🟢 ดี" if latency < 100 else "🟡 ปกติ" if latency < 200 else "🔴 ช้า"
            embed.add_field(
                name="📊 สถานะ",
                value=status,
                inline=True
            )
            
            # Add footer with timestamp
            embed.set_footer(text=f"ตรวจสอบเมื่อ • {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
            
            await interaction.edit_original_response(content=None, embed=embed)
        except Exception as e:
            await self.cog_app_command_error(interaction, e)

    @app_commands.command(name="ข้อมูลเซิร์ฟเวอร์", description="แสดงข้อมูลเชิงลึกและสถิติของเซิร์ฟเวอร์")
    async def serverinfo(self, interaction: discord.Interaction):
        """แสดงข้อมูลเกี่ยวกับเซิร์ฟเวอร์แบบพรีเมียม"""
        if not interaction.guild:
            return await interaction.response.send_message("❌ คำสั่งนี้ใช้ได้เฉพาะในเซิร์ฟเวอร์", ephemeral=True)

        guild = interaction.guild
        await interaction.response.defer()

        # คำนวณข้อมูลสมาชิก
        total_members = guild.member_count
        bots = sum(1 for m in guild.members if m.bot)
        humans = total_members - bots
        
        # สถานะสมาชิก
        online = len([m for m in guild.members if m.status == discord.Status.online])
        idle = len([m for m in guild.members if m.status == discord.Status.idle])
        dnd = len([m for m in guild.members if m.status == discord.Status.dnd])
        
        # วันที่สร้าง
        created_time = discord.utils.format_dt(guild.created_at, 'F')
        created_relative = discord.utils.format_dt(guild.created_at, 'R')

        embed = discord.Embed(
            title=f"🏰 {guild.name}",
            description=f"```{guild.description or 'ไม่มีคำอธิบายเซิร์ฟเวอร์'}```",
            color=discord.Color.from_rgb(0, 200, 255),
            timestamp=datetime.now()
        )

        if guild.icon: embed.set_thumbnail(url=guild.icon.url)
        if guild.banner: embed.set_image(url=guild.banner.url)

        # ข้อมูลพื้นฐาน
        embed.add_field(
            name="📌 ข้อมูลทั่วไป",
            value=f"**เจ้าของ:** {guild.owner.mention if guild.owner else 'ไม่ทราบ'}\n"
                  f"**ID:** `{guild.id}`\n"
                  f"**สร้างเมื่อ:** {created_time}\n({created_relative})",
            inline=False
        )

        # สถิติสมาชิก
        embed.add_field(
            name="👥 สมาชิก",
            value=f"**ทั้งหมด:** `{total_members}` คน\n"
                  f"**คน:** `{humans}` | **บอท:** `{bots}`\n"
                  f"**🟢:** `{online}` | **🟡:** `{idle}` | **🔴:** `{dnd}`",
            inline=True
        )

        # สถิติช่อง
        embed.add_field(
            name="📝 ช่องการใช้งาน",
            value=f"**หมวดหมู่:** `{len(guild.categories)}` ช่อง\n"
                  f"**ข้อความ:** `{len(guild.text_channels)}` ช่อง\n"
                  f"**เสียง:** `{len(guild.voice_channels)}` ช่อง",
            inline=True
        )

        # ข้อมูลความปลอดภัยและการปรับแต่ง
        features = ", ".join(guild.features).lower().replace("_", " ") if guild.features else "ไม่มี"
        embed.add_field(
            name="🔐 ความปลอดภัย & ฟีเจอร์",
            value=f"**ระดับความปลอดภัย:** `{str(guild.verification_level).title()}`\n"
                  f"**ฟิลเตอร์เนื้อหา:** `{str(guild.explicit_content_filter).title()}`\n"
                  f"**ฟีเจอร์:** {features[:100]}...",
            inline=False
        )

        # บูสต์และขีดจำกัด
        embed.add_field(
            name="💎 เซิร์ฟเวอร์บูสต์",
            value=f"**จำนวน:** `{guild.premium_subscription_count}` บูสต์\n"
                  f"**เลเวล:** `Level {guild.premium_tier}`\n"
                  f"**อีโมจิ:** `{len(guild.emojis)}/{guild.emoji_limit}`",
            inline=True
        )

        embed.add_field(
            name="🎭 บทบาท",
            value=f"**ทั้งหมด:** `{len(guild.roles)}` ยศ\n"
                  f"**สูงสุด:** {guild.roles[-1].mention}",
            inline=True
        )

        embed.set_footer(text=f"Requested by {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="ข้อมูลผู้ใช้", description="แสดงโปรไฟล์และข้อมูลเชิงลึกของผู้ใช้")
    @app_commands.describe(user="ผู้ใช้ที่ต้องการดูข้อมูล (ถ้าไม่ระบุจะแสดงข้อมูลของคุณ)")
    async def userinfo(self, interaction: discord.Interaction, user: discord.Member = None):
        """แสดงข้อมูลเกี่ยวกับผู้ใช้แบบพรีเมียม"""
        target = user or interaction.user
        await interaction.response.defer()

        # สร้างวันที่
        created_time = discord.utils.format_dt(target.created_at, 'F')
        created_relative = discord.utils.format_dt(target.created_at, 'R')
        joined_time = discord.utils.format_dt(target.joined_at, 'F') if target.joined_at else "ไม่ทราบ"
        joined_relative = discord.utils.format_dt(target.joined_at, 'R') if target.joined_at else ""

        # รวบรวมยศ
        roles = [role.mention for role in reversed(target.roles[1:])] # เรียงจากสูงไปต่ำ ไม่รวม @everyone
        roles_display = " ".join(roles[:15]) if roles else "ไม่มี"
        if len(roles) > 15: roles_display += f" ...และอีก {len(roles)-15} ยศ"

        # ธง/เครื่องหมาย (Flags)
        flags = [f.replace("_", " ").title() for f, v in target.public_flags if v]
        flags_text = ", ".join(flags) if flags else "ไม่มี"

        embed = discord.Embed(
            title=f"👤 {target.name}#{target.discriminator}",
            color=target.color if target.color.value else discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        embed.set_thumbnail(url=target.display_avatar.url)
        if target.banner: embed.set_image(url=target.banner.url)

        # สถานะและประเภทบัญชี
        status_map = {
            discord.Status.online: "🟢 ออนไลน์",
            discord.Status.idle: "🟡 ไม่อยู่",
            discord.Status.dnd: "🔴 ห้ามรบกวน",
            discord.Status.offline: "⚫ ออฟไลน์"
        }
        account_type = "🤖 บอท" if target.bot else "👤 ผู้ใช้ทั่วไป"
        
        embed.add_field(
            name="📌 ข้อมูลทั่วไป",
            value=f"**ID:** `{target.id}`\n"
                  f"**ประเภท:** {account_type}\n"
                  f"**สถานะ:** {status_map.get(target.status, '⚫ ไม่พบข้อมูล')}\n"
                  f"**เข็มกลัด:** {flags_text}",
            inline=False
        )

        embed.add_field(
            name="📅 ไทม์ไลน์",
            value=f"**สร้างบัญชีเมื่อ:** {created_time}\n({created_relative})\n"
                  f"**เข้าร่วมเซิร์ฟเวอร์:** {joined_time}\n({joined_relative})",
            inline=False
        )

        embed.add_field(
            name=f"🎭 บทบาท ({len(target.roles)-1})",
            value=roles_display,
            inline=False
        )

        # สิทธิ์สำคัญ
        key_perms = []
        if target.guild_permissions.administrator: key_perms.append("`Administrator`")
        if target.guild_permissions.manage_guild: key_perms.append("`Manage Server`")
        if target.guild_permissions.manage_roles: key_perms.append("`Manage Roles`")
        if target.guild_permissions.manage_channels: key_perms.append("`Manage Channels`")
        if target.guild_permissions.ban_members: key_perms.append("`Ban Members`")
        
        if key_perms:
            embed.add_field(name="🔑 สิทธิ์สำคัญ", value=" · ".join(key_perms), inline=False)

        embed.set_footer(text=f"User ID: {target.id}")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="ข้อมูลบอท", description="แสดงประสิทธิภาพและสถิติเชิงลึกของบอท")
    async def show_bot_info(self, interaction: discord.Interaction):
        """แสดงข้อมูลประสิทธิภาพระบบและบอทแบบพรีเมียม"""
        await interaction.response.defer()
        
        # ปิงและสถิติพื้นฐาน
        latency = round(self.bot.latency * 1000)
        total_guilds = len(self.bot.guilds)
        total_members = sum(g.member_count for g in self.bot.guilds)
        total_commands = len(self.bot.tree.get_commands())
        
        # ระบบ Uptime
        uptime_str = self.get_uptime()
        
        # ข้อมูลระบบ (Hardware)
        cpu_usage = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        ram_used = ram.used / (1024 ** 3)
        ram_total = ram.total / (1024 ** 3)
        
        embed = discord.Embed(
            title="🎮 Alpha Bot Performance Dashboard",
            description="```ระบบกำลังทำงานอย่างเต็มประสิทธิภาพ 🟢```",
            color=discord.Color.from_rgb(255, 100, 0),
            timestamp=datetime.now()
        )

        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        # Infrastructure
        embed.add_field(
            name="🚀 โครงสร้างพื้นฐาน",
            value=f"**ความหน่วง:** `{latency}ms`\n"
                  f"**เวลาทำงาน:** `{uptime_str}`\n"
                  f"**Python:** `{platform.python_version()}`\n"
                  f"**Discord.py:** `{discord.__version__}`",
            inline=True
        )

        # Network Stats
        embed.add_field(
            name="📊 สถิติเครือข่าย",
            value=f"**เซิร์ฟเวอร์:** `{total_guilds}` แห่ง\n"
                  f"**สมาชิกทั้งหมด:** `{total_members:,}` คน\n"
                  f"**คำสั่งทั้งหมด:** `{total_commands}` คำสั่ง",
            inline=True
        )

        # Resource Usage
        embed.add_field(
            name="💻 ทรัพยากรเครื่อง",
            value=f"**CPU Usage:** `{cpu_usage}%`\n"
                  f"**RAM Usage:** `{ram.percent}%` ({ram_used:.2f}GB / {ram_total:.2f}GB)\n"
                  f"**ระบบที่รัน:** `{platform.system()} {platform.release()}`",
            inline=False
        )

        # New Features and Developer contact
        embed.add_field(
            name="🛠️ ทีมพัฒนา และ โปรเจกต์",
            value="**ผู้พัฒนาหลัก:** `DeepMind Antigravity`\n"
                  "**โปรเจกต์:** [GitHub Registry](https://github.com/ygygi67)\n"
                  "**สถานะ:** `Development State (Experimental)`",
            inline=False
        )

        embed.set_footer(text="✨ Powered by High-Performance Core", icon_url=self.bot.user.display_avatar.url)
        
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="เชิญบอท", description="สร้างลิงก์เชิญบอท")
    async def invite(self, interaction: discord.Interaction):
        """สร้างลิงก์เชิญบอท"""
        try:
            permissions = discord.Permissions(
                send_messages=True,
                embed_links=True,
                attach_files=True,
                read_message_history=True,
                add_reactions=True,
                connect=True,
                speak=True,
                use_voice_activation=True,
                stream=True,
                view_channel=True,
                manage_messages=True,
                use_external_emojis=True,
                use_application_commands=True,
                manage_channels=True,
                manage_roles=True,
                administrator=True
            )
            
            invite_url = discord.utils.oauth_url(
                self.bot.user.id,
                permissions=permissions,
                scopes=["bot", "applications.commands"]
            )
            
            embed = discord.Embed(
                title="🔗 เชิญบอท",
                description=f"[คลิกที่นี่]({invite_url}) เพื่อเชิญบอทเข้าเซิร์ฟเวอร์ของคุณ\n\n**หมายเหตุ:** บอทจะต้องได้รับสิทธิ์ Administrator เพื่อให้สามารถทำงานได้อย่างสมบูรณ์",
                color=discord.Color.blue()
            )
            
            # Add bot avatar
            if self.bot.user.avatar:
                embed.set_thumbnail(url=self.bot.user.avatar.url)
            
            # Add footer with bot name
            embed.set_footer(text=f"Bot: {self.bot.user.name}")
            
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await self.cog_app_command_error(interaction, e)

    @app_commands.command(name="ช่อง", description="แสดงข้อมูลเกี่ยวกับช่องทั้งหมดในเซิร์ฟเวอร์")
    async def channels(self, interaction: discord.Interaction):
        """แสดงข้อมูลเกี่ยวกับช่องทั้งหมดในเซิร์ฟเวอร์"""
        try:
            if not interaction.guild:
                await interaction.response.send_message("❌ คำสั่งนี้สามารถใช้ได้เฉพาะในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
                return

            guild = interaction.guild
            
            # Create embed
            embed = discord.Embed(
                title=f"📊 ข้อมูลช่องทั้งหมดใน {guild.name}",
                color=discord.Color.blue()
            )
            
            # Add server icon if available
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            
            # Text Channels
            text_channels = [f"📝 {channel.mention} ({channel.name})" for channel in guild.text_channels]
            if text_channels:
                embed.add_field(
                    name=f"📝 ช่องข้อความ ({len(text_channels)})",
                    value="\n".join(text_channels[:10]) + (f"\nและอีก {len(text_channels)-10} ช่อง..." if len(text_channels) > 10 else ""),
                    inline=False
                )
            
            # Voice Channels
            voice_channels = [f"🔊 {channel.mention} ({channel.name})" for channel in guild.voice_channels]
            if voice_channels:
                embed.add_field(
                    name=f"🔊 ช่องเสียง ({len(voice_channels)})",
                    value="\n".join(voice_channels[:10]) + (f"\nและอีก {len(voice_channels)-10} ช่อง..." if len(voice_channels) > 10 else ""),
                    inline=False
                )
            
            # Categories
            category_channels = [f"📁 {category.name}" for category in guild.categories]
            if category_channels:
                embed.add_field(
                    name=f"📁 หมวดหมู่ ({len(category_channels)})",
                    value="\n".join(category_channels[:10]) + (f"\nและอีก {len(category_channels)-10} หมวดหมู่..." if len(category_channels) > 10 else ""),
                    inline=False
                )
            
            # Bot Permissions
            bot_permissions = guild.me.guild_permissions
            permissions_text = (
                f"อ่านข้อความ: {'✅' if bot_permissions.read_messages else '❌'}\n"
                f"ส่งข้อความ: {'✅' if bot_permissions.send_messages else '❌'}\n"
                f"จัดการข้อความ: {'✅' if bot_permissions.manage_messages else '❌'}\n"
                f"เชื่อมต่อเสียง: {'✅' if bot_permissions.connect else '❌'}\n"
                f"พูด: {'✅' if bot_permissions.speak else '❌'}\n"
                f"จัดการช่อง: {'✅' if bot_permissions.manage_channels else '❌'}"
            )
            
            embed.add_field(
                name="🔒 สิทธิ์ของบอท",
                value=permissions_text,
                inline=False
            )
            
            # Add footer with server ID
            embed.set_footer(text=f"Server ID: {guild.id}")
            
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await self.cog_app_command_error(interaction, e)

    @app_commands.command(name="คำสั่ง", description="แสดงรายการคำสั่งทั้งหมดที่บอทมีให้ใช้งาน")
    async def help(self, interaction: discord.Interaction):
        """แสดงรายการคำสั่งทั้งหมดแบบอัตโนมัติแบ่งตามหมวดหมู่ (พร้อมระบบแบ่งหน้า)"""
        try:
            await interaction.response.defer(ephemeral=False)
            
            cog_aliases = {
                "Admin": "🛠️ การตั้งค่าแอดมิน",
                "Moderation": "🛡️ การดูแลความเรียบร้อย",
                "Music": "🎵 ระบบเสียงและเพลง",
                "Roles": "🎭 ระบบรับยศ",
                "ServerCopier": "🖨️ ระบบคัดลอกเซิร์ฟเวอร์",
                "ServerLogger": "📋 ระบบล็อกเซิร์ฟเวอร์",
                "Stats": "📊 สถิติในเซิร์ฟเวอร์",
                "Status": "📡 สถานะและการทำงาน",
                "Utility": "🔧 เครื่องมือทั่วไป",
                "RoleSyncAndManage": "⚙️ การตั้งค่าและจัดสิทธิ์ยศ",
                "AIBot": "🤖 ระบบ AI และแชทบอท",
                "Voice": "🎤 ระบบจัดการเสียง"
            }

            all_pages = []
            all_commands_count = 0
            
            # รวบรวมคำสั่งทั้งหมดแบ่งตาม Cog
            all_cog_cmds = {}
            for cog_name, cog in self.bot.cogs.items():
                cmds = cog.get_app_commands()
                if not cmds: continue
                
                cmd_list = []
                for cmd in cmds:
                    # เก็บทั้ง Command ธรรมดาและ Group
                    all_commands_count += 1
                    desc = cmd.description or "ไม่มีคำอธิบาย"
                    if len(desc) > 60: desc = desc[:57] + "..."
                    cmd_list.append(f"`/{cmd.name}` - {desc}")
                
                if cmd_list:
                    all_cog_cmds[cog_aliases.get(cog_name, f"📌 {cog_name}")] = cmd_list

            # แบ่งเข้า Embed หน้าละ 5 Cog เพื่อไม่ให้ยาวเกินไป
            cog_items = list(all_cog_cmds.items())
            items_per_page = 4
            
            for i in range(0, len(cog_items), items_per_page):
                page_items = cog_items[i:i+items_per_page]
                embed = discord.Embed(
                    title="📚 รายการคำสั่งของ Alpha Bot",
                    description=f"นี่คือคำสั่งทั้งหมดที่ซิงค์แล้วจำนวน **{all_commands_count}** คำสั่ง\n\n",
                    color=discord.Color.blue(),
                    timestamp=datetime.now()
                )
                
                for group_name, cmds in page_items:
                    val = "\n".join(cmds)
                    if len(val) > 1000: val = val[:1000] + "\n..."
                    embed.add_field(name=group_name, value=val, inline=False)
                
                embed.set_thumbnail(url=self.bot.user.display_avatar.url)
                embed.set_footer(text=f"หน้า {len(all_pages)+1}/{(len(cog_items)-1)//items_per_page + 1} | ใช้ปุ่มด้านล่างเพื่อเปลี่ยนหน้า")
                all_pages.append(embed)

            if not all_pages:
                return await interaction.followup.send("❌ ขณะนี้ไม่พบคำสั่งที่ใช้งานได้")

            view = MemberHelpView(all_pages, interaction.user.id)
            await interaction.followup.send(embed=all_pages[0], view=view)
            
        except Exception as e:
            logger.error(f"Error in help command: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาดภายใน: {e}", ephemeral=True)


    @app_commands.command(name="สถิติ", description="แสดงสถิติการใช้งานของบอทแบบเรียลไทม์")
    async def stats(self, interaction: discord.Interaction):
        """แสดงสถิติการใช้งานของบอทแบบเรียลไทม์"""
        try:
            # Check cooldown
            current_time = datetime.now().timestamp()
            if current_time - self.cooldowns[interaction.guild.id][interaction.user.id] < self.stats_cooldown:
                remaining = int(self.stats_cooldown - (current_time - self.cooldowns[interaction.guild.id][interaction.user.id]))
                minutes = remaining // 60
                seconds = remaining % 60
                await interaction.response.send_message(f"⏳ กรุณารออีก {minutes} นาที {seconds} วินาทีก่อนใช้คำสั่งนี้อีกครั้ง", ephemeral=True)
                return

            # Create initial embed
            embed = discord.Embed(
                title="📊 สถิติการใช้งาน",
                description="กำลังอัปเดตข้อมูล...",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed)
            
            # Update stats every 5 seconds for 1 minute
            for _ in range(12):
                # System Stats
                cpu_percent = psutil.cpu_percent()
                memory = psutil.virtual_memory()
                memory_used = memory.used / (1024 * 1024 * 1024)  # Convert to GB
                memory_total = memory.total / (1024 * 1024 * 1024)  # Convert to GB
                
                # Bot Stats
                latency = round(self.bot.latency * 1000)
                total_members = sum(guild.member_count for guild in self.bot.guilds)
                total_voice_channels = sum(len(guild.voice_channels) for guild in self.bot.guilds)
                active_voice_channels = sum(1 for guild in self.bot.guilds for vc in guild.voice_channels if vc.members)
                
                # Create updated embed
                embed = discord.Embed(
                    title="📊 สถิติการใช้งาน",
                    color=discord.Color.blue()
                )
                
                # System Information
                embed.add_field(
                    name="💻 ระบบ",
                    value=f"CPU: **{cpu_percent}%**\nRAM: **{memory.percent}%**\n({memory_used:.2f} GB / {memory_total:.2f} GB)",
                    inline=True
                )
                
                # Bot Information
                embed.add_field(
                    name="🤖 บอท",
                    value=f"ความหน่วง: **{latency}ms**\nเวลาทำงาน: **{self.get_uptime()}**",
                    inline=True
                )
                
                # Server Information
                embed.add_field(
                    name="🌐 เซิร์ฟเวอร์",
                    value=f"จำนวน: **{len(self.bot.guilds)}**\nสมาชิก: **{total_members}**",
                    inline=True
                )
                
                # Voice Channel Information
                embed.add_field(
                    name="🔊 ช่องเสียง",
                    value=f"ทั้งหมด: **{total_voice_channels}**\nใช้งาน: **{active_voice_channels}**",
                    inline=True
                )
                
                # Add timestamp
                embed.set_footer(text=f"อัปเดตล่าสุด • {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
                
                await interaction.edit_original_response(embed=embed)
                await asyncio.sleep(5)  # Wait 5 seconds before next update
            
            # Final message
            embed = discord.Embed(
                title="📊 สถิติการใช้งาน",
                description="การอัปเดตสิ้นสุดลงแล้ว\nใช้คำสั่ง `/สถิติ` อีกครั้งเพื่อดูข้อมูลใหม่",
                color=discord.Color.blue()
            )
            await interaction.edit_original_response(embed=embed)
            
            # Update cooldown after successful execution
            self.cooldowns[interaction.guild.id][interaction.user.id] = current_time
            
        except Exception as e:
            await self.cog_app_command_error(interaction, e)

    @app_commands.command(name="เสียง", description="แสดงข้อมูลช่องเสียงที่กำลังใช้งาน")
    async def voice_stats(self, interaction: discord.Interaction):
        """แสดงข้อมูลช่องเสียงที่กำลังใช้งาน"""
        try:
            if not interaction.guild:
                await interaction.response.send_message("❌ คำสั่งนี้สามารถใช้ได้เฉพาะในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
                return

            guild = interaction.guild
            
            # Get voice channel information
            active_channels = []
            total_members = 0
            
            for vc in guild.voice_channels:
                if vc.members:
                    member_count = len(vc.members)
                    total_members += member_count
                    active_channels.append(f"🔊 {vc.name}: **{member_count}** คน")
            
            # Create embed
            embed = discord.Embed(
                title=f"🔊 ช่องเสียงที่ใช้งานใน {guild.name}",
                color=discord.Color.blue()
            )
            
            if active_channels:
                embed.add_field(
                    name=f"ช่องที่ใช้งาน ({len(active_channels)})",
                    value="\n".join(active_channels),
                    inline=False
                )
                embed.add_field(
                    name="👥 สมาชิกทั้งหมด",
                    value=f"**{total_members}** คน",
                    inline=True
                )
            else:
                embed.description = "ไม่มีช่องเสียงที่กำลังใช้งานอยู่"
            
            # Add server icon if available
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            
            # Add footer with timestamp
            embed.set_footer(text=f"อัปเดตเมื่อ • {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
            
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await self.cog_app_command_error(interaction, e)

    @app_commands.command(name="ระบบ", description="แสดงข้อมูลการใช้งานระบบ")
    async def system_stats(self, interaction: discord.Interaction):
        """แสดงข้อมูลการใช้งานระบบ"""
        try:
            # Get system information
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Create embed
            embed = discord.Embed(
                title="💻 ข้อมูลระบบ",
                color=discord.Color.blue()
            )
            
            # CPU Information
            embed.add_field(
                name="🔄 CPU",
                value=f"การใช้งาน: **{cpu_percent}%**\nจำนวนคอร์: **{psutil.cpu_count()}**",
                inline=True
            )
            
            # Memory Information
            memory_used = memory.used / (1024 * 1024 * 1024)  # Convert to GB
            memory_total = memory.total / (1024 * 1024 * 1024)  # Convert to GB
            embed.add_field(
                name="💾 RAM",
                value=f"การใช้งาน: **{memory.percent}%**\n({memory_used:.2f} GB / {memory_total:.2f} GB)",
                inline=True
            )
            
            # Disk Information
            disk_used = disk.used / (1024 * 1024 * 1024)  # Convert to GB
            disk_total = disk.total / (1024 * 1024 * 1024)  # Convert to GB
            embed.add_field(
                name="💿 หน่วยความจำ",
                value=f"การใช้งาน: **{disk.percent}%**\n({disk_used:.2f} GB / {disk_total:.2f} GB)",
                inline=True
            )
            
            # Process Information
            process = psutil.Process()
            embed.add_field(
                name="⚡ โปรเซส",
                value=f"CPU: **{process.cpu_percent()}%**\nRAM: **{process.memory_percent():.2f}%**",
                inline=True
            )
            
            # Network Information
            net_io = psutil.net_io_counters()
            embed.add_field(
                name="🌐 เครือข่าย",
                value=f"รับ: **{net_io.bytes_recv / (1024*1024):.2f} MB**\nส่ง: **{net_io.bytes_sent / (1024*1024):.2f} MB**",
                inline=True
            )
            
            # Add footer with timestamp
            embed.set_footer(text=f"อัปเดตเมื่อ • {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
            
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await self.cog_app_command_error(interaction, e)

    @app_commands.command(name="ติดตามต่อเนื่อง", description="แสดงข้อมูลการใช้งานแบบเรียลไทม์ต่อเนื่อง (สำหรับผู้ดูแลระบบ)")
    @app_commands.describe(interval="ระยะเวลาการอัปเดต (วินาที) (ค่าเริ่มต้น: 1)")
    @app_commands.checks.has_permissions(administrator=True)
    async def monitor_continuous_admin(self, interaction: discord.Interaction, interval: int = 1):
        """แสดงข้อมูลการใช้งานแบบเรียลไทม์ต่อเนื่อง (สำหรับผู้ดูแลระบบ)"""
        try:
            # Validate interval
            if interval < 1 or interval > 60:
                await interaction.response.send_message("❌ ระยะเวลาการอัปเดตต้องอยู่ระหว่าง 1-60 วินาที", ephemeral=True)
                return

            # Stop any existing monitor for this user
            if interaction.user.id in self.active_monitors:
                self.active_monitors[interaction.user.id].stopped = True
                del self.active_monitors[interaction.user.id]

            # Create initial embed
            embed = discord.Embed(
                title=f"{self.walking_frames[0]} การติดตามระบบ",
                description=f"กำลังเริ่มการติดตาม...\nอัปเดตทุก {interval} วินาที",
                color=discord.Color.blue()
            )
            
            # Create view for tracking
            class MonitorView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=None)
                    self.stopped = False
            
            view = MonitorView()
            self.active_monitors[interaction.user.id] = view
            
            # Send initial response
            await interaction.response.send_message("✅ เริ่มการติดตามระบบแล้ว", ephemeral=True)
            
            # Send monitoring message
            message = await interaction.channel.send(embed=embed)
            
            start_time = datetime.now()
            
            # Update loop
            while not view.stopped:
                # Calculate elapsed time
                elapsed = (datetime.now() - start_time).total_seconds()
                hours = int(elapsed // 3600)
                minutes = int((elapsed % 3600) // 60)
                seconds = int(elapsed % 60)
                
                # Update walking animation
                self.current_frame = (self.current_frame + 1) % len(self.walking_frames)
                
                # System Stats
                cpu_percent = psutil.cpu_percent()
                memory = psutil.virtual_memory()
                memory_used = memory.used / (1024 * 1024 * 1024)  # Convert to GB
                memory_total = memory.total / (1024 * 1024 * 1024)  # Convert to GB
                
                # Bot Stats
                latency = round(self.bot.latency * 1000)
                total_members = sum(guild.member_count for guild in self.bot.guilds)
                total_voice_channels = sum(len(guild.voice_channels) for guild in self.bot.guilds)
                active_voice_channels = sum(1 for guild in self.bot.guilds for vc in guild.voice_channels if vc.members)
                
                # Process Stats
                process = psutil.Process()
                process_cpu = process.cpu_percent()
                process_memory = process.memory_percent()
                
                # Network Stats
                net_io = psutil.net_io_counters()
                bytes_sent = net_io.bytes_sent / (1024*1024)  # Convert to MB
                bytes_recv = net_io.bytes_recv / (1024*1024)  # Convert to MB
                
                # Create updated embed
                embed = discord.Embed(
                    title=f"{self.walking_frames[self.current_frame]} การติดตามระบบ",
                    description=f"⏱️ เวลาทำงาน: **{hours:02d}:{minutes:02d}:{seconds:02d}**",
                    color=discord.Color.blue()
                )
                
                # System Information
                embed.add_field(
                    name="💻 ระบบ",
                    value=f"CPU: **{cpu_percent}%**\nRAM: **{memory.percent}%**\n({memory_used:.2f} GB / {memory_total:.2f} GB)",
                    inline=True
                )
                
                # Bot Information
                embed.add_field(
                    name="🤖 บอท",
                    value=f"ความหน่วง: **{latency}ms**\nCPU: **{process_cpu:.1f}%**\nRAM: **{process_memory:.1f}%**",
                    inline=True
                )
                
                # Server Information
                embed.add_field(
                    name="🌐 เซิร์ฟเวอร์",
                    value=f"จำนวน: **{len(self.bot.guilds)}**\nสมาชิก: **{total_members}**",
                    inline=True
                )
                
                # Voice Channel Information
                embed.add_field(
                    name="🔊 ช่องเสียง",
                    value=f"ทั้งหมด: **{total_voice_channels}**\nใช้งาน: **{active_voice_channels}**",
                    inline=True
                )
                
                # Network Information
                embed.add_field(
                    name="🌐 เครือข่าย",
                    value=f"รับ: **{bytes_recv:.2f} MB**\nส่ง: **{bytes_sent:.2f} MB**",
                    inline=True
                )
                
                # Add timestamp
                embed.set_footer(text=f"อัปเดตล่าสุด • {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
                
                # Edit the monitoring message
                try:
                    await message.edit(embed=embed)
                except:
                    view.stopped = True
                    break
                    
                await asyncio.sleep(interval)
            
        except Exception as e:
            await self.cog_app_command_error(interaction, e)

    @app_commands.command(name="ติดตาม", description="แสดงข้อมูลการใช้งานแบบเรียลไทม์ (จำกัดเวลา 1 นาที)")
    @app_commands.describe(interval="ระยะเวลาการอัปเดต (วินาที) (ค่าเริ่มต้น: 1)")
    async def monitor_continuous_public(self, interaction: discord.Interaction, interval: int = 1):
        """แสดงข้อมูลการใช้งานแบบเรียลไทม์ (จำกัดเวลา 1 นาที)"""
        try:
            # Validate interval
            if interval < 1 or interval > 60:
                await interaction.response.send_message("❌ ระยะเวลาการอัปเดตต้องอยู่ระหว่าง 1-60 วินาที", ephemeral=True)
                return

            # Stop any existing public monitor for this user
            if interaction.user.id in self.public_monitors:
                self.public_monitors[interaction.user.id].stopped = True
                del self.public_monitors[interaction.user.id]   

            # Create initial embed
            embed = discord.Embed(
                title=f"{self.walking_frames[0]} การติดตามระบบ",
                description=f"กำลังเริ่มการติดตาม...\nอัปเดตทุก {interval} วินาที\n⏱️ จำกัดเวลา 1 นาที",
                color=discord.Color.blue()
            )
            
            # Create view for tracking
            class MonitorView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=None)
                    self.stopped = False
            
            view = MonitorView()
            self.public_monitors[interaction.user.id] = view
            
            # Send initial response
            await interaction.response.send_message("✅ เริ่มการติดตามระบบแล้ว", ephemeral=True)
            
            # Send monitoring message
            message = await interaction.channel.send(embed=embed)
            
            start_time = datetime.now()
            end_time = start_time + timedelta(minutes=1)  # Set 1 minute limit
            
            # Update loop
            while not view.stopped:
                # Check if time limit reached
                if datetime.now() >= end_time:
                    embed = discord.Embed(
                        title="⏰ การติดตามสิ้นสุดลง",
                        description="การติดตามระบบสิ้นสุดลงตามเวลาที่กำหนด (1 นาที)\n\n"
                                    "💡 **คุณสามารถใช้คำสั่ง `/ติดตาม` อีกรอบเพื่อเริ่มการติดตามใหม่ได้ครับ**",
                        color=discord.Color.blue()
                    )
                    await message.edit(embed=embed)
                    view.stopped = True
                    break
                
                # Calculate elapsed time
                elapsed = (datetime.now() - start_time).total_seconds()
                hours = int(elapsed // 3600)
                minutes = int((elapsed % 3600) // 60)
                seconds = int(elapsed % 60)
                
                # Update walking animation
                self.current_frame = (self.current_frame + 1) % len(self.walking_frames)
                
                # Bot Stats
                latency = round(self.bot.latency * 1000)
                total_members = sum(guild.member_count for guild in self.bot.guilds)
                total_voice_channels = sum(len(guild.voice_channels) for guild in self.bot.guilds)
                active_voice_channels = sum(1 for guild in self.bot.guilds for vc in guild.voice_channels if vc.members)
                
                # Create updated embed
                embed = discord.Embed(
                    title=f"{self.walking_frames[self.current_frame]} การติดตามระบบ",
                    description=f"⏱️ เวลาทำงาน: **{hours:02d}:{minutes:02d}:{seconds:02d}**\n⏳ เหลือเวลา: **{int((end_time - datetime.now()).total_seconds())}** วินาทีก่อนสิ้นสุด",
                    color=discord.Color.blue()
                )
                
                # Bot Information
                embed.add_field(
                    name="🤖 บอท",
                    value=f"ความหน่วง: **{latency}ms**",
                    inline=True
                )
                
                # Server Information
                embed.add_field(
                    name="🌐 เซิร์ฟเวอร์",
                    value=f"จำนวน: **{len(self.bot.guilds)}**\nสมาชิก: **{total_members}**",
                    inline=True
                )
                
                # Voice Channel Information
                embed.add_field(
                    name="🔊 ช่องเสียง",
                    value=f"ทั้งหมด: **{total_voice_channels}**\nใช้งาน: **{active_voice_channels}**",
                    inline=True
                )
                
                # Add timestamp
                embed.set_footer(text=f"อัปเดตล่าสุด • {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
                
                # Edit the monitoring message
                try:
                    await message.edit(embed=embed)
                except:
                    view.stopped = True
                    break
                    
                await asyncio.sleep(interval)
            
            # Clean up
            if interaction.user.id in self.public_monitors:
                del self.public_monitors[interaction.user.id]
            
        except Exception as e:
            await self.cog_app_command_error(interaction, e)

    @app_commands.command(name="เชิญบอทเต็ม", description="สร้างลิงก์เชิญบอทและแสดงคำสั่งที่ซิงค์แล้ว")
    async def invite_bot(self, interaction: discord.Interaction):
        try:
            permissions = discord.Permissions(
                send_messages=True,
                embed_links=True,
                attach_files=True,
                read_message_history=True,
                add_reactions=True,
                connect=True,
                speak=True,
                use_voice_activation=True,
                stream=True,
                view_channel=True,
                manage_messages=True,
                use_external_emojis=True,
                use_application_commands=True,
                manage_channels=True,
                manage_roles=True,
                administrator=True
            )
            invite_url = discord.utils.oauth_url(
                self.bot.user.id,
                permissions=permissions,
                scopes=["bot", "applications.commands"]
            )
            # Get all synced commands
            all_cmds = self.bot.tree.get_commands()
            synced_commands = [f"/{cmd.name} - {cmd.description}" for cmd in all_cmds]
            
            # If user is bot admin, show secret commands
            if self._is_bot_admin(interaction.user.id):
                synced_commands.append("⚠️ **[Admin Only]** `!fullbackup` - สำรองข้อมูลทุกอย่างจากทุกเซิร์ฟเวอร์")
                synced_commands.append("⚠️ **[Admin Only]** `!Copy_here` - จะก็อปเซิฟร์โดยให้ใส่ ID ของเซิฟร์นั้น ๆ")

            # Limit description to avoid 400 Bad Request (Max 4096 chars)
            # We will show first 20 commands to keep it clean and safe
            display_cmds = synced_commands[:20]
            remaining = len(synced_commands) - 20
            
            description_text = f"[คลิกที่นี่]({invite_url}) เพื่อเชิญบอทเข้าเซิร์ฟเวอร์ของคุณ\n\n**คำสั่งที่ซิงค์แล้ว ({len(synced_commands)}):**\n"
            description_text += "\n".join(display_cmds)
            if remaining > 0:
                description_text += f"\n*...และอีก {remaining} คำสั่ง*"

            # Safety check for the 4096 limit
            if len(description_text) > 4000:
                description_text = description_text[:3990] + "..."

            embed = discord.Embed(
                title="🔗 เชิญบอท",
                description=description_text,
                color=discord.Color.green()
            )
            # Fallback for command name
            command_name = getattr(getattr(interaction, "command", None), "name", "เชิญบอทเต็ม")
            embed.add_field(
                name="Command Used",
                value=f"`/{command_name}`",
                inline=False
            )
            embed.add_field(
                name="User",
                value=f"{getattr(interaction.user, 'mention', str(interaction.user))} (`{getattr(interaction.user, 'id', 'N/A')}`)",
                inline=True
            )
            embed.add_field(
                name="Channel",
                value=f"{getattr(interaction.channel, 'mention', str(interaction.channel))}",
                inline=True
            )
            embed.add_field(
                name="Guild",
                value=f"{getattr(getattr(interaction, 'guild', None), 'name', 'DM')}",
                inline=True
            )
            # Use interaction.created_at if available, else fallback to now
            timestamp = getattr(interaction, "created_at", None)
            if not timestamp or not isinstance(timestamp, datetime):
                timestamp = datetime.now()
            embed.set_footer(text=f"Synced at {timestamp.strftime('%d/%m/%Y %H:%M:%S')}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            import traceback
            logger.error(f"Error in invite_bot: {e}\n{traceback.format_exc()}")
            await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)

    @app_commands.command(name="โหลดรูปทั้งเซิร์ฟ", description="ดาวน์โหลดรูปโปรไฟล์สมาชิก (Admin Only)")
    @app_commands.describe(ขอบเขต="เลือกเซิร์ฟเวอร์ที่ต้องการโหลด (เฉพาะแอดมินบอทที่โหลดได้ทุกเซิร์ฟ)")
    @app_commands.choices(ขอบเขต=[
        app_commands.Choice(name="เฉพาะเซิร์ฟเวอร์นี้", value="current"),
        app_commands.Choice(name="ทุกเซิร์ฟเวอร์ที่บอทอยู่ (เฉพาะแอดมินบอท)", value="all")
    ])
    async def download_all_avatars(self, interaction: discord.Interaction, ขอบเขต: str = "current"):
        """ดาวน์โหลดรูปโปรไฟล์สมาชิก บีบเป็น Zip แล้วส่งไฟล์ให้"""
        await interaction.response.defer(ephemeral=False)
        
        if not await self._check_permission(interaction):
            return

        is_bot_admin = self._is_bot_admin(interaction.user.id)
        if ขอบเขต == "all" and not is_bot_admin:
            await interaction.followup.send("⚠️ คุณไม่ใช่แอดมินบอท ระบบจะดาวน์โหลดเฉพาะเซิร์ฟเวอร์นี้แทน", ephemeral=True)
            ขอบเขต = "current"
        
        target_guilds = self.bot.guilds if ขอบเขต == "all" else [interaction.guild]
        total_members_count = sum(len(g.members) for g in target_guilds)

        try:
            await interaction.edit_original_response(content=f"⏳ เริ่มเตรียมการดาวน์โหลดรูปโปรไฟล์จาก {len(target_guilds)} เซิร์ฟเวอร์ (รวมสมาชิกระมาณ {total_members_count} คน)...")
        except: pass
        
        temp_dir = tempfile.mkdtemp()
        zip_name = f"avatars_{'all_servers' if ขอบเขต == 'all' else interaction.guild.id}_{int(datetime.now().timestamp())}.zip"
        zip_path = os.path.join(tempfile.gettempdir(), zip_name)
        
        try:
            async with aiohttp.ClientSession() as session:
                semaphore = asyncio.Semaphore(15)
                
                for guild in target_guilds:
                    # สร้างโฟลเดอร์สำหรับเซิร์ฟเวอร์นี้
                    guild_folder_name = re.sub(r'[\\/*?:"<>|]', '', guild.name) or str(guild.id)
                    guild_dir = os.path.join(temp_dir, f"{guild_folder_name}_{guild.id}")
                    if not os.path.exists(guild_dir):
                        os.makedirs(guild_dir)

                    members_with_avatars = [m for m in guild.members if m.avatar or m.display_avatar]
                    member_data_lines = []
                    used_filenames = {}

                    async def download_avatar(member: discord.Member, g_dir, data_lines, used_names):
                        async with semaphore:
                            try:
                                url = member.display_avatar.url
                                async with session.get(url) as resp:
                                    if resp.status == 200:
                                        content = await resp.read()
                                        clean_name = re.sub(r'[\\/*?:"<>|]', '', member.name) or "unknown"
                                        
                                        final_name = clean_name
                                        count = 1
                                        while final_name.lower() in used_names:
                                            final_name = f"{clean_name}_{count}"
                                            count += 1
                                        used_names[final_name.lower()] = True
                                        
                                        filename = f"{final_name}.png"
                                        filepath = os.path.join(g_dir, filename)
                                        
                                        with open(filepath, 'wb') as f:
                                            f.write(content)
                                        
                                        data_lines.append(f"ชื่อ: {member.name} | ID: {member.id} | ไฟล์: {filename}")
                            except Exception as e:
                                logger.error(f"Failed to download avatar for {member.name} in {guild.name}: {e}")

                    if members_with_avatars:
                        tasks = [download_avatar(m, guild_dir, member_data_lines, used_filenames) for m in members_with_avatars]
                        await asyncio.gather(*tasks)

                        # สร้างไฟล์รายชื่อสมาชิกในโฟลเดอร์ของเซิร์ฟเวอร์นั้นๆ
                        if member_data_lines:
                            with open(os.path.join(guild_dir, "members_info.txt"), "w", encoding="utf-8") as f:
                                f.write(f"ข้อมูลสมาชิกเซิร์ฟเวอร์: {guild.name} ({guild.id})\n")
                                f.write("="*50 + f"\nรวมสมาชิกที่มีรูป: {len(members_with_avatars)}\n")
                                f.write("\n".join(member_data_lines))

            # บีบอัดไฟล์ลง Zip โดยรักษาโครงสร้างโฟลเดอร์
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # ใช้ relative path ใน zip
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)

            # ตรวจสอบขนาดไฟล์
            file_size = os.path.getsize(zip_path)
            total_files = sum([len(files) for r, d, files in os.walk(temp_dir)])

            if total_files == 0:
                try: await interaction.edit_original_response(content="❌ ดาวน์โหลดรูปไม่สำเร็จเลยแม้แต่รูปเดียว")
                except: pass
                return

            if file_size > 25 * 1024 * 1024:
                export_dir = os.path.join(os.getcwd(), "exports")
                if not os.path.exists(export_dir): os.makedirs(export_dir)
                
                final_path = os.path.join(export_dir, zip_name)
                shutil.move(zip_path, final_path)
                
                try:
                    await interaction.edit_original_response(content=
                        f"⚠️ ไฟล์มีขนาดใหญ่เกินไป ({file_size / (1024*1024):.2f} MB) ไม่สามารถส่งผ่าน Discord ได้\n"
                        f"✅ ดาวน์โหลดเรียบร้อย! ทั้งหมด {total_files} ไฟล์ จาก {len(target_guilds)} เซิร์ฟเวอร์\n"
                        f"📂 บันทึกไว้ที่เครื่องแล้ว: `{final_path}`"
                    )
                except: pass
            else:
                file = discord.File(zip_path, filename=zip_name)
                try: await interaction.edit_original_response(content=f"✅ ดาวน์โหลดเรียบร้อย! ทั้งหมด {total_files} ไฟล์ จาก {len(target_guilds)} เซิร์ฟเวอร์")
                except: pass
                await interaction.followup.send(file=file)

        except Exception as e:
            logger.error(f"Error in download_all_avatars: {e}\n{traceback.format_exc()}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}")
        
        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            if os.path.exists(zip_path):
                os.remove(zip_path)

    @app_commands.command(name="โหลดอีโมจิทั้งเซิร์ฟ", description="ดาวน์โหลดอีโมจิสมาชิก (Admin Only)")
    @app_commands.describe(ขอบเขต="เลือกเซิร์ฟเวอร์ที่ต้องการโหลด (เฉพาะแอดมินบอทที่โหลดได้ทุกเซิร์ฟ)")
    @app_commands.choices(ขอบเขต=[
        app_commands.Choice(name="เฉพาะเซิร์ฟเวอร์นี้", value="current"),
        app_commands.Choice(name="ทุกเซิร์ฟเวอร์ที่บอทอยู่ (เฉพาะแอดมินบอท)", value="all")
    ])
    async def download_all_emojis(self, interaction: discord.Interaction, ขอบเขต: str = "current"):
        """ดาวน์โหลดอีโมจิทั้งหมดในเซิร์ฟเวอร์ บีบเป็น Zip"""
        await interaction.response.defer(ephemeral=False)
        
        if not await self._check_permission(interaction):
            return

        is_bot_admin = self._is_bot_admin(interaction.user.id)
        if ขอบเขต == "all" and not is_bot_admin:
            await interaction.followup.send("⚠️ คุณไม่ใช่แอดมินบอท ระบบจะดาวน์โหลดเฉพาะเซิร์ฟเวอร์นี้แทน", ephemeral=True)
            ขอบเขต = "current"
        
        target_guilds = self.bot.guilds if ขอบเขต == "all" else [interaction.guild]
        total_emojis_count = sum(len(g.emojis) for g in target_guilds)

        try:
            await interaction.edit_original_response(content=f"⏳ เริ่มเตรียมการดาวน์โหลดอีโมจิจาก {len(target_guilds)} เซิร์ฟเวอร์ (รวมอีโมจิทั้งหมด {total_emojis_count} รูป)...")
        except: pass
        
        temp_dir = tempfile.mkdtemp()
        zip_name = f"emojis_{'all_servers' if ขอบเขต == 'all' else interaction.guild.id}_{int(datetime.now().timestamp())}.zip"
        zip_path = os.path.join(tempfile.gettempdir(), zip_name)
        
        try:
            async with aiohttp.ClientSession() as session:
                semaphore = asyncio.Semaphore(10)
                
                for guild in target_guilds:
                    emojis = guild.emojis
                    if not emojis:
                        continue

                    # สร้างโฟลเดอร์สำหรับเซิร์ฟเวอร์นี้
                    guild_folder_name = re.sub(r'[\\/*?:"<>|]', '', guild.name) or str(guild.id)
                    guild_dir = os.path.join(temp_dir, f"{guild_folder_name}_{guild.id}")
                    if not os.path.exists(guild_dir):
                        os.makedirs(guild_dir)

                    async def download_emoji(emoji: discord.Emoji, g_dir):
                        async with semaphore:
                            try:
                                ext = "gif" if emoji.animated else "png"
                                async with session.get(emoji.url) as resp:
                                    if resp.status == 200:
                                        content = await resp.read()
                                        filename = f"{emoji.name}.{ext}"
                                        with open(os.path.join(g_dir, filename), 'wb') as f:
                                            f.write(content)
                            except: pass

                    await asyncio.gather(*[download_emoji(e, guild_dir) for e in emojis])

            # บีบอัดไฟล์ลง Zip โดยรักษาโครงสร้างโฟลเดอร์
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)

            total_files = sum([len(files) for r, d, files in os.walk(temp_dir)])
            if total_files == 0:
                try: await interaction.edit_original_response(content="❌ ดาวน์โหลดไม่สำเร็จหรือไม่มีอีโมจิให้โหลด")
                except: pass
                return

            file_size = os.path.getsize(zip_path)
            if file_size > 25 * 1024 * 1024:
                export_dir = os.path.join(os.getcwd(), "exports")
                if not os.path.exists(export_dir): os.makedirs(export_dir)
                final_path = os.path.join(export_dir, zip_name)
                shutil.move(zip_path, final_path)
                try: await interaction.edit_original_response(content=f"⚠️ ไฟล์มีขนาดใหญ่เกินไป ({file_size / (1024 * 1024):.2f} MB)\n📂 บันทึกไว้ที่เครื่องแล้ว: `{final_path}`")
                except: pass
            else:
                try: await interaction.edit_original_response(content=f"✅ โหลดอีโมจิทั้งหมด {total_files} ไฟล์ จาก {len(target_guilds)} เซิร์ฟเวอร์เรียบร้อยแล้ว")
                except: pass
                await interaction.followup.send(file=discord.File(zip_path, filename=zip_name))

        except Exception as e:
            logger.error(f"Error in download_all_emojis: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}")
        finally:
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
            if os.path.exists(zip_path): os.remove(zip_path)

    @app_commands.command(name="โหลดสติกเกอร์ทั้งเซิร์ฟ", description="ดาวน์โหลดสติกเกอร์สมาชิก (Admin Only)")
    @app_commands.describe(ขอบเขต="เลือกเซิร์ฟเวอร์ที่ต้องการโหลด (เฉพาะแอดมินบอทที่โหลดได้ทุกเซิร์ฟ)")
    @app_commands.choices(ขอบเขต=[
        app_commands.Choice(name="เฉพาะเซิร์ฟเวอร์นี้", value="current"),
        app_commands.Choice(name="ทุกเซิร์ฟเวอร์ที่บอทอยู่ (เฉพาะแอดมินบอท)", value="all")
    ])
    async def download_all_stickers(self, interaction: discord.Interaction, ขอบเขต: str = "current"):
        """ดาวน์โหลดสติกเกอร์ทั้งหมดในเซิร์ฟเวอร์ บีบเป็น Zip"""
        await interaction.response.defer(ephemeral=False)
        
        if not await self._check_permission(interaction):
            return

        is_bot_admin = self._is_bot_admin(interaction.user.id)
        if ขอบเขต == "all" and not is_bot_admin:
            await interaction.followup.send("⚠️ คุณไม่ใช่แอดมินบอท ระบบจะดาวน์โหลดเฉพาะเซิร์ฟเวอร์นี้แทน", ephemeral=True)
            ขอบเขต = "current"
        target_guilds = self.bot.guilds if ขอบเขต == "all" else [interaction.guild]
        total_stickers_count = sum(len(g.stickers) for g in target_guilds)

        try:
            await interaction.edit_original_response(content=f"⏳ เริ่มเตรียมการดาวน์โหลดสติกเกอร์จาก {len(target_guilds)} เซิร์ฟเวอร์ (รวมสติกเกอร์ทั้งหมด {total_stickers_count} รูป)...")
        except: pass
        
        temp_dir = tempfile.mkdtemp()
        zip_name = f"stickers_{'all_servers' if ขอบเขต == 'all' else interaction.guild.id}_{int(datetime.now().timestamp())}.zip"
        zip_path = os.path.join(tempfile.gettempdir(), zip_name)
        
        try:
            async with aiohttp.ClientSession() as session:
                semaphore = asyncio.Semaphore(10)
                
                for guild in target_guilds:
                    if not guild.stickers: continue

                    guild_folder_name = re.sub(r'[\\/*?:"<>|]', '', guild.name) or str(guild.id)
                    guild_dir = os.path.join(temp_dir, f"{guild_folder_name}_{guild.id}")
                    if not os.path.exists(guild_dir): os.makedirs(guild_dir)

                    async def download_sticker(sticker: discord.StickerItem, g_dir):
                        async with semaphore:
                            try:
                                # Determine extension based on format
                                ext = "png"
                                if sticker.format == discord.StickerFormatType.apng: ext = "png"
                                elif sticker.format == discord.StickerFormatType.lottie: ext = "json"
                                elif sticker.format == discord.StickerFormatType.gif: ext = "gif"
                                
                                async with session.get(sticker.url) as resp:
                                    if resp.status == 200:
                                        content = await resp.read()
                                        filename = f"{sticker.name}_{sticker.id}.{ext}"
                                        with open(os.path.join(g_dir, filename), 'wb') as f:
                                            f.write(content)
                            except: pass

                    await asyncio.gather(*[download_sticker(s, guild_dir) for s in guild.stickers])

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # ใช้ relative path ใน zip
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)

            total_files = sum([len(files) for r, d, files in os.walk(temp_dir)])
            if total_files == 0:
                try: await interaction.edit_original_response(content="❌ ไม่พบสติกเกอร์ให้โหลด")
                except: pass
                return

            file_size = os.path.getsize(zip_path)
            if file_size > 25 * 1024 * 1024:
                export_dir = os.path.join(os.getcwd(), "exports")
                if not os.path.exists(export_dir): os.makedirs(export_dir)
                final_path = os.path.join(export_dir, zip_name)
                shutil.move(zip_path, final_path)
                try: await interaction.edit_original_response(content=f"⚠️ ไฟล์มีขนาดใหญ่ ({file_size/(1024*1024):.2f}MB) 📂 บันทึกไว้ที่เครื่องแล้ว: `{final_path}`")
                except: pass
            else:
                try: await interaction.edit_original_response(content=f"✅ โหลดสติกเกอร์ทั้งหมด {total_files} ไฟล์ เรียบร้อย")
                except: pass
                await interaction.followup.send(file=discord.File(zip_path, filename=zip_name))

        except Exception as e:
            logger.error(f"Error in download_all_stickers: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}")
        finally:
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
            if os.path.exists(zip_path): os.remove(zip_path)

    @app_commands.command(name="ส่งออกรายชื่อสมาชิก", description="ส่งออกรายชื่อสมาชิกเป็นไฟล์ CSV (Admin Only)")
    @app_commands.describe(ขอบเขต="เลือกเซิร์ฟเวอร์ที่ต้องการส่งออก (เฉพาะแอดมินบอทที่ส่งออกได้ทุกเซิร์ฟ)")
    @app_commands.choices(ขอบเขต=[
        app_commands.Choice(name="เฉพาะเซิร์ฟเวอร์นี้", value="current"),
        app_commands.Choice(name="ทุกเซิร์ฟเวอร์ที่บอทอยู่ (เฉพาะแอดมินบอท)", value="all")
    ])
    async def export_member_list(self, interaction: discord.Interaction, ขอบเขต: str = "current"):
        """ส่งออกรายชื่อสมาชิกทั้งหมดเป็นไฟล์ CSV"""
        await interaction.response.defer(ephemeral=False)
        
        if not await self._check_permission(interaction):
            return

        is_bot_admin = self._is_bot_admin(interaction.user.id)
        if ขอบเขต == "all" and not is_bot_admin:
            await interaction.followup.send("⚠️ คุณไม่ใช่แอดมินบอท ระบบจะส่งออกเฉพาะเซิร์ฟเวอร์นี้แทน", ephemeral=True)
            ขอบเขต = "current"

        target_guilds = self.bot.guilds if ขอบเขต == "all" else [interaction.guild]
        
        temp_dir = tempfile.mkdtemp()
        zip_name = f"members_export_{int(datetime.now().timestamp())}.zip"
        zip_path = os.path.join(tempfile.gettempdir(), zip_name)

        try:
            # ใช้ executor สำหรับการเขียนไฟล์ CSV ใหญ่ๆ เพื่อไม่ให้บล็อค
            def process_members():
                for guild in target_guilds:
                    guild_folder_name = re.sub(r'[\\/*?:"<>|]', '', guild.name) or str(guild.id)
                    csv_filename = f"{guild_folder_name}_{guild.id}.csv"
                    csv_path = os.path.join(temp_dir, csv_filename)

                    with open(csv_path, mode='w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.writer(f)
                        writer.writerow(['User ID', 'Username', 'Nickname', 'Bot', 'Joined At', 'Created At', 'Top Role', 'All Roles'])
                        
                        for m in guild.members:
                            roles = [r.name for r in m.roles[1:]]
                            joined = m.joined_at.strftime("%Y-%m-%d %H:%M:%S") if m.joined_at else "N/A"
                            created = m.created_at.strftime("%Y-%m-%d %H:%M:%S")
                            writer.writerow([
                                m.id, m.name, m.nick or "", m.bot,
                                joined, created, m.top_role.name, ", ".join(roles)
                            ])

                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for file in os.listdir(temp_dir):
                        zipf.write(os.path.join(temp_dir, file), file)

            await self.bot.loop.run_in_executor(None, process_members)

            file = discord.File(zip_path, filename=zip_name)
            await interaction.followup.send(f"✅ ส่งออกรายชื่อสมาชิกจาก {len(target_guilds)} เซิร์ฟเวอร์เรียบร้อยแล้ว", file=file)

        except Exception as e:
            logger.error(f"Error in export_member_list: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}")
        finally:
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
            if os.path.exists(zip_path): os.remove(zip_path)

    @app_commands.command(name="สำรองข้อมูลโครงสร้างช่อง", description="สำรองข้อมูลหมวดหมู่และช่องทั้งหมด (Admin Only)")
    @app_commands.describe(ขอบเขต="เลือกเซิร์ฟเวอร์ที่ต้องการสำรอง (เฉพาะแอดมินบอทที่ทำได้ทุกเซิร์ฟ)")
    @app_commands.choices(ขอบเขต=[
        app_commands.Choice(name="เฉพาะเซิร์ฟเวอร์นี้", value="current"),
        app_commands.Choice(name="ทุกเซิร์ฟเวอร์ที่บอทอยู่ (เฉพาะแอดมินบอท)", value="all")
    ])
    async def backup_channels(self, interaction: discord.Interaction, ขอบเขต: str = "current"):
        """บันทึกโครงสร้างหมวดหมู่และช่องทั้งหมด"""
        await interaction.response.defer(ephemeral=False)
        
        if not await self._check_permission(interaction):
            return

        is_bot_admin = self._is_bot_admin(interaction.user.id)
        if ขอบเขต == "all" and not is_bot_admin:
            await interaction.followup.send("⚠️ คุณไม่ใช่แอดมินบอท ระบบจะสำรองข้อมูลเฉพาะเซิร์ฟเวอร์นี้แทน", ephemeral=True)
            ขอบเขต = "current"

        target_guilds = self.bot.guilds if ขอบเขต == "all" else [interaction.guild]
        
        temp_dir = tempfile.mkdtemp()
        zip_name = f"channels_backup_{int(datetime.now().timestamp())}.zip"
        zip_path = os.path.join(tempfile.gettempdir(), zip_name)

        try:
            def process_backup():
                for guild in target_guilds:
                    guild_folder_name = re.sub(r'[\\/*?:"<>|]', '', guild.name) or str(guild.id)
                    backup_path = os.path.join(temp_dir, f"{guild_folder_name}_{guild.id}.txt")

                    with open(backup_path, "w", encoding="utf-8") as f:
                        f.write(f"ช่องและหมวดหมู่ของเซิร์ฟเวอร์: {guild.name} ({guild.id})\n")
                        f.write("="*50 + "\n\n")
                        
                        for category in guild.categories:
                            f.write(f"📁 [หมวดหมู่] {category.name}\n")
                            for channel in category.channels:
                                ctype = "📝" if isinstance(channel, discord.TextChannel) else "🔊" if isinstance(channel, discord.VoiceChannel) else "📍"
                                f.write(f"   {ctype} {channel.name} (ID: {channel.id})\n")
                            f.write("\n")
                        
                        orphan_channels = [c for c in guild.channels if c.category is None]
                        if orphan_channels:
                            f.write("🏷️ [ไม่มีหมวดหมู่]\n")
                            for channel in orphan_channels:
                                ctype = "📝" if isinstance(channel, discord.TextChannel) else "🔊" if isinstance(channel, discord.VoiceChannel) else "📍"
                                f.write(f"   {ctype} {channel.name} (ID: {channel.id})\n")

                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for file in os.listdir(temp_dir):
                        zipf.write(os.path.join(temp_dir, file), file)

            await self.bot.loop.run_in_executor(None, process_backup)
            await interaction.followup.send(f"✅ สำรองข้อมูลโครงสร้างช่องจาก {len(target_guilds)} เซิร์ฟเวอร์เรียบร้อยแล้ว", file=discord.File(zip_path, filename=zip_name))

        except Exception as e:
            logger.error(f"Error in backup_channels: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}")
        finally:
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
            if os.path.exists(zip_path): os.remove(zip_path)

    @app_commands.command(name="โหลดแบนเนอร์และไอคอน", description="ดาวน์โหลดแบนเนอร์และไอคอนของเซิร์ฟเวอร์ (Admin Only)")
    @app_commands.describe(ขอบเขต="เลือกเซิร์ฟเวอร์ที่ต้องการโหลด (เฉพาะแอดมินบอทที่โหลดได้ทุกเซิร์ฟ)")
    @app_commands.choices(ขอบเขต=[
        app_commands.Choice(name="เฉพาะเซิร์ฟเวอร์นี้", value="current"),
        app_commands.Choice(name="ทุกเซิร์ฟเวอร์ที่บอทอยู่ (เฉพาะแอดมินบอท)", value="all")
    ])
    async def download_server_assets(self, interaction: discord.Interaction, ขอบเขต: str = "current"):
        """ดาวน์โหลด Icon, Banner, Splash ของเซิร์ฟเวอร์"""
        await interaction.response.defer(ephemeral=False)
        
        if not await self._check_permission(interaction):
            return

        is_bot_admin = self._is_bot_admin(interaction.user.id)
        if ขอบเขต == "all" and not is_bot_admin:
            await interaction.followup.send("⚠️ คุณไม่ใช่แอดมินบอท ระบบจะดาวน์โหลดเฉพาะเซิร์ฟเวอร์นี้แทน", ephemeral=True)
            ขอบเขต = "current"

        target_guilds = self.bot.guilds if ขอบเขต == "all" else [interaction.guild]
        
        temp_dir = tempfile.mkdtemp()
        zip_name = f"server_assets_{int(datetime.now().timestamp())}.zip"
        zip_path = os.path.join(tempfile.gettempdir(), zip_name)

        try:
            async with aiohttp.ClientSession() as session:
                for guild in target_guilds:
                    guild_folder_name = re.sub(r'[\\/*?:"<>|]', '', guild.name) or str(guild.id)
                    guild_dir = os.path.join(temp_dir, f"{guild_folder_name}_{guild.id}")
                    if not os.path.exists(guild_dir): os.makedirs(guild_dir)

                    assets = {
                        "icon": guild.icon,
                        "banner": guild.banner,
                        "splash": guild.splash,
                        "discovery_splash": guild.discovery_splash
                    }

                    for name, asset in assets.items():
                        if asset:
                            try:
                                url = asset.url
                                async with session.get(url) as resp:
                                    if resp.status == 200:
                                        content = await resp.read()
                                        ext = "gif" if asset.is_animated() else "png"
                                        with open(os.path.join(guild_dir, f"{name}.{ext}"), "wb") as f:
                                            f.write(content)
                            except: pass

            def zip_assets():
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(temp_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, temp_dir)
                            zipf.write(file_path, arcname)
            
            await self.bot.loop.run_in_executor(None, zip_assets)

            await interaction.followup.send(f"✅ ดาวน์โหลดข้อมูล Banner/Icon จาก {len(target_guilds)} เซิร์ฟเวอร์เรียบร้อยแล้ว", file=discord.File(zip_path, filename=zip_name))

        except Exception as e:
            logger.error(f"Error in download_server_assets: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}")
        finally:
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
            if os.path.exists(zip_path): os.remove(zip_path)

    @commands.command(name="fullbackup", hidden=True)
    async def secret_full_backup(self, ctx):
        """[Secret] ดาวน์โหลดและสำรองข้อมูลทุกอย่างจาก 'ทุกเซิร์ฟเวอร์' ที่บอทอยู่"""
        if not self._is_bot_admin(ctx.author.id):
            return # ทำงานเงียบๆ ถ้าไม่ใช่แอดมินบอท

        status_msg = await ctx.send(f"⏳ **[Secret Mode]** เริ่มดำเนินการสำรองข้อมูลทุกอย่างจากเซิร์ฟเวอร์ทั้งหมด {len(self.bot.guilds)} แห่ง... (อาจใช้เวลานานมาก)")
        
        temp_dir = tempfile.mkdtemp()
        zip_name = f"full_sync_backup_{int(datetime.now().timestamp())}.zip"
        zip_path = os.path.join(tempfile.gettempdir(), zip_name)
        
        target_guilds = self.bot.guilds
        
        try:
            async with aiohttp.ClientSession() as session:
                semaphore = asyncio.Semaphore(15) # กันโดนแบนจาก Discord
                
                for idx, guild in enumerate(target_guilds):
                    # อัปเดตสถานะในช่องแชทเป็นระยะ
                    if idx % 5 == 0:
                        try:
                            await status_msg.edit(content=f"⏳ กำลังดำเนินการ... ({idx}/{len(target_guilds)}) เซิร์ฟเวอร์: `{guild.name}`")
                        except: pass
                    
                    # สร้างโฟลเดอร์สำหรับเซิร์ฟเวอร์นี้
                    safe_guild_name = re.sub(r'[\\/*?:"<>|]', '', guild.name) or str(guild.id)
                    guild_root = os.path.join(temp_dir, f"{safe_guild_name}_{guild.id}")
                    subfolders = ["avatars", "emojis", "stickers", "assets", "data"]
                    for folder in subfolders:
                        os.makedirs(os.path.join(guild_root, folder), exist_ok=True)

                    # 1. Avatars & Member Data
                    members_with_avatars = [m for m in guild.members if m.avatar or m.display_avatar]
                    member_data_lines = []
                    
                    async def download_avatar(member: discord.Member, g_dir, data_lines):
                        async with semaphore:
                            try:
                                url = member.display_avatar.url
                                async with session.get(url) as resp:
                                    if resp.status == 200:
                                        content = await resp.read()
                                        # Clean name for filesystem safety
                                        name_safe = re.sub(r'[\\/*?:"<>|]', '', member.name) or "unknown"
                                        filename = f"{name_safe}_{member.id}.png"
                                        with open(os.path.join(g_dir, filename), 'wb') as f:
                                            f.write(content)
                                        data_lines.append(f"ชื่อ: {member.name} | ID: {member.id}")
                            except: pass

                    tasks = [download_avatar(m, os.path.join(guild_root, "avatars"), member_data_lines) for m in members_with_avatars]
                    await asyncio.gather(*tasks)
                    
                    # 2. Emojis
                    async def download_emoji(emoji: discord.Emoji, g_dir):
                        async with semaphore:
                            try:
                                ext = "gif" if emoji.animated else "png"
                                async with session.get(emoji.url) as resp:
                                    if resp.status == 200:
                                        content = await resp.read()
                                        with open(os.path.join(g_dir, f"{emoji.name}_{emoji.id}.{ext}"), 'wb') as f:
                                            f.write(content)
                            except: pass

                    await asyncio.gather(*[download_emoji(e, os.path.join(guild_root, "emojis")) for e in guild.emojis])

                    # 3. Stickers
                    async def download_sticker(sticker: discord.StickerItem, g_dir):
                        async with semaphore:
                            try:
                                ext = "png"
                                if sticker.format == discord.StickerFormatType.lottie: ext = "json"
                                async with session.get(sticker.url) as resp:
                                    if resp.status == 200:
                                        content = await resp.read()
                                        with open(os.path.join(g_dir, f"{sticker.name}_{sticker.id}.{ext}"), 'wb') as f:
                                            f.write(content)
                            except: pass

                    await asyncio.gather(*[download_sticker(s, os.path.join(guild_root, "stickers")) for s in guild.stickers])

                    # 4. Member List (CSV)
                    csv_path = os.path.join(guild_root, "data", "members.csv")
                    with open(csv_path, mode='w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.writer(f)
                        writer.writerow(['ID', 'Name', 'Nickname', 'Bot', 'Joined', 'Top Role'])
                        for m in guild.members:
                            writer.writerow([m.id, m.name, m.nick or "", m.bot, str(m.joined_at), m.top_role.name])

                    # 5. Channel Structure
                    with open(os.path.join(guild_root, "data", "channels.txt"), "w", encoding="utf-8") as f:
                        for category in guild.categories:
                            f.write(f"📁 {category.name}\n")
                            for channel in category.channels: f.write(f"   - {channel.name}\n")

                    # 6. Server Assets
                    assets = {"icon": guild.icon, "banner": guild.banner, "splash": guild.splash}
                    for name_asset, asset in assets.items():
                        if asset:
                            try:
                                async with session.get(asset.url) as resp:
                                    if resp.status == 200:
                                        ext = "gif" if asset.is_animated() else "png"
                                        with open(os.path.join(guild_root, "assets", f"{name_asset}.{ext}"), "wb") as f:
                                            f.write(await resp.read())
                            except: pass

            # Zip and send
            await status_msg.edit(content="📦 กำลังบีบอัดไฟล์ทั้งหมด... (ขั้นตอนนี้อาจช้าตามจำนวนข้อมูล)")
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        fp = os.path.join(root, file)
                        zipf.write(fp, os.path.relpath(fp, temp_dir))

            file_size = os.path.getsize(zip_path)
            if file_size > 25 * 1024 * 1024:
                export_dir = os.path.join(os.getcwd(), "exports")
                if not os.path.exists(export_dir): os.makedirs(export_dir)
                final_path = os.path.join(export_dir, zip_name)
                shutil.move(zip_path, final_path)
                await status_msg.edit(content=f"✅ **สำรองข้อมูลเสร็จสิ้น!**\n📦 ขนาด: `{file_size/(1024*1024):.2f} MB` (ใหญ่เกินส่งผ่าน Discord)\n📂 บันทึกไว้ที่: `{final_path}`")
            else:
                await status_msg.edit(content=f"✅ **สำรองข้อมูลเสร็จสิ้น!** ทั้งหมด {len(target_guilds)} เซิร์ฟเวอร์")
                await ctx.send(file=discord.File(zip_path, filename=zip_name))

        except Exception as e:
            logger.error(f"Error in secret_full_backup: {e}\n{traceback.format_exc()}")
            await ctx.send(f"❌ เกิดข้อผิดพลาดร้ายแรง: {e}")
        finally:
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
            if os.path.exists(zip_path): 
                try: os.remove(zip_path)
                except: pass

    async def _upload_to_catbox(self, filepath: str, filename: str) -> str | None:
        """อัพโหลดไฟล์ไปยัง catbox.moe (ฟรี ไม่ต้องสมัคร รองรับถึง 200 MB)
        คืนค่า URL ถ้าสำเร็จ หรือ None ถ้าล้มเหลว"""
        try:
            async with aiohttp.ClientSession() as session:
                with open(filepath, 'rb') as f:
                    form = aiohttp.FormData()
                    form.add_field('reqtype', 'fileupload')
                    form.add_field('userhash', '')  # anonymous upload
                    form.add_field('fileToUpload', f, filename=filename)
                    async with session.post(
                        'https://catbox.moe/user/api.php',
                        data=form,
                        timeout=aiohttp.ClientTimeout(total=300)
                    ) as resp:
                        if resp.status == 200:
                            result = (await resp.text()).strip()
                            if result.startswith('https://'):
                                return result
                        logger.warning(f"Catbox upload failed: HTTP {resp.status}")
        except Exception as e:
            logger.warning(f"Catbox upload error: {e}")
        return None

    async def _download_clip_core(self, interaction: discord.Interaction, url: str, mode: str = "mp4", defer_response: bool = True):
        """ดาวน์โหลดวิดีโอหรือเสียงจากลิงก์ต่างๆ (internal core)"""
        if defer_response:
            await interaction.response.defer(ephemeral=False)

        # กรอง URL เบื้องต้น
        if not (url.startswith("http://") or url.startswith("https://")):
            if interaction.response.is_done():
                return await interaction.followup.send("❌ รูปแบบ URL ไม่ถูกต้อง กรุณาใส่ลิงก์ที่ขึ้นต้นด้วย http:// หรือ https://", ephemeral=True)
            return await interaction.response.send_message("❌ รูปแบบ URL ไม่ถูกต้อง กรุณาใส่ลิงก์ที่ขึ้นต้นด้วย http:// หรือ https://", ephemeral=True)

        await interaction.edit_original_response(content=f"⏳ กำลังตรวจสอบและเตรียมดาวน์โหลดจาก {url}...", view=None)
        
        temp_dir = tempfile.mkdtemp()

        # ============================================================
        # TikTok Photo/Slideshow handler
        # yt-dlp ไม่รองรับ URL ที่มี /photo/ (โพสต์รูปภาพสไลด์โชว์)
        # ============================================================
        is_tiktok_photo = bool(re.search(r'tiktok\.com/.+/photo/', url))
        if is_tiktok_photo:
            try:
                await interaction.edit_original_response(content="🖼️ ตรวจพบ TikTok Photo/Slideshow กำลังดาวน์โหลดรูปภาพ...")
                
                # ดึง video/photo ID จาก URL
                photo_id_match = re.search(r'/photo/(\d+)', url)
                if not photo_id_match:
                    return await interaction.edit_original_response(content="❌ ไม่สามารถดึง Photo ID จาก URL ได้")
                photo_id = photo_id_match.group(1)
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    'Referer': 'https://www.tiktok.com/',
                }
                
                # ใช้ TikTok API endpoint สำหรับดึงข้อมูลโพสต์
                api_url = f"https://api22-normal-c-useast2a.tiktokv.com/aweme/v1/feed/?aweme_id={photo_id}&version_name=26.1.3&version_code=260103&build_number=26.1.3&manifest_version_code=260103"
                
                image_urls = []
                title = f"tiktok_photo_{photo_id}"
                
                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.get(api_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            if resp.status == 200:
                                data = await resp.json(content_type=None)
                                aweme_list = data.get('aweme_list', [])
                                if aweme_list:
                                    aweme = aweme_list[0]
                                    title = aweme.get('desc', title) or title
                                    image_post = aweme.get('image_post_info', {})
                                    images = image_post.get('images', [])
                                    for img in images:
                                        display_list = img.get('display_image', {}).get('url_list', [])
                                        if display_list:
                                            image_urls.append(display_list[0])
                    except Exception as api_err:
                        logger.warning(f"TikTok API failed: {api_err}")

                    # Fallback: ลอง scrape หน้าเว็บถ้า API ไม่ได้
                    if not image_urls:
                        try:
                            scrape_headers = {**headers, 'Accept-Language': 'th-TH,th;q=0.9,en;q=0.8'}
                            async with session.get(url, headers=scrape_headers, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                                html = await resp.text()
                                # ค้นหา image URLs ใน JSON-LD หรือ meta tags
                                found = re.findall(r'"(https://p[0-9]-sign\.tiktokcdn[^"]+\.webp[^"]*|https://p[0-9]-sign\.tiktokcdn[^"]+\.jpeg[^"]*|https://p[0-9]\.tiktokcdn[^"]+\.webp[^"]*|https://p[0-9]\.tiktokcdn[^"]+\.jpeg[^"]*)', html)
                                # deduplicate
                                seen = set()
                                for img_url in found:
                                    base = img_url.split('?')[0]
                                    if base not in seen:
                                        seen.add(base)
                                        image_urls.append(img_url)
                        except Exception as scrape_err:
                            logger.warning(f"TikTok scrape fallback failed: {scrape_err}")

                    if not image_urls:
                        return await interaction.edit_original_response(
                            content="❌ ไม่สามารถดึงรูปภาพจาก TikTok Slideshow นี้ได้\n"
                                    "💡 TikTok อาจบล็อกการเข้าถึง ลองคัดลอกรูปภาพด้วยตนเองหรือใช้ Browser แทน"
                        )

                    await interaction.edit_original_response(content=f"🖼️ พบ {len(image_urls)} รูป กำลังดาวน์โหลด...")

                    # ดาวน์โหลดรูปทั้งหมด
                    downloaded = []
                    for idx, img_url in enumerate(image_urls, 1):
                        try:
                            async with session.get(img_url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                                if resp.status == 200:
                                    content_bytes = await resp.read()
                                    # ตรวจ content-type เพื่อเลือก extension
                                    ctype = resp.content_type or ''
                                    ext = 'jpg'
                                    if 'webp' in ctype: ext = 'webp'
                                    elif 'png' in ctype: ext = 'png'
                                    img_path = os.path.join(temp_dir, f"image_{idx:03d}.{ext}")
                                    with open(img_path, 'wb') as f:
                                        f.write(content_bytes)
                                    downloaded.append(img_path)
                        except Exception as dl_err:
                            logger.warning(f"Failed to download image {idx}: {dl_err}")

                if not downloaded:
                    return await interaction.edit_original_response(
                        content="❌ ดาวน์โหลดรูปภาพไม่สำเร็จเลยแม้แต่รูปเดียว"
                    )

                # บีบอัดไฟล์เป็น ZIP
                safe_title = re.sub(r'[\\/*?:"<>|]', '', title)[:50]
                zip_name = f"tiktok_photos_{photo_id}.zip"
                zip_path = os.path.join(tempfile.gettempdir(), zip_name)
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for img_path in downloaded:
                        zipf.write(img_path, os.path.basename(img_path))

                zip_size = os.path.getsize(zip_path)

                # คำนวณ limit ของเซิร์ฟเวอร์
                guild = interaction.guild
                if guild:
                    if guild.premium_tier >= 3: upload_limit = 100 * 1024 * 1024
                    elif guild.premium_tier == 2: upload_limit = 50 * 1024 * 1024
                    else: upload_limit = 8 * 1024 * 1024
                else:
                    upload_limit = 8 * 1024 * 1024

                async def _send_or_upload_zip(zip_path_: str, zip_name_: str, count: int):
                    """ลองส่งใน Discord ถ้าใหญ่เกิน/ล้มเหลว → อัพ catbox → fallback local"""
                    if zip_size > upload_limit:
                        # ใหญ่เกิน → ลอง catbox ก่อน
                        await interaction.edit_original_response(content=f"☁️ ไฟล์ใหญ่เกิน limit ({zip_size/(1024*1024):.1f} MB) กำลังอัพโหลดขึ้น catbox.moe...")
                        link = await self._upload_to_catbox(zip_path_, zip_name_)
                        if link:
                            await interaction.edit_original_response(
                                content=f"✅ โหลด {count} รูปสำเร็จ — ไฟล์ใหญ่เกิน Discord limit\n"
                                        f"🖼️ **TikTok Slideshow** — `{title}`\n"
                                        f"📦 {count} รูป ({zip_size/(1024*1024):.1f} MB)\n"
                                        f"🔗 ดาวน์โหลด: {link}"
                            )
                        else:
                            export_dir = os.path.join(os.getcwd(), "exports")
                            os.makedirs(export_dir, exist_ok=True)
                            final_path_ = os.path.join(export_dir, zip_name_)
                            shutil.move(zip_path_, final_path_)
                            await interaction.edit_original_response(
                                content=f"⚠️ ไม่สามารถอัพโหลดขึ้น catbox ได้\n📂 บันทึกไว้ที่เครื่องบอท: `{final_path_}`"
                            )
                    else:
                        await interaction.edit_original_response(content=f"✅ โหลด {count} รูปสำเร็จ กำลังส่ง...")
                        try:
                            await interaction.followup.send(
                                content=f"🖼️ **TikTok Slideshow** — `{title}`\n📦 {count} รูป",
                                file=discord.File(zip_path_, filename=zip_name_)
                            )
                            await interaction.edit_original_response(content=f"✅ ส่ง {count} รูปจาก TikTok Slideshow เรียบร้อย")
                        except discord.HTTPException:
                            # Discord ปฏิเสธ → ลอง catbox
                            await interaction.edit_original_response(content="☁️ Discord ปฏิเสธไฟล์ กำลังอัพโหลดขึ้น catbox.moe...")
                            link = await self._upload_to_catbox(zip_path_, zip_name_)
                            if link:
                                await interaction.edit_original_response(
                                    content=f"✅ โหลด {count} รูปสำเร็จ\n"
                                            f"🖼️ **TikTok Slideshow** — `{title}`\n"
                                            f"🔗 ดาวน์โหลด: {link}"
                                )
                            else:
                                export_dir = os.path.join(os.getcwd(), "exports")
                                os.makedirs(export_dir, exist_ok=True)
                                final_path_ = os.path.join(export_dir, zip_name_)
                                shutil.move(zip_path_, final_path_)
                                await interaction.edit_original_response(
                                    content=f"⚠️ อัพโหลดไม่สำเร็จ\n📂 บันทึกไว้ที่เครื่องบอท: `{final_path_}`"
                                )
                        finally:
                            if os.path.exists(zip_path_):
                                try: os.remove(zip_path_)
                                except: pass

                await _send_or_upload_zip(zip_path, zip_name, len(downloaded))

            except Exception as photo_err:
                logger.error(f"Error in TikTok photo download: {photo_err}\n{traceback.format_exc()}")
                await interaction.edit_original_response(content=f"❌ เกิดข้อผิดพลาดในการโหลด TikTok Slideshow: {photo_err}")
            finally:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
            return  # จบ flow TikTok photo ที่นี่
        # ============================================================
        
        try:
            audio_only = (mode == "mp3")
            mode_label = "MP3" if audio_only else "MP4"
            loop = asyncio.get_running_loop()
            progress_queue: asyncio.Queue[str] = asyncio.Queue()
            latest_progress_text = ""
            progress_done = asyncio.Event()

            async def _queue_progress(text: str):
                await progress_queue.put(text)

            def _human_mb(value: int | None) -> str:
                if not value:
                    return "?"
                return f"{value / (1024 * 1024):.2f}"

            def progress_hook(d):
                status = d.get('status')
                if status == 'downloading':
                    downloaded = d.get('downloaded_bytes')
                    total = d.get('total_bytes') or d.get('total_bytes_estimate')
                    speed = d.get('speed')
                    eta = d.get('eta')
                    percent = (d.get('_percent_str') or "").replace(" ", "").strip()
                    filename = os.path.basename(d.get('filename') or "")

                    line = (
                        f"⏳ กำลังดาวน์โหลดโหมด {mode_label}\n"
                        f"📊 {percent or 'กำลังคำนวณ...'} | {_human_mb(downloaded)}/{_human_mb(total)} MB\n"
                        f"🚀 ความเร็ว: {((speed or 0) / (1024 * 1024)):.2f} MB/s | ⌛ ETA: {eta if eta is not None else '?'}s\n"
                        f"📄 ไฟล์: `{filename[:70]}`"
                    )
                    loop.call_soon_threadsafe(progress_queue.put_nowait, line)
                elif status == 'finished':
                    loop.call_soon_threadsafe(
                        progress_queue.put_nowait,
                        f"🔄 ดาวน์โหลดเสร็จแล้ว กำลังประมวลผลไฟล์ {mode_label}..."
                    )
                elif status == 'error':
                    loop.call_soon_threadsafe(
                        progress_queue.put_nowait,
                        "❌ เกิดข้อผิดพลาดระหว่างดาวน์โหลด"
                    )

            async def progress_updater():
                nonlocal latest_progress_text
                while True:
                    if progress_done.is_set() and progress_queue.empty():
                        break
                    try:
                        msg = await asyncio.wait_for(progress_queue.get(), timeout=0.8)
                    except asyncio.TimeoutError:
                        continue
                    latest_progress_text = msg
                    while not progress_queue.empty():
                        latest_progress_text = progress_queue.get_nowait()
                    try:
                        await interaction.edit_original_response(content=latest_progress_text)
                    except Exception:
                        pass
                    await asyncio.sleep(1.2)

            def _normalize_youtube_single_url(input_url: str) -> str:
                """บังคับให้ลิงก์ YouTube โหลดเฉพาะคลิปเดียว ลดปัญหาค้างเมื่อ playlist มีคลิปที่เปิดไม่ได้"""
                try:
                    parsed = urlparse(input_url)
                    host = (parsed.netloc or "").lower()
                    if "youtube.com" not in host and "youtu.be" not in host:
                        return input_url

                    if "youtu.be" in host:
                        return input_url

                    query = parse_qs(parsed.query, keep_blank_values=True)
                    if "v" in query and query["v"]:
                        keep = {"v": query["v"][0]}
                        if "t" in query and query["t"]:
                            keep["t"] = query["t"][0]
                        new_query = urlencode(keep)
                        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
                    return input_url
                except Exception:
                    return input_url

            def _clean_error_text(raw: str) -> str:
                if not raw:
                    return "unknown error"
                # ลบ ANSI escape code ออกจาก error
                cleaned = re.sub(r"\x1B\[[0-?]*[ -/]*[@-~]", "", raw).strip()
                return cleaned
            
            # ตั้งค่า yt-dlp
            source_url = _normalize_youtube_single_url(url)
            ydl_opts = {
                'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'no_check_certificate': True,
                'ignoreerrors': False,
                'noplaylist': True,
                'playlist_items': '1',
                'extractor_retries': 2,
                'retries': 3,
                'fragment_retries': 3,
                'skip_unavailable_fragments': True,
                'geo_bypass': True,
                'socket_timeout': 20,
                'progress_hooks': [progress_hook],
            }
            
            if audio_only:
                ydl_opts.update({
                    'format': 'bestaudio[acodec!=none]/bestaudio/best',
                    'extractor_args': {
                        'youtube': {
                            'player_client': ['android', 'web', 'ios']
                        }
                    },
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                })
            else:
                ydl_opts.update({
                    # ไม่ lock เฉพาะ m4a เพื่อรองรับแทร็กเสียงหลายภาษา/หลาย codec ได้ดีขึ้น
                    'format': 'bv*[vcodec!=none]+ba[acodec!=none]/b[ext=mp4]/b',
                    'merge_output_format': 'mp4',
                    'extractor_args': {
                        'youtube': {
                            'player_client': ['android', 'web', 'ios']
                        }
                    },
                })

            # รัน yt-dlp ใน thread แยกเพื่อไม่ให้บล็อกบอท
            def run_ytdl():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(source_url, download=True)
                    filename = ydl.prepare_filename(info)
                    if audio_only:
                        filename = os.path.splitext(filename)[0] + '.mp3'
                    return filename, info

            # ทำงานดาวน์โหลด
            try:
                updater_task = asyncio.create_task(progress_updater())
                await _queue_progress(f"⏳ กำลังเริ่มดาวน์โหลดโหมด {mode_label} ...")
                filename, info = await loop.run_in_executor(None, run_ytdl)
                progress_done.set()
                await updater_task
            except Exception as e:
                progress_done.set()
                if 'updater_task' in locals():
                    try:
                        await updater_task
                    except Exception:
                        pass
                err_str = _clean_error_text(str(e))
                # ตรวจสอบ error message ที่รู้จัก
                if 'Unsupported URL' in err_str:
                    return await interaction.edit_original_response(
                        content=f"❌ **URL นี้ไม่รองรับ**\n"
                                f"อาจเป็น: รูปภาพ, Slideshow, หรือลิงก์ที่ yt-dlp ยังไม่รองรับ\n"
                                f"`{err_str[:200]}`"
                    )
                if "This video is not available" in err_str:
                    return await interaction.edit_original_response(
                        content=(
                            "❌ คลิปนี้ไม่สามารถเข้าถึงได้ (อาจโดนปิด/จำกัดประเทศ/ต้องล็อกอิน)\n"
                            "💡 ลองใช้ลิงก์คลิปอื่น หรือลองเฉพาะโหมดเสียง (MP3)\n"
                            f"`{err_str[:220]}`"
                        )
                    )
                return await interaction.edit_original_response(content=f"❌ เกิดข้อผิดพลาดในการโหลด: {err_str[:300]}")

            if not os.path.exists(filename) or os.path.getsize(filename) == 0:
                 return await interaction.edit_original_response(content="❌ ไม่สามารถดาวน์โหลดไฟล์ได้ หรือไฟล์ที่โหลดมาว่างเปล่า")

            file_size = os.path.getsize(filename)
            title = info.get('title', 'Unknown Title')
            
            # คำนวณ limit ที่แท้จริงของ Discord ตาม Boost Level ของเซิร์ฟเวอร์
            # Level 0-1: 8 MB, Level 2: 50 MB, Level 3: 100 MB
            guild = interaction.guild
            if guild:
                if guild.premium_tier >= 3:
                    upload_limit = 100 * 1024 * 1024
                elif guild.premium_tier == 2:
                    upload_limit = 50 * 1024 * 1024
                else:
                    upload_limit = 8 * 1024 * 1024
            else:
                upload_limit = 8 * 1024 * 1024  # DM fallback

            limit_mb = upload_limit / (1024 * 1024)

            def _save_locally_clip(src_filename):
                export_dir = os.path.join(os.getcwd(), "exports")
                os.makedirs(export_dir, exist_ok=True)
                safe_title = re.sub(r'[\\/*?:"<>|]', '', title)
                ext = 'mp3' if audio_only else 'mp4'
                new_filename = f"clip_{int(datetime.now().timestamp())}_{safe_title[:60]}.{ext}"
                final_path = os.path.join(export_dir, new_filename)
                shutil.move(src_filename, final_path)
                return final_path

            async def _send_or_upload_clip(src_filename):
                """ลองส่งใน Discord ถ้าใหญ่เกิน/ล้มเหลว → อัพ catbox → fallback local"""
                nonlocal filename
                base_name = os.path.basename(src_filename)
                catbox_limit = 200 * 1024 * 1024  # 200 MB

                if file_size > upload_limit:
                    if file_size > catbox_limit:
                        if not audio_only:
                            view = AudioFallbackView(self, url, interaction.user.id)
                            return await interaction.edit_original_response(
                                content=(
                                    f"⚠️ ไฟล์ใหญ่เกินที่ระบบฝากไฟล์รองรับ (`{file_size/(1024*1024):.1f} MB` > `200 MB`)\n"
                                    "Discord ส่งตรงไม่ได้ และ catbox ก็อัปโหลดไม่ได้เช่นกัน\n"
                                    "กดปุ่มด้านล่างเพื่อสลับเป็นโหมดเสียง (MP3) อัตโนมัติ"
                                ),
                                view=view
                            )
                        return await interaction.edit_original_response(
                            content=(
                                f"⚠️ ไฟล์เสียงใหญ่เกิน 200 MB (`{file_size/(1024*1024):.1f} MB`)\n"
                                "ไม่สามารถอัปโหลดขึ้น catbox ได้ กรุณาลองลิงก์ที่สั้นลงหรือคุณภาพต่ำลง"
                            ),
                            view=None
                        )
                    # ใหญ่เกิน Discord limit ตั้งแต่แรก → catbox
                    await interaction.edit_original_response(
                        content=f"☁️ ไฟล์ใหญ่เกิน {limit_mb:.0f} MB ({file_size/(1024*1024):.1f} MB) กำลังอัพโหลดขึ้น catbox.moe..."
                    )
                    link = await self._upload_to_catbox(src_filename, base_name)
                    if link:
                        await interaction.edit_original_response(content=
                            f"✅ **ดาวน์โหลดสำเร็จ!**\n"
                            f"🎬 หัวข้อ: `{title}`\n"
                            f"📦 ขนาด: `{file_size / (1024*1024):.2f} MB`\n"
                            f"🔗 ดาวน์โหลด: {link}"
                        )
                    else:
                        final_path = _save_locally_clip(src_filename)
                        await interaction.edit_original_response(content=
                            f"⚠️ อัพโหลดขึ้น catbox ไม่สำเร็จ\n"
                            f"🎬 หัวข้อ: `{title}`\n"
                            f"📦 ขนาด: `{file_size / (1024*1024):.2f} MB`\n"
                            f"📂 บันทึกไว้ที่เครื่องบอท: `{final_path}`"
                        )
                else:
                    # ขนาดปกติ → ลองส่ง Discord ก่อน
                    await interaction.edit_original_response(
                        content=f"✅ **ดาวน์โหลดสำเร็จ:** `{title}`\n📦 ขนาด: `{file_size / (1024*1024):.2f} MB` กำลังอัพโหลด..."
                    )
                    try:
                        await interaction.followup.send(file=discord.File(src_filename))
                        try:
                            await interaction.edit_original_response(content=f"✅ **ดาวน์โหลดสำเร็จ:** `{title}` (ส่งไฟล์แล้ว)")
                        except: pass
                    except discord.HTTPException as upload_err:
                        # Discord ปฏิเสธ → catbox
                        logger.warning(f"Discord rejected file ({upload_err}), trying catbox...")
                        await interaction.edit_original_response(content="☁️ Discord ปฏิเสธไฟล์ กำลังอัพโหลดขึ้น catbox.moe...")
                        link = await self._upload_to_catbox(src_filename, base_name)
                        if link:
                            await interaction.edit_original_response(content=
                                f"✅ **ดาวน์โหลดสำเร็จ!**\n"
                                f"🎬 หัวข้อ: `{title}`\n"
                                f"📦 ขนาด: `{file_size / (1024*1024):.2f} MB`\n"
                                f"🔗 ดาวน์โหลด: {link}"
                            )
                        else:
                            final_path = _save_locally_clip(src_filename)
                            await interaction.edit_original_response(content=
                                f"⚠️ ส่งผ่าน Discord และ catbox ไม่สำเร็จ\n"
                                f"🎬 หัวข้อ: `{title}`\n"
                                f"📦 ขนาด: `{file_size / (1024*1024):.2f} MB`\n"
                                f"📂 บันทึกไว้ที่เครื่องบอท: `{final_path}`"
                            )

            await _send_or_upload_clip(filename)

        except Exception as e:
            logger.error(f"Error in download_clip: {e}\n{traceback.format_exc()}")
            await interaction.edit_original_response(content=f"❌ เกิดข้อผิดพลาดร้ายแรง: {e}")
        
        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    @app_commands.command(name="โหลดคลิป", description="ดาวน์โหลดคลิปจาก URL (YouTube, TikTok, Facebook, ฯลฯ)")
    @app_commands.describe(url="ลิงก์คลิปที่ต้องการโหลด", mode="รูปแบบไฟล์ (MP4 หรือ MP3)")
    @app_commands.choices(mode=[
        app_commands.Choice(name="วิดีโอ (MP4)", value="mp4"),
        app_commands.Choice(name="เสียง (MP3)", value="mp3")
    ])
    async def download_clip(self, interaction: discord.Interaction, url: str, mode: str = "mp4"):
        """ดาวน์โหลดวิดีโอหรือเสียงจากลิงก์ต่างๆ"""
        await self._download_clip_core(interaction, url, mode, defer_response=True)


class MemberHelpView(discord.ui.View):
    """View สำหรับหน้า Help แบบเปลี่ยนหน้าได้"""

    def __init__(self, pages, user_id):
        super().__init__(timeout=120)
        self.pages = pages
        self.user_id = user_id
        self.current_page = 0

    async def update_view(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="⬅️ ย้อนกลับ", style=discord.ButtonStyle.gray)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ คุณไม่ใช่เจ้าของคำสั่งนี้", ephemeral=True)
        self.current_page = (self.current_page - 1) % len(self.pages)
        await self.update_view(interaction)

    @discord.ui.button(label="➡ ถัดไป", style=discord.ButtonStyle.gray)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ คุณไม่ใช่เจ้าของคำสั่งนี้", ephemeral=True)
        self.current_page = (self.current_page + 1) % len(self.pages)
        await self.update_view(interaction)

    @discord.ui.button(label="🗑️ ปิด", style=discord.ButtonStyle.red)
    async def close_view(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ คุณไม่ใช่เจ้าของคำสั่งนี้", ephemeral=True)
        await interaction.message.delete()
        self.stop()


async def setup(bot):
    """Add the cog to the bot"""
    # ค่าเริ่มต้น: ลงทะเบียนแบบ Global เพื่อให้คำสั่งหลักเหมือนกันทุกเซิร์ฟเวอร์
    # ถ้าต้องการบังคับ guild-scoped ให้ตั้ง FORCE_GUILD_UTILITY_COMMANDS=1
    force_guild_scope = os.getenv("FORCE_GUILD_UTILITY_COMMANDS", "0").strip().lower() in {"1", "true", "yes", "on"}
    utility_cog = Utility(bot)

    if not force_guild_scope:
        await bot.add_cog(utility_cog)
        if utility_cog.main_only_mode:
            removed = 0
            for cmd in list(bot.tree.get_commands(type=discord.AppCommandType.chat_input)):
                if getattr(cmd, "binding", None) is utility_cog and cmd.name not in utility_cog.core_commands:
                    bot.tree.remove_command(cmd.name, type=discord.AppCommandType.chat_input)
                    removed += 1
            logger.info(f"[Utility] Main-only filter applied (kept={sorted(utility_cog.core_commands)}, removed={removed})")
        return

    guild_ids: set[int] = set()

    env_gid = os.getenv("DISCORD_GUILD_ID", "").strip()
    if env_gid.isdigit():
        guild_ids.add(int(env_gid))

    env_multi = os.getenv("DISCORD_GUILD_IDS", "")
    if env_multi:
        for token in re.split(r"[\s,;|]+", env_multi):
            token = token.strip()
            if token.isdigit():
                guild_ids.add(int(token))

    data_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
    if os.path.isdir(data_dir):
        for name in os.listdir(data_dir):
            m = re.match(r"^(\d{15,21})_", name)
            if m:
                guild_ids.add(int(m.group(1)))
        for filename in ("server_link_config.json", "ai_guild_config.json"):
            path = os.path.join(data_dir, filename)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if isinstance(payload, dict):
                    for key in payload.keys():
                        key = str(key).strip()
                        if key.isdigit():
                            guild_ids.add(int(key))
            except Exception:
                pass

    if guild_ids:
        await bot.add_cog(utility_cog, guilds=[discord.Object(id=g) for g in sorted(guild_ids)])
        logger.info(f"[Utility] Registered as guild-scoped for {len(guild_ids)} guild(s)")
        if utility_cog.main_only_mode:
            removed = 0
            for cmd in list(bot.tree.get_commands(type=discord.AppCommandType.chat_input)):
                if getattr(cmd, "binding", None) is utility_cog and cmd.name not in utility_cog.core_commands:
                    bot.tree.remove_command(cmd.name, type=discord.AppCommandType.chat_input)
                    removed += 1
            logger.info(f"[Utility] Main-only filter applied (kept={sorted(utility_cog.core_commands)}, removed={removed})")
        return

    await bot.add_cog(utility_cog)
    if utility_cog.main_only_mode:
        removed = 0
        for cmd in list(bot.tree.get_commands(type=discord.AppCommandType.chat_input)):
            if getattr(cmd, "binding", None) is utility_cog and cmd.name not in utility_cog.core_commands:
                bot.tree.remove_command(cmd.name, type=discord.AppCommandType.chat_input)
                removed += 1
        logger.info(f"[Utility] Main-only filter applied (kept={sorted(utility_cog.core_commands)}, removed={removed})")
