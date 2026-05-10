# Controlled Agent Harness v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Proof Agent v1 as a local-first, CLI-first Controlled Agent Harness Framework that proves workflow control, policy decisions, evidence validation, tool approval, memory boundaries, JSONL trace, and Governance Receipt through the enterprise QA reference template.

**Architecture:** Implement the public framework contract around `agent.yaml`, typed Pydantic models, a deterministic-first runtime path, a LangGraph-backed workflow adapter hidden behind Proof Agent interfaces, a self-built local Harness RAG provider, a Tool Gateway with one MCP mock tool, session memory, validators, JSONL trace, and a receipt generator. The deterministic demo and full enterprise QA run must share the same policy, evidence, approval, trace, receipt, and workflow contracts.

**Tech Stack:** Python 3.12+, `uv`, Typer, Pydantic v2, PyYAML, pytest, ruff, mypy, Jinja2, LangGraph 1.1.x, `mcp[cli]` stdio transport, `langchain-mcp-adapters`, sentence-transformers plus ChromaDB for local retrieval, Docker Compose, GitHub Actions.

---

## Source Documents Analyzed

- `README.md`
- `CLAUDE.md`
- `docs/Proof Agent PRD.md`
- `docs/Proof Agent Technical Plan.md`
- `docs/Proof Agent Test Plan.md`
- `docs/Proof Agent Engineering Review.md`
- `docs/Proof Agent Framework Design.md`
- `docs/Proof Agent 技术设计方案.md`
- `docs/superpowers/specs/2026-05-09-controlled-agent-harness-redesign.md`
- `docs/concepts/agent-contract.md`
- `docs/concepts/policy-engine.md`
- `docs/concepts/trace-event-contract.md`
- `docs/concepts/approval-state-contract.md`
- `docs/concepts/governance-receipt-contract.md`
- `docs/concepts/trust-boundaries.md`

## Planning Decisions

1. v1 keeps workflow selection inside `agent.yaml`; no public `workflow.yaml`.
2. v1 policy supports YAML rules only; Python policy hooks remain internal extension seams.
3. v1 Tool Gateway exposes named mock tools only; no generic high-level tool verbs.
4. v1 quality checks are deterministic validators; LLM-as-judge is outside the release gate.
5. Existing documentation filenames stay stable until code exists; implementation can add docs without reorganizing the repository.
6. The deleted working-tree file `docs/superpowers/plans/2026-05-09-proof-agent-v1.md` is treated as user-owned state and is not restored by this plan.
7. v1 knowledge retrieval follows `docs/Proof Agent 技术设计方案.md`: self-built lightweight RAG behind a `KnowledgeProvider` interface, with optional future Agentic/remote providers behind the same boundary.
8. JSONL trace is the audit source of truth. Governance Receipt generation must aggregate trace events, not read workflow-private state.
9. LangGraph, ChromaDB, and MCP SDK details remain in adapter/runtime modules and must not leak into public config, policy, trace, receipt, or contract models.

## File Structure Map

Final implementation shape. Create missing files and modify existing files as noted in each task:

```text
pyproject.toml
uv.lock
.env.example
Dockerfile
proof_agent/__init__.py
proof_agent/cli.py
proof_agent/errors.py
proof_agent/contracts/__init__.py
proof_agent/contracts/approval.py
proof_agent/contracts/evidence.py
proof_agent/contracts/manifest.py
proof_agent/contracts/policy.py
proof_agent/contracts/receipt.py
proof_agent/contracts/run.py
proof_agent/contracts/tool.py
proof_agent/contracts/trace.py
proof_agent/config/loader.py
proof_agent/config/manifest.py
proof_agent/config/validation.py
proof_agent/policy/engine.py
proof_agent/policy/loader.py
proof_agent/policy/rules.py
proof_agent/validators/evidence.py
proof_agent/validators/quality.py
proof_agent/validators/schema.py
proof_agent/validators/safety.py
proof_agent/validators/tool_result.py
proof_agent/knowledge/provider.py
proof_agent/knowledge/local_provider.py
proof_agent/knowledge/chunker.py
proof_agent/knowledge/citations.py
proof_agent/knowledge/evaluator.py
proof_agent/knowledge/index.py
proof_agent/workflow/state.py
proof_agent/workflow/nodes.py
proof_agent/workflow/orchestrator.py
proof_agent/workflow/routing.py
proof_agent/runtime/langgraph_runner.py
proof_agent/tools/approval.py
proof_agent/tools/gateway.py
proof_agent/tools/mcp_mock.py
proof_agent/tools/registry.py
proof_agent/memory/session.py
proof_agent/audit/trace.py
proof_agent/audit/redaction.py
proof_agent/audit/receipt.py
proof_agent/audit/templates/governance_receipt.md.j2
proof_agent/demo/deterministic_provider.py
proof_agent/demo/scenarios.py
proof_agent/compare/plain_rag.py
proof_agent/compare/harness_rag.py
examples/enterprise_qa/agent.yaml
examples/enterprise_qa/policy.yaml
examples/enterprise_qa/tools.yaml
examples/enterprise_qa/questions.yaml
examples/enterprise_qa/README.md
examples/enterprise_qa/knowledge/customer-support-policy.md
examples/enterprise_qa/knowledge/discount-policy.md
examples/enterprise_qa/expected/governance_receipt.md
examples/enterprise_qa/expected/trace.jsonl
runs/.gitkeep
docker-compose.yml
.github/workflows/ci.yml
```

