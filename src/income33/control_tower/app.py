from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI

from income33.config import AppConfig, load_config
from income33.control_tower.agent_command_routes import register_agent_command_routes
from income33.control_tower.bot_command_routes import (
    DASHBOARD_ALLOWED_COMMANDS as _DASHBOARD_ALLOWED_COMMANDS,
    register_bot_command_routes,
)
from income33.control_tower.dashboard import render_dashboard_html
from income33.control_tower.public_routes import register_public_routes
from income33.control_tower.service import ControlTowerService
from income33.db import Database
from income33.logging_utils import setup_component_logger

setup_component_logger("income33.control_tower", "control_tower.log")
logger = logging.getLogger("income33.control_tower.app")

DASHBOARD_ALLOWED_COMMANDS = _DASHBOARD_ALLOWED_COMMANDS


def _render_dashboard_html(payload: dict) -> str:
    return render_dashboard_html(payload)


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
    register_public_routes(app)
    register_bot_command_routes(app)
    register_agent_command_routes(app)

    logger.info(
        "control_tower_app_ready host=%s port=%s db_path=%s",
        resolved_config.control_tower.host,
        resolved_config.control_tower.port,
        resolved_config.control_tower.database_path,
    )

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
