# Insurance Knowledge Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [FRAME | HIGH] Build a private, layout-aware, reviewable, version-pinned insurance Knowledge path that ingests long PDFs, publishes immutable Rule Unit revisions into an attested OpenSearch hybrid index, and answers governed institution-specialist queries without weakening authorization, authority, citation, or evidence gates.

**Architecture:** [FRAME | HIGH] Add new provider-neutral contracts and focused Hybrid modules beside the retained Local Index path. PostgreSQL and S3-compatible storage remain authority, OpenSearch is a rebuildable projection, and all parser, embedding, reranker, and scheduler integrations are injected private-service ports. Delivery proceeds through six independently testable phases: contracts and trust context; structured ingestion and review; index publication; governed runtime retrieval; evaluation and cutover mechanics; and production release-authority closure.

**Tech Stack:** [FRAME | HIGH] Python 3.12, Pydantic v2 frozen contracts, FastAPI, Typer, PostgreSQL via psycopg, S3-compatible storage via boto3, self-hosted OpenSearch 3.x over an injected guarded HTTP transport, Docling and PaddleOCR PP-StructureV3 private service APIs, Qwen3 embedding and GTE reranker private service APIs, openpyxl for literal-cell workbook intake, React 19, TypeScript, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-07-12-insurance-knowledge-architecture-design.md`

---

## Scope And Sequencing

[KNOWN | HIGH] The repository currently has a file-backed Local Index lifecycle, one non-authorized `KnowledgeProvider.retrieve(query, top_k)` protocol, one-shape `ResolvedKnowledgeBinding`, flat `ParsedKnowledgeDocument`, existing Knowledge Hub API/UI, and deterministic evaluation foundations. It does not yet contain PostgreSQL/S3/OpenSearch production adapters, Hybrid binding contracts, institution Knowledge authorization context, structured PDF artifacts, Rule Unit review, or sealed Knowledge release gates.

[FRAME | HIGH] Do not implement this as one cutover. Complete each phase and its gate before starting the next:

1. [FRAME | HIGH] Phase A — contracts, trusted authorization propagation, ports, and backward-compatible binding resolution.
2. [FRAME | HIGH] Phase B — Hybrid-specific intake, structured parsing, Rule Unit projection, workbook curation, and human review.
3. [FRAME | HIGH] Phase C — embedding, OpenSearch projection, manifest, attestation chain, and serialized Source publication.
4. [FRAME | HIGH] Phase D — governed Hybrid runtime retrieval, authority/admission separation, degradation, Agent binding, and rollback.
5. [FRAME | HIGH] Phase E — Gold Suite, parser benchmark, capacity envelope, operations, shadow run, and gated cutover.
6. [FRAME | HIGH] Phase F — live deployment drivers, independent sealed-evaluator trust, candidate-bound Knowledge Release Record, production telemetry composition, and external asset-manifest enforcement.

[FRAME | HIGH] Private model-serving images and their cluster lifecycle remain deployment-owned external services. This repository owns their typed client contracts, conformance tests, exact revision references, scheduler interaction, health checks, and release gates; it must not vendor Docling, PaddleOCR, embedding, or reranker weights into the Proof Agent image.

## Target File Structure

### Contracts

Create:

- `proof_agent/contracts/hybrid_documents.py` — canonical pages, blocks, tables, parser lineage, artifact-build identity.
- `proof_agent/contracts/insurance_rules.py` — visibility algebra, approved metadata, Rule Unit revisions, evidence slots, authority results.
- `proof_agent/contracts/knowledge_index.py` — Index Generation, Retrieval Profile, publication manifest, attestation, publication attempt.
- `proof_agent/contracts/insurance_authorization.py` — trusted institution, region, channel, role, and business-line run context.
- `tests/test_hybrid_document_contracts.py`
- `tests/test_insurance_rule_contracts.py`
- `tests/test_knowledge_index_contracts.py`
- `tests/test_insurance_authorization.py`

Modify:

- `proof_agent/contracts/knowledge_resolution.py` — add a backward-compatible discriminated Hybrid binding variant.
- `proof_agent/contracts/agent_configuration.py` — add Hybrid Source, revision review, publication, and operational records.
- `proof_agent/contracts/evidence.py` — add Rule Unit, authority, and evidence-slot identity without overloading scores.
- `proof_agent/contracts/__init__.py` — export new public contracts.

### Hybrid Capability Modules

Create:

- `proof_agent/capabilities/knowledge/hybrid/__init__.py`
- `proof_agent/capabilities/knowledge/hybrid/ports.py` — artifact, repository, parser, model, scheduler, and search protocols.
- `proof_agent/capabilities/knowledge/hybrid/intake.py` — Hybrid-only PDF preflight and capacity validation.
- `proof_agent/capabilities/knowledge/hybrid/parser_clients.py` — Docling and Paddle private-service adapters.
- `proof_agent/capabilities/knowledge/hybrid/canonicalizer.py` — vendor JSON to canonical artifact conversion.
- `proof_agent/capabilities/knowledge/hybrid/quality.py` — page/block/table quality gates and review escalation.
- `proof_agent/capabilities/knowledge/hybrid/pipeline.py` — structured parse orchestration.
- `proof_agent/capabilities/knowledge/hybrid/rule_units.py` — coherent clause, section, row, and row-group projection.
- `proof_agent/capabilities/knowledge/hybrid/workbook.py` — template-bound metadata workbook import.
- `proof_agent/capabilities/knowledge/hybrid/versioning.py` — build, generation, profile, and unit revision fingerprints.
- `proof_agent/capabilities/knowledge/hybrid/model_clients.py` — embedding, reranker, and scheduler clients.
- `proof_agent/capabilities/knowledge/hybrid/opensearch.py` — deterministic query and bulk projection adapter.
- `proof_agent/capabilities/knowledge/hybrid/manifest.py` — content-addressed manifest shards and root artifact.
- `proof_agent/capabilities/knowledge/hybrid/publication.py` — fenced attempt, validation, attestation, and commit orchestration.
- `proof_agent/capabilities/knowledge/hybrid/provider.py` — `hybrid_index` provider implementation.
- `proof_agent/capabilities/knowledge/ingestion/hybrid_worker.py` — Hybrid durable job handler.

Modify:

- `proof_agent/capabilities/knowledge/registry.py`
- `proof_agent/capabilities/knowledge/blended.py`
- `proof_agent/capabilities/knowledge/ingestion/worker.py` — dispatch only; preserve Local Index behavior.
- `proof_agent/capabilities/knowledge/ingestion/contracts.py`
- `proof_agent/capabilities/knowledge/ingestion/__init__.py`

### Authority, Storage, And Delivery

Create:

- `proof_agent/configuration/hybrid_knowledge_repository.py` — authority protocol and in-memory test adapter.
- `proof_agent/configuration/postgres_hybrid_knowledge_repository.py` — production authority adapter.
- `proof_agent/configuration/migrations/0001_hybrid_knowledge.sql` — Hybrid tables, constraints, sequence, fencing, and CAS columns.
- `proof_agent/capabilities/knowledge/hybrid/s3_artifacts.py` — exact-version S3 artifact adapter.
- `proof_agent/control/knowledge/hybrid_request.py` — Control Plane request construction and trusted filter projection.
- `proof_agent/control/knowledge/insurance_authority.py` — applicability, precedence, authority, and conflict gate.
- `proof_agent/control/knowledge/evidence_slots.py` — clause, guidance, and comparison slot completeness.
- `proof_agent/control/knowledge/context_expansion.py` — independently authorized structural expansion.
- `proof_agent/control/knowledge/context_assembler.py` — bounded insurance evidence payload construction.
- `proof_agent/control/knowledge/answer_validator.py` — post-generation citation, authority, and answer-contract validation.
- `proof_agent/control/knowledge/hybrid_retrieval.py` — Hybrid-only execution coordinator.
- `proof_agent/capabilities/knowledge/hybrid/recovery.py` — authority-driven orphan reconciliation and index rebuild.
- `tests/test_hybrid_knowledge_repository.py`
- `tests/test_hybrid_publication.py`
- `tests/test_hybrid_retrieval.py`
- `tests/test_insurance_authority_gate.py`

Modify:

- `proof_agent/bootstrap/knowledge_resolution.py`
- `proof_agent/bootstrap/validation.py`
- `proof_agent/bootstrap/composition.py`
- `proof_agent/control/knowledge/retrieval_service.py` — delegate Hybrid requests; do not add Hybrid internals here.
- `proof_agent/control/context_assembler.py`
- `proof_agent/control/workflow/controlled_react/composition.py`
- `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- `proof_agent/delivery/configuration_api.py`
- `proof_agent/delivery/api.py`
- `proof_agent/delivery/run_execution_service.py`
- `proof_agent/delivery/agent_package_execution.py`
- `proof_agent/delivery/cli.py`
- `proof_agent/runtime/approval_resume.py`
- `proof_agent/observability/api/operator_identity.py`
- `proof_agent/observability/api/serializers.py`
- `proof_agent/observability/audit/trace.py`
- `proof_agent/observability/audit/receipt.py`

### Evaluation, Dashboard, And Deployment Verification

Create:

- `proof_agent/evaluation/knowledge_cases.py`
- `proof_agent/evaluation/knowledge_metrics.py`
- `proof_agent/evaluation/knowledge_gates.py`
- `proof_agent/evaluation/sealed_knowledge_acceptance.py`
- `proof_agent/evaluation/parser_benchmark.py`
- `proof_agent/evaluation/knowledge_shadow.py`
- `proof_agent/evaluation/knowledge_capacity.py`
- `proof_agent/evaluation/knowledge_recovery.py`
- `proof_agent/evaluation/suites/insurance_knowledge_tuning.sample.yaml`
- `proof_agent/evaluation/suites/insurance_knowledge_capacity.sample.yaml`
- `dashboard/src/components/knowledge/KnowledgeReviewPanel.tsx`
- `dashboard/src/components/knowledge/KnowledgeOperationsPanel.tsx`
- `dashboard/src/components/knowledge/__tests__/KnowledgeReviewPanel.test.tsx`
- `dashboard/src/components/knowledge/__tests__/KnowledgeOperationsPanel.test.tsx`
- `tests/fixtures/knowledge/hybrid/docling-simple.json`
- `tests/fixtures/knowledge/hybrid/docling-complex-table.json`
- `tests/fixtures/knowledge/hybrid/paddle-ocr-page.json`
- `tests/fixtures/knowledge/hybrid/metadata-workbook.xlsx`
- `tests/integration/test_hybrid_opensearch.py`
- `tests/integration/test_hybrid_postgres_s3.py`
- `docker-compose.hybrid-test.yml` — local integration only, never production authority.

Modify:

- `proof_agent/contracts/evaluation.py`
- `proof_agent/evaluation/gate_profiles.py`
- `proof_agent/evaluation/gates.py`
- `proof_agent/evaluation/suites.py`
- `dashboard/src/api/types.ts`
- `dashboard/src/api/client.ts`
- `dashboard/src/pages/KnowledgeDetailPage.tsx`
- `dashboard/src/pages/__tests__/KnowledgeDetailPage.test.tsx`
- `pyproject.toml`
- `.env.example`
- `docs/technical-design.md`
- `docs/developer-guide.md`
- `docs/evaluation-system.md`
- `docs/development-progress.md`

## Phase A — Contracts And Trust Context

### Task 1: Add Canonical Structured Document Contracts

**Files:**

- Create: `proof_agent/contracts/hybrid_documents.py`
- Modify: `proof_agent/contracts/__init__.py`
- Create: `tests/test_hybrid_document_contracts.py`

- [ ] **Step 1: Write the failing canonical-artifact tests**

```python
def test_structured_artifact_preserves_table_cells_and_parser_lineage() -> None:
    artifact = StructuredKnowledgeDocumentArtifact(
        schema_version="structured-knowledge.v1",
        document_id="doc_1",
        revision_id="rev_1",
        original_sha256="a" * 64,
        build_identity=StructuredArtifactBuildIdentity(
            build_id="skab_1",
            source_sha256="a" * 64,
            parser_adapter="docling",
            parser_revision="2.112.0",
            model_digests=("sha256:model",),
            canonical_schema_version="structured-knowledge.v1",
            configuration_sha256="b" * 64,
        ),
        pages=(
            StructuredPage(
                page_number=12,
                width=612,
                height=792,
                blocks=(),
                tables=(
                    StructuredTable(
                        table_id="tbl_1",
                        title="Eligibility",
                        bbox=BoundingBox(x0=10, y0=20, x1=500, y1=700),
                        cells=(
                            StructuredTableCell(
                                row=1,
                                column=2,
                                text="Age 18-60",
                                bbox=BoundingBox(x0=100, y0=50, x1=200, y1=80),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    assert artifact.pages[0].tables[0].cells[0].text == "Age 18-60"
    assert artifact.build_identity.parser_adapter == "docling"
```

- [ ] **Step 2: Run the test and verify import failure**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_document_contracts.py -q`

Expected: FAIL because `proof_agent.contracts.hybrid_documents` does not exist.

- [ ] **Step 3: Implement frozen document contracts**

```python
class BoundingBox(FrozenModel):
    x0: float
    y0: float
    x1: float
    y1: float


class StructuredArtifactBuildIdentity(FrozenModel):
    build_id: str
    source_sha256: str
    parser_adapter: str
    parser_revision: str
    model_digests: tuple[str, ...] = ()
    canonical_schema_version: Literal["structured-knowledge.v1"]
    configuration_sha256: str


class StructuredTableCell(FrozenModel):
    row: int
    column: int
    row_span: int = 1
    column_span: int = 1
    text: str
    bbox: BoundingBox
    source_method: Literal["native", "ocr", "reconstructed"] = "native"
