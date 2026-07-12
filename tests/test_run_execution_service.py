from pathlib import Path
from typing import Any

import proof_agent.delivery.run_execution_service as run_execution_service
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import ReceiptOutcome, WorkflowTemplateExecutionResult
from proof_agent.delivery.published_agents import PublishedAgent
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.approval_resume import LangGraphApprovalResumeRegistry


def test_published_agent_run_uses_per_run_history_artifact_dir(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "history")
    configuration_store = LocalAgentConfigurationStore(tmp_path / "config")
    starts: list[Any] = []

    class FakeControlledReActOrchestrator:
        def start(self, request: Any) -> WorkflowTemplateExecutionResult:
            starts.append(request)
            return WorkflowTemplateExecutionResult(
                run_id=request.run_id,
                template_name=request.template_name,
                template_descriptor_version=request.template_descriptor_version,
                outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                final_output="ok",
                message="ok",
            )

    execution = run_execution_service.execute_published_agent_run(
        dependencies=run_execution_service.RunExecutionDependencies(
            store=store,
            runs_dir=tmp_path / "latest",
            configuration_store=configuration_store,
            approval_resume_registry=LangGraphApprovalResumeRegistry(
                tmp_path / "approval_resume",
                configuration_store=configuration_store,
            ),
            controlled_react_orchestrator=FakeControlledReActOrchestrator(),
        ),
        published_agent=PublishedAgent(
            agent_id="react_enterprise_qa_v3",
            manifest_path=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            display_name="Enterprise QA V3",
            purpose="Answer enterprise QA questions.",
            customer_facing=False,
            agent_version_id="version_003",
            source_draft_id="draft_003",
        ),
        question="What is the reimbursement rule for travel meals?",
    )

    expected_dir = store.history_dir / execution.detail.run_id
    assert starts[0].run_id == execution.detail.run_id
    assert (expected_dir / "trace.jsonl").exists()
    assert (tmp_path / "latest").resolve() == expected_dir.resolve()


def test_v3_published_agent_run_uses_controlled_react_orchestrator(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "history")
    configuration_store = LocalAgentConfigurationStore(tmp_path / "config")
    starts: list[Any] = []

    class FakeControlledReActOrchestrator:
        def start(self, request: Any) -> WorkflowTemplateExecutionResult:
            starts.append(request)
            return WorkflowTemplateExecutionResult(
                run_id=request.run_id,
                template_name=request.template_name,
                template_descriptor_version=request.template_descriptor_version,
                outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                final_output="controlled answer",
                message="controlled answer",
            )

    execution = run_execution_service.execute_published_agent_run(
        dependencies=run_execution_service.RunExecutionDependencies(
            store=store,
            runs_dir=tmp_path / "latest",
            configuration_store=configuration_store,
            approval_resume_registry=LangGraphApprovalResumeRegistry(
                tmp_path / "approval_resume",
                configuration_store=configuration_store,
            ),
            controlled_react_orchestrator=FakeControlledReActOrchestrator(),
        ),
        published_agent=PublishedAgent(
            agent_id="react_enterprise_qa_v3",
            manifest_path=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            display_name="Enterprise QA V3",
            purpose="Answer enterprise QA questions.",
            customer_facing=False,
            agent_version_id="version_003",
            source_draft_id="draft_003",
        ),
        question="What is the reimbursement rule for travel meals?",
    )

    assert len(starts) == 1
    assert starts[0].template_name == "react_enterprise_qa_v3"
    assert starts[0].template_descriptor_version == "react_enterprise_qa.v3"
    assert execution.result.workflow_template_execution_result is not None
    assert execution.result.final_output == "controlled answer"
    assert execution.detail.run_id == starts[0].run_id
    assert execution.detail.outcome == ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert execution.detail.workflow_projection.template_name == "react_enterprise_qa_v3"
    assert (store.history_dir / execution.detail.run_id / "trace.jsonl").exists()
    assert (store.history_dir / execution.detail.run_id / "governance_receipt.md").exists()
