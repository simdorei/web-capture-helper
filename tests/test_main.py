from __future__ import annotations

import web_capture_helper.main as main_module


def test_crash_log_path_in_frozen_mode_respects_relative_log_dir_override(tmp_path, monkeypatch):
    exe_dir = tmp_path / "release"
    exe_dir.mkdir()
    exe_path = exe_dir / "web-capture-helper.exe"

    monkeypatch.setattr(main_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(main_module.sys, "executable", str(exe_path), raising=False)
    monkeypatch.setenv("WEB_CAPTURE_HELPER_LOG_DIR", "custom-logs")

    crash_path = main_module._crash_log_path()

    assert crash_path == exe_dir / "custom-logs" / "web-capture-helper-crash.log"


def test_main_handles_loader_failure_with_crash_log_and_pause_on_frozen(tmp_path, monkeypatch):
    exe_dir = tmp_path / "release"
    exe_dir.mkdir()
    exe_path = exe_dir / "web-capture-helper.exe"

    monkeypatch.setattr(main_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(main_module.sys, "executable", str(exe_path), raising=False)
    monkeypatch.setenv("WEB_CAPTURE_HELPER_LOG_DIR", "logs")

    def failing_loader():
        raise RuntimeError("loader failed")

    monkeypatch.setattr(main_module, "_load_app_and_runner", failing_loader)

    prompts: list[str] = []

    def fake_input(message: str) -> str:
        prompts.append(message)
        return ""

    monkeypatch.setattr("builtins.input", fake_input)

    exit_code = main_module.main()

    assert exit_code == 1
    assert prompts and "Press Enter to close" in prompts[0]

    crash_log_path = exe_dir / "logs" / "web-capture-helper-crash.log"
    assert crash_log_path.exists()

    crash_text = crash_log_path.read_text(encoding="utf-8")
    assert "loader failed" in crash_text
    assert "frozen=True" in crash_text


def test_main_successful_runner_returns_zero(monkeypatch):
    def successful_loader():
        return object(), lambda: None

    monkeypatch.setattr(main_module, "_load_app_and_runner", successful_loader)

    assert main_module.main() == 0


def test_main_logs_nonzero_system_exit_as_startup_failure(tmp_path, monkeypatch):
    exe_dir = tmp_path / "release"
    exe_dir.mkdir()
    exe_path = exe_dir / "web-capture-helper.exe"

    monkeypatch.setattr(main_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(main_module.sys, "executable", str(exe_path), raising=False)
    monkeypatch.setenv("WEB_CAPTURE_HELPER_LOG_DIR", "logs")

    def loader_with_system_exit():
        def run_server() -> None:
            raise SystemExit(1)

        return object(), run_server

    monkeypatch.setattr(main_module, "_load_app_and_runner", loader_with_system_exit)
    monkeypatch.setattr("builtins.input", lambda _="": "")

    exit_code = main_module.main()

    assert exit_code == 1
    crash_log_path = exe_dir / "logs" / "web-capture-helper-crash.log"
    assert crash_log_path.exists()
    crash_text = crash_log_path.read_text(encoding="utf-8")
    assert "SystemExit" in crash_text


def test_main_uses_fallback_crash_log_when_primary_write_fails(tmp_path, monkeypatch):
    fallback_log = tmp_path / "fallback" / "web-capture-helper-crash.log"

    def failing_loader():
        raise RuntimeError("startup exploded")

    monkeypatch.setattr(main_module, "_load_app_and_runner", failing_loader)
    monkeypatch.setattr(
        main_module,
        "_write_crash_log",
        lambda _exc: (_ for _ in ()).throw(PermissionError("no write permission")),
    )

    def fake_fallback_writer(exc: BaseException, original_error: BaseException):
        fallback_log.parent.mkdir(parents=True, exist_ok=True)
        fallback_log.write_text(f"{type(exc).__name__}: {exc}\n{type(original_error).__name__}: {original_error}", encoding="utf-8")
        return fallback_log

    monkeypatch.setattr(main_module, "_write_fallback_crash_log", fake_fallback_writer, raising=False)

    exit_code = main_module.main()

    assert exit_code == 1
    assert fallback_log.exists()
    text = fallback_log.read_text(encoding="utf-8")
    assert "startup exploded" in text
    assert "no write permission" in text


def test_safe_path_segment_removes_traversal_characters():
    assert main_module._safe_path_segment("../bad user") == "bad_user"
    assert main_module._safe_path_segment("..") == "unknown-user"