```

[FRAME | HIGH] Add focused `StructuredBlock`, `StructuredTable`, `StructuredPage`, `ParserWarning`, and `StructuredKnowledgeDocumentArtifact` models. Keep vendor payloads and SDK types out of these contracts.

- [ ] **Step 4: Export contracts and run tests**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_document_contracts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/contracts/hybrid_documents.py proof_agent/contracts/__init__.py tests/test_hybrid_document_contracts.py
git commit -m "feat: add structured knowledge document contracts"
```

### Task 2: Add Insurance Rule Revision And Visibility Contracts

**Files:**

- Create: `proof_agent/contracts/insurance_rules.py`
- Modify: `proof_agent/contracts/__init__.py`
- Create: `tests/test_insurance_rule_contracts.py`

- [ ] **Step 1: Write failing visibility-algebra tests**

```python
def test_restricted_visibility_requires_explicit_dimension_modes() -> None:
    with pytest.raises(ValidationError):
        ApprovedInsuranceKnowledgeVisibilityScope(
            visibility="RESTRICTED",
            institutions=ScopeDimension(mode="ALLOWLIST", values=("INST-1",)),
        )


def test_allowlist_requires_values_and_all_rejects_values() -> None:
    with pytest.raises(ValidationError):
        ScopeDimension(mode="ALLOWLIST", values=())
    with pytest.raises(ValidationError):
        ScopeDimension(mode="ALL", values=("unexpected",))
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_insurance_rule_contracts.py -q`

Expected: FAIL because the contracts do not exist.

- [ ] **Step 3: Implement explicit visibility and immutable Rule Unit revision contracts**

```python
class ScopeDimension(FrozenModel):
    mode: Literal["ALL", "ALLOWLIST"]
    values: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        if self.mode == "ALLOWLIST" and not self.values:
            raise ValueError("ALLOWLIST requires at least one value")
        if self.mode == "ALL" and self.values:
            raise ValueError("ALL does not accept values")
        return self


class ApprovedInsuranceKnowledgeVisibilityScope(FrozenModel):
    visibility: Literal["PUBLIC", "RESTRICTED"]
    institutions: ScopeDimension | None = None
    regions: ScopeDimension | None = None
    channels: ScopeDimension | None = None
    roles: ScopeDimension | None = None
    business_lines: ScopeDimension | None = None
    revision_id: str


class InsuranceRuleUnitRevision(FrozenModel):
    rule_unit_revision_id: str
    logical_rule_key: str
    document_id: str
    revision_id: str
    structured_build_id: str
    content: str
    citation_uri: str
    metadata_revision_id: str
    visibility_scope: ApprovedInsuranceKnowledgeVisibilityScope
    content_sha256: str
    authority_sha256: str
```

[FRAME | HIGH] Add a model validator requiring all five dimensions for `RESTRICTED` and forbidding dimension fields for `PUBLIC`. Add metadata draft/approved revision, applicability, precedence, evidence-slot, and authority-gate result contracts without a shared numeric confidence field.

- [ ] **Step 4: Add row/row-group and isolated-cell rejection tests**

```python
def test_isolated_cell_cannot_be_rule_unit_kind() -> None:
    with pytest.raises(ValidationError):
        InsuranceRuleUnitRevision(unit_kind="cell", **valid_rule_fields())
```

Run: `uv run --extra dev python -m pytest tests/test_insurance_rule_contracts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/contracts/insurance_rules.py proof_agent/contracts/__init__.py tests/test_insurance_rule_contracts.py
git commit -m "feat: add insurance rule authority contracts"
```

### Task 3: Add Hybrid Index, Publication, And Retrieval Profile Contracts

**Files:**

- Create: `proof_agent/contracts/knowledge_index.py`
- Modify: `proof_agent/contracts/agent_configuration.py`
- Modify: `proof_agent/contracts/__init__.py`
- Create: `tests/test_knowledge_index_contracts.py`

- [ ] **Step 1: Write failing version-separation tests**

```python
def test_retrieval_profile_is_not_part_of_index_generation() -> None:
    generation = KnowledgeIndexGeneration(
        generation_id="kig_1",
        source_id="ks_1",
        canonical_schema_version="structured-knowledge.v1",
        search_projection_version="rule-unit-search.v1",
        mapping_sha256="a" * 64,
        analyzer_sha256="b" * 64,
        embedding_model_revision="qwen3-embedding-0.6b@sha256:model",
        embedding_instruction_sha256="c" * 64,
        embedding_dimension=1024,
        normalized=True,
    )
    profile = KnowledgeRetrievalProfileRevision(
        profile_revision_id="krp_1",
        lexical_budget=100,
        dense_budget=100,
        rrf_window=50,
        reranker_revision="gte-reranker@sha256:model",
        rerank_budget=50,
        final_budget=16,
        enabled_degradations=(),
    )
    assert generation.generation_id != profile.profile_revision_id
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_knowledge_index_contracts.py -q`

Expected: FAIL because the version contracts do not exist.

- [ ] **Step 3: Implement publication and attestation contracts**

```python
class KnowledgeProjectionAttestation(FrozenModel):
    attestation_id: str
    source_id: str
    generation_id: str
    index_uuid: str
    refresh_checkpoint: str
    manifest_root_sha256: str
    covered_publication_sequences: tuple[int, ...]
    parent_attestation_sha256: str | None = None
    projection_sha256: str
    validated_document_count: int


class HybridKnowledgePublicationRecord(FrozenModel):
    publication_id: str
    source_id: str
    source_snapshot_id: str
    source_publication_seq: int
    generation_id: str
    manifest_ref: ExactArtifactRef
    attestation: KnowledgeProjectionAttestation
    validation_id: str
    published_at: str
    published_by: str
```

[FRAME | HIGH] Also add `KnowledgePublicationAttempt`, `RuleUnitManifestRoot`, `RuleUnitManifestShard`, `KnowledgeIndexGeneration`, `KnowledgeRetrievalProfileRevision`, and Hybrid review/readiness records. Extend existing `resource_kind` literals with `hybrid_publication` without changing Local Index and remote defaults.

- [ ] **Step 4: Test attestation parent and coverage validation**

Run: `uv run --extra dev python -m pytest tests/test_knowledge_index_contracts.py -q`

Expected: PASS, including rejection of duplicate/non-positive sequence values and parent self-reference.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/contracts/knowledge_index.py proof_agent/contracts/agent_configuration.py proof_agent/contracts/__init__.py tests/test_knowledge_index_contracts.py
git commit -m "feat: add hybrid knowledge version contracts"
```

### Task 4: Add A Backward-Compatible Discriminated Binding Union

**Files:**

- Modify: `proof_agent/contracts/knowledge_resolution.py`
- Modify: `proof_agent/contracts/__init__.py`
- Modify: `tests/test_knowledge_binding_resolver.py`
- Modify: `tests/test_agent_configuration_contracts.py`

- [ ] **Step 1: Write failing round-trip tests for both variants**

```python
def test_resolved_binding_set_round_trips_legacy_and_hybrid() -> None:
    resolved = ResolvedKnowledgeBindingSet(
        bindings=(
            ResolvedKnowledgeBinding(
                binding_id="legacy",
                source_scope="shared",
                source_id="ks_local",
                source_version_id="snapshot_1",
                provider="local_index",
            ),
            ResolvedHybridKnowledgeBinding(
                binding_id="hybrid",
                source_id="ks_hybrid",
                source_publication_id="kspub_2",
                source_snapshot_id="snapshot_2",
                index_generation_id="kig_2",
                source_publication_seq=7,
                retrieval_profile_revision_id="krp_2",
                manifest_ref=artifact_ref(),
                publication_attestation_id="att_2",
            ),
        )
    )
    restored = ResolvedKnowledgeBindingSet.model_validate(resolved.model_dump(mode="json"))
    assert isinstance(restored.bindings[1], ResolvedHybridKnowledgeBinding)
```

- [ ] **Step 2: Run resolver tests and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_knowledge_binding_resolver.py tests/test_agent_configuration_contracts.py -q`

Expected: FAIL because `ResolvedHybridKnowledgeBinding` is absent.

- [ ] **Step 3: Preserve the legacy constructor and add a discriminated item type**

```python
class ResolvedKnowledgeBinding(FrozenModel):
    binding_kind: Literal["legacy"] = "legacy"
    # retain every existing field and default


class ResolvedHybridKnowledgeBinding(FrozenModel):
    binding_kind: Literal["hybrid"] = "hybrid"
    binding_id: str
    source_scope: Literal["shared"] = "shared"
    source_id: str
    provider: Literal["hybrid_index"] = "hybrid_index"
    source_publication_id: str
    source_snapshot_id: str
    index_generation_id: str
    source_publication_seq: int
    retrieval_profile_revision_id: str
    manifest_ref: ExactArtifactRef
    publication_attestation_id: str
    failure_mode: str = "required"
    fusion_weight: float = 1.0


ResolvedKnowledgeBindingItem = Annotated[
    ResolvedKnowledgeBinding | ResolvedHybridKnowledgeBinding,
    Field(discriminator="binding_kind"),
]
```

- [ ] **Step 4: Run the full binding and published-version regression set**

Run: `uv run --extra dev python -m pytest tests/test_knowledge_binding_resolver.py tests/test_published_agent_versions.py tests/test_composition.py -q`

Expected: PASS; existing serialized bindings gain only the default `binding_kind: legacy` field.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/contracts/knowledge_resolution.py proof_agent/contracts/__init__.py tests/test_knowledge_binding_resolver.py tests/test_agent_configuration_contracts.py
git commit -m "feat: add resolved hybrid knowledge binding"
```

### Task 5: Propagate Trusted Institution Authorization Into Runs

**Files:**

- Create: `proof_agent/contracts/insurance_authorization.py`
- Modify: `proof_agent/observability/api/operator_identity.py`
- Modify: `proof_agent/delivery/api.py`
- Modify: `proof_agent/delivery/run_execution_service.py`
- Modify: `proof_agent/delivery/agent_package_execution.py`
- Modify: `proof_agent/runtime/approval_resume.py`
- Modify: `proof_agent/bootstrap/composition.py`
- Modify: `proof_agent/contracts/__init__.py`
- Create: `tests/test_insurance_authorization.py`
- Modify: `tests/test_run_execution_api.py`
- Modify: `tests/test_approval_resume.py`

- [ ] **Step 1: Write failing tests proving request bodies cannot self-assert ACL scope**

```python
def test_chat_run_rejects_body_supplied_knowledge_scope(client) -> None:
    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "agent_1",
            "question": "Which rule applies?",
            "knowledge_scope": {"institutions": ["INST-ADMIN"]},
        },
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Write failing identity-propagation and resume tests**

```python
def test_published_run_uses_scope_from_operator_identity(fake_identity_provider) -> None:
    fake_identity_provider.identity = OperatorIdentityContext(
        operator_id="op_1",
        display_name="Operator",
        permissions=frozenset(),
        institution_authorization=InstitutionAuthorizationContext(
            institutions=("INST-1",),
            regions=("CN-SH",),
            channels=("agency",),
            roles=("specialist",),
            business_lines=("short_term_accident",),
        ),
    )
    # execute request and assert the frozen run input contains only trace-safe scope facts
```

Run: `uv run --extra dev python -m pytest tests/test_insurance_authorization.py tests/test_run_execution_api.py tests/test_approval_resume.py -q`

Expected: FAIL because the trusted context is absent.

- [ ] **Step 3: Implement the frozen authorization contract and identity default**

```python
class InstitutionAuthorizationContext(FrozenModel):
    institutions: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    business_lines: tuple[str, ...] = ()
    public_only: bool = True
```

[FRAME | HIGH] Extend `OperatorIdentityContext` with `institution_authorization`, defaulting local and unmatched identities to `public_only=True`. Resolve it through server-side identity dependencies; do not add it to `ChatRunRequest` or `ConversationRunRequest`.

- [ ] **Step 4: Thread the context through execution and resume snapshots**

[FRAME | HIGH] Add the field to `AgentPackageRunRequest`, `PublishedAgentRunExecution` inputs, Controlled ReAct start/resume context, and trace-safe run-start summary. Approval resume must restore the same frozen context rather than resolving current claims again.

- [ ] **Step 5: Run targeted and trust-boundary tests**

Run: `uv run --extra dev python -m pytest tests/test_insurance_authorization.py tests/test_run_execution_api.py tests/test_approval_resume.py tests/test_trust_boundaries.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/contracts/insurance_authorization.py proof_agent/contracts/__init__.py proof_agent/observability/api/operator_identity.py proof_agent/delivery/api.py proof_agent/delivery/run_execution_service.py proof_agent/delivery/agent_package_execution.py proof_agent/runtime/approval_resume.py proof_agent/bootstrap/composition.py tests/test_insurance_authorization.py tests/test_run_execution_api.py tests/test_approval_resume.py
git commit -m "feat: propagate trusted insurance knowledge scope"
```

### Phase A Completion Gate

- [ ] Run: `uv run --extra dev python -m pytest tests/test_hybrid_document_contracts.py tests/test_insurance_rule_contracts.py tests/test_knowledge_index_contracts.py tests/test_knowledge_binding_resolver.py tests/test_insurance_authorization.py -q`
- [ ] Run: `uv run --extra dev ruff check proof_agent tests`
- [ ] Run: `uv run --extra dev --extra openai mypy proof_agent`
- [ ] Run: `uv run --extra dev proof-agent demo`

[FRAME | HIGH] Expected: all new contract tests pass, the deterministic demo remains unchanged, and no Hybrid network or model dependency is imported by default.

## Phase B — Structured Ingestion, Rule Projection, And Review

### Task 6: Add Hybrid Ports And Deterministic Test Adapters

**Files:**

