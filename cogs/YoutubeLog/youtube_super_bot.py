import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import time
import requests
import os
import logging
import math
import statistics
import re
import sqlite3
import copy
import sys
import asyncio
from io import StringIO
from datetime import datetime, timedelta, timezone
from yt_dlp import YoutubeDL
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path

# ==========================================
# 🔇 Custom stderr filter สำหรับ yt-dlp
# ==========================================
class YtDlpFilter:
    def __init__(self):
        self.original_stderr = sys.stderr

    def write(self, text):
        skippable = [
            'This live event will begin',
            'live event will begin in',
            'Premieres in',
            'Scheduled for',
            'starts in',
            "Join this channel to get access to members-only content",
            "This video is available to this channel's members on level",
            "members-only content like this video",
            "exclusive perks"
        ]
        if any(err in text for err in skippable):
            return
        self.original_stderr.write(text)

    def flush(self):
        self.original_stderr.flush()

# ==========================================
# 🚀 CONFIGURATION
# ==========================================
# หมายเหตุ: ย้ายไฟล์ base directory ให้ตรงกับ structure ของบอทหลัก
BOT_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BOT_BASE_DIR, "data", "youtube_spy")
os.makedirs(DATA_DIR, exist_ok=True)

DB_FILE_NAME = os.path.join(DATA_DIR, "UltimateBot_Database_V9.json")
STATUS_FILE = os.path.join(DATA_DIR, "bot_status.json")
LOG_FILE = os.path.join(DATA_DIR, "youtube_bot.log")

# Webhooks for notifications (can be configured via env)
DISCORD_WEBHOOKS = [
    os.getenv('YOUTUBE_SPY_WEBHOOK', '')
]

MY_CHANNELS = ['UCmv8yCHA_JxyY2EsmBcveWA', 'UCBGNEsqD95IJ9mpaeMkp9RA', 'UCKsRTlYf1kXw-fuVtCeafYg']
SPY_CHANNELS = [
    '@Parmnitchan', '@FlukkCh', '@PondKunChannel', '@FordKunGCH',
    '@MyNameHENRY', '@ManamiNeko', '@HecateVT', '@hamikochannel',
    'UCxlUGqvk5JFI9EQI-qsqd1g', 'UCiJAhh95T2tO4loc12Qrftg', '@9arm',
    'UCbe-CsCcpjPBUpX-wChCFaQ', '@ibukich.1830', 'UC5RUJJL9lIVedWvYelN8jEg', '@MrBeast',
    '@OwenKz70', '@karosppm', '@GolfPPM', '@GOFtocktax'
]

NOTIFY_SETTINGS = {
    'minChannelViewsDiff': 100,
    'minVideoViewsDiff': 10,
    'minVideoLikesDiff': 1,
    'minVideoCommentsDiff': 1,
    'trackLatestChannelVideos': 5
}

ADVANCED_SETTINGS = {
    'maxPagesToFetch': 1,
    'deep_analysis': True,
    'anomaly_detection': True,
    'debug_mode': True,
    'retry_attempts': 3,
    'retry_delay': 5,
    'max_videos_per_channel': 100,
    'historical_days': 30,
    'stats_window': 7
}

ANOMALY_THRESHOLDS = {
    'view_spike_multiplier': 5.0,
    'sub_spike_multiplier': 3.0,
    'upload_burst_threshold': 10,
    'view_drop_threshold': 0.5,
    'sub_drop_threshold': 0.02
}

SQL_SETTINGS = {
    'enable': os.getenv('YOUTUBE_SPY_SQL_ENABLE', 'False').lower() == 'true',
    'host': os.getenv('YOUTUBE_SPY_SQL_HOST', ''),
    'port': int(os.getenv('YOUTUBE_SPY_SQL_PORT', '4000')),
    'database': os.getenv('YOUTUBE_SPY_SQL_DB', 'test'),
    'user': os.getenv('YOUTUBE_SPY_SQL_USER', ''),
    'password': os.getenv('YOUTUBE_SPY_SQL_PASSWORD', ''),
    'table_name': os.getenv('YOUTUBE_SPY_SQL_TABLE', 'youtube_log')
}

# Logger setup
logger = logging.getLogger('youtube_spy')
logger.setLevel(logging.DEBUG if ADVANCED_SETTINGS['debug_mode'] else logging.INFO)

# ==========================================
# 🗄️ Database & Helpers
# ==========================================
def _default_snapshot() -> dict:
    return {"channels": {}, "latestUploads": {}, "playlists": {}, "channelVideosStats": {}, "videos": {}, "idCache": {}}

