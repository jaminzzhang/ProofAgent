# Policy Denied Outcome

Proof Agent uses a distinct `POLICY_DENIED` terminal outcome when policy blocks a required governed action and no alternate governed path can satisfy the request. Controlled ReAct V3 maps final-answer model `before_model_call` denial to this outcome instead of `REFUSED_NO_EVIDENCE`.

This keeps evidence insufficiency separate from policy enforcement. The trade-off is a public outcome enum expansion that must be reflected in receipts, Dashboard badges, API projections, and evaluation gates.
