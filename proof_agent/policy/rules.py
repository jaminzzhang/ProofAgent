from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from proof_agent.contracts import EnforcementPoint, PolicyRule
from proof_agent.errors import ProofAgentError


def load_policy_rules(path: Path | str) -> tuple[PolicyRule, ...]:
    policy_path = Path(path)
    if not policy_path.exists():
        raise ProofAgentError(
            "PA_POLICY_001",
            f"policy file does not exist: {policy_path}",
            "Create the policy file or update policy.file in agent.yaml.",
            artifact_path=policy_path,
        )
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    rules = raw.get("rules", [])
    if not isinstance(rules, list):
        raise ProofAgentError(
            "PA_POLICY_001",
            "policy.yaml rules must be a list",
            "Use a top-level rules list in policy.yaml.",
            artifact_path=policy_path,
        )
    return tuple(_rule_from_mapping(rule) for rule in rules)


def _rule_from_mapping(raw: dict[str, Any]) -> PolicyRule:
    return PolicyRule(
        rule_id=raw["rule_id"],
        enforcement_point=EnforcementPoint(raw["enforcement_point"]),
        condition=raw.get("condition", {}),
        decision=raw.get("decision", {}),
        reason_template=raw.get("reason_template", raw["rule_id"]),
    )
