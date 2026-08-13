# Knowledge Source Service TDD 与辅助编码报告

本报告记录 `knowledge-source-service` 的 RED → GREEN → REFACTOR 证据。[KNOWN | HIGH] 2026-08-12 的 Goal 范围已完成本地验收；该结论不代表生产发布批准、容量批准或 cutover 完成。

## 1. 建议结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | `VERIFIED_LOCAL` |
| 最高风险等级 | P1 |
| 模式 | 本地修改；真实 PostgreSQL、MinIO、OpenSearch 与 OCI image 验证 |

## 2. 测试目标与范围

| 项 | 内容 |
| --- | --- |
| 测试目标 | 先冻结 `CreateKnowledgeQueryRequest` V1 可观察 contract，再按 scope-plan 的 T0 至 T14 递增实现 |
| 测试范围 | strict schemas、HTTP resource、状态与幂等、服务运行、摄取与版本、检索、Agentic、ProofAgent 接入 |
| 不覆盖范围 | 生产发布批准、真实生产数据或凭证、尚未进入当前 RED 的后续行为 |

## 3. 测试场景

| 编号 | 场景 | 类型 | 优先级 | 风险等级 |
| --- | --- | --- | --- | --- |
| T0-CQ-001 | 合法 V1 请求可解析并按公共字段序列化 | positive contract | P1 | P1 |
| T0-CQ-002 | 未声明的顶层字段被拒绝 | negative contract | P1 | P1 |
| T0-CQ-003 | 未要求 narrowing assertion 时可省略 context | positive contract | P1 | P1 |
| T0-CQ-004 | 未声明的 nested backend/scope/budget 字段全部被拒绝 | negative contract | P1 | P1 |
| T0-CQ-005 | `as_of` 和 `deadline_at` 必须带时区 | negative contract | P1 | P1 |
| T0-CQ-006 | execution budget 的每个 hard limit 必须为正数 | negative contract | P1 | P1 |
| T0-CQ-007 | Release ID、问题和 assertion 不接受空白 | negative contract | P1 | P1 |
| T0-CQ-008 | 未指定 strategy 时使用 `single_pass` | positive contract | P1 | P1 |
| T0-CQ-009 | 未提供 narrowing constraint 时使用空 typed constraints | positive contract | P1 | P1 |
| T0-CQ-010 | filter 不接受 backend-native object | negative security contract | P1 | P1 |
| T0-HTTP-001 | POST 创建可轮询的 queued Knowledge Query | HTTP tracer bullet | P1 | P1 |
| T0-RESULT-001 | mixed result 保留 relevance/structured 独立 ordering | result contract | P1 | P1 |
| T0-RESULT-002 | relevance candidate 必须绑定 exact Source Version provenance | result/provenance contract | P1 | P1 |
| T0-RESULT-003 | context Evidence Unit 必须独立携带 citation | result/provenance contract | P1 | P1 |
| T0-RESULT-004 | structured candidate 保留 typed value/citation/order | result/structured contract | P1 | P1 |
| T0-RESULT-005 | structured value 必须匹配声明类型 | result/structured validation | P1 | P1 |
| T0-RESULT-006 | result 不接受其他 Release 的 candidate | result/version isolation | P1 | P1 |
| T0-RESULT-007 | succeeded Query 暴露 typed available Result | resource/result contract | P1 | P1 |
| T0-RESULT-008 | 非 succeeded/available Query 不得携带 Result | resource/state contract | P1 | P1 |
| T0-RESULT-009 | available Result 必须有 content 与 retention expiry | resource/retention contract | P1 | P1 |
| T0-RESULT-010 | execution state 与 result availability 必须兼容 | resource/state contract | P1 | P1 |
| T0-HTTP-002 | GET 通过 Location 轮询已创建 Query | HTTP tracer bullet | P1 | P1 |
| T0-HTTP-003 | exact idempotency replay 返回同一 Query | HTTP/idempotency | P1 | P1 |
| T0-HTTP-004 | 同 key 不同 request 返回安全冲突 | HTTP/idempotency/error | P1 | P1 |
| T0-HTTP-005 | client 不可轮询另一 client 的 Query | HTTP/security isolation | P1 | P1 |
| T0-HTTP-006 | create 要求非空白 `Idempotency-Key` | HTTP/header/error | P1 | P1 |
| T0-HTTP-007 | 不存在或不可见 Query 返回相同安全 problem | HTTP/error/isolation | P1 | P1 |
| T0-HTTP-008 | queued Query 可取消为同一 terminal resource | HTTP/state | P1 | P1 |
| T0-HTTP-009 | 已过 execution deadline 的请求在排队前被拒绝 | HTTP/admission/time | P1 | P1 |
| T1-DIST-001 | KSS 是不依赖 ProofAgent 的独立 Python distribution | packaging/import boundary | P1 | P1 |
| T1-ROLE-001 | CLI 暴露五个隔离 process roles | process interface | P1 | P1 |
| T1-HEALTH-001 | `/livez` 暴露 service/release identity | HTTP health | P1 | P2 |
| T1-HEALTH-002 | `/readyz` 报告有界必需依赖状态 | HTTP readiness | P1 | P1 |
| T1-HEALTH-003 | 任一必需依赖不可用时 readiness 失败关闭 | HTTP readiness/failure | P1 | P1 |
| T1-CONFIG-001 | API role 配置检查失败关闭且不回显值 | process/config/security | P1 | P1 |
| T1-ROLE-002 | distribution 为每个 process role 暴露 console entry point | packaging/process | P1 | P1 |
| T3-EXEC-001 | Query Executor 完成 queued→succeeded typed result | executor tracer bullet | P1 | P1 |

## 4. Given-When-Then 用例

