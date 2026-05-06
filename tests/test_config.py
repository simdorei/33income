from income33.config import load_config


def test_load_config_with_env_and_yaml(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "INCOME33_CONTROL_TOWER_HOST=0.0.0.0\n"
        "INCOME33_CONTROL_TOWER_PORT=9444\n"
        "INCOME33_DB_PATH=data/test.db\n"
        "INCOME33_BOOTSTRAP_AGENT_COUNT=12\n"
        "INCOME33_AGENT_PC_ID=pc-17\n"
        "INCOME33_AGENT_BOT_ID=reporter-08\n"
        "INCOME33_AGENT_COMMAND_POLL_INTERVAL_SECONDS=0\n",
        encoding="utf-8",
    )

    ct_yaml = tmp_path / "control_tower.yaml"
    ct_yaml.write_text(
        "server:\n"
        "  host: 127.0.0.1\n"
        "  port: 8330\n"
        "database:\n"
        "  path: data/yaml.db\n",
        encoding="utf-8",
    )

    agent_yaml = tmp_path / "agent.yaml"
    agent_yaml.write_text(
        "agent:\n"
        "  pc_id: pc-01\n"
        "  bot_id: sender-01\n"
        "  bot_type: sender\n",
        encoding="utf-8",
    )

    for key in [
        "INCOME33_CONTROL_TOWER_HOST",
        "INCOME33_CONTROL_TOWER_PORT",
        "INCOME33_DB_PATH",
        "INCOME33_BOOTSTRAP_AGENT_COUNT",
        "INCOME33_AGENT_PC_ID",
        "INCOME33_AGENT_BOT_ID",
    ]:
        monkeypatch.delenv(key, raising=False)

    config = load_config(
        env_file=str(env_file),
        control_tower_config_path=str(ct_yaml),
        agent_config_path=str(agent_yaml),
    )

    assert config.control_tower.host == "0.0.0.0"
    assert config.control_tower.port == 9444
    assert config.control_tower.database_path == "data/test.db"
    assert config.control_tower.bootstrap_agent_count == 12

    assert config.agent.pc_id == "pc-17"
    assert config.agent.bot_id == "reporter-08"
    assert config.agent.bot_type == "sender"
    assert config.agent.heartbeat_interval_seconds == 5
    assert config.agent.command_poll_interval_seconds == 1
