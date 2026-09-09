"""Control-owned validation for bounded Workflow Stage Prompt configuration."""

from __future__ import annotations

from pathlib import Path

from proof_agent.contracts import WorkflowStagePromptConfig
from proof_agent.control.workflow.templates import WorkflowStageDescriptor
from proof_agent.errors import ProofAgentError


# The unified Dashboard Prompt uses business_context as its compatibility carrier.
MAX_WORKFLOW_STAGE_BUSINESS_CONTEXT_CHARS = 12000
MAX_WORKFLOW_STAGE_INSTRUCTION_COUNT = 10
MAX_WORKFLOW_STAGE_INSTRUCTION_CHARS = 500
MAX_WORKFLOW_STAGE_OUTPUT_PREFERENCE_COUNT = 10
MAX_WORKFLOW_STAGE_OUTPUT_PREFERENCE_CHARS = 300
MAX_WORKFLOW_STAGE_TOTAL_PROMPT_CHARS = 12000
FORBIDDEN_WORKFLOW_STAGE_PROMPT_PHRASES = (
    "system_prompt",
    "developer_prompt",
    "ignore policy",
    "bypass approval",
    "reveal chain-of-thought",
    "ignore evidence",
    "call tool directly",
    "override validator",
)
FORBIDDEN_WORKFLOW_STAGE_PROMPT_SECRET_PARTS = (
    "api_key",
    "authorization",
    "bearer",
    "password",
    "secret",
    "access_token",
)


def validate_workflow_stage_prompt_config(
    *,
    stage_id: str,
    prompt: WorkflowStagePromptConfig,
    stage_descriptor: WorkflowStageDescriptor,
    manifest_path: Path | None = None,
) -> int:
    """Validate one Workflow Stage Prompt against descriptor and safety limits."""

    configured_prompt_fields = _configured_workflow_prompt_fields(prompt)
    unsupported_prompt_fields = sorted(
        field
        for field in configured_prompt_fields
        if field not in stage_descriptor.editable_prompt_fields
    )
    if unsupported_prompt_fields:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported prompt field for workflow stage {stage_id}: {', '.join(unsupported_prompt_fields)}",
            f"Use editable Prompt fields: {', '.join(stage_descriptor.editable_prompt_fields)}.",
            artifact_path=manifest_path,
        )

    prompt_chars = _validate_workflow_stage_prompt_text(
        stage_id,
        prompt.business_context,
        "business_context",
        MAX_WORKFLOW_STAGE_BUSINESS_CONTEXT_CHARS,
        manifest_path=manifest_path,
    )
    if len(prompt.task_instructions) > MAX_WORKFLOW_STAGE_INSTRUCTION_COUNT:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"workflow stage {stage_id} task_instructions has too many items",
            f"Use at most {MAX_WORKFLOW_STAGE_INSTRUCTION_COUNT} task_instructions.",
            artifact_path=manifest_path,
        )
    for instruction in prompt.task_instructions:
        prompt_chars += _validate_workflow_stage_prompt_text(
            stage_id,
            instruction,
            "task_instructions",
            MAX_WORKFLOW_STAGE_INSTRUCTION_CHARS,
            manifest_path=manifest_path,
        )
    if len(prompt.output_preferences) > MAX_WORKFLOW_STAGE_OUTPUT_PREFERENCE_COUNT:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"workflow stage {stage_id} output_preferences has too many items",
            f"Use at most {MAX_WORKFLOW_STAGE_OUTPUT_PREFERENCE_COUNT} output_preferences.",
            artifact_path=manifest_path,
        )
    for preference in prompt.output_preferences:
        prompt_chars += _validate_workflow_stage_prompt_text(
            stage_id,
            preference,
            "output_preferences",
            MAX_WORKFLOW_STAGE_OUTPUT_PREFERENCE_CHARS,
            manifest_path=manifest_path,
        )
    return prompt_chars


def _configured_workflow_prompt_fields(prompt: object) -> tuple[str, ...]:
    fields: list[str] = []
    if getattr(prompt, "business_context", ""):
        fields.append("business_context")
    if getattr(prompt, "task_instructions", ()):
        fields.append("task_instructions")
    if getattr(prompt, "output_preferences", ()):
        fields.append("output_preferences")
    return tuple(fields)


def _validate_workflow_stage_prompt_text(
    stage_id: str,
    value: str,
    field_name: str,
    max_chars: int,
    *,
    manifest_path: Path | None,
) -> int:
    if len(value) > max_chars:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"workflow stage {stage_id} {field_name} exceeds size limit",
            f"Use at most {max_chars} characters for {field_name}.",
            artifact_path=manifest_path,
        )
    normalized = value.lower()
    if any(phrase in normalized for phrase in FORBIDDEN_WORKFLOW_STAGE_PROMPT_PHRASES):
        raise ProofAgentError(
            "PA_CONFIG_002",
            "workflow stage prompt contains forbidden governance override language",
            (
                "Remove instructions that override Harness prompts, policy, approval, "
                "evidence, validators, tools, or chain-of-thought boundaries."
            ),
            artifact_path=manifest_path,
        )
    if any(part in normalized for part in FORBIDDEN_WORKFLOW_STAGE_PROMPT_SECRET_PARTS):
        raise ProofAgentError(
            "PA_CONFIG_002",
            "workflow stage prompt contains secret-looking text",
            "Remove secrets and credential-like values from workflow stage Prompt configuration.",
            artifact_path=manifest_path,
        )
    return len(value)