def load_snapshot() -> dict:
    if os.path.exists(DB_FILE_NAME):
        try:
            with open(DB_FILE_NAME, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for key, val in _default_snapshot().items():
                    data.setdefault(key, val)
                return data
        except: pass
    return _default_snapshot()

def save_snapshot(snapshot: dict):
    with open(DB_FILE_NAME, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

def load_bot_status() -> dict:
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {}

def save_bot_status(status: dict):
    with open(STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

def save_to_external_sql(channel_data_array: list):
    if not SQL_SETTINGS['enable'] or not channel_data_array:
        return
    try:
        import pymysql
        conn = pymysql.connect(
            host=SQL_SETTINGS['host'], port=SQL_SETTINGS['port'],
            user=SQL_SETTINGS['user'], password=SQL_SETTINGS['password'],
            database=SQL_SETTINGS['database'], ssl={'ssl': {}}, charset='utf8mb4'
        )
        cursor = conn.cursor()
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {SQL_SETTINGS['table_name']} (id INT AUTO_INCREMENT PRIMARY KEY, timestamp DATETIME, channel_id VARCHAR(50), channel_name VARCHAR(100), subscriber_count INT, view_count BIGINT, video_count INT)")
        now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        for data in channel_data_array:
            cursor.execute(f"INSERT INTO {SQL_SETTINGS['table_name']} (timestamp, channel_id, channel_name, subscriber_count, view_count, video_count) VALUES (%s, %s, %s, %s, %s, %s)", (now, data['id'], data['name'], data['subs'], data['views'], data['vids']))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"SQL Error: {e}")

def send_advanced_discord(embed_obj: dict):
    payload = {"embeds": [embed_obj]}
    for webhook in DISCORD_WEBHOOKS:
        try:
            requests.post(webhook.strip(), json=payload, timeout=15)
        except: pass

def f_diff(num: int) -> str:
    return f"+{num:,}" if num > 0 else f"{num:,}" if num < 0 else "0"

def trunc_title(s: str, max_length: int = 55) -> str:
    return (s[:max_length] + "...") if s and len(s) > max_length else (s or "ไม่มีชื่อ")

# ==========================================
# 🔍 Analysis & Fetching
# ==========================================
def analyze_channel_patterns(videos: List[Dict]) -> Dict:
    if not videos: return {}
    analysis = {'avg_video_duration': 0, 'upload_frequency': 0, 'most_common_category': 'Unknown', 'engagement_rate': 0, 'video_performance_variance': 0}
    try:
        durations = [v.get('duration', 0) for v in videos if v.get('duration', 0) > 0]
        if durations: analysis['avg_video_duration'] = statistics.mean(durations)
        upload_dates = []
        for v in videos:
            if v.get('upload_date'):
                try: upload_dates.append(datetime.strptime(v['upload_date'], '%Y%m%d'))
                except: continue
        if len(upload_dates) > 1:
            upload_dates.sort(reverse=True)
            date_range = (upload_dates[0] - upload_dates[-1]).days
            if date_range > 0: analysis['upload_frequency'] = len(upload_dates) / date_range
        categories = [v.get('category', 'Unknown') for v in videos]
        if categories: analysis['most_common_category'] = max(set(categories), key=categories.count)
        total_views = sum(v.get('views', 0) for v in videos)
        total_likes = sum(v.get('like_count', 0) for v in videos)
        total_comments = sum(v.get('comment_count', 0) for v in videos)
        if total_views > 0: analysis['engagement_rate'] = (total_likes + total_comments) / total_views * 100
        view_counts = [v.get('views', 0) for v in videos if v.get('views', 0) > 0]
        if len(view_counts) > 1: analysis['video_performance_variance'] = statistics.stdev(view_counts) / statistics.mean(view_counts) * 100
    except: pass
    return analysis

def detect_anomalies(current_data: Dict, historical_data: Dict, channel_name: str) -> List[Dict]:
    anomalies = []
    if not ADVANCED_SETTINGS['anomaly_detection']: return anomalies
    try:
        cs, hs = current_data.get('subs', 0), historical_data.get('subs', 0)
        if hs > 0:
            rate = (cs - hs) / hs
            if rate > ANOMALY_THRESHOLDS['sub_spike_multiplier']: anomalies.append({'type': 'spike', 'description': f"ผู้ติดตามพุ่งขึ้น {rate:.1%}"})
            elif rate < -ANOMALY_THRESHOLDS['sub_drop_threshold']: anomalies.append({'type': 'drop', 'description': f"ผู้ติดตามลดลง {abs(rate):.1%}"})
        cv, hv = current_data.get('views', 0), historical_data.get('views', 0)
        if hv > 0:
            rate = (cv - hv) / hv
            if rate > ANOMALY_THRESHOLDS['view_spike_multiplier']: anomalies.append({'type': 'spike', 'description': f"วิวพุ่งขึ้น {rate:.1%}"})
            elif rate < -ANOMALY_THRESHOLDS['view_drop_threshold']: anomalies.append({'type': 'drop', 'description': f"วิวลดลง {abs(rate):.1%}"})
    except: pass
    return anomalies

class SilentLogger:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass

def _ydl_extract_video(video_id: str) -> Optional[Dict]:
    try:
        with YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True, 'ignoreerrors': True, 'logger': SilentLogger()}) as ydl:
            return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    except: return None

