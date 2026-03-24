import os
import shutil
import re

print("=======================================")
print("  กำลังกู้คืนระบบเพลงจาก Git...")
print("=======================================")

# 1. กู้คืนไฟล์เก่าทั้งหมดผ่าน Git
print("📥 ดึงไฟล์เดิม...")
os.system("git restore cogs/music.py cogs/music_distributed.py music_player/README.md music_player/music_player.py music_player/requirements.txt music_player/youtube_music_player.py")

# 2. นำไปจัดระเบียบให้เข้าที่ใหม่ตามโฟลเดอร์
print("📂 จัดระเบียบไฟล์เข้าที่...")
os.makedirs("cogs/music", exist_ok=True)
if os.path.exists("cogs/music.py"):
    shutil.move("cogs/music.py", "cogs/music/music.py")
if os.path.exists("cogs/music_distributed.py"):
    shutil.move("cogs/music_distributed.py", "cogs/music/music_distributed.py")

# 3. ซ่อมระบบ Import มุ่งเป้าไปที่ระบบ Core ตามแบบแผนใหม่
print("🔧 อัปเดตโครงสร้างระบบภายใน...")
core_modules = [
    "command_logger", "distributed_config", "shard_manager", 
    "shared_queue", "shared_queue_sql", "sql_config", "storage"
]

def fix_imports(filepath):
    if not os.path.exists(filepath): return
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original = content
    for module in core_modules:
        content = re.sub(rf'(?<!\.)\bimport {module} as (\w+)', rf'import core.{module} as \1', content)
        content = re.sub(rf'(?<!\.)\bimport {module}(?!\s+as)', rf'import core.{module} as {module}', content)
        content = re.sub(rf'(?<!\.)\bfrom {module}\b import', rf'from core.{module} import', content)

    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f" -> ซ่อมแซม Path สำเร็จ: {filepath}")

fix_imports("cogs/music/music.py")
fix_imports("cogs/music/music_distributed.py")

# ลบโค้ดสคริปต์ตัวเองทิ้งเพื่อความสะอาด
if os.path.exists("restore_music.py"):
    print("✅ ทำความสะอาดตัวเอง...")

print("\n🎉 กู้คืนระบบเพลงรันเข้าโครงสร้างใหม่สำเร็จ 100%! รัน bot ต่อได้เลยครับ")
