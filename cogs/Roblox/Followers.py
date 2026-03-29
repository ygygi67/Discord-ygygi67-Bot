import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
import asyncio
import re
import os
import json
from datetime import datetime, timezone

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

async def setup(bot):
    await bot.add_cog(FollowersCog(bot))
