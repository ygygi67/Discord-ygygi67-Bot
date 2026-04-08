import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
import asyncio
import re
import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from collections import deque

logger = logging.getLogger("discord_bot")
MAX_BOARD_USERS = 1000
ACTIVITY_RETENTION_DAYS = 40

class RobloxAddUsersModal(discord.ui.Modal, title="➕ เพิ่มชื่อ/ID Roblox"):
    users_text = discord.ui.TextInput(
        label="รายชื่อหรือ ID",
        style=discord.TextStyle.paragraph,
        placeholder="เช่น Builderman, 261, 156, noobmaster",
        required=True,
        max_length=1500
    )

    def __init__(self, view: "RobloxPresenceBoardView"):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        if not await self.view._check_owner(interaction):
            return
        await interaction.response.defer()
        self.view.last_action = "เพิ่มรายชื่อเอง"
        added, unresolved = await self.view.add_users_from_text(str(self.users_text))
        await self.view.refresh_message()
        msg = f"✅ เพิ่มแล้ว {added} คน"
        if unresolved:
            msg += f"\n⚠️ แปลงไม่ได้: {', '.join(unresolved[:10])}"
        await interaction.followup.send(msg, ephemeral=True)


class RobloxFetchFriendsModal(discord.ui.Modal, title="👥 ดึงเพื่อนจาก Roblox ID/Name"):
    owner_text = discord.ui.TextInput(
        label="ID หรือชื่อ Roblox เจ้าของรายชื่อเพื่อน",
        placeholder="เช่น 261 หรือ Builderman",
        required=True,
        max_length=100
    )
    limit_text = discord.ui.TextInput(
        label="จำนวนเพื่อนสูงสุด (1-1000)",
        placeholder="100",
        required=False,
        max_length=4
    )

    def __init__(self, view: "RobloxPresenceBoardView"):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        if not await self.view._check_owner(interaction):
            return
        await interaction.response.defer()
        raw = str(self.owner_text).strip()
        limit_raw = str(self.limit_text).strip() or "30"
        try:
            limit = max(1, min(MAX_BOARD_USERS, int(limit_raw)))
        except Exception:
            limit = 100
        self.view.last_action = f"ดึงเพื่อนจาก {raw}"
        added = await self.view.add_friends_of(raw, limit)
        await self.view.refresh_message()
        msg = f"✅ ดึงเพื่อนเพิ่มแล้ว {added} คน"
        note = self.view.cog.last_friend_fetch_note
        if note:
            msg += f"\n⚠️ {note}"
        await interaction.followup.send(msg, ephemeral=True)


