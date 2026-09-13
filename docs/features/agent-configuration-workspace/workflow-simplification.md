# Workflow 配置梳理与精简

日期：2026-09-10。范围：Dashboard Workflow 配置页、既有保存入口与未保存提示。
依据：ADR-0252；延续 ADR-0251 的单一 Prompt 和结构模板。

## 结论与使用路径

[KNOWN | HIGH] 日常配置只需要：查看完整流程并选择节点 → 编写 Prompt（可选插入结构模板）→
保存 Workflow。留空使用系统默认指令；不需要把每个系统节点都配置一遍。
本轮未改变流程拓扑、模型决策集合、工具权限、证据接纳或后台 API 契约。

推荐顺序：先调“生成答案”的内容重点和表达要求；只有意图理解或查询规划存在明确问题，
再调整“理解用户诉求”和“规划下一步”。额外上下文按需展开，不默认改动已有开关。

## 当前页面审查证据

以当前源码组件和完整后端模板描述构造虚构配置，在 Codex 内置浏览器捕获旧页和新页。
这不是生产 Agent 数据；观察的是实际组件渲染与交互，不是设计示意图。

1. 打开旧页：首屏主要是固定模板、重复模板选择、Runtime 未配置及多个节点统计；Prompt
   不在同一默认视口内，用户先看到 Save Core 和 Save Stages 两个保存入口。
2. 进入节点：节点 ID、模型标记、Required、输入输出、关系分支与多层 Inspector 标题，
   大部分是解释性信息，不能操作；原始 `include_*` 开关要求用户先理解内部字段。
3. 当前主路径：桌面 224 px 流程侧栏与 Prompt 编辑区并排；窄屏默认显示流程入口与当前配置。保留 10 个节点、4 个分支、返回规划、一个保存入口和修改状态。
4. 展开高级设置：只出现本节点可提供数据的上下文选项；预览明确为不调用模型的上下文检查。
5. 点击系统节点/展开技术信息：查看既有设置、绑定版本和原始 YAML；不暗示这些是日常必填项。
6. 窄屏检查发现标题被操作区挤成细列，已改为标题和操作分行，并使用紧凑节点布局。

可访问性检查覆盖表单标签、键盘可操作按钮、展开状态、当前节点标记、错误/修改状态提示及
390 px 窄屏布局。未执行完整屏幕阅读器验收，不声明 WCAG 全面符合。

## 配置逐项取舍

| 原配置/信息 | 实际作用 | 精简处理 |
| --- | --- | --- |
| Workflow Template 选择 | 当前只有 `react_enterprise_qa_v3` | 删除选择器，绑定名在技术信息只读展示 |
| Save Core | 单独保存同一个固定模板，增加理解成本 | 移除；统一使用既有 stages 保存端点 |
| Runtime / Checkpointer | 已退出当前公共配置契约 | 删除 Runtime 展示及编辑器内残留说明，不读取/写入旧字段 |
| 描述版本、总节点数、模型节点数、可编辑数 | 系统技术描述，不是用户决策 | 移除重复统计；版本保留在技术信息 |
| Relationship Map 的 Entry/Processing/Terminal | 描述关系，不等于 V3 循环执行顺序 | 保留全部流程节点；用条件分支与返回规划标注循环，系统配置只读 |
| 多层 Stage Design/Inspector/节点标题 | 重复组织文字 | 只保留 Workflow 与当前节点标题 |
| Stage ID、Availability、Input/Output、分支 | 排查配置时有用 | 移到技术信息 |
| Prompt | 对阶段提出业务要求 | 主界面保留，仍是一段自由文本 |
| 结构模板 | 帮助组织 Prompt | 保留三个章节和填写提示，不含业务范文 |
| Context Options | 可选的额外上下文投影 | 放入高级设置，中文说明，只展示已接入的数据项 |
| Preview Context | 预览脱敏/限长上下文，不调用模型 | 放入高级设置，显示截断提示 |
| Advanced YAML 独立面板 | 只读排查视图 | 合并到技术信息 |
| Save Stages | 保存全部节点的配置 | 改为“保存 Workflow”，显示未保存状态，无变更时禁用 |

## 各节点的实际配置入口

| 节点 | 当前 Prompt 模型输入链路 | 新入口 |
| --- | --- | --- |
| `intent_resolution` | 已接入 | 理解用户诉求：常用 Prompt |
| `plan` | 已接入 | 规划下一步：常用 Prompt |
| `model_answer` | 已接入 | 生成答案：常用 Prompt |
| `retrieval_review` | 配置可进入摘要/指纹，未看到注入审查模型的调用 | 系统节点，只读保留原值并说明限制 |
| `tool_review` | 同上 | 系统节点，只读保留原值并说明限制 |
| `clarification` | 系统返回澄清结果 | 系统节点 |
| `retrieval` | 执行检索与证据接纳 | 系统节点；知识绑定在 Knowledge 配置 |
| `tool` | 工具网关执行 | 系统节点；工具能力在 Tools 配置 |
| `memory` | 按独立记忆策略处理 | 系统节点；记忆能力在 Memory 配置 |
| `response` | 结果投影 | 系统节点；措辞在生成答案调整，披露在 Response 配置 |

