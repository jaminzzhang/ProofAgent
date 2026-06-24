"""Tests for ADR-0015 retrieval contracts: RetrievalCapabilities, DocumentNode, RetrievalAction."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from proof_agent.capabilities.knowledge.capabilities import RetrievalCapabilities
from proof_agent.capabilities.knowledge import KnowledgeDocumentRoutingSelection
from proof_agent.capabilities.knowledge.contracts import DocumentNode, RetrievalAction
from proof_agent.contracts.manifest import ModelConfig, RetrievalConfig


# ============================================================================
# RetrievalCapabilities Tests
# ============================================================================


def test_retrieval_capabilities_defaults_to_parallel_retrieval() -> None:
    """Parallel retrieval defaults to enabled for providers that expose capabilities."""
    caps = RetrievalCapabilities()
    assert caps.supports_structure_listing is False
    assert caps.supports_scoped_retrieval is False
    assert caps.supports_parallel_retrieval is True


def test_retrieval_capabilities_can_enable_features() -> None:
    """Can construct with True values for all capability flags."""
    caps = RetrievalCapabilities(
        supports_structure_listing=True,
        supports_scoped_retrieval=True,
        supports_parallel_retrieval=True,
    )
    assert caps.supports_structure_listing is True
    assert caps.supports_scoped_retrieval is True
    assert caps.supports_parallel_retrieval is True


def test_retrieval_capabilities_is_frozen() -> None:
    """Mutation raises ValidationError due to frozen=True."""
    caps = RetrievalCapabilities()
    with pytest.raises(ValidationError):
        caps.supports_structure_listing = True  # type: ignore[misc]


def test_retrieval_capabilities_serialization_roundtrip() -> None:
    """model_dump() and model_validate() preserve values."""
    original = RetrievalCapabilities(
        supports_structure_listing=True,
        supports_scoped_retrieval=False,
    )
    data = original.model_dump()
    restored = RetrievalCapabilities.model_validate(data)
    assert restored == original


# ============================================================================
# DocumentNode Tests
# ============================================================================


def test_document_node_required_fields() -> None:
    """Can construct with minimum required fields."""
    node = DocumentNode(
        node_id="doc_001",
        title="Policy Document",
        depth=0,
    )
    assert node.node_id == "doc_001"
    assert node.title == "Policy Document"
    assert node.depth == 0


def test_document_node_defaults() -> None:
    """Optional fields have correct defaults."""
    node = DocumentNode(
        node_id="doc_001",
        title="Policy Document",
        depth=0,
    )
    assert node.summary is None
    assert node.child_ids == ()
    assert len(node.metadata) == 0


def test_document_node_with_all_fields() -> None:
    """Can construct with all fields populated."""
    node = DocumentNode(
        node_id="doc_001",
        title="Policy Document",
        summary="This document covers insurance policies.",
        depth=1,
        child_ids=("sec_001", "sec_002"),
        metadata={
            "tags": ["insurance", "policy"],
            "document_type": "regulation",
            "business_category": "insurance",
        },
    )
    assert node.summary == "This document covers insurance policies."
    assert node.child_ids == ("sec_001", "sec_002")
    # freeze_value converts lists to tuples recursively
    assert node.metadata["tags"] == ("insurance", "policy")
    assert node.metadata["document_type"] == "regulation"


def test_document_node_is_frozen() -> None:
    """Mutation raises ValidationError due to frozen=True."""
    node = DocumentNode(
        node_id="doc_001",
        title="Policy Document",
        depth=0,
    )
    with pytest.raises(ValidationError):
        node.title = "Changed Title"  # type: ignore[misc]


def test_document_node_metadata_is_immutable() -> None:
    """Nested metadata mutation raises TypeError."""
    node = DocumentNode(
        node_id="doc_001",
        title="Policy Document",
        depth=0,
        metadata={"tags": ["insurance"]},
    )
    with pytest.raises(TypeError):
        node.metadata["new_key"] = "value"  # type: ignore[index]


def test_document_node_child_ids_are_immutable() -> None:
    """child_ids is a tuple, not a list."""
    node = DocumentNode(
        node_id="doc_001",
        title="Policy Document",
        depth=0,
        child_ids=("sec_001", "sec_002"),
    )
    assert isinstance(node.child_ids, tuple)
    # tuples don't have append method, so AttributeError is raised
    with pytest.raises(AttributeError):
        node.child_ids.append("sec_003")  # type: ignore[attr-defined]


def test_document_node_serialization_roundtrip() -> None:
    """model_dump() and model_validate() preserve values."""
    original = DocumentNode(
        node_id="doc_001",
        title="Policy Document",
        summary="Summary text",
        depth=1,
        child_ids=("sec_001",),
        metadata={"key": "value"},
    )
    data = original.model_dump()
    restored = DocumentNode.model_validate(data)
    assert restored == original


# ============================================================================
# RetrievalAction Tests
# ============================================================================


def test_retrieval_action_sufficient() -> None:
    """Can construct a 'sufficient' action."""
    action = RetrievalAction(
        action="sufficient",
        reason="Evidence is adequate to answer the question.",
    )
    assert action.action == "sufficient"
    assert action.reason == "Evidence is adequate to answer the question."
    assert action.new_query is None


def test_retrieval_action_rewrite_carries_new_query() -> None:
    """Rewrite action includes new_query field."""
    action = RetrievalAction(
        action="rewrite",
        reason="Need to search from different angle.",
        new_query="What are the coverage limits for auto insurance?",
    )
    assert action.action == "rewrite"
    assert action.new_query == "What are the coverage limits for auto insurance?"


def test_retrieval_action_abort() -> None:
    """Can construct an 'abort' action."""
    action = RetrievalAction(
        action="abort",
        reason="No relevant documents found in knowledge base.",
    )
    assert action.action == "abort"


def test_retrieval_action_rejects_invalid_action() -> None:
    """Literal validation rejects unknown action types."""
    with pytest.raises(ValidationError):
        RetrievalAction(
            action="unknown",  # type: ignore[arg-type]
            reason="Invalid action.",
        )


def test_retrieval_action_is_frozen() -> None:
    """Mutation raises ValidationError due to frozen=True."""
    action = RetrievalAction(
        action="sufficient",
        reason="Evidence is adequate.",
    )
    with pytest.raises(ValidationError):
        action.reason = "Changed reason"  # type: ignore[misc]


def test_retrieval_action_new_query_default_none() -> None:
    """new_query defaults to None when not provided."""
    action = RetrievalAction(
        action="abort",
        reason="No evidence found.",
    )
    assert action.new_query is None


def test_retrieval_action_serialization_roundtrip() -> None:
    """model_dump() and model_validate() preserve values."""
    original = RetrievalAction(
        action="rewrite",
        reason="Need different perspective.",
        new_query="Rewritten query",
    )
    data = original.model_dump()
    restored = RetrievalAction.model_validate(data)
    assert restored == original


# ============================================================================
# KnowledgeDocumentRoutingSelection Tests
# ============================================================================


def test_knowledge_document_routing_selection_serialization_roundtrip() -> None:
    """model_dump() and model_validate() preserve the strict routing response."""
    original = KnowledgeDocumentRoutingSelection(
        selected_document_ids=("doc_001", "doc_002"),
        reason="The selected documents match the request.",
    )
    data = original.model_dump()
    restored = KnowledgeDocumentRoutingSelection.model_validate(data)
    assert original.model_dump(mode="json") == {
        "selected_document_ids": ["doc_001", "doc_002"],
        "reason": "The selected documents match the request.",
    }
    assert restored == original


def test_knowledge_document_routing_selection_rejects_unknown_fields() -> None:
    """Unknown routing-model response fields reject validation."""
    with pytest.raises(ValidationError):
        KnowledgeDocumentRoutingSelection.model_validate(
            {
                "selected_document_ids": ["doc_001"],
                "reason": "The selected document matches the request.",
                "confidence": 0.9,
            }
        )


# ============================================================================
# RetrievalConfig Extension Tests
# ============================================================================


def test_retrieval_config_max_rounds_default() -> None:
    """max_rounds defaults to 3."""
    config = RetrievalConfig(strategy="agentic")
    assert config.max_rounds == 3


def test_retrieval_config_max_queries_default() -> None:
    """max_queries defaults to 3."""
    config = RetrievalConfig(strategy="agentic")
    assert config.max_queries == 3


def test_retrieval_config_query_parallelism_defaults() -> None:
    """query_concurrency and query_timeout_seconds have bounded defaults."""
    config = RetrievalConfig(strategy="agentic")
    assert config.query_concurrency == 3
    assert config.query_timeout_seconds == 10.0


@pytest.mark.parametrize("max_queries", [0, 6])
def test_retrieval_config_rejects_out_of_range_max_queries(max_queries: int) -> None:
    """max_queries is constrained to the approved 1..5 budget range."""
    with pytest.raises(ValidationError):
        RetrievalConfig(strategy="agentic", max_queries=max_queries)


@pytest.mark.parametrize("query_concurrency", [0, 6])
def test_retrieval_config_rejects_out_of_range_query_concurrency(
    query_concurrency: int,
) -> None:
    """query_concurrency is constrained to the approved 1..5 budget range."""
    with pytest.raises(ValidationError):
        RetrievalConfig(strategy="agentic", query_concurrency=query_concurrency)


@pytest.mark.parametrize("query_timeout_seconds", [0, 121])
def test_retrieval_config_rejects_out_of_range_query_timeout(
    query_timeout_seconds: float,
) -> None:
    """query_timeout_seconds is constrained to the approved 0.01..120 second range."""
    with pytest.raises(ValidationError):
        RetrievalConfig(strategy="agentic", query_timeout_seconds=query_timeout_seconds)


def test_retrieval_config_evaluator_model_default_none() -> None:
    """evaluator_model defaults to None."""
    config = RetrievalConfig(strategy="agentic")
    assert config.evaluator_model is None


def test_retrieval_config_evaluator_model_can_be_set() -> None:
    """evaluator_model can be set to a ModelConfig."""
    model = ModelConfig(provider="openai", name="gpt-4o-mini")
    config = RetrievalConfig(strategy="agentic", evaluator_model=model)
    assert config.evaluator_model == model
    assert config.evaluator_model.name == "gpt-4o-mini"


def test_retrieval_config_max_rounds_can_be_set() -> None:
    """max_rounds can be set to a custom value."""
    config = RetrievalConfig(strategy="agentic", max_rounds=5)
    assert config.max_rounds == 5


def test_retrieval_config_is_frozen() -> None:
    """Mutation raises ValidationError due to frozen=True."""
    config = RetrievalConfig(strategy="agentic")
    with pytest.raises(ValidationError):
        config.max_rounds = 10  # type: ignore[misc]


def test_retrieval_config_serialization_roundtrip() -> None:
    """model_dump() and model_validate() preserve values."""
    model = ModelConfig(provider="openai", name="gpt-4o-mini")
    original = RetrievalConfig(
        strategy="agentic",
        max_rounds=5,
        query_concurrency=4,
        query_timeout_seconds=7.5,
        evaluator_model=model,
    )
    data = original.model_dump()
    restored = RetrievalConfig.model_validate(data)
    assert restored == original
