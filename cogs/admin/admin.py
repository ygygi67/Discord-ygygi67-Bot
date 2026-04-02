import discord
from discord.ext import commands
from discord import app_commands
import logging
import os
from datetime import datetime, timezone, timedelta
import traceback
import asyncio
import psutil
import json
from typing import Optional

logger = logging.getLogger('discord_bot')

class GuildPaginator(discord.ui.View):
    def __init__(self, guilds, user):
        super().__init__(timeout=60)
        self.guilds = sorted(guilds, key=lambda g: g.name)
        self.user = user
        self.page = 0
        self.per_page = 5

    def create_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page
        current_guilds = self.guilds[start:end]
        
        embed = discord.Embed(
            title="🌐 รายชื่อเซิร์ฟเวอร์ที่บอทอยู่",
            color=discord.Color.blue(),
            description=f"หน้า {self.page + 1} จาก {((len(self.guilds) - 1) // self.per_page) + 1}",
            timestamp=datetime.now(timezone.utc)
        )
        
        for guild in current_guilds:
            owner = guild.owner.mention if guild.owner else "ไม่ทราบ"
            embed.add_field(
                name=guild.name,
                value=f"ID: `{guild.id}`\nสมาชิก: {guild.member_count} คน\nเจ้าของ: {owner}",
                inline=False
            )
        return embed

    @discord.ui.button(label="ก่อนหน้า", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("❌ คุณไม่มีสิทธิ์กดปุ่มนี้", ephemeral=True)
            
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="ถัดไป", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("❌ คุณไม่มีสิทธิ์กดปุ่มนี้", ephemeral=True)
            
        if (self.page + 1) * self.per_page < len(self.guilds):
            self.page += 1
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

class BulkDeleteControlView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=1800)
        self.owner_id = owner_id
        self.paused = False
        self.stopped = False

    async def _auth(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ ปุ่มนี้สำหรับคนที่เริ่มคำสั่งเท่านั้น", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⏸️ หยุดชั่วคราว", style=discord.ButtonStyle.secondary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._auth(interaction):
            return
        self.paused = not self.paused
        button.label = "▶️ ทำงานต่อ" if self.paused else "⏸️ หยุดชั่วคราว"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="🛑 หยุดการทำงาน", style=discord.ButtonStyle.danger)
    async def stop_action(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._auth(interaction):
            return
        self.stopped = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        super().stop()

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.allowed_user_id = "1034845842709958786"
        self.allowed_guild_id = 1034845842709958786
        self.admin_users = set()
        self.status_message = None
        self.status_channel = None
        self.status_task = None
        self.stress_task = None
        self.stress_active = False
        self.stress_level = 0
        self.stress_start_time = None
        self.diagnostic_results = []
        self.admin_config_path = "data/admin_config.json"
        self.load_admin_config()
        logger.info("Admin cog initialized")

    def load_admin_config(self):
        """Load admin users and status channel from config file"""
        try:
            if os.path.exists(self.admin_config_path):
                with open(self.admin_config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.admin_users = set(config.get("admin_users", []))
                    status_id = config.get("status_channel")
                    if status_id:
                        self.status_channel = self.bot.get_channel(status_id)
            elif os.path.exists("channels.json"): # Backward compatibility
                with open("channels.json", "r") as f:
                    config = json.load(f)
                    status_id = config.get("status_channel")
                    if status_id:
                        self.status_channel = self.bot.get_channel(status_id)
        except Exception as e:
            logger.error(f"Error loading admin config: {e}")

    def save_admin_config(self):
        """Save admin users and status channel to config file"""
        try:
            if not os.path.exists("data"):
                os.makedirs("data")
            config = {
                "admin_users": list(self.admin_users),
                "status_channel": self.status_channel.id if self.status_channel else None
            }
            with open(self.admin_config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
            logger.info("Saved admin configuration")
        except Exception as e:
            logger.error(f"Error saving admin config: {e}")

    async def cog_load(self):
        """Initialize status update task when cog is loaded"""
        if self.status_channel:
            self.status_task = self.bot.loop.create_task(self.update_status())
            logger.info("Started status update task")

    async def cog_unload(self):
        """Clean up tasks when cog is unloaded"""
        if self.status_task:
            self.status_task.cancel()
            try:
                await self.status_task
            except asyncio.CancelledError:
                pass
            logger.info("Stopped status update task")
            
        if self.stress_task:
            self.stress_active = False
            self.stress_task.cancel()
            try:
                await self.stress_task
            except asyncio.CancelledError:
                pass
            logger.info("Stopped stress test task")

    async def update_status(self):
        """Periodically update the status message"""
        await self.bot.wait_until_ready()
        
        while not self.bot.is_closed():
            try:
                if self.status_channel:
                    # Get server statistics
                    guild = self.bot.get_guild(self.allowed_guild_id)
                    if not guild:
                        await asyncio.sleep(60)
                        continue

                    # Create status embed
                    embed = discord.Embed(
                        title="สถานะบอท",
                        description="บอทพร้อมทำงาน!",
                        color=discord.Color.green(),
                        timestamp=datetime.now(timezone.utc)
                    )

                    # Server information
                    total_members = guild.member_count
                    online_members = sum(1 for m in guild.members if m.status != discord.Status.offline)
                    idle_members = sum(1 for m in guild.members if m.status == discord.Status.idle)
                    dnd_members = sum(1 for m in guild.members if m.status == discord.Status.dnd)
                    offline_members = sum(1 for m in guild.members if m.status == discord.Status.offline)

                    embed.add_field(
                        name="ข้อมูลเซิร์ฟเวอร์",
                        value=f"สมาชิกทั้งหมด: {total_members} คน\n"
                              f"ออนไลน์: {online_members} คน\n"
                              f"ไม่อยู่: {idle_members} คน\n"
                              f"ยุ่ง: {dnd_members} คน\n"
                              f"ออฟไลน์: {offline_members} คน",
                        inline=False
                    )

                    # Voice channels
                    active_voice = []
                    for vc in guild.voice_channels:
                        if vc.members:
                            active_voice.append(f"{vc.name}: {len(vc.members)} คน")

                    if active_voice:
                        embed.add_field(
                            name="ช่องเสียงที่ใช้งานอยู่",
                            value="\n".join(active_voice),
                            inline=False
                        )

                    # System information
                    cpu_percent = psutil.cpu_percent(interval=0.1)
                    memory = psutil.virtual_memory()
                    memory_percent = memory.percent
                    memory_used = memory.used / (1024 * 1024 * 1024)
                    memory_total = memory.total / (1024 * 1024 * 1024)

                    embed.add_field(
                        name="💻 ระบบ",
                        value=f"CPU: **{cpu_percent}%**\nRAM: **{memory.percent}%**\n({memory_used:.2f} GB / {memory_total:.2f} GB)",
                        inline=True
                    )

                    # Add bot statistics
                    embed.add_field(
                        name="🤖 บอท",
                        value=f"ความหน่วง: **{round(self.bot.latency * 1000)}ms**\nเวอร์ชัน: **{discord.__version__}**",
                        inline=True
                    )

                    # Add music statistics if available
                    if hasattr(self.bot, 'get_cog'):
                        music_cog = self.bot.get_cog('Music')
                        if music_cog:
                            try:
                                # Get current playing status
                                current_playing = "ไม่มี"  # Default value
                                for guild in self.bot.guilds:
                                    if guild.voice_client and guild.voice_client.is_playing():
                                        current_playing = guild.voice_client.track.title
                                        break
                                
                                embed.add_field(
                                    name="🎵 เพลง",
                                    value=f"กำลังเล่น: **{current_playing}**",
                                    inline=False
                                )
                            except Exception as e:
                                logger.error(f"Error getting music stats: {e}")

                    # Update the message
                    try:
                        if self.status_message:
                            await self.status_message.edit(embed=embed)
                        else:
                            self.status_message = await self.status_channel.send(embed=embed)
                    except discord.NotFound:
                        self.status_message = await self.status_channel.send(embed=embed)
                    except Exception as e:
                        logger.error(f"Error updating status message: {e}")

            except Exception as e:
                logger.error(f"Error in status update task: {e}")

            # Sleep for 60 seconds, but break it into smaller intervals to prevent blocking
            for _ in range(12):
                if self.bot.is_closed():
                    break
                await asyncio.sleep(5)

    def is_admin(self, user_id):
        """Check if user is an admin"""
        return str(user_id) == self.allowed_user_id or str(user_id) in self.admin_users

    def is_server_admin_or_bot_admin(self, interaction: discord.Interaction) -> bool:
        """Check if user is a bot admin or server admin"""
        if self.is_admin(interaction.user.id):
            return True
        if interaction.guild:
            admin_role = discord.utils.get(interaction.guild.roles, name="Server Admin")
            if admin_role and admin_role in getattr(interaction.user, 'roles', []):
                return True
            if getattr(interaction.user, 'guild_permissions', None) and interaction.user.guild_permissions.administrator:
                return True
        return False

    @app_commands.command(name="ตรวจสอบสิทธิ์", description="ตรวจสอบสิทธิ์แอดมินของคุณ")
    async def check_permissions(self, interaction: discord.Interaction):
        """ตรวจสอบสิทธิ์ของผู้ใช้"""
        embed = discord.Embed(
            title="🔍 ตรวจสอบสิทธิ์",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="ผู้ใช้",
            value=f"{interaction.user.mention} ({interaction.user.name})\nID: {interaction.user.id}",
            inline=False
        )
        
        user_id = str(interaction.user.id)
        if user_id == self.allowed_user_id:
            status = "✅ แอดมินหลัก"
        elif user_id in self.admin_users:
            status = "✅ แอดมิน"
        else:
            status = "❌ ไม่มีสิทธิ์แอดมิน"
        
        embed.add_field(
            name="สถานะแอดมิน",
            value=status,
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="หยุดบอท", description="หยุดการทำงานของบอท")
    async def shutdown(self, interaction: discord.Interaction):
        """หยุดการทำงานของบอท"""
        if not self.is_admin(interaction.user.id):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)
            return
            
        logger.info(f"Bot shutdown initiated by {interaction.user.name}")
        await interaction.response.send_message("🛑 กำลังปิดบอท...")
        await self.bot.close()

    @app_commands.command(name="ล้างข้อความ", description="ลบข้อความแบบละเอียด (ทุกช่อง/ตาม ID/เว็บฮุก/แอป)")
    @app_commands.describe(
        จำนวน="จำนวนข้อความล่าสุดต่อช่องที่ต้องการสแกน (สูงสุด 1000)",
        ผู้ใช้="ลบเฉพาะสมาชิกคนนี้ (กดเลือกจากรายชื่อ)",
        ผู้ใช้ไอดี="ลบเฉพาะผู้ใช้ ID นี้ (เผื่อไม่ได้อยู่ในเซิร์ฟแล้ว)",
        ยศ="ลบเฉพาะสมาชิกที่มียศนี้",
        กี่ชั่วโมงที่ผ่านมา="ลบเฉพาะข้อความใหม่ภายในกี่ชั่วโมง",
        กี่วันที่ผ่านมา="ลบเฉพาะข้อความใหม่ภายในกี่วัน",
        เฉพาะบอท="ลบเฉพาะข้อความจากบอท",
        เฉพาะเว็บฮุก="ลบเฉพาะข้อความจาก webhook",
        เฉพาะแอปภายนอก="ลบเฉพาะข้อความจาก interaction/app/webhook",
        webhook_id="ลบเฉพาะ Webhook ID นี้",
        application_id="ลบเฉพาะ Application ID นี้",
        ทุกช่อง="สแกนและลบจากทุกช่องข้อความในเซิร์ฟเวอร์"
    )
    async def clear(
        self,
        interaction: discord.Interaction,
        จำนวน: int = 30,
        ผู้ใช้: Optional[discord.Member] = None,
        ผู้ใช้ไอดี: Optional[str] = None,
        ยศ: Optional[discord.Role] = None,
        กี่ชั่วโมงที่ผ่านมา: Optional[float] = None,
        กี่วันที่ผ่านมา: Optional[float] = None,
        เฉพาะบอท: bool = False,
        เฉพาะเว็บฮุก: bool = False,
        เฉพาะแอปภายนอก: bool = False,
        webhook_id: Optional[str] = None,
        application_id: Optional[str] = None,
        ทุกช่อง: bool = False
    ):
        """ล้างข้อความพร้อมฟิลเตอร์แบบละเอียด รองรับทุกช่องและปุ่มหยุดชั่วคราว/หยุด"""
        if not self.is_server_admin_or_bot_admin(interaction):
            return await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)

        if not interaction.guild:
            return await interaction.response.send_message("❌ ใช้คำสั่งนี้ได้เฉพาะในเซิร์ฟเวอร์", ephemeral=True)

        me = interaction.guild.me or interaction.guild.get_member(self.bot.user.id)
        if not me or not me.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ บอทไม่มีสิทธิ์ `Manage Messages`", ephemeral=True)

        if จำนวน <= 0 or จำนวน > 1000:
            return await interaction.response.send_message("❌ จำนวนข้อความต้องอยู่ระหว่าง 1 - 1000", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        try:
            user_id_filter = None
            if ผู้ใช้ and ผู้ใช้ไอดี:
                return await interaction.followup.send("❌ เลือกได้อย่างใดอย่างหนึ่ง: `ผู้ใช้` หรือ `ผู้ใช้ไอดี`", ephemeral=True)
            if ผู้ใช้:
                user_id_filter = ผู้ใช้.id
            elif ผู้ใช้ไอดี:
                if not ผู้ใช้ไอดี.isdigit():
                    return await interaction.followup.send("❌ `ผู้ใช้ไอดี` ต้องเป็นตัวเลขเท่านั้น", ephemeral=True)
                user_id_filter = int(ผู้ใช้ไอดี)

            webhook_id_filter = None
            if webhook_id:
                if not webhook_id.isdigit():
                    return await interaction.followup.send("❌ `webhook_id` ต้องเป็นตัวเลขเท่านั้น", ephemeral=True)
                webhook_id_filter = int(webhook_id)

            application_id_filter = None
            if application_id:
                if not application_id.isdigit():
                    return await interaction.followup.send("❌ `application_id` ต้องเป็นตัวเลขเท่านั้น", ephemeral=True)
                application_id_filter = int(application_id)

            after_limit = None
            if กี่ชั่วโมงที่ผ่านมา or กี่วันที่ผ่านมา:
                delta_hours = กี่ชั่วโมงที่ผ่านมา if กี่ชั่วโมงที่ผ่านมา else 0
                delta_days = กี่วันที่ผ่านมา if กี่วันที่ผ่านมา else 0
                after_limit = datetime.now(timezone.utc) - timedelta(days=delta_days, hours=delta_hours)

            def check_filter(m: discord.Message) -> bool:
                if user_id_filter and (not m.author or m.author.id != user_id_filter):
                    return False
                if ยศ:
                    if not isinstance(m.author, discord.Member):
                        return False
                    if ยศ not in m.author.roles:
                        return False
                if เฉพาะบอท and not (m.author and m.author.bot):
                    return False
                if เฉพาะเว็บฮุก and m.webhook_id is None:
                    return False
                if เฉพาะแอปภายนอก and (m.webhook_id is None and m.application_id is None):
                    return False
                if webhook_id_filter and m.webhook_id != webhook_id_filter:
                    return False
                if application_id_filter and m.application_id != application_id_filter:
                    return False
                return True

            filter_info = []
            if user_id_filter: filter_info.append(f"👤 UID `{user_id_filter}`")
            if ยศ: filter_info.append(f"🛡️ {ยศ.name}")
            if เฉพาะบอท: filter_info.append("🤖 เฉพาะบอท")
            if เฉพาะเว็บฮุก: filter_info.append("🪝 เฉพาะเว็บฮุก")
            if เฉพาะแอปภายนอก: filter_info.append("🧩 เฉพาะแอปภายนอก")
            if webhook_id_filter: filter_info.append(f"🪝 Webhook `{webhook_id_filter}`")
            if application_id_filter: filter_info.append(f"🧩 App `{application_id_filter}`")
            if after_limit: filter_info.append(f"⏱️ ตั้งแต่ {after_limit.strftime('%d/%m %H:%M')}")
            if ทุกช่อง: filter_info.append("🌐 ทุกช่อง")

            info_str = f" ({' | '.join(filter_info)})" if filter_info else ""
            view = BulkDeleteControlView(interaction.user.id)
            status_msg = await interaction.followup.send(
                f"🗑️ กำลังสแกนและลบข้อความ {จำนวน} รายการล่าสุดต่อช่อง{info_str}...",
                view=view
            )

            channels = []
            if ทุกช่อง:
                for ch in interaction.guild.text_channels:
                    perms = ch.permissions_for(me)
                    if perms.read_message_history and perms.manage_messages:
                        channels.append(ch)
            else:
                if not isinstance(interaction.channel, discord.TextChannel):
                    return await status_msg.edit(content="❌ ห้องนี้ไม่ใช่ห้องข้อความ", view=None)
                channels = [interaction.channel]

            total_scanned = 0
            total_matched = 0
            deleted_count = 0
            failed_count = 0

            for channel_idx, channel in enumerate(channels, start=1):
                if view.stopped:
                    break
                while view.paused and not view.stopped:
                    await status_msg.edit(
                        content=f"⏸️ หยุดชั่วคราวอยู่... ({channel_idx}/{len(channels)}) | ลบแล้ว {deleted_count} | ล้มเหลว {failed_count}",
                        view=view
                    )
                    await asyncio.sleep(1.0)
                if view.stopped:
                    break

                try:
                    messages = [m async for m in channel.history(limit=จำนวน, after=after_limit)]
                except Exception:
                    failed_count += 1
                    continue

                total_scanned += len(messages)
                targets = [m for m in messages if check_filter(m) and m.id != status_msg.id]
                total_matched += len(targets)

                bulk_cutoff = datetime.now(timezone.utc) - timedelta(days=14)
                bulk_targets = [m for m in targets if m.created_at > bulk_cutoff]
                single_targets = [m for m in targets if m.created_at <= bulk_cutoff]

                # ลบแบบ bulk ก่อน (ลด 429 ได้เยอะมาก)
                for i in range(0, len(bulk_targets), 100):
                    if view.stopped:
                        break
                    while view.paused and not view.stopped:
                        await asyncio.sleep(0.8)
                    if view.stopped:
                        break

                    chunk = bulk_targets[i:i + 100]
                    try:
                        if len(chunk) == 1:
                            await chunk[0].delete()
                            deleted_count += 1
                        elif len(chunk) > 1:
                            await channel.delete_messages(chunk)
                            deleted_count += len(chunk)
                    except (discord.Forbidden, discord.HTTPException):
                        # fallback ลบทีละข้อความ
                        for msg in chunk:
                            try:
                                await msg.delete()
                                deleted_count += 1
                                await asyncio.sleep(0.45)
                            except (discord.Forbidden, discord.HTTPException):
                                failed_count += 1

                    await status_msg.edit(
                        content=(
                            f"🧹 กำลังทำงาน... ช่อง {channel_idx}/{len(channels)} (`#{channel.name}`)\n"
                            f"📚 สแกน: {total_scanned} | 🎯 ตรงเงื่อนไข: {total_matched}\n"
                            f"✅ ลบแล้ว: {deleted_count} | ⚠️ ล้มเหลว: {failed_count}\n"
                            f"⚡ โหมดลบ: Bulk ({len(bulk_targets)} ข้อความในช่องนี้)"
                        ),
                        view=view
                    )
                    await asyncio.sleep(1.2)

                # ลบข้อความเก่า (เกิน 14 วัน) ทีละข้อความ พร้อมหน่วงเพื่อลด 429
                for msg_idx, msg in enumerate(single_targets, start=1):
                    if view.stopped:
                        break
                    while view.paused and not view.stopped:
                        await asyncio.sleep(0.8)
                    if view.stopped:
                        break

                    try:
                        await msg.delete()
                        deleted_count += 1
                    except (discord.Forbidden, discord.HTTPException):
                        failed_count += 1

                    await asyncio.sleep(0.55)
                    if (msg_idx % 15 == 0) or (deleted_count + failed_count) % 30 == 0:
                        await status_msg.edit(
                            content=(
                                f"🧹 กำลังทำงาน... ช่อง {channel_idx}/{len(channels)} (`#{channel.name}`)\n"
                                f"📚 สแกน: {total_scanned} | 🎯 ตรงเงื่อนไข: {total_matched}\n"
                                f"✅ ลบแล้ว: {deleted_count} | ⚠️ ล้มเหลว: {failed_count}\n"
                                f"🐢 โหมดลบ: ทีละข้อความ (เก่าเกิน 14 วัน)"
                            ),
                            view=view
                        )

            stopped_text = " (ผู้ใช้กดหยุดการทำงาน)" if view.stopped else ""
            summary = (
                f"✅ ล้างข้อความเสร็จสิ้น{stopped_text}\n"
                f"📚 สแกนทั้งหมด: **{total_scanned}** ข้อความ\n"
                f"🎯 ตรงเงื่อนไข: **{total_matched}** ข้อความ\n"
                f"🗑️ ลบสำเร็จ: **{deleted_count}**\n"
                f"⚠️ ลบไม่สำเร็จ: **{failed_count}**\n"
                f"👮 ผู้ใช้คำสั่ง: {interaction.user.mention} (`{interaction.user.id}`)"
            )
            for item in view.children:
                item.disabled = True
            await status_msg.edit(content=summary, view=view)

            logger.info(
                f"[CLEAR] guild={interaction.guild.id} by={interaction.user.id} all_channels={ทุกช่อง} "
                f"channels={len(channels)} scanned={total_scanned} matched={total_matched} "
                f"deleted={deleted_count} failed={failed_count}"
            )
        except Exception as e:
            logger.error(f"Error in clear_messages: {e}", exc_info=True)
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาดระหว่างลบข้อความ: {str(e)[:250]}", ephemeral=True)

    @app_commands.command(name="ตรวจสอบข้อความ", description="ดูแหล่งที่มาของข้อความ (บอท/เว็บฮุก/แอป)")
    @app_commands.describe(message_id="ไอดีข้อความที่ต้องการตรวจสอบ", ช่อง="ช่องที่ข้อความนั้นอยู่ (ถ้าไม่ใส่จะใช้ห้องปัจจุบัน)")
    async def inspect_message(self, interaction: discord.Interaction, message_id: str, ช่อง: Optional[discord.TextChannel] = None):
        if not self.is_server_admin_or_bot_admin(interaction):
            return await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟเวอร์", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        target_channel = ช่อง or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            return await interaction.followup.send("❌ ต้องเป็นห้องข้อความเท่านั้น", ephemeral=True)

        try:
            msg = await target_channel.fetch_message(int(message_id))
        except Exception:
            return await interaction.followup.send("❌ ไม่พบข้อความนี้ หรือบอทไม่มีสิทธิ์อ่านประวัติข้อความ", ephemeral=True)

        interaction_user_text = "ไม่พบข้อมูล"
        if getattr(msg, "interaction", None) and getattr(msg.interaction, "user", None):
            interaction_user_text = f"{msg.interaction.user.mention} (`{msg.interaction.user.id}`)"
        elif getattr(msg, "interaction_metadata", None):
            user_id = getattr(msg.interaction_metadata, "user_id", None)
            if user_id:
                interaction_user_text = f"<@{user_id}> (`{user_id}`)"

        embed = discord.Embed(title="🔎 ตรวจสอบแหล่งที่มาข้อความ", color=discord.Color.blurple())
        embed.add_field(name="Message ID", value=f"`{msg.id}`", inline=False)
        embed.add_field(name="Author", value=f"{msg.author} (`{msg.author.id}`)", inline=False)
        embed.add_field(name="Author is bot", value="ใช่" if msg.author.bot else "ไม่ใช่", inline=True)
        embed.add_field(name="Webhook ID", value=f"`{msg.webhook_id}`" if msg.webhook_id else "ไม่มี", inline=True)
        embed.add_field(name="Application ID", value=f"`{msg.application_id}`" if msg.application_id else "ไม่มี", inline=True)
        embed.add_field(name="คนที่กดคำสั่งแอป (ถ้าดึงได้)", value=interaction_user_text, inline=False)
        embed.add_field(name="Channel", value=f"{target_channel.mention} (`{target_channel.id}`)", inline=False)
        embed.set_footer(text="ถ้าเป็นข้อความจากบอทภายนอกและไม่มี interaction metadata อาจระบุตัวผู้ใช้จริงไม่ได้")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="ค้นหาข้อความ", description="ค้นหาว่าใครเคยพิมพ์อะไรไว้ (ใส่ ID หรือเลือกผู้ใช้ได้)")
    @app_commands.describe(
        ผู้ใช้="เลือกจากรายชื่อสมาชิก",
        ผู้ใช้ไอดี="ค้นหาจาก User ID",
        คำค้น="คำที่ต้องการค้นหาในข้อความ",
        ทุกช่อง="ค้นหาทุกห้องข้อความในเซิร์ฟเวอร์",
        จำนวนต่อช่อง="จำนวนข้อความที่สแกนต่อห้อง (สูงสุด 1000)",
        จำนวนผลลัพธ์="จำนวนผลลัพธ์ที่แสดงสูงสุด"
    )
    async def search_messages(
        self,
        interaction: discord.Interaction,
        ผู้ใช้: Optional[discord.Member] = None,
        ผู้ใช้ไอดี: Optional[str] = None,
        คำค้น: Optional[str] = None,
        ทุกช่อง: bool = True,
        จำนวนต่อช่อง: int = 200,
        จำนวนผลลัพธ์: int = 20
    ):
        if not self.is_server_admin_or_bot_admin(interaction):
            return await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟเวอร์", ephemeral=True)
        if จำนวนต่อช่อง <= 0 or จำนวนต่อช่อง > 1000:
            return await interaction.response.send_message("❌ `จำนวนต่อช่อง` ต้องอยู่ระหว่าง 1 - 1000", ephemeral=True)
        if จำนวนผลลัพธ์ <= 0 or จำนวนผลลัพธ์ > 50:
            return await interaction.response.send_message("❌ `จำนวนผลลัพธ์` ต้องอยู่ระหว่าง 1 - 50", ephemeral=True)
        if not ผู้ใช้ and not ผู้ใช้ไอดี and not คำค้น:
            return await interaction.response.send_message("❌ กรุณาใส่อย่างน้อย 1 เงื่อนไข: ผู้ใช้/ผู้ใช้ไอดี/คำค้น", ephemeral=True)
        if ผู้ใช้ and ผู้ใช้ไอดี:
            return await interaction.response.send_message("❌ เลือกได้อย่างใดอย่างหนึ่ง: `ผู้ใช้` หรือ `ผู้ใช้ไอดี`", ephemeral=True)

        user_id_filter = None
        if ผู้ใช้:
            user_id_filter = ผู้ใช้.id
        elif ผู้ใช้ไอดี:
            if not ผู้ใช้ไอดี.isdigit():
                return await interaction.response.send_message("❌ `ผู้ใช้ไอดี` ต้องเป็นตัวเลขเท่านั้น", ephemeral=True)
            user_id_filter = int(ผู้ใช้ไอดี)

        await interaction.response.defer(ephemeral=True)

        me = interaction.guild.me or interaction.guild.get_member(self.bot.user.id)
        channels = []
        if ทุกช่อง:
            for ch in interaction.guild.text_channels:
                perms = ch.permissions_for(me)
                if perms.read_message_history and perms.view_channel:
                    channels.append(ch)
        else:
            if not isinstance(interaction.channel, discord.TextChannel):
                return await interaction.followup.send("❌ ห้องนี้ไม่ใช่ห้องข้อความ", ephemeral=True)
            channels = [interaction.channel]

        status_msg = await interaction.followup.send(f"🔍 กำลังค้นหาใน {len(channels)} ห้อง...")

        matches = []
        scanned = 0

        for idx, channel in enumerate(channels, start=1):
            try:
                async for msg in channel.history(limit=จำนวนต่อช่อง):
                    scanned += 1
                    if user_id_filter and msg.author.id != user_id_filter:
                        continue
                    if คำค้น and คำค้น.lower() not in (msg.content or "").lower():
                        continue
                    matches.append(msg)
                    if len(matches) >= จำนวนผลลัพธ์:
                        break
                if len(matches) >= จำนวนผลลัพธ์:
                    break
                if idx % 5 == 0:
                    await status_msg.edit(content=f"🔍 กำลังค้นหา... ({idx}/{len(channels)}) | สแกน {scanned} | พบ {len(matches)}")
            except Exception:
                continue

        if not matches:
            return await status_msg.edit(content=f"ℹ️ ไม่พบข้อความตามเงื่อนไข (สแกน {scanned} ข้อความ)")

        lines = []
        for i, msg in enumerate(matches[:จำนวนผลลัพธ์], start=1):
            text = (msg.content or "").strip().replace("\n", " ")
            if len(text) > 70:
                text = text[:67] + "..."
            if not text:
                text = "[ไม่มีข้อความตัวอักษร]"
            lines.append(
                f"{i}. <@{msg.author.id}> (`{msg.author.id}`) | <#{msg.channel.id}> | "
                f"[Jump]({msg.jump_url})\n↳ {text}"
            )

        desc = "\n\n".join(lines[:จำนวนผลลัพธ์])
        if len(desc) > 3900:
            desc = desc[:3890] + "\n\n... (ตัดข้อความเพื่อไม่ให้เกินลิมิต Discord)"

        embed = discord.Embed(
            title="📜 ผลการค้นหาข้อความย้อนหลัง",
            description=desc,
            color=discord.Color.green()
        )
        embed.add_field(name="สรุป", value=f"สแกน: `{scanned}` | พบ: `{len(matches)}` | แสดง: `{min(len(matches), จำนวนผลลัพธ์)}`", inline=False)
        embed.set_footer(text="คุณสามารถคัดลอก User ID/Message ID ไปใช้กับคำสั่งอื่นต่อได้")

        await status_msg.edit(content="✅ ค้นหาเสร็จแล้ว", embed=embed)

    @app_commands.command(name="สถานะ", description="แสดงสถานะของบอทและเซิร์ฟเวอร์")
    async def status(self, interaction: discord.Interaction):
        """แสดงสถานะของบอทและเซิร์ฟเวอร์"""
        try:
            # Check if user has manage_messages permission
            if not interaction.user.guild_permissions.manage_messages:
                await interaction.response.send_message(
                    "❌ คุณต้องมีสิทธิ์จัดการข้อความเพื่อใช้คำสั่งนี้\n"
                    "โปรดติดต่อแอดมินเพื่อขอสิทธิ์เพิ่มเติม",
                    ephemeral=True
                )
                return

            # Get server statistics
            total_members = sum(guild.member_count for guild in self.bot.guilds)
            online_members = sum(len([m for m in guild.members if m.status != discord.Status.offline]) for guild in self.bot.guilds)
            total_channels = sum(len(guild.channels) for guild in self.bot.guilds)
            total_voice_channels = sum(len(guild.voice_channels) for guild in self.bot.guilds)
            total_text_channels = sum(len(guild.text_channels) for guild in self.bot.guilds)
            
            # Get system statistics
            cpu_percent = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            memory_used = memory.used / (1024 * 1024 * 1024)  # Convert to GB
            memory_total = memory.total / (1024 * 1024 * 1024)  # Convert to GB
            
            # Create embed
            embed = discord.Embed(
                title="📊 สถานะบอท",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            # Add server statistics
            embed.add_field(
                name="🌐 เซิร์ฟเวอร์",
                value=f"จำนวน: **{len(self.bot.guilds)}**\nสมาชิกทั้งหมด: **{total_members}**\nออนไลน์: **{online_members}**",
                inline=True
            )
            
            embed.add_field(
                name="📝 แชแนล",
                value=f"ทั้งหมด: **{total_channels}**\nข้อความ: **{total_text_channels}**\nเสียง: **{total_voice_channels}**",
                inline=True
            )
            
            embed.add_field(
                name="💻 ระบบ",
                value=f"CPU: **{cpu_percent}%**\nRAM: **{memory.percent}%**\n({memory_used:.2f} GB / {memory_total:.2f} GB)",
                inline=True
            )
            
            # Add bot statistics
            embed.add_field(
                name="🤖 บอท",
                value=f"ความหน่วง: **{round(self.bot.latency * 1000)}ms**\nเวอร์ชัน: **{discord.__version__}**",
                inline=True
            )
            
            # Add music statistics if available
            try:
                music_cog = self.bot.get_cog("Music")
                if music_cog:
                    # Check if any guild has a voice client that's playing
                    playing_guilds = []
                    for guild in self.bot.guilds:
                        if guild.voice_client and guild.voice_client.is_playing():
                            playing_guilds.append(guild)
                    
                    if playing_guilds:
                        current_song = playing_guilds[0].voice_client.source.title if hasattr(playing_guilds[0].voice_client.source, 'title') else "ไม่ทราบชื่อเพลง"
                        embed.add_field(
                                name="🎵 เพลงที่กำลังเล่น",
                                value=f"**{current_song}**\nใน **{len(playing_guilds)}** เซิร์ฟเวอร์",
                            inline=False
                        )
                    else:
                        embed.add_field(
                            name="🎵 เพลงที่กำลังเล่น",
                            value="ไม่มีเพลงที่กำลังเล่นอยู่ในขณะนี้",
                            inline=False
                        )
            except Exception as e:
                logger.error(f"Error getting music stats: {e}")
            
            # Add footer
            embed.set_footer(text=f"Requested by {interaction.user.name}")
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in status command: {e}")
            await interaction.response.send_message(
                "❌ เกิดข้อผิดพลาดในการแสดงสถานะ\n"
                "โปรดลองใหม่อีกครั้งหรือติดต่อแอดมิน",
                ephemeral=True
            )

    @app_commands.command(name="เพิ่มแอดมิน", description="เพิ่มผู้ใช้เป็นแอดมินบอท")
    @app_commands.describe(user="ผู้ใช้ที่จะเพิ่มเป็นแอดมิน")
    async def add_admin(self, interaction: discord.Interaction, user: discord.Member):
        """เพิ่มผู้ใช้เป็นแอดมิน"""
        if str(interaction.user.id) != self.allowed_user_id:
            await interaction.response.send_message("❌ เฉพาะแอดมินหลักเท่านั้นที่สามารถเพิ่มแอดมินได้", ephemeral=True)
            return

        user_id = str(user.id)
        if user_id == self.allowed_user_id:
            await interaction.response.send_message("❌ ผู้ใช้นี้เป็นแอดมินหลักอยู่แล้ว", ephemeral=True)
            return

        if user_id in self.admin_users:
            await interaction.response.send_message("❌ ผู้ใช้นี้เป็นแอดมินอยู่แล้ว", ephemeral=True)
            return

        self.admin_users.add(user_id)
        self.save_admin_config()
        logger.info(f"Added {user.name} (ID: {user_id}) as admin by {interaction.user.name}")
        await interaction.response.send_message(f"✅ เพิ่ม {user.mention} เป็นแอดมินเรียบร้อยแล้ว")

    @app_commands.command(name="ลบแอดมิน", description="ลบผู้ใช้ออกจากการเป็นแอดมิน")
    @app_commands.describe(user="ผู้ใช้ที่จะลบออกจากการเป็นแอดมิน")
    async def remove_admin(self, interaction: discord.Interaction, user: discord.Member):
        """ลบผู้ใช้ออกจากการเป็นแอดมิน"""
        if str(interaction.user.id) != self.allowed_user_id:
            await interaction.response.send_message("❌ เฉพาะแอดมินหลักเท่านั้นที่สามารถลบแอดมินได้", ephemeral=True)
            return

        user_id = str(user.id)
        if user_id == self.allowed_user_id:
            await interaction.response.send_message("❌ ไม่สามารถลบแอดมินหลักได้", ephemeral=True)
            return

        if user_id not in self.admin_users:
            await interaction.response.send_message("❌ ผู้ใช้นี้ไม่ได้เป็นแอดมิน", ephemeral=True)
            return

        self.admin_users.remove(user_id)
        self.save_admin_config()
        logger.info(f"Removed {user.name} (ID: {user_id}) from admins by {interaction.user.name}")
        await interaction.response.send_message(f"✅ ลบ {user.mention} ออกจากการเป็นแอดมินแล้ว")

    @app_commands.command(name="รายชื่อแอดมิน", description="แสดงรายชื่อแอดมินทั้งหมด")
    async def list_admins(self, interaction: discord.Interaction):
        """แสดงรายชื่อแอดมินทั้งหมด"""
        embed = discord.Embed(
            title="👑 รายชื่อแอดมิน",
            color=discord.Color.gold()
        )

        main_admin = await self.bot.fetch_user(int(self.allowed_user_id))
        embed.add_field(
            name="แอดมินหลัก",
            value=f"{main_admin.mention} ({main_admin.name})",
            inline=False
        )

        if self.admin_users:
            admin_mentions = []
            for admin_id in self.admin_users:
                try:
                    admin = await self.bot.fetch_user(int(admin_id))
                    admin_mentions.append(f"{admin.mention} ({admin.name})")
                except:
                    admin_mentions.append(f"ID: {admin_id} (ไม่พบผู้ใช้)")
            
            embed.add_field(
                name="แอดมินเพิ่มเติม",
                value="\n".join(admin_mentions) if admin_mentions else "ไม่มีแอดมินเพิ่มเติม",
                inline=False
            )
        else:
            embed.add_field(
                name="แอดมินเพิ่มเติม",
                value="ไม่มีแอดมินเพิ่มเติม",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="สร้างยศเจ้าของ", description="สร้างยศเจ้าของบอทพร้อมให้สิทธิ์สูงสุด")
    async def create_owner_role(self, interaction: discord.Interaction):
        """สร้างยศเจ้าของบอทพร้อมให้สิทธิ์สูงสุด"""
        if str(interaction.user.id) != self.allowed_user_id:
            await interaction.response.send_message("❌ เฉพาะเจ้าของบอทเท่านั้นที่สามารถใช้คำสั่งนี้ได้", ephemeral=True)
            return

        try:
            # Defer the response since role creation might take time
            await interaction.response.defer(ephemeral=True)

            owner_role = discord.utils.get(interaction.guild.roles, name="👑 Bot Owner")
            if owner_role:
                if owner_role in interaction.user.roles:
                    await interaction.followup.send("❌ คุณมียศเจ้าของบอทอยู่แล้ว", ephemeral=True)
                else:
                    await interaction.user.add_roles(owner_role)
                    await interaction.followup.send("✅ ให้ยศเจ้าของบอทแก่คุณเรียบร้อยแล้ว")
                return

            owner_role = await interaction.guild.create_role(
                name="👑 Bot Owner",
                permissions=discord.Permissions.all(),
                color=discord.Color.gold(),
                hoist=True,
                mentionable=True,
                reason="Bot Owner Role Creation"
            )

            positions = {role: role.position for role in interaction.guild.roles}
            positions[owner_role] = interaction.guild.me.top_role.position - 1
            await interaction.guild.edit_role_positions(positions=positions)

            await interaction.user.add_roles(owner_role)
            
            logger.info(f"Created and assigned Owner role to {interaction.user.name} in {interaction.guild.name}")
            await interaction.followup.send("✅ สร้างและให้ยศเจ้าของบอทแก่คุณเรียบร้อยแล้ว", ephemeral=True)

        except discord.Forbidden:
            await interaction.followup.send("❌ บอทไม่มีสิทธิ์ในการจัดการบทบาท โปรดให้สิทธิ์ 'Administrator' แก่บอทก่อน", ephemeral=True)
        except Exception as e:
            logger.error(f"Error creating owner role: {str(e)}")
            await interaction.followup.send("❌ เกิดข้อผิดพลาดในการสร้างยศเจ้าของบอท", ephemeral=True)

    @app_commands.command(name="สร้างแอดมินเซิร์ฟเวอร์", description="สร้างยศแอดมินเซิร์ฟเวอร์")
    async def create_server_admin_role(self, interaction: discord.Interaction):
        """สร้างยศแอดมินเซิร์ฟเวอร์"""
        if str(interaction.user.id) != self.allowed_user_id:
            await interaction.response.send_message("❌ เฉพาะแอดมินหลักเท่านั้นที่สามารถสร้างยศแอดมินเซิร์ฟเวอร์ได้", ephemeral=True)
            return

        try:
            admin_role = discord.utils.get(interaction.guild.roles, name="Server Admin")
            if admin_role:
                await interaction.response.send_message("❌ ยศแอดมินเซิร์ฟเวอร์มีอยู่แล้ว", ephemeral=True)
                return

            admin_role = await interaction.guild.create_role(
                name="Server Admin",
                permissions=discord.Permissions.all(),
                color=discord.Color.red(),
                hoist=True,
                mentionable=True
            )
            
            logger.info(f"Created Server Admin role in {interaction.guild.name}")
            await interaction.response.send_message("✅ สร้างยศแอดมินเซิร์ฟเวอร์เรียบร้อยแล้ว")

        except discord.Forbidden:
            await interaction.response.send_message("❌ บอทไม่มีสิทธิ์ในการสร้างบทบาท โปรดให้สิทธิ์ 'Administrator' แก่บอทก่อน", ephemeral=True)
        except Exception as e:
            logger.error(f"Error creating server admin role: {str(e)}")
            await interaction.response.send_message("❌ เกิดข้อผิดพลาดในการสร้างยศแอดมินเซิร์ฟเวอร์", ephemeral=True)

    @app_commands.command(name="ให้แอดมินเซิร์ฟเวอร์", description="ให้ยศแอดมินเซิร์ฟเวอร์แก่ผู้ใช้")
    @app_commands.describe(user="ผู้ใช้ที่จะให้ยศแอดมินเซิร์ฟเวอร์")
    async def give_server_admin(self, interaction: discord.Interaction, user: discord.Member):
        """ให้ยศแอดมินเซิร์ฟเวอร์แก่ผู้ใช้"""
        if str(interaction.user.id) != self.allowed_user_id:
            await interaction.response.send_message("❌ เฉพาะแอดมินหลักเท่านั้นที่สามารถให้ยศแอดมินเซิร์ฟเวอร์ได้", ephemeral=True)
            return

        try:
            admin_role = discord.utils.get(interaction.guild.roles, name="Server Admin")
            if not admin_role:
                await interaction.response.send_message("❌ ไม่พบบทบาทแอดมินเซิร์ฟเวอร์", ephemeral=True)
                return

            if admin_role in user.roles:
                await interaction.response.send_message(f"❌ {user.mention} มียศแอดมินเซิร์ฟเวอร์อยู่แล้ว", ephemeral=True)
                return

            await user.add_roles(admin_role)
            logger.info(f"Gave server admin role to {user.name} in {interaction.guild.name}")
            await interaction.response.send_message(f"✅ ให้ยศแอดมินเซิร์ฟเวอร์แก่ {user.mention} เรียบร้อยแล้ว")

        except discord.Forbidden:
            await interaction.response.send_message("❌ บอทไม่มีสิทธิ์ในการจัดการบทบาท โปรดให้สิทธิ์ 'Administrator' แก่บอทก่อน", ephemeral=True)
        except Exception as e:
            logger.error(f"Error giving server admin role: {str(e)}")
            await interaction.response.send_message("❌ เกิดข้อผิดพลาดในการให้ยศแอดมินเซิร์ฟเวอร์", ephemeral=True)

    @app_commands.command(name="ลบแอดมินเซิร์ฟเวอร์", description="ลบยศแอดมินเซิร์ฟเวอร์จากผู้ใช้")
    @app_commands.describe(user="ผู้ใช้ที่จะลบยศแอดมินเซิร์ฟเวอร์")
    async def remove_server_admin(self, interaction: discord.Interaction, user: discord.Member):
        """ลบยศแอดมินเซิร์ฟเวอร์จากผู้ใช้"""
        if str(interaction.user.id) != self.allowed_user_id:
            await interaction.response.send_message("❌ เฉพาะแอดมินหลักเท่านั้นที่สามารถลบยศแอดมินเซิร์ฟเวอร์ได้", ephemeral=True)
            return

        try:
            admin_role = discord.utils.get(interaction.guild.roles, name="Server Admin")
            if not admin_role:
                await interaction.response.send_message("❌ ไม่พบบทบาทแอดมินเซิร์ฟเวอร์", ephemeral=True)
                return

            if admin_role not in user.roles:
                await interaction.response.send_message(f"❌ {user.mention} ไม่มียศแอดมินเซิร์ฟเวอร์", ephemeral=True)
                return

            await user.remove_roles(admin_role)
            logger.info(f"Removed server admin role from {user.name} in {interaction.guild.name}")
            await interaction.response.send_message(f"✅ ลบยศแอดมินเซิร์ฟเวอร์ของ {user.mention} เรียบร้อยแล้ว")

        except discord.Forbidden:
            await interaction.response.send_message("❌ บอทไม่มีสิทธิ์ในการจัดการบทบาท โปรดให้สิทธิ์ 'Administrator' แก่บอทก่อน", ephemeral=True)
        except Exception as e:
            logger.error(f"Error removing server admin role: {str(e)}")
            await interaction.response.send_message("❌ เกิดข้อผิดพลาดในการลบยศแอดมินเซิร์ฟเวอร์", ephemeral=True)

    @app_commands.command(name="แอดมินเซิร์ฟเวอร์", description="แสดงรายชื่อแอดมินเซิร์ฟเวอร์ทั้งหมด")
    async def list_server_admins(self, interaction: discord.Interaction):
        """แสดงรายชื่อแอดมินเซิร์ฟเวอร์ทั้งหมด"""
        try:
            admin_role = discord.utils.get(interaction.guild.roles, name="Server Admin")
            if not admin_role:
                await interaction.response.send_message("❌ ไม่พบบทบาทแอดมินเซิร์ฟเวอร์ในเซิร์ฟเวอร์นี้", ephemeral=True)
                return

            embed = discord.Embed(
                title="👑 รายชื่อแอดมินเซิร์ฟเวอร์",
                description=f"เซิร์ฟเวอร์: {interaction.guild.name}",
                color=discord.Color.red()
            )

            admin_members = [member for member in interaction.guild.members if admin_role in member.roles]
            if admin_members:
                admin_list = "\n".join([f"{member.mention} ({member.name})" for member in admin_members])
                embed.add_field(name="แอดมินเซิร์ฟเวอร์", value=admin_list, inline=False)
            else:
                embed.add_field(name="แอดมินเซิร์ฟเวอร์", value="ไม่มีแอดมินเซิร์ฟเวอร์", inline=False)

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error listing server admins: {str(e)}")
            await interaction.response.send_message("❌ เกิดข้อผิดพลาดในการแสดงรายชื่อแอดมินเซิร์ฟเวอร์", ephemeral=True)

    @app_commands.command(name="ตั้งค่าสถานะ", description="ตั้งค่าช่องสำหรับแสดงสถานะบอท")
    @app_commands.describe(channel="ช่องสำหรับแสดงสถานะ")
    async def setup_status(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """ตั้งค่าช่องสำหรับแสดงสถานะบอท"""
        if not self.is_admin(interaction.user.id):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)
            return

        try:
            # Create initial status message
            embed = discord.Embed(
                title="🤖 สถานะบอท",
                description="กำลังตั้งค่าสถานะ...",
                color=discord.Color.blue()
            )
            
            message = await channel.send(embed=embed)
            
            # Store channel and message
            self.status_channel = channel
            self.status_message = message
            
            # Save channel ID
            self.save_admin_config()
            
            await interaction.response.send_message(
                f"✅ ตั้งค่าช่องแสดงสถานะที่ {channel.mention} เรียบร้อยแล้ว",
                ephemeral=True
            )
            
            # Start or restart the update task
            if self.status_task:
                self.status_task.cancel()
            self.status_task = self.bot.loop.create_task(self.update_status())
            
        except Exception as e:
            logger.error(f"Error setting up status channel: {e}")
            await interaction.response.send_message(
                f"❌ เกิดข้อผิดพลาดในการตั้งค่าช่องแสดงสถานะ: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(name="ตรวจสอบสิทธิ์บอท", description="ตรวจสอบสิทธิ์ของบอทในเซิร์ฟเวอร์")
    async def check_bot_permissions(self, interaction: discord.Interaction):
        """ตรวจสอบสิทธิ์ของบอทในเซิร์ฟเวอร์"""
        try:
            # Get bot's member object
            bot_member = interaction.guild.get_member(self.bot.user.id)
            if not bot_member:
                await interaction.response.send_message("❌ ไม่พบข้อมูลบอทในเซิร์ฟเวอร์นี้", ephemeral=True)
                return

            # Get bot's permissions
            permissions = bot_member.guild_permissions
            
            # Create embed
            embed = discord.Embed(
                title="🔍 ตรวจสอบสิทธิ์บอท",
                description=f"เซิร์ฟเวอร์: {interaction.guild.name}",
                color=discord.Color.blue()
            )

            # Add permission fields
            permission_fields = {
                "👑 สิทธิ์หลัก": [
                    ("ผู้ดูแลระบบ", permissions.administrator),
                    ("จัดการเซิร์ฟเวอร์", permissions.manage_guild),
                    ("จัดการบทบาท", permissions.manage_roles),
                    ("จัดการช่อง", permissions.manage_channels)
                ],
                "📝 สิทธิ์ข้อความ": [
                    ("ส่งข้อความ", permissions.send_messages),
                    ("จัดการข้อความ", permissions.manage_messages),
                    ("ฝังลิงก์", permissions.embed_links),
                    ("แนบไฟล์", permissions.attach_files),
                    ("อ่านประวัติข้อความ", permissions.read_message_history)
                ],
                "🎵 สิทธิ์เสียง": [
                    ("เชื่อมต่อ", permissions.connect),
                    ("พูด", permissions.speak),
                    ("ใช้กิจกรรมเสียง", permissions.use_voice_activation),
                    ("ย้ายสมาชิก", permissions.move_members)
                ],
                "⚙️ สิทธิ์อื่นๆ": [
                    ("เพิ่มปฏิกิริยา", permissions.add_reactions),
                    ("สร้างการเชิญ", permissions.create_instant_invite),
                    ("เปลี่ยนชื่อเล่น", permissions.change_nickname),
                    ("จัดการเว็บฮุค", permissions.manage_webhooks)
                ]
            }

            for category, perms in permission_fields.items():
                value = "\n".join([f"{'✅' if perm else '❌'} {name}" for name, perm in perms])
                embed.add_field(name=category, value=value, inline=False)

            # Add footer with bot's role position and missing permissions
            role_position = bot_member.top_role.position
            missing_perms = []
            
            # Check for critical permissions
            if not permissions.administrator:
                missing_perms.append("ผู้ดูแลระบบ")
            if not permissions.manage_guild:
                missing_perms.append("จัดการเซิร์ฟเวอร์")
            if not permissions.manage_roles:
                missing_perms.append("จัดการบทบาท")
            if not permissions.manage_channels:
                missing_perms.append("จัดการช่อง")
            if not permissions.send_messages:
                missing_perms.append("ส่งข้อความ")
            if not permissions.embed_links:
                missing_perms.append("ฝังลิงก์")
            if not permissions.connect:
                missing_perms.append("เชื่อมต่อ")
            if not permissions.speak:
                missing_perms.append("พูด")
            
            if missing_perms:
                embed.add_field(name="⚠️ สิทธิ์ที่ขาดหาย", value=", ".join(missing_perms), inline=False)
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error checking bot permissions: {e}")
            await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {str(e)}", ephemeral=True)

    @app_commands.command(name="รายการเซิร์ฟเวอร์", description="แสดงรายชื่อเซิร์ฟเวอร์ทั้งหมดที่บอทอยู่")
    async def list_guilds(self, interaction: discord.Interaction):
        """แสดงรายชื่อเซิร์ฟเวอร์ทั้งหมดที่บอทอยู่"""
        if not self.is_admin(interaction.user.id):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)
            return

        guilds = self.bot.guilds
        if not guilds:
            return await interaction.response.send_message("บอทไม่ได้อยู่ในเซิร์ฟเวอร์ใดๆ", ephemeral=True)
            
        paginator = GuildPaginator(guilds, interaction.user)
        await interaction.response.send_message(embed=paginator.create_embed(), view=paginator, ephemeral=True)

    @app_commands.command(name="สร้างลิงก์เชิญเซิร์ฟเวอร์", description="สร้างลิงก์เชิญสำหรับเซิร์ฟเวอร์อื่นที่บอทอยู่")
    @app_commands.describe(guild_id="ID ของเซิร์ฟเวอร์ที่ต้องการสร้างลิงก์เชิญ")
    async def create_external_invite(self, interaction: discord.Interaction, guild_id: str):
        """สร้างลิงก์เชิญสำหรับเซิร์ฟเวอร์อื่น"""
        if not self.is_admin(interaction.user.id):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)
            return

        try:
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                await interaction.response.send_message(f"❌ ไม่พบเซิร์ฟเวอร์ที่มี ID: {guild_id}", ephemeral=True)
                return

            # Find a text channel to create invite
            channels = [c for c in guild.text_channels if c.permissions_for(guild.me).create_instant_invite]
            if not channels:
                # Try voice channels if no text channels
                channels = [c for c in guild.voice_channels if c.permissions_for(guild.me).create_instant_invite]
                
            if not channels:
                await interaction.response.send_message(f"❌ บอทไม่มีสิทธิ์สร้างลิงก์เชิญในเซิร์ฟเวอร์ {guild.name}", ephemeral=True)
                return

            channel = channels[0]
            # Create a 24h invite with 1 use
            invite = await channel.create_invite(max_age=86400, max_uses=1, unique=True, reason=f"Generated by {interaction.user.name}")
            
            await interaction.response.send_message(f"✅ สร้างลิงก์เชิญสำหรับ **{guild.name}** เรียบร้อยแล้ว:\n{invite.url}", ephemeral=True)
            logger.info(f"Invite generated for {guild.name} by {interaction.user.name}")

        except Exception as e:
            logger.error(f"Error generating external invite: {e}")
            await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {str(e)}", ephemeral=True)

            footer_text = f"ตำแหน่งยศสูงสุดของบอท: {role_position}"
            if missing_perms:
                footer_text += f"\n⚠️ สิทธิ์ที่ขาด: {', '.join(missing_perms)}"
            
            embed.set_footer(text=footer_text)

            # Add warning if bot doesn't have administrator permissions
            if not permissions.administrator:
                embed.add_field(
                    name="⚠️ คำเตือน",
                    value="บอทไม่มีสิทธิ์ผู้ดูแลระบบ ซึ่งอาจทำให้บางคำสั่งไม่ทำงาน\n"
                          "แนะนำให้ให้สิทธิ์ผู้ดูแลระบบแก่บอทเพื่อการทำงานที่สมบูรณ์",
                    inline=False
                )

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error checking bot permissions: {e}")
            await interaction.response.send_message("❌ เกิดข้อผิดพลาดในการตรวจสอบสิทธิ์", ephemeral=True)

    @app_commands.command(name="sync", description="ซิงค์คำสั่งกับ Discord")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync(self, interaction: discord.Interaction, scope: str = "guild", force: bool = False):
        """ซิงค์คำสั่งกับ Discord
        
        Parameters
        ----------
        scope: str
            ขอบเขตการซิงค์ (guild หรือ global)
        force: bool
            บังคับซิงค์ใหม่ทั้งหมด
        """
        if str(interaction.user.id) != self.allowed_user_id:
            await interaction.response.send_message("❌ เฉพาะเจ้าของบอทเท่านั้นที่สามารถใช้คำสั่งนี้ได้", ephemeral=True)
            return

        try:
            await interaction.response.defer(ephemeral=True)
            
            # Check if bot has required permissions
            bot_member = interaction.guild.get_member(self.bot.user.id)
            if not bot_member.guild_permissions.administrator:
                await interaction.followup.send(
                    "⚠️ บอทไม่มีสิทธิ์ผู้ดูแลระบบ ซึ่งอาจทำให้บางคำสั่งไม่ทำงาน\n"
                    "แนะนำให้ให้สิทธิ์ผู้ดูแลระบบแก่บอทเพื่อการทำงานที่สมบูรณ์",
                    ephemeral=True
                )
            
            if scope.lower() == "global":
                # Sync globally
                if force:
                    # Clear existing commands first
                    await self.bot.tree.clear_commands(guild=None)
                    await interaction.followup.send("🗑️ ล้างคำสั่งเก่าทั้งหมดแล้ว", ephemeral=True)
                
                synced = await self.bot.sync_commands()
                logger.info(f"/sync (global): Synced {len(synced[0]) if isinstance(synced, tuple) else len(synced)} commands globally.")
                await interaction.followup.send(f"✅ ซิงค์คำสั่งทั้งหมด {synced} คำสั่งเรียบร้อยแล้ว", ephemeral=True)
            else:
                # Sync to current guild
                if force:
                    # Clear existing commands first
                    await self.bot.tree.clear_commands(guild=interaction.guild)
                    await interaction.followup.send("🗑️ ล้างคำสั่งเก่าทั้งหมดแล้ว", ephemeral=True)
                
                synced = await self.bot.sync_commands(interaction.guild)
                logger.info(f"/sync (guild): Synced {len(synced[0]) if isinstance(synced, tuple) else len(synced)} commands to guild {interaction.guild.name}.")
                await interaction.followup.send(f"✅ ซิงค์คำสั่งทั้งหมด {synced} คำสั่งกับเซิร์ฟเวอร์นี้เรียบร้อยแล้ว", ephemeral=True)
                
        except discord.HTTPException as e:
            if e.status == 429:  # Rate limit hit
                retry_after = e.retry_after
                await interaction.followup.send(
                    f"⏳ กำลังรอ {retry_after} วินาทีเพื่อซิงค์คำสั่งอีกครั้ง...",
                    ephemeral=True
                )
                await asyncio.sleep(retry_after)
                try:
                    if scope.lower() == "global":
                        synced = await self.bot.sync_commands()
                    else:
                        synced = await self.bot.sync_commands(interaction.guild)
                    await interaction.followup.send(f"✅ ซิงค์คำสั่งทั้งหมด {synced} คำสั่งเรียบร้อยแล้ว", ephemeral=True)
                except Exception as e:
                    logger.error(f"Error in sync retry: {e}")
                    await interaction.followup.send("❌ เกิดข้อผิดพลาดในการซิงค์คำสั่ง", ephemeral=True)
            else:
                logger.error(f"Error in sync command: {e}")
                await interaction.followup.send("❌ เกิดข้อผิดพลาดในการซิงค์คำสั่ง", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in sync command: {e}")
            await interaction.followup.send("❌ เกิดข้อผิดพลาดในการซิงค์คำสั่ง", ephemeral=True)

    def _run_stress_calc(self, level):
        """Heavy CPU work to be run in a thread"""
        try:
            # Matrix multiplication for CPU stress
            size = 500 * level 
            matrix1 = [[i + j for j in range(size)] for i in range(size)]
            matrix2 = [[i * j for j in range(size)] for i in range(size)]
            result = [[sum(a * b for a, b in zip(row, col)) for col in zip(*matrix2)] for row in matrix1]
            
            # Prime number calculation for additional stress
            for i in range(500 * level):
                num = i * 1000
                is_prime = True
                for j in range(2, int(num ** 0.5) + 1):
                    if num % j == 0:
                        is_prime = False
                        break
            return True
        except Exception as e:
            logger.error(f"Error in stress calc thread: {e}")
            return False

    async def stress_cpu(self):
        """Background task to stress CPU safely by using a separate thread"""
        while self.stress_active:
            try:
                # Run heavy work in a thread to keep event loop responsive
                await asyncio.to_thread(self._run_stress_calc, self.stress_level)
                
                # Delay to prevent 100% CPU usage and allow other tasks
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Error in stress task: {e}")
                await asyncio.sleep(1)

    def _calculate_score(self, avg_cpu, memory_mb, iterations):
        """Calculate a performance score based on benchmark data"""
        # Logic: More iterations is better, higher CPU is expected during benchmark
        base_score = iterations / 100
        cpu_bonus = avg_cpu * 2
        mem_penalty = max(0, memory_mb - 500) # Penalty for leaking?
        final_score = int(base_score + cpu_bonus - mem_penalty)
        
        if final_score > 5000: grade = "S (ยอดเยี่ยม)"
        elif final_score > 3500: grade = "A (ดีมาก)"
        elif final_score > 2000: grade = "B (ปกติ)"
        elif final_score > 1000: grade = "C (พอใช้)"
        else: grade = "D (ต้องการการอัปเกรด)"
        
        return final_score, grade

    def _get_progress_bar(self, current, total, length=15):
        percent = current / total
        filled = int(length * percent)
        return "▰" * filled + "▱" * (length - filled)

    @app_commands.command(name="วินิจฉัยระบบ", description="วิเคราะห์และทดสอบประสิทธิภาพบอทแบบละเอียด")
    @app_commands.describe(seconds="ระยะเวลาในการรันการตรวจสอบ (5-60 วินาที)")
    async def system_diagnostics(self, interaction: discord.Interaction, seconds: int = 15):
        """รันการตรวจสอบระบบแบบละเอียด"""
        if not self.is_admin(interaction.user.id):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)
            return

        if seconds < 5 or seconds > 60:
            return await interaction.response.send_message("❌ ระยะเวลาต้องอยู่ระหว่าง 5 ถึง 60 วินาที", ephemeral=True)

        if self.stress_active:
            return await interaction.response.send_message("⚠️ กำลังรันการตรวจสอบระบบอยู่แล้วในขณะนี้", ephemeral=True)

        try:
            await interaction.response.defer(ephemeral=True)
            
            self.stress_active = True
            self.stress_level = 5 # Default level for diagnostics
            self.stress_start_time = datetime.now()
            iters = 0
            
            # Start background stress task
            self.stress_task = self.bot.loop.create_task(self.stress_cpu())
            
            embed = discord.Embed(
                title="🔍 กำลังรันการวินิจฉัยระบบ...",
                description="บอทกำลังทำการทดสอบโหลด CPU และตรวจสอบค่าสถิติต่างๆ",
                color=discord.Color.blue()
            )
            
            msg = await interaction.followup.send(embed=embed)
            
            # Monitoring loop
            cpu_samples = []
            for i in range(seconds):
                if not self.stress_active: break
                
                # Get current stats
                process = psutil.Process()
                curr_cpu = psutil.cpu_percent()
                cpu_samples.append(curr_cpu)
                memory_mb = process.memory_info().rss / 1024 / 1024
                latency = round(self.bot.latency * 1000)
                
                prog = self._get_progress_bar(i + 1, seconds)
                embed.description = (
                    f"**สถานะการตรวจสอบ:** `{prog}` ({i+1}/{seconds}s)\n\n"
                    f"**ประสิทธิภาพปัจจุบัน:**\n"
                    f"🖥️ CPU Usage: `{curr_cpu}%` (System)\n"
                    f"💾 Memory: `{memory_mb:.1f} MB` (Process)\n"
                    f"📡 Latency: `{latency}ms` (Discord API)\n"
                    f"⚙️ Level: `{self.stress_level}/10`"
                )
                
                await interaction.edit_original_response(embed=embed)
                await asyncio.sleep(1)
                iters += 10 # Simulated work tracking

            # Wrap up
            self.stress_active = False
            if self.stress_task:
                self.stress_task.cancel()

            avg_cpu = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0
            score, grade = self._calculate_score(avg_cpu, memory_mb, iters * 100)
            
            # final report
            report_embed = discord.Embed(
                title="✅ ผลการวินิจฉัยระบบเสร็จสิ้น",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            report_embed.description = f"บอททำงานบนสภาพแวดล้อมที่ **{grade}**"
            
            report_embed.add_field(name="📊 คะแนนรวม", value=f"**{score:,}**", inline=True)
            report_embed.add_field(name="🏆 เกรด", value=f"**{grade}**", inline=True)
            report_embed.add_field(name="🕒 ระยะเวลาที่ทดสอบ", value=f"`{seconds} วินาที`", inline=True)
            
            report_embed.add_field(
                name="💻 สรุป CPU & RAM", 
                value=f"ค่าเฉลี่ย CPU: `{avg_cpu:.1f}%`\nการจอง RAM สูงสุด: `{memory_mb:.1f} MB`", 
                inline=False
            )
            
            report_embed.add_field(
                name="🌐 สรุปการเชื่อมต่อ", 
                value=f"ความหน่วงเฉลี่ย: `{latency}ms` (Discord)", 
                inline=False
            )
            
            report_embed.set_footer(text=f"วินิจฉัยโดย: {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
            
            await interaction.edit_original_response(embed=report_embed)

        except Exception as e:
            self.stress_active = False
            logger.error(f"Error in diagnostics: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาดในการวินิจฉัย: {e}", ephemeral=True)

    @app_commands.command(name="หยุดวินิจฉัย", description="หยุดการตรวจสอบระบบที่กำลังรันอยู่")
    async def stop_diagnostics(self, interaction: discord.Interaction):
        """หยุดการตรวจสอบระบบ"""
        if not self.is_admin(interaction.user.id):
            return await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)

        if self.stress_active:
            self.stress_active = False
            if self.stress_task: self.stress_task.cancel()
            await interaction.response.send_message("🛑 สั่งหยุดการวินิจฉัยระบบเรียบร้อยแล้ว", ephemeral=True)
        else:
            await interaction.response.send_message("❌ ไม่มีการวินิจฉัยที่กำลังรันอยู่", ephemeral=True)

    @app_commands.command(name="สร้างลิงก์เชิญ", description="สร้างลิงก์เชิญสำหรับเซิร์ฟเวอร์")
    @app_commands.describe(
        max_uses="จำนวนครั้งสูงสุดที่ใช้ลิงก์ได้ (0 = ไม่จำกัด)",
        max_age="อายุของลิงก์เป็นวินาที (0 = ไม่หมดอายุ)",
        temporary="ลิงก์ชั่วคราวหรือไม่ (สมาชิกจะถูกเตะเมื่อออกจากเซิร์ฟเวอร์)"
    )
    async def create_invite(self, interaction: discord.Interaction, max_uses: int = 0, max_age: int = 0, temporary: bool = False):
        """สร้างลิงก์เชิญสำหรับเซิร์ฟเวอร์"""
        try:
            # Check permissions
            if not interaction.user.guild_permissions.create_instant_invite:
                await interaction.response.send_message(
                    "❌ คุณไม่มีสิทธิ์ในการสร้างลิงก์เชิญ\n"
                    "ต้องการสิทธิ์: สร้างการเชิญ",
                    ephemeral=True
                )
                return

            # Create invite
            invite = await interaction.channel.create_invite(
                max_uses=max_uses,
                max_age=max_age,
                temporary=temporary
            )

            # Track statistics
            stats_cog = self.bot.get_cog('Stats')
            if stats_cog:
                stats_cog.update_user_stats(str(interaction.user.id), "invites_sent")
                stats_cog.update_server_stats(str(interaction.guild.id), "invites")

            # Create embed
            embed = discord.Embed(
                title="🔗 ลิงก์เชิญ",
                description=f"ลิงก์เชิญสำหรับ {interaction.guild.name}",
                color=discord.Color.green()
            )

            # Add invite details
            embed.add_field(
                name="ลิงก์",
                value=f"[คลิกที่นี่]({invite.url})",
                inline=False
            )

            details = []
            if max_uses > 0:
                details.append(f"จำนวนครั้งที่ใช้ได้: {max_uses}")
            if max_age > 0:
                hours = max_age // 3600
                minutes = (max_age % 3600) // 60
                details.append(f"หมดอายุใน: {hours} ชั่วโมง {minutes} นาที")
            if temporary:
                details.append("สมาชิกชั่วคราว")
            
            if details:
                embed.add_field(
                    name="รายละเอียด",
                    value="\n".join(details),
                    inline=False
                )

            # Add statistics
            if stats_cog:
                user_stats = stats_cog.stats["users"].get(str(interaction.user.id), {})
                total_invites = user_stats.get("invites_sent", 0)
                embed.add_field(
                    name="📊 สถิติ",
                    value=f"คุณได้สร้างลิงก์เชิญทั้งหมด {total_invites:,} ครั้ง",
                    inline=False
                )

            embed.set_footer(text=f"สร้างโดย {interaction.user.name}")

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ บอทไม่มีสิทธิ์ในการสร้างลิงก์เชิญ\n"
                "ต้องการสิทธิ์: สร้างการเชิญ",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error creating invite: {e}")
            await interaction.response.send_message("❌ เกิดข้อผิดพลาดในการสร้างลิงก์เชิญ", ephemeral=True)

    @app_commands.command(name="ตรวจสอบผู้ใช้", description="ตรวจสอบสถานะการแบนและเตะของผู้ใช้")
    @app_commands.describe(user="ผู้ใช้ที่ต้องการตรวจสอบ")
    async def check_user_status(self, interaction: discord.Interaction, user: discord.User):
        """ตรวจสอบสถานะการแบนและเตะของผู้ใช้"""
        try:
            # Check permissions
            if not interaction.user.guild_permissions.ban_members:
                await interaction.response.send_message(
                    "❌ คุณไม่มีสิทธิ์ในการตรวจสอบผู้ใช้\n"
                    "ต้องการสิทธิ์: แบนสมาชิก",
                    ephemeral=True
                )
                return

            # Defer response since this might take time
            await interaction.response.defer(ephemeral=True)

            # Create embed
            embed = discord.Embed(
                title="🔍 ตรวจสอบผู้ใช้",
                description=f"ข้อมูลของ {user.mention}",
                color=discord.Color.blue()
            )

            # Add user info
            embed.add_field(
                name="ข้อมูลผู้ใช้",
                value=f"ชื่อ: {user.name}\nID: {user.id}",
                inline=False
            )

            # Get statistics
            stats_cog = self.bot.get_cog('Stats')
            user_stats = {}
            if stats_cog:
                user_stats = stats_cog.stats["users"].get(str(user.id), {})

            # Check bans
            ban_list = []
            for guild in self.bot.guilds:
                try:
                    ban_entry = await guild.fetch_ban(user)
                    if ban_entry:
                        ban_list.append(f"**{guild.name}**\nเหตุผล: {ban_entry.reason or 'ไม่มีเหตุผล'}")
                except discord.NotFound:
                    continue
                except discord.Forbidden:
                    ban_list.append(f"**{guild.name}**\nไม่สามารถตรวจสอบได้ (ไม่มีสิทธิ์)")

            if ban_list:
                embed.add_field(
                    name="🚫 ถูกแบนจากเซิร์ฟเวอร์",
                    value="\n\n".join(ban_list),
                    inline=False
                )
            else:
                embed.add_field(
                    name="✅ สถานะการแบน",
                    value="ไม่พบการแบนจากเซิร์ฟเวอร์ใดๆ",
                    inline=False
                )

            # Check kicks
            kick_list = []
            if stats_cog and "kicks" in stats_cog.stats:
                for server_id, kicks in stats_cog.stats["kicks"].items():
                    if str(user.id) in kicks:
                        kick_info = kicks[str(user.id)]
                        kick_list.append(f"**{kick_info['guild_name']}**\nเมื่อ: {kick_info['timestamp']}")

            if kick_list:
                embed.add_field(
                    name="👢 ถูกเตะจากเซิร์ฟเวอร์",
                    value="\n\n".join(kick_list),
                    inline=False
                )

            # Check if user is in any mutual servers
            mutual_servers = []
            for guild in self.bot.guilds:
                if guild.get_member(user.id):
                    mutual_servers.append(guild.name)

            if mutual_servers:
                embed.add_field(
                    name="🌐 เซิร์ฟเวอร์ที่อยู่ร่วมกัน",
                    value="\n".join([f"• {server}" for server in mutual_servers]),
                    inline=False
                )

            # Add user statistics if available
            if user_stats:
                stats_info = []
                if "messages" in user_stats:
                    stats_info.append(f"ข้อความ: {user_stats['messages']:,} ข้อความ")
                if "commands" in user_stats:
                    stats_info.append(f"คำสั่ง: {user_stats['commands']:,} ครั้ง")
                if "invites_sent" in user_stats:
                    stats_info.append(f"การเชิญ: {user_stats['invites_sent']:,} ครั้ง")
                if "voice_time" in user_stats:
                    hours = user_stats["voice_time"] // 3600
                    minutes = (user_stats["voice_time"] % 3600) // 60
                    stats_info.append(f"เวลาในช่องเสียง: {hours:,} ชั่วโมง {minutes:,} นาที")

                if stats_info:
                    embed.add_field(
                        name="📊 สถิติผู้ใช้",
                        value="\n".join(stats_info),
                        inline=False
                    )

            # Add footer with timestamp
            embed.set_footer(text=f"ตรวจสอบเมื่อ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error checking user status: {e}")
            await interaction.followup.send("❌ เกิดข้อผิดพลาดในการตรวจสอบผู้ใช้", ephemeral=True)

    @app_commands.command(name="ประกาศ_ทุกคน", description="ส่ง DM ข้อความประกาศหาทุกคน (แอดมินบอทสามารถส่งข้ามเซิฟร์ได้)")
    @app_commands.describe(
        หัวข้อ="หัวข้อประกาศ",
        เนื้อหา="เนื้อหาประกาศ",
        รูปภาพ="ลิงก์รูปภาพ (ไม่จำเป็น)",
        ข้ามเซิร์ฟ="ส่งหาทุกคนในทุกเซิฟร์ที่บอทอยู่ (แอดมินบอทเท่านั้น)",
        ยศ="ส่งเฉพาะสมาชิกที่มียศนี้ (ไม่เลือก = ส่งทุกคน)"
    )
    async def broadcast_dm(self, interaction: discord.Interaction, หัวข้อ: str, เนื้อหา: str, รูปภาพ: str = None, ข้ามเซิร์ฟ: bool = False, ยศ: Optional[discord.Role] = None):
        """ส่ง DM ประกาศหาทุกคนในเซิร์ฟเวอร์แบบมืออาชีพ"""
        if not self.is_server_admin_or_bot_admin(interaction):
            return await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้ (ต้องเป็นแอดมินเซิร์ฟเวอร์หรือแอดมินบอท)", ephemeral=True)

        # Only bot owner can cross-server broadcast
        is_bot_owner = str(interaction.user.id) == self.allowed_user_id
        if ข้ามเซิร์ฟ and not is_bot_owner:
            return await interaction.response.send_message("❌ การส่งข้ามเซิฟร์ใช้ได้เฉพาะแอดมินของบอทเท่านั้น", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # Load or create broadcast log to prevent duplicates
        log_file = "data/broadcast_log.json"
        os.makedirs("data", exist_ok=True)
        broadcast_key = f"{หัวข้อ}_{datetime.now().strftime('%Y-%m-%d')}"
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                broadcast_log = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            broadcast_log = {}

        already_sent_ids = set(broadcast_log.get(broadcast_key, []))

        # Build target guild list
        target_guilds = list(self.bot.guilds) if ข้ามเซิร์ฟ else [interaction.guild]

        sent = 0
        failed = 0
        skipped = 0
        sent_list = []
        failed_list = []
        guild_summaries = []

        status_msg = await interaction.followup.send(
            f"⏳ เริ่มการส่งประกาศ {'ข้ามเซิฟร์ทั้งหมด' if ข้ามเซิร์ฟ else f'ในเซิฟร์ {interaction.guild.name}'}..."
            f"{f' (ยศ: {ยศ.name})' if ยศ else ''}"
        )

        for guild in target_guilds:
            g_sent = 0
            g_failed = 0
            g_skipped = 0

            # Ensure we have member list (requires members intent)
            members = [m for m in guild.members if not m.bot]
            
            # Filter by role if specified
            if ยศ:
                members = [m for m in members if ยศ in m.roles]
            
            total = len(members)

            for i, member in enumerate(members):
                # Skip if already sent
                if member.id in already_sent_ids:
                    skipped += 1
                    g_skipped += 1
                    continue

                try:
                    # Progress every 5 or each person
                    remaining = total - i
                    eta_seconds = remaining * 3
                    eta_str = f"{eta_seconds // 60} นาที {eta_seconds % 60} วิ" if eta_seconds > 60 else f"{eta_seconds} วิ"
                    try:
                        await status_msg.edit(content=(
                            f"📡 **กำลังส่งประกาศ...** [{guild.name}] ({i+1}/{total})\n"
                            f"👤 **ผู้รับปัจจุบัน:** {member.name}\n"
                            f"📥 ส่งแล้ว: {sent} | ⏭️ ข้ามแล้ว: {skipped} | ❌ ล้มเหลว: {failed}\n"
                            f"⏱️ **เวลาที่เหลือ (เซิฟร์นี้):** {eta_str}"
                        ))
                    except: pass

                    embed = discord.Embed(
                        title=f"📢 {หัวข้อ}",
                        description=เนื้อหา,
                        color=discord.Color.gold(),
                        timestamp=datetime.now()
                    )
                    if รูปภาพ:
                        try: embed.set_image(url=รูปภาพ)
                        except: pass

                    embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
                    embed.set_footer(text=f"ประกาศอย่างเป็นทางการจาก {guild.name}")

                    await member.send(embed=embed)
                    sent += 1
                    g_sent += 1
                    sent_list.append(member.name)
                    already_sent_ids.add(member.id)
                    await asyncio.sleep(3)

                except (discord.Forbidden, discord.HTTPException):
                    failed += 1
                    g_failed += 1
                    failed_list.append(f"{member.name} ({guild.name})") 
                    logger.info(f"Cannot send DM to {member.name}")
                except Exception as e:
                    failed += 1
                    g_failed += 1
                    failed_list.append(f"{member.name} (Error)")
                    logger.warning(f"Broadcast error for {member.name}: {e}")

            guild_summaries.append(f"**{guild.name}**: ✅{g_sent} ⏭️{g_skipped} ❌{g_failed}")

        # Save updated broadcast log
        broadcast_log[broadcast_key] = list(already_sent_ids)
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(broadcast_log, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving broadcast log: {e}")

        # Build final summary embed
        sent_str = ", ".join(sent_list)
        if len(sent_str) > 450: sent_str = sent_str[:447] + "..."
        failed_str = ", ".join(failed_list) if failed_list else "ไม่มี"
        if len(failed_str) > 450: failed_str = failed_str[:447] + "..."

        final_embed = discord.Embed(
            title="✅ ส่งประกาศเสร็จสิ้น!",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        final_embed.add_field(name=f"📥 ส่งสำเร็จ ({sent})", value=f"```{sent_str if sent_str else 'ไม่มี'}```", inline=False)
        final_embed.add_field(name=f"❌ ส่งไม่สำเร็จ ({failed})", value=f"```{failed_str}```", inline=False)
        if skipped: final_embed.add_field(name=f"⏭️ ข้ามแล้ว (ส่งไปแล้ววันนี้) ({skipped})", value="ป้องกันการส่งซ้ำ", inline=False)
        if ข้ามเซิร์ฟ:
            guild_summary_str = "\n".join(guild_summaries)
            if len(guild_summary_str) > 900: guild_summary_str = guild_summary_str[:897] + "..."
            final_embed.add_field(name="🌐 สรุปรายเซิฟร์", value=guild_summary_str, inline=False)
        final_embed.set_footer(text="คนที่ไม่สำเร็จมักเกิดจาก ปิด DM หรือบล็อกบอท")

        await status_msg.edit(content=None, embed=final_embed)

    @app_commands.command(name="ทดสอบ_ประกาศ", description="ทดสอบส่ง DM ประกาศหาตัวเองเพื่อดูตัวอย่างก่อนส่งจริง")
    @app_commands.describe(หัวข้อ="หัวข้อประกาศ", เนื้อหา="เนื้อหาประกาศ", รูปภาพ="ลิงก์รูปภาพ (ไม่จำเป็น)")
    async def test_broadcast_dm(self, interaction: discord.Interaction, หัวข้อ: str, เนื้อหา: str, รูปภาพ: str = None):
        """ส่งตัวอย่างประกาศหาตัวเอง"""
        if not self.is_server_admin_or_bot_admin(interaction):
            return await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้ (ต้องเป็นแอดมินเซิร์ฟเวอร์หรือแอดมินบอท)", ephemeral=True)
            
        try:
            embed = discord.Embed(
                title=f"📢 {หัวข้อ}",
                description=เนื้อหา,
                color=discord.Color.gold(),
                timestamp=datetime.now()
            )
            if รูปภาพ:
                try:
                    embed.set_image(url=รูปภาพ)
                except: pass
            
            embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
            embed.set_footer(text=f"ส่งโดย {interaction.user.name} (โหมดทดสอบ)")
            
            await interaction.user.send(embed=embed)
            await interaction.response.send_message("✅ ส่งตัวอย่างเข้า DM ของคุณแล้ว กรุณาตรวจสอบก่อนส่งจริง!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ ไม่สามารถส่ง DM หาคุณได้: {str(e)}", ephemeral=True)

    @app_commands.command(name="ประกาศ_ช่อง", description="ส่งข้อความประกาศลงในช่องที่ระบุ")
    @app_commands.describe(ช่อง="ช่องที่ต้องการประกาศ", หัวข้อ="หัวข้อ", เนื้อหา="เนื้อหา", รูปภาพ="ลิงก์รูปภาพ")
    async def broadcast_channel(self, interaction: discord.Interaction, ช่อง: discord.TextChannel, หัวข้อ: str, เนื้อหา: str, รูปภาพ: str = None):
        """ประกาศในช่องแชทแบบสวยงาม"""
        if not self.is_server_admin_or_bot_admin(interaction):
            return await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้ (ต้องเป็นแอดมินเซิร์ฟเวอร์หรือแอดมินบอท)", ephemeral=True)

        embed = discord.Embed(
            title=f"📣 {หัวข้อ}",
            description=เนื้อหา,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        if รูปภาพ:
            try:
                embed.set_image(url=รูปภาพ)
            except: pass
            
        embed.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"ประกาศโดย {interaction.user.name}")
        
        await ช่อง.send(embed=embed)
        await interaction.response.send_message(f"✅ ส่งประกาศลงในช่อง {ช่อง.mention} เรียบร้อยแล้ว", ephemeral=True)

    @app_commands.command(name="dm", description="ส่ง DM หาสมาชิกเฉพาะคนที่เลือก")
    @app_commands.describe(
        ผู้ใช้="สมาชิกที่ต้องการส่ง DM หา (เลือกได้สูงสุด 10 คน)",
        หัวข้อ="หัวข้อข้อความ",
        เนื้อหา="เนื้อหาข้อความ",
        รูปภาพ="ลิงก์รูปภาพ (ไม่จำเป็น)"
    )
    async def dm_users(
        self, 
        interaction: discord.Interaction, 
        ผู้ใช้: discord.Member,
        หัวข้อ: str,
        เนื้อหา: str,
        รูปภาพ: str = None
    ):
        """ส่ง DM หาสมาชิกเฉพาะคนที่เลือก"""
        if not self.is_server_admin_or_bot_admin(interaction):
            return await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้ (ต้องเป็นแอดมินเซิร์ฟเวอร์หรือแอดมินบอท)", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        
        sent = 0
        failed = 0
        failed_list = []
        
        # Create the DM embed
        embed = discord.Embed(
            title=f"📩 {หัวข้อ}",
            description=เนื้อหา,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        if รูปภาพ:
            try:
                embed.set_image(url=รูปภาพ)
            except:
                pass
        
        embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        embed.set_footer(text=f"ส่งโดย {interaction.user.name}")
        
        # Send DM to each user
        status_msg = await interaction.followup.send(f"⏳ กำลังส่ง DM หา {ผู้ใช้.name}...")
        
        try:
            await ผู้ใช้.send(embed=embed)
            sent += 1
            await status_msg.edit(content=f"✅ ส่ง DM สำเร็จหา {ผู้ใช้.mention} เรียบร้อยแล้ว")
        except (discord.Forbidden, discord.HTTPException):
            failed += 1
            failed_list.append(ผู้ใช้.name)
            await status_msg.edit(content=f"❌ ไม่สามารถส่ง DM หา {ผู้ใช้.mention} ได้ (อาจปิด DM หรือบล็อกบอท)")
        except Exception as e:
            failed += 1
            failed_list.append(f"{ผู้ใช้.name} (Error)")
            logger.warning(f"DM error for {ผู้ใช้.name}: {e}")
            await status_msg.edit(content=f"❌ เกิดข้อผิดพลาดในการส่ง DM หา {ผู้ใช้.mention}")

    @app_commands.command(name="dm_หลายคน", description="ส่ง DM หาสมาชิกหลายคนพร้อมกัน (สูงสุด 10 คน)")
    @app_commands.describe(
        ผู้ใช้1="สมาชิกคนที่ 1",
        ผู้ใช้2="สมาชิกคนที่ 2 (ไม่จำเป็น)",
        ผู้ใช้3="สมาชิกคนที่ 3 (ไม่จำเป็น)",
        ผู้ใช้4="สมาชิกคนที่ 4 (ไม่จำเป็น)",
        ผู้ใช้5="สมาชิกคนที่ 5 (ไม่จำเป็น)",
        ผู้ใช้6="สมาชิกคนที่ 6 (ไม่จำเป็น)",
        ผู้ใช้7="สมาชิกคนที่ 7 (ไม่จำเป็น)",
        ผู้ใช้8="สมาชิกคนที่ 8 (ไม่จำเป็น)",
        ผู้ใช้9="สมาชิกคนที่ 9 (ไม่จำเป็น)",
        ผู้ใช้10="สมาชิกคนที่ 10 (ไม่จำเป็น)",
        หัวข้อ="หัวข้อข้อความ",
        เนื้อหา="เนื้อหาข้อความ",
        รูปภาพ="ลิงก์รูปภาพ (ไม่จำเป็น)"
    )
    async def dm_multiple_users(
        self, 
        interaction: discord.Interaction, 
        ผู้ใช้1: discord.Member,
        หัวข้อ: str,
        เนื้อหา: str,
        ผู้ใช้2: Optional[discord.Member] = None,
        ผู้ใช้3: Optional[discord.Member] = None,
        ผู้ใช้4: Optional[discord.Member] = None,
        ผู้ใช้5: Optional[discord.Member] = None,
        ผู้ใช้6: Optional[discord.Member] = None,
        ผู้ใช้7: Optional[discord.Member] = None,
        ผู้ใช้8: Optional[discord.Member] = None,
        ผู้ใช้9: Optional[discord.Member] = None,
        ผู้ใช้10: Optional[discord.Member] = None,
        รูปภาพ: str = None
    ):
        """ส่ง DM หาสมาชิกหลายคนพร้อมกัน"""
        if not self.is_server_admin_or_bot_admin(interaction):
            return await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้ (ต้องเป็นแอดมินเซิร์ฟเวอร์หรือแอดมินบอท)", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        
        # Collect all users
        users = [ผู้ใช้1, ผู้ใช้2, ผู้ใช้3, ผู้ใช้4, ผู้ใช้5, 
                 ผู้ใช้6, ผู้ใช้7, ผู้ใช้8, ผู้ใช้9, ผู้ใช้10]
        users = [u for u in users if u is not None]  # Remove None values
        
        sent = 0
        failed = 0
        failed_list = []
        
        # Create the DM embed
        embed = discord.Embed(
            title=f"📩 {หัวข้อ}",
            description=เนื้อหา,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        if รูปภาพ:
            try:
                embed.set_image(url=รูปภาพ)
            except:
                pass
        
        embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        embed.set_footer(text=f"ส่งโดย {interaction.user.name}")
        
        # Send DM to each user
        status_msg = await interaction.followup.send(f"⏳ กำลังส่ง DM หา {len(users)} คน...")
        
        for i, user in enumerate(users):
            try:
                await status_msg.edit(content=f"⏳ กำลังส่ง DM หา {user.name}... ({i+1}/{len(users)})")
                await user.send(embed=embed)
                sent += 1
                await asyncio.sleep(1)  # Small delay to avoid rate limits
            except (discord.Forbidden, discord.HTTPException):
                failed += 1
                failed_list.append(user.name)
                logger.info(f"Cannot send DM to {user.name}")
            except Exception as e:
                failed += 1
                failed_list.append(f"{user.name} (Error)")
                logger.warning(f"DM error for {user.name}: {e}")
        
        # Build final summary embed
        final_embed = discord.Embed(
            title="✅ ส่ง DM เสร็จสิ้น!",
            color=discord.Color.green() if failed == 0 else discord.Color.orange(),
            timestamp=datetime.now()
        )
        final_embed.add_field(name=f"📥 ส่งสำเร็จ", value=f"{sent} คน", inline=True)
        final_embed.add_field(name=f"❌ ส่งไม่สำเร็จ", value=f"{failed} คน", inline=True)
        if failed_list:
            failed_str = ", ".join(failed_list)
            if len(failed_str) > 1000:
                failed_str = failed_str[:997] + "..."
            final_embed.add_field(name="รายชื่อที่ส่งไม่สำเร็จ", value=failed_str, inline=False)
        final_embed.set_footer(text="คนที่ไม่สำเร็จมักเกิดจาก ปิด DM หรือบล็อกบอท")
        
        await status_msg.edit(content=None, embed=final_embed)

async def setup(bot):
    await bot.add_cog(Admin(bot)) 
