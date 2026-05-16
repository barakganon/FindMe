"""api/agent/invite_allowlist.py — Email allowlist gate for the v2 soft launch (W5).

Env-var driven. Three settings:
  V2_INVITE_ONLY        (bool, default false) — master toggle
  V2_EMAIL_ALLOWLIST    (comma-separated emails)
  V2_ALLOW_ANON         (bool, default true) — when invite-only, may anon use?

When V2_INVITE_ONLY=false (the default), the gate is a no-op. Useful for dev,
post-launch open access, or A/B canaries.

When V2_INVITE_ONLY=true:
  - Logged-in users whose email is NOT in V2_EMAIL_ALLOWLIST → blocked (403)
  - Anonymous users → blocked unless V2_ALLOW_ANON=true
"""

from __future__ import annotations

import os
from typing import Iterable, Optional


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def invite_only_enabled() -> bool:
    return _bool_env("V2_INVITE_ONLY", False)


def allow_anonymous_in_invite_mode() -> bool:
    return _bool_env("V2_ALLOW_ANON", True)


def allowed_emails() -> set[str]:
    raw = os.environ.get("V2_EMAIL_ALLOWLIST", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_allowed(current_user: Optional[object]) -> bool:
    """Return True iff the requester may use /api/chat/v2.

    Logic:
      - Invite-only disabled → always allow.
      - Invite-only enabled + anonymous user + V2_ALLOW_ANON true → allow.
      - Invite-only enabled + anonymous user + V2_ALLOW_ANON false → deny.
      - Invite-only enabled + logged-in user with email in allowlist → allow.
      - Invite-only enabled + logged-in user without matching email → deny.
    """
    if not invite_only_enabled():
        return True

    if current_user is None:
        return allow_anonymous_in_invite_mode()

    email = (getattr(current_user, "email", None) or "").strip().lower()
    if not email:
        return False
    return email in allowed_emails()


def block_reason(current_user: Optional[object]) -> str:
    """Human-readable reason for a 403, surfaced in the response body."""
    if current_user is None:
        return "v2 is currently invite-only and anonymous access is disabled"
    return "your account is not on the v2 invite list"
