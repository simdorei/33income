import json

from income33.agent.runner import MockAgentRunner
from income33.config import AgentConfig


class FakeClient:
    def __init__(self, commands=None):
        self.commands = commands or []
        self.heartbeats = []
        self.completed = []

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


def build_runner(commands=None):
    agent = AgentConfig(
        pc_id="pc-01",
        hostname="WIN-PC-01",
        ip_address="127.0.0.1",
        control_tower_url="http://127.0.0.1:8330",
        bot_id="sender-01",
        bot_type="sender",
        heartbeat_interval_seconds=30,
    )
    client = FakeClient(commands=commands)
    return MockAgentRunner(agent=agent, client=client), client


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


def test_non_running_statuses_do_not_advance_steps():
    runner, _ = build_runner()
    runner.bot.status = "login_opened"

    first = runner.bot.tick()
    second = runner.bot.tick()

    assert first.status == "login_opened"
    assert first.current_step == "login_opened"
    assert second.current_step == "login_opened"
