# Controlled ReAct Legacy Runtime Deletion Gate

Accepted.

The V3 Orchestrator cutover requires removing legacy V3 execution entrypoints from production code, tests, and current architecture documentation. `run_with_langgraph`, `resume_langgraph_approval`, `LangGraphApprovalResumeRegistry`, React runtime graphs, and LangGraph checkpoint resume must not remain as V3 execution paths after cutover.

Tests that currently exercise those entrypoints should be rewritten against `ControlledReActOrchestrator.start` and `ControlledReActOrchestrator.resume`, or deleted when they only assert retired behavior. Documentation must describe the Orchestrator path as the current architecture; historical plans may remain as history but must not define active execution semantics. LangGraph dependencies should be removed if no non-V3 product path still requires them after the old paths are deleted.

The rejected alternative is keeping legacy runtime functions as internal compatibility helpers or test fixtures. That would let retired runtime behavior continue to define correctness through test authority, CLI usage, or stale documentation despite the new Orchestrator entry point.
