# Evaluation Decisions

## Ambiguity Resolutions

- "Handoff trigger configuration" could mean hard-coded only, business-configurable, or prompt-defined. Resolved: V1 keeps fixed baseline triggers and permits Agent Contract or policy configuration only for enterprise high-value failure scenarios; frontend and prompt-defined triggers are not trusted.
- "Admit an exactly deduplicated candidate" could mean boosting confidence because multiple sources returned it, averaging scores, selecting the highest score, or applying conservative admission. Resolved: **Merged Evidence Admission Evaluation** keeps WRRF contribution aggregation separate from admission; an approved scorer evaluates the merged chunk once when configured, otherwise the minimum available calibrated contributor score applies, and candidates with no valid score remain inadmissible.

## Relationship And Reference Notes

- Evaluation verifies governed behavior but does not become runtime authority.

- Published Agent Version boundaries matter because evaluation trends must be version-aware.

- **Workflow Template Stages** are reserved for Agent-owner-visible configuration, explanation, audit, or evaluation points; internal policy checks, validators, model requests, helper functions, and Runtime Plane nodes are not automatically stages.
- **Merged Evidence Admission Evaluation** does not reward duplicate retrieval hits with a higher Evidence Admission Score. When configured, an approved admission scorer evaluates the merged normalized chunk once; otherwise the merged candidate uses the minimum available calibrated Evidence Admission Score from contributing sources. Contributors without calibrated admission scores remain visible in Trace but do not participate in score aggregation, and a merged candidate with no valid admission score remains inadmissible.
