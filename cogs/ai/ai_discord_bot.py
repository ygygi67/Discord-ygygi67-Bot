# =========================================
# 🤖 AI Discord Bot (v3 - Channel & Room System)
# by YGYG67
# Features:
#   - Long-Term Memory (facts + summaries)
#   - Multi-Personality Modes
#   - Auto Conversation Summarization
#   - Async / Fast Response (aiohttp)
#   - AI Channel Zone (auto-reply in designated channels)
#   - Personal AI Room (category + private channel per user)
#   - Multi-server support (per guild_id config)
# =========================================

import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import asyncio
import aiohttp
import logging
from datetime import datetime
from typing import Optional
from cogs.utility.server_link import get_guild_settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
OLLAMA_URL  = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL       = os.getenv("AI_MODEL", "llama3")

_BASE = os.path.dirname(os.path.abspath(__file__))
MEMORY_PATH      = os.path.normpath(os.path.join(_BASE, "..", "..", "data", "ai_memory.json"))
GUILD_CFG_PATH   = os.path.normpath(os.path.join(_BASE, "..", "..", "data", "ai_guild_config.json"))

MAX_HISTORY_PAIRS = 20   # เพิ่มจาก 12 เป็น 20 เพื่อเก็บ context นานขึ้น
CATEGORY_NAME     = "🤖 AI Rooms"  # ชื่อ category ที่จะสร้าง

# ─────────────────────────────────────────
# 🎭 PERSONALITIES
# ─────────────────────────────────────────
PERSONALITIES: dict[str, dict] = {
    "casual": {
        "label": "😺 เพื่อนสนิท (ค่าเริ่มต้น)",
        "prompt": (
            'คุณคือ AI ผู้ช่วยชื่อ "โมสต์" ถูกสร้างโดย YGYG67\n'
            "บุคลิก: เป็นกันเองเหมือนเพื่อนสนิท คุยสนุก ตอบละเอียด มีความเห็นส่วนตัว\n"
            "กฎสำคัญ:\n"
            "1. ตอบเป็นภาษาเดียวกับที่ผู้ใช้ถามเสมอ (ไทย=ไทย, อังกฤษ=อังกฤษ)\n"
            "2. ตอบยาว ๆ เป็นธรรมชาติ เหมือนคุยกับเพื่อนจริง ๆ\n"
            "3. แสดงความคิดเห็นและอารมณ์ได้\n"
            "4. ใช้คำว่า เออ, อืม, นะ, 555, จริงดิ, เว่อร์ ได้ตามสถานการณ์\n"
            "5. ถ้าไม่รู้จริง ๆ ให้บอกตรง ๆ\n"
            "6. ชอบถามกลับเพื่อให้บทสนทนาดำเนินต่อ\n"
            "7. แชร์ประสบการณ์และเรื่องราวที่เกี่ยวข้องได้\n"
            "8. จำเรื่องที่คุยกันได้และอ้างอิงถึงบทสนทนาก่อนหน้า"
        ),
    },
    "formal": {
        "label": "👔 ทางการ",
        "prompt": (
            'คุณคือผู้ช่วย AI มืออาชีพชื่อ "Alpha" ถูกสร้างโดย YGYG67\n'
            "บุคลิก: สุภาพ มืออาชีพ ให้ข้อมูลครบถ้วน\n"
            "กฎสำคัญ:\n"
            "1. ตอบเป็นภาษาเดียวกับที่ผู้ใช้ถามเสมอ\n"
            "2. ตอบละเอียด มีโครงสร้างชัดเจน\n"
            "3. ใช้ภาษาที่ถูกต้องและสุภาพ\n"
            "4. อธิบายเป็นขั้นตอนเมื่อจำเป็น\n"
            "5. ให้ตัวอย่างประกอบการอธิบาย\n"
            "6. ถามความต้องการเพิ่มเติมเพื่อช่วยได้ครบถ้วน"
        ),
    },
    "teacher": {
        "label": "📚 ครู/อธิบายละเอียด",
        "prompt": (
            'คุณคือ AI ครูชื่อ "อาจารย์โมสต์" ถูกสร้างโดย YGYG67\n'
            "บุคลิก: ใจดี อธิบายละเอียด ทำให้เข้าใจง่าย\n"
            "กฎสำคัญ:\n"
            "1. ตอบเป็นภาษาเดียวกับที่ผู้ใช้ถามเสมอ\n"
            "2. อธิบายเป็นขั้นตอน จากง่ายไปยาก\n"
            "3. ใช้ตัวอย่างจากชีวิตจริง\n"
            "4. ถามว่าเข้าใจไหม หรือต้องการให้อธิบายเพิ่ม\n"
            "5. ให้ข้อมูลพื้นฐานก่อนลงรายละเอียด\n"
            "6. ใช้เปรียบเทียบเพื่อให้เห็นภาพชัด\n"
            "7. สรุปประเด็นสำคัญท้ายบทสนทนา"
        ),
    },
    "funny": {
        "label": "😂 ตลก/สนุกสนาน",
        "prompt": (
            'คุณคือ AI ชื่อ "โมสต์ฮา" ถูกสร้างโดย YGYG67\n'
            "บุคลิก: ตลก เฮฮา ช่างคุย มีมส์แน่น\n"
            "กฎสำคัญ:\n"
            "1. ตอบเป็นภาษาเดียวกับที่ผู้ใช้ถามเสมอ\n"
            "2. ตอบด้วยความขำขัน แต่ให้ข้อมูลที่ถูกต้อง\n"
            "3. ใช้มีมส์และคำตลก ๆ ได้\n"
            "4. ชอบเล่นมุกตอบกลับ\n"
            "5. บรรยากาศสนุกสนาน ไม่จริงจังมาก\n"
            "6. เหมือนคุยกับเพื่อนตลก ๆ\n"
            "7. ใช้อิโมจิและคำว่า 555 ได้เต็มที่"
        ),
    },
    "deep": {
        "label": "🤔 คิดลึก/ปรัชญา",
        "prompt": (
            'คุณคือ AI นักคิดชื่อ "โมสต์" ถูกสร้างโดย YGYG67\n'
            "บุคลิก: ชอบคิดวิเคราะห์ มองหลายมุม ถกเถียงเชิงลึก\n"
            "กฎสำคัญ:\n"
            "1. ตอบเป็นภาษาเดียวกับที่ผู้ใช้ถามเสมอ\n"
            "2. วิเคราะห์หลายมุมมองของประเด็น\n"
            "3. ถามคำถามกลับเพื่อให้คิด\n"
            "4. อ้างอิงแนวคิดหรือทฤษฎีที่เกี่ยวข้อง\n"
            "5. ชวนถกเถียงและแลกเปลี่ยนความคิดเห็น\n"
            "6. ไม่ตัดสินว่าอะไรถูกผิดแต่นำเสนอข้อมูล\n"
            "7. ชวนคิดต่อไปเรื่อย ๆ"
        ),
    },
}

