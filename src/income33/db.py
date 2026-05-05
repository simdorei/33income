from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from income33.utils.time import now_utc_iso


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {k: row[k] for k in row.keys()}

    @staticmethod
    def _ensure_columns(
        conn: sqlite3.Connection,
        table: str,
        columns: dict[str, str],
    ) -> None:
        existing_columns = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for column_name, column_definition in columns.items():
            if column_name not in existing_columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_definition}")

    @staticmethod
    def _optional_bool_to_int(value: Any) -> int | None:
        if value is None:
            return None
        return 1 if bool(value) else 0

    def init_db(self) -> None:
        db_path = Path(self.path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    pc_id TEXT PRIMARY KEY,
                    hostname TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    status TEXT NOT NULL,
                    agent_version TEXT,
                    repo_path TEXT,
                    repo_is_git INTEGER,
                    git_head TEXT,
                    git_head_short TEXT,
                    git_branch TEXT,
                    git_origin_main TEXT,
                    git_up_to_date INTEGER,
                    git_dirty INTEGER,
                    version_status TEXT,
                    assigned_bot_ids TEXT,
                    last_heartbeat_at TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bots (
                    bot_id TEXT PRIMARY KEY,
                    bot_type TEXT NOT NULL,
                    pc_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    profile_dir TEXT,
                    pid INTEGER,
                    last_heartbeat_at TEXT,
                    current_step TEXT,
                    current_target_id TEXT,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_message TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bot_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id TEXT NOT NULL,
                    pc_id TEXT NOT NULL,
                    level TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_type TEXT NOT NULL,
                    external_id TEXT,
                    status TEXT NOT NULL,
                    current_step TEXT,
                    assigned_bot_id TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pc_id TEXT NOT NULL,
                    bot_id TEXT NOT NULL,
                    command TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT,
                    created_at TEXT NOT NULL,
                    picked_at TEXT,
                    finished_at TEXT,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS repeat_schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id TEXT NOT NULL,
                    pc_id TEXT NOT NULL,
                    command TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    interval_sec INTEGER NOT NULL,
                    next_run_at TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_queued_command_id INTEGER,
                    last_queued_at TEXT,
                    last_error_message TEXT,
                    UNIQUE(bot_id, command)
                );
                """
            )
            self._ensure_columns(
                conn,
                "agents",
                {
                    "repo_path": "TEXT",
                    "repo_is_git": "INTEGER",
                    "git_head": "TEXT",
                    "git_head_short": "TEXT",
                    "git_branch": "TEXT",
                    "git_origin_main": "TEXT",
                    "git_up_to_date": "INTEGER",
                    "git_dirty": "INTEGER",
                    "version_status": "TEXT",
                },
            )

    @staticmethod
    def _slot_identity(index: int) -> tuple[str, str, str, str]:
        pc_id = f"pc-{index:02d}"
        hostname = f"WIN-PC-{index:02d}"
        ip_address = f"192.168.10.{100 + index}"
        if index <= 9:
            bot_type = "sender"
            bot_seq = index
        else:
            bot_type = "reporter"
            bot_seq = index - 9
        bot_id = f"{bot_type}-{bot_seq:02d}"
        return pc_id, hostname, ip_address, bot_id

    @staticmethod
    def _bot_type_for_id(bot_id: str) -> str:
        return "sender" if bot_id.startswith("sender") else "reporter"

    @staticmethod
    def _is_legacy_placeholder_bot(row: sqlite3.Row | None) -> bool:
        if row is None:
            return False
        # Earlier placeholder rows used a visible current_step value and
        # sometimes included synthetic heartbeat times. Treat that state as
        # seeded data even when last_heartbeat_at is not NULL.
        legacy_placeholder_step = "".join(("mo", "ck_cycle"))
        return row["current_step"] == legacy_placeholder_step

    @staticmethod
    def _has_legacy_placeholder_agent_identity(
        row: sqlite3.Row | None,
        hostname: str,
        ip_address: str,
    ) -> bool:
        if row is None:
            return False
        return (
            row["hostname"] == hostname
            and row["ip_address"] == ip_address
            and row["agent_version"] == "0.1.0"
        )

    def ensure_agent_slots(self, agent_count: int = 18) -> None:
        now = now_utc_iso()
        slot_count = max(agent_count, 18)
        with self._connect() as conn:
            for index in range(1, slot_count + 1):
                pc_id, hostname, ip_address, bot_id = self._slot_identity(index)
                bot_type = self._bot_type_for_id(bot_id)

                agent_row = conn.execute(
                    "SELECT * FROM agents WHERE pc_id = ?",
                    (pc_id,),
                ).fetchone()
                bot_row = conn.execute(
                    "SELECT * FROM bots WHERE bot_id = ?",
                    (bot_id,),
                ).fetchone()

                bot_is_legacy_placeholder = self._is_legacy_placeholder_bot(bot_row)
                agent_has_legacy_identity = self._has_legacy_placeholder_agent_identity(
                    agent_row,
                    hostname,
                    ip_address,
                )

                if agent_row is None:
                    conn.execute(
                        """
                        INSERT INTO agents (
                            pc_id, hostname, ip_address, status, agent_version,
                            assigned_bot_ids, last_heartbeat_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            pc_id,
                            hostname,
                            ip_address,
                            "offline",
                            "0.1.0",
                            bot_id,
                            None,
                            now,
                        ),
                    )
                elif agent_has_legacy_identity and bot_is_legacy_placeholder:
                    conn.execute(
                        """
                        UPDATE agents
                        SET status = 'offline',
                            assigned_bot_ids = ?,
                            last_heartbeat_at = NULL,
                            error_code = NULL,
                            error_message = NULL,
                            updated_at = ?
                        WHERE pc_id = ?
                        """,
                        (bot_id, now, pc_id),
                    )

                if bot_row is None:
                    conn.execute(
                        """
                        INSERT INTO bots (
                            bot_id, bot_type, pc_id, status, profile_dir,
                            last_heartbeat_at, current_step, success_count,
                            failure_count, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            bot_id,
                            bot_type,
                            pc_id,
                            "connection_required",
                            f"profiles\\{bot_id}",
                            None,
                            "접속필요",
                            0,
                            0,
                            now,
                        ),
                    )
                elif bot_is_legacy_placeholder:
                    conn.execute(
                        """
                        UPDATE bots
                        SET status = 'connection_required',
                            last_heartbeat_at = NULL,
                            current_step = '접속필요',
                            success_count = 0,
                            failure_count = 0,
                            error_code = NULL,
                            error_message = NULL,
                            updated_at = ?
                        WHERE bot_id = ?
                        """,
                        (now, bot_id),
                    )

    def list_agents(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agents ORDER BY pc_id ASC"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_bots(self, bot_type: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if bot_type:
                rows = conn.execute(
                    "SELECT * FROM bots WHERE bot_type = ? ORDER BY bot_id ASC",
                    (bot_type,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM bots ORDER BY bot_id ASC").fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_agent(self, pc_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM agents WHERE pc_id = ?", (pc_id,)).fetchone()
        return self._row_to_dict(row)

    def get_bot(self, bot_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM bots WHERE bot_id = ?", (bot_id,)).fetchone()
        return self._row_to_dict(row)

    def get_summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            total_agents = conn.execute("SELECT COUNT(*) AS cnt FROM agents").fetchone()["cnt"]
            online_agents = conn.execute(
                "SELECT COUNT(*) AS cnt FROM agents WHERE status = 'online'"
            ).fetchone()["cnt"]
            offline_agents = conn.execute(
                "SELECT COUNT(*) AS cnt FROM agents WHERE status = 'offline'"
            ).fetchone()["cnt"]
            total_bots = conn.execute("SELECT COUNT(*) AS cnt FROM bots").fetchone()["cnt"]
            sender_bots = conn.execute(
                "SELECT COUNT(*) AS cnt FROM bots WHERE bot_type = 'sender'"
            ).fetchone()["cnt"]
            reporter_bots = conn.execute(
                "SELECT COUNT(*) AS cnt FROM bots WHERE bot_type = 'reporter'"
            ).fetchone()["cnt"]

            status_rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM bots GROUP BY status"
            ).fetchall()
            status_counts = {row["status"]: row["cnt"] for row in status_rows}

        return {
            "total_agents": total_agents,
            "online_agents": online_agents,
            "offline_agents": offline_agents,
            "total_bots": total_bots,
            "sender_bots": sender_bots,
            "reporter_bots": reporter_bots,
            "bot_status_counts": status_counts,
        }

    def upsert_repeat_schedule(
        self,
        *,
        bot_id: str,
        pc_id: str,
        command: str,
        payload: dict[str, Any],
        interval_sec: int,
        next_run_at: str,
    ) -> dict[str, Any]:
        now = now_utc_iso()
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO repeat_schedules (
                    bot_id, pc_id, command, payload_json, interval_sec,
                    next_run_at, enabled, created_at, updated_at,
                    last_error_message
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, NULL)
                ON CONFLICT(bot_id, command) DO UPDATE SET
                    pc_id = excluded.pc_id,
                    payload_json = excluded.payload_json,
                    interval_sec = excluded.interval_sec,
                    next_run_at = excluded.next_run_at,
                    enabled = 1,
                    updated_at = excluded.updated_at,
                    last_error_message = NULL
                """,
                (bot_id, pc_id, command, payload_json, interval_sec, next_run_at, now, now),
            )
            row = conn.execute(
                "SELECT * FROM repeat_schedules WHERE bot_id = ? AND command = ?",
                (bot_id, command),
            ).fetchone()
        return self._row_to_dict(row)  # type: ignore[arg-type]

    def disable_repeat_schedule(self, *, bot_id: str, command: str) -> dict[str, Any] | None:
        now = now_utc_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE repeat_schedules
                SET enabled = 0, updated_at = ?
                WHERE bot_id = ? AND command = ?
                """,
                (now, bot_id, command),
            )
            row = conn.execute(
                "SELECT * FROM repeat_schedules WHERE bot_id = ? AND command = ?",
                (bot_id, command),
            ).fetchone()
        return self._row_to_dict(row)

    def list_repeat_schedules(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM repeat_schedules ORDER BY bot_id ASC, command ASC"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_due_repeat_schedules(self, now: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM repeat_schedules
                WHERE enabled = 1 AND next_run_at <= ?
                ORDER BY next_run_at ASC, id ASC
                """,
                (now,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def mark_repeat_schedule_queued(
        self,
        *,
        schedule_id: int,
        command_id: int,
        next_run_at: str,
    ) -> dict[str, Any]:
        now = now_utc_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE repeat_schedules
                SET next_run_at = ?,
                    updated_at = ?,
                    last_queued_command_id = ?,
                    last_queued_at = ?,
                    last_error_message = NULL
                WHERE id = ?
                """,
                (next_run_at, now, command_id, now, schedule_id),
            )
            row = conn.execute(
                "SELECT * FROM repeat_schedules WHERE id = ?",
                (schedule_id,),
            ).fetchone()
        return self._row_to_dict(row)  # type: ignore[arg-type]

    def mark_repeat_schedule_error(self, *, schedule_id: int, message: str) -> dict[str, Any] | None:
        now = now_utc_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE repeat_schedules
                SET updated_at = ?, last_error_message = ?
                WHERE id = ?
                """,
                (now, message, schedule_id),
            )
            row = conn.execute(
                "SELECT * FROM repeat_schedules WHERE id = ?",
                (schedule_id,),
            ).fetchone()
        return self._row_to_dict(row)

    def has_active_command(self, *, bot_id: str, command: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM commands
                WHERE bot_id = ? AND command = ? AND status IN ('pending', 'running')
                LIMIT 1
                """,
                (bot_id, command),
            ).fetchone()
        return row is not None

    def enqueue_command(
        self,
        pc_id: str,
        bot_id: str,
        command: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = now_utc_iso()
        payload_json = json.dumps(payload or {}, ensure_ascii=False)

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO commands (
                    pc_id, bot_id, command, status,
                    payload_json, created_at
                ) VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (pc_id, bot_id, command, payload_json, now),
            )
            command_id = cursor.lastrowid

            mapped_state = {
                "start": ("starting", "starting"),
                "stop": ("stopped", "stopped"),
                "restart": ("restarting", "restarting"),
                "open_login": ("login_required", "login_required"),
                "login_done": ("idle", "idle"),
                "fill_login": ("login_filling", "login_filling"),
                "submit_auth_code": ("manual_required", "auth_code_queued"),
                "refresh_page": ("refreshing", "session_refresh"),
            }.get(command)
            if mapped_state is not None:
                mapped_status, mapped_step = mapped_state
                conn.execute(
                    "UPDATE bots SET status = ?, current_step = ?, updated_at = ? WHERE bot_id = ?",
                    (mapped_status, mapped_step, now, bot_id),
                )

            row = conn.execute("SELECT * FROM commands WHERE id = ?", (command_id,)).fetchone()
        return self._row_to_dict(row)  # type: ignore[arg-type]

    def poll_commands(self, pc_id: str, limit: int = 10) -> list[dict[str, Any]]:
        now = now_utc_iso()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM commands
                WHERE pc_id = ? AND status = 'pending'
                ORDER BY id ASC
                LIMIT ?
                """,
                (pc_id, limit),
            ).fetchall()

            command_ids = [row["id"] for row in rows]
            if command_ids:
                placeholders = ",".join("?" for _ in command_ids)
                conn.execute(
                    f"UPDATE commands SET status = 'running', picked_at = ? WHERE id IN ({placeholders})",
                    (now, *command_ids),
                )
                refreshed = conn.execute(
                    f"SELECT * FROM commands WHERE id IN ({placeholders}) ORDER BY id ASC",
                    tuple(command_ids),
                ).fetchall()
            else:
                refreshed = []

        return [self._row_to_dict(row) for row in refreshed]

    def complete_command(
        self,
        command_id: int,
        status: str = "done",
        error_message: str | None = None,
    ) -> dict[str, Any]:
        now = now_utc_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE commands
                SET status = ?, finished_at = ?, error_message = ?
                WHERE id = ?
                """,
                (status, now, error_message, command_id),
            )
            command_row = conn.execute(
                "SELECT * FROM commands WHERE id = ?",
                (command_id,),
            ).fetchone()
            if command_row is None:
                raise KeyError(f"command not found: {command_id}")

            bot_id = command_row["bot_id"]
            command = command_row["command"]
            if status == "done":
                mapped_state = {
                    "start": ("running", "running"),
                    "stop": ("stopped", "stopped"),
                    "restart": ("running", "running"),
                    "open_login": ("login_opened", "login_opened"),
                    "login_done": ("idle", "idle"),
                    "fill_login": ("login_auth_required", "login_auth_required"),
                    "submit_auth_code": ("session_active", "session_active"),
                    "refresh_page": ("session_active", "session_refresh"),
                }.get(command)
            else:
                mapped_state = ("crashed", "command_failed")

            if mapped_state:
                mapped_status, mapped_step = mapped_state
                conn.execute(
                    "UPDATE bots SET status = ?, current_step = ?, updated_at = ? WHERE bot_id = ?",
                    (mapped_status, mapped_step, now, bot_id),
                )

            if command == "submit_auth_code":
                conn.execute(
                    "UPDATE commands SET payload_json = ? WHERE id = ?",
                    (json.dumps({"auth_code": "***"}, ensure_ascii=False), command_id),
                )

            refreshed = conn.execute(
                "SELECT * FROM commands WHERE id = ?",
                (command_id,),
            ).fetchone()

        return self._row_to_dict(refreshed)  # type: ignore[arg-type]

    def upsert_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = now_utc_iso()
        pc_id = payload["pc_id"]
        bot_id = payload.get("bot_id")
        agent_status = payload.get("agent_status", "online")
        hostname = payload.get("hostname", "UNKNOWN")
        ip_address = payload.get("ip_address", "0.0.0.0")
        agent_version = payload.get("agent_version") or "0.1.0"
        repo_path = payload.get("repo_path")
        repo_is_git = self._optional_bool_to_int(payload.get("repo_is_git"))
        git_head = payload.get("git_head")
        git_head_short = payload.get("git_head_short")
        git_branch = payload.get("git_branch")
        git_origin_main = payload.get("git_origin_main")
        git_up_to_date = self._optional_bool_to_int(payload.get("git_up_to_date"))
        git_dirty = self._optional_bool_to_int(payload.get("git_dirty"))
        version_status = payload.get("version_status")

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agents (
                    pc_id, hostname, ip_address, status,
                    agent_version, repo_path, repo_is_git, git_head,
                    git_head_short, git_branch, git_origin_main,
                    git_up_to_date, git_dirty, version_status,
                    assigned_bot_ids, last_heartbeat_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pc_id) DO UPDATE SET
                    hostname = excluded.hostname,
                    ip_address = excluded.ip_address,
                    status = excluded.status,
                    agent_version = excluded.agent_version,
                    repo_path = excluded.repo_path,
                    repo_is_git = excluded.repo_is_git,
                    git_head = excluded.git_head,
                    git_head_short = excluded.git_head_short,
                    git_branch = excluded.git_branch,
                    git_origin_main = excluded.git_origin_main,
                    git_up_to_date = excluded.git_up_to_date,
                    git_dirty = excluded.git_dirty,
                    version_status = excluded.version_status,
                    assigned_bot_ids = excluded.assigned_bot_ids,
                    last_heartbeat_at = excluded.last_heartbeat_at,
                    updated_at = excluded.updated_at
                """,
                (
                    pc_id,
                    hostname,
                    ip_address,
                    agent_status,
                    agent_version,
                    repo_path,
                    repo_is_git,
                    git_head,
                    git_head_short,
                    git_branch,
                    git_origin_main,
                    git_up_to_date,
                    git_dirty,
                    version_status,
                    bot_id,
                    now,
                    now,
                ),
            )

            if bot_id:
                bot_type = "sender" if bot_id.startswith("sender") else "reporter"
                bot_status = payload.get("bot_status", "running")
                current_step = payload.get("current_step", "heartbeat")
                success_count = int(payload.get("success_count", 0))
                failure_count = int(payload.get("failure_count", 0))

                conn.execute(
                    """
                    INSERT INTO bots (
                        bot_id, bot_type, pc_id, status, profile_dir,
                        last_heartbeat_at, current_step, success_count,
                        failure_count, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(bot_id) DO UPDATE SET
                        bot_type = excluded.bot_type,
                        pc_id = excluded.pc_id,
                        status = excluded.status,
                        last_heartbeat_at = excluded.last_heartbeat_at,
                        current_step = excluded.current_step,
                        success_count = excluded.success_count,
                        failure_count = excluded.failure_count,
                        updated_at = excluded.updated_at
                    """,
                    (
                        bot_id,
                        bot_type,
                        pc_id,
                        bot_status,
                        f"profiles\\{bot_id}",
                        now,
                        current_step,
                        success_count,
                        failure_count,
                        now,
                    ),
                )

            refreshed = conn.execute(
                "SELECT * FROM agents WHERE pc_id = ?",
                (pc_id,),
            ).fetchone()

        return self._row_to_dict(refreshed)  # type: ignore[arg-type]

    def clear_active_commands(self, *, bot_id: str, reason: str = "cleared_by_operator") -> int:
        now = now_utc_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE commands
                SET status = 'failed', finished_at = ?, error_message = ?
                WHERE bot_id = ? AND status IN ('pending', 'running')
                """,
                (now, reason, bot_id),
            )
        return int(cursor.rowcount or 0)

    def list_active_commands(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM commands
                WHERE status IN ('pending', 'running')
                ORDER BY bot_id ASC, id ASC
                """
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_recent_commands(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM commands ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]
