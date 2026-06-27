# Context Map

Proof Agent is moving from one large domain glossary to routed domain contexts. Use this map to choose the smallest relevant context before reading domain language.

During the migration, [CONTEXT.md](./CONTEXT.md) keeps product-wide terms only. New domain terms should go into the relevant `docs/domain/*/CONTEXT.md` file. Resolved ambiguity or relationship history should go into the matching `docs/domain/*/decisions.md` file when that history is worth preserving.

## Contexts

- [Product Core](./CONTEXT.md) - product category, cross-cutting Harness language, and terms shared by every other context.
- [Workflow Control](./docs/domain/workflow-control/CONTEXT.md) - Workflow Templates, Controlled ReAct execution, approval, clarification, observations, and finalization.
- [Agent Configuration](./docs/domain/agent-configuration/CONTEXT.md) - Agent Contract authoring, Draft and Published Agents, publication, validation, and effective configuration.
- [Business Flow Skills](./docs/domain/business-flow-skills/CONTEXT.md) - Business Flow Skill Pack bindings, routing, admission, addenda, and no-pack behavior.
- [Knowledge And Evidence](./docs/domain/knowledge-evidence/CONTEXT.md) - Knowledge Sources, bindings, retrieval, ingestion, evidence, citations, and Local Index language.
- [Tools Models And Memory](./docs/domain/tools-models-memory/CONTEXT.md) - Tool and MCP capability language, model connection language, model-call roles, and memory scopes.
- [Tool Proposal Governance](./docs/domain/tool-proposal-governance/CONTEXT.md) - planner-visible tool proposal eligibility, proposal-safe parameters, binding, approval snapshots, and scope violations.
- [Observability](./docs/domain/observability/CONTEXT.md) - Trace, Governance Receipt, RunStore, Dashboard projections, validation capture, and audit-safe summaries.
- [Evaluation](./docs/domain/evaluation/CONTEXT.md) - evaluation cases, suites, campaigns, metrics, gates, diagnostics, and release thresholds.
- [Application Surfaces](./docs/domain/app-surfaces/CONTEXT.md) - Dashboard, Unified Chat, Knowledge Hub UI, list pagination, approval queue filters, and navigation terminology.
- [Insurance Reference](./docs/domain/insurance-reference/CONTEXT.md) - public example Agents and insurance-specific customer/institution service language.

## Relationships

- Product Core defines the vocabulary shared by all other contexts.
- Agent Configuration chooses and publishes the Workflow Control and capability configuration used at run time.
- Workflow Control consumes Knowledge And Evidence, Tools Models And Memory, Tool Proposal Governance, and Business Flow Skills through governed Control Envelope boundaries.
- Tool Proposal Governance consumes Tool Contracts and Agent Tool Bindings from Tools Models And Memory, then exposes planner-visible proposal scope without granting execution permission.
- Business Flow Skills may narrow or prioritize Tool Proposal Governance facts, but they do not create or expand tool authority.
- Observability records projections of Workflow Control facts, but it does not own execution decisions.
- Observability records Tool Proposal Governance projections, but it does not own tool proposal admission.
- Evaluation exercises Published Agent Versions, Workflow Control behavior, and Tool Proposal Governance behavior without becoming a runtime authority.
- Application Surfaces configure or observe Agents through APIs; they do not bypass Product Core governance boundaries.
- Insurance Reference is a reference domain that validates the framework; it is not the whole product.

## Maintenance Rules

- `CONTEXT.md` and `docs/domain/*/CONTEXT.md` are glossary files and should contain only `## Language`.
- Put relationship notes, ambiguity history, and implementation-order notes in `docs/domain/*/decisions.md`.
- Keep implementation sequences, migration order, cutover scope, acceptance gates, and test gates out of glossary files.
- Keep `docs/domain/*/decisions.md` headings limited to ambiguity, relationship/reference, presentation vocabulary, and example-dialogue sections.
- Run `python3 scripts/check-domain-contexts.py` and `git diff --check` after domain documentation edits.
