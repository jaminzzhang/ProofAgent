# run_35395fed：输出预算截断修正

2026-09-14 更新：下文的 8192 Token 是本轮故障修复的中间默认值；
随后用户要求的 64K 默认值已取代它。当前默认 `reserved_output_tokens=65536`、
`max_total_tokens=262144`、`max_active_seconds=600`，详见
`64k-output-and-timeouts-2026-09-14.md`。下文验证计数为当时的历史快照。

[KNOWN | HIGH] 2026-09-13，Run 已完成检索，Intent deferred_answer_field_count=4，
blocking_field_count=0。两次 Final Answer 均 finish_reason=length、output_tokens=2048，
输出字符数分别为 3715、3583。Capture 仅保留 JSON 解析失败状态，未保留可重建的完整答案。
这次不是缺少证据或个人信息前置阻断，模型复核尚未执行。

根因：ADR-0260 增加分析正文、原文引用与 coverage 后，默认输出预留仍为 2048，
BudgetedModelProvider 将其作为实际每次输出硬上限。修复请求未说明截断，沿用相同上限。
因此原调用和修复均产出不完整 JSON，而诊断只给出 schema_failed，未暴露截断类别。

[FRAME | HIGH] 默认输出预留调整为 8192，Dashboard fallback 和配置示例同步。
总 Token、时间和调用次数预算不变；显式小上限不被提高，所有调用继续先预留再结算。
该默认影响未显式配置输出预留的工作流，不会重写已有 Draft 字段。
当前 Draft 和其模型连接均未显式配置输出 Token 上限，重启后使用新默认。

finish_reason=length 直接生成 model_output_truncated 诊断，即使内容偶然可解析也不交付。
普通解析错误同步保留 parse error violation code。一次修复明确要求压缩正文和重复引文、
保留条件、全部 coverage 和主动问询；修复保留原 request 的输出/超时约束。
持续截断时返回明确输出上限提示，不将残缺内容伪装成成功答案。

[KNOWN | HIGH] 新的 test_answer_output_budget.py 在修复前 2 failed：默认限额无法交付、
截断没有可识别诊断。修复后覆盖默认完整交付、显式小上限持续截断、同限额压缩恢复、
可解析但 length 结束仍拒绝四种行为。全后端 3082 passed / 102 skipped / 2 deselected
（当时包含前两项新用例）；后补两项与关联回归单独验证。mypy 424 源文件、Ruff、
Dashboard WorkflowPolicyEditor 六项通过。

PARTIAL_VERIFICATION：本地合成 provider 复现了实际预算与截断路径；没有向外部模型
重放该 Run，也不能保证更大预算解决所有真实模型输出问题。保留原 Run 不改写。
