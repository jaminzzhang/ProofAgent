# Proof Agent S0 V3 Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [FRAME | HIGH] Establish a green, strict, V3-only baseline and the immutable contracts that every later release Gate result must bind to.

**Architecture:** [FRAME | HIGH] Introduce a small provider-neutral `proof_agent.release` contract/verifier module, retain Controlled ReAct V3 execution directly under the Control Plane, and delete active legacy workflow, approval, customer, example, and local-execution surfaces without changing historical records.

**Tech Stack:** [KNOWN | HIGH] Pydantic v2, Python 3.12, Typer, pytest, React 19, TypeScript, Vitest, npm workspaces.

---

## Prerequisites and Exit Contract

- [ ] [KNOWN | HIGH] Start from the reviewed master plan and approved release-closure specification.
- [ ] [FRAME | HIGH] Work in the isolated implementation worktree created from the planning commit.
- [ ] [FRAME | HIGH] Exit only when root frontend build passes, the strict verifier is fail-closed, V3 is the only active template, `agent_management_insurance_specialist` is the only public example, and no production approval/customer/LangGraph/local-tool path remains.

## Task 1: Capture the Baseline and Add Deletion-Guard Tests

**Files:**

- Create: `tests/test_initial_production_inventory.py`
- Create: `dashboard/src/productionInventory.test.tsx`
- Create: `chat/src/productionInventory.test.tsx`
- Inspect: `pyproject.toml`, `package.json`, `packages/ui/package.json`

- [ ] [KNOWN | HIGH] Run the current baseline and save command output outside Git under `runs/planning/s0-baseline/`:

```bash
uv run --extra dev python -m pytest tests/ -q
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai mypy proof_agent
npm test
npm run build
```

[KNOWN | HIGH] Expected baseline: Python checks may pass, while `npm run build` fails because `@proofagent/ui` has no `build` script. Record any additional failure before changing code.

- [ ] [FRAME | HIGH] Write `tests/test_initial_production_inventory.py` first. It must assert:

```python
from pathlib import Path

import pytest

from proof_agent.control.workflow.templates import resolve_workflow_template
from proof_agent.errors import ProofAgentError


ROOT = Path(__file__).parents[1]


def test_only_v3_template_is_supported() -> None:
    assert resolve_workflow_template("react_enterprise_qa_v3").name == (
        "react_enterprise_qa_v3"
    )
    for removed in ("enterprise_qa", "react_enterprise_qa", "react_enterprise_qa_v2"):
        with pytest.raises(ProofAgentError):
            resolve_workflow_template(removed)


def test_only_one_public_agent_package_exists() -> None:
    packages = sorted(path.name for path in (ROOT / "examples").iterdir() if path.is_dir())
    assert packages == ["agent_management_insurance_specialist"]


def test_removed_runtime_and_fixture_paths_do_not_exist() -> None:
    removed = (
        "proof_agent/runtime",
        "proof_agent/evaluation/demo/fixtures/agentic_rag_example",
        "proof_agent/evaluation/demo/fixtures/enterprise_qa",
        "proof_agent/evaluation/demo/fixtures/react_enterprise_qa",
        "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v2",
    )
    assert [path for path in removed if (ROOT / path).exists()] == []
```

- [ ] [FRAME | HIGH] Add frontend inventory tests that render routers/navigation and assert `/operator` remains while `/customer` and `/approvals` links/routes are absent.
- [ ] [KNOWN | HIGH] Run the three new test files and confirm they fail for the current legacy inventory.
- [ ] [FRAME | HIGH] Commit only after later tasks make these guards green.

## Task 2: Close the Root Frontend Build Contract

**Files:**

- Modify: `packages/ui/package.json`
- Modify: `package.json`

- [ ] [FRAME | HIGH] Add the missing workspace build alias without introducing an unnecessary emitted package format:

```json
"scripts": {
  "build": "tsc --noEmit",
  "typecheck": "tsc --noEmit"
}
```

- [ ] [FRAME | HIGH] Add explicit root typecheck aliases so CI can distinguish typechecking from asset builds:

```json
"typecheck": "npm run typecheck -ws --if-present"
```

- [ ] [KNOWN | HIGH] Run:

```bash
npm run typecheck
npm run build
```

