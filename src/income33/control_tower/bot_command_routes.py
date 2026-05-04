from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from income33.control_tower.rate_based_bookkeeping_config import (
    rate_based_bookkeeping_auto_filter_payload,
)
from income33.control_tower.request_parsing import parse_tax_doc_ids, read_form_value
from income33.control_tower.service import dashboard_allowed_commands
from income33.models import CommandRequest

logger = logging.getLogger("income33.control_tower.app")

DASHBOARD_ALLOWED_COMMANDS = frozenset(dashboard_allowed_commands())


def register_bot_command_routes(app: FastAPI) -> None:
    @app.post("/api/bots/{bot_id}/commands")
    def queue_command(bot_id: str, body: CommandRequest) -> dict[str, Any]:
        try:
            command = app.state.service.queue_bot_command(
                bot_id=bot_id,
                command=body.command,
                payload=body.payload,
            )
        except KeyError as exc:
            logger.warning("queue_command_not_found bot_id=%s", bot_id)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            logger.warning("queue_command_rejected bot_id=%s command=%s reason=%s", bot_id, body.command, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return command

    @app.post("/ui/bots/{bot_id}/commands/{command}")
    def queue_command_from_dashboard(bot_id: str, command: str) -> RedirectResponse:
        if command not in DASHBOARD_ALLOWED_COMMANDS:
            raise HTTPException(status_code=400, detail=f"unsupported command: {command}")
        try:
            app.state.service.queue_bot_command(bot_id=bot_id, command=command, payload={})
        except KeyError as exc:
            logger.warning("queue_command_not_found bot_id=%s command=%s", bot_id, command)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            logger.warning("queue_command_rejected bot_id=%s command=%s reason=%s", bot_id, command, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=303)

    @app.post("/ui/bots/{bot_id}/auth-code")
    async def queue_submit_auth_code(bot_id: str, request: Request) -> RedirectResponse:
        auth_code = await read_form_value(request, "auth_code")
        if not auth_code:
            raise HTTPException(status_code=400, detail="auth_code is required")
        try:
            app.state.service.queue_bot_command(
                bot_id=bot_id,
                command="submit_auth_code",
                payload={"auth_code": auth_code},
            )
        except KeyError as exc:
            logger.warning("queue_auth_code_not_found bot_id=%s", bot_id)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=303)

    async def _queue_tax_doc_id_list_command(
        *,
        bot_id: str,
        request: Request,
        command: str,
        log_label: str,
        extra_payload: dict[str, Any] | None = None,
        allow_empty_tax_doc_ids: bool = False,
    ) -> RedirectResponse:
        tax_doc_ids = parse_tax_doc_ids(
            await read_form_value(request, "tax_doc_ids"),
            allow_empty=allow_empty_tax_doc_ids,
        )

        try:
            payload_data: dict[str, Any] = {"tax_doc_ids": tax_doc_ids}
            if extra_payload:
                payload_data.update(extra_payload)
            app.state.service.queue_bot_command(
                bot_id=bot_id,
                command=command,
                payload=payload_data,
            )
        except KeyError as exc:
            logger.warning("%s_not_found bot_id=%s", log_label, bot_id)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            logger.warning("%s_rejected bot_id=%s reason=%s", log_label, bot_id, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=303)

    @app.post("/ui/bots/{bot_id}/rate-based-bookkeeping-send-list")
    async def queue_rate_based_bookkeeping_send_list(bot_id: str, request: Request) -> RedirectResponse:
        return await _queue_tax_doc_id_list_command(
            bot_id=bot_id,
            request=request,
            command="send_rate_based_bookkeeping_expected_tax_amounts",
            log_label="queue_rate_based_bookkeeping_send_list",
            extra_payload=rate_based_bookkeeping_auto_filter_payload(),
            allow_empty_tax_doc_ids=True,
        )

    @app.post("/ui/bots/{bot_id}/tax-report-submit-list")
    async def queue_tax_report_submit_list(bot_id: str, request: Request) -> RedirectResponse:
        # 현재 대시보드 신고 버튼은 실제 국세/지방세 제출이 아니라
        # 신고 전 준비 단계(담당자 배정 + minus-amount correction)만 큐잉한다.
        return await _queue_tax_doc_id_list_command(
            bot_id=bot_id,
            request=request,
            command="submit_tax_reports",
            log_label="queue_tax_report_submit_list",
            extra_payload={"prepare_only": True},
        )

    @app.post("/ui/bots/{bot_id}/tax-report-one-click-submit-list")
    async def queue_tax_report_one_click_submit_list(bot_id: str, request: Request) -> RedirectResponse:
        return await _queue_tax_doc_id_list_command(
            bot_id=bot_id,
            request=request,
            command="submit_tax_reports",
            log_label="queue_tax_report_one_click_submit_list",
            extra_payload={"one_click_submit": True},
            allow_empty_tax_doc_ids=True,
        )

    @app.post("/ui/bots/{bot_id}/tax-report-one-click-submit-status-check-list")
    async def queue_tax_report_one_click_submit_status_check_list(bot_id: str, request: Request) -> RedirectResponse:
        return await _queue_tax_doc_id_list_command(
            bot_id=bot_id,
            request=request,
            command="submit_tax_reports",
            log_label="queue_tax_report_one_click_submit_status_check_list",
            extra_payload={"one_click_submit": True, "one_click_submit_status_check": True},
            allow_empty_tax_doc_ids=True,
        )
