# Single Public Example Design

## Goal

Reduce the repository from four public Agent example packages to one canonical example:

```text
examples/insurance_customer_service/
```

The remaining example must be the only user-facing Agent package under `examples/`.

## Scope

Delete these public example packages:

```text
examples/enterprise_qa/
examples/react_enterprise_qa/
examples/insurance_service_qa/
```

Keep `examples/insurance_customer_service/` as the canonical runnable package. Add a concise package README if needed so developers can understand and run it without consulting removed examples.

Preserve the framework-owned `enterprise_qa` and `react_enterprise_qa` workflow templates. They are supported Control Envelope execution shapes, not public example packages.

## Fixture Boundary

The existing CLI demos and regression tests use the old Enterprise QA packages for intentionally narrow workflow behavior:

- evidence-backed answer with citations
- insufficient-evidence refusal
- approval wait for a governed mock tool
- Controlled ReAct clarification and review trace
- optional remote model configuration validation

Move the minimum required baseline Agent packages into non-public fixture directories:

```text
proof_agent/evaluation/demo/fixtures/
tests/fixtures/
```

The CLI-owned deterministic packages belong under `proof_agent/evaluation/demo/fixtures/`. Tests should use those CLI fixtures when they verify the same behavior, or use `tests/fixtures/` when a test-only variant is needed.

Remove `examples/demo_tools.py` after its handler has moved beside the CLI fixture. The `examples` Python package may remain because the insurance customer-service adapter and read handlers are imported by tests.

## Public Entry Points

Update public-facing defaults and documentation so they point only to:

```text
examples/insurance_customer_service/agent.yaml
```

This includes:

- root `README.md`
- `AGENTS-COMMON.md`
- English documentation index and guides
- Dashboard Agent creation defaults and visible templates
- CLI `doctor`

`proof-agent demo` and `proof-agent react-demo` remain regression commands backed by internal fixtures. Documentation should describe them as deterministic framework regression demos rather than additional user-copyable Agent packages.

The `compare` command may continue to compare Plain RAG with the internal Harness RAG baseline because it is an evaluation helper, not a public Agent package selector.

## Documentation Policy

Update active English documentation only. Do not rewrite historical specs or plans under `docs/superpowers/`, and do not synchronize `docs/zh/` during development.

Remove active English example pages that describe deleted packages:

```text
docs/examples/enterprise-qa.md
docs/examples/react-enterprise-qa.md
docs/examples/insurance-service-qa.md
```

Update remaining active pages to avoid presenting deleted packages as runnable examples. Keep concept-level references to workflow template names where they describe supported framework contracts.

## Test Strategy

Update tests that currently load deleted public packages:

- workflow, policy, tool, provider, CLI, API, import, and storage tests use fixture paths
- customer-service tests continue to use `examples/insurance_customer_service/`
- the deleted `insurance_service_qa` example test is removed or rewritten against the canonical customer-service example
- frontend tests and defaults no longer advertise deleted manifests

Run:

```bash
git diff --check
uv run --extra dev ruff check proof_agent tests
uv run --extra dev mypy proof_agent
uv run --extra dashboard --extra dev python -m pytest tests/ -v
cd dashboard && npm test && npm run build
cd chat && npm test && npm run build
```

Also verify:

```bash
find examples -mindepth 1 -maxdepth 1 -type d ! -name '__pycache__'
rg "examples/(enterprise_qa|react_enterprise_qa|insurance_service_qa)" \
  --glob '!docs/superpowers/**' --glob '!docs/zh/**'
```

The first command must list only `examples/insurance_customer_service`. The second must return no active references.
