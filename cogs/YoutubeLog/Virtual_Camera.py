import cv2
import numpy as np
import pyvirtualcam
import time
import keyboard
import asyncio
import threading
from playwright.async_api import async_playwright

URL_LIST = [
    "https://vdo.ninja/?v=R4JvREqj",
]
LOCAL_IMAGE_PATH = "ygygi67-25.png"
WIDTH, HEIGHT = 1280, 720
FPS = 30

selected_idx = 0
latest_frame = None
frame_lock = threading.Lock()
stop_event = threading.Event()

async def load_page(browser, url, idx):
    print(f"⏳ กำลังโหลดกล้องที่ {idx+1}...")
    context = await browser.new_context(
        permissions=["camera", "microphone"],
        viewport={"width": WIDTH, "height": HEIGHT}
    )
    page = await context.new_page()

    try:
        await page.goto(url, timeout=60000, wait_until="networkidle")
    except:
        await page.goto(url, timeout=60000)

    try:
        await page.wait_for_selector("video", timeout=15000)
        print(f"✅ เจอ video element กล้องที่ {idx+1}")
    except:
        print(f"⚠️ ไม่เจอ video element กล้องที่ {idx+1}")

    await page.mouse.click(WIDTH // 2, HEIGHT // 2)
    await asyncio.sleep(1)
    await page.mouse.click(WIDTH // 2, HEIGHT // 2)

    await page.evaluate("""() => {
        document.querySelectorAll('video').forEach(v => {
            v.muted = false;
            v.play().catch(() => {});
        });
    }""")

    await asyncio.sleep(3)

    state = await page.evaluate("""() => {
        const v = document.querySelector('video');
        if (!v) return 'NO VIDEO ELEMENT';
        return `readyState=${v.readyState} | paused=${v.paused} | muted=${v.muted}`;
    }""")
    print(f"📺 กล้องที่ {idx+1}: {state}")
    return page

async def capture_loop_cdp(page, img_fallback):
    global latest_frame

    client = await page.context.new_cdp_session(page)

    async def on_frame(params):
        global latest_frame
        try:
            img_data = np.frombuffer(
                __import__('base64').b64decode(params["data"]), np.uint8
            )
            frame = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
            if frame is not None:
                frame = cv2.resize(frame, (WIDTH, HEIGHT))
                with frame_lock:
                    latest_frame = frame
        except Exception as e:
            print(f"⚠️ decode error: {e}")
        finally:
            # ✅ ACK ทุก frame ไม่งั้น CDP หยุดส่ง
            try:
                await client.send("Page.screencastFrameAck", {
                    "sessionId": params["sessionId"]
                })
            except:
                pass

    client.on("Page.screencastFrame", on_frame)

    await client.send("Page.startScreencast", {
        "format": "jpeg",
        "quality": 80,
        "maxWidth": WIDTH,
        "maxHeight": HEIGHT,
        "everyNthFrame": 1
    })

    print("🎬 CDP screencast เริ่มแล้ว")

    try:
        while not stop_event.is_set():
            await asyncio.sleep(0.1)
    finally:
        try:
            await client.send("Page.stopScreencast")
        except:
            pass

def cam_loop(img_fallback):
    global latest_frame

    with pyvirtualcam.Camera(width=WIDTH, height=HEIGHT, fps=FPS) as cam:
        print(f"🚀 พร้อม! ส่งไปที่: {cam.device}")

        while not stop_event.is_set():
            try:
                with frame_lock:
                    frame = latest_frame.copy() if latest_frame is not None else img_fallback

                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                cam.send(frame_rgb)
                cam.sleep_until_next_frame()
            except Exception:
                time.sleep(0.01)

async def main():
    global selected_idx, latest_frame, stop_event

    img_fallback = cv2.imread(LOCAL_IMAGE_PATH)
    if img_fallback is None:
        print(f"❌ ไม่พบไฟล์ {LOCAL_IMAGE_PATH} สร้างภาพสีดำแทน")
        img_fallback = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    else:
        img_fallback = cv2.resize(img_fallback, (WIDTH, HEIGHT))

    latest_frame = img_fallback

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        pages = []
        for i, url in enumerate(URL_LIST):
            try:
                pg = await load_page(browser, url, i)
                pages.append(pg)
            except Exception as e:
                print(f"⚠️ ลิงก์ที่ {i+1} โหลดไม่สำเร็จ: {e}")

        if not pages:
            print("❌ ไม่มีลิงก์ไหนโหลดสำเร็จเลย ปิดโปรแกรม")
            return

        cam_thread = threading.Thread(target=cam_loop, args=(img_fallback,), daemon=True)
        cam_thread.start()

        capture_task = asyncio.create_task(
            capture_loop_cdp(pages[selected_idx], img_fallback)
        )

        print(f"กดเลข 1-{len(pages)} เพื่อสลับกล้อง | Ctrl+C เพื่อออก")

        try:
            while True:
                for i in range(len(pages)):
                    if keyboard.is_pressed(str(i + 1)):
                        if selected_idx != i:
                            print(f"🎯 สลับไปกล้องที่ {i + 1}")
                            selected_idx = i
                            capture_task.cancel()
                            capture_task = asyncio.create_task(
                                capture_loop_cdp(pages[selected_idx], img_fallback)
                            )
                await asyncio.sleep(0.05)

        except KeyboardInterrupt:
            print("🛑 กำลังปิด...")
            stop_event.set()
            capture_task.cancel()

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())