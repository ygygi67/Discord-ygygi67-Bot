import os
from collections import defaultdict
from googleapiclient.discovery import build

# ==========================================
# ⚙️ ตั้งค่าพื้นฐาน (ดึงมาจากโค้ดของคุณ)
# ==========================================
API_KEY = 'AIzaSyD9vITTQSEH-ylJGYNdni1iIQUxH-i7K3w'
PLAYLIST_ID = 'PLClZz0mM3CSkzq9OPkgpqjlosUqxtO78m'

# ฟังก์ชันดึงรายชื่อวิดีโอทั้งหมด
def get_all_playlist_videos(youtube, playlist_id):
    videos = []
    next_page_token = None
    
    while True:
        request = youtube.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=50, 
            pageToken=next_page_token
        )
        response = request.execute()
        
        for item in response['items']:
            video_id = item['snippet']['resourceId']['videoId']
            title = item['snippet']['title']
            videos.append({'id': video_id, 'title': title})
            
        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break
            
    return videos

def main():
    youtube = build('youtube', 'v3', developerKey=API_KEY)
    
    print("⏳ กำลังสแกน Playlist เพื่อหาคลิปซ้ำ...")
    all_videos = get_all_playlist_videos(youtube, PLAYLIST_ID)
    print(f"✅ ดึงข้อมูลเสร็จสิ้น! พบวิดีโอทั้งหมด {len(all_videos)} รายการ\n")

    # ตัวแปรเก็บข้อมูลเพื่อหาตัวซ้ำ
    id_tracker = defaultdict(list)
    title_tracker = defaultdict(list)

    # วนลูปเก็บข้อมูล ลำดับที่, ID, และ ชื่อ
    for index, video in enumerate(all_videos):
        position = index + 1 # ลำดับคลิปใน Playlist
        vid = video['id']
        title = video['title']
        
        id_tracker[vid].append(position)
        title_tracker[title].append({'position': position, 'id': vid})

    # ----------------------------------------
    # 1. หาคลิปที่เพิ่มซ้ำ (ลิงก์เดียวกันเป๊ะ)
    # ----------------------------------------
    duplicate_ids = {vid: positions for vid, positions in id_tracker.items() if len(positions) > 1}
    
    print("="*50)
    print(f"🚨 สรุป: พบวิดีโอที่ 'ลิงก์ซ้ำกัน' จำนวน {len(duplicate_ids)} รายการ")
    print("="*50)
    if duplicate_ids:
        for vid, positions in duplicate_ids.items():
            # หาชื่อคลิปมาแสดง
            sample_title = next(title for title, data in title_tracker.items() if any(d['id'] == vid for d in data))
            print(f"🎬 ชื่อคลิป: {sample_title}")
            print(f"🔗 ลิงก์: https://www.youtube.com/watch?v={vid}")
            print(f"📍 อยู่ในลำดับที่: {positions}\n")
    else:
        print("✅ ไม่มีวิดีโอที่ลิงก์ซ้ำกันเลย เยี่ยมมาก!\n")

    # ----------------------------------------
    # 2. หาคลิปที่ชื่อซ้ำกัน (แต่อาจจะคนละลิงก์)
    # ----------------------------------------
    # คัดเฉพาะชื่อที่ซ้ำ และ ID ต้องไม่ซ้ำกันด้วย (เพราะ ID ซ้ำเช็คไปแล้วด้านบน)
    duplicate_titles = {}
    for title, data in title_tracker.items():
        unique_ids = set(d['id'] for d in data)
        if len(unique_ids) > 1:
            duplicate_titles[title] = data

    print("="*50)
    print(f"⚠️ สรุป: พบวิดีโอที่ 'ชื่อเหมือนกัน แต่คนละลิงก์' จำนวน {len(duplicate_titles)} ชื่อ")
    print("="*50)
    if duplicate_titles:
        for title, data in duplicate_titles.items():
            print(f"📝 ชื่อคลิป: {title}")
            for item in data:
                print(f"   - ลำดับที่ {item['position']} -> ลิงก์: https://www.youtube.com/watch?v={item['id']}")
            print()
    else:
        print("✅ ไม่มีวิดีโอที่ชื่อซ้ำกัน!\n")

if __name__ == '__main__':
    main()