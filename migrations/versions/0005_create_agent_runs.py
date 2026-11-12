"""create agent runs and tool call audit

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "language",
            sa.Enum(
                "ru",
                "en",
                name="agent_language",
                native_enum=False,
                create_constraint=True,
                length=2,
            ),
            nullable=False,
        ),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("refusal", sa.Boolean(), nullable=False),
        sa.Column("citation_warning", sa.Boolean(), nullable=False),
        sa.Column("citations", JSONB(), nullable=False),
        sa.Column("steps", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("args", JSONB(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
    )
    op.create_index("ix_tool_calls_run_id", "tool_calls", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_tool_calls_run_id", table_name="tool_calls")
    op.drop_table("tool_calls")
    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_table("agent_runs")
