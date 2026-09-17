# Workflow 空节点导致发布失败

[KNOWN | HIGH] 目标：配置保存与发布契约一致（产品目标 4、5）。用户在 Publish version
遇到 `PA_CONFIG_002: unavailable workflow stage configuration ... tool, tool_review`。

根因：WorkflowModuleEditor 为完整流程图的每个节点补齐编辑状态，保存时将空状态也
写入 workflow.stages。tools 禁用时，发布门禁正确拒绝这些不可用节点；实际草稿
`draft_a701d51c` revision 48 的两个节点均只有 id。

修复：保存时省略没有 Prompt 内容且没有启用 context 的节点；已有空配置允许直接
重新保存清理。完整流程图及有内容的配置保留，后端发布门禁不变。页面保存依然使用
当前 revision CAS；保存后必须重新验证该 revision。

## 验证

- RED：WorkflowModuleEditor.simplification 回归只修改一个 Prompt，实际保存了 10 个
  节点，预期仅保存修改节点，失败。
- GREEN：Dashboard 全套 `npm run test -w proof-agent-dashboard`：272 passed。
  包括旧空节点直接清理、已有非空配置保留、页面 revisioned 保存。
- `.venv/bin/python -m pytest tests/test_agent_configuration_store.py -q`：17 passed，
  保留非空不可用配置的发布拒绝用例。
- `npm run typecheck`、`npm run build:dashboard`、`git diff --check` 通过。
- 真实浏览器：`127.0.0.1:18080`，Agent → Workflow → 保存 Workflow。
  revision 48 → 49；重载后 tools 仍禁用，tool/tool_review 均不再出现在配置中，
  保存按钮禁用，验证显示过期。完整十节点流程仍可见。

[KNOWN | HIGH] 本次已修复并保存本地草稿，未调用外部模型重跑验证，未发布新版本。
这是本地配置与 UI 验证，不是生产发布证据。
