import discord
from discord.ext import commands
import logging
import asyncio

logger = logging.getLogger('discord_bot')

# ─────────────────────────────────────────────
#  Rate-limit-aware API wrapper
#  จะ retry อัตโนมัติเมื่อโดน 429 สูงสุด max_retries ครั้ง
# ─────────────────────────────────────────────
async def safe_api(coro, label: str = "", max_retries: int = 5):
    """
    รัน coroutine พร้อม retry อัตโนมัติเมื่อโดน HTTPException (429)
    คืนค่าผลลัพธ์หรือ None ถ้า fail หลัง retry ครบ
    """
    for attempt in range(1, max_retries + 1):
        try:
            return await coro
        except discord.HTTPException as e:
            if e.status == 429:
                # อ่าน retry_after จาก header ถ้ามี
                retry_after = getattr(e, "retry_after", None) or 5.0
                logger.warning(f"[{label}] Rate limited (429) — รอ {retry_after:.1f}s (ครั้งที่ {attempt}/{max_retries})")
                await asyncio.sleep(float(retry_after) + 0.5)
            else:
                logger.error(f"[{label}] HTTPException {e.status}: {e.text}")
                return None
        except discord.Forbidden:
            logger.error(f"[{label}] Forbidden — บอทไม่มีสิทธิ์เพียงพอ")
            return None
        except Exception as e:
            logger.error(f"[{label}] Unexpected error: {e}")
            return None
    logger.error(f"[{label}] ล้มเหลวหลัง {max_retries} ครั้ง")
    return None


