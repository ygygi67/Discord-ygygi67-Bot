import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import shutil
from datetime import datetime
import logging
from collections import defaultdict
import matplotlib.pyplot as plt
import io

logger = logging.getLogger('discord_bot')

STATS_FILE = "data/stats.json"
TOP_N = 10

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
        required_keys = ["messages", "voice", "names", "servers", "commands", "bans", "kicks", "invites"]
        for key in required_keys:
            if key not in stats:
                stats[key] = {}
        return stats

    def cog_unload(self):
        self.save_stats_loop.cancel()
        save_stats(self.stats)

    def update_user_stats(self, user_id: str, category: str, value: int = 1):
        """Update user statistics"""
        if user_id not in self.stats["messages"]:
            self.stats["messages"][user_id] = 0
        self.stats["messages"][user_id] += value
        # Defensive: ensure 'names' exists
        if "names" not in self.stats:
            self.stats["names"] = {}
        self.stats["names"][user_id] = self.bot.get_user(int(user_id)).display_name
        save_stats(self.stats)

    def update_server_stats(self, server_id: str, category: str, value: int = 1):
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
            self.update_server_stats(server_id, "messages")

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
        uid = str(member.id)
        # Defensive: ensure 'names' exists
        if "names" not in self.stats:
            self.stats["names"] = {}
        self.stats["names"][uid] = member.display_name
        if after.channel and not before.channel:
            self.voice_start[uid] = datetime.utcnow()
        elif before.channel and not after.channel:
            start_time = self.voice_start.pop(uid, None)
            if start_time:
                duration = (datetime.utcnow() - start_time).total_seconds() / 60
                self.stats["voice"].setdefault(uid, 0)
                self.stats["voice"][uid] += duration
                save_stats(self.stats)

    @tasks.loop(minutes=1)
    async def save_stats_loop(self):
        # Add ongoing voice time
        self.stats.setdefault("voice", {})
        now = datetime.utcnow()
        for uid, start in self.voice_start.items():
            duration = (now - start).total_seconds() / 60
            self.stats["voice"].setdefault(uid, 0)
            self.stats["voice"][uid] += 1  # Add 1 minute per loop
        save_stats(self.stats)

    @app_commands.command(name="สถิติผู้ใช้", description="แสดงสถิติของผู้ใช้")
    @app_commands.describe(user="ผู้ใช้ที่ต้องการดูสถิติ (ถ้าไม่ระบุจะแสดงสถิติของคุณ)")
    async def user_stats(self, interaction: discord.Interaction, user: discord.User = None):
        """แสดงสถิติของผู้ใช้"""
        try:
            target_user = user or interaction.user
            user_id = str(target_user.id)

            if user_id not in self.stats["messages"]:
                await interaction.response.send_message(
                    "❌ ไม่พบข้อมูลสถิติของผู้ใช้นี้",
                    ephemeral=True
                )
                return

            user_stats = self.stats["messages"][user_id]

            embed = discord.Embed(
                title=f"📊 สถิติของ {target_user.name}",
                color=discord.Color.blue()
            )

            # Add basic stats
            embed.add_field(
                name="ข้อความ",
                value=f"ส่งข้อความ: {user_stats:,} ข้อความ",
                inline=True
            )

            # Add voice time
            hours = self.stats["voice"].get(user_id, 0) // 60
            minutes = self.stats["voice"].get(user_id, 0) % 60
            embed.add_field(
                name="เวลาในช่องเสียง",
                value=f"{hours:,} ชั่วโมง {minutes:,} นาที",
                inline=True
            )

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error showing user stats: {e}")
            await interaction.response.send_message(
                "❌ เกิดข้อผิดพลาดในการแสดงสถิติ",
                ephemeral=True
            )

    @app_commands.command(name="สถิติเซิร์ฟเวอร์", description="แสดงสถิติของเซิร์ฟเวอร์")
    async def server_stats(self, interaction: discord.Interaction):
        """แสดงสถิติของเซิร์ฟเวอร์"""
        try:
            server_id = str(interaction.guild.id)

            if server_id not in self.stats["servers"]:
                await interaction.response.send_message(
                    "❌ ไม่พบข้อมูลสถิติของเซิร์ฟเวอร์นี้",
                    ephemeral=True
                )
                return

            server_stats = self.stats["servers"][server_id]

            embed = discord.Embed(
                title=f"📊 สถิติของ {interaction.guild.name}",
                color=discord.Color.blue()
            )

            # Add basic stats
            embed.add_field(
                name="ข้อความ",
                value=f"ข้อความทั้งหมด: {server_stats['messages']:,} ข้อความ",
                inline=True
            )

            # Add voice time
            hours = self.stats["voice"].get(server_id, 0) // 60
            minutes = self.stats["voice"].get(server_id, 0) % 60
            embed.add_field(
                name="เวลาในช่องเสียง",
                value=f"{hours:,} ชั่วโมง {minutes:,} นาที",
                inline=True
            )

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error showing server stats: {e}")
            await interaction.response.send_message(
                "❌ เกิดข้อผิดพลาดในการแสดงสถิติ",
                ephemeral=True
            )

    @app_commands.command(name="อันดับผู้ใช้", description="แสดงอันดับผู้ใช้ตามหมวดหมู่")
    @app_commands.describe(category="หมวดหมู่ที่ต้องการดูอันดับ (ข้อความ/คำสั่ง/การเชิญ)")
    async def user_leaderboard(self, interaction: discord.Interaction, category: str = "messages"):
        """แสดงอันดับผู้ใช้"""
        try:
            # Validate category
            valid_categories = {
                "messages": "ข้อความ",
                "commands": "คำสั่ง",
                "invites_sent": "การเชิญ"
            }

            if category not in valid_categories:
                await interaction.response.send_message(
                    f"❌ หมวดหมู่ไม่ถูกต้อง\n"
                    f"หมวดหมู่ที่ใช้ได้: {', '.join(valid_categories.values())}",
                    ephemeral=True
                )
                return

            # Select correct stats dictionary
            if category == "messages":
                users = self.stats.get("messages", {})
            elif category == "commands":
                users = self.stats.get("commands", {})
            elif category == "invites_sent":
                users = self.stats.get("invites_sent", {})
            else:
                users = {}

            # Get top 10 users
            sorted_users = sorted(
                users.items(),
                key=lambda x: x[1],
                reverse=True
            )[:TOP_N]

            embed = discord.Embed(
                title=f"🏆 อันดับผู้ใช้ - {valid_categories[category]}",
                color=discord.Color.gold()
            )

            # Add leaderboard entries
            for i, (user_id, count) in enumerate(sorted_users, 1):
                try:
                    user = await self.bot.fetch_user(int(user_id))
                    value = count
                    if category == "messages":
                        value = f"{value:,} ข้อความ"
                    elif category == "commands":
                        value = f"{value:,} ครั้ง"
                    elif category == "invites_sent":
                        value = f"{value:,} ครั้ง"

                    embed.add_field(
                        name=f"{i}. {user.name}",
                        value=value,
                        inline=False
                    )
                except:
                    continue

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f"Error showing leaderboard: {e}")
            await interaction.response.send_message(
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
