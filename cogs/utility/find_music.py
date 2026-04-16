import discord
from discord import app_commands
from discord.ext import commands
import os
import time
import logging
from shazamio import Shazam

logger = logging.getLogger('discord_bot')

class FindMusic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.shazam = Shazam()
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
            
            # Use shazamio to recognize the song
            out = await self.shazam.recognize(temp_path)
            
            if not out.get("track"):
                return await interaction.followup.send("❌ ขออภัยครับ AI ไม่พบข้อมูลเพลงในไฟล์นี้ (อาจเป็นเพราะเสียงรบกวนเยอะไป ไม่มีเสียงร้องนิ่งๆ หรือเพลงยังไม่มีในระบบสตรีมมิ่งโลกครับ)")
                
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
            
            embed.set_footer(text="พลังโดย Shazamio API")
            if cover_url:
                embed.set_thumbnail(url=cover_url)
                
            # สร้างปุ่มค้นหาใน Youtube หรือ Spotify
            view = discord.ui.View()
            yt_url = f"https://www.youtube.com/results?search_query={title.replace(' ', '+')}+{subtitle.replace(' ', '+')}"
            view.add_item(discord.ui.Button(label="ค้นหาเพลงนี้ใน YouTube", url=yt_url, style=discord.ButtonStyle.link, emoji="▶️"))
                
            await interaction.followup.send(embed=embed, view=view)
            
        except Exception as e:
            logger.error(f"[Shazam] Error recognizing file: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาดในการวิเคราะห์ไฟล์เสียง: {str(e)[:100]}")
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception as ex:
                    logger.warning(f"Could not delete temp shazam file: {temp_path} - {ex}")

async def setup(bot):
    await bot.add_cog(FindMusic(bot))
