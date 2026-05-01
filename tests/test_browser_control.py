import logging
from urllib.parse import parse_qs, urlparse

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


class FakePage:
    url = "https://newta.3o3.co.kr/tasks/git"

    def goto(self, *args, **kwargs):  # pragma: no cover - should not be needed in this test
        raise AssertionError("already on NewTA page")


def test_preview_send_targets_scans_all_pages_reverse_by_default(monkeypatch):
    fetched_pages = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None):
        if url.endswith("/api/ta/info/v1/tax-offices/simple"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": [{"id": 325}]}}

        assert "/api/tax/v1/taxdocs/filter-search" in url
        query = parse_qs(urlparse(url).query)
        page_index = int(query["page"][0])
        size = int(query["size"][0])
        fetched_pages.append(page_index)
        start = page_index * size
        stop = min(start + size, 45)
        return {
            "ok": True,
            "status": 200,
            "json": {
                "ok": True,
                "data": {
                    "content": [{"taxDocId": tax_doc_id} for tax_doc_id in range(start + 1, stop + 1)],
                    "totalElements": 45,
                    "totalPages": 3,
                },
            },
        }

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.preview_expected_tax_send_targets(
        bot_id="sender-01",
        payload={"year": 2025, "size": 20},
    )

    assert fetched_pages == [0, 2, 1]
    assert result["count"] == 45
    assert result["total_elements"] == 45
    assert result["total_pages"] == 3
    assert result["scan_order"] == "reverse"
    assert result["pages_scanned"] == [2, 1, 0]
    assert result["tax_doc_ids"] == list(range(41, 46)) + list(range(21, 41)) + list(range(1, 21))
    assert result["current_step"] == "목록조회 테스트 45/45건 역순 3→1/3페이지 총 3페이지 officeId=325"
