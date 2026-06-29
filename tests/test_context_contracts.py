from __future__ import annotations

import pytest
from pydantic import ValidationError

from proof_agent.contracts import (
    ContextAssemblyBudget,
    ContextSourceRef,
    ContextSourceType,
    ControlledRunContext,
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
            "dropped_source_refs": ["turn_000"],
            "fallback_reasons": ["older_turn_compacted"],
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
