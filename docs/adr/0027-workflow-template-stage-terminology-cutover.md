# Workflow Template Stage Terminology Cutover

Accepted.

Proof Agent will migrate public Workflow Template language from node terminology to **Workflow Template Stage** terminology across Agent Contract configuration, Workflow Template Descriptor, Dashboard configuration, trace facts, examples, and tests without dual-reading old `workflow.nodes[]` fields. We chose a direct breaking cutover because "node" is easily confused with LangGraph or runtime graph nodes, while "stage" names the governed Control Envelope concept that Agent owners, Dashboard, trace, and Published Agent explanations share.
