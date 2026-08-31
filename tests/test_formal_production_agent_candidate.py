from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace, TracebackType
from typing import BinaryIO, Literal, cast

import pytest
from pydantic import ValidationError

from proof_agent.configuration.knowledge_release import (
    knowledge_release_candidate_sha256,
    require_formal_production_agent_phase_f_record,
)
from proof_agent.configuration.importer import build_agent_package_contract_bundle
from proof_agent.contracts import (
    ActiveAgentVersion,
    AgentDraftRecord,
    AgentPublicationRecord,
    AuditActorFacts,
    AuditMetadataRecord,
    ContractBundle,
    DraftAgent,
    DraftKnowledgeReleaseBindingCandidate,
    ExactArtifactRef,
    FormalProductionAgentCandidate,
    FormalProductionAgentOnlineSmokeQualification,
    FormalProductionAgentOnlineSmokeRequest,
    FormalProductionAgentOnlineSmokeResult,
    FormalProductionAgentPhaseFPreparation,
    FormalProductionAgentPhaseFRecord,
    FormalProductionAgentQueryGrantStaging,
    FormalProductionAgentPublicationCommandReceipt,
    FormalProductionAgentPublicationCommandRequest,
    FormalProductionAgentPublicationCommandState,
    FormalProductionAgentPublicationEvidence,
    FormalProductionAgentReferenceStaging,
    InstitutionAuthorizationContext,
    KnowledgeReleaseEvidenceSet,
    PostgresEncryptedModelCredentialReference,
    ProductionKssBindingProfile,
    ProductionAgentKnowledgeQueryGrantRequest,
    ProductionAgentReleaseReferenceRequest,
    ProductionSecretHandle,
    PublishedAgentVersion,
    ReceiptOutcome,
    ProvisionedProductionAgentKnowledgeQueryGrant,
    RegisteredProductionAgentReleaseReference,
    RunPurpose,
    SecretPurpose,
    SharedModelConnection,
    SharedModelConnectionLifecycleState,
)
from proof_agent.contracts.persistence import (
    FormalProductionAgentPublicationCandidateCheckpoint,
    FormalProductionAgentPublicationExecutionClaim,
    FormalProductionAgentPublicationCommandRecord,
    FormalProductionAgentPublicationCommandReservation,
    PersistenceConflictError,
    PersistencePointerConflictError,
)
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceManagementWorkspace,
    KnowledgeServiceReadinessProjection,
    KnowledgeServiceReleaseProjection,
)
from proof_agent.contracts.artifacts import (
    ArtifactObjectVersion,
    ArtifactPutRequest,
)
from proof_agent.contracts.ports.knowledge_candidates import (
    KnowledgeCandidateAdmissionError,
    KnowledgeCandidateAdmissionFailureReason,
)
from proof_agent.control.formal_production_agent_candidate import (
    FormalProductionAgentCandidateAssembler,
    FormalProductionAgentCandidateRejected,
    FormalProductionKnowledgeReleaseCatalog,
    formal_production_agent_candidate_sha256,
)
from proof_agent.control.formal_production_agent_phase_f import (
    FormalProductionAgentPhaseFPreparer,
    FormalProductionAgentPhaseFRejected,
)
from proof_agent.control.formal_production_agent_online_smoke import (
    FormalProductionAgentOnlineSmokeRejected,
    FormalProductionAgentOnlineSmokeService,
)
from proof_agent.control.formal_production_agent_publication import (
    FormalProductionAgentPublicationRejected,
    FormalProductionAgentPublisher,
)
from proof_agent.control.formal_production_agent_publication_command import (
    FormalProductionAgentPublicationCommandRejected,
    FormalProductionAgentPublicationCommandService,
)
from proof_agent.control.formal_production_agent_reference_staging import (
    FormalProductionAgentReferenceStager,
    FormalProductionAgentReferenceStagingRejected,
)
from proof_agent.control.formal_production_agent_query_grant_staging import (
    FormalProductionAgentQueryGrantStager,
    FormalProductionAgentQueryGrantStagingRejected,
)
from proof_agent.control.production_agent_publication_configuration import (
    ProductionAgentPublicationConfigurationProjector,
)
from proof_agent.control.production_agent import ProductionAgentValidationError
from proof_agent.delivery.production_agent_validation import (
    FormalCandidateExternalSmokeDiagnosticError,
    FormalProductionAgentCandidateExternalSmokeRunner,
    FormalProductionAgentOnlineSmokeRunner,
)
from proof_agent.errors import ProofAgentError


class _DraftRepository:
    def __init__(self, record: AgentDraftRecord | None) -> None:
        self.record = record

    def get_draft(self, agent_id: str, draft_id: str) -> AgentDraftRecord | None:
        if self.record is None:
            return None
        if self.record.draft.agent_id != agent_id or self.record.draft.draft_id != draft_id:
            return None
        return self.record


class _ReadOnlyUnitOfWork:
    def __init__(self, record: AgentDraftRecord | None) -> None:
        self.agents = _DraftRepository(record)
        self.committed = False

    def __enter__(self) -> _ReadOnlyUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    def commit(self) -> None:
        self.committed = True


class _UnitOfWorkFactory:
    def __init__(self, record: AgentDraftRecord | None) -> None:
        self.record = record
        self.units: list[_ReadOnlyUnitOfWork] = []

    def __call__(self) -> _ReadOnlyUnitOfWork:
        unit = _ReadOnlyUnitOfWork(self.record)
        self.units.append(unit)
        return unit


class _Catalog:
    def __init__(
        self,
        workspace: KnowledgeServiceManagementWorkspace,
        *,
        before_call: Callable[[], None] | None = None,
    ) -> None:
        self._workspace = workspace
        self._before_call = before_call

    def workspace(self) -> KnowledgeServiceManagementWorkspace:
        if self._before_call is not None:
            self._before_call()
        return self._workspace


class _UnavailableCatalog:
    def workspace(self) -> KnowledgeServiceManagementWorkspace:
        raise RuntimeError("private upstream failure")


class _ModelConnections:
    def __init__(self, connection: SharedModelConnection) -> None:
        self._connection = connection

    def get_model_connection(self, connection_id: str) -> SharedModelConnection | None:
        if connection_id == self._connection.connection_id:
            return self._connection
        return None


class _PhaseFAuthority:
    def __init__(
        self,
        *,
        authorized: bool = True,
        failure: Exception | None = None,
        before_call: Callable[[], None] | None = None,
    ) -> None:
        self.authorized = authorized
        self.failure = failure
        self.before_call = before_call
        self.records: list[FormalProductionAgentPhaseFRecord] = []

    def verify_phase_f_record(self, record: FormalProductionAgentPhaseFRecord) -> bool:
        if self.before_call is not None:
            self.before_call()
        self.records.append(record)
        if self.failure is not None:
            raise self.failure
        return self.authorized


class _ReferenceRegistrar:
    def __init__(
        self,
        *,
        failure: Exception | None = None,
        receipt_updates: dict[str, object] | None = None,
        before_call: Callable[[], None] | None = None,
    ) -> None:
        self.failure = failure
        self.receipt_updates = receipt_updates or {}
        self.before_call = before_call
        self.calls: list[tuple[ProductionAgentReleaseReferenceRequest, str]] = []
        self.references: dict[str, RegisteredProductionAgentReleaseReference] = {}

    def register_release_reference(
        self,
        request: ProductionAgentReleaseReferenceRequest,
        *,
        idempotency_key: str,
    ) -> RegisteredProductionAgentReleaseReference:
        if self.before_call is not None:
            self.before_call()
        self.calls.append((request, idempotency_key))
        if self.failure is not None:
            raise self.failure
        existing = self.references.get(idempotency_key)
        if existing is not None:
            return existing
        reference = RegisteredProductionAgentReleaseReference(
            **request.model_dump(mode="python"),
            release_reference_id="release-reference-05c",
            authenticated_client_id="proof-agent-production",
            registered_at=datetime(2026, 8, 30, 12, 31, tzinfo=UTC),
        )
        reference = reference.model_copy(update=self.receipt_updates)
        self.references[idempotency_key] = reference
        return reference


class _QueryGrantProvisioner:
    def __init__(
        self,
        *,
        failure: Exception | None = None,
        receipt_updates: dict[str, object] | None = None,
        before_call: Callable[[], None] | None = None,
    ) -> None:
        self.failure = failure
        self.receipt_updates = receipt_updates or {}
        self.before_call = before_call
        self.calls: list[ProductionAgentKnowledgeQueryGrantRequest] = []

    def provision_query_grant(
        self,
        request: ProductionAgentKnowledgeQueryGrantRequest,
    ) -> ProvisionedProductionAgentKnowledgeQueryGrant:
        if self.before_call is not None:
            self.before_call()
        self.calls.append(request)
        if self.failure is not None:
            raise self.failure
        receipt = ProvisionedProductionAgentKnowledgeQueryGrant(
            knowledge_base_release_id=request.knowledge_base_release_id,
            client_grant_id="query-grant-runtime-05m",
            client_id="proof-agent-runtime",
            knowledge_space_id="insurance",
            allowed_strategies=("single_pass", "agentic"),
            execution_budget={
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 20,
                "max_model_tokens": 1_000,
                "max_duration_ms": 5_000,
            },
            effective_access_scope_digest=f"sha256:{'c' * 64}",
            created_at=datetime(2026, 8, 30, 13, 30, tzinfo=UTC),
        )
        return receipt.model_copy(update=self.receipt_updates)


class _OnlineSmokeValidator:
    def __init__(
        self,
        *,
        failure: Exception | None = None,
        result_updates: dict[str, object] | None = None,
        before_call: Callable[[], None] | None = None,
        after_call: Callable[[], None] | None = None,
    ) -> None:
        self.failure = failure
        self.result_updates = result_updates or {}
        self.before_call = before_call
        self.after_call = after_call
        self.calls: list[FormalProductionAgentOnlineSmokeRequest] = []

    def validate_online_smoke(
        self,
        request: FormalProductionAgentOnlineSmokeRequest,
        *,
        query_grant_staging: FormalProductionAgentQueryGrantStaging,
    ) -> FormalProductionAgentOnlineSmokeResult:
        assert (
            query_grant_staging.reference_staging.release_reference.release_reference_id
            == request.release_reference_id
        )
        if self.before_call is not None:
            self.before_call()
        self.calls.append(request)
        if self.failure is not None:
            raise self.failure
        result = FormalProductionAgentOnlineSmokeResult(
            agent_id=request.agent_id,
            provisional_version_id=request.provisional_version_id,
            validation_run_id=request.validation_run_id,
            release_reference_id=request.release_reference_id,
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            accepted_citation_count=2,
            trace_ref=_artifact("online-smoke-trace", "6"),
            receipt_ref=_artifact("online-smoke-receipt", "7"),
        )
        if self.after_call is not None:
            self.after_call()
        return result.model_copy(update=self.result_updates)


class _ExactArtifactStore:
    def __init__(self, *, readback_override: bytes | None = None) -> None:
        self.contents: dict[str, bytes] = {}
        self.versions: dict[ArtifactObjectVersion, bytes] = {}
        self.readback_override = readback_override

    def put_immutable(
        self,
        request: ArtifactPutRequest,
        body: BinaryIO,
    ) -> ArtifactObjectVersion:
        content = body.read()
        assert request.expected_sha256 == hashlib.sha256(content).hexdigest()
        assert request.expected_size_bytes == len(content)
        sequence = len(self.versions) + 1
        ref = ArtifactObjectVersion(
            object_id=f"artifact-{sequence}",
            bucket="formal-online-smoke",
            object_key=f"objects/00/00000000-0000-0000-0000-{sequence:012d}",
            version_id=f"artifact-{sequence}",
            sha256=request.expected_sha256,
            size_bytes=request.expected_size_bytes,
            kind=request.kind,
            owner=request.owner,
            content_type=request.content_type,
            created_at=datetime(2026, 7, 15, tzinfo=UTC),
            display_filename=request.display_filename,
        )
        self.versions[ref] = content
        return ref

    def head_exact(self, reference: ArtifactObjectVersion) -> ArtifactObjectVersion:
        assert reference in self.versions
        return reference

    def open_exact(self, reference: ArtifactObjectVersion) -> BytesIO:
        if self.readback_override is not None:
            return BytesIO(self.readback_override)
        return BytesIO(self.versions[reference])

    def exact_uri(self, reference: ArtifactObjectVersion) -> str:
        self.head_exact(reference)
        artifact_uri = f"s3://{reference.bucket}/{reference.object_key}"
        self.contents[artifact_uri] = self.versions[reference]
        return artifact_uri

    def get_exact(self, reference: ExactArtifactRef) -> bytes:
        if self.readback_override is not None:
            return self.readback_override
        return self.contents[reference.artifact_uri]


class _FormalPublicationState:
    def __init__(
        self,
        *,
        record: AgentDraftRecord,
        active: ActiveAgentVersion | None = None,
        audit_failure: Exception | None = None,
        command_failures: list[Exception] | None = None,
    ) -> None:
        self.record = record
        self.active = active
        self.audit_failure = audit_failure
        self.command_failures = list(command_failures or [])
        self.publications: list[AgentPublicationRecord] = []
        self.audits: list[AuditMetadataRecord] = []
        self.formal_publication_commands: dict[
            tuple[str, str], FormalProductionAgentPublicationCommandRecord
        ] = {}


class _FormalPublicationAgents:
    def __init__(self, unit: _FormalPublicationUnitOfWork) -> None:
        self._unit = unit

    def get_draft(self, agent_id: str, draft_id: str) -> AgentDraftRecord | None:
        record = self._unit.factory.state.record
        if record.draft.agent_id != agent_id or record.draft.draft_id != draft_id:
            return None
        return record

    def list_active(self) -> tuple[ActiveAgentVersion, ...]:
        active = self._unit.factory.state.active
        return () if active is None else (active,)

    def publish_version(
        self,
        publication: AgentPublicationRecord,
        *,
        expected_draft_revision: int,
    ) -> AgentPublicationRecord:
        state = self._unit.factory.state
        if state.record.revision != expected_draft_revision:
            raise PersistenceConflictError(
                resource_type="agent_draft",
                resource_id=publication.version.source_draft_id,
                expected_revision=expected_draft_revision,
                actual_revision=state.record.revision,
            )
        expectation = publication.active_pointer_expectation
        actual = None if state.active is None else state.active.version_id
        expected = None if expectation is None else expectation.version_id
        if actual != expected:
            raise PersistencePointerConflictError(
                resource_type="active_agent_version",
                resource_id=publication.version.agent_id,
                expected_pointer=expected,
                actual_pointer=actual,
            )
        self._unit.pending_publication = publication
        self._unit.pending_active = publication.activation
        return publication


class _FormalPublicationAudits:
    def __init__(self, unit: _FormalPublicationUnitOfWork) -> None:
        self._unit = unit

    def append(self, event: AuditMetadataRecord) -> None:
        failure = self._unit.factory.state.audit_failure
        if failure is not None:
            raise failure
        self._unit.pending_audits.append(event)


