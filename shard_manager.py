"""
Shard Manager - จัดการ Sharding สำหรับ Discord Bot
รองรับ Auto Sharding และ Manual Sharding
"""

import os
import sys
import asyncio
import discord
from discord.ext import commands, tasks
from typing import Optional, List, Dict
import json
import aiohttp

class ShardManager:
    """
    จัดการ Sharding แบบ Manual และ Auto
    ช่วยกระจายเซิร์ฟเวอร์ไปยัง Shard ต่างๆ
    """
    
    def __init__(self, 
                 token: str,
                 total_shards: int = None,  # None = Auto
                 shard_ids: List[int] = None,  # [0, 1, 2] สำหรับ cluster นี้
                 cluster_id: int = 0,
                 total_clusters: int = 1):
        self.token = token
        self.total_shards = total_shards
        self.shard_ids = shard_ids
        self.cluster_id = cluster_id
        self.total_clusters = total_clusters
        self.shard_count = None
        
    async def get_recommended_shards(self) -> int:
        """ขอจำนวน Shard ที่แนะนำจาก Discord API"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    'https://discord.com/api/v10/gateway/bot',
                    headers={'Authorization': f'Bot {self.token}'}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('shards', 1)
                    else:
                        print(f"[ShardManager] API Error: {resp.status}")
                        return 1
        except Exception as e:
            print(f"[ShardManager] Error getting shards: {e}")
            return 1
    
    def calculate_shard_ids(self) -> List[int]:
        """คำนวณ Shard IDs ที่ Cluster นี้ต้องรับผิดชอบ"""
        if self.total_shards is None:
            # Auto mode - ต้องรอ get_recommended_shards ก่อน
            return None
            
        # แบ่ง shard ให้แต่ละ cluster เท่าๆ กัน
        shards_per_cluster = self.total_shards // self.total_clusters
        extra = self.total_shards % self.total_clusters
        
        start = self.cluster_id * shards_per_cluster + min(self.cluster_id, extra)
        end = start + shards_per_cluster + (1 if self.cluster_id < extra else 0)
        
        return list(range(start, end))
    
    def create_bot(self, **kwargs) -> commands.AutoShardedBot:
        """สร้าง Bot instance สำหรับ Cluster นี้"""
        
        # ถ้า shard_ids ถูกกำหนดแล้ว ใช้มัน
        if self.shard_ids:
            shard_count = self.total_shards or max(self.shard_ids) + 1
            print(f"[ShardManager] Starting cluster {self.cluster_id} with shards: {self.shard_ids}")
            
            return commands.AutoShardedBot(
                shard_count=shard_count,
                shard_ids=self.shard_ids,
                **kwargs
            )
        
        # Auto sharding - Discord จัดการให้
        print(f"[ShardManager] Starting with Auto Sharding")
        return commands.AutoShardedBot(**kwargs)

class DistributedAlphaBot(commands.AutoShardedBot):
    """
    Bot ที่รองรับ Sharding + Clustering
    สามารถรันเป็น Master หรือ Worker ได้
    """
    
    def __init__(self, 
                 cluster_id: int = 0,
                 total_clusters: int = 1,
                 is_worker: bool = False,
                 **kwargs):
        
        self.cluster_id = cluster_id
        self.total_clusters = total_clusters
        self.is_worker = is_worker
        self.start_time = None
        
        # ถ้าเป็น Worker ไม่ต้องใช้ Sharding
        if is_worker:
            super().__init__(**kwargs)
        else:
            # Master ใช้ AutoShardedBot
            super().__init__(**kwargs)
    
    async def setup_hook(self):
        """Called when bot is starting"""
        from shared_queue import AsyncSharedQueue
        self.queue = AsyncSharedQueue()
        
        # Load cogs
        await self._load_cogs()
        
        # Start background tasks
        if not self.is_worker:
            self.update_status.start()
            self.cleanup_tasks.start()
    
    async def _load_cogs(self):
        """โหลด Cogs ตามโหมดการทำงาน"""
        import os
        
        ignored_files = ['conversation.py', 'message_detection.py', '__pycache__']
        
        # Worker โหลดเฉพาะ Cogs ที่ต้องประมวลผลงานหนัก
        if self.is_worker:
            worker_cogs = ['music', 'stats']  # Cogs ที่ใช้ทรัพยากรเยอะ
            for cog in worker_cogs:
                try:
                    await self.load_extension(f'cogs.{cog}')
                except Exception as e:
                    print(f"[Worker] Failed to load {cog}: {e}")
            return
        
        # Master โหลดทุก Cogs ยกเว้นอันที่ Worker จัดการ
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py') and filename not in ignored_files:
                cog_name = filename[:-3]
                try:
                    await self.load_extension(f'cogs.{cog_name}')
                except Exception as e:
                    print(f"[Master] Failed to load {cog_name}: {e}")
    
    @tasks.loop(minutes=5)
    async def update_status(self):
        """อัพเดทสถานะบอททุก 5 นาที"""
        if self.is_ready():
            guild_count = len(self.guilds)
            user_count = sum(g.member_count for g in self.guilds)
            
            await self.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name=f"{guild_count} servers | {user_count} users"
                )
            )
    
    @tasks.loop(hours=1)
    async def cleanup_tasks(self):
        """ลบ Task เก่าทุกชั่วโมง"""
        from shared_queue import get_queue
        queue = get_queue()
        queue.cleanup_old_tasks(hours=24)
    
    async def on_ready(self):
        """Called when bot is ready"""
        print(f"✅ {'Worker' if self.is_worker else f'Master (Cluster {self.cluster_id})'} Ready!")
        print(f"   Logged in as: {self.user}")
        print(f"   Shards: {self.shard_count}")
        print(f"   Guilds: {len(self.guilds)}")
    
    async def on_shard_ready(self, shard_id):
        """Called when a shard is ready"""
        print(f"🟢 Shard {shard_id} Ready")
    
    async def on_shard_connect(self, shard_id):
        """Called when a shard connects"""
        print(f"🔌 Shard {shard_id} Connected")
    
    async def on_shard_disconnect(self, shard_id):
        """Called when a shard disconnects"""
        print(f"🔴 Shard {shard_id} Disconnected")
    
    async def on_shard_resumed(self, shard_id):
        """Called when a shard resumes"""
        print(f"🔄 Shard {shard_id} Resumed")

# Helper function สำหรับสร้าง Bot
def create_distributed_bot(
    token: str,
    mode: str = 'master',  # 'master', 'worker', 'standalone'
    cluster_id: int = 0,
    total_clusters: int = 1,
    shard_ids: List[int] = None,
    **kwargs
) -> commands.AutoShardedBot:
    """
    สร้าง Bot ตามโหมดที่ต้องการ
    
    Modes:
    - master: ควบคุมหลาย Shards, ส่งงานให้ Workers
    - worker: รับงานจาก Master มาประมวลผล
    - standalone: ทำงานคนเดียว (เหมือนเดิม)
    """
    
    intents = discord.Intents.all()
    intents.members = True
    intents.message_content = True
    intents.presences = True
    
    if mode == 'standalone':
        # โหมดเดิม - ไม่ใช้ Sharding
        return commands.Bot(
            command_prefix='!',
            intents=intents,
            **kwargs
        )
    
    elif mode == 'master':
        # Master Mode - ใช้ Sharding
        if shard_ids:
            # Manual sharding (Cluster)
            shard_count = max(shard_ids) + 1
            return DistributedAlphaBot(
                cluster_id=cluster_id,
                total_clusters=total_clusters,
                is_worker=False,
                shard_count=shard_count,
                shard_ids=shard_ids,
                command_prefix='!',
                intents=intents,
                **kwargs
            )
        else:
            # Auto sharding
            return DistributedAlphaBot(
                is_worker=False,
                command_prefix='!',
                intents=intents,
                **kwargs
            )
    
    elif mode == 'worker':
        # Worker Mode - ไม่ต้องใช้ Sharding แต่ต้องเชื่อมต่อ Queue
        return DistributedAlphaBot(
            is_worker=True,
            command_prefix='!',  # Workers ไม่รับ commands จาก Discord
            intents=intents,
            **kwargs
        )
    
    else:
        raise ValueError(f"Unknown mode: {mode}")
