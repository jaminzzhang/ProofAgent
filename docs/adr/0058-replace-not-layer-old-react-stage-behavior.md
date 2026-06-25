# Replace, Not Layer, Old React Stage Behavior

Accepted.

The V3 **Controlled ReAct Orchestrator** must replace the existing React Enterprise QA stage behavior surface rather than wrapping it as a dependency. Existing pure helpers, validators, provider adapters, `KnowledgeRetrievalService`, `ToolGateway`, policy evaluation, trace emitters, and model normalization code may be extracted or reused, but the Orchestrator must not delegate core transitions to `ReActEnterpriseQAStageBehavior` or its public stage methods.

The rejected alternative is a thin Orchestrator facade over the old stage behavior. That would reduce first-commit churn but preserve the current shallow module: raw continuation dictionaries, public per-stage execution, runtime imports, and tool terminal-output behavior would remain behind the new name. The refactor goal is to deepen the orchestration module, not rename the old one.
