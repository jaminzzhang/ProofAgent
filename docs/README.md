# Proof Agent Documentation

Proof Agent is a Controlled Agent Harness Framework. It uses Harness Engineering to manage the Agent lifecycle across workflow, policy, tools, memory, models, validators, trace, receipt, deployment, and observability.

The project is not positioned as local-first or CLI-first. It keeps a deterministic local demo as a regression baseline, and supports CLI and Docker entry points. Remote models, LangChain/LangGraph, vector stores, real MCP, and Dashboard capabilities are adapter-driven integrations around the same Harness contract.

## Source Of Truth

1. `prd.md` — product positioning, scope, non-goals, roadmap.
2. `technical-design.md` — authoritative architecture and implementation boundaries.
3. `feasibility-analysis.md` — feasibility, audience, stack options, and risks.
4. `developer-guide.md` — developer workflow for building, configuring, deploying, and managing governed Agents.
5. `evaluation-system.md` — V1 Agent evaluation metrics, deterministic gates, judge diagnostics, suites, thresholds, curation, and artifacts.
6. `evaluation-campaign-system.md` — coding-agent-led Campaign workflow, Active Agent readiness, Evaluation Lab page, performance diagnostics, and repeatable artifact model.
7. `frontend-design-principles.md` — mandatory Dashboard and Unified Chat frontend IA, interaction, component, and review principles.
8. `development-progress.md` — current codebase status; useful, but always verify against the code.


## Domain Language

| Document | Purpose |
| --- | --- |
| `../CONTEXT-MAP.md` | Routes agents and humans to the relevant domain context. |
| `../CONTEXT.md` | Product Core glossary terms shared by every domain. |
| `domain/*/CONTEXT.md` | Focused domain glossaries for workflow control, configuration, knowledge, tools/models/memory, observability, evaluation, application surfaces, and reference domains. |
| `domain/*/decisions.md` | Optional lightweight ambiguity-resolution and relationship notes for decisions too granular for an ADR but too verbose for a glossary. |
| `../scripts/check-domain-contexts.py` | Structural checker for glossary-only context files and duplicate terms. |

## Concept Contracts

| Document | Purpose |
| --- | --- |
| `concepts/control-envelope.md` | Core Harness / Control Envelope mental model |
| `concepts/agent-contract.md` | `agent.yaml` public contract |
| `concepts/policy-engine.md` | Policy enforcement points and decisions |
| `concepts/approval-state-contract.md` | Tool approval state machine |
| `concepts/trace-event-contract.md` | JSONL trace event contract |
| `concepts/governance-receipt-contract.md` | Human-readable receipt contract |
| `concepts/trust-boundaries.md` | Security scope, assumptions, and non-claims |
| `concepts/react-loop-control.md` | Controlled ReAct Loop control contract: action set, budget, convergence, eligibility, Observation Records |

## Architecture Decision Records

| Decision set | Purpose |
| --- | --- |
| `adr/0048-controlled-react-orchestrator-v3-only.md` through `adr/0073-controlled-react-migration-slice-order.md` | V3 Controlled ReAct Orchestrator cutover: v3-only product path, run-scoped start/resume interface, no LangGraph core, typed run state, observation-only actions, approval snapshot resume, module placement, port boundaries, delivery entrypoint, template-bound execution, stage projection, test authority, and migration order |
| `adr/0032-controlled-react-loop-and-convergence-governance.md` and `adr/0033-react-loop-verification-regime.md` | Loop governance and verification baseline that V3 Orchestrator implements or narrows |

## Developer Guide

| Document | Purpose |
| --- | --- |
| `developer-guide.md` | Quick Start, architecture module overview, configuration, development, deployment, and management steps for AI Agent owners |

## Frontend

| Document | Purpose |
| --- | --- |
| `frontend-design-principles.md` | Mandatory design principles for Dashboard and Unified Chat frontend changes |

## Evaluation

| Document | Purpose |
| --- | --- |
| `evaluation-system.md` | Governed Agent evaluation model, including Governed Resolution Rate, deterministic gates, judge-led diagnostic scoring, release thresholds, and production curation |
| `evaluation-campaign-system.md` | Repeatable Evaluation Campaign workflow for the Active Published Agent Version, including sample production, coding-agent diagnostics, private Evaluation Lab page data, and version-aware trends |

## Implementation Specs

| Document | Purpose |
| --- | --- |
| `specs/mcp-tool-gateway-support.md` | Implementation slices and test plan for accepted MCP Tool Gateway support decisions. Specs must stay subordinate to ADRs, concept contracts, and `technical-design.md`. |

## Examples

| Document | Purpose |
| --- | --- |
| `examples/launch-script.md` | Demo and evaluation commands |
| `examples/insurance-customer-service.md` | Customer-facing Insurance Customer Service Agent behavior |
| `examples/institution-insurance-specialist.md` | Staff-facing Institution Insurance Specialist Agent behavior |
| `examples/governance-receipt.md` | Example receipt rendering |

## Bilingual Structure

Docs are bilingual: English (default) under `docs/`, Chinese translations under `docs/zh/` with the same directory structure. Only update English docs during development; Chinese translations are synced at release time.

## Active Documentation Policy

- Keep root-level docs few and authoritative.
- Put reusable contracts in `concepts/`.
- Put runnable behavior in `examples/`.
- Do not keep parallel architecture plans that restate the same roadmap.
- When a design decision changes, update the PRD, technical design, and affected concept page together.