- Create: `proof_agent/capabilities/knowledge/hybrid/ports.py`
- Create: `proof_agent/configuration/hybrid_knowledge_repository.py`
- Create: `tests/test_hybrid_knowledge_repository.py`

- [ ] **Step 1: Write failing protocol-level repository tests**

```python
def test_in_memory_repository_claims_one_job_with_fencing_token() -> None:
    repo = InMemoryHybridKnowledgeRepository()
    repo.enqueue(job("job_1"))
    first = repo.claim_next(worker_id="worker_a", lease_seconds=30)
    second = repo.claim_next(worker_id="worker_b", lease_seconds=30)
    assert first is not None
    assert first.fencing_token == 1
    assert second is None
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_knowledge_repository.py -q`

Expected: FAIL because ports and the reference adapter are absent.

- [ ] **Step 3: Define narrow protocols**

```python
class KnowledgeArtifactStore(Protocol):
    def put_immutable(self, *, key: str, content: bytes, media_type: str) -> ExactArtifactRef: ...
    def get_exact(self, ref: ExactArtifactRef) -> bytes: ...


class HybridSearchIndex(Protocol):
    def bulk_upsert(self, request: ProjectionBulkRequest) -> ProjectionBulkResult: ...
    def verify_identity(self, expected: SearchIndexIdentity) -> SearchIndexIdentity: ...
    def search(self, request: HybridSearchRequest) -> tuple[HybridSearchHit, ...]: ...
```

[FRAME | HIGH] Add focused protocols for parser, embedding, reranker, work scheduler, authority repository, and clock. Implement only deterministic in-memory/filesystem adapters in this task.

- [ ] **Step 4: Implement lease, fencing, idempotency, and immutable artifact tests**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_knowledge_repository.py -q`

Expected: PASS, including stale-token rejection and duplicate immutable-key digest validation.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/capabilities/knowledge/hybrid/ports.py proof_agent/configuration/hybrid_knowledge_repository.py tests/test_hybrid_knowledge_repository.py
git commit -m "feat: add hybrid knowledge ports and reference store"
```

### Task 7: Add Provider-Specific Hybrid PDF Intake

**Files:**

- Create: `proof_agent/capabilities/knowledge/hybrid/intake.py`
- Modify: `proof_agent/bootstrap/validation.py`
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `proof_agent/capabilities/knowledge/ingestion/contracts.py`
- Modify: `tests/test_knowledge_document_parsers.py`
- Create: `tests/test_hybrid_intake.py`

- [ ] **Step 1: Write failing separation tests**

```python
def test_blank_scanned_pdf_is_accepted_by_hybrid_preflight(tmp_path: Path) -> None:
    path = write_blank_pdf(tmp_path / "scan.pdf")
    result = preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert result.page_profiles[0].requires_ocr is True


def test_blank_pdf_remains_rejected_by_local_index_parser(tmp_path: Path) -> None:
    path = write_blank_pdf(tmp_path / "scan.pdf")
    with pytest.raises(ProofAgentError):
        parse_quarantined_upload(path, filename="scan.pdf", content_type="application/pdf")
```

- [ ] **Step 2: Run tests and verify Hybrid failure only**

Run: `uv run --extra dev --extra ingestion python -m pytest tests/test_hybrid_intake.py tests/test_knowledge_document_parsers.py -q`

Expected: Hybrid import fails; all existing Local Index tests retain current behavior.

- [ ] **Step 3: Implement `HybridIntakeLimits` and page profiling**

```python
class HybridIntakeLimits(FrozenModel):
    max_file_bytes: int
    max_pdf_pages: int
    max_batch_files: int
    max_source_documents: int = 10_000


def preflight_hybrid_pdf(path: Path, *, limits: HybridIntakeLimits) -> HybridPdfPreflight:
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise hybrid_intake_error("encrypted_pdf")
    profiles = tuple(profile_page(page, page_number=i) for i, page in enumerate(reader.pages, 1))
    return HybridPdfPreflight(page_count=len(reader.pages), page_profiles=profiles)
```

[FRAME | HIGH] Use `pypdf` only for safe preflight and native-text ratio sampling. Do not return canonical text from this function.

- [ ] **Step 4: Add provider-aware upload routing**

[FRAME | HIGH] Extend Source validation and upload API branches for `hybrid_index`, using its configured limits and Hybrid repository. Keep Local Index request limits and messages unchanged. Reject Markdown, archives, encrypted PDFs, executable content, and customer attachment routes for Hybrid V1.

- [ ] **Step 5: Run intake and API regression tests**

Run: `uv run --extra dev --extra ingestion python -m pytest tests/test_hybrid_intake.py tests/test_knowledge_document_parsers.py tests/test_agent_configuration_api.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/capabilities/knowledge/hybrid/intake.py proof_agent/bootstrap/validation.py proof_agent/delivery/configuration_api.py proof_agent/capabilities/knowledge/ingestion/contracts.py tests/test_hybrid_intake.py tests/test_knowledge_document_parsers.py tests/test_agent_configuration_api.py
git commit -m "feat: add hybrid pdf intake"
```

### Task 8: Add Docling And Paddle Service Adapters Plus Canonicalization

**Files:**

- Create: `proof_agent/capabilities/knowledge/hybrid/parser_clients.py`
- Create: `proof_agent/capabilities/knowledge/hybrid/canonicalizer.py`
- Create: `proof_agent/capabilities/knowledge/hybrid/quality.py`
- Create: `proof_agent/capabilities/knowledge/hybrid/pipeline.py`
- Create: `tests/test_hybrid_parser_pipeline.py`
- Create: `tests/fixtures/knowledge/hybrid/docling-simple.json`
- Create: `tests/fixtures/knowledge/hybrid/docling-complex-table.json`
- Create: `tests/fixtures/knowledge/hybrid/paddle-ocr-page.json`

- [ ] **Step 1: Write failing canonicalization tests using checked-in vendor fixtures**

```python
def test_docling_fixture_maps_page_bbox_and_table_cells() -> None:
    artifact = canonicalize_docling(load_fixture("docling-complex-table.json"), build=build_id())
    assert artifact.pages[0].tables[0].cells
    assert artifact.pages[0].tables[0].cells[0].bbox.x1 > 0


def test_paddle_escalation_replaces_one_block_without_mixing_text() -> None:
    result = merge_selected_results(docling_artifact(), paddle_page(), decisions=(replace_block(),))
    assert result.pages[0].blocks[0].source_method == "ocr"
    assert result.pages[0].blocks[0].text == "selected paddle text"
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_parser_pipeline.py -q`

Expected: FAIL because parser adapters and canonicalizers are absent.

- [ ] **Step 3: Implement private service request contracts**

```python
class PrivateParserClient(Protocol):
    def parse(self, request: ParserServiceRequest) -> ParserServiceResponse: ...


class ParserServiceRequest(FrozenModel):
    original_ref: ExactArtifactRef
    page_numbers: tuple[int, ...]
    parser_revision: str
    model_digests: tuple[str, ...]
    configuration_sha256: str
```

[FRAME | HIGH] The client receives an injected guarded transport and exact service/model revisions. It must never download weights, follow redirects, or expose vendor types outside the adapter.

- [ ] **Step 4: Implement quality decisions and explicit merge records**

[FRAME | HIGH] Quality rules cover missing native text, reading-order gaps, table-cell integrity, cross-page continuation, and parser warnings. Emit `PASS`, `ESCALATE_PAGE`, or `REVIEW_REQUIRED`; merge only at recorded block/table boundaries.

- [ ] **Step 5: Run fixture tests**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_parser_pipeline.py -q`

Expected: PASS without network access.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/capabilities/knowledge/hybrid/parser_clients.py proof_agent/capabilities/knowledge/hybrid/canonicalizer.py proof_agent/capabilities/knowledge/hybrid/quality.py proof_agent/capabilities/knowledge/hybrid/pipeline.py tests/test_hybrid_parser_pipeline.py tests/fixtures/knowledge/hybrid
git commit -m "feat: add structured parser pipeline"
```

### Task 9: Add The Hybrid Worker And Artifact Build Identity

**Files:**

- Create: `proof_agent/capabilities/knowledge/ingestion/hybrid_worker.py`
- Modify: `proof_agent/capabilities/knowledge/ingestion/worker.py`
- Modify: `proof_agent/capabilities/knowledge/ingestion/__init__.py`
- Modify: `proof_agent/delivery/cli.py`
- Create: `tests/test_hybrid_knowledge_worker.py`

- [ ] **Step 1: Write failing worker lifecycle tests**

```python
def test_hybrid_worker_retries_transient_parser_failure_but_reviews_content_failure() -> None:
    transient = run_worker(parser=parser_timeout_once())
    assert transient.state == "retry_scheduled"
    review = run_worker(parser=ambiguous_table_parser())
    assert review.state == "review_required"
    assert review.auto_retry_count == 0
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_knowledge_worker.py -q`

Expected: FAIL because the Hybrid worker is absent.

- [ ] **Step 3: Implement provider-dispatched job handling**

```python
class HybridKnowledgeWorker:
    def run_once(self) -> HybridWorkerOutcome | None:
        claim = self._repo.claim_next(worker_id=self._worker_id, lease_seconds=60)
        if claim is None:
            return None
        try:
            return self._process_claim(claim)
        except TransientKnowledgeServiceError as exc:
            return self._repo.schedule_retry(claim, safe_error(exc))
        except ReviewRequiredError as exc:
            return self._repo.require_review(claim, safe_review_reason(exc))
```

[FRAME | HIGH] Keep existing Local Index worker semantics intact. The CLI chooses a handler by claimed job provider; no Hybrid code runs for Local Index tasks.

- [ ] **Step 4: Persist original, vendor JSON, canonical JSON, preview, and build identity**

[FRAME | HIGH] Finalize every artifact immutably through `KnowledgeArtifactStore`, verify digest/length, and commit only exact references. A stale fencing token may leave an orphan artifact but cannot commit job state.

- [ ] **Step 5: Run Hybrid and existing worker regressions**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_knowledge_worker.py tests/test_knowledge_ingestion_worker.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/capabilities/knowledge/ingestion/hybrid_worker.py proof_agent/capabilities/knowledge/ingestion/worker.py proof_agent/capabilities/knowledge/ingestion/__init__.py proof_agent/delivery/cli.py tests/test_hybrid_knowledge_worker.py
git commit -m "feat: add hybrid knowledge worker"
```

### Task 10: Project Coherent Rule Unit Revisions And Metadata Drafts

**Files:**

- Create: `proof_agent/capabilities/knowledge/hybrid/rule_units.py`
- Create: `proof_agent/capabilities/knowledge/hybrid/versioning.py`
- Create: `tests/test_hybrid_rule_units.py`

- [ ] **Step 1: Write failing structural projection tests**

```python
def test_table_cells_project_as_one_row_rule_unit_with_headers() -> None:
    units = project_rule_units(canonical_table_artifact(), document_defaults=defaults())
    row = next(unit for unit in units if unit.unit_kind == "table_row")
    assert "Age" in row.table_context
    assert "18-60" in row.content
    assert row.cell_coordinates
    assert all(unit.unit_kind != "cell" for unit in units)
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_rule_units.py -q`

Expected: FAIL because the projector is absent.

- [ ] **Step 3: Implement deterministic units and inheritance**

```python
def project_rule_units(
    artifact: StructuredKnowledgeDocumentArtifact,
    *,
    document_defaults: InsuranceRuleMetadataDraft,
) -> tuple[InsuranceRuleUnitDraft, ...]:
    return tuple(
        unit
        for page in artifact.pages
        for unit in (*project_sections(page), *project_table_rows(page))
    )
```

[FRAME | HIGH] Preserve headings, definitions, table headers, row groups, continuation ids, page/bbox/cell lineage, and inherited document metadata. Do not use fixed token chunks as authority units.

- [ ] **Step 4: Add immutable revision fingerprint tests**

[FRAME | HIGH] Assert that content, structured build, approved metadata, or visibility revision changes alter `rule_unit_revision_id`, while a logical rule key remains stable for review diffs only.

Run: `uv run --extra dev python -m pytest tests/test_hybrid_rule_units.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/capabilities/knowledge/hybrid/rule_units.py proof_agent/capabilities/knowledge/hybrid/versioning.py tests/test_hybrid_rule_units.py
git commit -m "feat: project insurance rule unit revisions"
```

### Task 11: Add Workbook Curation And Human Review Surfaces

**Files:**

- Create: `proof_agent/capabilities/knowledge/hybrid/workbook.py`
- Modify: `pyproject.toml`
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/api/client.ts`
- Create: `dashboard/src/components/knowledge/KnowledgeReviewPanel.tsx`
- Create: `dashboard/src/components/knowledge/__tests__/KnowledgeReviewPanel.test.tsx`
- Modify: `dashboard/src/pages/KnowledgeDetailPage.tsx`
- Create: `tests/test_insurance_metadata_workbook.py`
- Create: `tests/fixtures/knowledge/hybrid/metadata-workbook.xlsx`

- [ ] **Step 1: Add the optional workbook dependency**

```toml
hybrid = ["httpx>=0.27.0,<1", "openpyxl>=3.1.5,<4"]
```

[FRAME | HIGH] Do not add Docling, Paddle, embedding, or reranker packages to Proof Agent extras.

- [ ] **Step 2: Write failing literal-cell, exact-anchor, and conflict tests**

```python
def test_workbook_rejects_formula_authority_cells() -> None:
    with pytest.raises(WorkbookValidationError, match="literal cells"):
        import_metadata_workbook(formula_fixture(), known_anchors=anchors())


def test_pdf_and_workbook_disagreement_blocks_readiness() -> None:
    result = reconcile_metadata_drafts(pdf_draft(), workbook_draft(authority="regional"))
    assert result.state == "review_required"
    assert result.conflicts[0].field == "authority"
```

