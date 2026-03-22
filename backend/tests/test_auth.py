import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
import asyncio
import os
from types import SimpleNamespace

# Set test env vars before importing settings
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")
os.environ.setdefault("FIRECRAWL_API_KEY", "test-firecrawl-key")

import auth


def test_get_authenticated_user_returns_user_id(monkeypatch):
    monkeypatch.setattr(
        auth.jwks_client,
        "get_signing_key_from_jwt",
        lambda token: SimpleNamespace(key="test-key"),
    )
    monkeypatch.setattr(
        auth.jwt,
        "decode",
        lambda token, key, algorithms, audience: {"sub": "test-user-123"},
    )

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="signed-token")
    result = asyncio.run(auth.get_authenticated_user(creds))
    assert result == "test-user-123"


def test_get_authenticated_user_invalid_token_raises_401(monkeypatch):
    monkeypatch.setattr(
        auth.jwks_client,
        "get_signing_key_from_jwt",
        lambda token: (_ for _ in ()).throw(auth.jwt.PyJWTError("bad token")),
    )

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad-token")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(auth.get_authenticated_user(creds))
    assert exc_info.value.status_code == 401


def test_ensure_team_access_allows_disabled_gate(monkeypatch):
    monkeypatch.setattr(
        auth,
        "get_team_access_state",
        lambda: {"enabled": False, "current_version": 1},
    )

    auth.ensure_team_access("test-user-123")


def test_ensure_team_access_requires_current_version(monkeypatch):
    monkeypatch.setattr(
        auth,
        "get_team_access_state",
        lambda: {"enabled": True, "current_version": 3},
    )
    monkeypatch.setattr(
        auth,
        "get_team_access_profile",
        lambda user_id: {
            "id": user_id,
            "team_access_version": 2,
            "team_access_blocked": False,
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        auth.ensure_team_access("test-user-123")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "team_access_required"


def test_ensure_team_access_blocks_revoked_user(monkeypatch):
    monkeypatch.setattr(
        auth,
        "get_team_access_state",
        lambda: {"enabled": True, "current_version": 2},
    )
    monkeypatch.setattr(
        auth,
        "get_team_access_profile",
        lambda user_id: {
            "id": user_id,
            "team_access_version": 2,
            "team_access_blocked": True,
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        auth.ensure_team_access("test-user-123")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "team_access_blocked"
