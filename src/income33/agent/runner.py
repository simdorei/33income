from __future__ import annotations

import argparse
import json
import logging
import re
import time
from typing import Any, Callable

from income33.agent.browser_control import (
    assign_taxdocs_to_current_accountant,
    fill_login,
    inspect_login_state,
    is_keepalive_due,
    is_refresh_enabled,
    preview_expected_tax_send_targets,
    preview_rate_based_bookkeeping_expected_tax_amounts,
    refresh_page,
    resolve_refresh_interval_seconds,
    send_bookkeeping_expected_tax_amount,
    send_expected_tax_amounts,
    send_rate_based_bookkeeping_expected_tax_amount,
    send_rate_based_bookkeeping_expected_tax_amounts,
    send_simple_expense_rate_expected_tax_amounts,
    submit_auth_code,
    submit_tax_reports,
)
from income33.agent.client import ControlTowerClient
from income33.agent.login import open_login_window
from income33.bots.reporter import ReporterBotRunner
from income33.bots.sender import SenderBotRunner
from income33.config import AgentConfig, load_config
from income33.control_tower.service import (
    command_retry_policy,
    payload_has_explicit_tax_doc_ids,
    reporter_only_commands,
    resolve_retry_interval_seconds,
    resolve_retry_max_attempts,
    sender_only_commands,
    should_cancel_repeated_send_before_command,
    should_schedule_repeated_send,
)
from income33.logging_utils import setup_component_logger
from income33.version_info import DEFAULT_AGENT_VERSION, collect_repo_version_info


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

_REPEAT_SEND_CONTINUABLE_STATUSES = {
    "session_active",
    "login_auth_required",
    "manual_required",
}


def _build_bot_runner(agent: AgentConfig):
    if agent.bot_type == "reporter":
        return ReporterBotRunner(bot_id=agent.bot_id)
    return SenderBotRunner(bot_id=agent.bot_id)


