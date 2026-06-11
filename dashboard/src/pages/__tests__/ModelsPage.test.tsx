// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createModelConnection, fetchModelConnections } from '../../api/client'
import type { SharedModelConnection } from '../../api/types'
import { Sidebar } from '../../components/Sidebar'
import { ModelsPage } from '../ModelsPage'

vi.mock('../../api/client', () => ({
  createModelConnection: vi.fn(),
  fetchModelConnections: vi.fn(),
}))

describe('ModelsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('adds Models to the Configuration navigation', () => {
    render(
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>,
    )

    const link = screen.getByRole('link', { name: /Models/i })
    expect(link).toHaveAttribute('href', '/models')
  })

  it('lists shared model connections with operational status fields', async () => {
    vi.mocked(fetchModelConnections).mockResolvedValue({
      data: [
        modelConnection({
          connection_id: 'model_deepseek_default',
          display_name: 'DeepSeek Default',
          provider: 'deepseek',
          model_identifier: 'deepseek-chat',
          base_url: 'https://api.deepseek.com',
          credential_ref: { type: 'env', name: 'DEEPSEEK_API_KEY' },
          reference_summary: {
            connection_id: 'model_deepseek_default',
            draft_agent_reference_count: 1,
            published_agent_version_reference_count: 2,
            knowledge_source_reference_count: 1,
            in_flight_operation_count: 0,
            audit_retention_blocked: false,
          },
          last_smoke_test: {
            smoke_test_id: 'modelsmoke_1',
            connection_id: 'model_deepseek_default',
            status: 'passed',
            created_at: '2026-06-07T00:00:00Z',
            created_by: 'dashboard',
            provider: 'deepseek',
            model_identifier: 'deepseek-chat',
            credential_ref: { type: 'env', name: 'DEEPSEEK_API_KEY' },
            request_sent: true,
            error_code: null,
            message: 'ok',
          },
        }),
        modelConnection({
          connection_id: 'model_archived',
          display_name: 'Archived OpenAI',
          provider: 'openai',
          model_identifier: 'gpt-4.1-mini',
          lifecycle_state: 'ARCHIVED',
          credential_ref: { type: 'env', name: 'OPENAI_API_KEY' },
        }),
      ],
      meta: { total: 2 },
    })

    render(
      <MemoryRouter>
        <ModelsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('DeepSeek Default')).toBeInTheDocument()
    expect(screen.getByText('model_deepseek_default')).toBeInTheDocument()
    expect(screen.getByText('deepseek')).toBeInTheDocument()
    expect(screen.getByText('deepseek-chat')).toBeInTheDocument()
    expect(screen.getByText('api.deepseek.com')).toBeInTheDocument()
    expect(screen.getByText('DEEPSEEK_API_KEY')).toBeInTheDocument()
    expect(screen.getByText('4 refs')).toBeInTheDocument()
    expect(screen.getByText('smoke passed')).toBeInTheDocument()
    expect(screen.getByText('Archived OpenAI')).toBeInTheDocument()
    expect(screen.getByText('archived')).toBeInTheDocument()
  })

  it('filters by provider lifecycle reference state smoke status and text search', async () => {
    vi.mocked(fetchModelConnections).mockResolvedValue({
      data: [
        modelConnection({
          connection_id: 'model_deepseek_default',
          display_name: 'DeepSeek Default',
          provider: 'deepseek',
          model_identifier: 'deepseek-chat',
          reference_summary: {
            connection_id: 'model_deepseek_default',
            draft_agent_reference_count: 1,
            published_agent_version_reference_count: 0,
            knowledge_source_reference_count: 0,
            in_flight_operation_count: 0,
            audit_retention_blocked: false,
          },
          last_smoke_test: {
            smoke_test_id: 'modelsmoke_1',
            connection_id: 'model_deepseek_default',
            status: 'passed',
            created_at: '2026-06-07T00:00:00Z',
            created_by: 'dashboard',
            provider: 'deepseek',
            model_identifier: 'deepseek-chat',
            credential_ref: { type: 'env', name: 'DEEPSEEK_API_KEY' },
            request_sent: true,
            error_code: null,
            message: 'ok',
          },
        }),
        modelConnection({
          connection_id: 'model_openai_unused',
          display_name: 'OpenAI Unused',
          provider: 'openai',
          model_identifier: 'gpt-4.1-mini',
          credential_ref: { type: 'env', name: 'OPENAI_API_KEY' },
        }),
      ],
      meta: { total: 2 },
    })

    render(
      <MemoryRouter>
        <ModelsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('DeepSeek Default')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Provider Filter'), { target: { value: 'openai' } })
    expect(screen.queryByText('DeepSeek Default')).not.toBeInTheDocument()
    expect(screen.getByText('OpenAI Unused')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Provider Filter'), { target: { value: 'all' } })
    fireEvent.change(screen.getByLabelText('References'), { target: { value: 'referenced' } })
    expect(screen.getByText('DeepSeek Default')).toBeInTheDocument()
    expect(screen.queryByText('OpenAI Unused')).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('References'), { target: { value: 'all' } })
    fireEvent.change(screen.getByLabelText('Smoke'), { target: { value: 'passed' } })
    expect(screen.getByText('DeepSeek Default')).toBeInTheDocument()
    expect(screen.queryByText('OpenAI Unused')).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Smoke'), { target: { value: 'all' } })
    fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'unused' } })
    expect(screen.queryByText('DeepSeek Default')).not.toBeInTheDocument()
    expect(screen.getByText('OpenAI Unused')).toBeInTheDocument()
  })

  it('creates model connections with env credential references', async () => {
    vi.mocked(fetchModelConnections).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(createModelConnection).mockResolvedValue(
      modelConnection({
        connection_id: 'model_deepseek_default',
        display_name: 'DeepSeek Default',
        provider: 'deepseek',
        model_identifier: 'deepseek-chat',
      }),
    )

    render(
      <MemoryRouter>
        <ModelsPage />
      </MemoryRouter>,
    )

    await screen.findByText('Models')
    fireEvent.change(screen.getByLabelText('Display Name'), {
      target: { value: 'DeepSeek Default' },
    })
    fireEvent.change(screen.getByLabelText('Connection ID'), {
      target: { value: 'model_deepseek_default' },
    })
    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'deepseek' } })
    fireEvent.change(screen.getByLabelText('Model Identifier'), {
      target: { value: 'deepseek-chat' },
    })
    fireEvent.change(screen.getByLabelText('Base URL'), {
      target: { value: 'https://api.deepseek.com' },
    })
    fireEvent.change(screen.getByLabelText('Credential Env'), {
      target: { value: 'DEEPSEEK_API_KEY' },
    })
    fireEvent.change(screen.getByLabelText('Timeout Seconds'), { target: { value: '20' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create Model' }))

    await waitFor(() => {
      expect(createModelConnection).toHaveBeenCalledWith({
        connection_id: 'model_deepseek_default',
        display_name: 'DeepSeek Default',
        provider: 'deepseek',
        model_identifier: 'deepseek-chat',
        base_url: 'https://api.deepseek.com',
        credential_ref: { type: 'env', name: 'DEEPSEEK_API_KEY' },
        timeout_seconds: 20,
      })
    })
  })

  it('shows an error state when model connections cannot load', async () => {
    vi.mocked(fetchModelConnections).mockRejectedValue(new Error('network down'))

    render(
      <MemoryRouter>
        <ModelsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Unable to load model connections.')).toBeInTheDocument()
  })
})

function modelConnection(overrides: Partial<SharedModelConnection>): SharedModelConnection {
  return {
    connection_id: 'model_default',
    display_name: 'Default Model',
    description: '',
    tags: [],
    provider: 'deepseek',
    model_identifier: 'deepseek-chat',
    base_url: null,
    credential_ref: { type: 'env', name: 'DEEPSEEK_API_KEY' },
    organization_env: null,
    project_env: null,
    timeout_seconds: null,
    lifecycle_state: 'ACTIVE',
    created_at: '2026-06-07T00:00:00Z',
    updated_at: '2026-06-07T00:00:00Z',
    reference_summary: {
      connection_id: 'model_default',
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