def get_channel_data(channel_input: str) -> Optional[Dict]:
    base = f"https://www.youtube.com/channel/{channel_input}" if not channel_input.startswith('@') else f"https://www.youtube.com/{channel_input}"
    candidate_urls = [base + "/videos", base + "/shorts", base]
    flat_opts = {
        'quiet': True, 
        'no_warnings': True, 
        'extract_flat': 'in_playlist', 
        'playlist_items': f"1-{ADVANCED_SETTINGS['max_videos_per_channel']}", 
        'ignoreerrors': True, 
        'skip_download': True,
        'logger': SilentLogger()
    }
    
    for attempt in range(ADVANCED_SETTINGS['retry_attempts']):
        try:
            info, used_url = None, None
            for url in candidate_urls:
                with YoutubeDL(flat_opts) as ydl:
                    res = ydl.extract_info(url, download=False)
                    if res and (res.get('entries') or res.get('id')):
                        info, used_url = res, url; break
            if not info: continue

            flat_videos = []
            for v in (info.get('entries', []) or []):
                if not v or v.get('is_upcoming'): continue
                flat_videos.append({
                    'id': v['id'], 'title': v.get('title') or 'Untitled', 'views': v.get('view_count') or 0,
                    'url': f"https://youtu.be/{v['id']}", 'duration': v.get('duration') or 0,
                    'upload_date': v.get('upload_date'), 'like_count': v.get('like_count') or 0,
                    'comment_count': v.get('comment_count') or 0, 'description': '', 'category': 'Unknown'
                })

            n_deep = NOTIFY_SETTINGS['trackLatestChannelVideos']
            for i, vid in enumerate(flat_videos[:n_deep]):
                deep = _ydl_extract_video(vid['id'])
                if deep:
                    vid.update({'views': deep.get('view_count', vid['views']), 'like_count': deep.get('like_count', 0), 'comment_count': deep.get('comment_count', 0), 'description': (deep.get('description') or '')[:500], 'title': deep.get('title', vid['title'])})
                    cats = deep.get('categories') or []
                    vid['category'] = cats[0] if cats else 'Unknown'

            metadata = {
                'id': info.get('channel_id') or info.get('id'), 'name': info.get('channel') or info.get('uploader') or info.get('title') or 'Unknown',
                'description': (info.get('description') or '')[:500], 'subs': info.get('channel_follower_count') or 0,
                'views': info.get('view_count') or 0, 'url': info.get('channel_url') or info.get('webpage_url'),
                'thumbnail': info.get('thumbnails', [{}])[-1].get('url', ''), 'videos': flat_videos, 'total_videos': info.get('playlist_count') or len(flat_videos)
            }
            if ADVANCED_SETTINGS['deep_analysis'] and flat_videos: metadata.update(analyze_channel_patterns(flat_videos))
            return metadata
        except Exception as e:
            if attempt < ADVANCED_SETTINGS['retry_attempts'] - 1: time.sleep(ADVANCED_SETTINGS['retry_delay'] * (2**attempt))
    return None

def is_notification_window() -> bool:
    m = datetime.now().minute
    return m <= 10 or m >= 50

