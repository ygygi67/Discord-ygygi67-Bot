import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import asyncio
import os
from yt_dlp import YoutubeDL
import re
from typing import Optional, List, Dict, Any
import json
from datetime import datetime, timezone
import time
import uuid
import random
import shutil
from difflib import SequenceMatcher
from pathlib import Path

logger = logging.getLogger('music_cog')

# ═══════════════════════════════════════════════════════
# 🎵 MUSIC RECOMMENDATION SYSTEM (YouTube Music-like)
# ═══════════════════════════════════════════════════════

class MusicRecommendationEngine:
    """ระบบแนะนำเพลงอัจฉริยะ - เรียนรู้รสนิยมและแนะนำเพลงที่เหมาะสม"""
    
    def __init__(self, cog):
        self.cog = cog
        self.recommendation_cache = {}
        self.fallback_playlist_id = "PLClZz0mM3CSkzq9OPkgpqjlosUqxtO78m"
        self.fallback_tracks = []
        self.last_fallback_update = 0
        
    async def load_fallback_playlist(self):
        """โหลดเพลงจาก playlist สำรองทุก 6 ชั่วโมง"""
        current_time = time.time()
        if current_time - self.last_fallback_update < 21600 and self.fallback_tracks:  # 6 hours
            return self.fallback_tracks
            
        try:
            ydl_opts = {
                'format': 'bestaudio/best',
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'playlistend': 100,  # โหลดแค่ 100 เพลงแรก
            }
            
            playlist_url = f"https://www.youtube.com/playlist?list={self.fallback_playlist_id}"
            
            def extract():
                with YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(playlist_url, download=False)
            
            info = await asyncio.get_event_loop().run_in_executor(None, extract)
            
            if info and 'entries' in info:
                self.fallback_tracks = []
                for entry in info['entries']:
                    if entry:
                        track = MusicTrack(
                            title=entry.get('title', 'Unknown'),
                            url=entry.get('url'),
                            duration=entry.get('duration', 0),
                            webpage_url=entry.get('webpage_url', entry.get('url')),
                            source="fallback_playlist"
                        )
                        if self.is_good_quality_track(track):
                            self.fallback_tracks.append(track)
                
                self.last_fallback_update = current_time
                logger.info(f"[MusicRec] Loaded {len(self.fallback_tracks)} tracks from fallback playlist")
                
        except Exception as e:
            logger.error(f"[MusicRec] Failed to load fallback playlist: {e}")
            
        return self.fallback_tracks
        
    def get_random_fallback_track(self) -> Optional['MusicTrack']:
        """สุ่มเพลงจาก playlist สำรอง"""
        if self.fallback_tracks:
            return random.choice(self.fallback_tracks)
        return None
        
    def extract_artist_from_title(self, title: str) -> str:
        """แยกชื่อศิลปินจากชื่อเพลง"""
        separators = [' - ', ' – ', ' — ', ': ', ' | ']
        for sep in separators:
            if sep in title:
                parts = title.split(sep, 1)
                if len(parts) == 2:
                    artist = parts[0].strip()
                    if len(artist) > 2 and not artist.isdigit():
                        return artist
        return ""
    
    def get_search_strategies(self, last_track) -> list:
        """สร้างหลายกลยุทธ์การค้นหา"""
        title = last_track.title
        artist = self.extract_artist_from_title(title)
        clean_title = re.sub(r'\([^)]*\)|\[[^\]]*\]', '', title).strip()
        
        strategies = []
        
        if artist and len(artist) > 2:
            strategies.extend([
                f"{artist} greatest hits",
                f"{artist} popular songs",
                f"{artist} เพลงฮิต",
            ])
        
        strategies.extend([
            f"songs similar to {clean_title}",
            f"music like {clean_title}",
            "top music 2024",
            "popular songs this week",
        ])
        
        return strategies
    
    def is_good_quality_track(self, track) -> bool:
        """ตรวจสอบคุณภาพเพลง"""
        title_lower = track.title.lower()
        
        bad_keywords = [
            'live', 'concert', 'performance', 'karaoke',
            '1 hour', '10 hours', 'loop', ' slowed ', ' reverb',
            'reaction', 'review', 'tutorial', 'how to',
            'minecraft', 'roblox', 'fortnite', 'gameplay'
        ]
        
        for keyword in bad_keywords:
            if keyword in title_lower:
                return False
        
        if track.duration > 0:
            if track.duration < 60 or track.duration > 600:
                return False
        
        return True
    
    def calculate_similarity(self, track1, track2) -> float:
        """คำนวณความคล้ายคลึง (0-1)"""
        title1 = track1.title.lower()
        title2 = track2.title.lower()
        
        similarity = SequenceMatcher(None, title1, title2).ratio()
        
        artist1 = self.extract_artist_from_title(track1.title).lower()
        artist2 = self.extract_artist_from_title(track2.title).lower()
        if artist1 and artist2 and (artist1 in artist2 or artist2 in artist1):
            similarity += 0.3
        
        return min(similarity, 1.0)
    
    async def find_best_recommendation(self, guild_id: int, last_track) -> Optional['MusicTrack']:
        """หาเพลงแนะนำที่ดีที่สุด - ถ้าไม่เจอจากกลยุทธ์ปกติ ให้ใช้ fallback playlist"""
        strategies = self.get_search_strategies(last_track)
        candidates = []
        
        for strategy in strategies[:4]:
            try:
                track = await self.cog.search_track(strategy)
                if track and self.is_good_quality_track(track):
                    score = self.calculate_similarity(last_track, track)
                    candidates.append((track, score))
                    
                    if score > 0.5:
                        break
                        
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.warning(f"[MusicRec] Search failed: {e}")
                continue
        
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]
        
        # 🎯 Fallback: ถ้าไม่เจอเพลงที่ดี ให้ใช้ playlist สำรอง
        logger.info("[MusicRec] No good recommendation found, using fallback playlist")
        await self.load_fallback_playlist()
        return self.get_random_fallback_track()

