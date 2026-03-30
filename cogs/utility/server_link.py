import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import logging
import asyncio
from datetime import datetime, timedelta
import re
from urllib.parse import urlparse
from collections import defaultdict, deque
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# CONFIG PATH
# ─────────────────────────────────────────
_BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.normpath(os.path.join(_BASE, "..", "..", "data", "server_link_config.json"))
MESSAGE_MAP_PATH = os.path.normpath(os.path.join(_BASE, "..", "..", "data", "intercom_message_map.json"))
URL_PATTERN = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)
BLOCKED_WORDS = {
    "ควย", "เหี้ย", "สัส", "สัด", "fuck", "bitch", "nigger", "porn", "xxx"
}
DEFAULT_APPROVED_DOMAINS = [
    "discord.com",
    "discord.gg",
    "youtube.com",
    "youtu.be",
    "github.com",
    "roblox.com",
]

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
        "last_remind_time": None,
        "anti_spam_enabled": True,
        "content_filter_enabled": True,
        "link_filter_enabled": True,
        "approved_link_domains": DEFAULT_APPROVED_DOMAINS,
        "custom_blocked_words": [],
        "intercom_log_channel_id": None,
    }
    guild_data = config.get(str(guild_id), {})
    for k, v in defaults.items():
        if k not in guild_data:
            guild_data[k] = list(v) if isinstance(v, list) else v
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
            "last_remind_time": None,
            "anti_spam_enabled": True,
            "content_filter_enabled": True,
            "link_filter_enabled": True,
            "approved_link_domains": list(DEFAULT_APPROVED_DOMAINS),
            "custom_blocked_words": [],
            "intercom_log_channel_id": None,
        }
    config[gid_str].update(kwargs)
    _save_config(config)

