# Evaluation Campaign Run Execution Adapter Slice 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect Evaluation Campaign sample production to the operator-facing Run Execution surface so Campaigns can create real `evaluation_sample` runs for Active Published Agents instead of relying only on fake or hand-written sample runners.

**Architecture:** Extract the existing Published Agent run execution body from `proof_agent/delivery/api.py` into a small delivery service that accepts an explicit `RunPurpose`. Add `RunExecutionApiEvaluationSampleRunner` as the Campaign adapter: it resolves the Published Agent from app state, executes through the same delivery service with `RunPurpose.EVALUATION_SAMPLE`, writes a safe `operator_response.txt` projection, and returns `EvaluationSampleRun` for the existing Campaign sample-production seam.

**Tech Stack:** Python 3.12, FastAPI app state, Pydantic v2 contracts, existing `RunStore`, `PublishedAgentRegistry`, LangGraph runner, pytest.

---

## File Structure

- Create `proof_agent/delivery/run_execution_service.py`
  - Owns the deep execution interface used by both the existing `/api/chat/runs` route and evaluation sample adapters.
  - Keeps run execution semantics in Delivery instead of duplicating Harness execution in Evaluation.
- Create `proof_agent/evaluation/run_execution_samples.py`
  - Owns the `RunExecutionApiEvaluationSampleRunner` adapter that satisfies `EvaluationSampleRunner`.
  - Writes the safe operator response projection required by Subject Manifest export.
- Modify `proof_agent/delivery/api.py`
  - Replaces the body of `_execute_published_agent_run(...)` with delegation to `execute_published_agent_run(...)`.
  - Preserves current external API behavior: normal chat runs remain `run_purpose: production`.
- Test `tests/test_evaluation_run_execution_samples.py`
  - Exercises a full Campaign with `produce_samples: true` and the real adapter.
  - Verifies generated run metadata, subject manifest export, and Analyzer readiness.

## Implementation Slices

### Slice 1: Campaign Uses Run Execution Adapter For Evaluation Samples

**Files:**
- Create: `tests/test_evaluation_run_execution_samples.py`
- Create: `proof_agent/evaluation/run_execution_samples.py`
- Create: `proof_agent/delivery/run_execution_service.py`
- Modify: `proof_agent/delivery/api.py`

- [ ] **Step 1: Write the failing adapter-backed Campaign test**

Create `tests/test_evaluation_run_execution_samples.py`:

```python
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from fastapi.testclient import TestClient

from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import RunPurpose
from proof_agent.evaluation.campaigns import run_evaluation_campaign
from proof_agent.evaluation.run_execution_samples import RunExecutionApiEvaluationSampleRunner
from proof_agent.observability.api.app import create_app


def test_campaign_uses_run_execution_api_adapter_for_evaluation_samples(tmp_path: Path) -> None:
    app = _app_with_published_agent(
        tmp_path,
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
    )
    campaign_path = _write_campaign_fixture(tmp_path)

    summary = run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=tmp_path / "campaigns",
        run_store=app.state.store,
        sample_runner=RunExecutionApiEvaluationSampleRunner(app),
    )

    assert summary.readiness_status == "ready"
    subject_manifest_path = summary.artifact_dir / "subject_manifest.yaml"
    subject_manifest = yaml.safe_load(subject_manifest_path.read_text(encoding="utf-8"))
    run_id = subject_manifest["subjects"][0]["run_ref"]["run_id"]
    detail = app.state.store.get_run_detail(run_id)

    assert detail.run_purpose == RunPurpose.EVALUATION_SAMPLE
    assert detail.agent_id == "enterprise_qa"
    assert detail.question == "What is the reimbursement rule for travel meals?"
    assert subject_manifest["subjects"][0]["execution_surface"] == "run_execution_api"
    assert subject_manifest["subjects"][0]["projections"]["evaluated_response"]["ref"].endswith(
        "operator_response.txt"
    )
    assert (app.state.store.history_dir / run_id / "operator_response.txt").read_text(
        encoding="utf-8"
    )


def _app_with_published_agent(tmp_path: Path, manifest_path: Path):
    store = LocalAgentConfigurationStore(tmp_path / "config")
    draft = import_agent_package(manifest_path, store=store, actor="test-user")
    store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation",
        actor="test-user",
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={},
        agent_configuration_store=store,
    )
    TestClient(app)
    return app


def _write_campaign_fixture(tmp_path: Path) -> Path:
    suite_path = tmp_path / "suite.yaml"
    campaign_path = tmp_path / "campaign.yaml"
    suite_path.write_text(
        """
suite_id: run_execution_sample_smoke
version: "2026-06-22"
name: Run Execution Sample Smoke
cases:
  - case_id: supported
    question: What is the reimbursement rule for travel meals?
    intent_type: guidance
    expected_resolution: answer_with_citations
    risk_class: low
    capability_path: evidence_answer
    expected:
      outcome: ANSWERED_WITH_CITATIONS
""".lstrip(),
        encoding="utf-8",
    )
    campaign_path.write_text(
        """
campaign_id: run_execution_adapter_probe
version: "2026-06-22"
target:
  agent_id: enterprise_qa
suites:
  formal:
    - source: core_regression
      suite_ref: suite.yaml
      produce_samples: true
      subject_manifest_id: run_execution_adapter_subjects
thresholds:
  governed_resolution_rate_min: 0.95
  artifact_sufficiency_required: 1.0
  deterministic_gate_pass_required: 1.0
""".lstrip(),
        encoding="utf-8",
    )
    return campaign_path
```

