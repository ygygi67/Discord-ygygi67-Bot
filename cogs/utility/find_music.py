import discord
from discord import app_commands
from discord.ext import commands
import os
import time
import logging
import asyncio
import shutil
import re
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

            # 2. First Pass Shazam
            def run_shazam(fp):
                with open(fp, "rb") as f:
                    song_bytes = f.read()
                    shazam = Shazam(song_bytes)
                    recognize = shazam.recognizeSong()
                    for offset, result in recognize:
                        if result and result.get("matches"):
                            return result
                    return None

            await status_msg.edit(content="🔍 กำลังให้ AI วิเคราะห์เสียงเพื่อหาเพลง...")
            out = await asyncio.to_thread(run_shazam, temp_path)
            
            # 3. Second Pass if not found (Instrumental)
            if not out or not out.get("track"):
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
                    await status_msg.edit(content="🔍 สกัดดนตรีสำเร็จ! กำลังวิเคราะห์รอบที่สอง...")
                    out = await asyncio.to_thread(run_shazam, instrumental_path)
            
            if not out or not out.get("track"):
                return await status_msg.edit(content="❌ ขออภัยครับ แม้จะแยกลบเสียงรบกวนด้วย AI แล้ว แต่ก็ยังไม่พบข้อมูลเพลงนี้ครับ")
                
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
                
            # สร้าง UI View พร้อมปุ่ม YouTube และปุ่ม ฟังเพลง
            view = discord.ui.View()
            yt_url = f"https://www.youtube.com/results?search_query={title.replace(' ', '+')}+{subtitle.replace(' ', '+')}"
            view.add_item(discord.ui.Button(label="ดูใน YouTube", url=yt_url, style=discord.ButtonStyle.link, emoji="▶️"))
            view.add_item(ListenButton(title, subtitle)) # เพิ่มปุ่มฟังเพลง
                
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
