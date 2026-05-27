# Dashboard-Hosted Agent Configuration Workspace

Proof Agent will add an Agent Configuration Workspace inside the shared Dashboard Shell instead of building a detached builder app or turning the Dashboard API into an execution/configuration catch-all. We chose this because Agent owners need to move fluidly between monitoring a governed Agent and changing its configuration, while the trust boundaries still require separate API surfaces for observability, configuration, and execution.

The Dashboard Shell becomes Agent-centric: global run, approval, and handoff monitoring remains available, and each Agent detail view combines Monitor, Configure, Validate & Test, Versions, and Contract View. Configuration is served by an Agent Configuration API; Dashboard API remains read-only observability; Run Execution API and Customer Run API continue to execute only Published Agent Versions.

Agent configuration follows a Draft Agent lifecycle. The Agent Configuration Store owns drafts, version history, validation results, publication metadata, reusable Knowledge Sources and Tool Sources, and operation audit metadata. Agent Contract and Agent Package artifacts remain the reviewable execution language; existing Agent Packages can be imported into Draft Agents without overwriting the source package by default.

Publication promotes a validated Draft Agent into an immutable Published Agent Version after an Agent Validation Run. A Published Agent resolves to an Active Agent Version by default, and rollback changes that active pointer instead of mutating or deleting historical versions. Run artifacts must record the actual Published Agent Version used for execution.

Workflow editing is Workflow Template Node Configuration, not free-form runtime graph editing. The UI may expose node-based editing for planner, retrieval, review, tool gate, answer gate, memory, and response settings, but those settings compile back into registered Workflow Template and Agent Contract semantics.

Knowledge and tools use a reusable asset plus Agent binding model. Knowledge Sources and Tool Sources are reusable; Agent Knowledge Bindings and Agent Tool Bindings define per-Agent scope, retrieval strategy, approval behavior, and authorization constraints. Memory remains Agent-specific Agent Memory Configuration in the first implementation stage because consent, lifecycle controls, and cross-Agent leakage risk make reusable memory assets a later platform concern.

The first experience uses an Agent Creation Wizard for setup, then a module-based workspace with visual forms, Workflow Template Node Configuration, Validate & Test, Versions, and Contract View. Contract View is an advanced view over the same Draft Agent state, not a second source of truth. Natural-language descriptions may help users understand configuration, but executable policy remains structured Policy Rule Configuration.
