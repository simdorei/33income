from __future__ import annotations

import argparse
import json
import logging
import time
from typing import Any, Callable

from income33.agent.browser_control import (
    fill_login,
    is_keepalive_due,
    is_refresh_enabled,
    refresh_page,
    resolve_refresh_interval_seconds,
    submit_auth_code,
)
from income33.agent.client import ControlTowerClient
from income33.agent.login import open_login_window
from income33.bots.reporter import ReporterBotRunner
from income33.bots.sender import SenderBotRunner
from income33.config import AgentConfig, load_config
from income33.logging_utils import setup_component_logger


_KEEPALIVE_BLOCKING_STATUSES = {
    "stopped",
    "paused",
    "login_required",
    "login_opened",
    "login_filling",
    "login_auth_required",
    "manual_required",
    "crashed",
}


def _build_bot_runner(agent: AgentConfig):
    if agent.bot_type == "reporter":
        return ReporterBotRunner(bot_id=agent.bot_id)
    return SenderBotRunner(bot_id=agent.bot_id)


class MockAgentRunner:
    def __init__(
        self,
        agent: AgentConfig,
        client: ControlTowerClient,
        logger: logging.Logger | None = None,
        monotonic_fn: Callable[[], float] | None = None,
    ) -> None:
        self.agent = agent
        self.client = client
        self.bot = _build_bot_runner(agent)
        self.logger = logger or logging.getLogger("income33.agent.runner")
        self._monotonic = monotonic_fn or time.monotonic
        self._last_refresh_monotonic: float | None = None
        self._step_override: str | None = None

    @staticmethod
    def _command_payload(command: dict[str, Any]) -> dict[str, Any]:
        raw_payload = command.get("payload_json")
        if not raw_payload:
            return {}
        if isinstance(raw_payload, dict):
            return raw_payload
        try:
            parsed = json.loads(raw_payload)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _set_bot_state(self, status: str, step: str | None = None) -> None:
        self.bot.status = status
        self._step_override = step

    def _apply_snapshot_override(self, snapshot: Any) -> Any:
        if self._step_override:
            snapshot.current_step = self._step_override
            snapshot.status = self.bot.status
            self._step_override = None
        return snapshot

    def _run_keepalive_if_due(self) -> None:
        if not is_refresh_enabled():
            return
        if self.bot.status in _KEEPALIVE_BLOCKING_STATUSES:
            return

        interval = resolve_refresh_interval_seconds()
        now = self._monotonic()
        if not is_keepalive_due(self._last_refresh_monotonic, now, interval):
            return

        self.bot.status = "refreshing"
        result = refresh_page(
            bot_id=self.agent.bot_id,
            payload={},
            logger=logging.getLogger("income33.agent.browser_control"),
        )
        self._last_refresh_monotonic = now
        self.bot.status = str(result.get("status") or "session_active")
        self._step_override = str(result.get("current_step") or "session_refresh")
        self.logger.info(
            "keepalive_refreshed bot_id=%s step=%s interval=%s",
            self.agent.bot_id,
            self._step_override,
            interval,
        )

    def _handle_command(self, command: dict[str, Any]) -> None:
        command_name = command["command"]
        command_id = command["id"]
        payload = self._command_payload(command)
        self.logger.info(
            "command_received command_id=%s command=%s bot_id=%s",
            command_id,
            command_name,
            self.agent.bot_id,
        )

        try:
            if command_name == "start":
                self.bot.start()
            elif command_name == "stop":
                self.bot.stop()
            elif command_name == "restart":
                self.bot.restart()
            elif command_name == "open_login":
                self._set_bot_state("login_required")
                open_login_window(
                    bot_id=self.agent.bot_id,
                    payload=payload,
                    logger=logging.getLogger("income33.agent.login"),
                )
                self._set_bot_state("login_opened", "login_opened")
            elif command_name == "fill_login":
                self._set_bot_state("login_filling")
                result = fill_login(
                    bot_id=self.agent.bot_id,
                    payload=payload,
                    logger=logging.getLogger("income33.agent.browser_control"),
                )
                self._set_bot_state(
                    str(result.get("status") or "login_auth_required"),
                    str(result.get("current_step") or "login_auth_required"),
                )
            elif command_name == "submit_auth_code":
                auth_code = str(payload.get("auth_code") or "")
                self._set_bot_state("manual_required")
                result = submit_auth_code(
                    bot_id=self.agent.bot_id,
                    auth_code=auth_code,
                    payload=payload,
                    logger=logging.getLogger("income33.agent.browser_control"),
                )
                self._set_bot_state(
                    str(result.get("status") or "session_active"),
                    str(result.get("current_step") or "session_active"),
                )
            elif command_name == "refresh_page":
                self._set_bot_state("refreshing", "session_refresh")
                result = refresh_page(
                    bot_id=self.agent.bot_id,
                    payload=payload,
                    logger=logging.getLogger("income33.agent.browser_control"),
                )
                self._set_bot_state(
                    str(result.get("status") or "session_active"),
                    str(result.get("current_step") or "session_refresh"),
                )
            elif command_name == "login_done":
                self._set_bot_state("idle", "idle")
                self.logger.info("login_done_marked bot_id=%s", self.agent.bot_id)
            elif command_name != "status":
                raise ValueError(f"unsupported command: {command_name}")
            # status command is heartbeat-only
        except Exception as exc:
            self.client.complete_command(
                command_id=command_id,
                status="failed",
                error_message=str(exc),
            )
            self.logger.exception(
                "command_failed command_id=%s command=%s bot_id=%s",
                command_id,
                command_name,
                self.agent.bot_id,
            )
            return

        self.client.complete_command(command_id=command_id, status="done")
        self.logger.debug("command_completed command_id=%s", command_id)

    def run_once(self) -> None:
        self._run_keepalive_if_due()
        snapshot = self._apply_snapshot_override(self.bot.tick())
        self.logger.debug("bot_snapshot=%s", json.dumps(snapshot.__dict__, ensure_ascii=False))

        heartbeat_payload = {
            "pc_id": self.agent.pc_id,
            "hostname": self.agent.hostname,
            "ip_address": self.agent.ip_address,
            "agent_status": "online",
            "bot_id": snapshot.bot_id,
            "bot_status": snapshot.status,
            "current_step": snapshot.current_step,
            "success_count": snapshot.success_count,
            "failure_count": snapshot.failure_count,
        }

        self.client.send_heartbeat(heartbeat_payload)
        self.logger.debug(
            "heartbeat_sent pc_id=%s bot_id=%s step=%s",
            self.agent.pc_id,
            snapshot.bot_id,
            snapshot.current_step,
        )

        commands = self.client.poll_commands(self.agent.pc_id, limit=5)
        self.logger.debug("polled_commands count=%s pc_id=%s", len(commands), self.agent.pc_id)

        for command in commands:
            self._handle_command(command)

    def run_forever(self) -> None:
        interval = max(1, int(self.agent.heartbeat_interval_seconds))
        self.logger.info(
            "agent_runner_started pc_id=%s bot_id=%s tower=%s interval=%s",
            self.agent.pc_id,
            self.agent.bot_id,
            self.agent.control_tower_url,
            interval,
        )

        while True:
            try:
                self.run_once()
            except Exception:  # pragma: no cover (network/runtime dependent)
                self.logger.exception("agent_cycle_failed pc_id=%s", self.agent.pc_id)
            time.sleep(interval)


def main() -> None:
    setup_component_logger("income33.agent", "agent.log")
    logger = logging.getLogger("income33.agent.runner")

    parser = argparse.ArgumentParser(description="Run income33 local agent")
    parser.add_argument("--once", action="store_true", help="heartbeat/poll only once")
    args = parser.parse_args()

    config = load_config()
    client = ControlTowerClient(
        base_url=config.agent.control_tower_url,
        logger=logging.getLogger("income33.agent.client"),
    )
    logger.info(
        "AGENT START pc_id=%s bot_id=%s tower=%s",
        config.agent.pc_id,
        config.agent.bot_id,
        config.agent.control_tower_url,
    )
    try:
        client.health_check()
    except Exception:
        logger.error(
            "AGENT CANNOT CONNECT tower=%s - check control tower host, port, firewall, and agent .env URL",
            config.agent.control_tower_url,
        )
        raise

    runner = MockAgentRunner(agent=config.agent, client=client, logger=logger)

    if args.once:
        runner.run_once()
        logger.info("agent_run_once_complete")
        return

    runner.run_forever()


if __name__ == "__main__":
    main()