- [ ] **Step 3: Run backend tests and verify failure**

Run: `uv run --extra dev --extra hybrid python -m pytest tests/test_insurance_metadata_workbook.py -q`

Expected: FAIL because the importer is absent.

- [ ] **Step 4: Implement template-bound import and review APIs**

[FRAME | HIGH] Accept only literal cells in the versioned template, reject macros/external links/formulas in authority columns, bind every row to exact Source/document/revision and optional canonical anchor, persist original and normalized artifacts, and create drafts only. Add list/detail/approve/correct/reject review routes guarded by Knowledge edit/publish permissions.

- [ ] **Step 5: Write the failing Dashboard review test**

```tsx
it('blocks publication while metadata conflicts remain', async () => {
  render(<KnowledgeReviewPanel sourceId="ks_1" />)
  expect(await screen.findByText('Authority conflict')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Publish source' })).toBeDisabled()
})
```

- [ ] **Step 6: Implement the focused review panel and run UI tests**

Run: `npm test --workspace dashboard -- KnowledgeReviewPanel.test.tsx KnowledgeDetailPage.test.tsx`

Expected: PASS.

- [ ] **Step 7: Run backend tests and commit**

Run: `uv run --extra dev --extra hybrid python -m pytest tests/test_insurance_metadata_workbook.py tests/test_agent_configuration_api.py -q`

Expected: PASS.

```bash
git add pyproject.toml proof_agent/capabilities/knowledge/hybrid/workbook.py proof_agent/delivery/configuration_api.py dashboard/src/api/types.ts dashboard/src/api/client.ts dashboard/src/components/knowledge/KnowledgeReviewPanel.tsx dashboard/src/components/knowledge/__tests__/KnowledgeReviewPanel.test.tsx dashboard/src/pages/KnowledgeDetailPage.tsx tests/test_insurance_metadata_workbook.py tests/fixtures/knowledge/hybrid/metadata-workbook.xlsx
git commit -m "feat: add insurance rule metadata review"
```

### Phase B Completion Gate

- [ ] Run all Phase B tests with `uv run --extra dev --extra ingestion --extra hybrid python -m pytest tests/test_hybrid_intake.py tests/test_hybrid_parser_pipeline.py tests/test_hybrid_knowledge_worker.py tests/test_hybrid_rule_units.py tests/test_insurance_metadata_workbook.py -q`.
- [ ] Run `npm test --workspace dashboard -- KnowledgeReviewPanel.test.tsx KnowledgeDetailPage.test.tsx`.
- [ ] Run one fixture-only worker from quarantine through `review_required` and one through canonical artifact plus approved Rule Unit revisions.
- [ ] Verify Local Index blank-PDF rejection, worker, publication, and deterministic demo tests still pass.

## Phase C — Index Projection And Serialized Source Publication

### Task 12: Freeze Build, Index, Unit, And Retrieval Profile Fingerprints

**Files:**

- Modify: `proof_agent/capabilities/knowledge/hybrid/versioning.py`
- Create: `tests/test_hybrid_versioning.py`

- [ ] **Step 1: Write the fingerprint matrix before implementation**

```python
@pytest.mark.parametrize(
    "field",
    [
        "canonical_schema_version",
        "search_projection_version",
        "mapping_sha256",
        "analyzer_sha256",
        "embedding_model_revision",
        "embedding_instruction_sha256",
        "embedding_dimension",
        "normalized",
    ],
)
def test_index_compatibility_field_changes_generation(field: str) -> None:
    assert generation_id(**{field: changed_value(field)}) != generation_id()


@pytest.mark.parametrize("field", ["reranker_revision", "rerank_budget", "final_budget"])
def test_query_time_field_changes_profile_but_not_generation(field: str) -> None:
    assert profile_id(**{field: changed_value(field)}) != profile_id()
    assert generation_id() == generation_id()
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_versioning.py -q`

Expected: FAIL because the fingerprint functions are incomplete.

- [ ] **Step 3: Implement canonical JSON hashing**

```python
def stable_digest(value: Mapping[str, object]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()
```

[FRAME | HIGH] Implement separate functions for structured build, Rule Unit revision, Index Generation, Retrieval Profile Revision, manifest shard, manifest root, and projection attestation. Each function accepts only its declared compatibility fields.

- [ ] **Step 4: Add negative tests for accidental query-time fields in generation hashing**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_versioning.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/capabilities/knowledge/hybrid/versioning.py tests/test_hybrid_versioning.py
git commit -m "feat: separate knowledge compatibility fingerprints"
```

### Task 13: Add Private Embedding, Reranker, And Scheduler Clients

**Files:**

- Create: `proof_agent/capabilities/knowledge/hybrid/model_clients.py`
- Create: `tests/test_hybrid_model_clients.py`
- Modify: `proof_agent/capabilities/knowledge/hybrid/parser_clients.py`
- Modify: `proof_agent/capabilities/knowledge/hybrid/pipeline.py`
- Modify: `proof_agent/capabilities/knowledge/ingestion/hybrid_worker.py`
- Modify: `proof_agent/bootstrap/composition.py`
- Modify: `proof_agent/delivery/api.py`
- Create: `tests/test_hybrid_scheduler_integration.py`
- Create: `tests/test_hybrid_composition.py`
- Modify: `.env.example`

- [ ] **Step 1: Write failing conformance tests against a fake guarded transport**

```python
def test_embedding_request_pins_revision_instruction_and_dimension() -> None:
    transport = RecordingTransport(response={"vectors": [[0.1, 0.2]]})
    scheduler = ImmediateFakeKnowledgeModelWorkScheduler()
    client = PrivateEmbeddingClient(
        transport=transport,
        scheduler=scheduler,
        endpoint="https://embed.internal",
    )
    client.embed(
        texts=("insurance rule",),
        model_revision="qwen3-embedding-0.6b@sha256:model",
        instruction="Represent the insurance rule for retrieval",
        dimension=1024,
        normalized=True,
        priority="offline",
    )
    assert transport.last_request["model_revision"].endswith("sha256:model")
    assert transport.last_request["dimension"] == 1024


def test_scheduler_places_online_rerank_before_offline_ocr() -> None:
    scheduler = InMemoryKnowledgeModelWorkScheduler()
    offline = scheduler.submit(kind="ocr", priority="offline")
    online = scheduler.submit(kind="rerank", priority="online")
    assert scheduler.claim_next().work_id == online.work_id
    assert offline.state == "queued"
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_model_clients.py -q`

Expected: FAIL because clients and scheduler are absent.

- [ ] **Step 3: Implement transport-only clients and typed responses**

```python
class PrivateEmbeddingClient:
    def embed(self, *, texts: tuple[str, ...], model_revision: str,
              instruction: str, dimension: int, normalized: bool,
              priority: WorkPriority) -> tuple[tuple[float, ...], ...]:
        response = self._scheduler.submit_and_wait(
            kind="embedding",
            priority=priority,
            operation=lambda: self._transport.post_json(self._endpoint, {
                "texts": list(texts),
                "model_revision": model_revision,
                "instruction": instruction,
                "dimension": dimension,
                "normalized": normalized,
            }),
        )
        return validate_vectors(response, count=len(texts), dimension=dimension)
```

[FRAME | HIGH] Add equivalent reranker and scheduler clients with explicit timeouts, queue-time reporting, exact revision echo validation, bounded batch sizes, and no redirect or runtime-download behavior. Endpoint configuration uses secret-safe internal service handles; `.env.example` contains names only.

- [ ] **Step 4: Add malformed dimension, wrong revision, timeout, and cancellation tests**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_model_clients.py -q`

Expected: PASS.

- [ ] **Step 5: Route every private-service call through one scheduler port**

[FRAME | HIGH] `PrivateDoclingClient`, `PrivatePaddleClient`, `PrivateEmbeddingClient`, and `PrivateRerankerClient` must receive the same `KnowledgeModelWorkScheduler` dependency. Their public methods submit typed work and wait on the resulting handle; no adapter may call its transport directly. The Hybrid parse pipeline labels Docling/Paddle/OCR as `offline`; Task 16 must label publication-time embedding as `offline`, and Task 19 must label query embedding and reranking as `online`. Cancellation and timeout propagate to the shared handle, and every result reports scheduler queue time separately from service time.

[FRAME | HIGH] `proof_agent/bootstrap/composition.py` is the only production composition root for this port. It constructs one `PrivateKnowledgeModelWorkSchedulerClient` from the guarded internal scheduler endpoint and queue namespace, injects that same instance into Hybrid parser, embedding, reranker, ingestion-worker, publication, and retrieval factories, and registers exactly one close hook in the FastAPI lifespan. Separate worker processes use the same remote endpoint and namespace, so priority is global rather than process-local. `InMemoryKnowledgeModelWorkScheduler` is test-only; production composition fails closed if scheduler configuration is missing and must never create one local queue per adapter.

```python
def test_online_rerank_preempts_queued_ingestion_across_real_adapters() -> None:
    scheduler = PausedFakeScheduler()
    parser = PrivatePaddleClient(transport=transport(), scheduler=scheduler)
    reranker = PrivateRerankerClient(transport=transport(), scheduler=scheduler)
    parser.submit_page(page(), priority="offline")
    reranker.submit(query(), priority="online")
    assert scheduler.release_next().kind == "rerank"


def test_composition_injects_one_scheduler_client_everywhere() -> None:
    graph = compose_hybrid_knowledge(settings=scheduler_settings())
    assert graph.parser.scheduler is graph.embedding.scheduler
    assert graph.embedding.scheduler is graph.reranker.scheduler
    assert graph.reranker.scheduler is graph.ingestion_worker.scheduler
    assert graph.scheduler.close_registration_count == 1
```

Run: `uv run --extra dev python -m pytest tests/test_hybrid_model_clients.py tests/test_hybrid_scheduler_integration.py tests/test_hybrid_composition.py tests/test_hybrid_parser_pipeline.py -q`

Expected: PASS and the recording transports show no request before the scheduler releases its work handle.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/capabilities/knowledge/hybrid/model_clients.py proof_agent/capabilities/knowledge/hybrid/parser_clients.py proof_agent/capabilities/knowledge/hybrid/pipeline.py proof_agent/capabilities/knowledge/ingestion/hybrid_worker.py proof_agent/bootstrap/composition.py proof_agent/delivery/api.py tests/test_hybrid_model_clients.py tests/test_hybrid_scheduler_integration.py tests/test_hybrid_composition.py .env.example
git commit -m "feat: add private knowledge model clients"
```

### Task 14: Build The OpenSearch Rule Unit Projection And Hybrid Query

**Files:**

- Create: `proof_agent/capabilities/knowledge/hybrid/opensearch.py`
- Create: `tests/test_hybrid_opensearch_adapter.py`
- Create: `tests/integration/test_hybrid_opensearch.py`
- Create: `docker-compose.hybrid-test.yml`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write failing mapping and query tests**

```python
def test_hybrid_query_applies_one_filter_to_bm25_and_vector_lanes() -> None:
    request = governed_search_request(scope=inst_1_scope(), publication_seq=7)
    body = build_hybrid_query(request)
    common_filter = body["query"]["hybrid"]["filter"]
    assert {"range": {"publication_seq_from": {"lte": 7}}} in flatten(common_filter)
    assert {
        "bool": {
            "should": [
                {"range": {"publication_seq_to": {"gte": 7}}},
                {"bool": {"must_not": {"exists": {"field": "publication_seq_to"}}}},
            ],
            "minimum_should_match": 1,
        }
    } in flatten(common_filter)
    assert {"term": {"allowed_institutions": "INST-1"}} in flatten(common_filter)
    assert "post_filter" not in body


def test_mapping_uses_keyword_fields_for_acl_and_identifiers() -> None:
    mapping = rule_unit_index_mapping(dimension=1024)
    assert mapping["properties"]["rule_unit_revision_id"]["type"] == "keyword"
    assert mapping["properties"]["dense_vector"]["dimension"] == 1024
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev --extra hybrid python -m pytest tests/test_hybrid_opensearch_adapter.py -q`

Expected: FAIL because the OpenSearch adapter is absent.

- [ ] **Step 3: Implement deterministic index naming, mapping, bulk upsert, and query building**

```python
def physical_index_name(source_id: str, generation_id: str) -> str:
    return f"pa-knowledge-{safe_id(source_id)}-{safe_id(generation_id)}"


def build_hybrid_query(request: HybridSearchRequest) -> dict[str, object]:
    return {
        "size": request.rrf_window,
        "query": {
            "hybrid": {
                "filter": build_common_filter(request),
                "queries": [build_bm25(request), build_knn(request)],
            }
        },
        "search_pipeline": request.rrf_pipeline,
    }
```

[FRAME | HIGH] Project exact identifiers, manifest/metadata/visibility digests, half-closed publication membership intervals (`publication_seq_from <= requested_seq` and `publication_seq_to is null or >= requested_seq`), explicit visibility modes, applicability, effective dates, citation lineage, lexical text, and one dense vector. Never index raw vendor payloads or unapproved drafts. A later publication may close an old revision interval and open a new one inside the same generation; historical bindings therefore never filter on one exact `source_publication_seq` field.

- [ ] **Step 4: Add response normalization and unauthorized-hit rejection tests**

[FRAME | HIGH] The adapter returns only typed ids, relevance rank/score, citation, and bounded content. It rejects missing digests, wrong generation, unexpected index UUID, and hits outside the requested Source even if OpenSearch returns them.

Run: `uv run --extra dev --extra hybrid python -m pytest tests/test_hybrid_opensearch_adapter.py -q`

Expected: PASS without OpenSearch.

- [ ] **Step 5: Add opt-in local integration coverage**

[FRAME | HIGH] `docker-compose.hybrid-test.yml` contains only a local OpenSearch test service with security disabled and no production credentials. Mark integration tests `hybrid_integration` and keep them out of default CI.

Run: `docker compose -f docker-compose.hybrid-test.yml up -d opensearch`

Run: `uv run --extra dev --extra hybrid python -m pytest -m hybrid_integration tests/integration/test_hybrid_opensearch.py -q`

Expected: PASS for mapping creation, filtered BM25+dense search, RRF ordering, and exact index identity.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/capabilities/knowledge/hybrid/opensearch.py tests/test_hybrid_opensearch_adapter.py tests/integration/test_hybrid_opensearch.py docker-compose.hybrid-test.yml pyproject.toml
git commit -m "feat: add opensearch hybrid projection"
```

