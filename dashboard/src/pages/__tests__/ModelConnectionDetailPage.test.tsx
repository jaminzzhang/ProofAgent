// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  archiveModelConnection,
  deleteModelConnection,
  fetchModelConnection,
  fetchModelConnectionDeletionEligibility,
  fetchModelConnectionReferences,
  restoreModelConnection,
  smokeTestModelConnection,
  updateModelConnection,
  validateModelConnection,
} from '../../api/client'
import type { SharedModelConnection } from '../../api/types'
import { ModelConnectionDetailPage } from '../ModelConnectionDetailPage'

vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {
    readonly status: number
    readonly statusText: string
    readonly detail: unknown

    constructor(status: number, statusText: string, bodyText: string, detail: unknown) {
      super(`API error: ${status} ${statusText} ${bodyText}`)
      this.name = 'ApiError'
      this.status = status
      this.statusText = statusText
      this.detail = detail
    }
  },
  archiveModelConnection: vi.fn(),
  deleteModelConnection: vi.fn(),
  fetchModelConnection: vi.fn(),
  fetchModelConnectionDeletionEligibility: vi.fn(),
  fetchModelConnectionReferences: vi.fn(),
  restoreModelConnection: vi.fn(),
  smokeTestModelConnection: vi.fn(),
  updateModelConnection: vi.fn(),
  validateModelConnection: vi.fn(),
}))

