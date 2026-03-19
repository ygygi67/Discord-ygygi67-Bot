"""
🤖 Distributed Bot System - ใช้งานง่ายๆ

สร้าง 3 โหมดการทำงานให้เลือก:

═══════════════════════════════════════════════════════════

[โหมดที่ 1] STANDALONE (เหมือนเดิม - แนะนำสำหรับเริ่มต้น)
├─ ใช้ได้ทันที ไม่ต้องตั้งค่าอะไร
├─ เหมาะกับ 1-50 เซิร์ฟเวอร์
└─ รัน: python bot.py

═══════════════════════════════════════════════════════════

[โหมดที่ 2] MASTER + WORKERS (ในเครื่องเดียว)
├─ Master: รับคำสั่งจาก Discord
├─ Workers: 2-4 ตัว ช่วยประมวลผลงานหนัก (เช่น download เพลง)
├─ ทุกอย่างอยู่ในเครื่องเดียวกัน
└─ รัน: start_cluster.bat เลือก 4

═══════════════════════════════════════════════════════════

[โหมดที่ 3] MULTI-CLUSTER (หลายเครื่อง)
├─ เครื่องที่ 1: Master + Workers
├─ เครื่องที่ 2: Master (Cluster 1) + Workers  
├─ เครื่องที่ 3: Workers อย่างเดียว
├─ แชร์ไฟล์ data/shared_queue.db ผ่าน Network หรือ Cloud
└─ รัน: ตั้งค่า .env ในแต่ละเครื่องแล้วรัน

═══════════════════════════════════════════════════════════
"""

# ============ วิธีใช้งาน ============

# 1. STANDALONE (แนะนำเริ่มต้น)
# ---------------------------
# ไม่ต้องแก้ไขอะไร รันเหมือนเดิม:
#   python bot.py

# 2. MASTER + WORKERS (ในเครื่อง)
# ---------------------------
# เปิดไฟล์ .env เพิ่มบรรทัดนี้:
#   BOT_MODE=master
#   NUM_WORKERS=2
#
# แล้วรัน:
#   start_cluster.bat (เลือก 4)

# 3. MULTI-CLUSTER (หลายเครื่อง)
# ---------------------------
# เครื่องที่ 1 (Master):
#   BOT_MODE=master
#   TOTAL_SHARDS=4
#   CLUSTER_ID=0
#   TOTAL_CLUSTERS=2
#
# เครื่องที่ 2 (Master Cluster 1):
#   BOT_MODE=master  
#   TOTAL_SHARDS=4
#   CLUSTER_ID=1
#   TOTAL_CLUSTERS=2
#
# Workers (ทุกเครื่อง):
#   python worker_node.py --worker-id 0 --num-workers 2

# ============ ตัวอย่าง .env ============

SAMPLE_ENV = """
# Token (ใช้ร่วมกันทุกเครื่อง)
DISCORD_TOKEN=your_token_here

# โหมดการทำงาน: standalone / master / worker
BOT_MODE=standalone

# === สำหรับ Master Mode ===
# จำนวน Shards (เว้นว่าง = Auto)
TOTAL_SHARDS=

# Cluster (ถ้ามีหลายเครื่อง)
CLUSTER_ID=0
TOTAL_CLUSTERS=1

# === สำหรับ Worker Mode ===
NUM_WORKERS=2

# === คิวระบบ ===
# แชร์ไฟล์นี้ระหว่างเครื่องผ่าน Network/Cloud
QUEUE_DB_PATH=data/shared_queue.db
"""
