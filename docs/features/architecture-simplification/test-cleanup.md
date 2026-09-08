# 测试与检查适用性清理 — 2026-09-08

[KNOWN | HIGH] 用户明确授权删除无用或不再使用的测试与检查。本轮在前一轮架构
简化的未提交工作区上继续执行，不修改生产行为，不删除安全门禁，不把缺少真实
依赖导致的跳过当作退役证据。

## 已删除与修正

| 对象 | 适用性证据 | 处理 |
| --- | --- | --- |
| `test_cli.py` 的 8 个 Knowledge Worker 函数（13 个参数化实例） | ADR-0242 和现行 AGENTS-COMMON 已取消内嵌知识运行职责；CLI 不注册 knowledge-worker；测试永久 skip 且模拟不存在的 worker/composition | 删除测试、替身类、3 个别名与 `_invoke_knowledge_worker` |
| `test_worker_readiness.py` 的 standby Knowledge Worker 测试 | 对应生产 composition 已删除 | 删除测试、RecordingKnowledgeWorker 与 Composition.worker；保留 Executor 激活/租约测试 |
| `test_run_execution_api.py` 的 package Markdown 检索成功测试 | 已退役的本地知识绑定；sapphire fixture 无其他调用方 | 删除测试与 `_copy_react_v3_agent_with_unique_knowledge`；保留现行 Dify/Agentset Harness 成功/拒绝测试 |
| `test_agent_configuration_api.py` 的 2 个旧 Skill Pack Knowledge 绑定用例 | 假定示例含 general_insurance_knowledge，并断言已经不存在的 unknown-binding 文案；永久 skip | 删除失效用例；保留当前 contract 编辑、revision CAS、Skill Pack 与外部绑定测试 |
| `hybrid_integration` | 两个使用者实际是通用 S3 与 PostgreSQL→S3 队列测试 | 改为 `s3_integration`，同步默认选择器与 CI；两项集成测试完整保留 |
| `search_integration` | 全测试集无标记使用者，当前仓库不承担 OpenSearch 检索实现 | 删除未使用的 marker 声明 |
| CI demo 的 ANSWERED_WITH_CITATIONS 检查 | 隔离执行实际输出 supported/unsupported 均为 REFUSED_NO_EVIDENCE | 改为三个场景的精确行匹配；保留 Trace/Receipt 存在检查，并增强原 CLI 用例 |

[COMPUTED | HIGH] 合计删除 12 个测试函数、17 个收集实例。没有删除任何此前
正常通过的测试实例；不是通过删除失败断言获得 GREEN。

## 保留且仍适用

- [KNOWN | HIGH] 旧命令/运行包缺席检查保护当前产品范围；历史 KSS 版本不可
  ready/queued、发布 gate 默认关闭等拒绝测试仍对应现行规则。
- [KNOWN | HIGH] PostgreSQL/S3、真实模型测试属于依赖条件测试，不是废弃测试。
  本轮没有启动依赖服务或调用真实模型，未伪造它们的验证结果。
- [KNOWN | HIGH] 六个永久 skip 的目标仍适用：`test_trace_model_events.py` 两项、
  `test_model_output_validators.py` 一项、`test_agent_configuration_api.py` 两项、
  `test_conversation_api.py` 一项。它们保护模型输出校验、Trace 脱敏/角色、验证捕获
  和共享模型配置，但旧 embedded-Knowledge fixture 不能到达 model_answer。
  保留且明确为未执行覆盖，不能计为有效保护；迁移这些 fixture 尚未实施。
- [KNOWN | HIGH] KSS 历史发布/管理检查没有仅按文件名批量移除；保留代码契约的
  校验职责与历史数据边界需要一并考虑。

## 验证

| 阶段 | 命令/观察 | 结果 |
| --- | --- | --- |
| 改前基线 | pytest CLI、worker_readiness、run_execution_api、dependency_layout | 68 passed、15 skipped |
| 受影响回归 | 上述文件加 agent_configuration_api | 161 passed、2 skipped |
| marker 校验 | `pytest tests/integration --collect-only -q --strict-markers` | 2 deselected；默认范围不变 |
| 显式集成选择 | 同上加 `-m s3_integration` | 恰好收集原来的 2 项集成测试 |
| 全后端 | `.venv/bin/python -m pytest tests/ --strict-markers -q`，允许本机回环端口 | 2702 passed、92 skipped、2 deselected，36.50 秒 |
| CI smoke | 隔离目录执行真实 CLI demo，然后执行 workflow 原有结果/工件检查脚本 | 全部通过 |
| 静态/文档 | Ruff、domain-context 检查、`git diff --check` | 通过 |

[COMPUTED | HIGH] 与上一轮 2702 通过、109 跳过、2 未选中相比，通过数量不变，
17 项退役跳过已移除。92 个跳过包含 6 个上述过时 fixture 用例，其余为条件性依赖
测试；不能宣称测试无缺口。Authlib 与 Pydantic 既有提示仍存在。

本轮未改前端或生产 Python 逻辑，未重复执行上一轮已通过的前端构建和类型检查。
`pyproject.toml` 只调整 pytest 配置，依赖与 lockfile 未变化。自检完成，未独立
委派审查、提交、推送或部署。本记录是本轮测试结果，前一轮 verification.md 的
差异指纹和结果保留为历史快照。
