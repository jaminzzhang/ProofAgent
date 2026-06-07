# Proof Agent PRD

## 1. Product Positioning

Proof Agent is a **Controlled Agent Harness Framework**: using Harness Engineering to manage the Agent lifecycle, placing LLMs, tools, knowledge, memory, and runtime into an orchestratable, approvable, verifiable, and auditable Control Envelope.

Core product judgments:
- **Harness is the main product**: Workflow, PolicyEngine, Tool Gateway, Validators, Memory Boundary, Trace, and Governance Receipt are first-class capabilities.
- **Models and runtimes are adapters**: Remote models, LangChain/LangGraph, vector stores, real MCPs, and Dashboards plug into the Harness, rather than replacing it.
- **Deterministic demo is a regression baseline, not the product boundary**: The project is no longer defined as local-first; the local deterministic path is used to prove the governance chain and guarantee testing.
- **CLI and Docker are the current deployment entry points**: The project is no longer defined as CLI-first; CLI, Docker, and Dashboard APIs are all entry points or observation planes for the controlled Harness.

The long-term vision is an enterprise-grade **Agent Control Platform**. In the current phase, the goal is to solidify the framework's control semantics, contracts, adapter boundaries, and the runnable Insurance Customer Service Agent.

V1 also introduces an **Autonomous Customer Service Mode** private pilot. This mode keeps Proof Agent positioned as the reusable Controlled Agent Harness Framework while delivering a concrete Insurance Customer Service Agent for direct end-customer automatic replies. The V1 product has two deliverables:

- **Agent Framework Deliverable:** customer contracts, Customer Run API, Customer-Safe Response Projection, read-only authorization boundaries, internal handoff events, and handoff monitor projections.
- **Insurance Customer Service Agent:** `examples/insurance_customer_service/`, customer Web Chat, deterministic journey suite, and local Markdown knowledge.

## 2. Target Audience

- Enterprise AI platform teams: Need unified governance over remote models, tools, knowledge bases, and approvals.
- Agent application owners: Need readable receipts and machine-processable traces.
- Security, compliance, and architecture review teams: Need structured traces and readable receipts.
- AI consulting and delivery teams: Need reusable, controlled Agent delivery skeletons.

## 3. Core Capabilities

| Capability | Product Requirement |
| --- | --- |
| Agent Contract | Use `agent.yaml` to declare workflow, knowledge, model, policy, tools, memory, audit |
| Workflow | Harness controls workflow state transitions; the model only generates content within controlled nodes |
| PolicyEngine | Outputs typed decisions at enforcement points like retrieval, answer, tool, memory, model call |
| Model Provider | Supports deterministic baselines and remote providers; remote output must pass validators |
| Knowledge Provider | Supports local documents, vector stores, and remote enterprise knowledge source adapters; uniformly returns `EvidenceChunk` |
| Tool Gateway / MCP | All tool calls go through an allowlist, parameter validation, risk grading, approval, and trace |
| Memory Boundary | Memory read/write has policy, redaction, retention, and tenant boundary designs |
| Validators | Admission control for schema, evidence, citation, safety, tool result, etc. |
| Trace & Receipt | JSONL Trace is the source of truth; Governance Receipt is the human-readable proof |
| Run Execution API | Application surfaces start governed runs through Published Agent ids, not arbitrary manifest paths |
| Customer Run API | Customer-facing conversations return only customer-safe response projections |
| Customer Handoff Monitor | Internal handoff events are visible to operators without exposing escalation state to customers |
| Controlled Conversation Context | Assisted chat can use prior turns through bounded, trace-safe context admission while preserving per-turn evidence retrieval |
| Dashboard | Dashboard API queries runs, traces, receipts, stats; UI/Approval Console for future platform evolution |
| Deployment | Both CLI and Docker can run the deterministic demo; remote capabilities are enabled via environment variables and optional extras |

## 4. Current MVP Scope

The current runnable MVP exposes the Insurance Customer Service Agent as its canonical public example while keeping deterministic Enterprise QA regression fixtures to prove the complete Harness lifecycle:
1. Load `agent.yaml`.
2. Execute policy gates.
3. Retrieve knowledge and evaluate evidence.
4. Call deterministic or remote model provider.
5. Process tool approval.
6. Control memory write.
7. Run validators.
8. Write trace, receipt, and run history.
9. Observe results via CLI, Docker, or Dashboard API.

Acceptance outcomes for the current deterministic demo:
```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
tool_required: WAITING_FOR_APPROVAL
```
> Note: Enumeration values in code should be considered authoritative; examples in documentation must be checked synchronously during validation.

Customer service V1 acceptance adds:

- anonymous customers may ask generic policy/claim questions but must sign in for customer-specific status
- authenticated mock customer sessions may read only their own policy and claim status
- customer responses must not expose trace links, receipt links, policy decisions, review results, approval state, tool parameters, or internal handoff state
- account-changing requests and cross-customer access attempts create internal handoff events for monitoring

## 5. Non-Goals

For the current phase, we do not commit to:
- A fully hosted multi-tenant console.
- Production-grade RBAC / IAM / OAuth / DLP.
- Production OAuth/OIDC/IAM for customer sessions.
- Customer-visible human escalation states.
- Transactional insurance actions such as canceling policies, submitting claims, or approving payments.
- Compatibility with all MCP servers.
- Complete immunity against arbitrary prompt injections.
- LLM-as-judge replacing deterministic validators.
- Multi-Agent platforms, template marketplaces, or hosted control planes.

These are directions for platform evolution but must be added gradually after the Control Envelope semantics are stable.

## 6. Success Criteria

- Enterprise reviewers can run the CLI or Docker demo successfully within 30 minutes.
- The deterministic demo requires no API keys and covers answer, refusal, and approval-wait scenarios.
- Remote model paths cannot bypass policies, evidence, validators, traces, and receipts.
- The Tool Gateway can prove that tool governance semantics remain consistent before and after real MCP integration.
- The Dashboard API can query execution history based on run artifacts, rather than spawning a separate execution semantic.
- The evaluation system measures Governed Resolution Rate through deterministic gates, while LLM or human judges remain diagnostic and cannot replace governance validators.
- Documentation system is clear: AI reads `docs/README.md` first; architecture reads `docs/technical-design.md` first.

## 7. Evolution Roadmap

| Phase | Goal | Key Deliverables |
| --- | --- | --- |
| 0 | Contracts and positioning | PRD, technical design, concept docs, Agent Contract |
| 1 | Deterministic Harness MVP | CLI, Docker, Enterprise QA Template, Trace, Receipt |
| 2 | Model Provider Governance | remote model provider, model trace, model validators |
| 3 | Observability & Dashboard API | RunStore, runs/history, health/runs/stats API |
| 4 | Production Adapters | LangChain/LangGraph, real MCP, vector store, Azure/Anthropic, streaming |
| 5 | Customer Service V1 | Customer Run API, Customer Web Chat, internal handoff monitor, Insurance Customer Service Agent |
| 6 | Controlled Agent Memory | Local Case Memory, Memory Admission, Mem0 adapter, User Memory, Shared Memory |
| 7 | Agent Control Platform | Dashboard UI, Approval Console, RBAC, multi-template, multi-Agent, external observability export |
