import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import asyncio
import logging
import sys
import json
import psutil
from datetime import datetime, timezone
from collections import Counter

logger = logging.getLogger('maintenance_cog')

class Maintenance(commands.Cog):
    """🛠️ ระบบดูแลรักษาและรีเซ็ตอัตโนมัติ (Maintenance System)"""
    
    def __init__(self, bot):
        self.bot = bot
        self.auto_reset_task.start()
        
    def cog_unload(self):
        self.auto_reset_task.cancel()

    @tasks.loop(hours=24)
    async def auto_reset_task(self):
        """ล้างระบบและโหลด Cog ใหม่ทุก 24 ชม. เพื่อความเสถียร"""
        # ข้ามรอบแรก (ตอนรันบอทเสร็จใหม่ๆ ไม่ต้องรี)
        if self.auto_reset_task.current_loop == 0:
            return
            
        logger.info("🕒 กำลังดำเนินการรีเซ็ตระบบอัตโนมัติตามกำหนดเวลา (Scheduled Reset)...")
        try:
            success, errors = await self.perform_reset()
            logger.info(f"✅ Auto-reset Complete: Success {success}, Errors {errors}")
        except Exception as e:
            logger.error(f"❌ Error during auto-reset: {e}")

    async def perform_reset(self):
        """ดำเนินการรีโหลด Cogs ทั้งหมดที่โหลดอยู่ในตัวบอท"""
        # ดึงรายชื่อ extension ที่โหลดอยู่ (ยกเว้นตัวมันเอง)
        loaded_extensions = list(self.bot.extensions.keys())
        
        success_count = 0
        error_count = 0
        
        # Save state for important cogs if they have it (e.g. Music)
        music_cog = self.bot.get_cog('Music')
        if music_cog:
            logger.info("💾 บันทึกสถานะเพลงก่อนรีเซ็ต...")
            for guild in self.bot.guilds:
                if guild.voice_client:
                    await music_cog.save_voice_state(guild.id, guild.voice_client.channel.id)

        # แจ้ง Music Cog ว่าเป็นการ Reload (ห้ามเตะบอทออกจากห้องเสียง)
        if music_cog:
            music_cog.reload_in_progress = True

        try:
            for extension in loaded_extensions:
                try:
                    # ไม่รีโหลดตัวเองเพื่อป้องกันปัญหา Task ถูกยกเลิกกลางคันกะทันหัน
                    if extension == 'cogs.utility.maintenance':
                        continue
                        
                    await self.bot.reload_extension(extension)
                    logger.info(f"🔄 Reloaded: {extension}") # Log to console
                    success_count += 1
                except Exception as e:
                    logger.error(f"❌ ไม่สามารถรีโหลดโมดูล {extension} ได้: {e}")
                    error_count += 1
        finally:
            # ปิดโหมด Reload หลังจากโหลดครบทุกตัวแล้ว
            if music_cog:
                music_cog.reload_in_progress = False
        
        logger.info(f"✅ Maintenance Reset Complete: {success_count} success, {error_count} errors.")

        
        # Sync tree if needed (might be slow, use with caution)
        # try:
        #     await self.bot.tree.sync()
        # except: pass

        return success_count, error_count

    # Disabled slash command: merged into /sync, kept as legacy code.
    # @app_commands.command(name="system_reset", description="🛠️ รีเซ็ตระบบใหม่ (Reload Cogs) เพื่อแก้ไขปัญหาบอทเอ๋อ หรือตั้งค่าไม่ติด")
    @app_commands.default_permissions(administrator=True)
    async def system_reset(self, interaction: discord.Interaction):
        """คำสั่งสำหรับ Admin ในการรีเซ็ตระบบด้วยตนเอง"""
        await interaction.response.defer(ephemeral=False)
        
        embed = discord.Embed(
            title="🛠️ ระบบกำลังดำเนินการรีเซ็ต...",
            description="บอทกำลังทำการ Reload โมดูลทั้งหมดและข้อมูลที่เกี่ยวข้อง กรุณารอสักครู่ (ประมาณ 5-10 วินาที)...",
            color=discord.Color.blue()
        )
        embed.set_footer(text="ระบบเพลงและสถานะเสียงจะถูกรักษาไว้")
        await interaction.followup.send(embed=embed)
        
        start_time = datetime.now()
        success, errors = await self.perform_reset()
        duration = (datetime.now() - start_time).total_seconds()
        
        result_embed = discord.Embed(
            title="✅ รีเซ็ตระบบเสถียรภาพเรียบร้อย!",
            description=f"ระบบได้โหลดโมดูลใหม่ทั้งหมดเข้าสู่หน่วยความจำแล้ว\n\n"
                        f"📊 **ข้อมูลสรุป:**\n"
                        f"• ✅ โหลดสำเร็จ: `{success}` โมดูล\n"
                        f"• ❌ พบข้อผิดพลาด: `{errors}` โมดูล\n"
                        f"• ⏱️ ใช้เวลา: `{duration:.2f}` วินาที\n\n"
                        f"🛡️ **ความปลอดภัย:** ระบบเสียงและสมาชิกที่เชื่อมต่ออยู่จะไม่หลุดจากห้องเสียง (Seamless Reload)",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        result_embed.set_footer(text="ทำงานด้วยระบบรีเซ็ตอัตโนมัติ v1.0", icon_url=self.bot.user.display_avatar.url)
        
        await interaction.followup.send(embed=result_embed)

    @app_commands.command(name="reload_system", description="🛠️ รีโหลด Cogs และระบบหลักโดยไม่เตะบอทออกจากห้องเสียง")
    @app_commands.default_permissions(administrator=True)
    async def reload_system(self, interaction: discord.Interaction):
        if not getattr(interaction.user, "guild_permissions", None) or not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ ต้องมีสิทธิ์ Administrator", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        start_time = datetime.now()
        success, errors = await self.perform_reset()
        duration = (datetime.now() - start_time).total_seconds()
        await interaction.followup.send(
            f"✅ รีโหลดระบบเรียบร้อย\n"
            f"• สำเร็จ: `{success}` โมดูล\n"
            f"• ผิดพลาด: `{errors}` โมดูล\n"
            f"• ใช้เวลา: `{duration:.2f}` วินาที",
            ephemeral=True
        )

    # Disabled slash command: merged into /sync, kept as legacy code.
    # @app_commands.command(name="system_sync", description="🔄 ซิงค์คำสั่ง Slash Commands ทั้งหมดไปยังเซิร์ฟเวอร์ (แก้ป้ายคำสั่งไม่ขึ้น)")
    @app_commands.default_permissions(administrator=True)
    async def system_sync(self, interaction: discord.Interaction):
        """คำสั่งสำหรับซิงค์คิวรีคำสั่งใหม่ (ใช้เมื่อคำสั่งใหม่ไม่ปรากฏหรือค้าง)"""
        await interaction.response.defer(ephemeral=True)
        try:
            guild_id = os.getenv('DISCORD_GUILD_ID')
            if guild_id and guild_id.strip():
                guild = discord.Object(id=int(guild_id))
                self.bot.tree.copy_global_to(guild=guild)
                cmds = await self.bot.tree.sync(guild=guild)
                await interaction.followup.send(f"✅ ซิงค์คำสั่งสำเร็จ (เฉพาะเซิร์ฟเวอร์ทดสอบ): `{len(cmds)}` คำสั่ง")
            else:
                cmds = await self.bot.tree.sync()
                await interaction.followup.send(f"✅ ซิงค์คำสั่ง Global สำเร็จ: `{len(cmds)}` คำสั่ง (อาจใช้เวลา 1 ชม. ถึงจะเห็นผลทั่วกัน)")
        except Exception as e:
            await interaction.followup.send(f"❌ ซิงค์ไม่สำเร็จ: {e}")

    @app_commands.command(name="system_status", description="📊 ตรวจสอบสถานะความพร้อมของระบบ")
    async def system_status(self, interaction: discord.Interaction):
        """ดูว่ามีโมดูลไหนที่โหลดอยู่บ้าง"""
        await interaction.response.defer(ephemeral=True)
        extensions = list(self.bot.extensions.keys())
        cogs = list(self.bot.cogs.keys())
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / (1024 * 1024)
        cpu_percent = psutil.cpu_percent(interval=0.1)
        uptime = datetime.now(timezone.utc) - self.bot.start_time
        voice_clients = [vc for vc in self.bot.voice_clients if vc and vc.is_connected()]
        tree_commands = list(self.bot.tree.walk_commands())
        command_names = [cmd.qualified_name for cmd in tree_commands]
        duplicates = [name for name, count in Counter(command_names).items() if count > 1]
        disabled_legacy = sorted(getattr(self.bot, "disabled_legacy_commands", []))
        network_status = {}
        try:
            with open(os.path.join("data", "network_status.json"), "r", encoding="utf-8") as f:
                network_status = json.load(f)
        except Exception:
            network_status = {}
        
        embed = discord.Embed(
            title="📊 รายงานความเสถียรของระบบ",
            color=discord.Color.purple(),
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.add_field(name="📦 Loaded Extensions", value=f"`{len(extensions)}` โมดูล", inline=True)
        embed.add_field(name="⚙️ Active Cogs", value=f"`{len(cogs)}` ฟีเจอร์", inline=True)
        embed.add_field(
            name="🧭 Slash Commands",
            value=(
                f"Local tree: `{len(command_names)}` คำสั่ง\n"
                f"คำสั่งซ้ำในโค้ด: `{len(duplicates)}`\n"
                f"Legacy ปิดไว้: `{len(disabled_legacy)}`"
            ),
            inline=True
        )
        embed.add_field(name="🌐 Discord", value=f"Latency: `{round(self.bot.latency * 1000)}ms`\nGuilds: `{len(self.bot.guilds)}`\nVoice: `{len(voice_clients)}`", inline=True)
        embed.add_field(name="💻 Process", value=f"CPU: `{cpu_percent}%`\nRAM: `{memory_mb:.1f} MB`\nUptime: `{str(uptime).split('.')[0]}`", inline=True)
        embed.add_field(name="🧩 Runtime", value=f"Tasks: `{len(asyncio.all_tasks())}`\nShutting down: `{getattr(self.bot, '_is_shutting_down', False)}`\nMode: `{getattr(self.bot, 'mode', 'unknown')}`", inline=True)
        embed.add_field(
            name="📡 Network Recovery",
            value=(
                f"Status: `{network_status.get('status', 'unknown')}`\n"
                f"Last outage: `{network_status.get('last_outage', 'ไม่พบประวัติ')}`\n"
                f"Last reconnect: `{network_status.get('last_reconnect', 'ไม่พบประวัติ')}`"
            ),
            inline=False
        )
        if duplicates:
            embed.add_field(
                name="⚠️ คำสั่งซ้ำในโค้ด",
                value="\n".join(f"• `/{name}`" for name in duplicates[:10]),
                inline=False
            )
        if disabled_legacy:
            embed.add_field(
                name="🧹 Legacy ที่ปิดแล้ว",
                value=(
                    "\n".join(f"• `/{name}`" for name in disabled_legacy[:12]) +
                    "\nใช้ `/sync scope:guild force:true` เพื่อล้างเมนูค้างในเซิร์ฟเวอร์นี้"
                ),
                inline=False
            )
        embed.add_field(name="⏳ รอรอบรีเซ็ตอัตโนมัติ", value=f"ทุก 24 ชม. (รอบถัดไป: {self.auto_reset_task.next_iteration.strftime('%H:%M:%S') if self.auto_reset_task.next_iteration else 'N/A'})", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Maintenance(bot))
