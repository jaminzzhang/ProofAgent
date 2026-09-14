# run_d9e43d0e — 购前咨询的上下文依赖修复

[KNOWN | HIGH] 历史 Trace 表明：公开产品检索尚未开始，已规划的三个必需查询被
“用户是否已投保该产品及具体保单信息（如有追问需要）”阻断。
原问题要求产品保障说明及购前适合性分析；Trace 已保留三个个人信息缺口。
原始模型交互未被 capture 保存，不能断言当时具体如何标注该字段。

[FRAME | HIGH] 服务产品目标 1、2、3：仅为当前子任务建立信息依赖，保留问题范围，
先回答有据的独立部分，再询问真正影响适合性的个人信息。设计见 ADR-0263。

| 用户要求/边界 | 必需证据或输入 | 输出要求 | 验证入口 |
| --- | --- | --- | --- |
| 30 岁，问指定寿险保障及是否适合买 | 必需公开查询；条款仍须准入、引用及复核 | 不以已有该产品保单为前提；先推进检索 | required_context、无分类两个回归 |
| 缺预算、需求等个人信息 | 公共证据与剩余个人缺口分开 | 保留 deferred_answer_fields，部分答案后主动问询 | 预算与保单字段并存对照；原 partial-answer 编排用例 |
| Planner 再次提出保单资料 | 相同当前请求、必需查询 | 不重新暂停 | 真实 Orchestrator + synthetic ports |
| 已有保单理赔/退保，或混合个案请求 | 具体个案输入 | 保留必要澄清，不能套购前例外 | 既有保单及混合请求对照 |
| 身份、权限、工具输入、冻结 Task 必需上下文 | 对应硬性输入/授权 | 不放行，不执行依赖动作 | compound 字段、tool_input、Task 对照 |
| 无独立查询、工具建议、REFUSE、未知字段 | 保持原有约束 | 不因出现“保单”二字而放行 | negative/boundary 用例 |

[KNOWN | HIGH] RED：原字段 required_context 与无分类均误返回 ASK_CLARIFICATION；
Sol Low 子 Agent 独立构建的初始用例得到 2 failed / 9 passed。修复同时覆盖
Intent normalization、Planner 和两个模型阶段的系统 Prompt；未更改用户配置、
历史 Run 或模型契约字段。

验证命令：

```bash
.venv/bin/python -m pytest tests/test_purchase_context_dependencies.py tests/test_partial_answer_clarification.py tests/test_partial_answer_orchestrator.py tests/test_clarification_policy.py -q
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check proof_agent tests
.venv/bin/mypy proof_agent
.venv/bin/python scripts/check-domain-contexts.py
git diff --check
```

[KNOWN | HIGH] 验证结果：Sol Low 独立用例及相关澄清/部分回答回归 54 passed；
后端全量 3,106 passed、102 skipped、2 deselected（在最后五项边界用例加入前收集）；
最后新增边界已包含在上述 54 项定向回归中。Ruff、Mypy（425 个源文件）、
领域索引检查与 diff 空白检查通过。两条现有依赖警告仍在。

本地合成测试验证编排行为；并未重新调用外部模型或 Knowledge。
最终真实回答的适合性分析、原文引用、覆盖度仍需单独业务验证。
有界中文规则可能保守地保留未识别同义表达的缺口，不宣称通用依赖推理已证明。
状态：PARTIAL_VERIFICATION。