class ServerCopier(commands.Cog):
    """Cog for copying server structures (Channels, Categories, Roles)"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ──────────────────────────────────────────
    #  Main command
    # ──────────────────────────────────────────

    @commands.command(name="copy_here")
    @commands.has_permissions(administrator=True)
    async def copy_server(self, ctx: commands.Context, source_id: int):
        """คัดลอกโครงสร้างจากเซิร์ฟเวอร์ต้นทาง (Roles, Categories, Channels)"""

        source_guild = self.bot.get_guild(source_id)
        current_guild = ctx.guild

        if not source_guild:
            return await ctx.send("❌ ไม่พบเซิร์ฟเวอร์ต้นทาง (ตรวจสอบว่าบอทอยู่ในเซิร์ฟเวอร์นั้นด้วย)")

        # ── Confirmation ──
        await ctx.send(
            f"🛡️ **โหมดเสถียร (Rate-limit Safe)**\n"
            f"ก๊อปปี้จาก: **{source_guild.name}** (`{source_guild.id}`)\n"
            f"ปลายทาง: **{current_guild.name}**\n\n"
            f"⚠️ ข้อมูลในเซิร์ฟเวอร์นี้จะถูกลบทั้งหมด\n"
            f"พิมพ์ `ยืนยัน` เพื่อดำเนินการต่อ (30 วินาที)"
        )

        def check(m: discord.Message) -> bool:
            return m.author == ctx.author and m.channel == ctx.channel and m.content == "ยืนยัน"

        try:
            await self.bot.wait_for("message", check=check, timeout=30.0)
        except asyncio.TimeoutError:
            return await ctx.send("❌ ยกเลิก — หมดเวลายืนยัน")

        # ── Status channel ──
        status_channel = await safe_api(
            current_guild.create_text_channel(name="⏳-สถานะการก๊อปปี้"),
            label="create_status_channel",
        )
        if not status_channel:
            return await ctx.send("❌ ไม่สามารถสร้างช่องสถานะได้")

        status_msg = await status_channel.send("🚀 **เริ่มกระบวนการก๊อปปี้...**")

        async def update_status(text: str):
            if self.bot.is_closed():
                return
            try:
                await status_msg.edit(content=f"⚙️ **สถานะล่าสุด:** {text}")
            except Exception:
                pass

        # ── 1. ล้างข้อมูลเก่า ──
        await update_status("กำลังลบช่องทางเดิมทั้งหมด...")
        logger.info("Cleanup: deleting old channels...")
        for ch in list(current_guild.channels):
            if ch.id != status_channel.id:
                await safe_api(ch.delete(), label=f"delete_channel:{ch.name}")
                await asyncio.sleep(0.3)

        await update_status("กำลังลบยศเดิมทั้งหมด...")
        logger.info("Cleanup: deleting old roles...")
        deletable_roles = [
            r for r in current_guild.roles
            if not r.is_default() and not r.managed and r < current_guild.me.top_role
        ]
        for r in deletable_roles:
            await safe_api(r.delete(), label=f"delete_role:{r.name}")
            await asyncio.sleep(0.5)  # role delete ต้องการ delay มากกว่า channel

        # ── 2. อัปเดตข้อมูลเซิร์ฟเวอร์ ──
        await update_status("กำลังอัปเดตชื่อและไอคอนเซิร์ฟเวอร์...")
        icon_bytes = None
        if source_guild.icon:
            try:
                icon_bytes = await source_guild.icon.read()
            except Exception:
                logger.warning("ดาวน์โหลดไอคอนไม่ได้ — ข้ามขั้นตอนนี้")

        await safe_api(
            current_guild.edit(name=source_guild.name, icon=icon_bytes),
            label="edit_guild_metadata",
        )

        # ── 3. สร้างยศ (จุดหลักที่แก้) ──
        #
        # ปัญหาเดิม:
        #   - sleep(0.4) น้อยเกินสำหรับ role creation (limit ~5 roles / 5s)
        #   - ไม่ retry เมื่อโดน 429
        #   - edit_role_positions ยิงทีเดียวทั้งหมดทำให้ค้าง
        #
        # วิธีแก้:
        #   - ใช้ safe_api() ที่ retry เมื่อโดน 429 อัตโนมัติ
        #   - sleep(1.2) ต่อ role เพื่อไม่เกิน ~5 req/5s
        #   - จัด position ทีละก้อนเล็กๆ (batch) แทนทีเดียว
        # ─────────────────────────────────────────

        role_map: dict[int, discord.Role] = {}
        sorted_source_roles = sorted(source_guild.roles, key=lambda r: r.position, reverse=True)
        processable_roles = [r for r in sorted_source_roles if not r.is_default() and not r.managed]
        total_roles = len(processable_roles)

        logger.info(f"Creating {total_roles} roles...")
        await update_status(f"กำลังสร้างยศ 0/{total_roles}...")

        for idx, role in enumerate(processable_roles, 1):
            if self.bot.is_closed():
                return

            new_role = await safe_api(
                current_guild.create_role(
                    name=role.name,
                    permissions=role.permissions,
                    colour=role.colour,
                    hoist=role.hoist,
                    mentionable=role.mentionable,
                ),
                label=f"create_role:{role.name}",
            )

            if new_role:
                role_map[role.id] = new_role
                logger.info(f"  Role created: {role.name} ({idx}/{total_roles})")
            else:
                logger.warning(f"  Role skipped: {role.name} ({idx}/{total_roles})")

            if idx % 5 == 0 or idx == total_roles:
                await update_status(f"กำลังสร้างยศ {idx}/{total_roles}...")

            # 1.2s ต่อ role — ปลอดภัยสำหรับ global rate limit (5 req/5s)
            await asyncio.sleep(1.2)

        # ── จัด Role Position แบบ batch (10 ต่อรอบ) ──
        await update_status("กำลังจัดเรียงลำดับยศ...")
        logger.info("Re-ordering roles in batches...")

        # เรียงบทบาทจากล่างขึ้นบน (ascending) ตาม position ใน source guild
        manageable_roles = [
            r for r in sorted_source_roles
            if r.id in role_map and not r.is_default()
            and role_map[r.id] < current_guild.me.top_role
        ]
        manageable_roles.reverse()

        ordered = []
        max_pos = current_guild.me.top_role.position - 1
        for index, r in enumerate(manageable_roles):
            # ตำแหน่งใหม่เริ่มต้นที่ 1 (เพราะ @everyone คือ 0) และไม่เกินตำแหน่งสูงสุดของบอท
            new_pos = min(index + 1, max_pos)
            ordered.append((role_map[r.id], new_pos))

        # แบ่งเป็น batch ละ 10 คู่
        batch_size = 10
        for i in range(0, len(ordered), batch_size):
            batch = dict(ordered[i : i + batch_size])
            await safe_api(
                current_guild.edit_role_positions(positions=batch),
                label=f"edit_role_positions batch {i // batch_size + 1}",
            )
            await asyncio.sleep(1.5)  # หยุดรอระหว่าง batch

        # ── 4. สร้าง Categories + Channels ──
        logger.info("Creating categories and channels...")
        for category in sorted(source_guild.categories, key=lambda c: c.position):
            if self.bot.is_closed():
                return

            await update_status(f"🏗️ สร้างกลุ่มช่อง: {category.name}")

            cat_overwrites = {
                role_map[t.id]: ow
                for t, ow in category.overwrites.items()
                if isinstance(t, discord.Role) and t.id in role_map
            }
            new_cat = await safe_api(
                current_guild.create_category(
                    name=category.name,
                    overwrites=cat_overwrites,
                    position=category.position,
                ),
                label=f"create_category:{category.name}",
            )
            if not new_cat:
                continue

            await asyncio.sleep(0.5)

            for ch in sorted(category.channels, key=lambda c: c.position):
                if self.bot.is_closed():
                    return

                ch_ow = {
                    role_map[t.id]: ow
                    for t, ow in ch.overwrites.items()
                    if isinstance(t, discord.Role) and t.id in role_map
                }

                if isinstance(ch, discord.TextChannel):
                    await safe_api(
                        new_cat.create_text_channel(
                            name=ch.name,
                            topic=ch.topic,
                            slowmode_delay=ch.slowmode_delay,
                            nsfw=ch.nsfw,
                            overwrites=ch_ow,
                            position=ch.position,
                        ),
                        label=f"create_text:{ch.name}",
                    )
                elif isinstance(ch, discord.VoiceChannel):
                    await safe_api(
                        new_cat.create_voice_channel(
                            name=ch.name,
                            user_limit=ch.user_limit,
                            bitrate=min(ch.bitrate, current_guild.bitrate_limit),
                            overwrites=ch_ow,
                            position=ch.position,
                        ),
                        label=f"create_voice:{ch.name}",
                    )
                elif isinstance(ch, discord.ForumChannel):
                    await safe_api(
                        new_cat.create_forum(
                            name=ch.name,
                            topic=ch.topic,
                            overwrites=ch_ow,
                        ),
                        label=f"create_forum:{ch.name}",
                    )

                await asyncio.sleep(0.4)

        # ช่องที่ไม่อยู่ใน category
        for ch in sorted(source_guild.channels, key=lambda c: c.position):
            if self.bot.is_closed():
                return
            if ch.category is not None or ch.id == status_channel.id:
                continue

            ch_ow = {
                role_map[t.id]: ow
                for t, ow in ch.overwrites.items()
                if isinstance(t, discord.Role) and t.id in role_map
            }

            if isinstance(ch, discord.TextChannel):
                await safe_api(
                    current_guild.create_text_channel(
                        name=ch.name, topic=ch.topic, overwrites=ch_ow, position=ch.position
                    ),
                    label=f"create_text_nocat:{ch.name}",
                )
            elif isinstance(ch, discord.VoiceChannel):
                await safe_api(
                    current_guild.create_voice_channel(
                        name=ch.name, overwrites=ch_ow, position=ch.position
                    ),
                    label=f"create_voice_nocat:{ch.name}",
                )

            await asyncio.sleep(0.4)

        # ── 5. Sync Roles ให้สมาชิก ──
        await update_status("🎁 กำลังมอบยศคืนให้สมาชิก...")
        sync_count = 0
        synced_members = 0

        for member in current_guild.members:
            if self.bot.is_closed():
                break
            if member.bot:
                continue

            source_member = source_guild.get_member(member.id)
            if not source_member:
                continue

            roles_to_add = [
                role_map[r.id]
                for r in source_member.roles
                if r.id in role_map
                and not r.is_default()
                and not r.managed
                and role_map[r.id] < current_guild.me.top_role
            ]

            if roles_to_add:
                result = await safe_api(
                    member.add_roles(*roles_to_add, reason="Server clone sync"),
                    label=f"add_roles:{member.name}",
                )
                if result is not False:
                    sync_count += len(roles_to_add)
                    synced_members += 1

            # ทุก 5 คน หยุดพัก 1 วินาที ป้องกัน rate limit
            if synced_members % 5 == 0 and synced_members > 0:
                await asyncio.sleep(1.0)

        # ── 6. สรุปผล ──
        summary = (
            f"✅ **Clone Complete!**\n"
            f"ต้นทาง: **{source_guild.name}** (`{source_guild.id}`)\n"
            f"ยศที่สร้าง: `{len(role_map)}/{total_roles}`\n"
            f"สมาชิกที่ sync: `{synced_members}` คน ({sync_count} role assignments)\n"
        )

        await update_status("✅ เสร็จสิ้นสมบูรณ์!")
        logger.info(f"Clone complete: {source_guild.name} → {current_guild.name}")

        try:
            await ctx.author.send(summary)
        except discord.Forbidden:
            pass

        await asyncio.sleep(15)
        try:
            await status_channel.delete()
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerCopier(bot))