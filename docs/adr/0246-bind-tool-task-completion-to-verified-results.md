# ADR-0246: Bind tool task completion to verified results

## Status

[FRAME | HIGH] Accepted for the user-authorized P1-2 implementation on 2026-09-06; concrete contracts remain bounded by the P1/P2 scope plan.

## Decision

Extend the existing Controlled ReAct workflow to execute a bounded dependency plan of required read-only tool work. Freeze admitted task requirements before execution. A model may propose an action, but cannot remove a requirement, change its dependency or declare completion. Parameters derived from earlier work must bind to verified same-Run observations rather than model-rewritten values.

Enforce tool-call budget before dispatch, preserve failures and cancellation, and require bound successful result truth before completing each dependent task. Query, deterministic computation and report generation form one V3 execution path through Tool Gateway and existing artifact finalization. Report bytes and semantic content must be checked before visibility; a matching hash alone is insufficient. No arbitrary code execution, package handler or state-changing production tool is introduced.

The initial calculation verifier uses explicitly configured exact decimal sum over decimal strings; no implicit rounding, exchange rate or domain rule is inferred. Missing results, unknown outcomes, stale/cross-Run proofs and dependency cycles fail closed. Recovery uses the same persisted observations and does not treat trace summaries as execution authority.

[KNOWN | HIGH] Recovery binds the persisted task plan, selected admitted Skill, conversation/Memory inputs and execution configuration digest, including Tool Source configuration. Production Queue checkpoint-pointer integration is not part of this local port recovery implementation.
