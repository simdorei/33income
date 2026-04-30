import json

from income33.db import Database


def test_init_and_seed_mock_data(tmp_path):
    db_path = tmp_path / "33income.db"
    db = Database(str(db_path))

    db.init_db()
    db.seed_mock_data(agent_count=18)

    summary = db.get_summary()

    assert summary["total_agents"] == 18
    assert summary["total_bots"] == 18
    assert summary["online_agents"] == 0
    assert summary["offline_agents"] == 18
    assert summary["sender_bots"] == 9
    assert summary["reporter_bots"] == 9

    sender01 = db.get_bot("sender-01")
    assert sender01 is not None
    assert sender01["status"] == "connection_required"
    assert sender01["current_step"] == "접속필요"
    assert sender01["last_heartbeat_at"] is None


def test_enqueue_and_poll_commands(tmp_path):
    db_path = tmp_path / "33income.db"
    db = Database(str(db_path))
    db.init_db()
    db.seed_mock_data(agent_count=18)

    command = db.enqueue_command(pc_id="pc-01", bot_id="sender-01", command="open_login")

    assert command["status"] == "pending"

    bot = db.get_bot("sender-01")
    assert bot is not None
    assert bot["status"] == "login_required"
    assert bot["current_step"] == "login_required"

    polled = db.poll_commands(pc_id="pc-01", limit=5)
    assert len(polled) == 1
    assert polled[0]["id"] == command["id"]
    assert polled[0]["status"] == "running"

    done = db.complete_command(command_id=command["id"], status="done")
    assert done["status"] == "done"

    bot = db.get_bot("sender-01")
    assert bot is not None
    assert bot["status"] == "login_opened"
    assert bot["current_step"] == "login_opened"


def test_db_status_mapping_for_new_login_and_refresh_commands(tmp_path):
    db_path = tmp_path / "33income.db"
    db = Database(str(db_path))
    db.init_db()
    db.seed_mock_data(agent_count=18)

    fill = db.enqueue_command(pc_id="pc-01", bot_id="sender-01", command="fill_login")
    bot = db.get_bot("sender-01")
    assert bot is not None
    assert bot["status"] == "login_filling"
    assert bot["current_step"] == "login_filling"
    db.complete_command(command_id=fill["id"], status="done")
    bot = db.get_bot("sender-01")
    assert bot is not None
    assert bot["status"] == "login_auth_required"
    assert bot["current_step"] == "login_auth_required"

    auth = db.enqueue_command(
        pc_id="pc-01",
        bot_id="sender-01",
        command="submit_auth_code",
        payload={"auth_code": "123456"},
    )
    bot = db.get_bot("sender-01")
    assert bot is not None
    assert bot["status"] == "manual_required"
    assert bot["current_step"] == "auth_code_queued"
    done_auth = db.complete_command(command_id=auth["id"], status="done")
    assert "123456" not in done_auth["payload_json"]
    assert json.loads(done_auth["payload_json"]) == {"auth_code": "***"}
    bot = db.get_bot("sender-01")
    assert bot is not None
    assert bot["status"] == "session_active"
    assert bot["current_step"] == "session_active"

    refresh = db.enqueue_command(pc_id="pc-01", bot_id="sender-01", command="refresh_page")
    bot = db.get_bot("sender-01")
    assert bot is not None
    assert bot["status"] == "refreshing"
    assert bot["current_step"] == "session_refresh"
    db.complete_command(command_id=refresh["id"], status="done")
    bot = db.get_bot("sender-01")
    assert bot is not None
    assert bot["status"] == "session_active"
    assert bot["current_step"] == "session_refresh"
