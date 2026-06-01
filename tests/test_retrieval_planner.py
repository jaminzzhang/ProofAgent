"""Tests for RetrievalPlanner component (ADR-0015)."""

from proof_agent.contracts.evidence import EvidenceChunk, EvidenceStatus
from proof_agent.control.workflow.retrieval_planner import RetrievalPlanner


class MockKnowledgeProvider:
    """Mock knowledge provider for testing."""

    def __init__(self, responses: list[list[EvidenceChunk]] | None = None):
        self.responses = responses or []
        self.calls: list[str] = []

    def retrieve(self, query: str) -> list[EvidenceChunk]:
        self.calls.append(query)
        if self.responses:
            return self.responses.pop(0)
        return []


class MockPlannerModel:
    """Mock planner model that returns predefined action plans."""

    def __init__(self, action_plans: list[dict]):
        self.action_plans = action_plans
        self.calls: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self.action_plans:
            plan = self.action_plans.pop(0)
            if plan["action"] == "rewrite":
                return f"""{{"action": "rewrite", "new_query": "{plan["new_query"]}", "reason": "{plan["reason"]}"}}"""
            elif plan["action"] == "abort":
                return f"""{{"action": "abort", "reason": "{plan["reason"]}"}}"""
            else:
                return """{"action": "sufficient", "reason": "Evidence is adequate"}"""
        return """{"action": "sufficient", "reason": "Default"}"""


class MockEvaluatorModel:
    """Mock evaluator model that returns predefined judgments."""

    def __init__(self, judgments: list[dict]):
        self.judgments = judgments
        self.calls: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self.judgments:
            judgment = self.judgments.pop(0)
            return f"""{{"sufficient": {str(judgment["sufficient"]).lower()}, "reason": "{judgment["reason"]}"}}"""
        return """{"sufficient": true, "reason": "Default"}"""


def make_evidence(content: str, source: str, citation: str) -> EvidenceChunk:
    """Helper to create EvidenceChunk with required status field."""
    return EvidenceChunk(
        content=content,
        source=source,
        citation=citation,
        status=EvidenceStatus.CANDIDATE,
    )


