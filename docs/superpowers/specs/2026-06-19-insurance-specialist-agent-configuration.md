# Insurance Specialist Agent Configuration Design

Status: Grill-with-docs draft  
Date: 2026-06-19

## Purpose

Design a Proof Agent configuration for an internal insurance specialist who supports
office staff responsible for managing agents. The Agent should answer consultation
questions about agent basic law, product clauses, underwriting, claims, customer or
agent questions, and should perform authorized read-only performance and activity
lookups for agents inside the specialist's management scope.

The design builds on `react_enterprise_qa_v2` and the existing
`examples/institution_insurance_specialist/` package. It uses dynamic business
planning with controlled execution: the LLM may infer the business subplan, but
Workflow Template topology, PolicyEngine, Tool Gateway, validators, memory, trace,
and receipt behavior remain Harness-owned.

## Confirmed Decisions

### Business Flow Shape

Use one staff-facing Institution Insurance Specialist Agent with multiple
Business Flow Skill Packs, rather than a separate workflow or one large generic
Prompt. Intent Resolution may recommend one Primary Business Flow Skill Pack, and
Control Plane admission decides whether it is admitted.

Initial Business Flow Skill Packs:

- `agent_basic_law_consultation`
- `product_clause_consultation`
- `underwriting_consultation`
- `claims_consultation`
- `customer_agent_question_support`
- `agent_performance_activity_lookup`
- `general_insurance_specialist` as the safe default

`workflow.stages[]` carries base stage Prompt addenda and context options.
Business-specific guidance belongs in package-local Skill Pack
`stage_prompt_addenda` for `plan`, `retrieval_review`, `tool_review`, and
`model_answer`.

### Lookup Authorization

Performance and activity lookup uses a two-layer scope:

1. The default lookup scope is Managed Agent Scope from Institution Authorization
   Context.
2. User-provided filters may narrow the scope but cannot expand it.

Expected lookup parameters:

- `institution_id`
- `branch_id`
- `team_id`
- `agent_id`
- `business_line`
- `report_period`
- `metric`
- `aggregation_level`

Missing required lookup facts should route to clarification. Tools remain
read-only, parameter-bounded, and audit-visible.

V1 supported metrics:

- `premium_income`
- `first_year_commission`
- `policy_count`
- `visit_count`
- `proposal_count`
- `meeting_count`
- `persistency_rate`
- `conversion_rate`
- `active_agent_count`
- `qualified_agent_count`
- `target_achievement_rate`

Every lookup requires `report_period`. Answers must disclose period,
aggregation level, filters, and calculation basis. Unsupported metrics route to
clarification or safe refusal; the model must not reinterpret them as nearby
metrics.

### Source Authority

Apply Insurance Source Authority Order:

- Authorized business-system records answer current state, such as policy
  status, claim status, agent grade, performance values, or activity values.
- Formal rules, clauses, and SOP documents answer rule interpretation, including
  agent basic law, product clauses, underwriting rules, and claims procedures.
- Report systems answer statistical or management metrics, with period, filters,
  and calculation basis disclosed.
- External wording drafts may only rephrase accepted evidence, authorized
  records, or report results; they cannot add commitments.
- Source conflicts stay explicit. The model must not invent a reconciliation.

### Configuration Language

Use Chinese for business-facing Prompt content whenever possible, including
`business_context`, `task_instructions`, and `output_preferences`. Keep machine
contract keys and stable identifiers in English, including YAML field names,
Workflow Stage ids, Tool Contract names, Knowledge Binding ids, Policy Rule ids,
and Business Flow Skill Pack ids.

### External Wording Draft Trigger

Generate an External Wording Draft only when the request clearly asks how to
reply to a customer or agent, or when the staff member explicitly requests
external wording. Ordinary consultation and lookup answers should return the
staff-facing specialist answer only.

External wording drafts must hide internal system names, tool parameters,
authorization details, policy rule names, review results, trace details, and
receipt details.

### Response Structure

Use an adaptive Institution Specialist Response Projection. Do not render every
section for every answer; include only sections supported by the request and
accepted sources.

1. Conclusion or recommendation.
2. Basis.
3. Boundary or missing information.
4. External Wording Draft, only when triggered.

Lookup answers must disclose report period, scope, metric basis, filters, and
aggregation level. Consultation answers must disclose the rule, clause, SOP, or
business record basis and the applicable conditions.

## Base Agent Contract Direction

The Agent should use:

```yaml
name: agent_management_insurance_specialist
purpose: "为保险公司内勤专员提供受控的业务咨询、条款解释、两核问题支持、客户或代理人问题答复建议，以及授权范围内的代理人业绩和活动量只读查询。"

workflow:
  runtime: langgraph
  template: react_enterprise_qa_v2
  template_descriptor_version: react_enterprise_qa.v2
  checkpointer:
    provider: sqlite
    uri: memory

retrieval:
  strategy: single_step
  top_k: 3
  min_score: 0.2

react:
  max_steps: 6
  max_tool_calls: 1
  record_reasoning_summary: true

review:
  mode: auto
  low_risk_fast_path: true

response:
  include_reasoning_summary: true
  include_review_results: true

capabilities:
  tools:
    enabled: true
    file: ./tools.yaml
  memory:
    enabled: true
    provider: local
    scopes:
      case:
        enabled: true
        retention_days: 30
        max_records: 8
        allow_restricted: false
      user:
        enabled: false
      shared:
        enabled: false
  skills:
    enabled: true
    business_flows:
      - id: general_insurance_specialist
        definition: ./skills/general_insurance_specialist.yaml
        default: true
      - id: agent_basic_law_consultation
        definition: ./skills/agent_basic_law_consultation.yaml
      - id: product_clause_consultation
        definition: ./skills/product_clause_consultation.yaml
      - id: underwriting_consultation
        definition: ./skills/underwriting_consultation.yaml
      - id: claims_consultation
        definition: ./skills/claims_consultation.yaml
      - id: customer_agent_question_support
        definition: ./skills/customer_agent_question_support.yaml
      - id: agent_performance_activity_lookup
        definition: ./skills/agent_performance_activity_lookup.yaml
```

