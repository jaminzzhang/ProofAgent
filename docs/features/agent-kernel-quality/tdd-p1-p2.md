# P1/P2 实施与验收记录

[KNOWN | HIGH] 2026-09-07，分支 `codex/kernel-p1-p2`，整体状态为 `PARTIAL_VERIFICATION`。本记录覆盖本地实现与下列指定验收范围。真实业务写入、真实 Dify/模型联调及生产发布没有完成。

## 已实现范围

| 切片 | 当前行为 | 本地证据 |
|---|---|---|
| P1-1 | 保留有来源的目标/约束，当前轮修订和撤销立即影响实际模型请求；先保留任务状态，再裁减历史细节与可选 Memory；冲突先澄清，容量不足拒绝；turn 与状态按原并发边界保存 | `tests/test_conversation_task_state.py`：30/100 轮、真实 ModelRequest、修订/撤销、来源与预算、重建；`test_conversation_api.py`：并发追加返回 409；`test_postgres_conversation_repository.py`：真实数据库原子保存与重建 |
| P1-2 | 包内固定只读工具计划最多 8 步，依赖参数只取同 Run 已验证真值；嵌套 JSON Schema 校验不访问外部 `$ref`；精确十进制求和在调用前验证操作数，返回后核对结果；验证成功才生成指定字段报告 | `test_tool_task_execution.py`、`test_tool_task_gateway_integration.py`、`test_tool_schema_boundary.py`；实际 V3 + Tool Gateway + MCP 模拟传输完成查询→计算→报告 |
| P1-3 | development 专用业务授权/幂等/结果核验契约与 SQLite 账本；短事务、lease fencing、请求冲突、当前权限重验、未知结果对账、独立补偿授权；receipt 验证必须显式为 `True` | `test_business_action_boundary.py`：22 项；模拟提交后丢响应、重建和并发；production 模式拒绝执行 |
| P1-4 | Skill 文件限于包内普通文件，拒绝逃逸/符号链接/歧义 YAML/超限/未知引用；获准 Skill 的工具引用限制运行时工具集合，未选中或空引用不给工具 | `test_skill_resource_boundary.py`、`test_skill_runtime_scope.py`；Gateway 集成确认恶意文字不能调用未引用工具；`test_skill_two_domain_integration.py` 通过保险与内部 IT 账号恢复两领域 |
| P2 | 固定源码、固定样本和环境绑定的重复观测；记录延迟、逻辑模型调用、提供方实际 Token；条件不匹配或质量谓词失败则不可比较 | `test_kernel_measurement.py`；`scripts/measure-agent-kernel.py`；[五次测量汇总](evidence/p1-p2/measurement/summary.json) |

[KNOWN | HIGH] 恢复执行复用原 Snapshot/Observation Truth Store，核对同 Run、问题、模板、授权、任务计划、预算、会话/Memory 输入和执行配置摘要。摘要包含工具契约、Tool Source 配置、Skill、策略、知识绑定与阶段上下文。检查点保留已获准 Skill；恢复后重新应用相应选择。只跳过已保存且通过真值核验的步骤，不承诺远端调用与本地检查点之间的 exactly-once。

[KNOWN | HIGH] 报告由已验证工具结果确定性生成，只包含包中指定且属于工具 `summary_fields` 的字段。`PublishedRunWorkHandler` 将 HTML report 与原 trace、receipt 一起交给原 Artifact Finalization；不会通过独立目录写入创造生产可见性。文件产物测试不能替代真实 S3 端到端证明。

## 发现并关闭的缺口

[KNOWN | HIGH] 回归先复现、再修复：Skill 声明原先未限制实际工具集合；恢复未绑定执行配置；异常 traceback 可能泄露 Skill 原始输入；无效计算操作数直到调用后才拒绝；非 JSON/非有限值/超大工具参数未在计划入口拒绝；模型包装层重复计数；会话并发冲突未映射为 409。对应测试保留在上述专项文件中。

[KNOWN | HIGH] PostgreSQL 首轮 80 passed、1 skipped、3 failed。三个失败来自历史回滚样例仍使用退休的 KSS binding。测试已改为当前外部知识绑定；并发同步点移至事务前的 clock，仍验证唯一获胜者与审计失败原子回滚。相关 7 项复验通过；没有恢复旧 KSS 执行路径或放宽生产契约。

## 验证与测量边界

