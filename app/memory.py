"""SQLite 会话记忆：消息、用户偏好、待补全槽位。"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .utils import now_iso


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    meta TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, id);
                CREATE TABLE IF NOT EXISTS profile (
                    session_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(session_id, key)
                );
                CREATE TABLE IF NOT EXISTS pending (
                    session_id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def ensure_session(self, session_id: str) -> None:
        ts = now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO sessions(session_id, created_at, updated_at) VALUES(?,?,?)",
                (session_id, ts, ts),
            )
            self._conn.execute(
                "UPDATE sessions SET updated_at=? WHERE session_id=?", (ts, session_id)
            )

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.ensure_session(session_id)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO messages(session_id, role, content, meta, created_at) VALUES(?,?,?,?,?)",
                (
                    session_id,
                    role,
                    content,
                    json.dumps(meta or {}, ensure_ascii=False),
                    now_iso(),
                ),
            )

    def recent_messages(self, session_id: str, limit: int = 8) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content, meta, created_at FROM messages "
                "WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        result = []
        for row in reversed(rows):
            result.append(
                {
                    "role": row["role"],
                    "content": row["content"],
                    "meta": json.loads(row["meta"] or "{}"),
                    "created_at": row["created_at"],
                }
            )
        return result

    def set_profile(self, session_id: str, key: str, value: Any) -> None:
        self.ensure_session(session_id)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO profile(session_id, key, value, updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(session_id, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (session_id, key, json.dumps(value, ensure_ascii=False), now_iso()),
            )

    def get_profile(self, session_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM profile WHERE session_id=? AND key=?",
                (session_id, key),
            ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]

    def all_profile(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value FROM profile WHERE session_id=?", (session_id,)
            ).fetchall()
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                result[row["key"]] = row["value"]
        return result

    def set_pending(self, session_id: str, action: str, payload: dict[str, Any]) -> None:
        self.ensure_session(session_id)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO pending(session_id, action, payload, updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET action=excluded.action, "
                "payload=excluded.payload, updated_at=excluded.updated_at",
                (
                    session_id,
                    action,
                    json.dumps(payload, ensure_ascii=False),
                    now_iso(),
                ),
            )

    def get_pending(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT action, payload, updated_at FROM pending WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["payload"])
        except json.JSONDecodeError:
            payload = {}
        return {
            "action": row["action"],
            "payload": payload,
            "updated_at": row["updated_at"],
        }

    def clear_pending(self, session_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM pending WHERE session_id=?", (session_id,))

    def close(self) -> None:
        with self._lock:
            self._conn.close()