# ═══════════════════════════════════════════════════════
# 💾 GUILD CONFIG  (เก็บ per-server settings)
# ═══════════════════════════════════════════════════════

def _load_guild_cfg() -> dict:
    try:
        os.makedirs(os.path.dirname(GUILD_CFG_PATH), exist_ok=True)
        with open(GUILD_CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_guild_cfg(data: dict):
    os.makedirs(os.path.dirname(GUILD_CFG_PATH), exist_ok=True)
    with open(GUILD_CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _get_guild_data(guild_id: str) -> dict:
    cfg = _load_guild_cfg()
    return cfg.get(guild_id, {
        "ai_channels": [],      # list[int]  — channel IDs ที่กำหนดเป็น AI zone
        "personal_rooms": {},   # {user_id: channel_id}
    })

def _save_guild_data(guild_id: str, guild_data: dict):
    cfg = _load_guild_cfg()
    cfg[guild_id] = guild_data
    _save_guild_cfg(cfg)

# helper ── ตรวจสอบว่า channel นี้เป็น AI zone หรือไม่
def is_ai_channel(guild_id: str, channel_id: int) -> bool:
    gd = _get_guild_data(guild_id)
    return channel_id in gd.get("ai_channels", [])

# ═══════════════════════════════════════════════════════
# 💾 USER MEMORY
# ═══════════════════════════════════════════════════════

def _load_raw() -> dict:
    try:
        os.makedirs(os.path.dirname(MEMORY_PATH), exist_ok=True)
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_raw(data: dict):
    os.makedirs(os.path.dirname(MEMORY_PATH), exist_ok=True)
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _get_user_data(uid: str) -> dict:
    data = _load_raw()
    return data.get(uid, {
        "facts": {},
        "history": [],
        "summary": "",
        "personality": "casual",
        "last_seen": "",
    })

def _save_user_data(uid: str, user_data: dict):
    data = _load_raw()
    user_data["last_seen"] = datetime.now().isoformat(timespec="seconds")
    data[uid] = user_data
    _save_raw(data)

# ─────────────────────────────────────────
# 🧠 FACT EXTRACTOR
# ─────────────────────────────────────────
FACT_RULES = [
    ("ชื่อ",      "ชื่อ",      "name"),
    ("เรียกฉัน",  "เรียกฉัน",  "name"),
    ("อยู่ที่",   "อยู่ที่",   "location"),
    ("อยู่แถว",   "อยู่แถว",   "location"),
    ("เกิดปี",    "เกิดปี",    "birth_year"),
    ("อายุ",      "อายุ",      "age"),
    ("ทำงาน",     "ทำงาน",     "job"),
    ("เรียน",     "เรียน",     "school"),
    ("ชอบ",       "ชอบ",       "likes"),
]

def extract_facts(text: str) -> dict:
    facts = {}
    for keyword, split_on, key in FACT_RULES:
        if keyword in text:
            parts = text.split(split_on, 1)
            if len(parts) > 1:
                value = parts[1].strip().split()[0] if parts[1].strip() else ""
                if value:
                    facts[key] = value
    return facts

# ─────────────────────────────────────────
# 🗜️ AUTO SUMMARIZER
# ─────────────────────────────────────────
async def summarize_history(session: aiohttp.ClientSession, history: list[dict]) -> str:
    convo_text = "\n".join(
        f"{'ผู้ใช้' if h['role'] == 'user' else 'บอท'}: {h['msg']}"
        for h in history
    )
    prompt = f"""สรุปบทสนทนาต่อไปนี้เป็น 2-3 ประโยคภาษาไทย ให้ครอบคลุมประเด็นสำคัญ:

{convo_text}

สรุป:"""
    try:
        async with session.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.3}},
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            result = await resp.json()
            return result.get("response", "").strip()
    except Exception as e:
        logger.warning(f"[AI] summarize failed: {e}")
        return " | ".join(h["msg"][:80] for h in history[:3] if h["role"] == "user")

