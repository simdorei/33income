import logging
from urllib.parse import parse_qs, urlparse

import pytest

from income33.agent import browser_control


@pytest.fixture(autouse=True)
def isolate_one_click_log_dir(monkeypatch, tmp_path, request):
    if "one_click" in request.node.name:
        monkeypatch.setenv("INCOME33_LOG_DIR", str(tmp_path))


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


def _one_click_summary_response(
    *,
    expected_national=-605_445,
    final_national=-605_445,
    expected_local=-60_544,
    final_local=-60_544,
):
    return {
        "ok": True,
        "status": 200,
        "json": {
            "data": {
                "예상세액": {
                    "납부환급할세액_종합소득세": expected_national,
                    "납부환급할세액_지방소득세": expected_local,
                },
                "최종세액_고객계정": {
                    "납부환급할세액_종합소득세": final_national,
                    "납부환급할세액_지방소득세": final_local,
                },
            },
            "error": None,
        },
    }


class RefreshFakePage:
    def __init__(self, url="https://newta.3o3.co.kr/tasks/git"):
        self.url = url
        self.goto_calls = []
        self.reload_calls = []

    def goto(self, url, **kwargs):
        self.goto_calls.append({"url": url, "kwargs": kwargs})
        self.url = url

    def reload(self, **kwargs):
        self.reload_calls.append({"kwargs": kwargs})


def test_inspect_login_state_uses_tax_office_api_even_when_not_dashboard(monkeypatch):
    fetch_calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(RefreshFakePage(url="https://newta.3o3.co.kr/tasks/git"), 29203)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        fetch_calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        assert url.endswith("/api/ta/info/v1/tax-offices/simple")
        return {
            "ok": True,
            "status": 200,
            "json": {"ok": True, "data": [{"id": 325}, {"id": 326}, {"id": 327}]},
        }

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)
    monkeypatch.setattr(browser_control, "_has_visible_locator", lambda *args, **kwargs: False)

    result = browser_control.inspect_login_state(bot_id="sender-03")

    assert result["status"] == "session_active"
    assert result["current_step"] == "session_active"
    assert result["office_id"] == 327
    assert result["office_index"] == 2
    assert fetch_calls[0]["headers"]["x-host"] == "GROUND"


def test_inspect_login_state_treats_tax_office_401_as_login_required(monkeypatch):
    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(RefreshFakePage(url="https://newta.3o3.co.kr/tasks/git"), 29203)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        return {"ok": False, "status": 401, "json": {"ok": False, "error": "Unauthorized"}}

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)
    monkeypatch.setattr(browser_control, "_has_visible_locator", lambda *args, **kwargs: False)

    result = browser_control.inspect_login_state(bot_id="sender-01")

    assert result["status"] == "login_required"
    assert "401" in result["current_step"]


def test_refresh_page_verifies_session_with_tax_office_api(monkeypatch):
    page = RefreshFakePage(url="https://newta.3o3.co.kr/login")

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(page, 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        assert url.endswith("/api/ta/info/v1/tax-offices/simple")
        return {"ok": False, "status": 401, "json": {"ok": False, "error": "Unauthorized"}}

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.refresh_page(bot_id="sender-01", payload={"force": True})

    assert result["status"] == "login_required"
    assert "401" in result["current_step"]
    assert page.goto_calls
    assert page.reload_calls


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


def test_preview_send_targets_selects_office_id_from_sender_bot_index(monkeypatch):
    filter_search_queries = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None):
        if url.endswith("/api/ta/info/v1/tax-offices/simple"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": [{"id": 325}, {"id": 326}, {"id": 327}, {"id": 328}, {"id": 329}],
                },
            }

        assert "/api/tax/v1/taxdocs/filter-search" in url
        filter_search_queries.append(parse_qs(urlparse(url).query))
        return {
            "ok": True,
            "status": 200,
            "json": {
                "ok": True,
                "data": {
                    "content": [],
                    "totalElements": 0,
                    "totalPages": 1,
                },
            },
        }

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.preview_expected_tax_send_targets(
        bot_id="sender-05",
        payload={"year": 2025, "size": 20, "scan_order": "forward"},
    )

    assert result["office_id"] == 329
    assert result["office_index"] == 4
    assert filter_search_queries[0]["officeId"] == ["329"]


def test_send_expected_tax_amounts_posts_selected_tax_doc_ids(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/tax/v1/taxdocs/expected-tax-amount/send"):
            assert method == "POST"
            assert headers["x-host"] == "GIT"
            assert headers["x-web-path"] == "https://newta.3o3.co.kr/tasks/git"
            assert json_body == {"taxDocIdSet": [1360165, 1360211]}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"result": True}, "error": None}}
        if url.endswith("/api/ta/info/v1/tax-offices/simple"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": [{"id": 325}]}}
        assert "/api/tax/v1/taxdocs/filter-search" in url
        return {
            "ok": True,
            "status": 200,
            "json": {
                "ok": True,
                "data": {"content": [], "totalElements": 0, "totalPages": 1},
            },
        }

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.send_expected_tax_amounts(
        bot_id="sender-01",
        payload={"tax_doc_ids": [1360165, 1360211]},
    )

    assert any(call["url"].endswith("/api/tax/v1/taxdocs/expected-tax-amount/send") for call in calls)
    assert result["status"] == "session_active"
    assert result["sent_count"] == 2
    assert result["tax_doc_ids"] == [1360165, 1360211]
    assert result["current_step"] == "계산발송 완료 2건 status=200"


def test_send_expected_tax_amounts_can_collect_targets_then_post(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "json_body": json_body})
        if url.endswith("/api/ta/info/v1/tax-offices/simple"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": [{"id": 325}]}}
        if "/api/tax/v1/taxdocs/filter-search" in url:
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "content": [{"taxDocId": 11}, {"taxDocId": 12}],
                        "totalElements": 2,
                        "totalPages": 1,
                    },
                },
            }
        assert url.endswith("/api/tax/v1/taxdocs/expected-tax-amount/send")
        assert method == "POST"
        assert json_body == {"taxDocIdSet": [11, 12]}
        return {"ok": True, "status": 200, "json": {"ok": True, "data": {"result": True}, "error": None}}

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.send_expected_tax_amounts(bot_id="sender-01", payload={"year": 2025, "size": 20})

    send_calls = [call for call in calls if call["url"].endswith("/api/tax/v1/taxdocs/expected-tax-amount/send")]
    assert len(send_calls) == 1
    assert send_calls[0]["method"] == "POST"
    assert send_calls[0]["json_body"] == {"taxDocIdSet": [11, 12]}
    assert result["sent_count"] == 2
    assert result["tax_doc_ids"] == [11, 12]


def test_send_expected_tax_amounts_keeps_session_active_when_collected_targets_are_empty(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "json_body": json_body})
        if url.endswith("/api/ta/info/v1/tax-offices/simple"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": [{"id": 325}]}}
        assert "/api/tax/v1/taxdocs/filter-search" in url
        return {
            "ok": True,
            "status": 200,
            "json": {
                "ok": True,
                "data": {
                    "content": [],
                    "totalElements": 0,
                    "totalPages": 1,
                },
            },
        }

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.send_expected_tax_amounts(bot_id="sender-01", payload={"year": 2025, "size": 20})

    assert [call["method"] for call in calls] == ["GET", "GET"]
    assert result["status"] == "session_active"
    assert result["sent_count"] == 0
    assert result["tax_doc_ids"] == []
    assert result["current_step"] == "계산발송 대상 없음"


def test_send_simple_expense_rate_expected_tax_amounts_checks_summary_then_conditionally_posts(monkeypatch):
    calls = []

    def fake_preview_expected_tax_send_targets(*, bot_id, payload, logger):
        assert payload["workflow_filter_set"] == "REVIEW_WAITING"
        assert payload["apply_expense_rate_type_filter"] == "SIMPLIFIED_EXPENSE_RATE"
        assert payload["tax_doc_custom_type_filter"] == "NONE"
        assert payload["direction"] == "ASC"
        assert payload["scan_order"] == "forward"
        return {
            "ok": True,
            "status": "session_active",
            "count": 2,
            "tax_doc_ids": [1368668, 1368669],
        }

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        assert headers["x-host"] == "GIT"
        assert headers["x-web-path"] == "https://newta.3o3.co.kr/git/summary"

        if url.endswith("/api/tax/v1/taxdocs/1368668/summary?isMasking=true"):
            assert method == "GET"
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"taxDocTaxRayList": []}}}

        if url.endswith(
            "/api/tax/v1/taxdocs/1368668/expected-tax-amount/calculation/estimate?submitAccountType=CUSTOMER"
        ):
            assert method == "GET"
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "종합소득세_납부_할_세액": 2079941,
                        "지방소득세_납부_할_세액": 207994,
                        "권장수수료": 88000,
                    },
                },
            }

        if url.endswith("/api/tax/v1/taxdocs/1368668/expected-tax-amount/send"):
            assert method == "POST"
            assert json_body == {
                "calculationType": "ESTIMATE",
                "submitAccountType": "CUSTOMER",
                "추가_경비_인정액": 0,
                "expectedTaxAmount": 2079941,
                "expectedLocalTaxAmount": 207994,
                "submitFee": 88000,
                "advisedFeeAmount": 88000,
                "isCustomReview": False,
                "isTimeDiscount": False,
                "timeDiscountFee": None,
            }
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"result": True}, "error": None}}

        if url.endswith("/api/tax/v1/taxdocs/1368669/summary?isMasking=true"):
            assert method == "GET"
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": True, "data": {"taxDocTaxRayList": [{"id": 1, "type": "중복수입의심"}]}},
            }

        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "preview_expected_tax_send_targets", fake_preview_expected_tax_send_targets)
    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.send_simple_expense_rate_expected_tax_amounts(bot_id="sender-01", payload={})

    assert [
        (call["method"], call["url"].split("/api/tax/v1/taxdocs/")[1])
        for call in calls
    ] == [
        ("GET", "1368668/summary?isMasking=true"),
        ("GET", "1368669/summary?isMasking=true"),
        ("GET", "1368668/expected-tax-amount/calculation/estimate?submitAccountType=CUSTOMER"),
        ("POST", "1368668/expected-tax-amount/send"),
    ]
    assert result["ok"] is True
    assert result["attempted_count"] == 2
    assert result["sent_count"] == 1
    assert result["skipped_count"] == 1
    assert result["failed_count"] == 0
    assert result["tax_doc_ids"] == [1368668, 1368669]
    assert result["eligible_tax_doc_ids"] == [1368668]
    assert result["sent_tax_doc_ids"] == [1368668]
    assert result["current_step"] == "단순경비율 목록발송 완료 발송=1건 스킵=1건 실패=0건"


def test_send_simple_expense_rate_expected_tax_amounts_ignores_forced_bookkeeping_calculation_type(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/tax/v1/taxdocs/1368668/summary?isMasking=true"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"taxDocTaxRayList": []}}}
        if url.endswith(
            "/api/tax/v1/taxdocs/1368668/expected-tax-amount/calculation/estimate?submitAccountType=CUSTOMER"
        ):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "종합소득세_납부_할_세액": 2079941,
                        "지방소득세_납부_할_세액": 207994,
                        "권장수수료": 88000,
                    },
                },
            }
        if url.endswith("/api/tax/v1/taxdocs/1368668/expected-tax-amount/send"):
            assert method == "POST"
            assert json_body["calculationType"] == "ESTIMATE"
            assert json_body["추가_경비_인정액"] == 0
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"result": True}, "error": None}}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.send_simple_expense_rate_expected_tax_amounts(
        bot_id="sender-01",
        payload={"tax_doc_ids": [1368668], "calculation_type": "BOOKKEEPING"},
    )

    assert result["ok"] is True
    assert [call["method"] for call in calls] == ["GET", "GET", "POST"]


