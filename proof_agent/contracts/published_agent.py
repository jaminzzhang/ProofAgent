"""Application-neutral identity and runtime facts for a resolved Published Agent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from proof_agent.contracts.workflow_stage_configuration import PublishedAgentRuntimeFacts
from proof_agent.contracts.knowledge_resolution import ResolvedKnowledgeBindingSet


@dataclass(frozen=True)
class PublishedAgent:
    """A configured Agent package exposed through a stable identifier."""

    agent_id: str
    manifest_path: Path
    display_name: str
    purpose: str
    customer_facing: bool
    agent_version_id: str | None = None
    source_draft_id: str | None = None
    validation_run_id: str | None = None
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None
    runtime_facts: PublishedAgentRuntimeFacts | None = None
    source: str = "configuration"
