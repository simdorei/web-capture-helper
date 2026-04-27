from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit
from zipfile import ZIP_DEFLATED, ZipFile

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError

APP_NAME = "web-capture-helper"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 33133
DEFAULT_MAX_BODY_CHARS = 500_000
DEFAULT_CAPTURE_FILENAME = "captures.jsonl"
DEFAULT_LOG_FILENAME = "web-capture-helper.log"
DEFAULT_LOG_MAX_BYTES = 2_000_000
DEFAULT_LOG_BACKUP_COUNT = 3

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


@dataclass(frozen=True)
class RuntimePaths:
    base_dir: Path
    capture_dir: Path
    log_dir: Path
    capture_file: Path
    log_file: Path
    frozen: bool


@dataclass(frozen=True)
class RuntimeConfig:
    host: str
    port: int
    max_body_chars: int
    paths: RuntimePaths


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


def _capture_file_for_date(capture_dir: Path, now: datetime | None = None) -> Path:
    now_dt = now or datetime.now(timezone.utc)
    date_part = now_dt.strftime("%Y%m%d")
    return capture_dir / date_part / DEFAULT_CAPTURE_FILENAME


def _resolve_base_dir(
    *,
    cwd: Path | None = None,
    executable: str | Path | None = None,
    frozen: bool | None = None,
) -> tuple[Path, bool]:
    frozen_mode = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)

    if frozen_mode:
        executable_path = Path(executable or sys.executable).expanduser().resolve()
        return executable_path.parent, True

    return (cwd or Path.cwd()).expanduser().resolve(), False


def _resolve_override_path(override: str | None, fallback: Path, *, base_dir: Path) -> Path:
    if not override:
        return fallback

    candidate = Path(override).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()