class _FormalPublicationCommands:
    def __init__(self, unit: _FormalPublicationUnitOfWork) -> None:
        self._unit = unit

    def reserve(
        self,
        record: FormalProductionAgentPublicationCommandRecord,
        *,
        lease_duration: timedelta,
    ) -> FormalProductionAgentPublicationCommandReservation:
        assert lease_duration > timedelta(0)
        key = (record.actor_subject, record.idempotency_key)
        existing = self._unit.pending_commands.get(key)
        if existing is None:
            existing = self._unit.factory.state.formal_publication_commands.get(key)
        if existing is not None:
            existing_claim = existing.execution_claim
            proposed_claim = record.execution_claim
            assert proposed_claim is not None
            if (
                existing.receipt.state is FormalProductionAgentPublicationCommandState.IN_PROGRESS
                and existing_claim is not None
                and _test_timestamp(existing_claim.lease_expires_at)
                <= _test_timestamp(record.receipt.started_at)
            ):
                taken_over = existing.model_copy(
                    update={
                        "execution_claim": FormalProductionAgentPublicationExecutionClaim(
                            fencing_token=existing_claim.fencing_token + 1,
                            owner_id=proposed_claim.owner_id,
                            lease_expires_at=proposed_claim.lease_expires_at,
                        )
                    }
                )
                self._unit.pending_commands[key] = taken_over
                return FormalProductionAgentPublicationCommandReservation(
                    record=taken_over,
                    created=False,
                    acquired=True,
                )
            return FormalProductionAgentPublicationCommandReservation(
                record=existing,
                created=False,
                acquired=False,
            )
        self._unit.pending_commands[key] = record
        return FormalProductionAgentPublicationCommandReservation(
            record=record,
            created=True,
            acquired=True,
        )

    def find_owned(
        self,
        *,
        command_id: str,
        actor_subject: str,
    ) -> FormalProductionAgentPublicationCommandRecord | None:
        records = (
            *self._unit.factory.state.formal_publication_commands.values(),
            *self._unit.pending_commands.values(),
        )
        return next(
            (
                record
                for record in records
                if record.receipt.command_id == command_id and record.actor_subject == actor_subject
            ),
            None,
        )

    def checkpoint_candidate(
        self,
        record: FormalProductionAgentPublicationCommandRecord,
        *,
        formal_candidate_sha256: str,
        knowledge_release_candidate_sha256: str,
    ) -> FormalProductionAgentPublicationCommandRecord:
        key = (record.actor_subject, record.idempotency_key)
        current = self._unit.pending_commands.get(key)
        if current is None:
            current = self._unit.factory.state.formal_publication_commands.get(key)
        assert current is not None
        assert current.receipt.state is FormalProductionAgentPublicationCommandState.IN_PROGRESS
        assert current.receipt.command_id == record.receipt.command_id
        assert current.execution_claim == record.execution_claim
        if current.candidate_checkpoint is not None:
            return current
        checkpointed = current.model_copy(
            update={
                "candidate_checkpoint": FormalProductionAgentPublicationCandidateCheckpoint(
                    formal_candidate_sha256=formal_candidate_sha256,
                    knowledge_release_candidate_sha256=(knowledge_release_candidate_sha256),
                    checkpointed_at=current.receipt.started_at,
                )
            }
        )
        self._unit.pending_commands[key] = checkpointed
        return checkpointed

    def complete(
        self,
        record: FormalProductionAgentPublicationCommandRecord,
    ) -> FormalProductionAgentPublicationCommandRecord:
        if self._unit.factory.state.command_failures:
            raise self._unit.factory.state.command_failures.pop(0)
        key = (record.actor_subject, record.idempotency_key)
        current = self._unit.pending_commands.get(key)
        if current is None:
            current = self._unit.factory.state.formal_publication_commands.get(key)
        assert current is not None
        assert current.receipt.command_id == record.receipt.command_id
        assert current.receipt.request_sha256 == record.receipt.request_sha256
        assert current.execution_claim == record.execution_claim
        assert current.candidate_checkpoint == record.candidate_checkpoint
        if current.receipt.state is not FormalProductionAgentPublicationCommandState.IN_PROGRESS:
            return current
        self._unit.pending_commands[key] = record
        return record


def _test_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class _FormalPublicationUnitOfWork:
    def __init__(self, factory: _FormalPublicationUnitOfWorkFactory) -> None:
        self.factory = factory
        self.agents = _FormalPublicationAgents(self)
        self.audit = _FormalPublicationAudits(self)
        self.formal_publication_commands = _FormalPublicationCommands(self)
        self.pending_publication: AgentPublicationRecord | None = None
        self.pending_active: ActiveAgentVersion | None = None
        self.pending_audits: list[AuditMetadataRecord] = []
        self.pending_commands: dict[
            tuple[str, str], FormalProductionAgentPublicationCommandRecord
        ] = {}
        self.committed = False

    def __enter__(self) -> _FormalPublicationUnitOfWork:
        self.factory.open_count += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        try:
            if exc_type is None and self.committed:
                state = self.factory.state
                if self.pending_publication is not None:
                    state.publications.append(self.pending_publication)
                    state.active = self.pending_active
                state.audits.extend(self.pending_audits)
                state.formal_publication_commands.update(self.pending_commands)
        finally:
            self.factory.open_count -= 1

    def commit(self) -> None:
        self.committed = True


class _FormalPublicationUnitOfWorkFactory:
    def __init__(self, state: _FormalPublicationState) -> None:
        self.state = state
        self.units: list[_FormalPublicationUnitOfWork] = []
        self.open_count = 0

    def __call__(self) -> _FormalPublicationUnitOfWork:
        unit = _FormalPublicationUnitOfWork(self)
        self.units.append(unit)
        return unit


def test_assembler_roots_candidate_in_exact_draft_revision_and_draft_release() -> None:
    record = AgentDraftRecord(draft=_draft(), revision=11)
    uow_factory = _UnitOfWorkFactory(record)
    assembler = FormalProductionAgentCandidateAssembler(
        unit_of_work_factory=uow_factory,
        knowledge_release_catalog=_Catalog(_catalog()),
        publication_configuration_projector=ProductionAgentPublicationConfigurationProjector(
            configuration_store=_ModelConnections(_model_connection())
        ),
    )

    assembled = assembler.assemble(
        agent_id=record.draft.agent_id,
        draft_id=record.draft.draft_id,
        draft_revision=record.revision,
        binding_profile=_binding_profile(),
    )

    assert assembled.agent_id == record.draft.agent_id
    assert assembled.draft_id == record.draft.draft_id
    assert assembled.draft_revision == 11
    assert assembled.contract_bundle == record.draft.contract_bundle
    assert assembled.knowledge_release_candidate == _candidate()
    assert assembled.knowledge_service_catalog_revision == "kss-catalog-42"
    assert len(assembled.resolved_knowledge_bindings.bindings) == 1
    binding = assembled.resolved_knowledge_bindings.bindings[0]
    assert binding.knowledge_base_release_id == _candidate().knowledge_base_release_id
    assert binding.binding_id == _binding_profile().binding_id
    assert binding.client_credential_ref == _binding_profile().client_credential_ref
    assert binding.admission_scorer_id == _binding_profile().admission_scorer_id
    assert binding.admission_scorer_revision == _binding_profile().admission_scorer_revision
    assert assembled.knowledge_release_candidate_sha256 == (
        knowledge_release_candidate_sha256(
            assembled.contract_bundle,
            assembled.resolved_knowledge_bindings,
        )
    )
    assert len(assembled.formal_candidate_sha256) == 64
    assert all(not unit.committed for unit in uow_factory.units)


def test_assembler_rejects_a_stale_draft_revision_before_reading_kss() -> None:
    record = AgentDraftRecord(draft=_draft(), revision=12)
    assembler = _assembler(
        uow_factory=_UnitOfWorkFactory(record),
        catalog=_UnavailableCatalog(),
    )

    with pytest.raises(FormalProductionAgentCandidateRejected) as raised:
        assembler.assemble(
            agent_id=record.draft.agent_id,
            draft_id=record.draft.draft_id,
            draft_revision=11,
            binding_profile=_binding_profile(),
        )

    assert raised.value.code == "formal_candidate_draft_revision_conflict"
    assert "private upstream failure" not in str(raised.value)


def test_assembler_rejects_a_missing_named_draft() -> None:
    assembler = _assembler(
        uow_factory=_UnitOfWorkFactory(None),
        catalog=_Catalog(_catalog()),
    )

    with pytest.raises(FormalProductionAgentCandidateRejected) as raised:
        assembler.assemble(
            agent_id="agent_management_insurance_specialist",
            draft_id="019ba001-1111-7000-8000-000000000701",
            draft_revision=11,
            binding_profile=_binding_profile(),
        )

    assert raised.value.code == "formal_candidate_draft_not_found"


def test_assembler_revalidates_the_full_release_tuple_as_queryable() -> None:
    record = AgentDraftRecord(draft=_draft(), revision=11)
    assembler = _assembler(
        uow_factory=_UnitOfWorkFactory(record),
        catalog=_Catalog(_catalog(release_state="deprecated")),
    )

    with pytest.raises(FormalProductionAgentCandidateRejected) as raised:
        assembler.assemble(
            agent_id=record.draft.agent_id,
            draft_id=record.draft.draft_id,
            draft_revision=record.revision,
            binding_profile=_binding_profile(),
        )

    assert raised.value.code == "formal_candidate_authoring_blocked"
    assert raised.value.blocker_codes == ("knowledge_release_not_queryable",)


def test_assembler_rejects_a_queryable_release_with_a_foreign_parent_tuple() -> None:
    record = AgentDraftRecord(draft=_draft(), revision=11)
    assembler = _assembler(
        uow_factory=_UnitOfWorkFactory(record),
        catalog=_Catalog(_catalog(release_base_version_id="foreign-base-version")),
    )

    with pytest.raises(FormalProductionAgentCandidateRejected) as raised:
        assembler.assemble(
            agent_id=record.draft.agent_id,
            draft_id=record.draft.draft_id,
            draft_revision=record.revision,
            binding_profile=_binding_profile(),
        )

    assert raised.value.code == "formal_candidate_authoring_blocked"
    assert raised.value.blocker_codes == ("knowledge_release_not_queryable",)


@pytest.mark.parametrize(
    "catalog_kind",
    ["raises", "unavailable", "unversioned"],
)
def test_assembler_rejects_an_unavailable_or_unversioned_live_catalog(
    catalog_kind: str,
) -> None:
    record = AgentDraftRecord(draft=_draft(), revision=11)
    catalogs: dict[str, FormalProductionKnowledgeReleaseCatalog] = {
        "raises": _UnavailableCatalog(),
        "unavailable": _Catalog(_catalog(readiness_state="unavailable")),
        "unversioned": _Catalog(_catalog(catalog_revision=None)),
    }
    assembler = _assembler(
        uow_factory=_UnitOfWorkFactory(record),
        catalog=catalogs[catalog_kind],
    )

    with pytest.raises(FormalProductionAgentCandidateRejected) as raised:
        assembler.assemble(
            agent_id=record.draft.agent_id,
            draft_id=record.draft.draft_id,
            draft_revision=record.revision,
            binding_profile=_binding_profile(),
        )

    assert raised.value.code == "formal_candidate_catalog_unavailable"
    assert "private upstream failure" not in str(raised.value)


def test_binding_profile_cannot_select_a_release_or_use_an_unversioned_secret() -> None:
    payload = _binding_profile().model_dump(mode="python")
    payload["knowledge_base_release_id"] = "environment-selected-release"

    with pytest.raises(ValidationError, match="knowledge_base_release_id"):
        ProductionKssBindingProfile.model_validate(payload)

    unversioned_payload = _binding_profile().model_dump(mode="python")
    unversioned_payload["client_credential_ref"] = ProductionSecretHandle(
        protocol_id="vault-kv-v2",
        handle_id="proofagent/kss/client",
        purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
        version_id=None,
    )
    with pytest.raises(ValidationError, match="versioned credential"):
        ProductionKssBindingProfile.model_validate(unversioned_payload)

    wrong_purpose_payload = _binding_profile().model_dump(mode="python")
    wrong_purpose_payload["client_credential_ref"] = ProductionSecretHandle(
        protocol_id="vault-kv-v2",
        handle_id="proofagent/kss/client",
        purpose=SecretPurpose.MODEL_CREDENTIAL,
        version_id="secret-version-7",
    )
    with pytest.raises(ValidationError, match="Knowledge credential"):
        ProductionKssBindingProfile.model_validate(wrong_purpose_payload)


def test_formal_candidate_digest_changes_when_the_exact_revision_changes() -> None:
    first_record = AgentDraftRecord(draft=_draft(), revision=11)
    second_record = AgentDraftRecord(draft=_draft(), revision=12)

    first = _assemble(first_record)
    second = _assemble(second_record)

    assert first.knowledge_release_candidate_sha256 == (second.knowledge_release_candidate_sha256)
    assert first.formal_candidate_sha256 != second.formal_candidate_sha256


def test_phase_f_preparer_binds_exact_formal_candidate_without_publishing() -> None:
    candidate = _assemble(AgentDraftRecord(draft=_draft(), revision=11))
    authority = _PhaseFAuthority()
    identities = iter(("phase-f-record-1", "provisional-version-1", "validation-run-1"))
    preparer = FormalProductionAgentPhaseFPreparer(
        phase_f_authority=authority,
        identifier_factory=lambda: next(identities),
        clock=lambda: datetime(2026, 8, 30, 12, 30, tzinfo=UTC),
    )

    preparation = preparer.prepare(
        candidate=candidate,
        evidence=_phase_f_evidence(),
        actor=AuditActorFacts(
            subject="release-operator",
            identity_provider="deployment-identity",
            session_id="release-session-05b",
        ),
    )

    assert preparation.candidate == candidate
    provisional = preparation.provisional_version
    assert provisional.agent_id == candidate.agent_id
    assert provisional.source_draft_id == candidate.draft_id
    assert provisional.source_draft_revision == candidate.draft_revision
    assert provisional.formal_candidate_sha256 == candidate.formal_candidate_sha256
    assert provisional.version_id == "provisional-version-1"
    assert provisional.validation_run_id == "validation-run-1"
    assert provisional.prepared_at == "2026-08-30T12:30:00Z"
    assert provisional.prepared_by == "release-operator"
    assert provisional.resolved_knowledge_bindings == candidate.resolved_knowledge_bindings
    assert provisional.workflow_stage_availability.available_stage_ids
    assert provisional.effective_workflow_stage_configuration.stage_ids
    assert (
        provisional.workflow_stage_configuration_source.source_type.value
        == "formal_production_candidate"
    )
    record = provisional.phase_f_record
    assert record.record_id == "phase-f-record-1"
    assert record.provisional_version_id == provisional.version_id
    assert record.validation_run_id == provisional.validation_run_id
    assert record.formal_candidate_sha256 == candidate.formal_candidate_sha256
    assert record.knowledge_release_candidate_sha256 == candidate.knowledge_release_candidate_sha256
    assert record.evidence == _phase_f_evidence()
    assert len(record.record_sha256) == 64
    assert authority.records == [record]


def test_reference_stager_registers_exact_release_for_provisional_version() -> None:
    candidate = _assemble(AgentDraftRecord(draft=_draft(), revision=11))
    preparation = _phase_f_preparer(_PhaseFAuthority()).prepare(
        candidate=candidate,
        evidence=_phase_f_evidence(),
        actor=_release_actor(),
    )
    registrar = _ReferenceRegistrar()

    staging = FormalProductionAgentReferenceStager(registrar=registrar).stage(
        preparation=preparation,
    )

    request, idempotency_key = registrar.calls[0]
    assert request.knowledge_space_id == candidate.knowledge_release_candidate.knowledge_space_id
    assert request.knowledge_base_id == candidate.knowledge_release_candidate.knowledge_base_id
    assert (
        request.knowledge_base_release_id
        == candidate.knowledge_release_candidate.knowledge_base_release_id
    )
    assert request.external_resource_kind == "published_agent_version"
    assert request.external_resource_id == preparation.provisional_version.version_id
    assert request.purpose == "execution_or_rollback"
    assert idempotency_key == "formal-agent-reference:provisional-version-1"
    assert staging.preparation == preparation
    assert staging.release_reference.release_reference_id == "release-reference-05c"
    assert staging.release_reference.state == "active"
    assert set(staging.model_dump(mode="json")) == {
        "schema_version",
        "preparation",
        "release_reference",
    }


