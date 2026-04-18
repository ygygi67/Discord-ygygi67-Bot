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
        model_dir = os.path.abspath("data/models/separator")
        os.makedirs(model_dir, exist_ok=True)
        
        cmd = [
            "audio-separator",
            input_path,
            "--output_dir", output_dir,
            "--model_filename", model_name,
            "--output_format", "MP3",
            "--model_file_dir", model_dir
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
            # Show the last part of the output where the actual error is, avoiding startup info logs
            short_err = err_msg[-300:].strip() if err_msg else "Unknown"
            raise Exception(f"AI ทำงานล้มเหลว: {short_err}")
            
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
            # ตรวจสอบลำดับคิว
            queue_pos = 1
            if hasattr(self.bot.queue, 'get_queue_position'):
                queue_pos = await self.bot.queue.get_queue_position(task_id, 'vocal_separation')
            
            # ดึง Original Response เพื่อเอา ID มาใช้อัปเดตสถานะ (แบบเดียวกับโหลดคลิป)
            msg = await interaction.original_response()
            task_data["msg_id"] = msg.id
            
            await self.bot.queue.submit_task(task)
            
            await interaction.edit_original_response(
                content=f"📥 **รับงานแยกเสียงร้องเรียบร้อย!**\n🆔 `งาน: {task_id}`\n📊 คิวปัจจุบัน: `ลำดับที่ {queue_pos}`\n⚙️ โหมด: `{mode}`\n⏳ ระบบจะแจ้งเตือนที่นี่เมื่อเสร็จสิ้น..."
            )
        else:
            await interaction.followup.send("⚠️ ระบบคิวไม่พร้อมใช้งาน จะรันงานแบบชั่วคราว (ไม่รันต่อถ้ารีสตาร์ท)")
            asyncio.create_task(self.process_queue_task(task))
    async def _upload_to_catbox(self, file_path: str, filename: str) -> Optional[str]:
        """อัปโหลดไฟล์ขึ้น catbox.moe"""
        try:
            url = "https://catbox.moe/user/api.php"
            async with aiohttp.ClientSession() as session:
                with open(file_path, 'rb') as f:
                    data = aiohttp.FormData()
                    data.add_field('reqtype', 'fileupload')
                    data.add_field('fileToUpload', f, filename=filename)
                    async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                        if resp.status == 200:
                            result = await resp.text()
                            if result.strip().startswith("https://"):
                                return result.strip()
                        logger.warning(f"[Separator] Catbox upload failed: HTTP {resp.status}")
        except Exception as e:
            logger.warning(f"[Separator] Catbox upload error: {e}")
        return None

    async def process_queue_task(self, task: Task):
        """จัดการงานจากคิว ประมวลผล และส่งผลลัพธ์ลง Channel (รองรับ Session Resilience)"""
        if not self.bot.is_ready():
            await self.bot.wait_until_ready()
            
        link = task.data['link']
        channel_id = task.data['channel_id']
        user_id = task.data.get('user_id')
        mode = task.data.get('mode', 'vocals_std')
        model_name = task.data.get('model', 'UVR-MDX-NET-Voc_FT.onnx')
        msg_id = task.data.get("msg_id")
        
        channel = self.bot.get_channel(channel_id)
        if not channel:
            try: channel = await self.bot.fetch_channel(channel_id)
            except: return

        # พยายามดึงข้อความเดิมที่สร้างไว้ตอนสั่ง (จะอัปเดตข้อความเดิมแบบโหลดคลิป)
        progress_msg = None
        if msg_id:
            for _ in range(3): # ลองใหม่ 3 ครั้งเผื่อ Discord ยังบันทึกข้อความไม่เสร็จ
                try:
                    progress_msg = await channel.fetch_message(msg_id)
                    break
                except:
                    await asyncio.sleep(1)

        status_prefix = f"🎙️ **[AI Vocal Separator]**\n👤 <@{user_id}>\n🏷️ โหมด: `{mode}`\n"
        work_path = os.path.join(self.temp_dir, task.id)
        os.makedirs(work_path, exist_ok=True)
        
        # ฟังก์ชันช่วยอัปเดตข้อความอย่างปลอดภัย
        async def update_status(text):
            nonlocal progress_msg
            if not progress_msg:
                progress_msg = await channel.send(text)
                return
            try:
                await progress_msg.edit(content=text)
            except:
                progress_msg = await channel.send(text)

        try:
            # 1. เตรียมระบบและรายงานสถานะ
            await update_status(status_prefix + "⏳ กำลังเริ่มเตรียมการ (เตรียม Folder)...")
            
            # 2. ดาวน์โหลดเสียง
            await update_status(status_prefix + "⏳ กำลังดาวน์โหลดและแยกเสียงจาก YouTube/TikTok...")
            input_file, video_title = await self._download_audio(link, work_path)
            
            # 3. รัน AI
            await update_status(status_prefix + f"🧠 กำลังจองคิวประมวลผล AI: **{video_title}**...")
            
            async with self.ai_semaphore:
                # ตรวจสอบคิวในขณะนั้นเพื่อรายงาน
                q_info = ""
                if hasattr(self.bot, 'queue') and hasattr(self.bot.queue, 'get_active_count'):
                    active = await self.bot.queue.get_active_count('vocal_separation')
                    if active > 1: q_info = f"\n📊 (มีงานอื่นส่งมาพร้อมกัน {active-1} งาน - กำลังประมวลผลต่อ)"
                
                avg_total = self._get_avg_time(mode)
                start_ai_ts = time.time()
                
                # ฟังก์ชันจำลอง Progress Bar และเวลาที่เหลือ
                async def progress_updater(main_task):
                    while not main_task.done():
                        elapsed = time.time() - start_ai_ts
                        remaining = max(5, avg_total - elapsed)
                        percent = min(95, int((elapsed / (elapsed + remaining)) * 100))
                        
                        bar_len = 10
                        filled = int(bar_len * percent / 100)
                        bar = "▰" * filled + "▱" * (bar_len - filled)
                        
                        etc_text = f"⏳ ใช้ไป: `{int(elapsed)}s` | คาดว่าเสร็จในอีก: `{int(remaining)}s`"
                        await update_status(status_prefix + f"🧠 **กำลังประมวลผล:** `{model_name}`{q_info}\n\n{bar} `{percent}%`\n{etc_text}\n*(กำลังใช้ AI แยกเสียงออกจากกัน...)*")
                        await asyncio.sleep(8)

                # รันแยกเสียง
                output_dir = os.path.join(work_path, "output")
                os.makedirs(output_dir, exist_ok=True)
                
                # สร้าง Task สำหรับรันคำสั่ง
                separator_task = asyncio.create_task(self._run_separator(input_file, output_dir, model_name))
                # สร้าง Task สำหรับอัปเดต UI
                update_task = asyncio.create_task(progress_updater(separator_task))
                
                await separator_task
                update_task.cancel()
                
                actual_duration = time.time() - start_ai_ts
                self._update_perf(mode, actual_duration)
            
            # 4. ตรวจสอบและส่งผลลัพธ์
            output_files = list(Path(output_dir).glob("*.mp3"))
            if not output_files:
                output_files = list(Path(output_dir).glob("*.*"))
                if not output_files:
                    raise Exception("AI ไม่สามารถสร้างไฟล์ผลลัพธ์ได้ (อาจเป็นเพราะลิขสิทธิ์หรือไฟล์ต้นฉบับมีปัญหา)")

            await update_status(status_prefix + "✅ แยกเสียงร้องสำเร็จแล้ว! กำลังตรวจสอบขนาดไฟล์...")
            
            # คำนวณขีดจำกัดการอัปโหลด (ดิสคอร์ดปรับลดมาตรฐานเหลือ 10MB ในหลายเซิร์ฟเวอร์)
            upload_limit = 10 * 1024 * 1024 
            if channel.guild:
                if channel.guild.premium_tier >= 3: upload_limit = 95 * 1024 * 1024
                elif channel.guild.premium_tier >= 2: upload_limit = 48 * 1024 * 1024

            direct_files = []
            cloud_links = []
            
            for fpath in output_files:
                fsize = os.path.getsize(str(fpath))
                if fsize < 100: continue
                
                fname = os.path.basename(fpath).lower()
                clean_name = video_title
                if "vocals" in fname: clean_name += " (เสียงร้อง).mp3"
                elif "instrumental" in fname or "vocal_less" in fname: clean_name += " (ดนตรี).mp3"
                elif "drums" in fname: clean_name += " (กลอง).mp3"
                elif "bass" in fname: clean_name += " (เบส).mp3"
                elif "guitar" in fname: clean_name += " (กีตาร์).mp3"
                elif "piano" in fname: clean_name += " (เปียโน).mp3"
                elif "other" in fname: clean_name += " (อื่นๆ).mp3"
                else: clean_name += f"_{os.path.basename(fpath)}"

                if fsize > upload_limit:
                    await update_status(status_prefix + f"☁️ ไฟล์ `{clean_name}` ใหญ่เกินไป ({fsize/(1024*1024):.1f}MB) กำลังอัพโหลดขึ้น Cloud...")
                    link = await self._upload_to_catbox(str(fpath), clean_name)
                    if link:
                        cloud_links.append(f"- [{clean_name}]({link}) ({fsize/(1024*1024):.1f}MB)")
                    else:
                        cloud_links.append(f"- ⚠️ {clean_name} (ใหญ่เกินไปและอัพโหลด Cloud ล้มเหลว)")
                else:
                    direct_files.append(discord.File(str(fpath), filename=clean_name))

            # ส่งไฟล์ทีละไฟล์เพื่อป้องกัน 413 Payload Too Large (เมื่อขนาดรวมทุกไฟล์เกินขีดจำกัด)
            if direct_files:
                for idx, f in enumerate(direct_files, start=1):
                    try:
                        content = f"📦 **ผลลัพธ์ AI** ({idx}/{len(direct_files)})"
                        await channel.send(content=content, file=f)
                    except discord.HTTPException as he:
                        if he.status == 413:
                            # ถ้าส่งทีละไฟล์ยังเกิน (ไฟล์เดียว > Limit) ให้พยายามอัพขึ้น Cloud
                            logger.warning(f"[Separator] Single file too large for Discord: {f.filename}")
                            await channel.send(f"☁️ ไฟล์ `{f.filename}` ใหญ่เกินขีดจำกัดของเซิร์ฟเวอร์ กำลังอัพโหลดขึ้น Cloud โดยอัตโนมัติ...")
                            
                            try:
                                # Get original path from discord.File object
                                local_fp = getattr(f.fp, 'name', None)
                                # ต้องปิดไฟล์ก่อนนำไปใช้อีกครั้งเพื่อหลีกเลี่ยง Permission Error (Windows)
                                f.close() 
                                
                                if local_fp and os.path.exists(local_fp):
                                    link = await self._upload_to_catbox(local_fp, f.filename)
                                    if link:
                                        await channel.send(f"☁️ **ดาวน์โหลด `{f.filename}` (Cloud):**\n- {link}")
                                    else:
                                        await channel.send(f"⚠️ `{f.filename}` - มีขนาดใหญ่เกินไปและอัพโหลด Cloud ล้มเหลว")
                                else:
                                    await channel.send(f"⚠️ ไม่สามารถอัพโหลด `{f.filename}` ขึ้น Cloud ได้")
                            except Exception as ex:
                                logger.error(f"[Separator] Advanced Catbox fallback failed: {ex}")
                        else:
                            logger.error(f"[Separator] Error sending file {f.filename}: {he}")
                    finally:
                        try: f.close()
                        except: pass

            # แสดงลิงก์ Cloud (ถ้ามี)
            cloud_links_text = ""
            if cloud_links:
                cloud_links_text = "\n\n☁️ **ไฟล์ที่ขนาดใหญ่เกิน Discord Limit:**\n" + "\n".join(cloud_links)

            await update_status(status_prefix + f"✅ **แยกเสียงสำเร็จ!**\n🎬 ชื่อคลิป: **{video_title}**\n📦 รวม {len(output_files)} ไฟล์เรียบร้อย" + cloud_links_text)

            if hasattr(self.bot, 'queue'):
                await self.bot.queue.complete_task(task.id, result={"title": video_title})

        except Exception as e:
            logger.error(f"[Separator] ❌ Error in task `{task.id}`: {e}")
            await update_status(status_prefix + f"❌ **เกิดข้อผิดพลาด:** `{str(e)}`")
            if hasattr(self.bot, 'queue'):
                await self.bot.queue.complete_task(task.id, error=str(e))
        finally:
            shutil.rmtree(work_path, ignore_errors=True)


async def setup(bot):
    await bot.add_cog(VocalSeparator(bot))