The final package should declare separate Knowledge Bindings for agent basic law,
product clauses, underwriting and claims procedures, customer support wording, and
performance/report metric definitions. Tool Contracts should expose read-only
business-system and report lookups only.

## Workflow Stage Configuration

`react_enterprise_qa_v2` exposes these stages:

```text
intent_resolution -> plan -> clarification -> retrieval_review -> retrieval
-> model_answer -> tool_review -> tool -> memory -> response
```

The editable Prompt fields are limited to `business_context`,
`task_instructions`, and `output_preferences`. Business-facing values should be
Chinese. Harness prompts, topology, policy, validators, Tool Gateway, trace, and
receipt remain locked by Proof Agent.

### `intent_resolution`

Prompt:

```yaml
business_context: "你正在为保险公司内勤专员理解请求意图。请求可能涉及代理人基本法、产品条款、核保、理赔、客户或代理人问题答复、代理人业绩或活动量查询。请只做审计安全的意图识别，不生成最终答案。"
task_instructions:
  - "识别用户目标、业务领域、已知事实、缺失字段、歧义和风险信号。"
  - "区分知识咨询、授权查数、客户或代理人回复话术、事务性操作请求和权限范围不足。"
  - "只推荐后续动作类别和候选业务流，不产生可执行工具参数或最终答复。"
output_preferences:
  - "输出审计安全的意图摘要，不暴露原始思维链。"
  - "缺失字段用字段名表达，例如 report_period、agent_id、metric。"
```

Context:

```yaml
include_agent_purpose: true
include_recent_conversation_summary: true
include_bound_knowledge_sources: true
include_bound_tools: true
include_policy_outline: true
```

### `plan`

Prompt:

```yaml
business_context: "你正在为内勤专员制定受控业务子计划。计划可以覆盖咨询、查数、两核、客户或代理人问题，但执行必须经过固定的受控 ReAct Workflow。"
task_instructions:
  - "先判断是否需要公共知识、制度条款、授权业务系统记录、报表指标或外部话术草稿。"
  - "查数请求必须明确统计周期、指标、汇总粒度和可管理代理人范围；不能假设权限或默认扩大范围。"
  - "若缺少继续执行所需的最小字段，规划澄清；若请求变更业务状态，规划安全拒答或流程性说明。"
  - "混合问题要拆分为咨询依据、查数依据和话术需求，但不能合并多个业务流的权限。"
output_preferences:
  - "用简短中文概括业务子计划。"
  - "列出下一步需要的证据或只读工具类型，不写原始思维链。"
```

Context:

```yaml
include_agent_purpose: true
include_recent_conversation_summary: true
include_bound_knowledge_sources: true
include_bound_tools: true
include_policy_outline: true
```

### `clarification`

`clarification` does not accept editable Prompt addenda in the current
descriptor. Configure context only:

```yaml
include_agent_purpose: true
include_recent_conversation_summary: true
include_missing_field_schema: true
```

Expected behavior:

- Ask only for the minimum missing field set.
- For lookup, prefer asking for `report_period`, `metric`, `aggregation_level`,
  and optional narrowing filters.
- If a scoped lookup lacks permission context, clarify scope or refuse the lookup
  while still allowing public knowledge consultation when possible.

### `retrieval_review`

Prompt:

```yaml
business_context: "你正在审查是否应使用受控知识检索。知识来源适用于制度、条款、SOP、口径定义和通用业务解释；不能替代实时业务系统记录或报表结果。"
task_instructions:
  - "代理人基本法、产品条款、核保规则、理赔流程和指标口径优先走知识检索。"
  - "保单状态、理赔状态、代理人职级、业绩数值和活动量属于当前状态或报表事实，不能只靠文档回答。"
  - "当来源可能冲突时，标记来源权威顺序和需要复核的冲突点。"
output_preferences:
  - "说明允许或拒绝检索的业务理由。"
  - "优先返回应检索的知识绑定或业务线范围。"
```

Context:

```yaml
include_agent_purpose: true
include_retrieval_intent: true
include_bound_knowledge_sources: true
include_policy_outline: true
```

### `retrieval`

`retrieval` is a governed execution stage and does not accept editable Prompt
addenda. Configure context only:

```yaml
include_retrieval_intent: true
include_bound_knowledge_sources: true
include_source_routing_metadata: true
```

Expected behavior:

- Use bound Knowledge Bindings only.
- Preserve citations and evidence boundaries.
- Treat no accepted evidence as a refusal or clarification path, not a best
  guess.

### `model_answer`

Prompt:

