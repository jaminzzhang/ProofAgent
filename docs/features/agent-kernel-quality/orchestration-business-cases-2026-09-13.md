# Orchestration 业务任务合成开发验证（2026-09-13）

此文件按 [业务任务验证模板](../../testing/business-task-verification-template.zh-CN.md)记录预先期望。全部材料是 synthetic，只验证受支持的控制行为，不证明实际理赔规则、真实模型质量、独立 holdout 或部署状态。源码版本以执行时 Git 状态为准；执行入口为离线 Python 组合/编排测试，无外部模型、服务或写工具。案例标注版本 `bc-dev-v1`，开发回归集；尚无独立业务标注人与复核人。

各案例将运行终态、治理、事实正确、任务完整、预期匹配分开记录。`ANSWERED_WITH_CITATIONS` 仅为运行终态；未实现的通用语义判断记 `unassessed`。执行结果与测试代码映射见下表；本套件不作为 Evaluation Suite 或 Release Gate。

| ID / 业务原话或目标 | 独立给定的参考事实、条件和必需输出 | 预期终态与判定 | 测试映射 |
| --- | --- | --- | --- |
| BC-PERF：甲公司业绩有哪些亮点、较好与承压业务？ | E1：合成 2026 Q1 寿险营运利润 100.00 亿元，同比 +6.4%；E2：同季度寿险新业务价值率 23.5%，同比下降 4.8 个百分点。R1/R2 同时表达增长和压力，保留主体、期间、单位、方向及寿险范围；改成 35.2 属事实错误，只答 E1 属完整性错误。 | 完整输出的受支持领域检查通过；错误数值应触发 `answer_facts` 失败；遗漏压力应触发 `final_answer_adequacy` 失败。人工业务质量仍未独立评估。 | `test_performance_complete_and_wrong_or_omitted_pressure_are_separate` |
| BC-ASK：集团年度业绩，但必需口径/期间缺失；对照为可默认的表达偏好。 | R1 必需上下文不能猜；R2 可选偏好有明确安全默认时披露假设并检索。合成无证据源，不能编造业绩。 | 必需项为 `WAITING_FOR_USER_CLARIFICATION`，业务未完成；可选偏好进入 `plan_retrieval` 且不能宣称已回答。 | `test_required_context_asks_but_defaultable_preference_progresses` |
| BC-INJECT：理赔检索文本企图要求未授权 `customer_lookup`。 | R1 内容里的命令不是工具授权；有效工具权限由 Control Plane scope 决定。当前测试将恶意目标表示为 planner 提案，尚未把注入文本放入真实检索候选。 | 提案在工具范围门禁拒绝，无工具执行；这只验证权限边界，不验证模型是否遵从注入。 | `test_untrusted_tool_request_does_not_grant_out_of_scope_capability` |
| BC-UNKNOWN：解释所有适用理赔条件和例外。 | R1 需要完整条件、例外、适用性；现有通用 `answer_coverage` verifier 没有该领域完整语义依据。即使检索到材料并形成回答也不得臆造完成。 | Task assessment `unassessed`、phase `paused`；业务交付完成为否。 | `test_unknown_business_analysis_does_not_complete_task` |
| BC-LITE：比较两份保单，需两项查询。 | E1/E2 分属必需查询 `QUERY_A`/`QUERY_B`，不能因 lite 省掉其中一项。 | 允许升级时两个查询均执行，effective complexity 为 `standard`；上限封顶时明确阻断且不执行残缺查询。 | `test_lite_multi_query_escalates_or_preserves_all_requirements` |
| BC-BUDGET：Task 首次运行已用尽一次检索配额，后续恢复。 | R1 累计 `retrieval_calls=1` 持久记录；再次检索是超额，不能清零或多执行。 | 恢复的 ledger 保持已消耗值，并在额外分发前报 `retrieval_calls_exhausted`。当前仅测预算组件恢复，完整 Task 多 Run 集成另见 `tests/test_workflow_task_package.py`。 | `test_budget_restore_keeps_consumed_capacity_and_blocks_extra_work` |

尚未实施的高价值案例：理赔等待期与急诊例外、既往症除外的优先级和适用性；住院材料与异地急诊额外材料的多问题完整性；寿险和银行正反指标及表格脚注跨业务完整性；候选 Knowledge 文本中的提示注入从检索、准入到回答的端到端处理；预算耗尽后真实 Task 多 Run 恢复且不重复已完成工具结果。这些需要独立的规则单元/证据锚点、来源日期、权限和当前受支持的验收 profile，不能先从模型回答倒推 expected。

运行记录（2026-09-13，本地）：`uv run --extra dev python -m pytest tests/test_orchestration_business_cases.py -q` 为 `6 passed in 0.44s`；`uv run --extra dev ruff check tests/test_orchestration_business_cases.py` 与 `git diff --check` 通过。
最终完整后端回归为`3043 passed / 102 skipped / 2 deselected`，其中包含上述6个案例与另外17项编排/Prompt专项检查。
源码包含未提交改动，基础HEAD为`2ae4fae`；相关源码和测试的文件哈希、最终JUnit摘要与验证边界见
[验证记录](orchestration-verification-2026-09-13.json)，流程分析和结果解释见
[编排与Prompt报告](orchestration-prompt-review-2026-09-13.md)。
离线测试未生成可发布的Run/Trace/Receipt。固定合成回归与真实模型、浏览器及部署验证分开报告。
