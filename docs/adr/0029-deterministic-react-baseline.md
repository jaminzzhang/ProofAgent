# Deterministic ReAct Baseline

Accepted.

Proof Agent's long-term deterministic regression baseline will be the primary `react_enterprise_qa` Workflow Template running through deterministic planner, reviewer, model, retrieval, and tool implementations, rather than the older linear `enterprise_qa` template. The old `enterprise_qa` template remains a read-only compatibility path, but it is not a permanent architectural baseline; if preserving it later blocks clean Workflow Template Execution boundaries, Proof Agent may explicitly delete and rebuild that compatibility path around React Enterprise QA. We choose this because the baseline should prove the governed Workflow Template used by the product, while maintaining a separate legacy workflow world hides execution-boundary debt and makes later Workflow cleanup harder.
