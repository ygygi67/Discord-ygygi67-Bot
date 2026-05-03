import discord
from discord import app_commands
from discord.ext import commands
import os
import time
import logging
import asyncio
import shutil
import re
import math
from pathlib import Path
from typing import Optional
from ShazamAPI import Shazam

logger = logging.getLogger('discord_bot')

class ListenButton(discord.ui.Button):
    def __init__(self, title: str, subtitle: str):
        super().__init__(label="ฟังเพลง (Download & Send)", style=discord.ButtonStyle.primary, emoji="🎵")
        self.title = title
        self.subtitle = subtitle

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        
        search_query = f"{self.title} {self.subtitle}"
        work_dir = os.path.join("data/temp/shazam", f"dl_{interaction.user.id}_{int(time.time())}")
        os.makedirs(work_dir, exist_ok=True)
        
        try:
            # ใช้ yt-dlp ค้นหาและดาวน์โหลดเพลงที่ดีที่สุด
            out_tmpl = os.path.join(work_dir, "song.%(ext)s")
            cmd = [
                "yt-dlp", 
                "--no-playlist", 
                "-x", 
                "--audio-format", "mp3", 
                "--max-filesize", "25M",
                "-o", out_tmpl, 
                f"ytsearch1:{search_query}"
            ]
            
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await proc.communicate()
            
            # หาไฟล์ที่โหลดมาได้
            file_path = ""
            for f in os.listdir(work_dir):
                if f.endswith(".mp3"):
                    file_path = os.path.join(work_dir, f)
                    break
            
            if file_path and os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                # เช็คลิมิตไฟล์ของดิสคอร์ด (ปกติ 25MB)
                limit = interaction.guild.filesize_limit if interaction.guild else 25 * 1024 * 1024
                
                if file_size > limit:
                    await interaction.followup.send(f"❌ ไฟล์เพลงมีขนาดใหญ่เกินไป ({file_size/1024/1024:.1f}MB) เกินขีดจำกัดของเซิร์ฟเวอร์นี้ครับ", ephemeral=True)
                else:
                    # ส่งไฟล์
                    await interaction.followup.send(
                        content=f"🎵 จัดให้ตามคำขอครับ! นี่คือเพลง **{self.title} - {self.subtitle}**",
                        file=discord.File(file_path, filename=f"{self.title}.mp3")
                    )
            else:
                await interaction.followup.send("❌ ไม่พบเพลงที่ต้องการดาวน์โหลด หรือเกิดข้อผิดพลาดในการโหลดครับ", ephemeral=True)
                
        except Exception as e:
            logger.error(f"[ListenButton] Error: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {str(e)}", ephemeral=True)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

