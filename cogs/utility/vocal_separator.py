import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
import tempfile
import shutil
import logging
import time
import aiohttp
import json
from pathlib import Path
from typing import Optional, Dict, List
from core.shared_queue import Task
from datetime import datetime, timedelta

logger = logging.getLogger('discord_bot')

def format_duration_th(seconds: float) -> str:
    """แปลงวินาทีเป็นข้อความภาษาไทย (X นาที Y วินาที)"""
    m, s = divmod(int(seconds), 60)
    res = []
    if m > 0: res.append(f"{m} นาที")
    if s > 0 or not res: res.append(f"{s} วินาที")
    return " ".join(res)

class VocalSeparator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.temp_dir = "data/temp/separator"
        os.makedirs(self.temp_dir, exist_ok=True)
        # จำกัดการรัน AI พร้อมกันสูงสุด 2 งาน เพื่อป้องกัน CPU พุ่ง 100% จนบอทค้าง
        self.ai_semaphore = asyncio.Semaphore(2)
        # เก็บรายการ process ที่กำลังทำงานอยู่ เพื่อสั่ง kill ตอนปิดบอท
        self.active_processes = set()
        self.perf_file = "data/vsep_performance.json"
        self._ensure_perf_file()

    def _ensure_perf_file(self):
        if not os.path.exists(self.perf_file):
            defaults = {
                "vocals_std": {"avg": 40, "count": 1},
                "vocals_ultra": {"avg": 75, "count": 1},
                "stems_4": {"avg": 130, "count": 1},
                "stems_6": {"avg": 210, "count": 1}
            }
            with open(self.perf_file, 'w', encoding='utf-8') as f:
                json.dump(defaults, f, indent=2)

    def _get_avg_time(self, mode: str) -> float:
        try:
            with open(self.perf_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get(mode, {}).get("avg", 60)
        except: return 60

    def _update_perf(self, mode: str, duration: float):
        try:
            with open(self.perf_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            entry = data.get(mode, {"avg": duration, "count": 0})
            old_avg = entry["avg"]
            count = entry["count"]
            
            # Simple moving average
            new_avg = (old_avg * count + duration) / (count + 1)
            data[mode] = {"avg": new_avg, "count": count + 1}
            
            with open(self.perf_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"[Separator] Perf update error: {e}")

    async def cog_unload(self):
        """ล้างงานที่ค้างอยู่ตอนปิด/โหลดใหม่"""
        logger.info("[Separator] Unloading cog and cleaning up processes...")
        try:
            # ใช้ wait_for เพื่อกันการค้างถาวรตอนปิดโปรเซส
            async def cleanup():
                for proc in list(self.active_processes):
                    try:
                        proc.terminate()
                        await asyncio.sleep(0.1)
                        if proc.returncode is None: proc.kill()
                    except: pass
                self.active_processes.clear()
            
            await asyncio.wait_for(cleanup(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("[Separator] Process cleanup timed out")
        except Exception as e:
            logger.error(f"[Separator] Error in cog_unload: {e}")

    def _check_dependency(self):
        """ตรวจสอบว่าติดตั้ง audio-separator เรียบร้อยหรือไม่"""
        try:
            import audio_separator
            return True
        except ImportError:
            return False

    async def _download_audio(self, url: str, work_path: str) -> tuple[str, str]:
        """ดาวน์โหลดเสียงจาก URL โดยใช้ yt-dlp (รองรับทั้งลิงก์, การค้นหา และไฟล์ดิสคอร์ด)"""
        dl_path = os.path.join(work_path, "downloaded.%(ext)s")
        
        # ปรับแต่ง URL สำหรับการค้นหา
        processed_url = url
        if not url.startswith("http"):
            processed_url = f"ytsearch1:{url}"
        elif "youtube.com/results" in url or "youtube.com/search" in url:
            # ส่ง URL ผลการค้นหาไปตรงๆ ได้เลย เพราะ yt-dlp รองรับและจะใช้ --playlist-items 1 ดึงคลิปแรก
            processed_url = url

        video_title = "Audio File"
        try:
            cmd_title = ["yt-dlp", "--no-playlist", "--get-title", "--playlist-items", "1", processed_url]
            proc_title = await asyncio.create_subprocess_exec(*cmd_title, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            self.active_processes.add(proc_title)
            stdout_title, _ = await proc_title.communicate()
            if proc_title in self.active_processes: self.active_processes.remove(proc_title)
            if stdout_title: video_title = stdout_title.decode().strip()
        except: pass

        cmd = ["yt-dlp", "--no-playlist", "--playlist-items", "1", "-x", "--audio-format", "mp3", "-o", dl_path, processed_url]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self.active_processes.add(proc)
        stdout_dl, stderr_dl = await proc.communicate()
        if proc in self.active_processes: self.active_processes.remove(proc)

        input_file = ""
        for f in os.listdir(work_path):
            if f.startswith("downloaded"):
                input_file = os.path.join(work_path, f)
                break
        if not input_file or not os.path.exists(input_file):
            err_msg = stderr_dl.decode() if stderr_dl else "Unknown error"
            logger.error(f"[Separator] yt-dlp failed: {err_msg[-300:]}")
            raise Exception("ไม่สามารถดาวน์โหลดไฟล์เสียงได้ (โปรดตรวจสอบลิงก์หรือชื่อเพลง)")
            
        return input_file, video_title

    async def _run_separator(self, input_path: str, output_dir: str, model_name: str):
        """รันกระบวนการแยกเสียงใน Subprocess"""
        model_dir = os.path.abspath("data/models/separator")
        os.makedirs(model_dir, exist_ok=True)
        
        # audio-separator จะพยายามใช้ CUDA โดยอัตโนมัติถ้าติดตั้ง onnxruntime-gpu
        cmd = [
            "audio-separator",
            input_path,
            "--output_dir", output_dir,
            "--model_filename", model_name,
            "--output_format", "MP3",
            "--model_file_dir", model_dir,
            "--log_level", "info"
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
            raise Exception(f"AI ทำงานล้มเหลว: {err_msg[-300:].strip()}")
            
        return output_dir

    @app_commands.command(name="แยกเสียงร้อง", description="แยกเสียงร้องออกจากดนตรี (รองรับลิงก์ YouTube, ชื่อเพลง, หรือไฟล์ดิสคอร์ด)")
    @app_commands.describe(
        url="ใส่ลิงก์ YouTube, ชื่อเพลงที่ต้องการค้นหา, หรือลิงก์ไฟล์เสียงโดยตรง",
        mode="เลือกโหมดการแยก (แยกเครื่องดนตรี, แยกเสียงคุณภาพสูง)"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="🎙️ เสียงร้อง + ดนตรี (มาตรฐาน)", value="vocals_std"),
        app_commands.Choice(name="🌟 เสียงร้อง + ดนตรี (คุณภาพสูงสุด)", value="vocals_ultra"),
        app_commands.Choice(name="🥁 แยก 4 ชิ้น", value="stems_4"),
        app_commands.Choice(name="🎸 แยก 6 ชิ้น", value="stems_6")
    ])
    async def separate_cmd(self, interaction: discord.Interaction, url: str, mode: str = "vocals_std"):
        if not self._check_dependency():
            return await interaction.response.send_message("❌ โปรดติดตั้ง `audio-separator[onnxruntime]` ในเครื่องบอท", ephemeral=True)

        await interaction.response.defer(thinking=True)
        
        model_map = {
            "vocals_std": "UVR-MDX-NET-Voc_FT.onnx",
            "vocals_ultra": "model_bs_roformer_ep_368_sdr_12.9628.ckpt",
            "stems_4": "htdemucs_ft.yaml",
            "stems_6": "htdemucs_6s.yaml"
        }
        
        target_model = model_map.get(mode, "UVR-MDX-NET-Voc_FT.onnx")
        task_id = f"vsep_{int(time.time())}_{interaction.user.id}"
        task_data = {
            "url": url,
            "channel_id": interaction.channel_id,
            "user_id": interaction.user.id,
            "guild_id": interaction.guild_id,
            "mode": mode,
            "model": target_model
        }
        
        task = Task(id=task_id, type='vocal_separation', data=task_data)
        
        if hasattr(self.bot, 'queue'):
            msg = await interaction.original_response()
            task_data["msg_id"] = msg.id
            await self.bot.queue.submit_task(task)
            await interaction.edit_original_response(
                content=f"📥 **รับงานแยกเสียงร้องเรียบร้อย!**\n🆔 `งาน: {task_id}`\n⚙️ โหมด: `{mode}`\n⏳ ระบบจะแจ้งเตือนที่นี่เมื่อเสร็จสิ้น..."
            )
        else:
            asyncio.create_task(self.process_queue_task(task))

    async def _upload_to_catbox(self, file_path: str, filename: str) -> Optional[str]:
        """อัปโหลดไฟล์ขึ้น catbox.moe (จำกัด 200MB)"""
        if not os.path.exists(file_path): return None
        fsize = os.path.getsize(file_path)
        if fsize > 195 * 1024 * 1024: return await self._upload_to_gofile(file_path)

        try:
            url = "https://catbox.moe/user/api.php"
            async with aiohttp.ClientSession() as session:
                with open(file_path, 'rb') as f:
                    data = aiohttp.FormData()
                    data.add_field('reqtype', 'fileupload')
                    data.add_field('fileToUpload', f, filename=filename)
                    async with session.post(url, data=data, timeout=300) as resp:
                        if resp.status == 200:
                            result = await resp.text()
                            if result.strip().startswith("https://"):
                                return result.strip()
        except: pass
        return await self._upload_to_gofile(file_path)

    async def _upload_to_gofile(self, file_path: str) -> Optional[str]:
        """อัปโหลดไฟล์ขึ้น Gofile.io"""
        if not os.path.exists(file_path): return None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://api.gofile.io/getServer', timeout=10) as resp:
                    if resp.status != 200: return None
                    data = await resp.json()
                    server = data['data']['server']

                with open(file_path, 'rb') as f:
                    form = aiohttp.FormData()
                    form.add_field('file', f, filename=os.path.basename(file_path))
                    async with session.post(f"https://{server}.gofile.io/uploadFile", data=form, timeout=900) as resp:
                        if resp.status == 200:
                            res_data = await resp.json()
                            if res_data.get('status') == 'ok':
                                return res_data['data']['downloadPage']
        except: pass
        return None

    async def process_queue_task(self, task: Task):
        """ประมวลผลงานแยกเสียงจากคิว"""
        task_id = task.id
        link = task.data.get('url') or task.data.get('link')
        mode = task.data.get('mode')
        model_name = task.data.get('model')
        channel_id = task.data.get('channel_id')
        msg_id = task.data.get('msg_id')
        
        channel = self.bot.get_channel(channel_id)
        if not channel: return
        
        progress_msg = None
        if msg_id:
            try: progress_msg = await channel.fetch_message(msg_id)
            except: pass
            
        status_prefix = f"🆔 `งาน: {task_id}`\n"
        work_path = os.path.join(self.temp_dir, task_id)
        os.makedirs(work_path, exist_ok=True)
        
        async def update_status(text):
            nonlocal progress_msg
            if not progress_msg:
                progress_msg = await channel.send(text)
                return
            try: await progress_msg.edit(content=text)
            except: progress_msg = await channel.send(text)

        try:
            start_total_ts = time.time()
            await update_status(status_prefix + "⏳ กำลังเริ่มดาวน์โหลดไฟล์...")
            
            start_dl_ts = time.time()
            input_file, video_title = await self._download_audio(link, work_path)
            dl_duration = time.time() - start_dl_ts
            
            await update_status(status_prefix + f"🧠 กำลังจองคิวประมวลผล AI: **{video_title}**...")
            
            async with self.ai_semaphore:
                avg_total = self._get_avg_time(mode)
                start_ai_ts = time.time()
                
                async def progress_updater(main_task):
                    while not main_task.done():
                        elapsed = time.time() - start_ai_ts
                        remaining = max(5, avg_total - elapsed)
                        percent = min(95, int((elapsed / (elapsed + remaining)) * 100))
                        bar = "▰" * int(10 * percent / 100) + "▱" * (10 - int(10 * percent / 100))
                        eta_str = (datetime.now() + timedelta(seconds=remaining)).strftime('%H:%M:%S')
                        await update_status(status_prefix + f"🧠 **กำลังแยกเสียง:** `{model_name}`\n\n{bar} `{percent}%`\n⏳ เหลือ: **{format_duration_th(remaining)}**\n🕒 เสร็จเวลา: `{eta_str}`")
                        await asyncio.sleep(8)

                output_dir = os.path.join(work_path, "output")
                os.makedirs(output_dir, exist_ok=True)
                
                separator_task = asyncio.create_task(self._run_separator(input_file, output_dir, model_name))
                update_task = asyncio.create_task(progress_updater(separator_task))
                
                await separator_task
                update_task.cancel()
                
                ai_duration = time.time() - start_ai_ts
                self._update_perf(mode, ai_duration)
            
            await update_status(status_prefix + "📤 กำลังเตรียมส่งไฟล์...")
            start_upload_ts = time.time()
            
            output_files = [os.path.join(output_dir, f) for f in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, f))]
            
            upload_limit = 10 * 1024 * 1024
            if channel.guild:
                if channel.guild.premium_tier >= 3: upload_limit = 95 * 1024 * 1024
                elif channel.guild.premium_tier >= 2: upload_limit = 48 * 1024 * 1024

            direct_files = []
            cloud_links = []
            
            for fpath in output_files:
                fsize = os.path.getsize(fpath)
                if fsize < 100: continue
                
                fname = os.path.basename(fpath).lower()
                clean_name = video_title
                if "vocals" in fname: clean_name += " (เสียงร้อง).mp3"
                elif "instrumental" in fname: clean_name += " (ดนตรี).mp3"
                else: clean_name += f"_{os.path.basename(fpath)}"

                if fsize > upload_limit:
                    url = await self._upload_to_catbox(fpath, clean_name)
                    if url: cloud_links.append(f"- [{clean_name}]({url})")
                    else: cloud_links.append(f"- ⚠️ {clean_name} (ใหญ่เกินไป)")
                else:
                    direct_files.append(discord.File(fpath, filename=clean_name))

            if direct_files:
                await channel.send(f"✅ แยกเสียง **{video_title}** เรียบร้อยแล้ว!", files=direct_files)
            if cloud_links:
                await channel.send(f"☁️ **ไฟล์ขนาดใหญ่ (Cloud):**\n" + "\n".join(cloud_links))
            
            upload_duration = time.time() - start_upload_ts
            total_duration = time.time() - start_total_ts
            
            summary = (
                f"⏱️ **สรุปเวลาที่ใช้สำหรับ {video_title}:**\n"
                f"• 📥 ดาวน์โหลด: `{format_duration_th(dl_duration)}`\n"
                f"• 🧠 ประมวลผล AI: `{format_duration_th(ai_duration)}`\n"
                f"• 📤 อัปโหลด/ส่ง: `{format_duration_th(upload_duration)}`\n"
                f"✨ **รวมทั้งสิ้น:** `{format_duration_th(total_duration)}`"
            )
            await channel.send(summary)
            await update_status(status_prefix + "✅ **งานเสร็จสมบูรณ์!**")

            if hasattr(self.bot, 'queue'):
                await self.bot.queue.complete_task(task_id, result={"title": video_title})

        except Exception as e:
            logger.error(f"[Separator] ❌ Error in task `{task_id}`: {e}")
            await update_status(status_prefix + f"❌ **เกิดข้อผิดพลาด:** `{str(e)}`")
            if hasattr(self.bot, 'queue'):
                await self.bot.queue.complete_task(task_id, error=str(e))
        finally:
            shutil.rmtree(work_path, ignore_errors=True)

async def setup(bot):
    await bot.add_cog(VocalSeparator(bot))