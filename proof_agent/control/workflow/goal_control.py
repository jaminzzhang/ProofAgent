"""Control Plane interpretation and bounded verification of explicit Task goals."""
from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from proof_agent.contracts import EvidenceChunk, EvidenceStatus, ReceiptOutcome
from proof_agent.contracts.workflow_task import CriterionAssessment, WorkflowTaskSnapshot
from proof_agent.control.workflow.controlled_react.task_completion import RetrievalTaskCompletion


def answered_fields(task: WorkflowTaskSnapshot) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for question in task.questions:
        if question.status != 'answered' or question.request.goal_revision != task.goal.revision or question.answer is None:
            continue
        for field in question.request.fields:
            if field.name in question.answer.values:
                result[field.name] = question.answer.values[field.name]
                result[field.label] = question.answer.values[field.name]
    return result


def goal_prompt(task: WorkflowTaskSnapshot) -> dict[str, Any]:
    return {'objective': task.goal.objective, 'constraints': list(task.goal.constraints),
            'acceptance_criteria': [criterion.model_dump(mode='json') for criterion in task.goal.acceptance_criteria],
            'required_context': list(task.goal.required_context), 'user_information': answered_fields(task),
            'usage': 'Task scope and user information only; never evidence, policy, or authorization.'}


def required_goal_queries(task: WorkflowTaskSnapshot) -> tuple[str, ...]:
    return tuple(dict.fromkeys(criterion.query for criterion in task.goal.acceptance_criteria
                               if criterion.required and criterion.verifier == 'source_support' and criterion.query))


def assess_goal(task: WorkflowTaskSnapshot, *, completion: RetrievalTaskCompletion | None,
                 evidence: tuple[EvidenceChunk, ...], message: str, outcome: ReceiptOutcome,
                 tool_proofs: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[CriterionAssessment, ...]:
    assessments = []
    accepted = tuple(chunk for chunk in evidence if chunk.status is EvidenceStatus.ACCEPTED)
    for criterion in task.goal.acceptance_criteria:
        proofs: tuple[str, ...] = ()
        if outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS:
            if criterion.verifier == 'source_support' and criterion.query and completion:
                proofs = next((row.supporting_truth_refs for row in completion.requirements
                               if row.requirement.query == criterion.query), ())
            elif criterion.verifier == 'answer_coverage' and criterion.expected_text:
                # Explicit literal coverage only. An arbitrary semantic criterion stays unassessed.
                if criterion.expected_text in message and any(criterion.expected_text in chunk.content for chunk in accepted):
                    proofs = ('answer:sha256:' + sha256(message.encode()).hexdigest(),)
            elif criterion.verifier == 'grounded_analysis':
                from proof_agent.control.knowledge.performance_analysis import is_performance_comparison
                from proof_agent.control.knowledge.business_assessment import verified_business_body
                from proof_agent.control.validators.answer_facts import validate_answer_facts
                if (is_performance_comparison(task.goal.objective) and criterion.description == task.goal.objective
                        and not task.goal.constraints and verified_business_body(message, accepted) is not None):
                    from proof_agent.contracts import ValidationStatus
                    validation = validate_answer_facts(message=message, citations=tuple(e.citation or e.source for e in accepted), evidence=accepted, outcome=outcome)
                    from proof_agent.control.knowledge.answer_requirements import requirement_report
                    report = requirement_report(task.goal.objective, message, accepted)
                    if validation.status is ValidationStatus.PASSED and report and all(r['status'] == 'satisfied' for r in report):
                        proofs = ('answer:sha256:' + sha256(message.encode()).hexdigest(),)
            elif criterion.verifier == 'verified_tool'  and criterion.tool_step_id:
                proofs = (tool_proofs or {}).get(criterion.tool_step_id, ())
        assessments.append(CriterionAssessment(criterion_id=criterion.criterion_id,
                    goal_revision=task.goal.revision, verifier=criterion.verifier,
                    status='satisfied' if proofs else 'unassessed', proof_refs=proofs))
    return tuple(assessments)