- [ ] **Step 2: Run the adapter-backed Campaign test and verify RED**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_evaluation_run_execution_samples.py::test_campaign_uses_run_execution_api_adapter_for_evaluation_samples -v
```

Expected: FAIL because `proof_agent.evaluation.run_execution_samples` does not exist.

- [ ] **Step 3: Extract delivery execution service**

Create `proof_agent/delivery/run_execution_service.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import AgentManifest, ContextAdmission, RunPurpose
from proof_agent.delivery.published_agents import PublishedAgent
from proof_agent.errors import ProofAgentError
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.approval_resume import (
    LangGraphApprovalResumeContext,
    LangGraphApprovalResumeRegistry,
)
from proof_agent.runtime.langgraph_runner import run_with_langgraph


@dataclass(frozen=True)
class RunExecutionDependencies:
    store: RunStore
    runs_dir: Path
    configuration_store: LocalAgentConfigurationStore
    approval_resume_registry: LangGraphApprovalResumeRegistry


@dataclass(frozen=True)
class PublishedAgentRunExecution:
    result: Any
    detail: Any
    manifest: AgentManifest


def execute_published_agent_run(
    *,
    dependencies: RunExecutionDependencies,
    published_agent: PublishedAgent,
    question: str,
    conversation_context: ContextAdmission | None = None,
    run_purpose: RunPurpose = RunPurpose.PRODUCTION,
    allow_untrusted_web_supplement: bool = False,
) -> PublishedAgentRunExecution:
    store = dependencies.store
    run_id = f"run_{uuid4().hex[:8]}"
    checkpointer = dependencies.approval_resume_registry.checkpointer_for(run_id)
    manifest = load_agent_manifest(published_agent.manifest_path)
    result = run_with_langgraph(
        published_agent.manifest_path,
        question=question,
        runs_dir=dependencies.runs_dir,
        conversation_context=conversation_context,
        run_id=run_id,
        store=store,
        checkpointer=checkpointer,
        manifest=manifest,
        resolved_knowledge_bindings=published_agent.resolved_knowledge_bindings,
        configuration_store=dependencies.configuration_store,
        run_purpose=run_purpose,
        agent_id=published_agent.agent_id,
        agent_version_id=published_agent.agent_version_id,
        draft_id=published_agent.source_draft_id,
        allow_untrusted_web_supplement=allow_untrusted_web_supplement,
        published_agent_runtime_facts=published_agent.runtime_facts,
    )
    detail = store.get_run_detail(run_id)
    if detail is None:
        raise RuntimeError("Run artifacts were not persisted.")
    if detail.pending_approvals:
        execution_input = result.workflow_template_execution_input
        if execution_input is None:
            raise RuntimeError(
                "Run is waiting for approval without Workflow Template Execution Input."
            )
        dependencies.approval_resume_registry.put(
            LangGraphApprovalResumeContext(
                agent_yaml=published_agent.manifest_path,
                runs_dir=store.history_dir / run_id,
                run_id=run_id,
                question=question,
                checkpointer=checkpointer,
                manifest=manifest,
                conversation_context=conversation_context,
                resolved_knowledge_bindings=published_agent.resolved_knowledge_bindings,
                configuration_store=dependencies.configuration_store,
                run_purpose=detail.run_purpose,
                agent_id=published_agent.agent_id,
                agent_version_id=published_agent.agent_version_id,
                draft_id=published_agent.source_draft_id,
                allow_untrusted_web_supplement=allow_untrusted_web_supplement,
                workflow_template_execution_input=execution_input,
            )
        )
    return PublishedAgentRunExecution(result=result, detail=detail, manifest=manifest)
```

Modify `proof_agent/delivery/api.py` so `_execute_published_agent_run(...)` constructs `RunExecutionDependencies`, calls `execute_published_agent_run(...)`, maps `ProofAgentError` to the same HTTP 400 response, and returns:

```python
execution = execute_published_agent_run(...)
return execution.result, execution.detail, execution.manifest
```

Keep the default route behavior as `RunPurpose.PRODUCTION`.

- [ ] **Step 4: Implement the Run Execution sample adapter**

Create `proof_agent/evaluation/run_execution_samples.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from proof_agent.contracts import EvaluationResponseProjectionAudience, RunPurpose
from proof_agent.delivery.published_agents import PublishedAgentRegistry
from proof_agent.delivery.run_execution_service import (
    RunExecutionDependencies,
    execute_published_agent_run,
)
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.sample_production import EvaluationSampleRequest, EvaluationSampleRun
from proof_agent.observability.storage.run_store import RunStore


