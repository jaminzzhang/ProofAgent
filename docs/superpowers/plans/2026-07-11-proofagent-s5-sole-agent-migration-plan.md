# Proof Agent S5 Sole Agent Production Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [FRAME | HIGH] Publish only `agent_management_insurance_specialist` as a production-valid Controlled ReAct V3 Agent with S3 Knowledge, PostgreSQL Case Memory, concrete model/Secret/egress bindings, and either one validated read-only HTTPS tool contract or an explicit disabled-tool capability.

**Architecture:** [FRAME | HIGH] Treat the Git example as a deterministic authoring/reference package and use an idempotent bootstrap service to create immutable PostgreSQL shared assets and the sole Published Agent Version. The published snapshot holds exact S3, model, Secret Handle, egress, tool, and evaluation-contract references consumed by S4’s Executor.

**Tech Stack:** [KNOWN | HIGH] Existing Controlled ReAct V3, PostgreSQL repositories, S3 Artifact Port/materialization, Production Secret Handles, guarded HTTPS, Pydantic v2, pytest, real model-provider integration tests.

---

## Prerequisites and Exit Contract

- [ ] [FRAME | HIGH] Begin only after S2, S3, and S4 are merged, reviewed, and green.
- [ ] [KNOWN | HIGH] Read the insurance-reference, business-flow-skills, agent-configuration, knowledge-evidence, tools-models-memory, workflow-control, evaluation, and observability contexts routed by `CONTEXT-MAP.md`.
- [ ] [FRAME | HIGH] Require a concrete production-equivalent model connection. A read-only HTTPS Tool Source is optional: bind it only when concrete and validated; otherwise set `tool_mode=disabled` and prove no tool can be selected. A local handler can never substitute.
- [ ] [FRAME | HIGH] Exit only when runtime/publication/discovery/evaluation expose one Agent ID and one V3 template, and the same immutable evaluation contract passes deterministically and is runnable against the candidate model.

## Task 1: Define the Initial Production Agent Deployment Contract

**Files:**

- Create: `proof_agent/contracts/initial_production.py`
- Modify: `proof_agent/contracts/agent_configuration.py`
- Modify: `proof_agent/contracts/manifest.py`
- Modify: `proof_agent/contracts/__init__.py`
- Create: `deploy/production/bootstrap/initial-agent.schema.json`
- Create: `deploy/production/bootstrap/initial-agent.example.json`
- Create: `tests/test_initial_production_agent_contract.py`

- [ ] [FRAME | HIGH] Write red tests rejecting any Agent ID other than `agent_management_insurance_specialist`, any template other than `react_enterprise_qa_v3`, mutable draft refs, package/local Knowledge in production, environment credentials, local/session/user/shared memory, missing active egress ref, local/stdio/approval/state-changing tools, and unbound evaluation contract.
- [ ] [FRAME | HIGH] Define a strict deployment input containing exact immutable refs rather than raw values:

```json
{
  "schema_version": "proofagent.initial-agent-deployment.v1",
  "agent_id": "agent_management_insurance_specialist",
  "agent_version": "content-digest-version",
  "workflow_template": "react_enterprise_qa_v3",
  "knowledge_snapshot_id": "immutable-snapshot-id",
  "model_connection_version_id": "immutable-model-version-id",
  "egress_policy_version_id": "immutable-egress-version-id",
  "tool_mode": "disabled",
  "tool_source_version_id": null,
  "case_memory_policy_id": "initial-case-memory-v1",
  "evaluation_contract_sha256": "64-lowercase-hex"
}
```

- [ ] [FRAME | HIGH] The checked-in example uses deterministic non-secret fixture IDs and is explicitly non-candidate. Candidate input is generated from already validated PostgreSQL versions and is itself digest-bound. `tool_mode` is `disabled` with a null source or `read_only_https` with one exact validated source; no third state is accepted.
- [ ] [FRAME | HIGH] Remove production fields `workflow.runtime`, checkpointer, `react.max_steps`, package path, `api_key_env`, `base_url_env`, raw tool handler, and local memory provider from the accepted production schema.
- [ ] [FRAME | HIGH] Commit with message `Define sole Agent deployment contract`.

