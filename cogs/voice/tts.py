import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncio
from gtts import gTTS
import uuid
import logging
import re
import tempfile
import speech_recognition as sr
import io
import json
import zipfile
from typing import Optional

logger = logging.getLogger('discord_bot')

TTS_DIRECT_TEXT_LIMIT = 4000
TTS_FILE_TEXT_LIMIT = 20000
TTS_CHUNK_LIMIT = 1200
AUTO_TTS_MESSAGE_LIMIT = 500
TTS_CONFIG_FILE = "data/tts_config.json"

def _resolve_primary_guild_id() -> Optional[int]:
    use_guild_scope = os.getenv("USE_GUILD_SCOPED_COMMANDS", "0").strip().lower() in {"1", "true", "yes", "on"}
    if not use_guild_scope:
        return None

    env_gid = os.getenv("DISCORD_GUILD_ID")
    if env_gid and env_gid.strip().isdigit():
        return int(env_gid)

    data_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
    if os.path.isdir(data_dir):
        for name in os.listdir(data_dir):
            m = re.match(r"^(\d{15,21})_", name)
            if m:
                return int(m.group(1))
    return None

def _guild_scope_decorator():
    guild_id = _resolve_primary_guild_id()
    if guild_id:
        return app_commands.guilds(discord.Object(id=guild_id))
    return lambda f: f

class TTSCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tts_queue = {}  # {guild_id: asyncio.Queue}
        self.is_playing = {} # {guild_id: bool}
        self.state_file = 'data/tts_state.json'
        self.config_file = TTS_CONFIG_FILE
        self.config = self._load_config()
        self.active_filenames = set() # เก็บไฟล์ที่ยังต้องใช้ห้ามลบ
        self.cleanup_task = self.bot.loop.create_task(self._initial_cleanup())

    def _load_config(self):
        os.makedirs("data", exist_ok=True)
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        else:
            data = {}
        data.setdefault("auto_tts_enabled", {})
        return data

    def _save_config(self):
        os.makedirs("data", exist_ok=True)
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)

    def _auto_tts_enabled(self, guild_id: int):
        return bool(self.config.get("auto_tts_enabled", {}).get(str(guild_id), True))

    def _set_auto_tts_enabled(self, guild_id: int, enabled: bool):
        self.config.setdefault("auto_tts_enabled", {})[str(guild_id)] = bool(enabled)
        self._save_config()

    def _split_tts_text(self, text: str, limit: int = TTS_CHUNK_LIMIT):
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return []
        chunks = []
        current = ""
        parts = re.split(r"([.!?。！？\n])", text)
        sentences = []
        for index in range(0, len(parts), 2):
            sentence = parts[index]
            if index + 1 < len(parts):
                sentence += parts[index + 1]
            sentence = sentence.strip()
            if sentence:
                sentences.append(sentence)

        for sentence in sentences or [text]:
            if len(sentence) > limit:
                for start in range(0, len(sentence), limit):
                    piece = sentence[start:start + limit].strip()
                    if piece:
                        chunks.append(piece)
                current = ""
                continue
            if current and len(current) + len(sentence) + 1 > limit:
                chunks.append(current.strip())
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            chunks.append(current.strip())
        return chunks

    def _detect_tts_language(self, text: str):
        sample = text.strip()
        if re.search(r"[\u0E00-\u0E7F]", sample):
            return "th"
        if re.search(r"[\u3040-\u30ff]", sample):
            return "ja"
        if re.search(r"[\uac00-\ud7af]", sample):
            return "ko"
        if re.search(r"[\u4e00-\u9fff]", sample):
            return "zh-CN"
        if re.search(r"[\u0400-\u04FF]", sample):
            return "ru"
        if re.search(r"[\u0600-\u06FF]", sample):
            return "ar"
        lowered = sample.lower()
        language_hints = [
            ("es", r"\b(el|la|los|las|una|para|gracias|hola|porque)\b|[¿¡ñ]"),
            ("fr", r"\b(le|la|les|des|bonjour|merci|pourquoi|avec)\b|[çœ]"),
            ("de", r"\b(der|die|das|und|nicht|danke|hallo|warum)\b|[äöüß]"),
            ("it", r"\b(il|lo|gli|ciao|grazie|perché|sono)\b"),
            ("pt", r"\b(o|a|os|as|obrigado|olá|porque|você)\b|[ãõç]"),
            ("id", r"\b(aku|kamu|terima kasih|selamat|yang|dan)\b"),
            ("vi", r"[ăâđêôơư]|[àáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]"),
        ]
        for lang, pattern in language_hints:
            if re.search(pattern, lowered):
                return lang
        return "en" if re.search(r"[a-zA-Z]", sample) else "th"

    async def _read_text_attachment(self, attachment: discord.Attachment):
        filename = (attachment.filename or "").lower()
        content_type = (attachment.content_type or "").lower()
        if not (filename.endswith(".txt") or content_type.startswith("text/")):
            raise ValueError("not_text_file")
        if attachment.size and attachment.size > 256 * 1024:
            raise ValueError("file_too_large")
        raw = await attachment.read(use_cached=True)
        return raw.decode("utf-8-sig", errors="ignore").strip()

    def _is_voice_text_channel_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return False
        if not self._auto_tts_enabled(message.guild.id):
            return False
        if not isinstance(message.author, discord.Member):
            return False
        if not message.author.voice or not message.author.voice.channel:
            return False
        return getattr(message.channel, "id", None) == message.author.voice.channel.id

    def _describe_attachment(self, attachment: discord.Attachment):
        filename = attachment.filename or "ไม่ทราบชื่อไฟล์"
        content_type = (attachment.content_type or "").lower()
        lower_name = filename.lower()
        if content_type.startswith("image/") or lower_name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
            return f"ส่งรูปภาพ {filename}"
        if content_type.startswith("audio/") or lower_name.endswith((".mp3", ".wav", ".ogg", ".m4a", ".flac", ".opus")):
            return f"ส่งไฟล์เสียง {filename}"
        if content_type.startswith("video/") or lower_name.endswith((".mp4", ".mov", ".webm", ".mkv")):
            return f"ส่งวิดีโอ {filename}"
        return f"ส่งไฟล์ {filename}"

    def _message_to_auto_tts_text(self, message: discord.Message):
        author_name = getattr(message.author, "display_name", message.author.name)
        pieces = []
        content = (message.clean_content or "").strip()
        url_pattern = r"https?://\S+"
        urls = re.findall(url_pattern, content)
        content_without_urls = re.sub(url_pattern, "", content).strip()
        if content_without_urls:
            pieces.append(content_without_urls)
        if urls:
            pieces.append(f"{author_name} ส่งลิงก์ {len(urls)} ลิงก์")
        for attachment in message.attachments:
            pieces.append(f"{author_name} {self._describe_attachment(attachment)}")
        if message.stickers:
            pieces.append(f"{author_name} ส่งสติกเกอร์")
        return " ".join(pieces).strip()

    async def _queue_tts_for_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
        text: str,
        channel: discord.abc.Messageable | None = None,
        announce: bool = False,
    ):
        text = (text or "").strip()
        if not text:
            return False
        user_channel = member.voice.channel if member.voice else None
        if not user_channel:
            return False

        if not guild.voice_client:
            await user_channel.connect()
        elif guild.voice_client.channel != user_channel:
            try:
                await guild.voice_client.move_to(user_channel)
            except Exception:
                pass

        chunks = self._split_tts_text(text)
        generated_files = []
        for index, chunk in enumerate(chunks, 1):
            filename = f"tts_temp_{uuid.uuid4().hex[:8]}_auto_{index}.mp3"

            def generate_tts(chunk_text=chunk, output=filename):
                lang = self._detect_tts_language(chunk_text)
                tts = gTTS(text=chunk_text, lang=lang)
                tts.save(output)

            await self.bot.loop.run_in_executor(None, generate_tts)
            generated_files.append((filename, chunk))

        if guild.id not in self.tts_queue:
            self.tts_queue[guild.id] = asyncio.Queue()
        for file_path, chunk in generated_files:
            await self.tts_queue[guild.id].put((file_path, chunk))
        self._save_state()

        if not self.is_playing.get(guild.id, False):
            for _ in range(5):
                if guild.voice_client and guild.voice_client.is_connected():
                    break
                await asyncio.sleep(1)
            if guild.voice_client and guild.voice_client.is_connected():
                if not guild.voice_client.is_playing():
                    await self._play_next(guild.id)
                else:
                    self.is_playing[guild.id] = True

        if announce and channel:
            try:
                await channel.send(f"🗣️ พูดตามข้อความของ {member.mention} แล้ว")
            except Exception:
                pass
        return True

    async def cog_load(self):
        """เมื่อโหลด Cog ให้ทำการพยายามพูดต่อจากเดิม"""
        asyncio.create_task(self._auto_resume())

    def _save_state(self):
        """บันทึกสถานะคิวลงไฟล์"""
        try:
            os.makedirs('data', exist_ok=True)
            data = {}
            for gid, q in self.tts_queue.items():
                # ดึงรายการทั้งหมดใน Queue ออกมาจดไว้ (เนื่องจาก asyncio.Queue ไม่มีวิธีดูตรงๆ ต้องแปลง)
                # เราจะจดเฉพาะคิวที่ค้างอยู่
                items = list(q._queue)
                if items:
                    data[str(gid)] = items
            
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving TTS state: {e}")

    async def _auto_resume(self):
        """ระบบมุดเข้าห้องเดิมมาพูดต่ออัตโนมัติ"""
        await self.bot.wait_until_ready()
        await asyncio.sleep(5) # รอให้ Music ระบบอื่นเข้าห้องให้เสร็จก่อน

        if not os.path.exists(self.state_file):
            return

        try:
            if os.path.getsize(self.state_file) == 0:
                return

            with open(self.state_file, 'r', encoding='utf-8') as f:
                try:
                    state = json.load(f)
                except json.JSONDecodeError:
                    return # Ignore empty or corrupted JSON file
            
            for gid_str, items in state.items():
                guild_id = int(gid_str)
                guild = self.bot.get_guild(guild_id)
                if not guild: continue

                # หาว่าควรเข้าช่องไหน (มุดตาม Music ไป หรือใช้ห้องเดิม)
                vc = guild.voice_client
                if not vc and items:
                    # ถ้าบอทไม่ได้อยู่ในห้องเสียง แต่มีคิวค้าง ให้หาห้องที่มีสมาชิกอยู่ หรือห้องที่บอทควรมุดไป
                    # (ในที่นี้เราจะรอดูสักพัก ถ้าบอทไม่มุดตามระบบเพลงไป เราจะยังไม่เริ่มพูดเพื่อประหยัดทรัพยากร)
                    continue
                
                if vc and items:
                    self.tts_queue[guild_id] = asyncio.Queue()
                    for item in items:
                        if os.path.exists(item[0]):
                            await self.tts_queue[guild_id].put(item)
                            self.active_filenames.add(item[0])
                    
                    if not self.is_playing.get(guild_id, False) and not self.tts_queue[guild_id].empty():
                        await self._play_next(guild_id)
                        
        except Exception as e:
            logger.error(f"Error in TTS auto-resume: {e}")

    async def _initial_cleanup(self):
        """ลบไฟล์ขยะที่ค้างจากการรันครั้งก่อน แบบฉลาดขึ้น"""
        await self.bot.wait_until_ready()
        await asyncio.sleep(10) # รอให้ auto_resume เซ็ต active_filenames ก่อน
        count = 0
        try:
            for file in os.listdir('.'):
                if file.startswith('tts_temp_') and file.endswith('.mp3'):
                    if file not in self.active_filenames:
                        try:
                            os.remove(file)
                            count += 1
                        except: pass
            if count > 0:
                logger.info(f"Cleanup finished: removed {count} old TTS temp files")
        except Exception as e:
            logger.error(f"Error during initial TTS cleanup: {e}")

    async def _play_next(self, guild_id):
        if guild_id not in self.tts_queue or self.tts_queue[guild_id].empty():
            self.is_playing[guild_id] = False
            self._save_state()
            return

        self.is_playing[guild_id] = True
        guild = self.bot.get_guild(guild_id)
        if not guild or not guild.voice_client or not guild.voice_client.is_connected():
            self.is_playing[guild_id] = False
            return

        file_path, text = await self.tts_queue[guild_id].get()
        self._save_state() # อัปเดตคิวหลังจากดึงออกมา

        def after_playing(error):
            if error:
                logger.error(f"Error in TTS playback: {error}")
            
            # ลบไฟล์ทิ้งแบบอัจฉริยะ (รอ FFmpeg ปล่อยไฟล์)
            async def delayed_delete(path):
                # รอให้แน่ใจว่า FFmpeg ปล่อยไฟล์แน่ๆ
                await asyncio.sleep(2)
                for _ in range(5): 
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                        break
                    except Exception:
                        await asyncio.sleep(2)
            
            self.bot.loop.create_task(delayed_delete(file_path))
            self.bot.loop.create_task(self._play_next(guild_id))

        try:
            guild.voice_client.play(discord.FFmpegPCMAudio(file_path), after=after_playing)
        except Exception as e:
            logger.error(f"Error playing TTS: {e}")
            # ถ้าเล่นไม่สำเร็จ ให้ลบไฟล์ทันที
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except:
                pass
            self.bot.loop.create_task(self._play_next(guild_id))

    @app_commands.command(name="พูดตาม", description="สั่งให้บอทพูดข้อความ หรืออ่านข้อความจากไฟล์ .txt")
    @_guild_scope_decorator()
    @app_commands.describe(
        text="ข้อความที่ต้องการให้บอทพูด (สูงสุด 4,000 ตัวอักษรตามข้อจำกัด Discord)",
        ไฟล์ข้อความ="ไฟล์ .txt สำหรับข้อความยาว (ระบบรับสูงสุด 20,000 ตัวอักษร)",
        ส่งไฟล์เสียง="แนบไฟล์เสียงที่สร้างกลับมาในแชทด้วยหรือไม่",
        พูดอัตโนมัติ="เปิด/ปิดการพูดตามอัตโนมัติในแชทช่องเสียงของเซิร์ฟเวอร์นี้"
    )
    async def speak(
        self,
        interaction: discord.Interaction,
        text: Optional[str] = None,
        ไฟล์ข้อความ: Optional[discord.Attachment] = None,
        ส่งไฟล์เสียง: bool = False,
        พูดอัตโนมัติ: Optional[bool] = None,
    ):
        """รับข้อความเสียงและสร้าง TTS"""
        if พูดอัตโนมัติ is not None:
            if not interaction.guild:
                return await interaction.response.send_message("❌ ตั้งค่าพูดอัตโนมัติได้เฉพาะในเซิร์ฟเวอร์", ephemeral=True)
            can_manage = (
                getattr(interaction.user, "guild_permissions", None)
                and interaction.user.guild_permissions.manage_guild
            )
            if not can_manage:
                return await interaction.response.send_message("❌ ต้องมีสิทธิ์จัดการเซิร์ฟเวอร์เพื่อเปิด/ปิดพูดอัตโนมัติ", ephemeral=True)
            self._set_auto_tts_enabled(interaction.guild.id, พูดอัตโนมัติ)
            status = "เปิด" if พูดอัตโนมัติ else "ปิด"
            if not text and not ไฟล์ข้อความ:
                return await interaction.response.send_message(f"✅ {status}ระบบพูดตามอัตโนมัติในแชทช่องเสียงแล้ว", ephemeral=True)

        if not text and not ไฟล์ข้อความ:
            return await interaction.response.send_message("❌ กรุณาใส่ข้อความ หรือแนบไฟล์ `.txt` ครับ", ephemeral=True)
        
        # ถ้าไม่ได้อยู่ห้องเสียง ให้ส่งไฟล์เสียงกลับไปอัตโนมัติแทนการ error
        if not interaction.user.voice:
            ส่งไฟล์เสียง = True

        user_channel = interaction.user.voice.channel if interaction.user.voice else None
        guild = interaction.guild

        await interaction.response.defer()

        try:
            if ไฟล์ข้อความ:
                text_from_file = await self._read_text_attachment(ไฟล์ข้อความ)
                text = f"{text or ''}\n{text_from_file}".strip()
        except ValueError as error:
            code = str(error)
            if code == "not_text_file":
                return await interaction.followup.send("❌ รองรับเฉพาะไฟล์ `.txt` หรือไฟล์ text เท่านั้น")
            if code == "file_too_large":
                return await interaction.followup.send("❌ ไฟล์ข้อความใหญ่เกินไป จำกัดที่ 256KB")
            return await interaction.followup.send("❌ อ่านไฟล์ข้อความไม่สำเร็จ")

        text = (text or "").strip()
        if len(text) > TTS_FILE_TEXT_LIMIT:
            return await interaction.followup.send(f"❌ ข้อความยาวเกินไป ระบบรับสูงสุด `{TTS_FILE_TEXT_LIMIT:,}` ตัวอักษร")

        chunks = self._split_tts_text(text)
        if not chunks:
            return await interaction.followup.send("❌ ข้อความว่างเปล่า หรือไม่มีส่วนที่อ่านได้")

        # เชื่อมต่อช่องเสียง (เฉพาะกรณีที่คนพิมพ์อยู่ในห้องเสียง)
        if user_channel:
            if not guild.voice_client:
                try:
                    await user_channel.connect()
                except Exception as e:
                    return await interaction.followup.send(f"❌ ไม่สามารถเชื่อมต่อกับช่องเสียงได้: {e}")
            elif guild.voice_client.channel != user_channel:
                try:
                    await guild.voice_client.move_to(user_channel)
                except:
                    pass

        try:
            generated_files = []
            for index, chunk in enumerate(chunks, 1):
                filename = f"tts_temp_{uuid.uuid4().hex[:8]}_{index}.mp3"

                def generate_tts(chunk_text=chunk, output=filename):
                    lang = self._detect_tts_language(chunk_text)
                    tts = gTTS(text=chunk_text, lang=lang)
                    tts.save(output)

                await self.bot.loop.run_in_executor(None, generate_tts)
                generated_files.append((filename, chunk))
            
            # ตอบกลับ
            if ส่งไฟล์เสียง:
                if len(generated_files) == 1:
                    with open(generated_files[0][0], "rb") as audio_file:
                        audio_bytes = audio_file.read()
                    preview_file = discord.File(io.BytesIO(audio_bytes), filename=f"tts_preview_{interaction.user.id}.mp3")
                    await interaction.followup.send(
                        f"🗣️ **สั่งให้บอทพูด:** `{len(text):,}` ตัวอักษร / `{len(chunks)}` ท่อน\n> {text[:1800]}",
                        file=preview_file
                    )
                else:
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                        for index, (file_path, _) in enumerate(generated_files, 1):
                            archive.write(file_path, arcname=f"tts_part_{index:02d}.mp3")
                    zip_buffer.seek(0)
                    await interaction.followup.send(
                        f"🗣️ **สร้างเสียงพูดแล้ว:** `{len(text):,}` ตัวอักษร / `{len(chunks)}` ท่อน",
                        file=discord.File(zip_buffer, filename=f"tts_preview_{interaction.user.id}.zip")
                    )
            else:
                await interaction.followup.send(f"🗣️ **สั่งให้บอทพูด:** `{len(text):,}` ตัวอักษร / `{len(chunks)}` ท่อน\n> {text[:1800]}")
            
            # ใช้งาน Queue และเล่นเสียงเฉพาะเมื่อแชนแนลมีอยู่จริง (อยู่ในห้องเสียง)
            if user_channel:
                if guild.id not in self.tts_queue:
                    self.tts_queue[guild.id] = asyncio.Queue()
                    
                for file_path, chunk in generated_files:
                    await self.tts_queue[guild.id].put((file_path, chunk))
                self._save_state() # จดคิวลงไฟล์ทันที
                
                # ถ้าระบบไม่ได้เล่นอยู่ให้เริ่มเล่น
                if not self.is_playing.get(guild.id, False):
                    # ให้โอกาสบอทเชื่อมต่อสำเร็จนิดนึง (กรณีเพิ่งกด Join)
                    for _ in range(5):
                        if guild.voice_client and guild.voice_client.is_connected():
                            break
                        await asyncio.sleep(1)

                    if guild.voice_client and guild.voice_client.is_connected():
                        if not guild.voice_client.is_playing():
                            await self._play_next(guild.id)
                        else:
                            self.is_playing[guild.id] = True
                    else:
                        self.is_playing[guild.id] = False
            else:
                # ถ้าไม่ได้เข้าห้องเสียง แปลว่าสร้างมาเพื่อเอาไฟล์เฉยๆ สามารถลบไฟล์ต้นฉบับได้เลย
                for file_path, _ in generated_files:
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    except:
                        pass
                    
        except Exception as e:
            if not self.bot.is_closed():
                import traceback
                logger.error(f"Error generating TTS: {e}\n{traceback.format_exc()}")
                try:
                    await interaction.followup.send("❌ เกิดข้อผิดพลาดในการสร้างเสียงพูด กรุณาลองใหม่")
                except: pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self._is_voice_text_channel_message(message):
            return
        content = self._message_to_auto_tts_text(message)
        if not content or content.startswith(("/", "!", ".")):
            return
        if len(content) > AUTO_TTS_MESSAGE_LIMIT:
            try:
                await message.channel.send(
                    f"⚠️ ข้อความยาวเกินไปสำหรับพูดตามอัตโนมัติ จำกัด `{AUTO_TTS_MESSAGE_LIMIT}` ตัวอักษร "
                    "ถ้าต้องการพูดยาวให้ใช้ `/พูดตาม` ครับ",
                    delete_after=8,
                )
            except Exception:
                pass
            return
        try:
            await self._queue_tts_for_member(message.guild, message.author, content)
        except Exception as e:
            logger.error(f"Auto voice-channel TTS failed: {e}")

    def _parse_message_reference(self, raw: str):
        value = raw.strip()
        link_pattern = r"^https?://(?:ptb\.|canary\.)?discord\.com/channels/(\d+|@me)/(\d+)/(\d+)$"
        match = re.match(link_pattern, value)
        if match:
            guild_id_raw, channel_id_raw, message_id_raw = match.groups()
            guild_id = None if guild_id_raw == "@me" else int(guild_id_raw)
            return guild_id, int(channel_id_raw), int(message_id_raw)

        if value.isdigit():
            return None, None, int(value)

        raise ValueError("invalid_reference")

    async def _resolve_message_from_input(
        self,
        interaction: discord.Interaction,
        link_or_id: str,
        channel: discord.TextChannel | None,
    ) -> discord.Message:
        _, channel_id, message_id = self._parse_message_reference(link_or_id)

        # Case 1: Full message link was provided
        if channel_id is not None:
            target_channel = self.bot.get_channel(channel_id)
            if target_channel is None:
                target_channel = await self.bot.fetch_channel(channel_id)

            if not isinstance(target_channel, (discord.TextChannel, discord.Thread)):
                raise ValueError("invalid_channel_type")

            return await target_channel.fetch_message(message_id)

        # Case 2: Only message ID was provided
        if channel is not None:
            target_channel = channel
        elif isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            target_channel = interaction.channel
        else:
            raise ValueError("channel_required")

        return await target_channel.fetch_message(message_id)

    def _pick_audio_attachment(self, message: discord.Message) -> discord.Attachment | None:
        audio_exts = (".ogg", ".oga", ".mp3", ".wav", ".m4a", ".webm", ".mp4")
        for attachment in message.attachments:
            content_type = (attachment.content_type or "").lower()
            filename = attachment.filename.lower()
            if content_type.startswith("audio/") or filename.endswith(audio_exts):
                return attachment
        return None

    async def _convert_to_wav(self, source_path: str, wav_path: str):
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            source_path,
            "-ac",
            "1",
            "-ar",
            "16000",
            wav_path,
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            details = stderr.decode("utf-8", errors="ignore")[:400]
            raise RuntimeError(f"ffmpeg_convert_failed: {details}")

    async def _transcribe_wav(self, wav_path: str) -> str:
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)

        def _recognize_th():
            return recognizer.recognize_google(audio_data, language="th-TH")

        def _recognize_en():
            return recognizer.recognize_google(audio_data, language="en-US")

        try:
            return await self.bot.loop.run_in_executor(None, _recognize_th)
        except sr.UnknownValueError:
            return await self.bot.loop.run_in_executor(None, _recognize_en)

    @app_commands.command(
        name="ถอดเสียงข้อความ",
        description="ถอดเสียงจากข้อความที่มีไฟล์เสียง (รองรับลิงก์หรือ Message ID)"
    )
    @_guild_scope_decorator()
    @app_commands.describe(
        ข้อความลิงก์หรือไอดี="วางลิงก์ข้อความ Discord หรือ Message ID",
        ช่อง="เลือกช่องเมื่อใส่แค่ Message ID (ถ้าไม่ใส่จะใช้ช่องปัจจุบัน)",
        ส่งไฟล์ต้นฉบับ="ให้บอทแนบไฟล์เสียงต้นฉบับกลับมาพร้อมผลถอดเสียงหรือไม่"
    )
    async def transcribe_message_audio(
        self,
        interaction: discord.Interaction,
        ข้อความลิงก์หรือไอดี: str,
        ช่อง: discord.TextChannel | None = None,
        ส่งไฟล์ต้นฉบับ: bool = False,
    ):
        await interaction.response.defer(ephemeral=False)

        temp_input = None
        temp_wav = None
        try:
            message = await self._resolve_message_from_input(interaction, ข้อความลิงก์หรือไอดี, ช่อง)
            attachment = self._pick_audio_attachment(message)
            if attachment is None:
                return await interaction.followup.send(
                    "❌ ไม่พบไฟล์เสียงในข้อความนี้ กรุณาใส่ลิงก์/ID ของข้อความที่มีไฟล์เสียงหรือ Voice Message"
                )

            raw_audio = await attachment.read(use_cached=True)
            input_suffix = os.path.splitext(attachment.filename)[1] or ".ogg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=input_suffix) as source_file:
                source_file.write(raw_audio)
                temp_input = source_file.name

            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as wav_file:
                temp_wav = wav_file.name

            await self._convert_to_wav(temp_input, temp_wav)
            transcript = await self._transcribe_wav(temp_wav)

            if not transcript.strip():
                return await interaction.followup.send("⚠️ ถอดเสียงเสร็จแล้ว แต่ไม่ได้ข้อความที่อ่านได้")

            message_link = (
                f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"
                if message.guild
                else f"https://discord.com/channels/@me/{message.channel.id}/{message.id}"
            )
            output = (
                f"🎙️ **ผลการถอดเสียง**\n"
                f"🔗 ที่มา: {message_link}\n\n"
                f"{transcript}"
            )

            if len(output) > 1900:
                output = output[:1890] + "..."

            if ส่งไฟล์ต้นฉบับ:
                safe_name = attachment.filename or "source_audio"
                await interaction.followup.send(
                    output,
                    file=discord.File(temp_input, filename=safe_name)
                )
            else:
                await interaction.followup.send(output)

        except ValueError as error:
            code = str(error)
            if code == "invalid_reference":
                await interaction.followup.send(
                    "❌ รูปแบบไม่ถูกต้อง กรุณาใส่ลิงก์ข้อความ Discord หรือ Message ID ที่ถูกต้อง"
                )
            elif code == "invalid_channel_type":
                await interaction.followup.send("❌ ลิงก์นี้ไม่ได้ชี้ไปยังช่องข้อความที่รองรับ")
            elif code == "channel_required":
                await interaction.followup.send("❌ ถ้าใส่แค่ Message ID กรุณาเลือกช่องด้วย")
            else:
                await interaction.followup.send(f"❌ ไม่สามารถดึงข้อความได้: {code}")
        except discord.Forbidden:
            await interaction.followup.send("❌ บอทไม่มีสิทธิ์เข้าถึงช่องหรือข้อความเป้าหมาย")
        except discord.NotFound:
            await interaction.followup.send("❌ ไม่พบข้อความที่ระบุ กรุณาตรวจสอบลิงก์หรือ ID")
        except FileNotFoundError:
            await interaction.followup.send("❌ ไม่พบ `ffmpeg` ในเครื่องบอท กรุณาติดตั้ง ffmpeg ก่อนใช้งานคำสั่งนี้")
        except sr.RequestError:
            await interaction.followup.send("❌ ระบบถอดเสียงภายนอกไม่พร้อมใช้งานในขณะนี้ กรุณาลองใหม่อีกครั้ง")
        except sr.UnknownValueError:
            await interaction.followup.send("⚠️ ไม่สามารถแปลงเสียงเป็นข้อความได้ (เสียงอาจเบา/ไม่ชัด)")
        except Exception as e:
            import traceback
            logger.error(f"Error transcribing message audio: {e}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ เกิดข้อผิดพลาดระหว่างการถอดเสียง")
        finally:
            for path in (temp_input, temp_wav):
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

async def setup(bot):
    await bot.add_cog(TTSCommand(bot))