class RunExecutionApiEvaluationSampleRunner:
    def __init__(self, app: Any) -> None:
        self._app = app

    def __call__(self, request: EvaluationSampleRequest) -> EvaluationSampleRun:
        registry = cast(PublishedAgentRegistry, self._app.state.published_agents)
        published_agent = registry.resolve(request.target_agent_id)
        if published_agent is None:
            raise EvaluationInputError(f"Published Agent not found: {request.target_agent_id}")
        if (
            request.target_agent_version_id is not None
            and published_agent.agent_version_id is not None
            and request.target_agent_version_id != published_agent.agent_version_id
        ):
            raise EvaluationInputError(
                "Evaluation target Agent Version does not match active published Agent Version: "
                f"{request.target_agent_version_id}"
            )

        store = cast(RunStore, self._app.state.store)
        execution = execute_published_agent_run(
            dependencies=RunExecutionDependencies(
                store=store,
                runs_dir=cast(Path, self._app.state.runs_dir),
                configuration_store=self._app.state.agent_configuration_store,
                approval_resume_registry=self._app.state.approval_resume_registry,
            ),
            published_agent=published_agent,
            question=request.question,
            run_purpose=RunPurpose.EVALUATION_SAMPLE,
        )
        response_path = store.history_dir / execution.detail.run_id / "operator_response.txt"
        response_path.write_text(execution.result.final_output, encoding="utf-8")
        return EvaluationSampleRun(
            case_ref=request.case_ref,
            run_id=execution.detail.run_id,
            response_projection_ref=Path("operator_response.txt"),
            response_projection_audience=EvaluationResponseProjectionAudience.OPERATOR,
        )
```

- [ ] **Step 5: Run the adapter-backed Campaign test and verify GREEN**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_evaluation_run_execution_samples.py::test_campaign_uses_run_execution_api_adapter_for_evaluation_samples -v
```

Expected: PASS.

### Slice 2: Target Version Mismatch Is Rejected

**Files:**
- Modify: `tests/test_evaluation_run_execution_samples.py`
- Modify: `proof_agent/evaluation/run_execution_samples.py`

- [ ] **Step 1: Write the failing target-version guard test**

Add:

```python
import pytest
from proof_agent.contracts import EvaluationCaseRef
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.sample_production import EvaluationSampleRequest


def test_run_execution_sample_runner_rejects_target_version_mismatch(tmp_path: Path) -> None:
    app = _app_with_published_agent(
        tmp_path,
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
    )
    runner = RunExecutionApiEvaluationSampleRunner(app)

    with pytest.raises(EvaluationInputError, match="does not match active published Agent Version"):
        runner(
            EvaluationSampleRequest(
                case_ref=EvaluationCaseRef(case_id="supported"),
                question="What is the reimbursement rule for travel meals?",
                target_agent_id="enterprise_qa",
                target_agent_version_id="wrong_version",
            )
        )
```

- [ ] **Step 2: Run the guard test and verify RED**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_evaluation_run_execution_samples.py::test_run_execution_sample_runner_rejects_target_version_mismatch -v
```

Expected: FAIL until `RunExecutionApiEvaluationSampleRunner` rejects mismatched target versions even when the configured fixture has an active version.

- [ ] **Step 3: Implement minimal version guard**

In `RunExecutionApiEvaluationSampleRunner.__call__`, reject when `request.target_agent_version_id` is not `None` and differs from `published_agent.agent_version_id`.

- [ ] **Step 4: Run adapter tests and verify GREEN**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest tests/test_evaluation_run_execution_samples.py -v
```

Expected: PASS.

### Slice 3: Regression And Documentation

**Files:**
- Modify: `docs/evaluation-campaign-system.md`
- Modify: `docs/technical-design.md`

- [ ] **Step 1: Update implementation status**

Update Evaluation Campaign docs to say Slice 4 adds the Run Execution API-backed sample adapter, while Customer Run API sampling remains future work.

- [ ] **Step 2: Run targeted verification**

Run:

```bash
uv run --extra dev --extra dashboard python -m pytest \
  tests/test_evaluation_run_execution_samples.py \
  tests/test_evaluation_campaign_sample_production.py \
  tests/test_run_execution_api.py::test_chat_run_execution_starts_published_agent_and_persists_run \
  -v
uv run --extra dev ruff check \
  proof_agent/delivery/api.py \
  proof_agent/delivery/run_execution_service.py \
  proof_agent/evaluation/run_execution_samples.py \
  tests/test_evaluation_run_execution_samples.py
uv run --extra dev mypy \
  proof_agent/delivery/run_execution_service.py \
  proof_agent/evaluation/run_execution_samples.py \
  proof_agent/delivery/api.py
git diff --check
```

Expected: PASS for all targeted checks.

## Self-Review

- Spec coverage: this slice connects Campaign sample production to the first real application-facing execution semantics and preserves Analyzer read-only behavior.
- Placeholder scan: no `TBD`, `TODO`, or vague edge handling is used.
- Type consistency: the adapter satisfies `EvaluationSampleRunner`, returns `EvaluationSampleRun`, writes `operator_response.txt`, and persists generated runs with `RunPurpose.EVALUATION_SAMPLE`.