### Task 15: Build Content-Addressed Publication Manifests And Attestation Chains

**Files:**

- Create: `proof_agent/capabilities/knowledge/hybrid/manifest.py`
- Create: `tests/test_hybrid_manifest.py`

- [ ] **Step 1: Write failing shard-reuse and chain tests**

```python
def test_manifest_reuses_unchanged_document_shards() -> None:
    first = build_manifest(source_id="ks_1", units=units_for_documents("a", "b"))
    second = build_manifest(source_id="ks_1", units=changed_units_for_document("b"))
    assert first.shard_for("a").sha256 == second.shard_for("a").sha256
    assert first.root_sha256 != second.root_sha256


def test_descendant_attestation_must_cover_retained_sequences() -> None:
    with pytest.raises(ValueError, match="retained sequence"):
        append_attestation(parent=attestation(sequences=(1,)), covered_sequences=(2,))
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_manifest.py -q`

Expected: FAIL because manifest builders are absent.

- [ ] **Step 3: Implement immutable shards and root**

```python
def build_manifest_shard(units: tuple[InsuranceRuleUnitRevision, ...]) -> RuleUnitManifestShard:
    entries = tuple(sorted((manifest_entry(unit) for unit in units), key=lambda x: x.rule_unit_revision_id))
    return RuleUnitManifestShard(entries=entries, sha256=stable_digest({"entries": entries}))
```

[FRAME | HIGH] Shard by stable document id, persist each shard immutably, and let one root reference shard exact versions/digests. Unchanged documents reuse shards so routine publication does not rewrite a million-page inventory.

- [ ] **Step 4: Implement attestation parent, coverage, candidate-digest, and index-identity validation**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_manifest.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/capabilities/knowledge/hybrid/manifest.py tests/test_hybrid_manifest.py
git commit -m "feat: add rule unit manifests and attestations"
```

### Task 16: Implement Fenced Hybrid Source Publication And Production Authority Adapters

**Files:**

- Create: `proof_agent/capabilities/knowledge/hybrid/publication.py`
- Create: `proof_agent/configuration/postgres_hybrid_knowledge_repository.py`
- Create: `proof_agent/configuration/migrations/0001_hybrid_knowledge.sql`
- Create: `proof_agent/capabilities/knowledge/hybrid/s3_artifacts.py`
- Create: `proof_agent/capabilities/knowledge/hybrid/recovery.py`
- Modify: `proof_agent/bootstrap/composition.py`
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `proof_agent/delivery/cli.py`
- Modify: `docker-compose.hybrid-test.yml`
- Modify: `pyproject.toml`
- Create: `tests/test_hybrid_publication.py`
- Create: `tests/test_hybrid_recovery.py`
- Create: `tests/integration/test_hybrid_postgres_s3.py`
- Create: `tests/integration/test_hybrid_generation_rebuild.py`

- [ ] **Step 1: Add production-only dependencies without changing deterministic extras**

```toml
production = ["psycopg[binary,pool]>=3.2,<4", "boto3>=1.40,<2"]
```

[FRAME | HIGH] Keep `dev`, `ingestion`, `tree`, and the deterministic demo independent of these packages.

- [ ] **Step 2: Write failing stale-validation, concurrent-attempt, orphan-reconciliation, and rebuild tests**

```python
def test_final_commit_rejects_stale_candidate_digest() -> None:
    attempt = begin_publication(candidate_digest="old")
    with pytest.raises(PublicationConflict):
        commit_publication(attempt, current_candidate_digest="new")


def test_failed_attempt_does_not_publish_but_may_leave_sequence_gap() -> None:
    attempt = begin_publication(sequence=8)
    fail_after_projection(attempt)
    assert current_publication_sequence() == 7
    assert next_reserved_sequence() == 9
    assert orphan_projection_ids() == (attempt.attempt_id,)


def test_reconciler_deletes_only_unreferenced_failed_projection() -> None:
    report = reconcile_orphans(authority=authority(), index=index_with_failed_attempt())
    assert report.deleted_attempt_ids == ("attempt-8",)
    assert active_projection_ids() == ("attempt-7",)


def test_generation_rebuild_reproduces_root_and_coverage() -> None:
    rebuilt = rebuild_generation(source_id="ks_1", generation_id="gen_1")
    assert rebuilt.manifest_root_sha256 == published_manifest_root()
    assert rebuilt.covered_publication_sequences == published_sequences()
```

- [ ] **Step 3: Create PostgreSQL schema with explicit constraints**

```sql
CREATE TABLE knowledge_publication_attempt (
  attempt_id text PRIMARY KEY,
  source_id text NOT NULL,
  reserved_sequence bigint NOT NULL,
  fencing_token bigint NOT NULL,
  source_draft_version_id text NOT NULL,
  candidate_digest text NOT NULL,
  generation_id text NOT NULL,
  validation_id text NOT NULL UNIQUE,
  state text NOT NULL CHECK (state IN ('BUILDING','VALIDATED','PUBLISHED','FAILED')),
  UNIQUE (source_id, reserved_sequence)
);
```

[FRAME | HIGH] Add tables for documents/revisions, structured-build refs, review state, approved Rule Unit revisions, visibility scopes, generations, profiles, manifest refs, attestations, publications, and orphan reconciliation. Use foreign keys and immutable-row constraints; do not store artifact bytes.

- [ ] **Step 4: Implement exact-version S3 put/get and digest verification**

[FRAME | HIGH] Use system-generated keys, create-without-overwrite, returned version ids, SHA-256 plus length verification, and no ETag-as-content-hash assumption.

- [ ] **Step 5: Implement publication orchestration and short final CAS transaction**

```python
def publish(self, request: HybridPublicationRequest) -> HybridKnowledgePublicationRecord:
    attempt = self._repo.begin_attempt(request)
    manifest = self._manifest_builder.finalize(attempt)
    projection = self._index.apply(attempt, manifest)
    attestation = self._attestor.validate(attempt, manifest, projection)
    return self._repo.commit_if_current(attempt, manifest, attestation)
```

[FRAME | HIGH] `commit_if_current` locks the Source row briefly and compares live fencing token, one-use validation id, Draft version, candidate, generation, manifest, and attestation digests. The active Source pointer changes only in this transaction.

[FRAME | HIGH] All publication embeddings call `PrivateEmbeddingClient` with `priority="offline"`; the client itself must pass through the shared scheduler added in Task 13. Persist scheduler queue and service time on the attempt without placing either value in compatibility fingerprints.

[FRAME | HIGH] Extend the Task 13 composition graph instead of constructing a scheduler in publication code. Add a test proving the publication service's embedding client holds `graph.scheduler`, and that publication shutdown does not close the shared client independently.

- [ ] **Step 6: Implement authority-driven orphan reconciliation and generation rebuild**

[FRAME | HIGH] `HybridRecoveryService` treats PostgreSQL publication, manifest, attestation, and attempt rows as authority. Reconciliation classifies stale failed/abandoned projections, proves no active or retained publication references each projection, then deletes or records a retryable cleanup failure. Rebuild reads exact manifest root/shards and artifact versions from PostgreSQL plus S3, creates a fresh physical index UUID, verifies counts/digests/membership intervals, appends a rebuild attestation, and swaps the generation projection pointer by fenced CAS. It never derives authority from the damaged OpenSearch index.

[FRAME | HIGH] Add idempotent CLI commands `proof-agent knowledge reconcile-orphans --source-id ... --dry-run|--apply` and `proof-agent knowledge rebuild-generation --source-id ... --generation-id ...`. Dry-run is the default for cleanup. Unit tests cover active-reference refusal, interrupted cleanup retry, corrupt S3 object refusal, digest mismatch, fresh index UUID, and identical manifest/coverage.

Run: `uv run --extra dev --extra hybrid python -m pytest tests/test_hybrid_recovery.py -q`

Expected: PASS without external services.

- [ ] **Step 7: Add Hybrid validate/publish/list API branches**

[FRAME | HIGH] Reuse existing Source publication routes and permission checks, dispatching by provider. Return stable conflicts for stale validation, lost fencing, manifest mismatch, and attestation failure.

- [ ] **Step 8: Provision disposable dependencies and run production-adapter integration tests**

Run: `uv run --extra dev --extra hybrid python -m pytest tests/test_hybrid_publication.py tests/test_hybrid_recovery.py tests/test_knowledge_source_publication.py -q`

Expected: PASS.

[FRAME | HIGH] Extend `docker-compose.hybrid-test.yml` with pinned disposable PostgreSQL and MinIO services, named health checks, a one-shot bucket initializer, and test-only credentials. The integration fixtures read `HYBRID_TEST_POSTGRES_DSN`, `HYBRID_TEST_S3_ENDPOINT`, `HYBRID_TEST_S3_BUCKET`, `HYBRID_TEST_S3_ACCESS_KEY`, and `HYBRID_TEST_S3_SECRET_KEY`, run migration `0001_hybrid_knowledge.sql`, and empty only their unique per-run bucket prefix during teardown.

Run: `docker compose -f docker-compose.hybrid-test.yml up -d --wait postgres minio minio-init opensearch`

Run: `HYBRID_TEST_POSTGRES_DSN=postgresql://proof:proof@127.0.0.1:55432/proof HYBRID_TEST_S3_ENDPOINT=http://127.0.0.1:59000 HYBRID_TEST_S3_BUCKET=proof-agent-test HYBRID_TEST_S3_ACCESS_KEY=proof HYBRID_TEST_S3_SECRET_KEY=proof-secret uv run --extra dev --extra hybrid --extra production python -m pytest -m hybrid_integration tests/integration/test_hybrid_postgres_s3.py tests/integration/test_hybrid_generation_rebuild.py -q`

Expected: PASS for migrations, versioned artifact writes, fenced publication, orphan cleanup, and full generation rebuild against the disposable services.

Run after integration verification: `docker compose -f docker-compose.hybrid-test.yml down -v --remove-orphans`

Expected: disposable containers, networks, and volumes are removed; no production endpoint is addressable from this compose project.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml docker-compose.hybrid-test.yml proof_agent/capabilities/knowledge/hybrid/publication.py proof_agent/capabilities/knowledge/hybrid/recovery.py proof_agent/configuration/postgres_hybrid_knowledge_repository.py proof_agent/configuration/migrations/0001_hybrid_knowledge.sql proof_agent/capabilities/knowledge/hybrid/s3_artifacts.py proof_agent/bootstrap/composition.py proof_agent/delivery/configuration_api.py proof_agent/delivery/cli.py tests/test_hybrid_publication.py tests/test_hybrid_recovery.py tests/integration/test_hybrid_postgres_s3.py tests/integration/test_hybrid_generation_rebuild.py
git commit -m "feat: publish attested hybrid knowledge sources"
```

### Phase C Completion Gate

- [ ] Run all Phase C unit tests.
- [ ] Run the OpenSearch and PostgreSQL/S3 integration markers against disposable services.
- [ ] Publish sequence 1, publish a delta at sequence 2, and prove a sequence-1 query still returns the sequence-1 Rule Unit revisions and visibility.
- [ ] Force failure after OpenSearch refresh and prove PostgreSQL still exposes the prior publication while reconciliation lists the orphan attempt.
- [ ] Rebuild one physical `source + generation` index from PostgreSQL plus S3 manifests and compare manifest roots and attestation coverage.
- [ ] Close more than `1,000` retained memberships, fail in the second real restoration batch,
      then prove a retry converges and a later publication succeeds.
- [ ] Create a disposable PostgreSQL database from the complete historical Phase C migration DDL, apply
      the current migration twice, and prove legacy rows plus new locator, orphan, validation,
      constraint, and immutability behavior.

## Phase D — Governed Hybrid Runtime And Agent Activation

### Task 17: Resolve Hybrid Publications Into Published Agent Bindings

**Files:**

- Modify: `proof_agent/bootstrap/knowledge_resolution.py`
- Modify: `proof_agent/configuration/local_store.py`
- Modify: `proof_agent/configuration/hybrid_knowledge_repository.py`
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `proof_agent/delivery/published_agents.py`
- Modify: `tests/test_knowledge_binding_resolver.py`
- Modify: `tests/test_published_agent_versions.py`

- [ ] **Step 1: Write failing Hybrid resolution tests**

```python
def test_resolver_pins_publication_profile_manifest_and_attestation() -> None:
    publication = publish_hybrid_source(sequence=7)
    profile = publish_retrieval_profile("krp_2")
    resolved = resolve_shared_binding(publication=publication, profile=profile)
    binding = resolved.bindings[0]
    assert isinstance(binding, ResolvedHybridKnowledgeBinding)
    assert binding.source_publication_seq == 7
    assert binding.retrieval_profile_revision_id == "krp_2"
    assert binding.publication_attestation_id == publication.attestation.attestation_id
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_knowledge_binding_resolver.py tests/test_published_agent_versions.py -q`

Expected: FAIL because the resolver has only Local Index and remote branches.

- [ ] **Step 3: Add Draft profile selection and Hybrid resolution**

[FRAME | HIGH] A Draft binding may select an approved Retrieval Profile revision or inherit the Source default. Agent validation resolves an exact profile and publication; Agent publication freezes the complete Hybrid variant. Later Source/profile publication creates an upgrade opportunity only.

- [ ] **Step 4: Add missing/stale/incompatible publication failures**

[FRAME | HIGH] Fail Agent validation when manifest/attestation refs are missing, the profile is unpublished, or its expected generation fields conflict. Keep existing Local Index and remote resolution behavior unchanged.

- [ ] **Step 5: Run resolver, Agent publication, and rollback tests**

Run: `uv run --extra dev python -m pytest tests/test_knowledge_binding_resolver.py tests/test_published_agent_versions.py tests/test_agent_configuration_store.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/bootstrap/knowledge_resolution.py proof_agent/configuration/local_store.py proof_agent/configuration/hybrid_knowledge_repository.py proof_agent/delivery/configuration_api.py proof_agent/delivery/published_agents.py tests/test_knowledge_binding_resolver.py tests/test_published_agent_versions.py
git commit -m "feat: pin hybrid knowledge in agent versions"
```

### Task 18: Admit Structured Insurance Conditions And Build Governed Hybrid Requests

**Files:**

- Create: `proof_agent/control/knowledge/hybrid_request.py`
- Modify: `proof_agent/contracts/react_workflow.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- Modify: `proof_agent/control/workflow/controlled_react/composition.py`
- Create: `tests/test_hybrid_request.py`
- Modify: `tests/test_react_intent_resolution.py`