[KNOWN | HIGH] 最终完整后端验证：`PROOF_AGENT_REQUIRE_POSTGRES_TESTS=1 .venv/bin/python -m pytest tests/ -q`，显式连接本次独占临时 PostgreSQL 17.5，**2751 passed、24 skipped、2 deselected**，88.21 秒。2 项警告为 Authlib 旧接口弃用与配置 fixture 的 Pydantic 序列化警告。跳过项不计为通过；此次没有真实 Dify/模型/S3 发布通过证据。临时数据库测试完成后已删除。

[KNOWN | HIGH] `.venv/bin/ruff check proof_agent tests scripts/measure-agent-kernel.py`、`.venv/bin/mypy proof_agent`（394 个源文件）、`uv lock --check --offline`（114 个包）、`python3 scripts/check-domain-contexts.py` 与 `git diff --check` 均通过。7 份证据 JSON 的源码指纹与最终源码一致：`sha256:7a2c615a2083e85d4752b8a972369ecbb8caaf25fdfe11265267167e9497b757`。没有完成新的独立 Agent Review，不能沿用 P0-4 的 `NO_BLOCKING_FINDINGS` 作为本次审查结论。

[KNOWN | HIGH] [固定内核探针](evidence/p1-p2/kernel-baseline/kernel_baseline.md)五项通过：数值、复合检索、意图改写、结构化事实与长对话约束。历史探针 ID `intent_rewrite_reaches_kss` 保留兼容名称，当前实际执行 Dify 适配器。探针不衡量总体答案正确率。

[KNOWN | HIGH] 测量使用真实 V3 控制逻辑及同步 Python 模型端口，网络和模型响应为固定模拟输入。单检索与复合检索各重复五次，分别为 5/6 次逻辑模型调用；p50/p95 以 JSON 报告实际值为准。质量谓词只验证必需检索与获准事实进入答案输入，答案内容质量未在该测量中验证。无真实提供方 usage 或价格，Token/费用保留 `null`，性能改进状态为 `not_established`。包装层嵌套只计外层一次；异步或跨线程模型不在此仪器覆盖范围。

## 仍未完成

- P1-1 只支持明确标记及有界预算/禁止动作表达，不代表任意自然语言任务状态理解；保留期外来源不会被悄悄续期。
- P1-2 使用包内只读配方，不是通用自然语言自动规划。生产 Queue 检查点引用与自动恢复尚未接通，报告的真实 S3 提交链路仍待验证。
- P1-3 真实业务对象、动作、远端幂等与 receipt/补偿语义未指定；生产 PostgreSQL 业务账本与提供方适配未交付。当前协调器未接 API/V3 生产路由。
- P1-4 第二领域仅为内部验收 fixture，唯一公开示例仍是保险内勤。当前安全校验会保守拒绝包含 `password` 的答案；账号恢复样例使用不触发该标记的等义业务用语，不代表该误报已修复。
- P2 真实模型/Dify HTTPS、Secret Provider、默认拒绝 egress、S3 及完整部署/发布 Gates 未完成。临时本地 PostgreSQL 测试不能转换为 Production GO。

[FRAME | HIGH] 后续真实联调需要用户给出明确业务动作及非生产服务目标/既有凭据引用。不得把等待时间或本地通过视为该授权。


## 发布 Gate 盘点

[KNOWN | HIGH] `proof_agent/release/contracts.py` 定义的五个顶层 Gate 本次均未生成发布通过证据：

| Gate | 本次已有证据 | 仍缺少 |
|---|---|---|
| `candidate_integrity` | 本地源码指纹、依赖锁核对 | 已发布候选 OCI/契约/完整产物绑定 |
| `access_security` | 本地身份、权限等既有回归 | 指定部署目标的 OIDC、Secret、egress 黑盒证据 |
| `governed_behavior` | 有界任务、证据、工具、Skill 与拒绝回归 | 真实模型/Dify 固定业务集与发布绑定结果 |
| `operational_readiness` | 隔离 PostgreSQL 合同验证 | 目标环境队列、S3、备份与观测验证 |
| `deployment_recovery` | 本地检查点与数据库事务边界测试 | 同镜像 Executor、Blue-Green、故障/回滚演练 |

[KNOWN | HIGH] 本次没有运行前端检查：Dashboard/Operator Chat 源码及公共接口未增加页面，改动限于后端行为、内部 fixture 与文档。既有前端测试结果不作为本次新增验收证据。没有提交、合并或推送本分支。
