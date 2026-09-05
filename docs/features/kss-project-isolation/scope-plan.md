# KSS 独立项目隔离 Scope、准入与 TDD 计划

## 1. 建议结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | `TDD_INPUT_READY` |
| 最高风险等级 | P1 |
| 一句话依据 | 用户已选定独立项目方案；既有 ADR 已固定服务权威和 HTTP 边界，当前代码依赖可定位，生产数据/部署/远端均明确排除 |
| 下一步建议 | 按双项目 repository-boundary tracer 执行 `hicode:tdd` |

## 2. 依据与输入缺口

| 材料 | 来源 | 是否读取 | 关键证据 | 缺口 |
| --- | --- | --- | --- | --- |
| 项目规则 | `AGENTS.md`、`AGENTS-COMMON.md`、hicode rules | 是 | TDD、fail-closed、active docs、秘密边界 | 无 |
| 当前上下文 | `docs/PROJ_CONTEXT.md`、`docs/DOMAIN_KNOWLEDGE.md` | 是 | KSS 当前仍位于 ProofAgent 根目录 | 需随迁移更新 |
| KSS 设计 | feature docs、ADR-0192 至 ADR-0210 | 是 | KSS 独立逻辑权威、exact Release、Candidate Evidence | 无语义缺口 |
| 当前代码 | KSS package、distribution、tests、Compose、ProofAgent clients | 是 | ProofAgent 运行代码没有直接 import KSS；主要耦合在仓库布局、测试和构建 | 无 |
| 新项目位置 | 同级 `/Users/jamin/Dev/mz-projects/KSS` | 已检查 | 目标不存在，避免覆盖 | 远端未指定，非本轮阻断 |

## 3. 需求准入评审

| 项 | 内容 |
| --- | --- |
| 准入结论 | `NO_BLOCKING_GAPS` |
| 需求分析输入 | 用户指令、active docs、源文件/测试引用盘点、Compose 和 distribution 事实 |
| 证据缺口 | 远端地址、完整历史迁移方式、正式生产数据/部署 cutover；均排除在本轮本地代码迁移之外 |
| 复杂度处理 | 采用四个可独立验证切片，不把生产 cutover 混入代码仓库拆分 |

## 4. 需求分析与范围边界

| 项 | 内容 |
| --- | --- |
| 需求目标 | KSS 成为独立源码与发布项目，ProofAgent 仅通过受控 HTTP/工件契约依赖它 |
| 范围内 | 新 KSS 项目、源码/测试/build/lock 迁移、ProofAgent 源码移除、外部镜像 Compose 契约、active docs |
| 范围外 | 生产数据迁移、远端/push、生产部署/切流、公共 API 或领域模型变化 |
| 非目标 | 取消 KSS；复制两套实现；把 KSS token 暴露给 Dashboard；以本地测试宣称 Production GO |
| 验收标准 | 双向 import 禁止；ProofAgent 不含 KSS 实现/构建；KSS 独立 tests/static/lock 通过；ProofAgent 相关回归通过 |
| feature_context 更新 | 已创建 |
| ADR 处理 | 新增 ADR-0239，记录物理项目与发布所有权 |

## 5. 设计树方案

