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

    ids = module._collect_tax_doc_ids(object(), args=_default_args())

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

    result = module._find_bookkeeping_zero_additional_expense(object(), tax_doc_ids=[1001, 1002, 1003])

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

    result = module._find_bookkeeping_zero_additional_expense(object(), tax_doc_ids=[1001])

    assert result["matches"] == []
    assert result["failures"] == [
        {
            "taxDocId": 1001,
            "status": 502,
            "responseOk": False,
            "failureReason": "upstream failed",
        }
    ]
