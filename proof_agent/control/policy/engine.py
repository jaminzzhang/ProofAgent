from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from proof_agent.contracts import (
    EnforcementPoint,
    PolicyDecision,
    PolicyDecisionType,
    PolicyRule,
)
from proof_agent.control.policy.rules import load_policy_rules


class PolicyEngine:
    """Small deterministic evaluator for declarative policy.yaml rules."""

    def __init__(self, rules: tuple[PolicyRule, ...]) -> None:
        self.rules = rules

    @classmethod
    def from_file(cls, path: Path | str) -> PolicyEngine:
        return cls(load_policy_rules(path))

    def evaluate(
        self,
        enforcement_point: EnforcementPoint | str,
        context: Mapping[str, Any],
        *,
        trace_event_id: str = "",
    ) -> PolicyDecision:
        point = EnforcementPoint(enforcement_point)
        for rule in self.rules:
            if rule.enforcement_point != point:
                continue
            decision = self._evaluate_rule(rule, context)
            if decision is not None:
                # v1 uses first-match semantics to keep receipts easy to explain.
                return PolicyDecision(
                    decision=decision,
                    enforcement_point=point,
                    reason=rule.reason_template,
                    policy_rule_id=rule.rule_id,
                    metadata=dict(context),
                    trace_event_id=trace_event_id,
                )
        return self._allow(point, context, trace_event_id=trace_event_id)

    def _evaluate_rule(
        self, rule: PolicyRule, context: Mapping[str, Any]
    ) -> PolicyDecisionType | None:
        if rule.enforcement_point == EnforcementPoint.BEFORE_ANSWER:
            return self._evaluate_before_answer(rule, context)
        if rule.enforcement_point == EnforcementPoint.BEFORE_TOOL_CALL:
            return self._evaluate_before_tool_call(rule, context)
        if rule.enforcement_point == EnforcementPoint.BEFORE_MEMORY_WRITE:
            return self._evaluate_before_memory_write(rule, context)
        if rule.enforcement_point == EnforcementPoint.BEFORE_RETRIEVAL:
            return self._evaluate_before_retrieval(rule)
        if rule.enforcement_point == EnforcementPoint.BEFORE_MODEL_CALL:
            return self._evaluate_before_model_call(rule, context)
        return None

    def _evaluate_before_answer(
        self, rule: PolicyRule, context: Mapping[str, Any]
    ) -> PolicyDecisionType:
        """Require enough accepted evidence before the agent can answer."""

        condition = rule.condition
        min_count = int(condition.get("min_evidence_count", 0))
        require_citations = bool(condition.get("require_citations", False))
        accepted_count = int(context.get("accepted_evidence_count", 0))
        citations_present = bool(context.get("citations_present", False))
        passed = accepted_count >= min_count and (not require_citations or citations_present)
        return self._decision_from_rule(rule, "on_pass" if passed else "on_fail")

    def _evaluate_before_tool_call(
        self, rule: PolicyRule, context: Mapping[str, Any]
    ) -> PolicyDecisionType | None:
        """Only match tool rules for the requested tool and configured risk level."""

        condition = rule.condition
        if condition.get("tool_name") != context.get("tool_name"):
            return None
        if "risk_level" in condition and condition["risk_level"] != context.get("risk_level"):
            return None
        return self._decision_from_rule(rule, "on_match")

    def _evaluate_before_memory_write(
        self, rule: PolicyRule, context: Mapping[str, Any]
    ) -> PolicyDecisionType:
        """Block memory writes containing fields that policy marks as unsafe."""

        deny_fields = set(rule.condition.get("deny_fields", ()))
        write = context.get("write", context)
        if isinstance(write, Mapping) and deny_fields.intersection(write):
            return self._decision_from_rule(rule, "on_match")
        return self._decision_from_rule(rule, "on_pass")

    def _evaluate_before_retrieval(self, rule: PolicyRule) -> PolicyDecisionType:
        if "deny" in rule.decision.values():
            return self._decision_from_rule(rule, "on_match")
        return PolicyDecisionType.ALLOW

    def _evaluate_before_model_call(
        self, rule: PolicyRule, context: Mapping[str, Any]
    ) -> PolicyDecisionType | None:
        condition = rule.condition
        for key in ("provider", "model", "cost_class", "stream"):
            if key in condition and condition[key] != context.get(key):
                return None
        max_tokens = condition.get("max_estimated_tokens")
        if max_tokens is not None:
            estimated = context.get("estimated_tokens")
            if estimated is None or int(estimated) > int(max_tokens):
                return self._decision_from_rule(rule, "on_fail")
        return self._decision_from_rule(rule, "on_match")

    def _decision_from_rule(self, rule: PolicyRule, key: str) -> PolicyDecisionType:
        value = rule.decision.get(key, "allow")
        return PolicyDecisionType(value)

    def _allow(
        self,
        enforcement_point: EnforcementPoint,
        context: Mapping[str, Any],
        *,
        trace_event_id: str,
    ) -> PolicyDecision:
        """Produce an explicit allow decision when no rule blocks the action."""

        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            enforcement_point=enforcement_point,
            reason="No blocking policy rule matched.",
            policy_rule_id="default.allow",
            metadata=dict(context),
            trace_event_id=trace_event_id,
        )
