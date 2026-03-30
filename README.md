# 🌌 ygygi67 Bot — Distributed Discord Super Bot

> บอท Discord สายครบเครื่องที่รวม **AI + Music + Intercom + Moderation + Voice Tools**  
> ออกแบบให้รันได้ทั้งแบบเครื่องเดียว และแบบกระจายงานหลาย worker/shard สำหรับเซิร์ฟเวอร์ขนาดใหญ่ 🚀

---

## 🎯 Project Vision

`ygygi67 Bot` ถูกสร้างมาเพื่อให้ “เซิร์ฟเวอร์เดียวจบทุกงาน”  
ไม่ต้องสลับหลายบอทให้วุ่นวาย ทั้งงานคุย, งานดูแล, งานเพลง, งานเชื่อมข้ามเซิร์ฟ, และงาน automation พื้นฐาน

สิ่งที่โปรเจกต์นี้เน้น:

- ⚡ **เร็วและเสถียร** ด้วยโครงสร้าง Distributed
- 🧩 **ขยายต่อได้** ด้วย Cog-based architecture
- 🛡️ **ปลอดภัยขึ้น** ด้วย Intercom Security Control Panel
- 🎙️ **ใช้งานจริงได้** ด้วยระบบ Voice/TTS/Transcription

---

## ✨ Feature Showcase

### 🤖 AI Assistant
- ห้อง AI ส่วนตัวและโซน AI
- จดจำบริบท/สรุปบทสนทนา
- โหมดบุคลิก AI หลายรูปแบบ

### 🎵 Music & Voice
- เล่นเพลงและจัดคิว
- สั่ง TTS ด้วย `/พูดตาม`
- ถอดเสียงจากข้อความด้วย `/ถอดเสียงข้อความ`
  - รองรับลิงก์ข้อความ Discord
  - รองรับ Message ID + ระบุช่อง
  - เลือกได้ว่าจะส่งไฟล์เสียงต้นฉบับกลับมาด้วยหรือไม่

### 🌐 Intercom Cross-Server
- Broadcast ข้ามเซิร์ฟเวอร์
- ส่งแบบเจาะจงเซิร์ฟ (`/intercom_private`)
- ส่ง DM ข้ามเซิร์ฟ (`/intercom_dm`)
- รองรับ sync แก้ไขข้อความต้นทางไปปลายทาง
- แสดง `UID / GID / MID` ในข้อความปลายทาง

### 🎛️ Intercom Security Control Panel
- กันสแปม
- กรองคำไม่เหมาะสม (ค่าเริ่มต้น + เพิ่มคำเอง)
- กรองลิงก์ด้วย allowlist
- ตั้งช่อง log เหตุการณ์ความปลอดภัย
- ลบข้อความต้นทาง+ปลายทางด้วย `/intercom_purge`

### 🛠️ Server Management
- ชุดคำสั่ง admin/moderation
- ระบบห้อง private chat
- ระบบ status/stats/notification/logging

---

## 🧭 Command Map (หมวดหลัก)

### Setup
- `/setup_server`
- `/intercom_setup`

### Intercom
- `/intercom_panel`
- `/intercom_security`
- `/intercom_private`
- `/intercom_dm`
- `/intercom_purge`

### Voice
- `/พูดตาม`
- `/ถอดเสียงข้อความ`
- `/โหลดคลิป`
- `/แปลงไฟล์`
- `/แปลงไฟล์_รองรับ`

---

## ⚙️ คำสั่งการทำงาน (พร้อมตัวอย่าง)

### `/โหลดคลิป url:<ลิงก์> mode:<mp4|mp3>`
- หน้าที่: ดาวน์โหลดวิดีโอ/เสียงจากลิงก์ YouTube, TikTok และแหล่งที่รองรับ
- จุดเด่น: แสดงสถานะดาวน์โหลดแบบอัปเดตข้อความ, มี fallback กดปุ่มแปลงเป็น MP3 เมื่อไฟล์ใหญ่เกิน
- ตัวอย่างข้อความบอท:
  - `⏳ กำลังตรวจสอบและเตรียมดาวน์โหลดจาก ...`
  - `📊 52.3% | 12.40/23.70 MB`
  - `⚠️ ไฟล์ใหญ่เกิน 200 MB ... กดปุ่มเพื่อสลับเป็น MP3`
  - `✅ ดาวน์โหลดสำเร็จ`

### `/แปลงไฟล์ file:<ไฟล์แนบ> target_format:<ปลายทาง>`
- หน้าที่: แปลงไฟล์แบบอัตโนมัติด้วยเส้นทางแปลง (conversion path)
- รองรับ: ข้อความ ↔ ข้อความ, สื่อ ↔ สื่อ (รูป/เสียง/วิดีโอ)
- ตัวอย่างข้อความบอท:
  - `🔄 กำลังแปลง (1/2) MP4 ➜ MP3 ...`
  - `✅ แปลงเสร็จแล้ว MP4 ➜ MP3`
  - `❌ ยังไม่รองรับเส้นทางแปลงไฟล์นี้`

