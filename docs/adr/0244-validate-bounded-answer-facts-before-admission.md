# ADR-0244: Validate bounded answer facts before admission

## Status

[FRAME | HIGH] Accepted for the user-authorized P0-4 implementation on 2026-09-06.

## Decision

Control Plane adds deterministic, bounded fact consistency checks to the existing final-answer validation boundary. Legal citations alone cannot support a different amount, unit, subject, polarity or explicitly stated field value. Only cited Accepted Evidence content supports facts; provenance identifiers and conversation are not evidence facts. Structured fields retain their exact values and record identities.

Keep FinalAnswerOutput unchanged. Source-near numeric statements and explicit assertions are checked conservatively; unrecognized language is counted as unassessed. A passed bounded check is not proof of universal semantic entailment. Calculations, currency conversion, broad paraphrase and implicit reasoning require later evaluation/design rather than favorable model self-assessment.

Reuse the existing one-repair final-answer path, including policy evaluation and all validation gates on every attempt. Safety failures never enter repair even when another validator fails first. An exhausted repair returns the existing safe refusal; policy/budget denial remains policy_denied. Diagnostic metadata contains bounded codes/counts, never source or answer text. No provider coupling, public configuration, storage or production authority is added.