Create these tests:

```text
tests/test_cli.py
tests/test_contracts.py
tests/test_config_loader.py
tests/test_policy_engine.py
tests/test_trace_writer.py
tests/test_receipt_generator.py
tests/test_knowledge_provider.py
tests/test_evidence_validator.py
tests/test_tool_gateway.py
tests/test_memory_boundary.py
tests/test_workflow_enterprise_qa.py
tests/test_compare.py
tests/test_trust_boundaries.py
```

Responsibilities:

- `contracts/` owns public enums and immutable Pydantic data models. `contracts/__init__.py` re-exports the stable public API used by tests and downstream users.
- `errors.py` owns stable error codes and user-facing remediation text.
- `config/` loads and validates `agent.yaml`, `policy.yaml`, and `tools.yaml`.
- `policy/` evaluates YAML rules at the four enforcement points.
- `knowledge/` owns the `KnowledgeProvider` interface, local Markdown chunking, local indexing, retrieval, evidence scoring, and citation ids.
- `validators/` owns deterministic schema, evidence, tool result, safety, and quality checks.
- `workflow/` owns Proof Agent workflow state and orchestration semantics.
- `runtime/` adapts workflow orchestration to LangGraph without leaking LangGraph types into contracts.
- `tools/` owns approval state, allowlist/risk checks, parameter guards, MCP stdio mock registration, and normalized tool results.
- `memory/` owns session-only memory and policy-gated writes.
- `audit/` owns JSONL trace, redaction, receipt template rendering, and receipt generation from trace events.
- `demo/` owns API-key-free deterministic scenarios.
- `compare/` owns Plain RAG vs Harness RAG command behavior.

## Task 1: Package And CLI Scaffold

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `proof_agent/__init__.py`
- Modify: `proof_agent/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Confirm or adjust CLI smoke tests**

```python
# tests/test_cli.py
from typer.testing import CliRunner

from proof_agent.cli import app


runner = CliRunner()


def test_demo_command_exists() -> None:
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 0
    assert "Proof Agent demo" in result.output


def test_doctor_command_exists() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Python" in result.output
```

- [ ] **Step 2: Run the baseline tests**

Run: `python -m pytest tests/test_cli.py -v`

Expected: PASS on the current scaffold. If running from a clean checkout before install, FAIL with `ModuleNotFoundError: No module named 'proof_agent'` is acceptable and should be resolved by Step 4.

- [ ] **Step 3: Update package metadata and keep the minimal Typer app**

```toml
# pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "proof-agent"
version = "0.1.0"
description = "Local-first Controlled Agent Harness Framework"
requires-python = ">=3.12"
dependencies = [
  "typer>=0.12.0",
  "pydantic>=2.7.0",
  "pyyaml>=6.0.1",
  "jinja2>=3.1.0",
  "langgraph>=1.1.0",
  "langchain-mcp-adapters>=0.1.0",
  "mcp[cli]>=1.27.0",
  "sentence-transformers>=3.0.0",
  "chromadb>=1.5.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0.0", "ruff>=0.5.0", "mypy>=1.10.0"]

[project.scripts]
proof-agent = "proof_agent.cli:main"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.mypy]
python_version = "3.12"
strict = true
```

```python
# proof_agent/__init__.py
__version__ = "0.1.0"
```

```python
# proof_agent/cli.py
import typer

app = typer.Typer(no_args_is_help=True)


@app.command()
def demo() -> None:
    typer.echo("Proof Agent demo")


@app.command()
def run(agent_yaml: str) -> None:
    typer.echo(f"Running {agent_yaml}")


@app.command()
def doctor() -> None:
    typer.echo("Python: ok")


@app.command()
def inspect(path: str) -> None:
    typer.echo(f"Inspecting {path}")


@app.command()
def compare(agent_yaml: str, question: str = typer.Option(..., "--question")) -> None:
    typer.echo(f"Comparing {agent_yaml}: {question}")


def main() -> None:
    app()
```

- [ ] **Step 4: Generate lockfile and install editable package**

Run: `uv lock && uv pip install -e ".[dev]"`

Expected: `uv.lock` is created and the `proof-agent` console script is available in the active environment.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_cli.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock proof_agent/__init__.py proof_agent/cli.py tests/test_cli.py
git commit -m "Add package and CLI scaffold"
```

## Task 2: Core Contracts And Error Codes

