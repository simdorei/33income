from income33.db import Database


def test_init_and_seed_mock_data(tmp_path):
    db_path = tmp_path / "33income.db"
    db = Database(str(db_path))

    db.init_db()
    db.seed_mock_data(agent_count=18)

    summary = db.get_summary()

    assert summary["total_agents"] == 18
    assert summary["total_bots"] == 18
    assert summary["online_agents"] == 9
    assert summary["offline_agents"] == 9
    assert summary["sender_bots"] == 9
    assert summary["reporter_bots"] == 9


def test_enqueue_and_poll_commands(tmp_path):
    db_path = tmp_path / "33income.db"
    db = Database(str(db_path))
    db.init_db()
    db.seed_mock_data(agent_count=18)

    command = db.enqueue_command(pc_id="pc-01", bot_id="sender-01", command="restart")

    assert command["status"] == "pending"

    polled = db.poll_commands(pc_id="pc-01", limit=5)
    assert len(polled) == 1
    assert polled[0]["id"] == command["id"]
    assert polled[0]["status"] == "running"

    done = db.complete_command(command_id=command["id"], status="done")
    assert done["status"] == "done"