[KNOWN | HIGH] 事实来源：`proof_agent/control/workflow/templates.py` 定义节点；
`proof_agent/control/workflow/controlled_react/composition.py` 的 `_stage_contexts.get(...)`
只有意图、规划、答案三处消费；`stage_contexts.py` 构建其静态上下文投影。
描述中的 model-bearing 不等于配置文本已接入该节点的实际模型调用。

## 所有 Context 选项分类

下表描述的是 stage-context 补充投影，不是该阶段的全部运行输入。隐藏一个空投影开关不会
取消独立传入的 Accepted Evidence、工具合同或权限上下文。对话摘要也不会因此成为证据。

| 选项（去掉 `include_` 前缀） | 当前补充投影内容 | 新界面处理 |
| --- | --- | --- |
| `agent_purpose` | Agent purpose | 高级：助手职责 |
| `recent_conversation_summary` | 经 admission 的会话摘要；没有时为空 | 高级：近期对话摘要 |
| `bound_knowledge_sources` | 绑定来源的 source_id 列表，不是文档正文 | 高级：已绑定的知识来源 |
| `citation_requirements` | 固定引用要求文字 | 高级：证据引用要求 |
| `response_disclosure_policy` | response 配置投影 | 高级：回答展示设置 |
| `policy_outline` | 仅策略文件路径，不是策略内容 | 不提供编辑开关，原值保留 |
| `bound_tools`、`tool_contract_summary` | 空字符串 | 不提供无实际内容的编辑开关 |
| `missing_field_schema`、`source_routing_metadata`、`evidence_summary` | 空数组 | 同上 |
| `retrieval_intent`、`outcome` | 空字符串 | 同上 |
| `tool_proposal`、`parameter_bounds` | 空对象 | 同上 |
| `approval_requirements`、`approval_state` | 空字符串，当前产品无审批流程 | 同上 |
| `governance_summary` | 空数组 | 同上 |
| `memory_scope`、`memory_denylist_summary` | 真实记忆配置/禁止字段摘要，但属于系统 Memory 节点 | 系统技术信息保留，Memory 模块管理能力 |

五类有效选项仍与当前节点 descriptor 的 allowlist 取交集，不跨节点新增选项。
所有未展示的既有键值和当前描述中未显示的已配置节点在保存时保留，后台继续负责校验。

## 状态、兼容与权限

- 单一保存沿用 `updateWorkflowStages` 和 Draft `expected_revision`，不是新增执行路径。
- 使用已绑定的模板和描述版本；不匹配时禁止编辑/保存，不猜测迁移目标。
- 修改多个节点一次保存；失败和冲突保留本地输入；保存返回的 YAML 才刷新基线。
- 各节点显示未保存标记；切换节点不丢失输入；恢复原值后不制造无意义的保存。
- 模块内切换受现有未保存提示保护；“放弃未保存修改”同步重置 Workflow；刷新页面有提示。
- 任意外部路由跳转、跨设备并发、离线恢复不在本轮承诺范围。
- 总 Prompt 预算继续为 12,000 Unicode 字符；运行上下文仍受既有截断规则约束。
- Backend API、Skill 配置、已发布 Agent、运行时节点和策略不因本轮 UI 简化而变更。

## 验证记录

[KNOWN | HIGH] LOCAL_VERIFIED：本轮 UI 与配置交互的本地验证；不是上线或生产验收。

- RED：新测试在旧实现中复现固定模板选择、双保存入口和默认高级开关问题。
- `npm run test -w proof-agent-dashboard`：257 passed，39 个测试文件全部通过。
- `npm run build:dashboard`：TypeScript/Vite 构建通过；现有主 chunk 大于 500 kB 的提示保留。
- 回归覆盖结构模板、预览/保存一致、跨节点保留、失败保留、描述版本不匹配、系统节点只读、
  隐藏配置保留、重复提交保护、Unicode 总预算、原值恢复、刷新保护、跨模块阻止及主动放弃。
- 实际浏览器使用完整后端描述 + 虚构 Agent，验证插入模板、上下文切换、跨节点和保存重载；
  桌面及 390 px 截图检查。API/页面测试与浏览器 fixture 分别验证，不冒称生产端到端。
- 自检发现并修复窄屏标题挤压和开关恢复后的假 dirty。没有独立子 Agent 审查。
- 后端未修改，因此不重复执行此前后端全量测试；本轮没有真实模型/外部服务效果验证。

## 维护标准

