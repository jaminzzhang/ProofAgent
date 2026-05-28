import { describe, expect, it } from 'vitest'
import { updateAgentYamlField } from './agentYaml'

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
})