# ─────────────────────────────────────────
# 🧠 PROMPT BUILDER
# ─────────────────────────────────────────
def build_prompt(user_data: dict, user_input: str) -> str:
    persona_key = user_data.get("personality", "casual")
    persona = PERSONALITIES.get(persona_key, PERSONALITIES["casual"])

    facts = user_data.get("facts", {})
    fact_lines = "\n".join(f"- {k}: {v}" for k, v in facts.items()) or "- (ยังไม่มีข้อมูล)"

    summary = user_data.get("summary", "")
    summary_section = f"\n[สรุปบทสนทนาก่อนหน้า]\n{summary}" if summary else ""

    history = user_data.get("history", [])
    history_text = "\n".join(
        f"{'ผู้ใช้' if h['role'] == 'user' else 'บอท'}: {h['msg']}"
        for h in history[-10:]  # แสดง 10 ข้อความล่าสุด
    )

    # เพิ่มคำแนะนำให้ AI ตอบยาวและเป็นธรรมชาติ พร้อมตรวจสอบภาษาและหัวข้อ
    response_guide = """
[คำแนะนำการตอบ]
- ตอบให้ละเอียดและเป็นธรรมชาติ เหมือนคุยกับเพื่อนจริง ๆ
- ถ้าคำถามซับซ้อน อธิบายให้เข้าใจง่าย
- ถ้าคำถามง่าย ตอบสั้นกระชับแต่เป็นกันเอง
- ถามกลับเพื่อให้บทสนทนดำเนินต่อไป
- ใช้อิโมจิและคำ filler (อืม, เออ, นะ) ตามสมควร
- แสดงความคิดเห็นหรือประสบการณ์ส่วนตัวได้
- อ้างอิงบทสนทนาก่อนหน้าและต่อยอดความคิด
- ชวนคุยต่อด้วยคำถามที่เกี่ยวข้อง

[ตรวจสอบภาษา]
ตอบเป็นภาษาเดียวกับที่ผู้ใช้ใช้เสมอ ไม่สลับภาษา

[ติดตามหัวข้อ]
จำหัวข้อที่กำลังคุยอยู่ และตอบให้สอดคล้องกับบริบท
"""

    return (
        f"{persona['prompt']}\n\n"
        f"[ข้อมูลระยะยาวของผู้ใช้]\n{fact_lines}\n"
        f"{summary_section}\n\n"
        f"[ประวัติการสนทนาล่าสุด - 20 ข้อความ]\n{history_text}\n"
        f"{response_guide}\n\n"
        f"ผู้ใช้: {user_input}\n"
        f"บอท:"
    )

