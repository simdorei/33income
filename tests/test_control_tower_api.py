from fastapi.testclient import TestClient

from income33.config import AppConfig, ControlTowerConfig
from income33.control_tower.app import create_app
from income33.control_tower.service import ControlTowerService
from income33.db import Database


def build_client(tmp_path):
    db_path = tmp_path / "tower.db"
    config = AppConfig(
        control_tower=ControlTowerConfig(database_path=str(db_path), bootstrap_agent_count=18)
    )
    db = Database(str(db_path))
    service = ControlTowerService(db=db, bootstrap_agent_count=18)
    app = create_app(config=config, service=service)
    return TestClient(app)


def test_summary_and_root_dashboard(tmp_path):
    client = build_client(tmp_path)

    summary = client.get("/api/summary")
    assert summary.status_code == 200
    payload = summary.json()

    assert payload["total_agents"] == 18
    assert payload["total_bots"] == 18
    assert payload["online_agents"] == 0
    assert payload["offline_agents"] == 18

    root = client.get("/")
    assert root.status_code == 200
    assert "33income Control Tower" in root.text
    assert "발송 봇 01-09" in root.text
    assert "신고 봇 01-09" in root.text
    assert "접속필요" in root.text
    assert "sender-01" in root.text
    assert "sender-09" in root.text
    assert "reporter-01" in root.text
    assert "reporter-09" in root.text
    assert "로그인 열기" in root.text
    assert "로그인 입력" in root.text
    assert "인증코드 제출" in root.text
    assert "새로고침" in root.text
    assert "content='5'" in root.text
    assert "/ui/bots/sender-01/commands/open_login" in root.text
    assert "/ui/bots/sender-01/commands/fill_login" in root.text


def test_queue_poll_and_complete_command(tmp_path):
    client = build_client(tmp_path)

    queued = client.post("/api/bots/sender-01/commands", json={"command": "start"})
    assert queued.status_code == 200
    queued_payload = queued.json()

    assert queued_payload["bot_id"] == "sender-01"
    assert queued_payload["status"] == "pending"

    polled = client.get("/api/agents/pc-01/commands/poll")
    assert polled.status_code == 200
    polled_payload = polled.json()["commands"]
    assert len(polled_payload) == 1
    assert polled_payload[0]["status"] == "running"

    command_id = polled_payload[0]["id"]
    complete = client.post(f"/api/commands/{command_id}/complete", json={"status": "done"})
    assert complete.status_code == 200
    assert complete.json()["status"] == "done"


def test_dashboard_can_queue_login_command(tmp_path):
    client = build_client(tmp_path)

    response = client.post(
        "/ui/bots/sender-01/commands/open_login",
        follow_redirects=False,
    )

    assert response.status_code == 303
    polled = client.get("/api/agents/pc-01/commands/poll")
    assert polled.status_code == 200
    commands = polled.json()["commands"]
    assert len(commands) == 1
    assert commands[0]["command"] == "open_login"


def test_dashboard_can_queue_auth_code_command(tmp_path):
    client = build_client(tmp_path)

    response = client.post(
        "/ui/bots/sender-01/auth-code",
        data={"auth_code": "123456"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    polled = client.get("/api/agents/pc-01/commands/poll")
    assert polled.status_code == 200
    commands = polled.json()["commands"]
    assert len(commands) == 1
    assert commands[0]["command"] == "submit_auth_code"
    assert "123456" in commands[0]["payload_json"]


def test_api_submit_auth_code_response_is_masked_but_agent_poll_has_value(tmp_path):
    client = build_client(tmp_path)

    queued = client.post(
        "/api/bots/sender-01/commands",
        json={"command": "submit_auth_code", "payload": {"auth_code": "654321"}},
    )

    assert queued.status_code == 200
    assert "654321" not in queued.text
    assert "***" in queued.json()["payload_json"]

    polled = client.get("/api/agents/pc-01/commands/poll")
    assert polled.status_code == 200
    commands = polled.json()["commands"]
    assert len(commands) == 1
    assert "654321" in commands[0]["payload_json"]

def test_heartbeat_marks_slot_connected_and_updates_bot(tmp_path):
    client = build_client(tmp_path)

    hb = client.post(
        "/api/agents/heartbeat",
        json={
            "pc_id": "pc-01",
            "hostname": "WIN-PC-01",
            "ip_address": "192.168.10.101",
            "agent_status": "online",
            "bot_id": "sender-01",
            "bot_status": "running",
            "current_step": "step_a",
            "success_count": 2,
            "failure_count": 1,
        },
    )
    assert hb.status_code == 200
    assert hb.json()["accepted"] is True

    summary = client.get("/api/summary")
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["online_agents"] == 1
    assert payload["offline_agents"] == 17

    bots = client.get("/api/bots?bot_type=sender")
    assert bots.status_code == 200
    sender01 = next(bot for bot in bots.json()["bots"] if bot["bot_id"] == "sender-01")
    assert sender01["status"] == "running"
    assert sender01["last_heartbeat_at"] is not None
    assert sender01["current_step"] == "step_a"

    root = client.get("/")
    assert root.status_code == 200
    assert "sender-01" in root.text
    assert "step_a" in root.text