```yaml
business_context: "你正在为保险公司内勤专员生成候选回答。回答必须基于已采信证据、授权只读结果或报表结果，不能做承诺、审批、赔付保证或权限外判断。"
task_instructions:
  - "先给结论或建议，再给依据，再给边界或缺失信息；只有触发对外回复时才生成外部话术草稿。"
  - "咨询类回答要说明制度、条款、SOP 或业务记录依据，以及适用条件。"
  - "查数类回答要说明统计周期、范围、指标口径、筛选条件和汇总粒度。"
  - "来源冲突时明确列出冲突，不自行调和成一个新结论。"
  - "不得承诺承保、赔付、保全、佣金调整、客户通知或任何状态变更。"
output_preferences:
  - "中文、简洁、面向内勤专员。"
  - "必要时使用小标题：结论/建议、依据、边界/缺失信息、对外话术草稿。"
  - "引用来源使用安全标签，不暴露内部工具名、参数、规则编号或审核细节。"
```

Context:

```yaml
include_agent_purpose: true
include_recent_conversation_summary: true
include_evidence_summary: true
include_citation_requirements: true
include_response_disclosure_policy: true
```

### `tool_review`

Prompt:

```yaml
business_context: "你正在审查只读工具提议。工具只能查询当前专员可管理代理人范围内的业务记录或报表数据，不能执行任何业务状态变更。"
task_instructions:
  - "查数工具必须具备权限上下文、统计周期、指标和汇总粒度；用户筛选条件只能缩小范围。"
  - "保单、理赔、客户或代理人记录查询必须具备稳定标识或受控筛选条件。"
  - "拒绝或澄清承保审批、理赔结案、保全变更、佣金调整、外呼发送、工单创建等事务性操作。"
  - "工具参数只能使用 Tool Contract 允许的字段；不得生成令牌、密码、手机号等敏感参数。"
output_preferences:
  - "权限和风险判断保持审计安全。"
  - "清楚说明允许、拒绝或需要澄清的原因。"
```

Context:

```yaml
include_agent_purpose: true
include_tool_proposal: true
include_tool_contract_summary: true
include_policy_outline: true
include_approval_requirements: true
```

### `tool`

`tool` is a Tool Gateway execution stage and does not accept editable Prompt
addenda. Configure context only:

```yaml
include_tool_contract_summary: true
include_approval_state: true
include_parameter_bounds: true
```

Expected behavior:

- Execute only registered, read-only, parameter-bounded tools.
- Denied or unsupported parameters fail closed.
- Tool results are redacted and projected as authorized support, not memory.

### `memory`

`memory` does not accept editable Prompt addenda in the current descriptor.
Configure context only:

```yaml
include_agent_purpose: true
include_memory_scope: true
include_memory_denylist_summary: true
include_recent_conversation_summary: true
```

Expected behavior:

- Store current-case focus, clarified filters, period, metric, business line, and
  response-format preference only.
- Do not store customer identity facts, agent identity facts, policy status,
  claim status, report values, tool payloads, raw evidence, or raw transcripts.

### `response`

`response` is a projection stage and does not accept editable Prompt addenda.
Configure context only:

```yaml
include_agent_purpose: true
include_outcome: true
include_governance_summary: true
include_response_disclosure_policy: true
```

Expected behavior:

- Return the Institution Specialist Response Projection.
- Include governance details only when response settings and caller projection
  allow them.
- Include External Wording Draft only when triggered.

## Suggested `workflow.stages[]` YAML