def _int_from_env(env: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(env.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def build_runtime_config(
    env: Mapping[str, str] | None = None,
    *,
    cwd: Path | None = None,
    executable: str | Path | None = None,
    frozen: bool | None = None,
    now: datetime | None = None,
) -> RuntimeConfig:
    env_map = os.environ if env is None else env
    base_dir, frozen_mode = _resolve_base_dir(cwd=cwd, executable=executable, frozen=frozen)

    capture_dir = _resolve_override_path(
        env_map.get("WEB_CAPTURE_HELPER_DIR"),
        base_dir / "captures",
        base_dir=base_dir,
    )
    log_dir = _resolve_override_path(
        env_map.get("WEB_CAPTURE_HELPER_LOG_DIR"),
        base_dir / "logs",
        base_dir=base_dir,
    )

    host = env_map.get("WEB_CAPTURE_HELPER_HOST", DEFAULT_HOST)
    port = _int_from_env(env_map, "WEB_CAPTURE_HELPER_PORT", DEFAULT_PORT)
    max_body_chars = _int_from_env(env_map, "WEB_CAPTURE_HELPER_MAX_BODY_CHARS", DEFAULT_MAX_BODY_CHARS)

    capture_file = _capture_file_for_date(capture_dir, now=now)
    log_file = log_dir / DEFAULT_LOG_FILENAME

    return RuntimeConfig(
        host=host,
        port=port,
        max_body_chars=max_body_chars,
        paths=RuntimePaths(
            base_dir=base_dir,
            capture_dir=capture_dir,
            log_dir=log_dir,
            capture_file=capture_file,
            log_file=log_file,
            frozen=frozen_mode,
        ),
    )


def ensure_runtime_dirs(paths: RuntimePaths) -> None:
    paths.capture_file.parent.mkdir(parents=True, exist_ok=True)
    paths.log_dir.mkdir(parents=True, exist_ok=True)


def configure_logging(
    paths: RuntimePaths,
    *,
    env: Mapping[str, str] | None = None,
    logger_name: str = APP_NAME,
) -> logging.Logger:
    env_map = os.environ if env is None else env
    max_bytes = _int_from_env(env_map, "WEB_CAPTURE_HELPER_LOG_MAX_BYTES", DEFAULT_LOG_MAX_BYTES)
    backup_count = _int_from_env(env_map, "WEB_CAPTURE_HELPER_LOG_BACKUP_COUNT", DEFAULT_LOG_BACKUP_COUNT)

    ensure_runtime_dirs(paths)

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        paths.log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    logger.info("logger_configured log_file=%s", paths.log_file)
    return logger


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


def _truncate(value: Any, max_body_chars: int) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        if len(value) <= max_body_chars:
            return value
        return value[:max_body_chars] + f"\n...[truncated {len(value) - max_body_chars} chars]"
    return value


def _model_to_dict(event: CaptureEvent) -> dict[str, Any]:
    if hasattr(event, "model_dump"):
        return event.model_dump()
    return event.dict()


def sanitize_event(event: CaptureEvent, max_body_chars: int = DEFAULT_MAX_BODY_CHARS) -> dict[str, Any]:
    data = _model_to_dict(event)
    data["event_id"] = data.get("event_id") or str(uuid.uuid4())
    data["captured_at"] = data.get("captured_at") or utc_now_iso()
    data["method"] = (data.get("method") or "GET").upper()
    data["request_headers"] = _sanitize_headers(data.get("request_headers"))
    data["response_headers"] = _sanitize_headers(data.get("response_headers"))
    data["request_body"] = _truncate(data.get("request_body"), max_body_chars=max_body_chars)
    data["response_body"] = _truncate(data.get("response_body"), max_body_chars=max_body_chars)
    data.setdefault("notes", {})
    data["notes"]["helper_redaction"] = "cookie/auth/token/session/csrf-like headers redacted by web-capture-helper"
    return data


def _redact_url_for_log(url: str | None) -> str | None:
    if not url:
        return url

    try:
        parts = urlsplit(str(url))
    except Exception:
        return "<redacted-url>"

    if not parts.scheme or not parts.hostname:
        return "<redacted-url>"

    host = parts.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parts.port is not None:
        host = f"{host}:{parts.port}"

    return urlunsplit((parts.scheme, host, "/", "", ""))


def summarize_capture_for_log(event_data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event_data.get("event_id"),
        "source": event_data.get("source"),
        "method": event_data.get("method"),
        "url": _redact_url_for_log(str(event_data.get("url"))) if event_data.get("url") is not None else None,
        "response_status": event_data.get("response_status"),
        "duration_ms": event_data.get("duration_ms"),
        "error": event_data.get("error"),
    }


def capture_path(capture_dir: Path | None = None, now: datetime | None = None) -> Path:
    base_capture_dir = capture_dir or DEFAULT_CONFIG.paths.capture_dir
    path = _capture_file_for_date(base_capture_dir, now=now)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def create_capture_zip(capture_dir: Path) -> Path:
    capture_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="web-capture-helper-"))
    zip_path = tmp_dir / f"web-captures-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')}.zip"
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        for file_path in sorted(capture_dir.rglob("*")):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(capture_dir).as_posix())
    return zip_path


