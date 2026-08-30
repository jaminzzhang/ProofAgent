"""Read-only assembly of one exact Formal Production Agent Candidate."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Protocol

from proof_agent.configuration.knowledge_release import (
    knowledge_release_candidate_sha256,
)
from proof_agent.contracts import (
    FormalProductionAgentCandidate,
    ProductionKssBindingProfile,
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
)
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceManagementWorkspace,
)
from proof_agent.contracts.ports import ConfigurationUnitOfWork
from proof_agent.control.production_agent_publication import SOLE_PRODUCTION_AGENT_ID
from proof_agent.control.production_agent_publication_configuration import (
    ProductionAgentPublicationConfigurationProjector,
)


class FormalProductionKnowledgeReleaseCatalog(Protocol):
    """Read the current KSS catalog without claiming KSS lifecycle authority."""

    def workspace(self) -> KnowledgeServiceManagementWorkspace: ...


class FormalProductionAgentCandidateRejected(RuntimeError):
    """Stable fail-closed rejection before any formal publication side effect."""

    def __init__(
        self,
        *,
        code: str,
        detail: str,
        blocker_codes: tuple[str, ...] = (),
    ) -> None:
        self.code = code
        self.detail = detail
        self.blocker_codes = blocker_codes
        super().__init__(detail)


class FormalProductionAgentCandidateAssembler:
    """Bind one exact stored Draft to live KSS facts and deployment-owned profile."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], ConfigurationUnitOfWork],
        knowledge_release_catalog: FormalProductionKnowledgeReleaseCatalog,
        publication_configuration_projector: ProductionAgentPublicationConfigurationProjector,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._knowledge_release_catalog = knowledge_release_catalog
        self._publication_configuration_projector = publication_configuration_projector

    def assemble(
        self,
        *,
        agent_id: str,
        draft_id: str,
        draft_revision: int,
        binding_profile: ProductionKssBindingProfile,
    ) -> FormalProductionAgentCandidate:
        if agent_id != SOLE_PRODUCTION_AGENT_ID:
            raise FormalProductionAgentCandidateRejected(
                code="formal_candidate_agent_not_found",
                detail="The requested production Agent was not found.",
            )
        if not draft_id.strip():
            raise ValueError("draft_id must not be empty")
        if isinstance(draft_revision, bool) or draft_revision < 1:
            raise ValueError("draft_revision must be at least one")

        with self._unit_of_work_factory() as uow:
            record = uow.agents.get_draft(agent_id, draft_id)
        if record is None:
            raise FormalProductionAgentCandidateRejected(
                code="formal_candidate_draft_not_found",
                detail="The requested Agent Draft was not found.",
            )
        if record.revision != draft_revision:
            raise FormalProductionAgentCandidateRejected(
                code="formal_candidate_draft_revision_conflict",
                detail="The Agent Draft changed; reload it before formal publication.",
            )

        try:
            catalog = self._knowledge_release_catalog.workspace()
        except Exception as exc:
            raise FormalProductionAgentCandidateRejected(
                code="formal_candidate_catalog_unavailable",
                detail="The live KSS Release catalog is unavailable.",
            ) from exc
        catalog_revision = catalog.readiness.revision
        if catalog.readiness.state != "ready" or catalog_revision is None:
            raise FormalProductionAgentCandidateRejected(
                code="formal_candidate_catalog_unavailable",
                detail="The live KSS Release catalog is unavailable.",
            )

        projection = self._publication_configuration_projector.project(
            draft=record.draft,
            revision=record.revision,
            catalog=catalog,
        )
        release_candidate = projection.knowledge_release_candidate
        if (
            projection.authoring_configuration_state != "ready"
            or not projection.knowledge_release_queryable
            or release_candidate is None
        ):
            raise FormalProductionAgentCandidateRejected(
                code="formal_candidate_authoring_blocked",
                detail="The Agent Draft is not admissible for formal publication.",
                blocker_codes=tuple(blocker.code for blocker in projection.configuration_blockers),
            )

        resolved_bindings = ResolvedKnowledgeBindingSet(
            bindings=(
                ResolvedKnowledgeSourceServiceBinding(
                    binding_id=binding_profile.binding_id,
                    knowledge_base_release_id=(release_candidate.knowledge_base_release_id),
                    client_credential_ref=binding_profile.client_credential_ref,
                    admission_scorer_id=binding_profile.admission_scorer_id,
                    admission_scorer_revision=(binding_profile.admission_scorer_revision),
                    failure_mode=binding_profile.failure_mode,
                ),
            )
        )
        release_candidate_sha256 = knowledge_release_candidate_sha256(
            record.draft.contract_bundle,
            resolved_bindings,
        )
        formal_candidate_sha256 = _formal_candidate_sha256(
            agent_id=record.draft.agent_id,
            draft_id=record.draft.draft_id,
            draft_revision=record.revision,
            display_name=record.draft.display_name,
            purpose=record.draft.purpose,
            contract_bundle=record.draft.contract_bundle.model_dump(mode="json"),
            knowledge_release_candidate=release_candidate.model_dump(mode="json"),
            knowledge_service_catalog_revision=catalog_revision,
            resolved_knowledge_bindings=resolved_bindings.model_dump(mode="json"),
            knowledge_release_candidate_sha256=release_candidate_sha256,
        )
        return FormalProductionAgentCandidate(
            agent_id=record.draft.agent_id,
            draft_id=record.draft.draft_id,
            draft_revision=record.revision,
            display_name=record.draft.display_name,
            purpose=record.draft.purpose,
            contract_bundle=record.draft.contract_bundle,
            knowledge_release_candidate=release_candidate,
            knowledge_service_catalog_revision=catalog_revision,
            resolved_knowledge_bindings=resolved_bindings,
            knowledge_release_candidate_sha256=release_candidate_sha256,
            formal_candidate_sha256=formal_candidate_sha256,
        )


def _formal_candidate_sha256(**payload: object) -> str:
    canonical = json.dumps(
        {
            "schema_version": "formal-production-agent-candidate.v1",
            **payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__ = [
    "FormalProductionAgentCandidateAssembler",
    "FormalProductionAgentCandidateRejected",
    "FormalProductionKnowledgeReleaseCatalog",
]