```yaml
workflow:
  runtime: langgraph
  template: react_enterprise_qa_v2
  template_descriptor_version: react_enterprise_qa.v2
  checkpointer:
    provider: sqlite
    uri: memory
  stages:
    - id: intent_resolution
      prompt:
        business_context: "你正在为保险公司内勤专员理解请求意图。请求可能涉及代理人基本法、产品条款、核保、理赔、客户或代理人问题答复、代理人业绩或活动量查询。请只做审计安全的意图识别，不生成最终答案。"
        task_instructions:
          - "识别用户目标、业务领域、已知事实、缺失字段、歧义和风险信号。"
          - "区分知识咨询、授权查数、客户或代理人回复话术、事务性操作请求和权限范围不足。"
          - "只推荐后续动作类别和候选业务流，不产生可执行工具参数或最终答复。"
        output_preferences:
          - "输出审计安全的意图摘要，不暴露原始思维链。"
          - "缺失字段用字段名表达，例如 report_period、agent_id、metric。"
      context:
        include_agent_purpose: true
        include_recent_conversation_summary: true
        include_bound_knowledge_sources: true
        include_bound_tools: true
        include_policy_outline: true
    - id: plan
      prompt:
        business_context: "你正在为内勤专员制定受控业务子计划。计划可以覆盖咨询、查数、两核、客户或代理人问题，但执行必须经过固定的受控 ReAct Workflow。"
        task_instructions:
          - "先判断是否需要公共知识、制度条款、授权业务系统记录、报表指标或外部话术草稿。"
          - "查数请求必须明确统计周期、指标、汇总粒度和可管理代理人范围；不能假设权限或默认扩大范围。"
          - "若缺少继续执行所需的最小字段，规划澄清；若请求变更业务状态，规划安全拒答或流程性说明。"
          - "混合问题要拆分为咨询依据、查数依据和话术需求，但不能合并多个业务流的权限。"
        output_preferences:
          - "用简短中文概括业务子计划。"
          - "列出下一步需要的证据或只读工具类型，不写原始思维链。"
      context:
        include_agent_purpose: true
        include_recent_conversation_summary: true
        include_bound_knowledge_sources: true
        include_bound_tools: true
        include_policy_outline: true
    - id: clarification
      context:
        include_agent_purpose: true
        include_recent_conversation_summary: true
        include_missing_field_schema: true
    - id: retrieval_review
      prompt:
        business_context: "你正在审查是否应使用受控知识检索。知识来源适用于制度、条款、SOP、口径定义和通用业务解释；不能替代实时业务系统记录或报表结果。"
        task_instructions:
          - "代理人基本法、产品条款、核保规则、理赔流程和指标口径优先走知识检索。"
          - "保单状态、理赔状态、代理人职级、业绩数值和活动量属于当前状态或报表事实，不能只靠文档回答。"
          - "当来源可能冲突时，标记来源权威顺序和需要复核的冲突点。"
        output_preferences:
          - "说明允许或拒绝检索的业务理由。"
          - "优先返回应检索的知识绑定或业务线范围。"
      context:
        include_agent_purpose: true
        include_retrieval_intent: true
        include_bound_knowledge_sources: true
        include_policy_outline: true
    - id: retrieval
      context:
        include_retrieval_intent: true
        include_bound_knowledge_sources: true
        include_source_routing_metadata: true
    - id: model_answer
      prompt:
        business_context: "你正在为保险公司内勤专员生成候选回答。回答必须基于已采信证据、授权只读结果或报表结果，不能做承诺、审批、赔付保证或权限外判断。"
        task_instructions:
          - "先给结论或建议，再给依据，再给边界或缺失信息；只有触发对外回复时才生成外部话术草稿。"
          - "咨询类回答要说明制度、条款、SOP 或业务记录依据，以及适用条件。"
          - "查数类回答要说明统计周期、范围、指标口径、筛选条件和汇总粒度。"
          - "来源冲突时明确列出冲突，不自行调和成一个新结论。"
          - "不得承诺承保、赔付、保全、佣金调整、客户通知或任何状态变更。"
        output_preferences:
          - "中文、简洁、面向内勤专员。"
          - "必要时使用小标题：结论/建议、依据、边界/缺失信息、对外话术草稿。"
          - "引用来源使用安全标签，不暴露内部工具名、参数、规则编号或审核细节。"
      context:
        include_agent_purpose: true
        include_recent_conversation_summary: true
        include_evidence_summary: true
        include_citation_requirements: true
        include_response_disclosure_policy: true
    - id: tool_review
      prompt:
        business_context: "你正在审查只读工具提议。工具只能查询当前专员可管理代理人范围内的业务记录或报表数据，不能执行任何业务状态变更。"
        task_instructions:
          - "查数工具必须具备权限上下文、统计周期、指标和汇总粒度；用户筛选条件只能缩小范围。"
          - "保单、理赔、客户或代理人记录查询必须具备稳定标识或受控筛选条件。"
          - "拒绝或澄清承保审批、理赔结案、保全变更、佣金调整、外呼发送、工单创建等事务性操作。"
          - "工具参数只能使用 Tool Contract 允许的字段；不得生成令牌、密码、手机号等敏感参数。"
        output_preferences:
          - "权限和风险判断保持审计安全。"
          - "清楚说明允许、拒绝或需要澄清的原因。"
      context:
        include_agent_purpose: true
        include_tool_proposal: true
        include_tool_contract_summary: true
        include_policy_outline: true
        include_approval_requirements: true
    - id: tool
      context:
        include_tool_contract_summary: true
        include_approval_state: true
        include_parameter_bounds: true
    - id: memory
      context:
        include_agent_purpose: true
        include_memory_scope: true
        include_memory_denylist_summary: true
        include_recent_conversation_summary: true
    - id: response
      context:
        include_agent_purpose: true
        include_outcome: true
        include_governance_summary: true
        include_response_disclosure_policy: true
```

## Business Flow Skill Pack Configuration

Use package-local Skill Pack definitions under `skills/`. Intent Resolution sees
only routing-safe summaries. After Control Plane admission, the selected pack's
addenda are appended to `plan`, `retrieval_review`, `tool_review`, and
`model_answer` where configured.

### Binding Summary

```yaml
capabilities:
  skills:
    enabled: true
    business_flows:
      - id: general_insurance_specialist
        definition: ./skills/general_insurance_specialist.yaml
        default: true
      - id: agent_basic_law_consultation
        definition: ./skills/agent_basic_law_consultation.yaml
      - id: product_clause_consultation
        definition: ./skills/product_clause_consultation.yaml
      - id: underwriting_consultation
        definition: ./skills/underwriting_consultation.yaml
      - id: claims_consultation
        definition: ./skills/claims_consultation.yaml
      - id: customer_agent_question_support
        definition: ./skills/customer_agent_question_support.yaml
      - id: agent_performance_activity_lookup
        definition: ./skills/agent_performance_activity_lookup.yaml
```

### `general_insurance_specialist`

Use as safe default for broad insurance staff consultation when no narrower pack
is confidently admitted. It must not broaden data scope or tool authority.

```yaml
schema_version: business_flow_skill_pack.v1
id: general_insurance_specialist
label: General Insurance Specialist
description: "处理一般保险内勤咨询和无法唯一归类但仍在受控范围内的问题。"
intent_patterns:
  - 一般咨询
  - 保险业务问题
  - 业务规则
  - 流程说明
admission:
  min_confidence: 0.35
  require_authorization_context: false
knowledge_binding_refs:
  - general_insurance_knowledge
policy_rule_refs:
  - answering.require_evidence_or_authorized_read
stage_prompt_addenda:
  plan:
    business_context: "该业务流是安全默认流，只能处理通用咨询和流程解释，不能扩大查数、客户记录或代理人记录权限。"
    task_instructions:
      - "如果问题实际需要具体业务记录或报表数据，转为澄清或拒绝权限外查询。"
  model_answer:
    output_preferences:
      - "默认给内勤专员简短结论和依据；没有证据时明确说明无法支持。"
```

