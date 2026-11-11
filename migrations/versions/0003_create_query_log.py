"""create query log: queries, citations, feedback

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.create_table(
        "queries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "language",
            sa.Enum(
                "ru",
                "en",
                name="answer_language",
                native_enum=False,
                create_constraint=True,
                length=2,
            ),
            nullable=False,
        ),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("refusal", sa.Boolean(), nullable=False),
        sa.Column("citation_warning", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_queries_user_id", "queries", ["user_id"])
    op.create_table(
        "citations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "query_id",
            sa.Integer(),
            sa.ForeignKey("queries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("section_path", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.UniqueConstraint("query_id", "position", name="uq_citations_query_position"),
    )
    op.create_table(
        "feedback",
        sa.Column(
            "query_id",
            sa.Integer(),
            sa.ForeignKey("queries.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("useful", sa.Boolean(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_table("citations")
    op.drop_index("ix_queries_user_id", table_name="queries")
    op.drop_table("queries")