@pytest.mark.parametrize(
    "tamper",
    ["candidate", "phase_f_record", "version_id", "validation_run_id"],
)
def test_reference_stager_rejects_tampered_preparation_before_registration(
    tamper: str,
) -> None:
    preparation = _phase_f_preparation()
    if tamper == "candidate":
        candidate = preparation.candidate.model_copy(update={"formal_candidate_sha256": "0" * 64})
        drifted = preparation.model_copy(update={"candidate": candidate})
    elif tamper == "phase_f_record":
        provisional = preparation.provisional_version
        record = provisional.phase_f_record.model_copy(update={"record_sha256": "0" * 64})
        drifted = preparation.model_copy(
            update={
                "provisional_version": provisional.model_copy(update={"phase_f_record": record})
            }
        )
    else:
        drifted_value = (
            "provisional-version-drift" if tamper == "version_id" else "validation-run-drift"
        )
        provisional = preparation.provisional_version.model_copy(update={tamper: drifted_value})
        drifted = preparation.model_copy(update={"provisional_version": provisional})
    registrar = _ReferenceRegistrar()

    with pytest.raises(FormalProductionAgentReferenceStagingRejected) as raised:
        FormalProductionAgentReferenceStager(registrar=registrar).stage(
            preparation=drifted,
        )

    assert raised.value.code == "reference_preparation_integrity_invalid"
    assert registrar.calls == []


def test_reference_stager_rejects_invalid_external_resource_as_preparation_drift() -> None:
    preparation = _phase_f_preparation()
    provisional = preparation.provisional_version.model_copy(update={"version_id": "invalid id"})
    invalid = preparation.model_copy(update={"provisional_version": provisional})
    registrar = _ReferenceRegistrar()

    with pytest.raises(FormalProductionAgentReferenceStagingRejected) as raised:
        FormalProductionAgentReferenceStager(registrar=registrar).stage(
            preparation=invalid,
        )

    assert raised.value.code == "reference_preparation_integrity_invalid"
    assert registrar.calls == []


def test_release_reference_request_rejects_unknown_release_selection_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ProductionAgentReleaseReferenceRequest(
            knowledge_space_id="space-insurance",
            knowledge_base_id="base-insurance",
            knowledge_base_release_id="release-insurance-v3",
            external_resource_id="provisional-version-1",
            latest_release_id="release-latest",
        )


def test_reference_stager_fails_closed_when_registration_is_unavailable() -> None:
    registrar = _ReferenceRegistrar(failure=RuntimeError("private KSS detail"))

    with pytest.raises(FormalProductionAgentReferenceStagingRejected) as raised:
        FormalProductionAgentReferenceStager(registrar=registrar).stage(
            preparation=_phase_f_preparation(),
        )

    assert raised.value.code == "reference_registration_unavailable"
    assert "private KSS detail" not in str(raised.value)
    assert len(registrar.calls) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("knowledge_space_id", "space-drift"),
        ("knowledge_base_id", "base-drift"),
        ("knowledge_base_release_id", "release-drift"),
        ("external_resource_kind", "agent_draft"),
        ("external_resource_id", "version-drift"),
        ("purpose", "active_only"),
        ("state", "deregistered"),
    ],
)
def test_reference_stager_rejects_drifted_registration_receipt(
    field: str,
    value: str,
) -> None:
    registrar = _ReferenceRegistrar(receipt_updates={field: value})

    with pytest.raises(FormalProductionAgentReferenceStagingRejected) as raised:
        FormalProductionAgentReferenceStager(registrar=registrar).stage(
            preparation=_phase_f_preparation(),
        )

    assert raised.value.code == "reference_registration_integrity_invalid"
    assert len(registrar.references) == 1


def test_reference_stager_replays_the_same_idempotent_active_reference() -> None:
    preparation = _phase_f_preparation()
    registrar = _ReferenceRegistrar()
    stager = FormalProductionAgentReferenceStager(registrar=registrar)

    first = stager.stage(preparation=preparation)
    second = stager.stage(preparation=preparation)

    assert first == second
    assert len(registrar.calls) == 2
    assert {key for _, key in registrar.calls} == {"formal-agent-reference:provisional-version-1"}
    assert len(registrar.references) == 1


def test_query_grant_staging_derives_the_exact_candidate_release_before_online_smoke() -> None:
    reference_staging = _reference_staging(_ReferenceRegistrar())
    provisioner = _QueryGrantProvisioner()

    staging = FormalProductionAgentQueryGrantStager(
        provisioner=provisioner,
    ).stage(reference_staging=reference_staging)

    candidate_release = reference_staging.preparation.candidate.knowledge_release_candidate
    assert provisioner.calls == [
        ProductionAgentKnowledgeQueryGrantRequest(
            knowledge_base_release_id=candidate_release.knowledge_base_release_id,
        )
    ]
    assert isinstance(staging, FormalProductionAgentQueryGrantStaging)
    assert staging.reference_staging == reference_staging
    assert staging.query_grant.knowledge_base_release_id == (
        candidate_release.knowledge_base_release_id
    )
    assert staging.query_grant.knowledge_space_id == candidate_release.knowledge_space_id
    assert set(staging.model_dump(mode="json")) == {
        "schema_version",
        "reference_staging",
        "query_grant",
    }
    assert "published_at" not in staging.model_dump_json()
    assert "activated_at" not in staging.model_dump_json()


def test_query_grant_staging_rejects_invalid_reference_before_provisioning() -> None:
    provisioner = _QueryGrantProvisioner()

    with pytest.raises(FormalProductionAgentQueryGrantStagingRejected) as raised:
        FormalProductionAgentQueryGrantStager(provisioner=provisioner).stage(
            reference_staging=_phase_f_preparation(),
        )

    assert raised.value.code == "query_grant_reference_staging_integrity_invalid"
    assert provisioner.calls == []


def test_query_grant_staging_fails_closed_when_provisioning_is_unavailable() -> None:
    provisioner = _QueryGrantProvisioner(failure=RuntimeError("private operator transport detail"))

    with pytest.raises(FormalProductionAgentQueryGrantStagingRejected) as raised:
        FormalProductionAgentQueryGrantStager(provisioner=provisioner).stage(
            reference_staging=_reference_staging(_ReferenceRegistrar()),
        )

    assert raised.value.code == "query_grant_provisioning_unavailable"
    assert "private operator transport detail" not in str(raised.value)
    assert len(provisioner.calls) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("knowledge_base_release_id", "release-drift"),
        ("knowledge_space_id", "space-drift"),
        ("active", False),
    ],
)
def test_query_grant_staging_rejects_drifted_or_inactive_receipt(
    field: str,
    value: object,
) -> None:
    provisioner = _QueryGrantProvisioner(receipt_updates={field: value})

    with pytest.raises(FormalProductionAgentQueryGrantStagingRejected) as raised:
        FormalProductionAgentQueryGrantStager(provisioner=provisioner).stage(
            reference_staging=_reference_staging(_ReferenceRegistrar()),
        )

    assert raised.value.code == "query_grant_integrity_invalid"
    assert len(provisioner.calls) == 1


def test_online_smoke_requires_query_grant_staging_as_its_explicit_input() -> None:
    reference_staging = _reference_staging(_ReferenceRegistrar())
    grant_staging = FormalProductionAgentQueryGrantStager(
        provisioner=_QueryGrantProvisioner(),
    ).stage(reference_staging=reference_staging)
    validator = _OnlineSmokeValidator()

    qualification = FormalProductionAgentOnlineSmokeService(
        online_smoke_validator=validator,
    ).qualify(
        query_grant_staging=grant_staging,
        smoke_question="等待期如何解释？",
    )

    assert qualification.query_grant_staging == grant_staging
    assert qualification.request.knowledge_base_release_id == (
        grant_staging.query_grant.knowledge_base_release_id
    )


def test_online_smoke_qualifies_the_exact_registered_staging_without_publication() -> None:
    registrar = _ReferenceRegistrar()
    staging = _query_grant_staging(_reference_staging(registrar))
    validator = _OnlineSmokeValidator()

    qualification = FormalProductionAgentOnlineSmokeService(
        online_smoke_validator=validator,
    ).qualify(
        query_grant_staging=staging,
        smoke_question="等待期如何解释？",
    )

    assert len(validator.calls) == 1
    request = validator.calls[0]
    preparation = staging.reference_staging.preparation
    candidate = preparation.candidate
    provisional = preparation.provisional_version
    release = candidate.knowledge_release_candidate
    assert request.agent_id == candidate.agent_id
    assert request.provisional_version_id == provisional.version_id
    assert request.validation_run_id == provisional.validation_run_id
    assert request.formal_candidate_sha256 == candidate.formal_candidate_sha256
    assert request.knowledge_release_candidate_sha256 == (
        candidate.knowledge_release_candidate_sha256
    )
    assert request.knowledge_space_id == release.knowledge_space_id
    assert request.knowledge_base_id == release.knowledge_base_id
    assert request.knowledge_base_release_id == release.knowledge_base_release_id
    assert request.release_reference_id == (
        staging.reference_staging.release_reference.release_reference_id
    )
    assert request.smoke_question == "等待期如何解释？"
    assert qualification.query_grant_staging == staging
    assert qualification.request == request
    assert qualification.result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert qualification.result.accepted_citation_count == 2
    assert set(qualification.model_dump(mode="json")) == {
        "schema_version",
        "query_grant_staging",
        "request",
        "result",
    }
    assert len(registrar.references) == 1
    assert "published_at" not in qualification.model_dump_json()
    assert "activated_at" not in qualification.model_dump_json()


def test_online_smoke_requires_registered_staging_before_calling_validator() -> None:
    validator = _OnlineSmokeValidator()

    with pytest.raises(FormalProductionAgentOnlineSmokeRejected) as raised:
        FormalProductionAgentOnlineSmokeService(
            online_smoke_validator=validator,
        ).qualify(
            query_grant_staging=_phase_f_preparation(),
            smoke_question="等待期如何解释？",
        )

    assert raised.value.code == "online_smoke_query_grant_staging_integrity_invalid"
    assert validator.calls == []


@pytest.mark.parametrize(
    ("result_updates", "expected_code"),
    [
        (
            {"outcome": ReceiptOutcome.REFUSED_NO_EVIDENCE},
            "online_smoke_failed",
        ),
        ({"accepted_citation_count": 0}, "online_smoke_failed"),
        ({"agent_id": "agent-drift"}, "online_smoke_integrity_invalid"),
        ({"provisional_version_id": "version-drift"}, "online_smoke_integrity_invalid"),
        ({"validation_run_id": "run-drift"}, "online_smoke_integrity_invalid"),
        ({"release_reference_id": "reference-drift"}, "online_smoke_integrity_invalid"),
    ],
)
def test_online_smoke_failure_or_identity_drift_keeps_registered_reference(
    result_updates: dict[str, object],
    expected_code: str,
) -> None:
    registrar = _ReferenceRegistrar()
    staging = _query_grant_staging(_reference_staging(registrar))
    validator = _OnlineSmokeValidator(result_updates=result_updates)

    with pytest.raises(FormalProductionAgentOnlineSmokeRejected) as raised:
        FormalProductionAgentOnlineSmokeService(
            online_smoke_validator=validator,
        ).qualify(
            query_grant_staging=staging,
            smoke_question="等待期如何解释？",
        )

    assert raised.value.code == expected_code
    assert len(registrar.references) == 1
    assert next(iter(registrar.references.values())) == (
        staging.reference_staging.release_reference
    )


def test_online_smoke_rejects_non_active_reference_before_calling_validator() -> None:
    registrar = _ReferenceRegistrar()
    staging = _query_grant_staging(_reference_staging(registrar))
    reference_staging = staging.reference_staging
    inactive_reference = reference_staging.release_reference.model_copy(
        update={"state": "deregistered"}
    )
    inactive_reference_staging = reference_staging.model_copy(
        update={"release_reference": inactive_reference}
    )
    inactive_staging = staging.model_copy(update={"reference_staging": inactive_reference_staging})
    validator = _OnlineSmokeValidator()

    with pytest.raises(FormalProductionAgentOnlineSmokeRejected) as raised:
        FormalProductionAgentOnlineSmokeService(
            online_smoke_validator=validator,
        ).qualify(
            query_grant_staging=inactive_staging,
            smoke_question="等待期如何解释？",
        )

    assert raised.value.code == "online_smoke_query_grant_staging_integrity_invalid"
    assert validator.calls == []
    assert len(registrar.references) == 1


def test_online_smoke_rejects_uncertain_or_non_distinct_evidence_without_detail_leak() -> None:
    registrar = _ReferenceRegistrar()
    staging = _query_grant_staging(_reference_staging(registrar))
    unavailable = _OnlineSmokeValidator(failure=RuntimeError("private runner detail"))

    with pytest.raises(FormalProductionAgentOnlineSmokeRejected) as raised:
        FormalProductionAgentOnlineSmokeService(
            online_smoke_validator=unavailable,
        ).qualify(
            query_grant_staging=staging,
            smoke_question="等待期如何解释？",
        )

    assert raised.value.code == "online_smoke_unavailable"
    assert "private runner detail" not in str(raised.value)
    assert len(registrar.references) == 1

    shared_evidence = _artifact("shared-online-smoke", "8")
    non_distinct = _OnlineSmokeValidator(
        result_updates={"trace_ref": shared_evidence, "receipt_ref": shared_evidence}
    )
    with pytest.raises(FormalProductionAgentOnlineSmokeRejected) as non_distinct_raised:
        FormalProductionAgentOnlineSmokeService(
            online_smoke_validator=non_distinct,
        ).qualify(
            query_grant_staging=staging,
            smoke_question="等待期如何解释？",
        )

    assert non_distinct_raised.value.code == "online_smoke_integrity_invalid"
    assert len(registrar.references) == 1


def test_online_smoke_contracts_reject_unknown_fields_and_blank_question() -> None:
    staging = _query_grant_staging(_reference_staging(_ReferenceRegistrar()))
    service = FormalProductionAgentOnlineSmokeService(
        online_smoke_validator=_OnlineSmokeValidator(),
    )

    with pytest.raises(FormalProductionAgentOnlineSmokeRejected) as raised:
        service.qualify(query_grant_staging=staging, smoke_question="   ")
    assert raised.value.code == "online_smoke_question_invalid"

    request = _online_smoke_request(staging)
    with pytest.raises(ValidationError, match="extra_forbidden"):
        FormalProductionAgentOnlineSmokeRequest.model_validate(
            {**request.model_dump(mode="python"), "latest_release_id": "release-latest"}
        )

    result = _OnlineSmokeValidator().validate_online_smoke(
        request,
        query_grant_staging=staging,
    )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        FormalProductionAgentOnlineSmokeQualification.model_validate(
            {
                "query_grant_staging": staging,
                "request": request,
                "result": result,
                "published_version_id": "must-not-exist",
            }
        )