[FRAME | HIGH] Expected result: both exit zero and `dashboard/dist/` plus `chat/dist/` exist; `@proofagent/ui` is validated as a source-exported workspace.

- [ ] [FRAME | HIGH] Commit with message `Fix root frontend build contract`.

## Task 3: Define Strict Release Contracts and the Immutable Gate Profile

**Files:**

- Create: `proof_agent/release/__init__.py`
- Create: `proof_agent/release/contracts.py`
- Create: `proof_agent/release/profiles/initial-private-pilot-v1.json`
- Create: `tests/test_release_contracts.py`
- Modify: `proof_agent/contracts/_base.py` only if the existing frozen/forbid base cannot be reused cleanly

- [ ] [FRAME | HIGH] Write failing contract tests for unknown fields, duplicate Gate IDs, mutable image tags without a digest, missing sole-Agent binding, invalid SHA-256, and a profile that marks a required Gate optional.
- [ ] [FRAME | HIGH] Implement strict frozen models. Keep the public shape equivalent to:

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Sha256 = str
GateStatus = Literal["passed", "failed", "skipped", "error", "not_run"]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DigestRef(StrictFrozenModel):
    sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    length: int = Field(ge=0)


class ProductionCandidateBinding(StrictFrozenModel):
    schema_version: Literal["proofagent.candidate-binding.v1"]
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    clean_tree: Literal[True]
    product_version: str = Field(min_length=1)
    oci_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    python_distribution: DigestRef
    dashboard_assets: DigestRef
    operator_chat_assets: DigestRef
    migration_set: DigestRef
    agent_id: Literal["agent_management_insurance_specialist"]
    agent_version: str = Field(min_length=1)
    agent_bundle: DigestRef
    evaluation_contract: DigestRef
    configuration_snapshot: DigestRef
    gate_profile: DigestRef
    deployment_compatibility_manifest: DigestRef


class EvidenceRef(StrictFrozenModel):
    evidence_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    digest: DigestRef
    candidate_binding_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    produced_at: datetime
    expires_at: datetime | None = None


class GateResult(StrictFrozenModel):
    gate_id: str = Field(min_length=1)
    status: GateStatus
    candidate_binding_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: tuple[EvidenceRef, ...]
    metrics: dict[str, float | int | str | bool]
    blocker_codes: tuple[str, ...] = ()


class ReleaseGateManifest(StrictFrozenModel):
    schema_version: Literal["proofagent.release-gate-manifest.v1"]
    profile_id: Literal["initial-private-pilot-v1"]
    candidate: ProductionCandidateBinding
    results: tuple[GateResult, ...]
    generated_at: datetime

    @model_validator(mode="after")
    def unique_gate_ids(self) -> "ReleaseGateManifest":
        ids = [result.gate_id for result in self.results]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate gate_id")
        return self
```

- [ ] [FRAME | HIGH] Store the immutable profile as data owned by the package. Its exact 13 required IDs are:

```json
{
  "schema_version": "proofagent.gate-profile.v1",
  "profile_id": "initial-private-pilot-v1",
  "required_gate_ids": [
    "backend_frontend_quality",
    "distribution_image",
    "supply_chain_runtime_security",
    "identity_authorization",
    "secrets_egress",
    "deterministic_evaluation",
    "real_llm_evaluation",
    "dependency_compatibility",
    "capacity_responsiveness",
    "queue_progress",
    "resilience_recovery",
    "deployment",
    "browser_operations"
  ]
}
```

- [ ] [FRAME | HIGH] Export only provider-neutral contracts from `proof_agent/release/__init__.py`.
- [ ] [KNOWN | HIGH] Run `uv run --extra dev python -m pytest tests/test_release_contracts.py -v` and expect a clean pass.
- [ ] [FRAME | HIGH] Commit with message `Add strict release candidate contracts`.

## Task 4: Implement the Fail-Closed Manifest Verifier

**Files:**

- Create: `proof_agent/release/digests.py`
- Create: `proof_agent/release/profile.py`
- Create: `proof_agent/release/verifier.py`
- Create: `tests/test_release_verifier.py`
- Modify: `proof_agent/delivery/cli.py`

- [ ] [FRAME | HIGH] Write parameterized red tests for every decision-table row: all pass, required non-pass status, missing/unknown result, digest mismatch, binding mismatch, stale evidence, missing expiry where required, invalid attestation, incomplete compatibility binding, insufficient sample, threshold miss, and expired deploy window.
- [ ] [FRAME | HIGH] Implement pure verification with no network calls. Use a result contract equivalent to:

```python
class ReleaseDecision(StrictFrozenModel):
    decision: Literal["GO", "NO-GO"]
    candidate_binding_sha256: Sha256
    checked_at: datetime
    blocker_codes: tuple[str, ...]


