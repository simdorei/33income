from __future__ import annotations

from typing import Any

import requests


class ControlTowerClient:
    def __init__(self, base_url: str, timeout: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def send_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/api/agents/heartbeat",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def poll_commands(self, pc_id: str, limit: int = 5) -> list[dict[str, Any]]:
        response = requests.get(
            f"{self.base_url}/api/agents/{pc_id}/commands/poll",
            params={"limit": limit},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json().get("commands", [])

    def complete_command(
        self,
        command_id: int,
        status: str = "done",
        error_message: str | None = None,
    ) -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/api/commands/{command_id}/complete",
            json={"status": status, "error_message": error_message},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
