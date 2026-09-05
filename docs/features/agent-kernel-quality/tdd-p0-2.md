# P0-2 验收记录

[COMPUTED | HIGH] 切片结论：`LOCAL_VERIFIED`。必需检索完成门控已完成本地验收：新增 55 项测试，受影响回归 482 passed、3 个既有 skip；Ruff、Mypy 与独立 Review 通过。最终评审建议：`NO_BLOCKING_FINDINGS`。整体路线仍为 `PARTIAL_VERIFICATION`；检索覆盖不等于答案语义正确或业务任务整体完成。

[KNOWN | HIGH] 范围见 [scope-p0-2.md](scope-p0-2.md)，决策见 [ADR-0241](../../adr/0241-gate-final-answers-on-required-retrieval-evidence.md)。分支为 `codex/agent-kernel-quality-baseline`，基准提交为 `4cf7c73`，验收日期为 2026-09-06。P0-1A/P0-1B 的历史产物保持不变。

## 实现与控制顺序

[KNOWN | HIGH] 新增内部 `task_completion.py`，复用现有 Orchestrator、Review/Policy、Observation Committer、Truth Store 和 AnswerEvidenceContext。唯一公共事件变更是在 `TraceEventType` 增加 `task_completion_evaluated`；没有增加 Run State 或 snapshot 字段，没有另建执行循环、完成账本或知识权威。

1. 首次 Intent Resolution 的结果显式冻结。对其中 `required=true` 的查询仅去除首尾空白并去重，按完整查询 SHA-256 派生要求 ID；保留原 Intent 随既有快照保存。
2. 每轮从原要求与实际 bound truth 重算进展。证明必须属于当前 Run 和 observation/action 身份；检索 truth 的实际查询精确匹配，并含有来源、引用均可用的 ACCEPTED chunk。
3. 有未尝试要求时，过早 final 或重复、无关、非法形状的检索查询转为下一个 required query。新提议保留风险等级和 risk flags，只携带新查询参数，再进入原 Review、Policy 与精确 KSS binding 路径。
4. 空结果或未准入结果保留未完成，同时继续其他未尝试要求。全部尝试仍未满足或观察预算耗尽时明确拒答，不调用 synthesis；最后一个允许的观察恰好补齐要求时，可以进入答案阶段。
5. 显式拒答和澄清优先保留。业务、检索 unresolved subgoals 不因另一查询成功而消失。审批拒绝仍保留为 observation；既有合法替代检索可以补齐证据，但不会执行被拒工具。
6. synthesis 前复核同一份已验证 AnswerEvidenceContext；快照恢复在执行任何后续观察前验证原始证据。答案后的投影复用已计算结果，不在 memory write 后重新读取 truth。
7. 完成事件与终止 plan 投影只携带版本、状态、固定原因、要求 ID、数量和绑定引用。无 required 查询时结果为 `not_applicable`，保持原有行为和 Trace 事件序列。

## 逐项验收

[COMPUTED | HIGH] 下表由 [test_retrieval_task_completion.py](../../../tests/test_retrieval_task_completion.py) 的 55 项测试覆盖；均已通过。外部模型、KSS、工具采用固定 synthetic 边界，composition、主循环、证据提交、文件存储及 TraceWriter 使用实际实现。

