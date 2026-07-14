from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock


@dataclass(frozen=True)
class Stats:
    success_count: int
    failure_count: int
    total_count: int
    first_success_at: str
    last_success_at: str
    last_failure: str
    peak_hour: int | None
    peak_hour_count: int
    peak_day: str
    peak_day_count: int


@dataclass(frozen=True)
class ModerationStats:
    deleted_count: int
    kept_count: int
    protected_count: int


class EventStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS copy_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_chat_id TEXT NOT NULL,
                    source_title TEXT NOT NULL,
                    source_message_id INTEGER NOT NULL,
                    target_chat_id TEXT NOT NULL,
                    copied_message_id INTEGER,
                    ok INTEGER NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    created_at_ts REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sent_reports (
                    period_type TEXT NOT NULL,
                    period_key TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    PRIMARY KEY (period_type, period_key)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS moderation_posts (
                    source_chat_id TEXT NOT NULL,
                    source_title TEXT NOT NULL,
                    source_message_id INTEGER NOT NULL,
                    posted_at TEXT NOT NULL,
                    posted_at_ts REAL NOT NULL,
                    thumbs_up INTEGER NOT NULL DEFAULT 0,
                    thumbs_down INTEGER NOT NULL DEFAULT 0,
                    poop_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'watching',
                    delete_after TEXT NOT NULL DEFAULT '',
                    delete_after_ts REAL,
                    owner_notice_message_id INTEGER,
                    updated_at TEXT NOT NULL,
                    updated_at_ts REAL NOT NULL,
                    PRIMARY KEY (source_chat_id, source_message_id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS moderation_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_chat_id TEXT NOT NULL,
                    source_message_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    thumbs_up INTEGER NOT NULL DEFAULT 0,
                    thumbs_down INTEGER NOT NULL DEFAULT 0,
                    poop_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    created_at_ts REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_copy_events_created_at_ts ON copy_events(created_at_ts)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_copy_events_ok_created_at_ts ON copy_events(ok, created_at_ts)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_copy_events_target_message "
                "ON copy_events(target_chat_id, copied_message_id, ok)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_moderation_posts_due ON moderation_posts(status, delete_after_ts)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_moderation_events_type_created ON moderation_events(event_type, created_at_ts)"
            )
            self._ensure_column("moderation_posts", "poop_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column("moderation_events", "poop_count", "INTEGER NOT NULL DEFAULT 0")

    def _ensure_column(self, table: str, column: str, declaration: str) -> None:
        columns = {str(row["name"]) for row in self._conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def _insert_event(
        self,
        source_chat_id: str,
        source_title: str,
        source_message_id: int,
        target_chat_id: str,
        copied_message_id: int | None,
        ok: bool,
        error: str,
        at: datetime,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO copy_events (
                    source_chat_id, source_title, source_message_id, target_chat_id,
                    copied_message_id, ok, error, created_at, created_at_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_chat_id,
                    source_title,
                    int(source_message_id),
                    target_chat_id,
                    copied_message_id,
                    1 if ok else 0,
                    error,
                    at.isoformat(),
                    at.timestamp(),
                ),
            )

    def record_copy_success(
        self,
        source_chat_id: str,
        source_title: str,
        source_message_id: int,
        target_chat_id: str,
        copied_message_id: int | None,
        at: datetime,
    ) -> None:
        self._insert_event(source_chat_id, source_title, source_message_id, target_chat_id, copied_message_id, True, "", at)

    def record_copy_failure(
        self,
        source_chat_id: str,
        source_title: str,
        source_message_id: int,
        target_chat_id: str,
        error: str,
        at: datetime,
    ) -> None:
        self._insert_event(source_chat_id, source_title, source_message_id, target_chat_id, None, False, error[:500], at)

    def get_copy_event_by_target_message(self, target_chat_id: str, copied_message_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM copy_events
                WHERE target_chat_id = ? AND copied_message_id = ? AND ok = 1
                ORDER BY created_at_ts DESC, id DESC
                LIMIT 1
                """,
                (str(target_chat_id), int(copied_message_id)),
            ).fetchone()
        return dict(row) if row else None

    def stats_between(self, start: datetime, end: datetime) -> Stats:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    SUM(CASE WHEN ok = 1 THEN 1 ELSE 0 END) AS success_count,
                    SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS failure_count,
                    COUNT(*) AS total_count
                FROM copy_events
                WHERE created_at_ts >= ? AND created_at_ts < ?
                """,
                (start.timestamp(), end.timestamp()),
            ).fetchone()
            last_success = self._conn.execute(
                """
                SELECT created_at FROM copy_events
                WHERE ok = 1 AND created_at_ts >= ? AND created_at_ts < ?
                ORDER BY created_at_ts DESC LIMIT 1
                """,
                (start.timestamp(), end.timestamp()),
            ).fetchone()
            first_success = self._conn.execute(
                """
                SELECT created_at FROM copy_events
                WHERE ok = 1 AND created_at_ts >= ? AND created_at_ts < ?
                ORDER BY created_at_ts ASC LIMIT 1
                """,
                (start.timestamp(), end.timestamp()),
            ).fetchone()
            last_failure = self._conn.execute(
                """
                SELECT error FROM copy_events
                WHERE ok = 0 AND created_at_ts >= ? AND created_at_ts < ?
                ORDER BY created_at_ts DESC LIMIT 1
                """,
                (start.timestamp(), end.timestamp()),
            ).fetchone()
            peak_hour = self._conn.execute(
                """
                SELECT CAST(substr(created_at, 12, 2) AS INTEGER) AS hour, COUNT(*) AS count
                FROM copy_events
                WHERE ok = 1 AND created_at_ts >= ? AND created_at_ts < ?
                GROUP BY hour
                ORDER BY count DESC, hour ASC
                LIMIT 1
                """,
                (start.timestamp(), end.timestamp()),
            ).fetchone()
            peak_day = self._conn.execute(
                """
                SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count
                FROM copy_events
                WHERE ok = 1 AND created_at_ts >= ? AND created_at_ts < ?
                GROUP BY day
                ORDER BY count DESC, day ASC
                LIMIT 1
                """,
                (start.timestamp(), end.timestamp()),
            ).fetchone()
        success = int(rows["success_count"] or 0)
        failure = int(rows["failure_count"] or 0)
        return Stats(
            success_count=success,
            failure_count=failure,
            total_count=int(rows["total_count"] or 0),
            first_success_at=str(first_success["created_at"]) if first_success else "-",
            last_success_at=str(last_success["created_at"]) if last_success else "-",
            last_failure=str(last_failure["error"]) if last_failure else "-",
            peak_hour=int(peak_hour["hour"]) if peak_hour else None,
            peak_hour_count=int(peak_hour["count"] or 0) if peak_hour else 0,
            peak_day=str(peak_day["day"]) if peak_day else "",
            peak_day_count=int(peak_day["count"] or 0) if peak_day else 0,
        )

    def failure_summary_between(self, start: datetime, end: datetime, limit: int = 3) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT error, COUNT(*) AS count
                FROM copy_events
                WHERE ok = 0 AND created_at_ts >= ? AND created_at_ts < ? AND error != ''
                GROUP BY error
                ORDER BY count DESC, MAX(created_at_ts) DESC
                LIMIT ?
                """,
                (start.timestamp(), end.timestamp(), int(limit)),
            ).fetchall()
        return [{"error": str(row["error"]), "count": int(row["count"] or 0)} for row in rows]

    def record_moderation_post(
        self,
        source_chat_id: str,
        source_title: str,
        source_message_id: int,
        at: datetime,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO moderation_posts (
                    source_chat_id, source_title, source_message_id,
                    posted_at, posted_at_ts, updated_at, updated_at_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(source_chat_id),
                    str(source_title),
                    int(source_message_id),
                    at.isoformat(),
                    at.timestamp(),
                    at.isoformat(),
                    at.timestamp(),
                ),
            )

    def get_moderation_post(self, source_chat_id: str, source_message_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM moderation_posts WHERE source_chat_id = ? AND source_message_id = ?",
                (str(source_chat_id), int(source_message_id)),
            ).fetchone()
        return dict(row) if row else None

    def update_moderation_reactions(
        self,
        source_chat_id: str,
        source_message_id: int,
        thumbs_up: int,
        thumbs_down: int,
        at: datetime,
        poop_count: int = 0,
    ) -> dict | None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE moderation_posts
                SET thumbs_up = ?, thumbs_down = ?, poop_count = ?, updated_at = ?, updated_at_ts = ?
                WHERE source_chat_id = ? AND source_message_id = ?
                """,
                (
                    max(0, int(thumbs_up)),
                    max(0, int(thumbs_down)),
                    max(0, int(poop_count)),
                    at.isoformat(),
                    at.timestamp(),
                    str(source_chat_id),
                    int(source_message_id),
                ),
            )
        return self.get_moderation_post(source_chat_id, source_message_id)

    def set_moderation_pending(
        self,
        source_chat_id: str,
        source_message_id: int,
        delete_after: datetime,
        at: datetime,
    ) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE moderation_posts
                SET status = 'pending', delete_after = ?, delete_after_ts = ?,
                    owner_notice_message_id = NULL, updated_at = ?, updated_at_ts = ?
                WHERE source_chat_id = ? AND source_message_id = ? AND status = 'watching'
                """,
                (
                    delete_after.isoformat(),
                    delete_after.timestamp(),
                    at.isoformat(),
                    at.timestamp(),
                    str(source_chat_id),
                    int(source_message_id),
                ),
            )
        return int(cursor.rowcount or 0) == 1

    def set_moderation_notice(
        self,
        source_chat_id: str,
        source_message_id: int,
        notice_message_id: int,
        at: datetime,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE moderation_posts
                SET owner_notice_message_id = ?, updated_at = ?, updated_at_ts = ?
                WHERE source_chat_id = ? AND source_message_id = ? AND status IN ('pending', 'protected')
                """,
                (
                    int(notice_message_id),
                    at.isoformat(),
                    at.timestamp(),
                    str(source_chat_id),
                    int(source_message_id),
                ),
            )

    def cancel_moderation_pending(self, source_chat_id: str, source_message_id: int, at: datetime) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE moderation_posts
                SET status = 'watching', delete_after = '', delete_after_ts = NULL,
                    owner_notice_message_id = NULL, updated_at = ?, updated_at_ts = ?
                WHERE source_chat_id = ? AND source_message_id = ? AND status = 'pending'
                """,
                (at.isoformat(), at.timestamp(), str(source_chat_id), int(source_message_id)),
            )
        return int(cursor.rowcount or 0) == 1

    def due_moderation_posts(self, at: datetime) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM moderation_posts
                WHERE status = 'pending' AND delete_after_ts IS NOT NULL AND delete_after_ts <= ?
                ORDER BY delete_after_ts ASC
                """,
                (at.timestamp(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def complete_moderation(
        self,
        source_chat_id: str,
        source_message_id: int,
        status: str,
        event_type: str,
        reason: str,
        at: datetime,
        allow_terminal_delete: bool = False,
    ) -> bool:
        with self._lock, self._conn:
            row = self._conn.execute(
                """
                SELECT status, thumbs_up, thumbs_down, poop_count FROM moderation_posts
                WHERE source_chat_id = ? AND source_message_id = ?
                """,
                (str(source_chat_id), int(source_message_id)),
            ).fetchone()
            current_status = str(row["status"]) if row else ""
            if not row or current_status == "deleted":
                return False
            if current_status in {"kept", "failed"} and not (allow_terminal_delete and status == "deleted"):
                return False
            if str(row["status"]) == str(status):
                return False
            self._conn.execute(
                """
                UPDATE moderation_posts
                SET status = ?, delete_after = '', delete_after_ts = NULL,
                    updated_at = ?, updated_at_ts = ?
                WHERE source_chat_id = ? AND source_message_id = ?
                """,
                (
                    str(status),
                    at.isoformat(),
                    at.timestamp(),
                    str(source_chat_id),
                    int(source_message_id),
                ),
            )
            self._conn.execute(
                """
                INSERT INTO moderation_events (
                    source_chat_id, source_message_id, event_type, reason,
                    thumbs_up, thumbs_down, poop_count, created_at, created_at_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(source_chat_id),
                    int(source_message_id),
                    str(event_type),
                    str(reason),
                    int(row["thumbs_up"] or 0),
                    int(row["thumbs_down"] or 0),
                    int(row["poop_count"] or 0),
                    at.isoformat(),
                    at.timestamp(),
                ),
            )
        return True

    def count_recent_auto_deletions(self, since: datetime) -> int:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS count FROM moderation_events
                WHERE event_type = 'deleted' AND reason IN ('auto', 'poop') AND created_at_ts >= ?
                """,
                (since.timestamp(),),
            ).fetchone()
        return int(row["count"] or 0)

    def moderation_stats_between(self, start: datetime, end: datetime) -> ModerationStats:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    SUM(CASE WHEN event_type = 'deleted' THEN 1 ELSE 0 END) AS deleted_count,
                    SUM(CASE WHEN event_type = 'kept' THEN 1 ELSE 0 END) AS kept_count,
                    SUM(CASE WHEN event_type = 'protected' THEN 1 ELSE 0 END) AS protected_count
                FROM moderation_events
                WHERE created_at_ts >= ? AND created_at_ts < ?
                """,
                (start.timestamp(), end.timestamp()),
            ).fetchone()
        return ModerationStats(
            deleted_count=int(row["deleted_count"] or 0),
            kept_count=int(row["kept_count"] or 0),
            protected_count=int(row["protected_count"] or 0),
        )

    def prune_copy_events_before(self, cutoff: datetime) -> int:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM copy_events WHERE created_at_ts < ?",
                (cutoff.timestamp(),),
            )
            self._conn.execute(
                "DELETE FROM moderation_events WHERE created_at_ts < ?",
                (cutoff.timestamp(),),
            )
            self._conn.execute(
                "DELETE FROM moderation_posts WHERE posted_at_ts < ?",
                (cutoff.timestamp(),),
            )
        return int(cursor.rowcount or 0)

    def health_check(self, at: datetime) -> bool:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO state (key, value) VALUES ('health_check_at', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (at.isoformat(),),
            )
        return True

    def backup_database(self, at: datetime, keep_days: int = 7) -> str | None:
        if self.path == ":memory:":
            return None
        db_path = Path(self.path)
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"assistant_{at:%Y%m%d}.sqlite3"
        with self._lock:
            backup_conn = sqlite3.connect(backup_path)
            try:
                self._conn.backup(backup_conn)
            finally:
                backup_conn.close()

        backups = sorted(backup_dir.glob("assistant_*.sqlite3"))
        for old_backup in backups[:-max(1, int(keep_days))]:
            try:
                old_backup.unlink()
            except OSError:
                pass
        return str(backup_path)

    def recent_events(self, limit: int = 8) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT source_title, source_message_id, ok, error, created_at
                FROM copy_events
                ORDER BY created_at_ts DESC LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def was_report_sent(self, period_type: str, period_key: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM sent_reports WHERE period_type = ? AND period_key = ?",
                (period_type, period_key),
            ).fetchone()
        return row is not None

    def mark_report_sent(self, period_type: str, period_key: str, at: datetime) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO sent_reports (period_type, period_key, sent_at) VALUES (?, ?, ?)",
                (period_type, period_key, at.isoformat()),
            )

    def get_state(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM state WHERE key = ?", (str(key),)).fetchone()
        if not row:
            return None
        return str(row["value"])

    def set_state(self, key: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(key), str(value)),
            )

    def get_offset(self) -> int | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM state WHERE key = 'update_offset'").fetchone()
        if not row:
            return None
        try:
            return int(row["value"])
        except Exception:
            return None

    def set_offset(self, offset: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO state (key, value) VALUES ('update_offset', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(int(offset)),),
            )

    def close(self) -> None:
        self._conn.close()
