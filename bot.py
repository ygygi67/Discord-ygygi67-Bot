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
from core.shared_queue import Task

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
NETWORK_ERROR_FILE = os.path.join(DATA_DIR, 'network_error.flag')
NETWORK_STATUS_FILE = os.path.join(DATA_DIR, 'network_status.json')
ALIVE_FLAG = os.path.join(DATA_DIR, 'alive.flag')

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
        if not self.bot.is_ready() or self.bot.is_closed() or getattr(self.bot, '_is_shutting_down', False):
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
            # Normalize to lower case, striped
            str(x).strip().lower()
            for x in cfg.get("disabled_slash_commands", [])
            if str(x).strip()
        }
        self._console_task = None
        self._restart_requested = False
        self._graceful_restart_requested = False
        self._stop_requested = False
        self._is_shutting_down = False
        self.active_processes = set()

    async def _send_offline_status(self):
        """Helper to send the 'ปิดบอทแล้วน่าา' message to status channel"""
        try:
            status_cog = self.get_cog('Status')
            if status_cog and hasattr(status_cog, 'status_channel_id') and status_cog.status_channel_id:
                channel = self.get_channel(status_cog.status_channel_id) or await self.fetch_channel(status_cog.status_channel_id)
                if channel:
                    # Attempt to purge old status messages
                    try: await channel.purge(limit=5)
                    except: pass
                    
                    embed = discord.Embed(
                        title="🔴 ปิดบอทแล้วน่าา | System Closed",
                        description="บอทถูกปิดการใช้งานตามคำสั่งเรียบร้อยแล้วครับ",
                        color=0xe74c3c,
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.set_footer(text="แล้วเจอกันใหม่นะ!")
                    await channel.send(embed=embed)
                    logger.info("Sent offline status to status channel")
        except Exception as e:
            logger.warning(f"Could not send offline status: {e}")

    async def _disconnect_voice_clients(self):
        """Helper to disconnect all voice clients in parallel with a timeout"""
        if not self.voice_clients:
            return

        logger.info(f"Disconnecting {len(self.voice_clients)} voice client(s)...")
        
        async def safe_disconnect(vc):
            try:
                # Use wait_for to prevent hanging forever on a single VC
                # On Windows, force=True is important
                await asyncio.wait_for(vc.disconnect(force=True), timeout=4.0)
            except Exception as e:
                logger.warning(f"Failed to disconnect VC in {vc.guild.name}: {e}")

        # Disconnect all in parallel
        tasks = [safe_disconnect(vc) for vc in list(self.voice_clients)]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Voice clients disconnected.")

    async def _cancel_all_tasks(self):
        """Helper to cancel all background tasks started by the bot"""
        logger.info("Cancelling all background tasks...")
        
        # 1. Unload all cogs first (this triggers cog_unload)
        cogs_to_remove = list(self.cogs.keys())
        for cog_name in cogs_to_remove:
            try:
                logger.info(f"Unloading cog: {cog_name}...")
                await asyncio.wait_for(self.remove_cog(cog_name), timeout=10.0)
            except Exception as e:
                logger.warning(f"Error removing cog {cog_name}: {e}")

        # 2. Kill tracked background processes (ToffeeShare, etc.)
        if hasattr(self, 'active_processes') and self.active_processes:
            logger.info(f"Cleaning up {len(self.active_processes)} active processes...")
            for proc in list(self.active_processes):
                try:
                    proc.terminate()
                    await asyncio.sleep(0.1)
                    if hasattr(proc, 'kill'): proc.kill()
                except: pass
            self.active_processes.clear()

        # 3. Cancel remaining tasks (avoid cancelling the watchdog/supervisor task)
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not tasks: return

        def _is_watchdog_task(t: asyncio.Task) -> bool:
            try:
                coro = t.get_coro()
                name = getattr(coro, "__name__", "") or ""
                qualname = getattr(coro, "__qualname__", "") or ""
                return ("run_with_watchdog" in name) or ("run_with_watchdog" in qualname)
            except Exception:
                return False

        for task in tasks:
            if _is_watchdog_task(task):
                continue
            task.cancel()
            
        try:
            # Give tasks a moment to handle cancellation
            await asyncio.wait(tasks, timeout=2.0)
        except: pass

    async def _runtime_app_command_check(self, interaction: discord.Interaction) -> bool:
        cmd_name = None
        if interaction.command:
            cmd_name = interaction.command.name
        elif interaction.data and isinstance(interaction.data, dict):
            cmd_name = interaction.data.get("name")

        if not cmd_name:
            return True

        # ระบบป้องกันคำสั่งใหม่ระหว่างห้ามรีสตาร์ทแบบปลอดภัย
        if self._graceful_restart_requested:
            msg = "⚠️ **บอทกำลังเตรียมรีสตาร์ทแบบปลอดภัย**\nขณะนี้บอทหยุดรับคำสั่งใหม่เพื่อรอให้งานที่ค้างอยู่ประมวลผลเสร็จสิ้น โปรดลองใหม่ในอีกสักครู่ครับ"
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception: pass
            return False

        normalized = str(cmd_name).strip().lower()
        try:
            guild_id = getattr(interaction, "guild_id", None)
            channel_id = getattr(interaction, "channel_id", None)
            user_id = getattr(getattr(interaction, "user", None), "id", None)
            logger.info(
                f"[APP_CMD] start /{cmd_name} user={user_id} guild={guild_id} channel={channel_id}"
            )
        except Exception:
            pass
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

    async def on_app_command_completion(self, interaction: discord.Interaction, command):
        try:
            name = getattr(command, "name", None) or getattr(getattr(interaction, "command", None), "name", "unknown")
            logger.info(f"[APP_CMD] done /{name} user={getattr(interaction.user, 'id', None)} guild={interaction.guild_id}")
        except Exception:
            pass

    async def on_app_command_error(self, interaction: discord.Interaction, error):
        try:
            cmd = getattr(getattr(interaction, "command", None), "name", "unknown")
            logger.error(f"[APP_CMD] error /{cmd}: {error}")
        except Exception:
            pass

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
            aliases = {
                "h": "help", "?": "help",
                "st": "status",
                "d": "disable", "dis": "disable",
                "e": "enable", "en": "enable",
                "l": "list", "ls": "list",
                "sy": "sync",
                "gs": "guildsync",
                "r": "restart", "rs": "restart",
                "sr": "saferestart",
                "w": "busy",
                "s": "stop", "q": "stop", "x": "stop",
            }
            action = aliases.get(action, action)

            if action in {"help", "h", "?"}:
                logger.info(
                    "Console commands:\n"
                    "  help                - show this help\n"
                    "  status              - show bot runtime status\n"
                    "  busy                - show why safe-restart is waiting\n"
                    "  disable <cmd>       - disable slash command by name (without /)\n"
                    "  enable <cmd>        - re-enable slash command\n"
                    "  list                - list disabled slash commands\n"
                    "  sync                - sync global commands\n"
                    "  guildsync           - sync guild commands (if guild id resolved)\n"
                    "  restart             - graceful restart process loop\n"
                    "  saferestart (sr)    - wait for tasks to finish then restart\n"
                    "  stop                - graceful shutdown"
                )
            elif action == "status":
                logger.info(
                    f"Runtime status | ready={self.is_ready()} guilds={len(self.guilds)} "
                    f"disabled={len(self.disabled_slash_commands)} stop={self._stop_requested} restart={self._restart_requested} sr_pending={self._graceful_restart_requested}"
                )
            elif action in {"busy", "why"}:
                try:
                    reasons = await self._get_busy_reasons()
                    if reasons:
                        logger.info("Busy reasons:\n  - " + "\n  - ".join(reasons))
                    else:
                        logger.info("Busy reasons: (none) - bot looks idle")
                except Exception as e:
                    logger.warning(f"Failed to compute busy reasons: {e}")
            elif action == "disable":
                if not arg:
                    logger.warning("Usage: disable <command_name> | shorthand: d <command_name> (เช่น: d โหลดคลิป)")
                    continue
                cmd = arg.replace("/", "").strip().lower()
                self.disabled_slash_commands.add(cmd)
                self._save_disabled_commands()
                logger.info(f"⛔ Disabled command: /{cmd}")
            elif action == "enable":
                if not arg:
                    logger.warning("Usage: enable <command_name> | shorthand: e <command_name> (เช่น: e โหลดคลิป)")
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
            elif action == "saferestart":
                self._graceful_restart_requested = True
                logger.warning("🛡️ Safe Restart requested. Waiting for tasks to finish...")
                asyncio.create_task(self._graceful_restart_monitor())
            elif action in {"stop", "shutdown", "quit", "exit"}:
                self._stop_requested = True
                logger.warning("🛑 Stop requested from console...")
                await self.close()
                return
            else:
                logger.warning(f"Unknown console command: {action} (type 'help')")

    async def _get_busy_reasons(self) -> list[str]:
        """Return human-readable reasons for why safe-restart is waiting."""
        reasons: list[str] = []

        # 1) Shared queue (vocal separation etc.)
        if hasattr(self, 'queue'):
            try:
                pending = await self.queue.get_pending_count()
                if pending > 0:
                    reasons.append(f"Shared queue pending: {pending}")

                    # Include a small sample of pending tasks to show what's blocking restart
                    try:
                        sample = await self.queue.list_tasks(status='pending', limit=3)
                        for t in sample:
                            reasons.append(f"Pending task: id={t.id} type={t.type} created_at={t.created_at}")
                    except Exception:
                        pass

                vsep_active = await self.queue.get_active_count('vocal_separation')
                if vsep_active > 0:
                    reasons.append(f"Shared queue active vocal_separation: {vsep_active}")
            except Exception:
                pass

        # 2) VocalSeparator processes
        try:
            vsep = self.get_cog('VocalSeparator')
            if vsep and hasattr(vsep, 'active_processes'):
                procs = list(getattr(vsep, 'active_processes') or [])
                if len(procs) > 0:
                    reasons.append(f"VocalSeparator active processes: {len(procs)}")
        except Exception:
            pass

        # 3) TTS queue / playback
        try:
            tts = self.get_cog('TTSCommand')
            if tts and hasattr(tts, 'tts_queue'):
                q = getattr(tts, 'tts_queue') or {}
                for guild_id, guild_q in q.items():
                    try:
                        is_playing = bool(getattr(tts, 'is_playing', {}).get(guild_id))
                        if is_playing:
                            reasons.append(f"TTS playing in guild {guild_id}")
                        if hasattr(guild_q, "qsize") and guild_q.qsize() > 0:
                            reasons.append(f"TTS queue in guild {guild_id}: {guild_q.qsize()} pending")
                        elif hasattr(guild_q, "empty") and not guild_q.empty():
                            reasons.append(f"TTS queue in guild {guild_id}: not empty")
                    except Exception:
                        continue
        except Exception:
            pass

        # 4) Music voice clients
        try:
            if self.get_cog('Music'):
                for vc in list(self.voice_clients):
                    try:
                        if vc.is_playing() or vc.is_paused():
                            reasons.append(f"Music active in guild {getattr(vc.guild, 'id', 'unknown')}")
                    except Exception:
                        continue
        except Exception:
            pass

        # 5) YouTube Spy scanning
        try:
            yt_spy = self.get_cog('YoutubeSpyCog')
            if yt_spy and getattr(yt_spy, 'is_scanning', False):
                reasons.append("YoutubeSpy scanning in progress")
        except Exception:
            pass

        return reasons

    async def _is_bot_busy(self) -> bool:
        """ตรวจสอบว่าบอทมีงานที่กำลังรันค้างอยู่หรือไม่"""
        try:
            return len(await self._get_busy_reasons()) > 0
        except Exception:
            return False

    async def _graceful_restart_monitor(self):
        """ลูปสำหรับเฝ้ารอจนงานเสร็จแล้วค่อยรีสตาร์ท"""
        check_count = 0
        while self._graceful_restart_requested:
            busy = await self._is_bot_busy()
            if not busy:
                logger.warning("✅ All tasks finished. Performing Safe Restart now...")
                self._restart_requested = True
                await self.close()
                break
            
            if check_count % 6 == 0: # ทุกๆ 1 นาที
                try:
                    reasons = await self._get_busy_reasons()
                    if reasons:
                        logger.info("⏳ Safe Restart: Waiting for active tasks to complete...\n  - " + "\n  - ".join(reasons))
                    else:
                        logger.info("⏳ Safe Restart: Waiting for active tasks to complete...")
                except Exception:
                    logger.info("⏳ Safe Restart: Waiting for active tasks to complete...")
            
            check_count += 1
            await asyncio.sleep(10)

    async def setup_hook(self):
        self._init_runtime_controls()
        # รองรับ discord.py หลายเวอร์ชัน:
        if hasattr(self.tree, "add_check"):
            self.tree.add_check(self._runtime_app_command_check)
        else:
            setattr(self.tree, "interaction_check", self._runtime_app_command_check)

        # Initialize queue for master or standalone mode (any mode that isn't a dedicated worker)
        if not is_worker():
            from core.shared_queue import AsyncSharedQueue
            self.queue = AsyncSharedQueue()
            await self.queue.reset_interrupted_tasks() # กู้คืน Task ที่ค้างตอนรีสตาร์ท
            asyncio.create_task(self._cleanup_loop())
            asyncio.create_task(self._task_runner_loop()) # เริ่มระบบประมวลผล Task อัตโนมัติ
        
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
                # 1) sync global
                enable_global_sync = os.getenv("ENABLE_GLOBAL_SYNC", "0").strip().lower() in {"1", "true", "yes", "on"}
                global_cmds = []
                if enable_global_sync:
                    global_cmds = await self.tree.sync()
                    logger.info(f"Global tree synced ({len(global_cmds)} commands)")
                else:
                    global_cmds = list(self.tree.get_commands(type=discord.AppCommandType.chat_input))
                    logger.info(f"Global sync skipped (ENABLE_GLOBAL_SYNC=0) | local commands={len(global_cmds)}")

                # 2) sync guild-scoped commands ทุก guild ที่รู้จัก
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

            if not commands_list:
                local_cmds = self.tree.get_commands(type=discord.AppCommandType.chat_input)
                if local_cmds:
                    commands_list = list(local_cmds)
                    logger.warning(f"⚠️ Sync API คืนค่าว่าง แต่พบคำสั่ง local {len(commands_list)} รายการ")
            
            if commands_list:
                cmd_names = [f"/{cmd.name}" for cmd in commands_list]
                logger.info(f"✅ โหลดสำเร็จ {len(commands_list)} คำสั่ง:")
                chunk_size = 8
                for i in range(0, len(cmd_names), chunk_size):
                    logger.info(f"   > {', '.join(cmd_names[i:i + chunk_size])}")

                synced_names = {cmd.name for cmd in commands_list}
                expected_core = {"คำสั่ง", "สถิติ", "เสียง", "ระบบ", "ติดตาม", "เชิญบอทเต็ม", "โหลดคลิป"}
                missing_expected = sorted(expected_core - synced_names)
                if missing_expected:
                    logger.warning(f"⚠️ คำสั่งบางส่วนหายจากการซิงค์: {', '.join('/' + n for n in missing_expected)}")
            else:
                logger.warning("⚠️ ไม่มีคำสั่งถูกโหลดขึ้นมาเลย")
                
        except discord.Forbidden:
            logger.warning(f"⚠️ Missing access to sync tree. Falling back to global sync...")
            commands_list = await self.tree.sync()
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
            # ข้ามโฟลเดอร์ที่ไม่ต้องการ (เช่น venv, git, cache) ในการท่องไดเรกทอรีถัดไป
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['venv', '.venv', 'node_modules', '__pycache__']]
            
            # บล็อกชั้นที่ 2: ตรวจสอบ root path ปัจจุบันว่าอยู่ในโฟลเดอร์ต้องห้ามหรือไม่ (เผื่อกรณีระบบไฟล์แปลกๆ)
            root_parts = root.replace(os.sep, '/').split('/')
            if any(p.startswith('.') or p in ['venv', '.venv', 'node_modules', '__pycache__'] for p in root_parts):
                continue

            for filename in files:
                if filename.endswith('.py') and filename not in ignored:
                    rel_path = os.path.relpath(os.path.join(root, filename), BASE_DIR)
                    module_path = rel_path.replace(os.sep, '.')[:-3]
                    cog_name = filename[:-3]
                    
                    if target_cogs is not None and cog_name not in target_cogs: continue
                    try:
                        # ตรวจสอบเบื้องต้นว่าไฟล์มีฟังก์ชัน setup หรือไม่ (เพื่อป้องกัน Error: has no 'setup' function)
                        has_setup = False
                        file_path = os.path.join(root, filename)
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                                if 'async def setup' in content or 'def setup' in content:
                                    has_setup = True
                        except: pass
                        
                        if not has_setup:
                            continue

                        await self.load_extension(module_path)
                        logger.info(f"{'[Worker] ' if is_worker_mode else ''}Loaded: {module_path}")
                        loaded_count += 1
                    except Exception as e:
                        logger.error(f"❌ Failed to load {module_path}: {e}")
        
        logger.info(f"✅ Cog loading complete. Total loaded: {loaded_count}")

    async def _task_runner_loop(self):
        """ลูปสำหรับประมวลผล Task จากคิว (เช็คทุก 1 วินาทีและรันแบบ Parallel)"""
        if not hasattr(self, 'queue'): return
        
        await asyncio.sleep(3)
        logger.info("⚙️ Persistent Task Runner started (Parallel Mode).")
        
        while not self.is_closed():
            try:
                # ดึงงานประเภทที่บอทจัดการได้
                task = await self.queue.get_next_task(['vocal_separation'])
                if not task:
                    await asyncio.sleep(1)
                    continue

                # รันงานแบบ Parallel (ไม่บล็อก loop)
                asyncio.create_task(self._handle_task_safely(task))
                # พักแป๊บนึงก่อนดึงงานถัดไปเพื่อไม่ให้ดึงรัวเกินไป
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"⚠️ Task Runner Loop error: {e}")
                await asyncio.sleep(5)

    async def _handle_task_safely(self, task: Task):
        """ฟังก์ชันช่วยรันงานและจัดการผลลัพธ์"""
        logger.info(f"🏃 Processing Task: {task.id} ({task.type})")
        try:
            if task.type == 'vocal_separation':
                cog = self.get_cog('VocalSeparator')
                if cog and hasattr(cog, 'process_queue_task'):
                    await cog.process_queue_task(task)
                else:
                    await self.queue.complete_task(task.id, error="No handler found")
        except Exception as e:
            logger.error(f"❌ Critical error in task {task.id}: {e}")
            await self.queue.complete_task(task.id, error=str(e))

    async def _notify_network_recovery(self):
        """แจ้งเตือนเมื่อเน็ตกลับมา หลังจากที่หลุดไปก่อนหน้า"""
        try:
            # 0. บันทึกสถานะว่ากำลังออนไลน์
            try:
                status_data = {}
                if os.path.exists(NETWORK_STATUS_FILE):
                    with open(NETWORK_STATUS_FILE, 'r', encoding='utf-8') as f:
                        status_data = json.load(f)
                status_data["status"] = "online"
                status_data["last_reconnect"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                status_data["recovery_pending"] = True
                with open(NETWORK_STATUS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(status_data, f, indent=4)
            except Exception: pass

            await asyncio.sleep(8)
            status_channel_id = None
            channels_path = os.path.join(DATA_DIR, 'channels.json')
            if os.path.exists(channels_path):
                try:
                    with open(channels_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        status_channel_id = data.get('status_channel')
                except Exception: pass
            
            msg = "🔄 **Network Recovery Report**\nระบบทำการเชื่อมต่อเครือข่ายใหม่สำเร็จแล้ว ขณะนี้บอทกลับมาออนไลน์ตามปกติ รายละเอียดความเสถียรถูกบันทึกลงใน Dashboard เรียบร้อยครับ"
            if status_channel_id:
                try:
                    channel = self.get_channel(status_channel_id) or await self.fetch_channel(status_channel_id)
                    if channel:
                        await channel.send(msg)
                        status_cog = self.get_cog('Status')
                        if status_cog and hasattr(status_cog, 'update_status_task'):
                            await asyncio.sleep(2)
                            asyncio.create_task(status_cog.update_status_task())
                except Exception: pass

            # ลบไฟล์ Flag
            if os.path.exists(NETWORK_ERROR_FILE):
                os.remove(NETWORK_ERROR_FILE)
                
        except Exception as e:
            logger.error(f"Error in _notify_network_recovery: {e}")

    async def _handle_unexpected_restart(self):
        """จัดการเมื่อตรวจพบว่าบอทเปิดใหม่หลังจากการปิดตัวแบบไม่ปกติ"""
        try:
            # บันทึกลงสถานะว่าเกิดเหตุการณ์ไม่ปกติ
            try:
                status_data = {}
                if os.path.exists(NETWORK_STATUS_FILE):
                    with open(NETWORK_STATUS_FILE, 'r', encoding='utf-8') as f:
                        status_data = json.load(f)
                status_data["unexpected_event"] = True
                status_data["last_event_time"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                with open(NETWORK_STATUS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(status_data, f, indent=4)
            except Exception: pass

            # แจ้งเตือนเจ้าของบอทแบบเรียบง่าย
            try:
                app_info = await self.application_info()
                owner = app_info.owner
                
                embed = discord.Embed(
                    title="⚠️ ตรวจพบการเริ่มต้นใหม่หลังระบบขัดข้อง",
                    description="บอทเพิ่งเปิดใช้งานหลังจากมีการปิดตัวลงอย่างไม่ปกติ (เช่น คอมดับ หรือโปรเซสถูกสั่งปิดกะทันหัน) ระบบได้กลับมาทำงานตามปกติแล้วครับ",
                    color=discord.Color.red(),
                    timestamp=datetime.now()
                )
                embed.set_footer(text="สถานะถูกบันทึกลงใน Dashboard เรียบร้อย")
                await owner.send(embed=embed)
                logger.info(f"Sent security restart report to owner {owner.name}")
            except Exception as e:
                logger.error(f"Failed to send security report: {e}")
                
        except Exception as e:
            logger.error(f"Error in _handle_unexpected_restart: {e}")


    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(3600)
            try:
                from core.shared_queue import get_queue
                get_queue().cleanup_old_tasks(hours=24)
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

    async def on_ready(self):
        if self._is_shutting_down:
            return

        logger.info(f"✅ {self.mode.capitalize()} Ready! User: {self.user}")
        
        # 1. ตรวจสอบสถานะการปิดตัวล่าสุด
        # ถ้ามี ALIVE_FLAG ค้างอยู่ แสดงว่าไม่ได้ปิดแบบปกติ (Unexpected Shutdown)
        if os.path.exists(ALIVE_FLAG):
            asyncio.create_task(self._handle_unexpected_restart())
        
        # สร้าง ALIVE_FLAG ใหม่เพื่อบอกว่าตอนนี้บอทกำลังรันอยู่
        try:
            with open(ALIVE_FLAG, 'w', encoding='utf-8') as f:
                f.write(f"PID: {os.getpid()} | START: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception: pass
        
        if self._is_shutting_down: return

        # 2. ตรวจสอบการกู้คืนจากเน็ตหลุด
        if os.path.exists(NETWORK_ERROR_FILE):
             asyncio.create_task(self._notify_network_recovery())
             
             # คืนค่าเสียง
             music_cog = self.get_cog('Music')
             if music_cog and hasattr(music_cog, 'auto_resume_on_load'):
                 asyncio.create_task(music_cog.auto_resume_on_load())

        activity_name = f"{len(self.guilds)} servers"
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=activity_name))


        # กวาด Sync คำสั่งไปยังกิลด์ทั้งหมดที่บอทอาศัยอยู่ แต่ยังไม่เคยถูก Sync ใน setup_hook
        try:
            copy_global = os.getenv("COPY_GLOBAL_TO_KNOWN_GUILDS", "1").strip().lower() in {"1", "true", "yes", "on"}
            if copy_global:
                known = set(resolve_known_guild_ids())
                for g in self.guilds:
                    if g.id not in known:
                        self.tree.copy_global_to(guild=g)
                        cmds = await self.tree.sync(guild=g)
                        logger.info(f"Guild tree dynamically synced to missed guild {g.name} ({g.id}) ({len(cmds)} commands)")
        except Exception as e:
            logger.error(f"Error dynamically syncing missed guilds: {e}")

        voice_id = os.getenv('AUTO_JOIN_VOICE_ID')
        if voice_id:
            try:
                await asyncio.sleep(2)
                channel = self.get_channel(int(voice_id)) or await self.fetch_channel(int(voice_id))
                if channel and isinstance(channel, discord.VoiceChannel):
                    if not channel.guild.voice_client:
                        await channel.connect()
                        logger.info(f"🔊 Auto-joined voice channel: {channel.name} ({voice_id})")
            except Exception as e:
                logger.error(f"Failed to auto-join voice channel {voice_id}: {e}")

    async def on_guild_join(self, guild):
        logger.info(f"🤖 Bot joined a new server: {guild.name} (ID: {guild.id})")
        try:
            copy_global = os.getenv("COPY_GLOBAL_TO_KNOWN_GUILDS", "1").strip().lower() in {"1", "true", "yes", "on"}
            if copy_global:
                self.tree.copy_global_to(guild=guild)
                cmds = await self.tree.sync(guild=guild)
                logger.info(f"✅ Immediately synced {len(cmds)} commands to new guild {guild.name}")
        except Exception as e:
            logger.error(f"⚠️ Could not sync commands for new guild: {e}")

    async def on_message(self, message):
        if message.author.bot:
            return
        await self.process_commands(message)

    async def on_disconnect(self):
        logger.warning("🔌 Discord gateway disconnected. (Potential Network Outage)")
        # สร้าง Flag ไว้เพื่อแจ้งเตือนตอน Reconnect
        try:
            if not os.path.exists(NETWORK_ERROR_FILE):
                with open(NETWORK_ERROR_FILE, 'w', encoding='utf-8') as f:
                    f.write(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                logger.info(f"Saved network error flag to: {NETWORK_ERROR_FILE}")
        except Exception as e:
            logger.error(f"Could not save network error flag: {e}")

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

    async def close(self):
        if getattr(self, "_already_closing", False):
            return
        self._already_closing = True
        self._is_shutting_down = True
        logger.info("Closing bot gracefully...")

        # 1. ส่งสถานะปิดบอทลง Status Channel ก่อนปิดการเชื่อมต่อ
        await self._send_offline_status()

        # 2. ลบ Flag ว่ากำลังทำงานอยู่ (เพราะปิดแบบปกติ)
        if os.path.exists(ALIVE_FLAG):
            try: os.remove(ALIVE_FLAG)
            except: pass

        # 3. Disconnect all voice clients explicitly with safety timeout
        await self._disconnect_voice_clients()
        
        # 4. ยกเลิก Task ทั้งหมด
        await self._cancel_all_tasks()
        
        await asyncio.sleep(0.5)
        await super().close()
        logger.info("Bot closed successfully.")

class DistributedAlphaBot(AlphaBotBase, commands.AutoShardedBot):
    def __init__(self, **kwargs):
        intents = discord.Intents.all()
        intents.members = True
        intents.message_content = True
        intents.presences = True
        
        shard_ids = get_shard_ids()
        total_shards = dcfg.TOTAL_SHARDS
        
        if shard_ids:
            kwargs['shard_ids'] = shard_ids
            kwargs['shard_count'] = total_shards or max(shard_ids) + 1
        elif total_shards:
            kwargs['shard_count'] = total_shards
            
        super().__init__(command_prefix='!', intents=intents, application_id=APPLICATION_ID, **kwargs)
        self.start_time = datetime.now(timezone.utc)
        self.mode = dcfg.BOT_MODE

    async def close(self):
        if getattr(self, "_already_closing", False):
            return
        self._already_closing = True
        self._is_shutting_down = True
        logger.info("Closing autosharded bot gracefully...")
        
        # 1. ส่งสถานะปิดบอทลง Status Channel
        await self._send_offline_status()

        # 2. ลบ Flag ว่ากำลังทำงานอยู่
        if os.path.exists(ALIVE_FLAG):
            try: os.remove(ALIVE_FLAG)
            except: pass

        # 3. Disconnect all voice clients explicitly with safety timeout
        await self._disconnect_voice_clients()

        # 4. ยกเลิก Task ทั้งหมด
        await self._cancel_all_tasks()

        await asyncio.sleep(0.5)
        await super().close()
        logger.info("Autosharded bot closed successfully.")

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
                    bot = AlphaBot()
                else:
                    bot = DistributedAlphaBot()

                async with bot:
                    await bot.start(TOKEN)

                if getattr(bot, "_stop_requested", False):
                    return
                if getattr(bot, "_restart_requested", False):
                    attempt = 0
                    await asyncio.sleep(1.0)
                    continue
                raise RuntimeError("bot.start exited unexpectedly")

            except KeyboardInterrupt:
                return
            except asyncio.CancelledError:
                # On Python 3.13+, CancelledError inherits BaseException and can bubble out during close().
                # Treat cancellation as a normal control-flow event for stop/restart.
                try:
                    t = asyncio.current_task()
                    if t is not None:
                        t.uncancel()
                except Exception:
                    pass

                if bot and getattr(bot, "_stop_requested", False):
                    return
                if bot and getattr(bot, "_restart_requested", False):
                    attempt = 0
                    await asyncio.sleep(1.0)
                    continue
                return
            except (discord.GatewayNotFound, discord.ConnectionClosed, OSError, ConnectionResetError, asyncio.TimeoutError, Exception) as e:
                # ตรวจสอบว่าเป็น Exception ที่ต้องการข้ามหรือไม่ (เช่น KeyboardInterrupt ถูกดักไปแล้ว)
                if isinstance(e, KeyboardInterrupt): return
                
                # สร้างไฟล์ Flag แสดงว่าหลุดเพราะเน็ต
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                try:
                    # มั่นใจว่าลบ ALIVE_FLAG ก่อนบันทึกความผิดพลาดเครือข่าย เพื่อไม่ให้ระบบเข้าใจผิดว่าบอทค้าง
                    if os.path.exists(ALIVE_FLAG):
                        os.remove(ALIVE_FLAG)
                        
                    with open(NETWORK_ERROR_FILE, 'w', encoding='utf-8') as f:
                        f.write(now_str)
                    
                    # บันทึกลงสถานะรวม
                    status_data = {}
                    if os.path.exists(NETWORK_STATUS_FILE):
                        try:
                            with open(NETWORK_STATUS_FILE, 'r', encoding='utf-8') as f:
                                status_data = json.load(f)
                        except Exception: pass
                    status_data["last_outage"] = now_str
                    status_data["status"] = "offline"
                    # ตรวจสอบว่าเป็นเหตุการณ์ไม่ปกติหรือไม่ (ถ้าไม่ใช่ OSError ทั่วไป)
                    if not isinstance(e, (discord.GatewayNotFound, discord.ConnectionClosed, ConnectionResetError)):
                         status_data["unexpected_event"] = True
                         
                    with open(NETWORK_STATUS_FILE, 'w', encoding='utf-8') as f:
                        json.dump(status_data, f, indent=4)
                except Exception: pass
                
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                logger.warning(f"🌐 Network/Gateway/Runtime error: {e}. Reconnecting in {delay}s")
                await asyncio.sleep(delay)
            except Exception as e:
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                logger.error(f"💥 Fatal runtime error: {e}. Restarting in {delay}s")
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
    except asyncio.CancelledError:
        # Prevent noisy stack traces if a shutdown triggers a cancellation at the runner level.
        pass

if __name__ == "__main__":
    run_bot()
