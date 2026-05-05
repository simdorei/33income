#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
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


def _request_json(context: BrowserContext, *, url: str, headers: dict[str, str]) -> dict[str, Any]:
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


def _is_logged_in(context: BrowserContext) -> bool:
    me_url = f"{TA_API_BASE}/api/ta/v1/me"
    headers = {
        "accept": "application/json",
        "x-host": "GROUND",
        "x-web-path": "dashboard/default",
    }
    result = _request_json(context, url=me_url, headers=headers)
    payload = result.get("json")
    return bool(
        result.get("ok")
        and isinstance(payload, dict)
        and payload.get("ok")
        and isinstance(payload.get("data"), dict)
    )


def _wait_for_login(page: Page, context: BrowserContext, wait_sec: int) -> None:
    page.goto(NEWTA_HOME, wait_until="domcontentloaded")
    if _is_logged_in(context):
        return

    print("[LOGIN] 로그인 세션이 없어 브라우저를 열었습니다. NewTA 로그인 완료 후 자동 진행합니다.")
    deadline = time.time() + max(10, wait_sec)
    while time.time() < deadline:
        time.sleep(3)
        if _is_logged_in(context):
            print("[LOGIN] 로그인 확인됨. 수집 시작합니다.")
            return
    raise RuntimeError(f"로그인 대기 시간 초과({wait_sec}초). 로그인 후 다시 실행해주세요.")


def _collect_tax_doc_ids(context: BrowserContext, *, args: argparse.Namespace) -> list[int]:
    headers = {
        "accept": "application/json, text/plain, */*",
        "x-host": "GIT",
        "x-web-path": "https://newta.3o3.co.kr/tasks/git",
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
            "taxDocCustomTypeFilter": args.tax_doc_custom_type_filter,
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
                f"filter-search 실패 page={page} status={result.get('status')} body={result.get('text', '')[:500]}"
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


def _find_bookkeeping_zero_additional_expense(context: BrowserContext, *, tax_doc_ids: list[int]) -> dict[str, Any]:
    headers = {
        "accept": "application/json, text/plain, */*",
        "x-host": "GIT",
        "x-web-path": "https://newta.3o3.co.kr/git/summary",
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
                "status": result.get("status"),
                "responseOk": result.get("ok"),
                "failureReason": str(error_payload or result.get("text") or "base-info request failed")[:500],
            }
            failures.append(failure)
            print(f"[WARN] base-info 실패 taxDocId={tax_doc_id} status={result.get('status')}")
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
    parser.add_argument("--no-cdp", action="store_true", help="CDP 접속을 건너뛰고 새 브라우저를 띄웁니다.")
    parser.add_argument("--headless", action="store_true", help="새 브라우저 fallback 시 headless로 실행")
    parser.add_argument("--login-wait-sec", type=int, default=600)
    parser.add_argument("--output", type=Path, default=None)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = args.output or _default_output_path()

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
            _wait_for_login(page, context, args.login_wait_sec)

            tax_doc_ids = _collect_tax_doc_ids(context, args=args)
            print(f"[INFO] 수집 taxDocId: {len(tax_doc_ids)}건")

            scan_result = _find_bookkeeping_zero_additional_expense(context, tax_doc_ids=tax_doc_ids)
            matches = scan_result["matches"]
            failures = scan_result["failures"]
            incomplete = len(failures) > 0
            result = {
                "meta": {
                    "used_cdp": used_cdp,
                    "cdp_endpoint": args.cdp_endpoint,
                    "incomplete": incomplete,
                    "filter": {
                        "officeId": args.office_id,
                        "workflowFilterSet": args.workflow_filter_set,
                        "assignmentStatusFilter": args.assignment_status_filter,
                        "taxDocCustomTypeFilter": args.tax_doc_custom_type_filter,
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
                    "collectedTaxDocCount": len(tax_doc_ids),
                    "baseInfoAttemptedCount": scan_result["attemptedCount"],
                    "baseInfoFailureCount": len(failures),
                    "matchedCount": len(matches),
                },
                "taxDocIds": tax_doc_ids,
                "matches": matches,
                "failures": failures,
            }

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

            print(f"[DONE] BOOKKEEPING + additionalExpenseAmount=0: {len(matches)}건")
            print(f"[DONE] base-info 조회 실패: {len(failures)}건")
            print(f"[DONE] 결과 파일: {output_path}")
            for item in matches:
                print(f"  - taxDocId={item['taxDocId']}")
            if failures:
                print("[WARN] base-info 조회 실패 taxDocId 목록:")
                for failure in failures:
                    print(f"  - taxDocId={failure['taxDocId']} status={failure.get('status')}")
                return 2
            return 0
        finally:
            if browser is not None:
                browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
