from __future__ import annotations

import os

_RATE_BASED_BOOKKEEPING_AUTO_FILTER_DEFAULTS: dict[str, str] = {
    "workflow_filter_set": "REVIEW_WAITING",
    "tax_doc_custom_type_filter": "가",
    "review_type_filter": "NORMAL",
    "apply_expense_rate_type_filter": "ALL",
    "sort": "REVIEW_REQUEST_DATE_TIME",
    "direction": "ASC",
    "scan_order": "forward",
}

_RATE_BASED_BOOKKEEPING_AUTO_FILTER_ENVS: dict[str, str] = {
    "workflow_filter_set": "INCOME33_RATE_BOOKKEEPING_WORKFLOW_FILTER_SET",
    "tax_doc_custom_type_filter": "INCOME33_RATE_BOOKKEEPING_TAX_DOC_CUSTOM_TYPE_FILTER",
    "review_type_filter": "INCOME33_RATE_BOOKKEEPING_REVIEW_TYPE_FILTER",
    "apply_expense_rate_type_filter": "INCOME33_RATE_BOOKKEEPING_APPLY_EXPENSE_RATE_TYPE_FILTER",
    "sort": "INCOME33_RATE_BOOKKEEPING_SORT",
    "direction": "INCOME33_RATE_BOOKKEEPING_DIRECTION",
    "scan_order": "INCOME33_RATE_BOOKKEEPING_SCAN_ORDER",
}


def _env_text(name: str, fallback: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return fallback
    return value.strip()


def rate_based_bookkeeping_auto_filter_payload() -> dict[str, str]:
    """Return control-tower-owned filters for the sender rate-bookkeeping action."""
    return {
        key: _env_text(_RATE_BASED_BOOKKEEPING_AUTO_FILTER_ENVS[key], fallback)
        for key, fallback in _RATE_BASED_BOOKKEEPING_AUTO_FILTER_DEFAULTS.items()
    }


def rate_based_bookkeeping_auto_action_label() -> str:
    explicit_label = os.getenv("INCOME33_RATE_BOOKKEEPING_BUTTON_LABEL")
    if explicit_label and explicit_label.strip():
        return explicit_label.strip()
    payload = rate_based_bookkeeping_auto_filter_payload()
    return f"경비율 장부발송({payload['review_type_filter']}·{payload['tax_doc_custom_type_filter']})"


def rate_based_bookkeeping_auto_hint() -> str:
    payload = rate_based_bookkeeping_auto_filter_payload()
    return (
        f"{payload['workflow_filter_set']} · 유형 {payload['tax_doc_custom_type_filter']} · "
        f"검토 {payload['review_type_filter']} 자동조회"
    )


def rate_based_bookkeeping_auto_confirm_message() -> str:
    payload = rate_based_bookkeeping_auto_filter_payload()
    return (
        f"{payload['workflow_filter_set']} + 유형 {payload['tax_doc_custom_type_filter']} + "
        f"검토 {payload['review_type_filter']} 대상을 자동조회해서 "
        "경비율 장부발송을 순차 실행할까요?"
    )
