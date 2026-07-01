from __future__ import annotations

import pytest
from pydantic import ValidationError

from proof_agent.contracts import (
    ContextAdmission,
    ContextAssemblyBudget,
    ContextSourceRef,
    ContextSourceType,
    AgentContextConfiguration,
    ContextBudgetProfile,
    ContextConvergenceLadder,
    ControlledRunContext,
    MemoryRecallAdmission,
    MemoryRecallTraceSummary,
    MemoryRecallWorkingPayload,
    MemoryScope,
    RunStartContextAssembly,
    WorkingContextSection,
)


def test_controlled_run_context_produces_trace_safe_assembly_summary() -> None:
    context = ControlledRunContext(
        run_id="run_123",
        sources=(
            ContextSourceRef(
                source_type=ContextSourceType.CONVERSATION_TURN,
                source_id="turn_001",
            ),
            ContextSourceRef(
                source_type=ContextSourceType.MEMORY_RECALL,
                source_id="mem_case_001",
            ),
        ),
        working_sections=(
            WorkingContextSection(
                section_id="harness_control",
                source_refs=("harness:react_enterprise_qa_v3",),
                priority=0,
                stable_prefix=True,
                estimated_tokens=240,
            ),
            WorkingContextSection(
                section_id="recent_turns",
                source_refs=("turn_001",),
                priority=60,
                stable_prefix=False,
                estimated_tokens=180,
            ),
        ),
        budget=ContextAssemblyBudget(
            max_tokens=4096,
            estimated_tokens=420,
            dropped_source_refs=("turn_000",),
            fallback_reasons=("older_turn_compacted",),
        ),
    )

    assert context.trace_safe_summary().model_dump(mode="json") == {
        "run_id": "run_123",
        "source_refs": [
            {"source_type": "conversation_turn", "source_id": "turn_001"},
            {"source_type": "memory_recall", "source_id": "mem_case_001"},
        ],
        "working_sections": [
            {
                "section_id": "harness_control",
                "source_refs": ["harness:react_enterprise_qa_v3"],
                "priority": 0,
                "stable_prefix": True,
                "estimated_tokens": 240,
            },
            {
                "section_id": "recent_turns",
                "source_refs": ["turn_001"],
                "priority": 60,
                "stable_prefix": False,
                "estimated_tokens": 180,
            },
        ],
        "budget": {
            "max_tokens": 4096,
            "estimated_tokens": 420,
            "convergence_level": "none",
            "budget_source": "unknown",
            "dropped_source_refs": ["turn_000"],
            "fallback_reasons": ["older_turn_compacted"],
            "calibration_update_refs": [],
        },
    }


def test_controlled_run_context_orders_working_sections_for_cache_stability() -> None:
    context = ControlledRunContext(
        run_id="run_123",
        working_sections=(
            WorkingContextSection(
                section_id="recent_turns",
                source_refs=("turn_001",),
                priority=60,
                stable_prefix=False,
                estimated_tokens=180,
            ),
            WorkingContextSection(
                section_id="agent_contract",
                source_refs=("agent:insurance_customer_service",),
                priority=10,
                stable_prefix=True,
                estimated_tokens=120,
            ),
            WorkingContextSection(
                section_id="harness_control",
                source_refs=("harness:react_enterprise_qa_v3",),
                priority=0,
                stable_prefix=True,
                estimated_tokens=240,
            ),
        ),
        budget=ContextAssemblyBudget(max_tokens=4096, estimated_tokens=540),
    )

    assert [section.section_id for section in context.cache_stable_working_sections()] == [
        "harness_control",
        "agent_contract",
        "recent_turns",
    ]


def test_working_context_section_rejects_raw_context_section_id() -> None:
    with pytest.raises(ValidationError):
        WorkingContextSection(
            section_id="raw_context",
            source_refs=("turn_001",),
            priority=60,
            stable_prefix=False,
            estimated_tokens=180,
        )