# ═══════════════════════════════════════════════════════

class MusicTrack:
    def __init__(self, title: str, url: str, duration: int = 0, 
                 thumbnail: str = None, webpage_url: str = None, 
                 requester: discord.Member = None, source: str = "unknown"):
        self.title = title
        self.url = url
        self.duration = duration
        self.thumbnail = thumbnail
        self.webpage_url = webpage_url or url
        self.requester = requester
        self.source = source
        self.is_karaoke = False
        self.local_url = None
        self.created_at = datetime.now(timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'title': self.title,
            'url': self.url,
            'duration': self.duration,
            'thumbnail': self.thumbnail,
            'webpage_url': self.webpage_url,
            'source': self.source,
            'is_karaoke': self.is_karaoke,
            'local_url': self.local_url,
            'requester_id': self.requester.id if self.requester else None,
            'created_at': self.created_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], guild: discord.Guild = None):
        track = cls(
            title=data['title'],
            url=data['url'],
            duration=data.get('duration', 0),
            thumbnail=data.get('thumbnail'),
            webpage_url=data.get('webpage_url'),
            source=data.get('source', 'unknown')
        )
        track.is_karaoke = data.get('is_karaoke', False)
        track.local_url = data.get('local_url')
        if guild and data.get('requester_id'):
            track.requester = guild.get_member(data['requester_id'])
        return track

class MusicQueue:
    def __init__(self):
        self.tracks: List[MusicTrack] = []
        self.history: List[MusicTrack] = []
        self.loop_mode = "none" # none, track, queue
        self.shuffle_enabled = False
        self.current_track: Optional[MusicTrack] = None
        self.volume = 1.0
        self.filters = {
            "bassboost": False,
            "nightcore": False,
            "vaporwave": False
        }
        self.text_channel_id: Optional[int] = None
        self.start_time: float = 0
        self.paused_at: float = 0
        self.total_paused: float = 0
        self.is_refreshing: bool = False
        self.auto_play: bool = False
        self.is_afk: bool = False
    
    def add(self, track: MusicTrack) -> int:
        self.tracks.append(track)
        return len(self.tracks)
    
    def get_next(self) -> Optional[MusicTrack]:
        if self.loop_mode == "track" and self.current_track:
            return self.current_track

        if not self.tracks:
            if self.loop_mode == "queue" and self.history:
                self.tracks = self.history.copy()
                self.history.clear()
            else:
                return None
        
        if self.shuffle_enabled and len(self.tracks) > 1:
            import random
            track = random.choice(self.tracks)
            self.tracks.remove(track)
        else:
            track = self.tracks.pop(0)
        
        if self.current_track:
            self.history.append(self.current_track)
        
        self.current_track = track
        return track
    
    def remove(self, index: int) -> Optional[MusicTrack]:
        if 0 <= index < len(self.tracks):
            return self.tracks.pop(index)
        return None
    
    def clear(self):
        self.tracks.clear()
        self.current_track = None
    
    def shuffle(self):
        import random
        random.shuffle(self.tracks)

