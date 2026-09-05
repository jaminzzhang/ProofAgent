# P0-1B：质量评估口径

[FRAME | HIGH] 2026-09-05，用户授权继续优先顺序交付。准入结论：`TDD_INPUT_READY`。本切片沿用 hicode Scope → TDD → Review；最高风险 P1：把治理检查成功或不可信样本误计为质量成功。

## 交付范围

[KNOWN | HIGH] 当前 Analyzer 的 `forbidden_claim` 在没有语义断言时返回诊断性 PASSED，有断言时返回 NOT_EVALUATED；GRR 排除诊断 Gate。因此 GRR 不能作为答案正确率。依据：`proof_agent/evaluation/gates.py`、`analyzer.py` 和 P0-1A 证据。

[FRAME | HIGH] 在现有 Analyzer 和 artifact writer 中新增独立质量结果，不增加 Agent 执行路径、外部 judge 或未绑定的质量通过输入。既有 GRR、Gate Profile、Release Decision 和 `judge_mode=none` 保留原义。公共契约决策见 ADR-0240。

| 节点 | 输入/处理 | 可观察结果与验收 |
|---|---|---|
| CLASSIFY | `quality_target` 可选；旧套件仅在 expected resolution/outcome 一致时推断回答或拒答；任务必须显式标注 | 严格枚举；显式矛盾标签拒绝；无法分类的 required case 保留 target=null，不静默删除 |
| TRUST | subject 与同一字节快照的 artifact 摘要、完整 Trace/Receipt outcome | 缺失、哈希不符、LOCAL_ONLY、未完成/相互矛盾的记录均为 not_evaluated；最后 final_output 自身必须有结果，不能由旧事件或 metadata 补足 |
| ANSWER | 已验证记录与应答 gold 比较 | 错误 outcome/确定性 Gate 失败为 failed；引用合法、词项匹配或治理通过不能替代语义核验，仍为 not_evaluated |
| REFUSAL | 与人工维护的拒答决策 gold 匹配 | 只有全部必需治理检查通过、artifact 充分且没有待评语义声明才 passed；不证明措辞质量或知识库确实无答案 |
| TASK | 显式 task_completion 用例 | 工具成功或已输出答案不构成任务完成；缺结果核验为 not_evaluated |
| METRICS | 只统计 required standalone cases | 三个 cohort 各自 total=passed+failed+not_evaluated；未分类单列；optional/extra subjects/scenario steps 不扩大分母 |
| REPORT | JSONL case 明细、质量汇总 JSON、Markdown 与分析 Receipt | 状态、原因、分母及逐项是否纳入统计一致；空分母的比例为 null；未评估保留分母；不输出响应正文 |
| RECOVERY | 某个已映射样本不可读/损坏 | 该 case 治理结果失败且质量未评估，继续分析其余样本；固定脱敏错误原因，整个正式分析不能因其缺失通过 |

## 指标定义

- `verified_success_rate = passed / total`，`total=0` 时为 null。这是全部既定样本中已证实成功的比例，不是未评估样本的正确率估计。
- `assessment_coverage_rate = (passed + failed) / total`，空分母为 null。全部未评估时两项比例都是 0，且 not_evaluated=total。
- 回答和任务暂缺正向核验能力，不能输出成功；拒答的正向口径限定为 curated refusal decision matched。
- 可选用例和 scenario step 仍有逐项质量明细，但不参与本切片的 standalone 汇总。真正的场景任务完成率留给任务完成条件切片。

## TDD 与验收顺序

1. 真实 Analyzer tracer：绑定的治理成功应答仍不得计为正确回答。
2. 拒答正例及将相同拒答套入应答 gold 的反例；任务成功状态不可冒充完成。
3. 固定分母、空集、未分类、可选用例和 scenario 重复引用；严格公共契约。
4. 损坏/不可信 artifact 优先级与继续分析；机器产物和 Markdown 一致性。
5. 独立 Review、全部受影响评估回归、Ruff/Mypy、文档检查、P0-1A 探针重新执行；记录准确结果。

## 风险与边界

[FRAME | HIGH] 无新存储权威、网络依赖、数据库迁移、权限或生产配置变更。只在现有分析目录增加质量投影文件；它不授权发布或执行。读取旧 case 结果时，质量与统计纳入标记缺失均保持 null，不能默认判通过。EvaluationCase 及其 expected 的未知字段改为拒绝，防止质量标签或语义断言拼写错误被忽略；现有受支持套件必须回归通过。

[INFERRED | HIGH] 本切片不修复答案生成、任务规划或真实语义核验；其价值是阻止指标把这些能力缺口隐藏。回滚为撤销本切片新增质量契约、分析投影和文档；保留 P0-1A 历史证据。