def _load_message_map() -> dict:
    try:
        if os.path.exists(MESSAGE_MAP_PATH):
            with open(MESSAGE_MAP_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading intercom_message_map: {e}")
    return {}

def _save_message_map(data: dict):
    try:
        os.makedirs(os.path.dirname(MESSAGE_MAP_PATH), exist_ok=True)
        with open(MESSAGE_MAP_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving intercom_message_map: {e}")

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
        self._spam_buckets: dict[tuple[int, int], deque[datetime]] = defaultdict(deque)
        self._spam_cooldown_until: dict[tuple[int, int], datetime] = {}
        self.reminder_task.start()

    def cog_unload(self):
        self.reminder_task.cancel()

    def _extract_domains(self, text: str) -> list[str]:
        domains: list[str] = []
        for url in URL_PATTERN.findall(text or ""):
            try:
                parsed = urlparse(url)
                host = (parsed.hostname or "").lower()
                if host.startswith("www."):
                    host = host[4:]
                if host:
                    domains.append(host)
            except Exception:
                continue
        return domains

    def _blocked_words_for_guild(self, guild_id: int) -> set[str]:
        settings = get_guild_settings(guild_id)
        custom_words = settings.get("custom_blocked_words") or []
        return set(BLOCKED_WORDS) | {str(word).strip().lower() for word in custom_words if str(word).strip()}

    def _contains_blocked_words(self, guild_id: int, text: str) -> bool:
        lowered = (text or "").lower()
        return any(word in lowered for word in self._blocked_words_for_guild(guild_id))

    def _is_spam(self, guild_id: int, user_id: int) -> tuple[bool, str]:
        key = (guild_id, user_id)
        now = datetime.utcnow()

        cooldown_until = self._spam_cooldown_until.get(key)
        if cooldown_until and now < cooldown_until:
            seconds = int((cooldown_until - now).total_seconds()) + 1
            return True, f"⚠️ คุณส่งเร็วเกินไป กรุณารอ {seconds} วินาทีก่อนส่งอีกครั้ง"

        bucket = self._spam_buckets[key]
        while bucket and (now - bucket[0]).total_seconds() > 10:
            bucket.popleft()

        bucket.append(now)
        if len(bucket) > 4:
            self._spam_cooldown_until[key] = now + timedelta(seconds=20)
            bucket.clear()
            return True, "🚫 ตรวจพบสแปม: ส่งข้อความถี่เกินกำหนด (สูงสุด 4 ข้อความใน 10 วินาที)"
        return False, ""

    def _validate_intercom_message(self, guild_id: int, user_id: int, text: str) -> tuple[bool, str]:
        settings = get_guild_settings(guild_id)

        if settings.get("anti_spam_enabled", True):
            is_spam, reason = self._is_spam(guild_id, user_id)
            if is_spam:
                return False, reason

        if settings.get("content_filter_enabled", True) and self._contains_blocked_words(guild_id, text):
            return False, "🚫 ข้อความนี้มีคำที่ไม่เหมาะสมและถูกบล็อกโดยระบบความปลอดภัย"

        if settings.get("link_filter_enabled", True):
            domains = self._extract_domains(text)
            if domains:
                approved = set((settings.get("approved_link_domains") or []))
                unapproved = [domain for domain in domains if domain not in approved]
                if unapproved:
                    bad = ", ".join(sorted(set(unapproved))[:4])
                    return False, (
                        f"🔒 พบลิงก์ที่ยังไม่อนุมัติ: {bad}\n"
                        f"ให้แอดมินใช้ `/intercom_security action:approve` เพื่ออนุมัติโดเมนก่อน"
                    )

        return True, ""

    def _apply_intercom_meta(
        self,
        embed: discord.Embed,
        *,
        user: discord.abc.User,
        guild: discord.Guild,
        source_message_id: Optional[int] = None,
    ) -> discord.Embed:
        embed.set_author(
            name=f"{user.name} • UID: {user.id}",
            icon_url=user.display_avatar.url
        )
        guild_icon = guild.icon.url if guild.icon else None
        footer_text = f"GID: {guild.id}"
        if source_message_id:
            footer_text += f" | MID: {source_message_id}"
        embed.set_footer(
            text=footer_text,
            icon_url=guild_icon
        )
        return embed

    def _build_relay_embed(self, source_message: discord.Message) -> discord.Embed:
        embed = discord.Embed(
            description=source_message.content or "‎",
            color=discord.Color.from_rgb(0, 150, 255),
            timestamp=source_message.created_at
        )
        self._apply_intercom_meta(
            embed,
            user=source_message.author,
            guild=source_message.guild,
            source_message_id=source_message.id
        )
        if source_message.attachments:
            embed.set_image(url=source_message.attachments[0].url)
        return embed

    def _can_manage_intercom(self, interaction: discord.Interaction) -> bool:
        if self._is_bot_admin(interaction.user.id):
            return True
        if isinstance(interaction.user, discord.Member):
            return interaction.user.guild_permissions.manage_guild
        return False

    def _normalize_domain(self, raw: str) -> Optional[str]:
        text = (raw or "").strip().lower()
        if not text:
            return None
        if text.startswith("http://") or text.startswith("https://"):
            parsed = urlparse(text)
            host = (parsed.hostname or "").lower()
        else:
            host = text.split("/")[0].split(":")[0].lower()
        host = host.removeprefix("www.")
        if "." not in host or " " in host:
            return None
        return host

    def _build_security_embed(self, guild_id: int) -> discord.Embed:
        settings = get_guild_settings(guild_id)
        approved_domains = settings.get("approved_link_domains", [])
        domain_preview = ", ".join(approved_domains[:8]) if approved_domains else "ไม่มี"
        if len(approved_domains) > 8:
            domain_preview += f" ... (+{len(approved_domains) - 8})"

        guild = self.bot.get_guild(guild_id)
        log_channel_id = settings.get("intercom_log_channel_id")
        log_channel = guild.get_channel(log_channel_id) if guild and log_channel_id else None

        embed = discord.Embed(title="🛡️ Intercom Security Control Panel", color=discord.Color.blurple())
        embed.description = "กดปุ่มเพื่อเปิด/ปิดระบบ, ตั้ง Log, และจัดการโดเมนอนุมัติ"
        embed.add_field(name="กันสแปม", value="✅ เปิด" if settings.get("anti_spam_enabled", True) else "❌ ปิด", inline=True)
        embed.add_field(name="กรองคำไม่เหมาะสม", value="✅ เปิด" if settings.get("content_filter_enabled", True) else "❌ ปิด", inline=True)
        embed.add_field(name="กรองลิงก์", value="✅ เปิด" if settings.get("link_filter_enabled", True) else "❌ ปิด", inline=True)
        embed.add_field(name="โดเมนที่อนุมัติ", value=domain_preview, inline=False)
        custom_words = settings.get("custom_blocked_words") or []
        words_preview = ", ".join(custom_words[:8]) if custom_words else "ไม่มี"
        if len(custom_words) > 8:
            words_preview += f" ... (+{len(custom_words) - 8})"
        embed.add_field(name="คำไม่เหมาะสม (กำหนดเอง)", value=words_preview, inline=False)
        embed.add_field(name="ห้อง Log", value=(log_channel.mention if log_channel else "ยังไม่ได้ตั้ง"), inline=False)
        return embed

    def _is_bot_admin(self, user_id: int) -> bool:
        admin_cog = self.bot.get_cog("Admin")
        if admin_cog:
            if hasattr(admin_cog, "is_admin"):
                return bool(admin_cog.is_admin(user_id))
            if hasattr(admin_cog, "allowed_user_id"):
                return str(user_id) == str(getattr(admin_cog, "allowed_user_id"))
        return False

    async def _send_security_log(self, guild_id: int, title: str, description: str, color: discord.Color):
        settings = get_guild_settings(guild_id)
        log_channel_id = settings.get("intercom_log_channel_id") or settings.get("intercom_channel_id")
        if not log_channel_id:
            return

        channel = self.bot.get_channel(int(log_channel_id))
        if not channel:
            return

        embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.utcnow())
        try:
            await channel.send(embed=embed)
        except Exception:
            pass

    def _source_key(self, guild_id: int, channel_id: int, message_id: int) -> str:
        return f"{guild_id}:{channel_id}:{message_id}"

    def _parse_source_key(self, key: str) -> tuple[int, int, int]:
        gid, cid, mid = key.split(":")
        return int(gid), int(cid), int(mid)

    async def _delete_message_safely(self, channel_id: int, message_id: int) -> bool:
        try:
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.DMChannel)):
                return False
            msg = await channel.fetch_message(message_id)
            await msg.delete()
            return True
        except Exception:
            return False

    def _find_source_keys_by_any_message_id(self, message_id: int) -> list[str]:
        mapping = _load_message_map()
        matched: list[str] = []
        for source_key, relays in mapping.items():
            try:
                _, _, src_mid = self._parse_source_key(source_key)
            except Exception:
                continue
            if src_mid == message_id:
                matched.append(source_key)
                continue
            for relay in relays:
                if int(relay.get("message_id", 0)) == message_id:
                    matched.append(source_key)
                    break
        return matched

    def _parse_message_reference(self, raw: str) -> tuple[Optional[int], Optional[int], int]:
        value = raw.strip()
        pattern = r"^https?://(?:ptb\.|canary\.)?discord\.com/channels/(\d+|@me)/(\d+)/(\d+)$"
        match = re.match(pattern, value)
        if match:
            guild_raw, channel_raw, message_raw = match.groups()
            guild_id = None if guild_raw == "@me" else int(guild_raw)
            return guild_id, int(channel_raw), int(message_raw)

        if value.isdigit():
            return None, None, int(value)

        raise ValueError("invalid_reference")

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
            embed.add_field(name="🛡️ กันสแปม", value="✅ เปิด" if settings.get("anti_spam_enabled", True) else "❌ ปิด", inline=True)
            embed.add_field(name="🚫 กรองคำไม่เหมาะสม", value="✅ เปิด" if settings.get("content_filter_enabled", True) else "❌ ปิด", inline=True)
            embed.add_field(name="🔗 กรองลิงก์", value="✅ เปิด" if settings.get("link_filter_enabled", True) else "❌ ปิด", inline=True)
            log_channel = interaction.guild.get_channel(settings.get("intercom_log_channel_id")) if settings.get("intercom_log_channel_id") else None
            embed.add_field(name="🧾 ห้อง Log", value=(log_channel.mention if log_channel else "ยังไม่ได้ตั้ง"), inline=False)
            
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

    @app_commands.command(name="intercom_security", description="🛡️ จัดการระบบความปลอดภัย Intercom แบบรวม (สแปม/คำไม่เหมาะสม/ลิงก์/log)")
    @app_commands.describe(
        action="เลือกการทำงาน",
        value="ใช้กับ approve/unapprove เช่น โดเมนหรือ URL",
        enabled="ใช้กับ toggle_spam/toggle_content/toggle_link",
        log_channel="ตั้งห้อง log สำหรับความปลอดภัย Intercom"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="เปิดแผงควบคุมแบบปุ่มกด", value="panel"),
        app_commands.Choice(name="ดูสถานะความปลอดภัย", value="status"),
        app_commands.Choice(name="เปิด/ปิด กันสแปม", value="toggle_spam"),
        app_commands.Choice(name="เปิด/ปิด กรองคำไม่เหมาะสม", value="toggle_content"),
        app_commands.Choice(name="เปิด/ปิด กรองลิงก์", value="toggle_link"),
        app_commands.Choice(name="อนุมัติโดเมนลิงก์", value="approve"),
        app_commands.Choice(name="ถอนโดเมนลิงก์", value="unapprove"),
        app_commands.Choice(name="ดูรายการโดเมนที่อนุมัติ", value="list"),
        app_commands.Choice(name="เพิ่มคำไม่เหมาะสม", value="add_badword"),
        app_commands.Choice(name="ลบคำไม่เหมาะสม", value="remove_badword"),
        app_commands.Choice(name="ดูรายการคำไม่เหมาะสม", value="list_badwords"),
        app_commands.Choice(name="ตั้งห้อง Log", value="set_log"),
    ])
    @app_commands.default_permissions(manage_guild=True)
    async def intercom_security(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        value: Optional[str] = None,
        enabled: Optional[bool] = None,
        log_channel: Optional[discord.TextChannel] = None,
    ):
        guild_id = interaction.guild_id
        settings = get_guild_settings(guild_id)
        action_value = action.value

        if action_value == "panel":
            embed = self._build_security_embed(guild_id)
            view = IntercomSecurityView(self, guild_id, owner_user_id=interaction.user.id)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return

        if action_value == "toggle_spam":
            if enabled is None:
                await interaction.response.send_message("❌ กรุณาระบุค่า `enabled`", ephemeral=True)
                return
            update_guild_settings(guild_id, anti_spam_enabled=enabled)
        elif action_value == "toggle_content":
            if enabled is None:
                await interaction.response.send_message("❌ กรุณาระบุค่า `enabled`", ephemeral=True)
                return
            update_guild_settings(guild_id, content_filter_enabled=enabled)
        elif action_value == "toggle_link":
            if enabled is None:
                await interaction.response.send_message("❌ กรุณาระบุค่า `enabled`", ephemeral=True)
                return
            update_guild_settings(guild_id, link_filter_enabled=enabled)
        elif action_value == "approve":
            if not value:
                await interaction.response.send_message("❌ กรุณาระบุโดเมนหรือ URL ใน `value`", ephemeral=True)
                return
            host = self._normalize_domain(value)
            if not host:
                await interaction.response.send_message("❌ รูปแบบโดเมนไม่ถูกต้อง", ephemeral=True)
                return
            approved = settings.get("approved_link_domains", [])
            if host not in approved:
                approved.append(host)
                approved = sorted(set(approved))
                update_guild_settings(guild_id, approved_link_domains=approved)
                await self._send_security_log(
                    guild_id,
                    "✅ Intercom Link Approved",
                    f"อนุมัติโดเมน `{host}` โดย {interaction.user.mention}",
                    discord.Color.green()
                )
        elif action_value == "unapprove":
            if not value:
                await interaction.response.send_message("❌ กรุณาระบุโดเมนใน `value`", ephemeral=True)
                return
            host = self._normalize_domain(value)
            if not host:
                await interaction.response.send_message("❌ รูปแบบโดเมนไม่ถูกต้อง", ephemeral=True)
                return
            approved = settings.get("approved_link_domains", [])
            approved = [d for d in approved if d != host]
            update_guild_settings(guild_id, approved_link_domains=approved)
            await self._send_security_log(
                guild_id,
                "🗑️ Intercom Link Removed",
                f"ถอนโดเมน `{host}` โดย {interaction.user.mention}",
                discord.Color.orange()
            )
        elif action_value == "set_log":
            if not log_channel:
                await interaction.response.send_message("❌ กรุณาเลือก `log_channel`", ephemeral=True)
                return
            update_guild_settings(guild_id, intercom_log_channel_id=log_channel.id)
            await interaction.response.send_message(f"✅ ตั้งห้อง Log เป็น {log_channel.mention} แล้ว", ephemeral=True)
            return
        elif action_value == "add_badword":
            if not value:
                await interaction.response.send_message("❌ กรุณาระบุคำใน `value`", ephemeral=True)
                return
            bad_word = value.strip().lower()
            settings_now = get_guild_settings(guild_id)
            custom_words = settings_now.get("custom_blocked_words") or []
            if bad_word not in custom_words:
                custom_words.append(bad_word)
                custom_words = sorted(set(custom_words))
                update_guild_settings(guild_id, custom_blocked_words=custom_words)
            await interaction.response.send_message(f"✅ เพิ่มคำไม่เหมาะสม `{bad_word}` แล้ว", ephemeral=True)
            return
        elif action_value == "remove_badword":
            if not value:
                await interaction.response.send_message("❌ กรุณาระบุคำใน `value`", ephemeral=True)
                return
            bad_word = value.strip().lower()
            settings_now = get_guild_settings(guild_id)
            custom_words = [word for word in (settings_now.get("custom_blocked_words") or []) if word != bad_word]
            update_guild_settings(guild_id, custom_blocked_words=custom_words)
            await interaction.response.send_message(f"✅ ลบคำ `{bad_word}` ออกจากรายการแล้ว", ephemeral=True)
            return
        elif action_value == "list_badwords":
            settings_now = get_guild_settings(guild_id)
            custom_words = settings_now.get("custom_blocked_words") or []
            if not custom_words:
                await interaction.response.send_message("ℹ️ ยังไม่มีคำไม่เหมาะสมแบบกำหนดเอง", ephemeral=True)
                return
            lines = [f"{index + 1}. `{word}`" for index, word in enumerate(custom_words[:40])]
            if len(custom_words) > 40:
                lines.append(f"... และอีก {len(custom_words) - 40} คำ")
            await interaction.response.send_message("🚫 คำไม่เหมาะสม (กำหนดเอง):\n" + "\n".join(lines), ephemeral=True)
            return
        elif action_value == "list":
            approved = settings.get("approved_link_domains", [])
            if not approved:
                await interaction.response.send_message("ℹ️ ยังไม่มีโดเมนที่อนุมัติ", ephemeral=True)
                return
            lines = [f"{index + 1}. `{domain}`" for index, domain in enumerate(approved[:40])]
            if len(approved) > 40:
                lines.append(f"... และอีก {len(approved) - 40} โดเมน")
            await interaction.response.send_message("📃 โดเมนที่อนุมัติ:\n" + "\n".join(lines), ephemeral=True)
            return

        embed = self._build_security_embed(guild_id)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="intercom_panel", description="🎛️ เปิดแผงควบคุม Intercom Security แบบปุ่มกด")
    async def intercom_panel(self, interaction: discord.Interaction):
        embed = self._build_security_embed(interaction.guild_id)
        view = IntercomSecurityView(self, interaction.guild_id, owner_user_id=interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

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

        is_ok, reason = self._validate_intercom_message(message.guild.id, message.author.id, message.content)
        if not is_ok:
            try:
                await message.delete()
            except Exception:
                pass
            try:
                notice = await message.channel.send(f"{message.author.mention} {reason}")
                await asyncio.sleep(8)
                await notice.delete()
            except Exception:
                pass
            await self._send_security_log(
                message.guild.id,
                "🚫 Intercom Message Blocked",
                f"ผู้ใช้: {message.author.mention}\nเหตุผล: {reason}\nข้อความ: {message.content[:300]}",
                discord.Color.orange()
            )
            return

        # Global Broadcast (Mode 1)
        config = _load_config()
        sent_records: list[dict[str, int]] = []
        for gid_str, data in config.items():
            if int(gid_str) == message.guild.id:
                continue
            
            if data.get("cross_chat_enabled") and data.get("intercom_channel_id"):
                target_guild = self.bot.get_guild(int(gid_str))
                if target_guild:
                    target_channel = target_guild.get_channel(data["intercom_channel_id"])
                    if target_channel:
                        embed = self._build_relay_embed(message)
                        
                        try:
                            sent = await target_channel.send(embed=embed)
                            sent_records.append({
                                "guild_id": int(gid_str),
                                "channel_id": target_channel.id,
                                "message_id": sent.id
                            })
                        except Exception:
                            pass

        if sent_records:
            mapping = _load_message_map()
            source_key = self._source_key(message.guild.id, message.channel.id, message.id)
            mapping[source_key] = sent_records
            _save_message_map(mapping)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.author.bot or not after.guild:
            return
        if before.content == after.content and len(before.attachments) == len(after.attachments):
            return

        settings = get_guild_settings(after.guild.id)
        if not settings["cross_chat_enabled"] or settings["intercom_channel_id"] != after.channel.id:
            return

        mapping = _load_message_map()
        source_key = self._source_key(after.guild.id, after.channel.id, after.id)
        relays = mapping.get(source_key)
        if not relays:
            return

        is_ok, reason = self._validate_intercom_message(after.guild.id, after.author.id, after.content)
        if not is_ok:
            try:
                await after.delete()
            except Exception:
                pass
            await self._send_security_log(
                after.guild.id,
                "🚫 Intercom Edit Blocked",
                f"ผู้ใช้: {after.author.mention}\nเหตุผล: {reason}\nข้อความ: {after.content[:300]}",
                discord.Color.orange()
            )
            return

        embed = self._build_relay_embed(after)
        edited_count = 0
        for relay in relays:
            target_channel = self.bot.get_channel(int(relay.get("channel_id", 0)))
            target_message_id = int(relay.get("message_id", 0))
            if not target_channel or not target_message_id:
                continue
            try:
                target_msg = await target_channel.fetch_message(target_message_id)
                await target_msg.edit(embed=embed)
                edited_count += 1
            except Exception:
                continue

        if edited_count > 0:
            await self._send_security_log(
                after.guild.id,
                "✏️ Intercom Message Updated",
                f"ผู้ใช้: {after.author.mention}\nMID ต้นทาง: `{after.id}`\nอัปเดตปลายทาง: `{edited_count}` ข้อความ",
                discord.Color.blue()
            )

    @app_commands.command(name="intercom_private", description="🌐 ส่งข้อความ Intercom เฉพาะเซิร์ฟเวอร์ที่เลือก (Directed Mode)")
    @app_commands.describe(server_id="เลือกเซิร์ฟเวอร์เป้าหมาย", message="ข้อความที่ต้องการส่ง")
    @app_commands.autocomplete(server_id=server_id_autocomplete)
    async def intercom_private(self, interaction: discord.Interaction, server_id: str, message: str):
        settings = get_guild_settings(interaction.guild_id)
        if not settings["cross_chat_enabled"]:
            await interaction.response.send_message("❌ ระบบคุยข้ามเซิร์ฟเวอร์ยังไม่เปิดใช้งาน", ephemeral=True)
            return

        is_ok, reason = self._validate_intercom_message(interaction.guild_id, interaction.user.id, message)
        if not is_ok:
            await interaction.response.send_message(reason, ephemeral=True)
            await self._send_security_log(
                interaction.guild_id,
                "🚫 Intercom Private Blocked",
                f"ผู้ใช้: {interaction.user.mention}\nเหตุผล: {reason}\nข้อความ: {message[:300]}",
                discord.Color.orange()
            )
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
        self._apply_intercom_meta(embed, user=interaction.user, guild=interaction.guild)
        
        await target_channel.send(embed=embed)
        await self._send_security_log(
            interaction.guild_id,
            "📨 Intercom Private Sent",
            f"จาก {interaction.user.mention} ไปเซิร์ฟ `{target_guild.id}` ({target_guild.name})",
            discord.Color.green()
        )
        await interaction.response.send_message(f"✅ ส่งข้อความไปยัง {target_guild.name} เรียบร้อย!", ephemeral=True)

    @app_commands.command(name="intercom_dm", description="🌐 ส่งข้อความ DM ข้ามเซิร์ฟเวอร์ (หาจากรายชื่อสมาชิกในเซิร์ฟเวอร์อื่น)")
    @app_commands.describe(server_id="เซิร์ฟเวอร์เป้าหมาย", user_id="สมาชิกเป้าหมาย (ID)", message="ข้อความ")
    @app_commands.autocomplete(server_id=server_id_autocomplete)
    async def intercom_dm(self, interaction: discord.Interaction, server_id: str, user_id: str, message: str):
        settings = get_guild_settings(interaction.guild_id)
        if not settings["cross_chat_enabled"]:
            await interaction.response.send_message("❌ ระบบข้ามเซิร์ฟเวอร์ปิดอยู่", ephemeral=True)
            return

        is_ok, reason = self._validate_intercom_message(interaction.guild_id, interaction.user.id, message)
        if not is_ok:
            await interaction.response.send_message(reason, ephemeral=True)
            await self._send_security_log(
                interaction.guild_id,
                "🚫 Intercom DM Blocked",
                f"ผู้ใช้: {interaction.user.mention}\nเหตุผล: {reason}\nข้อความ: {message[:300]}",
                discord.Color.orange()
            )
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
            self._apply_intercom_meta(embed, user=interaction.user, guild=interaction.guild)
            await target_member.send(embed=embed)
            await self._send_security_log(
                interaction.guild_id,
                "📧 Intercom DM Sent",
                f"จาก {interaction.user.mention} ไปหา `{target_member.id}` ในเซิร์ฟ `{target_guild.id}`",
                discord.Color.green()
            )
            await interaction.response.send_message(f"✅ ส่ง DM หา {target_member.name} สำเร็จ!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ ส่ง DM ไม่สำเร็จ: {e}", ephemeral=True)

    @app_commands.command(name="intercom_purge", description="🧹 ลบข้อความไม่เหมาะสมจากต้นทางและข้อความที่กระจายไปแล้ว (Bot Admin)")
    @app_commands.describe(
        link_or_id="ลิงก์ข้อความ Discord หรือ Message ID",
        channel="ช่องของข้อความ (ใช้เมื่อใส่แค่ Message ID)"
    )
    async def intercom_purge(
        self,
        interaction: discord.Interaction,
        link_or_id: str,
        channel: Optional[discord.TextChannel] = None
    ):
        if not self._is_bot_admin(interaction.user.id):
            await interaction.response.send_message("❌ คำสั่งนี้ใช้ได้เฉพาะแอดมินบอท", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            _, ref_channel_id, target_message_id = self._parse_message_reference(link_or_id)
        except ValueError:
            await interaction.followup.send("❌ รูปแบบไม่ถูกต้อง กรุณาใส่ลิงก์ข้อความหรือ Message ID")
            return

        source_keys = self._find_source_keys_by_any_message_id(target_message_id)
        if not source_keys:
            # fallback: ถ้าเป็นข้อความใหม่ที่ยังไม่เจอใน map ลองผูกด้วย channel ที่ระบุ
            if ref_channel_id:
                target_channel_id = ref_channel_id
            elif channel:
                target_channel_id = channel.id
            elif interaction.channel and isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
                target_channel_id = interaction.channel.id
            else:
                await interaction.followup.send("❌ ไม่พบ mapping ของข้อความนี้ และไม่สามารถระบุช่องได้")
                return

            fallback_key = self._source_key(interaction.guild_id, target_channel_id, target_message_id)
            source_keys = [fallback_key]

        mapping = _load_message_map()
        deleted_total = 0
        failed_total = 0
        touched_sources = 0

        for source_key in set(source_keys):
            touched_sources += 1
            try:
                source_gid, source_cid, source_mid = self._parse_source_key(source_key)
            except Exception:
                continue

            if await self._delete_message_safely(source_cid, source_mid):
                deleted_total += 1
            else:
                failed_total += 1

            relays = mapping.get(source_key, [])
            for relay in relays:
                relay_cid = int(relay.get("channel_id", 0))
                relay_mid = int(relay.get("message_id", 0))
                if relay_cid and relay_mid:
                    if await self._delete_message_safely(relay_cid, relay_mid):
                        deleted_total += 1
                    else:
                        failed_total += 1

            if source_key in mapping:
                del mapping[source_key]

        _save_message_map(mapping)

        await self._send_security_log(
            interaction.guild_id,
            "🧹 Intercom Purge Executed",
            (
                f"โดย: {interaction.user.mention}\n"
                f"Sources: {touched_sources}\n"
                f"ลบสำเร็จ: {deleted_total}\n"
                f"ลบไม่สำเร็จ: {failed_total}\n"
                f"Ref: `{target_message_id}`"
            ),
            discord.Color.red()
        )

        await interaction.followup.send(
            f"✅ Purge เสร็จแล้ว | ลบสำเร็จ: `{deleted_total}` | ลบไม่สำเร็จ: `{failed_total}`"
        )

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


class DomainInputModal(discord.ui.Modal):
    def __init__(self, cog: ServerLink, guild_id: int, mode: str):
        title = "อนุมัติโดเมน" if mode == "approve" else "ถอนโดเมน"
        super().__init__(title=title)
        self.cog = cog
        self.guild_id = guild_id
        self.mode = mode
        self.domain_input = discord.ui.TextInput(
            label="โดเมนหรือ URL",
            placeholder="เช่น https://youtube.com หรือ discord.com",
            required=True,
            max_length=200
        )
        self.add_item(self.domain_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not self.cog._can_manage_intercom(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์จัดการ Control Panel นี้", ephemeral=True)
            return

        host = self.cog._normalize_domain(self.domain_input.value)
        if not host:
            await interaction.response.send_message("❌ รูปแบบโดเมนไม่ถูกต้อง", ephemeral=True)
            return

        settings = get_guild_settings(self.guild_id)
        approved = settings.get("approved_link_domains", [])

        if self.mode == "approve":
            if host not in approved:
                approved.append(host)
                approved = sorted(set(approved))
                update_guild_settings(self.guild_id, approved_link_domains=approved)
            await self.cog._send_security_log(
                self.guild_id,
                "✅ Intercom Link Approved",
                f"อนุมัติโดเมน `{host}` โดย {interaction.user.mention}",
                discord.Color.green()
            )
            await interaction.response.send_message(f"✅ อนุมัติโดเมน `{host}` แล้ว", ephemeral=True)
            return

        approved = [d for d in approved if d != host]
        update_guild_settings(self.guild_id, approved_link_domains=approved)
        await self.cog._send_security_log(
            self.guild_id,
            "🗑️ Intercom Link Removed",
            f"ถอนโดเมน `{host}` โดย {interaction.user.mention}",
            discord.Color.orange()
        )
        await interaction.response.send_message(f"✅ ถอนโดเมน `{host}` แล้ว", ephemeral=True)


class BadWordInputModal(discord.ui.Modal):
    def __init__(self, cog: ServerLink, guild_id: int):
        super().__init__(title="เพิ่มคำไม่เหมาะสม")
        self.cog = cog
        self.guild_id = guild_id
        self.word_input = discord.ui.TextInput(
            label="คำที่ต้องการบล็อก",
            placeholder="พิมพ์คำที่ต้องการเพิ่ม",
            required=True,
            max_length=100
        )
        self.add_item(self.word_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not self.cog._can_manage_intercom(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์จัดการ Control Panel นี้", ephemeral=True)
            return

        bad_word = self.word_input.value.strip().lower()
        if not bad_word:
            await interaction.response.send_message("❌ กรุณากรอกคำที่ต้องการเพิ่ม", ephemeral=True)
            return

        settings = get_guild_settings(self.guild_id)
        custom_words = settings.get("custom_blocked_words") or []
        if bad_word not in custom_words:
            custom_words.append(bad_word)
            custom_words = sorted(set(custom_words))
            update_guild_settings(self.guild_id, custom_blocked_words=custom_words)
        await interaction.response.send_message(f"✅ เพิ่มคำไม่เหมาะสม `{bad_word}` แล้ว", ephemeral=True)


class ConfirmRemoveView(discord.ui.View):
    def __init__(self, cog: ServerLink, guild_id: int, kind: str, target_value: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.kind = kind
        self.target_value = target_value

    @discord.ui.button(label="ยืนยันลบ", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog._can_manage_intercom(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์จัดการ Control Panel นี้", ephemeral=True)
            return

        settings = get_guild_settings(self.guild_id)
        if self.kind == "domain":
            approved = [d for d in settings.get("approved_link_domains", []) if d != self.target_value]
            update_guild_settings(self.guild_id, approved_link_domains=approved)
            await self.cog._send_security_log(
                self.guild_id,
                "🗑️ Intercom Link Removed",
                f"ถอนโดเมน `{self.target_value}` โดย {interaction.user.mention}",
                discord.Color.orange()
            )
            await interaction.response.edit_message(content=f"✅ ถอนโดเมน `{self.target_value}` แล้ว", view=None)
            return

        custom_words = [w for w in settings.get("custom_blocked_words", []) if w != self.target_value]
        update_guild_settings(self.guild_id, custom_blocked_words=custom_words)
        await interaction.response.edit_message(content=f"✅ ลบคำไม่เหมาะสม `{self.target_value}` แล้ว", view=None)

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="ยกเลิกการลบแล้ว", view=None)


class IntercomSecurityView(discord.ui.View):
    def __init__(self, cog: ServerLink, guild_id: int, owner_user_id: int):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id
        self.owner_user_id = owner_user_id
        self._add_domain_remove_select()
        self._add_badword_remove_select()

    def _add_domain_remove_select(self):
        settings = get_guild_settings(self.guild_id)
        approved = settings.get("approved_link_domains", [])
        if not approved:
            return
        options = [discord.SelectOption(label=domain, value=domain) for domain in approved[:25]]
        select = discord.ui.Select(
            placeholder="เลือกโดเมนที่ต้องการถอน",
            min_values=1,
            max_values=1,
            options=options,
            row=3
        )

        async def _on_select(interaction: discord.Interaction):
            if not self.cog._can_manage_intercom(interaction):
                await interaction.response.send_message("❌ คุณไม่มีสิทธิ์จัดการ Control Panel นี้", ephemeral=True)
                return
            domain = select.values[0]
            await interaction.response.send_message(
                f"⚠️ ยืนยันการถอนโดเมน `{domain}` ?",
                ephemeral=True,
                view=ConfirmRemoveView(self.cog, self.guild_id, "domain", domain)
            )

        select.callback = _on_select
        self.add_item(select)

    def _add_badword_remove_select(self):
        settings = get_guild_settings(self.guild_id)
        words = settings.get("custom_blocked_words", [])
        if not words:
            return
        options = [discord.SelectOption(label=word, value=word) for word in words[:25]]
        select = discord.ui.Select(
            placeholder="เลือกคำไม่เหมาะสมที่ต้องการลบ",
            min_values=1,
            max_values=1,
            options=options,
            row=4
        )

        async def _on_select(interaction: discord.Interaction):
            if not self.cog._can_manage_intercom(interaction):
                await interaction.response.send_message("❌ คุณไม่มีสิทธิ์จัดการ Control Panel นี้", ephemeral=True)
                return
            word = select.values[0]
            await interaction.response.send_message(
                f"⚠️ ยืนยันการลบคำ `{word}` ?",
                ephemeral=True,
                view=ConfirmRemoveView(self.cog, self.guild_id, "badword", word)
            )

        select.callback = _on_select
        self.add_item(select)

    async def _refresh(self, interaction: discord.Interaction, note: Optional[str] = None):
        embed = self.cog._build_security_embed(self.guild_id)
        if note:
            embed.description = f"{embed.description}\n\n{note}"
        await interaction.response.edit_message(embed=embed, view=IntercomSecurityView(self.cog, self.guild_id, self.owner_user_id))

    @discord.ui.button(label="Toggle Spam", style=discord.ButtonStyle.blurple, row=0)
    async def toggle_spam(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog._can_manage_intercom(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์จัดการ Control Panel นี้", ephemeral=True)
            return
        settings = get_guild_settings(self.guild_id)
        new_state = not settings.get("anti_spam_enabled", True)
        update_guild_settings(self.guild_id, anti_spam_enabled=new_state)
        await self._refresh(interaction, f"🛡️ กันสแปม: {'เปิด' if new_state else 'ปิด'}")

    @discord.ui.button(label="Toggle Content", style=discord.ButtonStyle.blurple, row=0)
    async def toggle_content(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog._can_manage_intercom(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์จัดการ Control Panel นี้", ephemeral=True)
            return
        settings = get_guild_settings(self.guild_id)
        new_state = not settings.get("content_filter_enabled", True)
        update_guild_settings(self.guild_id, content_filter_enabled=new_state)
        await self._refresh(interaction, f"🚫 กรองคำไม่เหมาะสม: {'เปิด' if new_state else 'ปิด'}")

    @discord.ui.button(label="Toggle Link", style=discord.ButtonStyle.blurple, row=0)
    async def toggle_link(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog._can_manage_intercom(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์จัดการ Control Panel นี้", ephemeral=True)
            return
        settings = get_guild_settings(self.guild_id)
        new_state = not settings.get("link_filter_enabled", True)
        update_guild_settings(self.guild_id, link_filter_enabled=new_state)
        await self._refresh(interaction, f"🔗 กรองลิงก์: {'เปิด' if new_state else 'ปิด'}")

    @discord.ui.button(label="Use This Channel as Log", style=discord.ButtonStyle.green, row=1)
    async def set_log_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog._can_manage_intercom(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์จัดการ Control Panel นี้", ephemeral=True)
            return
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("❌ ช่องนี้ไม่รองรับการตั้งเป็น Log", ephemeral=True)
            return
        update_guild_settings(self.guild_id, intercom_log_channel_id=interaction.channel.id)
        await self._refresh(interaction, f"🧾 ตั้งห้อง Log เป็น {interaction.channel.mention} แล้ว")

    @discord.ui.button(label="Approve Domain", style=discord.ButtonStyle.green, row=1)
    async def approve_domain(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog._can_manage_intercom(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์จัดการ Control Panel นี้", ephemeral=True)
            return
        await interaction.response.send_modal(DomainInputModal(self.cog, self.guild_id, "approve"))

    @discord.ui.button(label="Unapprove Domain", style=discord.ButtonStyle.red, row=1)
    async def unapprove_domain(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog._can_manage_intercom(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์จัดการ Control Panel นี้", ephemeral=True)
            return
        await interaction.response.send_modal(DomainInputModal(self.cog, self.guild_id, "unapprove"))

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.gray, row=2)
    async def refresh_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog._can_manage_intercom(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์จัดการ Control Panel นี้", ephemeral=True)
            return
        await self._refresh(interaction, "🔄 รีเฟรชข้อมูลแล้ว")

    @discord.ui.button(label="Add Bad Word", style=discord.ButtonStyle.red, row=2)
    async def add_bad_word(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog._can_manage_intercom(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์จัดการ Control Panel นี้", ephemeral=True)
            return
        await interaction.response.send_modal(BadWordInputModal(self.cog, self.guild_id))

async def setup(bot: commands.Bot):
    await bot.add_cog(ServerLink(bot))
