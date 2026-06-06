// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { SharedModelConnection } from '../../../api/types'
import { ModelModuleEditor } from '../../agent/ModelModuleEditor'

const AGENT_YAML = `name: enterprise_qa
model:
  provider: deepseek
  name: deepseek-chat
  params:
    temperature: 0
    max_output_tokens: 800
react:
  max_steps: 5
  max_tool_calls: 2
  record_reasoning_summary: true
  planner:
    provider: deepseek
    name: deepseek-chat
    params:
      temperature: 0
review:
  mode: auto
  subagent:
    provider: deepseek
    name: deepseek-chat
    fail_closed: true
    params:
      temperature: 0
      max_output_tokens: 500
      timeout_seconds: 5
`

describe('ModelModuleEditor', () => {
  it('selects a shared model connection for the answer role', () => {
    const onModelConfigChange = vi.fn()

    render(
      <ModelModuleEditor
        agentYaml={AGENT_YAML}
        modelConnections={[
          modelConnection({
            connection_id: 'model_deepseek_default',
            display_name: 'DeepSeek Default',
          }),
        ]}
        onFieldChange={vi.fn()}
        onModelConfigChange={onModelConfigChange}
        onSave={vi.fn()}
        busy={false}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Role-Specific' }))
    fireEvent.change(screen.getByLabelText('Answer Model Source'), {
      target: { value: 'shared:model_deepseek_default' },
    })

    expect(onModelConfigChange).toHaveBeenCalledWith(['model'], {
      model_source: 'shared',
      connection_id: 'model_deepseek_default',
      params: {
        temperature: '0',
        max_output_tokens: '800',
      },
    })
  })

  it('selects custom model configuration for the planner role', () => {
    const onModelConfigChange = vi.fn()

    render(
      <ModelModuleEditor
        agentYaml={AGENT_YAML}
        modelConnections={[modelConnection()]}
        onFieldChange={vi.fn()}
        onModelConfigChange={onModelConfigChange}
        onSave={vi.fn()}
        busy={false}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Role-Specific' }))
    fireEvent.change(screen.getByLabelText('Planner Model Source'), {
      target: { value: 'custom' },
    })

    expect(onModelConfigChange).toHaveBeenCalledWith(['react', 'planner'], {
      model_source: 'custom',
      provider: 'deepseek',
      name: 'deepseek-chat',
      credential_ref: {
        type: 'env',
        name: '',
      },
      params: {
        temperature: '0',
      },
    })
  })

  it('writes reviewer usage controls under review.subagent.params', () => {
    const onFieldChange = vi.fn()

    render(
      <ModelModuleEditor
        agentYaml={AGENT_YAML}
        modelConnections={[modelConnection()]}
        onFieldChange={onFieldChange}
        onModelConfigChange={vi.fn()}
        onSave={vi.fn()}
        busy={false}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Role-Specific' }))
    fireEvent.change(screen.getByLabelText('Reviewer Max Output Tokens'), {
      target: { value: '700' },
    })
    fireEvent.change(screen.getByLabelText('Reviewer Timeout (s)'), {
      target: { value: '8' },
    })

    expect(onFieldChange).toHaveBeenCalledWith(
      ['review', 'subagent', 'params', 'max_output_tokens'],
      '700',
    )
    expect(onFieldChange).toHaveBeenCalledWith(
      ['review', 'subagent', 'params', 'timeout_seconds'],
      '8',
    )
  })

  it('applies unified shared model selection to answer planner and reviewer', () => {
    const onModelConfigChange = vi.fn()

    render(
      <ModelModuleEditor
        agentYaml={AGENT_YAML}
        modelConnections={[
          modelConnection({
            connection_id: 'model_deepseek_default',
            display_name: 'DeepSeek Default',
          }),
        ]}
        onFieldChange={vi.fn()}
        onModelConfigChange={onModelConfigChange}
        onSave={vi.fn()}
        busy={false}
      />,
    )

    fireEvent.change(screen.getByLabelText('Primary Model Source'), {
      target: { value: 'shared:model_deepseek_default' },
    })

    expect(onModelConfigChange).toHaveBeenCalledWith(
      ['model'],
      expect.objectContaining({
        model_source: 'shared',
        connection_id: 'model_deepseek_default',
      }),
    )
    expect(onModelConfigChange).toHaveBeenCalledWith(
      ['react', 'planner'],
      expect.objectContaining({
        model_source: 'shared',
        connection_id: 'model_deepseek_default',
      }),
    )
    expect(onModelConfigChange).toHaveBeenCalledWith(
      ['review', 'subagent'],
      expect.objectContaining({
        model_source: 'shared',
        connection_id: 'model_deepseek_default',
        fail_closed: 'true',
      }),
    )
  })

  it('shows an archived warning for an existing shared model reference', () => {
    render(
      <ModelModuleEditor
        agentYaml={`name: enterprise_qa
model:
  model_source: shared
  connection_id: model_archived
react:
  planner:
    provider: deepseek
    name: deepseek-chat
review:
  subagent:
    provider: deepseek
    name: deepseek-chat
    fail_closed: true
`}
        modelConnections={[
          modelConnection({
            connection_id: 'model_archived',
            display_name: 'Archived DeepSeek',
            lifecycle_state: 'ARCHIVED',
          }),
          modelConnection({
            connection_id: 'model_active',
            display_name: 'Active DeepSeek',
            lifecycle_state: 'ACTIVE',
          }),
        ]}
        onFieldChange={vi.fn()}
        onModelConfigChange={vi.fn()}
        onSave={vi.fn()}
        busy={false}
      />,
    )

    expect(screen.getByLabelText('Primary Model Source')).toHaveValue('shared:model_archived')
    expect(screen.getByText('Archived connection is already referenced.')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Active DeepSeek' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Archived DeepSeek (archived)' })).toBeInTheDocument()
  })
})

function modelConnection(overrides: Partial<SharedModelConnection> = {}): SharedModelConnection {
  return {
    connection_id: 'model_deepseek_default',
    display_name: 'DeepSeek Default',
    description: '',
    tags: [],
    provider: 'deepseek',
    model_identifier: 'deepseek-chat',
    base_url: 'https://api.deepseek.com',
    credential_ref: { type: 'env', name: 'DEEPSEEK_API_KEY' },
    organization_env: null,
    project_env: null,
    timeout_seconds: 20,
    lifecycle_state: 'ACTIVE',
    created_at: '2026-06-07T00:00:00Z',
    updated_at: '2026-06-07T00:00:00Z',
    reference_summary: {
      connection_id: 'model_deepseek_default',
      draft_agent_reference_count: 0,
      published_agent_version_reference_count: 0,
      knowledge_source_reference_count: 0,
      in_flight_operation_count: 0,
      audit_retention_blocked: false,
    },
    last_validation: null,
    last_smoke_test: null,
    ...overrides,
  }
}
