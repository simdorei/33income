#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

from playwright.sync_api import BrowserContext, Page, sync_playwright

TA_API_BASE = "https://ta-gw.3o3.co.kr"
NEWTA_HOME = "https://newta.3o3.co.kr/"


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _search_first_key(data: Any, key: str) -> Any:
    if isinstance(data, dict):
        if key in data:
            return data.get(key)
        for child in data.values():
            found = _search_first_key(child, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for child in data:
            found = _search_first_key(child, key)
            if found is not None:
                return found
    return None


def _parse_repeated_custom_types(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    parsed: list[str] = []
    for raw in values:
        for token in str(raw).split(","):
            custom_type = token.strip()
            if custom_type:
                parsed.append(custom_type)
    return parsed


def _build_auth_headers(args: argparse.Namespace) -> dict[str, str]:
    headers: dict[str, str] = {}
    auth_token = str(getattr(args, "auth_token", "") or "").strip()
    if auth_token:
        headers["authorization"] = auth_token if auth_token.lower().startswith("bearer ") else f"Bearer {auth_token}"

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


class _DirectAPIResponse:
    def __init__(self, *, status: int, body: str, url: str) -> None:
        self.status = status
        self.ok = 200 <= status < 300
        self.url = url
        self._body = body

    def text(self) -> str:
        return self._body

    def json(self) -> Any:
        return json.loads(self._body)


class _DirectAPIRequest:
    def get(self, url: str, *, headers: dict[str, str]) -> _DirectAPIResponse:
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                body = response.read().decode(charset, errors="replace")
                return _DirectAPIResponse(status=response.status, body=body, url=url)
        except urllib.error.HTTPError as exc:
            charset = exc.headers.get_content_charset() if exc.headers else None
            body = exc.read().decode(charset or "utf-8", errors="replace")
            return _DirectAPIResponse(status=exc.code, body=body, url=url)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GET 요청 실패 url={url} error={exc.reason}") from exc


class _DirectAPIContext:
    def __init__(self) -> None:
        self.request = _DirectAPIRequest()


def _request_json(context: Any, *, url: str, headers: dict[str, str]) -> dict[str, Any]:
    response = context.request.get(url, headers=headers)
    body = response.text()
    try:
        data = response.json()
    except Exception:
        data = None
    return {
        "ok": response.ok,
        "status": response.status,
        "url": url,
        "json": data,
        "text": body,
    }


def _is_logged_in(context: BrowserContext, *, auth_headers: dict[str, str] | None = None) -> bool:
    me_url = f"{TA_API_BASE}/api/ta/v1/me"
    headers = {
        "accept": "application/json",
        "x-host": "GROUND",
        "x-web-path": "dashboard/default",
        **(auth_headers or {}),
    }
    result = _request_json(context, url=me_url, headers=headers)
    payload = result.get("json")
    return bool(
        result.get("ok")
        and isinstance(payload, dict)
        and payload.get("ok")
        and isinstance(payload.get("data"), dict)
    )


def _wait_for_login(
    page: Page,
    context: BrowserContext,
    wait_sec: int,
    *,
    auth_headers: dict[str, str] | None = None,
) -> None:
    page.goto(NEWTA_HOME, wait_until="domcontentloaded")
    if _is_logged_in(context, auth_headers=auth_headers):
        return

    print("[LOGIN] 로그인 세션이 없어 브라우저를 열었습니다. NewTA 로그인 완료 후 자동 진행합니다.")
    deadline = time.time() + max(10, wait_sec)
    while time.time() < deadline:
        time.sleep(3)
        if _is_logged_in(context, auth_headers=auth_headers):
            print("[LOGIN] 로그인 확인됨. 수집 시작합니다.")
            return
    raise RuntimeError(f"로그인 대기 시간 초과({wait_sec}초). 로그인 후 다시 실행해주세요.")


def _collect_tax_doc_ids(
    context: BrowserContext,
    *,
    args: argparse.Namespace,
    tax_doc_custom_type_filter: str,
    auth_headers: dict[str, str] | None = None,
) -> list[int]:
    headers = {
        "accept": "application/json, text/plain, */*",
        "x-host": "GIT",
        "x-web-path": "https://newta.3o3.co.kr/tasks/git",
        **(auth_headers or {}),
    }

    page = int(args.page)
    size = int(args.size)
    max_targets = int(getattr(args, "max_targets", 0) or 0)
    limit = max_targets if max_targets > 0 else None

    ids: list[int] = []
    seen_ids: set[int] = set()
    total_pages: int | None = None

    while True:
        query = {
            "officeId": args.office_id,
            "workflowFilterSet": args.workflow_filter_set,
            "assignmentStatusFilter": args.assignment_status_filter,
            "taxDocCustomTypeFilter": tax_doc_custom_type_filter,
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
            "size": size,
        }

        url = f"{TA_API_BASE}/api/tax/v1/taxdocs/filter-search?{urlencode(query)}"
        result = _request_json(context, url=url, headers=headers)
        body = result.get("json")

        if not result.get("ok") or not isinstance(body, dict) or not body.get("ok"):
            raise RuntimeError(
                "filter-search 실패 "
                f"customType={tax_doc_custom_type_filter} "
                f"page={page} status={result.get('status')} body={result.get('text', '')[:500]}"
            )

        data = body.get("data") if isinstance(body, dict) else None
        content = data.get("content") if isinstance(data, dict) else None
        if not isinstance(content, list):
            content = []

        total_pages_raw = data.get("totalPages") if isinstance(data, dict) else None
        parsed_total_pages = _as_int(total_pages_raw)
        if parsed_total_pages is not None and parsed_total_pages > 0:
            total_pages = parsed_total_pages

        for row in content:
            if not isinstance(row, dict):
                continue
            tax_doc_id = _as_int(row.get("taxDocId"))
            if tax_doc_id is None or tax_doc_id in seen_ids:
                continue
            seen_ids.add(tax_doc_id)
            ids.append(tax_doc_id)
            if limit is not None and len(ids) >= limit:
                return ids

        if total_pages is not None:
            if page >= total_pages - 1:
                break
            page += 1
            continue

        if not content:
            break
        page += 1

    return ids


def _find_bookkeeping_zero_additional_expense(
    context: BrowserContext,
    *,
    tax_doc_ids: list[int],
    tax_doc_custom_type_filter: str,
    auth_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    headers = {
        "accept": "application/json, text/plain, */*",
        "x-host": "GIT",
        "x-web-path": "https://newta.3o3.co.kr/git/summary",
        **(auth_headers or {}),
    }

    matches: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for tax_doc_id in tax_doc_ids:
        url = f"{TA_API_BASE}/api/tax/v1/taxdocs/{tax_doc_id}/expected-tax-amount/base-info"
        result = _request_json(context, url=url, headers=headers)
        body = result.get("json")
        if not result.get("ok") or not isinstance(body, dict) or not body.get("ok"):
            error_payload = body.get("error") if isinstance(body, dict) else None
            failure = {
                "taxDocId": tax_doc_id,
                "customType": tax_doc_custom_type_filter,
                "status": result.get("status"),
                "responseOk": result.get("ok"),
                "failureReason": str(error_payload or result.get("text") or "base-info request failed")[:500],
            }
            failures.append(failure)
            print(
                f"[WARN] base-info 실패 customType={tax_doc_custom_type_filter} "
                f"taxDocId={tax_doc_id} status={result.get('status')}"
            )
            continue

        data = body.get("data") if isinstance(body, dict) else None
        calculation_type = _search_first_key(data, "calculationType") if data is not None else None
        additional_expense_amount = _search_first_key(data, "additionalExpenseAmount") if data is not None else None

        normalized_calculation_type = str(calculation_type or "").strip().upper()
        normalized_additional_expense = _as_int(additional_expense_amount)

        if normalized_calculation_type == "BOOKKEEPING" and normalized_additional_expense == 0:
            matches.append(
                {
                    "taxDocId": tax_doc_id,
                    "customType": tax_doc_custom_type_filter,
                    "calculationType": normalized_calculation_type,
                    "additionalExpenseAmount": normalized_additional_expense,
                    "baseInfo": data,
                }
            )

    return {
        "matches": matches,
        "failures": failures,
        "attemptedCount": len(tax_doc_ids),
    }


def _default_output_path() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path.cwd() / f"bookkeeping_zero_additional_expense_{ts}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "EXPECTED_SENT 목록에서 taxDocId를 수집한 뒤 expected-tax-amount/base-info를 조회해 "
            "calculationType=BOOKKEEPING & additionalExpenseAmount=0 케이스를 찾습니다."
        )
    )
    parser.add_argument("--office-id", type=int, default=327)
    parser.add_argument("--workflow-filter-set", default="EXPECTED_SENT")
    parser.add_argument("--assignment-status-filter", default="ALL")
    parser.add_argument("--tax-doc-custom-type-filter", default="가")
    parser.add_argument(
        "--tax-doc-custom-type-filters",
        nargs="+",
        default=None,
        help="복수 custom type 동시 조회(예: --tax-doc-custom-type-filters 가 자 또는 '가,자').",
    )
    parser.add_argument("--business-income-type-filter", default="ALL")
    parser.add_argument("--freelancer-income-amount-type-filter", default="ALL")
    parser.add_argument("--review-type-filter", default="NORMAL")
    parser.add_argument("--submit-guide-type-filter", default="ALL")
    parser.add_argument("--apply-expense-rate-type-filter", default="ALL")
    parser.add_argument("--notice-type-filter", default="ALL")
    parser.add_argument("--extra-survey-type-filter", default="ALL")
    parser.add_argument("--expected-tax-amount-type-filter", default="ALL")
    parser.add_argument("--free-reason-type-filter", default="ALL")
    parser.add_argument("--refund-status-filter", default="ALL")
    parser.add_argument("--tax-doc-service-code-type-filter", default="C0")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--sort", default="REVIEW_REQUEST_DATE_TIME")
    parser.add_argument("--direction", default="DESC")
    parser.add_argument("--page", type=int, default=0)
    parser.add_argument("--size", type=int, default=20)
    parser.add_argument(
        "--max-targets",
        type=int,
        default=0,
        help="수집 taxDocId 최대 건수(0이면 제한 없음, 전체 페이지 조회).",
    )

    parser.add_argument("--cdp-endpoint", default="http://127.0.0.1:9222")
    parser.add_argument(
        "--direct-get",
        action="store_true",
        help="브라우저/CDP 없이 --auth-token/--request-header 인증값으로 API GET만 수행합니다.",
    )
    parser.add_argument("--no-cdp", action="store_true", help="CDP 접속을 건너뛰고 새 브라우저를 띄웁니다.")
    parser.add_argument("--headless", action="store_true", help="새 브라우저 fallback 시 headless로 실행")
    parser.add_argument("--login-wait-sec", type=int, default=600)
    parser.add_argument("--auth-token", default="", help="Authorization 토큰. Bearer 접두사 없으면 자동 추가.")
    parser.add_argument(
        "--request-header",
        dest="request_headers",
        action="append",
        default=[],
        help="추가 요청 헤더. 여러 번 지정 가능 (예: --request-header 'x-device-id: ...').",
    )
    parser.add_argument("--output", type=Path, default=None)

    return parser.parse_args()


def _resolve_custom_types(args: argparse.Namespace) -> list[str]:
    custom_types = _parse_repeated_custom_types(args.tax_doc_custom_type_filters)
    if not custom_types:
        fallback_custom_type = str(args.tax_doc_custom_type_filter or "").strip()
        custom_types = [fallback_custom_type] if fallback_custom_type else ["가"]
    return list(dict.fromkeys(custom_types))


def _run_scan(
    context: Any,
    *,
    args: argparse.Namespace,
    output_path: Path,
    auth_headers: dict[str, str],
    custom_types: list[str],
    used_cdp: bool,
) -> int:
    per_type: dict[str, Any] = {}
    all_matches: list[dict[str, Any]] = []
    all_failures: list[dict[str, Any]] = []
    unique_tax_doc_ids: list[int] = []
    seen_ids: set[int] = set()
    attempted_count = 0

    for custom_type in custom_types:
        tax_doc_ids = _collect_tax_doc_ids(
            context,
            args=args,
            tax_doc_custom_type_filter=custom_type,
            auth_headers=auth_headers,
        )
        print(f"[INFO] customType={custom_type} 수집 taxDocId: {len(tax_doc_ids)}건")
        for tax_doc_id in tax_doc_ids:
            if tax_doc_id in seen_ids:
                continue
            seen_ids.add(tax_doc_id)
            unique_tax_doc_ids.append(tax_doc_id)

        scan_result = _find_bookkeeping_zero_additional_expense(
            context,
            tax_doc_ids=tax_doc_ids,
            tax_doc_custom_type_filter=custom_type,
            auth_headers=auth_headers,
        )
        matches = scan_result["matches"]
        failures = scan_result["failures"]
        attempted_count += scan_result["attemptedCount"]
        all_matches.extend(matches)
        all_failures.extend(failures)

        per_type[custom_type] = {
            "taxDocIds": tax_doc_ids,
            "collectedTaxDocCount": len(tax_doc_ids),
            "baseInfoAttemptedCount": scan_result["attemptedCount"],
            "baseInfoFailureCount": len(failures),
            "matchedCount": len(matches),
            "matches": matches,
            "failures": failures,
        }

    incomplete = len(all_failures) > 0
    result = {
        "meta": {
            "used_cdp": used_cdp,
            "cdp_endpoint": args.cdp_endpoint,
            "incomplete": incomplete,
            "customTypes": custom_types,
            "authHeaderKeys": sorted(auth_headers.keys()),
            "filter": {
                "officeId": args.office_id,
                "workflowFilterSet": args.workflow_filter_set,
                "assignmentStatusFilter": args.assignment_status_filter,
                "taxDocCustomTypeFilter": args.tax_doc_custom_type_filter,
                "taxDocCustomTypeFilters": custom_types,
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
            },
            "collectedTaxDocCount": len(unique_tax_doc_ids),
            "baseInfoAttemptedCount": attempted_count,
            "baseInfoFailureCount": len(all_failures),
            "matchedCount": len(all_matches),
        },
        "taxDocIds": unique_tax_doc_ids,
        "matches": all_matches,
        "failures": all_failures,
        "perCustomType": per_type,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[DONE] BOOKKEEPING + additionalExpenseAmount=0: {len(all_matches)}건")
    print(f"[DONE] base-info 조회 실패: {len(all_failures)}건")
    print(f"[DONE] 결과 파일: {output_path}")
    for item in all_matches:
        print(f"  - customType={item.get('customType')} taxDocId={item['taxDocId']}")
    if all_failures:
        print("[WARN] base-info 조회 실패 taxDocId 목록:")
        for failure in all_failures:
            print(
                f"  - customType={failure.get('customType')} "
                f"taxDocId={failure['taxDocId']} status={failure.get('status')}"
            )
        return 2
    return 0


def main() -> int:
    args = parse_args()
    output_path = args.output or _default_output_path()
    auth_headers = _build_auth_headers(args)
    custom_types = _resolve_custom_types(args)

    if getattr(args, "direct_get", False):
        if not auth_headers:
            print("[ERROR] --direct-get은 --auth-token 또는 --request-header 인증값이 필요합니다.")
            return 1
        context = _DirectAPIContext()
        if not _is_logged_in(context, auth_headers=auth_headers):
            raise RuntimeError("direct GET 인증 확인 실패. auth token/header를 확인해주세요.")
        return _run_scan(
            context,
            args=args,
            output_path=output_path,
            auth_headers=auth_headers,
            custom_types=custom_types,
            used_cdp=False,
        )

    with sync_playwright() as p:
        browser = None
        context: BrowserContext | None = None
        page: Page | None = None
        used_cdp = False

        if not args.no_cdp:
            try:
                browser = p.chromium.connect_over_cdp(args.cdp_endpoint)
                used_cdp = True
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.pages[0] if context.pages else context.new_page()
                print(f"[INFO] CDP 연결 성공: {args.cdp_endpoint}")
            except Exception as exc:
                print(f"[WARN] CDP 연결 실패({args.cdp_endpoint}): {exc}")

        if context is None or page is None:
            browser = p.chromium.launch(headless=args.headless)
            context = browser.new_context()
            page = context.new_page()
            print("[INFO] 새 브라우저 컨텍스트로 실행합니다(필요 시 수동 로그인).")

        try:
            _wait_for_login(page, context, args.login_wait_sec, auth_headers=auth_headers)
            return _run_scan(
                context,
                args=args,
                output_path=output_path,
                auth_headers=auth_headers,
                custom_types=custom_types,
                used_cdp=used_cdp,
            )
        finally:
            if browser is not None:
                browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
