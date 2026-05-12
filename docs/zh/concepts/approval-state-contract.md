# Approval State Contract (审批状态合约)

工具审批是一种工作流状态，而不是隐藏的回调函数。

确定性演示使用一个 MCP mock 工具来证明审批模型。审批合约必须足够明确以支持对 requested（请求）、granted（授权）、denied（拒绝）以及 timed-out（超时）这些路径的测试，并且在引入真实的 MCP 适配器时，它必须保持不变。

## 审批 ID

每个审批请求包含：

```text
run_id
approval_id
tool_name
requested_at
expires_at
state
reason
trace_event_id
```

`approval_id` 在单次运行中是唯一的，并会出现在 trace 事件、CLI 输出以及 Governance Receipt 中。

## 状态机 (State Machine)

```text
requested
  | grant
  v
granted -> tool_result

requested
  | deny
  v
denied -> safe terminal response

requested
  | timeout
  v
timed_out -> safe terminal response
```

## CLI 体验 (CLI UX)

CLI 默认使用内联审批：

```text
Approval required: customer_lookup
Reason: Policy rule tools.customer_lookup.approval requires human approval.
Approval ID: appr_0001

Approve tool call? [y/N]
```

接受的输入：

- `y` 或 `yes` -> `approval_granted`
- `n`、`no` 或留空 -> `approval_denied`
- 在超时前无响应 -> `approval_timeout`

## 可选的恢复形式 (Optional Resume Shape)

当前公共路径为内联审批。未来的 Dashboard 或恢复 API 可以重用相同的 id：

```bash
proof-agent approve <run_id> <approval_id>
proof-agent deny <run_id> <approval_id>
```

如果不需要非交互式的审批，v1 暂不需要这些命令。

## Trace 要求

审批状态必须发出以下事件：

- `approval_requested`
- 有且只有一个终态审批事件：`approval_granted`、`approval_denied` 或 `approval_timeout`
- `tool_result` 仅在 `approval_granted` 之后发出
- `final_output` 在拒绝或超时后发出

## Receipt 要求

Governance Receipt 必须包含：

- 审批 ID (approval id)
- 工具名称 (tool name)
- 最终审批状态 (final approval state)
- 原因 (reason)
- 请求和终态决策的 trace 事件 ID