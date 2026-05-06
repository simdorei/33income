from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SessionAdhesionReadModel:
    session_status: str
    last_session_active_at: str | None
    last_probe_at: str | None
    last_refresh_at: str | None
    adhesion_level: str
    adhesion_score: int
    affinity: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_status": self.session_status,
            "last_session_active_at": self.last_session_active_at,
            "last_probe_at": self.last_probe_at,
            "last_refresh_at": self.last_refresh_at,
            "adhesion_level": self.adhesion_level,
            "adhesion_score": self.adhesion_score,
            "affinity": self.affinity,
            "affinity_bot_id": self.affinity.get("bot_id"),
            "affinity_pc_id": self.affinity.get("pc_id"),
            "affinity_hostname": self.affinity.get("hostname"),
            "affinity_ip_address": self.affinity.get("ip_address"),
            "affinity_profile_dir": self.affinity.get("profile_dir"),
            "affinity_debug_port": self.affinity.get("debug_port"),
            "affinity_office_id": self.affinity.get("office_id"),
        }


def _normalize_session_status(bot_status: str | None, heartbeat_age_seconds: int | None) -> str:
    if heartbeat_age_seconds is not None and heartbeat_age_seconds > 180:
        return "stale"

    if bot_status in {"running", "waiting", "session_active", "refreshing"}:
        return "active"
    if bot_status in {"login_auth_required"}:
        return "auth_required"
    if bot_status in {"login_required", "login_opened", "login_filling", "manual_required"}:
        return "login_required"
    if bot_status in {"stuck", "crashed"}:
        return "stale"
    return "unknown"


def _adhesion_score(session_status: str, heartbeat_age_seconds: int | None) -> int:
    age = heartbeat_age_seconds if heartbeat_age_seconds is not None else 9999

    if session_status == "active":
        if age <= 30:
            return 95
        if age <= 180:
            return 80
        if age <= 300:
            return 60
        return 35

    if session_status == "auth_required":
        return 45 if age <= 180 else 25

    if session_status == "login_required":
        return 30 if age <= 180 else 15

    if session_status == "stale":
        return 10

    return 20


def _adhesion_level(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    if score >= 25:
        return "low"
    return "none"


def build_session_adhesion_read_model(
    *,
    bot_row: dict[str, Any],
    agent_row: dict[str, Any] | None = None,
) -> SessionAdhesionReadModel:
    heartbeat_age_raw = bot_row.get("heartbeat_age_seconds")
    heartbeat_age_seconds: int | None
    try:
        heartbeat_age_seconds = int(heartbeat_age_raw) if heartbeat_age_raw is not None else None
    except (TypeError, ValueError):
        heartbeat_age_seconds = None

    bot_status = str(bot_row.get("status") or "")
    session_status = _normalize_session_status(bot_status=bot_status, heartbeat_age_seconds=heartbeat_age_seconds)

    last_session_active_at = bot_row.get("last_heartbeat_at") if session_status == "active" else None
    score = _adhesion_score(session_status=session_status, heartbeat_age_seconds=heartbeat_age_seconds)

    affinity = {
        "bot_id": bot_row.get("bot_id"),
        "pc_id": bot_row.get("pc_id"),
        "hostname": (agent_row or {}).get("hostname"),
        "ip_address": (agent_row or {}).get("ip_address"),
        "profile_dir": bot_row.get("profile_dir"),
        "debug_port": bot_row.get("debug_port"),
        "office_id": bot_row.get("office_id"),
    }

    return SessionAdhesionReadModel(
        session_status=session_status,
        last_session_active_at=last_session_active_at,
        last_probe_at=None,
        last_refresh_at=None,
        adhesion_level=_adhesion_level(score),
        adhesion_score=score,
        affinity=affinity,
    )