- [ ] **Step 1: Write failing proposal/admission tests**

```python
def test_model_proposed_unknown_condition_is_rejected() -> None:
    proposal = InsuranceConditionProposal(values={"vip_override": "yes"})
    result = admit_insurance_conditions(proposal, taxonomy=approved_taxonomy())
    assert result.admitted is False
    assert result.reason == "unknown_condition_key"


def test_missing_authority_condition_clarifies_before_search() -> None:
    result = build_governed_hybrid_request(
        intent=conditional_guidance_intent(missing=("region",)),
        authorization=inst_1_scope(),
        binding=hybrid_binding(),
    )
    assert result.clarification.missing_fields == ("region",)
    assert result.request is None
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_request.py tests/test_react_intent_resolution.py -q`

Expected: FAIL because structured insurance conditions are absent.

- [ ] **Step 3: Extend intent output with a bounded proposal**

```python
class InsuranceConditionProposal(FrozenModel):
    values: Mapping[str, str] = Field(default_factory=FrozenDict)


class InsuranceConditionAdmission(FrozenModel):
    admitted: bool
    normalized_values: Mapping[str, str] = Field(default_factory=FrozenDict)
    missing_authority_fields: tuple[str, ...] = ()
    reason: str
```

[FRAME | HIGH] Intent Resolution may propose only configured taxonomy keys and values. Control Plane validation, trusted operator scope, server as-of time, and pinned binding facts construct the request. The model never authors visibility, publication, generation, or manifest filters.

- [ ] **Step 4: Implement `GovernedHybridRetrievalRequest` construction**

[FRAME | HIGH] Include exact binding, normalized conditions, approved applicability filters, query set, query type, required evidence slots, as-of time, candidate budgets from the pinned profile, and trace-safe ids. Return clarification/no-recommendation before calling the provider when authority-bearing conditions are missing.

- [ ] **Step 5: Run intent and request tests**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_request.py tests/test_react_intent_resolution.py tests/test_controlled_react_orchestrator.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/control/knowledge/hybrid_request.py proof_agent/contracts/react_workflow.py proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py proof_agent/control/workflow/controlled_react/composition.py tests/test_hybrid_request.py tests/test_react_intent_resolution.py
git commit -m "feat: build governed hybrid retrieval requests"
```

### Task 19: Add Hybrid Provider Execution, ACL Prefilter, And Attestation Verification

**Files:**

- Create: `proof_agent/capabilities/knowledge/hybrid/provider.py`
- Create: `proof_agent/control/knowledge/hybrid_retrieval.py`
- Modify: `proof_agent/capabilities/knowledge/registry.py`
- Modify: `proof_agent/capabilities/knowledge/blended.py`
- Modify: `proof_agent/bootstrap/composition.py`
- Modify: `proof_agent/control/knowledge/retrieval_service.py`
- Create: `tests/test_hybrid_retrieval.py`
- Modify: `tests/test_knowledge_retrieval_service.py`

- [ ] **Step 1: Write failing fail-closed retrieval tests**

```python
def test_attestation_is_verified_before_content_search() -> None:
    search = RecordingSearchIndex(identity=wrong_index_identity())
    with pytest.raises(ProofAgentError, match="attestation"):
        execute_hybrid_retrieval(request(), search=search)
    assert search.content_query_count == 0


def test_acl_filter_reaches_both_retrieval_lanes_and_reranker() -> None:
    result = execute_hybrid_retrieval(request(scope=inst_1_scope()), search=fixture_index())
    assert all(hit.visibility_matches("INST-1") for hit in result.candidates)
    assert all(item.source_id == "ks_1" for item in result.reranker_input)


def test_online_query_work_uses_shared_scheduler_priority() -> None:
    scheduler = RecordingKnowledgeModelWorkScheduler()
    execute_hybrid_retrieval(request(), scheduler=scheduler)
    assert scheduler.submissions_for("query_embedding").only_priority == "online"
    assert scheduler.submissions_for("rerank").only_priority == "online"
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev --extra hybrid python -m pytest tests/test_hybrid_retrieval.py tests/test_knowledge_retrieval_service.py -q`

Expected: FAIL because Hybrid execution is absent.

- [ ] **Step 3: Implement the provider and delegate from the existing service**

```python
class HybridIndexProvider:
    def retrieve_governed(
        self, request: GovernedHybridRetrievalRequest
    ) -> HybridRetrievalCandidates:
        self._attestations.verify_before_search(request.binding)
        embedding = self._embedding.embed_query(request)
        hits = self._search.search(to_search_request(request, embedding))
        verified = self._manifests.verify_candidates(request, hits)
        return self._rerank(request, verified)
```

[FRAME | HIGH] Add a narrow Hybrid branch in `KnowledgeRetrievalService`; keep query orchestration, policy, and trace entry points shared, but move all Hybrid details into `hybrid_retrieval.py`. Do not enlarge the existing 2,000-line module with query DSL, manifest, or authority code.

[FRAME | HIGH] Inject the same `KnowledgeModelWorkScheduler` instance used by ingestion/publication. Query embedding and reranking must call the Task 13 scheduled clients with `priority="online"`; the provider cannot call guarded transports directly. Return queue time and service time as separate trace-safe measurements and cancel pending scheduler work when the governed run is cancelled.

[FRAME | HIGH] Extend the existing composition graph with the provider; do not instantiate a scheduler inside `HybridIndexProvider` or request scope. The composition test must prove provider embedding/reranker clients, publication embedding, and ingestion parser clients all reference `graph.scheduler`.

- [ ] **Step 4: Stop synthesizing admission score from Hybrid relevance**

[FRAME | HIGH] `BlendedKnowledgeProvider` may retain legacy calibrated admission scores but must not calculate Hybrid `admission_score` from native score or fusion weight. Source-local RRF and cross-Source WRRF remain relevance ranks only.

- [ ] **Step 5: Run service, provider, and mixed-binding tests**

Run: `uv run --extra dev --extra hybrid python -m pytest tests/test_hybrid_retrieval.py tests/test_knowledge_retrieval_service.py tests/test_knowledge_provider.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/capabilities/knowledge/hybrid/provider.py proof_agent/control/knowledge/hybrid_retrieval.py proof_agent/capabilities/knowledge/registry.py proof_agent/capabilities/knowledge/blended.py proof_agent/bootstrap/composition.py proof_agent/control/knowledge/retrieval_service.py tests/test_hybrid_retrieval.py tests/test_knowledge_retrieval_service.py tests/test_hybrid_composition.py
git commit -m "feat: execute governed hybrid retrieval"
```

### Task 20: Enforce Authority, Evidence Slots, Context Expansion, And Degradation

**Files:**

- Create: `proof_agent/control/knowledge/insurance_authority.py`
- Create: `proof_agent/control/knowledge/evidence_slots.py`
- Create: `proof_agent/control/knowledge/context_expansion.py`
- Create: `proof_agent/control/knowledge/context_assembler.py`
- Create: `proof_agent/control/knowledge/answer_validator.py`
- Modify: `proof_agent/contracts/evidence.py`
- Modify: `proof_agent/control/context_assembler.py`
- Modify: `proof_agent/control/validators/evidence.py`
- Modify: `proof_agent/control/knowledge/hybrid_retrieval.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- Create: `tests/test_insurance_authority_gate.py`
- Create: `tests/test_hybrid_evidence_slots.py`
- Create: `tests/test_hybrid_context_expansion.py`
- Create: `tests/test_insurance_answer_contract.py`

- [ ] **Step 1: Write the zero-tolerance authority tests**

```python
@pytest.mark.parametrize(
    "failure",
    ["wrong_version", "outside_effective_period", "acl_mismatch", "precedence_conflict", "bad_citation"],
)
def test_authority_failure_never_returns_advisory_answer(failure: str) -> None:
    decision = evaluate_insurance_authority(candidate_with(failure), request())
    assert decision.admitted is False
    assert decision.outcome in {"clarify", "conflict", "no_recommendation"}
```

- [ ] **Step 2: Write comparison completeness and expansion-ACL tests**

```python
def test_comparison_requires_both_product_evidence_slots() -> None:
    result = evaluate_required_slots(comparison_slots("A", "B"), evidence_for_product("A"))
    assert result.complete is False
    assert result.missing_slot_ids == ("product:B",)


def test_context_expansion_does_not_read_unauthorized_definition() -> None:
    store = RecordingRuleStore(definition=restricted_definition("INST-2"))
    expanded = expand_context(selected_rule("INST-1"), request=inst_1_request(), store=store)
    assert restricted_definition_id() not in expanded.unit_ids
    assert store.unauthorized_content_reads == 0


def test_successful_guidance_requires_answer_sections_and_supported_citations() -> None:
    result = validate_generated_insurance_answer(
        generated_answer_missing("conditions"),
        admitted_evidence=complete_guidance_evidence(),
    )
    assert result.admitted is False
    assert result.reason == "missing_required_answer_section"
```

- [ ] **Step 3: Run and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_insurance_authority_gate.py tests/test_hybrid_evidence_slots.py tests/test_hybrid_context_expansion.py tests/test_insurance_answer_contract.py -q`

Expected: FAIL because the gates are absent.

- [ ] **Step 4: Implement deterministic gate order**

[FRAME | HIGH] Execute: manifest/candidate digest → publication membership → visibility → effective period → applicability → business-approved precedence → citation integrity → required slot completeness → Evidence Admission. Relevance rank cannot skip or change this order.

- [ ] **Step 5: Implement independent expansion authorization**

[FRAME | HIGH] Fetch expansion metadata first, apply the same Source/sequence/visibility/applicability filters, and fetch content only for passing ids. Bound expansion to headings, table headers, row group, continuations, and referenced definitions declared by the pinned profile.

- [ ] **Step 6: Implement prevalidated degradations**

[FRAME | HIGH] BM25-only or RRF-without-reranker runs only when the pinned Retrieval Profile names the exact degradation and includes a passing sealed-evaluation evidence ref for Source and query type. Generation, attestation, ACL, manifest, and citation failures never degrade.

- [ ] **Step 7: Assemble bounded model context and enforce the answer contract after generation**

[FRAME | HIGH] `context_assembler.py` accepts only authority-admitted, slot-complete evidence and emits a bounded prompt payload with immutable Rule Unit/citation ids, normalized user conditions, explicit assumptions, and the required answer schema. It must not expose excluded candidates or let the model rewrite applicability, precedence, visibility, effective period, or authority decisions.

[FRAME | HIGH] For a successful advisory answer, the typed result requires `recommendation`, `conditions`, `assumptions`, `rule_basis`, `warnings`, and `service_reminder`; query-type policy may mark a field explicitly `not_applicable` but never silently omit it. `answer_validator.py` runs after generation and before delivery, proving every factual or normative statement maps to admitted Rule Unit ids, every citation anchor exists in the pinned manifest/publication, the answer does not contradict the deterministic authority decision, all required slots remain represented, and no unsupported product/rule claim appears. Failure returns `clarify`, `conflict`, or `no_recommendation` with no advisory prose.

```python
def test_post_generation_validator_rejects_unsupported_recommendation() -> None:
    generated = answer_with_claim("Product B accepts this occupation")
    decision = validate_generated_insurance_answer(generated, admitted_evidence=evidence_for_product_a_only())
    assert decision.outcome == "no_recommendation"
    assert decision.deliverable_answer is None