| 编号 | Given | When | Then |
| --- | --- | --- | --- |
| T0-CQ-001 | exact Release、问题、策略、约束、签名 context、预算和绝对 deadline | 验证 `CreateKnowledgeQueryRequest` | 接受请求并只输出 V1 公共字段 |
| T0-CQ-002 | 合法请求额外携带 caller-controlled `knowledge_space_id` | 验证 `CreateKnowledgeQueryRequest` | 返回 validation failure，不静默忽略字段 |
| T0-CQ-003 | grant/policy 不要求 narrowing context，合法请求省略该字段 | 验证 `CreateKnowledgeQueryRequest` | 请求仍有效，context 为 `None` |
| T0-CQ-004 | nested objects 携带 backend query、Space 或 cost 字段 | 验证 `CreateKnowledgeQueryRequest` | 三个未声明字段均被明确拒绝 |
| T0-CQ-005 | constraint time 和 execution deadline 是 naive datetime | 验证 `CreateKnowledgeQueryRequest` | 两个时间字段均被拒绝 |
| T0-CQ-006 | 任一请求预算为 0 或负数 | 验证 `CreateKnowledgeQueryRequest` | 每个无效 hard limit 均被拒绝 |
| T0-CQ-007 | Release ID、问题或 assertion 为空或只有空格 | 验证 `CreateKnowledgeQueryRequest` | 对应字段均被拒绝 |
| T0-CQ-008 | 合法请求省略 `strategy` | 验证 `CreateKnowledgeQueryRequest` | strategy 明确规范化为 `single_pass` |
| T0-CQ-009 | 合法请求省略 `query_constraints` | 验证 `CreateKnowledgeQueryRequest` | `as_of=None` 且 `filters=[]`，不生成 backend query |
| T0-CQ-010 | filter 包含 OpenSearch/SQL 类 backend-native object | 验证 `CreateKnowledgeQueryRequest` | schema validation 失败，不进入 planner |
| T0-HTTP-001 | 已认证 client、合法 request 和唯一 idempotency key | POST `/v1/knowledge-queries` | `202`、poll headers 和唯一 queued resource |
| T0-RESULT-001 | 一个 Query 同时产生 ranked 与 structured group | 验证 `KnowledgeQueryResult` | 两组 ordering 分开序列化，无 cross-group score/rank |
| T0-RESULT-002 | relevance candidate 缺少 `knowledge_source_version_id` | 验证 mixed result | validation failure；不能返回不可重放候选 |
| T0-RESULT-003 | context unit 有内容/hash/lineage 但缺少 locator | 验证 mixed result | validation failure；context 不可退化为匿名拼接文本 |
| T0-RESULT-004 | structured group 含一个 typed record candidate | 验证 mixed result | field type/value、Dataset Revision citation 和 structured order 原样保留 |
| T0-RESULT-005 | 7 类 structured field 的 value 与声明类型不一致 | 验证 mixed result | 每个字段独立 validation failure |
| T0-RESULT-006 | candidate 的 Release 与 result lineage 不同 | 验证 mixed result | validation failure；禁止跨 Release 混合 |
| T0-RESULT-007 | succeeded Query、available retention metadata、typed result | 验证 `KnowledgeQuery` | 完整 result 序列化且 execution/retention 状态分离 |
| T0-RESULT-008 | running Query 携带 available Result | 验证 `KnowledgeQuery` | validation failure；执行中资源不能提前暴露结果 |
| T0-RESULT-009 | succeeded/available Query 缺少 result 和 expiry | 验证 `KnowledgeQuery` | validation failure；不可声称结果可获取 |
| T0-RESULT-010 | cancelled Query 声称 retained Result 已 expired | 验证 `KnowledgeQuery` | validation failure；execution expiry 与 result retention 不混淆 |
| T0-HTTP-002 | 已成功创建 queued Query | GET response `Location` | `200` 并返回同一 Query resource |
| T0-HTTP-003 | 同一 client/key/request 已创建 Query | 再次 POST 同一 request | `200`，同一 Location 和 immutable resource，不生成第二个 ID |
| T0-HTTP-004 | 同一 client/key 已绑定另一个 fingerprint | POST 不同 request | `409` RFC 9457 problem，不创建新 Query、不回显敏感 request |
| T0-HTTP-005 | client A 已创建 Query | client B GET 同一 opaque ID | 与不存在资源一致返回 `404`，响应不回显 ID |
| T0-HTTP-006 | create header 缺失或只有空格的 `Idempotency-Key` | POST 合法 body | `400 invalid_idempotency_key` RFC 9457 problem |
| T0-HTTP-007 | authenticated client GET 不存在或不可见 ID | GET Query | `404 knowledge_query_not_found`，不区分不存在与越权 |
| T0-HTTP-008 | client 拥有 queued Query | POST Query cancel link | 同一 ID 转为 `cancelled`，记录取消/完成时间，无结果 |
| T0-HTTP-009 | `deadline_at <= submitted_at` | POST create | `422 knowledge_query_deadline_elapsed`，不创建 Query |
| T1-DIST-001 | service package 已存在 | 读取 distribution metadata | 独立 name/build/dependencies，不声明 `proof-agent` 依赖 |
| T1-ROLE-001 | 独立 distribution | 执行 `python -m knowledge_source_service roles` | 稳定列出 API、Query Executor、Worker、Scheduler、Migration |
| T1-HEALTH-001 | API 进程已构建 | 未认证 GET `/livez` | `200` stable health schema；仅表示进程存活 |
| T1-HEALTH-002 | PostgreSQL、object storage、search 均 ready | 未认证 GET `/readyz` | `200 ready`，仅返回 dependency name/status |
| T1-HEALTH-003 | 任一 required dependency unavailable | GET `/readyz` | `503 unavailable`，不泄露额外 probe facts |
| T1-CONFIG-001 | API role 启动前检查权威依赖配置 | 执行 `api --check-config` | 缺失时退出 2 仅列键名；配置齐全时退出 0 且不回显值 |
| T1-ROLE-002 | 安装独立 wheel | 查询 console scripts metadata | umbrella CLI 与五个 role 命令均指向独立 callable |
| T3-EXEC-001 | HTTP 已创建 queued Query | executor `run_once()` 后 GET | 同一 Query 转为 succeeded、携带 typed result 与 retention expiry |

## 5. Mock、数据与断言

| 项 | 规则 | 风险 |
| --- | --- | --- |
| Contract fixture | 使用小型、固定、无敏感数据的 JSON | fixture 漂移必须由 contract test 阻止 |
| 时间 | 使用带时区的固定 RFC 3339 值 | naive datetime 必须在负向用例中拒绝 |
| 断言 | 对完整 public serialization 断言，不断言 private implementation | 防止字段和默认值静默漂移 |

## 6. RED-GREEN-REFACTOR 记录

