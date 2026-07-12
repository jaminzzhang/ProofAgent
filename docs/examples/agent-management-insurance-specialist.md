# Agent Management Insurance Specialist

`examples/agent_management_insurance_specialist/` is the sole public and initial-production Agent identity.

It serves internal insurance operations specialists through Controlled ReAct V3. The S0 package answers knowledge-backed questions with deterministic providers and does not access current customer, policy, claim, agent, performance or activity records.

```bash
uv run --extra dev proof-agent run \
  examples/agent_management_insurance_specialist/agent.yaml \
  --question "理赔处理中需要向代理人说明哪些材料要求？"
```

Expected properties:

- workflow template is `react_enterprise_qa_v3`;
- package knowledge is routed through explicit bindings;
- Business Flow Skill Packs narrow intent and context without granting authority;
- tools are disabled and `max_tool_calls` is zero;
- trace and Governance Receipt are written under `runs/latest/`;
- unsupported claims fail closed when evidence is insufficient.

S5 will replace development package-local knowledge/memory bindings with published PostgreSQL/S3/secret-handle references and may add validated read-only HTTPS tools. That production migration is not part of the current S0 package.
