import asyncio
import json
import logging
import os
import random
import re
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

logger = logging.getLogger("discord_bot")

CONFIG_PATH = "data/alarm_warning_config.json"
CACHE_DIR = "data/alarm_media"
WARN_DIR = "Warn"
DEFAULT_WARN_SONG = "A Thousand Years Cinematic Version"
LOCAL_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus", ".webm", ".mp4", ".mkv"}

WAKE_MESSAGES = [
    "ตื่นได้แล้ววว ถึงเวลาแล้วนะ!",
    "ถึงเวลาแล้วครับ ลุกได้แล้วคนเก่ง",
    "นาฬิกาปลุกมาแล้ว อย่ากดเลื่อนในใจนะ",
    "ไปได้แล้วครับ ภารกิจรออยู่!",
    "ตื่น ๆ ๆ เวลาไม่รอใครนะ",
    "ถึงเวลาที่ตั้งไว้แล้วครับ เปิดตา เปิดใจ เปิดงาน",
    "ปลุกแบบนุ่มนวลก่อน ถ้าไม่ตื่นเดี๋ยวเพลงวนเองนะ",
    "ได้เวลาแล้วครับ อย่าให้บอทต้องร้องเพลงจนเหนื่อย",
]


class StopAlarmView(discord.ui.View):
    def __init__(self, cog: "AlarmWarning", guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(label="ปิดนาฬิกาปลุก", style=discord.ButtonStyle.danger, emoji="🛑")
    async def stop_alarm(self, interaction: discord.Interaction, button: discord.ui.Button):
        stopped = await self.cog.stop_alarm_playback(self.guild_id)
        if stopped:
            await interaction.response.send_message("🛑 ปิดนาฬิกาปลุกแล้วครับ", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ ตอนนี้ไม่มีนาฬิกาปลุกที่กำลังเล่นอยู่", ephemeral=True)


class AlarmWarning(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = self._load_config()
        self.active_alarm_guilds: set[int] = set()
        self.network_warn_task: asyncio.Task | None = None
        self.network_warn_process: asyncio.subprocess.Process | None = None
        os.makedirs(CACHE_DIR, exist_ok=True)
        os.makedirs(WARN_DIR, exist_ok=True)
        self.alarm_loop.start()
        logger.info("AlarmWarning cog initialized")

    def cog_unload(self):
        self.alarm_loop.cancel()
        if self.network_warn_task:
            self.network_warn_task.cancel()
        if self.network_warn_process and self.network_warn_process.returncode is None:
            self.network_warn_process.terminate()

    def _load_config(self):
        os.makedirs("data", exist_ok=True)
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        else:
            data = {}
        data.setdefault("warn_folder", WARN_DIR)
        data.setdefault("alarms", [])
        return data

    def _save_config(self):
        os.makedirs("data", exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)

    async def _run_process(self, *cmd):
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode("utf-8", errors="ignore"), stderr.decode("utf-8", errors="ignore")

    def _safe_name(self, text: str):
        return re.sub(r"[^a-zA-Z0-9ก-๙._-]+", "_", text).strip("_")[:80] or "alarm"

    async def _cache_audio(self, query_or_url: str, prefix: str):
        os.makedirs(CACHE_DIR, exist_ok=True)
        file_base = f"{prefix}_{self._safe_name(query_or_url)}_{int(time.time())}"
        output_template = os.path.join(CACHE_DIR, f"{file_base}.%(ext)s")
        source = query_or_url if re.match(r"https?://", query_or_url) else f"ytsearch1:{query_or_url}"
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", output_template,
            source,
        ]
        code, _, stderr = await self._run_process(*cmd)
        if code != 0:
            logger.warning(f"[AlarmWarning] yt-dlp cache failed: {stderr[:400]}")
            return None
        for filename in os.listdir(CACHE_DIR):
            if filename.startswith(file_base) and filename.lower().endswith(".mp3"):
                return os.path.join(CACHE_DIR, filename)
        return None

    def _parse_alarm_time(self, text: str):
        now = datetime.now()
        raw = text.strip().lower()
        relative = re.fullmatch(r"(\d+)\s*(m|min|นาที|h|hr|ชม|ชั่วโมง)", raw)
        if relative:
            amount = int(relative.group(1))
            unit = relative.group(2)
            return now + (timedelta(hours=amount) if unit in {"h", "hr", "ชม", "ชั่วโมง"} else timedelta(minutes=amount))

        thai_hour = re.search(r"(\d{1,2})(?:\s*โมง)(?:\s*(\d{1,2})\s*นาที)?", raw)
        if thai_hour:
            hour = int(thai_hour.group(1))
            minute = int(thai_hour.group(2) or 0)
            target = now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
            return target if target > now else target + timedelta(days=1)

        clock = re.search(r"(\d{1,2})[:.](\d{1,2})", raw)
        if clock:
            hour = int(clock.group(1))
            minute = int(clock.group(2))
            target = now.replace(hour=hour % 24, minute=minute % 60, second=0, microsecond=0)
            return target if target > now else target + timedelta(days=1)

        if raw.isdigit():
            hour = int(raw)
            target = now.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
            return target if target > now else target + timedelta(days=1)
        return None

    def _can_bot_use_voice(self, channel: discord.VoiceChannel):
        me = channel.guild.me
        perms = channel.permissions_for(me)
        return perms.connect and perms.speak

    async def _resolve_alarm_channel(self, guild: discord.Guild, member: discord.Member | None):
        if member and member.voice and member.voice.channel:
            preferred = member.voice.channel
            if isinstance(preferred, discord.VoiceChannel) and self._can_bot_use_voice(preferred):
                return preferred, False

        for channel in guild.voice_channels:
            if self._can_bot_use_voice(channel):
                if member and member.voice and member.guild.me.guild_permissions.move_members:
                    try:
                        await member.move_to(channel, reason="Alarm target channel cannot be used by bot")
                    except Exception as e:
                        logger.warning(f"[AlarmWarning] could not move member to alarm channel: {e}")
                return channel, True
        return None, False

    async def _connect_or_move(self, channel: discord.VoiceChannel):
        vc = channel.guild.voice_client
        if vc and vc.is_connected():
            if vc.channel.id != channel.id:
                await vc.move_to(channel)
            return vc
        return await channel.connect(timeout=20.0, reconnect=True)

    def _play_looping_file(self, vc: discord.VoiceClient, file_path: str, volume: float = 2.8):
        if vc.is_playing() or vc.is_paused():
            vc.stop()
        before_options = "-stream_loop -1"
        options = f"-vn -af loudnorm=I=-12:TP=-0.5:LRA=8,volume={volume}"
        vc.play(discord.FFmpegPCMAudio(file_path, before_options=before_options, options=options))

    async def stop_alarm_playback(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild or not guild.voice_client:
            return False
        vc = guild.voice_client
        if vc.is_playing() or vc.is_paused():
            vc.stop()
        self.active_alarm_guilds.discard(guild_id)
        return True

    def _warn_folder(self):
        folder = self.config.get("warn_folder") or WARN_DIR
        os.makedirs(folder, exist_ok=True)
        return folder

    def _warn_files(self):
        folder = Path(self._warn_folder())
        files = [
            str(path)
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in LOCAL_AUDIO_EXTENSIONS
        ]
        return files

    async def _play_local_warn_loop(self):
        logger.warning("[AlarmWarning] local Wi-Fi warning player started")
        while True:
            files = self._warn_files()
            if not files:
                logger.warning(f"[AlarmWarning] Warn folder is empty: {os.path.abspath(self._warn_folder())}")
                await asyncio.sleep(10)
                continue
            file_path = random.choice(files)
            try:
                cmd = [
                    "ffplay",
                    "-nodisp",
                    "-autoexit",
                    "-volume", "100",
                    file_path,
                ]
                self.network_warn_process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await self.network_warn_process.wait()
            except asyncio.CancelledError:
                if self.network_warn_process and self.network_warn_process.returncode is None:
                    self.network_warn_process.terminate()
                raise
            except FileNotFoundError:
                logger.error("[AlarmWarning] ffplay not found. Please install FFmpeg or add it to PATH.")
                return
            except Exception as e:
                logger.warning(f"[AlarmWarning] local warning playback failed: {e}")
                await asyncio.sleep(3)

    async def play_network_warning(self, diagnosis: dict | None = None):
        diagnosis = diagnosis or {}
        if diagnosis.get("kind") != "wifi_disconnected":
            return
        if self.network_warn_task and not self.network_warn_task.done():
            return
        self.network_warn_task = asyncio.create_task(self._play_local_warn_loop())

    async def stop_network_warning(self):
        if self.network_warn_task and not self.network_warn_task.done():
            self.network_warn_task.cancel()
            try:
                await self.network_warn_task
            except asyncio.CancelledError:
                pass
        if self.network_warn_process and self.network_warn_process.returncode is None:
            self.network_warn_process.terminate()
        self.network_warn_task = None
        self.network_warn_process = None
        logger.info("[AlarmWarning] local Wi-Fi warning player stopped")

    @app_commands.command(name="เพิ่มเพลงเตือนเน็ต", description="ดาวน์โหลด/เพิ่มเพลงเข้าโฟลเดอร์ Warn สำหรับเตือนตอน Wi‑Fi หลุด")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(query_or_url="ชื่อเพลงหรือ URL เช่น A Thousand Years Cinematic Version")
    async def add_network_warning_song(self, interaction: discord.Interaction, query_or_url: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        old_cache_dir = CACHE_DIR
        try:
            globals()["CACHE_DIR"] = self._warn_folder()
            path = await self._cache_audio(query_or_url, "warn")
        finally:
            globals()["CACHE_DIR"] = old_cache_dir
        note = f"บันทึกไฟล์แล้ว: `{os.path.basename(path)}`" if path else "ดาวน์โหลดไม่สำเร็จ ให้ใส่ไฟล์เองในโฟลเดอร์ Warn ได้เลย"
        await interaction.followup.send(
            f"✅ เพิ่มเพลงเตือนเน็ตแล้ว: `{query_or_url}`\n"
            f"โฟลเดอร์: `{os.path.abspath(self._warn_folder())}`\n"
            f"สถานะ: {note}",
            ephemeral=True,
        )

    @app_commands.command(name="รายการเพลงเตือนเน็ต", description="ดูไฟล์เพลงในโฟลเดอร์ Warn ที่สุ่มเล่นตอน Wi‑Fi หลุด")
    async def list_network_warning_songs(self, interaction: discord.Interaction):
        files = self._warn_files()
        lines = [f"{index}. `{os.path.basename(path)}`" for index, path in enumerate(files[:20], 1)]
        await interaction.response.send_message(
            f"โฟลเดอร์: `{os.path.abspath(self._warn_folder())}`\n" + ("\n".join(lines) if lines else "ยังไม่มีไฟล์เพลงเตือน"),
            ephemeral=True,
        )

    @app_commands.command(name="นาฬิกาปลุก", description="ตั้งนาฬิกาปลุกในช่องเสียงพร้อมเพลง/คลิปวนซ้ำ")
    @app_commands.describe(
        เวลา="เวลา เช่น 06:00, 6 โมง, 30m, 1h",
        เพลงหรือคลิป="URL หรือชื่อเพลง/คลิปที่จะให้เปิดตอนปลุก",
        ข้อความ="ข้อความปลุก ถ้าไม่ใส่บอทจะสุ่มให้",
    )
    async def set_alarm(self, interaction: discord.Interaction, เวลา: str, เพลงหรือคลิป: str, ข้อความ: str | None = None):
        if not interaction.guild:
            return await interaction.response.send_message("❌ ใช้คำสั่งนี้ในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
        target_time = self._parse_alarm_time(เวลา)
        if not target_time:
            return await interaction.response.send_message("❌ อ่านเวลาไม่ออกครับ ลองใช้ `06:00`, `6 โมง`, `30m`, `1h`", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)
        cached_path = await self._cache_audio(เพลงหรือคลิป, "alarm")
        alarm = {
            "id": f"{interaction.guild.id}_{interaction.user.id}_{int(time.time())}",
            "guild_id": interaction.guild.id,
            "user_id": interaction.user.id,
            "text_channel_id": interaction.channel_id,
            "voice_channel_id": interaction.user.voice.channel.id if interaction.user.voice else None,
            "source": เพลงหรือคลิป,
            "path": cached_path,
            "message": ข้อความ,
            "due_at": target_time.isoformat(),
            "created_at": datetime.now().isoformat(),
        }
        self.config.setdefault("alarms", []).append(alarm)
        self._save_config()

        cache_note = "แคชเพลงแล้ว" if cached_path else "ยังแคชเพลงไม่สำเร็จ จะลองโหลดอีกครั้งตอนปลุก"
        await interaction.followup.send(
            f"⏰ ตั้งนาฬิกาปลุกแล้ว: <t:{int(target_time.timestamp())}:F> (<t:{int(target_time.timestamp())}:R>)\n"
            f"เพลง/คลิป: `{เพลงหรือคลิป}`\n"
            f"สถานะเพลง: {cache_note}",
            ephemeral=True,
        )

    async def _trigger_alarm(self, alarm: dict):
        guild = self.bot.get_guild(int(alarm["guild_id"]))
        if not guild:
            return
        member = guild.get_member(int(alarm["user_id"]))
        text_channel = self.bot.get_channel(int(alarm["text_channel_id"])) if alarm.get("text_channel_id") else None
        if not text_channel:
            text_channel = next((ch for ch in guild.text_channels if ch.permissions_for(guild.me).send_messages), None)

        message = alarm.get("message") or random.choice(WAKE_MESSAGES)
        file_path = alarm.get("path")
        if not file_path or not os.path.exists(file_path):
            file_path = await self._cache_audio(alarm.get("source", DEFAULT_WARN_SONG), "alarm")
            alarm["path"] = file_path
            self._save_config()

        if not member or not member.voice:
            if text_channel:
                await text_channel.send(f"{member.mention if member else ''} ⏰ {message}".strip())
            try:
                user = await self.bot.fetch_user(int(alarm["user_id"]))
                await user.send(f"⏰ {message}\nเพลง/คลิปที่ตั้งไว้: {alarm.get('source')}")
            except Exception:
                pass
            return

        channel, moved = await self._resolve_alarm_channel(guild, member)
        if not channel:
            if text_channel:
                await text_channel.send(f"{member.mention} ⏰ {message}\n❌ บอทเข้าช่องเสียงไหนไม่ได้เลยครับ")
            return
        if not file_path:
            if text_channel:
                await text_channel.send(f"{member.mention} ⏰ {message}\n❌ โหลดเพลง/คลิปสำหรับปลุกไม่สำเร็จครับ")
            return

        vc = await self._connect_or_move(channel)
        self.active_alarm_guilds.add(guild.id)
        self._play_looping_file(vc, file_path, volume=2.6)
        if text_channel:
            moved_note = "\nย้ายไปช่องที่บอทพูดได้แล้ว" if moved else ""
            await text_channel.send(
                f"{member.mention} ⏰ {message}{moved_note}\n"
                f"กำลังเล่น `{alarm.get('source')}` วนซ้ำจนกว่าจะกดปิด",
                view=StopAlarmView(self, guild.id),
            )

    @tasks.loop(seconds=20)
    async def alarm_loop(self):
        await self.bot.wait_until_ready()
        now = datetime.now()
        pending = []
        changed = False
        for alarm in self.config.get("alarms", []):
            try:
                due_at = datetime.fromisoformat(alarm["due_at"])
            except Exception:
                changed = True
                continue
            if due_at <= now:
                changed = True
                asyncio.create_task(self._trigger_alarm(alarm))
            else:
                pending.append(alarm)
        if changed:
            self.config["alarms"] = pending
            self._save_config()


async def setup(bot):
    await bot.add_cog(AlarmWarning(bot))