def test_formal_online_smoke_runner_executes_exact_governed_validation_and_retains_artifacts(
    tmp_path: Path,
) -> None:
    staging = _query_grant_staging(_real_reference_staging())
    request = _online_smoke_request(staging)
    artifact_store = _ExactArtifactStore()
    execute_calls: list[dict[str, object]] = []

    def execute(**kwargs: object) -> SimpleNamespace:
        execute_calls.append(kwargs)
        assert kwargs["run_id"] == request.validation_run_id
        assert kwargs["run_purpose"] is RunPurpose.VALIDATION
        assert kwargs["institution_authorization"] == InstitutionAuthorizationContext(
            institutions=("branch-shanghai",)
        )
        agent = kwargs["published_agent"]
        assert agent.agent_id == request.agent_id
        assert agent.agent_version_id == request.provisional_version_id
        assert agent.validation_run_id == request.validation_run_id
        assert agent.resolved_knowledge_bindings == (
            staging.reference_staging.preparation.provisional_version.resolved_knowledge_bindings
        )
        assert agent.runtime_facts.agent_version_id == request.provisional_version_id
        assert agent.manifest_path.read_text(encoding="utf-8") == (
            staging.reference_staging.preparation.provisional_version.contract_bundle.agent_yaml
        )
        dependencies = kwargs["dependencies"]
        trace = dependencies.runs_dir.parent / "trace.jsonl"
        receipt = dependencies.runs_dir.parent / "receipt.md"
        trace.write_bytes(b'{"event_type":"final_output"}\n')
        receipt.write_bytes(b"# governed formal smoke receipt\n")
        return SimpleNamespace(
            result=SimpleNamespace(trace_path=trace, receipt_path=receipt),
            detail=SimpleNamespace(
                outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                evidence_chunks=(
                    SimpleNamespace(
                        status="accepted",
                        citation="knowledge://insurance/rules/r1#p1",
                    ),
                    SimpleNamespace(
                        status="accepted",
                        citation="knowledge://insurance/rules/r2#p2",
                    ),
                    SimpleNamespace(status="rejected", citation="private://ignored"),
                ),
            ),
        )

    runner = FormalProductionAgentOnlineSmokeRunner(
        configuration_store=object(),
        knowledge_candidate_runtime=object(),
        guarded_http_client=object(),
        secret_provider=object(),
        model_credential_resolver=object(),
        artifact_store=artifact_store,
        work_root=tmp_path / "formal-smoke-work",
        institution_authorization=InstitutionAuthorizationContext(
            institutions=("branch-shanghai",)
        ),
        execute=execute,
    )

    result = runner.validate_online_smoke(request, query_grant_staging=staging)

    assert result.agent_id == request.agent_id
    assert result.provisional_version_id == request.provisional_version_id
    assert result.validation_run_id == request.validation_run_id
    assert result.release_reference_id == request.release_reference_id
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.accepted_citation_count == 2
    assert artifact_store.get_exact(result.trace_ref).endswith(b"\n")
    assert artifact_store.get_exact(result.receipt_ref).startswith(b"# governed")
    assert len(execute_calls) == 1
    assert list((tmp_path / "formal-smoke-work").iterdir()) == []


def test_formal_candidate_external_smoke_runs_exact_candidate_without_phase_f(
    tmp_path: Path,
) -> None:
    candidate = _real_reference_staging().preparation.candidate
    artifact_store = _ExactArtifactStore()
    execute_calls: list[dict[str, object]] = []

    def execute(**kwargs: object) -> SimpleNamespace:
        execute_calls.append(kwargs)
        assert kwargs["run_id"] == "formal-candidate-probe-run-1"
        assert kwargs["run_purpose"] is RunPurpose.VALIDATION
        agent = kwargs["published_agent"]
        assert agent.agent_id == candidate.agent_id
        assert agent.source_draft_id == candidate.draft_id
        assert agent.agent_version_id == (
            f"formal-candidate-probe-{candidate.formal_candidate_sha256}"
        )
        assert agent.validation_run_id == "formal-candidate-probe-run-1"
        assert agent.resolved_knowledge_bindings == candidate.resolved_knowledge_bindings
        assert agent.runtime_facts.agent_version_id == agent.agent_version_id
        assert agent.manifest_path.read_text(encoding="utf-8") == (
            candidate.contract_bundle.agent_yaml
        )
        dependencies = kwargs["dependencies"]
        trace = dependencies.runs_dir.parent / "trace.jsonl"
        receipt = dependencies.runs_dir.parent / "receipt.md"
        trace.write_bytes(b'{"event_type":"final_output"}\n')
        receipt.write_bytes(b"# governed candidate dependency probe\n")
        return SimpleNamespace(
            result=SimpleNamespace(trace_path=trace, receipt_path=receipt),
            detail=SimpleNamespace(
                outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                evidence_chunks=(
                    SimpleNamespace(
                        status="accepted",
                        citation="knowledge://insurance/rules/r1#p1",
                    ),
                ),
            ),
        )

    runner = FormalProductionAgentCandidateExternalSmokeRunner(
        configuration_store=object(),
        knowledge_candidate_runtime=object(),
        guarded_http_client=object(),
        secret_provider=object(),
        model_credential_resolver=object(),
        artifact_store=artifact_store,
        work_root=tmp_path / "candidate-probe-work",
        institution_authorization=InstitutionAuthorizationContext(
            institutions=("branch-shanghai",)
        ),
        identifier_factory=lambda: "formal-candidate-probe-run-1",
        execute=execute,
    )

    result = runner.validate_candidate_external_smoke(
        candidate,
        question="航班延误保险如何理赔？",
    )

    assert result.agent_id == candidate.agent_id
    assert result.draft_id == candidate.draft_id
    assert result.draft_revision == candidate.draft_revision
    assert result.formal_candidate_sha256 == candidate.formal_candidate_sha256
    assert result.knowledge_release_candidate_sha256 == (
        candidate.knowledge_release_candidate_sha256
    )
    assert result.knowledge_base_release_id == (
        candidate.knowledge_release_candidate.knowledge_base_release_id
    )
    assert result.validation_run_id == "formal-candidate-probe-run-1"
    assert result.model_connection_ids == ("model_production_primary",)
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.accepted_citation_count == 1
    assert artifact_store.get_exact(result.trace_ref).endswith(b"\n")
    assert artifact_store.get_exact(result.receipt_ref).startswith(b"# governed")
    assert len(execute_calls) == 1
    assert list((tmp_path / "candidate-probe-work").iterdir()) == []


def test_formal_candidate_external_smoke_fails_closed_without_cited_evidence(
    tmp_path: Path,
) -> None:
    candidate = _real_reference_staging().preparation.candidate
    artifact_store = _ExactArtifactStore()

    def execute(**kwargs: object) -> SimpleNamespace:
        dependencies = kwargs["dependencies"]
        trace = dependencies.runs_dir.parent / "trace.jsonl"
        receipt = dependencies.runs_dir.parent / "receipt.md"
        trace.write_bytes(b'{"event_type":"refusal"}\n')
        receipt.write_bytes(b"# refused candidate dependency probe\n")
        return SimpleNamespace(
            result=SimpleNamespace(trace_path=trace, receipt_path=receipt),
            detail=SimpleNamespace(
                outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
                evidence_chunks=(),
            ),
        )

    runner = FormalProductionAgentCandidateExternalSmokeRunner(
        configuration_store=object(),
        knowledge_candidate_runtime=object(),
        guarded_http_client=object(),
        secret_provider=object(),
        model_credential_resolver=object(),
        artifact_store=artifact_store,
        work_root=tmp_path / "candidate-probe-work",
        institution_authorization=InstitutionAuthorizationContext(
            institutions=("branch-shanghai",)
        ),
        identifier_factory=lambda: "formal-candidate-probe-run-2",
        execute=execute,
    )

    with pytest.raises(ProductionAgentValidationError) as raised:
        runner.validate_candidate_external_smoke(
            candidate,
            question="航班延误保险如何理赔？",
        )

    assert getattr(raised.value, "code", None) == (
        "formal_candidate_external_smoke_evidence_admission_failed"
    )
    assert artifact_store.contents == {}
    assert list((tmp_path / "candidate-probe-work").iterdir()) == []


def test_formal_candidate_external_smoke_exposes_only_allowlisted_admission_reason(
    tmp_path: Path,
) -> None:
    candidate = _real_reference_staging().preparation.candidate
    secret_sentinel = "private-admission-metadata-must-not-appear"

    def execute(**kwargs: object) -> SimpleNamespace:
        dependencies = kwargs["dependencies"]
        trace = dependencies.runs_dir.parent / "trace.jsonl"
        receipt = dependencies.runs_dir.parent / "receipt.md"
        trace.write_bytes(b'{"event_type":"evidence_evaluation"}\n')
        receipt.write_bytes(b"# governed refusal\n")
        return SimpleNamespace(
            result=SimpleNamespace(trace_path=trace, receipt_path=receipt),
            detail=SimpleNamespace(
                outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
                evidence_chunks=(
                    SimpleNamespace(
                        status="rejected",
                        citation="knowledge://insurance/rules/r1#p1",
                        admission_score=0.24,
                    ),
                ),
                trace_events=(
                    {
                        "event_type": "evidence_evaluation",
                        "payload": {
                            "metadata": {
                                "no_evidence_reason_code": (
                                    "knowledge_candidate_threshold_not_met"
                                ),
                                "private_detail": secret_sentinel,
                            }
                        },
                    },
                ),
            ),
        )

    runner = _formal_candidate_external_runner(
        tmp_path=tmp_path,
        artifact_store=_ExactArtifactStore(),
        execute=execute,
        run_id="formal-candidate-probe-admission-reason",
    )

    with pytest.raises(FormalCandidateExternalSmokeDiagnosticError) as raised:
        runner.validate_candidate_external_smoke(
            candidate,
            question="航班延误保险如何理赔？",
        )

    assert raised.value.code == ("formal_candidate_external_smoke_evidence_admission_failed")
    assert getattr(raised.value, "reason_code", None) == ("evidence_admission_threshold_not_met")
    assert secret_sentinel not in str(raised.value)


def test_formal_candidate_external_smoke_preserves_structured_scorer_reason(
    tmp_path: Path,
) -> None:
    candidate = _real_reference_staging().preparation.candidate
    secret_sentinel = "private-scorer-boundary-detail-must-not-appear"

    def execute(**kwargs: object) -> SimpleNamespace:
        del kwargs
        raise KnowledgeCandidateAdmissionError(
            KnowledgeCandidateAdmissionFailureReason.SCORER_UNAVAILABLE,
            secret_sentinel,
            secret_sentinel,
        )

    runner = _formal_candidate_external_runner(
        tmp_path=tmp_path,
        artifact_store=_ExactArtifactStore(),
        execute=execute,
        run_id="formal-candidate-probe-scorer-unavailable",
    )

    with pytest.raises(FormalCandidateExternalSmokeDiagnosticError) as raised:
        runner.validate_candidate_external_smoke(
            candidate,
            question="航班延误保险如何理赔？",
        )

    assert raised.value.code == ("formal_candidate_external_smoke_evidence_admission_failed")
    assert raised.value.reason_code == "evidence_admission_scorer_unavailable"
    assert secret_sentinel not in str(raised.value)


@pytest.mark.parametrize(
    ("stage_code", "reason_code"),
    (
        (
            "formal_candidate_external_smoke_evidence_admission_failed",
            "private-unapproved-admission-reason",
        ),
        (
            "formal_candidate_external_smoke_model_failed",
            "evidence_admission_scorer_unavailable",
        ),
    ),
)
def test_formal_candidate_external_smoke_rejects_unapproved_reason_projection(
    stage_code: str,
    reason_code: str,
) -> None:
    with pytest.raises(ValueError, match="admission reason code is invalid"):
        FormalCandidateExternalSmokeDiagnosticError(
            stage_code,
            reason_code=reason_code,
        )


def test_formal_candidate_external_smoke_classifies_kss_failure_without_detail(
    tmp_path: Path,
) -> None:
    candidate = _real_reference_staging().preparation.candidate
    secret_sentinel = "private-kss-response-must-not-appear"

    def execute(**kwargs: object) -> SimpleNamespace:
        del kwargs
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            secret_sentinel,
            "private-kss-fix-must-not-appear",
        )

    runner = FormalProductionAgentCandidateExternalSmokeRunner(
        configuration_store=object(),
        knowledge_candidate_runtime=object(),
        guarded_http_client=object(),
        secret_provider=object(),
        model_credential_resolver=object(),
        artifact_store=_ExactArtifactStore(),
        work_root=tmp_path / "candidate-probe-work",
        institution_authorization=InstitutionAuthorizationContext(
            institutions=("branch-shanghai",)
        ),
        identifier_factory=lambda: "formal-candidate-probe-run-kss-failure",
        execute=execute,
    )

    with pytest.raises(ProductionAgentValidationError) as raised:
        runner.validate_candidate_external_smoke(
            candidate,
            question="航班延误保险如何理赔？",
        )

    assert getattr(raised.value, "code", None) == ("formal_candidate_external_smoke_kss_failed")
    assert secret_sentinel not in str(raised.value)
    assert list((tmp_path / "candidate-probe-work").iterdir()) == []


@pytest.mark.parametrize(
    ("source_code", "expected_code"),
    (
        (
            "PA_KNOWLEDGE_001",
            "formal_candidate_external_smoke_evidence_admission_failed",
        ),
        ("PA_MODEL_002", "formal_candidate_external_smoke_model_failed"),
        (
            "PA_MODEL_CONNECTION_001",
            "formal_candidate_external_smoke_model_failed",
        ),
    ),
)
def test_formal_candidate_external_smoke_classifies_structured_execution_failure(
    tmp_path: Path,
    source_code: str,
    expected_code: str,
) -> None:
    candidate = _real_reference_staging().preparation.candidate
    secret_sentinel = f"private-{source_code}-detail-must-not-appear"

    def execute(**kwargs: object) -> SimpleNamespace:
        del kwargs
        raise ProofAgentError(source_code, secret_sentinel, secret_sentinel)

    runner = _formal_candidate_external_runner(
        tmp_path=tmp_path,
        artifact_store=_ExactArtifactStore(),
        execute=execute,
        run_id=f"formal-candidate-probe-{source_code.casefold()}",
    )

    with pytest.raises(ProductionAgentValidationError) as raised:
        runner.validate_candidate_external_smoke(
            candidate,
            question="航班延误保险如何理赔？",
        )

    assert getattr(raised.value, "code", None) == expected_code
    assert getattr(raised.value, "reason_code", None) is None
    assert secret_sentinel not in str(raised.value)


@pytest.mark.parametrize(
    ("outcome", "evidence_chunks", "trace_events", "expected_code"),
    (
        (
            ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            (SimpleNamespace(status="accepted", citation="   "),),
            (),
            "formal_candidate_external_smoke_citation_validation_failed",
        ),
        (
            ReceiptOutcome.REFUSED_NO_EVIDENCE,
            (
                SimpleNamespace(
                    status="accepted",
                    citation="knowledge://insurance/rules/r1#p1",
                ),
            ),
            (
                {
                    "event_type": "final_answer_validation_failed",
                    "payload": {"error_code": "citation_binding_failed"},
                },
            ),
            "formal_candidate_external_smoke_citation_validation_failed",
        ),
        (
            ReceiptOutcome.REFUSED_NO_EVIDENCE,
            (
                SimpleNamespace(
                    status="accepted",
                    citation="knowledge://insurance/rules/r1#p1",
                ),
            ),
            (
                {
                    "event_type": "final_answer_validation_failed",
                    "payload": {"error_code": "schema_failed"},
                },
            ),
            "formal_candidate_external_smoke_model_failed",
        ),
    ),
)
def test_formal_candidate_external_smoke_classifies_trace_safe_run_failure(
    tmp_path: Path,
    outcome: ReceiptOutcome,
    evidence_chunks: tuple[SimpleNamespace, ...],
    trace_events: tuple[dict[str, object], ...],
    expected_code: str,
) -> None:
    candidate = _real_reference_staging().preparation.candidate

    def execute(**kwargs: object) -> SimpleNamespace:
        dependencies = kwargs["dependencies"]
        trace = dependencies.runs_dir.parent / "trace.jsonl"
        receipt = dependencies.runs_dir.parent / "receipt.md"
        trace.write_bytes(b'{"event_type":"bounded_failure"}\n')
        receipt.write_bytes(b"# bounded candidate dependency probe\n")
        return SimpleNamespace(
            result=SimpleNamespace(trace_path=trace, receipt_path=receipt),
            detail=SimpleNamespace(
                outcome=outcome,
                evidence_chunks=evidence_chunks,
                trace_events=trace_events,
            ),
        )

    runner = _formal_candidate_external_runner(
        tmp_path=tmp_path,
        artifact_store=_ExactArtifactStore(),
        execute=execute,
        run_id="formal-candidate-probe-trace-safe-failure",
    )

    with pytest.raises(ProductionAgentValidationError) as raised:
        runner.validate_candidate_external_smoke(
            candidate,
            question="航班延误保险如何理赔？",
        )

    assert getattr(raised.value, "code", None) == expected_code


