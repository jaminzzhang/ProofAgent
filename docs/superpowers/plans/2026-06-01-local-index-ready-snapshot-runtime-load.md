# Local Index READY Snapshot Runtime Load Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the registered `local_index` provider load an immutable published READY snapshot at runtime without building indexes during an Agent run.

**Architecture:** Add a small snapshot metadata loader beside `LocalIndexProvider`. Wire `LocalIndexProvider.from_config()` through the existing model registry, resolve the source-owned routing model, validate `artifact_meta.json`, and call the existing read-only LlamaIndex load path.

**Tech Stack:** Python 3.12, Pydantic contracts, LlamaIndex TreeIndex, pytest, Ruff, mypy

---

### Task 1: READY Snapshot Metadata Loader

**Files:**
- Create: `proof_agent/capabilities/knowledge/local_index_snapshot.py`
- Test: `tests/test_local_index_snapshot.py`

- [x] Write failing tests for valid READY metadata and rejected missing, malformed, or non-READY metadata.
- [x] Run `uv run --extra dev --extra tree python -m pytest tests/test_local_index_snapshot.py -q`.
- [x] Implement the frozen metadata contract and loader with `PA_KNOWLEDGE_001` failures.
- [x] Re-run the focused test file.

### Task 2: Runtime Provider Resolution

**Files:**
- Modify: `proof_agent/capabilities/knowledge/local_index.py`
- Modify: `tests/test_local_index_provider.py`

- [x] Replace the placeholder `from_config()` expectation with failing tests for routing model resolution, ingestion-model inheritance, READY validation, and read-only load.
- [x] Run focused `LocalIndexProvider.from_config()` tests and confirm failure.
- [x] Make ingestion LLM optional, reject management-plane builds when absent, and implement `from_config()`.
- [x] Normalize LlamaIndex storage-load errors to `PA_KNOWLEDGE_002`.
- [x] Re-run local index tests.

### Task 3: Documentation And Verification

**Files:**
- Modify: `docs/developer-guide.md`
- Modify: `docs/development-progress.md`

- [x] Document the required `artifact_meta.json` READY sidecar and source-owned routing model.
- [x] Run `uv run --extra dev --extra dashboard --extra tree python -m pytest tests/ -q`.
- [x] Run `uv run --extra dev --extra tree ruff check proof_agent tests`.
- [x] Run `uv run --extra dev --extra dashboard --extra openai --extra tree mypy proof_agent`.
- [x] Run `git diff --check`.
