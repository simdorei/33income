from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass
class ControlTowerConfig:
    host: str = "127.0.0.1"
    port: int = 8330
    database_path: str = "data/33income.db"
    bootstrap_agent_count: int = 18
    stale_seconds: int = 180


@dataclass
class AgentConfig:
    pc_id: str = "pc-01"
    hostname: str = "WIN-PC-01"
    ip_address: str = "127.0.0.1"
    control_tower_url: str = "http://127.0.0.1:8330"
    bot_id: str = "sender-01"
    bot_type: str = "sender"
    heartbeat_interval_seconds: int = 5
    command_poll_interval_seconds: int = 1


@dataclass
class AppConfig:
    control_tower: ControlTowerConfig = field(default_factory=ControlTowerConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)


def _load_yaml(path: str | os.PathLike[str]) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    return data or {}


def _env_int(name: str, fallback: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return fallback
    return int(value)


def load_config(
    env_file: str = ".env",
    control_tower_config_path: str = "config/control_tower.yaml",
    agent_config_path: str = "config/agent.yaml",
) -> AppConfig:
    env_path = Path(env_file)
    if env_path.exists():
        load_dotenv(env_path, override=True)

    control_tower_yaml = _load_yaml(control_tower_config_path)
    agent_yaml = _load_yaml(agent_config_path)

    server_yaml = control_tower_yaml.get("server", {})
    database_yaml = control_tower_yaml.get("database", {})
    slot_yaml = control_tower_yaml.get("slots", control_tower_yaml.get("bootstrap", {}))

    agent_section = agent_yaml.get("agent", {})
    bot_section = agent_yaml.get("bot", {})

    host = os.getenv("INCOME33_CONTROL_TOWER_HOST", server_yaml.get("host", "127.0.0.1"))
    port = _env_int("INCOME33_CONTROL_TOWER_PORT", int(server_yaml.get("port", 8330)))
    database_path = os.getenv(
        "INCOME33_DB_PATH",
        str(database_yaml.get("path", "data/33income.db")),
    )
    bootstrap_agent_count = _env_int(
        "INCOME33_BOOTSTRAP_AGENT_COUNT",
        int(slot_yaml.get("agent_count", 18)),
    )
    stale_seconds = _env_int(
        "INCOME33_STALE_SECONDS",
        int(slot_yaml.get("stale_seconds", 180)),
    )

    control_tower_url = os.getenv(
        "CONTROL_TOWER_URL",
        os.getenv(
            "INCOME33_AGENT_CONTROL_TOWER_URL",
            str(agent_section.get("control_tower_url", "http://127.0.0.1:8330")),
        ),
    )

    pc_id = os.getenv("INCOME33_AGENT_PC_ID", str(agent_section.get("pc_id", "pc-01")))
    hostname = os.getenv(
        "INCOME33_AGENT_HOSTNAME",
        str(agent_section.get("hostname", "WIN-PC-01")),
    )
    ip_address = os.getenv(
        "INCOME33_AGENT_IP_ADDRESS",
        str(agent_section.get("ip_address", "127.0.0.1")),
    )
    bot_id = os.getenv(
        "INCOME33_AGENT_BOT_ID",
        str(bot_section.get("bot_id", agent_section.get("bot_id", "sender-01"))),
    )
    bot_type = os.getenv(
        "INCOME33_AGENT_BOT_TYPE",
        str(bot_section.get("bot_type", agent_section.get("bot_type", "sender"))),
    )
    heartbeat_interval = max(
        1,
        _env_int(
            "INCOME33_AGENT_HEARTBEAT_INTERVAL_SECONDS",
            int(agent_section.get("heartbeat_interval_seconds", 5)),
        ),
    )
    command_poll_interval = max(
        1,
        _env_int(
            "INCOME33_AGENT_COMMAND_POLL_INTERVAL_SECONDS",
            int(agent_section.get("command_poll_interval_seconds", 1)),
        ),
    )

    return AppConfig(
        control_tower=ControlTowerConfig(
            host=host,
            port=port,
            database_path=database_path,
            bootstrap_agent_count=bootstrap_agent_count,
            stale_seconds=stale_seconds,
        ),
        agent=AgentConfig(
            pc_id=pc_id,
            hostname=hostname,
            ip_address=ip_address,
            control_tower_url=control_tower_url,
            bot_id=bot_id,
            bot_type=bot_type,
            heartbeat_interval_seconds=heartbeat_interval,
            command_poll_interval_seconds=command_poll_interval,
        ),
    )
