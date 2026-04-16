import discord
from discord import app_commands
from discord.ext import commands
import os
import time
import logging
import asyncio
import shutil
from pathlib import Path
from typing import Optional
from ShazamAPI import Shazam

logger = logging.getLogger('discord_bot')

class FindMusic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.temp_dir = "data/temp/shazam"
        os.makedirs(self.temp_dir, exist_ok=True)

    @app_commands.command(name="หาเพลง", description="ค้นหาชื่อเพลงรองรับลิงก์ YouTube/TikTok พร้อมระบบ AI ลบเสียงคนพูดอัตโนมัติหากหาไม่เจอ")
    @app_commands.describe(
        file="ไฟล์เสียงหรือวิดีโอ (ถ้ามี)",
        url="ลิงก์จาก YouTube, TikTok, Facebook (ถ้ามี)"
    )
    async def find_music_cmd(self, interaction: discord.Interaction, file: Optional[discord.Attachment] = None, url: Optional[str] = None):
        if not file and not url:
            return await interaction.response.send_message("❌ กรุณาอัปโหลดไฟล์เสียง/วิดีโอ หรือใส่ลิงก์ URL ครับ", ephemeral=True)
            
        await interaction.response.defer(thinking=True)
        temp_path = ""
        work_dir = os.path.join(self.temp_dir, f"shazam_{int(time.time())}_{interaction.user.id}")
        os.makedirs(work_dir, exist_ok=True)
        
        try:
            status_msg = await interaction.followup.send("⏳ กำลังเตรียมข้อมูลเสียง...")
            
            # 1. Download or Save File
            if file:
                if not file.content_type or not ("audio" in file.content_type or "video" in file.content_type):
                    return await status_msg.edit(content="❌ กรุณาอัปโหลดไฟล์เสียงหรือวิดีโอเท่านั้นครับ")
                temp_path = os.path.join(work_dir, file.filename)
                await file.save(temp_path)
            elif url:
                await status_msg.edit(content="⏳ กำลังดาวน์โหลดเสียงจากลิงก์...")
                dl_path = os.path.join(work_dir, "downloaded.%(ext)s")
                cmd = ["yt-dlp", "--no-playlist", "-x", "--audio-format", "mp3", "-o", dl_path, url]
                proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                await proc.wait()
                
                for f in os.listdir(work_dir):
                    if f.startswith("downloaded"):
                        temp_path = os.path.join(work_dir, f)
                        break
                
                if not temp_path or not os.path.exists(temp_path):
                    return await status_msg.edit(content="❌ ไม่สามารถดาวน์โหลดเสียงจากลิงก์ได้ครับ (อาจเป็นลิงก์ส่วนตัว หรือไม่รองรับ)")

            # 2. First Pass Shazam (วิเคราะห์จากต้นฉบับก่อน)
            def run_shazam(fp):
                with open(fp, "rb") as f:
                    song_bytes = f.read()
                    shazam = Shazam(song_bytes)
                    recognize = shazam.recognizeSong()
                    for offset, result in recognize:
                        # Если нашли совпадения (matches)
                        if result and result.get("matches"):
                            return result
                    return None

            await status_msg.edit(content="🔍 กำลังให้ AI วิเคราะห์เสียงเพื่อหาเพลง...")
            out = await asyncio.to_thread(run_shazam, temp_path)
            
            # 3. Second Pass if not found (ใช้ AI แยกเนื้อเสียงพูดออก แล้วค้นหาใหม่)
            if not out or not out.get("track"):
                await status_msg.edit(content="⚠️ ไม่พบเพลงในเสียงต้นฉบับ (อาจมีเสียง Effect หรือเสียงคนพูดทับ)\n🧠 กำลังใช้ AI **สกัดเฉพาะเสียงดนตรี** ทิ้งเสียงรบกวนเพื่อหาใหม่... (อาจใช้เวลา 1-2 นาที)")
                
                # Run AI Separator (หา Instrumental)
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
                    await status_msg.edit(content="🔍 สกัดดนตรีสำเร็จ! กำลังวิเคราะห์จังหวะเพลงรอบที่สอง...")
                    out = await asyncio.to_thread(run_shazam, instrumental_path)
            
            # ถ้ายังไม่เจออีก
            if not out or not out.get("track"):
                return await status_msg.edit(content="❌ ขออภัยครับ แม้จะแยกลบเสียงรบกวนด้วย AI แล้ว แต่ก็ยังไม่พบข้อมูลเพลงนี้ครับ (เพลงอาจเก่าเกินไป โดนลิขสิทธิ์ดัดแปลงเสียง หรือไม่มีในฐานข้อมูลสากล)")
                
            track = out["track"]
            title = track.get("title", "ไม่ระบุชื่อเพลง")
            subtitle = track.get("subtitle", "ไม่ระบุศิลปิน")
            cover_url = track.get("images", {}).get("coverarthq") or track.get("images", {}).get("coverart")
            
            genres = track.get("genres", {}).get("primary", "ไม่ระบุ")
            
            embed = discord.Embed(
                title="🎵 ค้นพบเพลงแล้ว!",
                description="ระบบวิเคราะห์เสียงด้วย AI ตรวจพบเพลงที่คุณตามหาครับ",
                color=discord.Color.green()
            )
            embed.add_field(name="ชื่อเพลง", value=f"**{title}**", inline=False)
            embed.add_field(name="ศิลปิน", value=f"**{subtitle}**", inline=False)
            embed.add_field(name="แนวเพลง", value=f"`{genres}`", inline=True)
            
            embed.set_footer(text="พลังโดย Shazam API & Audio Separator")
            if cover_url:
                embed.set_thumbnail(url=cover_url)
                
            # สร้างปุ่มค้นหาใน Youtube
            view = discord.ui.View()
            yt_url = f"https://www.youtube.com/results?search_query={title.replace(' ', '+')}+{subtitle.replace(' ', '+')}"
            view.add_item(discord.ui.Button(label="ค้นหาเพลงนี้ใน YouTube", url=yt_url, style=discord.ButtonStyle.link, emoji="▶️"))
                
            await status_msg.edit(content="✨ ตรวจพบเพลงจากเสียงที่คุณส่งมาเรียบร้อยแล้ว!", embed=embed, view=view)
            
        except Exception as e:
            logger.error(f"[Shazam] Error recognizing file: {e}")
            try:
                await status_msg.edit(content=f"❌ เกิดข้อผิดพลาดในการวิเคราะห์ไฟล์เสียง: {str(e)[:100]}")
            except: pass
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

async def setup(bot):
    await bot.add_cog(FindMusic(bot))
