# 目标任务与可配置 Workflow

[KNOWN | HIGH] 2026-09-12：目标、问询、证据要求和推理复杂度已接入同一个
`react_enterprise_qa_v3`。实现依据为 [ADR-0255](../../adr/0255-compile-goal-driven-workflow-policies.md)，
验证与未交付项见 [实施记录](tdd-adaptive-workflow.md)。

## 使用入口

Dashboard 的 Agent → Workflow 可配置复杂度、问询模式、问询力度、证据要求、各阶段覆盖和预算。
执行预览与运行使用同一个后端编译器；完整十个节点始终可见，并展示执行、条件执行、确定性处理、跳过及原因。
预览绑定当前 Draft revision，不写入草稿。保存节点与策略是一次 CAS 更新；修改 Draft 不改变已发布版本。

Operator Chat 默认仍为普通问答。选择“目标任务”，填写目标和可选验收项后创建并执行。
每个文本验收项转为必需的来源查询；未填写时按整体目标查询。当前必需查询上限为 5，超过后会返回缺口，
不会截断目标。显示的“已验证”表示对应的有界验证器通过，不代表通用语义正确性保证。
任务卡展示目标版本、各项验收、状态、累计调用和 tokens。任务链接保存 `task` 和冻结的 Agent `version`，
可重新打开读取持久状态。必要问询使用文字、选项、布尔或数字字段；回答失败保留输入和幂等键。

暂停、恢复、重新发起过期问询、修改目标和取消都由后端校验状态与版本。
修改目标时已有运行必须先结束；Goal revision 加一，旧问询失效，验收重新验证。
必填答案没有完成前，恢复只回到问询；过期问题重新生成 Question ID，旧问题不能继续回答。
任务完整验收由 Control Plane 判定，用户不能直接把任务改为 `complete`。

## 配置示例

以下是合并到现有 Agent YAML 的可加载策略片段；保留现有 models、capabilities、review 等业务配置。
也可以通过 Dashboard 编辑。`reasoning.effort` 默认省略，避免向未知模型发送不支持的参数。

```yaml
workflow:
  template: react_enterprise_qa_v3
  execution:
    complexity: standard
    ceiling: deep
    auto_escalate: true
    budget:
      max_model_calls: 16
      max_retrieval_calls: 5
      max_tool_calls: 4
      max_total_tokens: 262144
      reserved_output_tokens: 65536
      max_active_seconds: 600

interaction:
  mode: adaptive
  intensity: balanced
  max_rounds: 2
  max_questions_per_round: 1
  unavailable: return_missing_context
  wait_timeout_seconds: 86400
  checkpoints:
    goal: {intensity: thorough, ask_on: [required_context]}
    plan: {ask_on: [scope_change, budget_change]}
    evidence: {ask_on: [applicability_unresolved]}
    tool_input: {ask_on: [required_parameter]}
    finalization: {ask_on: [user_preference_blocking]}

assurance:
  level: grounded
  unknown_required_claim: block
  evidence_conflict: resolve_or_block
  applicability: required
  evidence:
    min_sources: 1
  checkpoints:
    finalization:
      required_metadata: [source_id, document_version]
```

[KNOWN | HIGH] 配置采用严格契约，未知字段、非法枚举、负预算、低于请求复杂度的 ceiling 都会被拒绝。
未提供新策略的普通 Run 保持 legacy 路径。显式目标任务未声明 execution 时使用 standard 的默认总预算。
旧 `response.clarification_level` 仍可用于旧配置；迁移时应删除该字段，由 `interaction.intensity` 统一管理。
如果同时声明且不一致，加载/保存拒绝；不静默选择其中一项。

## 三组相互独立的控制

| 控制 | 选项 | 实际行为 |
|---|---|---|
| 复杂度 | `lite` | 单一必需查询采用确定性规划，跳过可选 memory；Intent、准入、必需查询、工具权限、最终校验保留 |
| 复杂度 | `standard` | 使用现有有界 ReAct 与配置的审查路径 |
| 复杂度 | `deep` | 保留完整规划，并禁用配置中的低风险审查 fast path；`rules_only` 仍按规则，不强行引入模型 |
| 模式 | `autonomous` | 自动处理可选偏好；必要信息不足返回缺口或暂停，不猜必填输入 |
| 模式 | `adaptive` / `interactive` | 根据力度和阶段策略有界问询；interactive 更积极询问可选偏好 |
| 力度 | `minimal` / `balanced` / `thorough` | 调整可选问询；可检索事实优先检索，必需上下文不随力度减少 |
| 证据要求 | `basic` / `grounded` | 保留全部基础检查与事实一致性验证；当前二者共享基础验证器，不宣称额外语义识别能力 |
| 证据要求 | `strict` | 在基础检查上拒绝未评估关键断言；可配置更高来源、时效和元数据要求 |

