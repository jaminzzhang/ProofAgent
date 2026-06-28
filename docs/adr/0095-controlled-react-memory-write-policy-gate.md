# Controlled ReAct Memory Write Policy Gate

Controlled ReAct V3 treats memory writes as governed side effects that must pass `before_memory_write` before any memory provider is mutated. The Orchestrator owns this decision. Memory adapters may prepare candidate values and commit approved writes, but they must not be the semantic owner of the policy gate.

The V3 memory port is split into candidate preparation and commit. `prepare_write(state, answer)` produces the proposed write values for policy evaluation and trace-safe metadata. The Orchestrator emits `memory_write_requested`, evaluates `before_memory_write`, emits the normal `policy_decision`, and then either calls `commit_write(candidate)` or emits a blocked `memory_write_decision` without committing.

Denied memory writes block only the memory side effect. They do not change the terminal user-facing answer unless a future policy explicitly defines memory denial as terminal. This keeps answer admission (`before_answer`) separate from side-effect admission (`before_memory_write`) and aligns V3 with the existing Customer API memory write semantics.

Trace payloads for memory write governance must remain trace-safe. They may include field names, field counts, decision status, policy rule id, and validation metadata, but not raw memory values or final answer text.