# ==========================================
# 🤖 Discord Cog
# ==========================================
class YoutubeSpyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.is_scanning = False
        self.spy_loop.start()

    def cog_unload(self):
        self.spy_loop.cancel()

    @tasks.loop(minutes=10)
    async def spy_loop(self):
        if self.is_scanning:
            return
        await self.run_scan()

    async def run_scan(self, force_notify=False):
        # รันใน thread แยกเพื่อไม่ให้บล็อก bot หลัก
        if self.is_scanning:
            return
        return await asyncio.to_thread(self._do_scan, force_notify)

    def _do_scan(self, force_notify=False):
        if self.is_scanning:
            return
        self.is_scanning = True
        try:
            logger.info("🚀 Starting scan...")
            status = load_bot_status()
            is_first = status.get('IS_INITIALIZED') != 'TRUE'
            in_window = is_notification_window() or force_notify

            if is_first:
                status['IS_INITIALIZED'] = 'TRUE'
                save_bot_status(status)

            current_snapshot = load_snapshot()
            last_data = copy.deepcopy(current_snapshot)
            sql_data = []

            targets = [{'input': c, 'type': 'MY'} for c in MY_CHANNELS] + [{'input': c, 'type': 'SPY'} for c in SPY_CHANNELS]
            
            for idx, target in enumerate(targets, 1):
                data = get_channel_data(target['input'])
                if not data: continue
                
                ch_id = data['id']
                is_my = target['type'] == 'MY'
                sql_data.append({'id': ch_id, 'name': data['name'], 'subs': data['subs'], 'views': data['views'], 'vids': data['total_videos']})

                current_snapshot['channels'].setdefault(ch_id, {})
                old_ch = last_data['channels'].get(ch_id, data)
                
                fields = []
                # ตรวจสอบการเปลี่ยนชื่อ
                if old_ch.get('name') and old_ch['name'] != data['name']:
                    fields.append({"name": "✏️ เปลี่ยนชื่อช่อง!", "value": f"> ❌ {old_ch['name']}\n> ✅ {data['name']}", "inline": False})
                
                # ตรวจสอบสถิติ
                sub_diff = data['subs'] - old_ch.get('subs', 0)
                view_diff = data['views'] - old_ch.get('views', 0)
                if sub_diff != 0 or view_diff >= NOTIFY_SETTINGS['minChannelViewsDiff']:
                    fields.append({"name": "📊 สถิติ", "value": f"👥 ผู้ติดตาม: {data['subs']:,} ({f_diff(sub_diff)})\n👁️ วิวรวม: {data['views']:,} ({f_diff(view_diff)})", "inline": False})

                # ตรวจสอบคลิปใหม่
                current_snapshot['latestUploads'].setdefault(ch_id, {})
                old_uploads = current_snapshot['latestUploads'][ch_id]
                current_uploads = {v['id']: v['title'] for v in data['videos']}
                
                new_vids = [f"> 🔗 [{t}](https://youtu.be/{i})" for i, t in current_uploads.items() if i not in old_uploads]
                if new_vids:
                    fields.append({"name": "🎬 อัปโหลดใหม่!", "value": "\n".join(new_vids[:10]), "inline": False})
                
                current_snapshot['latestUploads'][ch_id].update(current_uploads)
                current_snapshot['channels'][ch_id] = {'subs': data['subs'], 'views': data['views'], 'name': data['name'], 'vids': data['total_videos']}

                if fields and in_window:
                    report = {
                        "author": {"name": data['name'], "url": data['url'], "icon_url": data['thumbnail']},
                        "title": "🕵️ ข้อมูลสอดแนม" if not is_my else "🛡️ อัปเดตช่องของคุณ",
                        "color": 15158332 if not is_my else 3447003,
                        "fields": fields,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "footer": {"text": "YouTube Spy V9"}
                    }
                    send_advanced_discord(report)

            save_snapshot(current_snapshot)
            save_to_external_sql(sql_data)
        except Exception as e:
            logger.error(f"Scan error: {e}")
        finally:
            self.is_scanning = False
            logger.info("Scan completed.")

    @app_commands.command(name="youtube-spy", description="จัดการระบบสอดแนม YouTube")
    @app_commands.choices(action=[
        app_commands.Choice(name="สแกนทันที (Manual Scan)", value="scan"),
        app_commands.Choice(name="ดูสถานะปัจจุบัน (Status)", value="status"),
        app_commands.Choice(name="รีเซ็ตฐานข้อมูล (Reset DB)", value="reset")
    ])
    async def yt_spy(self, interaction: discord.Interaction, action: str):
        if action == "scan":
            await interaction.response.send_message("🔍 กำลังเริ่มการสแกนเชิงลึก... (อาจใช้เวลา 1-2 นาที)", ephemeral=True)
            await self.run_scan(force_notify=True)
            await interaction.followup.send("✅ สแกนเสร็จสิ้น! บันทึกข้อมูลและส่งแจ้งเตือนเรียบร้อย", ephemeral=True)
        elif action == "status":
            snap = load_snapshot()
            channels = snap.get('channels', {})
            msg = f"📊 **สถานะระบบสอดแนม**\n"
            msg += f"• จำนวนช่องที่ติดตาม: {len(channels)} ช่อง\n"
            msg += f"• สแกนล่าสุดเมื่อ: {datetime.now().strftime('%H:%M:%S')}\n"
            msg += f"• ช่วงเวลาแจ้งเตือน: {'เปิด' if is_notification_window() else 'ปิด (รอต้นชั่วโมง)'}"
            await interaction.response.send_message(msg)
        elif action == "reset":
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message("❌ เฉพาะแอดมินเท่านั้นที่รีเซ็ตได้", ephemeral=True)
            if os.path.exists(DB_FILE_NAME): os.remove(DB_FILE_NAME)
            await interaction.response.send_message("🧹 รีเซ็ตฐานข้อมูลเรียบร้อยแล้ว!")

async def setup(bot):
    await bot.add_cog(YoutubeSpyCog(bot))