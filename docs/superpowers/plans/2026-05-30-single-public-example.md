# Single Public Example Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep `examples/insurance_customer_service/` as the repository's only public Agent example while preserving deterministic framework regression coverage in internal fixtures.

**Architecture:** Public copyable packages live under `examples/`; CLI-owned regression packages live under `proof_agent/evaluation/demo/fixtures/`. Workflow template names remain framework contracts. Tests use internal fixtures for generic Harness coverage and the canonical insurance customer-service package for product-facing coverage.

**Tech Stack:** Python 3.12, Typer, pytest, React 19, TypeScript, Vite, Markdown

---

## File Map

- Create `proof_agent/evaluation/demo/fixtures/__init__.py` to mark internal demo fixtures as a package.
- Move the old `examples/enterprise_qa/` and `examples/react_enterprise_qa/` packages into `proof_agent/evaluation/demo/fixtures/`.
- Move `examples/demo_tools.py` into `proof_agent/evaluation/demo/fixtures/demo_tools.py`.
- Modify `proof_agent/delivery/cli.py` and `proof_agent/evaluation/compare/harness_rag.py` to use internal fixtures and the canonical public package appropriately.
- Create `tests/test_example_layout.py` to enforce the single-public-example rule.
- Modify tests that load the removed public packages so generic Harness tests use internal fixtures.
- Delete `tests/test_insurance_service_qa_example.py`; customer-service example coverage remains in `tests/test_insurance_customer_service_example.py` and the journey suite.
- Modify Dashboard defaults so they advertise only `insurance_customer_service`.
- Modify active English documentation and delete active pages for removed examples.

### Task 1: Enforce One Public Example

**Files:**
- Create: `tests/test_example_layout.py`

- [ ] **Step 1: Write the failing repository-layout test**

```python
from pathlib import Path


def test_only_insurance_customer_service_is_public_example() -> None:
    public_examples = sorted(
        path.name
        for path in Path("examples").iterdir()
        if path.is_dir() and not path.name.startswith("__")
    )

    assert public_examples == ["insurance_customer_service"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run --extra dev python -m pytest tests/test_example_layout.py -v
```

Expected: FAIL because three legacy public example directories still exist.

### Task 2: Move Generic Regression Packages Behind The Public Boundary

**Files:**
- Create: `proof_agent/evaluation/demo/fixtures/__init__.py`
- Move: `examples/enterprise_qa/` to `proof_agent/evaluation/demo/fixtures/enterprise_qa/`
- Move: `examples/react_enterprise_qa/` to `proof_agent/evaluation/demo/fixtures/react_enterprise_qa/`
- Move: `examples/demo_tools.py` to `proof_agent/evaluation/demo/fixtures/demo_tools.py`
- Modify: `proof_agent/evaluation/demo/fixtures/enterprise_qa/tools.yaml`
- Modify: `proof_agent/evaluation/demo/fixtures/react_enterprise_qa/tools.yaml`
- Modify: `proof_agent/delivery/cli.py`
- Modify: `proof_agent/evaluation/compare/harness_rag.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_compare.py`

- [ ] **Step 1: Move the two generic packages and tool handler**

Keep the Agent Contract contents stable. Update both internal `tools.yaml` files so the mock stdio command uses:

```yaml
args:
  - -m
  - proof_agent.evaluation.demo.fixtures.demo_tools
```

- [ ] **Step 2: Point CLI regression commands at internal fixtures**

Use constants in `proof_agent/delivery/cli.py`:

```python
DEMO_AGENT_PATH = Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml")
REACT_DEMO_AGENT_PATH = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml")
PUBLIC_EXAMPLE_PATH = Path("examples/insurance_customer_service/agent.yaml")
```

`demo` and `react-demo` use the internal fixture constants. `doctor` checks `PUBLIC_EXAMPLE_PATH` and its sibling `knowledge/`.

- [ ] **Step 3: Make `compare` execute the supplied manifest**

Pass `Path(agent_yaml)` into `run_harness_rag`:

```python
harness = run_harness_rag(question, agent_yaml=Path(agent_yaml))
```

Keep the internal Enterprise QA fixture as the Python helper's default for regression tests.

- [ ] **Step 4: Add a CLI compare regression test**

Patch `run_harness_rag`, invoke `proof-agent compare custom/agent.yaml --question sample`, and assert the patched call receives `Path("custom/agent.yaml")`.

- [ ] **Step 5: Run targeted tests**

```bash
uv run --extra dev python -m pytest tests/test_cli.py tests/test_compare.py tests/test_example_layout.py -v
```

Expected: layout test still fails until the insurance staff example is removed; CLI and compare tests pass.

### Task 3: Retarget Generic Harness Tests

**Files:**
- Modify: tests that reference `examples/enterprise_qa/` or `examples/react_enterprise_qa/`
- Delete: `tests/test_insurance_service_qa_example.py`

- [ ] **Step 1: Replace generic package paths**

Replace:

