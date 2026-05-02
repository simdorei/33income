from fastapi.testclient import TestClient

from income33.config import AppConfig, ControlTowerConfig
from income33.control_tower.app import create_app
from income33.control_tower.service import (
    ControlTowerService,
    command_retry_policy,
    command_policies,
    dashboard_allowed_commands,
    get_command_policy,
    resolve_retry_interval_seconds,
    resolve_retry_max_attempts,
    sender_only_commands,
    should_cancel_repeated_send_before_command,
    should_schedule_repeated_send,
)
from income33.db import Database
from income33.models import COMMAND_TYPES


def build_client(tmp_path):
    db_path = tmp_path / "tower.db"
    config = AppConfig(
        control_tower=ControlTowerConfig(database_path=str(db_path), bootstrap_agent_count=18)
    )
    db = Database(str(db_path))
    service = ControlTowerService(db=db, bootstrap_agent_count=18)
    app = create_app(config=config, service=service)
    return TestClient(app)


def test_command_policy_centralizes_dashboard_allowlist_and_sender_only_guardrails():
    allowed = dashboard_allowed_commands()
    assert "open_login" in allowed
    assert "send_expected_tax_amounts" in allowed
    assert "submit_auth_code" not in allowed

    assert get_command_policy("send_expected_tax_amounts").sender_only is True
    assert get_command_policy("open_login").sender_only is False


def test_command_metadata_and_policy_maps_are_aligned():
    policies = command_policies()
    assert set(COMMAND_TYPES) == set(policies)

    allowed = dashboard_allowed_commands()
    assert allowed == {command for command, policy in policies.items() if policy.dashboard_allowed}
    assert sender_only_commands() == {
        command for command, policy in policies.items() if policy.sender_only
    }


def test_repeat_orchestration_policy_helpers_are_centralized():
    assert should_cancel_repeated_send_before_command("status") is False
    assert should_cancel_repeated_send_before_command("send_expected_tax_amounts") is False
    assert should_cancel_repeated_send_before_command("stop") is True

    assert should_schedule_repeated_send("send_expected_tax_amounts", {"year": 2025}) is True
    assert should_schedule_repeated_send("send_expected_tax_amounts", {"tax_doc_ids": [1]}) is False
    assert should_schedule_repeated_send(
        "send_expected_tax_amounts",
        {"tax_doc_ids": [1], "repeat": True},
    ) is True
    assert should_schedule_repeated_send("status", {"repeat": True}) is False


def test_retry_policy_resolution_uses_command_policy_defaults_and_legacy_env(monkeypatch):
    assert command_retry_policy({"_retry": {"interval_sec": 120, "max_attempts": 4}}) == {
        "interval_sec": 120,
        "max_attempts": 4,
    }
    assert command_retry_policy({"retry": {"interval_sec": 90}}) == {"interval_sec": 90}
    assert command_retry_policy({"interval_sec": 15, "max_attempts": 2}) == {
        "interval_sec": 15,
        "max_attempts": 2,
    }

    monkeypatch.delenv("INCOME33_SEND_REPEAT_INTERVAL_SECONDS", raising=False)
    assert resolve_retry_interval_seconds("send_expected_tax_amounts", {}) == 300
    assert resolve_retry_max_attempts("send_expected_tax_amounts", {}) == 3
    assert resolve_retry_interval_seconds(
        "preview_rate_based_bookkeeping_expected_tax_amounts",
        {},
    ) == 60
    assert resolve_retry_max_attempts(
        "preview_rate_based_bookkeeping_expected_tax_amounts",
        {},
    ) == 2

    monkeypatch.setenv("INCOME33_SEND_REPEAT_INTERVAL_SECONDS", "420")
    assert resolve_retry_interval_seconds("send_expected_tax_amounts", {}) == 420
    monkeypatch.setenv("INCOME33_SEND_REPEAT_INTERVAL_SECONDS", "0")
    assert resolve_retry_interval_seconds("send_expected_tax_amounts", {}) == 300


def test_default_retry_hint_applies_when_not_provided(tmp_path):
    client = build_client(tmp_path)

    queued = client.post(
        "/api/bots/sender-01/commands",
        json={"command": "send_expected_tax_amounts", "payload": {"tax_doc_ids": [1360165]}},
    )
    assert queued.status_code == 200

    polled = client.get("/api/agents/pc-01/commands/poll")
    assert polled.status_code == 200
    commands = polled.json()["commands"]
    assert len(commands) == 1
    assert commands[0]["command"] == "send_expected_tax_amounts"
    assert '"_retry": {"interval_sec": 300, "max_attempts": 3}' in commands[0]["payload_json"]


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
    assert "목록조회 테스트" in root.text
    assert "계산발송" in root.text
    assert "일괄세션 확인" in root.text
    assert "일괄 계산발송 시작" in root.text
    assert "content='5'" in root.text
    assert "/ui/bots/sender-01/commands/open_login" in root.text
    assert "/ui/bots/sender-01/commands/fill_login" in root.text
    assert "/ui/bots/sender-01/commands/preview_send_targets" in root.text
    assert "/ui/bots/sender-01/commands/send_expected_tax_amounts" in root.text
    assert "/ui/bots/sender-01/send-expected-tax-amounts-list" in root.text
    assert "name='tax_doc_ids'" in root.text
    assert "<textarea" in root.text
    assert "/ui/bots/sender-01/commands/preview_rate_based_bookkeeping_expected_tax_amounts" in root.text
    assert "/ui/bots/sender-01/commands/send_rate_based_bookkeeping_expected_tax_amounts" in root.text
    assert "return confirm" in root.text
    assert "/ui/bots/reporter-01/commands/send_expected_tax_amounts" not in root.text
    assert "/ui/bots/reporter-01/commands/send_rate_based_bookkeeping_expected_tax_amounts" not in root.text


