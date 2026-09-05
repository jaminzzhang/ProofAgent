# P0-2：必需检索要求的完成门控

[FRAME | HIGH] 用户于 2026-09-05 授权「提交 git，并继续下一切片」。前置切片已提交为 `4cf7c73`。本切片按 Scope → TDD → Review 交付；2026-09-06 完成本地验收，见 [tdd-p0-2.md](tdd-p0-2.md)。最高风险 P1：用首个观察、未绑定内容或模型自述作为全部任务完成证明。

## 目标与边界

[KNOWN | HIGH] 切片开始时，`action_control._detect_answer_ready` 仅检查最后一条观察的 accepted count 和空 unresolved subgoals；`composition._context_summary` 同样优先提示生成答案。P0-1A 的两个 required 查询探针因此只有一个查询执行。已有 `IntentResolution.retrieval_query_set`、不可变 Run State、摘要绑定的 Observation Truth 与最终 AnswerEvidenceContext 可复用。

[FRAME | HIGH] 本切片交付「每个必需检索查询均有可引用的 Accepted Evidence」这一完成门控。它是生成答案的必要条件，不是语义正确性或业务任务整体完成证明；P0-1B 的 answer/task 正向质量验证仍为未评估。ADR-0241 记录控制规则。

| 设计节点 | 规则 | 验收结果 |
|---|---|---|
| REQUIRE | 从首次已验证 Intent 中 required=true 的查询派生固定要求；原 Intent 显式冻结并随原 snapshot 保存 | planner、memory、summary 不能删除要求；仅首尾空白归一化；完全相同查询去重；optional 不阻止完成 |
| PROVE | 从已绑定且与本 Run/record 身份一致的 RetrievalObservationTruth 派生进展 | 实际 admission_metadata.query 与要求精确匹配；ACCEPTED chunk 的非空白 source 在 record 中，非空白 citation 同时在 truth/record 中；不信 count、planner 参数或工具成功 |
| PLAN | 尚有未执行要求时保持检索可选；过早 final 或重复/无关检索提议转入未执行的 required query | 新提议仍走原 Review、Policy、精确 KSS binding；不复用工具参数；风险等级不降级 |
| FINAL | 调用 synthesis 前重新验证同一完成门控 | 未完成不能调用生成；全部必需查询完成后所有已准入事实进入既有答案输入 |
| BLOCKER | 检索覆盖不覆盖明确 REFUSE/ASK 或业务、检索 unresolved subgoal | 准入拒答原因保留；历史冲突不因另一查询成功而消失；工具审批拒绝事实保留，但允许既有合法替代检索路径作答 |
| NO_PROGRESS | 已尝试但没有有效证据的要求保留未完成；先执行其他未尝试要求 | 全部尝试后仍不满足则明确拒答，不在同一失败查询上反复消耗预算 |
| BUDGET | 原有 max_plan_rounds 限制观察动作；未完成且达到上限停止 | 返回固定预算不足原因与未完成数量；已完成要求可在最后一个观察恰好耗尽预算时进入最终答案，不再执行观察 |
| RECOVER | 从 snapshot 中原有冻结 Intent 和 bound truth 重新派生进展 | 不增加 snapshot 字段或改变摘要格式；恢复不再调用 Intent 模型；损坏、跨 Run、替换 truth 均拒绝，在后续观察和工具执行前验证 |
| AUDIT | 输出版本化完成投影，仅含要求 ID、完成数量、未完成 ID、绑定 truth 引用和原因 | 不新增原始查询、回答、模型提示或工具返回正文；Trace 与 plan stage 可解释门控 |
| COMPAT | 无 required query 的调用不启用门控 | 保留原有执行语义，明确 not_applicable；不宣称空任务完成 |

## 实现选择

[FRAME | HIGH] 使用独立、纯计算的 `task_completion` 模块，从已冻结的 Intent 和已核验的 Observation Truth 重算进展。不另建数据库、执行循环或可由模型写入的完成账本；不增加 snapshot 默认字段，避免旧摘要因新增默认值失效。Run 内要求身份按规范化查询的 SHA-256 派生，跨 Run 的证据不能复用。

[FRAME | HIGH] 通过 Orchestrator 的 plan constraint 与 synthesis 前检查执行门控。仅调整提示词无法防止模型提前作答；仅移除 final action 又会被既有默认约束改写成拒答，均不足以满足继续执行的要求。

[KNOWN | HIGH] Trace 的封闭枚举新增 `task_completion_evaluated`，仅在门控适用时发出，固定 `stage_id=plan`。真实 TraceWriter 已验证事件序列与无正文投影；无 required 查询的旧调用不增加该事件。完成、拒答、澄清及工具 policy/scope 拒绝结果在最后一个 plan stage 附同一版本投影。现有审批等待与其快照仍使用原格式，等待前进展可从计划事件读取。

## TDD 顺序

1. 通过真实 composition + synthetic 外部模型/KSS，重现两个 required 查询只执行一个，修到两份已准入事实共同进入最后答案请求。
2. 验证过早 final、optional、重复查询、不同查询相同证据数量、证据为空及预算边界。
3. 验证 summary/参数伪造、Candidate/Rejected、无 citation、Tool success、truth/run 身份与恢复；Policy/Review 拒绝不得绕过。
4. 验证审计投影与旧调用；重新运行五个内核探针、受影响回归、Ruff/Mypy 和文档检查；独立 Review 后记录全部证据。

## 限制

[FRAME | HIGH] 不增加生产写工具、审批产品流程、通用任务执行器、跨轮重规划权威或跨对话持久化机制。本门控可能使原先遗漏的单个 required 改写查询得到执行；这属于查询完成约束的结果，不表示 P0-3 的结构化事实与完整证据链已经验收。语义等价查询和多事实语义覆盖仍待后续类型化/语义验证。

[FRAME | HIGH] 回滚仅撤销本切片的派生门控、审计投影与文档；已提交的质量测量切片及历史探针证据保持不变。当前范围和用户授权足够，无待用户确认项。
