from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from income33.db import Database
from income33.models import COMMAND_TYPES
from income33.status_mirror import StatusMirror
from income33.utils.time import to_utc_iso, utc_now

logger = logging.getLogger("income33.control_tower.service")

REPORTER_ONE_CLICK_DEFAULT_CUSTOM_TYPE_FILTER = "NONE"
REPORTER_ONE_CLICK_REPEAT_INTERVAL_SECONDS = 300
REPORTER_ONE_CLICK_COMMAND = "submit_tax_reports"


def reporter_one_click_submit_payload(custom_type_filter: str = REPORTER_ONE_CLICK_DEFAULT_CUSTOM_TYPE_FILTER) -> dict[str, Any]:
    return {
        "tax_doc_ids": [],
        "one_click_submit": True,
        "oneClickSubmit": True,
        "tax_doc_custom_type_filter": custom_type_filter,
        "taxDocCustomTypeFilter": custom_type_filter,
        "workflow_filter_set": "SUBMIT_READY",
        "workflowFilterSet": "SUBMIT_READY",
        "review_type_filter": "NORMAL",
        "reviewTypeFilter": "NORMAL",
        "sort": "SUBMIT_REQUEST_DATE_TIME",
        "sort_field": "SUBMIT_REQUEST_DATE_TIME",
        "sortField": "SUBMIT_REQUEST_DATE_TIME",
        "direction": "ASC",
        "max_auto_targets": 0,
        "maxAutoTargets": 0,
        "repeat": True,
        "_retry": {"interval_sec": REPORTER_ONE_CLICK_REPEAT_INTERVAL_SECONDS},
    }


def _coerce_utc_datetime(value: datetime | None) -> datetime:
    if value is None:
        return utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class CommandPolicy:
    sender_only: bool = False
    reporter_only: bool = False
    dashboard_allowed: bool = False
    default_retry: dict[str, Any] | None = None
    preserves_repeat_schedule: bool = False
    repeat_schedule_enabled: bool = False


_DEFAULT_POLICY = CommandPolicy()


_COMMAND_POLICIES: dict[str, CommandPolicy] = {
    "start": CommandPolicy(dashboard_allowed=True),
    "stop": CommandPolicy(dashboard_allowed=True),
    "restart": CommandPolicy(dashboard_allowed=True),
    "status": CommandPolicy(dashboard_allowed=True, preserves_repeat_schedule=True),
    "open_login": CommandPolicy(dashboard_allowed=True),
    "login_done": CommandPolicy(dashboard_allowed=True),
    "fill_login": CommandPolicy(dashboard_allowed=True),
    "refresh_page": CommandPolicy(dashboard_allowed=True),
    "preview_send_targets": CommandPolicy(),
    "submit_auth_code": CommandPolicy(),
    "send_expected_tax_amounts": CommandPolicy(
        sender_only=True,
        dashboard_allowed=True,
        default_retry={"interval_sec": 300, "max_attempts": 3},
        preserves_repeat_schedule=True,
        repeat_schedule_enabled=True,
    ),
    "send_simple_expense_rate_expected_tax_amounts": CommandPolicy(
        sender_only=True,
        dashboard_allowed=True,
    ),
    "send_bookkeeping_expected_tax_amount": CommandPolicy(sender_only=True),
    "send_rate_based_bookkeeping_expected_tax_amount": CommandPolicy(sender_only=True),
    "preview_rate_based_bookkeeping_expected_tax_amounts": CommandPolicy(
        sender_only=True,
        default_retry={"interval_sec": 60, "max_attempts": 2},
    ),
    "send_rate_based_bookkeeping_expected_tax_amounts": CommandPolicy(
        sender_only=True,
        default_retry={"interval_sec": 60, "max_attempts": 2},
    ),
    "submit_tax_reports": CommandPolicy(
        reporter_only=True,
        dashboard_allowed=True,
        default_retry={"interval_sec": 300},
        preserves_repeat_schedule=True,
    ),
}

if missing_policy_commands := set(COMMAND_TYPES) - set(_COMMAND_POLICIES):
    raise RuntimeError(
        f"missing command policy definitions: {sorted(missing_policy_commands)}"
    )
