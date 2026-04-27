from __future__ import annotations

import logging
from html import escape
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from income33.config import AppConfig, load_config
from income33.control_tower.service import ControlTowerService
from income33.db import Database
from income33.logging_utils import setup_component_logger
from income33.models import CommandCompleteRequest, CommandRequest, HeartbeatRequest

setup_component_logger("income33.control_tower", "control_tower.log")
logger = logging.getLogger("income33.control_tower.app")


def _build_html_table(columns: list[str], rows: list[dict[str, Any]]) -> str:
    header = "".join(f"<th>{escape(col)}</th>" for col in columns)
    body_parts: list[str] = []
    for row in rows:
        cells = "".join(
            f"<td>{escape(str(row.get(col, '')))}</td>" for col in columns
        )
        body_parts.append(f"<tr>{cells}</tr>")

    body = "".join(body_parts) if body_parts else "<tr><td colspan='99'>No rows</td></tr>"
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def _render_dashboard_html(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    agents = payload["agents"]
    bots = payload["bots"]

    summary_items = "".join(
        f"<li><strong>{escape(str(key))}</strong>: {escape(str(value))}</li>"
        for key, value in summary.items()
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
    ]

    agents_html = _build_html_table(agent_columns, agents)
    bots_html = _build_html_table(bot_columns, bots)

    return f"""
    <!doctype html>
    <html lang='ko'>
      <head>
        <meta charset='utf-8' />
        <title>33income Control Tower</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 24px; background: #f7f8fb; }}
          h1, h2 {{ color: #1f2937; }}
          .card {{ background: #fff; padding: 16px; border-radius: 8px; margin-bottom: 18px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
          table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
          th, td {{ border: 1px solid #e5e7eb; padding: 8px; text-align: left; }}
          th {{ background: #f3f4f6; }}
          code {{ background: #eef2ff; padding: 2px 6px; border-radius: 4px; }}
        </style>
      </head>
      <body>
        <h1>33income Control Tower</h1>
        <p>Mock 관제 대시보드 (Windows 런타임 기준)</p>

        <div class='card'>
          <h2>요약</h2>
          <ul>{summary_items}</ul>
          <p>API: <code>/api/summary</code>, <code>/api/agents</code>, <code>/api/bots</code></p>
        </div>

        <div class='card'>
          <h2>Agents</h2>
          {agents_html}
        </div>

        <div class='card'>
          <h2>Bots</h2>
          {bots_html}
        </div>
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
        mock_agent_count=resolved_config.control_tower.mock_agent_count,
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
        return command

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