class RobloxPresenceBoardView(discord.ui.View):
    def __init__(self, cog: "FollowersCog", owner_id: int, user_ids: List[str], sort_by: str = "name", auto_update: bool = True):
        super().__init__(timeout=None)
        self.cog = cog
        self.owner_id = owner_id
        self.user_ids = user_ids
        self.sort_by = sort_by
        self.sort_desc = False
        self.auto_update = auto_update
        self.message: Optional[discord.Message] = None
        self.auto_task: Optional[asyncio.Task] = None
        self.interval_sec = 45
        self.page = 0
        self.page_size = 15
        self.total_pages = 1
        self.total_rows = 0
        self.last_action = "เริ่มต้น"
        self._update_button_labels()

    def _update_button_labels(self):
        self.btn_sort_name.style = discord.ButtonStyle.success if self.sort_by == "name" else discord.ButtonStyle.secondary
        self.btn_sort_latest.style = discord.ButtonStyle.success if self.sort_by == "latest" else discord.ButtonStyle.secondary
        self.btn_sort_game.style = discord.ButtonStyle.success if self.sort_by == "game" else discord.ButtonStyle.secondary
        self.btn_toggle_auto.label = "⏸️ หยุดอัปเดตอัตโนมัติ" if self.auto_update else "▶️ อัปเดตต่ออัตโนมัติ"
        self.btn_sort_order.label = "🔽 Z→A/ใหม่→เก่า" if self.sort_desc else "🔼 A→Z/เก่า→ใหม่"
        self.btn_page.label = f"หน้า {self.page + 1}/{max(1, self.total_pages)}"
        self.btn_first.disabled = self.page <= 0
        self.btn_prev.disabled = self.page <= 0
        self.btn_next.disabled = self.page >= max(0, self.total_pages - 1)
        self.btn_jump_back_5.disabled = self.page <= 0
        self.btn_jump_back_10.disabled = self.page <= 0
        self.btn_jump_forward_5.disabled = self.page >= max(0, self.total_pages - 1)
        self.btn_jump_forward_10.disabled = self.page >= max(0, self.total_pages - 1)
        self.btn_last.disabled = self.page >= max(0, self.total_pages - 1)

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if not self.owner_id:
            return True
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ แผงนี้สำหรับคนที่เรียกคำสั่งเท่านั้น", ephemeral=True)
            return False
        return True

    async def refresh_message(self):
        if not self.message:
            return
        embed, total_pages, total_rows = await self.cog.build_presence_board_embed(
            self.user_ids, self.sort_by, page=self.page, page_size=self.page_size, sort_desc=self.sort_desc, action=self.last_action
        )
        self.total_pages = total_pages
        self.total_rows = total_rows
        if self.page >= self.total_pages:
            self.page = max(0, self.total_pages - 1)
            embed, self.total_pages, self.total_rows = await self.cog.build_presence_board_embed(
                self.user_ids, self.sort_by, page=self.page, page_size=self.page_size, sort_desc=self.sort_desc, action=self.last_action
            )
        self._update_button_labels()
        await self.message.edit(embed=embed, view=self)
        self.cog.upsert_presence_board(
            guild_id=getattr(self.message.guild, "id", None),
            channel_id=self.message.channel.id,
            message_id=self.message.id,
            owner_id=self.owner_id,
            user_ids=self.user_ids,
            sort_by=self.sort_by,
            sort_desc=self.sort_desc,
            page=self.page,
            page_size=self.page_size,
            auto_update=self.auto_update,
        )
        logger.info(f"[RobloxBoard] refreshed owner={self.owner_id} users={len(self.user_ids)} page={self.page+1}/{self.total_pages} sort={self.sort_by}")

    async def add_users_from_text(self, raw_text: str) -> Tuple[int, List[str]]:
        tokens = [x.strip() for x in re.split(r"[,\n\r\t ]+", raw_text or "") if x.strip()]
        tokens = tokens[:MAX_BOARD_USERS]
        unresolved: List[str] = []
        added = 0
        async with aiohttp.ClientSession() as session:
            for token in tokens:
                uid = await self.cog.resolve_user_input(session, token)
                if not uid:
                    unresolved.append(token)
                    continue
                uid = str(uid)
                if uid not in self.user_ids:
                    if len(self.user_ids) < MAX_BOARD_USERS:
                        self.user_ids.append(uid)
                    else:
                        unresolved.append(token)
                        continue
                    added += 1
        return added, unresolved

    async def add_friends_of(self, owner_input: str, limit: int = 30) -> int:
        async with aiohttp.ClientSession() as session:
            owner_id = await self.cog.resolve_user_input(session, owner_input)
            if not owner_id:
                return 0
            friend_ids = await self.cog.get_friend_ids(session, str(owner_id), limit=limit)
        added = 0
        for fid in friend_ids:
            if len(self.user_ids) >= MAX_BOARD_USERS:
                break
            if fid not in self.user_ids:
                self.user_ids.append(fid)
                added += 1
        return added

    async def _auto_loop(self):
        while self.auto_update and self.message:
            await asyncio.sleep(self.interval_sec)
            if not self.auto_update or not self.message:
                break
            try:
                await self.refresh_message()
            except Exception:
                break

    def start_auto(self):
        if self.auto_update and (self.auto_task is None or self.auto_task.done()):
            self.auto_task = asyncio.create_task(self._auto_loop())

    def stop_auto(self):
        self.auto_update = False
        if self.auto_task and not self.auto_task.done():
            self.auto_task.cancel()
        self.auto_task = None

    async def on_timeout(self):
        # หมดเวลาเฉพาะปุ่มกด แต่ยังคงสถานะ auto-update ใน config ไว้
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="🔄 รีเฟรช", style=discord.ButtonStyle.primary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.last_action = "รีเฟรชข้อมูล"
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="↕️ ชื่อ", style=discord.ButtonStyle.success, row=3)
    async def btn_sort_name(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.sort_by = "name"
        self.last_action = "เรียงตามชื่อ"
        self._update_button_labels()
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="🕒 ล่าสุด", style=discord.ButtonStyle.secondary, row=3)
    async def btn_sort_latest(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.sort_by = "latest"
        self.last_action = "เรียงตามออนไลน์ล่าสุด"
        self._update_button_labels()
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="🎮 เวลาเล่น", style=discord.ButtonStyle.secondary, row=3)
    async def btn_sort_game(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.sort_by = "game"
        self.last_action = "เรียงตามเวลาเล่นเกม"
        self._update_button_labels()
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="🔼 A→Z/เก่า→ใหม่", style=discord.ButtonStyle.secondary, row=3)
    async def btn_sort_order(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.sort_desc = not self.sort_desc
        self.last_action = "สลับทิศทางการเรียง"
        self._update_button_labels()
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="⏸️ หยุดอัปเดตอัตโนมัติ", style=discord.ButtonStyle.secondary, row=1)
    async def btn_toggle_auto(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.auto_update = not self.auto_update
        self.last_action = "เปิด/ปิดอัปเดตอัตโนมัติ"
        self._update_button_labels()
        if self.auto_update:
            self.start_auto()
        else:
            self.stop_auto()
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="หน้าแรก", style=discord.ButtonStyle.secondary, row=0)
    async def btn_first(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.page = 0
        self.last_action = "ไปหน้าแรก"
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="⬅️ ก่อนหน้า", style=discord.ButtonStyle.secondary, row=0)
    async def btn_prev(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        if self.page > 0:
            self.page -= 1
        self.last_action = "ย้อนไปหน้าก่อนหน้า"
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="หน้า 1/1", style=discord.ButtonStyle.secondary, row=1, disabled=True)
    async def btn_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        await interaction.response.send_message("ℹ️ ใช้ปุ่ม ก่อนหน้า/ถัดไป เพื่อเปลี่ยนหน้า", ephemeral=True)

    @discord.ui.button(label="ถัดไป ➡️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_next(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        if self.page < self.total_pages - 1:
            self.page += 1
        self.last_action = "ไปหน้าถัดไป"
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="⏪ -10 หน้า", style=discord.ButtonStyle.secondary, row=2)
    async def btn_jump_back_10(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.page = max(0, self.page - 10)
        self.last_action = "ย้อน 10 หน้า"
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="⏮ -5 หน้า", style=discord.ButtonStyle.secondary, row=2)
    async def btn_jump_back_5(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.page = max(0, self.page - 5)
        self.last_action = "ย้อน 5 หน้า"
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="+5 หน้า ⏭", style=discord.ButtonStyle.secondary, row=2)
    async def btn_jump_forward_5(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.page = min(max(0, self.total_pages - 1), self.page + 5)
        self.last_action = "ข้ามไป 5 หน้า"
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="+10 หน้า ⏩", style=discord.ButtonStyle.secondary, row=2)
    async def btn_jump_forward_10(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.page = min(max(0, self.total_pages - 1), self.page + 10)
        self.last_action = "ข้ามไป 10 หน้า"
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="ไปหน้าสุดท้าย", style=discord.ButtonStyle.secondary, row=0)
    async def btn_last(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.page = max(0, self.total_pages - 1)
        self.last_action = "ไปหน้าสุดท้าย"
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="➕ เพิ่มชื่อ/ID", style=discord.ButtonStyle.success, row=4)
    async def btn_add_users(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        await interaction.response.send_modal(RobloxAddUsersModal(self))

    @discord.ui.button(label="👥 ดึงเพื่อน", style=discord.ButtonStyle.primary, row=4)
    async def btn_add_friends(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        await interaction.response.send_modal(RobloxFetchFriendsModal(self))

    @discord.ui.button(label="🛑 ปิดแผง", style=discord.ButtonStyle.danger, row=4)
    async def btn_stop(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.stop_auto()
        self.cog.upsert_presence_board(
            guild_id=getattr(interaction.guild, "id", None),
            channel_id=interaction.channel_id,
            message_id=interaction.message.id if interaction.message else 0,
            owner_id=self.owner_id,
            user_ids=self.user_ids,
            sort_by=self.sort_by,
            sort_desc=self.sort_desc,
            page=self.page,
            page_size=self.page_size,
            auto_update=False,
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.defer()
        await self.refresh_message()

class FollowersCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.default_target = "4401534231"
        self.presence_map = {
            0: "🔴 Offline",
            1: "🟢 Online", 
            2: "🎮 กำลังเล่นเกม",
            3: "🛠️ อยู่ใน Studio"
        }
        self.tracking_file = 'data/roblox_tracking.json'
        self.presence_cache_file = 'data/roblox_presence_cache.json'
        self.presence_boards_file = 'data/roblox_presence_boards.json'
        self.activity_file = 'data/roblox_activity_history.json'
        self.tracked_users = self.load_tracking_data() # {roblox_id: [channel_id, ...]}
        self.last_presence = {} # {roblox_id: last_presence_type}
        self.game_started_at: Dict[str, float] = {}
        self.game_total_seconds: Dict[str, float] = {}
        self.last_online_ts: Dict[str, float] = {}
        self.presence_cache = self.load_presence_cache()
        self.presence_boards = self.load_presence_boards()
        self.activity_data = self.load_activity_data()
        self.activity_dirty = False
        self.last_friend_fetch_note = ""
        
        # เริ่ม Task ตรวจสอบสถานะ
        self.check_presence_task.start()
        self.refresh_presence_boards_task.start()

    def load_tracking_data(self):
        """โหลดข้อมูลการติดตามจากไฟล์"""
        try:
            if os.path.exists(self.tracking_file):
                with open(self.tracking_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading tracking data: {e}")
        return {}

    def save_tracking_data(self):
        """บันทึกข้อมูลการติดตามลงไฟล์"""
        try:
            os.makedirs(os.path.dirname(self.tracking_file), exist_ok=True)
            with open(self.tracking_file, 'w', encoding='utf-8') as f:
                json.dump(self.tracked_users, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Error saving tracking data: {e}")

    def load_presence_cache(self) -> Dict[str, dict]:
        try:
            if os.path.exists(self.presence_cache_file):
                with open(self.presence_cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
        except Exception as e:
            logger.warning(f"[RobloxBoard] failed to load presence cache: {e}")
        return {}

    def save_presence_cache(self):
        try:
            os.makedirs(os.path.dirname(self.presence_cache_file), exist_ok=True)
            with open(self.presence_cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.presence_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[RobloxBoard] failed to save presence cache: {e}")

    def load_presence_boards(self) -> Dict[str, dict]:
        try:
            if os.path.exists(self.presence_boards_file):
                with open(self.presence_boards_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
        except Exception as e:
            logger.warning(f"[RobloxBoard] failed to load board config: {e}")
        return {}

    def save_presence_boards(self):
        try:
            os.makedirs(os.path.dirname(self.presence_boards_file), exist_ok=True)
            with open(self.presence_boards_file, 'w', encoding='utf-8') as f:
                json.dump(self.presence_boards, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[RobloxBoard] failed to save board config: {e}")

    def load_activity_data(self) -> Dict[str, dict]:
        try:
            if os.path.exists(self.activity_file):
                with open(self.activity_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
        except Exception as e:
            logger.warning(f"[RobloxActivity] failed to load activity data: {e}")
        return {}

    def save_activity_data(self):
        if not self.activity_dirty:
            return
        try:
            os.makedirs(os.path.dirname(self.activity_file), exist_ok=True)
            with open(self.activity_file, 'w', encoding='utf-8') as f:
                json.dump(self.activity_data, f, ensure_ascii=False, indent=2)
            self.activity_dirty = False
        except Exception as e:
            logger.warning(f"[RobloxActivity] failed to save activity data: {e}")

    def _record_activity_sample(
        self,
        user_id: str,
        status_type: int,
        location: str = "",
        display_name: str = "",
        username: str = "",
        sample_ts: Optional[float] = None,
        last_online_ts: Optional[float] = None
    ):
        uid = str(user_id)
        now_ts = float(sample_ts or datetime.now(timezone.utc).timestamp())
        entry = self.activity_data.get(uid)
        if not isinstance(entry, dict):
            entry = {"samples": []}

        if display_name:
            entry["display_name"] = display_name
        if username:
            entry["username"] = username
        if status_type > 0:
            entry["last_online_ts"] = now_ts
        if last_online_ts and last_online_ts > 0:
            entry["last_online_ts"] = max(float(entry.get("last_online_ts", 0.0)), float(last_online_ts))

        samples = entry.get("samples")
        if not isinstance(samples, list):
            samples = []
        keep_after = now_ts - ACTIVITY_RETENTION_DAYS * 86400
        samples = [s for s in samples if float(s.get("ts", 0.0) or 0.0) >= keep_after]

        last = samples[-1] if samples else None
        should_append = (
            last is None
            or int(last.get("status_type", -1)) != int(status_type)
            or str(last.get("location", "")) != str(location or "")
            or (now_ts - float(last.get("ts", 0.0) or 0.0)) >= 60
        )
        if should_append:
            samples.append({
                "ts": now_ts,
                "status_type": int(status_type),
                "location": str(location or "")[:120]
            })

        if len(samples) > 3500:
            samples = samples[-3500:]

        entry["samples"] = samples
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.activity_data[uid] = entry
        self.activity_dirty = True

    def _compute_activity_stats(self, user_id: str) -> dict:
        uid = str(user_id)
        entry = self.activity_data.get(uid) or {}
        samples = entry.get("samples", [])
        if not isinstance(samples, list):
            samples = []

        cleaned = []
        for s in samples:
            try:
                cleaned.append({
                    "ts": float(s.get("ts", 0.0)),
                    "status_type": int(s.get("status_type", 0)),
                    "location": str(s.get("location", "")),
                })
            except Exception:
                continue
        cleaned.sort(key=lambda x: x["ts"])

        now_ts = datetime.now(timezone.utc).timestamp()
        day_cut = now_ts - 86400
        week_cut = now_ts - (7 * 86400)
        month_cut = now_ts - (30 * 86400)
        totals = {"day": 0.0, "week": 0.0, "month": 0.0}
        hour_buckets: Dict[int, float] = {h: 0.0 for h in range(24)}
        sessions: List[Tuple[float, str]] = []

        prev_status = 0
        for idx, cur in enumerate(cleaned):
            cur_ts = cur["ts"]
            if cur["status_type"] == 2 and prev_status != 2:
                sessions.append((cur_ts, cur.get("location", "")))
            next_ts = cleaned[idx + 1]["ts"] if idx + 1 < len(cleaned) else now_ts
            if cur["status_type"] == 2 and next_ts > cur_ts:
                for key, cutoff in (("day", day_cut), ("week", week_cut), ("month", month_cut)):
                    start = max(cur_ts, cutoff)
                    end = min(next_ts, now_ts)
                    if end > start:
                        totals[key] += end - start
                start_hour = datetime.fromtimestamp(cur_ts, tz=timezone.utc).hour
                hour_buckets[start_hour] = hour_buckets.get(start_hour, 0.0) + max(0.0, next_ts - cur_ts)
            prev_status = cur["status_type"]

        sessions.sort(key=lambda x: x[0], reverse=True)
        top_hours = sorted(hour_buckets.items(), key=lambda kv: kv[1], reverse=True)
        top_hours = [(h, sec) for h, sec in top_hours if sec > 0][:3]
        return {
            "display_name": entry.get("display_name") or uid,
            "username": entry.get("username") or uid,
            "last_online_ts": float(entry.get("last_online_ts", 0.0) or 0.0),
            "totals": totals,
            "sample_count": len(cleaned),
            "recent_sessions": sessions[:6],
            "top_hours": top_hours,
        }

    def upsert_presence_board(
        self,
        guild_id: Optional[int],
        channel_id: int,
        message_id: int,
        owner_id: int,
        user_ids: List[str],
        sort_by: str,
        sort_desc: bool,
        page: int,
        page_size: int,
        auto_update: bool,
    ):
        if not channel_id or not message_id:
            return
        key = str(message_id)
        self.presence_boards[key] = {
            "guild_id": guild_id,
            "channel_id": channel_id,
            "message_id": message_id,
            "owner_id": owner_id,
            "user_ids": [str(x) for x in user_ids][:MAX_BOARD_USERS],
            "sort_by": sort_by,
            "sort_desc": bool(sort_desc),
            "page": int(max(0, page)),
            "page_size": int(max(5, min(25, page_size))),
            "auto_update": bool(auto_update),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.save_presence_boards()

    def cog_unload(self):
        self.check_presence_task.cancel()
        self.refresh_presence_boards_task.cancel()

    async def get_user_info(self, session, user_id):
        """ดึงข้อมูลผู้ใช้จาก Roblox API แบบ Asynchronous"""
        try:
            # ข้อมูลพื้นฐาน
            async with session.get(f"https://users.roblox.com/v1/users/{user_id}", timeout=10) as r:
                if r.status != 200:
                    return None
                user_data = await r.json()
            
            # ข้อมูลสถานะออนไลน์
            presence_url = "https://presence.roblox.com/v1/presence/users"
            async with session.post(presence_url, json={"userIds": [int(user_id)]}, timeout=10) as r:
                presence_data = {}
                if r.status == 200:
                    p_info = await r.json()
                    if p_info.get("userPresences"):
                        presence_data = p_info["userPresences"][0]
            
            # ข้อมูลเพื่อนและผู้ติดตาม (เรียกพร้อมกันเพื่อประหยัดเวลา)
            tasks = [
                session.get(f"https://friends.roblox.com/v1/users/{user_id}/friends/count"),
                session.get(f"https://friends.roblox.com/v1/users/{user_id}/followers/count"),
                session.get(f"https://friends.roblox.com/v1/users/{user_id}/followings/count"),
                session.get(f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png&isCircular=false")
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            friends_count = 0
            followers_count = 0
            followings_count = 0
            avatar_image_url = None
            
            if not isinstance(results[0], Exception) and results[0].status == 200:
                friends_count = (await results[0].json()).get("count", 0)
            if not isinstance(results[1], Exception) and results[1].status == 200:
                followers_count = (await results[1].json()).get("count", 0)
            if not isinstance(results[2], Exception) and results[2].status == 200:
                followings_count = (await results[2].json()).get("count", 0)
            if not isinstance(results[3], Exception) and results[3].status == 200:
                av_data = await results[3].json()
                if av_data.get("data"):
                    avatar_image_url = av_data["data"][0].get("imageUrl")
            
            return {
                "id": user_data.get("id"),
                "name": user_data.get("name"),
                "displayName": user_data.get("displayName"),
                "description": user_data.get("description", "ไม่มีคำอธิบาย"),
                "created": user_data.get("created"),
                "isBanned": user_data.get("isBanned", False),
                "hasVerifiedBadge": user_data.get("hasVerifiedBadge", False),
                "presence": presence_data.get("userPresenceType", 0),
                "lastLocation": presence_data.get("lastLocation", "ไม่ทราบ"),
                "friends": friends_count,
                "followers": followers_count,
                "followings": followings_count,
                "avatar_url": avatar_image_url
            }
        except Exception as e:
            print(f"Error getting user info: {e}")
            return None

    async def check_is_following(self, session, user_id, target_id):
        """ตรวจสอบว่า user_id กำลัง follow target_id หรือไม่"""
        url = f"https://friends.roblox.com/v1/users/{user_id}/followings?sortOrder=Asc&limit=100"
        try:
            while True:
                async with session.get(url, timeout=10) as r:
                    if r.status != 200:
                        return False
                    data = await r.json()
                    for user in data["data"]:
                        if str(user["id"]) == str(target_id):
                            return True
                    cursor = data.get("nextPageCursor")
                    if cursor:
                        url = f"https://friends.roblox.com/v1/users/{user_id}/followings?sortOrder=Asc&limit=100&cursor={cursor}"
                    else:
                        break
            return False
        except:
            return False

    async def get_user_id_by_name(self, session, username):
        """แปลงชื่อผู้ใช้ (Username) เป็น UserID"""
        url = "https://users.roblox.com/v1/usernames/users"
        try:
            async with session.post(url, json={"usernames": [username], "excludeBannedUsers": False}, timeout=10) as r:
                if r.status == 200:
                    data = await r.json()
                    if data.get("data") and len(data["data"]) > 0:
                        return str(data["data"][0].get("id"))
            return None
        except:
            return None

    async def get_friend_ids(self, session: aiohttp.ClientSession, user_id: str, limit: int = 30) -> List[str]:
        self.last_friend_fetch_note = ""
        ids: List[str] = []
        cursor = None
        seen_cursors = set()
        limit = max(1, min(MAX_BOARD_USERS, limit))
        expected_count = None
        try:
            async with session.get(f"https://friends.roblox.com/v1/users/{user_id}/friends/count", timeout=10) as rc:
                if rc.status == 200:
                    count_data = await rc.json()
                    expected_count = int(count_data.get("count", 0))
        except Exception:
            expected_count = None

        while len(ids) < limit:
            url = f"https://friends.roblox.com/v1/users/{user_id}/friends?sortOrder=Asc&limit=100"
            if cursor:
                url += f"&cursor={cursor}"
            try:
                async with session.get(url, timeout=15) as r:
                    if r.status != 200:
                        logger.warning(f"[RobloxBoard] friends lookup failed: HTTP {r.status} for user={user_id}")
                        break
                    data = await r.json()
                    for item in data.get("data", []):
                        fid = str(item.get("id", "")).strip()
                        if fid.isdigit():
                            if fid not in ids:
                                ids.append(fid)
                            if len(ids) >= limit:
                                break
                    next_cursor = data.get("nextPageCursor")
                    if not next_cursor:
                        break
                    if next_cursor in seen_cursors:
                        break
                    seen_cursors.add(next_cursor)
                    cursor = next_cursor
                    if not cursor:
                        break
            except Exception:
                break
        if expected_count is not None and expected_count > len(ids):
            self.last_friend_fetch_note = (
                f"API ส่งรายชื่อได้ {len(ids)} จากจำนวนรวม {expected_count} "
                f"(บางบัญชี Roblox ถูกจำกัดผลลัพธ์ใน endpoint นี้)"
            )
        logger.info(f"[RobloxBoard] fetched friends user={user_id} count={len(ids)} requested={limit}")
        return ids

    async def get_paginated_relation_ids(
        self,
        session: aiohttp.ClientSession,
        url_base: str,
        limit: int = 1000,
    ) -> List[str]:
        ids: List[str] = []
        seen: set[str] = set()
        cursor = None
        limit = max(1, min(5000, limit))
        while len(ids) < limit:
            per_page = min(100, limit - len(ids))
            url = f"{url_base}?sortOrder=Asc&limit={per_page}"
            if cursor:
                url += f"&cursor={cursor}"
            try:
                async with session.get(url, timeout=20) as r:
                    if r.status != 200:
                        break
                    data = await r.json()
                    for item in data.get("data", []):
                        rid = str(item.get("id", "")).strip()
                        if rid.isdigit() and rid not in seen:
                            seen.add(rid)
                            ids.append(rid)
                            if len(ids) >= limit:
                                break
                    cursor = data.get("nextPageCursor")
                    if not cursor:
                        break
            except Exception:
                break
        return ids

    async def get_friends_set(self, session: aiohttp.ClientSession, user_id: str, limit: int = 1000) -> set[str]:
        ids = await self.get_paginated_relation_ids(
            session,
            f"https://friends.roblox.com/v1/users/{user_id}/friends",
            limit=limit
        )
        return set(ids)

    async def get_followers_set(self, session: aiohttp.ClientSession, user_id: str, limit: int = 1000) -> set[str]:
        ids = await self.get_paginated_relation_ids(
            session,
            f"https://friends.roblox.com/v1/users/{user_id}/followers",
            limit=limit
        )
        return set(ids)

    async def get_followings_set(self, session: aiohttp.ClientSession, user_id: str, limit: int = 1000) -> set[str]:
        ids = await self.get_paginated_relation_ids(
            session,
            f"https://friends.roblox.com/v1/users/{user_id}/followings",
            limit=limit
        )
        return set(ids)

    async def get_usernames_map(self, session: aiohttp.ClientSession, ids: List[str]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        chunks: List[List[int]] = []
        parsed = [int(x) for x in ids if str(x).isdigit()]
        for i in range(0, len(parsed), 100):
            chunks.append(parsed[i:i+100])
        for chunk in chunks:
            basic = await self.get_users_basic_batch(session, chunk)
            for uid, data in basic.items():
                username = data.get("name") or uid
                out[uid] = username
        return out

    async def find_friend_path(
        self,
        session: aiohttp.ClientSession,
        start_id: str,
        target_id: str,
        max_depth: int = 4,
        branch_limit: int = 120,
        node_limit: int = 1200,
    ) -> Optional[List[str]]:
        if start_id == target_id:
            return [start_id]

        queue = deque([(start_id, [start_id], 0)])
        visited = {start_id}
        expanded = 0

        while queue:
            current_id, path, depth = queue.popleft()
            if depth >= max_depth:
                continue
            if expanded >= node_limit:
                break

            neighbors = await self.get_paginated_relation_ids(
                session,
                f"https://friends.roblox.com/v1/users/{current_id}/friends",
                limit=branch_limit
            )
            expanded += 1
            for nxt in neighbors:
                if nxt == target_id:
                    return path + [nxt]
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, path + [nxt], depth + 1))
        return None

    async def resolve_user_input(self, session: aiohttp.ClientSession, raw: str) -> Optional[str]:
        raw = (raw or "").strip()
        if not raw:
            return None
        if raw.isdigit():
            return raw
        url_match = re.search(r"roblox\.com/users/(\d+)", raw, flags=re.IGNORECASE)
        if url_match:
            return url_match.group(1)
        return await self.get_user_id_by_name(session, raw)

    async def get_users_basic_batch(self, session: aiohttp.ClientSession, user_ids: List[int]) -> Dict[str, dict]:
        users: Dict[str, dict] = {}
        if not user_ids:
            return users
        for attempt in range(3):
            try:
                async with session.post(
                    "https://users.roblox.com/v1/users",
                    json={"userIds": user_ids, "excludeBannedUsers": False},
                    timeout=20
                ) as r:
                    if r.status == 200:
                        payload = await r.json()
                        for item in payload.get("data", []):
                            uid = str(item.get("id", "")).strip()
                            if uid:
                                users[uid] = item
                        return users
                    if r.status == 429:
                        await asyncio.sleep(0.8 * (attempt + 1))
                        continue
                    logger.warning(f"[RobloxBoard] users batch lookup failed: HTTP {r.status}")
                    return users
            except Exception as e:
                if attempt == 2:
                    logger.warning(f"[RobloxBoard] users batch lookup error: {e}")
                await asyncio.sleep(0.3 * (attempt + 1))
        return users

    async def get_presence_batch(self, session: aiohttp.ClientSession, user_ids: List[int]) -> Dict[str, dict]:
        result: Dict[str, dict] = {}
        if not user_ids:
            return result

        # Roblox presence endpoint sometimes returns 400/429 on bigger chunks
        chunk_size = 100
        for i in range(0, len(user_ids), chunk_size):
            chunk = user_ids[i:i + chunk_size]
            success = False
            for attempt in range(2):
                try:
                    async with session.post("https://presence.roblox.com/v1/presence/users", json={"userIds": chunk}, timeout=15) as r:
                        if r.status == 200:
                            payload = await r.json()
                            for p in payload.get("userPresences", []):
                                uid = str(p.get("userId"))
                                result[uid] = p
                            success = True
                            break
                        if r.status == 429:
                            await asyncio.sleep(0.8 * (attempt + 1))
                            continue
                        if r.status == 400 and len(chunk) > 25:
                            # fallback split half
                            mid = len(chunk) // 2
                            left = await self.get_presence_batch(session, chunk[:mid])
                            right = await self.get_presence_batch(session, chunk[mid:])
                            result.update(left)
                            result.update(right)
                            success = True
                            break
                        logger.warning(f"[RobloxBoard] presence lookup failed: HTTP {r.status} (chunk={len(chunk)})")
                        break
                except Exception as e:
                    if attempt == 1:
                        logger.warning(f"[RobloxBoard] presence lookup error: {e}")
                    await asyncio.sleep(0.3 * (attempt + 1))
            if not success:
                continue
        return result

    def _parse_time(self, iso_text: str) -> float:
        if not iso_text:
            return 0.0
        try:
            dt = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return 0.0

    def _game_duration_sec(self, user_id: str) -> float:
        now = datetime.now(timezone.utc).timestamp()
        total = self.game_total_seconds.get(user_id, 0.0)
        started = self.game_started_at.get(user_id)
        if started:
            total += max(0.0, now - started)
        return total

    def _format_duration(self, sec: float) -> str:
        sec = int(max(0, sec))
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    async def fetch_presence_rows(self, user_ids: List[str]) -> List[dict]:
        if not user_ids:
            return []
        rows: List[dict] = []
        async with aiohttp.ClientSession() as session:
            ids_int = [int(x) for x in user_ids if str(x).isdigit()]
            if not ids_int:
                return []
            presence_by_id = await self.get_presence_batch(session, ids_int)

            basic_by_id: Dict[str, dict] = {}
            for i in range(0, len(ids_int), 100):
                chunk = ids_int[i:i+100]
                basic_by_id.update(await self.get_users_basic_batch(session, chunk))

            for uid in [str(x) for x in ids_int]:
                basic = basic_by_id.get(uid, {})
                p = presence_by_id.get(uid, {})
                cached = self.presence_cache.get(uid, {})
                p_type = int(p.get("userPresenceType", self.last_presence.get(uid, cached.get("status_type", 0))) or 0)
                location = str(p.get("lastLocation") or "")
                last_online_iso = p.get("lastOnline") or ""
                last_online_ts = self._parse_time(last_online_iso)
                if p_type > 0:
                    self.last_online_ts[uid] = datetime.now(timezone.utc).timestamp()
                elif last_online_ts > 0:
                    self.last_online_ts[uid] = last_online_ts
                elif cached.get("last_online_ts"):
                    self.last_online_ts[uid] = float(cached.get("last_online_ts", 0.0))
                self.last_presence[uid] = p_type

                if p_type == 2:
                    if uid not in self.game_started_at:
                        self.game_started_at[uid] = datetime.now(timezone.utc).timestamp()
                else:
                    if uid in self.game_started_at:
                        start = self.game_started_at.pop(uid)
                        self.game_total_seconds[uid] = self.game_total_seconds.get(uid, 0.0) + max(0.0, datetime.now(timezone.utc).timestamp() - start)

                display_name = basic.get("displayName") or cached.get("display_name") or uid
                username = basic.get("name") or cached.get("username") or uid
                user_id_text = str(basic.get("id") or cached.get("user_id") or uid)
                status_text = self.presence_map.get(p_type, cached.get("status_text", "❓ ไม่ทราบ"))
                last_ts = self.last_online_ts.get(uid, 0.0)
                game_sec = self._game_duration_sec(uid)

                self.presence_cache[uid] = {
                    "display_name": display_name,
                    "username": username,
                    "user_id": user_id_text,
                    "status_type": p_type,
                    "status_text": status_text,
                    "last_online_ts": last_ts,
                    "game_duration_sec": game_sec,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                self._record_activity_sample(
                    user_id=uid,
                    status_type=p_type,
                    location=location,
                    display_name=display_name,
                    username=username,
                    last_online_ts=last_ts
                )

                rows.append({
                    "display_name": display_name,
                    "username": username,
                    "user_id": user_id_text,
                    "status_text": status_text,
                    "status_type": p_type,
                    "last_online_ts": last_ts,
                    "game_duration_sec": game_sec,
                })
        self.save_presence_cache()
        self.save_activity_data()
        return rows

    async def build_presence_board_embed(
        self,
        user_ids: List[str],
        sort_by: str = "name",
        page: int = 0,
        page_size: int = 15,
        sort_desc: bool = False,
        action: str = "รีเฟรชข้อมูล"
    ) -> Tuple[discord.Embed, int, int]:
        rows = await self.fetch_presence_rows(user_ids)

        if sort_by == "latest":
            rows.sort(key=lambda x: (x["last_online_ts"], x["display_name"].lower()), reverse=sort_desc)
        elif sort_by == "game":
            rows.sort(key=lambda x: (x["game_duration_sec"], x["display_name"].lower()), reverse=sort_desc)
        else:
            rows.sort(key=lambda x: x["display_name"].lower(), reverse=sort_desc)

        total_rows = len(rows)
        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        page = max(0, min(page, total_pages - 1))
        start = page * page_size
        end = start + page_size
        page_rows = rows[start:end]

        lines = ["`Name                @Username          UserID        Status            LastSeen        GameTime`"]
        for r in page_rows:
            name = (r["display_name"][:18]).ljust(18)
            uname = ("@" + r["username"][:15]).ljust(18)
            uid = r["user_id"][:12].ljust(12)
            status = r["status_text"][:16].ljust(16)
            last_seen = datetime.fromtimestamp(r["last_online_ts"], tz=timezone.utc).strftime("%H:%M:%S") if r["last_online_ts"] else "--:--:--"
            game_time = self._format_duration(r["game_duration_sec"])
            lines.append(f"`{name}{uname}{uid}{status}{last_seen:<16}{game_time}`")

        desc = "\n".join(lines)
        if len(desc) > 3900:
            desc = desc[:3900] + "\n`... (truncated)`"

        embed = discord.Embed(
            title="📊 Roblox Presence Board",
            description=desc if rows else "ไม่พบข้อมูลผู้ใช้ Roblox ที่ระบุ",
            color=discord.Color.blurple(),
            timestamp=datetime.now()
        )
        sort_label = {
            "name": "ชื่อ",
            "latest": "ออนไลน์ล่าสุด",
            "game": "เวลาเล่น",
        }.get(sort_by, sort_by)
        direction = "มาก→น้อย" if sort_desc else "น้อย→มาก"
        online_count = sum(1 for r in rows if r.get("status_type", 0) > 0)
        embed.set_footer(
            text=f"รวม {len(rows)} คน (ออนไลน์ {online_count}) | กำลังเรียง: {sort_label} ({direction}) | หน้า {page + 1}/{total_pages} | โหมด: {action}"
        )
        return embed, total_pages, total_rows

    @app_commands.command(name="เช็คโปรไฟล์roblox", description="ตรวจสอบข้อมูลโปรไฟล์ Roblox และสถานะการติดตาม")
    @app_commands.describe(user_id="ID, ชื่อผู้ใช้ หรือลิงก์โปรไฟล์ Roblox", target_id="ID ที่ต้องการตรวจสอบว่าฟอลอยู่ไหม (ค่าเริ่มต้น: ID แอดมิน)")
    async def check_roblox(self, interaction: discord.Interaction, user_id: str, target_id: str = None):
        await interaction.response.defer()
        
        real_user_id = None
        
        # 1. ลองหาตัวเลข ID จาก input (รองรับลิงก์โปรไฟล์)
        match = re.search(r"(\d{7,})", user_id)
        if match:
            real_user_id = match.group(1)
        else:
            # 2. ถ้าไม่มีตัวเลข ให้ลองค้นหาด้วยชื่อผู้ใช้
            async with aiohttp.ClientSession() as session:
                real_user_id = await self.get_user_id_by_name(session, user_id)
        
        if not real_user_id:
            return await interaction.followup.send(f"❌ ไม่พบรหัสผู้ใช้หรือชื่อผู้ใช้: `{user_id}`", ephemeral=True)
        
        target = target_id or self.default_target
        
        async with aiohttp.ClientSession() as session:
            # ดึงข้อมูลพร้อมกัน
            info_task = self.get_user_info(session, real_user_id)
            follow_task = self.check_is_following(session, real_user_id, target)
            
            user_info, is_follow = await asyncio.gather(info_task, follow_task)
            
            if not user_info:
                return await interaction.followup.send(f"❌ ไม่พบข้อมูลผู้ใช้ ID: `{real_user_id}` (อาจจะเป็น ID ปลอมหรือมีปัญหาที่ API)")
            
            # สร้าง Embed
            status_text = "✅ **กำลัง Follow**" if is_follow else "❌ **ไม่ได้ Follow**"
            color = discord.Color.green() if is_follow else discord.Color.red()
            
            presence_status = self.presence_map.get(user_info["presence"], "❓ ไม่ทราบ")
            
            # จัดการวันที่สร้าง
            try:
                created_date = datetime.fromisoformat(user_info["created"].replace("Z", "+00:00"))
                created_str = f"{discord.utils.format_dt(created_date, 'F')} ({discord.utils.format_dt(created_date, 'R')})"
            except:
                created_str = user_info["created"]

            embed = discord.Embed(
                title=f"👤 ข้อมูลโปรไฟล์: {user_info['displayName']}",
                url=f"https://www.roblox.com/users/{real_user_id}/profile",
                color=color,
                timestamp=datetime.now()
            )
            
            embed.add_field(name="📌 สถานะการติดตาม", value=f"{status_text} ต่อ ID: `{target}`", inline=False)
            
            embed.add_field(name="🆔 User ID", value=f"`{user_info['id']}`", inline=True)
            embed.add_field(name="🏷️ Username", value=f"@{user_info['name']}", inline=True)
            embed.add_field(name="🌐 สถานะออนไลน์", value=presence_status, inline=True)
            
            embed.add_field(name="👥 เพื่อน", value=f"{user_info['friends']:,} คน", inline=True)
            embed.add_field(name="📢 ผู้ติดตาม", value=f"{user_info['followers']:,} คน", inline=True)
            embed.add_field(name="➕ กำลังติดตาม", value=f"{user_info['followings']:,} คน", inline=True)
            
            embed.add_field(name="📅 สร้างบัญชีเมื่อ", value=created_str, inline=False)
            
            if user_info["description"] and user_info["description"] != "":
                desc = user_info["description"]
                if len(desc) > 200: desc = desc[:197] + "..."
                embed.add_field(name="📝 คำอธิบายโปรไฟล์", value=f"```{desc}```", inline=False)
            
            badges = []
            if user_info["isBanned"]: badges.append("🚫 **BANNED**")
            if user_info["hasVerifiedBadge"]: badges.append("✅ **VERIFIED**")
            if badges:
                embed.add_field(name="⚠️ เครื่องหมาย", value=" | ".join(badges), inline=False)
                
            if user_info["avatar_url"]:
                embed.set_thumbnail(url=user_info["avatar_url"])
            
            embed.set_footer(text=f"Requested by {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
            
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="กิจกรรมโปรไฟล์roblox", description="สรุปการออนไลน์และเวลาเล่น Roblox จากข้อมูลติดตาม")
    @app_commands.describe(user="ID/ชื่อ/ลิงก์ Roblox ที่ต้องการดู", auto_track="ถ้ายังไม่มีในฐานข้อมูล ให้เริ่มติดตามอัตโนมัติ")
    async def roblox_activity_profile(self, interaction: discord.Interaction, user: str, auto_track: bool = True):
        await interaction.response.defer()
        async with aiohttp.ClientSession() as session:
            user_id = await self.resolve_user_input(session, user)
            if not user_id:
                return await interaction.followup.send(f"❌ ไม่สามารถแปลงผู้ใช้ `{user}` เป็น Roblox ID ได้")
            basic = await self.get_users_basic_batch(session, [int(user_id)])
            presence = await self.get_presence_batch(session, [int(user_id)])

        p = presence.get(str(user_id), {})
        basic_user = basic.get(str(user_id), {})
        p_type = int(p.get("userPresenceType", 0) or 0)
        last_online_ts = self._parse_time(str(p.get("lastOnline") or ""))
        self._record_activity_sample(
            user_id=str(user_id),
            status_type=p_type,
            location=str(p.get("lastLocation") or ""),
            display_name=str(basic_user.get("displayName") or ""),
            username=str(basic_user.get("name") or ""),
            last_online_ts=last_online_ts
        )
        self.save_activity_data()

        stats = self._compute_activity_stats(str(user_id))
        auto_track_note = ""
        if auto_track and stats.get("sample_count", 0) <= 1:
            rid_str = str(user_id)
            cid_str = str(interaction.channel_id)
            channels = self.tracked_users.setdefault(rid_str, [])
            if cid_str not in channels:
                channels.append(cid_str)
                self.save_tracking_data()
                auto_track_note = "ยังไม่มีข้อมูลสะสมมากพอ ระบบเริ่มเพิ่มผู้ใช้นี้เข้ารายการติดตามในช่องนี้แล้ว ✅"

        totals = stats.get("totals", {})
        day_h = totals.get("day", 0.0) / 3600
        week_h = totals.get("week", 0.0) / 3600
        month_h = totals.get("month", 0.0) / 3600
        last_ts = float(stats.get("last_online_ts", 0.0) or 0.0)
        last_online = datetime.fromtimestamp(last_ts, tz=timezone.utc) if last_ts > 0 else None

        embed = discord.Embed(
            title="📈 Roblox Activity Profile",
            color=discord.Color.blurple(),
            timestamp=datetime.now()
        )
        display_name = stats.get("display_name", str(user_id))
        username = stats.get("username", str(user_id))
        embed.add_field(name="ผู้ใช้", value=f"{display_name} (@{username})\n`{user_id}`", inline=False)
        if last_online:
            absolute_ts = discord.utils.format_dt(last_online, "F")
            relative_ts = discord.utils.format_dt(last_online, "R")
            last_online_value = f"{absolute_ts}\n({relative_ts})"
        else:
            last_online_value = "ยังไม่มีข้อมูล"
        embed.add_field(name="ออนไลน์ล่าสุด", value=last_online_value, inline=False)
        embed.add_field(name="เวลาเล่น 1 วัน", value=f"`{day_h:.2f}` ชั่วโมง", inline=True)
        embed.add_field(name="เวลาเล่น 1 สัปดาห์", value=f"`{week_h:.2f}` ชั่วโมง", inline=True)
        embed.add_field(name="เวลาเล่น 1 เดือน", value=f"`{month_h:.2f}` ชั่วโมง", inline=True)

        top_hours = stats.get("top_hours", [])
        if top_hours:
            hour_text = "\n".join(f"- {h:02d}:00 UTC ~ {sec/3600:.2f} ชม." for h, sec in top_hours)
        else:
            hour_text = "ยังไม่มีข้อมูลเวลาเล่นเกมเพียงพอ"
        embed.add_field(name="เล่นช่วงเวลาไหนบ่อย", value=hour_text[:1024], inline=False)

        sessions = stats.get("recent_sessions", [])
        if sessions:
            session_lines = []
            for ts, location in sessions[:5]:
                dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                location_text = f" • {location}" if location else ""
                session_lines.append(f"- {discord.utils.format_dt(dt, 'R')}{location_text}")
            embed.add_field(name="เข้าเล่นเกมล่าสุด", value="\n".join(session_lines)[:1024], inline=False)

        footer = f"เก็บตัวอย่างแล้ว {stats.get('sample_count', 0)} จุด"
        if auto_track_note:
            footer += " • เปิดติดตามอัตโนมัติแล้ว"
            embed.add_field(name="ℹ️ ระบบติดตาม", value=auto_track_note, inline=False)
        embed.set_footer(text=footer)
        await interaction.followup.send(embed=embed)

    # --- ระบบติดตามสถานะ ---

    @tasks.loop(seconds=45) # ตรวจสอบทุก 45 วินาที
    async def check_presence_task(self):
        if not self.tracked_users:
            return
            
        try:
            async with aiohttp.ClientSession() as session:
                # แปลงรหัสคนทั้งหมดเป็น List และใช้ helper ที่มี retry/backoff + split chunk อัตโนมัติ
                ids = [int(rid) for rid in self.tracked_users.keys() if str(rid).isdigit()]
                if not ids:
                    return

                presence_map = await self.get_presence_batch(session, ids)
                if not presence_map:
                    logger.warning("[PresenceTask] empty presence response (possibly rate-limited)")
                    return

                for rid_int in ids:
                    rid = str(rid_int)
                    p = presence_map.get(rid, {})
                    ptype = int(p.get("userPresenceType", 0) or 0)
                    location = str(p.get("lastLocation", "ไม่ทราบ"))
                    last_online_ts = self._parse_time(str(p.get("lastOnline") or ""))
                    self._record_activity_sample(
                        user_id=rid,
                        status_type=ptype,
                        location=location,
                        last_online_ts=last_online_ts
                    )

                    # ตรวจสอบว่ามีข้อมูลการเปลี่ยนแปลงไหม
                    if rid in self.last_presence and self.last_presence[rid] != ptype:
                        await self.notify_presence_change(rid, ptype, location)

                    # อัปเดตสถานะล่าสุด
                    self.last_presence[rid] = ptype

                self.save_activity_data()
        except aiohttp.ClientConnectionError:
            # มักเกิดตอนกำลัง restart/shutdown connector
            logger.info("[PresenceTask] connector closed during restart/shutdown")
        except asyncio.CancelledError:
            # task ถูกยกเลิกตอน unload ปกติ
            return
        except Exception as e:
            logger.warning(f"[PresenceTask] error: {e}")

    @tasks.loop(seconds=45)
    async def refresh_presence_boards_task(self):
        if not self.presence_boards:
            return
        changed = False
        remove_keys: List[str] = []
        for key, cfg in list(self.presence_boards.items()):
            auto_update = bool(cfg.get("auto_update", True))
            if not auto_update and cfg.get("rehydrated", False):
                continue
            channel_id = int(cfg.get("channel_id", 0) or 0)
            message_id = int(cfg.get("message_id", 0) or 0)
            if not channel_id:
                remove_keys.append(key)
                continue
            try:
                channel = self.bot.get_channel(channel_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(channel_id)
                embed, total_pages, _ = await self.build_presence_board_embed(
                    user_ids=cfg.get("user_ids", []),
                    sort_by=cfg.get("sort_by", "name"),
                    page=int(cfg.get("page", 0)),
                    page_size=int(cfg.get("page_size", 15)),
                    sort_desc=bool(cfg.get("sort_desc", False)),
                    action="อัปเดตต่อเนื่อง (หลังรีบูต)"
                )
                msg = None
                if message_id:
                    try:
                        msg = await channel.fetch_message(message_id)
                    except Exception:
                        msg = None
                if msg is None:
                    view = RobloxPresenceBoardView(
                        self,
                        owner_id=int(cfg.get("owner_id", 0) or 0),
                        user_ids=[str(x) for x in cfg.get("user_ids", [])][:MAX_BOARD_USERS],
                        sort_by=cfg.get("sort_by", "name"),
                        auto_update=auto_update
                    )
                    view.sort_desc = bool(cfg.get("sort_desc", False))
                    view.page = int(cfg.get("page", 0) or 0)
                    view.page_size = int(cfg.get("page_size", 15) or 15)
                    view.total_pages = total_pages
                    view.last_action = "อัปเดตต่อเนื่อง (หลังรีบูต)"
                    view._update_button_labels()
                    msg = await channel.send(embed=embed, view=view)
                    view.message = msg
                    cfg["message_id"] = msg.id
                    changed = True
                else:
                    view = RobloxPresenceBoardView(
                        self,
                        owner_id=int(cfg.get("owner_id", 0) or 0),
                        user_ids=[str(x) for x in cfg.get("user_ids", [])][:MAX_BOARD_USERS],
                        sort_by=cfg.get("sort_by", "name"),
                        auto_update=auto_update
                    )
                    view.sort_desc = bool(cfg.get("sort_desc", False))
                    view.page = int(cfg.get("page", 0) or 0)
                    view.page_size = int(cfg.get("page_size", 15) or 15)
                    view.total_pages = total_pages
                    view.last_action = "อัปเดตต่อเนื่อง (หลังรีบูต)"
                    view._update_button_labels()
                    await msg.edit(embed=embed, view=view)
                    view.message = msg
                cfg["page"] = min(int(cfg.get("page", 0)), max(0, total_pages - 1))
                cfg["updated_at"] = datetime.now(timezone.utc).isoformat()
                cfg["rehydrated"] = True
                logger.info(f"[RobloxBoard] persistent update channel={channel_id} message={cfg.get('message_id')}")
                await asyncio.sleep(0.6)
            except Exception as e:
                logger.warning(f"[RobloxBoard] persistent update failed key={key}: {e}")
        for key in remove_keys:
            self.presence_boards.pop(key, None)
            changed = True
        if changed:
            self.save_presence_boards()

    async def notify_presence_change(self, roblox_id, p_type, location):
        """แจ้งเตือนการเปลี่ยนแปลงไปยังทุก Channel ที่เลือกไว้"""
        channels_ids = self.tracked_users.get(roblox_id, [])
        if not channels_ids: return
        
        async with aiohttp.ClientSession() as session:
            info = await self.get_user_info(session, roblox_id)
            if not info: return
            
            p_text = self.presence_map.get(p_type, "ไม่ทราบ")
            color = discord.Color.blue()
            if p_type == 0: color = discord.Color.light_grey() # Offline
            elif p_type == 1: color = discord.Color.green()   # Online
            elif p_type == 2: color = discord.Color.gold()    # In Game
            elif p_type == 3: color = discord.Color.purple()  # In Studio

            embed = discord.Embed(
                title=f"📢 อัปเดตสถานะ: {info['displayName']}",
                description=f"ระบบตรวจพบการเปลี่ยนแปลงสถานะล่าสุดของ **{info['displayName']}** (@{info['name']})",
                color=color,
                timestamp=datetime.now()
            )
            embed.set_thumbnail(url=info['avatar_url'])
            embed.add_field(name="🌐 สถานะใหม่", value=f"**{p_text}**", inline=True)
            
            if p_type in [2, 3]: # Playing or In Studio
                embed.add_field(name="📍 กิจกรรมปัจจุบัน", value=f"`{location}`", inline=True)
            
            embed.set_footer(text=f"Roblox ID: {roblox_id}")

            # ส่งไปยังทุกช่องที่ลงทะเบียนไว้
            for cid_str in channels_ids:
                try:
                    channel = self.bot.get_channel(int(cid_str))
                    if channel:
                        await channel.send(embed=embed)
                except:
                    pass

    @app_commands.command(name="ติดตามสถานะroblox", description="ลงทะเบียนติดตามสถานะของผู้ใช้ Roblox (บอทจะแจ้งในห้องนี้เมื่อเขาเปลี่ยนสถานะ)")
    @app_commands.describe(user_id="ID หรือชื่อผู้ใช้ Roblox ที่ต้องการติดตาม")
    async def track_roblox(self, interaction: discord.Interaction, user_id: str):
        await interaction.response.defer()
        
        real_user_id = None
        match = re.search(r"(\d{7,})", user_id)
        if match:
            real_user_id = match.group(1)
        else:
            async with aiohttp.ClientSession() as session:
                real_user_id = await self.get_user_id_by_name(session, user_id)
        
        if not real_user_id or not real_user_id.isdigit():
            return await interaction.followup.send(f"❌ ไม่พบข้อมูลผู้ใช้: `{user_id}`")
        
        cid_str = str(interaction.channel_id)
        rid_str = str(real_user_id)
        
        if rid_str not in self.tracked_users:
            self.tracked_users[rid_str] = []
            
        if cid_str not in self.tracked_users[rid_str]:
            self.tracked_users[rid_str].append(cid_str)
            self.save_tracking_data()
            await interaction.followup.send(f"✅ **เริ่มการติดตามสำเร็จ!** บอทจะแจ้งเตือนเมื่อ User ID: `{rid_str}` มีการเปลี่ยนแปลงสถานะมายังช่องนี้")
        else:
            await interaction.followup.send(f"ℹ️ คุณลงทะเบียนติดตาม User ID: `{rid_str}` ในช่องนี้ไว้แล้ว")

    @app_commands.command(name="ยกเลิกติดตามroblox", description="ยกเลิกการติดตามสถานะของผู้ใช้ Roblox ในห้องนี้")
    @app_commands.describe(user_id="ID หรือชื่อผู้ใช้ Roblox ที่ต้องการยกเลิก")
    async def untrack_roblox(self, interaction: discord.Interaction, user_id: str):
        real_user_id = None
        match = re.search(r"(\d{7,})", user_id)
        if match: real_user_id = match.group(1)
        else:
            async with aiohttp.ClientSession() as session:
                real_user_id = await self.get_user_id_by_name(session, user_id)
        
        if not real_user_id:
            return await interaction.response.send_message(f"❌ ไม่พบข้อมูลผู้ใช้: `{user_id}`", ephemeral=True)
            
        cid_str = str(interaction.channel_id)
        rid_str = str(real_user_id)
        
        if rid_str in self.tracked_users and cid_str in self.tracked_users[rid_str]:
            self.tracked_users[rid_str].remove(cid_str)
            if not self.tracked_users[rid_str]:
                del self.tracked_users[rid_str]
            self.save_tracking_data()
            await interaction.response.send_message(f"✅ ยกเลิกการติดตาม User ID: `{rid_str}` สำหรับช่องนี้เรียบร้อยแล้ว")
        else:
            await interaction.response.send_message(f"❌ คุณไม่ได้ลงทะเบียนติดตาม User ID: `{rid_str}` ไว้ในช่องนี้", ephemeral=True)

    @app_commands.command(name="รายการติดตามroblox", description="ดูรายชื่อผู้ใช้ Roblox ที่กำลังติดตามอยู่ในเซิร์ฟเวอร์นี้")
    async def list_tracked(self, interaction: discord.Interaction):
        tracked_here = []
        for rid, channels in self.tracked_users.items():
            if str(interaction.channel_id) in channels:
                tracked_here.append(rid)
                
        if not tracked_here:
            return await interaction.response.send_message("ℹ️ ไม่มีรายชื่อที่กำลังติดตามอยู่ในช่องนี้")
            
        text = "\n".join([f"- `{rid}`" for rid in tracked_here])
        await interaction.response.send_message(f"📋 **รายชื่อที่กำลังติดตามในช่องนี้:**\n{text}")

    @app_commands.command(name="สถานะกระดานroblox", description="แสดงตารางสถานะ Roblox หลายคนแบบอัปเดตต่อเนื่อง")
    @app_commands.describe(
        รายชื่อ="ใส่ ID/ชื่อ Roblox ได้หลายคน คั่นด้วย , หรือช่องว่าง",
        ดึงเพื่อนจาก="ใส่ ID/ชื่อ Roblox เพื่อดึงรายชื่อเพื่อนเพิ่มเข้าในตาราง",
        จำนวนเพื่อน="จำนวนเพื่อนที่ต้องการดึง (1-100)",
        เรียงตาม="รูปแบบการเรียงตาราง",
        อัปเดตต่อเนื่อง="ให้บอทรีเฟรชตารางอัตโนมัติทุก 45 วินาทีหรือไม่"
    )
    @app_commands.choices(เรียงตาม=[
        app_commands.Choice(name="ตามชื่อ", value="name"),
        app_commands.Choice(name="ออนไลน์ล่าสุด", value="latest"),
        app_commands.Choice(name="เล่นเกมนานสุด", value="game"),
    ])
    async def roblox_presence_board(
        self,
        interaction: discord.Interaction,
        รายชื่อ: str = "",
        ดึงเพื่อนจาก: str = "",
        จำนวนเพื่อน: int = 30,
        เรียงตาม: str = "name",
        อัปเดตต่อเนื่อง: bool = True,
    ):
        await interaction.response.defer()
        logger.info(
            f"[RobloxBoard] command start by={interaction.user.id} guild={interaction.guild_id} channel={interaction.channel_id} "
            f"sort={เรียงตาม} auto={อัปเดตต่อเนื่อง}"
        )

        tokens = [x.strip() for x in re.split(r"[,\n\r\t ]+", รายชื่อ or "") if x.strip()]
        tokens = tokens[:MAX_BOARD_USERS]

        resolved: List[str] = []
        unresolved: List[str] = []
        async with aiohttp.ClientSession() as session:
            for idx, token in enumerate(tokens, start=1):
                uid = await self.resolve_user_input(session, token)
                if uid:
                    resolved.append(str(uid))
                else:
                    unresolved.append(token)
                if idx % 50 == 0:
                    logger.info(f"[RobloxBoard] resolving inputs progress {idx}/{len(tokens)}")

            if ดึงเพื่อนจาก.strip():
                logger.info(f"[RobloxBoard] fetching friends seed={ดึงเพื่อนจาก.strip()} limit={จำนวนเพื่อน}")
                owner_id = await self.resolve_user_input(session, ดึงเพื่อนจาก.strip())
                if owner_id:
                    friend_ids = await self.get_friend_ids(session, str(owner_id), limit=max(1, min(MAX_BOARD_USERS, จำนวนเพื่อน)))
                    resolved.extend(friend_ids)
                else:
                    unresolved.append(ดึงเพื่อนจาก.strip())

        resolved = list(dict.fromkeys(resolved))[:MAX_BOARD_USERS]
        if not resolved:
            return await interaction.followup.send("❌ ไม่พบรายชื่อที่ใช้งานได้ กรุณาใส่รายชื่อ/ID หรือระบุ `ดึงเพื่อนจาก`")

        view = RobloxPresenceBoardView(self, interaction.user.id, resolved, sort_by=เรียงตาม, auto_update=อัปเดตต่อเนื่อง)
        embed, total_pages, total_rows = await self.build_presence_board_embed(resolved, sort_by=เรียงตาม, page=0, page_size=view.page_size)
        view.total_pages = total_pages
        view.total_rows = total_rows
        view._update_button_labels()
        if unresolved:
            embed.add_field(name="⚠️ แปลงไม่ได้", value=", ".join(f"`{x}`" for x in unresolved[:20]), inline=False)

        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg
        self.upsert_presence_board(
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            message_id=msg.id,
            owner_id=interaction.user.id,
            user_ids=resolved,
            sort_by=เรียงตาม,
            sort_desc=view.sort_desc,
            page=0,
            page_size=view.page_size,
            auto_update=อัปเดตต่อเนื่อง,
        )
        logger.info(
            f"[RobloxBoard] created by={interaction.user.id} guild={interaction.guild_id} channel={interaction.channel_id} "
            f"users={len(resolved)} sort={เรียงตาม} auto={อัปเดตต่อเนื่อง}"
        )
        if view.auto_update:
            view.start_auto()

    @app_commands.command(name="เครือข่ายroblox", description="ค้นหาเพื่อนร่วมกัน/ติดตามร่วมกัน/เส้นทางเชื่อมโยง Roblox")
    @app_commands.describe(
        mode="เลือกประเภทการค้นหา",
        user_a="ID/ชื่อ Roblox ฝั่ง A",
        user_b="ID/ชื่อ Roblox ฝั่ง B",
        max_items="จำนวนที่ดึงต่อฝั่ง (ใช้กับโหมดร่วมกัน)",
        max_depth="ความลึกสูงสุดในการหาเส้นทาง (ใช้กับโหมดเส้นทาง)",
        branch_limit="จำนวนเพื่อนสูงสุดที่ขยายต่อโหนด (ใช้กับโหมดเส้นทาง)"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="เพื่อนร่วมกัน", value="common_friends"),
        app_commands.Choice(name="ผู้ติดตามร่วมกัน", value="common_followers"),
        app_commands.Choice(name="กำลังติดตามร่วมกัน", value="common_followings"),
        app_commands.Choice(name="เส้นทางเชื่อมโยงเพื่อน", value="path_friends"),
    ])
    async def roblox_network(
        self,
        interaction: discord.Interaction,
        mode: str,
        user_a: str,
        user_b: str,
        max_items: int = 1000,
        max_depth: int = 4,
        branch_limit: int = 120,
    ):
        await interaction.response.defer()
        logger.info(
            f"[RobloxNetwork] start by={interaction.user.id} guild={interaction.guild_id} mode={mode} "
            f"user_a={user_a} user_b={user_b} max_items={max_items} max_depth={max_depth} branch_limit={branch_limit}"
        )
        max_items = max(10, min(5000, max_items))
        max_depth = max(1, min(8, max_depth))
        branch_limit = max(20, min(500, branch_limit))

        async with aiohttp.ClientSession() as session:
            aid = await self.resolve_user_input(session, user_a)
            bid = await self.resolve_user_input(session, user_b)
            if not aid or not bid:
                logger.warning(f"[RobloxNetwork] resolve failed aid={aid} bid={bid}")
                return await interaction.followup.send("❌ ไม่สามารถแปลงผู้ใช้ A/B เป็น Roblox ID ได้")

            names = await self.get_usernames_map(session, [aid, bid])
            a_name = names.get(aid, aid)
            b_name = names.get(bid, bid)

            if mode == "path_friends":
                logger.info(f"[RobloxNetwork] finding path aid={aid} bid={bid} depth={max_depth} branch={branch_limit}")
                path = await self.find_friend_path(
                    session, aid, bid, max_depth=max_depth, branch_limit=branch_limit
                )
                embed = discord.Embed(
                    title="🕸️ Roblox Friend Path",
                    color=discord.Color.blurple(),
                    timestamp=datetime.now()
                )
                if path:
                    logger.info(f"[RobloxNetwork] path found length={len(path)-1}")
                    node_map = await self.get_usernames_map(session, path)
                    chain = " ➜ ".join(f"{node_map.get(uid, uid)} (`{uid}`)" for uid in path)
                    embed.description = chain[:3900]
                    embed.add_field(name="ผลลัพธ์", value=f"พบเส้นทางยาว {len(path)-1} ขั้น", inline=False)
                else:
                    logger.info("[RobloxNetwork] path not found")
                    embed.description = f"ไม่พบเส้นทางเพื่อนจาก `{a_name}` ไป `{b_name}` ภายในความลึก {max_depth}"
                    embed.add_field(name="คำแนะนำ", value="ลองเพิ่ม `max_depth` หรือ `branch_limit` แล้วค้นหาอีกครั้ง", inline=False)
                return await interaction.followup.send(embed=embed)

            if mode == "common_friends":
                logger.info(f"[RobloxNetwork] comparing common_friends with max_items={max_items}")
                set_a, set_b = await asyncio.gather(
                    self.get_friends_set(session, aid, limit=max_items),
                    self.get_friends_set(session, bid, limit=max_items),
                )
                label = "เพื่อนร่วมกัน"
            elif mode == "common_followers":
                logger.info(f"[RobloxNetwork] comparing common_followers with max_items={max_items}")
                set_a, set_b = await asyncio.gather(
                    self.get_followers_set(session, aid, limit=max_items),
                    self.get_followers_set(session, bid, limit=max_items),
                )
                label = "ผู้ติดตามร่วมกัน"
            else:  # common_followings
                logger.info(f"[RobloxNetwork] comparing common_followings with max_items={max_items}")
                set_a, set_b = await asyncio.gather(
                    self.get_followings_set(session, aid, limit=max_items),
                    self.get_followings_set(session, bid, limit=max_items),
                )
                label = "กำลังติดตามร่วมกัน"

            common_ids = sorted(set_a.intersection(set_b), key=lambda x: int(x))
            logger.info(f"[RobloxNetwork] common result count={len(common_ids)}")
            preview_ids = common_ids[:50]
            preview_map = await self.get_usernames_map(session, preview_ids) if preview_ids else {}
            lines = [f"- {preview_map.get(uid, uid)} (`{uid}`)" for uid in preview_ids]
            embed = discord.Embed(
                title=f"🔎 Roblox Network • {label}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(
                name="คู่ที่เปรียบเทียบ",
                value=f"A: {a_name} (`{aid}`)\nB: {b_name} (`{bid}`)",
                inline=False
            )
            if common_ids:
                embed.add_field(name=f"พบทั้งหมด {len(common_ids)} รายการ", value="\n".join(lines)[:1024], inline=False)
                if len(common_ids) > len(preview_ids):
                    embed.set_footer(text=f"แสดง {len(preview_ids)} จากทั้งหมด {len(common_ids)}")
            else:
                embed.description = "ไม่พบรายการร่วมกันจากการค้นหานี้"
            await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(FollowersCog(bot))
