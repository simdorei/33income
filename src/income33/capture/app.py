from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

SENSITIVE_HEADER_NAMES = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "set-cookie",
    "x-csrf-token",
    "x-xsrf-token",
    "x-auth-token",
}
PARTIAL_SENSITIVE_HEADER_PATTERNS = ("token", "secret", "session", "auth", "csrf", "xsrf")
DEFAULT_CAPTURE_DIR = Path(os.environ.get("INCOME33_CAPTURE_DIR", "captures"))
MAX_BODY_CHARS = int(os.environ.get("INCOME33_CAPTURE_MAX_BODY_CHARS", "500000"))


class CaptureEvent(BaseModel):
    event_id: str | None = None
    captured_at: str | None = None
    sequence: int | None = None
    source: str = Field(default="browser-snippet")
    page_url: str | None = None
    method: str | None = None
    url: str
    request_headers: dict[str, Any] = Field(default_factory=dict)
    request_body: Any = None
    response_status: int | None = None
    response_headers: dict[str, Any] = Field(default_factory=dict)
    response_body: Any = None
    duration_ms: float | None = None
    error: str | None = None
    notes: dict[str, Any] = Field(default_factory=dict)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_sensitive_header(name: str) -> bool:
    low = name.lower()
    if low in SENSITIVE_HEADER_NAMES:
        return True
    return any(pattern in low for pattern in PARTIAL_SENSITIVE_HEADER_PATTERNS)


def _sanitize_headers(headers: dict[str, Any] | None) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in (headers or {}).items():
        key_str = str(key)
        if _is_sensitive_header(key_str):
            if key_str.lower() in {"cookie", "set-cookie"}:
                sanitized[key_str] = {
                    "redacted": True,
                    "cookie_names": _extract_cookie_names(str(value)),
                }
            else:
                sanitized[key_str] = {"redacted": True, "present": bool(value)}
        else:
            sanitized[key_str] = value
    return sanitized


def _extract_cookie_names(cookie_value: str) -> list[str]:
    names: list[str] = []
    # Handles Cookie: a=1; b=2 and Set-Cookie-ish lines conservatively.
    for part in re.split(r";|,\s*(?=[^;,=]+=)", cookie_value):
        if "=" not in part:
            continue
        name = part.split("=", 1)[0].strip()
        if name and name.lower() not in {"path", "domain", "expires", "max-age", "secure", "httponly", "samesite"}:
            names.append(name)
    return sorted(set(names))


def _truncate(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        if len(value) <= MAX_BODY_CHARS:
            return value
        return value[:MAX_BODY_CHARS] + f"\n...[truncated {len(value) - MAX_BODY_CHARS} chars]"
    return value


def _capture_path(capture_dir: Path | None = None) -> Path:
    capture_dir = capture_dir or DEFAULT_CAPTURE_DIR
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    folder = capture_dir / date_part
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "captures.jsonl"


def sanitize_event(event: CaptureEvent) -> dict[str, Any]:
    data = event.model_dump()
    data["event_id"] = data.get("event_id") or str(uuid.uuid4())
    data["captured_at"] = data.get("captured_at") or utc_now_iso()
    data["method"] = (data.get("method") or "GET").upper()
    data["request_headers"] = _sanitize_headers(data.get("request_headers"))
    data["response_headers"] = _sanitize_headers(data.get("response_headers"))
    data["request_body"] = _truncate(data.get("request_body"))
    data["response_body"] = _truncate(data.get("response_body"))
    data.setdefault("notes", {})
    data["notes"]["helper_redaction"] = "cookie/auth/token/session/csrf-like headers redacted by local helper"
    return data


def create_app() -> FastAPI:
    app = FastAPI(title="33income Local Capture Helper", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        path = _capture_path()
        return {
            "status": "ok",
            "capture_file": str(path),
            "max_body_chars": MAX_BODY_CHARS,
            "time": utc_now_iso(),
        }

    @app.post("/capture")
    async def capture(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception as exc:  # pragma: no cover - defensive
            raise HTTPException(status_code=400, detail=f"invalid json: {exc}") from exc

        event = CaptureEvent.model_validate(payload)
        data = sanitize_event(event)
        path = _capture_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
        return JSONResponse({"ok": True, "event_id": data["event_id"], "capture_file": str(path)})

    @app.get("/latest")
    def latest(limit: int = 20) -> dict[str, Any]:
        if limit < 1 or limit > 200:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
        path = _capture_path()
        if not path.exists():
            return {"items": [], "capture_file": str(path)}
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        return {"items": [json.loads(line) for line in lines if line.strip()], "capture_file": str(path)}

    @app.get("/download")
    def download() -> FileResponse:
        path = _capture_path()
        if not path.exists():
            raise HTTPException(status_code=404, detail="no capture file yet")
        return FileResponse(path, media_type="application/jsonl", filename=path.name)

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("income33.capture.app:app", host="127.0.0.1", port=33133, reload=False)
