from __future__ import annotations

from income33.status_mirror import StatusMirror, StatusMirrorConfig


def test_status_mirror_disabled_by_default_does_not_send():
    calls = []
    mirror = StatusMirror(
        StatusMirrorConfig(enabled=False, webhook_url=None, telegram_bot_token=None, telegram_chat_id=None),
        post_json=lambda url, body, timeout: calls.append((url, body, timeout)),
    )

    assert mirror.notify_heartbeat({"pc_id": "pc-01", "bot_id": "sender-01"}) is False
    assert calls == []


def test_status_mirror_posts_webhook_on_meaningful_heartbeat_change():
    calls = []
    now = [1000.0]
    mirror = StatusMirror(
        StatusMirrorConfig(enabled=True, webhook_url="https://mirror.example/hook", min_interval_seconds=60),
        clock=lambda: now[0],
        post_json=lambda url, body, timeout: calls.append((url, body, timeout)),
    )
    heartbeat = {
        "pc_id": "pc-01",
        "bot_id": "sender-01",
        "bot_status": "session_active",
        "current_step": "계산발송 완료",
        "version_status": "ok",
        "git_head_short": "abcdef1",
    }

    assert mirror.notify_heartbeat(heartbeat, previous_bot={"status": "running", "current_step": "old"}) is True
    assert len(calls) == 1
    assert calls[0][0] == "https://mirror.example/hook"
    assert calls[0][1]["event"] == "income33_status"
    assert calls[0][1]["pc_id"] == "pc-01"
    assert calls[0][1]["bot_id"] == "sender-01"
    assert "계산발송 완료" in calls[0][1]["text"]

    assert mirror.notify_heartbeat(heartbeat, previous_bot={"status": "session_active", "current_step": "계산발송 완료"}) is False
    assert len(calls) == 1

    now[0] += 61
    changed = dict(heartbeat, current_step="계산발송 실패: status=0")
    assert mirror.notify_heartbeat(changed, previous_bot={"status": "session_active", "current_step": "계산발송 완료"}) is True
    assert len(calls) == 2


def test_status_mirror_telegram_payload_does_not_include_bot_token():
    calls = []
    mirror = StatusMirror(
        StatusMirrorConfig(
            enabled=True,
            telegram_bot_token="TEST_TELEGRAM_TOKEN",
            telegram_chat_id="999",
            min_interval_seconds=0,
        ),
        clock=lambda: 1000.0,
        post_json=lambda url, body, timeout: calls.append((url, body, timeout)),
    )

    assert mirror.notify_heartbeat({
        "pc_id": "pc-10",
        "bot_id": "reporter-01",
        "bot_status": "manual_required",
        "current_step": "신고준비 실패",
        "version_status": "non_git",
        "git_head_short": None,
    }) is True

    assert len(calls) == 1
    url, body, timeout = calls[0]
    assert url.endswith("/sendMessage")
    assert "TEST_TELEGRAM_TOKEN" in url
    assert body["chat_id"] == "999"
    assert "TEST_TELEGRAM_TOKEN" not in str(body)
    assert "non_git" in body["text"]
