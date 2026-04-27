from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from web_capture_helper.server import build_runtime_config, configure_logging, create_app, summarize_capture_for_log


def test_build_runtime_config_source_mode_uses_cwd_defaults(tmp_path):
    now = datetime(2026, 4, 27, 2, 0, tzinfo=timezone.utc)

    config = build_runtime_config(env={}, cwd=tmp_path, frozen=False, now=now)

    assert config.paths.frozen is False
    assert config.paths.base_dir == tmp_path
    assert config.paths.capture_dir == tmp_path / "captures"
    assert config.paths.log_dir == tmp_path / "logs"
    assert config.paths.capture_file == tmp_path / "captures" / "20260427" / "captures.jsonl"
    assert config.paths.log_file == tmp_path / "logs" / "web-capture-helper.log"


def test_build_runtime_config_frozen_mode_uses_executable_directory(tmp_path):
    exe_dir = tmp_path / "release"
    exe_dir.mkdir()
    executable = exe_dir / "web-capture-helper.exe"
    now = datetime(2026, 4, 27, 2, 0, tzinfo=timezone.utc)

    config = build_runtime_config(
        env={},
        cwd=tmp_path / "elsewhere",
        executable=executable,
        frozen=True,
        now=now,
    )

    assert config.paths.frozen is True
    assert config.paths.base_dir == exe_dir
    assert config.paths.capture_dir == exe_dir / "captures"
    assert config.paths.log_dir == exe_dir / "logs"
    assert config.paths.capture_file == exe_dir / "captures" / "20260427" / "captures.jsonl"
    assert config.paths.log_file == exe_dir / "logs" / "web-capture-helper.log"


def test_build_runtime_config_honors_env_overrides(tmp_path):
    env = {
        "WEB_CAPTURE_HELPER_DIR": str(tmp_path / "custom-captures"),
        "WEB_CAPTURE_HELPER_LOG_DIR": str(tmp_path / "custom-logs"),
        "WEB_CAPTURE_HELPER_PORT": "49123",
    }

    config = build_runtime_config(env=env, cwd=tmp_path, frozen=False)

    assert config.port == 49123
    assert config.paths.capture_dir == tmp_path / "custom-captures"
    assert config.paths.log_dir == tmp_path / "custom-logs"


def test_build_runtime_config_resolves_relative_overrides_from_base_dir(tmp_path):
    env = {
        "WEB_CAPTURE_HELPER_DIR": "relative-captures",
        "WEB_CAPTURE_HELPER_LOG_DIR": "relative-logs",
    }

    config = build_runtime_config(env=env, cwd=tmp_path / "work", frozen=False)

    assert config.paths.capture_dir == (tmp_path / "work" / "relative-captures")
    assert config.paths.log_dir == (tmp_path / "work" / "relative-logs")


def test_build_runtime_config_resolves_relative_overrides_from_exe_dir_when_frozen(tmp_path):
    exe_dir = tmp_path / "release"
    exe_dir.mkdir()
    executable = exe_dir / "web-capture-helper.exe"
    env = {
        "WEB_CAPTURE_HELPER_DIR": "relative-captures",
        "WEB_CAPTURE_HELPER_LOG_DIR": "relative-logs",
    }

    config = build_runtime_config(
        env=env,
        cwd=tmp_path / "somewhere-else",
        executable=executable,
        frozen=True,
    )

    assert config.paths.capture_dir == (exe_dir / "relative-captures")
    assert config.paths.log_dir == (exe_dir / "relative-logs")


def test_health_reports_runtime_paths_and_frozen_mode(tmp_path):
    env = {
        "WEB_CAPTURE_HELPER_PORT": "43111",
    }
    config = build_runtime_config(env=env, cwd=tmp_path, frozen=False)
    logger = logging.getLogger("web-capture-helper-test-health")

    app = create_app(config=config, logger=logger)
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["port"] == 43111
    assert payload["frozen"] is False
    assert payload["capture_dir"] == str(tmp_path / "captures")
    assert payload["log_dir"] == str(tmp_path / "logs")
    assert payload["capture_file"].endswith("captures/" + datetime.now(timezone.utc).strftime("%Y%m%d") + "/captures.jsonl")
    assert payload["log_file"].endswith("logs/web-capture-helper.log")


def test_summarize_capture_for_log_excludes_sensitive_fields():
    event = {
        "event_id": "event-1",
        "method": "POST",
        "url": "https://user:pass@example.test/api/token/abc?session=secret#frag",
        "response_status": 200,
        "duration_ms": 12.4,
        "request_body": "password=supersecret",
        "response_body": "token=abc",
        "request_headers": {"Authorization": "Bearer abc"},
    }

    summary = summarize_capture_for_log(event)

    as_text = json.dumps(summary)
    assert "request_body" not in summary
    assert "response_body" not in summary
    assert "Authorization" not in as_text
    assert "supersecret" not in as_text
    assert "token=abc" not in as_text
    assert "user:pass" not in as_text
    assert "session=secret" not in as_text
    assert summary["event_id"] == "event-1"
    assert summary["method"] == "POST"
    assert summary["url"] == "https://example.test/"


def test_configured_route_logging_excludes_sensitive_fields(tmp_path):
    config = build_runtime_config(env={}, cwd=tmp_path, frozen=False)
    logger = configure_logging(
        config.paths,
        env={},
        logger_name="web-capture-helper-test-file-logging",
    )
    app = create_app(config=config, logger=logger)

    with TestClient(app) as client:
        response = client.post(
            "/capture",
            json={
                "url": "https://example.test/api?token=abc123",
                "method": "POST",
                "request_headers": {"Authorization": "Bearer top-secret", "Cookie": "A=1"},
                "request_body": "password=supersecret",
                "response_body": "session=secret",
                "response_status": 200,
            },
        )

    assert response.status_code == 200
    for handler in logger.handlers:
        handler.flush()

    log_text = config.paths.log_file.read_text(encoding="utf-8")
    assert "capture_saved" in log_text
    assert "https://example.test/" in log_text
    assert "/api" not in log_text
    assert "token=abc123" not in log_text
    assert "top-secret" not in log_text
    assert "A=1" not in log_text
    assert "supersecret" not in log_text
    assert "session=secret" not in log_text