def test_send_simple_expense_rate_expected_tax_amounts_marks_summary_errors_as_failed_and_continues(monkeypatch):
    calls = []

    def fake_preview_expected_tax_send_targets(*, bot_id, payload, logger):
        return {
            "ok": True,
            "status": "session_active",
            "count": 5,
            "tax_doc_ids": [2001, 2002, 2003, 2004, 2005],
        }

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})

        if url.endswith("/api/tax/v1/taxdocs/2001/summary?isMasking=true"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"taxDocTaxRayList": []}}}
        if url.endswith(
            "/api/tax/v1/taxdocs/2001/expected-tax-amount/calculation/estimate?submitAccountType=CUSTOMER"
        ):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "종합소득세_납부_할_세액": 101,
                        "지방소득세_납부_할_세액": 10,
                        "권장수수료": 55,
                    },
                },
            }
        if url.endswith("/api/tax/v1/taxdocs/2001/expected-tax-amount/send"):
            assert method == "POST"
            assert json_body == {
                "calculationType": "ESTIMATE",
                "submitAccountType": "CUSTOMER",
                "추가_경비_인정액": 0,
                "expectedTaxAmount": 101,
                "expectedLocalTaxAmount": 10,
                "submitFee": 55,
                "advisedFeeAmount": 55,
                "isCustomReview": False,
                "isTimeDiscount": False,
                "timeDiscountFee": None,
            }
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"result": True}}}

        if url.endswith("/api/tax/v1/taxdocs/2002/summary?isMasking=true"):
            return {"ok": False, "status": 503, "json": None, "fetch_error": "network timeout"}

        if url.endswith("/api/tax/v1/taxdocs/2003/summary?isMasking=true"):
            return {"ok": True, "status": 200, "json": {"ok": False, "data": None, "error": {"message": "bad"}}}

        if url.endswith("/api/tax/v1/taxdocs/2004/summary?isMasking=true"):
            return {"ok": True, "status": 200, "json": {"ok": True}}

        if url.endswith("/api/tax/v1/taxdocs/2005/summary?isMasking=true"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"taxDocTaxRayList": []}}}
        if url.endswith(
            "/api/tax/v1/taxdocs/2005/expected-tax-amount/calculation/estimate?submitAccountType=CUSTOMER"
        ):
            return {"ok": False, "status": 504, "json": None, "fetch_error": "gateway timeout"}

        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "preview_expected_tax_send_targets", fake_preview_expected_tax_send_targets)
    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.send_simple_expense_rate_expected_tax_amounts(
        bot_id="sender-01",
        payload={"calculation_retry_count": 0, "calculation_retry_delay_seconds": 0},
    )

    assert [
        (call["method"], call["url"].split("/api/tax/v1/taxdocs/")[1])
        for call in calls
    ] == [
        ("GET", "2001/summary?isMasking=true"),
        ("GET", "2002/summary?isMasking=true"),
        ("GET", "2003/summary?isMasking=true"),
        ("GET", "2004/summary?isMasking=true"),
        ("GET", "2005/summary?isMasking=true"),
        ("GET", "2001/expected-tax-amount/calculation/estimate?submitAccountType=CUSTOMER"),
        ("POST", "2001/expected-tax-amount/send"),
        ("GET", "2005/expected-tax-amount/calculation/estimate?submitAccountType=CUSTOMER"),
    ]
    assert result["attempted_count"] == 5
    assert result["sent_count"] == 1
    assert result["skipped_count"] == 0
    assert result["failed_count"] == 4
    assert result["eligible_tax_doc_ids"] == [2001, 2005]
    assert result["sent_tax_doc_ids"] == [2001]
    assert result["current_step"] == "단순경비율 목록발송 완료 발송=1건 스킵=0건 실패=4건"
    assert [failure["tax_doc_id"] for failure in result["failures"]] == [2002, 2003, 2004, 2005]
    assert result["failures"][-1]["stage"] == "calculation"
    assert result["failures"][-1]["reason"] == "calculation_http_non_ok"


def test_send_simple_expense_rate_expected_tax_amounts_retries_calculation_only(monkeypatch):
    calls = []
    calculation_attempt = {"count": 0}

    def fake_preview_expected_tax_send_targets(*, bot_id, payload, logger):
        return {
            "ok": True,
            "status": "session_active",
            "count": 1,
            "tax_doc_ids": [9101],
        }

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "json_body": json_body})

        if url.endswith("/api/tax/v1/taxdocs/9101/summary?isMasking=true"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"taxDocTaxRayList": []}}}

        if url.endswith(
            "/api/tax/v1/taxdocs/9101/expected-tax-amount/calculation/estimate?submitAccountType=CUSTOMER"
        ):
            calculation_attempt["count"] += 1
            if calculation_attempt["count"] == 1:
                return {"ok": False, "status": 503, "json": None, "fetch_error": "temporary unavailable"}
            if calculation_attempt["count"] == 2:
                return {
                    "ok": True,
                    "status": 200,
                    "json": {
                        "ok": True,
                        "data": {
                            "종합소득세_납부_할_세액": 777,
                            "지방소득세_납부_할_세액": 77,
                            "권장수수료": 33,
                        },
                    },
                }

        if url.endswith("/api/tax/v1/taxdocs/9101/expected-tax-amount/send"):
            assert method == "POST"
            assert json_body == {
                "calculationType": "ESTIMATE",
                "submitAccountType": "CUSTOMER",
                "추가_경비_인정액": 0,
                "expectedTaxAmount": 777,
                "expectedLocalTaxAmount": 77,
                "submitFee": 33,
                "advisedFeeAmount": 33,
                "isCustomReview": False,
                "isTimeDiscount": False,
                "timeDiscountFee": None,
            }
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"result": True}}}

        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "preview_expected_tax_send_targets", fake_preview_expected_tax_send_targets)
    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.send_simple_expense_rate_expected_tax_amounts(
        bot_id="sender-01",
        payload={"calculation_retry_count": 2, "calculation_retry_delay_seconds": 0},
    )

    assert result["failed_count"] == 0
    assert result["sent_count"] == 1
    assert calculation_attempt["count"] == 2
    assert [
        (call["method"], call["url"].split("/api/tax/v1/taxdocs/")[1])
        for call in calls
    ] == [
        ("GET", "9101/summary?isMasking=true"),
        ("GET", "9101/expected-tax-amount/calculation/estimate?submitAccountType=CUSTOMER"),
        ("GET", "9101/expected-tax-amount/calculation/estimate?submitAccountType=CUSTOMER"),
        ("POST", "9101/expected-tax-amount/send"),
    ]


def test_send_simple_expense_rate_expected_tax_amounts_logs_failure_reasons(monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    def fake_preview_expected_tax_send_targets(*, bot_id, payload, logger):
        return {
            "ok": True,
            "status": "session_active",
            "count": 3,
            "tax_doc_ids": [4001, 4002, 4003],
        }

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        if url.endswith("/api/tax/v1/taxdocs/4001/summary?isMasking=true"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"taxDocTaxRayList": []}}}
        if url.endswith(
            "/api/tax/v1/taxdocs/4001/expected-tax-amount/calculation/estimate?submitAccountType=CUSTOMER"
        ):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "종합소득세_납부_할_세액": 11,
                        "지방소득세_납부_할_세액": 1,
                        "권장수수료": 9,
                    },
                },
            }
        if url.endswith("/api/tax/v1/taxdocs/4002/summary?isMasking=true"):
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": False, "data": None, "error": {"message": "요약 조회 실패"}},
            }
        if url.endswith("/api/tax/v1/taxdocs/4003/summary?isMasking=true"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"taxDocTaxRayList": [{"id": 7}]}}}
        if url.endswith("/api/tax/v1/taxdocs/4001/expected-tax-amount/send"):
            return {
                "ok": False,
                "status": 400,
                "json": {"ok": False, "data": {"result": False}, "error": {"message": "발송 제한"}},
                "text": "발송 제한",
            }

        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "preview_expected_tax_send_targets", fake_preview_expected_tax_send_targets)
    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.send_simple_expense_rate_expected_tax_amounts(bot_id="sender-01", payload={})

    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert result["failed_count"] == 2
    assert result["skipped_count"] == 1
    assert (
        "send_simple_expense_rate_expected_tax_amounts_failure "
        "bot_id=sender-01 tax_doc_id=4002 stage=summary reason=summary_json_non_ok status=200 detail=요약 조회 실패"
    ) in joined
    assert (
        "send_simple_expense_rate_expected_tax_amounts_failure "
        "bot_id=sender-01 tax_doc_id=4001 stage=send reason=send_failed status=400 detail=발송 제한"
    ) in joined
    assert (
        "send_simple_expense_rate_expected_tax_amounts_skipped "
        "bot_id=sender-01 tax_doc_id=4003 reason=tax_ray_exists tax_ray_count=1"
    ) in joined


def test_send_simple_expense_rate_collects_all_pages_then_summaries_then_sorted_sends(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/ta/info/v1/tax-offices/simple"):
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": True, "data": [{"id": 325}, {"id": 329}]},
            }

        if "/api/tax/v1/taxdocs/filter-search" in url:
            query = parse_qs(urlparse(url).query)
            assert query["officeId"] == ["329"]
            assert query["workflowFilterSet"] == ["REVIEW_WAITING"]
            assert query["taxDocCustomTypeFilter"] == ["NONE"]
            assert query["applyExpenseRateTypeFilter"] == ["SIMPLIFIED_EXPENSE_RATE"]
            assert query["taxDocServiceCodeTypeFilter"] == ["C0"]
            assert query["year"] == ["2025"]
            assert query["sort"] == ["REVIEW_REQUEST_DATE_TIME"]
            assert query["direction"] == ["ASC"]
            assert query["size"] == ["2"]
            page_index = int(query["page"][0])
            content_by_page = {
                0: [{"taxDocId": 3001}, {"taxDocId": 3002}],
                1: [{"taxDocId": 3003}],
            }
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "content": content_by_page[page_index],
                        "totalElements": 3,
                        "totalPages": 2,
                    },
                },
            }

        if url.endswith("/api/tax/v1/taxdocs/3001/summary?isMasking=true"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"taxDocTaxRayList": [{"id": 1}]}}}
        if url.endswith("/api/tax/v1/taxdocs/3002/summary?isMasking=true"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"taxDocTaxRayList": []}}}
        if url.endswith("/api/tax/v1/taxdocs/3003/summary?isMasking=true"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"taxDocTaxRayList": []}}}
        if url.endswith(
            "/api/tax/v1/taxdocs/3002/expected-tax-amount/calculation/estimate?submitAccountType=CUSTOMER"
        ):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "종합소득세_납부_할_세액": 201,
                        "지방소득세_납부_할_세액": 20,
                        "권장수수료": 35,
                    },
                },
            }
        if url.endswith(
            "/api/tax/v1/taxdocs/3003/expected-tax-amount/calculation/estimate?submitAccountType=CUSTOMER"
        ):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "종합소득세_납부_할_세액": 301,
                        "지방소득세_납부_할_세액": 30,
                        "권장수수료": 45,
                    },
                },
            }
        if url.endswith("/api/tax/v1/taxdocs/3002/expected-tax-amount/send"):
            assert method == "POST"
            assert json_body == {
                "calculationType": "ESTIMATE",
                "submitAccountType": "CUSTOMER",
                "추가_경비_인정액": 0,
                "expectedTaxAmount": 201,
                "expectedLocalTaxAmount": 20,
                "submitFee": 35,
                "advisedFeeAmount": 35,
                "isCustomReview": False,
                "isTimeDiscount": False,
                "timeDiscountFee": None,
            }
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"result": True}}}
        if url.endswith("/api/tax/v1/taxdocs/3003/expected-tax-amount/send"):
            assert method == "POST"
            assert json_body == {
                "calculationType": "ESTIMATE",
                "submitAccountType": "CUSTOMER",
                "추가_경비_인정액": 0,
                "expectedTaxAmount": 301,
                "expectedLocalTaxAmount": 30,
                "submitFee": 45,
                "advisedFeeAmount": 45,
                "isCustomReview": False,
                "isTimeDiscount": False,
                "timeDiscountFee": None,
            }
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"result": True}}}

        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.send_simple_expense_rate_expected_tax_amounts(
        bot_id="sender-02",
        payload={"year": 2025, "size": 2},
    )

    taxdoc_calls = [
        call
        for call in calls
        if "/api/tax/v1/taxdocs/filter-search" in call["url"] or "/api/tax/v1/taxdocs/" in call["url"]
    ]
    assert [
        (call["method"], call["url"].split("/api/tax/v1/taxdocs/")[1])
        for call in taxdoc_calls
    ] == [
        ("GET", "filter-search?officeId=329&workflowFilterSet=REVIEW_WAITING&assignmentStatusFilter=ALL&taxDocCustomTypeFilter=NONE&businessIncomeTypeFilter=ALL&freelancerIncomeAmountTypeFilter=ALL&reviewTypeFilter=NORMAL&submitGuideTypeFilter=ALL&applyExpenseRateTypeFilter=SIMPLIFIED_EXPENSE_RATE&noticeTypeFilter=ALL&extraSurveyTypeFilter=ALL&expectedTaxAmountTypeFilter=ALL&freeReasonTypeFilter=ALL&refundStatusFilter=ALL&taxDocServiceCodeTypeFilter=C0&year=2025&sort=REVIEW_REQUEST_DATE_TIME&direction=ASC&page=0&size=2"),
        ("GET", "filter-search?officeId=329&workflowFilterSet=REVIEW_WAITING&assignmentStatusFilter=ALL&taxDocCustomTypeFilter=NONE&businessIncomeTypeFilter=ALL&freelancerIncomeAmountTypeFilter=ALL&reviewTypeFilter=NORMAL&submitGuideTypeFilter=ALL&applyExpenseRateTypeFilter=SIMPLIFIED_EXPENSE_RATE&noticeTypeFilter=ALL&extraSurveyTypeFilter=ALL&expectedTaxAmountTypeFilter=ALL&freeReasonTypeFilter=ALL&refundStatusFilter=ALL&taxDocServiceCodeTypeFilter=C0&year=2025&sort=REVIEW_REQUEST_DATE_TIME&direction=ASC&page=1&size=2"),
        ("GET", "3001/summary?isMasking=true"),
        ("GET", "3002/summary?isMasking=true"),
        ("GET", "3003/summary?isMasking=true"),
        ("GET", "3002/expected-tax-amount/calculation/estimate?submitAccountType=CUSTOMER"),
        ("POST", "3002/expected-tax-amount/send"),
        ("GET", "3003/expected-tax-amount/calculation/estimate?submitAccountType=CUSTOMER"),
        ("POST", "3003/expected-tax-amount/send"),
    ]
    assert result["tax_doc_ids"] == [3001, 3002, 3003]
    assert result["eligible_tax_doc_ids"] == [3002, 3003]
    assert result["sent_tax_doc_ids"] == [3002, 3003]
    assert result["sent_count"] == 2
    assert result["skipped_count"] == 1
    assert result["failed_count"] == 0