| 编号 | 场景 | 验收结果 |
|---|---|---|
| C01 真实组合 | 两个 required 查询；或模型始终只提议 final | 两个查询均到达 KSS，两份已准入事实共同进入最终模型输入 |
| C02 主循环 | Planner 过早 final、重复第一查询、连续三个查询各返回一份证据 | 逐一执行未尝试要求；不因相同 evidence count 触发过早收敛 |
| C03 要求身份 | optional、完全相同查询、首尾空白、大小写和标点差异 | optional 不阻塞；仅完全相同规范化查询去重；大小写和标点不同仍是不同要求 |
| C04 空集与损坏 | 缺省、空集、全 optional；错误集合类型、非布尔 required、缺字段、空白 query、超过 5 项 | 前者 `not_applicable`；损坏要求显式拒绝，不当作空任务完成 |
| C05 预算 | 观察预算为 0、1、2，需两个查询 | 分别执行 0、1、2 个查询；前两者带预算不足原因拒答，第三者允许最终生成 |
| C06 未完成 | 第一 required 无证据，第二有证据 | 两者均尝试；明确剩余 1 个要求；无部分答案或无限重试 |
| C07 假进展 | Candidate、Rejected、缺 citation/source、空白 citation/source、夸大 count、错误 metadata.query | completed count 不增加，不调用答案生成 |
| C08 工具成功 | 工具自报 success/all_requirements_complete，伪造计数 | 不计为检索证明；执行剩余 required 查询后才能作答 |
| C09 固定要求 | Planner 尝试修改 Intent 集合或 required 字段 | 冻结对象拒绝修改；模型与能力边界不能删除原要求 |
| C10 安全终止 | 检索完成或预算耗尽时明确 REFUSE/ASK；早期观察仍有冲突 | 保留原拒答、澄清及业务准入原因；另一查询成功不能消除冲突 |
| C11 风险与授权 | 高风险 final 被转为检索；Review、工具 Policy、工具 Scope 拒绝 | 风险等级和标记保留；原工具参数被移除；拒绝时无越权执行，投影带固定原因 |
| C12 恢复 | 查询 A 后等待工具审批；新 Orchestrator 和文件适配器恢复 | Intent 只调用一次；复用 A 的原 truth，仅补查 B；原事实和证明引用保留 |
| C13 损坏恢复 | 文件 truth 缺失或 metadata 被替换 | 在恢复后的工具和检索调用前拒绝，无答案生成 |
| C14 证据身份 | 跨 Run、未绑定、内容篡改、action ID 或 record ref 不一致 | 均拒绝；自洽但属于另一 Run 的摘要也不能复用 |
| C15 替代路径 | 工具审批拒绝后，合法 required 替代检索补齐要求 | 允许基于替代证据作答；工具调用次数为 0，拒绝 truth 仍保留 |
| C16 审计与兼容 | 真实 TraceWriter、未知拒答原因、非字符串提议参数、旧无要求调用 | 新事件可持久化，无原查询/答案正文；未知原因规范化；非法参数形状不使门控崩溃；旧事件序列不变 |

## RED → GREEN → REFACTOR 与评审

| 阶段 | 实际证据 |
|---|---|
| 复合任务 RED → GREEN | 真实 composition 首轮只执行 A，测试失败；修复后 A/B 均到达 KSS。再加入始终 final 的 Planner 反例并修复 |
| 完成与预算 RED → GREEN | 预算、optional、重复和空证据等 5 项失败、3 项通过；加入进展、拒答和投影后 8 项通过 |
| 首轮评审 RED → GREEN | 明确 REFUSE/ASK 被改成答案，以及空白 refs 被算作证明：8 failed、15 passed → 全部通过 |
| 恢复与阻断 RED → GREEN | 增强断言后，丢失/替换 truth 在工具执行后才失败，且早期冲突被另一查询掩盖：3 failed、47 passed → 50 passed。另有 4 个 identity fixture 初稿缺少 `/truth`，已修正，不计作产品缺陷 |
| 真实 Trace 集成 RED → GREEN | 扩大回归发现 4 个 package/API 测试因新事件未注册失败；独立 TraceWriter 反例同样失败。补齐封闭枚举后 57 项相关测试通过 |
| 最终评审 RED → GREEN | 审批拒绝后的合法替代路径被阻断、工具拒绝缺投影；同时增加两个未类型化参数反例：4 failed → 全部通过；补工具 scope 投影验收后 55 项通过 |
| 最终整理 | Ruff 格式化；原主循环、快照、文件存储、评估、知识客户端、Trace 与 Receipt 回归共 482 passed、3 个既有 skip；没有新增 skip/xfail 或降低旧断言 |

