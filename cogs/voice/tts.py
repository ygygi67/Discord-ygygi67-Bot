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
from typing import Optional

logger = logging.getLogger('discord_bot')

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
        self.active_filenames = set() # เก็บไฟล์ที่ยังต้องใช้ห้ามลบ
        self.cleanup_task = self.bot.loop.create_task(self._initial_cleanup())

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
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
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

    @app_commands.command(name="พูดตาม", description="สั่งให้บอทพูดข้อความที่คุณต้องการ (พิมพ์ยาวแค่ไหนก็ได้)")
    @_guild_scope_decorator()
    @app_commands.describe(
        text="ข้อความที่ต้องการให้บอทพูด",
        ส่งไฟล์เสียง="แนบไฟล์เสียงที่สร้างกลับมาในแชทด้วยหรือไม่"
    )
    async def speak(self, interaction: discord.Interaction, text: str, ส่งไฟล์เสียง: bool = False):
        """รับข้อความเสียงและสร้าง TTS"""
        
        # ตรวจสอบการเชื่อมต่อเสียง (ถ้าขอแค่ไฟล์เสียง ไม่ต้องอยู่ห้องเสียงก็ได้)
        if not interaction.user.voice and not ส่งไฟล์เสียง:
            return await interaction.response.send_message("❌ คุณต้องอยู่ในช่องเสียงก่อน หรือเลือกตั้งค่า `ส่งไฟล์เสียง` เป็น True เพื่อรับแค่ไฟล์ครับ", ephemeral=True)

        user_channel = interaction.user.voice.channel if interaction.user.voice else None
        guild = interaction.guild

        await interaction.response.defer()

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
            # สร้างไฟล์ออดิโอแยกชิ้นเพื่อไม่ให้ชนกันเวลาใช้งานรัวๆ
            filename = f"tts_temp_{uuid.uuid4().hex[:8]}.mp3"
            
            # ใช้ loop run_in_executor เพื่อไม่ให้การเจนเเสียงไปบล็อคการทำงานของบอท
            def generate_tts():
                tts = gTTS(text=text, lang='th')
                tts.save(filename)
                
            await self.bot.loop.run_in_executor(None, generate_tts)
            
            # ตอบกลับ
            if ส่งไฟล์เสียง:
                with open(filename, "rb") as audio_file:
                    audio_bytes = audio_file.read()
                preview_file = discord.File(io.BytesIO(audio_bytes), filename=f"tts_preview_{interaction.user.id}.mp3")
                await interaction.followup.send(
                    f"🗣️ **สั่งให้บอทพูด:**\n> {text[:1900]}",
                    file=preview_file
                )
            else:
                await interaction.followup.send(f"🗣️ **สั่งให้บอทพูด:**\n> {text[:1900]}")
            
            # ใช้งาน Queue และเล่นเสียงเฉพาะเมื่อแชนแนลมีอยู่จริง (อยู่ในห้องเสียง)
            if user_channel:
                if guild.id not in self.tts_queue:
                    self.tts_queue[guild.id] = asyncio.Queue()
                    
                await self.tts_queue[guild.id].put((filename, text))
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
                try:
                    if os.path.exists(filename):
                        os.remove(filename)
                except:
                    pass
                    
        except Exception as e:
            if not self.bot.is_closed():
                import traceback
                logger.error(f"Error generating TTS: {e}\n{traceback.format_exc()}")
                try:
                    await interaction.followup.send("❌ เกิดข้อผิดพลาดในการสร้างเสียงพูด กรุณาลองใหม่")
                except: pass

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
