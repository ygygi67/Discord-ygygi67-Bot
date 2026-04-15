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
from typing import Optional, Dict, List
from core.shared_queue import Task

logger = logging.getLogger('discord_bot')

class VocalSeparator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.temp_dir = "data/temp/separator"
        os.makedirs(self.temp_dir, exist_ok=True)
        # จำกัดการรัน AI พร้อมกันสูงสุด 2 งาน เพื่อป้องกัน CPU พุ่ง 100% จนบอทค้าง
        self.ai_semaphore = asyncio.Semaphore(2)

    def _check_dependency(self):
        """ตรวจสอบว่าติดตั้ง audio-separator เรียบร้อยหรือไม่"""
        try:
            import audio_separator
            return True
        except ImportError:
            return False

    async def _download_audio(self, url: str, work_path: str) -> tuple[str, str]:
        """ดาวน์โหลดเสียงจาก URL โดยใช้ yt-dlp"""
        dl_path = os.path.join(work_path, "downloaded.%(ext)s")
        # รับชื่อคลิปก่อน
        video_title = "Audio File"
        try:
            cmd_title = ["yt-dlp", "--no-playlist", "--get-title", url]
            proc_title = await asyncio.create_subprocess_exec(*cmd_title, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout_title, _ = await proc_title.communicate()
            if stdout_title:
                video_title = stdout_title.decode().strip()
        except: pass

        # ดาวน์โหลด
        cmd = ["yt-dlp", "--no-playlist", "-x", "--audio-format", "mp3", "-o", dl_path, url]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc.wait()

        input_file = ""
        for f in os.listdir(work_path):
            if f.startswith("downloaded"):
                input_file = os.path.join(work_path, f)
                break
        
        if not input_file or not os.path.exists(input_file):
            raise Exception("ไม่สามารถดาวน์โหลดไฟล์เสียงได้")
            
        return input_file, video_title

    async def _run_separator(self, input_path: str, output_dir: str):
        """รันกระบวนการแยกเสียงใน Subprocess"""
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
        
        await process.communicate()
        if process.returncode != 0:
            raise Exception("กระบวนการแยกเสียงล้มเหลว")
            
        return output_dir

    @app_commands.command(name="แยกเสียงร้อง", description="แยกเสียงร้องออกจากดนตรี (ระบบอัจฉริยะ ทำงานต่อได้แม้บอทรีสตาร์ท)")
    @app_commands.describe(url="ใส่ลิงก์ YouTube ที่ต้องการแยกเสียง")
    async def separate_cmd(self, interaction: discord.Interaction, url: str):
        if not self._check_dependency():
            return await interaction.response.send_message("❌ โปรดติดตั้ง `audio-separator[onnxruntime]` ในเครื่องรันบอท", ephemeral=True)

        await interaction.response.defer(thinking=True)
        
        # สร้าง Task ลงใน Queue เพื่อให้ระบบประมวลผลต่อได้ถ้าบอทค้างหรือรีสตาร์ท
        task_id = f"vsep_{int(time.time())}_{interaction.user.id}"
        task_data = {
            "link": url,
            "channel_id": interaction.channel_id,
            "user_id": interaction.user.id,
            "guild_id": interaction.guild_id,
            "interaction_token": interaction.token
        }
        
        task = Task(id=task_id, type='vocal_separation', data=task_data)
        
        if hasattr(self.bot, 'queue'):
            await self.bot.queue.submit_task(task)
            await interaction.followup.send(f"📥 **รับงานเข้าคิวเรียบร้อย!** (ID: `{task_id}`)\nระบบจะเริ่มทำงานทันที และจะส่งไฟล์ให้ในห้องนี้แม้ว่าบอทจะรีสตาร์ทไประหว่างทางครับ")
        else:
            await interaction.followup.send("⚠️ ระบบคิวไม่พร้อมใช้งาน จะรันงานแบบชั่วคราว (ไม่รันต่อถ้ารีสตาร์ท)")
            asyncio.create_task(self.process_queue_task(task))

    async def process_queue_task(self, task: Task):
        """จัดการงานจากคิว ประมวลผล และส่งผลลัพธ์ลง Channel (รองรับ Session Resilience)"""
        # รอจนกว่าบอทจะพร้อมจริงๆ เพื่อป้องกัน Session is closed หลังจากบูต
        if not self.bot.is_ready():
            await self.bot.wait_until_ready()
            
        link = task.data['link']
        channel_id = task.data['channel_id']
        user_id = task.data.get('user_id')
        
        # ค้นหา Channel
        channel = self.bot.get_channel(channel_id)
        if not channel:
            try: channel = await self.bot.fetch_channel(channel_id)
            except: return

        status_prefix = f"🎵 **[AI Vocal Separator]**\n👤 ผู้ขอ: <@{user_id}>\n🔗 ลิงก์: {link}\n"
        work_path = os.path.join(self.temp_dir, task.id)
        os.makedirs(work_path, exist_ok=True)
        
        progress_msg = None
        
        # ฟังก์ชันช่วยส่งข้อความแบบปลอดภัย (ป้องกัน Session is closed)
        async def safe_send(text, **kwargs):
            if not self.bot.is_ready() or self.bot.is_closed(): return None
            try: return await channel.send(text, **kwargs)
            except Exception as e:
                logger.warning(f"[Separator] safe_send failed: {e}")
                return None

        async def safe_edit(msg, text):
            if not msg or self.bot.is_closed(): return
            try: await msg.edit(content=text)
            except Exception as e:
                logger.warning(f"[Separator] safe_edit failed: {e}")

        try:
            # รายงานสถานะเริ่มต้น
            progress_msg = await safe_send(status_prefix + "⏳ ระบบกำลังเตรียมการ...")
            
            # 1. ดาวน์โหลด
            await safe_edit(progress_msg, status_prefix + "⏳ กำลังดาวน์โหลดไฟล์เสียงจาก YouTube...")
            input_file, video_title = await self._download_audio(link, work_path)
            
            # 2. แยกเสียง (ใช้ Semaphore จำกัดการรันพร้อมกัน)
            update_text = status_prefix + f"📦 ไฟล์: **{video_title}**\n"
            await safe_edit(progress_msg, update_text + "⏳ รอคิวว่าง (Queueing...)")
            
            async with self.ai_semaphore:
                await safe_edit(progress_msg, update_text + "⏳ [░░░░░░░░░░] 0% (Initializing AI Engine...)")
                
                output_dir = os.path.join(work_path, "output")
                os.makedirs(output_dir, exist_ok=True)
                
                # รันแยกเสียง
                sep_task = asyncio.create_task(self._run_separator(input_file, output_dir))
                
                steps = [
                    "▓░░░░░░░░░] 10% (Loading UVR Model...)",
                    "▓▓░░░░░░░░] 25% (Processing Blocks...)",
                    "▓▓▓░░░░░░░] 35% (Vocal Extraction...)",
                    "▓▓▓▓░░░░░░] 45% (Cleaning Noise...)",
                    "▓▓▓▓▓░░░░░] 55% (Singing Voice Isolation...)",
                    "▓▓▓▓▓▓░░░░] 65% (Generating Instrumental...)",
                    "▓▓▓▓▓▓▓░░░] 75% (Combining Layers...)",
                    "▓▓▓▓▓▓▓▓░░] 85% (Finalizing Audio...)",
                    "▓▓▓▓▓▓▓▓▓░] 95% (Exporting MP3...)"
                ]
                
                for step in steps:
                    if sep_task.done(): break
                    await safe_edit(progress_msg, update_text + f"⏳ [{step}")
                    await asyncio.sleep(8)
                    
                await sep_task
                await safe_edit(progress_msg, update_text + "✅ [▓▓▓▓▓▓▓▓▓▓] 100% (AI Processing Finished!)")
            
            # 3. ส่งไฟล์
            result_files = [str(f) for f in Path(output_dir).glob("*.mp3")]
            if not result_files: raise Exception("AI ไม่สร้างไฟล์ผลลัพธ์")
            
            files_to_send = []
            for fpath in result_files:
                fname = os.path.basename(fpath)
                final_name = video_title
                if "(Vocals)" in fname: final_name += " (Vocals).mp3"
                elif "(Instrumental)" in fname: final_name += " (Instrumental).mp3"
                else: final_name += f"_{fname}"
                files_to_send.append(discord.File(fpath, filename=final_name))
            
            if channel:
                try:
                    await channel.send(content=f"✅ **แยกเสียงสำเร็จ!**\n📦 คลิป: **{video_title}**\n👤 <@{user_id}>", files=files_to_send)
                except:
                    # ถ้าส่งไม่ได้ (เครื่องอาจจะรวน) ให้รอ 5 วิแล้วลองส่งอีกครั้งครั้งสุดท้าย
                    await asyncio.sleep(5)
                    await channel.send(content=f"✅ **แยกเสียงสำเร็จ!**\n📦 คลิป: **{video_title}**\n👤 <@{user_id}>", files=files_to_send)
            
            # ปิดงานใน DB
            if hasattr(self.bot, 'queue'):
                await self.bot.queue.complete_task(task.id, result={"title": video_title})
                
        except Exception as e:
            err_text = f"❌ เกิดข้อผิดพลาดในงาน `{task.id}`: {str(e)}"
            logger.error(f"[Separator] {err_text}")
            if channel: await safe_send(err_text)
            if hasattr(self.bot, 'queue'): await self.bot.queue.complete_task(task.id, error=str(e))
        finally:
            if progress_msg:
                try: await progress_msg.delete()
                except: pass
            shutil.rmtree(work_path, ignore_errors=True)

    @app_commands.command(name="เช็คคิวแยกเสียง", description="ดูรายการงานแยกเสียงที่กำลังรอคิว")
    async def check_queue(self, interaction: discord.Interaction):
        if not hasattr(self.bot, 'queue'):
            return await interaction.response.send_message("❌ ระบบคิวไม่พร้อมใช้งาน", ephemeral=True)
        
        stats = await self.bot.queue.get_stats()
        pending = stats.get('pending', 0)
        processing = stats.get('processing', 0)
        completed = stats.get('completed', 0)
        failed = stats.get('failed', 0)
        
        embed = discord.Embed(
            title="📊 สถิติคิวงานแยกเสียง (AI Vocal Separator)",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="⏳ กำลังรอคิว", value=f"`{pending}` งาน", inline=True)
        embed.add_field(name="🏃 กำลังประมวลผล", value=f"`{processing}` งาน", inline=True)
        embed.add_field(name="✅ สำเร็จแล้ว", value=f"`{completed}` งาน", inline=True)
        embed.add_field(name="❌ ล้มเหลว", value=f"`{failed}` งาน", inline=True)
        
        msg = "💡 ระบบระจำกัดให้รันพร้อมกันได้สูงสุด `2` งาน เพื่อความเสถียรครับ"
        if pending > 0:
            msg += f"\nคิวของคุณจะเริ่มทำงานทันทีเมื่อถึงลำดับครับ"
            
        embed.set_footer(text=msg)
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(VocalSeparator(bot))