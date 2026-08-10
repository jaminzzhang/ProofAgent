"""Cut insurance metadata review authority directly to V2."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0020_metadata_review_v2"
down_revision: str | None = "0019_ingestion_operation_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("hybrid_metadata_reviews", "legacy_hybrid_metadata_reviews")
    op.execute(
        "ALTER INDEX hybrid_metadata_reviews_source_state_idx "
        "RENAME TO legacy_hybrid_metadata_reviews_source_state_idx"
    )

    op.create_table(
        "insurance_metadata_profiles",
        sa.Column("profile_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("lifecycle_state", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("profile_id"),
        sa.CheckConstraint(
            "lifecycle_state IN ('active','archived')",
            name="insurance_metadata_profiles_lifecycle",
        ),
    )
    op.create_table(
        "insurance_metadata_profile_revisions",
        sa.Column("profile_revision_id", sa.Text(), nullable=False),
        sa.Column("profile_id", sa.Text(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("profile_digest", sa.String(64), nullable=False),
        sa.Column("reference_only", sa.Boolean(), nullable=False),
        sa.Column("profile_json", postgresql.JSONB(), nullable=False),
        sa.Column("published_by", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("profile_revision_id"),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["insurance_metadata_profiles.profile_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "profile_id",
            "revision_number",
            name="insurance_metadata_profile_revision_number_uq",
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="insurance_metadata_profile_revision_positive",
        ),
    )
    op.create_table(
        "knowledge_source_metadata_bindings",
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("metadata_scheme", sa.Text(), nullable=False),
        sa.Column("profile_revision_id", sa.Text(), nullable=False),
        sa.Column("bound_by", sa.Text(), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source_id"),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge_sources.source_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["profile_revision_id"],
            ["insurance_metadata_profile_revisions.profile_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "metadata_scheme = 'insurance_rule.v2'",
            name="knowledge_source_metadata_binding_scheme",
        ),
    )
    op.create_table(
        "hybrid_metadata_review_sets",
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("review_set_id", sa.Text(), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("structured_build_id", sa.Text(), nullable=False),
        sa.Column("profile_revision_id", sa.Text(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("review_set_identity", sa.String(64), nullable=False),
        sa.Column("current", sa.Boolean(), nullable=False),
        sa.Column("review_set_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source_id", "review_set_id"),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge_sources.source_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["profile_revision_id"],
            ["insurance_metadata_profile_revisions.profile_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "generation > 0", name="hybrid_metadata_review_sets_generation"
        ),
    )
    op.create_index(
        "hybrid_metadata_review_sets_current_document_uq",
        "hybrid_metadata_review_sets",
        ["source_id", "document_id", "revision_id"],
        unique=True,
        postgresql_where=sa.text("current = TRUE"),
    )
    op.create_table(
        "hybrid_metadata_reviews",
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("review_id", sa.Text(), nullable=False),
        sa.Column("review_set_id", sa.Text(), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_revision_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("canonical_anchor", sa.Text()),
        sa.Column("review_version", sa.Integer(), nullable=False),
        sa.Column("review_identity", sa.String(64), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("current", sa.Boolean(), nullable=False),
        sa.Column("approved_metadata_revision_id", sa.Text()),
        sa.Column("review_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source_id", "review_id"),
        sa.ForeignKeyConstraint(
            ["source_id", "review_set_id"],
            [
                "hybrid_metadata_review_sets.source_id",
                "hybrid_metadata_review_sets.review_set_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["profile_revision_id"],
            ["insurance_metadata_profile_revisions.profile_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "review_version > 0", name="hybrid_metadata_reviews_v2_version"
        ),
        sa.CheckConstraint(
            "state IN ('needs_input','ready_for_approval','approved','rejected')",
            name="hybrid_metadata_reviews_v2_state",
        ),
        sa.CheckConstraint(
            "scope IN ('document_default','rule_unit_override')",
            name="hybrid_metadata_reviews_v2_scope",
        ),
        sa.CheckConstraint(
            "(scope = 'document_default' AND canonical_anchor IS NULL) OR "
            "(scope = 'rule_unit_override' AND canonical_anchor IS NOT NULL)",
            name="hybrid_metadata_reviews_v2_anchor",
        ),
        sa.CheckConstraint(
            "(state = 'approved') = (approved_metadata_revision_id IS NOT NULL)",
            name="hybrid_metadata_reviews_v2_approval",
        ),
    )
    op.create_index(
        "hybrid_metadata_reviews_source_state_idx",
        "hybrid_metadata_reviews",
        ["source_id", "current", "state", "review_id"],
    )
    op.create_index(
        "hybrid_metadata_reviews_current_default_uq",
        "hybrid_metadata_reviews",
        ["source_id", "document_id", "revision_id"],
        unique=True,
        postgresql_where=sa.text("current = TRUE AND scope = 'document_default'"),
    )
    op.create_index(
        "hybrid_metadata_reviews_current_override_uq",
        "hybrid_metadata_reviews",
        ["source_id", "document_id", "revision_id", "canonical_anchor"],
        unique=True,
        postgresql_where=sa.text("current = TRUE AND scope = 'rule_unit_override'"),
    )
    op.create_table(
        "hybrid_metadata_review_decisions",
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("decision_id", sa.Text(), nullable=False),
        sa.Column("review_id", sa.Text(), nullable=False),
        sa.Column("prior_review_identity", sa.String(64), nullable=False),
        sa.Column("resulting_review_identity", sa.String(64), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_fields_json", postgresql.JSONB(), nullable=False),
        sa.Column("decision_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source_id", "decision_id"),
        sa.ForeignKeyConstraint(
            ["source_id", "review_id"],
            ["hybrid_metadata_reviews.source_id", "hybrid_metadata_reviews.review_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "action IN ('save_draft','approve','reject')",
            name="hybrid_metadata_review_decisions_action",
        ),
    )
    op.create_index(
        "hybrid_metadata_review_decisions_review_idx",
        "hybrid_metadata_review_decisions",
        ["source_id", "review_id", "created_at", "decision_id"],
    )


def downgrade() -> None:
    raise RuntimeError("Metadata Review V2 direct cutover does not support downgrade")
