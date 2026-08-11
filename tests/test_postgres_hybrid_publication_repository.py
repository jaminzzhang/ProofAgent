from __future__ import annotations

import hashlib
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy.engine import make_url

from proof_agent.configuration.hybrid_migrations import apply_hybrid_migrations
from proof_agent.configuration.postgres_hybrid_knowledge_repository import (
    PostgresHybridKnowledgeRepository,
)
from proof_agent.contracts.knowledge_index import KnowledgeIndexGeneration


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def test_pg_stage_source_candidate_bootstraps_new_publication_authority(
    postgres_dsn: str,
) -> None:
    raw_dsn = make_url(postgres_dsn).set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    apply_hybrid_migrations(raw_dsn)
    repository = PostgresHybridKnowledgeRepository.from_dsn(raw_dsn)
    source_id = f"hybrid-{uuid4()}"
    generation = KnowledgeIndexGeneration(
        generation_id=f"generation-{uuid4()}",
        source_id=source_id,
        canonical_schema_version="structured-knowledge.v1",
        search_projection_version="rule-unit-search.v1",
        mapping_sha256="a" * 64,
        analyzer_sha256="b" * 64,
        embedding_model_revision="embedding@sha256:test",
        embedding_instruction_sha256=hashlib.sha256(b"instruction").hexdigest(),
        embedding_dimension=2,
        normalized=True,
    )

    try:
        repository.stage_source_candidate(
            source_id=source_id,
            source_draft_version_id="draft-1",
            candidate_digest="c" * 64,
            generation=generation,
        )

        with psycopg.connect(raw_dsn) as connection:
            authority = connection.execute(
                """SELECT draft_version_id, candidate_digest
                     FROM hybrid_knowledge_source_authority
                    WHERE source_id=%s""",
                (source_id,),
            ).fetchone()
            stored_generation = connection.execute(
                """SELECT source_id, mapping_sha256
                     FROM hybrid_knowledge_generation
                    WHERE generation_id=%s""",
                (generation.generation_id,),
            ).fetchone()

        assert authority == ("draft-1", "c" * 64)
        assert stored_generation == (source_id, generation.mapping_sha256)
    finally:
        repository.close()
