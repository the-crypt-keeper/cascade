from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Tuple
import asyncio
import sqlite3
import json
import threading
from contextlib import contextmanager
from pathlib import Path
import yaml

@dataclass
class Message:
    cascade_id: str
    payload: Any
    metadata: Dict[str, Any]

    def derive_cascade_id(self, step_name: str, **params) -> str:
        next_id = f"{self.cascade_id}/" if self.cascade_id else ""
        next_id += step_name
        if params:
            param_str = ",".join(f"{k}={v}" for k, v in sorted(params.items()))
            next_id += f":{param_str}"
        return next_id

    @staticmethod
    def merge_cascade_ids(cascade_ids: list[str], step_name: str) -> str:
        merged = ";".join(sorted(cascade_ids))
        return f"{merged}@{step_name}"

class SQLiteStorage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_db()

    @property
    def conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(self.db_path)
        return self._local.conn

    @contextmanager
    def transaction(self):
        with self._lock:
            try:
                yield self.conn
                self.conn.commit()
            except:
                self.conn.rollback()
                raise

    def _init_db(self):
        with self.transaction() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    stream_name TEXT,
                    cascade_id TEXT,
                    payload TEXT,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (stream_name, cascade_id)
                )
            ''')

    async def exists(self, stream_name: str, cascade_id: str) -> bool:
        with self.transaction() as conn:
            cursor = conn.execute(
                'SELECT 1 FROM messages WHERE stream_name = ? AND cascade_id = ?',
                (stream_name, cascade_id)
            )
            return cursor.fetchone() is not None

    async def store(self, stream_name: str, msg: Message):
        with self.transaction() as conn:
            conn.execute(
                'INSERT INTO messages (stream_name, cascade_id, payload, metadata) VALUES (?, ?, ?, ?)',
                (stream_name, msg.cascade_id, json.dumps(msg.payload), json.dumps(msg.metadata))
            )

    async def get_all_messages(self, stream_name: str) -> List[Message]:
        with self.transaction() as conn:
            cursor = conn.execute(
                'SELECT cascade_id, payload, metadata FROM messages WHERE stream_name = ? ORDER BY created_at ASC',
                (stream_name,)
            )
            return [Message(
                cascade_id=row[0],
                payload=json.loads(row[1]),
                metadata=json.loads(row[2])
            ) for row in cursor.fetchall()]

    async def get_all_streams(self) -> List[str]:
        with self.transaction() as conn:
            cursor = conn.execute('SELECT DISTINCT stream_name FROM messages')
            return [row[0] for row in cursor.fetchall()]

    async def get_message(self, cascade_id: str) -> Optional[Message]:
        """Get a message by its cascade ID from any stream"""
        with self.transaction() as conn:
            cursor = conn.execute(
                'SELECT stream_name, cascade_id, payload, metadata FROM messages WHERE cascade_id = ?',
                (cascade_id,)
            )
            row = cursor.fetchone()
            if row:
                return Message(
                    cascade_id=row[1],
                    payload=json.loads(row[2]),
                    metadata=json.loads(row[3])
                )
            return None
        
class Subscription:
    """Wraps a queue for a specific consumer"""
    def __init__(self, queue: asyncio.Queue):
        self.queue = queue
        
    async def get(self) -> Message:
        """Get next message from this subscription"""
        return await self.queue.get()

class Stream:
    def __init__(self, name: str, storage: SQLiteStorage):
        self.name = name
        self.storage = storage
        self.subs: Dict[str, tuple[asyncio.Queue, int]] = {}  # (queue, weight)
        
    def register_sub(self, weight: int = 1) -> Tuple[str, Subscription]:
        """Register a subscription with optional weight for load balancing. Returns (sub_id, subscription)"""
        sub_id = f"{self.name}:sub{len(self.subs)}"
        queue = asyncio.Queue()
        self.subs[sub_id] = (queue, weight)
        return sub_id, Subscription(queue)
        
    async def check_exists(self, cascade_id: str) -> bool:
        """Check if a message already exists in this stream"""
        return await self.storage.exists(self.name, cascade_id)

    async def put(self, msg: Message, _no_store: bool = False):
        """Put a message into the stream"""
        print("put()", msg.cascade_id)
        
        # First persist to storage
        if not _no_store:
            await self.storage.store(self.name, msg)
        
        if not self.subs:
            return

        # Build weighted subscriber list
        weighted_subs = []
        for sub_id, (_, weight) in self.subs.items():
            if weight == 0:  # Special case: gets all messages
                await self.subs[sub_id][0].put(msg)
            weighted_subs.extend([sub_id] * weight)

        if weighted_subs:
            # Use consistent hashing to pick subscriber
            sub_idx = hash(msg.cascade_id) % len(weighted_subs)
            sub_id = weighted_subs[sub_idx]
            await self.subs[sub_id][0].put(msg)
            
    def is_empty(self) -> bool:
        """Check if all subscription queues are empty"""
        return all(queue.empty() for queue, _ in self.subs.values())

class CascadeManager:
    def __init__(self, storage: SQLiteStorage, debug: bool = False):
        self.storage = storage
        self.streams: Dict[str, Stream] = {}
        self.steps: set[str] = set()  # Track all registered steps
        self.idle_steps: set[str] = set()
        self._completion_event = asyncio.Event()
        self.debug = debug
        
    def get_stream(self, name: str) -> Stream:
        """Get an existing stream or create a new one"""
        if name not in self.streams:
            self.streams[name] = Stream(name, self.storage)
        return self.streams[name]

    async def restore_state(self):
        """Restore streams from storage on startup"""
        stream_names = await self.storage.get_all_streams()
        for name in stream_names:
            stream = self.get_stream(name)
            messages = await self.storage.get_all_messages(name)
            for msg in messages:
                await stream.put(msg, _no_store=True)

    def mark_step_idle(self, step_id: str):
        """Mark a step as idle (no more work to do)"""
        if self.debug:
            print(f"Step {step_id} marked idle")
        if step_id not in self.steps:
            self.steps.add(step_id)
        self.idle_steps.add(step_id)
        self._check_completion()

    def mark_step_active(self, step_id: str):
        """Mark a step as active (found work to do)"""
        if step_id not in self.steps:
            self.steps.add(step_id)
        if step_id in self.idle_steps:
            print(f"Step {step_id} marked active")
            self.idle_steps.discard(step_id)

    def _check_completion(self):
        """Check if all steps are idle and all queues are empty"""
        all_idle = len(self.idle_steps) == len(self.steps)
        all_empty = all(stream.is_empty() for stream in self.streams.values())

        if self.debug:
            print("\nChecking completion state:")
            print(f"Registered steps: {self.steps}")
            print(f"Idle steps: {self.idle_steps}")
            
            for stream_name, stream in self.streams.items():
                empty = stream.is_empty()
                print(f"Stream '{stream_name}' empty: {empty}")
                print(f"-- Subscribers: {list(stream.subs.keys())}")
                print(f"-- Queue sizes: {[queue.qsize() for queue, _ in stream.subs.values()]}")
            
            print(f"All steps idle: {all_idle} ({len(self.idle_steps)} == {len(self.steps)})")
            print(f"All queues empty: {all_empty}")
        else:
            # List active steps and count non-empty streams
            active_streams = sum(1 for stream in self.streams.values() if not stream.is_empty())
            print(f"Progress: {len(self.idle_steps)}/{len(self.steps)} streams idle, {active_streams} streams with pending messages.")

        if all_idle and all_empty:
            if self.debug:
                print("Pipeline complete!")
            self._completion_event.set()
            
    async def wait_for_completion(self):
        """Wait for pipeline completion"""
        print("Waiting for pipeline to complete.")
        await self._completion_event.wait()

    async def unroll(self, msg: Message) -> Dict[str, Any]:
        """Unroll a cascade ID to get all upstream outputs"""
        
        def parse_step_name(step_spec: str) -> str:
            """Extract step name from step specification"""
            return step_spec.split(':', 1)[0]
        
        async def unroll_single_path(path: str) -> Dict[str, Any]:
            """Unroll a single path, handling duplicate step names"""
            result = {}
            current_path = []
            seen_steps = {}  # track count of each step name
            
            for step in path.split('/'):
                if not step:
                    continue
                    
                current_path.append(step)
                full_id = '/'.join(current_path)
                
                msg = await self.storage.get_message(full_id)
                if msg:
                    step_name = parse_step_name(step)
                    if step_name in result:
                        # Add suffix for duplicate step names
                        count = seen_steps.get(step_name, 0)
                        seen_steps[step_name] = count + 1
                        step_name = f"{step_name}_{count}"
                    result[step_name] = msg.payload
            
            return result

        # Split into roots and path if @ present
        parts = msg.cascade_id.split('@', 1)
        if len(parts) == 2:
            roots_part, path = parts
            roots = roots_part.split(';')
        else:
            roots = []
            path = parts[0]
        
        # Build final result
        result = {}
        
        # Process roots
        for i, root in enumerate(roots):
            root_result = await unroll_single_path(root)
            result[f"root{i}"] = root_result
        
        # Process main path
        path_result = await unroll_single_path(path)
        result.update(path_result)
        
        return result

class Cascade:
    def __init__(self, project_name, debug: bool = False):
        self.storage = SQLiteStorage(project_name+'.db')
        self.manager = CascadeManager(self.storage, debug=debug)
        self.steps = []
                
    async def step(self, step):
        """Register and setup a step"""
        await step.setup(self.manager)
        self.steps.append(step)

    async def run(self):
        # Restore any existing state
        await self.manager.restore_state()
        
        """Run all steps until completion"""
        try:
            # Start all steps
            tasks = [asyncio.create_task(step.run()) for step in self.steps]
            
            # Wait for completion
            await self.manager.wait_for_completion()
            
            # Cancel all tasks
            for task in tasks:
                task.cancel()
                
            # Wait for tasks to finish
            await asyncio.gather(*tasks, return_exceptions=True)

        finally:
            # Ensure steps are shutdown
            for step in self.steps:
                await step.shutdown()