### `/แปลงไฟล์_รองรับ`
- หน้าที่: แสดงรายการหมวดไฟล์ที่ระบบรองรับทั้งหมดอย่างรวดเร็ว

### `/ถอดเสียงข้อความ`
- หน้าที่: ถอดเสียงจากข้อความที่มีไฟล์เสียง/ลิงก์ข้อความ
- รองรับ: ใส่ลิงก์ข้อความ Discord หรือ Message ID + ช่อง

### `/พูดตาม`
- หน้าที่: ให้บอทพูดข้อความในห้องเสียงด้วย TTS
- เหมาะกับ: ประกาศ, แจ้งเตือน, โหมดผู้ช่วยเสียง

---

## 🗣️ ประโยคตอบกลับของบอท (ใช้งานจริง)

- `⏳ กำลังเริ่มดาวน์โหลดโหมด MP4 ...`
- `🔄 ดาวน์โหลดเสร็จแล้ว กำลังประมวลผลไฟล์ MP3...`
- `☁️ ไฟล์ใหญ่เกิน limit กำลังอัพโหลดขึ้น catbox.moe...`
- `❌ คลิปนี้ไม่สามารถเข้าถึงได้ (อาจโดนปิด/จำกัดประเทศ/ต้องล็อกอิน)`
- `✅ ส่งไฟล์เรียบร้อย`
- `❌ เกิดข้อผิดพลาดในการโหลด: ...`

---

## 🧠 Runtime Modes

| Mode | เหมาะกับ | ตัวอย่างคำสั่ง |
|------|----------|----------------|
| `standalone` | เครื่องเดียว / เริ่มต้นเร็ว | `python bot.py` |
| `master` | คุม shard/cluster | `BOT_MODE=master python bot.py` |
| `worker` | รับงานหนักแยก process | `python worker_node.py` |

---

## ⚡ Quick Start

### 1) Install dependencies

```bash
pip install -r requirements.txt
```

### 2) Configure environment

```bash
copy .env.example .env
```

ค่าที่ต้องมีอย่างน้อย:

- `DISCORD_TOKEN`
- `APPLICATION_ID`
- `DISCORD_GUILD_ID`

> ถ้าใช้ถอดเสียง ต้องมี `ffmpeg` ใน PATH ด้วย

### 3) Run

```bash
python bot.py
```

หรือรันแบบคลัสเตอร์:

```bash
start_cluster.bat
```

---

## 🗂️ Project Structure (อัปเดตตามโครงจริง)

```text
ygygi67 Bot/
├─ bot.py
├─ worker_node.py
├─ start.bat
├─ start_cluster.bat
├─ RestartNow.bat.bat
├─ requirements.txt
├─ .env.example
│
├─ cogs/
│  ├─ admin/
│  │  ├─ admin.py
│  │  ├─ moderation.py
│  │  ├─ roles.py
│  │  ├─ server_copier.py
│  │  └─ sync_and_manage.py
│  ├─ ai/
│  │  └─ ai_discord_bot.py
│  ├─ core/
│  │  └─ base.py
│  ├─ download_video/
│  │  └─ download_video.py
│  ├─ music/
│  │  └─ music.py
│  ├─ Roblox/
│  │  └─ Followers.py
│  ├─ utility/
│  │  ├─ bot_notifications.py
│  │  ├─ discovery.py
│  │  ├─ maintenance.py
│  │  ├─ modmail.py
│  │  ├─ server_link.py
│  │  ├─ server_logger.py
│  │  ├─ stats.py
│  │  ├─ status.py
│  │  ├─ suggestion.py
│  │  └─ utility.py
│  └─ voice/
│     └─ tts.py
│
├─ core/
│  ├─ command_logger.py
│  ├─ distributed_config.py
│  ├─ shard_manager.py
│  ├─ shared_queue.py
│  ├─ shared_queue_sql.py
│  ├─ sql_config.py
│  └─ storage.py
│
├─ data/
├─ docs/
│  ├─ README.md
│  └─ SETUP_GUIDE.md
├─ scripts/
├─ ffmpeg/
├─ VoiceLoggerBot/
├─ logs/            # runtime
├─ exports/         # runtime
├─ build/           # generated
└─ dist/            # generated
```

---

## 🔐 Security & Ops Notes

- อย่า commit `.env` เด็ดขาด
- แนะนำตั้ง `intercom_log_channel_id` เพื่อ audit เหตุการณ์
- โฟลเดอร์ `logs/`, `exports/`, `dist/`, `build/` เป็น output/runtime
- ก่อน deploy ควรทดสอบคำสั่งสำคัญในเซิร์ฟเวอร์ staging

---

## 📄 License

MIT

---

Made with ❤️ using `discord.py`