if unknown_policy_commands := set(_COMMAND_POLICIES) - set(COMMAND_TYPES):
    raise RuntimeError(
        f"unknown command policy definitions: {sorted(unknown_policy_commands)}"
    )


def command_policies() -> dict[str, CommandPolicy]:
    return dict(_COMMAND_POLICIES)


def get_command_policy(command: str) -> CommandPolicy:
    return _COMMAND_POLICIES.get(command, _DEFAULT_POLICY)


def dashboard_allowed_commands() -> set[str]:
    return {command for command, policy in _COMMAND_POLICIES.items() if policy.dashboard_allowed}


def sender_only_commands() -> set[str]:
    return {command for command, policy in _COMMAND_POLICIES.items() if policy.sender_only}


def reporter_only_commands() -> set[str]:
    return {command for command, policy in _COMMAND_POLICIES.items() if policy.reporter_only}


def should_cancel_repeated_send_before_command(command: str) -> bool:
    return not get_command_policy(command).preserves_repeat_schedule


def _command_default_retry(command: str) -> dict[str, Any]:
    default_retry = get_command_policy(command).default_retry
    if not isinstance(default_retry, dict):
        return {}
    return dict(default_retry)


def _coerce_min_int(value: Any, minimum: int) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < minimum:
        return None
    return parsed


