import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
import asyncio
import re
import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("discord_bot")
MAX_BOARD_USERS = 1000

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
        added = await self.view.add_friends_of(raw, limit)
        await self.view.refresh_message()
        await interaction.followup.send(f"✅ ดึงเพื่อนเพิ่มแล้ว {added} คน", ephemeral=True)


class RobloxPresenceBoardView(discord.ui.View):
    def __init__(self, cog: "FollowersCog", owner_id: int, user_ids: List[str], sort_by: str = "name", auto_update: bool = True):
        super().__init__(timeout=1800)
        self.cog = cog
        self.owner_id = owner_id
        self.user_ids = user_ids
        self.sort_by = sort_by
        self.auto_update = auto_update
        self.message: Optional[discord.Message] = None
        self.auto_task: Optional[asyncio.Task] = None
        self.interval_sec = 45
        self.page = 0
        self.page_size = 15
        self.total_pages = 1
        self.total_rows = 0
        self._update_button_labels()

    def _update_button_labels(self):
        self.btn_sort_name.style = discord.ButtonStyle.success if self.sort_by == "name" else discord.ButtonStyle.secondary
        self.btn_sort_latest.style = discord.ButtonStyle.success if self.sort_by == "latest" else discord.ButtonStyle.secondary
        self.btn_sort_game.style = discord.ButtonStyle.success if self.sort_by == "game" else discord.ButtonStyle.secondary
        self.btn_toggle_auto.label = "⏸️ หยุดอัปเดตอัตโนมัติ" if self.auto_update else "▶️ เริ่มอัปเดตอัตโนมัติ"
        self.btn_page.label = f"หน้า {self.page + 1}/{max(1, self.total_pages)}"
        self.btn_prev.disabled = self.page <= 0
        self.btn_next.disabled = self.page >= max(0, self.total_pages - 1)
        self.btn_jump_back_5.disabled = self.page <= 0
        self.btn_jump_back_10.disabled = self.page <= 0
        self.btn_jump_forward_5.disabled = self.page >= max(0, self.total_pages - 1)
        self.btn_jump_forward_10.disabled = self.page >= max(0, self.total_pages - 1)
        self.btn_last.disabled = self.page >= max(0, self.total_pages - 1)

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ แผงนี้สำหรับคนที่เรียกคำสั่งเท่านั้น", ephemeral=True)
            return False
        return True

    async def refresh_message(self):
        if not self.message:
            return
        embed, total_pages, total_rows = await self.cog.build_presence_board_embed(
            self.user_ids, self.sort_by, page=self.page, page_size=self.page_size
        )
        self.total_pages = total_pages
        self.total_rows = total_rows
        if self.page >= self.total_pages:
            self.page = max(0, self.total_pages - 1)
            embed, self.total_pages, self.total_rows = await self.cog.build_presence_board_embed(
                self.user_ids, self.sort_by, page=self.page, page_size=self.page_size
            )
        self._update_button_labels()
        await self.message.edit(embed=embed, view=self)
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
        self.stop_auto()
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
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="↕️ ชื่อ", style=discord.ButtonStyle.success, row=0)
    async def btn_sort_name(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.sort_by = "name"
        self._update_button_labels()
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="🕒 ล่าสุด", style=discord.ButtonStyle.secondary, row=0)
    async def btn_sort_latest(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.sort_by = "latest"
        self._update_button_labels()
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="🎮 เวลาเล่น", style=discord.ButtonStyle.secondary, row=0)
    async def btn_sort_game(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.sort_by = "game"
        self._update_button_labels()
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="⏸️ หยุดอัปเดตอัตโนมัติ", style=discord.ButtonStyle.secondary, row=1)
    async def btn_toggle_auto(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.auto_update = not self.auto_update
        self._update_button_labels()
        if self.auto_update:
            self.start_auto()
        else:
            self.stop_auto()
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="⬅️ ก่อนหน้า", style=discord.ButtonStyle.secondary, row=1)
    async def btn_prev(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        if self.page > 0:
            self.page -= 1
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="หน้า 1/1", style=discord.ButtonStyle.secondary, row=1, disabled=True)
    async def btn_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        await interaction.response.send_message("ℹ️ ใช้ปุ่ม ก่อนหน้า/ถัดไป เพื่อเปลี่ยนหน้า", ephemeral=True)

    @discord.ui.button(label="ถัดไป ➡️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_next(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        if self.page < self.total_pages - 1:
            self.page += 1
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="⏪ -10 หน้า", style=discord.ButtonStyle.secondary, row=2)
    async def btn_jump_back_10(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.page = max(0, self.page - 10)
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="⏮ -5 หน้า", style=discord.ButtonStyle.secondary, row=2)
    async def btn_jump_back_5(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.page = max(0, self.page - 5)
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="+5 หน้า ⏭", style=discord.ButtonStyle.secondary, row=2)
    async def btn_jump_forward_5(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.page = min(max(0, self.total_pages - 1), self.page + 5)
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="+10 หน้า ⏩", style=discord.ButtonStyle.secondary, row=2)
    async def btn_jump_forward_10(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.page = min(max(0, self.total_pages - 1), self.page + 10)
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="⏹ หน้าสุดท้าย", style=discord.ButtonStyle.secondary, row=2)
    async def btn_last(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.page = max(0, self.total_pages - 1)
        await interaction.response.defer()
        await self.refresh_message()

    @discord.ui.button(label="➕ เพิ่มชื่อ/ID", style=discord.ButtonStyle.success, row=3)
    async def btn_add_users(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        await interaction.response.send_modal(RobloxAddUsersModal(self))

    @discord.ui.button(label="👥 ดึงเพื่อน", style=discord.ButtonStyle.primary, row=3)
    async def btn_add_friends(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        await interaction.response.send_modal(RobloxFetchFriendsModal(self))

    @discord.ui.button(label="🛑 ปิดแผง", style=discord.ButtonStyle.danger, row=3)
    async def btn_stop(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not await self._check_owner(interaction):
            return
        self.stop_auto()
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
        self.tracked_users = self.load_tracking_data() # {roblox_id: [channel_id, ...]}
        self.last_presence = {} # {roblox_id: last_presence_type}
        self.game_started_at: Dict[str, float] = {}
        self.game_total_seconds: Dict[str, float] = {}
        self.last_online_ts: Dict[str, float] = {}
        
        # เริ่ม Task ตรวจสอบสถานะ
        self.check_presence_task.start()

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

    def cog_unload(self):
        self.check_presence_task.cancel()

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
        ids: List[str] = []
        cursor = None
        limit = max(1, min(MAX_BOARD_USERS, limit))
        while len(ids) < limit:
            remaining = min(100, limit - len(ids))
            url = f"https://friends.roblox.com/v1/users/{user_id}/friends?sortOrder=Asc&limit={remaining}"
            if cursor:
                url += f"&cursor={cursor}"
            try:
                async with session.get(url, timeout=15) as r:
                    if r.status != 200:
                        break
                    data = await r.json()
                    for item in data.get("data", []):
                        fid = str(item.get("id", "")).strip()
                        if fid.isdigit():
                            ids.append(fid)
                            if len(ids) >= limit:
                                break
                    cursor = data.get("nextPageCursor")
                    if not cursor:
                        break
            except Exception:
                break
        return ids

    async def resolve_user_input(self, session: aiohttp.ClientSession, raw: str) -> Optional[str]:
        match = re.search(r"(\d{4,})", raw or "")
        if match:
            return match.group(1)
        return await self.get_user_id_by_name(session, (raw or "").strip())

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
            presence_by_id: Dict[str, dict] = {}
            for i in range(0, len(ids_int), 100):
                chunk = ids_int[i:i+100]
                url = "https://presence.roblox.com/v1/presence/users"
                async with session.post(url, json={"userIds": chunk}, timeout=15) as r:
                    if r.status == 200:
                        payload = await r.json()
                        for p in payload.get("userPresences", []):
                            uid = str(p.get("userId"))
                            presence_by_id[uid] = p

            basic_by_id: Dict[str, dict] = {}
            for i in range(0, len(ids_int), 100):
                chunk = ids_int[i:i+100]
                ids_query = ",".join(str(x) for x in chunk)
                try:
                    async with session.get(f"https://users.roblox.com/v1/users?userIds={ids_query}", timeout=15) as r:
                        if r.status == 200:
                            payload = await r.json()
                            for u in payload.get("data", []):
                                basic_by_id[str(u.get("id"))] = u
                except Exception:
                    continue

            for uid in [str(x) for x in ids_int]:
                basic = basic_by_id.get(uid, {})
                p = presence_by_id.get(uid, {})
                p_type = int(p.get("userPresenceType", 0) or 0)
                last_online_iso = p.get("lastOnline") or ""
                last_online_ts = self._parse_time(last_online_iso)
                if p_type > 0:
                    self.last_online_ts[uid] = datetime.now(timezone.utc).timestamp()
                elif last_online_ts > 0:
                    self.last_online_ts[uid] = last_online_ts

                if p_type == 2:
                    if uid not in self.game_started_at:
                        self.game_started_at[uid] = datetime.now(timezone.utc).timestamp()
                else:
                    if uid in self.game_started_at:
                        start = self.game_started_at.pop(uid)
                        self.game_total_seconds[uid] = self.game_total_seconds.get(uid, 0.0) + max(0.0, datetime.now(timezone.utc).timestamp() - start)

                rows.append({
                    "display_name": basic.get("displayName", uid),
                    "username": basic.get("name", uid),
                    "user_id": str(basic.get("id", uid)),
                    "status_text": self.presence_map.get(p_type, "❓ ไม่ทราบ"),
                    "status_type": p_type,
                    "last_online_ts": self.last_online_ts.get(uid, 0.0),
                    "game_duration_sec": self._game_duration_sec(uid),
                })
        return rows

    async def build_presence_board_embed(
        self, user_ids: List[str], sort_by: str = "name", page: int = 0, page_size: int = 15
    ) -> Tuple[discord.Embed, int, int]:
        rows = await self.fetch_presence_rows(user_ids)

        if sort_by == "latest":
            rows.sort(key=lambda x: (x["last_online_ts"], x["display_name"].lower()), reverse=True)
        elif sort_by == "game":
            rows.sort(key=lambda x: (x["game_duration_sec"], x["display_name"].lower()), reverse=True)
        else:
            rows.sort(key=lambda x: x["display_name"].lower())

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
        embed.set_footer(text=f"รวม {len(rows)} คน | Sort: {sort_by} | Page {page + 1}/{total_pages}")
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

    # --- ระบบติดตามสถานะ ---

    @tasks.loop(seconds=45) # ตรวจสอบทุก 45 วินาที
    async def check_presence_task(self):
        if not self.tracked_users:
            return
            
        try:
            async with aiohttp.ClientSession() as session:
                # แปลงรหัสคนทั้งหมดเป็น List เพื่อทำการ Query แบบ Batch
                ids = [int(rid) for rid in self.tracked_users.keys()]
                
                # Roblox Presence API (Batch up to 100)
                url = "https://presence.roblox.com/v1/presence/users"
                async with session.post(url, json={"userIds": ids}, timeout=15) as r:
                    if r.status == 200:
                        data = await r.json()
                        presences = data.get("userPresences", [])
                        
                        for p in presences:
                            rid = str(p.get("userId"))
                            ptype = p.get("userPresenceType", 0)
                            location = p.get("lastLocation", "ไม่ทราบ")
                            
                            # ตรวจสอบว่ามีข้อมูลการเปลี่ยนแปลงไหม
                            if rid in self.last_presence and self.last_presence[rid] != ptype:
                                # มีการเปลี่ยนแปลง! ส่งแจ้งเตือน
                                await self.notify_presence_change(rid, ptype, location)
                            
                            # อัปเดตสถานะล่าสุด
                            self.last_presence[rid] = ptype
                    else:
                        print(f"Presence Task Error: status {r.status}")
        except Exception as e:
            print(f"Presence Task Traceback Error: {e}")

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

    @app_commands.command(name="กระดานสถานะroblox", description="แสดงตารางสถานะ Roblox หลายคนแบบอัปเดตต่อเนื่อง")
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

        tokens = [x.strip() for x in re.split(r"[,\n\r\t ]+", รายชื่อ or "") if x.strip()]
        tokens = tokens[:MAX_BOARD_USERS]

        resolved: List[str] = []
        unresolved: List[str] = []
        async with aiohttp.ClientSession() as session:
            for token in tokens:
                uid = await self.resolve_user_input(session, token)
                if uid:
                    resolved.append(str(uid))
                else:
                    unresolved.append(token)

            if ดึงเพื่อนจาก.strip():
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
        logger.info(
            f"[RobloxBoard] created by={interaction.user.id} guild={interaction.guild_id} channel={interaction.channel_id} "
            f"users={len(resolved)} sort={เรียงตาม} auto={อัปเดตต่อเนื่อง}"
        )
        if view.auto_update:
            view.start_auto()

async def setup(bot):
    await bot.add_cog(FollowersCog(bot))
