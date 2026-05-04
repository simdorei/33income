from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

logger = logging.getLogger("income33.status_mirror")

PostJsonFn = Callable[[str, dict[str, Any], float], Any]
ClockFn = Callable[[], float]


@dataclass(frozen=True)
class StatusMirrorConfig:
    enabled: bool = False
    webhook_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    min_interval_seconds: int = 60
    timeout_seconds: float = 3.0

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "StatusMirrorConfig":
        env = environ or os.environ
        enabled = str(env.get("INCOME33_STATUS_MIRROR_ENABLED", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        min_interval = _coerce_int(env.get("INCOME33_STATUS_MIRROR_MIN_INTERVAL_SECONDS"), 60, minimum=0)
        timeout = _coerce_float(env.get("INCOME33_STATUS_MIRROR_TIMEOUT_SECONDS"), 3.0, minimum=0.1)
        return cls(
            enabled=enabled,
            webhook_url=_blank_to_none(env.get("INCOME33_STATUS_MIRROR_WEBHOOK_URL")),
            telegram_bot_token=(
                _blank_to_none(env.get("INCOME33_STATUS_MIRROR_TELEGRAM_BOT_TOKEN"))
                or _blank_to_none(env.get("INCOME33_TELEGRAM_BOT_TOKEN"))
            ),
            telegram_chat_id=(
                _blank_to_none(env.get("INCOME33_STATUS_MIRROR_TELEGRAM_CHAT_ID"))
                or _blank_to_none(env.get("INCOME33_TELEGRAM_CHAT_ID"))
            ),
            min_interval_seconds=min_interval,
            timeout_seconds=timeout,
        )

    @property
    def has_target(self) -> bool:
        return bool(self.webhook_url or (self.telegram_bot_token and self.telegram_chat_id))


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _coerce_int(value: str | None, default: int, *, minimum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _coerce_float(value: str | None, default: float, *, minimum: float) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _default_post_json(url: str, body: dict[str, Any], timeout: float) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status


def _safe_value(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)


class StatusMirror:
    def __init__(
        self,
        config: StatusMirrorConfig | None = None,
        *,
        clock: ClockFn | None = None,
        post_json: PostJsonFn | None = None,
    ) -> None:
        self.config = config or StatusMirrorConfig.from_env()
        self._clock = clock or time.monotonic
        self._post_json = post_json or _default_post_json
        self._last_sent_at_by_key: dict[str, float] = {}
        self._last_signature_by_subject: dict[str, str] = {}

    def notify_heartbeat(
        self,
        payload: Mapping[str, Any],
        *,
        previous_agent: Mapping[str, Any] | None = None,
        previous_bot: Mapping[str, Any] | None = None,
    ) -> bool:
        if not self.config.enabled or not self.config.has_target:
            return False

        subject = f"{payload.get('pc_id') or '-'}:{payload.get('bot_id') or '-'}"
        signature = self._signature(payload)
        previous_signature = self._last_signature_by_subject.get(subject)
        if previous_signature == signature:
            return False

        if previous_agent or previous_bot:
            if not self._meaningful_change(payload, previous_agent=previous_agent, previous_bot=previous_bot):
                self._last_signature_by_subject[subject] = signature
                return False

        now = self._clock()
        last_sent_at = self._last_sent_at_by_key.get(subject)
        if last_sent_at is not None and now - last_sent_at < self.config.min_interval_seconds:
            return False

        message = self._format_message(payload)
        event_payload = {
            "event": "income33_status",
            "pc_id": payload.get("pc_id"),
            "bot_id": payload.get("bot_id"),
            "agent_status": payload.get("agent_status"),
            "bot_status": payload.get("bot_status"),
            "current_step": payload.get("current_step"),
            "version_status": payload.get("version_status"),
            "git_head_short": payload.get("git_head_short"),
            "git_branch": payload.get("git_branch"),
            "repo_is_git": payload.get("repo_is_git"),
            "text": message,
        }

        attempted = False
        try:
            if self.config.webhook_url:
                self._post_json(self.config.webhook_url, event_payload, self.config.timeout_seconds)
                attempted = True
            if self.config.telegram_bot_token and self.config.telegram_chat_id:
                telegram_url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
                self._post_json(
                    telegram_url,
                    {"chat_id": self.config.telegram_chat_id, "text": message},
                    self.config.timeout_seconds,
                )
                attempted = True
        except (urllib.error.URLError, OSError, TimeoutError, Exception) as exc:  # pragma: no cover - defensive logging
            logger.warning("status_mirror_send_failed target=%s error=%s", self._target_label(), type(exc).__name__)
            return False

        if attempted:
            self._last_sent_at_by_key[subject] = now
            self._last_signature_by_subject[subject] = signature
        return attempted

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> str:
        fields = (
            payload.get("agent_status"),
            payload.get("bot_status"),
            payload.get("current_step"),
            payload.get("version_status"),
            payload.get("git_head_short"),
            payload.get("git_dirty"),
            payload.get("git_up_to_date"),
        )
        return json.dumps(fields, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _meaningful_change(
        payload: Mapping[str, Any],
        *,
        previous_agent: Mapping[str, Any] | None,
        previous_bot: Mapping[str, Any] | None,
    ) -> bool:
        version_status = str(payload.get("version_status") or "")
        if version_status and version_status not in {"ok", ""}:
            return True
        if previous_agent is None and previous_bot is None:
            return True
        if previous_agent and payload.get("agent_status") != previous_agent.get("status"):
            return True
        if previous_agent and payload.get("version_status") != previous_agent.get("version_status"):
            return True
        if previous_agent and payload.get("git_head_short") != previous_agent.get("git_head_short"):
            return True
        if previous_bot and payload.get("bot_status") != previous_bot.get("status"):
            return True
        if previous_bot and payload.get("current_step") != previous_bot.get("current_step"):
            return True
        return False

    @staticmethod
    def _format_message(payload: Mapping[str, Any]) -> str:
        parts = [
            "[33income 상태]",
            f"pc={_safe_value(payload.get('pc_id'))}",
            f"bot={_safe_value(payload.get('bot_id'))}",
            f"status={_safe_value(payload.get('bot_status') or payload.get('agent_status'))}",
            f"step={_safe_value(payload.get('current_step'))}",
            f"version={_safe_value(payload.get('version_status'))}",
            f"git={_safe_value(payload.get('git_head_short'))}",
            f"branch={_safe_value(payload.get('git_branch'))}",
        ]
        return " | ".join(parts)

    def _target_label(self) -> str:
        labels = []
        if self.config.webhook_url:
            labels.append("webhook")
        if self.config.telegram_bot_token and self.config.telegram_chat_id:
            labels.append("telegram")
        return "+".join(labels) or "none"
