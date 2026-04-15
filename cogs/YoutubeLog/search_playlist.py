import re
from googleapiclient.discovery import build

# ==========================================
# ⚙️ ตั้งค่าพื้นฐาน 
# ==========================================
API_KEY = 'AIzaSyD9vITTQSEH-ylJGYNdni1iIQUxH-i7K3w'
PLAYLIST_ID = 'PLClZz0mM3CSkzq9OPkgpqjlosUqxtO78m'

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

# ฟังก์ชันตัดเอาเฉพาะ ID ออกจากลิงก์ YouTube แบบยาวๆ
def extract_video_id(url):
    match = re.search(r"(?:v=|/)([0-9A-Za-z_-]{11}).*", url)
    return match.group(1) if match else url

def main():
    youtube = build('youtube', 'v3', developerKey=API_KEY)
    
    print("⏳ กำลังโหลดข้อมูล Playlist ของคุณ (รอสักครู่)...")
    all_videos = get_all_playlist_videos(youtube, PLAYLIST_ID)
    print(f"✅ โหลดเสร็จสิ้น! มีวิดีโอทั้งหมด {len(all_videos)} รายการพร้อมให้ค้นหา\n")

    while True:
        print("="*50)
        print("🔍 เมนูค้นหาคลิปใน Playlist")
        print("1. ค้นหาด้วย 'ลิงก์' (หรือ Video ID)")
        print("2. ค้นหาด้วย 'ชื่อคลิป' (พิมพ์แค่บางคำก็เจอ)")
        print("0. ออกจากโปรแกรม")
        print("="*50)
        
        choice = input("👉 เลือกเมนู (0/1/2): ")
        
        if choice == '0':
            print("👋 ลาก่อนครับ!")
            break
            
        elif choice == '1':
            url = input("🔗 วางลิงก์ YouTube ที่ต้องการค้นหา: ")
            vid = extract_video_id(url)
            
            # ค้นหาว่ามี ID นี้ไหม พร้อมเก็บลำดับ
            matches = [(index + 1, v) for index, v in enumerate(all_videos) if v['id'] == vid]
            
            print("\nผลการค้นหา:")
            if matches:
                for pos, v in matches:
                    print(f"✅ มีคลิปนี้แล้ว! ชื่อ: {v['title']}")
                    print(f"📍 อยู่ในลำดับที่: {pos} (ของระบบเดิม)")
            else:
                print("❌ ยังไม่มีคลิปนี้ใน Playlist ครับ สามารถกดเพิ่มได้เลย!")
                
        elif choice == '2':
            keyword = input("📝 พิมพ์ชื่อคลิป (หรือบางส่วนของชื่อ): ").lower()
            
            # ค้นหาโดยไม่สนตัวพิมพ์เล็ก-ใหญ่
            matches = [(index + 1, v) for index, v in enumerate(all_videos) if keyword in v['title'].lower()]
            
            print("\nผลการค้นหา:")
            if matches:
                print(f"✅ เจอทั้งหมด {len(matches)} รายการที่มีคำนี้:")
                for pos, v in matches:
                    print(f"  - ลำดับ {pos} | ชื่อ: {v['title']} (ลิงก์: https://youtu.be/{v['id']})")
            else:
                print(f"❌ ไม่พบคลิปที่มีคำว่า '{keyword}' ครับ")
                
        else:
            print("⚠️ กรุณาเลือกเมนู 0, 1 หรือ 2 เท่านั้นครับ")
        print("\n")

if __name__ == '__main__':
    main()