"""Add user accounts tables: users, locations, vouchers, preferences, signals, attributes, history, favorites

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-02

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("google_id", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("google_id", name="uq_users_google_id"),
    )

    # 2. user_locations
    op.create_table(
        "user_locations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("address", sa.String(255), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_user_locations_user", "user_locations", ["user_id"])
    # Partial unique index: only one default location per user
    op.execute(
        "CREATE UNIQUE INDEX idx_user_locations_default "
        "ON user_locations(user_id) WHERE is_default = true"
    )

    # 3. user_voucher_cards
    op.create_table(
        "user_voucher_cards",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("voucher_network", sa.String(50), nullable=False),
        sa.Column("nickname", sa.String(100), nullable=True),
        sa.Column("balance", sa.Numeric(10, 2), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_user_vouchers_user", "user_voucher_cards", ["user_id"])

    # 4. user_preferences
    op.create_table(
        "user_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "key"),
    )

    # 5. user_implicit_signals
    op.create_table(
        "user_implicit_signals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_type", sa.String(50), nullable=False),
        sa.Column("signal_value", sa.String(255), nullable=False),
        sa.Column("weight", sa.Float(), server_default=sa.text("1.0"), nullable=False),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_implicit_user_type_val "
        "ON user_implicit_signals(user_id, signal_type, signal_value)"
    )

    # 6. user_inferred_attributes
    op.create_table(
        "user_inferred_attributes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attribute", sa.String(100), nullable=False),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("confidence", sa.Float(), server_default=sa.text("0.5"), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column(
            "inferred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "is_confirmed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_inferred_user", "user_inferred_attributes", ["user_id"])
    op.execute(
        "CREATE UNIQUE INDEX idx_inferred_user_attr "
        "ON user_inferred_attributes(user_id, attribute)"
    )

    # 7. user_search_history
    op.create_table(
        "user_search_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(50), nullable=True),
        sa.Column("resolved_query", sa.Text(), nullable=True),
        sa.Column("city_used", sa.String(100), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("top_result_name", sa.Text(), nullable=True),
        sa.Column(
            "voucher_network",
            sa.String(50),
            server_default=sa.text("'buyme'"),
            nullable=False,
        ),
        sa.Column(
            "searched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE INDEX idx_search_history_user "
        "ON user_search_history(user_id, searched_at DESC)"
    )

    # 8. user_favorite_stores
    op.create_table(
        "user_favorite_stores",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "saved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("note", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "store_id"),
    )


def downgrade() -> None:
    op.drop_table("user_favorite_stores")
    op.execute("DROP INDEX IF EXISTS idx_search_history_user")
    op.drop_table("user_search_history")
    op.execute("DROP INDEX IF EXISTS idx_inferred_user_attr")
    op.drop_index("idx_inferred_user", table_name="user_inferred_attributes")
    op.drop_table("user_inferred_attributes")
    op.execute("DROP INDEX IF EXISTS idx_implicit_user_type_val")
    op.drop_table("user_implicit_signals")
    op.drop_table("user_preferences")
    op.drop_index("idx_user_vouchers_user", table_name="user_voucher_cards")
    op.drop_table("user_voucher_cards")
    op.execute("DROP INDEX IF EXISTS idx_user_locations_default")
    op.drop_index("idx_user_locations_user", table_name="user_locations")
    op.drop_table("user_locations")
    op.drop_table("users")
