"""User-bound requirements shared by planning and answering; no model confidence proof."""
from hashlib import sha256
import re
from typing import Literal

from proof_agent.contracts.answer_requirements import AnswerRequirement
from proof_agent.contracts.workflow_task import GoalContract
from proof_agent.contracts.evidence import EvidenceChunk



def answer_requirements(question: str) -> tuple[AnswerRequirement, ...]:
    # Split only explicit user clauses. Do not invent entities, time or unstated goals.
    if len(question) > 8192:
        from proof_agent.errors import ProofAgentError
        raise ProofAgentError("PA_RUNTIME_001", "Answer requirements exceed the supported input size.", "Split the question into bounded tasks.")
    parts = [s.strip() for s in re.split(r'[，,。；;？?\n]+', question) if s.strip()]
    if not parts:
        return ()
    if len(parts) > 16:
        parts = [question]
    result = []
    for part in dict.fromkeys(parts):
        kind: Literal['highlights', 'strengths', 'pressures', 'question'] = 'question'
        if re.search(r'亮点|优势', part):
            kind = 'highlights'
        elif re.search(r'较好|比较好', part):
            kind = 'strengths'
        elif re.search(r'较差|比较差|弱项|不足|压力|劣势|下滑', part):
            kind = 'pressures'
        result.append(AnswerRequirement(requirement_id='ar_' + sha256(part.encode()).hexdigest()[:16], source_text=part, kind=kind))
    return tuple(result)


def requirement_payload(question: str) -> list[dict[str, str]]:
    return [r.model_dump() for r in answer_requirements(question)]


def compile_goal_requirements(goal: GoalContract, *, previous_goal: GoalContract | None = None) -> GoalContract:
    """Add the supported objective's acceptance check, not a new user objective."""
    from proof_agent.contracts.workflow_task import GoalContract, AcceptanceCriterion
    from proof_agent.contracts.persistence import PersistenceInvariantError
    from proof_agent.control.knowledge.performance_analysis import is_performance_comparison
    reserved = tuple(c for c in goal.acceptance_criteria if c.criterion_id == 'proofagent-answer-contract')
    if reserved and (previous_goal is None or any(c not in previous_goal.acceptance_criteria for c in reserved)):
        raise PersistenceInvariantError('proofagent-answer-contract is reserved for the control-owned objective check')
    criteria = tuple(c for c in goal.acceptance_criteria if c.criterion_id != 'proofagent-answer-contract')
    if is_performance_comparison(goal.objective):
        if len(criteria) >= 32:
            raise PersistenceInvariantError('analysis tasks allow at most 31 custom criteria plus the objective check')
        criteria += (AcceptanceCriterion(criterion_id='proofagent-answer-contract', description=goal.objective,
                                         verifier='grounded_analysis', required=True),)
    return GoalContract.model_validate({**goal.model_dump(mode='python'), 'acceptance_criteria': criteria})


def requirement_report(question: str, message: str, evidence: tuple[EvidenceChunk, ...]) -> tuple[dict[str, str], ...]:
    """Report bounded completion separately from source/fact validity."""
    from proof_agent.control.knowledge.business_assessment import verified_business_body
    from proof_agent.control.knowledge.performance_analysis import is_performance_comparison, performance_coverage
    body = verified_business_body(message, evidence) if is_performance_comparison(question) else None
    coverage = performance_coverage(body) if body is not None else frozenset()
    rows = []
    for r in answer_requirements(question):
        direction = 'strengths' if r.kind == 'highlights' else r.kind
        satisfied = body is not None and direction in coverage and 'period' in coverage
        rows.append({'requirement_id': r.requirement_id, 'status': 'satisfied' if satisfied else 'unassessed',
                     'verification_kind': 'bounded_domain_profile' if body is not None else 'unassessed'})
    return tuple(rows)
