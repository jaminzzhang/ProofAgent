# Proof Agent Development Progress

> Last updated: 2026-05-10
> Purpose: Provide AI Coding Agents with a clear, up-to-date picture of project development status.

## 1. Project Summary

Proof Agent is an **Enterprise Agent Delivery Kit** — a local-first, CLI-first Python package implementing a **Control Envelope** that wraps Agent execution with policy enforcement, evidence checks, tool approval, memory boundaries, JSONL trace, and Governance Receipt.

- **Target user:** Enterprise AI Agent owners and platform architects
- **First template:** Enterprise knowledge Q&A
- **Authoritative design doc:** `docs/Proof Agent 技术设计方案.md`

## 2. Current Build Status

| Check | Status |
|-------|--------|
| pytest (55 tests) | All passing |
| Ruff lint | Clean |
| mypy type check | Clean |
| Deterministic demo | Working (3 scenarios) |
| CI (GitHub Actions) | Active |

## 3. Module Implementation Status

### Fully Implemented

| Module | Location | Lines | Description |
|--------|----------|------:|-------------|
| Contracts | `contracts/` (11 files) | ~394 | Pydantic v2 frozen models: `AgentManifest`, `PolicyDecision`, `EvidenceChunk`, `TraceEvent` (19 types), `ModelRequest`, `ModelResponse`, `ApprovalState`, `ReceiptOutcome` (7 outcomes), `RunResult` |
| CLI | `cli.py` | 145 | Typer CLI: `demo`, `run`, `doctor`, `inspect`, `compare` |
| Config | `config/` (3 files) | 322 | Load `agent.yaml` with shape/type/file/secret validation |
| Policy Engine | `policy/` (2 files) | 180 | 5 enforcement points (`before_retrieval`, `before_answer`, `before_model_call`, `before_tool_call`, `before_memory_write`), first-match rule evaluation |
| Knowledge | `knowledge/` (5 files) | 169 | Markdown chunking, token-overlap retrieval, evidence evaluation, ChromaDB vector index adapter |
| Workflow | `workflow/` (3 files) | 434 | Full Enterprise QA orchestrator with policy gates, model provider integration, output validation, and receipt generation |
| Audit | `audit/` (3 files + template) | 238 | JSONL trace writer with auto-redaction, Governance Receipt via Jinja2 template |
| Validators | `validators/` (5 files) | 150 | Evidence threshold, citation support, secret detection, schema validation, tool result validation |
| Tools | `tools/` (3 files) | 158 | ToolGateway with parameter validation, approval state machine, mock `customer_lookup` |
| Memory | `memory/` (1 file) | 41 | Session memory with field denylist |
| Demo | `demo/` (2 files) | 39 | Deterministic provider with 3 canned scenarios |
| Compare | `compare/` (3 files) | 48 | Plain RAG vs Harness RAG comparison |
| Errors | `errors.py` | 56 | `ProofAgentError` + `ErrorCode` enum |

### Model Provider Layer (Recently Completed)

| Provider | Status | Location | Notes |
|----------|--------|----------|-------|
| `deterministic` | Fully implemented | `providers/deterministic.py` | Wraps demo `DeterministicProvider` to `ModelProvider` protocol |
| `openai_compatible` | Fully implemented | `providers/openai_compatible.py` (179 lines) | OpenAI SDK integration, env var resolution, error mapping (auth/timeout/API), token usage extraction |
| `azure_openai` | Placeholder only | `providers/placeholders.py` | Raises `PA_MODEL_001` on any use |
| `anthropic` | Placeholder only | `providers/placeholders.py` | Raises `PA_MODEL_001` on any use |

Supporting files: `providers/protocol.py` (ModelProvider Protocol), `providers/registry.py` (PROVIDER_MAP), `providers/__init__.py` (resolve_provider factory).

### Stubbed / Not Yet Implemented

| Feature | Location | Status |
|---------|----------|--------|
| LangGraph StateGraph | `runtime/langgraph_runner.py` (28 lines) | Thin adapter; delegates to plain Python orchestrator. Real `interrupt()` not wired. |
| MCP stdio transport | `tools/mcp_mock.py` (15 lines) | Mock tool only. Real MCP protocol not connected. |
| Workflow nodes | `workflow/nodes.py` (8 lines) | Node name constants defined but not used as LangGraph nodes. |
| Vector knowledge | `knowledge/index.py` (39 lines) | ChromaDB adapter exists but requires optional `[vector]` dependencies. |

## 4. Test Coverage Summary

22 test files, 1,156 lines of tests, **55 tests all passing**.

