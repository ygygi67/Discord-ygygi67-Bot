import discord
from discord.ext import commands
from discord import app_commands
import os
import logging
import asyncio
import json
import sys
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Import Distributed Config
import core.distributed_config as dcfg
from core.distributed_config import is_master, is_worker, is_standalone, get_shard_ids

# Import custom config
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
APPLICATION_ID = os.getenv('APPLICATION_ID')

# Get base directory
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

COGS_DIR = os.path.join(BASE_DIR, 'cogs')
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

if COGS_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Set up logging
def setup_logging():
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)
    current_date = datetime.now().strftime('%Y-%m-%d')
    log_file = os.path.join(LOGS_DIR, f'bot_{current_date}.log')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.FileHandler(log_file, encoding='utf-8'), logging.StreamHandler()]
    )
    return logging.getLogger('discord_bot')

logger = setup_logging()

class DiscordLogHandler(logging.Handler):
    """Custom logging handler to send warnings/errors to Discord with batching"""
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.setLevel(logging.WARNING)
        self.queue = []
        self.is_processing = False

    def emit(self, record):
        if not self.bot.is_ready() or self.bot.is_closed():
            return
            
        msg = self.format(record)
        # ป้องกัน Log Loop: ถ้าข้อความเกี่ยวกับ rate limit หรือการส่ง log ล้มเหลว ห้าม log ซ้ำ
        if any(x in msg.lower() for x in ["failed to send log", "rate limited", "429", "session is closed", "gateway"]): 
            return
        
        self.queue.append((record.levelno, record.name, msg))
        if not self.is_processing:
            # ใช้ call_soon_threadsafe เพื่อให้สั่งงานข้าม Thread ได้ (เช่น จาก ffmpeg callback)
            self.bot.loop.call_soon_threadsafe(self._safe_start_process)

    def _safe_start_process(self):
        if not self.is_processing and not self.bot.is_closed():
            asyncio.create_task(self.process_queue())

    async def process_queue(self):
        if self.is_processing or self.bot.is_closed(): return
        self.is_processing = True
        await asyncio.sleep(5)
        try:
            if self.bot.is_closed(): return
            log_cog = self.bot.get_cog('ServerLogger')
            if not log_cog or not self.queue: return
            current_batch = self.queue[:]
            self.queue.clear()
            max_level = max(item[0] for item in current_batch)
            color = discord.Color.orange() if max_level == logging.WARNING else discord.Color.red()
            content = ""
            for _, name, msg in current_batch:
                line = f"**[{name}]** {msg}\n"
                if len(content) + len(line) > 1900:
                    content += "... (Truncated)"
                    break
                content += line
            embed = discord.Embed(
                title=f"🚨 System Logs (Batch x{len(current_batch)})",
                description=f"```\n{content}\n```",
                color=color,
                timestamp=datetime.now()
            )
            await log_cog.send_log(embed)
        except Exception: pass
        finally:
            self.is_processing = False
            if self.queue and not self.bot.is_closed():
                self.bot.loop.call_soon_threadsafe(self._safe_start_process)