def test_api_rejects_expected_tax_amount_commands_for_reporter_bot(tmp_path):
    client = build_client(tmp_path)

    for command in (
        "send_expected_tax_amounts",
        "send_bookkeeping_expected_tax_amount",
        "send_rate_based_bookkeeping_expected_tax_amount",
        "preview_rate_based_bookkeeping_expected_tax_amounts",
        "send_rate_based_bookkeeping_expected_tax_amounts",
    ):
        queued = client.post(
            "/api/bots/reporter-01/commands",
            json={"command": command, "payload": {}},
        )
        assert queued.status_code == 400
        assert "only allowed for sender" in queued.text


def test_api_can_queue_send_bookkeeping_expected_tax_amount_command(tmp_path):
    client = build_client(tmp_path)

    queued = client.post(
        "/api/bots/sender-01/commands",
        json={
            "command": "send_bookkeeping_expected_tax_amount",
            "payload": {
                "tax_doc_id": 1345836,
                "submit_account_type": "CUSTOMER",
                "total_business_expense_amount": 41538144,
            },
        },
    )
    assert queued.status_code == 200
    assert queued.json()["status"] == "pending"

    polled = client.get("/api/agents/pc-01/commands/poll")
    assert polled.status_code == 200
    commands = polled.json()["commands"]
    assert len(commands) == 1
    assert commands[0]["command"] == "send_bookkeeping_expected_tax_amount"
    assert '"tax_doc_id": 1345836' in commands[0]["payload_json"]
    assert '"total_business_expense_amount": 41538144' in commands[0]["payload_json"]


def test_api_can_queue_send_rate_based_bookkeeping_expected_tax_amount_command(tmp_path):
    client = build_client(tmp_path)

    queued = client.post(
        "/api/bots/sender-01/commands",
        json={
            "command": "send_rate_based_bookkeeping_expected_tax_amount",
            "payload": {"tax_doc_id": 1348568},
        },
    )
    assert queued.status_code == 200
    assert queued.json()["status"] == "pending"

    polled = client.get("/api/agents/pc-01/commands/poll")
    assert polled.status_code == 200
    commands = polled.json()["commands"]
    assert len(commands) == 1
    assert commands[0]["command"] == "send_rate_based_bookkeeping_expected_tax_amount"
    assert '"tax_doc_id": 1348568' in commands[0]["payload_json"]


def test_api_can_queue_bulk_rate_based_bookkeeping_commands(tmp_path):
    for command in (
        "preview_rate_based_bookkeeping_expected_tax_amounts",
        "send_rate_based_bookkeeping_expected_tax_amounts",
    ):
        client = build_client(tmp_path)
        queued = client.post(
            "/api/bots/sender-01/commands",
            json={"command": command, "payload": {"year": 2025, "size": 20}},
        )
        assert queued.status_code == 200
        assert queued.json()["status"] == "pending"

        polled = client.get("/api/agents/pc-01/commands/poll")
        assert polled.status_code == 200
        commands = polled.json()["commands"]
        assert len(commands) == 1
        assert commands[0]["command"] == command
        assert '"year": 2025' in commands[0]["payload_json"]


def test_api_can_queue_send_expected_tax_amounts_command(tmp_path):
    client = build_client(tmp_path)

    queued = client.post(
        "/api/bots/sender-01/commands",
        json={"command": "send_expected_tax_amounts", "payload": {"tax_doc_ids": [1360165]}},
    )
    assert queued.status_code == 200
    assert queued.json()["status"] == "pending"

    polled = client.get("/api/agents/pc-01/commands/poll")
    assert polled.status_code == 200
    commands = polled.json()["commands"]
    assert len(commands) == 1
    assert commands[0]["command"] == "send_expected_tax_amounts"
    assert '"tax_doc_ids": [1360165]' in commands[0]["payload_json"]


