from __future__ import annotations

import getpass
import os
import re
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

APP_NAME = "web-capture-helper"
Runner = Callable[[], None]


def _set_private_file_permissions(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        # Best-effort only (Windows/ACL environments may ignore chmod semantics).
        pass


def _safe_path_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", value).strip("._")
    return cleaned or "unknown-user"


def _load_app_and_runner() -> tuple[Any, Runner]:
    """Load the ASGI app/runner in both package and script execution modes."""

    try:
        from .server import app, run
    except ImportError:
        # Direct script execution (`python src/web_capture_helper/main.py`) and
        # some frozen entrypoint paths do not have package-relative context.
        package_root = Path(__file__).resolve().parents[1]
        if str(package_root) not in sys.path:
            sys.path.insert(0, str(package_root))
        from web_capture_helper.server import app, run

    return app, run


def _resolve_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def _resolve_log_dir() -> Path:
    base_dir = _resolve_base_dir()
    override = os.environ.get("WEB_CAPTURE_HELPER_LOG_DIR")
    if not override:
        return base_dir / "logs"

    candidate = Path(override).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()


def _crash_log_path() -> Path:
    log_dir = _resolve_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "web-capture-helper-crash.log"


def _write_crash_log(exc: BaseException) -> Path:
    path = _crash_log_path()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n=== web-capture-helper startup crash ({datetime.now(timezone.utc).isoformat()}) ===\n")
        fh.write(f"executable={sys.executable}\n")
        fh.write(f"frozen={bool(getattr(sys, 'frozen', False))}\n")
        fh.write(f"cwd={Path.cwd()}\n")
        fh.write(f"log_dir={_resolve_log_dir()}\n")
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=fh)
    _set_private_file_permissions(path)
    return path


def _write_fallback_crash_log(exc: BaseException, original_error: BaseException) -> Path:
    try:
        user_segment = _safe_path_segment(getpass.getuser() or "unknown-user")
    except Exception:
        user_segment = "unknown-user"

    fallback_dir = Path(tempfile.gettempdir()) / APP_NAME / user_segment / "logs"
    fallback_dir.mkdir(parents=True, exist_ok=True)

    fd, raw_path = tempfile.mkstemp(prefix="web-capture-helper-crash-", suffix=".log", dir=fallback_dir)
    fallback_path = Path(raw_path)

    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(f"\n=== web-capture-helper fallback startup crash ({datetime.now(timezone.utc).isoformat()}) ===\n")
        fh.write(f"fallback_reason={type(original_error).__name__}: {original_error}\n")
        fh.write(f"executable={sys.executable}\n")
        fh.write(f"frozen={bool(getattr(sys, 'frozen', False))}\n")
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=fh)

    _set_private_file_permissions(fallback_path)
    return fallback_path


_APP_LOAD_ERROR: BaseException | None = None


async def _unavailable_app(_scope: Any, _receive: Any, _send: Any) -> None:
    if _APP_LOAD_ERROR is None:
        raise RuntimeError("web-capture-helper app is unavailable")
    raise RuntimeError("web-capture-helper app failed to load; run module directly to collect crash logs") from _APP_LOAD_ERROR


def _safe_load_app() -> Any:
    global _APP_LOAD_ERROR
    try:
        loaded_app, _ = _load_app_and_runner()
        _APP_LOAD_ERROR = None
        return loaded_app
    except Exception as exc:
        # Keep import-time errors from crashing immediately so `main()` can log
        # startup failures to crash log with a clear message.
        _APP_LOAD_ERROR = exc
        return _unavailable_app


app = _safe_load_app()


def _handle_startup_failure(exc: BaseException) -> int:
    crash_log: Path | None = None
    log_write_error: BaseException | None = None

    try:
        crash_log = _write_crash_log(exc)
    except Exception as write_error:
        log_write_error = write_error
        try:
            crash_log = _write_fallback_crash_log(exc, write_error)
        except Exception as fallback_error:
            log_write_error = fallback_error
            crash_log = None

    print(f"{APP_NAME} failed to start.")
    if crash_log is not None:
        print(f"Crash log: {crash_log}")
        print(f"Please send this file for support: {crash_log}")
    else:
        print("Crash log could not be written to disk.")
        print("Please share the console output for support.")
    if log_write_error is not None:
        print(f"Crash-log write fallback triggered: {type(log_write_error).__name__}: {log_write_error}")

    traceback.print_exception(type(exc), exc, exc.__traceback__)

    if getattr(sys, "frozen", False):
        try:
            input("Press Enter to close...")
        except EOFError:
            pass

    return 1


def main() -> int:
    try:
        _, run_server = _load_app_and_runner()
        run_server()
        return 0
    except KeyboardInterrupt:
        raise
    except SystemExit as exc:
        if exc.code in (0, None):
            return 0
        return _handle_startup_failure(exc)
    except Exception as exc:
        return _handle_startup_failure(exc)


if __name__ == "__main__":
    raise SystemExit(main())