class AlphaBotBase:
    """Base functionality for AlphaBot"""
    async def setup_hook(self):
        # Initialize queue for master mode
        if is_master() and not is_worker():
            from core.shared_queue import AsyncSharedQueue
            self.queue = AsyncSharedQueue()
            asyncio.create_task(self._cleanup_loop())
        
        # Load cogs
        await self._load_cogs()
        
        # Setup Discord log handler
        discord_logger = logging.getLogger('discord')
        if not any(isinstance(h, DiscordLogHandler) for h in discord_logger.handlers):
            handler = DiscordLogHandler(self)
            handler.setFormatter(logging.Formatter('%(name)s: %(message)s'))
            discord_logger.addHandler(handler)
            
        # Synchronize Slash Commands
        try:
            guild_id = os.getenv('DISCORD_GUILD_ID')
            commands_list = []
            if guild_id and guild_id.strip():
                guild = discord.Object(id=int(guild_id))
                self.tree.copy_global_to(guild=guild)
                commands_list = await self.tree.sync(guild=guild)
                logger.info(f"Tree synced to guild: {guild_id}")
            else:
                commands_list = await self.tree.sync()
                logger.info("Global tree synced")
            
            # Print command summary with wrapped lines for readability
            if commands_list:
                cmd_names = [f"/{cmd.name}" for cmd in commands_list]
                logger.info(f"✅ โหลดสำเร็จ {len(commands_list)} คำสั่ง:")
                chunk_size = 8
                for i in range(0, len(cmd_names), chunk_size):
                    logger.info(f"   > {', '.join(cmd_names[i:i + chunk_size])}")

                # Sanity check: catch cases where a whole block of commands silently disappears
                # (e.g., accidentally indented under a UI View class instead of the Cog).
                synced_names = {cmd.name for cmd in commands_list}
                expected_core = {"คำสั่ง", "สถิติ", "เสียง", "ระบบ", "ติดตาม", "เชิญบอทเต็ม", "โหลดคลิป"}
                missing_expected = sorted(expected_core - synced_names)
                if missing_expected:
                    logger.warning(
                        f"⚠️ คำสั่งบางส่วนหายจากการซิงค์: {', '.join('/' + n for n in missing_expected)} "
                        f"(ถ้าไม่ตั้งใจให้หาย ให้ตรวจสอบการประกาศ @app_commands.command ใน Cog)"
                    )
            else:
                logger.warning("⚠️ ไม่มีคำสั่งถูกโหลดขึ้นมาเลย")
                
        except discord.Forbidden:
            logger.warning(f"⚠️ Missing access to sync tree for guild {guild_id}. Falling back to global sync...")
            commands_list = await self.tree.sync()
            cmd_names = [f"/{cmd.name}" for cmd in commands_list]
            logger.info(f"✅ โหลดสำเร็จ {len(commands_list)} คำสั่ง (fallback):")
            chunk_size = 8
            for i in range(0, len(cmd_names), chunk_size):
                logger.info(f"   > {', '.join(cmd_names[i:i + chunk_size])}")
        except Exception as e:
            logger.error(f"Failed to sync tree: {e}")

    async def _load_cogs(self):
        logger.info(f"📁 Scanning for cogs in: {COGS_DIR}")
        if not os.path.exists(COGS_DIR):
            logger.error(f"❌ Cogs directory not found: {COGS_DIR}")
            return

        ignored = ['conversation.py', 'message_detection.py', 'say.py', 'fun.py', 'chat.py', '__pycache__']
        is_worker_mode = is_worker()
        target_cogs = ['music', 'stats'] if is_worker_mode else None
        
        loaded_count = 0
        for root, dirs, files in os.walk(COGS_DIR):
            if '__pycache__' in dirs:
                dirs.remove('__pycache__')
            
            for filename in files:
                if filename.endswith('.py') and filename not in ignored:
                    # แปลงที่อยู่ไฟล์จากโฟลเดอร์ให้เป็น format แบบ module import
                    # ตัวอย่าง: cogs\admin\roles.py -> cogs.admin.roles
                    rel_path = os.path.relpath(os.path.join(root, filename), BASE_DIR)
                    module_path = rel_path.replace(os.sep, '.')[:-3]
                    cog_name = filename[:-3]
                    
                    if target_cogs is not None and cog_name not in target_cogs: continue
                    try:
                        await self.load_extension(module_path)
                        logger.info(f"{'[Worker] ' if is_worker_mode else ''}Loaded: {module_path}")
                        loaded_count += 1
                    except Exception as e:
                        logger.error(f"❌ Failed to load {module_path}: {e}")
        
        logger.info(f"✅ Cog loading complete. Total loaded: {loaded_count}")

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(3600)
            try:
                from core.shared_queue import get_queue
                get_queue().cleanup_old_tasks(hours=24)
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

    async def on_ready(self):
        logger.info(f"✅ {self.mode.capitalize()} Ready! User: {self.user}")
        
        # Set activity
        activity_name = f"{len(self.guilds)} servers"
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=activity_name))

        # Auto-join voice channel if configured
        voice_id = os.getenv('AUTO_JOIN_VOICE_ID')
        if voice_id:
            try:
                # Wait a bit for guild cache
                await asyncio.sleep(2)
                channel = self.get_channel(int(voice_id)) or await self.fetch_channel(int(voice_id))
                if channel and isinstance(channel, discord.VoiceChannel):
                    # Check if already connected in that guild
                    if not channel.guild.voice_client:
                        await channel.connect()
                        logger.info(f"🔊 Auto-joined voice channel: {channel.name} ({voice_id})")
            except Exception as e:
                logger.error(f"Failed to auto-join voice channel {voice_id}: {e}")

    async def on_message(self, message):
        if message.author.bot: return
        await self.process_commands(message)

class AlphaBot(AlphaBotBase, commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        intents.members = True
        intents.message_content = True
        intents.presences = True
        super().__init__(command_prefix='!', intents=intents, application_id=APPLICATION_ID)
        self.start_time = datetime.now(timezone.utc)
        self.mode = 'standalone'

class DistributedAlphaBot(AlphaBotBase, commands.AutoShardedBot):
    def __init__(self, **kwargs):
        intents = discord.Intents.all()
        intents.members = True
        intents.message_content = True
        intents.presences = True
        
        shard_ids = get_shard_ids()
        total_shards = dcfg.TOTAL_SHARDS
        
        if shard_ids:
            # Clustering mode (Manual Shard IDs)
            kwargs['shard_ids'] = shard_ids
            kwargs['shard_count'] = total_shards or max(shard_ids) + 1
            print(f"🎲 Cluster handling specific shards: {shard_ids}")
        elif total_shards:
            # Auto-sharding with forced count
            kwargs['shard_count'] = total_shards
            print(f"🎲 Auto Sharding Mode with {total_shards} total shards")
        else:
            # Pure Auto-sharding
            print(f"🎲 Pure Auto Sharding Mode")
            
        super().__init__(command_prefix='!', intents=intents, application_id=APPLICATION_ID, **kwargs)
        self.start_time = datetime.now(timezone.utc)
        self.mode = dcfg.BOT_MODE

    async def on_shard_ready(self, shard_id):
        logger.info(f"🟢 Shard {shard_id} Ready")

def run_bot():
    if not TOKEN:
        logger.error("Error: TOKEN is not set in .env file.")
        sys.exit(1)

    if is_standalone():
        logger.info("🤖 Starting Standalone Mode")
        bot = AlphaBot()
    else:
        logger.info(f"🤖 Starting {dcfg.BOT_MODE.upper()} Mode")
        bot = DistributedAlphaBot()
    
    async def main():
        async with bot:
            await bot.start(TOKEN)

    try:
        asyncio.run(main())
    except KeyboardInterrupt: pass
    except Exception as e: logger.error(f"Fatal error: {e}")

if __name__ == "__main__":
    run_bot()
