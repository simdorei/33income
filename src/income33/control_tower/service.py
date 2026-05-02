from __future__ import annotations

import logging
from typing import Any

from income33.db import Database

logger = logging.getLogger("income33.control_tower.service")


_SENDER_ONLY_COMMANDS = {
    "send_expected_tax_amounts",
    "send_bookkeeping_expected_tax_amount",
    "send_rate_based_bookkeeping_expected_tax_amount",
    "preview_rate_based_bookkeeping_expected_tax_amounts",
    "send_rate_based_bookkeeping_expected_tax_amounts",
}


def _sanitize_command_for_response(command: dict[str, Any]) -> dict[str, Any]:
    if command.get("command") != "submit_auth_code":
        return command
    sanitized = dict(command)
    sanitized["payload_json"] = '{"auth_code": "***"}'
    return sanitized


class ControlTowerService:
    def __init__(
        self,
        db: Database,
        bootstrap_agent_count: int = 18,
    ) -> None:
        self.db = db
        self.bootstrap_agent_count = bootstrap_agent_count

    def bootstrap(self) -> None:
        self.db.init_db()
        self.db.ensure_agent_slots(agent_count=self.bootstrap_agent_count)
        logger.info(
            "control_tower_bootstrap_done bootstrap_agent_count=%s",
            self.bootstrap_agent_count,
        )

    def get_summary(self) -> dict[str, Any]:
        return self.db.get_summary()

    def list_agents(self) -> list[dict[str, Any]]:
        return self.db.list_agents()

    def list_bots(self, bot_type: str | None = None) -> list[dict[str, Any]]:
        return self.db.list_bots(bot_type=bot_type)

    def list_recent_commands(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.list_recent_commands(limit=limit)

    def _normalize_command_payload(
        self,
        *,
        bot: dict[str, Any],
        command: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")

        envelope_payload = payload
        envelope_target = None
        if isinstance(payload.get("payload"), dict):
            envelope_payload = payload["payload"]
            envelope_target = payload.get("target")
            envelope_command = payload.get("command")
            if envelope_command and envelope_command != command:
                raise ValueError("envelope command does not match command path")

        if isinstance(envelope_target, dict):
            target_bot_id = envelope_target.get("bot_id")
            if target_bot_id and target_bot_id != bot.get("bot_id"):
                raise ValueError("target bot_id does not match bot id")
            target_role = envelope_target.get("bot_role")
            if target_role and target_role != bot.get("bot_type"):
                raise ValueError("target bot_role does not match bot type")

        normalized = dict(envelope_payload)
        if isinstance(payload.get("meta"), dict):
            normalized["_meta"] = payload["meta"]
        if isinstance(payload.get("retry"), dict):
            normalized["_retry"] = payload["retry"]
        return normalized

    def queue_bot_command(
        self,
        bot_id: str,
        command: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bot = self.db.get_bot(bot_id)
        if bot is None:
            raise KeyError(f"bot not found: {bot_id}")
        payload = self._normalize_command_payload(bot=bot, command=command, payload=payload)
        if command in _SENDER_ONLY_COMMANDS and bot.get("bot_type") != "sender":
            raise ValueError("expected tax amount commands are only allowed for sender bots")

        queued = self.db.enqueue_command(
            pc_id=bot["pc_id"],
            bot_id=bot_id,
            command=command,
            payload=payload,
        )
        logger.info(
            "command_enqueued bot_id=%s pc_id=%s command=%s command_id=%s",
            bot_id,
            bot["pc_id"],
            command,
            queued["id"],
        )
        return _sanitize_command_for_response(queued)

    def poll_agent_commands(self, pc_id: str, limit: int = 10) -> list[dict[str, Any]]:
        commands = self.db.poll_commands(pc_id=pc_id, limit=limit)
        logger.debug("command_polled pc_id=%s count=%s", pc_id, len(commands))
        return commands

    def complete_command(
        self,
        command_id: int,
        status: str,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        done = self.db.complete_command(
            command_id=command_id,
            status=status,
            error_message=error_message,
        )
        logger.info(
            "command_completed command_id=%s status=%s bot_id=%s",
            command_id,
            status,
            done.get("bot_id"),
        )
        return _sanitize_command_for_response(done)

    def receive_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        record = self.db.upsert_heartbeat(payload)
        logger.info(
            "AGENT CONNECTED heartbeat_received pc_id=%s bot_id=%s bot_status=%s step=%s",
            payload.get("pc_id"),
            payload.get("bot_id"),
            payload.get("bot_status"),
            payload.get("current_step"),
        )
        return record

    def build_dashboard(self) -> dict[str, Any]:
        return {
            "summary": self.get_summary(),
            "agents": self.list_agents(),
            "bots": self.list_bots(),
            "commands": self.list_recent_commands(limit=20),
        }