### `agent_basic_law_consultation`

Use for agent basic law, rank assessment, qualification, commission rule
explanation, activity requirements, and rule-based progress interpretation.

```yaml
schema_version: business_flow_skill_pack.v1
id: agent_basic_law_consultation
label: Agent Basic Law Consultation
description: "解答代理人基本法、职级、考核、佣金规则和资格进度相关咨询。"
intent_patterns:
  - 代理人基本法
  - 基本法
  - 职级考核
  - 晋升
  - 维持考核
  - 佣金规则
  - 资格进度
admission:
  min_confidence: 0.65
  require_authorization_context: false
knowledge_binding_refs:
  - agent_basic_law_docs
  - metric_definition_docs
policy_rule_refs:
  - answering.require_evidence_or_authorized_read
stage_prompt_addenda:
  plan:
    business_context: "该业务流处理代理人基本法咨询。重点是制度解释、适用条件、缺失事实和是否需要另行查数。"
    task_instructions:
      - "区分制度解释和具体代理人当前资格判断；后者如果需要实时数据，应提出只读查数需求。"
      - "不要把制度规则解释成对某个代理人的最终晋升、降级或佣金调整决定。"
  retrieval_review:
    business_context: "代理人基本法、考核口径和佣金规则应优先检索正式制度或口径文件。"
    task_instructions:
      - "检索制度章节、适用期间、职级条件和指标定义。"
  model_answer:
    output_preferences:
      - "说明制度名称、适用对象、关键条件和仍需核对的数据项。"
      - "如涉及具体代理人资格，标注这是规则解释或数据支持建议，不是最终人事或佣金决定。"
```

### `product_clause_consultation`

Use for product clause interpretation, responsibility scope, exclusions, waiting
periods, benefit definitions, and product explanation support.

```yaml
schema_version: business_flow_skill_pack.v1
id: product_clause_consultation
label: Product Clause Consultation
description: "解答保险产品条款、保障责任、除外责任、等待期和产品解释问题。"
intent_patterns:
  - 产品条款
  - 保障责任
  - 除外责任
  - 等待期
  - 赔付范围
  - 产品解释
  - 产品咨询
  - 产品说明
  - 产品介绍
  - 产品优缺点
  - 优缺点
  - 卖点
  - 不足
admission:
  min_confidence: 0.65
  require_authorization_context: false
knowledge_binding_refs:
  - product_clause_docs
policy_rule_refs:
  - answering.require_evidence_or_authorized_read
  - response.no_coverage_or_payment_guarantee
stage_prompt_addenda:
  plan:
    business_context: "该业务流处理产品条款解释。重点是条款原文、适用条件、除外和不能作出的承诺。"
    task_instructions:
      - "判断问题是通用条款解释，还是要求对具体客户作保障或赔付结论。"
      - "具体客户结论必须依赖授权记录和理赔或核保流程，不能仅凭条款片段承诺。"
  retrieval_review:
    business_context: "产品条款问题必须检索正式条款、产品说明或合规发布材料。"
    task_instructions:
      - "优先检索条款名称、责任章节、除外章节、等待期和定义条款。"
  model_answer:
    output_preferences:
      - "用“条款含义、适用条件、边界提醒”的顺序回答。"
      - "避免生成保障确定、赔付金额或法律意见式表述。"
```

### `underwriting_consultation`

Use for underwriting rules, health disclosure, occupational class, extra premium,
exclusion, postponement, decline explanation, and underwriting material
preparation.

```yaml
schema_version: business_flow_skill_pack.v1
id: underwriting_consultation
label: Underwriting Consultation
description: "解答核保规则、健康告知、职业类别、加费、除外、延期和拒保说明相关问题。"
intent_patterns:
  - 核保
  - 健康告知
  - 职业类别
  - 加费
  - 除外
  - 延期
  - 拒保
admission:
  min_confidence: 0.68
  require_authorization_context: false
knowledge_binding_refs:
  - underwriting_rule_docs
policy_rule_refs:
  - answering.require_evidence_or_authorized_read
  - tools.transactional_insurance_operation.deny
stage_prompt_addenda:
  plan:
    business_context: "该业务流处理承保前核保咨询。重点是核保规则解释、材料要求和不能替代核保结论。"
    task_instructions:
      - "区分核保规则咨询、材料准备建议和具体承保决定。"
      - "涉及具体投保件时，如需要保单或投保记录，应要求稳定标识和授权范围。"
  retrieval_review:
    business_context: "核保咨询应检索核保规则、职业分类、健康告知和材料清单。"
  model_answer:
    output_preferences:
      - "说明规则依据、可能需要的补充材料和需要人工或系统核保确认的边界。"
      - "不得承诺可承保、费率、除外条件或最终核保结论。"
```

### `claims_consultation`

Use for claims process, required materials, liability assessment explanation,
deductible, waiting period, claim status explanation, and pending claim wording.

