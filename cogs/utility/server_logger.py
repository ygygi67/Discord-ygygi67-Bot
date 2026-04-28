import discord
from discord.ext import commands
import logging
from datetime import datetime, timezone
from collections import defaultdict
import asyncio
import time

logger = logging.getLogger('discord_bot')


# ─────────────────────────────────────────────
#  Simple in-memory rate limiter
#  ป้องกัน Log Spam เช่น on_message ถูกยิงถี่เกิน
# ─────────────────────────────────────────────
class RateLimiter:
    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self._calls: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        timestamps = self._calls[key]
        # ลบ timestamp เก่าออก
        self._calls[key] = [t for t in timestamps if now - t < self.period]
        if len(self._calls[key]) < self.max_calls:
            self._calls[key].append(now)
            return True
        return False


# ─────────────────────────────────────────────
#  Helper: แปลง Permission ต่างกันเป็น text
# ─────────────────────────────────────────────
def diff_permissions(before: discord.Permissions, after: discord.Permissions) -> tuple[list[str], list[str]]:
    """คืนค่า (granted, revoked) permission names"""
    granted, revoked = [], []
    for perm, value in after:
        before_val = getattr(before, perm)
        if value and not before_val:
            granted.append(perm.replace("_", " ").title())
        elif not value and before_val:
            revoked.append(perm.replace("_", " ").title())
    return granted, revoked


