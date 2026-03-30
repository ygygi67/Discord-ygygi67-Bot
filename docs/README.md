# 🤖 Discord Bot - Distributed Music & Management Bot

บอท Discord แบบ Distributed ที่รองรับการทำงานหลายเครื่อง (Sharding + Clustering) พร้อมระบบประมวลผลงานหนักผ่าน Workers

## ✨ Features

- 🎵 **Music Player** - เล่นเพลงจาก YouTube
- 🎲 **Distributed System** - รองรับหลาย Shards และ Workers
- 👥 **Server Management** - จัดการเซิร์ฟเวอร์อัตโนมัติ
- 📊 **Statistics** - เก็บสถิติการใช้งาน
- 📝 **Logging** - บันทึกทุกกิจกรรม
- 🛡️ **Moderation** - ระบบจัดการเซิร์ฟเวอร์
- 🌐 **Intercom Cross-Server** - คุยข้ามเซิร์ฟเวอร์พร้อมระบบความปลอดภัย
- 🎛️ **Intercom Control Panel** - จัดการระบบกรอง/ลิงก์/Log แบบปุ่มกด
- 🎙️ **Voice Transcription** - ถอดเสียงจากลิงก์ข้อความหรือ Message ID

## 🆕 Intercom & Voice Commands

### Intercom Security

- `/intercom_panel` เปิดหน้า Control Panel แบบปุ่มกด
- `/intercom_security action:panel` เปิด Control Panel ผ่านคำสั่งรวม
- `/intercom_security action:approve value:<domain_or_url>` อนุมัติโดเมนลิงก์
- `/intercom_security action:unapprove value:<domain_or_url>` ถอนโดเมน
- `/intercom_security action:add_badword value:<word>` เพิ่มคำไม่เหมาะสม
- `/intercom_security action:remove_badword value:<word>` ลบคำไม่เหมาะสม
- `/intercom_security action:list_badwords` ดูรายการคำไม่เหมาะสมแบบกำหนดเอง
- `/intercom_security action:set_log log_channel:<channel>` ตั้งห้อง Log

ระบบรองรับ:
- กันสแปม (rate limit)
- กรองคำไม่เหมาะสม (คำมาตรฐาน + คำกำหนดเอง)
- กรองลิงก์ด้วย allowlist
- บันทึก Log เหตุการณ์ความปลอดภัย
- ซิงก์แก้ไขข้อความต้นทางไปยังข้อความปลายทางที่ถูกกระจาย

### Intercom Moderation

- `/intercom_purge link_or_id:<message_link_or_id>` ลบข้อความต้นทาง + ข้อความที่กระจายไปแล้ว

### Voice

- `/ถอดเสียงข้อความ ข้อความลิงก์หรือไอดี:<message_link_or_id> [ช่อง:<text_channel>]`
- รองรับทั้งลิงก์ข้อความ Discord และ Message ID
- ถอดเสียงจากไฟล์เสียง/voice message และตอบกลับเป็นข้อความ

## 🚀 Quick Start

### 1. ติดตั้ง Dependencies
```bash
pip install -r requirements.txt
```

### 2. ตั้งค่า Environment
```bash
copy .env.example .env
# แก้ไข .env ใส่ Discord Token ของคุณ
```

### 3. รันบอท
```bash
# แบบปกติ (Standalone)
python bot.py

# แบบมี Workers ช่วยประมวลผล
start_cluster.bat
```

## 🏗️ Architecture

### โหมดการทำงาน

| โหมด | ใช้สำหรับ | คำสั่ง |
|------|----------|--------|
| `standalone` | 1 เครื่อง, 1-50 เซิร์ฟเวอร์ | `python bot.py` |
| `master` | หลาย Shards | `BOT_MODE=master python bot.py` |
| `worker` | ประมวลผลงานหนัก | `python worker_node.py` |

## 📁 Project Structure

```
DiscordBot/
├── bot.py                 # Main Bot File
├── worker_node.py         # Worker for heavy tasks
├── shared_queue.py        # Task queue system
├── shard_manager.py       # Sharding management
├── distributed_config.py  # Configuration
├── cogs/                  # Bot commands
├── data/                  # Database & Storage
├── logs/                  # Log files
└── music/                 # Downloaded music
```

## 🔧 Configuration

### ไฟล์ .env
```env
DISCORD_TOKEN=your_token_here
APPLICATION_ID=your_app_id
DISCORD_GUILD_ID=your_guild_id

# Distributed Settings
BOT_MODE=standalone
TOTAL_SHARDS=4
CLUSTER_ID=0
NUM_WORKERS=2
```

## ⚠️ Security

- **อย่า commit ไฟล์ .env ที่มี Token**
- **Token มีแค่ใน .env** - ลบแล้วบอทจะรันไม่ได้
- ใช้ `.env.example` เป็น template

## 📝 License

MIT License

---

Made with ❤️ using discord.py
 
