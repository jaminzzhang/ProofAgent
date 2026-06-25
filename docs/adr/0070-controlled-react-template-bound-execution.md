# Controlled ReAct Template-Bound Execution

Accepted.

The V3 product path is selected by `workflow.template: react_enterprise_qa_v3`, which binds the Published Agent to the **Controlled ReAct Orchestrator**. Agent YAML does not choose the execution engine for V3 through `workflow.runtime`.

During cutover, current V3 fixtures, validation rules, and active documentation should stop requiring `workflow.runtime: langgraph` as the runtime selector. LangGraph checkpointer configuration must not define V3 approval resume semantics; approval resume is owned by the Orchestrator run-state snapshot path.

The rejected alternative is preserving `workflow.runtime` as an engine selector while routing `react_enterprise_qa_v3` to the Orchestrator. That would keep split authority between template semantics and runtime engine selection, making it possible for configuration to opt back into retired execution behavior.
