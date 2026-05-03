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
        assert "total_business_expense_amount must be greater than or equal to base business expense" in str(exc)
    else:  # pragma: no cover - explicit assertion branch
        raise AssertionError("expense below base should fail")


def test_rate_for_industry_code_rounds_generated_float_artifacts(monkeypatch):
    monkeypatch.setitem(browser_control.SIMPLE_EXPENSE_RATES, "TEST918", 0.9179999999999999)

    assert browser_control._rate_for_industry_code("TEST918") == browser_control.Decimal("0.918")
    assert browser_control._floor_money(1000 * browser_control._rate_for_industry_code("TEST918")) == 918


def test_operator_requested_real_estate_industry_codes_use_2452_percent_rate():
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
    } == {code: browser_control.Decimal("0.2452") for code in requested_codes}


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

    result = browser_control.send_rate_based_bookkeeping_expected_tax_amounts(
        bot_id="sender-01",
        payload={"year": 2025, "size": 20, "force_refresh": True},
    )

    assert result["ok"] is True
    assert result["sent_count"] == 1
    assert result["skipped_count"] == 1
    assert result["failed_count"] == 0
    assert result["tax_doc_ids"] == [1348568, 1348569]
    assert "일괄 경비율 장부발송 완료" in result["current_step"]
    assert calls == [
        ("preview", "sender-01", {"year": 2025, "size": 20, "force_refresh": True}),
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

    monkeypatch.setattr(browser_control, "_run_in_cdp_session", fake_run_in_cdp_session)

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
    assert "taxDocId=11 | 음수항목 보정 실패 | status=500 | reason=temporary failure | customType=미설정" in summary_lines[1]


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
