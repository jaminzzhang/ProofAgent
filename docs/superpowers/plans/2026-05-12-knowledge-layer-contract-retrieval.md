# Knowledge Layer Contract Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the Knowledge layer so Local Markdown, Local Vector, Remote Search, and reserved Agentic RAG all fit the same governed Harness contract.

**Architecture:** Knowledge providers retrieve candidate evidence only. Retrieval Strategy owns top-k, thresholds, single-step versus agentic orchestration, and fallback behavior. The Control Plane admits or rejects evidence and emits audit-safe trace facts; providers never decide final answers or accepted evidence.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, Typer CLI, LangGraph runtime boundary, pytest, Ruff, mypy, optional Chroma/sentence-transformers behind `[vector]`.

---

## Decisions Already Recorded

- Domain language: `CONTEXT.md`
- ADR: `docs/adr/0001-knowledge-provider-contract-and-retrieval-strategy.md`
- Breaking change: no compatibility shim for `knowledge.path`
- First-stage executable strategy: `retrieval.strategy: single_step`
- Reserved future strategy: `retrieval.strategy: agentic`, fail-fast with `PA_RETRIEVAL_001`
- Provider names: `local_markdown`, `local_vector`, `remote_search`
- Remote Search first stage: fixture normalization, no real network calls
- Local Vector first stage: query existing index only, no index build command
- Trace/receipt evidence policy: record evidence summaries by default, not raw evidence content

## File Map

### Contracts And Bootstrap

- Modify `proof_agent/contracts/manifest.py`
  - Add `RetrievalConfig`
  - Change `KnowledgeConfig` from `provider/path/index_path` to `provider/params`
  - Keep params frozen with the same pattern as `ModelConfig.params`
- Modify `proof_agent/bootstrap/manifest.py`
  - Parse `knowledge.params`
  - Resolve provider-specific path params such as `path`, `index_path`, `mock_results_path`
  - Parse required top-level `retrieval`
- Modify `proof_agent/bootstrap/validation.py`
  - Require `retrieval`
  - Validate provider-specific knowledge params
  - Validate retrieval strategy and thresholds
  - Add `PA_RETRIEVAL_001` guidance for recognized but unavailable strategies
- Modify `proof_agent/errors.py` only if error metadata helpers need extending
- Modify `examples/enterprise_qa/agent.yaml`
  - Use `knowledge.provider: local_markdown`
  - Move path to `knowledge.params.path`
  - Add `retrieval.strategy: single_step`

### Knowledge Capability Layer

- Modify `proof_agent/capabilities/knowledge/provider.py`
  - Add `from_config`
  - Add `provider_name`
  - Let `retrieve` accept `top_k: int | None`
- Rename or adapt `proof_agent/capabilities/knowledge/local_provider.py`
  - Prefer class name `LocalMarkdownProvider`
  - Return candidate evidence
  - Store citation in `EvidenceChunk.citation`
- Modify `proof_agent/capabilities/knowledge/index.py`
  - Prefer class name `LocalVectorProvider`
  - Add `from_config`
  - Query existing Chroma index only
  - Return candidate evidence with metadata
- Create `proof_agent/capabilities/knowledge/remote_search.py`
  - Implement fixture-backed Remote Search normalization
  - Validate required env-var names through config, not secret values
  - No HTTP calls in first stage
- Create `proof_agent/capabilities/knowledge/registry.py`
  - Add `PROVIDER_MAP`
  - Add `resolve_knowledge_provider`
- Modify `proof_agent/capabilities/knowledge/__init__.py`
  - Export protocol and resolver

### Evidence, Validators, Trace

- Modify `proof_agent/contracts/evidence.py`
  - Add `CANDIDATE`
  - Add `citation: str | None`
  - Add `metadata: Mapping[str, Any]`
- Modify `proof_agent/control/validators/evidence.py`
  - Treat provider output as candidate evidence
  - Return accepted/rejected evidence summary metadata
  - Do not rely on provider-supplied accepted status
- Modify `proof_agent/control/validators/citations.py`
  - Support `EvidenceChunk.citation`
  - Keep content-citation parsing only if needed for tests during migration
- Modify `proof_agent/contracts/trace.py`
  - Add `retrieval_plan`
  - Add `retrieval_step`
  - Keep `retrieval_result`
- Modify `proof_agent/observability/storage/run_store.py`
  - Extract evidence summaries from new evaluation metadata
  - Avoid raw evidence content in Dashboard detail
- Modify `proof_agent/observability/audit/receipt.py`
  - Feed retrieval plan/step/result events to receipt context if useful
  - Render evidence summaries only
