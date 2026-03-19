"""
Distributed Music Cog - ตัวอย่างการใช้ Worker Queue
Master ส่งงาน download ให้ Worker ทำ
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
import uuid

# Import queue system
try:
    from shared_queue import AsyncSharedQueue, Task
    from distributed_config import is_master, ENABLE_DISTRIBUTED_MUSIC
    DISTRIBUTED_MODE = True
except:
    DISTRIBUTED_MODE = False

class MusicDistributed(commands.Cog):
    """Music Cog ที่รองรับ Distributed Mode"""
    
    def __init__(self, bot):
        self.bot = bot
        self.queue = None
        self.pending_downloads = {}  # Track pending downloads
        
        if DISTRIBUTED_MODE and is_master() and ENABLE_DISTRIBUTED_MUSIC:
            self.queue = AsyncSharedQueue()
            self.check_downloads.start()
    
    def cog_unload(self):
        if hasattr(self, 'check_downloads'):
            self.check_downloads.cancel()
    
    @tasks.loop(seconds=2)
    async def check_downloads(self):
        """เช็คผลลัพธ์จาก Workers ทุก 2 วินาที"""
        completed = []
        
        for task_id, info in list(self.pending_downloads.items()):
            result = await self.queue.get_task_result(task_id, timeout=0)
            
            if result:
                if result.status == 'completed':
                    # แจ้งผู้ใช้ว่า download เสร็จแล้ว
                    channel = self.bot.get_channel(info['channel_id'])
                    if channel:
                        title = result.result.get('title', 'Unknown')
                        duration = result.result.get('duration', 0)
                        await channel.send(
                            f"✅ **{title}** ({duration//60}:{duration%60:02d}) "
                            f"พร้อมเล่นแล้ว! (ประมวลผลโดย Worker)"
                        )
                    completed.append(task_id)
                    
                elif result.status == 'failed':
                    channel = self.bot.get_channel(info['channel_id'])
                    if channel:
                        await channel.send(
                            f"❌ ดาวน์โหลดล้มเหลว: {result.error}"
                        )
                    completed.append(task_id)
        
        # ลบที่เสร็จแล้วออกจาก list
        for task_id in completed:
            del self.pending_downloads[task_id]
    
    @app_commands.command(name="play_distributed", description="เล่นเพลงแบบใช้ Worker ช่วย")
    @app_commands.describe(url="ลิงก์ YouTube")
    async def play_distributed(self, interaction: discord.Interaction, url: str):
        """คำสั่งเล่นเพลงที่ส่งงานไปให้ Worker ทำ"""
        
        if not DISTRIBUTED_MODE or not is_master():
            await interaction.response.send_message(
                "❌ Distributed mode ไม่เปิดใช้งาน",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(thinking=True)
        
        # สร้าง Task ส่งไปให้ Worker
        task = Task(
            id=str(uuid.uuid4()),
            type='download',
            data={
                'url': url,
                'output_path': './music/downloads',
                'guild_id': interaction.guild_id,
                'user_id': interaction.user.id
            },
            priority=0,  # High priority
            shard_id=getattr(self.bot, 'shard_id', 0)
        )
        
        # ส่งเข้าคิว
        success = await self.queue.submit_task(task)
        
        if success:
            # บันทึกไว้ track ผลลัพธ์
            self.pending_downloads[task.id] = {
                'channel_id': interaction.channel_id,
                'user_id': interaction.user.id,
                'url': url
            }
            
            await interaction.followup.send(
                f"🎵 ส่งคำขอดาวน์โหลดไปยัง Worker แล้ว!\n"
                f"   Task ID: `{task.id[:8]}`\n"
                f"   รอสักครู่ระบบจะแจ้งเมื่อพร้อม...",
                ephemeral=False
            )
        else:
            await interaction.followup.send(
                "❌ ไม่สามารถส่งงานไปยัง Worker ได้",
                ephemeral=True
            )
    
    @app_commands.command(name="queue_stats", description="ดูสถิติคิวงาน")
    async def queue_stats(self, interaction: discord.Interaction):
        """ดูสถิติของ Task Queue"""
        
        if not DISTRIBUTED_MODE or not self.queue:
            await interaction.response.send_message(
                "❌ Distributed mode ไม่เปิดใช้งาน",
                ephemeral=True
            )
            return
        
        stats = await self.queue.get_stats()
        
        embed = discord.Embed(
            title="📊 Task Queue Statistics",
            color=discord.Color.blue()
        )
        
        for status, count in stats.items():
            embed.add_field(
                name=status.title(),
                value=f"{count} tasks",
                inline=True
            )
        
        pending = len(self.pending_downloads)
        embed.add_field(
            name="Your Pending",
            value=f"{pending} downloads",
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(MusicDistributed(bot))
