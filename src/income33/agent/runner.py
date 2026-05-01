from __future__ import annotations

import argparse
import json
import logging
import os
import time
from typing import Any, Callable

from income33.agent.browser_control import (
    assign_taxdocs_to_current_accountant,
    fill_login,
    inspect_login_state,
    is_keepalive_due,
    is_refresh_enabled,
    preview_expected_tax_send_targets,
    refresh_page,
    resolve_refresh_interval_seconds,
    send_expected_tax_amounts,
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

_LOGIN_STATE_PROBE_STATUSES = {
    "login_opened",
    "login_filling",
    "login_auth_required",
    "manual_required",
    "session_active",
}


def _resolve_send_repeat_interval_seconds() -> int:
    raw_value = os.getenv("INCOME33_SEND_REPEAT_INTERVAL_SECONDS", "300")
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return 300


def _payload_has_explicit_tax_doc_ids(payload: dict[str, Any]) -> bool:
    for key in ("tax_doc_ids", "taxDocIds", "taxDocIdSet"):
        value = payload.get(key)
        if value:
            return True
    return False


def _build_bot_runner(agent: AgentConfig):
    if agent.bot_type == "reporter":
        return ReporterBotRunner(bot_id=agent.bot_id)
    return SenderBotRunner(bot_id=agent.bot_id)


class AgentRunner:
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
        self._persistent_step: str | None = None
        self._repeat_send_payload: dict[str, Any] | None = None
        self._next_repeated_send_monotonic: float | None = None
        self._repeat_send_attempt_counts: dict[int, int] = {}

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
        previous_status = self.bot.status
        self.bot.status = status
        if step is None:
            if status != previous_status:
                self._persistent_step = None
            self._step_override = self._persistent_step
            return

        if step == status and status == previous_status and self._persistent_step:
            self._step_override = self._persistent_step
            return

        self._persistent_step = step
        self._step_override = step

    def _apply_snapshot_override(self, snapshot: Any) -> Any:
        step = self._step_override or self._persistent_step
        if step:
            snapshot.current_step = step
            snapshot.status = self.bot.status
            self._step_override = None
        return snapshot

    def _build_heartbeat_payload(self, snapshot: Any) -> dict[str, Any]:
        return {
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

    def _send_snapshot_heartbeat(self, snapshot: Any) -> None:
        heartbeat_payload = self._build_heartbeat_payload(snapshot)
        self.client.send_heartbeat(heartbeat_payload)
        self.logger.debug(
            "heartbeat_sent pc_id=%s bot_id=%s step=%s",
            self.agent.pc_id,
            snapshot.bot_id,
            snapshot.current_step,
        )

    def _send_current_state_heartbeat(self) -> None:
        snapshot = self._apply_snapshot_override(self.bot.tick())
        self.logger.debug("bot_snapshot=%s", json.dumps(snapshot.__dict__, ensure_ascii=False))
        self._send_snapshot_heartbeat(snapshot)

    def _probe_browser_login_state(self) -> None:
        if self.bot.status not in _LOGIN_STATE_PROBE_STATUSES:
            return
        result = inspect_login_state(
            bot_id=self.agent.bot_id,
            payload={},
            logger=logging.getLogger("income33.agent.browser_control"),
        )
        if not result:
            return
        self._set_bot_state(
            str(result.get("status") or self.bot.status),
            str(result.get("current_step") or self.bot.status),
        )

    def _run_keepalive_if_due(self) -> None:
        if not is_refresh_enabled():
            return
        if self.bot.status in _KEEPALIVE_BLOCKING_STATUSES:
            return

        interval = resolve_refresh_interval_seconds()
        now = self._monotonic()
        if not is_keepalive_due(self._last_refresh_monotonic, now, interval):
            return

        self._set_bot_state("refreshing", "session_refresh")
        result = refresh_page(
            bot_id=self.agent.bot_id,
            payload={},
            logger=logging.getLogger("income33.agent.browser_control"),
        )
        self._last_refresh_monotonic = now
        self._set_bot_state(
            str(result.get("status") or "session_active"),
            str(result.get("current_step") or "session_refresh"),
        )
        self.logger.info(
            "keepalive_refreshed bot_id=%s step=%s interval=%s",
            self.agent.bot_id,
            self._step_override,
            interval,
        )

    def _schedule_repeated_send(self, payload: dict[str, Any]) -> None:
        interval = _resolve_send_repeat_interval_seconds()
        self._repeat_send_payload = dict(payload)
        self._next_repeated_send_monotonic = self._monotonic() + interval
        self._repeat_send_attempt_counts = {}
        self.logger.info(
            "send_repeat_scheduled bot_id=%s interval=%s",
            self.agent.bot_id,
            interval,
        )

    def _cancel_repeated_send(self) -> None:
        if self._repeat_send_payload is None:
            return
        self.logger.info("send_repeat_cancelled bot_id=%s", self.agent.bot_id)
        self._repeat_send_payload = None
        self._next_repeated_send_monotonic = None
        self._repeat_send_attempt_counts = {}

    @staticmethod
    def _track_repeat_send_attempts(
        attempt_counts: dict[int, int],
        tax_doc_ids: list[int],
    ) -> list[int]:
        fallback_tax_doc_ids: list[int] = []
        for raw_tax_doc_id in tax_doc_ids:
            if isinstance(raw_tax_doc_id, bool):
                continue
            tax_doc_id = int(raw_tax_doc_id)
            if tax_doc_id <= 0:
                continue
            next_attempt = attempt_counts.get(tax_doc_id, 0) + 1
            attempt_counts[tax_doc_id] = next_attempt
            if next_attempt >= 3:
                fallback_tax_doc_ids.append(tax_doc_id)
        return fallback_tax_doc_ids

    def _run_repeated_send_if_due(self) -> None:
        if self._repeat_send_payload is None or self._next_repeated_send_monotonic is None:
            return
        if self.bot.status != "session_active":
            self._cancel_repeated_send()
            return
        now = self._monotonic()
        if now < self._next_repeated_send_monotonic:
            return

        payload = dict(self._repeat_send_payload)
        interval = _resolve_send_repeat_interval_seconds()
        try:
            self._set_bot_state("session_active", "계산발송 반복 중")
            self._send_current_state_heartbeat()
            result = send_expected_tax_amounts(
                bot_id=self.agent.bot_id,
                payload=payload,
                logger=logging.getLogger("income33.agent.browser_control"),
            )
        except Exception as exc:
            self._cancel_repeated_send()
            self._set_bot_state("manual_required", f"계산발송 실패: {exc}")
            self._send_current_state_heartbeat()
            self.logger.exception("send_repeat_failed bot_id=%s", self.agent.bot_id)
            return

        fallback_tax_doc_ids = self._track_repeat_send_attempts(
            self._repeat_send_attempt_counts,
            list(result.get("tax_doc_ids") or []),
        )
        if fallback_tax_doc_ids:
            try:
                assign_result = assign_taxdocs_to_current_accountant(
                    bot_id=self.agent.bot_id,
                    tax_doc_ids=fallback_tax_doc_ids,
                    payload=payload,
                    logger=logging.getLogger("income33.agent.browser_control"),
                )
            except Exception as exc:
                self._cancel_repeated_send()
                self._set_bot_state("manual_required", f"잔여목록 배정 실패: {exc}")
                self._send_current_state_heartbeat()
                self.logger.exception("send_repeat_assignment_failed bot_id=%s", self.agent.bot_id)
                return

            for tax_doc_id in fallback_tax_doc_ids:
                self._repeat_send_attempt_counts.pop(tax_doc_id, None)
            result = assign_result

        self._set_bot_state(
            str(result.get("status") or "session_active"),
            str(result.get("current_step") or "계산발송 완료"),
        )
        self._next_repeated_send_monotonic = now + interval
        self._send_current_state_heartbeat()
        self.logger.info(
            "send_repeat_done bot_id=%s next_interval=%s",
            self.agent.bot_id,
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
        if command_name not in {"status", "send_expected_tax_amounts"}:
            self._cancel_repeated_send()

        try:
            if command_name == "start":
                self.bot.start()
                self._set_bot_state(self.bot.status)
            elif command_name == "stop":
                self.bot.stop()
                self._set_bot_state(self.bot.status)
            elif command_name == "restart":
                self.bot.restart()
                self._set_bot_state(self.bot.status)
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
            elif command_name == "preview_send_targets":
                self._set_bot_state("session_active", "목록조회 테스트 중")
                self._send_current_state_heartbeat()
                result = preview_expected_tax_send_targets(
                    bot_id=self.agent.bot_id,
                    payload=payload,
                    logger=logging.getLogger("income33.agent.browser_control"),
                )
                self._set_bot_state(
                    str(result.get("status") or "session_active"),
                    str(result.get("current_step") or "목록조회 테스트 완료"),
                )
            elif command_name == "send_expected_tax_amounts":
                self._cancel_repeated_send()
                self._set_bot_state("session_active", "계산발송 중")
                self._send_current_state_heartbeat()
                result = send_expected_tax_amounts(
                    bot_id=self.agent.bot_id,
                    payload=payload,
                    logger=logging.getLogger("income33.agent.browser_control"),
                )
                self._set_bot_state(
                    str(result.get("status") or "session_active"),
                    str(result.get("current_step") or "계산발송 완료"),
                )
                if payload.get("repeat") is True or not _payload_has_explicit_tax_doc_ids(payload):
                    self._schedule_repeated_send(payload)
                    self._track_repeat_send_attempts(
                        self._repeat_send_attempt_counts,
                        list(result.get("tax_doc_ids") or []),
                    )
            elif command_name == "login_done":
                self._set_bot_state("idle", "idle")
                self.logger.info("login_done_marked bot_id=%s", self.agent.bot_id)
            elif command_name != "status":
                raise ValueError(f"unsupported command: {command_name}")
            # status command is heartbeat-only
        except Exception as exc:
            if command_name == "send_expected_tax_amounts":
                self._cancel_repeated_send()
                self._set_bot_state("manual_required", f"계산발송 실패: {exc}")
            self.client.complete_command(
                command_id=command_id,
                status="failed",
                error_message=str(exc),
            )
            self._send_current_state_heartbeat()
            self.logger.exception(
                "command_failed command_id=%s command=%s bot_id=%s",
                command_id,
                command_name,
                self.agent.bot_id,
            )
            return

        self.client.complete_command(command_id=command_id, status="done")
        self._send_current_state_heartbeat()
        self.logger.debug("command_completed command_id=%s", command_id)

    def run_once(self) -> None:
        self._run_keepalive_if_due()
        self._probe_browser_login_state()
        snapshot = self._apply_snapshot_override(self.bot.tick())
        self.logger.debug("bot_snapshot=%s", json.dumps(snapshot.__dict__, ensure_ascii=False))

        self._send_snapshot_heartbeat(snapshot)

        commands = self.client.poll_commands(self.agent.pc_id, limit=5)
        self.logger.debug("polled_commands count=%s pc_id=%s", len(commands), self.agent.pc_id)

        for command in commands:
            self._handle_command(command)

        if not commands:
            self._run_repeated_send_if_due()

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

    runner = AgentRunner(agent=config.agent, client=client, logger=logger)

    if args.once:
        runner.run_once()
        logger.info("agent_run_once_complete")
        return

    runner.run_forever()


if __name__ == "__main__":
    main()
