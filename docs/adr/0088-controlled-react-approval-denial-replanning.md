# Controlled ReAct Approval Denial Replanning

Controlled ReAct approval denial does not immediately terminate the run. A denial is recorded as an Approval Denial Observation, then the planner replans from the remaining admitted context so the Agent may continue with an alternate governed path when the denied tool is not essential.

This preserves operator authority over the specific tool execution without turning every denial into a full conversation stop. If replanning determines that the denied tool is necessary and no governed alternative can satisfy the task, the workflow must terminate with `TOOL_APPROVAL_DENIED` rather than inventing a tool result, bypassing approval, or misclassifying the stop as `REFUSED_NO_EVIDENCE`.
