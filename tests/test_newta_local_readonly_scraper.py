from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "newta_local_readonly_scraper.py"
    spec = importlib.util.spec_from_file_location("newta_local_readonly_scraper", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _default_args(**overrides):
    args = argparse.Namespace(
        api_base_url="https://ta-gw.3o3.co.kr",
        auth_token="",
        cookie="",
        prompt_cookie=False,
        interactive=False,
        prompt_token=False,
        skip_auth_check=False,
        request_headers=[],
        output=None,
        export_common_business_free_reason_xlsx=False,
        free_reason_type_match="사업형태_공동사업",
        summary_masking=False,
        office_id=None,
        office_index=0,
        office_name_contains="",
        workflow_filter_set="SUBMIT_READY",
        assignment_status_filter="ALL",
        tax_doc_custom_type_filter="ALL",
        tax_doc_custom_type_filters=[],
        business_income_type_filter="ALL",
        freelancer_income_amount_type_filter="ALL",
        review_type_filter="FREE",
        submit_guide_type_filter="ALL",
        apply_expense_rate_type_filter="ALL",
        notice_type_filter="ALL",
        extra_survey_type_filter="ALL",
        expected_tax_amount_type_filter="ALL",
        free_reason_type_filter="ALL",
        refund_status_filter="ALL",
        tax_doc_service_code_type_filter="C0",
        year=2025,
        sort="SUBMIT_REQUEST_DATE_TIME",
        direction="ASC",
        page=0,
        size=20,
        max_targets=0,
        tax_doc_ids=[],
        no_list=False,
        include_summary=False,
        include_submit_status=False,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


class FakeClient:
    def __init__(self, module):
        self.module = module
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_json(self, url: str, *, headers: dict[str, str]):
        self.calls.append((url, dict(headers)))
        if url.endswith("/api/ta/v1/me"):
            return self.module.JSONResult(
                True,
                200,
                url,
                {
                    "ok": True,
                    "data": {
                        "id": 1,
                        "officeId": 327,
                        "username": "not-exported",
                        "role": "TAX_ACCOUNTANT",
                    },
                },
                "",
            )
        if url.endswith("/api/ta/info/v1/tax-offices/simple"):
            return self.module.JSONResult(True, 200, url, {"ok": True, "data": [{"id": 327, "name": "main"}]}, "")
        if "/api/tax/v1/taxdocs/filter-search" in url:
            query = parse_qs(urlparse(url).query)
            page = int(query["page"][0])
            rows_by_page = {
                0: [{"taxDocId": 101}, {"taxDocId": 102}],
                1: [{"taxDocId": 103}, {"taxDocId": 104}],
                2: [{"taxDocId": 105}],
            }
            return self.module.JSONResult(
                True,
                200,
                url,
                {"ok": True, "data": {"content": rows_by_page.get(page, []), "totalPages": 3}},
                "",
            )
        if "/api/tax/v1/taxdocs/" in url and "/summary" in url and "/submits/summary" not in url:
            tax_doc_id = int(url.split("/taxdocs/", 1)[1].split("/", 1)[0])
            reasons_by_id = {
                101: [{"freeReasonType": "사업형태_공동사업"}],
                102: [{"freeReasonType": "다른사유"}],
            }
            return self.module.JSONResult(
                True,
                200,
                url,
                {
                    "ok": True,
                    "data": {
                        "taxDocId": tax_doc_id,
                        "phoneNumber": f"010-0000-{tax_doc_id}",
                        "taxDocFreeReasonList": reasons_by_id.get(tax_doc_id, []),
                        "name": "not-exported",
                        "homeTaxAccountPassword": "not-exported",
                    },
                },
                "",
            )
        if "/submits/summary" in url:
            tax_doc_id = int(url.split("/taxdocs/", 1)[1].split("/", 1)[0])
            return self.module.JSONResult(True, 200, url, {"ok": True, "data": {"taxDocId": tax_doc_id}}, "")
        if "/ta-submit/status" in url:
            tax_doc_id = int(url.split("/submit/", 1)[1].split("/", 1)[0])
            return self.module.JSONResult(True, 200, url, {"ok": True, "data": {"taxDocId": tax_doc_id, "status": "SUCCESS"}}, "")
        raise AssertionError(url)


def test_build_auth_headers_uses_env_and_redacts_sensitive_values(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("NEWTA_AUTH_TOKEN", "env-token-secret")
    monkeypatch.setenv("NEWTA_COOKIE", "session_id=fake-local-session")

    headers = module._build_auth_headers(_default_args(request_headers=["x-device-id: abc123"]))
    redacted = module._redacted_headers(headers)

    assert headers == {
        "cookie": "session_id=fake-local-session",
        "authorization": "Bearer env-token-secret",
        "x-device-id": "abc123",
    }
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["cookie"] == "[REDACTED]"
    assert "env-token-secret" not in str(redacted)
    assert "fake-local-session" not in str(redacted)
    assert redacted["x-device-id"] == "[present:6]"


def test_read_only_client_blocks_state_changing_methods_before_network():
    module = _load_module()

    with pytest.raises(ValueError, match="state-changing method is blocked"):
        module.ReadOnlyAPIClient().request_json("PUT", "https://example.invalid/ta-submit", headers={})


def test_collect_filter_search_paginates_and_honors_max_targets():
    module = _load_module()
    client = FakeClient(module)
    args = _default_args(max_targets=3)

    result = module.collect_filter_search(
        client,
        args=args,
        auth_headers={"authorization": "Bearer test-token"},
        office_id=327,
        custom_type="아",
    )

    assert result["taxDocIds"] == [101, 102, 103]
    assert result["pages"] == [0, 1]
    assert result["truncatedByMaxTargets"] is True
    filter_calls = [url for url, _headers in client.calls if "filter-search" in url]
    assert [parse_qs(urlparse(url).query)["taxDocCustomTypeFilter"][0] for url in filter_calls] == ["아", "아"]


def test_run_scrape_explicit_tax_doc_ids_fetches_summary_and_status_without_list():
    module = _load_module()
    client = FakeClient(module)
    args = _default_args(
        tax_doc_ids=["1001,1002"],
        no_list=True,
        include_summary=True,
        include_submit_status=True,
    )

    result = module.run_scrape(client, args=args, auth_headers={"authorization": "Bearer test-token"})

    assert result["taxDocIds"] == [1001, 1002]
    assert result["meta"]["summaryCount"] == 2
    assert result["meta"]["submitStatusCount"] == 2
    assert result["filterSearch"] == []
    called_urls = [url for url, _headers in client.calls]
    assert not any("filter-search" in url for url in called_urls)
    assert not any("tax-offices/simple" in url for url in called_urls)


def test_run_scrape_auto_list_resolves_office_from_me_and_keeps_auth_value_out_of_meta():
    module = _load_module()
    client = FakeClient(module)
    args = _default_args(tax_doc_custom_type_filters=["아,마"], max_targets=2)

    result = module.run_scrape(client, args=args, auth_headers={"authorization": "Bearer raw-secret-token"})

    assert result["taxDocIds"] == [101, 102]
    assert result["meta"]["authCheck"]["officeId"] == 327
    assert result["meta"]["selectedOffice"] == {"id": 327, "officeId": 327, "selectedBy": "me"}
    assert result["meta"]["customTypes"] == ["아", "마"]
    assert result["meta"]["authHeadersRedacted"] == {"authorization": "[REDACTED]"}
    assert "raw-secret-token" not in str(result["meta"])
    assert "not-exported" not in str(result["meta"])
    called_urls = [url for url, _headers in client.calls]
    assert any(url.endswith("/api/ta/v1/me") for url in called_urls)
    assert not any("tax-offices/simple" in url for url in called_urls)
    filter_calls = [url for url in called_urls if "filter-search" in url]
    assert {parse_qs(urlparse(url).query)["officeId"][0] for url in filter_calls} == {"327"}


def test_common_business_free_reason_export_keeps_only_requested_fields():
    module = _load_module()
    client = FakeClient(module)
    args = _default_args(tax_doc_ids=["101,102"], no_list=True)

    result = module.collect_common_business_free_reason_rows(
        client,
        args=args,
        auth_headers={"cookie": "session_id=fake-local-session"},
    )

    assert result["matches"] == [{"taxDocId": 101, "phoneNumber": "010-0000-101"}]
    assert result["meta"]["rawProfileSummariesStored"] is False
    assert result["meta"]["matchedCount"] == 1
    assert "not-exported" not in str(result)
    summary_urls = [url for url, _headers in client.calls if "/api/tax/v1/taxdocs/" in url and "/summary" in url]
    assert len(summary_urls) == 2
    assert parse_qs(urlparse(summary_urls[0]).query) == {"isMasking": ["false"]}


def test_common_business_free_reason_xlsx_contains_requested_columns(tmp_path):
    module = _load_module()
    output_path = tmp_path / "matches.xlsx"

    module.write_common_business_free_reason_xlsx(
        output_path,
        [{"taxDocId": 101, "phoneNumber": "010-0000-0101"}],
    )

    assert output_path.exists()
    with zipfile.ZipFile(output_path) as archive:
        worksheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")

    assert "taxDocId" in worksheet_xml
    assert "phoneNumber" in worksheet_xml
    assert "<v>101</v>" in worksheet_xml
    assert "010-0000-0101" in worksheet_xml


def test_common_business_phone_export_wrapper_help_is_executable():
    script_path = Path(__file__).resolve().parents[1] / "tools" / "newta_common_business_phone_export.sh"

    assert os.access(script_path, os.X_OK)
    completed = subprocess.run(
        [str(script_path), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "officeId=auto from GET /api/ta/v1/me" in completed.stdout
    assert "page size=20" in completed.stdout
    assert "max targets=0 (all pages)" in completed.stdout
    assert "Never calls POST/PUT/PATCH/DELETE" in completed.stdout
