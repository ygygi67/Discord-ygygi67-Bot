import discord
from discord.ext import commands
from discord import app_commands
import sys
import subprocess
import os
import platform
import random
import time
from datetime import datetime
import re
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import urllib.request
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import threading
import queue
import mimetypes
import urllib.parse
import shutil

class DownloadVideoCog(commands.Cog, name="DownloadVideo"):
    def __init__(self, bot):
        self.bot = bot

async def setup(bot):
    await bot.add_cog(DownloadVideoCog(bot))

def auto_update_yt_dlp():
    try:
        print("Checking for yt-dlp updates...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("yt-dlp is up to date!")
    except Exception as e:
        print(f"Warning: Could not auto-update yt-dlp: {e}")

def ensure_yt_dlp():
    try:
        import yt_dlp
        return yt_dlp
    except ModuleNotFoundError:
        print("yt-dlp not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp"])
        print("yt-dlp installed. Continuing...")
        import yt_dlp
        return yt_dlp

def ensure_mutagen():
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import ID3, APIC, error as ID3Error
        import requests
        return EasyID3, ID3, APIC, ID3Error, requests
    except ModuleNotFoundError:
        print("mutagen not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "mutagen", "requests"])
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import ID3, APIC, error as ID3Error
        import requests
        return EasyID3, ID3, APIC, ID3Error, requests

auto_update_yt_dlp()
yt_dlp = ensure_yt_dlp()
EasyID3, ID3, APIC, ID3Error, requests = ensure_mutagen()

def log_result(message):
    with open("download_log.txt", "a", encoding="utf-8") as logf:
        logf.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")

def is_empty_file(filepath):
    return os.path.exists(filepath) and os.path.getsize(filepath) == 0

def embed_metadata_mp3(filename, info, url=None):
    try:
        audio = EasyID3(filename)
    except ID3Error:
        audio = EasyID3()
    audio['title'] = info.get('title', '')
    if info.get('artist'):
        audio['artist'] = info['artist']
    if info.get('album'):
        audio['album'] = info['album']
    if info.get('composer'):
        audio['composer'] = info['composer']
    if url:
        try:
            audio['comment'] = url
        except Exception:
            try:
                audio['description'] = url
            except Exception:
                pass
    audio.save(filename)
    # Add cover art
    if info.get('thumbnail'):
        try:
            img_data = requests.get(info['thumbnail']).content
            audio = ID3(filename)
            audio.add(APIC(
                encoding=3,
                mime='image/jpeg',
                type=3,
                desc='Cover',
                data=img_data
            ))
            audio.save(filename)
            print("🎵 Embedded cover art and metadata into MP3.")
        except Exception:
            print("⚠️  Could not embed cover art.")
    else:
        print("🎵 Embedded metadata into MP3 (no cover art found).")

def get_download_mode():
    mode = input("Download mode: [v]ideo (default) or [a]udio only? (v/a): ").strip().lower()
    return mode == 'a'

def get_download_folder():
    def_folder = 'D:/Downloader'
    folder = input(f"Download folder (default: {def_folder}): ").strip() or def_folder
    os.makedirs(folder, exist_ok=True)
    return folder

def progress_hook(d):
    if d['status'] == 'downloading':
        print(f"  Downloading: {d.get('filename', '')} | {d.get('downloaded_bytes', 0) / 1024 / 1024:.2f} MB", end='\r')
    elif d['status'] == 'finished':
        print(f"  Finished: {d.get('filename', '')}")
        beep()

def ask_for_links():
    supported_sites = [
        "YouTube", "Bilibili", "Bluesky", "Dailymotion", "Facebook", "Instagram", "Loom", "OK.ru", "Pinterest",
        "Reddit", "Rutube", "Snapchat", "SoundCloud", "Streamable", "TikTok", "Tumblr", "Twitch clips", "Twitter/X",
        "Vimeo", "VK", "Xiaohongshu"
    ]
    print("\nSupported sites:")
    print(", ".join(supported_sites))
    print("Paste links from any of the above sites, one per line. Press Enter on an empty line to finish:")
    links = []
    while True:
        line = input()
        if not line.strip():
            break
        links.append(line.strip())
    return links

def is_tiktok_photo_post(url):
    return "tiktok.com" in url and "/photo/" in url

def download_tiktok_photo_post(url, download_folder, chromedriver_path=None):
    print(f"🔎 Attempting to download images from TikTok photo post: {url}")
    if not chromedriver_path:
        chromedriver_path = get_chromedriver_path()
    if not chromedriver_path or not os.path.exists(chromedriver_path):
        print_warning("chromedriver not found. Please install the correct version for your Chrome.")
        return False
    try:
        service = Service(chromedriver_path)
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        driver = webdriver.Chrome(service=service, options=options)

        print(f"Loading {url} ...")
        driver.get(url)
        time.sleep(5)  # Wait for page to load

        # Try to scroll to load more images (simulate user interaction)
        for _ in range(3):
            driver.execute_script("window.scrollBy(0, 500);")
            time.sleep(1)

        # Wait for at least one image to be present
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "img"))
        )

        images = driver.find_elements(By.TAG_NAME, "img")

        os.makedirs(download_folder, exist_ok=True)

        downloaded = set()
        img_count = 0
        for i, img in enumerate(images):
            src = img.get_attribute('src')
            # Filter: only http(s) images, not base64, not already downloaded, and likely large
            if src and src.startswith('http') and src not in downloaded and not src.startswith("data:"):
                # Optionally, filter by size (skip very small images)
                try:
                    # Get image size (in bytes) before downloading
                    with urllib.request.urlopen(src) as u:
                        info = u.info()
                        size = int(info.get("Content-Length", 0))
                    if size < 20 * 1024:  # Skip images smaller than 20KB (likely icons)
                        continue
                    filename = os.path.join(download_folder, f"tiktok_photo_{img_count+1}.jpg")
                    urllib.request.urlretrieve(src, filename)
                    print(f"Downloaded {filename} ({size/1024:.1f} KB)")
                    downloaded.add(src)
                    img_count += 1
                except Exception as e:
                    print(f"Failed to download {src}: {e}")

        driver.quit()
        print(f"✅ Downloaded {img_count} images.")
        return img_count > 0
    except Exception as e:
        print(f"❌ Error downloading TikTok photo post images: {e}")
        return False

