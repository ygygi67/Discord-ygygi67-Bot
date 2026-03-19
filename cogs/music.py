import discord
from discord.ext import commands
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('music_cog')

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
        self.created_at = datetime.now(timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'title': self.title,
            'url': self.url,
            'duration': self.duration,
            'thumbnail': self.thumbnail,
            'webpage_url': self.webpage_url,
            'source': self.source,
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
    def __init__(self, bot):
        self.bot = bot
        self.queues: Dict[int, MusicQueue] = {}
        self.voice_state_file = 'data/music_state.json'
        
        if not os.path.exists('data'):
            os.makedirs('data')
        
    async def save_voice_state(self, guild_id: int, channel_id: Optional[int]):
        try:
            full_data = {}
            if os.path.exists(self.voice_state_file):
                with open(self.voice_state_file, 'r', encoding='utf-8') as f:
                    full_data = json.load(f)
            
            guild_id_str = str(guild_id)
            if channel_id:
                queue = self.get_queue(guild_id)
                full_data[guild_id_str] = {
                    'channel_id': channel_id,
                    'current_track': queue.current_track.to_dict() if queue.current_track else None,
                    'queue': [t.to_dict() for t in queue.tracks],
                    'loop': queue.loop_mode,
                    'shuffle': queue.shuffle_enabled,
                    'volume': queue.volume,
                    'filters': queue.filters,
                    'text_channel_id': queue.text_channel_id
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

    @commands.Cog.listener()
    async def on_ready(self):
        await asyncio.sleep(5) # Wait for guilds
        states = self.load_voice_states()
        for g_id, state in states.items():
            guild = self.bot.get_guild(int(g_id))
            if not guild: continue
            
            c_id = state['channel_id'] if isinstance(state, dict) else state
            channel = guild.get_channel(c_id)
            if channel and isinstance(channel, discord.VoiceChannel):
                try:
                    vc = await channel.connect()
                    if isinstance(state, dict):
                        queue = self.get_queue(guild.id)
                        queue.loop_mode = state.get('loop', 'none')
                        queue.shuffle_enabled = state.get('shuffle', False)
                        queue.volume = state.get('volume', 1.0)
                        queue.filters = state.get('filters', {"bassboost": False, "nightcore": False, "vaporwave": False})
                        queue.text_channel_id = state.get('text_channel_id')
                        
                        # Current track
                        curr = state.get('current_track')
                        if curr:
                            track = await self.search_track(curr.get('webpage_url') or curr.get('url'))
                            if track:
                                track.requester = guild.get_member(curr.get('requester_id'))
                                await self.play_track(vc, track)
                        
                        # Queue
                        for t_data in state.get('queue', []):
                            queue.tracks.append(MusicTrack.from_dict(t_data, guild))
                except Exception as e:
                    logger.error(f"Auto-resume failed for {guild.name}: {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot: return
        guild = member.guild
        vc = guild.voice_client
        if not vc: return

        # Follow logic
        if before.channel != after.channel and after.channel and vc.channel == before.channel:
            if not [m for m in before.channel.members if not m.bot]:
                if len([m for m in after.channel.members if not m.bot]) <= 1:
                    await vc.move_to(after.channel)
                    await self.save_voice_state(guild.id, after.channel.id)

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

    async def play_track(self, vc: discord.VoiceClient, track: MusicTrack, seek: float = 0):
        try:
            queue = self.get_queue(vc.guild.id)
            
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
            
            vc.play(discord.FFmpegPCMAudio(track.url, **opts), 
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
            await asyncio.sleep(300)
            if vc and not vc.is_playing() and not [m for m in vc.channel.members if not m.bot]:
                await vc.disconnect()
                await self.save_voice_state(guild.id, None)

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
    async def play(self, interaction: discord.Interaction, query: str):
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
        
        queue = self.get_queue(interaction.guild.id)
        pos = queue.add(track)
        
        if not vc.is_playing():
            next_t = queue.get_next()
            await self.play_track(vc, next_t)
            await self.send_now_playing(interaction.channel, next_t)
            await interaction.followup.send(f"✅ เริ่มเล่น: **{track.title}**")
        else:
            await self.save_voice_state(interaction.guild.id, vc.channel.id)
            await interaction.followup.send(f"✅ เพิ่มเข้าคิวที่ #{pos}: **{track.title}**")

    async def _process_playlist(self, interaction: discord.Interaction, query: str):
        try:
            with YoutubeDL({'extract_flat': 'in_playlist', 'quiet': True}) as ydl:
                info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(query, download=False, process=False))
                if not info or 'entries' not in info: return
                entries = list(info['entries'])
                queue = self.get_queue(interaction.guild.id)
                queue.text_channel_id = interaction.channel_id
                vc = interaction.guild.voice_client
                
                status_msg = await interaction.channel.send(f"🎶 เริ่มทยอยเพิ่มเพลย์ลิสต์จำนวน {len(entries)} เพลง...")
                
                for i, entry in enumerate(entries):
                    # Progress Update & ETA every 5 tracks
                    if i % 5 == 0:
                        remaining = len(entries) - i
                        # Approx 2s per track (search + sleep)
                        eta_sec = remaining * 2
                        eta_str = f"{eta_sec // 60} นาที {eta_sec % 60} วินาที" if eta_sec > 60 else f"{eta_sec} วินาที"
                        try:
                            await status_msg.edit(content=(
                                f"🎶 **กำลังเพิ่มเพลงลงคิว...** ({i+1}/{len(entries)})\n"
                                f"💿 **เพลงล่าสุด:** {entry.get('title', 'Unknown')[:50]}...\n"
                                f"⏳ **คาดว่าเสร็จสิ้นใน:** {eta_str}"
                            ))
                        except: pass

                    url = entry.get('url') or entry.get('webpage_url') or (f"https://www.youtube.com/watch?v={entry['id']}" if entry.get('id') else None)
                    if url:
                        track = await self.search_track(url)
                        if track:
                            track.requester = interaction.user
                            queue.add(track)
                            if i == 0 and not vc.is_playing():
                                next_t = queue.get_next()
                                await self.play_track(vc, next_t)
                                await self.send_now_playing(interaction.channel, next_t)
                    
                    if i % 10 == 0: await self.save_voice_state(interaction.guild.id, vc.channel.id)
                    await asyncio.sleep(1)
                
                await status_msg.edit(content=f"✅ เพิ่มเพลย์ลิสต์สำเร็จทั้งหมด **{len(entries)}** เพลง!")
        except Exception as e:
            logger.error(f"Playlist error: {e}")

    @app_commands.command(name="ข้าม", description="ข้ามเพลงปัจจุบัน")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
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
        for g in self.bot.guilds:
            if g.voice_client: await g.voice_client.disconnect()

async def setup(bot):
    await bot.add_cog(Music(bot))