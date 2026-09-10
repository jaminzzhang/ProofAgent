// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ModuleEditor } from '../../agent/ModuleEditor'
import { MEMORY_FIELDS } from '../../agent/module-configs/memory'
import { RESPONSE_FIELDS } from '../../agent/module-configs/response'

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
  it('shows the default clarification level and sends the selected contract value', () => {
    const change = vi.fn()
    const save = vi.fn()
    const { rerender } = render(<ModuleEditor title="响应配置" fields={RESPONSE_FIELDS}
      yamlSection="response" agentYaml={AGENT_YAML} onFieldChange={change}
      onSave={save} busy={false} />)
    expect(screen.getByLabelText('澄清程度')).toHaveDisplayValue('均衡（默认）')
    fireEvent.change(screen.getByLabelText('澄清程度'), { target: { value: 'minimal' } })
    expect(change).toHaveBeenCalledWith(['response', 'clarification_level'], 'minimal')
    rerender(<ModuleEditor title="响应配置" fields={RESPONSE_FIELDS}
      yamlSection="response" agentYaml={`${AGENT_YAML}\nresponse:\n  clarification_level: minimal\n`}
      onFieldChange={change} onSave={save} busy={false} />)
    expect(screen.getByLabelText('澄清程度')).toHaveDisplayValue('少澄清')
    fireEvent.click(screen.getByRole('button', { name: /save|保存/i }))
    expect(save).toHaveBeenCalledOnce()
  })
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