def print_warning(msg):
    # Yellow color (ANSI) + emoji
    print(f"\033[93m⚠️  {msg}\033[0m")

def extract_playlist_id(url):
    m = re.search(r'[?&]list=([a-zA-Z0-9_-]+)', url)
    return m.group(1) if m else None

def is_image_url(url):
    image_exts = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg')
    parsed = urllib.parse.urlparse(url)
    if any(parsed.path.lower().endswith(ext) for ext in image_exts):
        return True
    return False

def download_image(url, download_folder):
    from urllib.parse import unquote, urlparse
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path)
    if not filename:
        filename = 'image'
    base, ext = os.path.splitext(filename)
    i = 1
    outname = filename
    while os.path.exists(os.path.join(download_folder, outname)):
        outname = f'{base}_{i}{ext}'
        i += 1
    outpath = os.path.join(download_folder, outname)
    try:
        urllib.request.urlretrieve(url, outpath)
        print(f"Downloaded image: {outpath}")
        log_result(f"SUCCESS: {url} | Downloaded image: {outpath}")
    except Exception as e:
        print(f"❌ Error downloading image {url}: {e}")
        log_result(f"FAILED: {url} | {e}")

def get_os_type():
    plat = sys.platform
    if plat.startswith('win'):
        return 'windows'
    elif plat == 'darwin':
        return 'mac'
    elif plat.startswith('linux'):
        return 'linux'
    return 'unknown'