class FindMusic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.temp_dir = "data/temp/shazam"
        os.makedirs(self.temp_dir, exist_ok=True)

    async def _run_process(self, *cmd):
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode("utf-8", errors="ignore"), stderr.decode("utf-8", errors="ignore")

    async def _probe_duration(self, file_path: str) -> float:
        code, stdout, _ = await self._run_process(
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
        )
        if code != 0:
            return 0.0
        try:
            return max(0.0, float(stdout.strip()))
        except Exception:
            return 0.0

    def _build_segments(self, duration: float):
        if duration <= 0:
            return [(0.0, 10.0)]
        if duration <= 12:
            return [(0.0, min(10.0, duration))]
        if duration <= 30:
            segment_len = max(6.0, min(10.0, duration / 3))
            starts = [0.0, max(0.0, (duration - segment_len) / 2), max(0.0, duration - segment_len)]
            return [(start, min(segment_len, duration - start)) for start in starts]

        segment_len = 10.0
        sample_count = min(12, max(4, math.ceil(duration / 45)))
        max_start = max(0.0, duration - segment_len)
        starts = [round((max_start * i) / max(1, sample_count - 1), 2) for i in range(sample_count)]
        return [(start, min(segment_len, duration - start)) for start in starts]

    async def _extract_segment(self, source: str, output: str, start: float, length: float, speed: float = 1.0) -> bool:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", f"{start:.2f}",
            "-t", f"{length:.2f}",
            "-i", source,
            "-vn",
            "-ac", "1",
            "-ar", "44100",
        ]
        if abs(speed - 1.0) > 0.01:
            cmd += ["-af", f"asetrate=44100*{speed:.3f},aresample=44100"]
        cmd += ["-b:a", "128k", output]
        code, _, stderr = await self._run_process(*cmd)
        if code != 0:
            logger.warning(f"[Shazam] ffmpeg segment failed speed={speed} start={start}: {stderr[:300]}")
        return code == 0 and os.path.exists(output) and os.path.getsize(output) > 1024

    def _track_key(self, track: dict) -> str:
        title = str(track.get("title", "")).strip().lower()
        subtitle = str(track.get("subtitle", "")).strip().lower()
        return f"{title}|{subtitle}"

    def _format_ts(self, seconds: float) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _run_shazam_file(self, fp: str):
        with open(fp, "rb") as f:
            song_bytes = f.read()
            shazam = Shazam(song_bytes)
            recognize = shazam.recognizeSong()
            for offset, result in recognize:
                if result and result.get("matches") and result.get("track"):
                    return result
        return None

    async def _recognize_multi_song(self, source_path: str, work_dir: str, status_msg):
        duration = await self._probe_duration(source_path)
        segments = self._build_segments(duration)
        speeds = [1.0, 0.88, 1.12]
        found = {}

        for index, (start, length) in enumerate(segments, 1):
            await status_msg.edit(
                content=(
                    f"🔍 กำลังสแกนเพลงหลายช่วง... `{index}/{len(segments)}` "
                    f"ช่วง `{self._format_ts(start)}-{self._format_ts(start + length)}`"
                )
            )
            for speed in speeds:
                segment_path = os.path.join(work_dir, f"segment_{index}_{str(speed).replace('.', '_')}.mp3")
                if not await self._extract_segment(source_path, segment_path, start, length, speed=speed):
                    continue
                out = await asyncio.to_thread(self._run_shazam_file, segment_path)
                if not out or not out.get("track"):
                    continue
                track = out["track"]
                key = self._track_key(track)
                if not key.strip("|"):
                    continue
                item = found.setdefault(key, {"track": track, "hits": [], "speed": speed})
                item["hits"].append(start)
                if abs(speed - 1.0) < abs(item.get("speed", 1.0) - 1.0):
                    item["speed"] = speed

        return list(found.values()), duration

    @app_commands.command(name="หาเพลง", description="ค้นหาชื่อเพลงจากลิงก์ YouTube/TikTok หรือลิงก์ข้อความ Discord ที่มีไฟล์")
    @app_commands.describe(
        url="ลิงก์จาก YouTube, TikTok, Facebook หรือ ลิงก์ข้อความดิสคอร์ดที่มีไฟล์เสียง/วิดีโอ"
    )
    async def find_music_cmd(self, interaction: discord.Interaction, url: str):
        if not url:
            return await interaction.response.send_message("❌ กรุณาใส่ลิงก์ URL ครับ", ephemeral=True)
            
        await interaction.response.defer(thinking=True)
        temp_path = ""
        work_dir = os.path.join(self.temp_dir, f"shazam_{int(time.time())}_{interaction.user.id}")
        os.makedirs(work_dir, exist_ok=True)
        
        try:
            status_msg = await interaction.followup.send("⏳ กำลังเตรียมข้อมูลเสียง...")
            
            # ตรวจสอบว่าเป็นลิงก์ข้อความ Discord หรือไม่
            attachment = None
            msg_link_match = re.search(r"discord\.com/channels/(\d+|@me)/(\d+)/(\d+)", url)
            
            if msg_link_match:
                try:
                    await status_msg.edit(content="⏳ กำลังดึงไฟล์จากลิงก์ข้อความ Discord...")
                    c_id = int(msg_link_match.group(2))
                    m_id = int(msg_link_match.group(3))
                    
                    channel = self.bot.get_channel(c_id)
                    if not channel:
                        channel = await self.bot.fetch_channel(c_id)
                    
                    msg = await channel.fetch_message(m_id)
                    if msg.attachments:
                        attachment = msg.attachments[0]
                        if not attachment.content_type or not ("audio" in attachment.content_type or "video" in attachment.content_type):
                             return await status_msg.edit(content="❌ ไฟล์ในลิงก์ข้อความนั้นไม่ใช่ไฟล์เสียงหรือวิดีโอครับ")
                        
                        temp_path = os.path.join(work_dir, attachment.filename)
                        await attachment.save(temp_path)
                    else:
                        return await status_msg.edit(content="❌ ข้อความตามลิงก์ที่ส่งมาไม่มีไฟล์แนบครับ")
                except Exception as e:
                    return await status_msg.edit(content=f"❌ ไม่สามารถดึงข้อมูลจากลิงก์ข้อความได้: {str(e)}")
            
            # ถ้าไม่ใช่ลิงก์ข้อความ หรือไม่มี Attachment ให้ลองใช้ yt-dlp โหลดจาก URL
            if not attachment:
                await status_msg.edit(content="⏳ กำลังดาวน์โหลดเสียงจากลิงก์...")
                dl_path = os.path.join(work_dir, "downloaded.%(ext)s")
                cmd = ["yt-dlp", "--no-playlist", "-x", "--audio-format", "mp3", "-o", dl_path, url]
                proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, stderr = await proc.communicate()
                
                for f in os.listdir(work_dir):
                    if f.startswith("downloaded"):
                        temp_path = os.path.join(work_dir, f)
                        break
                
                if not temp_path or not os.path.exists(temp_path):
                    err_msg = stderr.decode('utf-8', errors='ignore')
                    if "Log in for access" in err_msg or "Sign in to confirm" in err_msg:
                        return await status_msg.edit(content="❌ ดาวน์โหลดไม่ได้ครับ: คลิปนี้ถูกบล็อกการเข้าถึง แนะนำให้ส่งลิงก์ข้อความที่มีไฟล์แทนครับ")
                    return await status_msg.edit(content="❌ ไม่สามารถดาวน์โหลดเสียงจากลิงก์ได้ครับ (ลิงก์อาจไม่ถูกต้อง หรือระบบป้องกันดาวน์โหลด)")

            await status_msg.edit(content="🔍 กำลังให้ AI วิเคราะห์เสียงแบบหลายช่วงเพื่อหาเพลงทั้งหมด...")
            results, duration = await self._recognize_multi_song(temp_path, work_dir, status_msg)
            
            # 3. Second Pass if not found (Instrumental)
            if not results:
                await status_msg.edit(content="⚠️ ไม่พบเพลงในเสียงต้นฉบับ\n🧠 กำลังใช้ AI **สกัดเฉพาะเสียงดนตรี** ทิ้งเสียงรบกวนเพื่อหาใหม่...")
                
                output_dir = os.path.join(work_dir, "output")
                os.makedirs(output_dir, exist_ok=True)
                sep_cmd = [
                    "audio-separator",
                    temp_path,
                    "--output_dir", output_dir,
                    "--model_filename", "UVR-MDX-NET-Voc_FT.onnx", 
                    "--output_format", "MP3"
                ]
                
                proc_sep = await asyncio.create_subprocess_exec(*sep_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                await proc_sep.wait()
                
                instrumental_path = ""
                for fpath in Path(output_dir).glob("*.mp3"):
                    if "instrumental" in fpath.name.lower() or "vocal_less" in fpath.name.lower():
                        instrumental_path = str(fpath)
                        break
                
                if instrumental_path and os.path.exists(instrumental_path):
                    await status_msg.edit(content="🔍 สกัดดนตรีสำเร็จ! กำลังวิเคราะห์หลายช่วงรอบที่สอง...")
                    results, duration = await self._recognize_multi_song(instrumental_path, work_dir, status_msg)
            
            if not results:
                return await status_msg.edit(content="❌ ขออภัยครับ ระบบลองสแกนหลายช่วง + ปรับความเร็วเสียงแล้ว แต่ยังไม่พบข้อมูลเพลงนี้ครับ")
            
            embed = discord.Embed(
                title="🎵 ค้นพบเพลงแล้ว!",
                description=f"ระบบสแกนหลายช่วงของคลิปและตรวจพบ `{len(results)}` เพลง" + (f"\nความยาวที่ตรวจ: `{duration:.1f}` วินาที" if duration else ""),
                color=discord.Color.green()
            )

            first_track = results[0]["track"]
            cover_url = first_track.get("images", {}).get("coverarthq") or first_track.get("images", {}).get("coverart")
            for idx, item in enumerate(results[:5], 1):
                track = item["track"]
                title = track.get("title", "ไม่ระบุชื่อเพลง")
                subtitle = track.get("subtitle", "ไม่ระบุศิลปิน")
                genres = track.get("genres", {}).get("primary", "ไม่ระบุ")
                hits = ", ".join(self._format_ts(hit) for hit in item.get("hits", [])[:4])
                speed = item.get("speed", 1.0)
                speed_note = "ปกติ" if abs(speed - 1.0) < 0.01 else ("ลองสโลว์เสียง" if speed < 1 else "ลองเร่งเสียง")
                embed.add_field(
                    name=f"{idx}. {title}",
                    value=f"ศิลปิน: **{subtitle}**\nแนวเพลง: `{genres}`\nเจอช่วง: `{hits or 'ไม่ระบุ'}`\nโหมดที่เจอ: `{speed_note}`",
                    inline=False
                )

            embed.set_footer(text="พลังโดย Shazam API, FFmpeg & Audio Separator")
            if cover_url:
                embed.set_thumbnail(url=cover_url)
                
            # สร้าง UI View พร้อมปุ่ม YouTube และปุ่ม ฟังเพลง
            view = discord.ui.View()
            first_title = first_track.get("title", "")
            first_subtitle = first_track.get("subtitle", "")
            yt_url = f"https://www.youtube.com/results?search_query={first_title.replace(' ', '+')}+{first_subtitle.replace(' ', '+')}"
            view.add_item(discord.ui.Button(label="ดูใน YouTube", url=yt_url, style=discord.ButtonStyle.link, emoji="▶️"))
            view.add_item(ListenButton(first_title, first_subtitle)) # เพิ่มปุ่มฟังเพลงเพลงแรก
                
            await status_msg.edit(content="✨ ตรวจพบเพลงเรียบร้อยแล้ว!", embed=embed, view=view)
            
        except Exception as e:
            logger.error(f"[Shazam] Error: {e}")
            try:
                await status_msg.edit(content=f"❌ เกิดข้อผิดพลาด: {str(e)[:100]}")
            except: pass
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

async def setup(bot):
    await bot.add_cog(FindMusic(bot))
