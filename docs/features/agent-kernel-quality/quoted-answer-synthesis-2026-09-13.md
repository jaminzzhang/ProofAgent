# 总结分析与引用原文：实施及验证记录

日期：2026-09-13。决策：[ADR-0260](../../adr/0260-synthesize-answers-with-bound-source-quotes.md)。

## 目标与最终行为

[FRAME | HIGH] 根据用户明确授权，回答允许 LLM 总结、改写、合并多段事实及解释表格，
并在回答中展示引用原文。服务“准确且完整交付”和“证明结果与过程”两个核心目标。
背景是 run_6ed2bd2f 的摘录式回答；该历史 Run 不被修改，也不是新实现的真实模型质量证明。

[KNOWN | HIGH] 正常链路现在是：
用户要求与 Task 上下文 → Accepted Evidence → 分析正文/原文引用/逐项 coverage →
Control 原文绑定与安全检查 → 单独的模型复核 → 编号原文交付。
模型复核不通过时进行有界的正文与引用修复并再次复核，取消自动 source-ID 拼接恢复。
needs_evidence 可进入原有受控补检；needs_user_input 保留必要个人信息缺口。

## 系统契约

- message：自然语言解释与分析，可以改写、合并、解释表格，保留条件与事实口径。
- citations：已准入证据的精确引用标识。
- quotes：每项含 claim、text、citation；claim 必须出现在正文，text 必须来自绑定来源，
  原文匹配仅规范化空白。Control 在正文插入编号并在末尾呈现原文 literal blocks。
- coverage：每个用户 requirement ID 恰好一次，状态为 answered、needs_evidence 或 needs_user_input。
- review：claims_supported、conditions_preserved、requirements_addressed 三项均须通过。
  使用同一回答 provider/model 的单独 HARNESS_REVIEW 调用，纳入原有授权、Token/调用预算和 Trace。
  它不是独立模型仲裁，也不提供确定性语义证明。

[KNOWN | HIGH] 伪造原文、错误引用、确定性同源数值冲突、缺少 coverage、越界大小、
不通过或缺失的复核仍被拒绝。复核绑定最终正文和 Accepted Evidence 哈希，改动后不能复用。
旧 message/citations 形式仅保留原文/确定性表格及 typed adapter 兼容，不开放无引文分析旁路。
中文空格、原有安全展示前缀和保留脚注的表格投影仍可使用。

[KNOWN | HIGH] Task 的语义验收项仍为 unassessed；model_assessed 的 disposition 单独呈现。
ANSWERED_WITH_CITATIONS 不自动代表所有业务验收完成，strict assurance 仍拒绝未评估项。

## 回归用例与执行证据

分析与实现由当前主 Agent 完成；Sol Low 子 Agent 使用合成证据、脚本化模型端口执行验证，
未调用外部模型/Knowledge 进行业务 replay。

| 用例 | 预期 |
| --- | --- |
| 改写、合并、表格解释并附真实原文 | 通过绑定后还须复核，交付正文及编号原文 |
| 原文正确但年龄事件时点推断错误 | conditions_preserved=false，修复后重新复核 |
| 两个子问题只答一个，或缺少个人信息 | 拒绝假完整；补检或明确缺口 |
| 假原文、错来源、缺少 quotes 试图自由分析 | 不得通过 |
| 同源互斥数值 | 保留硬失败，不因模型复核放行 |
| 复核拒绝、异常、超预算或 policy 拒绝 | 不交付未经复核的分析 |
| 正文/证据变更后复用结果 | 哈希绑定拒绝 |
| 原文含 Markdown、HTML、连续反引号 | 保留为 literal block，不逃逸成可执行标记 |
| Task 要求语义完成、strict assurance | 模型复核通过也不能自动证明完成 |

[KNOWN | HIGH] 验证过程先暴露了旧逐句门禁、原文分析旁路和展示兼容失败；
修复及测试迁移保留原有负例，不用跳过用例消除失败。最终执行：

- Host 后端全集：3073 passed、102 skipped、2 deselected，2 warnings，45.03 秒。
- 新契约、复核、端到端与边界四文件：30 passed，0.68 秒。
- mypy：424 个源文件通过；受影响文件 Ruff 通过。
- domain-context 检查及 git diff --check 通过。

主要用例：test_quoted_answer_contract.py、test_answer_grounding_review.py、
test_quoted_answer_workflow.py、test_quoted_answer_boundaries.py；
兼容迁移覆盖 answer_fact_validation、performance_answer_contract、answer_context_continuity、
prompt_contract_alignment、task_answer_workflow。

## 限制与后续业务验证

[KNOWN | HIGH] 本记录是 PARTIAL_VERIFICATION。固定 fake-provider 用例证明流程和契约，
不能证明真实模型判断可靠；同模型复核可能存在相关错误，增加调用与 Token 成本。
未进行真实产品问题 replay，也未验证外部证据的权威性、新鲜度或全面性。
按[业务验证模板](../../testing/business-task-verification-template.zh-CN.md)使用独立业务标注，
重点检查“保障内容 + 30 岁适合性”、免责与现金价值条件、信息缺口以及结论和引文的推导关系。

本次不改变原有 Run。重启本地后端后，新请求采用新契约；已有配置与历史记录保留。
未执行 commit、push 或生产发布。
