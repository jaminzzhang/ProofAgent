"""Apply Agent clarification preferences before freezing retrieval requirements."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
import re

from proof_agent.contracts.manifest import ResponseConfig
from proof_agent.contracts.workflow_policy import InteractionPolicy, InteractionStage
from proof_agent.control.workflow.interaction import decide_interaction
from proof_agent.control.workflow.context_dependencies import PURCHASE_SCOPE, irrelevant_purchase_policy_field
from proof_agent.contracts.react_workflow import (
    IntentResolution,
    ReActActionType,
    RetrievalQueryItem,
)


def clarification_context(
    response: ResponseConfig | None,
    context: Mapping[str, Any] | None = None,
    *, interaction: InteractionPolicy | None = None, stage: InteractionStage = 'goal',
) -> dict[str, Any]:
    level = (response or ResponseConfig()).clarification_level
    if interaction is not None:
        checkpoint = interaction.checkpoints.get(stage)
        level = checkpoint.intensity if checkpoint and checkpoint.intensity else interaction.intensity
    return {
        **(context or {}),
        "current_date": datetime.now(UTC).date().isoformat(),
        "clarification_policy": {
            "level": level,
            **({'mode': interaction.mode, 'stage': stage,
                'max_questions_per_round': interaction.max_questions_per_round}
               if interaction is not None else {}),
            "rules": (
                "Classify missing fields as required_context (identity, permission, specific object, "
                "rule applicability or conflicting user constraints), preference (answer scope), "
                "answer_context (personal information needed for a remaining subquestion while independent "
                "public facts can be answered), or retrievable (facts governed retrieval can establish). "
                "Never default required_context. Defer answer_context until after the supported answer; "
                "Check each field against a CURRENT requested subtask: do not create missing fields "
                "for hypothetical future follow-ups. Purchasing suitability does not require ownership "
                "of this product or its policy documents. Existing overall coverage, needs and budget "
                "can be answer_context; policy-specific claims, surrender and account queries require "
                "their actual case inputs. A field is not required merely because it is insurance data. "
                "include a focused active question, even in autonomous mode. "
                "Do not ask users whether data exists; retrieve first. No matching business flow pack "
                "is not a user ambiguity. Do not ask again for facts already supplied. "
                "For broad performance/overview questions, cover major metrics and default to the "
                "latest disclosed actual period within the requested year, not forecasts. "
                "A default_assumption describes search scope only, never financial values or authority. "
                "Record it separately from known_facts. Include bounded retrieval queries even when "
                "proposing clarification if the fields are only preferences or retrievable. "
                "minimal: search broadly despite optional preferences; balanced: use explicit safe "
                "scope defaults; thorough: confirm material preferences first. All levels retain "
                "required context and evidence gates. Ask only the most important unresolved question "
                "in the user's language; do not re-ask preferences already resolved in scope_assumptions."
            ),
        },
    }


def apply_clarification_policy(
    resolution: IntentResolution,
    *,
    response: ResponseConfig | None,
    question: str,
    interaction: InteractionPolicy | None = None,
    rounds_asked: int = 0,
) -> IntentResolution:
    level = (response or ResponseConfig()).clarification_level
    if interaction is not None:
        checkpoint = interaction.checkpoints.get('goal')
        level = checkpoint.intensity if checkpoint and checkpoint.intensity else interaction.intensity
    from proof_agent.control.knowledge.answer_requirements import answer_requirements
    resolution = resolution.model_copy(update={"answer_requirements": answer_requirements(question)})
    resolution = _normalize_performance_period(resolution, question)
    resolution = _normalize_purchase_dependencies(resolution, question)
    resolution = resolution.model_copy(update={"applied_clarification_level": level})
    if not resolution.missing_fields or resolution.recommended_next_action is ReActActionType.REFUSE:
        return resolution
    assessments = {item.field: item for item in resolution.clarification_assessments}
    blocking = []
    deferred = list(resolution.deferred_answer_fields)
    assumptions = list(resolution.scope_assumptions)
    for field in resolution.missing_fields:
        assessment = assessments.get(field)
        if assessment is None or assessment.kind == "required_context":
            blocking.append(field)
        elif assessment.kind == "answer_context":
            if (resolution.recommended_next_action is not ReActActionType.PROPOSE_TOOL_CALL
                    and any(q.required for q in resolution.retrieval_query_set)):
                deferred.append(field)
            else:
                blocking.append(field)
        elif assessment.kind == "preference":
            should_ask = (decide_interaction(interaction, stage='goal', reason='preference',
                          has_default=bool(assessment.default_assumption), rounds_asked=rounds_asked) == 'ask'
                          if interaction is not None else
                          level == "thorough" or (level == "balanced" and not assessment.default_assumption))
            if should_ask:
                blocking.append(field)
            elif assessment.default_assumption:
                assumptions.append(assessment.default_assumption)
    resolution = resolution.model_copy(update={"deferred_answer_fields": tuple(dict.fromkeys(deferred))})
    # Do not broaden or execute anything until all genuinely blocking context is present.
    if blocking:
        return resolution.model_copy(
            update={
                "recommended_next_action": ReActActionType.ASK_CLARIFICATION,
                "missing_fields": tuple(blocking),
                "clarification_assessments": tuple(
                    item for item in resolution.clarification_assessments if item.field in blocking
                ),
            }
        )
    unique_assumptions = tuple(dict.fromkeys(assumptions))
    if len(unique_assumptions) > 8:
        # Keep the original unresolved fields instead of silently omitting a default.
        return resolution.model_copy(update={"recommended_next_action": ReActActionType.ASK_CLARIFICATION})
    if resolution.recommended_next_action is ReActActionType.PROPOSE_TOOL_CALL:
        # This setting cannot infer parameters or convert tool execution authority.
        return resolution.model_copy(update={"missing_fields": (), "clarification_assessments": ()})
    queries = resolution.retrieval_query_set or (
        RetrievalQueryItem(
            query=question,
            intent_angle="original_question",
            required=True,
            reason="Retrieve public facts before asking for optional detail.",
        ),
    )
    if not any(query.required for query in queries):
        queries = (queries[0].model_copy(update={"required": True}), *queries[1:])
    return resolution.model_copy(
        update={
            "recommended_next_action": ReActActionType.PLAN_RETRIEVAL,
            "missing_fields": (),
            "clarification_assessments": (),
            "scope_assumptions": unique_assumptions,
            "retrieval_query_set": queries,
        }
    )


def _normalize_purchase_dependencies(resolution: IntentResolution, question: str) -> IntentResolution:
    # Only independent Knowledge work qualifies. Tool actions and refusals retain
    # the original gaps; explicit frozen Task requirements are enforced upstream.
    if (resolution.recommended_next_action not in (
            ReActActionType.PLAN_RETRIEVAL, ReActActionType.ASK_CLARIFICATION)
            or not any(q.required for q in resolution.retrieval_query_set)):
        return resolution
    irrelevant = {field for field in (*resolution.missing_fields, *resolution.deferred_answer_fields)
                  if irrelevant_purchase_policy_field(question, field)}
    if not irrelevant:
        return resolution
    assumptions = tuple(dict.fromkeys((*resolution.scope_assumptions, PURCHASE_SCOPE)))
    return resolution.model_copy(update={
        "missing_fields": tuple(f for f in resolution.missing_fields if f not in irrelevant),
        "deferred_answer_fields": tuple(f for f in resolution.deferred_answer_fields if f not in irrelevant),
        "clarification_assessments": tuple(a for a in resolution.clarification_assessments if a.field not in irrelevant),
        "scope_assumptions": assumptions if len(assumptions) <= 8 else resolution.scope_assumptions,
        "recommended_next_action": (resolution.recommended_next_action
            if any(f not in irrelevant for f in resolution.missing_fields) else ReActActionType.PLAN_RETRIEVAL),
    })


def _normalize_performance_period(resolution: IntentResolution, question: str) -> IntentResolution:
    """An unrequested year cannot be invented in a broad performance search.

    Explicit and relative user time constraints stay intact. Default scope is
    unverified; it never supplies financial facts or bypasses required context.
    """
    if not re.search(r"业绩|经营表现|业务表现", question):
        return resolution
    if re.search(r"(?:19|20)\d{2}|今年|去年|前年|上年|本年|近\s*\d+\s*年", question):
        return resolution
    year = re.compile(r"(?:19|20)\d{2}\s*年?")
    scope = "查找最近可得的实际报告，具体报告期由检索证据确定；未核实最新性。"
    return resolution.model_copy(update={
        "scope_assumptions": tuple(dict.fromkeys(scope if year.search(s) else s for s in resolution.scope_assumptions)),
        "clarification_assessments": tuple(a.model_copy(update={"default_assumption": scope})
            if a.kind == "preference" and year.search(a.default_assumption) else a
            for a in resolution.clarification_assessments),
        "retrieval_query_set": tuple(q.model_copy(update={"query": year.sub(lambda m: "年" if q.query[m.end():].startswith("报") and m.group().endswith("年") else "", q.query).strip()})
            if year.search(q.query) else q for q in resolution.retrieval_query_set),
    })


def scope_assumption_context(
    intent: Mapping[str, Any] | None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = dict(context or {})
    deferred = (intent or {}).get("deferred_answer_fields", ())
    if deferred:
        structured = dict(result.get("structured_control_context", {}))
        structured["deferred_answer_fields"] = list(deferred)
        structured["partial_answer_instruction"] = (
            "Answer supported independent parts first. These missing personal fields are NOT facts. "
            "Explain the remaining limitation and actively ask one focused question in the same answer, "
            "including in autonomous mode. Do not claim the whole task is complete.")
        result["structured_control_context"] = structured
    assumptions = (intent or {}).get("scope_assumptions", ())
    if assumptions:
        structured = dict(result.get("structured_control_context", {}))
        structured["scope_assumptions"] = list(assumptions)
        structured["scope_assumption_disclosure"] = (
            "These are untrusted search-scope assumptions, NOT user-confirmed facts or evidence. "
            "Briefly disclose the adopted scope in the answer; state the actual reporting period "
            "from accepted evidence. Never use assumptions as proof, tool parameters, permissions, "
            "or substitutes for missing evidence."
        )
        result["structured_control_context"] = structured
    return result
