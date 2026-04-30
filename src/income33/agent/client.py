from __future__ import annotations

import logging
from typing import Any

import requests

from income33.logging_utils import resolve_http_timeout_seconds


class ControlTowerClient:
    def __init__(
        self,
        base_url: str,
        timeout: int | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout if timeout is not None else resolve_http_timeout_seconds()
        self.logger = logger or logging.getLogger("income33.agent.client")

    def send_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.logger.debug(
            "send_heartbeat pc_id=%s bot_id=%s bot_status=%s",
            payload.get("pc_id"),
            payload.get("bot_id"),
            payload.get("bot_status"),
        )
        try:
            response = requests.post(
                f"{self.base_url}/api/agents/heartbeat",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException:
            self.logger.exception("send_heartbeat failed")
            raise

        body = response.json()
        self.logger.info(
            "CONNECTED heartbeat accepted status_code=%s pc_id=%s bot_id=%s",
            response.status_code,
            payload.get("pc_id"),
            payload.get("bot_id"),
        )
        return body

    def health_check(self) -> dict[str, Any]:
        """Verify that the control tower is reachable before the main loop starts."""

        self.logger.info("checking control tower connection tower=%s", self.base_url)
        try:
            response = requests.get(f"{self.base_url}/api/health", timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException:
            self.logger.exception("CONTROL TOWER CONNECTION FAILED tower=%s", self.base_url)
            raise

        body = response.json()
        self.logger.info(
            "CONNECTED control tower health ok tower=%s status_code=%s status=%s",
            self.base_url,
            response.status_code,
            body.get("status"),
        )
        return body

    def poll_commands(self, pc_id: str, limit: int = 5) -> list[dict[str, Any]]:
        self.logger.debug("poll_commands pc_id=%s limit=%s", pc_id, limit)
        try:
            response = requests.get(
                f"{self.base_url}/api/agents/{pc_id}/commands/poll",
                params={"limit": limit},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException:
            self.logger.exception("poll_commands failed pc_id=%s", pc_id)
            raise

        commands = response.json().get("commands", [])
        self.logger.info("CONNECTED command poll ok count=%s pc_id=%s", len(commands), pc_id)
        return commands

    def complete_command(
        self,
        command_id: int,
        status: str = "done",
        error_message: str | None = None,
    ) -> dict[str, Any]:
        self.logger.debug(
            "complete_command command_id=%s status=%s",
            command_id,
            status,
        )
        try:
            response = requests.post(
                f"{self.base_url}/api/commands/{command_id}/complete",
                json={"status": status, "error_message": error_message},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException:
            self.logger.exception(
                "complete_command failed command_id=%s status=%s",
                command_id,
                status,
            )
            raise

        body = response.json()
        self.logger.debug(
            "complete_command accepted command_id=%s status_code=%s",
            command_id,
            response.status_code,
        )
        return body
