from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "find_bookkeeping_zero_additional_expense.py"
    spec = importlib.util.spec_from_file_location("find_bookkeeping_zero_additional_expense", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _default_args(**overrides):
    args = argparse.Namespace(
        office_id=327,
        workflow_filter_set="EXPECTED_SENT",
        assignment_status_filter="ALL",
        tax_doc_custom_type_filter="가",
        tax_doc_custom_type_filters=None,
        business_income_type_filter="ALL",
        freelancer_income_amount_type_filter="ALL",
        review_type_filter="NORMAL",
        submit_guide_type_filter="ALL",
        apply_expense_rate_type_filter="ALL",
        notice_type_filter="ALL",
        extra_survey_type_filter="ALL",
        expected_tax_amount_type_filter="ALL",
        free_reason_type_filter="ALL",
        refund_status_filter="ALL",
        tax_doc_service_code_type_filter="C0",
        year=2025,
        sort="REVIEW_REQUEST_DATE_TIME",
        direction="DESC",
        page=0,
        size=2,
        max_targets=0,
        cdp_endpoint="http://127.0.0.1:9222",
        direct_get=False,
        no_cdp=False,
        headless=False,
        login_wait_sec=600,
        auth_token="",
        request_headers=[],
        output=None,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_collect_tax_doc_ids_paginates_all_pages(monkeypatch):
    module = _load_module()
    called_pages: list[int] = []

    def fake_request_json(context, *, url, headers):
        query = parse_qs(urlparse(url).query)
        page = int(query["page"][0])
        called_pages.append(page)
        rows_by_page = {
            0: [{"taxDocId": 101}, {"taxDocId": 102}],
            1: [{"taxDocId": 103}, {"taxDocId": 104}],
            2: [{"taxDocId": 105}],
        }
        return {
            "ok": True,
            "status": 200,
            "json": {
                "ok": True,
                "data": {
                    "content": rows_by_page.get(page, []),
                    "totalElements": 5,
                    "totalPages": 3,
                },
            },
            "text": "",
        }

    monkeypatch.setattr(module, "_request_json", fake_request_json)

    ids = module._collect_tax_doc_ids(object(), args=_default_args(), tax_doc_custom_type_filter="가")

    assert ids == [101, 102, 103, 104, 105]
    assert called_pages == [0, 1, 2]


def test_find_bookkeeping_zero_additional_expense_tracks_failures(monkeypatch):
    module = _load_module()

    def fake_request_json(context, *, url, headers):
        if "/taxdocs/1001/" in url:
            return {
                "ok": False,
                "status": 500,
                "json": {"ok": False, "error": {"message": "boom"}},
                "text": "boom",
            }
        if "/taxdocs/1002/" in url:
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {"calculationType": "BOOKKEEPING", "additionalExpenseAmount": 0},
                },
                "text": "",
            }
        if "/taxdocs/1003/" in url:
            return {
                "ok": True,
                "status": 200,
                "json": {
                    "ok": True,
                    "data": {"calculationType": "BOOKKEEPING", "additionalExpenseAmount": 10},
                },
                "text": "",
            }
        raise AssertionError(url)

    monkeypatch.setattr(module, "_request_json", fake_request_json)

    result = module._find_bookkeeping_zero_additional_expense(
        object(),
        tax_doc_ids=[1001, 1002, 1003],
        tax_doc_custom_type_filter="자",
    )

    assert [item["taxDocId"] for item in result["matches"]] == [1002]
    assert [item["taxDocId"] for item in result["failures"]] == [1001]


def test_find_bookkeeping_zero_additional_expense_handles_non_dict_failure_body(monkeypatch):
    module = _load_module()

    def fake_request_json(context, *, url, headers):
        return {
            "ok": False,
            "status": 502,
            "json": ["bad gateway"],
            "text": "upstream failed",
        }

    monkeypatch.setattr(module, "_request_json", fake_request_json)

    result = module._find_bookkeeping_zero_additional_expense(
        object(),
        tax_doc_ids=[1001],
        tax_doc_custom_type_filter="가",
    )

    assert result["matches"] == []
    assert result["failures"] == [
        {
            "taxDocId": 1001,
            "customType": "가",
            "status": 502,
            "responseOk": False,
            "failureReason": "upstream failed",
        }
    ]