**Files:**
- Move/Replace: `proof_agent/contracts.py`
- Create: `proof_agent/contracts/__init__.py`
- Create: `proof_agent/contracts/approval.py`
- Create: `proof_agent/contracts/evidence.py`
- Create: `proof_agent/contracts/manifest.py`
- Create: `proof_agent/contracts/policy.py`
- Create: `proof_agent/contracts/receipt.py`
- Create: `proof_agent/contracts/run.py`
- Create: `proof_agent/contracts/tool.py`
- Create: `proof_agent/contracts/trace.py`
- Modify: `proof_agent/errors.py`
- Modify: `tests/test_contracts.py`

- [ ] **Step 1: Write or extend contract tests**

```python
# tests/test_contracts.py
from proof_agent.contracts import EnforcementPoint, PolicyDecision, PolicyDecisionType, ReceiptOutcome
from proof_agent.errors import ProofAgentError


def test_policy_decision_is_typed_and_traceable() -> None:
    decision = PolicyDecision(
        decision=PolicyDecisionType.ALLOW,
        enforcement_point=EnforcementPoint.BEFORE_ANSWER,
        reason="Evidence is sufficient.",
        policy_rule_id="answering.require_retrieval",
        metadata={"accepted_evidence_count": 2},
        trace_event_id="evt_0003",
    )
    assert decision.decision == PolicyDecisionType.ALLOW
    assert decision.trace_event_id == "evt_0003"


def test_receipt_outcomes_match_contract() -> None:
    assert ReceiptOutcome.ANSWERED_WITH_CITATIONS.value == "ANSWERED_WITH_CITATIONS"
    assert ReceiptOutcome.FAILED_RECEIPT_UNAVAILABLE.value == "FAILED_RECEIPT_UNAVAILABLE"


def test_error_message_contains_fix() -> None:
    error = ProofAgentError("PA_CONFIG_001", "missing policy.file", "Add policy.file to agent.yaml")
    assert "Fix: Add policy.file to agent.yaml" in str(error)
```

- [ ] **Step 2: Run contract tests before migration**

Run: `python -m pytest tests/test_contracts.py -v`

Expected: current scaffold may PASS. After adding tests for split contract modules or missing models, FAIL until the migration in Step 3 is complete.

- [ ] **Step 3: Implement immutable models and errors**

Replace the existing flat `proof_agent/contracts.py` with focused contract modules using Pydantic models and `ConfigDict(frozen=True)`. Re-export the public contract names from `proof_agent/contracts/__init__.py` so callers can continue importing from `proof_agent.contracts`. Include these enums exactly:

```python
class PolicyDecisionType(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    ESCALATE = "escalate"


class EnforcementPoint(str, Enum):
    BEFORE_RETRIEVAL = "before_retrieval"
    BEFORE_ANSWER = "before_answer"
    BEFORE_TOOL_CALL = "before_tool_call"
    BEFORE_MEMORY_WRITE = "before_memory_write"
```

Add `AgentManifest`, `PolicyRule`, `EvidenceChunk`, `ApprovalStatus`, `ApprovalState`, `TraceEvent`, `ReceiptOutcome`, `WorkflowState`, `ToolRequest`, `ValidationResult`, and `RunResult` with fields from `docs/Proof Agent Technical Plan.md`. Keep LangGraph, ChromaDB, and MCP types out of these models.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_contracts.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/contracts proof_agent/errors.py tests/test_contracts.py
git commit -m "Add core contracts and error codes"
```

## Task 3: Config Loader And Enterprise QA Template Files

**Files:**
- Create: `proof_agent/config/loader.py`
- Create: `proof_agent/config/manifest.py`
- Create: `proof_agent/config/validation.py`
- Create: `tests/test_config_loader.py`
- Create: `examples/enterprise_qa/agent.yaml`
- Create: `examples/enterprise_qa/policy.yaml`
- Create: `examples/enterprise_qa/tools.yaml`
- Create: `examples/enterprise_qa/questions.yaml`
- Create: `examples/enterprise_qa/knowledge/customer-support-policy.md`
- Create: `examples/enterprise_qa/knowledge/discount-policy.md`

- [ ] **Step 1: Write failing config tests**

```python
# tests/test_config_loader.py
from pathlib import Path

import pytest

from proof_agent.config.loader import load_agent_manifest
from proof_agent.errors import ProofAgentError


def test_load_valid_enterprise_qa_manifest() -> None:
    manifest = load_agent_manifest(Path("examples/enterprise_qa/agent.yaml"))
    assert manifest.name == "enterprise_qa"
    assert manifest.workflow.runtime == "langgraph"
    assert manifest.knowledge.provider == "local"


def test_missing_policy_file_fails_fast(tmp_path: Path) -> None:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    agent_yaml.write_text(
        """
name: broken
purpose: "Broken manifest."
workflow:
  runtime: langgraph
  template: enterprise_qa
knowledge:
  provider: local
  path: ./knowledge
model:
  provider: deterministic
  name: demo
tools:
  file: ./tools.yaml
memory:
  provider: session
audit:
  trace_path: ../../runs/latest/trace.jsonl
  receipt_path: ../../runs/latest/governance_receipt.md
""",
        encoding="utf-8",
    )
    with pytest.raises(ProofAgentError) as exc:
        load_agent_manifest(agent_yaml)
    assert exc.value.code == "PA_CONFIG_001"
