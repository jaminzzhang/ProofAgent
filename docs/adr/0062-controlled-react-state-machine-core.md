# Controlled ReAct State Machine Core

Accepted.

The V3 **Controlled ReAct Orchestrator** will be implemented around a typed **Controlled ReAct State Machine Core**. Public `start` and `resume` operations drive explicit transitions shaped as `ControlledReActRunState -> TransitionCommand -> EffectResult -> ControlledReActRunState/Outcome`.

LLM calls, retrieval, tool execution, policy evaluation, trace-safe stage projection, receipt projection, transition locking, and run-state snapshot persistence are effect ports. The state machine core may select commands, validate results, update typed run state, and classify outcomes, but it must not directly mutate untyped dictionaries, depend on LangGraph state, or allow capability modules to own orchestration state.

The rejected alternative is an imperative orchestrator that calls planner, retrieval, tool, trace, and persistence helpers in sequence while sharing mutable state. That shape would preserve the current shallow orchestration boundary: side effects would define control flow, and tests would need to exercise adapters instead of deterministic transition rules.