```

- [ ] **Step 8: Run tests and commit**

Run: `uv run --extra dev python -m pytest tests/test_insurance_authority_gate.py tests/test_hybrid_evidence_slots.py tests/test_hybrid_context_expansion.py tests/test_insurance_answer_contract.py tests/test_evidence_validator.py tests/test_controlled_react_orchestrator.py -q`

Expected: PASS.

```bash
git add proof_agent/control/knowledge/insurance_authority.py proof_agent/control/knowledge/evidence_slots.py proof_agent/control/knowledge/context_expansion.py proof_agent/control/knowledge/context_assembler.py proof_agent/control/knowledge/answer_validator.py proof_agent/contracts/evidence.py proof_agent/control/context_assembler.py proof_agent/control/validators/evidence.py proof_agent/control/knowledge/hybrid_retrieval.py proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py tests/test_insurance_authority_gate.py tests/test_hybrid_evidence_slots.py tests/test_hybrid_context_expansion.py tests/test_insurance_answer_contract.py
git commit -m "feat: enforce insurance evidence authority"
```

### Task 21: Add Trace, Receipt, And Exact Rollback Semantics

**Files:**

- Modify: `proof_agent/observability/audit/trace.py`
- Modify: `proof_agent/observability/audit/receipt.py`
- Modify: `proof_agent/observability/audit/templates/governance_receipt.md.j2`
- Modify: `proof_agent/observability/api/serializers.py`
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `tests/test_trace_writer.py`
- Modify: `tests/test_receipt_generator.py`
- Modify: `tests/test_published_agent_versions.py`
- Modify: `tests/test_knowledge_source_publication.py`

- [ ] **Step 1: Write failing safe-projection tests**

```python
def test_trace_does_not_disclose_excluded_rule_identity_or_content() -> None:
    trace = run_hybrid_query_with_acl_exclusion()
    payload = trace.event("hybrid_retrieval_summary").payload
    assert payload["excluded_count"] == 1
    assert "excluded_rule_unit_ids" not in payload
    assert "excluded_content" not in payload
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_trace_writer.py tests/test_receipt_generator.py -q`

Expected: FAIL because Hybrid trace facts are absent.

- [ ] **Step 3: Add trace-safe lifecycle and runtime events**

[FRAME | HIGH] Record structured-build identity, review transition, generation/profile, publication attempt, manifest/attestation ids, candidate counts, latency including scheduler queue, degradation mode, authority result, evidence-slot status, and citation counts. Never record raw originals, excluded identities, ACL claims, vendor payloads, or full evidence by default.

- [ ] **Step 4: Add Receipt projection and rollback tests**

[FRAME | HIGH] Immediate cutover rollback uses Agent Version Rollback and restores the selected immutable Hybrid binding. Source-content reversion creates a rollback Draft, new Source validation/publication, explicit Agent binding upgrade, Agent validation, and new Agent publication. Add tests proving the two paths cannot be conflated.

- [ ] **Step 5: Run observability and rollback tests**

Run: `uv run --extra dev python -m pytest tests/test_trace_writer.py tests/test_receipt_generator.py tests/test_published_agent_versions.py tests/test_knowledge_source_publication.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/observability/audit/trace.py proof_agent/observability/audit/receipt.py proof_agent/observability/audit/templates/governance_receipt.md.j2 proof_agent/observability/api/serializers.py proof_agent/delivery/configuration_api.py tests/test_trace_writer.py tests/test_receipt_generator.py tests/test_published_agent_versions.py tests/test_knowledge_source_publication.py
git commit -m "feat: audit hybrid knowledge execution"
```

### Phase D Completion Gate

- [ ] Publish a V3 Agent with one Hybrid binding and one pinned Retrieval Profile.
- [ ] Run clause lookup, conditional guidance, comparison, missing-condition clarification, rule conflict, and no-evidence scenarios.
- [ ] Prove unauthorized candidates are zero before reranking by inspecting the test-only internal recorder; prove production trace exposes counts only.
- [ ] Kill embedding and reranker services separately and verify only explicitly prevalidated modes continue.
- [ ] Force generation, manifest, attestation, and citation failures and verify no recommendation and no TreeIndex fallback.
- [ ] Agent Version Rollback restores the previous binding; Source rollback creates a new monotonic Source publication.

## Phase E — Evaluation, Operations, And Shadow Cutover

### Task 22: Add Parser And Insurance Knowledge Evaluation Contracts

**Files:**

- Modify: `proof_agent/contracts/evaluation.py`
- Create: `proof_agent/evaluation/knowledge_cases.py`
- Create: `proof_agent/evaluation/knowledge_metrics.py`
- Create: `proof_agent/evaluation/parser_benchmark.py`
- Create: `proof_agent/evaluation/suites/insurance_knowledge_tuning.sample.yaml`
- Create: `tests/test_insurance_knowledge_evaluation.py`
- Create: `tests/test_parser_benchmark.py`

- [ ] **Step 1: Write failing schema and metric tests**

```python
def test_comparison_case_requires_complete_gold_evidence_slots() -> None:
    with pytest.raises(ValidationError):
        InsuranceKnowledgeCase(query_type="comparison", required_evidence_slots=())


def test_required_evidence_recall_at_50() -> None:
    metrics = retrieval_metrics(gold=("u1", "u2"), ranked=("u1", *noise(49), "u2"))
    assert metrics.required_evidence_recall_at_50 == 0.5
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_insurance_knowledge_evaluation.py tests/test_parser_benchmark.py -q`

Expected: FAIL because Knowledge-specific cases and metrics are absent.

- [ ] **Step 3: Implement query and parser case contracts**

[FRAME | HIGH] Query cases label 30/50/20 type, exact Source/publication, required Rule Unit revisions, evidence slots, authority expectations, conditions, clarification/conflict/refusal, and ACL hard negatives. Parser cases label reading order, table cells, cross-page continuation, OCR text, citation anchors, and mandatory-review expectation.

- [ ] **Step 4: Implement sliced metrics and hard-gate facts**

[FRAME | HIGH] Compute Recall@20/50/100, complete-evidence Top-5/10, nDCG@10, MRR@10, citation resolvability, authority failures, ACL candidate exposure, parser character/table/anchor metrics, and review-required recall by query/document/parser/ACL slice.

- [ ] **Step 5: Run tests and commit**

Run: `uv run --extra dev python -m pytest tests/test_insurance_knowledge_evaluation.py tests/test_parser_benchmark.py -q`

Expected: PASS.

```bash
git add proof_agent/contracts/evaluation.py proof_agent/evaluation/knowledge_cases.py proof_agent/evaluation/knowledge_metrics.py proof_agent/evaluation/parser_benchmark.py proof_agent/evaluation/suites/insurance_knowledge_tuning.sample.yaml tests/test_insurance_knowledge_evaluation.py tests/test_parser_benchmark.py
git commit -m "feat: evaluate insurance knowledge retrieval"
```

### Task 23: Add Sealed Acceptance And Non-Compensating Release Gates

**Files:**

- Create: `proof_agent/evaluation/sealed_knowledge_acceptance.py`
- Create: `proof_agent/evaluation/knowledge_gates.py`
- Modify: `proof_agent/evaluation/gate_profiles.py`
- Modify: `proof_agent/evaluation/gates.py`
- Modify: `proof_agent/evaluation/suites.py`
- Modify: `proof_agent/delivery/cli.py`
- Create: `tests/test_sealed_knowledge_acceptance.py`
- Modify: `tests/test_evaluation_gates.py`

- [ ] **Step 1: Write failing one-attempt and aggregate-only tests**

```python
def test_sealed_evaluator_rejects_second_attempt_for_same_candidate() -> None:
    evaluator = SealedKnowledgeAcceptanceStore()
    evaluator.run(candidate_digest="candidate-1", sealed_suite_ref=sealed_ref())
    with pytest.raises(EvaluationInputError, match="one acceptance attempt"):
        evaluator.run(candidate_digest="candidate-1", sealed_suite_ref=sealed_ref())


def test_sealed_result_contains_no_case_level_feedback() -> None:
    result = evaluator.run(candidate_digest="candidate-2", sealed_suite_ref=sealed_ref())
    assert not hasattr(result, "case_results")
    assert result.hard_gate_failures >= 0
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_sealed_knowledge_acceptance.py tests/test_evaluation_gates.py -q`

Expected: FAIL because sealed evaluation is absent.

- [ ] **Step 3: Implement the aggregate release authority**

[FRAME | HIGH] The sealed suite is an exact external artifact reference readable only by the evaluator service identity. The normal report receives aggregate/slice metrics and hard-gate counts, never questions, labels, evidence ids, or case failures. Revealed failures must be retired and replaced outside this command.

- [ ] **Step 4: Implement hard gates before quality thresholds**

```python
HARD_ZERO_FIELDS = (
    "unauthorized_candidate_exposure",
    "wrong_version_or_precedence",
    "unresolvable_formal_citation",
    "advice_under_authority_uncertainty",
    "high_severity_unsupported_claim",
)
```

[FRAME | HIGH] Any nonzero value blocks release before Recall, quality, or latency is evaluated. Then require overall Recall@50 ≥ 0.95, each query slice ≥ 0.90, conditional/comparison complete Top-10 ≥ 0.90, and performance gates from the pinned profile.

- [ ] **Step 5: Add `proof-agent evaluate knowledge-acceptance` and run tests**

Run: `uv run --extra dev python -m pytest tests/test_sealed_knowledge_acceptance.py tests/test_evaluation_gates.py tests/test_evaluation_cli.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/evaluation/sealed_knowledge_acceptance.py proof_agent/evaluation/knowledge_gates.py proof_agent/evaluation/gate_profiles.py proof_agent/evaluation/gates.py proof_agent/evaluation/suites.py proof_agent/delivery/cli.py tests/test_sealed_knowledge_acceptance.py tests/test_evaluation_gates.py tests/test_evaluation_cli.py
git commit -m "feat: gate hybrid knowledge releases"
```

### Task 24: Add Knowledge Operations API And Dashboard

**Files:**

- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/api/client.ts`
- Create: `dashboard/src/components/knowledge/KnowledgeOperationsPanel.tsx`
- Create: `dashboard/src/components/knowledge/__tests__/KnowledgeOperationsPanel.test.tsx`
- Modify: `dashboard/src/pages/KnowledgeDetailPage.tsx`
- Create: `tests/test_hybrid_knowledge_operations.py`

- [ ] **Step 1: Write failing backend aggregation tests**

```python
def test_operations_projection_is_trace_safe_and_includes_queue_time() -> None:
    projection = build_operations_projection(fake_health_sources())
    assert projection.retrieval_p95_ms >= projection.scheduler_queue_p95_ms
    assert projection.unauthorized_candidate_exposure == 0
    assert not hasattr(projection, "raw_rule_content")
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_knowledge_operations.py -q`

Expected: FAIL because the operations projection is absent.

- [ ] **Step 3: Implement read-only operations endpoint**

[FRAME | HIGH] Expose queue age, retry/review backlog, parser escalation, throughput, GPU queue/utilization summary, embedding backlog, index lag, orphan count, publication age, rebuild state, stage latency, no-evidence/clarification/conflict/refusal/degradation rates, citation failures, slot coverage, and zero-tolerance security counters. Return safe counts and identifiers only.

- [ ] **Step 4: Write and implement the Dashboard panel test**

```tsx
it('shows release blockers before throughput diagnostics', async () => {
  render(<KnowledgeOperationsPanel sourceId="ks_1" />)
  expect(await screen.findByText('Release blockers')).toBeVisible()
  expect(screen.getByText('Unauthorized candidates: 0')).toBeVisible()
  expect(screen.getByText('Review backlog: 12')).toBeVisible()
})
```

Run: `npm test --workspace dashboard -- KnowledgeOperationsPanel.test.tsx KnowledgeDetailPage.test.tsx`

Expected: PASS.

- [ ] **Step 5: Run backend tests and commit**

Run: `uv run --extra dev python -m pytest tests/test_hybrid_knowledge_operations.py tests/test_agent_configuration_api.py -q`

Expected: PASS.

```bash
git add proof_agent/delivery/configuration_api.py dashboard/src/api/types.ts dashboard/src/api/client.ts dashboard/src/components/knowledge/KnowledgeOperationsPanel.tsx dashboard/src/components/knowledge/__tests__/KnowledgeOperationsPanel.test.tsx dashboard/src/pages/KnowledgeDetailPage.tsx tests/test_hybrid_knowledge_operations.py
git commit -m "feat: expose hybrid knowledge operations"
```

### Task 25: Run Shadow Migration, Capacity Envelope, And Cutover Verification

**Files:**

- Create: `proof_agent/evaluation/knowledge_shadow.py`
- Create: `proof_agent/evaluation/knowledge_capacity.py`
- Create: `proof_agent/evaluation/knowledge_recovery.py`
- Create: `proof_agent/evaluation/suites/insurance_knowledge_capacity.sample.yaml`
- Create: `tests/test_knowledge_shadow_cutover.py`
- Create: `tests/test_knowledge_capacity.py`
- Create: `tests/test_knowledge_recovery_drill.py`
- Create: `tests/integration/test_hybrid_capacity_envelope.py`
- Create: `tests/integration/test_hybrid_recovery_drill.py`
- Modify: `proof_agent/delivery/cli.py`
- Modify: `docs/technical-design.md`
- Modify: `docs/developer-guide.md`
- Modify: `docs/evaluation-system.md`
- Modify: `docs/development-progress.md`
- Modify: `.env.example`

- [ ] **Step 1: Write failing shadow-comparison and rollback tests**

```python
def test_shadow_run_never_changes_active_agent_or_source() -> None:
    before = active_versions()
    run_shadow_comparison(legacy_binding(), hybrid_candidate_binding())
    assert active_versions() == before


def test_cutover_rollback_selects_prior_agent_version() -> None:
    cutover_to(hybrid_agent_version())
    rollback_agent_version(legacy_agent_version())
    assert active_agent_version() == legacy_agent_version()


def test_capacity_report_requires_five_active_runs_and_ingestion_sample() -> None:
    with pytest.raises(ValueError, match="five active runs"):
        seal_capacity_report(measurements=measurements(active_runs=4, ingestion_samples=1))


def test_recovery_drill_fails_when_rebuilt_manifest_differs() -> None:
    result = run_recovery_drill(fault="drop_generation_index", rebuilt_root="wrong")
    assert result.passed is False
    assert result.failed_gate == "manifest_root_reproduction"
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run --extra dev python -m pytest tests/test_knowledge_shadow_cutover.py tests/test_knowledge_capacity.py tests/test_knowledge_recovery_drill.py -q`

