"""Add unique constraint on products.canonical_name

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-25

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_products_canonical_name", "products", ["canonical_name"])


def downgrade() -> None:
    op.drop_constraint("uq_products_canonical_name", "products", type_="unique")
