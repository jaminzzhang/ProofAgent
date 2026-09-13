"""Local Draft inspection adapter for Workflow Stage configuration."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.compiler import compile_draft_agent
from proof_agent.contracts import DraftAgent
from proof_agent.control.agent_configuration_workspace import (
    AgentConfigurationWorkflowStageDraftFacts,
)
from proof_agent.control.workflow.execution_compiler import compile_manifest_execution


class LocalAgentConfigurationWorkflowStageAdapter:
    """Compile one Draft candidate and return bounded manifest facts."""

    def inspect(
        self,
        *,
        draft: DraftAgent,
    ) -> AgentConfigurationWorkflowStageDraftFacts:
        with TemporaryDirectory(prefix="proof-agent-workflow-stage-") as temporary_dir:
            package_dir = compile_draft_agent(draft, Path(temporary_dir))
            manifest = load_agent_manifest(package_dir / "agent.yaml")
            tool_contract_reference = (
                _package_reference(
                    manifest.capabilities.tools.file,
                    package_dir=package_dir,
                )
                if manifest.capabilities.tools.enabled
                and manifest.capabilities.tools.file is not None
                else ""
            )
            return AgentConfigurationWorkflowStageDraftFacts(
                template_name=manifest.workflow.template,
                agent_purpose=manifest.purpose,
                tool_contract_reference=tool_contract_reference,
                policy_reference=_package_reference(
                    manifest.policy.file,
                    package_dir=package_dir,
                ),
                response_disclosure_policy=(
                    manifest.response.model_dump(mode="json")
                    if manifest.response is not None
                    else {}
                ),
                memory_scope={
                    "enabled": manifest.capabilities.memory.enabled,
                    "provider": manifest.capabilities.memory.provider,
                    "scopes": dict(manifest.capabilities.memory.scopes),
                },
                execution_plan=compile_manifest_execution(manifest),
            )


def _package_reference(reference: Path, *, package_dir: Path) -> str:
    candidate = reference if reference.is_absolute() else package_dir / reference
    try:
        return candidate.resolve().relative_to(package_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("compiled manifest reference must stay inside its package") from exc
