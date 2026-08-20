"""Local whole-package validation adapter for raw Agent Contracts."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.bootstrap.skills import load_business_flow_skill_pack_set
from proof_agent.configuration.compiler import compile_draft_agent
from proof_agent.contracts import DraftAgent
from proof_agent.control.workflow.templates import resolve_workflow_template
from proof_agent.errors import ProofAgentError


class LocalAgentConfigurationContractValidator:
    """Compile and validate one Contract candidate without retaining artifacts."""

    def validate(self, *, draft: DraftAgent) -> None:
        try:
            with TemporaryDirectory(prefix="proof-agent-contract-") as temporary_dir:
                package_dir = compile_draft_agent(draft, Path(temporary_dir))
                manifest_path = package_dir / "agent.yaml"
                manifest = load_agent_manifest(manifest_path)
                load_business_flow_skill_pack_set(
                    manifest,
                    template=resolve_workflow_template(manifest.workflow.template),
                    manifest_path=manifest_path,
                )
        except (KeyError, ValueError, ProofAgentError) as exc:
            raise ValueError("Agent Contract candidate is invalid.") from exc