| 步骤 | 行为 | 文件 | 结果 |
| --- | --- | --- | --- |
| RED-001 | 合法 V1 create request contract | `tests/contract/knowledge_service/test_create_knowledge_query_contract.py` | 失败符合预期：`ModuleNotFoundError: knowledge_source_service` |
| GREEN-001 | 实现最小 create request contract | `services/knowledge-source-service/knowledge_source_service/contracts/knowledge_query.py` | targeted test：1 passed |
| REFACTOR-001 | 提取可复用的合法 request fixture | `tests/contract/knowledge_service/test_create_knowledge_query_contract.py` | targeted test：1 passed |
| RED-002 | 未声明的顶层字段必须 fail closed | `tests/contract/knowledge_service/test_create_knowledge_query_contract.py` | 失败符合预期：Pydantic 默认忽略 extra field，未抛出 `ValidationError` |
| GREEN-002 | 顶层 request 使用 `extra=forbid` | `services/knowledge-source-service/knowledge_source_service/contracts/knowledge_query.py` | targeted tests：2 passed |
| RED-003 | `access_narrowing_context` 必须可选 | `tests/contract/knowledge_service/test_create_knowledge_query_contract.py` | 失败符合预期：字段被错误要求为必填 |
| GREEN-003 | 将 narrowing context 改为 optional | `services/knowledge-source-service/knowledge_source_service/contracts/knowledge_query.py` | targeted tests：3 passed |
| RED-004 | nested contract 也必须 fail closed | `tests/contract/knowledge_service/test_create_knowledge_query_contract.py` | 失败符合预期：三个 nested extra fields 均被静默忽略 |
| GREEN-004 | 引入统一 `StrictContract` | `services/knowledge-source-service/knowledge_source_service/contracts/knowledge_query.py` | targeted tests：4 passed |
| RED-005 | 公共时间必须 timezone-aware | `tests/contract/knowledge_service/test_create_knowledge_query_contract.py` | 失败符合预期：naive `as_of` 和 `deadline_at` 均被接受 |
| GREEN-005 | 时间字段使用 `AwareDatetime` | `services/knowledge-source-service/knowledge_source_service/contracts/knowledge_query.py` | targeted tests：5 passed |
| RED-006 | execution budget hard limits 必须为正数 | `tests/contract/knowledge_service/test_create_knowledge_query_contract.py` | 失败符合预期：0 和负数均被接受 |
| GREEN-006 | budget 字段使用 `gt=0` | `services/knowledge-source-service/knowledge_source_service/contracts/knowledge_query.py` | targeted tests：6 passed |
| RED-007 | authority-bearing text fields 不得为空白 | `tests/contract/knowledge_service/test_create_knowledge_query_contract.py` | 失败符合预期：三个空白字段均被接受 |
| GREEN-007 | 引入统一 `NonBlankText` | `services/knowledge-source-service/knowledge_source_service/contracts/knowledge_query.py` | targeted tests：7 passed |
| RED-008 | strategy 默认值必须为 `single_pass` | `tests/contract/knowledge_service/test_create_knowledge_query_contract.py` | 失败符合预期：省略 strategy 时字段缺失 |
| GREEN-008 | strategy 默认设为 `single_pass` | `services/knowledge-source-service/knowledge_source_service/contracts/knowledge_query.py` | targeted tests：8 passed |
| RED-009 | typed narrowing constraints 必须可省略 | `tests/contract/knowledge_service/test_create_knowledge_query_contract.py` | 失败符合预期：省略 constraints 时字段缺失 |
| GREEN-009 | 使用默认空 `QueryConstraints` | `services/knowledge-source-service/knowledge_source_service/contracts/knowledge_query.py` | targeted tests：9 passed |
| RED-010 | 禁止 backend-native filter object | `tests/contract/knowledge_service/test_create_knowledge_query_contract.py` | 失败符合预期：任意 nested object 被 `Any` 接受 |
| GREEN-010 | 使用 strict backend-neutral `QueryFilter` | `services/knowledge-source-service/knowledge_source_service/contracts/knowledge_query.py` | targeted tests：10 passed |
| RED-HTTP-001 | 创建可轮询的 queued resource | `tests/contract/knowledge_service/test_knowledge_query_http_api.py` | 失败符合预期：service 尚无 adapters/application/delivery 路径 |
| GREEN-HTTP-001 | 实现 create→persist→202 纵向路径 | `services/knowledge-source-service/knowledge_source_service/{contracts,ports,application,adapters,delivery}/` | targeted HTTP test：1 passed；中间修正 FastAPI local dependency wiring |
| REFACTOR-HTTP-001 | 提取 TestClient composition | `tests/contract/knowledge_service/test_knowledge_query_http_api.py` | service contract suite：11 passed |
| RED-HTTP-002 | 已创建 Query 必须可通过 Location 轮询 | `tests/contract/knowledge_service/test_knowledge_query_http_api.py` | 失败符合预期：Location 返回 `404 Not Found` |
| GREEN-HTTP-002 | repository/application/delivery 增加 GET | `services/knowledge-source-service/knowledge_source_service/` | targeted HTTP tests：2 passed |
| RED-HTTP-003 | exact idempotency replay 不得创建新 Query | `tests/contract/knowledge_service/test_knowledge_query_http_api.py` | 失败符合预期：第二次返回 `202` 并生成新 ID |
| GREEN-HTTP-003 | 持久化 client-scoped fingerprint 并返回 replay outcome | `services/knowledge-source-service/knowledge_source_service/` | targeted HTTP tests：3 passed |
| RED-HTTP-004 | idempotency fingerprint mismatch 必须安全冲突 | `tests/contract/knowledge_service/test_knowledge_query_http_api.py` | 失败符合预期：delivery 尚无 trace-ID/error mapping seam |
| GREEN-HTTP-004 | fingerprint mismatch 映射为 trace-safe RFC 9457 problem | `services/knowledge-source-service/knowledge_source_service/` | targeted HTTP tests：4 passed |
| RED-HTTP-005 | Query 读取必须按认证 client 隔离 | `tests/contract/knowledge_service/test_knowledge_query_http_api.py` | 失败符合预期：client B 收到 client A Query 的 `200` 完整响应 |
| GREEN-HTTP-005 | application 按 owner client 隐藏 Query | `services/knowledge-source-service/knowledge_source_service/application/knowledge_queries.py` | targeted HTTP tests：5 passed |
| RED-HTTP-006 | create 必须拒绝空白 idempotency header | `tests/contract/knowledge_service/test_knowledge_query_http_api.py` | 失败符合预期：空白 key 创建了 `202` Query |
| GREEN-HTTP-006 | header dependency 拒绝空白并映射安全 problem | `services/knowledge-source-service/knowledge_source_service/delivery/http.py` | targeted HTTP tests：6 passed |
| REFACTOR-HTTP-002 | 提取统一 RFC 9457 response renderer | `services/knowledge-source-service/knowledge_source_service/delivery/http.py` | service contract suite：16 passed |
| RED-HTTP-007 | Query not-found 必须使用安全 Problem Details | `tests/contract/knowledge_service/test_knowledge_query_http_api.py` | 失败符合预期：默认响应为 `application/json`，缺少稳定 problem contract |
| GREEN-HTTP-007 | GET 不可见分支使用统一 Problem renderer | `services/knowledge-source-service/knowledge_source_service/delivery/http.py` | targeted HTTP tests：7 passed |
| RED-HTTP-008 | queued Query cancel 必须返回同一 terminal resource | `tests/contract/knowledge_service/test_knowledge_query_http_api.py` | 失败符合预期：cancel link 返回 `405 Method Not Allowed` |
| GREEN-HTTP-008 | application 持久化 queued→cancelled 并增加 cancel route | `services/knowledge-source-service/knowledge_source_service/` | targeted HTTP tests：8 passed |
| RED-HTTP-009 | elapsed deadline 必须在 durable create 前拒绝 | `tests/contract/knowledge_service/test_knowledge_query_http_api.py` | 失败符合预期：创建了 deadline 早于 submitted_at 的 `202` Query |
| GREEN-HTTP-009 | create 在 ID/持久化前验证单次时钟 deadline | `services/knowledge-source-service/knowledge_source_service/` | targeted HTTP tests：9 passed |
| RED-DIST-001 | service 必须有独立 distribution metadata | `tests/contract/knowledge_service/test_service_distribution.py` | 失败符合预期：`services/knowledge-source-service/pyproject.toml` 不存在 |
| GREEN-DIST-001 | 新增独立 hatch distribution metadata | `services/knowledge-source-service/pyproject.toml` | targeted packaging test：1 passed；sdist/wheel 构建成功 |
| REFACTOR-DIST-001 | dependency 断言改为 required subset | `tests/contract/knowledge_service/test_service_distribution.py` | targeted packaging test 与 Ruff 均通过 |
| RED-ROLE-001 | CLI 必须列出五个 process roles | `tests/contract/knowledge_service/test_service_distribution.py` | 失败符合预期：package 缺少 `__main__`，不可执行 |
| GREEN-ROLE-001 | 新增 module CLI 和稳定 role vocabulary | `services/knowledge-source-service/knowledge_source_service/{cli.py,__main__.py}` | targeted distribution tests：2 passed |
| RED-HEALTH-001 | API 必须提供无认证 liveness 与 release identity | `tests/contract/knowledge_service/test_knowledge_query_http_api.py` | 失败符合预期：HTTP composition 不接受 release identity，缺少 health interface |
| GREEN-HEALTH-001 | 新增 stable liveness contract 与 `/livez` | `services/knowledge-source-service/knowledge_source_service/{contracts/health.py,delivery/http.py}` | targeted HTTP tests：10 passed |
| RED-HEALTH-002 | readiness 必须报告三个 required dependencies | `tests/contract/knowledge_service/test_knowledge_query_http_api.py` | 失败符合预期：HTTP composition 不接受 readiness probe |
| GREEN-HEALTH-002 | readiness probe 映射为有界 dependency projection | `services/knowledge-source-service/knowledge_source_service/{contracts/health.py,delivery/http.py}` | targeted HTTP tests：11 passed |
| RED-HEALTH-003 | unavailable required dependency 必须返回 `503` | `tests/contract/knowledge_service/test_knowledge_query_http_api.py` | 失败符合预期：unavailable body 仍返回 HTTP `200` |
| GREEN-HEALTH-003 | unavailable readiness 使用 HTTP `503` | `services/knowledge-source-service/knowledge_source_service/delivery/http.py` | service contract suite：24 passed；Ruff 通过；mypy 首次发现 Literal 窄化问题 |
| REFACTOR-HEALTH-001 | 显式声明 dependency name Literal type | `services/knowledge-source-service/knowledge_source_service/{contracts/health.py,delivery/http.py}` | 待复跑 |
| RED-CONFIG-001 | API role 必须验证 required dependency configuration | `tests/contract/knowledge_service/test_service_distribution.py` | 失败符合预期：CLI 不认识 `api`，只返回 argparse usage |
| GREEN-CONFIG-001 | 新增纯环境配置检查，不读取 `.env` 或打印值 | `services/knowledge-source-service/knowledge_source_service/{configuration.py,cli.py}` | targeted distribution tests：3 passed |
| RED-ROLE-002 | wheel 必须暴露 per-role console scripts | `tests/contract/knowledge_service/test_service_distribution.py` | 失败符合预期：distribution metadata 缺少 `project.scripts` |
| GREEN-ROLE-002 | 新增 umbrella 与五个 per-role console scripts | `services/knowledge-source-service/{pyproject.toml,knowledge_source_service/cli.py}` | targeted distribution tests：4 passed；Ruff/mypy 通过 |
| RED-RESULT-001 | mixed result 必须保留两类 group 语义 | `tests/contract/knowledge_service/test_knowledge_query_result_contract.py` | 失败符合预期：缺少 `contracts.results` module |
| GREEN-RESULT-001 | 实现 mixed result envelope 与 typed group ordering | `services/knowledge-source-service/knowledge_source_service/contracts/results.py` | targeted result test：1 passed |
| REFACTOR-RESULT-001 | 提取 mixed result golden factory | `tests/contract/knowledge_service/test_knowledge_query_result_contract.py` | targeted result test：1 passed |
| RED-RESULT-002 | relevance candidate 必须有 exact Source Version | `tests/contract/knowledge_service/test_knowledge_query_result_contract.py` | 失败符合预期：arbitrary candidate dict 接受缺失 provenance |
| GREEN-RESULT-002 | 实现 strict relevance Candidate Evidence contract | `services/knowledge-source-service/knowledge_source_service/contracts/results.py` | targeted result tests：2 passed |
| RED-RESULT-003 | context unit 必须有独立 citation | `tests/contract/knowledge_service/test_knowledge_query_result_contract.py` | 失败符合预期：arbitrary context dict 接受缺失 locator |
| GREEN-RESULT-003 | 实现独立可引用的 typed context unit | `services/knowledge-source-service/knowledge_source_service/contracts/results.py` | targeted result tests：3 passed |
| RED-RESULT-004 | structured candidate 必须保留 typed semantics | `tests/contract/knowledge_service/test_knowledge_query_result_contract.py` | 失败符合预期：缺少 structured data、Dataset locator 和 structured ranking variants |
| GREEN-RESULT-004 | 用 group-specific Candidate types 保留 structured semantics | `services/knowledge-source-service/knowledge_source_service/contracts/results.py` | targeted result tests：4 passed |
| RED-RESULT-005 | structured value 必须匹配 `value_type` | `tests/contract/knowledge_service/test_knowledge_query_result_contract.py` | 失败符合预期：7 个不匹配值全部被接受 |
| GREEN-RESULT-005 | 对 structured field 执行声明类型校验 | `services/knowledge-source-service/knowledge_source_service/contracts/results.py` | targeted result tests：5 passed；Ruff/mypy 通过 |
| RED-RESULT-006 | Candidate Release 必须匹配 Result Release | `tests/contract/knowledge_service/test_knowledge_query_result_contract.py` | 失败符合预期：跨 Release candidate 被接受 |
| GREEN-RESULT-006 | Result aggregate 拒绝跨 Release Candidate | `services/knowledge-source-service/knowledge_source_service/contracts/results.py` | targeted result tests：6 passed |
| RED-RESULT-007 | succeeded Query 必须携带 typed available result | `tests/contract/knowledge_service/test_knowledge_query_result_contract.py` | 失败符合预期：Resource 的 `result` 只接受 `None` |
| GREEN-RESULT-007 | 提取 shared contract base 并绑定 typed result/problem | `services/knowledge-source-service/knowledge_source_service/contracts/{base.py,knowledge_query.py,results.py}` | service contract suite：33 passed |
| REFACTOR-RESULT-002 | 提取 succeeded Query golden factory | `tests/contract/knowledge_service/test_knowledge_query_result_contract.py` | targeted result tests：7 passed |
| RED-RESULT-008 | 非 succeeded/available Query 不得携带 result | `tests/contract/knowledge_service/test_knowledge_query_result_contract.py` | 失败符合预期：running Query 接受并暴露完整 Result |
| GREEN-RESULT-008 | Resource validator 限制 Result visibility | `services/knowledge-source-service/knowledge_source_service/contracts/knowledge_query.py` | targeted result tests：8 passed |
| RED-RESULT-009 | available result 必须含 content 与 expiry | `tests/contract/knowledge_service/test_knowledge_query_result_contract.py` | 失败符合预期：available Query 接受空 content/expiry |
| GREEN-RESULT-009 | available Result 要求 content 与 retention expiry | `services/knowledge-source-service/knowledge_source_service/contracts/knowledge_query.py` | targeted result tests：9 passed |
| RED-RESULT-010 | execution state 与 result availability 不得混淆 | `tests/contract/knowledge_service/test_knowledge_query_result_contract.py` | 失败符合预期：cancelled execution 接受 `result_availability=expired` |
| GREEN-RESULT-010 | 固定 execution state/result availability 映射 | `services/knowledge-source-service/knowledge_source_service/contracts/knowledge_query.py` | service contract suite：36 passed；Ruff/mypy 通过 |
| RED-EXEC-001 | executor 必须完成一条 queued Query | `tests/contract/knowledge_service/test_knowledge_query_executor.py` | 失败符合预期：缺少 `application.query_executor` module |
| GREEN-EXEC-001 | 实现 create→claim→retrieve→succeeded tracer | `services/knowledge-source-service/knowledge_source_service/{domain,ports,adapters,application}/` | targeted executor test：1 passed |
| REFACTOR-EXEC-001 | 提取 executor runtime/create helpers | `tests/contract/knowledge_service/test_knowledge_query_executor.py` | targeted executor test：1 passed |
| RED-EXEC-002 | 未预期检索失败必须安全收敛且不得泄漏内部异常 | `tests/contract/knowledge_service/test_knowledge_query_executor.py` | 失败符合预期：executor 缺少 trace factory seam，无法构造安全 terminal failure |
| GREEN-EXEC-002 | 捕获检索异常并持久化 trace-safe terminal failure | `services/knowledge-source-service/knowledge_source_service/application/query_executor.py` | targeted executor tests：2 passed |
| REFACTOR-EXEC-002 | 提取公共执行失败 Problem 构造并清理测试时钟 | executor 与 contract test | targeted executor tests：2 passed；Ruff/mypy 通过 |
| RED-EXEC-003 | queued Query 在领取时已到 deadline 不得调用检索 | `tests/contract/knowledge_service/test_knowledge_query_executor.py` | 失败符合预期：检索被调用一次且 Query 错误成功 |
| GREEN-EXEC-003 | 在任何检索调用前执行 absolute deadline 闸门 | `services/knowledge-source-service/knowledge_source_service/application/query_executor.py` | targeted executor tests：3 passed |
| RED-EXEC-004 | deadline 时到达的 late result 不得提交 success | `tests/contract/knowledge_service/test_knowledge_query_executor.py` | 失败符合预期：late result 被错误持久化为 `succeeded` |
| GREEN-EXEC-004 | terminal commit 前再次校验 deadline 并丢弃 late result | `services/knowledge-source-service/knowledge_source_service/application/query_executor.py` | targeted executor tests：4 passed |
| REFACTOR-EXEC-004 | 合并领取前与提交前的执行过期状态写入 | `services/knowledge-source-service/knowledge_source_service/application/query_executor.py` | targeted executor tests：4 passed；Ruff/mypy 通过 |
| RED-EXEC-005 | running Query 被取消后旧 executor 不得提交 success | `tests/contract/knowledge_service/test_knowledge_query_executor.py` | 失败符合预期：旧 running 快照覆盖了 `cancelled` 终态 |
| GREEN-EXEC-005 | provider 返回后重读权威状态，非 running 时停止 terminal commit | `services/knowledge-source-service/knowledge_source_service/application/query_executor.py` | targeted executor tests：5 passed |
| REFACTOR-EXEC-005 | 提取统一的 running-state recheck seam | `services/knowledge-source-service/knowledge_source_service/application/query_executor.py` | targeted executor tests：5 passed；Ruff/mypy 通过 |
| RED-STATE-001 | cancel 不得改写 succeeded terminal Query | executor/HTTP contract test | 失败符合预期：构造了携带 Result 的非法 cancelled resource 并触发响应校验异常 |
| GREEN-STATE-001 | terminal cancel 返回稳定 409，合法 cancel 使用完整模型校验 | application/delivery modules | service contract suite：42 passed；Ruff/mypy 通过 |
| RED-AUTH-001 | 一个 Space 可授权多个 Agent，但未授权 Agent 必须拒绝 | HTTP contract test | 失败符合预期：application 尚无 authorizer seam |
| GREEN-AUTH-001 | 引入 Release-derived admission port，并冻结 Space/Grant/scope facts | ports/application/domain/delivery modules | service contract suite：43 passed；Ruff/mypy 通过 |
| RED-AUTH-002 | executor 必须把冻结 admission context 传入 retrieval | executor contract test | 失败符合预期：retrieval 只收到原始 caller request，缺少服务推导的权限事实 |
| GREEN-AUTH-002 | 用 `AdmittedKnowledgeQuery` 贯通 request 与冻结 authority facts | retrieval port/executor | service contract suite：44 passed；Ruff/mypy 通过 |
| RED-TRACER-001 | Markdown + CSV 必须在同一 Release 返回 mixed typed Evidence Groups | hybrid retrieval tracer contract | 失败符合预期：缺少 Knowledge Catalog 与 Hybrid retrieval modules |
| GREEN-TRACER-001 | 实现 immutable catalog、Markdown units、typed CSV 与 mixed hybrid retrieval | domain/catalog/retrieval modules | targeted tracer：1 passed；Ruff/mypy 通过 |
| REFACTOR-TRACER-001 | 统一 Release、Evidence Unit 与 Query Plan 的 canonical content addressing | `domain/identities.py` | service contract suite：45 passed；Ruff/mypy 通过 |
| GREEN-AGENTIC-001 | 实现 content-free Agentic controller port 与 bounded multi-round engine | Agentic application/port modules | targeted Agentic test：1 passed；Ruff/mypy 通过 |
| RED-PA-001 | ProofAgent client 必须完成 create→poll 并保留 typed Candidate Evidence | ProofAgent adapter contract | 失败符合预期：缺少 Knowledge Source Service client adapter |
| GREEN-PA-001 | 实现 strict consumer contract、Candidate Service port 与 guarded HTTP client | ProofAgent contracts/adapter | targeted client test：1 passed；Ruff/mypy 通过 |
| RED-PA-002 | Control Plane 必须路由远程 exact Query 且保留 Structured Group | ProofAgent retrieval integration test | 失败符合预期：KnowledgeRetrievalService 尚无 Candidate Service dependency seam |
| GREEN-PA-002 | Control Plane 新增远程分支并保持 relevance/structured 边界 | ProofAgent retrieval service | new + legacy retrieval tests：30 passed；Ruff/mypy 通过 |
| RED-PA-003 | Published Agent factory 必须稳定生成 exact-Release semantic-attempt Query | Query factory contract | 失败符合预期：缺少 candidate request factory module |
| GREEN-PA-003 | 实现 exact Release/budget/context-bound stable Query factory | ProofAgent candidate request module | targeted factory test：1 passed；Ruff/mypy 通过 |
| RED-PA-004 | Harness composition 必须保留 Candidate Service 与 exact Query factory | composition contract | 失败符合预期：compose function 尚不接受远程 Candidate dependencies |
| GREEN-PA-004 | Candidate Service/factory 成对贯通 HarnessInvocation 与 controlled retrieval | bootstrap/workflow composition | composition/client tests：16 passed；Ruff/mypy 通过 |
| RED-PG-001 | PostgreSQL 必须跨 repository 精确重建 admitted Query | PostgreSQL integration contract | 失败符合预期：缺少 service-owned PostgreSQL adapter package |
| GREEN-PG-001 | 实现 service-owned migration 与完整 admitted Query 持久化/重建 | PostgreSQL adapter、migration 与隔离 schema fixture | 真实 PostgreSQL：1 passed；Ruff/mypy 通过 |
| RED-PG-002 | 过期租约可接管，但旧 worker 不得提交 | PostgreSQL lease/fencing integration contract | 失败符合预期：缺少 claim domain type 与 fenced repository API |
| GREEN-PG-002 | 使用 `FOR UPDATE SKIP LOCKED`、租约和单调 fencing token 原子领取 | PostgreSQL/memory repository、executor port | 真实 PostgreSQL：2 passed；executor：7 passed |
| REFACTOR-PG-002 | executor 所有状态提交统一走 fenced `save_claim` | executor、repository protocol 与 memory tracer | service contract：46 passed；Ruff/mypy 通过 |
| RED-PG-003 | 旧版本取消不得覆盖并发完成的终态 | PostgreSQL CAS integration contract | 失败符合预期：旧 `add` 无条件覆盖 `failed` 为 `cancelled` |
| GREEN-PG-003 | internal record 引入 `state_version`，外部状态更新执行 compare-and-swap | domain、PostgreSQL/memory repository | 真实 PostgreSQL：3 passed；service contract：46 passed；Ruff/mypy 通过 |
| RED-ARTIFACT-001 | Source original/canonical/manifest 必须先于 catalog visibility 固化 | document intake/release tracer | 失败符合预期：缺少 immutable artifact authority 与 publication application |
| GREEN-ARTIFACT-001 | 实现精确版本 artifact reference、S3-first Source Version 与 Release manifest | artifact/domain/intake/release modules | memory tracer 与真实 MinIO contract 通过 |
| RED-CATALOG-001 | 进程重启后必须从 PostgreSQL + exact S3 artifacts 重建 Source/Release | PostgreSQL/S3 publication contracts | 失败符合预期：缺少 durable catalog schema/adapter |
| GREEN-CATALOG-001 | PostgreSQL 管 visibility，S3 管内容；跨 Space FK 与 manifest digest 失败关闭 | catalog migration/adapter | document、dataset 的真实 PostgreSQL+MinIO contracts 通过 |
| RED-DATASET-001 | CSV 必须保留显式类型、稳定 record identity 与 typed filtering | dataset publication contract | 失败符合预期：缺少 typed Dataset Revision intake |
| GREEN-DATASET-001 | 实现 CSV Dataset Revision、typed values、record manifest 与 structured group | dataset intake/retrieval/catalog | 真实 PostgreSQL+MinIO contract 通过 |
| RED-ACCESS-001 | 多 Agent credential/grant 不得串用 Release 或扩大预算 | PostgreSQL access-control contract | 失败符合预期：缺少 durable client/grant authority |
| GREEN-ACCESS-001 | credential 仅存 hash；grant 固定 Release、策略、预算与 scope digest | access migration/adapter | 真实 PostgreSQL contract 通过 |
| RED-RUNTIME-001 | 独立 API/Executor 必须经 durable queue 完成 exact retrieval | runtime composition contract | 失败符合预期：缺少 production composition root |
| GREEN-RUNTIME-001 | FastAPI、PostgreSQL queue、fenced executor、catalog 和 S3 组成独立 runtime | bootstrap/runtime/process modules | 真实 PostgreSQL runtime contract 通过 |
| RED-RESULT-ARTIFACT-001 | available Result 不得以内联 JSON 作为 PostgreSQL 内容权威 | runtime persistence contract | 失败符合预期：`query_json.result` 保存完整结果 |
| GREEN-RESULT-ARTIFACT-001 | Result 先写 immutable artifact；PostgreSQL 只绑定 digest/reference/count | migration/repository/runtime | 真实 PostgreSQL runtime contract 通过 |
| RED-MGMT-001 | Operator API 必须完成 Source intake 与 exact Release publication 且不泄漏存储定位 | management HTTP contract | 失败符合预期：缺少 management delivery adapter |
| GREEN-MGMT-001 | 实现 Space/Source/Base、multipart intake 与 Release endpoints | management HTTP/intake modules | 真实 PostgreSQL management contract 通过 |
| RED-SEARCH-001 | Lexical、Sparse、Dense 必须保留独立 native score/rank | OpenSearch projection contract | 失败符合预期：缺少 search projection port/adapter |
| GREEN-SEARCH-001 | 实现 BM25、rank_features、HNSW/Lucene 三 lane 与 strict mapping | OpenSearch adapter | 真实 OpenSearch contract 通过 |
| RED-INDEXED-001 | Release 必须固定 index attestation，查询内容必须从 exact artifact 还原 | indexed release retrieval contract | 失败符合预期：缺少 indexed retrieval application |
| GREEN-INDEXED-001 | Release 固定 mapping/corpus/encoder；查询前 verify generation，再执行 weighted RRF | release/catalog/indexed retrieval | 真实 PostgreSQL+MinIO+OpenSearch contract 通过 |
| REFACTOR-INDEXED-001 | 相同 Release publication 可幂等验证并重用相同物理 generation | OpenSearch adapter/release contract | 真实三依赖 contract 通过 |
| RED-AGENTIC-002 | runtime 必须执行显式 Agentic，未配置 controller 时不得伪装成功 | runtime/Agentic contracts | 失败符合预期：composition 未接 Agentic controller |
| GREEN-AGENTIC-002 | runtime 接入 bounded controller；冻结 scope，约束 rounds/calls/tokens/time，缺失时失败关闭 | Agentic/runtime/http adapter | Agentic 与 runtime contracts 通过 |
| RED-PA-005 | ProofAgent 真实 client 必须穿过 KSS API、queue、executor 和 Result contract | runtime cross-boundary contract | 失败前仅有双方独立 mock contracts |
| GREEN-PA-005 | TestClient-backed guarded transport 完成 ProofAgent→KSS create/poll/Candidate Evidence 闭环 | ProofAgent client + KSS runtime | 真实 PostgreSQL cross-boundary contract 通过 |
| RED-FORMAT-001 | HTML active content 不得进入 canonical evidence，citation 仍绑定 source line | document tracer | 失败符合预期：`text/html` 不受支持 |
| GREEN-FORMAT-001 | 增加无外部加载 HTML parser，丢弃 script/style/template/noscript | document intake/management | HTML Source→Release→Query tracer 通过 |
| RED-FORMAT-002 | mapped JSON/JSONL 必须形成 typed Dataset 并保留 exact original media type | JSON dataset contracts | 失败符合预期：缺少 JSON intake 且 catalog 硬编码 `text/csv` |
| GREEN-FORMAT-002 | 增加 strict mapped JSON/JSONL、duplicate/unknown-field rejection 与 durable media type | JSON intake/catalog/management | memory + 真实 PostgreSQL/MinIO contracts 通过 |
| RED-RETENTION-001 | Result 到期后 API 与 durable catalog 均不得继续暴露内容引用 | executor/runtime contracts | 失败符合预期：到期后仍返回 available Result |
| GREEN-RETENTION-001 | API 生成 retention-safe view；reaper 原子解绑 artifact 并写 outbox，scheduler 周期执行 | application/repository/process modules | executor + 真实 PostgreSQL runtime contracts 通过 |
| RED-BUDGET-001 | mixed relevance/structured candidates 总数不得超过一个全局 hard budget | hybrid tracer | 失败符合预期：两个 group 分别消耗 `max_candidates` |
| GREEN-BUDGET-001 | relevance 优先后以剩余预算约束 structured；indexed path 同样截断 | hybrid/indexed retrieval | targeted mixed contract 通过 |
| RED-ENCODER-001 | 生产 Dense/Sparse 不得依赖测试 hashing baseline | private encoder contract | 失败符合预期：缺少 private encoder adapter |
| GREEN-ENCODER-001 | 实现 strict private HTTP encoder，固定 revision/dimension，拒绝非法/非有限向量 | HTTP encoder/process composition | encoder、process、mypy、Ruff 通过 |
| RED-FORMAT-003 | PDF、DOCX、PPTX、XLSX、Parquet 与 OCR 输入缺少可重放 locator | format contracts | 失败符合预期：对应 adapter 或 citation variant 不存在 |
| GREEN-FORMAT-003 | 实现 native PDF、DOCX、PPTX、XLSX、Parquet、PNG/JPEG/TIFF OCR 和 scanned-PDF escalation | intake/catalog/management contracts | 各格式 Source→Release→Query 与真实 S3 重放通过 |
| RED-STRUCTURED-001 | grouped aggregate、decimal comparison 与 aggregate citation 不受 typed AST 约束 | structured analysis contracts | 失败符合预期：仅支持 legacy record filter |
| GREEN-STRUCTURED-001 | 实现 bounded structured query、projection/filter/sort/group/aggregate、确定性 Decimal 与 input-set lineage | query/result/retrieval/ProofAgent contracts | typed analysis 与 consumer contract 通过 |
| RED-SNAPSHOT-001 | HTTP JSON、PostgreSQL 与 object manifest 不能形成 query-time independent Source Version | external snapshot contracts | 失败符合预期：缺少 snapshot ports/adapters |
| GREEN-SNAPSHOT-001 | 实现 static HTTPS、read-only repeatable PostgreSQL 和 exact object-manifest materialization | snapshot/intake/security contracts | Query 后不再调用 upstream；old Release 保持不变 |
| RED-SYNC-001 | 外部 snapshot 只能进程内调用，运行服务没有 durable synchronization resource | synchronization application/API/runtime contracts | 失败符合预期：缺少 resource、queue、worker 和 route |
| GREEN-SYNC-001 | 实现 `/v1/knowledge-source-synchronizations`、PostgreSQL queue、operator-scoped idempotency、lease/fencing/heartbeat 与 Knowledge Worker | migration/repository/worker/management/runtime | memory、真实 PostgreSQL 与 runtime contracts 通过 |
| RED-LEASE-001 | 长耗时 Query 或 Source capture 可在执行中失去租约并被重复领取 | executor concurrency contracts | 失败符合预期：repository/executor 缺少 renew seam |
| GREEN-LEASE-001 | Query 与 synchronization 在 lease 的 1/3 周期续租；续租失败或 fence 失效时丢弃结果 | repository/executor contracts | deterministic concurrency 与真实 PostgreSQL contracts 通过 |
| RED-INTEGRITY-001 | Knowledge Worker 没有可执行的 durable offline work | process/integrity contracts | 失败符合预期：role 直接退出 2 |
| GREEN-INTEGRITY-001 | Worker 有界重放 PostgreSQL/S3 Release authority 并核验 OpenSearch attestation | worker/process/real-dependency contracts | 真实三依赖 integrity regression 通过 |
| RED-CITATION-001 | ProofAgent 将非 `text_lines` locator 当作行号读取 | consumer integration + strict mypy | PDF locator 触发 `AttributeError`；mypy 报 union-attr |
| GREEN-CITATION-001 | 七类 document locator 映射为稳定 `knowledge://` fragment | ProofAgent retrieval integration | 7 个 locator 参数化回归与 strict mypy 通过 |
| RED-ENCODER-002 | 显式 deterministic encoder 与自定义 dense dimension 组合必须可启动 | process distribution contract | 失败符合预期：dimension 被误判为远程 encoder 配置并报告字段不完整 |
| GREEN-ENCODER-002 | 仅 endpoint/token/revision 激活远程 encoder；deterministic 模式独立接受 dimension | KSS process composition | targeted distribution tests 通过；Ruff 与 strict mypy 通过 |
| RED-PA-006 | 公共 Agent Package 运行入口必须可注入 exact Candidate Service 与 Query factory | Agent Package execution contract | 失败符合预期：`AgentPackageRunRequest` 不接受远程 Knowledge 依赖 |
| GREEN-PA-006 | 远程 Candidate Service 与 Query factory 贯通 Agent Package composition | delivery/bootstrap composition | Agent Package 与 composition targeted tests 通过 |
| RED-PA-007 | KSS 保持 Candidate-only 时，ProofAgent 必须有显式已批准 Admission Scorer 组合缝 | Control Plane integration + real runtime smoke | 无评分器的真实运行正确收敛为 `REFUSED_NO_EVIDENCE`；融合名次不得伪装为 Admission Score |
| GREEN-PA-007 | 新增批量 Candidate Admission Scorer port，记录 scorer identity/revision，默认仍失败关闭 | contracts/retrieval/bootstrap/workflow composition | 有评分器的真实运行返回 `ANSWERED_WITH_CITATIONS`；无评分器回归保持 failed |
| RED-PA-008 | Admission Scorer 越界值不得进入 Evidence Threshold | ProofAgent client integration | 失败符合预期：`1.01` 被当作普通 admission score 接受 |
| GREEN-PA-008 | Control Plane 只接受 0–1 的有限 Admission Score | ProofAgent retrieval service | 越界值以 `PA_KNOWLEDGE_001` 失败关闭 |
| VERIFY-KSS-001 | KSS contract suite | `tests/contract/knowledge_service` | 104 passed；使用真实 PostgreSQL、MinIO、OpenSearch |
| VERIFY-PA-001 | ProofAgent remote client、query factory、composition 与 citation | ProofAgent targeted suites | 25 passed；Ruff 与 strict mypy 通过 |
| VERIFY-REPO-001 | 仓库默认完整回归 | root `pytest -q` + localhost 定向复跑 | 3156 passed；133 skipped；13 marker-deselected；无代码失败 |
| VERIFY-IMAGE-001 | 独立 OCI image | Docker build、inspect、ephemeral `roles` | image `sha256:05e9f975…` 构建成功；UID/GID `10001:10001`；五角色 CLI 通过 |
| VERIFY-RUNTIME-002 | Markdown + typed CSV Release 经真实 KSS API、queue、executor、ProofAgent Control Plane 与最终回答 | loopback runtime smoke | Query `knowledge-query-cb42a6e21c914fd1b40d4e4691f38811`；2 条 accepted cited evidence；回答包含 300 元与所需材料 |
| VERIFY-IMAGE-002 | 重建最终 KSS 与 Agent 镜像并执行角色/API/问答 smoke | Docker build、inspect、run | KSS `sha256:e9742d85…`；Agent `sha256:f6f66c97…`；均为 UID/GID `10001:10001`；KSS 五角色与 Agent cited-answer 通过 |
| RED-DEPLOY-001 | KSS 五角色必须进入完整类生产 Compose，并经独立 TLS 入口和私有模型协议运行 | deployment contract | 失败符合预期：Compose 中没有 KSS 角色，模型兼容面缺少 KSS projection、Agentic 和 OCR 协议 |
| GREEN-DEPLOY-001 | 新增 KSS 五角色、`8444` TLS 入口、三个受 Bearer 保护的模型协议和显式私有 CA 装配 | Compose、nginx、model plane、KSS adapters | 部署契约与模型协议定向测试通过；Compose 展开校验通过 |
| RED-DEPLOY-002 | KSS 与 ProofAgent 不能共享同一逻辑 PostgreSQL database | real migration startup | 首次迁移因双方独立拥有同名 `knowledge_sources` 表而失败关闭 |
| GREEN-DEPLOY-002 | 新增幂等数据库初始化 Job，KSS 独占 `knowledge_source_service` database 和迁移 ledger | Compose migration authority | 初始化与六个 KSS migration 均退出 0；KSS readiness 的 PostgreSQL、对象存储和搜索均为 `ready` |
| RED-DEPLOY-003 | 独立逻辑数据库还必须使用独立登录凭证，并可重复检测对象所有权漂移 | deployment authority contract | 失败符合预期：KSS DSN 仍复用 `proof` 角色，验收脚本未检查角色、数据库、schema 和表所有权 |
| GREEN-DEPLOY-003 | 生成独立随机凭证，幂等创建非超级用户 `knowledge_source_service` 角色，仅迁移 KSS 数据库 `public` schema 内对象，并加入失败关闭验收 | Compose database initialization + verifier | 保留现有数据；KSS database、`public` schema 和 13 张表均由专用角色拥有；`proof` database 所有权不变；更新后的 verifier 通过 |
| VERIFY-DEPLOY-001 | 完整类生产 Docker 栈、异构摄取、标准/结构化/Agentic 查询和 ProofAgent 问答 | retained Compose runtime | KSS `sha256:97c2db1f…`；Agent `sha256:cc4f8014…`；KSS 五角色 non-root/read-only；精确 Release `release-a4b70851cb914862000e15c3` 返回 3 个 single-pass、2 个 structured、3 个 Agentic candidates；ProofAgent 为 `ANSWERED_WITH_CITATIONS` |

