"""Evidence-qualified assurance; no model confidence is a correctness probability."""
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any
from unicodedata import normalize
from proof_agent.contracts import EvidenceChunk, EvidenceStatus, ReceiptOutcome, ValidationResult, ValidationStatus
from proof_agent.contracts.workflow_policy import AssurancePolicy
from proof_agent.control.validators.answer_facts import validate_answer_facts


@dataclass(frozen=True)
class AssuranceAssessment:
    violations: tuple[str, ...]
    source_count: int
    checked_claim_count: int
    unassessed_claim_count: int
    verification_kind: str = "bounded_consistency_only"

    @property
    def passed(self) -> bool:
        return not self.violations

    def projection(self) -> dict[str, Any]:
        return {'status': 'passed' if self.passed else 'blocked',
                'violations': list(self.violations), 'source_count': self.source_count,
                'checked_claim_count': self.checked_claim_count,
                'unassessed_claim_count': self.unassessed_claim_count,
                'verification_kind': self.verification_kind}


def requires_external_sources(policy: AssurancePolicy) -> bool:
    """Verified tool reports satisfy baseline provenance; source-specific additions do not."""
    return any(requirement.min_sources > 1 or requirement.max_age_days is not None or requirement.required_metadata
               for requirement in (policy.evidence, *policy.checkpoints.values()))


def _source_count(evidence: tuple[EvidenceChunk, ...]) -> int:
    # Multiple chunks share one source; exact republications share one content
    # component even with different provider identities. This is conservative
    # deduplication, not a claim of independent editorial provenance.
    parents: dict[str, str] = {}

    def root(key: str) -> str:
        parents.setdefault(key, key)
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    source_keys = set()
    for item in evidence:
        source = (item.source_id or item.source).strip()
        content = ' '.join(normalize('NFKC', item.content).casefold().split())
        if not source or not content:
            continue
        key = f'source:{source}'
        source_keys.add(key)
        fingerprint = f'content:{sha256(content.encode()).hexdigest()}'
        parents[root(fingerprint)] = root(key)
    return len({root(key) for key in source_keys})


def evaluate_assurance(policy: AssurancePolicy, *, evidence: tuple[EvidenceChunk, ...],
                       message: str | None = None, today: date | None = None,
                       fact_validation: ValidationResult | None = None) -> AssuranceAssessment:
    today = today or datetime.now(UTC).date()
    accepted = tuple(item for item in evidence if item.status is EvidenceStatus.ACCEPTED)
    source_count = _source_count(accepted)
    # Checkpoint requirements accumulate. A later setting cannot erase a declared requirement.
    requirements = (policy.evidence, *policy.checkpoints.values())
    violations = []
    if source_count < max(requirement.min_sources for requirement in requirements):
        violations.append('insufficient_independent_sources')
    metadata_required = {key for requirement in requirements for key in requirement.required_metadata}
    max_ages = [requirement.max_age_days for requirement in requirements if requirement.max_age_days is not None]
    for item in accepted:
        if not item.citation or not item.source:
            violations.append('source_binding_incomplete')
        metadata = item.metadata
        values = {'source_id': item.source_id, 'document_version': item.revision_id or item.source_version_id,
                  'effective_date': metadata.get('effective_date')}
        if any(not values[key] for key in metadata_required):
            violations.append('required_source_metadata_missing')
        if metadata.get('applicability') in ('unknown', 'unresolved', 'inapplicable', False):
            violations.append('applicability_unresolved')
        if metadata.get('conflict') is True or metadata.get('evidence_conflict') in ('unresolved', True):
            violations.append('evidence_conflict_unresolved')
        if max_ages:
            try:
                effective_date = date.fromisoformat(str(metadata.get('effective_date', ''))[:10])
            except ValueError:
                violations.append('source_date_unavailable')
            else:
                if not 0 <= (today - effective_date).days <= min(max_ages):
                    violations.append('source_expired_or_future')
    checked = unassessed = 0
    verification_kind = "bounded_consistency_only"
    if message is not None:
        from proof_agent.control.validators.quoted_answer import answer_binding
        if fact_validation is not None:
            binding = answer_binding(message, accepted)
            valid = (fact_validation.status is ValidationStatus.PASSED
                     and fact_validation.metadata.get("verification_kind") == "quote_binding_and_model_review"
                     and all(fact_validation.metadata.get(k) == v for k, v in binding.items()))
            if not valid:
                violations.append("answer_grounding_binding_invalid")
            facts = fact_validation
            verification_kind = "quote_binding_and_model_review"
        else:
            facts = validate_answer_facts(message=message,
                    citations=tuple(item.citation for item in accepted if item.citation),
                    evidence=accepted, outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS)
        checked = int(facts.metadata.get('checked_statement_count', 0))
        unassessed = int(facts.metadata.get('unassessed_statement_count', 0))
        if facts.status is not ValidationStatus.PASSED:
            violations.append('answer_fact_validation_failed')
        if policy.level == 'strict' and (unassessed or not checked):
            violations.append('required_claim_unassessed')
    return AssuranceAssessment(tuple(dict.fromkeys(violations)), source_count, checked, unassessed, verification_kind)
