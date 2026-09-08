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