class ServerLogger(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log_channel_id: int = 1467898137459949742
        self.invites: dict[int, dict[str, int]] = {}  # guild_id → {code: uses}
        # Rate limiter: แต่ละ (event_type, entity_id) ได้สูงสุด 5 ครั้ง / 10 วินาที
        self._rate_limiter = RateLimiter(max_calls=5, period=10.0)
        
        self.log_queue = []
        self._flush_task = self.bot.loop.create_task(self._log_flusher())
        logger.info(f"ServerLogger initialized | log channel: {self.log_channel_id}")

    async def cog_unload(self):
        if hasattr(self, '_flush_task') and self._flush_task:
            self._flush_task.cancel()

    async def _log_flusher(self):
        """ส่ง log จากคิวทีละชุดเพื่อหลีกเลี่ยง Rate limit"""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                if self.log_queue:
                    channel = self.bot.get_channel(self.log_channel_id) or await self._fetch_channel()
                    if channel:
                        # Discord ให้ส่งได้สูงสุด 10 embed ต่อ 1 ข้อความ
                        embeds_to_send = self.log_queue[:10]
                        self.log_queue = self.log_queue[10:]
                        try:
                            await channel.send(embeds=embeds_to_send)
                        except discord.HTTPException as e:
                            # ถ้าโดน Rate limit ให้พักและเอาข้อมูลกลับไปคิว
                            if e.status == 429:
                                self.log_queue = embeds_to_send + self.log_queue
                                retry_after = getattr(e, "retry_after", 5.0)
                                await asyncio.sleep(retry_after + 1.0)
                            else:
                                logger.error(f"HTTPException sending log queue: {e}")
                        except discord.Forbidden:
                            logger.error(f"Missing permission to send to log channel {self.log_channel_id}")
            except Exception as e:
                logger.error(f"Error in log flusher: {e}")
            
            await asyncio.sleep(2.0)

    # ──────────────────────────────────────────
    #  Core helper
    # ──────────────────────────────────────────

    async def send_log(self, embed: discord.Embed, guild: discord.Guild | None = None) -> None:
        """นำ embed เข้า Queue เพื่อส่งไปยัง log channel ที่กำหนด"""
        if self.bot.is_closed():
            return

        # ใส่ footer เซิร์ฟเวอร์
        if guild:
            existing_footer = embed.footer.text or ""
            server_info = f"Server: {guild.name} (ID: {guild.id})"
            new_footer = f"{existing_footer} | {server_info}" if existing_footer else server_info
            embed.set_footer(text=new_footer)
        elif not embed.footer.text:
            embed.set_footer(text="System Log")

        self.log_queue.append(embed)

    async def _fetch_channel(self) -> discord.TextChannel | None:
        try:
            return await self.bot.fetch_channel(self.log_channel_id)  # type: ignore
        except Exception:
            return None

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _rl(self, event: str, entity_id: int) -> bool:
        """True = อนุญาตให้ log ได้"""
        return self._rate_limiter.is_allowed(f"{event}:{entity_id}")

    async def _get_audit_entry(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
        within_seconds: float = 10.0,
        limit: int = 5,
    ) -> discord.AuditLogEntry | None:
        """ดึง audit log entry ล่าสุดที่ตรงเงื่อนไข"""
        try:
            async for entry in guild.audit_logs(limit=limit, action=action):
                age = (self._now() - entry.created_at).total_seconds()
                if getattr(entry.target, "id", None) == target_id and age < within_seconds:
                    return entry
        except (discord.Forbidden, discord.HTTPException):
            pass
        except Exception as e:
            # ป้องกัน event handler ล่มในช่วง reconnect/shutdown (เช่น Connector is closed)
            logger.warning(f"[ServerLogger] audit log fetch skipped ({action}): {e}")
        return None

    def _add_field(self, embed: discord.Embed, name: str, value: str, inline: bool = False) -> None:
        """Add a field to embed safely, truncating value if it exceeds 1024 chars."""
        # ป้องกันค่าว่างเปล่า
        safe_value = str(value or "_(ว่าง)_").strip()
        if not safe_value:
            safe_value = "_(ระบุไม่ได้)_"

        # ตัดให้เหลือ 1024 ตามกติกา Discord (ตัดเหลือ 1021 เพื่อรวม ...)
        if len(safe_value) > 1024:
            safe_value = safe_value[:1020] + "..."
            
        embed.add_field(name=name, value=safe_value, inline=inline)


    # ──────────────────────────────────────────
    #  Invite cache
    # ──────────────────────────────────────────

    async def _cache_invites(self, guild: discord.Guild) -> None:
        try:
            self.invites[guild.id] = {inv.code: inv.uses for inv in await guild.invites()}
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            await self._cache_invites(guild)
        logger.info("Invite tracking initialized for all guilds.")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self._cache_invites(guild)

    # ──────────────────────────────────────────
    #  Member events
    # ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        embed = discord.Embed(
            title="📥 สมาชิกใหม่เข้าร่วม",
            color=discord.Color.green(),
            timestamp=self._now(),
        )
        embed.set_author(name=member.name, icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.description = f"{member.mention} เข้าร่วมเซิร์ฟเวอร์"
        self._add_field(embed, "บัญชีสร้างเมื่อ", f"{discord.utils.format_dt(member.created_at, 'D')}\n{discord.utils.format_dt(member.created_at, 'R')}")
        self._add_field(embed, "จำนวนสมาชิก", str(member.guild.member_count))
        embed.set_footer(text=f"User ID: {member.id}")

        # ── Invite tracking ──
        inviter_text = "ไม่สามารถระบุได้"
        guild_invites = self.invites.get(member.guild.id, {})
        try:
            current = await member.guild.invites()
            for inv in current:
                cached_uses = guild_invites.get(inv.code, 0)
                if inv.uses > cached_uses:
                    inviter_text = (
                        f"{inv.inviter.mention} (`{inv.inviter.name}`)\n"
                        f"Code: `{inv.code}` · ใช้ไปแล้ว {inv.uses} ครั้ง"
                        if inv.inviter
                        else f"Code: `{inv.code}` (ไม่พบผู้สร้าง)"
                    )
                    guild_invites[inv.code] = inv.uses
                    break
            self.invites[member.guild.id] = {inv.code: inv.uses for inv in current}
        except (discord.Forbidden, discord.HTTPException):
            pass

        self._add_field(embed, "ลิงก์เชิญโดย", inviter_text, inline=False)
        await self.send_log(embed, member.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        embed = discord.Embed(
            title="📤 สมาชิกออกจากเซิร์ฟเวอร์",
            color=discord.Color.red(),
            timestamp=self._now(),
        )
        embed.set_author(name=member.name, icon_url=member.display_avatar.url)
        embed.description = f"{member.mention} (`{member.name}`) ออกจากเซิร์ฟเวอร์"
        roles_text = ", ".join(r.mention for r in member.roles[1:])
        self._add_field(embed, "บทบาทที่มี", roles_text or "ไม่มี", inline=False)
        embed.set_footer(text=f"User ID: {member.id}")

        # ตรวจว่าถูก kick หรือไม่
        entry = await self._get_audit_entry(member.guild, discord.AuditLogAction.kick, member.id)
        if entry:
            embed.title = "👢 สมาชิกถูกเตะออก (Kick)"
            embed.color = discord.Color.dark_orange()
            self._add_field(embed, "เตะโดย", entry.user.mention)
            self._add_field(embed, "เหตุผล", entry.reason or "ไม่ระบุ")

        await self.send_log(embed, member.guild)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        embed = discord.Embed(
            title="🔨 สมาชิกถูกแบน",
            color=discord.Color.dark_red(),
            timestamp=self._now(),
        )
        embed.set_author(name=user.name, icon_url=user.display_avatar.url)
        embed.description = f"{user.mention} (`{user.id}`) ถูกแบนจากเซิร์ฟเวอร์"

        entry = await self._get_audit_entry(guild, discord.AuditLogAction.ban, user.id)
        if entry:
            self._add_field(embed, "แบนโดย", entry.user.mention)
            self._add_field(embed, "เหตุผล", entry.reason or "ไม่ระบุ")

        embed.set_footer(text=f"User ID: {user.id}")
        await self.send_log(embed, guild)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        embed = discord.Embed(
            title="🔓 ยกเลิกการแบน",
            color=discord.Color.green(),
            timestamp=self._now(),
        )
        embed.set_author(name=user.name, icon_url=user.display_avatar.url)
        embed.description = f"ยกเลิกการแบนให้ {user.mention} (`{user.id}`)"

        entry = await self._get_audit_entry(guild, discord.AuditLogAction.unban, user.id)
        if entry:
                self._add_field(embed, "ยกเลิกโดย", entry.user.mention)

        await self.send_log(embed, guild)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        guild = after.guild

        # ── Nickname ──
        if before.nick != after.nick:
            embed = discord.Embed(title="📝 เปลี่ยนชื่อเล่น", color=discord.Color.blue(), timestamp=self._now())
            embed.set_author(name=after.name, icon_url=after.display_avatar.url)
            embed.description = f"{after.mention} เปลี่ยนชื่อเล่น"
            self._add_field(embed, "ชื่อเล่นเดิม", before.nick or "_(ไม่มี)_", inline=True)
            self._add_field(embed, "ชื่อเล่นใหม่", after.nick or "_(ไม่มี)_", inline=True)
            entry = await self._get_audit_entry(guild, discord.AuditLogAction.member_update, after.id)
            if entry and entry.user.id != after.id:
                self._add_field(embed, "แก้ไขโดย", entry.user.mention, inline=False)
            embed.set_footer(text=f"User ID: {after.id}")
            await self.send_log(embed, guild)

        # ── Timeout ──
        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:
                embed = discord.Embed(title="⏳ สมาชิกถูก Timeout", color=discord.Color.dark_red(), timestamp=self._now())
                embed.description = (
                    f"{after.mention} ถูก Timeout จนถึง "
                    f"{discord.utils.format_dt(after.timed_out_until)} "
                    f"({discord.utils.format_dt(after.timed_out_until, 'R')})"
                )
            else:
                embed = discord.Embed(title="🔓 ยกเลิก Timeout", color=discord.Color.green(), timestamp=self._now())
                embed.description = f"{after.mention} พ้นช่วง Timeout แล้ว"

            embed.set_author(name=after.name, icon_url=after.display_avatar.url)
            entry = await self._get_audit_entry(guild, discord.AuditLogAction.member_update, after.id)
            if entry:
                self._add_field(embed, "ดำเนินการโดย", entry.user.mention)
                self._add_field(embed, "เหตุผล", entry.reason or "ไม่ระบุ")
            embed.set_footer(text=f"User ID: {after.id}")
            await self.send_log(embed, guild)

        # ── Roles ──
        if before.roles != after.roles:
            added = [r for r in after.roles if r not in before.roles]
            removed = [r for r in before.roles if r not in after.roles]
            if added or removed:
                embed = discord.Embed(title="🛡️ อัปเดตบทบาทสมาชิก", color=discord.Color.blurple(), timestamp=self._now())
                embed.set_author(name=after.name, icon_url=after.display_avatar.url)
                if added:
                    self._add_field(embed, "✅ เพิ่มบทบาท", " ".join(r.mention for r in added), inline=False)
                if removed:
                    self._add_field(embed, "❌ ถอดบทบาท", " ".join(r.mention for r in removed), inline=False)
                entry = await self._get_audit_entry(guild, discord.AuditLogAction.member_role_update, after.id)
                if entry:
                    self._add_field(embed, "ดำเนินการโดย", entry.user.mention, inline=False)
                embed.set_footer(text=f"User ID: {after.id}")
                await self.send_log(embed, guild)

        # ── Server Avatar ──
        if before.guild_avatar != after.guild_avatar:
            embed = discord.Embed(title="🖼️ เปลี่ยนรูปโปรไฟล์ (Server)", color=discord.Color.blue(), timestamp=self._now())
            embed.set_author(name=after.name, icon_url=after.display_avatar.url)
            embed.description = f"{after.mention} อัปเดตรูปโปรไฟล์เฉพาะเซิร์ฟเวอร์"
            
            entry = await self._get_audit_entry(guild, discord.AuditLogAction.member_update, after.id)
            if entry and (entry.before.avatar is not None or entry.after.avatar is not None):
                 self._add_field(embed, "ดำเนินการโดย", entry.user.mention, inline=False)
            if before.guild_avatar:
                self._add_field(embed, "รูปเดิม", f"[คลิก]({before.guild_avatar.url})")
            if after.guild_avatar:
                embed.set_image(url=after.guild_avatar.url)
                self._add_field(embed, "รูปใหม่", f"[คลิก]({after.guild_avatar.url})")
            embed.set_footer(text=f"User ID: {after.id}")
            await self.send_log(embed, guild)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User) -> None:
        # ── Username ──
        if before.name != after.name or before.discriminator != after.discriminator:
            embed = discord.Embed(title="👤 เปลี่ยนชื่อผู้ใช้", color=discord.Color.blue(), timestamp=self._now())
            embed.set_author(name=after.name, icon_url=after.display_avatar.url)
            embed.description = f"{after.mention} เปลี่ยนชื่อผู้ใช้"
            self._add_field(embed, "ชื่อเดิม", f"{before.name}#{before.discriminator}", inline=True)
            self._add_field(embed, "ชื่อใหม่", f"{after.name}#{after.discriminator}", inline=True)
            embed.set_footer(text=f"User ID: {after.id}")
            await self.send_log(embed)

        # ── Global Avatar ──
        if before.avatar != after.avatar:
            embed = discord.Embed(title="🖼️ เปลี่ยนรูปโปรไฟล์หลัก", color=discord.Color.blue(), timestamp=self._now())
            embed.set_author(name=after.name, icon_url=after.display_avatar.url)
            embed.description = f"{after.mention} เปลี่ยนรูปโปรไฟล์หลักของบัญชี"
            if before.avatar:
                embed.set_thumbnail(url=before.avatar.url)
                self._add_field(embed, "รูปเดิม", f"[คลิก]({before.avatar.url})")
            if after.avatar:
                embed.set_image(url=after.avatar.url)
                self._add_field(embed, "รูปใหม่", f"[คลิก]({after.avatar.url})")
            embed.set_footer(text=f"User ID: {after.id}")
            await self.send_log(embed)

    # ──────────────────────────────────────────
    #  Voice events
    # ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot: return
        if not self._rl("voice", member.id):
            return

        guild = member.guild

        # ── Channel Join / Leave / Move ──
        if before.channel != after.channel:
            embed = discord.Embed(color=discord.Color.orange(), timestamp=self._now())
            embed.set_author(name=member.name, icon_url=member.display_avatar.url)
            embed.set_footer(text=f"User ID: {member.id}")

            if before.channel is None:
                embed.title = "🔊 เข้าช่องเสียง"
                embed.description = f"{member.mention} เข้า {after.channel.mention} (**{after.channel.name}**)"
                embed.color = discord.Color.green()

            elif after.channel is None:
                embed.title = "🔇 ออกจากช่องเสียง"
                embed.description = f"{member.mention} ออกจาก {before.channel.mention} (**{before.channel.name}**)"
                embed.color = discord.Color.red()
                # ตรวจว่าถูก admin disconnect
                entry = await self._get_audit_entry(guild, discord.AuditLogAction.member_disconnect, member.id)
                if entry:
                    embed.title = "🚫 ถูกตัดการเชื่อมต่อจากช่องเสียง"
                    self._add_field(embed, "ดำเนินการโดย", f"{entry.user.mention} ({entry.user.name})", inline=False)

            else:
                embed.title = "🔄 ย้ายช่องเสียง"
                embed.description = f"{member.mention} ย้ายจาก {before.channel.mention} → {after.channel.mention}"
                entry = await self._get_audit_entry(guild, discord.AuditLogAction.member_move, member.id)
                if entry:
                    self._add_field(embed, "ย้ายโดย", f"{entry.user.mention} ({entry.user.name})", inline=False)

            await self.send_log(embed, guild)
            return

        # ── Mute / Deaf / Stream ──
        changes: list[str] = []
        is_server_action = False

        if before.self_mute != after.self_mute:
            changes.append("🔇 ปิดไมค์" if after.self_mute else "🎙️ เปิดไมค์")
        if before.self_deaf != after.self_deaf:
            changes.append("🎧 ปิดหู" if after.self_deaf else "🔊 เปิดหู")
        if before.self_stream != after.self_stream:
            changes.append("📡 เริ่ม Stream" if after.self_stream else "📡 หยุด Stream")
        if before.self_video != after.self_video:
            changes.append("📷 เปิดกล้อง" if after.self_video else "📷 ปิดกล้อง")
        if before.mute != after.mute:
            changes.append("🚨 **ถูกปิดไมค์โดยแอดมิน**" if after.mute else "✅ **ถูกยกเลิกการปิดไมค์**")
            is_server_action = True
        if before.deaf != after.deaf:
            changes.append("🚨 **ถูกปิดหูโดยแอดมิน**" if after.deaf else "✅ **ถูกยกเลิกการปิดหู**")
            is_server_action = True

        if changes:
            embed = discord.Embed(title="🎙️ สถานะเสียงเปลี่ยนไป", color=discord.Color.orange(), timestamp=self._now())
            embed.set_author(name=member.name, icon_url=member.display_avatar.url)
            embed.description = f"{member.mention}: " + " · ".join(changes)
            if after.channel:
                embed.description += f"\nในช่อง: {after.channel.mention}"

            if is_server_action:
                entry = await self._get_audit_entry(guild, discord.AuditLogAction.member_update, member.id)
                if entry:
                    self._add_field(embed, "ดำเนินการโดย", f"{entry.user.mention} ({entry.user.name})", inline=False)

            embed.set_footer(text=f"User ID: {member.id}")
            await self.send_log(embed, guild)

    # ──────────────────────────────────────────
    #  Message events
    # ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Log เฉพาะข้อความที่มีไฟล์แนบ"""
        if message.author.bot or not message.guild or not message.attachments:
            return
        if not self._rl("msg_attach", message.author.id):
            return

        embed = discord.Embed(title="📎 ส่งไฟล์แนบ", color=discord.Color.light_grey(), timestamp=self._now())
        embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
        embed.description = f"{message.author.mention} ส่งไฟล์ในช่อง {message.channel.mention}"

        file_lines = []
        for a in message.attachments:
            size_kb = a.size / 1024
            file_lines.append(f"[{a.filename}]({a.url}) `{size_kb:.1f} KB`")
            if a.content_type and "image" in a.content_type and not embed.image.url:
                embed.set_image(url=a.proxy_url or a.url)

        self._add_field(embed, "ไฟล์แนบ", "\n".join(file_lines), inline=False)
        if message.content:
            self._add_field(embed, "ข้อความ", message.content[:1000], inline=False)
        embed.set_footer(text=f"User ID: {message.author.id} | Msg ID: {message.id}")
        await self.send_log(embed, message.guild)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.author.bot or before.content == after.content:
            return
        if not self._rl("msg_edit", after.author.id):
            return

        embed = discord.Embed(title="✏️ แก้ไขข้อความ", color=discord.Color.yellow(), timestamp=self._now())
        embed.set_author(name=after.author.name, icon_url=after.author.display_avatar.url)
        embed.description = f"แก้ไขข้อความโดย {after.author.mention}"
        self._add_field(embed, "ช่อง", after.channel.mention, inline=True)
        self._add_field(embed, "ลิงก์ข้อความ", f"[คลิกที่นี่]({after.jump_url})", inline=True)
        self._add_field(embed, "ก่อนแก้ไข", before.content or "_(ว่าง)_", inline=False)
        self._add_field(embed, "หลังแก้ไข", after.content or "_(ว่าง)_", inline=False)

        if after.attachments:
            for a in after.attachments:
                if a.content_type and "image" in a.content_type:
                    embed.set_image(url=a.proxy_url or a.url)
                    break

        embed.set_footer(text=f"Author ID: {after.author.id} | Msg ID: {after.id}")
        await self.send_log(embed, after.guild)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        has_image = any(
            a.content_type and "image" in a.content_type for a in message.attachments
        )
        title = f"🖼️ ลบข้อความ (มีรูป) ของ {message.author.name}" if has_image else "🗑️ ลบข้อความ"

        embed = discord.Embed(title=title, color=discord.Color.red(), timestamp=self._now())
        embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
        embed.description = f"ข้อความของ {message.author.mention} ถูกลบในช่อง {message.channel.mention}"
        self._add_field(embed, "เนื้อหา", message.content or "_(ว่าง)_", inline=False)

        # ไฟล์แนบ
        if message.attachments:
            images, videos, others = [], [], []
            for a in message.attachments:
                link = f"[{a.filename}]({a.url})"
                ct = a.content_type or ""
                if "image" in ct:
                    images.append(link)
                    if not embed.image.url:
                        embed.set_image(url=a.proxy_url or a.url)
                elif "video" in ct:
                    videos.append(link)
                else:
                    others.append(link)

            parts = []
            if images:
                parts.append("🖼️ รูปภาพ: " + ", ".join(images))
            if videos:
                parts.append("🎥 วิดีโอ: " + ", ".join(videos))
            if others:
                parts.append("📁 ไฟล์อื่น: " + ", ".join(others))
            if parts:
                self._add_field(embed, "ไฟล์แนบ", "\n".join(parts), inline=False)

        # ตรวจว่าใครลบ (ต้องใช้ audit log)
        info_footer = f"Author: {message.author.id} | Msg ID: {message.id}"
        if message.guild:
            entry = await self._get_audit_entry(
                message.guild, discord.AuditLogAction.message_delete, message.author.id, within_seconds=5
            )
            if entry:
                self._add_field(embed, "ลบโดย", entry.user.mention, inline=False)
            else:
                info_footer += " | หากไม่มีชื่อผู้ลบ แปลว่าเป็นเจ้าของข้อความลบเอง"

        embed.set_footer(text=info_footer)
        await self.send_log(embed, message.guild)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]) -> None:
        if not messages:
            return
        guild = messages[0].guild
        channel = messages[0].channel
        embed = discord.Embed(
            title="🧹 ลบข้อความจำนวนมาก (Bulk Delete)",
            color=discord.Color.dark_red(),
            timestamp=self._now(),
        )
        embed.description = f"ลบ **{len(messages)}** ข้อความ ในช่อง {channel.mention}"

        # พยายามหาว่าใครสั่ง purge
        if guild:
            entry = await self._get_audit_entry(guild, discord.AuditLogAction.message_bulk_delete, channel.id)
            if entry:
                embed.add_field(name="สั่งโดย", value=entry.user.mention)

        # สรุปผู้ส่งข้อความ
        author_count: dict[str, int] = defaultdict(int)
        for m in messages:
            if not m.author.bot:
                author_count[m.author.name] += 1
        if author_count:
            top = sorted(author_count.items(), key=lambda x: x[1], reverse=True)[:5]
            self._add_field(
                embed,
                "ข้อความของ (Top 5)",
                "\n".join(f"`{name}`: {cnt} ข้อความ" for name, cnt in top),
                inline=False,
            )

        embed.set_footer(text=f"Channel ID: {channel.id}")
        await self.send_log(embed, guild)

    # ──────────────────────────────────────────
    #  Channel events
    # ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        embed = discord.Embed(title="🆕 สร้างช่องใหม่", color=discord.Color.green(), timestamp=self._now())
        embed.description = f"**{channel.name}** ({channel.mention})\nประเภท: `{channel.type}`"
        if channel.category:
            self._add_field(embed, "หมวดหมู่", channel.category.name)

        entry = await self._get_audit_entry(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        if entry:
            embed.add_field(name="สร้างโดย", value=f"{entry.user.mention} ({entry.user.name})")

        await self.send_log(embed, channel.guild)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        embed = discord.Embed(title="🗑️ ลบช่อง", color=discord.Color.red(), timestamp=self._now())
        embed.description = f"ชื่อช่อง: **{channel.name}**\nประเภท: `{channel.type}`"
        if channel.category:
            self._add_field(embed, "หมวดหมู่", channel.category.name)

        entry = await self._get_audit_entry(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        if entry:
            embed.add_field(name="ลบโดย", value=f"{entry.user.mention} ({entry.user.name})")

        await self.send_log(embed, channel.guild)

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self,
        before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ) -> None:
        embed = discord.Embed(title="⚙️ อัปเดตช่อง", color=discord.Color.blue(), timestamp=self._now())
        embed.description = f"ช่อง: {after.mention} (`{after.name}`)"
        changed = False

        if before.name != after.name:
            self._add_field(embed, "เปลี่ยนชื่อ", f"`{before.name}` → `{after.name}`", inline=False)
            changed = True
        if before.category != after.category:
            self._add_field(
                embed,
                "ย้ายหมวดหมู่",
                f"`{before.category}` → `{after.category}`",
                inline=False,
            )
            changed = True

        # ตรวจ permission overwrites
        if hasattr(before, "overwrites") and before.overwrites != after.overwrites:
            self._add_field(embed, "สิทธิ์ (Overwrites)", "มีการแก้ไข Permission Overwrites", inline=False)
            changed = True

        if not changed:
            return

        entry = await self._get_audit_entry(after.guild, discord.AuditLogAction.channel_update, after.id)
        if entry:
            embed.add_field(name="แก้ไขโดย", value=entry.user.mention, inline=False)

        await self.send_log(embed, after.guild)

    # ──────────────────────────────────────────
    #  Role events
    # ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        embed = discord.Embed(title="🎭 สร้างบทบาทใหม่", color=discord.Color.green(), timestamp=self._now())
        embed.description = f"บทบาท: {role.mention} (`{role.name}`)"
        self._add_field(embed, "สี", str(role.color))
        self._add_field(embed, "Hoisted", "✅" if role.hoist else "❌")
        self._add_field(embed, "Mentionable", "✅" if role.mentionable else "❌")

        entry = await self._get_audit_entry(role.guild, discord.AuditLogAction.role_create, role.id)
        if entry:
            self._add_field(embed, "สร้างโดย", f"{entry.user.mention} ({entry.user.name})")

        await self.send_log(embed, role.guild)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        embed = discord.Embed(title="🗑️ ลบบทบาท", color=discord.Color.red(), timestamp=self._now())
        embed.description = f"บทบาทที่ถูกลบ: **{role.name}**"

        entry = await self._get_audit_entry(role.guild, discord.AuditLogAction.role_delete, role.id)
        if entry:
            embed.add_field(name="ลบโดย", value=f"{entry.user.mention} ({entry.user.name})")

        await self.send_log(embed, role.guild)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        embed = discord.Embed(
            title="🛡️ อัปเดตบทบาท",
            color=after.color if after.color.value else discord.Color.blue(),
            timestamp=self._now(),
        )
        embed.description = f"บทบาท: {after.mention}"
        changed = False

        if before.name != after.name:
            self._add_field(embed, "เปลี่ยนชื่อ", f"`{before.name}` → `{after.name}`", inline=False)
            changed = True
        if before.color != after.color:
            self._add_field(embed, "เปลี่ยนสี", f"`{before.color}` → `{after.color}`", inline=False)
            changed = True
        if before.hoist != after.hoist:
            self._add_field(embed, "Hoisted", "✅ เปิด" if after.hoist else "❌ ปิด", inline=True)
            changed = True
        if before.mentionable != after.mentionable:
            self._add_field(embed, "Mentionable", "✅ เปิด" if after.mentionable else "❌ ปิด", inline=True)
            changed = True
        if before.permissions != after.permissions:
            granted, revoked = diff_permissions(before.permissions, after.permissions)
            if granted:
                self._add_field(embed, "✅ เพิ่มสิทธิ์", ", ".join(granted) or "—", inline=False)
            if revoked:
                self._add_field(embed, "❌ ถอดสิทธิ์", ", ".join(revoked) or "—", inline=False)
            changed = True

        if not changed:
            return

        entry = await self._get_audit_entry(after.guild, discord.AuditLogAction.role_update, after.id)
        if entry:
            embed.add_field(name="แก้ไขโดย", value=entry.user.mention, inline=False)

        await self.send_log(embed, after.guild)

    # ──────────────────────────────────────────
    #  Guild events
    # ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild) -> None:
        embed = discord.Embed(title="⚙️ ข้อมูลเซิร์ฟเวอร์เปลี่ยนไป", color=discord.Color.purple(), timestamp=self._now())
        changed = False

        if before.name != after.name:
            self._add_field(embed, "เปลี่ยนชื่อ", f"`{before.name}` → `{after.name}`", inline=False)
            changed = True
        if before.description != after.description:
            desc_text = f"**เดิม:** {before.description or '_(ว่าง)_'}\n**ใหม่:** {after.description or '_(ว่าง)_'}"
            self._add_field(embed, "เปลี่ยนคำอธิบาย", desc_text, inline=False)
            changed = True
        if before.icon != after.icon:
            self._add_field(embed, "เปลี่ยนไอคอน", "มีการอัปเดตรูปไอคอน", inline=False)
            if after.icon:
                embed.set_thumbnail(url=after.icon.url)
            changed = True
        if before.banner != after.banner:
            self._add_field(embed, "เปลี่ยนแบนเนอร์", "มีการอัปเดตแบนเนอร์", inline=False)
            if after.banner:
                embed.set_image(url=after.banner.url)
            changed = True
        if before.verification_level != after.verification_level:
            self._add_field(
                embed,
                "เปลี่ยนระดับยืนยัน",
                f"`{before.verification_level}` → `{after.verification_level}`",
                inline=False,
            )
            changed = True

        if changed:
            entry = await self._get_audit_entry(after, discord.AuditLogAction.guild_update, after.id)
            if entry:
                self._add_field(embed, "แก้ไขโดย", entry.user.mention, inline=False)
            await self.send_log(embed, after)

    # ──────────────────────────────────────────
    #  Thread events
    # ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        embed = discord.Embed(title="🧵 สร้างเธรดใหม่", color=discord.Color.green(), timestamp=self._now())
        embed.description = f"เธรด: **{thread.name}** ({thread.mention})"
        if thread.parent:
            self._add_field(embed, "ช่องหลัก", thread.parent.mention)
        if thread.owner:
            self._add_field(embed, "สร้างโดย", thread.owner.mention)
        await self.send_log(embed, thread.guild)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread) -> None:
        embed = discord.Embed(title="🗑️ ลบเธรด", color=discord.Color.red(), timestamp=self._now())
        embed.description = f"ชื่อเธรด: **{thread.name}**"
        if thread.parent:
            self._add_field(embed, "ช่องหลัก", thread.parent.name)
        await self.send_log(embed, thread.guild)

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread) -> None:
        if before.name == after.name and before.archived == after.archived and before.locked == after.locked:
            return
        embed = discord.Embed(title="🧵 อัปเดตเธรด", color=discord.Color.blue(), timestamp=self._now())
        embed.description = f"เธรด: {after.mention} (`{after.name}`)"

        if before.name != after.name:
            self._add_field(embed, "เปลี่ยนชื่อ", f"`{before.name}` → `{after.name}`")
        if before.archived != after.archived:
            self._add_field(embed, "สถานะ", "📦 จัดเก็บแล้ว" if after.archived else "🔄 เปิดใช้งานใหม่")
        if before.locked != after.locked:
            self._add_field(embed, "ล็อก", "🔒 ล็อกแล้ว" if after.locked else "🔓 ปลดล็อก")

        await self.send_log(embed, after.guild)

    # ──────────────────────────────────────────
    #  Invite events
    # ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        embed = discord.Embed(title="📩 สร้างลิงก์เชิญ", color=discord.Color.blue(), timestamp=self._now())
        embed.description = f"ลิงก์: `{invite.url}`\nช่อง: {invite.channel.mention}"
        self._add_field(embed, "สร้างโดย", invite.inviter.mention if invite.inviter else "ระบบ")
        max_uses = f"{invite.max_uses} ครั้ง" if invite.max_uses else "ไม่จำกัด"
        max_age = "ไม่หมดอายุ" if invite.max_age == 0 else f"{invite.max_age // 60} นาที"
        self._add_field(embed, "ใช้ได้สูงสุด", max_uses)
        self._add_field(embed, "หมดอายุใน", max_age)
        self._add_field(embed, "Temporary", "✅" if invite.temporary else "❌")
        embed.set_footer(text=f"Code: {invite.code}")

        if invite.guild and invite.guild.id not in self.invites:
            self.invites[invite.guild.id] = {}
        if invite.guild:
            self.invites[invite.guild.id][invite.code] = invite.uses

        await self.send_log(embed, invite.guild)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        embed = discord.Embed(title="🗑️ ลบลิงก์เชิญ", color=discord.Color.red(), timestamp=self._now())
        embed.description = f"Code: `{invite.code}` ในช่อง {invite.channel.mention} ถูกลบหรือหมดอายุ"
        
        entry = await self._get_audit_entry(invite.guild, discord.AuditLogAction.invite_delete, invite.code) if invite.guild else None
        if entry:
            self._add_field(embed, "ลบโดย", entry.user.mention)
            
        await self.send_log(embed, invite.guild)

    # ──────────────────────────────────────────
    #  Emoji / Sticker events
    # ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_emojis_update(
        self,
        guild: discord.Guild,
        before: list[discord.Emoji],
        after: list[discord.Emoji],
    ) -> None:
        embed = discord.Embed(title="🎨 อัปเดตอีโมจิ", color=discord.Color.purple(), timestamp=self._now())
        
        # ค้นหาว่าใครเป็นคนทำ
        entry = await self._get_audit_entry(guild, discord.AuditLogAction.emoji_update, 0, within_seconds=10, limit=1) # target_id 0 doesn't work well for list updates, but we can try without target_id match in a custom way or just get latest
        # Better: get latest emoji_create/emoji_update/emoji_delete
        action = None
        if len(before) < len(after): action = discord.AuditLogAction.emoji_create
        elif len(before) > len(after): action = discord.AuditLogAction.emoji_delete
        else: action = discord.AuditLogAction.emoji_update
        
        if action:
            try:
                async for e in guild.audit_logs(limit=1, action=action):
                    if (self._now() - e.created_at).total_seconds() < 10:
                        embed.add_field(name="ดำเนินการโดย", value=e.user.mention, inline=False)
                        break
            except Exception as e:
                logger.warning(f"[ServerLogger] emoji audit log lookup skipped: {e}")

        before_set, after_set = set(before), set(after)

        if len(before) < len(after):
            new_emojis = [e for e in after if e not in before_set]
            embed.color = discord.Color.green()
            embed.description = "เพิ่มอีโมจิใหม่:\n" + "\n".join(
                f"{e} `:{e.name}:` (ID: `{e.id}`)" for e in new_emojis
            )
        elif len(before) > len(after):
            del_emojis = [e for e in before if e not in after_set]
            embed.color = discord.Color.red()
            embed.description = "ลบอีโมจิ:\n" + "\n".join(
                f"`:{e.name}:` (ID: `{e.id}`)" for e in del_emojis
            )
        else:
            embed.description = "มีการแก้ไขชื่ออีโมจิ"

        await self.send_log(embed, guild)

    @commands.Cog.listener()
    async def on_guild_stickers_update(
        self,
        guild: discord.Guild,
        before: list[discord.GuildSticker],
        after: list[discord.GuildSticker],
    ) -> None:
        embed = discord.Embed(title="🖼️ อัปเดตสติกเกอร์", color=discord.Color.purple(), timestamp=self._now())

        action = None
        if len(before) < len(after): action = discord.AuditLogAction.sticker_create
        elif len(before) > len(after): action = discord.AuditLogAction.sticker_delete
        else: action = discord.AuditLogAction.sticker_update

        if action:
            try:
                async for e in guild.audit_logs(limit=1, action=action):
                    if (self._now() - e.created_at).total_seconds() < 10:
                        embed.add_field(name="ดำเนินการโดย", value=e.user.mention, inline=False)
                        break
            except Exception as e:
                logger.warning(f"[ServerLogger] sticker audit log lookup skipped: {e}")
            new_s = next((s for s in after if s not in before), None)
            if new_s:
                embed.color = discord.Color.green()
                embed.description = f"เพิ่มสติกเกอร์: **{new_s.name}** (ID: `{new_s.id}`)"
                embed.set_image(url=new_s.url)
        elif len(before) > len(after):
            del_s = next((s for s in before if s not in after), None)
            if del_s:
                embed.color = discord.Color.red()
                embed.description = f"ลบสติกเกอร์: **{del_s.name}** (ID: `{del_s.id}`)"

        await self.send_log(embed, guild)

    # ──────────────────────────────────────────
    #  Stage events
    # ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_stage_instance_create(self, stage: discord.StageInstance) -> None:
        embed = discord.Embed(title="🎭 เริ่มกิจกรรมเวที (Stage)", color=discord.Color.green(), timestamp=self._now())
        embed.description = f"หัวข้อ: **{stage.topic}**\nช่อง: {stage.channel.mention}"
        await self.send_log(embed, stage.guild)

    @commands.Cog.listener()
    async def on_stage_instance_delete(self, stage: discord.StageInstance) -> None:
        embed = discord.Embed(title="🎭 สิ้นสุดกิจกรรมเวที", color=discord.Color.red(), timestamp=self._now())
        embed.description = f"หัวข้อ: **{stage.topic}**"
        await self.send_log(embed, stage.guild)

    @commands.Cog.listener()
    async def on_stage_instance_update(self, before: discord.StageInstance, after: discord.StageInstance) -> None:
        embed.description = f"เธรด: {after.mention} (`{after.name}`)"
        if before.topic != after.topic:
            self._add_field(embed, "หัวข้อเดิม", before.topic)
            self._add_field(embed, "หัวข้อใหม่", after.topic)
        await self.send_log(embed, after.guild)

    # ──────────────────────────────────────────
    #  Scheduled Event events
    # ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_scheduled_event_create(self, event: discord.ScheduledEvent) -> None:
        embed = discord.Embed(title="📅 สร้างกิจกรรม (Scheduled Event)", color=discord.Color.green(), timestamp=self._now())
        embed.description = f"**{event.name}**"
        if event.description:
            self._add_field(embed, "รายละเอียด", event.description, inline=False)
        self._add_field(embed, "เริ่มต้น", discord.utils.format_dt(event.start_time, "F"))
        if event.end_time:
            self._add_field(embed, "สิ้นสุด", discord.utils.format_dt(event.end_time, "F"))
        if event.creator:
            self._add_field(embed, "สร้างโดย", event.creator.mention)
        if event.image:
            embed.set_image(url=event.image.url)
        await self.send_log(embed, event.guild)

    @commands.Cog.listener()
    async def on_scheduled_event_delete(self, event: discord.ScheduledEvent) -> None:
        embed = discord.Embed(title="🗑️ ลบกิจกรรม", color=discord.Color.red(), timestamp=self._now())
        embed.description = f"กิจกรรม: **{event.name}**"
        await self.send_log(embed, event.guild)

    @commands.Cog.listener()
    async def on_scheduled_event_update(
        self, before: discord.ScheduledEvent, after: discord.ScheduledEvent
    ) -> None:
        if before.status != after.status:
            status_map = {
                discord.EventStatus.active: ("🟢 เริ่มกิจกรรมแล้ว", discord.Color.green()),
                discord.EventStatus.ended: ("🔴 กิจกรรมสิ้นสุดแล้ว", discord.Color.red()),
                discord.EventStatus.cancelled: ("❌ ยกเลิกกิจกรรม", discord.Color.dark_red()),
            }
            title, color = status_map.get(after.status, ("📅 อัปเดตกิจกรรม", discord.Color.blue()))
            embed = discord.Embed(title=title, color=color, timestamp=self._now())
            embed.description = f"**{after.name}**"
            await self.send_log(embed, after.guild)

    # ──────────────────────────────────────────
    #  AutoMod events
    # ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_automod_rule_create(self, rule: discord.AutoModRule) -> None:
        embed = discord.Embed(title="🛡️ สร้างกฎ AutoMod ใหม่", color=discord.Color.green(), timestamp=self._now())
        embed.description = f"ชื่อกฎ: **{rule.name}**\nID: `{rule.id}`"
        self._add_field(embed, "ประเภท Event", str(rule.event_type))
        await self.send_log(embed, rule.guild)

    @commands.Cog.listener()
    async def on_automod_rule_delete(self, rule: discord.AutoModRule) -> None:
        embed = discord.Embed(title="🗑️ ลบกฎ AutoMod", color=discord.Color.red(), timestamp=self._now())
        embed.description = f"ชื่อกฎ: **{rule.name}**\nID: `{rule.id}`"
        await self.send_log(embed, rule.guild)

    @commands.Cog.listener()
    async def on_automod_action_execution(self, execution: discord.AutoModAction) -> None:
        if not self._rl("automod", execution.user_id):
            return
        embed = discord.Embed(title="🛡️ AutoMod ทำงาน", color=discord.Color.dark_orange(), timestamp=self._now())
        member = execution.member
        embed.description = (
            f"ผู้ใช้: {member.mention if member else f'<@{execution.user_id}>'}\n"
            f"กฎ: **{execution.rule_name or 'ไม่ระบุ'}**\n"
            f"การกระทำ: `{execution.action.type}`"
        )
        if execution.content:
            self._add_field(embed, "เนื้อหาที่ถูกจับ", execution.content, inline=False)
        if execution.matched_keyword:
            self._add_field(embed, "คำที่ match", f"`{execution.matched_keyword}`", inline=True)
        embed.set_footer(text=f"User ID: {execution.user_id}")
        await self.send_log(embed, execution.guild)

    # ──────────────────────────────────────────
    #  Misc events
    # ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.TextChannel) -> None:
        embed = discord.Embed(title="🔗 อัปเดต Webhooks", color=discord.Color.blue(), timestamp=self._now())
        embed.description = f"มีการแก้ไข Webhook ในช่อง {channel.mention}"
        
        entry = await self._get_audit_entry(channel.guild, discord.AuditLogAction.webhook_update, 0)
        if entry:
             self._add_field(embed, "ดำเนินการโดย", entry.user.mention)
             
        await self.send_log(embed, channel.guild)

    @commands.Cog.listener()
    async def on_guild_integrations_update(self, guild: discord.Guild) -> None:
        embed = discord.Embed(title="🔌 อัปเดต Integrations", color=discord.Color.blue(), timestamp=self._now())
        embed.description = "มีการเปลี่ยนแปลง Integration/Application ของเซิร์ฟเวอร์"
        
        entry = await self._get_audit_entry(guild, discord.AuditLogAction.integration_update, 0)
        if entry:
            self._add_field(embed, "ดำเนินการโดย", entry.user.mention)
            
        await self.send_log(embed, guild)

    @commands.Cog.listener()
    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: discord.app_commands.Command,
    ) -> None:
        embed = discord.Embed(title="⌨️ ใช้คำสั่ง", color=discord.Color.light_grey(), timestamp=self._now())
        embed.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)
        channel_mention = interaction.channel.mention if hasattr(interaction.channel, "mention") else "DM"
        embed.description = f"ใช้คำสั่ง `/{command.name}` ในช่อง {channel_mention}"

        opts = interaction.data.get("options") if interaction.data else None
        if opts:
            self._add_field(
                embed,
                "พารามิเตอร์",
                "\n".join(f"**{o['name']}:** `{o.get('value', '—')}`" for o in opts),
                inline=False,
            )

        await self.send_log(embed, interaction.guild)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ServerLogger(bot))
