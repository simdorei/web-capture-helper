import json

from fastapi.testclient import TestClient

from web_capture_helper.server import CaptureEvent, create_app, sanitize_event


def test_sanitize_event_redacts_sensitive_headers():
    event = CaptureEvent(
        url="https://example.test/api",
        method="post",
        request_headers={
            "Cookie": "SESSION=abc; XSRF-TOKEN=def",
            "Authorization": "Bearer secret",
            "Content-Type": "application/json",
            "X-Custom-Session-Id": "secret-session",
        },
        request_body="{}",
    )

    data = sanitize_event(event)

    assert data["method"] == "POST"
    assert data["request_headers"]["Cookie"]["redacted"] is True
    assert data["request_headers"]["Cookie"]["cookie_names"] == ["SESSION", "XSRF-TOKEN"]
    assert data["request_headers"]["Authorization"]["redacted"] is True
    assert data["request_headers"]["X-Custom-Session-Id"]["redacted"] is True
    assert data["request_headers"]["Content-Type"] == "application/json"


def test_capture_endpoint_writes_jsonl(tmp_path, monkeypatch):
    import web_capture_helper.server as server

    monkeypatch.setattr(server, "DEFAULT_CAPTURE_DIR", tmp_path)
    app = create_app()
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
    files = list(tmp_path.glob("*/captures.jsonl"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "example.test" in text
    assert "A=1" not in text


def test_latest_returns_recent_items(tmp_path, monkeypatch):
    import web_capture_helper.server as server

    monkeypatch.setattr(server, "DEFAULT_CAPTURE_DIR", tmp_path)
    app = create_app()
    client = TestClient(app)

    client.post("/capture", json={"url": "https://example.test/one"})
    client.post("/capture", json={"url": "https://example.test/two"})

    response = client.get("/latest?limit=1")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["url"] == "https://example.test/two"
