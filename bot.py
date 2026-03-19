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
import distributed_config as dcfg
from distributed_config import is_master, is_worker, is_standalone, get_shard_ids

# Import Shard Manager if using distributed mode
if not is_standalone():
    from shard_manager import DistributedAlphaBot, create_distributed_bot

# Import custom config (assuming configuration file existence)
try:
    from config import TOKEN, APPLICATION_ID
except ImportError:
    # Fallback to .env if config.py is missing or empty
    load_dotenv()
    TOKEN = os.getenv('DISCORD_TOKEN')
    APPLICATION_ID = os.getenv('APPLICATION_ID')

# Get base directory (works for both script and PyInstaller)
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

COGS_DIR = os.path.join(BASE_DIR, 'cogs')
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

# Add cogs to Python path for imports (needed for PyInstaller)
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
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger('discord_bot')

class DiscordLogHandler(logging.Handler):
    """Custom logging handler to send warnings/errors to Discord with batching to avoid 429"""
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.setLevel(logging.WARNING)
        self.queue = []
        self.is_processing = False

    def emit(self, record):
        if not self.bot.is_ready():
            return
            
        msg = self.format(record)
        # Avoid recursion and spammy rate limit warnings themselves
        if any(x in msg.lower() for x in ["failed to send log to channel", "rate limited", "429"]):
            return

        self.queue.append((record.levelno, record.name, msg))
        if not self.is_processing:
            asyncio.create_task(self.process_queue())

    async def process_queue(self):
        self.is_processing = True
        await asyncio.sleep(5) # Wait 5 seconds to collect more logs
        
        try:
            log_cog = self.bot.get_cog('ServerLogger')
            if not log_cog or not self.queue:
                return

            # Batch logs together
            current_batch = self.queue[:]
            self.queue.clear()
            
            # Group by criticality
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
        except:
            pass
        finally:
            self.is_processing = False
            # If new logs arrived during sleep, start again
            if self.queue:
                asyncio.create_task(self.process_queue())

logger = setup_logging()

class AlphaBot(commands.Bot):
    """Original standalone bot - maintained for backward compatibility"""
    def __init__(self):
        intents = discord.Intents.all()
        intents.members = True
        intents.message_content = True
        intents.presences = True
        
        super().__init__(
            command_prefix='!',
            intents=intents,
            application_id=APPLICATION_ID
        )
        
        self.start_time = datetime.now(timezone.utc)
        self.synced_guild_id = 1171254331643789332
        self.mode = 'standalone'

