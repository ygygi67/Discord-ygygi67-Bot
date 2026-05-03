import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import shutil
from datetime import datetime, timedelta
import logging
from collections import defaultdict
import matplotlib.pyplot as plt
import io
from typing import Optional

logger = logging.getLogger('discord_bot')

STATS_FILE = "data/stats.json"
TOP_N = 10

class StatsRangeModal(discord.ui.Modal):
    def __init__(self, cog: "Stats", target_type: str, target_id: str, title: str):
        super().__init__(title="เลือกช่วงวันที่")
        self.cog = cog
        self.target_type = target_type
        self.target_id = target_id
        self.title_text = title
        self.start_date = discord.ui.TextInput(label="วันที่เริ่ม", placeholder="YYYY-MM-DD", max_length=10)
        self.end_date = discord.ui.TextInput(label="วันที่จบ", placeholder="YYYY-MM-DD", max_length=10)
        self.add_item(self.start_date)
        self.add_item(self.end_date)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            start = datetime.strptime(str(self.start_date.value).strip(), "%Y-%m-%d")
            end = datetime.strptime(str(self.end_date.value).strip(), "%Y-%m-%d")
            if end < start:
                start, end = end, start
            keys = self.cog._date_keys_between(start, end)
            if not keys:
                await interaction.response.send_message("❌ ไม่พบช่วงวันที่ที่เลือก", ephemeral=True)
                return
            if self.target_type == "user":
                embed = self.cog.build_user_stats_embed(self.target_id, self.title_text, keys, f"{keys[-1]} ถึง {keys[0]}")
            else:
                embed = self.cog.build_server_stats_embed(interaction.guild, keys, f"{keys[-1]} ถึง {keys[0]}")
            await interaction.response.edit_message(embed=embed)
        except Exception as e:
            logger.warning(f"Stats custom range failed: {e}")
            await interaction.response.send_message("❌ รูปแบบวันที่ไม่ถูกต้อง ใช้ YYYY-MM-DD เช่น 2026-05-03", ephemeral=True)