```yaml
schema_version: business_flow_skill_pack.v1
id: claims_consultation
label: Claims Consultation
description: "解答理赔流程、材料、责任认定说明、免赔、等待期、理赔状态解释和待决案件话术。"
intent_patterns:
  - 理赔
  - 赔案
  - 理赔材料
  - 待决
  - 拒赔
  - 免赔
  - 理赔进度
admission:
  min_confidence: 0.68
  require_authorization_context: false
knowledge_binding_refs:
  - claims_sop_docs
  - product_clause_docs
tool_contract_refs:
  - claim_record_lookup
policy_rule_refs:
  - answering.require_evidence_or_authorized_read
  - tools.read_only_institution_business.allow
  - response.no_coverage_or_payment_guarantee
stage_prompt_addenda:
  plan:
    business_context: "该业务流处理理赔咨询。流程和材料用知识来源，当前赔案状态用授权只读记录。"
    task_instructions:
      - "如果用户询问具体赔案进度或待决原因，检查是否有 claim_id 和权限范围。"
      - "如果缺少赔案标识，仍可先回答通用理赔流程或材料要求。"
  retrieval_review:
    business_context: "理赔流程、材料和条款责任说明优先检索 SOP 和条款；当前状态不能只靠文档回答。"
  tool_review:
    business_context: "具体赔案状态查询只能使用只读赔案工具，并要求稳定赔案标识和权限范围。"
  model_answer:
    output_preferences:
      - "区分流程解释、条款依据和当前赔案状态。"
      - "待决或拒赔相关话术应保守表达，不承诺赔付结果或时限。"
```

### `customer_agent_question_support`

Use when the staff member asks how to answer a customer or agent, or when the
request clearly asks for external wording.

```yaml
schema_version: business_flow_skill_pack.v1
id: customer_agent_question_support
label: Customer Or Agent Question Support
description: "为客户或代理人问题生成内勤处理建议，并在触发条件满足时生成可审核的外部话术草稿。"
intent_patterns:
  - 怎么回复客户
  - 怎么回复代理人
  - 客户问
  - 代理人问
  - 话术
  - 对外说明
admission:
  min_confidence: 0.62
  require_authorization_context: false
knowledge_binding_refs:
  - customer_agent_wording_docs
  - product_clause_docs
  - claims_sop_docs
policy_rule_refs:
  - answering.require_evidence_or_authorized_read
  - response.external_wording_safety
stage_prompt_addenda:
  plan:
    business_context: "该业务流处理客户或代理人问题支持。先给内勤处理建议，只有明确需要对外回复时才生成外部话术草稿。"
    task_instructions:
      - "判断请求是否真的触发外部话术；普通咨询不自动生成话术。"
      - "外部话术只能基于已采信依据或授权记录，不能暴露内部治理细节。"
  retrieval_review:
    business_context: "对外话术应检索正式条款、流程说明、常见问答或合规话术来源。"
  model_answer:
    output_preferences:
      - "先输出内勤处理建议，再在需要时输出“对外话术草稿”。"
      - "外部话术应自然、克制、可人工审核，不包含内部系统名、参数、权限或审核细节。"
```

### `agent_performance_activity_lookup`

Use for authorized lookup of managed agents' performance, activity, quality, and
management metrics.

```yaml
schema_version: business_flow_skill_pack.v1
id: agent_performance_activity_lookup
label: Agent Performance And Activity Lookup
description: "查询当前内勤专员可管理代理人范围内的业绩、活动量、质量和目标进度指标。"
intent_patterns:
  - 查业绩
  - 活动量
  - 拜访量
  - 保费
  - FYC
  - 继续率
  - 转化率
  - 达成率
  - 名下代理人
admission:
  min_confidence: 0.72
  require_authorization_context: true
knowledge_binding_refs:
  - metric_definition_docs
tool_contract_refs:
  - agent_performance_lookup
  - agent_activity_lookup
  - agent_profile_lookup
policy_rule_refs:
  - tools.managed_agent_scope_read.allow
  - answering.require_evidence_or_authorized_read
stage_prompt_addenda:
  plan:
    business_context: "该业务流处理授权查数。默认范围是当前专员可管理代理人集合，用户只能通过机构、团队、代理人、业务线等条件缩小范围。"
    task_instructions:
      - "必须确认 report_period、metric 和 aggregation_level；缺少时先澄清。"
      - "仅支持 V1 指标集合，不支持的指标不能临时改写成相近指标。"
      - "如果用户要求跨权限范围查询，规划拒绝或要求重新限定范围。"
  retrieval_review:
    business_context: "查数前可检索指标定义和报表口径，但实际数值必须来自授权报表或业务系统。"
    task_instructions:
      - "检索 metric_definition_docs 用于解释指标口径。"
  tool_review:
    business_context: "查数工具必须是只读报表或代理人记录查询，参数必须被 Tool Contract 允许且不超过可管理代理人范围。"
    task_instructions:
      - "允许参数包括 institution_id、branch_id、team_id、agent_id、business_line、report_period、metric、aggregation_level。"
      - "拒绝手机号、密码、令牌、自由 SQL、写操作或导出全量明细。"
  model_answer:
    output_preferences:
      - "回答必须显示统计周期、范围、指标口径、筛选条件和汇总粒度。"
      - "如果查数结果为空，说明是无数据、权限不足、字段缺失还是工具失败。"
      - "不得把报表结果写成长期记忆或作为未来查询的事实来源。"
```

## Knowledge Binding Design

The Agent should bind knowledge by business authority, not by UI category. This
lets retrieval review and Skill Packs select the right source without changing
Workflow topology.