def verify_release_manifest(
    manifest: ReleaseGateManifest,
    *,
    checked_at: datetime,
    artifact_reader: ArtifactReader,
    attestation_verifier: AttestationVerifier,
) -> ReleaseDecision:
    """Recompute every digest, binding, freshness, threshold and required status."""
```

- [ ] [FRAME | HIGH] Keep freshness policy in the immutable profile: vulnerability 24 hours; dependency, real-LLM, load, fault, browser, and Blue/Green 72 hours; combined restore 30 days plus topology/backup/migration invalidation; deployment within 24 hours of the decision and before earliest expiry.
- [ ] [FRAME | HIGH] Reject local mutable paths such as `runs/latest`, mutable OCI tags, unknown fields/results, duplicate results, and any required status other than `passed`.
- [ ] [FRAME | HIGH] Add `proof-agent release verify --manifest PATH --evidence-root PATH --at RFC3339` with JSON output and exit 0 only for `GO`; exit 1 for valid `NO-GO`; exit 2 for invalid input.
- [ ] [KNOWN | HIGH] Run the focused tests and CLI help/smoke.
- [ ] [FRAME | HIGH] Commit with message `Implement fail-closed release manifest verifier`.

## Task 5: Move Retained V3 Helpers Out of the Runtime Package

**Files:**

- Modify: `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_execution.py`
- Modify: `proof_agent/control/workflow/controlled_react/composition.py`
- Modify: `proof_agent/control/workflow/controlled_react/orchestrator.py`
- Modify: `proof_agent/delivery/agent_package_execution.py`
- Modify: `proof_agent/delivery/run_execution_service.py`
- Create or modify focused modules under: `proof_agent/control/workflow/controlled_react/`
- Delete after all imports are gone: `proof_agent/runtime/`
- Modify: `tests/test_dependency_layout.py`

- [ ] [FRAME | HIGH] Add a failing dependency-layout assertion that no tracked Python module imports `proof_agent.runtime`, `langgraph`, or `langchain`.
- [ ] [KNOWN | HIGH] Use `rg -n 'proof_agent\.runtime|langgraph|langchain' proof_agent tests pyproject.toml` to inventory imports before moving code.
- [ ] [FRAME | HIGH] Move only V3-neutral DTO conversion, node context, and Controlled ReAct stage adapters into focused Control Plane modules. Do not copy the LangGraph runner, graph/checkpointer, interrupt/resume registry, or approval state machine.
- [ ] [FRAME | HIGH] Change execution composition to call the existing Controlled ReAct orchestrator directly for `react_enterprise_qa_v3`.
- [ ] [FRAME | HIGH] Delete `proof_agent/runtime/` only after focused Controlled ReAct, workflow, run-execution, trace, and receipt tests pass without it.
- [ ] [FRAME | HIGH] Remove `langgraph` from base dependencies and regenerate `uv.lock`; remove any now-unused LangChain packages as confirmed by `uv tree` and import search.
- [ ] [KNOWN | HIGH] Run:

```bash
uv run --extra dev python -m pytest \
  tests/test_controlled_react_orchestrator.py \
  tests/test_workflow_react_enterprise_qa.py \
  tests/test_run_execution_service.py \
  tests/test_dependency_layout.py -v
