from __future__ import annotations

import pytest
from pydantic import ValidationError

from proof_agent.contracts import (
    Permission,
    RecoveryOidcGroupMapping,
)
from proof_agent.observability.api.operator_identity import OperatorPermission


EXPECTED_PERMISSIONS = {
    "run.submit",
    "run.view",
    "run.cancel",
    "agent.view",
    "agent.edit",
    "agent.validate",
    "agent.publish",
    "knowledge_source.view",
    "knowledge_source.edit",
    "knowledge_source.review",
    "knowledge_source.publish",
    "knowledge_source.archive",
    "model_connection.view",
    "model_connection.edit",
    "model_connection.validate",
    "model_connection.archive",
    "tool_source.view",
    "tool_source.edit",
    "tool_source.validate",
    "tool_source.archive",
    "evaluation.view",
    "evaluation.run",
    "evaluation_curation.review",
    "permission_mapping.view",
    "permission_mapping.edit",
    "egress_policy.view",
    "egress_policy.edit",
    "secret_handle.view",
    "secret_handle.use",
    "audit.view",
    "audit.export",
}


def test_permission_vocabulary_is_exact_and_has_no_approval_resolution() -> None:
    assert {permission.value for permission in Permission} == EXPECTED_PERMISSIONS
    assert "approval.resolve" not in EXPECTED_PERMISSIONS
    assert OperatorPermission is Permission


def test_recovery_mapping_cannot_be_weakened() -> None:
    with pytest.raises(ValidationError, match="cannot weaken"):
        RecoveryOidcGroupMapping(
            claim_path="groups",
            group_name="proof-agent-recovery",
            permissions=(Permission.PERMISSION_MAPPING_VIEW,),
        )

    mapping = RecoveryOidcGroupMapping(
        claim_path="groups",
        group_name="proof-agent-recovery",
        permissions=(
            Permission.PERMISSION_MAPPING_VIEW,
            Permission.PERMISSION_MAPPING_EDIT,
            Permission.AUDIT_VIEW,
        ),
    )
    assert set(mapping.permissions) >= {
        Permission.PERMISSION_MAPPING_VIEW,
        Permission.PERMISSION_MAPPING_EDIT,
        Permission.AUDIT_VIEW,
    }
