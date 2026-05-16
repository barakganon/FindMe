"""Add agent_traces table for v2 chat telemetry

Revision ID: 0009
Revises: 26d06a1f803b
Create Date: 2026-05-16

Creates the per-turn telemetry table that the v2 agent endpoint writes after
each `run_agent` invocation. Stores the full tool-call trace as JSONB so we
can run ad-hoc analytics queries during the W5 soft launch and beyond:
  - which tools are called most?
  - what cities do users actually search?
  - p95 latency by intent?
  - cost per session?

Insertion is best-effort from `api/routes/chat_v2.py` — if the insert fails,
the chat response still returns successfully (telemetry must never block UX).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_agent_traces"
down_revision: Union[str, None] = "26d06a1f803b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_traces (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id      TEXT,
            user_id         UUID NULL REFERENCES users(id) ON DELETE SET NULL,
            message         TEXT NOT NULL,
            intent          TEXT,
            tool_calls      JSONB NOT NULL DEFAULT '[]'::jsonb,
            iterations      INTEGER NOT NULL DEFAULT 0,
            total_latency_ms FLOAT NOT NULL DEFAULT 0,
            total_cost_usd  NUMERIC(10,6),
            terminated_by   TEXT,
            voucher_network TEXT DEFAULT 'buyme',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_traces_created_at ON agent_traces(created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_traces_user_id ON agent_traces(user_id, created_at DESC) WHERE user_id IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_traces_intent ON agent_traces(intent)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_agent_traces_intent")
    op.execute("DROP INDEX IF EXISTS idx_agent_traces_user_id")
    op.execute("DROP INDEX IF EXISTS idx_agent_traces_created_at")
    op.execute("DROP TABLE IF EXISTS agent_traces")