def _check_initial_control_tower_connection(*, client: Any, logger: logging.Logger, tower_url: str) -> bool:
    try:
        client.health_check()
    except Exception:
        logger.warning(
            "AGENT INITIAL CONNECT FAILED tower=%s - agent will keep retrying; check control tower host, port, firewall, and agent .env URL",
            tower_url,
            exc_info=True,
        )
        return False
    return True


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
        self._repeat_send_failure_count: int = 0
        self._failure_step_messages: dict[str, str] = {
            "send_expected_tax_amounts": "계산발송 실패",
            "send_simple_expense_rate_expected_tax_amounts": "단순경비율 목록발송 실패",
            "send_bookkeeping_expected_tax_amount": "단건 계산발송 실패",
            "send_rate_based_bookkeeping_expected_tax_amount": "경비율 장부 계산발송 실패",
            "preview_rate_based_bookkeeping_expected_tax_amounts": "일괄세션 확인 실패",
            "send_rate_based_bookkeeping_expected_tax_amounts": "일괄 경비율 장부발송 실패",
            "submit_tax_reports": "국세신고 응답수집 실패",
        }

    @staticmethod
    def _command_payload_json(command: dict[str, Any]) -> dict[str, Any]:
        raw_payload = command.get("payload_json")
        if not raw_payload:
            return {}
        if isinstance(raw_payload, dict):
            return raw_payload
        try:
            parsed = json.loads(raw_payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("payload_json must be valid JSON") from exc
        return parsed if isinstance(parsed, dict) else {}

    @classmethod
    def _command_payload(cls, command: dict[str, Any], parsed: dict[str, Any] | None = None) -> dict[str, Any]:
        if parsed is None:
            parsed = cls._command_payload_json(command)
        envelope_payload = parsed.get("payload")
        if isinstance(envelope_payload, dict):
            return envelope_payload
        return parsed

    @staticmethod
    def _normalize_tax_doc_ids(raw_tax_doc_ids: Any) -> list[int]:
        if isinstance(raw_tax_doc_ids, str):
            raw_ids: list[Any] = [part.strip() for part in raw_tax_doc_ids.split(",") if part.strip()]
        elif isinstance(raw_tax_doc_ids, list):
            raw_ids = raw_tax_doc_ids
        else:
            return []

        normalized_tax_doc_ids: list[int] = []
        seen_tax_doc_ids: set[int] = set()
        for raw_tax_doc_id in raw_ids:
            if isinstance(raw_tax_doc_id, bool):
                continue
            try:
                tax_doc_id = int(raw_tax_doc_id)
            except (TypeError, ValueError):
                continue
            if tax_doc_id <= 0 or tax_doc_id in seen_tax_doc_ids:
                continue
            seen_tax_doc_ids.add(tax_doc_id)
            normalized_tax_doc_ids.append(tax_doc_id)
        return normalized_tax_doc_ids

    @classmethod
    def _normalize_send_tax_doc_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_payload = dict(payload)
        raw_tax_doc_ids: Any = None
        has_tax_doc_ids = False
        for key in ("tax_doc_ids", "taxDocIds", "taxDocIdSet"):
            if key in normalized_payload:
                raw_tax_doc_ids = normalized_payload.get(key)
                has_tax_doc_ids = True
                break
        if not has_tax_doc_ids:
            return normalized_payload
        normalized_payload["tax_doc_ids"] = cls._normalize_tax_doc_ids(raw_tax_doc_ids)
        normalized_payload.pop("taxDocIds", None)
        normalized_payload.pop("taxDocIdSet", None)
        return normalized_payload

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
        if self._step_override is None and self._repeat_send_payload is not None:
            step = self._repeat_send_wait_step(step or "계산발송 완료")
        if step:
            snapshot.current_step = step
            snapshot.status = self.bot.status
            self._step_override = None
        return snapshot

    @staticmethod
    def _strip_repeat_send_wait_suffix(step: str) -> str:
        return step.split(" / 다음발송 ", 1)[0]

    @staticmethod
    def _extract_status_code(text: str) -> int | None:
        match = re.search(r"status\s*=\s*(\d{3})", text)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _repeat_send_wait_step(self, base_step: str, remaining_seconds: int | None = None) -> str:
        base_step = self._strip_repeat_send_wait_suffix(base_step)
        if remaining_seconds is None:
            if self._next_repeated_send_monotonic is None:
                remaining_seconds = resolve_retry_interval_seconds("send_expected_tax_amounts", None)
            else:
                remaining_seconds = max(0, int(self._next_repeated_send_monotonic - self._monotonic()))
        return f"{base_step} / 다음발송 {remaining_seconds}초 후"

    def _build_heartbeat_payload(self, snapshot: Any) -> dict[str, Any]:
        payload = {
            "pc_id": self.agent.pc_id,
            "hostname": self.agent.hostname,
            "ip_address": self.agent.ip_address,
            "agent_status": "online",
            "agent_version": DEFAULT_AGENT_VERSION,
            "bot_id": snapshot.bot_id,
            "bot_status": snapshot.status,
            "current_step": snapshot.current_step,
            "success_count": snapshot.success_count,
            "failure_count": snapshot.failure_count,
        }
        payload.update(collect_repo_version_info())
        return payload

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
        result_status = str(result.get("status") or self.bot.status)
        if self._repeat_send_payload is not None and self.bot.status == "session_active" and result_status != "session_active":
            self.logger.info(
                "login_probe_ignored_during_send_repeat bot_id=%s probed_status=%s step=%s",
                self.agent.bot_id,
                result_status,
                result.get("current_step"),
            )
            return
        self._set_bot_state(
            result_status,
            str(result.get("current_step") or self.bot.status),
        )

    def _run_keepalive_if_due(self) -> None:
        if not is_refresh_enabled():
            return
        if self.bot.status in _KEEPALIVE_BLOCKING_STATUSES:
            if not (
                self._repeat_send_payload is not None
                and self.bot.status in {"login_auth_required", "manual_required"}
            ):
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

    def _schedule_repeated_send(
        self,
        payload: dict[str, Any],
        retry_policy: dict[str, Any],
        *,
        enable_fallback_assignment: bool,
    ) -> None:
        interval = resolve_retry_interval_seconds("send_expected_tax_amounts", retry_policy)
        self._repeat_send_payload = dict(payload)
        self._repeat_send_payload["_repeat_interval_sec"] = interval
        self._repeat_send_payload["_repeat_max_attempts"] = resolve_retry_max_attempts(
            "send_expected_tax_amounts",
            retry_policy,
        )
        self._repeat_send_payload["_repeat_fallback_assignment_enabled"] = bool(enable_fallback_assignment)
        self._next_repeated_send_monotonic = self._monotonic() + interval
        self._repeat_send_attempt_counts = {}
        self._repeat_send_failure_count = 0
        self.logger.info(
            "send_repeat_scheduled bot_id=%s interval=%s max_attempts=%s fallback_assignment_enabled=%s",
            self.agent.bot_id,
            interval,
            self._repeat_send_payload["_repeat_max_attempts"],
            self._repeat_send_payload["_repeat_fallback_assignment_enabled"],
        )

    def _cancel_repeated_send(self) -> None:
        if self._repeat_send_payload is None:
            return
        self.logger.info("send_repeat_cancelled bot_id=%s", self.agent.bot_id)
        self._repeat_send_payload = None
        self._next_repeated_send_monotonic = None
        self._repeat_send_attempt_counts = {}
        self._repeat_send_failure_count = 0

    @classmethod
    def _track_repeat_send_attempts(
        cls,
        attempt_counts: dict[int, int],
        tax_doc_ids: Any,
        max_attempts: int,
    ) -> list[int]:
        fallback_tax_doc_ids: list[int] = []
        for tax_doc_id in cls._normalize_tax_doc_ids(tax_doc_ids):
            next_attempt = attempt_counts.get(tax_doc_id, 0) + 1
            attempt_counts[tax_doc_id] = next_attempt
            if next_attempt >= max_attempts:
                fallback_tax_doc_ids.append(tax_doc_id)
        return fallback_tax_doc_ids

    def _run_repeated_send_if_due(self) -> None:
        if self._repeat_send_payload is None or self._next_repeated_send_monotonic is None:
            return
        if self.bot.status not in _REPEAT_SEND_CONTINUABLE_STATUSES:
            self._cancel_repeated_send()
            return
        now = self._monotonic()
        if now < self._next_repeated_send_monotonic:
            return

        payload = dict(self._repeat_send_payload)
        interval = resolve_retry_interval_seconds(
            "send_expected_tax_amounts",
            {"interval_sec": payload.get("_repeat_interval_sec")},
        )
        max_attempts = resolve_retry_max_attempts(
            "send_expected_tax_amounts",
            {"max_attempts": payload.get("_repeat_max_attempts")},
        )
        fallback_assignment_enabled = bool(payload.get("_repeat_fallback_assignment_enabled", True))
        send_payload = {k: v for k, v in payload.items() if not str(k).startswith("_repeat_")}
        send_payload = self._normalize_send_tax_doc_payload(send_payload)
        try:
            self._set_bot_state("session_active", "계산발송 반복 새로고침 중")
            self._send_current_state_heartbeat()
            refresh_payload = dict(send_payload)
            refresh_payload["force"] = True
            refresh_page(
                bot_id=self.agent.bot_id,
                payload=refresh_payload,
                logger=logging.getLogger("income33.agent.browser_control"),
            )
            self._set_bot_state("session_active", "계산발송 반복 중")
            self._send_current_state_heartbeat()
            result = send_expected_tax_amounts(
                bot_id=self.agent.bot_id,
                payload=send_payload,
                logger=logging.getLogger("income33.agent.browser_control"),
            )
        except Exception as exc:
            self._repeat_send_failure_count += 1
            status_code = self._extract_status_code(str(exc))
            self._next_repeated_send_monotonic = now + interval
            self._set_bot_state(
                "session_active",
                self._repeat_send_wait_step(
                    f"계산발송 실패({self._repeat_send_failure_count}회): {exc}",
                    remaining_seconds=interval,
                ),
            )
            self._send_current_state_heartbeat()
            self.logger.exception(
                "send_repeat_failed bot_id=%s next_interval=%s failure_count=%s status=%s",
                self.agent.bot_id,
                interval,
                self._repeat_send_failure_count,
                status_code,
            )
            return

        fallback_tax_doc_ids: list[int] = []
        if fallback_assignment_enabled:
            fallback_tax_doc_ids = self._track_repeat_send_attempts(
                self._repeat_send_attempt_counts,
                list(result.get("tax_doc_ids") or []),
                max_attempts=max_attempts,
            )
        if fallback_tax_doc_ids:
            try:
                assign_result = assign_taxdocs_to_current_accountant(
                    bot_id=self.agent.bot_id,
                    tax_doc_ids=fallback_tax_doc_ids,
                    payload=send_payload,
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

        self._next_repeated_send_monotonic = now + interval
        self._repeat_send_failure_count = 0
        result_step = str(result.get("current_step") or "계산발송 완료")
        self._set_bot_state(
            str(result.get("status") or "session_active"),
            self._repeat_send_wait_step(result_step, remaining_seconds=interval),
        )
        self._send_current_state_heartbeat()
        self.logger.info(
            "send_repeat_done bot_id=%s next_interval=%s sent_count=%s status_code=%s result_tax_doc_ids=%s",
            self.agent.bot_id,
            interval,
            result.get("sent_count"),
            result.get("status_code"),
            list(result.get("tax_doc_ids") or []),
        )

    def _handle_start(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
        self.bot.start()
        self._set_bot_state(self.bot.status)

    def _handle_stop(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
        self.bot.stop()
        self._set_bot_state(self.bot.status)

    def _handle_restart(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
        self.bot.restart()
        self._set_bot_state(self.bot.status)

    def _handle_open_login(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
        self._set_bot_state("login_required")
        open_login_window(
            bot_id=self.agent.bot_id,
            payload=payload,
            logger=logging.getLogger("income33.agent.login"),
        )
        self._set_bot_state("login_opened", "login_opened")

    def _handle_fill_login(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
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

    def _handle_submit_auth_code(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
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

    def _handle_refresh_page(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
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

    def _handle_preview_send_targets(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
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

    def _handle_send_expected_tax_amounts(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
        self._cancel_repeated_send()
        normalized_payload = self._normalize_send_tax_doc_payload(payload)
        has_explicit_tax_doc_ids = payload_has_explicit_tax_doc_ids(normalized_payload)
        self._set_bot_state("session_active", "계산발송 중")
        self._send_current_state_heartbeat()
        result = send_expected_tax_amounts(
            bot_id=self.agent.bot_id,
            payload=normalized_payload,
            logger=logging.getLogger("income33.agent.browser_control"),
        )
        result_status = str(result.get("status") or "session_active")
        result_step = str(result.get("current_step") or "계산발송 완료")
        if should_schedule_repeated_send("send_expected_tax_amounts", normalized_payload):
            self._schedule_repeated_send(
                normalized_payload,
                retry_policy,
                enable_fallback_assignment=not has_explicit_tax_doc_ids,
            )
            repeat_max_attempts = resolve_retry_max_attempts(
                "send_expected_tax_amounts",
                {"max_attempts": self._repeat_send_payload.get("_repeat_max_attempts")},
            )
            if not has_explicit_tax_doc_ids:
                self._track_repeat_send_attempts(
                    self._repeat_send_attempt_counts,
                    list(result.get("tax_doc_ids") or []),
                    max_attempts=repeat_max_attempts,
                )
            repeat_interval = resolve_retry_interval_seconds(
                "send_expected_tax_amounts",
                {"interval_sec": self._repeat_send_payload.get("_repeat_interval_sec")},
            )
            result_step = self._repeat_send_wait_step(
                result_step,
                remaining_seconds=repeat_interval,
            )
        self._set_bot_state(result_status, result_step)

    def _handle_send_simple_expense_rate_expected_tax_amounts(
        self,
        payload: dict[str, Any],
        retry_policy: dict[str, Any],
    ) -> None:
        self._cancel_repeated_send()
        self._set_bot_state("session_active", "단순경비율 목록발송 중")
        self._send_current_state_heartbeat()
        result = send_simple_expense_rate_expected_tax_amounts(
            bot_id=self.agent.bot_id,
            payload=payload,
            logger=logging.getLogger("income33.agent.browser_control"),
        )
        self._set_bot_state(
            str(result.get("status") or "session_active"),
            str(result.get("current_step") or "단순경비율 목록발송 완료"),
        )

    def _handle_send_bookkeeping_expected_tax_amount(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
        self._cancel_repeated_send()
        self._set_bot_state("session_active", "단건 계산발송 중")
        self._send_current_state_heartbeat()
        result = send_bookkeeping_expected_tax_amount(
            bot_id=self.agent.bot_id,
            payload=payload,
            logger=logging.getLogger("income33.agent.browser_control"),
        )
        self._set_bot_state(
            str(result.get("status") or "session_active"),
            str(result.get("current_step") or "단건 계산발송 완료"),
        )

    def _handle_send_rate_based_bookkeeping_expected_tax_amount(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
        # Deprecated single-item command path: normalize into list-based orchestration.
        self._cancel_repeated_send()
        self._set_bot_state("session_active", "경비율 장부 계산발송 중")
        self._send_current_state_heartbeat()
        normalized_payload = dict(payload)
        tax_doc_id = normalized_payload.get("tax_doc_id") or normalized_payload.get("taxDocId")
        if tax_doc_id is not None and not normalized_payload.get("tax_doc_ids"):
            normalized_payload["tax_doc_ids"] = [int(tax_doc_id)]
        result = send_rate_based_bookkeeping_expected_tax_amounts(
            bot_id=self.agent.bot_id,
            payload=normalized_payload,
            logger=logging.getLogger("income33.agent.browser_control"),
        )
        self._set_bot_state(
            str(result.get("status") or "session_active"),
            str(result.get("current_step") or "경비율 장부 계산발송 완료"),
        )

    def _handle_preview_rate_based_bookkeeping_expected_tax_amounts(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
        self._cancel_repeated_send()
        self._set_bot_state("session_active", "일괄세션 확인 중")
        self._send_current_state_heartbeat()
        result = preview_rate_based_bookkeeping_expected_tax_amounts(
            bot_id=self.agent.bot_id,
            payload=payload,
            logger=logging.getLogger("income33.agent.browser_control"),
        )
        self._set_bot_state(
            str(result.get("status") or "session_active"),
            str(result.get("current_step") or "일괄세션 확인 완료"),
        )

    def _handle_send_rate_based_bookkeeping_expected_tax_amounts(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
        self._cancel_repeated_send()
        self._set_bot_state("session_active", "일괄 경비율 장부발송 중")
        self._send_current_state_heartbeat()
        result = send_rate_based_bookkeeping_expected_tax_amounts(
            bot_id=self.agent.bot_id,
            payload=payload,
            logger=logging.getLogger("income33.agent.browser_control"),
        )
        self._set_bot_state(
            str(result.get("status") or "session_active"),
            str(result.get("current_step") or "일괄 경비율 장부발송 완료"),
        )

    def _handle_submit_tax_reports(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
        normalized_payload = self._normalize_send_tax_doc_payload(payload)
        self._set_bot_state("session_active", "국세신고 응답수집 중")
        self._send_current_state_heartbeat()
        result = submit_tax_reports(
            bot_id=self.agent.bot_id,
            payload=normalized_payload,
            logger=logging.getLogger("income33.agent.browser_control"),
        )
        self._set_bot_state(
            str(result.get("status") or "session_active"),
            str(result.get("current_step") or "국세신고 응답수집 완료"),
        )

    def _handle_login_done(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
        self._set_bot_state("idle", "idle")
        self.logger.info("login_done_marked bot_id=%s", self.agent.bot_id)

    def _handle_status(self, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
        return

    def _command_handlers(self) -> dict[str, Callable[[dict[str, Any], dict[str, Any]], None]]:
        return {
            "start": self._handle_start,
            "stop": self._handle_stop,
            "restart": self._handle_restart,
            "open_login": self._handle_open_login,
            "fill_login": self._handle_fill_login,
            "submit_auth_code": self._handle_submit_auth_code,
            "refresh_page": self._handle_refresh_page,
            "preview_send_targets": self._handle_preview_send_targets,
            "send_expected_tax_amounts": self._handle_send_expected_tax_amounts,
            "send_simple_expense_rate_expected_tax_amounts": self._handle_send_simple_expense_rate_expected_tax_amounts,
            "send_bookkeeping_expected_tax_amount": self._handle_send_bookkeeping_expected_tax_amount,
            "send_rate_based_bookkeeping_expected_tax_amount": self._handle_send_rate_based_bookkeeping_expected_tax_amount,
            "preview_rate_based_bookkeeping_expected_tax_amounts": self._handle_preview_rate_based_bookkeeping_expected_tax_amounts,
            "send_rate_based_bookkeeping_expected_tax_amounts": self._handle_send_rate_based_bookkeeping_expected_tax_amounts,
            "submit_tax_reports": self._handle_submit_tax_reports,
            "login_done": self._handle_login_done,
            "status": self._handle_status,
        }

    def _dispatch_command(self, command_name: str, payload: dict[str, Any], retry_policy: dict[str, Any]) -> None:
        handler = self._command_handlers().get(command_name)
        if handler is None:
            raise ValueError(f"unsupported command: {command_name}")
        handler(payload, retry_policy)

    def _apply_failure_state_for_command(self, command_name: str, exc: Exception) -> None:
        if command_name == "send_expected_tax_amounts":
            self._cancel_repeated_send()
        failure_prefix = self._failure_step_messages.get(command_name)
        if failure_prefix:
            self._set_bot_state("manual_required", f"{failure_prefix}: {exc}")

    def _handle_command(self, command: dict[str, Any]) -> None:
        command_name = command["command"]
        command_id = command["id"]
        self.logger.info(
            "command_received command_id=%s command=%s bot_id=%s",
            command_id,
            command_name,
            self.agent.bot_id,
        )
        if should_cancel_repeated_send_before_command(command_name):
            self._cancel_repeated_send()

        try:
            parsed_payload = self._command_payload_json(command)
            payload = self._command_payload(command, parsed_payload)
            retry_policy = command_retry_policy(parsed_payload)
            if self.agent.bot_type != "sender" and command_name in sender_only_commands():
                raise ValueError(f"SENDER_ONLY_COMMAND: {command_name}")
            if self.agent.bot_type != "reporter" and command_name in reporter_only_commands():
                raise ValueError(f"REPORTER_ONLY_COMMAND: {command_name}")
            self._dispatch_command(command_name, payload, retry_policy)
        except Exception as exc:
            self._apply_failure_state_for_command(command_name, exc)
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
    _check_initial_control_tower_connection(
        client=client,
        logger=logger,
        tower_url=config.agent.control_tower_url,
    )

    runner = AgentRunner(agent=config.agent, client=client, logger=logger)

    if args.once:
        runner.run_once()
        logger.info("agent_run_once_complete")
        return

    runner.run_forever()


if __name__ == "__main__":
    main()
