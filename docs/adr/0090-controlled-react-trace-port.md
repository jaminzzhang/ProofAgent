# Controlled ReAct Trace Port

Controlled ReAct V3 emits trace facts through a narrow run-scoped `TracePort` instead of returning a completed execution result for Delivery to decorate afterward. The port belongs to the Orchestrator effect boundary and exposes trace-safe operations for policy decisions, retrieval summaries, model request and response summaries, model errors, evidence admission, approvals, stage results, and terminal output.

The Orchestrator must not depend on `TraceWriter` or filesystem paths. Delivery and composition may adapt `TracePort` to JSONL persistence, but the ordering and existence of core governance events must follow the real execution order inside the Controlled ReAct run.