```

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest tests/test_config_loader.py -v`

Expected: FAIL because `load_agent_manifest` does not exist.

- [ ] **Step 3: Add example configs**

Use this exact `agent.yaml` shape:

```yaml
name: enterprise_qa
purpose: "Answer enterprise knowledge questions only when evidence supports the answer."

workflow:
  runtime: langgraph
  template: enterprise_qa

knowledge:
  provider: local
  path: ./knowledge

model:
  provider: deterministic
  name: demo

policy:
  file: ./policy.yaml

tools:
  file: ./tools.yaml

memory:
  provider: session

audit:
  trace_path: ../../runs/latest/trace.jsonl
  receipt_path: ../../runs/latest/governance_receipt.md
```

Use `policy.yaml` rules for `answering.require_retrieval`, `tools.customer_lookup.approval`, and `memory.deny_sensitive_fields`. Use `tools.yaml` with one tool named `customer_lookup`, `risk_level: medium`, `requires_approval: true`, and allowed parameters `customer_id` and `policy_id`.

- [ ] **Step 4: Implement loader**

`load_agent_manifest(path: Path) -> AgentManifest` must parse YAML, resolve relative file paths against the manifest directory, validate required fields, reject unsupported runtime/provider/memory values, check knowledge path existence, check audit parent writability, normalize `audit.trace_path` and `audit.receipt_path`, and raise `ProofAgentError` with codes from the technical plan.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_config_loader.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/config examples/enterprise_qa tests/test_config_loader.py
git commit -m "Add agent config loader and enterprise QA template"
```

## Task 4: JSONL Trace, Redaction, And Receipt Shell

**Files:**
- Create: `proof_agent/audit/trace.py`
- Create: `proof_agent/audit/redaction.py`
- Create: `proof_agent/audit/receipt.py`
- Create: `proof_agent/audit/templates/governance_receipt.md.j2`
- Create: `tests/test_trace_writer.py`
- Create: `tests/test_receipt_generator.py`

- [ ] **Step 1: Write failing trace and receipt tests**

```python
# tests/test_trace_writer.py
import json
from pathlib import Path

from proof_agent.audit.trace import TraceWriter


def test_trace_writer_emits_ordered_jsonl(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    writer = TraceWriter(trace_path, run_id="run_test")
    writer.emit("run_started", status="ok", payload={"manifest_path": "agent.yaml"})
    writer.emit("final_output", status="ok", payload={"outcome": "ANSWERED_WITH_CITATIONS"})
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["sequence"] for line in lines] == [1, 2]


