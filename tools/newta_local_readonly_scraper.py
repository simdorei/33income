#!/usr/bin/env python3
"""Local read-only NewTA scraper for operator-side diagnostics.

This tool intentionally supports GET-only collection.  It must not be used as a
submitter or a Control Tower command client.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from xml.sax.saxutils import escape as xml_escape

TA_API_BASE = "https://ta-gw.3o3.co.kr"
SENSITIVE_HEADER_TOKENS = ("authorization", "cookie", "token", "secret", "x-auth")
READ_ONLY_METHODS = {"GET"}


class JSONResult:
    def __init__(self, ok: bool, status: int, url: str, json_body: Any, text: str) -> None:
        self.ok = ok
        self.status = status
        self.url = url
        self.json_body = json_body
        self.text = text

    def as_record(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "url": self.url,
            "json": self.json_body,
        }


class ReadOnlyAPIClient:
    def request_json(self, method: str, url: str, *, headers: dict[str, str]) -> JSONResult:
        normalized_method = method.strip().upper()
        if normalized_method not in READ_ONLY_METHODS:
            raise ValueError(f"state-changing method is blocked in local scraper: {normalized_method}")

        request = urllib.request.Request(url, headers=headers, method=normalized_method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                text = response.read().decode(charset, errors="replace")
                return JSONResult(
                    ok=200 <= response.status < 300,
                    status=response.status,
                    url=url,
                    json_body=_parse_json_or_none(text),
                    text=text,
                )
        except urllib.error.HTTPError as exc:
            charset = exc.headers.get_content_charset() if exc.headers else None
            text = exc.read().decode(charset or "utf-8", errors="replace")
            return JSONResult(
                ok=False,
                status=exc.code,
                url=url,
                json_body=_parse_json_or_none(text),
                text=text,
            )
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GET request failed url={url} error={exc.reason}") from exc

    def get_json(self, url: str, *, headers: dict[str, str]) -> JSONResult:
        return self.request_json("GET", url, headers=headers)


def _parse_json_or_none(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def _csv_tokens(values: Iterable[str] | None) -> list[str]:
    tokens: list[str] = []
    for raw in values or []:
        for token in str(raw).split(","):
            stripped = token.strip()
            if stripped:
                tokens.append(stripped)
    return tokens


def _unique_preserve_order(values: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    unique: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _parse_tax_doc_ids(values: Iterable[str] | None) -> list[int]:
    ids: list[int] = []
    for token in _csv_tokens(values):
        try:
            parsed = int(token)
        except ValueError as exc:
            raise ValueError(f"invalid taxDocId: {token!r}") from exc
        if parsed <= 0:
            raise ValueError(f"taxDocId must be positive: {token!r}")
        ids.append(parsed)
    return _unique_preserve_order(ids)


def _parse_custom_type_filters(args: argparse.Namespace) -> list[str]:
    values = _csv_tokens(getattr(args, "tax_doc_custom_type_filters", None))
    if not values:
        fallback = str(getattr(args, "tax_doc_custom_type_filter", "") or "").strip()
        values = [fallback or "NONE"]
    return _unique_preserve_order(values)


def _strip_optional_header_prefix(raw_value: str, header_name: str) -> str:
    value = raw_value.strip()
    prefix = f"{header_name.lower()}:"
    if value.lower().startswith(prefix):
        return value.split(":", 1)[1].strip()
    return value


def _token_from_args_or_env(args: argparse.Namespace) -> str:
    token = str(getattr(args, "auth_token", "") or "").strip()
    if token:
        return _strip_optional_header_prefix(token, "authorization")
    token = str(os.getenv("NEWTA_AUTH_TOKEN") or "").strip()
    if token:
        return _strip_optional_header_prefix(token, "authorization")
    if getattr(args, "prompt_token", False):
        return _strip_optional_header_prefix(getpass.getpass("NewTA Authorization token: "), "authorization")
    return ""


def _cookie_from_args_or_env(args: argparse.Namespace) -> str:
    cookie = str(getattr(args, "cookie", "") or "").strip()
    if cookie:
        return _strip_optional_header_prefix(cookie, "cookie")
    cookie = str(os.getenv("NEWTA_COOKIE") or "").strip()
    if cookie:
        return _strip_optional_header_prefix(cookie, "cookie")
    if getattr(args, "prompt_cookie", False):
        return _strip_optional_header_prefix(getpass.getpass("NewTA Cookie header value: "), "cookie")
    return ""


def _build_auth_headers(args: argparse.Namespace) -> dict[str, str]:
    headers: dict[str, str] = {}
    cookie = _cookie_from_args_or_env(args)
    if cookie:
        headers["cookie"] = cookie

    token = _token_from_args_or_env(args)
    if token:
        headers["authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"

    for raw_header in getattr(args, "request_headers", []) or []:
        if ":" not in raw_header:
            raise ValueError(f"invalid --request-header format: {raw_header!r} (expected 'Key: Value')")
        key, value = raw_header.split(":", 1)
        header_key = key.strip().lower()
        header_value = value.strip()
        if not header_key or not header_value:
            raise ValueError(f"invalid --request-header format: {raw_header!r} (expected non-empty key/value)")
        headers[header_key] = header_value
    return headers


def _redacted_headers(headers: dict[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key, value in headers.items():
        lower_key = key.lower()
        if any(token in lower_key for token in SENSITIVE_HEADER_TOKENS):
            redacted[key] = "[REDACTED]"
        else:
            redacted[key] = f"[present:{len(value)}]"
    return redacted


def _base_url(args: argparse.Namespace) -> str:
    return str(getattr(args, "api_base_url", "") or TA_API_BASE).rstrip("/")


def _url(args: argparse.Namespace, path: str, params: dict[str, Any] | None = None) -> str:
    base = _base_url(args)
    query = f"?{urlencode(params)}" if params else ""
    return f"{base}{path}{query}"


def _default_headers(*, host: str, web_path: str, auth_headers: dict[str, str]) -> dict[str, str]:
    return {
        "accept": "application/json, text/plain, */*",
        "origin": "https://newta.3o3.co.kr",
        "referer": "https://newta.3o3.co.kr/",
        "user-agent": "Mozilla/5.0 local-newta-readonly-scraper/1.0",
        "x-host": host,
        "x-web-path": web_path,
        **auth_headers,
    }


def _response_ok(result: JSONResult) -> bool:
    body = result.json_body
    if isinstance(body, dict) and body.get("ok") is False:
        return False
    return result.ok


def _extract_data(result: JSONResult) -> Any:
    body = result.json_body
    if isinstance(body, dict) and "data" in body:
        return body.get("data")
    return body


def _me_context_from_result(result: JSONResult) -> dict[str, Any]:
    data = _extract_data(result)
    context: dict[str, Any] = {
        "ok": _response_ok(result),
        "status": result.status,
        "url": result.url,
        "dataPresent": isinstance(data, dict),
    }
    if not isinstance(data, dict):
        return context

    raw_office_id = data.get("officeId")
    if raw_office_id not in (None, ""):
        context["officeId"] = int(raw_office_id)
    raw_user_id = data.get("id")
    if raw_user_id not in (None, ""):
        context["userId"] = int(raw_user_id)
    role = str(data.get("role") or "").strip()
    if role:
        context["role"] = role
    return context


def check_auth(client: Any, *, args: argparse.Namespace, auth_headers: dict[str, str]) -> dict[str, Any]:
    headers = _default_headers(host="GROUND", web_path="dashboard/default", auth_headers=auth_headers)
    result = client.get_json(_url(args, "/api/ta/v1/me"), headers=headers)
    return _me_context_from_result(result)


def _select_office(offices: list[Any], *, args: argparse.Namespace) -> dict[str, Any]:
    if not offices:
        raise RuntimeError("office lookup returned no offices")

    office_id = getattr(args, "office_id", None)
    if office_id not in (None, ""):
        parsed_office_id = int(office_id)
        for office in offices:
            if isinstance(office, dict) and int(office.get("id") or office.get("officeId") or 0) == parsed_office_id:
                return dict(office)
        return {"id": parsed_office_id, "selectedBy": "argument"}

    name_contains = str(getattr(args, "office_name_contains", "") or "").strip()
    if name_contains:
        for office in offices:
            office_text = json.dumps(office, ensure_ascii=False) if isinstance(office, dict) else str(office)
            if name_contains in office_text:
                return dict(office) if isinstance(office, dict) else {"value": office}
        raise RuntimeError(f"no office matched --office-name-contains={name_contains!r}")

    index = int(getattr(args, "office_index", 0) or 0)
    if index < 0 or index >= len(offices):
        raise RuntimeError(f"office index out of range: {index} (office_count={len(offices)})")
    selected = offices[index]
    return dict(selected) if isinstance(selected, dict) else {"value": selected}


def _office_from_me_context(me_context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(me_context, dict):
        return None
    raw_office_id = me_context.get("officeId")
    if raw_office_id in (None, ""):
        return None
    office_id = int(raw_office_id)
    return {"id": office_id, "officeId": office_id, "selectedBy": "me"}


def resolve_office(
    client: Any,
    *,
    args: argparse.Namespace,
    auth_headers: dict[str, str],
    me_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    office_id = getattr(args, "office_id", None)
    if office_id not in (None, ""):
        return {"id": int(office_id), "officeId": int(office_id), "selectedBy": "argument"}

    selected_from_me = _office_from_me_context(me_context)
    if selected_from_me is not None:
        return selected_from_me

    if not isinstance(me_context, dict) or me_context.get("skipped"):
        fresh_me_context = check_auth(client, args=args, auth_headers=auth_headers)
        selected_from_me = _office_from_me_context(fresh_me_context)
        if selected_from_me is not None:
            return selected_from_me
        if not fresh_me_context.get("ok"):
            raise RuntimeError(f"office lookup via /api/ta/v1/me failed status={fresh_me_context.get('status')}")

    headers = _default_headers(host="GROUND", web_path="dashboard/default", auth_headers=auth_headers)
    result = client.get_json(_url(args, "/api/ta/info/v1/tax-offices/simple"), headers=headers)
    if not _response_ok(result):
        raise RuntimeError(f"office lookup failed status={result.status}")
    offices = _extract_data(result)
    if not isinstance(offices, list):
        raise RuntimeError("office lookup response did not contain a list")
    selected = _select_office(offices, args=args)
    selected.setdefault("selectedBy", "lookup")
    return selected


def _office_id_from_record(office: dict[str, Any]) -> int:
    raw_id = office.get("id") or office.get("officeId")
    if raw_id is None:
        raise RuntimeError("selected office did not contain id/officeId")
    return int(raw_id)


def _filter_search_params(args: argparse.Namespace, *, office_id: int, custom_type: str, page: int) -> dict[str, Any]:
    return {
        "officeId": office_id,
        "workflowFilterSet": args.workflow_filter_set,
        "assignmentStatusFilter": args.assignment_status_filter,
        "taxDocCustomTypeFilter": custom_type,
        "businessIncomeTypeFilter": args.business_income_type_filter,
        "freelancerIncomeAmountTypeFilter": args.freelancer_income_amount_type_filter,
        "reviewTypeFilter": args.review_type_filter,
        "submitGuideTypeFilter": args.submit_guide_type_filter,
        "applyExpenseRateTypeFilter": args.apply_expense_rate_type_filter,
        "noticeTypeFilter": args.notice_type_filter,
        "extraSurveyTypeFilter": args.extra_survey_type_filter,
        "expectedTaxAmountTypeFilter": args.expected_tax_amount_type_filter,
        "freeReasonTypeFilter": args.free_reason_type_filter,
        "refundStatusFilter": args.refund_status_filter,
        "taxDocServiceCodeTypeFilter": args.tax_doc_service_code_type_filter,
        "year": args.year,
        "sort": args.sort,
        "direction": args.direction,
        "page": page,
        "size": args.size,
    }


def collect_filter_search(
    client: Any,
    *,
    args: argparse.Namespace,
    auth_headers: dict[str, str],
    office_id: int,
    custom_type: str,
) -> dict[str, Any]:
    headers = _default_headers(host="GIT", web_path="https://newta.3o3.co.kr/tasks/git", auth_headers=auth_headers)
    page = int(args.page)
    size = int(args.size)
    max_targets = int(getattr(args, "max_targets", 0) or 0)
    limit = max_targets if max_targets > 0 else None
    total_pages: int | None = None
    rows: list[dict[str, Any]] = []
    ids: list[int] = []
    seen_ids: set[int] = set()
    requested_pages: list[int] = []

    while True:
        params = _filter_search_params(args, office_id=office_id, custom_type=custom_type, page=page)
        result = client.get_json(_url(args, "/api/tax/v1/taxdocs/filter-search", params), headers=headers)
        requested_pages.append(page)
        if not _response_ok(result):
            raise RuntimeError(f"filter-search failed customType={custom_type} page={page} status={result.status}")

        data = _extract_data(result)
        content = data.get("content") if isinstance(data, dict) else []
        content = content if isinstance(content, list) else []
        for row in content:
            if not isinstance(row, dict):
                continue
            rows.append(row)
            raw_tax_doc_id = row.get("taxDocId") or row.get("id")
            try:
                tax_doc_id = int(raw_tax_doc_id)
            except (TypeError, ValueError):
                continue
            if tax_doc_id in seen_ids:
                continue
            seen_ids.add(tax_doc_id)
            ids.append(tax_doc_id)
            if limit is not None and len(ids) >= limit:
                return {
                    "customType": custom_type,
                    "pages": requested_pages,
                    "rows": rows,
                    "taxDocIds": ids,
                    "truncatedByMaxTargets": True,
                }

        raw_total_pages = data.get("totalPages") if isinstance(data, dict) else None
        if total_pages is None and raw_total_pages is not None:
            try:
                total_pages = int(raw_total_pages)
            except (TypeError, ValueError):
                total_pages = None

        if total_pages is not None:
            if total_pages <= 0 or page >= total_pages - 1:
                break
        elif len(content) < size:
            break
        page += 1

    return {
        "customType": custom_type,
        "pages": requested_pages,
        "rows": rows,
        "taxDocIds": ids,
        "truncatedByMaxTargets": False,
    }


def fetch_summaries(
    client: Any,
    *,
    args: argparse.Namespace,
    auth_headers: dict[str, str],
    tax_doc_ids: list[int],
) -> list[dict[str, Any]]:
    headers = _default_headers(host="GIT", web_path="https://newta.3o3.co.kr/git/summary", auth_headers=auth_headers)
    records: list[dict[str, Any]] = []
    for tax_doc_id in tax_doc_ids:
        result = client.get_json(
            _url(args, f"/api/tax/v1/gitax/taxdocs/{tax_doc_id}/submits/summary"),
            headers=headers,
        )
        records.append({"taxDocId": tax_doc_id, **result.as_record()})
    return records


def fetch_submit_statuses(
    client: Any,
    *,
    args: argparse.Namespace,
    auth_headers: dict[str, str],
    tax_doc_ids: list[int],
) -> list[dict[str, Any]]:
    headers = _default_headers(host="GIT", web_path="https://newta.3o3.co.kr/git/submit", auth_headers=auth_headers)
    records: list[dict[str, Any]] = []
    for tax_doc_id in tax_doc_ids:
        result = client.get_json(
            _url(args, f"/api/tax/v1/gitax/submit/{tax_doc_id}/ta-submit/status"),
            headers=headers,
        )
        records.append({"taxDocId": tax_doc_id, **result.as_record()})
    return records


def _profile_summary_params(args: argparse.Namespace) -> dict[str, str]:
    return {"isMasking": "true" if getattr(args, "summary_masking", False) else "false"}


def fetch_profile_summary(
    client: Any,
    *,
    args: argparse.Namespace,
    auth_headers: dict[str, str],
    tax_doc_id: int,
) -> JSONResult:
    headers = _default_headers(host="GIT", web_path="https://newta.3o3.co.kr/git/summary", auth_headers=auth_headers)
    return client.get_json(
        _url(args, f"/api/tax/v1/taxdocs/{tax_doc_id}/summary", _profile_summary_params(args)),
        headers=headers,
    )


def _free_reason_types(summary_data: Any) -> list[str]:
    if not isinstance(summary_data, dict):
        return []
    raw_reasons = summary_data.get("taxDocFreeReasonList")
    if not isinstance(raw_reasons, list):
        return []

    reason_types: list[str] = []
    for raw_reason in raw_reasons:
        if not isinstance(raw_reason, dict):
            continue
        reason_type = str(raw_reason.get("freeReasonType") or "").strip()
        if reason_type:
            reason_types.append(reason_type)
    return _unique_preserve_order(reason_types)


def _auth_check_result(client: Any, *, args: argparse.Namespace, auth_headers: dict[str, str]) -> dict[str, Any]:
    if getattr(args, "skip_auth_check", False):
        return {"ok": True, "skipped": True}
    return check_auth(client, args=args, auth_headers=auth_headers)


def collect_common_business_free_reason_rows(
    client: Any,
    *,
    args: argparse.Namespace,
    auth_headers: dict[str, str],
) -> dict[str, Any]:
    if not auth_headers:
        raise RuntimeError("auth cookie/token/header is required; use --cookie, NEWTA_COOKIE, --prompt-cookie, or --auth-token")

    explicit_tax_doc_ids = _parse_tax_doc_ids(getattr(args, "tax_doc_ids", None))
    custom_types = _parse_custom_type_filters(args)
    auth_check = _auth_check_result(client, args=args, auth_headers=auth_headers)
    if not auth_check["ok"]:
        raise RuntimeError(f"authentication check failed status={auth_check.get('status')}")

    filter_results: list[dict[str, Any]] = []
    collected_tax_doc_ids: list[int] = []
    selected_office: dict[str, Any] | None = None
    if not explicit_tax_doc_ids and not getattr(args, "no_list", False):
        selected_office = resolve_office(client, args=args, auth_headers=auth_headers, me_context=auth_check)
        office_id = _office_id_from_record(selected_office)
        for custom_type in custom_types:
            result = collect_filter_search(
                client,
                args=args,
                auth_headers=auth_headers,
                office_id=office_id,
                custom_type=custom_type,
            )
            filter_results.append(result)
            collected_tax_doc_ids.extend(result["taxDocIds"])

    tax_doc_ids = _unique_preserve_order([*explicit_tax_doc_ids, *collected_tax_doc_ids])
    if not tax_doc_ids:
        raise RuntimeError("no taxDocIds found; check filters or pass --tax-doc-id")

    target_reason_type = str(getattr(args, "free_reason_type_match", "") or "사업형태_공동사업").strip()
    matches: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for tax_doc_id in tax_doc_ids:
        result = fetch_profile_summary(client, args=args, auth_headers=auth_headers, tax_doc_id=tax_doc_id)
        if not _response_ok(result):
            errors.append({"taxDocId": tax_doc_id, "status": result.status, "url": result.url})
            continue
        data = _extract_data(result)
        reason_types = _free_reason_types(data)
        if target_reason_type not in reason_types:
            continue
        phone_number = str(data.get("phoneNumber") or "").strip() if isinstance(data, dict) else ""
        matches.append({"taxDocId": tax_doc_id, "phoneNumber": phone_number})

    return {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "apiBaseUrl": _base_url(args),
            "authHeaderKeys": sorted(auth_headers.keys()),
            "authHeadersRedacted": _redacted_headers(auth_headers),
            "authCheck": auth_check,
            "selectedOffice": selected_office,
            "customTypes": custom_types,
            "filter": _filter_meta(args),
            "targetFreeReasonType": target_reason_type,
            "inputTaxDocCount": len(tax_doc_ids),
            "matchedCount": len(matches),
            "errorCount": len(errors),
            "readOnly": True,
            "blockedMethods": ["POST", "PUT", "PATCH", "DELETE"],
            "rawProfileSummariesStored": False,
        },
        "taxDocIds": tax_doc_ids,
        "filterSearch": filter_results,
        "matches": matches,
        "errors": errors,
    }


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _xlsx_cell(value: Any, *, row_index: int, column_index: int) -> str:
    ref = f"{_column_name(column_index)}{row_index}"
    if value is None:
        return f'<c r="{ref}"/>'
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, int | float):
        return f'<c r="{ref}"><v>{value}</v></c>'
    text = str(value)
    if text[:1] in {"=", "+", "-", "@"}:
        text = f"'{text}"
    return f'<c r="{ref}" t="inlineStr"><is><t>{xml_escape(text)}</t></is></c>'


def _xlsx_sheet_xml(rows: list[list[Any]]) -> str:
    xml_rows: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells = "".join(_xlsx_cell(value, row_index=row_index, column_index=column_index) for column_index, value in enumerate(row, start=1))
        xml_rows.append(f'<row r="{row_index}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>'
        f'{"".join(xml_rows)}'
        '</sheetData>'
        '</worksheet>'
    )


def write_common_business_free_reason_xlsx(output_path: Path, rows: list[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    table_rows: list[list[Any]] = [["taxDocId", "phoneNumber"]]
    table_rows.extend([[row.get("taxDocId", ""), row.get("phoneNumber", "")] for row in rows])
    now = datetime.now(timezone.utc).isoformat()
    worksheet = _xlsx_sheet_xml(table_rows)
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="matches" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '</Types>'
    )
    core_props = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:creator>newta-local-readonly-scraper</dc:creator>'
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{xml_escape(now)}</dcterms:created>'
        '</cp:coreProperties>'
    )
    app_props = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<Application>newta-local-readonly-scraper</Application></Properties>'
    )
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
        archive.writestr("docProps/core.xml", core_props)
        archive.writestr("docProps/app.xml", app_props)


def run_scrape(client: Any, *, args: argparse.Namespace, auth_headers: dict[str, str]) -> dict[str, Any]:
    if not auth_headers:
        raise RuntimeError("auth token/header is required; use --auth-token, NEWTA_AUTH_TOKEN, or --request-header")

    explicit_tax_doc_ids = _parse_tax_doc_ids(getattr(args, "tax_doc_ids", None))
    custom_types = _parse_custom_type_filters(args)
    auth_check = _auth_check_result(client, args=args, auth_headers=auth_headers)
    if not auth_check["ok"]:
        raise RuntimeError(f"authentication check failed status={auth_check.get('status')}")

    filter_results: list[dict[str, Any]] = []
    collected_tax_doc_ids: list[int] = []
    selected_office: dict[str, Any] | None = None
    if not explicit_tax_doc_ids and not getattr(args, "no_list", False):
        selected_office = resolve_office(client, args=args, auth_headers=auth_headers, me_context=auth_check)
        office_id = _office_id_from_record(selected_office)
        for custom_type in custom_types:
            result = collect_filter_search(
                client,
                args=args,
                auth_headers=auth_headers,
                office_id=office_id,
                custom_type=custom_type,
            )
            filter_results.append(result)
            collected_tax_doc_ids.extend(result["taxDocIds"])

    tax_doc_ids = _unique_preserve_order([*explicit_tax_doc_ids, *collected_tax_doc_ids])
    summary_records = (
        fetch_summaries(client, args=args, auth_headers=auth_headers, tax_doc_ids=tax_doc_ids)
        if getattr(args, "include_summary", False)
        else []
    )
    status_records = (
        fetch_submit_statuses(client, args=args, auth_headers=auth_headers, tax_doc_ids=tax_doc_ids)
        if getattr(args, "include_submit_status", False)
        else []
    )

    return {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "apiBaseUrl": _base_url(args),
            "authHeaderKeys": sorted(auth_headers.keys()),
            "authHeadersRedacted": _redacted_headers(auth_headers),
            "authCheck": auth_check,
            "selectedOffice": selected_office,
            "customTypes": custom_types,
            "filter": _filter_meta(args),
            "explicitTaxDocCount": len(explicit_tax_doc_ids),
            "collectedTaxDocCount": len(tax_doc_ids),
            "summaryCount": len(summary_records),
            "submitStatusCount": len(status_records),
            "readOnly": True,
            "blockedMethods": ["POST", "PUT", "PATCH", "DELETE"],
        },
        "taxDocIds": tax_doc_ids,
        "filterSearch": filter_results,
        "summaries": summary_records,
        "submitStatuses": status_records,
    }


def _filter_meta(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "officeId": getattr(args, "office_id", None),
        "officeIndex": getattr(args, "office_index", None),
        "officeNameContains": getattr(args, "office_name_contains", None),
        "workflowFilterSet": args.workflow_filter_set,
        "assignmentStatusFilter": args.assignment_status_filter,
        "taxDocCustomTypeFilter": args.tax_doc_custom_type_filter,
        "taxDocCustomTypeFilters": getattr(args, "tax_doc_custom_type_filters", None),
        "businessIncomeTypeFilter": args.business_income_type_filter,
        "freelancerIncomeAmountTypeFilter": args.freelancer_income_amount_type_filter,
        "reviewTypeFilter": args.review_type_filter,
        "submitGuideTypeFilter": args.submit_guide_type_filter,
        "applyExpenseRateTypeFilter": args.apply_expense_rate_type_filter,
        "noticeTypeFilter": args.notice_type_filter,
        "extraSurveyTypeFilter": args.extra_survey_type_filter,
        "expectedTaxAmountTypeFilter": args.expected_tax_amount_type_filter,
        "freeReasonTypeFilter": args.free_reason_type_filter,
        "refundStatusFilter": args.refund_status_filter,
        "taxDocServiceCodeTypeFilter": args.tax_doc_service_code_type_filter,
        "year": args.year,
        "sort": args.sort,
        "direction": args.direction,
        "page": args.page,
        "size": args.size,
        "maxTargets": args.max_targets,
    }


def _default_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("local_scrape_outputs") / f"newta_readonly_scrape_{stamp}.json"


def _default_common_business_free_reason_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("local_scrape_outputs") / f"newta_common_business_free_reason_{stamp}.xlsx"


def _prompt_text(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value or default


def _prompt_int(label: str, default: int) -> int:
    value = _prompt_text(label, str(default))
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an integer: {value!r}") from exc


def _prompt_optional_int(label: str, default: int | None, *, blank_hint: str) -> int | None:
    default_text = str(default) if default is not None else blank_hint
    value = input(f"{label} [{default_text}]: ").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an integer: {value!r}") from exc


def _has_auth_input(args: argparse.Namespace) -> bool:
    return bool(
        getattr(args, "cookie", "")
        or getattr(args, "auth_token", "")
        or getattr(args, "request_headers", [])
        or os.getenv("NEWTA_COOKIE")
        or os.getenv("NEWTA_AUTH_TOKEN")
    )


def _apply_interactive_prompts(args: argparse.Namespace) -> None:
    if not getattr(args, "interactive", False):
        return

    if not _has_auth_input(args) and not getattr(args, "prompt_token", False):
        args.prompt_cookie = True
    args.office_id = _prompt_optional_int(
        "officeId override",
        args.office_id,
        blank_hint="auto from /api/ta/v1/me",
    )
    args.workflow_filter_set = _prompt_text("workflowFilterSet", args.workflow_filter_set)
    args.tax_doc_custom_type_filter = _prompt_text("taxDocCustomTypeFilter", args.tax_doc_custom_type_filter)
    args.review_type_filter = _prompt_text("reviewTypeFilter", args.review_type_filter)
    args.tax_doc_service_code_type_filter = _prompt_text(
        "taxDocServiceCodeTypeFilter",
        args.tax_doc_service_code_type_filter,
    )
    args.year = _prompt_int("year", int(args.year))
    args.size = _prompt_int("page size", int(args.size))
    args.max_targets = _prompt_int("max targets (0 = all pages)", int(args.max_targets))
    if args.output is None:
        default_output = (
            _default_common_business_free_reason_output_path()
            if getattr(args, "export_common_business_free_reason_xlsx", False)
            else _default_output_path()
        )
        args.output = Path(_prompt_text("output path", str(default_output)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local GET-only NewTA scraper for 33income diagnostics")
    parser.add_argument("--api-base-url", default=TA_API_BASE)
    parser.add_argument("--interactive", action="store_true", help="Prompt for common local-run inputs before scraping.")
    parser.add_argument("--cookie", default="", help="Full NewTA Cookie header value. Prefer NEWTA_COOKIE or --prompt-cookie.")
    parser.add_argument("--prompt-cookie", action="store_true", help="Prompt for full Cookie header without echo.")
    parser.add_argument("--auth-token", default="", help="Authorization token. Bearer prefix is added when omitted.")
    parser.add_argument("--prompt-token", action="store_true", help="Prompt for token without echo when no env/arg token is set.")
    parser.add_argument(
        "--skip-auth-check",
        action="store_true",
        help=(
            "Skip the auth preflight. If officeId is not provided, "
            "/api/ta/v1/me is still used to discover it."
        ),
    )
    parser.add_argument(
        "--request-header",
        dest="request_headers",
        action="append",
        default=[],
        help="Extra request header, repeatable. Example: --request-header 'x-device-id: ...'",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--export-common-business-free-reason-xlsx",
        action="store_true",
        help="Export taxDocId/phoneNumber XLSX for summaries whose freeReasonType matches --free-reason-type-match.",
    )
    parser.add_argument("--free-reason-type-match", default="사업형태_공동사업")
    parser.add_argument("--summary-masking", action="store_true", help="Use isMasking=true for profile summary GETs.")

    parser.add_argument("--office-id", type=int, default=None)
    parser.add_argument("--office-index", type=int, default=0)
    parser.add_argument("--office-name-contains", default="")
    parser.add_argument("--workflow-filter-set", default="SUBMIT_READY")
    parser.add_argument("--assignment-status-filter", default="ALL")
    parser.add_argument("--tax-doc-custom-type-filter", default="ALL")
    parser.add_argument("--tax-doc-custom-type-filters", action="append", default=[])
    parser.add_argument("--business-income-type-filter", default="ALL")
    parser.add_argument("--freelancer-income-amount-type-filter", default="ALL")
    parser.add_argument("--review-type-filter", default="FREE")
    parser.add_argument("--submit-guide-type-filter", default="ALL")
    parser.add_argument("--apply-expense-rate-type-filter", default="ALL")
    parser.add_argument("--notice-type-filter", default="ALL")
    parser.add_argument("--extra-survey-type-filter", default="ALL")
    parser.add_argument("--expected-tax-amount-type-filter", default="ALL")
    parser.add_argument("--free-reason-type-filter", default="ALL")
    parser.add_argument("--refund-status-filter", default="ALL")
    parser.add_argument("--tax-doc-service-code-type-filter", default="C0")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--sort", default="SUBMIT_REQUEST_DATE_TIME")
    parser.add_argument("--direction", default="ASC")
    parser.add_argument("--page", type=int, default=0)
    parser.add_argument("--size", type=int, default=20)
    parser.add_argument("--max-targets", type=int, default=0)
    parser.add_argument("--tax-doc-id", dest="tax_doc_ids", action="append", default=[])
    parser.add_argument("--no-list", action="store_true", help="Do not auto-fetch filter-search list.")
    parser.add_argument("--include-summary", action="store_true", help="Fetch submits summary for collected/explicit taxDocIds.")
    parser.add_argument("--include-submit-status", action="store_true", help="Fetch one-click submit status for taxDocIds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _apply_interactive_prompts(args)
    auth_headers = _build_auth_headers(args)
    started = time.time()

    if getattr(args, "export_common_business_free_reason_xlsx", False):
        output_path = args.output or _default_common_business_free_reason_output_path()
        result = collect_common_business_free_reason_rows(
            ReadOnlyAPIClient(),
            args=args,
            auth_headers=auth_headers,
        )
        write_common_business_free_reason_xlsx(output_path, result["matches"])
        elapsed = time.time() - started
        meta = result["meta"]
        print(f"[DONE] common-business free-reason XLSX saved: {output_path}")
        print(
            "[DONE] counts "
            f"taxDocIds={meta['inputTaxDocCount']} "
            f"matches={meta['matchedCount']} "
            f"errors={meta['errorCount']} "
            f"elapsedSec={elapsed:.1f}"
        )
        print(f"[DONE] auth header keys: {', '.join(meta['authHeaderKeys']) or 'none'}")
        print("[DONE] raw profile summaries stored: false")
        return 0

    output_path = args.output or _default_output_path()
    result = run_scrape(ReadOnlyAPIClient(), args=args, auth_headers=auth_headers)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    elapsed = time.time() - started
    meta = result["meta"]
    print(f"[DONE] read-only scrape saved: {output_path}")
    print(
        "[DONE] counts "
        f"taxDocIds={meta['collectedTaxDocCount']} "
        f"summaries={meta['summaryCount']} "
        f"submitStatuses={meta['submitStatusCount']} "
        f"elapsedSec={elapsed:.1f}"
    )
    print(f"[DONE] auth header keys: {', '.join(meta['authHeaderKeys']) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
