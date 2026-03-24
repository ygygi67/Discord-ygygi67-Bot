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

