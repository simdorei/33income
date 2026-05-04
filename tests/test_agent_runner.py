import json
import logging

from income33.agent.runner import AgentRunner, _check_initial_control_tower_connection
from income33.config import AgentConfig
from income33.control_tower.service import (
    reporter_only_commands,
    sender_only_commands,
    should_cancel_repeated_send_before_command,
)


class FakeClient:
    def __init__(self, commands=None):
        self.commands = commands or []
        self.heartbeats = []
        self.completed = []

    def health_check(self):
        return {"status": "ok"}

    def send_heartbeat(self, payload):
        self.heartbeats.append(payload)
        return {"accepted": True}

    def poll_commands(self, pc_id, limit=5):
        assert pc_id == "pc-01"
        commands = self.commands
        self.commands = []
        return commands

    def complete_command(self, command_id, status="done", error_message=None):
        self.completed.append(
            {"command_id": command_id, "status": status, "error_message": error_message}
        )
        return self.completed[-1]


def build_runner(commands=None, monotonic_fn=None, bot_id="sender-01", bot_type="sender"):
    agent = AgentConfig(
        pc_id="pc-01",
        hostname="WIN-PC-01",
        ip_address="127.0.0.1",
        control_tower_url="http://127.0.0.1:8330",
        bot_id=bot_id,
        bot_type=bot_type,
        heartbeat_interval_seconds=30,
    )
    client = FakeClient(commands=commands)
    return AgentRunner(agent=agent, client=client, monotonic_fn=monotonic_fn), client


def test_initial_control_tower_health_failure_does_not_abort_agent_startup(caplog):
    class FailingHealthClient:
        def health_check(self):
            raise RuntimeError("tower unavailable")

    ok = _check_initial_control_tower_connection(
        client=FailingHealthClient(),
        logger=logging.getLogger("test.agent.startup"),
        tower_url="http://127.0.0.1:8330",
    )

    assert ok is False
    assert "AGENT INITIAL CONNECT FAILED" in caplog.text
    assert "agent will keep retrying" in caplog.text


