from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
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
DEFAULT_CAPTURE_DIR = Path(os.environ.get("WEB_CAPTURE_HELPER_DIR", "captures"))
MAX_BODY_CHARS = int(os.environ.get("WEB_CAPTURE_HELPER_MAX_BODY_CHARS", "500000"))
HOST = os.environ.get("WEB_CAPTURE_HELPER_HOST", "127.0.0.1")
PORT = int(os.environ.get("WEB_CAPTURE_HELPER_PORT", "33133"))


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


def _extract_cookie_names(cookie_value: str) -> list[str]:
    names: list[str] = []
    for part in re.split(r";|,\s*(?=[^;,=]+=)", cookie_value):
        if "=" not in part:
            continue
        name = part.split("=", 1)[0].strip()
        if name and name.lower() not in {"path", "domain", "expires", "max-age", "secure", "httponly", "samesite"}:
            names.append(name)
    return sorted(set(names))


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


def _truncate(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        if len(value) <= MAX_BODY_CHARS:
            return value
        return value[:MAX_BODY_CHARS] + f"\n...[truncated {len(value) - MAX_BODY_CHARS} chars]"
    return value


def capture_path(capture_dir: Path | None = None) -> Path:
    capture_dir = capture_dir or DEFAULT_CAPTURE_DIR
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    folder = capture_dir / date_part
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "captures.jsonl"


def _model_to_dict(event: CaptureEvent) -> dict[str, Any]:
    if hasattr(event, "model_dump"):
        return event.model_dump()
    return event.dict()


def sanitize_event(event: CaptureEvent) -> dict[str, Any]:
    data = _model_to_dict(event)
    data["event_id"] = data.get("event_id") or str(uuid.uuid4())
    data["captured_at"] = data.get("captured_at") or utc_now_iso()
    data["method"] = (data.get("method") or "GET").upper()
    data["request_headers"] = _sanitize_headers(data.get("request_headers"))
    data["response_headers"] = _sanitize_headers(data.get("response_headers"))
    data["request_body"] = _truncate(data.get("request_body"))
    data["response_body"] = _truncate(data.get("response_body"))
    data.setdefault("notes", {})
    data["notes"]["helper_redaction"] = "cookie/auth/token/session/csrf-like headers redacted by web-capture-helper"
    return data


def create_capture_zip(capture_dir: Path = DEFAULT_CAPTURE_DIR) -> Path:
    capture_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="web-capture-helper-"))
    zip_path = tmp_dir / f"web-captures-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')}.zip"
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        for file_path in sorted(capture_dir.rglob("*")):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(capture_dir).as_posix())
    return zip_path


def create_app() -> FastAPI:
    app = FastAPI(title="web-capture-helper", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        path = capture_path()
        return f"""
        <html><head><meta charset=\"utf-8\"><title>web-capture-helper</title></head>
        <body style=\"font-family: sans-serif; line-height: 1.5; padding: 24px;\">
          <h1>web-capture-helper running</h1>
          <p>Status: OK</p>
          <p>Capture file: <code>{path}</code></p>
          <ul>
            <li><a href=\"/health\">/health</a></li>
            <li><a href=\"/latest\">/latest</a></li>
            <li><a href=\"/download\">/download</a></li>
            <li><a href=\"/zip\">/zip</a></li>
          </ul>
        </body></html>
        """

    @app.get("/health")
    def health() -> dict[str, Any]:
        path = capture_path()
        return {
            "status": "ok",
            "capture_file": str(path),
            "max_body_chars": MAX_BODY_CHARS,
            "host": HOST,
            "port": PORT,
            "time": utc_now_iso(),
        }

    @app.post("/capture")
    async def capture(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid json: {exc}") from exc

        event = CaptureEvent(**payload)
        data = sanitize_event(event)
        path = capture_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
        return JSONResponse({"ok": True, "event_id": data["event_id"], "capture_file": str(path)})

    @app.get("/latest")
    def latest(limit: int = 20) -> dict[str, Any]:
        if limit < 1 or limit > 200:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
        path = capture_path()
        if not path.exists():
            return {"items": [], "capture_file": str(path)}
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        return {"items": [json.loads(line) for line in lines if line.strip()], "capture_file": str(path)}

    @app.get("/download")
    def download() -> FileResponse:
        path = capture_path()
        if not path.exists():
            raise HTTPException(status_code=404, detail="no capture file yet")
        return FileResponse(path, media_type="application/jsonl", filename=path.name)

    @app.get("/zip")
    def zip_download() -> FileResponse:
        zip_path = create_capture_zip()
        return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)

    return app


app = create_app()


def run() -> None:
    DEFAULT_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    print("web-capture-helper")
    print(f"Listening on http://{HOST}:{PORT}")
    print(f"Captures directory: {DEFAULT_CAPTURE_DIR.resolve()}")
    print("Open http://127.0.0.1:33133/health to verify.")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info", loop="asyncio", http="h11")


if __name__ == "__main__":
    run()
