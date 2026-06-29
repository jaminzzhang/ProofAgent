from __future__ import annotations

import pytest
from pydantic import ValidationError

from proof_agent.contracts import (
    MemoryPromotionDecision,
    MemoryPromotionOutcome,
    MemoryScope,
)


def test_no_memory_promotion_classification_has_no_target_scope() -> None:
    decision = MemoryPromotionDecision(
        outcome=MemoryPromotionOutcome.NO_MEMORY,
        source_turn_id="turn_123",
        reasons=("business_answer_text",),
    )

    assert decision.target_scope is None
    assert decision.reasons == ("business_answer_text",)

    with pytest.raises(ValidationError):
        MemoryPromotionDecision(
            outcome=MemoryPromotionOutcome.NO_MEMORY,
            source_turn_id="turn_123",
            target_scope=MemoryScope.CASE,
            reasons=("business_answer_text",),
        )
