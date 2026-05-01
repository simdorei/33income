from __future__ import annotations

import logging
from html import escape
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from income33.config import AppConfig, load_config
from income33.control_tower.service import ControlTowerService
from income33.db import Database
from income33.logging_utils import setup_component_logger
from income33.models import CommandCompleteRequest, CommandRequest, HeartbeatRequest

setup_component_logger("income33.control_tower", "control_tower.log")
logger = logging.getLogger("income33.control_tower.app")


DASHBOARD_ALLOWED_COMMANDS = {
    "start",
    "stop",
    "restart",
    "status",
    "open_login",
    "login_done",
    "fill_login",
    "refresh_page",
    "preview_send_targets",
    "send_expected_tax_amounts",
    "preview_rate_based_bookkeeping_expected_tax_amounts",
    "send_rate_based_bookkeeping_expected_tax_amounts",
}

BOT_DISPLAY_GROUPS: list[tuple[str, str, int, int, int]] = [
    ("발송 봇 01-09", "sender", 1, 9, 0),
    ("신고 봇 01-09", "reporter", 1, 9, 9),
]


def _build_html_table(columns: list[str], rows: list[dict[str, Any]]) -> str:
    header = "".join(f"<th>{escape(col)}</th>" for col in columns)
    body_parts: list[str] = []
    for row in rows:
        cells = "".join(
            f"<td>{row.get(col, '')}</td>"
            if col == "actions"
            else f"<td>{escape(str(row.get(col, '')))}</td>"
            for col in columns
        )
        body_parts.append(f"<tr>{cells}</tr>")

    body = "".join(body_parts) if body_parts else "<tr><td colspan='99'>No rows</td></tr>"
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def _command_button(
    bot_id: str,
    command: str,
    label: str,
    css_class: str = "",
    confirm_message: str | None = None,
) -> str:
    safe_bot_id = escape(bot_id, quote=True)
    safe_command = escape(command, quote=True)
    safe_label = escape(label)
    safe_class = escape(css_class, quote=True)
    confirm_attr = ""
    if confirm_message:
        safe_confirm = escape(confirm_message, quote=True)
        confirm_attr = f" onclick=\"return confirm('{safe_confirm}')\""
    return (
        f"<form method='post' action='/ui/bots/{safe_bot_id}/commands/{safe_command}' "
        "style='display:inline'>"
        f"<button class='{safe_class}' type='submit'{confirm_attr}>{safe_label}</button>"
        "</form>"
    )


def _submit_auth_code_form(bot_id: str) -> str:
    safe_bot_id = escape(bot_id, quote=True)
    return (
        f"<form method='post' action='/ui/bots/{safe_bot_id}/auth-code' class='inline-form'>"
        "<input type='password' name='auth_code' placeholder='인증코드 입력' "
        "autocomplete='one-time-code' required />"
        "<button type='submit' class='auth'>인증코드 제출</button>"
        "</form>"
    )


def _rate_based_bookkeeping_form(bot_id: str) -> str:
    safe_bot_id = escape(bot_id, quote=True)
    return (
        f"<form method='post' action='/ui/bots/{safe_bot_id}/rate-based-bookkeeping-send' "
        "class='inline-form' style='display:inline'>"
        "<input type='number' name='tax_doc_id' placeholder='taxDocId' min='1' required />"
        "<button type='submit' class='send' "
        "onclick=\"return confirm('taxDocId 기준 경비율 장부 계산발송을 진행할까요?')\">"
        "경비율 장부발송</button>"
        "</form>"
    )