```text
examples/enterprise_qa/
```

with:

```text
proof_agent/evaluation/demo/fixtures/enterprise_qa/
```

Replace:

```text
examples/react_enterprise_qa/
```

with:

```text
proof_agent/evaluation/demo/fixtures/react_enterprise_qa/
```

Do not change string literals used only as synthetic API metadata unless they claim to reference a real package.

- [ ] **Step 2: Delete the removed staff-example test**

Remove `tests/test_insurance_service_qa_example.py`. The retained package is covered by:

```text
tests/test_insurance_customer_service_example.py
tests/test_customer_journeys.py
tests/test_customer_run_api.py
```

- [ ] **Step 3: Remove the staff example package**

Delete:

```text
examples/insurance_service_qa/
```

- [ ] **Step 4: Run Python tests**

```bash
uv run --extra dashboard --extra dev python -m pytest tests/ -v
```

Expected: PASS.

### Task 4: Reduce Dashboard Defaults To The Canonical Example

**Files:**
- Modify: `dashboard/src/components/agent/CreateAgentWizard.tsx`
- Modify: `dashboard/src/pages/AgentsPage.tsx`
- Modify: Dashboard tests containing removed example manifest paths

- [ ] **Step 1: Keep one visible wizard template**

Reduce `TEMPLATES` to:

```ts
const TEMPLATES: readonly Template[] = [
  { id: 'insurance_customer_service', name: 'Insurance Customer Service', purpose: 'Provide read-only customer service for insurance policy and claim questions.', manifestPath: 'examples/insurance_customer_service/agent.yaml', description: 'Customer-facing insurance Q&A with account-scoped evidence.' },
]
```

- [ ] **Step 2: Update the Agents page import default**

Set:

```ts
useState('examples/insurance_customer_service/agent.yaml')
```

- [ ] **Step 3: Update frontend tests and verify Dashboard**

```bash
cd dashboard
npm test
npm run build
```

Expected: PASS.

### Task 5: Update Active English Documentation

**Files:**
- Modify: `AGENTS-COMMON.md`
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `docs/developer-guide.md`
- Modify: `docs/technical-design.md`
- Modify: `docs/prd.md`
- Modify: `docs/feasibility-analysis.md`
- Modify: `docs/examples/launch-script.md`
- Modify: `docs/examples/insurance-customer-service.md`
- Create: `examples/insurance_customer_service/README.md`
- Delete: `docs/examples/enterprise-qa.md`
- Delete: `docs/examples/react-enterprise-qa.md`
- Delete: `docs/examples/insurance-service-qa.md`

- [ ] **Step 1: Describe one public example**

Update active docs so `examples/insurance_customer_service/` is the only copyable Agent package. Keep template names such as `enterprise_qa` and `react_enterprise_qa` where docs explain framework contracts.

- [ ] **Step 2: Document internal demo commands accurately**

Keep:

```bash
uv run --extra dev proof-agent demo
uv run --extra dev --extra dashboard proof-agent react-demo
```

Describe these as framework regression demos backed by internal fixtures. Use the public insurance package for copy, import, and direct-run examples:

```bash
uv run --extra dev proof-agent run examples/insurance_customer_service/agent.yaml \
  --question "What documents are required for inpatient claim reimbursement?"
```

- [ ] **Step 3: Remove stale active pages and references**

Delete the three pages for removed packages. Do not edit `docs/zh/` or historical `docs/superpowers/` documents.

### Task 6: Verify The Cleanup

**Files:**
- Modify only files required by failures found during verification.

- [ ] **Step 1: Check layout and stale active references**

```bash
find examples -mindepth 1 -maxdepth 1 -type d ! -name '__pycache__'
rg "examples/(enterprise_qa|react_enterprise_qa|insurance_service_qa)" \
  --glob '!docs/superpowers/**' --glob '!docs/zh/**'
```

Expected: only `examples/insurance_customer_service` is listed; `rg` returns no active matches.

- [ ] **Step 2: Run Python static checks**

```bash
git diff --check
uv run --extra dev ruff check proof_agent tests
uv run --extra dev mypy proof_agent
```

Expected: PASS.

- [ ] **Step 3: Run Python and frontend verification**

```bash
uv run --extra dashboard --extra dev python -m pytest tests/ -v
cd dashboard && npm test && npm run build
cd chat && npm test && npm run build
```

Expected: PASS.

- [ ] **Step 4: Run smoke paths**

```bash
uv run --extra dev proof-agent demo
uv run --extra dev --extra dashboard proof-agent react-demo
uv run --extra dev proof-agent run examples/insurance_customer_service/agent.yaml \
  --question "What documents are required for inpatient claim reimbursement?"
uv run --extra dev proof-agent compare examples/insurance_customer_service/agent.yaml \
  --question "What discount should we give this customer next year?"
uv run --extra dev proof-agent doctor
```

Expected: deterministic commands run without external credentials; `doctor` reports the canonical example and sample knowledge as available.