- Modify `proof_agent/observability/audit/templates/governance_receipt.md.j2`
  - Show accepted/rejected evidence summary with source/citation/score/status

### Runtime And Policy

- Modify `proof_agent/runtime/graph.py`
  - Use `resolve_knowledge_provider(manifest.knowledge)`
  - Use `manifest.retrieval.top_k` and `manifest.retrieval.min_score`
  - Emit `retrieval_step` before provider retrieval
  - Emit `retrieval_result` with audit-safe summary
  - Fail-fast with `PA_RETRIEVAL_001` for `strategy: agentic`
- Modify `proof_agent/contracts/policy.py`
  - Add `before_retrieval_plan`
  - Add `before_retrieval_step`
- Modify `proof_agent/control/policy/engine.py`
  - Recognize the new enforcement points
  - Default unsupported/no matching rule behavior should stay consistent with existing policy semantics
- Modify `examples/enterprise_qa/policy.yaml` only if explicit rules are needed for the new step gates

### Docs

- Modify `docs/technical-design.md`
- Modify `docs/developer-guide.md`
- Modify `docs/concepts/agent-contract.md`
- Modify `docs/concepts/control-envelope.md`
- Modify `docs/concepts/trace-event-contract.md`
- Modify `docs/concepts/policy-engine.md`
- Modify `docs/concepts/governance-receipt-contract.md`
- Modify `docs/development-progress.md`
- Do not modify `docs/zh/`

---

## Task 1: Contract Migration Tests

**Files:**
- Modify: `proof_agent/contracts/manifest.py`
- Modify: `proof_agent/bootstrap/manifest.py`
- Modify: `proof_agent/bootstrap/validation.py`
- Modify: `examples/enterprise_qa/agent.yaml`
- Test: `tests/test_config_loader.py`
- Test: `tests/test_model_config_validation.py` if shared param secret checks are reused

- [ ] **Step 1: Write failing manifest tests**

Add tests that assert:

```python
def test_loads_knowledge_params_and_retrieval_config() -> None:
    manifest = load_agent_manifest(Path("examples/enterprise_qa/agent.yaml"))
    assert manifest.knowledge.provider == "local_markdown"
    assert manifest.knowledge.params["path"].name == "knowledge"
    assert manifest.retrieval.strategy == "single_step"
    assert manifest.retrieval.top_k == 2
    assert manifest.retrieval.min_score == 0.2
```

Add a breaking-change test:

```python
def test_legacy_knowledge_path_is_rejected(tmp_path: Path) -> None:
    # agent.yaml with knowledge.path and no knowledge.params
    # expected: PA_CONFIG_001
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py -v
```

Expected: fails because `RetrievalConfig` and `knowledge.params` are not implemented.

- [ ] **Step 3: Implement `KnowledgeConfig` and `RetrievalConfig`**

Target shape:

```python
class KnowledgeConfig(FrozenModel):
    provider: str
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)


class RetrievalConfig(FrozenModel):
    strategy: str
    top_k: int = 3
    min_score: float = 0.2
    max_steps: int | None = None
    allow_query_rewrite: bool = False
    allow_rerank: bool = False
    allow_single_step_fallback: bool = False
    planner_model: ModelConfig | None = None
```

- [ ] **Step 4: Update manifest parsing and path resolution**

Resolve only known path-like knowledge params:

```python
PATH_PARAM_KEYS = {"path", "index_path", "mock_results_path"}
```

For any value under those keys, resolve relative paths against the directory containing `agent.yaml`.

- [ ] **Step 5: Update validation**

Provider-specific requirements:

- `local_markdown`: require `params.path` directory
- `local_vector`: require `params.index_path` directory, `collection_name`, `embedding_model`
- `remote_search`: require `endpoint_env`, `api_key_env`, `index_name`; if `mock_results_path` is set, require file

Retrieval requirements:

- `strategy` must be `single_step` or `agentic`
- `top_k > 0`
- `0 <= min_score <= 1`
- `agentic.max_steps` should be present and positive in docs/tests, even if runtime is reserved

- [ ] **Step 6: Update example manifest**

Use:

```yaml
knowledge:
  provider: local_markdown
  params:
    path: ./knowledge

retrieval:
  strategy: single_step
  top_k: 2
  min_score: 0.2
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_config_loader.py tests/test_model_config_validation.py -v
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add proof_agent/contracts/manifest.py proof_agent/bootstrap/manifest.py proof_agent/bootstrap/validation.py examples/enterprise_qa/agent.yaml tests/test_config_loader.py tests/test_model_config_validation.py
git commit -m "Update knowledge contract and retrieval config"
```

