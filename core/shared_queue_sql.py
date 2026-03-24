"""
Shared Queue System for Distributed Bot - SQL Server Version
ใช้สำหรับประสานงานระหว่าง Shards และ Workers
รองรับทั้ง Redis, SQL Server, MySQL, และ SQLite
"""

import json
import sqlite3
import threading
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, asdict
import os
import logging

# SQL Database imports
try:
    import pyodbc  # SQL Server
    PYODBC_AVAILABLE = True
except ImportError:
    PYODBC_AVAILABLE = False

try:
    import mysql.connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

logger = logging.getLogger('discord_bot')

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

class DatabaseBackend:
    """Base class for different database backends"""
    
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.lock = threading.Lock()
    
    def connect(self):
        """Create database connection"""
        raise NotImplementedError
    
    def init_tables(self):
        """Create necessary tables"""
        raise NotImplementedError
    
    def execute_query(self, query: str, params: tuple = None):
        """Execute SQL query"""
        raise NotImplementedError

class SQLiteBackend(DatabaseBackend):
    """SQLite Backend (default)"""
    
    def __init__(self, db_path: str = 'data/shared_queue.db'):
        super().__init__(db_path)
        self.db_path = db_path
    
    def connect(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        return sqlite3.connect(self.db_path, check_same_thread=False)
    
    def init_tables(self):
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                priority INTEGER DEFAULT 0,
                shard_id INTEGER,
                status TEXT DEFAULT 'pending',
                result TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS worker_status (
                worker_id TEXT PRIMARY KEY,
                status TEXT DEFAULT 'idle',
                current_task TEXT,
                last_heartbeat TEXT NOT NULL,
                shard_id INTEGER
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority, created_at)
        ''')
        
        conn.commit()
        conn.close()

class SQLServerBackend(DatabaseBackend):
    """SQL Server Backend"""
    
    def __init__(self, server: str, database: str, username: str, password: str):
        connection_string = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};UID={username};PWD={password}'
        super().__init__(connection_string)
        
        if not PYODBC_AVAILABLE:
            raise ImportError("pyodbc is required for SQL Server. Install with: pip install pyodbc")
    
    def connect(self):
        return pyodbc.connect(self.connection_string)
    
    def init_tables(self):
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='tasks' AND xtype='U')
            CREATE TABLE tasks (
                id NVARCHAR(50) PRIMARY KEY,
                type NVARCHAR(50) NOT NULL,
                data NVARCHAR(MAX) NOT NULL,
                priority INTEGER DEFAULT 0,
                shard_id INTEGER,
                status NVARCHAR(20) DEFAULT 'pending',
                result NVARCHAR(MAX),
                error NVARCHAR(MAX),
                created_at NVARCHAR(50) NOT NULL,
                updated_at NVARCHAR(50) NOT NULL
            )
        ''')
        
        cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='worker_status' AND xtype='U')
            CREATE TABLE worker_status (
                worker_id NVARCHAR(50) PRIMARY KEY,
                status NVARCHAR(20) DEFAULT 'idle',
                current_task NVARCHAR(50),
                last_heartbeat NVARCHAR(50) NOT NULL,
                shard_id INTEGER
            )
        ''')
        
        cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name='IX_tasks_status')
            CREATE INDEX IX_tasks_status ON tasks(status)
        ''')
        
        cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name='IX_tasks_priority')
            CREATE INDEX IX_tasks_priority ON tasks(priority, created_at)
        ''')
        
        conn.commit()
        conn.close()

class MySQLBackend(DatabaseBackend):
    """MySQL Backend"""
    
    def __init__(self, host: str, database: str, username: str, password: str, port: int = 3306):
        connection_string = {
            'host': host,
            'database': database,
            'user': username,
            'password': password,
            'port': port
        }
        super().__init__(connection_string)
        
        if not MYSQL_AVAILABLE:
            raise ImportError("mysql-connector-python is required for MySQL. Install with: pip install mysql-connector-python")
    
    def connect(self):
        return mysql.connector.connect(**self.connection_string)
    
    def init_tables(self):
        conn = self.connect()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id VARCHAR(50) PRIMARY KEY,
                type VARCHAR(50) NOT NULL,
                data TEXT NOT NULL,
                priority INT DEFAULT 0,
                shard_id INT,
                status VARCHAR(20) DEFAULT 'pending',
                result TEXT,
                error TEXT,
                created_at VARCHAR(50) NOT NULL,
                updated_at VARCHAR(50) NOT NULL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS worker_status (
                worker_id VARCHAR(50) PRIMARY KEY,
                status VARCHAR(20) DEFAULT 'idle',
                current_task VARCHAR(50),
                last_heartbeat VARCHAR(50) NOT NULL,
                shard_id INT
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority, created_at)
        ''')
        
        conn.commit()
        conn.close()