def test_send_bookkeeping_expected_tax_amount_calculates_extra_expense_then_posts_single_send(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/tax/v1/taxdocs/1345836/expected-tax-amount/send"):
            assert method == "POST"
            assert headers["x-host"] == "GIT"
            assert json_body == {
                "calculationType": "BOOKKEEPING",
                "submitAccountType": "CUSTOMER",
                "추가_경비_인정액": 27543987,
                "expectedTaxAmount": -621639,
                "expectedLocalTaxAmount": -62164,
                "submitFee": 185000,
                "advisedFeeAmount": 185000,
                "isCustomReview": False,
                "isTimeDiscount": False,
                "timeDiscountFee": None,
            }
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"result": True}, "error": None}}

        assert "/api/tax/v1/taxdocs/1345836/expected-tax-amount/calculation/bookkeeping" in url
        assert method == "GET"
        assert headers["x-host"] == "GIT"
        query = parse_qs(urlparse(url).query)
        assert query["submitAccountType"] == ["CUSTOMER"]
        additional_expense_amount = int(query["additionalExpenseAmount"][0])
        if additional_expense_amount == 0:
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "사업소득_필요_경비": 13994157,
                        "사업소득_추가_경비_인정액": 0,
                    },
                    "error": None,
                },
            }
        assert additional_expense_amount == 27543987
        return {
            "ok": True,
            "status": 200,
            "json": {
                "ok": True,
                "data": {
                    "사업소득_필요_경비": 13994157,
                    "사업소득_추가_경비_인정액": 27543987,
                    "종합소득세_납부_할_세액": -621639,
                    "지방소득세_납부_할_세액": -62164,
                    "권장수수료": 185000,
                },
                "error": None,
            },
        }

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.send_bookkeeping_expected_tax_amount(
        bot_id="sender-01",
        payload={
            "tax_doc_id": 1345836,
            "submit_account_type": "CUSTOMER",
            "total_business_expense_amount": 41538144,
        },
    )

    assert [call["method"] for call in calls] == ["GET", "GET", "POST"]
    assert result["tax_doc_id"] == 1345836
    assert result["base_business_expense_amount"] == 13994157
    assert result["total_business_expense_amount"] == 41538144
    assert result["additional_expense_amount"] == 27543987
    assert result["expected_tax_amount"] == -621639
    assert result["expected_local_tax_amount"] == -62164
    assert result["submit_fee"] == 185000
    assert result["current_step"] == "단건 계산발송 완료 taxDocId=1345836 추가경비=27543987 예상세액=-621639 지방세=-62164 수수료=185000 status=200"


def test_send_bookkeeping_expected_tax_amount_retries_final_calculation_when_additional_expense_missing(monkeypatch):
    calls = []
    final_calculation_attempts = 0

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        nonlocal final_calculation_attempts
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/tax/v1/taxdocs/1345836/expected-tax-amount/send"):
            assert method == "POST"
            assert json_body["추가_경비_인정액"] == 27_543_987
            assert json_body["expectedTaxAmount"] == -621_639
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"result": True}, "error": None}}

        assert "/api/tax/v1/taxdocs/1345836/expected-tax-amount/calculation/bookkeeping" in url
        query = parse_qs(urlparse(url).query)
        additional_expense_amount = int(query["additionalExpenseAmount"][0])
        if additional_expense_amount == 0:
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": True, "data": {"사업소득_필요_경비": 13_994_157}, "error": None},
            }
        assert additional_expense_amount == 27_543_987
        final_calculation_attempts += 1
        applied_amount = 0 if final_calculation_attempts == 1 else 27_543_987
        return {
            "ok": True,
            "status": 200,
            "json": {
                "ok": True,
                "data": {
                    "사업소득_필요_경비": 13_994_157,
                    "사업소득_추가_경비_인정액": applied_amount,
                    "종합소득세_납부_할_세액": -621_639,
                    "지방소득세_납부_할_세액": -62_164,
                    "권장수수료": 185_000,
                },
                "error": None,
            },
        }

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.send_bookkeeping_expected_tax_amount(
        bot_id="sender-01",
        payload={
            "tax_doc_id": 1345836,
            "submit_account_type": "CUSTOMER",
            "total_business_expense_amount": 41_538_144,
        },
    )

    assert [call["method"] for call in calls] == ["GET", "GET", "GET", "POST"]
    assert final_calculation_attempts == 2
    assert result["additional_expense_amount"] == 27_543_987
    assert result["expected_tax_amount"] == -621_639


def test_send_bookkeeping_expected_tax_amount_aborts_when_final_calculation_retry_still_mismatches(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/tax/v1/taxdocs/1345836/expected-tax-amount/send"):
            raise AssertionError("send must not be posted while final calculation still mismatches additional expense")

        assert "/api/tax/v1/taxdocs/1345836/expected-tax-amount/calculation/bookkeeping" in url
        query = parse_qs(urlparse(url).query)
        additional_expense_amount = int(query["additionalExpenseAmount"][0])
        if additional_expense_amount == 0:
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": True, "data": {"사업소득_필요_경비": 13_994_157}, "error": None},
            }
        assert additional_expense_amount == 27_543_987
        return {
            "ok": True,
            "status": 200,
            "json": {
                "ok": True,
                "data": {
                    "사업소득_필요_경비": 13_994_157,
                    "사업소득_추가_경비_인정액": 0,
                    "종합소득세_납부_할_세액": -621_639,
                    "지방소득세_납부_할_세액": -62_164,
                    "권장수수료": 185_000,
                },
                "error": None,
            },
        }

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    with pytest.raises(RuntimeError, match="additional expense mismatch expected=27543987 actual=0"):
        browser_control.send_bookkeeping_expected_tax_amount(
            bot_id="sender-01",
            payload={
                "tax_doc_id": 1345836,
                "submit_account_type": "CUSTOMER",
                "total_business_expense_amount": 41_538_144,
            },
        )

    assert [call["method"] for call in calls] == ["GET", "GET", "GET"]


def test_send_bookkeeping_expected_tax_amount_retries_base_calculation_transport_failure_then_posts_once(monkeypatch):
    calls = []
    base_attempts = 0

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        nonlocal base_attempts
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/tax/v1/taxdocs/1345836/expected-tax-amount/send"):
            assert method == "POST"
            assert json_body["추가_경비_인정액"] == 27_543_987
            assert json_body["expectedTaxAmount"] == -621_639
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"result": True}, "error": None}}

        assert "/api/tax/v1/taxdocs/1345836/expected-tax-amount/calculation/bookkeeping" in url
        query = parse_qs(urlparse(url).query)
        additional_expense_amount = int(query["additionalExpenseAmount"][0])
        if additional_expense_amount == 0:
            base_attempts += 1
            if base_attempts == 1:
                return {"ok": False, "status": 503, "json": None, "text": "temporary", "fetch_error": None}
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {"사업소득_필요_경비": 13_994_157, "사업소득_추가_경비_인정액": 0},
                    "error": None,
                },
            }
        assert additional_expense_amount == 27_543_987
        return {
            "ok": True,
            "status": 200,
            "json": {
                "ok": True,
                "data": {
                    "사업소득_추가_경비_인정액": 27_543_987,
                    "종합소득세_납부_할_세액": -621_639,
                    "지방소득세_납부_할_세액": -62_164,
                    "권장수수료": 185_000,
                },
                "error": None,
            },
        }

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)
    monkeypatch.setattr(browser_control.time, "sleep", lambda seconds: None)

    result = browser_control.send_bookkeeping_expected_tax_amount(
        bot_id="sender-01",
        payload={
            "tax_doc_id": 1345836,
            "submit_account_type": "CUSTOMER",
            "total_business_expense_amount": 41_538_144,
            "bookkeeping_calculation_retry_delay_seconds": 0,
        },
    )

    assert [call["method"] for call in calls] == ["GET", "GET", "GET", "POST"]
    assert base_attempts == 2
    assert result["additional_expense_amount"] == 27_543_987


def test_send_bookkeeping_expected_tax_amount_retries_final_calculation_transport_failure_then_posts_once(monkeypatch):
    calls = []
    final_attempts = 0

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        nonlocal final_attempts
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/tax/v1/taxdocs/1345836/expected-tax-amount/send"):
            assert method == "POST"
            assert json_body["expectedTaxAmount"] == -621_639
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"result": True}, "error": None}}

        assert "/api/tax/v1/taxdocs/1345836/expected-tax-amount/calculation/bookkeeping" in url
        query = parse_qs(urlparse(url).query)
        additional_expense_amount = int(query["additionalExpenseAmount"][0])
        if additional_expense_amount == 0:
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": True, "data": {"사업소득_필요_경비": 13_994_157}, "error": None},
            }
        final_attempts += 1
        if final_attempts == 1:
            return {"ok": False, "status": 504, "json": None, "text": "gateway timeout", "fetch_error": None}
        return {
            "ok": True,
            "status": 200,
            "json": {
                "ok": True,
                "data": {
                    "사업소득_추가_경비_인정액": 27_543_987,
                    "종합소득세_납부_할_세액": -621_639,
                    "지방소득세_납부_할_세액": -62_164,
                    "권장수수료": 185_000,
                },
                "error": None,
            },
        }

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)
    monkeypatch.setattr(browser_control.time, "sleep", lambda seconds: None)

    result = browser_control.send_bookkeeping_expected_tax_amount(
        bot_id="sender-01",
        payload={
            "tax_doc_id": 1345836,
            "submit_account_type": "CUSTOMER",
            "total_business_expense_amount": 41_538_144,
            "bookkeeping_calculation_retry_delay_seconds": 0,
        },
    )

    assert [call["method"] for call in calls] == ["GET", "GET", "GET", "POST"]
    assert final_attempts == 2
    assert result["expected_tax_amount"] == -621_639


def test_send_bookkeeping_expected_tax_amount_retries_until_final_tax_fields_materialize(monkeypatch):
    calls = []
    final_attempts = 0

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        nonlocal final_attempts
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/tax/v1/taxdocs/1345836/expected-tax-amount/send"):
            assert method == "POST"
            assert json_body["expectedTaxAmount"] == -621_639
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"result": True}, "error": None}}

        assert "/api/tax/v1/taxdocs/1345836/expected-tax-amount/calculation/bookkeeping" in url
        query = parse_qs(urlparse(url).query)
        additional_expense_amount = int(query["additionalExpenseAmount"][0])
        if additional_expense_amount == 0:
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": True, "data": {"사업소득_필요_경비": 13_994_157}, "error": None},
            }
        final_attempts += 1
        data = {
            "사업소득_추가_경비_인정액": 27_543_987,
        }
        if final_attempts == 2:
            data.update(
                {
                    "종합소득세_납부_할_세액": -621_639,
                    "지방소득세_납부_할_세액": -62_164,
                    "권장수수료": 185_000,
                }
            )
        return {"ok": True, "status": 200, "json": {"ok": True, "data": data, "error": None}}

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)
    monkeypatch.setattr(browser_control.time, "sleep", lambda seconds: None)

    result = browser_control.send_bookkeeping_expected_tax_amount(
        bot_id="sender-01",
        payload={
            "tax_doc_id": 1345836,
            "submit_account_type": "CUSTOMER",
            "total_business_expense_amount": 41_538_144,
            "bookkeeping_calculation_retry_delay_seconds": 0,
        },
    )

    assert [call["method"] for call in calls] == ["GET", "GET", "GET", "POST"]
    assert final_attempts == 2
    assert result["expected_tax_amount"] == -621_639


def test_send_bookkeeping_expected_tax_amount_does_not_retry_send_post_on_transient_failure(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/tax/v1/taxdocs/1345836/expected-tax-amount/send"):
            assert method == "POST"
            return {"ok": False, "status": 503, "json": None, "text": "temporary", "fetch_error": None}

        assert "/api/tax/v1/taxdocs/1345836/expected-tax-amount/calculation/bookkeeping" in url
        query = parse_qs(urlparse(url).query)
        additional_expense_amount = int(query["additionalExpenseAmount"][0])
        if additional_expense_amount == 0:
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": True, "data": {"사업소득_필요_경비": 13_994_157}, "error": None},
            }
        return {
            "ok": True,
            "status": 200,
            "json": {
                "ok": True,
                "data": {
                    "사업소득_추가_경비_인정액": 27_543_987,
                    "종합소득세_납부_할_세액": -621_639,
                    "지방소득세_납부_할_세액": -62_164,
                    "권장수수료": 185_000,
                },
                "error": None,
            },
        }

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    with pytest.raises(RuntimeError, match="bookkeeping expected tax amount send failed status=503"):
        browser_control.send_bookkeeping_expected_tax_amount(
            bot_id="sender-01",
            payload={
                "tax_doc_id": 1345836,
                "submit_account_type": "CUSTOMER",
                "total_business_expense_amount": 41_538_144,
            },
        )

    assert [call["method"] for call in calls] == ["GET", "GET", "POST"]


def test_send_bookkeeping_expected_tax_amount_rejects_total_expense_below_base(monkeypatch):
    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        return {
            "ok": True,
            "status": 200,
            "json": {"ok": True, "data": {"사업소득_필요_경비": 13994157}, "error": None},
        }

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    try:
        browser_control.send_bookkeeping_expected_tax_amount(
            bot_id="sender-01",
            payload={
                "tax_doc_id": 1345836,
                "submit_account_type": "CUSTOMER",
                "total_business_expense_amount": 13000000,
            },
        )
    except ValueError as exc:
        assert "total_business_expense_amount must be greater than base business expense" in str(exc)
    else:  # pragma: no cover - explicit assertion branch
        raise AssertionError("expense below base should fail")


