#!/usr/bin/env bash
# Local GET-only NewTA exporter for taxDocs whose freeReasonType is 사업형태_공동사업.
# Prompts for the NewTA Cookie header at runtime and writes an XLSX with only taxDocId/phoneNumber.

set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Usage:
  ./tools/newta_common_business_phone_export.sh

What it does:
  - Prompts for the NewTA browser Cookie header without echo.
  - GETs filter-search with safe defaults from the captured browser request.
  - GETs /api/tax/v1/taxdocs/{taxDocId}/summary?isMasking=false for every collected taxDocId.
  - Exports only taxDocId and phoneNumber rows where freeReasonType == 사업형태_공동사업.
  - Never calls POST/PUT/PATCH/DELETE or submit/send/custom-type endpoints.

Default filters:
  officeId=auto from GET /api/ta/v1/me using the Cookie header
  workflowFilterSet=SUBMIT_READY
  taxDocCustomTypeFilter=ALL
  reviewTypeFilter=FREE
  taxDocServiceCodeTypeFilter=C0
  year=2025
  page size=20
  max targets=0 (all pages)

Optional env overrides:
  NEWTA_COOKIE                         full Cookie header (skips prompt)
  NEWTA_OUTPUT=/tmp/newta.xlsx         output path
  NEWTA_OFFICE_ID=327                  optional manual override; default is Cookie /me
  NEWTA_YEAR=2025
  NEWTA_PAGE_SIZE=20                   page size, not total limit
  NEWTA_MAX_TARGETS=0                  0 means all collected pages
  NEWTA_TAX_DOC_CUSTOM_TYPE_FILTER=ALL
  NEWTA_REVIEW_TYPE_FILTER=FREE
  NEWTA_WORKFLOW_FILTER_SET=SUBMIT_READY
  NEWTA_PYTHON=python3                 Python executable override

Extra CLI args are passed through and can override defaults, e.g.:
  ./tools/newta_common_business_phone_export.sh --max-targets 50 --size 20
USAGE
  exit 0
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
python_bin="${NEWTA_PYTHON:-${PYTHON:-python3}}"

args=(
  "${script_dir}/newta_local_readonly_scraper.py"
  --export-common-business-free-reason-xlsx
  --prompt-cookie
  --workflow-filter-set "${NEWTA_WORKFLOW_FILTER_SET:-SUBMIT_READY}"
  --assignment-status-filter "${NEWTA_ASSIGNMENT_STATUS_FILTER:-ALL}"
  --tax-doc-custom-type-filter "${NEWTA_TAX_DOC_CUSTOM_TYPE_FILTER:-ALL}"
  --business-income-type-filter "${NEWTA_BUSINESS_INCOME_TYPE_FILTER:-ALL}"
  --freelancer-income-amount-type-filter "${NEWTA_FREELANCER_INCOME_AMOUNT_TYPE_FILTER:-ALL}"
  --review-type-filter "${NEWTA_REVIEW_TYPE_FILTER:-FREE}"
  --submit-guide-type-filter "${NEWTA_SUBMIT_GUIDE_TYPE_FILTER:-ALL}"
  --apply-expense-rate-type-filter "${NEWTA_APPLY_EXPENSE_RATE_TYPE_FILTER:-ALL}"
  --notice-type-filter "${NEWTA_NOTICE_TYPE_FILTER:-ALL}"
  --extra-survey-type-filter "${NEWTA_EXTRA_SURVEY_TYPE_FILTER:-ALL}"
  --expected-tax-amount-type-filter "${NEWTA_EXPECTED_TAX_AMOUNT_TYPE_FILTER:-ALL}"
  --free-reason-type-filter "${NEWTA_FREE_REASON_TYPE_FILTER:-ALL}"
  --refund-status-filter "${NEWTA_REFUND_STATUS_FILTER:-ALL}"
  --tax-doc-service-code-type-filter "${NEWTA_TAX_DOC_SERVICE_CODE_TYPE_FILTER:-C0}"
  --year "${NEWTA_YEAR:-2025}"
  --sort "${NEWTA_SORT:-SUBMIT_REQUEST_DATE_TIME}"
  --direction "${NEWTA_DIRECTION:-ASC}"
  --size "${NEWTA_PAGE_SIZE:-20}"
  --max-targets "${NEWTA_MAX_TARGETS:-0}"
  --free-reason-type-match "${NEWTA_FREE_REASON_TYPE_MATCH:-사업형태_공동사업}"
)

if [[ -n "${NEWTA_OFFICE_ID:-}" ]]; then
  args+=(--office-id "${NEWTA_OFFICE_ID}")
fi

if [[ -n "${NEWTA_OUTPUT:-}" ]]; then
  args+=(--output "${NEWTA_OUTPUT}")
fi

if (($# > 0)); then
  args+=("$@")
fi

cd "${repo_root}"
echo "[INFO] NewTA common-business phone export: GET-only"
echo "[INFO] page size=${NEWTA_PAGE_SIZE:-20}; max targets=${NEWTA_MAX_TARGETS:-0} (0 means all pages)"
echo "[INFO] officeId=${NEWTA_OFFICE_ID:-auto from /api/ta/v1/me}"
echo "[INFO] output=${NEWTA_OUTPUT:-local_scrape_outputs/newta_common_business_free_reason_<UTC>.xlsx}"
echo "[INFO] Paste the full browser Cookie header when prompted. It is not printed or stored by this wrapper."
exec "${python_bin}" "${args[@]}"