---

## Task 2: Knowledge Provider Registry

**Files:**
- Modify: `proof_agent/capabilities/knowledge/provider.py`
- Modify: `proof_agent/capabilities/knowledge/local_provider.py`
- Modify: `proof_agent/capabilities/knowledge/index.py`
- Create: `proof_agent/capabilities/knowledge/remote_search.py`
- Create: `proof_agent/capabilities/knowledge/registry.py`
- Modify: `proof_agent/capabilities/knowledge/__init__.py`
- Test: `tests/test_knowledge_provider.py`

- [ ] **Step 1: Write failing provider resolver tests**

Cover:

```python
def test_resolves_local_markdown_provider() -> None: ...
def test_local_markdown_returns_candidate_citations() -> None: ...
def test_remote_search_fixture_normalizes_results(tmp_path: Path) -> None: ...
def test_unknown_knowledge_provider_fails() -> None: ...
```

- [ ] **Step 2: Run provider tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_knowledge_provider.py -v
```

Expected: fails because registry and new provider names do not exist.

- [ ] **Step 3: Update provider protocol**

Use the same shape as model providers:

```python
class KnowledgeProvider(Protocol):
    @classmethod
    def from_config(cls, knowledge_config: KnowledgeConfig) -> Self: ...

    @property
    def provider_name(self) -> str: ...

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]: ...
```

- [ ] **Step 4: Implement Local Markdown provider**

Keep deterministic token-overlap behavior. Rename class if practical:

```python
class LocalMarkdownProvider:
    @classmethod
    def from_config(cls, knowledge_config: KnowledgeConfig) -> Self:
        return cls(Path(knowledge_config.params["path"]))
```

Return `EvidenceStatus.CANDIDATE` and set `citation`.

- [ ] **Step 5: Implement Local Vector provider**

Adapt `LocalKnowledgeIndex` into a provider with `from_config`. Keep imports inside `retrieve`.

Do not implement index build.

- [ ] **Step 6: Implement Remote Search fixture adapter**

Fixture input shape:

```json
[
  {
    "source": "policy://travel#meals",
    "content": "Travel meals require receipts.",
    "score": 0.84,
    "citation": "travel-policy.md#meals:L10-L18",
    "metadata": {"document_id": "travel-policy"}
  }
]
```

Normalize to candidate `EvidenceChunk`. Reject non-JSON-serializable metadata in tests if a helper exists; otherwise keep values simple.

- [ ] **Step 7: Implement registry**

```python
PROVIDER_MAP: dict[str, type[KnowledgeProvider]] = {
    "local_markdown": LocalMarkdownProvider,
    "local_vector": LocalVectorProvider,
    "remote_search": RemoteSearchProvider,
}
```

Raise `ProofAgentError("PA_KNOWLEDGE_001", ...)` for unknown providers.

- [ ] **Step 8: Run provider tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_knowledge_provider.py -v
```

Expected: pass.

- [ ] **Step 9: Commit**

```bash
git add proof_agent/capabilities/knowledge tests/test_knowledge_provider.py
git commit -m "Add knowledge provider registry"
```

---

## Task 3: Evidence Contract And Validators

**Files:**
- Modify: `proof_agent/contracts/evidence.py`
- Modify: `proof_agent/control/validators/evidence.py`
- Modify: `proof_agent/control/validators/citations.py`
- Test: `tests/test_evidence_validator.py`
- Test: `tests/test_citation_validator.py`
- Test: `tests/test_contracts.py`

- [ ] **Step 1: Write failing evidence tests**

Add tests:

```python
def test_provider_candidate_evidence_is_admitted_by_validator() -> None: ...
def test_low_score_candidate_is_rejected_by_validator() -> None: ...
def test_citation_validator_uses_evidence_citation_field() -> None: ...
def test_evidence_metadata_is_frozen() -> None: ...
```

- [ ] **Step 2: Run validator tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evidence_validator.py tests/test_citation_validator.py tests/test_contracts.py -v
```

Expected: fails because `candidate`, `citation`, and `metadata` are not implemented.

- [ ] **Step 3: Extend `EvidenceChunk`**

Use:

```python
class EvidenceStatus(str, Enum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class EvidenceChunk(FrozenModel):
    source: str
    content: str
    score: float
    status: EvidenceStatus
    citation: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)