def stub_repeat_force_refresh(monkeypatch):
    calls = []

    def fake_refresh_page(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        return {"status": "session_active", "current_step": "session_refresh", "force": True}

    monkeypatch.setattr("income33.agent.runner.refresh_page", fake_refresh_page)
    return calls


def test_runner_heartbeat_includes_repo_version_info(monkeypatch):
    monkeypatch.setattr(
        "income33.agent.runner.collect_repo_version_info",
        lambda: {
            "repo_path": "C:\\33income",
            "repo_is_git": True,
            "git_head": "abcdef1234567890",
            "git_head_short": "abcdef1",
            "git_branch": "main",
            "git_origin_main": "abcdef1234567890",
            "git_up_to_date": True,
            "git_dirty": False,
            "version_status": "ok",
        },
    )
    runner, client = build_runner()

    runner.run_once()

    heartbeat = client.heartbeats[-1]
    assert heartbeat["agent_version"] == "0.1.0"
    assert heartbeat["repo_path"] == "C:\\33income"
    assert heartbeat["repo_is_git"] is True
    assert heartbeat["git_head_short"] == "abcdef1"
    assert heartbeat["git_up_to_date"] is True
    assert heartbeat["git_dirty"] is False
    assert heartbeat["version_status"] == "ok"


def test_runner_handles_open_login_command(monkeypatch, tmp_path):
    calls = []

    def fake_open_login_window(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        return {"dry_run": True, "profile_dir": str(tmp_path / bot_id)}

    monkeypatch.setattr("income33.agent.runner.open_login_window", fake_open_login_window)
    runner, client = build_runner(
        [
            {
                "id": 7,
                "command": "open_login",
                "payload_json": json.dumps({"login_url": "https://login.example"}),
            }
        ]
    )

    runner.run_once()

    assert calls == [{"bot_id": "sender-01", "payload": {"login_url": "https://login.example"}}]
    assert client.completed == [{"command_id": 7, "status": "done", "error_message": None}]
    assert runner.bot.status == "login_opened"


def test_runner_handles_fill_login_command(monkeypatch):
    calls = []

    def fake_fill_login(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        return {"status": "login_auth_required", "current_step": "login_auth_required"}

    monkeypatch.setattr("income33.agent.runner.fill_login", fake_fill_login)
    runner, client = build_runner(
        [{"id": 10, "command": "fill_login", "payload_json": json.dumps({"dry_run": True})}]
    )

    runner.run_once()

    assert calls == [{"bot_id": "sender-01", "payload": {"dry_run": True}}]
    assert client.completed == [{"command_id": 10, "status": "done", "error_message": None}]
    assert runner.bot.status == "login_auth_required"
    assert client.heartbeats[-1]["bot_status"] == "login_auth_required"
    assert client.heartbeats[-1]["current_step"] == "login_auth_required"


def test_runner_probes_browser_login_state_before_heartbeat(monkeypatch):
    calls = []

    def fake_inspect_login_state(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        return {"status": "login_auth_required", "current_step": "인증코드 입력 대기"}

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", fake_inspect_login_state)
    runner, client = build_runner()
    runner.bot.status = "login_opened"

    runner.run_once()

    assert calls == [{"bot_id": "sender-01", "payload": {}}]
    assert client.heartbeats[0]["bot_status"] == "login_auth_required"
    assert client.heartbeats[0]["current_step"] == "인증코드 입력 대기"


def test_runner_handles_submit_auth_code_command(monkeypatch):
    calls = []

    def fake_submit_auth_code(*, bot_id, auth_code, payload, logger):
        calls.append({"bot_id": bot_id, "auth_code": auth_code, "payload": payload})
        return {"status": "session_active", "current_step": "session_active"}

    monkeypatch.setattr("income33.agent.runner.submit_auth_code", fake_submit_auth_code)
    runner, client = build_runner(
        [
            {
                "id": 11,
                "command": "submit_auth_code",
                "payload_json": json.dumps({"auth_code": "987654"}),
            }
        ]
    )

    runner.run_once()

    assert calls == [
        {
            "bot_id": "sender-01",
            "auth_code": "987654",
            "payload": {"auth_code": "987654"},
        }
    ]
    assert client.completed == [{"command_id": 11, "status": "done", "error_message": None}]
    assert runner.bot.status == "session_active"


def test_runner_handles_preview_send_targets_command(monkeypatch):
    calls = []

    def fake_preview_expected_tax_send_targets(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        return {
            "status": "session_active",
            "current_step": "목록조회 테스트 20/274건 현재 1/14페이지 총 14페이지 officeId=325",
        }

    monkeypatch.setattr(
        "income33.agent.runner.preview_expected_tax_send_targets",
        fake_preview_expected_tax_send_targets,
    )
    runner, client = build_runner(
        [
            {
                "id": 12,
                "command": "preview_send_targets",
                "payload_json": json.dumps({"year": 2025, "size": 20}),
            }
        ]
    )

    runner.run_once()

    assert calls == [{"bot_id": "sender-01", "payload": {"year": 2025, "size": 20}}]
    assert client.completed == [{"command_id": 12, "status": "done", "error_message": None}]
    assert runner.bot.status == "session_active"
    assert client.heartbeats[-1]["current_step"] == "목록조회 테스트 20/274건 현재 1/14페이지 총 14페이지 officeId=325"


def test_runner_handles_send_expected_tax_amounts_command(monkeypatch):
    calls = []

    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        return {
            "status": "session_active",
            "current_step": "계산발송 완료 9건 status=200",
        }

    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    refresh_calls = stub_repeat_force_refresh(monkeypatch)
    runner, client = build_runner(
        [
            {
                "id": 14,
                "command": "send_expected_tax_amounts",
                "payload_json": json.dumps({"tax_doc_ids": [1360165, 1360211]}),
            }
        ]
    )

    runner.run_once()

    assert calls == [{"bot_id": "sender-01", "payload": {"tax_doc_ids": [1360165, 1360211]}}]
    assert client.completed == [{"command_id": 14, "status": "done", "error_message": None}]
    assert runner.bot.status == "session_active"
    assert client.heartbeats[-1]["current_step"] == "계산발송 완료 9건 status=200"


def test_runner_handles_send_simple_expense_rate_expected_tax_amounts_command(monkeypatch):
    calls = []

    def fake_send_simple_expense_rate_expected_tax_amounts(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        assert client.heartbeats[-1]["current_step"] == "단순경비율 목록발송 중"
        return {
            "status": "session_active",
            "current_step": "단순경비율 목록발송 완료 발송=2건 실패=0건",
        }

    monkeypatch.setattr(
        "income33.agent.runner.send_simple_expense_rate_expected_tax_amounts",
        fake_send_simple_expense_rate_expected_tax_amounts,
    )
    runner, client = build_runner(
        [
            {
                "id": 141,
                "command": "send_simple_expense_rate_expected_tax_amounts",
                "payload_json": json.dumps({}),
            }
        ]
    )

    runner.run_once()

    assert calls == [{"bot_id": "sender-01", "payload": {}}]
    assert client.completed == [{"command_id": 141, "status": "done", "error_message": None}]
    assert runner.bot.status == "session_active"
    assert client.heartbeats[-1]["current_step"] == "단순경비율 목록발송 완료 발송=2건 실패=0건"


def test_runner_fails_send_command_when_payload_json_is_invalid_json(monkeypatch):
    calls = []

    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        return {"status": "session_active", "current_step": "계산발송 완료"}

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", lambda **kwargs: None)
    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    runner, client = build_runner(
        [{"id": 141, "command": "send_expected_tax_amounts", "payload_json": '{"tax_doc_ids":[1,2]'}]
    )

    runner.run_once()

    assert calls == []
    assert client.completed == [
        {
            "command_id": 141,
            "status": "failed",
            "error_message": "payload_json must be valid JSON",
        }
    ]
    assert client.heartbeats[-1]["bot_status"] == "manual_required"
    assert client.heartbeats[-1]["current_step"] == "계산발송 실패: payload_json must be valid JSON"


def test_runner_rejects_sender_only_command_on_reporter(monkeypatch):
    monkeypatch.setattr("income33.agent.runner.inspect_login_state", lambda **kwargs: None)
    runner, client = build_runner(
        [{"id": 99, "command": "send_expected_tax_amounts", "payload_json": "{}"}],
        bot_id="reporter-01",
        bot_type="reporter",
    )

    runner.run_once()

    assert client.completed == [{"command_id": 99, "status": "failed", "error_message": "SENDER_ONLY_COMMAND: send_expected_tax_amounts"}]
    assert client.heartbeats[-1]["bot_status"] == "manual_required"
    assert "SENDER_ONLY_COMMAND" in client.heartbeats[-1]["current_step"]


def test_runner_sender_only_guard_uses_control_tower_policy_set():
    expected = {
        "send_expected_tax_amounts",
        "send_simple_expense_rate_expected_tax_amounts",
        "send_bookkeeping_expected_tax_amount",
        "send_rate_based_bookkeeping_expected_tax_amount",
        "preview_rate_based_bookkeeping_expected_tax_amounts",
        "send_rate_based_bookkeeping_expected_tax_amounts",
    }
    assert sender_only_commands() == expected


def test_runner_handles_submit_tax_reports_command_on_reporter(monkeypatch):
    calls = []

    def fake_submit_tax_reports(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        assert client.heartbeats[-1]["current_step"] == "국세신고 응답수집 중"
        return {
            "status": "manual_required",
            "current_step": "국세신고 응답수집 완료 성공=1건 실패=1건 로그=tax_report_submit_responses.jsonl",
        }

    monkeypatch.setattr("income33.agent.runner.submit_tax_reports", fake_submit_tax_reports)
    runner, client = build_runner(
        [
            {
                "id": 31,
                "command": "submit_tax_reports",
                "payload_json": json.dumps({"tax_doc_ids": [1001, 1002]}),
            }
        ],
        bot_id="reporter-01",
        bot_type="reporter",
    )

    runner.run_once()

    assert calls == [{"bot_id": "reporter-01", "payload": {"tax_doc_ids": [1001, 1002]}}]
    assert client.completed == [{"command_id": 31, "status": "done", "error_message": None}]
    assert runner.bot.status == "manual_required"
    assert client.heartbeats[-1]["current_step"] == "국세신고 응답수집 완료 성공=1건 실패=1건 로그=tax_report_submit_responses.jsonl"


def test_runner_schedules_reporter_one_click_none_submit_repeat_and_requeries_after_five_minutes(monkeypatch):
    monotonic_points = iter([1000.0, 1299.0, 1299.0, 1300.0, 1300.0])
    calls = []

    def fake_monotonic():
        return next(monotonic_points)

    def fake_submit_tax_reports(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        if len(calls) == 2:
            assert client.heartbeats[-1]["current_step"] == "국세신고 반복 중"
        return {
            "status": "session_active",
            "current_step": f"신고제출 대상 없음 #{len(calls)}",
            "attempted_count": 0,
            "tax_doc_ids": [],
        }

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", lambda **kwargs: None)
    monkeypatch.setattr("income33.agent.runner.submit_tax_reports", fake_submit_tax_reports)
    runner, client = build_runner(
        [
            {
                "id": 310,
                "command": "submit_tax_reports",
                "payload_json": json.dumps(
                    {
                        "tax_doc_ids": [],
                        "one_click_submit": True,
                        "tax_doc_custom_type_filter": "NONE",
                        "taxDocCustomTypeFilter": "NONE",
                        "max_auto_targets": 0,
                        "maxAutoTargets": 0,
                        "repeat": True,
                        "_retry": {"interval_sec": 300},
                    }
                ),
            }
        ],
        bot_id="reporter-01",
        bot_type="reporter",
        monotonic_fn=fake_monotonic,
    )

    runner.run_once()
    assert client.heartbeats[-1]["current_step"] == "신고제출 대상 없음 #1 / 다음신고 300초 후"
    runner.run_once()
    assert client.heartbeats[-1]["current_step"] == "신고제출 대상 없음 #1 / 다음신고 1초 후"
    runner.run_once()

    expected_repeat_payload = {
        "tax_doc_ids": [],
        "one_click_submit": True,
        "oneClickSubmit": True,
        "tax_doc_custom_type_filter": "NONE",
        "taxDocCustomTypeFilter": "NONE",
        "max_auto_targets": 0,
        "maxAutoTargets": 0,
        "repeat": True,
        "_retry": {"interval_sec": 300},
    }
    assert calls == [
        {"bot_id": "reporter-01", "payload": expected_repeat_payload},
        {"bot_id": "reporter-01", "payload": expected_repeat_payload},
    ]
    assert client.completed == [{"command_id": 310, "status": "done", "error_message": None}]
    assert client.heartbeats[-1]["current_step"] == "신고제출 대상 없음 #2 / 다음신고 300초 후"
    assert runner._repeat_send_payload is None


def test_runner_cancels_reporter_submit_repeat_when_operator_queues_control_command(monkeypatch):
    monotonic_points = iter([1000.0, 1300.0])
    calls = []

    def fake_monotonic():
        return next(monotonic_points)

    def fake_submit_tax_reports(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        return {"status": "session_active", "current_step": "신고제출 대상 없음", "attempted_count": 0, "tax_doc_ids": []}

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", lambda **kwargs: None)
    monkeypatch.setattr("income33.agent.runner.submit_tax_reports", fake_submit_tax_reports)
    runner, client = build_runner(
        [
            {
                "id": 311,
                "command": "submit_tax_reports",
                "payload_json": json.dumps(
                    {
                        "tax_doc_ids": [],
                        "one_click_submit": True,
                        "tax_doc_custom_type_filter": "NONE",
                        "max_auto_targets": 0,
                        "repeat": True,
                        "_retry": {"interval_sec": 300},
                    }
                ),
            }
        ],
        bot_id="reporter-01",
        bot_type="reporter",
        monotonic_fn=fake_monotonic,
    )

    runner.run_once()
    client.commands = [{"id": 312, "command": "stop", "payload_json": "{}"}]
    runner.run_once()
    runner.run_once()

    assert calls == [
        {
            "bot_id": "reporter-01",
            "payload": {
                "tax_doc_ids": [],
                "one_click_submit": True,
                "oneClickSubmit": True,
                "tax_doc_custom_type_filter": "NONE",
                "taxDocCustomTypeFilter": "NONE",
                "max_auto_targets": 0,
                "maxAutoTargets": 0,
                "repeat": True,
                "_retry": {"interval_sec": 300},
            },
        }
    ]
    assert client.completed == [
        {"command_id": 311, "status": "done", "error_message": None},
        {"command_id": 312, "status": "done", "error_message": None},
    ]


def test_runner_rejects_reporter_only_command_on_sender(monkeypatch):
    runner, client = build_runner(
        [{"id": 32, "command": "submit_tax_reports", "payload_json": json.dumps({"tax_doc_ids": [1001]})}],
        bot_id="sender-01",
        bot_type="sender",
    )

    runner.run_once()

    assert client.completed == [{"command_id": 32, "status": "failed", "error_message": "REPORTER_ONLY_COMMAND: submit_tax_reports"}]
    assert client.heartbeats[-1]["bot_status"] == "manual_required"
    assert "REPORTER_ONLY_COMMAND" in client.heartbeats[-1]["current_step"]


def test_runner_reporter_only_guard_uses_control_tower_policy_set():
    assert reporter_only_commands() == {"submit_tax_reports"}


def test_runner_repeat_cancel_guard_uses_control_tower_policy_set():
    assert should_cancel_repeated_send_before_command("status") is False
    assert should_cancel_repeated_send_before_command("send_expected_tax_amounts") is False
    assert should_cancel_repeated_send_before_command("stop") is True


def test_runner_handles_send_bookkeeping_expected_tax_amount_command(monkeypatch):
    calls = []

    def fake_send_bookkeeping_expected_tax_amount(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        assert client.heartbeats[-1]["current_step"] == "단건 계산발송 중"
        return {
            "status": "session_active",
            "current_step": "단건 계산발송 완료 taxDocId=1345836 추가경비=27543987 예상세액=-621639 지방세=-62164 수수료=185000 status=200",
        }

    monkeypatch.setattr(
        "income33.agent.runner.send_bookkeeping_expected_tax_amount",
        fake_send_bookkeeping_expected_tax_amount,
    )
    runner, client = build_runner(
        [
            {
                "id": 25,
                "command": "send_bookkeeping_expected_tax_amount",
                "payload_json": json.dumps(
                    {
                        "tax_doc_id": 1345836,
                        "submit_account_type": "CUSTOMER",
                        "total_business_expense_amount": 41538144,
                    }
                ),
            }
        ]
    )

    runner.run_once()

    assert calls == [
        {
            "bot_id": "sender-01",
            "payload": {
                "tax_doc_id": 1345836,
                "submit_account_type": "CUSTOMER",
                "total_business_expense_amount": 41538144,
            },
        }
    ]
    assert client.completed == [{"command_id": 25, "status": "done", "error_message": None}]
    assert runner.bot.status == "session_active"
    assert client.heartbeats[-1]["current_step"] == "단건 계산발송 완료 taxDocId=1345836 추가경비=27543987 예상세액=-621639 지방세=-62164 수수료=185000 status=200"


def test_runner_handles_send_rate_based_bookkeeping_expected_tax_amount_command(monkeypatch):
    calls = []

    def fake_send_rate_based_bookkeeping_expected_tax_amounts(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        assert client.heartbeats[-1]["current_step"] == "경비율 장부 계산발송 중"
        return {
            "status": "session_active",
            "current_step": "일괄 경비율 장부발송 완료 발송=0건 패스=1건 실패=0건",
            "skipped_count": 1,
        }

    monkeypatch.setattr(
        "income33.agent.runner.send_rate_based_bookkeeping_expected_tax_amounts",
        fake_send_rate_based_bookkeeping_expected_tax_amounts,
    )
    runner, client = build_runner(
        [
            {
                "id": 26,
                "command": "send_rate_based_bookkeeping_expected_tax_amount",
                "payload_json": json.dumps({"tax_doc_id": 1348568}),
            }
        ]
    )

    runner.run_once()

    assert calls == [{"bot_id": "sender-01", "payload": {"tax_doc_id": 1348568, "tax_doc_ids": [1348568]}}]
    assert client.completed == [{"command_id": 26, "status": "done", "error_message": None}]
    assert runner.bot.status == "session_active"
    assert client.heartbeats[-1]["current_step"] == "일괄 경비율 장부발송 완료 발송=0건 패스=1건 실패=0건"


def test_runner_handles_bulk_rate_based_bookkeeping_commands(monkeypatch):
    calls = []

    def fake_preview_rate_based_bookkeeping_expected_tax_amounts(*, bot_id, payload, logger):
        calls.append({"command": "preview", "bot_id": bot_id, "payload": payload})
        assert client.heartbeats[-1]["current_step"] == "일괄세션 확인 중"
        return {"status": "session_active", "current_step": "일괄세션 확인 2건"}

    def fake_send_rate_based_bookkeeping_expected_tax_amounts(*, bot_id, payload, logger):
        calls.append({"command": "send", "bot_id": bot_id, "payload": payload})
        assert client.heartbeats[-1]["current_step"] == "일괄 경비율 장부발송 중"
        return {"status": "session_active", "current_step": "일괄 경비율 장부발송 완료 발송=1건 패스=1건 실패=0건"}

    monkeypatch.setattr(
        "income33.agent.runner.preview_rate_based_bookkeeping_expected_tax_amounts",
        fake_preview_rate_based_bookkeeping_expected_tax_amounts,
    )
    monkeypatch.setattr(
        "income33.agent.runner.send_rate_based_bookkeeping_expected_tax_amounts",
        fake_send_rate_based_bookkeeping_expected_tax_amounts,
    )
    runner, client = build_runner(
        [
            {
                "id": 27,
                "command": "preview_rate_based_bookkeeping_expected_tax_amounts",
                "payload_json": json.dumps({"year": 2025, "size": 20}),
            },
            {
                "id": 28,
                "command": "send_rate_based_bookkeeping_expected_tax_amounts",
                "payload_json": json.dumps({"year": 2025, "size": 20}),
            },
        ]
    )

    runner.run_once()

    assert calls == [
        {"command": "preview", "bot_id": "sender-01", "payload": {"year": 2025, "size": 20}},
        {"command": "send", "bot_id": "sender-01", "payload": {"year": 2025, "size": 20}},
    ]
    assert client.completed == [
        {"command_id": 27, "status": "done", "error_message": None},
        {"command_id": 28, "status": "done", "error_message": None},
    ]
    assert client.heartbeats[-1]["current_step"] == "일괄 경비율 장부발송 완료 발송=1건 패스=1건 실패=0건"


def test_runner_reports_send_in_progress_before_blocking_send(monkeypatch):
    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        assert client.heartbeats[-1]["bot_status"] == "session_active"
        assert client.heartbeats[-1]["current_step"] == "계산발송 중"
        return {"status": "session_active", "current_step": "계산발송 완료"}

    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    refresh_calls = stub_repeat_force_refresh(monkeypatch)
    runner, client = build_runner(
        [{"id": 19, "command": "send_expected_tax_amounts", "payload_json": "{}"}]
    )

    runner.run_once()

    assert client.heartbeats[-1]["current_step"] == "계산발송 완료 / 다음발송 300초 후"


def test_runner_uses_retry_policy_interval_and_max_attempts_from_payload(monkeypatch):
    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        return {"status": "session_active", "current_step": "계산발송 완료", "tax_doc_ids": [1360165]}

    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    refresh_calls = stub_repeat_force_refresh(monkeypatch)
    runner, client = build_runner(
        [
            {
                "id": 119,
                "command": "send_expected_tax_amounts",
                "payload_json": json.dumps({"year": 2025, "_retry": {"interval_sec": 120, "max_attempts": 5}}),
            }
        ]
    )

    runner.run_once()

    assert client.heartbeats[-1]["current_step"] == "계산발송 완료 / 다음발송 120초 후"
    assert runner._repeat_send_payload["_repeat_interval_sec"] == 120
    assert runner._repeat_send_payload["_repeat_max_attempts"] == 5


def test_runner_reports_failure_step_when_send_command_fails(monkeypatch):
    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        raise RuntimeError("send api failed")

    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    refresh_calls = stub_repeat_force_refresh(monkeypatch)
    runner, client = build_runner(
        [{"id": 20, "command": "send_expected_tax_amounts", "payload_json": "{}"}]
    )

    runner.run_once()

    assert client.completed == [
        {"command_id": 20, "status": "failed", "error_message": "send api failed"}
    ]
    assert client.heartbeats[-1]["bot_status"] == "manual_required"
    assert client.heartbeats[-1]["current_step"] == "계산발송 실패: send api failed"


def test_runner_does_not_repeat_explicit_tax_doc_ids_without_repeat_opt_in(monkeypatch):
    monotonic_points = iter([1000.0])
    calls = []

    def fake_monotonic():
        return next(monotonic_points)

    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        return {"status": "session_active", "current_step": "계산발송 완료"}

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", lambda **kwargs: None)
    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    refresh_calls = stub_repeat_force_refresh(monkeypatch)
    runner, _ = build_runner(
        [
            {
                "id": 18,
                "command": "send_expected_tax_amounts",
                "payload_json": json.dumps({"tax_doc_ids": [1360165]}),
            }
        ],
        monotonic_fn=fake_monotonic,
    )

    runner.run_once()
    runner.run_once()

    assert calls == [{"bot_id": "sender-01", "payload": {"tax_doc_ids": [1360165]}}]


def test_runner_normalizes_tax_doc_ids_before_send(monkeypatch):
    calls = []

    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        return {"status": "session_active", "current_step": "계산발송 완료"}

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", lambda **kwargs: None)
    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    runner, _ = build_runner(
        [
            {
                "id": 181,
                "command": "send_expected_tax_amounts",
                "payload_json": json.dumps({"tax_doc_ids": [1360165, "1360165", 0, -7, True, "1360211", "bad"]}),
            }
        ]
    )

    runner.run_once()

    assert calls == [{"bot_id": "sender-01", "payload": {"tax_doc_ids": [1360165, 1360211]}}]


def test_runner_repeat_with_explicit_tax_doc_ids_skips_fallback_assignment_loop(monkeypatch):
    monotonic_points = iter([1000.0, 1300.0, 1300.0])
    send_calls = []
    assign_calls = []

    def fake_monotonic():
        return next(monotonic_points)

    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        send_calls.append({"bot_id": bot_id, "payload": payload})
        return {
            "status": "session_active",
            "current_step": f"계산발송 완료 #{len(send_calls)}",
            "tax_doc_ids": [555, 556],
        }

    def fake_assign_taxdocs_to_current_accountant(*, bot_id, tax_doc_ids, payload, logger):
        assign_calls.append({"bot_id": bot_id, "tax_doc_ids": tax_doc_ids, "payload": payload})
        return {"status": "session_active", "current_step": "잔여목록 배정 완료 2건 담당자=817 status=200"}

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", lambda **kwargs: None)
    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    stub_repeat_force_refresh(monkeypatch)
    monkeypatch.setattr(
        "income33.agent.runner.assign_taxdocs_to_current_accountant",
        fake_assign_taxdocs_to_current_accountant,
    )
    runner, _ = build_runner(
        [
            {
                "id": 182,
                "command": "send_expected_tax_amounts",
                "payload_json": json.dumps(
                    {
                        "tax_doc_ids": [555, "555", -1, True, "556", "bad"],
                        "repeat": True,
                        "_retry": {"interval_sec": 300, "max_attempts": 2},
                    }
                ),
            }
        ],
        monotonic_fn=fake_monotonic,
    )

    runner.run_once()
    runner.run_once()

    assert len(send_calls) == 2
    assert send_calls == [
        {
            "bot_id": "sender-01",
            "payload": {
                "tax_doc_ids": [555, 556],
                "repeat": True,
                "_retry": {"interval_sec": 300, "max_attempts": 2},
            },
        },
        {
            "bot_id": "sender-01",
            "payload": {
                "tax_doc_ids": [555, 556],
                "repeat": True,
                "_retry": {"interval_sec": 300, "max_attempts": 2},
            },
        },
    ]
    assert assign_calls == []


def test_runner_repeat_send_failure_keeps_retry_scheduled_until_stop(monkeypatch):
    monotonic_points = iter([1000.0, 1300.0, 1300.0, 1600.0, 1600.0])
    refresh_calls = []
    send_calls = []

    def fake_monotonic():
        return next(monotonic_points)

    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        send_calls.append({"bot_id": bot_id, "payload": payload})
        if len(send_calls) == 2:
            raise RuntimeError("send api failed")
        return {"status": "session_active", "current_step": f"계산발송 완료 #{len(send_calls)}"}

    def fake_refresh_page(*, bot_id, payload, logger):
        refresh_calls.append({"bot_id": bot_id, "payload": payload})
        return {"status": "session_active", "current_step": "session_refresh"}

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", lambda **kwargs: None)
    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    monkeypatch.setattr("income33.agent.runner.refresh_page", fake_refresh_page)
    runner, client = build_runner(
        [
            {
                "id": 184,
                "command": "send_expected_tax_amounts",
                "payload_json": json.dumps({"year": 2025, "repeat": True, "_retry": {"interval_sec": 300}}),
            }
        ],
        monotonic_fn=fake_monotonic,
    )

    runner.run_once()  # initial send success + repeat schedule
    runner.run_once()  # repeated send fails but schedule must remain
    runner.run_once()  # next interval retries again

    assert len(send_calls) == 3
    assert len(refresh_calls) == 2
    assert client.heartbeats[-1]["bot_status"] == "session_active"
    assert "다음발송" in client.heartbeats[-1]["current_step"]
    assert any("계산발송 실패(1회): send api failed / 다음발송 300초 후" in hb["current_step"] for hb in client.heartbeats)
    assert runner._repeat_send_payload is not None
    assert runner._next_repeated_send_monotonic is not None


def test_runner_repeats_send_after_five_idle_minutes(monkeypatch):
    monotonic_points = iter([1000.0, 1299.0, 1299.0, 1300.0, 1300.0])
    calls = []

    def fake_monotonic():
        return next(monotonic_points)

    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        if len(calls) == 2:
            assert client.heartbeats[-1]["current_step"] == "계산발송 반복 중"
        return {
            "status": "session_active",
            "current_step": f"계산발송 완료 #{len(calls)}",
        }

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", lambda **kwargs: None)
    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    refresh_calls = stub_repeat_force_refresh(monkeypatch)
    runner, client = build_runner(
        [
            {
                "id": 15,
                "command": "send_expected_tax_amounts",
                "payload_json": json.dumps({"year": 2025, "size": 20}),
            }
        ],
        monotonic_fn=fake_monotonic,
    )

    runner.run_once()
    assert client.heartbeats[-1]["current_step"] == "계산발송 완료 #1 / 다음발송 300초 후"
    runner.run_once()
    assert client.heartbeats[-1]["current_step"] == "계산발송 완료 #1 / 다음발송 1초 후"
    runner.run_once()

    assert calls == [
        {"bot_id": "sender-01", "payload": {"year": 2025, "size": 20}},
        {"bot_id": "sender-01", "payload": {"year": 2025, "size": 20}},
    ]
    assert client.completed == [{"command_id": 15, "status": "done", "error_message": None}]
    assert refresh_calls == [{"bot_id": "sender-01", "payload": {"year": 2025, "size": 20, "force": True}}]
    assert client.heartbeats[-1]["current_step"] == "계산발송 완료 #2 / 다음발송 300초 후"


def test_runner_ignores_false_auth_probe_while_repeat_send_is_scheduled(monkeypatch):
    monotonic_points = iter([1000.0, 1299.0, 1299.0, 1300.0, 1300.0])
    calls = []

    def fake_monotonic():
        return next(monotonic_points)

    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        return {
            "status": "session_active",
            "current_step": f"계산발송 완료 #{len(calls)}",
        }

    def fake_inspect_login_state(*, bot_id, payload, logger):
        return {"status": "login_auth_required", "current_step": "인증코드 입력 대기"}

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", fake_inspect_login_state)
    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    refresh_calls = stub_repeat_force_refresh(monkeypatch)
    runner, client = build_runner(
        [
            {
                "id": 24,
                "command": "send_expected_tax_amounts",
                "payload_json": json.dumps({"year": 2025, "size": 20}),
            }
        ],
        monotonic_fn=fake_monotonic,
    )

    runner.run_once()
    runner.run_once()
    assert client.heartbeats[-1]["bot_status"] == "session_active"
    assert client.heartbeats[-1]["current_step"] == "계산발송 완료 #1 / 다음발송 1초 후"
    runner.run_once()

    assert calls == [
        {"bot_id": "sender-01", "payload": {"year": 2025, "size": 20}},
        {"bot_id": "sender-01", "payload": {"year": 2025, "size": 20}},
    ]
    assert client.heartbeats[-1]["current_step"] == "계산발송 완료 #2 / 다음발송 300초 후"


def test_runner_repeat_send_continues_in_login_auth_required_state(monkeypatch):
    monotonic_points = iter([1000.0, 1300.0, 1300.0])
    send_calls = []

    def fake_monotonic():
        return next(monotonic_points)

    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        send_calls.append({"bot_id": bot_id, "payload": payload})
        return {"status": "session_active", "current_step": f"계산발송 완료 #{len(send_calls)}"}

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", lambda **kwargs: None)
    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    stub_repeat_force_refresh(monkeypatch)
    runner, _ = build_runner(
        [
            {
                "id": 185,
                "command": "send_expected_tax_amounts",
                "payload_json": json.dumps({"year": 2025, "repeat": True, "_retry": {"interval_sec": 300}}),
            }
        ],
        monotonic_fn=fake_monotonic,
    )

    runner.run_once()  # initial
    runner.bot.status = "login_auth_required"
    runner.run_once()  # due -> should still retry

    assert len(send_calls) == 2


def test_runner_repeat_fallback_does_not_assign_before_three_total_attempts(monkeypatch):
    monotonic_points = iter([1000.0, 1300.0, 1300.0])
    send_calls = []
    assign_calls = []

    def fake_monotonic():
        return next(monotonic_points)

    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        send_calls.append({"bot_id": bot_id, "payload": payload})
        return {"status": "session_active", "current_step": "계산발송 완료", "tax_doc_ids": [555]}

    def fake_assign_taxdocs_to_current_accountant(*, bot_id, tax_doc_ids, payload, logger):
        assign_calls.append({"bot_id": bot_id, "tax_doc_ids": tax_doc_ids, "payload": payload})
        return {"status": "session_active", "current_step": "잔여목록 배정 완료 1건 담당자=817 status=200"}

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", lambda **kwargs: None)
    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    refresh_calls = stub_repeat_force_refresh(monkeypatch)
    monkeypatch.setattr(
        "income33.agent.runner.assign_taxdocs_to_current_accountant",
        fake_assign_taxdocs_to_current_accountant,
    )
    runner, _ = build_runner(
        [
            {
                "id": 21,
                "command": "send_expected_tax_amounts",
                "payload_json": json.dumps({"year": 2025, "size": 20}),
            }
        ],
        monotonic_fn=fake_monotonic,
    )

    runner.run_once()
    runner.run_once()

    assert len(send_calls) == 2
    assert assign_calls == []


def test_runner_repeat_fallback_assignment_normalizes_tax_doc_ids(monkeypatch):
    monotonic_points = iter([1000.0, 1300.0, 1300.0])
    send_calls = []
    assign_calls = []

    def fake_monotonic():
        return next(monotonic_points)

    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        send_calls.append({"bot_id": bot_id, "payload": payload})
        return {
            "status": "session_active",
            "current_step": "계산발송 완료",
            "tax_doc_ids": [555, "555", 0, -1, True, "556", "556", "bad", 556],
        }

    def fake_assign_taxdocs_to_current_accountant(*, bot_id, tax_doc_ids, payload, logger):
        assign_calls.append({"bot_id": bot_id, "tax_doc_ids": tax_doc_ids, "payload": payload})
        return {"status": "session_active", "current_step": "잔여목록 배정 완료 2건 담당자=817 status=200"}

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", lambda **kwargs: None)
    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    stub_repeat_force_refresh(monkeypatch)
    monkeypatch.setattr(
        "income33.agent.runner.assign_taxdocs_to_current_accountant",
        fake_assign_taxdocs_to_current_accountant,
    )
    runner, _ = build_runner(
        [
            {
                "id": 183,
                "command": "send_expected_tax_amounts",
                "payload_json": json.dumps({"year": 2025, "_retry": {"interval_sec": 300, "max_attempts": 2}}),
            }
        ],
        monotonic_fn=fake_monotonic,
    )

    runner.run_once()
    runner.run_once()

    assert len(send_calls) == 2
    assert assign_calls == [
        {
            "bot_id": "sender-01",
            "tax_doc_ids": [555, 556],
            "payload": {"year": 2025, "_retry": {"interval_sec": 300, "max_attempts": 2}},
        }
    ]


def test_runner_repeat_fallback_assigns_once_after_three_total_attempts(monkeypatch):
    monotonic_points = iter([1000.0, 1300.0, 1300.0, 1600.0, 1600.0])
    send_calls = []
    assign_calls = []

    def fake_monotonic():
        return next(monotonic_points)

    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        send_calls.append({"bot_id": bot_id, "payload": payload})
        return {"status": "session_active", "current_step": "계산발송 완료", "tax_doc_ids": [555]}

    def fake_assign_taxdocs_to_current_accountant(*, bot_id, tax_doc_ids, payload, logger):
        assign_calls.append({"bot_id": bot_id, "tax_doc_ids": tax_doc_ids, "payload": payload})
        return {"status": "session_active", "current_step": "잔여목록 배정 완료 1건 담당자=817 status=200"}

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", lambda **kwargs: None)
    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    refresh_calls = stub_repeat_force_refresh(monkeypatch)
    monkeypatch.setattr(
        "income33.agent.runner.assign_taxdocs_to_current_accountant",
        fake_assign_taxdocs_to_current_accountant,
    )
    runner, client = build_runner(
        [
            {
                "id": 22,
                "command": "send_expected_tax_amounts",
                "payload_json": json.dumps({"year": 2025, "size": 20}),
            }
        ],
        monotonic_fn=fake_monotonic,
    )

    runner.run_once()
    runner.run_once()
    runner.run_once()

    assert len(send_calls) == 3
    assert assign_calls == [{"bot_id": "sender-01", "tax_doc_ids": [555], "payload": {"year": 2025, "size": 20}}]
    assert client.heartbeats[-1]["current_step"] == "잔여목록 배정 완료 1건 담당자=817 status=200 / 다음발송 300초 후"


def test_runner_keeps_repeating_after_leftover_assignment(monkeypatch):
    monotonic_points = iter([1000.0, 1300.0, 1300.0, 1600.0, 1600.0, 1900.0, 1900.0])
    send_calls = []
    assign_calls = []

    def fake_monotonic():
        return next(monotonic_points)

    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        send_calls.append({"bot_id": bot_id, "payload": payload})
        return {"status": "session_active", "current_step": f"계산발송 완료 #{len(send_calls)}", "tax_doc_ids": [555]}

    def fake_assign_taxdocs_to_current_accountant(*, bot_id, tax_doc_ids, payload, logger):
        assign_calls.append({"bot_id": bot_id, "tax_doc_ids": tax_doc_ids, "payload": payload})
        return {"status": "session_active", "current_step": "잔여목록 배정 완료 1건 담당자=817 status=200"}

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", lambda **kwargs: None)
    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    refresh_calls = stub_repeat_force_refresh(monkeypatch)
    monkeypatch.setattr(
        "income33.agent.runner.assign_taxdocs_to_current_accountant",
        fake_assign_taxdocs_to_current_accountant,
    )
    runner, client = build_runner(
        [
            {
                "id": 23,
                "command": "send_expected_tax_amounts",
                "payload_json": json.dumps({"year": 2025, "size": 20}),
            }
        ],
        monotonic_fn=fake_monotonic,
    )

    runner.run_once()
    runner.run_once()
    runner.run_once()
    runner.run_once()

    assert len(send_calls) == 4
    assert assign_calls == [{"bot_id": "sender-01", "tax_doc_ids": [555], "payload": {"year": 2025, "size": 20}}]
    assert client.heartbeats[-1]["current_step"] == "계산발송 완료 #4 / 다음발송 300초 후"


def test_runner_cancels_repeated_send_when_operator_queues_control_command(monkeypatch):
    monotonic_points = iter([1000.0, 1300.0])
    calls = []

    def fake_monotonic():
        return next(monotonic_points)

    def fake_send_expected_tax_amounts(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        return {"status": "session_active", "current_step": "계산발송 완료"}

    monkeypatch.setattr("income33.agent.runner.inspect_login_state", lambda **kwargs: None)
    monkeypatch.setattr("income33.agent.runner.send_expected_tax_amounts", fake_send_expected_tax_amounts)
    refresh_calls = stub_repeat_force_refresh(monkeypatch)
    runner, client = build_runner(
        [
            {"id": 16, "command": "send_expected_tax_amounts", "payload_json": "{}"},
        ],
        monotonic_fn=fake_monotonic,
    )

    runner.run_once()
    client.commands = [{"id": 17, "command": "stop", "payload_json": "{}"}]
    runner.run_once()
    runner.run_once()

    assert calls == [{"bot_id": "sender-01", "payload": {}}]
    assert client.completed == [
        {"command_id": 16, "status": "done", "error_message": None},
        {"command_id": 17, "status": "done", "error_message": None},
    ]


def test_preview_result_survives_next_idle_heartbeat(monkeypatch):
    def fake_preview_expected_tax_send_targets(*, bot_id, payload, logger):
        return {
            "status": "session_active",
            "current_step": "목록조회 테스트 20/565건 현재 1/29페이지 총 29페이지 officeId=325",
        }

    def fake_inspect_login_state(*, bot_id, payload, logger):
        return {"status": "session_active", "current_step": "session_active"}

    monkeypatch.setattr(
        "income33.agent.runner.preview_expected_tax_send_targets",
        fake_preview_expected_tax_send_targets,
    )
    monkeypatch.setattr("income33.agent.runner.inspect_login_state", fake_inspect_login_state)
    runner, client = build_runner(
        [
            {
                "id": 13,
                "command": "preview_send_targets",
                "payload_json": json.dumps({"year": 2025, "size": 20}),
            }
        ]
    )

    runner.run_once()
    runner.run_once()

    assert client.heartbeats[-1]["bot_status"] == "session_active"
    assert (
        client.heartbeats[-1]["current_step"]
        == "목록조회 테스트 20/565건 현재 1/29페이지 총 29페이지 officeId=325"
    )


def test_runner_handles_login_done_command():
    runner, client = build_runner([{"id": 8, "command": "login_done", "payload_json": "{}"}])

    runner.run_once()

    assert client.completed == [{"command_id": 8, "status": "done", "error_message": None}]
    assert runner.bot.status == "idle"


def test_runner_marks_command_failed_when_login_open_fails(monkeypatch):
    def fake_open_login_window(*, bot_id, payload, logger):
        raise RuntimeError("browser launch failed")

    monkeypatch.setattr("income33.agent.runner.open_login_window", fake_open_login_window)
    runner, client = build_runner([{"id": 9, "command": "open_login", "payload_json": "{}"}])

    runner.run_once()

    assert client.completed == [
        {"command_id": 9, "status": "failed", "error_message": "browser launch failed"}
    ]
    assert runner.bot.status == "login_required"


def test_runner_keepalive_refreshes_when_due(monkeypatch):
    monotonic_points = iter([1000.0, 1001.0])

    def fake_monotonic():
        return next(monotonic_points)

    calls = []

    def fake_refresh_page(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        return {"status": "session_active", "current_step": "session_refresh", "url": "https://x"}

    monkeypatch.setenv("INCOME33_REFRESH_ENABLED", "1")
    monkeypatch.setenv("INCOME33_REFRESH_INTERVAL_SECONDS", "600")
    monkeypatch.setattr("income33.agent.runner.refresh_page", fake_refresh_page)

    runner, client = build_runner(monotonic_fn=fake_monotonic)

    runner.run_once()

    assert calls == [{"bot_id": "sender-01", "payload": {}}]
    assert client.heartbeats[0]["bot_status"] == "session_active"
    assert client.heartbeats[0]["current_step"] == "session_refresh"


def test_runner_keepalive_refreshes_during_repeat_even_when_auth_required(monkeypatch):
    monotonic_points = iter([1000.0, 1001.0])

    def fake_monotonic():
        return next(monotonic_points)

    calls = []

    def fake_refresh_page(*, bot_id, payload, logger):
        calls.append({"bot_id": bot_id, "payload": payload})
        return {"status": "session_active", "current_step": "session_refresh", "url": "https://x"}

    monkeypatch.setenv("INCOME33_REFRESH_ENABLED", "1")
    monkeypatch.setenv("INCOME33_REFRESH_INTERVAL_SECONDS", "600")
    monkeypatch.setattr("income33.agent.runner.refresh_page", fake_refresh_page)

    runner, _ = build_runner(monotonic_fn=fake_monotonic)
    runner._repeat_send_payload = {"year": 2025}
    runner.bot.status = "login_auth_required"

    runner.run_once()

    assert calls == [{"bot_id": "sender-01", "payload": {}}]


def test_non_running_statuses_do_not_advance_steps():
    runner, _ = build_runner()
    runner.bot.status = "login_opened"

    first = runner.bot.tick()
    second = runner.bot.tick()

    assert first.status == "login_opened"
    assert first.current_step == "login_opened"
    assert second.current_step == "login_opened"