def test_formal_candidate_external_smoke_classifies_artifact_retention_failure(
    tmp_path: Path,
) -> None:
    candidate = _real_reference_staging().preparation.candidate
    artifact_store = _ExactArtifactStore(readback_override=b"private-corrupted-bytes")

    def execute(**kwargs: object) -> SimpleNamespace:
        dependencies = kwargs["dependencies"]
        trace = dependencies.runs_dir.parent / "trace.jsonl"
        receipt = dependencies.runs_dir.parent / "receipt.md"
        trace.write_bytes(b'{"event_type":"final_output"}\n')
        receipt.write_bytes(b"# governed candidate dependency probe\n")
        return SimpleNamespace(
            result=SimpleNamespace(trace_path=trace, receipt_path=receipt),
            detail=SimpleNamespace(
                outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                evidence_chunks=(
                    SimpleNamespace(
                        status="accepted",
                        citation="knowledge://insurance/rules/r1#p1",
                    ),
                ),
                trace_events=(),
            ),
        )

    runner = _formal_candidate_external_runner(
        tmp_path=tmp_path,
        artifact_store=artifact_store,
        execute=execute,
        run_id="formal-candidate-probe-artifact-retention-failure",
    )

    with pytest.raises(ProductionAgentValidationError) as raised:
        runner.validate_candidate_external_smoke(
            candidate,
            question="航班延误保险如何理赔？",
        )

    assert getattr(raised.value, "code", None) == (
        "formal_candidate_external_smoke_artifact_retention_failed"
    )


def test_formal_candidate_external_smoke_classifies_missing_source_artifact(
    tmp_path: Path,
) -> None:
    candidate = _real_reference_staging().preparation.candidate

    def execute(**kwargs: object) -> SimpleNamespace:
        dependencies = kwargs["dependencies"]
        root = dependencies.runs_dir.parent
        return SimpleNamespace(
            result=SimpleNamespace(
                trace_path=root / "missing-trace.jsonl",
                receipt_path=root / "missing-receipt.md",
            ),
            detail=SimpleNamespace(
                outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                evidence_chunks=(
                    SimpleNamespace(
                        status="accepted",
                        citation="knowledge://insurance/rules/r1#p1",
                    ),
                ),
                trace_events=(),
            ),
        )

    runner = _formal_candidate_external_runner(
        tmp_path=tmp_path,
        artifact_store=_ExactArtifactStore(),
        execute=execute,
        run_id="formal-candidate-probe-source-artifact-failure",
    )

    with pytest.raises(ProductionAgentValidationError) as raised:
        runner.validate_candidate_external_smoke(
            candidate,
            question="航班延误保险如何理赔？",
        )

    assert getattr(raised.value, "code", None) == (
        "formal_candidate_external_smoke_artifact_retention_failed"
    )


def test_formal_candidate_external_smoke_does_not_guess_ambiguous_failure_stage(
    tmp_path: Path,
) -> None:
    candidate = _real_reference_staging().preparation.candidate

    def execute(**kwargs: object) -> SimpleNamespace:
        dependencies = kwargs["dependencies"]
        trace = dependencies.runs_dir.parent / "trace.jsonl"
        receipt = dependencies.runs_dir.parent / "receipt.md"
        trace.write_bytes(b'{"event_type":"refusal"}\n')
        receipt.write_bytes(b"# governed candidate dependency probe refusal\n")
        return SimpleNamespace(
            result=SimpleNamespace(trace_path=trace, receipt_path=receipt),
            detail=SimpleNamespace(
                outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
                evidence_chunks=(
                    SimpleNamespace(
                        status="accepted",
                        citation="knowledge://insurance/rules/r1#p1",
                    ),
                ),
                trace_events=(),
            ),
        )

    runner = _formal_candidate_external_runner(
        tmp_path=tmp_path,
        artifact_store=_ExactArtifactStore(),
        execute=execute,
        run_id="formal-candidate-probe-ambiguous-failure",
    )

    with pytest.raises(ProductionAgentValidationError) as raised:
        runner.validate_candidate_external_smoke(
            candidate,
            question="航班延误保险如何理赔？",
        )

    assert not isinstance(raised.value, FormalCandidateExternalSmokeDiagnosticError)
    assert getattr(raised.value, "code", None) is None


def test_formal_online_smoke_runner_counts_only_cited_accepted_evidence(
    tmp_path: Path,
) -> None:
    staging = _query_grant_staging(_real_reference_staging())
    artifact_store = _ExactArtifactStore()

    def execute(**kwargs: object) -> SimpleNamespace:
        dependencies = kwargs["dependencies"]
        trace = dependencies.runs_dir.parent / "trace.jsonl"
        receipt = dependencies.runs_dir.parent / "receipt.md"
        trace.write_bytes(b'{"event_type":"governed_refusal"}\n')
        receipt.write_bytes(b"# governed refusal receipt\n")
        return SimpleNamespace(
            result=SimpleNamespace(trace_path=trace, receipt_path=receipt),
            detail=SimpleNamespace(
                outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                evidence_chunks=(
                    SimpleNamespace(status="accepted", citation="   "),
                    SimpleNamespace(status="rejected", citation="knowledge://ignored"),
                ),
            ),
        )

    service = FormalProductionAgentOnlineSmokeService(
        online_smoke_validator=_formal_online_runner(
            tmp_path=tmp_path,
            artifact_store=artifact_store,
            execute=execute,
        )
    )

    with pytest.raises(FormalProductionAgentOnlineSmokeRejected) as raised:
        service.qualify(
            query_grant_staging=staging,
            smoke_question="等待期如何解释？",
        )

    assert raised.value.code == "online_smoke_failed"
    assert len(artifact_store.contents) == 2
    assert staging.reference_staging.release_reference.state == "active"
    assert list((tmp_path / "formal-smoke-work").iterdir()) == []


def test_formal_online_smoke_runner_rejects_request_staging_drift_before_execution(
    tmp_path: Path,
) -> None:
    staging = _query_grant_staging(_real_reference_staging())
    request = _online_smoke_request(staging).model_copy(
        update={"knowledge_base_release_id": "release-drift"}
    )
    execute_calls: list[dict[str, object]] = []
    runner = _formal_online_runner(
        tmp_path=tmp_path,
        artifact_store=_ExactArtifactStore(),
        execute=lambda **kwargs: execute_calls.append(kwargs),
    )

    with pytest.raises(ProductionAgentValidationError, match="integrity"):
        runner.validate_online_smoke(request, query_grant_staging=staging)

    assert execute_calls == []


def test_formal_online_smoke_runner_readback_failure_is_stably_hidden(
    tmp_path: Path,
) -> None:
    staging = _query_grant_staging(_real_reference_staging())
    artifact_store = _ExactArtifactStore(readback_override=b"corrupted private bytes")

    def execute(**kwargs: object) -> SimpleNamespace:
        dependencies = kwargs["dependencies"]
        trace = dependencies.runs_dir.parent / "trace.jsonl"
        receipt = dependencies.runs_dir.parent / "receipt.md"
        trace.write_bytes(b'{"event_type":"final_output"}\n')
        receipt.write_bytes(b"# governed receipt\n")
        return SimpleNamespace(
            result=SimpleNamespace(trace_path=trace, receipt_path=receipt),
            detail=SimpleNamespace(
                outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                evidence_chunks=(
                    SimpleNamespace(
                        status="accepted",
                        citation="knowledge://insurance/rules/r1#p1",
                    ),
                ),
            ),
        )

    service = FormalProductionAgentOnlineSmokeService(
        online_smoke_validator=_formal_online_runner(
            tmp_path=tmp_path,
            artifact_store=artifact_store,
            execute=execute,
        )
    )

    with pytest.raises(FormalProductionAgentOnlineSmokeRejected) as raised:
        service.qualify(
            query_grant_staging=staging,
            smoke_question="等待期如何解释？",
        )

    assert raised.value.code == "online_smoke_unavailable"
    assert "corrupted private bytes" not in str(raised.value)
    assert staging.reference_staging.release_reference.state == "active"


def test_formal_publisher_stages_query_grant_between_reference_and_online_smoke() -> None:
    events: list[str] = []
    state = _FormalPublicationState(record=AgentDraftRecord(draft=_draft(), revision=11))
    factory = _FormalPublicationUnitOfWorkFactory(state)
    registrar = _ReferenceRegistrar(before_call=lambda: events.append("reference"))
    provisioner = _QueryGrantProvisioner(before_call=lambda: events.append("query_grant"))
    validator = _OnlineSmokeValidator(before_call=lambda: events.append("online_smoke"))

    _formal_publisher(
        factory=factory,
        authority=_PhaseFAuthority(),
        registrar=registrar,
        provisioner=provisioner,
        validator=validator,
    ).publish(
        agent_id=state.record.draft.agent_id,
        draft_id=state.record.draft.draft_id,
        draft_revision=state.record.revision,
        binding_profile=_binding_profile(),
        evidence=_phase_f_evidence(),
        smoke_question="等待期如何解释？",
        actor=_release_actor(),
    )

    assert events == ["reference", "query_grant", "online_smoke"]
    assert provisioner.calls == [
        ProductionAgentKnowledgeQueryGrantRequest(
            knowledge_base_release_id=_candidate().knowledge_base_release_id
        )
    ]


def test_formal_publication_command_preflight_is_read_only_before_phase_f() -> None:
    state = _FormalPublicationState(record=AgentDraftRecord(draft=_draft(), revision=11))
    factory = _FormalPublicationUnitOfWorkFactory(state)
    authority = _PhaseFAuthority()
    registrar = _ReferenceRegistrar()
    provisioner = _QueryGrantProvisioner()
    validator = _OnlineSmokeValidator()
    service = FormalProductionAgentPublicationCommandService(
        unit_of_work_factory=factory,
        publisher=_formal_publisher(
            factory=factory,
            authority=authority,
            registrar=registrar,
            provisioner=provisioner,
            validator=validator,
        ),
        binding_profile=_binding_profile(),
    )

    candidate = service.preflight(
        agent_id=state.record.draft.agent_id,
        draft_id=state.record.draft.draft_id,
        draft_revision=state.record.revision,
    )

    assert candidate.agent_id == state.record.draft.agent_id
    assert candidate.draft_id == state.record.draft.draft_id
    assert candidate.draft_revision == state.record.revision
    assert candidate.knowledge_release_candidate == _candidate()
    assert candidate.knowledge_service_catalog_revision == "kss-catalog-42"
    assert authority.records == []
    assert registrar.calls == []
    assert provisioner.calls == []
    assert validator.calls == []
    assert state.formal_publication_commands == {}
    assert state.publications == []
    assert state.active is None
    assert state.audits == []
    assert len(factory.units) == 1
    assert factory.units[0].committed is False


def test_formal_publication_command_receipt_read_is_actor_and_path_scoped() -> None:
    state = _FormalPublicationState(record=AgentDraftRecord(draft=_draft(), revision=11))
    command_record = FormalProductionAgentPublicationCommandRecord(
        actor_subject=_release_actor().subject,
        idempotency_key="formal-publish-status",
        receipt=FormalProductionAgentPublicationCommandReceipt(
            command_id="019ba001-1111-7000-8000-000000000810",
            state=FormalProductionAgentPublicationCommandState.IN_PROGRESS,
            agent_id=_draft().agent_id,
            draft_id=_draft().draft_id,
            draft_revision=11,
            request_sha256="1" * 64,
            started_at="2026-08-30T13:10:00Z",
        ),
        execution_claim=FormalProductionAgentPublicationExecutionClaim(
            fencing_token=1,
            owner_id="formal-publisher-process-1",
            lease_expires_at="2026-08-30T13:25:00Z",
        ),
        candidate_checkpoint=FormalProductionAgentPublicationCandidateCheckpoint(
            formal_candidate_sha256="2" * 64,
            knowledge_release_candidate_sha256="3" * 64,
            checkpointed_at="2026-08-30T13:10:01Z",
        ),
    )
    state.formal_publication_commands[
        (command_record.actor_subject, command_record.idempotency_key)
    ] = command_record
    factory = _FormalPublicationUnitOfWorkFactory(state)
    service = FormalProductionAgentPublicationCommandService(
        unit_of_work_factory=factory,
        publisher=_formal_publisher(
            factory=factory,
            authority=_PhaseFAuthority(),
            registrar=_ReferenceRegistrar(),
            validator=_OnlineSmokeValidator(),
        ),
        binding_profile=_binding_profile(),
    )

    receipt = service.get_receipt(
        agent_id=_draft().agent_id,
        draft_id=_draft().draft_id,
        command_id=command_record.receipt.command_id,
        actor=_release_actor(),
    )

    assert receipt == command_record.receipt
    for query in (
        {"actor": _release_actor().model_copy(update={"subject": "another-operator"})},
        {"agent_id": "another-agent"},
        {"draft_id": "019ba001-1111-7000-8000-000000000799"},
        {"command_id": "019ba001-1111-7000-8000-000000000899"},
        {"command_id": "not-a-command-id"},
    ):
        inputs = {
            "agent_id": _draft().agent_id,
            "draft_id": _draft().draft_id,
            "command_id": command_record.receipt.command_id,
            "actor": _release_actor(),
            **query,
        }
        with pytest.raises(FormalProductionAgentPublicationCommandRejected) as raised:
            service.get_receipt(**inputs)
        assert raised.value.code == "formal_publication_command_not_found"
    assert state.formal_publication_commands == {
        (command_record.actor_subject, command_record.idempotency_key): command_record
    }
    assert all(unit.committed is False for unit in factory.units)


