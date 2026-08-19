"""Development package validator for Agent Configuration Workspace publication."""

from __future__ import annotations

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.compiler import compile_draft_agent
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import AgentValidationRecord, DraftAgent


class LocalAgentConfigurationPublicationAdapter:
    """Validate package and live local assets without owning lifecycle writes."""

    def __init__(self, *, configuration_store: LocalAgentConfigurationStore) -> None:
        self._configuration_store = configuration_store

    def validate(
        self,
        *,
        draft: DraftAgent,
        validation: AgentValidationRecord,
    ) -> None:
        package_dir = compile_draft_agent(
            draft,
            self._configuration_store.root_dir / "compiled_publication",
        )
        load_agent_manifest(package_dir / "agent.yaml")
        self._configuration_store.validate_draft_publication(
            draft=draft,
            resolved_knowledge_bindings=validation.resolved_knowledge_bindings,
        )