```

Add a validator to freeze metadata like `ModelConfig.params`.

- [ ] **Step 4: Update evidence evaluator**

Do not trust provider status for acceptance. Compute accepted candidates with score threshold and return summary metadata:

```python
"evidence": tuple(
    {
        "source": chunk.source,
        "citation": chunk.citation,
        "score": chunk.score,
        "status": "accepted" if admitted else "rejected",
    }
)
```

- [ ] **Step 5: Update citation validator**

Supported citations should be built from accepted evidence citation/source. Keep source matching stable for Markdown citations.

- [ ] **Step 6: Run validator tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evidence_validator.py tests/test_citation_validator.py tests/test_contracts.py -v
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add proof_agent/contracts/evidence.py proof_agent/control/validators tests/test_evidence_validator.py tests/test_citation_validator.py tests/test_contracts.py
git commit -m "Separate candidate and accepted evidence"
```

---

## Task 4: Runtime Retrieval Step And Trace

**Files:**
- Modify: `proof_agent/contracts/trace.py`
- Modify: `proof_agent/runtime/graph.py`
- Modify: `proof_agent/contracts/policy.py`
- Modify: `proof_agent/control/policy/engine.py`
- Test: `tests/test_trace_model_events.py` or create `tests/test_retrieval_trace_events.py`
- Test: `tests/test_workflow_enterprise_qa.py`
- Test: `tests/test_policy_engine.py`

- [ ] **Step 1: Write failing runtime tests**

Cover:

```python
def test_single_step_retrieval_uses_manifest_provider_and_retrieval_config() -> None: ...
def test_trace_records_retrieval_step_before_result() -> None: ...
def test_agentic_strategy_fails_with_pa_retrieval_001() -> None: ...
def test_policy_accepts_retrieval_plan_and_step_enforcement_points() -> None: ...
```

- [ ] **Step 2: Run focused workflow tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_enterprise_qa.py tests/test_policy_engine.py -v
```

Expected: fails because runtime still hard-codes `LocalKnowledgeProvider`.

- [ ] **Step 3: Add trace event enum values**

Add:

```python
RETRIEVAL_PLAN = "retrieval_plan"
RETRIEVAL_STEP = "retrieval_step"
```

- [ ] **Step 4: Add policy enforcement points**

Add:

```python
BEFORE_RETRIEVAL_PLAN = "before_retrieval_plan"
BEFORE_RETRIEVAL_STEP = "before_retrieval_step"
```

Make engine dispatch no worse than existing behavior. If no special rule exists, keep current default semantics.

- [ ] **Step 5: Update runtime graph**

At composition:

```python
knowledge_provider = resolve_knowledge_provider(manifest.knowledge)
if manifest.retrieval.strategy == "agentic":
    raise ProofAgentError("PA_RETRIEVAL_001", ...)
```

In retrieve node:

- evaluate `before_retrieval`
- evaluate `before_retrieval_step`
- emit `retrieval_step`
- call provider
- emit `retrieval_result`
- evaluate evidence with `manifest.retrieval.min_score`
- evaluate `before_answer`

- [ ] **Step 6: Ensure trace payload is audit-safe**

Use summary fields only:

```python
{
    "step_id": "step_1",
    "provider": knowledge_provider.provider_name,
    "candidate_count": len(candidates),
    "sources": [chunk.source for chunk in candidates],
}
```

No raw evidence content.

- [ ] **Step 7: Run workflow tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_workflow_enterprise_qa.py tests/test_policy_engine.py tests/test_trace_model_events.py -v
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add proof_agent/contracts/trace.py proof_agent/contracts/policy.py proof_agent/control/policy/engine.py proof_agent/runtime/graph.py tests
git commit -m "Route retrieval through governed retrieval steps"
```

---

## Task 5: Receipt, Dashboard Projection, And Audit Safety

**Files:**
- Modify: `proof_agent/observability/storage/run_store.py`
- Modify: `proof_agent/observability/audit/receipt.py`
- Modify: `proof_agent/observability/audit/templates/governance_receipt.md.j2`
- Test: `tests/test_run_store.py`
- Test: `tests/test_dashboard_contracts.py`
- Test: `tests/test_receipt_generator.py`

- [ ] **Step 1: Write failing audit tests**

Add tests that assert:

- receipt shows source, citation, score, status
- receipt does not contain raw evidence content
- dashboard evidence chunks are derived from summary metadata
- rejected evidence appears as rejected when evaluation says so

- [ ] **Step 2: Run audit tests and verify failure**

Run:

```bash
uv run --extra dev python -m pytest tests/test_run_store.py tests/test_dashboard_contracts.py tests/test_receipt_generator.py -v
```

