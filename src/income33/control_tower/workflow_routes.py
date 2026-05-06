from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from income33.control_tower.rate_based_bookkeeping_config import (
    rate_based_bookkeeping_auto_filter_payload,
)
from income33.models import CommandCompleteRequest

logger = logging.getLogger("income33.control_tower.app")


class WorkflowCommandRequest(BaseModel):
    """Granular workflow command body.

    Supports both the explicit envelope shape {"payload": {...}} and the
    direct payload shape {...}. If callers mix both shapes, fail closed instead
    of silently dropping fields from state-changing command payloads.
    """

    model_config = ConfigDict(extra="allow")

    payload: dict[str, Any] = Field(default_factory=dict)


def _workflow_command_payload(body: WorkflowCommandRequest) -> dict[str, Any]:
    extra_fields = dict(body.model_extra or {})
    if "payload" in body.model_fields_set:
        if extra_fields:
            raise HTTPException(
                status_code=400,
                detail="use either payload envelope or direct payload fields, not both",
            )
        return dict(body.payload)
    return extra_fields or dict(body.payload)


def _queue_wrapped_command(
    app: FastAPI,
    *,
    bot_id: str,
    command: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return app.state.service.queue_bot_command(
            bot_id=bot_id,
            command=command,
            payload=payload or {},
        )
    except KeyError as exc:
        logger.warning("wrapped_command_not_found bot_id=%s command=%s", bot_id, command)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        logger.warning("wrapped_command_rejected bot_id=%s command=%s reason=%s", bot_id, command, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def register_workflow_routes(app: FastAPI) -> None:
    @app.post("/api/commands/{command_id}/completion")
    def complete_command_alias(command_id: int, body: CommandCompleteRequest) -> dict[str, Any]:
        try:
            return app.state.service.complete_command(
                command_id=command_id,
                status=body.status,
                error_message=body.error_message,
            )
        except KeyError as exc:
            logger.warning("complete_command_alias_not_found command_id=%s", command_id)
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/bots/{bot_id}/commands/active")
    def list_bot_active_commands(bot_id: str) -> dict[str, Any]:
        try:
            commands = app.state.service.list_bot_active_commands(bot_id=bot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"commands": commands}

    @app.get("/api/bots/{bot_id}/commands/recent")
    def list_bot_recent_commands(
        bot_id: str,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        try:
            commands = app.state.service.list_bot_recent_commands(bot_id=bot_id, limit=limit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"commands": commands}

    @app.post("/api/senders/{bot_id}/expected-tax/send")
    def queue_sender_expected_tax_send(bot_id: str, body: WorkflowCommandRequest) -> dict[str, Any]:
        return _queue_wrapped_command(
            app,
            bot_id=bot_id,
            command="send_expected_tax_amounts",
            payload=_workflow_command_payload(body),
        )

    @app.post("/api/senders/{bot_id}/simple-expense-rate/send")
    def queue_sender_simple_expense_rate_send(bot_id: str, body: WorkflowCommandRequest) -> dict[str, Any]:
        return _queue_wrapped_command(
            app,
            bot_id=bot_id,
            command="send_simple_expense_rate_expected_tax_amounts",
            payload=_workflow_command_payload(body),
        )

    @app.post("/api/senders/{bot_id}/rate-based-bookkeeping/send")
    def queue_sender_rate_based_bookkeeping_send(bot_id: str, body: WorkflowCommandRequest) -> dict[str, Any]:
        payload = dict(rate_based_bookkeeping_auto_filter_payload())
        payload.update(_workflow_command_payload(body))
        payload.setdefault("tax_doc_ids", [])
        return _queue_wrapped_command(
            app,
            bot_id=bot_id,
            command="send_rate_based_bookkeeping_expected_tax_amounts",
            payload=payload,
        )

    @app.post("/api/reporters/{bot_id}/tax-reports/submit")
    def queue_reporter_tax_report_submit(bot_id: str, body: WorkflowCommandRequest) -> dict[str, Any]:
        return _queue_wrapped_command(
            app,
            bot_id=bot_id,
            command="submit_tax_reports",
            payload=_workflow_command_payload(body),
        )

    @app.post("/api/reporters/{bot_id}/tax-reports/submit-status-check")
    def queue_reporter_tax_report_submit_status_check(bot_id: str, body: WorkflowCommandRequest) -> dict[str, Any]:
        payload = _workflow_command_payload(body)
        payload.setdefault("tax_doc_ids", [])
        payload["one_click_submit"] = True
        payload["one_click_submit_status_check"] = True
        return _queue_wrapped_command(
            app,
            bot_id=bot_id,
            command="submit_tax_reports",
            payload=payload,
        )

    @app.get("/api/bots/{bot_id}/session")
    def get_bot_session(bot_id: str) -> dict[str, Any]:
        try:
            return app.state.service.get_bot_session_view(bot_id=bot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/bots/{bot_id}/session/probe")
    def queue_bot_session_probe(bot_id: str, body: WorkflowCommandRequest) -> dict[str, Any]:
        return _queue_wrapped_command(
            app,
            bot_id=bot_id,
            command="status",
            payload=_workflow_command_payload(body),
        )

    @app.post("/api/bots/{bot_id}/session/refresh")
    def queue_bot_session_refresh(bot_id: str, body: WorkflowCommandRequest) -> dict[str, Any]:
        return _queue_wrapped_command(
            app,
            bot_id=bot_id,
            command="refresh_page",
            payload=_workflow_command_payload(body),
        )