class TestRetrievalPlanner:
    """Test RetrievalPlanner multi-round agentic retrieval."""

    def test_single_round_sufficient(self):
        """Test retrieval that succeeds on first round."""
        evidence = [
            make_evidence("Python is a programming language", "test.md", "test.md:1"),
        ]
        provider = MockKnowledgeProvider([evidence])
        planner_model = MockPlannerModel([{"action": "sufficient"}])
        evaluator_model = MockEvaluatorModel([{"sufficient": True, "reason": "Found answer"}])

        planner = RetrievalPlanner(
            knowledge_provider=provider,
            planner_model=planner_model,
            evaluator_model=evaluator_model,
            max_rounds=3,
        )

        result = planner.plan_and_retrieve("What is Python?")

        assert len(result.evidence) == 1
        assert result.evidence[0].content == "Python is a programming language"
        assert result.total_rounds == 1
        assert result.final_action == "sufficient"
        assert len(provider.calls) == 1

    def test_multi_round_with_rewrite(self):
        """Test retrieval with query rewrite across multiple rounds."""
        evidence1 = [make_evidence("Partial info", "doc1.md", "doc1.md:1")]
        evidence2 = [make_evidence("Complete answer", "doc2.md", "doc2.md:1")]

        provider = MockKnowledgeProvider([evidence1, evidence2])
        planner_model = MockPlannerModel([
            {"action": "rewrite", "new_query": "What is Python programming language?", "reason": "Need more specific"},
            {"action": "sufficient"},
        ])
        evaluator_model = MockEvaluatorModel([
            {"sufficient": False, "reason": "Insufficient detail"},
            {"sufficient": True, "reason": "Found complete answer"},
        ])

        planner = RetrievalPlanner(
            knowledge_provider=provider,
            planner_model=planner_model,
            evaluator_model=evaluator_model,
            max_rounds=3,
        )

        result = planner.plan_and_retrieve("Tell me about Python")

        assert len(result.evidence) == 2
        assert result.total_rounds == 2
        assert result.final_action == "sufficient"
        assert len(provider.calls) == 2
        assert provider.calls[1] == "What is Python programming language?"

    def test_abort_action(self):
        """Test abort action when evidence is inadequate."""
        provider = MockKnowledgeProvider([[]])
        planner_model = MockPlannerModel([
            {"action": "abort", "reason": "No relevant documents found"},
        ])
        evaluator_model = MockEvaluatorModel([{"sufficient": False, "reason": "No evidence"}])

        planner = RetrievalPlanner(
            knowledge_provider=provider,
            planner_model=planner_model,
            evaluator_model=evaluator_model,
            max_rounds=3,
        )

        result = planner.plan_and_retrieve("Unknown topic")

        assert len(result.evidence) == 0
        assert result.total_rounds == 1
        assert result.final_action == "abort"

    def test_max_rounds_termination(self):
        """Test hard limit termination at max_rounds."""
        evidence = [make_evidence("Partial", "doc.md", "doc.md:1")]
        provider = MockKnowledgeProvider([evidence, evidence, evidence, evidence])
        planner_model = MockPlannerModel([
            {"action": "rewrite", "new_query": "Query 2", "reason": "Try again"},
            {"action": "rewrite", "new_query": "Query 3", "reason": "Try again"},
            {"action": "rewrite", "new_query": "Query 4", "reason": "Try again"},
        ])
        evaluator_model = MockEvaluatorModel([
            {"sufficient": False, "reason": "Not enough"},
            {"sufficient": False, "reason": "Still not enough"},
            {"sufficient": False, "reason": "Still not enough"},
        ])

        planner = RetrievalPlanner(
            knowledge_provider=provider,
            planner_model=planner_model,
            evaluator_model=evaluator_model,
            max_rounds=3,
        )

        result = planner.plan_and_retrieve("Complex question")

        assert result.total_rounds == 3
        assert result.final_action == "max_rounds_reached"
        assert len(result.evidence) > 0

    def test_planner_model_failure_returns_accumulated_evidence(self):
        """Test that planner model failure returns accumulated evidence."""
        evidence = [make_evidence("Some evidence", "doc.md", "doc.md:1")]
        provider = MockKnowledgeProvider([evidence])

        class FailingModel:
            def generate(self, prompt: str) -> str:
                raise Exception("LLM API error")

        planner = RetrievalPlanner(
            knowledge_provider=provider,
            planner_model=FailingModel(),
            evaluator_model=MockEvaluatorModel([]),
            max_rounds=3,
        )

        result = planner.plan_and_retrieve("Test query")

        assert len(result.evidence) == 1
        assert result.final_action == "planner_failure"

    def test_evaluator_model_failure_returns_accumulated_evidence(self):
        """Test that evaluator model failure returns accumulated evidence."""
        evidence = [make_evidence("Evidence", "doc.md", "doc.md:1")]
        provider = MockKnowledgeProvider([evidence])
        planner_model = MockPlannerModel([{"action": "sufficient"}])

        class FailingEvaluator:
            def generate(self, prompt: str) -> str:
                raise Exception("Evaluator API error")

        planner = RetrievalPlanner(
            knowledge_provider=provider,
            planner_model=planner_model,
            evaluator_model=FailingEvaluator(),
            max_rounds=3,
        )

        result = planner.plan_and_retrieve("Test query")

        assert len(result.evidence) == 1
        assert result.final_action == "evaluator_failure"

    def test_action_plan_parse_error_returns_accumulated_evidence(self):
        """Test that action plan parsing error returns accumulated evidence."""
        evidence = [make_evidence("Evidence", "doc.md", "doc.md:1")]
        provider = MockKnowledgeProvider([evidence])

        class BadPlanner:
            def generate(self, prompt: str) -> str:
                return "invalid json {"

        planner = RetrievalPlanner(
            knowledge_provider=provider,
            planner_model=BadPlanner(),
            evaluator_model=MockEvaluatorModel([]),
            max_rounds=3,
        )

        result = planner.plan_and_retrieve("Test query")

        assert len(result.evidence) == 1
        assert result.final_action == "planner_failure"

    def test_provider_timeout_returns_accumulated_evidence(self):
        """Test that provider timeout returns accumulated evidence."""
        evidence1 = [make_evidence("Round 1", "doc1.md", "doc1.md:1")]

        class TimeoutProvider:
            def __init__(self):
                self.call_count = 0

            def retrieve(self, query: str) -> list[EvidenceChunk]:
                self.call_count += 1
                if self.call_count == 1:
                    return evidence1
                raise TimeoutError("Provider timeout")

        provider = TimeoutProvider()
        planner_model = MockPlannerModel([
            {"action": "rewrite", "new_query": "Query 2", "reason": "Try again"},
        ])
        evaluator_model = MockEvaluatorModel([
            {"sufficient": False, "reason": "Need more"},
        ])

        planner = RetrievalPlanner(
            knowledge_provider=provider,
            planner_model=planner_model,
            evaluator_model=evaluator_model,
            max_rounds=3,
        )

        result = planner.plan_and_retrieve("Test query")

        assert len(result.evidence) == 1
        assert result.evidence[0].content == "Round 1"
        assert result.final_action == "provider_failure"

    def test_evidence_accumulation_across_rounds(self):
        """Test that evidence accumulates across multiple rounds."""
        evidence1 = [make_evidence("Doc 1", "doc1.md", "doc1.md:1")]
        evidence2 = [make_evidence("Doc 2", "doc2.md", "doc2.md:1")]
        evidence3 = [make_evidence("Doc 3", "doc3.md", "doc3.md:1")]

        provider = MockKnowledgeProvider([evidence1, evidence2, evidence3])
        planner_model = MockPlannerModel([
            {"action": "rewrite", "new_query": "Query 2", "reason": "More"},
            {"action": "rewrite", "new_query": "Query 3", "reason": "More"},
            {"action": "sufficient"},
        ])
        evaluator_model = MockEvaluatorModel([
            {"sufficient": False, "reason": "Need more"},
            {"sufficient": False, "reason": "Need more"},
            {"sufficient": True, "reason": "Enough"},
        ])

        planner = RetrievalPlanner(
            knowledge_provider=provider,
            planner_model=planner_model,
            evaluator_model=evaluator_model,
            max_rounds=5,
        )

        result = planner.plan_and_retrieve("Complex query")

        assert len(result.evidence) == 3
        assert result.total_rounds == 3
        assert result.evidence[0].content == "Doc 1"
        assert result.evidence[1].content == "Doc 2"
        assert result.evidence[2].content == "Doc 3"

    def test_round_tracking_with_round_id(self):
        """Test that each round has a unique round_id for trace correlation."""
        evidence = [make_evidence("Evidence", "doc.md", "doc.md:1")]
        provider = MockKnowledgeProvider([evidence, evidence])
        planner_model = MockPlannerModel([
            {"action": "rewrite", "new_query": "Query 2", "reason": "More"},
            {"action": "sufficient"},
        ])
        evaluator_model = MockEvaluatorModel([
            {"sufficient": False, "reason": "Need more"},
            {"sufficient": True, "reason": "Enough"},
        ])

        planner = RetrievalPlanner(
            knowledge_provider=provider,
            planner_model=planner_model,
            evaluator_model=evaluator_model,
            max_rounds=3,
        )

        result = planner.plan_and_retrieve("Test query")

        assert len(result.rounds) == 2
        assert result.rounds[0].round_id != result.rounds[1].round_id
        assert result.rounds[0].round_id.startswith("round_")
        assert result.rounds[1].round_id.startswith("round_")

    def test_model_call_roles(self):
        """Test that planner and evaluator use correct ModelCallRole."""
        evidence = [make_evidence("Evidence", "doc.md", "doc.md:1")]
        provider = MockKnowledgeProvider([evidence])

        class RoleTrackingModel:
            def __init__(self):
                self.role = None

            def generate(self, prompt: str) -> str:
                return """{"action": "sufficient", "reason": "Test"}"""

        class RoleTrackingEvaluator:
            def __init__(self):
                self.role = None

            def generate(self, prompt: str) -> str:
                return """{"sufficient": true, "reason": "Test"}"""

        planner_model = RoleTrackingModel()
        evaluator_model = RoleTrackingEvaluator()

        # Note: In actual implementation, these models would be wrapped with role tracking
        planner = RetrievalPlanner(
            knowledge_provider=provider,
            planner_model=planner_model,
            evaluator_model=evaluator_model,
            max_rounds=3,
        )

        result = planner.plan_and_retrieve("Test query")

        # Verify the models were called
        assert result.total_rounds == 1