def test_formal_publisher_rejects_checkpoint_drift_before_phase_f() -> None:
    state = _FormalPublicationState(record=AgentDraftRecord(draft=_draft(), revision=11))
    factory = _FormalPublicationUnitOfWorkFactory(state)
    authority = _PhaseFAuthority()
    registrar = _ReferenceRegistrar()
    provisioner = _QueryGrantProvisioner()
    validator = _OnlineSmokeValidator()
    publisher = _formal_publisher(
        factory=factory,
        authority=authority,
        registrar=registrar,
        provisioner=provisioner,
        validator=validator,
    )
    candidate = publisher.preflight(
        agent_id=state.record.draft.agent_id,
        draft_id=state.record.draft.draft_id,
        draft_revision=state.record.revision,
        binding_profile=_binding_profile(),
    )
    command_record = FormalProductionAgentPublicationCommandRecord(
        actor_subject=_release_actor().subject,
        idempotency_key="checkpoint-drift",
        receipt=FormalProductionAgentPublicationCommandReceipt(
            command_id="019ba001-1111-7000-8000-000000000809",
            state=FormalProductionAgentPublicationCommandState.IN_PROGRESS,
            agent_id=candidate.agent_id,
            draft_id=candidate.draft_id,
            draft_revision=candidate.draft_revision,
            request_sha256="1" * 64,
            started_at="2026-08-30T12:31:00Z",
        ),
        execution_claim=FormalProductionAgentPublicationExecutionClaim(
            fencing_token=1,
            owner_id="formal-publisher-process-1",
            lease_expires_at="2026-08-30T12:46:00Z",
        ),
        candidate_checkpoint=FormalProductionAgentPublicationCandidateCheckpoint(
            formal_candidate_sha256="0" * 64,
            knowledge_release_candidate_sha256=(candidate.knowledge_release_candidate_sha256),
            checkpointed_at="2026-08-30T12:31:01Z",
        ),
    )

    with pytest.raises(FormalProductionAgentPublicationRejected) as raised:
        publisher.publish_checkpointed_candidate(
            candidate=candidate,
            evidence=_phase_f_evidence(),
            smoke_question="等待期如何解释？",
            actor=_release_actor(),
            command_record=command_record,
        )

    assert raised.value.code == "formal_publication_candidate_checkpoint_conflict"
    assert authority.records == []
    assert registrar.calls == []
    assert provisioner.calls == []
    assert validator.calls == []
    assert state.publications == []


def test_formal_publisher_atomically_publishes_exact_qualification_after_cas() -> None:
    active = ActiveAgentVersion(
        agent_id=_draft().agent_id,
        version_id="active-version-before-smoke",
        activated_at="2026-08-30T11:00:00Z",
        activated_by="earlier-release-operator",
    )
    state = _FormalPublicationState(
        record=AgentDraftRecord(draft=_draft(), revision=11),
        active=active,
    )
    factory = _FormalPublicationUnitOfWorkFactory(state)
    authority = _PhaseFAuthority(before_call=lambda: _require_no_open_transaction(factory))
    registrar = _ReferenceRegistrar(before_call=lambda: _require_no_open_transaction(factory))
    validator = _OnlineSmokeValidator(before_call=lambda: _require_no_open_transaction(factory))
    publisher = _formal_publisher(
        factory=factory,
        authority=authority,
        registrar=registrar,
        validator=validator,
    )

    publication = publisher.publish(
        agent_id=state.record.draft.agent_id,
        draft_id=state.record.draft.draft_id,
        draft_revision=state.record.revision,
        binding_profile=_binding_profile(),
        evidence=_phase_f_evidence(),
        smoke_question="等待期如何解释？",
        actor=_release_actor(),
    )

    assert publication.active_pointer_expectation is not None
    assert publication.active_pointer_expectation.version_id == active.version_id
    version = publication.version
    assert version.version_id == "provisional-version-1"
    assert version.validation_run_id == "validation-run-1"
    assert version.published_at == "2026-08-30T12:32:00Z"
    assert version.published_by == _release_actor().subject
    assert publication.activation.version_id == version.version_id
    assert publication.activation.activated_at == version.published_at
    formal_evidence = version.formal_production_evidence
    assert isinstance(formal_evidence, FormalProductionAgentPublicationEvidence)
    assert formal_evidence.source_draft_revision == 11
    assert formal_evidence.phase_f_record == authority.records[0]
    assert formal_evidence.release_reference == next(iter(registrar.references.values()))
    assert formal_evidence.online_smoke_result.outcome is (ReceiptOutcome.ANSWERED_WITH_CITATIONS)
    assert PublishedAgentVersion.model_validate(version.model_dump(mode="python")) == version
    assert state.publications == [publication]
    assert state.active == publication.activation
    assert len(state.audits) == 1
    audit = state.audits[0]
    assert audit.event_type == "agent.formal_version_published"
    assert audit.target_id == version.version_id
    assert audit.metadata["phase_f_record_id"] == "phase-f-record-1"
    assert audit.metadata["release_reference_id"] == "release-reference-05c"
    assert audit.metadata["validation_run_id"] == "validation-run-1"
    assert audit.metadata["replaced_active_version_id"] == active.version_id
    assert len(factory.units) == 3
    assert [unit.committed for unit in factory.units] == [False, False, True]
    assert factory.open_count == 0


def test_formal_publication_command_persists_success_and_exact_replay_once() -> None:
    state = _FormalPublicationState(record=AgentDraftRecord(draft=_draft(), revision=11))
    factory = _FormalPublicationUnitOfWorkFactory(state)
    registrar = _ReferenceRegistrar()
    validator = _OnlineSmokeValidator()
    service = FormalProductionAgentPublicationCommandService(
        unit_of_work_factory=factory,
        publisher=_formal_publisher(
            factory=factory,
            authority=_PhaseFAuthority(),
            registrar=registrar,
            validator=validator,
        ),
        binding_profile=_binding_profile(),
        identifier_factory=lambda: "019ba001-1111-7000-8000-000000000805",
        clock=lambda: datetime(2026, 8, 30, 13, 5, tzinfo=UTC),
    )
    request = FormalProductionAgentPublicationCommandRequest(
        draft_revision=11,
        evidence=_phase_f_evidence(),
        smoke_question="等待期如何解释？",
    )

    first = service.publish(
        agent_id=_draft().agent_id,
        draft_id=_draft().draft_id,
        request=request,
        idempotency_key="formal-publish-11",
        actor=_release_actor(),
    )
    replay = service.publish(
        agent_id=_draft().agent_id,
        draft_id=_draft().draft_id,
        request=request,
        idempotency_key="formal-publish-11",
        actor=_release_actor(),
    )

    assert first.replayed is False
    assert first.receipt.state is FormalProductionAgentPublicationCommandState.SUCCEEDED
    assert first.receipt.published_version_id == validator.calls[0].provisional_version_id
    assert first.receipt.validation_run_id == validator.calls[0].validation_run_id
    assert first.receipt.release_reference_id == "release-reference-05c"
    assert replay.replayed is True
    assert replay.receipt == first.receipt
    assert len(state.publications) == 1
    assert len(state.formal_publication_commands) == 1
    assert len(registrar.calls) == 1
    assert len(validator.calls) == 1
    assert len(state.audits) == 1


def test_formal_publication_command_rejects_changed_request_before_external_calls() -> None:
    state = _FormalPublicationState(record=AgentDraftRecord(draft=_draft(), revision=11))
    factory = _FormalPublicationUnitOfWorkFactory(state)
    registrar = _ReferenceRegistrar()
    validator = _OnlineSmokeValidator()
    service = FormalProductionAgentPublicationCommandService(
        unit_of_work_factory=factory,
        publisher=_formal_publisher(
            factory=factory,
            authority=_PhaseFAuthority(),
            registrar=registrar,
            validator=validator,
        ),
        binding_profile=_binding_profile(),
    )
    request = FormalProductionAgentPublicationCommandRequest(
        draft_revision=11,
        evidence=_phase_f_evidence(),
        smoke_question="等待期如何解释？",
    )
    service.publish(
        agent_id=_draft().agent_id,
        draft_id=_draft().draft_id,
        request=request,
        idempotency_key="formal-publish-conflict",
        actor=_release_actor(),
    )

    with pytest.raises(FormalProductionAgentPublicationCommandRejected) as raised:
        service.publish(
            agent_id=_draft().agent_id,
            draft_id=_draft().draft_id,
            request=request.model_copy(update={"smoke_question": "新的问题"}),
            idempotency_key="formal-publish-conflict",
            actor=_release_actor(),
        )

    assert raised.value.code == "formal_publication_idempotency_conflict"
    assert len(registrar.calls) == 1
    assert len(validator.calls) == 1


def test_formal_publication_command_takes_over_after_process_exit_lease_expires() -> None:
    class _ProcessExitPublisher:
        def preflight(self, **kwargs: object) -> FormalProductionAgentCandidate:
            del kwargs
            return _assemble(AgentDraftRecord(draft=_draft(), revision=11))

        def publish_checkpointed_candidate(self, **kwargs: object) -> AgentPublicationRecord:
            del kwargs
            raise SystemExit("simulated process exit")

    state = _FormalPublicationState(record=AgentDraftRecord(draft=_draft(), revision=11))
    factory = _FormalPublicationUnitOfWorkFactory(state)
    request = FormalProductionAgentPublicationCommandRequest(
        draft_revision=11,
        evidence=_phase_f_evidence(),
        smoke_question="等待期如何解释？",
    )
    interrupted = FormalProductionAgentPublicationCommandService(
        unit_of_work_factory=factory,
        publisher=cast(FormalProductionAgentPublisher, _ProcessExitPublisher()),
        binding_profile=_binding_profile(),
        identifier_factory=lambda: "019ba001-1111-7000-8000-000000000806",
        clock=lambda: datetime(2026, 8, 30, 13, 6, tzinfo=UTC),
        execution_owner="formal-publisher-process-1",
        lease_duration=timedelta(seconds=30),
    )
    with pytest.raises(SystemExit):
        interrupted.publish(
            agent_id=_draft().agent_id,
            draft_id=_draft().draft_id,
            request=request,
            idempotency_key="formal-publish-interrupted",
            actor=_release_actor(),
        )

    persisted = state.formal_publication_commands[
        (_release_actor().subject, "formal-publish-interrupted")
    ]
    assert persisted.candidate_checkpoint is not None
    first_checkpoint = persisted.candidate_checkpoint

    registrar = _ReferenceRegistrar()
    validator = _OnlineSmokeValidator()
    publisher = _formal_publisher(
        factory=factory,
        authority=_PhaseFAuthority(),
        registrar=registrar,
        validator=validator,
    )
    before_expiry = FormalProductionAgentPublicationCommandService(
        unit_of_work_factory=factory,
        publisher=publisher,
        binding_profile=_binding_profile(),
        clock=lambda: datetime(2026, 8, 30, 13, 6, 29, tzinfo=UTC),
        execution_owner="formal-publisher-process-2",
        lease_duration=timedelta(seconds=30),
    )
    in_progress = before_expiry.publish(
        agent_id=_draft().agent_id,
        draft_id=_draft().draft_id,
        request=request,
        idempotency_key="formal-publish-interrupted",
        actor=_release_actor(),
    )

    assert in_progress.replayed is True
    assert in_progress.receipt.state is FormalProductionAgentPublicationCommandState.IN_PROGRESS
    assert registrar.calls == []
    assert validator.calls == []

    after_expiry = FormalProductionAgentPublicationCommandService(
        unit_of_work_factory=factory,
        publisher=publisher,
        binding_profile=_binding_profile(),
        clock=lambda: datetime(2026, 8, 30, 13, 6, 31, tzinfo=UTC),
        execution_owner="formal-publisher-process-2",
        lease_duration=timedelta(seconds=30),
    )
    recovered = after_expiry.publish(
        agent_id=_draft().agent_id,
        draft_id=_draft().draft_id,
        request=request,
        idempotency_key="formal-publish-interrupted",
        actor=_release_actor(),
    )

    assert recovered.replayed is True
    assert recovered.receipt.state is FormalProductionAgentPublicationCommandState.SUCCEEDED
    assert len(state.publications) == 1
    assert len(registrar.calls) == 1
    assert len(validator.calls) == 1
    terminal = state.formal_publication_commands[
        (_release_actor().subject, "formal-publish-interrupted")
    ]
    assert terminal.candidate_checkpoint == first_checkpoint


def test_formal_publication_command_takeover_reuses_external_identities() -> None:
    state = _FormalPublicationState(record=AgentDraftRecord(draft=_draft(), revision=11))
    factory = _FormalPublicationUnitOfWorkFactory(state)
    registrar = _ReferenceRegistrar()
    request = FormalProductionAgentPublicationCommandRequest(
        draft_revision=11,
        evidence=_phase_f_evidence(),
        smoke_question="等待期如何解释？",
    )
    first_ids = iter(("phase-first", "version-first", "run-first"))
    first_authority = _PhaseFAuthority()
    interrupted_validator = _OnlineSmokeValidator(failure=SystemExit("process exit"))
    interrupted = FormalProductionAgentPublicationCommandService(
        unit_of_work_factory=factory,
        publisher=_formal_publisher(
            factory=factory,
            authority=_PhaseFAuthority(),
            registrar=registrar,
            validator=interrupted_validator,
            phase_f_preparer=FormalProductionAgentPhaseFPreparer(
                phase_f_authority=first_authority,
                identifier_factory=lambda: next(first_ids),
                clock=lambda: datetime(2026, 8, 30, 13, 7, tzinfo=UTC),
            ),
        ),
        binding_profile=_binding_profile(),
        identifier_factory=lambda: "019ba001-1111-7000-8000-000000000807",
        clock=lambda: datetime(2026, 8, 30, 13, 7, tzinfo=UTC),
        execution_owner="formal-publisher-process-1",
        lease_duration=timedelta(seconds=30),
    )

    with pytest.raises(SystemExit):
        interrupted.publish(
            agent_id=_draft().agent_id,
            draft_id=_draft().draft_id,
            request=request,
            idempotency_key="formal-publish-stable-identities",
            actor=_release_actor(),
        )

    persisted = state.formal_publication_commands[
        (_release_actor().subject, "formal-publish-stable-identities")
    ]
    assert persisted.candidate_checkpoint is not None
    first_checkpoint = persisted.candidate_checkpoint

    second_ids = iter(("phase-second", "version-second", "run-second"))
    second_authority = _PhaseFAuthority()
    resumed_validator = _OnlineSmokeValidator()
    resumed = FormalProductionAgentPublicationCommandService(
        unit_of_work_factory=factory,
        publisher=_formal_publisher(
            factory=factory,
            authority=_PhaseFAuthority(),
            registrar=registrar,
            validator=resumed_validator,
            phase_f_preparer=FormalProductionAgentPhaseFPreparer(
                phase_f_authority=second_authority,
                identifier_factory=lambda: next(second_ids),
                clock=lambda: datetime(2026, 8, 30, 13, 7, 31, tzinfo=UTC),
            ),
        ),
        binding_profile=_binding_profile(),
        clock=lambda: datetime(2026, 8, 30, 13, 7, 31, tzinfo=UTC),
        execution_owner="formal-publisher-process-2",
        lease_duration=timedelta(seconds=30),
    )

    recovered = resumed.publish(
        agent_id=_draft().agent_id,
        draft_id=_draft().draft_id,
        request=request,
        idempotency_key="formal-publish-stable-identities",
        actor=_release_actor(),
    )

    assert recovered.receipt.state is FormalProductionAgentPublicationCommandState.SUCCEEDED
    assert len(registrar.calls) == 2
    assert registrar.calls[0] == registrar.calls[1]
    assert interrupted_validator.calls[0].provisional_version_id == (
        resumed_validator.calls[0].provisional_version_id
    )
    assert interrupted_validator.calls[0].validation_run_id == (
        resumed_validator.calls[0].validation_run_id
    )
    assert first_authority.records == second_authority.records
    terminal = state.formal_publication_commands[
        (_release_actor().subject, "formal-publish-stable-identities")
    ]
    assert terminal.candidate_checkpoint == first_checkpoint


