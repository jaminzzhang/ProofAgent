# Knowledge 独立工作台改版

[KNOWN | HIGH] 2026-09-07：`/knowledge` 从 Dify 说明卡改为真实 Agent 草稿配置工作台。界面包括 Dify/Agentset 能力与文档卡片、Agent 选择器、直接编辑表单、接入步骤和验证入口；沿用简洁商务风。

配置通过现有草稿 API 加载，只有 `editable_modules` 明确包含 Knowledge 才读取编辑接口并开放编辑；不调用退役 KSS 管理接口、不创建新的全局知识权威。保存使用加载时的 `expected_revision`；409 重新读取最新配置，保留编辑内容并锁住保存，供用户显式重新载入或放弃。保存只表示配置持久化，不代表供应商连接或检索验证成功。

未保存期间锁定 Agent 选择器与页内导航链接，关闭/刷新触发原生提示，并提供明确放弃按钮。浏览器历史回退不属于此页内链接拦截的覆盖范围。表单复用已有 Provider 校验、凭证引用及绑定数量限制。

[COMPUTED | HIGH] 四项页面测试覆盖加载及来源入口、放弃后解锁且不写服务端、只读权限、精确 revision 保存与冲突保留。Dashboard 全量 241 项测试通过，构建与 diff 检查通过。实际 ego-browser 检查新增 Agentset 的 9 个输入、Agent 选择锁定、放弃后字段清除及解锁。真实页面没有保存测试绑定。

本地截图 `knowledge-workspace.png` 展示当前真实配置工作台。没有调用真实供应商、读取 Key 或变更发布状态。
