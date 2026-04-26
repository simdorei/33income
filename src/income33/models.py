from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

AgentStatus = Literal["online", "offline", "agent_stale", "agent_error"]
BotStatus = Literal[
    "idle",
    "starting",
    "running",
    "waiting",
    "paused",
    "login_required",
    "stuck",
    "crashed",
    "restarting",
    "stopped",
]
CommandType = Literal["start", "stop", "restart", "status"]
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