def get_ffmpeg_location():
    ffmpeg_path = shutil.which('ffmpeg')
    if ffmpeg_path:
        return ffmpeg_path
    os_type = get_os_type()
    possible = []
    if os_type == 'windows':
        possible = [
            os.path.join(os.getcwd(), 'ffmpeg.exe'),
            'C:/ffmpeg/bin/ffmpeg.exe',
            'C:/Program Files/ffmpeg/bin/ffmpeg.exe',
            'C:/Program Files (x86)/ffmpeg/bin/ffmpeg.exe',
        ]
    elif os_type == 'mac':
        possible = [
            '/usr/local/bin/ffmpeg',
            '/opt/homebrew/bin/ffmpeg',
        ]
    elif os_type == 'linux':
        possible = [
            '/usr/bin/ffmpeg',
            '/usr/local/bin/ffmpeg',
        ]
    for p in possible:
        if os.path.exists(p):
            return p
    return None

def get_aria2c_path():
    aria2c = shutil.which('aria2c')
    if aria2c:
        return aria2c
    os_type = get_os_type()
    if os_type == 'windows':
        possible = [
            os.path.join(os.getcwd(), 'aria2c.exe'),
            'C:/Program Files/Aria2/aria2c.exe',
            'C:/Program Files (x86)/Aria2/aria2c.exe',
        ]
    else:
        possible = ['/usr/bin/aria2c', '/usr/local/bin/aria2c']
    for p in possible:
        if os.path.exists(p):
            return p
    return None

def get_chromedriver_path():
    os_type = get_os_type()
    if os_type == 'windows':
        exe = 'chromedriver.exe'
    else:
        exe = 'chromedriver'
    local_path = os.path.join(os.getcwd(), exe)
    if os.path.exists(local_path):
        return local_path
    # Try to auto-download if not found
    try:
        import urllib.request, zipfile
        print("🔎 Downloading ChromeDriver automatically...")
        if os_type == 'windows':
            url = 'https://storage.googleapis.com/chrome-for-testing-public/124.0.6367.91/win32/chromedriver-win32.zip'
            zipname = 'chromedriver.zip'
            dirname = 'chromedriver-win32'
        elif os_type == 'mac':
            url = 'https://storage.googleapis.com/chrome-for-testing-public/124.0.6367.91/mac-x64/chromedriver-mac-x64.zip'
            zipname = 'chromedriver.zip'
            dirname = 'chromedriver-mac-x64'
        elif os_type == 'linux':
            url = 'https://storage.googleapis.com/chrome-for-testing-public/124.0.6367.91/linux64/chromedriver-linux64.zip'
            zipname = 'chromedriver.zip'
            dirname = 'chromedriver-linux64'
        else:
            print_warning("This operating system is not supported for automatic ChromeDriver download")
            return None
        urllib.request.urlretrieve(url, zipname)
        with zipfile.ZipFile(zipname, 'r') as zip_ref:
            zip_ref.extractall('.')
        driver_path = os.path.join(os.getcwd(), dirname, exe)
        if os.path.exists(driver_path):
            shutil.move(driver_path, local_path)
        shutil.rmtree(dirname, ignore_errors=True)
        os.remove(zipname)
        if os.path.exists(local_path):
            print(f"✅ ChromeDriver ready: {local_path}")
            return local_path
    except Exception as e:
        print_warning(f"Automatic ChromeDriver download failed: {e}")
    return None

def get_cookies_option():
    # Try auto-detect cookies file in script directory
    auto_cookie = os.path.join(os.path.dirname(os.path.abspath(__file__)), "www.youtube.com_cookies.txt")
    if os.path.exists(auto_cookie):
        print(f"\n🔑 Found cookies file: {auto_cookie} (using automatically)")
        return {'cookiefile': auto_cookie}
    # If not found, ask user as before
    print("\nIf you want to download private/restricted videos, you need to provide cookies.")
    print("You can export cookies from your browser using an extension like 'Get cookies.txt' or use --cookies-from-browser.")
    print("Leave blank if you don't need this.")
    print("Example for Chrome: chrome (or chromium, edge, firefox, opera, brave)")
    cookies_file = input("Path to cookies.txt file (or type browser name for --cookies-from-browser): ").strip()
    if not cookies_file:
        return None
    if cookies_file.lower() in ['chrome', 'chromium', 'edge', 'firefox', 'opera', 'brave']:
        return {'cookiesfrombrowser': cookies_file.lower()}
    return {'cookiefile': cookies_file}