def create_app(config: RuntimeConfig | None = None, logger: logging.Logger | None = None) -> FastAPI:
    runtime = config or build_runtime_config()
    app_logger = logger or logging.getLogger(APP_NAME)

    def _capture_file(now: datetime | None = None) -> Path:
        path = _capture_file_for_date(runtime.paths.capture_dir, now=now)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        ensure_runtime_dirs(runtime.paths)
        app_logger.info(
            "startup host=%s port=%s frozen=%s capture_dir=%s log_dir=%s capture_file=%s log_file=%s",
            runtime.host,
            runtime.port,
            runtime.paths.frozen,
            runtime.paths.capture_dir,
            runtime.paths.log_dir,
            _capture_file(),
            runtime.paths.log_file,
        )
        if runtime.host not in {"127.0.0.1", "localhost", "::1"}:
            app_logger.warning(
                "non_loopback_bind host=%s /health reveals local paths; use only in trusted network",
                runtime.host,
            )
        yield

    app = FastAPI(title=APP_NAME, version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        path = _capture_file()
        return f"""
        <html><head><meta charset=\"utf-8\"><title>{APP_NAME}</title></head>
        <body style=\"font-family: sans-serif; line-height: 1.5; padding: 24px;\">
          <h1>{APP_NAME} running</h1>
          <p>Status: OK</p>
          <p>Capture file: <code>{path}</code></p>
          <p>Log file: <code>{runtime.paths.log_file}</code></p>
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
        path = _capture_file()
        return {
            "status": "ok",
            "host": runtime.host,
            "port": runtime.port,
            "frozen": runtime.paths.frozen,
            "capture_dir": str(runtime.paths.capture_dir),
            "log_dir": str(runtime.paths.log_dir),
            "capture_file": str(path),
            "log_file": str(runtime.paths.log_file),
            "max_body_chars": runtime.max_body_chars,
            "time": utc_now_iso(),
        }

    @app.post("/capture")
    async def capture(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception as exc:
            app_logger.warning("capture_invalid_json error=%s", exc.__class__.__name__)
            raise HTTPException(status_code=400, detail=f"invalid json: {exc}") from exc

        try:
            event = CaptureEvent(**payload)
        except ValidationError as exc:
            locations = [".".join(str(part) for part in err.get("loc", ())) for err in exc.errors()]
            app_logger.warning("capture_validation_error fields=%s", locations)
            raise HTTPException(status_code=422, detail="validation error: missing or invalid fields") from exc

        data = sanitize_event(event, max_body_chars=runtime.max_body_chars)
        path = _capture_file()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")

        log_data = summarize_capture_for_log(data)
        app_logger.info(
            "capture_saved event_id=%s method=%s url=%s status=%s duration_ms=%s error=%s",
            log_data.get("event_id"),
            log_data.get("method"),
            log_data.get("url"),
            log_data.get("response_status"),
            log_data.get("duration_ms"),
            bool(log_data.get("error")),
        )

        return JSONResponse({"ok": True, "event_id": data["event_id"], "capture_file": str(path)})

    @app.get("/latest")
    def latest(limit: int = 20) -> dict[str, Any]:
        if limit < 1 or limit > 200:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 200")

        path = _capture_file()
        if not path.exists():
            return {"items": [], "capture_file": str(path)}

        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        return {"items": [json.loads(line) for line in lines if line.strip()], "capture_file": str(path)}

    @app.get("/download")
    def download() -> FileResponse:
        path = _capture_file()
        if not path.exists():
            app_logger.warning("download_requested capture_file_missing=%s", path)
            raise HTTPException(status_code=404, detail="no capture file yet")

        app_logger.info("download_requested capture_file=%s", path)
        return FileResponse(path, media_type="application/jsonl", filename=path.name)

    @app.get("/zip")
    def zip_download() -> FileResponse:
        zip_path = create_capture_zip(runtime.paths.capture_dir)
        app_logger.info("zip_requested capture_dir=%s zip_file=%s", runtime.paths.capture_dir, zip_path)
        return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)

    return app


DEFAULT_CONFIG = build_runtime_config()
app = create_app(config=DEFAULT_CONFIG, logger=logging.getLogger(APP_NAME))


def run() -> None:
    runtime = build_runtime_config()
    logger = configure_logging(runtime.paths)
    runtime_app = create_app(config=runtime, logger=logger)

    logger.info(
        "run host=%s port=%s frozen=%s capture_dir=%s log_dir=%s",
        runtime.host,
        runtime.port,
        runtime.paths.frozen,
        runtime.paths.capture_dir,
        runtime.paths.log_dir,
    )

    print(APP_NAME)
    print(f"Listening on http://{runtime.host}:{runtime.port}")
    print(f"Captures directory: {runtime.paths.capture_dir.resolve()}")
    print(f"Log file: {runtime.paths.log_file.resolve()}")
    print(f"Open http://{runtime.host}:{runtime.port}/health to verify.")

    uvicorn.run(runtime_app, host=runtime.host, port=runtime.port, log_level="info", loop="asyncio", http="h11")


if __name__ == "__main__":
    run()