Expected: fails on old extraction format.

- [ ] **Step 3: Update RunStore extraction**

Prefer `evidence_evaluation.payload.metadata.evidence`. Fall back to old source-only extraction only if needed for historical traces.

- [ ] **Step 4: Update receipt context and template**

Render table:

```markdown
| Source | Citation | Score | Status |
```

Do not render `EvidenceChunk.content`.

- [ ] **Step 5: Run audit tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_run_store.py tests/test_dashboard_contracts.py tests/test_receipt_generator.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/observability tests/test_run_store.py tests/test_dashboard_contracts.py tests/test_receipt_generator.py
git commit -m "Render audit-safe evidence summaries"
```

---

## Task 6: Documentation Migration

**Files:**
- Modify: `docs/technical-design.md`
- Modify: `docs/developer-guide.md`
- Modify: `docs/concepts/agent-contract.md`
- Modify: `docs/concepts/control-envelope.md`
- Modify: `docs/concepts/trace-event-contract.md`
- Modify: `docs/concepts/policy-engine.md`
- Modify: `docs/concepts/governance-receipt-contract.md`
- Modify: `docs/development-progress.md`
- Do not modify: `docs/zh/**`

- [ ] **Step 1: Update authoritative design**

In `docs/technical-design.md`, update:

- Agent Contract example
- Knowledge and Vector Providers
- Capability rules
- trace events
- error codes
- roadmap status

- [ ] **Step 2: Update developer guide**

Replace all old examples:

```yaml
knowledge:
  provider: local
  path: ./knowledge
```

with:

```yaml
knowledge:
  provider: local_markdown
  params:
    path: ./knowledge

retrieval:
  strategy: single_step
  top_k: 2
  min_score: 0.2
```

- [ ] **Step 3: Update concept docs**

Clarify:

- Agentic RAG is Retrieval Strategy, not provider or workflow template
- Provider returns candidate evidence
- Control Plane admits evidence
- trace records summaries, not raw content

- [ ] **Step 4: Run doc sanity checks**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 5: Commit**

```bash
git add docs/technical-design.md docs/developer-guide.md docs/concepts docs/development-progress.md
git commit -m "Document knowledge provider retrieval strategy"
```

---

## Task 7: End-To-End Verification

**Files:**
- No planned source edits unless verification finds issues

- [ ] **Step 1: Run unit suite**

Run:

```bash
uv run --extra dev python -m pytest tests/ -v
```

Expected: pass.

- [ ] **Step 2: Run Ruff**

Run:

```bash
uv run --extra dev ruff check proof_agent tests
```

Expected: pass.

- [ ] **Step 3: Run mypy**

Run:

```bash
uv run --extra dev mypy proof_agent
```

Expected: pass.

- [ ] **Step 4: Run deterministic demo**

Run:

```bash
uv run --extra dev proof-agent demo
```

Expected:

- supported -> `ANSWERED_WITH_CITATIONS`
- unsupported -> `REFUSED_NO_EVIDENCE`
- tool_required -> `WAITING_FOR_APPROVAL`

- [ ] **Step 5: Run direct Enterprise QA Template**

Run:

```bash
uv run --extra dev proof-agent run examples/enterprise_qa/agent.yaml
```

Expected: final outcome is still governed, with trace and receipt written.

- [ ] **Step 6: Inspect artifacts**

Run:

```bash
uv run --extra dev proof-agent inspect runs/latest/governance_receipt.md
uv run --extra dev proof-agent inspect runs/latest/trace.jsonl
```

Expected:

- `retrieval_step` appears before `retrieval_result`
- evidence summaries do not include raw evidence content
- final output behavior matches pre-migration demo outcomes

- [ ] **Step 7: Run diff check**

Run:

```bash
git diff --check
```

Expected: pass.

- [ ] **Step 8: Final commit**

```bash
git add proof_agent tests examples docs pyproject.toml
git commit -m "Implement governed knowledge retrieval contract"
```

---

## Notes For Implementers

- Keep third-party SDK objects out of `proof_agent/contracts/`, bootstrap, validators, trace, receipt, and Dashboard contracts.
- Do not add real Remote Search HTTP in this plan.
- Do not add Local Vector index build in this plan.
- Do not make Agentic RAG execute planner loops in this plan.
- Do not update Chinese docs in this plan.
- Keep the deterministic local demo runnable without network access or API keys.
- When a provider returns evidence, treat it as untrusted candidate evidence until Control Plane evaluation admits it.
