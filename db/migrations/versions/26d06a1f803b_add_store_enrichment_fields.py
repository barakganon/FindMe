"""add_store_enrichment_fields

Revision ID: 26d06a1f803b
Revises: 0008
Create Date: 2026-04-07 04:00:58.923811

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '26d06a1f803b'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add new columns to stores
    op.add_column('stores', sa.Column('buyme_categories', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=True))
    op.add_column('stores', sa.Column('parent_chain_id', sa.UUID(), nullable=True))
    op.add_column('stores', sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=True))
    op.add_column('stores', sa.Column('redemption_details_url', sa.String(length=1024), nullable=True))
    
    # 2. Add foreign key for chain support
    op.create_foreign_key('fk_stores_parent_chain', 'stores', 'stores', ['parent_chain_id'], ['id'], ondelete='SET NULL')
    
    # 3. Create indexes for new columns and existing ones that needed indexing
    op.create_index(op.f('ix_stores_parent_chain_id'), 'stores', ['parent_chain_id'], unique=False)
    
    # Ensure buyme_url index is unique (replacing the old constraint/index if needed)
    # Autogenerate detected change here, let's keep it safe:
    op.drop_constraint('uq_stores_buyme_url', 'stores', type_='unique')
    op.drop_index('ix_stores_buyme_url', table_name='stores')
    op.create_index(op.f('ix_stores_buyme_url'), 'stores', ['buyme_url'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_stores_buyme_url'), table_name='stores')
    op.create_index('ix_stores_buyme_url', 'stores', ['buyme_url'], unique=False)
    op.create_unique_constraint('uq_stores_buyme_url', 'stores', ['buyme_url'])
    
    op.drop_index(op.f('ix_stores_parent_chain_id'), table_name='stores')
    op.drop_constraint('fk_stores_parent_chain', 'stores', type_='foreignkey')
    
    op.drop_column('stores', 'redemption_details_url')
    op.drop_column('stores', 'metadata_json')
    op.drop_column('stores', 'parent_chain_id')
    op.drop_column('stores', 'buyme_categories')
