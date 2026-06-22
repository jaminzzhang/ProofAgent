# ADR-0032: Agent-Owned Evaluation Suite Freezes with Agent Version

## Status

Accepted

## Context

Proof Agent needs evaluation results that explain the current user-visible Agent behavior and remain comparable across version changes. Agent-specific business expectations could live only in Dashboard state, only in global framework suites, or inside the Agent Package and Published Agent Version boundary.

## Decision

Agent-Owned Evaluation Suites are authored with Draft Agents and frozen into each Published Agent Version as a Published Agent Evaluation Contract. They are private evaluation commitments, not runtime execution logic and not public user-facing behavior.

Core Regression Evaluation Suites remain framework-owned. Curated Production Evaluation Samples remain diagnostic and trend inputs unless separately promoted into a reviewed Agent-Owned or release suite.

## Consequences

- Historical evaluation results compare against the exact evaluation commitment frozen with the evaluated Agent version.
- Editing Agent-Owned Evaluation Cases requires a new Draft change and Agent Publication rather than mutating past expectations.
- Agent rollback restores both the immutable runtime configuration and that version's evaluation commitment.
- Dashboard may help author Draft evaluation suites, but it must not silently rewrite Published Agent expectations.
