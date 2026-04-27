from fastapi.testclient import TestClient

from income33.capture.app import create_app, sanitize_event, CaptureEvent


def test_sanitize_event_redacts_sensitive_headers():
    event = CaptureEvent(
        url="https://example.test/api",
        method="post",
        request_headers={
            "Cookie": "SESSION=abc; XSRF-TOKEN=def",
            "Authorization": "Bearer secret",
            "Content-Type": "application/json",
            "X-Custom-Session-Id": "secret-session",
        },
        request_body="{}",
    )

    data = sanitize_event(event)

    assert data["method"] == "POST"
    assert data["request_headers"]["Cookie"]["redacted"] is True
    assert data["request_headers"]["Cookie"]["cookie_names"] == ["SESSION", "XSRF-TOKEN"]
    assert data["request_headers"]["Authorization"]["redacted"] is True
    assert data["request_headers"]["X-Custom-Session-Id"]["redacted"] is True
    assert data["request_headers"]["Content-Type"] == "application/json"


def test_capture_endpoint_writes_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("INCOME33_CAPTURE_DIR", str(tmp_path))
    # Re-import module constants are already loaded in normal app, so patch directly.
    import income33.capture.app as capture_app

    monkeypatch.setattr(capture_app, "DEFAULT_CAPTURE_DIR", tmp_path)
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/capture",
        json={
            "url": "https://example.test/api",
            "method": "GET",
            "request_headers": {"Cookie": "A=1"},
            "response_status": 200,
            "response_body": "ok",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert (tmp_path).exists()
    files = list(tmp_path.glob("*/captures.jsonl"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "example.test" in text
    assert "A=1" not in text