## 7. 实现产物

| 范围 | 主要产物 |
| --- | --- |
| 独立服务 | `services/knowledge-source-service/` distribution、Dockerfile、运行手册、五个 process entry point、六个 PostgreSQL migration |
| Authority | PostgreSQL Query/Grant/Catalog/Synchronization authority；S3 immutable originals/canonical/manifests/results；OpenSearch rebuildable generation |
| Intake | Markdown、text、HTML、PDF、DOCX、PPTX、PNG/JPEG/TIFF、CSV、XLSX、mapped JSON/JSONL、Parquet、HTTP JSON、PostgreSQL snapshot、object manifest |
| Query | exact Release `KnowledgeQuery` API；Lexical/Sparse/Dense weighted RRF；typed Structured analysis；显式 bounded Agentic |
| Integration | ProofAgent `KnowledgeCandidateService` port、strict remote client、stable request factory、显式 `KnowledgeCandidateAdmissionScorer`、Control Plane composition |

## 8. 最终验证记录

| 命令或证据 | 结果 |
| --- | --- |
| `pytest -q tests/contract/knowledge_service`，启用 required PostgreSQL/S3/Search flags | 104 passed |
| 2026-08-12 final affected deployment/integration suites | 95 passed |
| `ruff check`：KSS、ProofAgent 变更与测试 | passed |
| `mypy --strict`：KSS 76 source files 与 ProofAgent 429 source files | passed |
| root `pytest -q` | 3148 passed；8 个 localhost bind 用例受 sandbox 阻止；授权环境定向复跑 8 passed |
| `docker build` + image inspect + runtime smoke | KSS `sha256:e9742d85…`、Agent `sha256:f6f66c97…`；non-root；KSS 五角色、Agent API health 和 cited-answer 通过 |
| 真实 KSS → ProofAgent 问答 | `ANSWERED_WITH_CITATIONS`；精确绑定 `release-3e5ac7da4da3e2bc9bd6f480`；回答包含 300 元、登机牌和航空公司延误证明 |
| 2026-08-12 类生产 Compose 部署 | KSS `sha256:97c2db1f…`、Agent `sha256:cc4f8014…`；KSS API/Executor/Worker/Scheduler 运行；Migration 与 Database Init 退出 0；`8444/readyz` 为 `ready`；数据库权限隔离验收通过 |
| 类生产异构查询与 Agent 接入 | Markdown + typed CSV；single-pass、structured、Agentic 均成功；ProofAgent 通过 guarded HTTPS 和显式 compatibility scorer 返回 `ANSWERED_WITH_CITATIONS`，答案包含 4 小时、300 元和 30 天 |
| KSS 真实依赖契约复跑 | PostgreSQL、MinIO、OpenSearch 均为 required；105 passed |
| `git diff --check` | passed |