def get_fast_ydl_opts(download_folder, audio_only, ffmpeg_path=None):
    aria2c_path = get_aria2c_path()
    external_downloader = 'aria2c' if aria2c_path else None
    external_downloader_args = ['-x', '16', '-s', '16', '-k', '5M'] if aria2c_path else None
    common_opts = {
        'outtmpl': os.path.join(download_folder, '%(title)s.%(ext)s'),
        'quiet': False,
        'progress_hooks': [progress_hook],
        'no_check_certificate': True,
        'ignoreerrors': True,
        'concurrent_fragments': 200,
        'fragment_retries': 5,
        'retries': 5,
        'socket_timeout': 60,
        'http_chunk_size': 50*1024*1024,  # 50MB
        'buffersize': 32768,
        'n_threads': 8,
    }
    if ffmpeg_path:
        common_opts['ffmpeg_location'] = ffmpeg_path
    if external_downloader:
        common_opts['external_downloader'] = external_downloader
        common_opts['external_downloader_args'] = external_downloader_args
    if audio_only:
        common_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:
        common_opts.update({
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
            'writesubtitles': False,
            'writeautomaticsub': False,
            'prefer_ffmpeg': True,
            'keepvideo': False,
        })
    return common_opts

def download_worker(q, download_folder, cookies_opts=None):
    while True:
        item = q.get()
        if item is None:
            break
        url, opts = item
        mode = opts.get('mode')
        # --- Image support ---
        if is_image_url(url):
            download_image(url, download_folder)
            q.task_done()
            continue
        audio_only = (mode == 'mp3')
        ffmpeg_path = get_ffmpeg_location()
        ydl_opts = get_fast_ydl_opts(download_folder, audio_only, ffmpeg_path)
        if opts.get('start') or opts.get('end'):
            args = []
            if opts.get('start'):
                args += ['-ss', opts['start']]
            if opts.get('end'):
                args += ['-to', opts['end']]
            ydl_opts['postprocessor_args'] = args
        # เพิ่ม cookies option ถ้ามี
        if cookies_opts:
            ydl_opts.update(cookies_opts)
        try:
            playlist_id = extract_playlist_id(url)
            if playlist_id:
                playlist_url = f'https://www.youtube.com/playlist?list={playlist_id}'
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        playlist_info = ydl.extract_info(playlist_url, download=False)
                except Exception as playlist_error:
                    error_msg = str(playlist_error)
                    if "playlist does not exist" in error_msg.lower() or "the playlist does not exist" in error_msg.lower():
                        print_warning(f"Playlist {playlist_id} does not exist or has been removed")
                        print("👉 Downloading single video instead...")
                        # Fall back to single video download
                        playlist_id = None
                        playlist_info = None
                    else:
                        raise playlist_error
                
                # If playlist_id is None after error handling, skip playlist logic
                if not playlist_id:
                    # Continue to single video download logic
                    pass
                else:
                    # Ensure playlist_info exists before using it
                    if playlist_info is None:
                        print_warning("Cannot load playlist information")
                        q.task_done()
                        continue
                    
                    playlist_title = playlist_info.get('title', 'Untitled Playlist').strip().replace('/', '_').replace('\\', '_')
                    playlist_folder = os.path.join(download_folder, playlist_title)
                    os.makedirs(playlist_folder, exist_ok=True)
                    single_ydl_opts = ydl_opts.copy()
                    single_ydl_opts['outtmpl'] = os.path.join(playlist_folder, '%(title)s.%(ext)s')
                    with yt_dlp.YoutubeDL(single_ydl_opts) as single_ydl:
                        info = single_ydl.extract_info(url, download=False)
                        print(f"\n🎬 Title: {info.get('title', 'Unknown')}")
                        print(f"📺 Channel: {info.get('uploader', info.get('channel', 'Unknown'))}")
                        print(f"📅 Published on: {info.get('upload_date', 'Unknown')}")
                        duration = info.get('duration')
                        if duration:
                            mins, secs = divmod(duration, 60)
                            print(f"⏱️ Duration: {mins}m {secs}s")
                        filesize = info.get('filesize') or info.get('filesize_approx')
                        if filesize:
                            print(f"💾 Filesize: {filesize/1024/1024:.2f} MB")
                        resolution = info.get('resolution') or (f"{info.get('width')}x{info.get('height')}" if info.get('width') and info.get('height') else None)
                        if resolution:
                            print(f"🖼️ Resolution: {resolution}")
                        vformat = info.get('ext') or info.get('format')
                        if vformat:
                            print(f"📦 Format: {vformat}")
                        print("📥 Downloading in MAXIMUM QUALITY...")
                        single_ydl.download([url])
                        filename = single_ydl.prepare_filename(info)
                        if audio_only:
                            filename = os.path.splitext(filename)[0] + '.mp3'
                        if is_empty_file(filename):
                            msg = f"The downloaded file for '{info.get('title', 'Unknown')}' is empty. It may be protected or unavailable."
                            print_warning(msg)
                            print("👉 This might be a website limitation, not a program error. Try other links, update yt-dlp, or check https://github.com/yt-dlp/yt-dlp/issues\n")
                            os.remove(filename)
                            log_result(f"FAILED: {url} | {msg}")
                        else:
                            print("✅ Download complete at MAXIMUM QUALITY!\n")
                            log_result(f"SUCCESS: {url} | {info.get('title', 'Unknown')}")
                            if audio_only:
                                embed_metadata_mp3(filename, info, url)
                    entries = playlist_info.get('entries', [])
                    entries = [entry for entry in entries if entry.get('id') != info.get('id')]
                    if not entries:
                        q.task_done()
                        continue
                    print(f"\nPlaylist: {playlist_title} has {len(entries)} more videos:")
                    for idx, entry in enumerate(entries):
                        print(f"{idx+1}. {entry.get('title', 'Untitled')} [{entry.get('id', '')}]")
                    print("\nDo you want to download more videos from this playlist?")
                    print("1 = Select videos, 2 = Download all, Enter = Skip")
                    sel = input("Select: ").strip()
                    if sel == '2':
                        playlist_ydl_opts = ydl_opts.copy()
                        playlist_ydl_opts['outtmpl'] = os.path.join(playlist_folder, '%(title)s.%(ext)s')
                        with yt_dlp.YoutubeDL(playlist_ydl_opts) as playlist_ydl:
                            playlist_ydl.download([playlist_url])
                        log_result(f"SUCCESS: {playlist_url} | Downloaded all videos in playlist: {playlist_title}")
                    elif sel == '1':
                        nums = input("Enter the video numbers you want to download (separated by ,): ").strip()
                        try:
                            indices = [int(s.strip())-1 for s in nums.split(',') if s.strip().isdigit()]
                            selected_entries = [entries[i] for i in indices if 0 <= i < len(entries)]
                            playlist_ydl_opts = ydl_opts.copy()
                            playlist_ydl_opts['outtmpl'] = os.path.join(playlist_folder, '%(title)s.%(ext)s')
                            with yt_dlp.YoutubeDL(playlist_ydl_opts) as playlist_ydl:
                                for entry in selected_entries:
                                    playlist_ydl.download([entry.get('webpage_url')])
                                    log_result(f"SUCCESS: {entry.get('webpage_url')} | {entry.get('title', 'Unknown')}")
                        except Exception:
                            print_warning("Invalid video selection. Skipping...")
                    q.task_done()
                    continue
            # --- Single video logic ---
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                is_live = info.get('is_live') or info.get('was_live')
                if is_live:
                    print_warning("This video is Live or has just ended. It may not be downloadable until the Live stream is over or YouTube has finished processing.")
                print(f"\n🎬 Title: {info.get('title', 'Unknown')}")
                print(f"📺 Channel: {info.get('uploader', info.get('channel', 'Unknown'))}")
                print(f"📅 Published on: {info.get('upload_date', 'Unknown')}")
                duration = info.get('duration')
                if duration:
                    mins, secs = divmod(duration, 60)
                    print(f"⏱️ Duration: {mins}m {secs}s")
                filesize = info.get('filesize') or info.get('filesize_approx')
                if filesize:
                    print(f"💾 Filesize: {filesize/1024/1024:.2f} MB")
                resolution = info.get('resolution') or (f"{info.get('width')}x{info.get('height')}" if info.get('width') and info.get('height') else None)
                if resolution:
                    print(f"🖼️ Resolution: {resolution}")
                vformat = info.get('ext') or info.get('format')
                if vformat:
                    print(f"📦 Format: {vformat}")
                print("📥 Downloading in MAXIMUM QUALITY...")
                ydl.download([url])
                filename = ydl.prepare_filename(info)
                if audio_only:
                    filename = os.path.splitext(filename)[0] + '.mp3'
                if is_empty_file(filename):
                    msg = f"The downloaded file for '{info.get('title', 'Unknown')}' is empty. It may be protected or unavailable."
                    print_warning(msg)
                    print("👉 This might be a website limitation, not a program error. Try other links, update yt-dlp, or check https://github.com/yt-dlp/yt-dlp/issues\n")
                    os.remove(filename)
                    log_result(f"FAILED: {url} | {msg}")
                else:
                    print("✅ Download complete at MAXIMUM QUALITY!\n")
                    log_result(f"SUCCESS: {url} | {info.get('title', 'Unknown')}")
                    if audio_only:
                        embed_metadata_mp3(filename, info, url)
            q.task_done()
        except Exception as e:
            error_msg = str(e)
            if ("Unsupported URL" in error_msg and "tiktok.com" in url and "/photo/" in url):
                error_msg = "TikTok photo posts (multi-image posts) are not supported. Please use a video link."
            elif "Requested format is not available" in error_msg:
                print_warning("The requested video format is not available")
                print("👉 Try using a different format or updating yt-dlp")
                error_msg = "Video format not available - try a different format"
            elif "ffmpeg exited with code" in error_msg:
                print_warning("ffmpeg could not download this stream. The video may still be Live, or YouTube has not finished processing the file.")
                print("👉 If it's Live, wait until the Live ends or YouTube processes the archive, then try again.")
            elif "HTTP Error 403" in error_msg:
                print_warning("This video may have restrictions or protections")
                print("👉 Try a different link or wait a moment and try again")
                error_msg = "Video access restricted"
            elif "No video formats" in error_msg or "No formats found" in error_msg:
                print_warning("No downloadable video formats found")
                print("👉 This video may have restrictions or be inaccessible")
                error_msg = "No video formats available for download"
            elif "Video unavailable" in error_msg or "This video is unavailable" in error_msg:
                print_warning("This video is not accessible")
                print("👉 The video may have been removed or has access restrictions")
                error_msg = "Video not accessible"
            elif "Private video" in error_msg or "sign in if you've been granted access" in error_msg.lower():
                print_warning("This video is private or access-restricted")
                print("👉 Use --cookies-from-browser or --cookies to authenticate (see https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp)")
                if not cookies_opts:
                    print("❗ You have not provided cookies. The program cannot download private videos.")
                error_msg = "Private video or restricted access - cookies required for download"
            elif "'NoneType' object has no attribute" in error_msg:
                print_warning("Error processing data")
                print("👉 Try a different link or check the link again")
                error_msg = "Error processing data"
            print(f"❌ Error downloading {url}: {error_msg}\n")
            print("👉 If this is a protected or unsupported link, try another or check for yt-dlp updates.\n")
            log_result(f"FAILED: {url} | {error_msg}")
            q.task_done()

