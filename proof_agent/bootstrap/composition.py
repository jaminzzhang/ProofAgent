from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from proof_agent.capabilities.knowledge import KnowledgeProvider, resolve_knowledge_provider
from proof_agent.capabilities.memory.session import SessionMemory
from proof_agent.capabilities.models import ModelProvider, resolve_provider
from proof_agent.capabilities.tools.gateway import ToolGateway
from proof_agent.contracts import AgentManifest
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.workflow.templates import WorkflowTemplate, resolve_workflow_template
from proof_agent.bootstrap.loader import load_agent_manifest


DEFAULT_MEMORY_DENY_FIELDS = frozenset({"access_token", "customer_phone", "provider_api_key"})


@dataclass(frozen=True)
class HarnessInvocation:
    """Resolved dependencies for one governed Harness execution."""

    manifest_path: Path
    manifest: AgentManifest
    template: WorkflowTemplate
    policy: PolicyEngine
    knowledge_provider: KnowledgeProvider
    model_provider: ModelProvider
    tool_gateway: ToolGateway
    memory_deny_fields: frozenset[str] = DEFAULT_MEMORY_DENY_FIELDS

    def create_memory(self) -> SessionMemory:
        """Create per-run memory with the configured sensitivity boundary."""

        return SessionMemory(deny_fields=self.memory_deny_fields)


def compose_harness_invocation(
    agent_yaml: Path | str,
    *,
    manifest: AgentManifest | None = None,
) -> HarnessInvocation:
    """Resolve an Agent Contract into the dependencies needed to run it."""

    manifest_path = Path(agent_yaml).resolve()
    resolved_manifest = manifest or load_agent_manifest(manifest_path)
    template = resolve_workflow_template(resolved_manifest.workflow.template)
    return HarnessInvocation(
        manifest_path=manifest_path,
        manifest=resolved_manifest,
        template=template,
        policy=PolicyEngine.from_file(resolved_manifest.policy.file),
        knowledge_provider=resolve_knowledge_provider(resolved_manifest.knowledge),
        model_provider=resolve_provider(resolved_manifest.model),
        tool_gateway=ToolGateway.from_file(resolved_manifest.tools.file),
    )
