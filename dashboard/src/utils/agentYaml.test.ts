import { describe, expect, it } from 'vitest'
import { replaceAgentYamlMapping, updateAgentYamlField } from './agentYaml'

const AGENT_YAML = `name: insurance_customer_service
purpose: "Provide customer service."

memory:
  provider: local
  scopes:
    case:
      enabled: true
      retention_days: 30
      max_records: 5
      allow_restricted: false
    user:
      enabled: false
    shared:
      enabled: false
`

describe('agentYaml', () => {
  it('updates deeply nested memory scope scalars', () => {
    const updated = updateAgentYamlField(
      AGENT_YAML,
      ['memory', 'scopes', 'case', 'retention_days'],
      '45',
    )

    expect(updated).toContain('      retention_days: 45')
    expect(updated).toContain('      max_records: 5')
  })

  it('inserts missing nested model params under an existing parent section', () => {
    const updated = updateAgentYamlField(
      `name: model_test
model:
  provider: deepseek
  name: deepseek-v4-flash
policy:
  file: ./policy.yaml
`,
      ['model', 'params', 'api_key_env'],
      'DEEPSEEK_API_KEY',
    )

    expect(updated).toContain(`model:
  provider: deepseek
  name: deepseek-v4-flash
  params:
    api_key_env: DEEPSEEK_API_KEY
policy:`)
  })

  it('replaces one mapping block without preserving stale sibling keys', () => {
    const updated = replaceAgentYamlMapping(
      `name: model_test
model:
  provider: deepseek
  name: deepseek-chat
  params:
    temperature: 0
    timeout_seconds: 30
policy:
  file: ./policy.yaml
`,
      ['model'],
      {
        model_source: 'shared',
        connection_id: 'model_deepseek_default',
        params: {
          temperature: '0',
          timeout_seconds: '5',
        },
      },
    )

    expect(updated).toContain(`model:
  model_source: shared
  connection_id: model_deepseek_default
  params:
    temperature: 0
    timeout_seconds: 5
policy:`)
    expect(updated).not.toContain('provider: deepseek')
    expect(updated).not.toContain('name: deepseek-chat')
  })
})
