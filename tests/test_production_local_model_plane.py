from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Literal

import pytest

from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    ImmediateKnowledgeModelWorkScheduler,
    KnowledgeModelCancellation,
)
from proof_agent.capabilities.knowledge.hybrid.metadata_review import (
    create_insurance_metadata_review_set,
    proofagent_insurance_reference_profile,
)
from proof_agent.capabilities.knowledge.hybrid.parser_clients import (
    ParserServiceAttestation,
    ParserServiceRequest,
    PrivateDoclingClient,
    PrivatePaddleClient,
    decode_parser_service_attestation,
)
from proof_agent.capabilities.knowledge.hybrid.pipeline import (
    PrivateHybridParserPipeline,
)
from proof_agent.capabilities.knowledge.hybrid.rule_units import project_rule_units
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildRequest,
    HybridKnowledgeWorker,
    hybrid_build_request_sha256,
)
from proof_agent.contracts.knowledge_index import ExactArtifactRef


def _model_plane() -> ModuleType:
    path = Path(__file__).parents[1] / "docker" / "production-local" / "model_plane.py"
    spec = importlib.util.spec_from_file_location("proof_agent_test_model_plane", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runtime_verifier() -> ModuleType:
    path = Path(__file__).parents[1] / "docker" / "production-local" / "verify_runtime.py"
    spec = importlib.util.spec_from_file_location(
        "proof_agent_test_runtime_verifier", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_parser_preserves_server_owned_document_identity() -> None:
    model_plane = _model_plane()
    response = model_plane._parser_response(
        {
            "document_id": "document-authority-1",
            "revision_id": "revision-authority-1",
            "original_ref": {
                "artifact_uri": "s3://proof-agent/original.pdf",
                "version_id": "version-1",
                "sha256": "a" * 64,
                "size_bytes": 1024,
                "media_type": "application/pdf",
            },
            "page_numbers": [1],
            "parser_revision": "docling@sha256:localproductionv1",
            "model_digests": ["sha256:docling-local-fixture-v1"],
            "configuration_sha256": "b" * 64,
            "allow_runtime_downloads": False,
        },
        adapter="docling",
    )

    assert response["vendor_json"]["document_id"] == "document-authority-1"
    assert response["vendor_json"]["revision_id"] == "revision-authority-1"


def test_local_model_plane_build_passes_worker_integrity_validation() -> None:
    model_plane = _model_plane()
    scheduler = ImmediateKnowledgeModelWorkScheduler()

    class ModelPlaneParserTransport:
        def __init__(self, adapter: Literal["docling", "paddle"]) -> None:
            self.adapter = adapter

        def parse(
            self,
            request: ParserServiceRequest,
            *,
            follow_redirects: Literal[False],
        ) -> ParserServiceAttestation:
            assert follow_redirects is False
            payload = request.model_dump(mode="json")
            payload["allow_runtime_downloads"] = False
            return decode_parser_service_attestation(
                model_plane._parser_response(payload, adapter=self.adapter)
            )

    pipeline = PrivateHybridParserPipeline(
        docling=PrivateDoclingClient(
            transport=ModelPlaneParserTransport("docling"),
            scheduler=scheduler,
        ),
        paddle=PrivatePaddleClient(
            transport=ModelPlaneParserTransport("paddle"),
            scheduler=scheduler,
        ),
        require_insurance_metadata_drafts=True,
    )
    request = HybridArtifactBuildRequest(
        job_id="job-production-local-parser",
        request_identity="source-1:document-authority-1:revision-authority-1",
        source_id="source-1",
        document_id="document-authority-1",
        revision_id="revision-authority-1",
        original_ref=ExactArtifactRef(
            artifact_uri="s3://proof-agent/original.pdf",
            version_id="version-1",
            sha256="a" * 64,
            size_bytes=1024,
            media_type="application/pdf",
        ),
        page_numbers=(1, 2),
        parser_revision="docling@sha256:localproductionv1",
        model_digests=(
            "docling@sha256:localproductionv1",
            "paddle@sha256:localproductionv1",
        ),
        configuration_sha256="b" * 64,
    )
    request = request.model_copy(
        update={"request_sha256": hybrid_build_request_sha256(request)}
    )

    parsed = pipeline.build(request, cancellation=KnowledgeModelCancellation())

    HybridKnowledgeWorker._validate_parser_output(request, parsed)


def test_local_model_plane_auto_reviews_into_one_confirmable_document_default() -> None:
    model_plane = _model_plane()
    scheduler = ImmediateKnowledgeModelWorkScheduler()

    class ModelPlaneParserTransport:
        def parse(
            self,
            request: ParserServiceRequest,
            *,
            follow_redirects: Literal[False],
        ) -> ParserServiceAttestation:
            assert follow_redirects is False
            payload = request.model_dump(mode="json")
            payload["allow_runtime_downloads"] = False
            return decode_parser_service_attestation(
                model_plane._parser_response(payload, adapter="docling")
            )

    client = PrivateDoclingClient(
        transport=ModelPlaneParserTransport(),
        scheduler=scheduler,
    )
    pipeline = PrivateHybridParserPipeline(
        docling=client,
        paddle=PrivatePaddleClient(
            transport=ModelPlaneParserTransport(),
            scheduler=scheduler,
        ),
        require_insurance_metadata_drafts=True,
    )
    request = HybridArtifactBuildRequest(
        job_id="job-ai-review",
        request_identity="ks_insurance:document-ai-review:revision-ai-review",
        source_id="ks_insurance",
        document_id="document-ai-review",
        revision_id="revision-ai-review",
        original_ref=ExactArtifactRef(
            artifact_uri="s3://proof-agent/original.pdf",
            version_id="version-ai-review",
            sha256="c" * 64,
            size_bytes=1024,
            media_type="application/pdf",
        ),
        page_numbers=(1, 2),
        parser_revision="docling@sha256:localproductionv1",
        model_digests=("docling@sha256:localproductionv1",),
        configuration_sha256="d" * 64,
    )
    request = request.model_copy(
        update={"request_sha256": hybrid_build_request_sha256(request)}
    )

    parsed = pipeline.build(request, cancellation=KnowledgeModelCancellation())
    review_set = create_insurance_metadata_review_set(
        source_id=request.source_id,
        structured_build_id=parsed.artifact.build_identity.build_id,
        profile=proofagent_insurance_reference_profile(),
        document_default=parsed.insurance_metadata.document_defaults,
        parser_proposals=parsed.insurance_metadata.pdf_drafts,
        canonical_anchors=(
            unit.canonical_anchor
            for unit in project_rule_units(
                parsed.artifact,
                document_defaults=parsed.insurance_metadata.document_defaults,
                source_id=request.source_id,
            )
        ),
    )

    assert len(review_set.reviews) == 1
    assert review_set.reviews[0].scope == "document_default"
    assert review_set.reviews[0].state == "ready_for_approval"
    assert review_set.reviews[0].current_draft.authority == "national"


def test_runtime_verifier_parser_requests_match_model_plane_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_plane = _model_plane()
    runtime_verifier = _runtime_verifier()

    def post(url: str, payload: dict[str, object]) -> None:
        if url.endswith(":9444/v1/parse"):
            model_plane._parser_response(payload, adapter="docling")
        if url.endswith(":9445/v1/parse"):
            model_plane._parser_response(payload, adapter="paddle")

    class HealthyResponse:
        status = 200

        def __enter__(self) -> HealthyResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(runtime_verifier, "_post", post)
    monkeypatch.setattr(
        runtime_verifier.urllib.request,
        "urlopen",
        lambda *args, **kwargs: HealthyResponse(),
    )

    runtime_verifier.main()
