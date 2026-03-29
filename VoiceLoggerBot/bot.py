import discord
import tempfile
import asyncio
import os
import sys
import shutil
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "1467898137459949742"))

# ============== เพิ่มตรงนี้ ==============
TARGET_STAGE_CHANNEL_ID = 1279771519811190925  # ช่อง Stage ที่ต้องการให้บอทเข้าเองทุกครั้ง
# =========================================

if not TOKEN:
    print("❌ ERROR: DISCORD_TOKEN not set in .env file!", flush=True)
    sys.exit(1)

print("=======================================", flush=True)
print(" Starting Voice Logger Bot... ", flush=True)
print("=======================================", flush=True)

try:
    import whisper
    print("✅ Whisper module found.", flush=True)
except ImportError:
    print("❌ ERROR: Whisper not found! Run: pip install openai-whisper", flush=True)
    sys.exit(1)

if not shutil.which("ffmpeg"):
    print("⚠️ WARNING: FFmpeg NOT found! Transcription will fail.", flush=True)
else:
    print("✅ FFmpeg found.", flush=True)

_model = None
def get_model():
    global _model
    if _model is None:
        print("⏳ Loading Whisper (tiny)...", flush=True)
        _model = whisper.load_model("tiny")
        print("✅ Whisper loaded!", flush=True)
    return _model

intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True

bot = discord.Bot(intents=intents)
active_recordings: dict[int, discord.VoiceClient] = {}

# ------------------------------------------------------------------
# Recording finished callback (เหมือนเดิม)
# ------------------------------------------------------------------
async def _finished_callback(
    sink: discord.sinks.WaveSink,
    channel: discord.TextChannel,
    guild_id: int,
):
    log_ch = bot.get_channel(LOG_CHANNEL_ID)
    if not sink.audio_data:
        await channel.send("🔇 No voice detected.")
        return

    status = await channel.send("⏳ Transcribing audio… please wait.")
    ai = get_model()
    results: list[tuple[str, str]] = []

    for user_id, audio in sink.audio_data.items():
        user = bot.get_user(user_id)
        display = user.display_name if user else f"User {user_id}"
        audio.file.seek(0)
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio.file.read())
                tmp_path = tmp.name
            res = await asyncio.to_thread(ai.transcribe, tmp_path, language="th")
            txt = (res.get("text") or "").strip()
            if txt:
                results.append((display, txt))
        except Exception as e:
            print(f"❌ Transcription error for {display}: {e}", flush=True)
            results.append((display, f"(transcription failed: {e})"))
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    try:
        await status.delete()
    except discord.HTTPException:
        pass

    if results:
        embed = discord.Embed(title="📝 Meeting Summary", color=discord.Color.blue())
        for display, text in results:
            embed.add_field(name=f"🎙️ {display}", value=text[:1024], inline=False)

        if log_ch:
            await log_ch.send(embed=embed)
            await channel.send("✅ Done! Report saved to log channel.")
        else:
            await channel.send("⚠️ Log channel not found — posting here instead:", embed=embed)
    else:
        await channel.send("🔇 No clear speech detected.")

# ------------------------------------------------------------------
# /เลขา-เริ่มบันทึก (เหมือนเดิม)
# ------------------------------------------------------------------
@bot.slash_command(name="เลขา-เริ่มบันทึก", description="เริ่มบันทึกเสียงในช่อง Stage ที่คุณอยู่")
async def start_recording(ctx: discord.ApplicationContext):
    await ctx.defer()
    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.followup.send("❌ กรุณาเข้าช่อง **Stage Channel** ก่อนนะครับ")

    channel = ctx.author.voice.channel
    if not isinstance(channel, discord.StageChannel):
        return await ctx.followup.send(
            "⚠️ **ต้องใช้ Stage Channel เท่านั้น**\n"
            "Discord บังคับใช้ E2EE (DAVE protocol) ตั้งแต่ 2 มีนาคม 2026\n"
            "ทำให้บอทไม่สามารถเชื่อมต่อ Voice Channel ปกติได้ (error 4017)\n\n"
            "**วิธีแก้:** สร้าง Stage Channel แล้วเข้าไปก่อนกดคำสั่งครับ"
        )

    if ctx.guild_id in active_recordings:
        return await ctx.followup.send("⚠️ กำลังบันทึกอยู่แล้ว ใช้ `/เลขา-หยุดบันทึก` เพื่อหยุดก่อน")

    await ctx.followup.send(f"⏳ กำลังเชื่อมต่อ Stage Channel **{channel.name}**…")

    try:
        vc: discord.VoiceClient = await channel.connect()
    except asyncio.TimeoutError:
        return await ctx.channel.send("❌ การเชื่อมต่อหมดเวลา กรุณาลองใหม่")
    except discord.ClientException as e:
        return await ctx.channel.send(f"❌ เชื่อมต่อไม่ได้: {e}")

    try:
        await ctx.guild.me.edit(suppress=False)  # กลายเป็น Speaker
    except Exception:
        pass

    try:
        vc.start_recording(
            discord.sinks.WaveSink(),
            _finished_callback,
            ctx.channel,
            ctx.guild_id,
        )
        active_recordings[ctx.guild_id] = vc
        await ctx.channel.send(
            f"🔴 **บันทึกเสียงใน {channel.name}**\n"
            "ใช้ `/เลขา-หยุดบันทึก` เพื่อหยุดและถอดข้อความ"
        )
    except Exception as e:
        active_recordings.pop(ctx.guild_id, None)
        try:
            await vc.disconnect(force=True)
        except Exception:
            pass
        await ctx.channel.send(f"❌ เริ่มบันทึกไม่ได้: {e}")

