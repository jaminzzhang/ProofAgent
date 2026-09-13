# Dashboard 简洁商务风改版

[KNOWN | HIGH] 2026-09-07，按用户要求完成 Dashboard 全局视觉与主要配置入口改版，已重新构建并由本地 18080 网关提供新资源。

## 设计与行为

- 深蓝导航、浅灰页面、白色工作区；深蓝主按钮、克制边框、统一文本对比；Dashboard 独立覆盖共享语义 tokens，未改变 Chat 主题。
- 页面标题与操作分离，小屏自动纵向排列；移除无实际入口的 Settings 占位项；移动菜单改为纵向导航。
- Agent 列表新增总数、有活动版本、有草稿统计，直接由现有数据计算，不推断发布或健康状态。
- 名称、ID、用途搜索与活动版本筛选可组合；显示匹配数量和空结果提示。创建为主操作，本地配置导入收进默认折叠区，继续由服务端 capabilities 控制可见性。
- 配置工作区采用同一导航风格与明确模块标题。Knowledge 区分连接、内容与凭证、检索设置；保留 Provider 条件字段、原生输入校验、脏状态、revision 冲突和保存语义。
- 兼容暗色和减少动画偏好；未增加依赖。

## 本地验证

[COMPUTED | HIGH] `npm run test -w proof-agent-dashboard`：238 passed / 37 files；`npm run build:dashboard`、`git diff --check` 通过。新增搜索与筛选组合测试验证空结果恢复及原草稿链接。既有测试按已移除占位入口与新增 h1 调整定位。

[COMPUTED | HIGH] ego-browser 检查实际 18080 页面：Agent 搜索空结果、列表恢复、中文切换、Knowledge 空态/未保存 Agentset 分组、暗色最终渲染、移动导航开关。320、768、1024、1440px 下列表及配置页无页面级横向溢出；宽表在自身容器横向滚动。早期主题切换截图为过渡帧，已丢弃并重新检查稳定画面。

[KNOWN | HIGH] 视觉验证没有保存临时 Agentset 配置；离开前使用“放弃未保存修改”。现有服务与数据目录保持不变。截图作为本地附件交付：`dashboard-business-agents.png`、`dashboard-business-knowledge.png`、`dashboard-business-mobile.png`。

[UNKNOWN | HIGH] 环境没有 Lighthouse CLI，未提供自动 Lighthouse 分数，也不声称完整无障碍合规。当前证据覆盖真实渲染、语义标签、键盘原生控件和上述视口；后端与发布权限未变更。

## 跨应用跳转修复（2026-09-08）

[KNOWN | HIGH] 版本页 `chatUrl` 与 Operator Chat 的 Run 详情链接原先在构建变量缺省时回退到硬编码 localhost:5174/5173。统一网关构建曾依赖启动命令设置空字符串，普通 npm build 会重新引入错误地址。

两处现改为：显式 VITE_CHAT_URL/VITE_DASHBOARD_URL 优先；普通构建缺省同源相对路径；仅 Vite 开发模式回退到当前 hostname 的相邻开发端口。显式地址尾部斜杠被规范化。新增双向导航回归测试；不改变发布版本选择和执行语义。

## Operator Chat 本地发送 404（2026-09-08）

[KNOWN | HIGH] 本机日志显示会话创建成功，随后 `POST /api/runs` 返回 404。Chat 原先固定采用生产队列协议，而本地服务提供 `/api/chat/conversations/{id}/runs` 同步开发入口。Session 现在明确返回 `chat_execution_mode`：开发为 `development_sync`，生产为 `queued`。Chat 等待初始化后按该能力选择；未知/缺省值仍走队列，生产错误不回退到开发执行。

[COMPUTED | HIGH] Chat 38 项测试、构建通过；会话/队列后端回归 43 passed、1 skipped。新增测试覆盖本地能力声明和真实本地会话接口（合成模型），未自动重放用户私有问题至外部模型。

Local restart verification: `/api/auth/session` reports `development_sync`, and
`/operator` returns HTTP 200 after rebuilding both frontends. The ignored local
launcher uses the existing server `--no-seed-example-agent` option because this
store contains a user-published version; resetting it to the canonical demo seed
would discard the configured state. No real model conversation was replayed in
this verification.

### Bounded answer-fact diagnostics

Fact failures now carry zero-based `message.statements[N]` locations through the
existing diagnostic field paths (including repair requests). Statements use the
validator's NFC normalization, ordered-list-prefix removal and sentence splitting.
The failure trace also includes at most 32 `fact_diagnostics` tuples containing
(statement index, violation code, match status). Status distinguishes an unmatched
subject, a matched subject with a different value, and conflicting source values.
These are exact-match diagnostics, not semantic hallucination determinations.
Audience/redaction review: only bounded indices and fixed codes are persisted;
no failed answer text, evidence text, prompt, credential or content hash is added.
The admission and answer validation decisions remain unchanged. Existing historic
Runs cannot be reconstructed from these new fields. Verification: 67 fact and
failure-payload tests passed; real-model replay remains unverified.

Planner pending-retrieval diagnosis (`run_b4298fdd`): one of two required queries
completed with three accepted candidates before the model proposed refusal. The
restricted-action context omitted accepted evidence progress. It now reports the
accepted count and recommends continuing eligible pending retrieval without
removing refusal or authorizing final answers early. This repairs missing context;
causation of the real model's choice and successful real-model completion remain
unverified. Targeted context/orchestrator/state-machine checks: 45 passed.
