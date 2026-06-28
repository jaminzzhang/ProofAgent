# Final Answer Admission Policy Gate

Controlled ReAct V3 treats `before_answer` as the final answer admission gate. It runs after answer synthesis produces a candidate governed answer and before the terminal result is committed, checking accepted evidence, citation presence and binding, authorized tool-result support, and final output validation facts.

`before_model_call` decides whether the answer model may be called; `before_answer` decides whether the candidate answer may leave the Control Envelope. If final answer admission is denied and no alternate governed path remains, the run terminates with `POLICY_DENIED`.