class StatsRangeView(discord.ui.View):
    def __init__(self, cog: "Stats", target_type: str, target_id: str, title: str):
        super().__init__(timeout=180)
        self.cog = cog
        self.target_type = target_type
        self.target_id = target_id
        self.title_text = title

    async def _render(self, interaction: discord.Interaction, days: int):
        keys = self.cog._date_keys_for_days(days)
        label = f"{days} วันล่าสุด"
        if self.target_type == "user":
            embed = self.cog.build_user_stats_embed(self.target_id, self.title_text, keys, label)
        else:
            embed = self.cog.build_server_stats_embed(interaction.guild, keys, label)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="7 วัน", style=discord.ButtonStyle.secondary)
    async def seven_days(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._render(interaction, 7)

    @discord.ui.button(label="15 วัน", style=discord.ButtonStyle.secondary)
    async def fifteen_days(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._render(interaction, 15)

    @discord.ui.button(label="30 วัน", style=discord.ButtonStyle.secondary)
    async def thirty_days(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._render(interaction, 30)

    @discord.ui.button(label="กำหนดเอง", style=discord.ButtonStyle.primary)
    async def custom_days(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StatsRangeModal(self.cog, self.target_type, self.target_id, self.title_text))

class LeaderboardCategorySelect(discord.ui.Select):
    def __init__(self, cog: "Stats"):
        self.cog = cog
        options = [
            discord.SelectOption(label="ข้อความ", value="messages", description="จัดอันดับตามจำนวนข้อความ"),
            discord.SelectOption(label="เวลาในช่องเสียง", value="voice", description="จัดอันดับตามเวลาอยู่ช่องเสียง"),
            discord.SelectOption(label="คำสั่ง", value="commands", description="จัดอันดับตามจำนวนครั้งที่ใช้คำสั่ง"),
        ]
        super().__init__(placeholder="เลือกหมวดหมู่อันดับ", options=options)

    async def callback(self, interaction: discord.Interaction):
        embed = await self.cog.build_leaderboard_embed(self.values[0])
        await interaction.response.edit_message(embed=embed, view=self.view)

class LeaderboardView(discord.ui.View):
    def __init__(self, cog: "Stats"):
        super().__init__(timeout=180)
        self.add_item(LeaderboardCategorySelect(cog))

def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"stats.json corrupted (JSONDecodeError): {e}")
            # พยายามกู้ object ตัวแรกจากไฟล์ที่มีข้อมูลซ้อนกัน
            try:
                with open(STATS_FILE, "r", encoding="utf-8") as f:
                    raw = f.read()
                decoder = json.JSONDecoder()
                obj, _ = decoder.raw_decode(raw.lstrip())
                backup_path = STATS_FILE + ".corrupt.bak"
                shutil.copy2(STATS_FILE, backup_path)
                logger.warning(f"Backed up corrupt stats file to: {backup_path}")
                return obj if isinstance(obj, dict) else {"messages": {}, "voice": {}, "names": {}, "servers": {}}
            except Exception as recover_err:
                logger.error(f"Failed to recover stats.json: {recover_err}")
                backup_path = STATS_FILE + ".unreadable.bak"
                try:
                    shutil.copy2(STATS_FILE, backup_path)
                    logger.warning(f"Backed up unreadable stats file to: {backup_path}")
                except Exception:
                    pass
                return {"messages": {}, "voice": {}, "names": {}, "servers": {}}
    return {"messages": {}, "voice": {}, "names": {}, "servers": {}}

def save_stats(stats):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.stats = self._ensure_stats_structure(load_stats())
        self.voice_start = {}
        self.save_stats_loop.start()
        logger.info("Stats cog initialized")

    def _ensure_stats_structure(self, stats):
        """Ensure stats has all required keys"""
        required_keys = ["messages", "voice", "names", "servers", "commands", "user_commands", "bans", "kicks", "invites", "daily"]
        for key in required_keys:
            if key not in stats:
                stats[key] = {}
        return stats

    def _today_key(self):
        return datetime.utcnow().strftime("%Y-%m-%d")

    def _format_minutes(self, minutes):
        total = max(0, int(round(float(minutes or 0))))
        hours, mins = divmod(total, 60)
        return f"{hours:,} ชั่วโมง {mins:02d} นาที"

    def _daily_bucket(self, date_key=None):
        date_key = date_key or self._today_key()
        daily = self.stats.setdefault("daily", {})
        bucket = daily.setdefault(date_key, {})
        for key in ("messages", "voice", "servers", "server_voice", "commands", "user_commands", "channels"):
            bucket.setdefault(key, {})
        return bucket

    def _date_keys_for_days(self, days: int):
        if not days or days <= 0:
            return []
        now = datetime.utcnow()
        return [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]

    def _date_keys_between(self, start: datetime, end: datetime):
        keys = []
        current = end
        while current >= start:
            keys.append(current.strftime("%Y-%m-%d"))
            current -= timedelta(days=1)
        return keys

    def _sum_daily(self, section: str, entity_id: str, days: int):
        if not days or days <= 0:
            return None
        total = 0
        found = False
        for date_key in self._date_keys_for_days(days):
            bucket = self.stats.get("daily", {}).get(date_key, {})
            data = bucket.get(section, {})
            if entity_id in data:
                found = True
                total += data.get(entity_id, 0)
        return total if found else 0

    def _sum_daily_keys(self, section: str, entity_id: str, date_keys: list[str]):
        total = 0
        for date_key in date_keys:
            bucket = self.stats.get("daily", {}).get(date_key, {})
            total += bucket.get(section, {}).get(entity_id, 0)
        return total

    def _busiest_day(self, section: str, entity_id: str, date_keys: list[str]):
        values = []
        for date_key in date_keys:
            count = self.stats.get("daily", {}).get(date_key, {}).get(section, {}).get(entity_id, 0)
            values.append((date_key, count))
        if not values:
            return "ไม่มีข้อมูล"
        day, count = max(values, key=lambda item: item[1])
        return f"{day} ({int(count):,})"

    def _server_messages_for_keys(self, server_id: str, date_keys: list[str]):
        total = 0
        for date_key in date_keys:
            total += self.stats.get("daily", {}).get(date_key, {}).get("servers", {}).get(server_id, {}).get("messages", 0)
        return total

    def _top_channel_for_keys(self, guild: discord.Guild, date_keys: list[str]):
        totals = defaultdict(int)
        for date_key in date_keys:
            channels = self.stats.get("daily", {}).get(date_key, {}).get("channels", {}).get(str(guild.id), {})
            for channel_id, count in channels.items():
                totals[channel_id] += count
        if not totals:
            return "ไม่มีข้อมูล"
        channel_id, count = max(totals.items(), key=lambda item: item[1])
        channel = guild.get_channel(int(channel_id)) if str(channel_id).isdigit() else None
        name = channel.mention if channel else f"`{channel_id}`"
        return f"{name} ({count:,} ข้อความ)"

    def build_user_stats_embed(self, user_id: str, title: str, date_keys: list[str] | None, label: str):
        if date_keys:
            message_count = self._sum_daily_keys("messages", user_id, date_keys)
            voice_minutes = self._sum_daily_keys("voice", user_id, date_keys)
            avg = message_count / max(1, len(date_keys))
            busiest = self._busiest_day("messages", user_id, date_keys)
        else:
            message_count = self.stats.get("messages", {}).get(user_id, 0)
            voice_minutes = self.stats.get("voice", {}).get(user_id, 0)
            days_with_data = [k for k, v in self.stats.get("daily", {}).items() if user_id in v.get("messages", {})]
            avg = message_count / max(1, len(days_with_data))
            busiest = self._busiest_day("messages", user_id, days_with_data) if days_with_data else "ไม่มีข้อมูล"

        embed = discord.Embed(title=f"📊 สถิติของ {title}", description=f"ช่วงเวลา: {label}", color=discord.Color.blurple())
        embed.add_field(name="ข้อความทั้งหมด", value=f"{int(message_count):,} ข้อความ", inline=True)
        embed.add_field(name="เฉลี่ยต่อวัน", value=f"{avg:,.1f} ข้อความ/วัน", inline=True)
        embed.add_field(name="วันที่พิมพ์เยอะสุด", value=busiest, inline=False)
        embed.add_field(name="เวลาในช่องเสียง", value=self._format_minutes(voice_minutes), inline=True)
        return embed

    def build_server_stats_embed(self, guild: discord.Guild, date_keys: list[str] | None, label: str):
        server_id = str(guild.id)
        if date_keys:
            message_count = self._server_messages_for_keys(server_id, date_keys)
            voice_minutes = self._sum_daily_keys("server_voice", server_id, date_keys)
            avg = message_count / max(1, len(date_keys))
            top_channel = self._top_channel_for_keys(guild, date_keys)
        else:
            server_stats = self.stats.get("servers", {}).get(server_id, {})
            message_count = server_stats.get("messages", 0)
            voice_minutes = server_stats.get("voice_time", 0)
            keys = [k for k, v in self.stats.get("daily", {}).items() if server_id in v.get("servers", {})]
            avg = message_count / max(1, len(keys))
            top_channel = self._top_channel_for_keys(guild, keys) if keys else "ไม่มีข้อมูล"

        embed = discord.Embed(title=f"📊 สถิติเซิร์ฟเวอร์ {guild.name}", description=f"ช่วงเวลา: {label}", color=discord.Color.blurple())
        embed.add_field(name="ข้อความรวม", value=f"{int(message_count):,} ข้อความ", inline=True)
        embed.add_field(name="เฉลี่ยต่อวัน", value=f"{avg:,.1f} ข้อความ/วัน", inline=True)
        embed.add_field(name="ช่องที่คุยเยอะสุด", value=top_channel, inline=False)
        embed.add_field(name="เวลาในช่องเสียงรวม", value=self._format_minutes(voice_minutes), inline=True)
        return embed

    async def build_leaderboard_embed(self, category: str):
        labels = {"messages": "ข้อความ", "voice": "เวลาในช่องเสียง", "commands": "คำสั่ง"}
        if category == "messages":
            users = self.stats.get("messages", {})
        elif category == "voice":
            users = self.stats.get("voice", {})
        else:
            users = self.stats.get("user_commands", {})

        sorted_users = sorted(users.items(), key=lambda x: x[1], reverse=True)[:TOP_N]
        embed = discord.Embed(
            title=f"🏆 อันดับผู้ใช้ - {labels.get(category, category)}",
            description="เลือกหมวดหมู่จากเมนูด้านล่างเพื่อสลับอันดับได้ทันที",
            color=discord.Color.gold()
        )
        if not sorted_users:
            embed.description = "ยังไม่มีข้อมูลในหมวดนี้"
            return embed

        lines = []
        for i, (user_id, count) in enumerate(sorted_users, 1):
            name = self.stats.get("names", {}).get(user_id)
            if not name and str(user_id).isdigit():
                try:
                    user = await self.bot.fetch_user(int(user_id))
                    name = user.name
                except Exception:
                    name = user_id
            if category == "voice":
                value = self._format_minutes(count)
            elif category == "messages":
                value = f"{int(count):,} ข้อความ"
            else:
                value = f"{int(count):,} ครั้ง"
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"`#{i}`"
            lines.append(f"{medal} **{name or user_id}**\n└ {value}")
        embed.add_field(name="ตารางอันดับ", value="\n".join(lines), inline=False)
        return embed

    def cog_unload(self):
        self.save_stats_loop.cancel()
        save_stats(self.stats)

    def update_user_stats(self, user_id: str, category: str, value: int = 1):
        """Update user statistics"""
        stats_key = "user_commands" if category == "commands" else category
        self.stats.setdefault(stats_key, {})
        if category in ("messages", "voice", "commands"):
            if user_id not in self.stats[stats_key]:
                self.stats[stats_key][user_id] = 0
            self.stats[stats_key][user_id] += value
        # Defensive: ensure 'names' exists
        if "names" not in self.stats:
            self.stats["names"] = {}
        user = self.bot.get_user(int(user_id))
        if user:
            self.stats["names"][user_id] = user.display_name
        if category == "messages":
            bucket = self._daily_bucket()
            bucket["messages"][user_id] = bucket["messages"].get(user_id, 0) + value
        elif category == "commands":
            bucket = self._daily_bucket()
            bucket["user_commands"][user_id] = bucket["user_commands"].get(user_id, 0) + value
        save_stats(self.stats)

    def update_server_stats(self, server_id: str, category: str, value: int = 1, channel_id: str | None = None):
        """Update server statistics"""
        # Defensive: ensure 'servers' exists
        if "servers" not in self.stats:
            self.stats["servers"] = {}
        if server_id not in self.stats["servers"]:
            self.stats["servers"][server_id] = {
                "messages": 0,
                "commands": 0,
                "invites": 0,
                "bans": 0,
                "kicks": 0,
                "voice_time": 0
            }
        self.stats["servers"][server_id][category] += value
        if category == "messages":
            bucket = self._daily_bucket()
            server_bucket = bucket["servers"].setdefault(server_id, {"messages": 0, "commands": 0, "voice_time": 0})
            server_bucket["messages"] = server_bucket.get("messages", 0) + value
            if channel_id:
                channel_bucket = bucket["channels"].setdefault(server_id, {})
                channel_bucket[channel_id] = channel_bucket.get(channel_id, 0) + value
        save_stats(self.stats)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Track message statistics"""
        if message.author.bot:
            return

        user_id = str(message.author.id)
        server_id = str(message.guild.id) if message.guild else "dm"

        self.update_user_stats(user_id, "messages")
        if message.guild:
            self.update_server_stats(server_id, "messages", channel_id=str(message.channel.id))

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        """Track command usage"""
        user_id = str(ctx.author.id)
        server_id = str(ctx.guild.id) if ctx.guild else "dm"
        command_name = ctx.command.name

        self.update_user_stats(user_id, "commands")
        if ctx.guild:
            self.update_server_stats(server_id, "commands")

        if "commands" not in self.stats:
            self.stats["commands"] = {}
        if command_name not in self.stats["commands"]:
            self.stats["commands"][command_name] = 0
        self.stats["commands"][command_name] += 1
        save_stats(self.stats)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        """Track ban statistics"""
        user_id = str(user.id)
        server_id = str(guild.id)

        self.update_user_stats(user_id, "bans")
        self.update_server_stats(server_id, "bans")

        if "bans" not in self.stats:
            self.stats["bans"] = {}
        if server_id not in self.stats["bans"]:
            self.stats["bans"][server_id] = {}
        self.stats["bans"][server_id][user_id] = {
            "timestamp": datetime.now().isoformat(),
            "guild_name": guild.name
        }
        save_stats(self.stats)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Track kick statistics"""
        user_id = str(member.id)
        server_id = str(member.guild.id)

        # Check if it was a kick (not a ban or leave)
        try:
            async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
                if entry.target.id == member.id:
                    self.update_user_stats(user_id, "kicks")
                    self.update_server_stats(server_id, "kicks")

                    if "kicks" not in self.stats:
                        self.stats["kicks"] = {}
                    if server_id not in self.stats["kicks"]:
                        self.stats["kicks"][server_id] = {}
                    self.stats["kicks"][server_id][user_id] = {
                        "timestamp": datetime.now().isoformat(),
                        "guild_name": member.guild.name
                    }
                    save_stats(self.stats)
                    break
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot: return
        uid = str(member.id)
        # Defensive: ensure 'names' exists
        if "names" not in self.stats:
            self.stats["names"] = {}
        self.stats["names"][uid] = member.display_name
        if after.channel and not before.channel:
            self.voice_start[uid] = {
                "started_at": datetime.utcnow(),
                "guild_id": str(member.guild.id)
            }
        elif before.channel and not after.channel:
            start_time = self.voice_start.pop(uid, None)
            if start_time:
                if isinstance(start_time, dict):
                    started_at = start_time.get("started_at")
                    guild_id = start_time.get("guild_id", str(member.guild.id))
                else:
                    started_at = start_time
                    guild_id = str(member.guild.id)
                duration = (datetime.utcnow() - started_at).total_seconds() / 60
                self.stats["voice"].setdefault(uid, 0)
                self.stats["voice"][uid] += duration
                self.stats["servers"].setdefault(guild_id, {"messages": 0, "commands": 0, "invites": 0, "bans": 0, "kicks": 0, "voice_time": 0})
                self.stats["servers"][guild_id]["voice_time"] = self.stats["servers"][guild_id].get("voice_time", 0) + duration
                bucket = self._daily_bucket()
                bucket["voice"][uid] = bucket["voice"].get(uid, 0) + duration
                bucket["server_voice"][guild_id] = bucket["server_voice"].get(guild_id, 0) + duration
                save_stats(self.stats)

    @tasks.loop(minutes=1)
    async def save_stats_loop(self):
        # Add ongoing voice time
        self.stats.setdefault("voice", {})
        now = datetime.utcnow()
        for uid, start in self.voice_start.items():
            started_at = start.get("started_at") if isinstance(start, dict) else start
            guild_id = start.get("guild_id") if isinstance(start, dict) else None
            duration = (now - started_at).total_seconds() / 60
            self.stats["voice"].setdefault(uid, 0)
            self.stats["voice"][uid] += 1  # Add 1 minute per loop
            bucket = self._daily_bucket()
            bucket["voice"][uid] = bucket["voice"].get(uid, 0) + 1
            if guild_id:
                self.stats["servers"].setdefault(guild_id, {"messages": 0, "commands": 0, "invites": 0, "bans": 0, "kicks": 0, "voice_time": 0})
                self.stats["servers"][guild_id]["voice_time"] = self.stats["servers"][guild_id].get("voice_time", 0) + 1
                bucket["server_voice"][guild_id] = bucket["server_voice"].get(guild_id, 0) + 1
        save_stats(self.stats)

    @app_commands.command(name="สถิติผู้ใช้", description="แสดงสถิติของผู้ใช้")
    @app_commands.describe(user="ผู้ใช้ที่ต้องการดูสถิติ (ถ้าไม่ระบุจะแสดงสถิติของคุณ)", days="จำนวนวันย้อนหลัง (0 = รวมทั้งหมด)")
    async def user_stats(self, interaction: discord.Interaction, user: discord.User = None, days: Optional[int] = 0):
        """แสดงสถิติของผู้ใช้"""
        await interaction.response.defer(ephemeral=False)
        try:
            target_user = user or interaction.user
            user_id = str(target_user.id)

            if user_id not in self.stats["messages"]:
                await interaction.followup.send(
                    "❌ ไม่พบข้อมูลสถิติของผู้ใช้นี้",
                    ephemeral=True
                )
                return

            days = max(0, min(int(days or 0), 365))
            keys = self._date_keys_for_days(days) if days else None
            label = f"{days} วันล่าสุด" if days else "รวมทั้งหมด"
            embed = self.build_user_stats_embed(user_id, target_user.display_name, keys, label)
            view = StatsRangeView(self, "user", user_id, target_user.display_name)
            await interaction.followup.send(embed=embed, view=view)

        except Exception as e:
            logger.error(f"Error showing user stats: {e}")
            await interaction.followup.send(
                "❌ เกิดข้อผิดพลาดในการแสดงสถิติ",
                ephemeral=True
            )

    @app_commands.command(name="สถิติเซิร์ฟเวอร์", description="แสดงสถิติของเซิร์ฟเวอร์")
    @app_commands.describe(days="จำนวนวันย้อนหลัง (0 = รวมทั้งหมด)")
    async def server_stats(self, interaction: discord.Interaction, days: Optional[int] = 0):
        """แสดงสถิติของเซิร์ฟเวอร์"""
        await interaction.response.defer(ephemeral=False)
        try:
            server_id = str(interaction.guild.id)

            if server_id not in self.stats["servers"]:
                await interaction.followup.send(
                    "❌ ไม่พบข้อมูลสถิติของเซิร์ฟเวอร์นี้",
                    ephemeral=True
                )
                return

            days = max(0, min(int(days or 0), 365))
            keys = self._date_keys_for_days(days) if days else None
            label = f"{days} วันล่าสุด" if days else "รวมทั้งหมด"
            embed = self.build_server_stats_embed(interaction.guild, keys, label)
            view = StatsRangeView(self, "server", server_id, interaction.guild.name)
            await interaction.followup.send(embed=embed, view=view)

        except Exception as e:
            logger.error(f"Error showing server stats: {e}")
            await interaction.followup.send(
                "❌ เกิดข้อผิดพลาดในการแสดงสถิติ",
                ephemeral=True
            )

    @app_commands.command(name="อันดับผู้ใช้", description="แสดงอันดับผู้ใช้ตามหมวดหมู่")
    @app_commands.describe(category="หมวดหมู่เริ่มต้นที่ต้องการดูอันดับ")
    @app_commands.choices(category=[
        app_commands.Choice(name="ข้อความ", value="messages"),
        app_commands.Choice(name="เวลาในช่องเสียง", value="voice"),
        app_commands.Choice(name="คำสั่ง", value="commands"),
    ])
    async def user_leaderboard(self, interaction: discord.Interaction, category: str = "messages"):
        """แสดงอันดับผู้ใช้"""
        await interaction.response.defer(ephemeral=False)
        try:
            if category not in {"messages", "voice", "commands"}:
                category = "messages"
            embed = await self.build_leaderboard_embed(category)
            await interaction.followup.send(embed=embed, view=LeaderboardView(self))

        except Exception as e:
            logger.error(f"Error showing leaderboard: {e}")
            await interaction.followup.send(
                "❌ เกิดข้อผิดพลาดในการแสดงอันดับ",
                ephemeral=True
            )

    @commands.command()
    async def stats(self, ctx):
        # Prepare data
        msg_counts = self.stats["messages"]
        voice_times = self.stats["voice"]
        names = self.stats["names"]

        # Top N users
        top_msg = sorted(msg_counts.items(), key=lambda x: x[1], reverse=True)[:TOP_N]
        top_voice = sorted(voice_times.items(), key=lambda x: x[1], reverse=True)[:TOP_N]

        # Plot
        fig, axs = plt.subplots(2, 1, figsize=(8, 6))
        # Messages
        msg_labels = [names.get(uid, uid) for uid, _ in top_msg]
        msg_values = [count for _, count in top_msg]
        axs[0].bar(msg_labels, msg_values, color='skyblue')
        axs[0].set_title('Top ข้อความที่ส่ง')
        axs[0].set_ylabel('จำนวนข้อความ')
        # Voice
        voice_labels = [names.get(uid, uid) for uid, _ in top_voice]
        voice_values = [v for _, v in top_voice]
        axs[1].bar(voice_labels, voice_values, color='lightgreen')
        axs[1].set_title('Top เวลาที่ใช้ในห้องพูด (นาที)')
        axs[1].set_ylabel('นาที')
        plt.tight_layout()
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png')
        buffer.seek(0)
        plt.close()

        # Text summary
        summary = "**Top ข้อความ:**\n"
        summary += "\n".join(f"{i+1}. {names.get(uid, uid)}: {count}" for i, (uid, count) in enumerate(top_msg))
        summary += "\n\n**Top Voice:**\n"
        summary += "\n".join(f"{i+1}. {names.get(uid, uid)}: {int(voice)} นาที" for i, (uid, voice) in enumerate(top_voice))

        await ctx.send(summary)
        await ctx.send(file=discord.File(fp=buffer, filename='stats.png'))

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def resetstats(self, ctx):
        self.stats = {"messages": {}, "voice": {}, "names": {}}
        save_stats(self.stats)
        await ctx.send("รีเซ็ตสถิติเรียบร้อยแล้ว")

async def setup(bot):
    """Setup function for the stats cog"""
    await bot.add_cog(Stats(bot))
    logger.info("Stats cog loaded")
