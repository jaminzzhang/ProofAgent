# Product Core Decisions

## Ambiguity Resolutions

- "Harness Agent framework" could mean the framework itself or an Agent built with it. Resolved: use **Controlled Agent Harness Framework** for the framework category.
- "V1 deliverable" could mean only the customer-service bot or the reusable Agent framework plus reference Agent. Resolved: V1 includes an **Agent Framework Deliverable** and the **Insurance Customer Service Agent**.
- "`examples/` v2 template" could mean renaming Public Example Agent Package directories or changing the Workflow Template registry. Resolved: keep stable **Public Example Agent Package** paths under `examples/` and upgrade their Agent Contracts, docs, and tests to use **React Enterprise QA Template V2** semantics.
- "`examples/` cleanup scope" could mean deleting internal evaluation fixtures as well as public example packages. Resolved: this cleanup is limited to source-controlled **Public Example Agent Package** files under `examples/`; internal evaluation fixtures under `proof_agent/evaluation/demo/fixtures/` remain separate regression assets.
- "Configuration storage" could mean replacing Agent Contract files or storing editable product state. Resolved: the **Agent Configuration Store** owns draft/version metadata, while **Agent Contract** and **Agent Package** remain the reviewable execution artifacts.
- "Policy-authorized read" could mean direct Customer API preflight execution or a governed tool call that skips only human approval. Resolved: it skips human approval only; the read still runs inside the **Control Envelope** and writes full Harness run artifacts.
- "Answer-ready eligible actions" could mean `{GENERATE_FINAL_ANSWER, REFUSE}` or a single finalization action. Resolved per ADR-0047: with no explicit blocker, the eligible set is `GENERATE_FINAL_ANSWER` only, backed by deterministic Action Constraint rewrite.

## Relationship And Reference Notes

- Proof Agent is a Controlled Agent Harness Framework.

- The Control Envelope is the cross-cutting boundary that every runtime and capability integration must respect.

- Reference Agents validate the Agent Framework Deliverable without defining the full product.

- Proof Agent is a **Controlled Agent Harness Framework**.
- V1 ships both an **Agent Framework Deliverable** and the **Insurance Customer Service Agent** reference implementation.
- An **Agent Contract** selects a **Workflow Template** for a run.
- An **Agent Contract** may configure model provider, model name, and provider parameters for planner and reviewer roles, but must not replace the **Harness Control Prompt** in V1.
- `policy_decision` remains the final governance trace event after `PolicyEngine` validation.
- **Agent Contract** and **Agent Package** remain the reviewable execution artifacts even when drafts and publication metadata live in the **Agent Configuration Store**.
- Remote request endpoint and URL path are static published configuration values. Headers may be static non-sensitive values or environment-variable references with an optional static prefix. V1 request mapping does not support string interpolation, dynamic URL paths, loops, conditions, functions, network callbacks, or scripts.
- An **Agent Contract** references one or more **Knowledge Sources** through an **Agent Knowledge Binding Set** without selecting providers.
- An **Agent Contract** must explicitly declare its **Retrieval Strategy**.
- **Harness RAG** admits final answers only after policy and evidence checks.
- **Plain RAG** does not provide the Harness controls required by **Harness RAG**.
