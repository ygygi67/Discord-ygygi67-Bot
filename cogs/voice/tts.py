import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncio
from gtts import gTTS
import uuid
import logging

logger = logging.getLogger('discord_bot')

class TTSCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tts_queue = {}  # {guild_id: asyncio.Queue}
        self.is_playing = {} # {guild_id: bool}
        self.cleanup_task = self.bot.loop.create_task(self._initial_cleanup())

    async def _initial_cleanup(self):
        """ลบไฟล์ขยะที่ค้างจากการรันครั้งก่อน"""
        await self.bot.wait_until_ready()
        count = 0
        try:
            for file in os.listdir('.'):
                if file.startswith('tts_temp_') and file.endswith('.mp3'):
                    try:
                        os.remove(file)
                        count += 1
                    except:
                        pass
            if count > 0:
                logger.info(f"Cleanup finished: removed {count} old TTS temp files")
        except Exception as e:
            logger.error(f"Error during initial TTS cleanup: {e}")

    async def _play_next(self, guild_id):
        if guild_id not in self.tts_queue or self.tts_queue[guild_id].empty():
            self.is_playing[guild_id] = False
            return

        self.is_playing[guild_id] = True
        guild = self.bot.get_guild(guild_id)
        if not guild or not guild.voice_client or not guild.voice_client.is_connected():
            self.is_playing[guild_id] = False
            return

        file_path, text = await self.tts_queue[guild_id].get()

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
    @app_commands.describe(text="ข้อความที่ต้องการให้บอทพูด")
    async def speak(self, interaction: discord.Interaction, text: str):
        """รับข้อความเสียงและสร้าง TTS"""
        
        # ตรวจสอบการเชื่อมต่อเสียง
        if not interaction.user.voice:
            return await interaction.response.send_message("❌ คุณต้องอยู่ในช่องเสียก่อนครับ", ephemeral=True)

        user_channel = interaction.user.voice.channel
        guild = interaction.guild

        await interaction.response.defer()

        # เชื่อมต่อช่องเสียง 
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
            
            # จัดการ Queue
            if guild.id not in self.tts_queue:
                self.tts_queue[guild.id] = asyncio.Queue()
                
            await self.tts_queue[guild.id].put((filename, text))
            
            # ตอบกลับ
            await interaction.followup.send(f"🗣️ **สั่งให้บอทพูด:**\n> {text[:1900]}")
            
            # ถ้าระบบไม่ได้เล่นอยู่ให้เริ่มเล่น
            if not self.is_playing.get(guild.id, False):
                if guild.voice_client and guild.voice_client.is_connected():
                    if not guild.voice_client.is_playing():
                        await self._play_next(guild.id)
                else:
                    self.is_playing[guild.id] = False
                    
        except Exception as e:
            import traceback
            logger.error(f"Error generating TTS: {e}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ เกิดข้อผิดพลาดในการสร้างเสียงพูด กรุณาลองใหม่")

async def setup(bot):
    await bot.add_cog(TTSCommand(bot))
