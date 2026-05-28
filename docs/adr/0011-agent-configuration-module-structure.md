# Agent Configuration Module Structure

The Agent Configuration Workspace organizes editing into eight Agent Configuration Modules (General, Workflow, Knowledge, Tools, Policy, Model, Memory, Response) plus four Agent Lifecycle Tabs (Validate & Test, Versions, Contract View, Monitor). We chose this because each module owns a focused set of Agent Contract fields, and separating configuration from lifecycle operations prevents users from accidentally publishing while editing or confusing draft state with published versions.

The alternative of grouping by concern (Behavior, Capabilities, Governance) was rejected because it adds nesting that doesn't match how users navigate—they think "I need to edit tools" not "I need to go into Capabilities." The alternative of workflow stages (Setup, Configure, Validate, Publish) was rejected because it implies a linear progression when users actually iterate between modules.
