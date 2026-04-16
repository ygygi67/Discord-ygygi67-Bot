import discord
from discord import app_commands
from discord.ext import commands
import os
import time
import logging
import asyncio
from ShazamAPI import Shazam

logger = logging.getLogger('discord_bot')

class FindMusic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.temp_dir = "data/temp/shazam"
        os.makedirs(self.temp_dir, exist_ok=True)

    @app_commands.command(name="หาเพลง", description="ค้นหาชื่อเพลงจากไฟล์เสียงหรือวิดีโอ (Shazam AI)")
    @app_commands.describe(file="ไฟล์เสียงหรือวิดีโอที่มีเสียงเพลง")
    async def find_music_cmd(self, interaction: discord.Interaction, file: discord.Attachment):
        if not file.content_type or not ("audio" in file.content_type or "video" in file.content_type):
            return await interaction.response.send_message("❌ กรุณาอัปโหลดไฟล์เสียงหรือวิดีโอเท่านั้นครับ", ephemeral=True)
            
        await interaction.response.defer(thinking=True)
        
        temp_path = os.path.join(self.temp_dir, f"shazam_{int(time.time())}_{interaction.user.id}_{file.filename}")
        
        try:
            await file.save(temp_path)
            
            # การใช้ ShazamAPI แบบ Synchronous (pydub & requests)
            # ต้องใช้ run_in_executor (to_thread) เพื่อไม่ให้บล็อค Discord Event Loop
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

            out = await asyncio.to_thread(run_shazam, temp_path)
            
            if not out or not out.get("track"):
                return await interaction.followup.send("❌ ขออภัยครับ AI ไม่พบข้อมูลเพลงในไฟล์นี้ (อาจเป็นเพราะเสียงรบกวนเยอะไป หรือเพลงยังไม่มีในระบบสตรีมมิ่งโลกครับ)")
                
            track = out["track"]
            title = track.get("title", "ไม่ระบุชื่อเพลง")
            subtitle = track.get("subtitle", "ไม่ระบุศิลปิน")
            cover_url = track.get("images", {}).get("coverarthq") or track.get("images", {}).get("coverart")
            
            genres = track.get("genres", {}).get("primary", "ไม่ระบุ")
            
            embed = discord.Embed(
                title="🎵 ค้นพบเพลงแล้ว!",
                description="ระบบวิเคราะห์เสียงด้วย AI และเจอเพลงที่คุณตามหาครับ",
                color=discord.Color.green()
            )
            embed.add_field(name="ชื่อเพลง", value=f"**{title}**", inline=False)
            embed.add_field(name="ศิลปิน", value=f"**{subtitle}**", inline=False)
            embed.add_field(name="แนวเพลง", value=f"`{genres}`", inline=True)
            
            embed.set_footer(text="พลังโดย Shazam API (Python 3.13 Ready)")
            if cover_url:
                embed.set_thumbnail(url=cover_url)
                
            # สร้างปุ่มค้นหาใน Youtube
            view = discord.ui.View()
            yt_url = f"https://www.youtube.com/results?search_query={title.replace(' ', '+')}+{subtitle.replace(' ', '+')}"
            view.add_item(discord.ui.Button(label="ค้นหาเพลงนี้ใน YouTube", url=yt_url, style=discord.ButtonStyle.link, emoji="▶️"))
                
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            logger.error(f"[Shazam] Error recognizing file: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาดในการวิเคราะห์ไฟล์เสียง: ขออภัย ไฟล์เสียงมีรูปแบบที่ไม่รองรับ หรือเซิร์ฟเวอร์ Shazam ปฏิเสธการเข้าถึงครับ")
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception as ex:
                    logger.warning(f"Could not delete temp shazam file: {temp_path} - {ex}")

async def setup(bot):
    await bot.add_cog(FindMusic(bot))
