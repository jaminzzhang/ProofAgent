
# 1. 先定义：什么是 Harness Engineering？

## 1.1 一句话定义

**Harness Engineering = 为 AI Agent 设计一套外部“控制系统”，让模型的智能可以被可靠地调用、约束、验证、追踪和复用。**

可以用这个公式理解：

> **Agent = Model + Harness**

模型负责“理解、推理、生成”；Harness 负责“流程、上下文、工具、记忆、权限、校验、回滚、观测”。

Martin Fowler 的文章也提到，Harness 已经被用来泛指 Agent 中“除模型之外的一切”，也就是围绕模型的上下文、工具、流程、反馈和约束系统。([martinfowler.com](https://martinfowler.com/articles/harness-engineering.html "Harness engineering for coding agent users")) Addy Osmani 对这个概念的解释也很直接：原始模型不是 Agent，模型只有被 Harness 赋予状态、工具执行、反馈循环和可执行约束之后，才真正成为 Agent。([Addy Osmani](https://addyosmani.com/blog/agent-harness-engineering/ "AddyOsmani.com - Agent Harness Engineering"))

## 1.2 用一个比喻说明

如果把大模型比作一个聪明但不稳定的“专家大脑”，那么 Harness 就像：

- **轨道**：规定它必须按什么流程走；
- **刹车**：高风险动作必须停下来确认；
- **仪表盘**：记录它为什么这么做、用了什么工具、花了多少成本；
- **记忆本**：沉淀历史经验、组织规则、项目上下文；
- **质检员**：检查输出是否符合规则、事实、格式和业务目标；
- **权限系统**：决定它能看什么、改什么、删什么、调用什么。

所以，Harness Engineering 的核心不是“让 Agent 更自由”，而是 **把 Agent 的自由度设计在可控边界内**。

---

# 2. 什么是 AI Agent？

## 2.1 基础定义

**AI Agent 是一个能够围绕目标自主执行任务的系统。**

它通常包括：

1. **目标理解**：理解用户想完成什么；
2. **任务规划**：拆解步骤；
3. **工具调用**：调用搜索、数据库、业务系统、代码执行器、MCP 工具等；
4. **状态管理**：知道当前做到哪一步；
5. **反馈修正**：根据结果继续调整；
6. **最终交付**：输出答案、创建文件、调用接口、发起流程。

简单说，传统 Chatbot 是“你问一句，它答一句”；Agent 是“你给一个目标，它自己规划并执行一串动作”。

## 2.2 Agent 的问题

Agent 的强项是灵活，但风险也来自灵活：

|问题|典型表现|
|---|---|
|流程不可控|Agent 自己跳步骤、漏步骤、提前执行|
|工具滥用|调用太多工具、调用错误工具、重复调用|
|上下文污染|把无关信息塞进上下文，影响判断|
|记忆不可靠|记住了错误信息，或者忘记关键规则|
|结果不可验证|输出看似合理，但没有证据链|
|高风险动作失控|自动删除、发送、部署、支付、改配置|
|难以调试|不知道它为什么这么做|
|难以复用|每次任务都靠 Prompt 临时发挥|

这就是为什么需要 Harness Engineering。

---

# 3. Harness Engineering 融入 Agent 的核心目标

你想实现的是：**Agent 的流程受控，同时保留智能能力。**

这里面有一个关键矛盾：

> 如果流程太死，Agent 就退化成传统工作流；  
> 如果流程太自由，Agent 就不可控、不可审计、不可上线。

所以最优设计不是“全自主 Agent”，也不是“纯流程机器人”，而是：

> **确定性流程骨架 + 智能节点 + 工具约束 + 反馈闭环 + 人工审批。**

也就是：  
**流程由 Harness 控制，判断由模型辅助，执行由工具完成，风险由策略拦截，结果由验证器确认。**

---

# 4. 推荐总体架构

可以设计成下面这个结构：

```text
用户目标 / 业务请求
        ↓
任务入口层 Intent Router
        ↓
流程编排层 Workflow Orchestrator
        ↓
计划控制层 Plan Controller
        ↓
Agent 执行层 LLM Agent Runtime
        ↓
工具与 MCP 层 Tool / MCP Gateway
        ↓
业务系统 / 知识库 / 数据库 / API
        ↓
验证层 Validator / Evaluator
        ↓
记忆层 Memory / Knowledge Graph
        ↓
审计与观测层 Observability / Governance
```

更简单地说：

```text
Agent 不直接访问世界
Agent 只能通过 Harness 访问世界
Harness 决定：
- 能不能做
- 怎么做
- 做到哪一步
- 是否需要确认
- 结果是否合格
- 是否写入记忆
```

---

# 5. 核心设计原则

## 原则一：流程控制权必须在 Harness，不在 LLM

LLM 可以提出计划，但不能直接决定流程跳转。

错误设计：

```text
LLM 自己决定：
先查知识库 → 再调用接口 → 再写数据库 → 再发邮件
```

正确设计：

```text
Harness 定义流程状态机：
开始 → 理解任务 → 检索上下文 → 生成计划 → 审批计划 → 执行步骤 → 验证结果 → 交付
```

LLM 只在某些节点中发挥智能，例如：

- 判断用户意图；
- 生成执行计划；
- 总结检索结果；
- 选择候选工具；    
- 生成业务文案；
- 解释异常原因。

但是流程推进、权限判断、风险拦截、结果落库，都应该由 Harness 控制。

---

## 原则二：用“状态机”替代“自由循环”

很多 Agent 框架喜欢用 ReAct 循环：

```text
Thought → Action → Observation → Thought → Action → Observation
```

这个适合探索型任务，但不适合企业级受控流程。

企业级 Agent 更适合：

```text
State 1: Receive Request
State 2: Classify Intent
State 3: Retrieve Context
State 4: Generate Plan
State 5: Validate Plan
State 6: Execute Step
State 7: Validate Result
State 8: Human Approval if Needed
State 9: Finalize
```

每个状态都要定义：

|项目|说明|
|---|---|
|输入|当前状态需要什么信息|
|输出|必须产生什么结构化结果|
|可用工具|这一阶段能用哪些工具|
|禁止行为|不能做什么|
|校验规则|如何判断输出合格|
|下一状态|满足什么条件才能进入下一步|
|失败处理|失败后重试、降级、转人工还是终止|

这就是“流程受控”的基础。

---

## 原则三：工具调用必须经过 Tool Gateway

Agent 不应该直接调用所有工具。

应该设计一个 **Tool / MCP Gateway**，所有工具调用都必须经过它。

```text
LLM → Tool Request → Tool Gateway → Policy Check → Execute → Result → Validator → LLM
```

Tool Gateway 需要做几件事：

1. **工具白名单**：当前任务只能使用指定工具；
2. **权限检查**：当前用户、当前 Agent、当前流程阶段是否允许调用；
3. **参数校验**：防止 LLM 传入危险参数；
4. **风险分级**：读操作、写操作、删除操作、外发操作分级；
5. **人工确认**：高风险动作必须确认；
6. **结果标准化**：把工具返回转换成统一结构；
7. **调用审计**：记录谁、何时、为什么、调用了什么。

Harness 在 MCP Server 的实践中也强调了工具面不能无限膨胀。它们的 MCP v2 从 130+ 个工具收敛到 11 个通用工具，用 registry-based dispatch 处理 125+ 种资源类型；核心原因是工具定义会占用模型上下文，工具越多，越容易降低推理质量。([Harness.io](https://www.harness.io/blog/harness-mcp-server-redesign "Designing MCP for the Age of AI Agents")) 这对你设计 Agent 框架很有启发：**不要把每个 API 都暴露给 LLM，而是让 LLM 说明意图，工具网关负责路由。**

---

# 6. 核心架构模块设计

## 6.1 Intent Router：意图识别层

负责判断用户到底要做什么。

例如：

```text
用户输入：
“帮我分析这个需求文档，并生成开发计划。”

Intent Router 输出：
{
  "intent": "requirement_analysis",
  "domain": "software_project_management",
  "risk_level": "medium",
  "requires_tools": ["document_reader", "knowledge_search", "plan_generator"],
  "requires_human_approval": false
}
```

这一层可以用 LLM，但输出必须是结构化 JSON，并经过 schema 校验。

核心设计：

|能力|说明|
|---|---|
|任务分类|问答、写作、分析、执行、审批、自动化|
|领域识别|保险、研发、运营、财务、法务等|
|风险分级|低风险、中风险、高风险|
|流程选择|选择对应 workflow|
|权限判断|用户是否有权限发起该流程|

---

## 6.2 Workflow Orchestrator：流程编排层

这是 Harness 的核心。

它不依赖 LLM 自由发挥，而是用 DSL / YAML / JSON 定义流程。

示例：

```yaml
workflow: requirement_analysis_agent
version: 1.0

states:
  - id: intake
    type: llm
    output_schema: RequirementIntake

  - id: retrieve_context
    type: tool
    tools:
      - knowledge_search
      - document_reader

  - id: generate_plan
    type: llm
    output_schema: ExecutionPlan

  - id: validate_plan
    type: validator
    rules:
      - must_have_scope
      - must_have_timeline
      - must_have_risks

  - id: human_approval
    type: approval
    condition: risk_level >= medium

  - id: finalize
    type: llm
    output_schema: FinalReport
```

这样设计的好处是：

1. 流程可视化；
2. 流程可审计；
3. 流程可版本化；
4. 流程可以复用；
5. LLM 不能随意越权；
6. 每一步都能加验证器。

Harness 自家的 Agent 文档中也提到，System Agents 可以 fork、customize，并作为 pipeline templates 管理，这类“Agent Pipeline 化”的思想非常适合企业级受控 Agent。([Harness Developer Hub](https://developer.harness.io/docs/platform/harness-ai/harness-agents "Harness Agents | Harness Developer Hub"))

---

## 6.3 Plan Controller：计划控制层

很多 Agent 失败不是因为不会执行，而是因为计划不可靠。

所以你需要把计划分成两个阶段：

```text
Plan Proposal → Plan Validation → Plan Execution
```

LLM 只能提出计划，不能自动执行高风险计划。

Plan Controller 要检查：

|检查项|说明|
|---|---|
|是否符合任务目标|有没有跑题|
|是否步骤完整|有没有漏掉关键步骤|
|是否调用了允许工具|有没有越权|
|是否存在高风险动作|删除、发送、部署、付款、改配置|
|是否需要人工审批|中高风险必须确认|
|是否有终止条件|防止无限循环|
|是否有回滚策略|执行失败如何处理|

推荐计划结构：

```json
{
  "goal": "生成需求分析报告",
  "steps": [
    {
      "step_id": "s1",
      "action": "read_document",
      "tool": "document_reader",
      "risk": "low",
      "expected_output": "需求摘要"
    },
    {
      "step_id": "s2",
      "action": "search_related_knowledge",
      "tool": "knowledge_search",
      "risk": "low",
      "expected_output": "相关历史方案"
    },
    {
      "step_id": "s3",
      "action": "generate_report",
      "tool": "llm",
      "risk": "low",
      "expected_output": "结构化报告"
    }
  ],
  "approval_required": false
}
```

---

## 6.4 Agent Runtime：Agent 执行层

这一层才是真正调用模型的地方。

但是注意：Agent Runtime 不应该是一个“万能 Agent”，而应该是多个小型 Agent / Skill。

建议拆成：

|Agent 类型|作用|
|---|---|
|Planner Agent|负责拆解任务|
|Research Agent|负责检索和归纳|
|Reasoning Agent|负责分析和判断|
|Writing Agent|负责生成报告、文案、总结|
|Tool Agent|负责把意图转成工具调用请求|
|Critic Agent|负责检查输出质量|
|Memory Agent|负责判断哪些内容值得写入记忆|

但这里有一个重要建议：

> 不要一开始就做复杂的多 Agent 群体协作。  
> 先做“单 Agent + 多 Skill + 强 Harness”。

因为多 Agent 容易带来：

- 成本上升；
- 状态混乱；
- 责任不清；
- 调试困难；
- 多个 Agent 相互误导。

更稳妥的方式是：

```text
一个主控 Agent
+
多个受控 Skill
+
一个确定性 Orchestrator
+
一个 Tool Gateway
```

---

## 6.5 Memory Layer：记忆层

记忆不要简单等同于“向量库”。

企业级 Agent 需要三类记忆：

### 第一类：Session Memory

当前任务内的短期记忆。

例如：

```text
用户目标、当前步骤、已调用工具、工具结果、临时判断、待确认事项
```

生命周期：一次任务结束后可清理。

---

### 第二类：Long-term Memory

跨任务长期记忆。

例如：

```text
用户偏好、组织规则、项目背景、历史决策、常用流程、团队规范
```

生命周期：长期保留，但必须可编辑、可删除、可追溯。

Anthropic 在长任务 Agent 的文章中提到，长时间任务的核心问题是跨多个上下文窗口工作时，新会话会丢失之前的状态，因此需要让 Agent 留下清晰工件，帮助下一轮继续工作。([Anthropic](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents "Effective harnesses for long-running agents \ Anthropic")) 这说明记忆层不只是“存文本”，而是要设计成“可接力、可恢复、可验证”的工作状态系统。

---

### 第三类：Knowledge Base / Knowledge Graph

这是组织知识，不是个人记忆。

例如：

```text
制度文档、产品手册、接口文档、流程规范、历史项目、FAQ、业务规则
```

OpenAI 在 Harness Engineering 实践中提到，他们把 repository knowledge 作为 system of record，而不是把所有内容塞进一个巨大的 AGENTS.md；AGENTS.md 更像目录，真正知识放在结构化 docs 里。([OpenAI](https://openai.com/index/harness-engineering/ "Harness engineering: leveraging Codex in an agent-first world | OpenAI")) 这个思路可以直接用于你的 Agent 框架：**不要让 Prompt 承载所有知识，要让 Prompt 指向知识系统。**

推荐知识结构：

```text
knowledge/
  business/
    insurance_rules.md
    underwriting_rules.md
    claims_process.md
  engineering/
    architecture.md
    api_spec.md
    deployment_rules.md
  operation/
    app_growth_playbook.md
    user_lifecycle.md
  project/
    project_a/
      background.md
      decisions.md
      risks.md
      weekly_reports.md
```

---

## 6.6 Validator / Evaluator：验证层

没有验证层，Agent 就不可控。

验证层分为五类：

### 1. Schema Validator

检查输出格式。

例如必须输出：

```json
{
  "summary": "...",
  "risks": [],
  "next_actions": []
}
```

不能让模型自由输出一大段不可解析文本。

---

### 2. Rule Validator

检查业务规则。

例如：

```text
保险销售话术不能承诺收益；
理赔建议不能替代官方理赔结论；
代码变更必须通过测试；
邮件发送必须确认收件人。
```

---

### 3. Tool Result Validator

检查工具结果是否可信。

例如：

```text
搜索结果是否为空？
数据库返回是否异常？
接口调用是否成功？
是否拿到了过期数据？
```

---

### 4. Safety Validator

检查是否存在危险动作。

例如：

```text
删除数据；
发送外部邮件；
修改生产配置；
提交代码；
部署服务；
调用支付；
访问敏感数据。
```

---

### 5. Quality Evaluator

检查输出质量。

例如：

```text
是否回答了问题？
是否有证据？
是否逻辑完整？
是否符合目标受众？
是否可执行？
是否遗漏关键风险？
```

这一步可以用 LLM-as-judge，但不能只靠 LLM。最好组合：

```text
规则校验 + 测试用例 + 静态检查 + LLM 评估 + 人工抽检
```

---

## 6.7 Human-in-the-loop：人工审批层

流程受控的关键不是完全自动化，而是明确哪些地方必须人工介入。

建议把动作分成四级：

|等级|动作类型|是否需要审批|
|---|---|---|
|L0|只读、总结、草稿|不需要|
|L1|内部文档生成、低风险建议|可选审批|
|L2|写入系统、创建任务、修改配置|需要审批|
|L3|删除、外发、部署、付款、影响客户|强制审批|

例如：

```text
Agent 可以自动生成邮件草稿；
但不能自动发送邮件，除非用户明确授权。

Agent 可以自动生成部署方案；
但不能自动部署生产环境，除非审批通过。

Agent 可以自动分析客户数据；
但不能自动对客户发营销短信，除非通过合规策略。
```

Harness MCP v2 的安全设计也包含 write confirmations、fail-closed deletes、read-only mode、重试和限流控制等机制。([Harness.io](https://www.harness.io/blog/harness-mcp-server-redesign "Designing MCP for the Age of AI Agents")) 这非常适合借鉴到你的 Tool Gateway 设计里。

---

# 7. 如何融合 Harness Engineering 和 Agent？

可以用一句话概括：

> **用 Harness Engineering 把 Agent 从“自由发挥的智能体”改造成“运行在受控流程里的智能能力节点”。**

具体融合方式如下。

---

## 7.1 把 Agent 放进流程，而不是让 Agent 生成流程

传统 Agent 设计：

```text
用户目标 → Agent 自己规划 → Agent 自己执行 → Agent 自己判断完成
```

Harness 化 Agent 设计：

```text
用户目标
→ Harness 选择流程
→ Agent 在指定节点中完成智能任务
→ Harness 校验输出
→ Harness 决定下一步
→ 必要时人工审批
→ Harness 记录和沉淀
```

本质变化：

|传统 Agent|Harness 化 Agent|
|---|---|
|LLM 是主控|Harness 是主控|
|流程隐含在 Prompt 中|流程显式定义在 Workflow 中|
|工具由 LLM 自由选|工具由状态和权限控制|
|结果靠模型自信|结果靠验证器确认|
|记忆随意写入|记忆经过筛选和版本化|
|难以审计|全链路可追踪|
|难以上线|可灰度、可回滚、可评估|

---

## 7.2 设计“确定性骨架 + 智能节点”

以“需求分析 Agent”为例。

```text
确定性骨架：
1. 接收需求
2. 判断需求类型
3. 检索相关资料
4. 生成分析计划
5. 校验计划
6. 生成报告
7. 质量检查
8. 输出结果

智能节点：
- 判断需求类型
- 总结文档
- 识别风险
- 生成方案
- 优化表达
```

这样 Agent 依然智能，但不会乱跑。

---

## 7.3 设计“工具少而强”，不要“工具多而散”

不要给 Agent 暴露 100 个业务 API。

推荐暴露 8 到 12 个高层工具：

```text
search_knowledge
read_document
query_business_data
create_draft
create_task
update_record
request_approval
send_notification
run_validation
generate_report
```

每个工具内部再做路由。

例如：

```text
LLM 调用：
query_business_data(resource="policy", query="...")
```

而不是暴露：

```text
get_policy_by_id
get_policy_list
get_policy_customer
get_policy_payment
get_policy_claims
get_policy_agent
...
```

这样可以减少模型上下文负担，也能降低误调用概率。Harness MCP v2 的设计就是从“一接口一工具”转向“少量通用工具 + registry dispatch”，这点很值得借鉴。([Harness.io](https://www.harness.io/blog/harness-mcp-server-redesign "Designing MCP for the Age of AI Agents"))

---

# 8. 推荐技术架构

## 8.1 分层架构

```text
┌────────────────────────────────────┐
│          User / Business UI         │
└────────────────────────────────────┘
                 ↓
┌────────────────────────────────────┐
│        Agent Control Plane          │
│  - Intent Router                    │
│  - Workflow Orchestrator            │
│  - Policy Engine                    │
│  - Approval Engine                  │
└────────────────────────────────────┘
                 ↓
┌────────────────────────────────────┐
│          Agent Runtime              │
│  - Planner                          │
│  - Executor                         │
│  - Critic                           │
│  - Memory Writer                    │
└────────────────────────────────────┘
                 ↓
┌────────────────────────────────────┐
│          Tool / MCP Gateway          │
│  - Tool Registry                    │
│  - Permission Check                 │
│  - Parameter Guard                  │
│  - Rate Limit                       │
│  - Audit Log                        │
└────────────────────────────────────┘
                 ↓
┌────────────────────────────────────┐
│   Enterprise Systems / Knowledge     │
│  - Vector DB                         │
│  - SQL / API                         │
│  - Documents                         │
│  - Workflow Systems                  │
│  - Git / CI / CRM / Insurance Core   │
└────────────────────────────────────┘
                 ↓
┌────────────────────────────────────┐
│      Observability & Evaluation      │
│  - Logs                              │
│  - Traces                            │
│  - Cost                              │
│  - Quality Score                     │
│  - Failure Analysis                  │
└────────────────────────────────────┘
```

---

## 8.2 核心组件说明

|模块|职责|
|---|---|
|Agent Control Plane|管控流程、权限、审批、策略|
|Workflow Orchestrator|定义和执行状态机|
|Policy Engine|判断动作是否允许|
|Agent Runtime|调用模型完成智能推理|
|Tool Gateway|统一管理工具和 MCP|
|Memory Service|管理短期记忆、长期记忆、知识库|
|Evaluator|对结果做规则和质量检查|
|Observability|记录全链路日志、成本、延迟、失败原因|
|Admin Console|管理流程、工具、权限、Prompt、版本|

---

# 9. 流程受控的关键机制

## 9.1 状态机控制

每个 Agent 任务都应该有明确状态。

示例：

```text
CREATED
→ INTENT_CLASSIFIED
→ CONTEXT_RETRIEVED
→ PLAN_GENERATED
→ PLAN_VALIDATED
→ WAITING_APPROVAL
→ EXECUTING
→ RESULT_VALIDATED
→ COMPLETED
```

任何状态跳转都必须由 Harness 决定。

---

## 9.2 工具权限控制

工具权限可以按四个维度控制：

```text
用户角色
Agent 类型
Workflow 阶段
工具风险等级
```

例如：

|用户|Agent|阶段|工具|是否允许|
|---|---|---|---|---|
|普通员工|文档 Agent|分析阶段|read_document|允许|
|普通员工|文档 Agent|执行阶段|send_email|禁止|
|管理者|项目 Agent|审批后|create_task|允许|
|管理者|运维 Agent|未审批|deploy_prod|禁止|

---

## 9.3 输入输出 Schema 控制

LLM 输出必须结构化。

例如，计划输出：

```json
{
  "task_summary": "string",
  "assumptions": ["string"],
  "steps": [
    {
      "id": "string",
      "description": "string",
      "tool": "string",
      "risk_level": "low|medium|high",
      "requires_approval": true
    }
  ],
  "risks": ["string"],
  "success_criteria": ["string"]
}
```

如果不符合 schema，直接退回重试，不进入下一步。

---

## 9.4 Checkpoint 机制

长任务必须有 checkpoint。

每完成一步，保存：

```json
{
  "workflow_id": "xxx",
  "current_state": "RESULT_VALIDATED",
  "completed_steps": ["s1", "s2"],
  "pending_steps": ["s3"],
  "artifacts": ["summary.md", "plan.json"],
  "decisions": [
    {
      "decision": "选择方案A",
      "reason": "成本低，风险小",
      "evidence": ["doc_1", "search_result_2"]
    }
  ]
}
```

这样 Agent 即使中断，也可以恢复。

---

## 9.5 高风险动作强制确认

高风险动作包括：

```text
发送外部消息
修改数据库
删除文件
提交代码
部署生产
调用支付
修改客户信息
触达客户
生成合规敏感建议
```

这些动作必须进入：

```text
propose → explain → approve → execute → audit
```

不能让 LLM 直接执行。

---

# 10. 记忆与知识库设计

你可以采用三层结构：

```text
Raw Sources → Curated Knowledge → Runtime Context
```

## 10.1 Raw Sources

原始资料：

```text
PDF、Word、网页、会议纪要、代码、接口文档、业务制度、历史报告
```

只存原文，不直接给 Agent 全量使用。

---

## 10.2 Curated Knowledge

经过整理后的知识：

```text
业务规则
流程规范
常见问题
项目背景
系统架构
角色权限
历史决策
```

这层需要版本、负责人、更新时间。

---

## 10.3 Runtime Context

Agent 当前任务真正需要的上下文。

原则：

```text
不是检索越多越好，而是只给当前步骤需要的最小充分上下文。
```

OpenAI 的实践也强调，不要用一个巨大说明文件承载所有知识，而是用简短入口文件作为地图，指向结构化知识源。([OpenAI](https://openai.com/index/harness-engineering/ "Harness engineering: leveraging Codex in an agent-first world | OpenAI"))

---

# 11. MCP 接入设计

MCP 很适合作为 Tool Gateway 的标准协议层。

但不要简单地把所有 MCP Server 都暴露给 Agent。

推荐做法：

```text
Agent
  ↓
Internal Tool Gateway
  ↓
MCP Adapter Layer
  ↓
Approved MCP Servers
  ↓
Business Systems
```

也就是说，Agent 不直接连 MCP Server，而是通过你自己的网关。

## 11.1 MCP 工具分级

|类型|示例|策略|
|---|---|---|
|Read-only MCP|搜索文档、查询项目、读取代码|默认允许|
|Draft MCP|创建草稿、生成 PR、创建任务草稿|低风险允许|
|Write MCP|更新记录、创建任务、修改状态|需要权限|
|Destructive MCP|删除、覆盖、关闭、回滚|强制审批|
|External Action MCP|发邮件、发消息、触达客户|强制审批 + 审计|

## 11.2 MCP 工具收敛

不要这样：

```text
100 个 MCP tools 全部暴露给 LLM
```

应该这样：

```text
10 个高层工具：
- search
- read
- create
- update
- delete
- execute
- validate
- approve
- summarize
- report
```

然后由 Tool Gateway 根据 resource type 和 policy 分发。

这和 Harness MCP v2 的“少量通用工具 + registry dispatch”理念一致。([Harness.io](https://www.harness.io/blog/harness-mcp-server-redesign "Designing MCP for the Age of AI Agents"))

---

# 12. 推荐落地方案：受控 Proof Agent Framework

## 12.1 框架名称可以叫：Proof Agent

核心能力：

```text
1. 流程编排
2. 状态机执行
3. LLM 节点
4. 工具网关
5. MCP 接入
6. 记忆管理
7. 知识库检索
8. 权限策略
9. 人工审批
10. 结果验证
11. 观测审计
12. 任务恢复
```

---

## 12.2 一次完整任务的执行链路

```text
Step 1：用户提交任务
“帮我根据这份需求文档生成开发方案。”

Step 2：Intent Router 分类
识别为 requirement_analysis。

Step 3：Workflow Orchestrator 加载流程
选择 requirement_analysis_workflow_v1。

Step 4：Context Retriever 检索上下文
读取需求文档、历史项目、架构规范。

Step 5：Planner Agent 生成计划
输出结构化 plan.json。

Step 6：Plan Validator 校验计划
检查是否有目标、范围、风险、步骤、验收标准。

Step 7：Executor Agent 分步骤执行
每一步只能调用当前状态允许的工具。

Step 8：Result Validator 检查结果
检查格式、完整性、事实依据、风险提示。

Step 9：Memory Writer 判断是否沉淀
把重要决策写入项目记忆。

Step 10：Final Response
输出报告，并附上证据、风险和下一步建议。
```

---

# 13. 数据模型设计

## 13.1 Workflow

```json
{
  "workflow_id": "requirement_analysis_v1",
  "name": "需求分析流程",
  "version": "1.0",
  "states": [],
  "policies": [],
  "validators": [],
  "allowed_tools": []
}
```

## 13.2 Agent Task

```json
{
  "task_id": "task_001",
  "user_id": "u_001",
  "workflow_id": "requirement_analysis_v1",
  "status": "EXECUTING",
  "current_state": "generate_plan",
  "risk_level": "medium",
  "created_at": "2026-05-09T10:00:00Z"
}
```

## 13.3 Tool Call

```json
{
  "tool_call_id": "tc_001",
  "task_id": "task_001",
  "tool_name": "knowledge_search",
  "input": {},
  "output": {},
  "risk_level": "low",
  "approved": true,
  "latency_ms": 1200,
  "cost": 0.02
}
```

## 13.4 Memory Record

```json
{
  "memory_id": "mem_001",
  "scope": "project",
  "type": "decision",
  "content": "本项目采用方案A，因为成本低、上线快。",
  "source_task_id": "task_001",
  "confidence": 0.86,
  "created_by": "agent",
  "review_status": "pending"
}
```

---

# 14. 推荐 MVP 范围

不要一开始做大而全的 Agent 平台。建议从一个高价值场景切入。

## MVP 目标

做一个：

> **受控流程的企业知识分析 Agent**

它能完成：

```text
上传文档
→ 自动分析
→ 检索知识库
→ 生成结构化报告
→ 输出风险和建议
→ 人工确认
→ 写入项目记忆
```

## MVP 必备能力

|模块|是否必做|
|---|---|
|Workflow DSL|必做|
|状态机执行器|必做|
|LLM 节点|必做|
|知识库检索|必做|
|Tool Gateway|必做|
|输出 Schema 校验|必做|
|审计日志|必做|
|人工审批|建议做|
|MCP 接入|建议做简版|
|多 Agent 协作|暂缓|
|自动执行写操作|暂缓|

---

# 15. MVP 技术选型建议

## 15.1 后端

|模块|推荐|
|---|---|
|API 服务|FastAPI / NestJS|
|Workflow Engine|Temporal / LangGraph / 自研轻量状态机|
|队列|Redis Queue / Celery / BullMQ|
|数据库|PostgreSQL|
|向量库|pgvector / Milvus / Qdrant|
|对象存储|S3 / MinIO|
|日志追踪|OpenTelemetry + Grafana|
|权限策略|Casbin / OPA|
|MCP|MCP Server + 自研 Gateway|

## 15.2 Agent 层

可以选：

|方案|适合情况|
|---|---|
|LangGraph|适合状态机 Agent|
|OpenAI Agents SDK|适合快速构建工具型 Agent|
|Semantic Kernel|适合企业系统集成|
|AutoGen|适合多 Agent 实验|
|自研 Orchestrator|适合强流程控制|

如果你的核心诉求是“流程完全受控”，我更建议：

> **自研轻量 Orchestrator + LLM SDK + MCP Gateway**

而不是完全依赖现成 Agent 框架。

因为很多 Agent 框架默认鼓励模型自主规划、自主调用工具，这和“流程受控”存在天然冲突。

---

# 16. 最推荐的产品形态

你可以把它设计成一个企业级 Agent Control Platform。

## 管理端

```text
Workflow 管理
Prompt 管理
工具管理
MCP Server 管理
权限策略管理
审批规则管理
知识库管理
记忆管理
执行日志
质量评估
成本分析
```

## 使用端

```text
任务入口
文档上传
Agent 执行过程展示
中间结果确认
审批卡片
最终报告
历史任务
知识沉淀
```

## 开发者端

```text
Workflow YAML
Tool SDK
MCP Adapter
Validator SDK
Memory SDK
Evaluation SDK
```

---

# 17. 关键设计取舍

## 17.1 不要追求“Agent 完全自主”

企业级 Agent 的目标不是“完全自主”，而是：

```text
该自主的地方自主；
该受控的地方受控；
该审批的地方审批；
该沉淀的地方沉淀。
```

## 17.2 不要把 Prompt 当系统架构

Prompt 只能表达意图和局部规则，不能替代：

```text
状态机
权限系统
工具网关
验证器
审批流
日志系统
记忆系统
```

## 17.3 不要让 LLM 直接决定高风险动作

LLM 可以建议，但不能直接执行。

尤其是：

```text
删除
发送
付款
部署
改生产数据
触达客户
合规敏感判断
```

## 17.4 不要过早做多 Agent

先做：

```text
Single Agent + Strong Harness
```

再做：

```text
Multi Skill
```

最后再考虑：

```text
Multi Agent Collaboration
```

---

# 18. 适合你的框架蓝图

结合你的目标，可以这样定义：

## Proof Agent : Controlled Agent Harness Framework

### 定位

一个面向企业场景的 Agent 框架，用 Harness Engineering 思想，把 Agent 的智能能力封装进可编排、可验证、可审计、可审批的流程中。

### 核心卖点

```text
1. 流程完全受控
2. 支持 Workflow 编排
3. 支持 Memory 和 Knowledge Base
4. 支持 MCP 接入
5. 支持权限、审批、审计
6. 支持结果验证和质量评估
7. 支持任务恢复和长期运行
```

### 技术理念

```text
LLM is not the controller.
Workflow is the controller.

LLM proposes.
Harness disposes.

Agent thinks.
Harness governs.

Tools execute.
Validators verify.
Humans approve.
Memory accumulates.
```

---

# 19. 一个具体示例：保险机构企业问答 Agent

假设你要做“保险机构企业问答 Agent”。

## 用户输入

```text
帮我分析本月保险代理人的销售情况，并给出改进方案。
```

## Harness 流程

```text
1. 识别任务类型：经营分析
2. 检查用户权限：是否能访问经营数据
3. 检索数据：触客、访客、转化、出单、活动、客户分层
4. 检索知识库：历史销售方案、销售策略
5. 生成分析计划
6. 校验计划完整性
7. 执行数据分析
8. 生成原因假设
9. 输出改进方案
10. 风险校验：是否涉及违规营销
11. 人工确认
12. 写入运营知识库
```

## Agent 智能点

```text
判断销售下降可能原因；
发现销售各环节的差异；
输出改进方案
输出管理层汇报稿。
```

## Harness 控制点

```text
不能越权查数据；
不能编造指标；
不能绕过合规；
必须输出证据链；
必须记录分析过程。
```

这就是“流程受控 + 智能增强”。

---

# 20. 最终建议

如果你要把 Harness Engineering 融入 Agent 框架，我建议按这个方向做：

## 第一阶段：做流程受控

先完成：

```text
Workflow DSL
状态机执行
LLM 节点
Schema 校验
Tool Gateway
日志审计
```

## 第二阶段：做知识和记忆

增加：

```text
知识库
长期记忆
项目记忆
规则记忆
上下文检索
记忆审核
```

## 第三阶段：做 MCP 编排

增加：

```text
MCP Adapter
MCP Tool Registry
工具分级
权限控制
审批控制
工具调用观测
```

## 第四阶段：做企业级治理

增加：

```text
权限体系
审批流
质量评估
成本监控
异常恢复
灰度发布
版本管理
合规审计
```

---

# 结论

你要设计的不是普通 Agent，而是一个 **Agent Control Framework**。

它的本质是：

> **用 Harness Engineering 把大模型的不确定性，装进一个确定性的流程、权限、验证和反馈系统里。**

最关键的架构判断是：

```text
Agent 负责智能；
Harness 负责控制。

Agent 负责生成可能性；
Harness 负责选择、限制、验证和落地。

Agent 可以思考；
但不能随意行动。
```

如果这套架构做成开源项目，最有价值的方向不是“又一个 Agent 框架”，而是：

> **一个面向企业应用的 Controlled Agent Harness Framework：  
> 让开发者可以用 YAML/DSL 编排受控 Agent 流程，内置 Memory、Knowledge Base、MCP Gateway、Policy、Approval、Validator 和 Observability。**

这个方向比单纯做 Chatbot、RAG 或多 Agent Demo 更有长期价值，因为企业真正缺的不是“更会聊天的 Agent”，而是 **可上线、可治理、可审计、可复用的 Agent 运行框架**。