def test_send_bookkeeping_expected_tax_amount_rejects_total_expense_equal_to_base_without_post(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/tax/v1/taxdocs/1345836/expected-tax-amount/send"):
            raise AssertionError("BOOKKEEPING send must not be posted with zero additional expense")

        assert "/api/tax/v1/taxdocs/1345836/expected-tax-amount/calculation/bookkeeping" in url
        query = parse_qs(urlparse(url).query)
        assert query["additionalExpenseAmount"] == ["0"]
        if len(calls) == 1:
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": True, "data": {"사업소득_필요_경비": 13_994_157}, "error": None},
            }
        return {
            "ok": True,
            "status": 200,
            "json": {
                "ok": True,
                "data": {
                    "사업소득_필요_경비": 13_994_157,
                    "사업소득_추가_경비_인정액": 0,
                    "종합소득세_납부_할_세액": 1,
                    "지방소득세_납부_할_세액": 1,
                    "권장수수료": 1,
                },
                "error": None,
            },
        }

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    with pytest.raises(ValueError, match="total_business_expense_amount must be greater than base business expense"):
        browser_control.send_bookkeeping_expected_tax_amount(
            bot_id="sender-01",
            payload={
                "tax_doc_id": 1345836,
                "submit_account_type": "CUSTOMER",
                "total_business_expense_amount": 13_994_157,
            },
        )

    assert [call["method"] for call in calls] == ["GET"]


def test_send_bookkeeping_expected_tax_amount_marks_da_when_zero_additional_expense_is_markable(
    monkeypatch,
    tmp_path,
):
    calls = []
    monkeypatch.setenv("INCOME33_LOG_DIR", str(tmp_path))

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/tax/v1/taxdocs/1345836/expected-tax-amount/send"):
            raise AssertionError("BOOKKEEPING send must not be posted with zero additional expense")
        if url.endswith("/api/tax/v1/taxdocs/1345836/custom-type"):
            assert method == "PUT"
            assert json_body == {"customType": "다"}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {}, "error": None}}
        if url.endswith("/api/tax/v1/taxdocs/1345836/memo"):
            assert method == "POST"
            assert json_body == {"memo": "경비율 산출 총 필요경비: 13994157원"}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {}, "error": None}}

        assert "/api/tax/v1/taxdocs/1345836/expected-tax-amount/calculation/bookkeeping" in url
        query = parse_qs(urlparse(url).query)
        assert query["additionalExpenseAmount"] == ["0"]
        return {
            "ok": True,
            "status": 200,
            "json": {"ok": True, "data": {"사업소득_필요_경비": 13_994_157}, "error": None},
        }

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.send_bookkeeping_expected_tax_amount(
        bot_id="sender-01",
        payload={
            "tax_doc_id": 1345836,
            "submit_account_type": "CUSTOMER",
            "total_business_expense_amount": 13_994_157,
            "mark_custom_type_da_on_negative_additional_expense": True,
        },
    )

    assert [call["method"] for call in calls] == ["GET", "PUT", "POST"]
    assert result["skipped"] is True
    assert result["reason"] == "rate_total_not_above_newta_base_expense"
    assert result["custom_type"] == "다"
    assert result["additional_expense_amount"] == 0


def test_send_rate_based_bookkeeping_expected_tax_amount_rejects_zero_total_before_bookkeeping_post(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_fetch_required_json_data(page, *, url, headers, label):
        calls.append({"url": url, "method": "GET", "label": label})
        return {}

    def fake_calculate_rate_based_total_business_expense(**kwargs):
        return {
            "mode": "general_only",
            "total_business_expense_amount": 0,
            "eligible_expense_amount": 0,
            "rate_cap_amount": 0,
        }

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):  # pragma: no cover - must not run
        raise AssertionError("BOOKKEEPING send must not be posted when rate-based total expense is zero")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_fetch_required_json_data", fake_fetch_required_json_data)
    monkeypatch.setattr(
        browser_control,
        "_calculate_rate_based_total_business_expense",
        fake_calculate_rate_based_total_business_expense,
    )
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    with pytest.raises(ValueError, match="total_business_expense_amount must be a positive integer"):
        browser_control.send_rate_based_bookkeeping_expected_tax_amount(
            bot_id="sender-01",
            payload={"tax_doc_id": 1348249},
        )

    assert [call["method"] for call in calls] == ["GET", "GET", "GET"]


def test_rate_for_industry_code_normalizes_float_artifacts_before_flooring_percent_tenths(monkeypatch):
    monkeypatch.setitem(browser_control.SIMPLE_EXPENSE_RATES, "TEST918", 0.9179999999999999)
    monkeypatch.setitem(browser_control.SIMPLE_EXPENSE_RATES, "TEST2459", 0.2459)

    assert browser_control._rate_for_industry_code("TEST918") == browser_control.Decimal("0.918")
    assert browser_control._floor_money(1000 * browser_control._rate_for_industry_code("TEST918")) == 918
    assert browser_control._rate_for_industry_code("TEST2459") == browser_control.Decimal("0.245")


def test_operator_requested_real_estate_industry_codes_floor_to_245_percent_rate():
    requested_codes = (
        "701101",
        "701102",
        "701103",
        "701104",
        "701201",
        "701202",
        "701203",
        "701204",
        "701205",
        "701206",
        "701300",
        "701301",
        "701302",
        "701400",
        "701501",
        "701502",
        "701503",
        "701504",
    )

    assert {
        code: browser_control._rate_for_industry_code(code)
        for code in requested_codes
    } == {code: browser_control.Decimal("0.245") for code in requested_codes}


def test_send_rate_based_bookkeeping_expected_tax_amount_sets_custom_type_da_and_logs_skip(
    monkeypatch,
    tmp_path,
):
    calls = []
    monkeypatch.setenv("INCOME33_LOG_DIR", str(tmp_path))

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/1348568/business-incomes"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "summary": {
                            "sum": {"수입금액": 363914985},
                            "itemList": [
                                {
                                    "사업자번호": "232-17-02578",
                                    "업종코드": "515060",
                                    "수입금액": 358474985,
                                },
                                {
                                    "사업자번호": "000-00-00000",
                                    "업종코드": "940914",
                                    "수입금액": 5440000,
                                },
                            ],
                        }
                    },
                    "error": None,
                },
            }
        if url.endswith("/api/tax/v1/gitax/year-end-document/1348568"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "신용카드등_신용카드": [{"금액": 43017489}],
                        "신용카드등_직불카드": [{"금액": 7478370}],
                        "신용카드등_현금영수증": [{"금액": 1848805}],
                    },
                    "error": None,
                },
            }
        if url.endswith("/api/tax/v1/gitax/expenses/1348568/expenses-summary"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "list": [
                            {
                                "사업자등록번호": "232-17-02578",
                                "세금계산서": 342845869,
                                "계산서": 174610,
                                "현금영수증": 1343142,
                                "사업용_신용카드": 35785354,
                                "화물운전자_복지카드": 0,
                                "인건비": 5200000,
                                "사회보험료": 0,
                                "이자상환액": None,
                                "기부금": 0,
                                "감가상각비": None,
                            }
                        ]
                    },
                    "error": None,
                },
            }
        if url.endswith("/api/tax/v1/taxdocs/1348568/custom-type"):
            assert method == "PUT"
            assert headers["x-host"] == "GIT"
            assert json_body == {"customType": "다"}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True, "error": None}}
        assert url.endswith("/api/tax/v1/taxdocs/1348568/memo")
        assert method == "POST"
        assert headers["x-host"] == "GIT"
        assert json_body == {"memo": "경비율 산출 총 필요경비: 300657111원"}
        return {"ok": True, "status": 200, "json": {"ok": True, "data": True, "error": None}}

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.send_rate_based_bookkeeping_expected_tax_amount(
        bot_id="sender-01",
        payload={"tax_doc_id": 1348568},
    )

    assert [call["method"] for call in calls] == ["GET", "GET", "GET", "PUT", "POST"]
    assert result["skipped"] is True
    assert result["reason"] == "eligible_expense_exceeds_rate_cap"
    assert result["custom_type"] == "다"
    assert result["custom_type_status_code"] == 200
    assert result["memo_status_code"] == 200
    assert result["rate_cap_amount"] == 296817287
    assert result["eligible_expense_amount"] == 385348975
    assert result["current_step"] == "경비율 계산 패스 taxDocId=1348568 customType=다 status=200"

    skip_log = tmp_path / "bookkeeping_expense_rate_skips.jsonl"
    assert skip_log.exists()
    skip_log_text = skip_log.read_text(encoding="utf-8")
    assert '"tax_doc_id": 1348568' in skip_log_text
    assert '"custom_type": "다"' in skip_log_text
    assert "232-17-02578" not in skip_log_text
    assert "385348975" not in skip_log_text


def test_send_rate_based_bookkeeping_expected_tax_amount_marks_da_when_rate_total_below_newta_base(
    monkeypatch,
):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/1348249/business-incomes"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "summary": {
                            "sum": {"수입금액": 10_000_000},
                            "itemList": [
                                {
                                    "사업자번호": "123-45-67890",
                                    "업종코드": "515060",
                                    "수입금액": 10_000_000,
                                }
                            ],
                        }
                    },
                    "error": None,
                },
            }
        if url.endswith("/api/tax/v1/gitax/year-end-document/1348249"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {}, "error": None}}
        if url.endswith("/api/tax/v1/gitax/expenses/1348249/expenses-summary"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"list": []}, "error": None}}
        if "/api/tax/v1/taxdocs/1348249/expected-tax-amount/calculation/bookkeeping" in url:
            assert method == "GET"
            query = parse_qs(urlparse(url).query)
            assert query["additionalExpenseAmount"] == ["0"]
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": True, "data": {"사업소득_필요_경비": 9_000_000}, "error": None},
            }
        if url.endswith("/api/tax/v1/taxdocs/1348249/custom-type"):
            assert method == "PUT"
            assert headers["x-host"] == "GIT"
            assert json_body == {"customType": "다"}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True, "error": None}}
        assert url.endswith("/api/tax/v1/taxdocs/1348249/memo")
        assert method == "POST"
        assert headers["x-host"] == "GIT"
        assert json_body == {"memo": "경비율 산출 총 필요경비: 8820000원"}
        return {"ok": True, "status": 200, "json": {"ok": True, "data": True, "error": None}}

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.send_rate_based_bookkeeping_expected_tax_amount(
        bot_id="sender-01",
        payload={"tax_doc_id": 1348249},
    )

    assert [call["method"] for call in calls] == ["GET", "GET", "GET", "GET", "PUT", "POST"]
    assert result["skipped"] is True
    assert result["reason"] == "rate_total_below_newta_base_expense"
    assert result["custom_type"] == "다"
    assert result["custom_type_status_code"] == 200
    assert result["memo_status_code"] == 200
    assert result["total_business_expense_amount"] == 8_820_000
    assert result["base_business_expense_amount"] == 9_000_000
    assert result["additional_expense_amount"] == -180_000
    assert result["current_step"] == "경비율 계산 패스 taxDocId=1348249 customType=다 status=200"


def test_send_rate_based_bookkeeping_expected_tax_amounts_collects_ta_list_then_processes_each_taxdoc(
    monkeypatch,
):
    calls = []

    def fake_preview_expected_tax_send_targets(*, bot_id, payload, logger):
        calls.append(("preview", bot_id, payload))
        return {
            "ok": True,
            "status": "session_active",
            "tax_doc_ids": [1348568, 1348569],
            "count": 2,
            "current_step": "일괄세션 확인 2건",
        }

    def fake_send_rate_based_bookkeeping_expected_tax_amount(*, bot_id, payload, logger):
        calls.append(("send", bot_id, payload))
        if payload["tax_doc_id"] == 1348569:
            return {
                "ok": True,
                "status": "session_active",
                "tax_doc_id": 1348569,
                "skipped": True,
                "current_step": "경비율 계산 패스 taxDocId=1348569 customType=다 status=200",
            }
        return {
            "ok": True,
            "status": "session_active",
            "tax_doc_id": 1348568,
            "current_step": "단건 계산발송 완료 taxDocId=1348568",
        }

    monkeypatch.setattr(
        browser_control,
        "preview_expected_tax_send_targets",
        fake_preview_expected_tax_send_targets,
    )
    monkeypatch.setattr(
        browser_control,
        "send_rate_based_bookkeeping_expected_tax_amount",
        fake_send_rate_based_bookkeeping_expected_tax_amount,
    )

    base_payload = {"year": 2025, "size": 20, "force_refresh": True}
    result = browser_control.send_rate_based_bookkeeping_expected_tax_amounts(
        bot_id="sender-01",
        payload=base_payload,
    )

    assert result["ok"] is True
    assert result["sent_count"] == 1
    assert result["skipped_count"] == 1
    assert result["failed_count"] == 0
    assert result["tax_doc_ids"] == [1348568, 1348569]
    assert "일괄 경비율 장부발송 완료" in result["current_step"]

    preview_call = calls[0]
    assert preview_call[0] == "preview"
    assert preview_call[1] == "sender-01"
    assert preview_call[2]["year"] == 2025
    assert preview_call[2]["size"] == 20
    assert preview_call[2]["force_refresh"] is True
    assert preview_call[2]["workflow_filter_set"] == "REVIEW_WAITING"
    assert preview_call[2]["tax_doc_custom_type_filter"] == "가"
    assert preview_call[2]["review_type_filter"] == "NORMAL"
    assert preview_call[2]["apply_expense_rate_type_filter"] == "ALL"
    assert preview_call[2]["sort"] == "REVIEW_REQUEST_DATE_TIME"
    assert preview_call[2]["direction"] == "ASC"
    assert preview_call[2]["scan_order"] == "forward"

    assert calls[1:] == [
        (
            "send",
            "sender-01",
            {"year": 2025, "size": 20, "force_refresh": True, "tax_doc_id": 1348568},
        ),
        (
            "send",
            "sender-01",
            {"year": 2025, "size": 20, "force_refresh": True, "tax_doc_id": 1348569},
        ),
    ]