def test_formal_publication_command_takeover_rejects_candidate_digest_drift_before_phase_f() -> (
    None
):
    state = _FormalPublicationState(record=AgentDraftRecord(draft=_draft(), revision=11))
    factory = _FormalPublicationUnitOfWorkFactory(state)
    registrar = _ReferenceRegistrar()
    request = FormalProductionAgentPublicationCommandRequest(
        draft_revision=11,
        evidence=_phase_f_evidence(),
        smoke_question="等待期如何解释？",
    )
    first_authority = _PhaseFAuthority()
    interrupted = FormalProductionAgentPublicationCommandService(
        unit_of_work_factory=factory,
        publisher=_formal_publisher(
            factory=factory,
            authority=first_authority,
            registrar=registrar,
            validator=_OnlineSmokeValidator(failure=SystemExit("process exit")),
            catalog=_catalog(catalog_revision="kss-catalog-before-exit"),
        ),
        binding_profile=_binding_profile(),
        identifier_factory=lambda: "019ba001-1111-7000-8000-000000000808",
        clock=lambda: datetime(2026, 8, 30, 13, 8, tzinfo=UTC),
        execution_owner="formal-publisher-process-1",
        lease_duration=timedelta(seconds=30),
    )

    with pytest.raises(SystemExit):
        interrupted.publish(
            agent_id=_draft().agent_id,
            draft_id=_draft().draft_id,
            request=request,
            idempotency_key="formal-publish-candidate-checkpoint",
            actor=_release_actor(),
        )

    resumed_authority = _PhaseFAuthority()
    resumed = FormalProductionAgentPublicationCommandService(
        unit_of_work_factory=factory,
        publisher=_formal_publisher(
            factory=factory,
            authority=resumed_authority,
            registrar=registrar,
            validator=_OnlineSmokeValidator(),
            catalog=_catalog(catalog_revision="kss-catalog-after-exit"),
        ),
        binding_profile=_binding_profile(),
        clock=lambda: datetime(2026, 8, 30, 13, 8, 31, tzinfo=UTC),
        execution_owner="formal-publisher-process-2",
        lease_duration=timedelta(seconds=30),
    )

    recovered = resumed.publish(
        agent_id=_draft().agent_id,
        draft_id=_draft().draft_id,
        request=request,
        idempotency_key="formal-publish-candidate-checkpoint",
        actor=_release_actor(),
    )

    assert recovered.replayed is True
    assert recovered.receipt.state is FormalProductionAgentPublicationCommandState.FAILED
    assert recovered.receipt.failure_code == "formal_publication_candidate_checkpoint_conflict"
    assert len(first_authority.records) == 1
    assert resumed_authority.records == []
    assert len(registrar.calls) == 1
    assert state.publications == []
    assert state.active is None


def test_formal_publication_command_persists_and_replays_stable_failure() -> None:
    state = _FormalPublicationState(record=AgentDraftRecord(draft=_draft(), revision=11))
    factory = _FormalPublicationUnitOfWorkFactory(state)
    validator = _OnlineSmokeValidator(failure=RuntimeError("private upstream detail"))
    service = FormalProductionAgentPublicationCommandService(
        unit_of_work_factory=factory,
        publisher=_formal_publisher(
            factory=factory,
            authority=_PhaseFAuthority(),
            registrar=_ReferenceRegistrar(),
            validator=validator,
        ),
        binding_profile=_binding_profile(),
    )
    request = FormalProductionAgentPublicationCommandRequest(
        draft_revision=11,
        evidence=_phase_f_evidence(),
        smoke_question="等待期如何解释？",
    )

    first = service.publish(
        agent_id=_draft().agent_id,
        draft_id=_draft().draft_id,
        request=request,
        idempotency_key="formal-publish-failed",
        actor=_release_actor(),
    )
    replay = service.publish(
        agent_id=_draft().agent_id,
        draft_id=_draft().draft_id,
        request=request,
        idempotency_key="formal-publish-failed",
        actor=_release_actor(),
    )

    assert first.receipt.state is FormalProductionAgentPublicationCommandState.FAILED
    assert first.receipt.failure_code == "online_smoke_unavailable"
    assert "private upstream detail" not in first.model_dump_json()
    assert replay.replayed is True
    assert replay.receipt == first.receipt
    assert len(validator.calls) == 1


def test_formal_publication_command_rolls_back_publication_if_receipt_completion_fails() -> None:
    state = _FormalPublicationState(
        record=AgentDraftRecord(draft=_draft(), revision=11),
        command_failures=[RuntimeError("private receipt write detail")],
    )
    factory = _FormalPublicationUnitOfWorkFactory(state)
    service = FormalProductionAgentPublicationCommandService(
        unit_of_work_factory=factory,
        publisher=_formal_publisher(
            factory=factory,
            authority=_PhaseFAuthority(),
            registrar=_ReferenceRegistrar(),
            validator=_OnlineSmokeValidator(),
        ),
        binding_profile=_binding_profile(),
    )

    result = service.publish(
        agent_id=_draft().agent_id,
        draft_id=_draft().draft_id,
        request=FormalProductionAgentPublicationCommandRequest(
            draft_revision=11,
            evidence=_phase_f_evidence(),
            smoke_question="等待期如何解释？",
        ),
        idempotency_key="formal-publish-rollback",
        actor=_release_actor(),
    )

    assert result.receipt.state is FormalProductionAgentPublicationCommandState.FAILED
    assert result.receipt.failure_code == "formal_publication_storage_unavailable"
    assert state.publications == []
    assert state.active is None
    assert state.audits == []
    assert "private receipt write detail" not in result.model_dump_json()


def test_formal_publication_command_contract_rejects_unknown_or_private_inputs() -> None:
    payload = FormalProductionAgentPublicationCommandRequest(
        draft_revision=11,
        evidence=_phase_f_evidence(),
        smoke_question="等待期如何解释？",
    ).model_dump(mode="python")

    for private_field in (
        "binding_profile",
        "release_reference_id",
        "published_version_id",
        "actor_subject",
    ):
        with pytest.raises(ValidationError, match="extra_forbidden"):
            FormalProductionAgentPublicationCommandRequest.model_validate(
                {**payload, private_field: "caller-controlled"}
            )


@pytest.mark.parametrize(
    ("concurrent_change", "expected_code"),
    [
        ("active", "formal_publication_active_pointer_conflict"),
        ("draft", "formal_publication_draft_revision_conflict"),
    ],
)
def test_formal_publisher_rejects_concurrent_change_after_smoke_without_partial_write(
    concurrent_change: str,
    expected_code: str,
) -> None:
    initial_active = ActiveAgentVersion(
        agent_id=_draft().agent_id,
        version_id="active-version-before-smoke",
        activated_at="2026-08-30T11:00:00Z",
        activated_by="earlier-release-operator",
    )
    state = _FormalPublicationState(
        record=AgentDraftRecord(draft=_draft(), revision=11),
        active=initial_active,
    )
    factory = _FormalPublicationUnitOfWorkFactory(state)
    registrar = _ReferenceRegistrar()

    def change_concurrently() -> None:
        if concurrent_change == "active":
            state.active = ActiveAgentVersion(
                agent_id=_draft().agent_id,
                version_id="active-version-concurrent",
                activated_at="2026-08-30T12:31:30Z",
                activated_by="concurrent-release-operator",
            )
        else:
            state.record = AgentDraftRecord(draft=_draft(), revision=12)

    publisher = _formal_publisher(
        factory=factory,
        authority=_PhaseFAuthority(),
        registrar=registrar,
        validator=_OnlineSmokeValidator(after_call=change_concurrently),
    )

    with pytest.raises(FormalProductionAgentPublicationRejected) as raised:
        publisher.publish(
            agent_id=state.record.draft.agent_id,
            draft_id=state.record.draft.draft_id,
            draft_revision=11,
            binding_profile=_binding_profile(),
            evidence=_phase_f_evidence(),
            smoke_question="等待期如何解释？",
            actor=_release_actor(),
        )

    assert raised.value.code == expected_code
    assert state.publications == []
    assert state.audits == []
    if concurrent_change == "active":
        assert state.active is not None
        assert state.active.version_id == "active-version-concurrent"
    else:
        assert state.active == initial_active
        assert state.record.revision == 12
    assert len(registrar.references) == 1
    assert factory.open_count == 0


def test_formal_publisher_rolls_back_version_activation_and_audit_when_audit_fails() -> None:
    initial_active = ActiveAgentVersion(
        agent_id=_draft().agent_id,
        version_id="active-version-before-smoke",
        activated_at="2026-08-30T11:00:00Z",
        activated_by="earlier-release-operator",
    )
    state = _FormalPublicationState(
        record=AgentDraftRecord(draft=_draft(), revision=11),
        active=initial_active,
        audit_failure=RuntimeError("private audit storage detail"),
    )
    factory = _FormalPublicationUnitOfWorkFactory(state)
    registrar = _ReferenceRegistrar()
    publisher = _formal_publisher(
        factory=factory,
        authority=_PhaseFAuthority(),
        registrar=registrar,
        validator=_OnlineSmokeValidator(),
    )

    with pytest.raises(FormalProductionAgentPublicationRejected) as raised:
        publisher.publish(
            agent_id=state.record.draft.agent_id,
            draft_id=state.record.draft.draft_id,
            draft_revision=state.record.revision,
            binding_profile=_binding_profile(),
            evidence=_phase_f_evidence(),
            smoke_question="等待期如何解释？",
            actor=_release_actor(),
        )

    assert raised.value.code == "formal_publication_storage_unavailable"
    assert "private audit storage detail" not in str(raised.value)
    assert state.publications == []
    assert state.active == initial_active
    assert state.audits == []
    assert len(registrar.references) == 1
    assert factory.open_count == 0


def test_formal_publisher_smoke_failure_never_opens_the_write_transaction() -> None:
    state = _FormalPublicationState(record=AgentDraftRecord(draft=_draft(), revision=11))
    factory = _FormalPublicationUnitOfWorkFactory(state)
    registrar = _ReferenceRegistrar()
    provisioner = _QueryGrantProvisioner()
    publisher = _formal_publisher(
        factory=factory,
        authority=_PhaseFAuthority(),
        registrar=registrar,
        provisioner=provisioner,
        validator=_OnlineSmokeValidator(
            result_updates={"outcome": ReceiptOutcome.REFUSED_NO_EVIDENCE}
        ),
    )

    with pytest.raises(FormalProductionAgentOnlineSmokeRejected) as raised:
        publisher.publish(
            agent_id=state.record.draft.agent_id,
            draft_id=state.record.draft.draft_id,
            draft_revision=state.record.revision,
            binding_profile=_binding_profile(),
            evidence=_phase_f_evidence(),
            smoke_question="等待期如何解释？",
            actor=_release_actor(),
        )

    assert raised.value.code == "online_smoke_failed"
    assert state.publications == []
    assert state.active is None
    assert state.audits == []
    assert len(registrar.references) == 1
    assert len(provisioner.calls) == 1
    assert len(factory.units) == 2
    assert all(not unit.committed for unit in factory.units)


def test_formal_publisher_query_grant_failure_stops_before_online_smoke_and_write() -> None:
    state = _FormalPublicationState(record=AgentDraftRecord(draft=_draft(), revision=11))
    factory = _FormalPublicationUnitOfWorkFactory(state)
    registrar = _ReferenceRegistrar()
    provisioner = _QueryGrantProvisioner(failure=RuntimeError("private KSS detail"))
    validator = _OnlineSmokeValidator()
    publisher = _formal_publisher(
        factory=factory,
        authority=_PhaseFAuthority(),
        registrar=registrar,
        provisioner=provisioner,
        validator=validator,
    )

    with pytest.raises(FormalProductionAgentQueryGrantStagingRejected) as raised:
        publisher.publish(
            agent_id=state.record.draft.agent_id,
            draft_id=state.record.draft.draft_id,
            draft_revision=state.record.revision,
            binding_profile=_binding_profile(),
            evidence=_phase_f_evidence(),
            smoke_question="等待期如何解释？",
            actor=_release_actor(),
        )

    assert raised.value.code == "query_grant_provisioning_unavailable"
    assert "private KSS detail" not in str(raised.value)
    assert len(registrar.references) == 1
    assert len(provisioner.calls) == 1
    assert validator.calls == []
    assert state.publications == []
    assert state.active is None
    assert state.audits == []
    assert len(factory.units) == 2
    assert all(not unit.committed for unit in factory.units)


def test_formal_publisher_rejects_foreign_active_agent_before_reference_registration() -> None:
    state = _FormalPublicationState(
        record=AgentDraftRecord(draft=_draft(), revision=11),
        active=ActiveAgentVersion(
            agent_id="foreign-active-agent",
            version_id="foreign-active-version",
            activated_at="2026-08-30T11:00:00Z",
            activated_by="earlier-release-operator",
        ),
    )
    factory = _FormalPublicationUnitOfWorkFactory(state)
    registrar = _ReferenceRegistrar()
    validator = _OnlineSmokeValidator()
    publisher = _formal_publisher(
        factory=factory,
        authority=_PhaseFAuthority(),
        registrar=registrar,
        validator=validator,
    )

    with pytest.raises(FormalProductionAgentPublicationRejected) as raised:
        publisher.publish(
            agent_id=state.record.draft.agent_id,
            draft_id=state.record.draft.draft_id,
            draft_revision=state.record.revision,
            binding_profile=_binding_profile(),
            evidence=_phase_f_evidence(),
            smoke_question="等待期如何解释？",
            actor=_release_actor(),
        )

    assert raised.value.code == "formal_publication_active_invariant_invalid"
    assert registrar.calls == []
    assert validator.calls == []
    assert state.publications == []
    assert state.audits == []


