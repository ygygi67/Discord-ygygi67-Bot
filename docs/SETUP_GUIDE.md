# 🤖 Distributed Bot - Quick Start Guide

## สำหรับเครื่องที่ 2 (หรือเครื่องอื่นๆ)

### ขั้นตอนการตั้งค่า:

1. **คัดลอกไฟล์บอท** จากเครื่องแรกมาทั้งหมด:
   ```
   DiscordBot.exe
   cogs/
   data/
   ffmpeg/
   ```

2. **สร้างไฟล์ .env ใหม่** (อย่าใช้ของเครื่องแรกโดยตรง):
   ```env
   DISCORD_TOKEN=ใส่_token_เดียวกัน
   
   # ตั้งค่า Cluster
   BOT_MODE=master
   TOTAL_SHARDS=4
   CLUSTER_ID=1          # เปลี่ยนเป็น 1, 2, 3... ตามเครื่อง
   TOTAL_CLUSTERS=2      # จำนวนเครื่องทั้งหมด
   
   # แชร์ไฟล์คิว (สำคัญ!)
   QUEUE_DB_PATH=\\เครื่องแรก\shared\data\shared_queue.db
   # หรือใช้ Google Drive/OneDrive/ Dropbox sync
   ```

3. **แชร์ไฟล์คิว** ระหว่างเครื่อง:
   - วิธี A: ใช้ Network Share (\\computer\path)
   - วิธี B: ใช้ Cloud Sync (Google Drive/OneDrive แชร์โฟลเดอร์ data/)
   - วิธี C: ใช้ Redis (ถ้ามีหลายเครื่องมาก)

4. **รัน**:
   ```batch
   DiscordBot.exe
   ```

## 🚀 โหมดการทำงาน (Bot Modes)

คุณสามารถเลือกโหมดการทำงานของบอทได้ 3 รูปแบบตามความต้องการ:

### 1. STANDALONE (แนะนำสำหรับเริ่มต้น)
- **การทำงาน**: บอทตัวเดียวทำทุกอย่าง (เล่นเพลง, เก็บสถิติ, จัดการเซิร์ฟเวอร์)
- **ความเหมาะสม**: 1-50 เซิร์ฟเวอร์ หรือการใช้งานทั่วไป
- **วิธีรัน**: `python bot.py` (ไม่ต้องตั้งค่าอะไรเพิ่มใน .env)

### 2. MASTER + WORKERS (ในเครื่องเดียว)
- **การทำงาน**: แบ่งหน้าที่กัน Master รับคำสั่งจาก Discord / Workers ช่วยประมวลผลงานหนัก (เช่น โหลดเพลง)
- **ความเหมาะสม**: เซิร์ฟเวอร์เยอะ หรือต้องการให้บอทลื่นขึ้นเวลาคนใช้เพลงเยอะๆ
- **วิธีรัน**: 
  1. ตั้งค่า `.env`: `BOT_MODE=master` และ `NUM_WORKERS=2`
  2. รัน: `start_cluster.bat` (เลือกข้อ 4)

### 3. MULTI-CLUSTER (หลายเครื่อง)
- **การทำงาน**: กระจายบอทไปรันบนคอมพิวเตอร์หลายเครื่อง ช่วยลดภาระของเครื่องใดเครื่องหนึ่ง
- **การตั้งค่า**:
  - **เครื่องที่ 1**: `BOT_MODE=master`, `CLUSTER_ID=0`, `TOTAL_CLUSTERS=2`
  - **เครื่องที่ 2**: `BOT_MODE=master`, `CLUSTER_ID=1`, `TOTAL_CLUSTERS=2`
  - **แชร์ข้อมูล**: ต้องแชร์ไฟล์ในโฟลเดอร์ `data/` ระหว่างเครื่อง (เช่น ผ่าน Google Drive หรือ Network Share)

---

## 🔐 Token อยู่ที่ไหนบ้าง?

**มีแค่จุดเดียว**: ไฟล์ `.env`

```
.env
  └─ DISCORD_TOKEN=xxx
```

**ไม่มีที่อื่น** ซ่อน Token ไว้

---

## 🛡️ วิธีอัพโหลด Git แบบปลอดภัย

### ขั้นตอน:

1. **สร้างไฟล์ `.gitignore`**:
   ```gitignore
   # ไฟล์ที่ห้ามอัพขึ้น Git
   .env
   *.env
   .env.local
   .env.production
   
   # ไฟล์ระบบ
   __pycache__/
   *.pyc
   *.pyo
   *.pyd
   .Python
   
   # Database & Logs
   *.db
   *.sqlite
   *.sqlite3
   /logs/
   /data/*.db
   
   # Build files
   /dist/
   /build/
   *.spec
   *.exe
   
   # Virtual Environment
   .venv/
   venv/
   
   # IDE
   .vscode/
   .idea/
   ```

2. **สร้างไฟล์ `.env.example`** (template สำหรับคนอื่น):
   ```env
   # คัดลอกไฟล์นี้เป็น .env แล้วใส่ค่าของคุณ
   DISCORD_TOKEN=your_token_here
   DISCORD_GUILD_ID=your_guild_id
   BOT_MODE=standalone
   ```

3. **คำสั่ง Git**:
   ```bash
   # เริ่มต้น
   git init
   
   # เพิ่มไฟล์ทั้งหมดยกเว้นที่อยู่ใน .gitignore
   git add .
   
   # ตรวจสอบว่า .env ไม่อยู่ใน staged files
   git status
   
   # Commit
   git commit -m "Initial commit - Discord Bot"
   
   # เชื่อมกับ GitHub
   git remote add origin https://github.com/username/repo.git
   git push -u origin main
   ```

4. **ตรวจสอบความปลอดภัย**:
   ```bash
   # ดูว่ามี Token หลุดไหม
   git log --all --full-history -- .env
   
   # ดูไฟล์ที่จะ push
   git ls-files
   ```

---

## 📦 การส่งไฟล์ให้คนอื่น (ไม่มี Token)

### วิธีที่ 1: สร้าง Package ไม่มี Token
รันไฟล์ `create_package.bat` → จะได้ `DiscordBot_Standalone.zip`

**คนรับต้องทำ**:
1. แตกไฟล์ zip
2. สร้างไฟล์ `.env` ใส่ Token ของตัวเอง
3. รัน `DiscordBot.exe`

### วิธีที่ 2: ใช้ Git (แนะนำ)
```bash
# คนรับ clone โค้ด
git clone https://github.com/yourname/bot.git
cd bot

# สร้าง .env เอง
copy .env.example .env
# (แก้ไข .env ใส่ Token)

# รัน
python bot.py
```

---

## ⚠️ สิ่งสำคัญ

1. **อย่าส่ง .env ที่มี Token ให้ใครเด็ดขาด**
2. **ถ้าส่ง .exe ที่ build แล้ว อย่าลืมลบ .env ออกก่อน zip**
3. **Token มีแค่ใน .env** - ลบหรือเปลี่ยนแล้วบอทจะรันไม่ได้จนกว่าจะใส่ใหม่
4. **แต่ละคนใช้ Token คนละตัวก็ได้** ถ้าอยากให้บอทตัวแยกกัน