def test_preview_rate_based_bookkeeping_expected_tax_amounts_uses_review_waiting_custom_filters(monkeypatch):
    fetched_query = {}

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        if url.endswith("/api/ta/info/v1/tax-offices/simple"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": [{"id": 325}, {"id": 326}, {"id": 327}, {"id": 328}, {"id": 329}],
                },
            }

        assert "/api/tax/v1/taxdocs/filter-search" in url
        query = parse_qs(urlparse(url).query)
        fetched_query.update(query)
        return {
            "ok": True,
            "status": 200,
            "json": {
                "ok": True,
                "data": {
                    "content": [{"taxDocId": 91001}, {"taxDocId": 91002}],
                    "totalElements": 2,
                    "totalPages": 1,
                },
            },
        }

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.preview_rate_based_bookkeeping_expected_tax_amounts(
        bot_id="sender-05",
        payload={"year": 2025, "size": 20},
    )

    assert result["tax_doc_ids"] == [91001, 91002]
    assert result["count"] == 2
    assert result["current_step"] == "일괄세션 확인 2건"
    assert fetched_query["officeId"] == ["329"]
    assert fetched_query["workflowFilterSet"] == ["REVIEW_WAITING"]
    assert fetched_query["taxDocCustomTypeFilter"] == ["가"]
    assert fetched_query["reviewTypeFilter"] == ["NORMAL"]
    assert fetched_query["applyExpenseRateTypeFilter"] == ["ALL"]
    assert fetched_query["taxDocServiceCodeTypeFilter"] == ["C0"]
    assert fetched_query["year"] == ["2025"]
    assert fetched_query["sort"] == ["REVIEW_REQUEST_DATE_TIME"]
    assert fetched_query["direction"] == ["ASC"]
    assert fetched_query["page"] == ["0"]
    assert fetched_query["size"] == ["20"]


def test_send_rate_based_bookkeeping_expected_tax_amounts_keeps_manual_taxdoc_ids_mode(monkeypatch):
    calls = []

    def fail_preview(*args, **kwargs):
        raise AssertionError("preview should not be called when explicit tax_doc_ids are provided")

    def fake_send_rate_based_bookkeeping_expected_tax_amount(*, bot_id, payload, logger):
        calls.append((bot_id, payload["tax_doc_id"]))
        return {
            "ok": True,
            "status": "session_active",
            "tax_doc_id": payload["tax_doc_id"],
            "current_step": f"단건 계산발송 완료 taxDocId={payload['tax_doc_id']}",
        }

    monkeypatch.setattr(browser_control, "preview_rate_based_bookkeeping_expected_tax_amounts", fail_preview)
    monkeypatch.setattr(
        browser_control,
        "send_rate_based_bookkeeping_expected_tax_amount",
        fake_send_rate_based_bookkeeping_expected_tax_amount,
    )

    result = browser_control.send_rate_based_bookkeeping_expected_tax_amounts(
        bot_id="sender-01",
        payload={"tax_doc_ids": [2001, 2002]},
    )

    assert result["ok"] is True
    assert result["sent_count"] == 2
    assert result["skipped_count"] == 0
    assert result["failed_count"] == 0
    assert result["tax_doc_ids"] == [2001, 2002]
    assert calls == [("sender-01", 2001), ("sender-01", 2002)]


def test_refresh_page_force_reload_calls_browser_reload(monkeypatch):
    events = []

    class RefreshPage:
        url = "https://newta.3o3.co.kr/tasks/git"

        def goto(self, url, **kwargs):
            events.append(("goto", url, kwargs.get("wait_until")))
            self.url = url

        def reload(self, **kwargs):
            events.append(("reload", kwargs.get("wait_until")))

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(RefreshPage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        assert url.endswith("/api/ta/info/v1/tax-offices/simple")
        return {"ok": True, "status": 200, "json": {"ok": True, "data": [{"id": 325}]}}

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.refresh_page(bot_id="sender-01", payload={"force": True})

    assert result["status"] == "session_active"
    assert result["force"] is True
    assert events == [
        ("goto", "https://newta.3o3.co.kr/tasks/git", "domcontentloaded"),
        ("reload", "domcontentloaded"),
    ]


def test_assign_taxdocs_to_current_accountant_fetches_me_then_puts_assignment(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29201)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/ta/v1/me"):
            assert method == "GET"
            assert headers["x-host"] == "GROUND"
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        assert url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign")
        assert method == "PUT"
        assert headers["x-host"] == "GIT"
        assert json_body == {"taxAccountantId": 817, "taxDocIdList": [1358717, 1360207]}
        return {"ok": True, "status": 200, "json": {"ok": True, "data": True, "error": None}}

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.assign_taxdocs_to_current_accountant(
        bot_id="sender-01",
        tax_doc_ids=[1358717, 1360207],
        payload={},
    )

    assert [call["method"] for call in calls] == ["GET", "PUT"]
    assert result["assigned_count"] == 2
    assert result["tax_accountant_id"] == 817
    assert result["current_step"] == "잔여목록 배정 완료 2건 담당자=817 status=200"


def test_assign_taxdocs_to_current_accountant_dry_run_skips_fetch_and_put(monkeypatch):
    def _fail_fetch(*args, **kwargs):
        raise AssertionError("dry run should not fetch")

    monkeypatch.setattr(browser_control, "_browser_fetch_json", _fail_fetch)

    result = browser_control.assign_taxdocs_to_current_accountant(
        bot_id="sender-01",
        tax_doc_ids=[1001, 1002],
        payload={"dry_run": True},
    )

    assert result["dry_run"] is True
    assert result["assigned_count"] == 2
    assert result["current_step"] == "잔여목록 배정 dry-run 2건"


def test_submit_tax_reports_assigns_then_applies_minus_amount_corrections(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("INCOME33_LOG_DIR", str(tmp_path))
    stale_log_path = tmp_path / "tax_report_submit_responses.jsonl"
    stale_summary_path = tmp_path / "tax_report_submit_failures.txt"
    stale_log_path.write_text(
        browser_control.json.dumps({"tax_doc_id": 10, "stage": "minus_amount_correction", "old": True}, ensure_ascii=False)
        + "\n"
        + browser_control.json.dumps({"tax_doc_id": 99, "stage": "minus_amount_correction", "old": True}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    stale_summary_path.write_text(
        "2026-01-01T00:00:00+00:00 | taxDocId=10 | 음수항목 보정 실패 | status=500 | reason=old | customType=미설정 | bot=reporter-01 | run=old\n"
        "2026-01-01T00:00:00+00:00 | taxDocId=99 | 음수항목 보정 실패 | status=500 | reason=old | customType=미설정 | bot=reporter-01 | run=old\n",
        encoding="utf-8",
    )

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/ta/v1/me"):
            assert method == "GET"
            assert headers["x-host"] == "GROUND"
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            assert method == "PUT"
            assert headers["x-host"] == "GIT"
            assert json_body == {"taxAccountantId": 817, "taxDocIdList": [10, 11]}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}

        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/10/business-incomes"):
            assert method == "GET"
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "calculationType": "BOOKKEEPING",
                        "summary": {
                            "itemList": [
                                {"사업자번호": "000-00-00000"},
                                {"사업자번호": "123-45-67890"},
                            ]
                        }
                    },
                },
            }
        if url.endswith("businessNumber=000-00-00000&businessIncomeType=PERSONAL"):
            assert method == "POST"
            return {
                "ok": False,
                "status": 400,
                "json": {"ok": False, "error": {"message": "총 필요경비에 음수항목이 존재하지 않습니다."}},
            }
        if url.endswith("businessNumber=123-45-67890&businessIncomeType=BUSINESS"):
            assert method == "POST"
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}

        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/11/business-incomes"):
            assert method == "GET"
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "calculationType": "BOOKKEEPING",
                        "summary": {
                            "itemList": [
                                {"사업자번호": "222-22-22222"},
                            ]
                        }
                    },
                },
            }
        if url.endswith("businessNumber=222-22-22222&businessIncomeType=BUSINESS"):
            return {"ok": False, "status": 500, "json": {"ok": False, "error": {"message": "temporary failure"}}}

        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [11, 10]},
    )

    assert [call["url"] for call in calls] == [
        "https://ta-gw.3o3.co.kr/api/ta/v1/me",
        "https://ta-gw.3o3.co.kr/api/tax/v1/gitax/taxdocs/tax-accountants/assign",
        "https://ta-gw.3o3.co.kr/api/tax/v1/gitax/gross-incomes-prepaid-tax/10/business-incomes",
        "https://ta-gw.3o3.co.kr/api/tax/v1/gitax/bookkeeping/10/minus-amount/correction?businessNumber=000-00-00000&businessIncomeType=PERSONAL",
        "https://ta-gw.3o3.co.kr/api/tax/v1/gitax/bookkeeping/10/minus-amount/correction?businessNumber=123-45-67890&businessIncomeType=BUSINESS",
        "https://ta-gw.3o3.co.kr/api/tax/v1/gitax/gross-incomes-prepaid-tax/11/business-incomes",
        "https://ta-gw.3o3.co.kr/api/tax/v1/gitax/bookkeeping/11/minus-amount/correction?businessNumber=222-22-22222&businessIncomeType=BUSINESS",
    ]
    assert result["attempted_count"] == 2
    assert result["success_count"] == 1
    assert result["skipped_count"] == 1
    assert result["failed_count"] == 1
    assert result["tax_doc_ids"] == [10, 11]
    assert result["assigned_count"] == 2
    assert result["tax_accountant_id"] == 817
    assert result["status"] == "manual_required"
    assert result["results"][0]["status"] == "completed"
    assert result["results"][0]["business_numbers"] == ["000-00-00000", "123-45-67890"]
    assert result["results"][1]["status"] == "skipped"
    assert result["results"][1]["stage"] == "minus_amount_correction"
    assert result["failures"][0]["tax_doc_id"] == 11
    assert result["failures"][0]["stage"] == "minus_amount_correction"

    log_lines = [browser_control.json.loads(line) for line in stale_log_path.read_text(encoding="utf-8").splitlines()]
    assert [(line["tax_doc_id"], line["stage"]) for line in log_lines] == [
        (99, "minus_amount_correction"),
        (11, "minus_amount_correction"),
    ]
    assert log_lines[1]["response_json"]["error"]["message"] == "temporary failure"
    assert "access-token" not in stale_log_path.read_text(encoding="utf-8")

    summary_lines = stale_summary_path.read_text(encoding="utf-8").splitlines()
    assert "taxDocId=10" not in "\n".join(summary_lines)
    assert "taxDocId=99" in summary_lines[0]
    assert (
        "taxDocId=11 | 음수항목 보정 실패 | status=500 | reason=temporary failure | "
        "taxDocCustomTypeFilter=ALL | customType=미설정"
    ) in summary_lines[1]


def test_submit_tax_reports_skips_minus_amount_for_estimate_calculation_type(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "json_body": json_body})
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            assert json_body == {"taxAccountantId": 817, "taxDocIdList": [12]}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/12/business-incomes"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "calculationType": "ESTIMATE",
                        "summary": {"itemList": [{"사업자번호": "123-45-67890"}]},
                    },
                },
            }
        if "/minus-amount/correction" in url:
            raise AssertionError("ESTIMATE calculationType must not call minus-amount correction")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(bot_id="reporter-01", payload={"tax_doc_ids": [12]})

    assert result["ok"] is True
    assert result["success_count"] == 1
    assert result["failed_count"] == 0
    assert result["results"][0]["status"] == "completed"
    assert result["results"][0]["calculation_type"] == "ESTIMATE"
    assert result["results"][0]["correction_count"] == 0
    assert result["results"][0]["correction_skipped_reason"] == "calculation_type_estimate"
    assert not any("/minus-amount/correction" in call["url"] for call in calls)


def test_submit_tax_reports_marks_business_income_lookup_failure_and_continues(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append(url)
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/20/business-incomes"):
            return {"ok": False, "status": 503, "json": None, "fetch_error": "network timeout"}
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/21/business-incomes"):
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": True, "data": {"summary": {"itemList": [{"사업자번호": "333-33-33333"}]}}},
            }
        if url.endswith("businessNumber=333-33-33333&businessIncomeType=BUSINESS"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [20, 21]},
    )

    assert result["attempted_count"] == 2
    assert result["success_count"] == 1
    assert result["failed_count"] == 1
    assert result["failures"][0]["tax_doc_id"] == 20
    assert result["failures"][0]["stage"] == "business_incomes"
    assert result["failures"][0]["failure_reason"] == "fetch_error=network timeout"


