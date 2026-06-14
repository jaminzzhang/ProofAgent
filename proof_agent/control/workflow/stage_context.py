from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from proof_agent.contracts import WorkflowStagePromptConfig
from proof_agent.control.workflow.templates import WorkflowTemplate
from proof_agent.errors import ProofAgentError


_SECRET_TEXT_PATTERNS = (
    re.compile(r"\bSECRET-[A-Za-z0-9_.-]+\b", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|access[_-]?token|bearer|password)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\bsecret\s+token\s+\S+", re.IGNORECASE),
)


def build_workflow_stage_context_preview(
    *,
    descriptor: WorkflowTemplate,
    stage_id: str,
    prompt: Mapping[str, Any] | WorkflowStagePromptConfig,
    context_options: Mapping[str, bool],
    sample_context: Mapping[str, Any],
) -> dict[str, Any]:
    """Render a redacted Workflow Stage Context Preview without executing the stage."""

    stage = descriptor.stage(stage_id)
    unsupported_context_options = sorted(
        option for option in context_options if option not in stage.context_options
    )
    if unsupported_context_options:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported context option for workflow stage {stage_id}: {', '.join(unsupported_context_options)}",
            f"Use context options: {', '.join(stage.context_options)}.",
        )

    normalized_prompt = _normalize_prompt(prompt)
    addendum, prompt_redacted = _business_context_addendum(normalized_prompt)
    structured_context, context_redacted = _selected_structured_context(
        context_options,
        sample_context,
    )
    prompt_fields = _prompt_fields(normalized_prompt)
    selected_context_options = sorted(
        option for option, enabled in context_options.items() if enabled
    )
    summary = {
        "stage_id": stage_id,
        "prompt_fields": prompt_fields,
        "context_options": selected_context_options,
        "business_context_length": len(normalized_prompt.business_context),
        "task_instruction_count": len(normalized_prompt.task_instructions),
        "output_preference_count": len(normalized_prompt.output_preferences),
        "redaction_applied": prompt_redacted or context_redacted,
    }
    return {
        "stage_id": stage_id,
        "stage_label": stage.label,
        "harness_control_prompt_summary": (
            "Harness control prompt is locked by Proof Agent and is not replaced by "
            "Workflow Stage Prompt Configuration."
        ),
        "structured_control_context": structured_context,
        "business_context_addendum": {
            "present": bool(addendum),
            "text": addendum,
            "fields": prompt_fields,
        },
        "summary": summary,
    }


def workflow_stage_context_summary(preview: Mapping[str, Any]) -> dict[str, Any]:
    """Return the trace-safe summary portion of a rendered stage context preview."""

    summary = preview.get("summary")
    if not isinstance(summary, Mapping):
        return {
            "stage_id": str(preview.get("stage_id", "")),
            "prompt_fields": [],
            "context_options": [],
            "business_context_length": 0,
            "task_instruction_count": 0,
            "output_preference_count": 0,
            "redaction_applied": False,
        }
    return {
        "stage_id": str(summary.get("stage_id", "")),
        "prompt_fields": list(summary.get("prompt_fields", [])),
        "context_options": list(summary.get("context_options", [])),
        "business_context_length": int(summary.get("business_context_length", 0)),
        "task_instruction_count": int(summary.get("task_instruction_count", 0)),
        "output_preference_count": int(summary.get("output_preference_count", 0)),
        "redaction_applied": bool(summary.get("redaction_applied", False)),
    }


def _normalize_prompt(
    prompt: Mapping[str, Any] | WorkflowStagePromptConfig,
) -> WorkflowStagePromptConfig:
    if isinstance(prompt, WorkflowStagePromptConfig):
        return prompt
    return WorkflowStagePromptConfig(
        business_context=str(prompt.get("business_context", "") or ""),
        task_instructions=tuple(
            str(item) for item in prompt.get("task_instructions", ()) or ()
        ),
        output_preferences=tuple(
            str(item) for item in prompt.get("output_preferences", ()) or ()
        ),
    )


def _business_context_addendum(prompt: WorkflowStagePromptConfig) -> tuple[str, bool]:
    lines: list[str] = []
    if prompt.business_context:
        lines.append("Business context:")
        lines.append(prompt.business_context)
    if prompt.task_instructions:
        lines.append("Task instructions:")
        lines.extend(f"- {item}" for item in prompt.task_instructions)
    if prompt.output_preferences:
        lines.append("Output preferences:")
        lines.extend(f"- {item}" for item in prompt.output_preferences)
    return _redact_text("\n".join(lines))


def _selected_structured_context(
    context_options: Mapping[str, bool],
    sample_context: Mapping[str, Any],
) -> tuple[dict[str, Any], bool]:
    selected: dict[str, Any] = {}
    redaction_applied = False
    for option, enabled in sorted(context_options.items()):
        if not enabled:
            continue
        key = option.removeprefix("include_")
        value, redacted = _redact_value(sample_context.get(key, ""))
        selected[option] = value
        redaction_applied = redaction_applied or redacted
    return selected, redaction_applied


def _prompt_fields(prompt: WorkflowStagePromptConfig) -> list[str]:
    fields: list[str] = []
    if prompt.business_context:
        fields.append("business_context")
    if prompt.task_instructions:
        fields.append("task_instructions")
    if prompt.output_preferences:
        fields.append("output_preferences")
    return fields


def _redact_value(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Mapping):
        redaction_applied = False
        mapping_result: dict[str, Any] = {}
        for key, item in value.items():
            redacted_item, redacted = _redact_value(item)
            mapping_result[str(key)] = redacted_item
            redaction_applied = redaction_applied or redacted
        return mapping_result, redaction_applied
    if isinstance(value, list | tuple):
        redaction_applied = False
        list_result: list[Any] = []
        for item in value:
            redacted_item, redacted = _redact_value(item)
            list_result.append(redacted_item)
            redaction_applied = redaction_applied or redacted
        return list_result, redaction_applied
    return value, False


def _redact_text(value: str) -> tuple[str, bool]:
    redacted = value
    for pattern in _SECRET_TEXT_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted, redacted != value
