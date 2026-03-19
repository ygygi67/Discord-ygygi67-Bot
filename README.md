# 🤖 Discord Bot - Distributed Music & Management Bot

บอท Discord แบบ Distributed ที่รองรับการทำงานหลายเครื่อง (Sharding + Clustering) พร้อมระบบประมวลผลงานหนักผ่าน Workers

## ✨ Features

- 🎵 **Music Player** - เล่นเพลงจาก YouTube
- 🎲 **Distributed System** - รองรับหลาย Shards และ Workers
- 👥 **Server Management** - จัดการเซิร์ฟเวอร์อัตโนมัติ
- 📊 **Statistics** - เก็บสถิติการใช้งาน
- 📝 **Logging** - บันทึกทุกกิจกรรม
- 🛡️ **Moderation** - ระบบจัดการเซิร์ฟเวอร์

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
 