def test_run_start_context_assembly_carries_trace_summary_and_compatibility_admission() -> None:
    context = ControlledRunContext(
        run_id="run_123",
        sources=(
            ContextSourceRef(
                source_type=ContextSourceType.CONVERSATION_TURN,
                source_id="turn_001",
            ),
        ),
        working_sections=(
            WorkingContextSection(
                section_id="recent_turns",
                source_refs=("turn_001",),
                priority=60,
                stable_prefix=False,
                estimated_tokens=180,
            ),
        ),
        budget=ContextAssemblyBudget(max_tokens=4096, estimated_tokens=180),
    )
    admission = ContextAdmission(
        admitted=True,
        turn_count=1,
        included_turn_ids=("turn_001",),
        summary="1 prior turn admitted.",
        char_count=180,
        max_turns=3,
    )

    assembly = RunStartContextAssembly.from_controlled_run_context(
        context,
        conversation_context=admission,
    )

    assert assembly.conversation_context == admission
    assert assembly.trace_safe_summary == context.trace_safe_summary()
    assert assembly.controlled_run_context == context
    assert assembly.trace_safe_summary.model_dump(mode="json") == {
        "run_id": "run_123",
        "source_refs": [
            {"source_type": "conversation_turn", "source_id": "turn_001"},
        ],
        "working_sections": [
            {
                "section_id": "recent_turns",
                "source_refs": ["turn_001"],
                "priority": 60,
                "stable_prefix": False,
                "estimated_tokens": 180,
            },
        ],
        "budget": {
            "max_tokens": 4096,
            "estimated_tokens": 180,
            "convergence_level": "none",
            "budget_source": "unknown",
            "dropped_source_refs": [],
            "fallback_reasons": [],
            "calibration_update_refs": [],
        },
    }


def test_memory_recall_trace_summary_rejects_secret_like_fact_keys() -> None:
    with pytest.raises(ValidationError):
        MemoryRecallTraceSummary(
            scope=MemoryScope.USER,
            subject_ref="CUST-001",
            included_memory_ids=("mem_user_001",),
            summary="Customer prefers monthly claim reports.",
            fact_keys=("api_key",),
            fact_count=1,
        )


def test_memory_recall_admission_projects_trace_summary_and_working_payload() -> None:
    payload = MemoryRecallWorkingPayload(
        scope=MemoryScope.CASE,
        source_refs=("mem_case_001",),
        summary="Case focus: inpatient reimbursement.",
        facts={"case_focus": "inpatient reimbursement"},
    )
    admission = MemoryRecallAdmission(
        admitted=True,
        scope=MemoryScope.CASE,
        case_id="cust_conv_001",
        agent_id="insurance_customer_service",
        included_memory_ids=("mem_case_001",),
        summary="Case focus: inpatient reimbursement.",
        fact_keys=("case_focus",),
        fact_count=1,
        working_payload=payload,
    )

    assert admission.trace_summary() == MemoryRecallTraceSummary(
        admitted=True,
        scope=MemoryScope.CASE,
        case_id="cust_conv_001",
        agent_id="insurance_customer_service",
        included_memory_ids=("mem_case_001",),
        summary="Case focus: inpatient reimbursement.",
        fact_keys=("case_focus",),
        fact_count=1,
    )
    assert admission.working_payload == payload


def test_agent_context_configuration_accepts_budget_and_convergence_policy() -> None:
    config = AgentContextConfiguration(
        budget_profile=ContextBudgetProfile(
            max_tokens=8192,
            reserved_output_tokens=1024,
            estimation_strategy="heuristic",
            profile_version="context_budget.v1",
        ),
        convergence=ContextConvergenceLadder(
            level1_ratio=0.5,
            level2_ratio=0.8,
            hard_limit_ratio=1.0,
        ),
        dynamic_calibration=True,
        source_policies={"memory_recall": {"max_records": 3}},
    )

    assert config.budget_profile is not None
    assert config.budget_profile.max_tokens == 8192
    assert config.convergence.level1_ratio == 0.5
    assert config.source_policies["memory_recall"]["max_records"] == 3


def test_agent_context_configuration_rejects_unordered_convergence_thresholds() -> None:
    with pytest.raises(ValidationError):
        ContextConvergenceLadder(level1_ratio=0.9, level2_ratio=0.8)


def test_agent_context_configuration_rejects_raw_source_policy_keys() -> None:
    with pytest.raises(ValidationError):
        AgentContextConfiguration(source_policies={"raw_context": True})