新增配置必须同时满足：用户有明确决策需要、运行时确有消费路径、存在可验证效果。
只读内部状态不做输入项；只有一个合法值不做选择框；空占位输入不作为有效开关；
高级技术字段按需展开。未来接入新的阶段 Prompt 或上下文时，同步更新 presentation 映射、
领域证据与交互测试，避免只新增 descriptor 就误导用户认为已生效。

## 本地截图与变更指纹

截图来自本轮虚构配置，不包含生产数据。

- 精简前：`/Users/jamin/.codex/visualizations/2026/09/09/01a0868b-1a5a-7ee3-8554-72e8748781c0/workflow-before.png`
- 精简后：`/Users/jamin/.codex/visualizations/2026/09/09/01a0868b-1a5a-7ee3-8554-72e8748781c0/workflow-after.png`
- 窄屏：`/Users/jamin/.codex/visualizations/2026/09/09/01a0868b-1a5a-7ee3-8554-72e8748781c0/workflow-narrow.png`
- 系统节点只读：`/Users/jamin/.codex/visualizations/2026/09/09/01a0868b-1a5a-7ee3-8554-72e8748781c0/workflow-system.png`

以下 SHA-256 对应已验证的当前代码与测试：

- `dashboard/src/components/agent/WorkflowModuleEditor.tsx`: `b01fd7bfa01e42c04d4d75e4dad71c1d493b448957ad0aa1117e7499bbac36c5`
- `dashboard/src/components/agent/workflowPresentation.ts`: `3991a01272384ae949f30c8b4f6d06fc391ad3cf6cf58128ace3c248c1f9f79a`
- `dashboard/src/pages/AgentDetailPage.tsx`: `8fefa908a8ce2f0881b94bfc68fdbf09697204b7fb378bf72725721cf2b1b7c4`
- `dashboard/src/components/__tests__/agent/WorkflowModuleEditor.test.tsx`: `3cd01c89304f3877df262b997754f69df339bb33804dca0c78600eef36d4a290`
- `dashboard/src/components/__tests__/agent/WorkflowModuleEditor.simplification.test.tsx`: `2a6f236d59363d57cf91208b5537aef5c25e505a10ba581f4bcf7ff3e9fbf427`
- `dashboard/src/pages/__tests__/AgentDetailPage.test.tsx`: `60c175c0d276f58feff046bac4b0c65b574486932203a8a6c5922b09f75113c7`

## 保留流程的修正验收（2026-09-10）

用户反馈上一版把配置简化成节点列表后，无法了解整个 Workflow。最终实现取消隐藏系统
节点，保留完整流程；简化仅作用于配置表单。`WorkflowConfigurationFlow.tsx` 展示理解诉求、
规划、澄清、检索审查/执行、工具审查/执行、生成答案、记忆与返回结果。观察后的返回规划
取自 `controlled_react/orchestrator.py::_run_loop`；记忆按需写入取自 `_write_memory`。
这是一张 V3 概念流程图，不能替代运行 Trace。未来运行分支变更时需要同步更新图与测试。

- RED：系统节点默认可见的回归测试在此前实现失败；修改后通过。
- Dashboard 全量 256 tests / 39 files passed；构建通过，保留既有 chunk 大小提示。
- 在实际本地 Dashboard 的保险助手草稿页面验证全部 10 个节点、系统节点点击定位、返回流程；
  没有写入或保存该草稿。390 px 实测 scrollWidth=clientWidth=390，节点数为 10。
- 完整流程截图：`/Users/jamin/.codex/visualizations/2026/09/09/01a0868b-1a5a-7ee3-8554-72e8748781c0/workflow-flow-restored.png`。
  上方旧版 `workflow-after.png` 仅记录此前已被用户要求修正的中间版本。

## 紧凑流程与配置并排（2026-09-10，当前设计）

用户反馈上方大流程图挤占首屏，因此将其替换为桌面 224 px 的紧凑侧栏，完整保留分支与
返回规划语义。同一分支的审查/执行节点横向连接；移除卡片底色、逐节点状态副标题和
强制滚动。右侧配置始终与流程顶部对齐。窄屏默认收起流程，入口显示当前节点和节点总数；
展开后选择节点自动收起，保留本地编辑，并将键盘焦点转入配置区。

当前验收覆盖：窄屏展开/选择/收起、全部节点保留、跨节点草稿保留、统一保存及原有保护。
Dashboard 全量 257 tests / 39 files passed，构建通过。实际本地草稿页面未作保存：
1280×720 下流程宽 223 px（加边框为 224 px），Prompt 顶部 y=442，可直接开始编辑；
390 px 下默认配置可见，展开流程选择“生成答案”后正常收起。旧版顶部总览截图仅作为迭代记录。

当前桌面截图：`/Users/jamin/.codex/visualizations/2026/09/09/01a0868b-1a5a-7ee3-8554-72e8748781c0/workflow-compact-desktop.png`。
