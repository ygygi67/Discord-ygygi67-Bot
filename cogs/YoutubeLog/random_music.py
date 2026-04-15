import os
import json
import random
from googleapiclient.discovery import build

# ==========================================
# ⚙️ ตั้งค่าพื้นฐาน
# ==========================================
API_KEY = 'AIzaSyD9vITTQSEH-ylJGYNdni1iIQUxH-i7K3w'
PLAYLIST_ID = 'PLClZz0mM3CSkzq9OPkgpqjlosUqxtO78m'
HISTORY_FILE = 'history.json'

# ฟังก์ชันดึงรายชื่อวิดีโอ "ทั้งหมด" ทะลุพันคลิป
def get_all_playlist_videos(youtube, playlist_id):
    videos = []
    next_page_token = None
    
    # ลูปดึงข้อมูลทีละ 50 คลิปไปเรื่อยๆ จนกว่าจะหมด Playlist
    while True:
        request = youtube.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=50, # YouTube ให้ดึงได้สูงสุดรอบละ 50 
            pageToken=next_page_token # โทเคนสำหรับกดไปหน้าถัดไป
        )
        response = request.execute()
        
        for item in response['items']:
            video_id = item['snippet']['resourceId']['videoId']
            title = item['snippet']['title']
            videos.append({'id': video_id, 'title': title})
            
        # เช็คว่ามีหน้าถัดไปอีกไหม
        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break # ถ้าไม่มีหน้าถัดไปแล้ว ให้หยุดลูป
            
    return videos

# ฟังก์ชันโหลดประวัติจาก JSON
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

# ฟังก์ชันบันทึกประวัติลง JSON
def save_history(history):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=4)

def main():
    youtube = build('youtube', 'v3', developerKey=API_KEY)
    
    print("⏳ กำลังดึงข้อมูล Playlist ทั้งหมด (ถ้าเพลงเป็นพันอาจใช้เวลาแป๊บนึง)...")
    all_videos = get_all_playlist_videos(youtube, PLAYLIST_ID)
    print(f"✅ ดึงสำเร็จ! เจอทั้งหมด {len(all_videos)} เพลงใน Playlist นี้")
    
    history = load_history()
    print(f"📚 คุณเคยฟังไปแล้ว {len(history)} เพลง")
    
    # 🔥 คัดกรอง: เอาเพลงทั้งหมด มาหักลบกับ เพลงที่อยู่ในประวัติ (รับประกันว่าไม่ซ้ำ 100%)
    unplayed_videos = [v for v in all_videos if v['id'] not in history]
    
    # ถ้าฟังครบทุกเพลงในกองแล้ว ให้รีเซ็ตประวัติใหม่
    if len(unplayed_videos) == 0:
        print("🎉 คุณฟังครบทุกเพลงใน Playlist แล้ว! ระบบจะล้างประวัติเพื่อเริ่มสุ่มใหม่ตั้งแต่ต้น...")
        history = []
        unplayed_videos = all_videos
        
    # สุ่ม 1 เพลงจากกองที่เหลือ (ที่ไม่ซ้ำแน่นอน)
    chosen_video = random.choice(unplayed_videos)
    
    print("\n" + "="*50)
    print(f"🎵 เพลงที่ได้: {chosen_video['title']}")
    print(f"🔗 ลิงก์: https://www.youtube.com/watch?v={chosen_video['id']}")
    print("="*50 + "\n")
    
    # เอา ID เพลงที่สุ่มได้ ยัดใส่ประวัติ แล้วเซฟลงไฟล์ JSON
    history.append(chosen_video['id'])
    save_history(history)
    print(f"💾 บันทึกเพลงนี้ลงในประวัติการฟังเรียบร้อยแล้ว!")

if __name__ == '__main__':
    main()