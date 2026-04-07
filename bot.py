import discord
from discord.ext import commands
from discord import app_commands
import os
import logging
import asyncio
import json
import sys
import re
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
DATA_DIR = os.path.join(BASE_DIR, 'data')
CONSOLE_CONTROL_FILE = os.path.join(DATA_DIR, 'console_control.json')

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

def load_console_control() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CONSOLE_CONTROL_FILE):
        return {"disabled_slash_commands": []}
    try:
        with open(CONSOLE_CONTROL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "disabled_slash_commands" not in data:
                data["disabled_slash_commands"] = []
            return data
    except Exception:
        return {"disabled_slash_commands": []}

def save_console_control(data: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONSOLE_CONTROL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def resolve_primary_guild_id() -> str | None:
    """Resolve guild ID from env; fallback to data filename prefix."""
    guild_id = os.getenv('DISCORD_GUILD_ID')
    if guild_id and guild_id.strip().isdigit():
        return guild_id.strip()

    data_dir = os.path.join(BASE_DIR, "data")
    if not os.path.isdir(data_dir):
        return None

    for name in os.listdir(data_dir):
        m = re.match(r"^(\d{15,21})_", name)
        if m:
            return m.group(1)
    return None

def resolve_known_guild_ids() -> list[int]:
    guild_ids: set[int] = set()

    env_gid = os.getenv("DISCORD_GUILD_ID", "").strip()
    if env_gid.isdigit():
        guild_ids.add(int(env_gid))

    env_multi = os.getenv("DISCORD_GUILD_IDS", "")
    if env_multi:
        for token in re.split(r"[\s,;|]+", env_multi):
            token = token.strip()
            if token.isdigit():
                guild_ids.add(int(token))

    if os.path.isdir(DATA_DIR):
        for name in os.listdir(DATA_DIR):
            m = re.match(r"^(\d{15,21})_", name)
            if m:
                guild_ids.add(int(m.group(1)))

        for filename in ("server_link_config.json", "ai_guild_config.json"):
            path = os.path.join(DATA_DIR, filename)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as file:
                    payload = json.load(file)
                if isinstance(payload, dict):
                    for key in payload.keys():
                        key = str(key).strip()
                        if key.isdigit():
                            guild_ids.add(int(key))
            except Exception:
                pass

    return sorted(guild_ids)

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
    def _init_runtime_controls(self):
        cfg = load_console_control()
        self.disabled_slash_commands: set[str] = {
            str(x).strip().lower()
            for x in cfg.get("disabled_slash_commands", [])
            if str(x).strip()
        }
        self._console_task = None
        self._restart_requested = False
        self._stop_requested = False

    async def _runtime_app_command_check(self, interaction: discord.Interaction) -> bool:
        cmd_name = None
        if interaction.command:
            cmd_name = interaction.command.name
        elif interaction.data and isinstance(interaction.data, dict):
            cmd_name = interaction.data.get("name")

        if not cmd_name:
            return True

        normalized = str(cmd_name).strip().lower()
        if normalized in self.disabled_slash_commands:
            msg = f"⛔ คำสั่ง `/{cmd_name}` ถูกปิดใช้งานชั่วคราวโดยแอดมิน (Console Control)"
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass
            return False
        return True

    def _save_disabled_commands(self):
        save_console_control({
            "disabled_slash_commands": sorted(self.disabled_slash_commands)
        })

    async def _console_control_loop(self):
        if not (sys.stdin and sys.stdin.isatty()):
            logger.info("Console control disabled: stdin is not interactive")
            return

        logger.info(
            "🧩 Console control ready | commands: help, status, disable <name>, enable <name>, "
            "list, sync, guildsync, restart, stop"
        )
        while not self.is_closed():
            try:
                raw = await asyncio.to_thread(input, "[console] > ")
            except EOFError:
                logger.warning("Console input closed (EOF), console control loop stopped")
                return
            except Exception as e:
                logger.warning(f"Console input error: {e}")
                await asyncio.sleep(1.0)
                continue

            line = (raw or "").strip()
            if not line:
                continue

            parts = line.split()
            action = parts[0].lower()
            arg = " ".join(parts[1:]).strip() if len(parts) > 1 else ""

            if action in {"help", "h", "?"}:
                logger.info(
                    "Console commands:\n"
                    "  help                - show this help\n"
                    "  status              - show bot runtime status\n"
                    "  disable <cmd>       - disable slash command by name (without /)\n"
                    "  enable <cmd>        - re-enable slash command\n"
                    "  list                - list disabled slash commands\n"
                    "  sync                - sync global commands\n"
                    "  guildsync           - sync guild commands (if guild id resolved)\n"
                    "  restart             - graceful restart process loop\n"
                    "  stop                - graceful shutdown"
                )
            elif action == "status":
                logger.info(
                    f"Runtime status | ready={self.is_ready()} guilds={len(self.guilds)} "
                    f"disabled={len(self.disabled_slash_commands)} stop={self._stop_requested} restart={self._restart_requested}"
                )
            elif action == "disable":
                if not arg:
                    logger.warning("Usage: disable <command_name>")
                    continue
                cmd = arg.replace("/", "").strip().lower()
                self.disabled_slash_commands.add(cmd)
                self._save_disabled_commands()
                logger.info(f"⛔ Disabled command: /{cmd}")
            elif action == "enable":
                if not arg:
                    logger.warning("Usage: enable <command_name>")
                    continue
                cmd = arg.replace("/", "").strip().lower()
                if cmd in self.disabled_slash_commands:
                    self.disabled_slash_commands.remove(cmd)
                    self._save_disabled_commands()
                    logger.info(f"✅ Enabled command: /{cmd}")
                else:
                    logger.info(f"ℹ️ Command /{cmd} is not disabled")
            elif action == "list":
                if not self.disabled_slash_commands:
                    logger.info("✅ No disabled slash commands")
                else:
                    logger.info("Disabled commands: " + ", ".join(f"/{c}" for c in sorted(self.disabled_slash_commands)))
            elif action == "sync":
                try:
                    cmds = await self.tree.sync()
                    logger.info(f"✅ Global sync done ({len(cmds)} commands)")
                except Exception as e:
                    logger.error(f"Global sync failed: {e}")
            elif action == "guildsync":
                gid = resolve_primary_guild_id()
                if not gid:
                    logger.warning("Cannot guildsync: no DISCORD_GUILD_ID resolved")
                    continue
                try:
                    cmds = await self.tree.sync(guild=discord.Object(id=int(gid)))
                    logger.info(f"✅ Guild sync done ({len(cmds)} commands) for {gid}")
                except Exception as e:
                    logger.error(f"Guild sync failed: {e}")
            elif action == "restart":
                self._restart_requested = True
                logger.warning("♻️ Restart requested from console...")
                await self.close()
                return
            elif action in {"stop", "shutdown", "quit", "exit"}:
                self._stop_requested = True
                logger.warning("🛑 Stop requested from console...")
                await self.close()
                return
            else:
                logger.warning(f"Unknown console command: {action} (type 'help')")

    async def setup_hook(self):
        self._init_runtime_controls()
        # รองรับ discord.py หลายเวอร์ชัน:
        # - บางเวอร์ชันมี add_check
        # - บางเวอร์ชันต้องใช้ interaction_check
        if hasattr(self.tree, "add_check"):
            self.tree.add_check(self._runtime_app_command_check)
        else:
            setattr(self.tree, "interaction_check", self._runtime_app_command_check)

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
            guild_id = resolve_primary_guild_id()
            commands_list = []
            known_guild_ids = resolve_known_guild_ids()
            if known_guild_ids:
                # 1) sync global ตามปกติ
                global_cmds = await self.tree.sync()
                logger.info(f"Global tree synced ({len(global_cmds)} commands)")

                # 2) sync guild-scoped commands ทุก guild ที่รู้จัก (แก้เคสคำสั่งบางเซิร์ฟเวอร์ไม่ครบ)
                merged = {}
                for c in global_cmds:
                    merged[c.name] = c

                copy_global_to_guild = os.getenv("COPY_GLOBAL_TO_KNOWN_GUILDS", "1").strip().lower() in {"1", "true", "yes", "on"}
                for gid in known_guild_ids:
                    try:
                        guild_obj = discord.Object(id=gid)
                        if copy_global_to_guild:
                            self.tree.copy_global_to(guild=guild_obj)
                        guild_cmds = await self.tree.sync(guild=guild_obj)
                        guild = self.get_guild(gid)
                        if guild:
                            guild_name = guild.name
                        else:
                            try:
                                fetched = await self.fetch_guild(gid)
                                guild_name = fetched.name
                            except Exception:
                                guild_name = "Unknown Guild"
                        logger.info(f"Guild tree synced to {guild_name} ({gid}) ({len(guild_cmds)} guild commands)")
                        for c in guild_cmds:
                            merged[c.name] = c
                    except discord.Forbidden:
                        logger.warning(f"⚠️ Missing access to sync tree for guild {gid}")
                    except Exception as sync_error:
                        logger.warning(f"⚠️ Failed syncing guild {gid}: {sync_error}")

                commands_list = list(merged.values())
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

        if os.getenv("ENABLE_CONSOLE_CONTROL", "1").strip() in {"1", "true", "yes", "on"}:
            if self._console_task is None or self._console_task.done():
                self._console_task = asyncio.create_task(self._console_control_loop())

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
        if message.author.bot:
            return

        try:
            display_name = message.author.display_name if isinstance(message.author, discord.Member) else message.author.name
            username = message.author.name
            uid = message.author.id
            guild_name = message.guild.name if message.guild else "DM"
            gid = message.guild.id if message.guild else "DM"

            parts = []
            if message.content and message.content.strip():
                content = message.content.strip().replace("\n", " ")
                if len(content) > 350:
                    content = content[:347] + "..."
                parts.append(content)

            if message.attachments:
                image_ext = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
                image_links = []
                file_links = []
                for attachment in message.attachments:
                    filename_lower = (attachment.filename or "").lower()
                    content_type = (attachment.content_type or "").lower()
                    is_image = filename_lower.endswith(image_ext) or content_type.startswith("image/")
                    if is_image:
                        image_links.append(attachment.url)
                    else:
                        file_links.append(attachment.url)
                if image_links:
                    parts.append("ส่งรูป: " + " | ".join(image_links[:3]))
                if file_links:
                    parts.append("ส่งไฟล์: " + " | ".join(file_links[:3]))

            if message.stickers:
                sticker_names = ", ".join(s.name for s in message.stickers[:3])
                parts.append(f"ส่งสติ๊กเกอร์: {sticker_names}")

            if message.embeds:
                parts.append(f"ส่ง Embed: {len(message.embeds)} รายการ")

            if not parts:
                parts.append("[ข้อความชนิดพิเศษ/ไม่มีข้อความตัวอักษร]")

            msg_text = " | ".join(parts)
            logger.info(f"{username} ({display_name}) {uid} | {guild_name} {gid} : {msg_text}")
        except Exception as log_err:
            logger.warning(f"message-log format failed: {log_err}")

        await self.process_commands(message)

    async def on_disconnect(self):
        logger.warning("🔌 Discord gateway disconnected. Waiting for reconnect...")

    async def on_resumed(self):
        logger.info("♻️ Discord gateway session resumed successfully")

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

    async def run_with_watchdog():
        attempt = 0
        base_delay = 3
        max_delay = 120

        while True:
            attempt += 1
            bot = None
            try:
                if is_standalone():
                    logger.info("🤖 Starting Standalone Mode")
                    bot = AlphaBot()
                else:
                    logger.info(f"🤖 Starting {dcfg.BOT_MODE.upper()} Mode")
                    bot = DistributedAlphaBot()

                async with bot:
                    await bot.start(TOKEN)

                # ปกติ start() จะไม่หลุดออกมาถ้าไม่มีเหตุปิดบอท
                if getattr(bot, "_stop_requested", False):
                    logger.info("🛑 Bot stop completed")
                    return
                if getattr(bot, "_restart_requested", False):
                    logger.info("♻️ Bot restart requested, restarting now...")
                    attempt = 0
                    await asyncio.sleep(1.0)
                    continue
                logger.warning("⚠️ bot.start() exited unexpectedly. Restarting...")
                raise RuntimeError("bot.start exited unexpectedly")

            except KeyboardInterrupt:
                logger.info("🛑 Shutdown requested by user")
                return
            except (discord.GatewayNotFound, discord.ConnectionClosed, OSError, ConnectionResetError, asyncio.TimeoutError) as e:
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                logger.warning(f"🌐 Network/Gateway error: {e}. Reconnecting in {delay}s (attempt {attempt})")
                await asyncio.sleep(delay)
            except Exception as e:
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                logger.error(f"💥 Fatal runtime error: {e}. Restarting in {delay}s (attempt {attempt})")
                await asyncio.sleep(delay)
            finally:
                if bot and not bot.is_closed():
                    try:
                        await bot.close()
                    except Exception:
                        pass

    try:
        asyncio.run(run_with_watchdog())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    run_bot()
