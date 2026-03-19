"""
Worker Node - โหนดประมวลผลงานหนัก
รับ Task จาก Master ผ่าน Shared Queue มาทำงาน
"""

import asyncio
import discord
from discord.ext import commands, tasks
from typing import List, Dict, Optional
import json
import os
import sys

# Add base dir to path
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE_DIR)

from shared_queue import AsyncSharedQueue, Task, get_queue

class WorkerNode:
    """
    Worker สำหรับประมวลผลงานหนัก
    ไม่ต้องเชื่อมต่อ Discord Gateway (ไม่ต้องใช้ Token)
    ทำงานผ่าน Shared Queue เท่านั้น
    """
    
    def __init__(self, worker_id: int, supported_tasks: List[str] = None):
        self.worker_id = worker_id
        self.supported_tasks = supported_tasks or ['download', 'process', 'convert']
        self.queue = AsyncSharedQueue()
        self.running = False
        self.current_task: Optional[Task] = None
        self.processed_count = 0
        
    async def start(self):
        """เริ่ม Worker Loop"""
        print(f"🚀 Worker {self.worker_id} Starting...")
        print(f"   Supported tasks: {self.supported_tasks}")
        
        self.running = True
        
        # Start worker loop
        while self.running:
            try:
                # ดึง Task จาก Queue
                task = await self.queue.get_next_task(self.supported_tasks)
                
                if task:
                    self.current_task = task
                    print(f"⚙️  Worker {self.worker_id} processing task: {task.id} ({task.type})")
                    
                    # ประมวลผล Task
                    result = await self.process_task(task)
                    
                    # รายงานผล
                    if result.get('success'):
                        await self.queue.complete_task(task.id, result=result)
                        print(f"✅ Worker {self.worker_id} completed: {task.id}")
                        self.processed_count += 1
                    else:
                        await self.queue.complete_task(task.id, error=result.get('error'))
                        print(f"❌ Worker {self.worker_id} failed: {task.id} - {result.get('error')}")
                    
                    self.current_task = None
                else:
                    # ไม่มีงาน รอสักพัก
                    await asyncio.sleep(1)
                    
            except Exception as e:
                print(f"❌ Worker {self.worker_id} Error: {e}")
                await asyncio.sleep(5)
    
    async def process_task(self, task: Task) -> Dict:
        """
        ประมวลผล Task ตามประเภท
        """
        try:
            if task.type == 'download':
                return await self._handle_download(task.data)
            elif task.type == 'process':
                return await self._handle_process(task.data)
            elif task.type == 'convert':
                return await self._handle_convert(task.data)
            else:
                return {'success': False, 'error': f'Unknown task type: {task.type}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _handle_download(self, data: Dict) -> Dict:
        """
        จัดการ Download (เช่น ดาวน์โหลดเพลงจาก YouTube)
        """
        import yt_dlp
        
        url = data.get('url')
        output_path = data.get('output_path', './music/downloads')
        
        if not url:
            return {'success': False, 'error': 'No URL provided'}
        
        try:
            os.makedirs(output_path, exist_ok=True)
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
            }
            
            # Run yt-dlp in thread pool ไม่ให้ block
            def download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return info
            
            info = await asyncio.to_thread(download)
            
            return {
                'success': True,
                'title': info.get('title'),
                'duration': info.get('duration'),
                'file_path': os.path.join(output_path, f"{info.get('title')}.mp3")
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _handle_process(self, data: Dict) -> Dict:
        """
        จัดการประมวลผลข้อมูล (เช่น สร้างกราฟสถิติ)
        """
        import matplotlib.pyplot as plt
        import io
        import base64
        
        try:
            # สร้างกราฟตามข้อมูลที่ส่งมา
            chart_type = data.get('chart_type', 'line')
            chart_data = data.get('data', [])
            
            plt.figure(figsize=(10, 6))
            
            if chart_type == 'line':
                plt.plot(chart_data)
            elif chart_type == 'bar':
                plt.bar(range(len(chart_data)), chart_data)
            elif chart_type == 'pie':
                plt.pie(chart_data.values(), labels=chart_data.keys())
            
            # บันทึกเป็น base64
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode()
            plt.close()
            
            return {
                'success': True,
                'image_base64': img_base64
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _handle_convert(self, data: Dict) -> Dict:
        """
        จัดการ Convert ไฟล์ (เช่น แปลงรูปแบบเสียง)
        """
        import subprocess
        
        input_file = data.get('input_file')
        output_format = data.get('output_format', 'mp3')
        
        if not input_file or not os.path.exists(input_file):
            return {'success': False, 'error': 'Input file not found'}
        
        try:
            output_file = input_file.rsplit('.', 1)[0] + f'.{output_format}'
            
            # ใช้ FFmpeg แปลงไฟล์
            cmd = [
                'ffmpeg', '-i', input_file,
                '-y',  # Overwrite output
                output_file
            ]
            
            result = await asyncio.to_thread(
                subprocess.run, cmd, 
                capture_output=True, 
                text=True
            )
            
            if result.returncode == 0:
                return {
                    'success': True,
                    'output_file': output_file
                }
            else:
                return {'success': False, 'error': result.stderr}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def stop(self):
        """หยุด Worker"""
        print(f"🛑 Worker {self.worker_id} Stopping...")
        self.running = False
    
    def get_status(self) -> Dict:
        """สถานะปัจจุบันของ Worker"""
        return {
            'worker_id': self.worker_id,
            'running': self.running,
            'current_task': self.current_task.id if self.current_task else None,
            'processed_count': self.processed_count,
            'supported_tasks': self.supported_tasks
        }

class WorkerPool:
    """
    จัดการหลาย Workers พร้อมกัน
    """
    
    def __init__(self, num_workers: int = 2):
        self.num_workers = num_workers
        self.workers: List[WorkerNode] = []
        self.tasks: List[asyncio.Task] = []
    
    async def start(self):
        """เริ่มทุก Workers"""
        print(f"🏭 Starting Worker Pool with {self.num_workers} workers")
        
        for i in range(self.num_workers):
            worker = WorkerNode(worker_id=i)
            self.workers.append(worker)
            
            # สร้าง task สำหรับแต่ละ worker
            task = asyncio.create_task(worker.start())
            self.tasks.append(task)
        
        # รอทุก worker (จะรอตลอดไปจนกว่าจะ stop)
        await asyncio.gather(*self.tasks, return_exceptions=True)
    
    def stop_all(self):
        """หยุดทุก Workers"""
        for worker in self.workers:
            worker.stop()
        
        # Cancel all tasks
        for task in self.tasks:
            task.cancel()
    
    def get_status(self) -> List[Dict]:
        """สถานะของทุก Workers"""
        return [w.get_status() for w in self.workers]

# สำหรับรัน Worker standalone
if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Worker Node for Discord Bot')
    parser.add_argument('--worker-id', type=int, default=0, help='Worker ID')
    parser.add_argument('--num-workers', type=int, default=2, help='Number of workers to start')
    
    args = parser.parse_args()
    
    if args.num_workers > 1:
        # รันหลาย Workers
        pool = WorkerPool(num_workers=args.num_workers)
        
        try:
            asyncio.run(pool.start())
        except KeyboardInterrupt:
            print("\nShutting down workers...")
            pool.stop_all()
    else:
        # รัน Worker เดี่ยว
        worker = WorkerNode(worker_id=args.worker_id)
        
        try:
            asyncio.run(worker.start())
        except KeyboardInterrupt:
            print("\nShutting down worker...")
            worker.stop()
