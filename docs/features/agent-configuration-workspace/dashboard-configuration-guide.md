# Dashboard Agent 配置体系与操作指南

日期：2026-09-07。适用：当前 Dashboard Draft Workspace；ADR-0242 外部 Knowledge。

## 结论与配置分层

[KNOWN | HIGH] 配置服务已有 Control-owned Workspace、完整 Contract 校验、revision CAS、
原子审计与独立版本管理。本轮沿现有服务补齐内容编辑、有效检索参数、配置导航及读取一致性，
没有引入另一套配置数据库或浏览器执行权威。依据：
`proof_agent/control/agent_configuration_workspace.py` 的 `update_contract`、
`proof_agent/delivery/configuration_api.py` 与 `production_agent_configuration.py`。

| 层 | 使用者要回答的问题 | 当前入口与内容 | 保存和生效边界 |
| --- | --- | --- | --- |
| 身份与目标 | 它负责什么任务？ | Overview：名称、用途、Draft、活动版本 | 元数据保存不执行 Agent |
| 行为设计 | 如何处理任务？ | Workflow：阶段指令与上下文；Skills：业务包与资源范围 | 固定 V3 模板与服务器校验 |
| 模型与预算 | 谁规划、回答和复核？ | Model：回答、Planner、Reviewer 模型，ReAct 限制与复核模式 | 共享连接/凭证引用；模型不能扩大权限 |
| 知识与证据 | 从哪里找，找到多少，如何准入？ | Knowledge：Dify Dataset、内容格式、凭证引用；全局检索限制 | 外部候选 → ProofAgent 准入；远端内容可变 |
| 工具与策略 | 可调用什么，如何限制？ | Tools：启用、文件与完整工具契约；Policy：文件与完整规则 | Contract 校验、Tool Gateway、服务端授权 |
| 记忆与响应 | 保留什么、对外展示什么？ | Memory：作用域/保留期/召回；Response：简要摘要与复核结果 | 记忆不成为 Accepted Evidence，不保存原始思维链 |
| 验证与版本 | 哪次配置被测试，哪个版本生效？ | Validate、Contract、Publication、Versions、Monitor | 依据服务端 capabilities；Draft 不等于活动版本 |

[KNOWN | HIGH] 概览中的配置指南只展示服务器公布的模块，并区分可编辑和只读。
它不计算虚假的完成率，不把字段非空或编辑权限当作连接健康、回答质量或发布就绪。
入口：`dashboard/src/components/agent/ConfigurationGuide.tsx`。

## 已修复的配置断点

| 问题 | 影响 | 当前行为与证据 |
| --- | --- | --- |
| 草稿和契约独立并发读取 | 有机会把旧内容与新 revision 配对，削弱 CAS 对丢失更新的保护 | 读取 Draft → Contract → Draft；两次 revision 一致才交付编辑；最多两次尝试，不稳定时显式重载。`useConfigDraft.ts` 与对应 hook 测试 |
| 切换 Agent 后旧请求晚到 | 旧 Draft 或活动版本覆盖当前页面 | Draft 与 Versions 忽略过期异步结果。两个 hook 回归测试 |
| Policy 和 Tools 只提供路径 | 无法在 Dashboard 完成实际内容配置 | 高级 YAML 内容编辑与 agent.yaml 同次 Contract 保存；保持服务端完整校验、revision CAS 与失败输入。AgentDetailPage 页面测试 |
| 只有 Dataset 参数 | 操作者看不见真正限制候选数量、阈值与必要查询的全局设置 | 全局检索表单、默认值、单位、范围与叠加语义；拒绝空数值、整数预算小数及越界值。RetrievalModuleEditor 测试 |
| 多模块未保存修改混合 | 保存来源不清晰，或绑定保存导致另一区域输入丢失 | 当前模块保存/放弃后再编辑另一模块；可返回未保存模块；Dataset 与全局参数互锁。页面回归 |

[KNOWN | HIGH] 保存失败保留内容；409 不自动把旧修改覆盖到新 revision。Dataset 有已有的显式
Reload Latest；通用 Contract 可先保留/复制修改，再重载页面获得新 revision 后重新应用。
本轮没有增加自动合并规则，也没有使用 localStorage 存储草稿内容。

