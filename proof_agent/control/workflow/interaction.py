"""Deterministic interaction decisions. Human information never grants authority."""
from typing import Literal
from proof_agent.contracts.workflow_policy import InteractionPolicy, InteractionReason, InteractionStage

REQUIRED_REASONS = frozenset({'required_context', 'scope_change', 'budget_change',
                              'applicability_unresolved', 'required_parameter', 'user_preference_blocking'})


def decide_interaction(
    policy: InteractionPolicy, *, stage: InteractionStage, reason: InteractionReason,
    has_default: bool = False, rounds_asked: int = 0,
) -> Literal['continue', 'ask', 'missing_context', 'pause']:
    if reason == 'retrievable':
        return 'continue'
    required = reason in REQUIRED_REASONS
    checkpoint = policy.checkpoints.get(stage)
    intensity = checkpoint.intensity if checkpoint and checkpoint.intensity else policy.intensity
    optional_ask = (bool(checkpoint and reason in checkpoint.ask_on)
                    or policy.mode == 'interactive' or intensity == 'thorough'
                    or (intensity == 'balanced' and not has_default))
    if not required and (not optional_ask or policy.mode == 'autonomous' or rounds_asked >= policy.max_rounds):
        return 'continue'
    if policy.mode == 'autonomous' or rounds_asked >= policy.max_rounds:
        return 'pause' if policy.unavailable == 'pause' else 'missing_context'
    return 'ask'
