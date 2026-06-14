# Policy Engine (策略引擎)

`PolicyEngine` 是 Control Envelope 的核心。

它将企业规则转化为在特定执行点 (enforcement points) 的类型化决策。每一个决策都会被写入 trace 并在 Governance Receipt 中总结。

## 执行点 (Enforcement Points)

Proof Agent 使用显式的执行点：

```text
before_retrieval
  决定 Agent 是否可以检索知识库。

before_answer
  决定证据是否足以生成回答。

before_tool_call
  决定一个工具调用是被允许、拒绝，还是需要审批。

before_memory_write
  决定生成的信息是否可以被写入会话记忆 (session memory)。

before_model_call
  决定在当前的 provider、模型、成本类别、预估 tokens、stream 设置和证据状态下，是否允许进行模型调用。
```

## 决策 (Decisions)

```text
allow
  继续执行工作流。

deny
  停止动作并返回一个安全的响应。

require_approval
  在一个显式的审批状态暂停。

escalate
  停止自动化处理，路由给人类或更高级别的工作流。
```

每个决策包含：

- decision type (决策类型)
- enforcement point (执行点)
- reason (原因)
- policy rule id (策略规则 ID)
- 相关证据或工具的元数据
- trace event id

## 规则意图示例

```yaml
answering:
  require_retrieval: true
  require_citations: true
  min_evidence_count: 2
  on_weak_evidence: deny

tools:
  customer_lookup:
    approval: required
    allowed_fields:
      - customer_id
      - policy_id

memory:
  allow_session_summary: true
  deny_personal_sensitive_fields: true
```

确切的 YAML 可能会演变，但合约应当保持稳定：策略总是产出类型化的、可追踪的决策。

## 最小策略 Schema

v1 策略文件必须支持带有明确 id 和执行点的规则列表：

```yaml
rules:
  - rule_id: answering.require_retrieval
    enforcement_point: before_answer
    condition:
      require_retrieval: true
      min_evidence_count: 2
      require_citations: true
    decision:
      on_pass: allow
      on_fail: deny
    reason_template: "回答需要至少 2 个带有引用且被接受的证据块。"

  - rule_id: tools.customer_lookup.approval
    enforcement_point: before_tool_call
    condition:
      tool_name: customer_lookup
    decision:
      on_match: require_approval
    reason_template: "customer_lookup 在执行前需要人类审批。"

  - rule_id: memory.deny_sensitive_fields
    enforcement_point: before_memory_write
    condition:
      deny_fields:
        - access_token
        - customer_phone
    decision:
      on_match: deny
      on_pass: allow
    reason_template: "会话记忆不能存储敏感字段。"

  - rule_id: model.remote_budget
    enforcement_point: before_model_call
    condition:
      cost_class: remote
      max_estimated_tokens: 4000
      stream: false
    decision:
      on_pass: allow
      on_fail: deny
    reason_template: "远程模型调用必须保持在配置的预算和流策略内。"
```

每个规则必须包含：

- `rule_id`
- `enforcement_point`
- `condition`
- `decision`
- `reason_template`

策略评估必须为其处理的每个执行点发出一个 `policy_decision` trace 事件。

## 设计规则

不要将企业治理分散在各个工作流阶段 (workflow stages) 中。工作流阶段只负责询问策略引擎。策略引擎进行决策。Trace 记录这个决策。
