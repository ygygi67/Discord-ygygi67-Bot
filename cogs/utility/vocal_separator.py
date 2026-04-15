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
        # เก็บรายการ process ที่กำลังทำงานอยู่ เพื่อสั่ง kill ตอนปิดบอท
        self.active_processes = set()

    async def cog_unload(self):
        """ล้างงานที่ค้างอยู่ตอนปิด/โหลดใหม่"""
        logger.info("[Separator] Unloading cog and cleaning up processes...")
        for proc in list(self.active_processes):
            try:
                proc.terminate()
                # ให้เวลา terminate แว็บนึง ถ้าไม่ตายก็ kill
                await asyncio.sleep(0.1)
                if proc.returncode is None: proc.kill()
            except: pass
        self.active_processes.clear()

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
            self.active_processes.add(proc_title)
            stdout_title, _ = await proc_title.communicate()
            if proc_title in self.active_processes: self.active_processes.remove(proc_title)
            
            if stdout_title:
                video_title = stdout_title.decode().strip()
        except: pass

        # ดาวน์โหลด
        cmd = ["yt-dlp", "--no-playlist", "-x", "--audio-format", "mp3", "-o", dl_path, url]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self.active_processes.add(proc)
        await proc.wait()
        if proc in self.active_processes: self.active_processes.remove(proc)

        input_file = ""
        for f in os.listdir(work_path):
            if f.startswith("downloaded"):
                input_file = os.path.join(work_path, f)
                break
        
        if not input_file or not os.path.exists(input_file):
            raise Exception("ไม่สามารถดาวน์โหลดไฟล์เสียงได้")
            
        return input_file, video_title

    async def _run_separator(self, input_path: str, output_dir: str, model_name: str):
        """รันกระบวนการแยกเสียงใน Subprocess"""
        cmd = [
            "audio-separator",
            input_path,
            "--output_dir", output_dir,
            "--model_filename", model_name,
            "--output_format", "MP3"
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        self.active_processes.add(process)
        stdout, stderr = await process.communicate()
        if process in self.active_processes: self.active_processes.remove(process)
        
        if process.returncode != 0:
            err_msg = stderr.decode() if stderr else "Unknown error"
            logger.error(f"[Separator] CLI Error: {err_msg}")
            raise Exception(f"AI ทำงานล้มเหลว: {err_msg[:100]}")
            
        return output_dir

    @app_commands.command(name="แยกเสียงร้อง", description="แยกเสียงร้องออกจากดนตรี (ระบบอัจฉริยะแบบเลือกโหมดได้)")
    @app_commands.describe(
        url="ใส่ลิงก์ YouTube ที่ต้องการแยกเสียง",
        mode="เลือกโหมดการแยก (แยกเครื่องดนตรี, แยกเสียงคุณภาพสูง)"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="🎙️ เสียงร้อง + ดนตรี (มาตรฐาน)", value="vocals_std"),
        app_commands.Choice(name="🌟 เสียงร้อง + ดนตรี (คุณภาพสูงสุด - BS-Roformer)", value="vocals_ultra"),
        app_commands.Choice(name="🥁 แยก 4 ชิ้น (ร้อง, กลอง, เบส, อื่นๆ)", value="stems_4"),
        app_commands.Choice(name="🎸 แยก 6 ชิ้น (ร้อง, กลอง, เบส, กีตาร์, เปียโน, อื่นๆ)", value="stems_6")
    ])
    async def separate_cmd(self, interaction: discord.Interaction, url: str, mode: str = "vocals_std"):
        if not self._check_dependency():
            return await interaction.response.send_message("❌ โปรดติดตั้ง `audio-separator[onnxruntime]` ในเครื่องรันบอท", ephemeral=True)

        await interaction.response.defer(thinking=True)
        
        # แผนผังโมเดลที่รองรับใน audio-separator v0.44.1+
        model_map = {
            "vocals_std": "UVR-MDX-NET-Voc_FT.onnx",
            "vocals_ultra": "model_bs_roformer_ep_368_sdr_12.9628.ckpt",
            "stems_4": "htdemucs_ft.yaml",
            "stems_6": "htdemucs_6s.yaml"
        }
        
        target_model = model_map.get(mode, "UVR-MDX-NET-Voc_FT.onnx")
        
        # สร้าง Task ลงใน Queue เพื่อให้ระบบประมวลผลต่อได้ถ้าบอทค้างหรือรีสตาร์ท
        task_id = f"vsep_{int(time.time())}_{interaction.user.id}"
        task_data = {
            "link": url,
            "channel_id": interaction.channel_id,
            "user_id": interaction.user.id,
            "guild_id": interaction.guild_id,
            "mode": mode,
            "model": target_model
        }
        
        task = Task(id=task_id, type='vocal_separation', data=task_data)
        
        if hasattr(self.bot, 'queue'):
            await self.bot.queue.submit_task(task)
            await interaction.followup.send(f"📥 **รับงานเข้าคิวเรียบร้อย!** (โหมด: `{mode}`)\n(ID: `{task_id}`)\nระบบจะส่งไฟล์ให้ในห้องนี้เมื่อเสร็จสิ้นครับ")
        else:
            await interaction.followup.send("⚠️ ระบบคิวไม่พร้อมใช้งาน จะรันงานแบบชั่วคราว (ไม่รันต่อถ้ารีสตาร์ท)")
            asyncio.create_task(self.process_queue_task(task))

    async def process_queue_task(self, task: Task):
        """จัดการงานจากคิว ประมวลผล และส่งผลลัพธ์ลง Channel (รองรับ Session Resilience)"""
        if not self.bot.is_ready():
            await self.bot.wait_until_ready()
            
        link = task.data['link']
        channel_id = task.data['channel_id']
        user_id = task.data.get('user_id')
        mode = task.data.get('mode', 'vocals_std')
        model_name = task.data.get('model', 'UVR-MDX-NET-Voc_FT.onnx')
        
        # ค้นหา Channel
        channel = self.bot.get_channel(channel_id)
        if not channel:
            try: channel = await self.bot.fetch_channel(channel_id)
            except: return

        status_prefix = f"🎵 **[AI Vocal Separator]**\n👤 ผู้ขอ: <@{user_id}>\n🏷️ โหมด: `{mode}`\n🔗 ลิงก์: {link}\n"
        work_path = os.path.join(self.temp_dir, task.id)
        os.makedirs(work_path, exist_ok=True)
        
        progress_msg = None
        
        # ฟังก์ชันช่วยส่งข้อความแบบปลอดภัย
        async def safe_send(text, **kwargs):
            if not self.bot.is_ready() or self.bot.is_closed(): return None
            try: return await channel.send(text, **kwargs)
            except: return None

        async def safe_edit(msg, text):
            if not msg or self.bot.is_closed(): return
            try: await msg.edit(content=text)
            except: pass

        try:
            # รายงานสถานะเริ่มต้น
            progress_msg = await safe_send(status_prefix + "⏳ ระบบกำลังเตรียมการ...")
            
            # 1. ดาวน์โหลด
            await safe_edit(progress_msg, status_prefix + "⏳ กำลังดาวน์โหลดไฟล์เสียงจาก YouTube...")
            input_file, video_title = await self._download_audio(link, work_path)
            
            # 2. แยกเสียง (ใช้ Semaphore จำกัดการรันพร้อมกัน)
            update_text = status_prefix + f"📦 ไฟล์: **{video_title}**\n"
            await safe_edit(progress_msg, update_text + "⏳ รอคิวว่างสำหรับ AI (Queueing...)")
            
            async with self.ai_semaphore:
                engine_msg = "Initializing BS-Roformer..." if "Roformer" in model_name else "Initializing AI Engine..."
                if "demucs" in model_name: engine_msg = "Initializing Demucs Stems Engine..."
                
                await safe_edit(progress_msg, update_text + f"⏳ [░░░░░░░░░░] 0% ({engine_msg})")
                
                output_dir = os.path.join(work_path, "output")
                os.makedirs(output_dir, exist_ok=True)
                
                # รันแยกเสียง
                sep_task = asyncio.create_task(self._run_separator(input_file, output_dir, model_name))
                
                # จำลอง Progress Bar ให้ดูมีความเคลื่อนไหว
                steps = [
                    "▓░░░░░░░░░] 10% (Loading Models...)",
                    "▓▓░░░░░░░░] 25% (Scanning Audio Patterns...)",
                    "▓▓▓░░░░░░░] 35% (Deep Learning Processing...)",
                    "▓▓▓▓░░░░░░] 45% (Isolating Components...)",
                    "▓▓▓▓▓░░░░░] 55% (Applying Filters...)",
                    "▓▓▓▓▓▓░░░░] 65% (Reconstruction Artifacts...)",
                    "▓▓▓▓▓▓▓░░░] 75% (Combining Stems...)",
                    "▓▓▓▓▓▓▓▓░░] 85% (Optimizing Output...)",
                    "▓▓▓▓▓▓▓▓▓░] 95% (Encoding MP3s...)"
                ]
                
                for step in steps:
                    if sep_task.done(): break
                    await safe_edit(progress_msg, update_text + f"⏳ [{step}")
                    wait_time = 15 if "stems" in mode else 8
                    await asyncio.sleep(wait_time)
                    
                await sep_task
                await safe_edit(progress_msg, update_text + "✅ [▓▓▓▓▓▓▓▓▓▓] 100% (AI Processing Finished!)")
            
            # 3. ส่งไฟล์
            result_files = [str(f) for f in Path(output_dir).glob("*.mp3")]
            if not result_files: raise Exception("AI ไม่สามารถสร้างไฟล์ผลลัพธ์ได้ (อาจเป็นเพราะลิขสิทธิ์หรือไฟล์ต้นฉบับมีปัญหา)")
            
            files_to_send = []
            for fpath in result_files:
                fname = os.path.basename(fpath)
                final_name = video_title
                
                if "(Vocals)" in fname or "_vocals" in fname: final_name += " (เสียงร้อง).mp3"
                elif "(Instrumental)" in fname or "_vocal_less" in fname: final_name += " (ดนตรี).mp3"
                elif "drums" in fname: final_name += " (กลอง).mp3"
                elif "bass" in fname: final_name += " (เบส).mp3"
                elif "guitar" in fname: final_name += " (กีตาร์).mp3"
                elif "piano" in fname: final_name += " (เปียโน).mp3"
                elif "other" in fname: final_name += " (เสียงอื่นๆ).mp3"
                else: final_name += f"_{fname}"
                
                files_to_send.append(discord.File(fpath, filename=final_name))
            
            if channel:
                chunks = [files_to_send[i:i + 10] for i in range(0, len(files_to_send), 10)]
                for i, chunk in enumerate(chunks):
                    prefix = "✅ **แยกเสียงสำเร็จ!**" if i == 0 else ""
                    try:
                        await channel.send(content=f"{prefix}\n📦 คลิป: **{video_title}**\n👤 <@{user_id}>\nโหมด: `{mode}`", files=chunk)
                    except:
                        await asyncio.sleep(3)
                        await channel.send(content=f"{prefix}\n📦 คลิป: **{video_title}**\n👤 <@{user_id}>", files=chunk)
            
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