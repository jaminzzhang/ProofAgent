"""Tests for Shared Model Connection configuration contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from proof_agent.contracts import (
    EnvironmentModelCredentialReference,
    ModelConnectionSmokeTestRecord,
    ModelConnectionValidationRecord,
    SharedModelConnection,
    SharedModelConnectionDeletionEligibility,
    SharedModelConnectionLifecycleState,
    SharedModelConnectionReferenceSummary,
)


def test_shared_model_connection_is_secret_safe_and_json_serializable() -> None:
    connection = SharedModelConnection(
        connection_id="model_deepseek_default",
        display_name="DeepSeek Default",
        description="Default DeepSeek connection",
        tags=("prod", "deepseek"),
        provider="deepseek",
        model_identifier="deepseek-chat",
        base_url="https://api.deepseek.com",
        credential_ref=EnvironmentModelCredentialReference(name="DEEPSEEK_API_KEY"),
        timeout_seconds=20,
        lifecycle_state=SharedModelConnectionLifecycleState.ACTIVE,
        created_at="2026-06-06T00:00:00Z",
        updated_at="2026-06-06T00:00:00Z",
    )

    payload = connection.model_dump(mode="json")

    assert payload["connection_id"] == "model_deepseek_default"
    assert payload["display_name"] == "DeepSeek Default"
    assert payload["credential_ref"] == {"type": "env", "name": "DEEPSEEK_API_KEY"}
    assert "api_key" not in payload
    assert "sk-" not in str(payload)

    with pytest.raises(ValidationError):
        connection.tags += ("changed",)


def test_shared_model_connection_supports_archived_lifecycle_state() -> None:
    connection = SharedModelConnection(
        connection_id="model_archived",
        display_name="Archived Model",
        provider="openai",
        model_identifier="gpt-4.1-mini",
        credential_ref=EnvironmentModelCredentialReference(name="OPENAI_API_KEY"),
        lifecycle_state=SharedModelConnectionLifecycleState.ARCHIVED,
        created_at="2026-06-06T00:00:00Z",
        updated_at="2026-06-06T00:05:00Z",
    )

    assert connection.lifecycle_state is SharedModelConnectionLifecycleState.ARCHIVED


def test_shared_model_connection_reference_summary_is_json_serializable() -> None:
    summary = SharedModelConnectionReferenceSummary(
        connection_id="model_deepseek_default",
        draft_agent_reference_count=2,
        published_agent_version_reference_count=1,
        knowledge_source_reference_count=3,
        in_flight_operation_count=0,
    )

    payload = summary.model_dump(mode="json")

    assert payload["draft_agent_reference_count"] == 2
    assert payload["published_agent_version_reference_count"] == 1
    assert payload["knowledge_source_reference_count"] == 3


def test_shared_model_connection_deletion_eligibility_serializes_blockers() -> None:
    summary = SharedModelConnectionReferenceSummary(
        connection_id="model_deepseek_default",
        draft_agent_reference_count=0,
        published_agent_version_reference_count=1,
        knowledge_source_reference_count=0,
        in_flight_operation_count=0,
    )
    eligibility = SharedModelConnectionDeletionEligibility(
        connection_id="model_deepseek_default",
        eligible=False,
        lifecycle_state=SharedModelConnectionLifecycleState.ARCHIVED,
        reference_summary=summary,
        blockers=("published_agent_version_reference_count must be 0",),
    )

    payload = eligibility.model_dump(mode="json")

    assert payload["eligible"] is False
    assert payload["blockers"] == ["published_agent_version_reference_count must be 0"]


def test_model_connection_validation_and_smoke_test_records_are_trace_safe() -> None:
    validation = ModelConnectionValidationRecord(
        validation_id="model_validation_001",
        connection_id="model_deepseek_default",
        status="failed",
        created_at="2026-06-06T00:00:00Z",
        created_by="operator",
        provider="deepseek",
        model_identifier="deepseek-chat",
        credential_ref=EnvironmentModelCredentialReference(name="DEEPSEEK_API_KEY"),
        checked_env_vars=("DEEPSEEK_API_KEY",),
        missing_env_vars=("DEEPSEEK_API_KEY",),
        error_code="PA_MODEL_CONNECTION_CREDENTIAL_MISSING",
        message="Missing credential environment variable: DEEPSEEK_API_KEY",
    )
    smoke_test = ModelConnectionSmokeTestRecord(
        smoke_test_id="model_smoke_001",
        connection_id="model_deepseek_default",
        status="skipped",
        created_at="2026-06-06T00:01:00Z",
        created_by="operator",
        provider="deepseek",
        model_identifier="deepseek-chat",
        credential_ref=EnvironmentModelCredentialReference(name="DEEPSEEK_API_KEY"),
        request_sent=False,
        error_code="PA_MODEL_CONNECTION_CREDENTIAL_MISSING",
        message="Missing credential environment variable: DEEPSEEK_API_KEY",
    )

    combined = {
        "validation": validation.model_dump(mode="json"),
        "smoke_test": smoke_test.model_dump(mode="json"),
    }

    assert combined["validation"]["missing_env_vars"] == ["DEEPSEEK_API_KEY"]
    assert combined["smoke_test"]["request_sent"] is False
    assert "raw_response" not in str(combined)
    assert "sk-" not in str(combined)
