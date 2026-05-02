from __future__ import annotations

from typing import Final, Literal, Optional

from pydantic import BaseModel, Field

AgentStatus = Literal["online", "offline", "agent_stale", "agent_error"]
BotStatus = Literal[
    "idle",
    "starting",
    "running",
    "waiting",
    "paused",
    "login_required",
    "login_opened",
    "login_filling",
    "login_auth_required",
    "manual_required",
    "session_active",
    "refreshing",
    "stuck",
    "crashed",
    "restarting",
    "stopped",
]
COMMAND_TYPES: Final[tuple[str, ...]] = (
    "start",
    "stop",
    "restart",
    "status",
    "open_login",
    "login_done",
    "fill_login",
    "submit_auth_code",
    "refresh_page",
    "preview_send_targets",
    "send_expected_tax_amounts",
    "send_bookkeeping_expected_tax_amount",
    "send_rate_based_bookkeeping_expected_tax_amount",
    "preview_rate_based_bookkeeping_expected_tax_amounts",
    "send_rate_based_bookkeeping_expected_tax_amounts",
)

CommandType = Literal[*COMMAND_TYPES]
CommandStatus = Literal["pending", "running", "done", "failed"]


class CommandRequest(BaseModel):
    command: CommandType
    payload: dict = Field(default_factory=dict)


class CommandCompleteRequest(BaseModel):
    status: Literal["done", "failed"] = "done"
    error_message: Optional[str] = None


class HeartbeatRequest(BaseModel):
    pc_id: str
    hostname: str
    ip_address: str
    agent_status: AgentStatus = "online"
    bot_id: Optional[str] = None
    bot_status: Optional[BotStatus] = None
    current_step: Optional[str] = None
    success_count: int = 0
    failure_count: int = 0