## 推荐操作顺序

1. 创建或打开 Agent，在概览明确任务用途。
2. 从配置指南进入 Workflow 与 Skills，明确阶段行为和资源范围。
3. 在 Model 选择回答、规划、复核模型。凭证管理使用共享连接服务。
4. 在 Knowledge 添加 Dataset、内容格式和凭证引用，保存绑定；再调整全局检索限制并保存。
5. 在 Tools 与 Policy 修改实际契约/规则。内容编辑目前为高级 YAML 编辑器，服务器执行完整校验。
6. 设置 Memory 与 Response。每个模块保存后再进入下一模块。
7. 在服务端允许时验证已保存的精确 revision；修改后重新验证。
8. 按当前部署公开的发布/版本入口操作，随后通过 Monitor 检查真实运行。

## 检索参数的真实含义

[KNOWN | HIGH] 以下来自 `bootstrap/manifest.py`、`bootstrap/validation.py`、
`control/knowledge/retrieval_service.py` 与 `bootstrap/composition.py`，并非通用 RAG 建议值。

| 字段 | 缺省值 | 约束与真实作用 |
| --- | --- | --- |
| retrieval.top_k | 3 | 正整数；每个 Dataset 取 min(全局, Dataset Top K) |
| retrieval.min_score | 0.2 | 0–1；采用 max(全局, Dataset 阈值) |
| retrieval.max_queries | 3 | 整数 1–5；限制意图准备时冻结的必要查询数量，不是总网络调用或并发预算 |
| retrieval.query_timeout_seconds | 20 秒 | 配置范围 0.01–120；当前 Dify 传输实际封顶 60 秒 |

[KNOWN | HIGH] 当前同步 Dify 路径未证明旧 `query_concurrency`、rewrite、rerank 开关具有对应效果，
因此本轮不把它们包装成可工作的开关。数据集 Top K 和全局候选上限不是总证据数量上限。
远端 Dataset 内容变化不会随 Agent 版本回滚。

## 验证边界与后续产品演进

[KNOWN | HIGH] 当前产品只有 `react_enterprise_qa_v3`；不增加用户账号管理、审批流程、任意脚本、
MCP stdio 或生产写工具。生产外部 Knowledge 发布 profile 与真实依赖验证仍以项目既有计划为准，
本轮不能用浏览器表单恢复未开放的生产动作。

[INFERRED | MED] 若要进一步降低非技术运营门槛，下一步应以服务端策略/工具 Schema 及错误字段
定位为依据建设可视化规则编辑器，再考虑配置版本差异与合并。当前完整文档内容可编辑，
但尚不是可视化规则设计器；任意新增开关都应先确认其执行效果。

[KNOWN | HIGH] 本轮未统一 Workflow Stage 和 Skill drawer 内部编辑状态，也不承诺浏览器关闭、
外部链接或直接切换路由后的未保存草稿恢复。当前保护覆盖页面模块导航、通用 Contract 编辑和
Dataset/全局参数交叉保存。真实连接、端到端模型质量和生产发布不是隔离 UI 验证的结论。

## Workflow 单一 Prompt（2026-09-09）

Workflow 的可编辑节点使用一个 Prompt 输入框。可以自由编写，也可点击“插入结构模板”，
插入 Business Context、Task Instructions 和 Output Preferences 三个章节及填写提示。
模板不预填保险或其他业务指令，内容由用户填写。模板追加到现有内容末尾，章节可任意
修改。非模型执行节点显示无需配置提示。

旧的 Business Context、Task Instructions、Output Preferences 会按顺序合并显示，
保存后统一文本使用现有 `prompt.business_context` 承载，两个列表字段清空。仅查看不会
保存或迁移 Draft；高级 YAML/API 字段继续兼容既有契约。Skills 模块的独立配置不受影响。

预览、保存和 YAML 投影使用同一份文本，编辑后旧预览失效。整个 Workflow 的提示文本仍
受 12,000 字符总预算及内容校验约束；运行上下文仍有长度限制，长文本需检查预览中的
truncation 标记。保存后应通过实际问题验证效果。设计依据：ADR-0251。