function renderPage(path = '/models/model_deepseek_default') {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/models/:connectionId" element={<ModelConnectionDetailPage />} />
        <Route path="/models" element={<div>Models list</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ModelConnectionDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchModelConnection).mockResolvedValue(modelConnection())
    vi.mocked(fetchModelConnectionReferences).mockResolvedValue(modelConnection().reference_summary)
    vi.mocked(fetchModelConnectionDeletionEligibility).mockResolvedValue({
      connection_id: 'model_deepseek_default',
      eligible: false,
      lifecycle_state: 'ACTIVE',
      reference_summary: modelConnection().reference_summary,
      blockers: ['connection_not_archived'],
    })
    vi.mocked(updateModelConnection).mockResolvedValue(
      modelConnection({ display_name: 'DeepSeek Production' }),
    )
    vi.mocked(archiveModelConnection).mockResolvedValue(
      modelConnection({ lifecycle_state: 'ARCHIVED' }),
    )
    vi.mocked(restoreModelConnection).mockResolvedValue(modelConnection())
    vi.mocked(deleteModelConnection).mockResolvedValue({
      connection_id: 'model_deepseek_default',
      eligible: true,
      lifecycle_state: 'ARCHIVED',
      reference_summary: modelConnection().reference_summary,
      blockers: [],
    })
    vi.mocked(validateModelConnection).mockResolvedValue({
      validation_id: 'modelvalidation_1',
      connection_id: 'model_deepseek_default',
      status: 'passed',
      created_at: '2026-06-07T00:00:00Z',
      created_by: 'dashboard',
      provider: 'deepseek',
      model_identifier: 'deepseek-chat',
      credential_ref: { type: 'env', name: 'DEEPSEEK_API_KEY' },
      checked_env_vars: ['DEEPSEEK_API_KEY'],
      missing_env_vars: [],
      error_code: null,
      message: 'Model connection validation passed.',
    })
    vi.mocked(smokeTestModelConnection).mockResolvedValue({
      smoke_test_id: 'modelsmoke_1',
      connection_id: 'model_deepseek_default',
      status: 'skipped',
      created_at: '2026-06-07T00:00:00Z',
      created_by: 'dashboard',
      provider: 'deepseek',
      model_identifier: 'deepseek-chat',
      credential_ref: { type: 'env', name: 'DEEPSEEK_API_KEY' },
      request_sent: false,
      error_code: null,
      message: 'Smoke test skipped.',
    })
  })

  it('renders overview and saves high-impact updates with confirmation', async () => {
    renderPage()

    expect(await screen.findByText('DeepSeek Default')).toBeInTheDocument()
    expect(screen.getByText('model_deepseek_default')).toBeInTheDocument()
    expect(screen.getByText('api.deepseek.com')).toBeInTheDocument()
    expect(screen.getByText('DEEPSEEK_API_KEY')).toBeInTheDocument()
    expect(screen.queryByText('test-key')).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Display Name'), {
      target: { value: 'DeepSeek Production' },
    })
    fireEvent.change(screen.getByLabelText('Model Identifier'), {
      target: { value: 'deepseek-reasoner' },
    })
    fireEvent.click(screen.getByLabelText('Confirm Impact'))
    fireEvent.click(screen.getByRole('button', { name: 'Save Overview' }))

    await waitFor(() => {
      expect(updateModelConnection).toHaveBeenCalledWith('model_deepseek_default', {
        display_name: 'DeepSeek Production',
        description: '',
        tags: [],
        provider: 'deepseek',
        model_identifier: 'deepseek-reasoner',
        base_url: 'https://api.deepseek.com',
        credential_ref: { type: 'env', name: 'DEEPSEEK_API_KEY' },
        organization_env: null,
        project_env: null,
        timeout_seconds: 20,
        confirm_impact: true,
      })
    })
  })

  it('turns model impact conflicts into an explicit confirmation review', async () => {
    vi.mocked(updateModelConnection)
      .mockRejectedValueOnce(
        new ApiError(
          409,
          'Conflict',
          '{"detail":{"requires_impact_review":true}}',
          {
            requires_impact_review: true,
            changed_fields: ['provider', 'model_identifier', 'base_url', 'credential_ref'],
            reference_summary: {
              connection_id: 'model_deepseek_default',
              draft_agent_reference_count: 6,
              published_agent_version_reference_count: 2,
              knowledge_source_reference_count: 2,
              in_flight_operation_count: 0,
              audit_retention_blocked: false,
            },
          },
        ),
      )
      .mockResolvedValueOnce(modelConnection({ model_identifier: 'deepseek-reasoner' }))

    renderPage()

    expect(await screen.findByText('DeepSeek Default')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Model Identifier'), {
      target: { value: 'deepseek-reasoner' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save Overview' }))

    expect(await screen.findByText('Impact review required')).toBeInTheDocument()
    expect(screen.getByText('provider, model_identifier, base_url, credential_ref')).toBeInTheDocument()
    expect(screen.getByText('6')).toBeInTheDocument()
    expect(screen.getAllByText('2')).toHaveLength(2)
    expect(screen.queryByText(/API error: 409/)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Confirm Impact and Save' }))

    await waitFor(() => {
      expect(updateModelConnection).toHaveBeenLastCalledWith('model_deepseek_default', expect.objectContaining({
        model_identifier: 'deepseek-reasoner',
        confirm_impact: true,
      }))
    })
    expect(await screen.findByText('Model connection saved.')).toBeInTheDocument()
  })

  it('shows references and runs validation and smoke actions', async () => {
    renderPage()

    expect(await screen.findByText('DeepSeek Default')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'References' }))
    expect(screen.getByText('Draft Agents')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('Knowledge Sources')).toBeInTheDocument()
    expect(fetchModelConnectionReferences).toHaveBeenCalledWith('model_deepseek_default')

    fireEvent.click(screen.getByRole('button', { name: 'Test' }))
    fireEvent.click(screen.getByRole('button', { name: 'Validate' }))
    await waitFor(() => {
      expect(validateModelConnection).toHaveBeenCalledWith('model_deepseek_default')
    })
    expect(await screen.findByText('Validation modelvalidation_1 passed.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Smoke Test' }))
    await waitFor(() => {
      expect(smokeTestModelConnection).toHaveBeenCalledWith('model_deepseek_default')
    })
    expect(await screen.findByText('Smoke test modelsmoke_1 skipped.')).toBeInTheDocument()
  })

  it('archives restores and deletes eligible archived connections', async () => {
    vi.mocked(fetchModelConnection).mockResolvedValue(
      modelConnection({ lifecycle_state: 'ARCHIVED' }),
    )
    vi.mocked(fetchModelConnectionDeletionEligibility).mockResolvedValue({
      connection_id: 'model_deepseek_default',
      eligible: true,
      lifecycle_state: 'ARCHIVED',
      reference_summary: modelConnection().reference_summary,
      blockers: [],
    })

    renderPage()

    expect(await screen.findByText('DeepSeek Default')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Restore Reason'), { target: { value: 'Reopen' } })
    fireEvent.click(screen.getByRole('button', { name: 'Restore' }))
    await waitFor(() => {
      expect(restoreModelConnection).toHaveBeenCalledWith('model_deepseek_default', {
        reason: 'Reopen',
      })
    })

    fireEvent.change(screen.getByLabelText('Delete Reason'), { target: { value: 'No references' } })
    fireEvent.click(screen.getByRole('button', { name: 'Delete Permanently' }))
    await waitFor(() => {
      expect(deleteModelConnection).toHaveBeenCalledWith('model_deepseek_default', {
        reason: 'No references',
      })
    })
    expect(await screen.findByText('Models list')).toBeInTheDocument()
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
      draft_agent_reference_count: 2,
      published_agent_version_reference_count: 1,
      knowledge_source_reference_count: 1,
      in_flight_operation_count: 0,
      audit_retention_blocked: false,
    },
    last_validation: null,
    last_smoke_test: null,
    ...overrides,
  }
}
