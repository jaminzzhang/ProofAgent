# Agent 澄清程度与过度澄清修复

日期：2026-09-10。设计：[ADR-0253](../../adr/0253-configure-agent-clarification-level.md)。

[KNOWN | HIGH] 本次实现范围为 `LOCAL_VERIFIED`：配置契约、YAML 加载、Control Plane
执行、模型输入传递、Draft 保存重载与 Dashboard 实际渲染已经本地验证。
没有重新调用 DeepSeek 重跑 `run_323deaaf`，不代表真实模型分类质量、证据可用性或发布通过。

## 行为与边界

- `response.clarification_level` 接受 `minimal` / `balanced` / `thorough`，默认均衡，非法值拒绝。
- 意图模型提出缺口分类和范围默认值；Control Plane 在冻结检索任务前应用配置。
  少澄清允许宽范围检索；均衡要求明确范围默认值；详细澄清确认偏好。
- 可检索事实不会阻断；必要上下文、未分类缺口始终保留，包括模型建议直接检索或工具调用时。
  业务流准入仍独立执行；`no_pack` 不会被程序误称为路由歧义。
- 自动继续使用已有有界查询，或将原问题作为一条 required 查询；仍须通过既有检索、权限、
  证据、事实和引用校验。没有资料的测试返回拒答，不制造“回答成功”。
- 范围假设以非证据上下文传给规划和最终回答（包括通用修复请求），要求说明采用的范围；
  不写入已知事实，不用于工具参数或授予权限。容量不足时保留澄清，不静默丢弃默认值。
- 澄清一次仅展示首个字段，中文问题使用中文；完整未解决字段保留在结果中。
- 配置保留现有 Draft CAS、版本与执行配置摘要绑定；旧记录缺少新意图字段仍可读取。

## 验证记录

所有命令工作目录为仓库根目录。没有新增外部模型调用、发布、Git commit 或 push。

| 检查 | 结果与覆盖 |
| --- | --- |
| 初始 `pytest tests/test_clarification_policy.py -q` | 10 failed / 2 passed；复现“概览问题在检索前被澄清阻断”和英文多字段回复 |
| 范围传递 RED | 1 failed / 16 passed；发现最终回答组装器最初丢弃新增上下文，已修复 |
| YAML 加载 RED | 3 failed / 18 passed；原手工加载器忽略新字段，已改严格契约校验 |
| 最后边界 RED | 4 failed / 21 passed；覆盖替代动作绕过必要上下文、详细档绕过与默认值容量，已修复 |
| 最终 `.venv/bin/python -m pytest tests/ -q`（允许 loopback） | **2760 passed, 92 skipped, 2 deselected**，36.91 秒；保留依赖条件跳过，不将其视为覆盖 |
| `npm test` | Dashboard **258 passed**，Chat **38 passed** |
| 文案调整后受影响前端回归 | `ModuleEditor`、Dashboard locale、`AgentDetailPage` 共 **77 passed** |
| `npm run build`；文案调整后 `npm run build:dashboard` | 通过；既有 bundle 大小提示保留 |
| `.venv/bin/ruff check proof_agent tests` | 通过 |
| `.venv/bin/mypy proof_agent` | 398 个源文件通过 |
| `uv lock --check` | 114 个依赖，锁文件一致；沙箱外运行解决系统配置服务限制 |
| `.venv/bin/python scripts/check-domain-contexts.py`；`git diff --check` | 通过 |
| 三档执行配置摘要对比 | 三个不同摘要，配置变化绑定执行 |

首次完整回归的 8 项失败均为 sandbox socket bind `Operation not permitted`，
允许 loopback 后相关 13 项全部通过；最后完整回归也已全部通过。
现有 Authlib 弃用和 Pydantic FrozenDict 序列化警告未被隐藏。

## 实际界面

ego-browser 独立空间打开本地 `127.0.0.1:5173`，从 Agent → Response 操作：

1. 原 Draft revision 29 显示默认“均衡”。
2. 选择“少澄清”，保存至 revision 30，刷新后仍显示 `minimal`。
3. 设回默认“均衡”，保存至 revision 31，刷新读取 `balanced`、`配置已保存`；无横向溢出。
4. 原活动版本未发布更新；旧 Draft 验证正常显示“验证已过期”。

截图：`runs/clarification-policy-verification/response-balanced.png`。
被测代码与测试文件哈希：`runs/clarification-policy-verification/files.sha256.json`。

## Review

本次为主 Agent 自检，没有独立子 Agent Review。已关闭：加载器丢字段、回答上下文丢字段、
配置未绑定执行摘要、用另一种动作绕过必要上下文、容量静默截断、澄清原因错误归类。
已有未提交改动保留；本次未修改事实校验器，也未将默认值当作证据放行。

实际模型仍可能错误分类缺口；无分类时保守阻断。原问题是否最终可回答，仍取决于实际模型
输出和知识源证据。本地测试仅证明声明分类下的控制行为与配置链路，不声称真实问答命中率。
