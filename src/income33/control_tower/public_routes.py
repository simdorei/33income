from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from income33.control_tower.dashboard import render_dashboard_html


def register_public_routes(app: FastAPI) -> None:
    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        payload = app.state.service.build_dashboard()
        return render_dashboard_html(payload)

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
