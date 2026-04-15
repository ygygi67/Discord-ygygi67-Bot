import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
import tempfile
import shutil
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger('discord_bot')

class VocalSeparator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.temp_dir = "data/temp/separator"
        os.makedirs(self.temp_dir, exist_ok=True)

    def _check_dependency(self):
        """ตรวจสอบว่าติดตั้ง audio-separator เรียบร้อยหรือไม่"""
        try:
            import audio_separator
            return True
        except ImportError:
            return False

    async def _run_separator(self, input_path: str, output_dir: str):
        """รันกระบวนการแยกเสียงใน Subprocess"""
        # ใช้โมเดล UVR-MDX-NET-Voc_FT (ให้คุณภาพสูงและสมดุล)
        # หากต้องการความเร็วสูงกว่านี้สามารถเปลี่ยนโมเดลได้
        cmd = [
            "audio-separator",
            input_path,
            "--output_dir", output_dir,
            "--model_filename", "UVR-MDX-NET-Voc_FT.onnx",
            "--output_format", "MP3"
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            logger.error(f"[Separator] Error: {stderr.decode()}")
            raise Exception(f"กระบวนการแยกเสียงล้มเหลว: {stderr.decode()[:200]}")
            
        return output_dir

    @app_commands.command(name="แยกเสียงร้อง", description="แยกเสียงร้องออกจากดนตรีโดยใช้ AI (ใช้เวลาประมวลผลสักครู่)")
    @app_commands.describe(
        file="แนบไฟล์เสียง (MP3, WAV, ฯลฯ)",
        url="ใส่ลิงก์ YouTube หรือลิงก์เสียงอื่นๆ"
    )
    async def separate(self, interaction: discord.Interaction, file: Optional[discord.Attachment] = None, url: Optional[str] = None):
        # 1. Defer ทันทีเพื่อป้องกัน Interaction Timeout (3 วินาที)
        await interaction.response.defer(thinking=True)

        if not self._check_dependency():
            return await interaction.followup.send(
                "❌ ระบบนี้ต้องการการติดตั้งเพิ่มเติม\nกรุณารันคำสั่ง `pip install \"audio-separator[onnxruntime]\"` ที่เครื่องรันบอทก่อนครับ"
            )

        if not file and not url:
            return await interaction.followup.send("❌ กรุณาแนบไฟล์หรือใส่ลิงก์ที่ต้องการแยกเสียงครับ")
        
        start_time = time.time()
        session_id = f"sep_{int(start_time)}"
        work_path = os.path.join(self.temp_dir, session_id)
        os.makedirs(work_path, exist_ok=True)
        
        try:
            input_file = ""
            base_name = "audio"
            
            # --- ขั้นตอนที่ 1: เตรียมไฟล์ ---
            if file:
                if not file.content_type or not any(x in file.content_type for x in ['audio', 'video']):
                    return await interaction.followup.send("❌ ไฟล์ที่แนบมาไม่ใช่ไฟล์เสียงหรือวิดีโอครับ")
                
                base_name = Path(file.filename).stem
                input_file = os.path.join(work_path, file.filename)
                await interaction.edit_original_response(content=f"📥 **กำลังบันทึกไฟล์...** `{file.filename}`")
                await file.save(input_file)
            else:
                # ดึงชื่อวิดีโอก่อนเพื่อความสวยงาม
                await interaction.edit_original_response(content="🔍 **กำลังตรวจสอบลิงก์...**")
                try:
                    cmd_title = ["yt-dlp", "--no-playlist", "--get-title", url]
                    proc_title = await asyncio.create_subprocess_exec(*cmd_title, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    stdout_title, _ = await proc_title.communicate()
                    if stdout_title:
                        base_name = stdout_title.decode().strip()
                except:
                    base_name = "youtube_audio"
                
                await interaction.edit_original_response(content=f"⏳ **กำลังดาวน์โหลด:** `{base_name}`\n(กรุณารอสักครู่...)")
                
                dl_path = os.path.join(work_path, "downloaded.%(ext)s")
                cmd = ["yt-dlp", "--no-playlist", "-x", "--audio-format", "mp3", "-o", dl_path, url]
                proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                await proc.wait()
                
                # หาไฟล์ที่โหลดมา
                for f in os.listdir(work_path):
                    if f.startswith("downloaded"):
                        input_file = os.path.join(work_path, f)
                        break
            
            if not input_file or not os.path.exists(input_file):
                return await interaction.followup.send("❌ ไม่สามารถดึงไฟล์เสียงมาประมวลผลได้")

            # --- ขั้นตอนที่ 2: รัน AI แยกเสียง ---
            status_msg = f"🤖 **AI กำลังแยกเสียง:** `{base_name}`\n"
            await interaction.edit_original_response(content=status_msg + "⏳ [░░░░░░░░░░] 0% (Starting AI...)")
            
            output_dir = os.path.join(work_path, "output")
            os.makedirs(output_dir, exist_ok=True)
            
            # รันแยกเสียงและพยายามอัปเดตสถานะหลอกๆ เพื่อให้ไม่ดูค้าง
            separator_task = asyncio.create_task(self._run_separator(input_file, output_dir))
            
            # อัปเดต Progress Bar ปลอมๆ ระหว่างรอ (เนื่องจาก audio-separator ไม่บอก % ตลอดเวลา)
            progress_steps = [
                "▓░░░░░░░░░] 10% (Loading Model...)",
                "▓▓░░░░░░░░] 25% (Initializing ONNX...)",
                "▓▓▓░░░░░░░] 35% (Inference Engine Start...)",
                "▓▓▓▓░░░░░░] 45% (Processing Audio Blocks...)",
                "▓▓▓▓▓░░░░░] 55% (Singing Voice Detection...)",
                "▓▓▓▓▓▓░░░░] 65% (Extracting Instrumentals...)",
                "▓▓▓▓▓▓▓░░░] 75% (Finalizing Layers...)",
                "▓▓▓▓▓▓▓▓░░] 85% (Exporting MP3...)",
                "▓▓▓▓▓▓▓▓▓░] 95% (Almost done...)"
            ]
            
            for step in progress_steps:
                if separator_task.done():
                    break
                await interaction.edit_original_response(content=status_msg + f"⏳ [{step}")
                await asyncio.sleep(8) # หน่วงเวลาแต่ละขั้น
                
            await separator_task
            await interaction.edit_original_response(content=status_msg + "✅ [▓▓▓▓▓▓▓▓▓▓] 100% (Completed!)")
            
            # --- ขั้นตอนที่ 3: ส่งไฟล์กลับ ---
            files_to_send = []
            output_files = os.listdir(output_dir)
            
            # ทำความสะอาดชื่อไฟล์
            clean_name = "".join(x for x in base_name if x.isalnum() or x in " -_()").strip()
            
            for f in output_files:
                f_path = os.path.join(output_dir, f)
                if "(Vocals)" in f:
                    files_to_send.append(discord.File(f_path, filename=f"{clean_name} (Vocals).mp3"))
                elif "(Instrumental)" in f:
                    files_to_send.append(discord.File(f_path, filename=f"{clean_name} (Instrumental).mp3"))
            
            duration = int(time.time() - start_time)
            await interaction.followup.send(
                content=f"✅ **ประมวลผลสำเร็จ!**\n🎵 เพลง: `{base_name}`\n⏱️ เวลาที่ใช้: `{duration // 60} นาที {duration % 60} วินาที`",
                files=files_to_send
            )

        except Exception as e:
            logger.error(f"[VocalSeparator] Global error: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาดในระบบ: {str(e)}")
            
        finally:
            # ลบไฟล์ชั่วคราวหลังทำงานเสร็จ (รอสักครู่เพื่อให้ Discord ส่งไฟล์จบก่อน)
            await asyncio.sleep(5)
            if os.path.exists(work_path):
                shutil.rmtree(work_path, ignore_errors=True)

async def setup(bot):
    await bot.add_cog(VocalSeparator(bot))