def test_formal_publication_evidence_rejects_drift_and_unknown_fields() -> None:
    staging = _query_grant_staging(_reference_staging(_ReferenceRegistrar()))
    result = _OnlineSmokeValidator().validate_online_smoke(
        _online_smoke_request(staging),
        query_grant_staging=staging,
    )
    reference_staging = staging.reference_staging
    payload = {
        "source_draft_revision": 11,
        "phase_f_record": reference_staging.preparation.provisional_version.phase_f_record,
        "release_reference": reference_staging.release_reference,
        "online_smoke_result": result,
    }

    with pytest.raises(ValidationError, match="identities must match"):
        FormalProductionAgentPublicationEvidence.model_validate(
            {
                **payload,
                "online_smoke_result": result.model_copy(update={"validation_run_id": "run-drift"}),
            }
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        FormalProductionAgentPublicationEvidence.model_validate(
            {**payload, "active_version_id": "must-not-be-caller-selected"}
        )


def test_formal_publication_record_requires_matching_draft_revision_and_cas() -> None:
    state = _FormalPublicationState(record=AgentDraftRecord(draft=_draft(), revision=11))
    publication = _formal_publisher(
        factory=_FormalPublicationUnitOfWorkFactory(state),
        authority=_PhaseFAuthority(),
        registrar=_ReferenceRegistrar(),
        validator=_OnlineSmokeValidator(),
    ).publish(
        agent_id=state.record.draft.agent_id,
        draft_id=state.record.draft.draft_id,
        draft_revision=state.record.revision,
        binding_profile=_binding_profile(),
        evidence=_phase_f_evidence(),
        smoke_question="等待期如何解释？",
        actor=_release_actor(),
    )

    with pytest.raises(ValidationError, match="Draft revision"):
        AgentPublicationRecord.model_validate(
            publication.model_copy(update={"draft_revision": 12}).model_dump(mode="python")
        )
    with pytest.raises(ValidationError, match="Active pointer expectation"):
        AgentPublicationRecord.model_validate(
            publication.model_copy(update={"active_pointer_expectation": None}).model_dump(
                mode="python"
            )
        )


@pytest.mark.parametrize(
    "field",
    ["formal_candidate_sha256", "knowledge_release_candidate_sha256"],
)
def test_phase_f_preparer_rejects_tampered_candidate_digest(field: str) -> None:
    candidate = _assemble(AgentDraftRecord(draft=_draft(), revision=11))
    tampered = candidate.model_copy(update={field: "0" * 64})
    authority = _PhaseFAuthority()

    with pytest.raises(FormalProductionAgentPhaseFRejected) as raised:
        _phase_f_preparer(authority).prepare(
            candidate=tampered,
            evidence=_phase_f_evidence(),
            actor=_release_actor(),
        )

    assert raised.value.code == "phase_f_candidate_integrity_invalid"
    assert authority.records == []


def test_phase_f_preparer_rejects_duplicate_evidence_before_authority() -> None:
    candidate = _assemble(AgentDraftRecord(draft=_draft(), revision=11))
    evidence = _phase_f_evidence()
    duplicate = evidence.model_copy(update={"capacity": evidence.shadow})
    authority = _PhaseFAuthority()

    with pytest.raises(FormalProductionAgentPhaseFRejected) as raised:
        _phase_f_preparer(authority).prepare(
            candidate=candidate,
            evidence=duplicate,
            actor=_release_actor(),
        )

    assert raised.value.code == "phase_f_evidence_invalid"
    assert authority.records == []


@pytest.mark.parametrize(
    ("authority", "expected_code"),
    [
        (_PhaseFAuthority(authorized=False), "phase_f_authority_denied"),
        (
            _PhaseFAuthority(failure=RuntimeError("private authority detail")),
            "phase_f_authority_unavailable",
        ),
    ],
)
def test_phase_f_preparer_fails_closed_when_authority_does_not_approve(
    authority: _PhaseFAuthority,
    expected_code: str,
) -> None:
    candidate = _assemble(AgentDraftRecord(draft=_draft(), revision=11))

    with pytest.raises(FormalProductionAgentPhaseFRejected) as raised:
        _phase_f_preparer(authority).prepare(
            candidate=candidate,
            evidence=_phase_f_evidence(),
            actor=_release_actor(),
        )

    assert raised.value.code == expected_code
    assert "private authority detail" not in str(raised.value)
    assert len(authority.records) == 1


def test_phase_f_preparer_rejects_unresolvable_workflow_before_authority() -> None:
    candidate = _assemble(AgentDraftRecord(draft=_draft(), revision=11))
    invalid_bundle = candidate.contract_bundle.model_copy(
        update={"agent_yaml": "name: agent_management_insurance_specialist\n"}
    )
    invalid = _candidate_with_contract_bundle(candidate, invalid_bundle)
    authority = _PhaseFAuthority()

    with pytest.raises(FormalProductionAgentPhaseFRejected) as raised:
        _phase_f_preparer(authority).prepare(
            candidate=invalid,
            evidence=_phase_f_evidence(),
            actor=_release_actor(),
        )

    assert raised.value.code == "phase_f_workflow_configuration_invalid"
    assert authority.records == []


def test_formal_phase_f_record_verifier_rejects_evidence_drift() -> None:
    candidate = _assemble(AgentDraftRecord(draft=_draft(), revision=11))
    preparation = _phase_f_preparer(_PhaseFAuthority()).prepare(
        candidate=candidate,
        evidence=_phase_f_evidence(),
        actor=_release_actor(),
    )
    record = preparation.provisional_version.phase_f_record
    drifted_evidence = record.evidence.model_copy(
        update={"recovery": _artifact("recovery-drift", "5")}
    )
    drifted_record = record.model_copy(update={"evidence": drifted_evidence})

    with pytest.raises(ProofAgentError, match="digest is invalid"):
        require_formal_production_agent_phase_f_record(
            record=drifted_record,
            candidate=candidate,
        )


def _assemble(record: AgentDraftRecord) -> FormalProductionAgentCandidate:
    return _assembler(
        uow_factory=_UnitOfWorkFactory(record),
        catalog=_Catalog(_catalog()),
    ).assemble(
        agent_id=record.draft.agent_id,
        draft_id=record.draft.draft_id,
        draft_revision=record.revision,
        binding_profile=_binding_profile(),
    )


def _candidate_with_contract_bundle(
    candidate: FormalProductionAgentCandidate,
    contract_bundle: ContractBundle,
) -> FormalProductionAgentCandidate:
    release_digest = knowledge_release_candidate_sha256(
        contract_bundle,
        candidate.resolved_knowledge_bindings,
    )
    updated = candidate.model_copy(
        update={
            "contract_bundle": contract_bundle,
            "knowledge_release_candidate_sha256": release_digest,
            "formal_candidate_sha256": "0" * 64,
        }
    )
    return updated.model_copy(
        update={"formal_candidate_sha256": formal_production_agent_candidate_sha256(updated)}
    )


def _phase_f_preparer(
    authority: _PhaseFAuthority,
) -> FormalProductionAgentPhaseFPreparer:
    identities = iter(("phase-f-record-1", "provisional-version-1", "validation-run-1"))
    return FormalProductionAgentPhaseFPreparer(
        phase_f_authority=authority,
        identifier_factory=lambda: next(identities),
        clock=lambda: datetime(2026, 8, 30, 12, 30, tzinfo=UTC),
    )


def _phase_f_preparation() -> FormalProductionAgentPhaseFPreparation:
    return _phase_f_preparer(_PhaseFAuthority()).prepare(
        candidate=_assemble(AgentDraftRecord(draft=_draft(), revision=11)),
        evidence=_phase_f_evidence(),
        actor=_release_actor(),
    )


def _reference_staging(
    registrar: _ReferenceRegistrar,
) -> FormalProductionAgentReferenceStaging:
    return FormalProductionAgentReferenceStager(registrar=registrar).stage(
        preparation=_phase_f_preparation(),
    )


def _real_reference_staging() -> FormalProductionAgentReferenceStaging:
    bundle = build_agent_package_contract_bundle(
        Path("deploy/production/agent_management_insurance_specialist/agent.yaml")
    )
    candidate = _candidate_with_contract_bundle(
        _assemble(AgentDraftRecord(draft=_draft(), revision=11)),
        bundle,
    )
    preparation = _phase_f_preparer(_PhaseFAuthority()).prepare(
        candidate=candidate,
        evidence=_phase_f_evidence(),
        actor=_release_actor(),
    )
    return FormalProductionAgentReferenceStager(registrar=_ReferenceRegistrar()).stage(
        preparation=preparation,
    )


def _formal_online_runner(
    *,
    tmp_path: Path,
    artifact_store: object,
    execute: Callable[..., object],
) -> FormalProductionAgentOnlineSmokeRunner:
    return FormalProductionAgentOnlineSmokeRunner(
        configuration_store=object(),
        knowledge_candidate_runtime=object(),
        guarded_http_client=object(),
        secret_provider=object(),
        model_credential_resolver=object(),
        artifact_store=artifact_store,
        work_root=tmp_path / "formal-smoke-work",
        institution_authorization=InstitutionAuthorizationContext(
            institutions=("branch-shanghai",)
        ),
        execute=execute,
    )


def _formal_candidate_external_runner(
    *,
    tmp_path: Path,
    artifact_store: object,
    execute: Callable[..., object],
    run_id: str,
) -> FormalProductionAgentCandidateExternalSmokeRunner:
    return FormalProductionAgentCandidateExternalSmokeRunner(
        configuration_store=object(),
        knowledge_candidate_runtime=object(),
        guarded_http_client=object(),
        secret_provider=object(),
        model_credential_resolver=object(),
        artifact_store=artifact_store,
        work_root=tmp_path / "candidate-probe-work",
        institution_authorization=InstitutionAuthorizationContext(
            institutions=("branch-shanghai",)
        ),
        identifier_factory=lambda: run_id,
        execute=execute,
    )


def _online_smoke_request(
    staging: FormalProductionAgentQueryGrantStaging,
) -> FormalProductionAgentOnlineSmokeRequest:
    reference_staging = staging.reference_staging
    preparation = reference_staging.preparation
    candidate = preparation.candidate
    provisional = preparation.provisional_version
    release = candidate.knowledge_release_candidate
    return FormalProductionAgentOnlineSmokeRequest(
        agent_id=candidate.agent_id,
        provisional_version_id=provisional.version_id,
        validation_run_id=provisional.validation_run_id,
        formal_candidate_sha256=candidate.formal_candidate_sha256,
        knowledge_release_candidate_sha256=candidate.knowledge_release_candidate_sha256,
        knowledge_space_id=release.knowledge_space_id,
        knowledge_base_id=release.knowledge_base_id,
        knowledge_base_release_id=release.knowledge_base_release_id,
        release_reference_id=reference_staging.release_reference.release_reference_id,
        smoke_question="等待期如何解释？",
    )


def _query_grant_staging(
    reference_staging: FormalProductionAgentReferenceStaging,
) -> FormalProductionAgentQueryGrantStaging:
    return FormalProductionAgentQueryGrantStager(
        provisioner=_QueryGrantProvisioner(),
    ).stage(reference_staging=reference_staging)


def _formal_publisher(
    *,
    factory: _FormalPublicationUnitOfWorkFactory,
    authority: _PhaseFAuthority,
    registrar: _ReferenceRegistrar,
    provisioner: _QueryGrantProvisioner | None = None,
    validator: _OnlineSmokeValidator,
    phase_f_preparer: FormalProductionAgentPhaseFPreparer | None = None,
    catalog: KnowledgeServiceManagementWorkspace | None = None,
) -> FormalProductionAgentPublisher:
    candidate_assembler = FormalProductionAgentCandidateAssembler(
        unit_of_work_factory=factory,
        knowledge_release_catalog=_Catalog(
            catalog or _catalog(),
            before_call=lambda: _require_no_open_transaction(factory),
        ),
        publication_configuration_projector=ProductionAgentPublicationConfigurationProjector(
            configuration_store=_ModelConnections(_model_connection())
        ),
    )
    return FormalProductionAgentPublisher(
        unit_of_work_factory=factory,
        candidate_assembler=candidate_assembler,
        phase_f_preparer=phase_f_preparer or _phase_f_preparer(authority),
        reference_stager=FormalProductionAgentReferenceStager(registrar=registrar),
        query_grant_stager=FormalProductionAgentQueryGrantStager(
            provisioner=provisioner or _QueryGrantProvisioner(),
        ),
        online_smoke_service=FormalProductionAgentOnlineSmokeService(
            online_smoke_validator=validator
        ),
        clock=lambda: datetime(2026, 8, 30, 12, 32, tzinfo=UTC),
    )


def _require_no_open_transaction(
    factory: _FormalPublicationUnitOfWorkFactory,
) -> None:
    assert factory.open_count == 0


def _release_actor() -> AuditActorFacts:
    return AuditActorFacts(
        subject="release-operator",
        identity_provider="deployment-identity",
        session_id="release-session-05b",
    )


def _assembler(
    *,
    uow_factory: _UnitOfWorkFactory,
    catalog: FormalProductionKnowledgeReleaseCatalog,
) -> FormalProductionAgentCandidateAssembler:
    return FormalProductionAgentCandidateAssembler(
        unit_of_work_factory=uow_factory,
        knowledge_release_catalog=catalog,
        publication_configuration_projector=ProductionAgentPublicationConfigurationProjector(
            configuration_store=_ModelConnections(_model_connection())
        ),
    )


def _draft() -> DraftAgent:
    return DraftAgent(
        agent_id="agent_management_insurance_specialist",
        draft_id="019ba001-1111-7000-8000-000000000701",
        display_name="Insurance Specialist",
        purpose="Answer governed insurance questions.",
        contract_bundle=ContractBundle(
            agent_yaml=_ready_agent_yaml(),
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
        ),
        knowledge_release_binding_candidate=_candidate(),
        created_at="2026-08-12T00:00:00Z",
        updated_at="2026-08-30T00:00:00Z",
        created_by="operator-1",
        updated_by="operator-1",
    )


def _ready_agent_yaml() -> str:
    return (
        "name: agent_management_insurance_specialist\n"
        "purpose: Test.\n"
        "workflow:\n"
        "  template: react_enterprise_qa_v3\n"
        "  template_descriptor_version: react_enterprise_qa.v3\n"
        "model:\n"
        "  model_source: shared\n"
        "  connection_id: model_deepseek\n"
        "react:\n"
        "  planner:\n"
        "    model_source: shared\n"
        "    connection_id: model_deepseek\n"
        "review:\n"
        "  subagent:\n"
        "    model_source: shared\n"
        "    connection_id: model_deepseek\n"
        "    fail_closed: true\n"
        "package_knowledge_sources: []\n"
        "knowledge_bindings: []\n"
        "capabilities:\n"
        "  tools:\n"
        "    enabled: false\n"
        "  memory:\n"
        "    enabled: false\n"
    )


def _candidate() -> DraftKnowledgeReleaseBindingCandidate:
    return DraftKnowledgeReleaseBindingCandidate(
        knowledge_space_id="insurance",
        knowledge_base_id="insurance-guidance",
        knowledge_base_version_id="insurance-guidance-v3",
        knowledge_base_release_id="release-a4b70851cb914862000e15c3",
    )


def _catalog(
    *,
    release_state: Literal["queryable", "deprecated", "retired", "revoked"] = "queryable",
    readiness_state: Literal["ready", "unavailable"] = "ready",
    catalog_revision: str | None = "kss-catalog-42",
    release_base_version_id: str | None = None,
) -> KnowledgeServiceManagementWorkspace:
    release_payload = _candidate().model_dump(mode="python")
    if release_base_version_id is not None:
        release_payload["knowledge_base_version_id"] = release_base_version_id
    return KnowledgeServiceManagementWorkspace(
        readiness=KnowledgeServiceReadinessProjection(
            state=readiness_state,
            revision=catalog_revision,
        ),
        spaces=(),
        sources=(),
        bases=(),
        source_versions=(),
        releases=(
            KnowledgeServiceReleaseProjection(
                **release_payload,
                source_version_count=3,
                state=release_state,
            ),
        ),
    )


def _binding_profile() -> ProductionKssBindingProfile:
    return ProductionKssBindingProfile(
        binding_id="production-kss-insurance",
        client_credential_ref=ProductionSecretHandle(
            protocol_id="vault-kv-v2",
            handle_id="proofagent/kss/client",
            purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
            version_id="secret-version-7",
        ),
        admission_scorer_id="proofagent-admission-scorer",
        admission_scorer_revision="scorer-v4",
    )


def _phase_f_evidence() -> KnowledgeReleaseEvidenceSet:
    return KnowledgeReleaseEvidenceSet(
        shadow=_artifact("shadow", "1"),
        capacity=_artifact("capacity", "2"),
        acceptance=_artifact("acceptance", "3"),
        recovery=_artifact("recovery", "4"),
    )


def _artifact(kind: str, digest_character: str) -> ExactArtifactRef:
    return ExactArtifactRef(
        artifact_uri=f"s3://proof-agent/phase-f/{kind}.json",
        version_id=f"opaque-{kind}-version",
        sha256=digest_character * 64,
        size_bytes=1024,
        media_type="application/json",
    )


def _model_connection() -> SharedModelConnection:
    return SharedModelConnection(
        connection_id="model_deepseek",
        display_name="DeepSeek",
        provider="deepseek",
        model_identifier="deepseek-chat",
        credential_ref=PostgresEncryptedModelCredentialReference(),
        lifecycle_state=SharedModelConnectionLifecycleState.ACTIVE,
        created_at="2026-08-20T00:00:00Z",
        updated_at="2026-08-20T00:00:00Z",
    )
