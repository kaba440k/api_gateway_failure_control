"""create traffic events

Revision ID: 20260504_0001
Revises:
Create Date: 2026-05-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260504_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("traffic_events"):
        op.create_table(
            "traffic_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("service", sa.String(length=100), nullable=False),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("latency_ms", sa.Float(), nullable=True),
            sa.Column("breaker_state", sa.String(length=30), nullable=True),
            sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_traffic_events_event_type "
        "ON traffic_events (event_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_traffic_events_service "
        "ON traffic_events (service)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_traffic_events_service")
    op.execute("DROP INDEX IF EXISTS ix_traffic_events_event_type")
    op.drop_table("traffic_events")