class DistributedAlphaBot(commands.AutoShardedBot):
    """Distributed Bot supporting Sharding + Clustering"""
    def __init__(self, **kwargs):
        intents = discord.Intents.all()
        intents.members = True
        intents.message_content = True
        intents.presences = True
        
        # Get shard configuration
        shard_ids = get_shard_ids()
        total_shards = dcfg.TOTAL_SHARDS
        
        if shard_ids:
            shard_count = total_shards or max(shard_ids) + 1
            print(f"🎲 Cluster {dcfg.CLUSTER_ID}/{dcfg.TOTAL_CLUSTERS} handling shards: {shard_ids}")
            super().__init__(
                command_prefix='!',
                intents=intents,
                application_id=APPLICATION_ID,
                shard_count=shard_count,
                shard_ids=shard_ids,
                **kwargs
            )
        else:
            print(f"🎲 Auto Sharding Mode")
            super().__init__(
                command_prefix='!',
                intents=intents,
                application_id=APPLICATION_ID,
                **kwargs
            )
        
        self.start_time = datetime.now(timezone.utc)
        self.synced_guild_id = 1171254331643789332
        self.mode = dcfg.BOT_MODE
        self.queue = None
        
    async def setup_hook(self):
        """Setup with distributed support"""
        # Initialize queue for master mode
        if is_master() and not is_worker():
            from shared_queue import AsyncSharedQueue
            self.queue = AsyncSharedQueue()
            asyncio.create_task(self._cleanup_loop())
        
        # Load cogs
        await self._load_cogs()
        
        # Setup Discord log handler
        discord_logger = logging.getLogger('discord')
        has_handler = any(isinstance(h, DiscordLogHandler) for h in discord_logger.handlers)
        if not has_handler:
            handler = DiscordLogHandler(self)
            handler.setFormatter(logging.Formatter('%(name)s: %(message)s'))
            discord_logger.addHandler(handler)
    
    async def _load_cogs(self):
        """Load cogs based on mode"""
        ignored = ['conversation.py', 'message_detection.py', '__pycache__']
        
        # Worker mode - only load processing cogs
        if is_worker():
            worker_cogs = ['music', 'stats']
            for cog in worker_cogs:
                try:
                    await self.load_extension(f'cogs.{cog}')
                    logger.info(f"[Worker] Loaded: {cog}")
                except Exception as e:
                    logger.error(f"[Worker] Failed {cog}: {e}")
            return
        
        # Master/Standalone - load all
        for filename in os.listdir(COGS_DIR):
            if filename.endswith('.py') and filename not in ignored:
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    logger.info(f"Loaded: {filename[:-3]}")
                except Exception as e:
                    logger.error(f"Failed {filename}: {e}")
    
    async def _cleanup_loop(self):
        """Cleanup old tasks periodically"""
        while True:
            await asyncio.sleep(3600)  # Every hour
            try:
                from shared_queue import get_queue
                get_queue().cleanup_old_tasks(hours=24)
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
    
    async def on_ready(self):
        logger.info(f"✅ {'Worker' if is_worker() else f'Cluster {dcfg.CLUSTER_ID}'} Ready!")
        logger.info(f"   User: {self.user} | Guilds: {len(self.guilds)}")
        if hasattr(self, 'shard_count'):
            logger.info(f"   Shards: {self.shard_count}")
        
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers"
            )
        )
    
    async def on_shard_ready(self, shard_id):
        logger.info(f"🟢 Shard {shard_id} Ready")
    
    async def on_shard_connect(self, shard_id):
        logger.info(f"🔌 Shard {shard_id} Connected")

    async def on_message(self, message):
        if message.author.bot:
            return
            
        # Optional: Direct message detection response (Thai phrases)
        help_keywords = ["ทำยังไง", "ช่วยด้วย", "คืออะไร"]
        if any(keyword in message.content for keyword in help_keywords):
            help_msg = "🤖 มีอะไรให้ช่วยไหมครับ? ลองใช้ `/คำสั่ง` เพื่อดูคำสั่งทั้งหมดได้เลย"
            await message.channel.send(help_msg)

        # Ensure other commands still work
        await self.process_commands(message)

    async def on_error(self, event, *args, **kwargs):
        """Global error handler for all events"""
        import traceback
        error = traceback.format_exc()
        logger.error(f"Error in {event}: {error}")
        
        # Send to log channel
        log_cog = self.get_cog('ServerLogger')
        if log_cog:
            embed = discord.Embed(title="⚠️ System Error", color=discord.Color.red(), timestamp=datetime.now())
            embed.description = f"**Event:** `{event}`\n```py\n{error[:1800]}\n```"
            await log_cog.send_log(embed)

    async def close(self):
        logger.info("Bot is shutting down...")
        await super().close()

def run_bot():
    if not TOKEN:
        logger.error("Error: TOKEN is not set in config.py or .env file.")
        sys.exit(1)

    # Choose bot class based on mode
    if is_standalone():
        logger.info("🤖 Starting Standalone Mode")
        bot = AlphaBot()
    else:
        logger.info(f"🤖 Starting {dcfg.BOT_MODE.upper()} Mode")
        bot = DistributedAlphaBot()
    
    async def main():
        async with bot:
            try:
                await bot.start(TOKEN)
            except KeyboardInterrupt:
                await bot.close()
            except Exception as e:
                logger.error(f"Error during bot execution: {e}")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    run_bot()