uv run --extra dev python -m pytest tests/ -q
```

- [ ] [FRAME | HIGH] Commit with message `Move V3 execution out of legacy runtime`.

## Task 6: Make Workflow Support V3-Only

**Files:**

- Modify: `proof_agent/control/workflow/templates.py`
- Modify: `proof_agent/contracts/manifest.py`
- Modify: `proof_agent/bootstrap/manifest.py`
- Modify: `proof_agent/bootstrap/validation.py`
- Modify: `proof_agent/bootstrap/composition.py`
- Modify: `proof_agent/delivery/agent_package_execution.py`
- Modify: `dashboard/src/components/agent/WorkflowModuleEditor.tsx`
- Modify: `dashboard/src/components/agent/module-configs/workflow.ts`
- Modify: `dashboard/src/hooks/useWorkflowTemplates.ts`
- Delete: `proof_agent/evaluation/demo/fixtures/agentic_rag_example/`
- Delete: `proof_agent/evaluation/demo/fixtures/enterprise_qa/`
- Delete: `proof_agent/evaluation/demo/fixtures/react_enterprise_qa/`
- Delete: `proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v2/`
- Retain and realign: `proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/`
- Delete after helper extraction/import closure: `proof_agent/control/workflow/react_enterprise_qa.py`
- Delete after helper extraction/import closure: `proof_agent/control/workflow/react_enterprise_qa_execution.py`
- Delete after helper extraction/import closure: `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- Delete after helper extraction/import closure: `proof_agent/control/workflow/nodes.py`
- Modify/delete the legacy workflow tests returned by the inventory search

- [ ] [FRAME | HIGH] Make the template registry expose only `react_enterprise_qa_v3` and reject all removed IDs at load, validation, import, publication, and execution boundaries.
- [ ] [FRAME | HIGH] Remove `WorkflowConfig.runtime`, `WorkflowConfig.checkpointer`, `CheckpointerConfig`, and legacy `ReactConfig.max_steps`; make the V3 `max_plan_rounds`/dual-axis budget explicit and reject removed YAML fields rather than silently ignoring them.
- [ ] [FRAME | HIGH] Realign the retained deterministic fixture with the sole Agent semantics: V3 Controlled ReAct, read-only behavior, no approval, no stdio/local handler, and no customer-mode promise.
- [ ] [FRAME | HIGH] Update Dashboard template selection and tests to show only V3; remove UI copy and YAML generation for V1/V2.
- [ ] [KNOWN | HIGH] Verify no active code or current docs claim removed templates are supported:

```bash
rg -n 'agentic_rag_example|enterprise_qa|react_enterprise_qa_v2|runtime: langgraph' \
  proof_agent dashboard chat examples tests docs \
  --glob '!docs/adr/**' --glob '!docs/superpowers/specs/**' --glob '!docs/superpowers/plans/**'
```

[FRAME | HIGH] Expected result: zero active support references; historical ADRs and dated specs may remain.

- [ ] [FRAME | HIGH] Commit with message `Cut active workflow support to Controlled ReAct V3`.

## Task 7: Remove Approval and Customer Production Surfaces

**Files:**

- Delete: `proof_agent/observability/api/routers/approvals.py`
- Delete: `proof_agent/delivery/customer_api.py`
- Delete: `proof_agent/delivery/customer_adapters.py`
- Delete: `proof_agent/observability/storage/customer_store.py`
- Delete: `proof_agent/observability/storage/handoff_projection.py`
- Delete: `proof_agent/observability/api/routers/handoffs.py`
- Delete: `proof_agent/contracts/handoff.py`
- Delete: `proof_agent/capabilities/tools/approval.py` after retained V3 callers no longer depend on it
- Delete: `proof_agent/runtime/approval_resume.py` if not already removed
- Modify: `proof_agent/observability/api/app.py`
- Modify: `proof_agent/delivery/run_execution_service.py`
- Delete: `dashboard/src/pages/ApprovalsPage.tsx`
- Delete: `dashboard/src/pages/HandoffsPage.tsx`
- Delete: `dashboard/src/pages/tabs/ApprovalTab.tsx`
- Delete: `dashboard/src/hooks/useApprovals.ts`
- Modify: `dashboard/src/router.tsx`, `dashboard/src/components/Sidebar.tsx`, `dashboard/src/pages/RunDetailPage.tsx`
- Delete: `chat/src/modes/customer/`
- Modify: `chat/src/router.tsx`, `chat/src/App.tsx`, `chat/src/pages/ModeSelectionPage.tsx`, `chat/src/i18n/messages.ts`
- Delete or rewrite: `tests/test_api_approvals.py`, `tests/test_approval_resume.py`, all `tests/test_customer_*.py`, approval/customer frontend tests