## Task 2: Cut the Reference Package to Production-Compatible V3 Semantics

**Files:**

- Modify: `examples/agent_management_insurance_specialist/agent.yaml`
- Modify: `examples/agent_management_insurance_specialist/policy.yaml`
- Modify: `examples/agent_management_insurance_specialist/tools.yaml`
- Delete: `examples/agent_management_insurance_specialist/tools.py`
- Modify: `examples/agent_management_insurance_specialist/README.md`
- Modify: all files under `examples/agent_management_insurance_specialist/skills/` that reference local tools or approval context
- Create: `tests/test_agent_management_insurance_specialist_example.py`

- [ ] [FRAME | HIGH] Write red reference-package tests for V3-only, read-only effects, no handler/command/stdio/approval, Case Memory-only scope, governance/refusal policy, and seven Knowledge documents.
- [ ] [FRAME | HIGH] Keep the Git package runnable in deterministic development mode through explicit local adapters, but make it compile into the same provider-neutral Published Agent contract used in production.
- [ ] [FRAME | HIGH] Change tool definitions to shared Tool Source references; no Python module path or executable command remains.
- [ ] [FRAME | HIGH] Update Skill Packs so transactional insurance operations route to governed refusal/procedural explanation and all lookup proposals require the validated shared read-only Tool Source.
- [ ] [KNOWN | HIGH] Run the focused package/config/compiler tests and deterministic CLI scenario.
- [ ] [FRAME | HIGH] Commit with message `Migrate insurance specialist package to V3`.

## Task 3: Build an Idempotent Sole-Agent Bootstrap and Quarantine Service

**Files:**

- Create: `proof_agent/configuration/initial_production_agent.py`
- Modify: `proof_agent/delivery/published_agents.py`
- Modify: `proof_agent/delivery/cli.py`
- Modify: `proof_agent/observability/api/app.py`
- Create: `tests/test_initial_production_agent.py`

- [ ] [FRAME | HIGH] Write red tests for first publish, same-input idempotency, changed-input new version, nonsole active Agent rejection, legacy draft quarantine, immutable version refs, atomic audit, and rollback on partial failure.
- [ ] [FRAME | HIGH] Add `proof-agent initial-agent validate --configuration PATH` and `proof-agent initial-agent publish --configuration PATH`; publication uses one S1 configuration unit of work.
- [ ] [FRAME | HIGH] On initial production bootstrap, deactivate/quarantine legacy drafts and Published Agent Versions without converting them. Historical run/audit refs remain readable but cannot be selected for a new Run.
- [ ] [FRAME | HIGH] Make registry/directory/list endpoints return only the sole Published Agent in production; never accept a browser manifest path.
- [ ] [FRAME | HIGH] Commit with message `Publish and enforce the sole production Agent`.

## Task 4: Publish the Seven-Document S3 Knowledge Snapshot

**Files:**

- Create: `deploy/production/bootstrap/knowledge/agent-management-insurance-specialist.json`
- Modify: `proof_agent/configuration/initial_production_agent.py`
- Modify: `proof_agent/capabilities/knowledge/ingestion/worker.py`
- Modify: `proof_agent/bootstrap/knowledge_resolution.py`
- Create: `tests/test_initial_production_agent_knowledge.py`

- [ ] [FRAME | HIGH] Write red tests for exact source inventory, isolated build, manifest-last upload, all-member verification, immutable snapshot bind, failed build/upload no visibility, and Executor materialization.
- [ ] [FRAME | HIGH] Upload the seven Markdown documents under `examples/agent_management_insurance_specialist/knowledge/` as one versioned Knowledge Source revision, build its Local Index, finalize exact S3 members/manifest, and publish one immutable snapshot.
- [ ] [FRAME | HIGH] Bind production Agent Knowledge only by snapshot ID/digest. Package filesystem knowledge is a deterministic authoring input, not runtime authority.
- [ ] [FRAME | HIGH] Preserve source authority/routing metadata and citation anchors through ingestion; candidate tests must detect missing/changed required documents.
- [ ] [FRAME | HIGH] Commit with message `Publish sole Agent Knowledge from S3`.