`lite + strict` 有效；lite 遇到多个必需查询或工具任务时，按 ceiling 自动升级 standard。
禁止升级则返回 `complexity_ceiling_exceeded`，不删验收项。模型推理 effort 与流程复杂度分别设置；
`workflow.execution.reasoning.effort` 可选 `off / low / medium / high / xhigh / max`，
须符合已准入的 provider/model 能力表。不支持的组合在网络请求前拒绝；DeepSeek 的有效映射记录在 Trace。
实现与来源见 `proof_agent/capabilities/models/reasoning.py` 和 [Harness 调研](../../research/2026-09-12-codex-deepseek-harness-sources.md)。

`assurance.evidence` 和各 checkpoint 要求合并取更严格值，后续阶段不能降低之前的必需要求。
`min_sources` 按来源身份与规范化相同内容去重；这不能识别所有改写转载或证明机构独立性。
`max_age_days` 检查来源的 `effective_date`，不用检索时间替代。支持声明必需
`source_id / document_version / effective_date` 元数据。明确不适用、未知适用性和未解决冲突均阻止回答。
未标注的适用范围、隐含冲突和一般语义仍需要业务证据与额外验证，配置等级不自动产生这些能力。

## 预算与验收

共享预算覆盖 Intent、Planner、Review、Answer、Repair 的实际模型调用，逐次 Knowledge binding
查询和工具实际执行。调用前预留输出，调用后结算。缺少 usage 保留保守预留和 unknown 计数；
丢失整个运行消费记录则 tokens 为 unknown，暂停并阻止以新预算继续。等待人工输入不占活动执行时间。
显式配置总预算时关闭 SDK 隐式重试；调用时间也受剩余活动预算约束。

Task 的多次 Run 累计资源，不因回答、恢复、Goal 修订或重连清零。预算耗尽保留任务与未完成验收，
Task 为 paused，Run 保留 `REFUSED_NO_EVIDENCE` 及原因。当前不支持对冻结 Task 原地扩预算；
需要调整发布配置后明确创建新任务。不能凭 UI 的“恢复”把 unknown 消费当作零。

验收支持 `source_support`（具体查询与准入证据绑定）、`answer_coverage`（指定文字同时出现在答案与证据）、
`verified_tool`（指定工具步骤与已验证报告）。缺少验证依据的自然语言标准保持 `unassessed`。
用户输入仅补充上下文，不成为 Accepted Evidence 或工具授权；工具只接收 schema 标记为 USER_SUPPLIED 的字段。

## Task API 与持久恢复

| 接口 | 用途 |
|---|---|
| `POST /api/tasks` | `agent_id/objective/acceptance_criteria/constraints/required_context`；创建与执行，带 `Idempotency-Key` |
| `GET /api/tasks/{task_id}` | 携带 `agent_id/agent_version` 读取本人任务及已有运行结果 |
| `POST /api/tasks/{task_id}/answers` | 携带 `question_id/expected_goal_revision/values/idempotency_key` 和 Agent 身份 |
| `POST /api/tasks/{task_id}/resume` | 派发已提交的恢复意图，或恢复暂停/过期问询；不复用其他 Run 的证明 |
| `PATCH /api/tasks/{task_id}/goal` | `expected_version` 与完整新 Goal；Goal revision 独立递增 |
| `PATCH /api/tasks/{task_id}/phase` | `expected_version` 与允许的暂停、恢复、取消状态；禁止人工完成 |

所有写操作使用现有 `RUN_SUBMIT` 权限；读取使用 `RUN_VIEW`；actor 由登录会话解析，不能由请求指定。
生产入口继承 OIDC/CSRF。PostgreSQL migration `0025_workflow_tasks` 增加 Task snapshot 和恢复 outbox。
Task 回答与恢复意图同一次 CAS；队列发布、Run 绑定和 outbox 标记同一事务；成功更新与 Run/artifact 可见性
使用同一 fencing 事务。失败或租约回收会标记未知消费，过期 worker 不可提交任务结果。

当前交付 Task 跨 Run continuation：等待释放 worker，回答立即派发新 Run；请求中断后可通过 `/resume`
恢复持久意图。没有跨用户后台扫描器；同一 Run 的局部恢复、非阻塞问询的并行独立分支仍是后续阶段。
开发适配器使用 SQLite；生产缺少 PostgreSQL 时返回 503，不回退本地文件。Task 原文保留 90 天并在访问时清理，
普通 Trace/Receipt 不写入目标原文、用户字段值、模型推理；只保留受限投影、固定原因码、计数和摘要标识。
