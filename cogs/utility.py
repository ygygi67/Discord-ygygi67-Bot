import discord
from discord import app_commands
from discord.ext import commands
import logging
from datetime import datetime, timedelta, timezone
import platform
import psutil
import os
import humanize
import time
import asyncio
from collections import defaultdict

logger = logging.getLogger('discord_bot')

class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = datetime.now()
        self.active_monitors = {}  # Store active monitors for admin version
        self.public_monitors = {}  # Store active monitors for public version
        self.walking_frames = ["🚶", "🏃", "🚶", "🏃"]  # Walking animation frames
        self.current_frame = 0
        self.cooldowns = defaultdict(lambda: defaultdict(float))
        self.userinfo_cooldown = 300  # 5 minutes cooldown for user info
        self.serverinfo_cooldown = 600  # 10 minutes cooldown for server info
        self.botinfo_cooldown = 300  # 5 minutes cooldown for bot info
        self.stats_cooldown = 900  # 15 minutes cooldown for stats
        logging.info("Utility cog initialized")

    async def cog_load(self):
        """Called when the cog is loaded"""
        try:
            # Sync commands with Discord
            synced = await self.bot.tree.sync()
            logger.info(f"Synced {len(synced)} commands")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")

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
            start_time = time.time()
            api_latency = round((time.time() - start_time) * 1000)
            
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

    @app_commands.command(name="ข้อมูลเซิร์ฟเวอร์", description="แสดงข้อมูลเกี่ยวกับเซิร์ฟเวอร์")
    async def serverinfo(self, interaction: discord.Interaction):
        """แสดงข้อมูลเกี่ยวกับเซิร์ฟเวอร์"""
        try:
            # Check cooldown
            current_time = time.time()
            if current_time - self.cooldowns[interaction.guild.id][interaction.user.id] < self.serverinfo_cooldown:
                remaining = int(self.serverinfo_cooldown - (current_time - self.cooldowns[interaction.guild.id][interaction.user.id]))
                minutes = remaining // 60
                seconds = remaining % 60
                await interaction.response.send_message(f"⏳ กรุณารออีก {minutes} นาที {seconds} วินาทีก่อนใช้คำสั่งนี้อีกครั้ง", ephemeral=True)
                return

            if not interaction.guild:
                await interaction.response.send_message("❌ คำสั่งนี้สามารถใช้ได้เฉพาะในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
                return

            guild = interaction.guild
            
            # Create embed with server icon
            embed = discord.Embed(
                title=f"📊 ข้อมูลเซิร์ฟเวอร์: {guild.name}",
                color=discord.Color.blue()
            )
            
            # Add server icon if available
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            
            # Basic Information
            embed.add_field(
                name="🆔 ID",
                value=f"`{guild.id}`",
                inline=True
            )
            
            # Handle case where guild owner might be None
            owner_info = "ไม่สามารถดึงข้อมูลได้"
            if guild.owner:
                owner_info = f"{guild.owner.mention} ({guild.owner.name})"
            
            embed.add_field(
                name="👑 เจ้าของ",
                value=owner_info,
                inline=True
            )
            
            # Format creation date
            created_at = guild.created_at.strftime("%d/%m/%Y %H:%M:%S")
            embed.add_field(
                name="📅 สร้างเมื่อ",
                value=f"`{created_at}`\n({humanize.naturaltime(guild.created_at)})",
                inline=True
            )
            
            # Member Information
            total_members = guild.member_count
            online_members = len([m for m in guild.members if m.status != discord.Status.offline])
            
            embed.add_field(
                name="👥 สมาชิก",
                value=f"ทั้งหมด: **{total_members}** คน\nออนไลน์: **{online_members}** คน",
                inline=True
            )
            
            # Channel Information
            text_channels = len(guild.text_channels)
            voice_channels = len(guild.voice_channels)
            categories = len(guild.categories)
            
            embed.add_field(
                name="📝 แชแนล",
                value=f"ข้อความ: **{text_channels}**\nเสียง: **{voice_channels}**\nหมวดหมู่: **{categories}**",
                inline=True
            )
            
            # Role Information
            roles = len(guild.roles)
            embed.add_field(
                name="🎭 ยศ",
                value=f"ทั้งหมด: **{roles}** ยศ",
                inline=True
            )
            
            # Boost Information
            if guild.premium_tier > 0:
                embed.add_field(
                    name="💎 บูสต์",
                    value=f"จำนวน: **{guild.premium_subscription_count}** บูสต์\nเลเวล: **{guild.premium_tier}**",
                    inline=True
                )
            
            # Add footer with server ID
            embed.set_footer(text=f"Server ID: {guild.id}")
            
            await interaction.response.send_message(embed=embed)

            # Update cooldown after successful execution
            self.cooldowns[interaction.guild.id][interaction.user.id] = current_time
        except Exception as e:
            await self.cog_app_command_error(interaction, e)

    @app_commands.command(name="ข้อมูลผู้ใช้", description="แสดงข้อมูลเกี่ยวกับผู้ใช้")
    @app_commands.describe(user="ผู้ใช้ที่ต้องการดูข้อมูล (ถ้าไม่ระบุจะแสดงข้อมูลของคุณ)")
    async def userinfo(self, interaction: discord.Interaction, user: discord.User = None):
        """แสดงข้อมูลเกี่ยวกับผู้ใช้"""
        try:
            # Check cooldown
            current_time = time.time()
            if current_time - self.cooldowns[interaction.guild.id][interaction.user.id] < self.userinfo_cooldown:
                remaining = int(self.userinfo_cooldown - (current_time - self.cooldowns[interaction.guild.id][interaction.user.id]))
                minutes = remaining // 60
                seconds = remaining % 60
                await interaction.response.send_message(f"⏳ กรุณารออีก {minutes} นาที {seconds} วินาทีก่อนใช้คำสั่งนี้อีกครั้ง", ephemeral=True)
                return

            target = user or interaction.user
            member = interaction.guild.get_member(target.id) if interaction.guild else None
            
            # Create embed with user's color
            embed = discord.Embed(
                title=f"👤 ข้อมูลผู้ใช้: {target.name}",
                color=target.color if hasattr(target, 'color') else discord.Color.blue()
            )
            
            # Add user avatar
            if target.avatar:
                embed.set_thumbnail(url=target.avatar.url)
            
            # Basic Information
            embed.add_field(
                name="🆔 ID",
                value=f"`{target.id}`",
                inline=True
            )
            
            # Member Information
            if member:
                if member.nick:
                    embed.add_field(
                        name="📝 ชื่อเล่น",
                        value=member.nick,
                        inline=True
                    )
                
                # Join date
                if member.joined_at:
                    joined_at = member.joined_at.strftime("%d/%m/%Y %H:%M:%S")
                    embed.add_field(
                        name="📅 เข้าร่วมเมื่อ",
                        value=f"`{joined_at}`\n({humanize.naturaltime(member.joined_at)})",
                        inline=True
                    )
                
                # Roles
                roles = [role.mention for role in member.roles[1:]]  # Exclude @everyone
                if roles:
                    roles_text = " ".join(roles) if len(roles) < 10 else f"{len(roles)} ยศ"
                    embed.add_field(
                        name=f"🎭 ยศ ({len(roles)})",
                        value=roles_text,
                        inline=False
                    )
            
            # Account Creation
            created_at = target.created_at.strftime("%d/%m/%Y %H:%M:%S")
            embed.add_field(
                name="📅 สร้างบัญชีเมื่อ",
                value=f"`{created_at}`\n({humanize.naturaltime(target.created_at)})",
                inline=True
            )
            
            # Add footer with user ID
            embed.set_footer(text=f"User ID: {target.id}")
            
            await interaction.response.send_message(embed=embed)

            # Update cooldown after successful execution
            self.cooldowns[interaction.guild.id][interaction.user.id] = current_time
        except Exception as e:
            await self.cog_app_command_error(interaction, e)

    @app_commands.command(name="ข้อมูลบอท", description="แสดงข้อมูลพื้นฐานของบอท")
    async def show_bot_info(self, interaction: discord.Interaction):
        try:
            # Check if user has manage_messages permission instead of requiring admin
            if not interaction.user.guild_permissions.manage_messages:
                return await interaction.response.send_message("❌ คุณต้องมีสิทธิ์จัดการข้อความเพื่อใช้คำสั่งนี้", ephemeral=True)

            # Get bot's latency
            latency = round(self.bot.latency * 1000)
            
            # Get uptime
            current_time = datetime.now(timezone.utc)
            uptime = current_time - self.bot.start_time
            days = uptime.days
            hours = uptime.seconds // 3600
            minutes = (uptime.seconds % 3600) // 60
            seconds = uptime.seconds % 60
            
            # Create status embed
            embed = discord.Embed(
                title="🤖 ข้อมูลบอท",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            # Add fields
            embed.add_field(
                name="⏱️ เวลาทำงาน",
                value=f"{days} วัน {hours} ชั่วโมง {minutes} นาที {seconds} วินาที",
                inline=False
            )
            embed.add_field(
                name="📶 ปิง",
                value=f"{latency}ms",
                inline=True
            )
            embed.add_field(
                name="👥 จำนวนเซิร์ฟเวอร์",
                value=str(len(self.bot.guilds)),
                inline=True
            )
            
            # Add footer
            embed.set_footer(text=f"Requested by {interaction.user.name}")
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in show_bot_info command: {e}")
            await interaction.response.send_message("❌ เกิดข้อผิดพลาดในการแสดงข้อมูลบอท", ephemeral=True)

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

    @app_commands.command(name="ช่วย", description="แสดงรายการคำสั่งทั้งหมด")
    async def help(self, interaction: discord.Interaction):
        """แสดงรายการคำสั่งทั้งหมด"""
        try:
            embed = discord.Embed(
                title="📚 รายการคำสั่งทั้งหมด",
                description="รายการคำสั่งที่สามารถใช้งานได้",
                color=discord.Color.blue()
            )
            
            # Utility Commands
            utility_commands = [
                "`/ความหน่วง` - ตรวจสอบความหน่วงของบอท",
                "`/ข้อมูลเซิร์ฟเวอร์` - แสดงข้อมูลเกี่ยวกับเซิร์ฟเวอร์",
                "`/ข้อมูลผู้ใช้` - แสดงข้อมูลเกี่ยวกับผู้ใช้",
                "`/ข้อมูลบอท` - แสดงข้อมูลเกี่ยวกับบอท",
                "`/เชิญบอท` - สร้างลิงก์เชิญบอท",
                "`/ช่อง` - แสดงข้อมูลเกี่ยวกับช่องทั้งหมดในเซิร์ฟเวอร์"
            ]
            
            embed.add_field(
                name="🔧 คำสั่งพื้นฐาน",
                value="\n".join(utility_commands),
                inline=False
            )
            
            # Add footer with bot name
            embed.set_footer(text=f"พิมพ์ / เพื่อดูรายการคำสั่งทั้งหมด")
            
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await self.cog_app_command_error(interaction, e)

    @app_commands.command(name="สถิติ", description="แสดงสถิติการใช้งานของบอทแบบเรียลไทม์")
    async def stats(self, interaction: discord.Interaction):
        """แสดงสถิติการใช้งานของบอทแบบเรียลไทม์"""
        try:
            # Check cooldown
            current_time = time.time()
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
                        description="การติดตามระบบสิ้นสุดลงตามเวลาที่กำหนด (1 นาที)",
                        color=discord.Color.blue()
                    )
                    await message.edit(embed=embed)
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
            synced_commands = [f"/{cmd.name} - {cmd.description}" for cmd in self.bot.tree.get_commands()]
            embed = discord.Embed(
                title="🔗 เชิญบอท",
                description=f"[คลิกที่นี่]({invite_url}) เพื่อเชิญบอทเข้าเซิร์ฟเวอร์ของคุณ\n\n**คำสั่งที่ซิงค์แล้ว:**\n" + "\n".join(synced_commands),
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

async def setup(bot):
    """Add the cog to the bot"""
    await bot.add_cog(Utility(bot))