def _bot_actions_html(bot_id: str) -> str:
    buttons = [
        _command_button(bot_id, "start", "시작"),
        _command_button(bot_id, "stop", "중지", "danger"),
        _command_button(bot_id, "restart", "재시작"),
        _command_button(bot_id, "open_login", "로그인 열기", "login"),
        _command_button(bot_id, "fill_login", "로그인 입력", "login"),
        _command_button(bot_id, "refresh_page", "새로고침", "refresh"),
        _command_button(bot_id, "preview_send_targets", "목록조회 테스트", "refresh"),
    ]
    if bot_id.startswith("sender-"):
        buttons.append(
            _command_button(
                bot_id,
                "send_expected_tax_amounts",
                "계산발송",
                "send",
                "목록조회된 대상에 실제 계산발송을 요청하고 5분 후 자동 반복합니다. 진행할까요?",
            )
        )
        buttons.append(_rate_based_bookkeeping_form(bot_id))
        buttons.append(
            _command_button(
                bot_id,
                "preview_rate_based_bookkeeping_expected_tax_amounts",
                "일괄세션 확인",
                "refresh",
            )
        )
        buttons.append(
            _command_button(
                bot_id,
                "send_rate_based_bookkeeping_expected_tax_amounts",
                "일괄 계산발송 시작",
                "send",
                "TA 목록을 조회한 뒤 각 taxDocId별 경비율 장부 계산발송을 진행합니다. 진행할까요?",
            )
        )
    buttons.extend(
        [
            _command_button(bot_id, "login_done", "로그인 완료", "login-done"),
            _submit_auth_code_form(bot_id),
        ]
    )
    return " ".join(buttons)