## 9. 生产前剩余事项

[KNOWN | HIGH] 下列事项不阻断本 Goal 的本地功能验收，但阻断“生产就绪”表述。

| 问题 | 等级 | 影响 | 建议动作 |
| --- | --- | --- | --- |
| 企业 OIDC、细粒度 operator permission 与配置审计尚未接入 | P1 | 管理面生产身份与审计 | 在 deployment/security slice 实现并演练 |
| ProofAgent 远程 client、Admission Scorer 仍由显式 composition 注入；当前类生产验证使用一次性 compatibility scorer 和预置 client credential，生产 scorer 校准/批准、Published Agent deployment binding、Secret Provider credential wiring 和 Client Grant provisioning 尚未产品化 | P1 | 长期运行的生产 Agent 启用、Evidence Admission 与凭证轮换 | 通过受控发布流程批准 scorer revision，并由 Secret Provider 和 Control Plane 完成部署装配；不得把 KSS rank 当分数或使用本地 provider 回退 |
| 正式 OpenAPI golden、client generation compatibility gate 尚未冻结 | P1 | 跨版本兼容 | 发布候选前生成并纳入 CI |
| Release Preparation one-use CAS、shadow/pilot/cutover 尚未实施 | P1 | 生产发布与回滚 | 按 Task 4、13、14 单独执行发布工程 |
| content-level ACL narrowing、reranker/context expansion 尚未交付 | P1 | 细粒度授权与质量 | 未启用这些能力前保持 fail closed，不声明支持 |
| 生产预算、SLO、retention 与 provider revision 尚待运行数据批准 | P2 | 容量、成本和超时 | 通过 load/shadow 数据校准并审批 |

## 10. 上下文更新

| 位置 | 更新 |
| --- | --- |
| `docs/features/knowledge-source-service/feature_context.md` | Goal 状态改为 `VERIFIED_LOCAL`；保留生产批准边界 |
| `docs/PROJ_CONTEXT.md` | feature index 改为 `VERIFIED_LOCAL` 并记录实际服务入口与验证事实 |
