from datetime import UTC, datetime

import pytest

from proof_agent.contracts import InstitutionAuthorizationContext
from proof_agent.contracts.agent_configuration import ContractBundle, PublishedAgentVersion
from proof_agent.contracts.egress import EgressPolicyVersion
from proof_agent.contracts.run_execution import RunRequest
from proof_agent.contracts.security import PermissionMappingVersion
from proof_agent.control.run_execution import (
    RunExecutionSnapshotAuthority,
    RunSnapshotAuthorityError,
)


NOW = datetime(2026, 7, 15, tzinfo=UTC)
VERSION_ID = "019ba001-1111-7000-8000-000000000001"
AUTHORITY_ID = "019ba001-1111-7000-8000-000000000099"


class Agents:
    def __init__(self, version):
        self.version = version

    def get_published(self, agent_id, version_id):
        if self.version is None:
            return None
        assert agent_id == self.version.agent_id
        assert version_id == self.version.version_id
        return self.version


class Security:
    def __init__(self):
        self.mapping = PermissionMappingVersion(
            version_id=AUTHORITY_ID,
            revision=1,
            created_at="2026-07-15T00:00:00Z",
            created_by="operator-1",
        )
        self.egress = EgressPolicyVersion(
            version_id=AUTHORITY_ID,
            revision=1,
            created_at="2026-07-15T00:00:00Z",
            created_by="operator-1",
        )

    def get_permission_mapping(self, version_id):
        return self.mapping if version_id == self.mapping.version_id else None

    def get_active_egress_policy(self):
        return self.egress


def _version() -> PublishedAgentVersion:
    return PublishedAgentVersion(
        agent_id="agent_management_insurance_specialist",
        version_id=VERSION_ID,
        source_draft_id="019ba001-1111-7000-8000-000000000002",
        validation_run_id="019ba001-1111-7000-8000-000000000003",
        contract_bundle=ContractBundle(
            agent_yaml=(
                "schema_version: 3\n"
                "model:\n"
                "  credential_secret_handle: model/primary\n"
            ),
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
        ),
        published_at="2026-07-15T00:00:00Z",
        published_by="operator-1",
    )


def _request() -> RunRequest:
    return RunRequest(
        run_id="019ba001-1111-7000-8000-000000000010",
        operator_subject="operator-1",
        idempotency_key="submit-1",
        agent_id="agent_management_insurance_specialist",
        agent_version_id=VERSION_ID,
        question="question",
        permission_mapping_version_id=AUTHORITY_ID,
        permission_epoch=7,
        institution_authorization=InstitutionAuthorizationContext(
            institutions=("branch-shanghai",),
        ),
        submitted_at=NOW,
    )


def test_snapshot_authority_freezes_agent_security_and_secret_handle_digests() -> None:
    authority = RunExecutionSnapshotAuthority(
        agents=Agents(_version()),  # type: ignore[arg-type]
        security=Security(),  # type: ignore[arg-type]
        release_id="proofagent-2026.07.15",
        image_digest="sha256:" + "a" * 64,
    )

    snapshot = authority(
        _request(),
        "019ba001-1111-7000-8000-000000000020",
        1,
        NOW,
    )

    assert snapshot.image_digest == "a" * 64
    assert snapshot.secret_handle_ids == ("model/primary",)
    assert snapshot.permission_epoch == 7
    assert snapshot.institution_authorization_sha256 == _request().institution_authorization_sha256
    assert all(
        len(value) == 64
        for value in (
            snapshot.agent_configuration_sha256,
            snapshot.knowledge_configuration_sha256,
            snapshot.model_configuration_sha256,
            snapshot.egress_policy_sha256,
            snapshot.permission_mapping_sha256,
            snapshot.tool_configuration_sha256,
        )
    )


def test_snapshot_authority_fails_closed_when_exact_publication_disappears() -> None:
    authority = RunExecutionSnapshotAuthority(
        agents=Agents(None),  # type: ignore[arg-type]
        security=Security(),  # type: ignore[arg-type]
        release_id="proofagent-2026.07.15",
        image_digest="a" * 64,
    )

    with pytest.raises(RunSnapshotAuthorityError, match="unavailable"):
        authority(
            _request(),
            "019ba001-1111-7000-8000-000000000020",
            1,
            NOW,
        )
