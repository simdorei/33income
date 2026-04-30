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
                """
            )

    def seed_mock_data(self, agent_count: int = 18) -> None:
        now = now_utc_iso()
        with self._connect() as conn:
            existing = conn.execute("SELECT COUNT(*) AS cnt FROM agents").fetchone()["cnt"]
            if existing > 0:
                return

            for index in range(1, agent_count + 1):
                pc_id = f"pc-{index:02d}"
                hostname = f"WIN-PC-{index:02d}"
                ip_address = f"192.168.10.{100 + index}"
                agent_status = "online" if index % 2 == 1 else "offline"

                if index <= 9:
                    bot_type = "sender"
                    bot_seq = index
                else:
                    bot_type = "reporter"
                    bot_seq = index - 9

                bot_id = f"{bot_type}-{bot_seq:02d}"
                bot_status = "running" if agent_status == "online" else "idle"
                step = "mock_cycle" if agent_status == "online" else "waiting_for_start"

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
                        agent_status,
                        "0.1.0",
                        bot_id,
                        now,
                        now,
                    ),
                )

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
                        bot_status,
                        f"profiles\\{bot_id}",
                        now,
                        step,
                        0,
                        0,
                        now,
                    ),
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

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agents (
                    pc_id, hostname, ip_address, status,
                    agent_version, assigned_bot_ids, last_heartbeat_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pc_id) DO UPDATE SET
                    hostname = excluded.hostname,
                    ip_address = excluded.ip_address,
                    status = excluded.status,
                    assigned_bot_ids = excluded.assigned_bot_ids,
                    last_heartbeat_at = excluded.last_heartbeat_at,
                    updated_at = excluded.updated_at
                """,
                (
                    pc_id,
                    hostname,
                    ip_address,
                    agent_status,
                    "0.1.0",
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

    def list_recent_commands(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM commands ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]
