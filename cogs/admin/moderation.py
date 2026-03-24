import discord
from discord import app_commands
from discord.ext import commands
import logging
from datetime import datetime, timedelta

logger = logging.getLogger('discord_bot')

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="เตะ", description="เตะสมาชิกออกจากเซิร์ฟเวอร์")
    @app_commands.describe(member="สมาชิกที่ต้องการเตะ", reason="เหตุผลในการเตะ")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        try:
            await member.kick(reason=reason)
            embed = discord.Embed(
                title="เตะสมาชิกสำเร็จ",
                description=f"{member.mention} ถูกเตะออกจากเซิร์ฟเวอร์แล้ว",
                color=discord.Color.red()
            )
            if reason:
                embed.add_field(name="เหตุผล", value=reason)
            await interaction.response.send_message(embed=embed)
            
            # Log the action (if DB exists)
            if hasattr(self.bot, 'db'):
                await self.log_moderation(interaction.user.id, member.id, "kick", reason)
        except Exception as e:
            logger.error(f"Error in kick command: {e}")
            await interaction.response.send_message("❌ ไม่สามารถเตะสมาชิกได้ (อาจเป็นเพราะบอทไม่มีสิทธิ์หรือสมาชิกมียศสูงกว่า)", ephemeral=True)

    @app_commands.command(name="แบน", description="แบนสมาชิกออกจากเซิร์ฟเวอร์")
    @app_commands.describe(member="สมาชิกที่ต้องการแบน", reason="เหตุผลในการแบน")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        try:
            await member.ban(reason=reason)
            embed = discord.Embed(
                title="แบนสมาชิกสำเร็จ",
                description=f"{member.mention} ถูกแบนออกจากเซิร์ฟเวอร์แล้ว",
                color=discord.Color.dark_red()
            )
            if reason:
                embed.add_field(name="เหตุผล", value=reason)
            await interaction.response.send_message(embed=embed)
            
            # Log the action (if DB exists)
            if hasattr(self.bot, 'db'):
                await self.log_moderation(interaction.user.id, member.id, "ban", reason)
        except Exception as e:
            logger.error(f"Error in ban command: {e}")
            await interaction.response.send_message("❌ ไม่สามารถแบนสมาชิกได้", ephemeral=True)

    @app_commands.command(name="หมดเวลา", description="จำกัดเวลาสมาชิก (Timeout)")
    @app_commands.describe(member="สมาชิกที่ต้องการจำกัดเวลา", minutes="จำนวนนาที", reason="เหตุผล")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = None):
        try:
            duration = timedelta(minutes=minutes)
            await member.timeout(duration, reason=reason)
            embed = discord.Embed(
                title="จำกัดเวลาสมาชิกสำเร็จ",
                description=f"{member.mention} ถูกจำกัดเวลาเป็นเวลา {minutes} นาที",
                color=discord.Color.orange()
            )
            if reason:
                embed.add_field(name="เหตุผล", value=reason)
            await interaction.response.send_message(embed=embed)
            
            # Log the action (if DB exists)
            if hasattr(self.bot, 'db'):
                await self.log_moderation(interaction.user.id, member.id, "timeout", reason)
        except Exception as e:
            logger.error(f"Error in timeout command: {e}")
            await interaction.response.send_message("❌ ไม่สามารถจำกัดเวลาสมาชิกได้", ephemeral=True)

    async def log_moderation(self, moderator_id: int, user_id: int, action: str, reason: str = None):
        try:
            async with self.bot.db.cursor() as cursor:
                await cursor.execute('''
                    INSERT INTO moderation_logs (user_id, moderator_id, action, reason, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, moderator_id, action, reason, datetime.utcnow()))
                await self.bot.db.commit()
        except Exception as e:
            logger.error(f"Error logging moderation action: {e}")

async def setup(bot):
    await bot.add_cog(Moderation(bot)) 