```yaml
package_knowledge_sources:
  - source_id: agent_management_insurance_knowledge
    name: Agent Management Insurance Knowledge
    provider: local_markdown
    params:
      path: ./knowledge

knowledge_bindings:
  - binding_id: general_insurance_knowledge
    source_ref:
      scope: package
      source_id: agent_management_insurance_knowledge
    alias: general
    failure_mode: advisory
    fusion_weight: 0.6
    top_k: 3
    routing_metadata:
      audience: institution_specialist

  - binding_id: agent_basic_law_docs
    source_ref:
      scope: package
      source_id: agent_management_insurance_knowledge
    alias: agent_basic_law
    failure_mode: required
    fusion_weight: 1.0
    top_k: 5
    routing_metadata:
      document_family: agent_basic_law
      authority: formal_rule

  - binding_id: product_clause_docs
    source_ref:
      scope: package
      source_id: agent_management_insurance_knowledge
    alias: product_clause
    failure_mode: required
    fusion_weight: 1.0
    top_k: 5
    routing_metadata:
      document_family: product_clause
      authority: policy_wording

  - binding_id: underwriting_rule_docs
    source_ref:
      scope: package
      source_id: agent_management_insurance_knowledge
    alias: underwriting_rules
    failure_mode: required
    fusion_weight: 1.0
    top_k: 5
    routing_metadata:
      document_family: underwriting_rule
      authority: underwriting_sop

  - binding_id: claims_sop_docs
    source_ref:
      scope: package
      source_id: agent_management_insurance_knowledge
    alias: claims_sop
    failure_mode: required
    fusion_weight: 1.0
    top_k: 5
    routing_metadata:
      document_family: claims_sop
      authority: claims_sop

  - binding_id: customer_agent_wording_docs
    source_ref:
      scope: package
      source_id: agent_management_insurance_knowledge
    alias: external_wording
    failure_mode: advisory
    fusion_weight: 0.8
    top_k: 3
    routing_metadata:
      document_family: external_wording
      authority: approved_wording

  - binding_id: metric_definition_docs
    source_ref:
      scope: package
      source_id: agent_management_insurance_knowledge
    alias: metric_definitions
    failure_mode: required
    fusion_weight: 1.0
    top_k: 3
    routing_metadata:
      document_family: metric_definition
      authority: report_basis
```

## Tool Contract Design

V1 tools are read-only. Policy-authorized read-only tools should not require
human approval when PolicyEngine verifies scope and parameters, but they still
run through Tool Gateway and trace.

```yaml
tools:
  - name: agent_performance_lookup
    description: "Read-only lookup for managed-agent performance metrics."
    transport: local
    handler: ./tools.py:agent_performance_lookup
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters:
      - institution_id
      - branch_id
      - team_id
      - agent_id
      - business_line
      - report_period
      - metric
      - aggregation_level
    denied_parameters:
      - access_token
      - staff_password
      - provider_api_key
      - write_action
      - sql
      - export_all
      - agent_phone

  - name: agent_activity_lookup
    description: "Read-only lookup for managed-agent activity metrics."
    transport: local
    handler: ./tools.py:agent_activity_lookup
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters:
      - institution_id
      - branch_id
      - team_id
      - agent_id
      - business_line
      - report_period
      - metric
      - aggregation_level
    denied_parameters:
      - access_token
      - staff_password
      - provider_api_key
      - write_action
      - sql
      - export_all
      - agent_phone

  - name: agent_profile_lookup
    description: "Read-only lookup for managed-agent profile handles and grade facts."
    transport: local
    handler: ./tools.py:agent_profile_lookup
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters:
      - institution_id
      - branch_id
      - team_id
      - agent_id
      - business_line
    denied_parameters:
      - access_token
      - staff_password
      - provider_api_key
      - write_action
      - agent_phone

  - name: policy_record_lookup
    description: "Read-only policy record lookup for authorized staff scope."
    transport: local
    handler: ./tools.py:policy_record_lookup
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters:
      - institution_id
      - branch_id
      - business_line
      - policy_id
    denied_parameters:
      - access_token
      - staff_password
      - provider_api_key
      - write_action

  - name: claim_record_lookup
    description: "Read-only claim record lookup for authorized staff scope."
    transport: local
    handler: ./tools.py:claim_record_lookup
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters:
      - institution_id
      - branch_id
      - business_line
      - claim_id
    denied_parameters:
      - access_token
      - staff_password
      - provider_api_key
      - write_action

  - name: customer_profile_lookup
    description: "Read-only customer profile handle lookup for authorized staff scope."
    transport: local
    handler: ./tools.py:customer_profile_lookup
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters:
      - institution_id
      - branch_id
      - business_line
      - customer_id
    denied_parameters:
      - access_token
      - staff_password
      - provider_api_key
      - write_action
      - customer_phone
```

## Policy Configuration

Recommended policy intent:

The YAML below follows the repository's policy file shape, but several
conditions such as `managed_agent_scope_required`, `allowed_metrics`,
`deny_commitments`, and `external_wording_must_hide` are target governance
conditions. Before treating them as fully deterministic enforcement, implement
or bind the matching PolicyEngine evaluators or validators. The design intent is
still important: these rules define the control points the Agent must satisfy.