def print_banner_animation():
    frames = ['|', '/', '-', '\\']
    banner1 = "   =============================================="
    banner2 = "      YOUTUBE & SOCIAL VIDEO DOWNLOADER v1.0     "
    banner3 = "   =============================================="
    banner4 = "   [Tip] Place your www.youtube.com_cookies.txt here for private videos!"
    banner5 = "   =============================================="
    for i in range(15):
        idx = i % 4
        os.system('cls' if os.name == 'nt' else 'clear')
        print()
        print("\033[92m" + banner1 + "\033[0m")
        print("\033[96m" + banner2 + "\033[0m")
        print("\033[92m" + banner3 + "\033[0m")
        print()
        print("\033[93m" + banner4 + "\033[0m")
        print()
        print("               \033[95mLoading... " + frames[idx] + "\033[0m")
        time.sleep(0.1)
    os.system('cls' if os.name == 'nt' else 'clear')

def print_banner():
    banner = r"""
\033[96m
   __   __        _        _           _           _           
   \ \ / /__ _ __| |_ __ _| |__  _   _| |__   ___ | | ___  ___ 
    \ V / _ \ '__| __/ _` | '_ \| | | | '_ \ / _ \| |/ _ \/ __|
     | |  __/ |  | || (_| | |_) | |_| | |_) | (_) | |  __/\__ \
     |_|\___|_|   \__\__,_|_.__/ \__,_|_.__/ \___/|_|\___||___/
\033[0m
    """
    print(banner)
    print("\033[92mYOUTUBE & SOCIAL VIDEO DOWNLOADER\033[0m")
    print("\033[93mTip: Place your www.youtube.com_cookies.txt here for private videos!\033[0m")
    print("\033[95m-------------------------------------------------------------\033[0m")