Expected: FAIL because shadow orchestration is absent.

- [ ] **Step 3: Implement non-mutating shadow comparison**

[FRAME | HIGH] Replay authorized questions against pinned legacy and Hybrid bindings, store only safe evidence identities, metrics, citations, outcomes, and latency, and never update Source or Agent active pointers. Add `proof-agent evaluate knowledge-shadow`.

- [ ] **Step 4: Implement and freeze the measured workload envelope**

[FRAME | HIGH] `KnowledgeCapacityEnvelope` is a frozen, digest-bearing evaluation artifact that records corpus/suite digest, changed documents/pages, Docling/Paddle mix, table density, model/profile revisions, hardware, online concurrency, reviewer availability, target Agent count, warmup/sample counts, hybrid retrieval P50/P95/P99, scheduler queue P95, full-run P95, ingestion throughput, retrieval P95 with and without ingestion, interference percentage, and approved-file-to-Active-Agent-Version duration. It refuses sealing unless there are exactly the required five simultaneous authorized runs, both idle and active-ingestion samples, and all raw measurement references. The one-to-four-hour SLO applies only to a passing sealed envelope.

[FRAME | HIGH] Implement `proof-agent evaluate knowledge-capacity --suite ... --output ...` to launch five bounded concurrent run workers plus a controlled offline ingestion workload through the same scheduler. Use a monotonic clock, fixed warmup/sample counts from the suite, separate queue/service timers, and exit non-zero when any threshold fails. The committed sample suite contains structure and placeholder fixture ids only; environment-specific thresholds and hardware labels are supplied by an approved sealed suite, not guessed in code.

Run: `uv run --extra dev python -m pytest tests/test_knowledge_capacity.py -q`

Expected: PASS for measurement validation, interference calculation, digest stability, and hard-gate exit status.

- [ ] **Step 5: Implement an executable recovery drill**

[FRAME | HIGH] `proof-agent evaluate knowledge-recovery --source-id ... --generation-id ... --output ...` snapshots active Source/Agent pointers, injects one test-scoped fault at a time, invokes Task 16 reconciliation/rebuild and Task 21 rollback APIs, and writes a signed/digest-bearing drill artifact. Supported integration-only faults are: fail after OpenSearch refresh, delete a disposable generation index, corrupt a copied test-prefix artifact, and cut over then roll back the Agent Version. The harness must prove prior publication visibility during failure, exact manifest/attestation reproduction after rebuild, cleanup idempotence, and unchanged production-style pointers until explicit cutover. Fault injection is rejected unless the repository and bucket carry the disposable-test marker.

Run: `uv run --extra dev python -m pytest tests/test_knowledge_recovery_drill.py -q`

Expected: PASS for safety guard, fault orchestration, evidence artifact, and failed-gate reporting.

- [ ] **Step 6: Execute staged verification with runnable commands**

1. [FRAME | HIGH] Start disposable dependencies: `docker compose -f docker-compose.hybrid-test.yml up -d --wait postgres minio minio-init opensearch`.
2. [FRAME | HIGH] Run parser and authorized retrieval shadow: `uv run --extra dev --extra hybrid --extra production proof-agent evaluate knowledge-shadow --suite var/knowledge-eval/approved-shadow-suite.yaml --output var/knowledge-eval/shadow-result.json`.
3. [FRAME | HIGH] Run the five-active-run and ingestion-interference harness: `uv run --extra dev --extra hybrid --extra production proof-agent evaluate knowledge-capacity --suite var/knowledge-eval/approved-capacity-suite.yaml --output var/knowledge-eval/capacity-result.json`.
4. [FRAME | HIGH] Run sealed acceptance: `uv run --extra dev --extra hybrid --extra production proof-agent evaluate knowledge-acceptance --suite var/knowledge-eval/sealed-acceptance-suite.yaml --output var/knowledge-eval/acceptance-result.json`.
5. [FRAME | HIGH] Run rebuild and rollback recovery: `uv run --extra dev --extra hybrid --extra production proof-agent evaluate knowledge-recovery --source-id "$HYBRID_TEST_SOURCE_ID" --generation-id "$HYBRID_TEST_GENERATION_ID" --output var/knowledge-eval/recovery-result.json`.
6. [FRAME | HIGH] Execute the assisted pilot on the named institution-specialist Agent, retain the prior Agent Version, publish the new Agent Version only after all four artifact digests are recorded in the release record, then invoke the existing Agent rollback API during the scheduled rollback drill.

Run: `HYBRID_TEST_POSTGRES_DSN=postgresql://proof:proof@127.0.0.1:55432/proof HYBRID_TEST_S3_ENDPOINT=http://127.0.0.1:59000 HYBRID_TEST_S3_BUCKET=proof-agent-test HYBRID_TEST_S3_ACCESS_KEY=proof HYBRID_TEST_S3_SECRET_KEY=proof-secret uv run --extra dev --extra hybrid --extra production python -m pytest -m hybrid_integration tests/integration/test_hybrid_capacity_envelope.py tests/integration/test_hybrid_recovery_drill.py -q`

Expected: PASS and emit sealed capacity/recovery artifacts with five active run ids, both interference baselines, exact rebuilt root/coverage, and rollback pointer evidence.

- [ ] **Step 7: Update English documentation**

[FRAME | HIGH] Document Hybrid Source creation, private service conformance, workbook curation, review/readiness, generation/profile rules, publication, Agent upgrade, runtime refusal/degradation, operations, evaluation, shadow, rollback, and rebuild. Do not update `docs/zh/` until release sync.

- [ ] **Step 8: Run full verification**

```bash
uv run --extra dev --extra openai --extra ingestion --extra tree --extra hybrid --extra production python -m pytest tests/ -q
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai mypy proof_agent
npm test
npm run build --workspace dashboard
uv run --extra dev proof-agent demo
python3 scripts/check-domain-contexts.py
git diff --check
```

Expected: all commands pass; deterministic demo outcomes remain unchanged.

- [ ] **Step 9: Commit**

```bash
git add proof_agent/evaluation/knowledge_shadow.py proof_agent/evaluation/knowledge_capacity.py proof_agent/evaluation/knowledge_recovery.py proof_agent/evaluation/suites/insurance_knowledge_capacity.sample.yaml proof_agent/delivery/cli.py tests/test_knowledge_shadow_cutover.py tests/test_knowledge_capacity.py tests/test_knowledge_recovery_drill.py tests/integration/test_hybrid_capacity_envelope.py tests/integration/test_hybrid_recovery_drill.py docs/technical-design.md docs/developer-guide.md docs/evaluation-system.md docs/development-progress.md .env.example
git commit -m "docs: complete hybrid knowledge rollout"
```

## Phase F — Production Release-Authority Closure

### Task 26: Replace precomputed Shadow and Acceptance inputs with live trusted execution

- [x] [COMPUTED | HIGH] `insurance-knowledge-shadow.v2` contains only question and pinned binding references; the core reads pointers and executes both bindings through a trusted driver.
- [x] [COMPUTED | HIGH] Sealed Acceptance input contains no aggregate. A private evaluator driver returns a canonical attestation and a separately resolved verifier checks identity, key, digest, and detached signature.
- [x] [COMPUTED | HIGH] Capacity, Recovery, Shadow, Acceptance, and Operations all have registered `private-http` entry points using the pinned private-network transport.

### Task 27: Make release evidence an Agent Publication authority

- [x] [COMPUTED | HIGH] Add `knowledge-release-record.v1` with exact Shadow, Capacity, Acceptance, and Recovery artifact references.
- [x] [COMPUTED | HIGH] Bind the record to the exact Contract Bundle and Resolved Knowledge Binding Set and reject altered, stale, missing, unknown, or duplicate-digest records.
- [x] [COMPUTED | HIGH] Require an independently resolved Release Evidence Authority to approve the four exact artifacts before record registration.
- [x] [COMPUTED | HIGH] Block every Hybrid Agent publication without a matching registered record and freeze the record into the Published Agent Version.

### Task 28: Close telemetry and real-asset configuration gaps

- [x] [COMPUTED | HIGH] Compose a production Knowledge Operations provider at API startup and close its resources with the application.
- [x] [COMPUTED | HIGH] Add `insurance-knowledge-assets.v1` for immutable external cohorts, exact 300/200 split, both 30/50/20 mixes, sealed custody, and a distinct 100-to-200 parser benchmark.
- [x] [COMPUTED | HIGH] Add environment configuration, architecture documentation, ADR, domain terms, and regression tests.
- [x] [COMPUTED | HIGH] Full backend verification: 2662 passed, 1 skipped, 8 opt-in deselected; Ruff and mypy passed.

[INFERRED | HIGH] The remaining release-gate work is deployment/business execution, not missing framework mechanics: provision real human-confirmed cohorts and private endpoints, execute the four commands, conduct the assisted pilot and rollback drill, and record the resulting immutable evidence.

## Phase-Gate Command Matrix

| Gate | Required services | Required configuration/fixtures | Command | Evidence artifact |
|---|---|---|---|---|
| Phase A | [FRAME | HIGH] None | [FRAME | HIGH] Frozen contract fixtures and fake trusted headers | `uv run --extra dev python -m pytest tests/test_hybrid_document_contracts.py tests/test_insurance_rule_contracts.py tests/test_knowledge_index_contracts.py tests/test_insurance_authorization.py tests/test_knowledge_binding_resolver.py -q` | [FRAME | HIGH] Pytest result plus serialized contract snapshots |
| Phase B | [FRAME | HIGH] Fake guarded transports; optional approved private parser sandbox | [FRAME | HIGH] Sanitized PDF/vendor JSON/workbook fixtures and exact parser revisions | `uv run --extra dev --extra ingestion --extra hybrid python -m pytest tests/test_hybrid_intake.py tests/test_hybrid_parser_pipeline.py tests/test_hybrid_knowledge_worker.py tests/test_hybrid_rule_units.py tests/test_insurance_metadata_workbook.py -q` | [FRAME | HIGH] Structured-build digest, review/readiness report |
| Phase C | [FRAME | HIGH] Disposable OpenSearch, PostgreSQL, MinIO | [FRAME | HIGH] `HYBRID_TEST_*` values from Task 16; migration and test-only bucket marker | `uv run --extra dev --extra hybrid --extra production python -m pytest -m hybrid_integration tests/integration/test_hybrid_opensearch.py tests/integration/test_hybrid_postgres_s3.py tests/integration/test_hybrid_generation_rebuild.py -q` | [FRAME | HIGH] Publication, orphan-reconciliation, rebuild manifest/attestation results |
| Phase D | [FRAME | HIGH] Fake scheduled model/search services for default tests; private conformance environment for pre-cutover | [FRAME | HIGH] Pinned Agent/Source/Generation/Profile and authorized institution fixtures | `uv run --extra dev --extra hybrid python -m pytest tests/test_hybrid_request.py tests/test_hybrid_retrieval.py tests/test_insurance_authority_gate.py tests/test_hybrid_evidence_slots.py tests/test_insurance_answer_contract.py -q` | [FRAME | HIGH] Safe trace, Receipt, answer-validation and rollback results |
| Phase E | [FRAME | HIGH] Disposable authority/search stack plus approved private parser/model services | [FRAME | HIGH] Sealed shadow, acceptance, and capacity suites; named test Source/Generation | [FRAME | HIGH] Run the four `proof-agent evaluate knowledge-*` commands from Task 25 | [FRAME | HIGH] Shadow, acceptance, capacity, and recovery artifacts whose digests enter the release record |
| Phase F | [FRAME | HIGH] Approved private evaluation/operations service plus independent verifier trust | [FRAME | HIGH] Real external asset manifest, frozen candidate, four immutable passing artifacts | [FRAME | HIGH] Register the candidate-bound Knowledge Release Record and publish through Agent Configuration | [FRAME | HIGH] Published Agent Version containing the exact validated Knowledge Release Record |

## Final Release Gate

- [ ] [FRAME | HIGH] All hard-zero security, authority, citation, and unsupported-claim gates pass on one sealed candidate.
- [ ] [FRAME | HIGH] Required-evidence Recall@50 and complete-evidence Top-10 thresholds pass overall and per agreed query slice.
- [ ] [FRAME | HIGH] Parser acceptance slice has zero rule-bearing content/citation-anchor loss and zero missed mandatory-review cases.
- [ ] [FRAME | HIGH] Five-active-run retrieval P95, scheduler queue time, ingestion interference, and full-run P95 meet the approved envelope.
- [ ] [FRAME | HIGH] A routine change reaches the named Active Agent Version within one to four hours inside the frozen workload envelope.
- [ ] [FRAME | HIGH] OpenSearch generation rebuild from PostgreSQL plus S3 reproduces manifest roots and attestation coverage.
- [ ] [FRAME | HIGH] Agent Version Rollback and Source rollback Draft paths both pass without mutable-latest or TreeIndex fallback.
- [ ] [FRAME | HIGH] No production process downloads models or sends Knowledge-bearing content outside the Private Knowledge Processing Boundary.

## Implementation Handoff Notes

- [FRAME | HIGH] Use `superpowers:subagent-driven-development` for this plan unless the user selects inline execution.
- [FRAME | HIGH] Execute one task per commit and stop at every phase completion gate for review.
- [FRAME | HIGH] Do not start Phase C before Phase B review/readiness behavior is executable; do not start Phase D before publication atomicity and historical replay pass; do not cut over before Phase E sealed gates and recovery drills pass.
- [FRAME | HIGH] If the external private model service or generic production storage/egress foundations land in another repository first, preserve these ports and run their conformance tests rather than duplicating provider-specific SDK objects inside Proof Agent contracts or Control Plane code.
