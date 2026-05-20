# Proof Agent Documentation

Proof Agent is a Controlled Agent Harness Framework. It uses Harness Engineering to manage the Agent lifecycle across workflow, policy, tools, memory, models, validators, trace, receipt, deployment, and observability.

The project is not positioned as local-first or CLI-first. It keeps a deterministic local demo as a regression baseline, and supports CLI and Docker entry points. Remote models, LangChain/LangGraph, vector stores, real MCP, and Dashboard capabilities are adapter-driven integrations around the same Harness contract.

## Source Of Truth

1. `prd.md` — product positioning, scope, non-goals, roadmap.
2. `technical-design.md` — authoritative architecture and implementation boundaries.
3. `feasibility-analysis.md` — feasibility, audience, stack options, and risks.
4. `developer-guide.md` — developer workflow for building, configuring, deploying, and managing governed Agents.
5. `development-progress.md` — current codebase status; useful, but always verify against the code.



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

## Developer Guide

| Document | Purpose |
| --- | --- |
| `developer-guide.md` | Quick Start, architecture module overview, configuration, development, deployment, and management steps for AI Agent owners |

## Examples

| Document | Purpose |
| --- | --- |
| `examples/launch-script.md` | Demo and evaluation commands |
| `examples/enterprise-qa.md` | Enterprise QA Template behavior |
| `examples/react-enterprise-qa.md` | Controlled ReAct Enterprise QA workflow behavior |
| `examples/insurance-service-qa.md` | Insurance Service QA Reference Agent behavior |
| `examples/insurance-customer-service.md` | Customer-facing Insurance Customer Service Agent behavior |
| `examples/governance-receipt.md` | Example receipt rendering |

## Bilingual Structure

Docs are bilingual: English (default) under `docs/`, Chinese translations under `docs/zh/` with the same directory structure. Only update English docs during development; Chinese translations are synced at release time.

## Active Documentation Policy

- Keep root-level docs few and authoritative.
- Put reusable contracts in `concepts/`.
- Put runnable behavior in `examples/`.
- Do not keep parallel architecture plans that restate the same roadmap.
- When a design decision changes, update the PRD, technical design, and affected concept page together.
