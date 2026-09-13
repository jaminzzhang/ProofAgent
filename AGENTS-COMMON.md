# Proof Agent Coding-Agent Guide

Read this file before repository-specific entry points such as `AGENTS.md`.

## Reasoning and claims

Act as a senior engineer, security reviewer and product skeptic. Do not agree merely because a user proposes a solution. Check repository evidence, identify tradeoffs and say when a requested design would weaken the Control Envelope.

For substantive architecture, security, readiness and status claims, prefix the claim with one source tag and one confidence tag:

- source: `KNOWN` (direct repository/runtime evidence), `COMPUTED` (derived from evidence), `INFERRED` (reasoned but not directly proved), `COMMON` (stable engineering knowledge), `FRAME` (approved design/decision), `GUESS` (weak hypothesis);
- confidence: `HIGH`, `MED`, `LOW`.

Example: `[KNOWN | HIGH] The active workflow registry exposes only react_enterprise_qa_v3.`

State uncertainty and missing evidence. Cite repository paths, commands, tests, commits or dated design records close to the claim. Never present a plan as implemented or a green local test suite as production release proof.

## Product goals and design acceptance

[FRAME | HIGH] ProofAgent 的核心目标：让 Agent 围绕明确的业务目标，在可配置的自主程度、
证据要求和资源预算内，持续完成检索、分析、计算与交付，并用可追溯证据说明完成了什么、
还有什么没有完成。以下是设计开发目标，不是当前能力或生产就绪声明；实际执行范围仍受下方产品边界约束。

设计、实现与评审应围绕五项目标：

1. **理解并保留任务**：保留原始问题、对象、期间、子问题、约束、验收项与版本。
   推断范围须披露，不能伪装成用户要求；修改、长对话与恢复不得静默丢失约束。
2. **准确且完整地交付**：必要资料须查询并准入；答案逐项回应问题，分析由事实支持，
   保留条件、单位、比较口径和相关反面证据。有引用、检索成功或指标罗列都不等于完成业务目标。
3. **自主推进并适时问询**：可检索事实先查，可选偏好合理默认；缺少必要上下文时问询或保留缺口。
   人工确认不替代外部事实证据、工具授权或完成校验。
4. **按要求控制执行**：问询力度、证据要求、流程复杂度与模型 effort 分别配置。
   简化只裁剪可选工作；保留必需验收、权限与证据门禁。恢复、修复和目标修订不重置累计预算。
5. **证明结果与过程**：模型提议，Control Plane 执行和验收；工具交付绑定已验证结果。
   Trace、Receipt 和用户可见状态应一致反映完成、缺口、暂停或失败，且遵守数据与受众边界。

业务任务成功要求：必需目标满足、关键事实有依据、结果覆盖问题、执行符合权限和预算、
验证证据可追溯。未知或未评估项不得算作通过；正确拒绝可通过相应测试，但不是业务交付完成。

每项行为变更应指出所服务的目标，并将“用户要求 → 必需证据/工具结果 → 输出要求 → 验证方法”
连成可检查的链路。针对受影响行为选择成功、失败与边界对照；涉及 UI 时验证实际入口、
保存/重载与执行一致性，保留完整流程及恢复回路。实现细节和测试数量不能替代业务验收。
按 [业务任务验证模板](docs/testing/business-task-verification-template.zh-CN.md) 编写具体案例；
按改动范围选择验证，不为纯文档或低影响改动机械补齐整套用例。

真实业务质量应使用独立标注、未参与调试的任务验证，并分别报告质量评估覆盖、完整正确、
错误完成、澄清、拒绝、恢复和成本。固定合成回归、真实模型质量、部署验证与正式发布证据
分别报告；不将 GRR、来源支持或模型 confidence 当作通用正确率。
未来外部业务写入须另行设计和验证授权、幂等与结果核对；本目标不开放当前生产写工具或脚本执行。

[FRAME | HIGH] 回答与 Prompt 变更遵循 [ADR-0260](docs/adr/0260-synthesize-answers-with-bound-source-quotes.md)：
允许 LLM 总结、合并、改写及解释表格；回答须展示绑定 Accepted Evidence 的引用原文。
Control 检查原文绑定并执行有界模型复核；复核是语义评估，不是确定性证明，不能自动满足 Task。
不得把正常生成或修复降级为逐句摘录；保留事实条件、问题覆盖、权限与累计预算。

[FRAME | HIGH] 混合问题遵循 [ADR-0261](docs/adr/0261-answer-independent-parts-before-personal-clarification.md)：
先交付可独立回答的有据部分，再主动询问剩余个人信息；自主模式也可在答案中提问。
部分交付不算 Task 完成；身份、权限、对象与工具输入等硬性前提不得因部分回答而绕过。

## Active product boundary

- only `react_enterprise_qa_v3` is active;
- only `examples/agent_management_insurance_specialist/` is public;
- only Dashboard and Operator Chat (`/operator`) are active browser surfaces;
- no customer Chat/handoff product and no approval workflow;
- no local accounts, passwords, user directory or user-management page;
- production identity target is OIDC-only with a seven-day backend session and server-side permissions;
- no active `proof_agent/runtime/` compatibility package;
- no package-local Python handlers, MCP stdio tools or state-changing production tools;
- arbitrary scripts/commands belong only in a future separately isolated sandbox.

