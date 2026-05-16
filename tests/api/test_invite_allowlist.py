"""tests/api/test_invite_allowlist.py — W5 invite-only gate unit tests."""

from __future__ import annotations

from types import SimpleNamespace

from api.agent.invite_allowlist import (
    allow_anonymous_in_invite_mode,
    allowed_emails,
    block_reason,
    invite_only_enabled,
    is_allowed,
)


# ---------------------------------------------------------------------------
# Master toggle
# ---------------------------------------------------------------------------


def test_invite_only_default_off(monkeypatch):
    monkeypatch.delenv("V2_INVITE_ONLY", raising=False)
    assert invite_only_enabled() is False


def test_invite_only_enabled_via_env(monkeypatch):
    monkeypatch.setenv("V2_INVITE_ONLY", "true")
    assert invite_only_enabled() is True


def test_invite_only_enabled_via_1(monkeypatch):
    monkeypatch.setenv("V2_INVITE_ONLY", "1")
    assert invite_only_enabled() is True


# ---------------------------------------------------------------------------
# Allowlist parsing
# ---------------------------------------------------------------------------


def test_allowed_emails_empty(monkeypatch):
    monkeypatch.delenv("V2_EMAIL_ALLOWLIST", raising=False)
    assert allowed_emails() == set()


def test_allowed_emails_lowercased_and_trimmed(monkeypatch):
    monkeypatch.setenv("V2_EMAIL_ALLOWLIST", "Alice@Example.com , bob@example.com,  ")
    assert allowed_emails() == {"alice@example.com", "bob@example.com"}


# ---------------------------------------------------------------------------
# is_allowed — gate off
# ---------------------------------------------------------------------------


def test_is_allowed_passes_when_invite_off(monkeypatch):
    monkeypatch.delenv("V2_INVITE_ONLY", raising=False)
    assert is_allowed(None) is True
    assert is_allowed(SimpleNamespace(email="anyone@example.com")) is True


# ---------------------------------------------------------------------------
# is_allowed — invite on, anonymous flag
# ---------------------------------------------------------------------------


def test_anonymous_allowed_when_invite_on_and_anon_allowed(monkeypatch):
    monkeypatch.setenv("V2_INVITE_ONLY", "true")
    monkeypatch.setenv("V2_ALLOW_ANON", "true")
    assert is_allowed(None) is True


def test_anonymous_blocked_when_invite_on_and_anon_blocked(monkeypatch):
    monkeypatch.setenv("V2_INVITE_ONLY", "true")
    monkeypatch.setenv("V2_ALLOW_ANON", "false")
    assert is_allowed(None) is False


def test_anonymous_allowed_by_default_when_invite_on(monkeypatch):
    """ALLOW_ANON defaults to true — explicitly unset, should permit anon."""
    monkeypatch.setenv("V2_INVITE_ONLY", "true")
    monkeypatch.delenv("V2_ALLOW_ANON", raising=False)
    assert allow_anonymous_in_invite_mode() is True
    assert is_allowed(None) is True


# ---------------------------------------------------------------------------
# is_allowed — logged-in user vs allowlist
# ---------------------------------------------------------------------------


def test_logged_in_email_in_allowlist_passes(monkeypatch):
    monkeypatch.setenv("V2_INVITE_ONLY", "true")
    monkeypatch.setenv("V2_EMAIL_ALLOWLIST", "alice@example.com,bob@example.com")
    user = SimpleNamespace(email="alice@example.com")
    assert is_allowed(user) is True


def test_logged_in_email_case_insensitive(monkeypatch):
    monkeypatch.setenv("V2_INVITE_ONLY", "true")
    monkeypatch.setenv("V2_EMAIL_ALLOWLIST", "alice@example.com")
    user = SimpleNamespace(email="ALICE@example.com")
    assert is_allowed(user) is True


def test_logged_in_email_not_in_allowlist_blocked(monkeypatch):
    monkeypatch.setenv("V2_INVITE_ONLY", "true")
    monkeypatch.setenv("V2_EMAIL_ALLOWLIST", "alice@example.com")
    user = SimpleNamespace(email="charlie@example.com")
    assert is_allowed(user) is False


def test_logged_in_no_email_blocked(monkeypatch):
    monkeypatch.setenv("V2_INVITE_ONLY", "true")
    monkeypatch.setenv("V2_EMAIL_ALLOWLIST", "alice@example.com")
    user = SimpleNamespace(email=None)
    assert is_allowed(user) is False


# ---------------------------------------------------------------------------
# block_reason
# ---------------------------------------------------------------------------


def test_block_reason_anon():
    msg = block_reason(None)
    assert "anonymous" in msg.lower()


def test_block_reason_user():
    msg = block_reason(SimpleNamespace(email="charlie@example.com"))
    assert "invite" in msg.lower()
