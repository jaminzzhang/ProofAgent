// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ModuleEditor } from '../../agent/ModuleEditor'
import { MEMORY_FIELDS } from '../../agent/module-configs/memory'

const AGENT_YAML = `name: insurance_customer_service
purpose: "Provide customer service."

capabilities:
  memory:
    enabled: true
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

describe('ModuleEditor', () => {
  it('reads deeply nested memory scope values from agent YAML', () => {
    render(
      <ModuleEditor
        title="Memory Configuration"
        fields={MEMORY_FIELDS}
        yamlSection="capabilities"
        agentYaml={AGENT_YAML}
        onFieldChange={vi.fn()}
        onSave={vi.fn()}
        busy={false}
      />,
    )

    expect(screen.getByLabelText('Case Retention (days)')).toHaveDisplayValue('30')
    expect(screen.getByLabelText('Case Allow Restricted')).toHaveValue('false')
  })

  it('explains each setting with purpose and YAML path', () => {
    render(
      <ModuleEditor
        title="Memory Configuration"
        description="Memory controls"
        fields={MEMORY_FIELDS}
        yamlSection="capabilities"
        agentYaml={AGENT_YAML}
        onFieldChange={vi.fn()}
        onSave={vi.fn()}
        busy={false}
      />,
    )

    expect(screen.getByText('Memory controls')).toBeInTheDocument()
    expect(screen.getByText('Controls where admitted memory records are stored between runs.')).toBeInTheDocument()
    expect(screen.getByText('capabilities.memory.provider')).toBeInTheDocument()
    expect(screen.getByText('capabilities.memory.scopes.case.retention_days')).toBeInTheDocument()
  })
})
