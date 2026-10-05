"""Явное хранилище состояния задачи (SQLite): прогоны, сообщения между агентами, артефакты (blackboard)."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .messages import AgentMessage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    brief TEXT NOT NULL,
    status TEXT NOT NULL,
    step INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    message TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    msg_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step INTEGER NOT NULL,
    sender TEXT NOT NULL,
    recipient TEXT NOT NULL,
    type TEXT NOT NULL,
    payload_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    run_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, key)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StateStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    # --- runs
    def create_run(self, run_id: str, brief: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO runs(run_id, brief, status, created_at) VALUES (?,?,?,?)",
                (run_id, brief, "running", _now()),
            )

    def update_run(self, run_id: str, *, status: str | None = None, step: int | None = None,
                   message: str | None = None, finished: bool = False) -> None:
        sets, vals = [], []
        if status is not None:
            sets.append("status=?"); vals.append(status)
        if step is not None:
            sets.append("step=?"); vals.append(step)
        if message is not None:
            sets.append("message=?"); vals.append(message)
        if finished:
            sets.append("finished_at=?"); vals.append(_now())
        if not sets:
            return
        with self._lock, self._conn:
            self._conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE run_id=?", (*vals, run_id))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT run_id, brief, status, step, created_at, finished_at, message FROM runs WHERE run_id=?", (run_id,))
        row = cur.fetchone()
        if not row:
            return None
        keys = ["run_id", "brief", "status", "step", "created_at", "finished_at", "message"]
        return dict(zip(keys, row))

    # --- messages
    def add_message(self, m: AgentMessage) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)",
                (m.msg_id, m.run_id, m.step, m.sender, m.recipient, m.type, m.payload_type,
                 json.dumps(m.payload, ensure_ascii=False), m.ts),
            )

    def messages(self, run_id: str) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT step, sender, recipient, type, payload_type, ts FROM messages WHERE run_id=? ORDER BY ts", (run_id,))
        return [dict(zip(["step", "sender", "recipient", "type", "payload_type", "ts"], r)) for r in cur.fetchall()]

    # --- blackboard
    def put(self, run_id: str, key: str, value: BaseModel | dict | list | str) -> None:
        if isinstance(value, BaseModel):
            data = value.model_dump_json()
        else:
            data = json.dumps(value, ensure_ascii=False)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?) ON CONFLICT(run_id, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (run_id, key, data, _now()),
            )

    def get(self, run_id: str, key: str, model: type[BaseModel] | None = None):
        cur = self._conn.execute("SELECT value FROM artifacts WHERE run_id=? AND key=?", (run_id, key))
        row = cur.fetchone()
        if not row:
            return None
        return model.model_validate_json(row[0]) if model else json.loads(row[0])

    def close(self) -> None:
        self._conn.close()
