import discord
from discord import app_commands
from discord.ext import commands
import random
import aiohttp
import logging
import json
import asyncio
from command_logger import command_logger

logger = logging.getLogger('discord_bot')

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("Fun cog initialized")

    @app_commands.command(name="ลูกแก้ว", description="ถามคำถามกับลูกบอลวิเศษ")
    @app_commands.describe(question="คำถามที่คุณต้องการถาม")
    async def eight_ball(self, interaction: discord.Interaction, question: str):
        """ตอบคำถามแบบสุ่ม"""
        responses = [
            "แน่นอนที่สุด",
            "ใช่ แน่นอน",
            "ไม่ต้องสงสัยเลย",
            "ใช่",
            "คุณสามารถพึ่งพาได้",
            "ตามที่ฉันเห็น ใช่",
            "น่าจะเป็นไปได้",
            "มองในแง่ดี",
            "ใช่",
            "สัญญาณบอกว่าใช่",
            "ตอบไม่ชัดเจน ลองถามอีกครั้ง",
            "ถามอีกครั้งในภายหลัง",
            "ไม่ควรบอกคุณตอนนี้",
            "ไม่สามารถทำนายได้ตอนนี้",
            "ตั้งสมาธิและถามอีกครั้ง",
            "อย่าพึ่งพามัน",
            "คำตอบของฉันคือไม่",
            "แหล่งที่มาของฉันบอกว่าไม่",
            "ไม่ค่อยดี",
            "ไม่แน่นอน"
        ]
        response = random.choice(responses)
        embed = discord.Embed(
            title="🎱 ลูกบอลวิเศษ",
            description=f"คำถาม: {question}\nคำตอบ: {response}",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ทอยลูกเต๋า", description="ทอยลูกเต๋า")
    @app_commands.describe(sides="จำนวนด้านของลูกเต๋า (ค่าเริ่มต้น: 6)")
    async def roll(self, interaction: discord.Interaction, sides: int = 6):
        """ทอยลูกเต๋า"""
        if sides < 2:
            await interaction.response.send_message("❌ จำนวนด้านต้องมากกว่า 1", ephemeral=True)
            return
        
        result = random.randint(1, sides)
        embed = discord.Embed(
            title="🎲 ทอยลูกเต๋า",
            description=f"คุณทอยลูกเต๋า {sides} ด้าน\nผลลัพธ์: **{result}**",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="มีม", description="ส่งมีมสุ่ม")
    async def meme(self, interaction: discord.Interaction):
        """ส่งมีมสุ่ม"""
        try:
            # Defer the response to prevent timeout
            await interaction.response.defer()
            
            async with aiohttp.ClientSession() as session:
                async with session.get('https://meme-api.com/gimme', timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        embed = discord.Embed(
                            title=data['title'],
                            url=data['postLink'],
                            color=discord.Color.blue()
                        )
                        embed.set_image(url=data['url'])
                        embed.set_footer(text=f"จาก r/{data['subreddit']}")
                        await interaction.followup.send(embed=embed)
                    else:
                        await interaction.followup.send("❌ ไม่สามารถโหลดมีมได้", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("❌ การโหลดมีมใช้เวลานานเกินไป กรุณาลองใหม่", ephemeral=True)
        except Exception as e:
            logging.error(f"Error in meme command: {str(e)}")
            await interaction.followup.send("❌ เกิดข้อผิดพลาดในการโหลดมีม กรุณาลองใหม่", ephemeral=True)

    @app_commands.command(name="เลือก", description="สุ่มเลือกหนึ่งตัวเลือกจากหลายตัวเลือก")
    @app_commands.describe(options="ตัวเลือกที่จะสุ่ม (คั่นด้วยเครื่องหมาย ,)")
    async def choose(self, interaction: discord.Interaction, options: str):
        """สุ่มเลือกหนึ่งตัวเลือก"""
        choices = [option.strip() for option in options.split(',')]
        if len(choices) < 2:
            await interaction.response.send_message("❌ กรุณาระบุตัวเลือกอย่างน้อย 2 ตัวเลือก", ephemeral=True)
            return
        
        choice = random.choice(choices)
        embed = discord.Embed(
            title="🎲 สุ่มเลือก",
            description=f"ตัวเลือก: {', '.join(choices)}\nผลลัพธ์: **{choice}**",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="โยนเหรียญ", description="โยนเหรียญ")
    async def coinflip(self, interaction: discord.Interaction):
        """โยนเหรียญ"""
        result = random.choice(["หัว", "ก้อย"])
        embed = discord.Embed(
            title="🪙 โยนเหรียญ",
            description=f"ผลลัพธ์: **{result}**",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="สวัสดี", description="รับคำทักทายสุ่มจากบอท")
    async def hello(self, interaction: discord.Interaction):
        """คำสั่งทักทาย"""
        greetings = [
            "สวัสดีครับ! 😊",
            "สวัสดีค่ะ! 💖",
            "หวัดดี! 👋",
            "ยินดีต้อนรับ! 🎉",
            "สวัสดีทุกคน! 🌟",
            "สวัสดีจ้า! 🎈",
            "หวัดดีเพื่อน! 🤗",
            "สวัสดีครับ/ค่ะ! 🎊",
            "ยินดีที่ได้รู้จัก! 🌈",
            "สวัสดีครับ/ค่ะ! 🎀"
        ]
        greeting = random.choice(greetings)
        await interaction.response.send_message(greeting)
        command_logger.log_command(interaction, greeting)

    # INSERT_YOUR_REWRITE_HERE

async def setup(bot):
    await bot.add_cog(Fun(bot)) 