def test_submit_tax_reports_one_click_polls_until_success_without_second_start(monkeypatch):
    calls = []
    status_responses = ["IN_PROGRESS"]

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/ta/v1/me"):
            assert headers["x-host"] == "GROUND"
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            assert method == "PUT"
            assert headers["x-host"] == "GIT"
            assert json_body == {"taxAccountantId": 817, "taxDocIdList": [3001]}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/3001/business-incomes"):
            assert method == "GET"
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "calculationType": "BOOKKEEPING",
                        "applyExpenseRateType": "SIMPLIFIED_EXPENSE_RATE",
                        "summary": {"itemList": [{"사업자번호": "123-45-67890"}]},
                    },
                },
            }
        if "/minus-amount/correction" in url:
            raise AssertionError("SIMPLIFIED_EXPENSE_RATE taxdoc must not call minus-amount correction")

        assert headers == {
            "accept": "application/json, text/plain, */*",
            "x-host": "GIT",
            "x-web-path": "https://newta.3o3.co.kr/git/submit",
        }
        if url.endswith("/api/tax/v1/gitax/submit/3001/submit-category"):
            raise AssertionError("SIMPLIFIED_EXPENSE_RATE taxdoc must go directly to ta-submit after tax guard")
        if "/api/tax/v1/gitax/taxdocs/" in url and url.endswith("/submits/summary"):
            assert method == "GET"
            return _one_click_summary_response()
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit"):
            assert method == "PUT"
            assert json_body == {"submitUserType": "APP_USER"}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit/status"):
            assert method == "GET"
            status = status_responses.pop(0)
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {"submitUserType": "APP_USER", "status": status, "errorMessage": None},
                },
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [3001], "one_click_submit": True, "poll_interval_sec": 0, "poll_timeout_sec": 1},
    )

    assert result["ok"] is True
    assert result["mode"] == "one_click_submit"
    assert result["success_count"] == 0
    assert result["in_progress_count"] == 1
    assert result["failed_count"] == 0
    assert result["current_step"].startswith("신고제출 완료 성공=0건 진행중=1건")
    assert result["results"][0]["submit_category"] == "ESTIMATE_OR_SIMPLIFIED_EXPENSE_RATE"
    assert result["results"][0]["status"] == "in_progress"
    assert result["results"][0]["final_status"] == "IN_PROGRESS"
    assert result["results"][0]["poll_count"] == 1
    assert sum(1 for call in calls if call["method"] == "PUT" and call["url"].endswith("/ta-submit")) == 1
    assert len([call for call in calls if call["url"].endswith("/ta-submit/status")]) == 1


def test_submit_tax_reports_one_click_summary_estimate_submits_before_business_income_and_category(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            assert method == "PUT"
            assert json_body == {"taxAccountantId": 817, "taxDocIdList": [3001]}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/3001/submits/summary"):
            assert method == "GET"
            response = _one_click_summary_response()
            response["json"]["data"]["계산방법"] = "ESIMATE"
            return response
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/3001/business-incomes"):
            raise AssertionError("summary 계산방법이 ESTIMATE/ESIMATE이면 business-incomes 전에 신고후보가 되어야 함")
        if url.endswith("/api/tax/v1/gitax/submit/3001/submit-category"):
            raise AssertionError("summary 계산방법이 ESTIMATE/ESIMATE이면 submit-category 전에 ta-submit 해야 함")
        if "/minus-amount/correction" in url:
            raise AssertionError("summary 계산방법이 ESTIMATE/ESIMATE이면 음수보정 호출 금지")
        if url.endswith("/api/tax/v1/taxdocs/3001/custom-type"):
            raise AssertionError("summary 계산방법이 ESTIMATE/ESIMATE이면 아 분류 호출 금지")
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit"):
            assert method == "PUT"
            assert json_body == {"submitUserType": "APP_USER"}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit/status"):
            assert method == "GET"
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": True, "data": {"submitUserType": "APP_USER", "status": "SUCCESS", "errorMessage": None}},
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [3001], "one_click_submit": True, "poll_interval_sec": 0, "poll_timeout_sec": 1},
    )

    assert result["ok"] is True
    assert result["success_count"] == 1
    assert result["failed_count"] == 0
    assert result["skipped_count"] == 0
    assert result["eligible_tax_doc_ids"] == [3001]
    assert result["results"][0]["submit_category"] == "ESTIMATE_OR_SIMPLIFIED_EXPENSE_RATE"
    assert result["results"][0]["status"] == "completed"
    summary_index = next(i for i, call in enumerate(calls) if call["url"].endswith("/submits/summary"))
    submit_index = next(i for i, call in enumerate(calls) if call["url"].endswith("/ta-submit"))
    assert summary_index < submit_index
    assert not any(call["url"].endswith("/business-incomes") for call in calls)
    assert not any(call["url"].endswith("/submit-category") for call in calls)

def test_submit_tax_reports_one_click_blocks_unfavorable_customer_tax_difference(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/3001/business-incomes"):
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": True, "data": {"calculationType": "ESTIMATE", "summary": {"itemList": []}}},
            }
        if url.endswith("/api/tax/v1/gitax/submit/3001/submit-category"):
            assert method == "GET"
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/3001/submits/summary"):
            assert method == "GET"
            return _one_click_summary_response(
                expected_national=-605_445,
                final_national=-305_445,
                expected_local=-60_544,
                final_local=-30_544,
            )
        if url.endswith("/api/tax/v1/taxdocs/3001/custom-type"):
            assert method == "PUT"
            assert headers["x-web-path"] == "https://newta.3o3.co.kr/git/summary"
            assert json_body == {"customType": "마"}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit/send/customer-waiting"):
            assert method == "POST"
            assert json_body == {
                "종합소득세_신고할세액": -305_445,
                "종합소득세_예상세액": -605_445,
                "지방소득세_신고할세액": -30_544,
                "지방소득세_예상세액": -60_544,
                "forceSubmit": False,
            }
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit"):
            raise AssertionError("unfavorable tax difference must not call final ta-submit PUT")
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit/status"):
            raise AssertionError("unfavorable tax difference must not poll submit status")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [3001], "one_click_submit": True, "poll_interval_sec": 0, "poll_timeout_sec": 1},
    )

    assert result["ok"] is True
    assert result["success_count"] == 0
    assert result["skipped_count"] == 1
    assert result["failed_count"] == 0
    assert result["unfavorable_tax_difference_skip_count"] == 1
    assert result["customer_waiting_failed_count"] == 0
    assert result["results"][0]["stage"] == "customer_tax_difference_guard"
    assert result["results"][0]["custom_type"] == "마"
    assert result["results"][0]["customer_waiting_payload"]["forceSubmit"] is False
    assert not any(call["url"].endswith("/api/tax/v1/gitax/submit/3001/ta-submit") for call in calls)


def test_submit_tax_reports_one_click_customer_waiting_failure_still_does_not_submit(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "json_body": json_body})
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/3001/business-incomes"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"calculationType": "ESTIMATE"}}}
        if url.endswith("/api/tax/v1/gitax/submit/3001/submit-category"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/3001/submits/summary"):
            return _one_click_summary_response(expected_national=10_000, final_national=20_000, expected_local=1_000, final_local=2_000)
        if url.endswith("/api/tax/v1/taxdocs/3001/custom-type"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit/send/customer-waiting"):
            return {"ok": False, "status": 500, "json": {"ok": False, "error": {"message": "WAITING_FAILED"}}}
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit"):
            raise AssertionError("customer-waiting failure must still not call final ta-submit PUT")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [3001], "one_click_submit": True, "poll_interval_sec": 0, "poll_timeout_sec": 1},
    )

    assert result["ok"] is False
    assert result["status"] == "manual_required"
    assert result["skipped_count"] == 1
    assert result["failed_count"] == 0
    assert result["unfavorable_tax_difference_skip_count"] == 1
    assert result["customer_waiting_failed_count"] == 1
    assert result["results"][0]["custom_type"] == "마"
    assert "WAITING_FAILED" in result["results"][0]["customer_waiting_error"]
    assert not any(call["url"].endswith("/api/tax/v1/gitax/submit/3001/ta-submit") for call in calls)


def test_submit_tax_reports_one_click_refund_in_progress_start_is_not_failure(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("INCOME33_LOG_DIR", str(tmp_path))

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "json_body": json_body})
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/3001/business-incomes"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "calculationType": "ESTIMATE",
                        "summary": {"itemList": [{"사업자번호": "123-45-67890"}]},
                    },
                },
            }
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/3002/business-incomes"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "calculationType": "ESTIMATE",
                        "summary": {"itemList": [{"사업자번호": "222-22-22222"}]},
                    },
                },
            }
        if "/minus-amount/correction" in url:
            raise AssertionError("ESTIMATE calculationType must not call minus-amount correction during one-click prepare")
        if url.endswith("/submit-category"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if "/api/tax/v1/gitax/taxdocs/" in url and url.endswith("/submits/summary"):
            assert method == "GET"
            return _one_click_summary_response()
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit"):
            assert method == "PUT"
            return {"ok": False, "status": 400, "json": {"ok": False, "error": {"message": "환불이 진행중입니다."}}}
        if url.endswith("/api/tax/v1/gitax/submit/3002/ta-submit"):
            assert method == "PUT"
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if url.endswith("/api/tax/v1/gitax/submit/3002/ta-submit/status"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {"submitUserType": "APP_USER", "status": "SUCCESS", "errorMessage": None},
                },
            }
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit/status"):
            raise AssertionError("refund-in-progress start response must not trigger an immediate status poll")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [3001, 3002], "one_click_submit": True, "poll_interval_sec": 0, "poll_timeout_sec": 1},
    )

    assert result["ok"] is True
    assert result["status"] == "session_active"
    assert result["success_count"] == 1
    assert result["in_progress_count"] == 1
    assert result["failed_count"] == 0
    assert result["results"][0]["tax_doc_id"] == 3001
    assert result["results"][0]["status"] == "in_progress"
    assert result["results"][0]["stage"] == "ta_submit_start"
    assert result["results"][0]["final_status"] == "REFUND_IN_PROGRESS"
    assert result["results"][0]["errorMessage"] == "환불이 진행중입니다."
    assert result["failures"] == []
    assert not (tmp_path / "tax_report_submit_responses.jsonl").exists()
    in_progress_lines = [
        browser_control.json.loads(line)
        for line in (tmp_path / "tax_report_one_click_in_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert in_progress_lines[-1]["tax_doc_id"] == 3001
    assert in_progress_lines[-1]["final_status"] == "REFUND_IN_PROGRESS"
    assert sum(1 for call in calls if call["method"] == "PUT" and call["url"].endswith("/ta-submit")) == 2
    assert not any(call["url"].endswith("/submit/3001/ta-submit/status") for call in calls)


def test_submit_tax_reports_one_click_start_failure_logs_and_batch_continues(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("INCOME33_LOG_DIR", str(tmp_path))

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "json_body": json_body})
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/3001/business-incomes"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"summary": {"itemList": []}}}}
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/3002/business-incomes"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"summary": {"itemList": []}}}}
        if url.endswith("/submit-category"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if "/api/tax/v1/gitax/taxdocs/" in url and url.endswith("/submits/summary"):
            assert method == "GET"
            return _one_click_summary_response()
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit"):
            assert method == "PUT"
            return {"ok": False, "status": 500, "json": {"ok": False, "error": {"message": "TEST_START_FAILED"}}}
        if url.endswith("/api/tax/v1/gitax/submit/3002/ta-submit"):
            assert method == "PUT"
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if url.endswith("/api/tax/v1/gitax/submit/3002/ta-submit/status"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {"submitUserType": "APP_USER", "status": "SUCCESS", "errorMessage": None},
                },
            }
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit/status"):
            raise AssertionError("start failure must not poll status")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [3001, 3002], "final_submit": True, "poll_interval_sec": 0, "poll_timeout_sec": 1},
    )

    assert result["ok"] is False
    assert result["success_count"] == 1
    assert result["failed_count"] == 1
    assert result["failures"][0]["tax_doc_id"] == 3001
    assert result["failures"][0]["stage"] == "ta_submit_start"
    assert result["failures"][0]["submit_category"] == "TA_ONECLICK"
    assert sum(1 for call in calls if call["method"] == "PUT" and call["url"].endswith("/ta-submit")) == 2
    assert not any(call["url"].endswith("/submit/3001/ta-submit/status") for call in calls)
    log_text = (tmp_path / "tax_report_submit_responses.jsonl").read_text(encoding="utf-8")
    assert "TEST_START_FAILED" in log_text
    assert "access-token" not in log_text


def test_submit_tax_reports_one_click_in_progress_is_recorded_and_moves_on(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("INCOME33_LOG_DIR", str(tmp_path))

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "json_body": json_body})
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/3001/business-incomes"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"summary": {"itemList": []}}}}
        if url.endswith("/api/tax/v1/gitax/submit/3001/submit-category"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if "/api/tax/v1/gitax/taxdocs/" in url and url.endswith("/submits/summary"):
            assert method == "GET"
            return _one_click_summary_response()
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit"):
            assert method == "PUT"
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit/status"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {"submitUserType": "APP_USER", "status": "IN_PROGRESS", "errorMessage": None},
                },
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [3001], "submit_mode": "ta-submit", "poll_interval_sec": 0, "poll_timeout_sec": 0},
    )

    assert result["ok"] is True
    assert result["status"] == "session_active"
    assert result["success_count"] == 0
    assert result["in_progress_count"] == 1
    assert result["failed_count"] == 0
    assert result["results"][0]["status"] == "in_progress"
    assert result["results"][0]["final_status"] == "IN_PROGRESS"
    assert result["results"][0]["poll_count"] == 1
    assert sum(1 for call in calls if call["method"] == "PUT" and call["url"].endswith("/ta-submit")) == 1
    assert len([call for call in calls if call["url"].endswith("/ta-submit/status")]) == 1

    in_progress_lines = [browser_control.json.loads(line) for line in (tmp_path / "tax_report_one_click_in_progress.jsonl").read_text(encoding="utf-8").splitlines()]
    assert in_progress_lines[-1]["tax_doc_id"] == 3001
    assert in_progress_lines[-1]["final_status"] == "IN_PROGRESS"
    assert in_progress_lines[-1]["run_id"] == result["run_id"]
    assert in_progress_lines[-1]["last_checked_at"]
    assert in_progress_lines[-1]["next_check_at"]


