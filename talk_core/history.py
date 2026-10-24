"""
TALK Core - Command History (SQLite)

JSONL geçmişi otomatik taşınır; son kayıtlar ve arama verimli çalışır.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import List, Optional

from .config import CONFIG_DIR, ensure_config_dir
from .models import HistoryEntry

HISTORY_DB = CONFIG_DIR / "history.db"
LEGACY_HISTORY_FILE = CONFIG_DIR / "history.jsonl"
LEGACY_HISTORY_TXT = Path.home() / ".talk_history"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    prompt TEXT NOT NULL,
    command TEXT NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    risk_level TEXT NOT NULL DEFAULT 'SAFE',
    returncode INTEGER,
    duration_sec REAL
);
"""


class HistoryManager:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or HISTORY_DB
        ensure_config_dir()
        self._init_db()
        self._migrate_legacy_if_needed()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            with self._connect() as conn:
                conn.executescript(_SCHEMA)
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    def _row_to_entry(self, row: sqlite3.Row) -> HistoryEntry:
        return HistoryEntry(
            id=row["id"],
            timestamp=row["timestamp"],
            prompt=row["prompt"],
            command=row["command"],
            explanation=row["explanation"] or "",
            risk_level=row["risk_level"] or "SAFE",
            returncode=row["returncode"],
            duration_sec=row["duration_sec"],
        )

    def _migrate_legacy_if_needed(self) -> None:
        if self.count() > 0:
            return

        sources: list[Path] = []
        if LEGACY_HISTORY_FILE.is_file():
            sources.append(LEGACY_HISTORY_FILE)
        if LEGACY_HISTORY_TXT.is_file():
            sources.append(LEGACY_HISTORY_TXT)

        for path in sources:
            try:
                if path.suffix == ".jsonl":
                    lines = path.read_text(encoding="utf-8").splitlines()
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            self.add(
                                prompt=str(data.get("prompt") or ""),
                                command=str(data.get("command") or ""),
                                explanation=str(data.get("explanation") or ""),
                                risk_level=str(data.get("risk_level") or "SAFE"),
                                returncode=data.get("returncode"),
                                duration_sec=data.get("duration_sec"),
                            )
                        except Exception:
                            continue
                else:
                    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
                    for line in path.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line:
                            self.add(line, line, "Legacy geçmiş", timestamp=now_str)
                backup = path.with_suffix(path.suffix + ".bak")
                if not backup.exists():
                    path.rename(backup)
            except Exception:
                continue

    def count(self) -> int:
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) AS c FROM history").fetchone()
                return int(row["c"]) if row else 0
        except sqlite3.Error:
            return 0

    def add(
        self,
        prompt: str,
        command: str,
        explanation: str = "",
        risk_level: str = "SAFE",
        returncode: Optional[int] = None,
        duration_sec: Optional[float] = None,
        timestamp: Optional[str] = None,
    ) -> HistoryEntry:
        entry = HistoryEntry(
            id=uuid.uuid4().hex[:8],
            timestamp=timestamp or time.strftime("%Y-%m-%d %H:%M:%S"),
            prompt=prompt.strip(),
            command=command.strip(),
            explanation=explanation.strip(),
            risk_level=risk_level,
            returncode=returncode,
            duration_sec=duration_sec,
        )
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO history
                    (id, timestamp, prompt, command, explanation, risk_level, returncode, duration_sec)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.id,
                        entry.timestamp,
                        entry.prompt,
                        entry.command,
                        entry.explanation,
                        entry.risk_level,
                        entry.returncode,
                        entry.duration_sec,
                    ),
                )
            os.chmod(self.db_path, 0o600)
        except (OSError, sqlite3.Error):
            pass
        return entry

    def get_recent(self, limit: int = 100) -> List[HistoryEntry]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM history ORDER BY rowid DESC LIMIT ?",
                    (max(1, limit),),
                ).fetchall()
            rows.reverse()
            return [self._row_to_entry(r) for r in rows]
        except sqlite3.Error:
            return []

    def search(self, query: str, limit: int = 50) -> List[HistoryEntry]:
        q = f"%{query.lower().strip()}%"
        if q == "%%":
            return self.get_recent(limit)
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM history
                    WHERE lower(prompt) LIKE ?
                       OR lower(command) LIKE ?
                       OR lower(explanation) LIKE ?
                    ORDER BY rowid DESC
                    LIMIT ?
                    """,
                    (q, q, q, max(1, limit)),
                ).fetchall()
            rows.reverse()
            return [self._row_to_entry(r) for r in rows]
        except sqlite3.Error:
            return []

    def clear(self) -> bool:
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM history")
            return True
        except (OSError, sqlite3.Error):
            return False