# ------------------------------------------------------------------
# /เลขา-หยุดบันทึก (เหมือนเดิม)
# ------------------------------------------------------------------
@bot.slash_command(name="เลขา-หยุดบันทึก", description="หยุดบันทึกและถอดข้อความ")
async def stop_recording(ctx: discord.ApplicationContext):
    await ctx.defer()
    vc = active_recordings.pop(ctx.guild_id, None)
    if not vc:
        return await ctx.followup.send("❌ ไม่ได้กำลังบันทึกอยู่ในขณะนี้")

    await ctx.followup.send("⏹️ หยุดบันทึกแล้ว กำลังประมวลผล…")
    try:
        vc.stop_recording()
    except Exception as e:
        await ctx.channel.send(f"⚠️ เกิดข้อผิดพลาดตอนหยุด: {e}")

    try:
        await vc.disconnect()
    except Exception as e:
        print(f"⚠️ Disconnect error (non-fatal): {e}", flush=True)

# ------------------------------------------------------------------
# on_ready - เพิ่มการเชื่อมต่ออัตโนมัติ
# ------------------------------------------------------------------
@bot.event
async def on_ready():
    print(f"✅ Bot online: {bot.user} (ID: {bot.user.id})", flush=True)
    print(f" Log channel ID: {LOG_CHANNEL_ID}", flush=True)
    print(f" 🎯 Target Stage Channel ID: {TARGET_STAGE_CHANNEL_ID}", flush=True)
    print(" ⚠️ Regular voice channels are broken (DAVE/E2EE error 4017) — Use Stage only!", flush=True)

    # === ส่วนที่เพิ่มใหม่: เข้า Stage Channel อัตโนมัติ ===
    try:
        channel = bot.get_channel(TARGET_STAGE_CHANNEL_ID)
        if not channel:
            print(f"❌ ไม่พบช่อง Stage ID {TARGET_STAGE_CHANNEL_ID}", flush=True)
            return

        if not isinstance(channel, discord.StageChannel):
            print(f"⚠️ ช่อง ID {TARGET_STAGE_CHANNEL_ID} ไม่ใช่ Stage Channel", flush=True)
            return

        if channel.guild.id in active_recordings:
            print("⚠️ กำลังบันทึกอยู่ใน Guild นี้แล้ว", flush=True)
            return

        print(f"⏳ กำลังเชื่อมต่อ Stage Channel: {channel.name} ...", flush=True)
        vc: discord.VoiceClient = await channel.connect()

        # กลายเป็น Speaker อัตโนมัติ
        try:
            await channel.guild.me.edit(suppress=False)
            print("✅ Bot กลายเป็น Speaker แล้ว", flush=True)
        except Exception as e:
            print(f"⚠️ ไม่สามารถกลายเป็น Speaker: {e}", flush=True)

        # เริ่มบันทึก
        vc.start_recording(
            discord.sinks.WaveSink(),
            _finished_callback,
            channel.guild.text_channels[0] if channel.guild.text_channels else None,  # ใช้ text channel แรกส่งข้อความ
            channel.guild.id,
        )
        active_recordings[channel.guild.id] = vc
        print(f"✅ เริ่มบันทึกเสียงใน {channel.name} อัตโนมัติแล้ว!", flush=True)

        # ส่งแจ้งเตือนใน text channel (เลือก channel ที่ต้องการได้)
        if channel.guild.text_channels:
            await channel.guild.text_channels[0].send(
                f"🔴 **บอทเริ่มบันทึกเสียงอัตโนมัติใน Stage: {channel.name}**\n"
                "ใช้ `/เลขา-หยุดบันทึก` เพื่อหยุด"
            )

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดตอนเชื่อมต่ออัตโนมัติ: {e}", flush=True)

if __name__ == "__main__":
    bot.run(TOKEN)