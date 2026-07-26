"""Add encrypted PostgreSQL model credentials."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0011_model_credential"
down_revision: str | None = "0010_hybrid_knowledge_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_connection_credentials",
        sa.Column("connection_id", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Text(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("connection_id"),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["model_connections.connection_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "octet_length(ciphertext) BETWEEN 29 AND 16412",
            name="ck_model_connection_credentials_ciphertext_size",
        ),
    )


def downgrade() -> None:
    op.drop_table("model_connection_credentials")
