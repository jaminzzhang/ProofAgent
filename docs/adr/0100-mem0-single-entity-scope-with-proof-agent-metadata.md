# Mem0 Single Entity Scope With Proof Agent Metadata

Proof Agent maps each memory scope to one Mem0 primary entity instead of mixing multiple Mem0 entity ids in the same search or deletion filter: Case Memory uses `run_id = case_id`, Customer Persistent User Memory uses `user_id = subject_ref`, and Proof Agent `agent_id` plus memory scope remain in metadata. We chose this because Mem0 entity-scoped retrieval treats entity ids as provider-owned partitions, while Proof Agent still needs Agent and scope isolation without letting provider taxonomy define Memory Admission or lifecycle policy.