def _build_fixed_slot_bot_sections(raw_bots: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    bot_map = {str(bot.get("bot_id", "")): bot for bot in raw_bots}
    sections: list[tuple[str, list[dict[str, Any]]]] = []

    for section_title, bot_type, start, end, pc_offset in BOT_DISPLAY_GROUPS:
        section_rows: list[dict[str, Any]] = []
        for slot in range(start, end + 1):
            bot_id = f"{bot_type}-{slot:02d}"
            row = dict(bot_map.get(bot_id) or {})
            if not row:
                row = {
                    "bot_id": bot_id,
                    "bot_type": bot_type,
                    "pc_id": f"pc-{slot + pc_offset:02d}",
                    "status": "connection_required",
                    "current_step": "접속필요",
                    "last_heartbeat_at": None,
                    "success_count": 0,
                    "failure_count": 0,
                }

            if not row.get("last_heartbeat_at"):
                row["status"] = row.get("status") or "connection_required"
                row["current_step"] = "접속필요"

            row["actions"] = _bot_actions_html(bot_id)
            section_rows.append(row)

        sections.append((section_title, section_rows))

    return sections


def _render_dashboard_html(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    agents = payload["agents"]
    bot_sections = _build_fixed_slot_bot_sections(payload["bots"])

    summary_items = "".join(
        f"<li><strong>{escape(str(key))}</strong>: {escape(str(value))}</li>" for key, value in summary.items()
    )

    agent_columns = [
        "pc_id",
        "hostname",
        "ip_address",
        "status",
        "assigned_bot_ids",
        "last_heartbeat_at",
    ]
    bot_columns = [
        "bot_id",
        "bot_type",
        "pc_id",
        "status",
        "current_step",
        "last_heartbeat_at",
        "success_count",
        "failure_count",
        "actions",
    ]

    agents_html = _build_html_table(agent_columns, agents)
    bot_sections_html = "".join(
        (
            "<div class='card'>"
            f"<h2>{escape(section_title)}</h2>"
            f"{_build_html_table(bot_columns, rows)}"
            "</div>"
        )
        for section_title, rows in bot_sections
    )

    return f"""
    <!doctype html>
    <html lang='ko'>
      <head>
        <meta charset='utf-8' />
        <meta http-equiv='refresh' content='5' />
        <title>33income Control Tower</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 24px; background: #f7f8fb; }}
          h1, h2 {{ color: #1f2937; }}
          .card {{ background: #fff; padding: 16px; border-radius: 8px; margin-bottom: 18px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
          table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
          th, td {{ border: 1px solid #e5e7eb; padding: 8px; text-align: left; vertical-align: top; }}
          th {{ background: #f3f4f6; }}
          button {{ margin: 2px; padding: 5px 8px; border: 1px solid #d1d5db; border-radius: 4px; background: #fff; cursor: pointer; }}
          .inline-form {{ display: inline; margin-left: 6px; }}
          .inline-form input {{ width: 130px; margin-right: 4px; padding: 4px 6px; }}
          button.danger {{ color: #b91c1c; }}
          button.login {{ background: #eef2ff; border-color: #818cf8; }}
          button.login-done {{ background: #ecfdf5; border-color: #34d399; }}
          button.refresh {{ background: #eff6ff; border-color: #60a5fa; }}
          button.send {{ background: #fef2f2; border-color: #f87171; color: #991b1b; font-weight: 600; }}
          button.auth {{ background: #fff7ed; border-color: #fb923c; }}
          code {{ background: #eef2ff; padding: 2px 6px; border-radius: 4px; }}
        </style>
      </head>
      <body>
        <h1>33income Control Tower</h1>
        <p>관제 대시보드 (Windows 런타임 기준)</p>
        <p><strong>연결 확인:</strong> 발송/신고 표가 01번부터 고정으로 표시됩니다. 아직 에이전트가 붙지 않은 봇은 <code>접속필요</code>로 보이고, 붙으면 <code>last_heartbeat_at</code> 시간이 갱신됩니다.</p>

        <div class='card'>
          <h2>요약</h2>
          <ul>{summary_items}</ul>
          <p>API: <code>/api/summary</code>, <code>/api/agents</code>, <code>/api/bots</code></p>
        </div>

        <div class='card'>
          <h2>Agents</h2>
          {agents_html}
        </div>

        {bot_sections_html}
      </body>
    </html>
    """


def create_app(
    config: AppConfig | None = None,
    service: ControlTowerService | None = None,
) -> FastAPI:
    resolved_config = config or load_config()
    resolved_service = service or ControlTowerService(
        db=Database(resolved_config.control_tower.database_path),
        bootstrap_agent_count=resolved_config.control_tower.bootstrap_agent_count,
    )

    # Ensure startup seed even in tests that do not run lifespan events.
    resolved_service.bootstrap()

    app = FastAPI(title="33income Control Tower", version="0.1.0")
    app.state.config = resolved_config
    app.state.service = resolved_service

    logger.info(
        "control_tower_app_ready host=%s port=%s db_path=%s",
        resolved_config.control_tower.host,
        resolved_config.control_tower.port,
        resolved_config.control_tower.database_path,
    )

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        payload = app.state.service.build_dashboard()
        return _render_dashboard_html(payload)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "title": app.title,
            "version": app.version,
        }

    @app.get("/api/summary")
    def summary() -> dict[str, Any]:
        return app.state.service.get_summary()

    @app.get("/api/agents")
    def agents() -> dict[str, Any]:
        return {"agents": app.state.service.list_agents()}

    @app.get("/api/bots")
    def bots(bot_type: str | None = Query(default=None)) -> dict[str, Any]:
        return {"bots": app.state.service.list_bots(bot_type=bot_type)}

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
        from urllib.parse import parse_qs

        raw_body = (await request.body()).decode("utf-8", errors="ignore")
        auth_code = parse_qs(raw_body).get("auth_code", [""])[0].strip()
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

    @app.post("/ui/bots/{bot_id}/rate-based-bookkeeping-send")
    async def queue_rate_based_bookkeeping_send(bot_id: str, request: Request) -> RedirectResponse:
        from urllib.parse import parse_qs

        raw_body = (await request.body()).decode("utf-8", errors="ignore")
        raw_tax_doc_id = parse_qs(raw_body).get("tax_doc_id", [""])[0].strip()
        try:
            tax_doc_id = int(raw_tax_doc_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="tax_doc_id must be a positive integer") from exc
        if tax_doc_id <= 0:
            raise HTTPException(status_code=400, detail="tax_doc_id must be a positive integer")
        try:
            app.state.service.queue_bot_command(
                bot_id=bot_id,
                command="send_rate_based_bookkeeping_expected_tax_amount",
                payload={"tax_doc_id": tax_doc_id},
            )
        except KeyError as exc:
            logger.warning("queue_rate_based_bookkeeping_not_found bot_id=%s", bot_id)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            logger.warning("queue_rate_based_bookkeeping_rejected bot_id=%s reason=%s", bot_id, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=303)

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

    return app


app = create_app()


def main() -> None:
    runtime_config = load_config()
    logger.info(
        "control_tower_start host=%s port=%s",
        runtime_config.control_tower.host,
        runtime_config.control_tower.port,
    )
    uvicorn.run(
        "income33.control_tower.app:app",
        host=runtime_config.control_tower.host,
        port=runtime_config.control_tower.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
