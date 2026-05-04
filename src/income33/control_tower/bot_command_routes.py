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

REPORTER_ONE_CLICK_CUSTOM_TYPE_FILTER_OPTIONS = frozenset(
    ("ALL", "NONE", "가", "나", "다", "라", "마", "바", "사", "아")
)
REPORTER_ONE_CLICK_FORCED_CUSTOM_TYPE_FILTER = "NONE"
REPORTER_ONE_CLICK_REPEAT_INTERVAL_SECONDS = 300


def _reporter_one_click_submit_payload(custom_type_filter: str | None = None) -> dict[str, Any]:
    custom_type_filter = REPORTER_ONE_CLICK_FORCED_CUSTOM_TYPE_FILTER
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


def _normalize_reporter_one_click_custom_type_filter(raw_value: str) -> str:
    custom_type_filter = (raw_value or "").strip() or "ALL"
    if custom_type_filter not in REPORTER_ONE_CLICK_CUSTOM_TYPE_FILTER_OPTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid tax_doc_custom_type_filter: {custom_type_filter}",
        )
    return custom_type_filter


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

    def _queue_command_for_all_bots(
        *,
        bot_type: str,
        command: str,
        payload: dict[str, Any] | None,
        log_label: str,
    ) -> RedirectResponse:
        bots = sorted(
            app.state.service.list_bots(bot_type=bot_type),
            key=lambda row: str(row.get("bot_id") or ""),
        )
        if not bots:
            logger.warning("%s_no_targets bot_type=%s", log_label, bot_type)
            raise HTTPException(status_code=404, detail=f"no bots found for type={bot_type}")

        queued_count = 0
        for bot in bots:
            bot_id = str(bot.get("bot_id") or "")
            if not bot_id:
                continue
            try:
                app.state.service.queue_bot_command(
                    bot_id=bot_id,
                    command=command,
                    payload=dict(payload or {}),
                )
            except ValueError as exc:
                logger.warning("%s_rejected bot_id=%s reason=%s", log_label, bot_id, exc)
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            queued_count += 1

        logger.info(
            "%s_done bot_type=%s command=%s queued_count=%s",
            log_label,
            bot_type,
            command,
            queued_count,
        )
        return RedirectResponse(url="/", status_code=303)

    @app.post("/ui/commands/senders/send-expected-tax-amounts-all")
    def queue_sender_all_send_expected_tax_amounts() -> RedirectResponse:
        return _queue_command_for_all_bots(
            bot_type="sender",
            command="send_expected_tax_amounts",
            payload={},
            log_label="queue_sender_all_send_expected_tax_amounts",
        )

    @app.post("/ui/commands/senders/send-simple-expense-rate-expected-tax-amounts-all")
    def queue_sender_all_send_simple_expense_rate_expected_tax_amounts() -> RedirectResponse:
        return _queue_command_for_all_bots(
            bot_type="sender",
            command="send_simple_expense_rate_expected_tax_amounts",
            payload={},
            log_label="queue_sender_all_send_simple_expense_rate_expected_tax_amounts",
        )

    @app.post("/ui/commands/senders/send-rate-based-bookkeeping-expected-tax-amounts-all")
    def queue_sender_all_send_rate_based_bookkeeping_expected_tax_amounts() -> RedirectResponse:
        payload_data = {"tax_doc_ids": []}
        payload_data.update(rate_based_bookkeeping_auto_filter_payload())
        return _queue_command_for_all_bots(
            bot_type="sender",
            command="send_rate_based_bookkeeping_expected_tax_amounts",
            payload=payload_data,
            log_label="queue_sender_all_send_rate_based_bookkeeping_expected_tax_amounts",
        )

    @app.post("/ui/commands/reporters/submit-tax-reports-one-click-all")
    async def queue_reporter_all_submit_tax_reports_one_click(request: Request) -> RedirectResponse:
        custom_type_filter = _normalize_reporter_one_click_custom_type_filter(
            await read_form_value(request, "tax_doc_custom_type_filter")
        )
        return _queue_command_for_all_bots(
            bot_type="reporter",
            command="submit_tax_reports",
            payload=_reporter_one_click_submit_payload(custom_type_filter),
            log_label="queue_reporter_all_submit_tax_reports_one_click",
        )

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
        tax_doc_ids = parse_tax_doc_ids(
            await read_form_value(request, "tax_doc_ids"),
            allow_empty=True,
        )
        payload_data = {"tax_doc_ids": tax_doc_ids, "one_click_submit": True}
        if not tax_doc_ids:
            payload_data.update(_reporter_one_click_submit_payload())
        try:
            app.state.service.queue_bot_command(
                bot_id=bot_id,
                command="submit_tax_reports",
                payload=payload_data,
            )
        except KeyError as exc:
            logger.warning("queue_tax_report_one_click_submit_list_not_found bot_id=%s", bot_id)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            logger.warning("queue_tax_report_one_click_submit_list_rejected bot_id=%s reason=%s", bot_id, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=303)

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
