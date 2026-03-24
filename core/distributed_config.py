"""
Distributed Configuration
Config สำหรับระบบกระจาย Sharding + Clustering
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ============ BOT MODE ============
# standalone: บอทเดี่ยว (เหมือนเดิม)
# master: ควบคุม shards หลายตัว
# worker: ประมวลผลงานหนัก
BOT_MODE = os.getenv('BOT_MODE', 'standalone')

# ============ SHARDING CONFIG ============
# ถ้าใช้ Auto Sharding ปล่อย None
# ถ้ากำหนดเอง ใส่จำนวน shard
TOTAL_SHARDS = int(os.getenv('TOTAL_SHARDS', '0')) or None

# ============ CLUSTERING CONFIG ============
# ถ้ามีหลายเครื่อง แต่ละเครื่องเป็น Cluster หนึ่ง
CLUSTER_ID = int(os.getenv('CLUSTER_ID', '0'))  # 0, 1, 2, ...
TOTAL_CLUSTERS = int(os.getenv('TOTAL_CLUSTERS', '1'))  # จำนวน cluster ทั้งหมด

# ถ้าใช้ Clustering ระบบจะคำนวณ shard_ids ให้อัตโนมัติ
# หรือกำหนดเองก็ได้
SHARD_IDS = os.getenv('SHARD_IDS', '')  # เช่น "0,1,2" หรือปล่อยว่างให้ Auto

# ============ WORKER CONFIG ============
# จำนวน Workers ในเครื่องนี้
NUM_WORKERS = int(os.getenv('NUM_WORKERS', '2'))

# Worker ID ถ้ารัน Worker เดี่ยว
WORKER_ID = int(os.getenv('WORKER_ID', '0'))

# ============ DATABASE/QUEUE ============
# Path สำหรับ Shared Queue (SQLite)
QUEUE_DB_PATH = os.getenv('QUEUE_DB_PATH', 'data/shared_queue.db')

# ============ NETWORK CONFIG ============
# ถ้าใช้ Redis แทน SQLite (สำหรับ production ที่มีหลายเครื่อง)
REDIS_URL = os.getenv('REDIS_URL', '')  # redis://localhost:6379/0

# ============ FEATURE FLAGS ============
# เปิด/ปิดการกระจายงาน
ENABLE_DISTRIBUTED_MUSIC = os.getenv('ENABLE_DISTRIBUTED_MUSIC', 'true').lower() == 'true'
ENABLE_DISTRIBUTED_STATS = os.getenv('ENABLE_DISTRIBUTED_STATS', 'true').lower() == 'true'

# ============ HELPER FUNCTIONS ============

def get_shard_ids():
    """คำนวณ Shard IDs ที่ Cluster นี้ต้องรับผิดชอบ"""
    if SHARD_IDS:
        return [int(x) for x in SHARD_IDS.split(',')]
    
    if TOTAL_SHARDS and TOTAL_CLUSTERS > 1:
        # แบ่ง shard ให้แต่ละ cluster
        shards_per_cluster = TOTAL_SHARDS // TOTAL_CLUSTERS
        extra = TOTAL_SHARDS % TOTAL_CLUSTERS
        
        start = CLUSTER_ID * shards_per_cluster + min(CLUSTER_ID, extra)
        end = start + shards_per_cluster + (1 if CLUSTER_ID < extra else 0)
        
        return list(range(start, end))
    
    return None  # Auto sharding

def is_master():
    """Check if running as Master"""
    return BOT_MODE == 'master'

def is_worker():
    """Check if running as Worker"""
    return BOT_MODE == 'worker'

def is_standalone():
    """Check if running standalone"""
    return BOT_MODE == 'standalone'

def print_config():
    """Print current configuration"""
    print("=" * 50)
    print("🤖 Distributed Bot Configuration")
    print("=" * 50)
    print(f"Mode: {BOT_MODE}")
    print(f"Cluster: {CLUSTER_ID}/{TOTAL_CLUSTERS}")
    print(f"Shards: {TOTAL_SHARDS or 'Auto'}")
    print(f"Shard IDs: {get_shard_ids() or 'Auto'}")
    print(f"Workers: {NUM_WORKERS}")
    print(f"Queue DB: {QUEUE_DB_PATH}")
    print(f"Redis: {REDIS_URL or 'Disabled (using SQLite)'}")
    print("=" * 50)

# Print on import
if __name__ != '__main__':
    print_config()
