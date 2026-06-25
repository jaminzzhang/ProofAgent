# Shadow Verify Before Controlled ReAct Orchestrator Cutover

Accepted.

The V3 **Controlled ReAct Orchestrator** migration may use temporary **Controlled ReAct Shadow Verification** before the hard cutover: representative current V3 inputs run through the new Orchestrator and are compared against the existing path for governed outcomes, trace facts, stage projections, approval pauses, receipts, and explicitly intended semantic corrections. After verification passes, the old executable paths are deleted rather than retained behind flags or compatibility adapters.

The rejected alternative is a direct hard cut with no shadow verification. That aligns with the final architecture but makes regressions hard to localize because this refactor changes executor ownership, state shape, approval resume, observation records, and stage projections together. Shadow verification is a migration tool only; it does not create dual-runtime product semantics.
