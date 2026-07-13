"""Immutable runtime identity for approved insurance rule-unit revisions."""

from __future__ import annotations

import hashlib
import json

from proof_agent.capabilities.knowledge.hybrid.rule_units import InsuranceRuleUnitDraft
from proof_agent.contracts.insurance_rules import (
    ApprovedInsuranceKnowledgeVisibilityScope,
    ApprovedInsuranceRuleMetadataRevision,
    InsuranceRuleUnitRevision,
)


def materialize_rule_unit_revision(
    draft: InsuranceRuleUnitDraft,
    *,
    approved_metadata: ApprovedInsuranceRuleMetadataRevision,
    approved_visibility: ApprovedInsuranceKnowledgeVisibilityScope,
) -> InsuranceRuleUnitRevision:
    """Materialize one approved revision; the review-only logical key is not its identity."""

    # Revalidate inputs so model_copy/model_construct cannot bypass lineage validators at the
    # identity boundary.
    draft = InsuranceRuleUnitDraft.model_validate(draft.model_dump())
    approved_metadata = ApprovedInsuranceRuleMetadataRevision.model_validate(
        approved_metadata.model_dump()
    )
    approved_visibility = ApprovedInsuranceKnowledgeVisibilityScope.model_validate(
        approved_visibility.model_dump()
    )
    content_sha256 = _sha256_text(draft.content)
    authority_payload = {
        "approved_metadata": approved_metadata.model_dump(mode="json"),
        "approved_visibility": approved_visibility.model_dump(mode="json"),
    }
    authority_sha256 = _sha256_json(authority_payload)
    projection_payload = draft.model_dump(
        mode="json",
        exclude={"logical_rule_key", "inherited_metadata", "ordinal"},
    )
    identity_payload = {
        "schema_version": "insurance-rule-unit-revision.v1",
        "projection": projection_payload,
        "content_sha256": content_sha256,
        "structured_build_identity": draft.structured_build_identity.model_dump(mode="json"),
        "approved_metadata": approved_metadata.model_dump(mode="json"),
        "approved_visibility": approved_visibility.model_dump(mode="json"),
    }
    revision_id = f"rur-{_sha256_json(identity_payload)}"
    return InsuranceRuleUnitRevision(
        rule_unit_revision_id=revision_id,
        logical_rule_key=draft.logical_rule_key,
        unit_kind=draft.unit_kind,
        document_id=draft.document_id,
        revision_id=draft.revision_id,
        structured_build_id=draft.structured_build_id,
        content=draft.content,
        citation_uri=draft.citation_uri,
        metadata_revision_id=approved_metadata.metadata_revision_id,
        visibility_scope=approved_visibility,
        content_sha256=content_sha256,
        authority_sha256=authority_sha256,
    )


def rule_unit_revision_fingerprint(
    draft: InsuranceRuleUnitDraft,
    *,
    approved_metadata: ApprovedInsuranceRuleMetadataRevision,
    approved_visibility: ApprovedInsuranceKnowledgeVisibilityScope,
) -> str:
    """Return the immutable revision identity without exposing review-key semantics."""

    return materialize_rule_unit_revision(
        draft,
        approved_metadata=approved_metadata,
        approved_visibility=approved_visibility,
    ).rule_unit_revision_id


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = ["materialize_rule_unit_revision", "rule_unit_revision_fingerprint"]
