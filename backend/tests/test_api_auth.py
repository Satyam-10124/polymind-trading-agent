"""
Dashboard API bearer auth + scoped CORS.

/api/status is public; every other route requires `Authorization: Bearer
<API_TOKEN>` when API_TOKEN is set. When API_TOKEN is unset, auth is skipped so
local dev works. CORS is locked to DASHBOARD_ORIGINS, not "*".

These need FastAPI installed; skipped cleanly if it isn't.
"""
import importlib

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _client(monkeypatch, token):
    """Reload api with API_TOKEN set/unset and return a TestClient."""
    import api
    importlib.reload(api)
    monkeypatch.setattr(api, "API_TOKEN", token)
    return TestClient(api.app)


def test_status_is_public_without_token(monkeypatch):
    c = _client(monkeypatch, token="secret")
    assert c.get("/api/status").status_code == 200


def test_protected_route_401_without_token(monkeypatch):
    c = _client(monkeypatch, token="secret")
    assert c.get("/api/positions").status_code == 401


def test_protected_route_401_with_wrong_token(monkeypatch):
    c = _client(monkeypatch, token="secret")
    r = c.get("/api/positions", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_protected_route_200_with_correct_token(monkeypatch):
    c = _client(monkeypatch, token="secret")
    r = c.get("/api/positions", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200


def test_auth_skipped_when_token_unset(monkeypatch):
    # API_TOKEN unset => protected routes are reachable without a header.
    c = _client(monkeypatch, token=None)
    assert c.get("/api/positions").status_code == 200


def test_require_token_logic_directly(monkeypatch):
    """The dependency raises 401 only when a token is configured and mismatched."""
    import api
    from fastapi import HTTPException

    monkeypatch.setattr(api, "API_TOKEN", "secret")
    # Correct token: no raise.
    api.require_token("Bearer secret")
    # Wrong / missing / malformed: raise 401.
    for bad in ("Bearer wrong", "", "secret", "Basic secret"):
        with pytest.raises(HTTPException) as exc:
            api.require_token(bad)
        assert exc.value.status_code == 401

    # Token disabled: anything (even empty) passes.
    monkeypatch.setattr(api, "API_TOKEN", None)
    api.require_token("")
