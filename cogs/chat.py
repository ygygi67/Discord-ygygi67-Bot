import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import logging
from typing import Dict, List, Optional

logger = logging.getLogger('discord_bot')

class Chat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.suggestion_channel = None
        self.status_channel = None
        
        # Combined keywords from previous conversation and message_detection cogs
        self.keywords = {
            "เพลง": ["เล่นเพลง", "เปิดเพลง", "เพลงอะไร", "เพลงไหนดี", "เพลงใหม่", "เพลงฮิต", "เพลงเพราะ", "เพลงดัง"],
            "เกม": ["เล่นเกม", "เกมอะไร", "เกมไหนดี", "เกมใหม่", "เกมสนุก", "เกมฟรี", "เกม pc", "เกมมือถือ"],
            "อาหาร": ["กินอะไร", "อาหารอะไร", "ร้านไหนดี", "อาหารอร่อย", "อาหารใหม่", "ร้านอาหาร", "อาหารไทย", "อาหารต่างชาติ"],
            "หนัง": ["ดูหนัง", "หนังอะไร", "หนังไหนดี", "หนังใหม่", "หนังสนุก", "หนังฟรี", "หนังไทย", "หนังต่างชาติ"],
            "การ์ตูน": ["ดูการ์ตูน", "การ์ตูนอะไร", "การ์ตูนไหนดี", "การ์ตูนใหม่", "อนิเมะ", "มังงะ", "การ์ตูนไทย", "การ์ตูนญี่ปุ่น"]
        }
        
        # Responses for generic help detection in main bot.py
        self.help_responses = [
            "🤖 กำลังรับฟังคำถามของคุณอยู่! ลองใช้ /คำสั่ง ดูได้นะครับ",
            "🤖 มีอะไรให้ช่วยไหมครับ? ลองใช้ /คำสั่ง เพื่อดูคำสั่งทั้งหมดได้เลย",
            "🤖 ต้องการความช่วยเหลือไหมครับ? ใช้ /คำสั่ง เพื่อดูคำสั่งทั้งหมดได้เลย"
        ]
        
        self.load_channels()

    def load_channels(self):
        """Load saved channel IDs from file"""
        try:
            if os.path.exists('channels.json'):
                with open('channels.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.suggestion_channel = data.get('suggestion_channel')
                    self.status_channel = data.get('status_channel')
                    logger.info(f"Loaded chat channels: suggestion={self.suggestion_channel}, status={self.status_channel}")
        except Exception as e:
            logger.error(f"Error loading chat channels: {e}")

    def save_channels(self):
        """Save channel IDs to file"""
        try:
            data = {
                'suggestion_channel': self.suggestion_channel,
                'status_channel': self.status_channel
            }
            with open('channels.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            logger.info("Saved chat channels configuration")
        except Exception as e:
            logger.error(f"Error saving chat channels: {e}")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Detect keywords in messages and respond"""
        if message.author.bot:
            return
            
        content = message.content.lower()
        
        # Check for keywords and respond with topic detection
        for topic, words in self.keywords.items():
            if any(word in content for word in words):
                await message.channel.send(f"ดูเหมือนว่าคุณกำลังพูดถึงเรื่อง {topic} อยู่นะ! 😊")
                break

    @app_commands.command(name="ตั้งค่าช่อง", description="ตั้งค่าช่องสำหรับข้อเสนอแนะและสถานะ")
    @app_commands.describe(
        suggestion_channel="ช่องสำหรับข้อเสนอแนะ",
        status_channel="ช่องสำหรับอัพเดทสถานะ"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_channels(
        self,
        interaction: discord.Interaction,
        suggestion_channel: discord.TextChannel,
        status_channel: discord.TextChannel
    ):
        """Set up channels for suggestions and status updates"""
        try:
            await interaction.response.defer()
            
            self.suggestion_channel = suggestion_channel.id
            self.status_channel = status_channel.id
            self.save_channels()
            
            embed = discord.Embed(
                title="✅ ตั้งค่าช่องเรียบร้อยแล้ว",
                description="ระบบได้บันทึกช่องสำหรับการทำงานแล้ว",
                color=discord.Color.green()
            )
            embed.add_field(name="ช่องข้อเสนอแนะ", value=suggestion_channel.mention, inline=True)
            embed.add_field(name="ช่องสถานะ", value=status_channel.mention, inline=True)
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Error setting up channels: {e}")
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {str(e)}", ephemeral=True)

    @app_commands.command(name="ข้อเสนอแนะ", description="ส่งข้อเสนอแนะถึงผู้พัฒนา")
    @app_commands.describe(suggestion="ข้อเสนอแนะของคุณ")
    async def suggest(self, interaction: discord.Interaction, suggestion: str):
        """Submit a suggestion"""
        if not self.suggestion_channel:
            return await interaction.response.send_message(
                "⚠️ ยังไม่ได้ตั้งค่าช่องข้อเสนอแนะ กรุณาให้แอดมินใช้คำสั่ง `/ตั้งค่าช่อง` ก่อนครับ", 
                ephemeral=True
            )

        channel = self.bot.get_channel(self.suggestion_channel)
        if not channel:
            return await interaction.response.send_message("❌ ไม่พบช่องข้อเสนอแนะในเซิร์ฟเวอร์นี้", ephemeral=True)

        embed = discord.Embed(
            title="💡 ข้อเสนอแนะใหม่",
            description=suggestion,
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url
        )
        embed.set_footer(text=f"User ID: {interaction.user.id}")

        await channel.send(embed=embed)
        await interaction.response.send_message("✅ ส่งข้อเสนอแนะของคุณเรียบร้อยแล้ว ขอบคุณครับ!", ephemeral=True)

    @app_commands.command(name="คำสำคัญ", description="ดูรายการคำสำคัญที่บอทจะคอยตอบโต้")
    async def list_keywords(self, interaction: discord.Interaction):
        """List all keywords by topic"""
        embed = discord.Embed(title="📝 รายการคำสำคัญ", color=discord.Color.blue())
        for topic, words in self.keywords.items():
            embed.add_field(
                name=f"📌 {topic}",
                value="`" + "`, `".join(words) + "`",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Chat(bot))
    logger.info("Chat cog loaded and integrated")