| Test File | Tests | Coverage Area |
|-----------|------:|---------------|
| `test_contracts.py` | 10 | Immutability, traceability, contract constraints |
| `test_receipt_model_usage.py` | 2 | Receipt renders model usage and model error |
| `test_openai_compatible_provider.py` | 2 | Mocked OpenAI client, usage mapping, API key validation |
| `test_model_config_validation.py` | 2 | Config loading, secret param rejection |
| `test_trace_model_events.py` | 2 | Model events don't store raw prompts; model errors traced |
| `test_model_contracts.py` | 2 | Model request immutability, provider-neutral usage |
| `test_model_output_validators.py` | 1 | Safety + citation validation chain |
| `test_model_provider_registry.py` | 4 | Deterministic provider, placeholder providers, unsupported provider |
| `test_citation_validator.py` | 1 | Citation support validation |
| `test_evidence_validator.py` | 2 | Evidence threshold acceptance/rejection |
| `test_workflow_enterprise_qa.py` | 4 | Supported answer, unsupported refusal, tool approval wait/deny |
| `test_policy_engine.py` | 3 | Evidence denial, tool approval, model call denial |
| `test_receipt_generator.py` | 1 | Receipt required sections |
| `test_tool_gateway.py` | 2 | Approval gating, approved execution |
| `test_memory_boundary.py` | 2 | Sensitive write rejection, safe write acceptance |
| `test_trace_writer.py` | 2 | JSONL ordering, redaction |
| `test_compare.py` | 1 | Harness comparison reuses enterprise workflow |
| `test_config_loader.py` | 2 | Valid manifest loading, missing policy file |
| `test_cli.py` | Tests | CLI command behavior |
| `test_trust_boundaries.py` | 1 | Persistent memory rejected for v1 |
| `test_knowledge_provider.py` | 1 | Source chunk retrieval |
| `test_dependency_layout.py` | 1 | Vector stack is optional |

## 5. Key Design Decisions (from `docs/Proof Agent 技术设计方案.md`)

1. **Harness controls flow, model only generates content** — LLM cannot decide retrieval, tool calls, approval, memory writes, policy branches, or final acceptance.
2. **Local-first baseline must be stable** — `proof-agent demo` runs without network, API key, or remote SDK.
3. **Third-party SDK isolation** — LangGraph, Chroma, MCP, OpenAI, Azure, Anthropic types stay in adapter layer, never in contracts/policy/trace/receipt/workflow.
4. **Failures should be auditable** — Remote model errors produce `model_error` trace events.
5. **Remote output is untrusted by default** — Model output must pass schema, safety, citation validators before final output.
6. **Config is explicit, carries no secrets** — `agent.yaml` declares env var names, not raw API keys.

## 6. Implementation Roadmap (from Tech Design, Section 17)

| Step | Description | Status |
|------|-------------|--------|
| 1 | Add model contracts (`ModelRole`, `ModelMessage`, `TokenUsage`, `ModelRequest`, `ModelResponse`) | Done |
| 2 | Add providers protocol/registry/factory | Done |
| 3 | Wrap deterministic provider | Done |
| 4 | Implement openai-compatible provider with optional `openai` dependency | Done |
| 5 | Add Azure/Anthropic placeholder providers | Done |
| 6 | Extend policy: `before_model_call` enforcement point | Done |
| 7 | Extend trace events: `model_request`, `model_response`, `model_error` | Done |
| 8 | Build `ModelRequest`, wire into orchestrator standard answer path | Done |
| 9 | Add model output validators (citation/evidence validator) | Done |
| 10 | Update Governance Receipt Model Usage section | Done |
| 11 | Update CLI doctor for remote model config readiness | Not started |
| 12 | Update docs: agent-contract.md and trace-event-contract.md | Not started |
| 13 | Run full verification | Not started |

## 7. Deferred Work (Not in Current Scope)

These items are explicitly deferred per the tech design document:

- Real Azure OpenAI adapter
- Real Anthropic adapter
- Streaming responses
- OpenAI Responses API-native provider
- Provider-native structured output / JSON schema mode
- LLM-as-judge quality evaluation
- Cost estimation and budget policy
- Multi-turn conversation state
- Post-tool remote generation
- LangGraph StateGraph with real `interrupt()`
- Real MCP stdio transport

## 8. Codebase Statistics

| Metric | Value |
|--------|-------|
| Python source files (proof_agent/) | 57 |
| Python source lines (proof_agent/) | 2,919 |
| Test files (tests/) | 22 |
| Test lines (tests/) | 1,156 |
| Total test count | 55 |
| Largest file | `workflow/orchestrator.py` (410 lines) |
| Documentation files (docs/) | 10+ |
| CLI entry point | `proof-agent` → `proof_agent.cli:main` |
| Python version | >=3.12 |
| Package manager | `uv` + `pyproject.toml` + `uv.lock` |

## 9. Git History Summary

Recent development progressed in these phases:

1. **Scaffold + Contracts** — Package structure, frozen Pydantic models, error codes
2. **Config + Audit** — `agent.yaml` loading, JSONL trace writer, receipt generator
3. **Policy + Knowledge** — YAML policy engine, local knowledge retrieval, evidence validation
4. **Demo + Tools** — Deterministic provider, RAG comparison, tool gateway, approval state
5. **Workflow Integration** — Full Enterprise QA orchestrator connecting all modules
6. **Release Readiness** — CI smoke tests, documentation
7. **Model Provider Layer** (most recent) — Protocol/registry/factory, deterministic wrapper, full OpenAI-compatible provider, `before_model_call` policy gate, model trace events, receipt model usage

## 10. How to Use This File

When starting a new AI Coding Agent session on this project:

1. Read this file for a quick status overview.
2. Read `docs/Proof Agent 技术设计方案.md` for authoritative design decisions.
3. Read `CLAUDE.md` and `AGENTS.md` for coding guidelines and project structure.
4. Run `uv run --extra dev python -m pytest tests/ -v` to verify baseline.
5. Check the implementation roadmap (Section 6) to identify remaining work.
