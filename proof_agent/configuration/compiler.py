from __future__ import annotations

from pathlib import Path

from proof_agent.contracts import DraftAgent


def compile_draft_agent(draft: DraftAgent, output_dir: Path) -> Path:
    """Write a Draft Agent's Contract Bundle as a reviewable Agent Package."""

    package_dir = output_dir / draft.agent_id / draft.draft_id
    package_dir.mkdir(parents=True, exist_ok=True)
    bundle = draft.contract_bundle
    (package_dir / "agent.yaml").write_text(bundle.agent_yaml, encoding="utf-8")
    (package_dir / "policy.yaml").write_text(bundle.policy_yaml, encoding="utf-8")
    (package_dir / "tools.yaml").write_text(bundle.tools_yaml, encoding="utf-8")
    for filename, content in bundle.extra_files.items():
        path = package_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return package_dir