```yaml
rules:
  - rule_id: answering.require_evidence_or_authorized_read
    enforcement_point: before_answer
    condition:
      require_retrieval: true
      min_evidence_count: 1
      require_citations: true
      allow_authorized_tool_result: true
    decision:
      on_pass: allow
      on_fail: deny
    reason_template: "Insurance specialist answers require accepted evidence or authorized read support."

  - rule_id: tools.managed_agent_scope_read.allow
    enforcement_point: before_tool_call
    condition:
      read_only: true
      institution_authorization_required: true
      managed_agent_scope_required: true
      allowed_metrics:
        - premium_income
        - first_year_commission
        - policy_count
        - visit_count
        - proposal_count
        - meeting_count
        - persistency_rate
        - conversion_rate
        - active_agent_count
        - qualified_agent_count
        - target_achievement_rate
      required_parameters:
        - report_period
        - metric
        - aggregation_level
    decision:
      on_match: allow
      on_fail: deny
    reason_template: "Managed-agent lookup requires read-only scope, allowed metric, period, aggregation level, and institution authorization context."

  - rule_id: tools.read_only_institution_business.allow
    enforcement_point: before_tool_call
    condition:
      read_only: true
      institution_authorization_required: true
    decision:
      on_match: allow
      on_fail: deny
    reason_template: "Institution business lookups require read-only scope and institution authorization context."

  - rule_id: tools.transactional_insurance_operation.deny
    enforcement_point: before_tool_call
    condition:
      deny_actions:
        - underwriting_approval
        - claim_approval
        - claim_settlement
        - policy_endorsement
        - policy_cancellation
        - premium_adjustment
        - commission_adjustment
        - outbound_message
        - external_work_item
        - data_export
    decision:
      on_match: deny
      on_pass: allow
    reason_template: "Transactional Insurance Operation requests are out of this Agent's supported scope."

  - rule_id: response.no_coverage_or_payment_guarantee
    enforcement_point: before_answer
    condition:
      deny_commitments:
        - coverage_guarantee
        - payment_guarantee
        - underwriting_decision
        - claim_decision
        - commission_adjustment_decision
    decision:
      on_match: deny
      on_pass: allow
    reason_template: "The Agent may explain supported facts but must not make final coverage, payment, underwriting, claim, or commission decisions."

  - rule_id: response.external_wording_safety
    enforcement_point: before_answer
    condition:
      external_wording_must_hide:
        - internal_system_name
        - tool_contract_identifier
        - raw_tool_parameter
        - authorization_detail
        - policy_rule_name
        - review_result
        - trace_detail
        - receipt_detail
    decision:
      on_pass: allow
      on_fail: deny
    reason_template: "External wording drafts must expose only customer-safe or agent-safe business explanation."

  - rule_id: memory.institution_case_only
    enforcement_point: before_memory_write
    condition:
      deny_fields:
        - customer_identity_fact
        - agent_identity_fact
        - policy_status
        - claim_status
        - report_value
        - raw_tool_payload
        - raw_evidence
        - raw_transcript
    decision:
      on_match: deny
      on_pass: allow
    reason_template: "Institution specialist memory stores current-case context only."
```

## Runtime Parameters

Recommended production defaults:

```yaml
retrieval:
  strategy: single_step
  top_k: 5
  min_score: 0.25
  max_queries: 3

react:
  max_steps: 6
  max_tool_calls: 1
  record_reasoning_summary: true
  planner:
    model_source: shared
    connection_id: model_planner_default
    params:
      temperature: 0
      max_output_tokens: 700
      timeout_seconds: 12

model:
  model_source: shared
  connection_id: model_answer_default
  params:
    temperature: 0
    max_output_tokens: 900
    timeout_seconds: 15

review:
  mode: auto
  low_risk_fast_path: true
  subagent:
    model_source: shared
    connection_id: model_review_default
    fail_closed: true
    params:
      temperature: 0
      max_output_tokens: 500
      timeout_seconds: 8

response:
  include_reasoning_summary: true
  include_review_results: true
```

For deterministic local fixtures, keep the existing `deterministic` providers.
For production packages, use Shared Model Connections or custom model config
with environment credential references only.

## Output Preferences By Scenario

### Consultation

```text
结论/建议：
  用 1-3 句给出专员可执行结论。

依据：
  列制度、条款、SOP、章节或引用点，以及适用条件。

边界/缺失信息：
  说明不支持的承诺、缺失事实、需要系统记录或需要人工复核的事项。
```

### Lookup

```text
结论/建议：
  概括查数结果或下一步处理建议。

依据：
  统计周期：...
  查询范围：...
  指标口径：...
  汇总粒度：...
  筛选条件：...

边界/缺失信息：
  说明无数据、权限不足、缺少字段、指标不支持或工具失败。
```

### External Wording Draft

```text
对外话术草稿：
  建议您可以这样回复：
  “……”

内部提醒：
  该话术仅供专员审核后使用，不包含内部系统、工具、权限或审核细节。
```

## Validation Cases

Minimum deterministic validation cases:

- Basic law consultation answers with citations and no tool call.
- Product clause question answers with clause basis and no coverage guarantee.
- Underwriting question explains rule boundary and refuses final underwriting
  decision.
- Claims pending question asks for claim id when current status is requested.
- Customer or agent wording request produces External Wording Draft.
- Ordinary consultation does not produce External Wording Draft.
- Managed-agent performance lookup with period and metric executes read-only
  lookup and reports scope.
- Managed-agent lookup without `report_period` requests clarification.
- Unsupported metric is clarified or refused, not reinterpreted.
- Cross-scope lookup request fails closed without defaulting to a broader pack.
- Transactional request such as commission adjustment or claim approval is not
  executed.