def test_submit_tax_reports_one_click_auto_fetch_targets_and_use_submit_ready_filters(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="income33.agent.browser_control")
    calls = []
    fetched_pages = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/ta/info/v1/tax-offices/simple"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": [{"id": 327}]}}
        if "/api/tax/v1/taxdocs/filter-search" in url:
            query = parse_qs(urlparse(url).query)
            fetched_pages.append(int(query["page"][0]))
            assert query["officeId"] == ["327"]
            assert query["workflowFilterSet"] == ["SUBMIT_READY"]
            assert query["taxDocCustomTypeFilter"] == ["가"]
            assert query["reviewTypeFilter"] == ["NORMAL"]
            assert query["sort"] == ["SUBMIT_REQUEST_DATE_TIME"]
            assert query["direction"] == ["ASC"]
            assert query["size"] == ["2"]
            if query["page"] == ["0"]:
                return {
                    "ok": True,
                    "status": 200,
                    "json": {
                        "ok": True,
                        "data": {"content": [{"taxDocId": 4101}, {"taxDocId": 4102}], "totalElements": 3, "totalPages": 2},
                    },
                }
            if query["page"] == ["1"]:
                return {
                    "ok": True,
                    "status": 200,
                    "json": {
                        "ok": True,
                        "data": {"content": [{"taxDocId": 4103}], "totalElements": 3, "totalPages": 2},
                    },
                }
            raise AssertionError(f"unexpected page query: {query}")
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            assert json_body == {"taxAccountantId": 817, "taxDocIdList": [4101, 4102, 4103]}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if "/api/tax/v1/gitax/gross-incomes-prepaid-tax/" in url and url.endswith("/business-incomes"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"summary": {"itemList": []}}}}
        if "/api/tax/v1/gitax/submit/" in url and url.endswith("/submit-category"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if "/api/tax/v1/gitax/taxdocs/" in url and url.endswith("/submits/summary"):
            assert method == "GET"
            return _one_click_summary_response()
        if "/api/tax/v1/gitax/submit/" in url and url.endswith("/ta-submit"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if "/api/tax/v1/gitax/submit/" in url and url.endswith("/ta-submit/status"):
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": True, "data": {"status": "IN_PROGRESS", "errorMessage": None}},
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={
            "one_click_submit": True,
            "one_click_fetch_page_size": 2,
            "max_auto_targets": 10,
            "tax_doc_custom_type_filter": "가",
        },
    )

    assert result["ok"] is True
    assert result["tax_doc_ids"] == [4101, 4102, 4103]
    assert result["attempted_count"] == 3
    assert result["in_progress_count"] == 3
    assert fetched_pages == [0, 1]
    assert result["one_click_fetch_page_size"] == 2
    assert result["auto_fetch_pages"] == [0, 1]

    joined_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "tax_report_submit_start" in joined_logs
    assert "tax_doc_custom_type_filter=가" in joined_logs
    assert "tax_report_one_click_submit_category" in joined_logs
    assert "submit_category=TA_ONECLICK" in joined_logs
    in_progress_lines = [
        browser_control.json.loads(line)
        for line in (tmp_path / "tax_report_one_click_in_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert {row["tax_doc_custom_type_filter"] for row in in_progress_lines} == {"가"}


def test_submit_tax_reports_one_click_ah_filter_reprocesses_logic_before_submit_or_ah_classification(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/ta/info/v1/tax-offices/simple"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": [{"id": 327}]}}
        if "/api/tax/v1/taxdocs/filter-search" in url:
            query = parse_qs(urlparse(url).query)
            assert query["workflowFilterSet"] == ["SUBMIT_READY"]
            assert query["taxDocCustomTypeFilter"] == ["아"]
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {"content": [{"taxDocId": 6101}, {"taxDocId": 6102}], "totalElements": 2, "totalPages": 1},
                },
            }
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            assert json_body == {"taxAccountantId": 817, "taxDocIdList": [6101, 6102]}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if "/api/tax/v1/gitax/taxdocs/" in url and url.endswith("/submits/summary"):
            assert method == "GET"
            return _one_click_summary_response()
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/6101/business-incomes"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"summary": {"itemList": []}}}}
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/6102/business-incomes"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "calculationType": "BOOKKEEPING",
                        "summary": {"itemList": [{"사업자번호": "123-45-67890", "업종코드": "701101"}]},
                    },
                },
            }
        if url.endswith("/api/tax/v1/taxdocs/6102/custom-type"):
            assert method == "PUT"
            assert json_body == {"customType": "아"}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/submit/6101/submit-category"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if url.endswith("/api/tax/v1/gitax/submit/6101/ta-submit"):
            assert method == "PUT"
            assert json_body == {"submitUserType": "APP_USER"}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if url.endswith("/api/tax/v1/gitax/submit/6101/ta-submit/status"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"status": "IN_PROGRESS"}}}
        if "/api/tax/v1/gitax/submit/6102/" in url:
            raise AssertionError("blocked-industry target must stop after 아 classification, not final submit")
        if "/minus-amount/correction" in url:
            raise AssertionError("blocked-industry target must not call minus correction")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"one_click_submit": True, "tax_doc_custom_type_filter": "아"},
    )

    assert result["tax_doc_ids"] == [6101, 6102]
    assert result["attempted_count"] == 2
    assert result["in_progress_count"] == 1
    assert result["blocked_industry_skip_count"] == 1
    assert result["ah_classified_count"] == 1
    assert result["eligible_tax_doc_ids"] == [6101]
    assert "아분류=1건" in result["current_step"]
    assert any(call["url"].endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/6101/business-incomes") for call in calls)
    assert any(call["url"].endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/6102/business-incomes") for call in calls)
    assert any(call["url"].endswith("/api/tax/v1/gitax/submit/6101/ta-submit") for call in calls)
    assert not any(call["url"].endswith("/api/tax/v1/gitax/submit/6102/ta-submit") for call in calls)


def test_submit_tax_reports_one_click_manual_ids_respect_custom_type_filter(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "headers": headers, "json_body": json_body})
        if url.endswith("/api/ta/info/v1/tax-offices/simple"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": [{"id": 327}]}}
        if "/api/tax/v1/taxdocs/filter-search" in url:
            query = parse_qs(urlparse(url).query)
            assert query["taxDocCustomTypeFilter"] == ["아"]
            assert query["workflowFilterSet"] == ["SUBMIT_READY"]
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": True, "data": {"content": [{"taxDocId": 4102}], "totalElements": 1, "totalPages": 1}},
            }
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            raise AssertionError("manual taxDocId outside selected custom type must not be assigned/submitted")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [4101], "one_click_submit": True, "tax_doc_custom_type_filter": "아"},
    )

    assert result["ok"] is True
    assert result["current_step"] == "신고제출 대상 없음"
    assert result["tax_doc_ids"] == []
    assert not any(call["url"].endswith("/taxdocs/tax-accountants/assign") for call in calls)


def test_submit_tax_reports_one_click_auto_fetch_targets_without_max_limit_fetches_all_pages(monkeypatch):
    fetched_pages = []
    expected_tax_doc_ids = list(range(7001, 7251))

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        if url.endswith("/api/ta/info/v1/tax-offices/simple"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": [{"id": 327}]}}
        if "/api/tax/v1/taxdocs/filter-search" in url:
            query = parse_qs(urlparse(url).query)
            page_index = int(query["page"][0])
            fetched_pages.append(page_index)
            assert query["size"] == ["100"]
            assert query["workflowFilterSet"] == ["SUBMIT_READY"]
            assert query["taxDocCustomTypeFilter"] == ["NONE"]
            if page_index == 0:
                rows = [{"taxDocId": tax_doc_id} for tax_doc_id in expected_tax_doc_ids[:100]]
            elif page_index == 1:
                rows = [{"taxDocId": tax_doc_id} for tax_doc_id in expected_tax_doc_ids[100:200]]
            elif page_index == 2:
                rows = [{"taxDocId": tax_doc_id} for tax_doc_id in expected_tax_doc_ids[200:]]
            else:
                raise AssertionError(f"unexpected page index: {page_index}")
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "content": rows,
                        "totalElements": len(expected_tax_doc_ids),
                        "totalPages": 3,
                    },
                },
            }
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            assert json_body == {"taxAccountantId": 817, "taxDocIdList": expected_tax_doc_ids}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if "/api/tax/v1/gitax/gross-incomes-prepaid-tax/" in url and url.endswith("/business-incomes"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"summary": {"itemList": []}}}}
        if "/api/tax/v1/gitax/submit/" in url and url.endswith("/submit-category"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if "/api/tax/v1/gitax/taxdocs/" in url and url.endswith("/submits/summary"):
            assert method == "GET"
            return _one_click_summary_response()
        if "/api/tax/v1/gitax/submit/" in url and url.endswith("/ta-submit"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if "/api/tax/v1/gitax/submit/" in url and url.endswith("/ta-submit/status"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"status": "IN_PROGRESS", "errorMessage": None}}}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"one_click_submit": True, "one_click_fetch_page_size": 100},
    )

    assert result["ok"] is True
    assert result["tax_doc_ids"] == expected_tax_doc_ids
    assert result["attempted_count"] == len(expected_tax_doc_ids)
    assert result["in_progress_count"] == len(expected_tax_doc_ids)
    assert result["auto_fetch_pages"] == [0, 1, 2]
    assert result["max_auto_targets"] is None


def test_submit_tax_reports_one_click_none_auto_fetch_payload_zero_ignores_env_cap_and_fetches_all_pages(monkeypatch):
    monkeypatch.setenv("INCOME33_ONE_CLICK_MAX_AUTO_TARGETS", "200")
    fetched_pages = []
    fetched_custom_filters = []
    expected_tax_doc_ids = list(range(7301, 7551))

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        if url.endswith("/api/ta/info/v1/tax-offices/simple"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": [{"id": 327}]}}
        if "/api/tax/v1/taxdocs/filter-search" in url:
            query = parse_qs(urlparse(url).query)
            page_index = int(query["page"][0])
            fetched_pages.append(page_index)
            fetched_custom_filters.append(query["taxDocCustomTypeFilter"][0])
            assert query["size"] == ["100"]
            assert query["workflowFilterSet"] == ["SUBMIT_READY"]
            assert query["taxDocCustomTypeFilter"] == ["NONE"]
            start = page_index * 100
            rows = [{"taxDocId": tax_doc_id} for tax_doc_id in expected_tax_doc_ids[start : start + 100]]
            if page_index > 2:
                raise AssertionError(f"unexpected page index: {page_index}")
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {"content": rows, "totalElements": len(expected_tax_doc_ids), "totalPages": 3},
                },
            }
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            assert json_body == {"taxAccountantId": 817, "taxDocIdList": expected_tax_doc_ids}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if "/api/tax/v1/gitax/gross-incomes-prepaid-tax/" in url and url.endswith("/business-incomes"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"summary": {"itemList": []}}}}
        if "/api/tax/v1/gitax/submit/" in url and url.endswith("/submit-category"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if "/api/tax/v1/gitax/taxdocs/" in url and url.endswith("/submits/summary"):
            assert method == "GET"
            return _one_click_summary_response()
        if "/api/tax/v1/gitax/submit/" in url and url.endswith("/ta-submit"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if "/api/tax/v1/gitax/submit/" in url and url.endswith("/ta-submit/status"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"status": "IN_PROGRESS"}}}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"one_click_submit": True, "max_auto_targets": 0, "maxAutoTargets": 0},
    )

    assert result["ok"] is True
    assert result["tax_doc_ids"] == expected_tax_doc_ids
    assert result["attempted_count"] == len(expected_tax_doc_ids)
    assert result["auto_fetch_pages"] == [0, 1, 2]
    assert result["max_auto_targets"] is None
    assert fetched_pages == [0, 1, 2]
    assert fetched_custom_filters == ["NONE", "NONE", "NONE"]


def test_submit_tax_reports_one_click_submit_chunk_size_is_capped_to_20(monkeypatch):
    calls = []
    put_tax_doc_ids = []
    tax_doc_ids = list(range(6001, 6026))

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "json_body": json_body})
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            assert json_body == {"taxAccountantId": 817, "taxDocIdList": tax_doc_ids}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if "/api/tax/v1/gitax/gross-incomes-prepaid-tax/" in url and url.endswith("/business-incomes"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"summary": {"itemList": []}}}}
        if "/api/tax/v1/gitax/submit/" in url and url.endswith("/submit-category"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if "/api/tax/v1/gitax/taxdocs/" in url and url.endswith("/submits/summary"):
            assert method == "GET"
            return _one_click_summary_response()
        if "/api/tax/v1/gitax/submit/" in url and url.endswith("/ta-submit"):
            put_tax_doc_ids.append(int(url.split("/submit/")[1].split("/")[0]))
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if "/api/tax/v1/gitax/submit/" in url and url.endswith("/ta-submit/status"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"status": "IN_PROGRESS"}}}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": tax_doc_ids, "one_click_submit": True, "one_click_submit_batch_size": 999},
    )

    assert result["ok"] is True
    assert result["submit_chunk_size"] == 20
    assert put_tax_doc_ids == tax_doc_ids
    assert sum(1 for call in calls if call["method"] == "PUT" and call["url"].endswith("/ta-submit")) == 25


