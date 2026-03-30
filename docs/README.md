# ygygi67 Bot

บอท Discord แบบครบเครื่องที่รวม AI, เพลง, ระบบข้ามเซิร์ฟเวอร์, เครื่องมือแอดมิน และระบบเสียงไว้ในโปรเจกต์เดียว  
ออกแบบมาให้ใช้ได้ทั้งแบบเครื่องเดียว (standalone) และแบบกระจายงาน (master/worker)

## Highlights

- AI Assistant พร้อมห้อง AI และการจดจำบริบท
- Music + Voice Queue
- Intercom คุยข้ามเซิร์ฟเวอร์
- Security Control Panel แบบปุ่มกด
- ถอดเสียงจากข้อความ Discord (ลิงก์/Message ID)
- ระบบ log, stats, moderation และ automation พื้นฐาน

## Core Features

### 1) Intercom Cross-Server

- ส่งข้อความจากห้อง Intercom ของเซิร์ฟต้นทางไปหลายเซิร์ฟปลายทางอัตโนมัติ
- รองรับส่งแบบเจาะจงเซิร์ฟ (`/intercom_private`) และข้ามเซิร์ฟแบบ DM (`/intercom_dm`)
- แสดงข้อมูลผู้ส่ง/ต้นทางใน embed ได้แก่ `UID`, `GID`, และ `MID` (Source Message ID)
- ถ้าแก้ไขข้อความต้นทาง ระบบจะแก้ไขข้อความปลายทางตาม

### 2) Intercom Security

- กันสแปม
- กรองคำไม่เหมาะสม (ทั้งค่าเริ่มต้นและคำเพิ่มเอง)
- กรองลิงก์ด้วย allowlist
- ตั้งห้อง log สำหรับเหตุการณ์ด้านความปลอดภัย
- ลบข้อความต้นทางและข้อความที่กระจายไปแล้วด้วยคำสั่งเดียว (`/intercom_purge`)

### 3) Voice & Transcription

- `/พูดตาม` สำหรับ TTS
- `/ถอดเสียงข้อความ` รองรับ:
  - ลิงก์ข้อความ Discord
  - Message ID + ระบุช่อง
  - ตัวเลือก `ส่งไฟล์ต้นฉบับ` เพื่อแนบไฟล์เสียงกลับมาพร้อมผลถอดเสียง

## Command Quick Reference

### Setup

- `/setup_server`
- `/intercom_setup`

### Intercom

- `/intercom_panel` เปิดหน้า Control Panel แบบปุ่มกด
- `/intercom_security` จัดการสถานะ/ลิงก์/คำไม่เหมาะสม/ห้อง log แบบรวม
- `/intercom_private`
- `/intercom_dm`
- `/intercom_purge`

### Voice

- `/พูดตาม`
- `/ถอดเสียงข้อความ`

## Architecture Modes

| Mode | Use Case | Example |
|------|----------|---------|
| `standalone` | บอทเครื่องเดียว | `python bot.py` |
| `master` | คุม shards / orchestration | `BOT_MODE=master python bot.py` |
| `worker` | รับงานหนัก | `python worker_node.py` |

## Quick Start

### 1) Install

```bash
pip install -r requirements.txt
```

### 2) Configure

```bash
copy .env.example .env
```

กำหนดค่าอย่างน้อย:

- `DISCORD_TOKEN`
- `APPLICATION_ID`
- `DISCORD_GUILD_ID` (สำหรับ sync คำสั่งแบบเร็วตอนพัฒนา)

### 3) Run

```bash
python bot.py
```

หรือรันแบบกระจายงาน:

```bash
start_cluster.bat
```

## Project Structure

```text
bot.py
worker_node.py
core/
cogs/
data/
docs/
logs/
```

## Security Notes

- ห้าม commit `.env`
- ถ้าใช้ระบบถอดเสียง ต้องมี `ffmpeg` ใน PATH
- ควรตั้งห้อง log สำหรับ Intercom Security เสมอ

## License

MIT
