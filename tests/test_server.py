from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from web_capture_helper.server import (
    CaptureEvent,
    build_runtime_config,
    create_app,
    sanitize_event,
)


def test_sanitize_event_redacts_sensitive_headers():
    event = CaptureEvent(
        url="https://example.test/api",
        method="post",
        request_headers={
            "Cookie": "SESSION=abc; XSRF-TOKEN=***",
            "Authorization": "Bearer secret",
            "Content-Type": "application/json",
            "X-Custom-Session-Id": "secret-session",
        },
        request_body="{}",
    )

    data = sanitize_event(event, max_body_chars=500000)

    assert data["method"] == "POST"
    assert data["request_headers"]["Cookie"]["redacted"] is True
    assert data["request_headers"]["Cookie"]["cookie_names"] == ["SESSION", "XSRF-TOKEN"]
    assert data["request_headers"]["Authorization"]["redacted"] is True
    assert data["request_headers"]["X-Custom-Session-Id"]["redacted"] is True
    assert data["request_headers"]["Content-Type"] == "application/json"


def test_capture_endpoint_writes_jsonl(tmp_path):
    config = build_runtime_config(env={}, cwd=tmp_path, frozen=False)
    app = create_app(config=config, logger=logging.getLogger("web-capture-helper-test-capture"))
    client = TestClient(app)

    response = client.post(
        "/capture",
        json={
            "url": "https://example.test/api",
            "method": "GET",
            "request_headers": {"Cookie": "A=1"},
            "response_status": 200,
            "response_body": "ok",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    capture_file = config.paths.capture_file
    assert capture_file.exists()
    text = capture_file.read_text(encoding="utf-8")
    assert "example.test" in text
    assert "A=1" not in text


def test_latest_returns_recent_items(tmp_path):
    config = build_runtime_config(env={}, cwd=tmp_path, frozen=False)
    app = create_app(config=config, logger=logging.getLogger("web-capture-helper-test-latest"))
    client = TestClient(app)

    client.post("/capture", json={"url": "https://example.test/one"})
    client.post("/capture", json={"url": "https://example.test/two"})

    response = client.get("/latest?limit=1")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["url"] == "https://example.test/two"


def test_zip_endpoint_returns_archive(tmp_path):
    config = build_runtime_config(env={}, cwd=tmp_path, frozen=False)
    app = create_app(config=config, logger=logging.getLogger("web-capture-helper-test-zip"))
    client = TestClient(app)

    client.post("/capture", json={"url": "https://example.test/zip"})
    response = client.get("/zip")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.content.startswith(b"PK")


def test_capture_validation_error_returns_422(tmp_path):
    config = build_runtime_config(env={}, cwd=tmp_path, frozen=False)
    app = create_app(config=config, logger=logging.getLogger("web-capture-helper-test-validation"))
    client = TestClient(app)

    response = client.post("/capture", json={"method": "GET"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "validation error" in detail.lower()