| 节点 | 类型 | 触发条件/输入 | 处理方案 | 输出/状态变化 | 范围边界 | 验证点 | 风险等级 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ROOT | 业务目标 | 独立 KSS 项目 | 源码与发布 ownership hard split | 双项目 | 不改变业务语义 | boundary suite | P1 |
| MAIN-1 | KSS 项目 | 当前 KSS package/distribution/tests | 根级 package + pyproject + Dockerfile + CI/docs | 可独立 build/test | 无 ProofAgent dependency | KSS test/static/lock | P1 |
| MAIN-2 | ProofAgent | 嵌入 KSS source/build/tests | 删除实现所有权，保留 clients/contracts | PA 仓库瘦身 | 不移除 Admission/BFF | PA regression/import scan | P1 |
| MAIN-3 | 集成 | 当前 Compose build KSS | 外部 `KSS_IMAGE` fail-closed 注入 | black-box dependency | 不执行发布 | Compose tests | P1 |
| MAIN-4 | 文档 | 当前事实漂移 | 更新 active docs/index/ADR | 可追溯边界 | 历史文档不重写 | context checker | P2 |
| BRANCH-1 | Cross tests | tests import 两个产品 | 拆成 KSS 内部 tests 与 ProofAgent 边界 tests | 无反向包依赖 | 实际跨服务运行留给 integration harness | import scan | P1 |
| BRANCH-2 | Missing artifact | `KSS_IMAGE` 缺失 | Compose 配置失败关闭 | 无隐式构建/回退 | 本地使用者需先构建 KSS | negative test | P1 |
| BRANCH-3 | Runtime state | 现有数据/容器可能存在 | 不读取、不修改、不删除 | 运行态不变 | 只改工作区文件 | command audit | P1 |

## 6. 澄清问题队列

| 问题 | 状态 | 推荐答案 | 推荐理由 | 影响 | 建议确认人 |
| --- | --- | --- | --- | --- | --- |
| 是否 hard split | 已关闭 | 是 | 用户明确要求独立项目并隔离 | 选择方案 | 用户 |
| 新项目本地路径 | 已关闭 | `/Users/jamin/Dev/mz-projects/KSS` | 与现有项目同级且目标不存在 | 文件位置 | 当前实现假设，可轻易更名 |
| 是否保留 PA 对 KSS 的源码 build | 已关闭 | 否 | 否则发布所有权仍耦合 | Compose/build | 用户目标与架构规则 |
| 是否本轮迁移生产数据/部署 | 已关闭 | 否 | 需要额外 authority 和 Gate | 无运行态变更 | 项目规则 |
| 远端与历史策略 | 待负责人确认，非阻断 | 本轮仅本地独立 repo + provenance | 避免擅自 push 或重写历史 | 后续协作 | 用户/仓库负责人 |

## 7. 关键规则与影响范围

| 对象 | 影响说明 | 证据来源 | 确认状态 | 风险等级 |
| --- | --- | --- | --- | --- |
| Candidate Evidence | 不改变 KSS 输出边界 | ADR-0192、ADR-0210 | 已确认 | P1 |
| exact Release | 不改变查询/Grant/Reference identity | active domain context | 已确认 | P1 |
| KSS image | 由独立项目构建并以精确工件 identity 被消费 | Candidate Binding v2 | 已确认 | P1 |
| ProofAgent clients | 保留 guarded HTTP、Vault handle、egress policy | current code | 已确认 | P1 |
| 生产数据 | 不在本轮移动 | AGENTS-COMMON production boundary | 已确认 | P1 |

## 8. 风险与阻断建议

| 风险 | 等级 | 证据 | 建议动作 | 建议确认人 |
| --- | --- | --- | --- | --- |
| 移动后丢失 KSS 回归覆盖 | P1 | 51 个 KSS contract 文件 | 测试随项目迁移并在新项目执行 | 代码评审人 |
| Cross test 形成反向 ProofAgent 依赖 | P1 | 两个 test 文件直接 import ProofAgent | 不迁入跨产品场景；以黑盒边界替代 | 架构评审人 |
| Compose 仍隐式构建旧源码 | P1 | 当前 `kss-api.build` | RED test 后改为必填外部 image | 发布评审人 |
| 误触本地/生产数据 | P1 | 现有 production-local 依赖 | 不启动、不 down、不删 volume；只做静态与单元验证 | 数据/发布负责人 |
| 历史可追溯性降低 | P2 | 新项目默认 snapshot | 记录来源 commit；后续可执行经确认的历史迁移 | 仓库负责人 |

## 9. 推荐方案与取舍