Historical ADRs and dated specs may describe removed capabilities. Active truth is README, `docs/prd.md`, `docs/technical-design.md`, `docs/developer-guide.md` and `docs/development-progress.md`.

## Architecture invariants

- Control Plane owns workflow, policy, evidence admission, validation and outcome mapping.
- Models, knowledge, memory and tools are capabilities behind provider-neutral ports.
- ADR-0242 supersedes KSS-only runtime rules: external Knowledge bindings are configured
  in Agent manifests; Dify and Agentset are supported read-only adapters (ADR-0249). KSS contracts are historical only.
- External providers return candidates; ProofAgent owns admission and required-query
  completion. Dataset IDs are mutable remote identities, not immutable KSS Releases.
- Default API/Executor/readiness/deployment must not require KSS. External production
  publication remains closed until its own profile and verification are delivered.
  Configuration and limits: `docs/features/external-knowledge/configuration.md`.
- The model proposes; it never grants itself permission or executes a capability directly.
- Memory and conversation context are not Accepted Evidence.
- Tools enter only through Tool Gateway; initial-production tools are read-only, published, schema-bounded and server-authorized.
- Trace is the execution fact log; Governance Receipt is a projection.
- Audit/read models do not become execution authority.
- Third-party SDK objects and secrets do not leak into public contracts or trace.
- Raw chain-of-thought is never stored or returned.
- Configuration may reference environment variable names, secret handles, or a
  configured encrypted-credential marker, never secret values. Production model API
  keys live only as authenticated ciphertext in the separate PostgreSQL credential
  table; its keyring remains outside PostgreSQL.

## Production boundary

S0 local files are development adapters. Production requires:

- PostgreSQL authority for mutable state and queue/coordination;
- OIDC-only sessions, CSRF and permission mappings;
- encrypted PostgreSQL model credentials with an external keyring, Secret Handles
  for other production credentials, and default-deny egress;
- S3-compatible immutable artifacts with S3-first verification and one PostgreSQL visibility transaction;
- a bounded PostgreSQL queue and same-image Run Executor role;
- coarse SSE progress with durable current-state reconnect;
- hardened Compose/Blue-Green deployment and all five top-level release Gates,
  covering the 13 required release-check families.

Do not add filesystem or local-identity fallbacks in production mode. Dependency failure must fail closed.

## Repository layout

```text
proof_agent/contracts/       provider-neutral contracts
proof_agent/bootstrap/       config and composition
proof_agent/control/         workflow, policy, knowledge and validators
proof_agent/capabilities/    concrete adapters
proof_agent/delivery/        CLI and APIs
proof_agent/observability/   trace, receipt, stores and read APIs
proof_agent/release/         release contracts and verifier
dashboard/                   operator configuration/observation UI
chat/                        Operator Chat UI
examples/agent_management_insurance_specialist/
tests/                       backend tests
docs/                        active docs plus historical records
```

## Commands

Install:

```bash
uv sync --extra dev --extra dashboard
npm install
```

Canonical smoke run:

```bash
uv run --extra dev proof-agent run \
  examples/agent_management_insurance_specialist/agent.yaml \
  --question "住院理赔需要准备哪些材料？"
```

Local services:

```bash
uv run --extra dev --extra dashboard proof-agent dev
uv run --extra dev --extra dashboard proof-agent verify-remote
```

`verify-remote` is local-only. Dashboard defaults to port 5173, Operator Chat to 5174, API to 8000 and the integrated gateway to 18080.

Full verification:

```bash
uv lock --check
uv run --extra dev python -m pytest tests/ -q
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai mypy proof_agent
npm run typecheck
npm test
npm run build
python3 scripts/check-domain-contexts.py
git diff --check
```

Run the smallest relevant test first while developing, then the full affected suite. Socket-bound HTTP tests must run in an environment that permits loopback binding before release evidence is signed.

## Change rules

- Use test-first changes for behavior and regressions.
- Preserve user changes and unrelated dirty-worktree content.
- Use `rg` for repository searches.
- Update active documentation in the same change as behavior.
- Do not silently retain deprecated config fields; strict contracts should reject them.
- Do not create alternate execution paths in API, frontend, evaluation or observability code.
- Do not weaken deterministic gates because an LLM or human judge is favorable.
- New trace fields require redaction and audience review.
- New storage requires ownership, transaction, concurrency, retention and recovery semantics.
- New network integrations require an explicit allowlist and secret-handle boundary.
- New script/command execution requires the separate sandbox design; never smuggle it through tools or workers.

## Review priorities

Prioritize:

1. authority or trust-boundary bypass;
2. loss of fail-closed behavior;
3. secret, identity, tenant or artifact leakage;
4. concurrency/idempotency/fencing errors;
5. evidence/citation correctness;
6. release binding or freshness errors;
7. product-surface regression and documentation drift.

Report findings with concrete file/line evidence and severity. Distinguish defects from intentional scope decisions and from future work.
