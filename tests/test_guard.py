"""The API answers this computer's own pages only. See api/guard.py."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from racecraft.api import guard
from racecraft.api.app import app
from racecraft.live import recorder

LOCAL = "http://127.0.0.1"


@pytest.fixture
def client():
    return TestClient(app, base_url=LOCAL)


@pytest.mark.parametrize("host, name", [
    ("127.0.0.1:47621", "127.0.0.1"),
    ("LOCALHOST:5173", "localhost"),
    ("[::1]:8000", "::1"),
    ("127.0.0.1", "127.0.0.1"),
    ("evil.example@127.0.0.1", "evil.example@127.0.0.1"),
    ("[::1", ""),
])
def test_hostname_drops_the_port_and_nothing_else(host, name):
    assert guard.hostname(host) == name


def test_a_local_request_is_answered_with_the_security_headers(client):
    response = client.get("/api/circuits")
    assert response.status_code == 200
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_errors_carry_the_headers_too(client):
    response = client.get("/api/no-such-thing")
    assert response.status_code == 404
    assert response.headers["x-content-type-options"] == "nosniff"


def test_another_host_is_refused():
    """DNS rebinding: another site's name pointed at 127.0.0.1."""
    response = TestClient(app, base_url="http://rebind.example").get("/api/circuits")
    assert response.status_code == 403
    assert "not this computer" in response.json()["detail"]
    assert response.headers["x-frame-options"] == "DENY"


def test_a_host_can_be_allowed_on_purpose(monkeypatch):
    monkeypatch.setenv("RACECRAFT_ALLOWED_HOSTS", " 192.168.1.20 , racecraft.lan")
    for base in ("http://192.168.1.20:8000", "http://racecraft.lan"):
        assert TestClient(app, base_url=base).get("/api/circuits").status_code == 200
    assert TestClient(app, base_url="http://other.lan").get("/api/circuits").status_code == 403


def test_another_sites_page_cannot_change_anything(client):
    for path in ("/api/sync", "/api/live/attach", "/api/live/detach"):
        response = client.post(path, headers={"Origin": "https://evil.example"})
        assert response.status_code == 403, path


def test_a_sandboxed_or_unnamed_page_cannot_either(client):
    assert client.post("/api/live/detach", headers={"Origin": "null"}).status_code == 403
    assert client.post("/api/live/detach", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_its_own_pages_and_the_app_itself_can(client):
    assert client.post("/api/live/detach", headers={"Origin": LOCAL}).status_code == 200
    assert client.post("/api/live/detach").status_code == 200         # the app, from no page
    dev = TestClient(app, base_url="http://localhost:5173")           # the Vite dev server's proxy
    assert dev.post("/api/live/detach", headers={"Origin": "http://localhost:5173"}).status_code == 200


def test_reading_from_another_site_is_left_to_cors(client):
    """A GET is not refused here; the browser keeps another site from reading it."""
    response = client.get("/api/circuits", headers={"Origin": "https://evil.example"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_the_api_docs_are_off(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


@pytest.mark.parametrize("recording", ["../secret.txt", "C:/Windows/win.ini", "/etc/passwd", "missing.txt"])
def test_live_attach_opens_only_a_recording_in_the_live_folder(client, tmp_path, monkeypatch, recording):
    monkeypatch.setattr(recorder, "LIVE_DIR", tmp_path / "live")
    (tmp_path / "live").mkdir()
    (tmp_path / "secret.txt").write_text("not a recording")
    response = client.post("/api/live/attach", params={"recording": recording})
    assert response.status_code == 400
    assert "no recording" in response.json()["detail"]
