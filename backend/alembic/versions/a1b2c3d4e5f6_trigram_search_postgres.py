"""trigram indexes for food search (PostgreSQL only)

Substring search (ILIKE '%term%') over hundreds of thousands of branded products needs
pg_trgm GIN indexes on PostgreSQL. pg_trgm ships with PostgreSQL and is a trusted
extension, so the database owner can enable it. SQLite installs skip this.

Revision ID: a1b2c3d4e5f6
Revises: 39fa0ca7057d
Create Date: 2026-10-30
"""
from collections.abc import Sequence

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "39fa0ca7057d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX IF NOT EXISTS ix_foods_name_trgm ON foods USING gin (name gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_foods_brand_trgm ON foods USING gin (brand gin_trgm_ops)")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_foods_brand_trgm")
    op.execute("DROP INDEX IF EXISTS ix_foods_name_trgm")