def test_collect_tax_doc_ids_applies_auth_headers_and_custom_type(monkeypatch):
    module = _load_module()
    captured: dict[str, object] = {}

    def fake_request_json(context, *, url, headers):
        query = parse_qs(urlparse(url).query)
        captured["customType"] = query["taxDocCustomTypeFilter"][0]
        captured["authorization"] = headers.get("authorization")
        captured["x-device-id"] = headers.get("x-device-id")
        return {
            "ok": True,
            "status": 200,
            "json": {
                "ok": True,
                "data": {
                    "content": [{"taxDocId": 999}],
                    "totalPages": 1,
                },
            },
            "text": "",
        }

    monkeypatch.setattr(module, "_request_json", fake_request_json)

    ids = module._collect_tax_doc_ids(
        object(),
        args=_default_args(),
        tax_doc_custom_type_filter="자",
        auth_headers={"authorization": "Bearer token-123", "x-device-id": "dev-1"},
    )

    assert ids == [999]
    assert captured == {
        "customType": "자",
        "authorization": "Bearer token-123",
        "x-device-id": "dev-1",
    }


def test_build_auth_headers_normalizes_token_and_custom_headers():
    module = _load_module()

    args = _default_args(
        auth_token="token-raw",
        request_headers=["X-Device-Id: abc", "x-trace-id: 123"],
    )

    headers = module._build_auth_headers(args)

    assert headers == {
        "authorization": "Bearer token-raw",
        "x-device-id": "abc",
        "x-trace-id": "123",
    }


def test_parse_repeated_custom_types_handles_csv_and_spaces():
    module = _load_module()

    parsed = module._parse_repeated_custom_types(["가, 자", "자", "  ", "나"])

    assert parsed == ["가", "자", "자", "나"]


def test_direct_get_mode_uses_auth_headers_without_launching_browser(monkeypatch, tmp_path):
    module = _load_module()
    output_path = tmp_path / "result.json"
    calls: dict[str, object] = {}

    class ExplodingPlaywright:
        def __enter__(self):
            raise AssertionError("direct GET mode must not start Playwright/browser")

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_collect(context, *, args, tax_doc_custom_type_filter, auth_headers=None):
        calls["context_type"] = type(context).__name__
        calls["auth_headers"] = auth_headers
        calls["custom_type"] = tax_doc_custom_type_filter
        return [1002]

    def fake_find(context, *, tax_doc_ids, tax_doc_custom_type_filter, auth_headers=None):
        return {
            "matches": [
                {
                    "taxDocId": tax_doc_ids[0],
                    "customType": tax_doc_custom_type_filter,
                    "calculationType": "BOOKKEEPING",
                    "additionalExpenseAmount": 0,
                    "baseInfo": {"calculationType": "BOOKKEEPING", "additionalExpenseAmount": 0},
                }
            ],
            "failures": [],
            "attemptedCount": 1,
        }

    monkeypatch.setattr(module, "sync_playwright", lambda: ExplodingPlaywright())
    monkeypatch.setattr(module, "_is_logged_in", lambda context, *, auth_headers=None: True)
    monkeypatch.setattr(module, "_collect_tax_doc_ids", fake_collect)
    monkeypatch.setattr(module, "_find_bookkeeping_zero_additional_expense", fake_find)
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: _default_args(
            direct_get=True,
            auth_token="token-raw",
            output=output_path,
        ),
    )

    assert module.main() == 0
    assert calls == {
        "context_type": "_DirectAPIContext",
        "auth_headers": {"authorization": "Bearer token-raw"},
        "custom_type": "가",
    }
    assert output_path.exists()