def test_submit_tax_reports_one_click_minus_amount_failure_sets_custom_type_ah_and_skips_submit(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "json_body": json_body})
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/5001/business-incomes"):
            return {
                "ok": True,
                "status": 200,
                "json": {"ok": True, "data": {"summary": {"itemList": [{"사업자번호": "123-45-67890"}]}}},
            }
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/5002/business-incomes"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"summary": {"itemList": []}}}}
        if url.endswith("bookkeeping/5001/minus-amount/correction?businessNumber=123-45-67890&businessIncomeType=BUSINESS"):
            return {"ok": False, "status": 400, "json": {"ok": False, "error": {"message": "DIFF_400"}}}
        if url.endswith("/api/tax/v1/taxdocs/5001/custom-type"):
            assert method == "PUT"
            assert json_body == {"customType": "아"}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/submit/5002/submit-category"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if "/api/tax/v1/gitax/taxdocs/" in url and url.endswith("/submits/summary"):
            assert method == "GET"
            return _one_click_summary_response()
        if url.endswith("/api/tax/v1/gitax/submit/5002/ta-submit"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if url.endswith("/api/tax/v1/gitax/submit/5002/ta-submit/status"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"status": "IN_PROGRESS"}}}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [5001, 5002], "one_click_submit": True},
    )

    assert result["failed_count"] == 1
    assert result["in_progress_count"] == 1
    assert result["failures"][0]["tax_doc_id"] == 5001
    assert result["failures"][0]["stage"] == "minus_amount_correction"
    assert result["failures"][0]["custom_type"] == "아"
    assert not any(call["url"].endswith("/api/tax/v1/gitax/submit/5001/ta-submit") for call in calls)


def test_submit_tax_reports_one_click_estimate_real_estate_code_still_submits_without_custom_type(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "json_body": json_body})
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            assert method == "PUT"
            assert json_body == {"taxAccountantId": 817, "taxDocIdList": [5201]}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/5201/business-incomes"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "calculationType": "ESTIMATE",
                        "summary": {"itemList": [{"사업자번호": "123-45-67890", "업종코드": "701101"}]},
                    },
                },
            }
        if "/minus-amount/correction" in url:
            raise AssertionError("ESTIMATE calculationType must not call minus-amount correction")
        if url.endswith("/api/tax/v1/taxdocs/5201/custom-type"):
            raise AssertionError("ESTIMATE blocked industry code must not set customType 아")
        if url.endswith("/api/tax/v1/gitax/submit/5201/submit-category"):
            raise AssertionError("ESTIMATE calculationType must submit before submit-category guard")
        if "/api/tax/v1/gitax/taxdocs/" in url and url.endswith("/submits/summary"):
            assert method == "GET"
            return _one_click_summary_response()
        if url.endswith("/api/tax/v1/gitax/submit/5201/ta-submit"):
            assert method == "PUT"
            assert json_body == {"submitUserType": "APP_USER"}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"category": "TA_ONECLICK"}}}
        if url.endswith("/api/tax/v1/gitax/submit/5201/ta-submit/status"):
            assert method == "GET"
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {"submitUserType": "APP_USER", "status": "SUCCESS", "errorMessage": None},
                },
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [5201], "one_click_submit": True, "poll_interval_sec": 0, "poll_timeout_sec": 1},
    )

    assert result["failed_count"] == 0
    assert result["skipped_count"] == 0
    assert result["blocked_industry_skip_count"] == 0
    assert result["eligible_tax_doc_ids"] == [5201]
    assert result["results"][0]["status"] == "completed"
    assert result["results"][0]["stage"] == "ta_submit_status"
    assert any(call["url"].endswith("/api/tax/v1/gitax/submit/5201/ta-submit") for call in calls)
    assert not any("/minus-amount/correction" in call["url"] for call in calls)
    assert not any(call["url"].endswith("/api/tax/v1/taxdocs/5201/custom-type") for call in calls)


def test_submit_tax_reports_one_click_blocks_submit_when_submit_category_marks_tax_amount_mismatch(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "json_body": json_body})
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            assert method == "PUT"
            assert json_body == {"taxAccountantId": 817, "taxDocIdList": [5301]}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/5301/business-incomes"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "calculationType": "BOOKKEEPING",
                        "summary": {"itemList": []},
                    },
                },
            }
        if url.endswith("/api/tax/v1/gitax/submit/5301/submit-category"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "category": "TA_ONECLICK",
                        "canSubmit": False,
                        "reason": "세액 차이로 제출할 수 없습니다.",
                    },
                },
            }
        if "/api/tax/v1/gitax/taxdocs/" in url and url.endswith("/submits/summary"):
            assert method == "GET"
            return _one_click_summary_response()
        if url.endswith("/api/tax/v1/gitax/submit/5301/ta-submit"):
            raise AssertionError("submit-category blocked case must not call ta-submit")
        if url.endswith("/api/tax/v1/gitax/submit/5301/ta-submit/status"):
            raise AssertionError("submit-category blocked case must not call ta-submit/status")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [5301], "one_click_submit": True},
    )

    assert result["failed_count"] == 1
    assert result["success_count"] == 0
    assert result["in_progress_count"] == 0
    assert result["failures"][0]["tax_doc_id"] == 5301
    assert result["failures"][0]["stage"] == "submit_category_guard"
    assert "세액 차이" in result["failures"][0]["failure_reason"]
    assert not any(call["url"].endswith("/api/tax/v1/gitax/submit/5301/ta-submit") for call in calls)


def test_submit_tax_reports_one_click_real_estate_code_sets_custom_type_ah_after_minus_amount_and_skips_submit(monkeypatch):
    calls = []

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "json_body": json_body})
        if url.endswith("/api/ta/v1/me"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"id": 817}}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/tax-accountants/assign"):
            assert method == "PUT"
            assert json_body == {"taxAccountantId": 817, "taxDocIdList": [5101]}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if url.endswith("/api/tax/v1/gitax/taxdocs/5101/submits/summary"):
            assert method == "GET"
            return _one_click_summary_response()
        if url.endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/5101/business-incomes"):
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {
                        "calculationType": "BOOKKEEPING",
                        "summary": {"itemList": [{"사업자번호": "123-45-67890", "업종코드": "701101"}]},
                    },
                },
            }
        if url.endswith("bookkeeping/5101/minus-amount/correction?businessNumber=123-45-67890&businessIncomeType=BUSINESS"):
            raise AssertionError("blocked real-estate industry code must not call minus-amount correction")
        if url.endswith("/api/tax/v1/taxdocs/5101/custom-type"):
            assert method == "PUT"
            assert json_body == {"customType": "아"}
            return {"ok": True, "status": 200, "json": {"ok": True, "data": True}}
        if "/api/tax/v1/gitax/submit/5101/" in url:
            raise AssertionError("blocked real-estate industry code must not submit")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [5101], "one_click_submit": True},
    )

    assert result["failed_count"] == 0
    assert result["skipped_count"] == 1
    assert result["blocked_industry_skip_count"] == 1
    assert result["eligible_tax_doc_ids"] == []
    assert result["results"][0]["status"] == "skipped"
    assert result["results"][0]["stage"] == "blocked_industry_code"
    assert result["results"][0]["custom_type"] == "아"
    assert result["results"][0]["blocked_industry_codes"] == ["701101"]
    custom_type_index = next(i for i, call in enumerate(calls) if call["url"].endswith("/api/tax/v1/taxdocs/5101/custom-type"))
    business_income_index = next(i for i, call in enumerate(calls) if call["url"].endswith("/api/tax/v1/gitax/gross-incomes-prepaid-tax/5101/business-incomes"))
    assert business_income_index < custom_type_index
    assert not any("/minus-amount/correction" in call["url"] for call in calls)
    assert not any("/api/tax/v1/gitax/submit/5101/" in call["url"] for call in calls)


def test_submit_tax_reports_one_click_status_check_only_uses_status_get_and_no_put(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("INCOME33_LOG_DIR", str(tmp_path))
    (tmp_path / "tax_report_one_click_in_progress.jsonl").write_text(
        browser_control.json.dumps(
            {
                "tax_doc_id": 7001,
                "run_id": "old-run-1",
                "final_status": "IN_PROGRESS",
                "last_checked_at": "2026-01-01T00:00:00+00:00",
                "next_check_at": "2026-01-01T00:01:00+00:00",
            },
            ensure_ascii=False,
        )
        + "\n"
        + browser_control.json.dumps(
            {
                "tax_doc_id": 7002,
                "run_id": "old-run-2",
                "final_status": "IN_PROGRESS",
                "last_checked_at": "2026-01-01T00:00:00+00:00",
                "next_check_at": "2026-01-01T00:01:00+00:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "json_body": json_body})
        assert method == "GET"
        assert json_body is None
        assert headers["x-host"] == "GIT"
        assert "/api/tax/v1/gitax/submit/" in url
        assert url.endswith("/ta-submit/status")
        if url.endswith("/submit/7001/ta-submit/status"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"status": "COMPLETED"}}}
        if url.endswith("/submit/7002/ta-submit/status"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"status": "IN_PROGRESS"}}}
        raise AssertionError(f"unexpected status url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"one_click_submit": True, "one_click_submit_status_check": True, "tax_doc_ids": []},
    )

    assert result["ok"] is True
    assert result["mode"] == "one_click_submit_status_check"
    assert result["tax_doc_ids"] == [7001, 7002]
    assert result["success_count"] == 1
    assert result["in_progress_count"] == 1
    assert result["failed_count"] == 0
    assert all(call["url"].endswith("/ta-submit/status") for call in calls)
    assert sum(1 for call in calls if call["url"].endswith("/ta-submit")) == 0


def test_submit_tax_reports_one_click_skips_reput_when_taxdoc_already_in_progress(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("INCOME33_LOG_DIR", str(tmp_path))
    (tmp_path / "tax_report_one_click_in_progress.jsonl").write_text(
        browser_control.json.dumps(
            {
                "tax_doc_id": 3001,
                "run_id": "old-run",
                "final_status": "IN_PROGRESS",
                "last_checked_at": "2026-01-01T00:00:00+00:00",
                "next_check_at": "2026-01-01T00:01:00+00:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_run_in_cdp_session(bot_id, payload, callback):
        return callback(FakePage(), 29301)

    def fake_browser_fetch_json(page, *, url, method="GET", headers=None, json_body=None):
        calls.append({"url": url, "method": method, "json_body": json_body})
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit/status"):
            return {"ok": True, "status": 200, "json": {"ok": True, "data": {"status": "IN_PROGRESS"}}}
        if "/api/tax/v1/gitax/taxdocs/" in url and url.endswith("/submits/summary"):
            assert method == "GET"
            return _one_click_summary_response()
        if url.endswith("/api/tax/v1/gitax/submit/3001/ta-submit"):
            raise AssertionError("must not re-put when taxdoc already in durable in-progress log")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)
    monkeypatch.setattr(browser_control, "_browser_fetch_json", fake_browser_fetch_json)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [3001], "one_click_submit": True},
    )

    assert result["ok"] is True
    assert result["in_progress_count"] == 1
    assert result["results"][0]["status"] == "in_progress"
    assert sum(1 for call in calls if call["url"].endswith("/ta-submit")) == 0
    assert len([call for call in calls if call["url"].endswith("/ta-submit/status")]) == 1
    assert all("/api/ta/v1/me" not in call["url"] for call in calls)


def test_submit_tax_reports_no_targets_returns_session_active():
    result = browser_control.submit_tax_reports(bot_id="reporter-01", payload={"tax_doc_ids": []})

    assert result["ok"] is True
    assert result["status"] == "session_active"
    assert result["attempted_count"] == 0
    assert result["success_count"] == 0
    assert result["failed_count"] == 0
    assert result["current_step"] == "국세신고 준비 대상 없음"


def test_submit_tax_reports_dry_run_does_not_post(monkeypatch):
    def _fail_fetch(*args, **kwargs):
        raise AssertionError("dry run should not fetch or post")

    monkeypatch.setattr(browser_control, "_browser_fetch_json", _fail_fetch)

    result = browser_control.submit_tax_reports(
        bot_id="reporter-01",
        payload={"tax_doc_ids": [1001, 1002], "dry_run": True},
    )

    assert result["dry_run"] is True
    assert result["attempted_count"] == 2
    assert result["current_step"] == "국세신고 준비 dry-run 2건"


def test_send_expected_tax_amounts_rejects_invalid_tax_doc_ids(monkeypatch):
    monkeypatch.setenv("INCOME33_BROWSER_CONTROL_DRY_RUN", "1")

    for bad_ids in ([0], [-1], [True]):
        try:
            browser_control.send_expected_tax_amounts(
                bot_id="sender-01",
                payload={"tax_doc_ids": bad_ids},
            )
        except ValueError as exc:
            assert "positive integers" in str(exc)
        else:  # pragma: no cover - explicit assertion branch
            raise AssertionError(f"invalid ids should fail: {bad_ids}")


def test_send_expected_tax_amounts_dry_run_does_not_post(monkeypatch):
    monkeypatch.setenv("INCOME33_BROWSER_CONTROL_DRY_RUN", "1")

    def _fail_fetch(*args, **kwargs):
        raise AssertionError("dry run should not fetch or post")

    monkeypatch.setattr(browser_control, "_browser_fetch_json", _fail_fetch)

    result = browser_control.send_expected_tax_amounts(
        bot_id="sender-01",
        payload={"tax_doc_ids": [1, 2, 3]},
    )

    assert result["dry_run"] is True
    assert result["sent_count"] == 3
    assert result["current_step"] == "계산발송 dry-run 3건"
