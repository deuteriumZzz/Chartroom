"""create documents, versions and chunks

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=16)


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("title_key", sa.String(300), nullable=False),
        sa.Column("language", _enum("document_language", "ru", "en"), nullable=False),
        sa.UniqueConstraint("title_key", "language", name="uq_documents_title_language"),
    )
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(50), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "status",
            _enum("indexing_status", "pending", "indexing", "indexed", "failed"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "label", name="uq_document_versions_label"),
        sa.UniqueConstraint("document_id", "checksum", name="uq_document_versions_checksum"),
    )
    op.create_index(
        "uq_document_versions_active",
        "document_versions",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "version_id",
            sa.Integer(),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section_path", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("qdrant_id", sa.Uuid(), nullable=False),
        sa.UniqueConstraint("version_id", "chunk_index", name="uq_chunks_version_index"),
    )


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_index("uq_document_versions_active", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_table("documents")
