# 64K 输出额度与长回答超时

[KNOWN | HIGH] 用户报告 PA_MODEL_004 HTTP 504，后台日志确认来自 Draft validation。
当前共享模型连接 model_8faa1b52 的 timeout_seconds=10。工作流原默认有效时间
120 秒且上限 120 秒，本地验证网关另有 60 秒等待限制。无法仅通过增加 Token 解决。

[FRAME | HIGH] 按用户要求采用 64K=65536 tokens；默认总预算为 262144，给输入、
生成、修复和复核留出空间。输出额度配置范围 64–131072；有效执行时间默认 600 秒，
配置范围 1–1800 秒。总预算仍为累计账本，显式配置的较小额度和超时保持有效。
增加的是允许的最大输出，不要求模型生成满额度，也不跳过引用与语义复核。

Dashboard 路径：Agent → Workflow → 推理与问询策略 → 策略高级设置。
修改“输出预留 Token”“总 Token 上限”“有效执行时间上限（秒）”，保存 Workflow。
模型单次请求超时由共享模型连接配置管理，并受工作流剩余有效时间约束。
本次通过现有 PATCH API 把上述当前连接超时更新为 600 秒，保留其他连接字段与凭据。
该共享连接的使用者将采用新超时。新默认不重写已经冻结的 Task 或用户显式预算。

本地 verify-remote 网关等待调整为 1860 秒，覆盖最大可配工作流时间并留出收尾余量。
这只涉及本地验证网关；外部部署的入口代理需按其部署配置对齐。

验证用例：test_long_answer_budget.py 验证 64K 预算与输入可共同预留、600 秒执行窗口、
显式小额度保留和代理等待边界；WorkflowPolicyEditor.test.tsx 验证默认显示及较大额度保存。
最终后端全集 3087 passed、102 skipped、2 deselected；Dashboard 配置测试 7 passed，
构建通过，Ruff 与 mypy 424 个源文件通过。本地三个入口 HTTP 200，配置 API 读回
模型连接 timeout_seconds=600。未发起真实外部模型 replay。