## Task 5: Add PostgreSQL Case Memory to Operator Runs

**Files:**

- Create: `proof_agent/delivery/operator_case_memory.py`
- Modify: `proof_agent/control/memory/extractor.py`
- Modify: `proof_agent/control/memory/admission.py`
- Modify: `proof_agent/delivery/run_executor.py`
- Modify: `proof_agent/delivery/api.py`
- Create: `tests/test_operator_case_memory.py`

- [ ] [FRAME | HIGH] Write red tests for current-conversation/case scope, 30-day logical expiry, maximum bounded records, policy denylist, trace-safe fact/summary only, no user/shared scope, and no citation/evidence satisfaction.
- [ ] [FRAME | HIGH] Read only unexpired records linked to the current authenticated Operator Chat conversation/case and Agent. Treat memory as untrusted context, never as evidence.
- [ ] [FRAME | HIGH] Write memory only after a governed terminal result and policy admission; do not persist raw transcript, raw evidence, raw tool payload, customer/agent identity facts, policy/claim state, report values, tokens, or secrets.
- [ ] [FRAME | HIGH] Link expiry to S3/S1 retention jobs and audit only trace-safe promotion/rejection facts.
- [ ] [FRAME | HIGH] Commit with message `Add case-only PostgreSQL memory to operator Runs`.

## Task 6: Bind a Validated Read-Only HTTPS Tool or Prove Tools Disabled

**Files:**

- Create: `deploy/production/bootstrap/tools/agent-management-read-api.example.json`
- Modify: `proof_agent/configuration/initial_production_agent.py`
- Modify: `proof_agent/control/workflow/controlled_react/tool_proposal_scope.py`
- Create: `tests/test_initial_production_agent_tool.py`

- [ ] [FRAME | HIGH] If `tool_mode=read_only_https`, use the concrete Tool Source origin/contract supplied by the deployment compatibility input. If `tool_mode=disabled`, reject any source ref and make the runtime tool catalog empty. The checked-in example is non-candidate and contains no credential.
- [ ] [FRAME | HIGH] Write red tests for exact origin, Secret Handle refs, `effect: read`, schema bounds, validation digest, permission scope, timeouts, off-policy redirect/DNS, modified contract, and attempted state-changing operation.
- [ ] [FRAME | HIGH] Run `tool_source.validate` through guarded HTTPS and persist the immutable validation result before publication. Runtime must compare the frozen contract/validation/egress digests.
- [ ] [FRAME | HIGH] Always include state-change and local-fallback denial. In `read_only_https` mode also include one authorized agent-performance/activity read scenario and fail closed when the service is unavailable; in `disabled` mode include a mandatory no-tool-selected scenario rather than skipping the evaluation Gate.
- [ ] [FRAME | HIGH] Commit with message `Enforce sole Agent optional read-only tool mode`.

## Task 7: Freeze the Deterministic Evaluation Contract

**Files:**

- Create: `proof_agent/evaluation/suites/agent_management_insurance_specialist.yaml`
- Create: `proof_agent/evaluation/subjects/agent_management_insurance_specialist/`
- Modify: `proof_agent/evaluation/suites.py`
- Create: `tests/test_initial_production_agent_evaluation.py`

- [ ] [FRAME | HIGH] Create required case IDs with explicit expected gates and no optional skip:

```text
supported_claims_materials
unsupported_future_discount
clarification_missing_report_period
read_only_agent_performance_or_tools_disabled
deny_claim_state_change
provider_timeout_or_5xx
hard_plan_and_attempt_budget
case_memory_is_not_evidence
```

- [ ] [FRAME | HIGH] Freeze input, required Knowledge/config refs, conditional tool-mode expectation, expected outcome family, citation/evidence/tool/policy gates, timing bounds, and artifact sufficiency into a canonical evaluation contract with SHA-256. The profile selects the required branch from the bound Agent snapshot, not candidate-supplied Gate optionality.
- [ ] [FRAME | HIGH] Run every case through the same S4 queue/Executor/S3 finalization path, not a special evaluation execution path.
- [ ] [FRAME | HIGH] Require all deterministic cases and all required artifact/gate fields; zero required skips.
- [ ] [FRAME | HIGH] Commit with message `Add sole Agent deterministic release evaluation`.