[COMPUTED | HIGH] 独立评审提出的终止动作覆盖、空白引用、审批替代路径和拒绝投影问题均已关闭；最终复审独立执行 5 个关闭项测试并给出 `NO_BLOCKING_FINDINGS`。本记录保存验收结论；没有另行创建 Review 报告或发布审批记录。

## 实际验证

[KNOWN | HIGH] 工作目录为仓库根目录。所有 Python 测试使用 `PYTHONDONTWRITEBYTECODE=1`，未读取 `.env`，未连接真实模型、KSS、数据库、对象存储或生产服务。

```bash
.venv/bin/python -m pytest -p no:cacheprovider tests/test_retrieval_task_completion.py -q
# 55 passed

.venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_retrieval_task_completion.py tests/test_agent_kernel_baseline.py \
  tests/test_evaluation*.py tests/test_agent_package_execution.py \
  tests/test_react_intent_resolution.py tests/test_react_planner.py \
  tests/test_react_loop_control.py tests/test_controlled_react*.py \
  tests/test_run_executor_snapshot.py tests/test_knowledge_source_service_client.py \
  tests/test_model_output_validators.py tests/test_context_assembler.py \
  tests/test_trace*.py tests/test_receipt*.py -q -rs
# 482 passed, 3 skipped

.venv/bin/ruff check proof_agent tests scripts/check-agent-kernel-baseline.py
# All checks passed

.venv/bin/mypy proof_agent
# Success: no issues found in 377 source files

.venv/bin/python scripts/check-domain-contexts.py
# exit 0

git diff --check
# exit 0；另检查所有本切片新增文件的空白与文档链接

.venv/bin/python scripts/check-agent-kernel-baseline.py \
  --output-dir docs/features/agent-kernel-quality/evidence/p0-2/kernel-baseline
# exit 1；2 项 passed_with_diagnostics，3 项 needs_review，无 probe_execution_error
```

[KNOWN | HIGH] 3 个 skip 均为既有、依赖已移除 embedded Knowledge 的 fixture：`test_model_output_validators.py:37`，`test_trace_model_events.py:39`、`:71`。没有新增跳过。前端代码未变；本切片未运行前端构建、真实依赖、部署或发布 Gates。

## 基线与剩余工作

[COMPUTED | HIGH] 当前源码绑定的 [基线 JSON](evidence/p0-2/kernel-baseline/kernel_baseline.json) 与 [可读报告](evidence/p0-2/kernel-baseline/kernel_baseline.md) 包含全部五个探针，无执行异常或跳过。结果如下：

| 固定探针 | P0-1B 历史结果 | P0-2 结果 |
|---|---|---|
| 复合检索完成 | `needs_review` | `passed_with_diagnostics`：两个查询和两份准入事实均到达最终输入 |
| Intent 改写到达 KSS | `needs_review` | `passed_with_diagnostics`：required 改写作为待完成要求实际执行 |
| 数值答案校验 | `needs_review` | `needs_review`：错误金额尚未被拒绝 |
| 结构化事实进入答案 | `needs_review` | `needs_review`：结构化金额尚未到达答案输入 |
| 长对话约束 | `needs_review` | `needs_review`：预算和提交禁令尚未可靠保留 |

[KNOWN | HIGH] 固定探针只验证对应链路。查询的语义充分性取决于 Intent 质量；精确查询覆盖不是多事实语义覆盖，最终模型仍可能漏写或写错。单次空结果不在本 Run 中无限重试；业务/检索 unresolved subgoals 需要澄清或新 Run，不由本门控自行清除。P0-1B 的答案和业务任务正向验证仍未评估，GRR、Release Decision 和生产权限均未升级。

[FRAME | HIGH] 下一切片为 P0-3：补齐结构化事实经 Evidence Admission 进入答案，逐项验证类型、数值、约束和来源引用保真。P0-4 处理答案语义与数值校验，P1-1 处理长对话任务状态；真实依赖和生产准入分别保留独立验收。
