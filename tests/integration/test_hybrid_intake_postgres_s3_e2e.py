from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO
import os
from uuid import uuid4

from pypdf import PdfWriter
import pytest
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import make_url

from proof_agent.capabilities.knowledge.hybrid.s3_artifacts import S3ExactArtifactStore
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridPrivateParserBuildConfig,
)
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.capabilities.persistence.postgres.database import upgrade_database
from proof_agent.capabilities.persistence.postgres.schema import audit_events
from proof_agent.contracts import AuditActorFacts
from proof_agent.control.knowledge.production_intake import (
    ProductionHybridKnowledgeIntakeService,
)


pytestmark = [pytest.mark.postgres_integration, pytest.mark.hybrid_integration]


@pytest.fixture
def postgres_dsn() -> Iterator[str]:
    base_dsn = _required("PROOF_AGENT_TEST_POSTGRES_DSN")
    schema = f"proof_agent_hybrid_intake_{uuid4().hex}"
    base_engine: Engine = create_engine(base_dsn)
    with base_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(base_dsn)
    query = dict(url.query)
    query["options"] = f"-csearch_path={schema}"
    isolated_dsn = url.set(query=query).render_as_string(hide_password=False)
    upgrade_database(isolated_dsn)
    try:
        yield isolated_dsn
    finally:
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        base_engine.dispose()


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is required for real PostgreSQL/S3 integration")
    return value


def _pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def test_real_pdf_preflight_s3_exact_write_and_atomic_postgres_admission(
    postgres_dsn: str,
) -> None:
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    store = S3ExactArtifactStore.from_environment(
        bucket=_required("PROOF_AGENT_TEST_S3_BUCKET"),
        key_prefix=f"hybrid-intake-{uuid4().hex}/",
        endpoint_url=_required("PROOF_AGENT_TEST_S3_ENDPOINT"),
        region_name="us-east-1",
        allow_insecure_endpoint=True,
    )
    service = ProductionHybridKnowledgeIntakeService(
        knowledge=bundle.knowledge,
        ingestion=bundle.hybrid_ingestion,
        unit_of_work_factory=bundle.configuration_uow,
        artifact_store=store,
        build_config=HybridPrivateParserBuildConfig(
            parser_revision="private-parser-v1",
            model_digests=("sha256:model-v1",),
            configuration_sha256="b" * 64,
        ),
    )
    actor = AuditActorFacts(
        subject="operator-1",
        identity_provider="enterprise-oidc",
        session_id=str(uuid4()),
        permissions=("knowledge_source.edit",),
    )
    source_id = f"ks_{uuid4().hex}"
    try:
        service.create_source(
            source_id=source_id,
            name="Insurance terms",
            params={},
            actor=actor,
        )
        assert bundle.knowledge.resolve_version(source_id).revision == 1

        content = _pdf()
        admission = service.admit_pdf(
            source_id=source_id,
            filename="terms.pdf",
            content_type="application/pdf",
            content=content,
            actor=actor,
        )

        assert admission.page_count == 1
        assert admission.request.original_ref.version_id
        assert admission.request.original_ref.version_id != (
            f"sha256:{admission.request.original_ref.sha256}"
        )
        assert store.get_exact(admission.request.original_ref) == content
        record = bundle.hybrid_ingestion.get_record(admission.request.job_id)
        assert record is not None
        assert record.filename == "terms.pdf"
        assert record.uploaded_by == "operator-1"
        assert record.build_request == admission.request
        assert record.job.state == "READY"
        assert bundle.knowledge.resolve_version(source_id).revision == 2
        assert (
            bundle.knowledge.get_knowledge_source(source_id).source_draft_version_id
            == admission.source.source_draft_version_id
        )
        with bundle.engine.connect() as connection:
            events = connection.execute(
                select(audit_events.c.event_type).order_by(audit_events.c.occurred_at)
            ).scalars().all()
        assert events == ["knowledge_source.created", "hybrid_pdf.admitted"]
    finally:
        store.close()
        bundle.close()