def test_api_can_queue_command_with_envelope_payload(tmp_path):
    client = build_client(tmp_path)

    queued = client.post(
        "/api/bots/sender-01/commands",
        json={
            "command": "send_expected_tax_amounts",
            "payload": {
                "command": "send_expected_tax_amounts",
                "target": {"bot_id": "sender-01", "bot_role": "sender"},
                "payload": {"tax_doc_ids": [1360165, 1360166]},
                "meta": {"request_id": "ct-test-001"},
                "retry": {"interval_sec": 120, "max_attempts": 4},
            },
        },
    )
    assert queued.status_code == 200

    polled = client.get("/api/agents/pc-01/commands/poll")
    assert polled.status_code == 200
    commands = polled.json()["commands"]
    assert len(commands) == 1
    assert '"tax_doc_ids": [1360165, 1360166]' in commands[0]["payload_json"]
    assert '"_meta": {"request_id": "ct-test-001"}' in commands[0]["payload_json"]
    assert '"_retry": {"interval_sec": 120, "max_attempts": 4}' in commands[0]["payload_json"]


def test_api_rejects_envelope_target_role_mismatch(tmp_path):
    client = build_client(tmp_path)

    queued = client.post(
        "/api/bots/sender-01/commands",
        json={
            "command": "send_expected_tax_amounts",
            "payload": {
                "command": "send_expected_tax_amounts",
                "target": {"bot_id": "sender-01", "bot_role": "reporter"},
                "payload": {"tax_doc_ids": [1360165]},
            },
        },
    )
    assert queued.status_code == 400
    assert "target bot_role does not match bot type" in queued.text


def test_api_rejects_envelope_target_bot_id_mismatch(tmp_path):
    client = build_client(tmp_path)

    queued = client.post(
        "/api/bots/sender-01/commands",
        json={
            "command": "send_expected_tax_amounts",
            "payload": {
                "command": "send_expected_tax_amounts",
                "target": {"bot_id": "sender-02", "bot_role": "sender"},
                "payload": {"tax_doc_ids": [1360165]},
            },
        },
    )
    assert queued.status_code == 400
    assert "target bot_id does not match bot id" in queued.text


def test_api_can_queue_preview_send_targets_command(tmp_path):
    client = build_client(tmp_path)

    queued = client.post(
        "/api/bots/sender-01/commands",
        json={"command": "preview_send_targets", "payload": {"year": 2025, "size": 20}},
    )
    assert queued.status_code == 200
    queued_payload = queued.json()
    assert queued_payload["bot_id"] == "sender-01"
    assert queued_payload["status"] == "pending"

    polled = client.get("/api/agents/pc-01/commands/poll")
    assert polled.status_code == 200
    commands = polled.json()["commands"]
    assert len(commands) == 1
    assert commands[0]["command"] == "preview_send_targets"
    assert '"year": 2025' in commands[0]["payload_json"]


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


def test_dashboard_can_queue_rate_based_bookkeeping_command(tmp_path):
    client = build_client(tmp_path)

    response = client.post(
        "/ui/bots/sender-01/rate-based-bookkeeping-send",
        data={"tax_doc_id": "1348568"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    polled = client.get("/api/agents/pc-01/commands/poll")
    assert polled.status_code == 200
    commands = polled.json()["commands"]
    assert len(commands) == 1
    assert commands[0]["command"] == "send_rate_based_bookkeeping_expected_tax_amount"
    assert '"tax_doc_id": 1348568' in commands[0]["payload_json"]


def test_dashboard_can_queue_send_expected_tax_amounts_from_taxdoc_id_list(tmp_path):
    client = build_client(tmp_path)

    response = client.post(
        "/ui/bots/sender-01/send-expected-tax-amounts-list",
        data={"tax_doc_ids": "1360165, 1360166\n1360165 1360167"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    polled = client.get("/api/agents/pc-01/commands/poll")
    assert polled.status_code == 200
    commands = polled.json()["commands"]
    assert len(commands) == 1
    assert commands[0]["command"] == "send_expected_tax_amounts"
    assert '"tax_doc_ids": [1360165, 1360166, 1360167]' in commands[0]["payload_json"]


def test_dashboard_rejects_invalid_taxdoc_id_list(tmp_path):
    client = build_client(tmp_path)

    response = client.post(
        "/ui/bots/sender-01/send-expected-tax-amounts-list",
        data={"tax_doc_ids": "1360165,abc"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "invalid tax_doc_id" in response.text


def test_dashboard_rejects_non_positive_taxdoc_id_list(tmp_path):
    client = build_client(tmp_path)

    for raw_value in ("0", "-1", "1.2"):
        response = client.post(
            "/ui/bots/sender-01/send-expected-tax-amounts-list",
            data={"tax_doc_ids": raw_value},
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert "invalid tax_doc_id" in response.text


def test_dashboard_rejects_too_many_taxdoc_ids(tmp_path):
    client = build_client(tmp_path)

    many_ids = ",".join(str(1000000 + i) for i in range(501))
    response = client.post(
        "/ui/bots/sender-01/send-expected-tax-amounts-list",
        data={"tax_doc_ids": many_ids},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "exceeds max 500" in response.text


def test_dashboard_rejects_empty_taxdoc_id_list(tmp_path):
    client = build_client(tmp_path)

    response = client.post(
        "/ui/bots/sender-01/send-expected-tax-amounts-list",
        data={"tax_doc_ids": "   "},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "tax_doc_ids is required" in response.text


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
