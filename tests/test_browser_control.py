import logging

from income33.agent import browser_control


def test_mask_secret_never_exposes_value():
    assert browser_control.mask_secret("secret") == "***"
    assert browser_control.mask_secret("  ") == ""
    assert browser_control.mask_secret(None) == ""


def test_fill_login_dry_run_does_not_require_playwright(monkeypatch):
    monkeypatch.setenv("INCOME33_BROWSER_CONTROL_DRY_RUN", "1")
    monkeypatch.setenv("INCOME33_LOGIN_ID", "demo-user")
    monkeypatch.setenv("INCOME33_LOGIN_PASSWORD", "demo-password")

    def _fail_loader():
        raise AssertionError("playwright should not load in dry run")

    monkeypatch.setattr(browser_control, "_load_playwright", _fail_loader)

    result = browser_control.fill_login(bot_id="sender-01")
    assert result["dry_run"] is True
    assert result["status"] == "login_auth_required"


def test_submit_auth_code_dry_run_masks_auth_code_in_logs(monkeypatch, caplog):
    monkeypatch.setenv("INCOME33_BROWSER_CONTROL_DRY_RUN", "1")
    caplog.set_level(logging.INFO)

    result = browser_control.submit_auth_code(bot_id="sender-01", auth_code="123456")

    assert result["dry_run"] is True
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "123456" not in joined
    assert "***" in joined


def test_keepalive_due_logic():
    assert browser_control.is_keepalive_due(None, now_monotonic=100.0, interval=600) is True
    assert browser_control.is_keepalive_due(100.0, now_monotonic=699.0, interval=600) is False
    assert browser_control.is_keepalive_due(100.0, now_monotonic=700.0, interval=600) is True


def test_resolve_refresh_url_prefers_payload(monkeypatch):
    monkeypatch.setenv("INCOME33_REFRESH_URL", "https://env.example/refresh")
    assert (
        browser_control.resolve_refresh_url({"refresh_url": "https://payload.example/refresh"})
        == "https://payload.example/refresh"
    )
