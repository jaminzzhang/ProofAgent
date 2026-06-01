"""Tests for Agent Configuration Workspace contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from proof_agent.contracts import (
    ActiveAgentVersion,
    AgentValidationRecord,
    ConfigurationOperation,
    ConfigurationOperationAudit,
    ContractBundle,
    DraftAgent,
    KnowledgeArtifactBuildSpec,
    KnowledgeDocument,
    KnowledgeIngestionJob,
    KnowledgeSource,
    QuarantinedKnowledgeUpload,
    PublishedAgentVersion,
    ToolSource,
)
from proof_agent.errors import ErrorCode


def _contract_bundle() -> ContractBundle:
    return ContractBundle(
        agent_yaml="name: enterprise_qa\n",
        policy_yaml="rules: []\n",
        tools_yaml="tools: {}\n",
        extra_files={"knowledge/README.md": "# Knowledge\n"},
        advanced_fields={"customer": {"adapter": "./customer_adapter.py"}},
    )


def test_contract_bundle_preserves_reviewable_files_and_advanced_fields() -> None:
    bundle = _contract_bundle()

    payload = bundle.model_dump(mode="json")

    assert payload["agent_yaml"].startswith("name:")
    assert payload["policy_yaml"] == "rules: []\n"
    assert payload["tools_yaml"] == "tools: {}\n"
    assert payload["extra_files"]["knowledge/README.md"] == "# Knowledge\n"
    assert payload["advanced_fields"]["customer"]["adapter"] == "./customer_adapter.py"


def test_draft_agent_is_editable_state_not_a_published_version() -> None:
    draft = DraftAgent(
        agent_id="enterprise_qa",
        draft_id="draft_001",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=_contract_bundle(),
        created_at="2026-05-27T00:00:00Z",
        updated_at="2026-05-27T00:00:00Z",
        created_by="local-user",
        updated_by="local-user",
    )

    assert draft.agent_id == "enterprise_qa"
    assert draft.draft_id == "draft_001"
    assert draft.version_id is None
    assert draft.validation_records == ()


def test_published_agent_version_requires_validation_run_id() -> None:
    version = PublishedAgentVersion(
        agent_id="enterprise_qa",
        version_id="version_001",
        source_draft_id="draft_001",
        validation_run_id="run_validation_001",
        contract_bundle=_contract_bundle(),
        published_at="2026-05-27T00:05:00Z",
        published_by="local-user",
    )

    assert version.validation_run_id == "run_validation_001"
    assert version.source_draft_id == "draft_001"

    with pytest.raises(ValidationError):
        PublishedAgentVersion(
            agent_id="enterprise_qa",
            version_id="version_002",
            source_draft_id="draft_001",
            validation_run_id="",
            contract_bundle=_contract_bundle(),
            published_at="2026-05-27T00:06:00Z",
            published_by="local-user",
        )


def test_active_agent_version_points_at_immutable_version() -> None:
    active = ActiveAgentVersion(
        agent_id="enterprise_qa",
        version_id="version_001",
        activated_at="2026-05-27T00:10:00Z",
        activated_by="publisher",
        rollback_from_version_id="version_002",
    )

    assert active.version_id == "version_001"
    assert active.rollback_from_version_id == "version_002"


def test_sources_are_reusable_assets_not_agent_bindings() -> None:
    knowledge = KnowledgeSource(
        source_id="ks_local_docs",
        name="Local Docs",
        provider="local_markdown",
        params={"path": "./knowledge"},
        created_at="2026-05-27T00:00:00Z",
        updated_at="2026-05-27T00:00:00Z",
    )
    tool = ToolSource(
        source_id="ts_local_tools",
        name="Local Fixture Tools",
        source_type="local_handler_package",
        tool_contract_ids=("policy_status_lookup", "claim_status_lookup"),
        params={"root": "./tools"},
        created_at="2026-05-27T00:00:00Z",
        updated_at="2026-05-27T00:00:00Z",
    )

    assert knowledge.provider == "local_markdown"
    assert knowledge.params["path"] == "./knowledge"
    assert tool.tool_contract_ids == ("policy_status_lookup", "claim_status_lookup")


def test_validation_record_links_draft_to_governed_run() -> None:
    record = AgentValidationRecord(
        validation_id="validation_001",
        draft_id="draft_001",
        run_id="run_validation_001",
        status="passed",
        created_at="2026-05-27T00:00:00Z",
        summary="Contract validation and test run passed.",
    )

    assert record.run_id == "run_validation_001"
    assert record.errors == ()


def test_configuration_operation_audit_is_json_serializable() -> None:
    audit = ConfigurationOperationAudit(
        operation_id="op_001",
        operation=ConfigurationOperation.IMPORTED,
        actor="local-user",
        created_at="2026-05-27T00:00:00Z",
        summary="Imported proof_agent/evaluation/demo/fixtures/enterprise_qa.",
        metadata={"source_path": "proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"},
    )

    payload = audit.model_dump(mode="json")

    assert payload["operation"] == "imported"
    assert (
        payload["metadata"]["source_path"]
        == "proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"
    )


def test_configuration_contracts_are_frozen() -> None:
    draft = DraftAgent(
        agent_id="enterprise_qa",
        draft_id="draft_001",
        display_name="Enterprise QA",
        purpose="Answer enterprise questions with evidence.",
        contract_bundle=_contract_bundle(),
        created_at="2026-05-27T00:00:00Z",
        updated_at="2026-05-27T00:00:00Z",
        created_by="local-user",
        updated_by="local-user",
    )

    with pytest.raises(ValidationError):
        draft.display_name = "Changed"  # type: ignore[misc]


def test_knowledge_ingestion_task_contracts_are_frozen_and_json_serializable() -> None:
    upload = QuarantinedKnowledgeUpload(
        upload_id="upload_001",
        source_id="ks_policy",
        filename="policy.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        storage_path="knowledge_sources/ks_policy/quarantined_uploads/upload_001/original-upload.bin",
        state="queued",
        created_at="2026-06-01T00:00:00Z",
        updated_at="2026-06-01T00:00:00Z",
    )
    build_spec = KnowledgeArtifactBuildSpec(
        provider="local_index",
        engine_name="llama-index-tree",
        engine_version="llama-index-tree@0.14.22",
        parser_fingerprint_identity="pypdf:v1@6.12.2",
        content_hash="original-sha256",
        parsed_text_sha256="parsed-text-sha256",
        declared_ingestion_model={
            "provider": "openai",
            "name": "gpt-4.1-mini",
            "params": {"api_key_env": "OPENAI_API_KEY"},
        },
    )
    job = KnowledgeIngestionJob(
        job_id="job_001",
        source_id="ks_policy",
        document_id="doc_001",
        revision_id="rev_001",
        state="queued",
        ingestion_config_fingerprint="fingerprint",
        artifact_build_spec=build_spec,
        created_at="2026-06-01T00:00:00Z",
        updated_at="2026-06-01T00:00:00Z",
    )

    assert upload.attempt_count == 0
    assert upload.claim_token is None
    assert upload.lease_expires_at is None
    assert job.attempt_count == 0
    assert job.auto_retry_count == 0
    assert job.max_auto_retries == 2
    assert job.artifact_path is None
    assert job.claimed_at is None
    assert job.completed_at is None
    assert job.model_dump(mode="json")["artifact_build_spec"]["engine_version"] == (
        "llama-index-tree@0.14.22"
    )

    with pytest.raises(ValidationError):
        upload.state = "processing"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        job.state = "processing"  # type: ignore[misc]


def test_knowledge_document_defaults_ingestion_job_and_artifact_reference() -> None:
    document = KnowledgeDocument(
        document_id="doc_001",
        source_id="ks_policy",
        revision_id="rev_001",
        filename="policy.pdf",
        content_type="application/pdf",
        content_hash="original-sha256",
        size_bytes=1024,
        state="queued",
        storage_path="knowledge_sources/ks_policy/documents/doc_001/revisions/rev_001/original.bin",
        created_at="2026-06-01T00:00:00Z",
        updated_at="2026-06-01T00:00:00Z",
    )

    assert document.ingestion_job_id is None
    assert document.artifact_path is None


def test_knowledge_ingestion_error_codes_are_stable() -> None:
    assert ErrorCode.PA_INGESTION_001.value == "PA_INGESTION_001"
    assert ErrorCode.PA_INGESTION_002.value == "PA_INGESTION_002"
    assert ErrorCode.PA_INGESTION_003.value == "PA_INGESTION_003"
    assert ErrorCode.PA_INGESTION_004.value == "PA_INGESTION_004"
