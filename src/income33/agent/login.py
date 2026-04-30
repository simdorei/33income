from __future__ import annotations

import logging
from typing import Any

from income33.agent.browser_control import (
    is_browser_control_dry_run,
    launch_login_browser,
    resolve_login_url,
    resolve_profile_dir,
)


def is_login_dry_run(payload: dict[str, Any] | None = None) -> bool:
    return is_browser_control_dry_run(payload)


def open_login_window(
    *,
    bot_id: str,
    payload: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Open human-login browser window on the local bot PC."""

    logger = logger or logging.getLogger("income33.agent.login")
    return launch_login_browser(bot_id=bot_id, payload=payload, logger=logger)


def open_login_browser(
    *,
    bot_id: str,
    payload: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Backward-compatible alias for older call sites/tests."""

    return open_login_window(bot_id=bot_id, payload=payload, logger=logger)


__all__ = [
    "is_login_dry_run",
    "open_login_browser",
    "open_login_window",
    "resolve_login_url",
    "resolve_profile_dir",
]
