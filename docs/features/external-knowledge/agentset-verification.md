# Agentset 与混合 Knowledge 本地验收

[KNOWN | HIGH] 2026-09-07，按用户指定的 Agentset 官方文档实现 ADR-0249。范围包括配置合同、共享受控传输、Search 适配器、运行时路由、来源与结构化记录校验、Dashboard、验证和版本冻结。Dify 原有快照字段与来源格式保持兼容。

## 交付与证据

| 切片 | 实现与验收 |
| --- | --- |
| AS-1 | `contracts/external_knowledge.py` 按 Provider 验证专属字段；拒绝未知 Provider、混用 Dataset/Namespace、错误 Tenant 和检索设置 |
| AS-2 | `capabilities/knowledge/agentset.py` 与 `external_http.py` 固定 Namespace/Tenant/Bearer、Search body、Rerank 模型、查询/响应/结果/超时上限；错误脱敏；无重定向或重试 |
| AS-3 | `bootstrap/external_knowledge.py` 分派适配器；`contracts/external_source.py` 统一来源身份；混合检索、文本/结构化记录均通过配置保存、Harness 引用回答与版本冻结测试 |
| AS-4 | `KnowledgeModuleEditor.tsx` 提供 Dify/Agentset 新增及 Provider 切换；条件字段、凭证引用和重排设置；切换时清除原 Provider 配置；原 revision 冲突机制保留 |
| AS-5 | 全量自动回归、真实浏览器保存/刷新、桌面/移动布局与文档均完成本地验证 |

[COMPUTED | HIGH] `tests/test_agentset_knowledge.py` 的 33 项测试覆盖请求边界、严格响应、空命中、凭证失败、HTTP 错误、重复分段、结构化格式漂移、混合来源与 Namespace/Tenant/Chunk 身份篡改。测试先行时 Agentset Provider 配置被原 Dify-only 合同拒绝；实现后通过。回归发现旧 Dify 文档来源被额外编码导致不兼容，已恢复原格式，Agentset 仍采用独立编码的 Chunk 来源。

## 最终检查

- `.venv/bin/python -m pytest -q`：**2699 passed, 109 skipped, 2 deselected**。2 项既有警告为 Authlib deprecation 和 FrozenDict serialization。需要 loopback 的用例在允许本机监听的环境重跑后通过；跳过项不视为已验证。
- `npm run test -w proof-agent-dashboard`：**237 passed / 36 files**。
- `npm run build -w proof-agent-dashboard`：通过；更新最终帮助文案后再次构建通过。
- `.venv/bin/ruff check proof_agent tests`：通过。
- `.venv/bin/mypy proof_agent`：397 个源文件通过。
- `python3 scripts/check-domain-contexts.py`、`git diff --check`：通过。

## 实际 UI

[COMPUTED | HIGH] 使用 ego-browser 和临时隔离 FastAPI 配置目录，加载真实 Dashboard 构建。添加 Agentset，填写 `ns_manuals`、`Customer1` 和示例 Secret Handle，浏览器原生 `checkValidity()` 为 true；保存后真实 API 回读 revision 2（原 1），Provider、Namespace、Tenant、凭证引用及检索设置一致。刷新后 Namespace 保留。示例仅为引用字符串，未配置或读取 API Key。临时服务与浏览器空间均已关闭。

桌面 1440×1100 表单双栏正常；移动端 390×844 使用模块选择器与单列表单，页面 `scrollWidth = innerWidth = 390`。截图为本地交付附件 `agentset-knowledge-desktop.png`、`agentset-knowledge-mobile.png`，不将运行时目录提交入 Git。

## 未覆盖边界

[UNKNOWN | HIGH] 未调用真实 Agentset 或 Dify、未验证真实 Namespace/Tenant 权限、供应商模型可用性、真实召回与重排质量；未执行远端文档写入、上线或正式发布。合成响应通过代表本地协议与控制链路的验收，不代表供应商语义质量或 Production GO。共享适配层便于继续扩展，但当前受支持 Provider 只有 Dify 和 Agentset。

配置与官方协议链接见 [配置指南](configuration.md)。
