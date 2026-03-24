"""
Shared Queue System for Distributed Bot
ใช้สำหรับประสานงานระหว่าง Shards และ Workers
รองรับทั้ง Redis (production) และ SQLite (simple setup)
"""

import json
import sqlite3
import threading
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, asdict
import os

@dataclass
class Task:
    """โครงสร้าง Task สำหรับส่งให้ Worker ประมวลผล"""
    id: str
    type: str  # 'download', 'process', 'convert', etc.
    data: Dict[str, Any]
    priority: int = 0  # 0=high, 1=normal, 2=low
    shard_id: Optional[int] = None
    status: str = 'pending'  # pending, processing, completed, failed
    result: Optional[Dict] = None
    error: Optional[str] = None
    created_at: str = None
    updated_at: str = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.updated_at is None:
            self.updated_at = self.created_at

class SharedQueue:
    """
    ระบบคิวแบบ Share ระหว่าง Shards/Workers
    ใช้ SQLite เป็น Backend (ง่าย ไม่ต้องติดตั้ง Redis)
    """
    
    def __init__(self, db_path: str = 'data/shared_queue.db'):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._local_handlers: Dict[str, List[Callable]] = {}
        self._init_db()
    
    def _init_db(self):
        """สร้างตารางถ้ายังไม่มี"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    data TEXT NOT NULL,
                    priority INTEGER DEFAULT 0,
                    shard_id INTEGER,
                    status TEXT DEFAULT 'pending',
                    result TEXT,
                    error TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            ''')
            
            # สร้าง index สำหรับค้นหาเร็ว
            conn.execute('CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_type ON tasks(type)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_priority ON tasks(priority)')
            conn.commit()
    
    def submit_task(self, task: Task) -> bool:
        """ส่ง Task เข้าคิว"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO tasks 
                    (id, type, data, priority, shard_id, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    task.id, task.type, json.dumps(task.data),
                    task.priority, task.shard_id, task.status,
                    task.created_at, task.updated_at
                ))
                conn.commit()
            return True
        except Exception as e:
            print(f"[Queue] Error submitting task: {e}")
            return False
    
    def get_next_task(self, task_types: List[str]) -> Optional[Task]:
        """Worker ดึง Task ถัดไปมาทำ (แบบ Lock ป้องกันการแย่งกัน)"""
        with self.lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    # หา Task ที่ pending มี priority สูงสุด สร้างมาก่อน
                    placeholders = ','.join('?' * len(task_types))
                    cursor = conn.execute(f'''
                        SELECT * FROM tasks 
                        WHERE status = 'pending' AND type IN ({placeholders})
                        ORDER BY priority ASC, created_at ASC
                        LIMIT 1
                    ''', task_types)
                    
                    row = cursor.fetchone()
                    if row:
                        # Lock task นี้ทันที
                        conn.execute('''
                            UPDATE tasks 
                            SET status = 'processing', updated_at = ?
                            WHERE id = ? AND status = 'pending'
                        ''', (datetime.now().isoformat(), row[0]))
                        conn.commit()
                        
                        if conn.total_changes > 0:  # Lock สำเร็จ
                            return self._row_to_task(row)
                    return None
            except Exception as e:
                print(f"[Queue] Error getting task: {e}")
                return None
    
    def complete_task(self, task_id: str, result: Dict = None, error: str = None) -> bool:
        """Worker รายงาน Task เสร็จสิ้น"""
        try:
            status = 'failed' if error else 'completed'
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    UPDATE tasks 
                    SET status = ?, result = ?, error = ?, updated_at = ?
                    WHERE id = ?
                ''', (
                    status,
                    json.dumps(result) if result else None,
                    error,
                    datetime.now().isoformat(),
                    task_id
                ))
                conn.commit()
            return True
        except Exception as e:
            print(f"[Queue] Error completing task: {e}")
            return False
    
    def get_task_result(self, task_id: str, timeout: int = 60) -> Optional[Task]:
        """Shard รอผลลัพธ์จาก Worker (polling)"""
        import time
        start = time.time()
        
        while time.time() - start < timeout:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute(
                        'SELECT * FROM tasks WHERE id = ?', (task_id,)
                    )
                    row = cursor.fetchone()
                    
                    if row and row[5] in ('completed', 'failed'):
                        return self._row_to_task(row)
                    
                time.sleep(0.5)  # รอ 0.5 วินาทีแล้วเช็คใหม่
            except Exception as e:
                print(f"[Queue] Error getting result: {e}")
                
        return None
    
    def get_pending_count(self) -> int:
        """จำนวน Task ที่ค้างอยู่"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE status = 'pending'"
                )
                return cursor.fetchone()[0]
        except:
            return 0
    
    def get_stats(self) -> Dict:
        """สถิติของคิว"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT status, COUNT(*) FROM tasks 
                    GROUP BY status
                ''')
                return {row[0]: row[1] for row in cursor.fetchall()}
        except:
            return {}
    
    def cleanup_old_tasks(self, hours: int = 24):
        """ลบ Task เก่าที่เสร็จแล้ว"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Fix: SQLite parameter binding for dynamic interval
                conn.execute('''
                    DELETE FROM tasks 
                    WHERE status IN ('completed', 'failed') 
                    AND updated_at < datetime('now', '-' || ? || ' hours')
                ''', (hours,))
                conn.commit()
        except Exception as e:
            print(f"[Queue] Error cleaning up: {e}")
    
    def _row_to_task(self, row) -> Task:
        """แปลง Database row เป็น Task object"""
        return Task(
            id=row[0],
            type=row[1],
            data=json.loads(row[2]),
            priority=row[3],
            shard_id=row[4],
            status=row[5],
            result=json.loads(row[6]) if row[6] else None,
            error=row[7],
            created_at=row[8],
            updated_at=row[9]
        )

# Singleton instance
_queue_instance: Optional[SharedQueue] = None

def get_queue() -> SharedQueue:
    """ดึง instance ของ SharedQueue"""
    global _queue_instance
    if _queue_instance is None:
        _queue_instance = SharedQueue()
    return _queue_instance

# Async wrapper สำหรับใช้กับ discord.py async
class AsyncSharedQueue:
    """Wrapper สำหรับใช้ใน async context"""
    
    def __init__(self):
        self.queue = get_queue()
        self._lock = asyncio.Lock()
    
    async def submit_task(self, task: Task) -> bool:
        async with self._lock:
            return await asyncio.to_thread(self.queue.submit_task, task)
    
    async def get_next_task(self, task_types: List[str]) -> Optional[Task]:
        async with self._lock:
            return await asyncio.to_thread(self.queue.get_next_task, task_types)
    
    async def complete_task(self, task_id: str, result: Dict = None, error: str = None) -> bool:
        async with self._lock:
            return await asyncio.to_thread(self.queue.complete_task, task_id, result, error)
    
    async def get_task_result(self, task_id: str, timeout: int = 60) -> Optional[Task]:
        return await asyncio.to_thread(self.queue.get_task_result, task_id, timeout)
    
    async def get_stats(self) -> Dict:
        return await asyncio.to_thread(self.queue.get_stats)
