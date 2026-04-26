from __future__ import annotations

from typing import Any

from income33.db import Database


class ControlTowerService:
    def __init__(self, db: Database, mock_agent_count: int = 18) -> None:
        self.db = db
        self.mock_agent_count = mock_agent_count

    def bootstrap(self) -> None:
        self.db.init_db()
        self.db.seed_mock_data(agent_count=self.mock_agent_count)

    def get_summary(self) -> dict[str, Any]:
        return self.db.get_summary()

    def list_agents(self) -> list[dict[str, Any]]:
        return self.db.list_agents()

    def list_bots(self, bot_type: str | None = None) -> list[dict[str, Any]]:
        return self.db.list_bots(bot_type=bot_type)

    def list_recent_commands(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.list_recent_commands(limit=limit)

    def queue_bot_command(
        self,
        bot_id: str,
        command: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bot = self.db.get_bot(bot_id)
        if bot is None:
            raise KeyError(f"bot not found: {bot_id}")
        return self.db.enqueue_command(
            pc_id=bot["pc_id"],
            bot_id=bot_id,
            command=command,
            payload=payload,
        )

    def poll_agent_commands(self, pc_id: str, limit: int = 10) -> list[dict[str, Any]]:
        return self.db.poll_commands(pc_id=pc_id, limit=limit)

    def complete_command(
        self,
        command_id: int,
        status: str,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        return self.db.complete_command(
            command_id=command_id,
            status=status,
            error_message=error_message,
        )

    def receive_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.db.upsert_heartbeat(payload)

    def build_dashboard(self) -> dict[str, Any]:
        return {
            "summary": self.get_summary(),
            "agents": self.list_agents(),
            "bots": self.list_bots(),
            "commands": self.list_recent_commands(limit=20),
        }
