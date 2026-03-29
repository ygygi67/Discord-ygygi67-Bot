import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# CONFIG PATH
# ─────────────────────────────────────────
_BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.normpath(os.path.join(_BASE, "..", "..", "data", "server_link_config.json"))

def _load_config() -> dict:
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading server_link_config: {e}")
    return {}

def _save_config(data: dict):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Error saving server_link_config: {e}")

def get_guild_settings(guild_id: int) -> dict:
    config = _load_config()
    defaults = {
        "private_room_enabled": False,
        "private_room_category_id": None,
        "ai_room_allowed": True,
        "cross_chat_enabled": False,
        "intercom_channel_id": None,
        "remind_setup": True,
        "last_remind_time": None
    }
    guild_data = config.get(str(guild_id), {})
    for k, v in defaults.items():
        if k not in guild_data:
            guild_data[k] = v
    return guild_data

def update_guild_settings(guild_id: int, **kwargs):
    config = _load_config()
    gid_str = str(guild_id)
    if gid_str not in config:
        config[gid_str] = {
            "private_room_enabled": False,
            "private_room_category_id": None,
            "ai_room_allowed": True,
            "cross_chat_enabled": False,
            "intercom_channel_id": None,
            "remind_setup": True,
            "last_remind_time": None
        }
    config[gid_str].update(kwargs)
    _save_config(config)

class ServerSetupView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self._set_buttons()

    def _set_buttons(self):
        settings = get_guild_settings(self.guild_id)
        
        # We can use buttons or selects for a nicer UI
        # But for now let's keep it simple with a summary embed and specific setup commands
        pass