def test_trace_writer_redacts_secret_payload(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    writer = TraceWriter(trace_path, run_id="run_test")
    writer.emit("tool_request", status="ok", payload={"access_token": "secret-token"})
    event = json.loads(trace_path.read_text(encoding="utf-8"))
    assert "secret-token" not in event["payload"].values()
    assert event["redaction"]["applied"] is True
```

```python
# tests/test_receipt_generator.py
from pathlib import Path

from proof_agent.audit.receipt import generate_receipt


def test_receipt_contains_required_sections(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    receipt_path = tmp_path / "governance_receipt.md"
    trace_path.write_text(
        '{"schema_version":"trace.v1","run_id":"run_test","event_id":"evt_0001","sequence":1,"timestamp":"2026-05-09T00:00:00Z","event_type":"final_output","span_id":"span_final","parent_span_id":null,"status":"ok","payload":{"agent_name":"enterprise_qa","question":"What is the travel meal rule?","outcome":"ANSWERED_WITH_CITATIONS"},"redaction":{"applied":false,"fields":[]}}\\n',
        encoding="utf-8",
    )
    generate_receipt(trace_path, receipt_path)
    text = receipt_path.read_text(encoding="utf-8")
    assert "# Governance Receipt" in text
    assert "Final Outcome" in text
```

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest tests/test_trace_writer.py tests/test_receipt_generator.py -v`

Expected: FAIL because audit modules do not exist.

- [ ] **Step 3: Implement trace writer and redaction**

`TraceWriter.emit()` must create the parent directory, assign `event_id` values like `evt_0001`, increment `sequence`, write one JSON object per line, and include `schema_version`, `run_id`, timestamp, `event_type`, `span_id`, `parent_span_id`, `status`, `payload`, and `redaction`.

Redact payload keys containing `api_key`, `access_token`, `bearer`, `password`, `secret`, `connection_string`, `customer_phone`, and `provider_api_key`.

- [ ] **Step 4: Implement receipt shell**

`generate_receipt(trace_path: Path, receipt_path: Path) -> None` must read JSONL, preserve trace on receipt errors, and render `audit/templates/governance_receipt.md.j2` with required sections: run id, timestamp, agent, question, final outcome, policy decisions, evidence, tools, memory, audit artifact paths, and redaction summary. The receipt generator must aggregate trace events only; do not pass workflow-private state into it.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_trace_writer.py tests/test_receipt_generator.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/audit tests/test_trace_writer.py tests/test_receipt_generator.py
git commit -m "Add trace writer and receipt generator"
```

## Task 5: Policy Engine

**Files:**
- Create: `proof_agent/policy/engine.py`
- Create: `proof_agent/policy/rules.py`
- Create: `tests/test_policy_engine.py`

- [ ] **Step 1: Write failing policy tests**

```python
# tests/test_policy_engine.py
from proof_agent.contracts import EnforcementPoint, PolicyDecisionType
from proof_agent.policy.engine import PolicyEngine


def test_before_answer_denies_weak_evidence() -> None:
    engine = PolicyEngine.from_file("examples/enterprise_qa/policy.yaml")
    decision = engine.evaluate(
        EnforcementPoint.BEFORE_ANSWER,
        {"accepted_evidence_count": 0, "citations_present": False},
    )
    assert decision.decision == PolicyDecisionType.DENY
    assert decision.policy_rule_id == "answering.require_retrieval"


def test_before_tool_call_requires_approval() -> None:
    engine = PolicyEngine.from_file("examples/enterprise_qa/policy.yaml")
    decision = engine.evaluate(
        EnforcementPoint.BEFORE_TOOL_CALL,
        {"tool_name": "customer_lookup", "risk_level": "medium"},
    )
    assert decision.decision == PolicyDecisionType.REQUIRE_APPROVAL
```

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest tests/test_policy_engine.py -v`

Expected: FAIL because `PolicyEngine` does not exist.

- [ ] **Step 3: Implement YAML rule evaluation**

Rules must support:

- `require_retrieval`, `min_evidence_count`, and `require_citations` at `before_answer`
- `tool_name` match at `before_tool_call`
- `deny_fields` match at `before_memory_write`
- unconditional allow for `before_retrieval` unless a rule denies it

Every evaluation returns a `PolicyDecision` with a reason, rule id, metadata, and trace event id value supplied by the caller or generated as an empty string for tests.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_policy_engine.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/policy tests/test_policy_engine.py
git commit -m "Add YAML policy engine"
```

## Task 6: Local Knowledge Provider And Evidence Validator

**Files:**
- Create: `proof_agent/knowledge/provider.py`
- Create: `proof_agent/knowledge/chunker.py`
- Create: `proof_agent/knowledge/index.py`
- Create: `proof_agent/knowledge/local_provider.py`
- Create: `proof_agent/knowledge/evaluator.py`
- Create: `proof_agent/knowledge/citations.py`
- Create: `proof_agent/validators/evidence.py`
- Create: `tests/test_knowledge_provider.py`
- Create: `tests/test_evidence_validator.py`

- [ ] **Step 1: Write failing knowledge and evidence tests**

```python
# tests/test_knowledge_provider.py
from pathlib import Path

from proof_agent.knowledge.local_provider import LocalKnowledgeProvider


def test_retrieval_returns_source_chunks() -> None:
    provider = LocalKnowledgeProvider(Path("examples/enterprise_qa/knowledge"))
    chunks = provider.retrieve("travel meal reimbursement", top_k=2)
    assert chunks
    assert chunks[0].source.endswith(".md")
    assert chunks[0].score > 0
```

```python
# tests/test_evidence_validator.py
from proof_agent.contracts import EvidenceChunk
from proof_agent.validators.evidence import evaluate_evidence


def test_enough_evidence_passes() -> None:
    chunks = [
        EvidenceChunk(source="customer-support-policy.md", content="Meals are reimbursed up to 50.", score=0.9, status="accepted"),
        EvidenceChunk(source="customer-support-policy.md", content="Receipts are required.", score=0.8, status="accepted"),
    ]
    result = evaluate_evidence(chunks, min_count=2, min_score=0.5)
    assert result.status == "passed"


def test_weak_evidence_fails() -> None:
    result = evaluate_evidence([], min_count=2, min_score=0.5)
    assert result.status == "failed"
```

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest tests/test_knowledge_provider.py tests/test_evidence_validator.py -v`

Expected: FAIL because knowledge and evidence modules do not exist.

- [ ] **Step 3: Define provider boundary and deterministic retrieval**

Define a `KnowledgeProvider` protocol/interface that returns standardized `EvidenceChunk` objects plus citation metadata. Implement Markdown loading, heading-aware chunking, lowercase token-overlap scoring, source ids, and citation labels as the deterministic fallback so `proof-agent demo` stays stable and offline.

- [ ] **Step 4: Add embedded local vector path**

Add `LocalKnowledgeIndex` using sentence-transformers `all-MiniLM-L6-v2` and ChromaDB `PersistentClient` when an index path is configured. The provider must keep ChromaDB and embedding details inside `knowledge/` and continue returning only `EvidenceChunk` contract objects.

- [ ] **Step 5: Implement evidence validation**

`evaluate_evidence()` must return a `ValidationResult` named `evidence` with `passed` only when accepted chunks meet `min_count` and `min_score`. Include rejected chunk counts and accepted source ids in metadata.

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_knowledge_provider.py tests/test_evidence_validator.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add proof_agent/knowledge proof_agent/validators/evidence.py tests/test_knowledge_provider.py tests/test_evidence_validator.py
git commit -m "Add local knowledge provider and evidence validation"
```

## Task 7: Deterministic Demo And Compare Paths

**Files:**
- Create: `proof_agent/demo/deterministic_provider.py`
- Create: `proof_agent/demo/scenarios.py`
- Create: `proof_agent/compare/plain_rag.py`
- Create: `proof_agent/compare/harness_rag.py`
- Modify: `proof_agent/cli.py`
- Create: `tests/test_compare.py`

- [ ] **Step 1: Write failing compare tests**

```python
# tests/test_compare.py
from proof_agent.compare.harness_rag import run_harness_rag
from proof_agent.compare.plain_rag import run_plain_rag


def test_plain_and_harness_diverge_on_unsupported_question() -> None:
    question = "What discount should we give this customer next year?"
    plain = run_plain_rag(question)
    harness = run_harness_rag(question)
    assert plain.outcome == "ANSWERED_LOOSELY"
    assert harness.outcome == "REFUSED_NO_EVIDENCE"
```

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest tests/test_compare.py -v`

Expected: FAIL because compare modules do not exist.

- [ ] **Step 3: Implement deterministic scenario outputs**

Add three scenarios:

- supported question: "What is the reimbursement rule for travel meals?"
- unsupported question: "What discount should we give this customer next year?"
- tool-required question: "Look up customer policy status before answering."

The deterministic provider may return fixed strings, but Harness RAG must still pass through retrieval, evidence evaluation, policy decision, trace, and receipt modules once workflow integration lands.

- [ ] **Step 4: Wire CLI `compare` to the compare modules**

`proof-agent compare examples/enterprise_qa/agent.yaml --question "..."` must print both Plain RAG and Harness RAG outcomes.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_compare.py tests/test_cli.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/demo proof_agent/compare proof_agent/cli.py tests/test_compare.py tests/test_cli.py
git commit -m "Add deterministic demo and RAG comparison"
```

## Task 8: Tool Gateway And Approval State

**Files:**
- Create: `proof_agent/tools/approval.py`
- Create: `proof_agent/tools/gateway.py`
- Create: `proof_agent/tools/mcp_mock.py`
- Create: `proof_agent/tools/registry.py`
- Create: `tests/test_tool_gateway.py`

- [ ] **Step 1: Write failing tool approval tests**

```python
# tests/test_tool_gateway.py
from proof_agent.contracts import ApprovalStatus
from proof_agent.tools.gateway import ToolGateway


def test_customer_lookup_requires_approval_before_execution() -> None:
    gateway = ToolGateway.from_file("examples/enterprise_qa/tools.yaml")
    result = gateway.request_tool(
        tool_name="customer_lookup",
        parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
        approved=False,
    )
    assert result.approval_state.state == ApprovalStatus.REQUESTED
    assert result.executed is False


def test_approved_customer_lookup_executes_mock_tool() -> None:
    gateway = ToolGateway.from_file("examples/enterprise_qa/tools.yaml")
    result = gateway.request_tool(
        tool_name="customer_lookup",
        parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
        approved=True,
    )
    assert result.approval_state.state == ApprovalStatus.GRANTED
    assert result.executed is True
```

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest tests/test_tool_gateway.py -v`

Expected: FAIL because tools modules do not exist.

- [ ] **Step 3: Implement approval state and gateway**

The gateway must validate allowlist, risk level, required parameters, denied parameters, and approval state. It must never execute the mock tool unless policy and approval allow execution.

- [ ] **Step 4: Implement MCP stdio mock behavior**

`customer_lookup` returns a normalized result containing `customer_id`, `policy_id`, `status`, and `source: "mcp_mock"`. Sensitive raw payloads must not be returned. Register the mock through `mcp[cli]` stdio transport and keep `langchain-mcp-adapters` conversion inside `tools/registry.py` or `runtime/langgraph_runner.py`; the Tool Gateway API must not expose MCP SDK objects.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_tool_gateway.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/tools tests/test_tool_gateway.py
git commit -m "Add tool gateway and approval state"
```

## Task 9: Memory Boundary And Validators

**Files:**
- Create: `proof_agent/memory/session.py`
- Create: `proof_agent/validators/schema.py`
- Create: `proof_agent/validators/safety.py`
- Create: `proof_agent/validators/tool_result.py`
- Create: `tests/test_memory_boundary.py`
- Create: `tests/test_trust_boundaries.py`

- [ ] **Step 1: Write failing memory and trust-boundary tests**

```python
# tests/test_memory_boundary.py
from proof_agent.memory.session import SessionMemory


def test_session_memory_rejects_sensitive_write() -> None:
    memory = SessionMemory(deny_fields={"access_token", "customer_phone"})
    result = memory.write({"summary": "ok", "access_token": "secret"})
    assert result.status == "failed"
    assert memory.read() == {}


def test_session_memory_allows_safe_summary() -> None:
    memory = SessionMemory(deny_fields={"access_token"})
    result = memory.write({"summary": "customer asked about travel meals"})
    assert result.status == "passed"
    assert memory.read()["summary"] == "customer asked about travel meals"
```

```python
# tests/test_trust_boundaries.py
from pathlib import Path

import pytest

from proof_agent.config.loader import load_agent_manifest
from proof_agent.errors import ProofAgentError


def test_persistent_memory_is_rejected_for_v1(tmp_path: Path) -> None:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\\n", encoding="utf-8")
    agent_yaml.write_text(
        """
name: broken
purpose: "Broken manifest."
workflow:
  runtime: langgraph
  template: enterprise_qa
knowledge:
  provider: local
  path: ./knowledge
model:
  provider: deterministic
  name: demo
policy:
  file: ./policy.yaml
tools:
  file: ./tools.yaml
memory:
  provider: persistent
audit:
  trace_path: ../../runs/latest/trace.jsonl
  receipt_path: ../../runs/latest/governance_receipt.md
""",
        encoding="utf-8",
    )
    with pytest.raises(ProofAgentError):
        load_agent_manifest(agent_yaml)
```

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest tests/test_memory_boundary.py tests/test_trust_boundaries.py -v`

Expected: FAIL because memory and validator modules do not exist or config does not reject persistent memory yet.

- [ ] **Step 3: Implement session memory**

Session memory stores only an in-process dictionary, emits validation results for writes, blocks denied fields, and supports `read()` and `clear()`.

- [ ] **Step 4: Implement validators**

Add deterministic validators for:

- schema: final output has `outcome`, `message`, and optional `citations`
- safety: no secret-like strings appear in output candidates
- tool result: mock result includes expected keys and `source == "mcp_mock"`

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_memory_boundary.py tests/test_trust_boundaries.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/memory proof_agent/validators tests/test_memory_boundary.py tests/test_trust_boundaries.py
git commit -m "Add memory boundary and validators"
```

## Task 10: Workflow Orchestrator And CLI Run/Demo Integration

**Files:**
- Create: `proof_agent/workflow/state.py`
- Create: `proof_agent/workflow/nodes.py`
- Create: `proof_agent/workflow/orchestrator.py`
- Create: `proof_agent/workflow/routing.py`
- Create: `proof_agent/runtime/langgraph_runner.py`
- Modify: `proof_agent/cli.py`
- Create: `tests/test_workflow_enterprise_qa.py`

- [ ] **Step 1: Write failing workflow tests**

```python
# tests/test_workflow_enterprise_qa.py
from pathlib import Path

from proof_agent.workflow.orchestrator import run_enterprise_qa


def test_supported_question_answers_with_citations(tmp_path: Path) -> None:
    result = run_enterprise_qa(
        Path("examples/enterprise_qa/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )
    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    assert result.trace_path.exists()
    assert result.receipt_path.exists()


def test_unsupported_question_refuses_without_evidence(tmp_path: Path) -> None:
    result = run_enterprise_qa(
        Path("examples/enterprise_qa/agent.yaml"),
        question="What discount should we give this customer next year?",
        runs_dir=tmp_path,
    )
    assert result.outcome == "REFUSED_NO_EVIDENCE"
```

- [ ] **Step 2: Run failing tests**

Run: `python -m pytest tests/test_workflow_enterprise_qa.py -v`

Expected: FAIL because workflow modules do not exist.

- [ ] **Step 3: Implement Proof Agent workflow state**

`WorkflowState` must track `run_id`, `workflow_name`, `current_node`, `question`, `evidence`, `policy_decisions`, `tool_requests`, `approval_state`, `memory_writes`, and `final_output`.

- [ ] **Step 4: Implement orchestrator path**

`run_enterprise_qa()` must load manifest, create trace writer, emit `run_started` and `manifest_loaded`, evaluate `before_retrieval`, retrieve knowledge, evaluate evidence, evaluate `before_answer`, answer/refuse, optionally call tool gateway, evaluate memory write, emit `final_output`, generate receipt, and return `RunResult`.

- [ ] **Step 5: Add LangGraph adapter behind internal runtime**

`runtime/langgraph_runner.py` must compile Proof Agent workflow nodes into LangGraph `StateGraph` with conditional routing. Tool approval should use LangGraph `interrupt()` and a SQLite checkpointer once the mock approval path is wired. LangGraph objects must not appear in config, policy, trace, receipt, or CLI public models.

- [ ] **Step 6: Add approval-state workflow tests**

Extend `tests/test_workflow_enterprise_qa.py` with a tool-required scenario that enters `WAITING_FOR_APPROVAL`, persists approval state, resumes when approval is granted, and returns a safe terminal response when approval is denied.

- [ ] **Step 7: Wire CLI commands**

`proof-agent demo` must run the supported, unsupported, and tool-required deterministic scenarios. `proof-agent run examples/enterprise_qa/agent.yaml` must run the enterprise QA path with a default question if no interactive prompt is available.

- [ ] **Step 8: Run tests**

Run: `python -m pytest tests/test_workflow_enterprise_qa.py tests/test_cli.py -v`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add proof_agent/workflow proof_agent/runtime proof_agent/cli.py tests/test_workflow_enterprise_qa.py tests/test_cli.py
git commit -m "Integrate enterprise QA workflow runtime"
```

## Task 11: Doctor, Inspect, Docker, CI, And Launch Smoke

**Files:**
- Modify: `proof_agent/cli.py`
- Create: `docker-compose.yml`
- Create: `Dockerfile`
- Create: `.env.example`
- Create: `runs/.gitkeep`
- Create: `.github/workflows/ci.yml`
- Modify: `README.md`
- Create: `examples/enterprise_qa/expected/governance_receipt.md`
- Create: `examples/enterprise_qa/expected/trace.jsonl`

- [ ] **Step 1: Extend CLI tests for doctor and inspect**

Add tests that run:

```bash
proof-agent doctor
proof-agent inspect runs/latest/governance_receipt.md
proof-agent inspect runs/latest/trace.jsonl
```

Expected CLI output includes readiness checks, receipt outcome, trace event count, and artifact paths.

- [ ] **Step 2: Implement doctor**

Check Python version, package import, write access to `runs/`, presence of `examples/enterprise_qa/agent.yaml`, sample knowledge files, Docker availability message, and optional model environment variables.

- [ ] **Step 3: Implement inspect**

For Markdown receipts, print final outcome and artifact path. For JSONL trace, print event count, run id, first event, last event, and whether redaction was applied.

- [ ] **Step 4: Add Docker Compose path**

`Dockerfile` installs the package with `uv pip install -e ".[dev]"`. `docker-compose.yml` runs `proof-agent demo` by default and mounts the repository so `runs/latest` appears on the host. Add `.env.example` for optional model provider variables; deterministic demo must not require those variables.

- [ ] **Step 5: Add CI**

GitHub Actions must run:

```bash
uv pip install -e ".[dev]"
python -m pytest tests/ -v
ruff check proof_agent tests
mypy proof_agent
proof-agent demo
test -f runs/latest/trace.jsonl
test -f runs/latest/governance_receipt.md
```

- [ ] **Step 6: Update README launch path**

README must include exact commands for the 2-minute deterministic demo, 30-minute enterprise evaluation, compare command, inspect command, expected artifact paths, and the three demo questions.

- [ ] **Step 7: Run final local verification**

Run:

```bash
uv pip install -e ".[dev]"
python -m pytest tests/ -v
ruff check proof_agent tests
mypy proof_agent
proof-agent demo
proof-agent run examples/enterprise_qa/agent.yaml
proof-agent compare examples/enterprise_qa/agent.yaml --question "What discount should we give this customer next year?"
proof-agent inspect runs/latest/governance_receipt.md
```

Expected: all commands succeed; `runs/latest/trace.jsonl` and `runs/latest/governance_receipt.md` exist; compare output shows Plain RAG and Harness RAG divergence.

- [ ] **Step 8: Commit**

```bash
git add proof_agent/cli.py Dockerfile docker-compose.yml .env.example runs/.gitkeep .github/workflows/ci.yml README.md examples/enterprise_qa/expected
git commit -m "Add release readiness and launch smoke path"
```

## Coverage Matrix

| Requirement | Covered by tasks |
| --- | --- |
| `agent.yaml` contract | Tasks 2, 3, 10 |
| Policy decisions at four enforcement points | Tasks 2, 5, 10 |
| Local knowledge and Harness RAG | Tasks 6, 7, 10 |
| Plain RAG vs Harness RAG comparison | Task 7 |
| MCP mock tool approval | Tasks 8, 10 |
| Session memory boundary | Task 9 |
| Validators and deterministic quality checks | Tasks 6, 8, 9, 10 |
| JSONL trace as audit source of truth | Task 4, 10 |
| Governance Receipt from trace events | Task 4, 10, 11 |
| `proof-agent demo` without API key | Tasks 1, 7, 10, 11 |
| `proof-agent run examples/enterprise_qa/agent.yaml` | Tasks 3, 10, 11 |
| `proof-agent doctor`, `inspect`, `compare` | Tasks 7, 11 |
| Trust boundaries and redaction | Tasks 4, 9 |
| Docker Compose and CI | Task 11 |

## Verification Gate

The branch is complete only after these commands pass locally:

```bash
uv pip install -e ".[dev]"
python -m pytest tests/ -v
ruff check proof_agent tests
mypy proof_agent
proof-agent demo
proof-agent run examples/enterprise_qa/agent.yaml
proof-agent compare examples/enterprise_qa/agent.yaml --question "What discount should we give this customer next year?"
proof-agent inspect runs/latest/governance_receipt.md
```

v1 acceptance requires:

- `proof-agent demo` runs without an LLM key in under two minutes.
- `proof-agent run examples/enterprise_qa/agent.yaml` writes `runs/latest/trace.jsonl` and `runs/latest/governance_receipt.md`.
- Supported questions answer with citations.
- Unsupported questions refuse or escalate.
- Tool-required questions enter approval state before tool execution.
- Plain RAG and Harness RAG visibly diverge for unsupported questions.
- Receipt satisfies the Governance Receipt Contract and never includes raw secrets.