| 方案 | 是否推荐 | 主干逻辑 | 收益 | 代价或风险 | 不选原因 |
| --- | --- | --- | --- | --- | --- |
| 独立 repo + 外部 OCI/HTTPS 契约 | 是 | KSS owns build/release，PA owns clients/governance | 权威、依赖和发布边界清晰 | 双项目变更与 integration fixture 维护 | — |
| 独立目录但仍由 PA monorepo 构建 | 否 | 目录拆分、发布不拆 | 改动较少 | 仍共享 lock/CI/build authority | 不满足项目隔离 |
| Git submodule | 否 | PA checkout 嵌套 KSS repo | 可锁 commit | 开发/CI 仍由 PA 树管理且易产生 submodule 漂移 | 当前无此约束需要 |

## 10. 设计树到 TDD 任务计划

| 任务 | 对应节点 | 目标 | RED 起点 | GREEN/验证 | 停止条件 |
| --- | --- | --- | --- | --- | --- |
| TDD-01 repository boundary | ROOT、MAIN-1、MAIN-2 | 双项目布局与双向 import 禁止 | ProofAgent boundary test 在旧目录存在时失败；KSS project test 在包缺失时失败 | 移动 package/tests/build metadata，两个 boundary tests 通过 | 发现运行代码直接 import 跨项目包 |
| TDD-02 external artifact | MAIN-3、BRANCH-2 | PA Compose 只消费外部 image | 测试断言 `build` 不存在且 image 必填 | Compose contract 与 config negative/positive 通过 | 需要访问 registry 或部署 |
| TDD-03 dependency/test ownership | MAIN-1、BRANCH-1 | 拆 lock、CI 和测试归属 | KSS 独立 test/static/lock 失败或 PA 仍收集 KSS tests | 两项目 focused tests 通过 | 必须弱化断言或引入反向依赖 |
| TDD-04 docs and evidence | MAIN-4 | 更新 active truth 与 ADR | domain checker/grep 暴露旧事实 | docs checker 与 diff check 通过 | 需要改写历史证据 |

| 项 | 内容 |
| --- | --- |
| 任务计划结论 | `TDD_INPUT_READY` |
| 下一步路由 | `hicode:tdd` |
| 未覆盖设计树节点 | 生产数据/部署 cutover、远端与完整历史迁移明确延期 |

## 11. TDD 输入与测试重点

| 设计树节点 | 场景 | 类型 | 优先级 | 数据要求 | 对应任务 |
| --- | --- | --- | --- | --- | --- |
| ROOT/MAIN-1/2 | 双项目 ownership | architecture | P1 | 只读文件树，不含 secrets | TDD-01 |
| MAIN-3/BRANCH-2 | 外部 image 缺失/提供 | deployment contract | P1 | 虚构 immutable image ref | TDD-02 |
| BRANCH-1 | 双向 import 与测试归属 | negative/static | P1 | 源文件列表 | TDD-03 |
| MAIN-4 | active docs 和历史边界 | documentation | P2 | 当前仓库路径 | TDD-04 |

## 12. ADR 判断

| 项 | 内容 |
| --- | --- |
| 是否需要 ADR | 是 |
| 判断理由 | 项目与发布所有权拆分难逆、缺少上下文会重新引入 build coupling，且 snapshot/submodule/monorepo 存在真实取舍 |
| 涉及决策点 | KSS 独立项目；ProofAgent 只消费外部工件和 HTTPS API；本地 integration harness 不是所有权回退 |

## 13. 知识沉淀与上下文更新

| 目标文档 | 更新类型 | 内容摘要 | 处理方式 | 确认状态 |
| --- | --- | --- | --- | --- |
| `docs/adr/0239-*` | 新 ADR | 物理项目与发布 ownership | 本轮创建 | 用户已选 hard split；发布仍未批准 |
| `docs/PROJ_CONTEXT.md` | current truth | 移除根 package 事实，增加外部项目边界 | TDD-04 更新 | 待实现证据 |
| `docs/DOMAIN_KNOWLEDGE.md` | decision index | 索引 ADR-0239 | TDD-04 更新 | 待实现证据 |
| active docs | contract/development | 外部 artifact 与本地 integration 说明 | TDD-04 更新 | 待实现证据 |
