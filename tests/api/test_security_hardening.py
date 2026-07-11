"""
tests/api/test_security_hardening.py — Epic 6 security-audit fixes.

Covers:
    1. api/auth.py — JWT_SECRET fail-fast in production, permissive dev default otherwise.
    2. api/main.py — CORS wildcard fail-fast in production.
    3. api/routes/auth.py — Google OAuth `aud` pinned to GOOGLE_CLIENT_ID.

The prod fail-fast checks run at *module import* time, so they're exercised via
a subprocess with controlled env vars rather than reload-in-process (avoids
polluting the shared `api.main` / `api.auth` module state used by every other
test in the suite).
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

_PY = sys.executable


def _run_import(module: str, env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    """Import `module` in a fresh subprocess with the given env vars set."""
    env = {"PATH": "/usr/bin:/bin"}
    # Inherit the current interpreter's env (venv, PYTHONPATH) but override specifics.
    import os

    env = dict(os.environ)
    env.update(env_overrides)
    return subprocess.run(
        [_PY, "-c", f"import {module}"],
        env=env,
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
        timeout=60,
    )


# ---------------------------------------------------------------------------
# 1a. Prod + missing JWT_SECRET → raise at import
# ---------------------------------------------------------------------------


def test_prod_missing_jwt_secret_raises() -> None:
    env = {"APP_ENV": "production"}
    env.pop("JWT_SECRET", None)
    import os

    full_env = dict(os.environ)
    full_env.pop("JWT_SECRET", None)
    full_env["APP_ENV"] = "production"
    result = subprocess.run(
        [_PY, "-c", "import api.auth"],
        env=full_env,
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
        timeout=60,
    )
    assert result.returncode != 0
    assert "JWT_SECRET" in result.stderr


def test_prod_dev_default_jwt_secret_raises() -> None:
    """Prod + JWT_SECRET explicitly set to the known dev default → still raise."""
    import os

    full_env = dict(os.environ)
    full_env["APP_ENV"] = "production"
    full_env["JWT_SECRET"] = "dev-secret-key-change-in-production"
    result = subprocess.run(
        [_PY, "-c", "import api.auth"],
        env=full_env,
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
        timeout=60,
    )
    assert result.returncode != 0
    assert "JWT_SECRET" in result.stderr


# ---------------------------------------------------------------------------
# 1b. Non-prod boots fine with no JWT_SECRET (dev default, warning only)
# ---------------------------------------------------------------------------


def test_non_prod_boots_with_default_jwt_secret() -> None:
    import os

    full_env = dict(os.environ)
    full_env.pop("JWT_SECRET", None)
    full_env.pop("APP_ENV", None)
    result = subprocess.run(
        [_PY, "-c", "import api.auth; print('OK')"],
        env=full_env,
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# 3a. Prod + wildcard CORS_ORIGINS → raise at import of api.main
# ---------------------------------------------------------------------------


def test_prod_wildcard_cors_raises() -> None:
    import os

    full_env = dict(os.environ)
    full_env["APP_ENV"] = "production"
    full_env["JWT_SECRET"] = "a-sufficiently-long-random-prod-secret"
    full_env.pop("CORS_ORIGINS", None)  # unset → defaults to "*"
    result = subprocess.run(
        [_PY, "-c", "import api.main"],
        env=full_env,
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
        timeout=60,
    )
    assert result.returncode != 0
    assert "CORS_ORIGINS" in result.stderr


def test_prod_explicit_cors_origins_boots_fine() -> None:
    import os

    full_env = dict(os.environ)
    full_env["APP_ENV"] = "production"
    full_env["JWT_SECRET"] = "a-sufficiently-long-random-prod-secret"
    full_env["CORS_ORIGINS"] = "https://app.example.com"
    result = subprocess.run(
        [_PY, "-c", "import api.main; print('OK')"],
        env=full_env,
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# 2. Google OAuth aud mismatch → 401 (network call mocked, never hits Google)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_google_oauth_aud_mismatch_rejected(monkeypatch) -> None:
    from api.dependencies import get_db
    from api.main import app

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "expected-client-id.apps.googleusercontent.com")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "sub": "google-user-123",
        "email": "user@example.com",
        "name": "Test User",
        "aud": "some-other-client-id.apps.googleusercontent.com",  # mismatched aud
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    class _MockDbDep:
        async def __call__(self):
            yield AsyncMock()

    app.dependency_overrides[get_db] = _MockDbDep()
    try:
        with patch("httpx.AsyncClient", return_value=mock_client):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                r = await client.post(
                    "/api/auth/google",
                    json={"google_token": "fake-token"},
                )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 401
    assert "aud" in r.json()["detail"].lower() or "audience" in r.json()["detail"].lower()
    # Never hit the real network — only our mocked client was used.
    mock_client.get.assert_awaited_once()


@pytest.mark.anyio
async def test_google_oauth_aud_match_accepted(monkeypatch) -> None:
    """Matching aud passes the new check and proceeds to find/create the user."""
    from api.dependencies import get_db
    from api.main import app

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "expected-client-id.apps.googleusercontent.com")

    user_id = uuid.uuid4()
    email = "user@example.com"

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "sub": "google-user-123",
        "email": email,
        "name": "Test User",
        "aud": "expected-client-id.apps.googleusercontent.com",
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    existing_user = MagicMock()
    existing_user.id = user_id
    existing_user.email = email
    existing_user.display_name = "Test User"
    existing_user.google_id = "google-user-123"

    class _MockDbDep:
        async def __call__(self):
            session = AsyncMock()

            async def _execute(*args, **kwargs):
                result = MagicMock()
                result.scalar_one_or_none.return_value = existing_user
                return result

            session.execute = _execute
            session.commit = AsyncMock()
            yield session

    app.dependency_overrides[get_db] = _MockDbDep()
    try:
        with patch("httpx.AsyncClient", return_value=mock_client):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                r = await client.post(
                    "/api/auth/google",
                    json={"google_token": "fake-token"},
                )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    data = r.json()
    assert data["user"]["email"] == email
