"""Apply Agent clarification preferences before freezing retrieval requirements."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from proof_agent.contracts.manifest import ResponseConfig
from proof_agent.contracts.react_workflow import (
    IntentResolution,
    ReActActionType,
    RetrievalQueryItem,
)


def clarification_context(
    response: ResponseConfig | None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    level = (response or ResponseConfig()).clarification_level
    return {
        **(context or {}),
        "current_date": datetime.now(UTC).date().isoformat(),
        "clarification_policy": {
            "level": level,
            "rules": (
                "Classify missing fields as required_context (identity, permission, specific object, "
                "rule applicability or conflicting user constraints), preference (answer scope), "
                "or retrievable (facts governed retrieval can establish). Never default required_context. "
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
) -> IntentResolution:
    level = (response or ResponseConfig()).clarification_level
    resolution = resolution.model_copy(update={"applied_clarification_level": level})
    if not resolution.missing_fields or resolution.recommended_next_action is ReActActionType.REFUSE:
        return resolution
    assessments = {item.field: item for item in resolution.clarification_assessments}
    blocking = []
    assumptions = list(resolution.scope_assumptions)
    for field in resolution.missing_fields:
        assessment = assessments.get(field)
        if assessment is None or assessment.kind == "required_context":
            blocking.append(field)
        elif assessment.kind == "preference":
            if level == "thorough" or (level == "balanced" and not assessment.default_assumption):
                blocking.append(field)
            elif assessment.default_assumption:
                assumptions.append(assessment.default_assumption)
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


def scope_assumption_context(
    intent: Mapping[str, Any] | None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = dict(context or {})
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
