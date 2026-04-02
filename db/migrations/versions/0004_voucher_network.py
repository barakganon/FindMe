"""Add voucher_network column to stores table

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-02

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add voucher_network column with default 'buyme' for all existing stores
    op.execute(
        "ALTER TABLE stores ADD COLUMN voucher_network VARCHAR(50) DEFAULT 'buyme' NOT NULL"
    )
    # Create index for filtering stores by voucher network
    op.execute(
        "CREATE INDEX idx_stores_voucher_network ON stores(voucher_network)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_stores_voucher_network")
    op.execute("ALTER TABLE stores DROP COLUMN IF EXISTS voucher_network")
