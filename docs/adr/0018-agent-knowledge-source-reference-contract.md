# Agent Knowledge Source Reference Contract

Accepted.

Proof Agent will replace ambiguous Agent-level `knowledge_sources[]` usage with explicit `package_knowledge_sources[]` plus `knowledge_bindings[].source_ref`, where `source_ref.scope` is either `package` or `shared`. We chose this direct breaking contract shape because standalone Agent Packages still need package-local Sources for deterministic demos and fixtures, while Dashboard-managed Agents must reference published shared Knowledge Sources without copying mutable provider params into Agent Draft YAML; keeping one `knowledge_sources[]` name for both cases would make the Knowledge Binding Resolver boundary ambiguous and invite runtime compatibility paths.