# ─────────────────────────────────────────
# 🤖 AI CALLER  (async)
# ─────────────────────────────────────────
async def call_ai(session: aiohttp.ClientSession, prompt: str) -> str:
    try:
        async with session.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 1024,
                    "top_p": 0.9,
                    "top_k": 40,
                    "repeat_penalty": 1.1,
                    "stop": ["\nผู้ใช้:", "\nUser:", "ผู้ใช้:", "User:"],
                },
            },
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            result = await resp.json()
            return result.get("response", "").strip()
    except asyncio.TimeoutError:
        return "⏳ AI ใช้เวลานานเกินไป ลองถามใหม่อีกครั้งนะ"
    except Exception as e:
        logger.error(f"[AI] call failed: {e}")
        return f"❌ เรียก AI ไม่ได้: {e}"


# ═══════════════════════════════════════════════════════
# 🎮 COG
# ═══════════════════════════════════════════════════════
class AIBot(commands.Cog):
    """🤖 AI Chat Bot — Memory, Multi-Personality, Channels & Personal Rooms"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: Optional[aiohttp.ClientSession] = None
        # cache ของ channel IDs ที่เป็น AI zone (populate ตอน ready)
        self._ai_channel_cache: set[int] = set()

    async def cog_load(self):
        self._session = aiohttp.ClientSession()
        self._rebuild_cache()
        logger.info("✅ AIBot cog loaded")

    async def cog_unload(self):
        if self._session:
            await self._session.close()

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _rebuild_cache(self):
        """โหลด AI channel IDs ทุก guild เข้า cache"""
        cfg = _load_guild_cfg()
        self._ai_channel_cache = set()
        for gd in cfg.values():
            for cid in gd.get("ai_channels", []):
                self._ai_channel_cache.add(int(cid))

    # ──────────────────────────────────────
    # CORE: process chat message
    # ──────────────────────────────────────
    async def _process_chat(self, uid: str, display_name: str, text: str) -> str:
        loop = asyncio.get_event_loop()
        user_data = await loop.run_in_executor(None, _get_user_data, uid)

        # อัป facts
        new_facts = extract_facts(text)
        if new_facts:
            user_data["facts"].update(new_facts)
        if "name" not in user_data["facts"]:
            user_data["facts"]["name"] = display_name

        # auto-summarize
        history = user_data.get("history", [])
        if len(history) >= MAX_HISTORY_PAIRS * 2:
            half = len(history) // 2
            old_half, new_half = history[:half], history[half:]
            logger.info(f"[AI] Auto-summarizing {len(old_half)} msgs for {uid}")
            new_summary = await summarize_history(self.session, old_half)
            old_summary = user_data.get("summary", "")
            user_data["summary"] = f"{old_summary}\n{new_summary}".strip() if old_summary else new_summary
            user_data["history"] = new_half

        prompt = build_prompt(user_data, text)
        reply = await call_ai(self.session, prompt)

        user_data["history"].append({"role": "user", "msg": text[:500]})
        user_data["history"].append({"role": "bot",  "msg": reply[:500]})
        await loop.run_in_executor(None, _save_user_data, uid, user_data)
        return reply

    @staticmethod
    def _split(text: str, length: int = 1990) -> list[str]:
        return [text[i:i+length] for i in range(0, len(text), length)]

    # ──────────────────────────────────────
    # EVENT: on_message — auto-reply in AI zones
    # ──────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # กรอง: บอท, DM, ช่องที่ไม่ใช่ AI zone
        if message.author.bot:
            return
        if not message.guild:
            return
        if message.channel.id not in self._ai_channel_cache:
            return

        # ตรวจสอบ config อีกครั้งจากไฟล์ (ป้องกัน cache stale)
        if not is_ai_channel(str(message.guild.id), message.channel.id):
            self._ai_channel_cache.discard(message.channel.id)
            return

        async with message.channel.typing():
            reply = await self._process_chat(
                str(message.author.id),
                message.author.display_name,
                message.content,
            )
        for chunk in self._split(reply):
            await message.channel.send(chunk)

    # ──────────────────────────────────────
    # SLASH: /ai
    # ──────────────────────────────────────
    @app_commands.command(name="ai", description="💬 คุยกับ AI โมสต์ (มีความจำระยะยาว)")
    @app_commands.describe(ข้อความ="พิมพ์ข้อความที่ต้องการถามหรือคุย")
    async def ai_chat(self, interaction: discord.Interaction, ข้อความ: str):
        await interaction.response.defer(thinking=True)
        reply = await self._process_chat(
            str(interaction.user.id),
            interaction.user.display_name,
            ข้อความ,
        )
        chunks = self._split(reply)
        await interaction.followup.send(chunks[0])
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)

    # ──────────────────────────────────────
    # PREFIX: !chat / !โมสต์ / !ai
    # ──────────────────────────────────────
    @commands.command(name="chat", aliases=["โมสต์", "ai"])
    async def chat_prefix(self, ctx: commands.Context, *, text: str):
        async with ctx.typing():
            reply = await self._process_chat(
                str(ctx.author.id), ctx.author.display_name, text
            )
        for chunk in self._split(reply):
            await ctx.send(chunk)

    # ══════════════════════════════════════
    # 📌 AI CHANNEL ZONE COMMANDS
    # ══════════════════════════════════════

    @app_commands.command(
        name="ai_setchannel",
        description="📌 กำหนด/ยกเลิกห้องนี้เป็น AI Zone (บอทจะตอบทุกข้อความอัตโนมัติ)"
    )
    @app_commands.describe(channel="ห้องที่ต้องการตั้งเป็น AI Zone (เว้นว่าง = ห้องปัจจุบัน)")
    @app_commands.default_permissions(manage_channels=True)
    async def ai_setchannel(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
    ):
        guild_id = str(interaction.guild_id)
        target = channel or interaction.channel

        loop = asyncio.get_event_loop()
        gd = await loop.run_in_executor(None, _get_guild_data, guild_id)
        ai_channels: list = gd.setdefault("ai_channels", [])

        if target.id in ai_channels:
            # ยกเลิก
            ai_channels.remove(target.id)
            self._ai_channel_cache.discard(target.id)
            await loop.run_in_executor(None, _save_guild_data, guild_id, gd)
            embed = discord.Embed(
                title="🔕 ยกเลิก AI Zone แล้ว",
                description=f"{target.mention} ถูกลบออกจาก AI Zone\nบอทจะไม่ตอบอัตโนมัติในห้องนี้แล้ว",
                color=discord.Color.orange(),
            )
        else:
            # เพิ่ม
            ai_channels.append(target.id)
            self._ai_channel_cache.add(target.id)
            await loop.run_in_executor(None, _save_guild_data, guild_id, gd)
            embed = discord.Embed(
                title="📌 ตั้งเป็น AI Zone สำเร็จ",
                description=(
                    f"{target.mention} เป็น AI Zone แล้ว!\n"
                    "บอทจะตอบกลับ **ทุกข้อความ** ในห้องนี้โดยอัตโนมัติ 🤖"
                ),
                color=discord.Color.green(),
            )
            embed.add_field(
                name="💡 เคล็ดลับ",
                value="ใช้คำสั่งนี้อีกครั้งในห้องเดิมเพื่อยกเลิก AI Zone",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="ai_listchannels",
        description="📋 ดูรายการห้อง AI Zone ในเซิร์ฟเวอร์นี้"
    )
    async def ai_listchannels(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        loop = asyncio.get_event_loop()
        gd = await loop.run_in_executor(None, _get_guild_data, guild_id)
        ch_ids: list = gd.get("ai_channels", [])

        if not ch_ids:
            await interaction.response.send_message(
                "📭 ยังไม่มีห้อง AI Zone ในเซิร์ฟเวอร์นี้\n"
                "ใช้ `/ai_setchannel` เพื่อตั้งห้องเป็น AI Zone",
                ephemeral=True,
            )
            return

        mentions = []
        for cid in ch_ids:
            ch = interaction.guild.get_channel(cid)
            mentions.append(ch.mention if ch else f"`{cid}` *(ลบไปแล้ว)*")

        embed = discord.Embed(
            title="📋 AI Zone Channels",
            description="\n".join(f"• {m}" for m in mentions),
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"รวม {len(ch_ids)} ห้อง")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ══════════════════════════════════════
    # 🏠 PERSONAL AI ROOM COMMANDS
    # ══════════════════════════════════════

    @app_commands.command(
        name="ai_myroom",
        description="🏠 สร้างห้องคุย AI ส่วนตัวของคุณ (มองเห็นแค่คุณกับบอท)"
    )
    async def ai_myroom(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        guild = interaction.guild
        user  = interaction.user
        guild_id = str(guild.id)
        uid      = str(user.id)
        loop     = asyncio.get_event_loop()

        # Check server settings
        settings = get_guild_settings(guild.id)
        if not settings.get("ai_room_allowed", True):
            await interaction.followup.send("❌ แอดมินปิดการใช้งานคำสั่งสร้างห้อง AI ในเซิร์ฟเวอร์นี้ (ติดต่อแอดมินให้ใช้ `/setup_server`)", ephemeral=True)
            return

        gd = await loop.run_in_executor(None, _get_guild_data, guild_id)
        personal_rooms: dict = gd.setdefault("personal_rooms", {})

        # ตรวจว่ามีห้องเดิมอยู่ไหม
        existing_id = personal_rooms.get(uid)
        if existing_id:
            existing_ch = guild.get_channel(existing_id)
            if existing_ch:
                embed = discord.Embed(
                    title="🏠 ห้องของคุณมีอยู่แล้ว!",
                    description=f"ห้อง AI ส่วนตัวของคุณคือ {existing_ch.mention}",
                    color=discord.Color.gold(),
                )
                embed.add_field(
                    name="💡 เคล็ดลับ",
                    value="ใช้ `/ai_deleteroom` เพื่อลบและสร้างใหม่",
                    inline=False,
                )
                await interaction.followup.send(embed=embed)
                return
            else:
                # ห้องถูกลบไปแล้ว ล้าง record เก่า
                del personal_rooms[uid]

        # ── หา/สร้าง category ──
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        if category is None:
            try:
                category = await guild.create_category(
                    CATEGORY_NAME,
                    reason=f"AI Personal Rooms — created for {user}",
                )
                logger.info(f"[AI] Created category '{CATEGORY_NAME}' in guild {guild.id}")
            except discord.Forbidden:
                await interaction.followup.send(
                    "❌ บอทไม่มีสิทธิ์สร้าง Category — กรุณาให้สิทธิ์ `Manage Channels`"
                )
                return

        # ── permission overwrites ──
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            ),
        }

        # sanitize ชื่อห้อง (ชื่อ Discord ห้ามมีตัวพิเศษบางตัว)
        safe_name = "".join(
            c if c.isascii() and (c.isalnum() or c in "-_ ") else ""
            for c in user.display_name
        ).strip() or str(user.id)
        channel_name = f"ai-{safe_name.lower().replace(' ', '-')}"

        # ── สร้างห้อง ──
        try:
            new_ch = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"🤖 ห้อง AI ส่วนตัวของ {user.display_name} — พิมพ์ได้เลย บอทตอบอัตโนมัติ",
                reason=f"AI personal room for {user} ({user.id})",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ บอทไม่มีสิทธิ์สร้าง Text Channel — กรุณาให้สิทธิ์ `Manage Channels`"
            )
            return

        # บันทึก
        personal_rooms[uid] = new_ch.id
        gd["personal_rooms"] = personal_rooms
        # เพิ่มห้องใหม่เข้า AI zone อัตโนมัติ
        gd.setdefault("ai_channels", []).append(new_ch.id)
        self._ai_channel_cache.add(new_ch.id)
        await loop.run_in_executor(None, _save_guild_data, guild_id, gd)

        # ส่ง welcome message ในห้องใหม่
        embed_welcome = discord.Embed(
            title=f"👋 ยินดีต้อนรับสู่ห้อง AI ของคุณ {user.display_name}!",
            description=(
                "นี่คือห้องคุย AI ส่วนตัวของคุณ 🎉\n\n"
                "**วิธีใช้:**\n"
                "• พิมพ์อะไรก็ได้ — บอทจะตอบอัตโนมัติ\n"
                "• `/ai_mode` — เปลี่ยน personality ของ AI\n"
                "• `/ai_memory` — ดูความจำที่ AI มีเกี่ยวกับคุณ\n\n"
                "**มีแค่คุณและบอทที่เห็นห้องนี้ได้** 🔒"
            ),
            color=discord.Color.purple(),
        )
        embed_welcome.set_footer(text="ใช้ /ai_deleteroom เพื่อลบห้องนี้")
        await new_ch.send(user.mention, embed=embed_welcome)

        # ตอบกลับ interaction
        embed_reply = discord.Embed(
            title="✅ สร้างห้อง AI ส่วนตัวสำเร็จ!",
            description=f"ห้องของคุณอยู่ที่ {new_ch.mention} ภายใต้หมวดโมสต์ **{CATEGORY_NAME}**",
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=embed_reply)

    # ──────────────────────────────────────
    # /ai_deleteroom — ลบห้องส่วนตัว
    # ──────────────────────────────────────
    @app_commands.command(
        name="ai_deleteroom",
        description="🗑️ ลบห้อง AI ส่วนตัวของคุณ"
    )
    async def ai_deleteroom(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        uid      = str(interaction.user.id)
        loop     = asyncio.get_event_loop()

        gd = await loop.run_in_executor(None, _get_guild_data, guild_id)
        personal_rooms: dict = gd.get("personal_rooms", {})
        ch_id = personal_rooms.get(uid)

        if not ch_id:
            await interaction.response.send_message(
                "❓ คุณยังไม่มีห้อง AI ส่วนตัว ใช้ `/ai_myroom` เพื่อสร้าง",
                ephemeral=True,
            )
            return

        ch = interaction.guild.get_channel(ch_id)
        await interaction.response.defer(thinking=True, ephemeral=True)

        # ลบออกจาก config
        del personal_rooms[uid]
        gd["personal_rooms"] = personal_rooms
        # ลบออกจาก AI zone ด้วย
        if ch_id in gd.get("ai_channels", []):
            gd["ai_channels"].remove(ch_id)
        self._ai_channel_cache.discard(ch_id)
        await loop.run_in_executor(None, _save_guild_data, guild_id, gd)

        # ลบห้องจริง
        if ch:
            try:
                await ch.delete(reason=f"AI room deleted by {interaction.user}")
            except Exception as e:
                logger.warning(f"[AI] Failed to delete room {ch_id}: {e}")

        await interaction.followup.send("🗑️ ลบห้อง AI ส่วนตัวของคุณเรียบร้อยแล้ว!")

    # ──────────────────────────────────────
    # /ai_rooms_list — (Admin) ดูห้องทั้งหมด
    # ──────────────────────────────────────
    @app_commands.command(
        name="ai_rooms_list",
        description="📊 (Admin) ดูรายการห้อง AI ส่วนตัวทั้งหมดในเซิร์ฟเวอร์"
    )
    @app_commands.default_permissions(manage_channels=True)
    async def ai_rooms_list(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        loop     = asyncio.get_event_loop()
        gd       = await loop.run_in_executor(None, _get_guild_data, guild_id)
        rooms    = gd.get("personal_rooms", {})

        if not rooms:
            await interaction.response.send_message(
                "📭 ยังไม่มีห้อง AI ส่วนตัวในเซิร์ฟเวอร์นี้",
                ephemeral=True,
            )
            return

        lines = []
        for uid, cid in rooms.items():
            member = interaction.guild.get_member(int(uid))
            ch     = interaction.guild.get_channel(cid)
            name   = member.mention if member else f"`{uid}`"
            room   = ch.mention if ch else f"`{cid}` *(ลบไปแล้ว)*"
            lines.append(f"• {name} → {room}")

        embed = discord.Embed(
            title="📊 AI Personal Rooms",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"รวม {len(rooms)} ห้อง")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ══════════════════════════════════════
    # 🎭 PERSONALITY / MEMORY COMMANDS
    # ══════════════════════════════════════

    @app_commands.command(name="ai_mode", description="🎭 เปลี่ยน personality ของ AI")
    @app_commands.describe(โหมด="เลือก personality ที่ต้องการ")
    @app_commands.choices(โหมด=[
        app_commands.Choice(name=v["label"], value=k)
        for k, v in PERSONALITIES.items()
    ])
    async def ai_mode(self, interaction: discord.Interaction, โหมด: str):
        uid  = str(interaction.user.id)
        loop = asyncio.get_event_loop()
        ud   = await loop.run_in_executor(None, _get_user_data, uid)
        ud["personality"] = โหมด
        await loop.run_in_executor(None, _save_user_data, uid, ud)
        label = PERSONALITIES[โหมด]["label"]
        embed = discord.Embed(
            title="🎭 เปลี่ยน Personality สำเร็จ",
            description=f"ตอนนี้ AI จะคุยในโหมด **{label}** กับคุณแล้ว!",
            color=discord.Color.purple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ai_memory", description="🧠 ดู/ลบ ความจำที่ AI มีเกี่ยวกับคุณ")
    @app_commands.describe(action="ดูความจำ หรือ ลบความจำทั้งหมด")
    @app_commands.choices(action=[
        app_commands.Choice(name="👁️ ดูความจำ",          value="view"),
        app_commands.Choice(name="📜 ดูสรุปบทสนทนา",      value="summary"),
        app_commands.Choice(name="🗑️ ลบความจำทั้งหมด",   value="clear"),
    ])
    async def ai_memory(self, interaction: discord.Interaction, action: str):
        uid  = str(interaction.user.id)
        loop = asyncio.get_event_loop()
        ud   = await loop.run_in_executor(None, _get_user_data, uid)

        if action == "view":
            facts    = ud.get("facts", {})
            persona  = ud.get("personality", "casual")
            hist_cnt = len(ud.get("history", [])) // 2
            last     = ud.get("last_seen", "ไม่ทราบ")
            fact_txt = ("\n".join(f"**{k}**: {v}" for k, v in facts.items())
                        or "_ยังไม่มีข้อมูล_")
            embed = discord.Embed(
                title=f"🧠 ความจำของ AI เกี่ยวกับ {interaction.user.display_name}",
                color=discord.Color.blue(),
            )
            embed.add_field(name="📋 ข้อมูลที่จำได้", value=fact_txt, inline=False)
            embed.add_field(
                name="🎭 Personality ปัจจุบัน",
                value=PERSONALITIES.get(persona, PERSONALITIES["casual"])["label"],
                inline=True,
            )
            embed.add_field(name="💬 บทสนทนา (ล่าสุด)", value=f"{hist_cnt} รอบ", inline=True)
            embed.set_footer(text=f"เห็นล่าสุด: {last}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif action == "summary":
            summary = ud.get("summary", "")
            if not summary:
                await interaction.response.send_message(
                    "📭 ยังไม่มีสรุปบทสนทนา (คุยก่อนนะ)", ephemeral=True
                )
                return
            embed = discord.Embed(
                title="📜 สรุปบทสนทนา",
                description=summary[:4000],
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif action == "clear":
            persona = ud.get("personality", "casual")
            new_ud  = {"facts": {}, "history": [], "summary": "",
                       "personality": persona, "last_seen": ud.get("last_seen", "")}
            await loop.run_in_executor(None, _save_user_data, uid, new_ud)
            await interaction.response.send_message(
                "🗑️ ลบความจำทั้งหมดแล้ว! (เก็บ personality ไว้ให้)", ephemeral=True
            )

    @app_commands.command(name="ai_summarize_now", description="📝 สั่งให้ AI สรุปบทสนทนาทันที")
    async def ai_summarize_now(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        uid  = str(interaction.user.id)
        loop = asyncio.get_event_loop()
        ud   = await loop.run_in_executor(None, _get_user_data, uid)
        hist = ud.get("history", [])
        if len(hist) < 2:
            await interaction.followup.send("💭 บทสนทนายังน้อยเกินไป")
            return
        summary    = await summarize_history(self.session, hist)
        old_sum    = ud.get("summary", "")
        ud["summary"] = f"{old_sum}\n{summary}".strip() if old_sum else summary
        ud["history"] = []
        await loop.run_in_executor(None, _save_user_data, uid, ud)
        embed = discord.Embed(title="✅ สรุปบทสนทนาแล้ว",
                              description=summary[:4000], color=discord.Color.gold())
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="ai_forget_fact",
                          description="🔁 ลบข้อมูลเฉพาะอย่างที่ AI จำเกี่ยวกับคุณ")
    @app_commands.describe(ชื่อข้อมูล="เช่น name, location, age, likes ฯลฯ")
    async def ai_forget_fact(self, interaction: discord.Interaction, ชื่อข้อมูล: str):
        uid  = str(interaction.user.id)
        loop = asyncio.get_event_loop()
        ud   = await loop.run_in_executor(None, _get_user_data, uid)
        key  = ชื่อข้อมูล.strip().lower()
        if key in ud.get("facts", {}):
            del ud["facts"][key]
            await loop.run_in_executor(None, _save_user_data, uid, ud)
            await interaction.response.send_message(f"✅ ลืม **{key}** แล้ว!", ephemeral=True)
        else:
            keys = ", ".join(ud.get("facts", {}).keys()) or "ไม่มี"
            await interaction.response.send_message(
                f"❓ ไม่พบ **{key}**\nข้อมูลที่มี: `{keys}`", ephemeral=True
            )


# ═══════════════════════════════════════════════════════
# 🚀 SETUP
# ═══════════════════════════════════════════════════════
async def setup(bot: commands.Bot):
    await bot.add_cog(AIBot(bot))
    logger.info("✅ AIBot cog registered")