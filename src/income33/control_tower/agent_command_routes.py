from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from income33.models import CommandCompleteRequest, HeartbeatRequest

logger = logging.getLogger("income33.control_tower.app")


def register_agent_command_routes(app: FastAPI) -> None:
    @app.get("/api/agents/{pc_id}/commands/poll")
    def poll_agent_commands(
        pc_id: str,
        limit: int = Query(default=10, ge=1, le=50),
    ) -> dict[str, Any]:
        commands = app.state.service.poll_agent_commands(pc_id=pc_id, limit=limit)
        return {"commands": commands}

    @app.post("/api/commands/{command_id}/complete")
    def complete_command(command_id: int, body: CommandCompleteRequest) -> dict[str, Any]:
        try:
            command = app.state.service.complete_command(
                command_id=command_id,
                status=body.status,
                error_message=body.error_message,
            )
        except KeyError as exc:
            logger.warning("complete_command_not_found command_id=%s", command_id)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return command

    @app.post("/api/agents/heartbeat")
    def agent_heartbeat(body: HeartbeatRequest) -> dict[str, Any]:
        record = app.state.service.receive_heartbeat(body.model_dump())
        return {"agent": record, "accepted": True}
