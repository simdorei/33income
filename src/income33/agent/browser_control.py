from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

DEFAULT_LOGIN_URL = "https://newta.3o3.co.kr/login?r=%2F"
DEFAULT_REFRESH_URL = "https://newta.3o3.co.kr/tasks/git"
DEFAULT_API_BASE_URL = "https://ta-gw.3o3.co.kr"
DEFAULT_DEBUG_PORT_BASE = 29200
DEFAULT_REFRESH_INTERVAL_SECONDS = 600
DEFAULT_TAXDOC_YEAR = 2025

WINDOWS_BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

POSIX_BROWSER_CANDIDATES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium-browser",
    "chromium",
    "microsoft-edge",
    "msedge",
]


def _env_bool(name: str, fallback: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return fallback
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, fallback: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def mask_secret(value: str | None) -> str:
    if value is None:
        return ""
    stripped = value.strip()
    if not stripped:
        return ""
    return "***"


def resolve_login_url(payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    return str(
        payload.get("login_url")
        or os.getenv("INCOME33_LOGIN_URL")
        or os.getenv("LOGIN_URL")
        or DEFAULT_LOGIN_URL
    )


def resolve_refresh_url(payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    return str(payload.get("refresh_url") or os.getenv("INCOME33_REFRESH_URL") or DEFAULT_REFRESH_URL)


def resolve_profile_dir(bot_id: str, payload: dict[str, Any] | None = None) -> Path:
    payload = payload or {}
    configured = payload.get("profile_dir")
    if configured:
        return Path(str(configured))

    profile_root = os.getenv("INCOME33_PROFILE_ROOT", "profiles")
    return Path(profile_root) / bot_id


def is_browser_control_dry_run(payload: dict[str, Any] | None = None) -> bool:
    payload = payload or {}
    return bool(payload.get("dry_run")) or _env_bool("INCOME33_BROWSER_CONTROL_DRY_RUN") or _env_bool(
        "INCOME33_LOGIN_DRY_RUN"
    ) or _env_bool("INCOME33_LOGIN_BROWSER_DRY_RUN")


def resolve_browser_executable() -> str | None:
    explicit = os.getenv("INCOME33_BROWSER_EXE") or os.getenv("BROWSER_EXE")
    if explicit:
        return explicit

    if os.name == "nt":
        for candidate in WINDOWS_BROWSER_CANDIDATES:
            if Path(candidate).exists():
                return candidate
        return None

    for candidate in POSIX_BROWSER_CANDIDATES:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def resolve_browser_debug_port(bot_id: str, payload: dict[str, Any] | None = None) -> int:
    payload = payload or {}
    if payload.get("debug_port"):
        return int(payload["debug_port"])

    base = _env_int("INCOME33_BROWSER_DEBUG_PORT_BASE", DEFAULT_DEBUG_PORT_BASE)

    sender_match = re.match(r"^sender-(\d+)$", bot_id)
    if sender_match:
        return base + int(sender_match.group(1))

    reporter_match = re.match(r"^reporter-(\d+)$", bot_id)
    if reporter_match:
        return base + 100 + int(reporter_match.group(1))

    fallback = sum(ord(ch) for ch in bot_id) % 1000
    return base + fallback


def _cdp_endpoint(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _env_text(name: str, fallback: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return fallback
    return value


def resolve_selector_text(
    payload: dict[str, Any] | None,
    *,
    payload_key: str,
    env_name: str,
    fallback: str,
) -> str:
    payload = payload or {}
    configured = payload.get(payload_key)
    if configured is not None and str(configured).strip():
        return str(configured).strip()
    return _env_text(env_name, fallback)


def resolve_selector_timeout_ms(payload: dict[str, Any] | None = None) -> int:
    payload = payload or {}
    if payload.get("selector_timeout_ms"):
        try:
            return max(100, int(payload["selector_timeout_ms"]))
        except (TypeError, ValueError):
            pass
    return max(100, _env_int("INCOME33_SELECTOR_TIMEOUT_MS", 2_000))


def _split_selector_candidates(selector_text: str) -> list[str]:
    if "||" in selector_text:
        return [part.strip() for part in selector_text.split("||") if part.strip()]
    return [selector_text.strip()] if selector_text.strip() else []


def _first_visible_locator(page: Any, selector_text: str, timeout_ms: int = 10_000) -> tuple[Any, str]:
    candidates = _split_selector_candidates(selector_text)
    for candidate in candidates:
        locator = page.locator(candidate).first
        try:
            locator.wait_for(state="visible", timeout=timeout_ms)
            return locator, candidate
        except Exception:
            continue
    raise RuntimeError(f"visible selector not found: {selector_text}")


def _has_visible_locator(page: Any, selector_text: str, timeout_ms: int = 500) -> bool:
    for candidate in _split_selector_candidates(selector_text):
        locator = page.locator(candidate).first
        try:
            locator.wait_for(state="visible", timeout=timeout_ms)
            return True
        except Exception:
            continue
    return False


def _resolve_browser_page(browser: Any) -> Any:
    contexts = list(browser.contexts)
    if contexts:
        context = contexts[0]
    else:
        context = browser.new_context()
    pages = list(context.pages)
    if pages:
        return pages[0]
    return context.new_page()


def _load_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on optional runtime install
        raise RuntimeError(
            "Playwright Python package is required for browser control. "
            "Install dependencies then retry."
        ) from exc
    return sync_playwright


def launch_login_browser(
    *,
    bot_id: str,
    payload: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    logger = logger or logging.getLogger("income33.agent.browser_control")
    payload = payload or {}
    login_url = resolve_login_url(payload)
    profile_dir = resolve_profile_dir(bot_id, payload)
    debug_port = resolve_browser_debug_port(bot_id, payload)
    profile_dir.mkdir(parents=True, exist_ok=True)

    if is_browser_control_dry_run(payload):
        logger.info(
            "browser_control_dry_run bot_id=%s url=%s profile_dir=%s debug_port=%s",
            bot_id,
            login_url,
            profile_dir,
            debug_port,
        )
        return {
            "opened": False,
            "dry_run": True,
            "url": login_url,
            "profile_dir": str(profile_dir),
            "browser": None,
            "debug_port": debug_port,
        }

    browser = resolve_browser_executable()
    if browser:
        command = [
            browser,
            f"--user-data-dir={profile_dir.resolve()}",
            f"--remote-debugging-port={debug_port}",
            "--new-window",
            login_url,
        ]
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(
            "browser_control_opened bot_id=%s browser=%s url=%s profile_dir=%s debug_port=%s",
            bot_id,
            browser,
            login_url,
            profile_dir,
            debug_port,
        )
        return {
            "opened": True,
            "dry_run": False,
            "url": login_url,
            "profile_dir": str(profile_dir),
            "browser": browser,
            "debug_port": debug_port,
            "cdp_endpoint": _cdp_endpoint(debug_port),
        }

    # last-resort fallback (no isolated profile/debug control)
    webbrowser.open(login_url, new=1, autoraise=True)
    logger.warning(
        "browser_control_opened_without_cdp bot_id=%s url=%s profile_dir=%s",
        bot_id,
        login_url,
        profile_dir,
    )
    return {
        "opened": True,
        "dry_run": False,
        "url": login_url,
        "profile_dir": str(profile_dir),
        "browser": "default",
        "profile_isolated": False,
        "debug_port": debug_port,
    }


def _run_in_cdp_session(bot_id: str, payload: dict[str, Any], fn) -> dict[str, Any]:
    debug_port = resolve_browser_debug_port(bot_id, payload)
    cdp_endpoint = _cdp_endpoint(debug_port)
    sync_playwright = _load_playwright()

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(cdp_endpoint)
        try:
            page = _resolve_browser_page(browser)
            return fn(page, debug_port)
        finally:
            browser.close()


def fill_login(
    *,
    bot_id: str,
    payload: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    logger = logger or logging.getLogger("income33.agent.browser_control")
    payload = payload or {}
    login_id = os.getenv("INCOME33_LOGIN_ID", "").strip()
    login_password = os.getenv("INCOME33_LOGIN_PASSWORD", "")

    if not login_id or not login_password:
        raise ValueError("INCOME33_LOGIN_ID and INCOME33_LOGIN_PASSWORD are required")

    if is_browser_control_dry_run(payload):
        logger.info(
            "fill_login_dry_run bot_id=%s debug_port=%s id_set=%s password_masked=%s",
            bot_id,
            resolve_browser_debug_port(bot_id, payload),
            bool(login_id),
            mask_secret(login_password),
        )
        return {
            "ok": True,
            "dry_run": True,
            "status": "login_auth_required",
            "current_step": "login_auth_required",
        }

    login_url = resolve_login_url(payload)
    id_selector = resolve_selector_text(
        payload,
        payload_key="login_id_selector",
        env_name="INCOME33_LOGIN_ID_SELECTOR",
        fallback="input[name='username'] || input[type='email'] || input[type='text']",
    )
    password_selector = resolve_selector_text(
        payload,
        payload_key="login_password_selector",
        env_name="INCOME33_LOGIN_PASSWORD_SELECTOR",
        fallback="input[name='password'] || input[type='password']",
    )
    submit_selector = resolve_selector_text(
        payload,
        payload_key="login_submit_selector",
        env_name="INCOME33_LOGIN_SUBMIT_SELECTOR",
        fallback="button[type='submit'] || button:has-text('로그인') || button:has-text('Login')",
    )
    auth_selector = resolve_selector_text(
        payload,
        payload_key="login_auth_code_selector",
        env_name="INCOME33_LOGIN_AUTH_CODE_SELECTOR",
        fallback="input[name='authCode'] || input[name='otp'] || input[inputmode='numeric'] || input[type='tel']",
    )
    selector_timeout_ms = resolve_selector_timeout_ms(payload)

    def _run(page: Any, debug_port: int) -> dict[str, Any]:
        page.goto(login_url, wait_until="domcontentloaded")
        id_locator, matched_id_selector = _first_visible_locator(page, id_selector, selector_timeout_ms)
        password_locator, matched_password_selector = _first_visible_locator(page, password_selector, selector_timeout_ms)
        id_locator.fill(login_id)
        password_locator.fill(login_password)
        submit_locator, matched_submit_selector = _first_visible_locator(page, submit_selector, selector_timeout_ms)
        submit_locator.click()
        auth_visible = _has_visible_locator(page, auth_selector, timeout_ms=5_000)
        return {
            "ok": True,
            "dry_run": False,
            "status": "login_auth_required" if auth_visible else "login_filling",
            "current_step": "인증코드 입력 대기" if auth_visible else "로그인 제출 후 확인 중",
            "debug_port": debug_port,
            "matched_selectors": {
                "id": matched_id_selector,
                "password": matched_password_selector,
                "submit": matched_submit_selector,
                "auth_code_visible": auth_visible,
            },
        }

    result = _run_in_cdp_session(bot_id, payload, _run)
    logger.info(
        "fill_login_done bot_id=%s debug_port=%s id_set=%s password_masked=%s",
        bot_id,
        result.get("debug_port"),
        bool(login_id),
        mask_secret(login_password),
    )
    return result


def submit_auth_code(
    *,
    bot_id: str,
    auth_code: str,
    payload: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    logger = logger or logging.getLogger("income33.agent.browser_control")
    payload = payload or {}
    safe_code = auth_code.strip()
    if not safe_code:
        raise ValueError("auth_code is required")

    if is_browser_control_dry_run(payload):
        logger.info(
            "submit_auth_code_dry_run bot_id=%s debug_port=%s auth_code_masked=%s",
            bot_id,
            resolve_browser_debug_port(bot_id, payload),
            mask_secret(safe_code),
        )
        return {
            "ok": True,
            "dry_run": True,
            "status": "session_active",
            "current_step": "session_active",
            "url": "https://newta.3o3.co.kr/dashboard",
        }

    auth_selector = resolve_selector_text(
        payload,
        payload_key="login_auth_code_selector",
        env_name="INCOME33_LOGIN_AUTH_CODE_SELECTOR",
        fallback="input[name='authCode'] || input[name='otp'] || input[inputmode='numeric'] || input[type='tel']",
    )
    submit_selector = resolve_selector_text(
        payload,
        payload_key="login_auth_submit_selector",
        env_name="INCOME33_LOGIN_AUTH_SUBMIT_SELECTOR",
        fallback="button[type='submit'] || button:has-text('확인') || button:has-text('인증') || button:has-text('Verify')",
    )
    dashboard_url = _env_text("INCOME33_DASHBOARD_URL", "https://newta.3o3.co.kr/dashboard")
    selector_timeout_ms = resolve_selector_timeout_ms(payload)

    def _run(page: Any, debug_port: int) -> dict[str, Any]:
        auth_locator, matched_auth_selector = _first_visible_locator(page, auth_selector, selector_timeout_ms)
        auth_locator.fill(safe_code)
        submit_locator, matched_submit_selector = _first_visible_locator(page, submit_selector, selector_timeout_ms)
        submit_locator.click()
        try:
            page.wait_for_url(f"{dashboard_url.rstrip('/')}**", timeout=10_000)
        except Exception:
            pass
        current_url = page.url
        on_dashboard = current_url.rstrip("/").startswith(dashboard_url.rstrip("/"))
        return {
            "ok": on_dashboard,
            "dry_run": False,
            "status": "session_active" if on_dashboard else "login_auth_required",
            "current_step": "session_active" if on_dashboard else "인증코드 확인 필요",
            "debug_port": debug_port,
            "url": current_url,
            "matched_selectors": {
                "auth_code": matched_auth_selector,
                "submit": matched_submit_selector,
            },
        }

    result = _run_in_cdp_session(bot_id, payload, _run)
    logger.info(
        "submit_auth_code_done bot_id=%s debug_port=%s auth_code_masked=%s",
        bot_id,
        result.get("debug_port"),
        mask_secret(safe_code),
    )
    return result


def inspect_login_state(
    *,
    bot_id: str,
    payload: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any] | None:
    logger = logger or logging.getLogger("income33.agent.browser_control")
    payload = payload or {}
    if is_browser_control_dry_run(payload):
        return None

    auth_selector = resolve_selector_text(
        payload,
        payload_key="login_auth_code_selector",
        env_name="INCOME33_LOGIN_AUTH_CODE_SELECTOR",
        fallback="input[name='authCode'] || input[name='otp'] || input[inputmode='numeric'] || input[type='tel']",
    )
    dashboard_url = _env_text("INCOME33_DASHBOARD_URL", "https://newta.3o3.co.kr/dashboard")

    def _run(page: Any, debug_port: int) -> dict[str, Any] | None:
        current_url = page.url
        if current_url.rstrip("/").startswith(dashboard_url.rstrip("/")):
            return {
                "status": "session_active",
                "current_step": "session_active",
                "url": current_url,
                "debug_port": debug_port,
            }
        if _has_visible_locator(page, auth_selector, timeout_ms=500):
            return {
                "status": "login_auth_required",
                "current_step": "인증코드 입력 대기",
                "url": current_url,
                "debug_port": debug_port,
            }
        return None

    try:
        result = _run_in_cdp_session(bot_id, payload, _run)
    except Exception as exc:
        logger.debug("inspect_login_state_skipped bot_id=%s error=%s", bot_id, exc)
        return None
    if result:
        logger.info(
            "inspect_login_state bot_id=%s status=%s step=%s url=%s",
            bot_id,
            result.get("status"),
            result.get("current_step"),
            result.get("url"),
        )
    return result


def _resolve_tax_api_base_url(payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    return str(payload.get("api_base_url") or os.getenv("INCOME33_TAX_API_BASE_URL") or DEFAULT_API_BASE_URL).rstrip("/")


def _resolve_taxdoc_year(payload: dict[str, Any] | None = None) -> int:
    payload = payload or {}
    if payload.get("year"):
        return int(payload["year"])
    return _env_int("INCOME33_TAXDOC_YEAR", DEFAULT_TAXDOC_YEAR)


def _resolve_taxdoc_page_size(payload: dict[str, Any] | None = None) -> int:
    payload = payload or {}
    if payload.get("size"):
        return max(1, min(100, int(payload["size"])))
    return max(1, min(100, _env_int("INCOME33_TAXDOC_PAGE_SIZE", 20)))


def _taxdoc_filter_search_url(
    *,
    api_base_url: str,
    office_id: int,
    year: int,
    page: int,
    size: int,
) -> str:
    params = {
        "officeId": office_id,
        "workflowFilterSet": "ASSIGN_WAITING",
        "assignmentStatusFilter": "ALL",
        "taxDocCustomTypeFilter": "ALL",
        "businessIncomeTypeFilter": "ALL",
        "freelancerIncomeAmountTypeFilter": "ALL",
        "reviewTypeFilter": "ALL",
        "submitGuideTypeFilter": "ALL",
        "applyExpenseRateTypeFilter": "ALL",
        "noticeTypeFilter": "ALL",
        "extraSurveyTypeFilter": "ALL",
        "expectedTaxAmountTypeFilter": "ALL",
        "refundStatusFilter": "ALL",
        "taxDocServiceCodeTypeFilter": "C0",
        "year": year,
        "sort": "REVIEW_REQUEST_DATE_TIME",
        "direction": "DESC",
        "page": page,
        "size": size,
    }
    return f"{api_base_url}/api/tax/v1/taxdocs/filter-search?{urlencode(params)}"


def _browser_fetch_json(page: Any, *, url: str, method: str = "GET", headers: dict[str, str] | None = None) -> dict[str, Any]:
    return page.evaluate(
        """
        async ({url, method, headers}) => {
          const response = await fetch(url, {
            method,
            headers,
            credentials: 'include',
          });
          const text = await response.text();
          let json = null;
          try { json = text ? JSON.parse(text) : null; } catch (e) {}
          return {
            ok: response.ok,
            status: response.status,
            url: response.url,
            json,
            text: json ? null : text.slice(0, 500),
          };
        }
        """,
        {"url": url, "method": method, "headers": headers or {}},
    )


def preview_expected_tax_send_targets(
    *,
    bot_id: str,
    payload: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    logger = logger or logging.getLogger("income33.agent.browser_control")
    payload = payload or {}
    year = _resolve_taxdoc_year(payload)
    size = _resolve_taxdoc_page_size(payload)
    page_index = max(0, int(payload.get("page", 0)))

    if is_browser_control_dry_run(payload):
        return {
            "ok": True,
            "dry_run": True,
            "status": "session_active",
            "current_step": f"목록조회 테스트 dry-run year={year} size={size}",
        }

    api_base_url = _resolve_tax_api_base_url(payload)
    web_path = _env_text("INCOME33_DASHBOARD_URL", "https://newta.3o3.co.kr/tasks/git")

    def _run(page: Any, debug_port: int) -> dict[str, Any]:
        if not str(page.url).startswith("https://newta.3o3.co.kr"):
            page.goto(web_path, wait_until="domcontentloaded")

        office_url = f"{api_base_url}/api/ta/info/v1/tax-offices/simple"
        common_headers = {
            "accept": "application/json, text/plain, */*",
            "x-web-path": web_path,
        }
        office_response = _browser_fetch_json(
            page,
            url=office_url,
            headers={**common_headers, "x-host": "GROUND"},
        )
        office_json = office_response.get("json") or {}
        if not office_response.get("ok") or not office_json.get("ok"):
            raise RuntimeError(f"office lookup failed status={office_response.get('status')}")
        offices = office_json.get("data") or []
        if not offices:
            raise RuntimeError("office lookup returned no offices")
        office_id = int(payload.get("office_id") or offices[0]["id"])

        list_url = _taxdoc_filter_search_url(
            api_base_url=api_base_url,
            office_id=office_id,
            year=year,
            page=page_index,
            size=size,
        )
        list_response = _browser_fetch_json(
            page,
            url=list_url,
            headers={**common_headers, "x-host": "GIT"},
        )
        list_json = list_response.get("json") or {}
        if not list_response.get("ok") or not list_json.get("ok"):
            raise RuntimeError(f"taxdoc list failed status={list_response.get('status')}")
        data = list_json.get("data") or {}
        content = data.get("content") or []
        tax_doc_ids = [int(row["taxDocId"]) for row in content if row.get("taxDocId") is not None]
        total_elements = int(data.get("totalElements") or len(tax_doc_ids))
        total_pages = int(data.get("totalPages") or 1)
        current_step = (
            f"목록조회 테스트 {len(tax_doc_ids)}/{total_elements}건 "
            f"현재 {page_index + 1}/{total_pages}페이지 총 {total_pages}페이지 officeId={office_id}"
        )
        return {
            "ok": True,
            "dry_run": False,
            "status": "session_active",
            "current_step": current_step,
            "debug_port": debug_port,
            "office_id": office_id,
            "year": year,
            "page": page_index,
            "size": size,
            "total_elements": total_elements,
            "total_pages": total_pages,
            "count": len(tax_doc_ids),
            "tax_doc_ids": tax_doc_ids,
        }

    result = _run_in_cdp_session(bot_id, payload, _run)
    logger.info(
        "preview_expected_tax_send_targets_done bot_id=%s office_id=%s page=%s count=%s total=%s",
        bot_id,
        result.get("office_id"),
        result.get("page"),
        result.get("count"),
        result.get("total_elements"),
    )
    return result


def refresh_page(
    *,
    bot_id: str,
    payload: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    logger = logger or logging.getLogger("income33.agent.browser_control")
    payload = payload or {}
    refresh_url = resolve_refresh_url(payload)

    if is_browser_control_dry_run(payload):
        logger.info(
            "refresh_page_dry_run bot_id=%s debug_port=%s url=%s",
            bot_id,
            resolve_browser_debug_port(bot_id, payload),
            refresh_url,
        )
        return {
            "ok": True,
            "dry_run": True,
            "status": "session_active",
            "current_step": "session_refresh_dry_run",
            "url": refresh_url,
        }

    def _run(page: Any, debug_port: int) -> dict[str, Any]:
        page.goto(refresh_url, wait_until="domcontentloaded")
        return {
            "ok": True,
            "dry_run": False,
            "status": "session_active",
            "current_step": "session_refresh",
            "debug_port": debug_port,
            "url": page.url,
        }

    result = _run_in_cdp_session(bot_id, payload, _run)
    logger.info(
        "refresh_page_done bot_id=%s debug_port=%s url=%s",
        bot_id,
        result.get("debug_port"),
        result.get("url"),
    )
    return result


def resolve_refresh_interval_seconds() -> int:
    return max(1, _env_int("INCOME33_REFRESH_INTERVAL_SECONDS", DEFAULT_REFRESH_INTERVAL_SECONDS))


def is_refresh_enabled() -> bool:
    return _env_bool("INCOME33_REFRESH_ENABLED", False)


def is_keepalive_due(last_refresh_monotonic: float | None, now_monotonic: float, interval: int) -> bool:
    if last_refresh_monotonic is None:
        return True
    return (now_monotonic - last_refresh_monotonic) >= max(1, interval)