class MusicControlView(discord.ui.View):
    def __init__(self, music_cog, guild_id: int):
        super().__init__(timeout=None)
        self.music_cog = music_cog
        self.guild_id = guild_id

    async def update_state(self, guild):
        if guild.voice_client:
            await self.music_cog.save_voice_state(guild.id, guild.voice_client.channel.id)

    @discord.ui.button(label="⏯️", style=discord.ButtonStyle.secondary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if not voice_client:
            return await interaction.response.send_message("❌ บอทไม่ได้อยู่ในช่องเสียง", ephemeral=True)
        
        queue = self.music_cog.get_queue(interaction.guild.id)
        if voice_client.is_playing():
            voice_client.pause()
            queue.paused_at = time.time()
            await interaction.response.send_message("⏸️ พักการเล่นเพลง", ephemeral=True)
        else:
            voice_client.resume()
            if queue.paused_at > 0:
                queue.total_paused += time.time() - queue.paused_at
                queue.paused_at = 0
            await interaction.response.send_message("▶️ เล่นเพลงต่อ", ephemeral=True)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client:
            voice_client.stop()
            await interaction.response.send_message("⏭️ ข้ามเพลงปัจจุบัน", ephemeral=True)
        else:
            await interaction.response.send_message("❌ บอทไม่ได้อยู่ในช่องเสียง", ephemeral=True)

    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client:
            queue = self.music_cog.get_queue(interaction.guild.id)
            queue.clear()
            await voice_client.disconnect()
            await self.music_cog.save_voice_state(interaction.guild.id, None)
            await interaction.response.send_message("⏹️ หยุดเล่นและออกจากช่องเสียง", ephemeral=True)
        else:
            await interaction.response.send_message("❌ บอทไม่ได้อยู่ในช่องเสียง", ephemeral=True)

    @discord.ui.button(label="🔀", style=discord.ButtonStyle.secondary)
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue = self.music_cog.get_queue(interaction.guild.id)
        queue.shuffle_enabled = not queue.shuffle_enabled
        await self.update_state(interaction.guild)
        status = "เปิด" if queue.shuffle_enabled else "ปิด"
        await interaction.response.send_message(f"🔀 {status} โหมดสุ่มเพลง", ephemeral=True)

    @discord.ui.button(label="🔁", style=discord.ButtonStyle.secondary)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue = self.music_cog.get_queue(interaction.guild.id)
        modes = ["none", "track", "queue"]
        current_index = modes.index(queue.loop_mode)
        next_index = (current_index + 1) % len(modes)
        queue.loop_mode = modes[next_index]
        await self.update_state(interaction.guild)
        
        mode_names = {"none": "ปิด", "track": "เพลงปัจจุบัน", "queue": "คิวทั้งหมด"}
        await interaction.response.send_message(f"🔁 โหมดวนซ้ำ: **{mode_names[queue.loop_mode]}**", ephemeral=True)

    @discord.ui.button(label="🔊+", style=discord.ButtonStyle.secondary)
    async def volume_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue = self.music_cog.get_queue(interaction.guild.id)
        queue.volume = min(queue.volume + 0.1, 2.0)
        await self.update_state(interaction.guild)
        await interaction.response.send_message(f"🔊 เพิ่มเสียงเป็น: **{int(queue.volume * 100)}%**", ephemeral=True)
        await self.music_cog.refresh_playback(interaction.guild.id)

    @discord.ui.button(label="🔉-", style=discord.ButtonStyle.secondary)
    async def volume_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue = self.music_cog.get_queue(interaction.guild.id)
        queue.volume = max(queue.volume - 0.1, 0.1)
        await self.update_state(interaction.guild)
        await interaction.response.send_message(f"🔉 ลดเสียงเหลือ: **{int(queue.volume * 100)}%**", ephemeral=True)
        await self.music_cog.refresh_playback(interaction.guild.id)

    @discord.ui.button(label="📻", style=discord.ButtonStyle.secondary)
    async def toggle_auto_play(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue = self.music_cog.get_queue(interaction.guild.id)
        queue.auto_play = not queue.auto_play
        await self.update_state(interaction.guild)
        status = "เปิด" if queue.auto_play else "ปิด"
        await interaction.response.send_message(f"📻 {status} โหมดเล่นเพลงอัตโนมัติ (แนะนำเพลงที่เกี่ยวข้อง)", ephemeral=True)

class FilterSelect(discord.ui.Select):
    def __init__(self, music_cog, guild_id):
        self.music_cog = music_cog
        self.guild_id = guild_id
        options = [
            discord.SelectOption(label="Bassboost", description="เพิ่มเบสให้หนักแน่น", emoji="🎸", value="bassboost"),
            discord.SelectOption(label="Nightcore", description="เพิ่มความเร็วและระดับเสียง", emoji="⚡", value="nightcore"),
            discord.SelectOption(label="Vaporwave", description="สไตล์ช้าๆ ผ่อนคลาย", emoji="🌴", value="vaporwave"),
            discord.SelectOption(label="ล้างเอฟเฟกต์", description="ปิดเอฟเฟกต์ทั้งหมด", emoji="❌", value="clear")
        ]
        super().__init__(placeholder="🎨 เลือกเอฟเฟกต์เสียง...", options=options)

    async def callback(self, interaction: discord.Interaction):
        queue = self.music_cog.get_queue(self.guild_id)
        if self.values[0] == "clear":
            for f in queue.filters: queue.filters[f] = False
        else:
            # Toggle filter
            filter_name = self.values[0]
            queue.filters[filter_name] = not queue.filters[filter_name]
        
        await self.music_cog.save_voice_state(self.guild_id, interaction.guild.voice_client.channel.id if interaction.guild.voice_client else None)
        
        # Apply immediately
        await self.music_cog.refresh_playback(self.guild_id)
        
        active_filters = [f.capitalize() for f, v in queue.filters.items() if v]
        filter_str = ", ".join(active_filters) if active_filters else "ปิด"
        await interaction.response.send_message(f"🔮 ปรับแต่งเสียง: **{filter_str}** (จะมีผลกับเพลงถัดไปหรือเริ่มใหม่)", ephemeral=True)

class Music(commands.Cog):
    """🎵 Advanced Music System with Smart Recommendations"""
    
    def __init__(self, bot):
        self.bot = bot
        self.queues: Dict[int, MusicQueue] = {}
        self.recommendation_engine = MusicRecommendationEngine(self)  # เครื่องมือแนะนำเพลงอัจฉริยะ
        self.voice_state_file = 'data/music_state.json'
        
        if not os.path.exists('data'):
            os.makedirs('data')
            
        # Distributed Mode Support
        self.shared_queue = None
        self.pending_downloads = {}
        
        try:
            from core.distributed_config import is_master, ENABLE_DISTRIBUTED_MUSIC
            if is_master() and ENABLE_DISTRIBUTED_MUSIC:
                from core.shared_queue import AsyncSharedQueue
                self.shared_queue = AsyncSharedQueue()
                self.check_downloads.start()
        except:
            pass
        
        # Reload protection
        self.reload_in_progress = False
        self.karaoke_dir = "data/temp/karaoke"
        os.makedirs(self.karaoke_dir, exist_ok=True)

        
    async def save_voice_state(self, guild_id: int, channel_id: Optional[int]):
        try:
            full_data = {}
            if os.path.exists(self.voice_state_file):
                with open(self.voice_state_file, 'r', encoding='utf-8') as f:
                    full_data = json.load(f)
            
            guild_id_str = str(guild_id)
            if channel_id:
                queue = self.get_queue(guild_id)
                
                # Calculate current playback position
                elapsed = 0
                if queue.current_track and queue.start_time > 0:
                    elapsed = time.time() - queue.start_time - queue.total_paused
                    if queue.paused_at > 0:
                        elapsed -= (time.time() - queue.paused_at)
                
                full_data[guild_id_str] = {
                    'channel_id': channel_id,
                    'current_track': queue.current_track.to_dict() if queue.current_track else None,
                    'queue': [t.to_dict() for t in queue.tracks],
                    'loop': queue.loop_mode,
                    'shuffle': queue.shuffle_enabled,
                    'volume': queue.volume,
                    'filters': queue.filters,
                    'text_channel_id': queue.text_channel_id,
                    'auto_play': queue.auto_play,
                    'is_afk': queue.is_afk,
                    'elapsed': max(0, elapsed)  # บันทึกตำแหน่งการเล่นปัจจุบัน
                }
            else:
                full_data.pop(guild_id_str, None)
                
            with open(self.voice_state_file, 'w', encoding='utf-8') as f:
                json.dump(full_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def load_voice_states(self) -> Dict[str, Any]:
        try:
            if os.path.exists(self.voice_state_file):
                with open(self.voice_state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading state: {e}")
        return {}

    async def cog_load(self):
        """Auto-resume playback when cog loads or bot restarts"""
        asyncio.create_task(self.auto_resume_on_load())

    async def auto_resume_on_load(self):
        """Internal method to handle the resume process"""
        await self.bot.wait_until_ready()
        # เพิ่มดีเลย์เพื่อให้แน่ใจว่า Cache ของกิลด์และแชแนลโหลดเสร็จสมบูรณ์จริงๆ
        await asyncio.sleep(15) 
        states = self.load_voice_states()

        
        for g_id, state in states.items():
            guild = self.bot.get_guild(int(g_id))
            if not guild:
                continue
            
            c_id = state.get('channel_id') if isinstance(state, dict) else state
            if not c_id:
                continue
                
            channel = guild.get_channel(c_id)
            if not channel or not isinstance(channel, discord.VoiceChannel):
                continue
                
            try:
                # Check if already connected
                vc = guild.voice_client
                if not vc:
                    # Connect to voice channel with retry
                    for attempt in range(3):
                        try:
                            vc = await channel.connect(timeout=20.0, reconnect=True)
                            logger.info(f"[AutoResume] Reconnected to {channel.name} in {guild.name}")
                            break
                        except Exception as ce:
                            logger.warning(f"[AutoResume] Connect attempt {attempt+1} failed: {ce}")
                            if attempt == 2:
                                raise ce
                            await asyncio.sleep(2)
                else:
                    logger.info(f"[AutoResume] Hijacking existing voice client in {guild.name}")
                
                if isinstance(state, dict):
                    queue = self.get_queue(guild.id)
                    
                    # Restore queue settings
                    queue.loop_mode = state.get('loop', 'none')
                    queue.shuffle_enabled = state.get('shuffle', False)
                    queue.volume = state.get('volume', 1.0)
                    queue.filters = state.get('filters', {"bassboost": False, "nightcore": False, "vaporwave": False})
                    queue.text_channel_id = state.get('text_channel_id')
                    queue.auto_play = state.get('auto_play', False)
                    queue.is_afk = state.get('is_afk', False)
                    
                    # Restore queue tracks
                    for t_data in state.get('queue', []):
                        track = MusicTrack.from_dict(t_data, guild)
                        if track:
                            queue.tracks.append(track)
                    
                    # Restore and resume current track
                    curr_data = state.get('current_track')
                    if curr_data:
                        current_track = MusicTrack.from_dict(curr_data, guild)
                        if current_track:
                            # Restore requester
                            requester_id = curr_data.get('requester_id')
                            if requester_id:
                                current_track.requester = guild.get_member(requester_id)
                            
                            # Calculate resume position
                            elapsed = state.get('elapsed', 0)
                            if elapsed > 5:  # Resume from 5 seconds before to avoid missing anything
                                resume_pos = max(0, elapsed - 5)
                            else:
                                resume_pos = 0
                            
                            logger.info(f"[AutoResume] Resuming {current_track.title} from {resume_pos}s")
                            
                            # Set as current track and play from position
                            queue.current_track = current_track
                            await self.play_track(vc, current_track, seek=resume_pos)
                            
                            # Notify in text channel
                            if queue.text_channel_id:
                                text_channel = guild.get_channel(queue.text_channel_id)
                                if text_channel:
                                    embed = discord.Embed(
                                        title="🔄 กลับมาเล่นต่อจากที่ค้างไว้",
                                        description=f"**{current_track.title}**\n▶️ เริ่มที่: `{int(resume_pos//60)}:{int(resume_pos%60):02d}`",
                                        color=discord.Color.blue()
                                    )
                                    await text_channel.send(embed=embed)
                    else:
                        # No current track but have queue - start playing queue
                        if queue.tracks and not vc.is_playing():
                            next_track = queue.get_next()
                            if next_track:
                                await self.play_track(vc, next_track)
                                logger.info(f"[AutoResume] Started playing queue: {next_track.title}")
                                
            except Exception as e:
                logger.error(f"[AutoResume] Failed for {guild.name}: {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot: return
        guild = member.guild
        vc = guild.voice_client
        if not vc: return

        # Follow logic (Ask before follow)
        if before.channel != after.channel and after.channel and vc.channel == before.channel:
            if not [m for m in before.channel.members if not m.bot]:
                class FollowView(discord.ui.View):
                    def __init__(self, bot_vc, target_channel, music_cog, guild_id):
                        super().__init__(timeout=120)
                        self.bot_vc = bot_vc
                        self.target_channel = target_channel
                        self.music_cog = music_cog
                        self.guild_id = guild_id

                    @discord.ui.button(label="ลากบอทมาที่นี่", style=discord.ButtonStyle.green, emoji="🏃")
                    async def follow_button(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                        if self.bot_vc and self.bot_vc.is_connected():
                            await self.bot_vc.move_to(self.target_channel)
                            await self.music_cog.save_voice_state(self.guild_id, self.target_channel.id)
                            await btn_interaction.response.send_message(f"✅ บอทย้ายตามมาเล่นเพลงที่ {self.target_channel.mention} แล้ว!", ephemeral=False)
                        else:
                            await btn_interaction.response.send_message("❌ บอทไม่ได้อยู่ในระบบแล้ว", ephemeral=True)
                        for child in self.children: child.disabled = True
                        try:
                            await btn_interaction.message.edit(view=self)
                        except: pass

                # ส่งคำถามไปที่ช่อง Text ภายใน Voice Channel ปัจจุบันที่ผู้ใช้ย้ายเข้าไป
                try:
                    await after.channel.send(
                        f"👋 คุณ {member.mention} ย้ายห้อง... ทิ้งบอทไว้ห้องเดิม\nต้องการให้บอทย้ายตามมาเล่นเพลงต่อที่นี่ไหม?", 
                        view=FollowView(vc, after.channel, self, guild.id)
                    )
                except Exception:
                    pass

    def get_queue(self, guild_id: int) -> MusicQueue:
        if guild_id not in self.queues:
            self.queues[guild_id] = MusicQueue()
        return self.queues[guild_id]

    async def search_track(self, query: str) -> Optional[MusicTrack]:
        if "youtu.be" in query:
            query = f"https://www.youtube.com/watch?v={query.split('/')[-1].split('?')[0]}"
        query = re.sub(r'&list=.*$', '', query)
        try:
            ydl_opts = {'format': 'bestaudio/best', 'quiet': True, 'no_warnings': True, 'extract_flat': False}
            if not any(d in query for d in ['youtube.com', 'youtu.be', 'soundcloud.com']):
                query = f"ytsearch1:{query}"
            with YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(query, download=False))
                if not info: return None
                if 'entries' in info and info['entries']: info = info['entries'][0]
                url = info.get('url')
                if not url:
                    formats = [f for f in info.get('formats', []) if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
                    if formats: url = sorted(formats, key=lambda x: x.get('abr', 0), reverse=True)[0]['url']
                return MusicTrack(title=info.get('title', 'Unknown'), url=url or info.get('webpage_url'), 
                                 duration=info.get('duration', 0), thumbnail=info.get('thumbnail'),
                                 webpage_url=info.get('webpage_url', query), source="yt-dlp")
        except Exception as e:
            logger.error(f"Search failed: {e}"); return None

    async def _process_karaoke_track(self, guild_id: int, track: MusicTrack):
        """ใช้ AI แยกเสียงร้องเพื่อสร้างไฟล์คาราโอเกะ (Instrumental)"""
        if track.local_url and os.path.exists(track.local_url):
            return
            
        queue = self.get_queue(guild_id)
        msg = None
        if queue.text_channel_id:
            channel = self.bot.get_guild(guild_id).get_channel(queue.text_channel_id)
            if channel:
                msg = await channel.send(f"🎙️ **AI กำลังจัดเตรียมโหมดคาราโอเกะ...**\nเพลง: `{track.title}`\n(ขั้นตอนนี้ใช้เวลาประมาณ 1-2 นาที กรุณารอสักครู่)")

        session_id = f"karaoke_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        work_path = os.path.join(self.karaoke_dir, session_id)
        os.makedirs(work_path, exist_ok=True)
        
        try:
            # 1. Download full audio
            temp_dl = os.path.join(work_path, "input.mp3")
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': temp_dl,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
                'no_warnings': True,
            }
            
            def download():
                with YoutubeDL(ydl_opts) as ydl:
                    ydl.download([track.webpage_url])
            
            await self.bot.loop.run_in_executor(None, download)
            
            if not os.path.exists(temp_dl):
                raise Exception("ดาวน์โหลดไฟล์เสียงไม่สำเร็จ")
                
            # 2. Separate
            output_dir = os.path.join(work_path, "output")
            os.makedirs(output_dir, exist_ok=True)
            
            cmd = [
                "audio-separator",
                temp_dl,
                "--output_dir", output_dir,
                "--model_filename", "UVR-MDX-NET-Voc_FT.onnx",
                "--output_format", "MP3"
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.wait()
            
            # 3. Find instrumental
            instrumental_file = None
            for f in os.listdir(output_dir):
                if "(Instrumental)" in f:
                    instrumental_file = os.path.join(output_dir, f)
                    break
            
            if instrumental_file:
                # Move to permanent temp storage
                final_path = os.path.join(self.karaoke_dir, f"{session_id}_inst.mp3")
                shutil.move(instrumental_file, final_path)
                track.local_url = final_path
                if msg: await msg.edit(content=f"✅ **AI คาราโอเกะพร้อมแล้ว!** เริ่มเล่น Instrumental ของ: `{track.title}`")
            else:
                raise Exception("AI แยกเสียงดนตรีไม่สำเร็จ")
                
        except Exception as e:
            logger.error(f"[Karaoke] Error processing {track.title}: {e}")
            if msg: await msg.edit(content=f"❌ **ขออภัย:** ระบบไม่สามารถสร้างคาราโอเกะได้ ({str(e)}) บอทจะเล่นแบบปกติแทน...")
        finally:
            # Clean up work path
            shutil.rmtree(work_path, ignore_errors=True)

    async def play_track(self, vc: discord.VoiceClient, track: MusicTrack, seek: float = 0):
        try:
            queue = self.get_queue(vc.guild.id)
            
            # 🎙️ Handle Karaoke Mode
            if track.is_karaoke and not track.local_url:
                await self._process_karaoke_track(vc.guild.id, track)
            
            # Use local URL if available
            stream_url = track.local_url if (track.local_url and os.path.exists(track.local_url)) else track.url
            
            # Dynamic FFMPEG filters
            af_filters = []
            
            # Audio Normalization (always on) - EBU R128 standard, keeps all songs at equal volume
            af_filters.append("loudnorm=I=-14:TP=-1:LRA=11")
            
            if queue.filters.get("bassboost"):
                af_filters.append("bass=g=15:f=110:w=0.6")
            if queue.filters.get("nightcore"):
                af_filters.append("atempo=1.06,asetrate=44100*1.25")
            if queue.filters.get("vaporwave"):
                af_filters.append("atempo=0.8,asetrate=44100*0.8")
            
            # Volume filter
            af_filters.append(f"volume={queue.volume}")
            
            filter_str = f"-af \"{','.join(af_filters)}\"" if af_filters else ""
            
            # Seek adjustment
            seek_opt = f"-ss {seek}" if seek > 0 else ""
            
            opts = {
                'options': f'-vn -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 {filter_str}', 
                'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 {seek_opt}'
            }
            
            vc.play(discord.FFmpegPCMAudio(stream_url, **opts), 
                    after=lambda e: asyncio.run_coroutine_threadsafe(self.handle_track_end(vc.guild), self.bot.loop))
            queue.current_track = track
            queue.start_time = time.time() - seek
            queue.total_paused = 0
            queue.paused_at = 0
            await self.save_voice_state(vc.guild.id, vc.channel.id)
        except Exception as e:
            logger.error(f"Play error: {e}")

    async def handle_track_end(self, guild: discord.Guild):
        queue = self.get_queue(guild.id)
        if queue.is_refreshing: return # Skip if we are just refreshing with filters
        
        next_t = queue.get_next()
        vc = guild.voice_client
        if next_t and vc:
            await self.play_track(vc, next_t)
            
            # Use saved text channel or find one
            channel = None
            if queue.text_channel_id:
                channel = guild.get_channel(queue.text_channel_id)
            
            if not channel:
                for ch in guild.text_channels:
                    if ch.permissions_for(guild.me).send_messages:
                        channel = ch
                        break
            
            if channel:
                await self.send_now_playing(channel, next_t)
        elif vc:
            if queue.is_afk: return
            await asyncio.sleep(300)
            if vc and not vc.is_playing() and not [m for m in vc.channel.members if not m.bot]:
                await vc.disconnect()
                await self.save_voice_state(guild.id, None)
            elif vc and not vc.is_playing() and queue.auto_play:
                # 🎯 ใช้ระบบแนะนำเพลงอัจฉริยะแทนการค้นหาง่าย ๆ
                last_track = queue.history[-1] if queue.history else queue.current_track
                if last_track:
                    logger.info(f"[AutoPlay] Finding recommendation based on: {last_track.title}")
                    
                    # ใช้ recommendation engine เพื่อหาเพลงที่ดีที่สุด
                    recommended = await self.recommendation_engine.find_best_recommendation(guild.id, last_track)
                    
                    if recommended:
                        recommended.requester = None  # บอทจัดมาให้
                        queue.add(recommended)
                        logger.info(f"[AutoPlay] Added recommended track: {recommended.title}")
                        
                        # แจ้งผู้ใช้ว่ากำลังเล่นเพลงแนะนำ
                        if queue.text_channel_id:
                            channel = guild.get_channel(queue.text_channel_id)
                            if channel:
                                embed = discord.Embed(
                                    title="🎵 เพลงแนะนำโดยอัตโนมัติ",
                                    description=f"**{recommended.title}**",
                                    color=discord.Color.green()
                                )
                                embed.set_footer(text="📻 เปิด Auto-Play เพื่อให้บอทแนะนำเพลงต่อเนื่อง")
                                await channel.send(embed=embed)
                        
                        # เล่นเพลงที่เพิ่มเข้ามา
                        await self.handle_track_end(guild)
                    else:
                        logger.warning("[AutoPlay] Could not find good recommendation")

    async def send_now_playing(self, channel: discord.TextChannel, track: MusicTrack):
        queue = self.get_queue(channel.guild.id)
        embed = discord.Embed(title="💿 ขณะนี้กำลังบรรเลงเพลง...", description=f"**[{track.title}]({track.webpage_url})**", color=discord.Color.blue())
        if track.thumbnail: embed.set_thumbnail(url=track.thumbnail)
        embed.add_field(name="ขอโดย", value=track.requester.mention if track.requester else "แอดมิน", inline=True)
        duration = "สด" if track.duration == 0 else f"{track.duration // 60}:{track.duration % 60:02d}"
        embed.add_field(name="ความยาว", value=duration, inline=True)
        
        # Audio status
        active_filters = [f.capitalize() for f, v in queue.filters.items() if v]
        filter_display = ", ".join(active_filters) if active_filters else "ทั่วไป"
        embed.add_field(name="🔊 ระดับเสียง", value=f"{int(queue.volume * 100)}%", inline=True)
        embed.add_field(name="🔮 ฟิลเตอร์", value=filter_display, inline=True)
        
        view = MusicControlView(self, channel.guild.id)
        view.add_item(FilterSelect(self, channel.guild.id))
        
        await channel.send(embed=embed, view=view)

    async def refresh_playback(self, guild_id: int, seek_override: float = None):
        vc = self.bot.get_guild(guild_id).voice_client
        if not vc: return
        queue = self.get_queue(guild_id)
        if not queue.current_track: return

        # Calculate current position if not provided
        elapsed = seek_override
        if elapsed is None:
            if queue.start_time > 0:
                elapsed = time.time() - queue.start_time - queue.total_paused
                if queue.paused_at > 0:
                    elapsed -= (time.time() - queue.paused_at)
            else:
                elapsed = 0
        
        # Stop without triggering handle_track_end
        queue.is_refreshing = True
        if vc.is_playing() or vc.is_paused():
            vc.stop()
        
        await asyncio.sleep(0.5) # Wait for cleanup
        await self.play_track(vc, queue.current_track, seek=max(0, elapsed))
        queue.is_refreshing = False

    @app_commands.command(name="เล่น", description="เล่นเพลงจากชื่อหรือลิงก์")
    @app_commands.describe(query="ชื่อเพลงหรือลิงก์", mode="เลือกโหมดการเล่น (สำหรับคาราโอเกะระบบจะโหลดและแยกเสียงร้องให้อัตโนมัติ)")
    @app_commands.choices(mode=[
        app_commands.Choice(name="ปกติ (Normal)", value="normal"),
        app_commands.Choice(name="คาราโอเกะ - ตัดเสียงร้อง (Karaoke)", value="karaoke")
    ])
    async def play(self, interaction: discord.Interaction, query: str, mode: str = "normal"):
        await interaction.response.defer()
        queue = self.get_queue(interaction.guild.id)
        queue.text_channel_id = interaction.channel_id
        if not interaction.user.voice: return await interaction.followup.send("❌ คุณต้องอยู่ในช่องเสียง", ephemeral=True)
        
        vc = interaction.guild.voice_client
        if not vc: vc = await interaction.user.voice.channel.connect()

        if 'playlist' in query or '&list=' in query:
            await interaction.followup.send("🎶 กำลังทยอยเพิ่มเพลย์ลิสต์...")
            asyncio.create_task(self._process_playlist(interaction, query))
            return

        track = await self.search_track(query)
        if not track: return await interaction.followup.send("❌ ไม่พบเพลง", ephemeral=True)
        track.requester = interaction.user
        track.is_karaoke = (mode == "karaoke")
        
        queue = self.get_queue(interaction.guild.id)
        pos = queue.add(track)
        
        if not vc.is_playing():
            next_t = queue.get_next()
            await self.play_track(vc, next_t)
            await self.send_now_playing(interaction.channel, next_t)
            with YoutubeDL({'extract_flat': 'in_playlist', 'quiet': True}) as ydl:
                return ydl.extract_info(query, download=False, process=False)
            await interaction.response.send_message("⏭️ ข้ามแล้ว")
        else:
            await interaction.response.send_message("❌ ไม่มีเพลงเล่นอยู่", ephemeral=True)

    @app_commands.command(name="คิว", description="ดูคิวเพลง")
    async def queue(self, interaction: discord.Interaction):
        q = self.get_queue(interaction.guild.id)
        embed = discord.Embed(title="📝 คิวเพลง", color=discord.Color.blue())
        if q.current_track: embed.add_field(name="🎵 กำลังเล่น", value=q.current_track.title, inline=False)
        if q.tracks:
            text = "\n".join([f"{i+1}. {t.title}" for i, t in enumerate(q.tracks[:10])])
            if len(q.tracks) > 10: text += f"\n...และอีก {len(q.tracks)-10} เพลง"
            embed.add_field(name="📋 คิวถัดไป", value=text, inline=False)
        else:
            embed.description = "ไม่มีเพลงในคิว"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="หยุด", description="หยุดและออกจากห้อง")
    async def stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc:
            self.get_queue(guild_id=interaction.guild.id).clear()
            await vc.disconnect()
            await self.save_voice_state(interaction.guild.id, None)
            await interaction.response.send_message("✅ หยุดและออกจากห้องแล้ว")
        else:
            await interaction.response.send_message("❌ ไม่ได้อยู่ในห้องเสียง", ephemeral=True)

    @app_commands.command(name="afk", description="ให้บอทอยู่ในช่องเสียงตลอดไป (แม้จะเล่นเพลงจบแล้ว)")
    @app_commands.describe(channel="ช่องที่ต้องการให้บอทเข้า (ถ้าไม่ระบุจะเข้าช่องที่คุณอยู่)")
    async def toggle_afk(self, interaction: discord.Interaction, channel: Optional[discord.VoiceChannel] = None):
        target_channel = channel
        if not target_channel:
            if interaction.user.voice:
                target_channel = interaction.user.voice.channel
            else:
                return await interaction.response.send_message("❌ กรุณาระบุช่องเสียง หรือเข้าช่องเสียงก่อนใช้คำสั่งนี้", ephemeral=True)
        
        await interaction.response.defer()
        
        queue = self.get_queue(interaction.guild.id)
        queue.is_afk = not queue.is_afk
        
        vc = interaction.guild.voice_client
        if queue.is_afk:
            if not vc:
                vc = await target_channel.connect()
            elif vc.channel.id != target_channel.id:
                await vc.move_to(target_channel)
            
            await self.save_voice_state(interaction.guild.id, target_channel.id)
            await interaction.followup.send(f"💤 **โหมด AFK เปิดใช้งาน:** บอทจะอยู่ในช่อง **{target_channel.name}** ตลอดไป (ใช้ `/afk` อีกครั้งเพื่อปิด)")
        else:
            await self.save_voice_state(interaction.guild.id, vc.channel.id if vc else None)
            await interaction.followup.send(f"💤 **โหมด AFK ปิดใช้งาน:** บอทจะออกจากช่องนี้หากไม่มีเพลงเล่น (ตามเวลาปกติ)")

    @app_commands.command(name="สุ่ม", description="สุ่มคิวเพลง")
    async def shuffle(self, interaction: discord.Interaction):
        q = self.get_queue(interaction.guild.id)
        q.shuffle_enabled = not q.shuffle_enabled
        await self.save_voice_state(interaction.guild.id, interaction.guild.voice_client.channel.id if interaction.guild.voice_client else None)
        await interaction.response.send_message(f"🔀 สุ่มเพลง: {'เปิด' if q.shuffle_enabled else 'ปิด'}")

    @app_commands.command(name="วนซ้ำ", description="ตั้งค่าวนซ้ำ")
    @app_commands.choices(mode=[app_commands.Choice(name="ปิด", value="none"), app_commands.Choice(name="เพลงปัจจุบัน", value="track"), app_commands.Choice(name="คิวทั้งหมด", value="queue")])
    async def loop(self, interaction: discord.Interaction, mode: str):
        q = self.get_queue(interaction.guild.id)
        q.loop_mode = mode
        await self.save_voice_state(interaction.guild.id, interaction.guild.voice_client.channel.id if interaction.guild.voice_client else None)
        texts = {"none": "ปิด", "track": "เพลงปัจจุบัน", "queue": "คิวทั้งหมด"}
        await interaction.response.send_message(f"🔁 วนซ้ำ: {texts[mode]}")

    async def cog_unload(self):
        if hasattr(self, 'check_downloads'):
            self.check_downloads.cancel()
        
        # ถ้าเป็นการ Reload ระบบ (Maintenance) บอทจะไม่ตัดการเชื่อมต่อจากห้องเสียง
        if self.reload_in_progress:
            logger.info("[Music] Cog unloading for RELOAD - keeping voice connections alive.")
            return

        for g in self.bot.guilds:
            if g.voice_client: await g.voice_client.disconnect()


    @tasks.loop(seconds=2)
    async def check_downloads(self):
        """เช็คผลลัพธ์จาก Workers ทุก 2 วินาที"""
        if not self.shared_queue: return
        completed = []
        for task_id, info in list(self.pending_downloads.items()):
            result = await self.shared_queue.get_task_result(task_id, timeout=0)
            if result:
                if result.status == 'completed':
                    channel = self.bot.get_channel(info['channel_id'])
                    if channel:
                        title = result.result.get('title', 'Unknown')
                        duration = result.result.get('duration', 0)
                        await channel.send(f"✅ **{title}** ({duration//60}:{duration%60:02d}) พร้อมเล่นแล้ว! (ประมวลผลโดย Worker)")
                    completed.append(task_id)
                elif result.status == 'failed':
                    channel = self.bot.get_channel(info['channel_id'])
                    if channel: await channel.send(f"❌ ดาวน์โหลดล้มเหลว: {result.error}")
                    completed.append(task_id)
        for task_id in completed:
            del self.pending_downloads[task_id]

    @app_commands.command(name="play_distributed", description="เล่นเพลงแบบใช้ Worker ช่วย")
    @app_commands.describe(url="ลิงก์ YouTube")
    async def play_distributed(self, interaction: discord.Interaction, url: str):
        if not self.shared_queue:
            return await interaction.response.send_message("❌ Distributed mode ไม่เปิดใช้งาน", ephemeral=True)
        await interaction.response.defer(thinking=True)
        from core.shared_queue import Task
        task = Task(
            id=str(uuid.uuid4()), type='download',
            data={'url': url, 'output_path': './music/downloads', 'guild_id': interaction.guild_id, 'user_id': interaction.user.id},
            priority=0, shard_id=getattr(self.bot, 'shard_id', 0)
        )
        if await self.shared_queue.submit_task(task):
            self.pending_downloads[task.id] = {'channel_id': interaction.channel_id, 'user_id': interaction.user.id, 'url': url}
            await interaction.followup.send(f"🎵 ส่งคำขอดาวน์โหลดไปยัง Worker แล้ว!\nTask ID: `{task.id[:8]}`", ephemeral=False)
        else:
            await interaction.followup.send("❌ ไม่สามารถส่งงานไปยัง Worker ได้", ephemeral=True)

    @app_commands.command(name="queue_stats", description="ดูสถิติคิวงาน (Distributed Mode)")
    async def queue_stats(self, interaction: discord.Interaction):
        if not self.shared_queue:
            return await interaction.response.send_message("❌ Distributed mode ไม่เปิดใช้งาน", ephemeral=True)
        stats = await self.shared_queue.get_stats()
        embed = discord.Embed(title="📊 Task Queue Statistics", color=discord.Color.blue())
        for status, count in stats.items():
            embed.add_field(name=status.title(), value=f"{count} tasks", inline=True)
        embed.add_field(name="Your Pending", value=f"{len(self.pending_downloads)} downloads", inline=True)
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Music(bot))