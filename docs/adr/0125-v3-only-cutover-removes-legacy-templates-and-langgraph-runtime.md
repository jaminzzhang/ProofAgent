# V3-Only Cutover Removes Legacy Templates and LangGraph Runtime

Accepted.

[FRAME | HIGH] `react_enterprise_qa_v3` is the sole supported Workflow Template after the initial-production cutover. `enterprise_qa`, `react_enterprise_qa` V1, `react_enterprise_qa_v2`, Agentic RAG examples, their executable fixtures, and their dispatch, validation, UI-catalog, CLI, evaluation, and current-documentation paths are deleted rather than hidden behind flags, aliases, automatic migration, or an importable `legacy` package. Old template names fail closed with a stable unsupported-version diagnostic.

[FRAME | HIGH] The public Agent Contract removes `workflow.runtime`, `workflow.checkpointer`, `CheckpointerConfig`, and the `react.max_steps` compatibility alias; V3 template identity binds Controlled ReAct Orchestrator execution and requires `max_plan_rounds`. The direct LangGraph dependency, legacy runtime graphs and runners, and LangGraph resume branches are removed. V3 convergence, action-constraint, review, tracing, snapshot, truth, claim, and resume helpers currently located in legacy-named modules must first move behind Controlled ReAct modules and ports.

[FRAME | HIGH] `agent_management_insurance_specialist` is the only current public example and production Agent. One internal deterministic V3 fixture remains for offline demo and test authority without becoming a second public Agent. Git history, accepted ADRs, and dated design or plan documents remain historical records, while active documentation and domain glossaries describe V3 only. Completed legacy artifacts remain read-only projections, but legacy drafts and Published Agent Versions are deactivated or quarantined without conversion, and legacy pending approvals become explicitly unresumable.

[FRAME | HIGH] This decision supersedes the executable compatibility provisions of ADR-0029 and earlier V1/V2 support statements while completing the deletion direction established by ADR-0055, ADR-0058, and ADR-0070.