def command_retry_policy(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    if "interval_sec" in payload or "max_attempts" in payload:
        return dict(payload)
    retry = payload.get("retry")
    if isinstance(retry, dict):
        return dict(retry)
    payload_retry = payload.get("_retry")
    if isinstance(payload_retry, dict):
        return dict(payload_retry)
    return {}


def resolve_retry_interval_seconds(
    command: str,
    retry_policy: Mapping[str, Any] | None,
) -> int:
    if parsed_interval := _coerce_min_int(
        command_retry_policy(retry_policy).get("interval_sec"),
        minimum=1,
    ):
        return parsed_interval

    policy_default_interval = _coerce_min_int(
        _command_default_retry(command).get("interval_sec"),
        minimum=1,
    )
    if policy_default_interval is not None and command != "send_expected_tax_amounts":
        return policy_default_interval
    if policy_default_interval is None:
        policy_default_interval = 300 if command == "send_expected_tax_amounts" else 1

    raw_env_value = os.getenv("INCOME33_SEND_REPEAT_INTERVAL_SECONDS", str(policy_default_interval))
    env_interval = _coerce_min_int(raw_env_value, minimum=1)
    if env_interval is not None:
        return env_interval
    return policy_default_interval


def resolve_retry_max_attempts(
    command: str,
    retry_policy: Mapping[str, Any] | None,
) -> int:
    if parsed_attempts := _coerce_min_int(
        command_retry_policy(retry_policy).get("max_attempts"),
        minimum=1,
    ):
        return parsed_attempts

    policy_default_attempts = _coerce_min_int(
        _command_default_retry(command).get("max_attempts"),
        minimum=1,
    )
    if policy_default_attempts is not None:
        return policy_default_attempts
    return 3


def payload_has_explicit_tax_doc_ids(payload: Mapping[str, Any]) -> bool:
    for key in ("tax_doc_ids", "taxDocIds", "taxDocIdSet"):
        if payload.get(key):
            return True
    return False


def should_schedule_repeated_send(command: str, payload: Mapping[str, Any]) -> bool:
    if not get_command_policy(command).repeat_schedule_enabled:
        return False
    if payload.get("repeat") is True:
        return True
    return not payload_has_explicit_tax_doc_ids(payload)


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
        status_mirror: StatusMirror | None = None,
    ) -> None:
        self.db = db
        self.bootstrap_agent_count = bootstrap_agent_count
        self.status_mirror = status_mirror or StatusMirror()

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

    def stop_and_clear_active_for_cohort(self, *, bot_type: str) -> list[dict[str, Any]]:
        bots = sorted(
            self.list_bots(bot_type=bot_type),
            key=lambda row: str(row.get("bot_id") or ""),
        )
        results: list[dict[str, Any]] = []
        for bot in bots:
            bot_id = str(bot.get("bot_id") or "")
            if not bot_id:
                continue
            cleared_count = self.db.clear_active_commands(bot_id=bot_id, reason="cleared_by_operator")
            queued_stop = self.queue_bot_command(bot_id=bot_id, command="stop", payload={})
            results.append(
                {
                    "bot_id": bot_id,
                    "cleared_count": cleared_count,
                    "queued_stop_command_id": queued_stop.get("id"),
                }
            )
        return results

    def list_recent_commands(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.list_recent_commands(limit=limit)

    def list_repeat_schedules(self) -> list[dict[str, Any]]:
        return self.db.list_repeat_schedules()

    def _decode_schedule_payload(self, schedule: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = json.loads(str(schedule.get("payload_json") or "{}"))
        except json.JSONDecodeError as exc:
            self.db.mark_repeat_schedule_error(
                schedule_id=int(schedule["id"]),
                message="payload_json must be valid JSON",
            )
            raise ValueError("repeat schedule payload_json must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("repeat schedule payload_json must be an object")
        return payload

    def start_reporter_one_click_submit_repeat(
        self,
        bot_id: str | None = None,
        *,
        custom_type_filter: str = REPORTER_ONE_CLICK_DEFAULT_CUSTOM_TYPE_FILTER,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        now_dt = _coerce_utc_datetime(now)
        interval_sec = REPORTER_ONE_CLICK_REPEAT_INTERVAL_SECONDS
        next_run_at = to_utc_iso(now_dt + timedelta(seconds=interval_sec))
        if bot_id is not None:
            bot = self.db.get_bot(bot_id)
            if bot is None:
                raise KeyError(f"bot not found: {bot_id}")
            if bot.get("bot_type") != "reporter":
                raise ValueError("tax report submit commands are only allowed for reporter bots")
            bots = [bot]
        else:
            bots = sorted(
                self.list_bots(bot_type="reporter"),
                key=lambda row: str(row.get("bot_id") or ""),
            )

        results: list[dict[str, Any]] = []
        for bot in bots:
            target_bot_id = str(bot["bot_id"])
            payload = reporter_one_click_submit_payload(custom_type_filter=custom_type_filter)
            schedule = self.db.upsert_repeat_schedule(
                bot_id=target_bot_id,
                pc_id=str(bot["pc_id"]),
                command=REPORTER_ONE_CLICK_COMMAND,
                payload=payload,
                interval_sec=interval_sec,
                next_run_at=next_run_at,
            )
            queued: dict[str, Any] | None = None
            if self.db.has_active_command(bot_id=target_bot_id, command=REPORTER_ONE_CLICK_COMMAND):
                self.db.mark_repeat_schedule_error(
                    schedule_id=int(schedule["id"]),
                    message="pending/running command exists",
                )
                logger.info(
                    "repeat_schedule_armed_without_initial_queue bot_id=%s command=%s reason=active_command_exists",
                    target_bot_id,
                    REPORTER_ONE_CLICK_COMMAND,
                )
            else:
                queued = self.queue_bot_command(
                    bot_id=target_bot_id,
                    command=REPORTER_ONE_CLICK_COMMAND,
                    payload=payload,
                )
                schedule = self.db.mark_repeat_schedule_queued(
                    schedule_id=int(schedule["id"]),
                    command_id=int(queued["id"]),
                    next_run_at=next_run_at,
                )
            results.append({"schedule": schedule, "command": queued})
        return results

    def enqueue_due_repeat_commands(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now_dt = _coerce_utc_datetime(now)
        now_iso = to_utc_iso(now_dt)
        queued_results: list[dict[str, Any]] = []
        for schedule in self.db.list_due_repeat_schedules(now_iso):
            bot_id = str(schedule["bot_id"])
            command = str(schedule["command"])
            schedule_id = int(schedule["id"])
            if self.db.has_active_command(bot_id=bot_id, command=command):
                self.db.mark_repeat_schedule_error(
                    schedule_id=schedule_id,
                    message="pending/running command exists",
                )
                logger.debug(
                    "repeat_schedule_skipped_active_command bot_id=%s command=%s schedule_id=%s",
                    bot_id,
                    command,
                    schedule_id,
                )
                continue
            try:
                payload = self._decode_schedule_payload(schedule)
                queued = self.queue_bot_command(bot_id=bot_id, command=command, payload=payload)
            except Exception as exc:
                self.db.mark_repeat_schedule_error(schedule_id=schedule_id, message=str(exc))
                logger.warning(
                    "repeat_schedule_queue_failed bot_id=%s command=%s schedule_id=%s reason=%s",
                    bot_id,
                    command,
                    schedule_id,
                    exc,
                )
                continue

            interval_sec = max(1, int(schedule["interval_sec"]))
            next_run_at = to_utc_iso(now_dt + timedelta(seconds=interval_sec))
            updated_schedule = self.db.mark_repeat_schedule_queued(
                schedule_id=schedule_id,
                command_id=int(queued["id"]),
                next_run_at=next_run_at,
            )
            queued_results.append({"schedule": updated_schedule, "command": queued})
            logger.info(
                "repeat_schedule_command_enqueued bot_id=%s command=%s schedule_id=%s command_id=%s next_run_at=%s",
                bot_id,
                command,
                schedule_id,
                queued["id"],
                next_run_at,
            )
        return queued_results

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

        policy = get_command_policy(command)
        if policy.default_retry is not None and "_retry" not in normalized:
            normalized["_retry"] = dict(policy.default_retry)
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
        policy = get_command_policy(command)
        if policy.sender_only and bot.get("bot_type") != "sender":
            raise ValueError("expected tax amount commands are only allowed for sender bots")
        if policy.reporter_only and bot.get("bot_type") != "reporter":
            raise ValueError("tax report submit commands are only allowed for reporter bots")
        if not policy.preserves_repeat_schedule:
            repeat_schedule_commands = {
                scheduled_command
                for scheduled_command, scheduled_policy in _COMMAND_POLICIES.items()
                if scheduled_policy.repeat_schedule_enabled
            }
            repeat_schedule_commands.add(REPORTER_ONE_CLICK_COMMAND)
            for repeat_command in repeat_schedule_commands:
                self.db.disable_repeat_schedule(bot_id=bot_id, command=repeat_command)

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
        self.enqueue_due_repeat_commands()
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

    def _preserve_operator_stopped_state(
        self,
        payload: dict[str, Any],
        previous_bot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not previous_bot or not payload.get("bot_id"):
            return payload
        if previous_bot.get("status") != "stopped":
            return payload
        if payload.get("bot_status") == "stopped":
            return payload

        preserved = dict(payload)
        preserved["bot_status"] = "stopped"
        preserved["current_step"] = previous_bot.get("current_step") or "stopped"
        logger.info(
            "heartbeat_preserved_operator_stopped_state bot_id=%s incoming_status=%s incoming_step=%s preserved_step=%s",
            payload.get("bot_id"),
            payload.get("bot_status"),
            payload.get("current_step"),
            preserved.get("current_step"),
        )
        return preserved

    def receive_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        previous_agent = self.db.get_agent(str(payload.get("pc_id"))) if payload.get("pc_id") else None
        previous_bot = self.db.get_bot(str(payload.get("bot_id"))) if payload.get("bot_id") else None
        effective_payload = self._preserve_operator_stopped_state(payload, previous_bot)
        record = self.db.upsert_heartbeat(effective_payload)
        self.status_mirror.notify_heartbeat(
            effective_payload,
            previous_agent=previous_agent,
            previous_bot=previous_bot,
        )
        logger.info(
            "AGENT CONNECTED heartbeat_received pc_id=%s bot_id=%s bot_status=%s step=%s",
            effective_payload.get("pc_id"),
            effective_payload.get("bot_id"),
            effective_payload.get("bot_status"),
            effective_payload.get("current_step"),
        )
        return record

    def build_dashboard(self) -> dict[str, Any]:
        bots = [dict(bot) for bot in self.list_bots()]
        active_by_bot: dict[str, list[str]] = {}
        for command in self.db.list_active_commands():
            bot_id = str(command.get("bot_id") or "")
            if not bot_id:
                continue
            label = f"{command.get('command')}[{command.get('status')}]#{command.get('id')}"
            active_by_bot.setdefault(bot_id, []).append(label)

        for bot in bots:
            bot_id = str(bot.get("bot_id") or "")
            bot["active_command"] = ", ".join(active_by_bot.get(bot_id, []))

        return {
            "summary": self.get_summary(),
            "agents": self.list_agents(),
            "bots": bots,
            "commands": self.list_recent_commands(limit=20),
        }