class ServerLink(commands.Cog):
    """🌐 Server Link & Private Room Management"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminder_task.start()

    def cog_unload(self):
        self.reminder_task.cancel()

    # ──────────────────────────────────────
    # ⚙️ ADMIN SETUP
    # ──────────────────────────────────────

    @app_commands.command(name="setup_server", description="⚙️ ตั้งค่าระบบห้องแชทและลิงก์ข้ามเซิร์ฟเวอร์")
    @app_commands.describe(
        private_room="เปิดใช้งานระบบคำสั่งสร้างห้องคุยส่วนตัว (/private_chat)",
        category="เลือกหมวดหมู่ที่จะสร้างห้อง (ถ้าไม่เลือก บอทจะสร้างเอง)",
        ai_room="อนุญาตให้ผู้เล่นใช้คำสั่ง /ai_myroom ของบอท",
        cross_chat="เปิดใช้งานระบบคุยข้ามเซิร์ฟเวอร์ (Intercom)",
        reminder="เปิด/ปิด การแจ้งเตือนตั้งค่ารายสัปดาห์ (DM หาผู้สร้างเซิร์ฟ)"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def setup_server(
        self, 
        interaction: discord.Interaction, 
        private_room: Optional[bool] = None,
        category: Optional[discord.CategoryChannel] = None,
        ai_room: Optional[bool] = None,
        cross_chat: Optional[bool] = None,
        reminder: Optional[bool] = None
    ):
        guild_id = interaction.guild_id
        updates = {}
        if private_room is not None: updates["private_room_enabled"] = private_room
        if category is not None: updates["private_room_category_id"] = category.id
        if ai_room is not None: updates["ai_room_allowed"] = ai_room
        if cross_chat is not None: updates["cross_chat_enabled"] = cross_chat
        if reminder is not None: updates["remind_setup"] = reminder

        if not updates:
            settings = get_guild_settings(guild_id)
            embed = discord.Embed(title=f"📊 ตั้งค่าปัจจุบันของ {interaction.guild.name}", color=discord.Color.blue())
            embed.add_field(name="🔒 ระบบห้องแชทส่วนตัว", value="✅ เปิด" if settings["private_room_enabled"] else "❌ ปิด", inline=True)
            cat = interaction.guild.get_channel(settings["private_room_category_id"]) if settings["private_room_category_id"] else None
            embed.add_field(name="📂 หมวดหมู่", value=cat.mention if cat else "สร้างเองอัตโนมัติ", inline=True)
            embed.add_field(name="🤖 AI Room Allowed", value="✅ ใช่" if settings["ai_room_allowed"] else "❌ ไม่", inline=True)
            embed.add_field(name="🌐 คุยข้ามเซิร์ฟ", value="✅ เปิด" if settings["cross_chat_enabled"] else "❌ ปิด", inline=True)
            embed.add_field(name="🔔 แจ้งเตือนตั้งค่า (Week)", value="✅ เปิด" if settings["remind_setup"] else "❌ ปิด", inline=True)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        update_guild_settings(guild_id, **updates)
        await interaction.response.send_message(f"✅ อัปเดตการตั้งค่าเรียบร้อยแล้ว!", ephemeral=True)

    # ──────────────────────────────────────
    # 🔒 PRIVATE ROOM COMMAND
    # ──────────────────────────────────────

    @app_commands.command(name="private_chat", description="🔒 สร้างห้องแชทส่วนตัวสำหรับคุณและสมาชิกที่เลือก")
    @app_commands.describe(member="เลือกสมาชิกที่ต้องการแชทด้วย")
    async def private_chat(self, interaction: discord.Interaction, member: discord.Member):
        settings = get_guild_settings(interaction.guild_id)
        if not settings["private_room_enabled"]:
            await interaction.response.send_message("❌ ระบบนี้ยังไม่เปิดใช้งานในเซิร์ฟเวอร์นี้ (ติดต่อแอดมินให้ใช้ `/setup_server`)", ephemeral=True)
            return

        if member.id == interaction.user.id:
            await interaction.response.send_message("❌ คุณไม่สามารถแชทส่วนตัวกับตัวเองได้ (ใช้ `/ai_myroom` สิ!)", ephemeral=True)
            return

        if member.bot:
            await interaction.response.send_message("❌ ไม่สามารถแชทส่วนตัวกับบอทได้ด้วยคำสั่งนี้", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        guild = interaction.guild
        category_id = settings["private_room_category_id"]
        category = guild.get_channel(category_id) if category_id else None

        if category is None and category_id:
            # Category was deleted, reset setting
            update_guild_settings(guild.id, private_room_category_id=None)

        if category is None:
            category_name = "🔒 Private Chats"
            category = discord.utils.get(guild.categories, name=category_name)
            if not category:
                try:
                    category = await guild.create_category(category_name)
                except discord.Forbidden:
                    await interaction.followup.send("❌ บอทไม่มีสิทธิ์สร้าง Category (Manage Channels)")
                    return

        # Overwrites
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True)
        }

        channel_name = f"chat-{interaction.user.name}-{member.name}"
        channel_name = "".join(c for c in channel_name if c.isalnum() or c == "-").lower()

        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"🔒 ห้องแชทส่วนตัวระหว่าง {interaction.user.display_name} และ {member.display_name}"
            )
            
            await channel.send(f"🔒 {interaction.user.mention} และ {member.mention} ห้องแชทส่วนตัวของคุณพร้อมใช้งานแล้ว!")
            await interaction.followup.send(f"✅ สร้างห้องแชทสำเร็จ! เชิญที่ {channel.mention}")
        except discord.Forbidden:
            await interaction.followup.send("❌ บอทไม่มีสิทธิ์สร้างห้องแชท (Manage Channels)")
        except Exception as e:
            logger.error(f"Error creating private chat: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}")

    # ──────────────────────────────────────
    # 🌐 INTERCOM (CROSS-SERVER CHAT)
    # ──────────────────────────────────────

    @app_commands.command(name="intercom_setup", description="🌐 ตั้งค่าห้องนี้เป็นห้องคุยข้ามเซิร์ฟเวอร์ (Intercom)")
    @app_commands.default_permissions(manage_channels=True)
    async def intercom_setup(self, interaction: discord.Interaction):
        settings = get_guild_settings(interaction.guild_id)
        if not settings["cross_chat_enabled"]:
            await interaction.response.send_message("❌ ระบบคุยข้ามเซิร์ฟเวอร์ยังไม่เปิดใช้งาน (ใช้ `/setup_server` เพื่อเปิดก่อน)", ephemeral=True)
            return

        update_guild_settings(interaction.guild_id, intercom_channel_id=interaction.channel_id)
        await interaction.response.send_message(f"✅ ตั้งค่า {interaction.channel.mention} เป็นห้อง Intercom เรียบร้อย!", ephemeral=True)

    async def server_id_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        config = _load_config()
        choices = []
        for gid_str, data in config.items():
            if int(gid_str) == interaction.guild_id:
                continue
            if data.get("cross_chat_enabled"):
                guild = self.bot.get_guild(int(gid_str))
                name = guild.name if guild else f"Unknown ({gid_str})"
                if current.lower() in name.lower() or current in gid_str:
                    choices.append(app_commands.Choice(name=name, value=gid_str))
        return choices[:25]

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        settings = get_guild_settings(message.guild.id)
        if not settings["cross_chat_enabled"] or settings["intercom_channel_id"] != message.channel.id:
            return

        # Global Broadcast (Mode 1)
        config = _load_config()
        for gid_str, data in config.items():
            if int(gid_str) == message.guild.id:
                continue
            
            if data.get("cross_chat_enabled") and data.get("intercom_channel_id"):
                target_guild = self.bot.get_guild(int(gid_str))
                if target_guild:
                    target_channel = target_guild.get_channel(data["intercom_channel_id"])
                    if target_channel:
                        embed = discord.Embed(
                            description=message.content,
                            color=discord.Color.from_rgb(0, 150, 255),
                            timestamp=message.created_at
                        )
                        embed.set_author(name=f"{message.author.name} [@{message.guild.name} | GID: {message.guild.id} | UID: {message.author.id}]", icon_url=message.author.display_avatar.url)
                        
                        if message.attachments:
                            embed.set_image(url=message.attachments[0].url)
                        
                        try:
                            await target_channel.send(embed=embed)
                        except Exception:
                            pass

    @app_commands.command(name="intercom_private", description="🌐 ส่งข้อความ Intercom เฉพาะเซิร์ฟเวอร์ที่เลือก (Directed Mode)")
    @app_commands.describe(server_id="เลือกเซิร์ฟเวอร์เป้าหมาย", message="ข้อความที่ต้องการส่ง")
    @app_commands.autocomplete(server_id=server_id_autocomplete)
    async def intercom_private(self, interaction: discord.Interaction, server_id: str, message: str):
        settings = get_guild_settings(interaction.guild_id)
        if not settings["cross_chat_enabled"]:
            await interaction.response.send_message("❌ ระบบคุยข้ามเซิร์ฟเวอร์ยังไม่เปิดใช้งาน", ephemeral=True)
            return

        target_guild = None
        if server_id.isdigit():
            target_guild = self.bot.get_guild(int(server_id))
        if not target_guild:
            for guild in self.bot.guilds:
                if server_id.lower() in guild.name.lower():
                    target_guild = guild
                    break

        if not target_guild:
            await interaction.response.send_message("❌ บอทไม่ได้อยู่ในเซิร์ฟเวอร์ที่เลือก หรือระบุชื่อ/ID ผิด", ephemeral=True)
            return

        server_id = str(target_guild.id)

        config = _load_config()
        target_data = config.get(server_id, {})
        if not target_data.get("cross_chat_enabled") or not target_data.get("intercom_channel_id"):
            await interaction.response.send_message(f"❌ เซิร์ฟเวอร์ {target_guild.name} ไม่ได้เปิดระบบ Intercom หรือไม่มีห้องรับ", ephemeral=True)
            return

        target_channel = target_guild.get_channel(target_data["intercom_channel_id"])
        if not target_channel:
            await interaction.response.send_message("❌ ไม่พบห้อง Intercom ในเซิร์ฟเวอร์เป้าหมาย", ephemeral=True)
            return

        embed = discord.Embed(
            title="🔒 Private Intercom",
            description=message,
            color=discord.Color.purple()
        )
        embed.set_author(name=f"{interaction.user.name} [@{interaction.guild.name} | GID: {interaction.guild.id} | UID: {interaction.user.id}]", icon_url=interaction.user.display_avatar.url)
        
        await target_channel.send(embed=embed)
        await interaction.response.send_message(f"✅ ส่งข้อความไปยัง {target_guild.name} เรียบร้อย!", ephemeral=True)

    @app_commands.command(name="intercom_dm", description="🌐 ส่งข้อความ DM ข้ามเซิร์ฟเวอร์ (หาจากรายชื่อสมาชิกในเซิร์ฟเวอร์อื่น)")
    @app_commands.describe(server_id="เซิร์ฟเวอร์เป้าหมาย", user_id="สมาชิกเป้าหมาย (ID)", message="ข้อความ")
    @app_commands.autocomplete(server_id=server_id_autocomplete)
    async def intercom_dm(self, interaction: discord.Interaction, server_id: str, user_id: str, message: str):
        settings = get_guild_settings(interaction.guild_id)
        if not settings["cross_chat_enabled"]:
            await interaction.response.send_message("❌ ระบบข้ามเซิร์ฟเวอร์ปิดอยู่", ephemeral=True)
            return

        target_guild = None
        if server_id.isdigit():
            target_guild = self.bot.get_guild(int(server_id))
        if not target_guild:
            for guild in self.bot.guilds:
                if server_id.lower() in guild.name.lower():
                    target_guild = guild
                    break

        if not target_guild:
            await interaction.response.send_message("❌ ไม่พบเซิร์ฟเวอร์ที่ระบุ", ephemeral=True)
            return

        server_id = str(target_guild.id)

        config = _load_config()
        if not config.get(server_id, {}).get("cross_chat_enabled"):
            await interaction.response.send_message("❌ เซิร์ฟเวอร์เป้าหมายปิดระบบข้ามเซิร์ฟเวอร์อยู่", ephemeral=True)
            return

        try:
            target_member = target_guild.get_member(int(user_id)) or await target_guild.fetch_member(int(user_id))
        except discord.NotFound:
            await interaction.response.send_message("❌ ไม่พบสมาชิก User ID นี้ในเซิร์ฟเวอร์เป้าหมาย (Unknown User)", ephemeral=True)
            return
        except Exception as e:
            await interaction.response.send_message(f"❌ เกิดข้อผิดพลาดในการค้นหาผู้ใช้: {e}", ephemeral=True)
            return

        if not target_member:
            await interaction.response.send_message("❌ ไม่พบสมาชิกในเซิร์ฟเวอร์นั้น", ephemeral=True)
            return

        try:
            embed = discord.Embed(
                title="📧 Cross-Server DM",
                description=message,
                color=discord.Color.green()
            )
            embed.set_author(name=f"{interaction.user.name} [@{interaction.guild.name} | ID: {interaction.guild.id}]", icon_url=interaction.user.display_avatar.url)
            await target_member.send(embed=embed)
            await interaction.response.send_message(f"✅ ส่ง DM หา {target_member.name} สำเร็จ!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ ส่ง DM ไม่สำเร็จ: {e}", ephemeral=True)

    # ──────────────────────────────────────
    # 🔔 WEEKLY REMINDER (DM SERVER OWNERS)
    # ──────────────────────────────────────

    @tasks.loop(hours=24)
    async def reminder_task(self):
        # We run this every 24h, but check if a week has passed for each guild
        now = datetime.now()
        config = _load_config()
        updated = False

        for guild in self.bot.guilds:
            gid_str = str(guild.id)
            data = config.get(gid_str, {})
            
            # Check if set up at all or if opted out
            is_setup = data.get("intercom_channel_id") or data.get("private_room_enabled")
            remind_opt = data.get("remind_setup", True)
            last_remind = data.get("last_remind_time")

            if not is_setup and remind_opt:
                # If never reminded or last remind was > 7 days ago
                should_remind = False
                if not last_remind:
                    should_remind = True
                else:
                    last_dt = datetime.fromisoformat(last_remind)
                    if (now - last_dt).days >= 7:
                        should_remind = True

                if should_remind:
                    try:
                        owner = guild.owner or await guild.fetch_member(guild.owner_id)
                        if owner:
                            view = ReminderView(guild.id)
                            embed = discord.Embed(
                                title=f"👋 สวัสดีครับเจ้าของเซิร์ฟ {guild.name}!",
                                description=(
                                    "เห็นว่าคุณยังไม่ได้เปิดใช้งานฟีเจอร์เจ๋งๆ ของบอทในเซิร์ฟเวอร์นี้:\n\n"
                                    "✨ **ฟีเจอร์ที่แนะนำ:**\n"
                                    "1. **ระบบ Intercom:** คุยกับเซิร์ฟเวอร์อื่นได้ทั่วโลก! 🌐\n"
                                    "2. **ระบบ Private Chat:** สร้างห้องคุยลับเฉพาะคน 2 คน 🔒\n"
                                    "3. **AI Personal Rooms:** ห้องคุย AI ส่วนตัว 🤖\n\n"
                                    "คุณสามารถตั้งค่าได้ง่ายๆ โดยใช้คำสั่ง `/setup_server` ในเซิร์ฟเวอร์ของคุณครับ!"
                                ),
                                color=discord.Color.gold()
                            )
                            embed.set_footer(text="ข้อความเตือนรายสัปดาห์ (คุณสามารถกดปิดได้ด้านล่าง)")
                            await owner.send(embed=embed, view=view)
                            
                            if gid_str not in config: config[gid_str] = {}
                            config[gid_str]["last_remind_time"] = now.isoformat()
                            updated = True
                            logger.info(f"Sent weekly setup reminder to owner of {guild.name}")
                    except Exception as e:
                        logger.warning(f"Could not send reminder to owner of {guild.name}: {e}")

        if updated:
            _save_config(config)

    @reminder_task.before_loop
    async def before_reminder(self):
        await self.bot.wait_until_ready()

class ReminderView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="❌ ไม่ต้องส่งมาอีกแล้วสำหรับฟีเจอร์นี้", style=discord.ButtonStyle.danger)
    async def stop_reminder(self, interaction: discord.Interaction, button: discord.ui.Button):
        update_guild_settings(self.guild_id, remind_setup=False)
        await interaction.response.send_message("✅ รับทราบครับ! บอทจะไม่ส่งข้อความแจ้งเตือนตั้งค่าสำหรับเซิร์ฟเวอร์นี้อีก", ephemeral=True)
        self.stop()

async def setup(bot: commands.Bot):
    await bot.add_cog(ServerLink(bot))