## Task 8: Add Candidate Real-LLM Evaluation for the Same Contract

**Files:**

- Create: `tests/llm_regression/test_agent_management_insurance_specialist_real_llm.py`
- Delete or supersede: `tests/llm_regression/test_v3_intent_execution_real_llm.py`
- Create: `proof_agent/evaluation/real_llm_release.py`
- Create: `tests/test_real_llm_release_binding.py`

- [ ] [FRAME | HIGH] Write binding tests proving the runner requires exact candidate image/release ID, sole Agent Version, evaluation-contract digest, model connection version, Secret Handle refs, and production-equivalent dependency endpoints.
- [ ] [FRAME | HIGH] Execute the same required cases as Task 7 with real model calls, including provider failure and hard-budget behavior. Do not accept a stub, mock, stale result, or result from a different image/Agent/model.
- [ ] [FRAME | HIGH] Store trace-safe candidate-bound Evidence through S3 and return `error/not_run`, not `passed`, when credentials/dependencies are missing.
- [ ] [FRAME | HIGH] S7 owns final Gate production/freshness; S5 proves the suite is complete and runnable.
- [ ] [FRAME | HIGH] Commit with message `Add candidate-bound sole Agent real-LLM suite`.

## Task 9: Align Dashboard, Operator Chat, and Development Seed

**Files:**

- Modify: `dashboard/src/components/agent/CreateAgentWizard.tsx`
- Modify: `dashboard/src/pages/AgentsPage.tsx`
- Modify: `dashboard/src/pages/AgentDetailPage.tsx`
- Modify: related Dashboard tests and i18n
- Modify: `chat/src/modes/operator/OperatorChatPage.tsx`
- Modify: related Chat tests
- Modify: `proof_agent/delivery/cli.py`

- [ ] [FRAME | HIGH] Write frontend inventory tests first: one Agent card/selection, V3-only workflow, no customer link, no approval action, no browser manifest path, and Case Memory labeled non-evidence.
- [ ] [FRAME | HIGH] Make development seed/import use only the sole example. Production startup does not auto-import from the filesystem; it requires the validated bootstrap publication.
- [ ] [FRAME | HIGH] Show immutable Agent/Knowledge/model/tool/egress/evaluation snapshot refs on the detail surface under their named view permissions.
- [ ] [FRAME | HIGH] Commit with message `Expose only the sole production Agent`.

## Task 10: S5 Full Verification and Review

- [ ] [KNOWN | HIGH] Run:

```bash
uv run --extra dev --extra postgres --extra s3 --extra security python -m pytest \
  tests/test_initial_production_agent_contract.py \
  tests/test_agent_management_insurance_specialist_example.py \
  tests/test_initial_production_agent.py \
  tests/test_initial_production_agent_knowledge.py \
  tests/test_operator_case_memory.py \
  tests/test_initial_production_agent_tool.py \
  tests/test_initial_production_agent_evaluation.py \
  tests/test_real_llm_release_binding.py -v
PROOF_AGENT_RUN_LLM_REGRESSION=1 \
  uv run --extra dev --extra openai --extra postgres --extra s3 --extra security \
  python -m pytest tests/llm_regression/test_agent_management_insurance_specialist_real_llm.py -v
npm run test -w proof-agent-dashboard
npm run test -w proof-agent-chat
npm run build
uv run --extra dev python -m pytest tests/ -v
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai --extra postgres --extra s3 --extra security mypy proof_agent
python3 scripts/check-domain-contexts.py
git diff --check
```

- [ ] [FRAME | HIGH] Independently review sole-inventory enforcement, V3 snapshot completeness, S3 Knowledge authority, Case Memory non-evidence/expiry, real HTTPS tool semantics, deterministic/real-LLM parity, and legacy-data quarantine.
- [ ] [FRAME | HIGH] Resolve all P0/P1 findings, record the S5 commit in the master plan, and only then start production packaging/deployment.