- [ ] [FRAME | HIGH] Write backend route tests first: all approval command endpoints and `/api/customer/*` return 404; completed historical approval facts remain visible only as inert run/audit fields.
- [ ] [FRAME | HIGH] Remove router registration, state stores, resume registry, handoff command/projection surfaces, frontend pages/routes/actions, customer seed data, and customer-only adapters.
- [ ] [FRAME | HIGH] Preserve generic conversation/run contracts only where Operator Chat still needs them; remove customer identity/ownership semantics that no active operator path consumes.
- [ ] [FRAME | HIGH] Ensure `approval.resolve` is absent from permissions/contracts and publication rejects approval-required tools.
- [ ] [FRAME | HIGH] Run backend and frontend inventory tests, then full frontend tests/build.
- [ ] [FRAME | HIGH] Commit with message `Remove approval and customer production surfaces`.

## Task 8: Retain Only the Sole Public Agent and Remove Local Execution Dependencies

**Files:**

- Delete: `examples/institution_insurance_specialist/`
- Delete: `examples/insurance_customer_service/`
- Modify: `examples/agent_management_insurance_specialist/agent.yaml`
- Modify: `examples/agent_management_insurance_specialist/tools.yaml`
- Delete: `examples/agent_management_insurance_specialist/tools.py`
- Modify: `proof_agent/delivery/cli.py`
- Modify: `proof_agent/observability/api/app.py`
- Modify: Dashboard seed/template files and tests returned by `rg -n 'insurance_customer_service|institution_insurance_specialist'`
- Modify/delete: active example tests and current documentation
- Modify: `pyproject.toml`, `uv.lock`

- [ ] [FRAME | HIGH] Update the sole example to `runtime: controlled_react`, template/descriptor V3, and no approval-required or local/stdio tool declaration. S5 will later replace package-local production bindings with PostgreSQL/S3/Secret Handle references.
- [ ] [FRAME | HIGH] Change all local development seed constants to `examples/agent_management_insurance_specialist/agent.yaml`.
- [ ] [FRAME | HIGH] Remove the unauthenticated public `cloudflared` quick-tunnel path from `verify-remote`; retain a local-only verification Gateway, and require production remote access to use the authenticated stable Gateway designed in S6.
- [ ] [FRAME | HIGH] Remove `langchain-mcp-adapters` and `mcp[cli]` from the base production dependency set. If deterministic development fixtures still need protocol DTOs, isolate them in an explicit non-production optional extra and prove the production image does not install it.
- [ ] [FRAME | HIGH] Delete extra public Agent packages and update active docs/tests without rewriting historical ADRs, dated specs, or Git history.
- [ ] [KNOWN | HIGH] Run:

```bash
rg -n 'insurance_customer_service|institution_insurance_specialist|approval.resolve|transport: (stdio|local)' \
  proof_agent dashboard chat examples tests docs \
  --glob '!docs/adr/**' --glob '!docs/superpowers/specs/**' --glob '!docs/superpowers/plans/**'
uv run --extra dev proof-agent demo
uv run --extra dev proof-agent run \
  examples/agent_management_insurance_specialist/agent.yaml \
  --question "理赔处理中需要向代理人说明哪些材料要求？"
```

[FRAME | HIGH] Expected result: no active support references to removed Agents/routes/transports; deterministic V3 produces governed trace and Receipt artifacts.

- [ ] [FRAME | HIGH] Commit with message `Retain only the V3 insurance specialist Agent`.

## Task 9: S0 Full Verification and Review

- [ ] [KNOWN | HIGH] Run:

```bash
uv lock --check
uv run --extra dev python -m pytest tests/ -v
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai mypy proof_agent
npm run typecheck
npm test
npm run build
python3 scripts/check-domain-contexts.py
git diff --check
```

- [ ] [FRAME | HIGH] Run a clean-tree inventory script that fails on any active removed Agent/template/route/runtime/dependency/local-tool marker.
- [ ] [FRAME | HIGH] Ask an independent reviewer to compare the complete S0 diff with this plan and ADR-0124/0125, with special attention to accidental deletion of generic Operator Chat contracts and retained V3 helpers.
- [ ] [FRAME | HIGH] Resolve every P0/P1 review finding, rerun verification, record the final S0 commit in the master plan, and only then start S1.
