import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger('discord_bot')

class Suggestion(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config_path = "data/channels.json"
        self.cooldown_path = "data/suggestion_cooldowns.json"
        
    def _read_config(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _read_cooldowns(self):
        try:
            if os.path.exists(self.cooldown_path):
                with open(self.cooldown_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error reading suggestion cooldowns: {e}")
        return {}

    def _save_cooldown(self, user_id: int):
        cooldowns = self._read_cooldowns()
        cooldowns[str(user_id)] = datetime.now(timezone.utc).isoformat()
        try:
            with open(self.cooldown_path, "w", encoding="utf-8") as f:
                json.dump(cooldowns, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving suggestion cooldown: {e}")

    @app_commands.command(name="ข้อเสนอแนะ", description="ส่งข้อเสนอแนะหรือแจ้งปัญหาเกี่ยวกับบอท (จำกัด 1 ครั้งต่อวัน)")
    @app_commands.describe(
        content="รายละเอียดข้อเสนอแนะหรือปัญหาที่พบ",
        attachment="ส่งรูปภาพประกอบ (ถ้ามี)"
    )
    async def suggest(
        self, 
        interaction: discord.Interaction, 
        content: str, 
        attachment: discord.Attachment = None
    ):
        """ส่งข้อเสนอแนะไปยังผู้ดูแลระบบ"""
        user_id = interaction.user.id
        cooldowns = self._read_cooldowns()
        
        # ตรวจสอบ Cooldown (24 ชั่วโมง)
        if str(user_id) in cooldowns:
            last_suggest_str = cooldowns[str(user_id)]
            last_suggest = datetime.fromisoformat(last_suggest_str)
            now = datetime.now(timezone.utc)
            
            # ถ้าเป็น Naive datetime ให้แปลงเป็น UTC
            if last_suggest.tzinfo is None:
                last_suggest = last_suggest.replace(tzinfo=timezone.utc)
                
            time_passed = now - last_suggest
            if time_passed < timedelta(days=1):
                remaining = timedelta(days=1) - time_passed
                hours = int(remaining.total_seconds() // 3600)
                minutes = int((remaining.total_seconds() % 3600) // 60)
                
                await interaction.response.send_message(
                    f"⏳ คุณส่งข้อเสนอแนะไปแล้ว\nกรุณารออีก **{hours} ชั่วโมง {minutes} นาที** ก่อนส่งอีกครั้งครับ",
                    ephemeral=True
                )
                return

        # อ่านช่องทางส่ง
        config = self._read_config()
        channel_id = config.get("suggestion_channel", 1359578935951622214)
        target_channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        
        if not target_channel:
            await interaction.response.send_message("❌ ไม่สามารถส่งข้อเสนอแนะได้ในขณะนี้ (หาช่องรับข้อมูลไม่พบ)", ephemeral=True)
            return

        # เตรียม Embed
        embed = discord.Embed(
            title="💡 มีข้อเสนอแนะใหม่!",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)
        embed.description = f"**รายละเอียด:**\n{content}"
        
        # ข้อมูลผู้ส่ง
        guild_info = f"{interaction.guild.name} (`{interaction.guild.id}`)" if interaction.guild else "Direct Message"
        embed.add_field(name="👤 ผู้ส่ง", value=f"{interaction.user.mention} (`{interaction.user.name}`)", inline=True)
        embed.add_field(name="🆔 User ID", value=f"`{interaction.user.id}`", inline=True)
        embed.add_field(name="🌐 จากเซิร์ฟเวอร์", value=guild_info, inline=False)
        
        if attachment:
            if "image" in attachment.content_type:
                embed.set_image(url=attachment.url)
            else:
                embed.add_field(name="📎 ไฟล์แนบ", value=f"[{attachment.filename}]({attachment.url})")

        embed.set_footer(text=f"AlphaBot Suggestions • {interaction.user.id}")

        try:
            await target_channel.send(embed=embed)
            # บันทึก Cooldown
            self._save_cooldown(user_id)
            
            success_embed = discord.Embed(
                title="✅ ส่งข้อเสนอแนะสำเร็จ",
                description="ขอบคุณสำหรับข้อมูลครับ! ข้อเสนอแนะของคุณถูกส่งไปยังทีมงานแล้ว",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=success_embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Failed to send suggestion: {e}")
            await interaction.response.send_message("❌ เกิดข้อผิดพลาดในการส่งข้อความ กรุณาลองใหม่อีกครั้งครับ", ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Suggestion(bot))