class SharedQueue:
    """
    ระบบคิวแบบ Share ระหว่าง Shards/Workers
    รองรับหลาย Database Backend
    """
    
    def __init__(self, backend_type: str = 'sqlite', **kwargs):
        self.backend_type = backend_type
        self._local_handlers: Dict[str, List[Callable]] = {}
        
        # Initialize database backend
        if backend_type == 'sqlite':
            db_path = kwargs.get('db_path', 'data/shared_queue.db')
            self.backend = SQLiteBackend(db_path)
        elif backend_type == 'sqlserver':
            self.backend = SQLServerBackend(
                server=kwargs['server'],
                database=kwargs['database'],
                username=kwargs['username'],
                password=kwargs['password']
            )
        elif backend_type == 'mysql':
            self.backend = MySQLBackend(
                host=kwargs['host'],
                database=kwargs['database'],
                username=kwargs['username'],
                password=kwargs['password'],
                port=kwargs.get('port', 3306)
            )
        else:
            raise ValueError(f"Unsupported backend: {backend_type}")
        
        self.backend.init_tables()
        logger.info(f"SharedQueue initialized with {backend_type} backend")
    
    def add_task(self, task: Task) -> bool:
        """เพิ่ม Task ลงในคิว"""
        with self.backend.lock:
            try:
                conn = self.backend.connect()
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT INTO tasks (id, type, data, priority, shard_id, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    task.id, task.type, json.dumps(task.data), task.priority,
                    task.shard_id, task.status, task.created_at, task.updated_at
                ))
                
                conn.commit()
                conn.close()
                return True
                
            except Exception as e:
                logger.error(f"Failed to add task {task.id}: {e}")
                return False
    
    def get_next_task(self, worker_id: str, task_types: List[str] = None) -> Optional[Task]:
        """ดึง Task ถัดไปจากคิว"""
        with self.backend.lock:
            try:
                conn = self.backend.connect()
                cursor = conn.cursor()
                
                # Build query based on backend type
                if self.backend_type == 'sqlite':
                    query = '''
                        SELECT * FROM tasks 
                        WHERE status = 'pending'
                        ORDER BY priority ASC, created_at ASC
                        LIMIT 1
                    '''
                    params = ()
                elif self.backend_type == 'sqlserver':
                    query = '''
                        SELECT TOP 1 * FROM tasks 
                        WHERE status = 'pending'
                        ORDER BY priority ASC, created_at ASC
                    '''
                    params = ()
                elif self.backend_type == 'mysql':
                    query = '''
                        SELECT * FROM tasks 
                        WHERE status = 'pending'
                        ORDER BY priority ASC, created_at ASC
                        LIMIT 1
                    '''
                    params = ()
                
                if task_types:
                    placeholders = ','.join(['?' for _ in task_types])
                    if self.backend_type == 'sqlserver':
                        query = query.replace("WHERE status = 'pending'", f"WHERE status = 'pending' AND type IN ({placeholders})")
                    else:
                        query = query.replace("WHERE status = 'pending'", f"WHERE status = 'pending' AND type IN ({placeholders})")
                    params = tuple(task_types)
                
                cursor.execute(query, params)
                row = cursor.fetchone()
                
                if row:
                    # Mark task as processing
                    cursor.execute('UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?', 
                                 ('processing', datetime.now().isoformat(), row[0]))
                    conn.commit()
                    
                    # Update worker status
                    self.update_worker_status(worker_id, 'processing', row[0])
                    
                    conn.close()
                    
                    return Task(
                        id=row[0], type=row[1], data=json.loads(row[2]),
                        priority=row[3], shard_id=row[4], status=row[5],
                        result=json.loads(row[6]) if row[6] else None,
                        error=row[7], created_at=row[8], updated_at=row[9]
                    )
                
                conn.close()
                return None
                
            except Exception as e:
                logger.error(f"Failed to get next task: {e}")
                return None
    
    def update_task_status(self, task_id: str, status: str, result: Dict = None, error: str = None):
        """อัพเดทสถานะ Task"""
        with self.backend.lock:
            try:
                conn = self.backend.connect()
                cursor = conn.cursor()
                
                cursor.execute('''
                    UPDATE tasks SET status = ?, result = ?, error = ?, updated_at = ?
                    WHERE id = ?
                ''', (
                    status, 
                    json.dumps(result) if result else None,
                    error,
                    datetime.now().isoformat(),
                    task_id
                ))
                
                conn.commit()
                conn.close()
                
            except Exception as e:
                logger.error(f"Failed to update task {task_id}: {e}")
    
    def update_worker_status(self, worker_id: str, status: str, current_task: str = None, shard_id: int = None):
        """อัพเดทสถานะ Worker"""
        with self.backend.lock:
            try:
                conn = self.backend.connect()
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT OR REPLACE INTO worker_status (worker_id, status, current_task, last_heartbeat, shard_id)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    worker_id, status, current_task, datetime.now().isoformat(), shard_id
                ))
                
                conn.commit()
                conn.close()
                
            except Exception as e:
                logger.error(f"Failed to update worker status {worker_id}: {e}")
    
    def get_queue_stats(self) -> Dict[str, int]:
        """ดึงสถิติคิว"""
        with self.backend.lock:
            try:
                conn = self.backend.connect()
                cursor = conn.cursor()
                
                cursor.execute('SELECT status, COUNT(*) FROM tasks GROUP BY status')
                stats = dict(cursor.fetchall())
                
                cursor.execute('SELECT COUNT(*) FROM worker_status WHERE status = "processing"')
                stats['active_workers'] = cursor.fetchone()[0]
                
                conn.close()
                return stats
                
            except Exception as e:
                logger.error(f"Failed to get queue stats: {e}")
                return {}

# Factory function for easy initialization
def create_shared_queue(backend_type: str = 'sqlite', **kwargs) -> SharedQueue:
    """สร้าง SharedQueue ตาม backend ที่ต้องการ"""
    return SharedQueue(backend_type, **kwargs)
