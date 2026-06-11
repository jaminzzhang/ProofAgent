# Institution Insurance Specialist Agent

This Agent Package demonstrates an institution-facing insurance specialist, not
a customer-facing service bot.

It uses the shared `react_enterprise_qa` Workflow Template with node Prompt
configuration for assisted insurance operations. The package is generic across
insurance business lines; the bundled fixture scopes the example to
short-term accident insurance through knowledge bindings and read-only
institution tools.

Key boundaries:

- staff-facing Assisted Service Mode.
- no `customer.adapter`, `customers.yaml`, or customer journey suite.
- read-only institution tools only.
- short-term insurance is a package scope, not a Harness workflow fork.
- current-case memory only.

Try a local run:

```bash
uv run --extra dev proof-agent run examples/institution_insurance_specialist/agent.yaml \
  --question "For short-term accident claims, what should a branch specialist explain to an agent when the claim is still pending?"
```
