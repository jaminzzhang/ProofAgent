"""Compatibility imports for pre-V3 ReAct Enterprise QA consumers.

Controlled ReAct owns the shared action-control and review semantics. Legacy
workflow code imports those implementations from here until its planned
removal; this module intentionally defines no second implementation.
"""

from proof_agent.control.workflow.controlled_react.action_control import (
    ActionRewrite,
    build_retrieval_observation_record,
    clarification_message,
    compute_eligible_action_set,
    constrain_action,
    emit_action_proposal,
    emit_intent_resolution,
    emit_reasoning_summary,
    should_block_duplicate_observation_action,
    should_stop_for_plan_budget,
    should_stop_for_step_budget,
)
from proof_agent.control.workflow.controlled_react.review import review_action

__all__ = [
    "ActionRewrite",
    "build_retrieval_observation_record",
    "clarification_message",
    "compute_eligible_action_set",
    "constrain_action",
    "emit_action_proposal",
    "emit_intent_resolution",
    "emit_reasoning_summary",
    "review_action",
    "should_block_duplicate_observation_action",
    "should_stop_for_plan_budget",
    "should_stop_for_step_budget",
]