def beep():
    print('\a', end='')

def print_random_motivation():
    messages = [
        "🎉 Done! Enjoy your music/video!",
        "🚀 All downloads finished! Have fun with your new files!",
        "😎 Download completed at lightning speed!",
        "✨ All done. Great job!",
        "👍 Everything downloaded smoothly!",
        "🥳 Yay! All files downloaded successfully!",
        "💡 If you have issues, try updating yt-dlp or contact the developer!"
    ]
    print("\033[96m" + random.choice(messages) + "\033[0m")

# --- Main logic ---
def main():
    print_banner_animation()
    print_banner()
    os_type = get_os_type()
    print(f"\033[94m🖥️  Detected OS: {os_type}\033[0m")
    if os_type == 'unknown':
        print_warning("This operating system may not be fully supported.")
    start_time = datetime.now()
    download_folder = get_download_folder()
    cookies_opts = get_cookies_option()
    last_links = []
    while True:
        links = []
        print("\nPaste video links (one per line, press Enter on an empty line to finish):")
        while True:
            link = input()
            if not link.strip():
                break
            links.append(link.strip())
        if not links:
            if last_links:
                print("\nNo links entered. Do you want to use the previous links?")
                print("1 = Yes, use previous links")
                print("2 = No, exit")
                choice = input("Choice: ").strip()
                if choice == '1':
                    links = last_links.copy()
                    print("\nRestored previous links:")
                    for idx, l in enumerate(links):
                        print(f"{idx+1}. {l}")
                else:
                    print("No links entered. Exiting.")
                    return
            else:
                print("No links entered. Exiting.")
                return
        last_links = links.copy()
        print("\nLinks to download:")
        for idx, l in enumerate(links):
            print(f"{idx+1}. {l}")
        print("\nChoose download mode for all links:")
        print("1 = All links as MP4 (video) - MAXIMUM QUALITY")
        print("2 = All links as MP3 (audio)")
        mode = input("Choice: ").strip()
        link_modes = []
        if mode == '2':
            link_modes = ['mp3'] * len(links)
        else:
            link_modes = ['mp4'] * len(links)

        # --- Configure options for all links ---
        link_options = []
        for i, (link, mode_) in enumerate(zip(links, link_modes)):
            link_options.append({'mode': mode_, 'resolution': None, 'start': None, 'end': None})

        q = queue.Queue()
        worker = threading.Thread(target=download_worker, args=(q, download_folder, cookies_opts), daemon=True)
        worker.start()
        for link, opts in zip(links, link_options):
            q.put((link, opts))
        print("\nWaiting for all downloads to finish...")
        q.join()
        q.put(None)  # Tell worker to exit
        worker.join()
        print("\nAll done!")
        end_time = datetime.now()
        elapsed = end_time - start_time
        print(f"\033[92mElapsed time: {elapsed}\033[0m")
        print_random_motivation()
        more = input("Do you want to download more links? (y/n): ").strip().lower()
        if more == 'n':
            break

if __name__ == "__main__":
    main()